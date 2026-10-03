#!/usr/bin/env bash
# scripts/ai/prodgen/preflight.sh — build the production tree from a fixed SHA and run the
# offline gates from inside WSL / Linux.
#
#   bash scripts/ai/prodgen/preflight.sh [<sha>] [<out-dir>]
#
# Defaults: sha = HEAD of this checkout's repository, out-dir = /tmp/prodgen-preflight.
# The default out-dir is recreated on every run; a custom out-dir is only replaced when it
# was produced by prodgen (fail-closed in build).
# PowerShell comments need a PowerShell parser (pwsh, or pwsh.exe / powershell.exe via WSL
# interop); without one the build reports them as class B and exits 1 — by design.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SHA="${1:-$(git -C "$REPO_ROOT" rev-parse HEAD)}"
OUT="${2:-/tmp/prodgen-preflight}"

if [ "$OUT" = "/tmp/prodgen-preflight" ] && [ -d "$OUT" ]; then
    rm -rf "$OUT"
fi

cd "$REPO_ROOT"
echo "[preflight] repo=$REPO_ROOT sha=$SHA out=$OUT"
if ! python3 -m scripts.ai.prodgen --json build --sha "$SHA" --out "$OUT" > "${OUT}.build.json"; then
    echo "[preflight] build FAILED — see ${OUT}.build.json (class B list) and the messages above"
    exit 1
fi
# verify 종료 코드(2026-10-04): 0 COMPLETE_PASS · 2 PARTIAL(--skip-live 는 언제나 PARTIAL — 통과가 아니다) · 1 FAIL
python3 -m scripts.ai.prodgen --json verify --tree "$OUT" --skip-live > "${OUT}.verify.json"
rc=$?
case "$rc" in
    0) echo "[preflight] OK — COMPLETE_PASS, tree at $OUT (reports: ${OUT}.build.json, ${OUT}.verify.json)" ;;
    2) echo "[preflight] PARTIAL — offline gates passed, live gates skipped (not a pass; run verify with --netrc/--vault-password-file on a Linux host or CI). tree at $OUT" ;;
    *) echo "[preflight] verify FAILED — see ${OUT}.verify.json"; exit 1 ;;
esac
exit 0
