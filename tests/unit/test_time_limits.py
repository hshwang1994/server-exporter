"""시간 한계 표 — 값이 파일마다 같고, 서로의 합이 맞는지 (2026-10-05, 8차 R3 · R8).

정본 표는 docs/operate/04-pipeline-runtime.md 의 "시간 한계" 절이다. 이 시험은 그 표의 값을 코드에서 읽어 서로 맞는지 본다.
  빌드 12시간 = 입력 확인 5분 + 실행 위치 확인 5분 + 서버 정보 수집 단계 39,000초 + 결과 확인 및 전송 1시간
  실제 수집(ansible-playbook)은 단계 안에서 최대 6시간 — 시작 기준으로 scripts/gather_budget.sh 가 계산하고 scripts/run_gather.sh 가 집행한다
  연결 대기 60초 · 응답 대기(수집 API) 30분 · Portal 응답 대기 시도당 10분 · 오래된 작업 폴더 7일 · 빌드 기록 14일/100개 · 결과 파일 7일/50개
작업(task) 단위 제한이 없다는 것은 tests/unit/test_remote_task_timeouts.py 가, Redfish 요청의 연결 · 응답 대기 분리는
tests/unit/test_redfish_request_timeouts.py 가 본다.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PORTAL = (REPO / "Jenkinsfile_portal").read_text(encoding="utf-8")
BUDGET = (REPO / "scripts" / "gather_budget.sh").read_text(encoding="utf-8")
RUN = (REPO / "scripts" / "run_gather.sh").read_text(encoding="utf-8")


def _constants() -> dict:
    block = PORTAL[PORTAL.index("Map seConstants() {"):PORTAL.index("\n}\n", PORTAL.index("Map seConstants() {"))]
    return {k: int(v) for k, v in re.findall(r"^\s+([A-Z_]+)\s*:\s*(\d+),", block, re.M)}


def _budget(name: str) -> int:
    m = re.search(rf"^{name}=(\d+)\b", BUDGET, re.M)
    assert m, name
    return int(m.group(1))


C = _constants()


def test_constants_table_is_complete():
    assert C == {"BUILD": 43200, "PRE": 600, "STAGE": 39000, "FINALIZER": 3600, "GATHER_MAX": 21600, "PORTAL_WAIT": 600,
                 "PORTAL_MIN": 30, "PORTAL_ATTEMPTS": 3, "KEEP_DAYS": 7}


def test_build_is_the_sum_of_its_parts_and_the_pipeline_options_use_the_same_values():
    assert C["BUILD"] == C["PRE"] + C["STAGE"] + C["FINALIZER"], "빌드 = 입력 확인 · 실행 위치 확인 + 수집 단계 + 결과 확인 및 전송"
    opts = PORTAL[PORTAL.index("\n    options {"):PORTAL.index("\n    stages {")]
    m = re.search(r"timeout\(time: (\d+), unit: 'HOURS'\)", opts)
    assert m and int(m.group(1)) * 3600 == C["BUILD"]
    pre = re.findall(r"options \{ timeout\(time: (\d+), unit: 'MINUTES'\) \}", PORTAL)
    assert len(pre) == 2 and sum(int(x) * 60 for x in pre) == C["PRE"], "입력 확인 · 실행 위치 확인 각 5분"
    m = re.search(r"options \{ timeout\(time: (\d+), unit: 'SECONDS'\) \}", PORTAL)
    assert m and int(m.group(1)) == C["STAGE"], "서버 정보 수집 단계"


def test_gather_budget_uses_the_same_limits_and_leaves_room_for_preserve():
    for name, key in (("BUILD_SEC", "BUILD"), ("PRE_SEC", "PRE"), ("FINALIZER_SEC", "FINALIZER"), ("STAGE_SEC", "STAGE"), ("GATHER_MAX_SEC", "GATHER_MAX")):
        assert _budget(name) == C[key], name
    grace, post = _budget("GRACE_SEC"), _budget("AGENT_POST_SEC")
    # 6시간 수집 + INT 뒤 정리 + 결과 정리 · 보존 몫이 단계 안에 들어가고, 남는 시간이 Runner 대기 · 준비에 쓰인다
    assert C["GATHER_MAX"] + grace + post < C["STAGE"]
    assert C["STAGE"] - C["GATHER_MAX"] - grace - post >= 3 * 3600, "Runner 대기 · checkout · Add-on 준비에 3시간 이상"
    assert re.search(rf'timeout --signal=INT --kill-after={grace} "\$LIMIT"', RUN), "INT 뒤 정리 시간 = gather_budget GRACE_SEC"
    assert "SE_FORCE_SEC" not in BUDGET.split("set -u", 1)[-1] and "SE_FORCE_SEC" not in RUN


def test_finalizer_limit_and_portal_waits():
    assert "long limit = Math.max(60L, Math.min((long) C.FINALIZER, buildStart + (long) C.BUILD - tPost - 60L))" in PORTAL
    assert "timeout(time: limit, unit: 'SECONDS') {" in PORTAL and "node('built-in')" in PORTAL
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
    assert "--build-limit-sec ${C.BUILD} --keep-days ${C.KEEP_DAYS} --every-sec 86400" in PORTAL, "작업 폴더 정리: 하루 한 번, 7일 지난 끝난 폴더"
    assert int(m.group(3)) == C["KEEP_DAYS"], "결과 파일 보관 기간 = 남은 작업 폴더 정리 기간"
