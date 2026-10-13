"""Linux sudo 프로브 live 매트릭스 (2026-10-13, 계획 8.0 / 3-A) — 실 Linux 대상에서 try_sudo.yml 의 분류를 **결과 모양**으로 다시 확인한다.

버전을 보지 않는다. Ansible 이나 sudo 를 올렸을 때 이 매트릭스를 다시 돌려 분류(통과 / 거부 / 정책 거부 / 불가)와 제출 횟수(후보당 1회)가
그대로인지 본다. 틀린 비밀번호를 실 PAM 에 보내는 경우는 없다 — 거부 · 종료 코드 · 무응답 · 부재는 가짜 sudo(fixture)로, 통과 · 정책 거부 ·
NOPASSWD 는 실 sudo 로 본다.

기본 skip. 활성(환경변수, 비밀번호는 어디에도 쓰지 않고 테스트가 만드는 0600 임시 파일로만 전달한다):
  SE_SUDO_LIVE_HOST / SE_SUDO_LIVE_USER / SE_SUDO_LIVE_PASSWORD        NOPASSWD sudo 계정 (필수)
  SE_SUDO_LIVE_PW_USER / SE_SUDO_LIVE_PW_PASSWORD                      비밀번호를 요구하는 표준 sudoers 계정 (가짜 sudo · 로그인 비밀번호 사례)
  SE_SUDO_LIVE_NOSUDO_USER / SE_SUDO_LIVE_NOSUDO_PASSWORD              sudo 권한이 없는 계정 (정책 거부 사례)
  ANSIBLE_PLAYBOOK_BIN                                                 ansible-playbook 경로 (없으면 PATH)
실행: pytest tests/integration/test_sudo_probe_live.py -m live
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.integration, pytest.mark.live]

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
FIXTURES = REPO / "tests" / "fixtures" / "sudo_live"
PLAYBOOK_BIN = os.environ.get("ANSIBLE_PLAYBOOK_BIN") or (
    None if os.name == "nt" else shutil.which("ansible-playbook"))
HOST = os.environ.get("SE_SUDO_LIVE_HOST", "").strip()

ACCOUNTS = {
    "nopasswd": (os.environ.get("SE_SUDO_LIVE_USER", ""), os.environ.get("SE_SUDO_LIVE_PASSWORD", "")),
    "password": (os.environ.get("SE_SUDO_LIVE_PW_USER", ""), os.environ.get("SE_SUDO_LIVE_PW_PASSWORD", "")),
    "nosudo": (os.environ.get("SE_SUDO_LIVE_NOSUDO_USER", ""), os.environ.get("SE_SUDO_LIVE_NOSUDO_PASSWORD", "")),
}

if not (PLAYBOOK_BIN and HOST and all(ACCOUNTS["nopasswd"])):
    pytest.skip("live sudo 매트릭스 미지정 (SE_SUDO_LIVE_HOST · SE_SUDO_LIVE_USER · SE_SUDO_LIVE_PASSWORD + ansible-playbook)",
                allow_module_level=True)

WRONG = [{"label": "sudo_primary", "role": "primary", "password": "live-wrong-1"},
         {"label": "sudo_fallback1", "role": "secondary", "password": "live-wrong-2"},
         {"label": "sudo_fallback2", "role": "secondary", "password": "live-wrong-3"}]

# 사례: 계정 · Vault 후보 · 가짜 sudo 모드 ('' = 실 sudo, 'absent' = 없는 경로)
CASES = {
    "nopasswd": ("nopasswd", [], ""),
    "login": ("password", [], ""),
    "vault_dup": ("password", [{"label": "sudo_primary", "role": "primary", "password": "__LOGIN__"}], ""),
    "denied": ("nosudo", [], ""),
    "reject": ("password", WRONG, "reject"),
    "rc1": ("password", WRONG[:1], "rc1"),
    "hang": ("password", WRONG[:1], "hang"),
    "absent": ("password", WRONG[:1], "absent"),
}


def _needs(case: str) -> None:
    account = CASES[case][0]
    if not all(ACCOUNTS[account]):
        pytest.skip(f"{case}: 계정 환경변수 미지정 ({account})")


def _write_private(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _run(case: str, tmp: Path) -> dict:
    account, candidates, fake = CASES[case]
    user, password = ACCOUNTS[account]
    hostvars = {"ansible_host": HOST, "ansible_user": user, "ansible_password": password}
    if fake == "absent":
        hostvars["ansible_become_exe"] = "/nonexistent/se_sudo"
    elif fake:
        hostvars["ansible_become_exe"] = f"/tmp/se_fake_sudo_{fake}"
    inventory = tmp / f"{case}.inventory.yml"
    extra = tmp / f"{case}.vars.json"
    result = tmp / f"{case}.result.json"
    _write_private(inventory, yaml.safe_dump({"all": {"hosts": {HOST: hostvars}}}))
    _write_private(extra, json.dumps({
        "harness_candidates": [{**c, "password": (password if c["password"] == "__LOGIN__" else c["password"])}
                               for c in candidates],
        "harness_fake_sudo_mode": fake if fake != "absent" else "",
        "harness_fake_sudo_src": str(FIXTURES / "fake_sudo.sh"),
        "harness_result_file": str(result),
    }))
    env = dict(os.environ)
    env.update({
        "REPO_ROOT": str(REPO),
        "ANSIBLE_CONFIG": str(REPO / "ansible.cfg"),
        # ansible.cfg 는 동적 인벤토리(script · auto)만 켠다 — 이 시험은 임시 YAML 인벤토리를 쓰므로 yaml 플러그인을 더한다
        "ANSIBLE_INVENTORY_ENABLED": "yaml,script,auto",
        "ANSIBLE_JSON_OUTPUT_FILE": str(tmp / f"{case}.output.jsonl"),
        "ANSIBLE_JSON_CHECKPOINT_FILE": str(tmp / f"{case}.checkpoint.jsonl"),
        "ANSIBLE_JSON_PROGRESS_FILE": str(tmp / f"{case}.progress.jsonl"),
    })
    try:
        proc = subprocess.run([PLAYBOOK_BIN, "-i", str(inventory), str(FIXTURES / "harness.yml"), "-e", f"@{extra}"],
                              cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=900)
    finally:
        inventory.unlink(missing_ok=True)
        extra.unlink(missing_ok=True)
    assert proc.returncode == 0, f"{case}: rc={proc.returncode}\n{proc.stderr[-3000:]}\n{proc.stdout[-2000:]}"
    assert result.is_file(), f"{case}: 결과 파일이 없다\n{proc.stdout[-2000:]}"
    data = json.loads(result.read_text(encoding="utf-8"))
    blob = json.dumps(data, ensure_ascii=False)
    for secret in [p for _, p in ACCOUNTS.values() if p] + [c["password"] for c in WRONG]:
        assert secret not in blob, f"{case}: 결과에 비밀번호 문자열이 있다"
    return data


@pytest.fixture(scope="module")
def tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("sudo_live")


@pytest.fixture(scope="module")
def runs(tmp):
    cache: dict[str, dict] = {}

    def get(case: str) -> dict:
        if case not in cache:
            cache[case] = _run(case, tmp)
        return cache[case]

    return get


def _attempt_labels(meta: dict) -> list[str]:
    return [a["label"] for a in meta["attempts"]]


def test_policy_and_budget_are_read_from_the_target(runs):
    data = runs("nopasswd")
    policy = data["policy"]
    assert {"pam_files", "lock_module", "deny", "even_deny_root", "unlock_time", "fail_interval"} <= set(policy)
    assert isinstance(policy["deny"], int) and policy["deny"] >= 1
    assert isinstance(data["max_rejections"], int) and 1 <= data["max_rejections"] <= 3
    assert data["sudo"]["max_rejections"] == data["max_rejections"]
    assert data["sudo"]["policy"] == policy


def test_nopasswd_account_submits_nothing(runs):
    meta = runs("nopasswd")["sudo"]
    assert meta["ok"] is True and meta["mode"] == "nopasswd" and meta["outcome"] == "nopasswd"
    assert meta["attempted_count"] == 0 and meta["rejected_count"] == 0 and meta["attempts"] == []
    assert meta["used_label"] is None and meta["fallback_used"] is False
    assert runs("nopasswd")["become_pass_empty"] is True


def test_login_password_is_tried_first_and_accepted(runs):
    _needs("login")
    meta = runs("login")["sudo"]
    assert meta["ok"] is True and meta["mode"] == "password" and meta["outcome"] == "password_accepted"
    assert meta["used_label"] == "login" and meta["fallback_used"] is False
    assert meta["attempted_count"] == 1 and meta["rejected_count"] == 0
    assert meta["attempts"] == [{"label": "login", "rc": 0, "unreachable": False, "verdict": "ok"}]
    assert runs("login")["become_pass_empty"] is False


def test_vault_candidate_equal_to_login_is_sent_once(runs):
    _needs("vault_dup")
    meta = runs("vault_dup")["sudo"]
    assert meta["ok"] is True and meta["used_label"] == "login"
    assert meta["attempted_count"] == 1 and _attempt_labels(meta) == ["login"]


def test_account_without_sudo_is_policy_denied_after_one_submission(runs):
    _needs("denied")
    data = runs("denied")
    meta = data["sudo"]
    assert meta["ok"] is False and meta["mode"] == "denied" and meta["outcome"] == "policy_denied"
    assert meta["attempted_count"] == 1 and meta["rejected_count"] == 0
    assert meta["attempts"] == [{"label": "login", "rc": 1, "unreachable": False, "verdict": "denied"}]
    assert data["become_pass_empty"] is True


def test_rejected_password_moves_on_and_stops_at_the_budget(runs):
    _needs("reject")
    data = runs("reject")
    meta = data["sudo"]
    budget = data["max_rejections"]
    expected = min(budget, 1 + len(WRONG))          # 로그인 후보 + Vault 3개, 예산 안에서만
    assert meta["ok"] is False and meta["mode"] == "rejected"
    assert meta["attempted_count"] == expected and meta["rejected_count"] == expected
    assert meta["outcome"] == ("budget_exhausted" if expected == budget else "password_rejected")
    assert _attempt_labels(meta) == (["login"] + [c["label"] for c in WRONG])[:expected]
    for attempt in meta["attempts"]:
        assert attempt["rc"] is None and attempt["unreachable"] is False and attempt["verdict"] == "rejected"
    # 가짜 sudo 호출 = 제출 1회/후보, 예산 뒤 호출 0
    assert data["fake_sudo_log"] == ["mode=reject got_password=1"] * expected
    assert data["become_pass_empty"] is True


def test_exit_code_without_retry_sentence_is_treated_as_policy_denial(runs):
    _needs("rc1")
    data = runs("rc1")
    meta = data["sudo"]
    assert meta["ok"] is False and meta["mode"] == "denied" and meta["outcome"] == "policy_denied"
    assert meta["attempted_count"] == 1 and meta["rejected_count"] == 0
    assert meta["attempts"] == [{"label": "login", "rc": 1, "unreachable": False, "verdict": "denied"}]
    assert data["fake_sudo_log"] == ["mode=rc1 got_password=1"]      # Vault 후보는 보내지 않았다


def test_silent_prompt_becomes_unavailable_after_the_escalation_timeout(runs):
    _needs("hang")
    data = runs("hang")
    meta = data["sudo"]
    assert meta["ok"] is False and meta["mode"] == "unavailable" and meta["outcome"] == "prompt_timeout"
    assert meta["attempted_count"] == 1 and meta["rejected_count"] == 0
    assert meta["attempts"] == [{"label": "login", "rc": None, "unreachable": True, "verdict": "unavailable"}]
    assert data["fake_sudo_log"] == ["mode=hang got_password=1"]
    assert data["become_pass_empty"] is True


def test_missing_sudo_binary_is_unavailable(runs):
    _needs("absent")
    data = runs("absent")
    meta = data["sudo"]
    assert meta["ok"] is False and meta["mode"] == "unavailable" and meta["outcome"] == "sudo_absent"
    assert meta["attempted_count"] == 1
    assert meta["attempts"] == [{"label": "login", "rc": 127, "unreachable": False, "verdict": "unavailable"}]
