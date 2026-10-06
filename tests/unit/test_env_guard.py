"""F05 (2026-10-05) · 8차 R1: 빌드 환경 경계 — 상위 환경에서 넘어온 시험용 · 재정의 값이 운영 수집을 바꾸지 못한다.

`scripts/env_guard.sh` 를 bash 로 실제 source 해서 확인한다 (Runner 의 bash 에서도 CI Gate 가 같은 시험을 돈다).
Jenkins withEnv 로 값을 넣지 않는 것만으로는 agent 프로세스에서 상속된 값이 남는다 — 그래서 셸에서 지운다.
수집 실행은 scripts/run_gather.sh 한 곳이고, 그 스크립트가 ansible-playbook 직전에 이 경계를 지난다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GUARD = REPO / "scripts" / "env_guard.sh"
RUN_GATHER = (REPO / "scripts" / "run_gather.sh").read_text(encoding="utf-8")
BASH = shutil.which("bash")
PORTAL = (REPO / "Jenkinsfile_portal").read_text(encoding="utf-8")
CLEARED_ALWAYS = ("SE_FORCE_LINUX_RAW_FALLBACK", "JSON_ONLY_NO_RECONCILE", "ANSIBLE_JSON_OUTPUT_TASK", "ANSIBLE_JSON_CHECKPOINT_TASK",
                  "ANSIBLE_STDOUT_CALLBACK", "SE_VENDOR_ALIASES_PATH")
KEPT = {"ANSIBLE_CONFIG": "/w/ansible.cfg", "ANSIBLE_JSON_OUTPUT_FILE": "/w/gather_output.json", "SE_FORKS_CAP_OS": "80",
        "REPO_ROOT": "/w"}


def _run(addon_validated: str, extra: dict) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in CLEARED_ALWAYS + ("ADDON_DIR", "SE_FORCE_SEC")}
    env.update(extra)
    names = " ".join(CLEARED_ALWAYS + ("ADDON_DIR",) + tuple(KEPT))
    script = (f'. "{GUARD.as_posix()}" {addon_validated}\n'
              f'for v in {names}; do if printenv "$v" >/dev/null; then echo "LEFT $v"; fi; done\n')
    return subprocess.run([BASH, "-c", script], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)


pytestmark = pytest.mark.skipif(BASH is None, reason="bash 없음")


def test_inherited_test_values_are_cleared_and_only_names_are_logged():
    inherited = {name: f"secret-ish-{i}" for i, name in enumerate(CLEARED_ALWAYS)} | {"ADDON_DIR": "/tmp/unverified-addon"} | KEPT
    r = _run("false", inherited)
    assert r.returncode == 0, r.stderr
    left = {line.split()[1] for line in r.stdout.splitlines() if line.startswith("LEFT ")}
    assert left == set(KEPT), "운영 설정(ansible.cfg 경로 · forks 상한 등)은 남기고 시험용 값만 지운다"
    msg = [line for line in r.stdout.splitlines() if line.startswith("[수집]")]
    assert len(msg) == 1 and "ADDON_DIR" in msg[0] and all(n in msg[0] for n in CLEARED_ALWAYS)
    assert "secret-ish" not in r.stdout and "/tmp/unverified-addon" not in r.stdout, "값은 출력하지 않는다"


def test_validated_addon_dir_is_kept():
    r = _run("true", {"ADDON_DIR": "/w/addon", "SE_FORCE_LINUX_RAW_FALLBACK": "true"})
    left = {line.split()[1] for line in r.stdout.splitlines() if line.startswith("LEFT ")}
    assert left == {"ADDON_DIR"}
    assert "ADDON_DIR" not in next(line for line in r.stdout.splitlines() if line.startswith("[수집]"))


def test_clean_environment_prints_nothing():
    r = _run("false", {})
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_empty_but_set_values_are_cleared_too():
    r = _run("false", {"SE_VENDOR_ALIASES_PATH": "", "ADDON_DIR": ""})
    assert "LEFT" not in r.stdout and "SE_VENDOR_ALIASES_PATH" in r.stdout


def test_removed_force_value_is_not_even_read():
    """8차 R1: 수집 시간 강제값(SE_FORCE_SEC)은 이제 어디서도 읽지 않는다 — 지울 대상도 아니다(남아 있어도 효과가 없다)."""
    guard = GUARD.read_text(encoding="utf-8")
    body = guard[guard.index("_se_guard_names="):]
    assert "SE_FORCE_SEC" not in body
    assert "SE_FORCE_SEC" not in PORTAL and "SE_FORCE_SEC" not in RUN_GATHER


def test_run_gather_sources_the_guard_before_ansible():
    i_guard = RUN_GATHER.index('. "$WS/scripts/env_guard.sh" "$ADDON_OK"')
    assert i_guard < RUN_GATHER.index('. "$WS/scripts/activate_ansible_venv.sh" || exit 90') < RUN_GATHER.index("ansible-playbook \"$PLAYBOOK\"")
    line = next(l for l in PORTAL.splitlines() if "scripts/run_gather.sh" in l and "bash " in l)
    assert "${addonDir ? 'true' : 'false'}" in line


def test_memory_is_never_an_input():
    """9차: 가용 메모리로 수집 시작을 막지 않는다 — 어디서도 메모리 값을 읽지 않으므로 시험 입력(SE_MEM_AVAILABLE_MB)을 지울 필요도 없다."""
    state = (REPO / "scripts" / "gather_state.py").read_text(encoding="utf-8")
    for text in (PORTAL, RUN_GATHER, state, GUARD.read_text(encoding="utf-8").split("_se_guard_names=", 1)[1]):
        assert "SE_MEM_AVAILABLE_MB" not in text and "meminfo" not in text and "MemAvailable" not in text
    assert "SE_FORCE_SEC" not in PORTAL


@pytest.mark.source_text
def test_guard_and_runner_are_shipped_in_the_production_tree():
    manifest = (REPO / "production_manifest.yml").read_text(encoding="utf-8")
    assert "  - path: scripts/env_guard.sh\n    language: shell\n" in manifest
    assert "  - path: scripts/run_gather.sh\n    language: shell\n" in manifest
    assert "scripts/gather_watch.py" not in manifest


def test_unparsed_inventory_fails_only_the_jenkins_gather_run():
    """2026-10-05 (F03 · CI #21): inventory 해석 실패를 실행 실패로 바꾸는 설정은 Jenkins 수집 실행에만 켠다 — ansible.cfg 에 두면
    진단용 ad-hoc 명령 · 시험 도구 · 승격 게이트 G15(모듈 smoke)가 "No inventory was parsed" 로 실패했다."""
    cfg = (REPO / "ansible.cfg").read_text(encoding="utf-8")
    assert not any(line.strip().startswith("unparsed_is_failed") for line in cfg.splitlines())
    i_env = RUN_GATHER.index("export ANSIBLE_INVENTORY_UNPARSED_FAILED=True")
    assert RUN_GATHER.index('. "$WS/scripts/env_guard.sh"') < i_env < RUN_GATHER.index('ansible-playbook "$PLAYBOOK"')
