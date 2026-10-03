"""C7 (Linux) — HBA / InfiniBand sysfs 속성 읽기 실패를 숨기지 않는다 (os-gather/tasks/linux/gather_hba_ib.yml).

무엇을 고정하나 (2026-10-03 Phase 2 C7)
--------------------------------------
1. raw 스크립트는 sysfs 속성 파일이 **있는데 읽지 못하면** ``ERR|<경로>`` 를 남긴다
   (종전: ``2>/dev/null`` 로 삼켜 빈 값 — 증거 소실). 파일이 없는 것은 드라이버가 그 속성을 내지
   않는 것이라 실패가 아니다.
2. fc_host / infiniband 가 있고 읽기 실패가 1건 이상이면 errors[] 에 **정확히 1건**
   (section=storage, 사용자 문장, detail 에 경로 — 최대 10개). 문제없으면 종전처럼 ``[]``.
3. 기존 성공 marker(``FC|`` / ``IB|``) 와 파싱 결과는 그대로다.

검증 방법
---------
raw 본문의 ``/sys/class/{fc_host,infiniband,net}`` 를 샌드박스 트리로 치환해 실제 sh 로 실행한다.
"읽을 수 없는 속성" 은 같은 이름의 **디렉터리**로 만든다 (``cat`` 이 실패한다 — Windows 에서도 재현된다).

2026-10-03 (Plan §8-2): fc_host + infiniband 는 raw 1회(``_l_hba_raw`` — FC 구간 다음 IB 구간)이고,
NIC driver map 줄(``NIC|``)은 gather_network.yml raw gather 첫머리가 낸다(``_l_net_raw``). 이 파일은 두 자리를
각각 실행해 gather_hba_ib.yml 에 넣는다 — 출력 계약(위 1~3)은 그대로다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.unit.linux_raw_harness import (  # noqa: E402
    LINUX_TASKS,
    RunResult,
    Sandbox,
    assert_user_sentence,
    iter_tasks,
    load_tasks,
    network_nic_block,
    raw_script,
    run_task_file,
)

HBA_YML = LINUX_TASKS / "gather_hba_ib.yml"

# 이번 변경으로 추가한 사용자 문장
HBA_MESSAGE = "스토리지 어댑터 정보 중 일부를 수집하지 못했습니다. 대상 상태와 수집 로그를 확인하세요."

FC_ATTRS = {
    "port_name": "0x10000090fa1b2c3d",
    "node_name": "0x20000090fa1b2c3d",
    "symbolic_name": "Emulex LPe32002-M2 FV12.8.351.0 DV12.8.0.5",
    "port_state": "Online",
    "speed": "16 Gbit",
}
FC_SCSI_HOST = {"fw_version": "12.8.351.0", "model_name": "LPe32002-M2",
                "manufacturer": "Emulex Corporation"}
IB_ATTRS = {"node_guid": "0c42:a103:0012:3456", "fw_ver": "20.31.1014", "hca_type": "MT4123",
            "board_id": "MT_0000000223"}
IB_PORT = {"state": "4: ACTIVE", "rate": "100 Gb/sec (4X EDR)"}
IB_GID0 = "fe80:0000:0000:0000:0c42:a103:0012:3456"


@pytest.fixture
def sbx(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path / "sbx", hide=())


def _attr(path: Path, value: str | None, unreadable: bool) -> None:
    if unreadable:
        path.mkdir(parents=True, exist_ok=True)          # cat 이 실패한다 ("Is a directory")
    elif value is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value + "\n", encoding="utf-8", newline="\n")


def build_sysfs(sbx: Sandbox, *, fc: bool = True, ib: bool = True,
                unreadable: tuple[str, ...] = (), absent: tuple[str, ...] = ()) -> Path:
    """sysfs 모양 트리. unreadable / absent 는 'fc:speed', 'ib:rate', 'ib:hca_type' 형식."""
    root = sbx.root / "sys" / "class"
    (root / "net" / "eth0").mkdir(parents=True, exist_ok=True)
    if fc:
        host = root / "fc_host" / "host1"
        host.mkdir(parents=True, exist_ok=True)
        for name, value in FC_ATTRS.items():
            if f"fc:{name}" not in absent:
                _attr(host / name, value, f"fc:{name}" in unreadable)
        (host / "device" / "driver").mkdir(parents=True, exist_ok=True)
        for name, value in FC_SCSI_HOST.items():
            if f"fc:{name}" not in absent:
                _attr(host / "device" / "scsi_host" / "host1" / name, value, False)
    if ib:
        adp = root / "infiniband" / "mlx5_0"
        adp.mkdir(parents=True, exist_ok=True)
        for name, value in IB_ATTRS.items():
            if f"ib:{name}" not in absent:
                _attr(adp / name, value, f"ib:{name}" in unreadable)
        port = adp / "ports" / "1"
        port.mkdir(parents=True, exist_ok=True)
        for name, value in IB_PORT.items():
            if f"ib:{name}" not in absent:
                _attr(port / name, value, f"ib:{name}" in unreadable)
        if "ib:gid0" not in absent:
            _attr(port / "gids" / "0", IB_GID0, "ib:gid0" in unreadable)
    return root


def _sysfs(script: str, sbx: Sandbox, root: Path) -> str:
    for cls in ("fc_host", "infiniband", "net"):
        script = script.replace(f"/sys/class/{cls}", sbx.p(root / cls))
    assert "/sys/class/" not in script.replace(sbx.p(root), ""), "치환되지 않은 sysfs 경로"
    return script


def run_all(sbx: Sandbox, root: Path) -> dict[str, RunResult]:
    """hba raw(fc_host + infiniband) 1회 + network raw 의 NIC driver map 블록 — 실제 두 자리."""
    return {"_l_hba_raw": sbx.run(_sysfs(raw_script(HBA_YML, "enumerate fc_host + infiniband"), sbx, root)),
            "_l_net_raw": sbx.run(_sysfs(network_nic_block(), sbx, root))}


def render(results: dict[str, RunResult]):
    run = run_task_file(HBA_YML, {"_l_hba_raw": results["_l_hba_raw"].register()},
                        ctx={"_l_net_raw": results["_l_net_raw"].register()})
    assert not run.rescued, f"rescue 로 빠졌다 — 새 Jinja 가 죽으면 안 된다: {run.rescued}"
    return run


def err_paths(res: RunResult, cls: str | None = None) -> list[str]:
    """ERR| 경로 (cls = 'fc_host' / 'infiniband' 이면 그 sysfs 클래스만)."""
    return [row[0] for row in res.rows("ERR") if cls is None or f"/{cls}/" in row[0]]


# ═══════════════════════════════════════════════════════════════════════════
def test_clean_sysfs_has_no_err_markers_and_no_errors(sbx):
    results = run_all(sbx, build_sysfs(sbx))
    assert err_paths(results["_l_hba_raw"]) == []
    run = render(results)
    assert run.ctx["_errors_fragment"] == []
    hba = run.ctx["_data_fragment"]["storage"]["hbas"][0]
    assert hba["wwpn"] == "10:00:00:90:fa:1b:2c:3d"
    assert hba["wwnn"] == "20:00:00:90:fa:1b:2c:3d"
    assert hba["link_status"] == "up"
    assert hba["link_speed_gbps"] == 16
    assert hba["model"] == "LPe32002-M2"
    assert hba["vendor"] == "Emulex Corporation"
    assert hba["firmware"] == "12.8.351.0"
    ib = run.ctx["_data_fragment"]["storage"]["infiniband"][0]
    assert (ib["adapter"], ib["port"], ib["link_status"], ib["rate_gbps"]) == ("mlx5_0", "1", "up", 100)
    assert ib["model"] == "MT4123" and ib["vendor"] == "Mellanox"
    assert ib["port_guid"] == "0c42:a103:0012:3456"
    assert run.ctx["_sections_collected_fragment"] == ["storage", "network"]


def test_absent_optional_attribute_is_not_a_read_failure(sbx):
    """드라이버가 내지 않는 속성(파일 없음)은 실패가 아니다 — hca_type 이 없으면 board_id 로."""
    results = run_all(sbx, build_sysfs(sbx, absent=("fc:symbolic_name", "ib:hca_type")))
    assert err_paths(results["_l_hba_raw"]) == []
    run = render(results)
    assert run.ctx["_errors_fragment"] == []
    assert run.ctx["_data_fragment"]["storage"]["infiniband"][0]["model"] == "MT_0000000223"


def test_unreadable_fc_attributes_emit_err_and_one_error(sbx):
    root = build_sysfs(sbx, unreadable=("fc:speed", "fc:port_state"))
    results = run_all(sbx, root)
    host = sbx.p(root / "fc_host" / "host1")
    assert sorted(err_paths(results["_l_hba_raw"], "fc_host")) == [f"{host}/port_state", f"{host}/speed"]
    assert err_paths(results["_l_hba_raw"], "infiniband") == []
    # 성공 marker 는 그대로 — 읽은 값만 채운다
    fc_rows = results["_l_hba_raw"].rows("FC")
    assert len(fc_rows) == 1 and fc_rows[0][1] == "0x10000090fa1b2c3d"

    run = render(results)
    hba = run.ctx["_data_fragment"]["storage"]["hbas"][0]
    assert hba["link_status"] == "unknown" and hba["link_speed_gbps"] is None
    errors = run.ctx["_errors_fragment"]
    assert len(errors) == 1
    err = errors[0]
    assert err["section"] == "storage"
    assert err["message"] == HBA_MESSAGE
    assert f"{host}/port_state" in err["detail"] and f"{host}/speed" in err["detail"]
    assert "scope=fc_host;" in err["detail"]
    assert "count=2" in err["detail"]
    # 섹션 판정은 종전 그대로 (목록이 있으면 collected)
    assert run.ctx["_sections_collected_fragment"] == ["storage", "network"]
    assert run.ctx["_sections_failed_fragment"] == []


def test_fc_and_ib_failures_are_reported_as_a_single_error(sbx):
    root = build_sysfs(sbx, unreadable=("fc:speed", "ib:rate", "ib:gid0"))
    results = run_all(sbx, root)
    assert len(err_paths(results["_l_hba_raw"], "infiniband")) == 2
    # 한 raw 안에서도 종전 순서 그대로 — fc_host ERR 가 infiniband ERR 보다 먼저
    paths = err_paths(results["_l_hba_raw"])
    assert ["/fc_host/" in p for p in paths] == [True, False, False]
    run = render(results)
    errors = run.ctx["_errors_fragment"]
    assert len(errors) == 1
    assert "scope=fc_host,infiniband;" in errors[0]["detail"]
    assert "count=3" in errors[0]["detail"]
    ib = run.ctx["_data_fragment"]["storage"]["infiniband"][0]
    assert ib["rate"] is None and ib["port_guid"] is None and ib["link_status"] == "up"


def test_no_fc_host_or_infiniband_directory_means_no_error(sbx):
    results = run_all(sbx, build_sysfs(sbx, fc=False, ib=False))
    assert results["_l_hba_raw"].lines == []
    run = render(results)
    assert run.ctx["_errors_fragment"] == []
    assert run.ctx["_data_fragment"]["storage"]["hbas"] == []


# ═══════════════════════════════════════════════════════════════════════════
# Jinja 판정만 — ERR 줄 해석 / 상한 10
# ═══════════════════════════════════════════════════════════════════════════
def _reg(lines: list[str]) -> dict:
    return RunResult(0, "".join(line + "\n" for line in lines), "").register()


def test_err_paths_are_capped_at_ten_and_deduplicated():
    fc_lines = [f"ERR|/sys/class/fc_host/host{i}/speed" for i in range(12)]
    fc_lines += ["ERR|/sys/class/fc_host/host0/speed"]                     # 중복
    ib_lines = [f"ERR|/sys/class/infiniband/mlx5_{i}/ports/1/rate" for i in range(3)]
    run = run_task_file(HBA_YML, {"_l_hba_raw": _reg(fc_lines + ib_lines)}, ctx={"_l_net_raw": _reg([])})
    assert not run.rescued
    errors = run.ctx["_errors_fragment"]
    assert len(errors) == 1
    detail = errors[0]["detail"]
    assert "count=15" in detail
    listed = detail.split("paths=", 1)[1].split(" 외 ")[0].split(",")
    assert len(listed) == 10
    assert listed[0] == "/sys/class/fc_host/host0/speed"
    assert detail.endswith(" 외 5건")


def test_err_free_output_keeps_empty_errors():
    run = run_task_file(HBA_YML, {
        "_l_hba_raw": _reg(["FC|host1|0x10000090fa1b2c3d|0x20000090fa1b2c3d|sym|Online|16 Gbit|"
                            "qla2xxx|8.08|QLE2692|QLogic"])}, ctx={"_l_net_raw": _reg([])})
    assert not run.rescued
    assert run.ctx["_errors_fragment"] == []
    assert run.ctx["_data_fragment"]["storage"]["hbas"][0]["driver"] == "qla2xxx"


def test_new_user_sentence_meets_portal_quality():
    assert_user_sentence(HBA_MESSAGE, "gather_hba_ib")


# ═══════════════════════════════════════════════════════════════════════════
# Plan §8-2 — 원격 실행 3 → 1 (fc_host + infiniband 1회, driver map 은 network raw 의 NIC| 줄)
# ═══════════════════════════════════════════════════════════════════════════
def test_hba_file_has_exactly_one_remote_task():
    remote = [t.get("name") for t in iter_tasks(load_tasks(HBA_YML))
              if any(k.startswith("ansible.builtin.") and k.split(".")[-1] not in ("set_fact", "include_tasks")
                     for k in t)]
    assert remote == ["linux | hba_ib | enumerate fc_host + infiniband"]


def test_driver_map_reads_only_nic_rows_from_network_raw():
    """network raw 의 다른 줄(ADAPTER| / ETHFW| / BOND| / VLANIF| / IF= …)은 driver map 에 섞이지 않는다."""
    net_lines = ["NIC|eno1|tg3||", "IF=eno1|c4:cb:e1:dc:bc:4a|1500|1000|up|10.0.0.5|24",
                 "ADAPTER|0000:02:00.0|Broadcom Inc.|NetXtreme BCM5720|tg3", "ETHFW|02:00.0|21.80.9",
                 "BOND|bond0|802.3ad|||||||ens1f0 ens1f1", "VLANIF|bond0.64|bond0|64",
                 "NIC|bond0.64|||", "NIC|vethe088486|||docker0", "NIC|ens1f0|i40e||bond0"]
    run = run_task_file(HBA_YML, {"_l_hba_raw": _reg([])}, ctx={"_l_net_raw": _reg(net_lines)})
    assert not run.rescued
    assert run.ctx["_data_fragment"]["network"]["driver_map"] == [
        {"name": "eno1", "driver": "tg3", "vlan_id": None, "bond_master": None},
        {"name": "bond0.64", "driver": None, "vlan_id": None, "bond_master": None},
        {"name": "vethe088486", "driver": None, "vlan_id": None, "bond_master": "docker0"},
        {"name": "ens1f0", "driver": "i40e", "vlan_id": None, "bond_master": "bond0"},
    ]
    assert run.ctx["_sections_collected_fragment"] == ["network"]


def test_driver_map_is_empty_when_network_raw_is_missing():
    """network gather 가 돌지 않았으면(_l_net_raw 미정의) 죽지 않고 빈 목록 — 섹션 collected 에서 network 제외."""
    run = run_task_file(HBA_YML, {"_l_hba_raw": _reg([])})
    assert not run.rescued
    assert run.ctx["_data_fragment"]["network"]["driver_map"] == []
    assert run.ctx["_sections_collected_fragment"] == []


def _can_symlink(base: Path) -> bool:
    try:
        (base / "_probe").symlink_to(base)
        return True
    except (OSError, NotImplementedError):
        return False


def _net_tree(sbx: Sandbox) -> Path:
    """lo / 물리 NIC(드라이버 링크) / bond 와 slave / bridge 와 port / VLAN — 실제 sysfs 모양 (symlink)."""
    net = sbx.root / "sys" / "class" / "net"
    drivers = sbx.root / "sys" / "bus" / "pci" / "drivers"
    for d in ("lo", "eno1", "ens1f0", "bond0", "bond0.64", "docker0", "veth1"):
        (net / d).mkdir(parents=True, exist_ok=True)
    for nic, drv in (("eno1", "tg3"), ("ens1f0", "i40e")):
        (drivers / drv).mkdir(parents=True, exist_ok=True)
        (net / nic / "device").mkdir()
        (net / nic / "device" / "driver").symlink_to(drivers / drv, target_is_directory=True)
    for master, port in (("bond0", "ens1f0"), ("docker0", "veth1")):
        (net / master / "uevent").write_text(f"INTERFACE={master}\n", encoding="utf-8")
        (net / port / "master").symlink_to(net / master, target_is_directory=True)
    return net


def test_nic_block_reads_driver_link_and_any_master(sbx):
    """driver = device/driver 링크 이름, master = bond 뿐 아니라 bridge 도 (종전 hba raw 와 같은 규칙), lo 제외."""
    if not _can_symlink(sbx.root):
        pytest.skip("symlink 를 만들 수 없는 환경 (Windows 권한)")
    net = _net_tree(sbx)
    res = sbx.run(network_nic_block().replace("/sys/class/net", sbx.p(net)))
    rows = {r[0]: r[1:] for r in res.rows("NIC")}
    assert set(rows) == {"eno1", "ens1f0", "bond0", "bond0.64", "docker0", "veth1"}
    assert rows["eno1"] == ["tg3", "", ""]
    assert rows["ens1f0"] == ["i40e", "", "bond0"]
    assert rows["veth1"] == ["", "", "docker0"]
    assert rows["bond0"] == ["", "", ""]


def test_nic_block_vlan_id_from_proc_net_vlan(sbx):
    """2026-10-03 P3 검수에서 발견 · 수정: /proc/net/vlan/<if> 첫 줄은 커널 형식 \'<if>  VID: <n>	 REORDER_HDR: …\' 로 이름 뒤 공백이 둘이라
    종전 awk -F\'[ |]\' 의 $2 는 빈 필드 → driver_map[].vlan_id 가 항상 null 이었다 (실캡처 rhel-baremetal bond0.64 = VLAN 64)."""
    net = sbx.root / "sys" / "class" / "net" / "bond0.64"
    net.mkdir(parents=True)
    vlan_dir = sbx.root / "proc" / "net" / "vlan"
    vlan_dir.mkdir(parents=True)
    (vlan_dir / "bond0.64").write_text(
        "bond0.64  VID: 64\t REORDER_HDR: 1  dev->priv_flags: 1001\n"
        "         total frames received            0\n", encoding="utf-8")
    script = (network_nic_block().replace("/sys/class/net", sbx.p(net.parent))
              .replace("/proc/net/vlan", sbx.p(vlan_dir)))
    rows = {r[0]: r[1:] for r in sbx.run(script).rows("NIC")}
    assert rows["bond0.64"][1] == "64"
