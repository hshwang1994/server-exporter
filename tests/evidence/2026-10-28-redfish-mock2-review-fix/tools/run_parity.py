"""18 label 개수 정합을 한 번에 돌린다 (2026-10-28 — stdlib). 판별기는 저장소 `tests/scripts/inventory_parity.py` 그대로(label 마다 1회 호출).

미러(원문 트리) × Tier 1 봉투(`<tier1_root>/<label>/gather_output.json`)를 대조하고, label 별 JSON 과 구현 측
`inventory-parity.md` 와 같은 열의 표를 쓴다. 판정은 판별기의 종료 코드 · `verdict` 그대로 옮긴다.

사용: python -I -X utf8 -B run_parity.py <tier1_root> <out_dir> <label>=<mirror_dir> [...]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
TOOL = REPO / "tests" / "scripts" / "inventory_parity.py"


def main():
    tier1, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    rows, bad = [], 0
    for t in sys.argv[3:]:
        label, _, mirror = t.partition("=")
        js = out / f"{label}.json"
        p = subprocess.run([sys.executable, "-B", str(TOOL), "--mirror", mirror, "--envelope-json",
                            str(tier1 / label / "gather_output.json"), "--label", label, "--json", str(js)],
                           capture_output=True, text=True, encoding="utf-8", env=env)
        d = json.loads(js.read_text(encoding="utf-8")) if js.exists() else {}
        ex, co, vd = d.get("exposure") or {}, d.get("collected") or {}, d.get("verdict") or {}
        verdict = "PASS" if vd.get("pass") and p.returncode == 0 else "UNEXPLAINED"
        bad += verdict != "PASS"
        rows.append(f"| {label} | {ex.get('power_state')} | {ex.get('disks_present')}/{ex.get('disks_absent_empty_bay')} | "
                    f"{co.get('disks')} | {ex.get('fc_ports')}(+{len(ex.get('orphan_fc_ndf') or [])}) | {co.get('fc_hbas')} | "
                    f"{verdict} | {', '.join(vd.get('notes') or [])}{'; 미설명 ' + str(vd['unexplained']) if vd.get('unexplained') else ''} | "
                    f"rc {p.returncode} |")
    md = [f"# 디스크 · FC 포트 개수 정합 — `{tier1.as_posix()}`", "",
          f"- 판별기 `tests/scripts/inventory_parity.py` × Tier 1 봉투, label {len(rows)} · 종료 코드 0 아님 {bad}", "",
          "| label | PowerState | 디스크 노출(present/absent·빈 베이) | 디스크 수집 | FC 포트 노출(+orphan NDF) | FC 수집(hbas) | 판정 | 설명 | rc |",
          "|---|---|---|---|---|---|---|---|---|"] + rows
    (out / "_parity.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
