"""tests/fixtures/finalize_corpus — Layer A oracle corpus 와 tests/scripts/finalize_corpus_check.py (2026-10-03, Plan §6-4).

고정하는 것
  1. 정답지(expected_*)는 지금의 Layer A(scripts/finalize_gather_output.py)가 corpus 입력으로 만드는 것과 같다 — Python 쪽 동치.
     (Groovy 쪽은 Jenkinsfile_ci 의 'Finalize Corpus' stage 가 같은 정답지로 seReconcileRaw 를 대조한다.)
  2. case 마다 "요청 1개 = 결과 1개": 줄 수 == 접수 ip 수, 접수 순서, origin 분류와 by_origin 합이 맞는다.
  3. 요구된 시나리오(normal · 중복 동일 · 중복 충돌 · 절단 · 손상 · checkpoint add-on 중단/완료 · precheck 실패만 · auth 뒤 lost ·
     아무것도 없음 · target_type 불일치 · manifest 밖 ip)가 모두 있고 README 가 case 마다 한 줄씩 설명한다.
  4. 검사기는 변조(줄 · 보고 · origin · 정답지 부재)를 잡고(exit 1), --regenerate 는 현재 정답지를 그대로 다시 만든다(멱등).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CHECK = REPO / "tests" / "scripts" / "finalize_corpus_check.py"
CORPUS = REPO / "tests" / "fixtures" / "finalize_corpus"
sys.path.insert(0, str(CHECK.parent))

import finalize_corpus_check as fcc  # noqa: E402

REQUIRED_SCENARIOS = ("normal", "dup_identical", "dup_conflict", "truncated_tail", "corrupt_middle",
                      "checkpoint_addon_interrupted", "checkpoint_addon_done", "precheck_failed", "auth_proven_then_lost",
                      "nothing", "wrong_target_type", "foreign_ip")


def _run(*args, corpus=CORPUS):
    return subprocess.run([sys.executable, str(CHECK), "--corpus", str(corpus), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def _copy_corpus(tmp_path: Path) -> Path:
    dst = tmp_path / "corpus"
    shutil.copytree(CORPUS, dst)
    return dst


def test_corpus_matches_current_layer_a_oracle():
    r = _run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "RESULT: MATCH" in r.stdout and "mismatches=0" in r.stdout


def test_corpus_has_required_scenarios_and_readme_rows():
    names = sorted(p.name for p in fcc.discover_cases(CORPUS))
    assert len(names) >= 8
    for key in REQUIRED_SCENARIOS:
        assert any(key in n for n in names), key
    readme = (CORPUS / "README.md").read_text(encoding="utf-8")
    for n in names:
        assert f"`{n}`" in readme, f"README 에 {n} 설명 행이 없다"
    assert "--regenerate" in readme and "2026-10-03" in readme and "RFC 5737" in readme


@pytest.mark.parametrize("case_dir", fcc.discover_cases(CORPUS), ids=lambda p: p.name)
def test_each_case_is_complete_and_cardinality_holds(case_dir: Path):
    manifest = fcc.read_manifest(case_dir)
    ips = [str(ip) for ip in manifest["ips"]]
    assert manifest["channel"] in ("os", "esxi", "redfish") and ips
    assert fcc.read_outcome(case_dir)
    lines = fcc._lines((case_dir / fcc.EXPECTED_FINAL).read_text(encoding="utf-8"))
    report = json.loads((case_dir / fcc.EXPECTED_REPORT).read_text(encoding="utf-8"))
    origins = json.loads((case_dir / fcc.EXPECTED_ORIGINS).read_text(encoding="utf-8"))
    assert len(lines) == len(ips) == report["accepted"] == len(origins)
    assert [json.loads(t)["ip"] for t in lines] == ips, "접수 순서"
    assert report["kept"] + report["filled"] == report["accepted"]
    assert report["by_origin"] == {o: Counter(origins).get(o, 0) for o in fcc.ORIGINS}
    assert report["exit_code"] in (0, 2) and report["layer"] == "a"
    keys13 = ["schema_version", "target_type", "collection_method", "ip", "hostname", "vendor", "status",
              "sections", "diagnosis", "meta", "correlation", "errors", "data"]
    for text, origin in zip(lines, origins):
        env = json.loads(text)
        assert set(env) == set(keys13)
        # OUTPUT 줄은 원문 그대로라 키 순서가 다를 수 있다(02_dup_identical 이 일부러 그런 줄을 둔다); 합성 봉투는 정본 순서다.
        if origin == "synthetic":
            assert list(env) == keys13
        assert env["target_type"] == manifest["channel"]
    assert fcc.invariants(case_dir, manifest, lines, report, origins) == []
    assert fcc.classify_origins(case_dir, lines) == origins
    for name in ("gather_manifest.json", "gather_output.json", "gather_checkpoint.jsonl", "gather_progress.jsonl",
                 fcc.EXPECTED_FINAL, fcc.EXPECTED_REPORT, fcc.EXPECTED_ORIGINS):
        p = case_dir / name
        if p.is_file():
            assert b"\r\n" not in p.read_bytes(), f"{p}: CRLF"


def test_corpus_covers_every_origin_and_damage_kind():
    reports = {c.name: json.loads((c / fcc.EXPECTED_REPORT).read_text(encoding="utf-8")) for c in fcc.discover_cases(CORPUS)}
    seen = Counter()
    for rep in reports.values():
        for o, n in rep["by_origin"].items():
            seen[o] += n
        seen["dropped"] += len(rep["dropped"])
        seen["conflicts"] += len(rep["conflicts"])
        seen["truncated_tail"] += len(rep["truncated_tail"])
        seen["corrupt_lines"] += len(rep["corrupt_lines"])
    for key in ("output", "checkpoint", "synthetic", "dropped", "conflicts", "truncated_tail", "corrupt_lines"):
        assert seen[key] >= 1, key
    assert {rep["channel"] for rep in reports.values()} == {"os", "esxi", "redfish"}
    assert {rep["exit_code"] for rep in reports.values()} == {0, 2}


def test_layer_a_synthetic_diagnosis_branches_are_all_present():
    """합성 봉투 4 분기(precheck 보존 · auth 뒤 GATHER_FAILED · lost → AUTH_PROBE_FAILED · OUTPUT_BUILD_FAILED)가 corpus 에 있다."""
    codes = Counter()
    for c in fcc.discover_cases(CORPUS):
        origins = json.loads((c / fcc.EXPECTED_ORIGINS).read_text(encoding="utf-8"))
        for text, o in zip(fcc._lines((c / fcc.EXPECTED_FINAL).read_text(encoding="utf-8")), origins):
            if o == "synthetic":
                d = json.loads(text)["diagnosis"]
                codes[(d["failure_stage"], d["failure_code"])] += 1
                assert d["details"]["finalizer"] == "layer_a"
    for key in (("reachable", "TARGET_UNREACHABLE"), ("port", "TCP_CONNECTION_REFUSED"), ("gather", "GATHER_FAILED"),
                ("auth", "AUTH_PROBE_FAILED"), ("fallback", "OUTPUT_BUILD_FAILED")):
        assert codes[key] >= 1, key


def test_checker_detects_tampered_line_report_origins_and_missing_file(tmp_path):
    corpus = _copy_corpus(tmp_path)
    assert _run(corpus=corpus).returncode == 0

    case = corpus / "03_dup_conflict"
    final = case / fcc.EXPECTED_FINAL
    lines = final.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"status": "partial"', '"status": "success"')
    final.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    r = _run("--case", "03_dup_conflict", corpus=corpus)
    assert r.returncode == 1 and "final[0]" in r.stdout and "RESULT: MISMATCH" in r.stdout

    corpus = _copy_corpus(tmp_path / "b")
    case = corpus / "13_mixed_blank_lines"
    rep = json.loads((case / fcc.EXPECTED_REPORT).read_text(encoding="utf-8"))
    rep["conflicts"] = []
    (case / fcc.EXPECTED_REPORT).write_bytes(json.dumps(rep, ensure_ascii=False, indent=2).encode("utf-8"))
    r = _run("--case", "13_mixed_blank_lines", corpus=corpus)
    assert r.returncode == 1 and "report.conflicts" in r.stdout

    corpus = _copy_corpus(tmp_path / "c")
    case = corpus / "10_nothing_synthetic"
    (case / fcc.EXPECTED_ORIGINS).write_bytes(b'["output", "synthetic"]\n')
    r = _run("--case", "10_nothing_synthetic", corpus=corpus)
    assert r.returncode == 1 and "origins" in r.stdout

    corpus = _copy_corpus(tmp_path / "d")
    (corpus / "01_normal" / fcc.EXPECTED_FINAL).unlink()
    r = _run("--case", "01_normal", corpus=corpus)
    assert r.returncode == 1 and "정답지 없음" in r.stdout


def test_checker_tool_failure_exit_3_for_missing_corpus_or_outcome(tmp_path):
    r = _run(corpus=tmp_path / "nope")
    assert r.returncode == 3 and "corpus 디렉터리 없음" in r.stderr
    corpus = _copy_corpus(tmp_path)
    (corpus / "01_normal" / "outcome.txt").unlink()
    r = _run("--case", "01_normal", corpus=corpus)
    assert r.returncode == 3 and "outcome.txt 없음" in r.stderr
    r = _run("--case", "does_not_exist")
    assert r.returncode == 3


def test_regenerate_is_idempotent_and_writes_lf(tmp_path):
    corpus = _copy_corpus(tmp_path)
    r = _run("--regenerate", corpus=corpus)
    assert r.returncode == 0 and "RESULT: REGENERATED" in r.stdout
    for case in fcc.discover_cases(corpus):
        for name in (fcc.EXPECTED_FINAL, fcc.EXPECTED_REPORT, fcc.EXPECTED_ORIGINS):
            got = (case / name).read_bytes()
            assert b"\r\n" not in got
            assert got == (CORPUS / case.name / name).read_bytes(), f"{case.name}/{name}: 저장된 정답지가 현재 Layer A 결과와 다르다"


def test_report_json_summary(tmp_path):
    out = tmp_path / "summary.json"
    r = _run("--report-json", str(out))
    assert r.returncode == 0
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["mode"] == "verify" and summary["mismatches"] == 0
    assert len(summary["cases"]) == len(fcc.discover_cases(CORPUS))
    assert all(c["problems"] == [] and c["origins"] for c in summary["cases"])
