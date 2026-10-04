"""tests/jenkins/harness/perf_observe.py · perf_observe_report.py (2026-10-04 최종 실행 지시 §7 — Runner 자원 관측, 읽기 전용).

고정하는 것
  1. 집계는 빌드(SE_BUILD_ID)별이다: peak PSS · worker 최대/peak 시 · 메인 PSS · worker 당 PSS(peak/최대/중앙) · 겹침(같은 샘플의 다른 빌드) · 겹친 합.
  2. 활성 worker = ansible-playbook cmdline 프로세스 − 메인(부모가 같은 빌드의 ansible-playbook 이 아닌 것). configured forks 가 아니다.
  3. PSS 를 못 읽은 프로세스가 있으면 pss_known_ratio < 1 로 드러난다(하한 표시).
  4. 샘플러는 /proc 만 읽는다 — 쓰기·신호·종료 호출이 없다(소스 검사). Jenkinsfile_perf_observe 는 NODE_NAME 필수 · archive 2 파일 · LF.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "tests" / "jenkins" / "harness"

pytestmark = pytest.mark.source_text   # 저장소 메타(jenkins/jobs config · Harness Jenkinsfile)를 읽는다 — G14 overlay(production tree) 제외 (CI #17 G14 실패 원인)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, HARNESS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


report = _load("perf_observe_report")
observe = _load("perf_observe")


def _row(ts, builds, ma=6_000_000, sf=1_000_000):
    return {"ts": ts, "mem_total_kb": 7_700_000, "mem_available_kb": ma, "swap_total_kb": 2_000_000, "swap_free_kb": sf, "load1": 0.5,
            "cpu_idle": 100, "cpu_total": 400, "builds": builds}


def _build(pss, workers, main_pss, procs=None, pss_known=None):
    n = procs if procs is not None else workers + 1
    return {"procs": n, "pss_kb": pss, "rss_kb": pss + 10_000, "pss_known": (pss_known if pss_known is not None else n),
            "playbook_procs": workers + 1, "active_workers": workers, "main_pid": 100, "main_pss_kb": main_pss, "ssh_procs": 0,
            "other_procs": 0, "pids": []}


def test_report_aggregates_per_build_with_workers_overlap_and_lower_bound_marker(tmp_path):
    rows = [
        _row(1000.0, {}, ma=6_100_000),
        _row(1002.0, {"jenkins-main-7": _build(200_000, 4, 80_000)}),
        _row(1004.0, {"jenkins-main-7": _build(330_000, 8, 90_000), "jenkins-prod-9": _build(150_000, 2, 70_000, pss_known=2)}, ma=5_700_000, sf=990_000),
        _row(1006.0, {"jenkins-main-7": _build(250_000, 4, 85_000)}),
        _row(1008.0, {}),
    ]
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    rep = report.summarise(report.load_samples(str(p)), "Runner03")
    by = {b["build_id"]: b for b in rep["builds"]}
    m = by["jenkins-main-7"]
    assert m["samples"] == 3 and m["duration_s"] == 4.0 and m["peak_pss_mb"] == round(330_000 / 1024, 1)
    assert m["peak_active_workers"] == 8 and m["workers_at_peak"] == 8 and m["main_pss_mb_at_peak"] == round(90_000 / 1024, 1)
    assert m["per_worker_pss_mb_at_peak"] == round((330_000 - 90_000) / 8 / 1024, 1), "worker 당 PSS = (트리 PSS − 메인) / 살아 있는 worker"
    assert m["per_worker_pss_mb_max"] == round(max((200_000 - 80_000) / 4, (330_000 - 90_000) / 8, (250_000 - 85_000) / 4) / 1024, 1)
    assert m["overlapped_with"] == ["jenkins-prod-9"] and m["combined_peak_pss_mb"] == round(480_000 / 1024, 1)
    assert m["mem_available_min_mb"] == round(5_700_000 / 1024, 1) and m["mem_available_drop_mb"] == round(400_000 / 1024, 1)
    assert m["swap_delta_mb"] == round(10_000 / 1024, 1) and m["pss_known_ratio"] == 1.0
    pr = by["jenkins-prod-9"]
    assert pr["pss_known_ratio"] == round(2 / 3, 3) < 1, "PSS 를 못 읽은 프로세스가 있으면 하한 표시"
    assert rep["combined_peak_pss_mb"] == round(480_000 / 1024, 1) and rep["combined_workers_at_peak"] == 10
    md = report.to_markdown([rep])
    assert "jenkins-main-7" in md and "Runner03" in md and md.count("\n") >= 4


def test_report_cli_writes_json_and_markdown(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text(json.dumps(_row(1.0, {"b": _build(100_000, 1, 50_000)})) + "\n", encoding="utf-8")
    out, md = tmp_path / "r.json", tmp_path / "r.md"
    assert report.main(["--samples", str(p), "--label", "n1", "--out", str(out), "--md", str(md)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data[0]["node"] == "n1" and data[0]["builds"][0]["build_id"] == "b" and md.read_text(encoding="utf-8").startswith("| 빌드")


def test_sampler_is_read_only_and_attributes_by_build_id_env():
    src = (HARNESS / "perf_observe.py").read_text(encoding="utf-8")
    assert "SE_BUILD_ID=" in src and "/environ" in src or "\"environ\"" in src
    for forbidden in ("os.kill", "signal.", "subprocess", "os.remove", "shutil.rmtree", "open(os.path.join(PROC, str(pid), \"environ\"), \"w"):
        assert forbidden not in src, f"읽기 전용 관측기에 {forbidden} 이 있다"
    assert re.search(r'open\([^)]*"w"', src.replace("\n", " ")).group(0).count('"w"') == 1 or src.count('"w"') <= 2, "쓰기는 결과 파일(out/meta)뿐"
    # active worker 정의: ansible-playbook 프로세스 − 메인(부모가 같은 빌드의 ansible-playbook 이 아닌 것)
    assert "mains = [p for p in procs if p[\"ppid\"] not in pids]" in src and 'b["active_workers"] = max(0, len(procs) - len(mains))' in src
    assert "smaps_rollup" in src and "Pss:" in src


def test_perf_observe_jenkinsfile_contract():
    jf = (HARNESS / "Jenkinsfile_perf_observe").read_bytes()
    assert b"\r\n" not in jf
    text = jf.decode("utf-8")
    assert "node(nodeName)" in text and "NODE_NAME 이 필요하다" in text
    assert "perf_observe.py --duration" in text and "archiveArtifacts(artifacts: 'perf_observe.jsonl,perf_observe_meta.json'" in text
    assert "checkout scm" in text and "timeout(time: 60, unit: 'MINUTES')" in text
    cfg = (REPO / "jenkins/jobs/clovirone-server-gather-perf-observe/config.xml").read_text(encoding="utf-8")
    assert "<scriptPath>tests/jenkins/harness/Jenkinsfile_perf_observe</scriptPath>" in cfg and "<name>*/main</name>" in cfg
    assert "<lightweight>true</lightweight>" in cfg and "<name>NODE_NAME</name>" in cfg
