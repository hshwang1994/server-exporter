"""작업자 coverage.json 6개 -> 11대 x 12영역 = 132칸 판정표 (json + md).
사용: python aggregate_coverage.py <analysis_dir> <out_dir>
coverage.json 허용 형태:
  A) {"<server>": {"_area": {state, evidence}, "<field>": {state, evidence}, ...}}            (단일 영역 보고서)
  B) {"<area>": {"<server>": {"_area": {...}, "<field>": {...}}}}                               (다중 영역 보고서)
  C) {"<server>": {"<area>": {"_area": {...}, "<field>": {...}}}}                               (다중 영역, 서버 우선)
영역 칸 상태가 없으면 필드 상태에서 유도: ISSUE > PASS > MOCK_LIMITATION > NOT_APPLICABLE > NOT_CHECKED.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

SERVERS = ["csus3200_01", "csus3200_02", "csus3200_03", "dl380_gen12_01", "dl380_gen12_02", "dl380_gen12_03", "dl380_gen12_04",
           "sr650_v4_01", "sr650_v4_02", "sr650_v4_03", "sr650_v4_04"]
AREAS = ["cpu", "system", "network", "storage", "memory", "firmware", "bios", "thermal", "hardware", "bmc", "power", "multi_node"]
REPORT_AREAS = {"01": ["system", "hardware", "multi_node"], "02": ["cpu", "memory"], "03": ["network", "storage"],
                "04": ["firmware", "bios"], "05": ["thermal", "power"], "06": ["bmc"]}
STATES = ["ISSUE", "PASS", "MOCK_LIMITATION", "NOT_APPLICABLE", "NOT_CHECKED"]


def norm_state(s):
    s = (s or "").strip().upper().replace("-", "_").replace(" ", "_")
    if s in STATES:
        return s
    if s.startswith("ISSUE"):
        return "ISSUE"
    if s in ("OK", "PASSED"):
        return "PASS"
    if s.startswith("NOT_APP") or s == "N/A" or s == "NA":
        return "NOT_APPLICABLE"
    if s.startswith("MOCK"):
        return "MOCK_LIMITATION"
    return "NOT_CHECKED"


def derive(cells):
    states = [norm_state(c.get("state")) for c in cells.values() if isinstance(c, dict)]
    for s in STATES:
        if s in states:
            return s
    return "NOT_CHECKED"


def cell_from(block):
    """block = {"_area": {...}, "<field>": {...}}  -> (state, evidence, field_states)"""
    if not isinstance(block, dict):
        return "NOT_CHECKED", "coverage.json 에 항목 없음", {}
    fields = {k: v for k, v in block.items() if k != "_area" and isinstance(v, dict)}
    area = block.get("_area") if isinstance(block.get("_area"), dict) else None
    if area and area.get("state"):
        return norm_state(area.get("state")), str(area.get("evidence") or "")[:300], {k: norm_state(v.get("state")) for k, v in fields.items()}
    return derive(fields), "필드 상태에서 유도", {k: norm_state(v.get("state")) for k, v in fields.items()}


def main():
    adir = Path(sys.argv[1]); out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
    grid = {s: {a: {"state": "NOT_CHECKED", "evidence": "보고서 없음", "report": None, "fields": {}} for a in AREAS} for s in SERVERS}
    for rep, areas in REPORT_AREAS.items():
        files = sorted(adir.glob(f"{rep}-*.coverage.json"))
        if not files:
            continue
        cov = json.load(open(files[0], encoding="utf-8"))
        for area in areas:
            for s in SERVERS:
                block = None
                if s in cov and isinstance(cov[s], dict) and isinstance(cov[s].get(f"_area_{area}"), dict) and "state" in cov[s][f"_area_{area}"]:
                    # 형태 D (작업자 01 형식): {"<server>": {"_area_<area>": {state, evidence}, "<area>.<field>": {state, evidence}, ...}}
                    block = {k.split(".", 1)[1]: v for k, v in cov[s].items() if k.startswith(area + ".") and isinstance(v, dict)}
                    block["_area"] = cov[s][f"_area_{area}"]
                elif s in cov and isinstance(cov[s], dict) and isinstance(cov[s].get("_area"), dict) and isinstance(cov[s]["_area"].get(area), dict) and "state" in cov[s]["_area"][area]:
                    # 형태 C' (작업자 02 형식): {"<server>": {"_area": {"<area>": {state, evidence}}, "<area>": {field: {...}}}}
                    block = dict(cov[s].get(area) or {})
                    block["_area"] = cov[s]["_area"][area]
                elif area in cov and isinstance(cov[area], dict) and s in cov[area]:          # B
                    block = cov[area][s]
                elif s in cov and isinstance(cov[s], dict) and area in cov[s] and isinstance(cov[s][area], dict) and ("_area" in cov[s][area] or any(isinstance(v, dict) and "state" in v for v in cov[s][area].values())):  # C
                    block = cov[s][area]
                elif s in cov and isinstance(cov[s], dict) and len(areas) == 1:              # A
                    block = cov[s]
                st, ev, fs = cell_from(block)
                grid[s][area] = {"state": st, "evidence": ev, "report": files[0].name, "fields": fs}
    counts = {st: 0 for st in STATES}
    for s in SERVERS:
        for a in AREAS:
            counts[grid[s][a]["state"]] += 1
    json.dump({"servers": SERVERS, "areas": AREAS, "grid": grid, "counts": counts, "total": len(SERVERS) * len(AREAS)},
              open(out / "coverage-132.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    md = ["# 11대 x 12 영역 = 132칸 판정표 (2026-10-26)", "",
          f"집계: " + ", ".join(f"{k} {v}" for k, v in counts.items()) + f" / 총 {len(SERVERS) * len(AREAS)}칸", "",
          "상태: PASS=실측과 일치 / ISSUE=이슈 있음(보고서 ID 참조) / NOT_APPLICABLE=계약·adapter 상 해당 없음 / MOCK_LIMITATION=Mock·재생 한계로 판정 불가 / NOT_CHECKED=미검토", "",
          "| server | " + " | ".join(AREAS) + " |", "|---|" + "---|" * len(AREAS)]
    for s in SERVERS:
        md.append(f"| {s} | " + " | ".join(grid[s][a]["state"] for a in AREAS) + " |")
    md += ["", "## 칸별 근거 (영역별 보고서의 `_area.evidence` 또는 필드 유도)", ""]
    for a in AREAS:
        md.append(f"### {a}")
        for s in SERVERS:
            c = grid[s][a]
            fs = ", ".join(f"{k}:{v}" for k, v in c["fields"].items()) if c["fields"] else "-"
            md.append(f"- **{s}** [{c['state']}] ({c['report'] or '보고서 없음'}) {c['evidence']} — 필드: {fs}")
        md.append("")
    open(out / "coverage-132.md", "w", encoding="utf-8", newline="\n").write("\n".join(md) + "\n")
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
