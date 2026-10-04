"""scripts/gather_budget.sh — 수집 배치 예산 공식 (2026-10-03, Plan §6-2 + Astra 3차 §1).

고정하는 것
  - gather = clamp(BASE + host_cap × waves, MIN, CAP); waves = ceil(H / forks); forks 는 채널·vCPU 로.
  - 집행 예산 = min(gather, force?, HARD_DEADLINE − now − RESERVE, STAGE_LIMIT − (now − stage_start) − GRACE − POST):
    stage_start 는 Resolve Location 끝(agent 를 얻기 전)이라 agent 대기·checkout·Add-on 준비가 길어지면 gather 가 줄고 reserve 는 줄지 않는다.
    예상값이 충분했어도 재계산 결과가 기준. (R6, 2026-10-03)
  - budget < MIN_START → start=false (not_started_budget). 강제값은 남은 시간을 넘지 못한다. 입력 불량은 rc 2.
  - 메모리 보호(P-1): mem_cap = floor((MemAvailable × share − fixed) / per_fork); forks = min(forks, mem_cap); mem_cap ≤ 0 → not_started_memory;
    MemAvailable 을 못 읽으면 mem_guard=unavailable 로 기존 상한. 테스트는 SE_MEM_AVAILABLE_MB 를 명시해 결정적으로 돈다.
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


def run(**env):
    base = {"SE_NOW_EPOCH": str(T0), "SE_BUILD_START_EPOCH": str(T0), "SE_STAGE_START_EPOCH": str(T0),
            "SE_CHANNEL": "os", "SE_HOSTS": "3", "SE_VCPU": "8",
            "SE_MEM_AVAILABLE_MB": "16000"}   # (16000×0.4 − 200)/80 = 77 ≥ OS 상한 50 → 메모리 보호가 forks 를 바꾸지 않는 기준 환경
    base.update({k: str(v) for k, v in env.items()})
    e = dict(os.environ)
    e.pop("SE_FORCE_SEC", None)
    e.update(base)
    r = subprocess.run([BASH, str(SCRIPT)], env=e, capture_output=True, text=True)
    return r.returncode, json.loads(r.stdout.strip()) if r.stdout.strip() else None


def test_small_os_batch_uses_min_and_starts():
    rc, b = run()
    assert rc == 0 and b["start"] is True and b["reason"] == "computed"
    assert b["forks"] == 3 and b["waves"] == 1 and b["host_cap"] == 240
    assert b["gather"] == 600, "BASE 300 + 240 = 540 < MIN 600"
    assert b["budget"] == 600


def test_os_forks_default_cap_50_and_runner_env_override():
    """OS 기본 상한 50 유지. 2026-10-04 Runner 실측(GP-18): slot 최악치 PSS 69 MB(Windows worker) → per_fork_mb 80, 13 host 트리 peak 463 MB."""
    _, b = run(SE_CHANNEL="os", SE_HOSTS=200)
    assert b["forks"] == 50 and b["waves"] == 4 and b["gather"] == 300 + 240 * 4
    _, b = run(SE_CHANNEL="os", SE_HOSTS=200, SE_FORKS_CAP_OS=100, SE_MEM_AVAILABLE_MB=40000)   # (16000−200)/80 = 197 ≥ 100
    assert b["forks"] == 100 and b["waves"] == 2, "Runner 노드 env 로 상향 (메모리 여유가 있을 때만 — P-1)"
    _, b = run(SE_CHANNEL="os", SE_HOSTS=200, SE_FORKS_CAP_OS=100)
    assert b["forks"] == 77, "기준 환경(16000 MB)에서는 메모리 보호 mem_cap=77 이 노드 env 상향을 자른다"
    _, b = run(SE_CHANNEL="os", SE_HOSTS=200, SE_FORKS_CAP_OS="abc")
    assert b["forks"] == 50, "잘못된 값은 기본 상한"
    _, b = run(SE_CHANNEL="os", SE_HOSTS=30, SE_FORKS_CAP_OS=100)
    assert b["forks"] == 30, "host 수가 상한보다 작으면 host 수"


def test_redfish_large_batch_formula():
    rc, b = run(SE_CHANNEL="redfish", SE_HOSTS=200, SE_VCPU=8)
    assert b["forks"] == 32 and b["waves"] == 7 and b["host_cap"] == 605
    assert b["gather"] == 300 + 605 * 7 == 4535 and b["budget"] == 4535
    rc, b2 = run(SE_CHANNEL="redfish", SE_HOSTS=200, SE_VCPU=8, SE_REDFISH_CANDIDATES=2, SE_REDFISH_RECOVERY=1)
    assert b2["host_cap"] == 2 * 605 + 240 and b2["gather"] == 5400, "CAP 에서 잘린다"


def test_esxi_forks_scale_with_vcpu():
    _, b = run(SE_CHANNEL="esxi", SE_HOSTS=50, SE_VCPU=4)
    assert b["forks"] == 8 and b["waves"] == 7


def test_late_node_entry_shrinks_budget_but_not_reserve():
    # 빌드 시작 후 140 분이 지나 node 에 들어왔다: HARD_DEADLINE(150 min) − now − RESERVE(990) = 600 − 990 < 0 → 시작하지 않는다.
    _, b = run(SE_NOW_EPOCH=T0 + 140 * 60, SE_STAGE_START_EPOCH=T0 + 139 * 60, SE_CHANNEL="redfish", SE_HOSTS=4)
    assert b["start"] is False and b["reason"] == "not_started_budget" and b["budget"] == 0
    # 100 분 경과: 남은 3000 − 990 = 2010 → gather(905) 그대로
    _, b = run(SE_NOW_EPOCH=T0 + 100 * 60, SE_STAGE_START_EPOCH=T0 + 99 * 60, SE_CHANNEL="redfish", SE_HOSTS=4)
    assert b["gather"] == 905 and b["budget"] == 905 and b["hard_remaining"] == 2010
    # 125 분 경과: 남은 1500 − 990 = 510 → budget 510 (gather 보다 작다), reserve 침범 없음
    _, b = run(SE_NOW_EPOCH=T0 + 125 * 60, SE_STAGE_START_EPOCH=T0 + 124 * 60, SE_CHANNEL="redfish", SE_HOSTS=4)
    assert b["budget"] == 510 and b["start"] is True


def test_agent_wait_is_charged_to_stage_budget():
    """R6 (2026-10-03 Astra 2·3차): stage_start 는 Resolve Location 끝이다 — 240 s 는 빌드 시작→stage 기준점(Validate+Resolve)의 pre 구간이지
    agent 대기가 아니다. agent 대기는 stage_start 이후에 쌓이므로 now 와의 차이로 stage 잔여에서 그대로 차감된다.
    산식: stage_remaining = stage_start + 6900 − now − 90 − 180, start=false ⇔ budget < 120."""
    stage_start = T0 + 240
    _, b = run(SE_NOW_EPOCH=stage_start + 5700, SE_STAGE_START_EPOCH=stage_start, SE_CHANNEL="os", SE_HOSTS=200)
    assert b["stage_remaining"] == 930 and b["start"] is True and b["budget"] == 930
    _, b = run(SE_NOW_EPOCH=stage_start + 6510, SE_STAGE_START_EPOCH=stage_start, SE_CHANNEL="os", SE_HOSTS=200)
    assert b["stage_remaining"] == 120 and b["start"] is True, "경계: 정확히 MIN_START 면 시작한다"
    _, b = run(SE_NOW_EPOCH=stage_start + 6511, SE_STAGE_START_EPOCH=stage_start, SE_CHANNEL="os", SE_HOSTS=200)
    assert b["stage_remaining"] == 119 and b["start"] is False and b["reason"] == "not_started_budget"
    _, b = run(SE_NOW_EPOCH=stage_start + 6600, SE_STAGE_START_EPOCH=stage_start, SE_CHANNEL="os", SE_HOSTS=200)
    assert b["stage_remaining"] == 30 and b["start"] is False
    assert b["hard_remaining"] == 9000 - (240 + 6600) - 990 == 1170, "hard 가 아니라 stage 가 구속한다"


def test_memory_guard_caps_forks_and_the_budget_grows_with_waves():
    """P-1: 가용 1000 MB → mem_cap = (400 − 200)/80 = 2 → OS 200 host 가 2 forks · 100 waves 로 늘고 gather 는 CAP 에 막힌다."""
    _, b = run(SE_CHANNEL="os", SE_HOSTS=200, SE_MEM_AVAILABLE_MB=1000)
    assert b["mem_guard"] == "active" and b["mem_avail_mb"] == 1000 and b["mem_cap"] == 2
    assert b["forks"] == 2 and b["waves"] == 100
    assert b["gather"] == 5400, "300 + 240×100 = 24300 → CAP 5400 (용량표의 근거)"
    _, b = run(SE_CHANNEL="os", SE_HOSTS=200, SE_MEM_AVAILABLE_MB=1000, SE_FORKS_CAP_OS=100)
    assert b["forks"] == 2, "노드 env 상한은 메모리 보호를 넘지 못한다 (상한으로만)"
    _, b = run(SE_CHANNEL="os", SE_HOSTS=3, SE_MEM_AVAILABLE_MB=1200)   # mem_cap = (480 − 200)/80 = 3
    assert b["forks"] == 3, "host 수가 더 작으면 host 수"


def test_memory_guard_refuses_to_start_when_no_fork_fits():
    rc, b = run(SE_CHANNEL="os", SE_HOSTS=10, SE_MEM_AVAILABLE_MB=500)   # (200 − 200)/80 = 0
    assert rc == 0 and b["start"] is False and b["reason"] == "not_started_memory"
    assert b["forks"] == 0 and b["waves"] == 0 and b["budget"] == 0 and b["mem_cap"] == 0 and b["mem_guard"] == "active"
    assert b["constants"]["per_fork_mb"] == 80 and b["constants"]["fixed_mb"] == 200 and b["constants"]["node_share_pct"] == 40


def test_memory_guard_unavailable_keeps_the_fixed_cap_and_says_so():
    _, b = run(SE_CHANNEL="os", SE_HOSTS=200, SE_MEM_AVAILABLE_MB="abc")
    assert b["forks"] == 50 and b["mem_guard"] == "unavailable" and b["mem_cap"] is None and b["mem_avail_mb"] is None
    _, b = run(SE_CHANNEL="os", SE_HOSTS=200, SE_MEM_AVAILABLE_MB=1000, SE_PER_FORK_MB=20, SE_FIXED_MB=100, SE_NODE_SHARE_PCT=50)
    assert b["mem_cap"] == (1000 * 50 // 100 - 100) // 20 == 20 and b["forks"] == 20, "실측 뒤 override 로 보정한다"


def test_slow_checkout_and_addon_after_long_wait_consume_stage_budget():
    """Astra 3차 §1: 긴 agent 대기 뒤 checkout/Add-on 도 지연 — stage 합산 상한에서 GRACE·POST 를 뺀 값이 집행 예산을 자른다."""
    stage_start = T0 + 10 * 60                     # Validate+Resolve 10 분 뒤 stage 기준점(Resolve Location 끝)
    now = stage_start + 100 * 60                   # agent 대기·checkout·준비에 100 분 (극단)
    _, b = run(SE_NOW_EPOCH=now, SE_STAGE_START_EPOCH=stage_start, SE_CHANNEL="os", SE_HOSTS=200)
    assert b["gather"] == 1260, "os 200 host: 300 + 240×4 (forks 상한 50 → 4 waves, 2026-10-03 Phase 5)"
    assert b["stage_remaining"] == 6900 - 100 * 60 - 90 - 180 == 630
    assert b["budget"] == 630 < b["gather"]
    # 준비가 더 길어져 stage 잔여가 MIN_START 아래로 → 시작하지 않는다
    _, b = run(SE_NOW_EPOCH=stage_start + 112 * 60, SE_STAGE_START_EPOCH=stage_start, SE_CHANNEL="os", SE_HOSTS=200)
    assert b["start"] is False


def test_force_replaces_gather_but_never_exceeds_remaining():
    _, b = run(SE_FORCE_SEC=120)
    assert b["reason"] == "forced" and b["budget"] == 120 and b["start"] is True
    _, b = run(SE_FORCE_SEC=99999)
    assert b["budget"] == min(b["hard_remaining"], b["stage_remaining"]) and b["budget"] < 99999
    _, b = run(SE_FORCE_SEC=60)
    assert b["start"] is False, "MIN_START 120 아래의 강제값도 수집을 시작하지 않는다"


def test_invalid_inputs_exit_2():
    rc, b = run(SE_CHANNEL="windows")
    assert rc == 2 and b["start"] is False and b["reason"] == "invalid_input"
    rc, _ = run(SE_HOSTS="abc")
    assert rc == 2
    rc, _ = run(SE_FORCE_SEC="12s")
    assert rc == 2


def test_constants_match_plan():
    _, b = run()
    c = b["constants"]
    assert c == {"global": 9000, "reserve": 990, "stage_limit": 6900, "grace": 90, "post": 180,
                 "base": 300, "min": 600, "cap": 5400, "min_start": 120,
                 "per_fork_mb": 80, "node_share_pct": 40, "fixed_mb": 200}
    assert c["reserve"] == 90 + 120 + 60 + 720, "GRACE + LAYER_A + ARCHIVE_STASH + FINALIZER_TOTAL"
    assert c["stage_limit"] <= c["global"] - 4 * 60 - 720, "Validate·Resolve 4 min + finalizer 720 s 가 150 min 안에 든다"
