"""ADR-2026-06-09 회귀 — HPE CSUS 3200 / Superdome Flex 멀티-노드 토폴로지 확장 수집.

cycle 2026-06-09 (설명 모델 검수 후속) — 누락분 5종 Additive 구현 회귀 차단:
  1. Chassis Thermal (gather_thermal + /ThermalSubsystem fallback)
  2. per-partition Boot order (gather_boot)
  3. Manager LogServices (gather_manager_logs)
  4. CompositionService + ResourceBlocks (gather_composition_service)
  5. Fabrics + FlexGrid Switches/Endpoints (gather_fabrics)

모두 mock HTTP 응답 (lab 부재 — rule 96 R1-A 합성: DMTF DSP0266 + HPE CSUS 3200
Administration Guide + Superdome Flex 상속). 단일 노드 path / 13 vendor 영향 0 검증 포함.
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

CREDS = ("u", "p", 10, False)


# ── Mock infrastructure ─────────────────────────────────────────────────────


def _extended_map() -> dict:
    """CSUS 3200 확장 합성 응답 — Boot / LogServices / CompositionService / Fabrics 포함.

    `_p()` 가 prefix 제거 → key 는 'Systems/Partition0', 'Fabrics/FlexGrid' 형식.
    """
    return {
        # Systems
        "Systems": (200, {"Members": [
            {"@odata.id": "/redfish/v1/Systems/Partition0"},
            {"@odata.id": "/redfish/v1/Systems/Partition1"},
        ]}, None),
        "Systems/Partition0": (200, {
            "Id": "Partition0", "Manufacturer": "HPE",
            "Model": "Compute Scale-up Server 3200",
            "Status": {"Health": "OK", "State": "Enabled"}, "PowerState": "On",
            "Boot": {
                "BootOrder": ["Boot0001", "Boot0002", "Boot0003"],
                "BootSourceOverrideEnabled": "Once",
                "BootSourceOverrideTarget": "Pxe",
                "BootSourceOverrideMode": "UEFI",
                "BootNext": "",
            },
        }, None),
        "Systems/Partition1": (200, {
            "Id": "Partition1", "Manufacturer": "HPE",
            "Model": "Compute Scale-up Server 3200",
            "Status": {"Health": "OK", "State": "Enabled"}, "PowerState": "On",
            # Boot 미노출 → boot == {}
        }, None),
        # Managers
        "Managers": (200, {"Members": [
            {"@odata.id": "/redfish/v1/Managers/RMC"},
        ]}, None),
        "Managers/RMC": (200, {
            "Id": "RMC", "FirmwareVersion": "3.10.00", "Model": "CSUS 3200 RMC",
            "ManagerType": "EnclosureManager",
            "Status": {"Health": "OK", "State": "Enabled"}, "PowerState": "On",
            "LogServices": {"@odata.id": "/redfish/v1/Managers/RMC/LogServices"},
        }, None),
        "Managers/RMC/LogServices": (200, {"Members": [
            {"@odata.id": "/redfish/v1/Managers/RMC/LogServices/IML"},
            {"@odata.id": "/redfish/v1/Managers/RMC/LogServices/IEL"},
        ]}, None),
        "Managers/RMC/LogServices/IML": (200, {
            "Id": "IML", "Name": "Integrated Management Log",
            "OverWritePolicy": "WrapsWhenFull", "ServiceEnabled": True,
            "LogEntryType": "OEM", "DateTime": "2026-06-09T00:00:00Z",
        }, None),
        "Managers/RMC/LogServices/IEL": (200, {
            "Id": "IEL", "Name": "Integrated Event Log",
            "OverWritePolicy": "WrapsWhenFull", "ServiceEnabled": True,
        }, None),
        # Chassis
        "Chassis": (200, {"Members": [
            {"@odata.id": "/redfish/v1/Chassis/Base"},
        ]}, None),
        "Chassis/Base": (200, {
            "Id": "Base", "ChassisType": "Enclosure", "Manufacturer": "HPE",
            "Model": "CSUS 3200 Base", "SerialNumber": "SN-BASE",
            "PartNumber": "PN-BASE",
            "Thermal": {"@odata.id": "/redfish/v1/Chassis/Base/Thermal"},
        }, None),
        "Chassis/Base/Thermal": (200, {
            "Temperatures": [
                {"Name": "Inlet", "ReadingCelsius": 22,
                 "Status": {"Health": "OK", "State": "Enabled"},
                 "UpperThresholdCritical": 42, "PhysicalContext": "Intake"},
                {"Name": "CPU1", "ReadingCelsius": "55",  # str → _safe_int 방어
                 "Status": {"Health": "OK"}},
            ],
            "Fans": [
                {"Name": "Fan1", "Reading": 8000, "ReadingUnits": "RPM",
                 "Status": {"Health": "OK"}},
                {"Name": "Fan2", "ReadingRPM": 7800,  # ReadingRPM fallback
                 "Status": {"Health": "OK"}},
            ],
        }, None),
        # CompositionService
        "CompositionService": (200, {
            "Id": "CompositionService", "ServiceEnabled": True,
            "Status": {"State": "Enabled", "Health": "OK"},
            "ResourceBlocks": {"@odata.id": "/redfish/v1/CompositionService/ResourceBlocks"},
        }, None),
        "CompositionService/ResourceBlocks": (200, {"Members": [
            {"@odata.id": "/redfish/v1/CompositionService/ResourceBlocks/Block0"},
            {"@odata.id": "/redfish/v1/CompositionService/ResourceBlocks/Block1"},
        ]}, None),
        "CompositionService/ResourceBlocks/Block0": (200, {
            "Id": "Block0", "Name": "Compute Block 0",
            "ResourceBlockType": ["Compute"],
            "Status": {"State": "Enabled", "Health": "OK"},
            "CompositionStatus": {"CompositionState": "Composed"},
            "Processors": [{"@odata.id": f"/x/p{i}"} for i in range(4)],
            "Memory": [{"@odata.id": f"/x/m{i}"} for i in range(8)],
            "Links": {
                "Chassis": [{"@odata.id": "/redfish/v1/Chassis/Base"}],
                "ComputerSystems": [{"@odata.id": "/redfish/v1/Systems/Partition0"}],
            },
        }, None),
        "CompositionService/ResourceBlocks/Block1": (200, {
            "Id": "Block1", "ResourceBlockType": ["Compute"],
            "Status": {"State": "Enabled", "Health": "OK"},
            "CompositionStatus": {"CompositionState": "Unused"},
            "Processors": [{"@odata.id": "/x/p0"}],
            "Memory": [{"@odata.id": "/x/m0"}, {"@odata.id": "/x/m1"}],
            "Links": {"Chassis": [{"@odata.id": "/redfish/v1/Chassis/Expansion1"}]},
        }, None),
        # Fabrics
        "Fabrics": (200, {"Members": [
            {"@odata.id": "/redfish/v1/Fabrics/FlexGrid"},
        ]}, None),
        "Fabrics/FlexGrid": (200, {
            "Id": "FlexGrid", "Name": "NUMAlink FlexGrid Fabric",
            "FabricType": "PCIe",
            "Status": {"State": "Enabled", "Health": "OK"},
            "Switches": {"@odata.id": "/redfish/v1/Fabrics/FlexGrid/Switches"},
            "Endpoints": {"@odata.id": "/redfish/v1/Fabrics/FlexGrid/Endpoints"},
        }, None),
        "Fabrics/FlexGrid/Switches": (200, {"Members": [
            {"@odata.id": "/redfish/v1/Fabrics/FlexGrid/Switches/Switch0"},
            {"@odata.id": "/redfish/v1/Fabrics/FlexGrid/Switches/Switch1"},
        ]}, None),
        "Fabrics/FlexGrid/Switches/Switch0": (200, {
            "Id": "Switch0", "Name": "FlexGrid Switch 0", "SwitchType": "PCIe",
            "Status": {"State": "Enabled", "Health": "OK"},
        }, None),
        "Fabrics/FlexGrid/Switches/Switch1": (200, {
            "Id": "Switch1", "SwitchType": "PCIe",
            "Status": {"State": "Enabled", "Health": "OK"},
        }, None),
        "Fabrics/FlexGrid/Endpoints": (200, {"Members": [
            {"@odata.id": "/redfish/v1/Fabrics/FlexGrid/Endpoints/Endpoint0"},
        ]}, None),
        "Fabrics/FlexGrid/Endpoints/Endpoint0": (200, {
            "Id": "Endpoint0", "EndpointProtocol": "PCIe",
            "Status": {"State": "Enabled", "Health": "OK"},
        }, None),
    }


def _patch(monkeypatch, extra=None) -> None:
    base = _extended_map()
    if extra:
        base.update(extra)

    def fake_get(bmc_ip, path, username, password, timeout, verify_ssl):
        if path in base:
            return base[path]
        return 404, None, "not mocked"

    monkeypatch.setattr(rg, "_get", fake_get)


def _full_service_root() -> dict:
    return {
        "Systems":  {"@odata.id": "/redfish/v1/Systems"},
        "Managers": {"@odata.id": "/redfish/v1/Managers"},
        "Chassis":  {"@odata.id": "/redfish/v1/Chassis"},
        "Fabrics":  {"@odata.id": "/redfish/v1/Fabrics"},
        "CompositionService": {"@odata.id": "/redfish/v1/CompositionService"},
    }


# ── gather_thermal ──────────────────────────────────────────────────────────


def test_thermal_legacy_temperatures_and_fans(monkeypatch) -> None:
    _patch(monkeypatch)
    data, errs = rg.gather_thermal("10.0.0.1", "/redfish/v1/Chassis/Base", *CREDS)
    assert errs == []
    assert len(data["temperatures"]) == 2
    inlet = data["temperatures"][0]
    assert inlet["name"] == "Inlet" and inlet["reading_celsius"] == 22
    assert inlet["upper_critical"] == 42
    # str "55" → int 55 (cast 방어)
    assert data["temperatures"][1]["reading_celsius"] == 55
    assert data["fans"][0]["reading"] == 8000 and data["fans"][0]["reading_units"] == "RPM"
    # ReadingRPM fallback
    assert data["fans"][1]["reading"] == 7800


def test_thermal_subsystem_fallback(monkeypatch) -> None:
    """/Thermal 404 → /ThermalSubsystem (DMTF 2020.4) fallback."""
    extra = {
        "Chassis/X/Thermal": (404, None, None),
        "Chassis/X/ThermalSubsystem": (200, {
            "ThermalMetrics": {"@odata.id": "/redfish/v1/Chassis/X/ThermalSubsystem/ThermalMetrics"},
            "Fans": {"@odata.id": "/redfish/v1/Chassis/X/ThermalSubsystem/Fans"},
        }, None),
        "Chassis/X/ThermalSubsystem/ThermalMetrics": (200, {
            "TemperatureReadingsCelsius": [
                {"DeviceName": "Inlet", "Reading": 21, "Status": {"Health": "OK"}},
            ],
        }, None),
        "Chassis/X/ThermalSubsystem/Fans": (200, {"Members": [
            {"@odata.id": "/redfish/v1/Chassis/X/ThermalSubsystem/Fans/0"},
        ]}, None),
        "Chassis/X/ThermalSubsystem/Fans/0": (200, {
            "Name": "Fan A", "SpeedPercent": {"Reading": 35}, "Status": {"Health": "OK"},
        }, None),
    }
    _patch(monkeypatch, extra)
    data, errs = rg.gather_thermal("10.0.0.1", "/redfish/v1/Chassis/X", *CREDS)
    assert data["temperatures"][0]["name"] == "Inlet"
    assert data["temperatures"][0]["reading_celsius"] == 21
    assert data["fans"][0]["reading"] == 35 and data["fans"][0]["reading_units"] == "Percent"


def test_thermal_absent_returns_empty(monkeypatch) -> None:
    """/Thermal + /ThermalSubsystem 모두 404 → {} (graceful, no error noise)."""
    _patch(monkeypatch)
    data, errs = rg.gather_thermal("10.0.0.1", "/redfish/v1/Chassis/Nope", *CREDS)
    assert data == {}
    assert errs == []  # 404 는 noise 차단


def test_thermal_no_uri(monkeypatch) -> None:
    _patch(monkeypatch)
    data, errs = rg.gather_thermal("10.0.0.1", "", *CREDS)
    assert data == {} and errs and errs[0]["section"] == "thermal"


# ── gather_boot ─────────────────────────────────────────────────────────────


def test_boot_order_extracted(monkeypatch) -> None:
    _patch(monkeypatch)
    data, errs = rg.gather_boot("10.0.0.1", "/redfish/v1/Systems/Partition0", *CREDS)
    assert data["boot_order"] == ["Boot0001", "Boot0002", "Boot0003"]
    assert data["boot_source_override_enabled"] == "Once"
    assert data["boot_source_override_target"] == "Pxe"
    assert data["boot_source_override_mode"] == "UEFI"


def test_boot_absent_returns_empty(monkeypatch) -> None:
    """Boot 객체 미노출 → {} (graceful)."""
    _patch(monkeypatch)
    data, errs = rg.gather_boot("10.0.0.1", "/redfish/v1/Systems/Partition1", *CREDS)
    assert data == {} and errs == []


def test_boot_nonlist_bootorder_defended(monkeypatch) -> None:
    """BootOrder 가 비-list (오염) → boot_order == [] (crash 방어)."""
    extra = {"Systems/Bad": (200, {"Boot": {"BootOrder": "not-a-list"}}, None)}
    _patch(monkeypatch, extra)
    data, errs = rg.gather_boot("10.0.0.1", "/redfish/v1/Systems/Bad", *CREDS)
    assert data["boot_order"] == []


# ── gather_manager_logs ─────────────────────────────────────────────────────


def test_manager_logs_extracted(monkeypatch) -> None:
    _patch(monkeypatch)
    logs, errs = rg.gather_manager_logs("10.0.0.1", "/redfish/v1/Managers/RMC", *CREDS)
    assert errs == []
    ids = [l["id"] for l in logs]
    assert ids == ["IML", "IEL"]
    assert logs[0]["name"] == "Integrated Management Log"
    assert logs[0]["overwrite_policy"] == "WrapsWhenFull"
    assert logs[0]["service_enabled"] is True


def test_manager_logs_absent_returns_empty(monkeypatch) -> None:
    """LogServices 링크 미노출 → [] (graceful)."""
    extra = {"Managers/NoLogs": (200, {"Id": "NoLogs"}, None)}
    _patch(monkeypatch, extra)
    logs, errs = rg.gather_manager_logs("10.0.0.1", "/redfish/v1/Managers/NoLogs", *CREDS)
    assert logs == [] and errs == []


# ── gather_composition_service ──────────────────────────────────────────────


def test_composition_service_resource_blocks(monkeypatch) -> None:
    _patch(monkeypatch)
    comp, errs = rg.gather_composition_service("10.0.0.1", _full_service_root(), *CREDS)
    assert errs == []
    assert comp["enabled"] is True
    assert comp["resource_block_count"] == 2
    b0 = comp["resource_blocks"][0]
    assert b0["id"] == "Block0"
    assert b0["processor_count"] == 4
    assert b0["memory_count"] == 8
    assert b0["composition_state"] == "Composed"
    # 설명 모델: 각 ResourceBlock 은 하나의 chassis 에 대응
    assert b0["chassis"] == ["/redfish/v1/Chassis/Base"]
    assert b0["computer_systems"] == ["/redfish/v1/Systems/Partition0"]
    assert b0["resource_block_types"] == ["Compute"]


def test_composition_absent_returns_none(monkeypatch) -> None:
    """ServiceRoot 에 CompositionService 링크 없음 → None (graceful, 13 vendor 안전)."""
    _patch(monkeypatch)
    sr = {"Systems": {"@odata.id": "/redfish/v1/Systems"}}  # no CompositionService
    comp, errs = rg.gather_composition_service("10.0.0.1", sr, *CREDS)
    assert comp is None and errs == []


# ── gather_fabrics ──────────────────────────────────────────────────────────


def test_fabrics_flexgrid_switches_endpoints(monkeypatch) -> None:
    _patch(monkeypatch)
    fabrics, errs = rg.gather_fabrics("10.0.0.1", _full_service_root(), *CREDS)
    assert errs == []
    assert len(fabrics) == 1
    fg = fabrics[0]
    assert fg["id"] == "FlexGrid"
    assert fg["switch_count"] == 2 and len(fg["switches"]) == 2
    assert fg["endpoint_count"] == 1 and len(fg["endpoints"]) == 1
    assert fg["switches"][0]["switch_type"] == "PCIe"
    assert fg["endpoints"][0]["endpoint_protocol"] == "PCIe"


def test_fabrics_absent_returns_none(monkeypatch) -> None:
    """ServiceRoot 에 Fabrics 링크 없음 → None (graceful)."""
    _patch(monkeypatch)
    sr = {"Systems": {"@odata.id": "/redfish/v1/Systems"}}
    fabrics, errs = rg.gather_fabrics("10.0.0.1", sr, *CREDS)
    assert fabrics is None and errs == []


# ── 통합: _collect_multi_node_topology 전체 ─────────────────────────────────


def test_topology_full_includes_all_new_components(monkeypatch) -> None:
    """end-to-end — partitions[].boot / chassis[].thermal / managers[].log_services /
    composition / fabrics + summary 신 카운트 모두 노출."""
    _patch(monkeypatch)
    result = rg._collect_multi_node_topology(
        "10.0.0.1", "hpe", _full_service_root(), *CREDS, manager_layout="rmc_primary")
    assert result is not None
    # partitions[].boot
    p0 = next(p for p in result["partitions"] if p["id"] == "Partition0")
    assert p0["boot"]["boot_order"] == ["Boot0001", "Boot0002", "Boot0003"]
    p1 = next(p for p in result["partitions"] if p["id"] == "Partition1")
    assert p1["boot"] == {}  # Boot 미노출 partition
    # chassis[].thermal
    base = next(c for c in result["chassis"] if c["id"] == "Base")
    assert base["thermal"]["temperatures"][0]["reading_celsius"] == 22
    assert "power" in base  # 기존 키 보존 (회귀 방어)
    # managers[].log_services
    rmc = next(m for m in result["managers"] if m["id"] == "RMC")
    assert [l["id"] for l in rmc["log_services"]] == ["IML", "IEL"]
    assert rmc["bmc"]["name"] == "RMC"  # 기존 라벨 보존
    # composition
    assert result["composition"]["resource_block_count"] == 2
    # fabrics
    assert result["fabrics"][0]["id"] == "FlexGrid"
    # summary 신 카운트
    assert result["summary"]["resource_block_count"] == 2
    assert result["summary"]["fabric_count"] == 1
    # 기존 summary 키 보존
    assert result["summary"]["partition_count"] == 2
    assert result["summary"]["representative_partition"] == "Partition0"


def test_topology_without_new_links_is_backward_compatible(monkeypatch) -> None:
    """ServiceRoot 에 Fabrics/CompositionService 링크 없음 (= 기존 CSUS 시나리오) →
    composition None / fabrics None / summary 카운트 0. 13 vendor / 기존 동작 영향 0."""
    _patch(monkeypatch)
    sr = {
        "Systems":  {"@odata.id": "/redfish/v1/Systems"},
        "Managers": {"@odata.id": "/redfish/v1/Managers"},
        "Chassis":  {"@odata.id": "/redfish/v1/Chassis"},
    }
    result = rg._collect_multi_node_topology(
        "10.0.0.1", "hpe", sr, *CREDS, manager_layout="rmc_primary")
    assert result["composition"] is None
    assert result["fabrics"] is None
    assert result["summary"]["resource_block_count"] == 0
    assert result["summary"]["fabric_count"] == 0
    # 기존 수집은 그대로
    assert result["summary"]["partition_count"] == 2
    # chassis thermal / partition boot 은 여전히 수집됨 (sub-resource 레벨)
    base = next(c for c in result["chassis"] if c["id"] == "Base")
    assert "thermal" in base


def test_topology_layout_none_still_none(monkeypatch) -> None:
    """manager_layout=None → None (신 컬렉터 추가 후에도 13 vendor 영향 0 불변)."""
    _patch(monkeypatch)
    result = rg._collect_multi_node_topology(
        "10.0.0.1", "hpe", _full_service_root(), *CREDS, manager_layout=None)
    assert result is None


# ── review fix 회귀 (cycle 2026-06-09) ──────────────────────────────────────


def test_chassis_get_fail_appends_member_without_doomed_subcalls(monkeypatch) -> None:
    """비-404 chassis GET 실패 → 멤버 append (chassis_count 보존) + power/thermal={} +
    중복 Power/Thermal error noise 없음 (review LOW fix)."""
    extra = {
        "Chassis": (200, {"Members": [
            {"@odata.id": "/redfish/v1/Chassis/Base"},
            {"@odata.id": "/redfish/v1/Chassis/Broken"},
        ]}, None),
        "Chassis/Broken": (500, None, "Internal Server Error"),
    }
    _patch(monkeypatch, extra)
    out = rg.gather_chassis_multi("10.0.0.1", "/redfish/v1/Chassis", *CREDS)
    ids = [c["id"] for c in out["chassis"]]
    assert "Broken" in ids  # append-on-fail (멤버 노출 — chassis_count 보존)
    broken = next(c for c in out["chassis"] if c["id"] == "Broken")
    assert broken["power"] == {} and broken["thermal"] == {}
    broken_errs = [e for e in out["errors"] if "Broken" in (e.get("message") or "")]
    assert len(broken_errs) == 1  # 정확히 'GET 실패' 1건 — doomed sub-GET error 없음
    assert not any("정보 실패" in (e.get("message") or "") for e in out["errors"])


def test_manager_label_role_consistent_for_nondocumented_ids(monkeypatch) -> None:
    """비-documented manager ID (Managers/1, Self, 2) → 첫 Manager 만 RMC/primary,
    나머지 generic/secondary. name/role 일치 + 단일 RMC (review genuine_bug_final fix).

    구: layout-default 가 substring 미매치 manager 전부 'RMC' 로 오라벨 + role=None (모순).
    """
    extra = {
        "Managers": (200, {"Members": [
            {"@odata.id": "/redfish/v1/Managers/1"},
            {"@odata.id": "/redfish/v1/Managers/Self"},
            {"@odata.id": "/redfish/v1/Managers/2"},
        ]}, None),
        "Managers/1":    (200, {"Id": "1", "FirmwareVersion": "3.0", "Status": {"Health": "OK"}}, None),
        "Managers/Self": (200, {"Id": "Self", "FirmwareVersion": "3.0", "Status": {"Health": "OK"}}, None),
        "Managers/2":    (200, {"Id": "2", "FirmwareVersion": "3.0", "Status": {"Health": "OK"}}, None),
    }
    _patch(monkeypatch, extra)
    out = rg.gather_managers_multi(
        "10.0.0.1", "/redfish/v1/Managers", "hpe", *CREDS, manager_layout="rmc_primary")
    mgrs = out["managers"]
    # 첫 manager 만 RMC/primary
    assert mgrs[0]["bmc"]["name"] == "RMC" and mgrs[0]["role"] == "primary"
    # 단일 RMC (다중 오라벨 방지)
    assert sum(1 for m in mgrs if m["bmc"]["name"] == "RMC") == 1
    for m in mgrs[1:]:
        assert m["role"] == "secondary"
        assert m["bmc"]["name"] == "iLO"  # hpe generic fallback (bmc_names['hpe'])
    # name/role 모순(RMC인데 비-primary) 부재 — 전 manager
    assert not any(m["bmc"]["name"] == "RMC" and m["role"] != "primary" for m in mgrs)


def test_manager_name_role_consistent_when_body_id_differs_from_uri_segment(monkeypatch) -> None:
    """응답 body Id ≠ URI 마지막 segment 인 경우에도 name/role 모순 불가 (review fix).

    DMTF 는 Manager.Id 와 @odata.id segment 불일치를 허용. 구: name 은 body Id 로,
    role 는 URI segment 로 분류 → 서로 다른 source 라 모순 가능 (예: name='RMC', role='secondary').
    fix: 두 분류 모두 동일 id(URI segment m['id']) 사용 → name=='RMC' iff role=='primary'.
    """
    extra = {
        "Managers": (200, {"Members": [
            {"@odata.id": "/redfish/v1/Managers/1"},   # body Id = iLO.Embedded.1 (divergent)
            {"@odata.id": "/redfish/v1/Managers/2"},   # body Id = RMC (divergent)
        ]}, None),
        "Managers/1": (200, {"Id": "iLO.Embedded.1", "FirmwareVersion": "2.85", "Status": {"Health": "OK"}}, None),
        "Managers/2": (200, {"Id": "RMC", "FirmwareVersion": "3.0", "Status": {"Health": "OK"}}, None),
    }
    _patch(monkeypatch, extra)
    out = rg.gather_managers_multi(
        "10.0.0.1", "/redfish/v1/Managers", "hpe", *CREDS, manager_layout="rmc_primary")
    for m in out["managers"]:
        name, role = m["bmc"]["name"], m["role"]
        # 핵심 불변식: name=='RMC' ⇔ role=='primary' (서로 모순 불가)
        assert (name == "RMC") == (role == "primary"), \
            f"name/role 모순: id={m['id']} name={name} role={role}"
    # 단일 primary (다중 primary 오분류 방지)
    assert sum(1 for m in out["managers"] if m["role"] == "primary") == 1


def test_manager_documented_ids_unchanged(monkeypatch) -> None:
    """documented ID (RMC/PDHC0/Bay1.iLO5) 는 fix 후에도 동일 (회귀 차단)."""
    extra = {
        "Managers": (200, {"Members": [
            {"@odata.id": "/redfish/v1/Managers/RMC"},
            {"@odata.id": "/redfish/v1/Managers/PDHC0"},
            {"@odata.id": "/redfish/v1/Managers/Bay1.iLO5"},
        ]}, None),
        "Managers/PDHC0":     (200, {"Id": "PDHC0", "FirmwareVersion": "3.10.00", "Status": {"Health": "OK"}}, None),
        "Managers/Bay1.iLO5": (200, {"Id": "Bay1.iLO5", "FirmwareVersion": "2.85", "Status": {"Health": "OK"}}, None),
    }
    _patch(monkeypatch, extra)
    out = rg.gather_managers_multi(
        "10.0.0.1", "/redfish/v1/Managers", "hpe", *CREDS, manager_layout="rmc_primary")
    by = {m["id"]: m for m in out["managers"]}
    assert by["RMC"]["bmc"]["name"] == "RMC" and by["RMC"]["role"] == "primary"
    assert by["PDHC0"]["bmc"]["name"] == "PDHC" and by["PDHC0"]["role"] == "secondary"
    assert by["Bay1.iLO5"]["bmc"]["name"] == "iLO" and by["Bay1.iLO5"]["role"] == "secondary"


def test_composition_malformed_200_enabled_none(monkeypatch) -> None:
    """CompositionService 가 200 이지만 비-dict(null) body → enabled=None (정직한 unknown).

    구: bool(_safe(None, 'ServiceEnabled', default=True)) → True (오해 소지). fix → None.
    """
    extra = {"CompositionService": (200, None, None)}  # null body @ 200
    _patch(monkeypatch, extra)
    comp, errs = rg.gather_composition_service("10.0.0.1", _full_service_root(), *CREDS)
    assert comp is not None
    assert comp["enabled"] is None
    assert comp["resource_block_count"] == 0
