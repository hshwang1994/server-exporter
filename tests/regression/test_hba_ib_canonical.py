"""HBA / InfiniBand canonical cross-channel shape regression (cycle 2026-05-29 · 2026-10-17 강화).

cycle 2026-05-29 (hba-ib-csus): storage.hbas[] / storage.infiniband[] 가 전 채널
(redfish / os / esxi) 에서 동일 canonical 키를 emit 하는지 검증. 호출자가 채널 무관하게
같은 키로 파싱 가능해야 함 (EXTERNAL-CONTRACTS §1/§2 통일 shape).

2026-10-17 (InfiniBand 전면 검증): IB 항목의 공통 계약을 키 4개 존재 검사에서 **11 키 + 자료형 + 값 규칙** 으로 올렸다
(docs/contract/03-fields.md 6.3.1). `assert_ib_entry_canonical` 은 Linux / Windows / Redfish 단위 테스트가 실제 렌더 결과에
그대로 적용한다 (시나리오 28 — 4채널 공통 계약). baseline 은 registry 밖 파일(windows_2022 등)까지 전수로 본다.

빈 baseline (FC/IB 미보유 lab 호스트) 은 빈 list → trivially pass.
populated: esxi_baseline (FC 2), hpe_csus_3200_baseline (FC 2) 가 실제 검증. IB 가 채워진 실측 baseline 은 없다 —
합성 fixture(tests/fixtures/redfish/synthetic_ib_mode) 의 손 작성 기대값이 Redfish 모양을 대표한다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BASELINE_DIR = REPO / "schema" / "baseline_v1"
SYNTH_IB = REPO / "tests" / "fixtures" / "redfish" / "synthetic_ib_mode" / "expected_network_adapters.json"

VALID_PORT_TYPES = frozenset({"FibreChannel", "FCoE", "iSCSI"})
VALID_SOURCES = frozenset({"redfish", "os", "esxi"})
VALID_LINK_STATUS = frozenset({"up", "down", "unknown"})          # storage.infiniband[] (종전 3값)
VALID_HBA_LINK_STATUS = frozenset({"up", "down"})                 # storage.hbas[] — 2026-10-19 값은 항상 up/down (null · unknown 없음)

# 전 채널 통일 canonical 코어 키 (channel-specific extra 는 추가 허용)
HBA_REQUIRED_KEYS = ("wwpn", "wwnn", "link_status", "link_speed_gbps", "port_type", "source")
# 2026-10-17: IB 항목 공통 11 키. Redfish 는 호환 키 adapter_model, Windows 는 note 를 더 가질 수 있다.
IB_REQUIRED_KEYS = ("adapter", "port", "node_guid", "port_guid", "link_status", "rate", "rate_gbps", "model", "vendor",
                    "firmware", "source")
IB_OPTIONAL_KEYS = frozenset({"adapter_model", "note"})
# GUID 표기 — 소문자 4-hex × 4 (filter_plugins/identity_normalizer.normalize_ib_guid · redfish_gather._normalize_ib_guid)
IB_GUID_RE = re.compile(r"^[0-9a-f]{4}(:[0-9a-f]{4}){3}$")


def assert_ib_entry_canonical(entry, label: str) -> None:
    """storage.infiniband[] 항목 1개의 공통 계약 (키 · 자료형 · 값 규칙). 4채널 단위 테스트가 실제 출력에 적용한다."""
    assert isinstance(entry, dict), f"[{label}] infiniband entry not dict: {entry!r}"
    for k in IB_REQUIRED_KEYS:
        assert k in entry, f"[{label}] infiniband entry missing canonical key '{k}': {sorted(entry)}"
    extra = set(entry) - set(IB_REQUIRED_KEYS) - IB_OPTIONAL_KEYS
    assert not extra, f"[{label}] infiniband entry has unknown keys {sorted(extra)} — 계약 밖 키는 field_dictionary 부터"
    assert entry["source"] in VALID_SOURCES, f"[{label}] source invalid: {entry['source']!r}"
    assert entry["link_status"] in VALID_LINK_STATUS, f"[{label}] link_status invalid: {entry['link_status']!r}"
    for k in ("adapter", "port", "rate", "model", "vendor", "firmware"):
        assert entry[k] is None or isinstance(entry[k], str), f"[{label}] {k} must be string|null: {entry[k]!r}"
    for k in ("node_guid", "port_guid"):
        v = entry[k]
        assert v is None or (isinstance(v, str) and IB_GUID_RE.match(v)), f"[{label}] {k} not a normalized GUID: {v!r}"
    r = entry["rate_gbps"]
    assert r is None or (isinstance(r, (int, float)) and not isinstance(r, bool) and r > 0), \
        f"[{label}] rate_gbps must be positive number|null: {r!r}"
    if entry["link_status"] != "up":
        assert r is None, f"[{label}] rate_gbps must be null unless link is up: {r!r}"
    if entry["source"] == "redfish":
        assert entry["rate"] is None, f"[{label}] Redfish has no rate text source — must be null"
        assert "adapter_model" in entry and entry["adapter_model"] == entry["model"], f"[{label}] adapter_model/model mismatch"
    if "note" in entry:
        assert isinstance(entry["note"], str) and not re.search(r"\brule\b|R\d+-?[A-Z]?\b", entry["note"]), \
            f"[{label}] note exposes internal rule ids: {entry['note']!r}"


def _storage(env: dict) -> dict:
    data = env.get("data") or {}
    st = data.get("storage")
    return st if isinstance(st, dict) else {}


def test_hba_entries_canonical(baseline_envelope: dict) -> None:
    label = baseline_envelope["__label"]
    hbas = _storage(baseline_envelope).get("hbas") or []
    assert isinstance(hbas, list), f"[{label}] storage.hbas not list"
    for i, h in enumerate(hbas):
        assert isinstance(h, dict), f"[{label}] hbas[{i}] not dict"
        for k in HBA_REQUIRED_KEYS:
            assert k in h, f"[{label}] hbas[{i}] missing canonical key '{k}': {sorted(h)}"
        assert h["port_type"] in VALID_PORT_TYPES, (
            f"[{label}] hbas[{i}].port_type invalid: {h['port_type']!r}"
        )
        assert h["source"] in VALID_SOURCES, (
            f"[{label}] hbas[{i}].source invalid: {h['source']!r}"
        )
        assert h["link_status"] in VALID_HBA_LINK_STATUS, (
            f"[{label}] hbas[{i}].link_status invalid: {h['link_status']!r} (up / down)"
        )


def test_infiniband_entries_canonical(baseline_envelope: dict) -> None:
    label = baseline_envelope["__label"]
    ib = _storage(baseline_envelope).get("infiniband") or []
    assert isinstance(ib, list), f"[{label}] storage.infiniband not list"
    for i, b in enumerate(ib):
        assert_ib_entry_canonical(b, f"{label} infiniband[{i}]")


@pytest.mark.parametrize("path", sorted(BASELINE_DIR.glob("*.json")), ids=lambda p: p.stem)
def test_every_baseline_file_infiniband_entries_canonical(path: Path) -> None:
    """registry 밖 baseline(windows_2022 등)도 같은 계약 — 2026-06-22 오탐 3건(팀 멀티플렉서)이 2026-10-17 에 [] 로 정정됐다."""
    env = json.loads(path.read_text(encoding="utf-8"))
    st = _storage(env)
    if "infiniband" not in st:
        # 2026-05-29 이전 실측 캡처(dell/hpe/lenovo/cisco/windows)에는 키 자체가 없다 — 실측 없이 baseline 을 고치지 않는다 (rule 21 R1)
        pytest.skip(f"{path.stem}: storage.infiniband 키 없음 (2026-05-29 이전 캡처)")
    ib = st["infiniband"]
    assert isinstance(ib, list), f"[{path.stem}] storage.infiniband not list"
    for i, b in enumerate(ib):
        assert_ib_entry_canonical(b, f"{path.stem} infiniband[{i}]")
    if path.stem == "windows_2022_baseline":
        assert ib == [], "10.100.64.120 은 IB 가 없다 (2026-09-03 실측 build192) — 팀 멀티플렉서 오탐이 되살아났다"


def test_synthetic_redfish_ib_fixture_entries_canonical() -> None:
    """합성 IB 모드 fixture 의 손 작성 기대값이 공통 계약을 만족한다 (Redfish 모양의 대표 — 실장비 아님)."""
    if not SYNTH_IB.is_file():
        pytest.skip("synthetic_ib_mode fixture 없음")
    entries = json.loads(SYNTH_IB.read_text(encoding="utf-8"))["infiniband"]
    assert len(entries) == 2
    for i, b in enumerate(entries):
        assert_ib_entry_canonical(b, f"synthetic_ib_mode infiniband[{i}]")
    assert [b["link_status"] for b in entries] == ["up", "down"]


def test_multi_node_partition_hba_ib_shape(baseline_envelope: dict) -> None:
    """multi_node.partitions[].storage 도 hbas/infiniband 키 보유 (CSUS canonical)."""
    label = baseline_envelope["__label"]
    mn = (baseline_envelope.get("data") or {}).get("multi_node")
    if not isinstance(mn, dict):
        return  # 비 multi_node vendor — N/A
    for p in mn.get("partitions") or []:
        st = p.get("storage") or {}
        assert "hbas" in st and "infiniband" in st, (
            f"[{label}] multi_node partition {p.get('id')} storage missing hbas/infiniband"
        )


def test_schema_example_hbas_use_the_canonical_shape() -> None:
    """2026-10-15: schema/examples/redfish_success.json 의 hbas 예시가 실제 출력과 같은 모양인지 (종전 예시는 SAS 컨트롤러 모양)."""
    ex = json.loads((REPO / "schema" / "examples" / "redfish_success.json").read_text(encoding="utf-8"))
    hbas = ex["data"]["storage"]["hbas"]
    assert hbas, "예시는 비어 있지 않아야 형식을 보여 줄 수 있다"
    for h in hbas:
        for k in HBA_REQUIRED_KEYS + ("adapter_id", "adapter_model", "port_id"):
            assert k in h, f"example hbas entry missing '{k}': {sorted(h)}"
        assert h["port_type"] in VALID_PORT_TYPES and h["source"] == "redfish"
        assert h["link_status"] in VALID_HBA_LINK_STATUS
