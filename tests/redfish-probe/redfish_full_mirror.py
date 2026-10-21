#!/usr/bin/env python3
"""Redfish 전수 재귀 미러 v2 — 계정으로 닿는 모든 GET 가능 리소스를 빠짐없이 raw 저장.

목적 (제한 운영망 1회 캡처 -> 인터넷망에서 코드/fixture 완성):
    운영망의 실 BMC/RMC 에 1회 접속해, 우리 수집 코드의 "가정된 경로"를 일절 쓰지 않고
    ServiceRoot 부터 장비가 응답에 실어 준 모든 링크를 재귀로 따라가 트리 전체를 raw 로 떠온다.
    떠온 트리는 replay_full_mirror.py / convert_dmtf_mockup.py / capture_mirror_fixture.py 가
    그대로 오프라인 재생해 fixture 와 회귀 기준선을 만든다.

설계 원칙:
    1. 우리 코드 비의존 - redfish_gather / adapter / 가정 경로를 호출하지 않는다.
    2. 깊은 스캔 - @odata.id / nextLink / ActionInfo 뿐 아니라 Actions target, Location[].Uri,
       *Uri/*URI/url/href 키, '/redfish/' 로 시작하는 문자열 값, 응답 Link 헤더까지 따라간다.
       스펙 고정 주소(/redfish, <root>/odata, <root>/$metadata)와 $metadata 가 참조하는 로컬 스키마도 받는다.
    3. 누락 0 - 비-JSON(XML/HTML/바이너리)은 절단하지 않고 raw.<ext> 로 전체 저장한다.
       일시 오류(5xx/429/408/timeout/TLS)는 backoff + Retry-After 로 재시도하고 마지막에 한 번 더 훑는다.
    4. 오류 판정 - 장비가 링크는 냈지만 실제로 없는 경로(404), 페이로드 없는 응답(204),
       GET 불가 주소(405), 요청 거절(400/406/...), 계정 권한 밖(401/403)은 오류가 아니다.
       받을 수 있는 것은 전부 받았다면 RESULT=COMPLETE 다.
    5. 잠금 방지 - 401/403 은 재시도하지 않는다. 자격 거절은 신호 2개가 모두 거절일 때만 단정하고
       요청 1~2회 만에 중단한다. 비밀번호는 argv 대신 환경변수/파일로 받을 수 있고 어떤 파일에도 쓰지 않는다.

판정 버킷 (manifest.summary):
    ok / ok_empty / ok_raw   2xx 저장 (JSON / 빈 본문 / 비-JSON raw)
    absent                   404/410 - 장비가 링크는 냈지만 없음 (오류 아님, 참조원 기록)
    not_gettable             405/501 - GET 불가 (액션 주소 등)
    rejected                 400/406/409/415/422/그 외 4xx - 장비가 요청을 거절 (재시도 안 함)
    outside_account          401/403 - 계정 권한 밖 (재시도 안 함)
    device_error             재시도·최종 sweep 뒤에도 같은 5xx/무응답이지만 다른 요청은 정상 (장비 측 결함)
    unresolved               재시도 뒤에도 남았고 장비/망이 불안정 - 유일한 미완료 사유 (--resume 으로 수렴)

인증:
    --auth auto(기본)   세션(POST SessionService/Sessions -> X-Auth-Token) 우선, 미지원이면 Basic.
    --auth session      세션만. --auth basic  Basic 만 (세션 POST 를 보내지 않음 - Basic 전용 RMC 용).
    비-GET 요청은 세션 로그인 POST 와 종료 DELETE 뿐이다 (장비 설정 변경 0).

출력 (= DMTF mockup = convert_dmtf_mockup.py 입력):
    <out>/redfish/v1/.../index.json    2xx 리소스 raw 본문 (@odata.id 보존)
    <out>/redfish/v1/.../headers.json  HTTP 상태 + 응답 헤더 (토큰/쿠키 제거)
    <out>/redfish/v1/.../raw.<ext>     비-JSON/바이너리 본문 (index.json 은 @odata.id 없는 스텁)
    <out>/_manifest.json               크롤 요약·자가진단 (manifest_schema=2)
    <out>/_links.json                  경로 -> 첫 참조원/종류/키/참조수
    <out>/_fsmap.json                  경로 -> 디스크 디렉터리 (충돌/예약어/길이 축약 기록, --resume 입력)
    <out>/_serviceroot_noauth.json     무인증 ServiceRoot

사용:
    export BMC_PASSWORD='...'                     # 또는 --password-env VAR / --password-file PATH
    python3 redfish_full_mirror.py -r <IP[:443]> -u <계정> -D <출력폴더>
    python3 redfish_full_mirror.py -r <IP> -u <계정> -D <출력폴더> --resume   # 중단/INCOMPLETE 이어받기
    python3 redfish_full_mirror.py --summarize <출력폴더> [<출력폴더> ...]   # 여러 호스트 manifest 요약

종료코드: 0=COMPLETE 1=INCOMPLETE 2=EMPTY(2xx 0건) 3=인증/세션 중단 4=도달 불가 130=중단(Ctrl-C/SIGTERM)

stdlib 전용(urllib / ssl / json / base64), Python 3.6+ (RHEL/Rocky 8 기본 python3 포함).
"""
import argparse
import base64
import datetime
import gzip
import hashlib
import http.client
import io
import json
import os
import re
import signal
import socket
import ssl
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections import OrderedDict, deque
from email.utils import parsedate_to_datetime

TOOL_VERSION = "2.0.0"
MANIFEST_SCHEMA = 2

JSON_ACCEPT = "application/json"
XML_ACCEPT = "application/xml"
ANY_ACCEPT = "*/*"

EXIT_COMPLETE = 0
EXIT_INCOMPLETE = 1
EXIT_EMPTY = 2
EXIT_AUTH = 3
EXIT_UNREACHABLE = 4
EXIT_INTERRUPTED = 130

AUTH_ABORTS = ("credentials_rejected", "session_unsupported", "session_limit_exceeded", "auth_lost")

# ---- 조정 가능한 상수 (시험이 monkeypatch 한다) ------------------------------------------------
BACKOFF_BASE = 1.5           # 재시도 backoff = BACKOFF_BASE * 2**n, 상한 BACKOFF_CAP
BACKOFF_CAP = 30.0
RETRY_AFTER_CAP = 60.0       # 429/503 Retry-After 상한
TIMEOUT_CAP = 180.0          # timeout 종류 재시도 시 요청 timeout 2배 점증 상한
TIMEOUT_RETRIES = 2          # timeout 은 한 리소스당 인라인 재시도 최대 2회 (장비가 멈춘 경우 시간 폭주 방지)
SWEEP_PAUSE = 5.0            # BFS 종료 뒤 최종 sweep 전에 쉬는 시간
RELOGIN_MIN_INTERVAL = 30.0  # 세션 재로그인 최소 간격
LOGIN_LIMIT_RETRIES = 3      # 세션 한도 초과(SessionLimitExceeded) 로그인 재시도 횟수
ERROR_BODY_CAP = 1 << 20     # 오류 응답 본문 보존 상한 1 MiB
HEALTH_CACHE_SECONDS = 15.0  # 장비 불안정 판정 재사용 시간

# 파일시스템(특히 Windows)에서 디렉터리명에 못 쓰는 문자. 본문 @odata.id 는 보존하고 디스크 경로명만
# 치환하므로, 재생 시 키잉(본문 @odata.id 기준)에는 영향 없다. (\x5c = 백슬래시)
_FS_BAD = re.compile(r'[\x00-\x1f<>:"|?*\x5c]')
_WIN_RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.I)
_RESERVED_LEAF = frozenset(["index.json", "headers.json"])

_ABS_URL = re.compile(r"^https?://[^/]+(/.*)$")
_QUOTE_SAFE = "/%:@!$&'()*+,;=-._~?#[]"
_SSE_PATH = re.compile(r"(?i)/sse$")
_VOLATILE_PATH = re.compile(r"/(Entries|Sessions)(/|$)")
_SESSION_LIMIT = re.compile(r"SessionLimitExceeded|RAC0218")
_LINK_TARGET = re.compile(r"<([^>]+)>")
_XML_URI_ATTR = re.compile(r'\bUri\s*=\s*"([^"]+)"')

# 따라가지 않는 키: 값이 링크처럼 보이지만 링크가 아니다.
_NOT_LINK_KEYS = frozenset(["@odata.context", "@odata.type", "@odata.etag", "$ref", "$id", "$schema",
                            "Image", "HttpPushUriTargets"])
_URI_KEYS = frozenset(["Uri", "URI", "url", "URL", "href", "TaskMonitor"])
# 정책 제외 키: GET 하면 스트림이 timeout 까지 멈춰 일시 장애로 오분류되고 재시도만 반복한다.
_POLICY_EXCLUDE_KEYS = frozenset(["ServerSentEventUri"])

_SECRET_HEADERS = frozenset(["x-auth-token", "set-cookie", "authorization", "proxy-authorization", "cookie"])

_CT_EXT = (("xml", ".xml"), ("html", ".html"), ("json", ".txt"), ("text/plain", ".txt"),
           ("gzip", ".gz"), ("zip", ".zip"), ("x-tar", ".tar"), ("zstd", ".zst"),
           ("pkix-cert", ".cer"), ("x-pem-file", ".pem"))


def _sleep(seconds):
    """모든 대기는 이 함수를 지난다 (시험이 monkeypatch 로 고속화)."""
    if seconds and seconds > 0:
        time.sleep(seconds)


def _emit(text, stream=None):
    """콘솔 인코딩이 ASCII 인 Python 3.6 환경에서도 한글 출력이 죽지 않게 한다."""
    stream = stream if stream is not None else sys.stdout
    line = text + "\n"
    try:
        stream.write(line)
    except UnicodeEncodeError:
        enc = getattr(stream, "encoding", None) or "ascii"
        stream.write(line.encode(enc, "replace").decode(enc, "replace"))
    try:
        stream.flush()
    except Exception:  # noqa: BLE001
        pass


def _utcnow_iso():
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.replace(microsecond=0, tzinfo=None).isoformat() + "Z"


def _bracket_ipv6(host):
    """IPv6 리터럴(콜론 2개 이상, 대괄호 없음)을 [addr]/[addr]:port 로 감싼다.

    안 감싸면 urlopen 이 ValueError -> 전 fetch 가 조용히 실패 -> 한 번뿐인 캡처를 '도달 불가'로 오진한다.
    """
    if host.startswith("["):
        return host
    addr, port = host, ""
    if host.count(":") == 1 and host.rsplit(":", 1)[1].isdigit():
        addr, port = host.rsplit(":", 1)
    if addr.count(":") >= 2:
        return "[%s]" % addr + (":%s" % port if port else "")
    return host


def _norm(path):
    """nav URI 를 방문/비교용으로 정규화: 절대 URL->경로, #fragment 제거, 경로의 // 접기, 끝 / 제거.

    ?query 는 보존한다 - 페이지네이션 nextLink(?$skip=50)는 쿼리로만 1페이지와 구별된다.
    경로의 // 를 접는 이유: Lenovo 가 /a//b 형태 링크를 내는데, 그대로 두면 같은 디스크 디렉터리에
    404 응답이 정상 200 저장본을 덮어쓴다 (실측 손실).
    """
    if not path:
        return ""
    m = _ABS_URL.match(path)
    if m:
        path = m.group(1)
    path = path.split("#", 1)[0]
    base, sep, query = path.partition("?")
    base = re.sub(r"/{2,}", "/", base)
    if len(base) > 1:
        base = base.rstrip("/")
    return base + sep + query if sep else base


def _keep_path(value):
    """링크 값에서 호스트만 떼고 경로를 그대로 둔다. _norm 과 달리 끝 슬래시를 보존한다
    (일부 BMC 는 세션 생성 POST 에 끝 슬래시를 요구한다). #fragment 는 제거하고 // 는 접는다."""
    m = _ABS_URL.match(value)
    path = (m.group(1) if m else value).split("#", 1)[0]
    return re.sub(r"/{2,}", "/", path)


def _quote_path(path):
    """요청 경로의 불법 문자(공백/비ASCII 등)만 percent-encode 한다. 기존 %XX 와 URL 구분자는 보존."""
    return urllib.parse.quote(path, safe=_QUOTE_SAFE, errors="replace")


def _retry_after_seconds(value, cap):
    """Retry-After(정수 초 또는 HTTP-date)를 초로 변환. 해석 불가면 None, 과거/음수는 0, 상한 cap."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        secs = float(text)
    except ValueError:
        try:
            when = parsedate_to_datetime(text)
        except Exception:  # noqa: BLE001
            return None
        if when is None:
            return None
        if not when.tzinfo:
            when = when.replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        secs = (when - now).total_seconds()
    if secs != secs or secs < 0:  # NaN 또는 과거
        secs = 0.0
    return min(secs, float(cap))


def _ext_for(content_type, path):
    ct = (content_type or "").lower()
    for token, ext in _CT_EXT:
        if token in ct:
            return ext
    last = path.split("?", 1)[0].rsplit("/", 1)[-1]
    m = re.search(r"(\.[A-Za-z0-9]{1,8})$", last)
    if m:
        return m.group(1).lower()
    return ".bin"


def _clip_bytes(text, limit):
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[:limit].decode("utf-8", "ignore")


def _hash8(text, n=8):
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:n]


def _fs_segment(seg):
    """URL 경로 세그먼트 -> 안전한 디렉터리명. 본문 @odata.id 는 그대로라 재생 키잉에 영향 없다."""
    s = seg.encode("utf-8", "replace").decode("utf-8", "replace")  # lone surrogate 제거
    s = _FS_BAD.sub("_", s)[:200]
    s = _clip_bytes(s, 240)                # 한글 등 멀티바이트도 NTFS/ext4 컴포넌트 한도 안으로
    s = s.rstrip(" .")                     # Windows: 끝 공백/점 불가. '.'/'..' 는 빈 문자열이 된다
    if not s:
        s = "_"
    if _WIN_RESERVED.match(s) or s.lower() in _RESERVED_LEAF:
        s = s + "_"
    return s


class FsMapper(object):
    """URL 경로 -> 출력 디렉터리 상대경로. 대소문자 무시 충돌/Windows 예약어/길이 초과를 흡수한다.

    모든 매핑은 _fsmap.json 에 기록돼 --resume 이 같은 디렉터리를 재사용한다.
    """

    def __init__(self, max_rel):
        self.max_rel = max_rel
        self.by_path = {}
        self.owner = {}

    def seed(self, path, rel_dir):
        self.by_path[path] = rel_dir
        self.owner[rel_dir.lower()] = path

    def dir_for(self, path):
        hit = self.by_path.get(path)
        if hit is not None:
            return hit
        rel = path.strip("/")
        segs = [_fs_segment(s) for s in rel.split("/") if s] if rel else []
        rel_dir = "/".join(segs)
        if len(rel_dir) > self.max_rel:
            keep, used = [], 0
            for s in segs:
                if used + len(s) + 1 > self.max_rel - 16:
                    break
                keep.append(s)
                used += len(s) + 1
            keep.append("~" + _hash8(path, 12))
            rel_dir = "/".join(keep)
        n = 8
        while self.owner.get(rel_dir.lower(), path) != path:
            parts = rel_dir.rsplit("/", 1)
            tail = parts[-1] + "~" + _hash8(path, n)
            rel_dir = (parts[0] + "/" + tail) if len(parts) == 2 else tail
            n += 4
        self.by_path[path] = rel_dir
        self.owner[rel_dir.lower()] = path
        return rel_dir


def _write_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _write_json(path, obj):
    """JSON 을 원자적으로 쓴다. lone surrogate 가 있어 UTF-8 인코딩이 안 되면 ensure_ascii 로 재시도."""
    last = None
    for ascii_only in (False, True):
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                json.dump(obj, f, indent=2, ensure_ascii=ascii_only, sort_keys=True, default=str)
            os.replace(tmp, path)
            return
        except UnicodeEncodeError as exc:
            last = exc
            try:
                os.remove(tmp)
            except OSError:
                pass
    raise last


def _filter_headers(headers):
    return OrderedDict((k, v) for k, v in headers.items() if k.lower() not in _SECRET_HEADERS)


def _link_header_targets(values):
    out = []
    for v in values:
        for m in _LINK_TARGET.finditer(v or ""):
            out.append(m.group(1))
    return out


def _looks_like_target(value):
    return value.startswith("/") or "://" in value


def _str_link_kind(key, value):
    """문자열 값 하나가 링크인지, 어떤 종류인지. 링크가 아니면 None."""
    if key == "@odata.id":
        return "odata.id"
    if key == "@odata.nextLink" or key.endswith("@odata.nextLink"):
        return "nextLink"
    if key.endswith("@Redfish.ActionInfo"):
        return "actioninfo"
    if key in _NOT_LINK_KEYS or key.startswith("@odata.") or "@Redfish." in key or "@Message." in key:
        return None
    if not value:
        return None
    if key == "target" and _looks_like_target(value):
        return "target"
    if (key in _URI_KEYS or key.endswith("Uri") or key.endswith("URI")) and _looks_like_target(value):
        return "uri"
    if value.startswith("/redfish/"):
        return "path_string"
    return None


def _collect_links(obj, key="", out=None, depth=0):
    """응답 JSON 어디에 있든 모든 링크를 재귀 수집 -> [(value, kind, key)] (Oem/중첩 dict·list 포함).

    @odata.id / nextLink / ActionInfo(v1 규칙) + Actions target / Location[].Uri / *Uri·*URI·url·href /
    '/redfish/' 로 시작하는 문자열 값. 값이 dict/list 인 키는 키와 무관하게 안쪽을 계속 뒤진다
    (@Redfish.Settings.SettingsObject 같은 링크가 거기 숨어 있다).
    """
    if out is None:
        out = []
    if depth > 200:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                kind = _str_link_kind(k, v)
                if kind:
                    out.append((v, kind, k))
            else:
                _collect_links(v, k, out, depth + 1)
    elif isinstance(obj, list):
        for it in obj:
            if isinstance(it, str):
                kind = _str_link_kind(key, it) if key else None
                if kind in ("odata.id", "nextLink", "actioninfo", "path_string"):
                    out.append((it, kind, key))
            else:
                _collect_links(it, key, out, depth + 1)
    return out


def _decode_body(raw, encoding):
    """Content-Encoding gzip/deflate 를 푼다. 깨진 압축은 원본 그대로 돌려 비-JSON 으로 흘려보낸다."""
    enc = (encoding or "").lower()
    if raw and ("gzip" in enc or "deflate" in enc):
        try:
            return gzip.decompress(raw) if "gzip" in enc else zlib.decompress(raw)
        except Exception:  # noqa: BLE001
            try:
                return zlib.decompress(raw, -zlib.MAX_WBITS)  # raw deflate (zlib 헤더 없음)
            except Exception:  # noqa: BLE001
                return raw
    return raw


def _parse_json(raw):
    """(성공 여부, 값). bytes 를 그대로 json 에 넘겨 UTF-8/BOM 을 처리한다 (Python 3.6+)."""
    try:
        return True, json.loads(raw)
    except ValueError:
        return False, None


def _error_detail(resp, limit=240):
    """오류 응답 본문에서 사람이 읽을 한 줄을 뽑는다 (Redfish error.message / ExtendedInfo)."""
    body = resp.body
    if not body:
        return resp.error or ""
    ok, data = _parse_json(body)
    if not ok:
        text = body[:limit].decode("utf-8", "replace")
        return " ".join(text.split())[:limit]
    msg = None
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            msg = err.get("message") or err.get("code")
            ext = err.get("@Message.ExtendedInfo")
            if isinstance(ext, list) and ext and isinstance(ext[0], dict):
                msg = ext[0].get("Message") or ext[0].get("MessageId") or msg
    return str(msg if msg else (resp.error or ""))[:limit]


def _is_session_limit(resp):
    if not resp.body:
        return False
    return bool(_SESSION_LIMIT.search(resp.body[:ERROR_BODY_CAP].decode("utf-8", "replace")))


# ================================================================================================
# 네트워크 계층
# ================================================================================================

def _make_ctx(verify, legacy_tls=False):
    """HTTPS context. verify=False(기본)는 self-signed BMC 허용 + 구형 BMC 호환 (redfish_gather._ctx 와 같은 정책).

    OP_LEGACY_SERVER_CONNECT 상수를 노출하지 않는 빌드(Python < 3.12)는 OpenSSL 값 0x4 를 직접 설정한다.
    legacy_tls 는 TLS 1.0/1.1 만 말하는 구형 BMC 용이다 (OS 의 crypto-policy 가 막으면 효과 없음).
    """
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        except (ValueError, OverflowError):
            pass
        try:
            ctx.set_ciphers("DEFAULT@SECLEVEL=0")
        except ssl.SSLError:
            pass
    if legacy_tls:
        if hasattr(ssl, "TLSVersion"):
            try:
                ctx.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
            except (ValueError, AttributeError):
                pass
        else:
            for name in ("OP_NO_TLSv1", "OP_NO_TLSv1_1"):
                ctx.options &= ~getattr(ssl, name, 0)
    return ctx


class Resp(object):
    """단일 HTTP 호출 결과. status 0=전송 실패(timeout/TLS/연결), -1=잘못된 URL."""

    def __init__(self):
        self.status = 0
        self.headers = OrderedDict()   # 원래 대소문자 보존
        self.h = {}                    # 소문자 키 조회용
        self.links = []                # Link 헤더 값들
        self.body = None               # bytes (메모리 경로)
        self.raw_path = None           # 디스크로 스트리밍한 임시 파일
        self.size = 0
        self.error = ""
        self.kind = ""                 # timeout | tls | conn | url | stream | redirect
        self.oversize = False
        self.location = None


class _RedirectGuard(urllib.request.HTTPRedirectHandler):
    """같은 장비 안의 GET 리다이렉트만 따라간다. 세션 토큰/Basic 이 다른 호스트로 새지 않게 한다.

    - 쓰기(POST/DELETE)는 어떤 리다이렉트도 따라가지 않는다.
    - 다른 호스트로의 이동은 /redfish/ 경로일 때만 우리 호스트로 재호스팅하고 그 외는 거부한다.
    - https -> http 하향은 거부한다.
    """

    def __init__(self, net):
        self.net = net

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        method = req.get_method()
        if method not in ("GET", "HEAD"):
            raise urllib.error.HTTPError(req.full_url, code, "redirect not followed for %s" % method, headers, fp)
        old = urllib.parse.urlsplit(req.full_url)
        new = urllib.parse.urlsplit(newurl)
        rehosted = False
        if (new.hostname or "").lower() == self.net.self_host:
            if old.scheme == "https" and new.scheme != "https":
                raise urllib.error.HTTPError(req.full_url, code, "redirect blocked: https to http downgrade",
                                             headers, fp)
        elif new.path.startswith("/redfish/"):
            newurl = "%s://%s%s%s" % (old.scheme, old.netloc, new.path, ("?" + new.query) if new.query else "")
            rehosted = True
        else:
            raise urllib.error.HTTPError(req.full_url, code,
                                         "redirect blocked: different host %s" % (new.hostname or "?"), headers, fp)
        if len(self.net.redirected) < 200:
            self.net.redirected.append({"from": old.path, "to": urllib.parse.urlsplit(newurl).path,
                                        "status": code, "rehosted": rehosted})
        return urllib.request.HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)


class Net(object):
    """urllib 위의 얇은 HTTP 계층. 환경 프록시 무시(기본), 리다이렉트 가드, 스트리밍 저장, 예외 -> Resp 변환."""

    def __init__(self, scheme, host, ctx, timeout, use_env_proxy=False):
        self.scheme = scheme
        self.host = host
        self.base = "%s://%s" % (scheme, host)
        self.timeout = timeout
        self.self_host = (urllib.parse.urlsplit("//" + host).hostname or host).lower()
        self.token = None
        self.basic = None
        self.requests = 0
        self.bytes_total = 0
        self.redirected = []
        self._seq = 0
        self._cur_part = None
        handlers = []
        if not use_env_proxy:
            handlers.append(urllib.request.ProxyHandler({}))
        if scheme == "https":
            handlers.append(urllib.request.HTTPSHandler(context=ctx))
        handlers.append(_RedirectGuard(self))
        self.opener = urllib.request.build_opener(*handlers)

    def auth_headers(self):
        if self.token:
            return {"X-Auth-Token": self.token}
        if self.basic:
            return {"Authorization": self.basic}
        return {}

    def request(self, method, path, accept=JSON_ACCEPT, auth="default", headers=None, body=None,
                timeout=None, max_bytes=0, spool_dir=None):
        resp = Resp()
        hdrs = {"Accept": accept}
        if auth == "default":
            hdrs.update(self.auth_headers())
        if headers:
            hdrs.update(headers)
        try:
            req = urllib.request.Request(self.base + _quote_path(path), data=body, headers=hdrs, method=method)
        except ValueError as exc:
            resp.status, resp.kind, resp.error = -1, "url", "ValueError: %s" % exc
            return resp
        self.requests += 1
        try:
            r = self.opener.open(req, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as e:
            resp.status = e.code
            resp.error = "HTTP %s: %s" % (e.code, e.reason)
            self._fill_headers(resp, e.headers)
            self._read_error_body(resp, e)
            if 300 <= e.code < 400:
                resp.kind = "redirect"
                resp.location = resp.h.get("location")
            return resp
        except Exception as e:  # noqa: BLE001 - 한 endpoint 실패가 크롤을 멈추면 안 된다.
            self._fill_exc(resp, e)
            return resp
        try:
            resp.status = getattr(r, "status", None) or r.getcode()
            self._fill_headers(resp, r.headers)
            self._read_body(resp, r, max_bytes, spool_dir)
        except Exception as e:  # noqa: BLE001 - 본문 읽기 중 timeout/연결 끊김
            self._drop_part()
            resp.body = None
            resp.raw_path = None
            resp.oversize = False
            self._fill_exc(resp, e)
        finally:
            try:
                r.close()
            except Exception:  # noqa: BLE001
                pass
        return resp

    @staticmethod
    def _fill_headers(resp, msg):
        if msg is None:
            return
        for k, v in msg.items():
            resp.headers[k] = (resp.headers[k] + ", " + v) if k in resp.headers else v
        resp.h = dict((k.lower(), v) for k, v in resp.headers.items())
        try:
            resp.links = list(msg.get_all("Link") or [])
        except Exception:  # noqa: BLE001
            resp.links = []

    @staticmethod
    def _read_error_body(resp, e):
        try:
            raw = e.read(ERROR_BODY_CAP)
        except Exception:  # noqa: BLE001
            raw = b""
        resp.body = _decode_body(raw, resp.h.get("content-encoding"))
        try:
            e.close()
        except Exception:  # noqa: BLE001
            pass

    def _drop_part(self):
        part, self._cur_part = self._cur_part, None
        if part:
            try:
                os.remove(part)
            except OSError:
                pass

    def _read_body(self, resp, r, max_bytes, spool_dir):
        ct = resp.h.get("content-type", "").lower()
        if "text/event-stream" in ct:       # 끝나지 않는 스트림 - 읽지 않는다
            resp.kind = "stream"
            resp.body = b""
            return
        cap = max_bytes if (max_bytes and max_bytes > 0) else None
        try:
            clen = int(resp.h.get("content-length", ""))
        except ValueError:
            clen = None
        if cap and clen is not None and clen > cap:
            resp.oversize, resp.size = True, clen
            return
        deadline = time.time() + max(self.timeout * 4, 120)
        texty = (not ct) or any(t in ct for t in ("json", "xml", "text", "html"))
        if texty or spool_dir is None:
            buf = bytearray()
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                buf.extend(chunk)
                if cap and len(buf) > cap:
                    resp.oversize, resp.size = True, len(buf)
                    return
                if time.time() > deadline:
                    raise socket.timeout("total read deadline exceeded")
            resp.body = _decode_body(bytes(buf), resp.h.get("content-encoding"))
            resp.size = len(resp.body)
            self.bytes_total += resp.size
            return
        # 바이너리: 디스크로 스트리밍 (메모리에 올리지 않는다)
        self._seq += 1
        part = os.path.join(spool_dir, ".dl-%d.part" % self._seq)
        self._cur_part = part
        total = 0
        with open(part, "wb") as f:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if cap and total > cap:
                    resp.oversize = True
                    break
                f.write(chunk)
                if time.time() > deadline:
                    raise socket.timeout("total read deadline exceeded")
        if resp.oversize:
            resp.size = total
            self._drop_part()
            return
        self._cur_part = None
        resp.raw_path, resp.size = part, total
        self.bytes_total += total

    @staticmethod
    def _fill_exc(resp, e):
        reason = getattr(e, "reason", None)
        inner = reason if isinstance(reason, BaseException) else e
        resp.error = ("%s: %s" % (type(inner).__name__, inner))[:300]
        resp.status = 0
        if isinstance(inner, (socket.timeout, TimeoutError)) or isinstance(e, (socket.timeout, TimeoutError)):
            resp.kind = "timeout"
        elif isinstance(inner, ssl.SSLError) or isinstance(e, ssl.SSLError) or isinstance(inner, ssl.CertificateError):
            resp.kind = "tls"
        elif isinstance(inner, (http.client.InvalidURL, ValueError, UnicodeError)):
            resp.status, resp.kind = -1, "url"
        else:
            resp.kind = "conn"


class AuthState(object):
    """세션/Basic 인증 상태. 비밀번호는 이 객체와 login() 요청 본문에만 존재하고 어디에도 기록되지 않는다."""

    def __init__(self, net, user, password, sessions_uri, sessions_source):
        self.net = net
        self.user = user
        self._password = password
        self.sessions_uri = sessions_uri
        self.sessions_source = sessions_source
        self.mode = "none"             # none | session | basic
        self.login_status = None
        self.login_error = None
        self.logout_status = None
        self.relogins = 0
        self.last_login = 0.0
        self.location = None

    def __repr__(self):                # 로그/예외 출력에 비밀번호가 새지 않게
        return "<AuthState mode=%s user=%s>" % (self.mode, self.user)

    def use_basic(self):
        raw = ("%s:%s" % (self.user, self._password)).encode("utf-8")
        self.net.basic = "Basic " + base64.b64encode(raw).decode("ascii")
        self.net.token = None
        self.mode = "basic"

    def login(self):
        """세션 생성 POST 1회. ok | no_token | rejected | limit | network | unsupported 를 돌려준다."""
        payload = json.dumps({"UserName": self.user, "Password": self._password}).encode("utf-8")
        self.net.token = None
        resp = self.net.request("POST", self.sessions_uri, JSON_ACCEPT, auth="none",
                                headers={"Content-Type": "application/json"}, body=payload)
        self.login_status = resp.status
        self.last_login = time.time()
        if 200 <= resp.status < 300:
            token = resp.h.get("x-auth-token")
            if not token:
                self.login_error = "2xx without X-Auth-Token"
                return "no_token"
            self.net.token = token
            self.net.basic = None
            self.location = self._session_location(resp)
            self.mode = "session"
            self.login_error = None
            return "ok"
        self.login_error = _error_detail(resp)
        if resp.status in (401, 403):
            return "rejected"
        if resp.status == 0:
            return "network"
        if _is_session_limit(resp):
            return "limit"
        return "unsupported"

    def login_with_retry(self):
        result = self.login()
        tries = 0
        while result == "limit" and tries < LOGIN_LIMIT_RETRIES:
            _sleep(min(BACKOFF_CAP, BACKOFF_BASE * (2 ** tries)))
            tries += 1
            result = self.login()
        return result

    @staticmethod
    def _session_location(resp):
        loc = resp.h.get("location")
        if loc:
            parts = urllib.parse.urlsplit(loc)
            path = _keep_path(parts.path + ("?" + parts.query if parts.query else ""))
            if path.startswith("/"):
                return path
        if resp.body:
            ok, data = _parse_json(resp.body)
            if ok and isinstance(data, dict) and isinstance(data.get("@odata.id"), str):
                return _keep_path(data["@odata.id"])
        return None

    def logout(self):
        """세션 종료 DELETE 1회 (finally 에서 반드시). 실패해도 예외를 내지 않는다."""
        if self.mode != "session" or not self.location or not self.net.token:
            return
        resp = self.net.request("DELETE", self.location, JSON_ACCEPT, timeout=10)
        self.logout_status = resp.status
        self.net.token = None


# ================================================================================================
# 크롤러
# ================================================================================================

_LIST_NAMES = ("absent", "not_gettable", "rejected", "outside_account", "device_error", "unresolved",
               "excluded", "skipped", "rehosted", "action_targets", "non_json", "binary",
               "count_mismatch", "accept_fallback", "wellknown")
_LIST_CAP = 5000
_PROBE_PREFER = ("Managers", "Systems", "Chassis", "AccountService", "SessionService", "UpdateService")


class Outcome(object):
    """fetch_resource 의 결과: 버킷 + 마지막 응답 + 시도 횟수."""

    def __init__(self, bucket, resp, attempts, note=""):
        self.bucket = bucket
        self.resp = resp
        self.attempts = attempts
        self.note = note


def _bucket(resp):
    """HTTP 결과 -> 판정 버킷. transient 만 재시도 대상이다."""
    st = resp.status
    if resp.kind == "stream":
        return "not_gettable"
    if 200 <= st < 300:
        return "ok"
    if st in (404, 410):
        return "absent"
    if st in (405, 501) or st == -1:
        return "not_gettable"
    if st in (401, 403):
        return "outside_account"
    if st in (408, 429) or st == 0 or 500 <= st < 600:
        return "transient"
    if st >= 400 and _is_session_limit(resp):
        return "transient"
    return "rejected"


class Crawler(object):
    def __init__(self, args, net, auth, password_source="none"):
        self.a = args
        self.net = net
        self.auth = auth
        self.password_source = password_source
        self.out = args.out
        self.root = _norm(args.root) or "/redfish/v1"
        self.fs = FsMapper(args.max_rel_path)
        self.excludes = [re.compile(p) for p in (args.exclude or [])]
        self.q = deque()
        self.seen = set()
        self.refs = OrderedDict()
        self.saved = OrderedDict()
        self.resume = {}
        self.prefetched = {}
        self.deferred = []
        self.sweep_done = False
        self.canary_path = None
        self.root_body = None
        self.protected_ok = 0
        self.unproven_401 = 0
        self.abort_reason = None
        self.abort_detail = ""
        self.interrupted = False
        self.in_cleanup = False
        self.processed = 0
        self.truncated = 0
        self.n_wellknown = 0
        self.exit_code = EXIT_COMPLETE
        self.t0 = time.time()
        self.started = _utcnow_iso()
        self.probe_info = None
        self._health = (0.0, True)
        self._old_handlers = {}
        self._dedupe = set()
        self.lists = dict((k, []) for k in _LIST_NAMES)
        self.counts = dict((k, 0) for k in _LIST_NAMES)
        self.cnt = {"ok": 0, "ok_empty": 0, "ok_raw": 0, "resumed": 0, "retries": 0, "files": 0}
        self.info = {"reachable": None, "auth_ok": None, "root_product": None,
                     "root_redfish_version": None, "realm": None, "tls_hint": False}
        self.firmware_versions = []

    # ---- 보조 ----------------------------------------------------------------------------------
    def _add(self, name, entry):
        self.counts[name] += 1
        if len(self.lists[name]) < _LIST_CAP:
            self.lists[name].append(entry)

    def _once(self, name, key, entry):
        mark = (name, key)
        if mark in self._dedupe:
            return
        self._dedupe.add(mark)
        self._add(name, entry)

    def abort(self, reason, detail=""):
        if not self.abort_reason:
            self.abort_reason = reason
            self.abort_detail = (detail or "")[:300]

    def _abs(self, rel):
        return os.path.join(self.out, *rel.split("/")) if rel else self.out

    # ---- 신호: SIGTERM/SIGHUP 도 Ctrl-C 와 같은 경로로 finally(세션 종료)를 거친다 ---------------------
    def _on_signal(self, signum, frame):
        if self.in_cleanup:
            return
        self.interrupted = True
        raise KeyboardInterrupt()

    def _install_signals(self):
        if threading.current_thread() is not threading.main_thread():
            return
        for name in ("SIGTERM", "SIGHUP"):
            sig = getattr(signal, name, None)
            if sig is None:
                continue
            try:
                self._old_handlers[sig] = signal.signal(sig, self._on_signal)
            except (ValueError, OSError):
                pass

    def _restore_signals(self):
        for sig, old in self._old_handlers.items():
            try:
                signal.signal(sig, old)
            except (ValueError, OSError, TypeError):
                pass
        self._old_handlers = {}

    # ---- 링크 큐 ---------------------------------------------------------------------------------
    def enqueue(self, raw, kind, key, ref):
        """발견한 링크를 정책(제외/재호스팅/cross-host)에 따라 큐에 넣는다. 접두사 가정 없이 절대경로면 따라간다."""
        if not isinstance(raw, str):
            return
        raw = raw.strip()
        if not raw:
            return
        if key in _POLICY_EXCLUDE_KEYS:
            self._once("excluded", raw, {"link": raw, "reason": "policy:%s" % key, "referrer": ref})
            return
        if kind == "target" and self.a.no_action_targets:
            self._once("excluded", raw, {"link": raw, "reason": "no-action-targets", "referrer": ref})
            return
        parts = urllib.parse.urlsplit(raw)
        link = raw
        rehost = False
        if parts.scheme and not parts.netloc:
            self._once("skipped", (raw, "non-path"), {"link": raw, "reason": "non-path", "referrer": ref})
            return
        if parts.netloc:
            if (parts.hostname or "").lower() != self.net.self_host:
                if not parts.path.startswith("/redfish/"):
                    self._once("skipped", (raw, "cross-host"),
                               {"link": raw, "reason": "cross-host", "referrer": ref})
                    return
                raw = parts.path + ("?" + parts.query if parts.query else "")
                rehost = True
        np = _norm(raw)
        if not np.startswith("/"):
            self._once("skipped", (link, "non-path"), {"link": link, "reason": "non-path", "referrer": ref})
            return
        if _SSE_PATH.search(np.split("?", 1)[0]):
            self._once("excluded", np, {"link": np, "reason": "policy:sse", "referrer": ref})
            return
        for rx in self.excludes:
            if rx.search(np):
                self._once("excluded", np, {"link": np, "reason": "user-exclude", "referrer": ref})
                return
        hit = self.refs.get(np)
        if hit is not None:
            hit["refs"] += 1
            return
        self.refs[np] = {"referrer": ref, "kind": kind, "key": key, "refs": 1}
        if rehost:
            self._add("rehosted", {"link": link, "path": np, "referrer": ref})
        self.q.append((np, kind, key, ref))

    # ---- 시작: 무인증 루트 -> 인증 확정 -----------------------------------------------------------
    def _request_retry(self, fetch_path, accept=JSON_ACCEPT, auth="default"):
        """전송 계층 실패(status 0)만 재시도하는 단순 GET. 시작 단계에서 쓴다."""
        resp = None
        for n in range(self.a.retries + 1):
            resp = self.net.request("GET", fetch_path, accept, auth=auth, timeout=self.a.timeout,
                                    max_bytes=self.a.max_bytes, spool_dir=self.out)
            if resp.status != 0 or n >= self.a.retries:
                break
            self.cnt["retries"] += 1
            _sleep(min(BACKOFF_CAP, BACKOFF_BASE * (2 ** n)))
        return resp

    def _sessions_uri(self):
        rb = self.root_body if isinstance(self.root_body, dict) else {}
        links = rb.get("Links")
        if isinstance(links, dict) and isinstance(links.get("Sessions"), dict):
            oid = links["Sessions"].get("@odata.id")
            if isinstance(oid, str) and oid:
                return _keep_path(oid), "Links.Sessions"
        ss = rb.get("SessionService")
        if isinstance(ss, dict) and isinstance(ss.get("@odata.id"), str) and ss["@odata.id"]:
            return _keep_path(ss["@odata.id"]).rstrip("/") + "/Sessions", "SessionService"
        return self.root + "/SessionService/Sessions", "default"

    def _probe_target(self):
        """Basic 확인용 보호 리소스: 루트가 알려준 컬렉션 중 Managers/Systems/Chassis 순, 없으면 루트."""
        rb = self.root_body if isinstance(self.root_body, dict) else {}
        cand = OrderedDict()
        for k, v in rb.items():
            if k == "Links" or not isinstance(v, dict):
                continue
            oid = v.get("@odata.id")
            if isinstance(oid, str) and oid:
                np = _norm(oid)
                if np.startswith("/") and np != self.root:
                    cand[k] = np
        for k in _PROBE_PREFER:
            if k in cand:
                return cand[k]
        if cand:
            return cand[sorted(cand)[0]]
        return self.root

    def _startup(self):
        os.makedirs(self.out, exist_ok=True)
        # 0) 무인증 ServiceRoot - detect/auth 경로 재구성용. 자격증명을 보내지 않으므로 잠금과 무관.
        out = self.fetch_resource(self.root, JSON_ACCEPT, auth="none", gate=False)
        resp = out.resp
        if resp.status == 0:
            self.info["tls_hint"] = (resp.kind == "tls")
            self.abort("unreachable", resp.error)
            return
        self.info["reachable"] = True
        body_obj = {}
        if resp.body:
            ok, val = _parse_json(resp.body)
            body_obj = val if ok else {"_non_json": resp.body[:4000].decode("utf-8", "replace")}
        try:
            _write_json(os.path.join(self.out, "_serviceroot_noauth.json"),
                        {"_status": resp.status, "body": body_obj})
        except (OSError, UnicodeError) as exc:
            _emit("[WARN] _serviceroot_noauth.json 저장 실패: %s" % exc, sys.stderr)
        if 200 <= resp.status < 300 and isinstance(body_obj, dict):
            self.root_body = body_obj
        # 0b) realm 캡처 (Session-only BMC 진단). 루트가 인증 게이트면 그 헤더에서, 공개면 루트가
        #     알려준 첫 링크를 무인증으로 한 번 찔러 401 이면 거기서. 하드코딩 경로 없음.
        if resp.status in (401, 403):
            self.info["realm"] = resp.h.get("www-authenticate")
        if not self.info["realm"] and isinstance(self.root_body, dict):
            ids = sorted(set(v for v, kind, _k in _collect_links(self.root_body)
                             if kind == "odata.id" and v.startswith("/")))
            for pid in ids:
                np = _norm(pid)
                if np and np != self.root:
                    r2 = self.net.request("GET", np, JSON_ACCEPT, auth="none", timeout=self.a.timeout)
                    if r2.status in (401, 403):
                        self.info["realm"] = r2.h.get("www-authenticate")
                    break
        self.auth.sessions_uri, self.auth.sessions_source = self._sessions_uri()
        self._establish_auth()

    def _establish_auth(self):
        """인증 상태기계. 401/403 을 부르는 자격증명 요청은 정상 경로에서 최대 2회(세션 POST + Basic 확인)다."""
        a = self.a
        if not a.user:
            self.auth.mode = "none"
            return
        result = None
        if a.auth in ("auto", "session"):
            result = self.auth.login_with_retry()
            if result == "ok":
                return
            if a.auth == "session":
                if result == "network":
                    self.abort("unreachable", "세션 로그인 요청 실패: %s" % (self.auth.login_error or ""))
                else:
                    reason = {"rejected": "credentials_rejected",
                              "limit": "session_limit_exceeded"}.get(result, "session_unsupported")
                    self.abort(reason, "세션 로그인 실패(status=%s, %s)" % (
                        self.auth.login_status, self.auth.login_error or result))
                return
            # auto: 세션 POST 의 401 은 Basic 전용 장비의 정상 응답일 수 있다 -> 단정하지 않고 Basic 으로 교차 확인
        self._basic_probe(result)

    def _basic_probe(self, post_result):
        self.auth.use_basic()
        target = self._probe_target()
        fetch_path = target + "/" if target == self.root else target
        resp = self._request_retry(fetch_path)
        st = resp.status
        self.probe_info = {"path": target, "status": st, "session_post": post_result,
                           "session_post_status": self.auth.login_status}
        if st == 0:
            self.info["tls_hint"] = (resp.kind == "tls")
            self.abort("unreachable", resp.error)
            return
        if st == 401:
            self.abort("credentials_rejected", "Basic 확인 요청이 401 (세션 POST: %s)" % (post_result or "생략"))
            return
        if st < 500 and st not in (408, 429):
            self.prefetched[_norm(target)] = resp   # 같은 요청이므로 BFS 에서 재사용 (이중 요청 방지)

    # ---- 단일 리소스 GET: 재시도/재협상/세션 만료 판정 ---------------------------------------------
    def fetch_resource(self, path, accept=JSON_ACCEPT, auth="default", retries=None, gate=True):
        a = self.a
        fetch_path = path + "/" if path == self.root else path
        pre = self.prefetched.pop(path, None) if auth == "default" else None
        left = a.retries if retries is None else retries
        timeout_left = TIMEOUT_RETRIES
        timeout = a.timeout
        attempts = 0
        n = 0
        relogged = False
        tried_406 = False
        while True:
            if pre is not None:
                resp, pre = pre, None
            else:
                resp = self.net.request("GET", fetch_path, accept, auth=auth, timeout=timeout,
                                        max_bytes=a.max_bytes, spool_dir=self.out)
                attempts += 1
                _sleep(a.delay)
            bucket = _bucket(resp)
            st = resp.status
            if bucket == "outside_account" and st == 401 and gate:
                if self.auth.mode == "session" and not relogged and self._session_expired(path):
                    relogged = True
                    if self._relogin():
                        continue
                elif self.auth.mode == "basic":
                    self._note_unproven_401()
            if bucket == "rejected" and st == 406 and not tried_406:
                tried_406 = True
                accept = ANY_ACCEPT
                self._once("accept_fallback", path, {"path": path, "accept": ANY_ACCEPT})
                continue
            can_retry = left > 0 and not self.abort_reason and not self.interrupted
            if bucket == "transient" and can_retry:
                if resp.kind == "timeout":
                    if timeout_left <= 0:
                        return Outcome(bucket, resp, attempts)
                    timeout_left -= 1
                    timeout = min(timeout * 2, TIMEOUT_CAP)
                left -= 1
                self.cnt["retries"] += 1
                wait = None
                if st in (429, 503):
                    wait = _retry_after_seconds(resp.h.get("retry-after"), RETRY_AFTER_CAP)
                if wait is None:
                    wait = min(BACKOFF_CAP, BACKOFF_BASE * (2 ** n))
                n += 1
                _sleep(wait)
                continue
            note = "after_relogin" if (relogged and bucket == "outside_account") else ""
            if resp.kind == "stream":
                note = "event-stream"
            return Outcome(bucket, resp, attempts, note)

    def _note_unproven_401(self):
        """Basic 모드에서 인증 성공이 한 번도 없는데 401 이 연속되면 비밀번호 문제로 보고 즉시 중단한다."""
        if self.protected_ok > 0:
            return
        self.unproven_401 += 1
        if self.unproven_401 >= 2:
            self.abort("credentials_rejected", "Basic 요청이 보호 리소스에서 연속 401 (인증 성공 0건)")

    def _canary_fetch_path(self):
        cp = self.canary_path or self.root
        return cp + "/" if cp == self.root else cp

    def _session_expired(self, path):
        """세션 모드의 401 이 토큰 만료인지, 이 리소스만 권한 밖인지 canary GET 으로 가른다."""
        if self.auth.relogins >= self.a.max_relogin or self.canary_path is None:
            return False
        if self.canary_path == path:
            return True
        c = self.net.request("GET", self._canary_fetch_path(), JSON_ACCEPT, timeout=self.a.timeout)
        return c.status == 401

    def _relogin(self):
        wait = RELOGIN_MIN_INTERVAL - (time.time() - self.auth.last_login)
        if wait > 0:
            _sleep(wait)
        self.auth.relogins += 1
        result = self.auth.login_with_retry()
        if result == "ok":
            return True
        self.abort("auth_lost", "세션 재로그인 실패(%s, status=%s)" % (result, self.auth.login_status))
        return False

    def _healthy(self):
        """장비가 지금 다른 요청에는 정상 응답하는가 (이미 받은 리소스 1건 재요청)."""
        stamp, last = self._health
        if not last and (time.time() - stamp) < HEALTH_CACHE_SECONDS:
            return False
        r = self.net.request("GET", self._canary_fetch_path(), JSON_ACCEPT, timeout=self.a.timeout)
        ok = 200 <= r.status < 300
        self._health = (time.time(), ok)
        return ok

    def _finalize_failure(self, d):
        """재시도와 최종 sweep 뒤에도 실패한 리소스. 장비가 다른 요청에는 정상이면 장비 측 결함(device_error),
        장비/망이 불안정하면 unresolved(미완료)로 가른다."""
        resp = d["resp"]
        entry = {"path": d["path"], "status": resp.status, "kind": resp.kind or "http",
                 "error": (resp.error or "")[:300], "attempts": d["attempts"], "referrer": d["ref"]}
        detail = _error_detail(resp)
        if detail and detail != entry["error"]:
            entry["detail"] = detail
        stable = (not self.abort_reason) and (not self.interrupted) and self._healthy()
        self._add("device_error" if stable else "unresolved", entry)

    # ---- 리소스 한 건 처리 --------------------------------------------------------------------------
    def _process(self, item):
        path, kind, key, ref = item
        ent = self.resume.get(path)
        if ent is not None and self._reuse(path, kind, key, ref, ent):
            return
        accept = XML_ACCEPT if (kind == "wellknown" and key == "$metadata") else JSON_ACCEPT
        out = self.fetch_resource(path, accept)
        self._dispatch(path, kind, key, ref, accept, out, 0)

    def _dispatch(self, path, kind, key, ref, accept, out, prior):
        bucket, resp = out.bucket, out.resp
        if kind == "wellknown":
            self.n_wellknown += 1
            saved = self._handle_ok(path, kind, key, ref, resp) if bucket == "ok" else False
            self._add("wellknown", {"path": path, "status": resp.status, "bucket": bucket, "saved": saved})
            return
        if kind == "target":
            self._add("action_targets", {"path": path, "status": resp.status, "bucket": bucket})
        if bucket == "ok":
            self._handle_ok(path, kind, key, ref, resp)
        elif bucket == "transient":
            d = {"path": path, "kind": kind, "key": key, "ref": ref, "accept": accept,
                 "resp": resp, "attempts": prior + out.attempts}
            if self.sweep_done or self.abort_reason or self.interrupted:
                self._finalize_failure(d)
            else:
                self.deferred.append(d)
        else:
            self._record(bucket, path, kind, key, ref, resp, out.note)

    def _record(self, bucket, path, kind, key, ref, resp, note=""):
        entry = {"path": path, "status": resp.status, "referrer": ref, "kind": kind, "key": key}
        detail = _error_detail(resp)
        if detail:
            entry["detail"] = detail
        if note:
            entry["note"] = note
        if bucket == "absent" and _VOLATILE_PATH.search(path):
            entry["hint"] = "volatile"
        if bucket == "not_gettable" and resp.h.get("allow"):
            entry["allow"] = resp.h.get("allow")
        if resp.location:
            entry["location"] = resp.location
        self._add(bucket, entry)

    @staticmethod
    def _remove(path):
        if path:
            try:
                os.remove(path)
            except OSError:
                pass

    @staticmethod
    def _headers_obj(resp):
        d = OrderedDict()
        d["_status"] = resp.status
        d.update(_filter_headers(resp.headers))
        return d

    def _save(self, path, saved_type, data, body, resp, content_type):
        rel = self.fs.dir_for(path)
        adir = self._abs(rel)
        os.makedirs(adir, exist_ok=True)
        index = os.path.join(adir, "index.json")
        if saved_type == "json":
            _write_json(index, data)
        elif saved_type == "empty":
            _write_json(index, {"_empty": True, "_path": path})
        else:
            name = "raw" + _ext_for(content_type, path)
            dest = os.path.join(adir, name)
            stub = OrderedDict([("_non_json", True), ("_path", path), ("_content_type", content_type),
                                ("_raw_file", name)])
            if resp.raw_path is not None:
                size = resp.size
                os.replace(resp.raw_path, dest)
                resp.raw_path = None
                if resp.h.get("content-encoding"):
                    stub["_content_encoding"] = resp.h.get("content-encoding")
            else:
                _write_atomic(dest, body or b"")
                size = len(body or b"")
            stub["_bytes"] = size
            _write_json(index, stub)
        _write_json(os.path.join(adir, "headers.json"), self._headers_obj(resp))
        return rel

    def _handle_ok(self, path, kind, key, ref, resp):
        """2xx 응답을 저장하고 링크를 큐에 넣는다. 저장하면 True."""
        wk = (kind == "wellknown")
        if resp.oversize:
            self._add("excluded", {"link": path, "reason": "oversize", "bytes": resp.size,
                                   "limit": self.a.max_bytes, "referrer": ref})
            return False
        ct = resp.h.get("content-type", "")
        body, data, saved_type = resp.body, None, None
        if resp.raw_path is not None and resp.size <= (16 << 20):
            # Content-Type 이 거짓말인 JSON 구제: 바이너리로 받았어도 JSON 이면 링크를 따라간다.
            try:
                with open(resp.raw_path, "rb") as f:
                    blob = f.read()
            except OSError:
                blob = b""
            ok, val = _parse_json(blob)
            if ok and isinstance(val, (dict, list)):
                body, data, saved_type = blob, val, "json"
                self._remove(resp.raw_path)
                resp.raw_path = None
        if saved_type is None:
            if resp.raw_path is not None:
                saved_type = "raw"
            elif not body:
                saved_type = "empty"
            else:
                ok, val = _parse_json(body)
                if ok:
                    saved_type, data = "json", val
                else:
                    saved_type = "raw"
        try:
            rel = self._save(path, saved_type, data, body, resp, ct)
        except (OSError, UnicodeError) as exc:
            self._remove(resp.raw_path)
            resp.raw_path = None
            self._add("unresolved", {"path": path, "status": resp.status, "kind": "save",
                                     "error": "save: %s" % exc, "referrer": ref})
            return False
        self.saved[path] = {"dir": rel, "type": saved_type}
        self.cnt["files"] += 1
        links = []
        if saved_type == "json":
            links.extend(_collect_links(data))
        links.extend((t, "link_header", "Link") for t in _link_header_targets(resp.links))
        if saved_type == "raw":
            self._add("non_json", {"path": path, "content_type": ct, "bytes": resp.size or len(body or b"")})
            if wk and key == "$metadata" and body:
                text = body[:(20 << 20)].decode("utf-8", "replace")
                links.extend((u, "metadata_ref", "Uri") for u in _XML_URI_ATTR.findall(text))
        self._after_ok(path, kind, key, ref, saved_type, data, links)
        return True

    def _after_ok(self, path, kind, key, ref, saved_type, data, links, resumed=False):
        if self.info["reachable"] is None:
            self.info["reachable"] = True
        if kind != "wellknown":
            self.cnt[{"json": "ok", "empty": "ok_empty", "raw": "ok_raw"}[saved_type]] += 1
            if resumed:
                self.cnt["resumed"] += 1
            if path != self.root:
                self.protected_ok += 1
                self.unproven_401 = 0
                self.info["auth_ok"] = True
                if self.canary_path is None:
                    self.canary_path = path
            elif isinstance(data, dict):
                self.info["root_product"] = data.get("Product")
                self.info["root_redfish_version"] = data.get("RedfishVersion")
                if self.root_body is None:
                    self.root_body = data
            if isinstance(data, dict):
                if data.get("Version") is not None and "Updateable" in data:
                    self.firmware_versions.append({"name": data.get("Name"), "version": data.get("Version")})
                self._check_count(path, data)
        for value, lkind, lkey in links:
            self.enqueue(value, lkind, lkey, path)

    def _check_count(self, path, data):
        """Members@odata.count 가 실제 멤버 수보다 큰데 nextLink 가 없으면 조용한 멤버 손실 후보로 기록한다."""
        members, declared = data.get("Members"), data.get("Members@odata.count")
        if not isinstance(members, list) or not isinstance(declared, int) or "?" in path:
            return
        if any(k.endswith("@odata.nextLink") for k in data):
            return
        if declared > len(members):
            self._add("count_mismatch", {"path": path, "declared": declared, "actual": len(members)})

    # ---- --resume: 이전 실행이 남긴 2xx 저장본 재사용 ----------------------------------------------------
    def _scan_tree(self):
        """_fsmap.json 이 없는 트리(v1 산출물, 강제 종료)에서 저장본을 복원한다."""
        found = {}
        for root, _dirs, files in os.walk(self.out):
            if "index.json" not in files:
                continue
            rel = os.path.relpath(root, self.out).replace(os.sep, "/")
            rel = "" if rel == "." else rel
            try:
                with open(os.path.join(root, "index.json"), "rb") as f:
                    ok, data = _parse_json(f.read())
            except OSError:
                continue
            if not ok or not isinstance(data, dict):
                continue
            oid = data.get("@odata.id")
            if not isinstance(oid, str):
                marked = data.get("_non_json") is True or data.get("_empty") is True
                oid = data.get("_path") if marked else None
            if isinstance(oid, str) and oid:
                found[_norm(oid) or "/"] = {"dir": rel, "type": "json"}
        return found

    def _load_resume(self):
        entries = {}
        fp = os.path.join(self.out, "_fsmap.json")
        if os.path.isfile(fp):
            try:
                with open(fp, "rb") as f:
                    ok, data = _parse_json(f.read())
                if ok and isinstance(data, dict) and isinstance(data.get("paths"), dict):
                    entries = data["paths"]
            except OSError:
                entries = {}
        if not entries:
            entries = self._scan_tree()
        good = {}
        for path, ent in entries.items():
            if not isinstance(ent, dict) or not isinstance(ent.get("dir"), str):
                continue
            if os.path.isfile(os.path.join(self._abs(ent["dir"]), "index.json")):
                good[path] = ent
                self.fs.seed(path, ent["dir"])
        self.resume = good

    def _reuse(self, path, kind, key, ref, ent):
        """저장본이 온전한 2xx 면 HTTP 없이 디스크에서 읽어 링크만 이어 따라간다. 재사용하면 True."""
        adir = self._abs(ent["dir"])
        try:
            with open(os.path.join(adir, "index.json"), "rb") as f:
                ok, data = _parse_json(f.read())
            with open(os.path.join(adir, "headers.json"), "rb") as f:
                okh, hdr = _parse_json(f.read())
        except OSError:
            return False
        if not ok or not okh or not isinstance(hdr, dict):
            return False
        status = hdr.get("_status")
        if not isinstance(status, int) or not 200 <= status < 300:
            return False
        stub = isinstance(data, dict) and data.get("_non_json") is True
        empty = isinstance(data, dict) and data.get("_empty") is True
        links = []
        if stub:
            rawf = os.path.join(adir, str(data.get("_raw_file", "")))
            if not os.path.isfile(rawf) or os.path.getsize(rawf) != data.get("_bytes", -1):
                return False
            saved_type = "raw"
        elif empty:
            saved_type = "empty"
        else:
            saved_type = "json"
            links.extend(_collect_links(data))
        if hdr.get("Link"):
            links.extend((t, "link_header", "Link") for t in _link_header_targets([hdr.get("Link")]))
        self.saved[path] = {"dir": ent["dir"], "type": saved_type}
        self.cnt["files"] += 1
        if kind == "wellknown":
            self.n_wellknown += 1
            self._add("wellknown", {"path": path, "status": status, "bucket": "ok", "saved": True,
                                    "resumed": True})
        self._after_ok(path, kind, key, ref, saved_type, data if saved_type == "json" else None,
                       links, resumed=True)
        return True

    # ---- 시드 / 메인 루프 / sweep ------------------------------------------------------------------
    def _seed(self):
        if self.a.resume:
            self._load_resume()
        self.refs[self.root] = {"referrer": None, "kind": "root", "key": "", "refs": 1}
        self.q.append((self.root, "root", "", None))
        seeds = []
        if self.root.startswith("/redfish"):
            seeds.append(("/redfish", "redfish"))
        seeds.append((self.root + "/odata", "odata"))
        seeds.append((self.root + "/$metadata", "$metadata"))
        for raw, name in seeds:
            np = _norm(raw)
            if np not in self.refs:
                self.refs[np] = {"referrer": None, "kind": "wellknown", "key": name, "refs": 1}
                self.q.append((np, "wellknown", name, None))

    def _loop(self):
        while self.q and not self.abort_reason and not self.interrupted:
            if len(self.seen) >= self.a.max:
                break
            item = self.q.popleft()
            if item[0] in self.seen:
                continue
            self.seen.add(item[0])
            try:
                self._process(item)
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # noqa: BLE001 - 한 리소스의 내부 오류가 전체를 멈추면 안 된다.
                self._internal_error(item, exc)
            self._tick()

    def _internal_error(self, item, exc):
        self._add("unresolved", {"path": item[0], "status": 0, "kind": "internal",
                                 "error": "internal: %s: %s" % (type(exc).__name__, exc),
                                 "referrer": item[3]})
        tag = type(exc).__name__
        if ("reported", tag) not in self._dedupe:
            self._dedupe.add(("reported", tag))
            _emit("[WARN] 내부 오류(%s) %s - 계속 진행합니다" % (tag, item[0]), sys.stderr)
            traceback.print_exc(file=sys.stderr)

    def _tick(self):
        self.processed += 1
        n = self.a.progress
        if n and not self.a.quiet and self.processed % n == 0:
            done_ok = self.cnt["ok"] + self.cnt["ok_empty"] + self.cnt["ok_raw"]
            _emit("[progress] done=%d queued=%d ok=%d absent=%d deferred=%d elapsed=%ds" % (
                self.processed, len(self.q), done_ok, self.counts["absent"], len(self.deferred),
                int(time.time() - self.t0)), sys.stderr)
        if self.processed % 500 == 0:
            self._checkpoint()

    def _sweep(self):
        """BFS 가 끝난 뒤 일시 오류로 미뤄 둔 리소스를 한 번 더 훑는다 (망/장비가 회복했을 수 있다)."""
        if not self.deferred or self.abort_reason or self.interrupted:
            return
        _sleep(SWEEP_PAUSE)
        pending, self.deferred = self.deferred, []
        self.sweep_done = True
        retries = max(1, self.a.retries // 2)
        for d in pending:
            if self.abort_reason or self.interrupted:
                self._finalize_failure(d)
                continue
            out = self.fetch_resource(d["path"], d["accept"], retries=retries)
            self._dispatch(d["path"], d["kind"], d["key"], d["ref"], d["accept"], out, d["attempts"])

    def _drain_unfinished(self):
        self.truncated = len(self.q)
        leftover, self.deferred = self.deferred, []
        for d in leftover:
            self._finalize_failure(d)
        try:
            for name in os.listdir(self.out):
                if name.startswith(".dl-") and name.endswith(".part"):
                    self._remove(os.path.join(self.out, name))
        except OSError:
            pass

    def run(self):
        self._install_signals()
        try:
            self._startup()
            if not self.abort_reason:
                self._seed()
                self._loop()
                self._sweep()
                self._loop()
        except KeyboardInterrupt:
            self.interrupted = True
        except Exception as exc:  # noqa: BLE001
            self.abort("internal_error", "%s: %s" % (type(exc).__name__, exc))
            _emit("[CRIT] 내부 오류로 중단합니다: %s" % self.abort_detail, sys.stderr)
            traceback.print_exc(file=sys.stderr)
        finally:
            self.in_cleanup = True
            self._restore_signals()
            try:
                self._drain_unfinished()
            except Exception:  # noqa: BLE001
                pass
            try:
                self.auth.logout()
            except Exception:  # noqa: BLE001
                pass
            manifest = self._write_outputs()
        _print_summary(manifest, self.out)
        return self.exit_code

    # ---- 판정 / 출력 --------------------------------------------------------------------------------
    def _fetched_ok(self):
        return self.cnt["ok"] + self.cnt["ok_empty"] + self.cnt["ok_raw"]

    def _verdict(self):
        """(result, exit_code). unresolved 와 truncated 만 미완료 사유다. 나머지 버킷은 정보다."""
        if self.abort_reason in AUTH_ABORTS:
            return "ABORT", EXIT_AUTH
        if self.abort_reason == "unreachable":
            return "ABORT", EXIT_UNREACHABLE
        if self.abort_reason:
            return "ABORT", EXIT_INCOMPLETE
        if self.interrupted:
            return "INCOMPLETE", EXIT_INTERRUPTED
        if self._fetched_ok() == 0:
            return "EMPTY", EXIT_EMPTY
        strict_fail = bool(self.a.strict) and self.counts["device_error"] > 0
        if self.counts["unresolved"] > 0 or self.truncated > 0 or strict_fail:
            return "INCOMPLETE", EXIT_INCOMPLETE
        return "COMPLETE", EXIT_COMPLETE

    def _fsmap_obj(self):
        return {"fsmap_schema": 1, "paths": dict(self.saved)}

    def _links_obj(self):
        return {"links_schema": 1, "paths": dict(self.refs)}

    def _checkpoint(self):
        try:
            _write_json(os.path.join(self.out, "_fsmap.json"), self._fsmap_obj())
        except (OSError, UnicodeError):
            pass

    def _build_manifest(self):
        a, c, n, lists = self.a, self.cnt, self.counts, self.lists
        result, code = self._verdict()
        self.exit_code = code
        longest = max([len(v) for v in self.fs.by_path.values()] or [0])
        summary = OrderedDict([
            ("ok", c["ok"]), ("ok_empty", c["ok_empty"]), ("ok_raw", c["ok_raw"]),
            ("absent", n["absent"]), ("not_gettable", n["not_gettable"]), ("rejected", n["rejected"]),
            ("outside_account", n["outside_account"]), ("device_error", n["device_error"]),
            ("unresolved", n["unresolved"]), ("excluded", n["excluded"]), ("rehosted", n["rehosted"]),
            ("skipped", n["skipped"]), ("redirected", len(self.net.redirected)),
            ("resumed_from_disk", c["resumed"]), ("requests", self.net.requests), ("retries", c["retries"]),
            ("bytes_total", self.net.bytes_total), ("count_mismatch", n["count_mismatch"]),
            ("files_expected", c["files"]), ("max_rel_path_chars", longest)])
        m = {
            "manifest_schema": MANIFEST_SCHEMA, "tool_version": TOOL_VERSION,
            "python_version": sys.version.split()[0], "platform": sys.platform,
            "started": self.started, "finished": _utcnow_iso(),
            "duration_s": round(time.time() - self.t0, 1),
            "host": a.host, "scheme": a.scheme, "root": self.root,
            "options": {"auth": a.auth, "retries": a.retries, "delay": a.delay, "timeout": a.timeout,
                        "verify": bool(a.verify), "legacy_tls": bool(a.legacy_tls), "max": a.max,
                        "max_bytes_per_resource": a.max_bytes, "max_rel_path": a.max_rel_path,
                        "max_relogin": a.max_relogin, "exclude": list(a.exclude or []),
                        "no_action_targets": bool(a.no_action_targets), "resume": bool(a.resume),
                        "strict": bool(a.strict), "use_env_proxy": bool(a.use_env_proxy),
                        "user": a.user, "password_source": self.password_source},
            "reachable": self.info["reachable"], "auth_ok": self.info["auth_ok"],
            "root_product": self.info["root_product"],
            "root_redfish_version": self.info["root_redfish_version"], "realm": self.info["realm"],
            "auth_mode": self.auth.mode,
            "session": {"sessions_uri": self.auth.sessions_uri, "source": self.auth.sessions_source,
                        "login_status": self.auth.login_status, "login_error": self.auth.login_error,
                        "relogins": self.auth.relogins, "logout_status": self.auth.logout_status},
            "basic_probe": self.probe_info,
            "result": result, "exit_code": code, "abort_reason": self.abort_reason,
            "abort_detail": self.abort_detail, "interrupted": self.interrupted,
            "complete_with_exclusions": result == "COMPLETE" and (n["excluded"] > 0 or n["device_error"] > 0),
            "tls_hint": self.info["tls_hint"],
            "discovered": len(self.seen) - self.n_wellknown, "fetched_ok": self._fetched_ok(),
            "truncated": self.truncated, "firmware_versions": self.firmware_versions,
            "summary": summary,
            "redirected": self.net.redirected,
            "failed": lists["unresolved"], "auth_failures": lists["outside_account"],
            "_aliases": {"failed": "unresolved", "auth_failures": "outside_account"},
        }
        for name in _LIST_NAMES:
            m[name] = lists[name]
        return m

    def _write_outputs(self):
        manifest = self._build_manifest()
        for name, obj in (("_manifest.json", manifest), ("_fsmap.json", self._fsmap_obj()),
                          ("_links.json", self._links_obj())):
            try:
                _write_json(os.path.join(self.out, name), obj)
            except Exception as exc:  # noqa: BLE001 - 디스크/경로 문제여도 진단은 stderr 로 남긴다.
                _emit("[WARN] %s 저장 실패 (%s)" % (name, exc), sys.stderr)
                if name == "_manifest.json":
                    _emit(json.dumps(manifest, indent=2, ensure_ascii=True, default=str), sys.stderr)
        return manifest


# ================================================================================================
# 요약 출력 / 여러 호스트 요약 / CLI
# ================================================================================================

_ABORT_HELP = {
    "credentials_rejected": "계정/비밀번호를 확인하세요. 요청을 1~2회만 보내고 중단했으므로 계정 잠금 위험은 낮습니다.",
    "session_unsupported": "이 장비는 세션 로그인을 받지 않습니다. --auth basic 으로 다시 실행하세요.",
    "session_limit_exceeded": "BMC 세션 한도가 찼습니다. 잠시 뒤 다시 실행하거나 --auth basic 을 쓰세요.",
    "auth_lost": "크롤 도중 세션을 되살리지 못했습니다. 계정 상태를 확인한 뒤 같은 -D 로 --resume 하세요.",
    "unreachable": "도달/방화벽/포트(443)를 확인하세요.",
    "internal_error": "도구 내부 오류입니다. stderr 의 traceback 을 공유해 주세요.",
}


def _print_summary(m, out_dir):
    s = m["summary"]
    result = m["result"]
    bar = "=" * 64
    say = _emit
    say(bar)
    say("  REDFISH FULL MIRROR v%s - %s        RESULT=%s" % (TOOL_VERSION, m["host"], result))
    say(bar)
    say("  reachable / auth_ok   : %s / %s   (auth_mode=%s, relogins=%s)" % (
        m["reachable"], m["auth_ok"], m["auth_mode"], m["session"]["relogins"]))
    say("  root product          : %s  (RedfishVersion=%s)" % (m["root_product"], m["root_redfish_version"]))
    say("  realm                 : %s" % m["realm"])
    say("  discovered            : %d   fetched 2xx : %d (json=%d empty=%d raw=%d, resumed=%d)" % (
        m["discovered"], m["fetched_ok"], s["ok"], s["ok_empty"], s["ok_raw"], s["resumed_from_disk"]))
    say("  absent (404/410)      : %-5d [INFO] 장비가 링크는 냈지만 존재하지 않음 - 오류 아님 (absent[].referrer)"
        % s["absent"])
    say("  not_gettable (405/501): %-5d [INFO] 액션 주소 등 GET 불가 - 정상" % s["not_gettable"])
    say("  rejected (400/406/..) : %-5d [INFO] 장비가 요청을 거절 - 재시도하지 않음" % s["rejected"])
    say("  outside_account       : %-5d [INFO] 계정 권한 밖(401/403) - 재시도하지 않음" % s["outside_account"])
    say("  device_error          : %-5d [INFO] 장비가 반복해서 5xx/무응답 (다른 요청은 정상) - 장비 측 결함 후보"
        % s["device_error"])
    say("  unresolved            : %-5d %s" % (s["unresolved"], "[OK]" if not s["unresolved"] else "[FAIL]"))
    say("  excluded / skipped    : %d / %d   (정책 제외, cross-host 등)   rehosted: %d   redirected: %d" % (
        s["excluded"], s["skipped"], s["rehosted"], s["redirected"]))
    if s["count_mismatch"]:
        say("  [INFO] Members@odata.count 불일치 컬렉션 %d건 - manifest count_mismatch 참조" % s["count_mismatch"])
    say("  requests / retries    : %d / %d   duration: %ss   bytes: %d" % (
        s["requests"], s["retries"], m["duration_s"], s["bytes_total"]))
    say("  output                : %s" % os.path.abspath(out_dir))
    if m["tls_hint"]:
        say("  [HINT] TLS 핸드셰이크 실패 - 구형 BMC 면 --legacy-tls 로 재시도하세요 (OS crypto-policy 가 TLS1.0/1.1 을"
            " 막으면 LEGACY 정책 필요).")
    if m["abort_reason"]:
        say("  [CRIT] 중단: %s - %s" % (m["abort_reason"], m["abort_detail"]))
        say("         %s" % _ABORT_HELP.get(m["abort_reason"], ""))
    if m["unresolved"]:
        say("  [FAIL] 미해결 %d건 (상위 10건):" % len(m["unresolved"]))
        for r in m["unresolved"][:10]:
            say("      %s  %s  (%s)" % (r.get("status"), r.get("path"), r.get("error")))
        say("         같은 -D 로 --resume 을 붙여 다시 실행하면 이 항목만 다시 시도합니다.")
    if m["truncated"]:
        say("  [WARN] 큐에 %d개가 남은 채 끝났습니다 (--max 상한/중단). --resume 으로 이어받으세요." % m["truncated"])
    if s["device_error"] and not m["abort_reason"]:
        say("  [INFO] device_error 는 오류로 보지 않습니다. 의심되면 --resume 으로 이 항목만 다시 시도하세요.")
    if result == "COMPLETE":
        say("  [OK] RESULT=COMPLETE - 이 계정으로 닿는 모든 GET 리소스를 저장했습니다.")
    elif result == "EMPTY":
        say("  [FAIL] RESULT=EMPTY - 2xx 응답 0건. 도달/인증/Redfish 활성화(RMC 라이선스)부터 확인하세요.")
    elif result == "INCOMPLETE":
        say("  [FAIL] RESULT=INCOMPLETE - 위 항목을 처리한 뒤 --resume 으로 다시 실행하세요.")
    else:
        say("  [FAIL] RESULT=ABORT")


def summarize(dirs):
    """여러 호스트의 _manifest.json 을 표 하나로 요약한다. 모두 COMPLETE 면 0, 아니면 1."""
    totals = OrderedDict([("COMPLETE", 0), ("INCOMPLETE", 0), ("EMPTY", 0), ("ABORT", 0), ("NO_MANIFEST", 0)])
    fmt = "  %-24s %-11s %7s %7s %8s %8s %8s %9s %-9s"
    _emit(fmt % ("host", "RESULT", "fetched", "absent", "not_get", "reject", "outside", "unresolv", "auth"))
    for d in dirs:
        try:
            with open(os.path.join(d, "_manifest.json"), "rb") as f:
                ok, m = _parse_json(f.read())
        except OSError:
            ok, m = False, None
        if not ok or not isinstance(m, dict):
            totals["NO_MANIFEST"] += 1
            _emit(fmt % (d[-24:], "NO_MANIFEST", "-", "-", "-", "-", "-", "-", "-"))
            continue
        s = m.get("summary") or {}
        res = m.get("result")
        if not res:  # v1 manifest: failed 목록이 비었는지로만 판단한다
            res = "EMPTY" if not m.get("fetched_ok") else ("INCOMPLETE" if m.get("failed") else "COMPLETE")
        totals[res] = totals.get(res, 0) + 1
        _emit(fmt % (str(m.get("host") or d)[-24:], res, m.get("fetched_ok", 0),
                     s.get("absent", "-"), s.get("not_gettable", "-"), s.get("rejected", "-"),
                     s.get("outside_account", "-"), s.get("unresolved", len(m.get("failed") or [])),
                     m.get("auth_mode", "-")))
        if m.get("abort_reason"):
            _emit("      [CRIT] %s - %s" % (m.get("abort_reason"), m.get("abort_detail")))
    _emit("  전체: " + " / ".join("%s %d" % (k, v) for k, v in totals.items()))
    return 0 if totals["COMPLETE"] == len(dirs) else 1


def build_parser():
    ap = argparse.ArgumentParser(description="Redfish 전수 재귀 미러 v2 (자동 발견)")
    ap.add_argument("--host", "-r", help="ip[:port] 또는 [ipv6]:port")
    ap.add_argument("--user", "-u", default="")
    ap.add_argument("--password", "-p", default="",
                    help="비밀번호 (ps 에 노출되므로 --password-env 권장)")
    ap.add_argument("--password-env", default=None, metavar="VAR",
                    help="비밀번호를 읽을 환경변수 이름 (기본 BMC_PASSWORD)")
    ap.add_argument("--password-file", default=None, metavar="PATH", help="비밀번호 파일 (첫 줄)")
    ap.add_argument("--out", "-D", help="출력 디렉터리")
    ap.add_argument("--scheme", choices=["https", "http"], default="https")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--verify", action="store_true", help="TLS 인증서 검증 (기본 off - self-signed BMC)")
    ap.add_argument("--max", type=int, default=200000, help="안전 상한(리소스 수)")
    ap.add_argument("--root", default="/redfish/v1/", help="시작 경로")
    ap.add_argument("--auth", choices=["auto", "session", "basic"], default="auto",
                    help="auto=세션 우선 후 Basic, session=세션만, basic=Basic 만 (세션 POST 생략)")
    ap.add_argument("--max-relogin", type=int, default=2, help="세션 만료 시 재로그인 최대 횟수")
    ap.add_argument("--retries", type=int, default=3, help="일시 오류 인라인 재시도 횟수")
    ap.add_argument("--delay", type=float, default=0.0, help="요청 사이 대기(초). BMC 부하가 걱정될 때")
    ap.add_argument("--legacy-tls", action="store_true", help="TLS 1.0/1.1 만 되는 구형 BMC 허용")
    ap.add_argument("--exclude", action="append", default=[], metavar="REGEX", help="경로 제외 정규식 (반복 가능)")
    ap.add_argument("--no-action-targets", action="store_true", help="Actions target 주소를 GET 하지 않음")
    ap.add_argument("--resume", action="store_true", help="같은 -D 의 2xx 저장본을 재사용하고 빈 곳만 받음")
    ap.add_argument("--strict", action="store_true", help="device_error 도 INCOMPLETE 로 취급")
    ap.add_argument("--progress", type=int, default=100, help="N개마다 진행 상황을 stderr 로 (0=끔)")
    ap.add_argument("--quiet", action="store_true", help="진행 상황 출력 끔")
    ap.add_argument("--max-bytes-per-resource", dest="max_bytes", type=int, default=64 * 1024 * 1024,
                    help="리소스 1건 최대 바이트 (0=무제한). 초과분은 받지 않고 excluded 로 기록 (펌웨어 이미지 등)")
    ap.add_argument("--max-rel-path", type=int, default=200, help="출력 상대경로 최대 글자 수 (Windows MAX_PATH 대비)")
    ap.add_argument("--use-env-proxy", action="store_true", help="환경변수 프록시 사용 (기본은 무시)")
    ap.add_argument("--summarize", nargs="+", metavar="DIR", help="여러 출력 폴더의 manifest 를 표로 요약하고 종료")
    return ap


def _prepare_stdio():
    """콘솔 인코딩이 한글을 못 담는 경우(C 로캘 ASCII 등)에도 --help / 요약 출력이 죽지 않게 한다.

    utf-8 / cp949 계열은 한글을 표현할 수 있으므로 인코딩을 바꾸지 않고(바꾸면 cp949 콘솔이 깨진다) 오류만
    replace 로 완화한다. 그 외(ASCII 등)는 Python 3.7+ 면 reconfigure 로, 3.6 에는 reconfigure 가 없으므로
    UTF-8 래퍼로 교체한다 (원본은 sys.__stdout__ 이 계속 잡고 있어 버퍼가 닫히지 않는다).
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        enc = (getattr(stream, "encoding", None) or "").lower().replace("-", "").replace("_", "")
        keep = enc in ("utf8", "cp949", "euckr", "ms949", "uhc")
        try:
            if keep:
                stream.reconfigure(errors="replace")            # Python 3.7+
            else:
                stream.reconfigure(encoding="utf-8", errors="replace")
            continue
        except Exception:  # noqa: BLE001
            pass
        buf = getattr(stream, "buffer", None)
        if buf is not None and not keep:
            try:
                setattr(sys, name, io.TextIOWrapper(buf, encoding="utf-8", errors="replace",
                                                    line_buffering=True))
            except Exception:  # noqa: BLE001
                pass


def _resolve_password(args):
    """(비밀번호 또는 None, 출처). 출처 문자열에는 비밀번호가 들어가지 않는다."""
    if args.password:
        return args.password, "argv"
    if args.password_file:
        try:
            with open(args.password_file, encoding="utf-8") as f:
                return f.readline().rstrip("\r\n"), "file"
        except OSError as exc:
            return None, "file-error: %s" % exc
    name = args.password_env or "BMC_PASSWORD"
    if name in os.environ:
        return os.environ[name], "env:" + name
    if args.password_env:
        return None, "env-missing: %s" % name
    return "", "none"


def main(argv=None):
    _prepare_stdio()
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.summarize:
        return summarize(args.summarize)
    if not args.host or not args.out:
        ap.error("-r/--host 와 -D/--out 은 필수입니다")
    if args.retries < 0 or args.timeout <= 0 or args.max_relogin < 0:
        ap.error("--retries/--max-relogin 은 0 이상, --timeout 은 1 이상이어야 합니다")
    password, source = _resolve_password(args)
    if password is None:
        _emit("[CRIT] 비밀번호를 읽지 못했습니다 (%s)" % source, sys.stderr)
        return EXIT_AUTH
    if source == "argv":
        _emit("[WARN] -p 로 준 비밀번호는 ps 로 보입니다. --password-env VAR 또는 --password-file 을 권장합니다.",
              sys.stderr)
    if args.user and source == "none":
        _emit("[WARN] 비밀번호가 없습니다 - 빈 비밀번호로 시도합니다.", sys.stderr)
    args.host = _bracket_ipv6(args.host)
    ctx = _make_ctx(args.verify, args.legacy_tls) if args.scheme == "https" else None
    net = Net(args.scheme, args.host, ctx, args.timeout, use_env_proxy=args.use_env_proxy)
    auth = AuthState(net, args.user, password, None, "default")
    return Crawler(args, net, auth, source).run()


if __name__ == "__main__":
    raise SystemExit(main())
