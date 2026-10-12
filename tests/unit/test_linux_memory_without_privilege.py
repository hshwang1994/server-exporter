"""Linux memory — sudo(become) 가 실패해도 OS 가 인식한 메모리 총량은 남는다 (2026-10-12).

재현한 결함: /proc/meminfo 를 특권 collector(become) 에서만 읽어, become 이 실패하면(비밀번호 불일치 · sudoers 부재)
memory 섹션이 failed 가 되고 "메모리 정보 수집에 실패했습니다" 가 나갔다 — 권한 없이 읽을 수 있는 값인데도.

고친 규칙: 비특권 raw gather(gather_system.yml) 가 MemTotal/MemAvailable 도 읽고, gather_memory.yml 은 특권 값이 없을 때 그 값을 쓴다
→ total_basis=os_visible, 섹션 success, 기존 os_visible 경고 1건(detail 에 cause=privilege_failed).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.unit.linux_raw_harness import (  # noqa: E402
    LINUX_TASKS, SYSTEM_YML, Sandbox, raw_script, run_task_file, shared_dmi_raw,
)

MEM_YML = LINUX_TASKS / "gather_memory.yml"
MEMINFO = "MemTotal:       16127952 kB\nMemFree:         1000000 kB\nMemAvailable:   12000000 kB\n"
OS_VISIBLE_MESSAGE = ("메모리 총 용량을 물리 설치량이 아닌 운영체제 인식 값으로 수집했습니다. "
                      "수집 계정의 권한을 확인하세요.")


@pytest.fixture
def sbx(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path / "sbx", hide=("dmidecode", "sudo"))


def _unprivileged_raw(sbx: Sandbox) -> dict:
    script = raw_script(SYSTEM_YML, "raw gather (os-release")
    meminfo = sbx.data_file("meminfo", MEMINFO)
    res = sbx.run(script.replace("/proc/meminfo", f"'{meminfo}'"))
    assert res.rc == 0
    return res.register()


def _parse_unprivileged(register: dict) -> dict:
    """gather_system.yml 'parse raw results' — 특권 결과가 비었을 때(become 실패) 비특권 값만 남는다."""
    from tests.unit.linux_raw_harness import ansible_env, render_tree, set_fact_args
    args = set_fact_args(SYSTEM_YML, "parse raw results")
    ctx = {"_l_raw_sys_result": register, "_l_raw_priv_result": {"rc": 1, "stdout": "", "stdout_lines": [], "stderr": "sudo: a password is required"}}
    return render_tree(ansible_env(), args, ctx)


def test_unprivileged_raw_reports_os_visible_memory(sbx):
    reg = _unprivileged_raw(sbx)
    lines = reg["stdout_lines"]
    assert "MEM_TOTAL_KB=16127952" in lines
    assert "MEM_AVAIL_KB=12000000" in lines


def test_memory_section_survives_become_failure(sbx):
    reg = _unprivileged_raw(sbx)
    parsed = _parse_unprivileged(reg)
    assert parsed["_l_raw_priv_failed"] is True
    priv = {"rc": 1, "stdout": "", "stdout_lines": [], "stderr": "sudo: a password is required"}
    ctx = {"_l_raw_sys": parsed["_l_raw_sys"], "_l_raw_priv_failed": True, "_l_dmi_raw": shared_dmi_raw(priv)}
    run = run_task_file(MEM_YML, registers={}, ctx=ctx)
    mem = run.ctx["_data_fragment"]["memory"]
    assert mem["total_mb"] == 15749 and mem["total_basis"] == "os_visible"
    assert mem["visible_mb"] == 15749 and mem["free_mb"] == 11718
    assert mem["installed_mb"] is None and mem["slots"] == []
    assert run.ctx["_sections_collected_fragment"] == ["memory"]
    assert run.ctx["_sections_failed_fragment"] == []
    errors = run.ctx["_errors_fragment"]
    assert len(errors) == 1 and errors[0]["message"] == OS_VISIBLE_MESSAGE
    assert "cause=privilege_failed" in errors[0]["detail"]


def test_privileged_values_still_win_when_present():
    """특권 collector 가 돌았으면 그 값(dmidecode 물리 총량)이 그대로 우선이다 — 비특권 값은 보조다."""
    priv_lines = ["DMI_MEM_BEGIN", "MEM_TOTAL_KB=16127952", "MEM_AVAIL_KB=12000000", "DMIDECODE=present",
                  "DMIDECODE_RC=0", "DMIDECODE_ERR=", "DMIDECODE_OK=yes", "MEM_PHYS_MB=16384",
                  "SLOT|16384|DDR4|3200|00CE00B300CE|M393A2K43DB3-CWE|S1100|DIMM_A1", "MEM_DEVICE_RECORDS=1", "DMI_MEM_END",
                  "DMI_PROC_BEGIN", "DMI_PROC_END"]
    priv = {"rc": 0, "stdout": "\n".join(priv_lines), "stdout_lines": priv_lines, "stderr": ""}
    ctx = {"_l_raw_sys": {"MEM_TOTAL_KB": "999", "MEM_AVAIL_KB": "1"}, "_l_raw_priv_failed": False, "_l_dmi_raw": shared_dmi_raw(priv)}
    run = run_task_file(MEM_YML, registers={}, ctx=ctx)
    mem = run.ctx["_data_fragment"]["memory"]
    assert mem["total_mb"] == 16384 and mem["total_basis"] == "physical_installed"
    assert mem["visible_mb"] == 15749   # 특권 collector 의 MEM_TOTAL_KB 가 그대로다 (비특권 999 는 쓰이지 않았다)
    assert run.ctx["_errors_fragment"] == []
