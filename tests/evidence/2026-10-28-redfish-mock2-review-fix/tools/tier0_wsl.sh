#!/bin/bash
# Tier 0 — Linux 공식 등가(env -i · 격리 venv · ext4 새 clone) + WSL 묶음별 FAIL → PASS 재현 (G1 · G2 · G3)
# 사용: bash tier0_wsl.sh <기대 HEAD sha> <phase: gate|repro>
set -u
EXPECT=${1:?expected sha}
PHASE=${2:?phase}
C=$HOME/se-fix-20261028
B=$HOME/se-fix-20261028-base
V=$HOME/venv-se-ci-20261028
W=/mnt/c/github/ClovirONE/clovirone-server-gathering
E=$W/tests/evidence/2026-10-28-redfish-mock2-review-fix/tier0
BR=fix/redfish-mock2-review-20261028
BASE=f92ebe6ad338693c7d993434ca7190129a4b7639

if [ "$PHASE" = gate ]; then
  [ -e "$C" ] && { echo "exists: $C"; exit 3; }
  git clone -q "$W" "$C" || exit 1
  git -C "$C" checkout -q "$BR" || exit 1
  H=$(git -C "$C" rev-parse HEAD)
  [ "$H" = "$EXPECT" ] || { echo "HEAD mismatch: $H != $EXPECT"; exit 4; }
  mkdir -p "$E/linux-venv"
  {
    echo "date_utc: $(date -u +%FT%TZ)"
    echo "clone: $C (ext4) head: $H branch: $(git -C "$C" branch --show-current)"
    echo "core.autocrlf=$(git -C "$C" config --get core.autocrlf || echo unset)"
    echo "core.fileMode=$(git -C "$C" config --get core.fileMode || echo unset)"
    echo "core.quotepath=$(git -C "$C" config --get core.quotepath || echo unset)"
    echo "crlf_files_in_checkout=$(cd "$C" && git ls-files -z | xargs -0 grep -lI $'\r' 2>/dev/null | wc -l)"
    echo "venv: $V"
    "$V/bin/python" --version
    "$V/bin/ansible" --version | head -1
    grep include-system-site-packages "$V/pyvenv.cfg"
    "$V/bin/ansible-galaxy" collection list 2>/dev/null | grep -E '^(community[.]vmware|ansible[.]windows|vmware[.]vmware) '
    uname -srm
    git --version
    echo "env: env -i HOME=\$HOME LANG=C.UTF-8 PATH=$V/bin:/usr/local/bin:/usr/bin:/bin SE_ANSIBLE_VENV=$V"
  } > "$E/linux-venv/env.txt" 2>&1
  "$V/bin/pip" freeze > "$E/linux-venv/pip_freeze.txt"
  cd "$C" || exit 1
  # Jenkinsfile_ci Gate 와 같은 명령: activate_ansible_venv.sh → ci_gate.sh (JUnit 기록)
  env -i HOME="$HOME" LANG=C.UTF-8 PATH="$V/bin:/usr/local/bin:/usr/bin:/bin" SE_ANSIBLE_VENV="$V" \
    bash -c 'set -o pipefail; . scripts/activate_ansible_venv.sh || exit 1
             echo "[tier0] venv=${VIRTUAL_ENV:-} pwsh=$(command -v pwsh || echo absent) powershell.exe=$(command -v powershell.exe || echo absent)"
             echo "[tier0] python=$(command -v python3) $(python3 --version 2>&1) pytest=$(python3 -m pytest --version 2>&1 | head -1)"
             CI_GATE_JUNIT_DIR="'"$E/linux-venv"'" bash scripts/ai/ci_gate.sh' > "$E/linux-venv/ci_gate.log" 2>&1
  rc=$?
  echo "ci_gate_rc=$rc" >> "$E/linux-venv/ci_gate.log"
  tail -4 "$E/linux-venv/ci_gate.log"
  exit 0
fi

if [ "$PHASE" = repro ]; then
  [ -d "$C" ] || { echo "no clone"; exit 3; }
  [ -e "$B" ] || git -C "$C" worktree add -q --detach "$B" "$BASE" || exit 1
  [ "$(git -C "$B" rev-parse HEAD)" = "$BASE" ] || { echo "base mismatch"; exit 4; }
  [ "$(git -C "$C" rev-parse HEAD)" = "$EXPECT" ] || { echo "head mismatch"; exit 4; }
  R=$E/repro-wsl
  mkdir -p "$R"
  run() {   # run <tag> <dir> <login-shell PATH: login|venv> <pytest args...>
    local tag=$1 dir=$2 mode=$3; shift 3
    if [ "$mode" = login ]; then
      # WSL 기본 셸 그대로: 시스템 python3 + 사용자 site pytest, PATH 에 Windows interop(powershell.exe) 포함
      bash -lc 'cd "$1" || exit 9; shift; echo "[repro] cwd=$PWD head=$(git rev-parse --short HEAD) python=$(command -v python3) pytest=$(python3 -m pytest --version 2>&1 | head -1) powershell.exe=$(command -v powershell.exe || echo absent) fileMode=$(git config --get core.fileMode)"; python3 -m pytest "$@" -q -p no:cacheprovider' _ "$dir" "$@" > "$R/$tag.log" 2>&1
    fi
    echo "rc=$?" >> "$R/$tag.log"
    echo "== $tag: $(grep -E '^[0-9]+ (passed|failed)|passed|failed' "$R/$tag.log" | tail -1)"
  }
  G1="tests/unit/test_seam_leak_guard.py"
  G2="tests/unit/prodgen/test_pipeline_tmp_repo.py tests/unit/prodgen/test_promotion_cycle.py"
  G3="tests/unit/test_windows_*.py"
  # shellcheck disable=SC2086
  run G1_base "$B" login $G1
  run G1_new  "$C" login $G1
  run G2_base "$B" login $G2
  run G2_new  "$C" login $G2
  (cd "$B" && ls tests/unit/test_windows_*.py) > "$R/G3_files.txt" 2>&1
  run G3_base "$B" login $(cd "$B" && ls tests/unit/test_windows_*.py)
  run G3_new  "$C" login $(cd "$C" && ls tests/unit/test_windows_*.py)
  exit 0
fi
echo "unknown phase"; exit 2
