"""tests/jenkins/harness — build_functions.py · fixture.py · harness_verdict.py · scenarios.json (2026-10-04, Astra 3차 §5 · 4차 §2·§3).

고정하는 것
  - build_functions.py 는 Jenkinsfile_portal 의 `pipeline {` 앞 함수부를 **글자 그대로** 잘라내고(해시 기록) wrapper 만 덧붙인다.
    wrapper 는 운영 소스에 없다 — 운영 Jenkinsfile 에는 장애 주입 토큰이 없어야 한다.
  - fixture.py 는 corpus 입력을 복사하고 manifest 를 현재 빌드(job/number/url)와 시험 request 로 다시 만든다.
  - harness_verdict.py 는 기대/관측 대조로 PASS · FAIL · PARTIAL(관측 부족) 을 나누고, 관측이 없으면 PASS 로 두지 않는다.
  - scenarios.json 의 이름 집합은 세 도구가 같은 것을 쓴다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "tests" / "jenkins" / "harness"
PORTAL = REPO / "Jenkinsfile_portal"
sys.path.insert(0, str(HARNESS))

import build_functions  # noqa: E402
import fixture  # noqa: E402
import harness_verdict  # noqa: E402

SCENARIOS = json.loads((HARNESS / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]


def test_scenario_names_are_consistent_across_tools():
    assert set(SCENARIOS) == set(build_functions.SCENARIOS)
    for name, sc in SCENARIOS.items():
        if name != "sandbox_probe":
            assert (REPO / "tests" / "fixtures" / "finalize_corpus" / sc["case"]).is_dir(), f"{name}: corpus case {sc['case']} 없음"
        assert "expect" in sc


def test_build_functions_extracts_runtime_functions_verbatim(tmp_path):
    out = tmp_path / "f.groovy"
    meta = build_functions.build(PORTAL, "archive_fail", out, tmp_path / "meta.json")
    text = out.read_text(encoding="utf-8")
    src = PORTAL.read_text(encoding="utf-8")
    functions = src[: src.index("\npipeline {") + 1]
    assert text.startswith(functions.rstrip("\n")), "함수부는 원본과 글자까지 같다 (wrapper 는 뒤에만 붙는다)"
    for name in ("seFinalizeAndCallback", "sePreserveGatherOutput", "seConstants", "seCallback", "seFilterEnvelopeLines"):
        assert name in meta["defs"], name
    assert "pipeline {" not in text.split("harness wrappers")[0]
    assert text.rstrip().endswith("return this")
    for wrapper in ("def getParams()", "def archiveArtifacts(Map m)", "def stash(Map m)", "def unstash(String name)",
                    "def readTrusted(String path)", "def sh(Map m)", "def unstable(String msg)", "def httpRequest(Map m)"):
        assert wrapper in text, wrapper
    assert "'archive_fail'" in text and "startsWith('gather_output.json')" in text, "주입 대상은 보존 archive 뿐"
    assert len(meta["functions_sha256"]) == 64 and len(meta["source_sha256"]) == 64


def test_runtime_jenkinsfile_has_no_fault_injection_tokens():
    """3차 §5-2: 장애 주입은 운영 소스 밖. 운영 Jenkinsfile 에 Harness 토큰이 없어야 한다."""
    src = PORTAL.read_text(encoding="utf-8")
    for token in ("faultInject", "SE_FAULT_INJECT", "injected", "HARNESS", "perfSample", "harness wrappers"):
        assert token not in src, token


def test_fixture_regenerates_manifest_for_the_current_build(tmp_path):
    ws = tmp_path / "ws"
    out = tmp_path / "state.json"
    rc = fixture.main(["--scenarios", str(HARNESS / "scenarios.json"), "--scenario", "normal_success",
                       "--corpus", str(REPO / "tests/fixtures/finalize_corpus"), "--workspace", str(ws),
                       "--job", "clovirone-cicd/clovirone-server-gather-harness", "--number", "77", "--url", "https://j/x/77/",
                       "--loc", "git", "--deployment-env", "harness", "--event-uuid", "harness-77", "--callback-url", "http://10.0.0.5:18080",
                       "--out", str(out)])
    assert rc == 0
    m = json.loads((ws / "gather_manifest.json").read_text(encoding="utf-8"))
    assert m["build"] == {"job": "clovirone-cicd/clovirone-server-gather-harness", "number": "77", "url": "https://j/x/77/"}
    assert m["request"]["callbackUrl"] == "http://10.0.0.5:18080" and m["request"]["eventUuid"] == "harness-77" and m["request"]["loc"] == "git"
    assert m["ips"] == ["198.51.100.11", "198.51.100.12", "198.51.100.13"] and m["channel"] == "os"
    assert (ws / "gather_output.json").is_file() and (ws / "gather_progress.jsonl").is_file()
    state = json.loads(out.read_text(encoding="utf-8"))
    assert state["run_preserve"] is True and state["outcome"] == "completed" and state["case"] == "01_normal"


def test_fixture_post_layer_a_mutation_corrupts_report(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "gather_finalize_report.json").write_text('{"ok": true}', encoding="utf-8")
    rc = fixture.main(["--scenarios", str(HARNESS / "scenarios.json"), "--scenario", "report_corrupt",
                       "--corpus", str(REPO / "tests/fixtures/finalize_corpus"), "--workspace", str(ws),
                       "--job", "x", "--number", "0", "--url", "x", "--callback-url", "x", "--out", str(tmp_path / "p.json"), "--post-layer-a"])
    assert rc == 0
    with pytest.raises(ValueError):
        json.loads((ws / "gather_finalize_report.json").read_text(encoding="utf-8"))


def _write(p: Path, obj) -> str:
    p.write_text(json.dumps(obj) if not isinstance(obj, str) else obj, encoding="utf-8")
    return str(p)


def _run_verdict(tmp_path, scenario, **files):
    args = ["--scenarios", str(HARNESS / "scenarios.json"), "--scenario", scenario, "--out", str(tmp_path / "result.json")]
    for k, v in files.items():
        args += [f"--{k}", v]
    rc = harness_verdict.main(args)
    return rc, json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))


def test_verdict_pass_fail_partial(tmp_path):
    body = tmp_path / "callback_body.json"
    body.write_bytes(b'{"loc":"git","gatherInfoJson":[]}')
    import hashlib
    sha = hashlib.sha256(body.read_bytes()).hexdigest()
    summary = {"accepted": 3, "lines": 3, "kept": 3, "filled": 0, "outcome": "completed", "layerA": "ok", "layerB": "skipped",
               "source": "stash", "unrecovered": [], "damage": [], "recovery_limited": False, "by_origin": {"output": 3, "checkpoint": 0, "synthetic": 0}}
    sink = json.dumps({"method": "POST", "status_sent": 200, "ok": True, "body_sha256": sha}) + "\n"
    preserve = {"archived": True, "stashed": True, "deleted": True}
    control = {"sink_reachable": True, "rethrown": False}
    rc, res = _run_verdict(tmp_path, "normal_success", summary=_write(tmp_path / "s.json", summary), body=str(body),
                           calls=_write(tmp_path / "c.json", ["archiveArtifacts", "stash", "unstash"]), sink=_write(tmp_path / "k.jsonl", sink),
                           preserve=_write(tmp_path / "p.json", preserve), control=_write(tmp_path / "ctl.json", control))
    assert rc == 0 and res["verdict"] == "PASS" and res["problems"] == []
    # FAIL: unstable 이 호출됐고 archive 가 실패했다
    rc, res = _run_verdict(tmp_path, "normal_success", summary=_write(tmp_path / "s.json", summary), body=str(body),
                           calls=_write(tmp_path / "c2.json", ["unstable:[Finalize/A] archive 실패"]), sink=_write(tmp_path / "k.jsonl", sink),
                           preserve=_write(tmp_path / "p2.json", {"archived": False, "stashed": True, "deleted": False}),
                           control=_write(tmp_path / "ctl.json", control))
    assert rc == 1 and res["verdict"] == "FAIL" and any("preserve.archived" in p for p in res["problems"])
    # PARTIAL: 요약이 없다 — PASS 로 두지 않는다
    rc, res = _run_verdict(tmp_path, "normal_success", calls=_write(tmp_path / "c3.json", []), control=_write(tmp_path / "ctl2.json", {"sink_reachable": False}))
    assert rc == 2 and res["verdict"] == "PARTIAL" and res["partial"]


def test_verdict_outer_timeout_requires_rethrown(tmp_path):
    rc, res = _run_verdict(tmp_path, "outer_timeout", control=_write(tmp_path / "ctl.json", {"rethrown": True, "sink_reachable": True}),
                           sink=_write(tmp_path / "k.jsonl", ""))
    assert rc == 0 and res["verdict"] == "PASS"
    rc, res = _run_verdict(tmp_path, "outer_timeout", control=_write(tmp_path / "ctl2.json", {"rethrown": False, "sink_reachable": True}),
                           sink=_write(tmp_path / "k2.jsonl", ""))
    assert rc == 1 and res["verdict"] == "FAIL", "외곽 timeout 을 삼켰다면 FAIL"


def test_build_functions_cli_runs(tmp_path):
    r = subprocess.run([sys.executable, str(HARNESS / "build_functions.py"), "--source", str(PORTAL), "--scenario", "normal_success",
                        "--out", str(tmp_path / "o.groovy")], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["scenario"] == "normal_success"



# ── 2026-10-04 검토 C5 — interruption 시나리오 ─────────────────────────────────────────
def test_interruption_scenarios_cover_the_six_conditions_and_bounded_ones_are_partial_without_approvals(tmp_path):
    names = set(SCENARIOS)
    assert {"recover_slow", "inner_recover_timeout", "inner_assemble_timeout", "outer_timeout", "foreign_timeout_interruption",
            "user_abort", "aborted_outcome_finalize"} <= names
    for n in ("inner_recover_timeout", "inner_assemble_timeout"):
        assert SCENARIOS[n]["bounded"] and SCENARIOS[n]["probe_approvals"] and SCENARIOS[n]["expect"]["rethrown"] is False
    assert SCENARIOS["user_abort"]["jenkins_result"] == "ABORTED" and SCENARIOS["user_abort"]["expect_interruption"]
    assert SCENARIOS["aborted_outcome_finalize"]["outcome"] == "aborted" and SCENARIOS["aborted_outcome_finalize"]["set_result"] == "ABORTED"
    assert SCENARIOS["aborted_outcome_finalize"]["expect"]["sink_posts_max"] == 1, "ABORTED 빌드는 Callback 1회만 시도"
    assert SCENARIOS["foreign_timeout_interruption"]["expect"]["rethrown"] is True
    # bounded scenario without the 4 approvals: rethrown → PARTIAL(승인) — not FAIL, not PASS
    control = {"rethrown": True, "bounded": True, "sink_reachable": True,
               "approvals": {"getEnclosingBlocks": False, "getId": False, "getCauses": True, "getNodeId": False}}
    rc, res = _run_verdict(tmp_path, "inner_recover_timeout", control=_write(tmp_path / "c1.json", control), sink=_write(tmp_path / "k1.jsonl", ""))
    assert rc == 2 and res["verdict"] == "PARTIAL" and any("Script Approval" in p and "getEnclosingBlocks" in p for p in res["partial"]), res
    # with every approval present a rethrow is a real FAIL (the bound did not work)
    control2 = dict(control, approvals={k: True for k in ("getEnclosingBlocks", "getId", "getCauses", "getNodeId")})
    rc, res = _run_verdict(tmp_path, "inner_recover_timeout", control=_write(tmp_path / "c2.json", control2), sink=_write(tmp_path / "k2.jsonl", ""))
    assert rc == 1 and res["verdict"] == "FAIL" and any("rethrown" in p for p in res["problems"])
    # foreign timeout: rethrown is the expectation regardless of approvals
    rc, res = _run_verdict(tmp_path, "foreign_timeout_interruption", control=_write(tmp_path / "c3.json", {"rethrown": True, "bounded": False, "sink_reachable": True}),
                           sink=_write(tmp_path / "k3.jsonl", ""))
    assert rc == 0 and res["verdict"] == "PASS"
    rc, res = _run_verdict(tmp_path, "foreign_timeout_interruption", control=_write(tmp_path / "c4.json", {"rethrown": False, "bounded": False, "sink_reachable": True}),
                           sink=_write(tmp_path / "k4.jsonl", ""))
    assert rc == 1 and res["verdict"] == "FAIL", "남의 timeout 을 삼켰다면 FAIL"


def test_verdict_checks_summary_outcome_for_aborted_finalize(tmp_path):
    summary = {"accepted": 3, "lines": 3, "kept": 3, "filled": 0, "outcome": "completed", "layerA": "ok", "layerB": "skipped", "source": "stash",
               "unrecovered": [], "damage": [], "by_origin": {"output": 3, "checkpoint": 0, "synthetic": 0}}
    sink = json.dumps({"method": "POST", "status_sent": 200, "ok": True, "body_sha256": "x"}) + "\n"
    calls = ["unstable:[Finalize] 전송은 됐지만 보충(filled=0) · 비정상 종료(outcome=aborted)"]
    rc, res = _run_verdict(tmp_path, "aborted_outcome_finalize", summary=_write(tmp_path / "s.json", summary),
                           calls=_write(tmp_path / "c.json", calls), sink=_write(tmp_path / "k.jsonl", sink),
                           control=_write(tmp_path / "ctl.json", {"rethrown": False, "sink_reachable": True}))
    assert rc == 1 and any(c["name"] == "outcome" and not c["ok"] for c in res["checks"]), "outcome=completed 는 aborted 사후 경로가 아니다"
    rc, res = _run_verdict(tmp_path, "aborted_outcome_finalize", summary=_write(tmp_path / "s2.json", dict(summary, outcome="aborted")),
                           calls=_write(tmp_path / "c.json", calls), sink=_write(tmp_path / "k.jsonl", sink),
                           control=_write(tmp_path / "ctl.json", {"rethrown": False, "sink_reachable": True}))
    assert rc == 0 and res["verdict"] == "PASS", res


def test_wrappers_for_the_new_scenarios(tmp_path):
    for scenario, needle in (("foreign_timeout_interruption", "HARNESS.outer.timeout(time: 2, unit: 'SECONDS')"),
                             ("inner_assemble_timeout", "readTrusted:slow:"),
                             ("inner_recover_timeout", "unstash:slow:")):
        out = tmp_path / f"{scenario}.groovy"
        build_functions.build(PORTAL, scenario, out, None)
        text = out.read_text(encoding="utf-8")
        assert needle in text, (scenario, needle)
        assert f"scenario: {scenario}" in text
