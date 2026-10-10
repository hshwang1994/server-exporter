"""F02 (2026-10-05): 결과 형태 검문 — 한 행의 값 종류 오류가 마무리 전체를 멈추지 않고, 세 검문이 같은 판정을 한다.

- Python Layer A(`scripts/finalize_gather_output.py` shape_gate · load_progress)는 목록·객체 값이 섞여도 예외 없이 그 행만 버린다.
- Groovy 두 곳(`scripts/jenkins/se_finalize.groovy` · `Jenkinsfile_portal`)의 `seEnvelopeShapeReason` 본문은 글자까지 같다 —
  라이브러리를 못 읽은 경로에서도 전송 직전 검문이 같은 규칙으로 돈다. Groovy 판정이 Python 과 같은지는 corpus
  (tests/fixtures/finalize_corpus 15~18)를 Jenkinsfile_ci 'Finalize Corpus' stage 가 대조한다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "callback_plugins"))

import finalize_gather_output as fz  # noqa: E402
from tests.unit.test_finalize_gather_output import _envelope, _run, _ws  # noqa: E402

PORTAL = (REPO / "Jenkinsfile_portal").read_text(encoding="utf-8")
LIB = (REPO / "scripts" / "jenkins" / "se_finalize.groovy").read_text(encoding="utf-8")


def _gate_body(text: str) -> str:
    m = re.search(r"@NonCPS\nString seEnvelopeShapeReason\(.*?\n}\n", text, re.S)
    assert m, "seEnvelopeShapeReason 이 없다"
    return m.group(0)


def test_groovy_gate_bodies_are_identical():
    assert _gate_body(PORTAL) == _gate_body(LIB)


def test_every_groovy_gate_site_uses_the_shared_function():
    assert "keys13" not in PORTAL.split("@NonCPS\nString seEnvelopeShapeReason(")[0], "인라인 13 키 검사가 남아 있다"
    filt = re.search(r"Map seFilterEnvelopeLines\(.*?\n}\n", PORTAL, re.S).group(0)
    assert "seEnvelopeShapeReason(obj, channel, accepted) != null" in filt
    raw = re.search(r"Map seReconcileRaw\(.*?\n}\n", LIB, re.S).group(0)
    assert raw.count("seEnvelopeShapeReason(obj, channel, accepted)") == 2, "OUTPUT · CHECKPOINT 두 문 모두"
    assert "keys13" not in raw


def test_layer_b_result_passes_the_send_gate_too():
    # 8차 R8: 결과 확인 본체는 빌드별 폴더 안에서 도는 seFinalizeIn 이다(seFinalizeAndCallback 은 한계 · 노드 · 폴더만 잡는다).
    #   C1 (2026-10-10): 줄 집합은 회수 후보마다 seEvalCandidate 가 만든다 — 보충 조립 결과도 그 안에서 같은 문을 지난다
    fin = re.search(r"Map seEvalCandidate\(.*?\n}\n", PORTAL, re.S).group(0)
    assert "Map gated = seFilterEnvelopeLines(res.lines, manifestJson)" in fin
    assert "layer_b_gate_dropped=" in fin


@pytest.mark.parametrize("mutate,reason_start", [
    (lambda e: e.__setitem__("ip", ["192.0.2.2"]), "ip type list"),
    (lambda e: e.__setitem__("status", ["success"]), "status type list"),
    (lambda e: e["sections"].__setitem__("memory", ["success"]), "sections shape"),
    (lambda e: e.__setitem__("target_type", {"x": 1}), "target_type type dict"),
    (lambda e: e.__setitem__("meta", ["x"]), "meta/correlation type"),
    (lambda e: e.__setitem__("hostname", 7), "hostname type int"),
    (lambda e: e.__setitem__("schema_version", True), 'schema_version != "1"'),
])
def test_value_type_errors_drop_only_that_row(tmp_path, mutate, reason_start):
    good = _envelope("192.0.2.1")
    bad = _envelope("192.0.2.2")
    mutate(bad)
    ws = _ws(tmp_path, ["192.0.2.1", "192.0.2.2"], outputs=[good, bad], rc=2)
    code, report, final = _run(ws)
    assert code == 2, "손상은 있었지만 처리했다 (종전: TypeError → exit 3, final 없음)"
    assert [e["ip"] for e in final] == ["192.0.2.1", "192.0.2.2"]
    assert final[0] == good, "정상 행은 그대로"
    assert final[1]["status"] == "failed" and report["filled"] == 1
    assert report["dropped"][0]["reason"].startswith(reason_start)


def test_schema_version_integer_one_still_passes():
    env = _envelope("192.0.2.1")
    env["schema_version"] = 1
    assert fz.shape_gate(env, "os", {"192.0.2.1"}) is None


def test_progress_rows_with_non_string_keys_are_skipped(tmp_path):
    ws = _ws(tmp_path, ["192.0.2.1"], progress=[
        {"ts": "t", "host": ["192.0.2.1"], "ip": ["192.0.2.1"], "event": "auth_proven", "task": "x"},
        {"ts": "t", "host": "192.0.2.1", "ip": "192.0.2.1", "event": "cred_load", "task": ["t"],
         "outcome": ["loaded"], "location": {"a": 1}},
    ], rc=2)
    code, report, final = _run(ws)
    assert code == 2 and [c["file"] for c in report["corrupt_lines"]] == ["progress"]
    diag = final[0]["diagnosis"]
    assert diag["failure_code"] == "OUTPUT_BUILD_FAILED", "목록 키 행의 auth_proven 은 쓰이지 않는다"
    assert "last_task" not in diag["details"], "문자열이 아닌 task 는 쓰지 않는다"


def test_non_finite_numbers_are_corrupt_lines(tmp_path):
    good = json.dumps(_envelope("192.0.2.1"), ensure_ascii=False)
    nan = json.dumps(_envelope("192.0.2.2"), ensure_ascii=False).replace('"data": {', '"data": {"x": NaN, ', 1)
    ws = _ws(tmp_path, ["192.0.2.1", "192.0.2.2"], raw_output=good + "\n" + nan + "\n", rc=0)
    code, report, final = _run(ws)
    assert code == 2 and report["corrupt_lines"][0]["line"] == 2
    assert "NaN" not in (ws / "gather_final.jsonl").read_text(encoding="utf-8"), "JSON 이 아닌 값을 수신 측에 보내지 않는다"


@pytest.mark.parametrize("loc", [None, "", "  cj  ", "a b/c<d>", "x" * 80, ["cj"], {"k": "v"}])
def test_location_display_matches_the_callback(loc):
    from tests.unit.test_callback_envelope_reconcile import json_only
    assert fz.display_location(loc) == json_only._display_location(loc)
