#!/usr/bin/env python3
"""rule 95 R1 의심 패턴 12종 자동 검출 (server-exporter 도메인).

production code (Python / YAML)에서 의심 패턴 grep + 라인 출력. advisory 도구.
TDD 작성 / 코드 리뷰 / harness-cycle observer 단계에서 활용.

Usage:
    python scripts/ai/scan_suspicious_patterns.py [--target <dir>] [--strict]

Patterns (rule 95 R1):
    1. Ansible default(omit) 누락 (vendor-specific 변수 직접 참조)
    2. set_fact 재정의로 fragment 침범 (rule 22)
    3. Jinja2 정규식 dead code
    4. adapter score 동률 처리 (priority 동률)
    5. is none / is undefined / length == 0 혼동
    6. 빈 callback message
    7. int() cast 미방어
    8. Single-vendor 분기 silent (다른 vendor skip)
    9. adapter_loader self-reference (순환 include)
    10. mutable / immutable 혼동 (Ansible vars dict)
    11. 외부 시스템 계약 drift (rule 96 — origin 주석 누락 adapter)

Exit codes:
    0 = 의심 0건
    2 = 의심 발견 (advisory — 즉시 수정 의무 아님)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# 검사 대상
SCAN_DIRS = [
    "common", "os-gather", "esxi-gather", "redfish-gather",
    "filter_plugins", "lookup_plugins", "module_utils", "callback_plugins",
    "adapters",
]
EXCLUDE_PATTERNS = [
    re.compile(r"\.git/"),
    re.compile(r"__pycache__/"),
    re.compile(r"\.pytest_cache/"),
    re.compile(r"tests/"),
    re.compile(r"vault/"),
]


def _is_excluded(rel: str) -> bool:
    return any(p.search(rel) for p in EXCLUDE_PATTERNS)


# 패턴 정의 (rule 95 R1)
PATTERNS = [
    {
        "id": 1,
        "name": "Ansible default(omit) 누락",
        "regex": re.compile(r"\{\{\s*[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*\s*\}\}"),
        "files": (".yml", ".yaml"),
        "exclude_lines": [re.compile(r"\|\s*default\s*\("), re.compile(r"^\s*#")],
        "advisory": "변수 참조에 default(...) 또는 default(omit) 권장",
    },
    {
        "id": 2,
        "name": "set_fact로 누적 변수 직접 수정 — fragment 침범 (rule 22)",
        "regex": re.compile(r"set_fact\s*:\s*$"),
        "files": (".yml", ".yaml"),
        # rule 11 R1: common/tasks/normalize/ 안의 builder는 누적 변수 set_fact 허용
        "exclude_paths": [re.compile(r"common/tasks/normalize/")],
        # set_fact 다음 indent 블록의 변수 키가 누적 변수와 매치되면 침범
        "set_fact_check_keys": [
            re.compile(r"^\s+_collected_data\s*:"),
            re.compile(r"^\s+_collected_errors\s*:"),
            re.compile(r"^\s+_supported_sections\s*:"),
            re.compile(r"^\s+_collected_supported\s*:"),
        ],
        "advisory": "set_fact로 누적 변수 (_collected_data / _collected_errors / _supported_sections) "
                    "직접 수정은 rule 22 fragment 침범. 자기 fragment만 만들어야 함 "
                    "(_data_fragment / _sections_<self>_*_fragment / _errors_fragment).",
    },
    {
        "id": 3,
        "name": "Jinja2 정규식 dead code",
        "regex": re.compile(r"regex_search\([^)]*\)\s*\|\s*default\(['\"]['\"]"),
        "files": (".yml", ".yaml"),
        "advisory": "regex_search 결과 빈 string fallback이 무의미 (이미 None/false 처리)",
    },
    {
        "id": 4,
        "name": "Adapter priority 동률 의심 (같은 vendor 내)",
        "regex": re.compile(r"^priority:\s*(\d+)\s*$"),
        "files": (".yml",),
        "scope": "adapters/",
        "advisory": "같은 vendor 내 priority 동률 시 정렬 결과 불확정 — score-adapter-match로 확인",
        "vendor_grouped": True,  # post-process: 같은 (channel, vendor) 그룹 안에서만 동률 판정
    },
    {
        "id": 5,
        "name": "is none / is undefined / length == 0 혼동",
        "regex": re.compile(r"(is\s+none|is\s+undefined|\|\s*length\s*==\s*0)"),
        "files": (".yml", ".yaml"),
        "exclude_lines": [re.compile(r"#\s*rule\s*95\s*R1\s*#5\s*ok", re.IGNORECASE)],
        "advisory": "Ansible 변수 상태 분기 — 의도 명확히 (none vs undefined vs 빈 list 의도 다름). "
                    "의도된 분기는 라인 끝에 '# rule 95 R1 #5 ok: <의도>' 주석으로 silence",
    },
    {
        "id": 6,
        "name": "빈 callback message (errors[]에 message 없이 빈 dict)",
        "regex": re.compile(r"errors\s*:\s*\[\s*\{\s*\}\s*\]"),
        "files": (".yml", ".yaml", ".py"),
        "advisory": "errors entry는 message 필드 필수",
    },
    {
        "id": 7,
        "name": "int() cast 미방어",
        "regex": re.compile(r"\bint\(\s*[a-z_][a-z0-9_.\[\]'\"]*\s*\)"),
        "files": (".py",),
        "exclude_lines": [
            re.compile(r"try\s*:"),
            re.compile(r"except"),
            re.compile(r"^\s*#"),
            re.compile(r"_safe_int\s*\("),  # helper 사용은 안전
            re.compile(r"def\s+_safe_int"),
            re.compile(r"#\s*rule\s*95\s*R1\s*#?7\s*ok", re.IGNORECASE),  # 인라인 silence
        ],
        "advisory": "int() ValueError 처리 — try/except 또는 _safe_int(...) helper 권장. "
                    "의도된 분기는 라인 끝에 '# rule 95 R1 #7 ok: <의도>' 주석으로 silence",
    },
    {
        "id": 9,
        "name": "adapter_loader self-reference 의심",
        "regex": re.compile(r"include\s*:\s*adapter_loader|lookup\(\s*['\"]adapter_loader"),
        "files": (".py", ".yml"),
        "scope": "lookup_plugins/",
        # docstring + 주석 라인은 분기 코드 아님 → false positive
        "exclude_lines": [re.compile(r"^\s*#"), re.compile(r"^\s*['\"]{3}")],
        "advisory": "adapter_loader가 자기 자신을 호출하는 경로 검토 (순환)",
    },
    {
        "id": 11,
        "name": "Adapter origin 주석 누락 (rule 96 R1)",
        "regex": re.compile(r"^priority:"),
        "files": (".yml",),
        "scope": "adapters/",
        "advisory": "adapter 첫 30 줄에 vendor / firmware / tested_against / oem_path 주석 필요",
        "check_metadata_comment": True,
    },
]


def _adapter_vendor_key(rel: str) -> Tuple[str, str]:
    """adapters/<channel>/<vendor>_<rest>.yml 에서 (channel, vendor) 추출.

    예: adapters/redfish/dell_idrac9.yml → ('redfish', 'dell')
        adapters/esxi/esxi_8x.yml      → ('esxi', 'esxi')
    """
    parts = rel.split("/")
    if len(parts) < 2 or parts[0] != "adapters":
        return ("", "")
    channel = parts[1] if len(parts) >= 3 else "registry"
    if len(parts) < 3:
        stem = parts[1].rsplit(".", 1)[0]
    else:
        stem = parts[2].rsplit(".", 1)[0]
    vendor = stem.split("_", 1)[0]
    return (channel, vendor)


def scan_file(path: Path, repo_root: Path) -> List[Tuple[int, str, int, str]]:
    """파일을 패턴별로 스캔. 위반 list 반환."""
    rel = path.relative_to(repo_root).as_posix()
    if _is_excluded(rel):
        return []
    findings = []

    suffix = path.suffix
    try:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
    except Exception:
        return []

    for pattern in PATTERNS:
        if suffix not in pattern["files"]:
            continue
        if "scope" in pattern and pattern["scope"] not in rel:
            continue
        if "exclude_paths" in pattern:
            if any(ex.search(rel) for ex in pattern["exclude_paths"]):
                continue

        # Adapter origin 주석 검사 (특수 처리 — rule 96 R1)
        if pattern.get("check_metadata_comment"):
            head = "\n".join(lines[:30])
            if not any(kw in head.lower() for kw in
                       ("vendor:", "firmware:", "tested_against:", "# origin:", "# 출처:")):
                findings.append((pattern["id"], rel, 1, pattern["advisory"]))
            continue

        # set_fact 다음 indent 블록 분석 (rule 22 — 누적 변수 침범만 검출)
        if pattern.get("set_fact_check_keys"):
            for lineno, line in enumerate(lines, start=1):
                if not pattern["regex"].search(line):
                    continue
                # set_fact 라인의 indent 측정 후, 다음 라인부터 더 큰 indent 블록 추출
                set_fact_indent = len(line) - len(line.lstrip())
                for offset in range(1, 30):  # 최대 30 라인 lookahead
                    nxt_idx = lineno - 1 + offset
                    if nxt_idx >= len(lines):
                        break
                    nxt = lines[nxt_idx]
                    if not nxt.strip():
                        continue
                    nxt_indent = len(nxt) - len(nxt.lstrip())
                    if nxt_indent <= set_fact_indent:
                        break  # 같은 또는 더 적은 indent → 블록 끝
                    # 누적 변수 키 매치 검사
                    for ex in pattern["set_fact_check_keys"]:
                        if ex.search(nxt):
                            findings.append((pattern["id"], rel, nxt_idx + 1, nxt.strip()[:80]))
            continue

        for lineno, line in enumerate(lines, start=1):
            if not pattern["regex"].search(line):
                continue
            # exclude_lines
            if "exclude_lines" in pattern:
                if any(ex.search(line) for ex in pattern["exclude_lines"]):
                    continue
            findings.append((pattern["id"], rel, lineno, line.strip()[:80]))
            # aggregate 패턴은 1회만 (priority 같은 카운팅 별도)
            if pattern.get("aggregate"):
                break

    return findings


_SPECIFICITY_KEYS = (
    "distribution_patterns",
    "version_patterns",
    "firmware_patterns",
    "model_patterns",
    "manufacturer_patterns",
)


def _adapter_has_specificity(rel: str, repo_root: Path) -> bool:
    """adapter YAML의 match 블록이 distribution/version/firmware/model_patterns 중 하나라도
    포함하면 specificity 확보 (priority 동률이라도 정렬 결과 결정 가능)."""
    try:
        text = (repo_root / rel).read_text(encoding="utf-8")
    except Exception:
        return False
    # match: 블록 안에 specificity 키가 있는지 (얕은 검사)
    in_match = False
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)
        if indent == 0 and stripped.startswith("match:"):
            in_match = True
            continue
        if in_match:
            if indent == 0:
                # 다른 top-level key 진입 → match 블록 끝
                in_match = False
                continue
            for key in _SPECIFICITY_KEYS:
                if stripped.startswith(f"{key}:"):
                    return True
    return False


def _filter_priority_dupes_by_vendor(
    findings: List[Tuple[int, str, int, str]],
    repo_root: Path,
) -> List[Tuple[int, str, int, str]]:
    """Pattern #4 후처리: 같은 (channel, vendor) 그룹 안에서 priority 값이 2번 이상이고
    해당 adapter들이 specificity 분리 키를 안 갖는 경우만 진짜 의심."""
    pid4 = [f for f in findings if f[0] == 4]
    others = [f for f in findings if f[0] != 4]

    groups: dict[Tuple[str, str], List[Tuple[int, str, int, str, int]]] = {}
    for pid, rel, lineno, snippet in pid4:
        m = re.match(r"^priority:\s*(\d+)", snippet)
        if not m:
            continue
        prio = int(m.group(1))
        key = _adapter_vendor_key(rel)
        groups.setdefault(key, []).append((pid, rel, lineno, snippet, prio))

    kept: List[Tuple[int, str, int, str]] = []
    for key, items in groups.items():
        prio_counts: dict[int, int] = {}
        for it in items:
            prio_counts[it[4]] = prio_counts.get(it[4], 0) + 1
        for pid, rel, lineno, snippet, prio in items:
            if prio_counts[prio] < 2:
                continue
            # specificity 분리 키 보유하면 silence (의도된 동률)
            if _adapter_has_specificity(rel, repo_root):
                continue
            kept.append((pid, rel, lineno, f"{snippet}  [vendor={key[1]} 동률, specificity 키 부재]"))

    return others + kept


def main() -> int:
    parser = argparse.ArgumentParser(description="rule 95 R1 의심 패턴 자동 검출")
    parser.add_argument("--target", default=None, help="검사 디렉터리 (기본: 전체)")
    parser.add_argument("--strict", action="store_true", help="의심 발견 시 exit 2")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()

    targets = [args.target] if args.target else SCAN_DIRS
    all_findings: List[Tuple[int, str, int, str]] = []

    for d in targets:
        path = repo_root / d
        if not path.is_dir():
            continue
        for f in path.rglob("*"):
            if f.is_file() and f.suffix in (".py", ".yml", ".yaml"):
                all_findings.extend(scan_file(f, repo_root))

    # Pattern #4 후처리: 같은 vendor 내 동률 + specificity 분리 키 부재만 남김
    all_findings = _filter_priority_dupes_by_vendor(all_findings, repo_root)

    if not all_findings:
        print("=== 의심 패턴 스캔 결과 ===")
        print("clean (rule 95 R1 12 패턴 — 검출 0건)")
        return 0

    # 패턴별 그룹
    print("=== 의심 패턴 스캔 결과 (advisory) ===")
    by_id: dict[int, list] = {}
    for pid, rel, lineno, snippet in all_findings:
        by_id.setdefault(pid, []).append((rel, lineno, snippet))

    for pid in sorted(by_id.keys()):
        pattern_meta = next(p for p in PATTERNS if p["id"] == pid)
        print(f"\n[#{pid}] {pattern_meta['name']} — {len(by_id[pid])}건")
        print(f"      → {pattern_meta['advisory']}")
        for rel, lineno, snippet in by_id[pid][:5]:
            print(f"      • {rel}:{lineno}  {snippet}")
        if len(by_id[pid]) > 5:
            print(f"      ... ({len(by_id[pid]) - 5}건 추가)")

    print(f"\n총 {len(all_findings)}건 (advisory). 의심 발견 시:")
    print("  - rule 95 R3 — @pytest.mark.xfail 추가 + FAILURE_PATTERNS.md entry")
    print("  - 또는 의도된 패턴이면 코드 주석으로 근거 명시")

    return 2 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
