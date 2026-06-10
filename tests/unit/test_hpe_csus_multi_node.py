"""회귀 — HPE CSUS 3200 / Superdome Flex 멀티-노드 토폴로지 수집.

`gather_managers_multi` / `gather_systems_multi` / `gather_chassis_multi` /
`_collect_multi_node_topology` 통합 동작 검증. mock HTTP 응답 (3-partition × 4-manager
× 3-chassis 시나리오) 으로 lab 부재 환경 회귀 차단.

검증 항목:
1. manager_layout=None → multi_node=None (기존 vendor 동작 유지)
2. manager_layout='rmc_primary' + 멀티 manager → 전 manager 추출 + RMC primary 라벨
3. manager_layout='rmc_primary_ilo_secondary' + RMC+PDHC+iLO5 → 라벨 분기 (RMC/PDHC/iLO)
4. multi-partition 전수 수집 — partitions[].id 모두 추출
5. multi-chassis 전수 수집 — base/expansion kind 분류
6. summary.{partition_count, manager_count, chassis_count} 정확
7. representative_partition = partitions[0].id
8. 일부 endpoint fail 시 errors[] 누적 (graceful degradation)
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

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


# ── Mock infrastructure ─────────────────────────────────────────────────────


def _csus_response_map() -> dict:
    """CSUS 3200 합성 응답 — 3-partition × 4-manager × 3-chassis 시나리오.

    `_p()` 가 prefix 를 제거해 path 가 'Managers', 'Systems/Partition0' 형식.
    source (web sources 합성): sdflexutils + DMTF v1.15 + iLO5 API ref.
    """
    return {
        # Managers 컬렉션
        "Managers": (200, {
            "Members": [
                {"@odata.id": "/redfish/v1/Managers/RMC"},
                {"@odata.id": "/redfish/v1/Managers/PDHC0"},
                {"@odata.id": "/redfish/v1/Managers/PDHC1"},
                {"@odata.id": "/redfish/v1/Managers/Bay1.iLO5"},
            ]
        }, None),
        # Manager 개별
        "Managers/RMC": (200, {
            "Id": "RMC", "Name": "Rack Management Controller",
            "FirmwareVersion": "3.10.00", "Model": "CSUS 3200 RMC",
            "ManagerType": "EnclosureManager",
            "Status": {"Health": "OK", "State": "Enabled"},
            "PowerState": "On", "UUID": "rmc-uuid",
        }, None),
        "Managers/PDHC0": (200, {
            "Id": "PDHC0", "FirmwareVersion": "3.10.00",
            "Status": {"Health": "OK", "State": "Enabled"},
        }, None),
        "Managers/PDHC1": (200, {
            "Id": "PDHC1", "FirmwareVersion": "3.10.00",
            "Status": {"Health": "OK", "State": "Enabled"},
        }, None),
        "Managers/Bay1.iLO5": (200, {
            "Id": "Bay1.iLO5", "FirmwareVersion": "2.85",
            "Status": {"Health": "OK", "State": "Enabled"},
        }, None),
        # Systems 컬렉션
        "Systems": (200, {
            "Members": [
                {"@odata.id": "/redfish/v1/Systems/Partition0"},
                {"@odata.id": "/redfish/v1/Systems/Partition1"},
                {"@odata.id": "/redfish/v1/Systems/Partition2"},
            ]
        }, None),
        # System per-partition (gather_system 호출 — 빈 dict 반환해도 OK)
        "Systems/Partition0": (200, {
            "Id": "Partition0", "Manufacturer": "HPE",
            "Model": "Compute Scale-up Server 3200",
            "Status": {"Health": "OK", "State": "Enabled"},
            "PowerState": "On",
            "ProcessorSummary": {"Count": 4},
            "MemorySummary": {"TotalSystemMemoryGiB": 2048},
        }, None),
        "Systems/Partition1": (200, {
            "Id": "Partition1", "Manufacturer": "HPE",
            "Model": "Compute Scale-up Server 3200",
            "Status": {"Health": "OK", "State": "Enabled"},
            "PowerState": "On",
        }, None),
        "Systems/Partition2": (200, {
            "Id": "Partition2", "Manufacturer": "HPE",
            "Model": "Compute Scale-up Server 3200",
            "Status": {"Health": "OK", "State": "Enabled"},
            "PowerState": "On",
        }, None),
        # Chassis 컬렉션
        "Chassis": (200, {
            "Members": [
                {"@odata.id": "/redfish/v1/Chassis/Base"},
                {"@odata.id": "/redfish/v1/Chassis/Expansion1"},
                {"@odata.id": "/redfish/v1/Chassis/Expansion2"},
            ]
        }, None),
        # Chassis per-id
        "Chassis/Base": (200, {
            "Id": "Base", "ChassisType": "Enclosure",
            "Manufacturer": "HPE", "Model": "CSUS 3200 Base",
            "SerialNumber": "SN-BASE", "PartNumber": "PN-BASE",
        }, None),
        "Chassis/Expansion1": (200, {
            "Id": "Expansion1", "ChassisType": "Enclosure",
            "Manufacturer": "HPE", "Model": "CSUS 3200 Expansion",
            "SerialNumber": "SN-EXP1", "PartNumber": "PN-EXP",
        }, None),
        "Chassis/Expansion2": (200, {
            "Id": "Expansion2", "ChassisType": "Enclosure",
            "Manufacturer": "HPE", "Model": "CSUS 3200 Expansion",
            "SerialNumber": "SN-EXP2", "PartNumber": "PN-EXP",
        }, None),
    }


def _patch_get(monkeypatch, extra=None) -> None:
    """`rg._get` mock + 부재 path → 404 graceful (gather_* 함수들이 graceful fail).

    extra: 기본 응답 map 위에 덧씌울 dict (예: 일부 endpoint fail 시나리오)
    """
    base = _csus_response_map()
    if extra:
        base.update(extra)

    def fake_get(bmc_ip, path, username, password, timeout, verify_ssl):
        if path in base:
            return base[path]
        # 미정의 path (EthernetInterfaces / Processors / Memory / Storage / Network / Power)
        # 는 404 — gather_* 함수가 errors[] 에 등록하고 graceful 진행.
        return 404, None, "not mocked"

    monkeypatch.setattr(rg, "_get", fake_get)


# ── _collect_multi_node_topology — manager_layout=None ──────────────────────


def test_multi_node_topology_disabled_when_layout_none(monkeypatch) -> None:
    """manager_layout=None → None 반환 (기존 vendor 동작 유지)."""
    _patch_get(monkeypatch)
    service_root = {
        "Systems":  {"@odata.id": "/redfish/v1/Systems"},
        "Managers": {"@odata.id": "/redfish/v1/Managers"},
        "Chassis":  {"@odata.id": "/redfish/v1/Chassis"},
    }
    result = rg._collect_multi_node_topology(
        "10.0.0.1", "hpe", service_root,
        "u", "p", 10, False, manager_layout=None,
    )
    assert result is None


# ── _collect_multi_node_topology — RMC primary multi-manager ────────────────


def test_multi_node_topology_rmc_primary_all_managers(monkeypatch) -> None:
    """manager_layout='rmc_primary' + 4 managers → 모두 추출 + RMC primary 라벨."""
    _patch_get(monkeypatch)
    service_root = {
        "Systems":  {"@odata.id": "/redfish/v1/Systems"},
        "Managers": {"@odata.id": "/redfish/v1/Managers"},
        "Chassis":  {"@odata.id": "/redfish/v1/Chassis"},
    }
    result = rg._collect_multi_node_topology(
        "10.0.0.1", "hpe", service_root,
        "u", "p", 10, False, manager_layout="rmc_primary",
    )
    assert result is not None
    assert result["enabled"] is True
    assert result["layout"] == "rmc_primary"
    assert result["summary"]["manager_count"] == 4
    # RMC 가 primary 로 분류 + 'RMC' 라벨
    rmc_entry = next(m for m in result["managers"] if m["id"] == "RMC")
    assert rmc_entry["role"] == "primary"
    assert rmc_entry["bmc"]["name"] == "RMC"


def test_multi_node_topology_pdhc_secondary(monkeypatch) -> None:
    """PDHC0/PDHC1 → role=secondary + 'PDHC' 라벨."""
    _patch_get(monkeypatch)
    service_root = {
        "Systems":  {"@odata.id": "/redfish/v1/Systems"},
        "Managers": {"@odata.id": "/redfish/v1/Managers"},
        "Chassis":  {"@odata.id": "/redfish/v1/Chassis"},
    }
    result = rg._collect_multi_node_topology(
        "10.0.0.1", "hpe", service_root,
        "u", "p", 10, False, manager_layout="rmc_primary",
    )
    pdhc0 = next(m for m in result["managers"] if m["id"] == "PDHC0")
    assert pdhc0["role"] == "secondary"
    assert pdhc0["bmc"]["name"] == "PDHC"


def test_multi_node_topology_ilo_secondary_in_dual_manager_layout(monkeypatch) -> None:
    """rmc_primary_ilo_secondary + Bay1.iLO5 → role=secondary + 'iLO' 라벨."""
    _patch_get(monkeypatch)
    service_root = {
        "Systems":  {"@odata.id": "/redfish/v1/Systems"},
        "Managers": {"@odata.id": "/redfish/v1/Managers"},
        "Chassis":  {"@odata.id": "/redfish/v1/Chassis"},
    }
    result = rg._collect_multi_node_topology(
        "10.0.0.1", "hpe", service_root,
        "u", "p", 10, False, manager_layout="rmc_primary_ilo_secondary",
    )
    ilo = next(m for m in result["managers"] if m["id"] == "Bay1.iLO5")
    assert ilo["role"] == "secondary"
    assert ilo["bmc"]["name"] == "iLO"


# ── multi-partition / multi-chassis ─────────────────────────────────────────


def test_multi_node_topology_partitions_all_extracted(monkeypatch) -> None:
    """3 partition 모두 추출 + summary.partition_count=3 + representative=Partition0."""
    _patch_get(monkeypatch)
    service_root = {
        "Systems":  {"@odata.id": "/redfish/v1/Systems"},
        "Managers": {"@odata.id": "/redfish/v1/Managers"},
        "Chassis":  {"@odata.id": "/redfish/v1/Chassis"},
    }
    result = rg._collect_multi_node_topology(
        "10.0.0.1", "hpe", service_root,
        "u", "p", 10, False, manager_layout="rmc_primary",
    )
    assert result["summary"]["partition_count"] == 3
    assert result["summary"]["representative_partition"] == "Partition0"
    ids = [p["id"] for p in result["partitions"]]
    assert ids == ["Partition0", "Partition1", "Partition2"]


def test_multi_node_topology_chassis_kind_classified(monkeypatch) -> None:
    """Base / Expansion1 / Expansion2 → kind=base / expansion / expansion."""
    _patch_get(monkeypatch)
    service_root = {
        "Systems":  {"@odata.id": "/redfish/v1/Systems"},
        "Managers": {"@odata.id": "/redfish/v1/Managers"},
        "Chassis":  {"@odata.id": "/redfish/v1/Chassis"},
    }
    result = rg._collect_multi_node_topology(
        "10.0.0.1", "hpe", service_root,
        "u", "p", 10, False, manager_layout="rmc_primary",
    )
    assert result["summary"]["chassis_count"] == 3
    by_id = {c["id"]: c for c in result["chassis"]}
    assert by_id["Base"]["kind"] == "base"
    assert by_id["Expansion1"]["kind"] == "expansion"
    assert by_id["Expansion2"]["kind"] == "expansion"


# ── gather_bmc backward-compat (manager_layout 옵션 인자) ──────────────────


def test_gather_bmc_manager_layout_none_preserves_existing(monkeypatch) -> None:
    """manager_layout=None → 기존 bmc_names[vendor] fallback (HPE → 'iLO')."""
    _patch_get(monkeypatch)
    data, errs = rg.gather_bmc(
        "10.0.0.1", "/redfish/v1/Managers/Bay1.iLO5", "hpe",
        "u", "p", 10, False,
    )
    # Bay1.iLO5 endpoint 가 mock 응답 — manager_layout None 이라 bmc_names['hpe']='iLO'.
    assert data["name"] == "iLO"


def test_gather_bmc_manager_layout_rmc_overrides_label(monkeypatch) -> None:
    """manager_layout='rmc_primary' + Manager Id='RMC' → 'RMC' 라벨."""
    _patch_get(monkeypatch)
    data, errs = rg.gather_bmc(
        "10.0.0.1", "/redfish/v1/Managers/RMC", "hpe",
        "u", "p", 10, False,
        manager_layout="rmc_primary",
    )
    assert data["name"] == "RMC"


# ── per-partition storage/network 정규화 (canonical shape) ──


def test_partition_storage_normalized_to_canonical_shape() -> None:
    """raw gather_storage {controllers, volumes} → canonical storage section.

    physical_disks dedup + summary.groups + hbas/infiniband 자리 + 표준 키 보장.
    """
    raw = {
        "controllers": [{
            "id": "RSTe.SATA.1", "name": "Intel RSTe SATA",
            "controller_model": "C741 SATA", "controller_firmware": "1.2.3",
            "controller_manufacturer": "Intel", "controller_health": "OK",
            "health": "OK",
            "drives": [
                {"id": "Disk.0", "name": "Disk 0", "model": "MZ7L3480",
                 "serial": "S1", "capacity_bytes": 480103981056,
                 "media_type": "SSD", "protocol": "SATA", "health": "OK"},
                {"id": "Disk.1", "name": "Disk 1", "model": "MZ7L3480",
                 "serial": "S2", "capacity_bytes": 480103981056,
                 "media_type": "SSD", "protocol": "SATA", "health": "OK"},
            ],
        }],
        "volumes": [{
            "id": "Vol.0", "name": "OS Mirror", "controller_id": "RSTe.SATA.1",
            "member_drive_ids": ["Disk.0", "Disk.1"], "raid_level": "RAID1",
            "total_mb": 457862, "health": "OK", "state": "Enabled",
            "boot_volume": True,
        }],
    }
    out = rg._normalize_storage_raw(raw)
    # canonical 키 전부 존재 (top-level storage 와 동일 schema)
    for key in ("filesystems", "physical_disks", "datastores", "controllers",
                "logical_volumes", "summary", "hbas", "infiniband"):
        assert key in out, f"canonical storage key missing: {key}"
    assert len(out["controllers"]) == 1
    assert len(out["physical_disks"]) == 2  # dedup by name+model+serial (서로 다른 serial)
    assert out["logical_volumes"][0]["raid_level"] == "RAID1"
    # summary: 동일 480GB SATA SSD 2개 그룹
    assert out["summary"]["groups"][0]["quantity"] == 2
    assert out["summary"]["grand_total_gb"] == 2 * (480103981056 // 1048576 // 1024)
    assert out["hbas"] == [] and out["infiniband"] == []


def test_partition_storage_normalize_empty_raw() -> None:
    """빈/None raw → 빈 canonical (graceful — 404 partition storage)."""
    for raw in ({}, None, {"controllers": [], "volumes": []}):
        out = rg._normalize_storage_raw(raw)
        assert out["controllers"] == []
        assert out["physical_disks"] == []
        assert out["summary"] == {"groups": [], "grand_total_gb": 0}


def test_partition_network_normalized_to_dict() -> None:
    """raw gather_network (NIC list) → canonical network dict (구: list 노출 버그)."""
    raw = [{
        "id": "Eth0", "name": "Partition NIC 0", "mac": "aa:bb:cc:00:00:01",
        "speed_mbps": 25000, "mtu": 1500, "link_status": "LinkUp", "health": "OK",
        "ipv4": [{"address": "10.1.2.3", "subnet_mask": "255.255.255.0",
                  "gateway": "10.1.2.1", "address_origin": "DHCP"}],
    }]
    out = rg._normalize_network_raw(raw)
    assert isinstance(out, dict)  # 구 버그: list 였음
    for key in ("dns_servers", "default_gateways", "interfaces", "adapters",
                "ports", "summary"):
        assert key in out
    assert out["interfaces"][0]["link_status"] == "up"  # 정규화
    assert {"family": "ipv4", "address": "10.1.2.1"} in out["default_gateways"]


def test_partition_network_normalize_empty() -> None:
    """빈/None → 빈 canonical dict (404 partition network graceful)."""
    for raw in ([], None, "not-a-list"):
        out = rg._normalize_network_raw(raw)
        assert isinstance(out, dict)
        assert out["interfaces"] == []


def test_multi_node_partition_sections_are_canonical(monkeypatch) -> None:
    """전체 토폴로지에서 partitions[].storage 는 dict(canonical), network 도 dict.

    (Partition Storage/EthernetInterfaces 가 404 인 mock 이라도 shape 는 dict 보장.)
    """
    _patch_get(monkeypatch)
    service_root = {
        "Systems":  {"@odata.id": "/redfish/v1/Systems"},
        "Managers": {"@odata.id": "/redfish/v1/Managers"},
        "Chassis":  {"@odata.id": "/redfish/v1/Chassis"},
    }
    result = rg._collect_multi_node_topology(
        "10.0.0.1", "hpe", service_root,
        "u", "p", 10, False, manager_layout="rmc_primary",
    )
    p0 = result["partitions"][0]
    assert isinstance(p0["storage"], dict)
    assert set(("controllers", "physical_disks", "logical_volumes",
                "hbas", "infiniband", "summary")).issubset(p0["storage"].keys())
    assert isinstance(p0["network"], dict)
    assert "interfaces" in p0["network"]
    # cpu/memory 도 canonical (구: raw list/dict)
    assert isinstance(p0["cpu"], dict) and "summary" in p0["cpu"]
    assert isinstance(p0["memory"], dict) and "total_mb" in p0["memory"]


def test_partition_cpu_normalized_gpu_filter() -> None:
    """raw gather_processors(list) → canonical cpu (GPU 제외 + 합산 + summary)."""
    procs = [
        {"id": "1", "model": "Intel(R) Xeon(R) Platinum 8480+",
         "manufacturer": "Intel", "total_cores": 56, "total_threads": 112,
         "speed_mhz": 3800, "processor_type": "CPU"},
        {"id": "2", "model": "Intel(R) Xeon(R) Platinum 8480+",
         "manufacturer": "Intel", "total_cores": 56, "total_threads": 112,
         "speed_mhz": 3800, "processor_type": "CPU"},
        # GPU 는 CPU 필터로 제외되어야 함
        {"id": "GPU1", "model": "NVIDIA H100", "total_cores": 0,
         "processor_type": "GPU"},
    ]
    out = rg._normalize_cpu_raw(procs)
    assert out["sockets"] == 2  # GPU 제외
    assert out["cores_physical"] == 112
    assert out["logical_threads"] == 224
    assert out["model"] == "Intel(R) Xeon(R) Platinum 8480+"
    assert out["summary"]["groups"][0]["sockets"] == 2
    assert out["summary"]["groups"][0]["total_cores"] == 112


def test_partition_memory_normalized_summary() -> None:
    """raw gather_memory {total_mib, slots} → canonical memory + summary grouping."""
    raw = {"total_mib": 2097152, "slots": [
        {"id": f"DIMM{i}", "capacity_mb": 131072, "type": "DDR5",
         "speed_mhz": 4800, "manufacturer": "Samsung", "part_number": "M321",
         "health": "OK"} for i in range(16)
    ]}
    out = rg._normalize_memory_raw(raw)
    assert out["total_mb"] == 2097152
    assert out["total_basis"] == "physical_installed"
    assert len(out["slots"]) == 16
    g = out["summary"]["groups"][0]
    assert g["unit_capacity_gb"] == 128 and g["quantity"] == 16
    assert g["group_total_gb"] == 2048
    assert out["summary"]["grand_total_gb"] == 2048
