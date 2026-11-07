"""Tier 0 산출물 요약 — ci_gate 로그 · JUnit · 묶음별 재현 로그를 표로 낸다(읽기만).
사용: python -I -X utf8 -B tier0_summary.py <tier0 dir>
"""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

T = Path(sys.argv[1])
SUM_RE = re.compile(r"^=*\s*(\d+ (?:passed|failed|error|errors|skipped|xfailed|deselected)[^=]*?)\s*=*$")


def summary_lines(text):
    out = []
    for ln in text.splitlines():
        m = SUM_RE.match(ln.strip())
        if m and re.search(r"\bin [0-9.]+s\b", ln):
            out.append(m.group(1).strip())
    return out


def junit(p):
    if not p.exists():
        return None
    root = ET.parse(p).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    keys = ("tests", "failures", "errors", "skipped")
    agg = {k: sum(int(s.get(k, 0)) for s in suites) for k in keys}
    agg["size"] = p.stat().st_size
    return agg


def gate(d):
    log = T / d / "ci_gate.log"
    if not log.exists():
        print(f"| {d} | (없음) |")
        return
    text = log.read_text(encoding="utf-8", errors="replace")
    res = [ln for ln in text.splitlines() if "RESULT:" in ln]
    rc = [ln for ln in text.splitlines() if ln.startswith("ci_gate_rc=")]
    fails = [ln for ln in text.splitlines() if "-- [ci_gate] FAIL" in ln]
    skips = [ln for ln in text.splitlines() if "-- [ci_gate] 건너뜀" in ln or "skipped (" in ln]
    print(f"### {d}")
    print(f"- result: {res[-1] if res else '-'} / {rc[-1] if rc else '-'}")
    print(f"- step FAIL: {len(fails)}" + ("".join(f"\n  - {f}" for f in fails)))
    print(f"- step skipped: {len(skips)}" + ("".join(f"\n  - {s}" for s in skips)))
    for s in summary_lines(text):
        print(f"- pytest: {s}")
    for name in ("ci_gate_junit_unit.xml", "ci_gate_junit_integration.xml"):
        j = junit(T / d / name)
        print(f"- {name}: {j}")
    print()


def repro(d):
    p = T / d
    if not p.exists():
        print(f"### {d}: (없음)")
        return
    print(f"### {d}")
    print("| 로그 | pytest 요약 | rc |")
    print("|---|---|---|")
    for f in sorted(p.glob("*.log")):
        text = f.read_text(encoding="utf-8", errors="replace")
        s = summary_lines(text)
        rc = [ln for ln in text.splitlines() if ln.startswith("rc=")]
        print(f"| `{f.name}` | {s[-1] if s else '-'} | {rc[-1] if rc else '-'} |")
    print()


for d in ("linux-venv", "windows-clone"):
    gate(d)
for d in ("repro-wsl", "repro-windows"):
    repro(d)
