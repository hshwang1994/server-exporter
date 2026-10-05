"""2026-10-05 최종 정비 §5 — Windows 예외 무시 지점 감사(C-1 · C-2 · C-3 · C-6): 숨은 실패가 errors[] 로 드러나는가.

무엇을 보나
-----------
1. users (C-1 · C-2) — Jinja 체인 (모든 플랫폼)
   - 목록 조회 실패 표식: 0명이면 섹션 failed + 오류 1건, 일부만 읽었으면 성공 + 부분 오류 1건.
   - 그룹 조회 실패 표식: 섹션은 성공 + 오류 1건 (관리자 그룹으로만 남기는 내장 계정이 빠질 수 있다).
   - 표식 줄은 data.users 에 들어가지 않는다. 오류 detail 은 한 줄 · 길이 상한.
   - 명령 자체가 없을 때(F23 — 출력 없이 종료 코드 1)는 종전처럼 not_supported · 오류 0.
   - 표식이 없으면 종전 체인과 결과가 같다.
2. system (C-3) · storage (C-6) — Jinja 체인 (모든 플랫폼)
   - 섹션이 성공했는데 구성요소가 실패했으면 오류 1건(실패 구성요소 이름), 섹션 상태는 그대로.
   - 정상이면 0건, 섹션 자체가 실패면 종전 실패 오류만 (이중 보고 없음).
3. 실제 powershell.exe (Windows 호스트만) — 가짜 Get-LocalUser · Get-LocalGroup · Get-LocalGroupMember ·
   Get-CimInstance 위에서 users 스크립트가 표식을 실제로 내는지, 사용자 데이터가 종전 스크립트(PRE_SHA)와
   같은지, 종료 코드가 명령 부재(F23)에서만 1 인지. system 은 Win32_ComputerSystem 실패를 실제로 기록하는지.
   명령 부재는 가짜 함수가 아니라 존재하지 않는 명령 이름으로 바꿔 실제 CommandNotFoundException 을 낸다.
4. 비종료 CIM 오류 (Windows 호스트만) — 실제 Get-CimInstance 실패는 try/catch 로 잡히지 않는다(실측). 공용 조회가
   -ErrorVariable 로 받아 구성요소를 실패로 표시하는지, 가짜 cmdlet 이 Write-Error(비종료)를 낼 때도 오류가 남는지.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("jinja2")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_windows_call_consolidation_powershell as PS  # noqa: E402  (powershell.exe 가 없으면 PS.POWERSHELL = None)
from test_windows_call_consolidation_render import (  # noqa: E402
    MERGED_TASK,
    REPO,
    WIN,
    _NO_HBA,
    _lines_register,
    comp,
    failed,
    new_text,
    run_chain,
    stor_120,
    sys_120,
)

# 숨은 실패 수정 직전 커밋 (X12) — 종전 users 스크립트
PRE_SHA = "b33e278d329c845aa1c7fa498b48d826c9c8063c"
USERS_TASK = "windows | users | collect"

LIST_FAIL = "사용자 계정 목록 수집에 실패했습니다. 대상 상태와 수집 로그를 확인하세요."
LIST_PARTIAL = "사용자 계정 목록을 끝까지 읽지 못했습니다. 대상 상태와 수집 로그를 확인하세요."
GROUP_FAIL = "사용자 계정의 그룹 정보를 읽지 못했습니다. 대상 상태와 수집 로그를 확인하세요."
SYS_PARTS = "서버 기본 정보 일부를 읽지 못했습니다. 대상 상태와 수집 로그를 확인하세요."
STOR_DISKS = "스토리지 정보 중 물리 디스크 정보를 읽지 못했습니다. 대상 상태와 수집 로그를 확인하세요."

needs_powershell = pytest.mark.skipif(
    PS.POWERSHELL is None,
    reason="powershell.exe 없음 — 실제 스크립트 실행 검증은 Windows 호스트에서만 돈다 (Jinja 체인 검증은 모든 플랫폼)")


def users_text() -> str:
    return (WIN / "gather_users.yml").read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def old_users_text() -> str | None:
    try:
        proc = subprocess.run(["git", "show", f"{PRE_SHA}:os-gather/tasks/windows/gather_users.yml"],
                              cwd=str(REPO), capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.decode("utf-8") if proc.returncode == 0 else None


def _user(name, sid, groups="", *, is_system=False, home=None, last=None):
    return json.dumps({"name": name, "uid": sid, "groups": groups, "home": home, "is_system": is_system,
                       "last": last}, separators=(",", ":"))


def _mark(kind, detail):
    return json.dumps({"_error": kind, "detail": detail}, separators=(",", ":"))


def render_users(lines, rc=0, text=None):
    def shell(task_name, _script):
        assert task_name == USERS_TASK, task_name
        return _lines_register(list(lines), rc)
    frag, ctx = run_chain(text or users_text(), {}, shell)
    assert frag is not None
    return frag, ctx


def _messages(frag):
    return [e["message"] for e in frag["_errors_fragment"]]


def _sections(ctx):
    return (ctx["_sections_collected_fragment"], ctx["_sections_failed_fragment"],
            ctx["_sections_unsupported_fragment"])


ADMIN = _user("Administrator", "S-1-5-21-1-500", "Administrators", is_system=True)
GUEST = _user("Guest", "S-1-5-21-1-501", "", is_system=True)
SVC = _user("svc_backup", "S-1-5-21-1-1001", "Users,Remote Desktop Users")


# ═══════════════════════════════════════════════════════════════════════════
# 1. users — Jinja 체인
# ═══════════════════════════════════════════════════════════════════════════
def test_users_normal_records_no_error():
    frag, ctx = render_users([ADMIN, GUEST, SVC])
    assert [u["name"] for u in frag["_data_fragment"]["users"]] == ["Administrator", "svc_backup"]
    assert _sections(ctx) == (["users"], [], [])
    assert frag["_errors_fragment"] == [] and ctx["_w_users_marks"] == []


def test_users_list_failure_with_nobody_listed_fails_the_section():
    frag, ctx = render_users([_mark("list", "Get-LocalUser: Access is denied. (fixture)")])
    assert frag["_data_fragment"]["users"] == []
    assert _sections(ctx) == ([], ["users"], [])
    assert frag["_errors_fragment"] == [{
        "section": "users", "message": LIST_FAIL,
        "detail": "cause=command_failed; listed=0; error=Get-LocalUser: Access is denied. (fixture)"}]


def test_users_partial_list_keeps_what_was_read_and_records_it():
    frag, ctx = render_users([ADMIN, _mark("list", "Get-LocalUser: RPC server is unavailable. (fixture)")])
    assert [u["name"] for u in frag["_data_fragment"]["users"]] == ["Administrator"]
    assert _sections(ctx) == (["users"], [], [])
    assert frag["_errors_fragment"] == [{
        "section": "users", "message": LIST_PARTIAL,
        "detail": "cause=command_failed_partial; listed=1; error=Get-LocalUser: RPC server is unavailable. (fixture)"}]


def test_users_group_failure_keeps_the_section_and_records_it():
    frag, ctx = render_users([SVC, _mark("groups", "Administrators,Remote Desktop Users")])
    assert [u["name"] for u in frag["_data_fragment"]["users"]] == ["svc_backup"]
    assert _sections(ctx) == (["users"], [], [])
    assert frag["_errors_fragment"] == [{
        "section": "users", "message": GROUP_FAIL,
        "detail": "source=Get-LocalGroup,Get-LocalGroupMember; cause=command_failed; "
                  "groups=Administrators,Remote Desktop Users; effect=builtin_admin_may_be_omitted"}]


def test_users_both_failures_are_reported_once_each():
    frag, _ = render_users([SVC, _mark("list", "Get-LocalUser: x"), _mark("groups", "g")])
    assert _messages(frag) == [LIST_PARTIAL, GROUP_FAIL]


def test_users_marks_never_become_users():
    frag, ctx = render_users([_mark("groups", "g"), _mark("list", "x")])
    assert frag["_data_fragment"]["users"] == []
    assert [m["_error"] for m in ctx["_w_users_marks"]] == ["groups", "list"]


def test_users_command_missing_stays_not_supported_without_error():
    """F23 — Get-LocalUser · Win32_UserAccount 명령이 없으면 스크립트는 출력 없이 종료 코드 1 (종전과 같다)."""
    frag, ctx = render_users([], rc=1)
    assert _sections(ctx) == ([], [], ["users"])
    assert frag["_errors_fragment"] == []


def test_users_empty_list_with_clean_exit_is_still_a_success():
    """조회는 성공했는데 남길 사용자가 없는 경우(관리자 그룹 밖의 내장 계정뿐)는 종전처럼 성공 · 오류 0."""
    frag, ctx = render_users([GUEST])
    assert frag["_data_fragment"]["users"] == []
    assert _sections(ctx) == (["users"], [], []) and frag["_errors_fragment"] == []


def test_users_error_detail_is_one_line_and_bounded():
    frag, _ = render_users([_mark("list", "Get-LocalUser: line1\r\nline2 " + "x" * 400)])
    detail = frag["_errors_fragment"][0]["detail"]
    assert "\n" not in detail and "\r" not in detail
    err = detail.split("error=", 1)[1]
    assert len(err) == 160 and err.startswith("Get-LocalUser: line1  line2 ")


@pytest.mark.parametrize("lines,rc", [([ADMIN, GUEST, SVC], 0), ([GUEST], 0), ([], 1), ([ADMIN], 1)],
                         ids=["normal", "only_builtin", "f23", "rc1_with_users"])
def test_users_without_marks_render_like_the_old_chain(lines, rc):
    old = old_users_text()
    if old is None:
        pytest.skip(f"종전 파일({PRE_SHA[:8]}) 을 git 으로 읽을 수 없다")
    new_frag, new_ctx = render_users(lines, rc)
    old_frag, old_ctx = render_users(lines, rc, text=old)
    assert new_frag == old_frag
    assert _sections(new_ctx) == _sections(old_ctx)


# ═══════════════════════════════════════════════════════════════════════════
# 2. system · storage — 구성요소 실패 (Jinja 체인)
# ═══════════════════════════════════════════════════════════════════════════
def _render_doc(section, doc, facts=None, extra=None, rc=0):
    merged = _lines_register([json.dumps(doc)] if doc is not None else [], rc)
    extra = extra or {}

    def shell(task_name, _script):
        if task_name == MERGED_TASK[section]:
            return copy.deepcopy(merged)
        return copy.deepcopy(extra[task_name])
    frag, ctx = run_chain(new_text(section), dict(facts or {}), shell)
    assert frag is not None
    return frag, ctx


def _sys_doc(**override):
    s = sys_120()
    doc = {"read_operating_system": comp(), "read_computer_system": comp(),
           "os": s["comps"]["os"], "hosting": s["comps"]["hosting"]}
    doc.update(override)
    return doc, s["facts"]


def _stor_doc(**override):
    s = stor_120()
    doc = {"volumes": s["comps"]["volumes"], "read_disk_drives": comp(), "disks": s["comps"]["disks"]}
    doc.update(override)
    return doc, s["extra"]


def test_system_normal_document_records_no_component_error():
    doc, facts = _sys_doc()
    frag, ctx = _render_doc("system", doc, facts)
    assert ctx["_w_sys_parts_failed"] == []
    assert frag["_sections_collected_fragment"] == ["system"] and SYS_PARTS not in _messages(frag)


def test_system_computer_system_failure_is_recorded_once():
    doc, facts = _sys_doc(read_computer_system=failed("Win32_ComputerSystem: RPC server is unavailable (fixture)"),
                          hosting=failed("hosting needs Win32_ComputerSystem (fixture)"))
    frag, ctx = _render_doc("system", doc, facts)
    assert frag["_sections_collected_fragment"] == ["system"]  # OS 정보로 섹션은 성공 — 상태는 그대로 (시나리오 B)
    assert [e for e in frag["_errors_fragment"] if e["message"] == SYS_PARTS] == [{
        "section": "system", "message": SYS_PARTS,
        "detail": "source=Win32_OperatingSystem,Win32_ComputerSystem; cause=component_failed; "
                  "parts=read_computer_system,hosting"}]


def test_system_failed_section_is_not_reported_twice():
    """OS 정보도 setup fact 도 없으면 섹션 자체가 실패 — 종전 실패 오류만 남고 구성요소 오류는 붙지 않는다."""
    doc, _ = _sys_doc(read_operating_system=failed("Win32_OperatingSystem: Invalid class (fixture)"),
                      os=failed("os needs Win32_OperatingSystem (fixture)"))
    frag, ctx = _render_doc("system", doc, {})
    assert frag["_sections_failed_fragment"] == ["system"]
    assert ctx["_w_sys_parts_failed"] == ["read_operating_system", "os"]
    assert SYS_PARTS not in _messages(frag) and frag["_errors_fragment"]


def test_storage_normal_document_records_no_component_error():
    doc, extra = _stor_doc()
    frag, ctx = _render_doc("storage", doc, extra=extra)
    assert ctx["_w_stor_parts_failed"] == [] and STOR_DISKS not in _messages(frag)


def test_storage_disk_read_failure_with_volumes_is_recorded():
    doc, extra = _stor_doc(read_disk_drives=failed("Win32_DiskDrive: RPC server is unavailable (fixture)"),
                           disks=comp(rows=[]))
    frag, _ = _render_doc("storage", doc, extra=extra)
    assert frag["_sections_collected_fragment"] == ["storage"]
    assert frag["_data_fragment"]["storage"]["physical_disks"] == []
    assert frag["_data_fragment"]["storage"]["filesystems"]
    assert [e for e in frag["_errors_fragment"] if e["message"] == STOR_DISKS] == [{
        "section": "storage", "message": STOR_DISKS,
        "detail": "source=Win32_DiskDrive,Get-PhysicalDisk; cause=component_failed; parts=read_disk_drives; disks=0"}]


def test_storage_partial_disk_list_is_recorded_with_count():
    doc, extra = _stor_doc()
    doc["disks"] = failed("Get-PhysicalDisk: Not supported (fixture)", rows=doc["disks"]["rows"][:1])
    frag, _ = _render_doc("storage", doc, extra=extra)
    kept = len(frag["_data_fragment"]["storage"]["physical_disks"])
    assert kept == 1
    assert [e["detail"] for e in frag["_errors_fragment"] if e["message"] == STOR_DISKS] == [
        "source=Win32_DiskDrive,Get-PhysicalDisk; cause=component_failed; parts=disks; disks=1"]


def test_storage_failed_section_is_not_reported_twice():
    doc = {"volumes": comp(rows=[]), "read_disk_drives": failed("Win32_DiskDrive: RPC (fixture)"), "disks": comp(rows=[])}
    frag, _ = _render_doc("storage", doc, extra=copy.deepcopy(_NO_HBA))
    assert frag["_sections_failed_fragment"] == ["storage"]
    assert STOR_DISKS not in _messages(frag) and frag["_errors_fragment"]


# ═══════════════════════════════════════════════════════════════════════════
# 3. 실제 powershell.exe — users 스크립트 · system 스크립트
# ═══════════════════════════════════════════════════════════════════════════
_USERS_SHADOWS = r"""
function Get-Command {
[CmdletBinding()] param([Parameter(Position=0)][string]$Name)
if ($script:__fx.no_local_accounts -and $Name -eq 'Get-LocalUser') { return }
[PSCustomObject]@{ Name = $Name }
}
function Get-LocalUser {
[CmdletBinding()] param()
__Track 'Get-LocalUser'
$all = @($script:__fx.users); $stop = $script:__fx.list_fail_after
for ($i = 0; $i -lt $all.Count; $i++) {
if ($null -ne $stop -and $i -ge [int]$stop) { break }
$u = $all[$i]; $last = $null; if ($u.LastLogon) { $last = [datetime]$u.LastLogon }
[PSCustomObject]@{ Name = $u.Name; SID = [PSCustomObject]@{ Value = $u.SID }; LastLogon = $last }
}
if ($null -ne $stop) { $PSCmdlet.ThrowTerminatingError((__Err $script:__fx.list_fail_msg)) }
}
function Get-LocalGroup {
[CmdletBinding()] param()
__Track 'Get-LocalGroup'
if ($script:__fx.group_list_fail) { Write-Error $script:__fx.group_list_fail; return }
foreach ($p in $script:__fx.groups.PSObject.Properties) { [PSCustomObject]@{ Name = $p.Name } }
}
function Get-LocalGroupMember {
[CmdletBinding()] param([Parameter(Position=0)][string]$Name)
__Track ('Get-LocalGroupMember ' + $Name)
$f = $script:__fx.member_fail.$Name
if ($f -eq 'terminating') { $PSCmdlet.ThrowTerminatingError((__Err ('Failed to compare two elements in the array. (fixture ' + $Name + ')'))) }
if ($f -eq 'error') { Write-Error ('An unspecified error occurred. (fixture ' + $Name + ')'); return }
foreach ($m in @($script:__fx.groups.$Name)) { [PSCustomObject]@{ Name = ($env:COMPUTERNAME + '\' + $m) } }
}
function Get-ItemProperty {
[CmdletBinding()] param([Parameter(Position=0)][string[]]$Path)
foreach ($p in $Path) { $sid = ($p -split '\\')[-1]; $v = $script:__fx.profiles.$sid; if ($null -ne $v) { [PSCustomObject]@{ ProfileImagePath = $v } } }
}
"""

_PS_USERS = [{"Name": "Administrator", "SID": "S-1-5-21-1-500"},
             {"Name": "Guest", "SID": "S-1-5-21-1-501"},
             {"Name": "svc_backup", "SID": "S-1-5-21-1-1001", "LastLogon": "2026-09-30T01:02:03Z"}]
_PS_BASE = {
    "users": _PS_USERS,
    "groups": {"Administrators": ["Administrator"], "Users": ["svc_backup"], "Remote Desktop Users": ["svc_backup"]},
    "profiles": {"S-1-5-21-1-500": "C:\\Users\\Administrator", "S-1-5-21-1-1001": "C:\\Users\\svc_backup"},
    "cim": {"Win32_UserAccount": [{"Name": u["Name"], "SID": u["SID"]} for u in _PS_USERS]},
}


def _fx(**kw):
    d = copy.deepcopy(_PS_BASE)
    d.update(kw)
    return d


def _missing_cim(script):
    """Win32_UserAccount 조회 명령을 존재하지 않는 이름으로 — 실제 CommandNotFoundException (F23)."""
    assert "Get-CimInstance Win32_UserAccount" in script
    return script.replace("Get-CimInstance Win32_UserAccount", "Get-CimInstanceSeMissing Win32_UserAccount")


# 이름 → (fixture, 스크립트 변형, 남는 사용자, 새 섹션(collected, failed, unsupported), 새 오류 문장, 새 rc, 종전 rc)
_ALL = (["users"], [], [])
USER_CASES = {
    "normal": (_fx(), None, ["Administrator", "svc_backup"], _ALL, [], 0, 0),
    "list_partial": (_fx(list_fail_after=2, list_fail_msg="RPC server is unavailable. (fixture)"), None,
                     ["Administrator"], _ALL, [LIST_PARTIAL], 0, 1),
    "list_immediate": (_fx(list_fail_after=0, list_fail_msg="Access is denied. (fixture)"), None,
                       [], ([], ["users"], []), [LIST_FAIL], 0, 1),
    "member_error": (_fx(member_fail={"Administrators": "error"}), None, ["svc_backup"], _ALL, [GROUP_FAIL], 0, 0),
    "member_terminating": (_fx(member_fail={"Users": "terminating"}), None,
                           ["Administrator", "svc_backup"], _ALL, [GROUP_FAIL], 0, 0),
    "group_list_error": (_fx(group_list_fail="Access is denied. (fixture)"), None, ["svc_backup"], _ALL,
                         [GROUP_FAIL], 0, 0),
    "win32_normal": (_fx(no_local_accounts=True), None, ["svc_backup"], _ALL, [], 0, 0),
    "win32_fail": (_fx(no_local_accounts=True, fail={"Win32_UserAccount": "Invalid class. (fixture)"}), None,
                   [], ([], ["users"], []), [LIST_FAIL], 0, 1),
    "command_missing": (_fx(no_local_accounts=True), _missing_cim, [], ([], [], ["users"]), [], 1, 1),
}


def _ps_users(name, which):
    fixture, mutate = USER_CASES[name][:2]
    text = users_text() if which == "new" else old_users_text()
    if text is None:
        return None
    prelude = PS._HEADER + PS._SHADOWS["Get-CimInstance"] + _USERS_SHADOWS + "\n"
    box = {}

    def shell(task_name, script):
        assert task_name == USERS_TASK, task_name
        box["run"] = PS.run_encoded(prelude + PS.compact(mutate(script) if mutate else script), fixture)
        return {k: box["run"][k] for k in ("stdout", "stdout_lines", "rc")}
    frag, ctx = run_chain(text, {}, shell)
    return {"frag": frag, "ctx": ctx, "run": box["run"]}


@pytest.fixture(scope="module")
def user_runs():
    if PS.POWERSHELL is None:
        pytest.skip("powershell.exe 없음")
    jobs = [(n, w) for n in USER_CASES for w in ("new", "old")]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda j: _ps_users(*j), jobs))
    return dict(zip(jobs, results))


@needs_powershell
@pytest.mark.parametrize("name", list(USER_CASES))
def test_users_script_reports_its_failures(user_runs, name):
    _, _, names, sections, messages, rc_new, _ = USER_CASES[name]
    r = user_runs[(name, "new")]
    assert r["run"]["rc"] == rc_new, r["run"]["stderr"][-600:]
    assert [u["name"] for u in r["frag"]["_data_fragment"]["users"]] == names
    assert _sections(r["ctx"]) == sections
    assert _messages(r["frag"]) == messages


@needs_powershell
@pytest.mark.parametrize("name", list(USER_CASES))
def test_users_data_is_unchanged_from_the_old_script(user_runs, name):
    """사용자 · 그룹 데이터는 종전과 같다. 종전 스크립트는 어떤 실패도 기록하지 않았다(목록 실패는 종료 코드 1 뿐)."""
    old = user_runs[(name, "old")]
    if old is None:
        pytest.skip(f"종전 파일({PRE_SHA[:8]}) 을 git 으로 읽을 수 없다")
    new = user_runs[(name, "new")]
    assert new["frag"]["_data_fragment"] == old["frag"]["_data_fragment"]
    assert old["run"]["rc"] == USER_CASES[name][6], old["run"]["stderr"][-600:]
    assert old["frag"]["_errors_fragment"] == []


@needs_powershell
def test_old_script_hid_list_failures_as_not_supported(user_runs):
    """종전: 목록을 한 명도 못 읽으면 '미지원', 일부만 읽으면 '성공' — 둘 다 기록 없음 (이번 수정의 이유)."""
    if user_runs[("list_immediate", "old")] is None:
        pytest.skip("git 이력 없음")
    assert _sections(user_runs[("list_immediate", "old")]["ctx"]) == ([], [], ["users"])
    assert _sections(user_runs[("win32_fail", "old")]["ctx"]) == ([], [], ["users"])
    assert _sections(user_runs[("list_partial", "old")]["ctx"]) == _ALL


@needs_powershell
def test_users_list_failure_detail_names_the_query(user_runs):
    assert [e["detail"] for e in user_runs[("list_immediate", "new")]["frag"]["_errors_fragment"]] == [
        "cause=command_failed; listed=0; error=Get-LocalUser: Access is denied. (fixture)"]
    assert [e["detail"] for e in user_runs[("win32_fail", "new")]["frag"]["_errors_fragment"]] == [
        "cause=command_failed; listed=0; error=Win32_UserAccount: Invalid class. (fixture)"]
    assert [e["detail"] for e in user_runs[("list_partial", "new")]["frag"]["_errors_fragment"]] == [
        "cause=command_failed_partial; listed=1; error=Get-LocalUser: RPC server is unavailable. (fixture)"]


@needs_powershell
@pytest.mark.parametrize("name,groups", [("member_error", "Administrators"), ("member_terminating", "Users"),
                                         ("group_list_error", "Get-LocalGroup")])
def test_users_group_failure_detail_names_the_failed_groups(user_runs, name, groups):
    """실패한 그룹 이름은 사용자마다 반복 조회돼도 한 번만 남는다(그룹 목록 자체가 실패하면 Get-LocalGroup)."""
    assert [e["detail"] for e in user_runs[(name, "new")]["frag"]["_errors_fragment"]] == [
        f"source=Get-LocalGroup,Get-LocalGroupMember; cause=command_failed; groups={groups}; "
        "effect=builtin_admin_may_be_omitted"]


@needs_powershell
def test_group_queries_really_failed_in_the_fixture(user_runs):
    """비교가 헛돌지 않게: 그룹 실패 시나리오에서 가짜 cmdlet 이 실제로 불렸다."""
    calls = user_runs[("member_terminating", "new")]["run"]["calls"]
    assert "Get-LocalGroupMember Users" in calls and "Get-LocalGroup" in calls
    assert "Get-LocalUser" not in user_runs[("win32_normal", "new")]["run"]["calls"]


@needs_powershell
@pytest.mark.parametrize("fail,expect_error", [(None, False), ("Win32_ComputerSystem", True)])
def test_system_script_records_computer_system_failure(fail, expect_error):
    fixture = copy.deepcopy(PS.SYS_NORMAL)
    if fail:
        fixture["fail"] = {fail: f"{fail}: RPC server is unavailable (fixture)"}
    frag, ctx = run_chain(new_text("system"), dict(PS._SYS_FACTS), PS.PsShell("system", fixture))
    assert frag["_sections_collected_fragment"] == ["system"]
    errs = [e for e in frag["_errors_fragment"] if e["message"] == SYS_PARTS]
    if not expect_error:
        assert ctx["_w_sys_parts_failed"] == [] and errs == []
        return
    assert "read_computer_system" in ctx["_w_sys_parts_failed"]
    assert [e["detail"] for e in errs] == [
        "source=Win32_OperatingSystem,Win32_ComputerSystem; cause=component_failed; parts="
        + ",".join(ctx["_w_sys_parts_failed"])]


# ═══════════════════════════════════════════════════════════════════════════
# 4. 비종료 CIM 오류 — 실제 Get-CimInstance 실패의 모양 (2026-10-05 실측)
# ═══════════════════════════════════════════════════════════════════════════
# 실제 Get-CimInstance 실패(잘못된 클래스 · 네임스페이스 · provider 오류)는 비종료 오류라 구성요소의 try/catch 가
# 잡지 못한다. 공용 조회(read_operating_system · read_computer_system · read_disk_drives)는 -ErrorVariable 로 받아
# 구성요소를 실패로 표시한다. 위 가짜 cmdlet 은 종료 오류만 내므로, 여기서는 Write-Error(비종료)도 낸다.
_CIM_SOFT = r"""
function Get-CimInstance {
[CmdletBinding()] param([Parameter(Position=0)][string]$ClassName, [string]$Namespace, [string]$Filter)
__Track ('Get-CimInstance ' + $ClassName)
$m = $script:__fx.fail.$ClassName; if ($m) { $PSCmdlet.ThrowTerminatingError((__Err $m)) }
$s = $script:__fx.soft_fail.$ClassName; if ($s) { Write-Error -Message $s -Category InvalidOperation; return }
$v = $script:__fx.cim.$ClassName; if ($null -ne $v) { $v }
}"""


class SoftCimShell(PS.PsShell):
    """PsShell 과 같되 Get-CimInstance 가 fixture 의 soft_fail 클래스에 비종료 오류를 낸다."""

    def __init__(self, section: str, fixture: dict):
        super().__init__(section, fixture)
        self.prelude = PS._HEADER + "".join(_CIM_SOFT if s == "Get-CimInstance" else PS._SHADOWS[s]
                                      for s in PS.SECTION_SHADOWS[section]) + "\n"


@needs_powershell
def test_real_cim_failure_is_non_terminating_and_lands_in_the_error_variable():
    """전제(실측): 실제 Get-CimInstance 실패는 try/catch 로 잡히지 않고 -ErrorVariable 에 남는다."""
    script = (
        "$caught = $false\n"
        "try { $x = @(Get-CimInstance Win32_NoSuchClassSe 2>$null) } catch { $caught = $true }\n"
        "$e = $null\n"
        "$y = @(Get-CimInstance Win32_NoSuchClassSe -ErrorAction SilentlyContinue -ErrorVariable e)\n"
        "[PSCustomObject]@{ caught = $caught; captured = @($e).Count; rows = $y.Count } | ConvertTo-Json -Compress\n")
    r = PS.run_encoded(script)
    assert json.loads(r["stdout"].strip()) == {"caught": False, "captured": 1, "rows": 0}, r["stderr"][-400:]


@needs_powershell
@pytest.mark.parametrize("cls,part", [("Win32_ComputerSystem", "read_computer_system"),
                                      ("Win32_OperatingSystem", "read_operating_system")])
def test_system_records_non_terminating_cim_failures(cls, part):
    fixture = copy.deepcopy(PS.SYS_NORMAL)
    fixture["soft_fail"] = {cls: f"{cls}: Invalid class (fixture, non-terminating)"}
    frag, ctx = run_chain(new_text("system"), dict(PS._SYS_FACTS), SoftCimShell("system", fixture))
    assert ctx["_w_sys_parts_failed"] == [part]
    assert frag["_sections_collected_fragment"] == ["system"]  # setup fact 로 섹션은 성공 — 상태는 그대로
    assert [e["detail"] for e in frag["_errors_fragment"] if e["message"] == SYS_PARTS] == [
        f"source=Win32_OperatingSystem,Win32_ComputerSystem; cause=component_failed; parts={part}"]


@needs_powershell
def test_storage_records_non_terminating_disk_read_failure():
    fixture = copy.deepcopy(PS.STOR_120)
    fixture["soft_fail"] = {"Win32_DiskDrive": "Win32_DiskDrive: Provider load failure (fixture, non-terminating)"}
    frag, ctx = run_chain(new_text("storage"), {}, SoftCimShell("storage", fixture))
    assert ctx["_w_stor_parts_failed"] == ["read_disk_drives"]
    assert frag["_sections_collected_fragment"] == ["storage"] and frag["_data_fragment"]["storage"]["filesystems"]
    assert [e["detail"] for e in frag["_errors_fragment"] if e["message"] == STOR_DISKS] == [
        "source=Win32_DiskDrive,Get-PhysicalDisk; cause=component_failed; parts=read_disk_drives; disks=0"]


@needs_powershell
@pytest.mark.parametrize("section", ["system", "storage"])
def test_soft_cim_shell_without_failures_records_nothing(section):
    fixture = copy.deepcopy(PS.SYS_NORMAL if section == "system" else PS.STOR_120)
    facts = dict(PS._SYS_FACTS) if section == "system" else {}
    frag, ctx = run_chain(new_text(section), facts, SoftCimShell(section, fixture))
    key = "_w_sys_parts_failed" if section == "system" else "_w_stor_parts_failed"
    assert ctx[key] == []
    assert not [e for e in frag["_errors_fragment"] if e["message"] in (SYS_PARTS, STOR_DISKS)]


# ═══════════════════════════════════════════════════════════════════════════
# 5. 8차 R5 (2026-10-05) — 남은 실패 누락: setup(facts) · Hyper-V 서비스 · 네트워크 조회 · Get-Volume
# ═══════════════════════════════════════════════════════════════════════════
import test_windows_call_consolidation_render as R  # noqa: E402

MEM_VIS = "메모리 정보 중 OS 가 인식한 용량을 읽지 못했습니다. 대상 상태와 수집 로그를 확인하세요."
NET_PARTS = "네트워크 정보 중 일부를 읽지 못했습니다. 대상 상태와 수집 로그를 확인하세요."
STOR_VOL = "스토리지 정보 중 파일시스템(볼륨) 정보를 읽지 못했습니다. 대상 상태와 수집 로그를 확인하세요."


def test_memory_without_os_visible_value_explains_why_setup_failed():
    """setup 이 실패하면 설치량은 있어도 visible_mb · free_mb 가 빈다 — 종전에는 그 이유가 없었다(섹션은 그대로 성공)."""
    s = R.mem_120()
    facts = {"_w_setup_ok": False, "_w_setup_detail": "WinRM: The WS-Management service cannot process the request (fixture)"}
    frag, _ = R.render_new("memory", s["comps"], facts)
    assert frag["_sections_collected_fragment"] == ["memory"] and frag["_data_fragment"]["memory"]["total_mb"] == 8192
    assert frag["_data_fragment"]["memory"]["visible_mb"] is None
    assert frag["_errors_fragment"] == [{"section": "memory", "message": MEM_VIS, "detail": (
        "source=setup(ansible_memtotal_mb); cause=facts_failed; effect=visible_mb,free_mb=null; setup=failed; "
        "error=WinRM: The WS-Management service cannot process the request (fixture)")}]


def test_memory_without_os_visible_value_after_a_good_setup_says_no_value():
    s = R.mem_120()
    frag, _ = R.render_new("memory", s["comps"], {"_w_setup_ok": True})
    assert [e["detail"] for e in frag["_errors_fragment"]] == [
        "source=setup(ansible_memtotal_mb); cause=no_value; effect=visible_mb,free_mb=null"]


def test_memory_normal_and_old_paths_are_unchanged():
    s = R.mem_120()
    frag, _ = R.render_new("memory", s["comps"], dict(s["facts"], _w_setup_ok=True))
    assert frag["_errors_fragment"] == []
    t = R.mem_total_failed()
    frag, _ = R.render_new("memory", t["comps"], dict(t["facts"]))
    assert [e["message"] for e in frag["_errors_fragment"]] == ["메모리 정보 중 일부를 수집하지 못했습니다. 수집 계정의 권한을 확인하세요."]


def test_identifier_diagnostics_do_not_blame_privilege_when_setup_failed():
    s = R.sys_120()
    facts = {k: v for k, v in s["facts"].items() if k not in ("ansible_product_serial", "ansible_product_uuid")}
    frag, ctx = R.render_new("system", s["comps"], dict(facts, _w_setup_ok=False, _w_setup_detail="setup failed (fixture)"))
    diags = ctx["_w_id_diagnostics"]
    assert [d["message"] for d in diags] == ["시스템 제조번호를 읽지 못했습니다. 대상 상태와 수집 로그를 확인하세요.",
                                             "시스템 고유 식별자를 읽지 못했습니다. 대상 상태와 수집 로그를 확인하세요."]
    assert all("cause=facts_failed" in d["detail"] and "error=setup failed (fixture)" in d["detail"] for d in diags)
    # setup 이 정상인데 식별자 fact 만 없으면 종전대로 권한 문장
    frag, ctx = R.render_new("system", s["comps"], dict(facts, _w_setup_ok=True))
    assert all("cause=insufficient_privilege" in d["detail"] for d in ctx["_w_id_diagnostics"])


@pytest.mark.parametrize("role,expected", [("True", "baremetal"), ("Installed", "baremetal"), ("False", "virtual"), ("Unknown", "unknown")])
def test_hosting_type_does_not_guess_from_a_failed_service_query(role, expected):
    s = R.sys_hyperv_host_domain()
    s["comps"]["hosting"]["data"]["HyperVRole"] = role
    _, ctx = R.render_new("system", s["comps"], s["facts"])
    assert ctx["_w_hosting_type"] == expected


@needs_powershell
@pytest.mark.parametrize("services,fail,role,hosting_failed", [
    ({}, None, "False", False),                                       # 서비스 없음(실제 NoServiceFoundForGivenName · ObjectNotFound)
    ({"vmms": {"Status": "Running"}}, None, "True", False),
    ({"vmms": {"Status": "Stopped"}}, None, "Installed", False),      # 역할은 설치돼 있다 — 멈춘 서비스를 "없음" 으로 보지 않는다
    ({}, "Cannot open Service Control Manager on computer '.' (fixture)", "Unknown", True),
])
def test_hyperv_service_query_distinguishes_absent_state_and_failure(services, fail, role, hosting_failed):
    fixture = copy.deepcopy(PS.SYS_DOMAIN_HV)
    fixture["services"] = services
    if fail:
        fixture.setdefault("fail", {})["Get-Service"] = fail
    frag, ctx = run_chain(new_text("system"), dict(PS._SYS_FACTS), PS.PsShell("system", fixture))
    assert ctx["_w_hosting"]["HyperVRole"] == role
    assert ("hosting" in ctx["_w_sys_parts_failed"]) is hosting_failed
    if hosting_failed:
        assert ctx["_w_hosting_type"] == "unknown"
        assert [e["detail"] for e in frag["_errors_fragment"] if e["message"] == SYS_PARTS] == [
            "source=Win32_OperatingSystem,Win32_ComputerSystem; cause=component_failed; parts=hosting"]


@needs_powershell
@pytest.mark.parametrize("soft,part", [("Get-NetAdapter", "read_adapters"), ("Get-DnsClientServerAddress", "read_dns"),
                                       ("Get-NetIPAddress", "interfaces"), ("Get-NetRoute", "read_routes")])
def test_network_non_terminating_query_failures_are_recorded(soft, part):
    fixture = copy.deepcopy(PS.NET_TEAM)
    fixture["soft_fail"] = {soft: f"{soft}: provider failure (fixture, non-terminating)"}
    frag, ctx = run_chain(new_text("network"), {}, PS.PsShell("network", fixture))
    assert part in ctx["_w_net_parts_failed"]
    assert frag["_sections_collected_fragment"] == ["network"], "받은 정보로 섹션은 그대로 성공"
    errs = [e for e in frag["_errors_fragment"] if e["message"] == NET_PARTS]
    assert len(errs) == 1 and f"parts={part}" in errs[0]["detail"] and f"{soft}: provider failure" in errs[0]["detail"]
    assert frag["_data_fragment"]["network"]["interfaces"], "성공한 다른 네트워크 정보는 보존"


@needs_powershell
@pytest.mark.parametrize("fixture_name", ["NET_TEAM", "NET_NO_TEAM"])
def test_network_not_found_answers_are_not_failures(fixture_name):
    """IPv6 기본 경로가 없는 호스트처럼 '찾는 항목 없음'(ObjectNotFound)은 조회 실패가 아니다 — 2026-10-05 실측(이 PC)."""
    frag, ctx = run_chain(new_text("network"), {}, PS.PsShell("network", copy.deepcopy(getattr(PS, fixture_name))))
    assert ctx["_w_net_parts_failed"] == [] and NET_PARTS not in _messages(frag)


@needs_powershell
def test_storage_volume_query_failure_is_told_apart_from_no_volumes():
    fixture = copy.deepcopy(PS.STOR_120)
    fixture["soft_fail"] = {"Get-Volume": "Get-Volume: provider failure (fixture, non-terminating)"}
    frag, ctx = run_chain(new_text("storage"), {}, PS.PsShell("storage", fixture))
    assert ctx["_w_stor_volumes_failed"] in (True, "True")
    assert frag["_data_fragment"]["storage"]["filesystems"], "받은 볼륨은 그대로"
    errs = [e for e in frag["_errors_fragment"] if e["message"] == STOR_VOL]
    assert len(errs) == 1 and errs[0]["detail"].startswith("source=Get-Volume; cause=component_failed; parts=volumes; filesystems=2")
    clean, ctx = run_chain(new_text("storage"), {}, PS.PsShell("storage", copy.deepcopy(PS.STOR_120)))
    assert ctx["_w_stor_volumes_failed"] in (False, "False") and STOR_VOL not in _messages(clean)
