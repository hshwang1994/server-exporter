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
import socket
import ssl
import urllib.error
import urllib.request


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


def http_get(url, timeout, verify=False, auth=None):
    """HTTP GET — urllib stdlib 단일 경로 (외부 의존 없음).

    반환: (ok, err, payload) — payload={'status_code': int, 'json': dict|None}

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
        try:
            json_body = json.loads(body)
        except (ValueError, json.JSONDecodeError):
            json_body = None
        return True, None, {"status_code": status, "json": json_body}
    except urllib.error.HTTPError as e:
        return False, "HTTP {0}".format(e.code), {
            "status_code": e.code,
            "json": None,
        }
    except socket.timeout:
        return False, "요청 시간 초과 (timeout={0}s)".format(timeout), None
    except urllib.error.URLError as e:
        # ConnectionRefusedError / SSL handshake / DNS 등 묶음
        return False, "연결 실패: {0}".format(str(e.reason)[:200]), None
    except (ssl.SSLError, OSError) as e:
        return False, str(e)[:200], None


def ssh_banner_check(host, port, timeout):
    """SSH 배너 확인으로 SSH 서비스 동작 여부 검증 (IPv4/IPv6 듀얼 스택)."""
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
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            banner = sock.recv(256).decode("utf-8", errors="replace").strip()
            if banner.startswith("SSH-"):
                return True, None, {"ssh_banner": banner}
            # Round 15: 빈/비-SSH 배너 → 즉시 return 대신 다음 주소군(dual-stack) 시도.
            # 기존엔 IPv6 가 먼저 해석되어 빈 배너 반환 시 IPv4 SSH 를 시도조차 못 함 (tcp_check 패턴 일관).
            last_err = "SSH 배너가 아닙니다: {0}".format(banner[:50])
        except Exception as e:
            last_err = str(e)
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


def probe_os(host, port, timeout):
    """OS 채널 프로토콜 프로브 (SSH banner 또는 WinRM endpoint).

    WinRM (5985/5986): /wsman 이 200/401/403/405/503 응답 시 서비스 살아있음.
    403/503 추가 (probe_redfish 와 동일 정합): SPN 불일치/잠긴 계정 (403),
    IIS 재시작 중 (503) 등도 endpoint 자체는 살아있음 → 본 Ansible 수집에서
    처리. 이전 구현은 이를 "WinRM 미응답" 으로 오판정했음.

    SSH (22): banner 가 'SSH-' 로 시작하는지로 판정 — banner 차단 SSH 서버는
    이전과 동일하게 fail (드문 케이스, 별도 cycle 검토).
    """
    if port == 22:
        return ssh_banner_check(host, port, timeout)
    elif port in (5985, 5986):
        scheme = "https" if port == 5986 else "http"
        url = "{0}://{1}:{2}/wsman".format(scheme, host, port)
        ok, err, payload = http_get(url, timeout, verify=False)
        if ok or (payload and payload.get("status_code") in (200, 401, 403, 405, 503)):
            facts = {
                "transport": "winrm",
                "scheme": scheme,
                "port": port,
            }
            if payload:
                facts["root_status_code"] = payload.get("status_code")
            return True, None, facts
        return False, err, None
    else:
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


def _check_ports(host, ports, timeout_port):
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
        probed.append(port)
        ok, err, kind = tcp_check_ex(host, port, timeout_port)
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
        ),
        supports_check_mode=True,
    )

    host = module.params["host"]
    channel = module.params["channel"]
    ports = module.params["ports"] or CHANNEL_DEFAULT_PORTS.get(channel, [])
    verify_ssl = module.params["verify_ssl"]
    result = _init_result(channel, ports)

    # Stage 1+2: reachable + port_open (rule 27 R2 — host alive 분리)
    any_response, target_port_open, open_port, port_errors, port_kinds, probed = _check_ports(
        host, ports, module.params["timeout_port"]
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
