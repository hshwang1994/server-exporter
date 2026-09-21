"""Add-on hook 엔진 테스트 — 실제 ansible-playbook 으로 공통 조립 코드와 hook 을 태운다 (2026-09-21).

왜 필요한가:
    hook 의 약속은 "SE_ADDON_DIR 이 없으면 결과가 hook 도입 전과 같다" 와 "Add-on 이 무엇을 하든
    status · sections · diagnosis · 기존 data 는 바뀌지 않는다" 다. 이는 include_role · role
    filter_plugins · block/rescue · ignore_unreachable 같은 Ansible 실행 동작에 달려 있어 정적
    검사로는 증명되지 않는다. tests/fixtures/addon/harness.yml 이 실제 init_fragments →
    merge_fragment → run_addon.yml → build_* → json_only 콜백을 그대로 태운다.

비교 방식:
    `data` 키 순서는 원래 실행마다 달라진다 (merge_fragment 의 union 이 문자열 hash 에 의존 —
    hook 과 무관한 기존 동작). byte 비교는 PYTHONHASHSEED 를 고정해 같은 조건에서 한다.

실행 조건:
    Linux / WSL 의 ansible-playbook 이 있어야 한다 (없거나 Windows 면 skip). 다른 버전으로 돌리려면
    ANSIBLE_PLAYBOOK_BIN 에 실행 파일 경로를 준다 (운영과 같은 2.20.3 확인용).
    unreachable 시나리오는 192.0.2.1(TEST-NET-1, 라우팅되지 않는 문서용 주소)로 SSH 연결을
    시도해 3초 안에 실패하는 것을 이용한다. 실장비에는 연결하지 않는다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "addon"
# Windows 는 Ansible 제어 노드를 지원하지 않는다 (패키지가 깔려 있어도 CLI 가 시작 단계에서 멈춘다).
PLAYBOOK_BIN = os.environ.get("ANSIBLE_PLAYBOOK_BIN") or (
    None if os.name == "nt" else shutil.which("ansible-playbook"))

if not PLAYBOOK_BIN:
    pytest.skip("ansible-playbook 을 쓸 수 없는 환경 — 엔진 테스트는 Linux / WSL 에서 실행한다",
                allow_module_level=True)

HOSTS = [
    {"service_ip": "192.0.2.10", "physical_purpose": "DB", "note": "{{ 7*7 }}"},
    {"service_ip": "192.0.2.11", "physical_purpose": "APP", "note": "n2"},
]
SCENARIOS = {
    # 이름: (SE_ADDON_DIR, hook 포함 여부)
    "baseline": (None, False),
    "unset": (None, True),
    "missing": ("__missing__", True),
    # 디렉터리는 있지만 tasks/main.yml 이 없다 (Add-on 상위 폴더를 가리킨 실수)
    "no_entry": (FIXTURES, True),
    "empty": (FIXTURES / "empty", True),
    "ok": (FIXTURES / "ok", True),
    # 끝에 '/' 를 붙인 설정 실수 — 그대로 동작해야 한다
    "ok_trailing_slash": (f"{FIXTURES / 'ok'}/", True),
    "bad_config": (FIXTURES / "bad_config", True),
    "fail_runtime": (FIXTURES / "fail_runtime", True),
    "unreachable": (FIXTURES / "unreachable", True),
}


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """시나리오마다 playbook 을 한 번 실행해 결과 줄(raw)과 envelope 목록을 모은다."""
    tmp = tmp_path_factory.mktemp("addon_engine")
    out = {}
    for name, (addon_dir, with_hook) in SCENARIOS.items():
        env = {k: v for k, v in os.environ.items() if k != "SE_ADDON_DIR"}
        result_file = tmp / f"{name}.jsonl"
        env.update({
            "REPO_ROOT": str(REPO),
            "ANSIBLE_CONFIG": str(REPO / "ansible.cfg"),
            "INVENTORY_JSON": json.dumps(HOSTS, ensure_ascii=False),
            "ANSIBLE_JSON_OUTPUT_FILE": str(result_file),
            "PYTHONHASHSEED": "0",
        })
        if addon_dir == "__missing__":
            env["SE_ADDON_DIR"] = str(tmp / "no-such-addon")
        elif addon_dir is not None:
            env["SE_ADDON_DIR"] = str(addon_dir)
        cmd = [PLAYBOOK_BIN, "-i", str(REPO / "os-gather" / "inventory.sh"),
               str(FIXTURES / "harness.yml")]
        if not with_hook:
            cmd += ["-e", "harness_hook=false"]
        proc = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=600)
        assert proc.returncode == 0, f"{name}: rc={proc.returncode}\n{proc.stderr[-3000:]}"
        raw = result_file.read_text(encoding="utf-8")
        envelopes = [json.loads(line) for line in raw.splitlines() if line.strip()]
        out[name] = {"raw": raw, "by_ip": {e["ip"]: e for e in envelopes}, "count": len(envelopes)}
    return out


def _same_except(env: dict, base: dict, *skip: str) -> None:
    for key in base:
        if key not in skip:
            assert env[key] == base[key], f"{key} 가 바뀌었다"
    assert set(env) == set(base), "envelope 최상위 키 구성이 바뀌었다"


def test_every_scenario_yields_one_envelope_per_host(runs):
    for name, run in runs.items():
        assert run["count"] == len(HOSTS), f"{name}: envelope {run['count']}개 (기대 {len(HOSTS)})"
        assert set(run["by_ip"]) == {h["service_ip"] for h in HOSTS}, name


def test_unset_addon_dir_output_is_byte_identical_to_no_hook(runs):
    assert runs["unset"]["raw"] == runs["baseline"]["raw"]


def test_addon_with_nothing_to_add_is_byte_identical_to_no_hook(runs):
    assert runs["empty"]["raw"] == runs["baseline"]["raw"]


@pytest.mark.parametrize("scenario", ["missing", "no_entry"])
def test_missing_addon_dir_adds_exactly_one_addon_error(runs, scenario):
    for ip, env in runs[scenario]["by_ip"].items():
        base = runs["baseline"]["by_ip"][ip]
        _same_except(env, base, "errors")
        assert env["errors"][:-1] == base["errors"]
        added = env["errors"][-1]
        assert added["section"] == "addon"
        assert "SE_ADDON_DIR" not in added["message"] and "/" not in added["message"]
        assert "SE_ADDON_DIR=" in added["detail"] and "cause=addon_entry_not_found" in added["detail"]
        assert "addon" not in env["data"]


def test_trailing_slash_addon_dir_behaves_like_plain_path(runs):
    assert runs["ok_trailing_slash"]["raw"] == runs["ok"]["raw"]


def test_addon_result_lands_only_in_data_addon(runs):
    by_ip = {h["service_ip"]: h for h in HOSTS}
    for ip, env in runs["ok"]["by_ip"].items():
        base = runs["baseline"]["by_ip"][ip]
        _same_except(env, base, "data")
        assert {k: v for k, v in env["data"].items() if k != "addon"} == base["data"]
        assert env["data"]["addon"] == {"fixture": {
            "target": "linux",
            "purpose": by_ip[ip]["physical_purpose"],
            "note": by_ip[ip]["note"],          # "{{ 7*7 }}" 가 해석되지 않고 글자 그대로
            "filter": "fixture:x",              # role filter_plugins 자동 로드
            "text": "line1\nline2\n",
        }}


def test_addon_notes_become_one_error_without_data(runs):
    for ip, env in runs["bad_config"]["by_ip"].items():
        base = runs["baseline"]["by_ip"][ip]
        _same_except(env, base, "errors")
        assert env["errors"][:-1] == base["errors"]
        assert env["errors"][-1]["section"] == "addon"
        assert env["errors"][-1]["detail"] == "config.yml 을 읽지 못했습니다 (fixture)"


def test_addon_runtime_failure_is_isolated(runs):
    for ip, env in runs["fail_runtime"]["by_ip"].items():
        base = runs["baseline"]["by_ip"][ip]
        _same_except(env, base, "errors")      # 실패 전 중간 결과(partial)는 data 에 남지 않는다
        added = env["errors"][-1]
        assert env["errors"][:-1] == base["errors"]
        assert added["section"] == "addon"
        assert "cause=addon_failed" in added["detail"] and "fixture failure" in added["detail"]


def test_connection_lost_during_addon_keeps_the_host(runs):
    for ip, env in runs["unreachable"]["by_ip"].items():
        base = runs["baseline"]["by_ip"][ip]
        _same_except(env, base, "errors", "data")
        assert {k: v for k, v in env["data"].items() if k != "addon"} == base["data"]
        assert env["data"]["addon"] == {"fixture": {"reached": False}}
        assert env["errors"][:-1] == base["errors"]
        assert env["errors"][-1]["detail"] == "remote command not run: target unreachable"
