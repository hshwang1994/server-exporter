"""HBA / InfiniBand canonical cross-channel shape regression.

storage.hbas[] / storage.infiniband[] 가 전 채널
(redfish / os / esxi) 에서 동일 canonical 키를 emit 하는지 검증. 호출자가 채널 무관하게
같은 키로 파싱 가능해야 함 (통일 shape).

빈 baseline (FC/IB 미보유 lab 호스트) 은 빈 list → trivially pass.
populated: esxi_baseline (FC 2), hpe_csus_3200_baseline (FC 2) 가 실제 검증.
"""
from __future__ import annotations

VALID_PORT_TYPES = frozenset({"FibreChannel", "FCoE", "iSCSI"})
VALID_SOURCES = frozenset({"redfish", "os", "esxi"})

# 전 채널 통일 canonical 코어 키 (channel-specific extra 는 추가 허용)
HBA_REQUIRED_KEYS = ("wwpn", "wwnn", "link_status", "link_speed_gbps", "port_type", "source")
IB_REQUIRED_KEYS = ("node_guid", "link_status", "rate_gbps", "source")


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


def test_infiniband_entries_canonical(baseline_envelope: dict) -> None:
    label = baseline_envelope["__label"]
    ib = _storage(baseline_envelope).get("infiniband") or []
    assert isinstance(ib, list), f"[{label}] storage.infiniband not list"
    for i, b in enumerate(ib):
        assert isinstance(b, dict), f"[{label}] infiniband[{i}] not dict"
        for k in IB_REQUIRED_KEYS:
            assert k in b, f"[{label}] infiniband[{i}] missing canonical key '{k}': {sorted(b)}"
        assert b["source"] in VALID_SOURCES, (
            f"[{label}] infiniband[{i}].source invalid: {b['source']!r}"
        )


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
