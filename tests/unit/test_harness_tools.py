"""tests/jenkins/harness — build_functions.py · fixture.py · harness_verdict.py · scenarios.json (2026-10-04, Astra 3차 §5 · 4차 §2·§3).

고정하는 것
  - build_functions.py 는 Jenkinsfile_portal 의 `pipeline {` 앞 함수부를 **글자 그대로** 잘라내고(해시 기록) wrapper 만 덧붙인다.
    wrapper 는 운영 소스에 없다 — 운영 Jenkinsfile 에는 장애 주입 토큰이 없어야 한다.
  - fixture.py 는 corpus 입력을 복사하고 manifest 를 현재 빌드(job/number/url)와 시험 request 로 다시 만든다.
  - harness_verdict.py 는 기대/관측 대조로 PASS · FAIL · PARTIAL(관측 부족) 을 나누고, 관측이 없으면 PASS 로 두지 않는다.
  - scenarios.json 의 이름 집합은 세 도구가 같은 것을 쓴다.
  - 2026-10-05 (8차): Tier 2(BOUNDED) · Script Approval 실측 시나리오는 없다.
  - 2026-10-06 (9차): gather_stage 시나리오(gather_limit_preserve · infra_resume · infra_wait_expired · resume_impossible · gather_wait_abort)는
    운영 함수 seGatherStage 를 시험 상수로 그대로 실행한다. 준비물(fixture gather_stage: 가짜 ansible = stub_ansible.py · 시도별 계획 · 대상별 결과 줄),
    실행 기반 흉내 wrapper(node · nodesByLabel · retry · ws · checkout · withCredentials), 판정(gather · infra · body_reasons)을 고정하고,
    가짜 ansible 과 실제 run_gather.sh · gather_state.py 의 연결(남은 대상만 받기 · 한계 도달)을 Linux 에서 실제로 돌린다.
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
                    "def readTrusted(String path)", "def sh(Map m)", "def unstable(String msg)", "def httpRequest(Map m)",
                    "def node(String target, Closure body)", "def nodesByLabel(Map m)", "def retry(Map m, Closure body)",
                    "def ws(String path, Closure body)", "def checkout(Object s)", "def withCredentials(List creds, Closure body)",
                    "def writeFile(Map m)", "def fileExists(String f)", "def deleteDir()", "def seHarnessFault(String op, String target)"):
        assert wrapper in text, wrapper
    for name in ("seGatherStage", "seGatherLoop", "seWithNode", "seAttempt", "seAttemptBody", "seQueueTimer", "seInfraClose"):
        assert name in meta["defs"], name
    # gather 가 없는 시나리오에서는 실행 기반 wrapper 가 실제 step 으로 그대로 넘긴다
    for passthrough in ("if (HARNESS.gather == null) { return HARNESS.outer.node(target) { body() } }",
                        "if (HARNESS.gather == null) { return HARNESS.outer.nodesByLabel(m) }",
                        "if (m.conditions == null || (HARNESS.gather == null && !HARNESS.faults)) { return HARNESS.outer.retry(m) { body() } }",
                        "if (HARNESS.gather == null) { return HARNESS.outer.ws(path) { body() } }"):
        assert passthrough in text, passthrough
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
    # FL-F06 (2026-10-10): 빌드 인스턴스 표식(nonce)이 manifest 에 들어가고 state.build_nonce 와 같다 — Jenkinsfile_harness 가 SE_BUILD_NONCE 로 넘긴다
    nonce = m["build"].pop("nonce")
    assert nonce.startswith("harness-77-") and m["build"] == {"job": "clovirone-cicd/clovirone-server-gather-harness", "number": "77", "url": "https://j/x/77/"}
    assert m["request"]["callbackUrl"] == "http://10.0.0.5:18080" and m["request"]["eventUuid"] == "harness-77" and m["request"]["loc"] == "git"
    assert m["ips"] == ["198.51.100.11", "198.51.100.12", "198.51.100.13"] and m["channel"] == "os"
    assert (ws / "gather_output.json").is_file() and (ws / "gather_progress.jsonl").is_file()
    state = json.loads(out.read_text(encoding="utf-8"))
    assert state["run_preserve"] is True and state["outcome"] == "completed" and state["case"] == "01_normal"
    assert state["build_nonce"] == nonce


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
    assert "lib.seGatherStage(C)" in jf and "Map C = lib.seConstants() + (gsx.constants ?: [:])" in jf, "운영 함수를 시험 상수로 그대로 실행한다"
    assert "seGatherOutcome" not in jf and 'scripts/run_gather.sh"' not in jf, "Harness 가 run_gather.sh 를 따로 부르지 않는다 — 운영 함수가 부른다"
    assert "scripts/run_gather.sh scripts/env_guard.sh scripts/gather_state.py gather_ws/scripts/" in jf, \
        "checkout 모드도 run_gather.sh · env_guard.sh · gather_state.py 를 gather_ws(시도의 저장소 사본)에 둔다"
    assert "ADDON_REPO_URL=" in jf and "SE_ANSIBLE_VENV=${gsx.venv}" in jf and "SE_HARNESS_STUB_DIR=${gsx.stub_dir}" in jf
    assert "if (!fx.gather_stage) {" in jf, "gather_stage 의 보존은 운영 함수(마지막 시도)가 한다"
    assert 'endsWith("/${env.JOB_BASE_NAME}-${env.BUILD_NUMBER}")' in jf and "rm -rf '${hs.ws_path}' '${hs.ws_path}@tmp'" in jf, \
        "운영 Runner 에 시험 작업 폴더를 남기지 않는다(이 빌드의 것만)"
    assert "--received gather_received.jsonl" in jf and "--fixture fixture_state.json" in jf
    cfg = (REPO / "jenkins" / "jobs" / "clovirone-server-gather-harness" / "config.xml").read_text(encoding="utf-8")
    assert "<name>BOUNDED</name>" not in cfg


def _fixture_args(tmp_path, scenario, ws):
    return ["--scenarios", str(HARNESS / "scenarios.json"), "--scenario", scenario, "--corpus", str(REPO / "tests/fixtures/finalize_corpus"),
            "--workspace", str(ws), "--job", "clovirone-cicd/clovirone-server-gather-harness", "--number", "88", "--url", "https://j/x/88/",
            "--loc", "git", "--deployment-env", "harness", "--event-uuid", "harness-88", "--callback-url", "http://127.0.0.1:18080",
            "--out", str(tmp_path / "state.json")]


def test_fixture_gather_stage_prepares_the_stub_plan_and_no_gather_output(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "gather_output.json").write_text("stale\n", encoding="utf-8")
    (ws / "gather_run.json").write_text("{}", encoding="utf-8")
    assert fixture.main(_fixture_args(tmp_path, "infra_resume", ws)) == 0
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    gs = state["gather_stage"]
    assert state["run_preserve"] is False and state["outcome"] == "interrupted_unknown" and state["files_copied"] == []
    assert state["ips"] == [f"192.0.2.{10 + i}" for i in range(10)] and gs["ips"] == state["ips"] and gs["hosts"] == 10
    assert not (ws / "gather_output.json").exists() and not (ws / "gather_run.json").exists(), "수집 결과는 실제 실행이 만든다"
    assert gs["constants"]["INFRA_WAIT"] == 900 and gs["finalize_delay"] == 15 and gs["attempts"][0]["agent_lost"] is True
    stub = tmp_path / "harness_stub"
    tmpl = [json.loads(x) for x in (stub / "templates.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [t["ip"] for t in tmpl] == state["ips"] and all(len(t) == 13 and t["target_type"] == "os" for t in tmpl)
    plan = json.loads((stub / "plan.json").read_text(encoding="utf-8"))
    assert plan["ips"] == state["ips"] and plan["attempts"] == SCENARIOS["infra_resume"]["gather_stage"]["attempts"]
    assert (stub / "stub_ansible.py").read_text(encoding="utf-8") == (HARNESS / "stub_ansible.py").read_text(encoding="utf-8")
    act = (stub / "venv" / "bin" / "activate").read_text(encoding="utf-8")
    assert "VIRTUAL_ENV=" in act and "/bin:$PATH" in act
    assert "stub_ansible.py" in (stub / "venv" / "bin" / "ansible-playbook").read_text(encoding="utf-8")
    assert (ws / "os-gather" / "inventory.sh").is_file() and (ws / "os-gather" / "site.yml").is_file(), "시도의 저장소 사본에 inventory 자리"
    assert Path(gs["venv"]) == (stub / "venv").resolve() and Path(gs["stub_dir"]) == stub.resolve()


LINUX_ONLY = pytest.mark.skipif(not sys.platform.startswith("linux") or shutil.which("bash") is None or shutil.which("timeout") is None
                                or shutil.which("flock") is None, reason="Linux bash · coreutils timeout · flock 이 필요하다 (CI Runner · WSL 에서 실행)")


def _gather_ws(tmp_path, scenario):
    ws = tmp_path / "gather_ws"
    (ws / "scripts").mkdir(parents=True)
    for f in ("run_gather.sh", "env_guard.sh", "activate_ansible_venv.sh", "finalize_gather_output.py", "gather_state.py"):
        shutil.copy2(REPO / "scripts" / f, ws / "scripts" / f)
    shutil.copytree(REPO / "common" / "vars", ws / "common" / "vars")
    shutil.copytree(REPO / "common" / "tasks" / "normalize", ws / "common" / "tasks" / "normalize")
    assert fixture.main(_fixture_args(tmp_path, scenario, ws)) == 0
    gs = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["gather_stage"]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SE_", "ANSIBLE_", "ADDON_"))}
    env.update({"WORKSPACE": str(ws), "SE_ANSIBLE_VENV": gs["venv"], "SE_HARNESS_STUB_DIR": gs["stub_dir"], "VAULT_PASSWORD": "harness-stub",
                "ANSIBLE_JSON_OUTPUT_FILE": str(ws / "gather_output.json"), "ANSIBLE_JSON_PROGRESS_FILE": str(ws / "gather_progress.jsonl"),
                "ANSIBLE_JSON_CHECKPOINT_FILE": str(ws / "gather_checkpoint.jsonl"), "LC_ALL": "C.UTF-8"})
    return ws, gs, env


def _run_gather(ws, env, gather_max, lost="false"):
    argv = ["bash", str(ws / "scripts" / "run_gather.sh"), str(ws / "os-gather" / "site.yml"), str(ws / "os-gather" / "inventory.sh"), "git",
            "false", str(gather_max), lost]
    with open(ws.parent / "run.log", "a", encoding="utf-8") as log:
        p = subprocess.Popen(argv, env=env, stdout=log, stderr=subprocess.STDOUT)
        return p.wait(timeout=180)


@LINUX_ONLY
def test_gather_limit_stub_reaches_the_limit_and_layer_a_fills_only_the_unfinished(tmp_path):
    """gather_limit_preserve 의 시도를 로컬에서 그대로 — 실제 run_gather.sh 가 시험 한계에 닿아 INT 로 멈추고(rc 124 · gather_limit),
    결과 정리(Layer A)가 끝난 2대는 수집 결과 그대로, 끝나지 않은 1대만 실패 결과로 채운다."""
    ws, gs, env = _gather_ws(tmp_path, "gather_limit_preserve")
    rc = _run_gather(ws, env, 2)
    assert rc == 124, (ws.parent / "run.log").read_text(encoding="utf-8")
    run = json.loads((ws / "gather_run.json").read_text(encoding="utf-8"))
    assert run["rc"] == 124 and run["timed_out"] is True and run["ran_sec"] >= 2 and run["limit_sec"] == 2 and run["state"] == "gather_limit"
    assert len((ws / "gather_output.json").read_text(encoding="utf-8").splitlines()) == 2
    received = [json.loads(x) for x in (Path(gs["stub_dir"]) / "received.jsonl").read_text(encoding="utf-8").splitlines()]
    assert received == [{"attempt": 1, "hosts": gs["ips"]}]
    fin = subprocess.run([sys.executable, str(ws / "scripts" / "finalize_gather_output.py"), "--workspace", str(ws), "--repo-root", str(ws),
                          "--outcome", "timeout", "--limit-reason", "gather_limit"], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert fin.returncode == 0, fin.stderr
    report = json.loads((ws / "gather_finalize_report.json").read_text(encoding="utf-8"))
    assert report["by_origin"] == {"output": 2, "checkpoint": 0, "synthetic": 1} and report["filled"] == 1, report


@LINUX_ONLY
def test_infra_resume_stub_regathers_only_the_unfinished_hosts(tmp_path):
    """infra_resume 의 두 시도를 로컬에서 그대로 — 1번째 시도가 4대 결과 · 1대 Precheck 실패 · 1대 CHECKPOINT 만 남기고 수집 셸이 끝 기록 없이
    사라진다. 2번째 시도(이전 시도 중 Agent 끊김 보고)는 결과가 확정되지 않은 5대만 받는다(CHECKPOINT 만 있던 대상 포함, Precheck 실패 대상 제외)."""
    ws, gs, env = _gather_ws(tmp_path, "infra_resume")
    for name in ("gather_manifest.json",):
        assert (ws / name).is_file()
    rc = _run_gather(ws, env, 900)
    assert rc == -9, (ws.parent / "run.log").read_text(encoding="utf-8")
    deadline = __import__("time").monotonic() + 30
    while subprocess.run(["flock", "-n", str(ws / ".gather.lock"), "true"]).returncode != 0:
        assert __import__("time").monotonic() < deadline, "잠금이 풀리지 않았다"
        __import__("time").sleep(0.2)
    rc = _run_gather(ws, env, 900, lost="true")
    assert rc == 0, (ws.parent / "run.log").read_text(encoding="utf-8")
    ips = gs["ips"]
    received = [json.loads(x)["hosts"] for x in (Path(gs["stub_dir"]) / "received.jsonl").read_text(encoding="utf-8").splitlines()]
    assert received == [ips, ips[5:]]
    run = json.loads((ws / "gather_run.json").read_text(encoding="utf-8"))
    assert [a["state"] for a in run["attempts"]] == ["agent_disconnect", "completed"]
    assert run["attempts"][1]["limit_sec"] == 900 - run["attempts"][0]["exec_sec"]
    fin = subprocess.run([sys.executable, str(ws / "scripts" / "finalize_gather_output.py"), "--workspace", str(ws), "--repo-root", str(ws),
                          "--outcome", "completed"], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert fin.returncode == 0, fin.stderr
    report = json.loads((ws / "gather_finalize_report.json").read_text(encoding="utf-8"))
    assert report["by_origin"] == {"output": 9, "checkpoint": 0, "synthetic": 1}, report
    final = {json.loads(x)["ip"]: json.loads(x) for x in (ws / "gather_final.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()}
    assert final[ips[4]]["diagnosis"]["failure_stage"] == "reachable", "Precheck 실패 대상은 그 진단 그대로"


def _gather_summary(states, limits, execs, gmax=900, infra=None, **extra):
    attempts = [{"state": st, "limit_sec": lim, "exec_sec": ex} for st, lim, ex in zip(states, limits, execs)]
    base = {"accepted": 10, "lines": 10, "kept": 9, "filled": 1, "outcome": "completed", "layerA": "ok", "layerB": "skipped", "source": "stash",
            "unrecovered": [], "damage": [], "by_origin": {"output": 9, "checkpoint": 0, "synthetic": 1}, "warnings": ["filled"],
            "gather_run": {"gather_max_sec": gmax, "attempts": attempts, "rc": 0, "timed_out": False, "limit_sec": limits[-1], "ran_sec": sum(execs)},
            "infra": infra or {"budget_sec": 900, "used_sec": 42, "expired": False,
                               "episodes": [{"reason": "Runner 배정 대기", "result": "acquired", "sec": 0},
                                            {"reason": "같은 Runner(r3) 복구 대기", "result": "acquired", "sec": 26},
                                            {"reason": "결과 처리 노드", "result": "acquired", "sec": 16}]},
            "callback": {"attempted": True, "delivered": True, "http_code": 200, "attempts": 1}}
    base.update(extra)
    return base


def test_verdict_gather_stage_checks_received_states_limits_pinning_and_infra(tmp_path):
    import hashlib
    ips = [f"192.0.2.{10 + i}" for i in range(10)]
    body = tmp_path / "callback_body.json"
    body.write_bytes(b'{"loc":"git","gatherInfoJson":[]}')
    sha = hashlib.sha256(body.read_bytes()).hexdigest()
    received = _write(tmp_path / "r.jsonl", json.dumps({"attempt": 1, "hosts": ips}) + "\n" + json.dumps({"attempt": 2, "hosts": ips[5:]}) + "\n")
    fixture_state = _write(tmp_path / "fx.json", {"ips": ips})
    calls = ["node:harness-runner-label:delay:0", "retry:agent_lost", "node:SKHynix-Jenkins-Runner03:delay:20", "checkout:copy",
             "node:built-in:delay:15", "unstable:[결과 확인] 전송은 했지만 확인할 것이 있습니다. (filled)"]
    files = dict(body=str(body), calls=_write(tmp_path / "c.json", calls),
                 sink=_write(tmp_path / "k.jsonl", json.dumps({"method": "POST", "status_sent": 200, "ok": True, "body_sha256": sha}) + "\n"),
                 preserve=_write(tmp_path / "p.json", {"archived": True, "stashed": True, "deleted": True}),
                 control=_write(tmp_path / "ctl.json", {"sink_reachable": True, "rethrown": False, "gather": {"outcome": "completed"}}),
                 received=received, fixture=fixture_state)
    good = _gather_summary(["agent_disconnect", "completed"], [900, 870], [30, 12])
    rc, res = _run_verdict(tmp_path, "infra_resume", summary=_write(tmp_path / "s.json", good), **files)
    assert rc == 0 and res["verdict"] == "PASS", res["problems"] + res["partial"]
    # 두 번째 시도의 한계가 앞 시도의 실행 시간을 빼지 않았다면 FAIL
    bad = _gather_summary(["agent_disconnect", "completed"], [900, 900], [30, 12])
    rc, res = _run_verdict(tmp_path, "infra_resume", summary=_write(tmp_path / "s2.json", bad), **files)
    assert rc == 1 and any(c["name"] == "gather.limit_chain" and not c["ok"] for c in res["checks"])
    # 끝난 대상을 다시 수집했다면 FAIL
    files2 = dict(files, received=_write(tmp_path / "r2.jsonl", json.dumps({"attempt": 1, "hosts": ips}) + "\n" + json.dumps({"attempt": 2, "hosts": ips}) + "\n"))
    rc, res = _run_verdict(tmp_path, "infra_resume", summary=_write(tmp_path / "s3.json", good), **files2)
    assert rc == 1 and any(c["name"] == "gather.received" and not c["ok"] for c in res["checks"])
    # 다른 Runner 로 옮겼다면 FAIL
    files3 = dict(files, calls=_write(tmp_path / "c3.json", [c.replace("node:SKHynix-Jenkins-Runner03", "node:harness-runner-label") for c in calls]))
    rc, res = _run_verdict(tmp_path, "infra_resume", summary=_write(tmp_path / "s4.json", good), **files3)
    assert rc == 1 and any(c["name"] == "gather.pinned" and not c["ok"] for c in res["checks"])
    # 같은 Runner 를 기다린 시간이 짧다면(흉내 낸 20초를 대기로 세지 않았다면) FAIL
    short = _gather_summary(["agent_disconnect", "completed"], [900, 870], [30, 12],
                            infra={"budget_sec": 900, "used_sec": 3, "expired": False, "episodes": [{"reason": "같은 Runner(r3) 복구 대기", "result": "acquired", "sec": 3},
                                                                                                   {"reason": "결과 처리 노드", "result": "acquired", "sec": 16}]})
    rc, res = _run_verdict(tmp_path, "infra_resume", summary=_write(tmp_path / "s5.json", short), **files)
    assert rc == 1 and any(c["name"].startswith("infra.episode:복구 대기") and not c["ok"] for c in res["checks"])
    # 받은 대상 기록이 없으면 PASS 로 두지 않는다
    files4 = dict(files, received=str(tmp_path / "missing.jsonl"))
    rc, res = _run_verdict(tmp_path, "infra_resume", summary=_write(tmp_path / "s6.json", good), **files4)
    assert rc == 2 and any("gather.received" in p for p in res["partial"])


def test_verdict_body_reasons_use_the_catalog_sentence(tmp_path):
    import yaml
    cat = yaml.safe_load((REPO / "common/vars/failure_reasons.yml").read_text(encoding="utf-8"))["_fr_catalog"]
    infra = cat["infra_unavailable"]["default"]
    other = cat["output_build_failed"]["default"]
    env = lambda reason: {"diagnosis": {"failure_reason": reason}}
    body = tmp_path / "b.json"
    body.write_text(json.dumps({"gatherInfoJson": [env(infra), env(infra), env(None)]}, ensure_ascii=False), encoding="utf-8")
    obs = harness_verdict.observe({}, str(body), [], None, None, {})
    checks, partial = harness_verdict.check({"body_reasons": {"infra_unavailable": 2}}, obs)
    assert partial == [] and all(c["ok"] for c in checks), checks
    body.write_text(json.dumps({"gatherInfoJson": [env(other), env(infra), env(None)]}, ensure_ascii=False), encoding="utf-8")
    obs = harness_verdict.observe({}, str(body), [], None, None, {})
    checks, _ = harness_verdict.check({"body_reasons": {"infra_unavailable": 2}}, obs)
    assert not checks[0]["ok"] and checks[0]["observed"] == 1, "다른 문장(대상 측 실패)으로 보냈다면 FAIL"


def test_gather_stage_scenarios_cover_the_directive_tests():
    """9차 지시서 시험 대응 — 가짜 실행 기반 시나리오의 계획이 각 시험의 조건을 실제로 만든다."""
    r = SCENARIOS["infra_resume"]["gather_stage"]["attempts"]
    assert r[0]["agent_lost"] and r[0]["crash"] and r[0]["precheck_fail"] == [5] and r[0]["checkpoint"] == [6] and r[1]["queue_delay"] >= 20
    assert SCENARIOS["infra_resume"]["gather_stage"]["finalize_delay"] >= 15
    w = SCENARIOS["infra_wait_expired"]["gather_stage"]
    assert w["attempts"][0].get("orphan_hold") and w["attempts"][-1]["queue_delay"] > w["constants"]["INFRA_WAIT"], "대기 한도를 넘기는 대기"
    assert SCENARIOS["resume_impossible"]["gather_stage"]["attempts"][1]["remove_workspace"] is True
    ab = SCENARIOS["gather_wait_abort"]
    assert ab["jenkins_result"] == "ABORTED" and ab["expect_interruption"] and ab["gather_abort_after"] < ab["gather_stage"]["attempts"][1]["queue_delay"]
    assert "self_abort_after" not in ab, "결과 확인 단계의 취소 시나리오(user_abort)와 섞지 않는다"
    for name in ("gather_limit_preserve", "infra_resume", "infra_wait_expired", "resume_impossible", "gather_wait_abort"):
        sc = SCENARIOS[name]
        assert sc["run_preserve"] is False and "stub_gather" not in sc and "gather" in sc["expect"], name


def test_rethrow_from_the_gather_stage_does_not_cancel_the_delivery():
    """2026-10-06 (CI #27 · #29 gather_wait_abort): 수집 단계에서 다시 던진 interruption(실행 기반 대기 중 취소)은 전송을 막지 않는다 —
    결과 확인(post{always} 자리)이 뒤에서 한 번 보낸다. finalizer 밖으로 다시 던진 것만 전송 실패로 본다. rethrown_in 이 없는 옛 기록은 finalizer."""
    summary = {"accepted": 3, "lines": 3, "outcome": "aborted", "warnings": ["filled", "outcome_aborted"],
               "callback": {"attempted": True, "delivered": True, "http_code": 200, "attempts": 1}}
    sink = [{"method": "POST", "status_sent": 200, "ok": True, "body_sha256": "x"}]
    assert harness_verdict.observe(summary, None, [], sink, None, {"rethrown": True, "rethrown_in": "gather"})["delivered"] is True
    assert harness_verdict.observe(summary, None, [], sink, None, {"rethrown": True, "rethrown_in": "finalize"})["delivered"] is False
    assert harness_verdict.observe(summary, None, [], sink, None, {"rethrown": True})["delivered"] is False
    jf = (HARNESS / "Jenkinsfile_harness").read_text(encoding="utf-8")
    assert jf.count("control.rethrown_in = 'gather'") == 1 and jf.count("control.rethrown_in = 'finalize'") == 1
    assert "env.SE_HARNESS_VERDICT = (rc == 0) ? 'PASS' : ((rc == 1) ? 'FAIL' : ((rc == 2) ? 'PARTIAL' : 'ERROR'))" in jf
    assert jf.index("env.SE_HARNESS_VERDICT") < jf.index("if (rc == 1) {"), "판정 실패로 빌드가 끝나기 전에 남긴다"


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



# ── 10차 (2026-10-07) ──────────────────────────────────────────────────────────────────────────────────────

def test_fault_injection_lives_only_in_the_wrappers_and_counts_calls(tmp_path):
    """10차: 장애 주입은 wrapper 의 seHarnessFault 한 곳 — op(대상)의 n번째 호출에서 infra(실행 기반 오류 흉내) 또는 fail. 운영 함수부는 원본 그대로다."""
    out = tmp_path / "f.groovy"
    build_functions.build(PORTAL, "finalize_reentry", out, None)
    text = out.read_text(encoding="utf-8")
    wrappers = text.split("harness wrappers")[1]
    assert "HARNESS.agentLost = true" in wrappers and "HARNESS.offline = true" in wrappers
    for call in ("seHarnessFault('writeFile'", "seHarnessFault('readFile'", "seHarnessFault('fileExists'", "seHarnessFault('deleteDir'",
                 "seHarnessFault('stash'", "seHarnessFault('archiveArtifacts'", "seHarnessFault('sh'", "seHarnessFault('unstash'"):
        assert call in wrappers, call
    assert "HARNESS.finalizeDelays" in wrappers and "HARNESS.builtinCalls" in wrappers, "결과 처리 노드 진입마다 늦춘다"
    assert "hk.remove_files" in wrappers and "hk.addon_ref_to" in wrappers and "hk.remove_addon_copy" in wrappers
    functions = PORTAL.read_text(encoding="utf-8")
    functions = functions[: functions.index("\npipeline {")]
    assert "seHarnessFault" not in functions and "HARNESS" not in functions


def test_new_scenarios_declare_faults_that_hit_real_runtime_points():
    """faults 의 대상이 운영 함수가 실제로 부르는 이름이어야 주입이 걸린다(sh label · 기록 파일 이름 · stash 이름)."""
    src = PORTAL.read_text(encoding="utf-8")
    for name in build_functions.SCENARIOS:
        for f in SCENARIOS[name].get("faults") or []:
            assert f["op"] in ("writeFile", "readFile", "fileExists", "sh", "deleteDir", "stash", "archiveArtifacts", "unstash", "unarchive"), (name, f)
            # C1 (2026-10-10): interrupt = 실제 interruption 으로 끊는 실행 기반 오류, truncate = unarchive 로 받은 파일의 앞 keep 줄만(보관본 일부 회수)
            assert f.get("kind", "infra") in ("infra", "fail", "interrupt", "truncate"), (name, f)
            assert f.get("kind") != "truncate" or f["op"] == "unarchive", (name, f)
            if f["op"] == "sh":
                assert f"label: '{f['match']}'" in src, (name, f)
            elif f["op"] in ("writeFile", "readFile", "fileExists", "unarchive"):
                assert f"'{f['match']}'" in src, (name, f)
            elif f["op"] == "stash":
                assert f"name: '{f['match']}'" in src, (name, f)
    expired = SCENARIOS["finalize_reentry_expired"]
    assert expired["jenkins_result"] == "FAILURE" and expired["infra_budget_sec"] < expired["finalize_delays"][1]
    assert SCENARIOS["finalize_reentry_abort"]["jenkins_result"] == "ABORTED" and SCENARIOS["finalize_reentry_abort"]["expect_interruption"]
    assert SCENARIOS["finalize_limit_cumulative"]["slow"]["unstash"] >= 20


def test_fixture_builds_a_read_only_test_addon_repository_with_two_commits(tmp_path):
    ws = tmp_path / "gather_ws"
    r = subprocess.run([sys.executable, str(HARNESS / "fixture.py"), *_fixture_args(tmp_path, "addon_decision_transient", ws)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    st = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    addon = st["gather_stage"]["addon"]
    assert addon["url"].startswith("file://") and set(addon["commits"]) == {"A", "B"} and addon["unsupported"] is False
    bare = Path(addon["bare"])
    main = subprocess.run(["git", "-C", str(bare), "rev-parse", "refs/heads/main"], capture_output=True, text=True).stdout.strip()
    assert main == addon["commits"]["A"], "처음 main 은 A — 시험이 시도 사이에 B 로 옮긴다"
    work = tmp_path / "co"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], check=True)
    check = work / "tools" / "check_layout.py"
    assert subprocess.run([sys.executable, str(check), "addon", "--targets", "linux,windows"]).returncode == 0
    assert subprocess.run([sys.executable, str(check), "addon", "--targets", "esxi"]).returncode == 3
    assert "debug" in (work / "tasks" / "main.yml").read_text(encoding="utf-8"), "읽기 전용 — 대상에 아무것도 하지 않는다"
    assert st["gather_stage"]["node_steps"][1]["addon_ref_to"] == "B"


def test_verdict_checks_reentry_delivery_count_and_addon_commits(tmp_path):
    exp = {"sink_posts_eq": 1, "summary_present": True, "finalize": {"entries": 2, "exec_sec_before_min": 19},
           "finalize_result": {"incomplete": False}, "gather": {"addon_commits": ["A", "A"], "node_calls": 3}}
    summary = {"finalize": {"entries": 2, "exec_sec_before": 21}, "callback": {"delivered": True}}
    control = {"finalize_result": {"incomplete": False}, "gather": {"node_calls": 3, "addon": {"commits": {"A": "aaa", "B": "bbb"}}}}
    received = [{"attempt": 1, "hosts": ["x"], "addon_commit": "aaa"}, {"attempt": 2, "hosts": ["y"], "addon_commit": "aaa"}]
    obs = harness_verdict.observe(summary, None, [], [{"method": "POST", "status_sent": 200}], {}, control, received, {"ips": ["x", "y"]})
    checks, partial = harness_verdict.check(exp, obs)
    assert partial == [] and all(c["ok"] for c in checks), checks
    received[1]["addon_commit"] = "bbb"                          # 재개가 main(B)을 새로 받았다 — 결정 재사용 실패
    obs = harness_verdict.observe(summary, None, [], [{"method": "POST", "status_sent": 200}, {"method": "POST", "status_sent": 200}], {},
                                  control, received, {"ips": ["x", "y"]})
    checks, _ = harness_verdict.check(exp, obs)
    bad = {c["name"] for c in checks if not c["ok"]}
    assert {"gather.addon_commits", "sink_posts_eq"} <= bad
    none_obs = harness_verdict.observe(summary, None, [], [], {}, control, [{"hosts": [], "addon_dir": False}], {"ips": []})
    checks, _ = harness_verdict.check({"gather": {"addon_none": True}}, none_obs)
    assert all(c["ok"] for c in checks)


# ── C1 (2026-10-10): 결과 확인의 회수 매체 선택 ──────────────────────────────────────────────────────

def test_c1_wrappers_inject_interrupt_and_partial_unarchive(tmp_path):
    """interrupt 는 실제 interruption(다른 timeout 의 FlowInterruptedException) + Runner 오프라인, unarchive 는 원본 이름으로 주입하고 truncate 는
    실제 unarchive 뒤에 받은 파일의 앞 keep 줄만 남긴다. 운영 함수부에는 주입 토큰이 없다."""
    out = tmp_path / "f.groovy"
    build_functions.build(PORTAL, "recover_partial_archive_keeps_stash", out, None)
    wrappers = out.read_text(encoding="utf-8").split("harness wrappers")[1]
    assert "if (kind == 'interrupt') {" in wrappers and "HARNESS.outer.timeout(time: 1, unit: 'SECONDS') { HARNESS.outer.sleep(time: 30, unit: 'SECONDS') }" in wrappers
    unarch = wrappers[wrappers.index("def unarchive(Map m) {"):wrappers.index("// readTrusted 는")]
    assert "Map cut = seHarnessFault('unarchive', src)" in unarch
    assert unarch.index("HARNESS.outer.unarchive(m)") < unarch.index("HARNESS.outer.writeFile(file: dst")
    assert "take((cut.keep ?: 1) as int)" in unarch


def test_c1_scenarios_cover_the_directive_cases():
    """A 중간 stash 뒤 마지막 stash 실패 → archive · B 표식 없이 끊김 + Runner 미복귀 → archive · C archive 회수 전부 실패 → stash ·
    D 보관본 일부(정리 결과 실패 · OUTPUT 일부) + 더 나은 stash → stash · E CHECKPOINT 만 있는 archive → Layer B."""
    exp = {name: SCENARIOS[name]["expect"] for name in ("recover_final_archive_over_snapshot", "recover_flag_unwritten_archive",
                                                         "recover_archive_unavailable_stash", "recover_partial_archive_keeps_stash",
                                                         "recover_checkpoint_only_archive")}
    assert exp["recover_final_archive_over_snapshot"]["recovery"]["chosen"] == "archive"
    assert exp["recover_final_archive_over_snapshot"]["by_origin"] == {"output": 3, "checkpoint": 0, "synthetic": 0}
    assert exp["recover_flag_unwritten_archive"]["recovery"]["chosen"] == "archive" and exp["recover_flag_unwritten_archive"]["infra"]["expired"] is True
    assert exp["recover_archive_unavailable_stash"]["recovery"]["chosen"] == "stash" and exp["recover_archive_unavailable_stash"]["filled"] == 1
    d = exp["recover_partial_archive_keeps_stash"]
    assert d["recovery"]["chosen"] == "stash" and d["recovery"]["stash_real"] > d["recovery"]["archive_real"]
    assert d["by_origin"] == {"output": 2, "checkpoint": 1, "synthetic": 0}, "stash 의 OUTPUT · CHECKPOINT 를 버리지 않는다"
    e = exp["recover_checkpoint_only_archive"]
    assert e["source"] == "archive" and e["layerB"] == "ok" and e["by_origin"]["checkpoint"] == 1 and e["by_origin"]["synthetic"] == 0
    kinds = {(f["op"], f.get("kind")) for f in SCENARIOS["recover_flag_unwritten_archive"]["faults"]}
    assert ("stash", "interrupt") in kinds
    b_nodes = SCENARIOS["recover_flag_unwritten_archive"]["gather_stage"]
    assert b_nodes["node_steps"][2]["queue_delay"] > b_nodes["constants"]["INFRA_WAIT"], "보존만 다시 하려던 Runner 가 대기 한도 안에 돌아오지 않는다"


def test_verdict_checks_the_recovery_record():
    exp = {"recovery": {"final_stashed": False, "fast_path": False, "chosen": "archive", "stash_real": 2, "archive_real": 3, "stash_recovered": True}}
    summary = {"recovery": {"final_stashed": False, "fast_path": False, "chosen": "archive",
                            "stash": {"looked_up": True, "recovered": True, "real": 2}, "archive": {"looked_up": True, "real": 3}}}
    obs = harness_verdict.observe(summary, None, [], [], {}, {}, None, None)
    checks, partial = harness_verdict.check(exp, obs)
    assert partial == [] and all(c["ok"] for c in checks), checks
    summary["recovery"]["chosen"] = "stash"
    obs = harness_verdict.observe(summary, None, [], [], {}, {}, None, None)
    checks, _ = harness_verdict.check(exp, obs)
    assert {c["name"] for c in checks if not c["ok"]} == {"recovery.chosen"}
    obs = harness_verdict.observe({"source": "stash"}, None, [], [], {}, {}, None, None)
    _, partial = harness_verdict.check(exp, obs)
    assert partial == ["recovery: finalize_summary.json 에 recovery 없음"]


# ── 2026-10-08 CI 실행시간 개선: 같은 Job 의 빌드 둘이 동시에 돈다 ─────────────────────────────────

def _pass_inputs(tmp_path, event_uuids):
    body = tmp_path / "callback_body.json"
    body.write_bytes(b'{"loc":"git","gatherInfoJson":[]}')
    import hashlib
    sha = hashlib.sha256(body.read_bytes()).hexdigest()
    summary = {"accepted": 3, "lines": 3, "kept": 3, "filled": 0, "outcome": "completed", "layerA": "ok", "layerB": "skipped",
               "source": "stash", "unrecovered": [], "damage": [], "recovery_limited": False, "by_origin": {"output": 3, "checkpoint": 0, "synthetic": 0},
               "warnings": [], "callback": {"attempted": True, "delivered": True, "http_code": 200, "attempts": 1}}
    sink = "".join(json.dumps({"method": "POST", "status_sent": 200, "ok": True, "body_sha256": sha, "eventUuid": u}) + "\n" for u in event_uuids)
    return dict(summary=_write(tmp_path / "s.json", summary), body=str(body), sink=_write(tmp_path / "k.jsonl", sink),
                preserve=_write(tmp_path / "p.json", {"archived": True, "stashed": True, "deleted": True}),
                control=_write(tmp_path / "ctl.json", {"sink_reachable": True, "rethrown": False}))


def test_verdict_fails_when_the_sink_record_holds_another_builds_request(tmp_path):
    """수신기는 빌드마다 따로지만, 기록에 다른 요청(eventUuid)이 섞이면 격리가 깨진 것이다 — 그 빌드의 판정은 PASS 가 아니다.
    readTrusted 가 고정 후보 밖(Job branch 최신)을 읽었어도 FAIL 이다(섞인 revision)."""
    own = "harness-jenkins-clovirone-cicd-clovirone-server-gather-harness-970"
    files = _pass_inputs(tmp_path, [own])
    rc, res = _run_verdict(tmp_path, "normal_success", calls=_write(tmp_path / "c.json", ["readTrusted:scripts/jenkins/se_finalize.groovy"]),
                           **{"event-uuid": own}, **files)
    assert rc == 0 and res["verdict"] == "PASS"
    assert {c["name"] for c in res["checks"]} >= {"sink_isolation", "trusted_pinned"}
    files = _pass_inputs(tmp_path, [own, "harness-jenkins-clovirone-cicd-clovirone-server-gather-harness-971"])
    rc, res = _run_verdict(tmp_path, "normal_success", calls=_write(tmp_path / "c.json", []), **{"event-uuid": own}, **files)
    assert rc == 1 and any(p.startswith("sink_isolation") for p in res["problems"])
    files = _pass_inputs(tmp_path, [own])
    rc, res = _run_verdict(tmp_path, "normal_success", calls=_write(tmp_path / "c.json", ["readTrusted:common/vars/x.yml", "readTrusted:unpinned:common/vars/x.yml"]),
                           **{"event-uuid": own}, **files)
    assert rc == 1 and any(p.startswith("trusted_pinned") for p in res["problems"])


def test_sink_hold_has_no_isolation_check_because_it_receives_main_job_posts(tmp_path):
    """sink_hold 는 main Job(T2 · T5)의 POST 를 받는 보조 시나리오다 — 기대값이 없어 INFO 로 끝나고 eventUuid 격리 검사를 붙이지 않는다."""
    assert set(SCENARIOS["sink_hold"]["expect"]) <= {"note"} and SCENARIOS["sink_hold"]["hold_seconds"] > 0
    sink = json.dumps({"method": "POST", "status_sent": 200, "ok": True, "eventUuid": "r10-t2-1791328282"}) + "\n"
    rc, res = _run_verdict(tmp_path, "sink_hold", sink=_write(tmp_path / "k.jsonl", sink), **{"event-uuid": "harness-x-1"})
    assert rc == 0 and res["verdict"] == "INFO" and res["checks"] == []


def test_wrappers_fail_closed_outside_the_pinned_candidate(tmp_path):
    """readTrusted 는 고정 후보에서 미리 읽은 파일만 돌려준다 — 없는 경로는 기록(readTrusted:unpinned:)하고 실패시킨다(Job SCM 의 branch 최신을
    읽지 않는다). gather_stage 밖의 checkout 도 후보 밖을 받으므로 실패시킨다."""
    out = tmp_path / "f.groovy"
    build_functions.build(PORTAL, "normal_success", out, None)
    text = out.read_text(encoding="utf-8")
    rt = text[text.index("def readTrusted(String path) {"):]
    rt = rt[:rt.index("\n}\n")]
    assert "HARNESS.calls << ('readTrusted:unpinned:' + path)" in rt and "throw new Exception(" in rt
    assert "HARNESS.outer.readTrusted(" not in rt, "실제 readTrusted(Job SCM 최신)로 넘기지 않는다"
    co = text[text.index("def checkout(Object s) {"):]
    co = co[:co.index("\n}\n")]
    assert "HARNESS.outer.error(" in co and "HARNESS.outer.checkout(" not in co


@pytest.mark.source_text   # Jenkinsfile_harness 는 main 전용 — production tree overlay(G14)에는 없다
def test_harness_pipeline_isolates_concurrent_builds_and_pins_the_candidate():
    """2026-10-08: CI 의 두 lane 이 이 Job 의 빌드 둘을 동시에 돌린다.
    - 동시 실행을 막지 않는다(disableConcurrentBuilds 없음) · 보관 정책은 그대로.
    - 수신기: SINK_PORT=0 이면 OS 배정(기본값 18080 은 수동 · main E2E sink_hold 용으로 유지) · 빌드 번호로 나눈 controller 폴더 · ready 파일 대기
      (고정 sleep 없음) · 남의 수신기를 pkill 하지 않는다 · finally 에서 이 빌드의 수신기만(명령줄의 ready 경로 확인) 끝낸다.
    - 후보 고정: MAIN_SHA 를 그 commit 으로 받고(비교 유지) · readTrusted 3개 파일을 두 모드 모두 받은 소스에서 · Pipeline 정의 revision 을 git 이력으로 확인.
    - 부모가 결속을 확인할 빌드 변수 · 판정에 eventUuid 를 넘긴다."""
    jf = (HARNESS / "Jenkinsfile_harness").read_text(encoding="utf-8")
    code = "\n".join(l for l in jf.split("\n") if not l.lstrip().startswith("//"))
    assert "disableConcurrentBuilds()" not in code and "buildDiscarder(logRotator(numToKeepStr: '200'))" in code
    assert "string(name: 'SINK_PORT', defaultValue: '18080'" in code
    assert "pkill" not in code and "sleep 2" not in code and "sleep 1;" not in code
    assert 'sinkWs = "${pwd()}@sink/${env.BUILD_NUMBER}"' in code and 'ws("${pwd()}@sink")' not in code
    assert "--port ${sinkMode}" in code and '--ready-file "\\$D/ready.json"' in code
    assert "/proc/\\$PID/cmdline" in code and 'grep -qF -- "--ready-file \\$D/ready.json"' in code
    assert code.index("} finally {") < code.index("int rc = sh(returnStatus: true"), "판정 전에 수신기를 정리하고 기록을 회수한다"
    assert "String sinkUrl = 'http://127.0.0.1:9'" in code, "수신기가 뜨지 않으면 닫힌 포트로 — 남의 수신기로 보내지 않는다"
    assert "branches: [[name: want]], userRemoteConfigs: scm.userRemoteConfigs, extensions: scm.extensions" in code
    assert 'error "[Harness] MAIN_SHA ${want} != checkout ${checkoutSha}' in code, "받은 commit 과 후보 비교는 그대로"
    assert "git merge-base --is-ancestor '${want}' '${defRef}'" in code
    assert "git log --format=%H '${want}..${defRef}' -- tests/jenkins/harness/Jenkinsfile_harness" in code
    assert "for (String path in TRUSTED_PATHS)" in code and "trustedRoot = 'prodtree_src/'" in code
    for var in ("env.SE_HARNESS_SHA", "env.SE_HARNESS_FUNCTIONS_SHA256", "env.SE_HARNESS_SOURCE_SHA256", "env.SE_HARNESS_ARCHIVE_SHA256",
                "env.SE_HARNESS_TREE_HASH"):
        assert var in code, var
    assert "params.EXPECTED_ARCHIVE_SHA256" in code and "params.EXPECTED_TREE_HASH" in code
    assert code.index("sha256sum prodtree.tar.gz") < code.index("tar -xzf prodtree.tar.gz"), "압축 파일은 풀기 전에 대조한다"
    assert "--event-uuid '${eventUuid}'" in code
    cfg = (REPO / "jenkins" / "jobs" / "clovirone-server-gather-harness" / "config.xml").read_text(encoding="utf-8")
    assert "DisableConcurrentBuildsJobProperty" not in cfg, "Job 정의 스냅샷도 동시 실행을 막지 않는다"
