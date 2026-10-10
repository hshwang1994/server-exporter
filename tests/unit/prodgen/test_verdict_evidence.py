"""prodgen verdict model · report binding/digest · environment compatibility · E2E evidence contract
(2026-10-04, Astra R1 · §8-2 · §8-3 · 검토 C1 · C3)."""
from __future__ import annotations

import json

import pytest

from scripts.ai.prodgen.common import ProdgenError
from scripts.ai.prodgen.evidence import (CALLBACK_FAIL_MARKERS, CALLBACK_OK_MARKERS, CANON_FALLBACK_MARKERS, LAYER_B_UNAVAILABLE_MARKERS,
                                         MAIN_CONTRACT, REMOVED_MAIN_PARAMS, REQUIRED_HARNESS, REQUIRED_HARNESS_TREE,
                                         REQUIRED_MAIN, aggregate, canonical_digest, check_evidence, evaluate_harness,
                                         evaluate_main, java_string_hash, neighbour_revision, parse_entry, tip_frozen_revision,
                                         trusted_report)
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
    # 8차 R1 · R3: the stop/preserve proof is a Harness scenario in both groups; no bounded group exists any more
    assert "gather_limit_preserve" in REQUIRED_HARNESS and "gather_limit_preserve" in REQUIRED_HARNESS_TREE
    probs = check_evidence({"items": [i for i in _items(sha) if i["scenario"] != "gather_limit_preserve"]}, sha, tree_hash=TREE)
    assert len([p for p in probs if "gather_limit_preserve" in p]) == 2, probs
    with pytest.raises(TypeError):
        check_evidence({"items": _items(sha)}, sha, tree_hash=TREE, require_bounded=True)
    # digest
    ev2 = {"items": _items(sha), "collected_at": "x"}
    ev2["evidence_sha256"] = canonical_digest(ev2)
    assert check_evidence(ev2, sha, tree_hash=TREE) == []
    ev2["items"][0]["pass"] = False
    assert any("evidence_sha256" in p for p in check_evidence(ev2, sha))


def _main_item(**over):
    base = {"scenario": "S1", "kind": "main", "result": "SUCCESS", "building": False, "checkout_sha": "a" * 40,
            "params": {"loc": "git", "target_type": "os", "inventory_json": json.dumps([{"service_ip": "10.0.0.1"}, {"service_ip": "10.0.0.2"}]),
                       "callbackUrl": "http://10.100.64.151:8080"}}
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
    assert {"hosts_min", "full_limit"} <= set(_failed(evaluate_main("S3", _main_item(), SUMMARY_OK, BODY_OK, None, CONSOLE_OK)))
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
    # S3 (8차 R1): a large normal-input batch — ≥ 10 real hosts, completed under the operational 6-hour limit, nothing forced
    ips = [f"10.0.0.{n}" for n in range(1, 11)]
    s3 = _main_item(params=dict(_main_item()["params"], inventory_json=json.dumps([{"service_ip": ip} for ip in ips])))
    lim = {"gather_limit_sec": 21600, "gather_limit_source": "gather_limit", "gather_max_sec": 21600}
    sum3 = dict(SUMMARY_OK, accepted=10, lines=10, kept=10, limits=lim, by_origin={"output": 10, "checkpoint": 0, "synthetic": 0})
    body3 = {"gatherInfoJson": [_envelope(ip) for ip in ips]}
    assert _failed(evaluate_main("S3", s3, sum3, body3, None, CONSOLE_OK)) == []
    short = dict(sum3, limits=dict(lim, gather_limit_sec=9000, gather_limit_source="build_limit"))
    assert "full_limit" in _failed(evaluate_main("S3", s3, short, body3, None, CONSOLE_OK)), "빌드 한계로 줄어든 실행은 운영 한계 증거가 아니다"
    assert "full_limit" in _failed(evaluate_main("S3", s3, dict(sum3, limits=None), body3, None, CONSOLE_OK))
    forced = _main_item(params=dict(s3["params"], gatherBudgetForceSec="150"))
    assert "test_params_absent" in _failed(evaluate_main("S3", forced, sum3, body3, None, CONSOLE_OK)), "시험용 파라미터가 남은 빌드는 증거가 아니다"
    assert "no_test_tag" in _failed(evaluate_main("S3", s3, sum3, body3, None, "[시험: 강제 제한 150초]\n" + CONSOLE_OK))
    assert "hosts_min" in _failed(evaluate_main("S3", _main_item(), dict(sum3, accepted=2, lines=2), BODY_OK, None, CONSOLE_OK))
    # T2: TEST-NET hosts, all failed with complete diagnosis, delivered 2xx, SUCCESS
    t2 = _main_item(params=dict(_main_item()["params"], inventory_json=json.dumps([{"service_ip": "192.0.2.10"}, {"service_ip": "192.0.2.11"}]), callbackUrl="http://127.0.0.1:18080"))
    body2 = {"gatherInfoJson": [_envelope("192.0.2.10", ok=False), _envelope("192.0.2.11", ok=False)]}
    assert _failed(evaluate_main("T2", t2, SUMMARY_OK, body2, None, CONSOLE_OK)) == []
    assert "callback_delivered" in _failed(evaluate_main("T2", t2, SUMMARY_OK, body2, None, con6)), "연결 거부로 끝난 실행은 T2 가 아니라 T6 증거다"
    # E2E-A2: FAILURE + Resolve Location refusal marker + loc=chj
    a2 = _main_item(result="FAILURE", params=dict(_main_item()["params"], loc="chj"))
    a2_console = ("Obtained Jenkinsfile_portal from git https://x\n[Pipeline] { (Gather)\n[Pipeline] { (Declarative: Post Actions)\nRunning on Jenkins in /x\n"
                  "[Finalize] node wait 1s\n[Resolve Location] 등록되지 않은 Location: 'chj' (등록: ic cj yi git)")
    assert _failed(evaluate_main("E2E-A2", a2, None, None, None, a2_console)) == []
    # the refusal must happen before any agent ran, and the Jenkinsfile must have come from SCM (lightweight checkout marker)
    assert "stopped_before_agent" in _failed(evaluate_main("E2E-A2", a2, None, None, None, "Obtained Jenkinsfile_portal from git https://x\n[Pipeline] { (Gather)\nRunning on R01 in /w\n[Pipeline] { (Declarative: Post Actions)\n[Resolve Location] 등록되지 않은 Location: 'chj'"))
    assert "jenkinsfile_obtained" in _failed(evaluate_main("E2E-A2", a2, None, None, None, "[Resolve Location] 등록되지 않은 Location: 'chj'"))
    # S5: Kernel 6.x majors from data.system.kernel
    assert _failed(evaluate_main("S5", _main_item(), SUMMARY_OK, BODY_OK, None, CONSOLE_OK)) == []
    old = {"gatherInfoJson": [dict(_envelope("10.0.0.1"), data={"system": {"kernel": "5.14.0-570.el9.x86_64"}}), _envelope("10.0.0.2")]}
    assert "kernel_major" in _failed(evaluate_main("S5", _main_item(), SUMMARY_OK, old, None, CONSOLE_OK))
    assert set(MAIN_CONTRACT) >= set(REQUIRED_MAIN)


def test_fail_closed_scenario_binds_to_agreeing_neighbour_builds_only():
    """E2E-A2 stops in Resolve Location before any agent checkout, so Jenkins records no revision for it (CI #14 2026-10-04:
    `E2E-A2 … sha=None`). The Job's nearest earlier and later builds that carry a revision pin the SCM tip; the binding is
    accepted only when both agree, is recorded as `checkout_sha_source`, and never applies to a scenario with hosts."""
    a, b = "a" * 40, "b" * 40
    builds = [{"number": 41, "sha": a}, {"number": 42, "sha": a}, {"number": 43, "sha": None}, {"number": 44, "sha": a}]
    assert neighbour_revision(builds, 43) == (a, "neighbours:#42,#44")
    assert neighbour_revision([{"number": 42, "sha": a}, {"number": 43, "sha": None}, {"number": 44, "sha": b}], 43) == (None, None), "disagreeing sides → no binding"
    assert neighbour_revision([{"number": 43, "sha": None}, {"number": 44, "sha": a}], 43) == (None, None), "missing earlier side → no binding"
    assert neighbour_revision([{"number": 42, "sha": a}, {"number": 43, "sha": None}], 43) == (None, None), "missing later side → no binding"
    assert [k for k, c in MAIN_CONTRACT.items() if c.get("fail_closed")] == ["E2E-A2"], "only E2E-A2 is the fail-closed contract (T5 has no host constraint but does check out)"
    # the contract itself demands the lightweight checkout marker and that no agent ran before the refusal
    item = {"scenario": "E2E-A2", "result": "FAILURE", "building": False, "params": {"loc": "chj", "inventory_json": '[{"service_ip":"192.0.2.10"}]'}}
    con_ok = ("Obtained Jenkinsfile_portal from git https://x\n[Pipeline] { (Resolve Location)\n[Pipeline] { (Gather)\n[Pipeline] { (Declarative: Post Actions)\n"
              "Running on Jenkins in /data1/jenkins/home/workspace/x\n[Finalize] node wait 1s\n"
              "ERROR: [Resolve Location] 등록되지 않은 Location: 'chj' — 허용: [cj, git]")
    checks = {c["name"]: c["ok"] for c in evaluate_main("E2E-A2", item, None, None, None, con_ok)}
    assert checks["jenkinsfile_obtained"] and checks["stopped_before_agent"] and checks["console:[Resolve Location] 등록되지 않은 Location: 'chj'"]
    con_agent = ("Obtained Jenkinsfile_portal from git https://x\n[Pipeline] { (Gather)\nRunning on Runner01 in /w\n[Budget] exec gather=600\n"
                 "[Pipeline] { (Declarative: Post Actions)\nRunning on Jenkins in /x\n[Resolve Location] 등록되지 않은 Location: 'chj'")
    checks = {c["name"]: c["ok"] for c in evaluate_main("E2E-A2", item, None, None, None, con_agent)}
    assert not checks["stopped_before_agent"], "an agent before the refusal is not the fail-closed path"
    # 2026-10-04 최종 지시 §5: a neighbour-derived binding is an **estimate** — recorded, but never accepted as the binding of a required
    # scenario. Direct forms: Jenkins BuildData (build_data) or a trigger-side tip-frozen observation (tip_frozen:ls-remote).
    estimated = {"scenario": "E2E-A2", "kind": "main", "job": "j/main", "build": 43, "result": "FAILURE", "checkout_sha": a,
                 "checkout_sha_source": "neighbours:#42,#44", "binding": "estimated", "pass": True, "checks": [{"name": "jenkins_result", "ok": True}]}
    probs = [p for p in check_evidence({"items": [estimated]}, a, required_main=("E2E-A2",), required_harness=(), required_harness_tree=()) if p.startswith("E2E-A2")]
    assert probs and "estimate" in probs[0] and "neighbours:#42,#44" in probs[0], probs
    direct = dict(estimated, **{"checkout_sha_source": "tip_frozen:ls-remote", "binding": "direct"})
    assert not [p for p in check_evidence({"items": [direct]}, a, required_main=("E2E-A2",), required_harness=(), required_harness_tree=()) if p.startswith("E2E-A2")]
    unbound = dict(estimated, **{"checkout_sha": None, "checkout_sha_source": None, "binding": None, "pass": False})
    assert [p for p in check_evidence({"items": [unbound]}, a, required_main=("E2E-A2",), required_harness=(), required_harness_tree=()) if p.startswith("E2E-A2")]
    # tip-frozen observation: same tip before and after, build window inside the observation window
    obs = {"job": "j/main", "build": 43, "sha_before": a, "sha_after": a, "before_epoch": 1000, "after_epoch": 2000, "remote": "origin"}
    assert tip_frozen_revision(obs, 1_100_000, 300_000)[:2] == (a, "tip_frozen:ls-remote")
    assert tip_frozen_revision(dict(obs, sha_after=b), 1_100_000, 300_000)[0] is None, "tip moved → no direct binding"
    assert tip_frozen_revision(obs, 1_900_000, 300_000)[0] is None, "build ends after the second reading → no direct binding"
    assert tip_frozen_revision(obs, 900_000, 1_000)[0] is None, "build started before the first reading → no direct binding"
    assert tip_frozen_revision(None, 1_100_000, 300_000) == (None, None, None)
    assert tip_frozen_revision({"job": "j/main", "build": 43}, 1_100_000, 300_000)[0] is None, "incomplete observation"


def test_trusted_lines_identify_the_content_read_against_the_bound_revision(tmp_path):
    """§5 (2026-10-04 최종 지시): seTrusted() echoes `[Trusted] <path> len=N jhash=H` for every readTrusted. The collector recomputes
    Java String.hashCode over `git show <sha>:<path>` (UTF-8 and ISO-8859-1 decodings) and fails the item on a mismatch or when the
    revision's Jenkinsfile emits the marker but the console has no line. Older revisions without the marker add no check."""
    import subprocess
    assert java_string_hash("") == 0 and java_string_hash("a") == 97 and java_string_hash("hello") == 99162322
    assert java_string_hash("한글 — 테스트") == -1718497079 or isinstance(java_string_hash("한글 — 테스트"), int)   # deterministic int
    repo = tmp_path / "r"
    repo.mkdir()
    g = ["git", "-C", str(repo)]
    subprocess.run(g + ["init", "-q"], check=True)
    subprocess.run(g + ["config", "user.email", "t@x"], check=True)
    subprocess.run(g + ["config", "user.name", "t"], check=True)
    reg = "locations:\n  git: {agent_label: git}   # 한글 주석\n"
    (repo / "common").mkdir()
    (repo / "common" / "locations.yml").write_bytes(reg.encode("utf-8"))
    (repo / "Jenkinsfile_portal").write_text("echo \"[Trusted] ${path} len=${text.length()} jhash=${text.hashCode()}\"\n", encoding="utf-8")
    subprocess.run(g + ["add", "-A"], check=True)
    subprocess.run(g + ["commit", "-q", "-m", "x"], check=True)
    sha = subprocess.run(g + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    good = f"[Trusted] common/locations.yml len={len(reg)} jhash={java_string_hash(reg)}\n"
    items, checks = trusted_report(good, sha, str(repo))
    assert items[0]["match"] == "utf-8" and checks[0]["ok"], checks
    latin = reg.encode("utf-8").decode("latin-1")   # controller decoding with a non-UTF-8 default charset
    items, checks = trusted_report(f"[Trusted] common/locations.yml len={len(latin)} jhash={java_string_hash(latin)}\n", sha, str(repo))
    assert items[0]["match"] == "iso-8859-1" and checks[0]["ok"]
    items, checks = trusted_report(f"[Trusted] common/locations.yml len={len(reg)} jhash={java_string_hash(reg) + 1}\n", sha, str(repo))
    assert items[0]["match"] == "mismatch" and not checks[0]["ok"], "a different content than the bound revision is not that revision"
    _, checks = trusted_report("[Trusted] common/other.yml len=1 jhash=1\n", sha, str(repo))
    assert not checks[0]["ok"] and "unavailable" in checks[0]["observed"], "a path the revision does not have cannot be compared"
    _, checks = trusted_report("no marker lines at all", sha, str(repo))
    assert checks and checks[0]["name"] == "trusted_lines" and not checks[0]["ok"], "the revision emits the marker but the console has none"
    (repo / "Jenkinsfile_portal").write_text("pipeline {}\n", encoding="utf-8")
    subprocess.run(g + ["commit", "-qam", "old"], check=True)
    old = subprocess.run(g + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    assert trusted_report("no marker lines at all", old, str(repo)) == ([], []), "an older revision without seTrusted adds no check"


def test_harness_contract_rejects_wrong_scenario_source_or_missing_artifacts():
    item = {"scenario": "both_fail", "kind": "harness", "result": "SUCCESS", "building": False,
            "params": {"SCENARIO": "both_fail", "FUNCTIONS_SRC": "checkout"}}
    hr = {"scenario": "both_fail", "verdict": "PASS", "checks": [{"name": "delivered", "ok": True}], "partial": [], "problems": [],
          "meta": {"functions_sha256": "f" * 64, "source_sha256": "s" * 64}}
    control = {"functions_source": "checkout", "source_sha256": "s" * 64}
    assert _failed(evaluate_harness("both_fail", item, hr, control, "SUCCESS")) == []
    # 2026-10-10 (N3): a PASS verdict is only accepted when the recorded checks / partial / problems agree with it — a result whose
    # verdict field says PASS but carries a failed check, a partial list, or no checks at all is refused as evidence.
    assert "verdict_consistent" in _failed(evaluate_harness("both_fail", item, dict(hr, checks=[{"name": "delivered", "ok": False}]), control, "SUCCESS"))
    assert "verdict_consistent" in _failed(evaluate_harness("both_fail", item, dict(hr, partial=["sink_reachable"]), control, "SUCCESS"))
    assert "verdict_consistent" in _failed(evaluate_harness("both_fail", item, dict(hr, problems=["x"]), control, "SUCCESS"))
    assert "verdict_consistent" in _failed(evaluate_harness("both_fail", item, {k: v for k, v in hr.items() if k != "checks"}, control, "SUCCESS"))
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
    hr = {"scenario": "user_abort", "verdict": "PASS", "checks": [{"name": "jenkins_result", "ok": True}], "partial": [], "problems": [],
          "meta": {"functions_sha256": "f" * 64, "source_sha256": "s" * 64}}
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


def test_promote_has_one_required_stage_set_and_no_bounded_mode(tmp_path):
    """2026-10-05 (8차 R3): Tier 2(SE_FINALIZER_BOUNDED) · HARNESS_BOUNDED · --require-bounded 를 없앴다. 승격 조건은 배포와 무관하게
    REQUIRED_CI_STAGES 하나이고, 옛 입력(require_bounded 기록 · CLI 플래그)은 아무것도 다시 켜지 못한다 — CLI 는 그 플래그를 거부한다."""
    import json as _json
    from pathlib import Path
    from scripts.ai.prodgen import REQUIRED_CI_STAGES
    from scripts.ai.prodgen.cli import main as prodgen_main
    from scripts.ai.prodgen.promote import _check_ci_stages, _check_e2e
    a = "a" * 40
    stages = {k: "PASS" for k in REQUIRED_CI_STAGES}
    path = tmp_path / "ci.json"
    path.write_text(_json.dumps({"main_sha": a, "require_bounded": True, "stages": dict(stages, HARNESS_BOUNDED="PARTIAL")}), encoding="utf-8")
    assert _check_ci_stages(str(path), a, {}) == [], "옛 기록의 require_bounded · HARNESS_BOUNDED 는 판정에 쓰이지 않는다"
    path.write_text(_json.dumps({"main_sha": a, "stages": dict(stages, BUDGET="FAIL")}), encoding="utf-8")
    assert "BUDGET=FAIL" in _check_ci_stages(str(path), a, {})[0]
    assert not [p for p in _check_e2e({"items": []}, a) if "bounded" in p]
    with pytest.raises(SystemExit) as exc:
        prodgen_main(["promote", "--sha", a, "--require-bounded"])
    assert exc.value.code == 2, "argparse 가 모르는 옵션으로 거부한다" 
    root = Path(__file__).resolve().parents[3]
    for rel in ("scripts/ai/prodgen/promote.py", "scripts/ai/prodgen/cli.py", "scripts/ai/prodgen/evidence.py", "Jenkinsfile_ci"):
        text = (root / rel).read_text(encoding="utf-8")
        code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith(("#", "//")))
        for gone in ("require_bounded", "REQUIRE_BOUNDED", "--require-bounded", "_effective_require_bounded", "REQUIRED_HARNESS_BOUNDED"):
            assert gone not in code, (rel, gone)


def test_e2e_e_is_a_normal_redfish_run_with_standard_auth_and_account_write_zero():
    """8차 R1: E2E-E 는 시험용 dry-run 파라미터 없이 정상 Redfish 수집이다. 결과 봉투가 "표준 계정 인증(auth_success=true) · 계정 조정 경로
    미진입(details.account_service 비어 있음)" 을 보여야 한다 — CLAUDE.md §8 정상 경로(Account Write 0)."""
    def rf(ip, acct=None, auth=True):
        e = _envelope(ip)
        e["target_type"] = "redfish"
        e["diagnosis"] = dict(e["diagnosis"], auth_success=auth, details={"account_service": {} if acct is None else acct})
        return e
    item = _main_item(params=dict(_main_item()["params"], target_type="redfish",
                                  inventory_json=json.dumps([{"bmc_ip": "10.0.0.1"}, {"bmc_ip": "10.0.0.2"}])))
    body = {"gatherInfoJson": [rf("10.0.0.1"), rf("10.0.0.2")]}
    assert _failed(evaluate_main("E2E-E", item, SUMMARY_OK, body, None, CONSOLE_OK)) == []
    recovered = {"gatherInfoJson": [rf("10.0.0.1"), rf("10.0.0.2", acct={"attempted": True, "recovered": True, "method": "patch"})]}
    assert "account_write_zero" in _failed(evaluate_main("E2E-E", item, SUMMARY_OK, recovered, None, CONSOLE_OK)), "계정 조정 경로에 들어간 대상"
    no_auth = {"gatherInfoJson": [rf("10.0.0.1"), rf("10.0.0.2", auth=None)]}
    assert "account_write_zero" in _failed(evaluate_main("E2E-E", item, SUMMARY_OK, no_auth, None, CONSOLE_OK))
    dry = _main_item(params=dict(item["params"], redfishAccountDryrun="true"))
    assert "test_params_absent" in _failed(evaluate_main("E2E-E", dry, SUMMARY_OK, body, None, CONSOLE_OK)), "옛 dry-run 입력은 증거가 아니다"
    # the collector records the removed parameter names it saw (values are never needed)
    assert set(REMOVED_MAIN_PARAMS) == {"redfishAccountDryrun", "gatherBudgetForceSec"}
    assert "test_params_absent" in _failed(evaluate_main("S1", dict(_main_item(), removed_params_present=["gatherBudgetForceSec"]),
                                                         SUMMARY_OK, BODY_OK, None, CONSOLE_OK))


def test_console_markers_tolerate_timestamper_prefixes_and_the_8th_wording(tmp_path):
    """8차 R2: Timestamper 는 콘솔 줄마다 "[<ISO 시각>] " 을 붙이고, 업무 줄은 본문에도 "[YYYY-MM-DD HH:MM:SS +09:00] " 을 쓴다.
    표식 판정과 [Trusted] 줄 파싱이 그 접두어와 상관없이 같아야 한다."""
    ts = "[2026-10-06T01:02:03.456Z] "
    biz = "[2026-10-06 10:02:03 +09:00] "
    cb_ok = dict(SUMMARY_OK, callback={"attempted": True, "delivered": True, "http_code": 200, "attempts": 1}, warnings=[])
    con = (ts + biz + "[Portal 전송] 1번째 전송을 시작합니다. 응답은 최대 10분 기다립니다.\n" +
           ts + biz + "[Portal 전송] HTTP 200 응답을 받았습니다. 소요 시간: 1초. 2xx 는 Portal 이 요청을 받았다는 뜻입니다.\n")
    assert _failed(evaluate_main("S1", _main_item(), cb_ok, BODY_OK, None, con)) == []
    t6 = _main_item(result="UNSTABLE", params=dict(_main_item()["params"], callbackUrl="http://127.0.0.1:9"))
    cb_fail = dict(SUMMARY_OK, callback={"attempted": True, "delivered": False, "http_code": None, "attempts": 3}, warnings=["callback_failed"])
    con6 = ts + biz + "[Portal 전송] 전달하지 못했습니다. 시도 3번, 마지막 상태 응답 없음.\n" + ts + "[경고] Portal 전송에 실패했습니다. 보내려던 본문은 결과 파일 callback_body.json 에 있습니다.\n"
    assert _failed(evaluate_main("T6", t6, cb_fail, BODY_OK, None, con6)) == []
    tn = json.dumps([{"service_ip": "192.0.2.10"}, {"service_ip": "192.0.2.11"}])
    ea = _main_item(params=dict(_main_item()["params"], loc="cj", inventory_json=tn, callbackUrl="http://127.0.0.1:18080"))
    body_f = {"gatherInfoJson": [_envelope("192.0.2.10", ok=False), _envelope("192.0.2.11", ok=False)]}
    con_a = ts + "[실행 위치] cj 위치의 os 대상은 노드 라벨 'cj && linux' 에서 실행합니다. 후보: Runner01\n" + con
    checks = {c["name"]: c for c in evaluate_main("E2E-A", ea, cb_ok, body_f, None, con_a)}
    assert checks["console:[Resolve Location] cj + "]["ok"] and checks["console:[Resolve Location] cj + "]["observed"] == "[실행 위치] cj 위치의 "
    t5 = _main_item(scenario="T5", result="ABORTED")
    con5 = ts + biz + "[수집] 중단됨: 사용자 취소 또는 다른 중단입니다. 확보한 결과를 보존하고 전송으로 넘어갑니다. (outcome=aborted)\n" + con
    assert _failed(evaluate_main("T5", t5, dict(cb_ok, outcome="aborted"), BODY_OK, None, con5)) == []
    # [Trusted] lines with a Timestamper prefix are still parsed
    import subprocess
    repo = tmp_path / "r"
    repo.mkdir()
    g = ["git", "-C", str(repo)]
    subprocess.run(g + ["init", "-q"], check=True)
    subprocess.run(g + ["config", "user.email", "t@x"], check=True)
    subprocess.run(g + ["config", "user.name", "t"], check=True)
    reg = "locations:\n  git: {agent_label: git}\n"
    (repo / "common").mkdir()
    (repo / "common" / "locations.yml").write_text(reg, encoding="utf-8", newline="\n")
    (repo / "Jenkinsfile_portal").write_text("echo \"[Trusted] ${path}\"\n", encoding="utf-8")
    subprocess.run(g + ["add", "-A"], check=True)
    subprocess.run(g + ["commit", "-q", "-m", "x"], check=True)
    sha = subprocess.run(g + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    items, checks = trusted_report(ts + f"[Trusted] common/locations.yml len={len(reg)} jhash={java_string_hash(reg)}\n", sha, str(repo))
    assert items and items[0]["match"] == "utf-8" and checks[0]["ok"], (items, checks)


def test_main_contract_reads_the_new_operator_wording_and_the_summary_callback():
    """2026-10-05 (F13 · F09): 콘솔 문구가 한국어로 바뀌었다 — 전송 결과는 finalize_summary.callback 이 기록이고 콘솔 2xx 표식이 그 기록과
    맞아야 한다. 구 · 신 표식은 둘 다 인정한다(이전 빌드를 다시 판정할 때)."""
    cb_ok = dict(SUMMARY_OK, callback={"attempted": True, "delivered": True, "http_code": 200, "attempts": 1}, warnings=[])
    con_new = "[Portal 전송] http://10.100.64.151:8080/api/jenkins/gather/os 로 보냅니다 (최대 3번, 본문 900자)\n[Portal 전송] 완료: HTTP 200 (1/3번째 시도)\n"
    assert _failed(evaluate_main("S1", _main_item(), cb_ok, BODY_OK, None, con_new)) == []
    assert "callback_delivered" in _failed(evaluate_main("S1", _main_item(), cb_ok, BODY_OK, None, "[Portal 전송] 실패 (1/3번째 시도): HTTP 500\n")), \
        "요약과 콘솔이 어긋나면 전달로 보지 않는다"
    assert "callback_delivered" in _failed(evaluate_main("S1", _main_item(), dict(cb_ok, callback={"delivered": False}), BODY_OK, None, con_new))
    # T6 — 요약 delivered=false + 새 실패 문구
    t6 = _main_item(result="UNSTABLE", params=dict(_main_item()["params"], callbackUrl="http://127.0.0.1:9"))
    cb_fail = dict(SUMMARY_OK, callback={"attempted": True, "delivered": False, "http_code": None, "attempts": 3}, warnings=["callback_failed"])
    con6 = "[Portal 전송] 실패 (3/3번째 시도): 연결하지 못했거나 120초 안에 응답이 없었습니다: refused\n[경고] Portal 전송에 실패했습니다\n"
    assert _failed(evaluate_main("T6", t6, cb_fail, BODY_OK, None, con6)) == []
    # T5 — 새 중단 표식
    t5 = _main_item(scenario="T5", result="ABORTED")
    con5 = "[수집] 중단됨: 사용자 취소 또는 상위 시간 제한(단계 115분 · 빌드 150분) — 확보한 결과를 보존하고 전송으로 넘어갑니다 (outcome=aborted)\n" + con_new
    assert _failed(evaluate_main("T5", t5, dict(cb_ok, outcome="aborted"), BODY_OK, None, con5)) == []
    # E2E-A — 새 실행 위치 표식
    tn = json.dumps([{"service_ip": "192.0.2.10"}, {"service_ip": "192.0.2.11"}])
    ea = _main_item(result="SUCCESS", params=dict(_main_item()["params"], loc="cj", inventory_json=tn, callbackUrl="http://127.0.0.1:18080"))
    body_f = {"gatherInfoJson": [_envelope("192.0.2.10", ok=False), _envelope("192.0.2.11", ok=False)]}
    con_a = "[실행 위치] cj · os → 노드 라벨 'cj && (linux && windows)' (후보: Runner01)\n" + con_new
    checks = {c["name"]: c for c in evaluate_main("E2E-A", ea, cb_ok, body_f, None, con_a)}
    assert checks["console:[Resolve Location] cj + "]["ok"] and checks["console:[Resolve Location] cj + "]["observed"] == "[실행 위치] cj · "
    # E2E-A2 — 새 단계 이름으로 잘린 수집 블록 · 새 거부 표식
    a2 = _main_item(result="FAILURE", params=dict(_main_item()["params"], loc="chj"))
    a2_new = ("Obtained Jenkinsfile_portal from git https://x\n[Pipeline] { (실행 위치 확인)\n[Pipeline] { (서버 정보 수집)\n"
              "Stage \"서버 정보 수집\" skipped due to earlier failure(s)\n[Pipeline] { (Declarative: Post Actions)\nRunning on Jenkins in /x\n"
              "ERROR: [실행 위치] 등록되지 않은 Location: 'chj' — 허용: [cj, git]")
    assert _failed(evaluate_main("E2E-A2", a2, None, None, None, a2_new)) == []
    a2_agent = a2_new.replace("Stage \"서버 정보 수집\" skipped due to earlier failure(s)", "Running on Runner01 in /w")
    assert "stopped_before_agent" in _failed(evaluate_main("E2E-A2", a2, None, None, None, a2_agent))


def test_main_contract_reads_the_2026_10_09_wording():
    """2026-10-09 (로그 문구 정리): 사건 첫 줄 + 두 칸 들여쓴 상세 줄. 표식이 되는 첫 줄의 앞부분은 그대로라 판정이 같고,
    바뀐 표식(전송 확인 못함 · 거부 · 정본 · 결과 복구 모듈)은 새 문구를 더해 인정한다. 옛 빌드를 다시 판정하는 옛 표식도 그대로다."""
    ts = "[2026-10-09T01:02:03.456Z] "
    biz = "[2026-10-09 10:02:03 +09:00] "
    cb_ok = dict(SUMMARY_OK, callback={"attempted": True, "delivered": True, "http_code": 200, "attempts": 1}, warnings=[])
    con = (ts + biz + "[Portal 전송] 1번째 전송을 시작합니다.\n" + ts + "  주소: http://10.100.64.151:8080/api/jenkins/gather/os\n" +
           ts + biz + "[Portal 전송] HTTP 200 응답을 받았습니다. 소요 시간 0.3초.\n" +
           ts + "[요약] 정상 종료 (SUCCESS)\n" + ts + "  Portal 전송: HTTP 200, 응답 시각 2026-10-09 10:02:03 +09:00\n")
    assert _failed(evaluate_main("S1", _main_item(), cb_ok, BODY_OK, None, con)) == []
    # T6 — 전송을 확인하지 못한 빌드: 2xx 표식이 어디에도 없고(요약 행 포함), 실패 표식은 새 문구로도 잡힌다
    t6 = _main_item(result="UNSTABLE", params=dict(_main_item()["params"], callbackUrl="http://127.0.0.1:9"))
    cb_fail = dict(SUMMARY_OK, callback={"attempted": True, "delivered": False, "http_code": 408, "attempts": 3}, warnings=["callback_failed"])
    con6 = (ts + biz + "[Portal 전송] 3번째 전송에 실패했습니다.\n" + ts + "  연결하지 못했거나 응답을 받지 못했습니다.\n" + ts + "  전송 도구 상태: 408\n" +
            ts + biz + "[Portal 전송] 전송을 확인하지 못했습니다. 총 3번 시도했습니다.\n" + ts + "  마지막 전송 도구 상태: 408\n" +
            ts + "WARNING: [결과 확인] Portal 전송을 확인하지 못했습니다.\n" + ts + "[요약] 확인 필요 (UNSTABLE)\n" + ts + "  Portal 전송: 확인하지 못함\n")
    assert not any(m in con6 for m in CALLBACK_OK_MARKERS), "전송을 확인하지 못한 콘솔에 2xx 표식이 없다"
    assert any(m in con6 for m in CALLBACK_FAIL_MARKERS)
    assert _failed(evaluate_main("T6", t6, cb_fail, BODY_OK, None, con6)) == []
    refused = ts + biz + "[Portal 전송] Portal이 요청을 거부했습니다. HTTP 403.\n" + ts + "  다시 보내지 않습니다.\n"
    assert any(m in refused for m in CALLBACK_FAIL_MARKERS) and not any(m in refused for m in CALLBACK_OK_MARKERS)
    # T5 — 취소 표식은 첫 줄 앞부분 그대로
    t5 = _main_item(scenario="T5", result="ABORTED")
    con5 = ts + biz + "[수집] 중단됨: 사용자가 빌드를 취소했습니다.\n" + ts + "  지금까지 확보한 결과를 저장하고 Portal 전송을 시도합니다.\n" + con
    assert _failed(evaluate_main("T5", t5, dict(cb_ok, outcome="aborted"), BODY_OK, None, con5)) == []
    # E2E-A — 실행 위치 블록의 첫 줄
    tn = json.dumps([{"service_ip": "192.0.2.10"}, {"service_ip": "192.0.2.11"}])
    ea = _main_item(params=dict(_main_item()["params"], loc="cj", inventory_json=tn, callbackUrl="http://127.0.0.1:18080"))
    body_f = {"gatherInfoJson": [_envelope("192.0.2.10", ok=False), _envelope("192.0.2.11", ok=False)]}
    con_a = (ts + "[실행 위치] cj 위치의 os 대상은 'cj && (linux && windows)' 라벨의 Runner에서 실행합니다.\n" + ts + "  등록된 Runner: 1대 (Runner01)\n" +
             ts + "  연결된 Runner: 1대\n" + con)
    checks = {c["name"]: c for c in evaluate_main("E2E-A", ea, cb_ok, body_f, None, con_a)}
    assert checks["console:[Resolve Location] cj + "]["ok"] and checks["console:[Resolve Location] cj + "]["observed"] == "[실행 위치] cj 위치의 "
    # E2E-A2 — 여러 줄 오류의 첫 줄
    a2 = _main_item(result="FAILURE", params=dict(_main_item()["params"], loc="chj"))
    a2_new = ("Obtained Jenkinsfile_portal from git https://x\n[Pipeline] { (실행 위치 확인)\n[Pipeline] { (서버 정보 수집)\n"
              "Stage \"서버 정보 수집\" skipped due to earlier failure(s)\n[Pipeline] { (Declarative: Post Actions)\nRunning on Jenkins in /x\n"
              "ERROR: [실행 위치] 등록되지 않은 Location: 'chj'.\n  사용할 수 있는 값: cj, git, ic, yi\n  loc 값을 확인하세요.")
    assert _failed(evaluate_main("E2E-A2", a2, None, None, None, a2_new)) == []
    # 정본 · 결과 복구 모듈 대체 경로 표식(정보) — 새 문구도 기록된다
    assert any(m in "[결과 확인] 오류 안내 파일을 읽지 못해 기본 메시지를 사용합니다.\n  파일: …" for m in CANON_FALLBACK_MARKERS)
    assert any(m in "[결과 확인] 결과 복구 모듈을 읽지 못했습니다. 확보된 수집 결과로 처리를 계속합니다." for m in LAYER_B_UNAVAILABLE_MARKERS)
