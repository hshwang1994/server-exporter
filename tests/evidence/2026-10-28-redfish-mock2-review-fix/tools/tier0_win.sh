#!/bin/bash
# Tier 0 — Windows 새 clone(core.autocrlf=true) ci_gate + G4 · G5 FAIL → PASS 재현
# 조건은 독립 검증의 Windows 실행과 같게: 전역 MSYS_NO_PATHCONV=1(구현 핸드오프의 옛 안내) · PYTHONUTF8=1.
# 사용: bash tier0_win.sh <기대 HEAD sha> <phase: gate|repro>
set -u
EXPECT=${1:?expected sha}
PHASE=${2:?phase}
# 경로는 전부 Windows 형식(C:/…): 전역 MSYS_NO_PATHCONV=1 에서는 /c/… 가 git · python 인자로 변환되지 않고 C:\c\… 로 해석된다
S=C:/Users/hshwa/AppData/Local/Temp/claude/C--github-ClovirONE-clovirone-server-gathering/f440d626-b044-479a-b703-5273b7ae8be3/scratchpad
W=C:/github/ClovirONE/clovirone-server-gathering
E=C:/github/ClovirONE/clovirone-server-gathering/tests/evidence/2026-10-28-redfish-mock2-review-fix/tier0
# clone 은 짧은 새 경로에 둔다 — scratchpad 경로는 MAX_PATH 260 을 넘어 checkout 이 실패했다(2026-10-28, 'Filename too long')
NEW=C:/github/ClovirONE/se-fix-20261028-win/new
OLD=C:/github/ClovirONE/se-fix-20261028-win/base
BR=fix/redfish-mock2-review-20261028
BASE=f92ebe6ad338693c7d993434ca7190129a4b7639
export MSYS_NO_PATHCONV=1 PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1

if [ "$PHASE" = gate ]; then
  [ -e "$NEW" ] && { echo "exists: $NEW"; exit 3; }
  mkdir -p "$(dirname "$NEW")" || exit 1
  git clone -q --no-hardlinks "$W" "$NEW" || exit 1
  git -C "$NEW" checkout -q "$BR" || exit 1
  H=$(git -C "$NEW" rev-parse HEAD)
  [ "$H" = "$EXPECT" ] || { echo "HEAD mismatch: $H != $EXPECT"; exit 4; }
  mkdir -p "$E/windows-clone"
  {
    echo "date_utc: $(date -u +%FT%TZ)"
    echo "clone: $NEW head: $H branch: $(git -C "$NEW" branch --show-current)"
    echo "core.autocrlf=$(git -C "$NEW" config --get core.autocrlf || echo unset) ($(git -C "$NEW" config --show-origin --get core.autocrlf | cut -f1))"
    echo "core.fileMode=$(git -C "$NEW" config --get core.fileMode || echo unset)"
    echo "core.quotepath=$(git -C "$NEW" config --get core.quotepath || echo unset)"
    echo "env: MSYS_NO_PATHCONV=$MSYS_NO_PATHCONV PYTHONUTF8=$PYTHONUTF8 (전역 — 독립 검증 Windows 실행과 같은 조건)"
    python --version
    python -m pytest --version 2>&1 | head -1
    echo "ansible-playbook: $(ansible-playbook --version >/dev/null 2>&1 && echo present || echo absent)"
    git --version
    uname -srm
  } > "$E/windows-clone/env.txt" 2>&1
  # eol 속성 대상 3경로가 LF 로 풀렸는지(G5)
  (cd "$NEW" && for f in tests/fixtures/prodgen/sample.cfg tests/fixtures/prodgen/sample_module.py tests/fixtures/prodgen/sample_tasks.yml tests/scripts/finalize_corpus_check.py tests/reference/redfish/mock2/SHA256SUMS; do
     printf '%s CR=%s\n' "$f" "$(tr -cd '\r' < "$f" | wc -c)"; done) >> "$E/windows-clone/env.txt" 2>&1
  cd "$NEW" || exit 1
  CI_GATE_JUNIT_DIR="$E/windows-clone" bash scripts/ai/ci_gate.sh > "$E/windows-clone/ci_gate.log" 2>&1
  rc=$?
  echo "ci_gate_rc=$rc" >> "$E/windows-clone/ci_gate.log"
  tail -4 "$E/windows-clone/ci_gate.log"
  exit 0
fi

if [ "$PHASE" = repro ]; then
  [ -d "$NEW" ] || { echo "no new clone"; exit 3; }
  if [ ! -e "$OLD" ]; then
    # --no-checkout: 기준 커밋을 처음부터 checkout 해야 eol 속성 없는 파일이 그 커밋의 규칙(autocrlf=true → CRLF)으로 풀린다.
    #   브랜치 HEAD 를 먼저 풀고 옮기면 blob 이 같은 파일은 다시 쓰지 않아 LF 가 남는다(2026-10-28 첫 시도에서 G5 미재현).
    git clone -q --no-hardlinks --no-checkout "$W" "$OLD" || exit 1
    git -C "$OLD" checkout -q --detach "$BASE" || exit 1
  fi
  [ "$(git -C "$OLD" rev-parse HEAD)" = "$BASE" ] || { echo "base mismatch"; exit 4; }
  [ "$(git -C "$NEW" rev-parse HEAD)" = "$EXPECT" ] || { echo "head mismatch"; exit 4; }
  R=$E/repro-windows
  mkdir -p "$R"
  T="tests/unit/test_addon_checkout.py tests/unit/prodgen/test_fixtures_golden.py tests/unit/test_jenkinsfile_ci.py"
  for side in base new; do
    if [ $side = base ]; then d=$OLD; else d=$NEW; fi
    # shellcheck disable=SC2086
    (cd "$d" && echo "[repro] head=$(git rev-parse --short HEAD) autocrlf=$(git config --get core.autocrlf) MSYS_NO_PATHCONV=$MSYS_NO_PATHCONV" \
      && for f in tests/fixtures/prodgen/sample.cfg tests/scripts/finalize_corpus_check.py tests/reference/redfish/mock2/SHA256SUMS; do printf '%s CR=%s\n' "$f" "$(tr -cd '\r' < "$f" | wc -c)"; done \
      && python -m pytest $T -q -p no:cacheprovider) > "$R/G4G5_$side.log" 2>&1
    echo "rc=$?" >> "$R/G4G5_$side.log"
    echo "== G4G5_$side: $(grep -E 'passed|failed' "$R/G4G5_$side.log" | tail -1)"
  done
  exit 0
fi
echo "unknown phase"; exit 2
