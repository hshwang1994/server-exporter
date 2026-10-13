"""Linux sudo 확인 (2026-10-13) — os-gather/tasks/linux/try_sudo.yml · try_one_sudo.yml · preflight.yml 잠금 예산 · gather_system.yml 게이트.

무엇을 고정하나
  - 프로브는 결과의 구조(rc 유무 · 값 · unreachable · 출력 줄 '0')만 본다. 문자열 파싱 · Ansible 버전 가정 없음. 알 수 없는 모양은 중단.
  - 후보 = 로그인 비밀번호(비밀번호 인증일 때) → Vault 순서, 같은 값은 한 번만. 거부는 잠금 예산에 닿으면 멈춘다.
  - 예산은 host 의 잠금 정책(pam_faillock / pam_tally2 · deny · even_deny_root · unlock_time)에서 계산한다 — 변수는 _l_sudo_max_rejections 하나.
  - 특권 태스크(gather_system.yml 의 become 4건)는 _l_sudo_ok 로 게이트된다. 건너뛴 register 는 기존 '특권 수집 안 됨' 판정으로 떨어진다.
  - 결과 fact(_l_sudo_meta · attempts)에 비밀번호 · 원격 출력이 들어가지 않는다. 프로브 태스크에 task timeout 이 없다 (rule 80 R1).
정적 렌더다 — 실서버 실행은 tests/integration/test_sudo_probe_live.py (-m live) 와 Jenkins 실측이 맡는다.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tests.unit.linux_raw_harness import ansible_env, iter_tasks, load_tasks, render_tree, set_fact_args  # noqa: E402

LINUX = REPO / "os-gather" / "tasks" / "linux"
TRY_SUDO = LINUX / "try_sudo.yml"
TRY_ONE = LINUX / "try_one_sudo.yml"
PREFLIGHT = LINUX / "preflight.yml"
SYSTEM = LINUX / "gather_system.yml"
SITE = REPO / "os-gather" / "site.yml"


def _task(yml: Path, name_part: str) -> dict[str, Any]:
    hits = [t for t in iter_tasks(load_tasks(yml)) if str(t.get("name", "")).endswith("| " + name_part)]
    assert len(hits) == 1, (yml.name, name_part, [t.get("name") for t in hits])
    return hits[0]


def _when(task: dict[str, Any], ctx: dict[str, Any]) -> bool:
    env = ansible_env()
    conds = task.get("when")
    for cond in (conds if isinstance(conds, list) else [conds]):
        value = env.from_string("{{ " + str(cond) + " }}").render(**ctx)
        assert isinstance(value, bool), (cond, value)
        if not value:
            return False
    return True


def _facts(task: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    return render_tree(ansible_env(), task["ansible.builtin.set_fact"], ctx)


# ── 1. 프로브 태스크의 안전 키 ──────────────────────────────────────────────────────────────────────
def test_probe_tasks_keep_safety_keys_and_have_no_task_timeout():
    for yml in (TRY_SUDO, TRY_ONE):
        text = yml.read_text(encoding="utf-8")
        for banned in ("timeout:", "retries:", "until:", "auth_success", "diagnostic"):
            assert banned not in text, (yml.name, banned)
        raws = [t for t in iter_tasks(load_tasks(yml)) if "ansible.builtin.raw" in t]
        assert len(raws) == 1, yml.name
        probe = raws[0]
        assert probe.get("failed_when") is False and probe.get("changed_when") is False
        assert probe.get("ignore_unreachable") is True and probe.get("no_log") is True
    assert TRY_ONE.read_text(encoding="utf-8").count("register:") == 1


def test_nopasswd_probe_runs_without_become_and_candidate_probe_with_become():
    np = _task(TRY_SUDO, "nopasswd probe")
    assert "become" not in np
    assert np["ansible.builtin.raw"] == "sudo -k -n /bin/sh -c 'id -u'"
    cand = _task(TRY_ONE, "sudo probe")
    assert cand.get("become") is True
    assert cand["vars"]["ansible_become_flags"] == "-H -S -n -k"
    assert cand["ansible.builtin.raw"] == "id -u"


def test_candidate_probe_is_wrapped_so_a_become_exception_cannot_abort_the_play():
    """Runner ansible-core 2.20.3 실측(2026-10-13 main #558): 비밀번호 거부가 failed_when 으로 지울 수 없는 태스크 예외로 올라와 play 의
    rescue 로 떨어졌다. 프로브는 자체 block/rescue 안에 있고, rescue 는 같은 모양(rc 없음 · msg 만)의 결과를 register 에 남긴다."""
    outer = load_tasks(TRY_ONE)[-1]
    wrapper = next(t for t in outer["block"] if "probe with rescue" in t.get("name", ""))
    assert [t["name"] for t in wrapper["block"]] == ["linux | try_one_sudo | sudo probe"]
    rescue = wrapper["rescue"]
    assert len(rescue) == 1 and rescue[0]["no_log"] is True
    recorded = _facts(rescue[0], {"ansible_failed_result": {"msg": "Task failed: Incorrect sudo password", "failed": True}})["_l_sudo_probe"]
    assert "rc" not in recorded and recorded["msg"]
    ctx = {"_l_sudo_probe": recorded, "_l_sudo_attempts": [], "_l_sudo_rejections": 0, "_try_sudo": {"label": "login", "password": "x"}}
    ctx.update(_facts(_task(TRY_ONE, "evaluate"), ctx))
    assert ctx["_l_sudo_probe_verdict"].strip() == "rejected"
    assert "rc" not in _facts(rescue[0], {})["_l_sudo_probe"], "ansible_failed_result 가 없어도 죽지 않는다"
    for key in ("stdout", "stderr", "password"):
        assert key not in str(rescue[0]["ansible.builtin.set_fact"]), key


def test_secret_handling_tasks_are_no_log():
    for name in ("build candidates", "record meta", "init"):
        assert _task(TRY_SUDO, name).get("no_log") is True, name
    for name in ("apply candidate", "evaluate", "record attempt", "stop candidates unless the password was rejected"):
        assert _task(TRY_ONE, name).get("no_log") is True, name
    record = _task(TRY_ONE, "record attempt")["ansible.builtin.set_fact"]
    for key in ("stdout", "msg", "password", "stderr"):
        assert key not in str(record["_l_sudo_attempts"]), key
    meta = _task(TRY_SUDO, "record meta")["ansible.builtin.set_fact"]["_l_sudo_meta"]
    assert set(meta) == {"ok", "mode", "outcome", "attempted_count", "rejected_count", "max_rejections",
                         "used_label", "fallback_used", "policy", "attempts"}


# ── 2. NOPASSWD 확인 분류 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("register,ok,stop", [
    ({"rc": 0, "stdout_lines": ["0\r"]}, True, False),
    ({"rc": 0, "stdout_lines": ["1000"]}, False, False),           # sudo 없이 돈 것처럼 보여도 root 가 아니면 통과가 아니다
    ({"rc": 1, "stdout_lines": ["sudo: a password is required"]}, False, False),
    ({"rc": 127, "stdout_lines": []}, False, True),
    ({"rc": 255, "stdout_lines": []}, False, True),
    ({"unreachable": True, "msg": "timeout"}, False, True),
])
def test_nopasswd_classification(register, ok, stop):
    ctx = {"_l_sudo_ok": False, "_l_sudo_mode": "", "_l_sudo_nopasswd": register}
    ctx.update(_facts(_task(TRY_SUDO, "classify nopasswd probe"), ctx))
    assert ctx["_l_sudo_np_ok"] is ok
    assert _when(_task(TRY_SUDO, "adopt nopasswd"), ctx) is ok
    assert _when(_task(TRY_SUDO, "stop when sudo is unavailable"), ctx) is stop
    if ok:
        facts = _facts(_task(TRY_SUDO, "adopt nopasswd"), ctx)
        assert facts["_l_sudo_mode"] == "nopasswd" and facts["ansible_become_pass"] == ""
    if stop:
        facts = _facts(_task(TRY_SUDO, "stop when sudo is unavailable"), ctx)
        assert facts["_l_sudo_mode"] == "unavailable" and facts["ansible_become_pass"] == ""
        assert facts["_l_sudo_outcome"] in {"prompt_timeout", "sudo_absent", "transport"}


def test_root_login_short_circuits_and_probe_is_skipped_only_for_root():
    root = _task(TRY_SUDO, "root login needs no escalation")
    assert _when(root, {"ansible_user": "root"}) is True
    assert _when(root, {"ansible_user": "cloviradmin"}) is False
    assert _when(root, {}) is False
    probe = _task(TRY_SUDO, "nopasswd probe")
    assert _when(probe, {"_l_sudo_mode": "root"}) is False
    assert _when(probe, {"_l_sudo_mode": ""}) is True


# ── 3. 후보 판정 ────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("register,verdict,rejected,stop,mode,outcome", [
    ({"rc": 0, "stdout_lines": ["0\r"]}, "ok", 0, False, None, None),
    ({"failed": False, "msg": "Incorrect sudo password", "failed_when_result": False}, "rejected", 1, False, None, None),
    ({"rc": 1, "stdout": "user is not in the sudoers file."}, "denied", 0, True, "denied", "policy_denied"),
    ({"rc": 127, "stdout": ""}, "unavailable", 0, True, "unavailable", "sudo_absent"),
    ({"rc": 255, "stdout": ""}, "unavailable", 0, True, "unavailable", "transport"),
    ({"unreachable": True, "msg": "Timeout (62s) waiting for privilege escalation prompt"}, "unavailable", 0, True, "unavailable", "prompt_timeout"),
    ({}, "unknown_shape", 0, True, "unavailable", "unknown_shape"),
])
def test_candidate_verdict_and_stop(register, verdict, rejected, stop, mode, outcome):
    ctx = {"_l_sudo_probe": register, "_l_sudo_attempts": [], "_l_sudo_rejections": 0,
           "_try_sudo": {"label": "sudo_primary", "role": "primary", "password": "x"}}
    ctx.update(_facts(_task(TRY_ONE, "evaluate"), ctx))
    assert ctx["_l_sudo_probe_verdict"].strip() == verdict
    ctx.update(_facts(_task(TRY_ONE, "record attempt"), ctx))
    assert ctx["_l_sudo_rejections"] == rejected
    attempt = ctx["_l_sudo_attempts"][0]
    assert set(attempt) == {"label", "rc", "unreachable", "verdict"} and attempt["verdict"] == verdict
    assert _when(_task(TRY_ONE, "promote on success"), ctx) is (verdict == "ok")
    stop_task = _task(TRY_ONE, "stop candidates unless the password was rejected")
    assert _when(stop_task, ctx) is stop
    if stop:
        facts = _facts(stop_task, ctx)
        assert (facts["_l_sudo_mode"], facts["_l_sudo_outcome"].strip(), facts["ansible_become_pass"]) == (mode, outcome, "")


def test_stop_task_is_last_and_block_guards_ok_stopped_and_budget():
    doc = load_tasks(TRY_ONE)
    outer = doc[-1]
    assert "stop candidates unless the password was rejected" in outer["block"][-1]["name"]
    guard = {"when": outer["when"]}
    base = {"_l_sudo_ok": False, "_l_sudo_stopped": False, "_l_sudo_rejections": 0, "_l_sudo_max_rejections": 3}
    assert _when(guard, base) is True
    assert _when(guard, {**base, "_l_sudo_ok": True}) is False
    assert _when(guard, {**base, "_l_sudo_stopped": True}) is False
    assert _when(guard, {**base, "_l_sudo_rejections": 3}) is False, "예산에 닿으면 후보가 남아도 보내지 않는다"
    assert _when(guard, {**base, "_l_sudo_rejections": 1, "_l_sudo_max_rejections": 1}) is False
    assert _when(guard, {}) is True, "fact 가 하나도 없어도 첫 후보는 보낸다"
    assert _when(guard, {"_l_sudo_rejections": 1}) is False, "예산 fact 가 없으면 기본 1 — 첫 거부 뒤 멈춘다"


def test_candidates_are_login_first_and_deduped():
    build = _task(TRY_SUDO, "build candidates")
    vault = [{"label": "sudo_primary", "role": "primary", "password": "A"},
             {"label": "sudo_fallback1", "role": "secondary", "password": "B"}]
    out = _facts(build, {"ansible_password": "A", "_cred_sudo_candidates": vault})["_l_sudo_candidates"]
    assert [c["label"] for c in out] == ["login", "sudo_fallback1"], "로그인 값과 같은 Vault 항목은 뺀다"
    out = _facts(build, {"ansible_password": "Z", "_cred_sudo_candidates": vault})["_l_sudo_candidates"]
    assert [c["label"] for c in out] == ["login", "sudo_primary", "sudo_fallback1"]
    out = _facts(build, {"ansible_password": "", "_cred_sudo_candidates": vault})["_l_sudo_candidates"]
    assert [c["label"] for c in out] == ["sudo_primary", "sudo_fallback1"], "키 로그인(비밀번호 없음)이면 로그인 후보가 없다"
    assert _facts(build, {"ansible_password": None, "_cred_sudo_candidates": []})["_l_sudo_candidates"] == []
    assert _facts(build, {"_cred_sudo_candidates": vault, "ansible_password": "A"})["_l_sudo_candidates"][0]["role"] == "login"


def test_unsuccessful_end_states():
    task = _task(TRY_SUDO, "classify when no candidate succeeded")
    f = _facts(task, {"_l_sudo_tries": 0, "_l_sudo_rejections": 0, "_l_sudo_max_rejections": 3})
    assert (f["_l_sudo_mode"], f["_l_sudo_outcome"].strip()) == ("unavailable", "no_candidate")
    f = _facts(task, {"_l_sudo_tries": 2, "_l_sudo_rejections": 2, "_l_sudo_max_rejections": 3})
    assert (f["_l_sudo_mode"], f["_l_sudo_outcome"].strip()) == ("rejected", "password_rejected")
    f = _facts(task, {"_l_sudo_tries": 3, "_l_sudo_rejections": 3, "_l_sudo_max_rejections": 3})
    assert (f["_l_sudo_mode"], f["_l_sudo_outcome"].strip()) == ("rejected", "budget_exhausted")
    assert f["ansible_become_pass"] == ""


def test_meta_marks_fallback_only_for_vault_candidates():
    meta = _task(TRY_SUDO, "record meta")
    base = {"_l_sudo_ok": True, "_l_sudo_mode": "password", "_l_sudo_outcome": "password_accepted", "_l_sudo_tries": 1,
            "_l_sudo_rejections": 0, "_l_sudo_max_rejections": 3, "_l_sudo_used_label": "login", "_l_sudo_policy": {}, "_l_sudo_attempts": []}
    assert _facts(meta, base)["_l_sudo_meta"]["fallback_used"] is False
    assert _facts(meta, {**base, "_l_sudo_used_label": "sudo_primary"})["_l_sudo_meta"]["fallback_used"] is True
    assert _facts(meta, {**base, "_l_sudo_ok": True, "_l_sudo_mode": "nopasswd", "_l_sudo_used_label": None})["_l_sudo_meta"]["fallback_used"] is False


# ── 4. 잠금 예산 (preflight.yml) ───────────────────────────────────────────────────────────────────
def _budget(pf: dict[str, str]) -> tuple[dict[str, Any], int]:
    ctx = {"_l_pf": pf}
    ctx.update(_facts(_task(PREFLIGHT, "sudo lockout policy"), ctx))
    ctx.update(_facts(_task(PREFLIGHT, "sudo max rejections"), ctx))
    return ctx["_l_sudo_policy"], int(ctx["_l_sudo_max_rejections"])


@pytest.mark.parametrize("pf,expected", [
    ({"LOCK_PAM_FILES": "2", "LOCK_MODULE": "0", "LOCK_CONF": "1"}, 3),                                        # 잠금 모듈 없음 (.132 Ubuntu 24.04 와 같다)
    ({"LOCK_PAM_FILES": "3", "LOCK_MODULE": "1", "LOCK_ROOT_INLINE": "0", "LOCK_CONF": "1", "LOCK_ROOT_CONF": "0"}, 3),   # root 는 잠기지 않는 정책
    ({"LOCK_PAM_FILES": "3", "LOCK_MODULE": "1", "LOCK_ROOT_CONF": "1", "LOCK_CONF": "1"}, 1),                  # deny 기본 3 → 1 (로그인만)
    ({"LOCK_PAM_FILES": "3", "LOCK_MODULE": "1", "LOCK_ROOT_CONF": "1", "LOCK_CONF": "1", "LOCK_DENY_CONF": "4"}, 2),
    ({"LOCK_PAM_FILES": "3", "LOCK_MODULE": "1", "LOCK_ROOT_CONF": "1", "LOCK_CONF": "1", "LOCK_DENY_CONF": "5"}, 3),
    ({"LOCK_PAM_FILES": "3", "LOCK_MODULE": "1", "LOCK_ROOT_CONF": "1", "LOCK_CONF": "1", "LOCK_DENY_CONF": "9"}, 3),   # 상한 3
    ({"LOCK_PAM_FILES": "3", "LOCK_MODULE": "1", "LOCK_ROOT_INLINE": "1", "LOCK_DENY_INLINE": "6", "LOCK_CONF": "1", "LOCK_DENY_CONF": "3"}, 3),  # inline 우선
    ({"LOCK_PAM_FILES": "3", "LOCK_MODULE": "1", "LOCK_ROOT_CONF": "1", "LOCK_CONF": "1", "LOCK_DENY_CONF": "5", "LOCK_UNLOCK_CONF": "0"}, 2),  # 영구 잠금 → 1 감산
    ({"LOCK_PAM_FILES": "3", "LOCK_MODULE": "1", "LOCK_ROOT_CONF": "1", "LOCK_CONF": "1", "LOCK_DENY_CONF": "3", "LOCK_UNLOCK_CONF": "0"}, 1),  # 최소 1
    ({"LOCK_PAM_FILES": "0"}, 1),                                                                                # 읽지 못함 → 가장 보수적
    ({}, 1),
])
def test_budget_matrix(pf, expected):
    policy, budget = _budget(pf)
    assert budget == expected, policy


def test_policy_values_are_typed_and_secret_free():
    policy, _ = _budget({"LOCK_PAM_FILES": "3", "LOCK_MODULE": "1", "LOCK_ROOT_CONF": "1", "LOCK_CONF": "1",
                         "LOCK_DENY_CONF": "4", "LOCK_UNLOCK_CONF": "600", "LOCK_INTERVAL_CONF": "900"})
    assert policy == {"pam_files": 3, "lock_module": True, "deny": 4, "even_deny_root": True, "unlock_time": 600, "fail_interval": 900}


def test_preflight_reads_policy_without_privilege_and_without_extra_remote_calls():
    raws = [t for t in iter_tasks(load_tasks(PREFLIGHT)) if "ansible.builtin.raw" in t]
    assert len(raws) == 1 and "become" not in raws[0], "정책 읽기는 기존 preflight raw 한 번에 얹는다"
    body = raws[0]["ansible.builtin.raw"]
    for marker in ("LOCK_PAM_FILES=", "LOCK_MODULE=", "LOCK_DENY_INLINE=", "LOCK_ROOT_INLINE=", "LOCK_CONF=", "LOCK_DENY_CONF=",
                   "LOCK_ROOT_CONF=", "LOCK_UNLOCK_CONF=", "LOCK_INTERVAL_CONF="):
        assert marker in body, marker
    assert "sudo" not in body.replace("/etc/pam.d/sudo", ""), "preflight 는 sudo 를 부르지 않는다"


# ── 5. gather_system.yml 게이트 ────────────────────────────────────────────────────────────────────
def _gated(task: dict[str, Any], parents: list[dict[str, Any]]) -> bool:
    conds = []
    for t in parents + [task]:
        w = t.get("when")
        conds += (w if isinstance(w, list) else ([w] if w is not None else []))
    return any("_l_sudo_ok | default(true)" in str(c) for c in conds)


def test_every_become_task_in_gather_system_is_gated_by_sudo_ok():
    found = []

    def walk(items, parents):
        for t in items or []:
            if "block" in t:
                walk(t["block"], parents + [t])
            elif t.get("become") is True:
                found.append(t.get("name"))
                assert _gated(t, parents), t.get("name")
    walk(load_tasks(SYSTEM), [])
    assert len(found) == 4, found
    assert ansible_env().from_string("{{ _l_sudo_ok | default(true) | bool }}").render() is True
    assert ansible_env().from_string("{{ _l_sudo_ok | default(true) | bool }}").render(_l_sudo_ok=False) is False


def test_gated_off_privileged_registers_fall_into_privilege_failure():
    skipped = {"skipped": True, "changed": False, "skip_reason": "Conditional result was False"}
    parse = set_fact_args(SYSTEM, "parse raw results")
    ctx = {"_l_raw_sys_result": {"rc": 0, "stdout_lines": ["OS_ID=rhel", "DMI_PRODUCT_SERIAL=", "DMI_SYS_VENDOR=Dell Inc."]},
           "_l_raw_priv_result": skipped}
    out = render_tree(ansible_env(), parse, ctx)
    assert out["_l_raw_priv_failed"] is True and out["_l_raw_sys"]["DMI_SYS_VENDOR"] == "Dell Inc."
    runtime = set_fact_args(SYSTEM, "parse runtime")
    out = render_tree(ansible_env(), runtime, {"_l_runtime_raw": {"stdout_lines": ["TZ=UTC"]}, "_l_runtime_fw_raw": skipped})
    assert out["_l_runtime_fw_failed"] is True and out["_l_runtime"]["TZ"] == "UTC"


# ── 6. site.yml 배선 ────────────────────────────────────────────────────────────────────────────────
def test_site_yml_includes_try_sudo_after_preflight_and_exposes_details_sudo():
    plays = yaml.safe_load(SITE.read_text(encoding="utf-8"))
    linux = next(p for p in plays if p.get("hosts") == "_os_linux")
    main = next(t for t in linux["tasks"] if "block" in t)
    names = [t.get("name") for t in main["block"]]
    assert names.index("linux | try sudo") == names.index("linux | preflight") + 1
    assert main["block"][names.index("linux | try sudo")]["ansible.builtin.include_tasks"] == "tasks/linux/try_sudo.yml"
    success = next(t for t in main["block"] if t.get("name") == "linux | build diagnosis (success path)")
    assert success["ansible.builtin.set_fact"]["_diagnosis"]["details"]["sudo"] == "{{ _l_sudo_meta | default({}) }}"
    rescue = next(t for t in main["rescue"] if "Portal 표시용 diagnosis 보장" in t.get("name", ""))
    assert "'sudo': (_l_sudo_meta | default({}))" in rescue["ansible.builtin.set_fact"]["_diagnosis"]
    windows = next(p for p in plays if p.get("hosts") == "_os_windows")
    assert "try_sudo" not in yaml.safe_dump(windows), "Windows 인증 경로는 그대로다"
