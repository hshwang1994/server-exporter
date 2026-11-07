#!/bin/bash
# Tier 0 — Windows 작업 트리 ci_gate (Git Bash). 2026-10-28 판(../../2026-10-28-redfish-mock2-review-fix/tools/tier0_win.sh gate)과 달리
# 새 clone 을 만들지 않고 저장소 작업 트리에서 돌린다 — 저장소 밖에 폴더를 새로 만들지 않기 위해서다. 추적 파일 변경이 있으면 돌리지 않는다.
# ansible 이 없는 Windows 에서는 ci_gate 가 syntax-check 를 건너뛰므로 PARTIAL(rc 2)이 설계상 정상이다. 공식 Runner CI 가 아니다.
# 사용: bash tests/evidence/2026-10-29-redfish-summary-fix/tools/tier0_win.sh <기대 HEAD sha> [출력 폴더]
#   출력 폴더 인자는 실행(2026-10-31) 뒤에 더했다. 생략하면 그 실행의 위치(tier0/windows-worktree)다 — 이미 있으면 exit 3 이므로 재실행은 다른 폴더를 준다
set -u
EXPECT=${1:?expected sha}
W=C:/github/ClovirONE/clovirone-server-gathering
E=${2:-$W/tests/evidence/2026-10-29-redfish-summary-fix/tier0/windows-worktree}
cd "$W" || exit 1
H=$(git rev-parse HEAD)
[ "$H" = "$EXPECT" ] || { echo "HEAD mismatch: $H != $EXPECT"; exit 4; }
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "tracked changes present"; exit 5; }
[ -e "$E" ] && { echo "exists: $E"; exit 3; }
mkdir -p "$E" || exit 1
{
  echo "date_utc: $(date -u +%FT%TZ)"
  echo "worktree: $W head: $H branch: $(git branch --show-current)"
  echo "core.autocrlf=$(git config --get core.autocrlf || echo unset) ($(git config --show-origin --get core.autocrlf | cut -f1))"
  echo "core.fileMode=$(git config --get core.fileMode || echo unset)"
  echo "core.quotepath=$(git config --get core.quotepath || echo unset)"
  echo "untracked at start:"; git status --porcelain | sed 's/^/  /'
  echo "env: MSYS_NO_PATHCONV=${MSYS_NO_PATHCONV:-unset} PYTHONUTF8=${PYTHONUTF8:-unset}"
  python --version
  python -m pytest --version 2>&1 | head -1
  echo "ansible-playbook: $(ansible-playbook --version >/dev/null 2>&1 && echo present || echo absent)"
  git --version
  uname -srm
} > "$E/env.txt" 2>&1
CI_GATE_JUNIT_DIR="$E" bash scripts/ai/ci_gate.sh > "$E/ci_gate.log" 2>&1
rc=$?
echo "ci_gate_rc=$rc" >> "$E/ci_gate.log"
echo "untracked at end:" >> "$E/env.txt"; git status --porcelain | sed 's/^/  /' >> "$E/env.txt"
tail -4 "$E/ci_gate.log"
exit 0
