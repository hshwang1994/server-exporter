"""작업자 보고서 §4 의 이슈 헤딩을 기계 추출 -> issues_raw.json / issues_raw.md (ID, 심각도, 제목, 보고서, 확실성 힌트).
사용: python extract_issues.py <analysis_dir> <out_dir>
형식 차이를 허용: '### <ID> [SEV] 제목', '### <ID> — 제목 (SEV)', '### <ID> — 제목' + 다음 줄 '- 심각도: **SEV**'.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ID_RE = re.compile(r"^###\s+(?P<id>0[1-6]-[a-z_]+-\d{3})\s*(?P<rest>.*)$")
SEV_IN = re.compile(r"\b(HIGH|MED|LOW)\b")
CERT = re.compile(r"확실성[:：]?\s*\**\s*(확정|추정|검증불가|검증 불가|가설)")


def parse(path: Path):
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    in4 = False
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("## 4"):
            in4 = True
        elif ln.startswith("## ") and in4 and not ln.startswith("## 4"):
            in4 = False
        if in4:
            m = ID_RE.match(ln.strip())
            if m:
                rest = m.group("rest").strip()
                sev = None
                sm = SEV_IN.search(rest)
                if sm:
                    sev = sm.group(1)
                title = re.sub(r"\s*[\[(]\s*(HIGH|MED|LOW)[^\])]*[\])]\s*", " ", rest).strip(" —-–:")
                # 다음 12줄에서 심각도/확실성 보강
                cert = None
                for j in range(i + 1, min(i + 14, len(lines))):
                    if lines[j].startswith("### "):
                        break
                    if sev is None:
                        s2 = re.search(r"심각도[:：]?\s*\**\s*(HIGH|MED|LOW)", lines[j])
                        if s2:
                            sev = s2.group(1)
                    if cert is None:
                        c2 = CERT.search(lines[j])
                        if c2:
                            cert = c2.group(1)
                out.append({"id": m.group("id"), "severity": sev or "?", "title": title[:160], "certainty": cert, "report": path.name, "line": i + 1})
        i += 1
    return out


def main():
    adir = Path(sys.argv[1]); out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
    issues = []
    for f in sorted(adir.glob("0[1-6]-*.md")):
        issues.extend(parse(f))
    json.dump(issues, open(out / "issues_raw.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    sev_order = {"HIGH": 0, "MED": 1, "LOW": 2, "?": 3}
    md = ["| ID | 심각도 | 확실성 | 제목 | 보고서:행 |", "|---|---|---|---|---|"]
    for it in sorted(issues, key=lambda x: (sev_order.get(x["severity"], 9), x["id"])):
        md.append(f"| {it['id']} | {it['severity']} | {it['certainty'] or '-'} | {it['title']} | {it['report']}:{it['line']} |")
    open(out / "issues_raw.md", "w", encoding="utf-8", newline="\n").write("\n".join(md) + "\n")
    from collections import Counter
    print("issues:", len(issues), dict(Counter(i["severity"] for i in issues)), "reports:", sorted({i["report"] for i in issues}))


if __name__ == "__main__":
    main()
