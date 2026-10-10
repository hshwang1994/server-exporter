"""jenkins/jobs/clovirone-server-gather-ci/config.xml ↔ Jenkinsfile_ci ↔ evidence.REQUIRED_* — one Harness list (2026-10-10 HC-01).

Jenkins keeps the previous build's parameter defaults until the next run, and the repository XML is the restore copy of the job.
When the three disagreed (XML 12/4 · live 45/21 · evidence 50/23 on 2026-10-10) a default-parameter CI run could not produce promotion
evidence. The XML copy must carry the same lists as the Jenkinsfile, and both must equal the sets promotion requires."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.source_text

REPO = Path(__file__).resolve().parents[2]
CI_PATH = REPO / "Jenkinsfile_ci"
XML_PATH = REPO / "jenkins" / "jobs" / "clovirone-server-gather-ci" / "config.xml"
if not CI_PATH.is_file() or not XML_PATH.is_file():
    pytest.skip("Jenkinsfile_ci / job XML 없음 — main 전용", allow_module_level=True)
CI = CI_PATH.read_text(encoding="utf-8")
XML = XML_PATH.read_text(encoding="utf-8")


def _jf(name):
    m = re.search(r"string\(name: '%s', defaultValue: '([^']*)'" % name, CI)
    assert m, name
    return [x for x in m.group(1).split(",") if x]


def _xml(name):
    m = re.search(r"<name>%s</name>\s*<defaultValue>([^<]*)</defaultValue>" % name, XML)
    assert m, name
    return [x for x in m.group(1).split(",") if x]


@pytest.mark.parametrize("param", ["HARNESS_SCENARIOS", "HARNESS_TREE_SCENARIOS"])
def test_job_xml_default_equals_jenkinsfile_default(param):
    assert _xml(param) == _jf(param), f"{param}: jenkins/jobs XML must be regenerated from Jenkinsfile_ci"


def test_defaults_equal_the_required_promotion_sets():
    from scripts.ai.prodgen.evidence import REQUIRED_HARNESS, REQUIRED_HARNESS_TREE
    assert set(_jf("HARNESS_SCENARIOS")) == set(REQUIRED_HARNESS)
    assert set(_jf("HARNESS_TREE_SCENARIOS")) == set(REQUIRED_HARNESS_TREE)
    assert len(_jf("HARNESS_SCENARIOS")) == len(set(_jf("HARNESS_SCENARIOS"))), "no duplicates"


def test_other_string_params_in_xml_match_jenkinsfile_defaults():
    for name in ("PROMOTE_SHA", "BOOTSTRAP_BASELINE", "HARNESS_JOB", "E2E_MAIN_ENTRIES"):
        assert _xml(name) == _jf(name), name
