"""prodgen verdict model · report binding/digest · environment compatibility · E2E evidence contract
(2026-10-04, Astra R1 · §8-2 · §8-3 · 검토 C1 · C3)."""
from __future__ import annotations

import json

import pytest

from scripts.ai.prodgen.common import ProdgenError
from scripts.ai.prodgen.evidence import (MAIN_CONTRACT, REQUIRED_HARNESS, REQUIRED_HARNESS_BOUNDED, REQUIRED_HARNESS_TREE,
                                         REQUIRED_MAIN, aggregate, canonical_digest, check_evidence, evaluate_harness,
                                         evaluate_main, parse_entry)
from scripts.ai.prodgen.promote import _reuse_report
from scripts.ai.prodgen.verify import (ENV_COMPARE_KEYS, MANDATORY_GATES, GateReport, GateResult, environment_compatible,
                                       report_digest_ok)

ENV = {"python": "3.12.3", "platform": "Linux 6", "ansible_runtime": "native", "ansible_version": "ansible [core 2.20.3]",
       "collections_sha256": "c" * 64, "pwsh": "7.4.6", "groovy": "absent", "jenkins_version": "2.528.3"}


def _report(statuses: dict, partial: set = frozenset()) -> GateReport:
    rep = GateReport(tree="/t")
    for gid, st in statuses.items():
        rep.add(GateResult(gid, st, ["x"], {"partial": gid in partial, "partial_reason": "mandatory tests skipped"} if gid in partial else {}))
    rep.binding = {"main_sha": "a" * 40, "tree_hash": "b" * 64, "generator_hash": "c" * 64, "manifest_sha256": "d" * 64}
    rep.environment = dict(ENV)
    return rep


ALL_PASS = {gid: "PASS" for gid in MANDATORY_GATES}


def test_verdict_three_values():
    assert _report(ALL_PASS).verdict == "COMPLETE_PASS"
    partial = dict(ALL_PASS, G13="SKIP")
    r = _report(partial)
    assert r.verdict == "PARTIAL" and not r.ok and "G13: SKIP" in r.mandatory_missing
    missing = {k: v for k, v in ALL_PASS.items() if k not in ("G19", "G20")}
    r = _report(missing)
    assert r.verdict == "PARTIAL" and {"G19: not run", "G20: not run"} <= set(r.mandatory_missing)
    assert _report({}).verdict == "PARTIAL", "빈 결과는 통과가 아니다 (R1)"
    r = _report(dict(ALL_PASS, G07="FAIL"))
    assert r.verdict == "FAIL"
    r = _report(ALL_PASS, partial={"G14"})
    assert r.verdict == "PARTIAL" and any(m.startswith("G14: partial") for m in r.mandatory_missing), "gate 내부 필수 그룹 skip 은 PARTIAL (§8-3)"


def test_report_digest_detects_tampering():
    d = _report(ALL_PASS).to_dict()
    assert report_digest_ok(d) and len(d["report_sha256"]) == 64 and d["verdict"] == "COMPLETE_PASS"
    d2 = json.loads(json.dumps(d))
    d2["gates"][0]["status"] = "FAIL"
    assert not report_digest_ok(d2)
    d3 = dict(d)
    del d3["report_sha256"]
    assert not report_digest_ok(d3)


def test_environment_compatibility_unknown_is_not_a_match():
    """검토 C3: a missing identifier on either side is *not verified*, never a match; tools are compared by version."""
    assert environment_compatible(ENV, dict(ENV))[0]
    ok, problems = environment_compatible(ENV, dict(ENV, python="3.13.1"))
    assert not ok and problems and "python" in problems[0]
    ok, problems = environment_compatible(ENV, dict(ENV, jenkins_version=""))
    assert not ok and any("jenkins_version: not verified" in p for p in problems)
    ok, problems = environment_compatible(dict(ENV, jenkins_version=""), ENV)
    assert not ok and any("jenkins_version" in p for p in problems)
    ok, problems = environment_compatible(ENV, dict(ENV, pwsh="7.5.0"))
    assert not ok and any("pwsh" in p for p in problems), "pwsh=true 만으로 같은 도구라고 보지 않는다 — 버전 비교"
    ok, problems = environment_compatible(ENV, dict(ENV, collections_sha256=""))
    assert not ok and any("collections_sha256" in p for p in problems)
    assert set(("ansible_runtime", "collections_sha256", "jenkins_version", "pwsh", "groovy")) <= set(ENV_COMPARE_KEYS)
    # legacy boolean presence flags recorded by an older report are not a match either
    ok, _ = environment_compatible(dict(ENV, pwsh=True), ENV)
    assert not ok


def test_reuse_report_rules(tmp_path):
    rep = _report(ALL_PASS)
    prov = {"main_sha": "a" * 40, "tree_hash": "b" * 64, "generator_hash": "c" * 64, "manifest_sha256": "d" * 64}
    p = tmp_path / "r.json"
    p.write_text(json.dumps(rep.to_dict()), encoding="utf-8")
    got, problems, env_problems = _reuse_report(str(p), prov, rep.environment)
    assert got is not None and problems == [] and env_problems == []
    # different tree → not reusable
    got, problems, _ = _reuse_report(str(p), dict(prov, tree_hash="e" * 64), rep.environment)
    assert got is None and any("tree_hash" in x for x in problems)
    # different environment → the report stays reusable for code-only gates, the env-dependent ones are reported for re-run
    got, problems, env_problems = _reuse_report(str(p), prov, dict(rep.environment, ansible_version="ansible [core 2.18.0]"))
    assert got is not None and problems == [] and any("ansible_version" in x for x in env_problems)
    # unknown jenkins version at promote time → env-dependent gates must be re-run (C3)
    got, problems, env_problems = _reuse_report(str(p), prov, dict(rep.environment, jenkins_version=""))
    assert got is not None and any("jenkins_version: not verified" in x for x in env_problems)
    # PARTIAL report → not reusable
    rep2 = _report(dict(ALL_PASS, G19="SKIP"))
    p2 = tmp_path / "r2.json"
    p2.write_text(json.dumps(rep2.to_dict()), encoding="utf-8")
    got, problems, _ = _reuse_report(str(p2), prov, rep.environment)
    assert got is None and any("COMPLETE_PASS" in x for x in problems)
    # tampered digest → not reusable
    d = rep.to_dict()
    d["verdict"] = "COMPLETE_PASS"
    d["gates"][3]["details"] = ["edited"]
    p3 = tmp_path / "r3.json"
    p3.write_text(json.dumps(d), encoding="utf-8")
    got, problems, _ = _reuse_report(str(p3), prov, rep.environment)
    assert got is None and any("report_sha256" in x for x in problems)


# ── evidence items ─────────────────────────────────────────────────────────────────
TREE = "b" * 64


def _items(sha, fail=None, wrong_sha=None, tree_hash=TREE, tree_items=True):
    items = []
    for sc in REQUIRED_MAIN:
        items.append({"scenario": sc, "kind": "main", "job": "j/main", "build": 1, "result": "SUCCESS", "checkout_sha": (wrong_sha if sc == wrong_sha else sha),
                      "checks": [{"name": "contract", "ok": sc != fail}], "pass": sc != fail})
    for sc in REQUIRED_HARNESS:
        items.append({"scenario": sc, "kind": "harness", "job": "j/harness", "build": 1, "harness_verdict": "PASS", "checkout_sha": sha,
                      "functions_src": "checkout", "functions_sha256": "f" * 64, "checks": [{"name": "verdict", "ok": sc != fail}], "pass": sc != fail})
    if tree_items:
        for sc in REQUIRED_HARNESS_TREE:
            items.append({"scenario": sc, "kind": "harness", "job": "j/harness", "build": 2, "harness_verdict": "PASS", "checkout_sha": sha,
                          "functions_src": "artifact", "source_sha256": "a" * 64, "provenance_tree_hash": tree_hash,
                          "checks": [{"name": "verdict", "ok": sc != fail}], "pass": sc != fail})
    return items


def test_check_evidence_requires_every_scenario_group_for_the_same_sha_and_tree():
    sha = "a" * 40
    assert check_evidence({"items": _items(sha)}, sha, tree_hash=TREE) == []
    assert any("T6" in p for p in check_evidence({"items": _items(sha, fail="T6")}, sha))
    assert any("S1" in p for p in check_evidence({"items": [i for i in _items(sha) if i["scenario"] != "S1"]}, sha))
    assert check_evidence({"items": _items(sha)}, "b" * 40), "다른 SHA 의 증거는 쓸 수 없다"
    # the generated-tree group is separate from the main-function group — renaming does not satisfy it
    probs = check_evidence({"items": _items(sha, tree_items=False)}, sha, tree_hash=TREE)
    assert len([p for p in probs if "generated-tree" in p]) == len(REQUIRED_HARNESS_TREE)
    main_only_renamed = [dict(i, functions_src="checkout") for i in _items(sha)]
    assert any("generated-tree" in p for p in check_evidence({"items": main_only_renamed}, sha, tree_hash=TREE))
    # the tree group must name the tree under promotion
    assert any("tree" in p for p in check_evidence({"items": _items(sha, tree_hash="e" * 64)}, sha, tree_hash=TREE))
    # one source per group — mixed function hashes are refused
    mixed = _items(sha)
    mixed[len(REQUIRED_MAIN)]["functions_sha256"] = "9" * 64
    assert any("mixed sources" in p for p in check_evidence({"items": mixed}, sha, tree_hash=TREE))
    # bounded (Tier 2) scenarios are required only on demand
    assert check_evidence({"items": _items(sha)}, sha, tree_hash=TREE, require_bounded=False) == []
    probs = check_evidence({"items": _items(sha)}, sha, tree_hash=TREE, require_bounded=True)
    assert len([p for p in probs if "bounded" in p]) == len(REQUIRED_HARNESS_BOUNDED)
    # digest
    ev2 = {"items": _items(sha), "collected_at": "x"}
    ev2["evidence_sha256"] = canonical_digest(ev2)
    assert check_evidence(ev2, sha, tree_hash=TREE) == []
    ev2["items"][0]["pass"] = False
    assert any("evidence_sha256" in p for p in check_evidence(ev2, sha))


def _main_item(**over):
    base = {"scenario": "S1", "kind": "main", "result": "SUCCESS", "building": False, "checkout_sha": "a" * 40,
            "params": {"loc": "git", "target_type": "os", "inventory_json": json.dumps([{"service_ip": "10.0.0.1"}, {"service_ip": "10.0.0.2"}]),
                       "callbackUrl": "http://10.100.64.151:8080", "gatherBudgetForceSec": ""}}
    base.update(over)
    return base


def _envelope(ip, ok=True):
    d = {"reachable": ok, "port_open": ok, "protocol_supported": ok, "auth_success": ok if ok else None,
         "failure_stage": None if ok else "reachable", "failure_code": None if ok else "TARGET_UNREACHABLE",
         "failure_reason": None if ok else "대상에 도달하지 못했습니다", "details": {}}
    return {"schema_version": "1", "target_type": "os", "collection_method": "agent", "ip": ip, "hostname": ip, "vendor": None,
            "status": "success" if ok else "failed", "sections": {}, "diagnosis": d, "meta": {}, "correlation": {}, "errors": [],
            "data": {"system": {"os_family": "Linux", "kernel": "6.12.0-55.el10.x86_64"}} if ok else {}}


SUMMARY_OK = {"accepted": 2, "lines": 2, "kept": 2, "filled": 0, "outcome": "completed", "by_origin": {"output": 2, "checkpoint": 0, "synthetic": 0}}
BODY_OK = {"loc": "git", "gatherInfoJson": [_envelope("10.0.0.1"), _envelope("10.0.0.2")]}
CONSOLE_OK = "[Callback] POST -> http://10.100.64.151:8080/api/jenkins/gather/os\n[Callback] [OK] HTTP 200 (1/3)\n"


def _failed(checks):
    return [c["name"] for c in checks if not c["ok"]]


def test_main_contract_s1_passes_only_with_real_hosts_success_data_and_delivered_callback():
    assert _failed(evaluate_main("S1", _main_item(), SUMMARY_OK, BODY_OK, None, CONSOLE_OK)) == []
    # the same build registered under other names fails their own checks (C1 재현: one build cannot be every scenario)
    assert "hosts_testnet" in _failed(evaluate_main("T2", _main_item(), SUMMARY_OK, BODY_OK, None, CONSOLE_OK))
    assert {"jenkins_result", "outcome", "force_sec"} <= set(_failed(evaluate_main("S3", _main_item(), SUMMARY_OK, BODY_OK, None, CONSOLE_OK)))
    assert {"jenkins_result", "outcome"} <= set(_failed(evaluate_main("T5", _main_item(), SUMMARY_OK, BODY_OK, None, CONSOLE_OK)))
    assert {"jenkins_result", "callback_failed"} <= set(_failed(evaluate_main("T6", _main_item(), SUMMARY_OK, BODY_OK, None, CONSOLE_OK)))
    assert "loc" in _failed(evaluate_main("E2E-A", _main_item(), SUMMARY_OK, BODY_OK, None, CONSOLE_OK))
    assert {"jenkins_result", "loc"} <= set(_failed(evaluate_main("E2E-A2", _main_item(), SUMMARY_OK, BODY_OK, None, CONSOLE_OK)))
    # a caller may not re-declare the expected result (FAILURE → S1 PASS is impossible)
    assert "caller_expected" in _failed(evaluate_main("S1", _main_item(caller_expected="FAILURE"), SUMMARY_OK, BODY_OK, None, CONSOLE_OK))
    assert "jenkins_result" in _failed(evaluate_main("S1", _main_item(result="FAILURE"), SUMMARY_OK, BODY_OK, None, CONSOLE_OK))
    # TEST-NET hosts are not a real-host success; loopback callback is not a receiving system
    tn = _main_item(params=dict(_main_item()["params"], inventory_json=json.dumps([{"service_ip": "192.0.2.10"}, {"service_ip": "192.0.2.11"}])))
    assert "hosts_real" in _failed(evaluate_main("S1", tn, SUMMARY_OK, BODY_OK, None, CONSOLE_OK))
    lb = _main_item(params=dict(_main_item()["params"], callbackUrl="http://127.0.0.1:9"))
    assert "callback_receiver" in _failed(evaluate_main("S1", lb, SUMMARY_OK, BODY_OK, None, CONSOLE_OK))
    # body must carry one envelope per requested host with real data; missing console → markers cannot be verified
    body_short = {"loc": "git", "gatherInfoJson": [_envelope("10.0.0.1")]}
    assert "body_one_per_host" in _failed(evaluate_main("S1", _main_item(), SUMMARY_OK, body_short, None, CONSOLE_OK))
    assert "all_success" in _failed(evaluate_main("S1", _main_item(), SUMMARY_OK, {"gatherInfoJson": [_envelope("10.0.0.1"), _envelope("10.0.0.2", ok=False)]}, None, CONSOLE_OK))
    assert {"callback_delivered", "console_available"} <= set(_failed(evaluate_main("S1", _main_item(), SUMMARY_OK, BODY_OK, None, "")))
    assert "finalize_summary" in _failed(evaluate_main("S1", _main_item(), None, BODY_OK, None, CONSOLE_OK))
    assert "filled" in _failed(evaluate_main("S1", _main_item(), dict(SUMMARY_OK, filled=1), BODY_OK, None, CONSOLE_OK))
    assert "contract" in _failed(evaluate_main("S9", _main_item(), SUMMARY_OK, BODY_OK, None, CONSOLE_OK))


def test_main_contract_expected_failures_pass_when_the_behaviour_matches():
    """A test that is *expected* to end ABORTED/UNSTABLE/FAILURE passes when its behaviour is observed — not from the result alone."""
    # T5: ABORTED + outcome aborted + interruption marker + body preserved
    t5 = _main_item(scenario="T5", result="ABORTED")
    con = "[Gather] interrupted (취소 또는 timeout) — outcome=aborted, 재전파\n[Callback] [OK] HTTP 200 (1/1)\n"
    assert _failed(evaluate_main("T5", t5, dict(SUMMARY_OK, outcome="aborted"), BODY_OK, None, con)) == []
    assert "outcome" in _failed(evaluate_main("T5", t5, SUMMARY_OK, BODY_OK, None, con)), "ABORTED alone is not T5"
    # T6: UNSTABLE + failure marker + body
    t6 = _main_item(result="UNSTABLE", params=dict(_main_item()["params"], callbackUrl="http://127.0.0.1:9"))
    con6 = "[Callback] [FAIL] (3/3) httpRequest 예외\n[Finalize] delivered=false — body 는 artifact callback_body.json\n[Finalize] Callback 전송 실패 — artifact callback_body.json 참조\n"
    assert _failed(evaluate_main("T6", t6, SUMMARY_OK, BODY_OK, None, con6)) == []
    assert "callback_failed" in _failed(evaluate_main("T6", t6, SUMMARY_OK, BODY_OK, None, CONSOLE_OK)), "UNSTABLE with a delivered callback is not T6"
    # S3: UNSTABLE + forced budget ≥ 120 + timeout outcome + preserved real data + at least one synthesized host
    s3 = _main_item(result="UNSTABLE", params=dict(_main_item()["params"], gatherBudgetForceSec="180"))
    sum3 = dict(SUMMARY_OK, outcome="timeout", filled=1, by_origin={"output": 1, "checkpoint": 0, "synthetic": 1})
    assert _failed(evaluate_main("S3", s3, sum3, BODY_OK, None, CONSOLE_OK)) == []
    s3b = _main_item(result="UNSTABLE", params=dict(_main_item()["params"], gatherBudgetForceSec="60"))
    assert "force_sec" in _failed(evaluate_main("S3", s3b, sum3, BODY_OK, None, CONSOLE_OK)), "MIN_START_SEC=120 아래는 S3 가 아니다"
    assert "preserved_min" in _failed(evaluate_main("S3", s3, dict(sum3, by_origin={"output": 0, "checkpoint": 0, "synthetic": 2}), BODY_OK, None, CONSOLE_OK))
    # T2: TEST-NET hosts, all failed with complete diagnosis, delivered 2xx, SUCCESS
    t2 = _main_item(params=dict(_main_item()["params"], inventory_json=json.dumps([{"service_ip": "192.0.2.10"}, {"service_ip": "192.0.2.11"}]), callbackUrl="http://127.0.0.1:18080"))
    body2 = {"gatherInfoJson": [_envelope("192.0.2.10", ok=False), _envelope("192.0.2.11", ok=False)]}
    assert _failed(evaluate_main("T2", t2, SUMMARY_OK, body2, None, CONSOLE_OK)) == []
    assert "callback_delivered" in _failed(evaluate_main("T2", t2, SUMMARY_OK, body2, None, con6)), "연결 거부로 끝난 실행은 T2 가 아니라 T6 증거다"
    # E2E-A2: FAILURE + Resolve Location refusal marker + loc=chj
    a2 = _main_item(result="FAILURE", params=dict(_main_item()["params"], loc="chj"))
    assert _failed(evaluate_main("E2E-A2", a2, None, None, None, "[Resolve Location] 등록되지 않은 Location: 'chj' (등록: ic cj yi git)")) == []
    # S5: Kernel 6.x majors from data.system.kernel
    assert _failed(evaluate_main("S5", _main_item(), SUMMARY_OK, BODY_OK, None, CONSOLE_OK)) == []
    old = {"gatherInfoJson": [dict(_envelope("10.0.0.1"), data={"system": {"kernel": "5.14.0-570.el9.x86_64"}}), _envelope("10.0.0.2")]}
    assert "kernel_major" in _failed(evaluate_main("S5", _main_item(), SUMMARY_OK, old, None, CONSOLE_OK))
    assert set(MAIN_CONTRACT) >= set(REQUIRED_MAIN)


def test_harness_contract_rejects_wrong_scenario_source_or_missing_artifacts():
    item = {"scenario": "both_fail", "kind": "harness", "result": "SUCCESS", "building": False,
            "params": {"SCENARIO": "both_fail", "FUNCTIONS_SRC": "checkout"}}
    hr = {"scenario": "both_fail", "verdict": "PASS", "meta": {"functions_sha256": "f" * 64, "source_sha256": "s" * 64}}
    control = {"functions_source": "checkout", "source_sha256": "s" * 64}
    assert _failed(evaluate_harness("both_fail", item, hr, control, "SUCCESS")) == []
    # registered name differs from the build's parameter / artifact → refused (C1 재현: normal_success 빌드를 모든 이름으로 등록)
    assert {"param_scenario", "artifact_scenario"} <= set(_failed(evaluate_harness("archive_fail", item, hr, control, "SUCCESS")))
    assert "verdict" in _failed(evaluate_harness("both_fail", item, dict(hr, verdict="PARTIAL"), control, "SUCCESS"))
    assert "harness_result" in _failed(evaluate_harness("both_fail", item, None, control, "SUCCESS"))
    assert "control_source" in _failed(evaluate_harness("both_fail", item, hr, dict(control, functions_source="artifact"), "SUCCESS"))
    assert "harness_control" in _failed(evaluate_harness("both_fail", item, hr, None, "SUCCESS"))
    # generated-tree run must carry the provenance tree hash it executed
    tree_item = dict(item, params={"SCENARIO": "both_fail", "FUNCTIONS_SRC": "artifact"})
    assert "provenance_tree_hash" in _failed(evaluate_harness("both_fail", tree_item, hr, dict(control, functions_source="artifact"), "SUCCESS"))
    assert _failed(evaluate_harness("both_fail", tree_item, hr, dict(control, functions_source="artifact", provenance={"tree_hash": "t" * 64}), "SUCCESS")) == []
    # expected Jenkins result per scenario (user_abort ends ABORTED by design)
    assert "jenkins_result" in _failed(evaluate_harness("both_fail", item, hr, control, "ABORTED"))


def test_harness_expected_jenkins_result_comes_from_scenarios_json():
    """CI #12 dry-run: user_abort / aborted_outcome_finalize end ABORTED by design — the collector must judge them like the CI driver."""
    from scripts.ai.prodgen.evidence import harness_expected_results
    exp = harness_expected_results()
    assert exp.get("user_abort") == "ABORTED" and exp.get("aborted_outcome_finalize") == "ABORTED" and exp.get("normal_success") == "SUCCESS"
    assert harness_expected_results("/nonexistent/scenarios.json") == {}
    item = {"scenario": "user_abort", "kind": "harness", "result": "ABORTED", "building": False, "params": {"SCENARIO": "user_abort", "FUNCTIONS_SRC": "checkout"}}
    hr = {"scenario": "user_abort", "verdict": "PASS", "meta": {"functions_sha256": "f" * 64, "source_sha256": "s" * 64}}
    ctl = {"functions_source": "checkout", "source_sha256": "s" * 64}
    assert _failed(evaluate_harness("user_abort", item, hr, ctl, exp["user_abort"])) == []
    assert "jenkins_result" in _failed(evaluate_harness("user_abort", dict(item, result="SUCCESS"), hr, ctl, exp["user_abort"])), "ABORTED 가 기대인 시나리오가 SUCCESS 로 끝나면 통과가 아니다"


def test_parse_entry_and_aggregate(tmp_path):
    e = parse_entry("S1=clovirone-cicd/clovirone-server-gather-main:7")
    assert e["scenario"] == "S1" and e["build"] == 7 and e["kind"] == "main" and e["expected"] == "SUCCESS" and e["caller_expected"] is None
    e = parse_entry("T6=clovirone-cicd/clovirone-server-gather-main:9:UNSTABLE")
    assert e["expected"] == "UNSTABLE" and e["caller_expected"] == "UNSTABLE"
    e = parse_entry("normal_success=clovirone-cicd/clovirone-server-gather-harness:4")
    assert e["expected"] == "PASS" and e["kind"] == "harness"
    with pytest.raises(ProdgenError):
        parse_entry("bad")
    rep = _report(ALL_PASS).to_dict()
    rp = tmp_path / "report.json"
    rp.write_text(json.dumps(rep), encoding="utf-8")
    ev = {"items": _items("a" * 40), "collected_at": "x"}
    ev["evidence_sha256"] = canonical_digest(ev)
    ep = tmp_path / "ev.json"
    ep.write_text(json.dumps(ev), encoding="utf-8")
    out = tmp_path / "agg.json"
    res = aggregate(str(rp), [str(ep)], str(out))
    agg = json.loads(out.read_text(encoding="utf-8"))
    assert res["items"] == len(ev["items"]) and report_digest_ok(agg) and agg["report_sha256"] != rep["report_sha256"]
    assert agg["e2e_evidence"]["sources"][0]["evidence_sha256"] == ev["evidence_sha256"]
    # tampered / undigested input evidence cannot be aggregated (C1 ⑤: input digest first)
    bad = dict(ev)
    bad["items"] = json.loads(json.dumps(ev["items"]))
    bad["items"][0]["pass"] = False
    bp = tmp_path / "bad.json"
    bp.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ProdgenError):
        aggregate(str(rp), [str(bp)], str(out))
    nodigest = {k: v for k, v in ev.items() if k != "evidence_sha256"}
    np_ = tmp_path / "nodigest.json"
    np_.write_text(json.dumps(nodigest), encoding="utf-8")
    with pytest.raises(ProdgenError):
        aggregate(str(rp), [str(np_)], str(out))
    # tampered report cannot be aggregated onto
    rep["gates"][0]["status"] = "FAIL"
    rp.write_text(json.dumps(rep), encoding="utf-8")
    with pytest.raises(ProdgenError):
        aggregate(str(rp), [str(ep)], str(out))


def test_curl_json_disables_globbing_for_bracketed_tree_queries(monkeypatch, tmp_path):
    """CI #5 Evidence Aggregate: the Jenkins read failed with curl rc=3 because `tree=...actions[...]` was treated as a glob."""
    import subprocess
    from scripts.ai.prodgen import evidence as ev
    seen = {}

    def fake_run(args, **kw):
        seen["args"] = args
        return subprocess.CompletedProcess(args, 0, stdout='{"number": 28, "result": "SUCCESS"}\n200', stderr="")

    monkeypatch.setattr(ev.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(ev.subprocess, "run", fake_run)
    netrc = tmp_path / "netrc"
    netrc.write_text("machine x login a password b\n", encoding="utf-8")
    out = ev._curl_json("https://jenkins.invalid/job/x/28/api/json?tree=number,actions[parameters[name,value]]", str(netrc))
    assert out["number"] == 28
    flags = [a for a in seen["args"] if a.startswith("-") and not a.startswith("--")]
    assert any("g" in f for f in flags), seen["args"]
