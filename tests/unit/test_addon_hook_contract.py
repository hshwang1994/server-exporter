"""Add-on hook 정적 계약 — common/tasks/addon/run_addon.yml 과 호출 4곳 (2026-09-21).

왜 필요한가:
    Add-on 은 메인 저장소 밖의 코드다. 메인이 약속하는 것은 이 hook 하나뿐이라 그 모양이
    흔들리면 모든 Add-on 이 영향을 받는다. 실행 동작(include_role · rescue · unreachable)은
    tests/integration/test_addon_hook_playbook.py 가 실제 ansible-playbook 으로 확인하고,
    여기서는 Ansible 없이 확인할 수 있는 계약을 고정한다.

고정하는 것 (사용자 확정 2026-09-21):
    - 호출 위치: 4 play 모두 마지막 수집 뒤 · 조립(build) 앞, 각자의 target 값으로 한 번.
      SE_ADDON_DIR 이 없으면 include 자체를 건너뛴다 (200 host 기준 실측으로 추가한 조건).
    - 경로: SE_ADDON_DIR 하나만 본다. 자동 fallback 경로 · 특수값 없음.
      미설정 → 아무 것도 안 함 / 설정했는데 tasks/main.yml 없음 → errors[] 1건 / 있으면 실행.
    - Add-on 전용 timeout 없음.
    - errors[] 문장에는 변수명 · 경로가 없고 기술 근거는 detail 에만 있다 (docs/contract/03-fields.md 4-1).
"""
from __future__ import annotations

from pathlib import Path

import jinja2
import pytest
import yaml
from jinja2.nativetypes import NativeEnvironment

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "common" / "tasks" / "addon" / "run_addon.yml"
HOOK_REL = "common/tasks/addon/run_addon.yml"

# (site.yml, target, 바로 앞 수집 태스크, 뒤따르는 조립 태스크)
CALL_SITES = [
    ("os-gather/site.yml", "linux", "linux | gather hba_ib", "linux | build diagnosis (success path)"),
    ("os-gather/site.yml", "windows", "windows | gather runtime", "windows | build diagnosis (success path)"),
    ("esxi-gather/site.yml", "esxi", "esxi | collect runtime (B31/B32)", "esxi | build_sections"),
    ("redfish-gather/site.yml", "redfish", "redfish | normalize standard", "redfish | build_sections"),
]
FRAGMENT_SETTERS = ("addon | missing add-on fragment", "addon | result fragment", "addon | failure fragment")


# ── helpers ────────────────────────────────────────────────────────────────
def _load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _walk(tasks, section="tasks"):
    """(task, 형제 목록, 위치, section) 를 재귀로 돌려준다."""
    for idx, task in enumerate(tasks or []):
        if not isinstance(task, dict):
            continue
        yield task, tasks, idx, section
        for key in ("block", "rescue", "always"):
            if isinstance(task.get(key), list):
                yield from _walk(task[key], key if key != "block" else section)


def _include_file(task: dict) -> str:
    inc = task.get("ansible.builtin.include_tasks") or task.get("include_tasks") or ""
    return inc.get("file", "") if isinstance(inc, dict) else str(inc)


def _hook_calls(site_rel: str):
    found = []
    for play in _load(REPO / site_rel):
        for task, siblings, idx, section in _walk(play.get("tasks")):
            if _include_file(task).endswith(HOOK_REL):
                found.append((task, siblings, idx, section))
    return found


def _hook_tasks() -> dict:
    return {t.get("name"): t for t, *_ in _walk(_load(HOOK))}


def _index_of(siblings, name):
    for i, t in enumerate(siblings):
        if isinstance(t, dict) and t.get("name") == name:
            return i
    raise AssertionError(f"{name!r} 태스크를 찾지 못했다")


def _all_keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _all_keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _all_keys(v)


# ── 호출 위치 ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("site_rel,count", [
    ("os-gather/site.yml", 2), ("esxi-gather/site.yml", 1), ("redfish-gather/site.yml", 1)])
def test_each_play_calls_the_hook_exactly_once(site_rel, count):
    calls = _hook_calls(site_rel)
    assert len(calls) == count
    for task, _, _, section in calls:
        assert section == "tasks", "hook 은 rescue / always 가 아니라 수집 경로에만 둔다"
        assert "lookup('env','REPO_ROOT')" in _include_file(task).replace(" ", "")
        # 미설정(현재 모든 환경)이면 include 자체를 건너뛴다 — hook 안 태스크를 host 마다 평가하지 않는다
        assert task.get("when") == "lookup('env', 'SE_ADDON_DIR') | length > 0"


@pytest.mark.parametrize("site_rel,target,after,before", CALL_SITES,
                         ids=[c[1] for c in CALL_SITES])
def test_hook_sits_after_last_gather_and_before_build(site_rel, target, after, before):
    calls = [c for c in _hook_calls(site_rel) if (c[0].get("vars") or {}).get("_addon_target") == target]
    assert len(calls) == 1, f"{site_rel}: _addon_target={target} 호출이 {len(calls)}개"
    task, siblings, idx, _ = calls[0]
    assert _index_of(siblings, after) < idx < _index_of(siblings, before), (
        f"{site_rel}: hook 은 '{after}' 뒤, '{before}' 앞에 있어야 한다")
    assert set(task["vars"]) == {"_addon_target"}


# ── 경로 계약 ───────────────────────────────────────────────────────────────
def test_addon_dir_comes_only_from_se_addon_dir():
    locate = _hook_tasks()["addon | locate"]["ansible.builtin.set_fact"]
    assert locate == {"_addon_dir": "{{ lookup('env', 'SE_ADDON_DIR') }}"}, (
        "SE_ADDON_DIR 외 경로(자동 fallback · 기본값 · 특수값)를 두지 않는다")
    text = HOOK.read_text(encoding="utf-8")
    for forbidden in ("clovirone-gathering-addon", "'off'", '"off"', "../"):
        assert forbidden not in text, f"fallback 흔적 {forbidden!r}"


def _eval_when(conditions, addon_dir, existing):
    env = jinja2.Environment()
    env.tests["file"] = lambda path: path in existing
    return all(env.compile_expression(c)(_addon_dir=addon_dir) for c in conditions)


@pytest.mark.parametrize("addon_dir,existing,expect_missing,expect_run", [
    ("", set(), False, False),                                            # 미설정 → 조용히 건너뜀
    ("/opt/addon", set(), True, False),                                    # 설정 + 없음 → errors 1건
    ("/opt/addon", {"/opt/addon/tasks/main.yml"}, False, True),            # 설정 + 있음 → 실행
], ids=["unset", "set-missing", "set-present"])
def test_three_path_cases_are_distinguished(addon_dir, existing, expect_missing, expect_run):
    tasks = _hook_tasks()
    assert _eval_when(tasks["addon | record missing add-on"]["when"], addon_dir, existing) is expect_missing
    assert _eval_when(tasks["addon | run"]["when"], addon_dir, existing) is expect_run


def test_run_block_keeps_lost_hosts_and_isolates_failures():
    run = _hook_tasks()["addon | run"]
    assert run["ignore_unreachable"] is True
    assert run.get("rescue"), "Add-on 실패는 rescue 로 격리한다"
    includes = [t for t, *_ in _walk(run["block"]) if "ansible.builtin.include_role" in t]
    assert [t["ansible.builtin.include_role"] for t in includes] == [{"name": "{{ _addon_dir }}"}]


def test_hook_has_no_timeout():
    keys = set(_all_keys(_load(HOOK)))
    assert not keys & {"timeout", "async", "poll"}, "Add-on 전용 timeout 은 두지 않는다 (사용자 결정)"


# ── fragment ────────────────────────────────────────────────────────────────
def test_every_branch_resets_all_fragment_vars():
    merge = _load(REPO / "common" / "tasks" / "normalize" / "merge_fragment.yml")
    reset = next(t for t in merge if t.get("name") == "normalize | merge_fragment | reset fragment vars")
    fragment_vars = set(reset["ansible.builtin.set_fact"])
    tasks = _hook_tasks()
    for name in FRAGMENT_SETTERS:
        assert set(tasks[name]["ansible.builtin.set_fact"]) == fragment_vars, name
    for name in FRAGMENT_SETTERS:
        sf = tasks[name]["ansible.builtin.set_fact"]
        for var in fragment_vars - {"_data_fragment", "_errors_fragment"}:
            assert sf[var] == [], f"{name}: {var} — Add-on 은 섹션을 만들지 않는다 (status 불변)"


def test_missing_addon_error_record():
    sf = _hook_tasks()["addon | missing add-on fragment"]["ansible.builtin.set_fact"]
    assert sf["_data_fragment"] == {}
    [entry] = sf["_errors_fragment"]
    assert entry["section"] == "addon"
    detail = jinja2.Environment().from_string(entry["detail"]).render(_addon_dir="/opt/addon")
    assert detail == "SE_ADDON_DIR=/opt/addon; cause=addon_entry_not_found"


def _render(template: str, **ctx):
    return NativeEnvironment().from_string(template).render(**ctx)


@pytest.mark.parametrize("result,notes,expect_data,expect_errors", [
    ({}, [], {}, 0),
    ({"software": {"swList": []}}, [], {"addon": {"software": {"swList": []}}}, 0),
    ({}, ["n1", "n2"], {}, 1),
    ({"hosts": {"dbIpList": []}}, ["n1"], {"addon": {"hosts": {"dbIpList": []}}}, 1),
])
def test_result_fragment(result, notes, expect_data, expect_errors):
    sf = _hook_tasks()["addon | result fragment"]["ansible.builtin.set_fact"]
    data = _render(sf["_data_fragment"], _addon_result=result, _addon_errors=notes)
    errors = _render(sf["_errors_fragment"], _addon_result=result, _addon_errors=notes)
    assert data == expect_data, "맞는 rule 이 없으면 data.addon 키 자체가 없다"
    assert len(errors) == expect_errors
    if errors:
        assert errors[0]["section"] == "addon" and errors[0]["detail"] == " | ".join(notes)


def test_merge_is_skipped_when_nothing_to_add():
    task = _hook_tasks()["addon | merge result fragment"]
    assert task["when"] == "(_data_fragment | length > 0) or (_errors_fragment | length > 0)"


def test_rescue_detail_carries_the_failure():
    sf = _hook_tasks()["addon | failure fragment"]["ansible.builtin.set_fact"]
    [entry] = sf["_errors_fragment"]
    detail = _render(entry["detail"], ansible_failed_task={"name": "t1"},
                     ansible_failed_result={"msg": "boom"})
    assert detail == "cause=addon_failed; task=t1; boom"


def test_messages_follow_the_errors_contract():
    """message 에는 변수명 · 경로 · 템플릿이 없다 (기술 근거는 detail 로)."""
    tasks = _hook_tasks()
    messages = [tasks["addon | missing add-on fragment"]["ansible.builtin.set_fact"]["_errors_fragment"][0]["message"],
                tasks["addon | failure fragment"]["ansible.builtin.set_fact"]["_errors_fragment"][0]["message"],
                _render(tasks["addon | result fragment"]["ansible.builtin.set_fact"]["_errors_fragment"],
                        _addon_result={}, _addon_errors=["x"])[0]["message"]]
    for msg in messages:
        assert msg.strip()
        for token in ("SE_ADDON_DIR", "_addon", "{{", "/", "http", "timeout", "task"):
            assert token not in msg, f"message 에 {token!r}: {msg}"


# ── 수집 전 실패 envelope 에는 addon 이 없다 (data.bios 와 같은 규칙) ─────────
@pytest.mark.parametrize("rel", [
    "common/tasks/normalize/init_fragments.yml",
    "common/tasks/normalize/build_empty_data.yml",
    "common/tasks/normalize/build_failed_output.yml",
    "callback_plugins/json_only.py",
])
def test_skeletons_have_no_addon_key(rel):
    assert "addon" not in (REPO / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("site_rel", ["os-gather/site.yml", "esxi-gather/site.yml", "redfish-gather/site.yml"])
def test_always_fallbacks_have_no_addon_key(site_rel):
    for play in _load(REPO / site_rel):
        for task, _, _, section in _walk(play.get("tasks")):
            if section == "always":
                assert "addon" not in yaml.safe_dump(task, allow_unicode=True), task.get("name")
