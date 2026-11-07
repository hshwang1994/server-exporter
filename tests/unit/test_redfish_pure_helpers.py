"""redfish_gather.py 순수 헬퍼 특성화 테스트 (cycle 2026-06-04).

외부 계약(rule 96) robustness 함수들 — 펌웨어 응답 변형(non-numeric capacity,
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


# ── _safe_int (firmware drift ValueError 가드, rule 96) ───────────────────────

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
# 2026-10-29 (SA-09, 사용자 의견): Starting · Training(전이 상태) · Enabled · Active(State 값) · 미인식 값은 unknown — 원문은 notice 로.

def test_normalize_link_status_up_variants(rfg):
    for v in ("LinkUp", "Up", "Connected", " linkup ", "LINKUP"):
        assert rfg._normalize_link_status(v) == "up"


def test_normalize_link_status_state_values_are_not_links(rfg):
    # Enabled · Active 는 Status.State 값이지 링크 값이 아니다 — up 으로 보지 않는다 (종전 up)
    for v in ("Enabled", "Active", " ACTIVE "):
        assert rfg._normalize_link_status(v) == "unknown", v
        assert rfg._link_status_unmapped(v) == v.strip(), v


def test_normalize_link_status_down_variants(rfg):
    for v in ("LinkDown", "Down", "NoLink", "Disconnected", "Disabled",
              "Inactive", "Offline"):
        assert rfg._normalize_link_status(v) == "down"


def test_normalize_link_status_dmtf_transitional_to_unknown(rfg):
    # DMTF Port.LinkStatus · NetworkPort.LinkStatus 의 Starting · Training 은 링크를 협상하는 전이 상태 — 링크가 아직 정해지지 않았다.
    # 종전(2026-06-08) 'down' 매핑을 2026-10-29 (SA-09) 'unknown' 으로 바꿨다 — storage.infiniband 와 같은 값.
    # storage.hbas 는 종전처럼 down 이다 (아래 test_hba_* — HBA up/down 정책 불변).
    for v in ("Starting", "Training", " training "):
        assert rfg._normalize_link_status(v) == "unknown", v
        assert rfg._normalize_ib_link_status(v) == "unknown", v
        assert rfg._link_status_unmapped(v) == v.strip(), v


def test_normalize_link_status_unknown(rfg):
    for v in (None, "", "none", "unknown", "null"):
        assert rfg._normalize_link_status(v) == "unknown"


def test_normalize_link_status_unknown_vendor_value_is_unknown_and_raw_goes_to_notice(rfg):
    # 2026-10-29 (SA-09): 매트릭스 밖 값은 원문(소문자)을 값으로 내보내지 않는다(종전 'weirdstate') — 값은 unknown 이고
    # 원문은 호출부가 섹션당 notice 1건으로 남긴다(_link_status_unmapped).
    assert rfg._normalize_link_status("WeirdState") == "unknown"
    assert rfg._link_status_unmapped(" WeirdState ") == "WeirdState"
    assert rfg._link_status_unmapped(123) == "123"


def test_link_status_unmapped_is_none_for_empty_and_mapped_values(rfg):
    for v in (None, "", " ", "none", "Unknown", "null", "LinkUp", "Up", "Connected", "LinkDown", "Down", "NoLink",
              "Disconnected", "Disabled", "Inactive", "Offline"):
        assert rfg._link_status_unmapped(v) is None, v


# ── _hba_link_status / _hba_link_missing / _hba_link_unresolved (2026-10-19: storage.hbas[].link_status 는 up/down 둘뿐) ──
# 2026-10-28 사용자 결정: up 은 표준 링크 값(LinkUp · Up · Connected)뿐이다. 네트워크 정규화가 up 으로 보는 Enabled · Active 는
#   HBA 에서 down + '값 미확정' notice 다(표준 Port.LinkStatus 에서 링크 의미 불명). 종전 이 시험은 enabled · active 를 up 으로 고정했다.
def test_hba_link_status_is_up_only_for_an_active_link(rfg):
    for v in ("LinkUp", "Up", "Connected", " linkup ", "LINKUP", "up"):
        assert rfg._hba_link_status({"LinkStatus": v}) == "up", v


def test_hba_link_status_everything_else_is_down(rfg):
    for pdata in ({"LinkStatus": "LinkDown"}, {"LinkStatus": "NoLink"}, {"LinkStatus": "Starting"}, {"LinkStatus": "Training"},
                  {"LinkStatus": None}, {"LinkStatus": "Unknown"}, {"LinkStatus": "WeirdState"}, {"Id": "1"}, {}, None,
                  {"LinkStatus": "Down"}, {"LinkStatus": "Disconnected"}, {"LinkStatus": "Degraded"}, {"LinkStatus": ""},
                  {"LinkStatus": 123}, {"LinkStatus": True}, {"LinkStatus": "Link Up"}, {"LinkStatus": ["LinkUp"]}):
        assert rfg._hba_link_status(pdata) == "down", pdata


def test_hba_link_status_enabled_and_active_are_down_not_up(rfg):
    """2026-10-28 사용자 결정 — Enabled · Active 는 HBA 에서 down. 네트워크 정규화는 2026-10-29 (SA-09) 부터 unknown 이다(종전 up —
    정책을 섞지 않는다)."""
    for v in ("Enabled", "enabled", "Active", " ACTIVE "):
        assert rfg._hba_link_status({"LinkStatus": v}) == "down", v
        assert rfg._normalize_link_status(v) == "unknown", v


def test_hba_down_values_are_frozen_to_the_2026_10_28_list(rfg):
    """2026-10-29 (SA-09): 일반 NIC · 포트가 Starting · Training 을 unknown 으로 바꿔도 HBA 는 종전 down 목록 그대로다."""
    assert rfg._HBA_LINK_DOWN_VALUES == frozenset(("linkdown", "down", "nolink", "disconnected", "disabled", "inactive", "offline",
                                                    "starting", "training"))
    assert rfg._HBA_LINK_DOWN_VALUES - rfg._LINK_DOWN_VALUES == {"starting", "training"}


def test_hba_up_values_are_standard_link_values_and_a_subset_of_the_network_up_set(rfg):
    assert rfg._HBA_LINK_UP_VALUES == frozenset(("linkup", "up", "connected"))
    for v in rfg._HBA_LINK_UP_VALUES:
        assert rfg._normalize_link_status(v) == "up", v
    assert not {"enabled", "active"} & rfg._HBA_LINK_UP_VALUES


@pytest.mark.parametrize("raw", ["LinkUp", "Up", "Connected", "LinkDown", "Down", "NoLink", "Disconnected", "Disabled", "Starting",
                                 "Training", "Enabled", "Active", "Degraded", "Unknown", "", None, 123, "Link Up", "<absent>"])
def test_hba_every_down_says_why(rfg, raw):
    """값은 up/down 둘뿐이고, down 은 셋 중 정확히 하나로 설명된다 — 장비가 down 이라 함 · 키 없음(notice) · 값 미확정(notice).

    up 이면 notice 가 없다. 어떤 값도 근거 없이 조용히 down 이 되지 않는다.
    '장비가 down 이라 함' 은 HBA 전용 down 집합(_HBA_LINK_DOWN_VALUES) 기준이다 — 2026-10-29 (SA-09) 에 일반 정규화가 Starting · Training 을
    unknown 으로 바꾼 뒤에도 HBA 는 그 둘을 down(notice 없음)으로 둔다.
    """
    pdata = {"Id": "1"} if raw == "<absent>" else {"LinkStatus": raw}
    link = rfg._hba_link_status(pdata)
    assert link in ("up", "down")
    missing = rfg._hba_link_missing(pdata)
    unresolved = rfg._hba_link_unresolved(pdata)
    raw_v = pdata.get("LinkStatus")
    said_down = (not missing) and raw_v is not None and str(raw_v).strip().lower() in rfg._HBA_LINK_DOWN_VALUES
    if link == "up":
        assert not missing and unresolved is None and not said_down
    else:
        assert [said_down, missing, unresolved is not None].count(True) == 1, (raw, said_down, missing, unresolved)


def test_hba_link_missing_is_key_absence_only(rfg):
    assert rfg._hba_link_missing({"Id": "1"}) is True and rfg._hba_link_missing(None) is True
    assert rfg._hba_link_missing({"LinkStatus": None}) is False and rfg._hba_link_missing({"LinkStatus": "Unknown"}) is False


def test_hba_link_unresolved_returns_the_raw_value_only_when_not_up_or_down(rfg):
    assert rfg._hba_link_unresolved({"LinkStatus": None}) == "null"
    assert rfg._hba_link_unresolved({"LinkStatus": "Unknown"}) == "Unknown"
    assert rfg._hba_link_unresolved({"LinkStatus": " WeirdState "}) == "WeirdState"
    for pdata in ({"LinkStatus": "LinkUp"}, {"LinkStatus": "LinkDown"}, {"LinkStatus": "Training"}, {"Id": "1"}, None):
        assert rfg._hba_link_unresolved(pdata) is None, pdata
    # 2026-10-28: 추가 사례 — 원문 표기를 그대로(앞뒤 공백만 제거) 남긴다. 비문자열은 문자열로.
    assert rfg._hba_link_unresolved({"LinkStatus": "Degraded"}) == "Degraded"
    assert rfg._hba_link_unresolved({"LinkStatus": "Link Up"}) == "Link Up"
    assert rfg._hba_link_unresolved({"LinkStatus": ""}) == ""
    assert rfg._hba_link_unresolved({"LinkStatus": 123}) == "123"
    for pdata in ({"LinkStatus": "Up"}, {"LinkStatus": "Connected"}, {"LinkStatus": "Down"}, {"LinkStatus": "NoLink"},
                  {"LinkStatus": "Disconnected"}, {"LinkStatus": "Starting"}, {}):
        assert rfg._hba_link_unresolved(pdata) is None, pdata


def test_hba_link_unresolved_reports_enabled_and_active_as_undetermined(rfg):
    """2026-10-28 사용자 결정 — Enabled · Active 는 값 down + `링크 상태 값 미확정` notice(원문 표기)."""
    assert rfg._hba_link_unresolved({"LinkStatus": "Enabled"}) == "Enabled"
    assert rfg._hba_link_unresolved({"LinkStatus": " active "}) == "active"
    assert rfg._hba_link_missing({"LinkStatus": "Enabled"}) is False


# ── _normalize_port_speed (Round 17 #3) ──────────────────────────────────────
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


def test_port_speed_zero_gbps_unlinked_is_none(rfg):
    """CurrentSpeedGbps=0(link down) → (None, None). SCHEMA-02(2026-06-15 HPE DL380):
    0 은 '0Gbps 협상'이 아니라 '링크 없음' → gbps 도 None 으로 정규화해야 field_dictionary
    (hbas link_speed_gbps 'null when unlinked') 계약 + 동일 포트 mbps(None)와 일관. mbps 도 0
    역산 안 함(phantom mbps 방지 — 기존 의도 보존)."""
    gbps, mbps = rfg._normalize_port_speed({"CurrentSpeedGbps": 0})
    assert gbps is None   # SCHEMA-02 수정 전: 0 (계약 위반 + mbps=None 과 내부모순)
    assert mbps is None


# ── _get / _get_noauth 성공-path decode guard (Round 17 #18 + R18 refinement) ──
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
    """R18-1 회귀: JSON Infinity/NaN(json.loads 기본 허용) Gbps → int() OverflowError/ValueError
    로 network_adapters 섹션 전체 drop 되던 것 → _safe_int 경유로 (None,None) graceful."""
    assert rfg._normalize_port_speed({"CurrentSpeedGbps": float("inf")}) == (None, None)
    assert rfg._normalize_port_speed({"CurrentSpeedGbps": float("-inf")}) == (None, None)
    gbps, mbps = rfg._normalize_port_speed({"CurrentSpeedGbps": float("nan")})
    assert gbps is None and mbps is None
    # inf Gbps + 정상 Mbps → Gbps 무시, Mbps 보존
    g2, m2 = rfg._normalize_port_speed({"CurrentSpeedGbps": float("inf"), "CurrentLinkSpeedMbps": 10000})
    assert m2 == 10000 and g2 == 10.0


def test_port_speed_fractional_gbps_preserved(rfg):
    """R19-2/3 회귀: fractional CurrentSpeedGbps(2.5GbE 등)가 _safe_int truncate(2.5→2)되던 것 →
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
