"""tests/jenkins/harness/callback_sink.py — Harness Callback POST 수신기 (2026-10-04, Astra 3차 §5-1).

고정하는 것
  - POST /api/jenkins/gather/<target_type> 를 실제로 받고(GET 전용 http.server 가 아니다) body 를 검증해 기록한다.
  - 응답 코드 순서(--status 503,503,200)·지연·연결 끊기를 시험이 통제한다.
  - 기록은 시험별 파일(JSONL)이고, 평문 비밀값을 받을 일이 없는 구조다(envelope 만).
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SINK = REPO / "tests" / "jenkins" / "harness" / "callback_sink.py"
KEYS13 = ["schema_version", "target_type", "collection_method", "ip", "hostname", "vendor", "status",
          "sections", "diagnosis", "meta", "correlation", "errors", "data"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _envelope(ip: str, target_type: str = "os") -> dict:
    env = {k: None for k in KEYS13}
    env.update({"schema_version": "1", "target_type": target_type, "ip": ip, "status": "failed", "sections": {}, "errors": [], "data": {},
                "diagnosis": {}, "meta": {}, "correlation": {}})
    return env


def _post(url: str, body: dict, timeout: float = 10.0):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def _wait_health(port: int) -> None:
    for _ in range(50):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise AssertionError("sink did not come up")


@pytest.fixture
def sink(tmp_path):
    procs = []

    def start(*extra: str):
        port = _free_port()
        record = tmp_path / f"record_{port}.jsonl"
        cmd = [sys.executable, str(SINK), "--port", str(port), "--bind", "127.0.0.1", "--record", str(record),
               "--max-seconds", "60", *extra]
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        procs.append(p)
        _wait_health(port)
        return port, record

    yield start
    for p in procs:
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


def _records(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_valid_post_is_accepted_recorded_and_answered_2xx(sink):
    port, record = sink("--status", "200", "--expect-ips", "192.0.2.10,192.0.2.11")
    body = {"loc": "git", "deploymentEnvironmentId": "dev", "eventUuid": "e1",
            "gatherInfoJson": [_envelope("192.0.2.10"), _envelope("192.0.2.11")]}
    status, resp = _post(f"http://127.0.0.1:{port}/api/jenkins/gather/os", body)
    assert status == 200 and resp["received"] is True and resp["hosts"] == 2
    recs = _records(record)
    assert len(recs) == 1 and recs[0]["ok"] is True and recs[0]["problems"] == []
    assert recs[0]["hosts"] == ["192.0.2.10", "192.0.2.11"] and recs[0]["loc"] == "git" and recs[0]["eventUuid"] == "e1"
    assert recs[0]["status_sent"] == 200 and len(recs[0]["body_sha256"]) == 64


def test_invalid_body_and_wrong_path_are_recorded_as_problems(sink):
    port, record = sink("--status", "200")
    status, resp = _post(f"http://127.0.0.1:{port}/api/jenkins/gather/os", {"loc": "git", "gatherInfoJson": [{"ip": "1.2.3.4"}]})
    assert status == 200 and resp["received"] is False
    status2, _ = _post(f"http://127.0.0.1:{port}/api/other/path", {"x": 1})
    recs = _records(record)
    assert len(recs) == 2
    assert any("keys != 13" in p for p in recs[0]["problems"]) and "missing deploymentEnvironmentId" in recs[0]["problems"]
    assert any("is not /api/jenkins/gather" in p for p in recs[1]["problems"])


def test_status_sequence_then_sticky_last_value(sink):
    port, record = sink("--status", "503,503,200")
    body = {"loc": "git", "deploymentEnvironmentId": "dev", "eventUuid": "e1", "gatherInfoJson": [_envelope("192.0.2.10")]}
    url = f"http://127.0.0.1:{port}/api/jenkins/gather/os"
    codes = [_post(url, body)[0] for _ in range(4)]
    assert codes == [503, 503, 200, 200], "지정 순서대로, 마지막 값은 반복"
    assert [r["status_sent"] for r in _records(record)] == [503, 503, 200, 200]


def test_close_mode_drops_connection_without_response(sink):
    port, record = sink("--mode", "close")
    body = {"loc": "git", "deploymentEnvironmentId": "dev", "eventUuid": "e1", "gatherInfoJson": [_envelope("192.0.2.10")]}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/jenkins/gather/os", data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with pytest.raises(Exception):
        urllib.request.urlopen(req, timeout=10)
    recs = _records(record)
    assert len(recs) == 1 and recs[0]["status_sent"] is None and recs[0]["mode"] == "close"


def test_health_get_is_not_a_callback_record(sink):
    port, record = sink()
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as r:
        assert r.status == 200
    assert not record.exists() or _records(record) == [], "GET health 는 Callback 수신 증거가 아니므로 기록하지 않는다"
