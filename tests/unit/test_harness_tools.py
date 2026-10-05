"""tests/jenkins/harness — build_functions.py · fixture.py · harness_verdict.py · scenarios.json (2026-10-04, Astra 3차 §5 · 4차 §2·§3).

고정하는 것
  - build_functions.py 는 Jenkinsfile_portal 의 `pipeline {` 앞 함수부를 **글자 그대로** 잘라내고(해시 기록) wrapper 만 덧붙인다.
    wrapper 는 운영 소스에 없다 — 운영 Jenkinsfile 에는 장애 주입 토큰이 없어야 한다.
  - fixture.py 는 corpus 입력을 복사하고 manifest 를 현재 빌드(job/number/url)와 시험 request 로 다시 만든다.
  - harness_verdict.py 는 기대/관측 대조로 PASS · FAIL · PARTIAL(관측 부족) 을 나누고, 관측이 없으면 PASS 로 두지 않는다.
  - scenarios.json 의 이름 집합은 세 도구가 같은 것을 쓴다.
  - 2026-10-05 (8차): Tier 2(BOUNDED) · Script Approval 실측 시나리오는 없다. gather_limit_preserve 가 실제 scripts/run_gather.sh 를
    가짜 ansible-playbook 과 시험 한계로 실행하는 준비물(fixture stub_gather)과 판정(gather_run · limit_reason)을 고정한다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
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
        assert (REPO / "tests" / "fixtures" / "finalize_corpus" / sc["case"]).is_dir(), f"{name}: corpus case {sc['case']} 없음"
        assert "expect" in sc
        # 8차 R3: Tier 2 · 승인 실측 키는 남지 않는다
        assert not ({"bounded", "probe_approvals"} & set(sc)), name


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
               "source": "stash", "unrecovered": [], "damage": [], "recovery_limited": False, "by_origin": {"output": 3, "checkpoint": 0, "synthetic": 0},
               "warnings": [], "callback": {"attempted": True, "delivered": True, "http_code": 200, "attempts": 1}}
    sink = json.dumps({"method": "POST", "status_sent": 200, "ok": True, "body_sha256": sha}) + "\n"
    preserve = {"archived": True, "stashed": True, "deleted": True}
    control = {"sink_reachable": True, "rethrown": False}
    rc, res = _run_verdict(tmp_path, "normal_success", summary=_write(tmp_path / "s.json", summary), body=str(body),
                           calls=_write(tmp_path / "c.json", ["archiveArtifacts", "stash", "unstash"]), sink=_write(tmp_path / "k.jsonl", sink),
                           preserve=_write(tmp_path / "p.json", preserve), control=_write(tmp_path / "ctl.json", control))
    assert rc == 0 and res["verdict"] == "PASS" and res["problems"] == []
    # FAIL: unstable 이 호출됐고 archive 가 실패했다
    rc, res = _run_verdict(tmp_path, "normal_success", summary=_write(tmp_path / "s.json", summary), body=str(body),
                           calls=_write(tmp_path / "c2.json", ["unstable:[결과 보존] 보관(archive)에 실패해 전달(stash)로만 넘겼습니다."]), sink=_write(tmp_path / "k.jsonl", sink),
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



# ── 2026-10-04 검토 C5 · 8차 R3 — interruption 시나리오 ─────────────────────────────────────────
def test_interruption_scenarios_have_no_inner_bounds_and_are_rethrown(tmp_path):
    names = set(SCENARIOS)
    assert {"recover_slow", "outer_timeout", "foreign_timeout_interruption", "user_abort", "aborted_outcome_finalize",
            "gather_limit_preserve"} <= names
    for gone in ("inner_recover_timeout", "inner_assemble_timeout", "inner_archive_timeout", "inner_stash_timeout",
                 "inner_layer_a_read_timeout", "inner_body_timeout", "sandbox_probe"):
        assert gone not in names and gone not in build_functions.SCENARIOS, gone
    for n in ("archive_slow", "layer_a_read_slow", "recover_slow"):
        assert SCENARIOS[n]["expect"]["rethrown"] is False and SCENARIOS[n]["slow_seconds"] >= 45, n
    assert SCENARIOS["user_abort"]["jenkins_result"] == "ABORTED" and SCENARIOS["user_abort"]["expect_interruption"]
    assert SCENARIOS["aborted_outcome_finalize"]["outcome"] == "aborted" and SCENARIOS["aborted_outcome_finalize"]["set_result"] == "ABORTED"
    assert SCENARIOS["aborted_outcome_finalize"]["expect"]["sink_posts_max"] == 1, "ABORTED 빌드는 Callback 1회만 시도"
    assert SCENARIOS["foreign_timeout_interruption"]["expect"]["rethrown"] is True
    # foreign timeout: rethrown is the expectation; swallowing it is a FAIL
    rc, res = _run_verdict(tmp_path, "foreign_timeout_interruption", control=_write(tmp_path / "c3.json", {"rethrown": True, "sink_reachable": True}),
                           sink=_write(tmp_path / "k3.jsonl", ""))
    assert rc == 0 and res["verdict"] == "PASS"
    rc, res = _run_verdict(tmp_path, "foreign_timeout_interruption", control=_write(tmp_path / "c4.json", {"rethrown": False, "sink_reachable": True}),
                           sink=_write(tmp_path / "k4.jsonl", ""))
    assert rc == 1 and res["verdict"] == "FAIL", "다른 timeout 을 삼켰다면 FAIL"
    # 8차: 승인 기록은 판정에 쓰지 않는다 — 재전파는 그대로 관측값이다
    rc, res = _run_verdict(tmp_path, "recover_slow", control=_write(tmp_path / "c5.json", {"rethrown": True, "sink_reachable": True, "approvals": {}}),
                           sink=_write(tmp_path / "k5.jsonl", ""))
    assert rc == 1 and any("rethrown" in p for p in res["problems"]), res


def test_verdict_checks_summary_outcome_for_aborted_finalize(tmp_path):
    summary = {"accepted": 3, "lines": 3, "kept": 3, "filled": 0, "outcome": "completed", "layerA": "ok", "layerB": "skipped", "source": "stash",
               "unrecovered": [], "damage": [], "by_origin": {"output": 3, "checkpoint": 0, "synthetic": 0}, "warnings": [],
               "callback": {"attempted": True, "delivered": True, "http_code": 200, "attempts": 1}}
    sink = json.dumps({"method": "POST", "status_sent": 200, "ok": True, "body_sha256": "x"}) + "\n"
    calls = ["unstable:[마무리] 전송은 했지만 확인할 것이 있습니다 — 위의 [경고] 줄 참조 (outcome_aborted)"]
    rc, res = _run_verdict(tmp_path, "aborted_outcome_finalize", summary=_write(tmp_path / "s.json", summary),
                           calls=_write(tmp_path / "c.json", calls), sink=_write(tmp_path / "k.jsonl", sink),
                           control=_write(tmp_path / "ctl.json", {"rethrown": False, "sink_reachable": True}))
    assert rc == 1 and any(c["name"] == "outcome" and not c["ok"] for c in res["checks"]), "outcome=completed 는 aborted 사후 경로가 아니다"
    rc, res = _run_verdict(tmp_path, "aborted_outcome_finalize", summary=_write(tmp_path / "s2.json", dict(summary, outcome="aborted", warnings=["outcome_aborted"])),
                           calls=_write(tmp_path / "c.json", calls), sink=_write(tmp_path / "k.jsonl", sink),
                           control=_write(tmp_path / "ctl.json", {"rethrown": False, "sink_reachable": True}))
    assert rc == 0 and res["verdict"] == "PASS", res


def test_wrappers_for_the_new_scenarios(tmp_path):
    for scenario, needle in (("foreign_timeout_interruption", "HARNESS.outer.timeout(time: 2, unit: 'SECONDS')"),
                             ("recover_slow", "unstash:slow:"),
                             ("archive_slow", "archiveArtifacts:slow:"),
                             ("layer_a_read_slow", "readFile:slow:")):
        out = tmp_path / f"{scenario}.groovy"
        build_functions.build(PORTAL, scenario, out, None)
        text = out.read_text(encoding="utf-8")
        assert needle in text, (scenario, needle)
        assert f"scenario: {scenario}" in text
    for gone in ("__SLOW_STASH__", "__SLOW_READTRUSTED__", "__SLOW_WRITEFILE_BODY__", "seBounded", "slowBodyDone"):
        assert gone not in build_functions.WRAPPERS, gone


def test_layer_a_fault_injection_targets_the_runtime_label(tmp_path):
    """결과 정리(Layer A) 실패 주입은 운영 sh 의 label 로 고른다 — 8차 R7 에서 바뀐 label 과 같은 글자여야 주입이 걸린다."""
    src = PORTAL.read_text(encoding="utf-8")
    assert f"label: '{build_functions.LAYER_A_LABEL}'" in src
    out = tmp_path / "laf.groovy"
    build_functions.build(PORTAL, "layer_a_fail", out, None)
    text = out.read_text(encoding="utf-8")
    assert f"m.label == '{build_functions.LAYER_A_LABEL}'" in text and "'layer_a_fail'" in text
    # 운영 함수부에 label 이 없으면 생성 자체를 거부한다(주입이 조용히 빠지지 않게)
    broken = tmp_path / "Jenkinsfile_portal"
    broken.write_text(src.replace(f"label: '{build_functions.LAYER_A_LABEL}'", "label: 'something else'"), encoding="utf-8")
    with pytest.raises(SystemExit):
        build_functions.build(broken, "layer_a_fail", tmp_path / "x.groovy", None)


@pytest.mark.source_text   # jenkins/jobs/ 는 main 전용 — production tree overlay(G14)에는 없다
def test_harness_pipeline_has_no_tier2_and_runs_the_real_run_gather():
    jf = (HARNESS / "Jenkinsfile_harness").read_text(encoding="utf-8")
    for gone in ("BOUNDED", "seHarnessProbeNode", "seHarnessProbeCauses", "probe_approvals", "preserve_rethrown", "getEnclosingBlocks"):
        assert gone not in jf.split("\n", 15)[-1], gone
    assert 'bash "\\${WORKSPACE}/scripts/run_gather.sh"' in jf and "lib.seGatherOutcome(grc, run, 'gather_limit')" in jf
    assert "scripts/run_gather.sh scripts/env_guard.sh" in jf, "checkout 모드도 run_gather.sh · env_guard.sh 를 gather_ws 에 둔다"
    cfg = (REPO / "jenkins" / "jobs" / "clovirone-server-gather-harness" / "config.xml").read_text(encoding="utf-8")
    assert "<name>BOUNDED</name>" not in cfg


def _fixture_args(tmp_path, scenario, ws):
    return ["--scenarios", str(HARNESS / "scenarios.json"), "--scenario", scenario, "--corpus", str(REPO / "tests/fixtures/finalize_corpus"),
            "--workspace", str(ws), "--job", "clovirone-cicd/clovirone-server-gather-harness", "--number", "88", "--url", "https://j/x/88/",
            "--loc", "git", "--deployment-env", "harness", "--event-uuid", "harness-88", "--callback-url", "http://127.0.0.1:18080",
            "--out", str(tmp_path / "state.json")]


def test_fixture_stub_gather_prepares_a_fake_venv_and_no_gather_output(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "gather_output.json").write_text("stale\n", encoding="utf-8")
    (ws / "gather_run.json").write_text("{}", encoding="utf-8")
    assert fixture.main(_fixture_args(tmp_path, "gather_limit_preserve", ws)) == 0
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    sg = state["stub_gather"]
    assert sg["finish"] == 2 and sg["limit_sec"] == 8 and sg["hosts"] == 3 and state["outcome"] == "interrupted_unknown"
    assert not (ws / "gather_output.json").exists() and not (ws / "gather_run.json").exists(), "수집 결과는 실제 실행이 만든다"
    assert state["files_copied"] == []
    stub = tmp_path / "harness_stub"
    lines = (stub / "output.jsonl").read_text(encoding="utf-8").splitlines()
    corpus = (REPO / "tests/fixtures/finalize_corpus/01_normal/gather_output.json").read_text(encoding="utf-8").splitlines()
    assert lines == corpus[:2]
    act = (stub / "venv" / "bin" / "activate").read_text(encoding="utf-8")
    assert "VIRTUAL_ENV=" in act and "/bin:$PATH" in act
    ap = (stub / "venv" / "bin" / "ansible-playbook").read_text(encoding="utf-8")
    assert "ANSIBLE_JSON_OUTPUT_FILE" in ap and "exec sleep 600" in ap
    assert Path(sg["venv"]) == (stub / "venv").resolve() and Path(sg["inventory"]).is_file()


@pytest.mark.skipif(not sys.platform.startswith("linux") or shutil.which("bash") is None or shutil.which("timeout") is None,
                    reason="Linux bash · coreutils timeout 이 필요하다 (CI Runner · WSL 에서 실행)")
def test_stub_gather_runs_the_real_run_gather_to_its_limit_and_layer_a_fills_only_the_unfinished(tmp_path):
    """Jenkinsfile_harness 의 stub_gather 단계를 로컬에서 그대로 — 실제 run_gather.sh 가 시험 한계에 닿아 INT 로 멈추고(rc 124 · timed_out),
    결과 정리(Layer A)가 끝난 2대는 수집 결과 그대로, 끝나지 않은 1대만 실패 결과로 채운다."""
    ws = tmp_path / "gather_ws"
    (ws / "scripts").mkdir(parents=True)
    for f in ("run_gather.sh", "env_guard.sh", "activate_ansible_venv.sh", "finalize_gather_output.py"):
        shutil.copy2(REPO / "scripts" / f, ws / "scripts" / f)
    shutil.copytree(REPO / "common" / "vars", ws / "common" / "vars")
    shutil.copytree(REPO / "common" / "tasks" / "normalize", ws / "common" / "tasks" / "normalize")
    assert fixture.main(_fixture_args(tmp_path, "gather_limit_preserve", ws)) == 0
    sg = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["stub_gather"]
    limit = 2   # 시나리오 값(8 s)보다 줄여 빨리 끝낸다 — run_gather.sh 의 정상 인자다
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SE_", "ANSIBLE_", "ADDON_"))}
    env.update({"WORKSPACE": str(ws), "SE_ANSIBLE_VENV": sg["venv"], "SE_HARNESS_STUB_OUTPUT": sg["output"],
                "ANSIBLE_JSON_OUTPUT_FILE": str(ws / "gather_output.json"), "VAULT_PASSWORD": "harness-stub", "LC_ALL": "C.UTF-8"})
    r = subprocess.run(["bash", str(ws / "scripts" / "run_gather.sh"), sg["playbook"], sg["inventory"], "1", str(limit), "git", "false", str(sg["hosts"])],
                       env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 124, (r.returncode, r.stdout, r.stderr)
    run = json.loads((ws / "gather_run.json").read_text(encoding="utf-8"))
    assert run["rc"] == 124 and run["timed_out"] is True and run["ran_sec"] >= limit and run["limit_sec"] == limit
    assert len((ws / "gather_output.json").read_text(encoding="utf-8").splitlines()) == 2
    assert re.search(r"\[수집\] 실행 한계 2초\(2초\)에 도달해 INT 로 멈췄습니다", r.stdout), r.stdout
    fin = subprocess.run([sys.executable, str(ws / "scripts" / "finalize_gather_output.py"), "--workspace", str(ws), "--repo-root", str(ws),
                          "--outcome", "timeout", "--limit-reason", "gather_limit"], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert fin.returncode == 0, fin.stderr
    report = json.loads((ws / "gather_finalize_report.json").read_text(encoding="utf-8"))
    assert report["by_origin"] == {"output": 2, "checkpoint": 0, "synthetic": 1} and report["filled"] == 1, report
    final = [json.loads(x) for x in (ws / "gather_final.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    finished = {json.loads(x)["ip"] for x in Path(sg["output"]).read_text(encoding="utf-8").splitlines() if x.strip()}
    unfinished = [e for e in final if e["ip"] not in finished]
    assert len(final) == 3 and len(finished) == 2 and len(unfinished) == 1
    assert unfinished[0]["status"] == "failed" and unfinished[0]["diagnosis"]["details"].get("limit_reason") == "gather_limit"
    assert all(e["status"] != "failed" for e in final if e["ip"] in finished), "끝난 대상은 수집 결과 그대로"


def test_verdict_gather_limit_preserve(tmp_path):
    body = tmp_path / "callback_body.json"
    body.write_bytes(b'{"loc":"git","gatherInfoJson":[]}')
    import hashlib
    sha = hashlib.sha256(body.read_bytes()).hexdigest()
    summary = {"accepted": 3, "lines": 3, "kept": 2, "filled": 1, "outcome": "timeout", "limit_reason": "gather_limit",
               "layerA": "ok", "layerB": "skipped", "source": "stash", "unrecovered": [], "damage": [],
               "by_origin": {"output": 2, "checkpoint": 0, "synthetic": 1}, "warnings": ["filled", "outcome_timeout"],
               "gather_run": {"rc": 124, "timed_out": True, "limit_sec": 8, "ran_sec": 8},
               "callback": {"attempted": True, "delivered": True, "http_code": 200, "attempts": 1}}
    sink = json.dumps({"method": "POST", "status_sent": 200, "ok": True, "body_sha256": sha}) + "\n"
    files = dict(body=str(body), calls=_write(tmp_path / "c.json", ["unstable:[결과 확인] 전송은 했지만 확인할 것이 있습니다. (filled, outcome_timeout)"]),
                 sink=_write(tmp_path / "k.jsonl", sink), preserve=_write(tmp_path / "p.json", {"archived": True, "stashed": True, "deleted": True}),
                 control=_write(tmp_path / "ctl.json", {"sink_reachable": True, "rethrown": False}))
    rc, res = _run_verdict(tmp_path, "gather_limit_preserve", summary=_write(tmp_path / "s.json", summary), **files)
    assert rc == 0 and res["verdict"] == "PASS", res["problems"]
    # 한계에 닿지 않았다면(정상 종료 rc 0) 이 시나리오의 증거가 아니다
    rc, res = _run_verdict(tmp_path, "gather_limit_preserve",
                           summary=_write(tmp_path / "s2.json", dict(summary, gather_run={"rc": 0, "timed_out": False, "limit_sec": 8, "ran_sec": 3})), **files)
    assert rc == 1 and {"gather_run.rc", "gather_run.timed_out", "gather_run.ran_sec>=limit_sec"} <= {c["name"] for c in res["checks"] if not c["ok"]}
    # 실행 기록이 없으면 PASS 로 두지 않는다
    rc, res = _run_verdict(tmp_path, "gather_limit_preserve", summary=_write(tmp_path / "s3.json", {k: v for k, v in summary.items() if k != "gather_run"}), **files)
    assert rc == 2 and any("gather_run" in p for p in res["partial"])


def test_verdict_prefers_the_summary_callback_and_requires_the_sink_to_agree(tmp_path):
    """2026-10-05 (F09 · F13): 전송 여부는 finalize_summary.callback 이 기록이다. 수신 기록이 있으면 그 기록에 2xx 가 있어야 전달로 본다
    (요약이 거짓으로 delivered=true 를 적어도 통과하지 못한다). 경고는 문장이 아니라 warnings 코드로 판정한다."""
    base = {"accepted": 3, "lines": 3, "kept": 3, "filled": 0, "outcome": "completed", "layerA": "ok", "layerB": "skipped", "source": "stash",
            "unrecovered": [], "damage": [], "by_origin": {"output": 3, "checkpoint": 0, "synthetic": 0}, "warnings": []}
    claimed = dict(base, callback={"attempted": True, "delivered": True, "http_code": 200, "attempts": 1})
    sink_500 = json.dumps({"method": "POST", "status_sent": 500, "ok": False, "body_sha256": "x"}) + "\n"
    obs = harness_verdict.observe(claimed, None, [], [json.loads(sink_500)], None, {"rethrown": False})
    assert obs["delivered"] is False, "수신 기록에 2xx 가 없으면 요약의 delivered=true 를 믿지 않는다"
    obs = harness_verdict.observe(claimed, None, [], None, None, {"rethrown": False})
    assert obs["delivered"] is True and obs["warnings"] == [] and obs["callback"]["http_code"] == 200
    # sink_5xx: warnings 코드 + 새 문구 + delivered=false
    failed = dict(base, warnings=["callback_failed"], callback={"attempted": True, "delivered": False, "http_code": 500, "attempts": 3})
    rc, res = _run_verdict(tmp_path, "sink_5xx", summary=_write(tmp_path / "s.json", failed),
                           calls=_write(tmp_path / "c.json", ["unstable:[마무리] Portal 전송 실패 — 보내려던 본문은 결과 파일 callback_body.json"]),
                           sink=_write(tmp_path / "k.jsonl", sink_500 * 3), control=_write(tmp_path / "ctl.json", {"rethrown": False, "sink_reachable": True}))
    assert any(c["name"] == "warnings_include:callback_failed" and c["ok"] for c in res["checks"]), res
    assert any(c["name"] == "delivered" and c["ok"] for c in res["checks"]), res
    # 이전 형식 요약(warnings 없음)은 경고 판정을 PARTIAL 로 남긴다 — 통과로 치지 않는다
    old = {k: v for k, v in failed.items() if k != "warnings"}
    rc, res = _run_verdict(tmp_path, "sink_5xx", summary=_write(tmp_path / "s2.json", old),
                           calls=_write(tmp_path / "c2.json", ["unstable:[Finalize] Callback 전송 실패 — artifact callback_body.json 참조"]),
                           sink=_write(tmp_path / "k2.jsonl", sink_500 * 3), control=_write(tmp_path / "ctl2.json", {"rethrown": False, "sink_reachable": True}))
    assert any("warnings_include" in p for p in res["partial"]), res

