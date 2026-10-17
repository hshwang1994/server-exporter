"""ESXi `storage.infiniband[]` — 추정하지 않는다 (2026-10-17 InfiniBand 전면 검증).

종전 collect_network_extended.yml 은 vmnic 드라이버 이름이 nmlx/mlx 로 시작하면 그 NIC 를 `storage.infiniband[]` 에 넣었다.
ESXi 네이티브 nmlx5 드라이버는 Ethernet 전용이고 IB 는 SR-IOV/passthrough 로 VM 에만 가므로(NVIDIA · Broadcom KB 381748) 이것은
Mellanox **이더넷** NIC 를 IB 로 보고하는 오탐이었다. 이제 이 채널의 infiniband 는 항상 [] 이고, 그 밖의 네트워크 · HBA 수집은
그대로다. 실제 YAML set_fact 를 공통 merge/build_* 와 함께 렌더한다 (test_esxi_partial_failures_c9 하네스). 실장비 검증 아님.

시나리오 23(IB PCI 컨트롤러만 보이는 호스트)은 코드로 표현할 수 없다 — esxi_disks.py 가 HostPciDevice.classId 를 내지 않고 ESXi/OS
채널에는 notices 경로가 없다. docs/ai/NEXT_ACTIONS.md 에 모듈 변경 + 새 필드가 필요한 후속으로 적어 두었다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "unit"))

from test_esxi_partial_failures_c9 import EXT, OK_VMNIC, _ext, _final  # noqa: E402

MLX_VMNIC = {"failed": False, "hosts_vmnics_info": {"esxi01": {"vmnic_details": [
    {"device": "vmnic0", "status": "connected", "actual_speed": 10000, "driver": "igbn", "adapter": "Intel Corporation I350 Gigabit Network Connection"},
    {"device": "vmnic2", "status": "connected", "actual_speed": 100000, "driver": "nmlx5_core",
     "adapter": "Mellanox Technologies MT2892 Family [ConnectX-6 Dx]"},
    {"device": "vmnic3", "status": "disconnected", "actual_speed": "N/A", "driver": "nmlx5_core",
     "adapter": "Mellanox Technologies MT2892 Family [ConnectX-6 Dx]"}]}}}


def test_mellanox_vmnic_is_not_reported_as_infiniband():
    """시나리오 22 — nmlx5_core(이더넷 모드 ConnectX) vmnic 는 IB 가 아니다. network.adapters 에는 그대로 남는다."""
    ctx = _ext(_e_vmnic=MLX_VMNIC)
    assert ctx["_data_fragment"]["storage"]["infiniband"] == []
    drivers = {a["name"]: a["driver"] for a in ctx["_data_fragment"]["network"]["adapters"]}
    assert drivers == {"vmnic0": "igbn", "vmnic2": "nmlx5_core", "vmnic3": "nmlx5_core"}
    assert "_e_ext_ib" not in ctx
    assert ctx["_errors_fragment"] == []


def test_hbas_adapters_vswitches_unchanged():
    """시나리오 27 — IB 추정 제거가 HBA · vmnic · vSwitch 수집을 바꾸지 않는다."""
    ctx = _ext()
    frag = ctx["_data_fragment"]
    assert len(frag["storage"]["hbas"]) == 1 and frag["storage"]["hbas"][0]["wwpn"] == "21:00:00:24:ff:01:02:03"
    assert [a["name"] for a in frag["network"]["adapters"]] == ["vmnic0"]
    assert frag["network"]["virtual_switches"] == [{"name": "vSwitch0", "num_ports": 128, "mtu": 1500, "pnics": ["vmnic0"],
                                                    "portgroups": ["VM Network"]}]
    assert ctx["_sections_collected_fragment"] == ["network", "storage"]
    assert frag["storage"]["infiniband"] == []


def test_storage_collected_flag_follows_hbas_only():
    """종전에는 Mellanox vmnic 만 있어도(HBA 없음) storage 가 '수집됨' 이 됐다. 이제 HBA 만 본다 — 기본 storage 는 normalize_storage 가
    이미 collected 라 envelope 의 storage 상태는 success 그대로다."""
    ctx = _ext(_e_vmnic=MLX_VMNIC, _e_vmhba={"failed": False, "hosts_vmhbas_info": {"esxi01": {"vmhba_details": []}}})
    assert ctx["_sections_collected_fragment"] == ["network"]
    assert ctx["_errors_fragment"] == []
    final = _final(ctx)
    assert final["_norm_sections"]["storage"] == "success" and final["_out_status"] == "success"


def test_rescue_skeleton_keeps_empty_infiniband():
    doc = yaml.safe_load(EXT.read_text(encoding="utf-8"))
    rescue = doc[0]["rescue"][0]["ansible.builtin.set_fact"]["_data_fragment"]
    assert rescue["storage"]["infiniband"] == []


def test_no_ib_inference_text_remains():
    """정적 — 드라이버명 기반 추정 코드가 YAML 에 남아 있지 않다 (주석의 설명은 허용: 코드 줄만 본다)."""
    code = "\n".join(ln for ln in EXT.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#"))
    assert "_e_ext_ib" not in code
    assert "startswith('nmlx')" not in code and "startswith('mlx')" not in code
    assert "RoCE/IB-capable" not in code
    assert "'Mellanox'" not in code, "드라이버 이름에서 제조사를 추정하지 않는다"


def test_default_vmnic_fixture_still_renders_with_no_driver_key():
    """하네스 기본 입력(driver 키 없음)도 그대로 렌더된다 — 삭제가 adapters 파서에 영향을 주지 않는다."""
    ctx = _ext(_e_vmnic=OK_VMNIC)
    assert ctx["_data_fragment"]["network"]["adapters"][0]["driver"] is None
