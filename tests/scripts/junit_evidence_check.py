#!/usr/bin/env python3
"""tests/scripts/junit_evidence_check.py — 같은 빌드의 pytest 실행 기록(JUnit)으로 지정한 시험 파일이 실제로 돌았는지 확인한다 (2026-10-08).

왜 있나: CI 의 Time Limits 단계가 시험 파일 5개를 다시 돌렸다(약 80초). 그 파일들은 Gate(scripts/ai/ci_gate.sh 의 tests/unit)가
같은 SHA · 같은 Runner · 같은 venv 로 이미 실행한다. 다시 돌리는 대신 그 실행의 기록을 **시험 ID 단위**로 대조한다 —
기록 파일이 있다는 것만으로 PASS 를 만들지 않는다.

확인
  1. 지금 이 환경에서 `pytest --collect-only` 로 모은 시험 ID 가 JUnit 기록에 **정확히 한 번씩** 있다(빠짐 · 두 번 → FAIL)
  2. 각 ID 의 결과가 통과다(실패 · 오류 → FAIL, 건너뜀 → PARTIAL — 실행하지 않은 시험을 통과로 세지 않는다)
  3. 기록이 이 빌드 · 이 환경의 것이다: 파일 수정 시각 >= --not-before(빌드 시작), testsuite hostname == 이 host,
     workspace HEAD == --expect-sha (다르면 FAIL)
  기록 파일이 없으면 PARTIAL(Gate 의 pytest 가 돌지 않았다 — 통과가 아니다).
종료 코드: 0 PASS · 1 FAIL · 2 PARTIAL · 3 도구 실패(수집 자체가 실패)
출력(--report): {result, junit: {path, sha256, mtime, hostname}, expected: [ID…], outcomes: {ID: passed|failed|error|skipped|missing|duplicate}, problems}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

EXIT_PASS, EXIT_FAIL, EXIT_PARTIAL, EXIT_TOOL = 0, 1, 2, 3
NODE_ID = re.compile(r"^\S+\.py::\S")


def collect_ids(files: list[str], repo: str) -> list[str]:
    """이 환경에서 모이는 시험 ID — warnings 요약 줄이 섞이지 않게 warnings 플러그인을 끈다."""
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "-p", "no:warnings", *files]
    r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"pytest --collect-only rc={r.returncode}: {(r.stdout + r.stderr)[-600:]}")
    seen, ids = set(), []
    for line in r.stdout.splitlines():
        line = line.strip()
        if NODE_ID.match(line) and line not in seen:
            seen.add(line)
            ids.append(line)
    return ids


def junit_key(node_id: str) -> tuple[str, str]:
    """pytest 의 JUnit (classname, name) — junitxml.mangle_test_address 와 같은 규칙."""
    path, bracket, params = node_id.partition("[")
    names = path.split("::")
    names[0] = re.sub(r"\.py$", "", names[0].replace("/", "."))
    names[-1] += bracket + params
    return ".".join(names[:-1]), names[-1]


def read_junit(path: Path) -> tuple[dict, str]:
    """{(classname, name): [outcome…]} 와 첫 testsuite 의 hostname."""
    root = ET.parse(str(path)).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    host = suites[0].get("hostname", "") if suites else ""
    cases: dict = {}
    for tc in root.iter("testcase"):
        tags = {child.tag for child in tc}
        outcome = "failed" if "failure" in tags else "error" if "error" in tags else "skipped" if "skipped" in tags else "passed"
        cases.setdefault((tc.get("classname", ""), tc.get("name", "")), []).append(outcome)
    return cases, host


def _say(line: str) -> None:
    """콘솔 한 줄 — 로캘과 무관하게 UTF-8 (Jenkins 콘솔은 UTF-8, Windows 콘솔 cp949 에서도 멈추지 않는다)."""
    out = getattr(sys.stdout, "buffer", None)
    if out is not None:
        out.write((line + "\n").encode("utf-8", "replace"))
        out.flush()
    else:
        sys.stdout.write(line + "\n")


def git_head(repo: str) -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def check(junit: Path, files: list[str], repo: str, not_before: float | None, expect_sha: str | None) -> dict:
    report = {"result": None, "junit": {"path": str(junit)}, "expected": [], "outcomes": {}, "problems": []}
    expected = collect_ids(files, repo)
    report["expected"] = expected
    if not expected:
        report["problems"].append("지정한 파일에서 모인 시험 ID 가 없다")
        report["result"] = "FAIL"
        return report
    if not junit.is_file():
        report["problems"].append("Gate 의 JUnit 기록이 없다 — pytest 가 돌지 않았거나 기록을 남기지 않았다")
        report["outcomes"] = {i: "missing" for i in expected}
        report["result"] = "PARTIAL"
        return report
    raw = junit.read_bytes()
    st = junit.stat()
    cases, host = read_junit(junit)
    report["junit"].update({"sha256": hashlib.sha256(raw).hexdigest(), "mtime": int(st.st_mtime), "hostname": host, "testcases": sum(len(v) for v in cases.values())})
    fail = []
    if not_before is not None and st.st_mtime < not_before:
        fail.append(f"JUnit 기록이 이 빌드보다 오래됐다(mtime {int(st.st_mtime)} < 빌드 시작 {int(not_before)})")
    this_host = platform.node()
    if host and host != this_host:
        fail.append(f"JUnit 기록의 host {host!r} 가 이 host {this_host!r} 와 다르다")
    if expect_sha:
        head = git_head(repo)
        if head != expect_sha:
            fail.append(f"workspace HEAD {head or '-'} != 후보 {expect_sha}")
    skipped = []
    for node_id in expected:
        got = cases.get(junit_key(node_id), [])
        if not got:
            outcome = "missing"
        elif len(got) > 1:
            outcome = "duplicate"
        else:
            outcome = got[0]
        report["outcomes"][node_id] = outcome
        if outcome in ("missing", "duplicate", "failed", "error"):
            fail.append(f"{node_id}: {outcome}")
        elif outcome == "skipped":
            skipped.append(node_id)
    report["problems"] = fail + [f"{i}: skipped (실행하지 않았다)" for i in skipped]
    report["result"] = "FAIL" if fail else ("PARTIAL" if skipped else "PASS")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--junit", required=True, help="Gate 의 pytest JUnit 기록 (ci_gate.sh 의 CI_GATE_JUNIT_DIR)")
    ap.add_argument("--repo", default=".", help="pytest rootdir · git workspace (기본 현재 폴더)")
    ap.add_argument("--not-before", type=float, default=None, help="이 epoch 이후에 쓰인 기록만 이 빌드의 것으로 본다")
    ap.add_argument("--expect-sha", default="", help="workspace HEAD 가 이 commit 이어야 한다(후보 SHA)")
    ap.add_argument("--report", default="", help="결과 JSON")
    ap.add_argument("files", nargs="+", help="확인할 시험 파일")
    a = ap.parse_args(argv)
    try:
        report = check(Path(a.junit), a.files, a.repo, a.not_before, a.expect_sha or None)
    except (RuntimeError, ET.ParseError, OSError) as e:
        _say(f"[junit 대조] 도구 실패: {e}")
        if a.report:
            with open(a.report, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps({"result": "ERROR", "problems": [str(e)]}, ensure_ascii=False, indent=1))
        return EXIT_TOOL
    if a.report:
        with open(a.report, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(report, ensure_ascii=False, indent=1))
    counts: dict = {}
    for v in report["outcomes"].values():
        counts[v] = counts.get(v, 0) + 1
    _say(f"[junit 대조] {report['result']} — 시험 {len(report['expected'])}건 {counts} 기록 {report['junit'].get('sha256', '-')[:12]}"
         f" host={report['junit'].get('hostname', '-')}")
    for p in report["problems"][:20]:
        _say(f"[junit 대조]   {p}")
    return {"PASS": EXIT_PASS, "FAIL": EXIT_FAIL, "PARTIAL": EXIT_PARTIAL}[report["result"]]


if __name__ == "__main__":
    sys.exit(main())
