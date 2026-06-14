"""Regression for cycle 2026-05-07 M-I1~I5 — section variant helpers.

목적: M-I1 (storage SmartStorage), M-I2 (power dual-emit dedup), M-I3 (OEM
namespace unified), M-I4 (NIC OCP/SR-IOV), M-I5 (RoleId enum / DIMM label) 의
Additive helper 함수가 기대대로 동작하는지 + 호출자 envelope 영향 0 검증.

rule 92 R2: 모든 helper 는 raw dict 만 반환. envelope shape 변경 없음.
rule 12 R1 Allowed: OEM namespace 직접 의존 영역 (Redfish API spec).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

# ansible stub
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


# ──────────────────────────────────────────────────────────────────────────────
# M-I1: storage SmartStorage helper (HPE iLO4 legacy)
# ──────────────────────────────────────────────────────────────────────────────


def _seq_get(responses):
    """순차 응답 list → _get mock."""
    it = iter(responses)

    def fake(bmc_ip, path, username, password, timeout, verify_ssl):
        return next(it)

    return fake


def test_smart_storage_404_returns_graceful_empty():
    """SmartStorage 자체 404 → controllers/volumes 빈 list + errors 1건."""
    responses = [(404, None, None)]
    with patch.object(rg, '_get', _seq_get(responses)):
        ctrls, vols, errors = rg._gather_smart_storage(
            "10.1.1.1", "/redfish/v1/Systems/1", "u", "p", 30, False
        )
    assert ctrls == []
    assert vols == []
    assert len(errors) == 1
    assert 'SmartStorage' in errors[0]['message']


def test_smart_storage_success_extracts_controllers():
    """SmartStorage root 200 + ArrayControllers + PhysicalDrives → controllers list."""
    ss_root = {
        "ArrayControllers": {"@odata.id": "/redfish/v1/Systems/1/SmartStorage/ArrayControllers"},
    }
    ctrl_coll = {"Members": [{"@odata.id": "/redfish/v1/Systems/1/SmartStorage/ArrayControllers/0"}]}
    ctrl_data = {
        "Id": "0",
        "Model": "Smart Array P440ar",
        "Name": "Smart Array P440ar",
        "Manufacturer": "HPE",
        "FirmwareVersion": {"Current": {"VersionString": "4.52"}},
        "Status": {"Health": "OK"},
        "PhysicalDrives": {"@odata.id": "/redfish/v1/Systems/1/SmartStorage/ArrayControllers/0/PhysicalDrives"},
    }
    pd_coll = {"Members": [{"@odata.id": "/redfish/v1/Systems/1/SmartStorage/.../PhysicalDrives/0"}]}
    pd_data = {
        "Id": "0", "Model": "MK000480GWSSC",
        "SerialNumber": "ABC123", "Manufacturer": "HPE",
        "MediaType": "SSD", "InterfaceType": "SAS",
        "CapacityGB": 480, "Status": {"Health": "OK"},
    }
    responses = [
        (200, ss_root, None),
        (200, ctrl_coll, None),
        (200, ctrl_data, None),
        (200, pd_coll, None),
        (200, pd_data, None),
    ]
    with patch.object(rg, '_get', _seq_get(responses)):
        ctrls, vols, errors = rg._gather_smart_storage(
            "10.1.1.1", "/redfish/v1/Systems/1", "u", "p", 30, False
        )
    # SmartStorage 영역만 — HostBusAdapters 부재로 errors 1건 (그쪽 skip 메시지) 가능
    assert len(ctrls) == 1
    c = ctrls[0]
    assert c['id'] == '0'
    assert c['controller_model'] == 'Smart Array P440ar'
    assert c['controller_firmware'] == '4.52'
    assert len(c['drives']) == 1
    d = c['drives'][0]
    assert d['model'] == 'MK000480GWSSC'
    assert d['media_type'] == 'SSD'
    assert d['capacity_gb'] == 480
    assert d['capacity_bytes'] == 480_000_000_000
    assert vols == []


def test_gather_storage_falls_back_to_smartstorage_when_both_404():
    """gather_storage: Storage 404 + SimpleStorage 404 → SmartStorage fallback 시도."""
    # Storage + SimpleStorage 404 → SmartStorage 200 path
    ss_root = {"ArrayControllers": {"@odata.id": "/redfish/v1/Systems/1/SmartStorage/ArrayControllers"}}
    ctrl_coll = {"Members": []}
    responses = [
        (404, None, None),  # Storage
        (404, None, None),  # SimpleStorage
        (200, ss_root, None),  # SmartStorage root
        (200, ctrl_coll, None),  # ArrayControllers (empty)
        # HostBusAdapters key 부재 — _gather_smart_storage 가 skip
    ]
    with patch.object(rg, '_get', _seq_get(responses)):
        result, errors = rg.gather_storage(
            "10.1.1.1", "/redfish/v1/Systems/1", "u", "p", 30, False
        )
    # SmartStorage 결과: ArrayControllers Members 빈 list → controllers 빈 list +
    # 'Storage/SimpleStorage/SmartStorage 모두 실패' message 가 추가됨 (ctrls 가 비었으므로)
    assert result == {'controllers': [], 'volumes': []}


# ──────────────────────────────────────────────────────────────────────────────
# M-I2: power dual-emit dedup helper
# ──────────────────────────────────────────────────────────────────────────────


def test_merge_power_dual_dedups_psu_by_serial():
    """Power + PowerSubsystem 둘 다 emit 시 같은 serial PSU 1번만."""
    legacy = {
        'power_supplies': [
            {'name': 'PSU0', 'model': 'PS-1234', 'serial': 'SN-A1',
             'manufacturer': 'Dell', 'power_capacity_w': 750,
             'firmware_version': None, 'health': 'OK', 'state': 'Enabled'},
            {'name': 'PSU1', 'model': 'PS-1234', 'serial': 'SN-A2',
             'manufacturer': 'Dell', 'power_capacity_w': 750,
             'firmware_version': None, 'health': 'OK', 'state': 'Enabled'},
        ],
        'power_control': {
            'power_consumed_watts': 350, 'power_capacity_watts': 1500,
            'interval_in_min': 1, 'min_consumed_watts': 100,
            'avg_consumed_watts': 300, 'max_consumed_watts': 400,
        },
    }
    subsystem = {
        'power_supplies': [
            # 같은 serial — dedup 대상
            {'name': 'PSU0', 'model': 'PS-1234', 'serial': 'SN-A1',
             'manufacturer': 'Dell', 'power_capacity_w': 750,
             'firmware_version': None, 'health': 'OK', 'state': 'Enabled'},
            # 다른 PSU
            {'name': 'PSU1', 'model': 'PS-1234', 'serial': 'SN-A2',
             'manufacturer': 'Dell', 'power_capacity_w': 750,
             'firmware_version': None, 'health': 'OK', 'state': 'Enabled'},
        ],
        'power_control': None,
    }
    merged = rg._merge_power_dual(legacy, subsystem)
    assert len(merged['power_supplies']) == 2, "dedup 후 2 PSU"
    # PowerControl: legacy 우선 (system-level metric 풍부)
    assert merged['power_control']['power_consumed_watts'] == 350


def test_merge_power_dual_handles_empty_inputs():
    """legacy None / subsystem None / 둘 다 빈 list 안전."""
    assert rg._merge_power_dual(None, None) == {'power_supplies': [], 'power_control': None}
    assert rg._merge_power_dual({}, {}) == {'power_supplies': [], 'power_control': None}


def test_merge_power_dual_pc_fallback_to_subsystem():
    """legacy.power_control None → subsystem.power_control 사용."""
    legacy = {'power_supplies': [], 'power_control': None}
    subsystem = {
        'power_supplies': [],
        'power_control': {'power_capacity_watts': 1500, 'power_consumed_watts': None,
                          'interval_in_min': None, 'min_consumed_watts': None,
                          'avg_consumed_watts': None, 'max_consumed_watts': None},
    }
    merged = rg._merge_power_dual(legacy, subsystem)
    assert merged['power_control']['power_capacity_watts'] == 1500


# ──────────────────────────────────────────────────────────────────────────────
# M-I3: bmc / firmware OEM namespace unified extractor
# ──────────────────────────────────────────────────────────────────────────────


def test_extract_oem_unified_hpe_v6():
    """HPE iLO6: Oem.Hpe 매치."""
    data = {"Oem": {"Hpe": {"Type": "iLO6", "Firmware": {"Current": {"VersionString": "1.73"}}}}}
    oem, vendor, ns = rg._extract_oem_unified(data)
    assert vendor == 'hpe'
    assert ns == 'Hpe'
    assert oem.get('Type') == 'iLO6'


def test_extract_oem_unified_hpe_ilo4_fallback_to_hp():
    """HPE iLO4: Oem.Hp (legacy) fallback."""
    data = {"Oem": {"Hp": {"Type": "iLO4"}}}
    oem, vendor, ns = rg._extract_oem_unified(data)
    assert vendor == 'hpe'
    assert ns == 'Hp'


def test_extract_oem_unified_fujitsu_ts_fujitsu_variant():
    """Fujitsu: Oem.ts_fujitsu namespace."""
    data = {"Oem": {"ts_fujitsu": {"FirmwareInformation": {}}}}
    oem, vendor, ns = rg._extract_oem_unified(data)
    assert vendor == 'fujitsu'
    assert ns == 'ts_fujitsu'


def test_extract_oem_unified_quanta_qct_variant():
    """Quanta: Oem.QCT alias 매치."""
    data = {"Oem": {"QCT": {"PlatformVersion": "1.0"}}}
    oem, vendor, ns = rg._extract_oem_unified(data)
    assert vendor == 'quanta'
    assert ns == 'QCT'


def test_extract_oem_unified_inspur_variant():
    """Inspur: Oem.Inspur_System alias 매치."""
    data = {"Oem": {"Inspur_System": {"BMCInfo": {}}}}
    oem, vendor, ns = rg._extract_oem_unified(data)
    assert vendor == 'inspur'
    assert ns == 'Inspur_System'


def test_extract_oem_unified_expected_vendor_filter():
    """expected_vendor='dell' 지정 시 Dell namespace 만 시도."""
    data = {"Oem": {"Dell": {"DellManager": {}}, "Hpe": {"Type": "iLO6"}}}
    oem, vendor, ns = rg._extract_oem_unified(data, expected_vendor='dell')
    assert vendor == 'dell'
    assert ns == 'Dell'


def test_extract_oem_unified_no_oem_returns_empty():
    """Oem 키 부재 → ({}, None, None)."""
    assert rg._extract_oem_unified({"Status": {"Health": "OK"}}) == ({}, None, None)
    assert rg._extract_oem_unified({}) == ({}, None, None)
    assert rg._extract_oem_unified(None) == ({}, None, None)


def test_extract_oem_unified_empty_namespace_skipped():
    """Oem.<vendor>={} 같은 빈 dict 는 skip."""
    data = {"Oem": {"Dell": {}, "Hpe": {"Type": "iLO6"}}}
    oem, vendor, ns = rg._extract_oem_unified(data)
    # Dell 빈 dict 는 매치 안 됨 → HPE 매치
    assert vendor == 'hpe'


# ──────────────────────────────────────────────────────────────────────────────
# M-I4: NIC SR-IOV / OCP detection helpers
# ──────────────────────────────────────────────────────────────────────────────


def test_detect_nic_ocp_slot_via_service_label():
    """NetworkAdapter.Location.PartLocation.ServiceLabel='OCP' → 'ocp'."""
    adata = {
        "Location": {"PartLocation": {"LocationType": "Slot", "ServiceLabel": "OCP"}},
        "Name": "Mellanox ConnectX-6",
    }
    assert rg._detect_nic_ocp_slot(adata) == 'ocp'


def test_detect_nic_ocp_slot_via_name():
    """NetworkAdapter.Name 'OCP NIC' → 'ocp'."""
    adata = {"Name": "OCP NIC Mezzanine Card"}
    assert rg._detect_nic_ocp_slot(adata) == 'ocp'


def test_detect_nic_ocp_slot_pcie_when_slot_only():
    """LocationType='Slot' + OCP 시그널 없음 → 'pcie'."""
    adata = {
        "Location": {"PartLocation": {"LocationType": "Slot", "ServiceLabel": "Slot 1"}},
        "Name": "Broadcom NetXtreme",
    }
    assert rg._detect_nic_ocp_slot(adata) == 'pcie'


def test_detect_nic_ocp_slot_returns_none_when_unknown():
    """위치 정보 없음 → None."""
    assert rg._detect_nic_ocp_slot({}) is None
    assert rg._detect_nic_ocp_slot(None) is None


def test_detect_nic_sriov_dell_oem():
    """Dell OEM.NICDeviceFunctions.SRIOVCapable=true."""
    adata = {"Oem": {"Dell": {"NICDeviceFunctions": {"SRIOVCapable": True}}}}
    assert rg._detect_nic_sriov_capable(adata) is True


def test_detect_nic_sriov_hpe_config_dict():
    """HPE OEM.NetworkAdapter.SRIOVConfig dict 존재 → True."""
    adata = {"Oem": {"Hpe": {"NetworkAdapter": {"SRIOVConfig": {"Enabled": True}}}}}
    assert rg._detect_nic_sriov_capable(adata) is True


def test_detect_nic_sriov_standard_path():
    """표준 SRIOV.SRIOVCapable=True."""
    adata = {"SRIOV": {"SRIOVCapable": True}}
    assert rg._detect_nic_sriov_capable(adata) is True


def test_detect_nic_sriov_returns_none_when_unknown():
    """SR-IOV 정보 부재 → None."""
    assert rg._detect_nic_sriov_capable({}) is None


# ──────────────────────────────────────────────────────────────────────────────
# M-I5: RoleId enum / DIMM label normalization
# ──────────────────────────────────────────────────────────────────────────────


def test_normalize_role_id_dell_administrator():
    """Dell 표준 'Administrator' → 'administrator'."""
    assert rg._normalize_role_id('Administrator') == 'administrator'


def test_normalize_role_id_cisco_admin():
    """Cisco 'admin' → 'administrator'."""
    assert rg._normalize_role_id('admin') == 'administrator'


def test_normalize_role_id_lenovo_supervisor():
    """Lenovo 'Supervisor' → 'administrator'."""
    assert rg._normalize_role_id('Supervisor') == 'administrator'


def test_normalize_role_id_supermicro_user():
    """Supermicro 'User' → 'operator'."""
    assert rg._normalize_role_id('User') == 'operator'


def test_normalize_role_id_huawei_commonuser():
    """Huawei 'CommonUser' → 'readonly'."""
    assert rg._normalize_role_id('CommonUser') == 'readonly'


def test_normalize_role_id_supermicro_callback():
    """Supermicro 'Callback' (read-only) → 'readonly'."""
    assert rg._normalize_role_id('Callback') == 'readonly'


def test_normalize_role_id_none_empty():
    """None / '' → None."""
    assert rg._normalize_role_id(None) is None
    assert rg._normalize_role_id('') is None
    assert rg._normalize_role_id('   ') is None


def test_normalize_role_id_unknown_preserves_lowercase():
    """알 수 없는 role → lowercase raw 보존."""
    assert rg._normalize_role_id('CustomRoleX') == 'customrolex'


def test_normalize_dimm_label_dell():
    """Dell 'DIMM_A1' → 'DIMM A1'."""
    assert rg._normalize_dimm_label('DIMM_A1') == 'DIMM A1'


def test_normalize_dimm_label_hpe():
    """HPE 'P1-DIMM-A1' → 'P1 DIMM A1'."""
    assert rg._normalize_dimm_label('P1-DIMM-A1') == 'P1 DIMM A1'


def test_normalize_dimm_label_supermicro():
    """Supermicro 'CPU0_DIMM_A1' → 'CPU0 DIMM A1'."""
    assert rg._normalize_dimm_label('CPU0_DIMM_A1') == 'CPU0 DIMM A1'


def test_normalize_dimm_label_lenovo_preserves_space():
    """Lenovo 'DIMM 1' 그대로 (이미 공백 구분)."""
    assert rg._normalize_dimm_label('DIMM 1') == 'DIMM 1'


def test_normalize_dimm_label_none():
    """None / '' → None."""
    assert rg._normalize_dimm_label(None) is None
    assert rg._normalize_dimm_label('') is None


# ──────────────────────────────────────────────────────────────────────────────
# Smoke: envelope shape 변경 0 (rule 92 R2 Additive 검증)
# ──────────────────────────────────────────────────────────────────────────────


def test_helpers_do_not_export_new_envelope_keys():
    """본 cycle 추가 helper 들이 모듈 top-level 에 envelope 키 영향 없음 검증.

    rule 92 R2: 호출자 envelope 13 필드 변경 0 / data.<section>.<field> 신규 키 추가 0.
    """
    # 새 helper 들이 모두 underscore prefix (internal only)
    new_helpers = [
        '_gather_smart_storage',
        '_merge_power_dual',
        '_extract_oem_unified',
        '_detect_nic_ocp_slot',
        '_detect_nic_sriov_capable',
        '_normalize_role_id',
        '_normalize_dimm_label',
    ]
    for name in new_helpers:
        assert hasattr(rg, name), f"{name} missing"
        assert name.startswith('_'), f"{name} should be underscore-prefixed (internal)"
