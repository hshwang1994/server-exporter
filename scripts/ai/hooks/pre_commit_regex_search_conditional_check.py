#!/usr/bin/env python3
r"""pre-commit hook — rule 95 R1 #12: `regex_search` + `when` 절 None 가드 차단.

Ansible Jinja2 `regex_search` / `regex_findall` / `regex_replace` 가 미매치 시
**None** 반환 → Ansible strict mode 의 conditional 평가 fail
(`Conditional result (False) was derived from value of type 'NoneType'`).

직전 사고 (cycle 2026-05-11, build #133~#137 4건 fail):
- redfish-gather/tasks/vendors/hpe/collect_oem.yml L82
- redfish-gather/tasks/vendors/hpe/normalize_oem.yml L39, L45
- regex_search Superdome/Flex/CSUS 패턴 미매치 → None → block fail → status=failed

위험 패턴:
    when:
      - "var | regex_search('pattern')"               # NG — None 가드 없음

안전 패턴:
    when:
      - "(var | regex_search('pattern')) is not none" # OK
      - "(var | regex_findall('pattern')) | length > 0"  # OK
      - "(var | regex_search('pattern')) | default(false) | bool"  # OK
      - "var is regex('pattern')"                     # OK (regex_search 아님)

검사 알고리즘 (line-based heuristic):
1. git diff --cached --name-only 로 staged YAML 파일 list
2. 각 YAML 라인 단위 스캔
3. `when:` 블록 진입 감지 (`\s*when:\s*$` 또는 `\s*when:\s*-` 또는 inline `when: "..."`)
4. when 블록 내 regex_search/regex_findall/regex_replace 사용 라인 식별
5. 같은 라인에 가드 토큰 (`is not none` / `is none` / `is sameas` / `| length` / `| bool` /
   `| default(`) 없을 시 경고
6. 본 hook 은 **advisory** — 초기 도입 단계 (1주 안정 후 BLOCKING 격상 검토)

Exit codes:
    0 — 검사 통과 또는 advisory 경고 (commit 허용)
    1 — 환경변수 REGEX_WHEN_BLOCKING=1 명시 시만 차단

비활성화 환경변수:
    REGEX_WHEN_SKIP=1     — 본 hook skip
    REGEX_WHEN_BLOCKING=1 — advisory → blocking 격상 (1주 안정 후 사용)

Usage:
    pre-commit hook 자동 호출. 수동:
        python scripts/ai/hooks/pre_commit_regex_search_conditional_check.py
        python scripts/ai/hooks/pre_commit_regex_search_conditional_check.py --self-test
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


REGEX_FN_PATTERN = re.compile(r"\bregex_(?:search|findall|replace)\b")

# POST-regex_search 가드 토큰 — regex_search/findall/replace 호출 **뒤** 에 있어야
# None 출력을 차단. `| default('')` 가 regex_search 호출 **앞** 에 있으면 INPUT 만
# 가드 (regex_search 출력은 여전히 None). 5d6cf72c 사고 패턴이 그 사례.
POST_GUARD_TOKENS: tuple[str, ...] = (
    "is not none",
    "is none",
    "is sameas none",
    "is sameas(none)",
    "| length",
    "|length",
    "| bool",
    "|bool",
    "| default(",
    "|default(",
    # Round 15: ' in ' 토큰 제거 — regex_search 뒤 무관한 ' in ' (예: 'status in critical_list')
    # 에 substring 매칭되어 실제 미가드 violation 을 놓치는 false-negative 발생. 또한 Ansible
    # strict mode 에서 'in' 연산자는 None 을 가드하지 못함. 현 코드 중 이 토큰 의존 0건 (grep 확인).
)

# YAML 스캔 대상 디렉터리 (다른 영역 false positive 차단)
TARGET_DIRS: tuple[str, ...] = (
    "os-gather/",
    "esxi-gather/",
    "redfish-gather/",
    "common/",
    "adapters/",
)


def _normalize(p: str) -> str:
    return p.replace("\\", "/").strip()


def _staged_yaml_files(repo_root: Path) -> list[str]:
    """git staged YAML 파일 list (server-exporter 영역만)."""
    try:
        r = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, cwd=str(repo_root), timeout=5,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return []
    files: list[str] = []
    for ln in (r.stdout or "").splitlines():
        path = _normalize(ln)
        if not path:
            continue
        if not (path.endswith(".yml") or path.endswith(".yaml")):
            continue
        if not any(path.startswith(d) for d in TARGET_DIRS):
            continue
        files.append(path)
    return files


def _line_has_guard(line: str) -> bool:
    """regex_search/findall/replace **이후** 위치에 가드 토큰이 있는지 검사.

    `| default('')` 가 regex_search 앞에 있으면 INPUT 만 가드 (출력은 여전히 None).
    가드는 regex_search 호출 뒤 / 같은 식의 닫는 괄호 뒤에 와야 함.

    Algorithm:
    - regex_search/findall/replace 의 모든 occurrence 위치 식별
    - 마지막 occurrence 의 끝 위치 (matched_end) 이후 substring 검사
    - matched_end 이후 가드 토큰 존재 → safe
    """
    # 마지막 regex_* 호출 위치 식별
    last_end = -1
    for m in REGEX_FN_PATTERN.finditer(line):
        last_end = m.end()
    if last_end < 0:
        return True  # regex_* 호출 없음 — 본 검사 대상 아님
    after = line[last_end:].lower()
    return any(tok in after for tok in POST_GUARD_TOKENS)


def scan_file_lines(lines: list[str]) -> list[tuple[int, str, str]]:
    """파일 라인 list → 위험 라인 [(lineno, kind, text)] 반환.

    line-based heuristic:
    - `when:` 라인 발견 시 in_when=True. 같은 indent 또는 더 깊은 indent 의 다음 라인들이 when block.
    - inline form (`when: "..."`) 도 같은 라인 검사.
    - regex_search/findall/replace 발견 + 가드 토큰 없음 → flag.
    """
    findings: list[tuple[int, str, str]] = []
    in_when = False
    when_indent = -1

    for idx, raw_line in enumerate(lines, start=1):
        stripped = raw_line.rstrip("\n")
        if not stripped.strip():
            # 빈 라인은 YAML indent 블록 종료 신호 아님
            continue
        indent = len(stripped) - len(stripped.lstrip(" \t"))

        # `when:` 라인 감지 (block 형식 / inline 형식 둘 다 — 값이 비어도 매치)
        m_when = re.match(r"^(\s*)when:(?:\s*(.*))?$", stripped)
        if m_when:
            cond = (m_when.group(2) or "").strip()
            # block 형식: `when:` (값 없음) / `when: |` / `when: >`
            if cond in ("", "|", ">", "|-", ">-", "|+", ">+"):
                in_when = True
                when_indent = indent
                continue
            # inline 형식: `when: condition`
            if REGEX_FN_PATTERN.search(cond) and not _line_has_guard(cond):
                findings.append((idx, "inline-when", stripped))
            # inline 후 추가 conditional list 가능성 — block 활성화 유지
            in_when = True
            when_indent = indent
            continue

        # block 형식 — when 블록 안쪽 conditional 라인
        if in_when:
            # 같은 indent (혹은 더 깊은) 의 `- "..."` 또는 `- expr` 만 conditional
            if indent > when_indent:
                m_item = re.match(r"^\s*-\s*(.+)$", stripped)
                if m_item:
                    content = m_item.group(1).strip()
                    if (content.startswith('"') and content.endswith('"')) or \
                       (content.startswith("'") and content.endswith("'")):
                        content = content[1:-1]
                    if REGEX_FN_PATTERN.search(content) and not _line_has_guard(content):
                        findings.append((idx, "block-when", stripped))
                    continue
            # 같거나 얕은 indent — 다른 key 시작 → when 블록 종료
            in_when = False
            when_indent = -1

    return findings


def check_repo(repo_root: Path, blocking: bool = False) -> int:
    """staged YAML 파일 전수 검사. blocking=True 면 violations > 0 시 exit 1."""
    files = _staged_yaml_files(repo_root)
    if not files:
        return 0

    total_violations = 0
    for rel_path in files:
        abs_path = repo_root / rel_path
        if not abs_path.is_file():
            continue
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue
        findings = scan_file_lines(content.splitlines())
        if not findings:
            continue
        total_violations += len(findings)
        sev = "BLOCK" if blocking else "WARN"
        print(f"[{sev}] {rel_path} — regex_search/findall/replace + when 가드 누락 {len(findings)} 건:",
              file=sys.stderr)
        for lineno, kind, line in findings:
            preview = line.strip()
            if len(preview) > 120:
                preview = preview[:117] + "..."
            print(f"  L{lineno} [{kind}] {preview}", file=sys.stderr)

    if total_violations == 0:
        return 0

    print("", file=sys.stderr)
    print(f"[rule 95 R1 #12] regex_search/findall/replace + when 절 단독 사용 = NoneType conditional fail 위험.",
          file=sys.stderr)
    print("  안전 패턴: (var | regex_search('p')) is not none / | length > 0 / | default(false) | bool",
          file=sys.stderr)
    print("  skip: REGEX_WHEN_SKIP=1 (commit 단발성)", file=sys.stderr)

    return 1 if blocking else 0


def _self_test() -> int:
    """unit test — pre_commit_regex_search_conditional_check.py 자체 검증."""
    cases = [
        # (description, yaml_lines, expected_finding_count)
        (
            "bad: when block + regex_search no guard",
            [
                "- name: 'bad task'",
                "  set_fact:",
                "    x: true",
                "  when:",
                "    - \"_var | regex_search('pattern')\"",
            ],
            1,
        ),
        (
            "good: when block + regex_search is not none",
            [
                "  when:",
                "    - \"(_var | regex_search('pattern')) is not none\"",
            ],
            0,
        ),
        (
            "good: when block + regex_findall | length",
            [
                "  when:",
                "    - \"(_var | regex_findall('pattern')) | length > 0\"",
            ],
            0,
        ),
        (
            "good: inline when + default | bool",
            [
                "  when: \"(x | regex_search('p')) | default(false) | bool\"",
            ],
            0,
        ),
        (
            "bad: inline when + regex_search no guard",
            [
                "  when: \"x | regex_search('p')\"",
            ],
            1,
        ),
        (
            "good: regex_search outside when (set_fact value)",
            [
                "- set_fact:",
                "    foo: \"{{ x | regex_search('p') }}\"",
                "- debug:",
                "    msg: 'ok'",
            ],
            0,
        ),
        (
            "bad: multi-conditional with bad line",
            [
                "  when:",
                "    - _other_var | bool",
                "    - \"_x | regex_search('p')\"",
                "    - _another | length > 0",
            ],
            1,
        ),
        (
            "edge: `is regex` (Ansible test) — not regex_search",
            [
                "  when:",
                "    - \"_x is regex('p')\"",
            ],
            0,
        ),
        (
            "bad: 5d6cf72c pre-fix pattern (default before regex_search — INPUT 가드만)",
            [
                "  when:",
                "    - \"(_rf_detected_model | default('')) | regex_search('(?i)Superdome|Flex')\"",
            ],
            1,
        ),
        (
            "good: default AFTER regex_search (출력 가드)",
            [
                "  when:",
                "    - \"(_rf_detected_model | regex_search('(?i)Superdome|Flex')) | default(false) | bool\"",
            ],
            0,
        ),
    ]
    failures = 0
    for desc, lines, expected in cases:
        got = len(scan_file_lines(lines))
        status = "OK " if got == expected else "FAIL"
        print(f"[{status}] {desc}: expected={expected} got={got}")
        if got != expected:
            failures += 1
    if failures:
        print(f"\n{failures} self-test case FAILED", file=sys.stderr)
        return 1
    print(f"\nself-test OK ({len(cases)}/{len(cases)})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self-test", action="store_true",
                        help="hook 자체 검증")
    parser.add_argument("--blocking", action="store_true",
                        help="advisory → blocking 격상 (REGEX_WHEN_BLOCKING=1 동등)")
    args, _unknown = parser.parse_known_args()

    if args.self_test:
        return _self_test()

    if os.environ.get("REGEX_WHEN_SKIP", "").strip() == "1":
        return 0

    blocking = args.blocking or os.environ.get("REGEX_WHEN_BLOCKING", "").strip() == "1"

    repo_root = Path(__file__).resolve().parents[3]
    return check_repo(repo_root, blocking=blocking)


if __name__ == "__main__":
    sys.exit(main())
