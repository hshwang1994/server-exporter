"""CSUS 3200 fixture replay — tests/fixtures/redfish/hpe_csus_3200/ 오프라인 재생.

합성 fixture 파일들을 @odata.id 로 키잉한
응답 맵으로 재생해 `_collect_multi_node_topology` 를 end-to-end 구동한다. 이로써
(1) 신 컴포넌트(Thermal/Boot/LogServices/CompositionService/Fabrics) 수집 경로가
실제 fixture 로 회귀 보호되고, (2) fixture 들이 내부적으로 일관(링크 ↔ 대상 파일)
한지 검증된다.

lab 부재 — fixture 는 web sources 합성. 실 장비 fixture 교체 시 본 테스트는
그대로 재사용 (assert 는 구조 기반).
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

_stub_basic = types.ModuleType("ansible.module_utils.basic")
_stub_basic.AnsibleModule = object
_stub_module_utils = types.ModuleType("ansible.module_utils")
_stub_module_utils.basic = _stub_basic
_stub_ansible = types.ModuleType("ansible")
_stub_ansible.module_utils = _stub_module_utils
sys.modules.setdefault("ansible", _stub_ansible)
sys.modules.setdefault("ansible.module_utils", _stub_module_utils)
sys.modules.setdefault("ansible.module_utils.basic", _stub_basic)

import redfish_gather as rg  # noqa: E402

FIXTURE_DIR = REPO / "tests" / "fixtures" / "redfish" / "hpe_csus_3200"
CREDS = ("u", "p", 10, False)


def _build_response_map():
    """모든 *.json fixture 를 _p(@odata.id) 로 키잉한 GET 응답 맵 + service_root.

    service_root (@odata.id='/redfish/v1') 는 _p() 가 무효 처리하므로 맵에서 제외하고
    별도 반환한다 (_collect_multi_node_topology 인자로 전달).
    """
    response_map = {}
    service_root = None
    for f in sorted(FIXTURE_DIR.glob("*.json")):
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        oid = data.get("@odata.id")
        if not oid:
            continue
        if oid.rstrip("/") == "/redfish/v1":
            service_root = data
            continue
        response_map[rg._p(oid)] = (200, data, None)
    return response_map, service_root


@pytest.fixture(scope="module")
def topology(request):
    response_map, service_root = _build_response_map()
    assert service_root is not None, "service_root.json (@odata.id=/redfish/v1) 누락"

    def fake_get(bmc_ip, path, username, password, timeout, verify_ssl):
        if path in response_map:
            return response_map[path]
        return 404, None, "fixture 미존재 (graceful)"

    orig = rg._get
    rg._get = fake_get
    try:
        result = rg._collect_multi_node_topology(
            "10.50.11.999", "hpe", service_root, *CREDS, manager_layout="rmc_primary")
    finally:
        rg._get = orig
    return result


def test_topology_enabled(topology):
    assert topology is not None
    assert topology["enabled"] is True
    assert topology["layout"] == "rmc_primary"


def test_summary_counts(topology):
    s = topology["summary"]
    assert s["partition_count"] == 3
    assert s["manager_count"] == 4
    assert s["chassis_count"] == 3
    assert s["representative_partition"] == "Partition0"
    assert s["resource_block_count"] == 3
    assert s["fabric_count"] == 1


def test_partition0_boot_order(topology):
    """설명 모델: 각 nPartition 은 부팅 순서를 포함."""
    p0 = next(p for p in topology["partitions"] if p["id"] == "Partition0")
    assert p0["boot"]["boot_order"] == ["Boot0001", "Boot0002", "Boot0003"]
    assert p0["boot"]["boot_source_override_mode"] == "UEFI"


def test_all_partitions_populated(topology):
    """3 nPartition 전부 fixture 로 채워짐 (silent-empty 회귀 차단).

    이전엔 Partition1/2 fixture 부재로 system/boot 가 조용히 비어 있었음.
    """
    parts = {p["id"]: p for p in topology["partitions"]}
    assert set(parts) == {"Partition0", "Partition1", "Partition2"}
    for pid in parts:
        assert parts[pid]["boot"]["boot_order"] == ["Boot0001", "Boot0002", "Boot0003"], pid
        assert parts[pid]["system"].get("serial"), f"{pid} system.serial 비어있음"


def test_all_managers_populated_and_labeled(topology):
    """4 manager 전부 fixture 로 채워지고 RMC/PDHC/iLO 라벨 + role 분기.

    이전엔 PDHC0/PDHC1/Bay1.iLO5 fixture 부재로 bmc.name=None / log_services=[] 가
    조용히 발생.
    """
    mgrs = {m["id"]: m for m in topology["managers"]}
    assert set(mgrs) == {"RMC", "PDHC0", "PDHC1", "Bay1.iLO5"}
    assert mgrs["RMC"]["role"] == "primary" and mgrs["RMC"]["bmc"]["name"] == "RMC"
    assert mgrs["PDHC0"]["role"] == "secondary" and mgrs["PDHC0"]["bmc"]["name"] == "PDHC"
    assert mgrs["PDHC1"]["bmc"]["name"] == "PDHC"
    assert mgrs["Bay1.iLO5"]["role"] == "secondary" and mgrs["Bay1.iLO5"]["bmc"]["name"] == "iLO"
    # PDHC / iLO 는 LogServices 링크 미노출 → [] (graceful, RMC 만 IML/IEL)
    assert mgrs["PDHC0"]["log_services"] == []
    assert mgrs["Bay1.iLO5"]["log_services"] == []


def test_all_chassis_populated_with_thermal(topology):
    """3 chassis 전부 fixture + thermal (append-on-fail 멤버 노출 + thermal 수집)."""
    ch = {c["id"]: c for c in topology["chassis"]}
    assert set(ch) == {"Base", "Expansion1", "Expansion2"}
    for cid in ch:
        assert ch[cid]["thermal"].get("temperatures"), f"{cid} thermal 비어있음"
        assert ch[cid]["power"].get("power_supplies"), f"{cid} power 비어있음"
        assert ch[cid]["manufacturer"] == "HPE"


def test_replay_errors_are_only_graceful_404(topology):
    """replay error 는 fixture 미제공 sub-resource(404)만 — 예기치 못한 error 부재 보장.

    silent-empty 가 아닌 '의도된 graceful 404' 임을 명시.
    per-partition Processors/Memory/Storage/Network sub-resource fixture 부재 (4×3=12).
    """
    GRACEFUL = {"processors", "memory", "storage", "network"}
    errs = topology["errors"]
    bad = [e for e in errs if e.get("section") not in GRACEFUL]
    assert not bad, f"예기치 못한 (graceful 404 아님) error: {bad}"
    # 모든 error 는 dict + section/message 보유
    assert all(isinstance(e, dict) and e.get("section") and "message" in e for e in errs)


def test_base_chassis_thermal(topology):
    """설명 모델: 각 chassis 는 Power 와 Thermal 리소스를 둔다."""
    base = next(c for c in topology["chassis"] if c["id"] == "Base")
    # Power 실값 (chassis_base_power.json fixture — review [3] fix)
    assert base["power"]["power_control"]["power_consumed_watts"] == 1480
    assert len(base["power"]["power_supplies"]) == 2
    temps = base["thermal"]["temperatures"]
    fans = base["thermal"]["fans"]
    assert any(t["name"] == "Inlet Ambient" and t["reading_celsius"] == 22 for t in temps)
    assert len(fans) == 3 and fans[0]["reading"] == 8000


def test_rmc_log_services(topology):
    """설명 모델: RMC 는 Services 와 Logs 리소스로 연결된다."""
    rmc = next(m for m in topology["managers"] if m["id"] == "RMC")
    ids = [l["id"] for l in rmc["log_services"]]
    assert ids == ["IML", "IEL"]
    assert rmc["bmc"]["name"] == "RMC"


def test_composition_resource_blocks_map_to_chassis(topology):
    """설명 모델: 각 ResourceBlock 은 하나의 chassis 에 대응 + CPU/DIMM 포함."""
    comp = topology["composition"]
    assert comp is not None
    assert comp["resource_block_count"] == 3
    by_id = {b["id"]: b for b in comp["resource_blocks"]}
    assert by_id["Block0"]["chassis"] == ["/redfish/v1/Chassis/Base"]
    assert by_id["Block0"]["processor_count"] == 4
    assert by_id["Block0"]["memory_count"] == 8
    assert by_id["Block0"]["computer_systems"] == ["/redfish/v1/Systems/Partition0"]
    assert by_id["Block1"]["chassis"] == ["/redfish/v1/Chassis/Expansion1"]
    assert by_id["Block2"]["chassis"] == ["/redfish/v1/Chassis/Expansion2"]


def test_fabrics_flexgrid_switches_endpoints(topology):
    """설명 모델: NUMAlink fabric 을 표준 Fabric 모델로, FlexGrid 는 Switches+Endpoints."""
    fabrics = topology["fabrics"]
    assert fabrics is not None and len(fabrics) == 1
    fg = fabrics[0]
    assert fg["id"] == "FlexGrid"
    assert fg["switch_count"] == 2
    assert fg["endpoint_count"] == 2
    assert all(s["switch_type"] == "PCIe" for s in fg["switches"])
    assert all(e["endpoint_protocol"] == "PCIe" for e in fg["endpoints"])
