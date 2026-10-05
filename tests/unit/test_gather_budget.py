"""scripts/gather_budget.sh — 수집 실행 한계 계산 (2026-10-03 Plan §6-2, 2026-10-05 8차 R3 개정).

고정하는 것
  - 시간 한계: 빌드 12시간 = 입력 확인 · 실행 위치 확인 10분 + 서버 정보 수집 단계 39000초 + 결과 확인 및 전송 1시간.
    실행 한계 limit = min(6시간, 단계 남은 시간 − GRACE − AGENT_POST, 빌드 남은 시간 − FINALIZER − GRACE − AGENT_POST).
    6시간을 다 줄 수 없으면 limit_source=build_limit — 6시간을 보장했다고 하지 않는다.
  - 예상 시간(expected = BASE + host_est × waves)은 안내용이다. 실행 한계에 영향을 주지 않는다.
  - limit < MIN_START → start=false (not_started_budget). 입력 불량은 rc 2.
  - 메모리 보호(P-1): mem_cap = floor((MemAvailable × share − fixed) / per_fork); forks = min(forks, mem_cap); mem_cap ≤ 0 → not_started_memory;
    MemAvailable 을 못 읽으면 mem_guard=unavailable 로 기존 상한. 시험은 SE_MEM_AVAILABLE_MB 를 명시해 결정적으로 돈다.
  - 8차 R1: 강제 한계 입력(SE_FORCE_SEC)은 없다 — 상위 환경에 남아 있어도 결과가 바뀌지 않는다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "gather_budget.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash 없음")

T0 = 1_700_000_000
BUILD, PRE, STAGE, FINALIZER, GATHER_MAX, GRACE, AGENT_POST, MIN_START = 43200, 600, 39000, 3600, 21600, 90, 900, 120


def run(**env):
    base = {"SE_NOW_EPOCH": str(T0), "SE_BUILD_START_EPOCH": str(T0), "SE_STAGE_START_EPOCH": str(T0),
            "SE_CHANNEL": "os", "SE_HOSTS": "3", "SE_VCPU": "8",
            "SE_MEM_AVAILABLE_MB": "16000"}   # (16000×0.4 − 200)/80 = 77 ≥ OS 상한 50 → 메모리 보호가 forks 를 바꾸지 않는 기준 환경
    base.update({k: str(v) for k, v in env.items()})
    e = dict(os.environ)
    for k in ("SE_FORCE_SEC", "SE_FORKS_CAP_OS", "SE_PER_FORK_MB", "SE_FIXED_MB", "SE_NODE_SHARE_PCT"):
        e.pop(k, None)
    e.update(base)
    r = subprocess.run([BASH, str(SCRIPT)], env=e, capture_output=True, text=True)
    return r.returncode, json.loads(r.stdout.strip()) if r.stdout.strip() else None


def test_fresh_build_gets_the_full_six_hours():
    rc, b = run()
    assert rc == 0 and b["start"] is True and b["reason"] == "computed"
    assert b["limit"] == GATHER_MAX and b["limit_source"] == "gather_limit" and b["gather_max"] == GATHER_MAX
    assert b["stage_remaining"] == STAGE - GRACE - AGENT_POST
    assert b["build_remaining"] == BUILD - FINALIZER - GRACE - AGENT_POST
    assert b["forks"] == 3 and b["waves"] == 1 and b["expected"] == 300 + 240


def test_constants_add_up_and_match_the_pipeline():
    _, b = run()
    c = b["constants"]
    assert c["build"] == BUILD == c["pre"] + c["stage"] + c["finalizer"], "앞 단계가 길어도 결과 확인 및 전송에 1시간이 남는다"
    assert (c["pre"], c["stage"], c["finalizer"], c["gather_max"], c["grace"], c["agent_post"], c["min_start"]) == (
        PRE, STAGE, FINALIZER, GATHER_MAX, GRACE, AGENT_POST, MIN_START)
    assert c["per_fork_mb"] == 80 and c["fixed_mb"] == 200 and c["node_share_pct"] == 40
    for gone in ("stall", "reserve", "global", "stage_limit", "post", "cap", "min"):
        assert gone not in c, gone
    for gone in ("stall", "budget", "hard_remaining", "host_cap", "gather", "force"):
        assert gone not in b, gone


def test_expected_time_never_changes_the_limit():
    """예상 공식이 빗나가도(큰 배치 · 느린 대상) 실행 한계는 6시간 그대로다 — 예상은 안내와 자원 계획에만 쓴다."""
    for channel, hosts in (("os", 3), ("os", 200), ("esxi", 6), ("redfish", 10), ("redfish", 400)):
        _, b = run(SE_CHANNEL=channel, SE_HOSTS=hosts)
        assert b["limit"] == GATHER_MAX and b["limit_source"] == "gather_limit", (channel, hosts)
    _, b = run(SE_CHANNEL="redfish", SE_HOSTS=200, SE_VCPU=8)
    assert b["forks"] == 32 and b["waves"] == 7 and b["expected"] == 300 + 605 * 7


def test_long_wait_shrinks_the_limit_and_says_so():
    """Runner 대기 · checkout · Add-on 준비로 시간을 썼으면 그만큼만 줄고(build_limit), 결과 정리 · 보존 몫과 결과 확인 1시간은 줄지 않는다."""
    stage_start = T0 + 60
    now = stage_start + 5 * 3600                     # Runner 대기 5시간
    _, b = run(SE_NOW_EPOCH=now, SE_STAGE_START_EPOCH=stage_start)
    assert b["stage_remaining"] == stage_start + STAGE - now - GRACE - AGENT_POST == 39000 - 18000 - 990
    assert b["limit"] == b["stage_remaining"] < GATHER_MAX and b["limit_source"] == "build_limit" and b["start"] is True
    # 끝 무렵: 남은 시간이 MIN_START 미만이면 시작하지 않는다
    now = stage_start + STAGE - GRACE - AGENT_POST - (MIN_START - 1)
    _, b = run(SE_NOW_EPOCH=now, SE_STAGE_START_EPOCH=stage_start)
    assert b["limit"] == MIN_START - 1 and b["start"] is False and b["reason"] == "not_started_budget" and b["limit_source"] == "none"
    _, b = run(SE_NOW_EPOCH=now - 1, SE_STAGE_START_EPOCH=stage_start)
    assert b["limit"] == MIN_START and b["start"] is True, "경계: 정확히 MIN_START 면 시작한다"


def test_build_deadline_binds_when_the_stage_started_late():
    """입력 확인 · 실행 위치 확인이 비정상적으로 길었으면(단계 기준점이 늦다) 빌드 끝에서 결과 확인 1시간을 뺀 값이 구속한다."""
    stage_start = T0 + 2 * 3600
    now = stage_start + 3 * 3600
    _, b = run(SE_NOW_EPOCH=now, SE_STAGE_START_EPOCH=stage_start)
    assert b["build_remaining"] == T0 + BUILD - FINALIZER - now - GRACE - AGENT_POST
    assert b["limit"] == min(GATHER_MAX, b["stage_remaining"], b["build_remaining"]) == b["build_remaining"]


def test_forced_limit_input_is_gone():
    """8차 R1: 시험용 강제값은 운영 경로에서 없앴다 — 상위 환경에 SE_FORCE_SEC 이 남아 있어도 읽지 않는다."""
    _, plain = run()
    _, b = run(SE_FORCE_SEC=150)
    assert b == plain
    _, b = run(SE_FORCE_SEC="12s")
    assert b["limit"] == GATHER_MAX, "형식이 틀린 값도 무시한다(입력 오류로 끊지도 않는다)"
    assert "SE_FORCE_SEC" not in SCRIPT.read_text(encoding="utf-8").split("set -u", 1)[1], "본문에서 읽지 않는다(머리말 설명만)"


def test_os_forks_default_cap_50_and_runner_env_override():
    _, b = run(SE_CHANNEL="os", SE_HOSTS=200)
    assert b["forks"] == 50 and b["waves"] == 4 and b["expected"] == 300 + 240 * 4
    _, b = run(SE_CHANNEL="os", SE_HOSTS=200, SE_FORKS_CAP_OS=100, SE_MEM_AVAILABLE_MB=40000)
    assert b["forks"] == 100 and b["waves"] == 2
    _, b = run(SE_CHANNEL="os", SE_HOSTS=200, SE_FORKS_CAP_OS=100)
    assert b["forks"] == 77, "기준 환경(16000 MB)에서는 메모리 보호 mem_cap=77 이 노드 env 상향을 자른다"
    _, b = run(SE_CHANNEL="os", SE_HOSTS=200, SE_FORKS_CAP_OS="abc")
    assert b["forks"] == 50
    _, b = run(SE_CHANNEL="os", SE_HOSTS=30, SE_FORKS_CAP_OS=100)
    assert b["forks"] == 30


def test_esxi_and_redfish_forks_scale_with_vcpu():
    _, b = run(SE_CHANNEL="esxi", SE_HOSTS=50, SE_VCPU=4)
    assert b["forks"] == 8 and b["waves"] == 7
    _, b = run(SE_CHANNEL="redfish", SE_HOSTS=50, SE_VCPU=4)
    assert b["forks"] == 16 and b["waves"] == 4


def test_memory_guard_caps_forks():
    _, b = run(SE_CHANNEL="os", SE_HOSTS=200, SE_MEM_AVAILABLE_MB=1000)        # (400 − 200)/80 = 2
    assert b["mem_guard"] == "active" and b["mem_avail_mb"] == 1000 and b["mem_cap"] == 2
    assert b["forks"] == 2 and b["waves"] == 100 and b["limit"] == GATHER_MAX
    _, b = run(SE_CHANNEL="os", SE_HOSTS=200, SE_MEM_AVAILABLE_MB=1000, SE_FORKS_CAP_OS=100)
    assert b["forks"] == 2
    _, b = run(SE_CHANNEL="os", SE_HOSTS=3, SE_MEM_AVAILABLE_MB=1200)          # (480 − 200)/80 = 3
    assert b["forks"] == 3


def test_memory_guard_refuses_to_start_when_no_fork_fits():
    rc, b = run(SE_CHANNEL="os", SE_HOSTS=10, SE_MEM_AVAILABLE_MB=500)          # (200 − 200)/80 = 0
    assert rc == 0 and b["start"] is False and b["reason"] == "not_started_memory" and b["limit_source"] == "none"
    assert b["forks"] == 0 and b["waves"] == 0 and b["mem_cap"] == 0 and b["mem_guard"] == "active"


def test_memory_guard_unavailable_keeps_the_fixed_cap_and_says_so():
    _, b = run(SE_CHANNEL="os", SE_HOSTS=200, SE_MEM_AVAILABLE_MB="abc")
    assert b["forks"] == 50 and b["mem_guard"] == "unavailable" and b["mem_cap"] is None and b["mem_avail_mb"] is None
    _, b = run(SE_CHANNEL="os", SE_HOSTS=200, SE_MEM_AVAILABLE_MB=1000, SE_PER_FORK_MB=20, SE_FIXED_MB=100, SE_NODE_SHARE_PCT=50)
    assert b["mem_cap"] == (1000 * 50 // 100 - 100) // 20 == 20 and b["forks"] == 20


def test_invalid_inputs_exit_2():
    rc, b = run(SE_CHANNEL="windows")
    assert rc == 2 and b["start"] is False and b["reason"] == "invalid_input"
    rc, _ = run(SE_HOSTS="abc")
    assert rc == 2
    rc, _ = run(SE_HOSTS=0)
    assert rc == 2
