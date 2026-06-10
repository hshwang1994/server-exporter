"""CSUS per-partition normalize 의 grouping-key drift 가드.

배경:
    `redfish_gather.py` 의 `_summarize_partition_disks` / `_normalize_{storage,cpu,
    memory,network}_raw` (~210줄) 는 top-level `normalize_standard.yml`(Ansible) 의
    grouping/summary 로직을 Python 으로 **평행 재구현** 한다. 두 경로가 같은 grouping
    키로 묶지 않으면 `multi_node.partitions[].*.summary` 가 채널별로 divergence 한다.

    기존 `test_hpe_csus_multi_node.py` 는 **동질(homogeneous) happy-path** 만 검증해,
    grouping 키에서 한 필드가 빠져도(예: storage 키에서 protocol 누락) 전부 통과한다.
    본 파일은 **이질(heterogeneous) 입력으로 각 grouping 키 필드를 판별(discriminate)**
    하여, grouping 키 조합이 바뀌면 즉시 실패하도록 고정한다 (drift 가드).

    정본 grouping 키 (docstring + normalize_standard.yml 와 동기):
      storage(_summarize_partition_disks): cap_gb | media_type | protocol | model
      memory(_normalize_memory_raw)      : cap_gb | type | speed_mhz | manufacturer | part_number
      cpu(_normalize_cpu_raw)            : model
      network(_normalize_network_raw)    : default_gateways = 중복 제거된 gateway 집합

    ansible↔python full parity 는 ansible-playbook 필요(이 환경 부재) — 본 가드는
    Python 경로의 grouping 불변식을 잠가 drift 의 절반(코드측)을 차단한다.
"""
from __future__ import annotations

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

# cap_gb = total_mb // 1024 (MIB_PER_GIB). 깔끔한 GiB 정수용 MiB 값.
_MB_400G = 400 * 1024  # 409600 MiB → cap_gb 400
_MB_800G = 800 * 1024  # 819200 MiB → cap_gb 800


def _disk(total_mb=_MB_400G, media="SSD", protocol="SATA", model="MZ7L3"):
    return {"total_mb": total_mb, "media_type": media, "protocol": protocol, "model": model}


# ─────────────────────────────────────────────────────────────────────────────
# _summarize_partition_disks — grouping 키 = cap_gb | media_type | protocol | model
# ─────────────────────────────────────────────────────────────────────────────

def test_summarize_homogeneous_accumulates():
    """동일 spec N개 → 1 그룹, quantity=N, group_total=N×cap, grand_total 합산."""
    out = rg._summarize_partition_disks([_disk(), _disk(), _disk()])
    assert len(out["groups"]) == 1
    g = out["groups"][0]
    assert g["quantity"] == 3
    assert g["unit_capacity_gb"] == 400
    assert g["group_total_gb"] == 1200
    assert out["grand_total_gb"] == 1200


@pytest.mark.parametrize("field,a,b", [
    ("capacity", {"total_mb": _MB_400G}, {"total_mb": _MB_800G}),
    ("media_type", {"media": "SSD"}, {"media": "HDD"}),
    ("protocol", {"protocol": "SATA"}, {"protocol": "SAS"}),
    ("model", {"model": "MZ7L3"}, {"model": "MZ7L4"}),
])
def test_summarize_each_key_field_discriminates(field, a, b):
    """grouping 키의 각 필드가 다르면 별도 그룹 — 키 조합 drift 차단.

    이 판별이 깨지면(예: 키에서 protocol 제거) 두 디스크가 1 그룹으로 합쳐져 실패.
    """
    out = rg._summarize_partition_disks([_disk(**a), _disk(**b)])
    assert len(out["groups"]) == 2, (
        f"'{field}' 가 다른데 1 그룹으로 합쳐짐 — grouping 키에서 {field} 누락 의심"
    )
    assert all(g["quantity"] == 1 for g in out["groups"])


def test_summarize_zero_and_none_capacity_skipped():
    """cap_gb<=0 (total_mb 0/None/음수) 디스크는 그룹/합계에서 제외."""
    out = rg._summarize_partition_disks([
        _disk(),                       # 400 GiB 유효
        _disk(total_mb=0),             # 0 → skip
        _disk(total_mb=None),          # None → skip
        {"media_type": "SSD"},         # total_mb 키 부재 → skip
    ])
    assert len(out["groups"]) == 1
    assert out["groups"][0]["quantity"] == 1
    assert out["grand_total_gb"] == 400


def test_summarize_empty():
    """빈/None → 빈 summary (graceful)."""
    for raw in ([], None):
        out = rg._summarize_partition_disks(raw)
        assert out == {"groups": [], "grand_total_gb": 0}


def test_summarize_mixed_realistic():
    """2×400G SSD/SATA + 1×800G HDD/SAS → 2 그룹, grand=1600."""
    out = rg._summarize_partition_disks([
        _disk(), _disk(),
        _disk(total_mb=_MB_800G, media="HDD", protocol="SAS", model="ST8000"),
    ])
    assert len(out["groups"]) == 2
    by_qty = sorted(out["groups"], key=lambda g: g["quantity"])
    assert by_qty[0]["quantity"] == 1 and by_qty[0]["unit_capacity_gb"] == 800
    assert by_qty[1]["quantity"] == 2 and by_qty[1]["unit_capacity_gb"] == 400
    assert out["grand_total_gb"] == 1600


# ─────────────────────────────────────────────────────────────────────────────
# _normalize_storage_raw — physical_disks dedup(name+model+serial) + summary 연동
# ─────────────────────────────────────────────────────────────────────────────

def _bytes(gib):
    return gib * 1024 * 1048576  # cap_gb 보존되는 byte


def test_storage_physical_dedup_collapses_identical_identity():
    """동일 name+model+serial 2개 → physical_disks 1개(중복 붕괴), drives 는 2 유지.

    summary 는 physical(dedup) 기준이라 quantity=1 이어야 한다.
    """
    raw = {"controllers": [{"id": "c1", "name": "ctrl", "drives": [
        {"id": "d0", "name": "Disk0", "model": "MZ", "serial": "SAME",
         "capacity_bytes": _bytes(400), "media_type": "SSD", "protocol": "SATA"},
        {"id": "d1", "name": "Disk0", "model": "MZ", "serial": "SAME",
         "capacity_bytes": _bytes(400), "media_type": "SSD", "protocol": "SATA"},
    ]}], "volumes": []}
    out = rg._normalize_storage_raw(raw)
    assert len(out["controllers"][0]["drives"]) == 2   # 컨트롤러 drive 목록은 raw 보존
    assert len(out["physical_disks"]) == 1             # 정체성 동일 → dedup
    assert out["summary"]["groups"][0]["quantity"] == 1


def test_storage_drive_without_name_and_model_excluded_from_physical():
    """name·model 모두 없는 drive 는 physical_disks 미등재(빈 slot)."""
    raw = {"controllers": [{"id": "c1", "drives": [
        {"id": "empty", "name": None, "model": None, "capacity_bytes": None},
        {"id": "real", "name": "Disk1", "model": "MZ", "serial": "S1",
         "capacity_bytes": _bytes(400), "media_type": "SSD", "protocol": "SAS"},
    ]}], "volumes": []}
    out = rg._normalize_storage_raw(raw)
    assert len(out["physical_disks"]) == 1
    assert out["physical_disks"][0]["device"] == "Disk1"


def test_storage_heterogeneous_summary_multi_group():
    """서로 다른 spec drive → summary 다중 그룹 (storage_raw→summarize 연동)."""
    raw = {"controllers": [{"id": "c1", "drives": [
        {"name": "A", "model": "MZ", "serial": "1", "capacity_bytes": _bytes(400),
         "media_type": "SSD", "protocol": "SATA"},
        {"name": "B", "model": "ST", "serial": "2", "capacity_bytes": _bytes(800),
         "media_type": "HDD", "protocol": "SAS"},
    ]}], "volumes": []}
    out = rg._normalize_storage_raw(raw)
    assert len(out["summary"]["groups"]) == 2
    assert out["summary"]["grand_total_gb"] == 1200


# ─────────────────────────────────────────────────────────────────────────────
# _normalize_cpu_raw — model 그룹핑 + processor_type 필터 (CPU/CORE/'' 포함)
# ─────────────────────────────────────────────────────────────────────────────

def test_cpu_multiple_distinct_models_two_groups():
    """서로 다른 model 의 CPU → 2 그룹 (model 키 판별)."""
    procs = [
        {"model": "Xeon 8480", "total_cores": 56, "total_threads": 112,
         "manufacturer": "Intel", "processor_type": "CPU"},
        {"model": "Xeon 6430", "total_cores": 32, "total_threads": 64,
         "manufacturer": "Intel", "processor_type": "CPU"},
    ]
    out = rg._normalize_cpu_raw(procs)
    assert out["sockets"] == 2
    assert out["cores_physical"] == 88
    assert len(out["summary"]["groups"]) == 2


@pytest.mark.parametrize("ptype,counted", [
    ("CPU", True), ("CORE", True), ("", True),
    ("GPU", False), ("FPGA", False), ("Accelerator", False),
])
def test_cpu_processor_type_filter(ptype, counted):
    """processor_type ∈ {CPU,CORE,''} 만 카운트. 그 외(GPU/FPGA/…) 제외."""
    procs = [{"model": "X", "total_cores": 8, "total_threads": 16,
              "processor_type": ptype}]
    out = rg._normalize_cpu_raw(procs)
    assert (out["sockets"] == 1) is counted
    assert (out["cores_physical"] == 8) is counted


def test_cpu_empty_returns_nones():
    """빈/비-list → 모든 합산 None (graceful)."""
    for procs in ([], None, "x"):
        out = rg._normalize_cpu_raw(procs)
        assert out["sockets"] is None
        assert out["cores_physical"] is None
        assert out["summary"]["groups"] == []


# ─────────────────────────────────────────────────────────────────────────────
# _normalize_memory_raw — 키 cap|type|speed|mfr|part 판별 + zero-skip
# ─────────────────────────────────────────────────────────────────────────────

def _dimm(cap_mb=128 * 1024, type_="DDR5", speed=4800, mfr="Samsung", pn="M321"):
    return {"capacity_mb": cap_mb, "type": type_, "speed_mhz": speed,
            "manufacturer": mfr, "part_number": pn, "health": "OK"}


@pytest.mark.parametrize("field,a,b", [
    ("capacity", {"cap_mb": 128 * 1024}, {"cap_mb": 64 * 1024}),
    ("type", {"type_": "DDR5"}, {"type_": "DDR4"}),
    ("speed", {"speed": 4800}, {"speed": 5600}),
    ("manufacturer", {"mfr": "Samsung"}, {"mfr": "SK hynix"}),
    ("part_number", {"pn": "M321"}, {"pn": "HMC"}),
])
def test_memory_each_key_field_discriminates(field, a, b):
    """memory grouping 키의 각 필드가 다르면 별도 그룹 — 키 조합 drift 차단."""
    out = rg._normalize_memory_raw({"total_mib": 0, "slots": [_dimm(**a), _dimm(**b)]})
    assert len(out["summary"]["groups"]) == 2, (
        f"'{field}' 가 다른데 1 그룹 — memory grouping 키에서 {field} 누락 의심"
    )


def test_memory_zero_capacity_slot_skipped():
    """capacity 0/부재 slot 은 summary 그룹/합계 제외 (slots 원본은 보존)."""
    out = rg._normalize_memory_raw({"total_mib": 131072, "slots": [
        _dimm(),
        {"id": "empty", "capacity_mb": 0, "type": "Unknown"},
        {"id": "absent"},
    ]})
    assert len(out["slots"]) == 3           # 원본 slots 보존
    assert len(out["summary"]["groups"]) == 1
    assert out["summary"]["groups"][0]["quantity"] == 1
    assert out["summary"]["grand_total_gb"] == 128


def test_memory_empty_slots():
    """빈 slots → 빈 summary."""
    out = rg._normalize_memory_raw({"total_mib": None, "slots": []})
    assert out["summary"] == {"groups": [], "grand_total_gb": 0}


# ─────────────────────────────────────────────────────────────────────────────
# _normalize_network_raw — gateway 중복 제거 + 0.0.0.0/빈 주소 필터
# ─────────────────────────────────────────────────────────────────────────────

def test_network_gateway_dedup_across_nics():
    """여러 NIC 가 같은 gateway 를 가지면 default_gateways 에 1회만 등재."""
    raw = [
        {"id": "e0", "name": "n0", "ipv4": [{"address": "10.0.0.5",
            "gateway": "10.0.0.1", "subnet_mask": "255.255.255.0"}]},
        {"id": "e1", "name": "n1", "ipv4": [{"address": "10.0.0.6",
            "gateway": "10.0.0.1", "subnet_mask": "255.255.255.0"}]},
    ]
    out = rg._normalize_network_raw(raw)
    assert out["default_gateways"] == [{"family": "ipv4", "address": "10.0.0.1"}]


def test_network_distinct_gateways_kept():
    """서로 다른 gateway 는 모두 등재."""
    raw = [
        {"id": "e0", "ipv4": [{"address": "10.0.0.5", "gateway": "10.0.0.1"}]},
        {"id": "e1", "ipv4": [{"address": "10.1.0.5", "gateway": "10.1.0.1"}]},
    ]
    out = rg._normalize_network_raw(raw)
    gws = {g["address"] for g in out["default_gateways"]}
    assert gws == {"10.0.0.1", "10.1.0.1"}


def test_network_filters_zero_and_empty_address():
    """0.0.0.0 / 빈 주소는 interface.addresses 에서 제외."""
    raw = [{"id": "e0", "name": "n0", "ipv4": [
        {"address": "0.0.0.0", "gateway": "0.0.0.0"},
        {"address": "", "gateway": ""},
        {"address": "10.0.0.9", "gateway": "10.0.0.1"},
    ]}]
    out = rg._normalize_network_raw(raw)
    addrs = [a["address"] for a in out["interfaces"][0]["addresses"]]
    assert addrs == ["10.0.0.9"]
    # 0.0.0.0 gateway 도 default_gateways 에 미등재
    assert out["default_gateways"] == [{"family": "ipv4", "address": "10.0.0.1"}]
