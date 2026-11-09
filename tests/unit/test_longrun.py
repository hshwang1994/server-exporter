"""scripts/ai/longrun — 분리 실행 · 파일 감시 · 빌드 기록/이어받기 · 봉투 대조 · 승격 체인 계획 (2026-11-09).

고정하는 것
  - watch: 감시가 중간에 끊겨도 다시 걸면 빠짐 · 중복 없이 이어진다(읽은 위치 파일). 끝나지 않은 줄은 줄이 끝난 뒤 내보낸다.
  - start: 같은 작업 폴더에 살아 있는 실행이 있으면 띄우지 않는다. 띄운 프로세스의 출력은 작업 폴더 로그로 간다.
  - run_plan: 기대대로 끝난 시나리오는 다시 넣지 않고, journal 에만 있는 진행 중 빌드는 이어받고, 다른 결과로 끝난 빌드는
    새로 넣는다. E2E-A2 · T5 는 이어받지 않는다. 빌드 번호는 기다리기 전에 journal 에 남는다.
  - 승격 체인 계획: prodgen 필수 시나리오 · 계약 기대값 사용, E2E_MAIN_ENTRIES 형식, 다음 계획 파일.
  - Jenkins TLS: 모든 curl 호출이 고정한 인증서(`--cacert`)로 검증한다(`-k` 없음). 인증서는 지문이 기대값과 같을 때만 저장하고,
    인증서 파일이 없으면 체인은 네트워크 확인 전에 멈춘다.
scripts/ai 는 production tree 에 없다 — G14 overlay 에서 제외되도록 표식을 달고, import 는 fixture 안에서 한다.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import ssl
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.source_text   # scripts/ai(개발 전용 도구)를 쓴다 — production tree overlay(G14)에서 제외

REPO = Path(__file__).resolve().parents[2]
SHA = "e4e7d5d194da31c6a17848b85f6f968c0d7d1b75"


@pytest.fixture
def lr():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    return {name: importlib.import_module(f"scripts.ai.longrun.{name}")
            for name in ("detached", "submit", "bodies", "chain", "jenkins", "__main__")}


class _Stop(Exception):
    pass


# ---------------------------------------------------------------- watch
def test_watch_resumes_without_loss_or_duplicates(tmp_path, lr):
    det = lr["detached"]
    (tmp_path / "pid.txt").write_text("4242", encoding="ascii")
    log = tmp_path / "detached_20261109-000000.log"
    log.write_bytes("x [PASS] one\nx plain\nx [NG] two\nx [PA".encode("utf-8"))

    def stop_sleep(_s):
        raise _Stop

    got1 = []
    with pytest.raises(_Stop):
        for line in det.watch(tmp_path, r"\[PASS\]|\[NG\]", alive=lambda _p: True, sleep=stop_sleep):
            got1.append(line)
    assert got1 == ["x [PASS] one", "x [NG] two"]          # 끝나지 않은 줄은 아직 내보내지 않는다

    with log.open("ab") as fp:                               # 감시가 끊긴 사이에 줄이 늘었다
        fp.write("SS] three\nx [NG] four\n".encode("utf-8"))
    got2 = list(det.watch(tmp_path, r"\[PASS\]|\[NG\]", alive=lambda _p: False, sleep=stop_sleep))
    assert got2[:2] == ["x [PASS] three", "x [NG] four"]
    assert got2[-1].startswith("[MONITOR]") and "4242" in got2[-1]
    assert len(got2) == 3


def test_watch_reads_newer_log_from_start(tmp_path, lr):
    det = lr["detached"]
    (tmp_path / "pid.txt").write_text("4242", encoding="ascii")
    (tmp_path / "detached_20261109-000000.log").write_text("old [PASS] a\n", encoding="utf-8")
    (tmp_path / "watch_offset.txt").write_text("detached_20261109-000000.log 13", encoding="ascii")
    (tmp_path / "detached_20261109-010000.log").write_text("new [PASS] b\n", encoding="utf-8")
    got = list(det.watch(tmp_path, r"\[PASS\]", alive=lambda _p: False, sleep=lambda _s: None))
    assert got[0] == "new [PASS] b" and len(got) == 2


# ---------------------------------------------------------------- start / acquire
def test_start_refuses_when_work_dir_has_live_process(tmp_path, lr):
    det = lr["detached"]
    (tmp_path / "pid.txt").write_text(str(os.getpid()), encoding="ascii")
    rc, pid, log = det.start(tmp_path, [sys.executable, "-c", "print(1)"])
    assert (rc, pid, log) == (3, os.getpid(), None)
    assert not list(tmp_path.glob("detached_*.log"))


def test_start_runs_detached_and_writes_log(tmp_path, lr):
    det = lr["detached"]
    rc, pid, log = det.start(tmp_path, [sys.executable, "-c", "print('hello-longrun')"])
    assert rc == 0 and pid > 0 and log is not None
    assert det.read_pid(tmp_path) == pid
    t0 = time.time()
    while det.pid_alive(pid) and time.time() - t0 < 60:
        time.sleep(0.2)
    assert not det.pid_alive(pid)
    assert "hello-longrun" in log.read_text(encoding="utf-8", errors="replace")


def test_acquire_refuses_other_live_runner_then_takes_over(tmp_path, lr):
    det = lr["detached"]
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        (tmp_path / "pid.txt").write_text(str(other.pid), encoding="ascii")
        assert det.acquire(tmp_path) == other.pid
        assert det.read_pid(tmp_path) == other.pid
    finally:
        other.kill()
        other.wait()
    assert det.acquire(tmp_path) == 0
    assert det.read_pid(tmp_path) == os.getpid()


def test_cli_start_strips_separator_and_status_reports(tmp_path, lr, capsys):
    cli = lr["__main__"]
    assert cli.main(["start", "--work", str(tmp_path), "--", sys.executable, "-c", "print('cli-ok')"]) == 0
    pid = lr["detached"].read_pid(tmp_path)
    t0 = time.time()
    while lr["detached"].pid_alive(pid) and time.time() - t0 < 60:
        time.sleep(0.2)
    capsys.readouterr()
    assert cli.main(["status", "--work", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert f"pid={pid} alive=False" in out and "cli-ok" in out


# ---------------------------------------------------------------- run_plan
class FakeJenkins:
    def __init__(self, infos=None, results=None, fail_wait_on=None):
        self.infos = infos or {}
        self.results = results or {}
        self.fail_wait_on = fail_wait_on
        self.triggered: list[dict] = []
        self.stopped: list[int] = []
        self.next = 100

    def build_info(self, job, build):
        return self.infos[build]

    def trigger(self, job, params):
        self.triggered.append(dict(params))
        return f"queue/{self.next}"

    def wait_build_number(self, queue_url):
        n = self.next
        self.next += 1
        return n

    def wait_done(self, job, build):
        if self.fail_wait_on == build:
            raise RuntimeError("process killed while waiting")
        return {"result": self.results.get(build, "SUCCESS"), "duration": 2000,
                "actions": [{"lastBuiltRevision": {"SHA1": SHA}}]}

    def console_has(self, job, build, marker):
        return True

    def stop(self, job, build):
        self.stopped.append(build)
        return 302

    def artifact_text(self, job, build, rel):
        return 200, json.dumps({"gatherInfoJson": []})


def _prev(build):
    return {"loc": "ich", "target_type": "os", "eventUuid": f"old-{build}", "inventory_json": "[]", "PROMOTE_SHA": ""}


def _write_jsonl(path, recs):
    path.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")


def test_run_plan_keeps_adopts_and_retriggers(tmp_path, lr, monkeypatch):
    sub = lr["submit"]
    monkeypatch.setattr(sub.time, "sleep", lambda _s: None)
    runs = tmp_path / "runs_matrix.jsonl"
    _write_jsonl(runs, [{"scenario": "S1", "job": "j", "build": 40, "result": "SUCCESS", "ok_expected": True}])
    _write_jsonl(runs.with_name(runs.name + ".started"), [
        {"scenario": "S2", "build": 50, "job": "j", "eventUuid": "u50"},     # 아직 돈다 → 이어받기
        {"scenario": "S3", "build": 51, "job": "j", "eventUuid": "u51"},     # 다른 결과로 끝남 → 새로 넣기
        {"scenario": "E2E-A2", "build": 52, "job": "j", "eventUuid": "u52"},  # tip 관측이 증거 → 이어받지 않음
    ])
    jk = FakeJenkins(infos={50: {"building": True}, 51: {"building": False, "result": "FAILURE"}, 52: {"building": True}},
                     results={100: "SUCCESS", 101: "FAILURE", 102: "ABORTED"})
    tips = iter([SHA, SHA])
    entries = [("S1", 1, ("SUCCESS",)), ("S2", 2, ("SUCCESS",)), ("S3", 3, ("SUCCESS",)),
               ("E2E-A2", 4, ("FAILURE",)), ("T5", 5, ("ABORTED",))]
    out = sub.run_plan(jk, "j", entries, runs=runs, prev_params=_prev, bodies=tmp_path / "bodies",
                       body_name=lambda n: f"main_{n}.json", expect_sha=SHA, sets={"PROMOTE_SHA": SHA},
                       tip_of_main=lambda: next(tips), tip_file=tmp_path / "tip.json", log=lambda _m: None)
    assert len(jk.triggered) == 3 and all(p["PROMOTE_SHA"] == SHA for p in jk.triggered)
    assert all(not p["eventUuid"].startswith("old-") for p in jk.triggered)   # eventUuid 만 새 값
    assert out["S1"]["build"] == 40                                       # 그대로 둠
    assert out["S2"]["build"] == 50 and out["S2"].get("adopted") is True and out["S2"]["eventUuid"] == "u50"
    assert out["S3"]["build"] == 100 and out["S3"]["ok_expected"] is True
    assert out["E2E-A2"]["build"] == 101 and out["E2E-A2"]["tip_before"] == out["E2E-A2"]["tip_after"] == SHA
    assert json.loads((tmp_path / "tip.json").read_text(encoding="utf-8"))[0]["build"] == 101
    assert out["T5"]["build"] == 102 and out["T5"]["stop_http"] == 302 and jk.stopped == [102]
    journal = [json.loads(x) for x in runs.with_name(runs.name + ".started").read_text(encoding="utf-8").splitlines()]
    assert [e["build"] for e in journal] == [50, 51, 52, 100, 101, 102]
    assert (tmp_path / "bodies" / "main_100.json").exists()


def test_run_plan_journal_survives_death_and_next_run_adopts(tmp_path, lr, monkeypatch):
    sub = lr["submit"]
    monkeypatch.setattr(sub.time, "sleep", lambda _s: None)
    runs = tmp_path / "runs_ci.jsonl"
    jk = FakeJenkins(fail_wait_on=100)
    with pytest.raises(RuntimeError):
        sub.run_plan(jk, "ci", [("CI", 67, ("SUCCESS",))], runs=runs, prev_params=_prev, bodies=tmp_path / "b",
                     body_name=lambda n: f"ci_{n}.json", log=lambda _m: None)
    journal = runs.with_name(runs.name + ".started")
    assert [json.loads(x)["build"] for x in journal.read_text(encoding="utf-8").splitlines()] == [100]
    assert not runs.exists()
    jk2 = FakeJenkins(infos={100: {"building": True}})
    out = sub.run_plan(jk2, "ci", [("CI", 67, ("SUCCESS",))], runs=runs, prev_params=_prev, bodies=tmp_path / "b",
                       body_name=lambda n: f"ci_{n}.json", log=lambda _m: None)
    assert jk2.triggered == [] and out["CI"]["build"] == 100 and out["CI"]["adopted"] is True
    # 세 번째 실행: 기대대로 끝난 기록이 있으므로 아무것도 넣지 않는다
    jk3 = FakeJenkins()
    sub.run_plan(jk3, "ci", [("CI", 67, ("SUCCESS",))], runs=runs, prev_params=_prev, bodies=tmp_path / "b",
                 body_name=lambda n: f"ci_{n}.json", log=lambda _m: None)
    assert jk3.triggered == []


def test_run_plan_rejects_unknown_override(tmp_path, lr):
    with pytest.raises(KeyError):
        lr["submit"].build_params(_prev(1), {"NOT_A_PARAM": "x"}, {})


def test_run_plan_marks_checkout_mismatch(tmp_path, lr, monkeypatch):
    sub = lr["submit"]
    monkeypatch.setattr(sub.time, "sleep", lambda _s: None)
    out = sub.run_plan(FakeJenkins(), "j", [("S1", 1, ("SUCCESS",))], runs=tmp_path / "r.jsonl", prev_params=_prev,
                       bodies=tmp_path / "b", body_name=lambda n: f"m_{n}.json", expect_sha="f" * 40, log=lambda _m: None)
    assert out["S1"]["ok_expected"] is False and out["S1"]["sha_mismatch"] is True


# ---------------------------------------------------------------- bodies
def _body(path, envs):
    path.write_text(json.dumps({"gatherInfoJson": json.dumps(envs)}), encoding="utf-8")


def test_compare_same_diff_and_host_set(tmp_path, lr):
    b = lr["bodies"]
    e1 = {"ip": "10.0.0.1", "status": "success", "sections": {"system": "success"}, "errors": [], "correlation": {"serial_number": "S"},
          "data": {"hardware": {"serial": "S"}, "cpu": {"usage": 3}}, "diagnosis": {"failure_code": None, "details": {}}}
    _body(tmp_path / "a.json", [e1])
    e1b = json.loads(json.dumps(e1))
    e1b["data"]["cpu"]["usage"] = 99                          # 변동 값은 대조하지 않는다
    _body(tmp_path / "b.json", [e1b])
    assert b.compare(tmp_path / "a.json", tmp_path / "b.json", "t")[0] == 0
    e1c = json.loads(json.dumps(e1))
    e1c["status"] = "failed"
    _body(tmp_path / "c.json", [e1c, {**e1, "ip": "10.0.0.2"}])
    bad, lines = b.compare(tmp_path / "a.json", tmp_path / "c.json", "t")
    assert bad == 2 and any(x.startswith("[DIFF] 10.0.0.1: status") for x in lines) and lines[1].startswith("[NG] host set")
    s = b.summarize(tmp_path / "a.json")
    assert s["hosts"] == 1 and s["success_with_serial"] == 1 and s["details_serial_number"] == 0


# ---------------------------------------------------------------- 승격 체인 계획
def _plan():
    names = ["S1", "S2", "S3", "S4", "T2", "T6", "E2E-A", "E2E-A2", "E2E-D", "E2E-E", "T5"]
    return {"jenkins_url": "https://jenkins.invalid", "scm_url": "https://github.invalid/x",
            "jobs": {"main": "f/main", "ci": "f/ci", "production": "f/prod"}, "ci_prev": 69,
            "matrix": [{"scenario": n, "prev": 732 + i} for i, n in enumerate(names)],
            "canary": [{"name": "C-OS", "prev": 323, "main_scenario": "S3", "baseline": 323}]}


def test_chain_plan_validation_uses_prodgen_contract(tmp_path, lr):
    ch = lr["chain"].Chain(SHA, _plan(), tmp_path, tmp_path / "netrc", tmp_path / "pw")
    assert ch.validate_plan() == []
    assert ch.accept("T5") == ("ABORTED",) and ch.accept("E2E-A2") == ("FAILURE",) and ch.accept("T6") == ("UNSTABLE",)
    bad = _plan()
    bad["matrix"] = [m for m in bad["matrix"] if m["scenario"] != "T5"] + [{"scenario": "S1", "prev": 1}]
    bad["canary"][0]["main_scenario"] = "S9"
    probs = lr["chain"].Chain(SHA, bad, tmp_path, tmp_path / "n", tmp_path / "p").validate_plan()
    assert any("중복" in p for p in probs) and any("T5" in p for p in probs) and any("S9" in p for p in probs)


def test_chain_entries_and_next_plan(tmp_path, lr):
    ch = lr["chain"].Chain(SHA, _plan(), tmp_path, tmp_path / "netrc", tmp_path / "pw")
    builds = {m["scenario"]: 800 + i for i, m in enumerate(ch.plan["matrix"])}
    assert ch.entries_for(builds).startswith("S1=f/main:800,S2=f/main:801,") and ch.entries_for(builds).endswith("T5=f/main:810")
    ch.st = {"matrix": builds, "ci": 70, "canary": {"C-OS": 330}}
    nxt = ch.next_plan()
    assert nxt["ci_prev"] == 70 and nxt["matrix"][0] == {"scenario": "S1", "prev": 800}
    assert nxt["canary"][0]["prev"] == nxt["canary"][0]["baseline"] == 330
    assert ch.plan["ci_prev"] == 69                           # 원래 계획은 바뀌지 않는다


def test_chain_without_pinned_cert_stops_before_network(tmp_path, lr):
    ch = lr["chain"].Chain(SHA, _plan(), tmp_path, tmp_path / "netrc", tmp_path / "pw", cacert=tmp_path / "none.pem")

    def boom(*a, **k):
        raise AssertionError("파일이 없으면 git · Jenkins · GitHub 를 부르지 않는다")

    ch.git = boom
    ch.anonymous_read_ok = boom
    ch.jk.get_json = boom
    probs = ch.preflight("preflight", plan_only=True)
    assert any("고정한 Jenkins 인증서 없음" in p and "pin-cert" in p for p in probs)
    assert any("자격 파일 없음" in p for p in probs)


# ---------------------------------------------------------------- Jenkins TLS (고정 인증서)
def test_jenkins_curl_verifies_tls_with_pinned_cert(tmp_path, lr, monkeypatch):
    jm = lr["jenkins"]
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        out = b"200" if "-o" in cmd else b"HTTP/1.1 200 OK\r\n\r\n{}\n200"
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr=b"")

    monkeypatch.setattr(jm.subprocess, "run", fake_run)
    ca = tmp_path / "jenkins_chain.pem"
    jk = jm.Jenkins("https://jenkins.invalid", tmp_path / "netrc", jar=tmp_path / "jar", cacert=ca)
    assert jk.get_json("https://jenkins.invalid/api/json") == {}
    assert jk.download("https://jenkins.invalid/x", tmp_path / "x.json") == 200
    jk.crumb_header = "Jenkins-Crumb: c"
    jk.stop("f/main", 1)
    assert len(calls) == 3
    for cmd in calls:
        assert cmd[cmd.index("--cacert") + 1] == str(ca)
        short = [a for a in cmd if a.startswith("-") and not a.startswith("--")]
        assert not any("k" in a for a in short), cmd               # -k · -sk · -skg 없음
        assert "--insecure" not in cmd
    src = "\n".join(p.read_text(encoding="utf-8") for p in (REPO / "scripts" / "ai" / "longrun").glob("*.py"))
    assert not re.search(r'"-s?k[a-z]*"|--insecure', src)           # 패키지 어디에도 검증을 끄는 인자가 없다


def test_jenkins_tls_failure_is_named(tmp_path, lr, monkeypatch):
    jm = lr["jenkins"]
    monkeypatch.setattr(jm.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 60, stdout=b"\n000", stderr=b""))
    jk = jm.Jenkins("https://jenkins.invalid", tmp_path / "netrc", cacert=tmp_path / "ca.pem")
    with pytest.raises(jm.JenkinsError) as ei:
        jk.get_json("https://jenkins.invalid/api/json")
    assert "TLS 검증 실패" in str(ei.value) and "curl rc 60" in str(ei.value)


def test_pin_cert_saves_only_matching_fingerprint(tmp_path, lr):
    jm = lr["jenkins"]
    der = b"pinned-cert-der-bytes"
    pem = ssl.DER_cert_to_PEM_cert(der)
    seen = []

    def fetch(addr, timeout=None):
        seen.append(addr)
        return pem

    want = hashlib.sha256(der).hexdigest().upper()
    out = tmp_path / "ca" / "jenkins_chain.pem"
    rc, fp = jm.pin_cert("https://jenkins.invalid:8443/x", out, None, fetch=fetch)
    assert rc == 2 and fp.replace(":", "") == want and not out.exists() and seen[-1] == ("jenkins.invalid", 8443)
    rc, _ = jm.pin_cert("https://jenkins.invalid", out, "AA:" * 31 + "AA", fetch=fetch)
    assert rc == 4 and not out.exists() and seen[-1] == ("jenkins.invalid", 443)
    rc, _ = jm.pin_cert("https://jenkins.invalid", out, fp.lower(), fetch=fetch)     # 대소문자 · 콜론 무관
    assert rc == 0 and out.read_text(encoding="ascii") == pem


def test_chain_run_refuses_second_runner(tmp_path, lr, capsys):
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        (tmp_path / "pid.txt").write_text(str(other.pid), encoding="ascii")
        ch = lr["chain"].Chain(SHA, _plan(), tmp_path, tmp_path / "netrc", tmp_path / "pw")
        assert ch.run("preflight", "canary_cmp", plan_only=True) == 3
        assert "이미 실행 중" in capsys.readouterr().out
    finally:
        other.kill()
        other.wait()
