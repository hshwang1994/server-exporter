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

2026-10-17 (InfiniBand 전면 검증 — 실장비 IB 부재, 합성 sysfs 로 모의 실행)
-------------------------------------------------------------------------
4. ``ports/<n>/link_layer`` 가 ``InfiniBand`` 인 포트만 ``IB|`` 줄이 된다 (Ethernet = RoCE/iWARP 제외, 없음 = 제외,
   있는데 못 읽음 = ``ERR|`` + 제외). 장치가 아니라 **포트** 단위다.
5. ``rate_gbps`` 는 state ACTIVE 일 때만 숫자(2.5 같은 소수 보존). DOWN/INIT/ARMED/ACTIVE_DEFER 는 null.
6. vendor/model 은 ``device/uevent`` 의 PCI_SLOT_NAME → ``lspci -mm -s`` 이름. lspci 는 CONTROLLED 라 호스트 것이
   섞이지 않도록 숨기고 shim 으로만 답한다 (``lspci_shim``). 없으면 vendor null / model=hca_type.
7. GUID 는 ``normalize_ib_guid`` (all-zero · 형식 오류 → null). port_guid = gids/0 하위 4묶음.
입력값 형식의 근거는 gather_hba_ib.yml 헤더의 source 줄(kernel sysfs ABI · sysfs.c · rdma-core umad.c · RFC 4392).
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
# 커널 sysfs.c 출력 형식: state "%d: %s", rate "%d[.5] Gb/sec (%dX %s)", link_layer "InfiniBand"/"Ethernet"
IB_PORT = {"state": "4: ACTIVE", "rate": "100 Gb/sec (4X EDR)", "link_layer": "InfiniBand"}
IB_GID0 = "fe80:0000:0000:0000:0c42:a103:0012:3456"
IB_PCI = "0000:be:00.0"
IB_UEVENT = f"DRIVER=mlx5_core\nPCI_CLASS=20700\nPCI_ID=15B3:101B\nPCI_SLOT_NAME={IB_PCI}\nMODALIAS=pci:v000015B3d0000101Bsv000015B3sd00000007bc02sc07i00\n"
# lspci -mm -s 0000:be:00.0 출력 모양 (pci.ids 이름 — 필드: slot "class" "vendor" "device" -rNN "subvendor" "subdevice")
IB_LSPCI = 'be:00.0 "Infiniband controller" "Mellanox Technologies" "MT28908 Family [ConnectX-6]" "Mellanox Technologies" "Device 0007"'


@pytest.fixture
def sbx(tmp_path: Path) -> Sandbox:
    # lspci 만 숨긴다: 호스트(Linux)의 /usr/bin/lspci 가 fixture 의 PCI 주소에 답하면 결과가 호스트에 따라 바뀐다.
    # 나머지 도구는 이 파일의 raw 가 쓰지 않는다(종전 hide=() 와 같은 빠른 경로).
    return Sandbox(tmp_path / "sbx", hide=("lspci",))


def lspci_shim(sbx: Sandbox, table: dict[str, str] | None = None) -> Path:
    """`lspci -mm -s <addr>` 만 답하는 shim — 호출을 기록해 장치당 1회만 불렸는지 본다. 모르는 인자는 exit 1."""
    calls = sbx.data / "lspci_calls.txt"
    table = {f"-mm -s {IB_PCI}": IB_LSPCI} if table is None else table
    cases = "".join(f"  \"{args}\") printf '%s\\n' '{line}' ;;\n" for args, line in table.items())
    sbx.shim_cmd("lspci", f'echo "$*" >> \'{sbx.p(calls)}\'\ncase "$*" in\n{cases}  *) exit 1 ;;\nesac\n')
    return calls


def lspci_calls(calls: Path) -> list[str]:
    return calls.read_text(encoding="utf-8").split("\n")[:-1] if calls.exists() else []


def _attr(path: Path, value: str | None, unreadable: bool) -> None:
    if unreadable:
        path.mkdir(parents=True, exist_ok=True)          # cat 이 실패한다 ("Is a directory")
    elif value is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value + "\n", encoding="utf-8", newline="\n")


def add_ib_device(root: Path, name: str, *, attrs: dict[str, str | None] | None = None,
                  ports: dict[str, dict[str, str | None]] | None = None, uevent: str | None = IB_UEVENT,
                  unreadable: tuple[str, ...] = (), absent: tuple[str, ...] = ()) -> Path:
    """/sys/class/infiniband/<name> 장치 하나. ports = {"1": {state, rate, link_layer, gid0}} (None 값 = 파일 없음).
    unreadable / absent 는 'ib:link_layer' · 'ib:uevent' · 'ib:rate' 처럼 장치 안 모든 포트에 같이 적용된다."""
    adp = root / "infiniband" / name
    adp.mkdir(parents=True, exist_ok=True)
    for key, value in (IB_ATTRS if attrs is None else attrs).items():
        if f"ib:{key}" not in absent:
            _attr(adp / key, value, f"ib:{key}" in unreadable)
    if "ib:uevent" not in absent:
        _attr(adp / "device" / "uevent", uevent, "ib:uevent" in unreadable)
    for pname, pattrs in ({"1": dict(IB_PORT, gid0=IB_GID0)} if ports is None else ports).items():
        port = adp / "ports" / pname
        port.mkdir(parents=True, exist_ok=True)
        for key, value in pattrs.items():
            if f"ib:{key}" in absent:
                continue
            target = port / "gids" / "0" if key == "gid0" else port / key
            _attr(target, value, f"ib:{key}" in unreadable)
    return adp


def build_sysfs(sbx: Sandbox, *, fc: bool = True, ib: bool = True,
                unreadable: tuple[str, ...] = (), absent: tuple[str, ...] = ()) -> Path:
    """sysfs 모양 트리. unreadable / absent 는 'fc:speed', 'ib:rate', 'ib:hca_type', 'ib:link_layer', 'ib:uevent' 형식."""
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
        add_ib_device(root, "mlx5_0", unreadable=unreadable, absent=absent)
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
    calls = lspci_shim(sbx)
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
    assert isinstance(ib["rate_gbps"], int)
    assert ib["rate"] == "100 Gb/sec (4X EDR)"
    # 2026-10-17: 제조사/장치명은 lspci(pci.ids) 이름 — 종전 "MT4123 / Mellanox(접두 추정)" 가 아니다
    assert ib["model"] == "MT28908 Family [ConnectX-6]" and ib["vendor"] == "Mellanox Technologies"
    assert ib["node_guid"] == "0c42:a103:0012:3456"
    assert ib["port_guid"] == "0c42:a103:0012:3456"
    assert ib["firmware"] == "20.31.1014" and ib["source"] == "os"
    assert set(ib) == {"adapter", "port", "node_guid", "port_guid", "link_status", "rate", "rate_gbps",
                       "model", "vendor", "firmware", "source"}
    from tests.regression.test_hba_ib_canonical import assert_ib_entry_canonical   # 시나리오 28 — 4채널 공통 계약
    assert_ib_entry_canonical(ib, "linux clean")
    assert lspci_calls(calls) == [f"-mm -s {IB_PCI}"], "lspci 는 장치당 1회"
    assert run.ctx["_sections_collected_fragment"] == ["storage", "network"]


def test_absent_optional_attribute_is_not_a_read_failure(sbx):
    """드라이버가 내지 않는 속성(파일 없음)은 실패가 아니다 — hca_type 이 없으면 board_id 로.
    lspci 가 없는(shim 미설치 = 최소 환경) 호스트에서는 vendor 가 null 이고 model 은 칩 식별자다 — 추정하지 않는다."""
    results = run_all(sbx, build_sysfs(sbx, absent=("fc:symbolic_name", "ib:hca_type")))
    assert err_paths(results["_l_hba_raw"]) == []
    run = render(results)
    assert run.ctx["_errors_fragment"] == []
    ib = run.ctx["_data_fragment"]["storage"]["infiniband"][0]
    assert ib["model"] == "MT_0000000223" and ib["vendor"] is None


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
    """시나리오 1 — IB 장치 없음: 빈 목록, 오류 없음 (장치 부재의 확정 증거는 아니다 — 드라이버 미적재도 같은 모양)."""
    results = run_all(sbx, build_sysfs(sbx, fc=False, ib=False))
    assert results["_l_hba_raw"].lines == []
    run = render(results)
    assert run.ctx["_errors_fragment"] == []
    assert run.ctx["_data_fragment"]["storage"]["hbas"] == []
    assert run.ctx["_data_fragment"]["storage"]["infiniband"] == []


# ═══════════════════════════════════════════════════════════════════════════
# 2026-10-17 — InfiniBand 포트 판별 · 상태 · 속도 · GUID (합성 sysfs, 실장비 아님)
# ═══════════════════════════════════════════════════════════════════════════
def _ib_only(sbx: Sandbox) -> Path:
    """fc_host 없이 infiniband 클래스만 있는 루트 (장치는 호출자가 add_ib_device 로 넣는다)."""
    return build_sysfs(sbx, fc=False, ib=False)


def _ib_entries(sbx: Sandbox, root: Path) -> tuple[list[dict], dict[str, RunResult], object]:
    results = run_all(sbx, root)
    run = render(results)
    return run.ctx["_data_fragment"]["storage"]["infiniband"], results, run


def test_roce_port_is_excluded(sbx):
    """시나리오 3 — mlx5 이더넷 모드(RoCE): /sys/class/infiniband 에 등록되고 rate 도 IB 이름(4X EDR)으로 찍히지만
    link_layer 가 Ethernet 이라 IB 가 아니다. 오류도 아니다 (정상 판별)."""
    lspci_shim(sbx)
    root = _ib_only(sbx)
    add_ib_device(root, "mlx5_0", ports={"1": {"state": "4: ACTIVE", "rate": "100 Gb/sec (4X EDR)", "link_layer": "Ethernet",
                                               "gid0": "fe80:0000:0000:0000:0e42:a1ff:fe03:1234"}})
    entries, results, run = _ib_entries(sbx, root)
    assert results["_l_hba_raw"].rows("IB") == []
    assert entries == [] and run.ctx["_errors_fragment"] == []
    assert "storage" not in run.ctx["_sections_collected_fragment"]


def test_iwarp_rnic_is_excluded(sbx):
    """시나리오 4 — iWARP RNIC(cxgb4/irdma): node_type 3: RNIC, link_layer Ethernet → 제외. node_type 은 읽지 않는다
    (mlx5 는 RoCE 도 '1: CA' 라 구분 근거가 못 된다)."""
    root = _ib_only(sbx)
    add_ib_device(root, "cxgb4_0", attrs={"node_guid": "0007:4301:5c3f:5e10", "fw_ver": "1.26.6.0", "node_type": "3: RNIC"},
                  uevent="DRIVER=cxgb4\nPCI_SLOT_NAME=0000:3b:00.4\n",
                  ports={"1": {"state": "4: ACTIVE", "rate": "25 Gb/sec (1X EDR)", "link_layer": "Ethernet", "gid0": IB_GID0}})
    entries, results, _ = _ib_entries(sbx, root)
    assert results["_l_hba_raw"].rows("IB") == [] and entries == []


def test_two_port_hca_yields_two_entries(sbx):
    """시나리오 5 — 2포트 HCA: 포트마다 항목 1개, node_guid 는 같고 port_guid 는 다르다, lspci 는 장치당 1회."""
    calls = lspci_shim(sbx)
    root = _ib_only(sbx)
    add_ib_device(root, "mlx5_0", ports={
        "1": {"state": "4: ACTIVE", "rate": "200 Gb/sec (4X HDR)", "link_layer": "InfiniBand",
              "gid0": "fe80:0000:0000:0000:0c42:a103:0012:3456"},
        "2": {"state": "4: ACTIVE", "rate": "200 Gb/sec (4X HDR)", "link_layer": "InfiniBand",
              "gid0": "fe80:0000:0000:0000:0c42:a103:0012:3457"}})
    entries, _, run = _ib_entries(sbx, root)
    assert [(e["adapter"], e["port"]) for e in entries] == [("mlx5_0", "1"), ("mlx5_0", "2")]
    assert {e["node_guid"] for e in entries} == {"0c42:a103:0012:3456"}
    assert [e["port_guid"] for e in entries] == ["0c42:a103:0012:3456", "0c42:a103:0012:3457"]
    assert [e["rate_gbps"] for e in entries] == [200, 200]
    assert lspci_calls(calls) == [f"-mm -s {IB_PCI}"]
    assert run.ctx["_sections_collected_fragment"][0] == "storage"


def test_vpi_card_emits_only_infiniband_port(sbx):
    """시나리오 6 — VPI 카드 포트1 InfiniBand + 포트2 Ethernet: 포트 단위 판정이라 포트1 만 남는다."""
    lspci_shim(sbx)
    root = _ib_only(sbx)
    add_ib_device(root, "mlx5_0", ports={
        "1": {"state": "4: ACTIVE", "rate": "100 Gb/sec (4X EDR)", "link_layer": "InfiniBand", "gid0": IB_GID0},
        "2": {"state": "4: ACTIVE", "rate": "100 Gb/sec (4X EDR)", "link_layer": "Ethernet",
              "gid0": "fe80:0000:0000:0000:0e42:a1ff:fe03:1235"}})
    entries, _, _ = _ib_entries(sbx, root)
    assert [(e["adapter"], e["port"]) for e in entries] == [("mlx5_0", "1")]


def test_down_port_included_rate_gbps_null(sbx):
    """시나리오 7 — 링크 DOWN: 항목은 남고 link_status=down. 커널 rate_show 는 DOWN 포트에도 기본값(SDR)을 찍으므로
    rate 원문은 보존하되 rate_gbps 는 null (현재 협상 속도가 아니다)."""
    lspci_shim(sbx)
    root = _ib_only(sbx)
    add_ib_device(root, "mlx5_0", ports={"1": {"state": "1: DOWN", "rate": "10 Gb/sec (4X SDR)", "link_layer": "InfiniBand",
                                               "gid0": IB_GID0}})
    entries, _, run = _ib_entries(sbx, root)
    assert len(entries) == 1
    ib = entries[0]
    assert ib["link_status"] == "down" and ib["rate_gbps"] is None and ib["rate"] == "10 Gb/sec (4X SDR)"
    assert ib["port_guid"] == "0c42:a103:0012:3456"
    assert run.ctx["_errors_fragment"] == []


@pytest.mark.parametrize("state", ["2: INIT", "3: ARMED", "5: ACTIVE_DEFER", "0: NOP", "junk"])
def test_init_armed_defer_states_are_unknown(sbx, state):
    """시나리오 8 — 중간 상태(INIT/ARMED/ACTIVE_DEFER)와 알 수 없는 값은 unknown. 종전 부분 문자열 판정은 ACTIVE_DEFER 를 up 으로 봤다."""
    root = _ib_only(sbx)
    add_ib_device(root, "mlx5_0", ports={"1": {"state": state, "rate": "100 Gb/sec (4X EDR)", "link_layer": "InfiniBand",
                                               "gid0": IB_GID0}})
    entries, _, _ = _ib_entries(sbx, root)
    assert len(entries) == 1
    assert entries[0]["link_status"] == "unknown" and entries[0]["rate_gbps"] is None


def test_missing_state_attribute_is_unknown_not_down(sbx):
    """state 파일이 없으면(드라이버가 내지 않음) DOWN 이 아니라 unknown — 미확인과 DOWN 을 같이 취급하지 않는다."""
    root = _ib_only(sbx)
    add_ib_device(root, "mlx5_0", ports={"1": {"rate": "100 Gb/sec (4X EDR)", "link_layer": "InfiniBand", "gid0": IB_GID0}})
    entries, results, run = _ib_entries(sbx, root)
    assert entries[0]["link_status"] == "unknown"
    assert err_paths(results["_l_hba_raw"]) == [] and run.ctx["_errors_fragment"] == []


@pytest.mark.parametrize("node_guid, gid0, exp_node, exp_port", [
    ("0c42:a103:0012:3456", "fe80:0000:0000:0000:0c42:a103:0012:3456", "0c42:a103:0012:3456", "0c42:a103:0012:3456"),
    # 서브넷 prefix 가 기본값(fe80)이 아니어도 하위 64비트가 port GUID 다 (RFC 4392 §1.2)
    ("0c42:a103:0012:3456", "fec0:0000:0000:0001:0c42:a103:0012:3457", "0c42:a103:0012:3456", "0c42:a103:0012:3457"),
    (None, None, None, None),                                                          # 파일 없음
    ("0000:0000:0000:0000", "0000:0000:0000:0000:0000:0000:0000:0000", None, None),     # all-zero (미할당 / 예약 항목)
    ("zz", "fe80::0c42:a103:0012:3456", None, None),                                   # 형식 오류 / 압축 표기(8묶음 아님)
    ("0c42:a103:0012:3456", "fe80:0000:0000:0000:0c42:a103:0012", "0c42:a103:0012:3456", None),   # 7묶음
    ("0C42:A103:0012:3456", "FE80:0000:0000:0000:0C42:A103:0012:3456", "0c42:a103:0012:3456", "0c42:a103:0012:3456"),
])
def test_missing_zero_malformed_guids_are_null(sbx, node_guid, gid0, exp_node, exp_port):
    """시나리오 9 — GUID 정상/누락/오류: 확인된 값만 소문자 4묶음으로, 나머지는 null (값을 만들지 않는다)."""
    root = _ib_only(sbx)
    attrs = dict(IB_ATTRS)
    if node_guid is None:
        attrs.pop("node_guid")
    else:
        attrs["node_guid"] = node_guid
    port = {"state": "4: ACTIVE", "rate": "100 Gb/sec (4X EDR)", "link_layer": "InfiniBand"}
    if gid0 is not None:
        port["gid0"] = gid0
    add_ib_device(root, "mlx5_0", attrs=attrs, ports={"1": port})
    entries, results, run = _ib_entries(sbx, root)
    assert len(entries) == 1 and err_paths(results["_l_hba_raw"]) == [] and run.ctx["_errors_fragment"] == []
    assert (entries[0]["node_guid"], entries[0]["port_guid"]) == (exp_node, exp_port)


@pytest.mark.parametrize("rate, state, exp_rate, exp_gbps", [
    ("2.5 Gb/sec (1X SDR)", "4: ACTIVE", "2.5 Gb/sec (1X SDR)", 2.5),      # 시나리오 10 — 종전 25 로 읽던 값
    ("10 Gb/sec (4X SDR)", "4: ACTIVE", "10 Gb/sec (4X SDR)", 10),
    ("25 Gb/sec (1X EDR)", "4: ACTIVE", "25 Gb/sec (1X EDR)", 25),
    ("100 Gb/sec (4X EDR)", "4: ACTIVE", "100 Gb/sec (4X EDR)", 100),
    ("200 Gb/sec (4X HDR)", "4: ACTIVE", "200 Gb/sec (4X HDR)", 200),
    ("400 Gb/sec (4X NDR)", "4: ACTIVE", "400 Gb/sec (4X NDR)", 400),
    ("800 Gb/sec (4X XDR)", "4: ACTIVE", "800 Gb/sec (4X XDR)", 800),
    ("unknown", "4: ACTIVE", "unknown", None),                               # 시나리오 11 — 파싱 불가: 원문만
    ("0 Gb/sec (4X)", "4: ACTIVE", None, None),                              # 0 = 속도 없음
    (None, "4: ACTIVE", None, None),                                         # 속성 누락
    ("100 Gb/sec (4X EDR)", "1: DOWN", "100 Gb/sec (4X EDR)", None),         # DOWN 은 숫자 없음
])
def test_rate_parsing_keeps_decimal_and_nulls_when_not_active(sbx, rate, state, exp_rate, exp_gbps):
    root = _ib_only(sbx)
    port = {"state": state, "link_layer": "InfiniBand", "gid0": IB_GID0}
    if rate is not None:
        port["rate"] = rate
    add_ib_device(root, "mlx5_0", ports={"1": port})
    entries, _, _ = _ib_entries(sbx, root)
    assert len(entries) == 1
    assert (entries[0]["rate"], entries[0]["rate_gbps"]) == (exp_rate, exp_gbps)
    if exp_gbps is not None:
        assert type(entries[0]["rate_gbps"]) is (float if exp_gbps != int(exp_gbps) else int)


def test_unreadable_link_layer_emits_err_and_excludes_port(sbx):
    """시나리오 24 — link_layer 가 있는데 읽지 못하면 IB 로 추정하지 않고(포트 제외) 근거를 errors[] 에 남긴다."""
    root = _ib_only(sbx)
    add_ib_device(root, "mlx5_0", unreadable=("ib:link_layer",))
    entries, results, run = _ib_entries(sbx, root)
    assert entries == []
    assert err_paths(results["_l_hba_raw"], "infiniband") == [sbx.p(root / "infiniband" / "mlx5_0" / "ports" / "1" / "link_layer")]
    errors = run.ctx["_errors_fragment"]
    assert len(errors) == 1 and errors[0]["section"] == "storage" and errors[0]["message"] == HBA_MESSAGE
    assert "scope=infiniband;" in errors[0]["detail"] and "count=1" in errors[0]["detail"]


def test_unreadable_uevent_emits_err_but_keeps_port(sbx):
    """uevent 는 장치 수준이고 제조사/장치명에만 쓰인다 — 못 읽어도 포트는 남고(vendor null, model=hca) ERR 만 기록."""
    calls = lspci_shim(sbx)
    root = _ib_only(sbx)
    add_ib_device(root, "mlx5_0", unreadable=("ib:uevent",))
    entries, results, run = _ib_entries(sbx, root)
    assert len(entries) == 1
    assert entries[0]["vendor"] is None and entries[0]["model"] == "MT4123"
    assert lspci_calls(calls) == [], "PCI 주소를 모르면 lspci 를 부르지 않는다"
    assert err_paths(results["_l_hba_raw"], "infiniband") == [sbx.p(root / "infiniband" / "mlx5_0" / "device" / "uevent")]
    assert "scope=infiniband;" in run.ctx["_errors_fragment"][0]["detail"]


def test_absent_link_layer_attribute_excludes_port_silently(sbx):
    """link_layer 파일 자체가 없으면(구형 드라이버) IB 로 확정할 근거가 없다 — 제외, 오류 아님."""
    root = _ib_only(sbx)
    add_ib_device(root, "mlx5_0", absent=("ib:link_layer",))
    entries, results, run = _ib_entries(sbx, root)
    assert entries == [] and err_paths(results["_l_hba_raw"]) == [] and run.ctx["_errors_fragment"] == []


def test_lspci_placeholder_names_fall_back_to_hca_type(sbx):
    """lspci 가 pci.ids 에 없는 ID 를 만나면 'Device 1021' / 'Vendor 15b3' 자리표시자를 낸다 — 이름이 아니므로 쓰지 않는다."""
    lspci_shim(sbx, {f"-mm -s {IB_PCI}": 'be:00.0 "Infiniband controller" "Vendor 15b3" "Device 1021" "Vendor 15b3" "Device 0007"'})
    root = _ib_only(sbx)
    add_ib_device(root, "mlx5_0")
    entries, _, _ = _ib_entries(sbx, root)
    assert entries[0]["vendor"] is None and entries[0]["model"] == "MT4123"


def test_pipe_in_lspci_name_does_not_break_the_row(sbx):
    lspci_shim(sbx, {f"-mm -s {IB_PCI}": 'be:00.0 "Infiniband controller" "Mellanox|Technologies" "MT28908 Family [ConnectX-6]"'})
    root = _ib_only(sbx)
    add_ib_device(root, "mlx5_0")
    entries, results, _ = _ib_entries(sbx, root)
    assert len(results["_l_hba_raw"].rows("IB")[0]) == 12          # rows() 는 'IB' 접두를 뺀다 — 총 13 필드
    assert entries[0]["vendor"] == "MellanoxTechnologies"


def test_ib_row_has_13_fields_and_old_9_field_prefix_is_unchanged(sbx):
    """줄 형식 계약: 앞 9 필드는 종전 그대로, 뒤 4 필드(link_layer · pci_addr · pci_vendor · pci_device)가 추가됐다."""
    lspci_shim(sbx)
    root = _ib_only(sbx)
    add_ib_device(root, "mlx5_0")
    results = run_all(sbx, root)
    row = results["_l_hba_raw"].rows("IB")[0]
    assert row == ["mlx5_0", "1", "0c42:a103:0012:3456", IB_GID0, "ACTIVE", "100 Gb/sec (4X EDR)", "20.31.1014", "MT4123",
                   "InfiniBand", IB_PCI, "Mellanox Technologies", "MT28908 Family [ConnectX-6]"]


def test_old_nine_field_ib_row_still_parses_without_pci_values():
    """구 형식(9 필드) 줄도 파싱된다 — vendor null, model=hca (Jinja 판정만)."""
    run = run_task_file(HBA_YML, {"_l_hba_raw": _reg([f"IB|mlx5_0|1|0c42:a103:0012:3456|{IB_GID0}|ACTIVE|100 Gb/sec (4X EDR)|20.31.1014|MT4123"])},
                        ctx={"_l_net_raw": _reg([])})
    assert not run.rescued
    ib = run.ctx["_data_fragment"]["storage"]["infiniband"][0]
    assert (ib["vendor"], ib["model"], ib["rate_gbps"], ib["link_status"]) == (None, "MT4123", 100, "up")


def test_same_input_twice_is_identical(sbx):
    """시나리오 26 — 같은 입력을 두 번 수집하면 결과(항목 순서 포함)가 같다."""
    lspci_shim(sbx)
    root = _ib_only(sbx)
    add_ib_device(root, "mlx5_0", ports={
        "1": {"state": "4: ACTIVE", "rate": "100 Gb/sec (4X EDR)", "link_layer": "InfiniBand", "gid0": IB_GID0},
        "2": {"state": "1: DOWN", "rate": "10 Gb/sec (4X SDR)", "link_layer": "InfiniBand",
              "gid0": "fe80:0000:0000:0000:0c42:a103:0012:3457"}})
    first, _, _ = _ib_entries(sbx, root)
    second, _, _ = _ib_entries(sbx, root)
    assert first == second and len(first) == 2
    from tests.regression.test_hba_ib_canonical import assert_ib_entry_canonical
    for i, e in enumerate(first):
        assert_ib_entry_canonical(e, f"linux stable[{i}]")


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


# ── GP-23 (2026-10-05): 비루트 수집에서 /proc/net/vlan/<if> 는 읽히지 않는다 (커널 0600) ─────────────────────────────────────────────
IP_VLAN_OUT = ("7: bond0.64@bond0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP mode DEFAULT group default qlen 1000\n"
               "    link/ether aa:bb:cc:dd:ee:ff brd ff:ff:ff:ff:ff:ff promiscuity 0 allmulti 0 minmtu 0 maxmtu 65535\n"
               "    vlan protocol 802.1Q id 64 <REORDER_HDR> addrgenmode eui64 numtxqueues 1 numrxqueues 1\n")


def _vlan_net(sbx: Sandbox) -> Path:
    """bond0.64(VLAN — uevent DEVTYPE=vlan) · eno1(물리, VLAN 아님) — 링크 없이 디렉터리만(Windows 에서도 돈다)."""
    net = sbx.root / "sys" / "class" / "net"
    (net / "bond0.64").mkdir(parents=True)
    (net / "bond0.64" / "uevent").write_text("DEVTYPE=vlan\nINTERFACE=bond0.64\nIFINDEX=7\n", encoding="utf-8")
    (net / "eno1").mkdir(parents=True)
    (net / "eno1" / "uevent").write_text("INTERFACE=eno1\nIFINDEX=2\n", encoding="utf-8")
    return net


def _ip_shim(sbx: Sandbox) -> Path:
    """`ip -d link show dev <if>` 만 답하는 shim — 호출을 기록해 VLAN 장치에서만 불렸는지 본다."""
    calls = sbx.data / "ip_calls.txt"
    out = sbx.data_file("ip_vlan_out.txt", IP_VLAN_OUT)
    sbx.shim_cmd("ip", f'echo "$*" >> \'{sbx.p(calls)}\'\n'
                       f'case "$*" in\n  "-d link show dev bond0.64") cat \'{out}\' ;;\n  *) exit 1 ;;\nesac\n')
    return calls


def test_nic_block_vlan_id_falls_back_to_netlink_without_proc_entry(sbx):
    """GP-23: /proc/net/vlan 이 없거나(8021q proc 미노출) 비어 있으면 VLAN 장치(uevent DEVTYPE=vlan)에 한해 `ip -d link show dev` 의 id 를 쓴다.
    VLAN 이 아닌 장치에는 ip 를 부르지 않는다 (원격 실행 비용 · 출력 계약 불변)."""
    net = _vlan_net(sbx)
    calls = _ip_shim(sbx)
    script = (network_nic_block().replace("/sys/class/net", sbx.p(net))
              .replace("/proc/net/vlan", sbx.p(sbx.root / "proc_absent" / "vlan")))
    rows = {r[0]: r[1:] for r in sbx.run(script).rows("NIC")}
    assert rows["bond0.64"][1] == "64", rows
    assert rows["eno1"][1] == "", "VLAN 이 아닌 장치는 비어 있다"
    assert calls.read_text(encoding="utf-8").split("\n")[:-1] == ["-d link show dev bond0.64"], "ip 는 VLAN 장치에서만"


def test_nic_block_vlan_id_from_netlink_when_proc_entry_is_unreadable(sbx):
    """실장비 재현 조건(2026-10-04 production #88 .96/.95): 항목은 있는데(-f 참) 비루트라 읽기 실패 → netlink 로 64.
    Windows(chmod 무효) · root 실행에서는 읽기 실패를 만들 수 없어 건너뛴다."""
    import os
    net = _vlan_net(sbx)
    vlan_dir = sbx.root / "proc" / "net" / "vlan"
    vlan_dir.mkdir(parents=True)
    entry = vlan_dir / "bond0.64"
    entry.write_text("bond0.64  VID: 64\t REORDER_HDR: 1  dev->priv_flags: 1001\n", encoding="utf-8")
    entry.chmod(0)
    try:
        if os.access(entry, os.R_OK):
            pytest.skip("읽기 권한을 막을 수 없는 환경 (Windows 또는 root)")
        calls = _ip_shim(sbx)
        script = (network_nic_block().replace("/sys/class/net", sbx.p(net)).replace("/proc/net/vlan", sbx.p(vlan_dir)))
        rows = {r[0]: r[1:] for r in sbx.run(script).rows("NIC")}
        assert rows["bond0.64"][1] == "64", rows
        assert "-d link show dev bond0.64" in calls.read_text(encoding="utf-8")
    finally:
        entry.chmod(0o644)


def test_nic_block_readable_proc_entry_wins_and_netlink_is_not_called(sbx):
    """root 수집(또는 읽기 가능한 proc)이면 종전대로 /proc 값을 쓰고 ip 는 부르지 않는다."""
    net = _vlan_net(sbx)
    vlan_dir = sbx.root / "proc" / "net" / "vlan"
    vlan_dir.mkdir(parents=True)
    (vlan_dir / "bond0.64").write_text("bond0.64  VID: 64\t REORDER_HDR: 1  dev->priv_flags: 1001\n", encoding="utf-8")
    calls = _ip_shim(sbx)
    script = (network_nic_block().replace("/sys/class/net", sbx.p(net)).replace("/proc/net/vlan", sbx.p(vlan_dir)))
    rows = {r[0]: r[1:] for r in sbx.run(script).rows("NIC")}
    assert rows["bond0.64"][1] == "64"
    assert not calls.exists(), "proc 값이 있으면 netlink 를 부르지 않는다"


def test_nic_block_without_ip_command_keeps_vlan_empty(tmp_path):
    """ip 가 없는 최소 환경: 실패 없이 빈 값(null) — 종전 동작과 같다."""
    from tests.unit.linux_raw_harness import CONTROLLED
    sbx = Sandbox(tmp_path, hide=CONTROLLED + ("ip",))
    net = _vlan_net(sbx)
    script = (network_nic_block().replace("/sys/class/net", sbx.p(net))
              .replace("/proc/net/vlan", sbx.p(sbx.root / "proc_absent" / "vlan")))
    res = sbx.run(script)
    rows = {r[0]: r[1:] for r in res.rows("NIC")}
    assert rows["bond0.64"][1] == "" and res.rc == 0
