"""ESXi vmware_host_facts 중복 실행 제거 (2026-10-03, P5 — Plan §8-4).

자격 확인(try_one_credential.yml)의 probe 와 collect_facts.yml 이 같은 모듈 · 같은 스키마(summary)를
같은 host 에 두 번 실행했다. 인증에 성공한 probe 의 facts 를 promote 시점에 _e_probe_facts 로
보관하고, collect_facts.yml 은 그것이 있으면 모듈을 다시 부르지 않는다.

고정하는 계약:
  - host 당 모듈 실행(인증 성공 경로): esxi-gather/tasks/*.yml 의 모듈 태스크 중 재사용 조건
    (_e_facts_reused)으로 막히지 않는 것은 12개다 (종전 13). 재사용 조건은 collect_facts 의
    vmware_host_facts 하나에만 걸린다.
  - probe 와 fallback 의 모듈 인자는 자격증명을 빼면 같다 → 같은 함수(all_facts)가 같은 키를 낸다.
  - _e_raw_facts / _e_facts_ok 는 재사용 경로와 모듈 경로에서 같은 값이다.
  - 재사용은 인증 성공 + summary 스키마 표지가 있을 때만. 아니면 종전처럼 모듈을 부른다.
  - collect_facts 는 _e_probe 를 직접 읽지 않는다 — 인증 성공 뒤 남은 후보의 probe 가 skip 되면서
    _e_probe 를 skip 결과로 덮어쓴다 (ansible-core 2.20.7 실측: keys = changed / false_condition /
    skip_reason / skipped).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.e2e.test_failure_reason_contract import _env as _base_env
from tests.e2e.test_failure_reason_contract import _iter_tasks

REPO = Path(__file__).resolve().parents[2]
_TASKS = REPO / "esxi-gather" / "tasks"
_FACTS = "esxi-gather/tasks/collect_facts.yml"
_PROBE = "esxi-gather/tasks/try_one_credential.yml"
_SITE = "esxi-gather/site.yml"
_VHF = "community.vmware.vmware_host_facts"
_REUSE_FLAG = "_e_facts_reused"

# 대상(vSphere)을 부르지 않는 제어/변수 액션 — 모듈 실행으로 세지 않는다.
_CONTROL_ACTIONS = {
    "ansible.builtin.set_fact", "set_fact", "ansible.builtin.debug", "debug",
    "ansible.builtin.include_tasks", "include_tasks", "ansible.builtin.import_tasks", "import_tasks",
    "ansible.builtin.fail", "fail", "ansible.builtin.assert", "assert", "ansible.builtin.meta", "meta",
}
_TASK_KEYWORDS = {
    "name", "when", "register", "delegate_to", "failed_when", "changed_when", "no_log", "loop",
    "loop_control", "vars", "tags", "ignore_errors", "ignore_unreachable", "until", "retries", "delay",
    "environment", "args", "become", "run_once", "timeout", "block", "rescue", "always",
}

# community.vmware 6.2.0 vmware_host_facts all_facts() 가 내는 키 (schema=summary, show_tag /
# show_datacenter 기본 false). 2026-10-03 WSL 에서 실제 모듈 코드로 reference dump(esxi01, vmk0 1개)
# 를 돌려 확인했다. probe 인자 · fallback 인자 두 번 모두 키와 값이 같았다.
_SUMMARY_KEYS = (
    "ansible_all_ipv4_addresses", "ansible_bios_date", "ansible_bios_version", "ansible_datastore",
    "ansible_distribution", "ansible_distribution_build", "ansible_distribution_version",
    "ansible_host_connection_state", "ansible_hostname", "ansible_in_maintenance_mode",
    "ansible_interfaces", "ansible_memfree_mb", "ansible_memtotal_mb", "ansible_os_type",
    "ansible_processor", "ansible_processor_cores", "ansible_processor_count", "ansible_processor_vcpus",
    "ansible_product_name", "ansible_product_serial", "ansible_system_vendor", "ansible_uptime",
    "ansible_uuid", "ansible_vmk0", "cluster", "host_date_time", "vsan_cluster_uuid", "vsan_health",
    "vsan_node_uuid",
)
# 하류가 default() 로 읽지만 summary 스키마에는 없는 키 — 두 경로 모두 없다 (경로 간 차이 아님).
_NOT_IN_SUMMARY = {"ansible_machine", "ansible_processor_mhz"}
# 모듈 인자 기본값 (community.vmware 6.2.0 vmware_host_facts argument_spec).
_VHF_DEFAULTS = {"schema": "summary", "show_tag": False, "show_datacenter": False}
# Ansible 이 skip 된 태스크에 register 하는 값 (ansible-core 2.20.7 실측 키).
_SKIPPED = {"changed": False, "skipped": True, "skip_reason": "Conditional result was False",
            "false_condition": "not (_e_facts_reused | bool)"}


def _facts() -> dict[str, Any]:
    facts: dict[str, Any] = {key: None for key in _SUMMARY_KEYS}
    facts.update(ansible_hostname="esxi01", ansible_distribution="VMware ESXi",
                 ansible_distribution_version="7.0.3", ansible_distribution_build="20842708",
                 ansible_interfaces=["vmk0"],
                 ansible_vmk0={"device": "vmk0", "ipv4": {"address": "10.100.64.1"}})
    return facts


# ---------------------------------------------------------------------------
# production YAML 읽기 / 렌더
# ---------------------------------------------------------------------------
def _load(rel: str) -> Any:
    return yaml.safe_load((REPO / rel).read_text(encoding="utf-8")) or []


def _task(rel: str, needle: str) -> dict[str, Any]:
    for task in _iter_tasks(_load(rel)):
        if needle in (task.get("name") or ""):
            return task
    raise AssertionError(f"{rel} 에서 태스크를 찾지 못함: {needle!r}")


def _env():
    env = _base_env()

    def _failed(result: Any) -> bool:   # ansible.builtin `failed` test 대역
        if not isinstance(result, dict):
            raise TypeError("The 'failed' test expects a dictionary")
        return bool(result.get("failed", False))

    env.tests["failed"] = _failed
    return env


def _render(template: Any, **ctx: Any) -> Any:
    return _env().from_string(template).render(**ctx) if isinstance(template, str) else template


def _whens(task: dict[str, Any]) -> tuple[str, ...]:
    when = task.get("when")
    if when is None:
        return ()
    return tuple(str(w) for w in (when if isinstance(when, list) else [when]))


def _module_tasks(node: Any, file: str, guards: tuple[str, ...] = ()):
    """(파일, 액션, 유효 when 목록) — block 의 when 은 안쪽 태스크로 상속된다."""
    for task in node or []:
        if not isinstance(task, dict):
            continue
        effective = guards + _whens(task)
        if "block" in task:
            for key in ("block", "rescue", "always"):
                yield from _module_tasks(task.get(key), file, effective)
            continue
        actions = [k for k in task if k not in _TASK_KEYWORDS]
        if actions and actions[0] not in _CONTROL_ACTIONS:
            yield file, actions[0], effective


def _all_module_tasks() -> list[tuple[str, str, tuple[str, ...]]]:
    out = []
    for path in sorted(_TASKS.glob("*.yml")):
        out.extend(_module_tasks(yaml.safe_load(path.read_text(encoding="utf-8")), path.name))
    return out


# ═══════════════════════════════════════════════════════════════════════════
# 모듈 실행 수 — host 당 13 → 12
# ═══════════════════════════════════════════════════════════════════════════
def test_module_runs_per_host_drop_from_13_to_12():
    tasks = _all_module_tasks()
    # 2026-10-06 (9차 W06): 자격 probe 가 **실패했을 때만** 도는 관리 포트 재확인(wait_for, vSphere 를 부르지 않는다)은
    #   인증 성공 경로의 예산에 들지 않는다. 실패 경로 전용 태스크는 그것 하나뿐이다.
    failure_only = [(f, a) for f, a, g in tasks if any("not (_e_probe_ok | bool)" in w for w in g)]
    assert failure_only == [("try_one_credential.yml", "ansible.builtin.wait_for")], failure_only
    tasks = [t for t in tasks if (t[0], t[1]) not in failure_only]
    guarded = [(f, a) for f, a, g in tasks if any(_REUSE_FLAG in w for w in g)]
    unguarded = [(f, a) for f, a, g in tasks if not any(_REUSE_FLAG in w for w in g)]
    assert guarded == [("collect_facts.yml", _VHF)], (
        f"재사용 조건은 collect_facts 의 vmware_host_facts 하나에만 걸려야 한다: {guarded}")
    assert len(unguarded) == 12, (
        "인증 성공 경로의 host 당 모듈 실행 예산은 12 다 (종전 13). 모듈 태스크를 더하거나 빼면 "
        f"이 예산을 의식적으로 고친다: {unguarded}")
    assert [x for x in unguarded if x[1] == _VHF] == [("try_one_credential.yml", _VHF)], (
        "vmware_host_facts 는 자격 probe 한 번만 무조건 실행된다")


def test_probe_and_fallback_request_the_same_facts():
    """같은 모듈 · 같은 인자(자격증명 제외) → 같은 all_facts() → 같은 키."""
    def normalized(rel: str) -> dict[str, Any]:
        tasks = [t for t in _iter_tasks(_load(rel)) if _VHF in t]
        assert len(tasks) == 1, rel
        args = {k: v for k, v in tasks[0][_VHF].items() if k not in ("username", "password")}
        for key, value in _VHF_DEFAULTS.items():
            args.setdefault(key, value)
        return args

    probe, fallback = normalized(_PROBE), normalized(_FACTS)
    assert probe == fallback, (probe, fallback)
    assert probe["schema"] == "summary" and "properties" not in probe


# ═══════════════════════════════════════════════════════════════════════════
# probe facts 보관 — 인증 성공 promote 시점에만
# ═══════════════════════════════════════════════════════════════════════════
def test_probe_facts_are_captured_at_successful_promotion():
    promote = _task(_PROBE, "promote on success")
    assert promote["when"] == "_e_probe_ok | bool", "보관은 인증 성공 promote 와 같은 조건이어야 한다"
    template = promote["ansible.builtin.set_fact"]["_e_probe_facts"]
    facts = _facts()
    assert _render(template, _e_probe={"changed": False, "ansible_facts": facts}) == facts


def test_collect_facts_never_reads_the_overwritable_probe_register():
    text = (REPO / _FACTS).read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "_e_probe." not in code and "_e_probe |" not in code, (
        "_e_probe 는 뒤 후보 probe 의 skip 결과로 덮어써진다 — 보관값 _e_probe_facts 만 읽는다")


# ═══════════════════════════════════════════════════════════════════════════
# 재사용 판정
# ═══════════════════════════════════════════════════════════════════════════
_ABSENT = object()


@pytest.mark.parametrize("auth_ok,probe_facts,expected", [
    (True, "FACTS", True),
    (False, "FACTS", False),                                          # 인증 미확정
    (True, {}, False),
    (True, _ABSENT, False),                                           # 자격 후보 0건 — probe 미실행
    (True, {"discovered_interpreter_python": "/usr/bin/python3"}, False),   # facts 아닌 dict
    (True, "not-a-mapping", False),
], ids=["auth+facts", "no-auth", "empty", "absent", "interpreter-only", "non-mapping"])
def test_reuse_only_after_auth_with_summary_facts(auth_ok, probe_facts, expected):
    template = _task(_FACTS, "reuse credential probe facts")["ansible.builtin.set_fact"][_REUSE_FLAG]
    ctx: dict[str, Any] = {"_e_auth_ok": auth_ok}
    if probe_facts is not _ABSENT:
        ctx["_e_probe_facts"] = _facts() if probe_facts == "FACTS" else probe_facts
    assert _render(template, **ctx) is expected


def test_fallback_module_call_is_guarded_by_the_reuse_flag():
    module_task = _task(_FACTS, "esxi | collect | vmware_host_facts")
    assert _whens(module_task) == ("not (_e_facts_reused | bool)",)


# ═══════════════════════════════════════════════════════════════════════════
# 두 출처의 결과가 같다 — 하류가 읽는 _e_raw_facts / _e_facts_ok
# ═══════════════════════════════════════════════════════════════════════════
def _store(**ctx: Any) -> tuple[Any, Any]:
    facts_task = _task(_FACTS, "store raw facts")["ansible.builtin.set_fact"]
    return _render(facts_task["_e_raw_facts"], **ctx), _render(facts_task["_e_facts_ok"], **ctx)


def test_reused_and_fetched_facts_are_identical():
    facts = _facts()
    reused = _store(_e_facts_reused=True, _e_probe_facts=facts, _e_facts_result=_SKIPPED)
    fetched = _store(_e_facts_reused=False, _e_facts_result={"changed": False, "ansible_facts": facts})
    assert reused == fetched == (facts, True)


def test_module_failure_still_yields_no_facts():
    """재사용하지 않는 경로의 실패 판정은 종전과 같다 (failed_when:false 로 덮인 로그인 실패)."""
    raw, ok = _store(_e_facts_reused=False, _e_facts_result={
        "changed": False, "failed": False, "failed_when_result": False,
        "msg": "Cannot complete login due to an incorrect user name or password."})
    assert raw == {} and ok is False


def test_downstream_reads_only_summary_schema_keys():
    """하류(site.yml + tasks)가 읽는 _e_raw_facts 키는 summary 스키마 키다 — 두 출처가 같은 스키마."""
    import re

    consumed: set[str] = set()
    for path in [REPO / _SITE, *sorted(_TASKS.glob("*.yml"))]:
        consumed |= set(re.findall(r"_e_raw_facts\.(\w+)", path.read_text(encoding="utf-8")))
    consumed.discard("get")   # _e_raw_facts.get('ansible_' ~ iface) — 인터페이스별 키 (ansible_vmk0 등)
    assert consumed, "하류 소비 키를 찾지 못했다"
    unknown = sorted(consumed - set(_SUMMARY_KEYS) - _NOT_IN_SUMMARY)
    assert not unknown, f"summary 스키마에 없는 키를 하류가 읽는다: {unknown}"
