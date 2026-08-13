#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Ansible Custom Module: redfish_gather  v4
------------------------------------------
검증된 벤더별 URI 구조 (공식 문서 기반):

  HPE iLO 5/6/7 : Systems/1               / Managers/1   (Oem.Hpe / Oem.Hp fallback)
  Dell iDRAC 9/10 : Systems/System.Embedded.1 / Managers/iDRAC.Embedded.1  (Oem.Dell)
  Lenovo XCC/XCC2/XCC3 : Systems/1        / Managers/1   (Oem.Lenovo)
  Supermicro X11~X14 : Systems/1          / Managers/1   (Oem.Supermicro)
    Manufacturer = "Super Micro Computer, Inc."
  Cisco CIMC M4~M8 / UCS X-Series : Systems/<serial> / Managers/CIMC (Oem.Cisco — 옵션)
    Manufacturer = "Cisco Systems"

외부 라이브러리 불필요 — Python stdlib(urllib, ssl, socket) 만 사용

──────────────────────────────────────────────────────────────────────────────
Read-only 보장 (F83 / F87 — DSP0266 §11 + bmcweb OpenBMC #262 회피):
──────────────────────────────────────────────────────────────────────────────
본 모듈은 GET only — 정보 수집만 수행.
- _post() / _patch() 헬퍼는 P2 AccountService 계정 생성/갱신 진입점 한정 사용
  (recovery 계정 부재 시 자동 생성). dryrun=true 가 기본값이라 실 BMC 호출은
  사용자 명시 토글 후만. dryrun=false 도 idempotent (이미 존재 시 PATCH skip).
- ETag / If-Match 헤더 미사용 → bmcweb 일부 펌웨어의 If-Match crash 회피
  (OpenBMC issue #262).
- DELETE / OEM Action (SystemErase / SetBiosTime / RetryCloudConnect / ClearCMOS
  등) 절대 호출 안 함.
- F84 cycle 2026-05-01 추가: TLS 1.2/1.3 양쪽 호환 — _ctx() 가 SSLContext
  default 정책 (TLS 1.2 minimum) 사용. 구 BMC OpenSSL 3.x renegotiation 은
  OP_LEGACY_SERVER_CONNECT 로 호환. SECLEVEL=0 으로 weak cipher 허용.
"""

__metaclass__ = type

DOCUMENTATION = r'''
module: redfish_gather
short_description: Gather hardware info via Redfish API (Dell/HPE/Lenovo/Supermicro/Cisco)
options:
  bmc_ip:     required, str
  username:   required, str
  password:   required, str, no_log
  timeout:    optional, int, default 30
  verify_ssl: optional, bool, default false
'''

import json, re, socket, sys, time, traceback

# ── 단위 변환 상수 (cycle 2026-06-04 R-4 — 매직넘버 명명) ──────────────────────
# 주의: decimal(10^n) 과 binary(2^n) 는 의미가 다르므로 절대 통합 금지.
#   capacity_gb = DECIMAL GB (÷1e9) / total_mb·capacity_mb = BINARY MiB (÷2^20).
BYTES_PER_GB_DECIMAL = 1_000_000_000   # 10^9 — CapacityBytes ↔ capacity_gb (decimal GB)
BYTES_PER_MIB = 1048576                # 2^20 — CapacityBytes → total_mb (binary MiB)
MIB_PER_GIB = 1024                     # 2^10 — MiB → GiB (binary, grouping key)
MBPS_PER_GBPS = 1000.0                 # 10^3 — 네트워크 Mbps → Gbps (decimal bitrate, byte 아님)
MAX_COLLECTION_MEMBERS = 1024          # rule 95 R1: 무경계 Members/Drives 순회 DoS 상한 (실 BMC << 1024)


def _removeprefix(s, prefix):
    """str.removeprefix() 호환 (Python 3.8 이하 지원)"""
    if s.startswith(prefix):
        return s[len(prefix):]
    return s


def _safe_int(x, default=None):
    """Redfish 응답 robustness — string/None/non-numeric → default.

    rule 96 외부 계약 drift 대비. 펌웨어 변경으로 capacity 필드가 비-숫자
    문자열 또는 None을 반환할 때 ValueError로 모듈 자체가 죽는 사고 차단.
    """
    if x is None:
        return default
    try:
        return int(x)  # rule 95 R1 #7 ok: try/except 보호 안
    except (ValueError, TypeError, OverflowError):  # Round 15: int(float('inf')) → OverflowError 방어
        return default


def _safe_round_int(x, default=None):
    """소수 측정값(온도 등)을 반올림 정수로. _safe_int 의 int() 절삭과 달리 round() 사용.

    2026-06-16 감사 G1: 온도 reading 을 _safe_int 로 받으면 44.7031→44 / 38.86→38 /
    -68.75→-68 처럼 소수점 절삭(≤1° 오차)이 발생. round() 로 44.7→45 / 38.86→39 / -68.75→-69.
    int 계약은 유지(타입 불변) — 절삭 대신 반올림만 교체. _safe_int 는 watt/capacity 등 다른
    호출부에서 그대로 사용(회귀 0). 비-숫자/None/inf/nan → default.
    """
    if x is None:
        return default
    try:
        f = float(x)
    except (ValueError, TypeError, OverflowError):
        return default
    if f != f or f in (float('inf'), float('-inf')):  # nan/inf 흡수
        return default
    return int(round(f))


def _safe_num(x, default=None):
    """유한 숫자 정규화 — int 는 int, **유한 float 는 float 로 보존**; bool/비-숫자/None/inf/nan → default.

    Round 19 (R19-2/3 regression fix): _safe_int 는 int() 라 fractional float 를 truncate 한다
    (2.5GbE = CurrentSpeedGbps 2.5 → 2 데이터 손상). DMTF Port.CurrentSpeedGbps 는 number 타입이라
    소수 합법. 본 helper 는 fractional 보존 + inf/nan(json.loads 기본 허용) 은 None 으로 흡수해
    int() 캐스트 OverflowError/ValueError 도 차단한다.
    """
    if isinstance(x, bool):  # bool 은 int 하위형 — float(True)=1.0 오역산 방지
        return default
    try:
        f = float(x)
    except (ValueError, TypeError):
        return default
    if f != f or f in (float('inf'), float('-inf')):  # NaN(f!=f) / ±Infinity
        return default
    return int(x) if isinstance(x, int) else f


def _normalize_port_speed(pdata):
    """Redfish Port/NetworkPort 의 현재 링크 속도를 (speed_gbps, speed_mbps) 로 정규화.

    Round 17 #3: 신 Port resource(1.6+, `Ports`)는 CurrentSpeedGbps(Gbps) 만 주고
    CurrentLinkSpeedMbps(구 `NetworkPorts` 전용)를 안 준다. 따라서 Mbps 가 없으면
    Gbps 에서 역산해야 Ports-only 어댑터(HPE 등)의 current_link_speed_mbps /
    adapter speed_mbps 가 None 으로 유실되지 않는다. _safe_num 으로 정규화하여 숫자-문자열
    Gbps('10')·fractional Gbps(2.5) 보존 + bool/inf/nan 은 None 으로 방어.
    """
    cur_gbps = _safe(pdata, 'CurrentSpeedGbps')
    # Round 18/19: _safe_num 으로 정규화 — bool/문자열-비숫자/None/inf/nan 은 None(섹션 drop 유발
    # int() OverflowError/ValueError 차단), int 는 int, **fractional float(2.5GbE)는 float 보존**.
    cur_gbps_num = _safe_num(cur_gbps)
    speed_mbps = _safe_int(_safe(pdata, 'CurrentLinkSpeedMbps'))  # Round 3 #17: mbps int 통일
    if speed_mbps is None and cur_gbps_num:
        # round: fractional Gbps(2.5→2500) 정확 변환 + float 정밀도 truncation 방지
        speed_mbps = _safe_int(round(cur_gbps_num * MBPS_PER_GBPS))
    # SCHEMA-02 (2026-06-15 HPE DL380 검수): 미연결(LinkDown) FC/Ethernet 포트는
    # CurrentSpeedGbps=0 / CurrentLinkSpeedMbps 부재로 노출된다. 0 은 '0Gbps 협상'이
    # 아니라 '링크 없음' → speed_gbps 도 None 으로 정규화 (truthy 분기). field_dictionary
    # (hbas link_speed_gbps 'null when unlinked') 계약 + 동일 포트 current_link_speed_mbps
    # (미연결 시 None) 와 내부 일관성 확보. 양수 속도(2.5/25/32 등)는 truthy 라 영향 없음.
    if cur_gbps_num:
        speed_gbps = cur_gbps_num
    elif speed_mbps:
        speed_gbps = speed_mbps / MBPS_PER_GBPS
    else:
        speed_gbps = None
    return speed_gbps, speed_mbps


try:
    import urllib.request as urlreq
    import urllib.error as urlerr
    import ssl, base64
    HAS_URLLIB = True
except ImportError:
    HAS_URLLIB = False

from ansible.module_utils.basic import AnsibleModule


# ── HTTP 유틸 ────────────────────────────────────────────────────────────────

# verify_ssl(bool) 별 SSLContext 캐시 (cycle 2026-05-29 audit — host 당 재생성 제거)
_CTX_CACHE = {}


def _ctx(verify_ssl):
    """HTTPS context — verify_ssl=False 시 self-signed BMC 인증서 허용.

    cycle 2026-04-30: 구 BMC (HPE iLO4, Lenovo IMM2, 일부 iDRAC7/8 펌웨어) 호환.
    OpenSSL 3.x legacy renegotiation + weak cipher 허용 — verify=False 환경 한정.
    curl -k 와 동등한 관용성. 사내 BMC self-signed 망 한정.

    F84 cycle 2026-05-01 — TLS 1.2/1.3 양쪽 호환 명시:
    - minimum_version = TLSv1_2 (DMTF DSP0266 §10.2 권장 + iLO 7 enum 제거)
    - maximum_version = TLSv1_3 (Gen11+ / XCC3+ / X14+ 강제 가능)
    - SECLEVEL=0 으로 weak cipher 허용 (iLO 4 / IMM2 / 구 iDRAC 펌웨어)
    구 BMC TLS 1.0/1.1 만 지원하면 본 코드는 핸드셰이크 실패 → graceful
    degradation 으로 status=failed (precheck protocol 단계). 별 사고 신호
    없으면 minimum_version 유지. (rule 92 R2)

    cycle 2026-05-29 (audit): verify_ssl(bool) 별 1회만 빌드 후 재사용 (_CTX_CACHE).
    SSLContext 는 다중 연결 재사용이 표준 (Python 권장). host 당 30~150 회 재생성
    제거 — 동작 동일 (controller-side CPU/alloc 절감). Ansible module 은 host 당
    단일 subprocess → thread-safety 무관.
    """
    _cache_key = bool(verify_ssl)
    _cached = _CTX_CACHE.get(_cache_key)
    if _cached is not None:
        return _cached
    ctx = ssl.create_default_context()
    # TLS 1.2 minimum (DSP0266 §10.2). TLS 1.0/1.1 은 이미 DMTF/HPE/Cisco/Dell 모두 deprecated.
    if hasattr(ssl, 'TLSVersion'):
        try:
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.maximum_version = ssl.TLSVersion.TLSv1_3
        except (ValueError, AttributeError):
            # Python < 3.7 또는 OpenSSL TLS 1.3 미지원 — default 유지
            pass
    if not verify_ssl:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        if hasattr(ssl, 'OP_LEGACY_SERVER_CONNECT'):
            ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
        try:
            ctx.set_ciphers('DEFAULT@SECLEVEL=0')
        except ssl.SSLError:
            pass
    _CTX_CACHE[_cache_key] = ctx
    return ctx

def _auth(username, password):
    return 'Basic ' + base64.b64encode(f'{username}:{password}'.encode()).decode()

# ── 인증 응답 관측 (2026-08-11 Phase 5-A) ──────────────────────────────────────
# 자격증명을 실은 요청이 받은 **첫 HTTP status** 만 기록한다.
#   - 새 요청을 만들지 않는다. 이미 보내는 요청의 반환값만 본다 → 인증 시도 횟수 불변
#     (계정 잠금 위험이 커지지 않는다).
#   - 문자열 파싱이 아니다. urllib 이 준 정수 status 를 그대로 쓴다.
#   - 이 값은 module result 의 `auth_evidence` 로만 나가고 외부 envelope 을 늘리지 않는다.
#     site.yml 이 401(명시적 거부)일 때만 auth_success=false 로 쓴다. 403 은 인증 이후
#     권한 부족일 수 있어 거부로 확정하지 않는다.
_AUTH_OBSERVATION = {'first_status': None}


def _reset_auth_observation():
    _AUTH_OBSERVATION['first_status'] = None


def _record_auth_status(status):
    if _AUTH_OBSERVATION['first_status'] is None and isinstance(status, int) and status:
        _AUTH_OBSERVATION['first_status'] = status


def auth_evidence():
    """module result 로 내보낼 구조화 인증 관측값 (문자열 파싱 없음)."""
    return {'first_auth_status': _AUTH_OBSERVATION['first_status']}


# ── 정보성 통보 (notices) — 2026-08-12 신설 ──────────────────────────────────
#
# "성공한 fallback" 을 errors[] 에 넣지 않는다.
#   종전에는 SimpleStorage / SmartStorage fallback 으로 **데이터를 정상 수집했는데도**
#   errors 에 항목이 생겼고, _make_section_runner 의 `if errs: failed.append(section)` 때문에
#   그 섹션이 failed 로 잡혀 overall status 가 partial 로 강등됐다 (H11).
#   HPE iLO4 같은 구세대 BMC 는 **매 수집마다** partial 로 보고됐다.
#
# 정보를 버리지는 않는다. module result 의 `notices` 로 내보내고
# redfish-gather/site.yml 이 diagnosis.details.notices 에 싣는다
# (envelope 13 top-level 필드 변경 아님 — CLAUDE.md §11 이 details 를 기술 evidence /
#  확장 metadata 영역으로 규정한다).
_NOTICES = []


def _reset_notices():
    del _NOTICES[:]


def _notice(section, message):
    """수집에 성공했지만 사용자/운영자가 알아둘 사실 1건. 중복은 담지 않는다."""
    entry = {'section': section, 'message': str(message)}
    if entry not in _NOTICES:
        _NOTICES.append(entry)
    return entry


def notices():
    return list(_NOTICES)


def _get(bmc_ip, path, username, password, timeout, verify_ssl):
    """인증 GET — 반환 status 를 _record_auth_status 로 관측만 한다(요청 수 불변)."""
    status, data, err = _get_impl(bmc_ip, path, username, password, timeout, verify_ssl)
    _record_auth_status(status)
    return status, data, err


def _get_impl(bmc_ip, path, username, password, timeout, verify_ssl):
    url = f'https://{bmc_ip}/redfish/v1/{path.lstrip("/")}'
    # cycle 2026-04-30 hotfix: User-Agent 추가가 Lenovo XCC 일부 펌웨어 reject 유발 (사이트 검증).
    # Accept + OData-Version 만 유지 (cycle 전부터 동작 검증된 헤더 셋).
    req = urlreq.Request(url, headers={
        'Authorization': _auth(username, password),
        'Accept': 'application/json',
        'OData-Version': '4.0',
    })
    try:
        with urlreq.urlopen(req, context=_ctx(verify_ssl), timeout=timeout) as resp:
            # Round 17 #18: 성공 path 의 json.loads 를 지역 guard 로 감싼다.
            # 200(또는 2xx) + 빈 body 는 {}(tolerant), 비-JSON body(프록시 HTML/잘린 응답)는
            # err 설정. 둘 다 실제 status 를 보존(기존엔 함수-레벨 except 로 status 0 오보).
            # 빈 vs 비-JSON 구분: ServiceRoot 같은 detect 경로에서 malformed body 는 명확히
            # 실패로 남겨야 함(빈 {} 로 진행해 vendor=unknown 으로 새지 않게).
            raw = resp.read()
            try:
                data = json.loads(raw.decode('utf-8', errors='replace')) if raw else {}
                decode_err = None
            except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
                data, decode_err = {}, f'HTTP {resp.status}: body not JSON'
            return resp.status, data, decode_err
    except urlerr.HTTPError as e:
        try:    body = json.loads(e.read().decode('utf-8', errors='replace'))
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError): body = {}
        return e.code, body, f'HTTP {e.code}: {e.reason}'
    except urlerr.URLError as e:
        return 0, {}, f'URLError: {e.reason}'
    except socket.timeout:
        return 0, {}, f'Timeout after {timeout}s'
    except (OSError, ValueError) as e:
        return 0, {}, f'Unexpected: {type(e).__name__}: {e}'

def _post(bmc_ip, path, body, username, password, timeout, verify_ssl):
    """P2 (cycle 2026-04-28): AccountService 계정 생성 (POST /Accounts)."""
    url = f'https://{bmc_ip}/redfish/v1/{path.lstrip("/")}'
    try:
        payload = json.dumps(body).encode('utf-8')
    except TypeError:  # Round 4 #4/#5: 비-직렬화 body 방어 (provision crash 차단)
        payload = json.dumps(str(body)).encode('utf-8')
    req = urlreq.Request(url, data=payload, method='POST', headers={
        'Authorization': _auth(username, password),
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'OData-Version': '4.0',
    })
    try:
        with urlreq.urlopen(req, context=_ctx(verify_ssl), timeout=timeout) as resp:
            raw = resp.read()
            try:
                data = json.loads(raw.decode('utf-8', errors='replace')) if raw else {}
            except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
                data = {}
            return resp.status, data, None
    except urlerr.HTTPError as e:
        try:    body_err = json.loads(e.read().decode('utf-8', errors='replace'))
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError): body_err = {}
        return e.code, body_err, f'HTTP {e.code}: {e.reason}'
    except urlerr.URLError as e:
        return 0, {}, f'URLError: {e.reason}'
    except socket.timeout:
        return 0, {}, f'Timeout after {timeout}s'
    except (OSError, ValueError) as e:
        return 0, {}, f'Unexpected: {type(e).__name__}: {e}'

def _delete(bmc_ip, path, username, password, timeout, verify_ssl):
    """F50 phase 4 (cycle 2026-05-06): DELETE method 추가 — Lenovo XCC 권한 cache 손상 시
    DELETE + POST 재생성 fallback. Dell iDRAC 는 DELETE 미지원 (PATCH-only)."""
    url = f'https://{bmc_ip}/redfish/v1/{path.lstrip("/")}'
    req = urlreq.Request(url, method='DELETE', headers={
        'Authorization': _auth(username, password),
        'Accept': 'application/json',
        'OData-Version': '4.0',
    })
    try:
        with urlreq.urlopen(req, context=_ctx(verify_ssl), timeout=timeout) as resp:
            return resp.status, {}, None
    except urlerr.HTTPError as e:
        try:    body_err = json.loads(e.read().decode('utf-8', errors='replace'))
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError): body_err = {}
        return e.code, body_err, f'HTTP {e.code}: {e.reason}'
    except urlerr.URLError as e:
        return 0, {}, f'URLError: {e.reason}'
    except socket.timeout:
        return 0, {}, f'Timeout after {timeout}s'
    except (OSError, ValueError) as e:
        return 0, {}, f'Unexpected: {type(e).__name__}: {e}'


def _patch(bmc_ip, path, body, username, password, timeout, verify_ssl,
           extra_headers=None):
    """P2 (cycle 2026-04-28): AccountService 계정 update (PATCH /Accounts/{id}).

    extra_headers (2026-08-12): If-Match 를 **요구하는 Family 에서만** 실어 보낸다.
      전 vendor 에 ETag 를 켜지 않는 이유는 모듈 상단 주석 참조 (bmcweb If-Match crash).
    """
    url = f'https://{bmc_ip}/redfish/v1/{path.lstrip("/")}'
    try:
        payload = json.dumps(body).encode('utf-8')
    except TypeError:  # Round 4 #4/#5: 비-직렬화 body 방어 (provision crash 차단)
        payload = json.dumps(str(body)).encode('utf-8')
    headers = {
        'Authorization': _auth(username, password),
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'OData-Version': '4.0',
    }
    if extra_headers:
        headers.update({k: v for k, v in extra_headers.items() if v})
    req = urlreq.Request(url, data=payload, method='PATCH', headers=headers)
    try:
        with urlreq.urlopen(req, context=_ctx(verify_ssl), timeout=timeout) as resp:
            raw = resp.read()
            try:
                data = json.loads(raw.decode('utf-8', errors='replace')) if raw else {}
            except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
                data = {}
            return resp.status, data, None
    except urlerr.HTTPError as e:
        try:    body_err = json.loads(e.read().decode('utf-8', errors='replace'))
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError): body_err = {}
        return e.code, body_err, f'HTTP {e.code}: {e.reason}'
    except urlerr.URLError as e:
        return 0, {}, f'URLError: {e.reason}'
    except socket.timeout:
        return 0, {}, f'Timeout after {timeout}s'
    except (OSError, ValueError) as e:
        return 0, {}, f'Unexpected: {type(e).__name__}: {e}'

def _p(uri):
    """@odata.id URI → _get() path 인수.

    rule 95 R1: @odata.id 는 Redfish spec 상 str URI 지만, 오염/펌웨어 버그로 비-str
    (dict/int)이 오면 uri.lstrip 이 AttributeError → 호출 섹션 전체가 죽는다(silent
    total-section loss). 비-str 은 절대 매치 안 되는 무효 path 로 치환해 _get 가 404 로
    깨끗이 실패하게 한다 — '' 반환은 ServiceRoot(200) 오인 위험이 있어 금지.
    """
    if not isinstance(uri, str):
        return '__invalid_odata_id__'
    result = _removeprefix(_removeprefix(uri.lstrip('/'), 'redfish/v1/'), 'redfish/v1').rstrip('/')
    # 빈 path('/redfish/v1' 같은 퇴화 입력)는 _get('')=ServiceRoot(200) 오인 → 무효 처리 (Round 1 #23)
    return result if result else '__invalid_odata_id__'

def _safe(d, *keys, default=None):
    for k in keys:
        if not isinstance(d, dict): return default
        d = d.get(k, default)
        if d is None: return default
    return d

def _as_list(x):
    """비-list 오염 방어 — list 면 그대로, 아니면 [] (문자열/숫자 배열 반복용, Round 3)."""
    return x if isinstance(x, list) else []

def _dicts(x):
    """외부 배열에서 dict 원소만 추출 (비-list/비-dict 방어 — .get() 반복 crash 차단, Round 3)."""
    return [e for e in x if isinstance(e, dict)] if isinstance(x, list) else []

def _str(x):
    """문자열 메서드(.lower/.strip/.split 등) 호출 전 비-str(int/dict 오염) 방어.
    str 면 그대로, 아니면 '' (Round 8). `(x or '')` 와 str/None 입력에 동일 — golden 불변."""
    return x if isinstance(x, str) else ''

# 내부 분류 code — errors[] 원소에 붙되 **envelope 으로는 나가지 않는다**
# (common/tasks/normalize 의 정규화가 section/message/detail 3키만 뽑는다).
# 사용자 문구를 제어 로직의 키로 쓰지 않기 위한 자리다 (2026-08-12).
_CODE_VENDOR_UNRESOLVED = 'vendor_unresolved'


def _err(section, message, detail=None, code=None):
    entry = {'section': section, 'message': str(message), 'detail': detail}
    if code:
        entry['code'] = code
    return entry


# 확장 오류 정보에서 뽑을 최대 ExtendedInfo 항목 수 / 최종 문자열 길이 상한.
# BMC 가 수십 개 항목을 반환해도 errors[].detail 이 비대해지지 않게 절단한다.
MAX_EXTENDED_INFO_ITEMS = 3
MAX_EXTENDED_INFO_LEN = 300

# 이번 run 에서 표준 계정에 허용할 **최대 실패 인증 횟수**.
# Dell IP Blocking 기본값(60초 창에서 3회)을 기준으로 잡는다 — 장비가 정책을 알려주지
# 않아도 무제한으로 두지 않는다.
ACCOUNT_DEFAULT_AUTH_BUDGET = 3


def account_auth_budget(policy):
    """장비가 선언한 lockout 임계에서 실패 인증 예산을 끌어온다.

    **재시도를 늘리는 장치가 아니다.** 상한을 두어 검증 루프가 계정을 잠그기 전에
    멈추게 한다. `AccountLockoutThreshold == 0` 을 "제한 없음" 으로 읽지 않는다 —
    Dell 은 그 값이 0 이어도 IP Blocking(FailCount 3 / FailWindow 60s)이 따로 동작한다.
    source: 02 §22/§23, 03 §22, 04 §22, 06 §21, 07 §25
    """
    threshold = (policy or {}).get('lockout_threshold')
    if isinstance(threshold, int) and not isinstance(threshold, bool) and threshold > 0:
        # 임계에 도달하기 전에 멈춘다.
        return max(1, min(threshold - 1, ACCOUNT_DEFAULT_AUTH_BUDGET + 2))
    return ACCOUNT_DEFAULT_AUTH_BUDGET


# 계정 쓰기 후 재인증 확인 간격(초). 첫 시도는 지연 없이, 이후 1초 / 5초.
# BMC 가 계정 변경을 비동기 반영하거나 직전 연결이 옛 자격으로 남아 있는 경우를 흡수한다.
# 합계 6초 — 무한 대기가 되지 않도록 값 자체로 상한을 고정한다.
ACCOUNT_VERIFY_DELAYS = (0, 1, 5)

# 재인증 확인 총 대기 상한(초). 장비가 선언한 패널티가 아무리 길어도 이 값을 넘지 않는다.
ACCOUNT_VERIFY_MAX_TOTAL_SECONDS = 45


def account_verify_delays(policy):
    """장비가 **스스로 선언한** 인증 실패 패널티보다 짧게 확인하지 않는다.

    2026-08-12 사이트 실측 (HPE iLO6 / ProLiant DL380 Gen11):
      AccountService 가 ``AuthFailureDelayTimeSeconds=10``, ``AuthFailuresBeforeDelay=1`` 을
      선언한다. 즉 **첫 실패 직후부터** 그 계정의 인증이 10초간 막힌다. 표준 자격 인증이
      한 번 실패한 뒤 복구하는 흐름에서는 패널티가 이미 켜져 있으므로, 고정 6초(0/1/5) 안의
      재인증은 비밀번호를 올바로 썼더라도 전부 401 이 된다. 그러면 성공한 쓰기가
      'verification=failed' 로 보고되고, 사람을 계정 삭제/재생성 쪽으로 몰아간다.

    그래서 확인 간격을 장비가 준 값에서 끌어온다. 정책을 바꾸지 않고 **읽기만** 한다.
    """
    delays = list(ACCOUNT_VERIFY_DELAYS)
    penalty = 0
    for key in ('auth_failure_delay_seconds', 'lockout_duration'):
        value = (policy or {}).get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > penalty:
            penalty = value
    if penalty <= 0:
        return tuple(delays)
    remaining = ACCOUNT_VERIFY_MAX_TOTAL_SECONDS - sum(delays)
    extra = min(penalty + 2, remaining)
    if extra > 0:
        delays.append(extra)
    return tuple(delays)

# 2026-08-12 (rev.2): `ACCOUNT_OPTIONAL_PATCH_PROPS` 를 제거했다. "거부되면 빼도 되는
# 속성" 이라는 개념 자체가 추측성 재시도를 전제한다. 무엇을 보낼지는 쓰기 **전에**
# Family Property Contract 가 정한다 (`_ACCOUNT_PROP_DEFAULTS` / `props`).

_READ_ONLY_PROP_RE = re.compile(
    r'property\s+([A-Za-z][A-Za-z0-9_]*)\s+is\s+a?\s*read[\s-]?only', re.IGNORECASE
)

# `MessageArgs` 를 "거부된 속성 이름" 으로 읽어도 되는 MessageId 접미사.
# DSP0266 Base registry 에서 첫 인자가 property 이름인 메시지들이다. 이 목록에 없는
# MessageId 의 MessageArgs 는 값 / 리소스 / 자유 문장일 수 있으므로 읽지 않는다.
# 종전에는 MessageId 를 보지 않고 **모든** MessageArgs 문자열을 거부 속성으로 취급해,
# 성공 응답에 딸려온 정보성 메시지 하나가 Password 이후 재시도에서 Enabled/RoleId 를
# 통째로 떨어뜨릴 수 있었다.
# source: redfish.dmtf.org/registries/Base.1.12.0.json (PropertyNotWritable /
#         PropertyValueNotInList / PropertyUnknown 의 Arg1 = property name)
_PROPERTY_ARG_MESSAGE_IDS = (
    'PropertyNotWritable',
    'PropertyReadOnly',
    'PropertyNotUpdatable',
    'PropertyUnknown',
)
_PROP_NAME_RE = re.compile(r'\A[A-Za-z][A-Za-z0-9_]*\Z')

# 거부 종류. 셋을 구분해야 "왜 실패했는지" 를 사람이 알 수 있고, 무엇보다
# **재시도해도 되는 것이 하나도 없다** 는 사실이 분명해진다.
REJECT_READ_ONLY = 'read_only'        # 그 속성은 쓸 수 없다
REJECT_VALUE = 'value_rejected'       # 값이 허용 형식/목록에 맞지 않다
REJECT_POLICY = 'policy_rejected'     # 값이 장비 정책에 걸렸다 (Dell SYS474 등)

# 명시적 거부로 볼 Severity. 정보성 메시지(OK)는 거부가 아니다.
#   "모든 Warning 을 실패로 처리하는 것도 잘못" (02 §12) 이라 Severity 하나만으로 판단하지
#   않고, 아래에서 RelatedProperties 가 **우리가 실제로 요청한 속성**을 가리킬 때만 센다.
_REJECT_SEVERITIES = frozenset({'warning', 'critical', 'error'})

# `#/Password` / `#/Attributes/Foo` 같은 RelatedProperties 항목에서 속성 이름만 뽑는다.
# DMTF DSP0266: RelatedProperties 는 JSON Pointer fragment 다.
_RELATED_PROP_RE = re.compile(r'\A#?/(?:.*/)?([A-Za-z][A-Za-z0-9_]*)\Z')


def _related_property_names(item):
    """ExtendedInfo 항목의 `RelatedProperties` → 속성 이름 목록."""
    names = []
    for ref in _as_list(item.get('RelatedProperties')):
        if not isinstance(ref, str):
            continue
        m = _RELATED_PROP_RE.match(ref.strip())
        if m:
            names.append(m.group(1))
        elif _PROP_NAME_RE.match(ref.strip()):
            names.append(ref.strip())
    return names


def write_rejections(body, requested=None):
    """쓰기 응답이 **명시적으로 거부한** 항목들. `[{property, kind, message_id, severity}]`

    왜 `rejected_patch_properties()` 로 부족한가 (2026-08-12 Dell 실측):
        Dell 은 비밀번호가 정책에 걸리면 **HTTP 200** 과 함께 다음을 돌려준다.
            MessageId         = IDRAC.x.SYS474
            Message           = "Unable to set the password because the password entered
                                 does not comply to the Security Strengthen Policy standards."
            Severity          = Warning
            MessageArgs       = []
            RelatedProperties = ["#/Password"]
        종전 parser 는 (a) "그 속성은 read only" 문장과 (b) PropertyNotWritable 계열의
        `MessageArgs` 만 읽었다. SYS474 는 둘 중 어느 것도 아니라 **성공으로 통과**했고,
        그 뒤 재인증이 401 이 나면 원인을 "비밀번호 정책쯤" 으로 추측할 수밖에 없었다.
        같은 응답에 `Base.1.12.Success` / `SYS413` 성공 메시지가 함께 오기 때문에
        "성공 메시지가 있으니 성공" 도 성립하지 않는다.

    `requested` 를 주면 **우리가 실제로 보낸 속성**을 가리키는 거부만 센다. 응답에 딸려온
    다른 속성의 정보성 경고를 우리 요청의 실패로 오판하지 않기 위해서다.

    source: DMTF DSP0266 (`@Message.ExtendedInfo`, `RelatedProperties`, `MessageSeverity`),
            Dell Error and Event Message Guide (SYS474),
            사이트 실측 (10.100.15.34 iDRAC9 / Redfish 1.20.1)
    """
    if not isinstance(body, dict):
        return []
    err = body.get('error')
    scope = err if isinstance(err, dict) else body
    found = []
    seen = set()

    def _add(prop, kind, msg_id, severity):
        key = (prop, kind)
        if key in seen:
            return
        seen.add(key)
        found.append({'property': prop, 'kind': kind,
                      'message_id': msg_id, 'severity': severity})

    for item in _dicts(scope.get('@Message.ExtendedInfo')):
        msg_id = item.get('MessageId') if isinstance(item.get('MessageId'), str) else None
        sev = item.get('MessageSeverity') or item.get('Severity')
        sev = sev.lower() if isinstance(sev, str) else None

        # (1) 장비가 문장으로 "그 속성은 read only" 라고 말한 경우 — 가장 강한 신호다.
        #     단 `requested` 가 주어지면 **우리가 보낸 속성**에 대한 말일 때만 센다.
        #     보내지도 않은 속성의 경고를 우리 요청의 실패로 읽으면, 정상 쓰기가
        #     장비의 부수 메시지 하나 때문에 실패로 둔갑한다.
        text = item.get('Message')
        if isinstance(text, str):
            m = _READ_ONLY_PROP_RE.search(text)
            if m and (requested is None or m.group(1) in requested):
                _add(m.group(1), REJECT_READ_ONLY, msg_id, sev)

        # (2) MessageId 가 "첫 인자는 property 이름" 계열일 때만 MessageArgs 를 읽는다.
        if msg_id and any(msg_id.endswith(s) for s in _PROPERTY_ARG_MESSAGE_IDS):
            for arg in _as_list(item.get('MessageArgs')):
                if isinstance(arg, str) and _PROP_NAME_RE.match(arg) \
                        and (requested is None or arg in requested):
                    _add(arg, REJECT_READ_ONLY, msg_id, sev)
            continue

        # (3) RelatedProperties 가 우리가 요청한 속성을 가리키고 Severity 가 경고 이상이면
        #     그것은 정보가 아니라 거부다. read_only 로 이미 잡힌 것은 위에서 처리됐다.
        if sev in _REJECT_SEVERITIES:
            for prop in _related_property_names(item):
                if requested is not None and prop not in requested:
                    continue
                _add(prop, REJECT_POLICY, msg_id, sev)

    text = scope.get('message')
    if isinstance(text, str):
        m = _READ_ONLY_PROP_RE.search(text)
        if m:
            _add(m.group(1), REJECT_READ_ONLY, None, None)
    return found


def rejected_patch_properties(body):
    """쓰기 응답에서 "이 속성은 쓸 수 없다" 고 지목된 속성 이름들.

    왜 필요한가 (2026-08-12 Dell 실측):
        iDRAC10 은 `Locked` 를 포함한 계정 PATCH 에 **HTTP 200** 을 주면서 본문에
            Base.1.12.GeneralError
            "The property Locked is a read only property and cannot be assigned a value."
        를 담아 **요청 전체를 거부**했다. 상태 코드만 보면 성공이고, 실제로는 Password 도
        적용되지 않는다. 그 뒤 새 자격으로 인증하면 401 이 나오고, 코드는 원인을
        "비밀번호 정책 미충족" 쯤으로 추측할 수밖에 없었다.

        종전 코드에는 `Locked` 를 빼고 재시도하는 경로가 이미 있었지만 **HTTP 400/405
        에서만** 켜졌다. 200 으로 거부하는 펌웨어에는 도달하지 않았다.

    반환: 응답이 지목한 속성 이름 집합 (없으면 빈 set).
    source: DMTF DSP0266 Error responses (`@Message.ExtendedInfo`, `MessageArgs`),
            사이트 실측 (10.100.15.34 iDRAC9 / Redfish 1.20.1).

    2026-08-12 (rev.2): 본문은 `write_rejections()` 로 옮겼다. 이 함수는 **read-only 거부만**
    돌려주는 종전 계약을 유지한다 — 정책 거부(SYS474 등)는 "우리가 무엇을 요청했는지" 를
    알아야 정확히 판정되므로 `write_rejections(body, requested)` 를 직접 써야 한다.
    """
    return {r['property'] for r in write_rejections(body)
            if r['kind'] == REJECT_READ_ONLY and r['property']}


def _extended_info(body, limit=MAX_EXTENDED_INFO_LEN):
    """Redfish 오류 응답 body 에서 표준 확장 오류 정보를 사람이 읽을 한 줄로 축약.

    cycle 2026-08-03 (사이트 Dell 8대 400 사고): 지금까지 collection GET 실패 시 status
    코드만 남기고 body 를 버려 `detail: null` 이었다. DMTF DSP0266 은 오류 응답에
    `error.code` / `error.message` / `error.@Message.ExtendedInfo[]` 를 정의하고, 벤더는
    여기에 "왜 거부했는지"(미구현 / 라이선스 / 파라미터 오류)를 담는다. 이 정보를 버리면
    같은 400 이라도 '미지원' 인지 '우리 요청 결함' 인지 구분할 근거가 envelope 에 남지
    않는다 (rule 96 R2 — 외부 계약 확인 가능성 확보).

    source (rule 96 R1-A): DMTF DSP0266 Redfish Specification — "Error responses".

    Returns: 축약 문자열 또는 None (추출 가능한 정보 없음). Additive — 기존 detail=None
    호출부 동작 불변, envelope shape 변경 0 (rule 96 R1-B).
    """
    if not isinstance(body, dict):
        return None
    err = body.get('error')
    if not isinstance(err, dict):
        err = body
    parts = []

    def _push(v):
        if isinstance(v, str) and v.strip() and v.strip() not in parts:
            parts.append(v.strip())

    _push(err.get('code'))
    _push(err.get('message'))
    for item in _dicts(err.get('@Message.ExtendedInfo'))[:MAX_EXTENDED_INFO_ITEMS]:
        _push(item.get('Message') or item.get('MessageId'))
        _push(item.get('Resolution'))
    out = ' | '.join(parts).strip()
    return out[:limit] or None


def _capped(seq, section=None, errors=None):
    """무경계 collection(Members/Drives) 순회 상한 — P2 DoS/huge-payload 방어.

    오염/악성/버그 BMC 가 수천 멤버를 반환하면 멤버당 _get 가 N회 네트워크 왕복(각 timeout)을
    유발해 사실상 hang. cap 초과 시 절단 + _err 로 명시(silent 절단 금지 — rule 70).
    실 BMC 멤버 수는 cap 보다 훨씬 작아 정상 입력 결과 불변(rule 92 R2 Additive).

    2026-08-12 (M6): 종전에는 `errors=None` 으로 부르는 호출부(power TelemetryService,
    thermal Sensors)에서 **절단 사실이 아무 데도 남지 않았다** — docstring 이 금지한 silent
    절단이 실제로 두 곳에서 일어나고 있었다. 두 호출부는 (val, errors) 를 반환하지 않는
    헬퍼 안이라 errors 리스트를 넘길 자리가 없다. 함수 시그니처를 바꾸는 대신,
    errors 가 없으면 모듈 수준 notices 로 떨어뜨려 사실이 남게 한다.
    """
    seq = seq if isinstance(seq, list) else []  # Round 4 #2: 비-list 방어 (len/slice crash 차단)
    if len(seq) > MAX_COLLECTION_MEMBERS:
        if section:
            text = (f'collection 멤버 {len(seq)} > 상한 {MAX_COLLECTION_MEMBERS} '
                    f'— 절단(DoS 방어)')
            if errors is not None:
                errors.append(_err(section, text))
            else:
                _notice(section, text)
        return seq[:MAX_COLLECTION_MEMBERS]
    return seq


# 2026-04-29 fix B90 / B23: JEDEC ID -> vendor name normalization (rule 10 stdlib only)
# Cisco CIMC returns Memory.Manufacturer as raw '0xCExx' (Samsung) instead of name.
# JEP106 standard: 7-bit ID byte (MSB = parity). Common DRAM vendors below.
_JEDEC_VENDORS = {
    "01": "AMD",
    "0B": "Intel",
    "1F": "Atmel",
    "2C": "Micron Technology",
    "98": "Kingston",
    "AD": "SK hynix",
    "B3": "IDT",
    "BA": "PNY Electronics",
    "CE": "Samsung",
    "04": "Fujitsu",
    "07": "Hitachi",
}


# 2026-04-30 추가: vendor 이름 변형 → canonical name (cross-vendor consistency).
# BMC마다 같은 제조사를 다른 표기로 노출 (Dell="Hynix Semiconductor", Linux dmidecode="SK hynix").
_VENDOR_NAME_NORMALIZATION = {
    "hynix": "SK hynix",
    "hynix semiconductor": "SK hynix",
    "sk hynix": "SK hynix",
    "skhynix": "SK hynix",
    "samsung electronics": "Samsung",
    "samsung electronic": "Samsung",
    "micron": "Micron Technology",
    "micron technology": "Micron Technology",
    "kingston technology": "Kingston",
}


def _canonical_vendor_name(name):
    """Map vendor-name variants to canonical form. Used for memory.manufacturer cross-vendor consistency."""
    if not name or not isinstance(name, str):
        return name
    return _VENDOR_NAME_NORMALIZATION.get(name.strip().lower(), name)


def _normalize_jedec(value):
    """Normalize a JEDEC manufacturer ID hex string to vendor name.

    Handles:
      - "0xCE00" / "0xCE" / "0xAD00" (Cisco CIMC)
      - "00CE" / "00AD063200AD" (raw JEDEC, dmidecode style)
      - "Samsung" / "Hynix Semiconductor" — canonical normalization (cross-vendor)
      - None / "" / "Unknown" / "Not Specified" -> None
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in ("unknown", "not specified", "none"):
        return None
    # 0x prefixed hex (Cisco CIMC)
    if s.lower().startswith("0x"):
        hp = s[2:].upper()
        if hp[:2] in _JEDEC_VENDORS:
            return _JEDEC_VENDORS[hp[:2]]
        return s  # unknown — keep raw for traceability
    # Vendor name (contains non-hex alpha or whitespace)
    if " " in s or any(c.isalpha() and c not in "ABCDEFabcdef" for c in s):
        return _canonical_vendor_name(s)
    # Plain hex string
    if all(c in "0123456789ABCDEFabcdef" for c in s) and len(s) >= 2:
        # Try first byte (some BMCs) or 2nd byte (continuation+ID)
        for idx in (slice(2, 4), slice(0, 2)):
            byte = s[idx].upper() if len(s) >= idx.stop else None
            if byte and byte in _JEDEC_VENDORS:
                return _JEDEC_VENDORS[byte]
        return s
    return _canonical_vendor_name(s)


def _strip_or_none(value):
    """Strip whitespace and convert empty/sentinel strings to None.

    Cisco BMC가 일부 필드를 trailing space 포함하여 emit ('M386A8K40BM1-CRC    ').
    Cross-vendor 정합성 위해 모든 string 값을 strip 후 빈 문자열은 None.
    Non-string은 unchanged.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    s = value.strip()
    return s or None


# ── 벤더 정규화 ──────────────────────────────────────────────────────────────

# 내장 벤더 매핑 (vendor_aliases.yml 로드 불가 시 fallback)
# ※ common/vars/vendor_aliases.yml과 동기화 필요 — 변경 시 양쪽 모두 수정할 것
# canonical vendors: dell, hpe, lenovo, supermicro, cisco
# nosec rule12-r1: 아래 dict는 vendor 분기 코드가 아니라 Ansible runtime 외 환경
# (pytest / 직접 invoke)에서 vendor_aliases.yml load 실패 시 fallback 정규화 맵.
# vendor_aliases.yml이 primary, 본 dict는 secondary. 신규 alias 추가 시 vendor_aliases.yml만
# 갱신하면 충분 (verify_harness_consistency.py 동기화 게이트로 drift 검출).
_FALLBACK_VENDOR_MAP = {
    'dell': 'dell', 'dell inc.': 'dell', 'dell emc': 'dell',                # nosec rule12-r1
    'hpe': 'hpe', 'hewlett packard enterprise': 'hpe',                      # nosec rule12-r1
    'hewlett packard enterprise co.': 'hpe', 'hewlett-packard': 'hpe',      # nosec rule12-r1
    'hp enterprise': 'hpe', 'hp': 'hpe',                                    # nosec rule12-r1
    'lenovo': 'lenovo', 'lenovo group ltd.': 'lenovo',                      # nosec rule12-r1
    'lenovo group limited': 'lenovo', 'ibm': 'lenovo',                      # nosec rule12-r1
    'supermicro': 'supermicro', 'super micro computer, inc.': 'supermicro', # nosec rule12-r1
    'super micro computer': 'supermicro', 'smci': 'supermicro',             # nosec rule12-r1
    'cisco': 'cisco', 'cisco systems inc': 'cisco',                         # nosec rule12-r1
    'cisco systems inc.': 'cisco', 'cisco systems, inc': 'cisco',           # nosec rule12-r1
    'cisco systems, inc.': 'cisco', 'cisco systems': 'cisco',               # nosec rule12-r1
    # 2026-05-01 F44~F47 (사용자 명시 승인): Huawei / Inspur / Fujitsu / Quanta
    'huawei': 'huawei', 'huawei technologies co., ltd.': 'huawei',          # nosec rule12-r1
    'huawei technologies': 'huawei',                                        # nosec rule12-r1
    'inspur': 'inspur',                                                     # nosec rule12-r1
    'inspur information technology company limited': 'inspur',              # nosec rule12-r1
    'inspur information': 'inspur', 'inspur systems': 'inspur',             # nosec rule12-r1
    'fujitsu': 'fujitsu', 'fujitsu limited': 'fujitsu',                     # nosec rule12-r1
    'fujitsu technology solutions': 'fujitsu',                              # nosec rule12-r1
    'quanta': 'quanta', 'quanta computer': 'quanta',                        # nosec rule12-r1
    'quanta computer inc.': 'quanta',                                       # nosec rule12-r1
    'quanta cloud technology': 'quanta', 'qct': 'quanta',                   # nosec rule12-r1
}
# 호환 alias (외부 코드가 _BUILTIN_VENDOR_MAP 이름 참조 시)
_BUILTIN_VENDOR_MAP = _FALLBACK_VENDOR_MAP

# BMC 시그니처 → vendor (Redfish ServiceRoot Product/Name 필드의 BMC 제품명 매칭)
# nosec rule12-r1: ServiceRoot v1.0~1.4 펌웨어는 Vendor/Product 표준 필드 부재.
# BMC 제품명이 vendor 시그니처로 사실상 외부 Redfish spec 일부 (HPE Hpe namespace,
# Dell iDRAC, Lenovo XClarity 등). vendor 분기 코드가 아니라 정규화 맵.
_BMC_PRODUCT_HINTS = {
    'idrac': 'dell', 'integrated dell': 'dell',                             # nosec rule12-r1
    'ilo': 'hpe', 'proliant': 'hpe',                                        # nosec rule12-r1
    'xclarity': 'lenovo', 'thinksystem': 'lenovo',                          # nosec rule12-r1
    'xcc': 'lenovo', 'imm2': 'lenovo',                                      # nosec rule12-r1
    'megarac': 'supermicro',                                                # nosec rule12-r1
    'cimc': 'cisco', 'ucs': 'cisco',                                        # nosec rule12-r1
    # 2026-05-01 F44~F47 (사용자 명시 승인) — vendor BMC 시그니처
    'ibmc': 'huawei', 'fusionserver': 'huawei',                             # nosec rule12-r1
    'isbmc': 'inspur',                                                      # nosec rule12-r1
    'irmc': 'fujitsu', 'primergy': 'fujitsu',                               # nosec rule12-r1
    'quantagrid': 'quanta', 'quantaplex': 'quanta',                         # nosec rule12-r1
    # 2026-05-06 M-E2 (HPE Superdome Flex / Flex 280 web 검색 — lab 부재):
    # Superdome Flex 의 RMC (Rack Management Controller) host 가 ServiceRoot.Product 에
    # "Superdome Flex" 또는 "iLO 5" 로 응답 — hpe sub-line. Manufacturer 시그니처
    # 부재 펌웨어 환경에서 BMC 제품명으로 정규화 강건성 향상.
    # source: HPE Superdome Flex Server Admin Guide + sdflexutils GitHub
    'superdome': 'hpe', 'superdome flex': 'hpe',                            # nosec rule12-r1
    # 2026-06-04 (HP CSUS 3200 사이트 사고): RMC 가 ServiceRoot.Product/Name 에
    # "Compute Scale-up Server 3200" 으로 응답 — Manufacturer/alias 시그니처 부재
    # 펌웨어에서 무인증 probe 벤더 감지 강건성 향상 (rule 96 R1-A web 검증).
    # 복합 키만 사용 — 'csus'/'compute' 단독은 비-HPE Product/Name 와 substring 충돌
    # 위험 (워크플로 adversarial 검증 — _detect_vendor_from_service_root 의
    # `if hint in p`(Product) / `if hint in n`(Name) plain substring 매칭).
    # source: HPE Compute Scale-up Server 3200 FAQ + Superdome Flex Admin Guide (CSUS = Superdome Flex 후속).
    'compute scale-up server': 'hpe', 'csus 3200': 'hpe',                   # nosec rule12-r1
}


def _load_vendor_aliases_file():
    """vendor_aliases.yml을 로드합니다. 실패 시 빈 dict 반환.

    Path resolution 우선순위:
      1. SE_VENDOR_ALIASES_PATH 환경변수 (명시 override)
      2. REPO_ROOT 환경변수 + common/vars/vendor_aliases.yml
      3. __file__ 기반 ../../common/vars/vendor_aliases.yml (Ansible 표준 배치)
    """
    import os
    try:
        import yaml
    except ImportError:
        return {}

    candidates = []
    # 1. 명시 override
    explicit = os.environ.get('SE_VENDOR_ALIASES_PATH', '')
    if explicit:
        candidates.append(explicit)
    # 2. REPO_ROOT 기반
    repo_root = os.environ.get('REPO_ROOT', '')
    if repo_root:
        candidates.append(os.path.join(repo_root, 'common', 'vars', 'vendor_aliases.yml'))
    # 3. __file__ 기반 (redfish-gather/library/redfish_gather.py → common/vars/...)
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        # __file__ → redfish-gather/library/ → ../../common/vars/
        candidates.append(os.path.normpath(os.path.join(here, '..', '..', 'common', 'vars', 'vendor_aliases.yml')))
    except NameError:
        pass

    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            mapping = {}
            for canonical, alias_list in data.get('vendor_aliases', {}).items():
                if not isinstance(canonical, str):  # Round 13 #0: 비-str canonical(YAML int key) 방어
                    continue
                for alias in (alias_list if isinstance(alias_list, list) else []):  # Round 9 #0: str alias_list char 순회 방지
                    if isinstance(alias, str):  # Round 5 #10: None/비-str alias 가 로드 abort 시키지 않게
                        mapping[alias.strip().lower()] = canonical
            if mapping:
                return mapping
        except (IOError, OSError, yaml.YAMLError, AttributeError, TypeError):
            continue
    return {}

def _normalize_vendor_from_aliases(mfr_lower):
    """
    Manufacturer 문자열(소문자)을 정규화된 벤더명으로 변환합니다.
    1차: vendor_aliases.yml (REPO_ROOT 기반)
    2차: 내장 fallback 맵
    3차: 부분 매칭 (substring)
    """
    # 2026-08-12: 빈 입력 방어. 아래 부분 매칭의 `mfr_lower in key` 는 mfr_lower 가
    #   '' 이면 **모든 key 에 대해 참**이라, 공백-only Manufacturer("   ") 가 dict 첫
    #   항목의 vendor 로 확정되는 오탐이 있었다 (:1216 이 `mfr.strip().lower()` 로 호출).
    #   종전에는 그 오탐이 adapter 선택에만 영향했지만, Credential Vault 경로가 vendor
    #   에서 파생되면서 **다른 vendor 의 자격증명을 시도**하는 결과로 이어진다.
    #   빈 alias 방어(`if key and ...`)는 이미 있었고 빈 입력 방어만 없었다.
    if not mfr_lower:
        return 'unknown'

    # vendor_aliases.yml 시도 (primary)
    aliases = _load_vendor_aliases_file()
    # aliases (YAML primary) 우선, fallback dict는 보조
    merged = {**_FALLBACK_VENDOR_MAP, **aliases}

    # 정확 매칭
    if mfr_lower in merged:
        return merged[mfr_lower]

    # 부분 매칭 (기존 로직 호환)
    for key, canon in merged.items():
        if key and (key in mfr_lower or mfr_lower in key):  # rule 95: 빈 alias wildcard 매칭 방어 (Round 1 #9)
            return canon

    return 'unknown'


# ── 벤더 감지 ────────────────────────────────────────────────────────────────

def _probe_realm_hint(bmc_ip, timeout, verify_ssl):
    """G6 (cycle 2026-04-30): 401/403 응답의 WWW-Authenticate realm에서 vendor hint 추출.

    ServiceRoot 본문이 비어 vendor 식별 불가한 BMC에서도 401 응답 헤더의
    `WWW-Authenticate: Basic realm="iDRAC"` / `realm="iLO"` / `realm="XClarity Controller"`
    같은 realm 문자열로 vendor를 추정한다. 부가 fallback (필수 아님).

    Returns: vendor canonical name 또는 None
    """
    import re
    url = f'https://{bmc_ip}/redfish/v1/'
    req = urlreq.Request(url, headers={'Accept': 'application/json', 'OData-Version': '4.0'})
    realm_header = None
    try:
        # 무인증으로 시도 — 200이면 realm 없음 (이미 다른 단계에서 처리)
        with urlreq.urlopen(req, context=_ctx(verify_ssl), timeout=timeout) as resp:
            return None
    except urlerr.HTTPError as e:
        # 401/403일 때 WWW-Authenticate 헤더에서 realm 추출
        if e.code in (401, 403):
            realm_header = e.headers.get('WWW-Authenticate') or ''
    except (urlerr.URLError, socket.timeout, OSError, ValueError):
        return None

    if not realm_header:
        return None

    # realm="..." 추출
    m = re.search(r'realm\s*=\s*"([^"]+)"', realm_header, re.IGNORECASE)
    if not m:
        m = re.search(r"realm\s*=\s*'([^']+)'", realm_header, re.IGNORECASE)
    if not m:
        return None
    realm = m.group(1).lower().strip()

    # vendor_aliases + BMC product hints 매칭
    aliases_yaml = _load_vendor_aliases_file()
    vm = {**_FALLBACK_VENDOR_MAP, **aliases_yaml}
    for alias, canon in vm.items():
        if alias and alias in realm:
            return canon
    # nosec rule12-r1: realm BMC 시그니처
    for hint, canon in _BMC_PRODUCT_HINTS.items():                              # nosec rule12-r1
        if hint in realm:                                                       # nosec rule12-r1
            return canon                                                        # nosec rule12-r1
    return None


def _get_noauth(bmc_ip, path, timeout, verify_ssl):
    """인증 없이 GET 요청 (ServiceRoot 등 무인증 엔드포인트용)"""
    url = f'https://{bmc_ip}/redfish/v1/{path.lstrip("/")}'
    req = urlreq.Request(url, headers={
        'Accept': 'application/json',
        'OData-Version': '4.0',
    })
    try:
        with urlreq.urlopen(req, context=_ctx(verify_ssl), timeout=timeout) as resp:
            # Round 17 #18: 성공 path json.loads 지역 guard — 200+빈 body 는 {}(tolerant),
            # 비-JSON body 는 err 설정. status 0 오보 방지 + detect 경로 malformed 명확 실패.
            raw = resp.read()
            try:
                data = json.loads(raw.decode('utf-8', errors='replace')) if raw else {}
                decode_err = None
            except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
                data, decode_err = {}, f'HTTP {resp.status}: body not JSON'
            return resp.status, data, decode_err
    except urlerr.HTTPError as e:
        try:    body = json.loads(e.read().decode('utf-8', errors='replace'))
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError): body = {}
        return e.code, body, f'HTTP {e.code}: {e.reason}'
    except urlerr.URLError as e:
        return 0, {}, f'URLError: {e.reason}'
    except socket.timeout:
        return 0, {}, f'Timeout after {timeout}s'
    except (OSError, ValueError) as e:
        return 0, {}, f'Unexpected: {type(e).__name__}: {e}'


def _detect_vendor_from_service_root(root):
    """
    ServiceRoot 응답에서 벤더를 식별합니다 (무인증).

    식별 알고리즘 (대소문자 무시):
      1. Oem 객체의 키 이름 확인
      2. Vendor 필드 확인
      3. Product 필드에 벤더명 포함 확인
      4. Name 필드에 벤더명 포함 확인
      5. 모두 해당 없으면 None 반환

    Returns: vendor 문자열 ('dell', 'hpe', 'lenovo', 'supermicro', 'cisco') 또는 None
    """
    # production-audit (2026-04-29): vendor_aliases.yml + fallback merge.
    # 기존 _BUILTIN_VENDOR_MAP만 사용 시 YAML에 추가된 alias가 detect에 반영 안 되는 drift 차단.
    aliases_yaml = _load_vendor_aliases_file()
    vm = {**_FALLBACK_VENDOR_MAP, **aliases_yaml}

    # 1. Oem 객체의 키 이름 확인
    oem = _safe(root, 'Oem')
    if isinstance(oem, dict):
        # 1-A. 정확 매칭 (예: Oem.Lenovo, Oem.Hpe, Oem.Dell)
        for key in oem:
            k = key.lower()
            if k in vm:
                return vm[k]
        # 1-B. namespace prefix 매칭 — Lenovo XCC2/XCC3 'Lenovo_xxx', 일부 펌웨어 'Hpe_xxx' 등
        # nosec rule12-r1: BMC vendor OEM namespace prefix → vendor 식별 (외부 Redfish spec)
        for key in oem:                                                       # nosec rule12-r1
            k = key.lower()                                                   # nosec rule12-r1
            for alias, canon in vm.items():                                   # nosec rule12-r1
                if not alias:                                                 # nosec rule12-r1
                    continue                                                  # nosec rule12-r1
                if k.startswith(alias + '_') or k.startswith(alias + '.'):    # nosec rule12-r1
                    return canon                                              # nosec rule12-r1

    # 2. Vendor 필드 확인 — ServiceRoot v1.5.0+ 표준
    # G7 (cycle 2026-04-30): 'Dell Inc.' 같은 trailing dot/whitespace + substring 매칭
    vendor_field = _safe(root, 'Vendor')
    if vendor_field and isinstance(vendor_field, str):
        v = vendor_field.lower().strip()
        # 2-A. 정확 매칭 (원형 + trailing dot 제거 두 형식 둘 다 시도)
        for cand in (v, v.rstrip('.').strip()):
            if cand in vm:
                return vm[cand]
        # 2-B. substring 매칭 (Product/Name과 동일 정신)
        for alias, canonical in vm.items():
            if alias and alias in v:
                return canonical

    # 3. Product 필드에 벤더명 포함 확인 — ServiceRoot v1.3.0+ 표준
    product = _safe(root, 'Product')
    if product and isinstance(product, str):
        p = product.lower()
        for alias, canonical in vm.items():
            if alias and alias in p:  # rule 95: 빈 alias wildcard 매칭 방어 (Round 1 #8, 아래 Name 필드 동일 가드)
                return canonical
        # nosec rule12-r1: BMC 시그니처 → vendor 식별 (외부 Redfish spec OEM namespace)
        for hint, canon in _BMC_PRODUCT_HINTS.items():                        # nosec rule12-r1
            if hint in p:                                                     # nosec rule12-r1
                return canon                                                  # nosec rule12-r1

    # 4. Name 필드에 벤더명 포함 확인 — Cisco "Cisco RESTful Root Service" 등
    name = _safe(root, 'Name')
    if name and isinstance(name, str):
        n = name.lower()
        for alias, canonical in vm.items():
            if alias and alias in n:  # rule 95: 빈 alias wildcard 매칭 방어 (Round 1 #8)
                return canonical
        # nosec rule12-r1: BMC 시그니처 fallback (Name 필드)
        for hint, canon in _BMC_PRODUCT_HINTS.items():                        # nosec rule12-r1
            if hint in n:                                                     # nosec rule12-r1
                return canon                                                  # nosec rule12-r1

    # 5. 해당 없음
    return None


def _fetch_service_root(bmc_ip, username, password, timeout, verify_ssl):
    """ServiceRoot(/redfish/v1/) 응답 fetch — 무인증 → 인증 fallback.

    Returns: (root_dict_or_none, errors_list)
    """
    errors = []
    st, root, err = _get_noauth(bmc_ip, '', timeout, verify_ssl)
    if err or st != 200:
        # 무인증 실패 시 인증으로 재시도 (일부 BMC는 ServiceRoot도 인증 필요)
        st, root, err = _get(bmc_ip, '', username, password, timeout, verify_ssl)
        if err or st != 200:
            errors.append(_err('vendor_detect', f'ServiceRoot 실패: {err or st}'))
            return None, errors
    if not isinstance(root, dict):  # Round 6 #1: 비-dict ServiceRoot JSON(문자열/숫자) 계약 위반 방어
        errors.append(_err('vendor_detect', 'ServiceRoot JSON 이 object 아님'))
        return None, errors
    return root, errors


def _endpoint_with_fallback(bmc_ip, primary_path, fallback_path, username,
                            password, timeout, verify_ssl, section_name='generic'):
    """primary endpoint 시도 → 404 / 미지원 시 fallback endpoint 시도.

    cycle 2026-05-01 신설 (rule 22 R5 헬퍼 추상화 / HARNESS B5).
    Storage→SimpleStorage / Power→PowerSubsystem / 향후 ThermalSubsystem 같은
    DMTF 변천 호환 패턴을 재사용 가능한 단일 함수로 추상화.

    Behavior:
    - primary GET → 200 이면 (data, [], 'primary') 반환
    - primary 404 → fallback GET → 200 이면 (data, [], 'fallback') 반환
    - fallback 404 → ({}, [], 'not_supported') 반환 (호출자가 분류)
    - 5xx / 401 / 403 / 그 외 → ({}, [error], 'failed')

    호환성 fallback only — envelope 신 키 추가 안 함 (rule 96 R1-B Additive).

    Args:
        bmc_ip: BMC IP
        primary_path: 우선 시도 path (예: /Chassis/{id}/Power)
        fallback_path: 404 시 fallback path (예: /Chassis/{id}/PowerSubsystem)
        username, password, timeout, verify_ssl: 표준 HTTP 옵션
        section_name: error 분류 라벨 (envelope errors[] 의 stage)

    Returns:
        (data_dict, errors_list, source_label)
        source_label: 'primary' | 'fallback' | 'not_supported' | 'failed'
    """
    errors = []
    st, data, err = _get(bmc_ip, primary_path, username, password, timeout, verify_ssl)

    if not err and st == 200:
        return data, errors, 'primary'

    if st == 404:
        st_fb, data_fb, err_fb = _get(bmc_ip, fallback_path, username, password,
                                      timeout, verify_ssl)
        if not err_fb and st_fb == 200:
            return data_fb, errors, 'fallback'
        if st_fb == 404:
            return {}, errors, 'not_supported'
        errors.append(_err(section_name,
                           f'fallback {fallback_path} 실패: {err_fb or st_fb}'))
        return {}, errors, 'failed'

    errors.append(_err(section_name, f'{primary_path} 실패: {err or st}'))
    return {}, errors, 'failed'


def _resolve_first_member_uri(bmc_ip, coll_uri, username, password, timeout, verify_ssl):
    """컬렉션 URI → 첫 번째 Member의 @odata.id 추출.

    Managers/Chassis 등 N+1 컬렉션에서 첫 멤버만 반환 (NEXT_ACTIONS T3-05 — 향후 결정).
    Returns: (member_uri_or_none, status_code, error_msg)
    """
    if not coll_uri:
        return None, None, 'collection uri 없음'
    st, coll, err = _get(bmc_ip, _p(coll_uri), username, password, timeout, verify_ssl)
    if err or st != 200:
        return None, st, err or f'HTTP {st}'
    members = _safe(coll, 'Members') or []
    if not isinstance(members, list) or not members:  # rule 95 R1 #2: 비-list Members 방어 (Round 1 #24)
        return None, st, 'members 없음'
    return _safe(members[0], '@odata.id'), st, None


def _resolve_all_member_uris(bmc_ip, coll_uri, username, password, timeout, verify_ssl):
    """컬렉션 URI → 모든 Members 의 @odata.id 추출 (cycle 2026-05-12 — ADR-2026-05-12).

    `_resolve_first_member_uri` 의 Additive 확장. RMC (HPE Compute Scale-up Server 3200 /
    Superdome Flex) 같이 단일 진입점이 N개 Manager / N개 nPartition / N개 Chassis 를
    노출하는 환경에서 전수 수집을 위해 신설. 기존 단일 노드 함수는 변경 0 (rule 92 R2
    Additive only / rule 95 R1 #11 production 위험 회피).

    source (rule 96 R1-A):
      - HPE 공식: "supports large, partitionable systems managed by a single aggregated
        controller like HPE Compute Scale-up Server 3200 RMC"
      - DMTF DSP0266 v1.15.0 Collection.Members[] 표준 schema

    Returns: (members: list[dict], status_code, error_msg)
        members: [{'uri': str, 'id': str}]  (Member ID = URI 의 마지막 path segment)
    """
    if not coll_uri:
        return [], None, 'collection uri 없음'
    st, coll, err = _get(bmc_ip, _p(coll_uri), username, password, timeout, verify_ssl)
    if err or st != 200:
        return [], st, err or f'HTTP {st}'
    raw_members = _safe(coll, 'Members') or []
    if not isinstance(raw_members, list):  # rule 95 R1 #2: 비-list Members 방어 (Round 2 #15)
        raw_members = []
    out = []
    for m in raw_members:
        uri = _safe(m, '@odata.id')
        if not uri or not isinstance(uri, str):  # Round 3 #3: 비-str @odata.id .rstrip 방어
            continue
        # Member ID = URI 의 마지막 path segment (trailing '/' 제거)
        mid = uri.rstrip('/').rsplit('/', 1)[-1] if '/' in uri else uri
        out.append({'uri': uri, 'id': mid})
    if not out:
        return [], st, 'members 없음'
    return out, st, None


def _resolve_system_chassis_uri(bmc_ip, system_uri, default_chassis_uri,
                                username, password, timeout, verify_ssl):
    """System.Links.Chassis[0] 를 power/thermal/network_adapters/system 용 chassis 로 해석.

    cycle 2026-06-15 (HPE CSUS 3200 실미러 검수, CSUS-R1): multi-chassis RMC aggregation
    환경(HPE Compute Scale-up Server 3200 / Superdome Flex)에서 Chassis 컬렉션 첫 멤버는
    집계용 RackGroup 으로 PowerSubsystem / ThermalSubsystem / NetworkAdapters 가 부재한다.
    detect_vendor 가 `_resolve_first_member_uri(Chassis)` 로 그 RackGroup 을 chassis_uri 로
    잡으면 power/thermal/network_adapters 가 빈 chassis 에서 수집돼 data.power={}·data.thermal={}
    인데 collected=success (누락이 정상처럼 보임) + network_adapters=unsupported + FC HBA 소실.
    실제 데이터는 시스템이 속한 compute chassis(예: r001u01)에 있고, 그 chassis 는
    ComputerSystem.Links.Chassis 로 명시된다.

    본 helper 는 System.Links.Chassis[0] 를 반환하고, 부재/실패 시 default_chassis_uri
    (detect_vendor 의 첫 멤버) 로 graceful fallback 한다. 단일 chassis vendor(Dell/HPE/
    Lenovo 실미러 검증)는 Links.Chassis[0] == Chassis 컬렉션 첫 멤버라 동작 불변 (Additive,
    회귀 안전). PoweredBy/CooledBy 는 Dell 처럼 PSU/Fan fragment(`#/PowerSupplies/0`)를
    가리키는 벤더가 있어 chassis URI 로 쓰지 않는다 — Links.Chassis 만 신뢰.

    source (rule 96 R1-A): DMTF DSP0266 ComputerSystem.Links.Chassis (시스템이 속한 chassis).
    Returns: chassis_uri (str) — Links.Chassis[0] 또는 default_chassis_uri.
    """
    if not system_uri:
        return default_chassis_uri
    st, data, err = _get(bmc_ip, _p(system_uri), username, password, timeout, verify_ssl)
    if err or st != 200 or not isinstance(data, dict):
        return default_chassis_uri
    for link in _dicts(_safe(data, 'Links', 'Chassis')):  # 비-list/비-dict 방어 (rule 95 R1 #2)
        uri = _safe(link, '@odata.id')
        if uri and isinstance(uri, str):
            return uri
    return default_chassis_uri


def _classify_rmc_label(manager_uri, manager_id, manager_layout, is_first=True):  # nosec rule12-r1
    """Manager URI / ID + adapter capability 기반 BMC 표시명 결정 (cycle 2026-05-12).

    HPE CSUS 3200 / Superdome Flex 의 RMC primary 시스템에서 manager 별 라벨 분기:
      - RMC (Rack Management Controller) → 'RMC'
      - PDHC (per-chassis controller) → 'PDHC'
      - per-node iLO 5 → 'iLO'

    rule 12 R1 Allowed 영역 — line ~1559 `bmc_names` 매핑 (외부 spec 기반 표준 이름) 의
    fallback path 확장. `manager_layout` None 시 기존 동작 100% 보존 (Additive).

    cycle 2026-06-09 (review): `is_first` 추가. layout-default 'RMC' 는 **첫 Manager**
    에만 적용한다. 구: substring 미매치 Manager 가 전부 'RMC' 로 오라벨 + _classify_manager_role
    의 role 과 불일치 (name='RMC' 인데 role=None). 비-first unmatched → None 반환 →
    호출자가 generic bmc_names[vendor] 사용. 비-documented manager ID (Managers/1 / Self)
    환경에서 다중 RMC 오라벨 + name/role 모순 차단 (lab 부재 — 사이트 ID 패턴 NEXT_ACTIONS C6).

    source (rule 96 R1-A): HPE Superdome Flex Admin Guide + sdflexutils GitHub README

    Returns: str | None  (None 시 호출자가 bmc_names[vendor] fallback 사용)
    """
    if not manager_layout:
        return None
    lid = _str(manager_id).lower()
    luri = _str(manager_uri).lower()
    # 우선순위: ID substring → URI substring → (첫 Manager 한정) layout default
    if 'rmc' in lid or 'rmc' in luri:                                            # nosec rule12-r1
        return 'RMC'                                                             # nosec rule12-r1
    if 'pdhc' in lid or 'pdhc' in luri:                                          # nosec rule12-r1
        return 'PDHC'                                                            # nosec rule12-r1
    if 'ilo' in lid or 'ilo' in luri:                                            # nosec rule12-r1
        return 'iLO'                                                             # nosec rule12-r1
    # layout default — `rmc_primary` 시 **첫 Manager 만** RMC 로 가정. 비-first 는 None
    # (호출자 generic fallback) — 다중 RMC 오라벨 방지.
    if is_first and manager_layout in ('rmc_primary', 'rmc_primary_ilo_secondary'):
        return 'RMC'                                                             # nosec rule12-r1
    return None


def _classify_manager_role(manager_uri, manager_id, manager_layout, is_first=False):  # nosec rule12-r1
    """Manager 의 role (primary / secondary) 결정 (cycle 2026-05-12).

    `manager_layout` + ID substring 매칭 기반:
      - RMC → primary
      - PDHC / iLO → secondary
      - 그 외 첫 Manager → primary, 비-first → secondary
      - layout 미정의 → None

    cycle 2026-06-09 (review): `is_first` 추가 — `_classify_rmc_label` 과 name/role 정합.
    첫 Manager unmatched → primary (RMC 가정), 비-first unmatched → secondary. substring
    매치(pdhc/ilo)는 position 무관 secondary (첫 슬롯이라도 PDHC/iLO 면 secondary).

    Returns: str | None
    """
    if not manager_layout:
        return None
    lid = _str(manager_id).lower()
    luri = _str(manager_uri).lower()
    if 'rmc' in lid or 'rmc' in luri:                                            # nosec rule12-r1
        return 'primary'
    if manager_layout in ('rmc_primary', 'rmc_primary_ilo_secondary'):
        if 'pdhc' in lid or 'pdhc' in luri or 'ilo' in lid or 'ilo' in luri:    # nosec rule12-r1
            return 'secondary'
        # substring 미매치: 첫 Manager 는 primary (RMC 가정 — label 과 정합), 그 외 secondary
        return 'primary' if is_first else 'secondary'
    return None


def _classify_chassis_kind(chassis_uri, chassis_id, chassis_data):               # nosec rule12-r1
    """Chassis 의 kind (base / expansion / compute_module) 결정 (cycle 2026-05-12).

    HPE Superdome Flex / CSUS 3200 multi-chassis 환경:
      - base / Base → 'base'
      - expansion / Expansion → 'expansion'
      - compute / module → 'compute_module'
      - ChassisType 표준 필드 사용 가능 시 우선

    source (rule 96 R1-A): DMTF DSP0266 Chassis.v1_20 ChassisType enum

    Returns: str | None
    """
    lid = _str(chassis_id).lower()
    luri = _str(chassis_uri).lower()
    if 'base' in lid or 'base' in luri:
        return 'base'
    if 'expansion' in lid or 'expansion' in luri:
        return 'expansion'
    if 'compute' in lid or 'module' in lid or 'compute' in luri:
        return 'compute_module'
    # ChassisType 표준 fallback
    if isinstance(chassis_data, dict):
        ctype = _str(_safe(chassis_data, 'ChassisType')).lower()
        if ctype == 'enclosure':
            # base / expansion 구분 안 되는 generic enclosure
            return 'enclosure'
        # CSUS-R5 (2026-06-15 실미러 검수): RackGroup / Rack 도 DMTF ChassisType enum.
        # 구: multi_node.chassis[] 의 집계 chassis(RackGroup/Rack1) kind=null → ChassisType
        # 기반으로 채워 chassis 종류 식별 가능하게 (Additive — 기존 enum 결과 불변).
        if ctype in ('rackmount', 'card', 'blade', 'rackgroup', 'rack'):
            return ctype
    return None


def detect_vendor(bmc_ip, username, password, timeout, verify_ssl):
    """ServiceRoot(무인증)에서 벤더 식별 + Systems/Managers/Chassis URI 해석.

    Returns: (vendor, system_uri, manager_uri, chassis_uri, errors, service_root)
        service_root: 무인증/인증 ServiceRoot 응답 dict 원본 (None 가능).
            cycle 2026-05-11 추가 (T-01 HPE adapter 오선택 fix) —
            _extract_probe_facts() 가 ServiceRoot 에서 model/firmware hint 추출 시 사용.
    """
    root, errors = _fetch_service_root(bmc_ip, username, password, timeout, verify_ssl)
    if root is None:
        return 'unknown', None, None, None, errors, None

    vendor = _detect_vendor_from_service_root(root)
    if vendor is None:
        vendor = 'unknown'
        errors.append(_err('vendor_detect', 'ServiceRoot에서 벤더 식별 불가',
                           code=_CODE_VENDOR_UNRESOLVED))

    systems_uri  = _safe(root, 'Systems',  '@odata.id')
    if not systems_uri:
        errors.append(_err('vendor_detect', 'ServiceRoot 에 Systems 링크 없음'))
        return vendor, None, None, None, errors, root

    system_uri, st, serr = _resolve_first_member_uri(
        bmc_ip, systems_uri, username, password, timeout, verify_ssl
    )
    if not system_uri:
        errors.append(_err('vendor_detect', f'Systems 컬렉션 실패: {serr}'))
        return vendor, None, None, None, errors, root

    # Managers / Chassis는 실패해도 errors에 등재하지 않음 — 후속 섹션에서 재시도/스킵
    manager_uri, _, _ = _resolve_first_member_uri(
        bmc_ip, _safe(root, 'Managers', '@odata.id'),
        username, password, timeout, verify_ssl,
    )
    chassis_uri, _, _ = _resolve_first_member_uri(
        bmc_ip, _safe(root, 'Chassis', '@odata.id'),
        username, password, timeout, verify_ssl,
    )

    # G3 (cycle 2026-04-30): vendor=unknown 시 Chassis/Managers/System Manufacturer fallback.
    # ServiceRoot v1.0~1.4 펌웨어는 Vendor/Product 표준 필드 부재 — Manufacturer는 표준.
    if vendor == 'unknown':
        for fb_uri, fb_label in (
            (chassis_uri, 'Chassis'),
            (manager_uri, 'Managers'),
            (system_uri, 'Systems'),
        ):
            if not fb_uri:
                continue
            fst, fdata, _ferr = _get(bmc_ip, _p(fb_uri), username, password, timeout, verify_ssl)
            if fst != 200 or not isinstance(fdata, dict):
                continue
            mfr = _safe(fdata, 'Manufacturer')
            if mfr and isinstance(mfr, str):
                fb_vendor = _normalize_vendor_from_aliases(mfr.strip().lower())
                if fb_vendor and fb_vendor != 'unknown':
                    vendor = fb_vendor
                    # 2026-08-12: 종전에는 **사용자 문구 부분일치**로 앞선 error 를 지웠다.
                    #   문구를 다듬는 순간 제어 로직이 깨지는 구조라 내부 code 로 바꿨다.
                    errors = [e for e in errors if e.get('code') != _CODE_VENDOR_UNRESOLVED]
                    # 식별에 **성공**했으므로 error 가 아니라 notice 다 (H11).
                    _notice('vendor_detect',
                            f'{fb_label} Manufacturer fallback로 vendor={fb_vendor} 식별 (ServiceRoot 정보 부족)')
                    break

    # G6 (cycle 2026-04-30): G3까지 fail이면 401 WWW-Authenticate realm 헤더로 마지막 추정.
    if vendor == 'unknown':
        realm_vendor = _probe_realm_hint(bmc_ip, timeout, verify_ssl)
        if realm_vendor:
            vendor = realm_vendor
            errors = [e for e in errors if e.get('code') != _CODE_VENDOR_UNRESOLVED]
            _notice('vendor_detect',
                    f'WWW-Authenticate realm fallback로 vendor={realm_vendor} 식별 (ServiceRoot/Resources 본문 부족)')

    return vendor, system_uri, manager_uri, chassis_uri, errors, root


def _extract_probe_facts(root, vendor):                                       # nosec rule12-r1
    """ServiceRoot 무인증 응답에서 adapter selection 용 facts 추출.

    detect_vendor.yml 의 probe 단계는 무인증 (`username=""`) 으로 호출 — 본 수집의
    `gather_system()` / `gather_bmc()` 등은 모두 401 fail → `data.system` / `data.bmc`
    empty dict. 결과: facts.model / facts.firmware 가 비어 priority 가 가장 높은
    adapter 가 model/firmware 무관하게 선택됨 (T-01: HPE DL380 Gen11 가 hpe_ilo7
    Gen12-only adapter 로 오선택 사고).

    본 함수는 ServiceRoot (무인증 / 인증 fallback) 에서 vendor 별 semantic 을 알고
    safe 한 hint 만 추출. detect_vendor.yml 이 data.bmc/data.system 비어 있을 때
    fallback 으로 사용 (Additive — 기존 path 변경 0).

    vendor 별 ServiceRoot semantic 차이 (rule 96 R1 외부 계약):
      HPE: ServiceRoot.Product = 서버 모델 (예: "ProLiant DL380 Gen11"),
           Oem.Hpe.Manager[0].ManagerFirmwareVersion = iLO 펌웨어 (예: "1.73"),
           Oem.Hpe.Manager[0].ManagerType = iLO 세대 (예: "iLO 6").
           Oem.Hp namespace (iLO 4 시기) fallback.
      Dell/Lenovo/Cisco/Supermicro/Huawei/Inspur/Fujitsu/Quanta:
           ServiceRoot.Product 가 BMC 제품명 ("Integrated Dell Remote Access
           Controller" 등) — 서버 모델 아님. 무분별 추출 시 model_patterns 매치
           실패로 잘못된 adapter 선택 (예: dell_idrac10 의 PowerEdge R7xx
           model_patterns 가 BMC 명 ↔ 미매치 → 모든 dell adapter disqualify →
           generic fallback). 빈 dict 반환 — 기존 priority-based selection 유지.

    Returns: dict — 채워진 hint 만 포함. 빈 dict 가능.
        {model_hint: str, firmware_hint: str, manager_type: str}

    nosec rule12-r1: Redfish API spec 자체가 OEM namespace (Oem.Hpe / Oem.Hp) 정의 —
    라이브러리에서 vendor 분기 허용 (rule 12 R1 Allowed 영역, _extract_oem_* 와 동일 정신).
    """
    if not isinstance(root, dict):
        return {}
    facts = {}
    if vendor == 'hpe':                                                       # nosec rule12-r1
        product = _safe(root, 'Product')
        if isinstance(product, str) and product.strip():
            facts['model_hint'] = product.strip()
        managers = (_safe(root, 'Oem', 'Hpe', 'Manager')                       # nosec rule12-r1
                    or _safe(root, 'Oem', 'Hp', 'Manager'))                    # nosec rule12-r1
        mgr0 = None
        if isinstance(managers, list) and managers and isinstance(managers[0], dict):
            mgr0 = managers[0]
        elif isinstance(managers, dict):
            mgr0 = managers
        if mgr0 is not None:
            fw_ver = _safe(mgr0, 'ManagerFirmwareVersion')
            if isinstance(fw_ver, str) and fw_ver.strip():
                facts['firmware_hint'] = fw_ver.strip()
            mgr_type = _safe(mgr0, 'ManagerType')
            if isinstance(mgr_type, str) and mgr_type.strip():
                facts['manager_type'] = mgr_type.strip()
    return facts


# ── 섹션별 수집 ───────────────────────────────────────────────────────────────

# nosec rule12-r1 (전체 _extract_oem_*): 외부 계약 (rule 96 R1) 직접 의존.
# Redfish API spec 자체가 vendor namespace 정의 (Oem.Hpe / Oem.Dell / Oem.Lenovo ...)
# — adapter YAML로 위임 불가하므로 라이브러리에서 vendor 분기 허용.

def _extract_oem_hpe(data):                                                   # nosec rule12-r1
    """HPE OEM (iLO 5/6 = Oem.Hpe, iLO 4 이하 = Oem.Hp fallback).

    Underscore-prefixed keys (e.g. `_bios_date`) are hoisted to hardware-level
    by gather_system via _hoist_oem_extras. They populate **existing** envelope
    fields only (no new keys).
    Verified 2026-04-29 against HPE iLO 6 v1.73 (10.50.11.231): Bios.Current.Date
    populated; Manager.Oem.Hpe.Type field does not exist (former mapping was bug).

    CSUS-R17 (2026-06-15 실미러 검수): HPE Compute Scale-up Server 3200 / Superdome Flex 의
    System OEM 은 iLO namespace 가 아니라 #HpeH3Npar — AggregateHealthStatus / Bios.Current /
    PostState / ServerSignature 가 전부 부재라 구 코드는 모든 값이 null 인 iLO 스켈레톤을 날조
    (missing-looks-valid) 하면서 실 OEM(ProductId / ConsoleRouting / DCD / HostOS) 을 silent drop
    했다. OEM @odata.type 로 분기해 CSUS 전용 키를 추출한다. iLO(@odata.type 가 #HpeH3Npar 가
    아님 — #HpeiLO* 또는 마커 부재)는 default 분기 그대로 (Additive — 회귀 안전, rule 92 R2).
    hardware.oem 은 field_dictionary 상 벤더 가변 object("키 구조가 벤더마다 완전히 다름")라
    CSUS 키 추가는 계약 변경 아님 (rule 96 R1-B 위반 아님). raw 충실 — 부재 필드는 null.
    """
    oem = _safe(data, 'Oem', 'Hpe') or _safe(data, 'Oem', 'Hp') or {}         # nosec rule12-r1
    oem_type = _str(_safe(oem, '@odata.type'))
    if oem_type.startswith('#HpeH3Npar'):  # nosec rule12-r1 — Redfish OEM namespace (CSUS/Superdome Flex)
        dcd = _safe(oem, 'DCD') or {}
        host_os = _safe(oem, 'HostOS') or {}
        return {
            'product_id':                   _safe(oem, 'ProductId'),
            'console_routing':              _safe(oem, 'ConsoleRouting'),
            'console_routing_current_boot': _safe(oem, 'ConsoleRoutingCurrentBoot'),
            'dcd_version':                  _safe(dcd, 'DCDVersion'),
            'host_os_name':                 _safe(host_os, 'OsName'),
            'host_os_version':              _safe(host_os, 'OsVersion'),
            'host_os_description':          _safe(host_os, 'OsSysDescription'),
        }
    ahs = _safe(oem, 'AggregateHealthStatus') or {}
    bios_oem = _safe(oem, 'Bios', 'Current') or {}
    return {
        # Hoisted to hardware.bios_date (rule 96 — HPE OEM contract)
        '_bios_date':              _safe(bios_oem, 'Date'),
        'post_state':              _safe(oem, 'PostState'),
        'server_signature':        _safe(oem, 'ServerSignature'),
        'aggregate_server_health': _safe(ahs, 'AggregateServerHealth'),
        'fan_redundancy':          _safe(ahs, 'FanRedundancy'),
        'psu_redundancy':          _safe(ahs, 'PowerSupplyRedundancy'),
        'subsystem_health': {
            'fans':         _safe(ahs, 'Fans', 'Status', 'Health'),
            'memory':       _safe(ahs, 'Memory', 'Status', 'Health'),
            'network':      _safe(ahs, 'Network', 'Status', 'Health'),
            'power':        _safe(ahs, 'PowerSupplies', 'Status', 'Health'),
            'processors':   _safe(ahs, 'Processors', 'Status', 'Health'),
            'storage':      _safe(ahs, 'Storage', 'Status', 'Health'),
            'temperatures': _safe(ahs, 'Temperatures', 'Status', 'Health'),
        },
    }


def _extract_oem_dell(data):                                                  # nosec rule12-r1
    """Dell OEM (Oem.Dell.DellSystem).

    Round 11 raw 검증 (10.100.15.27, iDRAC 7.10.70.00): 정확한 키는
    'EstimatedExhaustTemperatureCelsius'. 일부 구 펌웨어에서 'Cel' 변형 가능성
    있어 Celsius 우선, Cel fallback.
    """
    oem = _safe(data, 'Oem', 'Dell', 'DellSystem') or {}                      # nosec rule12-r1
    bios_date = _safe(oem, 'BIOSReleaseDate')
    return {
        # Hoisted to hardware.bios_date by gather_system (envelope consistency w/ HPE)
        '_bios_date':              bios_date,
        'lifecycle_version':       _safe(oem, 'LifecycleControllerVersion'),
        'bios_release_date':       bios_date,
        'current_rollup_status':   _safe(oem, 'CurrentRollupStatus'),
        'cpu_rollup_status':       _safe(oem, 'CPURollupStatus'),
        'fan_rollup_status':       _safe(oem, 'FanRollupStatus'),
        'battery_rollup_status':   _safe(oem, 'BatteryRollupStatus'),
        'intrusion_rollup_status': _safe(oem, 'IntrusionRollupStatus'),
        'storage_rollup_status':   _safe(oem, 'StorageRollupStatus'),
        'chassis_service_tag':     _safe(oem, 'ChassisServiceTag'),
        'express_service_code':    _safe(oem, 'ExpressServiceCode'),
        # cycle 2026-06-14 (DELL R740 SYS-5): `or` 는 정상 값 0(0°C 배기온)을 falsy 로
        # 흘려 두 번째 키/None 로 오기재. 명시 None 비교로 genuine 0 보존.
        'estimated_exhaust_temp':  (_safe(oem, 'EstimatedExhaustTemperatureCelsius')
                                    if _safe(oem, 'EstimatedExhaustTemperatureCelsius') is not None
                                    else _safe(oem, 'EstimatedExhaustTemperatureCel')),
    }


# ── 벤더별 서버 대표 시리얼 resolver (2026-08-11) ────────────────────────────
# 표준 경로는 ComputerSystem.SerialNumber 이고 그대로 둔다(_ne('SerialNumber'), gather_system).
# 아래 레지스트리에 등록된 vendor 만 main()/run_gather 층에서 대표 시리얼을 덮어쓴다.
# 등록되지 않은 vendor 는 코드 경로 자체를 타지 않아 회귀 위험이 구조적으로 0이다.
#
# 이 판정을 gather_system 이 아니라 main() 층에 둔 이유:
#   대표 시리얼을 못 얻었을 때 "섹션 실패"(=partial)가 아니라 "수집 실패"(=failed)로
#   끝내야 하는데, 섹션 러너(_make_section_runner)는 partial 까지만 만들 수 있다.
#   따라서 확정과 차단을 모두 main() 층이 책임진다.

def _resolve_serial_dell(service_root, refetch=None):                         # nosec rule12-r1
    """Dell 서버 대표 시리얼 = Service Tag (ServiceRoot.Oem.Dell.ServiceTag 단일 정본).

    사용자 결정 (2026-08-11): 다른 시리얼 후보로 폴백하지 않는다. 못 얻으면 수집을 실패시킨다.

    원천 선택 근거 (rule 96 R1-A):
      - Dell iDRAC9 Redfish API Guide "Table 70. Properties for DellServiceRoot" 가
        ServiceTag 를 "System Service Tag" 로 정의한다 (확인 2026-08-11). 후보 4종
        (ServiceTag / DellSystem.NodeID / DellSystem.ChassisServiceTag / SKU) 중
        Dell 이 명시적으로 문서화한 유일한 필드이고, 문구가 chassis 가 아니라 System 스코프다.
      - ChassisServiceTag 는 Dell System Info Profile(DCIM1048) 이 "the service tag for the
        modular enclosure chassis" 로 정의 → 모듈러(블레이드)에서는 enclosure 를 가리킨다.
      - ComputerSystem.SerialNumber 는 보드 제조 시리얼이다. 동일 R760 실측에서 SMBIOS
        Type 2(Baseboard) 문자열 '.GSBPK54.CNIVC0048R0159.' 의 뒷부분과 일치하고
        Type 1(System)/Type 3(Chassis) 에는 나타나지 않는다
        (tests/evidence/2026-04-29-deep-verify/linux/ubuntu-r760-6-baremetal/dmi_*.txt).

    refetch: callable() -> service_root dict | None
        _fetch_service_root 는 무인증 GET 이 200 이면 인증 GET 을 하지 않는다. 무인증 응답이
        200 이면서 OEM 블록만 빠지는 펌웨어면 Service Tag 를 '없음' 으로 오판하게 되므로,
        1차 조회에서 못 찾은 경우에 한해 인증 ServiceRoot 를 1회 재조회한다.
        (같은 Guide 가 /redfish/v1 의 DellServiceRoot 를 "GET requires Login" 으로 적는다.)

    Returns: (service_tag, None) | (None, 실패사유)
    """
    # 이 프로젝트가 이미 invalid 로 정의한 식별자 값의 합집합 — 새로 정의하지 않는다.
    #   os-gather/tasks/linux/gather_system.yml:209    (serial 센티널 5종)
    #   os-gather/tasks/windows/gather_hardware.yml:53 (BIOS serial 센티널 8종)
    # 원본 PowerShell 목록이 대소문자 무시라 그 의미를 보존해 upper() 비교한다.
    # 빈 문자열/공백은 _strip_or_none 이 이미 None 으로 정규화하므로 목록에 넣지 않는다.
    invalid_values = ('NA', 'N/A', 'NONE', 'NOT SPECIFIED', 'TO BE FILLED BY O.E.M.',
                      'SYSTEM SERIAL NUMBER', '0', '00000000')

    def _pick(root):
        tag = _strip_or_none(_safe(root, 'Oem', 'Dell', 'ServiceTag'))         # nosec rule12-r1
        if tag is None:
            return None, ('서버 대표 시리얼을 확인하지 못했습니다 — '              # nosec rule12-r1
                          'ServiceRoot.Oem.Dell.ServiceTag 없음')              # nosec rule12-r1
        if not isinstance(tag, str):
            return None, ('서버 대표 시리얼을 확인하지 못했습니다 — '              # nosec rule12-r1
                          'ServiceRoot.Oem.Dell.ServiceTag 가 문자열이 아님')    # nosec rule12-r1
        if tag.strip().upper() in invalid_values:
            return None, ('서버 대표 시리얼을 확인하지 못했습니다 — '              # nosec rule12-r1
                          'ServiceRoot.Oem.Dell.ServiceTag 가 무효값(%r)' % tag)  # nosec rule12-r1
        return tag, None

    tag, err = _pick(service_root)
    if err is not None and refetch is not None:
        tag, err = _pick(refetch())
    return tag, err


# vendor → 대표 시리얼 resolver. 미등록 vendor 는 표준 SerialNumber 경로를 그대로 쓴다.
_SERIAL_RESOLVERS = {                                                         # nosec rule12-r1
    'dell': _resolve_serial_dell,                                             # nosec rule12-r1
}


def _extract_oem_lenovo(data, chassis_data=None):                             # nosec rule12-r1
    """Lenovo OEM (Oem.Lenovo).

    실측 (Lenovo XCC SR650 V2, 2026-04-28): ProductName은 System.Oem.Lenovo
    가 아닌 Chassis.Oem.Lenovo 에 존재. chassis_data 가 주어지면 Chassis 우선,
    없으면 System.Model 로 fallback.

    2026-04-29 fix B61: 추가 OEM 키 추출 — System.Oem.Lenovo의 운영 메타.
    """
    sys_oem = _safe(data, 'Oem', 'Lenovo') or {}                              # nosec rule12-r1
    cha_oem = _safe(chassis_data or {}, 'Oem', 'Lenovo') or {} if chassis_data else {}  # nosec rule12-r1
    product_name = (
        _safe(sys_oem, 'ProductName')
        or _safe(cha_oem, 'ProductName')
        or _safe(data, 'Model')
    )
    return {
        'product_name':         product_name,
        'system_status':        _safe(sys_oem, 'SystemStatus'),
        'fru_serial':           _safe(cha_oem, 'FruSerialNumber'),
        'machine_type':         _safe(cha_oem, 'MachineType'),
        'machine_level':        _safe(cha_oem, 'MachineLevel'),
        'product_id':           _safe(cha_oem, 'ProductId'),
        'system_id':            _safe(cha_oem, 'SystemId'),
        'health_summary':       _safe(sys_oem, 'HealthSummary'),
        'led_indicator':        _safe(cha_oem, 'LEDIndicators') or _safe(cha_oem, 'IndicatorLED'),
    }


def _extract_oem_supermicro(data):                                            # nosec rule12-r1
    """Supermicro OEM (Oem.Supermicro)."""
    oem = _safe(data, 'Oem', 'Supermicro') or {}                              # nosec rule12-r1
    return {
        'board_id':   _safe(oem, 'BoardID'),
        'node_id':    _safe(oem, 'NodeID'),
    }


def _extract_oem_cisco(data, chassis_data=None):                              # nosec rule12-r1
    """Cisco OEM (Oem.Cisco).

    2026-04-29 fix B61: Cisco CIMC C220 M4 (Round 11): ServiceRoot.Oem 빈 dict
    이지만 System/Chassis Oem.Cisco는 BoardSerial / Locator 등 일부 노출.
    """
    sys_oem = _safe(data, 'Oem', 'Cisco') or {}                               # nosec rule12-r1
    cha_oem = _safe(chassis_data or {}, 'Oem', 'Cisco') or {} if chassis_data else {}  # nosec rule12-r1
    return {
        'board_serial':       _safe(sys_oem, 'BoardSerialNumber') or _safe(cha_oem, 'BoardSerialNumber'),
        'platform_name':      _safe(sys_oem, 'PlatformName') or _safe(cha_oem, 'PlatformName'),
        'asset_tag':          _safe(sys_oem, 'AssetTag') or _safe(cha_oem, 'AssetTag'),
        'description':        _safe(sys_oem, 'Description') or _safe(cha_oem, 'Description'),
        'locator_led':        _safe(sys_oem, 'LocatorLED') or _safe(cha_oem, 'LocatorLED'),
    }


def _hoist_oem_extras(oem_dict, target):                                      # nosec rule12-r1
    """Move underscore-prefixed keys from OEM extractor result into target dict.

    Vendor extractors emit `_field` keys to populate **existing** envelope fields
    at hardware level (e.g. `_bios_date` -> hardware.bios_date). Only keys
    already present in `target` are filled — never adds new envelope keys.
    Unknown `_*` keys are silently dropped.
    Returns the cleaned OEM dict (without `_*` keys).
    """
    if not isinstance(oem_dict, dict):
        return oem_dict
    cleaned = {}
    for k, v in oem_dict.items():
        if isinstance(k, str) and k.startswith('_'):
            field = k[1:]
            if field in target and v is not None:
                # 2026-04-29 fix B16: bios_date / bios_release_date를 ISO 8601로 정규화.
                # Dell '09/10/2024' (MM/DD/YYYY) / HPE '03/01/2024' / 등 → 'YYYY-MM-DD'.
                if field in ('bios_date', 'bios_release_date'):
                    target[field] = _normalize_bios_date(v)
                else:
                    target[field] = v
            # else: silently drop — never add new envelope keys
        else:
            cleaned[k] = v
    return cleaned


# cycle 2026-05-07 M-I5: RoleId enum 정규화 매트릭스 (9 vendor).
# vendor 별 default role enum 변형을 5 표준 카테고리로 매핑.
# 표준 카테고리: 'administrator' / 'operator' / 'readonly' / 'none' / 'custom'
# rule 12 R1 Allowed — Redfish AccountService spec enum 직접 의존.
# rule 92 R2 — Additive helper (호출자가 옵션 사용. envelope 영향 0).
_ROLE_ID_NORMALIZATION_MATRIX = {                                             # nosec rule12-r1
    # Dell iDRAC 표준
    'administrator': 'administrator',
    'admin':         'administrator',                                         # nosec rule12-r1 — Cisco CIMC
    'supervisor':    'administrator',                                         # nosec rule12-r1 — Lenovo XCC
    'operator':      'operator',
    'user':          'operator',                                              # nosec rule12-r1 — Supermicro
    'readonly':      'readonly',
    'read-only':     'readonly',
    'read_only':     'readonly',
    'commonuser':    'readonly',                                              # nosec rule12-r1 — Huawei iBMC
    'callback':      'readonly',                                              # nosec rule12-r1 — Supermicro read-only role
    'none':          'none',
    'virtualmedia':  'custom',                                                # nosec rule12-r1 — HPE iLO
}


def _normalize_role_id(raw_role):                                             # nosec rule12-r1
    """cycle 2026-05-07 M-I5: RoleId enum 정규화 (9 vendor → 5 표준 enum).

    Args:
        raw_role: BMC 응답의 RoleId raw 문자열 (Administrator / admin / Supervisor / ...)

    Returns:
        normalized: 'administrator' / 'operator' / 'readonly' / 'none' / 'custom' / raw
                    (매트릭스에 없는 vendor-specific role 은 lowercase 그대로 보존)

    rule 92 R2 — Additive (호출자가 옵션 사용. envelope 영향 0).
    """
    if raw_role is None:
        return None
    s = str(raw_role).strip().lower()
    if not s:
        return None
    return _ROLE_ID_NORMALIZATION_MATRIX.get(s, s)


def _normalize_dimm_label(raw_label):                                         # nosec rule12-r1
    """cycle 2026-05-07 M-I5: DIMM ServiceLabel vendor 별 정규화.

    vendor 별 라벨 변형을 공통 형식으로 통일:
      - Dell:       "DIMM_A1"        → "DIMM A1"
      - HPE:        "P1-DIMM-A1"     → "P1 DIMM A1"  (CPU prefix 보존)
      - Lenovo:     "DIMM 1"         → "DIMM 1"
      - Supermicro: "CPU0_DIMM_A1"   → "CPU0 DIMM A1"

    Args:
        raw_label: 원본 ServiceLabel (예: "DIMM_A1")

    Returns: normalized label (공백 구분) — 정보 손실 없음

    rule 92 R2 — Additive (호출자가 옵션 사용. raw label 도 함께 보존 권장).
    """
    if raw_label is None:
        return None
    s = str(raw_label).strip()
    if not s:
        return None
    # underscore / hyphen → space 통일, 다중 공백 압축
    normalized = s.replace('_', ' ').replace('-', ' ')
    # 다중 공백 압축
    while '  ' in normalized:
        normalized = normalized.replace('  ', ' ')
    return normalized


def _normalize_link_status(value):
    """Normalize Redfish LinkStatus to standard enum.

    Vendor variations seen:
      - Dell iDRAC: 'LinkUp' / 'LinkDown' (raw spec)
      - HPE iLO:    'NoLink' / null
      - Cisco CIMC: 'Connected' / 'Disconnected' / null
      - Lenovo XCC: 'LinkUp' / 'LinkDown'

    DMTF DSP8010 2026.1 대조 2026-06-08: Port.LinkStatus enum 정본은
      ['LinkUp', 'Starting', 'Training', 'LinkDown', 'NoLink'] (Port.v1_19_0).
      'Starting'/'Training' = 링크 협상 중(비작동) 전이 상태 → 기존 비작동
      매핑(disabled/inactive/offline)과 동일하게 'down' 으로 정규화.

    Standard enum:
      'up'      — link active
      'down'    — link inactive (NoLink, LinkDown, Disconnected, Starting, Training)
      'unknown' — null/unknown response
    """
    if value is None:
        return 'unknown'
    s = str(value).strip().lower()
    if not s or s in ('none', 'unknown', 'null'):
        return 'unknown'
    if s in ('linkup', 'up', 'connected', 'enabled', 'active'):
        return 'up'
    if s in ('linkdown', 'down', 'nolink', 'disconnected', 'disabled',
             'inactive', 'offline', 'starting', 'training'):
        return 'down'
    return s  # unknown vendor-specific value — preserve raw


def _valid_iso_date(s):
    """'YYYY-MM-DD' 문자열이 실제 유효한 달력 날짜인지 (월 1-12 / 일 1-31 / 윤년 반영).

    Round 15: _normalize_bios_date 가 '2024-13-32' / '2024-00-00' 같은 invalid ISO 를
    생성하지 않도록 최종 검증. 잘못된 날짜면 raw 원문 보존 (호출자 ISO 파싱 실패 방지).
    """
    import datetime as _dt
    try:
        _dt.date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
        return True
    except (ValueError, TypeError, IndexError):
        return False


def _normalize_bios_date(value):
    """Normalize BIOS date to ISO 8601 (YYYY-MM-DD) where possible.

    Handles common formats:
      - 'MM/DD/YYYY'        (Dell iDRAC, HPE iLO inline)
      - 'YYYY-MM-DDT...'    (ESXi already ISO)
      - '03/01/2024'         (HPE — but ambiguous; assume MM/DD if year > 12)
      - None/'N/A' -> None
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.upper() in ('N/A', 'NONE', 'NOT SPECIFIED'):
        return None
    # Already ISO date prefix (YYYY-MM-DD)
    import re as _re
    if _re.match(r'^\d{4}-\d{2}-\d{2}', s):
        cand = s[:10]
        return cand if _valid_iso_date(cand) else s  # Round 15: invalid (예: 2024-13-32T..) → raw 보존
    # MM/DD/YYYY
    m = _re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', s)
    if m:
        mm, dd, yyyy = m.group(1), m.group(2), m.group(3)
        # Heuristic: if first part > 12, it's DD/MM/YYYY (European)
        try:
            if int(mm) > 12:
                mm, dd = dd, mm
        except ValueError:
            pass
        iso = f"{yyyy}-{int(mm):02d}-{int(dd):02d}"
        return iso if _valid_iso_date(iso) else s  # Round 15: 32/13 swap 후도 invalid → raw 보존
    # DD-MM-YYYY or YYYY-MM-DD plain (no T)
    m = _re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', s)
    if m:
        iso = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return iso if _valid_iso_date(iso) else s  # Round 15: 월 0/13 / 일 0/32 invalid → raw 보존
    # Couldn't parse — return raw to preserve data
    return s


# 주의 (2026-04-28 / NEXT_ACTIONS T3-03):
# cisco ServiceRoot.Oem 은 Round 11 실측 빈 dict (adapter cisco_cimc.yml strategy=standard_only).
# 단, 2026-04-29 fix B61 이후 System/Chassis Oem.Cisco 에서 일부 운영 메타가 나와
# _extract_oem_cisco 를 아래 매핑에 추가함 (ServiceRoot 가 아닌 System/Chassis 기준).
_OEM_EXTRACTORS = {                                                           # nosec rule12-r1
    'hpe':        _extract_oem_hpe,                                           # nosec rule12-r1
    'dell':       _extract_oem_dell,                                          # nosec rule12-r1
    'lenovo':     _extract_oem_lenovo,                                        # nosec rule12-r1
    'supermicro': _extract_oem_supermicro,                                    # nosec rule12-r1
    # 2026-04-29 fix B61: Cisco CIMC OEM 추출 추가 (이전 ServiceRoot.Oem 빈 dict이라 skip했지만
    # System/Chassis Oem.Cisco는 일부 운영 메타 노출).
    'cisco':      _extract_oem_cisco,                                         # nosec rule12-r1
}


# cycle 2026-05-07 M-I3: bmc / firmware OEM namespace unified extractor.
# 9 vendor 의 OEM namespace 변형 (Oem.Hp vs Oem.Hpe / Oem.Inspur vs Oem.Inspur_System
# / Oem.ts_fujitsu vs Oem.Fujitsu / Oem.Quanta_Computer_Inc vs Oem.QCT) 한 번에 해석.
# rule 12 R1 Allowed — Redfish API spec OEM namespace 직접 의존 (Allowed 영역).
# rule 92 R2 Additive — 본 helper 는 raw dict 만 반환. envelope 영향 0.
_OEM_NAMESPACE_FALLBACK_CHAIN = (                                             # nosec rule12-r1
    ('dell',       ('Dell',)),                                                # nosec rule12-r1
    ('hpe',        ('Hpe', 'Hp')),                                            # nosec rule12-r1 — iLO4 legacy
    ('lenovo',     ('Lenovo',)),                                              # nosec rule12-r1
    ('cisco',      ('Cisco', 'Cisco_RackUnit')),                              # nosec rule12-r1 — UCS variant
    ('supermicro', ('Supermicro',)),                                          # nosec rule12-r1
    ('huawei',     ('Huawei',)),                                              # nosec rule12-r1
    ('inspur',     ('Inspur', 'Inspur_System')),                              # nosec rule12-r1 — older firmware variant
    ('fujitsu',    ('ts_fujitsu', 'Fujitsu')),                                # nosec rule12-r1 — iRMC alias
    ('quanta',     ('Quanta_Computer_Inc', 'QCT')),                           # nosec rule12-r1
)


def _extract_oem_unified(data, expected_vendor=None):                         # nosec rule12-r1
    """cycle 2026-05-07 M-I3: 9 vendor OEM namespace 통합 추출 helper.

    Redfish 응답의 `Oem.<namespace>` 영역을 vendor 별 alias chain (Oem.Hp / Oem.Hpe,
    Oem.ts_fujitsu / Oem.Fujitsu 등) 순서대로 탐색해 첫 매치 반환.

    Args:
        data: Redfish 응답 dict (Manager / System / Chassis 어느 것도 OK)
        expected_vendor: 정규화된 vendor 이름 (dell/hpe/lenovo/...). 주어지면
                         해당 vendor namespace chain 만 시도. None 이면 전체 9
                         vendor chain 모두 순회 (첫 매치).

    Returns:
        (oem_dict, matched_vendor, matched_namespace)
        - oem_dict: 매치한 OEM 영역 dict ({} 가능)
        - matched_vendor: 'dell' / 'hpe' / ... 또는 None
        - matched_namespace: 'Dell' / 'Hp' / 'ts_fujitsu' / ... 또는 None

    rule 12 R1 Allowed — Redfish API spec OEM namespace 직접 의존.
    rule 92 R2 — Additive helper. 호출자가 raw dict 사용. envelope shape 변경 0.
    """
    if not isinstance(data, dict):
        return {}, None, None
    oem_root = data.get('Oem')
    if not isinstance(oem_root, dict) or not oem_root:
        return {}, None, None
    chain = _OEM_NAMESPACE_FALLBACK_CHAIN
    if expected_vendor:
        chain = tuple((v, ns) for v, ns in chain if v == expected_vendor)
    for vendor_key, namespaces in chain:
        for ns in namespaces:
            value = oem_root.get(ns)
            if isinstance(value, dict) and value:
                return value, vendor_key, ns
    return {}, None, None


def gather_system(bmc_ip, system_uri, vendor, username, password, timeout, verify_ssl,
                  chassis_uri=None, product_hint=None):
    """system 섹션 수집 (Redfish endpoints).

    호출 endpoint:
      - GET {system_uri}                       (예: /redfish/v1/Systems/1)
      - GET {chassis_uri} (선택, OEM 데이터 추출용 — Lenovo ProductName 등)

    Returns: (data_dict, errors_list)
    """
    st, data, err = _get(bmc_ip, _p(system_uri), username, password, timeout, verify_ssl)
    errors = []
    if err or st != 200:
        errors.append(_err('system', f'System 수집 실패: {err or st}'))
        return {}, errors

    # Lenovo 등 일부 벤더는 ProductName 이 Chassis.Oem 에 위치 (System.Oem 에는 없음).
    # OEM extractor 가 chassis 데이터를 활용할 수 있도록 1회 fetch.
    chassis_data = None
    if chassis_uri:
        cst, cdata, _cerr = _get(bmc_ip, _p(chassis_uri), username, password, timeout, verify_ssl)
        if not _cerr and cst == 200:
            chassis_data = cdata

    # HostName: HPE는 빈 문자열("") 반환 가능 → None으로 변환
    hostname = _safe(data, 'HostName')
    if isinstance(hostname, str) and not hostname.strip():
        hostname = None

    # IndicatorLED fallback: HPE Gen11은 IndicatorLED 미제공, LocationIndicatorActive 사용
    led_state = _safe(data, 'IndicatorLED')
    if led_state is None:
        loc_active = _safe(data, 'LocationIndicatorActive')
        if loc_active is not None:
            led_state = 'Blinking' if loc_active else 'Off'

    # MemorySummary.Status: HPE는 Health 미제공, HealthRollup만 제공
    mem_health = _safe(data, 'MemorySummary', 'Status', 'Health')
    if mem_health is None:
        mem_health = _safe(data, 'MemorySummary', 'Status', 'HealthRollup')

    # cycle-016 Phase N: System 의 raw API 풍부 필드 추가 (asset/lastreset/tpm)
    tpm_modules = _safe(data, 'TrustedModules') or []
    tpm_summary = None
    if isinstance(tpm_modules, list) and tpm_modules:
        first_tpm = tpm_modules[0] if isinstance(tpm_modules[0], dict) else {}
        tpm_summary = {
            'interface_type':   _safe(first_tpm, 'InterfaceType'),
            'firmware_version': _safe(first_tpm, 'FirmwareVersion'),
            'state':            _safe(first_tpm, 'Status', 'State'),
        }

    # 빈 문자열 → None 정규화 helper. HPE: AssetTag/PartNumber 등이 "" 반환 케이스.
    # 호출자가 None 과 "" 두 가지 상태를 동일 처리하도록 강제하지 않기 위함.
    # 2026-04-30 추가: Cisco 등 일부 BMC가 trailing whitespace 포함하는 PartNumber 반환 →
    # cross-vendor consistency 위해 strip().
    def _ne(*keys):
        # _strip_or_none + _safe 조합 (중복 stripping 로직 3곳 → 1곳 dedup, cycle 2026-05-29)
        return _strip_or_none(_safe(data, *keys))

    result = {
        'manufacturer':   _ne('Manufacturer'),
        'model':          _ne('Model'),
        'serial':         _ne('SerialNumber'),
        'sku':            _ne('SKU'),
        'uuid':           _ne('UUID'),
        'hostname':       hostname,
        'power_state':    _safe(data, 'PowerState'),
        'health':         _safe(data, 'Status', 'Health'),
        'state':          _safe(data, 'Status', 'State'),
        'led_state':      led_state,
        'bios_version':   _ne('BiosVersion'),
        # bios_date: 표준 Redfish 에는 키가 없음 — 벤더 OEM extractor 의 `_bios_date`
        # underscore-prefix 키를 _hoist_oem_extras 가 여기로 끌어올림.
        'bios_date':      None,
        'asset_tag':      _ne('AssetTag'),
        'system_type':    _safe(data, 'SystemType'),
        'part_number':    _ne('PartNumber'),
        'last_reset_time': _safe(data, 'LastResetTime'),
        'boot_progress':  _safe(data, 'BootProgress', 'LastState'),
        'tpm':            tpm_summary,
        'cpu_summary': {
            'count':  _safe_int(_safe(data, 'ProcessorSummary', 'Count')),  # Round 3 #7: int 통일
            'core_count':              _safe_int(_safe(data, 'ProcessorSummary', 'CoreCount')),
            'logical_processor_count': _safe_int(_safe(data, 'ProcessorSummary', 'LogicalProcessorCount')),
            'model':  _safe(data, 'ProcessorSummary', 'Model'),
            # HPE 등 일부 벤더는 ProcessorSummary.Status 에 Health 없이 HealthRollup 만 제공
            # (실측 HPE DL380 Gen12 iLO7: ProcessorSummary.Status={'HealthRollup':'OK'} — Health 부재).
            # memory_summary(line 1522-1524) / drives(2017) / volumes(2105) 와 동일한 HealthRollup fallback
            # 으로 health=null 유실 차단. raw 에 둘 다 없으면 None 유지(faithful).
            'health': (_safe(data, 'ProcessorSummary', 'Status', 'Health')
                       or _safe(data, 'ProcessorSummary', 'Status', 'HealthRollup')),
        },
        'memory_summary': {
            'total_gib': _safe_int(_safe(data, 'MemorySummary', 'TotalSystemMemoryGiB')),  # Round 4 #7: int 통일
            'health':    mem_health,
        },
        'oem': {},
    }

    # 벤더별 OEM 확장 dispatch (helper 함수에 위임)
    extractor = _OEM_EXTRACTORS.get(vendor)                                   # nosec rule12-r1
    if extractor is not None:
        # _extract_oem_lenovo / _extract_oem_cisco 는 chassis_data 인자 추가 (rule 96 R3 외부 계약).
        if vendor in ('lenovo', 'cisco'):                                     # nosec rule12-r1
            raw_oem = extractor(data, chassis_data=chassis_data)              # nosec rule12-r1
        else:
            raw_oem = extractor(data)
        # `_*` prefix 키 (예: `_bios_date`) 를 result hardware-level 로 끌어올린 뒤
        # OEM dict 에서는 제거. 기존 envelope 키만 채움 — 새 키 추가 없음.
        result['oem'] = _hoist_oem_extras(raw_oem, result)

    # A1 (2026-06-04, HP CSUS 3200 사이트 사고): Chassis 폴백 — System.Manufacturer/Model
    # 부재(None) 시 이미 fetch 한 chassis_data(상단)에서 보충. Additive only (rule 92 R2):
    #   - result 값이 None 일 때만 발동 (정상 13 vendor 는 System.Manufacturer/Model 보유 → 미발동).
    #   - _strip_or_none 으로 '' → None 정규화 유지 (파이프라인 불변식: 빈 문자열 금지).
    #   - chassis 값이 strip 후 truthy 일 때만 대입 (None→None / ''→None 무의미 대입 방지).
    # 근거: HPE Scale-up (CSUS 3200 / Superdome Flex) RMC 는 Partition0 System.Manufacturer/
    # Model 이 비고 Chassis 에만 존재 (DMTF ComputerSystem Manufacturer/Model optional+nullable).
    #
    # A1b (2026-06-04): System.Model 부재 시 ServiceRoot.Product(product_hint) 우선 fallback.
    # 근거: check_redfish (실 CSUS 3200 지원 도구) cr_module/system_chassis.py 가 동일 —
    #   `if model is None: model = connection.root.get("Product")` (rule 96 R1-A web 검증).
    # 사용자 CSUS 실측: ServiceRoot.Product="Compute Scale-up Server 3200" (깨끗한 모델명 —
    # Chassis.Model 의 "... Base" 접미사보다 정확). 정상 vendor 는 System.Model 보유 → 미발동
    # (ServiceRoot.Product 가 BMC 명인 Dell/Lenovo 도 System.Model 있어 fallback 안 탐).
    if result['model'] is None and product_hint:
        _ph = _strip_or_none(product_hint)
        if _ph is not None and isinstance(_ph, str):  # Round 14 #1: 비-str Product → model 타입 일관
            result['model'] = _ph
    if isinstance(chassis_data, dict):
        if result['manufacturer'] is None:
            _cm = _strip_or_none(_safe(chassis_data, 'Manufacturer'))
            if _cm is not None:
                result['manufacturer'] = _cm
        if result['model'] is None:
            _cmod = _strip_or_none(_safe(chassis_data, 'Model'))
            if _cmod is not None:
                result['model'] = _cmod

    # 주요 필드 누락은 경고 수준 — 수집 자체는 성공으로 처리.
    # errors에 추가하지 않아 _run()에서 failed로 분류되지 않음.

    return result, errors


def gather_bmc(bmc_ip, manager_uri, vendor, username, password, timeout, verify_ssl,
               manager_layout=None, is_first=True, manager_id=None):
    """bmc 섹션 수집 (Redfish endpoints).

    호출 endpoint:
      - GET {manager_uri}                            (예: /redfish/v1/Managers/1)
      - GET {manager_uri}/EthernetInterfaces (선택, BMC IP 추출)

    cycle 2026-05-12 (ADR-2026-05-12): `manager_layout` 옵션 인자 추가 (Additive).
      - None (기본값) — 기존 동작 100% 보존. `bmc.name = bmc_names[vendor]` 통일.
      - 'rmc_primary' / 'rmc_primary_ilo_secondary' — `_classify_rmc_label` 우선 적용.
        Manager URI/ID substring (`rmc` / `pdhc` / `ilo`) 매칭 시 'RMC' / 'PDHC' / 'iLO'.

    Returns: (data_dict, errors_list)
    """
    if not manager_uri:
        return {}, [_err('bmc', 'manager_uri 없음')]

    st, data, err = _get(bmc_ip, _p(manager_uri), username, password, timeout, verify_ssl)
    errors = []
    if err or st != 200:
        errors.append(_err('bmc', f'BMC 수집 실패: {err or st}'))
        return {}, errors

    # nosec rule12-r1: vendor → BMC 표시명 매핑 (외부 spec 기반 표준 이름)
    bmc_names = {'dell': 'iDRAC', 'hpe': 'iLO', 'lenovo': 'XCC', 'supermicro': 'BMC',
                 'cisco': 'CIMC',                                              # nosec rule12-r1
                 'huawei': 'iBMC', 'inspur': 'ISBMC', 'fujitsu': 'iRMC',       # nosec rule12-r1
                 'quanta': 'BMC'}                                              # nosec rule12-r1
    # cycle 2026-05-12 (ADR-2026-05-12): RMC primary 시스템 (HPE CSUS 3200 / Superdome Flex)
    # 라벨 분기 — manager_layout 정의 시 _classify_rmc_label 우선. None 일 때 기존 동작.
    # cycle 2026-06-09 (review): name(label) 과 role 가 동일 id 로 분류돼 모순 불가능하도록,
    # multi 경로는 manager_id(=URI segment m['id']) 를 명시 전달 — _classify_manager_role 와
    # 동일 source. 단일 노드(manager_id=None)는 응답 body Id 사용 (기존 동작 보존).
    _mid = manager_id if manager_id is not None else _safe(data, 'Id')
    rmc_label = _classify_rmc_label(manager_uri, _mid, manager_layout, is_first)
    # cycle-016 Phase M/N: BMC 운영 정보 강화 — datetime / dns / mac / uuid / last_reset / timezone / power_state
    result = {
        'name':             rmc_label or bmc_names.get(vendor, 'BMC'),
        'firmware_version': _safe(data, 'FirmwareVersion'),
        'model':            _safe(data, 'Model'),
        'manager_type':     _safe(data, 'ManagerType'),
        'health':           _safe(data, 'Status', 'Health'),
        'state':            _safe(data, 'Status', 'State'),
        'power_state':      _safe(data, 'PowerState'),
        'uuid':             _safe(data, 'UUID'),
        # 2026-06-16 감사 G4: Manager 식별 메타 (Additive). CSUS RMC raw 는 SerialNumber=
        # SGHD3TLNDD / PartNumber=R9N70A / Manufacturer=HPE 보유했으나 미수집이었다. Manager 가
        # 해당 필드 미제공인 vendor(대다수 iDRAC/iLO/XCC)는 None — shape 통일, 회귀 안전.
        'serial':           _strip_or_none(_safe(data, 'SerialNumber')),
        'part_number':      _strip_or_none(_safe(data, 'PartNumber')),
        'manufacturer':     _strip_or_none(_safe(data, 'Manufacturer')),
        'last_reset_time':  _safe(data, 'LastResetTime'),
        'timezone':         _safe(data, 'TimeZoneName'),
        'ip':               None,
        'mac_address':      None,
        'dns_name':         None,
        # 2026-06-16: BMC 관리 호스트명 (Manager.NetworkProtocol.HostName/FQDN). System.HostName
        # 부재 시 hostname fallback 소스. DMTF ManagerNetworkProtocol 표준이라 vendor-agnostic.
        # 단 vendor/세대별로 populate 여부 다름 (Cisco CIMC 등은 null) → graceful (None 유지).
        'network_hostname': None,
        'datetime':         _safe(data, 'DateTime'),
        'datetime_offset':  _safe(data, 'DateTimeLocalOffset'),
        'oem': {},
    }

    # Manager EthernetInterfaces에서 BMC IP / MAC / FQDN + NameServers / Gateway 추출
    # 2026-04-29 cisco-critical-review: BMC NIC 의 NameServers / IPv4Addresses[*].Gateway
    # 를 envelope 비노출 임시 키 (_network_meta) 로 캐시한다. normalize_standard.yml 이
    # dns_servers / default_gateways 정규화에 사용 후 _network_meta 키 자체는 envelope
    # 에서 제거한다 (rule 13 R5 / 22 / envelope 키 추가 금지).
    bmc_name_servers = []
    bmc_static_name_servers = []
    bmc_gateways = []
    nic_link = _safe(data, 'EthernetInterfaces', '@odata.id')
    if nic_link:
        nst, ncoll, nerr = _get(bmc_ip, _p(nic_link), username, password, timeout, verify_ssl)
        if not nerr and nst == 200:
            for nm in _dicts(_safe(ncoll, 'Members')):  # Round 5: 비-list/dict 방어
                nuri = _safe(nm, '@odata.id')
                if not nuri:
                    continue
                nst2, ndata, nerr2 = _get(bmc_ip, _p(nuri), username, password, timeout, verify_ssl)
                if nerr2 or nst2 != 200:
                    continue
                # IPv4 — 첫 매칭만 result['ip']/['mac_address']/['dns_name'] 에 사용,
                # 모든 NIC 의 Gateway 는 누적 (멀티 NIC: dedicated + shared 등 대비)
                nic_first_ip = None
                for addr in _dicts(_safe(ndata, 'IPv4Addresses')):  # Round 3 #4: 비-list/비-dict 방어
                    ip = _safe(addr, 'Address')
                    if ip and isinstance(ip, str) and ip not in ('0.0.0.0', ''):  # Round 7 #3: 비-str Address 방어
                        if nic_first_ip is None:
                            nic_first_ip = ip
                        gw = _safe(addr, 'Gateway')
                        if gw and isinstance(gw, str) and gw not in ('0.0.0.0', '') and gw not in bmc_gateways:  # Round 8 #2: 비-str Gateway
                            bmc_gateways.append(gw)
                # NameServers / StaticNameServers — 모든 NIC 누적 (중복 제거 + placeholder skip).
                # 실측 (Lenovo XCC SR650 V2): NameServers=["","","","::","::","::"] 처럼
                # 미설정 슬롯이 빈 문자열 / "::" / "0.0.0.0" 같은 placeholder 로 채워지므로 필터.
                _ns_placeholders = ('', '0.0.0.0', '::', '::0', '::1')
                for ns in _as_list(_safe(ndata, 'NameServers')):  # Round 3 #15: 비-list 방어
                    if isinstance(ns, str) and ns and ns not in _ns_placeholders and ns not in bmc_name_servers:  # Round 9 #1: 비-str element
                        bmc_name_servers.append(ns)
                for ns in _as_list(_safe(ndata, 'StaticNameServers')):
                    if isinstance(ns, str) and ns and ns not in _ns_placeholders and ns not in bmc_static_name_servers:  # Round 9 #1
                        bmc_static_name_servers.append(ns)
                # MAC + FQDN — IP 가 있는 첫 NIC 에서 추출 (기존 동작 유지)
                if nic_first_ip:
                    if not result['ip']:
                        result['ip'] = nic_first_ip
                    if not result['mac_address']:
                        _mac = _safe(ndata, 'MACAddress') or _safe(ndata, 'PermanentMACAddress')
                        # XC-4 (2026-06-15): MAC 소문자 정규화 — _normalize_wwn/ports[].associated_address
                        # (NET-2-1) 와 동일 canonical case. HPE iLO 는 Manager NIC MAC 을 대문자로
                        # 노출(7C:A6:..) 하나 System/Chassis NIC 은 소문자 → bmc.mac_address 만 case 이탈.
                        # raw 가 colon-grouped hex 라 .lower() 무손실 (cross-channel MAC dedup/매칭 일관).
                        result['mac_address'] = _mac.lower() if isinstance(_mac, str) else None  # Round 14 #2: 비-str MAC 방어
                    if not result['dns_name']:
                        result['dns_name'] = _safe(ndata, 'FQDN') or _safe(ndata, 'HostName')

    # envelope 비노출 — normalize_standard.yml 의 _rf_d_bmc_clean 단계에서 제거된다.
    result['_network_meta'] = {
        'name_servers':        bmc_name_servers,
        'static_name_servers': bmc_static_name_servers,
        'ipv4_gateways':       bmc_gateways,
    }

    # 2026-06-16: Manager.NetworkProtocol.HostName/FQDN — BMC 관리 호스트명 수집.
    # System.HostName 부재 시 hostname fallback 소스 (build_output 우선순위 chain).
    # DMTF ManagerNetworkProtocol 표준(HostName/FQDN optional) — vendor-agnostic.
    # 실측: Dell iDRAC9 / HPE iLO7·RMC / Lenovo XCC3 = populate. Cisco CIMC = null → graceful.
    np_link = _safe(data, 'NetworkProtocol', '@odata.id')
    if np_link:
        npst, npdata, _nperr = _get(bmc_ip, _p(np_link), username, password, timeout, verify_ssl)
        if not _nperr and npst == 200 and isinstance(npdata, dict):
            # FQDN 우선(도메인 포함 더 완전), 없으면 HostName. 빈 문자열 → None 정규화.
            result['network_hostname'] = (_strip_or_none(_safe(npdata, 'FQDN'))
                                          or _strip_or_none(_safe(npdata, 'HostName')))

    # 벤더별 BMC OEM 확장 (Redfish API spec)
    if vendor == 'hpe':                                                       # nosec rule12-r1
        oem = _safe(data, 'Oem', 'Hpe') or _safe(data, 'Oem', 'Hp') or {}     # nosec rule12-r1
        # 2026-04-29 raw 검증 (10.50.11.231 iLO 6 v1.73): Manager.Oem.Hpe 에 `Type`
        # 필드 부재 — 이전 매핑은 항상 null. 의미 있는 값은 Firmware.Current.VersionString.
        # ilo_version = iLO OEM 펌웨어 버전 (Oem.Hpe.Firmware.Current.VersionString).
        # CSUS-R4 (2026-06-15 실미러 검수): 구 `or _safe(data,'Model')` fallback 제거 —
        # CSUS RMC(RackManager)는 Oem.Hpe.Firmware 가 없어 Model("Compute Scale-up Server
        # 3200, 4S XNC Base Chassis")이 'ilo_version' 에 들어가 버전 필드에 모델명이 노출됐다
        # (호출자 오판). VersionString 부재 시 None 이 정직 — 실제 펌웨어는 bmc.firmware_version
        # (Manager.FirmwareVersion)에 있다. iLO(VersionString 보유)는 동작 불변.
        result['oem'] = {
            'ilo_version': _safe(oem, 'Firmware', 'Current', 'VersionString'),
        }
    elif vendor == 'supermicro':                                              # nosec rule12-r1
        oem = _safe(data, 'Oem', 'Supermicro') or {}                          # nosec rule12-r1
        result['oem'] = {'bmc_ip': _safe(oem, 'BMCIPv4Address')}
        if not result['ip'] and result['oem'].get('bmc_ip'):
            result['ip'] = result['oem']['bmc_ip']
    elif vendor == 'lenovo':                                                  # nosec rule12-r1
        # Lenovo XCC: Manager.Oem.Lenovo.release_name 등 운영 상태 메타.
        # 실측 (XCC SR650 V2, 2026-04-28): release_name="whitley_gp_23-5".
        oem = _safe(data, 'Oem', 'Lenovo') or {}                              # nosec rule12-r1
        result['oem'] = {'release_name': _safe(oem, 'release_name')}
    elif vendor == 'dell':                                                    # nosec rule12-r1
        # F50 (cycle 2026-05-06): Dell Manager.Oem.Dell.DelliDRACCard 추가.
        # 사이트 실측 (10.100.15.27 iDRAC9 7.10.70.00): IPMIVersion / LastUpdateTime
        # / LastSystemInventoryTime / URLString 풍부.
        # source: dell.com/support/manuals/.../idrac9_*_redfishapiguide_pub
        #         (DellManager.v1_4_0 + DelliDRACCard.v1_1_0).
        oem_dell = _safe(data, 'Oem', 'Dell', 'DelliDRACCard') or {}          # nosec rule12-r1
        result['oem'] = {
            'idrac_ipmi_version':            _safe(oem_dell, 'IPMIVersion'),
            'idrac_last_inventory_time':     _safe(oem_dell, 'LastSystemInventoryTime'),
            'idrac_last_update_time':        _safe(oem_dell, 'LastUpdateTime'),
            'idrac_url':                     _safe(oem_dell, 'URLString'),
        }
    # cisco: Manager.Oem 는 BMC 펌웨어별 부재 (10.100.15.2 CIMC 4.1(2g) 실측 — Oem={}).
    #        표준 필드 (ManagerType / FirmwareVersion / DateTime / UUID) 만으로 충분.
    # 신규 vendor (huawei/inspur/fujitsu/quanta) — 추가 OEM 추출은 사이트 fixture 수신 후 도입.

    return result, errors


def gather_processors(bmc_ip, system_uri, username, password, timeout, verify_ssl):
    """cpu 섹션 수집 (Redfish endpoints).

    호출 endpoint:
      - GET {system_uri}/Processors                  (Members collection)
      - GET {system_uri}/Processors/{id} × N         (각 CPU 상세)

    Returns: (cpu_list, errors_list)
    """
    path = _p(system_uri) + '/Processors'
    st, coll, err = _get(bmc_ip, path, username, password, timeout, verify_ssl)
    errors = []
    if err or st != 200:
        errors.append(_err('processors', f'Processor 컬렉션 실패: {err or st}'))
        return [], errors

    processors = []
    _absent = 0  # Round 15: Absent/Disabled CPU 카운트 (멤버 있으나 전부 Absent 구분용)
    for member in _dicts(_safe(coll, 'Members')):  # Round 4: 비-list/비-dict Members 방어
        uri = _safe(member, '@odata.id')
        if not uri: continue
        st, pdata, perr = _get(bmc_ip, _p(uri), username, password, timeout, verify_ssl)
        if perr or st != 200:
            errors.append(_err('processors', f'Processor {uri} 실패: {perr or st}'))
            continue
        if _safe(pdata, 'Status', 'State') in ('Absent', 'Disabled'):
            _absent += 1
            continue
        # 2026-04-29 raw 검증 (HPE iLO 6): SerialNumber / PartNumber 가 빈 문자열 ""
        # 반환 (BMC 한계). "" 은 의미상 None — 호출자가 truthy 비교만으로 판정 가능하도록
        # None 으로 정규화. cycle-016 Phase N 풍부 필드는 그대로 유지.
        # 2026-04-30: Cisco 등 trailing whitespace 정규화 추가.
        def _ne_p(*ks):
            # _strip_or_none + _safe 조합 (중복 stripping 로직 3곳 → 1곳 dedup, cycle 2026-05-29)
            return _strip_or_none(_safe(pdata, *ks))

        processors.append({
            'id':                _safe(pdata, 'Id'),
            'name':              _ne_p('Name'),
            'model':             _ne_p('Model'),
            'manufacturer':      _ne_p('Manufacturer'),
            'socket':            _safe(pdata, 'Socket'),
            'total_cores':       _safe_int(_safe(pdata, 'TotalCores')),
            'total_threads':     _safe_int(_safe(pdata, 'TotalThreads')),
            'speed_mhz':         _safe_int(_safe(pdata, 'MaxSpeedMHz')),  # Round 3 #6: int 통일
            'health':            _safe(pdata, 'Status', 'Health'),
            'processor_type':    _safe(pdata, 'ProcessorType'),
            'architecture':      _safe(pdata, 'ProcessorArchitecture'),
            'instruction_set':   _safe(pdata, 'InstructionSet'),
            'serial_number':     _ne_p('SerialNumber'),
            'part_number':       _ne_p('PartNumber'),
        })
    # Round 15: 멤버는 있었으나 전부 Absent/Disabled → 펌웨어 오류/미장착 가능. collected=[] 가
    # 컬렉션 GET 실패와 구분되도록 warning 명시 (gather_memory total_mib=0 구분 철학과 일관).
    if not processors and _absent > 0:
        errors.append(_err('processors',
                           f'모든 CPU({_absent})가 Absent/Disabled (펌웨어 오류 또는 미장착 가능)'))
    return processors, errors


def gather_memory(bmc_ip, system_uri, username, password, timeout, verify_ssl):
    """memory 섹션 수집 (Redfish endpoints).

    호출 endpoint:
      - GET {system_uri}/Memory                  (Members collection)
      - GET {system_uri}/Memory/{id} × N         (각 DIMM 상세)

    Returns: ({'total_mib': int, 'slots': list}, errors_list)
    """
    path = _p(system_uri) + '/Memory'
    st, coll, err = _get(bmc_ip, path, username, password, timeout, verify_ssl)
    errors = []
    if err or st != 200:
        errors.append(_err('memory', f'Memory 컬렉션 실패: {err or st}'))
        return {'total_mib': None, 'slots': []}, errors

    slots, total_mib = [], 0
    for member in _capped(_safe(coll, 'Members') or [], 'memory', errors):
        uri = _safe(member, '@odata.id')
        if not uri: continue
        st, mdata, merr = _get(bmc_ip, _p(uri), username, password, timeout, verify_ssl)
        if merr or st != 200:
            errors.append(_err('memory', f'Memory {uri} 실패: {merr or st}'))
            continue
        if _safe(mdata, 'Status', 'State') == 'Absent':
            continue
        # MEM-01 (2026-06-15 재검수): 구 `_safe(mdata,'CapacityMiB') or 0` 은 CapacityMiB 부재(None)를
        # 0(유효 용량)으로 날조 — 누락과 "0 MiB DIMM" 을 혼동(wrong-default). None 보존(raw 충실).
        # 합산은 아래 `is not None` 가드가 처리. 실데이터(present DIMM 은 CapacityMiB 보유)엔 영향 0 —
        # 부재 케이스만 0→None (cap_int=_safe_int(None)=None). present 0 은 그대로 0 보존.
        cap_int = _safe_int(_safe(mdata, 'CapacityMiB'))
        if cap_int is not None:  # Round 2 #4: 0-capacity 도 합산(no-op이나 preserve-0 일관)
            total_mib += cap_int
        # cycle-016 Phase N: BaseModuleType / RankCount / ErrorCorrection / DataWidth 추가
        # Phase P: 3 채널 키 일관성 — capacity_mb (이전 capacity_mib) 로 통일
        # 2026-04-29 fix B90: Cisco CIMC가 Manufacturer를 raw JEDEC ID '0xCExx'로 emit.
        # _normalize_jedec()로 vendor 이름 정규화 (Samsung/SK hynix/Micron 등).
        # 2026-04-29 fix B09: locator (DIMM 물리 위치) 추가 — 교체 작업 시 식별용.
        _mloc_slot = _safe(mdata, 'MemoryLocation', 'Slot')  # locator Slot 폴백용 (str cast — 아래 LOCATOR-STR)
        slots.append({
            'id':              _safe(mdata, 'Id'),
            'name':            _strip_or_none(_safe(mdata, 'Name')),
            # 'locator' 별도 키: DeviceLocator (벤더 표준 — 'A1','DIMM_A1','PROC1.DIMMA1' 등)
            # MemoryLocation.Slot 도 폴백 (Dell iDRAC 일부 펌웨어).
            # CSUS-R12 (2026-06-15 실미러 검수): HPE CSUS 는 DeviceLocator 부재 + MemoryLocation.Slot=0
            # (16 DIMM 전부 0, 식별 불가). Slot 이 falsy(0/None)일 때만 Location.PartLocation.ServiceLabel
            # (예: 'rack1/chassis_u1/cpu0/dimmA0')로 보정. Slot 이 truthy 인 vendor 는 불변(Additive 회귀안전).
            # LOCATOR-STR (2026-06-15 cross-device 일관성): field_dictionary 계약 = "string|null".
            # Lenovo(DeviceLocator 부재 + Slot=32 truthy int)는 구 코드가 int 32 누출(같은 slot id 는 str '32' 와 불일치).
            # truthy Slot 만 str cast → Lenovo 32→'32', CSUS Slot=0 은 falsy 유지(ServiceLabel 폴백 보존), Dell/DL380 DeviceLocator 불변.
            'locator':         (_safe(mdata, 'DeviceLocator')
                                or (str(_mloc_slot) if _mloc_slot else None)
                                or _safe(mdata, 'Location', 'PartLocation', 'ServiceLabel')
                                or (str(_mloc_slot) if _mloc_slot is not None else None)),
            'capacity_mb':     cap_int,
            'type':            _safe(mdata, 'MemoryDeviceType'),
            'base_module_type': _safe(mdata, 'BaseModuleType'),
            'speed_mhz':       _safe_int(_safe(mdata, 'OperatingSpeedMhz')),  # Round 3 #8: int 통일
            'manufacturer':    _normalize_jedec(_safe(mdata, 'Manufacturer')),
            'serial':          _strip_or_none(_safe(mdata, 'SerialNumber')),
            # 2026-04-30: Cisco 등 trailing whitespace 정규화.
            'part_number':     _strip_or_none(_safe(mdata, 'PartNumber')),
            'rank_count':      _safe_int(_safe(mdata, 'RankCount')),  # Round 4 #8/#14: int 통일
            'data_width_bits': _safe_int(_safe(mdata, 'DataWidthBits')),
            'bus_width_bits':  _safe_int(_safe(mdata, 'BusWidthBits')),
            'error_correction': _safe(mdata, 'ErrorCorrection'),
            'health':          _safe(mdata, 'Status', 'Health'),
        })
    # Round 15 fix: 'or None' 제거 — 수집 성공 시 total_mib 는 항상 int(>=0).
    # 0 (모든 DIMM Absent/0-cap) 을 None(컬렉션 GET 실패 시 반환)과 구분 (cap_int 합산이 0-capacity 도 보존).
    return {'total_mib': total_mib, 'slots': slots}, errors


def _gather_simple_storage(bmc_ip, members, username, password, timeout, verify_ssl):
    """SimpleStorage 경로 — 플랫 디바이스 목록 (구형 BMC 호환)."""
    controllers = []
    errors = []
    for member in members:
        uri = _safe(member, '@odata.id')
        if not uri:
            continue
        st, sdata, serr = _get(bmc_ip, _p(uri), username, password, timeout, verify_ssl)
        if serr or st != 200:
            errors.append(_err('storage', f'SimpleStorage {uri} 실패: {serr or st}'))
            continue
        drives = []
        for dev in _dicts(_safe(sdata, 'Devices')):  # Round 4 #1: 비-list Devices 방어
            cap_int = _safe_int(_safe(dev, 'CapacityBytes'))
            drives.append({
                'id':             None,
                'name':           _safe(dev, 'Name'),
                'model':          _safe(dev, 'Model'),
                'serial':         None,
                'manufacturer':   _safe(dev, 'Manufacturer'),
                'media_type':     None,
                'protocol':       None,
                'capacity_bytes': cap_int,
                'capacity_gb':    round(cap_int / BYTES_PER_GB_DECIMAL, 2) if cap_int is not None else None,  # 0 보존(known-zero) Round 1 #16
                'health':         _safe(dev, 'Status', 'Health'),
            })
        controllers.append({
            'id': _safe(sdata, 'Id'), 'name': _safe(sdata, 'Name'),
            'health': _safe(sdata, 'Status', 'Health'), 'drives': drives,
        })
    return controllers, errors


def _extract_storage_controller_info(sdata, bmc_ip, username, password, timeout, verify_ssl):
    """컨트롤러 메타 추출 — StorageControllers 인라인 우선, Controllers 서브링크 fallback.

    controller_name 은 실제 하드웨어 모델명 (예: "ThinkSystem RAID 930-8i 2GB Flash PCIe").
    Storage 객체의 Name 은 "RAID Storage" 같은 컨테이너 라벨이라 별개로 보존.
    """
    # 반환 (dict, errors_list) — 401/403/503 응답을 silent fail 로 두지 않고
    # errors 에 누적해 호출자가 "controller 정보 부재" 사유를 추적할 수 있게 한다.
    # 이전 구현은 cst != 200 인 모든 응답을 빈 dict 로만 반환해 권한 부족/일시 과부하를
    # 정상 부재와 구분 불가했음.
    errors = []
    inline_ctrls = _safe(sdata, 'StorageControllers') or []
    if isinstance(inline_ctrls, list) and inline_ctrls:  # rule 95 R1 #2: 비-list StorageControllers 방어 (Round 1 #0)
        c = inline_ctrls[0]
        return {
            'controller_name':         _safe(c, 'Name'),
            'controller_model':        _safe(c, 'Model'),
            'controller_firmware':     _safe(c, 'FirmwareVersion'),
            'controller_manufacturer': _safe(c, 'Manufacturer'),
            'controller_health':       _safe(c, 'Status', 'Health'),
        }, errors
    ctrl_link = _safe(sdata, 'Controllers', '@odata.id')
    if not ctrl_link:
        return {}, errors
    cst, ctrl_coll, cerr = _get(bmc_ip, _p(ctrl_link), username, password, timeout, verify_ssl)
    if cerr or cst != 200:
        # 401/403/503: BMC 가 응답한 의미 있는 에러 — errors 에 기록
        errors.append(_err('storage',
                           f'Controllers 컬렉션 fetch 실패 ({ctrl_link}): {cerr or cst}',
                           detail={'status_code': cst}))
        return {'controller_fetch_status': cst}, errors
    ctrl_members = _safe(ctrl_coll, 'Members') or []
    if not isinstance(ctrl_members, list) or not ctrl_members:  # rule 95 R1 #2: 비-list 방어 (Round 2 #13)
        return {}, errors
    c_uri = _safe(ctrl_members[0], '@odata.id')
    if not c_uri:
        return {}, errors
    cst2, cdata, cerr2 = _get(bmc_ip, _p(c_uri), username, password, timeout, verify_ssl)
    if cerr2 or cst2 != 200:
        errors.append(_err('storage',
                           f'Controller fetch 실패 ({c_uri}): {cerr2 or cst2}',
                           detail={'status_code': cst2}))
        return {'controller_fetch_status': cst2}, errors
    return {
        'controller_name':         _safe(cdata, 'Name'),
        'controller_model':        _safe(cdata, 'Model'),
        'controller_firmware':     _safe(cdata, 'FirmwareVersion'),
        'controller_manufacturer': _safe(cdata, 'Manufacturer'),
        'controller_health':       _safe(cdata, 'Status', 'Health'),
    }, errors


def _extract_storage_drives(sdata, bmc_ip, username, password, timeout, verify_ssl):
    """Drives 추출 — Empty Bay 필터링 + 정규화."""
    drives = []
    errors = []
    for d_member in _capped(_safe(sdata, 'Drives') or [], 'storage', errors):
        d_uri = _safe(d_member, '@odata.id')
        if not d_uri:
            continue
        dst, ddata, derr = _get(bmc_ip, _p(d_uri), username, password, timeout, verify_ssl)
        if derr or dst != 200:
            errors.append(_err('storage', f'Drive {d_uri} 실패: {derr or dst}'))
            continue
        # Q-09: HPE Empty Bay 필터 — CapacityBytes가 없거나 Name에 "Empty" 포함 시 스킵
        drive_name = _str(_safe(ddata, 'Name'))  # Round 11 #1: 분리형 string-method 방어
        cap_int = _safe_int(_safe(ddata, 'CapacityBytes'), default=0)
        if not cap_int:
            continue
        if 'empty' in drive_name.lower():
            continue
        # PredictedMediaLifeLeftPercent: HPE float / others int → normalize to int
        life_pct = _safe(ddata, 'PredictedMediaLifeLeftPercent')
        if life_pct is not None:
            life_pct = _safe_int(life_pct)
        drives.append({
            'id':             _safe(ddata, 'Id'),
            'name':           _safe(ddata, 'Name'),
            'model':          _safe(ddata, 'Model'),
            'serial':         _safe(ddata, 'SerialNumber'),
            'manufacturer':   _safe(ddata, 'Manufacturer'),
            'media_type':     _safe(ddata, 'MediaType'),
            'protocol':       _safe(ddata, 'Protocol'),
            'capacity_bytes': cap_int,
            'capacity_gb':    round(cap_int / BYTES_PER_GB_DECIMAL, 2) if cap_int else None,
            'health':         _safe(ddata, 'Status', 'Health') or _safe(ddata, 'Status', 'HealthRollup'),
            'failure_predicted':      _safe(ddata, 'FailurePredicted'),
            'predicted_life_percent': life_pct,
        })
    return drives, errors


# Redfish VolumeType enum → canonical RAID level (cycle 2026-06-04 R-4 — module-level hoist)
_VOLUMETYPE_RAID_MAP = {
    'NonRedundant': 'RAID0', 'Mirrored': 'RAID1',
    'StripedWithParity': 'RAID5', 'SpannedMirrors': 'RAID10',
    'SpannedStripesWithParity': 'RAID50',
}


def _extract_storage_volumes(sdata, controller_id, bmc_ip, username, password, timeout, verify_ssl):
    """Volumes 추출 — RAID 정규화 + JBOD 필터링."""
    volumes = []
    errors = []
    vol_link = _safe(sdata, 'Volumes', '@odata.id')
    if not vol_link:
        return volumes, errors
    vst, vcoll, verr = _get(bmc_ip, _p(vol_link), username, password, timeout, verify_ssl)
    if verr or vst != 200:
        # Volumes 미지원(HBA 모드 등)은 정상 — 에러 추가하지 않음
        return volumes, errors
    # cycle 2026-06-14 (DELL R740 실 미러 검수 STO-1): Dell 컨트롤러 OEM 이 명시하는 부팅 VD 의
    # FQDD(=부팅 Volume.Id). R740 iDRAC9 펌웨어는 표준 Volume.BootVolume 도 Volume.Oem.Dell.
    # DellVolume.BootVolumeSource 도 미제공 — 부팅 볼륨 정보는 *컨트롤러* 리소스의 이 키에만 존재.
    # 이게 없으면 모든 Dell 볼륨 boot_volume 이 false 로 오보됨(실제 OS 볼륨인데도). vol_id 와 매칭.
    # source: Systems/.../Storage/<ctrl> Oem.Dell.DellController.BootVirtualDiskFQDD, R740 실 미러.
    _boot_vd_fqdd = _safe(sdata, 'Oem', 'Dell', 'DellController', 'BootVirtualDiskFQDD')  # nosec rule12-r1
    if not (isinstance(_boot_vd_fqdd, str) and _boot_vd_fqdd.strip()):
        _boot_vd_fqdd = None
    for v_member in _dicts(_safe(vcoll, 'Members')):  # Round 5: 비-list/dict 방어
        v_uri = _safe(v_member, '@odata.id')
        if not v_uri:
            continue
        vst2, vdata, verr2 = _get(bmc_ip, _p(v_uri), username, password, timeout, verify_ssl)
        if verr2 or vst2 != 200:
            errors.append(_err('storage', f'Volume {v_uri} 실패: {verr2 or vst2}'))
            continue
        # RAIDType 표준 우선, Dell VolumeType fallback
        raid_type = _safe(vdata, 'RAIDType') or _VOLUMETYPE_RAID_MAP.get(_safe(vdata, 'VolumeType'))
        # member_drive_ids: Links.Drives[]의 @odata.id에서 마지막 path segment
        member_ids = [
            d_oid.rstrip('/').rsplit('/', 1)[-1]
            for d_link in _dicts(_safe(vdata, 'Links', 'Drives'))
            for d_oid in [_safe(d_link, '@odata.id')] if d_oid and isinstance(d_oid, str)  # rule 95: 비-str @odata.id 방어 (Round 1 #1)
        ]
        # JBOD/pass-through 필터: Non-RAID 모드에서 물리 디스크를 개별 Volume으로 노출
        vol_id = _safe(vdata, 'Id')
        if raid_type is None and len(member_ids) == 1 and member_ids[0] == vol_id:
            continue
        vcap_int = _safe_int(_safe(vdata, 'CapacityBytes'))
        # BUG-16 fix: Volume Name / DisplayName trailing whitespace 제거 (raw 'VD_0   ' 사고)
        v_name_raw = _safe(vdata, 'Name')
        v_name = v_name_raw.strip() if isinstance(v_name_raw, str) else v_name_raw
        # 2026-04-29 fix B48: Cisco CIMC가 Volume.Name을 빈 문자열 "" 로 emit.
        # 호출자 친화 fallback: 'Volume {id}' 또는 '{raid_level} Volume'.
        if not v_name:
            if vol_id:
                v_name = f"Volume {vol_id}"
            elif raid_type:
                v_name = f"{raid_type} Volume"
            else:
                v_name = None
        # BUG-15 fix: 표준 Redfish Volume.BootVolume 우선, 없으면 Dell Oem fallback.
        # 표준 필드가 명시 false 인 경우도 보존하기 위해 None 비교 사용.
        std_boot = _safe(vdata, 'BootVolume')
        if std_boot is not None:
            boot_volume = bool(std_boot)
        elif _boot_vd_fqdd is not None and vol_id is not None:                          # nosec rule12-r1
            # Dell 컨트롤러 OEM 의 BootVirtualDiskFQDD = 부팅 VD 의 Id (권위 source).
            # 매칭되는 볼륨만 true, 나머지는 false (정확한 단일 부팅 볼륨 식별).
            boot_volume = (vol_id == _boot_vd_fqdd)
        elif _safe(vdata, 'Oem', 'Dell'):                                              # nosec rule12-r1
            boot_volume = _safe(vdata, 'Oem', 'Dell', 'DellVolume', 'BootVolumeSource') is not None  # nosec rule12-r1
        else:
            boot_volume = None
        volumes.append({
            'id':               _safe(vdata, 'Id'),
            'name':             v_name,
            'controller_id':    controller_id,
            'member_drive_ids': member_ids,
            'raid_level':       raid_type,
            'total_mb':         (vcap_int // BYTES_PER_MIB) if vcap_int is not None else None,  # 0 보존(known-zero) Round 1 #17
            # BUG-19 fix: drive 와 동일하게 Status.Health 누락 시 HealthRollup fallback.
            'health':           _safe(vdata, 'Status', 'Health') or _safe(vdata, 'Status', 'HealthRollup'),
            'state':            _safe(vdata, 'Status', 'State'),
            'boot_volume':      boot_volume,
        })
    return volumes, errors


def _gather_standard_storage(bmc_ip, members, username, password, timeout, verify_ssl):
    """Storage 정규경로 — 컨트롤러 → 드라이브 → 볼륨 계층."""
    controllers = []
    volumes = []
    errors = []
    for member in members:
        uri = _safe(member, '@odata.id')
        if not uri:
            continue
        st, sdata, serr = _get(bmc_ip, _p(uri), username, password, timeout, verify_ssl)
        if serr or st != 200:
            errors.append(_err('storage', f'Storage {uri} 실패: {serr or st}'))
            continue
        ctrl_info, c_errs = _extract_storage_controller_info(sdata, bmc_ip, username, password, timeout, verify_ssl)
        errors.extend(c_errs)
        drives, d_errs = _extract_storage_drives(sdata, bmc_ip, username, password, timeout, verify_ssl)
        errors.extend(d_errs)
        # name 우선순위: controller_name (실제 하드웨어 모델) → Storage 객체 Name fallback.
        # 실측 (Lenovo XCC SR650 V2): 컨트롤러 식별 정보 손실 차단.
        ctrl_name = ctrl_info.get('controller_name') or _safe(sdata, 'Name')
        ctrl_entry = {
            'id':     _safe(sdata, 'Id'),
            'name':   ctrl_name,
            'health': _safe(sdata, 'Status', 'Health') or _safe(sdata, 'Status', 'HealthRollup'),
            'drives': drives,
        }
        ctrl_entry.update(ctrl_info)
        controllers.append(ctrl_entry)
        vols, v_errs = _extract_storage_volumes(sdata, _safe(sdata, 'Id'), bmc_ip, username, password, timeout, verify_ssl)
        volumes.extend(vols)
        errors.extend(v_errs)
    return controllers, volumes, errors


def _gather_smart_storage(bmc_ip, system_uri, username, password, timeout, verify_ssl):    # nosec rule12-r1
    """HPE iLO4 SmartStorage legacy path (cycle 2026-05-07 M-I1 — Additive).

    iLO4 (Gen8/Gen9 pre-iLO5) 펌웨어는 표준 `/Systems/{id}/Storage` 미도입,
    HPE OEM `/Systems/{id}/SmartStorage/ArrayControllers/*` + `/HostBusAdapters/*`
    경로로만 storage 정보 제공.

    rule 12 R1 Allowed — HPE OEM Redfish spec 직접 의존 (SmartStorage namespace).
    source: HPE iLO4 Redfish API guide (DSP0268 v1.5 pre-spec OEM path).

    Returns: (controllers: list, volumes: list, errors: list) — gather_standard_storage 와
             동일한 envelope shape (controllers / volumes / health / drives).
    실측 fixture: tests/fixtures/redfish/hpe_ilo4/ (Round 14 web sources).
    """
    base = _p(system_uri) + '/SmartStorage'
    st, ss_root, err = _get(bmc_ip, base, username, password, timeout, verify_ssl)
    errors = []
    if err or st != 200:
        errors.append(_err('storage', f'SmartStorage 미지원: {err or st}'))
        return [], [], errors

    controllers = []
    # ArrayControllers (RAID) + HostBusAdapters (HBA pass-through) 둘 다 시도
    for coll_key in ('ArrayControllers', 'HostBusAdapters'):
        coll_link = _safe(ss_root, coll_key, '@odata.id')
        if not coll_link:
            continue
        cst, coll, cerr = _get(bmc_ip, _p(coll_link), username, password, timeout, verify_ssl)
        if cerr or cst != 200:
            errors.append(_err('storage', f'SmartStorage.{coll_key} 실패: {cerr or cst}'))
            continue
        for member in _dicts(_safe(coll, 'Members')):  # Round 4: 비-list/비-dict Members 방어
            ctrl_uri = _safe(member, '@odata.id')
            if not ctrl_uri:
                continue
            ctrl_st, ctrl_data, ctrl_err = _get(bmc_ip, _p(ctrl_uri), username, password, timeout, verify_ssl)
            if ctrl_err or ctrl_st != 200:
                errors.append(_err('storage', f'SmartStorage controller {ctrl_uri} 실패: {ctrl_err or ctrl_st}'))
                continue
            # PhysicalDrives 컬렉션 (iLO4 SmartStorage 구조)
            drives = []
            pd_link = _safe(ctrl_data, 'PhysicalDrives', '@odata.id') or _safe(ctrl_data, 'Links', 'PhysicalDrives', '@odata.id')
            if pd_link:
                pst, pcoll, _perr = _get(bmc_ip, _p(pd_link), username, password, timeout, verify_ssl)
                if pst == 200:
                    for pd_m in _dicts(_safe(pcoll, 'Members')):  # Round 5: 비-list/dict 방어
                        pd_uri = _safe(pd_m, '@odata.id')
                        if not pd_uri:
                            continue
                        pdst, pddata, _pderr = _get(bmc_ip, _p(pd_uri), username, password, timeout, verify_ssl)
                        if pdst != 200:
                            continue
                        # iLO4 SmartStorage 단위 정정 (Round 1 #10/11/20): CapacityGB 는 십진 GB,
                        # CapacityMiB 는 이진 MiB. 둘을 혼동해 capacity_gb 에 MiB 값을 그대로 넣어
                        # ~1000x 부풀려 보고하던 오류 수정. 단위별로 capacity_bytes/capacity_gb 일관 산출.
                        cap_gb_field = _safe_int(_safe(pddata, 'CapacityGB'))
                        cap_mib_field = _safe_int(_safe(pddata, 'CapacityMiB'))
                        if cap_gb_field:
                            cap_bytes = cap_gb_field * BYTES_PER_GB_DECIMAL
                            capacity_gb = round(float(cap_gb_field), 2)  # Round 4 #13: MiB 경로와 float 타입 일관
                        elif cap_mib_field:
                            cap_bytes = cap_mib_field * BYTES_PER_MIB
                            capacity_gb = round(cap_bytes / BYTES_PER_GB_DECIMAL, 2)
                        else:
                            cap_bytes = None
                            capacity_gb = None
                        drives.append({
                            'id':             _safe(pddata, 'Id'),
                            'name':           _safe(pddata, 'Model') or _safe(pddata, 'Name'),
                            'model':          _safe(pddata, 'Model'),
                            'serial':         _safe(pddata, 'SerialNumber'),
                            'manufacturer':   _safe(pddata, 'Manufacturer'),
                            'media_type':     _safe(pddata, 'MediaType'),
                            'protocol':       _safe(pddata, 'InterfaceType'),
                            'capacity_bytes': cap_bytes,
                            'capacity_gb':    capacity_gb,
                            'health':         _safe(pddata, 'Status', 'Health'),
                        })
            ctrl_id = _safe(ctrl_data, 'Id')
            controllers.append({
                'id':                      ctrl_id,
                'name':                    _safe(ctrl_data, 'Model') or _safe(ctrl_data, 'Name'),
                'health':                  _safe(ctrl_data, 'Status', 'Health'),
                'drives':                  drives,
                'controller_name':         _safe(ctrl_data, 'Model'),
                'controller_model':        _safe(ctrl_data, 'Model'),
                'controller_firmware':     _safe(ctrl_data, 'FirmwareVersion', 'Current', 'VersionString')
                                           or _safe(ctrl_data, 'FirmwareVersion'),
                'controller_manufacturer': _safe(ctrl_data, 'Manufacturer') or 'HPE',  # nosec rule12-r1 — SmartStorage path 은 HPE OEM legacy spec 직접 의존
                'controller_health':       _safe(ctrl_data, 'Status', 'Health'),
            })
    # SmartStorage 는 logical volume (LogicalDrives) 별도 경로 — iLO4 fixture 부재로
    # 본 cycle 은 controllers + drives 만 (Additive — 향후 lab fixture 추가 시 보강)
    return controllers, [], errors


def gather_storage(bmc_ip, system_uri, username, password, timeout, verify_ssl):
    """Storage 진입 — Storage → SimpleStorage → SmartStorage fallback dispatcher.

    cycle 2026-05-07 M-I1: SmartStorage (HPE iLO4) fallback chain 추가 — Additive.
    기존 Storage / SimpleStorage 분기 변경 0. SmartStorage 는 iLO4 legacy path 라
    표준 / SimpleStorage 둘 다 404 일 때만 시도.
    """
    path = _p(system_uri) + '/Storage'
    st, coll, err = _get(bmc_ip, path, username, password, timeout, verify_ssl)
    errors = []

    # Storage 실패 시 SimpleStorage fallback (구형 BMC 호환)
    use_simple = False
    if err or st != 200:
        simple_path = _p(system_uri) + '/SimpleStorage'
        st2, coll2, err2 = _get(bmc_ip, simple_path, username, password, timeout, verify_ssl)
        if not err2 and st2 == 200:
            use_simple = True
            coll = coll2
            # 2026-08-12 (H11): 이건 **수집에 성공한** 정보다. errors 에 넣으면
            #   _make_section_runner 가 섹션을 failed 로 잡아 status 가 partial 로 강등된다.
            _notice('storage', 'Storage 미지원, SimpleStorage fallback 사용')
        else:
            # cycle 2026-05-07 M-I1: SmartStorage (HPE iLO4 OEM legacy) fallback —
            # 표준/SimpleStorage 모두 404 시 HPE 구 path 시도 (Additive).
            ctrls, vols, smart_errors = _gather_smart_storage(
                bmc_ip, system_uri, username, password, timeout, verify_ssl
            )
            if ctrls:
                # 2026-08-12 (H11): 성공한 fallback — errors 아님 (위 SimpleStorage 와 동일 사유)
                _notice('storage', 'Storage/SimpleStorage 미지원, SmartStorage (HPE OEM legacy) fallback 사용')  # nosec rule12-r1 — SmartStorage OEM path spec
                errors.extend(smart_errors)
                return {'controllers': ctrls, 'volumes': vols}, errors
            errors.append(_err('storage', f'Storage/SimpleStorage/SmartStorage 모두 실패: {err or st}'))
            return {'controllers': [], 'volumes': []}, errors

    members = _dicts(_safe(coll, 'Members'))  # Round 8 #3: 비-list Members 방어
    if use_simple:
        controllers, sub_errors = _gather_simple_storage(bmc_ip, members, username, password, timeout, verify_ssl)
        errors.extend(sub_errors)
        # 2026-08-12: fallback **사용 사실**은 notice 지만, fallback 이 200 을 주고도
        #   결과가 비면 그건 성공이 아니다. errors 가 비면 _make_section_runner 가
        #   섹션을 collected 로만 잡아 "데이터 없음" 이 아무 신호 없이 success 로 나간다.
        if not controllers and not errors:
            errors.append(_err('storage',
                               'SimpleStorage 경로가 응답했지만 디스크 정보가 비어 있음'))
        return {'controllers': controllers, 'volumes': []}, errors
    controllers, volumes, sub_errors = _gather_standard_storage(bmc_ip, members, username, password, timeout, verify_ssl)
    errors.extend(sub_errors)
    return {'controllers': controllers, 'volumes': volumes}, errors


def gather_network(bmc_ip, system_uri, username, password, timeout, verify_ssl):
    """Systems/{id}/EthernetInterfaces — 호스트 서버 NIC"""
    path = _p(system_uri) + '/EthernetInterfaces'
    st, coll, err = _get(bmc_ip, path, username, password, timeout, verify_ssl)
    errors = []
    if err or st != 200:
        errors.append(_err('network', f'EthernetInterfaces 실패: {err or st}'))
        return [], errors

    nics = []
    for member in _dicts(_safe(coll, 'Members')):  # Round 4: 비-list/비-dict Members 방어
        uri = _safe(member, '@odata.id')
        if not uri: continue
        st, ndata, nerr = _get(bmc_ip, _p(uri), username, password, timeout, verify_ssl)
        if nerr or st != 200:
            errors.append(_err('network', f'NIC {uri} 실패: {nerr or st}'))
            continue
        ipv4_addrs = [
            {'address': a.get('Address'), 'subnet_mask': a.get('SubnetMask'),
             'gateway': a.get('Gateway'), 'address_origin': a.get('AddressOrigin')}
            for a in _dicts(_safe(ndata, 'IPv4Addresses'))
            if a.get('Address') not in (None, '0.0.0.0', '')
        ]
        # 2026-04-29 fix B13: link_status enum 정규화 — Dell linkup/linkdown / HPE NoLink / Cisco Connected/Disconnected → up/down/unknown
        # cycle 2026-06-15 (Lenovo SR650 V4 실미러 검수): MAC 소문자 정규화 — bmc.mac_address /
        # network_adapters.*.mac / ports.associated_address 와 case 일관(라이브러리 lowercase 규약,
        # _normalize_wwn 독스트링). Lenovo XCC 는 System EthernetInterface MAC 을 대문자로 노출해
        # 같은 물리 NIC 이 data.network(대문자) vs network_adapters(소문자) 로 갈렸다. raw 가
        # colon-hex 라 .lower() 무손실.
        _nmac = _safe(ndata, 'MACAddress')
        nics.append({
            'id': _safe(ndata, 'Id'), 'name': _safe(ndata, 'Name') or _safe(ndata, 'Id') or '',
            'mac': _nmac.lower() if isinstance(_nmac, str) else _nmac, 'speed_mbps': _safe_int(_safe(ndata, 'SpeedMbps')),  # Round 2 #18: mbps int 통일
            'mtu': _safe_int(_safe(ndata, 'MTUSize')),  # Round 6 #6: int 통일(마지막 수치 필드)
            'link_status': _normalize_link_status(_safe(ndata, 'LinkStatus')),
            'health': _safe(ndata, 'Status', 'Health'),
            'ipv4': ipv4_addrs,
        })
    return nics, errors


def _detect_nic_ocp_slot(adata):                                              # nosec rule12-r1
    """cycle 2026-05-07 M-I4: NIC OCP (Open Compute Project) mezzanine 식별.

    NetworkAdapter.Location.PartLocation.LocationType 또는 ServiceLabel 패턴으로
    OCP NIC 식별. 펌웨어 별 차이:
      - iDRAC9 6.x+ : Location.PartLocation.LocationType='Slot' + ServiceLabel='OCP'
      - iLO6+ : Oem.Hpe.Location.OCPSlot
      - Supermicro X13+ : Location.PartLocation.LocationType='Slot' + name 'OCP*'

    Returns: 'ocp' / 'pcie' / None (식별 불가)

    rule 12 R1 Allowed — DSP0268 Location.PartLocation spec 직접 의존.
    rule 92 R2 — Additive helper (호출자가 사용. envelope 영향 0).
    """
    if not isinstance(adata, dict):
        return None
    loc = _safe(adata, 'Location', 'PartLocation') or {}
    service_label = _str(_safe(loc, 'ServiceLabel')).upper()
    location_type = _str(_safe(loc, 'LocationType')).lower()
    name = _str(_safe(adata, 'Name')).upper()
    if 'OCP' in service_label or 'OCP' in name:
        return 'ocp'
    # HPE OEM fallback
    hpe_oem = _safe(adata, 'Oem', 'Hpe') or {}                                # nosec rule12-r1
    if _safe(hpe_oem, 'Location', 'OCPSlot') or _safe(hpe_oem, 'OCPSlot'):    # nosec rule12-r1
        return 'ocp'
    if location_type == 'slot':
        return 'pcie'
    return None


def _detect_nic_sriov_capable(adata):                                         # nosec rule12-r1
    """cycle 2026-05-07 M-I4: NIC SR-IOV capability 식별.

    표준 DSP0268 v1.6+ NetworkDeviceFunctions 우선, vendor OEM fallback:
      - 표준: NetworkDeviceFunctions[*].SRIOV.SRIOVCapable
      - Dell: Oem.Dell.NICDeviceFunctions.SRIOVCapable
      - HPE:  Oem.Hpe.NetworkAdapter.SRIOVConfig (dict 존재 = capable)

    Args:
        adata: NetworkAdapter 응답 dict

    Returns: True / False / None (미응답)

    rule 12 R1 Allowed — Redfish OEM spec 직접 의존.
    rule 92 R2 — Additive helper (envelope 영향 0).
    """
    if not isinstance(adata, dict):
        return None
    # 표준 path: Controllers[0].Links.NetworkDeviceFunctions (DSP0268 v1.6+)
    # 본 helper 는 adapter 단위 응답만 사용 — 깊은 collection fetch 는 호출자 책임.
    # SR-IOV capability 표시는 일반적으로 NetworkAdapter root 또는 Oem 영역에 hint.
    if _safe(adata, 'SRIOV', 'SRIOVCapable') is True:
        return True
    # Dell OEM
    dell_oem = _safe(adata, 'Oem', 'Dell') or {}                              # nosec rule12-r1
    dell_sriov = _safe(dell_oem, 'NICDeviceFunctions', 'SRIOVCapable')        # nosec rule12-r1
    if dell_sriov is not None:
        return bool(dell_sriov)
    # HPE OEM
    hpe_oem = _safe(adata, 'Oem', 'Hpe') or {}                                # nosec rule12-r1
    if _safe(hpe_oem, 'NetworkAdapter', 'SRIOVConfig'):                       # nosec rule12-r1
        return True
    return None


def _normalize_wwn(value):
    """WWN(WWPN/WWNN) → 소문자 colon-grouped hex 정규화 (cross-channel 매칭 키).

    입력 변형 흡수: '20:00:00:24:..', '0x200000..', '200000..', None.
    16 hex(8 octet) 가 아니면 정리본(소문자) 보존 — 날조 금지 (rule 25 R7-B).
    """
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s or s in ('none', 'null', '0', '0x0'):
        return None
    s = _removeprefix(s, '0x')
    hexonly = ''.join(c for c in s if c in '0123456789abcdef')
    if len(hexonly) != 16:
        return str(value).strip().lower()
    return ':'.join(hexonly[i:i + 2] for i in range(0, 16, 2))


def _classify_port_protocol(port_protocol, link_tech, ndf, pdata=None):
    """포트/디바이스펑션 → 'FibreChannel'|'FCoE'|'InfiniBand'|'Ethernet'|None.

    DMTF 정본 (EXTERNAL-CONTRACTS §1/§2 — cycle 2026-05-29):
      - FC : Port.PortProtocol(Protocol enum) ∈ {FC,FCP,FCoE}
             또는 NetworkDeviceFunction.NetDevFuncType ∈ {FibreChannel,FibreChannelOverEthernet}
      - IB : Port.LinkNetworkTechnology=='InfiniBand' (또는 ActiveLinkTechnology)
             또는 NetworkDeviceFunction.NetworkDeviceTechnology=='InfiniBand'
    PortType enum 에는 FC/IB 값이 없어 사용 금지 (구 코드 dead-code 원인).
    rule 12 R1 Allowed — DMTF Protocol/NetDevFuncType spec 직접 의존 (vendor 분기 아님).
    """
    pp = _str(port_protocol).strip().upper()
    lt = _str(link_tech).strip().lower()
    ndf_type = ''
    ndf_tech = ''
    ndf_wwpn = None
    if isinstance(ndf, dict):
        ndf_type = _str(ndf.get('func_type')).strip().lower()
        ndf_tech = _str(ndf.get('net_dev_tech')).strip().lower()
        # CSUS-FC1 (2026-06-15 실미러 검수): NetDevFuncType/PortProtocol 부재 펌웨어(HPE CSUS
        # RMC — NDF 에 NetDevFuncType 없이 FibreChannel.WWPN 만 노출)에서도 FC 식별.
        # cycle 2026-08-03: 이 휴리스틱은 함수 **맨 끝**(명시 신호 전무 시)로 강등됐다 —
        # "WWPN 은 FC 전용 식별자" 전제가 FCoE 지원 CNA 에서 깨지기 때문(하단 주석 참조).
        # (Node/Port GUID 는 IB 시그널로 쓰지 않는다 — ConnectX VPI 가
        # Ethernet 모드에서도 GUID 를 노출해 Ethernet NIC 을 IB 로 오분류하기 때문.)
        ndf_wwpn = ndf.get('wwpn')
    # IB 우선 (IB NDF 가 Ethernet 으로 오인되지 않도록)
    if lt == 'infiniband' or ndf_tech == 'infiniband' or ndf_type == 'infiniband':
        return 'InfiniBand'
    if isinstance(pdata, dict) and isinstance(pdata.get('InfiniBand'), dict):
        return 'InfiniBand'
    if pp == 'FCOE' or ndf_type == 'fibrechanneloverethernet':
        return 'FCoE'
    if pp in ('FC', 'FCP', 'FIBRECHANNEL') or ndf_type == 'fibrechannel':
        return 'FibreChannel'
    if isinstance(pdata, dict) and isinstance(pdata.get('FibreChannel'), dict):
        return 'FibreChannel'
    if pp == 'ETHERNET' or lt == 'ethernet' or ndf_type == 'ethernet':
        return 'Ethernet'
    # CSUS-R8 (2026-06-15 실미러 검수): Port.Ethernet dict 존재 → Ethernet (FC/IB dict-presence 와
    # 대칭). HPE CSUS Mellanox NIC(MCX631102)은 PortProtocol/NetDevFuncType 없이 Port.Ethernet.
    # AssociatedMACAddresses 만 노출 → 구 코드는 port_type=None(미분류). DMTF Port.Ethernet 표준 블록.
    if isinstance(pdata, dict) and isinstance(pdata.get('Ethernet'), dict):
        return 'Ethernet'
    # CSUS-FC1 휴리스틱은 **명시 신호가 모두 없을 때만** 적용한다 (cycle 2026-08-03 강등).
    # WWPN 존재만으로 FC 로 확정하던 위치가 Ethernet 판정보다 위에 있어, FCoE 지원 CNA
    # (실측: 사이트 Dell R630 의 'BRCM 10G/GbE 2+2P 57800 rNDC')가 FC HBA 로 오분류됐다.
    # 이런 CNA 는 이더넷 기능에도 MAC 파생 WWN 을 달고 나온다 — 같은 물리 포트가
    # network.ports[]=Ethernet, storage.hbas[]=FibreChannel 로 갈리는 자기모순 발생.
    # FCoE 가 실제로 설정된 장비는 NetDevFuncType=FibreChannelOverEthernet 을 주므로
    # 위쪽 FCoE 분기에서 잡힌다 — 본 강등의 영향 없음.
    if ndf_wwpn:
        return 'FibreChannel'
    return None


def _fetch_ndf_index(bmc_ip, adata, username, password, timeout, verify_ssl):
    """NetworkAdapter.NetworkDeviceFunctions 수집 → 식별 dict 리스트.

    각 entry: {id, func_type, net_dev_tech, wwpn, wwnn, fc_id, node_guid, port_guid, port_uri}.
    port_uri = Links.PhysicalPortAssignment / PhysicalNetworkPortAssignment (정규화) — Port join 용.
    WWPN/WWNN(FC) 와 Node/Port GUID(IB) 는 Port 가 아니라 NetworkDeviceFunction 에 존재 (DMTF).
    미지원/오류 시 빈 리스트 (graceful — Port 기반 분류로 fallback).
    """
    ndfs = []
    ndf_link = _safe(adata, 'NetworkDeviceFunctions', '@odata.id')
    if not ndf_link:
        return ndfs
    st, coll, err = _get(bmc_ip, _p(ndf_link), username, password, timeout, verify_ssl)
    if err or st != 200:
        return ndfs
    for m in _dicts(_safe(coll, 'Members')):  # Round 5: 비-list/dict 방어
        u = _safe(m, '@odata.id')
        if not u:
            continue
        s2, nd, e2 = _get(bmc_ip, _p(u), username, password, timeout, verify_ssl)
        if e2 or s2 != 200 or not isinstance(nd, dict):
            continue
        fc = _safe(nd, 'FibreChannel') or {}
        ib = _safe(nd, 'InfiniBand') or {}
        port_uri = (_safe(nd, 'Links', 'PhysicalPortAssignment', '@odata.id')
                    or _safe(nd, 'Links', 'PhysicalNetworkPortAssignment', '@odata.id'))
        ndfs.append({
            'id':           _safe(nd, 'Id'),
            'func_type':    _safe(nd, 'NetDevFuncType'),
            'net_dev_tech': _safe(nd, 'NetworkDeviceTechnology'),
            'wwpn':         _normalize_wwn(_safe(fc, 'WWPN') or _safe(fc, 'PermanentWWPN')),
            'wwnn':         _normalize_wwn(_safe(fc, 'WWNN') or _safe(fc, 'PermanentWWNN')),
            'fc_id':        _safe(fc, 'FibreChannelId'),
            'node_guid':    _safe(ib, 'NodeGUID') or _safe(ib, 'PermanentNodeGUID'),
            'port_guid':    _safe(ib, 'PortGUID') or _safe(ib, 'PermanentPortGUID'),
            'port_uri':     _p(port_uri) if port_uri else None,
        })
    return ndfs


def _make_fc_hba(adapter_id, adapter_info, port_id, cls, link_status, speed_gbps,
                 primary_addr, ndf):
    """canonical storage.hbas[] entry 생성 (전 채널 통일 shape — EXTERNAL-CONTRACTS §1)."""
    wwpn = ndf.get('wwpn') if isinstance(ndf, dict) else None
    wwnn = ndf.get('wwnn') if isinstance(ndf, dict) else None
    if not wwpn:
        # Round 1 #22: primary_addr 가 MAC(6 octet)일 수 있음 — FC WWPN(8 octet/16 hex)으로
        # 정규화되는 경우에만 fallback. MAC 을 WWPN 으로 오기재하지 않음.
        cand = _normalize_wwn(primary_addr)
        if cand and len(cand.replace(':', '')) == 16:
            wwpn = cand
    return {
        'adapter_id':      adapter_id,
        'adapter_model':   adapter_info.get('model'),
        'port_id':         port_id,
        'wwpn':            wwpn,
        'wwnn':            wwnn,
        'model':           adapter_info.get('model'),
        'vendor':          adapter_info.get('manufacturer'),
        'driver':          None,
        'firmware':        adapter_info.get('firmware_version'),
        'link_status':     link_status,
        'link_speed_gbps': speed_gbps,
        'port_type':       cls,
        'source':          'redfish',
    }


def _make_ib_port(adapter_id, adapter_info, port_id, link_status, speed_gbps, pdata, ndf):
    """canonical storage.infiniband[] entry 생성 (전 채널 통일 shape — EXTERNAL-CONTRACTS §2)."""
    node_guid = ndf.get('node_guid') if isinstance(ndf, dict) else None
    port_guid = ndf.get('port_guid') if isinstance(ndf, dict) else None
    if isinstance(pdata, dict):
        ib_raw = pdata.get('InfiniBand')
        ibobj = ib_raw if isinstance(ib_raw, dict) else {}  # Round 3 #2: 비-dict InfiniBand 방어
        if not node_guid:
            arr = _as_list(ibobj.get('AssociatedNodeGUIDs'))
            node_guid = arr[0] if arr else None
        if not port_guid:
            arr = _as_list(ibobj.get('AssociatedPortGUIDs'))  # Round 4 #0: 비-list 방어 (위 AssociatedNodeGUIDs 가드와 일관)
            port_guid = arr[0] if arr else None
    return {
        'adapter':       adapter_id,
        'adapter_model': adapter_info.get('model'),
        'port':          port_id,
        'node_guid':     node_guid,
        'port_guid':     port_guid,
        'link_status':   link_status,
        'rate':          None,
        'rate_gbps':     speed_gbps,
        'vendor':        adapter_info.get('manufacturer'),
        'firmware':      adapter_info.get('firmware_version'),
        'source':        'redfish',
    }


def gather_network_adapters_chassis(bmc_ip, chassis_uri, username, password, timeout,
                                    verify_ssl, system_uri=None):
    """NetworkAdapters 수집 + FC HBA / InfiniBand 분류.

    NetworkAdapters         → adapters[] (NIC 카드 모델/firmware)
    Ports/NetworkPorts      → ports[]    (port-level link/speed)
    NetworkDeviceFunctions  → 식별 (FC WWPN/WWNN, IB Node/Port GUID)

    **수집 경로 2종 (cycle 2026-08-03 — 사이트 Dell R630 8대 400 사고 근본원인)**:
      1순위 `Chassis/{id}/NetworkAdapters`  — DMTF 현행 표준 위치
      2순위 `Systems/{id}/NetworkAdapters`  — 일부 펌웨어의 구현 위치

    배경: 펌웨어 세대에 따라 이 리소스의 부모가 다르다. 사이트 PowerEdge R630(13G / iDRAC8
    fw 2.7x~2.8x)은 Chassis 경로에 **HTTP 400** 을 주는데, 벤더 공식 API 가이드는 같은
    리소스를 `Systems/{id}/NetworkAdapters` 로 문서화한다. 즉 400 은 "장비 미지원"이 아니라
    **우리가 그 펌웨어에 없는 경로를 물어본 것**이었다. 1순위만 시도하던 구 코드는 이런
    장비에서 NIC 카드 정보를 영구히 못 받았다(adapters[] 항상 빈 배열).

    source (rule 96 R1-A):
      - Dell iDRAC8 Redfish API Guide 2.70.70.70 — NetworkAdapter Collection / Instance
        = `/redfish/v1/Systems/System.Embedded.1/NetworkAdapters[/<id>]`
      - 내부 실측: `tests/fixtures/redfish/real_dell_r740`(14G/iDRAC9) 는 Chassis 경로 200
        → 세대별 위치 차이 확인

    Additive (rule 92 R2): 1순위가 200 인 장비는 2순위를 아예 시도하지 않아 동작 100% 불변.
    vendor 분기 없음 — 경로 후보 순회는 vendor-agnostic (rule 12 R1).

    분류 정본 (DMTF — cycle 2026-05-29 fix, EXTERNAL-CONTRACTS §1/§2):
      - FC : Port.PortProtocol ∈ {FC,FCP,FCoE} 또는 NDF.NetDevFuncType=FibreChannel(OverEthernet)
      - IB : Port.LinkNetworkTechnology=='InfiniBand' 또는 NDF.NetworkDeviceTechnology=='InfiniBand'
      - 구 코드의 PortType('fibrechannel'/'infiniband') 분류는 dead-code (PortType enum 에
        FC/IB 값 없음 → 실장비 영원히 미매치). 본 cycle 에서 protocol/technology 기반으로 정정.

    WWPN/WWNN/GUID 는 NetworkDeviceFunction 에서 추출 (Port 아님). Port 가 없는 FC/IB NDF 도
    식별만으로 emit. 일부 vendor (Cisco CIMC 등) 미지원 → 빈 결과 graceful degradation.
    """
    out = {'adapters': [], 'ports': [], 'fc_hbas': [], 'infiniband': []}
    errors = []
    if not chassis_uri and not system_uri:
        return out, errors

    candidates = []
    if chassis_uri:
        candidates.append(_p(chassis_uri) + '/NetworkAdapters')
    if system_uri:
        alt = _p(system_uri) + '/NetworkAdapters'
        if alt not in candidates:
            candidates.append(alt)

    coll, first_fail = None, None
    for base in candidates:
        st, data, err = _get(bmc_ip, base, username, password, timeout, verify_ssl)
        if not err and st == 200:
            coll = data
            break
        if first_fail is None:
            # 표준(1순위) 경로의 실패 시그널을 보고 대상으로 삼는다 — message 문자열이
            # 기존과 동일해야 404-only 미지원 분류(_is_404_only_error)가 불변.
            first_fail = (err or st, _extended_info(data))
    if coll is None:
        sig, ext = first_fail
        detail = 'tried: ' + ' / '.join(candidates)
        if ext:
            detail += ' | ' + ext
        errors.append(_err('network_adapters',
                           f'NetworkAdapters 미지원 또는 실패: {sig}', detail))
        return out, errors

    for member in _dicts(_safe(coll, 'Members')):  # Round 4: 비-list/비-dict Members 방어
        adp_uri = _safe(member, '@odata.id')
        if not adp_uri:
            continue
        st2, adata, aerr = _get(bmc_ip, _p(adp_uri), username, password, timeout, verify_ssl)
        if aerr or st2 != 200:
            errors.append(_err('network_adapters', f'NetworkAdapter {adp_uri} 실패: {aerr or st2}'))
            continue

        adapter_id = _safe(adata, 'Id')
        # FirmwareVersion: Controllers[0].FirmwarePackageVersion 또는 root
        fw_ver = None
        ctrls = _safe(adata, 'Controllers', default=[]) or []
        if ctrls and isinstance(ctrls, list):
            fw_ver = _safe(ctrls[0], 'FirmwarePackageVersion')
            # CSUS-R16 (2026-06-15 실미러 검수): FirmwarePackageVersion 부재 펌웨어(HPE CSUS NetworkAdapter)
            # 는 어댑터 펌웨어를 Controllers[0].Links.PCIeDevices[] 가 가리키는 PCIeDevice.FirmwareVersion
            # 에 둔다(실측 Mellanox MCX631102="26.46.3048..."). 링크추적 fallback (Additive — 표준 위치
            # 보유 vendor 불변, PCIeDevice 도 부재 시 None 유지).
            if not fw_ver:
                for _pd in _dicts(_safe(ctrls[0], 'Links', 'PCIeDevices')):
                    _pd_uri = _safe(_pd, '@odata.id')
                    if not _pd_uri:
                        continue
                    _ps, _pdata, _pe = _get(bmc_ip, _p(_pd_uri), username, password, timeout, verify_ssl)
                    if _ps == 200 and isinstance(_pdata, dict):
                        fw_ver = _safe(_pdata, 'FirmwareVersion')
                        if fw_ver:
                            break
        # 빈 placeholder NetworkAdapter 필터:
        # 일부 BMC (실측 Lenovo XCC SR650 V2)는 PCIe slot 자체를 NetworkAdapters 컬렉션에
        # 빈 entry 로 노출. Controllers[0].ControllerCapabilities.NetworkPortCount=0 또는
        # manufacturer/model 모두 빈 문자열이면 실제 NIC 가 아니므로 skip.
        # cycle 2026-06-14 (DELL R740 실 미러 검수 NET-1): port_count 를 Controllers[0] 하나가
        # 아니라 *모든* Controller 의 NetworkPortCount 합으로 산출. Dell rNDC(예: 'BRCM GbE 4P
        # 5720-t rNDC')는 NetworkAdapter 1개가 Controller 2개(각 NetworkPortCount=2)를 노출 —
        # Controllers[0] 만 읽으면 4포트 카드가 2로 과소 집계됨(실 미러 NetworkPorts 멤버=4 와 불일치).
        # 단일 Controller 카드는 합=그 값 → 결과 불변(Additive). NetworkPortCount=DMTF 컨트롤러별 포트 수.
        port_count = 0
        if ctrls and isinstance(ctrls, list):
            for _ctrl in ctrls:
                _caps = _safe(_ctrl, 'ControllerCapabilities') or {}
                port_count += _safe_int(_safe(_caps, 'NetworkPortCount'), default=0) or 0
        mfr = _str(_safe(adata, 'Manufacturer')).strip()
        model = _str(_safe(adata, 'Model')).strip()
        if port_count == 0 and not mfr and not model:
            continue
        # 2026-04-29 fix B93: HPE iLO NetworkAdapter는 mac/link/speed 가 NetworkAdapter root에 없고
        # NetworkPorts/Ports collection에만 존재. adapter level에 fold-in (첫 번째 활성 port의 메타).
        # Dell/Lenovo는 NetworkAdapter root에 정보 있어 그대로 보존.
        adapter_info = {
            'id':               adapter_id,
            'name':             _safe(adata, 'Name'),
            'manufacturer':     mfr or None,
            'model':            model or None,
            'part_number':      _safe(adata, 'PartNumber') or None,
            'serial_number':    _safe(adata, 'SerialNumber') or None,
            'firmware_version': fw_ver or None,
            'mac':              None,  # ports fold-in으로 채워짐 (B93)
            'link_status':      'unknown',  # 동일 (B93)
            'speed_mbps':       None,
            'port_count':       port_count,
        }
        out['adapters'].append(adapter_info)
        adapter_idx = len(out['adapters']) - 1
        _ports_before = len(out['ports'])  # CSUS-R6: port_count fallback 기준점

        # NetworkDeviceFunctions — FC WWPN/WWNN + IB GUID 식별 (cycle 2026-05-29).
        ndfs = _fetch_ndf_index(bmc_ip, adata, username, password, timeout, verify_ssl)
        ndf_by_port = {n['port_uri']: i for i, n in enumerate(ndfs) if n.get('port_uri')}
        # CSUS-FC1 (2026-06-15 실미러 검수): NDF.Links.PhysicalPortAssignment 부재 펌웨어
        # (HPE CSUS RMC — NDF 가 Links.PCIeFunction 만 노출)에서 NDF↔Port 매칭이 port_uri 로
        # 안 되면 ID 일치(NDF.Id == Port.Id, 예: PCIeCard10Port1)로 fallback. 그래야 FC WWPN/WWNN
        # (NDF.FibreChannel 에 존재)이 port 에 join 돼 fc_hbas[].wwpn 이 소실되지 않는다.
        ndf_by_id = {n['id']: i for i, n in enumerate(ndfs) if n.get('id')}
        ndf_matched = set()
        # cycle 2026-08-03: port 순회에서 모은 (PortProtocol, link_tech, raw port) 컨텍스트.
        # Port 에 join 되지 않은 NDF 를 분류할 때 '부모 포트' 신호를 물려주는 데 쓴다 (아래 참조).
        port_ctx_by_id = {}

        # NetworkPorts (Redfish 1.5 이전) 또는 Ports (1.6+)
        ports_link = (_safe(adata, 'NetworkPorts', '@odata.id')
                      or _safe(adata, 'Ports', '@odata.id'))
        if ports_link:
            st3, pcoll, perr = _get(bmc_ip, _p(ports_link), username, password, timeout, verify_ssl)
            if perr or st3 != 200:
                errors.append(_err('network_adapters',
                                   f'Ports {ports_link} 실패: {perr or st3}'))
            else:
                for pmember in _dicts(_safe(pcoll, 'Members')):  # Round 5: 비-list/dict 방어
                    p_uri = _safe(pmember, '@odata.id')
                    if not p_uri:
                        continue
                    st4, pdata, perr2 = _get(bmc_ip, _p(p_uri), username, password, timeout, verify_ssl)
                    if perr2 or st4 != 200:
                        continue
                    # 속도: 신 CurrentSpeedGbps(Gbps) 우선 > 구 CurrentLinkSpeedMbps/1000 (Round 17 #3)
                    speed_gbps, speed_mbps = _normalize_port_speed(pdata)
                    assoc = _safe(pdata, 'AssociatedNetworkAddresses', default=[]) or []
                    if not isinstance(assoc, list):  # rule 95 R1 #2: 비-list 방어 (Round 2 #14)
                        assoc = []
                    # 신 Port resource(1.6+, `Ports`)는 구 NetworkPort 의 top-level
                    # AssociatedNetworkAddresses 대신 Ethernet.AssociatedMACAddresses /
                    # FibreChannel.AssociatedWWNs 에 주소를 둔다 (실측 HPE DL380 Gen12 iLO7:
                    # Port.Ethernet.AssociatedMACAddresses=["14:23:f3:b0:7a:40"], top-level
                    # AssociatedNetworkAddresses 부재 → 기존엔 adapter.mac / port.associated_address
                    # 전부 null 유실). 구 필드 우선(기존 동작·F48 테스트 보존) + 신 필드 fallback (Additive).
                    if not assoc:
                        eth_macs = _safe(pdata, 'Ethernet', 'AssociatedMACAddresses')
                        if isinstance(eth_macs, list) and eth_macs:
                            assoc = eth_macs
                        else:
                            # CSUS-FC2 (2026-06-15 실미러 검수): Port.FibreChannel 의 WWN 필드명이
                            # 펌웨어별로 AssociatedWWNs / AssociatedWorldWideNames 로 갈린다 (HPE CSUS
                            # RMC 는 후자). 둘 다 읽어 WWPN 소실 차단 (DMTF Port.FibreChannel).
                            fc_wwns = (_safe(pdata, 'FibreChannel', 'AssociatedWWNs')
                                       or _safe(pdata, 'FibreChannel', 'AssociatedWorldWideNames'))
                            if isinstance(fc_wwns, list) and fc_wwns:
                                assoc = fc_wwns
                    # NET-2-1 (2026-06-15): MAC/WWN 을 소문자 정규화해 adapters[].mac /
                    # fc_hbas[].wwpn(_normalize_wwn 소문자) 와 case 일관성 확보. HPE iLO7 은 FC
                    # WWPN 을 Ethernet.AssociatedMACAddresses 에 대문자로 노출 → 정규화 없이는 같은
                    # 주소가 associated_address(대문자) vs wwpn(소문자) 로 갈려 호출자 join mismatch.
                    # raw 가 이미 colon-grouped hex 라 .lower() 로 wwpn 정규화 결과와 동일.
                    primary_addr = assoc[0] if assoc else None
                    if isinstance(primary_addr, str):
                        primary_addr = primary_addr.lower()
                    raw_port_type = _safe(pdata, 'PortType') or ''
                    port_protocol = _safe(pdata, 'PortProtocol')
                    link_tech = (_safe(pdata, 'LinkNetworkTechnology')
                                 or _safe(pdata, 'ActiveLinkTechnology'))
                    # 2026-04-29 fix B13: ports의 link_status도 동일 enum 정규화.
                    normalized_link = _normalize_link_status(_safe(pdata, 'LinkStatus'))
                    port_id = _safe(pdata, 'Id')
                    if port_id:
                        port_ctx_by_id[port_id] = (port_protocol, link_tech, pdata)

                    # NDF join (식별 정보) — port_uri(PhysicalPortAssignment) 우선, 부재 시 ID 매칭(CSUS-FC1)
                    ndf_idx = ndf_by_port.get(_p(p_uri)) if p_uri else None
                    if ndf_idx is None and port_id:
                        ndf_idx = ndf_by_id.get(port_id)
                    ndf = ndfs[ndf_idx] if ndf_idx is not None else None
                    if ndf_idx is not None:
                        ndf_matched.add(ndf_idx)

                    cls = _classify_port_protocol(port_protocol, link_tech, ndf, pdata)

                    # CSUS-R13 (2026-06-15 실미러 검수): FC 포트의 associated_address 는 port WWN(WWPN)
                    # 이어야 한다. Port.FibreChannel.AssociatedWorldWideNames 가 [WWNN, WWPN] 다중 entry
                    # 면 assoc[0]=WWNN 오취득 → NDF.WWPN(=fc_hbas[].wwpn 과 동일)으로 교정해 일관성 확보.
                    # (Ethernet/IB 포트는 기존 primary_addr 유지 — ndf.wwpn 없음)
                    if cls in ('FibreChannel', 'FCoE') and isinstance(ndf, dict) and ndf.get('wwpn'):
                        primary_addr = ndf['wwpn']

                    port_info = {
                        'adapter_id':              adapter_id,
                        'adapter_model':           adapter_info['model'],
                        'port_id':                 port_id,
                        'name':                    _safe(pdata, 'Name'),
                        'physical_port_number':    _safe(pdata, 'PhysicalPortNumber'),
                        'link_status':             normalized_link,
                        'link_state':              _safe(pdata, 'LinkState'),
                        'current_link_speed_mbps': speed_mbps,
                        # port_type = 분류 결과 (FibreChannel/InfiniBand/Ethernet). 구 raw PortType
                        # (Upstream 등 — FC/IB 무관) 대체. 미분류 시 raw 보존.
                        'port_type':               cls or (raw_port_type or None),
                        'health':                  _safe(pdata, 'Status', 'Health'),
                        'associated_address':      primary_addr,
                    }
                    out['ports'].append(port_info)
                    # 2026-04-29 fix B93: adapter level에 ports의 첫 active 메타 fold-in.
                    # FC/IB 포트의 WWPN/GUID 는 NIC mac 이 아니므로 fold-in 제외.
                    cur = out['adapters'][adapter_idx]
                    if cur.get('mac') is None and primary_addr and cls not in ('FibreChannel', 'FCoE', 'InfiniBand'):
                        cur['mac'] = primary_addr
                    if cur.get('link_status') == 'unknown' or (cur.get('link_status') != 'up' and normalized_link == 'up'):
                        cur['link_status'] = normalized_link
                    if cur.get('speed_mbps') is None and speed_mbps:
                        cur['speed_mbps'] = speed_mbps

                    if cls in ('FibreChannel', 'FCoE'):
                        out['fc_hbas'].append(_make_fc_hba(
                            adapter_id, adapter_info, port_id, cls,
                            normalized_link, speed_gbps, primary_addr, ndf))
                    elif cls == 'InfiniBand':
                        out['infiniband'].append(_make_ib_port(
                            adapter_id, adapter_info, port_id,
                            normalized_link, speed_gbps, pdata, ndf))

        # Port 가 없거나 Port 에 join 되지 않은 FC/IB NetworkDeviceFunction 도 식별만으로 emit.
        # (port-less HBA / 구 펌웨어 — link_status/speed 는 미상)
        for i, ndf in enumerate(ndfs):
            if i in ndf_matched:
                continue
            # cycle 2026-08-03 (사이트 Dell R630 실측): join 실패한 NDF 도 '부모 포트' 신호를
            # 물려받아 분류한다. Dell 은 NDF Id 를 `<PortId>-<funcIdx>` 로 매기는데(예: 포트
            # NIC.Integrated.1-1 ↔ NDF NIC.Integrated.1-1-1) port_uri/ID-동일 매칭이 둘 다
            # 빗나가 orphan 이 된다. 컨텍스트 없이 분류하면 FCoE 지원 CNA 의 이더넷 기능이
            # (MAC 파생 WWN 때문에) FC HBA 로 잡힌다 — 같은 NIC 이 펌웨어 버전에 따라 갈리는
            # 원인이었다(실측: NIC fw 15.20.13 은 WWN 노출, 15.15.08 은 미노출).
            # 접두 매칭은 구분자 '-' 를 요구해 `...1-1` 이 `...1-10-1` 을 삼키지 않는다.
            nid = _str(ndf.get('id'))
            parent = None
            for _pid, _ctx in port_ctx_by_id.items():
                if nid.startswith(_pid + '-'):
                    parent = _ctx
                    break
            if parent is not None:
                cls = _classify_port_protocol(parent[0], parent[1], ndf, parent[2])
            else:
                cls = _classify_port_protocol(None, None, ndf, None)
            if cls in ('FibreChannel', 'FCoE'):
                out['fc_hbas'].append(_make_fc_hba(
                    adapter_id, adapter_info, ndf.get('id'), cls,
                    'unknown', None, None, ndf))
            elif cls == 'InfiniBand':
                out['infiniband'].append(_make_ib_port(
                    adapter_id, adapter_info, ndf.get('id'),
                    'unknown', None, None, ndf))

        # CSUS-R6 (2026-06-15 실미러 검수): ControllerCapabilities.NetworkPortCount 부재 펌웨어
        # (HPE CSUS NetworkAdapter — Controllers 에 ControllerCapabilities 없음)에서 port_count=0
        # 인데 실제 Ports 컬렉션은 2포트 → 잘못된 0. 이 어댑터에서 실제 수집된 ports 수로 보정.
        # NetworkPortCount 보유 vendor(Dell rNDC 등)는 port_count>0 라 미발동 (Additive 회귀안전).
        _ports_collected = len(out['ports']) - _ports_before
        if out['adapters'][adapter_idx].get('port_count') in (0, None) and _ports_collected > 0:
            out['adapters'][adapter_idx]['port_count'] = _ports_collected

    return out, errors


def gather_firmware(bmc_ip, username, password, timeout, verify_ssl):
    """
    UpdateService/FirmwareInventory — 벤더 공통
    Members 에 상세 필드 없으면 개별 URI 조회 (Dell/HPE/Supermicro 모두 해당)
    """
    path = 'UpdateService/FirmwareInventory'
    st, coll, err = _get(bmc_ip, path, username, password, timeout, verify_ssl)
    errors = []
    if err or st != 200:
        errors.append(_err('firmware', f'FirmwareInventory 실패: {err or st}'))
        return [], errors

    fw_list = []
    # cycle 2026-06-14 (DELL R740 실 미러 검수 FW-1): Dell iDRAC FirmwareInventory 는 동일
    # 구동 펌웨어를 'Current-<SoftwareId>-<ver>__<FQDD>' 와 'Installed-<...>__<FQDD>' 두 멤버로
    # 중복 노출(같은 SoftwareId/Version/Name). dedup 없으면 호출자가 firmware 를 2배로 카운트
    # (R740 실측 51 vs distinct 32). status-prefix 를 떼어낸 key(=<SoftwareId>-<ver>__<FQDD>)로
    # dedup — 서로 다른 물리 컴포넌트(FC.Slot.1-1 vs FC.Slot.1-2)는 '__<FQDD>' 가 달라 보존,
    # prefix 없는 Id(HPE 숫자/Lenovo) 는 자기 자신으로 정규화돼 dedup 무영향(Additive).
    # source: Dell iDRAC FirmwareInventory (Members Id prefix 규약), R740 실 미러.
    seen_fw_keys = set()                                                       # nosec rule12-r1
    for member in _capped(_safe(coll, 'Members') or [], 'firmware', errors):
        member_uri = _safe(member, '@odata.id')
        # Members 에 Name/Version 없으면 개별 URI 조회 (벤더 공통)
        if not _safe(member, 'Name') and member_uri:
            st2, fw_data, ferr = _get(bmc_ip, _p(member_uri), username, password, timeout, verify_ssl)
            if not ferr and st2 == 200:
                member = fw_data
        fw_id = _safe(member, 'Id') or (member_uri.rstrip('/').split('/')[-1]  # rstrip: 후행 슬래시 → 빈 id 방지 (Round 1 #13)
                                        if isinstance(member_uri, str) and member_uri else None)
        # Q-14: Dell Previous- 항목 스킵 (비활성 이전 버전)
        if fw_id and isinstance(fw_id, str) and fw_id.startswith('Previous-'):
            continue
        # 2026-04-29 fix B43 (재확인 cycle 2026-06-15, Lenovo SR650 V4 실미러 검수): pending
        # firmware (BMC-Primary-Pending / UEFI-Pending) 는 ID 에 'Pending' 포함, version 부재가
        # 정상(staged 업데이트). XCC1 은 Version=null, XCC3(V4) 은 Version="" 로 노출 — 아래 Cisco
        # 빈 슬롯 노이즈 필터('N/A'/''/'NA')가 pending 을 삼키지 않도록 먼저 식별한다.
        is_pending = bool(fw_id and isinstance(fw_id, str) and 'pending' in fw_id.lower())
        # 2026-04-29 cisco-critical-review: Cisco CIMC 의 "N/A" 빈 슬롯 (slot-1, slot-2
        # 등 PCIe 미장착 슬롯) 노이즈 필터. Version 이 "N/A"/""/"NA" 면 firmware 컴포넌트가
        # 부재 — 호출자에게 노이즈로 전달되지 않도록 skip (기존 키 유지, list 길이만 정확).
        # 단 pending 엔트리는 예외: 드롭하면 "업데이트 staged" 신호 유실(lenovo_baseline.json 이
        # pending 엔트리 보존 — 정책: pending=true + version=null 은 정상). version="" → null 통일.
        ver = _safe(member, 'Version')
        if isinstance(ver, str) and ver.strip().upper() in ('N/A', 'NA', ''):
            if not is_pending:
                continue
            ver = None
        # Q-13: SoftwareId가 문자열 "null"이면 Python None으로 변환
        component = _safe(member, 'SoftwareId')
        if isinstance(component, str) and component.lower() == 'null':
            component = None
        # FW-1 dedup: status-prefix 제거 key 로 Current-/Installed- 동일 펌웨어 중복 제거.
        # prefix 없는 Id 는 key=fw_id(고유) → dedup 무영향. Previous- 는 위에서 이미 skip.
        _dedup_key = fw_id
        if isinstance(fw_id, str):
            for _pref in ('Installed-', 'Current-', 'Available-', 'Rollback-'):  # nosec rule12-r1
                if fw_id.startswith(_pref):
                    _dedup_key = fw_id[len(_pref):]
                    break
        if _dedup_key in seen_fw_keys:
            continue
        seen_fw_keys.add(_dedup_key)
        fw_list.append({
            'id':         fw_id,
            'name':       _safe(member, 'Name'),
            'version':    ver,
            'updateable': _safe(member, 'Updateable'),
            'component':  component or fw_id,
            'pending':    is_pending,
        })
    return fw_list, errors


def _telemetry_total_power(bmc_ip, chassis_uri, username, password, timeout, verify_ssl):
    """TelemetryService MetricReports 에서 이 chassis 의 TotalPowerConsumedWatts (장비 권위 소비전력).

    CSUS-R14 (2026-06-15 실미러 검수): HPE CSUS 는 /Power·/EnvironmentMetrics 가 없어 표준 소비전력
    경로가 없고, 장비가 'TotalPowerConsumedWatts' 를 TelemetryService MetricReport(Id 에 chassis id
    내장: Chassis<id>_TotalPowerConsumedWatts)로 노출한다. MetricReports 컬렉션을 순회해 이 chassis 의
    리포트를 찾아 MetricValue 반환. PSU InputPowerWatts 합(AC 입력, ~20% 높음)보다 장비 자신의 '소비'
    정의(591.5W)에 충실. MetricValue 는 문자열("591.5") → _safe_num 으로 파싱.

    source (rule 96 R1-A): DMTF DSP0266 TelemetryService/MetricReport (MetricValues[].MetricId/MetricValue).
    Returns: int | None
    """
    cid = _str(chassis_uri).rstrip('/').rsplit('/', 1)[-1] if chassis_uri else ''
    if not cid:
        return None
    st, coll, err = _get(bmc_ip, 'TelemetryService/MetricReports', username, password, timeout, verify_ssl)
    if err or st != 200:
        return None
    cid_l = cid.lower()
    for m in _capped(_dicts(_safe(coll, 'Members')), 'power', None):
        u = _safe(m, '@odata.id')
        if not u or not isinstance(u, str):
            continue
        ul = u.lower()
        if cid_l not in ul or 'totalpowerconsumed' not in ul:
            continue
        st2, rep, _e = _get(bmc_ip, _p(u), username, password, timeout, verify_ssl)
        if st2 != 200 or not isinstance(rep, dict):
            continue
        for mv in _dicts(_safe(rep, 'MetricValues')):
            if _str(_safe(mv, 'MetricId')).strip().lower() == 'totalpowerconsumedwatts':
                num = _safe_num(_safe(mv, 'MetricValue'))  # "591.5" → float → int
                if num is not None:
                    return _safe_int(num)
    return None


def _gather_power_subsystem(bmc_ip, chassis_uri, username, password, timeout, verify_ssl):
    """DMTF 2020.4 (Redfish 1.13+) PowerSubsystem fallback parser.

    cycle 2026-05-01: 신 펌웨어 (HPE iLO 6 / Lenovo XCC2-3 / Dell iDRAC9 5.x+ /
    Supermicro X14+) 가 /Power 대신 /PowerSubsystem 응답. 기본 PSU 정보는 공통.
    PowerControl 같은 system-level metric 은 PowerSubsystem 에 직접 없고
    EnvironmentMetrics 로 분리됨 — 본 fallback 은 PSU info 만 매핑 (호출자 envelope
    유지). PowerControl 미응답이면 None.
    """
    errors = []
    ps_path = _p(chassis_uri) + '/PowerSubsystem'
    st, ps_data, perr = _get(bmc_ip, ps_path, username, password, timeout, verify_ssl)
    if perr or st != 200:
        # PowerSubsystem 도 없으면 진짜 미지원 — 호출자가 not_supported 분류
        return {}, [_err('power', f'PowerSubsystem 미지원: {perr or st}')] if st != 404 else []

    # PowerSubsystem.PowerSupplies 컬렉션 fetch
    psu_link = _safe(ps_data, 'PowerSupplies', '@odata.id')
    psus = []
    psu_input_total = 0          # CSUS-R10: PSU 입력전력 합 (소비전력 fallback)
    psu_input_seen = False
    if psu_link:
        st_c, coll, _err_c = _get(bmc_ip, _p(psu_link), username, password, timeout, verify_ssl)
        if st_c == 200:
            for member in _capped(_dicts(_safe(coll, 'Members')), 'power', errors):  # Round 4 비-list 방어 + cycle 2026-06-09 DoS 상한 (sibling 일관)
                m_uri = _safe(member, '@odata.id')
                if not m_uri:
                    continue
                st_m, mdata, _err_m = _get(bmc_ip, _p(m_uri), username, password, timeout, verify_ssl)
                if st_m != 200:
                    continue
                psus.append({
                    'name':             _safe(mdata, 'Name'),
                    'model':            _safe(mdata, 'Model'),
                    'serial':           _safe(mdata, 'SerialNumber'),
                    'manufacturer':     _safe(mdata, 'Manufacturer'),
                    # 2026-06-16 감사 G4 (Additive): CSUS PSU raw PartNumber=CSU2400AP-3-500 미수집이었음.
                    'part_number':      _safe(mdata, 'PartNumber'),
                    'power_capacity_w': _safe_int(_safe(mdata, 'PowerCapacityWatts')),
                    # CSUS-R9 (2026-06-15 실미러 검수): HPE CSUS PSU 는 FirmwareVersion 부재 +
                    # DMTF PowerSupply.Version("Release -0005")에 버전 → Version fallback (Additive).
                    'firmware_version': _safe(mdata, 'FirmwareVersion') or _safe(mdata, 'Version'),
                    'health':           _safe(mdata, 'Status', 'Health'),
                    'state':            _safe(mdata, 'Status', 'State'),
                })
                # CSUS-R10: PSU.Metrics.InputPowerWatts.Reading 합산 — chassis 에 /Power·
                # /EnvironmentMetrics 가 없어 소비전력이 PSU Metrics 에만 있는 환경(HPE CSUS) 대비.
                metrics_link = _safe(mdata, 'Metrics', '@odata.id')
                if metrics_link:
                    st_mm, mm, _e_mm = _get(bmc_ip, _p(metrics_link), username, password, timeout, verify_ssl)
                    if st_mm == 200 and isinstance(mm, dict):
                        ipw = _safe_int(_safe(mm, 'InputPowerWatts', 'Reading'))
                        if ipw is not None:
                            psu_input_total += ipw
                            psu_input_seen = True

    # PowerControl 은 PowerSubsystem 표준에 없음 — chassis-level 합산 또는 None
    pc_capacity = None
    psu_caps = [p['power_capacity_w'] for p in psus if p['power_capacity_w'] is not None]
    if psu_caps:
        pc_capacity = sum(psu_caps)
    power_control = {
        'power_consumed_watts':  None,
        'power_capacity_watts':  pc_capacity,
        'interval_in_min':       None,
        'min_consumed_watts':    None,
        'avg_consumed_watts':    None,
        'max_consumed_watts':    None,
    } if psus else None

    # F05 (cycle 2026-05-01): DMTF 2020.4 EnvironmentMetrics fallback —
    # PowerSubsystem 신 schema는 system-level metric을 EnvironmentMetrics 로 분리.
    # source: redfish.dmtf.org/schemas/v1/EnvironmentMetrics.v1_3_0.json (2020.4)
    # PowerWatts.Reading / ReadingRangeMin/Max 가 PowerControl 대응.
    if power_control is not None:
        em_path = _p(chassis_uri) + '/EnvironmentMetrics'
        st_em, em_data, _err_em = _get(bmc_ip, em_path, username, password, timeout, verify_ssl)
        if st_em == 200 and isinstance(em_data, dict):
            pw = em_data.get('PowerWatts') if isinstance(em_data.get('PowerWatts'), dict) else None
            if pw:
                pc_consumed = _safe_int(pw.get('Reading'))
                pc_min = _safe_int(pw.get('ReadingRangeMin'))
                pc_max = _safe_int(pw.get('ReadingRangeMax'))
                if pc_consumed is not None:
                    power_control['power_consumed_watts'] = pc_consumed
                if pc_min is not None:
                    power_control['min_consumed_watts'] = pc_min
                if pc_max is not None:
                    power_control['max_consumed_watts'] = pc_max
        # interval_in_min / avg_consumed_watts: EnvironmentMetrics 표준에 없음 — None 유지
        # CSUS-R14 (2026-06-15 실미러 검수): EnvironmentMetrics 부재 시 장비 자신의 권위 소비전력
        # (TelemetryService TotalPowerConsumedWatts, 591.5W)을 우선 사용 — PSU 입력전력 합(731W,
        # AC 입력이라 ~24% 높음)보다 장비의 '소비' 정의에 충실. 표준 경로(EnvironmentMetrics) 보유
        # vendor 는 위에서 이미 채워져 미발동.
        if power_control['power_consumed_watts'] is None:
            tpc = _telemetry_total_power(bmc_ip, chassis_uri, username, password, timeout, verify_ssl)
            if tpc is not None:
                power_control['power_consumed_watts'] = tpc
        # CSUS-R10: TelemetryService 도 없으면 PSU 입력전력 합으로 마지막 fallback (AC 입력 — 근사값).
        if power_control['power_consumed_watts'] is None and psu_input_seen:
            power_control['power_consumed_watts'] = psu_input_total

    return {'power_supplies': psus, 'power_control': power_control}, errors


def _merge_power_dual(legacy_result, subsystem_result):    # nosec rule12-r1
    """cycle 2026-05-07 M-I2: Power (deprecated) + PowerSubsystem dual-emit dedup.

    DSP0268 v1.13+ 이전/이후 펌웨어가 dual emit 하는 환경 (iDRAC9 5.x / iLO5-6 /
    XCC3 / Supermicro X12-X14) 에서 PowerSupplies 중복 제거.

    Strategy (Round 15 정정): serial 이 있으면 serial 로 dedup (같은 PSU 의 legacy/
    subsystem 이중 emit 을 name 차이와 무관하게 1회로). serial 이 없으면 (name, model)
    로 dedup. PowerControl 은 legacy 우선 (PowerSubsystem
    표준에는 system-level metric 없고 EnvironmentMetrics 로 분리됨 — legacy 가
    더 풍부).

    rule 92 R2: 입력 dict shape 유지 — `power_supplies` + `power_control` 키만.
    호출자 envelope 영향 0.

    Returns: merged dict (power_supplies + power_control).
    """
    legacy_psus = (legacy_result or {}).get('power_supplies') or []
    sub_psus = (subsystem_result or {}).get('power_supplies') or []

    seen = set()
    merged_psus = []
    for psu in legacy_psus + sub_psus:
        if not isinstance(psu, dict):
            continue
        # dedup key (Round 15 정정): serial 이 PSU 고유 식별자 — serial 있으면 serial 로만
        # dedup (legacy/subsystem 가 같은 PSU 를 다른 name 으로 emit 해도 1회로 합침). serial
        # 없으면 (name, model) — serial 부재 시 name 다른 별개 PSU 를 잘못 합치지 않도록.
        _ps_serial = psu.get('serial') or ''
        if _ps_serial:
            key = ('serial', _ps_serial)
        else:
            key = ('name_model', psu.get('name') or '', psu.get('model') or '')
        if key in seen:
            continue
        seen.add(key)
        merged_psus.append(psu)

    # PowerControl: legacy 우선 (system-level metric 풍부), 없으면 subsystem
    pc = (legacy_result or {}).get('power_control') or (subsystem_result or {}).get('power_control')
    return {'power_supplies': merged_psus, 'power_control': pc}


def gather_power(bmc_ip, chassis_uri, username, password, timeout, verify_ssl):
    """Chassis/{id}/Power — PSU 정보. chassis_uri는 detect_vendor()에서 전달.

    cycle 2026-05-01: /Power 404 시 /PowerSubsystem fallback (DMTF 2020.4 신 schema).
    Storage SimpleStorage fallback 패턴 따름 (gather_storage 참조).

    cycle 2026-05-07 M-I2: dual-emit dedup helper (_merge_power_dual) 추가 (Additive).
    현재 dispatcher 는 404 fallback only — dual emit 펌웨어 (iDRAC9 5.x / iLO5-6
    등) 의 PSU 중복 처리는 향후 adapter capability `power_strategy=dual` 활성화
    시 본 helper 호출 (현 cycle 은 사이트 검증 4 vendor 영향 0 위해 wire 보류).
    """
    errors = []
    if not chassis_uri:
        errors.append(_err('power', 'chassis_uri 없음 (detect_vendor 에서 Chassis 미발견)'))
        return {}, errors

    power_path = _p(chassis_uri) + '/Power'
    st, pdata, perr = _get(bmc_ip, power_path, username, password, timeout, verify_ssl)

    # cycle 2026-05-01: 404 = 신 펌웨어 가능 → PowerSubsystem fallback
    if st == 404:
        return _gather_power_subsystem(bmc_ip, chassis_uri, username, password, timeout, verify_ssl)

    if perr or st != 200:
        errors.append(_err('power', f'Power 정보 실패: {perr or st}'))
        return {}, errors

    # 2026-04-29 cisco-critical-review: PSU 정격 (power_capacity_w) fallback —
    # Cisco CIMC / 일부 vendor 는 PowerSupplies[*].PowerCapacityWatts 를 응답하지 않고
    # InputRanges[0].OutputWattage 에 PSU 정격을 둔다. envelope 키는 그대로,
    # null 이던 값을 채운다.
    psus = []
    for psu in _dicts(_safe(pdata, 'PowerSupplies')):  # Round 5 #4: 비-list/dict 방어
        psu_capacity = _safe_int(_safe(psu, 'PowerCapacityWatts'))  # Round 2: watt int 통일 (sum 안전 + 타입 일관)
        if psu_capacity is None:
            ranges = _safe(psu, 'InputRanges') or []
            if isinstance(ranges, list) and ranges and isinstance(ranges[0], dict):
                psu_capacity = _safe_int(ranges[0].get('OutputWattage'))
        psus.append({
            'name':             _safe(psu, 'Name'),
            'model':            _safe(psu, 'Model'),
            'serial':           _safe(psu, 'SerialNumber'),
            'manufacturer':     _safe(psu, 'Manufacturer'),
            'part_number':      _safe(psu, 'PartNumber'),  # 2026-06-16 감사 G4 (Additive)
            'power_capacity_w': psu_capacity,
            'firmware_version': _safe(psu, 'FirmwareVersion'),
            'health':           _safe(psu, 'Status', 'Health'),
            'state':            _safe(psu, 'Status', 'State'),
        })

    # PowerControl — system-level power consumption (Safe Common: 3 vendors verified)
    # production-audit (2026-04-29): pdata가 dict가 아닌 list/None일 가능성 방어 (Cisco/Supermicro edge)
    pc_list = (pdata.get('PowerControl') if isinstance(pdata, dict) else None) or []
    # Round 3 #0: 비-dict 원소 방어. Round 16: PowerControl 자체가 비-list(dict/int) 오염 시
    # pc_list[0] 가 KeyError(0)/TypeError → power 섹션 전체(이미 수집한 PSU 포함) 유실.
    # isinstance(pc_list, list) 추가로 컨테이너 타입까지 방어 (정상 list-of-dict 결과 불변).
    pc0 = pc_list[0] if (isinstance(pc_list, list) and pc_list and isinstance(pc_list[0], dict)) else {}
    pm = pc0.get('PowerMetrics') or {}
    # 2026-04-29 cisco-critical-review: chassis level power_capacity_watts fallback —
    # Cisco 는 PowerControl[0].PowerCapacityWatts 를 null 응답. PSU power_capacity_w
    # 합산으로 fallback (PSU 770W × 2 = 1540W 형태).
    pc_capacity = _safe_int(_safe(pc0, 'PowerCapacityWatts'))  # Round 2: watt int 통일
    if pc_capacity is None:
        psu_caps = [p['power_capacity_w'] for p in psus if p['power_capacity_w'] is not None]
        if psu_caps:
            pc_capacity = sum(psu_caps)
    power_control = {
        # Round 1 #21: watt 필드는 int 로 통일 (BMC 가 문자열 '1500' 반환 시 타입 불일치 방지).
        # PowerSubsystem 경로와도 일관 (둘 다 int watts).
        'power_consumed_watts':  _safe_int(_safe(pc0, 'PowerConsumedWatts')),
        'power_capacity_watts':  pc_capacity,
        'interval_in_min':       _safe(pm, 'IntervalInMin'),
        'min_consumed_watts':    _safe_int(_safe(pm, 'MinConsumedWatts')),
        'avg_consumed_watts':    _safe_int(_safe(pm, 'AverageConsumedWatts')),
        'max_consumed_watts':    _safe_int(_safe(pm, 'MaxConsumedWatts')),
    } if pc0 else None

    return {'power_supplies': psus, 'power_control': power_control}, errors


def gather_thermal(bmc_ip, chassis_uri, username, password, timeout, verify_ssl):
    """Chassis/{id}/Thermal — 온도 센서 + 팬 정보 (cycle 2026-06-09, ADR-2026-06-09).

    gather_power 패턴 mirror. /Thermal (legacy) 404 시 /ThermalSubsystem fallback
    (DMTF 2020.4 / Redfish 1.13+ 신 schema). HPE Compute Scale-up Server 3200 /
    Superdome Flex 의 multi-chassis 환경에서 chassis 별 Thermal 수집 — 설명 모델
    ("각 chassis 는 Power 와 Thermal 리소스를 둔다") 요구.

    source (rule 96 R1-A):
      - DMTF DSP0266 Thermal.v1 (legacy) + ThermalSubsystem.v1_0 (2020.4)
      - HPE Superdome Flex Admin Guide (chassis Thermal 표준 Redfish)
    lab 부재 — 사이트 실측 시 정정 의무 (NEXT_ACTIONS).

    Returns: (data_dict, errors_list)  — 빈 {} 시 Thermal 미지원 (graceful).
    """
    errors = []
    if not chassis_uri:
        return {}, [_err('thermal', 'chassis_uri 없음')]

    thermal_path = _p(chassis_uri) + '/Thermal'
    st, tdata, terr = _get(bmc_ip, thermal_path, username, password, timeout, verify_ssl)

    # /Thermal 404 = 신 펌웨어 가능 → ThermalSubsystem fallback (gather_power 패턴 동일)
    if st == 404:
        return _gather_thermal_subsystem(bmc_ip, chassis_uri, username, password, timeout, verify_ssl)

    if terr or st != 200:
        return {}, [_err('thermal', f'Thermal 정보 실패: {terr or st}')]

    temps = []
    for t in _dicts(_safe(tdata, 'Temperatures')):  # 비-list/dict 방어 (rule 95 R1 #2)
        temps.append({
            'name':             _safe(t, 'Name'),
            # 2026-06-16 감사 G1: 절삭(_safe_int) → 반올림(_safe_round_int). 44.7→45.
            'reading_celsius':  _safe_round_int(_safe(t, 'ReadingCelsius')),  # str '42' 방어
            'health':           _safe(t, 'Status', 'Health'),
            'state':            _safe(t, 'Status', 'State'),
            'upper_critical':   _safe_round_int(_safe(t, 'UpperThresholdCritical')),
            'physical_context': _safe(t, 'PhysicalContext'),
        })
    fans = []
    for f in _dicts(_safe(tdata, 'Fans')):
        # 펌웨어별 Reading / ReadingRPM 혼재 (legacy schema)
        reading = _safe(f, 'Reading')
        if reading is None:
            reading = _safe(f, 'ReadingRPM')
        fans.append({
            'name':          _safe(f, 'Name'),
            'reading':       _safe_int(reading),
            'reading_units': _safe(f, 'ReadingUnits'),
            'health':        _safe(f, 'Status', 'Health'),
            'state':         _safe(f, 'Status', 'State'),
        })
    return {'temperatures': temps, 'fans': fans}, errors


def _fan_rpm_from_sensors(bmc_ip, chassis_uri, fan_uris, username, password, timeout, verify_ssl):
    """Chassis/Sensors 의 ReadingType=Rotational(RPM) 센서를 Fan URI(RelatedItem)로 역인덱스.

    CSUS-R11 (2026-06-15 실미러 검수): HPE CSUS Fan.v1_5 리소스는 SpeedPercent 가 없고 실
    회전수(4410 RPM 등)가 Chassis/Sensors 컬렉션(ReadingType=Rotational)에만 있으며 Sensor.
    RelatedItem 이 ThermalSubsystem/Fans/<id> 를 역참조한다. Fan→Sensor 정참조 링크가 없어
    Sensors 를 순회해 reverse map 을 만든다. URI 에 'fan' 포함 센서만 GET 해 비용 제한(나머지
    센서 skip). 미지원/미매치 시 빈 map → 호출자가 reading=null 유지(회귀 안전 — 기존 동작).

    source (rule 96 R1-A): DMTF DSP0266 Sensor.v1 (Reading/ReadingUnits/ReadingType/RelatedItem).
    Returns: {fan_uri(_p 정규화): (reading_int, units)}
    """
    out = {}
    want = set(fan_uris or [])
    if not want:
        return out
    st, coll, err = _get(bmc_ip, _p(chassis_uri) + '/Sensors', username, password, timeout, verify_ssl)
    if err or st != 200:
        return out
    for m in _capped(_dicts(_safe(coll, 'Members')), 'thermal', None):
        su = _safe(m, '@odata.id')
        if not su or not isinstance(su, str) or 'fan' not in su.lower():  # 비용 제한: fan 센서만
            continue
        st2, sd, _e = _get(bmc_ip, _p(su), username, password, timeout, verify_ssl)
        if st2 != 200 or not isinstance(sd, dict):
            continue
        if _str(_safe(sd, 'ReadingType')).strip().lower() != 'rotational':
            continue
        reading = _safe_int(_safe(sd, 'Reading'))
        if reading is None:
            continue
        units = _safe(sd, 'ReadingUnits')
        for ri in _dicts(_safe(sd, 'RelatedItem')):
            ru = _safe(ri, '@odata.id')
            if ru and isinstance(ru, str):
                ru_p = _p(ru)
                if ru_p in want and ru_p not in out:
                    out[ru_p] = (reading, units)
    return out


def _gather_thermal_subsystem(bmc_ip, chassis_uri, username, password, timeout, verify_ssl):
    """DMTF 2020.4 ThermalSubsystem fallback — /Thermal 404 시 (cycle 2026-06-09).

    ThermalMetrics.TemperatureReadingsCelsius[] + Fans 컬렉션. _gather_power_subsystem
    패턴 mirror.
    source: redfish.dmtf.org/schemas/v1/ThermalSubsystem.v1_0_0.json (2020.4)
    """
    errors = []
    ts_path = _p(chassis_uri) + '/ThermalSubsystem'
    st, ts, terr = _get(bmc_ip, ts_path, username, password, timeout, verify_ssl)
    if terr or st != 200:
        # ThermalSubsystem 도 없으면 미지원 — 404 는 noise 차단 (_gather_power_subsystem 패턴)
        return {}, ([] if st == 404 else [_err('thermal', f'ThermalSubsystem 미지원: {terr or st}')])

    temps = []
    tm_link = _safe(ts, 'ThermalMetrics', '@odata.id')
    if tm_link:
        mst, tm, _e = _get(bmc_ip, _p(tm_link), username, password, timeout, verify_ssl)
        if mst == 200:
            for tr in _dicts(_safe(tm, 'TemperatureReadingsCelsius')):
                temps.append({
                    'name':             _safe(tr, 'DeviceName') or _safe(tr, 'Name'),
                    # 2026-06-16 감사 G1: 절삭 → 반올림. ThermalMetrics.Reading 은 float (39.3906).
                    'reading_celsius':  _safe_round_int(_safe(tr, 'Reading')),
                    'health':           _safe(tr, 'Status', 'Health'),
                    'state':            _safe(tr, 'Status', 'State'),
                    'upper_critical':   None,
                    'physical_context': _safe(tr, 'PhysicalContext'),
                })
    fans = []
    fan_uris = []  # CSUS-R11: Sensors RPM reverse-join 용 fan URI(_p) 순서 보존
    fans_link = _safe(ts, 'Fans', '@odata.id')
    if fans_link:
        fst, fcoll, _e = _get(bmc_ip, _p(fans_link), username, password, timeout, verify_ssl)
        if fst == 200:
            for fm in _capped(_dicts(_safe(fcoll, 'Members')), 'thermal', errors):  # DoS 상한 (sibling 일관)
                furi = _safe(fm, '@odata.id')
                if not furi:
                    continue
                fst2, fdata, _e2 = _get(bmc_ip, _p(furi), username, password, timeout, verify_ssl)
                if fst2 != 200:
                    continue
                fans.append({
                    'name':          _safe(fdata, 'Name'),
                    'reading':       _safe_int(_safe(fdata, 'SpeedPercent', 'Reading')),
                    'reading_units': 'Percent' if _safe(fdata, 'SpeedPercent') else None,
                    'health':        _safe(fdata, 'Status', 'Health'),
                    'state':         _safe(fdata, 'Status', 'State'),
                })
                fan_uris.append(_p(furi))
    # CSUS-R11 (2026-06-15 실미러 검수): Fan 리소스에 SpeedPercent 가 없어 reading=null 이면
    # Chassis/Sensors 의 Rotational(RPM) 센서를 RelatedItem 역참조로 join 해 회전수 채움.
    # SpeedPercent 보유 vendor 는 reading 이 이미 차 있어 미발동 (Additive 회귀안전).
    if fans and any(f['reading'] is None for f in fans):
        rpm_map = _fan_rpm_from_sensors(
            bmc_ip, chassis_uri, fan_uris, username, password, timeout, verify_ssl)
        if rpm_map:
            for i, f in enumerate(fans):
                if f['reading'] is None and i < len(fan_uris):
                    hit = rpm_map.get(fan_uris[i])
                    if hit:
                        f['reading'], f['reading_units'] = hit[0], hit[1]
    if not temps and not fans:
        return {}, errors
    return {'temperatures': temps, 'fans': fans}, errors


def gather_boot(bmc_ip, system_uri, username, password, timeout, verify_ssl):
    """Systems/{id} Boot 객체 → 부팅 순서 + override 설정 (cycle 2026-06-09).

    설명 모델 요구 — "각 Systems/<id> (nPartition) 는 ... 부팅 순서 ... 를 포함".
    기존 gather_system 은 boot_progress (BootProgress.LastState) 만 추출 — 본 함수는
    Boot.BootOrder / BootSourceOverride* 를 별도 수집해 multi_node.partitions[].boot
    로 노출 (Additive — 단일 노드 path / 13 vendor 영향 0).

    source (rule 96 R1-A): DMTF DSP0266 ComputerSystem.Boot (BootOrder /
      BootSourceOverrideTarget / BootSourceOverrideEnabled)
    Returns: (data_dict, errors_list)  — 빈 {} 시 Boot 미노출 (graceful).
    """
    errors = []
    if not system_uri:
        return {}, [_err('boot', 'system_uri 없음')]
    st, sdata, serr = _get(bmc_ip, _p(system_uri), username, password, timeout, verify_ssl)
    if serr or st != 200:
        # System GET 실패는 gather_system 이 이미 errors[] 에 보고 — boot 는 보조 정보라
        # silent (중복 error noise → status 오분류 방지). cycle 2026-06-09 self-review.
        return {}, []
    boot = _safe(sdata, 'Boot')
    if not isinstance(boot, dict):  # Boot 미노출 / 비-dict 오염 방어
        return {}, errors
    boot_order = [b for b in _as_list(_safe(boot, 'BootOrder')) if isinstance(b, str)]
    return {
        'boot_order':                   boot_order,
        'boot_source_override_enabled': _safe(boot, 'BootSourceOverrideEnabled'),
        'boot_source_override_target':  _safe(boot, 'BootSourceOverrideTarget'),
        'boot_source_override_mode':    _safe(boot, 'BootSourceOverrideMode'),
        'boot_next':                    _safe(boot, 'BootNext'),
        'uefi_target':                  _safe(boot, 'UefiTargetBootSourceOverride'),
    }, errors


# ── 메인 ─────────────────────────────────────────────────────────────────────

def _is_status_only_error(errs, codes):
    """모든 errors 가 주어진 HTTP status 코드 시그널이면 True.

    매칭 패턴 2종 (기존 _is_404_only_error 의 판정 규칙을 그대로 일반화):
      - detail 또는 message 에 'HTTP <code>' 포함
      - message 가 '...: <code>' / '... <code>' 로 끝남 (st 정수를 그대로 넣은 경로)
    """
    if not errs:
        return False
    for e in errs:
        if not isinstance(e, dict):
            return False
        detail = str(e.get('detail') or '')  # Round 2 #8: 비-str detail/message → 'in' TypeError 방어
        msg = str(e.get('message') or '')
        if any(('HTTP %s' % c) in detail or ('HTTP %s' % c) in msg for c in codes):
            continue
        if any(msg.endswith(': %s' % c) or msg.endswith(' %s' % c) for c in codes):
            continue
        return False
    return True


def _is_404_only_error(errs):
    """모든 errors가 'HTTP 404' 시그널이면 True (endpoint 자체 부재 = capability 미지원).

    cycle 2026-05-01: 404 = "endpoint 없음 = vendor/펌웨어 미지원" — errors[] 노이즈
    분리. 5xx / timeout / 401 / 403 과 분리해 'unsupported' 시그널로 분류.
    """
    return _is_status_only_error(errs, ('404',))



# NOTE (cycle 2026-08-03): `_is_capability_missing_error`(404+400) 를 도입했다가 제거함.
# 사이트 Dell R630(iDRAC8)의 400 은 미지원 신호가 아니라 **경로 오류**였다(벤더 공식 문서로
# 확인 — gather_network_adapters_chassis docstring). 400 을 미지원으로 분류하면 우리 버그가
# not_supported 로 덮인다. 400 을 미지원으로 볼 근거가 실측으로 확보되면 그때 재도입할 것.


def _is_empty_result(val):
    """섹션 수집 결과가 '데이터 없음'인지 — collection-level 404(미지원) vs sub-멤버 404(부분 수집) 구분.

    EXC-1 (2026-06-15 HPE DL380 검수): _run 의 404-only 분기가 val 유무와 무관하게 unsupported
    로 분류하면, collection GET 은 200 인데 일부 멤버만 404 인 '부분 수집'(예: NIC 6개 중 5개
    수집 + 1개 404)이 unsupported 로 오분류되고 부분 데이터가 silent 하게 남으며 404 error 가
    드롭돼 false success 로 이어진다. 진짜 미지원(collection GET 자체 404 → shaped-empty 반환)
    만 unsupported 로 분류하도록 val 이 의미상 비었는지 판정한다.

    빈 것: None / [] / {} / 모든 value 가 비어있는 dict (예: {'controllers':[],'volumes':[]},
    {'total_mib':None,'slots':[]}, {'adapters':[],'ports':[],'fc_hbas':[],'infiniband':[]}).
    """
    if not val:
        return True
    if isinstance(val, dict):
        return all(not v for v in val.values())
    return False


def _make_section_runner(all_errors, collected, failed, unsupported=None):
    """섹션 collector wrapper — 예외/errors 누적 + collected/failed/unsupported 추적.

    rule 60: stacktrace는 stderr console verbose에만, errors[]에는 type+message만.
    cycle 2026-05-01: 404 시그널은 unsupported list로 분리 (endpoint 부재 = capability 미지원).
    호환성: unsupported 인자 미전달 시 기존 동작 유지 (back-compat).
    """
    def _run(section, fn, *args):
        try:
            val, errs = fn(*args)
            # 404 only면 unsupported로 분류, errors[]에서 제외 (호출자 noise 차단)
            # EXC-1: 단, collection-level 404(val 비어있음=진짜 미지원)만 unsupported.
            # collection 200 + sub-멤버 404 로 *부분 수집*된 경우(val 채워짐)는 아래 일반 경로로
            # 흘려보내 collected+failed 로 잡는다 — 부분 데이터 손실이 'unsupported+success' 로
            # 은폐(누락이 정상처럼 보임)되는 것 차단.
            # cycle 2026-08-03 (되돌림): 400 을 capability 부재로 분류하던 확장을 제거했다.
            # 사이트 Dell R630 8대의 400 은 "장비 미지원" 이 아니라 **우리가 그 펌웨어에 없는
            # 경로를 물어본 것**이었음이 벤더 공식 문서로 확인됨(gather_network_adapters_chassis
            # docstring). 400 을 미지원으로 분류하면 우리 쪽 경로 버그가 not_supported 로 조용히
            # 덮인다 — 근거 없는 은폐라 되돌린다. 404(endpoint 부재)만 미지원으로 유지.
            if unsupported is not None and _is_404_only_error(errs) and _is_empty_result(val):
                unsupported.append(section)
                return val
            all_errors.extend(errs)
            collected.append(section)
            if errs:
                failed.append(section)
            return val
        except Exception as e:
            sys.stderr.write(
                "[redfish_gather] %s 예외: %s\n%s\n" %
                (section, type(e).__name__, traceback.format_exc(limit=3))
            )
            all_errors.append(_err(
                section, '예외 발생',
                "%s: %s" % (type(e).__name__, str(e)[:200])
            ))
            failed.append(section)
            return None
    return _run


def gather_manager_logs(bmc_ip, manager_uri, username, password, timeout, verify_ssl):
    """Managers/{id}/LogServices → 로그 서비스 목록 (cycle 2026-06-09).

    설명 모델 요구 — "RMC 는 ... Services 와 Logs 리소스로 연결된다". 본 함수는
    LogServices 컬렉션 메타(각 LogService 의 id/name/정책)를 수집해
    multi_node.managers[].log_services 로 노출 (Additive — 단일 노드 path /
    13 vendor 영향 0). 로그 엔트리 자체(대용량)는 수집하지 않음 — 범위 외.

    source (rule 96 R1-A): DMTF DSP0266 LogService / LogServiceCollection
    Returns: (list_of_log_services, errors_list)  — 빈 [] 시 LogServices 미노출.
    """
    errors = []
    if not manager_uri:
        return [], [_err('log_services', 'manager_uri 없음')]
    st, mdata, merr = _get(bmc_ip, _p(manager_uri), username, password, timeout, verify_ssl)
    if merr or st != 200:
        # Manager GET 실패는 gather_bmc 가 이미 errors[] 에 보고 — log_services 는 보조
        # 정보라 silent (중복 error noise 차단). cycle 2026-06-09 self-review.
        return [], []
    ls_link = _safe(mdata, 'LogServices', '@odata.id')
    if not ls_link:
        return [], errors  # LogServices 미노출 — graceful (정상)
    cst, coll, cerr = _get(bmc_ip, _p(ls_link), username, password, timeout, verify_ssl)
    if cerr or cst != 200:
        # 404 는 noise 차단 (endpoint 부재 = 미지원)
        return [], ([] if cst == 404 else [_err('log_services', f'LogServices 컬렉션 실패: {cerr or cst}')])
    out = []
    for m in _capped(_dicts(_safe(coll, 'Members')), 'log_services', errors):
        uri = _safe(m, '@odata.id')
        if not uri:
            continue
        lst, ld, _e = _get(bmc_ip, _p(uri), username, password, timeout, verify_ssl)
        if lst != 200 or not isinstance(ld, dict):
            continue
        out.append({
            'id':               _safe(ld, 'Id'),
            'name':             _safe(ld, 'Name'),
            'overwrite_policy': _safe(ld, 'OverWritePolicy'),
            'service_enabled':  _safe(ld, 'ServiceEnabled'),
            'log_entry_type':   _safe(ld, 'LogEntryType'),
            'date_time':        _safe(ld, 'DateTime'),
        })
    return out, errors


def gather_managers_multi(bmc_ip, managers_coll_uri, vendor, username, password,
                          timeout, verify_ssl, manager_layout=None):
    """모든 Managers Member 별 gather_bmc 호출 (cycle 2026-05-12 / ADR-2026-05-12).

    HPE CSUS 3200 / Superdome Flex 의 RMC + per-chassis PDHC + per-node iLO5 전수 수집.
    `manager_layout` 으로 `bmc.name` 라벨 분기 (RMC / PDHC / iLO).

    rule 92 R2 Additive only — 기존 `gather_bmc` 함수 변경 0. 다른 vendor 영향 0
    (이 함수는 manager_layout 정의된 vendor 만 호출).

    Returns: {'managers': [{id, uri, role, bmc, log_services}], 'errors': [...]}
    """
    out = {'managers': [], 'errors': []}
    members, _st, err = _resolve_all_member_uris(
        bmc_ip, managers_coll_uri, username, password, timeout, verify_ssl
    )
    if err:
        out['errors'].append(_err('multi_node.managers',
            f'Managers 컬렉션 실패: {err}'))
        return out
    # Round 16: multi-node 멤버 순회도 _capped DoS 상한 적용 (file 전역 컨벤션 일관 —
    # account/logs/composition/fabrics 와 동일). 실 BMC 멤버 수 << 상한 → 정상 결과 불변.
    for idx, m in enumerate(_capped(members, 'multi_node.managers', out['errors'])):
        # cycle 2026-06-09 (review): 첫 Manager 만 layout-default RMC/primary (다중 RMC
        # 오라벨 + name/role 불일치 차단). substring 매치(rmc/pdhc/ilo)는 position 무관.
        is_first = (idx == 0)
        bmc_data, bmc_errs = gather_bmc(
            bmc_ip, m['uri'], vendor,
            username, password, timeout, verify_ssl,
            manager_layout=manager_layout, is_first=is_first,
            manager_id=m['id'],  # role 와 동일 id source (name/role 모순 차단 — review)
        )
        # cycle 2026-06-09: Manager LogServices 수집 (설명 모델 "Services 와 Logs").
        logs_data, logs_errs = gather_manager_logs(
            bmc_ip, m['uri'], username, password, timeout, verify_ssl)
        # CSUS-R15 (2026-06-15 실미러 검수): gather_bmc 의 _network_meta 는 normalize_standard.yml
        # 이 top-level data.bmc 의 dns_servers/default_gateways 추출 후 제거하는 내부 임시 키다.
        # multi_node.managers[].bmc 는 normalize 를 거치지 않고 verbatim 통과 → _network_meta 누설
        # (envelope 비노출 키 위반, rule 13 R5 / 22). top-level 과 대칭으로 여기서 strip.
        if isinstance(bmc_data, dict) and '_network_meta' in bmc_data:
            bmc_data = {k: v for k, v in bmc_data.items() if k != '_network_meta'}
        out['managers'].append({
            'id':           m['id'],
            'uri':          m['uri'],
            'role':         _classify_manager_role(m['uri'], m['id'], manager_layout, is_first),
            'bmc':          bmc_data,
            'log_services': logs_data,
        })
        out['errors'].extend(bmc_errs)
        out['errors'].extend(logs_errs)
    return out


def _summarize_partition_disks(physical_disks):
    """physical_disks[] → storage.summary {groups, grand_total_gb} (per-partition).

    top-level normalize_standard.yml 의 _rf_summary_storage 와 동일 grouping 규칙
    (단위용량 × media × protocol × model). cycle 2026-05-29.
    """
    groups, seen, total = [], {}, 0
    for d in (physical_disks or []):
        cap_mb = _safe_int(d.get('total_mb'), 0)  # rule 95 R1 #7: 펌웨어가 str 반환 시 str//int crash 방어
        cap_gb = cap_mb // MIB_PER_GIB if cap_mb else 0
        if cap_gb <= 0:
            continue
        mt, pr, md = d.get('media_type'), d.get('protocol'), d.get('model')
        key = '%s|%s|%s|%s' % (cap_gb, mt, pr, md)
        if key in seen:
            g = groups[seen[key]]
            g['quantity'] += 1
            g['group_total_gb'] = g['quantity'] * cap_gb
        else:
            seen[key] = len(groups)
            groups.append({'unit_capacity_gb': cap_gb, 'model': md, 'media_type': mt,
                           'protocol': pr, 'quantity': 1, 'group_total_gb': cap_gb})
        total += cap_gb
    return {'groups': groups, 'grand_total_gb': total}


def _normalize_storage_raw(raw):
    """raw gather_storage {controllers, volumes} → canonical storage section.

    cycle 2026-05-29: multi_node.partitions[].storage 가 raw 로 노출되던 문제 해소.
    top-level normalize_standard.yml(Ansible) 과 동일 canonical shape 를 Python 에서 생성
    (multi_node 전용 parallel — 두 경로 모두 같은 schema 보장). hbas/infiniband 는 chassis
    레벨 NetworkAdapter 소관이라 partition storage 에는 빈 list (Additive 자리만 유지).
    """
    raw = raw if isinstance(raw, dict) else {}
    controllers_out, physical, seen = [], [], set()
    for ctrl in (raw.get('controllers') or []):
        if not isinstance(ctrl, dict):  # rule 95 R1 #2: 비-dict controller 방어 (Round 1 #2)
            continue
        drives_out = []
        for drv in (ctrl.get('drives') or []):
            if not isinstance(drv, dict):
                continue
            cap = drv.get('capacity_bytes')
            tmb = int(cap // BYTES_PER_MIB) if isinstance(cap, (int, float)) else None  # 0 보존(known-zero) Round 1 #15
            drives_out.append({
                'device': drv.get('name'), 'model': drv.get('model'),
                'total_mb': tmb, 'media_type': drv.get('media_type'),
                'protocol': drv.get('protocol'), 'health': drv.get('health'),
            })
            key = '%s%s%s' % (drv.get('name') or '', drv.get('model') or '', drv.get('serial') or '')
            if key not in seen and (drv.get('name') or drv.get('model')):
                seen.add(key)
                physical.append({
                    'id': drv.get('id'), 'device': drv.get('name'), 'model': drv.get('model'),
                    'serial': drv.get('serial'), 'total_mb': tmb,
                    'media_type': drv.get('media_type'), 'protocol': drv.get('protocol'),
                    'health': drv.get('health'),
                    'failure_predicted': drv.get('failure_predicted'),
                    'predicted_life_percent': drv.get('predicted_life_percent'),
                })
        controllers_out.append({
            'id': ctrl.get('id'), 'name': ctrl.get('name'), 'health': ctrl.get('health'),
            'controller_model': ctrl.get('controller_model'),
            'controller_firmware': ctrl.get('controller_firmware'),
            'controller_manufacturer': ctrl.get('controller_manufacturer'),
            'controller_health': ctrl.get('controller_health'),
            'drives': drives_out,
        })
    logical = []
    for vol in (raw.get('volumes') or []):
        if not isinstance(vol, dict):  # Round 5 #0: controllers/drives 와 일관
            continue
        logical.append({
            'id': vol.get('id'), 'name': vol.get('name'),
            'controller_id': vol.get('controller_id'),
            'member_drive_ids': vol.get('member_drive_ids') or [],
            'raid_level': vol.get('raid_level'), 'total_mb': vol.get('total_mb'),
            'health': vol.get('health'), 'state': vol.get('state'),
            'boot_volume': vol.get('boot_volume'),
        })
    return {
        'filesystems': [], 'physical_disks': physical, 'datastores': [],
        'controllers': controllers_out, 'logical_volumes': logical,
        'summary': _summarize_partition_disks(physical),
        'hbas': [], 'infiniband': [],
    }


def _normalize_network_raw(raw_nics):
    """raw gather_network (NIC list) → canonical network section (per-partition).

    cycle 2026-05-29: multi_node.partitions[].network 가 list 로 노출되던 schema 불일치
    해소 (top-level network 와 동일 dict shape). normalize_standard.yml interfaces 로직 parallel.
    """
    nics = raw_nics if isinstance(raw_nics, list) else []
    interfaces, gws = [], []
    for nic in nics:
        if not isinstance(nic, dict):
            continue
        addrs = []
        for a in _as_list(nic.get('ipv4')):  # Round 3 #5: 비-list ipv4 방어
            addr = a.get('address') if isinstance(a, dict) else None
            if addr and addr not in ('0.0.0.0', ''):
                addrs.append({'family': 'ipv4', 'address': addr, 'prefix_length': None,
                              'subnet_mask': a.get('subnet_mask'), 'gateway': a.get('gateway'),
                              'origin': a.get('address_origin')})
        interfaces.append({
            'id': nic.get('id') or nic.get('name'), 'name': nic.get('name'),
            'kind': 'server_nic', 'mac': nic.get('mac'), 'mtu': nic.get('mtu'),
            'speed_mbps': nic.get('speed_mbps'),
            'link_status': _normalize_link_status(nic.get('link_status')),
            'is_primary': False, 'addresses': addrs,
        })
    for iface in interfaces:
        for a in iface['addresses']:
            if a.get('gateway') and a['gateway'] not in ('0.0.0.0', ''):
                e = {'family': a['family'], 'address': a['gateway']}
                if e not in gws:
                    gws.append(e)
    return {'dns_servers': [], 'default_gateways': gws, 'interfaces': interfaces,
            'adapters': [], 'ports': [], 'summary': {'groups': []}}


def _normalize_cpu_raw(procs):
    """raw gather_processors (list) → canonical cpu section (per-partition).

    cycle 2026-05-29: top-level normalize_standard.yml 의 B01 필터 + 합산 + summary 와
    동일 결과를 Python 에서 생성 (multi_node.partitions[].cpu 일관성).
    """
    procs = procs if isinstance(procs, list) else []
    cpus = [p for p in procs if isinstance(p, dict)
            and (str(p.get('processor_type') or '').strip().upper() in ('CPU', 'CORE', ''))]
    cores = sum(_safe_int(p.get('total_cores'), 0) for p in cpus)  # rule 95 R1 #7: 비-숫자 cores str 방어
    threads = sum(_safe_int(p.get('total_threads'), 0) for p in cpus)
    models = [p.get('model') for p in cpus if p.get('model')]
    speeds = [p.get('speed_mhz') for p in cpus if p.get('speed_mhz')]
    archs = [p.get('architecture') for p in cpus if p.get('architecture')]
    isets = [p.get('instruction_set') for p in cpus if p.get('instruction_set')]
    groups, seen = [], {}
    for p in cpus:
        m = p.get('model') or 'unknown'
        tc = _safe_int(p.get('total_cores'), 0)  # rule 95 R1 #7: grouping 도 동일 방어
        if m in seen:
            g = groups[seen[m]]
            g['sockets'] += 1
            g['total_cores'] += tc
            g['cores_per_socket'] = g['total_cores'] // g['sockets']  # Round 2 #1: 혼합 코어 same-model 평균 갱신
        else:
            seen[m] = len(groups)
            groups.append({'model': m, 'manufacturer': p.get('manufacturer'),
                           'max_speed_mhz': p.get('speed_mhz'),
                           'architecture': p.get('architecture') or p.get('instruction_set'),
                           'sockets': 1, 'cores_per_socket': tc, 'total_cores': tc})
    return {
        'sockets': (len(cpus) or None),
        'cores_physical': (cores or None),
        'logical_threads': (threads or None),
        'model': (models[0] if models else None),
        'max_speed_mhz': (speeds[0] if speeds else None),
        'architecture': (archs[0] if archs else (isets[0] if isets else None)),
        'summary': {'groups': groups},
    }


def _normalize_memory_raw(raw_mem):
    """raw gather_memory {total_mib, slots} → canonical memory section (per-partition).

    cycle 2026-05-29: top-level normalize_standard.yml _rf_summary_memory 와 동일 grouping.
    """
    raw_mem = raw_mem if isinstance(raw_mem, dict) else {}
    slots = raw_mem.get('slots') or []
    total_mib = raw_mem.get('total_mib')
    groups, seen, total_gb = [], {}, 0
    for s in slots:
        if not isinstance(s, dict):
            continue
        cap_mb = _safe_int(s.get('capacity_mb') or s.get('capacity_mib'), 0)  # rule 95 R1 #7: '8GB' 등 단위문자열 방어
        if cap_mb <= 0:
            continue
        cap_gb = cap_mb // MIB_PER_GIB
        t, sp = s.get('type'), s.get('speed_mhz')
        mfr, pn = s.get('manufacturer'), s.get('part_number')
        key = '%s|%s|%s|%s|%s' % (cap_gb, t, sp, mfr, pn)
        if key in seen:
            g = groups[seen[key]]
            g['quantity'] += 1
            g['group_total_gb'] = g['quantity'] * cap_gb
        else:
            seen[key] = len(groups)
            groups.append({'unit_capacity_gb': cap_gb, 'type': t, 'speed_mhz': sp,
                           'manufacturer': mfr, 'part_number': pn, 'quantity': 1,
                           'group_total_gb': cap_gb})
        total_gb += cap_gb
    return {
        'total_mb': total_mib, 'total_basis': 'physical_installed',
        'installed_mb': total_mib, 'visible_mb': None, 'free_mb': None,
        'slots': slots, 'summary': {'groups': groups, 'grand_total_gb': total_gb},
    }


def gather_systems_multi(bmc_ip, systems_coll_uri, vendor, username, password,
                         timeout, verify_ssl, chassis_uri=None, product_hint=None):
    """모든 Systems Member 별 gather_system + per-partition summary (cycle 2026-05-12).

    nPartition 환경 — 각 Partition 별 cpu / memory / storage / network 모두 수집.

    cycle 2026-05-29: storage/network 를 canonical shape 로 정규화 (구: raw 노출).
    storage = {controllers, physical_disks, logical_volumes, hbas, infiniband, summary};
    network = {dns_servers, default_gateways, interfaces, adapters, ports, summary}.

    Returns: {'partitions': [{id, system_uri, system, cpu, memory, storage, network, boot}],
              'errors': [...]}
    """
    out = {'partitions': [], 'errors': []}
    members, _st, err = _resolve_all_member_uris(
        bmc_ip, systems_coll_uri, username, password, timeout, verify_ssl
    )
    if err:
        out['errors'].append(_err('multi_node.partitions',
            f'Systems 컬렉션 실패: {err}'))
        return out
    creds = (username, password, timeout, verify_ssl)
    # Round 16: per-partition 순회도 _capped DoS 상한 (멤버당 6 GET — file 컨벤션 일관).
    for m in _capped(members, 'multi_node.partitions', out['errors']):
        # CSUS-R1 (2026-06-15 실미러 검수): partition 별 Links.Chassis 로 compute chassis 해석
        # + product_hint 전달 → partition.system.manufacturer/model 이 top-level data.system 과
        # 일관(구: chassis_uri/product_hint 미전달로 multi_node.partitions[].system 만 null).
        part_chassis = _resolve_system_chassis_uri(bmc_ip, m['uri'], chassis_uri, *creds)
        sys_data, sys_errs = gather_system(bmc_ip, m['uri'], vendor, *creds, part_chassis, product_hint)
        cpu_data, cpu_errs = gather_processors(bmc_ip, m['uri'], *creds)
        mem_data, mem_errs = gather_memory(bmc_ip, m['uri'], *creds)
        sto_data, sto_errs = gather_storage(bmc_ip, m['uri'], *creds)
        net_data, net_errs = gather_network(bmc_ip, m['uri'], *creds)
        # cycle 2026-06-09: per-partition boot order (설명 모델 "부팅 순서").
        boot_data, boot_errs = gather_boot(bmc_ip, m['uri'], *creds)
        out['partitions'].append({
            'id':         m['id'],
            'system_uri': m['uri'],
            'system':     sys_data,
            # cycle 2026-05-29: per-partition 전 섹션 canonical 정규화.
            # 구: cpu=raw list / memory=raw dict / storage=raw / network=raw list
            #     → normalize 누락 (top-level 과 shape 불일치 + network 가 list).
            'cpu':        _normalize_cpu_raw(cpu_data),
            'memory':     _normalize_memory_raw(mem_data),
            'storage':    _normalize_storage_raw(sto_data),
            'network':    _normalize_network_raw(net_data),
            # cycle 2026-06-09: boot order (Additive — Boot 미노출 시 {}).
            'boot':       boot_data,
        })
        out['errors'].extend(sys_errs)
        out['errors'].extend(cpu_errs)
        out['errors'].extend(mem_errs)
        out['errors'].extend(sto_errs)
        out['errors'].extend(net_errs)
        out['errors'].extend(boot_errs)
    return out


def _extract_chassis_oem(cdata):                                              # nosec rule12-r1
    """Chassis-level OEM 추출 — OEM @odata.type 가 self-identify 하는 vendor namespace 기준.

    CSUS-R18 (2026-06-15 재검수, F2): HPE CSUS/Superdome compute chassis 는 Oem.Hpe.@odata.type=
    #HpeH3Chassis 로 물리위치(PhysicalLocationString/Physloc) + 프로세서 호환성(ProcessorsCompatibilityKey/
    Compatible) + OemChassisType 를 노출. 표준 Chassis 필드(manufacturer/model/serial/part_number)엔
    없는 정보라 미수집 시 영구 손실. multi_node.chassis[] entry 에 chassis-level oem 으로 보존(Additive).
    #HpeH3Chassis 아니면 {} (RackGroup/Rack/타 벤더 — 회귀 안전). 코드는 vendor 분기 없이 OEM
    @odata.type 만 검사 (rule 12 R1 Allowed — Redfish OEM namespace 직접 의존, CSUS-R17 와 동일 정신).
    """
    oem = _safe(cdata, 'Oem', 'Hpe') or _safe(cdata, 'Oem', 'Hp') or {}        # nosec rule12-r1
    oem_type = _str(_safe(oem, '@odata.type'))
    if oem_type.startswith('#HpeH3Chassis'):  # nosec rule12-r1 — Redfish OEM namespace (CSUS/Superdome)
        return {
            'oem_chassis_type':             _safe(oem, 'OemChassisType'),
            'physical_location':            _safe(oem, 'PhysicalLocationString'),
            'physloc':                      _safe(oem, 'Physloc'),
            'processors_compatibility_key': _safe(oem, 'ProcessorsCompatibilityKey'),
            'processors_compatible':        _safe(oem, 'ProcessorsCompatible'),
        }
    return {}


def gather_chassis_multi(bmc_ip, chassis_coll_uri, username, password,
                         timeout, verify_ssl):
    """모든 Chassis Member 별 hardware + power 수집 (cycle 2026-05-12).

    Base / Expansion / Compute Module 구분 + ChassisType 표준 fallback.

    Returns: {'chassis': [{id, uri, kind, chassis_type, manufacturer, model, ..., power, thermal}],
              'errors': [...]}
    """
    out = {'chassis': [], 'errors': []}
    members, _st, err = _resolve_all_member_uris(
        bmc_ip, chassis_coll_uri, username, password, timeout, verify_ssl
    )
    if err:
        out['errors'].append(_err('multi_node.chassis',
            f'Chassis 컬렉션 실패: {err}'))
        return out
    # Round 16: chassis 순회도 _capped DoS 상한 (file 컨벤션 일관).
    for m in _capped(members, 'multi_node.chassis', out['errors']):
        cst, cdata, cerr = _get(bmc_ip, _p(m['uri']),
                                username, password, timeout, verify_ssl)
        get_ok = (not cerr and cst == 200)
        if not get_ok:
            out['errors'].append(_err('multi_node.chassis',
                f"Chassis {m['id']} GET 실패: {cerr or cst}"))
            # cycle 2026-06-09: append-on-fail — GET 실패해도 멤버는 노출한다.
            # gather_systems_multi / gather_managers_multi 와 일관 (구: continue 로 drop
            # → chassis_count 가 collection 멤버 수보다 작게 under-report 되는 불일치).
        if not isinstance(cdata, dict):  # 비-dict 응답 오염 방어 (rule 95 R1 #2)
            cdata = {}
        kind = _classify_chassis_kind(m['uri'], m['id'], cdata)
        # cycle 2026-06-09 (review): chassis GET 성공 시에만 Power/Thermal sub-GET.
        # 실패 chassis 에 doomed sub-GET (2 round-trip) + 중복 error noise 차단 — 멤버는
        # append (chassis_count 보존). 설명 모델 "Power 와 Thermal".
        if get_ok:
            pwr_data, pwr_errs = gather_power(bmc_ip, m['uri'],
                                              username, password, timeout, verify_ssl)
            thm_data, thm_errs = gather_thermal(bmc_ip, m['uri'],
                                                username, password, timeout, verify_ssl)
        else:
            pwr_data, pwr_errs, thm_data, thm_errs = {}, [], {}, []
        out['chassis'].append({
            'id':            m['id'],
            'uri':           m['uri'],
            'kind':          kind,
            'chassis_type':  _safe(cdata, 'ChassisType'),
            'manufacturer':  _safe(cdata, 'Manufacturer'),
            'model':         _safe(cdata, 'Model'),
            'serial_number': _safe(cdata, 'SerialNumber'),
            'part_number':   _safe(cdata, 'PartNumber'),
            # 2026-06-16 감사 G4 (Additive): chassis 식별/상태 메타. CSUS r001u01 raw 는
            # UUID(System UUID 와 다른 chassis 고유)/AssetTag/PowerState 보유했으나 미수집이었음.
            'uuid':          _safe(cdata, 'UUID'),
            'asset_tag':     _strip_or_none(_safe(cdata, 'AssetTag')),
            'power_state':   _safe(cdata, 'PowerState'),
            'power':         pwr_data,
            # cycle 2026-06-09: thermal (Additive — Thermal 미노출 시 {}).
            'thermal':       thm_data,
            # CSUS-R18 (2026-06-15 재검수, F2): chassis-level OEM (#HpeH3Chassis — 물리위치/
            # 프로세서 호환성). 표준 필드에 없는 정보. 비-CSUS/RackGroup 은 {} (Additive).
            'oem':           _extract_chassis_oem(cdata),
        })
        out['errors'].extend(pwr_errs)
        out['errors'].extend(thm_errs)
    return out


def gather_composition_service(bmc_ip, service_root, username, password, timeout, verify_ssl):
    """CompositionService + ResourceBlocks 수집 (cycle 2026-06-09, ADR-2026-06-09).

    설명 모델 요구 — HPE CSUS 3200 nPartition 은 표준 Redfish Composition Service 로
    구성된다. 각 ResourceBlock 은 하나의 chassis 에 대응하고 CPU/DIMM 을 포함하며,
    ResourceBlock 의 ComputerSystems 링크가 조합된 nPartition 을 가리킨다.

    multi_node.composition (Additive — manager_layout 정의 vendor 만 호출).
    CompositionService 링크 부재 시 None (graceful — 대다수 vendor 는 미노출).

    source (rule 96 R1-A):
      - DMTF DSP0266 CompositionService / ResourceBlock
        (redfish.dmtf.org/schemas/v1/ResourceBlock.json)
      - HPE Compute Scale-up Server 3200 Administration Guide (nPartition = ResourceBlock 조합)
    lab 부재 — 사이트 실측 시 정정 의무 (NEXT_ACTIONS).

    Returns: (dict_or_None, errors_list)
    """
    errors = []
    if not isinstance(service_root, dict):
        return None, errors
    comp_uri = _safe(service_root, 'CompositionService', '@odata.id')
    if not comp_uri:
        return None, errors  # CompositionService 미노출 — graceful (대다수 vendor)
    st, comp, cerr = _get(bmc_ip, _p(comp_uri), username, password, timeout, verify_ssl)
    if cerr or st != 200:
        return None, ([] if st == 404 else
                      [_err('multi_node.composition', f'CompositionService 실패: {cerr or st}')])

    blocks = []
    rb_link = _safe(comp, 'ResourceBlocks', '@odata.id')
    if rb_link:
        rst, rcoll, rerr = _get(bmc_ip, _p(rb_link), username, password, timeout, verify_ssl)
        if rerr or rst != 200:
            if rst != 404:
                errors.append(_err('multi_node.composition',
                                   f'ResourceBlocks 컬렉션 실패: {rerr or rst}'))
        else:
            for m in _capped(_dicts(_safe(rcoll, 'Members')), 'multi_node.composition', errors):
                uri = _safe(m, '@odata.id')
                if not uri:
                    continue
                bst, bd, _e = _get(bmc_ip, _p(uri), username, password, timeout, verify_ssl)
                if bst != 200 or not isinstance(bd, dict):
                    continue
                # 각 ResourceBlock 의 chassis 대응 + 조합된 ComputerSystems (nPartition) 링크
                chassis_links = [
                    _safe(c, '@odata.id')
                    for c in _dicts(_safe(bd, 'Links', 'Chassis'))
                    if _safe(c, '@odata.id')
                ]
                systems_links = [
                    _safe(s, '@odata.id')
                    for s in _dicts(_safe(bd, 'Links', 'ComputerSystems'))
                    if _safe(s, '@odata.id')
                ]
                blocks.append({
                    'id':                   _safe(bd, 'Id'),
                    'name':                 _safe(bd, 'Name'),
                    'resource_block_types': [t for t in _as_list(_safe(bd, 'ResourceBlockType'))
                                             if isinstance(t, str)],
                    'state':                _safe(bd, 'Status', 'State'),
                    'health':               _safe(bd, 'Status', 'Health'),
                    'composition_state':    _safe(bd, 'CompositionStatus', 'CompositionState'),
                    # 표준 ResourceBlock = Processors/Memory idRef 배열 (DMTF). 비-표준
                    # collection-link(dict) 펌웨어면 0 으로 under-count — lab 부재, 사이트
                    # fixture 확인 시 정정 (NEXT_ACTIONS C9, rule 96 R1-A).
                    'processor_count':      len(_dicts(_safe(bd, 'Processors'))),
                    'memory_count':         len(_dicts(_safe(bd, 'Memory'))),
                    'chassis':              chassis_links,
                    'computer_systems':     systems_links,
                })
    return {
        # cycle 2026-06-09 (review): 비-dict/null 200 body 는 enabled=None (정직한 unknown).
        # dict 면 ServiceEnabled 누락 시 DMTF 관례상 True. sibling gather_manager_logs 와 정합.
        'enabled':              (bool(comp.get('ServiceEnabled', True)) if isinstance(comp, dict) else None),
        'state':                _safe(comp, 'Status', 'State'),
        'health':               _safe(comp, 'Status', 'Health'),
        'resource_block_count': len(blocks),
        'resource_blocks':      blocks,
    }, errors


def _gather_fabric_members(bmc_ip, coll_uri, username, password, timeout, verify_ssl, errors, kind):
    """Fabric 의 Switches / Endpoints 컬렉션 멤버 수집 helper (cycle 2026-06-09).

    kind='switch' → SwitchType / Status. kind='endpoint' → EndpointProtocol / Status.
    source (rule 96 R1-A): DMTF DSP0266 Switch / Endpoint.
    """
    if not coll_uri:
        return []
    st, coll, cerr = _get(bmc_ip, _p(coll_uri), username, password, timeout, verify_ssl)
    if cerr or st != 200:
        return []
    out = []
    for m in _capped(_dicts(_safe(coll, 'Members')), f'multi_node.fabrics.{kind}', errors):
        uri = _safe(m, '@odata.id')
        if not uri:
            continue
        mst, md, _e = _get(bmc_ip, _p(uri), username, password, timeout, verify_ssl)
        if mst != 200 or not isinstance(md, dict):
            continue
        if kind == 'switch':
            out.append({
                'id':          _safe(md, 'Id'),
                'name':        _safe(md, 'Name'),
                'switch_type': _safe(md, 'SwitchType'),
                'state':       _safe(md, 'Status', 'State'),
                'health':      _safe(md, 'Status', 'Health'),
            })
        else:  # endpoint
            out.append({
                'id':                _safe(md, 'Id'),
                'name':              _safe(md, 'Name'),
                'endpoint_protocol': _safe(md, 'EndpointProtocol'),
                'state':             _safe(md, 'Status', 'State'),
                'health':            _safe(md, 'Status', 'Health'),
            })
    return out


def gather_fabrics(bmc_ip, service_root, username, password, timeout, verify_ssl):
    """Fabrics + FlexGrid (Switches/Endpoints) 수집 (cycle 2026-06-09, ADR-2026-06-09).

    설명 모델 요구 — HPE CSUS 3200 은 NUMAlink fabric 을 표준 Redfish Fabric 모델로
    표현하며, FlexGrid Flex Fabric 은 Switches 와 Endpoints 를 사용한다 (Links/Zones 미사용).

    multi_node.fabrics (Additive — manager_layout 정의 vendor 만 호출). Fabrics 링크
    부재 시 None (graceful).

    source (rule 96 R1-A):
      - DMTF DSP0266 Fabric / Switch / Endpoint
      - HPE Compute Scale-up Server 3200 architecture (NUMAlink / FlexGrid)
    lab 부재 — 사이트 실측 시 정정 의무 (NEXT_ACTIONS).

    Returns: (list_of_fabrics_or_None, errors_list)
    """
    errors = []
    if not isinstance(service_root, dict):
        return None, errors
    fab_uri = _safe(service_root, 'Fabrics', '@odata.id')
    if not fab_uri:
        return None, errors  # Fabrics 미노출 — graceful
    st, fcoll, ferr = _get(bmc_ip, _p(fab_uri), username, password, timeout, verify_ssl)
    if ferr or st != 200:
        return None, ([] if st == 404 else
                      [_err('multi_node.fabrics', f'Fabrics 컬렉션 실패: {ferr or st}')])
    fabrics = []
    for m in _capped(_dicts(_safe(fcoll, 'Members')), 'multi_node.fabrics', errors):
        furi = _safe(m, '@odata.id')
        if not furi:
            continue
        fst, fdata, _e = _get(bmc_ip, _p(furi), username, password, timeout, verify_ssl)
        if fst != 200 or not isinstance(fdata, dict):
            continue
        switches = _gather_fabric_members(
            bmc_ip, _safe(fdata, 'Switches', '@odata.id'),
            username, password, timeout, verify_ssl, errors, kind='switch')
        endpoints = _gather_fabric_members(
            bmc_ip, _safe(fdata, 'Endpoints', '@odata.id'),
            username, password, timeout, verify_ssl, errors, kind='endpoint')
        fabrics.append({
            'id':             _safe(fdata, 'Id'),
            'name':           _safe(fdata, 'Name'),
            'fabric_type':    _safe(fdata, 'FabricType'),
            'state':          _safe(fdata, 'Status', 'State'),
            'health':         _safe(fdata, 'Status', 'Health'),
            'switch_count':   len(switches),
            'endpoint_count': len(endpoints),
            'switches':       switches,
            'endpoints':      endpoints,
        })
    return fabrics, errors


def _collect_multi_node_topology(bmc_ip, vendor, service_root,
                                 username, password, timeout, verify_ssl,
                                 manager_layout=None):
    """Multi-node topology 전수 수집 (cycle 2026-05-12 / ADR-2026-05-12).

    `manager_layout` 미정의 (None) 시 None 반환 — 기존 13 vendor 영향 0.
    HPE CSUS 3200 (`rmc_primary`) / Superdome Flex (`rmc_primary_ilo_secondary`) 만 활성.

    Returns: dict | None
        dict shape: {
            'enabled': bool,
            'layout': str,
            'summary': {partition_count, manager_count, chassis_count,
                        representative_partition,
                        resource_block_count, fabric_count},
            'partitions': list, 'managers': list, 'chassis': list,
            'composition': dict | None, 'fabrics': list | None,
            'errors': list,
        }
    """
    if not manager_layout:
        return None
    if not isinstance(service_root, dict):
        return None
    systems_uri  = _safe(service_root, 'Systems',  '@odata.id')
    managers_uri = _safe(service_root, 'Managers', '@odata.id')
    chassis_uri_coll = _safe(service_root, 'Chassis',  '@odata.id')

    sys_result = gather_systems_multi(
        bmc_ip, systems_uri, vendor, username, password, timeout, verify_ssl,
        product_hint=_safe(service_root, 'Product'),
    )
    mgr_result = gather_managers_multi(
        bmc_ip, managers_uri, vendor, username, password, timeout, verify_ssl,
        manager_layout=manager_layout,
    )
    chs_result = gather_chassis_multi(
        bmc_ip, chassis_uri_coll, username, password, timeout, verify_ssl,
    )
    # cycle 2026-06-09: CompositionService/ResourceBlocks + Fabrics/FlexGrid 수집
    # (설명 모델 요구). ServiceRoot 에 링크 부재 시 None (graceful — Additive).
    composition, comp_errs = gather_composition_service(
        bmc_ip, service_root, username, password, timeout, verify_ssl,
    )
    fabrics, fab_errs = gather_fabrics(
        bmc_ip, service_root, username, password, timeout, verify_ssl,
    )

    partitions = sys_result.get('partitions') or []
    managers   = mgr_result.get('managers')   or []
    chassis    = chs_result.get('chassis')    or []

    representative = partitions[0].get('id') if partitions else None  # rule 95 R1 #2: 방어적 .get (id 누락 KeyError 회피)
    rb_count = composition.get('resource_block_count', 0) if isinstance(composition, dict) else 0
    return {
        'enabled': True,
        'layout':  manager_layout,
        'summary': {
            'partition_count':           len(partitions),
            'manager_count':             len(managers),
            'chassis_count':             len(chassis),
            'representative_partition':  representative,
            # cycle 2026-06-09: composition / fabric 규모 (Additive 신 키)
            'resource_block_count':      rb_count,
            'fabric_count':              len(fabrics) if isinstance(fabrics, list) else 0,
        },
        'partitions': partitions,
        'managers':   managers,
        'chassis':    chassis,
        # cycle 2026-06-09: 신 컨테이너 (None = ServiceRoot 미노출 — Additive).
        'composition': composition,
        'fabrics':     fabrics,
        'errors': (
            sys_result.get('errors', [])
            + mgr_result.get('errors', [])
            + chs_result.get('errors', [])
            + comp_errs
            + fab_errs
        ),
    }


def _collect_all_sections(bmc_ip, vendor, system_uri, manager_uri, chassis_uri,
                          username, password, timeout, verify_ssl,
                          all_errors, collected, failed, unsupported=None,
                          manager_layout=None, product_hint=None):
    """10개 섹션 dispatch (system / bmc / processors / memory / storage / network /
    firmware / power / thermal / network_adapters[P4]).

    cycle 2026-05-01: unsupported list 추가 — 404 응답 섹션을 별도 분류
    (capability 미지원 = noise 아님).

    cycle 2026-06-14 (Track 4): thermal 단일노드 배선 (이전엔 multi_node 경로만).
    gather_power 패턴 mirror — /Thermal 404 시 /ThermalSubsystem fallback. 미지원 시
    {} graceful (collected 이지만 빈 dict). normalize 가 data.thermal 로 passthrough.

    cycle 2026-05-12 (ADR-2026-05-12): `manager_layout` 옵션 인자 추가 (Additive).
    None 시 기존 동작 100% 보존. RMC primary adapter 만 `gather_bmc` 라벨 분기 활성.
    """
    _run = _make_section_runner(all_errors, collected, failed, unsupported)
    creds = (username, password, timeout, verify_ssl)
    # CSUS-R1 (cycle 2026-06-15 실미러 검수): chassis 의존 섹션(power/thermal/network_adapters/
    # system OEM)은 System.Links.Chassis 가 가리키는 compute chassis 를 쓴다. detect_vendor 가
    # 잡은 chassis_uri(Chassis 컬렉션 첫 멤버)는 multi-chassis RMC 환경에서 집계용 RackGroup
    # 이라 PowerSubsystem/ThermalSubsystem/NetworkAdapters 가 비어 false-success/소실을 유발.
    # 단일 chassis vendor 는 Links.Chassis[0] == 첫 멤버라 불변 (Additive, 회귀 안전).
    eff_chassis_uri = _resolve_system_chassis_uri(
        bmc_ip, system_uri, chassis_uri, username, password, timeout, verify_ssl)
    return {
        'system':            _run('system',     gather_system,     bmc_ip, system_uri, vendor, *creds, eff_chassis_uri, product_hint),
        'bmc':               _run('bmc',        gather_bmc,        bmc_ip, manager_uri, vendor, *creds, manager_layout),
        'processors':        _run('processors', gather_processors, bmc_ip, system_uri,          *creds),
        'memory':            _run('memory',     gather_memory,     bmc_ip, system_uri,          *creds),
        'storage':           _run('storage',    gather_storage,    bmc_ip, system_uri,          *creds),
        'network':           _run('network',    gather_network,    bmc_ip, system_uri,          *creds),
        'firmware':          _run('firmware',   gather_firmware,   bmc_ip,                      *creds),
        'power':             _run('power',      gather_power,      bmc_ip, eff_chassis_uri,     *creds),
        # cycle 2026-06-14 (Track 4): 단일노드 thermal (온도 센서 + 팬). 미지원 벤더는 {} graceful.
        'thermal':           _run('thermal',    gather_thermal,    bmc_ip, eff_chassis_uri,     *creds),
        # P4 (cycle 2026-04-28): NIC 카드 + port-level + FC HBA / InfiniBand 분류
        # cycle 2026-08-03: system_uri 전달 — Chassis 경로 실패 시 Systems 경로 fallback
        # (펌웨어 세대별 NetworkAdapters 부모 리소스 차이. 상세는 함수 docstring).
        'network_adapters':  _run('network_adapters',
                                   gather_network_adapters_chassis,
                                   bmc_ip, eff_chassis_uri, *creds, system_uri),
    }


def _compute_final_status(collected, failed, errors=None):
    """collected / failed list → final_status (success / partial / failed).

    cycle 2026-04-30: errors[]에 인증 실패 (HTTP 401/403) 흔적 발견 시 'failed' 강제.
    이전 동작은 1개 섹션이라도 collected에 들어가면 'partial' 반환 — try_one_account
    loop가 'partial'을 success로 판정해 두 번째 자격증명으로 fallback 안 함 (Dell vault
    accounts 순서 사고). 인증 자체가 거부된 상태에서 partial로 emit하면 호출자도
    "데이터 일부 받음"으로 오해. auth fail 명시적으로 'failed'로 분류.
    """
    clean = [s for s in collected if s not in failed]

    # 인증 실패 시그널이 errors[]에 있으면 partial/success로 끌어올리지 않음
    if errors:
        for e in errors:
            if not isinstance(e, dict):
                continue
            detail = str(e.get('detail') or '')  # Round 4 #11: 비-str detail(int 등) 'in' TypeError 방어
            msg = str(e.get('message') or '')
            if ('HTTP 401' in detail or 'HTTP 403' in detail
                    or 'HTTP 401' in msg or 'HTTP 403' in msg):  # Round 11 #2: msg 측 40x 도 감지
                return 'failed', clean
            if '401' in msg and 'auth' in msg.lower():
                return 'failed', clean

    if not clean:
        return 'failed', clean
    if failed:
        return 'partial', clean
    return 'success', clean


# ── P2 (cycle 2026-04-28): AccountService — 공통계정 자동 생성/복구 ──────────
# vendor 분기는 Redfish API spec OEM namespace 의존 (rule 96 R1 외부 계약).
# Dell  : slot 기반 PATCH (/Accounts/{N}, N=1..17). POST 미지원
# HPE / Lenovo / Supermicro: POST /Accounts 표준
# Cisco : AccountService 표준 미지원 (errors[]에 not_supported 기록 후 종료)

# 2026-08-12 (rev.2): vendor -> create method 표(`_ACCOUNT_CREATE_STRATEGY`)를 제거했다.
#   production 소비자가 0건인데 `_ACCOUNT_FAMILIES` 와 **다른 답**을 담고 있었다
#   (예: cisco -> post_id_role_remap 무조건. 실제로는 Roles 어휘에 따라
#   cisco_bmc_dynamic 이나 generic 이 될 수 있다). 정본이 둘이면 둘 다 못 믿는다.
#   생성 방식의 정본은 `_ACCOUNT_FAMILIES[...]['create_method']` 하나다.

# ══════════════════════════════════════════════════════════════════════════════
# Account Capability Discovery (읽기 전용) — 2026-08-12
#
# 왜 필요한가:
#   종전 계정 코드는 AccountService body 에서 `Accounts.@odata.id` 하나만 읽었다.
#   그래서 (a) 계정 목록을 못 읽은 것과 계정이 없는 것을 구분하지 못했고,
#   (b) 쓰기 방식을 vendor 이름만으로 정했으며, (c) 쓰기가 실패하면 다른 payload 로
#   순차 재시도(=무작위 Write fallback)해서 어느 것이 맞는 방식인지 끝내 알 수 없었다.
#
#   9 Vendor 공식 조사 결과 같은 vendor 안에서도 Write 계약이 갈린다:
#     Lenovo XCC Purley = 빈 slot PATCH / Whitley·XCC2·XCC3·TSM = Collection POST
#     Cisco IMC = RoleId 'admin' + 명시 Id / 최신 Cisco BMC = 'Administrator' + BMC 할당 Id
#     Supermicro X13 01.05.xx+ / X14 01.02.xx.xx+ = IPMI/Redfish 계정 분리
#     Inspur M6 = HTTP 200 + Oem.Public.Status 0, PATCH 는 If-Match 요구
#   따라서 **쓰기 전에 읽기만으로 Family 를 확정하고, 확정된 방식 하나만 실행**한다.
# ══════════════════════════════════════════════════════════════════════════════

# 계정 열거 상태. 이 셋을 구분하지 못하면 "못 읽었다" 가 "없다" 로 둔갑한다.
ENUM_COMPLETE = 'complete'
ENUM_INCOMPLETE = 'incomplete'
ENUM_FAILED = 'failed'

# 표준 계정 존재 판정. CREATE 는 ABSENT 에서만 도달할 수 있다.
PRESENCE_PRESENT = 'present'
PRESENCE_ABSENT = 'absent'
PRESENCE_UNKNOWN = 'unknown'
PRESENCE_AMBIGUOUS = 'ambiguous'


def _get_response_etag(bmc_ip, path, username, password, timeout, verify_ssl):
    """단일 리소스의 ETag 만 얻는다 (If-Match 가 필요한 Family 전용).

    `_get()` 은 헤더를 돌려주지 않고, 그 시그니처는 인증 관측(_record_auth_status)
    계약과 테스트 seam 에 묶여 있어 바꾸지 않는다. 대신 ETag 가 실제로 필요한
    Family(현재 Inspur M6)에서만 이 함수로 1회 더 읽는다.
    source: Inspur Redfish User Manual V1.2 §4.6 (GET → ETag → PATCH If-Match)
    """
    url = f'https://{bmc_ip}/redfish/v1/{path.lstrip("/")}'
    req = urlreq.Request(url, headers={
        'Authorization': _auth(username, password),
        'Accept': 'application/json',
        'OData-Version': '4.0',
    })
    try:
        with urlreq.urlopen(req, context=_ctx(verify_ssl), timeout=timeout) as resp:
            resp.read()
            etag = resp.headers.get('ETag') if hasattr(resp, 'headers') else None
            _record_auth_status(resp.status)
            return etag or None
    except urlerr.HTTPError as e:
        _record_auth_status(e.code)
        return None
    except (urlerr.URLError, socket.timeout, OSError, ValueError):
        return None


def _patch_account(bmc_ip, path, body, username, password, timeout, verify_ssl,
                   headers=None):
    """계정 PATCH 래퍼. 헤더가 필요 없을 때는 `_patch` 를 **종전 시그니처 그대로** 부른다.

    이유: `_patch` 는 테스트가 monkeypatch 하는 seam 이다. 헤더 인자를 항상 넘기면
    기존 fake 들이 전부 깨진다. If-Match 가 실제로 필요한 Family 에서만 확장 호출한다.
    """
    if headers:
        return _patch(bmc_ip, path, body, username, password, timeout, verify_ssl,
                      extra_headers=headers)
    return _patch(bmc_ip, path, body, username, password, timeout, verify_ssl)


def _account_policy_of(service):
    """AccountService body → 정책 필드. 없는 값은 None 으로 남긴다(0 으로 접지 않는다)."""
    if not isinstance(service, dict):
        service = {}
    def _num(key):
        v = service.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) else None
    def _oem_num(key):
        """Oem 하위 namespace 를 **이름으로 분기하지 않고** 훑어 정수 항목을 찾는다.

        표준 AccountService 에는 '인증 실패 후 지연' 항목이 없어서 벤더가 Oem 에 둔다
        (HPE: Oem.Hpe.AuthFailureDelayTimeSeconds). namespace 이름을 하드코딩하면
        rule 12 R1 위반이자 새 벤더마다 코드가 늘어난다. 키 이름만 보고 값을 읽는다.
        """
        oem = service.get('Oem')
        if not isinstance(oem, dict):
            return None
        for section in oem.values():
            if isinstance(section, dict):
                v = section.get(key)
                if isinstance(v, int) and not isinstance(v, bool):
                    return v
        return None
    supported = _safe(service, 'SupportedAccountTypes', default=None)

    def _auth_methods():
        """Oem 하위에서 인증 방식 스위치를 **이름으로 분기하지 않고** 찾는다.

        upstream OpenBMC 는 `Oem.OpenBMC.AuthMethods` 에 BasicAuth/SessionToken/…
        를 노출한다. namespace 를 하드코딩하면 rule 12 R1 위반이므로 키 이름만 본다.
        """
        oem = service.get('Oem')
        if not isinstance(oem, dict):
            return None
        for section in oem.values():
            if isinstance(section, dict) and isinstance(section.get('AuthMethods'), dict):
                return {k: v for k, v in section['AuthMethods'].items()
                        if isinstance(v, bool)}
        return None

    return {
        'service_enabled':        _safe(service, 'ServiceEnabled', default=None),
        'min_password_length':    _num('MinPasswordLength'),
        'max_password_length':    _num('MaxPasswordLength'),
        'lockout_threshold':      _num('AccountLockoutThreshold'),
        'lockout_duration':       _num('AccountLockoutDuration'),
        'lockout_counter_reset':  _num('AccountLockoutCounterResetAfter'),
        # 장비가 선언한 '인증 실패 후 지연'. 재인증 확인 간격을 여기서 끌어온다.
        'auth_failure_delay_seconds': _oem_num('AuthFailureDelayTimeSeconds'),
        'auth_failures_before_delay': _oem_num('AuthFailuresBeforeDelay'),
        'supported_account_types': [s for s in _as_list(supported) if isinstance(s, str)] or None,
        # 2026-08-12 (rev.2): 인증 방식 자체가 꺼져 있을 수 있다.
        #   Dell iDRAC9 7.30.10.50+ / iDRAC10 1.30.10.50+ 는 기본이 `Unadvertised` 이고,
        #   Lenovo XCC3 도 `Unadvertised` 다. **Unadvertised != Disabled** 이며,
        #   이 client 는 처음부터 Authorization 헤더를 보내므로 Unadvertised 와 호환된다.
        #   `Disabled` 를 '비밀번호가 틀렸다' 로 오진하지 않기 위해 상태를 남긴다.
        #   **정책을 바꾸지 않는다 — 읽기만 한다.**
        # source: Dell KB 000437501, pubs.lenovo.com/xcc3-restapi (02 §24, 03 §23, 09 §23)
        'http_basic_auth': _str(_safe(service, 'HTTPBasicAuth', default='')) or None,
        'auth_methods':    _auth_methods(),
    }


def _account_login_interfaces(acc_data):
    """계정 Resource 에서 **Login Interface 목록**을 관측한다 (Huawei 고유 축).

    Huawei iBMC 는 Local User 마다 Web / SNMP / IPMI / SSH / SFTP / Local / **Redfish**
    인터페이스를 개별로 켜고 끈다. 즉 계정이 있고 권한도 맞고 비밀번호도 맞는데
    `Redfish` 가 꺼져 있으면 Redfish 인증이 실패한다. 이것을 모르면 그 실패를
    "비밀번호 불일치" 로 오진하고 쓸데없는 Account Write 를 유발한다.

    **읽기 전용이다.** 이 값을 켜는 정확한 OEM payload 는 공식 자료에서 확인되지 않았고,
    추측해서 쓰지 않는다 (07 §12/§37). 관측해서 진단에만 쓴다.

    OEM namespace 이름으로 분기하지 않고 키 이름만 본다 (rule 12 R1).
    source: Huawei "Setting the User Interfaces for Logging to iBMC" (07 §10)
    """
    oem = _safe(acc_data, 'Oem', default=None)
    if not isinstance(oem, dict):
        return None
    for section in oem.values():
        if not isinstance(section, dict):
            continue
        for key, value in section.items():
            if 'logininterface' not in key.replace('_', '').lower():
                continue
            items = [s for s in _as_list(value) if isinstance(s, str)]
            if items:
                return items
    return None


def _role_ids_from_collection(coll):
    """Roles Collection → Role Id 목록. 각 Role 을 개별 GET 하지 않고 URI 마지막 조각을 쓴다.

    RoleId 문자열을 코드가 추측하지 않기 위한 근거다. Cisco IMC 는 'admin',
    최신 Cisco BMC 는 'Administrator', Fujitsu 는 RedfishAdmin 계열을 쓴다.
    """
    ids = []
    for m in _dicts(_safe(coll, 'Members', default=[]) or []):
        uri = _safe(m, '@odata.id')
        if isinstance(uri, str) and uri:
            seg = uri.rstrip('/').rsplit('/', 1)[-1]
            if seg:
                ids.append(seg)
    return ids


def account_service_discover(bmc_ip, username, password, timeout, verify_ssl,
                             manager_uri=None, service_root=None):
    """AccountService 를 **읽기만** 해서 Write 결정에 필요한 근거를 모은다.

    Returns dict:
      service_uri / accounts_uri / roles_uri : 실제 @odata.id (하드코딩 아님)
      service      : AccountService body (실패 시 None — 인증 실패 판정의 정본)
      policy       : _account_policy_of()
      role_ids     : 지원 RoleId 목록 (없으면 [])
      accounts     : [{slot_uri,id,username,role_id,enabled,locked,account_types,
                       password_change_required,odata_type}]
      member_total : Members@odata.count (없으면 len(Members))
      member_read  : 실제로 읽어낸 member 수
      enumeration  : complete | incomplete | failed
      manager      : {firmware_version, model, manager_type} (manager_uri 있을 때만)
      errors       : [_err(...)]

    **enumeration 이 complete 가 아니면 호출자는 계정 부재를 확정해서는 안 된다.**
    """
    errors = []
    out = {
        'service_uri': None, 'accounts_uri': None, 'roles_uri': None,
        'service': None, 'policy': _account_policy_of(None), 'role_ids': [],
        'accounts': [], 'member_total': None, 'member_read': 0,
        'enumeration': ENUM_FAILED, 'manager': None, 'errors': errors,
        # AccountService GET 의 HTTP status. 401(명시적 인증 거부)과 0/5xx(도달 실패)를
        # 구분해야 lockout 예산을 옳게 쓴다 — transport 오류는 실패 카운터를 올리지 않는다.
        'auth_status': None,
        # ServiceRoot 본문. `RedfishVersion` 이 Family 판정 근거인 Vendor 가 있다
        # (QCT: Legacy v1.1 / Modern v1.11 / Inhouse OpenBMC). 이미 읽은 값을 버리지 않는다.
        'service_root': None,
    }

    # 1) ServiceRoot 가 알려주는 AccountService URI 를 우선한다.
    #    Dell iDRAC7/8·초기 iDRAC9 는 Manager-scoped(/Managers/<id>/AccountService) 를 쓴다.
    #    링크가 없으면 종전 하드코딩 경로로 되돌아간다 (회귀 방지).
    root = service_root if isinstance(service_root, dict) else None
    if root is None:
        code_r, root_data, _err_r = _get(bmc_ip, '', username, password, timeout, verify_ssl)
        root = root_data if code_r == 200 else None
    out['service_root'] = root
    svc_uri = _safe(root, 'AccountService', '@odata.id') if root else None
    out['service_uri'] = _p(svc_uri) if isinstance(svc_uri, str) and svc_uri else 'AccountService'

    # 2) AccountService 본문 — 이 GET 성공이 곧 복구 자격의 인증 시험이다.
    code, service, err = _get(bmc_ip, out['service_uri'], username, password, timeout, verify_ssl)
    out['auth_status'] = code
    if code != 200 or err:
        errors.append(_err('account_service', 'GET AccountService 실패',
                           detail=err or f'HTTP {code}'))
        return out
    out['service'] = service
    out['policy'] = _account_policy_of(service)
    out['enumeration'] = ENUM_INCOMPLETE

    roles_link = _safe(service, 'Roles', '@odata.id')
    if isinstance(roles_link, str) and roles_link:
        out['roles_uri'] = _p(roles_link)
        code_ro, roles_coll, err_ro = _get(
            bmc_ip, out['roles_uri'], username, password, timeout, verify_ssl)
        if code_ro == 200 and not err_ro:
            out['role_ids'] = _role_ids_from_collection(roles_coll)
        # Roles 조회 실패는 enumeration 완결성과 무관하다 (RoleId 는 fallback 이 있다).

    accounts_link = _safe(service, 'Accounts', '@odata.id')
    if not accounts_link:
        errors.append(_err('account_service', 'AccountService.Accounts 링크 없음',
                           detail=str(service)[:200]))
        return out
    out['accounts_uri'] = _p(accounts_link)

    # 3) Accounts Collection
    code, acc_coll, err = _get(bmc_ip, out['accounts_uri'], username, password, timeout, verify_ssl)
    if code != 200 or err:
        errors.append(_err('account_service', 'GET Accounts 컬렉션 실패',
                           detail=err or f'HTTP {code}'))
        return out

    members = _safe(acc_coll, 'Members', default=[]) or []
    if not isinstance(members, list):  # rule 95 R1 #2 (Round 1 #25)
        members = []
    declared = _safe(acc_coll, 'Members@odata.count', default=None)
    out['member_total'] = declared if isinstance(declared, int) and not isinstance(declared, bool) \
        else len(members)

    member_failures = 0
    capped = _capped(members, 'account_service', errors)  # Round 6 #8: 무경계 순회 DoS 방어
    truncated = len(capped) < len(members)
    for m in capped:
        slot_uri = _safe(m, '@odata.id')
        if not slot_uri:
            member_failures += 1
            continue
        code_a, acc_data, err_a = _get(bmc_ip, _p(slot_uri), username, password,
                                       timeout, verify_ssl)
        if code_a != 200 or err_a:
            errors.append(_err('account_service', f'GET {slot_uri} 실패',
                               detail=err_a or f'HTTP {code_a}'))
            member_failures += 1
            continue
        acct_types = _safe(acc_data, 'AccountTypes', default=None)
        out['accounts'].append({
            'slot_uri': slot_uri,
            'id':       _safe(acc_data, 'Id'),
            'username': _safe(acc_data, 'UserName', default=''),
            'role_id':  _safe(acc_data, 'RoleId',   default=''),
            'enabled':  bool(_safe(acc_data, 'Enabled', default=False)),
            'locked':   _safe(acc_data, 'Locked', default=None),
            # 2026-08-12: 최신 Lenovo XCC2/3 · Supermicro X13/X14 · Cisco BMC 는
            #   AccountTypes 에 'Redfish' 가 없으면 계정이 있어도 Redfish 인증이 막힌다.
            'account_types': [s for s in _as_list(acct_types) if isinstance(s, str)]
                             if acct_types is not None else None,
            'password_change_required': _safe(acc_data, 'PasswordChangeRequired', default=None),
            'odata_type': _safe(acc_data, '@odata.type', default=''),
            'has_username_key': isinstance(acc_data, dict) and 'UserName' in acc_data,
            # 2026-08-12 (rev.2): 자동화가 건드리면 안 되는 특수 계정인가.
            #   `HostBootstrapAccount` 는 DMTF ManagerAccount 표준 Property 이고
            #   (schema/redfish_dmtf_2026.1/ManagerAccount.v1_14_1.json), 실미러
            #   tests/reference/redfish/lenovo/10_50_11_232 의 계정 3개에 실제로 존재한다.
            #   즉 **XCC3 전용 개념이 아니다.** slot id 문자열로 맞히지 않고 이 값을 본다.
            'host_bootstrap': _safe(acc_data, 'HostBootstrapAccount', default=None),
            # Huawei 고유 축 — 계정별 Redfish 접근 스위치 (읽기 전용, 07 §10).
            'login_interfaces': _account_login_interfaces(acc_data),
        })
    out['member_read'] = len(out['accounts'])

    # 4) 완결성 판정 — 하나라도 빠지면 complete 가 아니다.
    if member_failures == 0 and not truncated and out['member_read'] == out['member_total']:
        out['enumeration'] = ENUM_COMPLETE
    else:
        errors.append(_err(
            'account_service',
            '계정 목록을 완전히 읽지 못했습니다. 계정 부재를 확정할 수 없습니다.',
            detail=(f'members declared={out["member_total"]} read={out["member_read"]} '
                    f'failures={member_failures} truncated={truncated}'),
        ))

    # 5) Manager 정보 (Firmware/Model) — Supermicro 계정분리 경계처럼 Firmware 가
    #    Strategy 근거인 Family 가 있다. 이미 인증된 자격이라 lockout 위험이 없다.
    if manager_uri:
        code_m, mgr, err_m = _get(bmc_ip, _p(manager_uri), username, password,
                                  timeout, verify_ssl)
        if code_m == 200 and not err_m:
            out['manager'] = {
                'firmware_version': _str(_safe(mgr, 'FirmwareVersion', default='')) or None,
                'model':            _str(_safe(mgr, 'Model', default='')) or None,
                'manager_type':     _str(_safe(mgr, 'ManagerType', default='')) or None,
            }
    return out


# 표준 계정 이름이 보호 대상 Resource 와 겹쳤다. 자동으로 건드리지 않는다.
PRESENCE_PROTECTED_CONFLICT = 'protected_conflict'


def account_is_protected(account, family=None):
    """자동화가 **건드리면 안 되는** 특수 계정인가.

    근거는 **Resource Property** 하나다: `HostBootstrapAccount == true`.
      DMTF ManagerAccount 표준 Property 이고(schema/redfish_dmtf_2026.1/
      ManagerAccount.v1_14_1.json), 실미러 10.50.11.232 의 계정 3개에 실제로 존재한다.
      즉 XCC3 전용 개념이 아니다. Family 이름이나 slot 번호로 맞히지 않는다.

    **Family 의 `reserved_slot_ids` 는 여기 쓰지 않는다.** 그것은 "생성할 때 이 슬롯은
    고르지 마라"(Dell slot 1 = IPMI anonymous 등)는 뜻이지, "그 슬롯에 있는 계정은
    고칠 수 없다" 는 뜻이 아니다. 둘을 섞으면 예약 슬롯에 정상적으로 자리 잡은 표준
    계정을 영영 복구하지 못한다. 생성 후보 제외는 create 경로에서 따로 한다.

    보호 계정은 **열거와 진단에는 그대로 남긴다.** 후보에서만 뺀다 —
    목록에서 지워 버리면 "없는 계정" 이 되어 오히려 생성 쓰기를 유발한다.
    """
    if not isinstance(account, dict):
        return False
    return account.get('host_bootstrap') is True


def account_presence(discovery, target_username, family=None):
    """(state, matches) — 표준 계정이 있는가/없는가/알 수 없는가/건드리면 안 되는가.

    ABSENT 는 **완전한 열거에 성공했고 그 안에 없을 때만** 확정한다.
    403 / 5xx / timeout / 링크 부재 / member 일부 실패는 전부 UNKNOWN 이다.

    표준 계정 이름이 보호 대상 Resource 와 겹치면 PROTECTED_CONFLICT 다 — 이름이 같다는
    이유로 HostBootstrap 같은 특수 계정의 비밀번호를 바꾸는 일은 하지 않는다.
    """
    accounts = (discovery or {}).get('accounts') or []
    matches = [a for a in accounts if (a.get('username') or '') == target_username]
    protected = [a for a in matches if account_is_protected(a, family)]
    if protected:
        return PRESENCE_PROTECTED_CONFLICT, protected
    if len(matches) > 1:
        return PRESENCE_AMBIGUOUS, matches
    if matches:
        return PRESENCE_PRESENT, matches
    if (discovery or {}).get('enumeration') != ENUM_COMPLETE:
        return PRESENCE_UNKNOWN, []
    return PRESENCE_ABSENT, []


# ── Account Family Strategy Matrix ────────────────────────────────────────────
# 선택 우선순위: 실제 Resource Capability → Vendor → BMC Family → Firmware →
#                Generation/Model → Adapter hint.
# Generation 문자열 하나만 보고 Write URI 를 고르지 않는다.
#
# evidence 의미:
#   proven      = 사이트 실측으로 Write 가 확인된 Family
#   documented  = vendor 공식 문서로 Write 계약이 확인된 Family (실장비 미검증)
#   unverified  = 공식 Write 계약 미확보 → **현행 동작을 그대로 유지**한다
#                 (사용자 결정 2026-08-12: 근거 부족 Family 는 현행 유지 + 라벨)

# ── Property Write Contract ───────────────────────────────────────────────────
# 왜 데이터로 두는가:
#   같은 Property 라도 Family 마다 쓰기 가능 여부가 다르다. 9 Vendor 조사 결과:
#     Locked                 : HPE iLO 는 속성 자체가 없고, Lenovo XCC 는 read-only,
#                              Huawei/Cisco BMC 는 writable, TSM 도 writable
#     PasswordChangeRequired : HPE/Cisco BMC(기존계정)/OpenBMC 는 read-only,
#                              Lenovo XCC1 Whitley·XCC2 는 writable, XCC3 는 목록에 없음
#     AccountTypes           : HPE 는 verify-only, Lenovo XCC2/3 는 writable
#   이 차이를 본문 조건문으로 표현하면 Family 가 늘 때마다 분기가 늘고, 어느 Family 가
#   무엇을 보내는지 한눈에 볼 수 없다. 그래서 **표로 선언하고 코드는 표를 읽는다.**
#
# 상태 5종:
#   writable    쓸 수 있다. 단 실제 drift 가 있을 때만 보낸다(no-op write 금지).
#   read_only   장비가 노출하지만 쓸 수 없다. 보내지 않고 대조만 한다.
#   verify_only 쓰기 대상이 아니지만 **반드시 확인**해야 한다 (예: Redfish 접근권).
#   unsupported 해당 Family 에 존재하지 않는다. 보내지도 대조하지도 않는다.
#   unverified  공식 계약을 확보하지 못했다. **자동으로 쓰지 않는다.** 관측만 한다.
#
# 기본값 정책:
#   최종 기본값은 `unverified` 다 — 모르는 Property 를 writable 로 가정하지 않는다.
#   다만 이번 단계(P1)는 **행동 변화 0** 이 합격 조건이라 현재 동작을 그대로 옮긴 값을
#   쓴다. Family 별 선언을 채운 뒤 기본값을 `unverified` 로 좁힌다(P2).
_ACCOUNT_PROP_DEFAULTS = {
    # 이 셋은 "표준 계정을 만든다/고친다" 는 동작 자체다. 이것까지 unverified 로 두면
    # Reconcile 이 아무것도 하지 못한다. 근거를 확보하지 못한 Family 도 이 셋으로
    # **한 번의 결정적 쓰기**는 수행한다 (프로젝트 UNVERIFIED 정책).
    'Password':               {'create': 'writable',    'repair': 'writable'},
    'RoleId':                 {'create': 'writable',    'repair': 'writable'},
    'Enabled':                {'create': 'writable',    'repair': 'writable'},
    # 나머지 셋은 Vendor 마다 read-only / 미지원 / writable 이 갈리고, 잘못 보내면
    # **요청 전체가 거부**된다. 그래서 계약을 선언하지 않은 Family 에서는 보내지 않는다.
    #   create 는 어느 Family 에서도 이 셋을 실은 적이 없다 — 그 사실을 그대로 적는다.
    'Locked':                 {'create': 'unsupported', 'repair': 'unverified'},
    'PasswordChangeRequired': {'create': 'unsupported', 'repair': 'unverified'},
    'AccountTypes':           {'create': 'unsupported', 'repair': 'unverified'},
}

# 계약을 확보하지 못한 Property 의 최종 상태. P2 에서 `_ACCOUNT_PROP_DEFAULTS` 미선언
# Property 의 기본값이 된다.
PROP_UNVERIFIED = 'unverified'

_ACCOUNT_FAMILY_DEFAULTS = {
    'create_method':            'collection_post',
    # 생성 대상 URI 종류. **Accounts 열거 URI 와 같은 개념이 아니다.**
    #   accounts_collection  : discovery 가 알려준 Accounts Collection 에 POST (현행 기본)
    #   account_service_root : AccountService 자체에 POST (최신 Supermicro 공식 계약)
    #   account_instance     : 개별 Account URI 에 POST (Cisco IMC 3.x)
    # 어떤 경우에도 하나를 실패하면 다른 것으로 갈아타지 않는다.
    'create_uri':               'accounts_collection',
    'needs_explicit_id':        False,
    'id_range':                 None,
    'role_map':                 {},
    'account_types':            None,
    # 쓰지는 않지만 **반드시 있어야 하는** AccountTypes (예: Redfish 접근권 검증).
    'account_types_required':   None,
    'password_change_required': None,   # None=보내지 않음 / False=명시적으로 끈다
    'oem_privileges_namespace': None,
    'reserved_slot_ids':        (),
    # If-Match 는 Family 공통 boolean 이 아니라 **Operation 단위** 계약이다.
    #   Inspur M6: Create = POST Collection (If-Match 없음)
    #              Repair = PATCH Instance + GET ETag → If-Match
    # 하나의 boolean 으로 두면 Create 에도 붙여야 하는 것처럼 읽힌다.
    # source: 浪潮英信服务器 Redfish用户手册 V1.2 §4.4(Create) / §4.6(Update)
    'if_match':                 {'create': False, 'repair': False},
    'write_success':            'generic',
    'evidence':                 'unverified',
    # 비밀번호를 다른 속성과 같은 PATCH 에 담으면 조용히 버리는 Family (HPE iLO).
    'isolated_write_patch':     False,
    # Repair PATCH 에서 **drift 가 없는 writable 속성까지** Password 와 함께 보낼 것인가.
    #
    # 기본은 False = drift-only 다. 실제로 달라진 것만 쓴다.
    #
    # True 는 "공통 Property 를 전부 보내라" 는 뜻이 **아니다.** 그 Family 에서
    # **writable 로 확인된 상태 Property 를 Password 와 함께 보내야만 하는 예외**를 뜻한다.
    # Property Contract 가 read_only / verify_only / unsupported / unverified 라고 말한
    # Property 는 full_body_patch=True Family 에서도 **절대 실리지 않는다**.
    #
    # True 는 LIVE 또는 공식 근거가 있는 Family 에만 명시한다. 한 Family 의 실측을
    # 다른 Vendor/Family 의 기본 동작으로 일반화하지 않는다(rule 25 R7-A-1 의 반대 방향
    # 오용 금지). 특히 UNVERIFIED Family 는 이 값을 상속하지 않는다.
    'full_body_patch':          False,
    # Family 별 Property 쓰기 계약. 미선언 Property 는 _ACCOUNT_PROP_DEFAULTS 를 따른다.
    'props':                    {},
}

_ACCOUNT_FAMILIES = {                                                          # nosec rule12-r1
    # Dell — slot PATCH. slot 1 = IPMI anonymous 예약. iDRAC10 은 slot 2 = root 예약.
    # source: dell.com/.../idrac8_2.70.70.70_ug/configuring-local-users,
    #         dell.com/.../idrac10_1.20.xx_ug/configuring-local-users (ID 1,2 reserved)
    # Locked: GET 에는 있지만 iDRAC9 7.10.70 실측에서 read-only 로 거부됐고(200+본문),
    #   공식 Updatable Property 목록(UserName/Password/RoleId/Enabled)에도 없다.
    # PasswordChangeRequired: 공식 Updatable 목록에 없음 → 보내지 않는다.
    # source: dell.com/.../idrac_3.18.18.18_redfishapiguide/manageraccount,
    #         사이트 실측 10.100.15.34 (02 §8/§9)
    'dell_slot_patch':          {'create_method': 'slot_patch',                # nosec rule12-r1
                                 'reserved_slot_ids': ('1',), 'evidence': 'proven',
                                 'props': {
                                     'Locked': {'create': 'unsupported', 'repair': 'read_only'},
                                     'AccountTypes': {'create': 'unsupported',
                                                      'repair': 'verify_only'},
                                 }},
    'dell_idrac10_slot_patch':  {'create_method': 'slot_patch',                # nosec rule12-r1
                                 'reserved_slot_ids': ('1', '2'), 'evidence': 'documented',
                                 'props': {
                                     'Locked': {'create': 'unsupported', 'repair': 'read_only'},
                                     'AccountTypes': {'create': 'unsupported',
                                                      'repair': 'verify_only'},
                                 }},
    # Cisco IMC/CIMC 4.1~6.0 — Collection POST + 명시 Id + Cisco enum RoleId.
    # source: cisco.com/.../b_Cisco_IMC_REST_API_guide_4_1 + 사이트 실측 10.100.15.2
    'cisco_cimc_collection_post_id': {'needs_explicit_id': True,               # nosec rule12-r1
                                      'id_range': (2, 16),
                                      'role_map': {'Administrator': 'admin',
                                                   'Operator': 'user',
                                                   'ReadOnly': 'readonly'},
                                      'evidence': 'proven'},
    # Cisco IMC 3.x — Collection 이 아니라 **Instance URI 에 POST** 한다.
    #   POST /redfish/v1/AccountService/Accounts/<ID>  (body 에 Id 를 넣지 않는다)
    # source: cisco.com/.../b_Cisco_IMC_REST_API_guide_301 (04 §4.2/§25.1)
    'cisco_cimc3_instance_post': {'create_uri': 'account_instance',            # nosec rule12-r1
                                  'needs_explicit_id': True,
                                  'id_range': (2, 16),
                                  'role_map': {'Administrator': 'admin',
                                               'Operator': 'user',
                                               'ReadOnly': 'readonly'},
                                  'evidence': 'documented'},
    # 최신 Cisco BMC (AMI MegaRAC 기반) — Id 는 BMC 가 정하고 RoleId 는 표준 이름.
    # source: cisco.com/.../b_cisco-bmc-rest-api-guide (1.0/2.0/4.0)
    # BMC 1.1 공식 ManagerAccount: Locked=Writable(관리자 unlock),
    #   PasswordChangeRequired=Read Only(기존 계정), AccountTypes=Read Only.
    #   BMC 2.0 은 Create 에서 PasswordChangeRequired:false 를 지원한다.
    # source: cisco.com/.../b_cisco-bmc-rest-api-guide-1_1, .../2-0-1 (04 §10.3/§11.1)
    'cisco_bmc_dynamic':        {'evidence': 'documented',                     # nosec rule12-r1
                                 'props': {
                                     'Locked': {'create': 'unsupported', 'repair': 'writable'},
                                     'PasswordChangeRequired': {'create': 'writable',
                                                                'repair': 'read_only'},
                                     'AccountTypes': {'create': 'unsupported',
                                                      'repair': 'verify_only'},
                                 }},
    # Lenovo Intel Purley XCC — slot 이 미리 만들어져 있고 UserName=='' 이 빈 슬롯이다.
    # source: pubs.lenovo.com/xcc-restapi/create_an_account_intel_p_based_patch
    # Purley 는 PasswordChangeRequired 자체를 제공하지 않는다. Locked 는 GET 에만 있고
    #   공식 Account Update Property 목록에는 없다.
    # source: pubs.lenovo.com/xcc-restapi/update_userid_password_role_properties_patch (03 §7.3)
    'lenovo_purley_slot_patch': {'create_method': 'slot_patch',                # nosec rule12-r1
                                 'evidence': 'documented',
                                 'props': {
                                     'Locked': {'create': 'unsupported', 'repair': 'read_only'},
                                     'PasswordChangeRequired': {'create': 'unsupported',
                                                                'repair': 'unsupported'},
                                 }},
    # Lenovo Whitley/AMD/XCC2/XCC3/TSM — Collection POST.
    # PasswordChangeRequired 를 명시하지 않으면 TSM 은 default true 라 생성 직후 막힌다.
    # source: pubs.lenovo.com/xcc-restapi/create_an_account_post,
    #         pubs.lenovo.com/tsm/post_create_new_account
    # Whitley/AMD 는 PasswordChangeRequired 가 공식 writable 이고, TSM 은 생략 시 true 라
    #   Create 에서 명시해야 한다. Locked 는 XCC1 이 read-only 인데 TSM 은 writable 이라
    #   두 계약이 이 Family 에 섞여 있다 — 근거가 갈리므로 **쓰지 않는다**(기본 unverified).
    # source: pubs.lenovo.com/xcc-restapi/create_an_account_post,
    #         pubs.lenovo.com/tsm/post_create_new_account, /manager_account (03 §8/§13/§14)
    'lenovo_collection_post':   {'password_change_required': False,            # nosec rule12-r1
                                 'evidence': 'documented',
                                 'props': {
                                     'PasswordChangeRequired': {'create': 'writable',
                                                                'repair': 'writable'},
                                 }},
    # XCC2/XCC3 는 AccountTypes 가 공식 writable 이다. Locked 는 GET 에만 있고 Update
    #   목록에는 없다. PasswordChangeRequired 는 XCC2 만 지원한다(XCC3 분리는 P4).
    # source: pubs.lenovo.com/xcc2-restapi/update_userid_password_role_properties_patch,
    #         pubs.lenovo.com/xcc3-restapi/resource_account_service_accounts (03 §10/§11/§15/§16)
    #
    # full_body_patch: **이 Family 한정 예외다.** 사이트 실측(10.50.11.232 Lenovo XCC)에서
    #   Password 를 단독으로 PATCH 하자 권한 cache 가 손상됐다 — RoleId 는 Administrator 로
    #   보이는데 /Managers 는 AccessDenied 였고, Password 를 Enabled/RoleId 와 함께 보내면
    #   권한이 유지됐다. 그래서 이 Family 는 drift 가 없어도 그 둘을 함께 싣는다.
    #   이 실측을 다른 Vendor/Family 의 기본 동작으로 일반화하지 않는다.
    #   read_only/verify_only/unsupported/unverified Property 는 여기서도 실리지 않는다.
    # source: 사이트 실측 10.50.11.232 (cycle 2026-05-06 F50 phase 4,
    #         tests/evidence/2026-08-12-git-location-live-verification.md §3.2)
    'lenovo_xcc2_accounttypes': {'password_change_required': False,            # nosec rule12-r1
                                 'account_types': ('Redfish',),
                                 'account_types_required': ('Redfish',),
                                 'reserved_slot_ids': ('HostBootStrap',),
                                 'full_body_patch': True,
                                 'evidence': 'documented',
                                 'props': {
                                     'Locked': {'create': 'unsupported', 'repair': 'read_only'},
                                     'PasswordChangeRequired': {'create': 'writable',
                                                                'repair': 'writable'},
                                     'AccountTypes': {'create': 'writable', 'repair': 'writable'},
                                 }},
    # XCC3 — XCC2 와 거의 같지만 **PasswordChangeRequired 가 공식 Create/Update Property
    #   목록에 없다.** XCC2 payload 를 그대로 쓰면 미지원 속성을 보내게 된다.
    #   HostBootstrap 은 slot id 가 아니라 HostBootstrapAccount Property 로 걸러낸다.
    # source: pubs.lenovo.com/xcc3-restapi/create_an_account_post,
    #         .../update_userid_password_role_properties_patch (03 §11.2/§11.3/§15)
    'lenovo_xcc3_accounttypes': {'account_types': ('Redfish',),                # nosec rule12-r1
                                 'account_types_required': ('Redfish',),
                                 'full_body_patch': True,
                                 'evidence': 'documented',
                                 'props': {
                                     'Locked': {'create': 'unsupported', 'repair': 'read_only'},
                                     'PasswordChangeRequired': {'create': 'unsupported',
                                                                'repair': 'unsupported'},
                                     'AccountTypes': {'create': 'writable', 'repair': 'writable'},
                                 }},
    # HPE iLO4 — OEM namespace 가 Hpe 가 아니라 Hp 다.
    # source: hewlettpackard.github.io/ilo-rest-api-docs/ilo4/
    # iLO4 ManagerAccount 에는 Locked / AccountTypes 가 없다.
    # source: hewlettpackard.github.io/ilo-rest-api-docs/ilo4/ (01 §5)
    'hpe_ilo4':                 {'oem_privileges_namespace': 'Hp',             # nosec rule12-r1
                                 'evidence': 'documented',
                                 'props': {
                                     'Locked': {'create': 'unsupported', 'repair': 'unsupported'},
                                     'AccountTypes': {'create': 'unsupported',
                                                      'repair': 'unsupported'},
                                 }},
    # HPE iLO5+ — RoleId 로 충분. source: servermanagementportal.ext.hpe.com/.../managingusers
    #
    # isolated_write_patch: 2026-08-12 사이트 실측 (10.50.11.231 / iLO6 /
    #   ProLiant DL380 Gen11 / Redfish 1.20.0). 같은 계정·같은 값으로 통제 실험:
    #     {Password} 단독            -> HTTP 400 iLO.2.36.InvalidPasswordLength (길이 검사됨)
    #     {Password,Enabled,RoleId}  -> HTTP 200 Base.1.19.AccountModified (같은 잘못된 값인데 통과)
    #   즉 iLO 는 Password 가 다른 속성과 함께 오면 **검사도 적용도 하지 않고 조용히 버린다.**
    #   그런데도 응답은 200 + AccountModified 라 성공과 구분되지 않는다
    #   (속성이 하나도 안 바뀌는 {Enabled,RoleId} PATCH 도 똑같이 AccountModified 를 준다).
    #   그래서 이 Family 는 비밀번호를 **단독 PATCH** 로 쓴다. 무작위 재시도가 아니라
    #   Family 가 미리 확정하는 쓰기 계약이다.
    # PasswordChangeRequired 는 iLO5/6/7 모두 Read Only 다. AccountTypes 는 iLO6 1.64+/
    #   iLO7 에 존재하지만 Read Only 라 **검증에만** 쓴다. Locked 는 공식 ManagerAccount
    #   schema 에 없고 실측(iLO6 v1.73)에서 400 PropertyNotWritableOrUnknown 으로 거부됐다.
    # source: servermanagementportal.ext.hpe.com/.../ilo6_manager_resourcedefns173,
    #         사이트 실측 10.50.11.231 (01 §9/§10/§11)
    'hpe_ilo5plus':             {'isolated_write_patch': True,              # nosec rule12-r1
                                 'evidence': 'proven',
                                 'account_types_required': ('Redfish',),
                                 'props': {
                                     'Locked': {'create': 'unsupported', 'repair': 'unsupported'},
                                     'PasswordChangeRequired': {'create': 'unsupported',
                                                                'repair': 'read_only'},
                                     'AccountTypes': {'create': 'unsupported',
                                                      'repair': 'verify_only'},
                                 }},
    # Supermicro X12/H12 계열 — 공식 Reference Guide 의 /AccountService/Accounts POST
    # source: supermicro.com/manuals/other/redfish-ref-guide-html/.../account-service.htm
    'supermicro_legacy':        {'evidence': 'documented'},                    # nosec rule12-r1
    # Supermicro Gen13 01.05.xx+ / Gen14 01.02.xx.xx+ — IPMI/Redfish 계정 분리 세대.
    # source: supermicro.com/en/support/manuals/product/software/redfish-user-guide/.../accounts.htm
    # 최신 Add Account 는 AccountTypes 를 Create payload 로 공식 지원한다. 반면 기존 계정의
    #   AccountTypes PATCH 는 최신 매뉴얼에서 확인되지 않아 **검증만** 한다.
    # source: supermicro.com/en/support/manuals/.../accounts.htm (05 §9/§11/§35)
    'supermicro_split_account': {'account_types': ('Redfish',),                # nosec rule12-r1
                                 'account_types_required': ('Redfish',),
                                 'evidence': 'documented',
                                 'props': {
                                     'AccountTypes': {'create': 'writable',
                                                      'repair': 'verify_only'},
                                 }},
    # Inspur M6 / ISBMC — HTTP 200 + Oem.Public.Status 0 이어야 성공. PATCH 는 If-Match.
    # source: 浪潮英信服务器 Redfish用户手册 V1.2 §4.4 / §4.6
    # Create 는 Collection POST 이고 **If-Match 를 쓰지 않는다.** Repair(Instance PATCH)만
    # GET 으로 ETag 를 받아 If-Match 로 싣는다. 두 Operation 의 계약이 서로 다르다.
    'inspur_m6':                {'if_match': {'create': False,                 # nosec rule12-r1
                                              'repair': True},
                                 'write_success': 'inspur_oem_status',
                                 'evidence': 'documented'},
    # Huawei iBMC — Collection POST + Instance PATCH 가 2019 MM920 / 2025 Kunpeng 양쪽 공식.
    # source: Huawei EDOC1100372764 (Kunpeng iBMC Redfish), EDOC1100105860 (MM920/921)
    # Huawei 최신 공식 ManagerAccount 는 Locked 를 GET/PATCH 로 정의한다 — 다른 Vendor 와
    #   달리 **실제로 잠긴 계정을 풀 수 있다.** 반대로 PasswordChangeRequired 와
    #   AccountTypes 는 공식 table 에 없어 보내지 않는다 (Huawei 의 축은 Login Interface 다).
    # source: Huawei EDOC1100372764 Kunpeng iBMC Redfish (07 §5/§11/§17/§18)
    'huawei_ibmc':              {'evidence': 'documented',                     # nosec rule12-r1
                                 'props': {
                                     'Locked': {'create': 'unsupported', 'repair': 'writable'},
                                     'PasswordChangeRequired': {'create': 'unsupported',
                                                                'repair': 'unsupported'},
                                     'AccountTypes': {'create': 'unsupported',
                                                      'repair': 'unsupported'},
                                 }},
    # 공식 Write 계약 미확보 Family — 현행 동작(표준 POST + 400/405 retry 사다리)을 그대로 둔다.
    # 대상: Fujitsu iRMC S4/S5/S6, Quanta 전 세대, Cisco UCS X-Series, Lenovo IMM2,
    #       Supermicro X9, Inspur M5/M7, HPE CSUS/Superdome RMC, 그리고 미식별 vendor.
    # 공식 Write 계약 미확보 Family — **한 번의 결정적 쓰기**만 한다.
    #   2026-08-12 (rev.2): 종전의 400/405 후 PasswordChangeRequired 추가 재시도를
    #   제거했다. 이 Family 에 속한 Vendor 들이 바로 그 재시도를 금지한 대상이다.
    'generic_collection_post':  {'evidence': 'unverified'},
    # ── Quanta / QCT ─────────────────────────────────────────────────────────
    # 세 Family 로 나누는 이유는 **동작을 바꾸기 위해서가 아니라 경계를 기록하기 위해서**다.
    #   D43K = Redfish v1.1 / D54U·S24P = Redfish v1.11 / S45Z 등 Xeon 6 = Inhouse OpenBMC.
    #   AST2600 을 쓴다는 사실만으로 OpenBMC 로 판정하면 안 되고(09 §5), QCT Inhouse
    #   OpenBMC 를 upstream bmcweb master 와 같다고 봐도 안 된다(09 §6).
    #   셋 다 Account Write 계약 미확보이므로 동작은 generic 과 동일하다.
    #   특히 AccountTypes 를 ['Redfish'] 로 보내면 upstream 은 StrictAccountTypes 오류를
    #   낸다(Redfish+WebUI 결합) — 그래서 어느 Family 도 AccountTypes 를 쓰지 않는다.
    # source: qct.io D43K / D54U / S24P / S45Z 제품자료 (09 §4/§5/§6/§44)
    'qct_legacy_redfish':       {'evidence': 'unverified'},                    # nosec rule12-r1
    'qct_modern_redfish':       {'evidence': 'unverified'},                    # nosec rule12-r1
    'qct_inhouse_openbmc':      {'evidence': 'unverified'},                    # nosec rule12-r1
}


def account_family(family_id):
    """family id → 기본값이 채워진 Family 레코드 (없는 id 는 generic 으로 접는다)."""
    rec = dict(_ACCOUNT_FAMILY_DEFAULTS)
    rec.update(_ACCOUNT_FAMILIES.get(family_id) or _ACCOUNT_FAMILIES['generic_collection_post'])
    rec['id'] = family_id if family_id in _ACCOUNT_FAMILIES else 'generic_collection_post'
    return rec


def account_prop_contract(family, prop, operation):
    """(Family, Property, create|repair) → 쓰기 계약 5-상태 중 하나.

    Family 가 선언한 값이 우선이고, 없으면 `_ACCOUNT_PROP_DEFAULTS`, 그것도 없으면
    `unverified` 다. **모르는 Property 를 writable 로 가정하지 않는다.**
    """
    declared = (family or {}).get('props') or {}
    entry = declared.get(prop)
    if isinstance(entry, dict) and operation in entry:
        return entry[operation]
    fallback = _ACCOUNT_PROP_DEFAULTS.get(prop) or {}
    return fallback.get(operation, PROP_UNVERIFIED)


def account_prop_writable(family, prop, operation):
    """그 Property 를 이 Operation 에서 **보내도 되는가**.

    `writable` 만 True 다. read_only / verify_only / unsupported / unverified 는
    전부 False — 특히 `unverified` 는 "일단 보내 보고 거부되면 뺀다" 가 아니라
    **애초에 보내지 않는다** 는 뜻이다 (추측성 재시도 금지).
    """
    return account_prop_contract(family, prop, operation) == 'writable'


def account_if_match(family, operation):
    """이 Operation 에서 If-Match 를 실어야 하는가 (Family 계약).

    Family 공통 boolean 이 아니라 Operation 단위다 — Inspur M6 는 Repair 만 요구하고
    Create 는 요구하지 않는다.
    """
    spec = (family or {}).get('if_match')
    if isinstance(spec, dict):
        return bool(spec.get(operation, False))
    return False


def _has_prepopulated_slots(accounts):
    """빈 UserName slot 이 미리 깔려 있는 모델인가 (Purley / Dell slot 모델의 서명).

    "UserName 이 falsy" 만으로 판단하지 않는다 — 키 자체가 없거나 GET 이 실패해
    비어 보이는 것과 실제 빈 문자열을 구분한다 (audit M-1).
    """
    empties = [a for a in accounts
               if a.get('has_username_key') and (a.get('username') or '') == '']
    return len(accounts) >= 8 and len(empties) >= 2


def _fw_at_least(firmware, major, minor):
    """'01.05.12' 같은 Firmware 문자열이 major.minor 이상인가. 파싱 실패 시 None."""
    if not isinstance(firmware, str):
        return None
    nums = re.findall(r'\d+', firmware)
    if len(nums) < 2:
        return None
    try:
        return (int(nums[0]), int(nums[1])) >= (major, minor)
    except (TypeError, ValueError):
        return None


# ── HPE Password isolation 의 Firmware 별 근거 ────────────────────────────────
# HPE Customer Advisory a00159600en_us (2026-05-12):
#   iLO6 v1.73 / v1.74, iLO7 v1.19 / v1.20 에서 UserAccount PATCH 가 일부 파라미터를
#   무시한다. 해결 버전은 iLO6 v1.75+ / iLO7 v1.21+.
#
# 왜 Family 를 쪼개지 않는가:
#   쓰기 **동작**은 전 iLO5/6/7 에서 같다 — Password 단독 PATCH 는 HPE 공식 문서가
#   지원하는 동작이고, 이 저장소는 그것을 안전 전략으로 채택한다. 갈리는 것은 동작이
#   아니라 **그 선택의 근거 수준**이다. 그래서 Family 는 하나로 두고 근거만 분리한다.
#
#   이 구분을 잃으면 iLO6 v1.73 한 대에서 얻은 LIVE-PROVEN 이 iLO5 전체와 Advisory 가
#   이미 고친 v1.75+ 까지 번진다. 그건 조사 결과를 과대표기하는 것이다.
HPE_PATCH_ADVISORY = 'a00159600en_us'

# 근거 수준 3종
ISOLATION_LIVE_PROVEN = 'live_proven'          # 이 저장소 실장비에서 직접 재현
ISOLATION_ADVISORY = 'advisory_derived'        # HPE 공식 Advisory 영향 Firmware
ISOLATION_SAFETY = 'safety_strategy'           # Vendor 필수 계약이 아닌 Repository 선택

_ILO_FW_RE = re.compile(r'iLO\s*(\d+)', re.IGNORECASE)
_ILO_VER_RE = re.compile(r'v?(\d+)\.(\d+)')


def hpe_isolation_evidence(firmware, model=None):
    """HPE Password 단독 PATCH 의 **근거 수준**을 Firmware 로 판정한다.

    반환: (isolation_basis, evidence, advisory_id)

    동작(단독 PATCH 여부)은 바꾸지 않는다 — 라벨만 정확히 한다.
    Firmware 를 읽지 못하면 과대주장하지 않고 `safety_strategy` / `documented` 로 둔다.
    """
    text = ' '.join(x for x in (firmware, model) if isinstance(x, str))
    gen_m = _ILO_FW_RE.search(text)
    gen = int(gen_m.group(1)) if gen_m else None
    ver_m = _ILO_VER_RE.search(firmware if isinstance(firmware, str) else '')
    ver = (int(ver_m.group(1)), int(ver_m.group(2))) if ver_m else None

    if gen == 6 and ver:
        if ver == (1, 73):
            # 2026-08-12 사이트 실측(10.50.11.231 / DL380 Gen11)에서 직접 재현한 유일한 버전.
            return ISOLATION_LIVE_PROVEN, 'proven', HPE_PATCH_ADVISORY
        if ver == (1, 74):
            return ISOLATION_ADVISORY, 'documented', HPE_PATCH_ADVISORY
        # v1.75+ 는 Advisory 가 해결했다고 명시한 버전이다. 구버전 결함을 가정하지 않는다.
        return ISOLATION_SAFETY, 'documented', None
    if gen == 7 and ver:
        if ver in ((1, 19), (1, 20)):
            return ISOLATION_ADVISORY, 'documented', HPE_PATCH_ADVISORY
        return ISOLATION_SAFETY, 'documented', None
    # iLO5 전체, 세대/버전 미상 — Advisory 대상이 아니고 실측 근거도 없다.
    return ISOLATION_SAFETY, 'documented', None


def resolve_account_family(vendor, discovery, adapter_id=None):
    """Write 전에 **읽기만으로** Account Family 를 확정한다.

    반환: (family_record, reasons) — reasons 는 어떤 근거로 골랐는지 진단용 문자열들.
    같은 입력에는 항상 같은 Family 를 돌려준다(결정적). 확정할 근거가 없으면
    'generic_collection_post' 로 접어 **현행 동작을 유지**한다.
    """
    d = discovery or {}
    accounts = d.get('accounts') or []
    roles = [r.lower() for r in (d.get('role_ids') or [])]
    mgr = d.get('manager') or {}
    firmware = mgr.get('firmware_version')
    hint = (adapter_id or '').lower()
    reasons = []
    v = (vendor or '').lower()

    if v == 'dell':                                                            # nosec rule12-r1
        # iDRAC10 은 slot 1 뿐 아니라 slot 2 도 예약이라, 세대를 잘못 잡으면 **쓰기 대상
        # 슬롯이 달라진다.** payload 와 method 는 같지만 URI 가 갈린다.
        #
        # 2026-08-12 실측 사고 (10.100.15.34): 실제로는 iDRAC9 / PowerEdge R760 /
        #   Firmware 7.10.70.00 인데 Family 가 dell_idrac10_slot_patch 로 잡혔다.
        #   원인은 두 겹이다.
        #     (a) Adapter 선택이 **무인증 probe** 단계라 model/firmware fact 가 비어 있고,
        #         비어 있는 fact 는 실격이 아니라 skip 이라 priority 만으로 정해진다
        #         (dell_idrac10 priority 120 > dell_idrac9 100). → adapter_id 가 idrac10.
        #     (b) 여기서 그 adapter_id 를 그대로 세대 근거로 썼다. 나머지 한쪽인
        #         Manager.Model 은 Dell 에서 '<NN>G Monolithic' 형태(이 장비는 16G)라
        #         'idrac10' 이 절대 들어가지 않는 죽은 조건이었다. 결국 **adapter hint
        #         단독으로** Family 가 결정됐다 — 이 함수의 계약(hint 는 마지막 순위) 위반.
        #   이번 장비에서 관측 가능한 차이가 0 이었던 것은 slot 2 를 root 가 쓰고 있어
        #   예약 슬롯 차이가 드러나지 않았기 때문이지, 동작이 같아서가 아니다.
        #
        # 그래서 세대는 **장비가 준 값**에서 정한다: Firmware major 가 유일하게 신뢰할 수
        # 있는 신호다 (iDRAC9 = 4.x~7.x, iDRAC10 = 1.x — adapters/redfish/dell_idrac{9,10}.yml
        # 의 firmware_patterns 와 같은 계약). Model 은 보조, hint 는 근거가 없을 때만.
        # source: dell.com/.../idrac10_1.20.xx_ug/configuring-local-users (ID 1,2 reserved)
        #
        # 주의: _has_prepopulated_slots() 는 세대를 가르지 못한다. 두 Family 모두
        #   slot_patch 이고 16 슬롯 prepopulated 는 iDRAC9/10 양쪽 모두 참이다.
        mdl = (mgr.get('model') or '').lower()
        fw_match = re.match(r'\s*(\d+)\.', str(firmware or ''))
        fw_major = int(fw_match.group(1)) if fw_match else None
        if fw_major in (4, 5, 6, 7):
            gen10 = False                    # Firmware 가 iDRAC9 를 확정한다 — hint 보다 우선
        elif fw_major == 1 or 'idrac10' in mdl:
            gen10 = True
        else:
            gen10 = 'idrac10' in hint        # 근거 없음 → hint 는 마지막 순위
        reasons.append(                                                        # nosec rule12-r1
            f'vendor=dell fw_major={fw_major} model={mdl!r} '
            f'hint_idrac10={"idrac10" in hint} '
            f'prepopulated={_has_prepopulated_slots(accounts)} → idrac10={gen10}')
        return account_family('dell_idrac10_slot_patch' if gen10 else 'dell_slot_patch'), reasons

    if v == 'cisco':                                                           # nosec rule12-r1
        # 실제 Role 어휘가 가장 강한 근거다. CIMC 는 admin/user/readonly,
        # 최신 Cisco BMC 는 Administrator/Operator 를 쓴다.
        if 'admin' in roles and 'administrator' not in roles:
            reasons.append('roles={admin,...} → CIMC enum family')  # nosec rule12-r1
            return account_family('cisco_cimc_collection_post_id'), reasons
        if 'administrator' in roles:
            reasons.append('roles contains Administrator → modern Cisco BMC family')  # nosec rule12-r1
            return account_family('cisco_bmc_dynamic'), reasons
        observed = {(a.get('role_id') or '').lower() for a in accounts}
        if 'admin' in observed and 'administrator' not in observed:
            reasons.append('existing account RoleId=admin → CIMC enum family')  # nosec rule12-r1
            return account_family('cisco_cimc_collection_post_id'), reasons
        if 'administrator' in observed:
            reasons.append('existing account RoleId=Administrator → modern Cisco BMC family')  # nosec rule12-r1
            return account_family('cisco_bmc_dynamic'), reasons
        if 'cisco_bmc' in hint:
            reasons.append('adapter hint cisco_bmc')
            return account_family('cisco_bmc_dynamic'), reasons
        if 'cimc' in hint:  # nosec rule12-r1
            # IMC 3.x 는 Instance URI POST, 4.1+ 는 Collection POST + body Id 다.
            # Manager Firmware major 로 가른다 — adapter hint 는 세대를 구분하지 못한다.
            fw_major = None
            m3 = re.match(r'\s*(\d+)\.', str(firmware or ''))
            if m3:
                fw_major = int(m3.group(1))
            if fw_major == 3:
                reasons.append('adapter hint cisco_cimc + firmware 3.x → Instance POST')  # nosec rule12-r1
                return account_family('cisco_cimc3_instance_post'), reasons
            reasons.append('adapter hint cisco_cimc')
            return account_family('cisco_cimc_collection_post_id'), reasons
        # UCS X-Series 등 근거 없는 Cisco 는 generic 으로 둔다 (추측 Write 금지).
        reasons.append('cisco family evidence 부족 → generic 유지')  # nosec rule12-r1
        return account_family('generic_collection_post'), reasons

    if v == 'lenovo':                                                          # nosec rule12-r1
        # 2026-08-12 (rev.2): **capability-first 로 되돌린다.** 종전에는 adapter hint 를
        #   가장 먼저 봐서 Cisco 분기(capability > hint)와 계약이 달랐다(NEXT_ACTIONS PWC-7).
        #   Dell iDRAC10 오분류가 보여줬듯 hint 는 무인증 probe 결과라 비어 있을 수 있고,
        #   그때는 priority 만으로 정해진다. 장비가 준 값을 먼저 본다.
        if 'imm2' in hint:
            reasons.append('IMM2 는 Redfish AccountService 근거 미확보 → generic 유지')
            return account_family('generic_collection_post'), reasons
        # (1) 장비가 실제로 노출한 AccountTypes — XCC2/XCC3 의 서명이다.
        exposes_account_types = any(a.get('account_types') for a in accounts)
        # (2) HostBootstrapAccount 는 XCC2/XCC3 계열에만 나타나는 표준 Property 다.
        has_bootstrap = any(a.get('host_bootstrap') is not None for a in accounts)
        if exposes_account_types or has_bootstrap or 'xcc3' in hint or 'xcc2' in hint:
            # XCC2 와 XCC3 는 PasswordChangeRequired 계약이 다르다. XCC3 근거가 있을 때만
            # XCC3 로 좁히고, 그 외에는 XCC2(더 넓은 Property 집합) 를 쓴다.
            if 'xcc3' in hint:
                reasons.append('adapter hint xcc3 → PasswordChangeRequired 미지원 Family')  # nosec rule12-r1
                return account_family('lenovo_xcc3_accounttypes'), reasons
            reasons.append(                                                        # nosec rule12-r1
                f'AccountTypes 관측={exposes_account_types} HostBootstrap 관측={has_bootstrap} '
                f'hint={hint!r} → AccountTypes 지원 XCC family')
            return account_family('lenovo_xcc2_accounttypes'), reasons
        # (3) Purley 만 pre-populated empty slot PATCH 로 계정을 만든다. Whitley/AMD 는 POST 라
        #     hint 가 그쪽을 가리키면 slot 관측이 있어도 Purley 로 보지 않는다.
        not_purley_hint = any(k in hint for k in ('whitley', 'amd', 'xcc2', 'xcc3'))
        if _has_prepopulated_slots(accounts) and not not_purley_hint:
            reasons.append('pre-populated empty slots 관측 → XCC Purley slot PATCH')  # nosec rule12-r1
            return account_family('lenovo_purley_slot_patch'), reasons
        reasons.append('dynamic members → Lenovo Collection POST')  # nosec rule12-r1
        return account_family('lenovo_collection_post'), reasons

    if v == 'hpe':                                                             # nosec rule12-r1
        if 'csus' in hint or 'superdome' in hint:
            reasons.append('HPE RMC(CSUS/Superdome) — create payload 공식 근거 미확보 → generic 유지')  # nosec rule12-r1
            return account_family('generic_collection_post'), reasons
        if 'ilo4' in hint:
            reasons.append('adapter hint ilo4 → Oem/Hp namespace')
            return account_family('hpe_ilo4'), reasons
        oem_keys = {k.lower() for k in (_safe(d.get('service'), 'Oem', default={}) or {}).keys()} \
            if isinstance(_safe(d.get('service'), 'Oem', default={}), dict) else set()
        if 'hp' in oem_keys and 'hpe' not in oem_keys:  # nosec rule12-r1
            reasons.append('AccountService.Oem 에 Hp 만 존재 → iLO4 계열')
            return account_family('hpe_ilo4'), reasons
        # Family 는 하나다 — 갈리는 것은 동작이 아니라 **근거 수준**이다.
        # Password 단독 PATCH 는 iLO5/6/7 모두에서 그대로 수행하고, 그것을
        # LIVE-PROVEN 이라고 부를 수 있는 범위만 Firmware 로 좁힌다.
        fam = account_family('hpe_ilo5plus')
        basis, evidence, advisory = hpe_isolation_evidence(firmware, mgr.get('model'))
        fam['isolation_basis'] = basis
        fam['evidence'] = evidence
        fam['firmware_advisory'] = advisory
        reasons.append(                                                        # nosec rule12-r1
            f'iLO5+ (RoleId 기반) firmware={firmware!r} '
            f'isolation_basis={basis} evidence={evidence}'
            + (f' advisory={advisory}' if advisory else ''))
        return fam, reasons

    if v == 'supermicro':                                                      # nosec rule12-r1
        # 계정 분리 세대는 Generation 이 아니라 Firmware 가 경계다.
        split = None
        # Generation + Firmware 를 장비값으로 확정했는가 (Create URI 결정 근거).
        gen_anchor = False
        if any(a.get('account_types') for a in accounts):
            split = True
            reasons.append('기존 계정이 AccountTypes 를 노출 → 계정 분리 세대')
        elif d.get('policy', {}).get('supported_account_types'):
            split = True
            reasons.append('AccountService.SupportedAccountTypes 존재 → 계정 분리 세대')
        elif 'x13' in hint or 'x14' in hint or 'ars' in hint:
            # 계정 분리 경계는 Generation 마다 다르다.
            #   Gen13 01.05.xx+ / Gen14 01.02.xx.xx+ / NVIDIA Superchip 01.04.xx+
            # source: supermicro.com/.../redfish-user-guide/.../accounts.htm (05 §10/§31)
            if 'x13' in hint:
                bound = (1, 5)
            elif 'x14' in hint:
                bound = (1, 2)
            else:                       # ARS = NVIDIA Superchip 계열
                bound = (1, 4)
            newer = _fw_at_least(firmware, *bound)
            split = bool(newer)
            gen_anchor = bool(newer is not None)
            reasons.append(                                                        # nosec rule12-r1
                f'adapter hint {hint} firmware={firmware} boundary={bound} split={split}')
        if split:
            fam = account_family('supermicro_split_account')
            # §3.5 Create URI 결정 규칙:
            #   최신 공식 Add Account 는 `POST /redfish/v1/AccountService` (루트) 다.
            #   그 계약을 쓰려면 Generation + Firmware 를 **장비가 준 값**으로 확정해야 한다.
            #   확정하지 못하면 추측하지 않고 구 Reference Guide 계약(Accounts Collection)
            #   하나만 쓴다. **두 URI 를 순차로 시도하는 fallback 은 만들지 않는다.**
            # source: 05 §9/§34/§39-B
            if gen_anchor:
                fam['create_uri'] = 'account_service_root'
                fam['create_uri_basis'] = 'generation+firmware'
            else:
                fam['create_uri'] = 'accounts_collection'
                fam['create_uri_basis'] = 'unverified_single_strategy'
                fam['evidence'] = 'unverified'
            reasons.append(f'create_uri={fam["create_uri"]} basis={fam["create_uri_basis"]}')
            return fam, reasons
        if 'x9' in hint:
            reasons.append('X9 는 공식 Redfish AccountService 근거 미확보 → generic 유지')
            return account_family('generic_collection_post'), reasons
        reasons.append('Supermicro legacy/Reference Guide family')  # nosec rule12-r1
        return account_family('supermicro_legacy'), reasons

    if v == 'inspur':                                                          # nosec rule12-r1
        oem = _safe(d.get('service'), 'Oem', 'Public', default=None)
        if isinstance(oem, dict) or 'm6' in hint or 'isbmc' in hint:
            reasons.append('Oem.Public 관측 또는 M6/ISBMC hint → Inspur M6 family')
            return account_family('inspur_m6'), reasons
        reasons.append('Inspur M5/M7 은 공식 계약 미확보 → generic 유지')
        return account_family('generic_collection_post'), reasons

    if v == 'quanta':                                                          # nosec rule12-r1
        # 동작은 셋 다 generic 과 같다 — 라벨로 경계를 남겨 다음 작업자가 어느 Family 의
        # Evidence 를 모아야 하는지 알 수 있게 한다. AST2600 만으로 OpenBMC 로 판정하지
        # 않고, QCT Inhouse OpenBMC 를 upstream bmcweb 과 동일시하지도 않는다.
        if 'openbmc' in hint or 'xeon6' in hint or 's45z' in hint or 's25z' in hint:
            reasons.append('QCT Inhouse OpenBMC 계열 — upstream bmcweb 과 동일시하지 않는다')
            return account_family('qct_inhouse_openbmc'), reasons
        redfish_ver = _str(_safe(d.get('service_root'), 'RedfishVersion', default='')) \
            if isinstance(d.get('service_root'), dict) else ''
        if redfish_ver.startswith('1.1.'):
            reasons.append(f'QCT Legacy Redfish {redfish_ver}')
            return account_family('qct_legacy_redfish'), reasons
        if redfish_ver.startswith('1.11'):
            reasons.append(f'QCT Modern Redfish {redfish_ver}')
            return account_family('qct_modern_redfish'), reasons
        reasons.append('QCT Family 근거 부족 → generic 유지 (Account Write 계약 미확보)')
        return account_family('generic_collection_post'), reasons

    if v == 'huawei':                                                          # nosec rule12-r1
        reasons.append('Huawei iBMC Collection POST (공식 문서 근거)')
        return account_family('huawei_ibmc'), reasons

    reasons.append(f'vendor={vendor or "unknown"} — Family 근거 없음 → generic 유지')
    return account_family('generic_collection_post'), reasons


def choose_role_id(family, target_role, discovery):
    """RoleId 문자열을 추측하지 않고 **장비가 지원한다고 말한 값** 중에서 고른다.

    우선순위: 지원 목록의 정확한 일치 → Family role_map 결과가 지원 목록에 있음 →
    기존 계정이 실제로 쓰고 있는 값(대소문자 무시 일치) → Family role_map → 원본.
    """
    supported = [r for r in ((discovery or {}).get('role_ids') or []) if isinstance(r, str)]
    lower = {r.lower(): r for r in supported}
    if target_role in supported:
        return target_role
    mapped = (family.get('role_map') or {}).get(target_role)
    if mapped and mapped in supported:
        return mapped
    if target_role and target_role.lower() in lower:
        return lower[target_role.lower()]
    if mapped and mapped.lower() in lower:
        return lower[mapped.lower()]
    return mapped or target_role


def interpret_write_response(family, code, body, err, requested=None):
    """쓰기 응답을 Family 계약으로 해석한다. (accepted, reason)

    HTTP status 하나로 통일하지 않는다:
      - Dell 은 200 을 주면서 본문으로 요청을 거부한다 (read-only 속성 / 비밀번호 정책).
      - Inspur M6 는 200 + Oem.Public.Status 0 이어야 성공이다.

    `requested` 를 주면 우리가 실제로 보낸 속성을 가리키는 거부만 센다.

    **어떤 거부 종류든 여기서 즉시 실패로 끝난다.** 속성을 빼고 다시 쓰거나 payload 를
    바꿔 재시도하지 않는다 — 그것은 추측성 재시도이고, 9 Vendor 조사가 공통으로 금지한
    패턴이다. 예상하지 못한 거부는 그대로 기록해서 사람이 보게 한다.
    """
    if err or code not in (200, 201, 204):
        return False, (err or f'HTTP {code}')
    rejected = write_rejections(body, requested)
    if rejected:
        detail = ', '.join(
            '{0}={1}{2}'.format(r['property'] or '?', r['kind'],
                                f"({r['message_id']})" if r['message_id'] else '')
            for r in rejected)
        return False, f'rejected: {detail}'
    if family.get('write_success') == 'inspur_oem_status':
        status = _safe(body, 'Oem', 'Public', 'Status', default=None)
        if status is None:
            # 응답이 OEM status 를 담지 않으면 "성공했다" 고 단정하지 않는다.
            return True, 'vendor status absent'
        if status != 0:
            return False, f'Oem.Public.Status={status}'
    return True, None


def _create_target_uri(family, discovery, explicit_id=None):
    """계정 **생성** 대상 URI. 열거 URI 와 같은 개념이 아니다.

    2026-08-12: 종전에는 5곳 모두 리터럴 'AccountService/Accounts' 를 썼다. 열거는
    `AccountService.Accounts.@odata.id` 를 따르면서 쓰기만 하드코딩 경로로 나가면,
    컬렉션이 표준 경로가 아닌 펌웨어(Dell 구세대의 Manager-scoped 경로 등)에서
    "읽기는 되는데 생성은 404" 가 된다. 링크가 없을 때만 종전 경로로 되돌아간다.

    2026-08-12 (rev.2): Vendor 에 따라 **Create URI 자체가 Accounts Collection 이 아니다.**
      최신 Supermicro : POST /redfish/v1/AccountService        (AccountService 루트)
      Cisco IMC 3.x   : POST /redfish/v1/AccountService/Accounts/<ID>  (Instance)
    그래서 "Accounts 를 어디서 읽었는가" 와 "어디에 만드는가" 를 분리한다.

    **하나가 실패하면 다른 URI 로 갈아타지 않는다.** 어느 것을 쓸지는 쓰기 전에
    Family 가 확정한다 (05 §34: 두 Create URI 를 fallback 으로 시도하는 것은 금지).
    """
    d = discovery or {}
    accounts_uri = d.get('accounts_uri') or 'AccountService/Accounts'
    kind = (family or {}).get('create_uri') or 'accounts_collection'
    if kind == 'account_service_root':
        return d.get('service_uri') or 'AccountService'
    if kind == 'account_instance':
        # Instance POST 는 대상 Id 가 있어야 의미가 있다. 없으면 Collection 으로 두고
        # 호출자가 Id 미확정 실패를 그대로 보고하게 한다 (URI 를 추측하지 않는다).
        if explicit_id is None:
            return accounts_uri
        return f'{accounts_uri.rstrip("/")}/{explicit_id}'
    return accounts_uri


def _confirm_account_state(bmc_ip, slot_uri, target_username, family,
                           username, password, timeout, verify_ssl, out):
    """쓰기 뒤 계정 리소스를 **다시 읽어** 실제 상태를 확인한다.

    재인증(=비밀번호가 맞는가)만으로는 Role / Enabled / AccountTypes /
    PasswordChangeRequired 가 의도대로 됐는지 알 수 없다. 여기서 확인한 사실을
    out['post_write_state'] 에 남기고, 어긋난 항목은 errors[] 로 드러낸다.
    이 함수는 **판정을 뒤집지 않는다** — 최종 성공 판정은 표준 자격 재인증이다.
    """
    if not slot_uri:
        return
    code, data, err = _get(bmc_ip, _p(slot_uri), username, password, timeout, verify_ssl)
    if code != 200 or err:
        out['errors'].append(_err(
            'account_service', '쓰기 후 계정 상태를 다시 읽지 못했습니다.',
            detail=err or f'HTTP {code}',
        ))
        return
    acct_types = _safe(data, 'AccountTypes', default=None)
    state = {
        'username':     _safe(data, 'UserName', default=''),
        'enabled':      _safe(data, 'Enabled', default=None),
        'role_id':      _safe(data, 'RoleId', default=''),
        'account_types': [s for s in _as_list(acct_types) if isinstance(s, str)]
                        if acct_types is not None else None,
        'password_change_required': _safe(data, 'PasswordChangeRequired', default=None),
    }
    out['post_write_state'] = state

    # 없는 속성을 "틀렸다" 고 하지 않는다. 응답이 그 키를 실제로 준 경우만 비교한다.
    mismatches = []
    if isinstance(data, dict) and 'UserName' in data and state['username'] != target_username:
        mismatches.append(f'UserName={state["username"]!r}')
    if state['enabled'] is False:
        mismatches.append('Enabled=false')
    if state['password_change_required'] is True:
        mismatches.append('PasswordChangeRequired=true')
    # 2026-08-12 (rev.2): "쓰는 축" 과 "확인해야 하는 축" 을 분리한다.
    #   HPE iLO6/7 · Cisco BMC 는 AccountTypes 가 read-only 라 쓰지 않지만, 그 계정이
    #   Redfish 로 접근 가능한지는 **반드시 확인**해야 한다. 쓰지 않는다는 이유로 검증까지
    #   건너뛰면 "계정은 있는데 Redfish 로는 못 쓰는" 상태를 놓친다 (01 §11, 04 §16, 05 §35).
    want_types = set(family.get('account_types_required')
                     or family.get('account_types') or ())
    if want_types and state['account_types'] is not None \
            and not want_types.issubset(set(state['account_types'])):
        mismatches.append(f'AccountTypes={state["account_types"]}')
    if mismatches:
        out['errors'].append(_err(
            'account_service',
            '표준 계정을 만들었지만 상태가 기대와 다릅니다. 계정 설정을 확인하세요.',
            detail='post-write state mismatch: ' + ', '.join(mismatches),
        ))


def build_create_payload(family, target_username, target_password, role_id,
                         explicit_id=None):
    """Family 가 확정된 뒤 **한 번에** 만드는 생성 payload. 순차 retry 로 채우지 않는다.

    각 Property 는 Family Property Contract(`props`)가 `writable` 이라고 말할 때만 실린다.
    read_only / unsupported / unverified Property 는 **애초에 보내지 않는다** — 보내고
    거부되면 빼는 방식은 추측성 재시도라 금지한다.
    """
    body = {'UserName': target_username}
    if account_prop_writable(family, 'Password', 'create'):
        body['Password'] = target_password
    if account_prop_writable(family, 'Enabled', 'create'):
        body['Enabled'] = True
    if account_prop_writable(family, 'RoleId', 'create'):
        body['RoleId'] = role_id
    if family.get('needs_explicit_id') and explicit_id is not None:
        body['Id'] = explicit_id
    if family.get('password_change_required') is False \
            and account_prop_writable(family, 'PasswordChangeRequired', 'create'):
        body['PasswordChangeRequired'] = False
    if family.get('account_types') and account_prop_writable(family, 'AccountTypes', 'create'):
        body['AccountTypes'] = list(family['account_types'])
    ns = family.get('oem_privileges_namespace')
    if ns:
        body['Oem'] = {ns: {'Privileges': {
            'LoginPriv': True, 'RemoteConsolePriv': True, 'UserConfigPriv': True,
            'VirtualMediaPriv': True, 'VirtualPowerAndResetPriv': True,
            'iLOConfigPriv': True}}}
    return body


def account_service_get(bmc_ip, username, password, timeout, verify_ssl):
    """GET AccountService + Accounts 컬렉션 enumerate (호환 wrapper).

    Returns: (acct_service: dict|None, accounts: list[...], errors)

    2026-08-12: 본문은 account_service_discover() 로 옮겼다. 이 함수는 3-tuple 계약에
    묶인 기존 호출자/테스트를 위해 남는다. **계정 부재를 판정하려는 호출자는 이 함수가
    아니라 account_service_discover() + account_presence() 를 써야 한다** — 3-tuple 은
    "열거가 완전했는가" 를 표현할 수 없어서, 조회 실패가 빈 목록과 구분되지 않는다.
    """
    d = account_service_discover(bmc_ip, username, password, timeout, verify_ssl)
    return d['service'], d['accounts'], d['errors']


def account_service_find_user(accounts, target_username):
    """기존 사용자 slot URI 검색. None 반환 = 미존재.

    주의: 첫 매칭만 반환한다. 동일 username 이 여러 slot 에 있는지 판단해야 하는
    호출자는 account_service_find_all_users() 를 써야 한다 (Phase 6-B §12).
    """
    for acc in accounts:
        if (acc.get('username') or '') == target_username:
            return acc
    return None


def account_service_find_all_users(accounts, target_username):
    """target_username 과 정확히 일치하는 slot **전부** 반환 (Phase 6-B §12).

    account_service_find_user() 는 첫 매칭만 돌려주므로, 같은 username 이 여러 slot 에
    존재하면 "어느 slot 을 고쳐야 하는지" 를 코드가 임의로 정하게 된다. 그 상태에서
    자동 PATCH 를 하면 운영자가 의도하지 않은 slot 의 비밀번호가 바뀔 수 있다.
    따라서 호출자는 이 함수로 개수를 먼저 확인하고, 2개 이상이면 쓰기를 중단한다.

    매칭 규칙은 account_service_find_user() 와 동일한 **대소문자 구분 완전일치** 다
    (실제 PATCH 대상을 고르는 함수와 판정 기준이 어긋나면 안 된다).
    """
    return [acc for acc in accounts if (acc.get('username') or '') == target_username]


def account_service_find_empty_slot(accounts, skip_slot_ids=None):
    """빈 사용자 슬롯 검색 (Dell PATCH 패턴). UserName='' 인 첫 슬롯 반환.

    F49 (cycle 2026-05-01): skip_slot_ids 파라미터 추가 — vendor 별 reserved
    slot 회피. Dell iDRAC9: slot 1 = anonymous reserved (UserName='', Enabled=false,
    PATCH 거부 → recovered=False). 호출자가 ['1'] 전달 시 슬롯 1 건너뛰고 2..N 에서
    빈 슬롯 검색. 다 차있으면 None.
    source: dell.com/support/manuals/.../idrac9_*_redfishapiguide_pub/manageraccount
            (slot 1 = User Account placeholder, 2..17 = actual user slots).
    """
    skip = set(skip_slot_ids or [])
    for acc in accounts:
        if ('' if acc.get('id') is None else str(acc.get('id'))) in skip:
            continue
        if not (acc.get('username') or ''):
            return acc
    return None


def account_service_find_all_empty_slots(accounts, skip_slot_ids=None):
    """빈 슬롯 모두 (slot id 정렬).

    2026-08-12 (audit M-1): "UserName 이 falsy" 하나로 판단하지 않는다. `_safe` 는
    키 부재 / JSON null / 비-dict 를 전부 ''  로 접기 때문에, 그대로 두면 **읽지 못한
    계정을 빈 슬롯으로 분류해 남의 계정을 덮어쓸 수** 있다. 열거 단계에서 `UserName`
    키를 실제로 봤다는 사실(has_username_key)이 있는 항목만 빈 슬롯으로 인정하고,
    Enabled 가 켜져 있으면 (이름은 비었지만 쓰이는 슬롯일 수 있으므로) 제외한다.
    has_username_key 를 제공하지 않는 예전 호출자(테스트 fixture 포함)는 종전처럼
    동작하도록 키가 아예 없을 때만 관대하게 취급한다.
    """
    skip = set(skip_slot_ids or [])

    def _is_empty(a):
        if (a.get('username') or '') != '':
            return False
        if 'has_username_key' not in a:      # 열거 정보가 없는 예전 호출자 — 종전 판정 유지
            return True
        # 실제 열거 결과: UserName 키를 봤어야 하고, 이름이 비었는데 Enabled 면 쓰이는 슬롯일
        # 수 있으므로 건드리지 않는다.
        return bool(a.get('has_username_key')) and not a.get('enabled')

    empties = [
        a for a in accounts
        if ('' if a.get('id') is None else str(a.get('id'))) not in skip and _is_empty(a)
    ]
    # id 가 숫자면 숫자 정렬, 아니면 문자열 정렬
    def _key(a):
        try:
            return (0, int(a.get('id') or '0'))
        except (ValueError, TypeError):
            return (1, ('' if a.get('id') is None else str(a.get('id'))))
    empties.sort(key=_key)
    return empties


def account_service_provision(
    bmc_ip, vendor, current_username, current_password,
    target_username, target_password, target_role,
    timeout, verify_ssl, dryrun=True, allow_delete_recreate=False,
    adapter_id=None, manager_uri=None, service_root=None,
):
    """공통계정(target) 생성 또는 복구.

    Args:
        bmc_ip:           BMC IP
        vendor:           정규화 vendor (dell/hpe/lenovo/supermicro/cisco) — vendor 분기용
        current_username: recovery 자격 (현재 인증된 사용자)
        current_password: recovery 자격 비밀번호
        target_username:  생성/복구할 공통계정명 (예: 'infraops')
        target_password:  설정할 공통계정 비밀번호
        target_role:      RoleId (예: 'Administrator')
        timeout:          HTTP timeout
        verify_ssl:       BMC 인증서 검증
        dryrun:           True 시 실제 PATCH/POST 호출하지 않고 시뮬레이션 (default ON)
        allow_delete_recreate:
            기존 계정 PATCH 후 검증이 실패했을 때 DELETE + POST 로 **기존 계정을 지우고
            다시 만드는** fallback 을 허용할지. default False = 지우지 않는다
            (Phase 6-B §11). 상세 근거는 아래 해당 분기 주석 참조.
        adapter_id:       선택된 Gathering Adapter id (Family 선택 **hint** — 단독 근거로
                          쓰지 않는다. 실제 Resource Capability 가 우선한다).
        manager_uri:      Manager @odata.id (Firmware/Model 을 Family 근거로 쓸 때).
        service_root:     이미 읽어 둔 ServiceRoot body (있으면 재요청하지 않는다).

    Returns:
        dict: {
          'recovered':       bool,
          'method':          'patch_existing' | 'patch_empty_slot' | 'post_new' | 'delete_repost' | 'noop' | 'not_supported' | 'ambiguous',
          'slot_uri':        '...' or None,
          'dryrun':          bool,
          'account_existed': bool,          # 대상 username 이 이미 있었는가
          'action':          'create' | 'password_sync' | 'none' | 'ambiguous',
          'verification':    'verified' | 'failed' | 'skipped' | 'none',
          'auth_ok':         bool,          # 복구 자격이 AccountService 인증에 성공했는가
          'write_response_info': str|None,  # 쓰기 응답의 @Message.ExtendedInfo 축약
          'verify_attempts': int,           # 재인증 확인 시도 횟수 (해당 경로에서만)
          'errors':          [_err(...), ...],
        }

    action / verification 의미 (Phase 6-B §17 — 운영 추적용):
      action.create        신규 계정을 만들었거나 만들려 했다 (대상 계정이 없었음)
      action.password_sync 이미 있는 계정의 비밀번호를 vault 값과 맞추려 했다
      action.ambiguous     같은 username 이 여러 slot 이라 쓰기를 중단했다 (§12)
      action.none          쓸 대상 자체가 없었다 (AccountService 미지원 등)
      verification.verified 쓴 뒤 새 자격으로 실제 인증까지 확인했다
      verification.failed   썼지만 새 자격 인증이 되지 않았다
      verification.skipped  dryrun 이라 쓰지 않았고 따라서 확인도 하지 않았다
      verification.none     쓰기를 하지 않았다 (2026-08-12 이후 **쓰기가 있었는데
                            'none' 인 결과는 나오지 않는다** — 모든 쓰기 경로가 재조회
                            + 재인증까지 수행하고 verified/failed 로 확정한다)

    presence (2026-08-12 신설):
      present / absent / unknown / ambiguous
      **unknown 에서는 어떤 쓰기도 하지 않는다.** 계정 목록을 완전히 읽지 못한 상태를
      "계정 없음" 으로 오판해 실제 생성 쓰기를 하던 결함(audit C-1)을 구조적으로 막는다.
    """
    out = {
        'recovered':       False,
        'method':          'noop',
        'slot_uri':        None,
        'dryrun':          bool(dryrun),
        'account_existed': False,
        'action':          'none',
        'verification':    'none',
        # 2026-08-12 (audit C-1): 계정 존재 여부의 3-상태. CREATE 는 'absent' 에서만 도달한다.
        'presence':        PRESENCE_UNKNOWN,
        # 확정된 Account Family 와 그 근거 / 신뢰 수준.
        'family':          None,
        'create_method':   None,
        'evidence':        None,
        'family_reasons':  [],
        # 장비가 선언한 계정 정책 (읽기만 — 정책을 바꾸지 않는다). 비밀번호 길이 자체는
        # 기록하지 않고 "선언 범위 안인가" 만 남긴다.
        'policy':          None,
        # 이번 실행에서 소비한 실패 인증 횟수 (username 별) — lockout 예산 추적.
        'auth_budget':     {},
        # 쓰기가 벤더 계약상 수락됐는가 (HTTP status 하나로 판단하지 않는다).
        'write_accepted':  None,
        'vendor_status':   None,
        'dryrun_reason':   None,
        # 쓰기 뒤 계정 리소스를 다시 읽어 확인한 실제 상태 (재인증과 별개 증거).
        'post_write_state': None,
        # 2026-08-12: 복구 자격이 **실제로 인증됐는가**. 이 값이 False 면 아래 어떤
        # 쓰기 경로에도 들어가지 않는다 (§14 — 인증도 안 된 자격으로 BMC 계정을 건드리지 않는다).
        'auth_ok':         False,
        # 복구 자격이 **명시적으로 거부**됐는가 (HTTP 401). transport/timeout 과 구분한다.
        'auth_rejected':   False,
        # PATCH/POST 응답 body 의 @Message.ExtendedInfo 축약. 2xx 에도 벤더가 여기에
        # "적용하지 않았다 / 정책 미충족" 을 담는다. 종전에는 body 를 통째로 버려서
        # 쓰기가 왜 무효였는지 알 근거가 남지 않았다 (2026-08-12 Dell 사례).
        'write_response_info': None,
        # ── Write Convergence 단계 분리 (2026-08-12 rev.2) ────────────────────
        # HTTP 2xx 는 transport 수락일 뿐이다. 아래 축을 각각 남겨야 "무엇까지 됐는지"
        # 를 사람이 구분할 수 있다.
        #   write_http_status  transport accepted
        #   write_accepted     property accepted (벤더 계약 기준)
        #   post_write_state   resource state converged
        #   verification       credential fresh-auth verified
        #   verify_resource    재인증에 실제로 사용한 리소스
        #   (gathering 검증은 Ansible Phase 3 재수집이 담당한다)
        'write_http_status': None,
        'verify_resource':   None,
        # 생성 대상 URI 와 그 종류 (Accounts Collection / AccountService 루트 / Instance).
        'create_uri':        None,
        'create_uri_kind':   None,
        'create_uri_basis':  None,
        # 정책 충돌 / 인증 예산 / 미지원 RoleId / 계정별 Redfish 접근 스위치.
        'policy_conflict':      None,
        'auth_budget_limit':    None,
        'auth_budget_exhausted': False,
        'role_id_unsupported':  False,
        'login_interfaces':     None,
        'write_rejections':     None,
        'errors':          [],
    }

    # 표준 자격으로 재인증하며 실패 횟수를 예산에 적는다.
    #   왜 세는가: 후보 credential loop 와 슬롯 재시도가 합쳐지면 한 run 에서 같은
    #   username 에 실패 인증이 몇 번 나가는지 아무도 모르는 상태였다. Dell IP Blocking
    #   기본값은 60초 창에서 3회, Huawei/Lenovo 는 5회, HPE 는 3회다.
    def _spend_auth(username):
        out['auth_budget'][username] = out['auth_budget'].get(username, 0) + 1

    # Capability Discovery 로 장비가 선언한 인증 실패 패널티를 읽은 뒤 확정된다(아래 1) 단계).
    # 그 전에 호출될 일은 없지만, 미할당 상태가 남지 않게 기본값으로 먼저 묶어 둔다.
    verify_schedule = ACCOUNT_VERIFY_DELAYS
    auth_budget_limit = ACCOUNT_DEFAULT_AUTH_BUDGET

    def _verify_standard_credential():
        """쓴 뒤 표준 자격으로 실제 인증되는지 확인. (ok, code, err, attempts)

        확인 대상 리소스를 결과에 남긴다 — "인증만 됐다" 와 "필요한 리소스에 실제로
        접근된다" 는 다른 주장이고, 어느 쪽을 확인했는지 결과에서 보여야 한다.
        """
        out['verify_resource'] = 'Systems'
        code_v, err_v = None, None
        for attempt, delay in enumerate(verify_schedule):
            # 예산을 넘기면서까지 확인하지 않는다. 여기서 더 시도하면 표준 계정을 잠근다.
            if out['auth_budget'].get(target_username, 0) >= auth_budget_limit:
                out['auth_budget_exhausted'] = True
                out['errors'].append(_err(
                    'account_service',
                    '재인증 확인을 계정 잠금 한도 전에 중단했습니다. '
                    '장비의 계정 잠금 정책과 표준 계정 상태를 확인하세요.',
                    detail=(f'auth budget {auth_budget_limit} reached for standard account; '
                            f'verified attempts={attempt}'),
                ))
                return False, code_v, err_v, attempt
            if delay:
                time.sleep(delay)
            code_v, _, err_v = _get(bmc_ip, 'Systems', target_username, target_password,
                                    timeout, verify_ssl)
            if code_v == 200 and not err_v:
                return True, code_v, None, attempt + 1
            _spend_auth(target_username)
        return False, code_v, err_v, len(verify_schedule)

    # 1) Capability Discovery — 이 호출이 곧 복구 자격의 인증 시험이다.
    #    2026-08-12: AccountService URI 를 하드코딩하지 않고 ServiceRoot 가 알려주는
    #    링크를 따른다 (Dell iDRAC7/8·초기 iDRAC9 는 Manager-scoped 경로를 쓴다).
    discovery = account_service_discover(
        bmc_ip, current_username, current_password, timeout, verify_ssl,
        manager_uri=manager_uri, service_root=service_root,
    )
    acct_service = discovery['service']
    accounts = discovery['accounts']
    errs = discovery['errors']

    # F50 (cycle 2026-05-06): Cisco AccountService 실 지원 확인 (10.100.15.2 사이트 실측).
    # 이전: not_supported 분기 (cycle 2026-04-29 잘못된 결론 — Members=1 만 보고 미지원 분류).
    # 신: 표준 POST 지원하나 Id 필드 명시 필수 (1-15) + RoleId Cisco-specific enum
    #     ('admin'/'user'/'readonly'/'SNMPOnly' — 'Administrator' 거부).
    # source: 사이트 실측 (10.100.15.2 CIMC AccountService.v1_6_0,
    #         POST /Accounts {Id:'2', RoleId:'admin'} → HTTP 201 + 인증 200).
    # cisco 분기는 아래 신규 생성 단계에서 POST body 변형으로 처리.

    # F13 (cycle 2026-05-01): Cisco 외 vendor도 일부 펌웨어가 AccountService 404
    # 응답 가능 (lab 부재 펌웨어 / 펌웨어 hot-fix 시 변동). errs가 404-only 시
    # 'not_supported' 분류 + errors[]에 noise 안 만듦 (Additive — 기존 cisco
    # 분기 + 일반 404 graceful).
    # source: redfish.dmtf.org/schemas/v1/AccountService.json (선택적 endpoint)
    if _is_404_only_error(errs):
        out['method'] = 'not_supported'
        out['action'] = 'none'
        out['errors'].append(_err(
            'account_service',
            f'AccountService 미지원 (vendor={vendor}, HTTP 404)',
        ))
        return out

    # 2026-08-12: AccountService GET 자체가 실패하면 (401 / TLS / timeout / 5xx)
    # **여기서 끝낸다.** 종전에는 그대로 진행해서 accounts=[] 로 "대상 계정 없음" 이 되고,
    # 신규 생성 경로로 들어가 인증도 안 된 자격으로 POST/PATCH 를 시도할 수 있었다.
    # 복구 자격이 인증되지 않았다는 것은 복구를 할 수 없다는 뜻이지, 계정을 만들
    # 자격이 생겼다는 뜻이 아니다.
    #   acct_service is None ⟺ AccountService GET 실패 (account_service_get 계약).
    out['auth_ok'] = acct_service is not None
    # 인증이 **명시적으로 거부**됐는가 (401). timeout / TLS / 5xx 는 여기 해당하지 않는다.
    # 후보 사이 backoff 길이를 이 값으로 정한다 — 실패 카운터를 올리지 않는 오류에
    # 긴 대기를 걸면 정상 장비의 수집 시간만 늘어난다.
    out['auth_rejected'] = (discovery.get('auth_status') == 401)
    if not out['auth_ok']:
        out['method'] = 'noop'
        out['action'] = 'none'
        out['errors'].extend(errs)
        out['errors'].append(_err(
            'account_service',
            '복구 계정으로 계정 관리 서비스에 접근하지 못해 표준 계정 정리를 시작하지 못했습니다.',
            detail='AccountService GET failed with recovery credential; no write attempted',
        ))
        return out

    out['errors'].extend(errs)

    # 1-b) 읽어 낸 정책 / Family 를 결과에 남긴다. 정책은 **바꾸지 않는다**.
    policy = discovery.get('policy') or {}
    min_len, max_len = policy.get('min_password_length'), policy.get('max_password_length')
    pw_len = len(target_password or '')
    within = None
    if min_len is not None or max_len is not None:
        within = ((min_len is None or pw_len >= min_len)
                  and (max_len is None or pw_len <= max_len))
    out['policy'] = {
        'min_password_length': min_len,
        'max_password_length': max_len,
        'lockout_threshold':   policy.get('lockout_threshold'),
        'lockout_duration':    policy.get('lockout_duration'),
        'auth_failure_delay_seconds': policy.get('auth_failure_delay_seconds'),
        'supported_account_types': policy.get('supported_account_types'),
        # 인증 방식 자체가 꺼져 있으면 비밀번호 문제로 오진하기 쉽다 — 상태만 남긴다.
        'http_basic_auth': policy.get('http_basic_auth'),
        'auth_methods':    policy.get('auth_methods'),
        # 비밀번호 길이 자체는 남기지 않는다 (탐색 공간을 줄여 주는 약한 누출).
        'within_declared_bounds': within,
    }
    # 재인증 확인 간격을 장비가 선언한 패널티에 맞춰 넓힌다 (정책은 읽기만 한다).
    verify_schedule = account_verify_delays(policy)
    out['verify_schedule_seconds'] = list(verify_schedule)
    # 실패 인증 예산도 장비가 선언한 값에서 끌어온다 (재시도를 늘리지 않는다).
    auth_budget_limit = account_auth_budget(policy)
    out['auth_budget_limit'] = auth_budget_limit
    # 2026-08-12 (rev.2): 정책 충돌을 **기계가 읽을 수 있는 상태**로 남긴다.
    #   전역 표준 비밀번호는 하나인데 Vendor 정책은 서로 다르다. 예를 들어 Cisco IMC 의
    #   Strong Password(max 14)와 Inspur 의 설정 가능 MinPasswordLength(최대 16)가 같은
    #   사이트에 있으면 두 정책을 동시에 만족하는 비밀번호가 **수학적으로 존재하지 않는다.**
    #   그것은 코드 버그가 아니라 제품 Contract 문제이므로, 무리하게 반복 Write 하지 않고
    #   운영자가 알아볼 수 있는 상태로 노출한다.
    #
    #   **차단하지 않는다**(사용자 결정 2026-08-12). 정책을 완화하지도, 비밀번호를 바꾸거나
    #   회전시키지도 않는다. 계약상 허용된 결정적 Write 를 1회 하고 실제 응답과
    #   Fresh Auth 로 최종 판정한다.
    if isinstance(min_len, int) and isinstance(max_len, int) and min_len > max_len:
        out['policy_conflict'] = {'kind': 'declared_range_impossible',
                                  'min_password_length': min_len,
                                  'max_password_length': max_len}
        out['errors'].append(_err(
            'account_service',
            '장비가 선언한 비밀번호 길이 정책이 서로 모순됩니다. 장비 정책을 확인하세요.',
            detail=f'declared MinPasswordLength={min_len} > MaxPasswordLength={max_len}',
        ))
    elif within is False:
        out['policy_conflict'] = {'kind': 'password_outside_declared_range',
                                  'min_password_length': min_len,
                                  'max_password_length': max_len}
        out['errors'].append(_err(
            'account_service',
            '표준 계정 비밀번호가 장비가 선언한 길이 정책 범위를 벗어납니다. '
            '쓰기는 시도하되 거부될 수 있습니다.',
            detail=f'declared MinPasswordLength={min_len} MaxPasswordLength={max_len}',
        ))

    family, family_reasons = resolve_account_family(vendor, discovery, adapter_id)
    out['family']         = family['id']
    out['create_method']  = family['create_method']
    out['evidence']       = family['evidence']
    out['family_reasons'] = family_reasons
    # 쓰기 동작을 고른 **근거 수준**. live_proven / advisory_derived / safety_strategy 를
    # 구분해 남기지 않으면, 한 대에서 얻은 실측이 Vendor 전체로 번져 보인다.
    out['isolation_basis']   = family.get('isolation_basis')
    out['firmware_advisory'] = family.get('firmware_advisory')
    role_id = choose_role_id(family, target_role, discovery)
    # 2026-08-12 (rev.2): 고른 RoleId 가 장비가 선언한 목록에 없으면 그 사실을 남긴다.
    #   Fujitsu 는 RedfishAdmin / RedfishOperator / RedfishReadOnly 라는 자체 Role 체계를
    #   갖는데, 그것이 곧 `ManagerAccount.RoleId` literal 이라는 근거는 없다(08 §9/§29).
    #   추측해서 바꾸지 않는다 — 보내되, 근거가 없다는 사실을 진단에 남긴다.
    supported_roles = [r for r in (discovery.get('role_ids') or []) if isinstance(r, str)]
    if supported_roles and role_id not in supported_roles:
        out['role_id_unsupported'] = True
        out['errors'].append(_err(
            'account_service',
            '장비가 알려 준 권한 목록에 없는 권한 이름을 사용합니다. '
            '표준 계정의 권한 설정을 확인하세요.',
            detail=f'RoleId={role_id!r} not in device Roles {sorted(supported_roles)}',
        ))

    # 2) 기존 사용자 검색
    #
    # 2026-08-11 (Phase 6-B §12): **전 매칭**을 먼저 센다.
    #   account_service_find_user() 는 첫 매칭만 돌려주므로, 같은 username 이 여러 slot 에
    #   있으면 코드가 임의의 slot 을 골라 PATCH 하게 된다. 그러면 운영자가 보고 있던 slot 이
    #   아닌 다른 slot 의 비밀번호가 조용히 바뀔 수 있다. 어느 쪽이 맞는지 코드가 알 수 없으므로
    #   자동 쓰기를 중단하고 사람이 정리하도록 slot 목록만 남긴다 (값은 남기지 않는다).
    presence, matches = account_presence(discovery, target_username, family)
    out['presence'] = presence

    if presence == PRESENCE_PROTECTED_CONFLICT:
        # 표준 계정 이름이 보호 대상 Resource 와 겹쳤다 (예: HostBootstrapAccount).
        #   이름이 같다는 이유로 특수 계정의 비밀번호/권한을 바꾸면 호스트 부팅 경로 같은
        #   다른 기능이 조용히 망가진다. 사람이 정리하도록 사실만 남기고 끝낸다.
        out['method'] = 'noop'
        out['action'] = 'none'
        out['account_existed'] = True
        slot_ids = [('' if m.get('id') is None else str(m.get('id'))) for m in matches]
        out['errors'].append(_err(
            'account_service',
            '표준 계정 이름이 시스템 예약 계정과 겹쳐 자동 처리를 중단했습니다. '
            '표준 계정 이름 또는 해당 슬롯을 정리한 뒤 다시 시도하세요.',
            detail='protected accounts: ' + ', '.join(s for s in slot_ids if s),
        ))
        return out

    if presence == PRESENCE_AMBIGUOUS:
        slot_ids = [('' if m.get('id') is None else str(m.get('id'))) for m in matches]
        out['method']          = 'ambiguous'
        out['action']          = 'ambiguous'
        out['account_existed'] = True
        out['errors'].append(_err(
            'account_service',
            '동일한 사용자 이름이 여러 계정 슬롯에 존재해 자동 처리를 중단했습니다. '
            '중복 슬롯을 정리한 뒤 다시 시도하세요.',
            detail='duplicate slots: ' + ', '.join(s for s in slot_ids if s),
        ))
        return out

    if presence == PRESENCE_UNKNOWN:
        # 2026-08-12 (audit C-1). 계정 목록을 완전히 읽지 못했다.
        #   "못 읽었다" 는 "없다" 가 아니다. 여기서 생성하면 이미 있는 계정을 못 본 채
        #   같은 이름으로 만들려 들고, 최악에는 남의 슬롯을 건드린다.
        #   Accounts 403 / 5xx / timeout / 링크 부재 / member 일부 실패가 전부 여기로 온다.
        out['method'] = 'noop'
        out['action'] = 'none'
        out['errors'].append(_err(
            'account_service',
            '계정 목록을 완전히 확인하지 못해 표준 계정 생성을 시작하지 않았습니다. '
            '복구 계정의 사용자 관리 권한과 계정 관리 서비스 상태를 확인하세요.',
            detail=(f'enumeration={discovery.get("enumeration")} '
                    f'declared={discovery.get("member_total")} '
                    f'read={discovery.get("member_read")}; no write attempted'),
        ))
        return out

    existing = matches[0] if matches else None

    if existing:
        out['method']          = 'patch_existing'
        out['action']          = 'password_sync'
        out['account_existed'] = True
        out['slot_uri']        = existing.get('slot_uri')
        # §10: "단순 비밀번호 불일치" 와 "계정이 비활성/잠김" 을 구분해 남긴다.
        #   BMC 가 Locked 를 아예 주지 않으면 None 이라 언급하지 않는다 (모름 ≠ 잠기지 않음).
        #   자동 enable/unlock 범위는 넓히지 않는다 — 아래 PATCH body 는 종전과 동일하다.
        if existing.get('enabled') is False:
            out['errors'].append(_err(
                'account_service',
                '대상 계정이 비활성 상태입니다. 비밀번호 불일치가 아니라 계정 비활성이 원인일 수 있습니다.',
                detail=f'slot={existing.get("id")} Enabled=false',
            ))
        if existing.get('locked') is True:
            out['errors'].append(_err(
                'account_service',
                '대상 계정이 잠금 상태입니다. 비밀번호 불일치가 아니라 계정 잠금이 원인일 수 있습니다.',
                detail=f'slot={existing.get("id")} Locked=true',
            ))
        # 2026-08-12 (rev.2): 계정별 Redfish 접근 스위치 (Huawei 고유 축).
        #   계정이 있고 권한도 맞는데 Redfish 가 꺼져 있으면 인증이 실패한다. 그 실패를
        #   비밀번호 문제로 오진하면 필요 없는 Account Write 가 반복된다.
        #   **켜는 payload 는 공식 근거가 없어 구현하지 않는다** — 관측해서 알려만 준다.
        out['login_interfaces'] = existing.get('login_interfaces')
        if existing.get('login_interfaces') is not None \
                and not any(s.lower() == 'redfish' for s in existing['login_interfaces']):
            out['errors'].append(_err(
                'account_service',
                '대상 계정에 Redfish 접근이 허용되어 있지 않습니다. '
                '비밀번호 문제가 아니라 계정의 접근 인터페이스 설정 문제일 수 있습니다.',
                detail=('login interfaces='
                        + ','.join(existing['login_interfaces'])),
            ))
        if dryrun:
            out['verification'] = 'skipped'
            return out
        # F50 phase 4 (cycle 2026-05-06): 기본은 full body PATCH 다 (Password + Enabled +
        # RoleId 함께). 사이트 실측 (10.50.11.232 Lenovo XCC): password 단독 PATCH 시
        # 권한 cache 손상 (RoleId='Administrator' 표시되지만 /Managers AccessDenied).
        # full body PATCH 시 권한 유지 정상.
        # source: 사이트 실측 + Lenovo XCC ManagerAccount.v1_8_1 동작.
        #
        # 2026-08-12: Locked 를 무조건 싣던 것을 **실제로 잠겨 있을 때만** 싣도록 좁힌다.
        #   잠기지 않은 계정에 Locked:false 를 보내는 것은 의미상 no-op 인데, 펌웨어가
        #   이를 거부하면 요청 전체가 죽는다. 실측 4대 중 2대가 거부했다:
        #     iLO6  -> HTTP 400 iLO.2.36.PropertyNotWritableOrUnknown ['Locked']
        #             (ManagerAccount 에 Locked 속성 자체가 없음 → 본문 전체 거부)
        #     XCC   -> Locked 는 노출하지만 read-only 라 거부 → drop 후 retry 로만 통과
        #   즉 no-op 하나 때문에 쓰기를 한 번 더 쓰고 있었다 (Lockout 예산 낭비).
        #   잠긴 계정을 푸는 경로는 그대로 살아 있다 — 그때는 Locked:false 가 실린다.
        #
        # 2026-08-12 (rev.2): 각 속성은 **Family Property Contract 가 writable 이라고
        #   말할 때만** 실린다. read_only / unsupported / unverified 속성은 애초에 보내지
        #   않는다 — 보내고 거부되면 빼는 방식은 추측성 재시도라 금지한다.
        #
        #   기본은 **drift-only** 다 — 실제로 달라진 것만 쓴다(9 Vendor 문서 공통 권고).
        #   `full_body_patch=True` 는 그 Family 에서 writable 로 확인된 상태 Property 를
        #   Password 와 **함께** 보내야만 하는 예외이고, LIVE/공식 근거가 있는 Family 에만
        #   명시한다. 한 Family 의 실측을 다른 Vendor 의 기본 동작으로 일반화하지 않는다.
        #   True 여도 read_only / verify_only / unsupported / unverified 는 실리지 않는다
        #   (아래 account_prop_writable 가 먼저 걸러낸다).
        full_body = bool(family.get('full_body_patch'))
        body_full = {}
        if account_prop_writable(family, 'Password', 'repair'):
            body_full['Password'] = target_password
        if account_prop_writable(family, 'Enabled', 'repair') \
                and (full_body or existing.get('enabled') is not True):
            body_full['Enabled'] = True
        # 2026-08-12: RoleId 문자열을 vendor 이름으로 추측하지 않는다. Roles Collection
        #   또는 기존 계정이 실제로 쓰는 값 중에서 고른다 (choose_role_id). Cisco IMC 는
        #   'admin', 최신 Cisco BMC 는 'Administrator' 라 remap 을 고정하면 한쪽이 깨진다.
        if account_prop_writable(family, 'RoleId', 'repair') \
                and (full_body or (existing.get('role_id') or '') != role_id):
            body_full['RoleId'] = role_id
        # 최신 Lenovo XCC2/3 · Supermicro 계정분리 세대는 AccountTypes 에 Redfish 가 없으면
        # 계정이 살아 있어도 Redfish 인증이 막힌다. Family 가 요구할 때만 함께 맞춘다.
        if family.get('account_types') and existing.get('account_types') is not None \
                and account_prop_writable(family, 'AccountTypes', 'repair'):
            want = set(family['account_types'])
            if not want.issubset(set(existing.get('account_types') or [])):
                body_full['AccountTypes'] = sorted(
                    set(existing.get('account_types') or []) | want)
        # PasswordChangeRequired 가 켜져 있으면 비밀번호를 바꿔도 접근이 막힌다.
        # 장비가 그 속성을 실제로 노출하고 **Family 계약이 writable 일 때만** 끈다.
        #   HPE iLO5/6/7 · Cisco BMC 1.1(기존 계정) · upstream OpenBMC 는 read-only 라
        #   여기에 실으면 요청 전체가 거부된다. 거부된 뒤 빼고 다시 쓰는 것은 금지다.
        if existing.get('password_change_required') is True \
                and account_prop_writable(family, 'PasswordChangeRequired', 'repair'):
            body_full['PasswordChangeRequired'] = False
        # 잠금 해제는 **실제로 잠겨 있을 때만** 요청한다 (위 2026-08-12 주석 참조).
        # Locked 가 read-only 인 Family(HPE iLO / Lenovo XCC)에서는 보내지 않는다.
        if existing.get('locked') is True and account_prop_writable(family, 'Locked', 'repair'):
            body_full['Locked'] = False
        patch_headers = None
        if account_if_match(family, 'repair'):
            # Inspur M6 공식 계약: GET 으로 ETag 를 받고 PATCH 에 If-Match 로 실어야 한다.
            # **Repair 전용이다** — 같은 Family 의 Create(Collection POST)는 요구하지 않는다.
            etag = _get_response_etag(bmc_ip, _p(existing['slot_uri']),
                                      current_username, current_password, timeout, verify_ssl)
            if etag:
                patch_headers = {'If-Match': etag}
        # Family 계약: 비밀번호를 다른 속성과 같은 PATCH 에 담으면 **조용히 버리는** 펌웨어가
        # 있다 (HPE iLO — 위 _ACCOUNT_FAMILIES['hpe_ilo5plus'] 주석의 통제 실험 참조).
        # 그런 Family 는 비밀번호를 단독으로 쓰고, 나머지 속성은 **실제로 달라진 것만**
        # 뒤이어 쓴다. 실패 후 다른 payload 로 갈아타는 무작위 재시도가 아니라, 쓰기 전에
        # Family 가 확정하는 순서다 (재시도 사다리 금지 원칙과 충돌하지 않는다).
        followup_body = {}
        if family.get('isolated_write_patch'):
            followup = {k: v for k, v in body_full.items() if k != 'Password'}
            if followup.get('Enabled') is True and existing.get('enabled') is True:
                followup.pop('Enabled', None)
            if 'RoleId' in followup and existing.get('role_id') == followup.get('RoleId'):
                followup.pop('RoleId', None)
            body_full = {'Password': target_password}
            followup_body = followup
            out['isolated_write'] = True
        code, patch_resp, err = _patch_account(
            bmc_ip, _p(existing['slot_uri']), body_full,
            current_username, current_password, timeout, verify_ssl, patch_headers,
        )
        if code == 412 and account_if_match(family, 'repair'):
            # ETag 가 그 사이 바뀐 경우만 1회 재획득 후 재시도한다 (그 외 재시도 없음).
            # 동일 URI + 동일 Payload + 새 ETag — payload 를 바꾸는 재시도가 아니다.
            etag = _get_response_etag(bmc_ip, _p(existing['slot_uri']),
                                      current_username, current_password, timeout, verify_ssl)
            if etag:
                code, patch_resp, err = _patch_account(
                    bmc_ip, _p(existing['slot_uri']), body_full,
                    current_username, current_password, timeout, verify_ssl,
                    {'If-Match': etag},
                )
        # 2026-08-12 (rev.2): **거부된 속성을 빼고 다시 쓰던 사다리를 제거했다.**
        #   종전에는 400/405 이거나 본문이 read-only 를 지목하면 그 속성을 빼고 한 번 더
        #   PATCH 했다. 이것은 "보내 보고 거부되면 뺀다" 는 추측성 재시도이고, 9 Vendor
        #   조사가 공통으로 금지한 blind write fallback 과 같은 종류다. 무엇이 쓸 수 있는
        #   속성인지는 **쓰기 전에** Family Property Contract 가 정한다(위 body_full 조립).
        #   그래서 이 지점에 도달하는 거부는 "계약이 틀렸거나 펌웨어가 예상 밖" 이라는 뜻이고,
        #   그때 할 일은 재시도가 아니라 **정확히 기록하고 실패로 끝내는 것**이다.
        #   허용되는 다중 쓰기는 두 가지뿐이다: (a) 위 ETag 412 재시도(동일 URI·동일 payload),
        #   (b) Family 가 쓰기 전에 확정한 deterministic sequence(HPE isolated followup).
        # 2026-08-12: 2xx 든 4xx 든 응답 body 의 확장 오류 정보를 **먼저 건진다.**
        #   Dell 은 PATCH 200 과 함께 @Message.ExtendedInfo 로 "무엇을 적용했는지 /
        #   무엇을 거부했는지" 를 돌려준다. 종전에는 body 를 `_` 로 버려서, 쓰기가
        #   수락됐는데 인증이 안 되는 상태의 원인을 알 방법이 아예 없었다.
        out['write_response_info'] = _extended_info(patch_resp) or out.get('write_response_info')
        # 2026-08-12: 성공 판정을 HTTP status 하나로 통일하지 않는다 (Family 계약).
        #   Dell iDRAC10 = 200 + 본문 거부, Inspur M6 = 200 + Oem.Public.Status 0.
        #   transport 수락(status)과 property 수락(accepted)을 각각 남긴다.
        out['write_http_status'] = code
        accepted, reject_reason = interpret_write_response(
            family, code, patch_resp, err, requested=set(body_full))
        out['write_accepted'] = accepted
        out['vendor_status'] = reject_reason
        out['write_rejections'] = write_rejections(patch_resp, set(body_full))
        if not accepted:
            # 2xx 인데 본문이 거부를 말하면 그것은 실패다. 여기서 끝내야 재인증 시도
            # 3회를 헛돌지 않고, 원인(어느 속성이 거부됐는지)이 그대로 남는다.
            out['errors'].append(_err(
                'account_service',
                f'PATCH 기존 사용자 실패 (slot={existing.get("id")})',
                detail=' | '.join(x for x in (
                    reject_reason, out['write_response_info'],
                ) if x),
            ))
            return out
        if followup_body:
            # 비밀번호는 이미 적용됐다. 남은 속성(권한/활성)만 맞춘다. 여기서 실패해도
            # 비밀번호 수렴 자체를 되돌리지 않는다 — 최종 판정은 아래 재조회 + 재인증이다.
            f_code, f_resp, f_err = _patch_account(
                bmc_ip, _p(existing['slot_uri']), followup_body,
                current_username, current_password, timeout, verify_ssl, patch_headers,
            )
            f_ok, f_reason = interpret_write_response(family, f_code, f_resp, f_err)
            out['followup_properties'] = sorted(followup_body)
            out['followup_accepted'] = f_ok
            if not f_ok:
                out['errors'].append(_err(
                    'account_service',
                    '표준 계정 비밀번호는 적용됐지만 계정 속성(권한/활성) 동기화는 거부됐습니다.',
                    detail=' | '.join(x for x in (
                        f'properties={",".join(sorted(followup_body))}',
                        f_reason, _extended_info(f_resp),
                    ) if x),
                ))
        # F50 phase 4: PATCH 후 실 인증 verify — silent fail / 권한 cache 손상 감지.
        # 1차 verify: 새 자격으로 /Systems GET. 401 이면 권한 손상.
        # fallback: DELETE + POST 재생성 (Lenovo XCC 권한 cache 클린 상태 보장).
        #
        # 2026-08-12: **즉시 1회** 만 확인하던 것을 짧은 지연 + 유한 재시도로 바꾼다.
        #   BMC 는 계정 변경을 비동기로 반영하는 경우가 있고, 직전 요청의 연결/세션이
        #   아직 옛 자격으로 살아 있을 수도 있다. 그 상태의 401 을 "적용 실패" 로 확정하면
        #   멀쩡한 쓰기를 실패로 보고하고, 그 다음 단계(계정 삭제 후 재생성)로 사람을 몰아간다.
        #   총 대기 상한은 ACCOUNT_VERIFY_DELAYS 합(=6초)으로 고정한다 — 무한 대기 금지.
        _confirm_account_state(bmc_ip, existing.get('slot_uri'), target_username,
                               family, current_username, current_password,
                               timeout, verify_ssl, out)
        ok_v, verify_code, verify_err, attempts = _verify_standard_credential()
        out['verify_attempts'] = attempts
        if ok_v:
            out['recovered']    = True
            out['verification'] = 'verified'
            return out
        out['verification'] = 'failed'
        # 2026-08-11 (Phase 6-B §11): **기존 계정을 지우는 fallback 은 기본적으로 하지 않는다.**
        #
        # 기존 승인 근거 (그대로 유효한 부분):
        #   docs/ai/catalogs/TEST_HISTORY.md "2026-05-06 (cycle-020 phase 4)" — 사이트 실측
        #   (Lenovo XCC SR650 V2). 이미 존재하던 공통계정이 RoleId=Administrator / Enabled=true
        #   인데도 모든 endpoint 가 AccessDenied 였고, Enabled 토글·RoleId 토글은 실패,
        #   DELETE + POST 재생성만 200 으로 복구됐다. 즉 근거는 **신규 생성 한정이 아니라
        #   기존 계정(=지금 이 경로)** 에 대한 것이다.
        #
        # 그럼에도 기본값을 끄는 이유:
        #   위 실측은 "권한 cache 손상" 이라는 특정 상태에서 나온 것인데, 이 지점에서 코드가
        #   보는 신호는 "새 자격으로의 인증이 안 된다" 뿐이다. 비밀번호가 BMC 정책에 걸려
        #   적용되지 않은 흔한 경우(Dell Security Strengthen Policy 사례와 동일한 silent fail)도
        #   똑같은 신호를 낸다. 둘을 구분할 수 없는 상태에서 지우면, 단순 비밀번호 동기화
        #   실패 때문에 **정상 동작 중이던 운영 계정을 삭제**하게 된다. DELETE 성공 후 POST 가
        #   실패하면 BMC 에 관리자 계정이 하나도 남지 않는다 (docs/ai/contracts/account-write-vendor-compat.md A3
        #   가 지적한 위험이며 같은 문서가 재검토를 권고했다).
        #
        # 그래서 기능을 없애지 않고 **명시적 opt-in** 으로 옮겼다. 운영자가 권한 cache 손상을
        # 확인한 뒤 allow_delete_recreate=True 로 부르면 종전 동작 그대로 복구된다.
        if not allow_delete_recreate:
            out['errors'].append(_err(
                'account_service',
                '기존 계정의 비밀번호를 맞춘 뒤 인증 확인에 실패했습니다. '
                '계정을 지우고 다시 만드는 자동 복구는 하지 않았습니다. 계정 상태를 확인하세요.',
                detail='; '.join(x for x in (
                    (verify_err or f'verify HTTP {verify_code}'),
                    f'slot={existing.get("id")}',
                    f'verify_attempts={out.get("verify_attempts")}',
                    (f'write_response={out["write_response_info"]}'
                     if out.get('write_response_info') else None),
                    'delete_recreate=disabled',
                ) if x),
            ))
            # 2026-08-12: 빈 슬롯 경로(patch_empty_slot)에만 있던 password 정책 힌트를
            #   기존 계정 경로에도 둔다. 두 경로의 실패 모양(PATCH 2xx + 인증 401)이
            #   같은데 한쪽에만 단서가 있어, 같은 사고를 두 번째 경로에서 만나면
            #   원인 후보조차 보이지 않았다. 단정하지 않고 확인할 지점만 제시한다.
            out['errors'].append(_err(
                'account_service',
                '비밀번호가 대상 장비의 암호 정책을 충족하지 못해 적용되지 않았을 수 있습니다. '
                '장비의 암호 정책과 등록된 비밀번호를 확인하세요.',
                detail=(
                    'write accepted but authentication with the new credential failed; '
                    'check BMC password strength policy (length / character classes / '
                    'password history) against the configured value'
                ),
            ))
            return out
        # 권한 손상 감지 — 운영 안전 위해 best-effort fallback.
        # vendor='dell' 은 PATCH-only (POST 미지원) → fallback 불가, errors[] 만 기록.
        # 그 외 vendor (Lenovo/HPE/Supermicro/Cisco/Huawei/Inspur/Fujitsu/Quanta):
        # DELETE + POST 재생성 시도.
        out['errors'].append(_err(
            'account_service',
            f'PATCH 200 후 verify {verify_code} (권한 cache 손상 의심) — '
            f'DELETE+POST 재생성 fallback 시도 (slot={existing.get("id")})',
            detail=verify_err or f'verify HTTP {verify_code}',
        ))
        if vendor == 'dell':                                                   # nosec rule12-r1
            # Dell PATCH-only — DELETE + POST 미지원
            out['errors'].append(_err(
                'account_service',
                'Dell iDRAC PATCH-only — DELETE+POST fallback 미지원 (수동 복구 필요)',  # nosec rule12-r1
            ))
            return out
        # DELETE 시도
        del_code, _, del_err = _delete(
            bmc_ip, _p(existing['slot_uri']),
            current_username, current_password, timeout, verify_ssl,
        )
        if del_code not in (200, 204) or del_err:
            out['errors'].append(_err(
                'account_service',
                f'DELETE 실패 (slot={existing.get("id")}) — fallback 불가',
                detail=del_err or f'HTTP {del_code}',
            ))
            return out
        # POST 재생성 (DELETE 후). PATCH existing 경로만 여기 도달하므로 표준 POST body 를
        # 만들고, vendor=='cisco' 면 RoleId enum remap + Id 필드를 추가한다.
        repost_id = (existing.get('id') or '2') if family.get('needs_explicit_id') else None
        body_post = build_create_payload(
            family, target_username, target_password, role_id,
            explicit_id=repost_id,
        )
        post_code, post_data, post_err = _post(
            bmc_ip, _create_target_uri(family, discovery, repost_id), body_post,
            current_username, current_password, timeout, verify_ssl,
        )
        out['write_http_status'] = post_code
        accepted_r, reason_r = interpret_write_response(family, post_code, post_data, post_err)
        out['write_accepted'] = accepted_r
        out['vendor_status'] = reason_r
        if accepted_r:
            # 삭제하고 새로 만든 계정은 **다시 확인해야 한다.** 여기서 예산이 없다는 이유로
            # 확인을 건너뛰면, 계정을 지워 놓고 그 결과를 보지 않은 채 실패로 보고하게 된다.
            # 예산의 목적은 헛도는 재시도로 계정을 잠그는 것을 막는 것이지, 방금 만든 계정의
            # 검증을 막는 것이 아니다. 그래서 이 한 번의 확인 몫만 상한을 올린다.
            auth_budget_limit += len(verify_schedule)
            out['auth_budget_limit'] = auth_budget_limit
            out['method']   = 'delete_repost'
            out['slot_uri'] = _str(_safe(post_data, '@odata.id')) or existing.get('slot_uri')  # Round 8 #4: 비-str @odata.id
            # 2026-08-12: 재생성 뒤에도 반드시 재조회 + 재인증까지 한다. 종전에는
            #   'none'(확인 안 함)을 성공으로 인정해, 실제로 못 쓰는 계정이 복구됨으로
            #   보고될 수 있었다 (audit H-1).
            _confirm_account_state(bmc_ip, out['slot_uri'], target_username, family,
                                   current_username, current_password, timeout, verify_ssl, out)
            ok_r, vcode_r, verr_r, attempts_r = _verify_standard_credential()
            out['verify_attempts'] = attempts_r
            out['recovered']    = bool(ok_r)
            out['verification'] = 'verified' if ok_r else 'failed'
            if not ok_r:
                out['errors'].append(_err(
                    'account_service',
                    'DELETE+POST 재생성 후 표준 계정 인증에 실패했습니다.',
                    detail=verr_r or f'verify HTTP {vcode_r}',
                ))
        else:
            out['errors'].append(_err(
                'account_service',
                'DELETE+POST 재생성 실패',
                detail=reason_r or post_err or f'HTTP {post_code}',
            ))
        return out

    # ── 3) 신규 생성 — Family Strategy ─────────────────────────────────────
    #
    # 2026-08-12: vendor 이름 분기 + 실패 시 다음 payload 로 순차 재시도(무작위 Write
    # fallback)를 걷어냈다. 읽기 단계에서 Family 를 확정했으므로 **검증된 방식 하나만**
    # 실행한다. 9 Vendor 공식 조사가 공통으로 금지한 패턴이 그 사다리였다:
    #   POST 실패 → 다른 body 로 POST → 또 다른 URI 로 POST …
    # 다만 공식 Write 계약을 확보하지 못한 Family(evidence='unverified')는 사용자 결정
    # (2026-08-12)에 따라 **현행 동작을 그대로 유지**한다 — 근거 없이 동작을 바꾸지 않는다.
    out['method'] = 'patch_empty_slot' if family['create_method'] == 'slot_patch' else 'post_new'
    out['action'] = 'create'

    # 생성 대상 슬롯/Id 결정 — 읽기 단계 결과만 사용한다.
    chosen_slot = None
    explicit_id = None
    if family['create_method'] == 'slot_patch':
        # Dell / Lenovo Purley: 미리 깔린 빈 슬롯에 PATCH 해서 계정을 만든다.
        # 예약 슬롯은 Family 가 안다 (Dell slot 1, iDRAC10 은 slot 1·2).
        # source: dell.com/.../idrac10_1.20.xx_ug/configuring-local-users,
        #         pubs.lenovo.com/xcc-restapi/create_an_account_intel_p_based_patch
        # 보호 계정은 Family 의 reserved id 뿐 아니라 **Resource Property** 로도 걸러낸다.
        protected_ids = {('' if a.get('id') is None else str(a.get('id')))
                         for a in accounts if account_is_protected(a, family)}
        empty_slots = account_service_find_all_empty_slots(
            accounts, skip_slot_ids=set(family['reserved_slot_ids']) | protected_ids,
        )
        if not empty_slots:
            out['errors'].append(_err(
                'account_service',
                '빈 계정 슬롯이 없어 표준 계정을 만들 수 없습니다. 사용하지 않는 계정을 정리하세요.',
                detail=f'family={family["id"]} reserved={sorted(family["reserved_slot_ids"])}',
            ))
            return out
        chosen_slot = empty_slots[0]
        out['slot_uri'] = chosen_slot.get('slot_uri')
    elif family['needs_explicit_id']:
        # Cisco IMC 4.1~6.0 은 POST body 에 Id 를 요구한다 (없으면 BadRequest).
        # 읽지 못한 슬롯을 "비어 있다" 로 세지 않는다 — 열거가 complete 인 경우만 여기 온다.
        lo, hi = family['id_range'] or (2, 16)
        used_ids = {('' if a.get('id') is None else str(a.get('id'))) for a in accounts}
        # 보호 계정 번호는 '비어 있음' 으로 세지 않는다.
        used_ids |= {('' if a.get('id') is None else str(a.get('id')))
                     for a in accounts if account_is_protected(a, family)}
        used_ids |= set(family['reserved_slot_ids'] or ())
        for candidate_id in range(lo, hi):
            if str(candidate_id) not in used_ids:
                explicit_id = str(candidate_id)
                break
        if explicit_id is None:
            out['errors'].append(_err(
                'account_service',
                '사용 가능한 계정 번호가 없어 표준 계정을 만들 수 없습니다. 계정을 정리하세요.',
                detail=f'family={family["id"]} id_range={lo}-{hi - 1} used={sorted(used_ids)}',
            ))
            return out

    if dryrun:
        # dry-run 은 "무엇을 쓸 예정인지" 까지만 남긴다. 실제 쓰기 증거가 아니다.
        out['verification'] = 'skipped'
        return out

    # ── 3-a) 빈 슬롯 PATCH 로 생성 ────────────────────────────────────────
    if family['create_method'] == 'slot_patch':
        body = build_create_payload(family, target_username, target_password, role_id)
        # 2026-08-12 (lockout 예산): 슬롯을 3개까지 돌며 재시도하던 것을 **1개**로 줄인다.
        #   종전 최악은 3슬롯 × 검증 3회 = 표준 계정에 실패 인증 9회를 20초에 발생시켰다.
        #   Dell IP Blocking 기본값(60초 창 3회)·HPE(3회)를 이미 넘는다. 슬롯을 바꿔 가며
        #   다시 쓰는 것은 "다른 방식으로 또 써 본다" 와 같은 종류의 시도이기도 하다.
        code, patch_resp, err = _patch(
            bmc_ip, _p(chosen_slot['slot_uri']), body,
            current_username, current_password, timeout, verify_ssl,
        )
        out['write_response_info'] = _extended_info(patch_resp) or out['write_response_info']
        # 2026-08-12: 생성 PATCH 응답의 본문 거부(Dell iDRAC10 의 200+read-only)를
        #   여기서도 본다. 종전에는 기존 계정 경로에만 이 검사가 있어, 같은 펌웨어의
        #   같은 거부를 생성 경로에서는 성공으로 읽고 넘어갔다.
        out['write_http_status'] = code
        accepted, reject_reason = interpret_write_response(family, code, patch_resp, err)
        out['write_accepted'] = accepted
        out['vendor_status'] = reject_reason
        if not accepted:
            out['verification'] = 'failed'
            out['errors'].append(_err(
                'account_service',
                f'빈 슬롯에 표준 계정을 만들지 못했습니다 (slot={chosen_slot.get("id")}).',
                detail=' | '.join(x for x in (
                    reject_reason, out['write_response_info']) if x),
            ))
            return out
        _confirm_account_state(bmc_ip, chosen_slot.get('slot_uri'), target_username, family,
                               current_username, current_password, timeout, verify_ssl, out)
        ok_v, verify_code, verify_err, attempts = _verify_standard_credential()
        out['verify_attempts'] = attempts
        if ok_v:
            out['recovered']    = True
            out['verification'] = 'verified'
            return out
        # 쓰기는 수락됐는데 그 자격으로 인증이 안 된다 — silent fail.
        # 만들다 만 슬롯을 그대로 두지 않는다 (best-effort cleanup, 응답도 남긴다).
        out['verification'] = 'failed'
        out['errors'].append(_err(
            'account_service',
            '표준 계정 생성은 수락됐지만 그 계정으로 인증되지 않았습니다. '
            '장비의 암호 정책과 등록된 비밀번호를 확인하세요.',
            detail=' | '.join(x for x in (
                (verify_err or f'verify HTTP {verify_code}'),
                f'slot={chosen_slot.get("id")}',
                'check BMC password strength policy (length / character classes / history)',
                out['write_response_info'],
            ) if x),
        ))
        cl_code, cl_resp, cl_err = _patch(
            bmc_ip, _p(chosen_slot['slot_uri']),
            {'UserName': '', 'Enabled': False, 'RoleId': 'None'},
            current_username, current_password, timeout, verify_ssl,
        )
        # audit M-5: 되돌리기 실패가 어디에도 남지 않던 문제. 남긴다.
        if cl_code not in (200, 204) or cl_err:
            out['errors'].append(_err(
                'account_service',
                '실패한 슬롯을 되돌리지 못했습니다. 해당 슬롯 상태를 확인하세요.',
                detail=' | '.join(x for x in (
                    cl_err or f'HTTP {cl_code}', _extended_info(cl_resp)) if x),
            ))
        return out

    # ── 3-b) POST 로 생성 ─────────────────────────────────────────────────
    # 대상 URI 는 Family 가 확정한다 (Accounts Collection / AccountService 루트 /
    # Account Instance). 실패해도 **다른 URI 로 갈아타지 않는다.**
    accounts_uri = _create_target_uri(family, discovery, explicit_id)
    out['create_uri'] = accounts_uri
    out['create_uri_kind'] = family.get('create_uri')
    # 최신 계약을 쓸 근거가 장비값에서 나왔는지, 근거 부족으로 구 계약 하나만 쓴 것인지.
    out['create_uri_basis'] = family.get('create_uri_basis')
    body_base = build_create_payload(family, target_username, target_password, role_id,
                                     explicit_id=explicit_id)
    code, resp_data, err = _post(
        bmc_ip, accounts_uri, body_base,
        current_username, current_password, timeout, verify_ssl,
    )
    out['write_http_status'] = code
    accepted, reject_reason = interpret_write_response(
        family, code, resp_data, err, requested=set(body_base))
    out['write_response_info'] = _extended_info(resp_data) or out['write_response_info']
    out['write_rejections'] = write_rejections(resp_data, set(body_base))

    # 2026-08-12 (rev.2): **`PasswordChangeRequired:false` 를 덧붙여 다시 POST 하던 경로를
    #   제거했다.** 종전에는 evidence='unverified' Family 에서만 그 사다리를 남겼는데,
    #   바로 그 Family 들(Fujitsu / Quanta / Cisco X-Series / Lenovo IMM2 / Supermicro X9 /
    #   Inspur M5·M7 / HPE RMC)이 공식 조사에서 **하나같이 이 재시도를 금지**한 대상이다.
    #     05 §19/§39-D, 06 §17/§31-F, 07 §17/§40-E, 08 §17/§32-C, 09 §19/§45-D
    #   UNVERIFIED 의 뜻은 "여러 번 시도해 본다" 가 아니라
    #     read-only discovery → 완전 열거 → **한 번의 결정적 쓰기** → 재조회 → 재인증
    #   이다. 계약을 모르면 추측하지 말고 한 번 쓰고 결과를 그대로 보고한다.

    out['write_accepted'] = accepted
    out['vendor_status'] = reject_reason
    if not accepted:
        out['verification'] = 'failed'
        out['errors'].append(_err(
            'account_service',
            '표준 계정 생성 요청이 거부됐습니다.',
            detail=' | '.join(x for x in (
                f'POST {accounts_uri}', f'family={family["id"]}',
                reject_reason, out['write_response_info']) if x),
        ))
        return out

    # 생성된 리소스의 정본은 응답이 알려준 @odata.id 다 (번호/이름을 추측하지 않는다).
    created_uri = _str(_safe(resp_data, '@odata.id')) or None
    if not created_uri:
        # 응답이 위치를 알려주지 않으면 다시 열거해서 찾는다 — 그래도 추측하지 않는다.
        recheck = account_service_discover(bmc_ip, current_username, current_password,
                                           timeout, verify_ssl,
                                           service_root=discovery.get('service'))
        again = [a for a in (recheck.get('accounts') or [])
                 if (a.get('username') or '') == target_username]
        created_uri = again[0].get('slot_uri') if len(again) == 1 else None
    out['slot_uri'] = created_uri

    # 2026-08-12 (audit H-1): POST 2xx 만으로 recovered=true 를 반환하던 경로를 없앤다.
    #   Cisco 공식 문서조차 Create 뒤 "Verifying the User" 를 별도 단계로 제시한다.
    _confirm_account_state(bmc_ip, created_uri, target_username, family,
                           current_username, current_password, timeout, verify_ssl, out)
    ok_v, verify_code, verify_err, attempts = _verify_standard_credential()
    out['verify_attempts'] = attempts
    if ok_v:
        out['recovered']    = True
        out['verification'] = 'verified'
        return out
    out['verification'] = 'failed'
    out['errors'].append(_err(
        'account_service',
        '표준 계정을 만들었지만 그 계정으로 인증되지 않았습니다. '
        '장비의 암호 정책과 계정 상태를 확인하세요.',
        detail=' | '.join(x for x in (
            (verify_err or f'verify HTTP {verify_code}'),
            f'family={family["id"]}', out['write_response_info']) if x),
    ))
    return out


def main():
    module = AnsibleModule(
        argument_spec=dict(
            bmc_ip          = dict(type='str',  required=True),
            username        = dict(type='str',  required=True),
            password        = dict(type='str',  required=True, no_log=True),
            timeout         = dict(type='int',  default=30),
            verify_ssl      = dict(type='bool', default=False),
            # P2 (cycle 2026-04-28): AccountService 통합
            mode            = dict(type='str',  default='gather',
                                   choices=['gather', 'account_provision']),
            target_username = dict(type='str',  default=''),
            target_password = dict(type='str',  default='', no_log=True),
            target_role     = dict(type='str',  default='Administrator'),
            dryrun          = dict(type='bool', default=True),
            # 2026-08-11 (Phase 6-B §11): 기존 계정 PATCH 후 인증 확인 실패 시
            # DELETE + POST 로 지우고 다시 만드는 fallback 의 opt-in 스위치.
            # default False = 지우지 않는다. 근거는 account_service_provision() 주석 참조.
            allow_delete_recreate = dict(type='bool', default=False),
            # cycle 2026-05-12 (ADR-2026-05-12): HPE CSUS 3200 / Superdome Flex
            # RMC primary 멀티-노드 토폴로지 수집 활성. adapter `vendor_notes.manager_layout`
            # 을 detect_vendor.yml → collect_standard.yml → 본 모듈까지 전달.
            # None 시 기존 13 vendor 영향 0 (Additive only — rule 92 R2).
            #   Allowed values: None / 'rmc_primary' / 'rmc_primary_ilo_secondary'
            manager_layout  = dict(type='str',  default=None, required=False),
            # 2026-08-12: Account Family 선택 **hint**. 단독 근거로 쓰지 않는다 —
            #   실제 Resource Capability 가 우선하고, adapter 이름은 동률을 깰 때만 쓴다.
            #   (Supermicro 계정분리 세대 / Lenovo XCC 세대 / HPE RMC 구분 등)
            adapter_id      = dict(type='str',  default=None, required=False),
        ),
        supports_check_mode=True,
    )

    if not HAS_URLLIB:
        module.fail_json(msg='Python urllib 를 import 할 수 없습니다')

    # Phase 5-A: 인증 관측은 invocation 단위다. Ansible 은 매 실행마다 새 프로세스지만
    # 테스트는 한 프로세스에서 main() 을 여러 번 부르므로 명시적으로 초기화한다.
    _reset_auth_observation()
    _reset_notices()

    p = module.params
    bmc_ip, username, password = p['bmc_ip'], p['username'], p['password']
    timeout, verify_ssl = p['timeout'], p['verify_ssl']
    mode = p['mode']

    # ── P2: AccountService provision mode ────────────────────────────────
    if mode == 'account_provision':
        target_username = p['target_username']
        target_password = p['target_password']
        target_role     = p['target_role']
        dryrun          = p['dryrun']

        if not target_username or not target_password:
            module.fail_json(
                msg='mode=account_provision 시 target_username/target_password 필수'
            )

        # 2026-08-12 (audit H-2): `supports_check_mode=True` 를 선언해 두고 module.check_mode 를
        #   한 번도 읽지 않아, `ansible-playbook --check` 로 **실제 PATCH/POST 가 나갔다.**
        #   여기서 dryrun 과 OR 로 묶어 --check 가 쓰기 0건을 보장하게 한다.
        dryrun_reason = None
        if module.check_mode and not dryrun:
            dryrun_reason = 'check_mode'
        elif dryrun:
            dryrun_reason = 'parameter'
        dryrun = bool(dryrun) or bool(module.check_mode)

        # detect_vendor 로 vendor 정규화 (분기 라우팅 용도).
        #   manager_uri / service_root 는 여기서 이미 얻으므로 Family 판단에 재사용한다
        #   (추가 요청 없이 Firmware/Model 근거를 확보하기 위해).
        vendor, _, mgr_uri, _, det_errors, svc_root = detect_vendor(
            bmc_ip, username, password, timeout, verify_ssl
        )
        result = account_service_provision(
            bmc_ip, vendor, username, password,
            target_username, target_password, target_role,
            timeout, verify_ssl, dryrun=dryrun,
            allow_delete_recreate=bool(p.get('allow_delete_recreate')),
            adapter_id=p.get('adapter_id'),
            manager_uri=mgr_uri,
            service_root=svc_root,
        )
        result['dryrun_reason'] = dryrun_reason
        result['errors'] = list(det_errors) + (result.get('errors') or [])
        module.exit_json(
            changed=bool(result.get('recovered')),
            mode='account_provision',
            vendor=vendor,
            account_service=result,
            # 2026-08-12: 이 모드도 detect_vendor 를 한 번 돌므로 vendor fallback 식별 같은
            #   정보성 통보가 생길 수 있다. gather 모드와 반환 shape 을 맞춘다.
            notices=notices(),
        )
        return

    # ── 기존 gather mode (cycle 2026-05-01: unsupported 분류 추가) ──────
    all_errors, collected, failed, unsupported = [], [], [], []

    # cycle 2026-05-12 (ADR-2026-05-12): manager_layout (adapter capability) 수신.
    # None 시 기존 13 vendor 영향 0 (Additive).
    manager_layout = p.get('manager_layout') or None

    vendor, system_uri, manager_uri, chassis_uri, det_errors, service_root = detect_vendor(
        bmc_ip, username, password, timeout, verify_ssl
    )
    all_errors.extend(det_errors)

    # T-01 (cycle 2026-05-11): ServiceRoot 무인증 응답에서 adapter selection 용 facts 추출.
    # detect_vendor.yml 의 probe 단계 (무인증) 에서 data.bmc/data.system 가 empty 이면
    # adapter_loader 가 priority 만으로 선택 — vendor-specific generation 정확 매칭 불가.
    # probe_facts 가 model_hint/firmware_hint/manager_type 을 제공해 adapter 선택 정확도 보강.
    # rule 96 R1-B Additive only — envelope shape 신 키 추가는 본 probe 경로 한정 +
    # 호출자 시스템 (Jenkins downstream) 은 본 키 모름 → 파싱 변경 0.
    probe_facts = _extract_probe_facts(service_root, vendor)

    if not system_uri:
        module.exit_json(
            changed=False, status='failed', vendor=vendor,
            collected=[], failed_sections=['all'], unsupported_sections=[],
            errors=all_errors, data={}, probe_facts=probe_facts,
            multi_node=None, auth_evidence=auth_evidence(), notices=notices(),
        )

    # 2026-08-11: 대표 시리얼 resolver 가 등록된 vendor 는 그 값을 **필수값**으로 다룬다.
    # 못 얻으면 다른 시리얼 후보로 대체하지 않고 수집 자체를 실패시킨다 (사용자 결정).
    # 미등록 vendor 는 _serial_resolver 가 None 이라 이 블록과 아래 확정 블록을 통째로 건너뛴다.
    _serial_resolver = _SERIAL_RESOLVERS.get(vendor)
    _forced_serial = None
    if _serial_resolver is not None:
        def _reauth_service_root():
            """인증 ServiceRoot 1회 재조회 — 1차(무인증 우선) 조회에서 못 찾았을 때만 호출된다."""
            if not username:
                return None
            st_r, root_r, err_r = _get(bmc_ip, '', username, password, timeout, verify_ssl)
            if err_r or st_r != 200 or not isinstance(root_r, dict):
                return None
            return root_r

        _forced_serial, _serial_err = _serial_resolver(
            service_root, refetch=_reauth_service_root)
        if _serial_err is not None:
            all_errors.append(_err('system', _serial_err))
            module.exit_json(
                changed=False, status='failed', vendor=vendor,
                collected=[], failed_sections=['all'], unsupported_sections=[],
                errors=all_errors, data={}, probe_facts=probe_facts,
                multi_node=None, auth_evidence=auth_evidence(), notices=notices(),
            )

    result_data = _collect_all_sections(
        bmc_ip, vendor, system_uri, manager_uri, chassis_uri,
        username, password, timeout, verify_ssl,
        all_errors, collected, failed, unsupported,
        manager_layout=manager_layout,
        # A1b (2026-06-04): ServiceRoot.Product 를 hardware.model fallback 로 전달 (check_redfish 동일).
        product_hint=_safe(service_root, 'Product'),
    )

    # 대표 시리얼 확정. gather_system 의 SerialNumber 값을 마지막에 덮어쓴다.
    # system 섹션을 못 얻었으면 대표 시리얼을 실을 자리가 없다 → partial 로 내보내면
    # hardware.serial=null 인 '정상' 결과가 되므로, 그 경로는 정상 결과로 반환하지 않는다.
    if _serial_resolver is not None:
        _sys_section = result_data.get('system')
        if isinstance(_sys_section, dict) and _sys_section:
            _sys_section['serial'] = _forced_serial
        else:
            all_errors.append(_err(
                'system',
                '서버 대표 시리얼을 결과에 실을 수 없습니다 — system 섹션 수집 실패'))
            module.exit_json(
                changed=False, status='failed', vendor=vendor,
                collected=[], failed_sections=['all'], unsupported_sections=[],
                errors=all_errors, data={}, probe_facts=probe_facts,
                multi_node=None, auth_evidence=auth_evidence(), notices=notices(),
            )

    # cycle 2026-05-12 (ADR-2026-05-12): manager_layout 정의 vendor 만 multi_node 수집.
    # None / 미정의 vendor — 13 vendor 영향 0 (Additive only).
    multi_node = _collect_multi_node_topology(
        bmc_ip, vendor, service_root,
        username, password, timeout, verify_ssl,
        manager_layout=manager_layout,
    )
    # Round 10: multi_node(RMC) 수집 errors(401/403 포함)를 status 계산 + envelope errors[] 에 반영.
    # 누락 시 multi_node 인증 실패가 success/partial 로 오분류(status 거짓). multi_node=None 시 영향 0.
    if isinstance(multi_node, dict):
        all_errors.extend(multi_node.get('errors') or [])

    final_status, clean = _compute_final_status(collected, failed, all_errors)

    module.exit_json(
        changed=False, status=final_status, vendor=vendor,
        collected=clean, failed_sections=list(set(failed)),
        unsupported_sections=list(set(unsupported)),
        errors=all_errors, data=result_data, probe_facts=probe_facts,
        multi_node=multi_node, auth_evidence=auth_evidence(), notices=notices(),
    )


if __name__ == '__main__':
    main()
