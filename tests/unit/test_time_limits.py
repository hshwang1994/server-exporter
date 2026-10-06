"""시간 한계 표 — 값이 파일마다 같고, 기다린 시간과 실행 시간을 따로 세는지 (2026-10-05 8차 R3 · R8, 2026-10-06 9차 개정).

정본 표는 docs/operate/04-pipeline-runtime.md 의 "시간 한계" 절이다. 이 시험은 그 표의 값을 코드에서 읽어 서로 맞는지 본다.
  빌드 전체 · 서버 정보 수집 단계의 timeout 은 없다(9차) — Runner · 결과 처리 노드를 최대 72시간 기다리는 동안 빌드를 끊지 않는다.
  실행 기반 대기 합 72시간(빌드 하나, 다시 시도해도 처음부터 세지 않는다) · 실제 수집 누적 6시간(scripts/gather_state.py 가 시도마다 남은 한계를 정하고
  scripts/run_gather.sh 가 집행) · 시도 하나의 실행 한계(6시간 + INT 뒤 정리 90초 + 준비 · 보존 몫, node 를 얻은 뒤) · 결과 확인 및 전송 1시간(노드를 얻은 뒤)
  연결 대기 60초 · 응답 대기(수집 API) 30분 · Portal 응답 대기 시도당 10분 · 오래된 작업 폴더 7일 · 빌드 기록 14일/100개 · 결과 파일 7일/50개
기다린 시간을 실행 시간에서 빼는 동작과 보수적인 실행 시간 계산은 tests/unit/test_gather_state.py 가 가짜 시계로 본다.
작업(task) 단위 제한이 없다는 것은 tests/unit/test_remote_task_timeouts.py 가, Redfish 요청의 연결 · 응답 대기 분리는
tests/unit/test_redfish_request_timeouts.py 가 본다.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PORTAL = (REPO / "Jenkinsfile_portal").read_text(encoding="utf-8")
RUN = (REPO / "scripts" / "run_gather.sh").read_text(encoding="utf-8")
STATE = (REPO / "scripts" / "gather_state.py").read_text(encoding="utf-8")
CLEANUP = (REPO / "scripts" / "workspace_cleanup.py").read_text(encoding="utf-8")


def _constants() -> dict:
    block = PORTAL[PORTAL.index("Map seConstants() {"):PORTAL.index("\n}\n", PORTAL.index("Map seConstants() {"))]
    return {k: int(v) for k, v in re.findall(r"^\s+([A-Z_]+)\s*:\s*(\d+),", block, re.M)}


C = _constants()


def test_constants_table_is_complete():
    assert C == {"INFRA_WAIT": 259200, "GATHER_MAX": 21600, "KILL_AFTER": 90, "ATTEMPT_MARGIN": 7200,
                 "FINALIZER": 3600, "ABORT_NODE_WAIT": 300, "BACKOFF_MAX": 3600, "MAX_BUILD": 295200, "PORTAL_WAIT": 600,
                 "PORTAL_MIN": 30, "PORTAL_ATTEMPTS": 3, "KEEP_DAYS": 7}


def test_no_build_or_stage_timeout_waiting_is_not_execution():
    opts = PORTAL[PORTAL.index("\n    options {"):PORTAL.index("\n    stages {")]
    assert "timeout(" not in opts, "빌드 전체 timeout 이 있으면 72시간 대기가 끊긴다"
    pre = re.findall(r"options \{ timeout\(time: (\d+), unit: 'MINUTES'\) \}", PORTAL)
    assert pre == ["5", "5"], "입력 확인 · 실행 위치 확인 각 5분 — 실행 기반 대기가 아니라 입력 · 저장소 확인"
    assert "unit: 'SECONDS') }" not in PORTAL, "서버 정보 수집 단계 한계(종전 39000초)는 없다"
    assert "unit: 'HOURS'" not in PORTAL


def test_execution_limits_start_only_after_a_node_is_acquired():
    attempt = PORTAL[PORTAL.index("def seAttempt(Map C, Map st, Map r) {"):]
    attempt = attempt[: attempt.index("\n}\n")]
    i_ws = attempt.index('ws("${env.JOB_BASE_NAME}-${env.BUILD_NUMBER}") {')
    i_t0 = attempt.index("long t0 = seNowMs()")
    i_to = attempt.index("timeout(time: limitSec, unit: 'SECONDS') {")
    assert i_ws < i_t0 < i_to, "시도 하나의 실행 한계는 node · 작업 폴더를 얻은 뒤에만 센다"
    assert "long limitSec = (C.GATHER_MAX as long) + (C.KILL_AFTER as long) + (C.ATTEMPT_MARGIN as long)" in attempt
    fin = PORTAL[PORTAL.index("def seFinalizeAndCallback() {"):]
    fin = fin[: fin.index("\n}\n")]
    # 10차 R1: 결과 확인 1시간은 노드를 얻은 뒤부터, 재진입해도 처음부터 세지 않는다 — 진입마다 노드를 얻은 때부터 끝(또는 오류 감지)까지 더한다
    assert "long leftMs = (C.FINALIZER as long) * 1000L - (fs.exec_ms as long)" in fin
    assert fin.index("seWithNode('built-in'") < fin.index("timeout(time: Math.max(1L, (long) (leftMs / 1000L)), unit: 'SECONDS') {"), "결과 확인 한계는 노드를 얻은 뒤"
    assert "fs.exec_ms = (fs.exec_ms as long) + Math.max(0L, seNowMs() - tInMs)" in fin and "} finally {" in fin
    assert "fs.abort_wait_ms" in fin and "(C.ABORT_NODE_WAIT as long) * 1000L - (fs.abort_wait_ms as long)" in fin, "취소된 빌드의 노드 대기 5분은 재진입마다 새로 주지 않는다"
    assert "OFFLINE_GRACE" not in PORTAL, "끊김 대기를 Jenkins 처리 유예(5분)로 앞당겨 세지 않는다 — 확인된 감지 시각부터 센다"


def test_gather_limit_is_accumulated_real_execution():
    assert re.search(rf'timeout --signal=INT --kill-after={C["KILL_AFTER"]} "\$LIMIT"', RUN), "INT 뒤 정리 시간 = KILL_AFTER"
    assert "limit = max(0, int(gather_max) - used)" in STATE, "이번 시도의 한계 = 6시간 − 누적 실제 수집 시간"
    assert "ALIVE_INTERVAL_SEC = 60" in STATE and "sleep 60" in RUN, "생존 표시 주기 = 보수적 계산의 더하는 몫"
    for gone in ("MemAvailable", "meminfo", "SE_MEM_AVAILABLE_MB", "SE_PER_FORK_MB", "SE_NODE_SHARE_PCT", "SE_FIXED_MB", "mem_cap", "MEM_REFUSED"):
        assert gone not in RUN and gone not in STATE and gone not in PORTAL, gone
    assert not (REPO / "scripts" / "gather_budget.sh").exists(), "메모리 · 남은 빌드 시간으로 시작을 막던 계산은 없다"


def test_infra_wait_is_one_budget_per_build():
    load = PORTAL[PORTAL.index("def seInfraLoad(Map C) {"):]
    load = load[: load.index("\n}\n")]
    assert "env.SE_INFRA_JSON" in load and "return seInfraNew(C.INFRA_WAIT as long)" in load
    assert PORTAL.count("seInfraNew(") == 2, "정의 하나 · 처음 만들 때 하나 — 다시 시도 · 재개 · 결과 처리 노드 대기가 같은 기록을 이어 쓴다"
    assert "Map infra = seInfraLoad(C)" in PORTAL[PORTAL.index("def seGatherStage(Map C) {"):PORTAL.index("def seGatherLoop(")]
    assert "Map infra = seInfraLoad(C)" in PORTAL[PORTAL.index("def seFinalizeAndCallback() {"):PORTAL.index("def seFinalizeIn(")]


def test_finalizer_limit_and_portal_waits():
    assert "int t = (int) Math.min((long) C.PORTAL_WAIT, left - 10L)" in PORTAL, "시도당 응답 대기 10분(남은 시간 안에서)"
    assert "if (left < (C.PORTAL_MIN as long))" in PORTAL
    assert "int maxAttempts = aborted ? 1 : (C.PORTAL_ATTEMPTS as int)" in PORTAL
    # 최악의 전송(3번 × 10분 + 대기 10 · 20초)이 결과 확인 및 전송 1시간 안에 들어간다
    assert C["PORTAL_ATTEMPTS"] * C["PORTAL_WAIT"] + 10 + 20 < C["FINALIZER"]


def test_connection_and_response_waits():
    os_site = (REPO / "os-gather" / "site.yml").read_text(encoding="utf-8")
    assert re.search(r"^\s+ansible_timeout:\s+60$", os_site, re.M) and "-o ConnectTimeout=60" in os_site, "SSH 연결 60초"
    assert "_probe_timeout: \"{{ probe_timeout | default(10) }}\"" in os_site, "OS 후보 포트 탐색 연결 10초(DROP 방화벽 · 3회 SYN 재시도 허용)"
    assert "_precheck_timeout_protocol: \"{{ _probe_protocol_timeout | default(60) }}\"" in os_site
    assert re.search(r"^\s+gather_timeout: 1800$", os_site, re.M), "Windows setup 사실 수집기 대기 30분"
    assert re.search(r"^\s+ansible_winrm_operation_timeout_sec:\s+60$", os_site, re.M), "WinRM 통신 규약 값은 유지"
    pre = (REPO / "common" / "tasks" / "precheck" / "run_precheck.yml").read_text(encoding="utf-8")
    assert "timeout_port: \"{{ _precheck_timeout_port | default(60) }}\"" in pre
    rf_site = (REPO / "redfish-gather" / "site.yml").read_text(encoding="utf-8")
    assert re.search(r"^\s+_rf_timeout: 1800\b", rf_site, re.M), "Redfish 응답 대기 30분"
    assert re.search(r"^CONNECT_TIMEOUT_SEC = 60$", (REPO / "redfish-gather" / "library" / "redfish_gather.py").read_text(encoding="utf-8"), re.M)
    esxi_site = (REPO / "esxi-gather" / "site.yml").read_text(encoding="utf-8")
    assert re.search(r"^\s+_precheck_timeout: 1800$", esxi_site, re.M)
    assert re.search(r"^_DEFAULT_TIMEOUT_SEC = 1800\b", (REPO / "esxi-gather" / "library" / "esxi_disks.py").read_text(encoding="utf-8"), re.M)
    addon = (REPO / "scripts" / "addon_checkout.sh").read_text(encoding="utf-8")
    assert "tmo=(timeout 1800)" in addon, "Add-on 받기 준비 30분"


def test_retention_and_cleanup_values():
    m = re.search(r"buildDiscarder\(logRotator\(daysToKeepStr: '(\d+)', numToKeepStr: '(\d+)', artifactDaysToKeepStr: '(\d+)', artifactNumToKeepStr: '(\d+)'\)\)", PORTAL)
    assert m and m.groups() == ("14", "100", "7", "50"), "빌드 기록 14일 · 100개, 결과 파일 7일 · 50개"
    assert "--build-limit-sec ${C.MAX_BUILD} --keep-days ${C.KEEP_DAYS} --every-sec 86400" in PORTAL, "작업 폴더 정리: 하루 한 번, 7일 지난 끝난 폴더"
    assert int(m.group(3)) == C["KEEP_DAYS"], "결과 파일 보관 기간 = 남은 작업 폴더 정리 기간"
    assert C["MAX_BUILD"] == C["INFRA_WAIT"] + C["GATHER_MAX"] + C["FINALIZER"] + 3 * 3600, "끝 기록 없는 폴더를 실행 중으로 보는 기간"
    m = re.search(r'"--build-limit-sec", type=int, default=(\d+)', CLEANUP)
    assert m and int(m.group(1)) == C["MAX_BUILD"]
