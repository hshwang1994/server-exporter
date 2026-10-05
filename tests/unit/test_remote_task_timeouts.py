"""원격 · local 모듈 태스크의 task-level `timeout:` (Plan §6-3, 2026-10-03).

왜 필요한가:
    free strategy 에서 한 host 의 hang 은 그 host 의 태스크 하나만 지연시키지만, 아무 상한이 없으면 배치 예산
    (Jenkins Gather)이 끊을 때까지 그 host 를 붙잡는다. task `timeout` 은 **개별 hang 격리** 수단이다 — host 상한 ·
    배치 상한이 아니다. Redfish 는 모듈 `deadline` 이 1차(정상 경로에서 register 가 남는다)이고 task timeout 은 backstop 이라
    deadline < timeout 이어야 한다.

고정하는 것:
    - Linux raw/setup/command/shell 전부 `_os_task_timeout | default(120)`
    - 자격 probe(linux ssh / windows win_ping) `_os_probe_timeout | default(60)`, Linux add_host `ansible_timeout: 15` (N6)
    - precheck_bundle `_precheck_task_timeout | default(120)`
    - redfish detect 120 (deadline 90) / collect 600 (deadline 540) / account 240 (deadline 180)
    - ESXi 모듈(community.vmware · esxi_disks) `_e_task_timeout | default(180)`
    - Windows win_shell/setup `_win_task_timeout | default(180)` (> ansible_winrm_read_timeout_sec 70)
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
REMOTE = {"raw", "setup", "command", "shell", "slurp", "stat", "script", "win_shell", "win_command", "win_ping",
          "precheck_bundle", "redfish_gather", "esxi_disks"}


def _load(rel):
    return yaml.safe_load((REPO / rel).read_text(encoding="utf-8"))


def _walk(tasks):
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield t
        for k in ("block", "rescue", "always"):
            if isinstance(t.get(k), list):
                yield from _walk(t[k])


def _remote_tasks(rel):
    doc = _load(rel)
    tasks = []
    if isinstance(doc, list) and doc and isinstance(doc[0], dict) and "hosts" in doc[0]:
        for play in doc:
            for sec in ("pre_tasks", "tasks", "post_tasks"):
                tasks += list(_walk(play.get(sec)))
    else:
        tasks = list(_walk(doc))
    out = []
    for t in tasks:
        acts = [k for k in t if k.split(".")[-1] in REMOTE or k.startswith("community.vmware.")]
        if not acts:
            continue
        if t.get("delegate_to") == "localhost" and acts[0].split(".")[-1] == "command":
            continue        # controller-side backoff sleep — hang 후보가 아니다
        out.append((t.get("name"), acts[0], t.get("timeout")))
    return out


def _default_of(expr):
    m = re.fullmatch(r"\{\{\s*(\w+)\s*\|\s*default\((\d+)\)\s*\}\}", str(expr))
    assert m, f"timeout 은 '{{{{ <var> | default(<int>) }}}}' 꼴이어야 한다: {expr!r}"
    return m.group(1), int(m.group(2))


LINUX = [f"os-gather/tasks/linux/{n}.yml" for n in
         ("gather_cpu", "gather_hba_ib", "gather_memory", "gather_network", "gather_storage",
          "gather_system", "gather_users", "preflight")]
# Plan §8-2 (2026-10-03): gather_memory 는 원격 명령을 실행하지 않는다 — gather_system raw gather 의
#   공유 DMI collector 결과(_l_dmi_raw)만 파싱한다. 원격 태스크가 다시 생기면 아래 timeout 검사는 그대로 적용된다.
LINUX_NO_REMOTE = {"os-gather/tasks/linux/gather_memory.yml"}


@pytest.mark.parametrize("rel", LINUX)
def test_linux_remote_tasks_have_120s_timeout(rel):
    tasks = _remote_tasks(rel)
    assert tasks or rel in LINUX_NO_REMOTE, f"{rel}: 원격 태스크를 찾지 못했다 (walker 점검)"
    for name, action, timeout in tasks:
        var, val = _default_of(timeout)
        assert (var, val) == ("_os_task_timeout", 120), f"{rel}: {name} ({action}) timeout={timeout!r}"


def test_credential_probe_timeout_60():
    tasks = {name: timeout for name, _, timeout in _remote_tasks("os-gather/tasks/try_one_credential.yml")}
    assert set(tasks) == {"os | try_one_credential | linux ssh probe", "os | try_one_credential | windows winrm probe"}
    for name, timeout in tasks.items():
        assert _default_of(timeout) == ("_os_probe_timeout", 60), name


def test_linux_add_host_sets_ansible_timeout_15():
    """N6: ansible.cfg timeout=60 이 ssh_common_args 의 ConnectTimeout=15 보다 먼저 나가 15 가 무시됐다."""
    for play in _load("os-gather/site.yml"):
        for t in _walk(play.get("tasks")):
            if t.get("name") == "detect | register linux hosts":
                args = t["ansible.builtin.add_host"]
                assert args["ansible_timeout"] == 15
                assert "-o ConnectTimeout=15" in args["ansible_ssh_common_args"]
                return
    raise AssertionError("linux add_host 태스크를 찾지 못했다")


def test_precheck_task_timeout_120():
    [(name, action, timeout)] = _remote_tasks("common/tasks/precheck/run_precheck.yml")
    assert action == "precheck_bundle"
    assert _default_of(timeout) == ("_precheck_task_timeout", 120)


REDFISH = {
    ("redfish-gather/tasks/detect_vendor.yml", "redfish | detect_vendor | probe"): (("_rf_detect_task_timeout", 120), "_rf_detect_deadline", 90),
    ("redfish-gather/tasks/try_one_account.yml", "redfish | try_account | attempt"): (("_rf_task_timeout", 1260), "_rf_deadline", 1200),
    ("redfish-gather/tasks/collect_standard.yml", "redfish | collect_standard | empty-credential attempt"): (("_rf_task_timeout", 1260), "_rf_deadline", 1200),
    ("redfish-gather/tasks/account_service_try_one.yml", "redfish | account_service | invoke"): (("_rf_account_task_timeout", 240), "_rf_account_deadline", 180),
}


@pytest.mark.parametrize("rel,name", list(REDFISH), ids=[k[1] for k in REDFISH])
def test_redfish_module_tasks_timeout_exceeds_module_deadline(rel, name):
    (var, val), dl_var, dl_default = REDFISH[(rel, name)]
    tasks = {n: (a, to) for n, a, to in _remote_tasks(rel)}
    action, timeout = tasks[name]
    assert action == "redfish_gather"
    assert _default_of(timeout) == (var, val)
    # 모듈 deadline 이 task timeout 보다 엄격히 작다 — 정상 경로에서는 모듈이 먼저 끝나 register 가 남는다
    task = next(t for t in _walk(_load(rel)) if t.get("name") == name)
    deadline_expr = str(task["redfish_gather"]["deadline"])
    m = re.fullmatch(r"\{\{\s*(\w+)\s*\|\s*default\((\d+)\)\s*\}\}", deadline_expr)
    assert m and m.group(1) == dl_var and int(m.group(2)) == dl_default, deadline_expr
    assert dl_default < val
    # site.yml 의 실제 값도 같은 관계
    site_vars = {}
    for play in _load("redfish-gather/site.yml"):
        site_vars.update(play.get("vars") or {})
    site_deadline = site_vars.get(dl_var, dl_default)
    site_timeout = site_vars.get(var, val)
    assert int(site_deadline) < int(site_timeout), f"site.yml {dl_var}={site_deadline} 가 {var}={site_timeout} 보다 작아야 한다"


def test_redfish_collect_is_progress_based():
    """2026-10-05 (F12): 수집 모듈은 절대 상한(1200)과 함께 '새 응답 없음' 상한(120)과 heartbeat 디렉터리를 받는다."""
    for rel, name in (("redfish-gather/tasks/try_one_account.yml", "redfish | try_account | attempt"),
                      ("redfish-gather/tasks/collect_standard.yml", "redfish | collect_standard | empty-credential attempt")):
        task = next(t for t in _walk(_load(rel)) if t.get("name") == name)
        args = task["redfish_gather"]
        assert re.fullmatch(r"\{\{\s*_rf_idle_deadline\s*\|\s*default\(120\)\s*\}\}", str(args["idle_deadline"])), rel
        assert "SE_PROGRESS_DIR" in str(args["progress_dir"]), rel
    site_vars = {}
    for play in _load("redfish-gather/site.yml"):
        site_vars.update(play.get("vars") or {})
    assert (site_vars["_rf_deadline"], site_vars["_rf_idle_deadline"], site_vars["_rf_task_timeout"]) == (1200, 120, 1260)
    assert site_vars["_rf_idle_deadline"] == 4 * site_vars["_rf_timeout"], "새 응답 없음 상한 = 소켓 timeout 4번"


WINDOWS = [f"os-gather/tasks/windows/{n}.yml" for n in
           ("gather_cpu", "gather_hardware", "gather_memory", "gather_network", "gather_runtime",
            "gather_storage", "gather_system", "gather_users")]
ESXI = [f"esxi-gather/tasks/{n}.yml" for n in
        ("collect_config", "collect_datastores", "collect_disks", "collect_dns", "collect_facts",
         "collect_network_extended", "collect_runtime", "try_one_credential")]


@pytest.mark.parametrize("rel", WINDOWS)
def test_windows_remote_tasks_have_180s_timeout(rel):
    tasks = _remote_tasks(rel)
    assert tasks, f"{rel}: 원격 태스크를 찾지 못했다"
    for name, action, timeout in tasks:
        assert _default_of(timeout) == ("_win_task_timeout", 180), f"{rel}: {name} ({action}) timeout={timeout!r}"


def test_windows_setup_in_site_has_180s_timeout():
    for play in _load("os-gather/site.yml"):
        for t in _walk(play.get("tasks")):
            if t.get("name") == "windows | setup":
                assert _default_of(t.get("timeout")) == ("_win_task_timeout", 180)
                return
    raise AssertionError("windows | setup 태스크를 찾지 못했다")


@pytest.mark.parametrize("rel", ESXI)
def test_esxi_module_tasks_have_180s_timeout(rel):
    for name, action, timeout in _remote_tasks(rel):
        assert _default_of(timeout) == ("_e_task_timeout", 180), f"{rel}: {name} ({action}) timeout={timeout!r}"
