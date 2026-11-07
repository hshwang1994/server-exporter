# -*- coding: utf-8 -*-
"""
HPE CSUS 3200 실측 baseline — 구조·자기 일관성 가드 (2026-10-27 사용자 FIX 5 로 실측 교체).

schema/baseline_v1/hpe_csus_3200_baseline.json 은 2026-05-29 ~ 2026-10-27 동안 lab 부재로 만든 합성본
(3 파티션 · 4 manager, FABRICATED MOCK)이었다. 2026-10-27 FIX 5 로 용인 2차 Mock csus3200_01(RMC 1.77.30)
을 HTTPS 미러 재생 + 실제 ansible-playbook 으로 수집한 최종 envelope 로 교체했다 — 출처와 수정 2곳(재생 주소
127.0.0.1 → BMC IP)은 diagnosis.details.baseline_origin 에 적혀 있다. 파일 이름은 이력상 유지한다(내용은 실측 가드).
2026-10-29 Summary 정합성 수정(SA-01 · SA-03) 뒤 같은 방법으로 다시 만들었다(값 변경 2건 — baseline_origin).

가드(기대값은 2차 Mock 실측에서 손으로 적었다 — 코드 출력 스냅샷이 아니다):
- summary 카운트 == 실제 list 길이, representative_partition == partitions[0]
- 실 구조 1 partition / 1 manager(RMC primary) / 3 chassis(RackGroup · Rack1 · r001u01), layout rmc_primary
- composition 1 block(count 는 null — FIX 6) / fabrics 1(FlexGrid, switch 2 · endpoint 개수 null — Endpoints 링크 없음, SA-01)
- origin 이 실측 표기(mock 아님), 시리얼이 MOCK 접두가 아님, 디스크 4 · FC HBA 4 == FC 포트 4(개수 정합)
- sections.system not_supported + hostname 발행(FIX 4), cpu.logical_threads 부재(FIX 1)
"""
import json
from pathlib import Path

import pytest

BASELINE = (
    Path(__file__).resolve().parents[2]
    / "schema" / "baseline_v1" / "hpe_csus_3200_baseline.json"
)


@pytest.fixture(scope="module")
def csus():
    with open(BASELINE, encoding="utf-8") as f:
        return json.load(f)


def _multi_node(csus):
    mn = (csus.get("data") or {}).get("multi_node")
    assert mn, "CSUS baseline 에 data.multi_node 가 없음"
    return mn


def test_summary_counts_match_lists(csus):
    """summary 의 카운트가 실제 list 길이와 일치 (값 drift 방지)."""
    mn = _multi_node(csus)
    summ = mn.get("summary") or {}
    assert summ.get("partition_count") == len(mn.get("partitions") or []) == 1
    assert summ.get("manager_count") == len(mn.get("managers") or []) == 1
    assert summ.get("chassis_count") == len(mn.get("chassis") or []) == 3
    assert summ.get("resource_block_count") == len((mn.get("composition") or {}).get("resource_blocks") or []) == 1
    assert summ.get("fabric_count") == len(mn.get("fabrics") or []) == 1


def test_representative_partition_is_first(csus):
    """representative_partition 표식이 partitions[0] 와 일치."""
    mn = _multi_node(csus)
    parts = mn.get("partitions") or []
    assert parts, "partitions 가 비어있음"
    rep = (mn.get("summary") or {}).get("representative_partition")
    first_id = parts[0].get("partition_id") or parts[0].get("id")
    assert rep == first_id == "Partition0", f"representative={rep} != partitions[0]={first_id}"


def test_real_topology_one_partition_one_rmc_three_chassis(csus):
    """2차 Mock csus3200_01 실측 구조 — 합성본(3 파티션 · 4 manager · Base/Expansion 섀시)이 아니다."""
    mn = _multi_node(csus)
    assert mn.get("enabled") is True
    assert mn.get("layout") == "rmc_primary"
    assert [p["id"] for p in mn["partitions"]] == ["Partition0"]
    assert mn["partitions"][0]["system_uri"] == "/redfish/v1/Systems/Partition0"
    assert [(m["id"], m["role"], (m.get("bmc") or {}).get("name")) for m in mn["managers"]] == [("RMC", "primary", "RMC")]
    assert [(c["id"], c["kind"], c["chassis_type"]) for c in mn["chassis"]] == [
        ("RackGroup", "rackgroup", "RackGroup"),
        ("Rack1", "rack", "Rack"),
        ("r001u01", "rackmount", "RackMount"),
    ]
    # 전원·온도는 장비 섀시(r001u01)에만 있다 — RackGroup/Rack1 은 navigation property 가 없어 요청하지 않는다(WP7 C5)
    assert mn["chassis"][0]["power"] == {} and mn["chassis"][1]["power"] == {}
    assert len(mn["chassis"][2]["thermal"]["temperatures"]) == 63
    assert len(mn["chassis"][2]["thermal"]["fans"]) == 10
    assert (csus["data"].get("bmc") or {}).get("name") == "RMC"
    assert csus["vendor"] == "hpCsus"
    assert csus["meta"]["adapter_id"] == "redfish_hpe_csus_3200"


def test_composition_and_fabric_shape(csus):
    mn = _multi_node(csus)
    comp = mn["composition"]
    assert comp["enabled"] is True and comp["state"] == "Enabled"
    block = comp["resource_blocks"][0]
    assert block["id"] == "r001u01"
    assert block["computer_systems"] == ["/redfish/v1/Systems/Partition0"]
    assert block["chassis"] == ["/redfish/v1/Chassis/r001u01"]
    # FIX 6: ResourceBlock 에 Processors/Memory 배열이 없으면 count 는 null — 가짜 0 이 아니다
    assert block["processor_count"] is None and block["memory_count"] is None
    fab = mn["fabrics"][0]
    assert fab["id"] == "FlexGrid"
    assert fab["switch_count"] == len(fab["switches"]) == 2
    # SA-01 (2026-10-29): 원천 Fabrics/FlexGrid 본문에 Endpoints 링크가 없다 — 확인하지 못한 개수는 null, 목록은 [] 유지(사용자 결정)
    assert fab["endpoint_count"] is None and fab["endpoints"] == []
    assert [s["id"] for s in fab["switches"]] == ["r001u01_HARP0", "r001u01_HARP1"]


def test_origin_is_measured_not_mock(csus):
    """실측 표기 — mock 표식·MOCK 시리얼이 남아 있으면 교체가 덜 된 것이다."""
    origin = (csus.get("diagnosis") or {}).get("details", {}).get("baseline_origin") or ""
    assert "실측" in origin and "csus3200_01" in origin, origin
    assert "mock-derived" not in origin.lower()
    mn = _multi_node(csus)
    serials = [(p.get("system") or {}).get("serial") or "" for p in mn["partitions"]]
    assert serials == ["SGHD4MGNLH-000"]
    assert not any(s.upper().startswith("MOCK") for s in serials)
    assert csus["correlation"]["serial_number"] == "SGHD4MGNLH"
    assert csus["data"]["hardware"]["serial"] == "SGHD4MGNLH"
    assert csus["hostname"] == "yicdspdb01"
    assert csus["ip"] == csus["correlation"]["host_ip"] == csus["correlation"]["bmc_ip"] == "11.65.23.24"
    assert "127.0.0.1" not in json.dumps(csus["data"], ensure_ascii=False)


def test_disk_and_fc_counts_match_exposure(csus):
    """원본 노출 수(디스크 4 · FC 포트 4)와 수집 수가 같다 — placeholder 항목 0 (사용자 2026-10-27 3차 지시)."""
    st = csus["data"]["storage"]
    assert len(st["physical_disks"]) == 4
    assert len(st["hbas"]) == 4
    fc_ports = [p for p in csus["data"]["network"]["ports"]
                if "fibre" in str(p.get("port_type") or p.get("protocol") or "").lower()]
    assert len(fc_ports) == 4
    assert all(h["link_status"] == "down" for h in st["hbas"]), "RMC 는 Port LinkStatus 를 주지 않아 down 폴백(결정 11 A안)"


def test_fix1_fix4_contract(csus):
    assert "logical_threads" not in csus["data"]["cpu"]
    for p in _multi_node(csus)["partitions"]:
        assert "logical_threads" not in (p.get("cpu") or {})
    assert csus["sections"]["system"] == "not_supported"
    assert csus["data"]["system"]["hostname"] == "yicdspdb01"
    assert csus["data"]["cpu"]["manufacturer"] == "Intel"
