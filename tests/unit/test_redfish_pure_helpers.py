"""redfish_gather.py 순수 헬퍼 특성화 테스트.

외부 계약 robustness 함수들 — 펌웨어 응답 변형(non-numeric capacity,
trailing space, 0x-prefixed JEDEC, 중첩 dict 부재 등)에 모듈이 죽지 않도록 방어하는
순수 함수. 직접 단위 테스트가 없어(0 커버) 본 파일에서 현재 동작을 고정한다.

대상: _safe / _safe_int / _removeprefix / _strip_or_none / _canonical_vendor_name
      / _normalize_jedec  (모두 stdlib-only, 부수효과 없음)

NOTE: filter-side `jedec_mapper.jedec_to_vendor` 는 test_jedec_mapper.py 가 커버.
본 파일은 **redfish-side** 별도 구현(`_normalize_jedec`)을 검증 — 입력 수용 경계가
filter-side 와 다르다(예: bare '2C' 를 redfish 는 해석, filter 는 raw 반환).
두 테이블 값 정합은 test_jedec_drift_guard.py 가 보장.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load_redfish_module():
    if "ansible.module_utils.basic" not in sys.modules:
        mock_basic = types.ModuleType("ansible.module_utils.basic")
        mock_basic.AnsibleModule = type("AnsibleModule", (), {})
        sys.modules.setdefault("ansible", types.ModuleType("ansible"))
        sys.modules.setdefault("ansible.module_utils", types.ModuleType("ansible.module_utils"))
        sys.modules["ansible.module_utils.basic"] = mock_basic
    src = REPO / "redfish-gather" / "library" / "redfish_gather.py"
    spec = importlib.util.spec_from_file_location("redfish_gather_pure_helpers", str(src))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rfg():
    return _load_redfish_module()


# ── _safe (중첩 dict 안전 getter) ─────────────────────────────────────────────

def test_safe_nested_hit(rfg):
    assert rfg._safe({"a": {"b": {"c": 1}}}, "a", "b", "c") == 1


def test_safe_single_key(rfg):
    assert rfg._safe({"a": 1}, "a") == 1
    assert rfg._safe({"a": {"b": 1}}, "a") == {"b": 1}


def test_safe_missing_key_default(rfg):
    assert rfg._safe({"a": 1}, "x") is None
    assert rfg._safe({"a": 1}, "x", default=0) == 0


def test_safe_non_dict_short_circuits(rfg):
    assert rfg._safe(None, "a") is None
    assert rfg._safe("notadict", "a") is None
    assert rfg._safe(123, "a", default="d") == "d"


def test_safe_none_value_treated_as_missing(rfg):
    assert rfg._safe({"a": None}, "a") is None
    assert rfg._safe({"a": {"b": None}}, "a", "b", default="x") == "x"


# ── _safe_int (firmware drift ValueError 가드) ───────────────────────

def test_safe_int_numeric(rfg):
    assert rfg._safe_int("5") == 5
    assert rfg._safe_int(5) == 5
    assert rfg._safe_int(5.9) == 5  # int() truncates


def test_safe_int_non_numeric_returns_default(rfg):
    assert rfg._safe_int("abc") is None
    assert rfg._safe_int(None) is None
    assert rfg._safe_int("3.5") is None  # int('3.5') raises ValueError → default
    assert rfg._safe_int("") is None


def test_safe_int_custom_default(rfg):
    assert rfg._safe_int("abc", default=0) == 0
    assert rfg._safe_int("42", default=0) == 42


# ── _removeprefix (Python 3.8 이하 호환) ──────────────────────────────────────

def test_removeprefix_strips(rfg):
    assert rfg._removeprefix("redfish/v1/Systems", "redfish/v1/") == "Systems"


def test_removeprefix_no_match_unchanged(rfg):
    assert rfg._removeprefix("abc", "xyz") == "abc"
    assert rfg._removeprefix("", "x") == ""


# ── _strip_or_none (Cisco trailing space, non-str passthrough) ────────────────

def test_strip_or_none_trims(rfg):
    assert rfg._strip_or_none("M386A8K40BM1-CRC    ") == "M386A8K40BM1-CRC"
    assert rfg._strip_or_none("  abc  ") == "abc"


def test_strip_or_none_empty_becomes_none(rfg):
    assert rfg._strip_or_none("") is None
    assert rfg._strip_or_none("   ") is None


def test_strip_or_none_non_string_passthrough(rfg):
    assert rfg._strip_or_none(None) is None
    assert rfg._strip_or_none(123) == 123
    assert rfg._strip_or_none(["x"]) == ["x"]


# ── _canonical_vendor_name (cross-vendor 이름 정규화) ─────────────────────────

def test_canonical_vendor_name_normalizes_variants(rfg):
    assert rfg._canonical_vendor_name("Hynix Semiconductor") == "SK hynix"
    assert rfg._canonical_vendor_name("hynix") == "SK hynix"
    assert rfg._canonical_vendor_name("Samsung Electronics") == "Samsung"
    assert rfg._canonical_vendor_name("Micron") == "Micron Technology"


def test_canonical_vendor_name_passthrough_and_guards(rfg):
    assert rfg._canonical_vendor_name("Samsung") == "Samsung"  # 이미 canonical
    assert rfg._canonical_vendor_name(None) is None
    assert rfg._canonical_vendor_name("") == ""  # falsy → 그대로 반환


# ── _normalize_jedec (redfish-side JEDEC ID 해석) ─────────────────────────────

def test_normalize_jedec_prefixed_hex(rfg):
    assert rfg._normalize_jedec("0xCE00") == "Samsung"
    assert rfg._normalize_jedec("0xAD") == "SK hynix"


def test_normalize_jedec_plain_hex_with_bank(rfg):
    # dmidecode raw: 앞 바이트(continuation)=00, 다음 바이트=ID
    assert rfg._normalize_jedec("00AD063200AD") == "SK hynix"


def test_normalize_jedec_bare_two_char(rfg):
    # redfish-side 는 bare 2자리도 해석 (filter-side 와의 수용 경계 차이)
    assert rfg._normalize_jedec("2C") == "Micron Technology"


def test_normalize_jedec_vendor_name_passthrough(rfg):
    assert rfg._normalize_jedec("Samsung") == "Samsung"
    assert rfg._normalize_jedec("Hynix Semiconductor") == "SK hynix"


def test_normalize_jedec_unknown_hex_kept_raw(rfg):
    # 미지의 ID 는 추적성 위해 raw 보존
    assert rfg._normalize_jedec("0xFF00") == "0xFF00"


def test_normalize_jedec_sentinels_to_none(rfg):
    for v in (None, "", "Unknown", "Not Specified", "none"):
        assert rfg._normalize_jedec(v) is None


# ── _normalize_link_status (DMTF Port.LinkStatus enum 정규화) ──────────────────
# DMTF DSP8010 2026.1 대조 2026-06-08: Port.LinkStatus enum 정본 =
#   ['LinkUp', 'Starting', 'Training', 'LinkDown', 'NoLink'] (Port.v1_19_0).
# vendor 변형 + 표준 전이 상태를 up/down/unknown 3-값으로 정규화.

def test_normalize_link_status_up_variants(rfg):
    for v in ("LinkUp", "Up", "Connected", "Enabled", "Active"):
        assert rfg._normalize_link_status(v) == "up"


def test_normalize_link_status_down_variants(rfg):
    for v in ("LinkDown", "Down", "NoLink", "Disconnected", "Disabled",
              "Inactive", "Offline"):
        assert rfg._normalize_link_status(v) == "down"


def test_normalize_link_status_dmtf_transitional_to_down(rfg):
    # DSP8010 2026.1 대조: 표준 전이 상태(Starting/Training)는 비작동 → 'down'.
    # 기존 disabled/inactive/offline 매핑과 일관. (gap fix)
    assert rfg._normalize_link_status("Starting") == "down"
    assert rfg._normalize_link_status("Training") == "down"


def test_normalize_link_status_unknown(rfg):
    for v in (None, "", "none", "unknown", "null"):
        assert rfg._normalize_link_status(v) == "unknown"


def test_normalize_link_status_unknown_vendor_value_preserved(rfg):
    # 매트릭스에 없는 vendor-specific 값은 추적성 위해 raw(lowercase) 보존
    assert rfg._normalize_link_status("WeirdState") == "weirdstate"


# ── _normalize_port_speed ──────────────────────────────────────
# 신 Port resource(1.6+, Ports)는 CurrentSpeedGbps 만, 구 NetworkPort 는
# CurrentLinkSpeedMbps 만 준다. Mbps 미제공 시 Gbps 에서 역산해야 유실 없음.
def test_port_speed_ports_only_gbps_derives_mbps(rfg):
    """신 Ports-only 어댑터(HPE): CurrentSpeedGbps=10, Mbps 없음 → mbps 10000 역산."""
    gbps, mbps = rfg._normalize_port_speed({"CurrentSpeedGbps": 10})
    assert mbps == 10000          # 가드 전: None (유실)
    assert gbps == 10


def test_port_speed_numeric_string_gbps(rfg):
    """숫자-문자열 Gbps('25') 흡수 → gbps/mbps 둘 다 보존 (가드 전: 둘 다 유실)."""
    gbps, mbps = rfg._normalize_port_speed({"CurrentSpeedGbps": "25"})
    assert mbps == 25000
    assert gbps == 25


def test_port_speed_legacy_mbps_only_preserved(rfg):
    """구 NetworkPort: CurrentLinkSpeedMbps=10000 만 → 기존 동작 불변."""
    gbps, mbps = rfg._normalize_port_speed({"CurrentLinkSpeedMbps": 10000})
    assert mbps == 10000
    assert gbps == 10.0


def test_port_speed_both_present_gbps_wins(rfg):
    """둘 다 있으면 Gbps 우선(기존), Mbps 는 보고된 값 유지."""
    gbps, mbps = rfg._normalize_port_speed({"CurrentSpeedGbps": 10, "CurrentLinkSpeedMbps": 10000})
    assert gbps == 10
    assert mbps == 10000


def test_port_speed_none_when_absent(rfg):
    """속도 필드 전무 → (None, None) (link-down/구 펌웨어)."""
    assert rfg._normalize_port_speed({}) == (None, None)


def test_port_speed_bool_gbps_ignored(rfg):
    """CurrentSpeedGbps 가 JSON true(오염) → int(True)=1 오역산 방지, Mbps 폴백."""
    gbps, mbps = rfg._normalize_port_speed({"CurrentSpeedGbps": True, "CurrentLinkSpeedMbps": 1000})
    assert mbps == 1000
    assert gbps == 1.0   # Mbps(1000)/1000 — bool Gbps 는 무시


def test_port_speed_zero_gbps_no_phantom_mbps(rfg):
    """CurrentSpeedGbps=0(link down) → mbps 0 역산 안 함(기존 동작 보존: gbps=0, mbps=None)."""
    gbps, mbps = rfg._normalize_port_speed({"CurrentSpeedGbps": 0})
    assert gbps == 0
    assert mbps is None


# ── _get / _get_noauth 성공-path decode guard ──
class _FakeResp:
    def __init__(self, status, body):
        self.status = status
        self._body = body
    def read(self):
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def test_get_empty_body_tolerant_but_nonjson_errs(rfg, monkeypatch):
    """200+유효JSON→(200,data,None); 200+빈body→(200,{},None) tolerant;
    200+비-JSON→(200,{},err) — detect 경로에서 malformed 를 명확히 실패로."""
    box = {"status": 200, "body": b""}

    def fake_urlopen(req, context=None, timeout=None):
        return _FakeResp(box["status"], box["body"])
    monkeypatch.setattr(rfg.urlreq, "urlopen", fake_urlopen)

    box.update(status=200, body=b'{"a": 1}')
    assert rfg._get("1.1.1.1", "x", "u", "p", 5, False) == (200, {"a": 1}, None)

    box.update(status=200, body=b"")
    st, data, err = rfg._get("1.1.1.1", "x", "u", "p", 5, False)
    assert st == 200 and data == {} and err is None        # 빈 body tolerant (가드 전: status 0)

    box.update(status=200, body=b"<html>oops</html>")
    st, data, err = rfg._get("1.1.1.1", "x", "u", "p", 5, False)
    assert st == 200 and data == {} and err is not None     # 비-JSON: status 보존 + err

    # _get_noauth 동일 계약
    box.update(status=200, body=b"")
    st, data, err = rfg._get_noauth("1.1.1.1", "x", 5, False)
    assert st == 200 and data == {} and err is None


def test_port_speed_infinity_nan_no_crash(rfg):
    """회귀: JSON Infinity/NaN(json.loads 기본 허용) Gbps → int() OverflowError/ValueError
    로 network_adapters 섹션 전체 drop 되던 것 → _safe_int 경유로 (None,None) graceful."""
    assert rfg._normalize_port_speed({"CurrentSpeedGbps": float("inf")}) == (None, None)
    assert rfg._normalize_port_speed({"CurrentSpeedGbps": float("-inf")}) == (None, None)
    gbps, mbps = rfg._normalize_port_speed({"CurrentSpeedGbps": float("nan")})
    assert gbps is None and mbps is None
    # inf Gbps + 정상 Mbps → Gbps 무시, Mbps 보존
    g2, m2 = rfg._normalize_port_speed({"CurrentSpeedGbps": float("inf"), "CurrentLinkSpeedMbps": 10000})
    assert m2 == 10000 and g2 == 10.0


def test_port_speed_fractional_gbps_preserved(rfg):
    """회귀: fractional CurrentSpeedGbps(2.5GbE 등)가 _safe_int truncate(2.5→2)되던 것 →
    _safe_num 으로 float 보존. mbps 는 round 로 정확(2500)."""
    gbps, mbps = rfg._normalize_port_speed({"CurrentSpeedGbps": 2.5})
    assert gbps == 2.5          # 가드 전(_safe_int): 2 (손상)
    assert mbps == 2500         # 가드 전: 2000 (off by 500)
    # 정수형 Gbps 불변
    assert rfg._normalize_port_speed({"CurrentSpeedGbps": 25.0}) == (25.0, 25000)
    assert rfg._normalize_port_speed({"CurrentSpeedGbps": 10}) == (10, 10000)
    # 5GbE 소수
    g5, m5 = rfg._normalize_port_speed({"CurrentSpeedGbps": 5.0})
    assert (g5, m5) == (5.0, 5000)


def test_safe_num_helper(rfg):
    """_safe_num: int→int, 유한 float→float 보존, bool/None/비숫자/inf/nan→None."""
    assert rfg._safe_num(10) == 10 and isinstance(rfg._safe_num(10), int)
    assert rfg._safe_num(2.5) == 2.5
    assert rfg._safe_num("25") == 25.0
    assert rfg._safe_num(True) is None
    assert rfg._safe_num(None) is None
    assert rfg._safe_num("x") is None
    assert rfg._safe_num(float("inf")) is None
    assert rfg._safe_num(float("nan")) is None
