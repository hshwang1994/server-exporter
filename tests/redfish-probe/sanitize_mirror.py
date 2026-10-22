#!/usr/bin/env python3
"""캡처 미러의 관리 IP 와 호스트 이름을 실제 값이 아닌 대체값으로 일관되게 바꾼 사본을 만든다 (반출용).

왜:
    폐쇄망에서 캡처한 mock 데이터를 밖으로 옮기면 관리 IP 와 호스트 이름이 함께 나간다. null 로 지우면 게더링 코드가
    형식(점 4개의 IPv4, 점으로 이어진 FQDN)을 기대하는 곳에서 어긋나므로, 형식이 유효한 가짜 값으로 바꾼다.
    - 같은 실제 값은 모든 호스트, 모든 파일, 모든 실행에서 같은 가짜 값이 된다 (대응표를 폐쇄망 안에 보관).
    - 같은 /24 에 있던 주소는 같은 가짜 /24 에 남고(게이트웨이가 같은 서브넷), 같은 /16 은 같은 가짜 /16 이다.
    - IPv4 는 사설 대역(10.x, 172.16/12, 192.168/16)으로, 호스트 이름은 host-xxxxxx, 도메인은 dom-xxxx.test 로 바뀐다.

무엇을 바꾸나:
    IPv4 / IPv6 주소, 호스트 이름 / FQDN / 도메인 (HostName 류 키, 서버 주소 키, URL 의 호스트에서 알아낸 것과
    --extra-host / --extra-domain 으로 준 것), 인증서 PEM 본문(안에 CN/SAN 으로 이름이 들어 있음).
    파일과 폴더 이름도 같은 규칙으로 바꾼다.
무엇을 안 바꾸나 (이 도구는 익명화를 보증하지 않는다):
    MAC, 시리얼 번호, 자산 태그, UUID, 계정 이름, 로그 속 사람 이름 등 - 개수만 보고서에 센다. 펌웨어 버전처럼 생긴
    값(Version/Firmware 류 키, 'version 1.2.3.4' 문맥)과 서브넷 마스크, 0.0.0.0, 127.x, 169.254.x, 멀티캐스트는 그대로 둔다.
    바이너리 첨부(raw.bin 등)는 안에 무엇이 있는지 알 수 없어 사본에 넣지 않는다 (--keep-binary 로 포함).

사용 (폐쇄망 안에서, 반출 전에):
    python3 sanitize_mirror.py /home/infraops/mock --out /home/infraops/mock_clean
    python3 sanitize_mirror.py --verify /home/infraops/mock_clean        # 실제 값이 남았는지 다시 검사
    대응표(--map, 기본 ~/.redfish_sanitize_map.json)에는 실제 값이 들어 있다 - 절대 반출하지 말고 사본 폴더 밖에 둔다.

종료코드: 0=성공(누출 0) 1=검증에서 실제 값 또는 의심 값이 남음 2=사용법/입출력 오류
stdlib 전용, Python 3.6+.
"""
import argparse
import collections
import datetime
import hashlib
import hmac
import io
import ipaddress
import json
import os
import re
import sys

TOOL_VERSION = "1.0.0"
MAP_VERSION = 1
DEFAULT_MAP = os.path.join(os.path.expanduser("~"), ".redfish_sanitize_map.json")
FAKE_TLD = "test"                      # RFC 2606 예약 - 절대 해석되지 않는다

_OCT = r"(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])"
# 왼쪽 경계: 단어/점/하이픈 뒤가 아니거나, JSON 이스케이프(\n \t \r) 바로 뒤
_LEFT = r"(?:(?<![\w.-])|(?<=\x5c[ntr]))"
_LEFT6 = r"(?:(?<![\w:.])|(?<=\x5c[ntr]))"
IPV4_RX = re.compile(_LEFT + "(" + _OCT + r"(?:\." + _OCT + r"){3})(?![\w-]|\.[0-9])")
_TOK = re.compile(r'"(?:[^"\x5c]|\x5c.)*"|[{}\[\]:,]', re.S)
PEM_RX = re.compile(r"-----BEGIN ([A-Z0-9 ]+)-----.*?-----END \1-----", re.S)
URL_HOST_RX = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://(?:[^/@\s\"']+@)?(\[[0-9A-Fa-f:.]+\]|[^/:\s\"'?#\x5c]+)")
HOSTNAME_RX = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
MAC_RX = re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])")

# 키 이름으로 값의 성격을 알아내는 규칙
HOST_KEY_END = ("hostname", "fqdn", "dnsname", "domainname", "dnsdomain", "dnsracname", "netbiosname", "machinename")
SERVER_KEY_RX = re.compile(r"(?i)^(ntpservers?|ntpserver\d*|staticnameservers?|dnsservers?|nameservers?|primarydns|"
                           r"secondarydns|syslogservers?|smtpserver(address)?|ldapserver(s)?|serveraddress|serverhostname|"
                           r"destination|clienturi|proxy(server|host|address)?|snmpdestinations?|trapdestinations?)$")
VERSION_KEY_RX = re.compile(r"(?i)(version|firmware|bios|bootcode|revision|build|release|package|software|driver|"
                            r"microcode|^fw|fw$)")
VERSION_CTX_RX = re.compile(r"(?i)(?:\b(?:version|ver|firmware|fw|build|release|rev|revision|bios)\b|(?<![A-Za-z])v)"
                            r"[\s:=._()-]*$")
OTHER_ID_KEYS = collections.OrderedDict([
    ("serial", re.compile(r"(?i)(serial|servicetag|assettag)")),
    ("uuid", re.compile(r"(?i)uuid")),
    ("mac", re.compile(r"(?i)(macaddress|permanentmac|^mac$)")),
    ("wwn", re.compile(r"(?i)(wwn|wwpn|wwnn)")),
    ("account", re.compile(r"(?i)^(username|userid|accountname|user_name)$")),
])

PUBLIC_SUFFIXES = ("dmtf.org", "w3.org", "ietf.org", "iana.org", "hpe.com", "hp.com", "dell.com", "lenovo.com",
                   "microsoft.com", "intel.com", "broadcom.com", "cisco.com", "huawei.com", "ibm.com", "supermicro.com",
                   "redhat.com", "openbmc.org", "github.com", "apache.org", "mozilla.org", "example.com", "example.org",
                   "example.net", "localhost", "localdomain")
STOP_NAMES = frozenset(["localhost", "localdomain", "bmc", "idrac", "ilo", "xcc", "cimc", "imm", "server", "admin", "root",
                        "default", "none", "null", "unknown", "host", "hostname", "system", "manager", "chassis",
                        "example", "test", "dns", "ntp", "smtp", "ldap", "redfish", "dell", "hpe", "lenovo", "supermicro",
                        "cisco", "mock", "emulator", "domain", "workgroup"])
_POOL16 = [(10, b) for b in range(1, 255)] + [(172, b) for b in range(16, 32)] + [(192, 168)]
TEXT_EXT = frozenset([".json", ".txt", ".xml", ".html", ".htm", ".log", ".csv", ".yml", ".yaml", ".ini", ".conf",
                      ".cfg", ".md", ".pem", ".crt", ".cer", ".csr"])
SKIP_NAMES = frozenset(["_mirror.lock"])


class SanitizeError(Exception):
    pass


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ip_int(ip):
    a, b, c, d = [int(x) for x in ip.split(".")]
    return (a << 24) | (b << 16) | (c << 8) | d


def keep_ip4(ip):
    """바꾸지 않는 주소의 이유('special' | 'mask') 또는 ''. 미지정/브로드캐스트/루프백/링크 로컬/멀티캐스트/문서용/마스크."""
    n = _ip_int(ip)
    if n in (0, 0xFFFFFFFF):
        return "special"
    inv = (~n) & 0xFFFFFFFF
    if inv & (inv + 1) == 0:
        return "mask"
    if (n >> 24) == 127 or (n >> 24) >= 224 or (n >> 16) == 0xA9FE or (n >> 8) in (0xC00002, 0xC63364, 0xCB0071):
        return "special"
    return ""


def scan_strings(text):
    """JSON 텍스트의 문자열 토큰을 (내용 시작, 내용 끝, 키 여부, 키 이름) 으로 차례로 낸다.

    값 문자열의 키 이름은 바로 앞 키(배열이면 배열을 가진 키)다. 형식은 건드리지 않으므로 이 위치로 그대로 치환할 수 있다."""
    stack = []
    pend = None
    pend_key = None
    for m in _TOK.finditer(text):
        ch = text[m.start()]
        if ch == '"':
            if pend is not None:
                yield pend[0] + 1, pend[1] - 1, False, pend_key
            pend = (m.start(), m.end())
            pend_key = stack[-1][1] if stack else None
            continue
        if ch == ":" and pend is not None:
            key = text[pend[0] + 1:pend[1] - 1]
            if stack and stack[-1][0] == "o":
                stack[-1][1] = key
            yield pend[0] + 1, pend[1] - 1, True, key
            pend = None
            continue
        if pend is not None:
            yield pend[0] + 1, pend[1] - 1, False, pend_key
            pend = None
        if ch == "{":
            stack.append(["o", None])
        elif ch == "[":
            stack.append(["a", stack[-1][1] if stack else None])
        elif ch in "}]" and stack:
            stack.pop()
    if pend is not None:
        yield pend[0] + 1, pend[1] - 1, False, pend_key


def is_host_key(key):
    k = (key or "").replace("_", "").lower()
    return bool(k) and k.endswith(HOST_KEY_END)


def is_public_host(host):
    h = host.lower().rstrip(".")
    return any(h == s or h.endswith("." + s) for s in PUBLIC_SUFFIXES)


def _is_ip_literal(low):
    return all(p.isdigit() for p in low.split("."))


class Mapper(object):
    """실제 값 -> 대체값 대응표. 파일로 저장한 대응표에는 실제 값이 들어 있으므로 반출하면 안 된다."""

    def __init__(self, state=None):
        s = state or {}
        self.key = bytes.fromhex(s["key"]) if s.get("key") else os.urandom(16)
        self.created = s.get("created") or _now()
        self.v4 = dict(s.get("ipv4", {}))
        self.v6 = dict(s.get("ipv6", {}))
        self.p16 = dict(s.get("p16", {}))
        self.p24 = dict(s.get("p24", {}))
        self.labels = dict(s.get("labels", {}))
        self.dom = dict(s.get("domains", {}))
        self.names = set(s.get("names", []))
        self._used16 = set(self.p16.values())
        self._used24 = set(self.p24.values())
        self._usedlab = set(self.labels.values())
        self._usedv6 = set(self.v6.values())
        self._useddom = set(self.dom.values())
        self._perm = {}

    def to_state(self):
        return {"version": MAP_VERSION, "tool_version": TOOL_VERSION, "key": self.key.hex(), "created": self.created, "updated": _now(),
                "ipv4": self.v4, "ipv6": self.v6, "p16": self.p16, "p24": self.p24, "labels": self.labels,
                "domains": self.dom, "names": sorted(self.names)}

    def _hex(self, *parts):
        msg = "\x1f".join(parts).encode("utf-8")
        return hmac.new(self.key, msg, hashlib.sha256).hexdigest()

    def _h(self, *parts):
        return int(self._hex(*parts), 16)

    # ---- IPv4 ----------------------------------------------------------------------------------
    def _fake16(self, k16):
        got = self.p16.get(k16)
        if got is not None:
            return got
        n = len(_POOL16)
        start = self._h("p16", k16) % n
        for i in range(n):
            a, b = _POOL16[(start + i) % n]
            cand = "%d.%d" % (a, b)
            if cand not in self._used16:
                self.p16[k16] = cand
                self._used16.add(cand)
                return cand
        raise SanitizeError("대체 주소 공간(/16 %d개)을 모두 썼습니다 - 서로 다른 /16 대역이 너무 많습니다" % n)

    def _fake24(self, k24, f16):
        got = self.p24.get(k24)
        if got is not None:
            return got
        start = self._h("p24", k24) % 256
        for i in range(256):
            cand = "%s.%d" % (f16, (start + i) % 256)
            if cand not in self._used24:
                self.p24[k24] = cand
                self._used24.add(cand)
                return cand
        raise SanitizeError("대체 /24 공간을 모두 썼습니다")

    def _host_octet(self, k24, d):
        if d in (0, 255):
            return d
        perm = self._perm.get(k24)
        if perm is None:
            order = sorted(range(1, 255), key=lambda v: self._h("host", k24, str(v)))
            perm = dict((v, order[v - 1]) for v in range(1, 255))
            self._perm[k24] = perm
        return perm[d]

    def ip4(self, ip):
        got = self.v4.get(ip)
        if got is not None:
            return got
        if keep_ip4(ip):
            self.v4[ip] = ip
            return ip
        a, b, c, d = [int(x) for x in ip.split(".")]
        k24 = "%d.%d.%d" % (a, b, c)
        f24 = self._fake24(k24, self._fake16("%d.%d" % (a, b)))
        fake = "%s.%d" % (f24, self._host_octet(k24, d))
        self.v4[ip] = fake
        return fake

    # ---- IPv6 ----------------------------------------------------------------------------------
    def ip6(self, addr):
        """대체 문자열. 루프백/미지정/멀티캐스트는 None (그대로 둔다)."""
        if addr.is_loopback or addr.is_unspecified or addr.is_multicast:
            return None
        key = addr.exploded
        got = self.v6.get(key)
        if got is not None:
            return got
        n = int(addr)
        mask64 = (1 << 64) - 1
        iid = self._h("v6iid", key) & mask64
        for _ in range(64):
            if (n >> 118) == 0x3FA:                                  # fe80::/10 링크 로컬은 링크 로컬로
                val = (0xFE80 << 112) | iid
            else:                                                    # 그 밖에는 ULA (/48 과 /64 묶음 유지)
                gid = self._h("v6g", "%012x" % (n >> 80)) & ((1 << 40) - 1)
                sub = self._h("v6s", "%016x" % (n >> 64)) & 0xFFFF
                val = (0xFD << 120) | (gid << 80) | (sub << 64) | iid
            cand = ipaddress.IPv6Address(val).compressed
            if cand not in self._usedv6:
                self.v6[key] = cand
                self._usedv6.add(cand)
                return cand
            iid = (iid + 1) & mask64
        raise SanitizeError("IPv6 대체 값을 만들 수 없습니다")

    # ---- 호스트 이름 / 도메인 ------------------------------------------------------------------
    def label(self, low):
        got = self.labels.get(low)
        if got is not None:
            return got
        full = self._hex("label", low)
        for width in (6, 8, 10, 12, 16, 24):
            cand = "host-" + full[:width]
            if cand not in self._usedlab:
                break
        self.labels[low] = cand
        self._usedlab.add(cand)
        return cand

    def add_domain(self, low):
        got = self.dom.get(low)
        if got is not None:
            return got
        full = self._hex("domain", low)
        for width in (4, 6, 8, 12, 16, 24):
            cand = "dom-%s.%s" % (full[:width], FAKE_TLD)
            if cand not in self._useddom:
                break
        self.dom[low] = cand
        self._useddom.add(cand)
        return cand

    def map_name(self, low):
        """호스트 이름 또는 FQDN(소문자) -> 대체 이름. 아는 도메인 접미를 먼저 찾는다."""
        labels = low.split(".")
        if len(labels) == 1:
            return self.label(low)
        for i in range(1, len(labels)):
            suffix = ".".join(labels[i:])
            if suffix in self.dom:
                return ".".join(self.label(x) for x in labels[:i]) + "." + self.dom[suffix]
        self.add_domain(".".join(labels[1:]))
        return self.map_name(low)

    def learn_host(self, token):
        """호스트 이름/FQDN 후보를 배운다. 배웠으면 True. 공개 도메인, IP, 흔한 단어는 배우지 않는다."""
        low = (token or "").strip().strip(".").lower()
        if not low or len(low) > 253 or not HOSTNAME_RX.match(low) or _is_ip_literal(low) or is_public_host(low):
            return False
        labels = low.split(".")
        if len(labels) == 1 and (low in STOP_NAMES or len(low) < 4 or low.isdigit()):
            return False
        self.names.add(low)
        if len(labels) >= 2:
            self.add_domain(".".join(labels[1:]))
            first = labels[0]
            if first not in STOP_NAMES and len(first) >= 4 and not first.isdigit():
                self.names.add(first)
        return True

    def learn_domain(self, token):
        low = (token or "").strip().strip(".").lower()
        if not low or not HOSTNAME_RX.match(low) or _is_ip_literal(low) or is_public_host(low):
            return False
        self.add_domain(low)
        return True


def load_map(path):
    if not os.path.exists(path):
        return Mapper()
    with open(path, encoding="utf-8") as f:
        state = json.load(f)
    if state.get("version") != MAP_VERSION:
        raise SanitizeError("대응표 형식이 다릅니다: %s" % path)
    return Mapper(state)


def save_map(path, mapper):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(mapper.to_state(), f, indent=1, sort_keys=True)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _match_case(orig, fake):
    return fake.upper() if (orig.isupper() and orig.lower() != orig) else fake


class Sanitizer(object):
    """텍스트/JSON 문자열 안의 IP 와 호스트 이름을 대응표대로 바꾼다. JSON 은 문자열 토큰만 건드려 형식을 그대로 둔다."""

    def __init__(self, mapper, protect_keys=(), protect_text=(), redact_certs=True):
        self.m = mapper
        self.pk = [re.compile(p) for p in protect_keys]
        self.pt = [re.compile(p) for p in protect_text]
        self.redact = redact_certs
        self.stats = collections.Counter()
        self.other = collections.Counter()
        self.rx = None
        self._key = None

    # ---- 배우기 (호스트 이름만. IP 는 만나는 대로 대응표에 넣는다) ------------------------------
    def learn_value(self, key, content):
        if key:
            if key == "host":
                self.m.learn_host(re.sub(r":[0-9]{1,5}$", "", content.strip()))
            elif is_host_key(key):
                self.m.learn_host(content)
            elif SERVER_KEY_RX.match(key):
                cand = content.strip()
                um = URL_HOST_RX.match(cand)
                host = (um.group(1) if um else cand).strip("[]")
                host = re.sub(r":[0-9]{1,5}$", "", host)
                if "." in host:
                    self.m.learn_host(host)
        if "://" in content:
            for um in URL_HOST_RX.finditer(content):
                if not um.group(1).startswith("["):
                    self.m.learn_host(um.group(1))

    def learn_json(self, text):
        for s, e, is_key, key in scan_strings(text):
            if not is_key and e > s:
                self.learn_value(key, text[s:e])

    def build(self):
        parts = []
        doms = sorted([d for d in self.m.dom if d.count(".") >= 1], key=len, reverse=True)
        if doms:
            parts.append(r"(?P<dom>(?<![A-Za-z0-9_-])(?P<pfx>(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+)"
                         r"(?P<d>%s)(?![A-Za-z0-9_-]))" % "|".join(re.escape(d) for d in doms))
        toks = sorted(self.m.names, key=len, reverse=True)
        if toks:
            parts.append(r"(?P<nm>(?<![A-Za-z0-9_-])(?:%s)(?![A-Za-z0-9_-]))" % "|".join(re.escape(t) for t in toks))
        parts.append(r"(?P<v6>" + _LEFT6 + r"[0-9A-Fa-f:]*:[0-9A-Fa-f:]*(?:\.[0-9]{1,3}){0,3}"
                     r"(?:%[A-Za-z0-9_.~-]+)?(?![\w:]))")
        parts.append(r"(?P<v4>" + _LEFT + "(?P<ip>" + _OCT + r"(?:\." + _OCT + r"){3})(?![\w-]|\.[0-9]))")
        self.rx = re.compile("|".join(parts), re.I)

    # ---- 바꾸기 ---------------------------------------------------------------------------------
    def _pem(self, m):
        body = m.group(0)
        bs_n = chr(92) + "n"
        nl = bs_n if bs_n in body else ("\n" if "\n" in body else " ")
        self.stats["pem"] += 1
        return "-----BEGIN %s-----%sREDACTED%s-----END %s-----" % (m.group(1), nl, nl, m.group(1))

    def _sub6(self, m):
        raw = m.group(0)
        tok, zone = (raw.split("%", 1)[0], "%" + raw.split("%", 1)[1]) if "%" in raw else (raw, "")
        if "::" not in tok and tok.count(":") != 7:
            return raw
        groups = tok.split(":")
        if len(groups) == 8 and all(len(g) == 2 for g in groups):          # 파이버채널 WWN 은 IPv6 가 아니다
            self.stats["v6_kept_wwn"] += 1
            return raw
        try:
            addr = ipaddress.IPv6Address(tok)
        except ValueError:
            return raw
        fake = self.m.ip6(addr)
        if fake is None:
            return raw
        self.stats["v6"] += 1
        return fake + zone

    def protect_reason(self, key, before):
        """IPv4 처럼 보여도 바꾸지 않는 이유('versionkey' | 'versionctx') 또는 ''. 펌웨어 버전을 망가뜨리지 않으려는 규칙."""
        if key and (VERSION_KEY_RX.search(key) or any(p.search(key) for p in self.pk)):
            return "versionkey"
        if VERSION_CTX_RX.search(before) or any(p.search(before) for p in self.pt):
            return "versionctx"
        return ""

    def _sub4(self, m):
        ip = m.group("ip")
        why = keep_ip4(ip)
        if why:
            self.stats["v4_kept_" + why] += 1
            return ip
        why = self.protect_reason(self._key, m.string[max(0, m.start("ip") - 24):m.start("ip")])
        if why:
            self.stats["v4_kept_" + why] += 1
            return ip
        self.stats["v4"] += 1
        return self.m.ip4(ip)

    def _sub(self, m):
        d = m.groupdict()
        if d.get("dom") is not None:
            labels = d["pfx"].rstrip(".").split(".")
            fake = ".".join(self.m.label(x.lower()) for x in labels) + "." + self.m.add_domain(d["d"].lower())
            self.stats["host"] += 1
            return _match_case(m.group(0), fake)
        if d.get("nm") is not None:
            self.stats["host"] += 1
            return _match_case(m.group(0), self.m.map_name(d["nm"].lower()))
        if d.get("v6") is not None:
            return self._sub6(m)
        return self._sub4(m)

    def sub_text(self, s, key=None):
        if not s:
            return s
        if self.redact and "-----BEGIN" in s:
            s = PEM_RX.sub(self._pem, s)
        self._key = key
        return self.rx.sub(self._sub, s)

    def _count_other(self, key, raw):
        if key:
            for name, rx in OTHER_ID_KEYS.items():
                if rx.search(key):
                    self.other[name] += 1
                    return
        if MAC_RX.search(raw):
            self.other["mac"] += 1

    def rewrite_json(self, text):
        out, pos = [], 0
        for s, e, is_key, key in scan_strings(text):
            if e <= s:
                continue
            raw = text[s:e]
            new = self.sub_text(raw, None if is_key else key)
            if not is_key:
                self._count_other(key, raw)
            if new != raw:
                out.append(text[pos:s])
                out.append(new)
                pos = e
        out.append(text[pos:])
        return "".join(out)


# ================================================================================================
# 폴더 처리
# ================================================================================================
BINARY_MAX = 64 << 20


def find_hosts(path, depth=3):
    """캡처 폴더(redfish/ 또는 _manifest.json 이 있는 곳)를 찾는다."""
    path = os.path.abspath(path)
    if os.path.isdir(os.path.join(path, "redfish")) or os.path.exists(os.path.join(path, "_manifest.json")):
        return [path]
    found = []
    if depth > 0 and os.path.isdir(path):
        for name in sorted(os.listdir(path)):
            if os.path.isdir(os.path.join(path, name)):
                found.extend(find_hosts(os.path.join(path, name), depth - 1))
    return found


def iter_files(host):
    for dp, dn, fn in os.walk(host):
        dn.sort()
        for name in sorted(fn):
            if name in SKIP_NAMES or name.endswith((".part", ".tmp")) or name.startswith(".dl-"):
                continue
            yield os.path.join(dp, name)


def read_text(path):
    """(문자열, '') 또는 (None, 'binary'). UTF-8 텍스트만 읽는다."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in TEXT_EXT and os.path.getsize(path) > BINARY_MAX:
        return None, "binary"
    with open(path, "rb") as f:
        data = f.read()
    if ext not in TEXT_EXT and b"\x00" in data[:8192]:
        return None, "binary"
    try:
        return data.decode("utf-8"), ""
    except UnicodeDecodeError:
        return None, "binary"


def _inside(child, parent):
    child, parent = os.path.abspath(child), os.path.abspath(parent)
    return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)


def sanitize(inputs, out_root, san, keep_binary=False, write=True):
    hosts = []
    for inp in inputs:
        root = os.path.abspath(inp)
        if not os.path.isdir(root):
            raise SanitizeError("폴더가 아닙니다: %s" % inp)
        for h in find_hosts(root):
            keep_root_name = h == root or len(inputs) > 1          # 입력이 여럿이면 입력 폴더 이름을 사본에도 남긴다
            hosts.append((h, os.path.dirname(root) if keep_root_name else root))
    if not hosts:
        raise SanitizeError("캡처 폴더(redfish/ 또는 _manifest.json 이 있는 곳)를 찾지 못했습니다")
    hints = 0                                                  # 폴더 이름 끝이 IP 마지막 자리인 호스트 (이름은 못 바꾸므로 알려만 준다)
    for h, _anchor in hosts:
        try:
            with open(os.path.join(h, "_manifest.json"), encoding="utf-8") as f:
                man_host = str(json.load(f).get("host", ""))
        except (OSError, ValueError, AttributeError):
            continue
        m = IPV4_RX.search(man_host)
        if m and re.search(r"[_.-]" + m.group(1).split(".")[-1] + "$", os.path.basename(h)):
            hints += 1
    for h, _anchor in hosts:                                   # 1단계: 호스트 이름을 모두 배운 뒤 바꾼다
        for p in iter_files(h):
            if p.lower().endswith(".json"):
                text, _why = read_text(p)
                if text is not None:
                    san.learn_json(text)
    san.build()
    base = out_root or "."                                     # --dry-run 에는 출력 폴더가 없다 (이름만 계산한다)
    rep = {"hosts": len(hosts), "files_json": 0, "files_text": 0, "binary_excluded": 0, "binary_kept": 0,
           "binary_list": [], "name_hints": hints}
    produced = set()
    for h, anchor in hosts:
        for p in iter_files(h):
            parts = os.path.relpath(p, anchor).split(os.sep)
            dest = os.path.join(base, *[san.sub_text(x, None) for x in parts])
            if dest.lower() in produced:
                raise SanitizeError("서로 다른 원본이 같은 사본 경로로 모입니다 (입력 폴더 이름이 겹침?): %s"
                                    % os.path.relpath(dest, base))
            produced.add(dest.lower())
            text, _why = read_text(p)
            if text is None:
                if keep_binary:
                    rep["binary_kept"] += 1
                    if write:
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        with open(p, "rb") as src, open(dest, "wb") as dst:
                            dst.write(src.read())
                else:
                    rep["binary_excluded"] += 1
                    if len(rep["binary_list"]) < 200:
                        rep["binary_list"].append({"file": os.path.relpath(dest, base).replace(os.sep, "/"),
                                                   "bytes": os.path.getsize(p)})
                continue
            if p.lower().endswith(".json"):
                new = san.rewrite_json(text)
                rep["files_json"] += 1
            else:
                new = san.sub_text(text, None)
                rep["files_text"] += 1
            if write:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(new.encode("utf-8"))
    return rep


# ================================================================================================
# 검증: 사본에 실제 값이 남았는지
# ================================================================================================
def verify(roots, san, mapper, limit=10):
    fakes4 = set(mapper.v4.values())
    reals4 = set(k for k, v in mapper.v4.items() if k != v and k not in fakes4)
    fake_names = set(mapper.labels.values()) | set(mapper.dom.values())
    real_names = [n for n in mapper.names if n not in fake_names]
    name_rx = None
    if real_names:
        name_rx = re.compile(r"(?<![A-Za-z0-9_-])(?:%s)(?![A-Za-z0-9_-])"
                             % "|".join(re.escape(t) for t in sorted(real_names, key=len, reverse=True)), re.I)
    res = {"files": 0, "binary_files": 0, "leak_ip": 0, "leak_host": 0, "leak_ip6": 0, "residual_ip": 0,
           "pem_left": 0, "where": []}

    def note(kind, rel, key):
        res[kind] += 1
        if len(res["where"]) < limit:
            res["where"].append("%s :: %s :: %s" % (kind, rel, key or "-"))

    def check(content, key, rel):
        for m in IPV4_RX.finditer(content):
            ip = m.group(1)
            if ip in reals4:
                note("leak_ip", rel, key)
            elif ip not in fakes4 and not keep_ip4(ip) and not san.protect_reason(
                    key, content[max(0, m.start(1) - 24):m.start(1)]):
                note("residual_ip", rel, key)
        if name_rx is not None and name_rx.search(content):
            note("leak_host", rel, key)
        if "-----BEGIN" in content and "REDACTED" not in content:
            note("pem_left", rel, key)
        for m in re.finditer(r"[0-9A-Fa-f:]*:[0-9A-Fa-f:]*", content):
            tok = m.group(0)
            if "::" in tok or tok.count(":") == 7:
                try:
                    a6 = ipaddress.IPv6Address(tok)
                except ValueError:
                    continue
                if a6.exploded in mapper.v6:
                    note("leak_ip6", rel, key)

    for root in roots:
        for dp, dn, fn in os.walk(root):
            dn.sort()
            for name in sorted(fn):
                p = os.path.join(dp, name)
                rel = os.path.relpath(p, root).replace(os.sep, "/")
                check(rel, None, rel + " (이름)")
                text, _why = read_text(p)
                if text is None:
                    res["binary_files"] += 1
                    continue
                res["files"] += 1
                if name.lower().endswith(".json"):
                    for s, e, is_key, key in scan_strings(text):
                        if e > s:
                            check(text[s:e], None if is_key else key, rel)
                else:
                    check(text, None, rel)
    res["ok"] = not (res["leak_ip"] or res["leak_host"] or res["leak_ip6"] or res["pem_left"])
    return res


# ================================================================================================
# CLI
# ================================================================================================
def _prepare_stdio():
    """콘솔이 한글을 못 담는 인코딩(C 로캘 ASCII 등)이어도 출력이 죽지 않게 한다 (Python 3.6 포함)."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        enc = (getattr(stream, "encoding", None) or "").lower().replace("-", "").replace("_", "")
        keep = enc in ("utf8", "cp949", "euckr", "ms949", "uhc")
        try:
            if keep:
                stream.reconfigure(errors="replace")
            else:
                stream.reconfigure(encoding="utf-8", errors="replace")
            continue
        except Exception:  # noqa: BLE001
            pass
        buf = getattr(stream, "buffer", None)
        if buf is not None and not keep:
            setattr(sys, name, io.TextIOWrapper(buf, encoding="utf-8", errors="replace", line_buffering=True))


def build_parser():
    ap = argparse.ArgumentParser(
        description="캡처 미러의 IP 와 호스트 이름을 형식이 유효한 대체값으로 일관되게 바꾼 반출용 사본을 만든다.",
        epilog="대응표(--map)에는 실제 값이 들어 있으니 사본과 함께 반출하지 마세요.")
    ap.add_argument("inputs", nargs="+", metavar="DIR", help="캡처 폴더 (여러 호스트가 든 상위 폴더도 가능). --verify 면 검사할 사본 폴더")
    ap.add_argument("--out", "-o", help="사본을 만들 폴더 (없거나 비어 있어야 한다)")
    ap.add_argument("--map", default=DEFAULT_MAP, help="대응표 파일 (없으면 만든다. 기본 ~/.redfish_sanitize_map.json)")
    ap.add_argument("--verify", action="store_true", help="DIR 에 실제 값이 남았는지만 검사")
    ap.add_argument("--dry-run", action="store_true", help="아무것도 쓰지 않고 무엇이 바뀔지 개수만 보고")
    ap.add_argument("--keep-binary", action="store_true", help="바이너리 첨부도 그대로 사본에 넣는다 (안의 값은 못 바꾼다)")
    ap.add_argument("--keep-certs", action="store_true", help="인증서 PEM 본문을 지우지 않는다")
    ap.add_argument("--protect-key", action="append", default=[], metavar="REGEX",
                    help="이 정규식에 맞는 키의 값은 IPv4 처럼 보여도 바꾸지 않는다 (버전 같은 값 보호). 반복 가능")
    ap.add_argument("--protect-text", action="append", default=[], metavar="REGEX",
                    help="IPv4 바로 앞 24자가 이 정규식에 맞으면 바꾸지 않는다. 반복 가능")
    ap.add_argument("--extra-host", action="append", default=[], metavar="NAME", help="추가로 바꿀 호스트 이름/FQDN. 반복 가능")
    ap.add_argument("--extra-domain", action="append", default=[], metavar="DOMAIN", help="추가로 바꿀 도메인. 반복 가능")
    ap.add_argument("--no-verify", action="store_true", help="만든 뒤 자동 검증을 건너뛴다")
    return ap


def _print_verify(res, say):
    say("  검증: 텍스트 %d개 검사 (바이너리 %d개 건너뜀)" % (res["files"], res["binary_files"]))
    say("    실제 IPv4 남음 %d · 실제 IPv6 남음 %d · 실제 호스트 이름 남음 %d · 인증서 본문 남음 %d"
        % (res["leak_ip"], res["leak_ip6"], res["leak_host"], res["pem_left"]))
    say("    의심 IPv4(버전으로 보이지 않는데 대응표에 없음) %d" % res["residual_ip"])
    for w in res["where"]:
        say("      " + w)
    say("  [%s] 반출 전 검사: %s" % ("PASS" if res["ok"] and not res["residual_ip"] else "FAIL",
                                  "실제 값이 남아 있지 않습니다" if res["ok"] and not res["residual_ip"]
                                  else "위 위치를 확인하세요 (--protect-key / --extra-host 로 조정)"))


def main(argv=None):
    _prepare_stdio()
    say = print
    args = build_parser().parse_args(argv)
    os.umask(0o077)
    try:
        mapper = load_map(args.map)
        for n in args.extra_host:
            mapper.learn_host(n)
        for d in args.extra_domain:
            mapper.learn_domain(d)
        san = Sanitizer(mapper, args.protect_key, args.protect_text, not args.keep_certs)
        if args.verify:
            san.build()
            res = verify([os.path.abspath(p) for p in args.inputs], san, mapper)
            _print_verify(res, say)
            return 0 if res["ok"] and not res["residual_ip"] else 1
        if not args.out and not args.dry_run:
            raise SanitizeError("--out 사본 폴더가 필요합니다 (아무것도 쓰지 않으려면 --dry-run)")
        out = os.path.abspath(args.out) if args.out else None
        for inp in args.inputs:
            if os.path.exists(os.path.join(inp, "_sanitize_report.json")):
                raise SanitizeError("이미 이 도구로 처리한 사본입니다 (다시 처리하면 대체값이 또 바뀝니다): %s" % inp)
        if out:
            for inp in args.inputs:
                if _inside(out, inp) or _inside(inp, out):
                    raise SanitizeError("사본 폴더와 캡처 폴더가 겹칩니다")
            if _inside(args.map, out):
                raise SanitizeError("대응표(--map)를 사본 폴더 안에 두면 실제 값이 반출됩니다")
            if os.path.isdir(out) and os.listdir(out):
                raise SanitizeError("사본 폴더가 비어 있지 않습니다: 새 폴더를 쓰세요")
        write = not args.dry_run
        rep = sanitize(args.inputs, out, san, keep_binary=args.keep_binary, write=write)
        st, other = san.stats, san.other
        real4 = len([k for k, v in mapper.v4.items() if k != v])
        kept = dict((k, v) for k, v in st.items() if "kept" in k)
        report = {"tool": "sanitize_mirror", "tool_version": TOOL_VERSION, "finished": _now(), "dry_run": not write,
                  "hosts": rep["hosts"], "files_json": rep["files_json"], "files_text": rep["files_text"],
                  "binary_excluded": rep["binary_excluded"], "binary_kept": rep["binary_kept"],
                  "binary_list": rep["binary_list"], "folder_name_hints": rep["name_hints"],
                  "replaced": {"ipv4": st["v4"], "ipv6": st["v6"], "hostname": st["host"], "pem": st["pem"]},
                  "kept": kept, "distinct": {"ipv4": real4, "hostnames": len(mapper.names), "domains": len(mapper.dom)},
                  "other_identifiers_not_replaced": dict(other)}
        if write:
            os.makedirs(out, exist_ok=True)
            with open(os.path.join(out, "_sanitize_report.json"), "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, sort_keys=True, ensure_ascii=False)
            save_map(args.map, mapper)
        say("  호스트 폴더 %d개 · JSON %d개 · 텍스트 %d개 · 바이너리 %s %d개" % (
            rep["hosts"], rep["files_json"], rep["files_text"], "포함" if args.keep_binary else "제외",
            rep["binary_kept"] if args.keep_binary else rep["binary_excluded"]))
        say("  바꾼 곳: IPv4 %d (서로 다른 %d개) · IPv6 %d · 호스트 이름 %d · 인증서 본문 %d" % (
            st["v4"], real4, st["v6"], st["host"], st["pem"]))
        say("  그대로 둔 IPv4: 버전 키 %d · 버전 문맥 %d · 마스크 %d · 특수 주소 %d" % (
            st["v4_kept_versionkey"], st["v4_kept_versionctx"], st["v4_kept_mask"], st["v4_kept_special"]))
        say("  [INFO] 바꾸지 않은 식별자(개수): " + (", ".join("%s %d" % kv for kv in sorted(other.items())) or "없음")
            + " - 이 도구는 IP 와 호스트 이름만 바꿉니다")
        if rep["name_hints"]:
            say("  [WARN] 호스트 폴더 %d개의 이름 끝이 IP 마지막 자리와 같습니다 - 폴더 이름은 바꾸지 않으니 다음부터는 IP 와 무관한 이름을 쓰세요"
                % rep["name_hints"])
        if write:
            say("  사본: %s" % out)
            say("  [WARN] 대응표 %s 에는 실제 값이 들어 있습니다. 반출하지 마세요." % args.map)
        if write and not args.no_verify:
            san.build()
            res = verify([out], san, mapper)
            _print_verify(res, say)
            return 0 if res["ok"] and not res["residual_ip"] else 1
        return 0
    except SanitizeError as exc:
        print("[CRIT] %s" % exc, file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print("[CRIT] %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
