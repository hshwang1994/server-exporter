"""prodgen verdict model · report binding/digest · environment compatibility · E2E evidence (2026-10-04, Astra R1 · §8-2 · §8-3)."""
from __future__ import annotations

import json

import pytest

from scripts.ai.prodgen.common import ProdgenError
from scripts.ai.prodgen.evidence import REQUIRED_HARNESS, REQUIRED_MAIN, aggregate, canonical_digest, check_evidence, parse_entry
from scripts.ai.prodgen.promote import _reuse_report
from scripts.ai.prodgen.verify import (MANDATORY_GATES, GateReport, GateResult, environment_compatible, report_digest_ok)


def _report(statuses: dict, partial: set = frozenset()) -> GateReport:
    rep = GateReport(tree="/t")
    for gid, st in statuses.items():
        rep.add(GateResult(gid, st, ["x"], {"partial": gid in partial, "partial_reason": "mandatory tests skipped"} if gid in partial else {}))
    rep.binding = {"main_sha": "a" * 40, "tree_hash": "b" * 64, "generator_hash": "c" * 64, "manifest_sha256": "d" * 64}
    rep.environment = {"python": "3.12.3", "platform": "Linux 6", "ansible_version": "ansible [core 2.20.3]", "pwsh": True, "groovy": False, "jenkins_version": "2.528.3"}
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


def test_environment_compatibility():
    base = {"python": "3.12.3", "platform": "Linux 6", "ansible_version": "ansible [core 2.20.3]", "pwsh": True, "groovy": False, "jenkins_version": "2.528.3"}
    assert environment_compatible(base, dict(base))[0]
    ok, problems = environment_compatible(base, dict(base, python="3.13.1"))
    assert not ok and problems and "python" in problems[0]
    assert environment_compatible(base, dict(base, jenkins_version=""))[0], "한쪽이 모르면 jenkins_version 은 불일치로 보지 않는다"


def test_reuse_report_rules(tmp_path):
    rep = _report(ALL_PASS)
    prov = {"main_sha": "a" * 40, "tree_hash": "b" * 64, "generator_hash": "c" * 64, "manifest_sha256": "d" * 64}
    p = tmp_path / "r.json"
    p.write_text(json.dumps(rep.to_dict()), encoding="utf-8")
    got, problems = _reuse_report(str(p), prov, rep.environment)
    assert got is not None and problems == []
    # different tree → not reusable
    got, problems = _reuse_report(str(p), dict(prov, tree_hash="e" * 64), rep.environment)
    assert got is None and any("tree_hash" in x for x in problems)
    # different environment → not reusable (env-dependent gates)
    got, problems = _reuse_report(str(p), prov, dict(rep.environment, ansible_version="ansible [core 2.18.0]"))
    assert got is None and any("environment" in x for x in problems)
    # PARTIAL report → not reusable
    rep2 = _report(dict(ALL_PASS, G19="SKIP"))
    p2 = tmp_path / "r2.json"
    p2.write_text(json.dumps(rep2.to_dict()), encoding="utf-8")
    got, problems = _reuse_report(str(p2), prov, rep.environment)
    assert got is None and any("COMPLETE_PASS" in x for x in problems)
    # tampered digest → not reusable
    d = rep.to_dict()
    d["verdict"] = "COMPLETE_PASS"
    d["gates"][3]["details"] = ["edited"]
    p3 = tmp_path / "r3.json"
    p3.write_text(json.dumps(d), encoding="utf-8")
    got, problems = _reuse_report(str(p3), prov, rep.environment)
    assert got is None and any("report_sha256" in x for x in problems)


def _items(sha, fail=None, wrong_sha=None):
    items = []
    for sc in REQUIRED_MAIN:
        items.append({"scenario": sc, "job": "j/main", "build": 1, "result": "SUCCESS", "checkout_sha": (wrong_sha if sc == wrong_sha else sha),
                      "expected": "SUCCESS", "pass": sc != fail})
    for sc in REQUIRED_HARNESS:
        items.append({"scenario": sc, "job": "j/harness", "build": 1, "harness_verdict": "PASS", "checkout_sha": sha, "expected": "PASS", "pass": sc != fail})
    return items


def test_check_evidence_requires_every_scenario_for_the_same_sha():
    sha = "a" * 40
    ev = {"items": _items(sha)}
    assert check_evidence(ev, sha) == []
    assert any("T6" in p for p in check_evidence({"items": _items(sha, fail="T6")}, sha))
    assert any("S1" in p for p in check_evidence({"items": [i for i in _items(sha) if i["scenario"] != "S1"]}, sha))
    assert check_evidence({"items": _items(sha)}, "b" * 40), "다른 SHA 의 증거는 쓸 수 없다"
    ev2 = {"items": _items(sha), "collected_at": "x"}
    ev2["evidence_sha256"] = canonical_digest(ev2)
    assert check_evidence(ev2, sha) == []
    ev2["items"][0]["pass"] = False
    assert any("evidence_sha256" in p for p in check_evidence(ev2, sha))


def test_parse_entry_and_aggregate(tmp_path):
    e = parse_entry("S1=clovirone-cicd/clovirone-server-gather-main:7")
    assert e == {"scenario": "S1", "job": "clovirone-cicd/clovirone-server-gather-main", "build": 7, "expected": "SUCCESS"}
    e = parse_entry("T6=clovirone-cicd/clovirone-server-gather-main:9:UNSTABLE")
    assert e["expected"] == "UNSTABLE"
    e = parse_entry("normal_success=clovirone-cicd/clovirone-server-gather-harness:4")
    assert e["expected"] == "PASS"
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
        return subprocess.CompletedProcess(args, 0, stdout='{"number": 28, "result": "SUCCESS"}', stderr="")

    monkeypatch.setattr(ev.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(ev.subprocess, "run", fake_run)
    netrc = tmp_path / "netrc"
    netrc.write_text("machine x login a password b\n", encoding="utf-8")
    out = ev._curl_json("https://jenkins.invalid/job/x/28/api/json?tree=number,actions[parameters[name,value]]", str(netrc))
    assert out["number"] == 28
    flags = [a for a in seen["args"] if a.startswith("-") and not a.startswith("--")]
    assert any("g" in f for f in flags), seen["args"]
