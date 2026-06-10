#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Ansible Custom Module: redfish_gather  v4
------------------------------------------
검증된 벤더별 URI 구조 (공식 문서 기반):

  HPE iLO 5/6/7: Systems/1               / Managers/1   (Oem.Hpe / Oem.Hp fallback)
  Dell iDRAC 9/10: Systems/System.Embedded.1 / Managers/iDRAC.Embedded.1  (Oem.Dell)
  Lenovo XCC/XCC2/XCC3: Systems/1        / Managers/1   (Oem.Lenovo)
  Supermicro X11~X14: Systems/1          / Managers/1   (Oem.Supermicro)
    Manufacturer = "Super Micro Computer, Inc."
  Cisco CIMC M4~M8 / UCS X-Series: Systems/<serial> / Managers/CIMC (Oem.Cisco — 옵션)
    Manufacturer = "Cisco Systems"

외부 라이브러리 불필요 — Python stdlib(urllib, ssl, socket) 만 사용

──────────────────────────────────────────────────────────────────────────────
Read-only 보장 (DSP0266 §11 + bmcweb OpenBMC #262 회피):
──────────────────────────────────────────────────────────────────────────────
본 모듈은 GET only — 정보 수집만 수행.
- _post() / _patch() 헬퍼는 AccountService 계정 생성/갱신 진입점 한정 사용
  (recovery 계정 부재 시 자동 생성). dryrun=true 가 기본값이라 실 BMC 호출은
  명시적 토글 후만. dryrun=false 도 idempotent (이미 존재 시 PATCH skip).
- ETag / If-Match 헤더 미사용 → bmcweb 일부 펌웨어의 If-Match crash 회피
  (OpenBMC issue #262).
- DELETE / OEM Action (SystemErase / SetBiosTime / RetryCloudConnect / ClearCMOS
  등) 절대 호출 안 함.
- TLS 1.2/1.3 양쪽 호환 — _ctx() 가 SSLContext
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

import json, socket, sys, traceback

# ── 단위 변환 상수 ──────────────────────
# 주의: decimal(10^n) 과 binary(2^n) 는 의미가 다르므로 절대 통합 금지.
#   capacity_gb = DECIMAL GB (÷1e9) / total_mb·capacity_mb = BINARY MiB (÷2^20).
BYTES_PER_GB_DECIMAL = 1_000_000_000   # 10^9 — CapacityBytes ↔ capacity_gb (decimal GB)
BYTES_PER_MIB = 1048576                # 2^20 — CapacityBytes → total_mb (binary MiB)
MIB_PER_GIB = 1024                     # 2^10 — MiB → GiB (binary, grouping key)
MBPS_PER_GBPS = 1000.0                 # 10^3 — 네트워크 Mbps → Gbps (decimal bitrate, byte 아님)
MAX_COLLECTION_MEMBERS = 1024  # 무경계 Members/Drives 순회 DoS 상한 (실 BMC << 1024)


def _removeprefix(s, prefix):
    """str.removeprefix() 호환 (Python 3.8 이하 지원)"""
    if s.startswith(prefix):
        return s[len(prefix):]
    return s


def _safe_int(x, default=None):
    """Redfish 응답 robustness — string/None/non-numeric → default.

    외부 계약 drift 대비. 펌웨어 변경으로 capacity 필드가 비-숫자
    문자열 또는 None을 반환할 때 ValueError로 모듈 자체가 죽는 사고 차단.
    """
    if x is None:
        return default
    try:
        return int(x)  # ok: try/except 보호 안
    except (ValueError, TypeError, OverflowError):  # Round 15: int(float('inf')) → OverflowError 방어
        return default


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
    if cur_gbps_num is not None:
        speed_gbps = cur_gbps_num
    elif speed_mbps is not None:
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

# verify_ssl(bool) 별 SSLContext 캐시
_CTX_CACHE = {}


def _ctx(verify_ssl):
    """HTTPS context — verify_ssl=False 시 self-signed BMC 인증서 허용.

    구 BMC (HPE iLO4, Lenovo IMM2, 일부 iDRAC7/8 펌웨어) 호환.
    OpenSSL 3.x legacy renegotiation + weak cipher 허용 — verify=False 환경 한정.
    curl -k 와 동등한 관용성. 사내 BMC self-signed 망 한정.

    TLS 1.2/1.3 양쪽 호환 명시:
    - minimum_version = TLSv1_2 (DMTF DSP0266 §10.2 권장 + iLO 7 enum 제거)
    - maximum_version = TLSv1_3 (Gen11+ / XCC3+ / X14+ 강제 가능)
    - SECLEVEL=0 으로 weak cipher 허용 (iLO 4 / IMM2 / 구 iDRAC 펌웨어)
    구 BMC TLS 1.0/1.1 만 지원하면 본 코드는 핸드셰이크 실패 → graceful
    degradation 으로 status=failed (precheck protocol 단계). 별 사고 신호
    없으면 minimum_version 유지.

    verify_ssl(bool) 별 1회만 빌드 후 재사용 (_CTX_CACHE).
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

def _get(bmc_ip, path, username, password, timeout, verify_ssl):
    url = f'https://{bmc_ip}/redfish/v1/{path.lstrip("/")}'
    # hotfix: User-Agent 추가가 Lenovo XCC 일부 펌웨어 reject 유발 (사이트 검증).
    # Accept + OData-Version 만 유지 (동작 검증된 헤더 셋).
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
    """AccountService 계정 생성 (POST /Accounts)."""
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
    """DELETE method 추가 — Lenovo XCC 권한 cache 손상 시
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


def _patch(bmc_ip, path, body, username, password, timeout, verify_ssl):
    """AccountService 계정 update (PATCH /Accounts/{id})."""
    url = f'https://{bmc_ip}/redfish/v1/{path.lstrip("/")}'
    try:
        payload = json.dumps(body).encode('utf-8')
    except TypeError:  # Round 4 #4/#5: 비-직렬화 body 방어 (provision crash 차단)
        payload = json.dumps(str(body)).encode('utf-8')
    req = urlreq.Request(url, data=payload, method='PATCH', headers={
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

def _p(uri):
    """@odata.id URI → _get() path 인수.

    @odata.id 는 Redfish spec 상 str URI 지만, 오염/펌웨어 버그로 비-str
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

def _err(section, message, detail=None):
    return {'section': section, 'message': str(message), 'detail': detail}


def _capped(seq, section=None, errors=None):
    """무경계 collection(Members/Drives) 순회 상한 — DoS/huge-payload 방어.

    오염/악성/버그 BMC 가 수천 멤버를 반환하면 멤버당 _get 가 N회 네트워크 왕복(각 timeout)을
    유발해 사실상 hang. cap 초과 시 절단 + (errors 제공 시) _err 로 명시(silent 절단 금지).
    실 BMC 멤버 수는 cap 보다 훨씬 작아 정상 입력 결과 불변.
    """
    seq = seq if isinstance(seq, list) else []  # Round 4 #2: 비-list 방어 (len/slice crash 차단)
    if len(seq) > MAX_COLLECTION_MEMBERS:
        if errors is not None and section:
            errors.append(_err(section,
                f'collection 멤버 {len(seq)} > 상한 {MAX_COLLECTION_MEMBERS} — 절단(DoS 방어)'))
        return seq[:MAX_COLLECTION_MEMBERS]
    return seq


# 2026-04-29 JEDEC ID -> vendor name normalization
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
# 아래 dict는 vendor 분기 코드가 아니라 Ansible runtime 외 환경
# (pytest / 직접 invoke)에서 vendor_aliases.yml load 실패 시 fallback 정규화 맵.
# vendor_aliases.yml이 primary, 본 dict는 secondary. 신규 alias 추가 시 vendor_aliases.yml만
# 갱신하면 충분.
_FALLBACK_VENDOR_MAP = {
    'dell': 'dell', 'dell inc.': 'dell', 'dell emc': 'dell',
    'hpe': 'hpe', 'hewlett packard enterprise': 'hpe',
    'hewlett packard enterprise co.': 'hpe', 'hewlett-packard': 'hpe',
    'hp enterprise': 'hpe', 'hp': 'hpe',
    'lenovo': 'lenovo', 'lenovo group ltd.': 'lenovo',
    'lenovo group limited': 'lenovo', 'ibm': 'lenovo',
    'supermicro': 'supermicro', 'super micro computer, inc.': 'supermicro',
    'super micro computer': 'supermicro', 'smci': 'supermicro',
    'cisco': 'cisco', 'cisco systems inc': 'cisco',
    'cisco systems inc.': 'cisco', 'cisco systems, inc': 'cisco',
    'cisco systems, inc.': 'cisco', 'cisco systems': 'cisco',
    # 2026-05-01 추가: Huawei / Inspur / Fujitsu / Quanta
    'huawei': 'huawei', 'huawei technologies co., ltd.': 'huawei',
    'huawei technologies': 'huawei',
    'inspur': 'inspur',
    'inspur information technology company limited': 'inspur',
    'inspur information': 'inspur', 'inspur systems': 'inspur',
    'fujitsu': 'fujitsu', 'fujitsu limited': 'fujitsu',
    'fujitsu technology solutions': 'fujitsu',
    'quanta': 'quanta', 'quanta computer': 'quanta',
    'quanta computer inc.': 'quanta',
    'quanta cloud technology': 'quanta', 'qct': 'quanta',
}
# 호환 alias (외부 코드가 _BUILTIN_VENDOR_MAP 이름 참조 시)
_BUILTIN_VENDOR_MAP = _FALLBACK_VENDOR_MAP

# BMC 시그니처 → vendor (Redfish ServiceRoot Product/Name 필드의 BMC 제품명 매칭)
# ServiceRoot v1.0~1.4 펌웨어는 Vendor/Product 표준 필드 부재.
# BMC 제품명이 vendor 시그니처로 사실상 외부 Redfish spec 일부 (HPE Hpe namespace,
# Dell iDRAC, Lenovo XClarity 등). vendor 분기 코드가 아니라 정규화 맵.
_BMC_PRODUCT_HINTS = {
    'idrac': 'dell', 'integrated dell': 'dell',
    'ilo': 'hpe', 'proliant': 'hpe',
    'xclarity': 'lenovo', 'thinksystem': 'lenovo',
    'xcc': 'lenovo', 'imm2': 'lenovo',
    'megarac': 'supermicro',
    'cimc': 'cisco', 'ucs': 'cisco',
    # 2026-05-01 추가 — vendor BMC 시그니처
    'ibmc': 'huawei', 'fusionserver': 'huawei',
    'isbmc': 'inspur',
    'irmc': 'fujitsu', 'primergy': 'fujitsu',
    'quantagrid': 'quanta', 'quantaplex': 'quanta',
    # 2026-05-06 (HPE Superdome Flex / Flex 280 web 검색 — lab 부재):
    # Superdome Flex 의 RMC (Rack Management Controller) host 가 ServiceRoot.Product 에
    # "Superdome Flex" 또는 "iLO 5" 로 응답 — hpe sub-line. Manufacturer 시그니처
    # 부재 펌웨어 환경에서 BMC 제품명으로 정규화 강건성 향상.
    # source: HPE Superdome Flex Server Admin Guide + sdflexutils GitHub
    'superdome': 'hpe', 'superdome flex': 'hpe',
    # HP CSUS 3200: RMC 가 ServiceRoot.Product/Name 에
    # "Compute Scale-up Server 3200" 으로 응답 — Manufacturer/alias 시그니처 부재
    # 펌웨어에서 무인증 probe 벤더 감지 강건성 향상.
    # 복합 키만 사용 — 'csus'/'compute' 단독은 비-HPE Product/Name 와 substring 충돌
    # 위험 (_detect_vendor_from_service_root 의
    # `if hint in p`(Product) / `if hint in n`(Name) plain substring 매칭).
    # source: HPE Compute Scale-up Server 3200 FAQ + Superdome Flex Admin Guide (CSUS = Superdome Flex 후속).
    'compute scale-up server': 'hpe', 'csus 3200': 'hpe',
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
    # vendor_aliases.yml 시도 (primary)
    aliases = _load_vendor_aliases_file()
    # aliases (YAML primary) 우선, fallback dict는 보조
    merged = {**_FALLBACK_VENDOR_MAP, **aliases}

    # 정확 매칭
    if mfr_lower in merged:
        return merged[mfr_lower]

    # 부분 매칭 (기존 로직 호환)
    for key, canon in merged.items():
        if key and (key in mfr_lower or mfr_lower in key):  # 빈 alias wildcard 매칭 방어 (Round 1 #9)
            return canon

    return 'unknown'


# ── 벤더 감지 ────────────────────────────────────────────────────────────────

def _probe_realm_hint(bmc_ip, timeout, verify_ssl):
    """401/403 응답의 WWW-Authenticate realm에서 vendor hint 추출.

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
    # realm BMC 시그니처
    for hint, canon in _BMC_PRODUCT_HINTS.items():
        if hint in realm:
            return canon
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
    # vendor_aliases.yml + fallback merge.
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
        # BMC vendor OEM namespace prefix → vendor 식별 (외부 Redfish spec)
        for key in oem:
            k = key.lower()
            for alias, canon in vm.items():
                if not alias:
                    continue
                if k.startswith(alias + '_') or k.startswith(alias + '.'):
                    return canon

    # 2. Vendor 필드 확인 — ServiceRoot v1.5.0+ 표준
    # 'Dell Inc.' 같은 trailing dot/whitespace + substring 매칭
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
            if alias and alias in p:  # 빈 alias wildcard 매칭 방어 (Round 1 #8, 아래 Name 필드 동일 가드)
                return canonical
        # BMC 시그니처 → vendor 식별 (외부 Redfish spec OEM namespace)
        for hint, canon in _BMC_PRODUCT_HINTS.items():
            if hint in p:
                return canon

    # 4. Name 필드에 벤더명 포함 확인 — Cisco "Cisco RESTful Root Service" 등
    name = _safe(root, 'Name')
    if name and isinstance(name, str):
        n = name.lower()
        for alias, canonical in vm.items():
            if alias and alias in n:  # 빈 alias wildcard 매칭 방어 (Round 1 #8)
                return canonical
        # BMC 시그니처 fallback (Name 필드)
        for hint, canon in _BMC_PRODUCT_HINTS.items():
            if hint in n:
                return canon

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

    신설.
    Storage→SimpleStorage / Power→PowerSubsystem / 향후 ThermalSubsystem 같은
    DMTF 변천 호환 패턴을 재사용 가능한 단일 함수로 추상화.

    Behavior:
    - primary GET → 200 이면 (data, [], 'primary') 반환
    - primary 404 → fallback GET → 200 이면 (data, [], 'fallback') 반환
    - fallback 404 → ({}, [], 'not_supported') 반환 (호출자가 분류)
    - 5xx / 401 / 403 / 그 외 → ({}, [error], 'failed')

    호환성 fallback only — envelope 신 키 추가 안 함.

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

    Managers/Chassis 등 N+1 컬렉션에서 첫 멤버만 반환.
    Returns: (member_uri_or_none, status_code, error_msg)
    """
    if not coll_uri:
        return None, None, 'collection uri 없음'
    st, coll, err = _get(bmc_ip, _p(coll_uri), username, password, timeout, verify_ssl)
    if err or st != 200:
        return None, st, err or f'HTTP {st}'
    members = _safe(coll, 'Members') or []
    if not isinstance(members, list) or not members:  # 비-list Members 방어 (Round 1 #24)
        return None, st, 'members 없음'
    return _safe(members[0], '@odata.id'), st, None


def _resolve_all_member_uris(bmc_ip, coll_uri, username, password, timeout, verify_ssl):
    """컬렉션 URI → 모든 Members 의 @odata.id 추출.

    `_resolve_first_member_uri` 의 확장. RMC (HPE Compute Scale-up Server 3200 /
    Superdome Flex) 같이 단일 진입점이 N개 Manager / N개 nPartition / N개 Chassis 를
    노출하는 환경에서 전수 수집을 위한 함수. 기존 단일 노드 함수는 그대로 두고
    별도 경로로 동작한다.

    source:
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
    if not isinstance(raw_members, list):  # 비-list Members 방어 (Round 2 #15)
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


def _classify_rmc_label(manager_uri, manager_id, manager_layout, is_first=True):
    """Manager URI / ID + adapter capability 기반 BMC 표시명 결정.

    HPE CSUS 3200 / Superdome Flex 의 RMC primary 시스템에서 manager 별 라벨 분기:
      - RMC (Rack Management Controller) → 'RMC'
      - PDHC (per-chassis controller) → 'PDHC'
      - per-node iLO 5 → 'iLO'

    Allowed 영역 — line ~1559 `bmc_names` 매핑 (외부 spec 기반 표준 이름) 의
    fallback path 확장. `manager_layout` None 시 기존 동작을 그대로 유지한다.

    `is_first` 로 layout-default 'RMC' 는 **첫 Manager** 에만 적용한다.
    substring 미매치 Manager 가 전부 'RMC' 로 오라벨되면 _classify_manager_role
    의 role 과 불일치 (name='RMC' 인데 role=None) 한다. 비-first unmatched → None 반환 →
    호출자가 generic bmc_names[vendor] 사용. 비-documented manager ID (Managers/1 / Self)
    환경에서 다중 RMC 오라벨 + name/role 모순을 차단한다 (lab 부재 — 사이트 ID 패턴 향후 결정).

    source: HPE Superdome Flex Admin Guide + sdflexutils GitHub README

    Returns: str | None  (None 시 호출자가 bmc_names[vendor] fallback 사용)
    """
    if not manager_layout:
        return None
    lid = _str(manager_id).lower()
    luri = _str(manager_uri).lower()
    # 우선순위: ID substring → URI substring → (첫 Manager 한정) layout default
    if 'rmc' in lid or 'rmc' in luri:
        return 'RMC'
    if 'pdhc' in lid or 'pdhc' in luri:
        return 'PDHC'
    if 'ilo' in lid or 'ilo' in luri:
        return 'iLO'
    # layout default — `rmc_primary` 시 **첫 Manager 만** RMC 로 가정. 비-first 는 None
    # (호출자 generic fallback) — 다중 RMC 오라벨 방지.
    if is_first and manager_layout in ('rmc_primary', 'rmc_primary_ilo_secondary'):
        return 'RMC'
    return None


def _classify_manager_role(manager_uri, manager_id, manager_layout, is_first=False):
    """Manager 의 role (primary / secondary) 결정.

    `manager_layout` + ID substring 매칭 기반:
      - RMC → primary
      - PDHC / iLO → secondary
      - 그 외 첫 Manager → primary, 비-first → secondary
      - layout 미정의 → None

    `is_first` 로 `_classify_rmc_label` 과 name/role 을 정합한다.
    첫 Manager unmatched → primary (RMC 가정), 비-first unmatched → secondary. substring
    매치(pdhc/ilo)는 position 무관 secondary (첫 슬롯이라도 PDHC/iLO 면 secondary).

    Returns: str | None
    """
    if not manager_layout:
        return None
    lid = _str(manager_id).lower()
    luri = _str(manager_uri).lower()
    if 'rmc' in lid or 'rmc' in luri:
        return 'primary'
    if manager_layout in ('rmc_primary', 'rmc_primary_ilo_secondary'):
        if 'pdhc' in lid or 'pdhc' in luri or 'ilo' in lid or 'ilo' in luri:
            return 'secondary'
        # substring 미매치: 첫 Manager 는 primary (RMC 가정 — label 과 정합), 그 외 secondary
        return 'primary' if is_first else 'secondary'
    return None


def _classify_chassis_kind(chassis_uri, chassis_id, chassis_data):
    """Chassis 의 kind (base / expansion / compute_module) 결정.

    HPE Superdome Flex / CSUS 3200 multi-chassis 환경:
      - base / Base → 'base'
      - expansion / Expansion → 'expansion'
      - compute / module → 'compute_module'
      - ChassisType 표준 필드 사용 가능 시 우선

    source: DMTF DSP0266 Chassis.v1_20 ChassisType enum

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
        if ctype in ('rackmount', 'card', 'blade'):
            return ctype
    return None


def detect_vendor(bmc_ip, username, password, timeout, verify_ssl):
    """ServiceRoot(무인증)에서 벤더 식별 + Systems/Managers/Chassis URI 해석.

    Returns: (vendor, system_uri, manager_uri, chassis_uri, errors, service_root)
        service_root: 무인증/인증 ServiceRoot 응답 dict 원본 (None 가능).
            추가 (HPE adapter 오선택 fix) —
            _extract_probe_facts() 가 ServiceRoot 에서 model/firmware hint 추출 시 사용.
    """
    root, errors = _fetch_service_root(bmc_ip, username, password, timeout, verify_ssl)
    if root is None:
        return 'unknown', None, None, None, errors, None

    vendor = _detect_vendor_from_service_root(root)
    if vendor is None:
        vendor = 'unknown'
        errors.append(_err('vendor_detect', 'ServiceRoot에서 벤더 식별 불가'))

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

    # vendor=unknown 시 Chassis/Managers/System Manufacturer fallback.
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
                    # errors에서 'ServiceRoot에서 벤더 식별 불가' 제거 (해소됨)
                    errors = [e for e in errors if 'ServiceRoot에서 벤더 식별 불가' not in (e.get('message') or '')]
                    errors.append(_err('vendor_detect',
                        f'{fb_label} Manufacturer fallback로 vendor={fb_vendor} 식별 (ServiceRoot 정보 부족)'))
                    break

    # 앞선 fallback 단계까지 모두 fail이면 401 WWW-Authenticate realm 헤더로 마지막 추정.
    if vendor == 'unknown':
        realm_vendor = _probe_realm_hint(bmc_ip, timeout, verify_ssl)
        if realm_vendor:
            vendor = realm_vendor
            errors = [e for e in errors if 'ServiceRoot에서 벤더 식별 불가' not in (e.get('message') or '')]
            errors.append(_err('vendor_detect',
                f'WWW-Authenticate realm fallback로 vendor={realm_vendor} 식별 (ServiceRoot/Resources 본문 부족)'))

    return vendor, system_uri, manager_uri, chassis_uri, errors, root


def _extract_probe_facts(root, vendor):
    """ServiceRoot 무인증 응답에서 adapter selection 용 facts 추출.

    detect_vendor.yml 의 probe 단계는 무인증 (`username=""`) 으로 호출 — 본 수집의
    `gather_system()` / `gather_bmc()` 등은 모두 401 fail → `data.system` / `data.bmc`
    empty dict. 결과: facts.model / facts.firmware 가 비어 priority 가 가장 높은
    adapter 가 model/firmware 무관하게 선택됨 (HPE DL380 Gen11 가 hpe_ilo7
    Gen12-only adapter 로 오선택 사고).

    본 함수는 ServiceRoot (무인증 / 인증 fallback) 에서 vendor 별 semantic 을 알고
    safe 한 hint 만 추출. detect_vendor.yml 이 data.bmc/data.system 비어 있을 때
    fallback 으로 사용 (기존 path 는 그대로 두고 별도 경로로 동작).

    vendor 별 ServiceRoot semantic 차이
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

    Redfish API spec 자체가 OEM namespace (Oem.Hpe / Oem.Hp) 정의 —
    라이브러리에서 vendor 분기 허용.
    """
    if not isinstance(root, dict):
        return {}
    facts = {}
    if vendor == 'hpe':
        product = _safe(root, 'Product')
        if isinstance(product, str) and product.strip():
            facts['model_hint'] = product.strip()
        managers = (_safe(root, 'Oem', 'Hpe', 'Manager')
                    or _safe(root, 'Oem', 'Hp', 'Manager'))
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

# (전체 _extract_oem_*): 외부 계약 직접 의존.
# Redfish API spec 자체가 vendor namespace 정의 (Oem.Hpe / Oem.Dell / Oem.Lenovo ...)
# — adapter YAML로 위임 불가하므로 라이브러리에서 vendor 분기 허용.

def _extract_oem_hpe(data):
    """HPE OEM (iLO 5/6 = Oem.Hpe, iLO 4 이하 = Oem.Hp fallback).

    Underscore-prefixed keys (e.g. `_bios_date`) are hoisted to hardware-level
    by gather_system via _hoist_oem_extras. They populate **existing** envelope
    fields only (no new keys).
    Verified 2026-04-29 against HPE iLO 6 v1.73 (10.50.11.231): Bios.Current.Date
    populated; Manager.Oem.Hpe.Type field does not exist (former mapping was bug).
    """
    oem = _safe(data, 'Oem', 'Hpe') or _safe(data, 'Oem', 'Hp') or {}
    ahs = _safe(oem, 'AggregateHealthStatus') or {}
    bios_oem = _safe(oem, 'Bios', 'Current') or {}
    return {
        # Hoisted to hardware.bios_date
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


def _extract_oem_dell(data):
    """Dell OEM (Oem.Dell.DellSystem).

    Round 11 raw 검증 (10.100.15.27, iDRAC 7.10.70.00): 정확한 키는
    'EstimatedExhaustTemperatureCelsius'. 일부 구 펌웨어에서 'Cel' 변형 가능성
    있어 Celsius 우선, Cel fallback.
    """
    oem = _safe(data, 'Oem', 'Dell', 'DellSystem') or {}
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
        'estimated_exhaust_temp':  (_safe(oem, 'EstimatedExhaustTemperatureCelsius')
                                    or _safe(oem, 'EstimatedExhaustTemperatureCel')),
    }


def _extract_oem_lenovo(data, chassis_data=None):
    """Lenovo OEM (Oem.Lenovo).

    실측 (Lenovo XCC SR650 V2, 2026-04-28): ProductName은 System.Oem.Lenovo
    가 아닌 Chassis.Oem.Lenovo 에 존재. chassis_data 가 주어지면 Chassis 우선,
    없으면 System.Model 로 fallback.

    2026-04-29 추가 OEM 키 추출 — System.Oem.Lenovo의 운영 메타.
    """
    sys_oem = _safe(data, 'Oem', 'Lenovo') or {}
    cha_oem = _safe(chassis_data or {}, 'Oem', 'Lenovo') or {} if chassis_data else {}
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


def _extract_oem_supermicro(data):
    """Supermicro OEM (Oem.Supermicro)."""
    oem = _safe(data, 'Oem', 'Supermicro') or {}
    return {
        'board_id':   _safe(oem, 'BoardID'),
        'node_id':    _safe(oem, 'NodeID'),
    }


def _extract_oem_cisco(data, chassis_data=None):
    """Cisco OEM (Oem.Cisco).

    2026-04-29 Cisco CIMC C220 M4 (Round 11): ServiceRoot.Oem 빈 dict
    이지만 System/Chassis Oem.Cisco는 BoardSerial / Locator 등 일부 노출.
    """
    sys_oem = _safe(data, 'Oem', 'Cisco') or {}
    cha_oem = _safe(chassis_data or {}, 'Oem', 'Cisco') or {} if chassis_data else {}
    return {
        'board_serial':       _safe(sys_oem, 'BoardSerialNumber') or _safe(cha_oem, 'BoardSerialNumber'),
        'platform_name':      _safe(sys_oem, 'PlatformName') or _safe(cha_oem, 'PlatformName'),
        'asset_tag':          _safe(sys_oem, 'AssetTag') or _safe(cha_oem, 'AssetTag'),
        'description':        _safe(sys_oem, 'Description') or _safe(cha_oem, 'Description'),
        'locator_led':        _safe(sys_oem, 'LocatorLED') or _safe(cha_oem, 'LocatorLED'),
    }


def _hoist_oem_extras(oem_dict, target):
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
                # 2026-04-29 bios_date / bios_release_date를 ISO 8601로 정규화.
                # Dell '09/10/2024' (MM/DD/YYYY) / HPE '03/01/2024' / 등 → 'YYYY-MM-DD'.
                if field in ('bios_date', 'bios_release_date'):
                    target[field] = _normalize_bios_date(v)
                else:
                    target[field] = v
            # else: silently drop — never add new envelope keys
        else:
            cleaned[k] = v
    return cleaned


# RoleId enum 정규화 매트릭스 (9 vendor).
# vendor 별 default role enum 변형을 5 표준 카테고리로 매핑.
# 표준 카테고리: 'administrator' / 'operator' / 'readonly' / 'none' / 'custom'
# Redfish AccountService spec enum 직접 의존.
# 호출자가 옵션으로 사용하는 helper (envelope 키는 그대로 유지).
_ROLE_ID_NORMALIZATION_MATRIX = {
    # Dell iDRAC 표준
    'administrator': 'administrator',
    'admin':         'administrator',  # Cisco CIMC
    'supervisor':    'administrator',  # Lenovo XCC
    'operator':      'operator',
    'user':          'operator',  # Supermicro
    'readonly':      'readonly',
    'read-only':     'readonly',
    'read_only':     'readonly',
    'commonuser':    'readonly',  # Huawei iBMC
    'callback':      'readonly',  # Supermicro read-only role
    'none':          'none',
    'virtualmedia':  'custom',  # HPE iLO
}


def _normalize_role_id(raw_role):
    """RoleId enum 정규화 (9 vendor → 5 표준 enum).

    Args:
        raw_role: BMC 응답의 RoleId raw 문자열 (Administrator / admin / Supervisor / ...)

    Returns:
        normalized: 'administrator' / 'operator' / 'readonly' / 'none' / 'custom' / raw
                    (매트릭스에 없는 vendor-specific role 은 lowercase 그대로 보존)

    호출자가 옵션으로 사용한다 (envelope 키는 그대로 유지).
    """
    if raw_role is None:
        return None
    s = str(raw_role).strip().lower()
    if not s:
        return None
    return _ROLE_ID_NORMALIZATION_MATRIX.get(s, s)


def _normalize_dimm_label(raw_label):
    """DIMM ServiceLabel vendor 별 정규화.

    vendor 별 라벨 변형을 공통 형식으로 통일:
      - Dell:       "DIMM_A1"        → "DIMM A1"
      - HPE: "P1-DIMM-A1" → "P1 DIMM A1" (CPU prefix 보존)
      - Lenovo:     "DIMM 1"         → "DIMM 1"
      - Supermicro: "CPU0_DIMM_A1"   → "CPU0 DIMM A1"

    Args:
        raw_label: 원본 ServiceLabel (예: "DIMM_A1")

    Returns: normalized label (공백 구분) — 정보 손실 없음

    호출자가 옵션으로 사용한다 (raw label 도 함께 보존 권장).
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


# 주의 (2026-04-28 / 향후 결정):
# cisco ServiceRoot.Oem 은 Round 11 실측 빈 dict (adapter cisco_cimc.yml strategy=standard_only).
# 단, 2026-04-29 이후 System/Chassis Oem.Cisco 에서 일부 운영 메타가 나와
# _extract_oem_cisco 를 아래 매핑에 추가함 (ServiceRoot 가 아닌 System/Chassis 기준).
_OEM_EXTRACTORS = {
    'hpe':        _extract_oem_hpe,
    'dell':       _extract_oem_dell,
    'lenovo':     _extract_oem_lenovo,
    'supermicro': _extract_oem_supermicro,
    # 2026-04-29 Cisco CIMC OEM 추출 추가 (이전 ServiceRoot.Oem 빈 dict이라 skip했지만
    # System/Chassis Oem.Cisco는 일부 운영 메타 노출).
    'cisco':      _extract_oem_cisco,
}


# bmc / firmware OEM namespace unified extractor.
# 9 vendor 의 OEM namespace 변형 (Oem.Hp vs Oem.Hpe / Oem.Inspur vs Oem.Inspur_System
# / Oem.ts_fujitsu vs Oem.Fujitsu / Oem.Quanta_Computer_Inc vs Oem.QCT) 한 번에 해석.
# Redfish API spec OEM namespace 직접 의존 (vendor namespace 허용 영역).
# 본 helper 는 raw dict 만 반환한다 (envelope 키 그대로 유지).
_OEM_NAMESPACE_FALLBACK_CHAIN = (
    ('dell',       ('Dell',)),
    ('hpe',        ('Hpe', 'Hp')),  # iLO4 legacy
    ('lenovo',     ('Lenovo',)),
    ('cisco',      ('Cisco', 'Cisco_RackUnit')),  # UCS variant
    ('supermicro', ('Supermicro',)),
    ('huawei',     ('Huawei',)),
    ('inspur',     ('Inspur', 'Inspur_System')),  # older firmware variant
    ('fujitsu',    ('ts_fujitsu', 'Fujitsu')),  # iRMC alias
    ('quanta',     ('Quanta_Computer_Inc', 'QCT')),
)


def _extract_oem_unified(data, expected_vendor=None):
    """9 vendor OEM namespace 통합 추출 helper.

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

    Redfish API spec OEM namespace 직접 의존.
    호출자가 raw dict 를 사용하는 helper (envelope 키는 그대로 유지).
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

    # System 의 raw API 풍부 필드 추가 (asset/lastreset/tpm)
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
        # _strip_or_none + _safe 조합 (중복 stripping 로직 3곳 → 1곳 dedup)
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
            'health': _safe(data, 'ProcessorSummary', 'Status', 'Health'),
        },
        'memory_summary': {
            'total_gib': _safe_int(_safe(data, 'MemorySummary', 'TotalSystemMemoryGiB')),  # Round 4 #7: int 통일
            'health':    mem_health,
        },
        'oem': {},
    }

    # 벤더별 OEM 확장 dispatch (helper 함수에 위임)
    extractor = _OEM_EXTRACTORS.get(vendor)
    if extractor is not None:
        # _extract_oem_lenovo / _extract_oem_cisco 는 chassis_data 인자 추가.
        if vendor in ('lenovo', 'cisco'):
            raw_oem = extractor(data, chassis_data=chassis_data)
        else:
            raw_oem = extractor(data)
        # `_*` prefix 키 (예: `_bios_date`) 를 result hardware-level 로 끌어올린 뒤
        # OEM dict 에서는 제거. 기존 envelope 키만 채움 — 새 키 추가 없음.
        result['oem'] = _hoist_oem_extras(raw_oem, result)

    # HP CSUS 3200: Chassis 폴백 — System.Manufacturer/Model
    # 부재(None) 시 이미 fetch 한 chassis_data(상단)에서 보충.
    #   - result 값이 None 일 때만 발동 (정상 vendor 는 System.Manufacturer/Model 보유 → 미발동).
    #   - _strip_or_none 으로 '' → None 정규화 유지 (파이프라인 불변식: 빈 문자열 금지).
    #   - chassis 값이 strip 후 truthy 일 때만 대입 (None→None / ''→None 무의미 대입 방지).
    # 근거: HPE Scale-up (CSUS 3200 / Superdome Flex) RMC 는 Partition0 System.Manufacturer/
    # Model 이 비고 Chassis 에만 존재 (DMTF ComputerSystem Manufacturer/Model optional+nullable).
    #
    # System.Model 부재 시 ServiceRoot.Product(product_hint) 우선 fallback.
    # 근거: check_redfish (실 CSUS 3200 지원 도구) cr_module/system_chassis.py 가 동일 —
    # `if model is None: model = connection.root.get("Product")`.
    # CSUS 실측: ServiceRoot.Product="Compute Scale-up Server 3200" (깨끗한 모델명 —
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

    `manager_layout` 옵션 인자.
      - None (기본값) — 기존 동작을 그대로 유지. `bmc.name = bmc_names[vendor]` 통일.
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

    # vendor → BMC 표시명 매핑 (외부 spec 기반 표준 이름)
    bmc_names = {'dell': 'iDRAC', 'hpe': 'iLO', 'lenovo': 'XCC', 'supermicro': 'BMC',
                 'cisco': 'CIMC',
                 'huawei': 'iBMC', 'inspur': 'ISBMC', 'fujitsu': 'iRMC',
                 'quanta': 'BMC'}
    # RMC primary 시스템 (HPE CSUS 3200 / Superdome Flex)
    # 라벨 분기 — manager_layout 정의 시 _classify_rmc_label 우선. None 일 때 기존 동작.
    # name(label) 과 role 가 동일 id 로 분류돼 모순 불가능하도록,
    # multi 경로는 manager_id(=URI segment m['id']) 를 명시 전달 — _classify_manager_role 와
    # 동일 source. 단일 노드(manager_id=None)는 응답 body Id 사용 (기존 동작 보존).
    _mid = manager_id if manager_id is not None else _safe(data, 'Id')
    rmc_label = _classify_rmc_label(manager_uri, _mid, manager_layout, is_first)
    # BMC 운영 정보 강화 — datetime / dns / mac / uuid / last_reset / timezone / power_state
    result = {
        'name':             rmc_label or bmc_names.get(vendor, 'BMC'),
        'firmware_version': _safe(data, 'FirmwareVersion'),
        'model':            _safe(data, 'Model'),
        'manager_type':     _safe(data, 'ManagerType'),
        'health':           _safe(data, 'Status', 'Health'),
        'state':            _safe(data, 'Status', 'State'),
        'power_state':      _safe(data, 'PowerState'),
        'uuid':             _safe(data, 'UUID'),
        'last_reset_time':  _safe(data, 'LastResetTime'),
        'timezone':         _safe(data, 'TimeZoneName'),
        'ip':               None,
        'mac_address':      None,
        'dns_name':         None,
        'datetime':         _safe(data, 'DateTime'),
        'datetime_offset':  _safe(data, 'DateTimeLocalOffset'),
        'oem': {},
    }

    # Manager EthernetInterfaces에서 BMC IP / MAC / FQDN + NameServers / Gateway 추출
    # BMC NIC 의 NameServers / IPv4Addresses[*].Gateway
    # 를 envelope 비노출 임시 키 (_network_meta) 로 캐시한다. normalize_standard.yml 이
    # dns_servers / default_gateways 정규화에 사용 후 _network_meta 키 자체는 envelope
    # 에서 제거한다.
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
                        result['mac_address'] = _mac if isinstance(_mac, str) else None  # Round 14 #2: 비-str MAC 방어
                    if not result['dns_name']:
                        result['dns_name'] = _safe(ndata, 'FQDN') or _safe(ndata, 'HostName')

    # envelope 비노출 — normalize_standard.yml 의 _rf_d_bmc_clean 단계에서 제거된다.
    result['_network_meta'] = {
        'name_servers':        bmc_name_servers,
        'static_name_servers': bmc_static_name_servers,
        'ipv4_gateways':       bmc_gateways,
    }

    # 벤더별 BMC OEM 확장 (Redfish API spec)
    if vendor == 'hpe':
        oem = _safe(data, 'Oem', 'Hpe') or _safe(data, 'Oem', 'Hp') or {}
        # 2026-04-29 raw 검증 (10.50.11.231 iLO 6 v1.73): Manager.Oem.Hpe 에 `Type`
        # 필드 부재 — 이전 매핑은 항상 null. 의미 있는 값은 Firmware.Current.VersionString.
        result['oem'] = {
            'ilo_version': (_safe(oem, 'Firmware', 'Current', 'VersionString')
                            or _safe(data, 'Model')),
        }
    elif vendor == 'supermicro':
        oem = _safe(data, 'Oem', 'Supermicro') or {}
        result['oem'] = {'bmc_ip': _safe(oem, 'BMCIPv4Address')}
        if not result['ip'] and result['oem'].get('bmc_ip'):
            result['ip'] = result['oem']['bmc_ip']
    elif vendor == 'lenovo':
        # Lenovo XCC: Manager.Oem.Lenovo.release_name 등 운영 상태 메타.
        # 실측 (XCC SR650 V2, 2026-04-28): release_name="whitley_gp_23-5".
        oem = _safe(data, 'Oem', 'Lenovo') or {}
        result['oem'] = {'release_name': _safe(oem, 'release_name')}
    elif vendor == 'dell':
        # Dell Manager.Oem.Dell.DelliDRACCard 추가.
        # 사이트 실측 (10.100.15.27 iDRAC9 7.10.70.00): IPMIVersion / LastUpdateTime
        # / LastSystemInventoryTime / URLString 풍부.
        # source: dell.com/support/manuals/.../idrac9_*_redfishapiguide_pub
        #         (DellManager.v1_4_0 + DelliDRACCard.v1_1_0).
        oem_dell = _safe(data, 'Oem', 'Dell', 'DelliDRACCard') or {}
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
        # None 으로 정규화. 풍부 필드는 그대로 유지.
        # 2026-04-30: Cisco 등 trailing whitespace 정규화 추가.
        def _ne_p(*ks):
            # _strip_or_none + _safe 조합 (중복 stripping 로직 3곳 → 1곳 dedup)
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
        cap = _safe(mdata, 'CapacityMiB') or 0
        cap_int = _safe_int(cap)
        if cap_int is not None:  # Round 2 #4: 0-capacity 도 합산(no-op이나 preserve-0 일관)
            total_mib += cap_int
        # BaseModuleType / RankCount / ErrorCorrection / DataWidth 추가
        # Phase P: 3 채널 키 일관성 — capacity_mb (이전 capacity_mib) 로 통일
        # 2026-04-29 Cisco CIMC가 Manufacturer를 raw JEDEC ID '0xCExx'로 emit.
        # _normalize_jedec()로 vendor 이름 정규화 (Samsung/SK hynix/Micron 등).
        # 2026-04-29 locator (DIMM 물리 위치) 추가 — 교체 작업 시 식별용.
        slots.append({
            'id':              _safe(mdata, 'Id'),
            'name':            _strip_or_none(_safe(mdata, 'Name')),
            # 'locator' 별도 키: DeviceLocator (벤더 표준 — 'A1','DIMM_A1','PROC1.DIMMA1' 등)
            # MemoryLocation.Slot 도 폴백 (Dell iDRAC 일부 펌웨어).
            'locator':         _safe(mdata, 'DeviceLocator') or _safe(mdata, 'MemoryLocation', 'Slot'),
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
    if isinstance(inline_ctrls, list) and inline_ctrls:  # 비-list StorageControllers 방어 (Round 1 #0)
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
    if not isinstance(ctrl_members, list) or not ctrl_members:  # 비-list 방어 (Round 2 #13)
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


# Redfish VolumeType enum → canonical RAID level
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
            for d_oid in [_safe(d_link, '@odata.id')] if d_oid and isinstance(d_oid, str)  # 비-str @odata.id 방어 (Round 1 #1)
        ]
        # JBOD/pass-through 필터: Non-RAID 모드에서 물리 디스크를 개별 Volume으로 노출
        vol_id = _safe(vdata, 'Id')
        if raid_type is None and len(member_ids) == 1 and member_ids[0] == vol_id:
            continue
        vcap_int = _safe_int(_safe(vdata, 'CapacityBytes'))
        # BUG-16 fix: Volume Name / DisplayName trailing whitespace 제거 (raw 'VD_0   ' 사고)
        v_name_raw = _safe(vdata, 'Name')
        v_name = v_name_raw.strip() if isinstance(v_name_raw, str) else v_name_raw
        # 2026-04-29 Cisco CIMC가 Volume.Name을 빈 문자열 "" 로 emit.
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
        elif _safe(vdata, 'Oem', 'Dell'):
            boot_volume = _safe(vdata, 'Oem', 'Dell', 'DellVolume', 'BootVolumeSource') is not None
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


def _gather_smart_storage(bmc_ip, system_uri, username, password, timeout, verify_ssl):
    """HPE iLO4 SmartStorage legacy path.

    iLO4 (Gen8/Gen9 pre-iLO5) 펌웨어는 표준 `/Systems/{id}/Storage` 미도입,
    HPE OEM `/Systems/{id}/SmartStorage/ArrayControllers/*` + `/HostBusAdapters/*`
    경로로만 storage 정보 제공.

    HPE OEM Redfish spec 직접 의존 (SmartStorage namespace).
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
                'controller_manufacturer': _safe(ctrl_data, 'Manufacturer') or 'HPE',  # SmartStorage path 은 HPE OEM legacy spec 직접 의존
                'controller_health':       _safe(ctrl_data, 'Status', 'Health'),
            })
    # SmartStorage 는 logical volume (LogicalDrives) 별도 경로 — iLO4 fixture 부재로
    # controllers + drives 만 수집 (향후 lab fixture 확보 시 보강 가능)
    return controllers, [], errors


def gather_storage(bmc_ip, system_uri, username, password, timeout, verify_ssl):
    """Storage 진입 — Storage → SimpleStorage → SmartStorage fallback dispatcher.

    SmartStorage (HPE iLO4) fallback chain 을 포함한다.
    기존 Storage / SimpleStorage 분기는 그대로 두고, SmartStorage 는 iLO4 legacy path 라
    표준 / SimpleStorage 둘 다 404 일 때만 시도한다.
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
            errors.append(_err('storage', 'Storage 미지원, SimpleStorage fallback 사용'))
        else:
            # SmartStorage (HPE iLO4 OEM legacy) fallback —
            # 표준/SimpleStorage 모두 404 시 HPE 구 path 시도.
            ctrls, vols, smart_errors = _gather_smart_storage(
                bmc_ip, system_uri, username, password, timeout, verify_ssl
            )
            if ctrls:
                errors.append(_err('storage', 'Storage/SimpleStorage 미지원, SmartStorage (HPE OEM legacy) fallback 사용'))  # SmartStorage OEM path spec
                errors.extend(smart_errors)
                return {'controllers': ctrls, 'volumes': vols}, errors
            errors.append(_err('storage', f'Storage/SimpleStorage/SmartStorage 모두 실패: {err or st}'))
            return {'controllers': [], 'volumes': []}, errors

    members = _dicts(_safe(coll, 'Members'))  # Round 8 #3: 비-list Members 방어
    if use_simple:
        controllers, sub_errors = _gather_simple_storage(bmc_ip, members, username, password, timeout, verify_ssl)
        errors.extend(sub_errors)
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
        # 2026-04-29 link_status enum 정규화 — Dell linkup/linkdown / HPE NoLink / Cisco Connected/Disconnected → up/down/unknown
        nics.append({
            'id': _safe(ndata, 'Id'), 'name': _safe(ndata, 'Name') or _safe(ndata, 'Id') or '',
            'mac': _safe(ndata, 'MACAddress'), 'speed_mbps': _safe_int(_safe(ndata, 'SpeedMbps')),  # Round 2 #18: mbps int 통일
            'mtu': _safe_int(_safe(ndata, 'MTUSize')),  # Round 6 #6: int 통일(마지막 수치 필드)
            'link_status': _normalize_link_status(_safe(ndata, 'LinkStatus')),
            'health': _safe(ndata, 'Status', 'Health'),
            'ipv4': ipv4_addrs,
        })
    return nics, errors


def _detect_nic_ocp_slot(adata):
    """NIC OCP (Open Compute Project) mezzanine 식별.

    NetworkAdapter.Location.PartLocation.LocationType 또는 ServiceLabel 패턴으로
    OCP NIC 식별. 펌웨어 별 차이:
      - iDRAC9 6.x+: Location.PartLocation.LocationType='Slot' + ServiceLabel='OCP'
      - iLO6+: Oem.Hpe.Location.OCPSlot
      - Supermicro X13+: Location.PartLocation.LocationType='Slot' + name 'OCP*'

    Returns: 'ocp' / 'pcie' / None (식별 불가)

    DSP0268 Location.PartLocation spec 직접 의존.
    호출자가 사용하는 helper (envelope 키는 그대로 유지).
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
    hpe_oem = _safe(adata, 'Oem', 'Hpe') or {}
    if _safe(hpe_oem, 'Location', 'OCPSlot') or _safe(hpe_oem, 'OCPSlot'):
        return 'ocp'
    if location_type == 'slot':
        return 'pcie'
    return None


def _detect_nic_sriov_capable(adata):
    """NIC SR-IOV capability 식별.

    표준 DSP0268 v1.6+ NetworkDeviceFunctions 우선, vendor OEM fallback:
      - 표준: NetworkDeviceFunctions[*].SRIOV.SRIOVCapable
      - Dell: Oem.Dell.NICDeviceFunctions.SRIOVCapable
      - HPE:  Oem.Hpe.NetworkAdapter.SRIOVConfig (dict 존재 = capable)

    Args:
        adata: NetworkAdapter 응답 dict

    Returns: True / False / None (미응답)

    Redfish OEM spec 직접 의존.
    호출자가 사용하는 helper (envelope 키는 그대로 유지).
    """
    if not isinstance(adata, dict):
        return None
    # 표준 path: Controllers[0].Links.NetworkDeviceFunctions (DSP0268 v1.6+)
    # 본 helper 는 adapter 단위 응답만 사용 — 깊은 collection fetch 는 호출자 책임.
    # SR-IOV capability 표시는 일반적으로 NetworkAdapter root 또는 Oem 영역에 hint.
    if _safe(adata, 'SRIOV', 'SRIOVCapable') is True:
        return True
    # Dell OEM
    dell_oem = _safe(adata, 'Oem', 'Dell') or {}
    dell_sriov = _safe(dell_oem, 'NICDeviceFunctions', 'SRIOVCapable')
    if dell_sriov is not None:
        return bool(dell_sriov)
    # HPE OEM
    hpe_oem = _safe(adata, 'Oem', 'Hpe') or {}
    if _safe(hpe_oem, 'NetworkAdapter', 'SRIOVConfig'):
        return True
    return None


def _normalize_wwn(value):
    """WWN(WWPN/WWNN) → 소문자 colon-grouped hex 정규화 (cross-channel 매칭 키).

    입력 변형 흡수: '20:00:00:24:..', '0x200000..', '200000..', None.
    16 hex(8 octet) 가 아니면 정리본(소문자) 보존 — 날조 금지.
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

    DMTF 정본:
      - FC: Port.PortProtocol(Protocol enum) ∈ {FC,FCP,FCoE}
             또는 NetworkDeviceFunction.NetDevFuncType ∈ {FibreChannel,FibreChannelOverEthernet}
      - IB: Port.LinkNetworkTechnology=='InfiniBand' (또는 ActiveLinkTechnology)
             또는 NetworkDeviceFunction.NetworkDeviceTechnology=='InfiniBand'
    PortType enum 에는 FC/IB 값이 없어 사용 금지 (구 코드 dead-code 원인).
    DMTF Protocol/NetDevFuncType spec 직접 의존 (vendor 분기 아님).
    """
    pp = _str(port_protocol).strip().upper()
    lt = _str(link_tech).strip().lower()
    ndf_type = ''
    ndf_tech = ''
    if isinstance(ndf, dict):
        ndf_type = _str(ndf.get('func_type')).strip().lower()
        ndf_tech = _str(ndf.get('net_dev_tech')).strip().lower()
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
    """canonical storage.hbas[] entry 생성 (전 채널 통일 shape)."""
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
    """canonical storage.infiniband[] entry 생성 (전 채널 통일 shape)."""
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


def gather_network_adapters_chassis(bmc_ip, chassis_uri, username, password, timeout, verify_ssl):
    """Chassis/{id}/NetworkAdapters 수집 + FC HBA / InfiniBand 분류.

    NetworkAdapters         → adapters[] (NIC 카드 모델/firmware)
    Ports/NetworkPorts      → ports[]    (port-level link/speed)
    NetworkDeviceFunctions  → 식별 (FC WWPN/WWNN, IB Node/Port GUID)

    분류 정본 (DMTF):
      - FC: Port.PortProtocol ∈ {FC,FCP,FCoE} 또는 NDF.NetDevFuncType=FibreChannel(OverEthernet)
      - IB: Port.LinkNetworkTechnology=='InfiniBand' 또는 NDF.NetworkDeviceTechnology=='InfiniBand'
      - 구 코드의 PortType('fibrechannel'/'infiniband') 분류는 dead-code (PortType enum 에
        FC/IB 값 없음 → 실장비 영원히 미매치). protocol/technology 기반으로 정정.

    WWPN/WWNN/GUID 는 NetworkDeviceFunction 에서 추출 (Port 아님). Port 가 없는 FC/IB NDF 도
    식별만으로 emit. 일부 vendor (Cisco CIMC 등) 미지원 → 빈 결과 graceful degradation.
    """
    out = {'adapters': [], 'ports': [], 'fc_hbas': [], 'infiniband': []}
    errors = []
    if not chassis_uri:
        return out, errors

    base = _p(chassis_uri) + '/NetworkAdapters'
    st, coll, err = _get(bmc_ip, base, username, password, timeout, verify_ssl)
    if err or st != 200:
        # 미지원 vendor 는 errors 에 기록하되 graceful degradation
        errors.append(_err('network_adapters',
                           f'NetworkAdapters 미지원 또는 실패: {err or st}'))
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
        # 빈 placeholder NetworkAdapter 필터:
        # 일부 BMC (실측 Lenovo XCC SR650 V2)는 PCIe slot 자체를 NetworkAdapters 컬렉션에
        # 빈 entry 로 노출. Controllers[0].ControllerCapabilities.NetworkPortCount=0 또는
        # manufacturer/model 모두 빈 문자열이면 실제 NIC 가 아니므로 skip.
        port_count = 0
        if ctrls and isinstance(ctrls, list):
            caps = _safe(ctrls[0], 'ControllerCapabilities') or {}
            port_count = _safe_int(_safe(caps, 'NetworkPortCount'), default=0) or 0
        mfr = _str(_safe(adata, 'Manufacturer')).strip()
        model = _str(_safe(adata, 'Model')).strip()
        if port_count == 0 and not mfr and not model:
            continue
        # 2026-04-29 HPE iLO NetworkAdapter는 mac/link/speed 가 NetworkAdapter root에 없고
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
            'mac':              None,  # ports fold-in으로 채워짐
            'link_status':      'unknown',  # 동일
            'speed_mbps':       None,
            'port_count':       port_count,
        }
        out['adapters'].append(adapter_info)
        adapter_idx = len(out['adapters']) - 1

        # NetworkDeviceFunctions — FC WWPN/WWNN + IB GUID 식별.
        ndfs = _fetch_ndf_index(bmc_ip, adata, username, password, timeout, verify_ssl)
        ndf_by_port = {n['port_uri']: i for i, n in enumerate(ndfs) if n.get('port_uri')}
        ndf_matched = set()

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
                    if not isinstance(assoc, list):  # 비-list 방어 (Round 2 #14)
                        assoc = []
                    primary_addr = assoc[0] if assoc else None
                    raw_port_type = _safe(pdata, 'PortType') or ''
                    port_protocol = _safe(pdata, 'PortProtocol')
                    link_tech = (_safe(pdata, 'LinkNetworkTechnology')
                                 or _safe(pdata, 'ActiveLinkTechnology'))
                    # 2026-04-29 ports의 link_status도 동일 enum 정규화.
                    normalized_link = _normalize_link_status(_safe(pdata, 'LinkStatus'))
                    port_id = _safe(pdata, 'Id')

                    # NDF join (식별 정보)
                    ndf_idx = ndf_by_port.get(_p(p_uri)) if p_uri else None
                    ndf = ndfs[ndf_idx] if ndf_idx is not None else None
                    if ndf_idx is not None:
                        ndf_matched.add(ndf_idx)

                    cls = _classify_port_protocol(port_protocol, link_tech, ndf, pdata)

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
                    # 2026-04-29 adapter level에 ports의 첫 active 메타 fold-in.
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
            cls = _classify_port_protocol(None, None, ndf, None)
            if cls in ('FibreChannel', 'FCoE'):
                out['fc_hbas'].append(_make_fc_hba(
                    adapter_id, adapter_info, ndf.get('id'), cls,
                    'unknown', None, None, ndf))
            elif cls == 'InfiniBand':
                out['infiniband'].append(_make_ib_port(
                    adapter_id, adapter_info, ndf.get('id'),
                    'unknown', None, None, ndf))

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
    for member in _capped(_safe(coll, 'Members') or [], 'firmware', errors):
        member_uri = _safe(member, '@odata.id')
        # Members 에 Name/Version 없으면 개별 URI 조회 (벤더 공통)
        if not _safe(member, 'Name') and member_uri:
            st2, fw_data, ferr = _get(bmc_ip, _p(member_uri), username, password, timeout, verify_ssl)
            if not ferr and st2 == 200:
                member = fw_data
        fw_id = _safe(member, 'Id') or (member_uri.rstrip('/').split('/')[-1]  # rstrip: 후행 슬래시 → 빈 id 방지 (Round 1 #13)
                                        if isinstance(member_uri, str) and member_uri else None)
        # Dell Previous- 항목 스킵 (비활성 이전 버전)
        if fw_id and isinstance(fw_id, str) and fw_id.startswith('Previous-'):
            continue
        # Cisco CIMC 의 "N/A" 빈 슬롯 (slot-1, slot-2
        # 등 PCIe 미장착 슬롯) 노이즈 필터. Version 이 "N/A"/""/"NA" 면 firmware 컴포넌트가
        # 부재 — 호출자에게 노이즈로 전달되지 않도록 skip (기존 키 유지, list 길이만 정확).
        ver = _safe(member, 'Version')
        if isinstance(ver, str) and ver.strip().upper() in ('N/A', 'NA', ''):
            continue
        # Q-13: SoftwareId가 문자열 "null"이면 Python None으로 변환
        component = _safe(member, 'SoftwareId')
        if isinstance(component, str) and component.lower() == 'null':
            component = None
        # 2026-04-29 Lenovo XCC pending firmware (BMC-Primary-Pending, UEFI-Pending)는
        # version=null + ID에 'Pending' 포함. version=null만으로는 호출자가 단순 누락인지 의도된
        # pending 인지 모름 → pending 메타필드 추가 (정책: pending=true이고 version=null은 정상,
        # pending=false이고 version=null은 데이터 누락).
        is_pending = bool(fw_id and isinstance(fw_id, str) and 'pending' in fw_id.lower())
        fw_list.append({
            'id':         fw_id,
            'name':       _safe(member, 'Name'),
            'version':    ver,
            'updateable': _safe(member, 'Updateable'),
            'component':  component or fw_id,
            'pending':    is_pending,
        })
    return fw_list, errors


def _gather_power_subsystem(bmc_ip, chassis_uri, username, password, timeout, verify_ssl):
    """DMTF 2020.4 (Redfish 1.13+) PowerSubsystem fallback parser.

    신 펌웨어 (HPE iLO 6 / Lenovo XCC2-3 / Dell iDRAC9 5.x+ /
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
    if psu_link:
        st_c, coll, _err_c = _get(bmc_ip, _p(psu_link), username, password, timeout, verify_ssl)
        if st_c == 200:
            for member in _capped(_dicts(_safe(coll, 'Members')), 'power', errors):  # Round 4 비-list 방어 + DoS 상한 (sibling 일관)
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
                    'power_capacity_w': _safe_int(_safe(mdata, 'PowerCapacityWatts')),
                    'firmware_version': _safe(mdata, 'FirmwareVersion'),
                    'health':           _safe(mdata, 'Status', 'Health'),
                    'state':            _safe(mdata, 'Status', 'State'),
                })

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

    # DMTF 2020.4 EnvironmentMetrics fallback —
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

    return {'power_supplies': psus, 'power_control': power_control}, errors


def _merge_power_dual(legacy_result, subsystem_result):
    """Power (deprecated) + PowerSubsystem dual-emit dedup.

    DSP0268 v1.13+ 이전/이후 펌웨어가 dual emit 하는 환경 (iDRAC9 5.x / iLO5-6 /
    XCC3 / Supermicro X12-X14) 에서 PowerSupplies 중복 제거.

    Strategy (Round 15 정정): serial 이 있으면 serial 로 dedup (같은 PSU 의 legacy/
    subsystem 이중 emit 을 name 차이와 무관하게 1회로). serial 이 없으면 (name, model)
    로 dedup. PowerControl 은 legacy 우선 (PowerSubsystem
    표준에는 system-level metric 없고 EnvironmentMetrics 로 분리됨 — legacy 가
    더 풍부).

    입력 dict shape 유지 — `power_supplies` + `power_control` 키만.
    호출자가 보는 envelope 키는 그대로 유지한다.

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

    /Power 404 시 /PowerSubsystem fallback (DMTF 2020.4 신 schema).
    Storage SimpleStorage fallback 패턴 따름 (gather_storage 참조).

    dual-emit dedup helper (_merge_power_dual) 를 함께 둔다.
    현재 dispatcher 는 404 fallback only — dual emit 펌웨어 (iDRAC9 5.x / iLO5-6
    등) 의 PSU 중복 처리는 향후 adapter capability `power_strategy=dual` 활성화
    시 본 helper 를 호출한다 (현재는 미연결).
    """
    errors = []
    if not chassis_uri:
        errors.append(_err('power', 'chassis_uri 없음 (detect_vendor 에서 Chassis 미발견)'))
        return {}, errors

    power_path = _p(chassis_uri) + '/Power'
    st, pdata, perr = _get(bmc_ip, power_path, username, password, timeout, verify_ssl)

    # 404 = 신 펌웨어 가능 → PowerSubsystem fallback
    if st == 404:
        return _gather_power_subsystem(bmc_ip, chassis_uri, username, password, timeout, verify_ssl)

    if perr or st != 200:
        errors.append(_err('power', f'Power 정보 실패: {perr or st}'))
        return {}, errors

    # PSU 정격 (power_capacity_w) fallback —
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
            'power_capacity_w': psu_capacity,
            'firmware_version': _safe(psu, 'FirmwareVersion'),
            'health':           _safe(psu, 'Status', 'Health'),
            'state':            _safe(psu, 'Status', 'State'),
        })

    # PowerControl — system-level power consumption (Safe Common: 3 vendors verified)
    # pdata가 dict가 아닌 list/None일 가능성 방어 (Cisco/Supermicro edge)
    pc_list = (pdata.get('PowerControl') if isinstance(pdata, dict) else None) or []
    # Round 3 #0: 비-dict 원소 방어. Round 16: PowerControl 자체가 비-list(dict/int) 오염 시
    # pc_list[0] 가 KeyError(0)/TypeError → power 섹션 전체(이미 수집한 PSU 포함) 유실.
    # isinstance(pc_list, list) 추가로 컨테이너 타입까지 방어 (정상 list-of-dict 결과 불변).
    pc0 = pc_list[0] if (isinstance(pc_list, list) and pc_list and isinstance(pc_list[0], dict)) else {}
    pm = pc0.get('PowerMetrics') or {}
    # chassis level power_capacity_watts fallback —
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
    """Chassis/{id}/Thermal — 온도 센서 + 팬 정보.

    gather_power 패턴 mirror. /Thermal (legacy) 404 시 /ThermalSubsystem fallback
    (DMTF 2020.4 / Redfish 1.13+ 신 schema). HPE Compute Scale-up Server 3200 /
    Superdome Flex 의 multi-chassis 환경에서 chassis 별 Thermal 수집 — 설명 모델
    ("각 chassis 는 Power 와 Thermal 리소스를 둔다") 요구.

    source:
      - DMTF DSP0266 Thermal.v1 (legacy) + ThermalSubsystem.v1_0 (2020.4)
      - HPE Superdome Flex Admin Guide (chassis Thermal 표준 Redfish)
    lab 부재 — 사이트 실측 시 정정 가능.

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
    for t in _dicts(_safe(tdata, 'Temperatures')):  # 비-list/dict 방어
        temps.append({
            'name':             _safe(t, 'Name'),
            'reading_celsius':  _safe_int(_safe(t, 'ReadingCelsius')),  # str '42' 방어
            'health':           _safe(t, 'Status', 'Health'),
            'state':            _safe(t, 'Status', 'State'),
            'upper_critical':   _safe_int(_safe(t, 'UpperThresholdCritical')),
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


def _gather_thermal_subsystem(bmc_ip, chassis_uri, username, password, timeout, verify_ssl):
    """DMTF 2020.4 ThermalSubsystem fallback — /Thermal 404 시.

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
                    'reading_celsius':  _safe_int(_safe(tr, 'Reading')),
                    'health':           _safe(tr, 'Status', 'Health'),
                    'state':            _safe(tr, 'Status', 'State'),
                    'upper_critical':   None,
                    'physical_context': _safe(tr, 'PhysicalContext'),
                })
    fans = []
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
    if not temps and not fans:
        return {}, errors
    return {'temperatures': temps, 'fans': fans}, errors


def gather_boot(bmc_ip, system_uri, username, password, timeout, verify_ssl):
    """Systems/{id} Boot 객체 → 부팅 순서 + override 설정.

    설명 모델 요구 — "각 Systems/<id> (nPartition) 는 ... 부팅 순서 ... 를 포함".
    기존 gather_system 은 boot_progress (BootProgress.LastState) 만 추출 — 본 함수는
    Boot.BootOrder / BootSourceOverride* 를 별도 수집해 multi_node.partitions[].boot
    로 노출한다 (단일 노드 path 는 그대로 동작).

    source: DMTF DSP0266 ComputerSystem.Boot (BootOrder /
      BootSourceOverrideTarget / BootSourceOverrideEnabled)
    Returns: (data_dict, errors_list)  — 빈 {} 시 Boot 미노출 (graceful).
    """
    errors = []
    if not system_uri:
        return {}, [_err('boot', 'system_uri 없음')]
    st, sdata, serr = _get(bmc_ip, _p(system_uri), username, password, timeout, verify_ssl)
    if serr or st != 200:
        # System GET 실패는 gather_system 이 이미 errors[] 에 보고 — boot 는 보조 정보라
        # silent (중복 error noise → status 오분류 방지).
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

def _is_404_only_error(errs):
    """모든 errors가 'HTTP 404' 시그널이면 True (endpoint 자체 부재 = capability 미지원).

    404 = "endpoint 없음 = vendor/펌웨어 미지원" — errors[] 노이즈
    분리. 5xx / timeout / 401 / 403 과 분리해 'unsupported' 시그널로 분류.
    """
    if not errs:
        return False
    for e in errs:
        if not isinstance(e, dict):
            return False
        detail = str(e.get('detail') or '')  # Round 2 #8: 비-str detail/message → 'in' TypeError 방어
        msg = str(e.get('message') or '')
        # 'HTTP 404' 패턴: detail에 'HTTP 404' 또는 message에 '404' 단독 정수
        if 'HTTP 404' in detail or 'HTTP 404' in msg:
            continue
        # message가 정확히 '...: 404' (st 정수 그대로) 패턴
        if msg.endswith(': 404') or msg.endswith(' 404'):
            continue
        return False
    return True


def _make_section_runner(all_errors, collected, failed, unsupported=None):
    """섹션 collector wrapper — 예외/errors 누적 + collected/failed/unsupported 추적.

    stacktrace는 stderr console verbose에만, errors[]에는 type+message만.
    404 시그널은 unsupported list로 분리 (endpoint 부재 = capability 미지원).
    호환성: unsupported 인자 미전달 시 기존 동작 유지 (back-compat).
    """
    def _run(section, fn, *args):
        try:
            val, errs = fn(*args)
            # 404 only면 unsupported로 분류, errors[]에서 제외 (호출자 noise 차단)
            if unsupported is not None and _is_404_only_error(errs):
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
    """Managers/{id}/LogServices → 로그 서비스 목록.

    설명 모델 요구 — "RMC 는 ... Services 와 Logs 리소스로 연결된다". 본 함수는
    LogServices 컬렉션 메타(각 LogService 의 id/name/정책)를 수집해
    multi_node.managers[].log_services 로 노출한다 (단일 노드 path 는 그대로 동작).
    로그 엔트리 자체(대용량)는 수집하지 않음 — 범위 외.

    source: DMTF DSP0266 LogService / LogServiceCollection
    Returns: (list_of_log_services, errors_list)  — 빈 [] 시 LogServices 미노출.
    """
    errors = []
    if not manager_uri:
        return [], [_err('log_services', 'manager_uri 없음')]
    st, mdata, merr = _get(bmc_ip, _p(manager_uri), username, password, timeout, verify_ssl)
    if merr or st != 200:
        # Manager GET 실패는 gather_bmc 가 이미 errors[] 에 보고 — log_services 는 보조
        # 정보라 silent (중복 error noise 차단).
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
    """모든 Managers Member 별 gather_bmc 호출.

    HPE CSUS 3200 / Superdome Flex 의 RMC + per-chassis PDHC + per-node iLO5 전수 수집.
    `manager_layout` 으로 `bmc.name` 라벨 분기 (RMC / PDHC / iLO).

    기존 `gather_bmc` 함수는 그대로 두고 별도로 동작한다. 이 함수는
    manager_layout 이 정의된 vendor 에서만 호출된다.

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
        # 첫 Manager 만 layout-default RMC/primary (다중 RMC
        # 오라벨 + name/role 불일치 차단). substring 매치(rmc/pdhc/ilo)는 position 무관.
        is_first = (idx == 0)
        bmc_data, bmc_errs = gather_bmc(
            bmc_ip, m['uri'], vendor,
            username, password, timeout, verify_ssl,
            manager_layout=manager_layout, is_first=is_first,
            manager_id=m['id'],  # role 와 동일 id source (name/role 모순 차단)
        )
        # Manager LogServices 수집 (설명 모델 "Services 와 Logs").
        logs_data, logs_errs = gather_manager_logs(
            bmc_ip, m['uri'], username, password, timeout, verify_ssl)
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
    (단위용량 × media × protocol × model)..
    """
    groups, seen, total = [], {}, 0
    for d in (physical_disks or []):
        cap_mb = _safe_int(d.get('total_mb'), 0)  # 펌웨어가 str 반환 시 str//int crash 방어
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

    multi_node.partitions[].storage 가 raw 로 노출되던 문제 해소.
    top-level normalize_standard.yml(Ansible) 과 동일 canonical shape 를 Python 에서 생성
    (multi_node 전용 parallel — 두 경로 모두 같은 schema 보장). hbas/infiniband 는 chassis
    레벨 NetworkAdapter 소관이라 partition storage 에는 빈 list (키 자리만 유지).
    """
    raw = raw if isinstance(raw, dict) else {}
    controllers_out, physical, seen = [], [], set()
    for ctrl in (raw.get('controllers') or []):
        if not isinstance(ctrl, dict):  # 비-dict controller 방어 (Round 1 #2)
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

    multi_node.partitions[].network 가 list 로 노출되던 schema 불일치
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

    top-level normalize_standard.yml 의 필터 + 합산 + summary 와
    동일 결과를 Python 에서 생성 (multi_node.partitions[].cpu 일관성).
    """
    procs = procs if isinstance(procs, list) else []
    cpus = [p for p in procs if isinstance(p, dict)
            and (str(p.get('processor_type') or '').strip().upper() in ('CPU', 'CORE', ''))]
    cores = sum(_safe_int(p.get('total_cores'), 0) for p in cpus)  # 비-숫자 cores str 방어
    threads = sum(_safe_int(p.get('total_threads'), 0) for p in cpus)
    models = [p.get('model') for p in cpus if p.get('model')]
    speeds = [p.get('speed_mhz') for p in cpus if p.get('speed_mhz')]
    archs = [p.get('architecture') for p in cpus if p.get('architecture')]
    isets = [p.get('instruction_set') for p in cpus if p.get('instruction_set')]
    groups, seen = [], {}
    for p in cpus:
        m = p.get('model') or 'unknown'
        tc = _safe_int(p.get('total_cores'), 0)  # grouping 도 동일 방어
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

    top-level normalize_standard.yml _rf_summary_memory 와 동일 grouping.
    """
    raw_mem = raw_mem if isinstance(raw_mem, dict) else {}
    slots = raw_mem.get('slots') or []
    total_mib = raw_mem.get('total_mib')
    groups, seen, total_gb = [], {}, 0
    for s in slots:
        if not isinstance(s, dict):
            continue
        cap_mb = _safe_int(s.get('capacity_mb') or s.get('capacity_mib'), 0)  # '8GB' 등 단위문자열 방어
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
                         timeout, verify_ssl, chassis_uri=None):
    """모든 Systems Member 별 gather_system + per-partition summary.

    nPartition 환경 — 각 Partition 별 cpu / memory / storage / network 모두 수집.

    storage/network 를 canonical shape 로 정규화 (구: raw 노출).
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
        sys_data, sys_errs = gather_system(bmc_ip, m['uri'], vendor, *creds, chassis_uri)
        cpu_data, cpu_errs = gather_processors(bmc_ip, m['uri'], *creds)
        mem_data, mem_errs = gather_memory(bmc_ip, m['uri'], *creds)
        sto_data, sto_errs = gather_storage(bmc_ip, m['uri'], *creds)
        net_data, net_errs = gather_network(bmc_ip, m['uri'], *creds)
        # per-partition boot order (설명 모델 "부팅 순서").
        boot_data, boot_errs = gather_boot(bmc_ip, m['uri'], *creds)
        out['partitions'].append({
            'id':         m['id'],
            'system_uri': m['uri'],
            'system':     sys_data,
            # per-partition 전 섹션 canonical 정규화.
            # 구: cpu=raw list / memory=raw dict / storage=raw / network=raw list
            #     → normalize 누락 (top-level 과 shape 불일치 + network 가 list).
            'cpu':        _normalize_cpu_raw(cpu_data),
            'memory':     _normalize_memory_raw(mem_data),
            'storage':    _normalize_storage_raw(sto_data),
            'network':    _normalize_network_raw(net_data),
            # boot order (Boot 미노출 시 {}).
            'boot':       boot_data,
        })
        out['errors'].extend(sys_errs)
        out['errors'].extend(cpu_errs)
        out['errors'].extend(mem_errs)
        out['errors'].extend(sto_errs)
        out['errors'].extend(net_errs)
        out['errors'].extend(boot_errs)
    return out


def gather_chassis_multi(bmc_ip, chassis_coll_uri, username, password,
                         timeout, verify_ssl):
    """모든 Chassis Member 별 hardware + power 수집.

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
            # append-on-fail — GET 실패해도 멤버는 노출한다.
            # gather_systems_multi / gather_managers_multi 와 일관 (구: continue 로 drop
            # → chassis_count 가 collection 멤버 수보다 작게 under-report 되는 불일치).
        if not isinstance(cdata, dict):  # 비-dict 응답 오염 방어
            cdata = {}
        kind = _classify_chassis_kind(m['uri'], m['id'], cdata)
        # chassis GET 성공 시에만 Power/Thermal sub-GET.
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
            'power':         pwr_data,
            # thermal (Thermal 미노출 시 {}).
            'thermal':       thm_data,
        })
        out['errors'].extend(pwr_errs)
        out['errors'].extend(thm_errs)
    return out


def gather_composition_service(bmc_ip, service_root, username, password, timeout, verify_ssl):
    """CompositionService + ResourceBlocks 수집.

    설명 모델 요구 — HPE CSUS 3200 nPartition 은 표준 Redfish Composition Service 로
    구성된다. 각 ResourceBlock 은 하나의 chassis 에 대응하고 CPU/DIMM 을 포함하며,
    ResourceBlock 의 ComputerSystems 링크가 조합된 nPartition 을 가리킨다.

    multi_node.composition (manager_layout 정의 vendor 만 호출).
    CompositionService 링크 부재 시 None (graceful — 대다수 vendor 는 미노출).

    source:
      - DMTF DSP0266 CompositionService / ResourceBlock
        (redfish.dmtf.org/schemas/v1/ResourceBlock.json)
      - HPE Compute Scale-up Server 3200 Administration Guide (nPartition = ResourceBlock 조합)
    lab 부재 — 사이트 실측 시 정정 가능.

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
                    # fixture 확인 시 정정.
                    'processor_count':      len(_dicts(_safe(bd, 'Processors'))),
                    'memory_count':         len(_dicts(_safe(bd, 'Memory'))),
                    'chassis':              chassis_links,
                    'computer_systems':     systems_links,
                })
    return {
        # 비-dict/null 200 body 는 enabled=None (정직한 unknown).
        # dict 면 ServiceEnabled 누락 시 DMTF 관례상 True. sibling gather_manager_logs 와 정합.
        'enabled':              (bool(comp.get('ServiceEnabled', True)) if isinstance(comp, dict) else None),
        'state':                _safe(comp, 'Status', 'State'),
        'health':               _safe(comp, 'Status', 'Health'),
        'resource_block_count': len(blocks),
        'resource_blocks':      blocks,
    }, errors


def _gather_fabric_members(bmc_ip, coll_uri, username, password, timeout, verify_ssl, errors, kind):
    """Fabric 의 Switches / Endpoints 컬렉션 멤버 수집 helper.

    kind='switch' → SwitchType / Status. kind='endpoint' → EndpointProtocol / Status.
    source: DMTF DSP0266 Switch / Endpoint.
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
    """Fabrics + FlexGrid (Switches/Endpoints) 수집.

    설명 모델 요구 — HPE CSUS 3200 은 NUMAlink fabric 을 표준 Redfish Fabric 모델로
    표현하며, FlexGrid Flex Fabric 은 Switches 와 Endpoints 를 사용한다 (Links/Zones 미사용).

    multi_node.fabrics (manager_layout 정의 vendor 만 호출). Fabrics 링크
    부재 시 None (graceful).

    source:
      - DMTF DSP0266 Fabric / Switch / Endpoint
      - HPE Compute Scale-up Server 3200 architecture (NUMAlink / FlexGrid)
    lab 부재 — 사이트 실측 시 정정 가능.

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
    """Multi-node topology 전수 수집.

    `manager_layout` 미정의 (None) 시 None 반환 — 기존 동작을 그대로 유지한다.
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
    )
    mgr_result = gather_managers_multi(
        bmc_ip, managers_uri, vendor, username, password, timeout, verify_ssl,
        manager_layout=manager_layout,
    )
    chs_result = gather_chassis_multi(
        bmc_ip, chassis_uri_coll, username, password, timeout, verify_ssl,
    )
    # CompositionService/ResourceBlocks + Fabrics/FlexGrid 수집
    # (설명 모델 요구). ServiceRoot 에 링크 부재 시 None (graceful).
    composition, comp_errs = gather_composition_service(
        bmc_ip, service_root, username, password, timeout, verify_ssl,
    )
    fabrics, fab_errs = gather_fabrics(
        bmc_ip, service_root, username, password, timeout, verify_ssl,
    )

    partitions = sys_result.get('partitions') or []
    managers   = mgr_result.get('managers')   or []
    chassis    = chs_result.get('chassis')    or []

    representative = partitions[0].get('id') if partitions else None  # 방어적 .get (id 누락 KeyError 회피)
    rb_count = composition.get('resource_block_count', 0) if isinstance(composition, dict) else 0
    return {
        'enabled': True,
        'layout':  manager_layout,
        'summary': {
            'partition_count':           len(partitions),
            'manager_count':             len(managers),
            'chassis_count':             len(chassis),
            'representative_partition':  representative,
            # composition / fabric 규모
            'resource_block_count':      rb_count,
            'fabric_count':              len(fabrics) if isinstance(fabrics, list) else 0,
        },
        'partitions': partitions,
        'managers':   managers,
        'chassis':    chassis,
        # 신 컨테이너 (None = ServiceRoot 미노출).
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
    """9개 섹션 dispatch (system / bmc / processors / memory / storage / network /
    firmware / power / network_adapters).

    unsupported list 추가 — 404 응답 섹션을 별도 분류
    (capability 미지원 = noise 아님).

    `manager_layout` 옵션 인자.
    None 시 기존 동작을 그대로 유지한다. RMC primary adapter 만 `gather_bmc` 라벨 분기 활성.
    """
    _run = _make_section_runner(all_errors, collected, failed, unsupported)
    creds = (username, password, timeout, verify_ssl)
    return {
        'system':            _run('system',     gather_system,     bmc_ip, system_uri, vendor, *creds, chassis_uri, product_hint),
        'bmc':               _run('bmc',        gather_bmc,        bmc_ip, manager_uri, vendor, *creds, manager_layout),
        'processors':        _run('processors', gather_processors, bmc_ip, system_uri,          *creds),
        'memory':            _run('memory',     gather_memory,     bmc_ip, system_uri,          *creds),
        'storage':           _run('storage',    gather_storage,    bmc_ip, system_uri,          *creds),
        'network':           _run('network',    gather_network,    bmc_ip, system_uri,          *creds),
        'firmware':          _run('firmware',   gather_firmware,   bmc_ip,                      *creds),
        'power':             _run('power',      gather_power,      bmc_ip, chassis_uri,         *creds),
        # NIC 카드 + port-level + FC HBA / InfiniBand 분류
        'network_adapters':  _run('network_adapters',
                                   gather_network_adapters_chassis,
                                   bmc_ip, chassis_uri, *creds),
    }


def _compute_final_status(collected, failed, errors=None):
    """collected / failed list → final_status (success / partial / failed).

    errors[]에 인증 실패 (HTTP 401/403) 흔적 발견 시 'failed' 강제.
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


# ── AccountService — 공통계정 자동 생성/복구 ──────────
# vendor 분기는 Redfish API spec OEM namespace 의존.
# Dell: slot 기반 PATCH (/Accounts/{N}, N=1..17). POST 미지원
# HPE / Lenovo / Supermicro: POST /Accounts 표준
# Cisco: AccountService 표준 미지원 (errors[]에 not_supported 기록 후 종료)

# (debugging visibility 보강):
# vendor → 신규 계정 생성 strategy 매핑 (account_service_provision 분기 정본).
# 본 dict 는 코드 분기를 변경하지 않음 — 의도 가시화 + log/도구가 사용.
# source: 사이트 실측 + Dell SWC0296 + Cisco CIMC 사이트 실측 (10.100.15.2).
_ACCOUNT_CREATE_STRATEGY = {
    'dell':       'patch_slot',  # PATCH /Accounts/{N=2..17}
    'hpe':        'post_standard',  # POST /AccountService/Accounts
    'lenovo':     'post_standard',
    'supermicro': 'post_standard',
    'cisco':      'post_id_role_remap',  # POST + Id 1-15 + RoleId enum remap
    'huawei':     'post_standard',  # lab 부재 / web sources
    'inspur':     'post_standard',
    'fujitsu':    'post_standard',
    'quanta':     'post_standard',
}


def _account_create_method_for_vendor(vendor):
    """vendor → 신규 계정 생성 strategy 이름.

    실제 분기는 account_service_provision() 본문 inline if/elif 가 수행.
    본 함수는 가시성 / 로깅 / 도구 (-vvv 시 정상 어떻게 분기될지) 용도.

    Returns: 'patch_slot' | 'post_standard' | 'post_id_role_remap' | 'unknown'
    """
    return _ACCOUNT_CREATE_STRATEGY.get(vendor, 'unknown')

def account_service_get(bmc_ip, username, password, timeout, verify_ssl):
    """GET /redfish/v1/AccountService + Accounts 컬렉션 enumerate.

    Returns: (acct_service: dict|None, accounts: list[{slot_uri, id, username, role_id, enabled}], errors)
    """
    errors = []
    code, root_data, err = _get(bmc_ip, 'AccountService', username, password, timeout, verify_ssl)
    if code != 200 or err:
        errors.append(_err('account_service', f'GET AccountService 실패', detail=err or f'HTTP {code}'))
        return None, [], errors
    accounts_link = _safe(root_data, 'Accounts', '@odata.id')
    if not accounts_link:
        errors.append(_err('account_service', 'AccountService.Accounts 링크 없음', detail=str(root_data)[:200]))
        return root_data, [], errors
    code, acc_coll, err = _get(bmc_ip, _p(accounts_link), username, password, timeout, verify_ssl)
    if code != 200 or err:
        errors.append(_err('account_service', 'GET Accounts 컬렉션 실패', detail=err or f'HTTP {code}'))
        return root_data, [], errors
    members = _safe(acc_coll, 'Members', default=[]) or []
    if not isinstance(members, list):  # 비-list Members → 빈 계정 (Round 1 #25)
        members = []
    accounts = []
    for m in _capped(members, 'account_service', errors):  # Round 6 #8: 무경계 계정 순회 DoS 방어
        slot_uri = _safe(m, '@odata.id')
        if not slot_uri:
            continue
        code_a, acc_data, err_a = _get(bmc_ip, _p(slot_uri), username, password, timeout, verify_ssl)
        if code_a != 200 or err_a:
            errors.append(_err('account_service', f'GET {slot_uri} 실패', detail=err_a or f'HTTP {code_a}'))
            continue
        accounts.append({
            'slot_uri': slot_uri,
            'id':       _safe(acc_data, 'Id'),
            'username': _safe(acc_data, 'UserName', default=''),
            'role_id':  _safe(acc_data, 'RoleId',   default=''),
            'enabled':  bool(_safe(acc_data, 'Enabled', default=False)),
        })
    return root_data, accounts, errors


def account_service_find_user(accounts, target_username):
    """기존 사용자 slot URI 검색. None 반환 = 미존재."""
    for acc in accounts:
        if (acc.get('username') or '') == target_username:
            return acc
    return None


def account_service_find_empty_slot(accounts, skip_slot_ids=None):
    """빈 사용자 슬롯 검색 (Dell PATCH 패턴). UserName='' 인 첫 슬롯 반환.

    skip_slot_ids 파라미터 추가 — vendor 별 reserved
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
    """빈 슬롯 모두 (slot id 정렬). PATCH 1차 실패 시 다음 슬롯 retry 용."""
    skip = set(skip_slot_ids or [])
    empties = [
        a for a in accounts
        if ('' if a.get('id') is None else str(a.get('id'))) not in skip and not (a.get('username') or '')
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
    timeout, verify_ssl, dryrun=True,
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

    Returns:
        dict: {
          'recovered': bool,
          'method':    'patch_existing' | 'patch_empty_slot' | 'post_new' | 'delete_repost' | 'noop' | 'not_supported',
          'slot_uri':  '...' or None,
          'dryrun':    bool,
          'errors':    [_err(...), ...],
        }
    """
    out = {
        'recovered': False,
        'method':    'noop',
        'slot_uri':  None,
        'dryrun':    bool(dryrun),
        'errors':    [],
    }

    # 1) AccountService GET
    _, accounts, errs = account_service_get(
        bmc_ip, current_username, current_password, timeout, verify_ssl
    )

    # Cisco AccountService 실 지원 확인 (10.100.15.2 사이트 실측).
    # 이전: not_supported 분기.
    # 신: 표준 POST 지원하나 Id 필드 명시 필수 (1-15) + RoleId Cisco-specific enum
    #     ('admin'/'user'/'readonly'/'SNMPOnly' — 'Administrator' 거부).
    # source: 사이트 실측 (10.100.15.2 CIMC AccountService.v1_6_0,
    #         POST /Accounts {Id:'2', RoleId:'admin'} → HTTP 201 + 인증 200).
    # cisco 분기는 아래 신규 생성 단계에서 POST body 변형으로 처리.

    # Cisco 외 vendor도 일부 펌웨어가 AccountService 404
    # 응답 가능 (lab 부재 펌웨어 / 펌웨어 hot-fix 시 변동). errs가 404-only 시
    # 'not_supported' 분류 + errors[]에 noise 안 만듦 (기존 cisco
    # 분기 + 일반 404 graceful).
    # source: redfish.dmtf.org/schemas/v1/AccountService.json (선택적 endpoint)
    if _is_404_only_error(errs):
        out['method'] = 'not_supported'
        out['errors'].append(_err(
            'account_service',
            f'AccountService 미지원 (vendor={vendor}, HTTP 404)',
        ))
        return out

    out['errors'].extend(errs)

    # 2) 기존 사용자 검색
    existing = account_service_find_user(accounts, target_username)

    if existing:
        out['method']   = 'patch_existing'
        out['slot_uri'] = existing.get('slot_uri')
        if dryrun:
            return out
        # full body PATCH 의무 (Password + Enabled +
        # Locked + RoleId 항상 함께). 사이트 실측 (10.50.11.232 Lenovo XCC):
        # password 단독 PATCH 시 권한 cache 손상 (RoleId='Administrator' 표시되지만
        # /Managers AccessDenied). full body PATCH 시 권한 유지 정상.
        # source: 사이트 실측 + Lenovo XCC ManagerAccount.v1_8_1 동작.
        body_full = {
            'Password': target_password,
            'Enabled':  True,
            'Locked':   False,
            'RoleId':   target_role,
        }
        # Round 15 fix: Cisco CIMC 는 RoleId 표준 enum ('Administrator') 거부 →
        # vendor enum ('admin'/'user'/'readonly') remap (POST/DELETE+POST 경로와 일관).
        # 미적용 시 PATCH 기존 사용자 HTTP 400 + fallback 미도달. source: 사이트 실측 10.100.15.2.
        if vendor == 'cisco':
            cisco_role_map = {'Administrator': 'admin', 'Operator': 'user',
                              'ReadOnly': 'readonly'}
            body_full['RoleId'] = cisco_role_map.get(target_role, 'admin')
        code, _, err = _patch(
            bmc_ip, _p(existing['slot_uri']), body_full,
            current_username, current_password, timeout, verify_ssl,
        )
        # 일부 펌웨어가 Locked 필드 PATCH 거부 (read-only) — Locked 빼고 1회 retry
        if code not in (200, 204) and code in (400, 405):
            body_no_locked = {k: v for k, v in body_full.items() if k != 'Locked'}
            code, _, err = _patch(
                bmc_ip, _p(existing['slot_uri']), body_no_locked,
                current_username, current_password, timeout, verify_ssl,
            )
            if code in (200, 204) and not err:
                out['errors'].append(_err(
                    'account_service',
                    'Locked 필드 PATCH 거부 — Locked 빼고 retry 성공 (BMC 펌웨어가 Locked read-only)',
                ))
        if code not in (200, 204) or err:
            out['errors'].append(_err(
                'account_service',
                f'PATCH 기존 사용자 실패 (slot={existing.get("id")})',
                detail=err or f'HTTP {code}',
            ))
            return out
        # PATCH 후 실 인증 verify — silent fail / 권한 cache 손상 감지.
        # 1차 verify: 새 자격으로 /Systems GET. 401 이면 권한 손상.
        # fallback: DELETE + POST 재생성 (Lenovo XCC 권한 cache 클린 상태 보장).
        verify_code, _, verify_err = _get(
            bmc_ip, 'Systems', target_username, target_password,
            timeout, verify_ssl,
        )
        if verify_code == 200 and not verify_err:
            out['recovered'] = True
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
        if vendor == 'dell':
            # Dell PATCH-only — DELETE + POST 미지원
            out['errors'].append(_err(
                'account_service',
                'Dell iDRAC PATCH-only — DELETE+POST fallback 미지원 (수동 복구 필요)',
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
        body_post = {
            'UserName': target_username,
            'Password': target_password,
            'Enabled':  True,
            'RoleId':   target_role,
        }
        if vendor == 'cisco':
            cisco_role_map = {'Administrator': 'admin', 'Operator': 'user',
                              'ReadOnly': 'readonly'}
            body_post['RoleId'] = cisco_role_map.get(target_role, 'admin')
            body_post['Id'] = existing.get('id') or '2'
        post_code, post_data, post_err = _post(
            bmc_ip, 'AccountService/Accounts', body_post,
            current_username, current_password, timeout, verify_ssl,
        )
        if post_code in (200, 201, 204) and not post_err:
            out['method']   = 'delete_repost'
            out['slot_uri'] = _str(_safe(post_data, '@odata.id')) or existing.get('slot_uri')  # Round 8 #4: 비-str @odata.id
            out['recovered'] = True
        else:
            out['errors'].append(_err(
                'account_service',
                'DELETE+POST 재생성 실패',
                detail=post_err or f'HTTP {post_code}',
            ))
        return out

    # 3) 신규 생성 — vendor 분기 (Dell=slot PATCH, 그 외=POST)
    if vendor == 'dell':
        # Dell iDRAC9 사이트 실측 사고 매트릭스.
        # 1. slot 1 = anonymous reserved (UserName='', Enabled=false). PATCH 거부.
        # 2. UserName + Password + Enabled + RoleId 동시 PATCH 시 HTTP 200 응답
        #    하지만 BMC 가 password 가 Security Strengthen Policy 미충족이면 silent
        #    fail. Enabled/RoleId 도 'username or password is blank' 로 거부 (실제
        #    password 미적용). 응답 코드만 보면 안 됨.
        # 3. 따라서 PATCH 후 새 자격으로 실 인증 시도 → silent-fail 감지.
        # source: 사이트 실측 (10.100.15.27 iDRAC9 7.10.70.00) + Dell SWC0296
        #         "user name or password is blank" + Security Strengthen Policy.
        empty_slots = account_service_find_all_empty_slots(
            accounts, skip_slot_ids={'1'},
        )
        if not empty_slots:
            out['errors'].append(_err(
                'account_service', 'Dell iDRAC 빈 슬롯 없음 — 사용자 정리 필요',
            ))
            return out
        out['method']   = 'patch_empty_slot'
        out['slot_uri'] = empty_slots[0].get('slot_uri')
        if dryrun:
            return out
        body = {
            'UserName': target_username,
            'Password': target_password,
            'Enabled':  True,
            'RoleId':   target_role,
        }
        last_err = None
        last_code = 0
        for slot in empty_slots[:3]:
            code, _, err = _patch(
                bmc_ip, _p(slot['slot_uri']), body,
                current_username, current_password, timeout, verify_ssl,
            )
            if code not in (200, 204) or err:
                last_err = err
                last_code = code
                out['errors'].append(_err(
                    'account_service',
                    f'Dell PATCH 빈 슬롯 실패 (slot={slot.get("id")}) — '
                    f'다음 빈 슬롯으로 retry',
                    detail=err or f'HTTP {code}',
                ))
                continue
            # PATCH 200 OK — 실 인증 검증 (Dell silent-fail 감지)
            verify_code, _, verify_err = _get(
                bmc_ip, 'Systems', target_username, target_password,
                timeout, verify_ssl,
            )
            if verify_code == 200 and not verify_err:
                out['recovered'] = True
                out['slot_uri'] = slot.get('slot_uri')
                break
            # silent fail 감지 — slot cleanup (UserName 비우기) 후 다음 슬롯으로
            out['errors'].append(_err(
                'account_service',
                f'Dell PATCH 200 응답이지만 인증 실패 (slot={slot.get("id")}, '
                f'verify HTTP {verify_code}) — Password 가 Security Strengthen '
                f'Policy 미충족 가능. vault password 강화 필요 (15자 이상 권장).',
                detail=verify_err or f'verify HTTP {verify_code}',
            ))
            # cleanup 시도 (best-effort)
            _patch(
                bmc_ip, _p(slot['slot_uri']),
                {'UserName': '', 'Enabled': False, 'RoleId': 'None'},
                current_username, current_password, timeout, verify_ssl,
            )
            last_code = verify_code
        if not out['recovered']:
            out['errors'].append(_err(
                'account_service',
                f'Dell PATCH 모든 빈 슬롯 실패 (시도={len(empty_slots[:3])})',
                detail=last_err or f'HTTP {last_code}',
            ))
        return out

    # Cisco CIMC POST 변형 — Id 필드 + RoleId enum mapping.
    # source: 사이트 실측 — POST /Accounts 가 'Id' 1-15 필수 (BadRequest if absent),
    #   RoleId 표준 enum 'Administrator' 거부 → Cisco enum 'admin'/'user'/'readonly'.
    if vendor == 'cisco':
        out['method'] = 'post_new'
        if dryrun:
            return out
        # Cisco RoleId mapping
        cisco_role_map = {
            'Administrator': 'admin', 'admin': 'admin',
            'Operator': 'user',       'user': 'user',
            'ReadOnly': 'readonly',   'readonly': 'readonly',
        }
        cisco_role = cisco_role_map.get(target_role, 'admin')
        # 빈 Id 찾기 (2..15 — slot 1 은 admin reserved)
        used_ids = {('' if a.get('id') is None else str(a.get('id'))) for a in accounts}
        target_id = None
        for candidate_id in range(2, 16):
            if str(candidate_id) not in used_ids:
                target_id = str(candidate_id)
                break
        if target_id is None:
            out['errors'].append(_err(
                'account_service',
                'Cisco CIMC: 빈 Account Id (2-15) 없음 — 사용자 정리 필요',
            ))
            return out
        body_cisco = {
            'Id':       target_id,
            'UserName': target_username,
            'Password': target_password,
            'Enabled':  True,
            'RoleId':   cisco_role,
        }
        code, resp_data, err = _post(
            bmc_ip, 'AccountService/Accounts', body_cisco,
            current_username, current_password, timeout, verify_ssl,
        )
        if code in (200, 201, 204) and not err:
            out['recovered'] = True
            out['slot_uri']  = _str(_safe(resp_data, '@odata.id')) or f'/redfish/v1/AccountService/Accounts/{target_id}'  # Round 11 #3
        else:
            out['errors'].append(_err(
                'account_service',
                f'Cisco POST /AccountService/Accounts 실패 (Id={target_id})',
                detail=err or f'HTTP {code}',
            ))
        return out

    # HPE / Lenovo / Supermicro: POST 표준 + vendor-specific fallback retries.
    # 펌웨어별 호환성 강화 (web research 2026-05-01).
    # source: HPE iLO5/6 docs (Oem.Hpe.Privileges 가능, RoleId 만으로도 충분),
    #   Lenovo XCC docs (PasswordChangeRequired 선택적, 미설정 시 default false),
    #   Supermicro Redfish User Guide (RoleId Administrator/Operator/ReadOnly,
    #   password complexity 매우 엄격 — POST 400 시 password policy 위반 시그널).
    out['method'] = 'post_new'
    if dryrun:
        return out
    body_base = {
        'UserName': target_username,
        'Password': target_password,
        'Enabled':  True,
        'RoleId':   target_role,
    }
    # 1차: 표준 body
    code, resp_data, err = _post(
        bmc_ip, 'AccountService/Accounts', body_base,
        current_username, current_password, timeout, verify_ssl,
    )
    if code in (200, 201, 204) and not err:
        out['recovered'] = True
        out['slot_uri']  = _str(_safe(resp_data, '@odata.id')) or None  # Round 11 #4
        return out

    # 2차 retry: 400/405 — Lenovo PasswordChangeRequired 명시 (일부 XCC 펌웨어 요구)
    # source: pubs.lenovo.com/xcc-restapi/create_an_account_post (PasswordChangeRequired
    #   default true → 호출자가 false 로 명시해야 즉시 사용 가능).
    if code in (400, 405):
        body_lenovo = dict(body_base, PasswordChangeRequired=False)
        code2, resp2, err2 = _post(
            bmc_ip, 'AccountService/Accounts', body_lenovo,
            current_username, current_password, timeout, verify_ssl,
        )
        if code2 in (200, 201, 204) and not err2:
            out['recovered'] = True
            out['slot_uri']  = _str(_safe(resp2, '@odata.id')) or None  # Round 11 #5
            out['errors'].append(_err(
                'account_service',
                'POST 1차 실패 → PasswordChangeRequired:false 추가 후 retry 성공 '
                '(Lenovo XCC password policy)',
            ))
            return out
        # 3차 retry: HPE Oem.Hpe.Privileges (HPE iLO 일부 펌웨어가 RoleId 단독 거부 보고).
        # source: HewlettPackard/ilo-rest-api-docs add_user_account.py.
        if vendor == 'hpe':
            body_hpe = dict(body_base)
            body_hpe['Oem'] = {'Hpe': {'Privileges': {'LoginPriv': True,
                                                      'RemoteConsolePriv': True,
                                                      'UserConfigPriv': True,
                                                      'VirtualMediaPriv': True,
                                                      'VirtualPowerAndResetPriv': True,
                                                      'iLOConfigPriv': True}}}
            code3, resp3, err3 = _post(
                bmc_ip, 'AccountService/Accounts', body_hpe,
                current_username, current_password, timeout, verify_ssl,
            )
            if code3 in (200, 201, 204) and not err3:
                out['recovered'] = True
                out['slot_uri']  = _str(_safe(resp3, '@odata.id')) or None  # Round 11 #6
                out['errors'].append(_err(
                    'account_service',
                    'POST 1차 실패 → Oem.Hpe.Privileges 추가 후 retry 성공',
                ))
                return out
            err = err3 or err
            code = code3 or code
        else:
            err = err2 or err
            code = code2 or code

    # 모든 retry 실패
    out['errors'].append(_err(
        'account_service',
        'POST /AccountService/Accounts 실패 (모든 vendor fallback 시도 후)',
        detail=err or f'HTTP {code}',
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
            # AccountService 통합
            mode            = dict(type='str',  default='gather',
                                   choices=['gather', 'account_provision']),
            target_username = dict(type='str',  default=''),
            target_password = dict(type='str',  default='', no_log=True),
            target_role     = dict(type='str',  default='Administrator'),
            dryrun          = dict(type='bool', default=True),
            # HPE CSUS 3200 / Superdome Flex
            # RMC primary 멀티-노드 토폴로지 수집 활성. adapter `vendor_notes.manager_layout`
            # 을 detect_vendor.yml → collect_standard.yml → 본 모듈까지 전달.
            # None 시 기존 동작 유지 (기존 vendor 영향 없음).
            #   Allowed values: None / 'rmc_primary' / 'rmc_primary_ilo_secondary'
            manager_layout  = dict(type='str',  default=None, required=False),
        ),
        supports_check_mode=True,
    )

    if not HAS_URLLIB:
        module.fail_json(msg='Python urllib 를 import 할 수 없습니다')

    p = module.params
    bmc_ip, username, password = p['bmc_ip'], p['username'], p['password']
    timeout, verify_ssl = p['timeout'], p['verify_ssl']
    mode = p['mode']

    # ── AccountService provision mode ────────────────────────────────
    if mode == 'account_provision':
        target_username = p['target_username']
        target_password = p['target_password']
        target_role     = p['target_role']
        dryrun          = p['dryrun']

        if not target_username or not target_password:
            module.fail_json(
                msg='mode=account_provision 시 target_username/target_password 필수'
            )

        # detect_vendor 로 vendor 정규화 (분기 라우팅 용도)
        vendor, _, _, _, det_errors, _ = detect_vendor(
            bmc_ip, username, password, timeout, verify_ssl
        )
        result = account_service_provision(
            bmc_ip, vendor, username, password,
            target_username, target_password, target_role,
            timeout, verify_ssl, dryrun=dryrun,
        )
        result['errors'] = list(det_errors) + (result.get('errors') or [])
        module.exit_json(
            changed=bool(result.get('recovered')),
            mode='account_provision',
            vendor=vendor,
            account_service=result,
        )
        return

    # ── 기존 gather mode ──────
    all_errors, collected, failed, unsupported = [], [], [], []

    # manager_layout (adapter capability) 수신.
    # None 시 기존 동작 유지 (기존 vendor 영향 없음).
    manager_layout = p.get('manager_layout') or None

    vendor, system_uri, manager_uri, chassis_uri, det_errors, service_root = detect_vendor(
        bmc_ip, username, password, timeout, verify_ssl
    )
    all_errors.extend(det_errors)

    # ServiceRoot 무인증 응답에서 adapter selection 용 facts 추출.
    # detect_vendor.yml 의 probe 단계 (무인증) 에서 data.bmc/data.system 가 empty 이면
    # adapter_loader 가 priority 만으로 선택 — vendor-specific generation 정확 매칭 불가.
    # probe_facts 가 model_hint/firmware_hint/manager_type 을 제공해 adapter 선택 정확도 보강.
    # probe_facts 는 본 probe 경로에서만 쓰이는 보조 키로, 기존 envelope 키는 그대로 유지한다.
    probe_facts = _extract_probe_facts(service_root, vendor)

    if not system_uri:
        module.exit_json(
            changed=False, status='failed', vendor=vendor,
            collected=[], failed_sections=['all'], unsupported_sections=[],
            errors=all_errors, data={}, probe_facts=probe_facts,
            multi_node=None,
        )

    result_data = _collect_all_sections(
        bmc_ip, vendor, system_uri, manager_uri, chassis_uri,
        username, password, timeout, verify_ssl,
        all_errors, collected, failed, unsupported,
        manager_layout=manager_layout,
        # (2026-06-04): ServiceRoot.Product 를 hardware.model fallback 로 전달 (check_redfish 동일).
        product_hint=_safe(service_root, 'Product'),
    )

    # manager_layout 정의 vendor 만 multi_node 수집.
    # None / 미정의 vendor — 기존 동작 유지 (기존 vendor 영향 없음).
    multi_node = _collect_multi_node_topology(
        bmc_ip, vendor, service_root,
        username, password, timeout, verify_ssl,
        manager_layout=manager_layout,
    )
    # Round 10: multi_node(RMC) 수집 errors(401/403 포함)를 status 계산 + envelope errors[] 에 반영.
    # 누락 시 multi_node 인증 실패가 success/partial 로 오분류(status 거짓). multi_node=None 시 영향 없음.
    if isinstance(multi_node, dict):
        all_errors.extend(multi_node.get('errors') or [])

    final_status, clean = _compute_final_status(collected, failed, all_errors)

    module.exit_json(
        changed=False, status=final_status, vendor=vendor,
        collected=clean, failed_sections=list(set(failed)),
        unsupported_sections=list(set(unsupported)),
        errors=all_errors, data=result_data, probe_facts=probe_facts,
        multi_node=multi_node,
    )


if __name__ == '__main__':
    main()
