#!/usr/bin/env python3
"""문서가 언급한 저장소 경로가 실제로 있는지 검사한다.

왜 필요한가
-----------
`verify_harness_consistency.py` 는 `.claude/**` 안의 링크만 본다. 그래서 문서가
저장소의 **다른** 경로를 잘못 가리켜도 게이트를 통과한다. 실제로 그 사각지대에서
아래가 통과된 상태로 살아 있었다.

- skill 5개가 없는 `tests/redfish-probe/test_baseline.py` 실행을 지시
- `rules/13 R1` 이 없는 디렉터리 `tests/baseline_v1/` 갱신을 의무로 규정
  (실제 경로는 `schema/baseline_v1/`)
- `measurement-targets.yaml` 이 없는 `FRAGMENT_TOPOLOGY.md` 를 측정 대상으로 등록
- 삭제된 `Jenkinsfile_grafana` 를 3곳이 참조

문서를 옮기거나 지울 때 참조가 깨지는 것도 같은 검사로 막는다.

오탐을 어떻게 줄였나
--------------------
저장소의 **실제 최상위 디렉터리 또는 루트 파일로 시작하는** 문자열만 경로로 본다.
그래서 평범한 산문이나 외부 URL 은 애초에 후보에 들어오지 않는다. 자리표시자가
들어간 표기(`vault/<loc>/redfish/<vendor>.yml`, `cycle-NNN.md` 등)는 템플릿이므로
건너뛴다.

Usage:
    python scripts/ai/verify_docs_references.py            # tracked .md 검사
    python scripts/ai/verify_docs_references.py --all-files # 코드/설정까지 포함
    python scripts/ai/verify_docs_references.py --full      # 전체 목록 출력
    python scripts/ai/verify_docs_references.py --baseline out.txt  # 현재 상태 기록

Exit codes:
    0 = 통과 (죽은 참조 없음)
    2 = 죽은 참조 발견
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# 이 목록으로 "경로처럼 생긴 문자열"과 "진짜 저장소 경로"를 가른다.
# 최상위 디렉터리는 실행 시점에 실측하고, 루트 파일만 명시한다.
ROOT_FILES = {
    "CLAUDE.md",
    "README.md",
    "REQUIREMENTS.md",
    "ansible.cfg",
    "requirements-test.txt",
}
ROOT_FILE_PREFIXES = ("Jenkinsfile",)

# 자리표시자가 들어간 표기는 템플릿이라 실존 검사 대상이 아니다.
PLACEHOLDER_TOKENS = ("{", "}", "<", ">", "*", "?", "…", "...", "$")
PLACEHOLDER_RE = re.compile(
    # 경로 한가운데 끼어 있어도 자리표시자다: `cycle-NNN.md`, `full-sweep-YYYY-MM-DD.md`
    r"(?:^|[/_-])(?:NNN|XXX|YYYY-MM-DD|YYYYMMDD|date|vendor|loc|channel|section)(?:[/._-]|$)",
    re.IGNORECASE,
)

# `docs/contract/03-fields.md` 처럼 번호만 적은 산문 약칭은 파일 경로 주장이 아니다.
# (재편 시 같이 고쳐야 하지만, 실존 게이트의 대상은 아니다 — `--shorthand` 로 따로 본다.)
DOCS_SHORTHAND_RE = re.compile(r"^docs/\d+$")

# 경로처럼 생겼지만 파일이 아닌 식별자. 근거를 함께 적는다.
NOT_A_PATH = {
    # credential_common.py:54 REDFISH_STANDARD_SCOPE — vault 경로가 아니라 scope 문자열
    "common/redfish/standard",
    # 2026-09-28 비운영 `Jenkinsfile` 삭제 뒤 남은 파이프라인은 `Jenkinsfile_portal` 하나다. 산문의 `Jenkinsfile` 은
    # "파이프라인 정의 파일" 을 뜻하는 일반 어휘라 실존 검사 대상이 아니다 (`Jenkinsfile_portal` 은 계속 검사한다).
    "Jenkinsfile",
}

# 경로 후보 추출: 공백/따옴표/괄호/백틱 으로 끊기는 경로 모양 토큰
PATH_TOKEN_RE = re.compile(r"[A-Za-z0-9_.\-/]+(?:\.[A-Za-z0-9_]+)?")

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".pytest_cache"}

# 역사를 기록하는 문서. 지금 없는 경로를 적는 게 이 문서들의 일이라 위반이 아니다.
HISTORY_DOC_RE = re.compile(
    r"(^docs/ai/decisions/|^docs/ai/archive/|^tests/evidence/"
    r"|CONVENTION_DRIFT\.md$|FAILURE_PATTERNS\.md$|TEST_HISTORY\.md$|CURRENT_STATE\.md$"
    # 아래 셋도 성격이 같다 — 그때 무엇이 있었는지를 적는 게 이 문서들의 일이다.
    r"|^docs/reference/decision-log\.md$|EXTERNAL_CONTRACTS\.md$|^docs/ai/NEXT_ACTIONS\.md$)"
)

# 그 줄이 "만들 예정"이거나 "예시"라고 말하면 실존 주장이 아니다.
#   `| 새 Linux 배포판 (예: Rocky) | adapters/os/linux_rocky.yml |` 처럼
#   무엇을 만들지 보여주는 표가 실제로 그 파일을 주장하는 건 아니다.
EXAMPLE_RE = re.compile(r"(예\s*:|예시|만들 |만든다|생성한다|작성한다|샘플|template|placeholder|권장|가정)")

# 그 줄 자체가 "이건 없다"를 말하고 있으면 위반이 아니다.
TOMBSTONE_RE = re.compile(
    r"(부재|없음|없다|가 아니라|이 아니라|삭제됨|삭제됐|제거됨|제거됐|해제됨|해제됐"
    r"|폐지|종전|옛 |더 이상|존재하지 않|DEPRECATED|아직 없으면)"
)


def git_tracked(patterns: list[str]) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", *patterns], cwd=REPO, capture_output=True, text=True
    )
    if out.returncode != 0:
        print(f"[FAIL] git ls-files 실패: {out.stderr.strip()}")
        raise SystemExit(2)
    return [p for p in out.stdout.splitlines() if p]


def top_level_dirs() -> set[str]:
    return {
        p.name
        for p in REPO.iterdir()
        if p.is_dir() and p.name not in SKIP_DIRS and not p.name.startswith(".git")
    } | {".claude"}


# 확장자 없이 슬래시로도 안 끝나는 토큰은 경로 주장이 아니라 산문으로 본다.
#   예: `os-gather/esxi-gather/redfish-gather` (채널 나열), `schema/JSON`, `docs/test`
# 이 규칙이 없으면 게이트가 오탐으로 가득 차 아무도 안 쓰게 된다.
EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,6}$")


def looks_like_repo_path(token: str, tops: set[str]) -> bool:
    if token in ROOT_FILES:
        return True
    if any(token.startswith(p) for p in ROOT_FILE_PREFIXES):
        return True
    head = token.split("/", 1)[0]
    if head not in tops or "/" not in token:
        return False
    # 잘린 토큰(`adapters/redfish/dell_`)은 원문이 와일드카드거나 줄바꿈된 것이다.
    if token.endswith(("_", "-")):
        return False
    return token.endswith("/") or bool(EXT_RE.search(token))


def is_placeholder(token: str) -> bool:
    if any(t in token for t in PLACEHOLDER_TOKENS):
        return True
    return bool(PLACEHOLDER_RE.search(token))


def normalize(token: str) -> str:
    """`file.py:123`, 후행 문장부호, `./` 를 정리한다."""
    token = token.strip().strip("`'\"")
    token = re.sub(r":[0-9]+(?:-[0-9]+)?$", "", token)      # file.py:12 / :12-34
    token = token.rstrip(".,;)]}")
    if token.startswith("./"):
        token = token[2:]
    return token


def extract_candidates(text: str, tops: set[str], shorthand: bool = False) -> set[str]:
    found: set[str] = set()
    for raw in PATH_TOKEN_RE.findall(text):
        tok = normalize(raw)
        if not tok or tok.startswith(("http://", "https://", "mailto:")):
            continue
        if not looks_like_repo_path(tok, tops):
            continue
        if is_placeholder(tok) or tok in NOT_A_PATH:
            continue
        if DOCS_SHORTHAND_RE.match(tok):
            if shorthand:
                found.add(tok)
            continue
        found.add(tok)
    return found


def exists(rel: str) -> bool:
    p = REPO / rel
    if p.exists():
        return True
    # 디렉터리를 파일처럼 적은 경우도 통과로 본다
    return (REPO / rel.rstrip("/")).exists()


def main() -> int:
    ap = argparse.ArgumentParser(description="문서 내 저장소 경로 참조 실존 검사")
    ap.add_argument("--all-files", action="store_true",
                    help="코드/설정 파일(.py/.yml/.yaml/.sh/Jenkinsfile*)까지 검사")
    ap.add_argument("--full", action="store_true", help="위반 전체 출력")
    ap.add_argument("--baseline", metavar="PATH",
                    help="현재 위반 목록을 파일로 기록하고 종료 0")
    ap.add_argument("--shorthand", action="store_true",
                    help="`docs/contract/03-fields.md` 같은 번호 약칭도 함께 보고 (문서 재편 시 치환 대상 파악용)")
    args = ap.parse_args()

    tops = top_level_dirs()

    patterns = ["*.md"]
    if args.all_files:
        patterns += ["*.py", "*.yml", "*.yaml", "*.sh", "Jenkinsfile*"]
    files = git_tracked(patterns)

    violations: list[tuple[str, int, str]] = []
    historical = 0
    scanned = 0
    for rel in files:
        fp = REPO / rel
        try:
            lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        scanned += 1
        hist_file = bool(HISTORY_DOC_RE.search(rel))
        for lineno, line in enumerate(lines, 1):
            for tok in extract_candidates(line, tops, shorthand=args.shorthand):
                # 저장소 루트 기준, 또는 그 문서가 있는 디렉터리 기준 (README 가 옆 파일을 이름만으로 가리키는 경우 —
                #   tests/jenkins/harness/README.md 의 `Jenkinsfile_harness`). 2026-10-10.
                if exists(tok) or (fp.parent / tok).exists():
                    continue
                # 역사 기록과 "없음을 주장하는 문장"은 위반이 아니다.
                #   ADR·evidence·drift 카탈로그는 그 시점에 존재하던 경로를 적는 게 일이고,
                #   "`tests/baseline_v1/` 가 아니라 …" 같은 문장은 부재가 곧 요지다.
                #   이걸 구분하지 않으면 검증기가 정확할수록 위반 수가 늘어난다.
                if hist_file or TOMBSTONE_RE.search(line) or EXAMPLE_RE.search(line):
                    historical += 1
                    continue
                violations.append((rel, lineno, tok))

    if args.baseline:
        Path(args.baseline).write_text(
            "\n".join(f"{f}:{n}\t{t}" for f, n, t in sorted(violations)) + "\n",
            encoding="utf-8",
        )
        print(f"baseline 기록: {args.baseline} ({len(violations)}건, {scanned}개 파일 검사)")
        return 0

    if violations:
        by_target: dict[str, list[str]] = {}
        for f, n, t in violations:
            by_target.setdefault(t, []).append(f"{f}:{n}")
        print(f"죽은 문서 참조: {len(violations)}건 / 대상 {len(by_target)}종 ({scanned}개 파일 검사)")
        if historical:
            print(f"  (역사 기록·부재 진술 {historical}건은 제외했다)")
        print()
        items = sorted(by_target.items(), key=lambda kv: -len(kv[1]))
        head = len(items) if args.full else 25
        for target, refs in items[:head]:
            print(f"  {target}  ({len(refs)}곳)")
            show = refs if args.full else refs[:3]
            for r in show:
                print(f"      {r}")
            if not args.full and len(refs) > 3:
                print(f"      ... 외 {len(refs) - 3}곳")
        if not args.full and len(items) > head:
            print(f"\n  ... 대상 {len(items) - head}종 추가 (--full 로 전체 출력)")
        return 2

    tail = f" / 역사 기록·부재 진술 {historical}건 제외" if historical else ""
    print(f"문서 참조 통과: 죽은 경로 없음 ({scanned}개 파일 검사{tail})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
