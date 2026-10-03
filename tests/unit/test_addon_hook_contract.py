"""Add-on hook 정적 계약 — common/tasks/addon/run_addon.yml 과 호출 4곳 (2026-09-21, 2026-10-03 D8 개정).

왜 필요한가:
    Add-on 은 메인 저장소 밖의 코드다. 메인이 약속하는 것은 이 hook 하나뿐이라 그 모양이
    흔들리면 모든 Add-on 이 영향을 받는다. 실행 동작(include_role · rescue · unreachable · task timeout)은
    tests/integration/test_addon_hook_playbook.py 가 실제 ansible-playbook 으로 확인하고,
    여기서는 Ansible 없이 확인할 수 있는 계약을 고정한다.

고정하는 것 (사용자 확정 2026-09-21 · Plan §6-1 D8 2026-10-03):
    - 호출 위치: 4 play 모두 **조립이 끝나고 CHECKPOINT 가 찍힌 뒤**, block 의 마지막 태스크로 한 번.
      ADDON_DIR 이 없으면 include 자체를 건너뛴다 (200 host 기준 실측으로 추가한 조건).
    - CHECKPOINT: 각 play 의 `inject schema_version` 바로 뒤, 조건 없이, `_output | to_json` 을 debug 로 낸다 —
      콜백(json_only)이 이름 완전일치로 gather_checkpoint.jsonl 에 보존한다.
    - 경로: ADDON_DIR 하나만 본다. 자동 fallback 경로 · 특수값 없음.
      미설정 → 아무 것도 안 함 / 설정했는데 tasks/main.yml 없음 → errors[] 1건 / 있으면 실행.
    - 결합: hook 은 fragment · 누적 변수를 만들지 않고 조립된 `_output` 의 data.addon · errors[] · meta.finished_at/duration_ms
      에만 결합한다. status · sections · diagnosis 는 CHECKPOINT 값 그대로.
    - timeout: role 안 태스크 각각에 `include_role.apply.timeout`(기본 300) 하나뿐. role 전체 · hook 전체 상한은 없다.
    - 진행 마커: `ADDON_START` / `ADDON_DONE` set_fact — 콜백의 이름과 완전일치.
    - errors[] 문장에는 변수명 · 경로가 없고 기술 근거는 detail 에만 있다 (docs/contract/03-fields.md 4-1).
"""
from __future__ import annotations

import datetime
import importlib.util
import sys
import types
from pathlib import Path

import jinja2
import pytest
import yaml
from jinja2.nativetypes import NativeEnvironment

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "common" / "tasks" / "addon" / "run_addon.yml"
HOOK_REL = "common/tasks/addon/run_addon.yml"

# (site.yml, target, inject schema_version 태스크 이름)
CALL_SITES = [
    ("os-gather/site.yml", "linux", "linux | inject schema_version"),
    ("os-gather/site.yml", "windows", "windows | inject schema_version"),
    ("esxi-gather/site.yml", "esxi", "esxi | inject schema_version"),
    ("redfish-gather/site.yml", "redfish", "redfish | inject schema_version"),
]
FRAGMENT_VARS = {"_data_fragment", "_sections_supported_fragment", "_sections_collected_fragment",
                 "_sections_failed_fragment", "_sections_unsupported_fragment", "_errors_fragment"}
ACCUMULATOR_VARS = {"_merged_data", "_all_sec_supported", "_all_sec_collected", "_all_sec_failed",
                    "_all_sec_unsupported", "_all_errors", "_collected_data"}


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


def _text(node) -> str:
    return yaml.safe_dump(node, allow_unicode=True)


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
        assert task.get("when") == "lookup('env', 'ADDON_DIR') | length > 0"


@pytest.mark.parametrize("site_rel,target,inject", CALL_SITES, ids=[c[1] for c in CALL_SITES])
def test_checkpoint_then_hook_close_the_block(site_rel, target, inject):
    """D8: inject schema_version → CHECKPOINT → hook(마지막). 그 사이에 다른 태스크가 없다."""
    calls = [c for c in _hook_calls(site_rel) if (c[0].get("vars") or {}).get("_addon_target") == target]
    assert len(calls) == 1, f"{site_rel}: _addon_target={target} 호출이 {len(calls)}개"
    task, siblings, idx, _ = calls[0]
    assert set(task["vars"]) == {"_addon_target"}
    i_inject = _index_of(siblings, inject)
    i_cp = _index_of(siblings, "CHECKPOINT")
    assert i_inject + 1 == i_cp, f"{site_rel}: CHECKPOINT 는 '{inject}' 바로 뒤"
    assert i_cp + 1 == idx, f"{site_rel}: hook 은 CHECKPOINT 바로 뒤"
    assert idx == len(siblings) - 1, f"{site_rel}: hook 은 block 의 마지막 태스크 (그 뒤는 always OUTPUT 뿐)"
    cp = siblings[i_cp]
    assert cp == {"name": "CHECKPOINT", "ansible.builtin.debug": {"msg": "{{ _output | to_json }}"}}, (
        "CHECKPOINT 는 조건 없이 조립된 _output 전체를 낸다")


def test_checkpoint_name_matches_callback_default():
    text = (REPO / "callback_plugins" / "json_only.py").read_text(encoding="utf-8")
    assert "os.getenv('ANSIBLE_JSON_CHECKPOINT_TASK', 'CHECKPOINT')" in text
    assert "self._addon_start_task = 'ADDON_START'" in text and "self._addon_done_task = 'ADDON_DONE'" in text


# ── 경로 계약 ───────────────────────────────────────────────────────────────
def test_addon_dir_comes_only_from_se_addon_dir():
    locate = _hook_tasks()["addon | locate"]["ansible.builtin.set_fact"]
    assert locate["_addon_dir"] == "{{ lookup('env', 'ADDON_DIR') }}", (
        "ADDON_DIR 외 경로(자동 fallback · 기본값 · 특수값)를 두지 않는다")
    assert locate["_addon_data_out"] == {} and locate["_addon_errors_out"] == [], "결합 입력은 매 host 초기화"
    text = HOOK.read_text(encoding="utf-8")
    for forbidden in ("clovirone-gathering-addon", "'off'", '"off"', "../"):
        assert forbidden not in text, f"fallback 흔적 {forbidden!r}"


def _eval_when(conditions, addon_dir, existing):
    env = jinja2.Environment()
    env.tests["file"] = lambda path: path in existing
    if isinstance(conditions, str):
        conditions = [conditions]
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
    # 마커 · 결합은 ADDON_DIR 이 있을 때만 (없으면 skipped → 콜백 이벤트 없음)
    for name in ("ADDON_START", "ADDON_DONE"):
        assert _eval_when(tasks[name]["when"], addon_dir, existing) is bool(addon_dir)


def test_run_block_keeps_lost_hosts_and_isolates_failures():
    run = _hook_tasks()["addon | run"]
    assert run["ignore_unreachable"] is True
    assert run.get("rescue"), "Add-on 실패는 rescue 로 격리한다"
    includes = [t for t, *_ in _walk(run["block"]) if "ansible.builtin.include_role" in t]
    assert len(includes) == 1
    inc = includes[0]["ansible.builtin.include_role"]
    assert inc["name"] == "{{ _addon_dir }}"
    assert set(inc) == {"name", "apply"}


def test_timeout_is_per_task_apply_only():
    """Plan §6-3: role 안 **태스크 각각** 300 s. hook 전체 · role 전체 · async 상한은 없다."""
    tasks = _hook_tasks()
    apply = tasks["addon | include add-on"]["ansible.builtin.include_role"]["apply"]
    assert apply == {"timeout": "{{ _addon_task_timeout | default(300) | int }}"}
    # timeout 키는 apply 안 하나뿐 — hook 자체 태스크(set_fact · include)에는 없다
    doc = _load(HOOK)
    occurrences = sum(1 for k in _all_keys(doc) if k == "timeout")
    assert occurrences == 1
    assert not set(_all_keys(doc)) & {"async", "poll"}


# ── 마커 ────────────────────────────────────────────────────────────────────
def test_progress_markers_bracket_the_addon():
    doc = _load(HOOK)
    names = [t.get("name") for t in doc]
    assert names[0] == "addon | locate"
    assert names[1] == "ADDON_START", "시작 마커는 경로 판정보다 앞 — 어느 분기로 가든 '들어갔다' 가 남는다"
    assert names[-1] == "ADDON_DONE", "종료 마커는 결합 뒤 마지막 — rescue 를 지나도 돈다"
    assert names.count("ADDON_START") == 1 and names.count("ADDON_DONE") == 1
    start, done = _hook_tasks()["ADDON_START"], _hook_tasks()["ADDON_DONE"]
    assert start["ansible.builtin.set_fact"] == {"_addon_phase": "started"}
    assert done["ansible.builtin.set_fact"] == {"_addon_phase": "done"}


# ── 결합 (fragment 아님) ────────────────────────────────────────────────────
def test_hook_does_not_touch_fragment_or_accumulator_vars():
    body = _text(_load(HOOK))        # 주석 제외 — 주석은 Add-on 이 _merged_data.system.hostname 을 읽는다고 설명한다
    for var in FRAGMENT_VARS | ACCUMULATOR_VARS:
        assert var not in body, f"{var}: D8 이후 hook 은 조립된 _output 에만 결합한다"
    assert "merge_fragment" not in body
    tasks = _hook_tasks()
    for name in ("addon | missing add-on error", "addon | result", "addon | failure"):
        assert set(tasks[name]["ansible.builtin.set_fact"]) <= {"_addon_data_out", "_addon_errors_out"}, name


def test_missing_addon_error_record():
    sf = _hook_tasks()["addon | missing add-on error"]["ansible.builtin.set_fact"]
    [entry] = sf["_addon_errors_out"]
    assert entry["section"] == "addon"
    detail = jinja2.Environment().from_string(entry["detail"]).render(_addon_dir="/opt/addon")
    assert detail == "ADDON_DIR=/opt/addon; cause=addon_entry_not_found"


def _render(template: str, **ctx):
    return NativeEnvironment().from_string(template).render(**ctx)


@pytest.mark.parametrize("result,notes,expect_data,expect_errors", [
    ({}, [], {}, 0),
    ({"swList": [{"name": "a", "value": None}]}, [], {"addon": {"swList": [{"name": "a", "value": None}]}}, 0),
    ({}, ["n1", "n2"], {}, 1),
    ({"dbIpList": []}, ["n1"], {"addon": {"dbIpList": []}}, 1),
])
def test_result_mapping(result, notes, expect_data, expect_errors):
    sf = _hook_tasks()["addon | result"]["ansible.builtin.set_fact"]
    data = _render(sf["_addon_data_out"], _addon_result=result, _addon_errors=notes)
    errors = _render(sf["_addon_errors_out"], _addon_result=result, _addon_errors=notes)
    assert data == expect_data, "돌려준 결과가 없으면 data.addon 키 자체가 없다"
    assert len(errors) == expect_errors
    if errors:
        assert errors[0]["section"] == "addon" and errors[0]["detail"] == " | ".join(notes)


def test_rescue_detail_carries_the_failure():
    sf = _hook_tasks()["addon | failure"]["ansible.builtin.set_fact"]
    assert sf["_addon_data_out"] == {}, "실패 전 중간 결과는 버린다"
    [entry] = sf["_addon_errors_out"]
    detail = _render(entry["detail"], ansible_failed_task={"name": "t1"},
                     ansible_failed_result={"msg": "boom"})
    assert detail == "cause=addon_failed; task=t1; boom"


def _normalize_errors():
    spec = importlib.util.spec_from_file_location(
        "errors_normalizer", REPO / "filter_plugins" / "errors_normalizer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.normalize_errors


def _combine_env():
    env = NativeEnvironment()

    def combine(base, *others, recursive=False, list_merge="replace"):
        out = dict(base)
        for o in others:
            out.update(o)
        return out

    env.filters["combine"] = combine
    env.filters["normalize_errors"] = _normalize_errors()
    env.tests["mapping"] = lambda x: isinstance(x, dict)
    fixed = datetime.datetime(2026, 10, 3, 12, 0, 30, tzinfo=datetime.timezone.utc)
    env.globals["now"] = lambda utc=False, fmt=None: fixed
    return env


_BASE_OUTPUT = {
    "schema_version": "1", "target_type": "os", "collection_method": "agent", "ip": "10.0.0.1",
    "hostname": "h", "vendor": None, "status": "partial",
    "sections": {"system": "success", "cpu": "failed"},
    "diagnosis": {"reachable": True, "failure_stage": None},
    "meta": {"started_at": "2026-10-03T12:00:00Z", "finished_at": "2026-10-03T12:00:10Z",
             "duration_ms": 10000, "adapter_id": "a", "adapter_version": None, "ansible_version": "x"},
    "correlation": {"host_ip": "10.0.0.1"},
    "errors": [{"section": "cpu", "message": "m", "detail": "d"}],
    "data": {"system": {"hostname": "h"}, "cpu": None},
}


def _combine(data_out, errors_out, addon_dir="/opt/addon", output=None, started_epoch=1790000000.0):
    task = _hook_tasks()["addon | combine into output"]
    env = _combine_env()
    ctx = dict(_output=output if output is not None else dict(_BASE_OUTPUT), _addon_dir=addon_dir,
               _addon_data_out=data_out, _addon_errors_out=errors_out, _started_epoch=started_epoch)
    if not all(env.compile_expression(c)(**ctx) for c in task["when"]):
        return None
    return env.from_string(task["ansible.builtin.set_fact"]["_output"]).render(**ctx)


def test_combine_touches_only_data_addon_errors_and_meta_stamps():
    long_detail = "x" * 2500
    out = _combine({"addon": {"swList": [1]}},
                   [{"section": "addon", "message": "추가 수집 중 처리하지 못한 항목이 있습니다.", "detail": long_detail}])
    base = _BASE_OUTPUT
    for key in ("schema_version", "target_type", "collection_method", "ip", "hostname", "vendor",
                "status", "sections", "diagnosis", "correlation"):
        assert out[key] == base[key], f"{key} 는 CHECKPOINT 값 그대로"
    assert set(out) == set(base), "envelope 13 필드 구성 불변"
    assert out["data"] == {"system": {"hostname": "h"}, "cpu": None, "addon": {"swList": [1]}}
    assert out["errors"][:-1] == base["errors"] and out["errors"][-1]["section"] == "addon"
    assert len(out["errors"][-1]["detail"]) < 2500, "errors 는 build_errors 와 같은 normalize_errors 를 거친다 (detail 절단)"
    assert out["meta"]["started_at"] == base["meta"]["started_at"]
    assert out["meta"]["finished_at"] == "2026-10-03T12:00:30+00:00Z"
    assert out["meta"]["duration_ms"] == int((_combine_env().globals["now"]().timestamp() - 1790000000.0) * 1000)
    assert set(out["meta"]) == set(base["meta"]), "meta 키 구성 불변 — 값(finished_at/duration_ms)만 갱신"


def test_combine_with_nothing_to_add_restamps_meta_only():
    out = _combine({}, [])
    assert out["data"] == _BASE_OUTPUT["data"] and out["errors"] == _BASE_OUTPUT["errors"]
    assert out["meta"]["finished_at"] != _BASE_OUTPUT["meta"]["finished_at"], "Add-on 이 돈 시간은 duration 에 들어간다"


def test_combine_is_skipped_without_addon_dir_or_output():
    assert _combine({"addon": {"a": 1}}, [], addon_dir="") is None
    task = _hook_tasks()["addon | combine into output"]
    assert "_output is defined" in task["when"] and "_output is mapping" in task["when"]


def test_messages_follow_the_errors_contract():
    """message 에는 변수명 · 경로 · 템플릿이 없다 (기술 근거는 detail 로)."""
    tasks = _hook_tasks()
    messages = [tasks["addon | missing add-on error"]["ansible.builtin.set_fact"]["_addon_errors_out"][0]["message"],
                tasks["addon | failure"]["ansible.builtin.set_fact"]["_addon_errors_out"][0]["message"],
                _render(tasks["addon | result"]["ansible.builtin.set_fact"]["_addon_errors_out"],
                        _addon_result={}, _addon_errors=["x"])[0]["message"]]
    for msg in messages:
        assert msg.strip()
        for token in ("ADDON_DIR", "_addon", "{{", "/", "http", "timeout", "task"):
            assert token not in msg, f"message 에 {token!r}: {msg}"


# ── 수집 전 실패 envelope 에는 addon 이 없다 (data.bios 와 같은 규칙) ─────────
@pytest.mark.parametrize("rel", [
    "common/tasks/normalize/init_fragments.yml",
    "common/tasks/normalize/build_empty_data.yml",
    "common/tasks/normalize/build_failed_output.yml",
])
def test_skeletons_have_no_addon_key(rel):
    assert "addon" not in (REPO / rel).read_text(encoding="utf-8")


def test_callback_fallback_shape_has_no_addon_key():
    """json_only 는 ADDON_START/ADDON_DONE 마커 이름을 알지만(D4), 보충 envelope 의 data 뼈대에는 addon 이 없다."""
    sys.path.insert(0, str(REPO / "callback_plugins"))
    try:
        import ansible.plugins.callback  # noqa: F401
    except ImportError:
        _cb = types.ModuleType("ansible.plugins.callback")
        _cb.CallbackBase = type("CallbackBase", (), {"__init__": lambda self, *a, **k: None})
        _plugins = sys.modules.setdefault("ansible.plugins", types.ModuleType("ansible.plugins"))
        _plugins.callback = _cb
        sys.modules.setdefault("ansible", types.ModuleType("ansible")).plugins = _plugins
        sys.modules["ansible.plugins.callback"] = _cb
    import json_only
    assert "addon" not in json_only._DATA_SKELETON
    for channel in ("os", "esxi", "redfish"):
        assert "addon" not in json_only._failed_shape(channel, "192.0.2.1")["data"]


@pytest.mark.parametrize("site_rel", ["os-gather/site.yml", "esxi-gather/site.yml", "redfish-gather/site.yml"])
def test_always_fallbacks_have_no_addon_key(site_rel):
    for play in _load(REPO / site_rel):
        for task, _, _, section in _walk(play.get("tasks")):
            if section == "always":
                assert "addon" not in _text(task), task.get("name")


# ── Add-on 변수 이름 (2026-09-30) — 옛 `SE_ADDON_*` 이름은 호환용으로도 남기지 않는다 ─────────
# 대응표는 docs/reference/decision-log.md 2026-09-30. 날짜가 박힌 과거 기록(tests/evidence 등)만 당시 이름을 쓴다.
CURRENT_ADDON_FILES = [
    "Jenkinsfile_portal",
    "scripts/addon_checkout.sh",
    "scripts/addon_askpass.sh",
    HOOK_REL,
    "os-gather/site.yml",
    "esxi-gather/site.yml",
    "redfish-gather/site.yml",
    "tests/fixtures/addon/harness.yml",
    "docs/develop/07-addon-hook.md",
    "docs/operate/02-agent-node.md",
    "docs/operate/03-job-registration.md",
    "docs/operate/04-pipeline-runtime.md",
    "docs/operate/08-ansible-config.md",
]


@pytest.mark.parametrize("rel", CURRENT_ADDON_FILES)
@pytest.mark.source_text   # 저장소 메타/문서/주석 의존 — production tree overlay(G14) 제외
def test_no_legacy_addon_variable_names(rel):
    text = (REPO / rel).read_text(encoding="utf-8")
    assert "SE_ADDON" not in text, f"{rel}: 옛 이름 SE_ADDON_* 대신 ADDON_REPO_URL · ADDON_REPO_REF · ADDON_DIR 등"
