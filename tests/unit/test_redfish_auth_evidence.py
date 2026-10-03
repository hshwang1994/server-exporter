"""redfish_gather — attempt 단위 인증 증거 파일 (Plan §6-3 D7 · Astra 3차 acceptance, 2026-10-03).

고정하는 것:
    - attempt 인자가 없거나 evidence_dir/id 가 비면 파일을 만들지 않는다 (Jenkins 밖 실행 · 종전 호출 호환).
    - 시도 시작 즉시 `<dir>/<ip>/<id>.json` 을 status null 로 **새로** 만든다 (같은 이름의 이전 파일을 덮어쓴다 — stale 401 이 남지 않는다).
    - 자격을 실은 첫 응답에서 first_auth_status 를 채우고 그 뒤 덮어쓰지 않는다 (A 401 뒤 B 200 은 B 의 파일에만 200).
    - auth_mode 는 username 유무로 credentialed / anonymous 를 구분한다 — 익명 200 은 인증 성공이 아니다 (filter 가 credentialed=False).
    - 쓰기는 원자적(os.replace), 요청마다 쓰지 않고 5초 throttle, 마지막 요청 경로만 남긴다.
    - 파일에 비밀값(password · Authorization)이 없다.
    - filter_plugins/auth_evidence.py 가 식별자 불일치 · 손상 · 부재를 전부 "증거 없음" 으로 돌려준다 (예외 없음).
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

_stub_basic = types.ModuleType("ansible.module_utils.basic")
_stub_basic.AnsibleModule = object
_stub_module_utils = types.ModuleType("ansible.module_utils")
_stub_module_utils.basic = _stub_basic
_stub_ansible = types.ModuleType("ansible")
_stub_ansible.module_utils = _stub_module_utils
sys.modules.setdefault("ansible", _stub_ansible)
sys.modules.setdefault("ansible.module_utils", _stub_module_utils)
sys.modules.setdefault("ansible.module_utils.basic", _stub_basic)

import redfish_gather as rg  # noqa: E402

_spec = importlib.util.spec_from_file_location("auth_evidence_filter", REPO / "filter_plugins" / "auth_evidence.py")
_filt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_filt)
parse_auth_evidence = _filt.parse_auth_evidence

SECRET = "Goodmit-not-a-real-secret-9x"
IP = "192.0.2.50"


def _attempt(tmp_path, att_id="collect-1-1", **over):
    base = {"evidence_dir": str(tmp_path / "ev"), "id": att_id, "build_id": "jenkins-x-7",
            "event_uuid": "e-1", "label": "standard-primary", "role": "primary"}
    base.update(over)
    return base


def _read(tmp_path, att_id="collect-1-1"):
    return json.loads((tmp_path / "ev" / IP / f"{att_id}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _reset():
    rg._evidence_reset()
    rg._reset_auth_observation()
    yield
    rg._evidence_reset()
    rg._reset_auth_observation()


def test_no_attempt_argument_writes_nothing(tmp_path):
    for attempt in (None, {}, {"evidence_dir": "", "id": "x"}, {"evidence_dir": str(tmp_path), "id": ""}):
        rg._evidence_begin(attempt, IP, "user")
        rg._evidence_request("Systems")
        rg._record_auth_status(200)
        assert rg.evidence_state()["path"] is None
    assert not list(tmp_path.iterdir())


def test_begin_creates_fresh_file_with_null_status_and_overwrites_previous(tmp_path):
    rg._evidence_begin(_attempt(tmp_path), IP, "user")
    rg._record_auth_status(401)
    assert _read(tmp_path)["first_auth_status"] == 401
    # 같은 attempt id 로 다시 시작 → 이전 401 이 사라진 새 파일 (stale 401 금지)
    rg._evidence_begin(_attempt(tmp_path), IP, "user")
    data = _read(tmp_path)
    assert data["first_auth_status"] is None and data["first_auth_at"] is None
    assert data["schema"] == 1 and data["attempt_id"] == "collect-1-1" and data["ip"] == IP
    assert data["build_id"] == "jenkins-x-7" and data["event_uuid"] == "e-1"
    assert data["label"] == "standard-primary" and data["role"] == "primary"
    assert data["auth_mode"] == "credentialed" and data["requests_sent"] == 0 and data["last_request"] is None
    assert set(data) == {"schema", "build_id", "event_uuid", "ip", "attempt_id", "label", "role", "auth_mode",
                         "first_auth_status", "first_auth_at", "started_at", "updated_at", "requests_sent", "last_request"}


def test_first_credentialed_status_is_recorded_once(tmp_path):
    rg._evidence_begin(_attempt(tmp_path), IP, "user")
    rg._record_auth_status(200)
    rg._record_auth_status(401)      # 하위 리소스의 401 은 첫 관측을 덮지 않는다
    data = _read(tmp_path)
    assert data["first_auth_status"] == 200 and data["first_auth_at"]
    assert rg.auth_evidence() == {"first_auth_status": 200}


def test_status_zero_or_non_int_is_not_evidence(tmp_path):
    rg._evidence_begin(_attempt(tmp_path), IP, "user")
    rg._record_auth_status(0)
    rg._record_auth_status(None)
    rg._record_auth_status("401")
    assert _read(tmp_path)["first_auth_status"] is None


def test_anonymous_attempt_is_marked_and_filter_refuses_it_as_auth_proof(tmp_path):
    rg._evidence_begin(_attempt(tmp_path, "anonymous-0-1", label="no-credential", role="anonymous"), IP, "")
    rg._record_auth_status(200)
    data = _read(tmp_path, "anonymous-0-1")
    assert data["auth_mode"] == "anonymous" and data["first_auth_status"] == 200
    ev = parse_auth_evidence(json.dumps(data), {"build_id": "jenkins-x-7", "event_uuid": "e-1", "ip": IP, "attempt_id": "anonymous-0-1"})
    assert ev["valid"] is True and ev["credentialed"] is False, "익명 200 은 그 자격의 인증 성공이 아니다"


def test_requests_are_counted_and_last_path_kept_with_throttle(tmp_path, monkeypatch):
    rg._evidence_begin(_attempt(tmp_path), IP, "user")
    clock = {"t": 1000.0}
    monkeypatch.setattr(rg.time, "monotonic", lambda: clock["t"])
    rg._EVIDENCE["last_write"] = clock["t"]
    rg._evidence_request("Systems")
    rg._evidence_request("Systems/1")
    assert _read(tmp_path)["requests_sent"] == 0, "5초 안의 요청은 파일에 바로 쓰지 않는다 (throttle)"
    assert rg._EVIDENCE["dirty"] is True
    clock["t"] += 6
    rg._evidence_request("Chassis/1")
    data = _read(tmp_path)
    assert data["requests_sent"] == 3 and data["last_request"] == "Chassis/1"
    rg._evidence_request("Managers/1")
    rg._evidence_finish()
    assert _read(tmp_path)["last_request"] == "Managers/1", "종료 시 dirty 상태는 강제로 쓴다"


def test_first_status_write_is_immediate_even_inside_throttle_window(tmp_path, monkeypatch):
    rg._evidence_begin(_attempt(tmp_path), IP, "user")
    monkeypatch.setattr(rg.time, "monotonic", lambda: 1000.0)
    rg._EVIDENCE["last_write"] = 1000.0
    rg._evidence_request("Systems")
    rg._record_auth_status(401)
    assert _read(tmp_path)["first_auth_status"] == 401


def test_write_is_atomic_and_leaves_no_temp_file(tmp_path):
    rg._evidence_begin(_attempt(tmp_path), IP, "user")
    rg._record_auth_status(200)
    files = sorted(p.name for p in (tmp_path / "ev" / IP).iterdir())
    assert files == ["collect-1-1.json"]


def test_file_contains_no_secret(tmp_path):
    rg._evidence_begin(_attempt(tmp_path, label="standard", role="primary"), IP, "infraops")
    rg._record_auth_status(200)
    text = (tmp_path / "ev" / IP / "collect-1-1.json").read_text(encoding="utf-8")
    assert SECRET not in text and "Authorization" not in text and "password" not in text.lower()
    assert "infraops" not in text, "username 도 싣지 않는다 — label/role 로 충분하다"


def test_unwritable_directory_does_not_raise(tmp_path):
    target = tmp_path / "file-not-dir"
    target.write_text("x", encoding="utf-8")
    rg._evidence_begin({"evidence_dir": str(target), "id": "collect-1-1"}, IP, "user")
    rg._record_auth_status(200)         # 디렉터리를 만들 수 없다 → 조용히 무시
    rg._evidence_finish()


def test_ids_are_sanitised_for_the_filesystem(tmp_path):
    rg._evidence_begin(_attempt(tmp_path, "collect/../x"), IP, "user")
    assert (tmp_path / "ev" / IP / "collect_.._x.json").is_file()
    assert _read(tmp_path, "collect_.._x")["attempt_id"] == "collect/../x", "파일 안의 id 는 원문 (대조용)"


# ── filter: 식별자 대조 · 손상 · 부재 ────────────────────────────────────────
_GOOD = {"schema": 1, "build_id": "b1", "event_uuid": "e1", "ip": IP, "attempt_id": "collect-1-1",
         "label": "std", "role": "primary", "auth_mode": "credentialed", "first_auth_status": 401,
         "first_auth_at": "t", "started_at": "t", "updated_at": "t", "requests_sent": 3, "last_request": "Systems"}
_EXPECT = {"build_id": "b1", "event_uuid": "e1", "ip": IP, "attempt_id": "collect-1-1"}


def test_filter_accepts_matching_file():
    ev = parse_auth_evidence(json.dumps(_GOOD), _EXPECT)
    assert ev["valid"] and ev["credentialed"] and ev["first_auth_status"] == 401
    assert ev["label"] == "std" and ev["role"] == "primary" and ev["last_request"] == "Systems" and ev["requests_sent"] == 3


@pytest.mark.parametrize("key", ["build_id", "event_uuid", "ip", "attempt_id"])
def test_filter_rejects_identifier_mismatch(key):
    ev = parse_auth_evidence(json.dumps(_GOOD), {**_EXPECT, key: "other"})
    assert ev["valid"] is False and ev["reason"] == f"mismatch:{key}" and ev["first_auth_status"] is None


def test_filter_skips_identifier_check_when_expectation_is_blank():
    """Jenkins 밖(SE_BUILD_ID 없음)에서는 빈 기대값을 대조하지 않는다 — attempt_id 와 ip 만으로 충분하다."""
    ev = parse_auth_evidence(json.dumps({**_GOOD, "build_id": ""}), {**_EXPECT, "build_id": "", "event_uuid": ""})
    assert ev["valid"] is True


@pytest.mark.parametrize("raw,reason", [
    (None, "missing"), ("", "missing"), ("   ", "missing"),
    ("{not json", "corrupt"), ("[1,2]", "corrupt"), (json.dumps({**_GOOD, "schema": 2}), "schema"),
])
def test_filter_treats_missing_or_corrupt_as_no_evidence(raw, reason):
    ev = parse_auth_evidence(raw, _EXPECT)
    assert ev["valid"] is False and ev["reason"] == reason and ev["credentialed"] is False


def test_filter_normalises_bad_status_values():
    for st in (None, 0, -1, "401", True):
        ev = parse_auth_evidence(json.dumps({**_GOOD, "first_auth_status": st}), _EXPECT)
        assert ev["valid"] is True and ev["first_auth_status"] is None, st


def test_module_argument_spec_declares_attempt():
    src = (REPO / "redfish-gather" / "library" / "redfish_gather.py").read_text(encoding="utf-8")
    assert "attempt         = dict(type='dict', default=None, required=False)" in src
    assert "_evidence_begin(p.get('attempt'), bmc_ip, username)" in src
    # 요청 함수 전부가 요청 수 · 마지막 경로를 남긴다 (비밀값 없음)
    for fn in ("_get_impl", "_post", "_delete", "_patch", "_get_noauth", "_probe_realm_hint"):
        body = src.split(f"def {fn}(", 1)[1].split("\ndef ", 1)[0]
        assert "_evidence_request(" in body, fn
