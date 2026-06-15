"""HPE CSUS 3200 실 미러 검수 수정 회귀 (2026-06-15, CSUS mirror audit).

실 장비(C:/github/서버mock데이터/HPE_CSUS3200, 4 노드) raw 기준으로 발견·수정한
5건의 회귀 차단. lab 부재 합성이 아니라 *실 미러가 노출한 구조*를 그대로 재현한다:
  - Chassis 컬렉션 첫 멤버 = 집계용 RackGroup(Power/Thermal/NetworkAdapters 부재)
  - 실제 compute chassis = r001u01 (PowerSubsystem/ThermalSubsystem/NetworkAdapters 보유)
  - System.Links.Chassis = [r001u01]  (compute chassis 의 정본 링크)
  - FC HBA(HPE SN1100Q): Port.FibreChannel.AssociatedWorldWideNames + NDF.FibreChannel.WWPN,
    NDF 는 Links.PhysicalPortAssignment 없이 Links.PCIeFunction 만 → ID(NDF.Id==Port.Id) 매칭
  - RMC: Oem.Hpe.Firmware 부재 (RackManager — iLO 아님)

수정:
  CSUS-R1  : _resolve_system_chassis_uri → power/thermal/network_adapters/system 이 compute chassis 사용
  CSUS-FC1 : NDF↔Port ID 매칭 fallback + _classify_port_protocol NDF.wwpn → FC
  CSUS-FC2 : Port.FibreChannel.AssociatedWorldWideNames 읽기
  CSUS-R3  : gather_systems_multi product_hint/per-partition chassis 전달
  CSUS-R4  : bmc.oem.ilo_version 의 Manager.Model fallback 제거
  CSUS-R5  : _classify_chassis_kind 가 RackGroup/Rack ChassisType 인식
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


def _patch(monkeypatch, rmap):
    """rmap = {path(_p 정규화): (status, body, err)}. 부재 path → 404 graceful."""
    def fake_get(bmc_ip, path, username, password, timeout, verify_ssl):
        return rmap.get(path, (404, None, "HTTP 404: Not Found"))
    monkeypatch.setattr(rg, "_get", fake_get)


# ── CSUS-R1: System.Links.Chassis 로 compute chassis 해석 ─────────────────────

def test_resolve_system_chassis_prefers_links_chassis(monkeypatch):
    """System.Links.Chassis[0](r001u01) 가 default(RackGroup)보다 우선."""
    _patch(monkeypatch, {
        "Systems/Partition0": (200, {
            "Id": "Partition0",
            "Links": {"Chassis": [{"@odata.id": "/redfish/v1/Chassis/r001u01"}]},
        }, None),
    })
    out = rg._resolve_system_chassis_uri(
        "ip", "/redfish/v1/Systems/Partition0", "/redfish/v1/Chassis/RackGroup", *CREDS)
    assert out == "/redfish/v1/Chassis/r001u01"


def test_resolve_system_chassis_falls_back_when_no_link(monkeypatch):
    """Links.Chassis 부재 → default_chassis_uri 보존 (단일 chassis vendor 동작 불변)."""
    _patch(monkeypatch, {"Systems/1": (200, {"Id": "1"}, None)})
    out = rg._resolve_system_chassis_uri(
        "ip", "/redfish/v1/Systems/1", "/redfish/v1/Chassis/1", *CREDS)
    assert out == "/redfish/v1/Chassis/1"


def test_resolve_system_chassis_falls_back_on_get_fail(monkeypatch):
    _patch(monkeypatch, {})  # system GET → 404
    out = rg._resolve_system_chassis_uri(
        "ip", "/redfish/v1/Systems/X", "/redfish/v1/Chassis/Default", *CREDS)
    assert out == "/redfish/v1/Chassis/Default"


def test_collect_all_sections_power_thermal_from_compute_chassis(monkeypatch):
    """RackGroup(빈) 이 첫 chassis 여도 power/thermal/network_adapters 는 r001u01 에서 수집.

    구 버그: data.power={}·data.thermal={} 인데 collected=success (false-success).
    """
    rmap = {
        # System with Links.Chassis -> r001u01
        "Systems/Partition0": (200, {
            "Id": "Partition0",
            "Status": {"Health": "OK", "State": "Enabled"}, "PowerState": "On",
            "Links": {"Chassis": [{"@odata.id": "/redfish/v1/Chassis/r001u01"}]},
        }, None),
        # RackGroup (default first member) — Power/Thermal/NetworkAdapters 모두 404 (부재)
        # r001u01 PowerSubsystem (legacy /Power 404 → PowerSubsystem)
        "Chassis/r001u01/PowerSubsystem": (200, {
            "PowerSupplies": {"@odata.id": "/redfish/v1/Chassis/r001u01/PowerSubsystem/PowerSupplies"},
        }, None),
        "Chassis/r001u01/PowerSubsystem/PowerSupplies": (200, {
            "Members": [{"@odata.id": "/redfish/v1/Chassis/r001u01/PowerSubsystem/PowerSupplies/0"}],
        }, None),
        "Chassis/r001u01/PowerSubsystem/PowerSupplies/0": (200, {
            "Name": "psu0", "Manufacturer": "Artesyn", "SerialNumber": "R65897002CBJP",
            "Status": {"Health": "OK", "State": "Enabled"},
        }, None),
        # r001u01 ThermalSubsystem (legacy /Thermal 404 → ThermalSubsystem)
        "Chassis/r001u01/ThermalSubsystem": (200, {
            "ThermalMetrics": {"@odata.id": "/redfish/v1/Chassis/r001u01/ThermalSubsystem/ThermalMetrics"},
            "Fans": {"@odata.id": "/redfish/v1/Chassis/r001u01/ThermalSubsystem/Fans"},
        }, None),
        "Chassis/r001u01/ThermalSubsystem/ThermalMetrics": (200, {
            "TemperatureReadingsCelsius": [
                {"DeviceName": "P0_TEMP", "Reading": 39.39, "PhysicalContext": "CPU"},
            ],
        }, None),
        "Chassis/r001u01/ThermalSubsystem/Fans": (200, {"Members": []}, None),
        # network_adapters: empty collection but present (200) so not unsupported
        "Chassis/r001u01/NetworkAdapters": (200, {"Members": []}, None),
    }
    _patch(monkeypatch, rmap)
    all_errors, collected, failed, unsupported = [], [], [], []
    data = rg._collect_all_sections(
        "ip", "hpe", "/redfish/v1/Systems/Partition0", None,
        "/redfish/v1/Chassis/RackGroup", *CREDS,
        all_errors, collected, failed, unsupported)
    # power/thermal 가 compute chassis 에서 실제 데이터로 채워짐 (false-success 아님)
    assert data["power"].get("power_supplies"), "power 가 r001u01 에서 수집돼야 함"
    assert data["power"]["power_supplies"][0]["serial"] == "R65897002CBJP"
    assert data["thermal"].get("temperatures"), "thermal 이 r001u01 에서 수집돼야 함"
    # network_adapters 는 200-빈 컬렉션 → unsupported 아님 (collected)
    assert "network_adapters" not in unsupported


# ── CSUS-FC1/FC2: FC HBA WWPN 추출 ──────────────────────────────────────────

def _fc_hba_chassis_map():
    """HPE SN1100Q FC HBA — 실 미러 구조 재현 (Port.AssociatedWorldWideNames + NDF id-join)."""
    return {
        "Chassis/r001u01/NetworkAdapters": (200, {
            "Members": [{"@odata.id": "/redfish/v1/Chassis/r001u01/NetworkAdapters/PCIeCard10"}],
        }, None),
        "Chassis/r001u01/NetworkAdapters/PCIeCard10": (200, {
            "Id": "PCIeCard10", "Name": "FC HBA",
            "Model": "HPE SN1100Q 16Gb 2P FC HBA", "Manufacturer": "HPE",
            "PartNumber": "P9D94A", "SerialNumber": "MY550301NK",
            "Ports": {"@odata.id": "/redfish/v1/Chassis/r001u01/NetworkAdapters/PCIeCard10/Ports"},
            "NetworkDeviceFunctions": {"@odata.id": "/redfish/v1/Chassis/r001u01/NetworkAdapters/PCIeCard10/NetworkDeviceFunctions"},
        }, None),
        "Chassis/r001u01/NetworkAdapters/PCIeCard10/Ports": (200, {
            "Members": [{"@odata.id": "/redfish/v1/Chassis/r001u01/NetworkAdapters/PCIeCard10/Ports/PCIeCard10Port1"}],
        }, None),
        # Port: PortProtocol/PortType 없음, FibreChannel.AssociatedWorldWideNames 만 (실 미러)
        "Chassis/r001u01/NetworkAdapters/PCIeCard10/Ports/PCIeCard10Port1": (200, {
            "Id": "PCIeCard10Port1", "Name": "io_slot10 Port 1",
            "FibreChannel": {"AssociatedWorldWideNames": ["51:40:2E:C0:20:82:C2:2C"]},
        }, None),
        "Chassis/r001u01/NetworkAdapters/PCIeCard10/NetworkDeviceFunctions": (200, {
            "Members": [{"@odata.id": "/redfish/v1/Chassis/r001u01/NetworkAdapters/PCIeCard10/NetworkDeviceFunctions/PCIeCard10Port1"}],
        }, None),
        # NDF: NetDevFuncType 없음, Links.PCIeFunction 만 (PhysicalPortAssignment 부재), FibreChannel.WWPN
        "Chassis/r001u01/NetworkAdapters/PCIeCard10/NetworkDeviceFunctions/PCIeCard10Port1": (200, {
            "Id": "PCIeCard10Port1",
            "FibreChannel": {"WWPN": "51:40:2E:C0:20:82:C2:2C", "WWNN": None},
            "Links": {"PCIeFunction": {"@odata.id": "/redfish/v1/x/PCIeFunctions/NetworkDevice"}},
        }, None),
    }


def test_fc_hba_wwpn_extracted_via_ndf_id_join(monkeypatch):
    """NDF 가 PhysicalPortAssignment 없이 PCIeFunction 만 노출 → ID 매칭으로 WWPN join."""
    _patch(monkeypatch, _fc_hba_chassis_map())
    out, errs = rg.gather_network_adapters_chassis(
        "ip", "/redfish/v1/Chassis/r001u01", *CREDS)
    assert len(out["fc_hbas"]) == 1
    hba = out["fc_hbas"][0]
    assert hba["wwpn"] == "51:40:2e:c0:20:82:c2:2c", "WWPN 소실되면 안 됨 (NDF id-join)"
    assert hba["port_type"] == "FibreChannel"
    assert hba["model"] == "HPE SN1100Q 16Gb 2P FC HBA"
    # port 의 associated_address 도 AssociatedWorldWideNames 에서 (소문자)
    assert out["ports"][0]["associated_address"] == "51:40:2e:c0:20:82:c2:2c"
    assert out["ports"][0]["port_type"] == "FibreChannel"


def test_classify_port_protocol_ndf_wwpn_is_fc():
    """NDF.wwpn 존재 → FibreChannel (NetDevFuncType/PortProtocol 부재 펌웨어)."""
    ndf = {"func_type": None, "net_dev_tech": None, "wwpn": "51:40:2e:c0:20:82:c2:2c",
           "wwnn": None, "node_guid": None, "port_guid": None}
    assert rg._classify_port_protocol(None, None, ndf, None) == "FibreChannel"


def test_classify_port_protocol_ndf_guid_not_forced_ib():
    """ConnectX VPI 안전성: NDF 에 GUID 만 있고 ethernet func_type 이면 IB 로 강제 분류 안 함."""
    ndf = {"func_type": "Ethernet", "net_dev_tech": "Ethernet", "wwpn": None,
           "wwnn": None, "node_guid": "0x0002c903", "port_guid": "0x0002c903"}
    # GUID 가 있어도 Ethernet 으로 분류돼야 함 (mac fold-in 보존)
    assert rg._classify_port_protocol(None, None, ndf, None) == "Ethernet"


# ── CSUS-R3: multi_node partition system manufacturer/model ──────────────────

def test_systems_multi_passes_product_hint(monkeypatch):
    """gather_systems_multi 가 product_hint + per-partition chassis 로 model/manufacturer 채움."""
    rmap = {
        "Systems": (200, {"Members": [{"@odata.id": "/redfish/v1/Systems/Partition0"}]}, None),
        # Partition0: Manufacturer/Model 부재 (실 미러 — partition system 은 비어 있음) + Links.Chassis
        "Systems/Partition0": (200, {
            "Id": "Partition0",
            "Status": {"Health": "OK", "State": "Enabled"}, "PowerState": "On",
            "Links": {"Chassis": [{"@odata.id": "/redfish/v1/Chassis/r001u01"}]},
        }, None),
        # compute chassis 에 Manufacturer 존재
        "Chassis/r001u01": (200, {"Id": "r001u01", "Manufacturer": "HPE",
                                  "Model": "Compute Scale-up Server 3200, 4S XNC Base Chassis"}, None),
    }
    _patch(monkeypatch, rmap)
    res = rg.gather_systems_multi(
        "ip", "/redfish/v1/Systems", "hpe", *CREDS,
        product_hint="Compute Scale-up Server 3200")
    p0 = res["partitions"][0]["system"]
    assert p0["manufacturer"] == "HPE", "partition.system.manufacturer 가 chassis fallback 으로 채워져야"
    # product_hint(깨끗한 모델명)가 우선
    assert p0["model"] == "Compute Scale-up Server 3200"


# ── CSUS-R4: bmc.oem.ilo_version Model fallback 제거 ─────────────────────────

def test_bmc_ilo_version_no_model_fallback_for_rmc(monkeypatch):
    """RMC(Oem.Hpe.Firmware 부재) → ilo_version=None (구: Manager.Model 문자열)."""
    _patch(monkeypatch, {
        "Managers/RMC": (200, {
            "Id": "RMC", "FirmwareVersion": "1.75.108-20260408_164726",
            "Model": "Compute Scale-up Server 3200, 4S XNC Base Chassis",
            "ManagerType": "RackManager",
            "Status": {"Health": "OK", "State": "Enabled"},
            "Oem": {"Hpe": {"@odata.type": "#HpeH3ManagerRmc"}},  # Firmware 키 없음
        }, None),
    })
    out, errs = rg.gather_bmc("ip", "/redfish/v1/Managers/RMC", "hpe", *CREDS)
    assert out["oem"]["ilo_version"] is None, "RMC 는 Model 을 ilo_version 으로 쓰지 않음"
    assert out["firmware_version"] == "1.75.108-20260408_164726"  # 실제 펌웨어는 표준 필드


def test_bmc_ilo_version_preserved_for_real_ilo(monkeypatch):
    """실 iLO(VersionString 보유) → ilo_version 보존 (회귀 안전)."""
    _patch(monkeypatch, {
        "Managers/1": (200, {
            "Id": "1", "FirmwareVersion": "iLO 6 v1.73", "Model": "iLO 6",
            "Oem": {"Hpe": {"Firmware": {"Current": {"VersionString": "1.73"}}}},
        }, None),
    })
    out, errs = rg.gather_bmc("ip", "/redfish/v1/Managers/1", "hpe", *CREDS)
    assert out["oem"]["ilo_version"] == "1.73"


# ── CSUS-R5: chassis kind RackGroup/Rack ────────────────────────────────────

def test_classify_chassis_kind_rackgroup_rack():
    assert rg._classify_chassis_kind("/redfish/v1/Chassis/RackGroup", "RackGroup",
                                     {"ChassisType": "RackGroup"}) == "rackgroup"
    assert rg._classify_chassis_kind("/redfish/v1/Chassis/Rack1", "Rack1",
                                     {"ChassisType": "Rack"}) == "rack"
    # RackMount 는 기존대로
    assert rg._classify_chassis_kind("/redfish/v1/Chassis/r001u01", "r001u01",
                                     {"ChassisType": "RackMount"}) == "rackmount"


# ── CSUS-R6: port_count fallback (ControllerCapabilities 부재) ────────────────

def test_port_count_fallback_to_actual_ports(monkeypatch):
    """ControllerCapabilities.NetworkPortCount 부재 → 실제 Ports 수로 port_count 보정."""
    A = "Chassis/r001u01/NetworkAdapters/PCIeCard10"  # _p 정규화 key
    U = "/redfish/v1/" + A                            # @odata.id value
    _patch(monkeypatch, {
        "Chassis/r001u01/NetworkAdapters": (200, {"Members": [{"@odata.id": U}]}, None),
        A: (200, {
            "Id": "PCIeCard10", "Model": "HPE SN1100Q 16Gb 2P FC HBA", "Manufacturer": "HPE",
            "Ports": {"@odata.id": U + "/Ports"},
            # Controllers 없음 → port_count 산출 0
        }, None),
        A + "/Ports": (200, {"Members": [
            {"@odata.id": U + "/Ports/PCIeCard10Port1"},
            {"@odata.id": U + "/Ports/PCIeCard10Port2"},
        ]}, None),
        A + "/Ports/PCIeCard10Port1": (200, {
            "Id": "P1", "FibreChannel": {"AssociatedWorldWideNames": ["51:40:2e:c0:20:82:c2:2c"]}}, None),
        A + "/Ports/PCIeCard10Port2": (200, {
            "Id": "P2", "FibreChannel": {"AssociatedWorldWideNames": ["51:40:2e:c0:20:82:c2:2e"]}}, None),
    })
    out, errs = rg.gather_network_adapters_chassis("ip", "/redfish/v1/Chassis/r001u01", *CREDS)
    assert out["adapters"][0]["port_count"] == 2, "port_count 가 실제 ports(2)로 보정돼야"


# ── CSUS-R9/R10: PSU Version + 소비전력(InputPowerWatts 합) ────────────────────

def test_power_subsystem_psu_version_and_consumed(monkeypatch):
    """PSU firmware_version=Version fallback + power_consumed_watts=PSU InputPowerWatts 합."""
    PS = "Chassis/r001u01/PowerSubsystem"  # _p 정규화 key prefix
    U = "/redfish/v1/" + PS
    _patch(monkeypatch, {
        # /Power 404 → PowerSubsystem 경로 + /EnvironmentMetrics 404
        PS: (200, {"PowerSupplies": {"@odata.id": U + "/PowerSupplies"}}, None),
        PS + "/PowerSupplies": (200, {"Members": [
            {"@odata.id": U + "/PowerSupplies/0"}, {"@odata.id": U + "/PowerSupplies/1"}]}, None),
        PS + "/PowerSupplies/0": (200, {
            "Name": "psu0", "Manufacturer": "Artesyn", "SerialNumber": "R65897002CBJP",
            "Version": "Release -0005",  # FirmwareVersion 부재
            "Metrics": {"@odata.id": U + "/PowerSupplies/0/Metrics"},
            "Status": {"Health": "OK", "State": "Enabled"}}, None),
        PS + "/PowerSupplies/1": (200, {
            "Name": "psu1", "Manufacturer": "Artesyn", "SerialNumber": "R65898004UBJP",
            "Version": "Release -0005",
            "Metrics": {"@odata.id": U + "/PowerSupplies/1/Metrics"},
            "Status": {"Health": "OK", "State": "Enabled"}}, None),
        PS + "/PowerSupplies/0/Metrics": (200, {"InputPowerWatts": {"Reading": 199.0}}, None),
        PS + "/PowerSupplies/1/Metrics": (200, {"InputPowerWatts": {"Reading": 172.0}}, None),
    })
    out, errs = rg.gather_power("ip", "/redfish/v1/Chassis/r001u01", *CREDS)
    assert out["power_supplies"][0]["firmware_version"] == "Release -0005"
    # 199 + 172 = 371 (PSU 입력전력 합)
    assert out["power_control"]["power_consumed_watts"] == 371


def test_power_consumed_prefers_environment_metrics(monkeypatch):
    """EnvironmentMetrics 가 있으면 그 값 우선 (PSU 합 fallback 미발동 — 회귀 안전)."""
    PS = "Chassis/C/PowerSubsystem"  # _p 정규화 key prefix
    U = "/redfish/v1/" + PS
    _patch(monkeypatch, {
        PS: (200, {"PowerSupplies": {"@odata.id": U + "/PowerSupplies"}}, None),
        PS + "/PowerSupplies": (200, {"Members": [{"@odata.id": U + "/PowerSupplies/0"}]}, None),
        PS + "/PowerSupplies/0": (200, {
            "Name": "psu0", "Metrics": {"@odata.id": U + "/PowerSupplies/0/Metrics"},
            "Status": {"State": "Enabled"}}, None),
        PS + "/PowerSupplies/0/Metrics": (200, {"InputPowerWatts": {"Reading": 199.0}}, None),
        "Chassis/C/EnvironmentMetrics": (200, {"PowerWatts": {"Reading": 500}}, None),
    })
    out, errs = rg.gather_power("ip", "/redfish/v1/Chassis/C", *CREDS)
    assert out["power_control"]["power_consumed_watts"] == 500  # EnvironmentMetrics 우선


# ── CSUS-R11: fan RPM from Sensors RelatedItem ───────────────────────────────

def test_fan_rpm_from_sensors_related_item(monkeypatch):
    """Fan 리소스에 SpeedPercent 없을 때 Sensors(Rotational).RelatedItem 역참조로 RPM 채움."""
    fan_uri = "/redfish/v1/Chassis/r001u01/ThermalSubsystem/Fans/ChassisFan0"
    _patch(monkeypatch, {
        "Chassis/r001u01/ThermalSubsystem": (200, {
            "Fans": {"@odata.id": "/redfish/v1/Chassis/r001u01/ThermalSubsystem/Fans"}}, None),
        "Chassis/r001u01/ThermalSubsystem/Fans": (200, {"Members": [{"@odata.id": fan_uri}]}, None),
        # Fan: SpeedPercent 없음 → reading null
        "Chassis/r001u01/ThermalSubsystem/Fans/ChassisFan0": (200, {
            "Id": "ChassisFan0", "Name": "chassis_fan0",
            "Status": {"Health": "OK", "State": "Enabled"}}, None),
        # Sensors 컬렉션: fan 센서가 RelatedItem 으로 Fan 역참조
        "Chassis/r001u01/Sensors": (200, {"Members": [
            {"@odata.id": "/redfish/v1/Chassis/r001u01/Sensors/CHASSIS_FAN0"},
            {"@odata.id": "/redfish/v1/Chassis/r001u01/Sensors/P0_TEMP"},  # 비-fan → GET 안 함
        ]}, None),
        "Chassis/r001u01/Sensors/CHASSIS_FAN0": (200, {
            "Reading": 4410.0, "ReadingUnits": "RPM", "ReadingType": "Rotational",
            "RelatedItem": [{"@odata.id": fan_uri}]}, None),
    })
    out, errs = rg.gather_thermal("ip", "/redfish/v1/Chassis/r001u01", *CREDS)
    # gather_thermal: /Thermal 404 → _gather_thermal_subsystem
    assert out["fans"][0]["reading"] == 4410
    assert out["fans"][0]["reading_units"] == "RPM"


# ── CSUS-R12: memory locator ServiceLabel fallback (Slot=0) ──────────────────

def test_memory_locator_servicelabel_when_slot_zero(monkeypatch):
    """DeviceLocator 부재 + MemoryLocation.Slot=0 → ServiceLabel 로 보정."""
    _patch(monkeypatch, {
        "Systems/1/Memory": (200, {"Members": [{"@odata.id": "/redfish/v1/Systems/1/Memory/D0"}]}, None),
        "Systems/1/Memory/D0": (200, {
            "Id": "D0", "Name": "rack1/chassis_u1/cpu0/dimmA0", "CapacityMiB": 32768,
            "MemoryLocation": {"Slot": 0, "Socket": 0},
            "Location": {"PartLocation": {"ServiceLabel": "rack1/chassis_u1/cpu0/dimmA0"}},
            "Status": {"State": "Enabled", "Health": "OK"}}, None),
    })
    out, errs = rg.gather_memory("ip", "/redfish/v1/Systems/1", *CREDS)
    assert out["slots"][0]["locator"] == "rack1/chassis_u1/cpu0/dimmA0"


def test_memory_locator_preserves_meaningful_slot(monkeypatch):
    """MemoryLocation.Slot 이 truthy(예: 3)면 ServiceLabel 무시 — 기존 vendor 동작 불변(회귀 안전)."""
    _patch(monkeypatch, {
        "Systems/1/Memory": (200, {"Members": [{"@odata.id": "/redfish/v1/Systems/1/Memory/D3"}]}, None),
        "Systems/1/Memory/D3": (200, {
            "Id": "D3", "Name": "DIMM3", "CapacityMiB": 16384,
            "MemoryLocation": {"Slot": 3},
            "Location": {"PartLocation": {"ServiceLabel": "should-not-be-used"}},
            "Status": {"State": "Enabled", "Health": "OK"}}, None),
    })
    out, errs = rg.gather_memory("ip", "/redfish/v1/Systems/1", *CREDS)
    assert out["slots"][0]["locator"] == 3


def test_memory_locator_prefers_device_locator(monkeypatch):
    """DeviceLocator 존재 시 최우선 (Dell 등 동작 불변)."""
    _patch(monkeypatch, {
        "Systems/1/Memory": (200, {"Members": [{"@odata.id": "/redfish/v1/Systems/1/Memory/A1"}]}, None),
        "Systems/1/Memory/A1": (200, {
            "Id": "A1", "Name": "DIMM_A1", "CapacityMiB": 16384, "DeviceLocator": "DIMM_A1",
            "MemoryLocation": {"Slot": 0},
            "Location": {"PartLocation": {"ServiceLabel": "ignored"}},
            "Status": {"State": "Enabled", "Health": "OK"}}, None),
    })
    out, errs = rg.gather_memory("ip", "/redfish/v1/Systems/1", *CREDS)
    assert out["slots"][0]["locator"] == "DIMM_A1"


# ── CSUS-R8: Ethernet port_type via Port.Ethernet dict ───────────────────────

def test_classify_ethernet_via_pdata_ethernet_dict():
    """PortProtocol/NetDevFuncType 부재 + Port.Ethernet dict → 'Ethernet' (FC/IB 대칭)."""
    pdata = {"Ethernet": {"AssociatedMACAddresses": ["60:5e:65:21:6e:d4"]}}
    assert rg._classify_port_protocol(None, None, None, pdata) == "Ethernet"
    # Ethernet dict 없으면 여전히 None (회귀 안전)
    assert rg._classify_port_protocol(None, None, None, {"Id": "x"}) is None


def test_mellanox_ethernet_port_classified(monkeypatch):
    """Mellanox host Ethernet 포트(Port.Ethernet 만 노출) port_type=Ethernet + mac fold-in."""
    A = "Chassis/r001u01/NetworkAdapters/PCIeCard1"
    U = "/redfish/v1/" + A
    _patch(monkeypatch, {
        "Chassis/r001u01/NetworkAdapters": (200, {"Members": [{"@odata.id": U}]}, None),
        A: (200, {"Id": "PCIeCard1", "Model": "MCX631102", "Manufacturer": "Mellanox",
                  "Ports": {"@odata.id": U + "/Ports"}}, None),
        A + "/Ports": (200, {"Members": [{"@odata.id": U + "/Ports/Port1"}]}, None),
        A + "/Ports/Port1": (200, {
            "Id": "Port1", "Ethernet": {"AssociatedMACAddresses": ["60:5E:65:21:6E:D4"]}}, None),
    })
    out, errs = rg.gather_network_adapters_chassis("ip", "/redfish/v1/Chassis/r001u01", *CREDS)
    assert out["ports"][0]["port_type"] == "Ethernet"
    assert out["ports"][0]["associated_address"] == "60:5e:65:21:6e:d4"
    assert out["adapters"][0]["mac"] == "60:5e:65:21:6e:d4"  # Ethernet → mac fold-in
    assert out["fc_hbas"] == []  # Ethernet 은 FC 아님


# ── CSUS-R13: FC associated_address = WWPN (not WWNN) ─────────────────────────

def test_fc_associated_address_is_wwpn_not_wwnn(monkeypatch):
    """Port.FibreChannel.AssociatedWorldWideNames=[WWNN, WWPN] 다중 entry → associated_address=WWPN(=NDF.WWPN=fc_hbas.wwpn)."""
    A = "Chassis/r001u01/NetworkAdapters/PCIeCard2"
    U = "/redfish/v1/" + A
    WWNN = "51:40:2e:c0:20:82:ec:65"
    WWPN = "51:40:2e:c0:20:82:ec:64"
    _patch(monkeypatch, {
        "Chassis/r001u01/NetworkAdapters": (200, {"Members": [{"@odata.id": U}]}, None),
        A: (200, {"Id": "PCIeCard2", "Model": "HPE SN1100Q 16Gb 2P FC HBA", "Manufacturer": "HPE",
                  "Ports": {"@odata.id": U + "/Ports"},
                  "NetworkDeviceFunctions": {"@odata.id": U + "/NetworkDeviceFunctions"}}, None),
        A + "/Ports": (200, {"Members": [{"@odata.id": U + "/Ports/PCIeCard2Port1"}]}, None),
        A + "/Ports/PCIeCard2Port1": (200, {
            "Id": "PCIeCard2Port1",
            # 다중 entry: [0]=WWNN, [1]=WWPN (실 미러 ordering)
            "FibreChannel": {"AssociatedWorldWideNames": [WWNN.upper(), WWPN.upper()]}}, None),
        A + "/NetworkDeviceFunctions": (200, {"Members": [{"@odata.id": U + "/NetworkDeviceFunctions/PCIeCard2Port1"}]}, None),
        A + "/NetworkDeviceFunctions/PCIeCard2Port1": (200, {
            "Id": "PCIeCard2Port1",
            "FibreChannel": {"WWPN": WWPN.upper(), "WWNN": WWNN.upper()},
            "Links": {"PCIeFunction": {"@odata.id": "/redfish/v1/x"}}}, None),
    })
    out, errs = rg.gather_network_adapters_chassis("ip", "/redfish/v1/Chassis/r001u01", *CREDS)
    port = out["ports"][0]
    hba = out["fc_hbas"][0]
    assert port["port_type"] == "FibreChannel"
    assert port["associated_address"] == WWPN, "associated_address 가 WWPN 이어야(WWNN 아님)"
    assert hba["wwpn"] == WWPN
    assert port["associated_address"] == hba["wwpn"], "ports.associated_address == fc_hbas.wwpn 일관"


# ── CSUS-R14: power_consumed from TelemetryService TotalPowerConsumedWatts ────

def test_power_consumed_prefers_telemetry(monkeypatch):
    """EnvironmentMetrics 부재 시 장비 권위 TelemetryService TotalPowerConsumedWatts(591) 우선 (PSU 입력합 아님)."""
    PS = "Chassis/r001u01/PowerSubsystem"; U = "/redfish/v1/" + PS
    _patch(monkeypatch, {
        PS: (200, {"PowerSupplies": {"@odata.id": U + "/PowerSupplies"}}, None),
        PS + "/PowerSupplies": (200, {"Members": [{"@odata.id": U + "/PowerSupplies/0"}]}, None),
        PS + "/PowerSupplies/0": (200, {
            "Name": "psu0", "Metrics": {"@odata.id": U + "/PowerSupplies/0/Metrics"},
            "Status": {"State": "Enabled"}}, None),
        PS + "/PowerSupplies/0/Metrics": (200, {"InputPowerWatts": {"Reading": 199.0}}, None),
        # TelemetryService 권위값 (MetricValue 는 문자열)
        "TelemetryService/MetricReports": (200, {"Members": [
            {"@odata.id": "/redfish/v1/TelemetryService/MetricReports/Chassisr001u01_TotalPowerConsumedWatts"}]}, None),
        "TelemetryService/MetricReports/Chassisr001u01_TotalPowerConsumedWatts": (200, {
            "MetricValues": [{"MetricId": "TotalPowerConsumedWatts", "MetricValue": "591.5"}]}, None),
    })
    out, errs = rg.gather_power("ip", "/redfish/v1/Chassis/r001u01", *CREDS)
    assert out["power_control"]["power_consumed_watts"] == 591, "TelemetryService 권위값 우선(PSU 199 아님)"


# ── CSUS-R15: _network_meta 내부 임시키 multi_node 누설 차단 ──────────────────

def test_multi_node_manager_bmc_strips_network_meta(monkeypatch):
    """gather_managers_multi 가 multi_node.managers[].bmc 에서 _network_meta 임시키 제거."""
    _patch(monkeypatch, {
        "Managers": (200, {"Members": [{"@odata.id": "/redfish/v1/Managers/RMC"}]}, None),
        "Managers/RMC": (200, {
            "Id": "RMC", "FirmwareVersion": "1.75.108", "ManagerType": "RackManager",
            "Status": {"Health": "OK", "State": "Enabled"},
            "EthernetInterfaces": {"@odata.id": "/redfish/v1/Managers/RMC/EthernetInterfaces"}}, None),
        "Managers/RMC/EthernetInterfaces": (200, {"Members": [{"@odata.id": "/redfish/v1/Managers/RMC/EthernetInterfaces/1"}]}, None),
        "Managers/RMC/EthernetInterfaces/1": (200, {
            "IPv4Addresses": [{"Address": "10.173.22.101", "Gateway": "10.173.22.1"}],
            "MACAddress": "7C:A6:2A:41:36:92", "NameServers": ["8.8.8.8"]}, None),
    })
    res = rg.gather_managers_multi("ip", "/redfish/v1/Managers", "hpe", *CREDS, manager_layout="rmc_primary")
    bmc = res["managers"][0]["bmc"]
    assert "_network_meta" not in bmc, "multi_node.managers[].bmc 에 내부 임시키 누설 금지"
    assert bmc["ip"] == "10.173.22.101"  # 정상 데이터는 보존


# ── CSUS-R16: adapter firmware from PCIeDevice link ──────────────────────────

def test_adapter_firmware_from_pcie_device(monkeypatch):
    """Controllers[0].FirmwarePackageVersion 부재 시 Links.PCIeDevices[].FirmwareVersion fallback."""
    A = "Chassis/r001u01/NetworkAdapters/PCIeCard1"; U = "/redfish/v1/" + A
    _patch(monkeypatch, {
        "Chassis/r001u01/NetworkAdapters": (200, {"Members": [{"@odata.id": U}]}, None),
        A: (200, {"Id": "PCIeCard1", "Model": "MCX631102", "Manufacturer": "Mellanox",
                  "Controllers": [{"Links": {"PCIeDevices": [{"@odata.id": "/redfish/v1/Chassis/r001u01/PCIeDevices/1"}]}}],
                  "Ports": {"@odata.id": U + "/Ports"}}, None),
        A + "/Ports": (200, {"Members": [{"@odata.id": U + "/Ports/P1"}]}, None),
        A + "/Ports/P1": (200, {"Id": "P1", "Ethernet": {"AssociatedMACAddresses": ["aa:bb:cc:dd:ee:ff"]}}, None),
        "Chassis/r001u01/PCIeDevices/1": (200, {"FirmwareVersion": "26.46.3048 (MT_0000000575)"}, None),
    })
    out, errs = rg.gather_network_adapters_chassis("ip", "/redfish/v1/Chassis/r001u01", *CREDS)
    assert out["adapters"][0]["firmware_version"] == "26.46.3048 (MT_0000000575)"


def test_adapter_firmware_prefers_package_version(monkeypatch):
    """Controllers[0].FirmwarePackageVersion 존재 시 그것 우선 (PCIeDevice 미참조 — 회귀 안전)."""
    A = "Chassis/c/NetworkAdapters/N1"; U = "/redfish/v1/" + A
    _patch(monkeypatch, {
        "Chassis/c/NetworkAdapters": (200, {"Members": [{"@odata.id": U}]}, None),
        A: (200, {"Id": "N1", "Model": "BCM57414", "Manufacturer": "Broadcom",
                  "Controllers": [{"FirmwarePackageVersion": "22.31.6",
                                   "Links": {"PCIeDevices": [{"@odata.id": "/redfish/v1/Chassis/c/PCIeDevices/9"}]},
                                   "ControllerCapabilities": {"NetworkPortCount": 2}}]}, None),
        "Chassis/c/PCIeDevices/9": (200, {"FirmwareVersion": "SHOULD-NOT-USE"}, None),
    })
    out, errs = rg.gather_network_adapters_chassis("ip", "/redfish/v1/Chassis/c", *CREDS)
    assert out["adapters"][0]["firmware_version"] == "22.31.6"


# ── CSUS-R17: system.oem #HpeH3Npar 분기 (all-null iLO 스켈레톤 날조 제거) ────────

def test_system_oem_csus_hpeh3npar_extracted():
    """#HpeH3Npar System OEM → CSUS 전용 키 추출 (구: all-null iLO 스켈레톤 + 실 OEM drop).

    실 미러 node03 Systems/Partition0.Oem.Hpe 구조 재현.
    """
    out = rg._extract_oem_hpe({
        "Oem": {"Hpe": {
            "@odata.type": "#HpeH3Npar.v1_3_0.HpeH3Npar",
            "ConsoleRouting": "default", "ConsoleRoutingCurrentBoot": "default",
            "DCD": {"DCDVersion": "5.0-7.1"},
            "HostOS": {"OsName": "Red Hat Enterprise Linux",
                       "OsVersion": "8.10 (Ootpa)",
                       "OsSysDescription": "Red Hat Enterprise Linux 8.10 (Ootpa)"},
            "OV": {}, "ProductId": "1590PID03030201",
        }},
    })
    assert out["product_id"] == "1590PID03030201"
    assert out["console_routing"] == "default"
    assert out["dcd_version"] == "5.0-7.1"
    assert out["host_os_name"] == "Red Hat Enterprise Linux"
    assert out["host_os_version"] == "8.10 (Ootpa)"
    # iLO 전용 키(all-null 스켈레톤) 가 더 이상 생성되지 않음
    assert "aggregate_server_health" not in out
    assert "subsystem_health" not in out


def test_system_oem_csus_empty_subobjects_null():
    """node01 형태 — DCD={} / HostOS 부재 → 해당 키 null (raw 충실, 날조 없음)."""
    out = rg._extract_oem_hpe({
        "Oem": {"Hpe": {
            "@odata.type": "#HpeH3Npar.v1_3_0.HpeH3Npar",
            "ConsoleRouting": "default", "ConsoleRoutingCurrentBoot": "default",
            "DCD": {}, "OV": {}, "ProductId": "1590PID03030201",
        }},
    })
    assert out["product_id"] == "1590PID03030201"
    assert out["dcd_version"] is None
    assert out["host_os_name"] is None


def test_system_oem_ilo_branch_preserved():
    """실 iLO(@odata.type 가 #HpeH3Npar 아님) → 기존 iLO 추출 그대로 (회귀 안전)."""
    out = rg._extract_oem_hpe({
        "Oem": {"Hpe": {
            "@odata.type": "#HpeServerOem.v1_0_0.HpeServerOem",
            "PostState": "FinishedPost",
            "AggregateHealthStatus": {"AggregateServerHealth": "OK",
                                      "FanRedundancy": "Redundant"},
            "Bios": {"Current": {"Date": "01/15/2024"}},
        }},
    })
    assert out["post_state"] == "FinishedPost"
    assert out["aggregate_server_health"] == "OK"
    assert out["fan_redundancy"] == "Redundant"
    assert out["_bios_date"] == "01/15/2024"
    # CSUS 키가 iLO 분기에 누설되지 않음
    assert "product_id" not in out


# ── CSUS-R18 (F2): chassis-level OEM (#HpeH3Chassis) 수집 ─────────────────────

def test_chassis_oem_hpeh3chassis_extracted():
    """compute chassis #HpeH3Chassis OEM(물리위치/프로세서 호환성) 추출 (실 r001u01 재현)."""
    out = rg._extract_chassis_oem({
        "Oem": {"Hpe": {
            "@odata.type": "#HpeH3Chassis.v1_3_0.HpeH3Chassis",
            "OemChassisType": "Base", "PhysicalLocationString": "rack1/chassis_u1",
            "Physloc": "FFFF010101FFFF62",
            "ProcessorsCompatibilityKey": "PK8071305075101", "ProcessorsCompatible": True,
        }},
    })
    assert out["oem_chassis_type"] == "Base"
    assert out["physical_location"] == "rack1/chassis_u1"
    assert out["physloc"] == "FFFF010101FFFF62"
    assert out["processors_compatibility_key"] == "PK8071305075101"
    assert out["processors_compatible"] is True


def test_chassis_oem_non_hpeh3chassis_empty():
    """RackGroup/Rack(#HpeH3Chassis 아님) / 타 벤더 / OEM 부재 → {} (Additive 회귀 안전)."""
    assert rg._extract_chassis_oem({"Oem": {"Hpe": {"@odata.type": "#HpeRackGroup.v1_0_0"}}}) == {}
    assert rg._extract_chassis_oem({"Manufacturer": "Dell Inc.", "Model": "PowerEdge R740"}) == {}
    assert rg._extract_chassis_oem({}) == {}


def test_chassis_oem_processors_compatible_false_preserved():
    """ProcessorsCompatible=False 도 falsy-drop 없이 보존 (_safe — bool 충실)."""
    out = rg._extract_chassis_oem({
        "Oem": {"Hpe": {"@odata.type": "#HpeH3Chassis.v1_3_0.HpeH3Chassis",
                        "ProcessorsCompatible": False}},
    })
    assert out["processors_compatible"] is False


# ── MEM-01: CapacityMiB 부재 → None 보존 (구: or 0 날조) ──────────────────────

def test_memory_missing_capacity_preserved_as_none(monkeypatch):
    """CapacityMiB 부재 DIMM → capacity_mb=None (구: 0 으로 날조 — 누락↔0 혼동)."""
    _patch(monkeypatch, {
        "Systems/X/Memory": (200, {"Members": [
            {"@odata.id": "/redfish/v1/Systems/X/Memory/D1"}]}, None),
        "Systems/X/Memory/D1": (200, {"Id": "D1", "Status": {"State": "Enabled"}}, None),
    })
    out, errs = rg.gather_memory("ip", "/redfish/v1/Systems/X", *CREDS)
    assert out["slots"][0]["capacity_mb"] is None


def test_memory_present_capacity_unchanged(monkeypatch):
    """CapacityMiB 보유 → 그대로 int (회귀 안전). 실측 0 도 0 보존(누락과 구분)."""
    _patch(monkeypatch, {
        "Systems/X/Memory": (200, {"Members": [
            {"@odata.id": "/redfish/v1/Systems/X/Memory/D1"},
            {"@odata.id": "/redfish/v1/Systems/X/Memory/D2"}]}, None),
        "Systems/X/Memory/D1": (200, {"Id": "D1", "CapacityMiB": 32768}, None),
        "Systems/X/Memory/D2": (200, {"Id": "D2", "CapacityMiB": 0}, None),
    })
    out, errs = rg.gather_memory("ip", "/redfish/v1/Systems/X", *CREDS)
    caps = {s["id"]: s["capacity_mb"] for s in out["slots"]}
    assert caps["D1"] == 32768
    assert caps["D2"] == 0
    assert out["total_mib"] == 32768  # 32768 + 0
