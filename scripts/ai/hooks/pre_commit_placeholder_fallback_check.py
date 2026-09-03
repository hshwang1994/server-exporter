#!/usr/bin/env python3
"""pre-commit hook — gather 데이터 필드의 placeholder / IP 대체 fallback 차단 (advisory).

2026-09-03 OS/ESXi 전수 검수에서 같은 종류의 버그가 37건 나왔다. 뿌리는 세 가지다:

1. **모르는 값을 다른 값으로 대체** — `hostname: ... | default(inventory_hostname)` (IP 로 대체, B-01),
   `'hostname': _ip` (always fallback, B-04).
2. **모르는 값을 placeholder 로** — `total_mb: ... | default(0)`, `uptime_seconds: ... | default(0)`,
   `sockets: ... else 1`, `hosting_type ... 'unknown'` 리터럴이 아니라 `| default('unknown')` 로 판정을 건너뜀 (B-11/B-14/B-32).
3. **None 을 문자열로** — `kernel: ... | default(none) | string` → "None" (B-34).

이 훅은 staged 된 gather / normalize YAML 만 라인 단위로 훑어 위 패턴을 경고한다.
값 계약 자체는 `tests/unit/test_field_dictionary_channel_emit.py` 가 고정하고, 이 훅은 커밋 직전에
같은 실수를 한 번 더 막는 안전망이다. 판정 근거가 있는 fallback(예: `default(none, true)`) 은 잡지 않는다.

검사 알고리즘 (line-based heuristic):
1. git diff --cached --name-only 로 staged YAML 파일 중 `os-gather/`, `esxi-gather/`, `redfish-gather/tasks/`,
   `common/tasks/normalize/` 아래 파일 선별
2. 주석 라인 제외, `esxi_hostname:` (community.vmware 모듈 인자) 라인 제외
3. 패턴 매치 시 경고 (파일:라인 + 어떤 규칙인지)

Exit codes:
    0 — 통과 또는 advisory 경고 (commit 허용)
    1 — PLACEHOLDER_FALLBACK_BLOCKING=1 명시 시만 차단

비활성화 환경변수:
    PLACEHOLDER_FALLBACK_SKIP=1     — 본 hook skip
    PLACEHOLDER_FALLBACK_BLOCKING=1 — advisory → blocking 격상

Usage:
    python scripts/ai/hooks/pre_commit_placeholder_fallback_check.py            # staged 파일
    python scripts/ai/hooks/pre_commit_placeholder_fallback_check.py --all      # 저장소 전수
    python scripts/ai/hooks/pre_commit_placeholder_fallback_check.py --self-test
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

REPO = Path(__file__).resolve().parents[3]

SCOPES = ("os-gather/", "esxi-gather/", "redfish-gather/tasks/", "common/tasks/normalize/")

# (규칙 id, 정규식, 설명)
RULES = [
    ("ip-fallback",
     re.compile(r"\b(hostname|fqdn):.*default\((_ip|_e_ip|inventory_hostname)\b"),
     "hostname/fqdn 을 IP(inventory_hostname/_ip/_e_ip) 로 대체 — 없으면 null (B-01)"),
    ("ip-literal",
     re.compile(r"'hostname':\s*(_ip|_e_ip|inventory_hostname)\b"),
     "envelope hostname 에 IP 변수 직접 대입 (B-04)"),
    ("zero-placeholder",
     re.compile(r"\b(uptime_seconds|total_mb|installed_mb|visible_mb|free_mb|capacity_mb|sockets|cores_physical|logical_threads|max_speed_mhz|l2_cache_kb|l3_cache_kb|swap_total_mb|swap_used_mb|swap_free_mb):.*\|\s*default\((0|'0'|1)\)"),
     "수량 필드에 0/1 placeholder — 모르면 null (B-11/B-14/B-32)"),
    ("unknown-placeholder",
     re.compile(r"\b(architecture|hosting_type|distribution|os_family|model|manufacturer|vendor|name):.*\|\s*default\('unknown'\)"),
     "판정 없이 'unknown' 리터럴 대체 — 판정식 또는 null (B-08/B-30/B-35)"),
    ("none-string",
     re.compile(r"\|\s*default\(none\)\s*\|\s*string\s*(\}\}|\"|$)"),
     "None 을 | string 으로 넘겨 \"None\" 문자열 생성 (B-34)"),
    ("false-placeholder",
     re.compile(r"\b(ntp_active|ntp_synchronized|is_primary):.*\|\s*default\(false\)\s*\|\s*bool"),
     "조회 실패를 false 로 단정 — tri-state(null) 유지 (B-31/B-32)"),
]


def _staged_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
                             capture_output=True, text=True, cwd=REPO, check=True).stdout
    except Exception:
        return []
    return [REPO / p.strip() for p in out.splitlines() if p.strip()]


def _in_scope(path: Path) -> bool:
    try:
        rel = path.relative_to(REPO).as_posix()
    except ValueError:
        return False
    return rel.endswith((".yml", ".yaml")) and rel.startswith(SCOPES)


def scan_text(text: str, label: str) -> list[str]:
    findings = []
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#") or "esxi_hostname:" in line:
            continue
        for rule_id, pat, why in RULES:
            if pat.search(line):
                findings.append(f"{label}:{i} [{rule_id}] {why}\n    {stripped[:140]}")
    return findings


def scan_files(paths: list[Path]) -> list[str]:
    findings = []
    for p in paths:
        if not p.exists() or not _in_scope(p):
            continue
        findings.extend(scan_text(p.read_text(encoding="utf-8", errors="replace"), p.relative_to(REPO).as_posix()))
    return findings


def _self_test() -> int:
    bad = "\n".join([
        "        fqdn:           \"{{ ansible_fqdn | default(inventory_hostname) }}\"",
        "                       'hostname': _ip | default(none),",
        "        uptime_seconds: \"{{ (ansible_uptime_seconds | default(0)) | int }}\"",
        "        hosting_type:   \"{{ _w_hosting_type | default('unknown') | trim }}\"",
        "        kernel:         \"{{ _w_os_data.build     | default(none) | string }}\"",
        "              ntp_synchronized: \"{{ _w_rt_ntp_obj.synced | default(false) | bool }}\"",
    ])
    good = "\n".join([
        "        hostname:       \"{{ _l_hostname_short | default(none) }}\"",
        "    esxi_hostname:  \"{{ _e_hostname | default(_e_ip, true) }}\"",
        "        uptime_seconds: \"{{ _e_uptime | default(none) }}\"",
        "        # kernel: \"{{ x | default(none) | string }}\"  (주석은 무시)",
    ])
    bad_hits = scan_text(bad, "bad.yml")
    good_hits = scan_text(good, "good.yml")
    ids = sorted({h.split("[")[1].split("]")[0] for h in bad_hits})
    ok = ids == sorted(r[0] for r in RULES) and not good_hits
    print(f"self-test: bad={len(bad_hits)} rules={ids} good={len(good_hits)} → {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="placeholder / IP-fallback 회귀 가드 (advisory)")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--all", action="store_true", help="staged 대신 저장소 전수")
    ap.add_argument("--blocking", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return _self_test()
    if os.environ.get("PLACEHOLDER_FALLBACK_SKIP") == "1":
        return 0

    if args.all:
        paths = [p for scope in SCOPES for p in (REPO / scope).rglob("*.yml")]
    else:
        paths = _staged_files()
    findings = scan_files(paths)
    if not findings:
        return 0
    blocking = args.blocking or os.environ.get("PLACEHOLDER_FALLBACK_BLOCKING") == "1"
    tag = "BLOCK" if blocking else "WARN"
    print(f"[{tag}] placeholder / IP-fallback 의심 {len(findings)}건 (pre_commit_placeholder_fallback_check)")
    for f in findings:
        print("  - " + f)
    print("  판정 근거가 있으면 null 을 쓰거나 판정식을 두세요. skip: PLACEHOLDER_FALLBACK_SKIP=1")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
