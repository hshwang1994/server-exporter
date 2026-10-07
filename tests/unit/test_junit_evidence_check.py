"""tests/scripts/junit_evidence_check.py — Time Limits 단계가 Gate 의 pytest 실행 기록(JUnit)을 시험 ID 단위로 대조한다 (2026-10-08).

고정하는 것
  - 지금 모이는 시험 ID 가 기록에 정확히 한 번씩 있고 통과여야 PASS 다(빠짐 · 두 번 · 실패 · 오류 → FAIL, 건너뜀 → PARTIAL).
  - 기록 파일이 있다는 것만으로 PASS 가 되지 않는다: 기록 없음 → PARTIAL, 이 빌드보다 오래된 기록 · 다른 host · 다른 SHA → FAIL.
  - ID → (classname, name) 대응은 pytest 가 실제로 쓴 JUnit 과 같다(매개변수 · 클래스 시험 포함).
"""
from __future__ import annotations

import importlib.util
import platform
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("junit_evidence_check", REPO / "tests" / "scripts" / "junit_evidence_check.py")
jec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jec)

SAMPLE = '''
import pytest


def test_plain():
    assert True


@pytest.mark.parametrize("n", [1, 2])
def test_param(n):
    assert n > 0


class TestGroup:
    def test_in_class(self):
        assert True
'''


@pytest.fixture
def project(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_sample.py").write_text(SAMPLE, encoding="utf-8")
    junit = tmp_path / "junit.xml"
    r = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", "--junitxml", str(junit)],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return tmp_path, junit


FILES = ["tests/test_sample.py"]


def _rewrite(junit: Path, mutate) -> None:
    tree = ET.parse(str(junit))
    mutate(tree.getroot())
    tree.write(str(junit), encoding="utf-8", xml_declaration=True)


def test_every_collected_id_passed_in_the_record_is_pass(project):
    repo, junit = project
    rep = jec.check(junit, FILES, str(repo), time.time() - 600, None)
    assert rep["result"] == "PASS", rep["problems"]
    assert len(rep["expected"]) == 4 and set(rep["outcomes"].values()) == {"passed"}
    assert "tests/test_sample.py::test_param[1]" in rep["outcomes"] and "tests/test_sample.py::TestGroup::test_in_class" in rep["outcomes"]
    assert jec.junit_key("tests/test_sample.py::TestGroup::test_in_class") == ("tests.test_sample.TestGroup", "test_in_class")
    assert len(rep["junit"]["sha256"]) == 64 and rep["junit"]["hostname"] == platform.node()


def test_a_missing_or_duplicated_id_fails(project):
    repo, junit = project

    def drop_one(root):
        for suite in root.iter("testsuite"):
            for tc in list(suite):
                if tc.get("name") == "test_plain":
                    suite.remove(tc)
    _rewrite(junit, drop_one)
    rep = jec.check(junit, FILES, str(repo), None, None)
    assert rep["result"] == "FAIL" and rep["outcomes"]["tests/test_sample.py::test_plain"] == "missing"

    def add_twice(root):
        for suite in root.iter("testsuite"):
            first = [tc for tc in suite if tc.get("name") == "test_param[1]"][0]
            suite.append(ET.fromstring(ET.tostring(first)))
    _rewrite(junit, add_twice)
    rep = jec.check(junit, FILES, str(repo), None, None)
    assert rep["outcomes"]["tests/test_sample.py::test_param[1]"] == "duplicate" and rep["result"] == "FAIL"


def test_skipped_is_partial_and_failure_is_fail(project):
    repo, junit = project

    def skip_one(root):
        tc = [t for t in root.iter("testcase") if t.get("name") == "test_param[2]"][0]
        ET.SubElement(tc, "skipped", {"message": "not on this platform"})
    _rewrite(junit, skip_one)
    rep = jec.check(junit, FILES, str(repo), None, None)
    assert rep["result"] == "PARTIAL", "실행하지 않은 시험을 통과로 세지 않는다"

    def fail_one(root):
        tc = [t for t in root.iter("testcase") if t.get("name") == "test_plain"][0]
        ET.SubElement(tc, "failure", {"message": "boom"})
    _rewrite(junit, fail_one)
    rep = jec.check(junit, FILES, str(repo), None, None)
    assert rep["result"] == "FAIL" and rep["outcomes"]["tests/test_sample.py::test_plain"] == "failed"


def test_no_record_is_partial_not_pass(project):
    repo, junit = project
    junit.unlink()
    rep = jec.check(junit, FILES, str(repo), None, None)
    assert rep["result"] == "PARTIAL" and set(rep["outcomes"].values()) == {"missing"}


def test_a_record_from_an_older_build_or_another_host_fails(project):
    repo, junit = project
    rep = jec.check(junit, FILES, str(repo), time.time() + 3600, None)
    assert rep["result"] == "FAIL" and any("오래됐다" in p for p in rep["problems"])

    def other_host(root):
        for suite in root.iter("testsuite"):
            suite.set("hostname", "some-other-runner")
    _rewrite(junit, other_host)
    rep = jec.check(junit, FILES, str(repo), None, None)
    assert rep["result"] == "FAIL" and any("host" in p for p in rep["problems"])


@pytest.mark.skipif(shutil.which("git") is None, reason="git 없음")
def test_workspace_head_must_be_the_candidate(project):
    repo, junit = project
    for args in (["init", "-q"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "c"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    assert jec.check(junit, FILES, str(repo), None, head)["result"] == "PASS"
    rep = jec.check(junit, FILES, str(repo), None, "0" * 40)
    assert rep["result"] == "FAIL" and any("후보" in p for p in rep["problems"])


def test_cli_exit_codes_and_report(project, tmp_path):
    repo, junit = project
    out = tmp_path / "report.json"
    r = subprocess.run([sys.executable, str(REPO / "tests" / "scripts" / "junit_evidence_check.py"), "--junit", str(junit), "--repo", str(repo),
                        "--report", str(out), *FILES], capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0 and out.is_file() and '"result": "PASS"' in out.read_text(encoding="utf-8")
    r = subprocess.run([sys.executable, str(REPO / "tests" / "scripts" / "junit_evidence_check.py"), "--junit", str(tmp_path / "none.xml"),
                        "--repo", str(repo), *FILES], capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 2, "기록 없음은 PARTIAL(2) — 통과가 아니다"
