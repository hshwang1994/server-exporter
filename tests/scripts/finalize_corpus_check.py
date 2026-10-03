#!/usr/bin/env python3
"""finalize_corpus_check.py — Layer A finalizer 를 corpus 위에서 실제로 돌려 정답지와 대조한다 (2026-10-03, Plan §6-4).

Python/Groovy 동치 검증의 **Python 쪽**이다. corpus 의 정답지(expected_*)는 언제나 이 스크립트가 `--regenerate` 로
`scripts/finalize_gather_output.py` 를 실행해 만든 것이라, Layer A 가 oracle 이다. Groovy 쪽(Layer B `seReconcileRaw`)은
`Jenkinsfile_ci` 의 'Finalize Corpus' stage 가 같은 입력과 같은 정답지로 대조한다 (`scripts/jenkins/se_finalize.groovy`).

corpus 구조: tests/fixtures/finalize_corpus/<case>/
  입력  gather_manifest.json (필수) · gather_output.json · gather_checkpoint.jsonl · gather_progress.jsonl · gather_rc.txt · outcome.txt (필수)
  정답  expected_final.jsonl (host 당 1줄, 접수 순서) · expected_report.json (Layer A 보고) ·
        expected_origins.json (host 별 origin — output | checkpoint | synthetic; Groovy 쪽이 비교 규칙을 고르는 데 쓴다)

사용:
  python tests/scripts/finalize_corpus_check.py                               # 전부 대조
  python tests/scripts/finalize_corpus_check.py --case 03_dup_conflict        # 하나만
  python tests/scripts/finalize_corpus_check.py --report-json corpus.json     # 결과 요약 JSON (Jenkins artifact 용)
  python tests/scripts/finalize_corpus_check.py --regenerate                  # 입력을 바꾼 뒤 정답지 재생성 — diff 를 반드시 읽는다

종료 코드: 0 전부 일치 · 1 불일치(또는 corpus 자체의 불변식 위반) · 3 도구 실패(corpus 없음 · Layer A 실행 불가 등)
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

if sys.platform == "win32":  # 콘솔 기본 인코딩(cp949)에서도 한글·대시를 깨지 않고 찍는다 (Jenkins Runner 는 Linux/UTF-8)
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

REPO = Path(__file__).resolve().parents[2]
LAYER_A = REPO / "scripts" / "finalize_gather_output.py"
DEFAULT_CORPUS = REPO / "tests" / "fixtures" / "finalize_corpus"

INPUT_FILES = ("gather_manifest.json", "gather_output.json", "gather_checkpoint.jsonl", "gather_progress.jsonl", "gather_rc.txt")
EXPECTED_FINAL, EXPECTED_REPORT, EXPECTED_ORIGINS = "expected_final.jsonl", "expected_report.json", "expected_origins.json"
ORIGINS = ("output", "checkpoint", "synthetic")

EXIT_OK, EXIT_MISMATCH, EXIT_TOOL = 0, 1, 3


class ToolFailure(Exception):
    pass


def _read(path: Path) -> str:
    # 정답지는 LF 로 저장하지만 Windows 작업 사본에서 CRLF 가 될 수 있다 — 줄 단위 비교라 universal newline 으로 읽는다.
    return path.read_text(encoding="utf-8")


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _write_lf(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def discover_cases(corpus: Path, only: str | None = None) -> list[Path]:
    if not corpus.is_dir():
        raise ToolFailure(f"corpus 디렉터리 없음: {corpus}")
    cases = sorted(p for p in corpus.iterdir() if p.is_dir() and (p / "gather_manifest.json").is_file())
    if only:
        cases = [c for c in cases if c.name == only]
        if not cases:
            raise ToolFailure(f"case 없음: {only}")
    if not cases:
        raise ToolFailure(f"corpus 에 case 가 없다: {corpus}")
    return cases


def read_manifest(case_dir: Path) -> dict:
    try:
        return json.loads(_read(case_dir / "gather_manifest.json"))
    except ValueError as e:
        raise ToolFailure(f"{case_dir.name}: manifest 파싱 실패: {e}") from e


def read_outcome(case_dir: Path) -> str:
    p = case_dir / "outcome.txt"
    if not p.is_file():
        raise ToolFailure(f"{case_dir.name}: outcome.txt 없음")
    outcome = _read(p).strip()
    if not outcome:
        raise ToolFailure(f"{case_dir.name}: outcome.txt 가 비었다")
    return outcome


def run_layer_a(case_dir: Path, python: str, repo_root: Path = REPO) -> tuple[int, list[str], dict, str]:
    """입력만 임시 workspace 로 복사해 Layer A 를 Jenkins 와 같은 CLI 로 실행한다 → (exit, final_lines, report, stderr)."""
    if not LAYER_A.is_file():
        raise ToolFailure(f"Layer A 스크립트 없음: {LAYER_A}")
    outcome = read_outcome(case_dir)
    with tempfile.TemporaryDirectory(prefix="finalize_corpus_") as tmp:
        ws = Path(tmp)
        for name in INPUT_FILES:
            src = case_dir / name
            if src.is_file():
                shutil.copyfile(src, ws / name)
        cmd = [python, str(LAYER_A), "--workspace", str(ws), "--repo-root", str(repo_root), "--outcome", outcome]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ToolFailure(f"{case_dir.name}: Layer A 실행 실패: {e}") from e
        final_path, report_path = ws / "gather_final.jsonl", ws / "gather_finalize_report.json"
        if r.returncode == 3 or not final_path.is_file() or not report_path.is_file():
            raise ToolFailure(f"{case_dir.name}: Layer A exit={r.returncode} (도구 실패) — {r.stderr.strip()[-300:]}")
        final_lines = _lines(_read(final_path))
        try:
            report = json.loads(_read(report_path))
        except ValueError as e:
            raise ToolFailure(f"{case_dir.name}: 보고 JSON 파싱 실패: {e}") from e
    return r.returncode, final_lines, report, r.stderr


def classify_origins(case_dir: Path, final_lines: list[str]) -> list[str]:
    """host 별 origin. OUTPUT 줄은 원문 그대로 통과하므로 gather_output.json 의 줄과 글자까지 같다(=output).
    나머지는 Layer A 가 남기는 표식으로 구분한다: checkpoint 복원은 마지막 errors[].detail 이 'finalized from checkpoint;' 로
    시작하고, 합성 봉투는 diagnosis.details.finalizer == 'layer_a' 다."""
    out_path = case_dir / "gather_output.json"
    output_lines = set(_lines(_read(out_path))) if out_path.is_file() else set()
    origins = []
    for text in final_lines:
        if text in output_lines:
            origins.append("output")
            continue
        env = json.loads(text)
        details = (env.get("diagnosis") or {}).get("details") or {}
        errors = env.get("errors") or []
        if details.get("finalizer") == "layer_a":
            origins.append("synthetic")
        elif errors and str(errors[-1].get("detail", "")).startswith("finalized from checkpoint;"):
            origins.append("checkpoint")
        else:
            origins.append("unknown")
    return origins


def invariants(case_dir: Path, manifest: dict, final_lines: list[str], report: dict, origins: list[str]) -> list[str]:
    """요청 1개 = 결과 1개 계약과 origin 분류의 자기 일관성 — 정답지가 손으로 고쳐졌어도 여기서 걸린다."""
    problems = []
    ips = [str(ip) for ip in manifest.get("ips") or []]
    if len(final_lines) != len(ips):
        problems.append(f"lines={len(final_lines)} != accepted={len(ips)}")
    got_ips = []
    for i, text in enumerate(final_lines):
        try:
            got_ips.append(json.loads(text).get("ip"))
        except ValueError:
            problems.append(f"line {i + 1}: not JSON")
    if got_ips and got_ips != ips[:len(got_ips)]:
        problems.append(f"ip order {got_ips} != manifest {ips}")
    if len(origins) != len(final_lines):
        problems.append(f"origins={len(origins)} != lines={len(final_lines)}")
    if any(o not in ORIGINS for o in origins):
        problems.append(f"origin 분류 불가: {origins}")
    by_origin = report.get("by_origin") or {}
    if by_origin != {o: Counter(origins).get(o, 0) for o in ORIGINS}:
        problems.append(f"by_origin {by_origin} != origins {dict(Counter(origins))}")
    if report.get("accepted") != len(ips) or report.get("kept", 0) + report.get("filled", 0) != len(ips):
        problems.append(f"report accepted/kept/filled 불일치: {report.get('accepted')}/{report.get('kept')}/{report.get('filled')} vs {len(ips)}")
    return problems


def compare_case(case_dir: Path, exit_code: int, final_lines: list[str], report: dict, origins: list[str]) -> list[str]:
    problems = []
    for name in (EXPECTED_FINAL, EXPECTED_REPORT, EXPECTED_ORIGINS):
        if not (case_dir / name).is_file():
            problems.append(f"정답지 없음: {name} (--regenerate 로 만든다)")
    if problems:
        return problems
    exp_lines = _lines(_read(case_dir / EXPECTED_FINAL))
    exp_report = json.loads(_read(case_dir / EXPECTED_REPORT))
    exp_origins = json.loads(_read(case_dir / EXPECTED_ORIGINS))
    if final_lines != exp_lines:
        if len(final_lines) != len(exp_lines):
            problems.append(f"final: lines {len(final_lines)} != expected {len(exp_lines)}")
        for i, (got, exp) in enumerate(zip(final_lines, exp_lines)):
            if got != exp:
                problems.append(f"final[{i}]: 줄이 다르다 — got {got[:140]}… / expected {exp[:140]}…")
    if report != exp_report:
        for key in sorted(set(report) | set(exp_report)):
            if report.get(key) != exp_report.get(key):
                problems.append(f"report.{key}: got {json.dumps(report.get(key), ensure_ascii=False)[:160]} / expected {json.dumps(exp_report.get(key), ensure_ascii=False)[:160]}")
    if exit_code != exp_report.get("exit_code"):
        problems.append(f"exit {exit_code} != expected_report.exit_code {exp_report.get('exit_code')}")
    if origins != exp_origins:
        problems.append(f"origins {origins} != expected {exp_origins}")
    return problems


def regenerate_case(case_dir: Path, final_lines: list[str], report: dict, origins: list[str]) -> None:
    _write_lf(case_dir / EXPECTED_FINAL, "\n".join(final_lines) + "\n")
    _write_lf(case_dir / EXPECTED_REPORT, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    _write_lf(case_dir / EXPECTED_ORIGINS, json.dumps(origins) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--case", default=None, help="이 이름의 case 만")
    ap.add_argument("--python", default=sys.executable, help="Layer A 를 실행할 python (기본: 이 인터프리터)")
    ap.add_argument("--regenerate", action="store_true", help="정답지(expected_*) 를 현재 Layer A 결과로 다시 쓴다")
    ap.add_argument("--report-json", default=None, help="결과 요약을 이 파일에 JSON 으로 쓴다")
    a = ap.parse_args(argv)

    summary = {"corpus": a.corpus, "layer_a": str(LAYER_A), "python": a.python, "platform": platform.platform(),
               "mode": "regenerate" if a.regenerate else "verify", "cases": [], "mismatches": 0}
    try:
        cases = discover_cases(Path(a.corpus), a.case)
        for case_dir in cases:
            manifest = read_manifest(case_dir)
            exit_code, final_lines, report, _ = run_layer_a(case_dir, a.python)
            origins = classify_origins(case_dir, final_lines)
            problems = invariants(case_dir, manifest, final_lines, report, origins)
            if a.regenerate:
                if problems:
                    raise ToolFailure(f"{case_dir.name}: 불변식 위반 상태로는 정답지를 쓰지 않는다 — {problems}")
                regenerate_case(case_dir, final_lines, report, origins)
            else:
                problems += compare_case(case_dir, exit_code, final_lines, report, origins)
            entry = {"name": case_dir.name, "channel": manifest.get("channel"), "accepted": len(manifest.get("ips") or []),
                     "exit_code": exit_code, "by_origin": report.get("by_origin"), "origins": origins, "problems": problems}
            summary["cases"].append(entry)
            summary["mismatches"] += 1 if problems else 0
            tag = "REGEN" if a.regenerate else ("FAIL" if problems else "OK")
            print(f"[corpus] {tag:5s} {case_dir.name:34s} ch={entry['channel']:<7s} accepted={entry['accepted']} exit={exit_code} by_origin={report.get('by_origin')}")
            for p in problems:
                print(f"         - {p}")
    except ToolFailure as e:
        print(f"[corpus] tool failure: {e}", file=sys.stderr)
        summary["tool_failure"] = str(e)
        if a.report_json:
            Path(a.report_json).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return EXIT_TOOL

    if a.report_json:
        Path(a.report_json).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    verdict = "REGENERATED" if a.regenerate else ("MISMATCH" if summary["mismatches"] else "MATCH")
    print(f"[corpus] RESULT: {verdict} cases={len(summary['cases'])} mismatches={summary['mismatches']}")
    return EXIT_MISMATCH if summary["mismatches"] else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
