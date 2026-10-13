"""정상 경로 failed(성공 섹션 0개 — H12) 봉투의 errors[0] 규칙을 실제 ansible-playbook 으로 확인한다 (2026-10-13).

무엇을 고정하나
  - `common/tasks/normalize/build_output.yml` 의 "ensure representative error": status=failed 인데 errors[0].message 가
    diagnosis.failure_reason 과 다르면 대표 오류를 앞에 두고 섹션 오류를 뒤에 보존한다 (완전히 같은 원소만 제외 · 상한 10 · 절단 표시).
  - 채널 표시는 rescue 와 같다 (linux_gather · windows_gather · esxi_gather · redfish_gather).
  - OS 채널은 그 뒤에 require_serial.yml 이 Serial 오류 1건을 덧붙인다 (문장은 유지). partial 대조군은 바뀌지 않는다.
정적 렌더(tests/e2e/test_errors_message_contract.py)와 달리 실제 Templar(jinja2_native) · include 체인 · json_only 콜백을 지난다.
Linux / WSL 의 ansible-playbook 이 있어야 한다 (없거나 Windows 면 skip). ANSIBLE_PLAYBOOK_BIN 으로 실행 파일을 바꿀 수 있다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
FIXTURES = REPO / "tests" / "fixtures" / "no_data"
PLAYBOOK_BIN = os.environ.get("ANSIBLE_PLAYBOOK_BIN") or (
    None if os.name == "nt" else shutil.which("ansible-playbook"))

if not PLAYBOOK_BIN:
    pytest.skip("ansible-playbook 을 쓸 수 없는 환경 — 엔진 테스트는 Linux / WSL 에서 실행한다",
                allow_module_level=True)

HOST = "192.0.2.10"
CASES = ("no_data", "no_errors", "many", "windows", "partial", "esxi", "redfish")
REASONS = yaml.safe_load((REPO / "common" / "vars" / "failure_reasons.yml").read_text(encoding="utf-8"))
NO_DATA = REASONS["_fr_catalog"]["gather_no_data"]["default"]
TRUNCATED = REASONS["_fr_errors_truncated"]
CPU_MESSAGE = "CPU 정보 수집에 실패한 항목이 있습니다. 대상 상태와 수집 로그를 확인하세요."
ENVELOPE_KEYS = {"target_type", "collection_method", "ip", "hostname", "vendor", "status", "sections", "diagnosis",
                 "meta", "correlation", "errors", "data", "schema_version"}


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("no_data_engine")
    out = {}
    for case in CASES:
        result_file = tmp / f"{case}.jsonl"
        env = dict(os.environ)
        env.update({
            "REPO_ROOT": str(REPO),
            "ANSIBLE_CONFIG": str(REPO / "ansible.cfg"),
            "INVENTORY_JSON": json.dumps([{"service_ip": HOST}]),
            "ANSIBLE_JSON_OUTPUT_FILE": str(result_file),
            "ANSIBLE_JSON_CHECKPOINT_FILE": str(tmp / f"{case}.checkpoint.jsonl"),
            "ANSIBLE_JSON_PROGRESS_FILE": str(tmp / f"{case}.progress.jsonl"),
            "PYTHONHASHSEED": "0",
        })
        cmd = [PLAYBOOK_BIN, "-i", str(REPO / "os-gather" / "inventory.sh"), str(FIXTURES / "harness.yml"),
               "-e", f"harness_case={case}"]
        proc = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=600)
        assert proc.returncode == 0, f"{case}: rc={proc.returncode}\n{proc.stderr[-3000:]}\n{proc.stdout[-2000:]}"
        envelopes = [json.loads(line) for line in result_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(envelopes) == 1, f"{case}: envelope {len(envelopes)}개"
        out[case] = envelopes[0]
    return out


def _rep(channel_marker: str) -> dict:
    return {"section": channel_marker, "message": NO_DATA,
            "detail": "success_sections=0; supported=system,cpu; failed=system,cpu"}


def _assert_failed_no_data(env: dict) -> None:
    assert set(env) == ENVELOPE_KEYS
    assert env["status"] == "failed"
    diag = env["diagnosis"]
    assert (diag["failure_stage"], diag["failure_code"], diag["failure_reason"]) == ("gather", "GATHER_FAILED", NO_DATA)
    assert env["sections"]["system"] == "failed" and env["sections"]["cpu"] == "failed"
    for entry in env["errors"]:
        assert isinstance(entry["message"], str) and entry["message"].strip()
        assert entry["detail"] is None or isinstance(entry["detail"], str)


def test_no_data_linux_puts_representative_first_and_keeps_section_errors(runs):
    env = runs["no_data"]
    _assert_failed_no_data(env)
    assert env["errors"][0] == _rep("linux_gather"), env["errors"]
    assert [e["message"] for e in env["errors"][1:3]] == [CPU_MESSAGE, CPU_MESSAGE]
    assert [e["detail"] for e in env["errors"][1:3]] == ["harness error 0", "harness error 1"]
    # OS 채널: require_serial 이 문장을 유지한 채 Serial 오류를 뒤에 붙인다 (시나리오 E 의 H12 경로)
    serial = env["errors"][-1]
    assert serial["section"] == "linux_gather" and serial["message"] == NO_DATA
    assert "field=serial_number" in serial["detail"] and "cause=not_collected" in serial["detail"]
    assert len(env["errors"]) == 4
    assert env["diagnosis"]["details"]["serial_number"] == {"present": False, "cause": "not_collected", "sudo": None}


def test_no_data_without_section_errors_has_only_the_representative(runs):
    env = runs["no_errors"]
    _assert_failed_no_data(env)
    assert env["errors"][0] == _rep("linux_gather")
    assert len(env["errors"]) == 2 and "field=serial_number" in env["errors"][1]["detail"]


def test_many_section_errors_are_capped_with_a_truncation_marker(runs):
    env = runs["many"]
    _assert_failed_no_data(env)
    errors = env["errors"]
    assert errors[0] == _rep("linux_gather")
    assert [e["detail"] for e in errors[1:10]] == [f"harness error {i}" for i in range(9)]
    assert errors[10]["message"] == TRUNCATED and "3건" in errors[10]["detail"]
    assert "field=serial_number" in errors[11]["detail"]
    assert len(errors) == 12


def test_windows_uses_its_channel_marker(runs):
    env = runs["windows"]
    _assert_failed_no_data(env)
    assert env["errors"][0] == _rep("windows_gather")
    assert env["errors"][-1]["section"] == "windows_gather"


@pytest.mark.parametrize("case,marker", [("esxi", "esxi_gather"), ("redfish", "redfish_gather")])
def test_other_channels_get_the_marker_and_no_serial_rule(runs, case, marker):
    env = runs[case]
    _assert_failed_no_data(env)
    assert env["errors"] == [_rep(marker), {"section": "cpu", "message": CPU_MESSAGE, "detail": "harness error 0"}]
    assert "serial_number" not in env["diagnosis"]["details"]


def test_partial_control_is_untouched(runs):
    env = runs["partial"]
    assert set(env) == ENVELOPE_KEYS
    assert env["status"] == "partial"
    diag = env["diagnosis"]
    assert (diag["failure_stage"], diag["failure_code"], diag["failure_reason"]) == (None, None, None)
    assert env["errors"] == [{"section": "cpu", "message": CPU_MESSAGE, "detail": "harness error 0"}]
    assert "serial_number" not in diag["details"]
    assert env["correlation"]["serial_number"] == "HARNESS-SN"
