#!/bin/bash
# Tier 0 — Linux 공식 등가 gate (env -i · 격리 venv · ext4 새 clone). 2026-10-28 판(../../2026-10-28-redfish-mock2-review-fix/tools/tier0_wsl.sh)의
# gate 부분을 이 브랜치 · 증거 폴더로만 바꿨다(repro 부분 없음). 공식 Runner CI 가 아니다 — "로컬 Linux 등가 gate" 로만 보고한다.
# 사용: MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash /mnt/c/<저장소>/tests/evidence/2026-10-29-redfish-summary-fix/tools/tier0_wsl.sh <기대 HEAD sha>
set -u
EXPECT=${1:?expected sha}
C=$HOME/se-fix-20261029
V=$HOME/venv-se-ci-20261028
W=/mnt/c/github/ClovirONE/clovirone-server-gathering
E=$W/tests/evidence/2026-10-29-redfish-summary-fix/tier0
BR=fix/redfish-mock2-summary-20261028

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
