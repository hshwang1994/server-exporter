#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# precheck_bundle.py — 통합 사전 진단 모듈
# ==============================================================================
# 수집 전 대상 호스트의 연결 상태를 4단계로 진단합니다.
#
# 단계:
#   1. reachable   — TCP 포트 연결로 호스트 도달 가능성 확인
#   2. port_open   — 채널별 서비스 포트 확인 (443/22/5985/5986)
#   3. protocol_supported — 프로토콜 핸드셰이크 (Redfish/SSH banner/vSphere)
#   4. auth_success — 인증 시도 (선택적)
#
# 사용법:
#   - name: Run precheck
#     precheck_bundle:
#       host: "{{ ansible_host }}"
#       channel: redfish
#       ports: [443]
#     delegate_to: localhost
#     register: precheck_result
# ==============================================================================

__metaclass__ = type

DOCUMENTATION = r"""
---
module: precheck_bundle
short_description: 수집 전 대상 호스트 연결 상태 4단계 진단
description:
  - ping(TCP) → port → protocol → auth 순서로 대상 호스트를 진단합니다.
  - 각 단계의 성공/실패 여부와 실패 사유를 반환합니다.
  - controller 노드에서 실행됩니다 (delegate_to: localhost).
options:
  host:
    description: 대상 호스트 IP 또는 hostname
    required: true
    type: str
  channel:
    description: 수집 채널
    required: true
    type: str
    choices: [redfish, os, esxi]
  ports:
    description: 확인할 포트 목록 (순서대로 시도, 첫 번째 성공 포트 사용)
    type: list
    elements: int
    default: []
  timeout_port:
    description: 포트 연결 타임아웃 (초)
    type: float
    default: 3.0
  timeout_protocol:
    description: 프로토콜 핸드셰이크 타임아웃 (초)
    type: float
    default: 15.0
  timeout_auth:
    description: 인증 시도 타임아웃 (초)
    type: float
    default: 8.0
  username:
    description: 인증 사용자명 (선택)
    type: str
  password:
    description: 인증 비밀번호 (선택)
    type: str
  verify_ssl:
    description: SSL 인증서 검증 여부
    type: bool
    default: false
author:
  - server-exporter
"""

from ansible.module_utils.basic import AnsibleModule
import base64
import json
import math
import socket
import ssl
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


# =============================================================================
# 채널별 기본 포트 정의
# =============================================================================
# 2026-08-10 실측 주의 — **"os" 채널은 production playbook 에서 호출되지 않는다.**
#   본 모듈을 include 하는 곳은 common/tasks/precheck/run_precheck.yml 이고, 이를
#   호출하는 곳은 redfish-gather/site.yml:46 과 esxi-gather/site.yml:51 둘뿐이다.
#   os-gather 는 precheck_bundle 대신 site.yml PLAY 1 에서 ansible.builtin.wait_for
#   3연타(5986 → 5985 → 22)로 OS 판별까지 함께 처리한다(os-gather/site.yml:40-81).
#   → 아래 "os" 항목과 probe_os() / ssh_banner_check() 는 **dead code 가 아니라
#     라이브러리 기능**이며 tests/unit/test_precheck_probe_os.py 가 회귀를 지킨다.
#     os-gather 를 precheck 로 통합할 경우의 진입점으로 유지한다(삭제 금지).
CHANNEL_DEFAULT_PORTS = {
    "redfish": [443],
    "os": [5986, 5985, 22],
    "esxi": [443],
}

# 채널별 프로토콜 진단 실패 메시지
#
# 이 값들은 그대로 diagnosis.failure_reason 이 되고, Portal 실패 Grid 의 "실패 사유" 칸에
# **그대로 노출된다** (2026-08-10 사용자 확인 — Portal 은 failure_reason 만 사용).
# 따라서 (a) 짧은 사용자용 요약이어야 하고 (b) 관측하지 못한 원인을 단정하면 안 된다.
#
# 2026-08-10 정정: redfish 값이 "이 장비는 Redfish를 지원하지 않습니다." 였는데 이는
#   **관측 범위를 넘는 단정**이다. 이 분기는 ServiceRoot 응답을 확인하지 못했을 때 잡히며,
#   그 원인은 미지원 외에도 TLS 협상 실패 / 5xx / 타임아웃 / 서비스 비활성일 수 있다
#   (probe_redfish 는 401·403·405·406·503 은 "살아있음"으로 통과시키므로 여기 도달했다는 것은
#    그 외의 실패라는 뜻일 뿐이다). 관측 사실만 남기고 확인 방향을 안내하도록 교체.
#
# 문체 원칙 (2026-08-10 사용자 지시): Portal Grid 를 읽는 사람은 일반 사용자다.
#   긴 대시(—) / 가운데점(·) 같은 특수 구분자를 쓰지 말고 완전한 한국어 문장으로 쓴다.
#   "관측한 사실" 한 문장 + "확인할 것" 한 문장 구성을 기본으로 한다.
#
# 2026-08-10 재정정: "응답을 반환하지 않았습니다" 도 여전히 관측보다 강한 표현이다.
#   이 분기는 HTTP 응답 자체는 받았지만 기대한 프로토콜 응답으로 판정하지 못한 경우에도
#   잡힌다(예: 허용 status 목록 밖의 코드). "응답이 아예 없었다"는 사실과 "기대한 프로토콜
#   응답을 확인하지 못했다"는 사실을 구분해, 후자만 진술하도록 교체.
CHANNEL_PROTOCOL_MESSAGES = {
    "redfish": "예상한 Redfish API 응답을 확인하지 못했습니다. Redfish 서비스 활성화 여부와 펌웨어 호환성을 확인하세요.",
    "os": "예상한 SSH 또는 WinRM 응답을 확인하지 못했습니다. 해당 서비스의 기동 상태를 확인하세요.",
    "esxi": "예상한 vSphere API 응답을 확인하지 못했습니다. ESXi 호스트의 서비스 상태를 확인하세요.",
}


# TCP 연결 실패 종류 (구조화 — 오류 문자열 파싱 대신 이 값으로 분류한다)
#   'dns'      : 주소 해석 실패 → TCP 연결 시도 자체를 못 함
#   'refused'  : RST 관측 → 호스트는 살아 있고 포트만 닫힘
#   'timeout'  : 응답 없음
#   'other'    : 그 외 OSError (no route 등)
TCP_FAIL_DNS = "dns"
TCP_FAIL_REFUSED = "refused"
TCP_FAIL_TIMEOUT = "timeout"
TCP_FAIL_OTHER = "other"


def tcp_check_ex(host, port, timeout):
    """TCP 포트 연결 확인 — (ok, err, kind) 3-튜플.

    production-audit (2026-04-29): IPv4/IPv6 듀얼 스택 — 기존 AF_INET only는
    IPv6-only 관리망 대상에 도달 불가. socket.getaddrinfo로 family를 자동 선택.

    2026-08-10 (Phase 2): 실패 **종류**를 구조화해 함께 반환한다. 종전에는 호출부가
    한국어 오류 문자열에 `"거부" in err` 같은 부분 문자열 검사를 해서 refused 를 판별했는데,
    그런 문자열 파싱으로 failure_code 를 만들면 문구가 바뀔 때마다 분류가 깨진다.
    반환값 kind 는 위 TCP_FAIL_* 상수 중 하나이며 failure_code 매핑의 유일한 근거다.
    """
    last_err = "주소 해석 실패"
    last_kind = TCP_FAIL_OTHER
    try:
        addr_infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        return False, "DNS 해석 실패: {0}".format(e), TCP_FAIL_DNS
    for family, socktype, proto, _canon, sockaddr in addr_infos:
        # Round 16: socket.socket() 를 try 안으로 — IPv6 비활성 host 에서 AF_INET6
        # 주소군에 socket() 이 OSError(EAFNOSUPPORT) 를 던지면(try 밖이면) 모듈 전체가
        # 죽음. try 안에서 잡아 다음 주소군(IPv4)으로 graceful degradation.
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            return True, None, None
        except socket.timeout:
            last_err = "연결 시간 초과 (timeout={0}s)".format(timeout)
            last_kind = TCP_FAIL_TIMEOUT
        except ConnectionRefusedError:
            last_err = "연결 거부됨 (port={0})".format(port)
            last_kind = TCP_FAIL_REFUSED
        except OSError as e:
            last_err = str(e)
            last_kind = TCP_FAIL_OTHER
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
    return False, last_err, last_kind


def tcp_check(host, port, timeout):
    """tcp_check_ex 의 (ok, err) 2-튜플 래퍼 — 기존 호출자/테스트 호환용."""
    ok, err, _kind = tcp_check_ex(host, port, timeout)
    return ok, err


# ansible.builtin.wait_for(state=started, port=...) 의 기본값 (실측 — ansible 2.19.9
# modules/wait_for.py argument_spec: connect_timeout=5, sleep=1).
# os-gather 는 이 모듈로 관리 포트를 확인했고 sleep / connect_timeout 을 지정한 적이 없다.
_WAIT_FOR_CONNECT_TIMEOUT = 5.0
_WAIT_FOR_SLEEP = 1.0


def _dominant_kind(kinds):
    """여러 시도의 실패 종류 → **대표 종류** (관측의 강도 순).

    마지막 오류 문자열 하나로 원인을 정하면 시도 순서에 따라 결과가 흔들린다.
    구조화된 kind 만 보고 결정한다. 우선순위 근거는 _tcp_failure_code 와 동일하다.
    """
    if TCP_FAIL_DNS in kinds:
        return TCP_FAIL_DNS
    if TCP_FAIL_REFUSED in kinds:
        return TCP_FAIL_REFUSED
    if TCP_FAIL_TIMEOUT in kinds:
        return TCP_FAIL_TIMEOUT
    return TCP_FAIL_OTHER


def tcp_check_budget(host, port, budget, poll_interval,
                     connect_timeout=_WAIT_FOR_CONNECT_TIMEOUT):
    """시간 예산 안에서 연결 가능 여부를 **반복 확인** — (ok, err, kind).

    2026-08-10 (Phase 3-A 보정): os-gather 는 종전에 `ansible.builtin.wait_for` 로 포트를
    확인했다. wait_for(state=started) 는 단발 연결이 아니라 **timeout 예산 안에서 폴링**한다
    (실측 — modules/wait_for.py:619-628):

        end = start + timeout
        while now < end:
            create_connection(..., min(connect_timeout, ceil(end - now)))   # 성공 시 종료
            time.sleep(sleep)

    Phase 3-A 최초 전환에서 이를 1회 시도로 바꿔, "probe 시작 시점엔 닫혀 있지만 예산 안에
    기동되는 서비스"가 실패로 바뀌는 회귀가 생겼다. 본 함수가 그 의미를 되돌린다.

    poll_interval 이 0 이하면 **단일 시도**(기존 redfish/esxi 동작)로 되돌아간다 —
    두 채널의 probe 횟수·타임아웃을 바꾸지 않기 위해서다.
    """
    if not poll_interval or poll_interval <= 0:
        return tcp_check_ex(host, port, budget)

    deadline = time.monotonic() + budget
    errs = []
    kinds = []
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        # wait_for 와 동일: 남은 예산을 올림한 값과 connect_timeout 중 작은 쪽
        ok, err, kind = tcp_check_ex(
            host, port, min(connect_timeout, math.ceil(remaining)))
        if ok:
            return True, None, None
        errs.append(err)
        kinds.append(kind)
        if deadline - time.monotonic() <= 0:
            break
        time.sleep(poll_interval)

    if not kinds:
        # 예산이 0 이하라 한 번도 시도하지 못한 경우 — 최소 1회는 시도한다
        return tcp_check_ex(host, port, budget)
    kind = _dominant_kind(kinds)
    # 대표 종류에 해당하는 **마지막** 오류 문자열을 증거로 남긴다
    err = next((e for e, k in zip(reversed(errs), reversed(kinds)) if k == kind), errs[-1])
    return False, err, kind


def _build_ssl_context(verify):
    """HTTPS context — verify=False 시 self-signed BMC 인증서 허용.

    cycle 2026-04-30: 구 BMC (HPE iLO4, Lenovo IMM2, 일부 iDRAC7/8 펌웨어)
    호환을 위해 verify=False 환경 한정으로 OpenSSL 3.x legacy renegotiation +
    weak cipher 허용. curl -k 와 동등한 관용성. 사내 BMC self-signed 망 한정.
    """
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        # OpenSSL 3.x: 구 BMC TLS legacy renegotiation 차단 해제
        if hasattr(ssl, 'OP_LEGACY_SERVER_CONNECT'):
            ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
        # 약한 cipher 허용 (TLS 1.0/1.1, RC4 등 — verify=False BMC 망 한정)
        try:
            ctx.set_ciphers('DEFAULT@SECLEVEL=0')
        except ssl.SSLError:
            pass
    return ctx


def _basic_auth_header(auth):
    """auth=(user, pass) → 'Basic ...' 헤더 값."""
    if not auth:
        return None
    credentials = base64.b64encode(
        "{0}:{1}".format(auth[0], auth[1]).encode()
    ).decode()
    return "Basic " + credentials


def _collect_headers(msg):
    """urllib 응답 헤더 → {소문자 이름: 값}. 중복 헤더는 ', ' 로 합친다.

    2026-08-10 (Phase 3-B): WinRM 판정 근거로 헤더가 필요하다. Windows 는
    `WWW-Authenticate` 를 여러 줄로 보내므로 get_all 로 모아 합친다.
    """
    out = {}
    if msg is None:
        return out
    try:
        names = {k.lower() for k in msg.keys()}
    except Exception:
        return out
    for name in names:
        try:
            values = msg.get_all(name) or []
        except Exception:
            values = []
        out[name] = ", ".join(str(v) for v in values)
    return out


def http_get(url, timeout, verify=False, auth=None):
    """HTTP GET — urllib stdlib 단일 경로 (외부 의존 없음).

    반환: (ok, err, payload)
      payload = {'status_code': int, 'json': dict|None, 'headers': {소문자: 값}}

    2026-08-10 (Phase 3-B): payload 에 'headers' 를 **추가**했다. 기존 호출자는
    'status_code' / 'json' 만 읽으므로 동작 변화 없다 (redfish / esxi 회귀 없음).

    cycle 2026-04-30: HTTP 406 Not Acceptable 호환 — 일부 BMC 펌웨어
    (HPE iLO 펌웨어 ServiceRoot RedfishVersion 1.17.0 등)이 Accept 헤더
    명시 안 된 요청을 거부.
    cycle 2026-04-30 hotfix: OData-Version + User-Agent 추가 시 Lenovo XCC
    일부 펌웨어가 reject (사이트 검증). Accept 헤더만 명시 — 사용자 실측 OK 패턴.
    """
    ctx = _build_ssl_context(verify)
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    auth_header = _basic_auth_header(auth)
    if auth_header:
        req.add_header("Authorization", auth_header)
    try:
        # Round 16: with 컨텍스트 매니저로 응답(소켓) 결정적 close (GC 의존 제거).
        # probe + auth 단계가 http_get 를 수회 호출 — 응답 미close 시 소켓 누적.
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.getcode()
            headers = _collect_headers(getattr(resp, "headers", None))
        try:
            json_body = json.loads(body)
        except (ValueError, json.JSONDecodeError):
            json_body = None
        return True, None, {
            "status_code": status, "json": json_body, "headers": headers,
        }
    except urllib.error.HTTPError as e:
        return False, "HTTP {0}".format(e.code), {
            "status_code": e.code,
            "json": None,
            "headers": _collect_headers(getattr(e, "headers", None)),
        }
    except socket.timeout:
        return False, "요청 시간 초과 (timeout={0}s)".format(timeout), None
    except urllib.error.URLError as e:
        # ConnectionRefusedError / SSL handshake / DNS 등 묶음
        return False, "연결 실패: {0}".format(str(e.reason)[:200]), None
    except (ssl.SSLError, OSError) as e:
        return False, str(e)[:200], None


# SSH Protocol Version Exchange (RFC 4253 §4.2)
#   - 서버는 "SSH-protoversion-softwareversion" 한 줄을 CR LF 로 끝낸다.
#   - 그 **앞에** 다른 줄(법적 고지 등)을 보낼 수 있고, 클라이언트는 그것을 건너뛰어야 한다.
#   - protoversion 은 2.0 (또는 하위 호환 표기 1.99) 만 유효로 본다.
# 무제한으로 읽지 않도록 줄 수와 바이트 수를 모두 제한한다.
_SSH_ID_MAX_LINES = 8
_SSH_ID_MAX_BYTES = 2048
_SSH_ID_PREFIXES = ("SSH-2.0-", "SSH-1.99-")


def _read_ssh_identification(sock, deadline):
    """SSH identification 줄을 찾아 반환 — 못 찾으면 None.

    RFC 4253 §4.2 가 허용하는 **선행 추가 줄**을 건너뛴다. 읽는 양은
    _SSH_ID_MAX_LINES / _SSH_ID_MAX_BYTES 로 제한한다 (무제한 수신 금지).
    """
    buf = b""
    lines = 0
    while len(buf) < _SSH_ID_MAX_BYTES and lines < _SSH_ID_MAX_LINES:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        sock.settimeout(remaining)
        chunk = sock.recv(256)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            lines += 1
            line = raw.decode("utf-8", errors="replace").strip()
            if line.startswith(_SSH_ID_PREFIXES):
                return line
            if line.startswith("SSH-"):
                # SSH 는 맞으나 우리가 아는 protoversion 이 아니다 — 그대로 알린다
                return line
            if lines >= _SSH_ID_MAX_LINES:
                return None
    return None


def ssh_banner_check(host, port, timeout):
    """SSH Protocol Identification 확인 (IPv4/IPv6 듀얼 스택).

    2026-08-10 (Phase 3-B): 종전에는 첫 recv(256) 이 "SSH-" 로 시작하는지만 봤다.
    RFC 4253 §4.2 는 identification 앞에 다른 줄을 보내는 것을 허용하므로 그런 서버를
    놓쳤고, "SSH-" 접두사만 맞으면 통과시켜 protoversion 을 검증하지 않았다.
    이제 선행 줄을 건너뛰고 SSH-2.0 / SSH-1.99 만 성공으로 인정한다.

    자격증명을 보내지 않고 Key Exchange 도 수행하지 않는다 (Protocol 확인까지만).
    """
    last_err = "주소 해석 실패"
    try:
        addr_infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        return False, "DNS 해석 실패: {0}".format(e), None
    for family, socktype, proto, _canon, sockaddr in addr_infos:
        # Round 16: socket.socket()/settimeout() 를 try 안으로 — IPv6 비활성 host 의
        # AF_INET6 주소군에서 socket() OSError(EAFNOSUPPORT) 가 모듈을 죽이지 않게
        # (tcp_check 와 동일). 잡아서 다음 주소군(IPv4)으로 진행.
        sock = None
        try:
            deadline = time.monotonic() + timeout
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            ident = _read_ssh_identification(sock, deadline)
            if ident is None:
                last_err = "SSH identification 미수신"
            elif ident.startswith(_SSH_ID_PREFIXES):
                # facts 에 raw identification 을 싣지 않는다 — 소프트웨어 버전 문자열을
                # 외부 JSON 에 새 필드로 노출하지 않기 위함. 실패 시 근거는 err 로만 전달.
                return True, None, {}
            else:
                last_err = "지원하지 않는 SSH protoversion: {0}".format(ident[:40])
            # Round 15: 비-SSH 응답 → 즉시 return 대신 다음 주소군(dual-stack) 시도.
        except Exception as e:
            last_err = str(e)[:120]
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
    return False, last_err, None


def probe_redfish(host, port, timeout, verify=False):
    """Redfish ServiceRoot 프로브.

    ServiceRoot가 200이 아닌 HTTP 응답 (401/403/503)을 던지더라도, BMC가
    Redfish 서비스를 응답한다는 증거 → protocol_supported=True. 인증 검증은
    Stage 4 (auth) 또는 본 수집 (redfish_gather library의 무인증→인증
    fallback) 에서 처리.

    배경: 일부 BMC (HPE iLO5/6 보안 강화 펌웨어, Lenovo XCC 일부) 는
    무인증 ServiceRoot에 401을 던진다. 이전 구현은 401/403/503을 모두
    HTTP 실패로 분류해 "Redfish 미지원"으로 오판정 → 통신 정상인 장비를
    차단. probe_esxi 의 status_code 허용 패턴을 따라 정정.

    G5 (cycle 2026-04-30): payload=None 케이스 (URLError/timeout/SSLError)
    에 1회 retry. BMC 부팅 직후 / 일시 부하 transient 차단.
    """
    import time as _time
    url = "https://{0}:{1}/redfish/v1/".format(host, port)

    last_err = None
    last_payload = None
    for attempt in (1, 2):  # 최대 2회 시도 (1 retry)
        ok, err, payload = http_get(url, timeout, verify=verify)

        if ok:
            json_data = payload.get("json") if payload else None
            probe_facts = {}
            if isinstance(json_data, dict):
                probe_facts["redfish_version"] = json_data.get("RedfishVersion")
                probe_facts["product"] = json_data.get("Product")
                systems_uri = None
                systems = json_data.get("Systems")
                if isinstance(systems, dict):
                    systems_uri = systems.get("@odata.id")
                probe_facts["systems_uri"] = systems_uri
            if attempt > 1:
                probe_facts["retry_count"] = attempt - 1
            return True, None, probe_facts

        # HTTP 응답은 왔지만 status != 200 — 서비스 살아있고 인증/일시상태 이슈
        # 401: 무인증 ServiceRoot 차단 (인증 강화 펌웨어)
        # 403: IP 화이트리스트 / 권한 부족 (BMC는 응답 중)
        # 405: Method Not Allowed — Redfish 응답하나 GET/HEAD 제한 (드물지만 일부 펌웨어)
        # 406: Not Acceptable — Accept 헤더 협상 불일치 (cycle 2026-04-30: http_get은
        #      Accept 헤더만 명시 — OData-Version/User-Agent는 Lenovo XCC reject로 제거됨.
        #      그럼에도 BMC 펌웨어가 추가 헤더 요구하는 케이스)
        # 503: BMC 일시 과부하 / 부팅 직후 — 본 수집에서 재시도 가능
        if payload and payload.get("status_code") in (401, 403, 405, 406, 503):
            facts = {
                "root_status_code": payload.get("status_code"),
                "requires_auth_at_root": payload.get("status_code") in (401, 403),
                "header_negotiation_issue": payload.get("status_code") in (405, 406),
            }
            if attempt > 1:
                facts["retry_count"] = attempt - 1
            return True, None, facts

        last_err, last_payload = err, payload
        # payload=None (URLError/timeout/SSLError) 일 때만 retry. HTTP 응답이 온 status는 retry 불필요.
        if payload is not None:
            break
        if attempt == 1:
            _time.sleep(1)  # 1초 backoff

    return False, last_err, None


# ── WS-Management Identify (WinRM Protocol 판정 정본) ──────────────────────
#
# 2026-08-10 (Phase 3-B 보정). 종전 판정은 응답 **헤더** 근거였다:
#   (1) WWW-Authenticate 의 WSMAN realm, (2) Server=Microsoft-HTTPAPI + 인증 요구.
# 둘 다 WinRM 의 Protocol Identity 를 직접 증명하지 않는다. 특히 (2) 는 http.sys 위에
# 올라간 아무 서비스나 통과시킬 수 있어 일반 HTTP 서비스를 Windows 로 오판할 위험이 있다.
# → **제거**하고, 실제 WS-Management Identify 요청/응답으로만 판정한다.
#
# 근거 (lab 부재 — rule 96 R1-A web sources):
#   - Microsoft Learn "Detecting Whether a Remote Computer Supports WS-Management Protocol"
#     https://learn.microsoft.com/en-us/windows/win32/winrm/
#             detecting-whether-a-remote-computer-supports-ws-management-protocol
#     (확인 2026-08-10) — IdentifyResponse 는 ProtocolVersion / ProductVendor /
#     ProductVersion 을 반환하며 ProductVendor 예시는 "Microsoft Corporation".
#   - 비인증 Identify 는 `WSMANIDENTIFY: unauthenticated` 헤더로 보낸다. 이 경우에도
#     ProtocolVersion 과 ProductVendor 는 반환되고 ProductVersion 만 placeholder 가 된다.
#   - SOAP envelope / DMTF wsman 네임스페이스는 설치본 pywinrm(winrm/protocol.py) 의
#     xmlns 맵으로 교차 확인했다.
# ※ lab 에 Windows WinRM 실장비가 없어 **실측 캡처가 아니라 규격 기반**이다.
WINRM_ENDPOINT_PATH = "/wsman"

_SOAP_ENVELOPE_NS = "http://www.w3.org/2003/05/soap-envelope"

# 네임스페이스 URI 는 문자열 비교라 표기가 정확히 맞아야 한다. 문서/구현마다 http/https 와
# `.xsd` 접미사 유무가 갈려 관측된 표기를 모두 허용한다 (문자열 포함 검색이 아니라
# XML 파서가 분리한 네임스페이스와의 **완전 일치** 비교다).
_WSMID_NAMESPACES = frozenset({
    "http://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity.xsd",
    "https://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity.xsd",
    "http://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity",
    "https://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity",
})

# ProtocolVersion 값은 DMTF WS-Management 프로토콜 URI 여야 한다.
_WSMAN_PROTOCOL_PREFIXES = (
    "http://schemas.dmtf.org/wbem/wsman/1/wsman",
    "https://schemas.dmtf.org/wbem/wsman/1/wsman",
)

# Windows 판정용 vendor 표기. WS-Management 는 표준이라 비-Windows 장비(BMC 등)도 구현한다.
# "WS-Man 이 있다" 와 "Windows WinRM 이다" 는 다른 명제이므로 vendor 까지 확인한다.
_WINRM_VENDOR_MARKER = "microsoft"

_IDENTIFY_REQUEST = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"'
    ' xmlns:wsmid="http://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity.xsd">'
    "<s:Header/><s:Body><wsmid:Identify/></s:Body></s:Envelope>"
).encode("utf-8")

# XML 폭탄 방어 — 파싱 전에 본문 크기를 제한한다 (ElementTree 는 엔티티 확장 공격에 취약).
_IDENTIFY_MAX_BYTES = 65536


def http_post_soap(url, body, timeout, verify=False, extra_headers=None):
    """SOAP POST — Protocol Probe 전용 최소 helper (stdlib urllib).

    기존 `http_get` 은 Redfish / ESXi / OS 가 함께 쓰는 GET 전용 helper 다. Identify 를
    위해 그것을 POST 겸용으로 변형하면 두 채널 동작에 영향이 갈 수 있어 별도로 둔다.
    반환: (ok, err, payload) — payload={'status_code', 'body'}. 자격증명은 보내지 않는다.
    """
    ctx = _build_ssl_context(verify)
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/soap+xml;charset=UTF-8")
    for name, value in (extra_headers or {}).items():
        req.add_header(name, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read(_IDENTIFY_MAX_BYTES)
            return True, None, {"status_code": resp.getcode(), "body": raw}
    except urllib.error.HTTPError as e:
        try:
            raw = e.read(_IDENTIFY_MAX_BYTES)
        except Exception:
            raw = b""
        return False, "HTTP {0}".format(e.code), {"status_code": e.code, "body": raw}
    except socket.timeout:
        return False, "요청 시간 초과 (timeout={0}s)".format(timeout), None
    except urllib.error.URLError as e:
        return False, "연결 실패: {0}".format(str(e.reason)[:200]), None
    except (ssl.SSLError, OSError) as e:
        return False, str(e)[:200], None


def parse_identify_response(raw):
    """WS-Management IdentifyResponse 검증 → (is_wsman, vendor, 사유).

    문자열 포함 검색이 아니라 **XML 파서가 분리한 네임스페이스**로 판정한다.
      1) 본문이 정상 XML 인가
      2) wsmanidentity 네임스페이스의 IdentifyResponse 인가
      3) ProtocolVersion 이 DMTF WS-Management 프로토콜 URI 인가
      4) ProductVendor 가 구조적으로 존재하는가 (Windows 판정은 호출부에서)
    """
    if not raw:
        return False, None, "응답 본문 없음"
    if len(raw) > _IDENTIFY_MAX_BYTES:
        return False, None, "응답 본문이 상한을 초과"
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        return False, None, "XML 파싱 실패: {0}".format(str(e)[:80])

    identify = None
    for elem in root.iter():
        if not isinstance(elem.tag, str) or not elem.tag.startswith("{"):
            continue
        ns, _sep, local = elem.tag[1:].partition("}")
        if local == "IdentifyResponse" and ns in _WSMID_NAMESPACES:
            identify = elem
            break
    if identify is None:
        return False, None, "IdentifyResponse 없음 (WS-Management 네임스페이스 불일치)"

    fields = {}
    for child in identify:
        if not isinstance(child.tag, str) or not child.tag.startswith("{"):
            continue
        ns, _sep, local = child.tag[1:].partition("}")
        if ns in _WSMID_NAMESPACES:
            fields[local] = (child.text or "").strip()

    protocol = fields.get("ProtocolVersion", "")
    if not protocol.startswith(_WSMAN_PROTOCOL_PREFIXES):
        return False, None, "ProtocolVersion 이 WS-Management 가 아님: {0}".format(
            protocol[:60] or "없음")

    vendor = fields.get("ProductVendor")
    if vendor is None:
        return False, None, "ProductVendor 없음"
    return True, vendor, "IdentifyResponse 확인"


def probe_os(host, port, timeout):
    """OS 채널 프로토콜 프로브 (SSH identification 또는 WinRM endpoint).

    2026-08-10 (Phase 3-B + 보정): WinRM 판정 근거가 두 번 바뀌었다.
      (a) 종전: `status in (200, 401, 403, 405, 503)` — "/wsman 에서 아무 HTTP 응답이나 오면
          WinRM" 과 사실상 같아 일반 웹서버를 Windows 로 오판할 수 있었다.
      (b) 1차 보정: 응답 헤더 근거(WSMAN realm / Microsoft-HTTPAPI + 인증요구).
          여전히 WinRM 의 Protocol Identity 를 직접 증명하지 못한다.
      (c) **현재**: 비인증 WS-Management Identify 를 보내고 IdentifyResponse 를 XML
          네임스페이스 기준으로 검증한다. HTTP status / Server / WWW-Authenticate 는
          **판정에 쓰지 않는다.**
    (이 함수는 Phase 3-B 이전까지 운영 경로에 배선돼 있지 않아 실제 오판 사고는 없었다.)

    TLS 정책은 바꾸지 않는다 — Windows 수집이 `ansible_winrm_server_cert_validation: ignore`
    를 쓰므로 probe 도 verify=False 로 맞춘다. 인증서 유효성 검사와 WinRM 존재 확인은
    별개 문제이며, probe 가 더 엄격해서 정상 서버가 탈락하는 일이 없어야 한다.
    """
    if port == 22:
        return ssh_banner_check(host, port, timeout)
    if port in (5985, 5986):
        scheme = "https" if port == 5986 else "http"
        url = "{0}://{1}:{2}{3}".format(scheme, host, port, WINRM_ENDPOINT_PATH)
        # 비인증 Identify — 자격증명을 보내지 않는다 (Credential Probe 와 분리).
        ok, err, payload = http_post_soap(
            url, _IDENTIFY_REQUEST, timeout, verify=False,
            extra_headers={"WSMANIDENTIFY": "unauthenticated"},
        )
        if payload is None:
            # 응답 자체가 없음 (TLS handshake 실패 / timeout / 연결 오류)
            return False, err or "WinRM endpoint 응답 없음", None

        is_wsman, vendor, why = parse_identify_response(payload.get("body"))
        if not is_wsman:
            return False, "WS-Management IdentifyResponse 아님 (HTTP {0}, {1})".format(
                payload.get("status_code"), why), None
        if _WINRM_VENDOR_MARKER not in (vendor or "").lower():
            # WS-Management 는 표준이라 비-Windows 장비도 구현한다. Windows 로 확정하지 않는다.
            return False, "WS-Management 는 응답하나 Windows WinRM 이 아님 (vendor={0})".format(
                (vendor or "미제공")[:40]), None
        return True, None, {}
    return False, "지원하지 않는 OS 포트: {0}".format(port), None


def probe_esxi(host, port, timeout, verify=False):
    """vSphere API endpoint 프로브.

    /sdk는 GET 메서드에 대해 다양한 응답을 던진다 (200/301/302/404/405/500/SOAP fault).
    응답이 오기만 하면 vSphere 서비스 살아있음으로 판단.

    401/403 추가 (probe_redfish 와 동일 정합): vCenter SSO / 인증 요구
    환경에서 /sdk 가 401/403을 던지더라도 endpoint 자체는 살아있음 →
    Stage 4 (auth) 또는 본 수집 (community.vmware) 에서 처리. 이전 구현은
    이를 "vSphere endpoint 미응답" 으로 오판정했음.
    """
    url = "https://{0}:{1}/sdk".format(host, port)
    ok, err, payload = http_get(url, timeout, verify=verify)
    if ok:
        return True, None, {"vsphere_endpoint": url}
    # 응답 오면 서비스 살아있음 — auth/일시상태 이슈는 후속 단계 책임
    if payload and payload.get("status_code") in (200, 301, 302, 401, 403, 404, 405, 500, 503):
        return True, None, {
            "vsphere_endpoint": url,
            "root_status_code": payload.get("status_code"),
            "requires_auth_at_root": payload.get("status_code") in (401, 403),
        }
    return False, err, None


def _init_result(channel, ports):
    """precheck result dict 초기화 (OS 채널 추가 필드 포함)."""
    result = {
        "changed": False,
        "reachable": False,
        "port_open": False,
        "protocol_supported": False,
        "auth_success": None,
        "failure_stage": None,
        # 2026-08-10 (Phase 2): 시스템이 분기에 쓰는 안정 식별자.
        # 사람이 읽는 failure_reason 과 역할을 분리한다. 실패가 없으면 None.
        "failure_code": None,
        "failure_reason": None,
        "detail": None,
        "checked_ports": ports,
        "selected_port": None,
        "probe_facts": {},
    }
    if channel == "os":
        result["detected_os"] = None
        result["detected_port"] = None
        result["winrm_scheme"] = None
    return result


def _check_ports(host, ports, timeout_port, poll_interval=0.0):
    """Stage 1+2: 포트 순회 → (any_response, target_port_open, open_port, port_errors, kinds, probed).

    probed 는 **실제로 순차 probe 를 수행한 포트 목록**이다 (성공 시 거기서 멈추므로
    구성된 전체 목록과 다를 수 있다). checked_ports 의 정본 (2026-08-10 Phase 3-A).

    kinds 는 실패한 포트별 TCP_FAIL_* 종류 목록이다 (성공 시 빈 목록).
    2026-08-10 (Phase 2): 종전에는 refused 판별을 `"거부" in err` 부분 문자열 검사로 했다.
    오류 문구를 한 글자만 바꿔도 판별이 조용히 깨지는 구조라 tcp_check_ex 의 구조화된
    kind 로 교체했다. failure_code 분류도 이 kind 만 근거로 삼는다.
    """
    any_response = False
    target_port_open = False
    open_port = None
    port_errors = []
    kinds = []
    probed = []
    for port in ports:
        # 한 포트를 예산 안에서 여러 번 시도해도 probed 에는 **한 번만** 넣는다
        # (checked_ports 는 "어떤 포트를 확인했나" 이지 "몇 번 시도했나"가 아니다).
        probed.append(port)
        ok, err, kind = tcp_check_budget(host, port, timeout_port, poll_interval)
        if ok:
            any_response = True
            target_port_open = True
            open_port = port
            break
        # ConnectionRefusedError → host alive 이지만 port 닫힘
        if kind == TCP_FAIL_REFUSED:
            any_response = True
        kinds.append(kind)
        port_errors.append("port={0}: {1}".format(port, err))
    return any_response, target_port_open, open_port, port_errors, kinds, probed


def _tcp_failure_code(kinds):
    """포트별 TCP 실패 종류 목록 → **대표** failure_code.

    포트를 여러 개 순차 probe 하면 포트마다 결과가 다를 수 있다
    (예: 5986 timeout / 5985 refused / 22 timeout). 마지막 결과만 보고 대표를 정하면
    probe 순서에 따라 결과가 흔들리므로, **관측의 강도** 순으로 결정한다 (2026-08-10 Phase 3-A).

    선정 규칙 (결정적, 순서 무관):
      1) 주소 해석 실패가 하나라도 있으면 DNS_RESOLUTION_FAILED
         — DNS 는 호스트 단위라 한 포트에서 실패하면 전 포트가 같다. TCP 연결 시도 자체를
           못 한 것이므로 가장 앞선 단계의 관측이다.
      2) RST(거부)를 하나라도 관측했으면 TCP_CONNECTION_REFUSED
         — "호스트가 살아 있다"는 **능동적 응답**을 실제로 본 것이라 가장 강한 관측이다.
      3) 그 외에는 TCP_CONNECT_FAILED
         — timeout / no route 등. "연결하지 못했다"는 사실만 확정할 수 있고 장비가
           꺼졌는지 경로가 막혔는지는 알 수 없다 (UNREACHABLE 로 단정 금지).

    포트별 원본 사유는 result['detail'] 에 "port=<n>: <사유>" 형태로 전부 보존된다.
    """
    if TCP_FAIL_DNS in kinds:
        return "DNS_RESOLUTION_FAILED"
    if TCP_FAIL_REFUSED in kinds:
        return "TCP_CONNECTION_REFUSED"
    return "TCP_CONNECT_FAILED"


def _search_os_candidates(host, ports, timeout_port, poll_interval, timeout_proto):
    """OS 후보 탐색 (Phase 3-B) — TCP 성공 **+ 기대 프로토콜 확인**까지 되어야 선택.

    종전에는 포트가 열리기만 하면 그 포트로 OS 를 확정했다. 그러면 5986/5985/22 에 다른
    서비스가 떠 있을 때 Windows / Linux 를 오판한다. 이제 포트가 열려도 기대 프로토콜이
    아니면 **다음 후보로 계속 진행**한다.

    반환: (selected_port, probed, tcp_open_ports, tcp_errors, tcp_kinds, proto_errors)
      selected_port : 프로토콜까지 확인된 포트 (없으면 None)
      probed        : 실제로 시도한 포트 (중복 없음, 순서 보존)
      tcp_open_ports: TCP 는 열렸던 포트 (프로토콜 실패 포함)
    """
    selected = None
    probed = []
    tcp_open_ports = []
    tcp_errors = []
    tcp_kinds = []
    proto_errors = []

    for port in ports:
        probed.append(port)
        ok, err, kind = tcp_check_budget(host, port, timeout_port, poll_interval)
        if not ok:
            tcp_kinds.append(kind)
            tcp_errors.append("port={0}: {1}".format(port, err))
            continue

        tcp_open_ports.append(port)
        p_ok, p_err, _facts = probe_os(host, port, timeout_proto)
        if p_ok:
            selected = port
            break
        # 프로토콜 불일치 — 근거를 남기고 **다음 후보로 계속**
        proto_errors.append("port={0}: {1}".format(port, p_err))

    return selected, probed, tcp_open_ports, tcp_errors, tcp_kinds, proto_errors


def _detect_os_from_port(open_port):
    """OS 채널: 포트 기반 OS 유형 + WinRM scheme 판별."""
    if open_port == 22:
        return "linux", None
    if open_port in (5985, 5986):
        return "windows", "https" if open_port == 5986 else "http"
    return None, None


def _probe_protocol(channel, host, open_port, timeout_proto, verify_ssl):
    """Stage 3 dispatcher — channel별 probe_* 호출."""
    if channel == "redfish":
        return probe_redfish(host, open_port, timeout_proto, verify=verify_ssl)
    if channel == "os":
        return probe_os(host, open_port, timeout_proto)
    if channel == "esxi":
        return probe_esxi(host, open_port, timeout_proto, verify=verify_ssl)
    return False, "알 수 없는 채널: {0}".format(channel), None


def _try_redfish_auth(host, open_port, username, password, timeout_auth, verify_ssl, result):
    """Stage 4 — Redfish Systems 호출로 인증 확인 + vendor hint 추출. 실패 시 result 업데이트만."""
    url = "https://{0}:{1}/redfish/v1/Systems".format(host, open_port)
    ok, err, payload = http_get(
        url, timeout_auth, verify=verify_ssl, auth=(username, password)
    )
    if not ok:
        # 2026-08-10: 종전엔 실패 원인과 무관하게 auth_success=False 를 넣었다. 그러나 여기서
        # ok=False 가 되는 원인에는 timeout / 5xx / TLS 오류도 포함된다 — 인증이 거부됐다는
        # 관측 근거가 없는 상황까지 "인증 실패"로 확정하던 셈이다.
        #   → BMC 가 **명시적으로 거부한 401** 을 관측했을 때만 False.
        #   → 403 은 인증 후 권한/IP 화이트리스트 문제일 수 있어 인증 거부로 단정하지 않는다.
        #   → 그 외에는 "확인하지 못함"인 None 유지.
        # failure_stage 는 원인이 아니라 **실행이 멈춘 단계**이므로 어느 쪽이든 'auth'.
        # 구조화된 HTTP status 를 그대로 본다 (문자열 파싱 아님 — http_get 이 payload 로 전달).
        status = (payload or {}).get("status_code")
        rejected = status == 401
        result["auth_success"] = False if rejected else None
        result["failure_stage"] = "auth"
        # 401 이든 timeout 이든 **멈춘 단계**는 같다. 원인 확정 여부는 auth_success 가 표현한다.
        # 403 은 인증 후 권한 부족일 수 있어 거부로 확정하지 않는다 (auth_success 는 None 유지).
        result["failure_code"] = "AUTH_PROBE_FAILED"
        result["failure_reason"] = (
            "BMC가 자격증명을 거부했습니다(HTTP 401). 계정과 비밀번호를 확인하세요."
            if rejected else
            "BMC 인증 단계에서 응답을 확인하지 못했습니다. 자격증명과 BMC 상태를 확인하세요."
        )
        result["detail"] = err
        return False
    result["auth_success"] = True
    json_data = payload.get("json") if payload else None
    if isinstance(json_data, dict):  # Round 5 #2: 비-dict JSON .get AttributeError 방어
        members = json_data.get("Members", [])
        # rule 95 R1 #2: 비-dict 멤버([null]/[str]) 방어 — members[0].get AttributeError 회피
        if members and isinstance(members[0], dict):
            result["probe_facts"]["first_system_uri"] = members[0].get("@odata.id", "")
    return True


def _run_os_candidate_flow(module, result, host, ports, verify_ssl):
    """OS 전용 진단 흐름 (Phase 3-B) — 후보 탐색 결과를 result 로 옮기고 exit_json.

    성공 우선 원칙: 앞 후보가 프로토콜 불일치여도 뒤 후보에서 확인되면 **전체 성공**이다.

    모든 후보 실패 시 대표 진단:
      - TCP 로 하나도 못 붙음 → Phase 3-A 매핑 유지 (DNS / REFUSED / CONNECT_FAILED)
      - TCP 는 붙었는데 프로토콜을 하나도 확인 못 함 → protocol / PROTOCOL_CHECK_FAILED
    """
    (selected, probed, tcp_open_ports, tcp_errors, tcp_kinds,
     proto_errors) = _search_os_candidates(
        host, ports,
        module.params["timeout_port"],
        module.params["port_poll_interval"],
        module.params["timeout_protocol"],
    )
    # 프로토콜 불일치로 다음 후보로 넘어간 포트도 "확인한 포트" 다
    result["checked_ports"] = probed or ports
    result["protocol_checked"] = True

    if selected is not None:
        os_type, scheme = _detect_os_from_port(selected)
        result["reachable"] = True
        result["port_open"] = True
        result["protocol_supported"] = True   # 실제 SSH / WinRM 응답을 확인했다
        result["selected_port"] = selected
        result["detected_os"] = os_type
        result["winrm_scheme"] = scheme
        result["detected_port"] = selected
        module.exit_json(**result)

    if tcp_open_ports:
        # 포트는 열렸으나 기대 프로토콜을 하나도 확인하지 못함
        result["reachable"] = True
        result["port_open"] = True
        result["protocol_supported"] = False   # 검사했고, 확인하지 못했다
        result["failure_stage"] = "protocol"
        result["failure_code"] = "PROTOCOL_CHECK_FAILED"
        result["failure_reason"] = (
            "관리 포트에는 연결되었지만 예상한 SSH 또는 WinRM 응답을 확인하지 못했습니다. "
            "SSH와 WinRM 서비스 설정을 확인하세요."
        )
        result["detail"] = "; ".join(proto_errors + tcp_errors)
        module.exit_json(**result)

    # TCP 단계에서 전부 실패 — Phase 3-A 매핑 그대로
    if TCP_FAIL_REFUSED in tcp_kinds:
        result["reachable"] = True
        result["failure_stage"] = "port"
        result["failure_code"] = "TCP_CONNECTION_REFUSED"
        result["failure_reason"] = (
            "호스트는 응답하지만 서비스 포트가 열려 있지 않습니다. "
            "방화벽 설정과 서비스 기동 상태를 확인하세요."
        )
    else:
        result["failure_stage"] = "reachable"
        result["failure_code"] = _tcp_failure_code(tcp_kinds)
        result["failure_reason"] = (
            "대상 호스트에 연결할 수 없습니다. "
            "서버 전원 상태와 네트워크 경로를 확인하세요."
        )
    result["detail"] = "; ".join(tcp_errors)
    module.exit_json(**result)


def run_module():
    module = AnsibleModule(
        argument_spec=dict(
            host=dict(type="str", required=True),
            channel=dict(
                type="str", required=True, choices=["redfish", "os", "esxi"]
            ),
            ports=dict(type="list", elements="int", default=[]),
            timeout_port=dict(type="float", default=3.0),
            timeout_protocol=dict(type="float", default=15.0),
            timeout_auth=dict(type="float", default=8.0),
            username=dict(type="str", required=False, no_log=True),
            password=dict(type="str", required=False, no_log=True),
            verify_ssl=dict(type="bool", default=False),
            # 2026-08-10 (Phase 3-A): Stage 3(프로토콜 확인) 수행 여부.
            #   OS 채널을 공통 precheck 로 통합하면서 필요해진 최소 확장이다. OS 는 종전에
            #   wait_for 로 TCP 개방만 확인했고, 이번 Phase 범위는 구조 정렬이지
            #   SSH/WinRM 실제 프로토콜 검증 도입이 아니다. probe_protocol=false 로 부르면
            #   Stage 1+2 까지만 수행하고 protocol_supported 는 초기값(False)을 유지한다
            #   — 즉 "포트가 열렸으니 프로토콜도 된다"고 **거짓으로 표시하지 않는다.**
            #   redfish / esxi 는 기본값 true 라 동작 불변.
            probe_protocol=dict(type="bool", default=True),
            # 2026-08-10 (Phase 3-A 보정): 포트당 재시도 간격(초).
            #   0 이면 단일 시도 — redfish / esxi 의 기존 동작이며 기본값이다.
            #   OS 는 종전 wait_for 의 폴링 의미를 보존하려고 1.0(wait_for sleep 기본값)을
            #   명시 전달한다. 예산(timeout_port)은 그대로라 총 대기 시간은 늘지 않는다.
            port_poll_interval=dict(type="float", default=0.0),
        ),
        supports_check_mode=True,
    )

    host = module.params["host"]
    channel = module.params["channel"]
    ports = module.params["ports"] or CHANNEL_DEFAULT_PORTS.get(channel, [])
    verify_ssl = module.params["verify_ssl"]
    result = _init_result(channel, ports)

    # ── OS 후보 탐색 (Phase 3-B) ─────────────────────────────────────────
    # OS 는 "포트가 열렸는가" 가 아니라 "기대한 관리 프로토콜이 응답하는가" 로 후보를 고른다.
    # 아래 분기는 OS + probe_protocol=true 일 때만 타고, redfish / esxi 는 기존 흐름 그대로다.
    if channel == "os" and module.params["probe_protocol"]:
        _run_os_candidate_flow(module, result, host, ports, verify_ssl)
        return   # _run_os_candidate_flow 안에서 exit_json 한다 (도달하지 않음)

    # Stage 1+2: reachable + port_open (rule 27 R2 — host alive 분리)
    any_response, target_port_open, open_port, port_errors, port_kinds, probed = _check_ports(
        host, ports, module.params["timeout_port"],
        poll_interval=module.params["port_poll_interval"],
    )
    # checked_ports 는 **실제로 순차 probe 를 수행한 포트**다 (구성된 전체 목록이 아니다).
    # 성공 시 거기서 멈추므로 OS 채널은 [5986] / [5986,5985] / [5986,5985,22] 로 달라진다.
    # redfish / esxi 는 포트가 [443] 하나뿐이라 값이 종전과 동일하다.
    result["checked_ports"] = probed or ports
    if not any_response:
        result["failure_stage"] = "reachable"
        # DNS_RESOLUTION_FAILED 또는 TCP_CONNECT_FAILED — RST 를 못 봤으므로 REFUSED 는 나올 수 없다
        result["failure_code"] = _tcp_failure_code(port_kinds)
        result["failure_reason"] = (
            "대상 호스트에 연결할 수 없습니다. "
            "서버 전원 상태와 네트워크 경로를 확인하세요."
        )
        result["detail"] = "; ".join(port_errors)
        module.exit_json(**result)
    if not target_port_open:
        result["reachable"] = True
        result["failure_stage"] = "port"
        # 이 분기는 RST 를 관측했기에만 도달한다 (_check_ports 의 any_response 조건)
        result["failure_code"] = "TCP_CONNECTION_REFUSED"
        result["failure_reason"] = (
            "호스트는 응답하지만 서비스 포트가 열려 있지 않습니다. "
            "방화벽 설정과 서비스 기동 상태를 확인하세요."
        )
        result["detail"] = "; ".join(port_errors)
        module.exit_json(**result)

    result["reachable"] = True
    result["port_open"] = True
    result["selected_port"] = open_port

    if channel == "os":
        os_type, scheme = _detect_os_from_port(open_port)
        result["detected_os"] = os_type
        result["winrm_scheme"] = scheme
        result["detected_port"] = open_port

    # Stage 3: protocol_supported
    #
    # 2026-08-10 (Phase 3-A): probe_protocol=false 면 Stage 3 자체를 수행하지 않는다.
    #   이때 protocol_supported 는 초기값 False 로 남는다. 이는 "프로토콜이 없다"가 아니라
    #   **"확인하지 않았다"** 는 뜻이다 (rule: 관측하지 않은 것을 true 로 만들지 않는다).
    #   호출부가 protocol_checked=False 를 보고 이 구분을 할 수 있게 결과에 함께 싣는다
    #   — 이 키는 build_diagnosis 가 매핑하지 않으므로 envelope 에는 나가지 않는다.
    if not module.params["probe_protocol"]:
        result["protocol_checked"] = False
        module.exit_json(**result)

    result["protocol_checked"] = True
    ok, err, facts = _probe_protocol(
        channel, host, open_port, module.params["timeout_protocol"], verify_ssl
    )
    if not ok:
        result["failure_stage"] = "protocol"
        result["failure_code"] = "PROTOCOL_CHECK_FAILED"
        result["failure_reason"] = CHANNEL_PROTOCOL_MESSAGES.get(
            channel, "프로토콜 확인 실패"
        )
        result["detail"] = err
        module.exit_json(**result)
    result["protocol_supported"] = True
    if facts:
        result["probe_facts"].update(facts)

    # Stage 4: auth_success (인증 정보 있을 때만)
    #
    # 2026-08-10 실측 주의 — **production 경로에서 Stage 4 는 항상 skip 된다.**
    #   redfish-gather/site.yml:41-47 과 esxi-gather/site.yml:46-52 는 precheck 에
    #   username/password 를 넘기지 않으므로 아래 if 가 성립하지 않고 auth_success 는
    #   None 으로 남는다. 이는 **버그가 아니라 설계**다:
    #     - redfish 는 Vault 2단계 로딩 구조라 precheck 시점에 아직 벤더가 확정되지
    #       않았고 → 어느 vault 를 열지 모르므로 자격증명 자체가 존재하지 않는다
    #       (detect_vendor.yml 이 precheck 다음에 실행된다).
    #     - 여기서 굳이 인증을 시도하면 본 수집 전에 실패 시도가 1회 더 쌓여
    #       BMC 계정 잠금 위험이 커진다(try_one_account.yml:77-88 의 5초 backoff 참조).
    #   실제 인증 성공 여부는 본 수집 성공 후 site.yml 이 auth_success: true 로
    #   덮어쓴다(redfish-gather/site.yml:191-193, esxi-gather/site.yml:200-210).
    #   → 아래 분기는 단위 테스트 / 수동 진단(직접 invoke) 용 경로다. 유지한다.
    username = module.params.get("username")
    password = module.params.get("password")
    if username and password and channel == "redfish":
        if not _try_redfish_auth(
            host, open_port, username, password,
            module.params["timeout_auth"], verify_ssl, result
        ):
            module.exit_json(**result)
    # esxi/os 인증은 Ansible 본체 모듈이 처리 → auth_success는 None 유지

    module.exit_json(**result)


def main():
    run_module()


if __name__ == "__main__":
    main()
