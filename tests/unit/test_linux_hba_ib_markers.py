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


def run_all(sbx: Sandbox, root: Path) -> dict[str, RunResult]:
    out = {}
    for register, name in (("_l_fc_raw", "enumerate fc_host"),
                           ("_l_ib_raw", "enumerate infiniband"),
                           ("_l_nicdrv_raw", "NIC driver map")):
        script = raw_script(HBA_YML, name)
        for cls in ("fc_host", "infiniband", "net"):
            script = script.replace(f"/sys/class/{cls}", sbx.p(root / cls))
        assert "/sys/class/" not in script.replace(sbx.p(root), ""), "치환되지 않은 sysfs 경로"
        out[register] = sbx.run(script)
    return out


def render(results: dict[str, RunResult]):
    run = run_task_file(HBA_YML, {k: v.register() for k, v in results.items()})
    assert not run.rescued, f"rescue 로 빠졌다 — 새 Jinja 가 죽으면 안 된다: {run.rescued}"
    return run


def err_paths(res: RunResult) -> list[str]:
    return [row[0] for row in res.rows("ERR")]


# ═══════════════════════════════════════════════════════════════════════════
def test_clean_sysfs_has_no_err_markers_and_no_errors(sbx):
    results = run_all(sbx, build_sysfs(sbx))
    assert err_paths(results["_l_fc_raw"]) == []
    assert err_paths(results["_l_ib_raw"]) == []
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
    assert err_paths(results["_l_fc_raw"]) == []
    assert err_paths(results["_l_ib_raw"]) == []
    run = render(results)
    assert run.ctx["_errors_fragment"] == []
    assert run.ctx["_data_fragment"]["storage"]["infiniband"][0]["model"] == "MT_0000000223"


def test_unreadable_fc_attributes_emit_err_and_one_error(sbx):
    root = build_sysfs(sbx, unreadable=("fc:speed", "fc:port_state"))
    results = run_all(sbx, root)
    host = sbx.p(root / "fc_host" / "host1")
    assert sorted(err_paths(results["_l_fc_raw"])) == [f"{host}/port_state", f"{host}/speed"]
    # 성공 marker 는 그대로 — 읽은 값만 채운다
    fc_rows = results["_l_fc_raw"].rows("FC")
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
    assert len(err_paths(results["_l_ib_raw"])) == 2
    run = render(results)
    errors = run.ctx["_errors_fragment"]
    assert len(errors) == 1
    assert "scope=fc_host,infiniband;" in errors[0]["detail"]
    assert "count=3" in errors[0]["detail"]
    ib = run.ctx["_data_fragment"]["storage"]["infiniband"][0]
    assert ib["rate"] is None and ib["port_guid"] is None and ib["link_status"] == "up"


def test_no_fc_host_or_infiniband_directory_means_no_error(sbx):
    results = run_all(sbx, build_sysfs(sbx, fc=False, ib=False))
    assert results["_l_fc_raw"].lines == [] and results["_l_ib_raw"].lines == []
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
    run = run_task_file(HBA_YML, {"_l_fc_raw": _reg(fc_lines), "_l_ib_raw": _reg(ib_lines),
                                  "_l_nicdrv_raw": _reg([])})
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
        "_l_fc_raw": _reg(["FC|host1|0x10000090fa1b2c3d|0x20000090fa1b2c3d|sym|Online|16 Gbit|"
                           "qla2xxx|8.08|QLE2692|QLogic"]),
        "_l_ib_raw": _reg([]), "_l_nicdrv_raw": _reg([])})
    assert not run.rescued
    assert run.ctx["_errors_fragment"] == []
    assert run.ctx["_data_fragment"]["storage"]["hbas"][0]["driver"] == "qla2xxx"


def test_new_user_sentence_meets_portal_quality():
    assert_user_sentence(HBA_MESSAGE, "gather_hba_ib")
