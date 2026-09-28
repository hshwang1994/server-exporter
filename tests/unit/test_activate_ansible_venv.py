"""scripts/activate_ansible_venv.sh 행위 명세 — venv 선택 규칙과 실패 시 동작.

Jenkins Stage 가 source 하는 헬퍼가 다음을 지키는지 bash 로 실제 실행해 확인한다.
  - SE_ANSIBLE_VENV 가 있으면 그 venv 만 쓰고, 없으면 다른 곳으로 넘어가지 않고 실패한다
  - PATH 의 ansible-playbook 실경로 옆에 activate 가 있을 때만 그 venv 를 채택한다
  - activate 없는 stray ansible-playbook 은 건너뛰고 알려진 후보 경로로 내려간다
  - 아무것도 없으면 실패하고, `. helper || exit 1` 뒤 명령은 실행되지 않는다
  - 활성화 뒤 python3 이 venv 밖이면 실패한다 / 두 번 source 해도 무해하다

Windows 에서는 Git for Windows 의 bash 를 쓴다 (PATH 의 bash 는 WSL 일 수 있다).
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts" / "activate_ansible_venv.sh"

CASES = [
    "env_ok",
    "env_invalid_no_fallback",
    "path_derived",
    "stray_then_known",
    "nothing_found_fails",
    "executed_mode_exit1",
    "source_twice",
    "python_outside_venv_fails",
]

# bash 드라이버: 가짜 venv 들을 mktemp 아래에 만들고 케이스마다 서브셸에서 헬퍼를 source 한다.
# 결과는 "CASE <이름> PASS|FAIL <상세>" 한 줄씩 stdout 으로 낸다.
DRIVER = r"""
set -u
HELPER_IN="$1"
if command -v cygpath >/dev/null 2>&1; then HELPER="$(cygpath -u "$HELPER_IN")"; else HELPER="$HELPER_IN"; fi
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
BASEPATH="/usr/bin:/bin"

mkvenv() {  # $1=dir $2=label $3=prepend_path(yes|no)
  mkdir -p "$1/bin"
  {
    echo "VIRTUAL_ENV=\"$1\""
    echo 'export VIRTUAL_ENV'
    if [ "$3" = yes ]; then
      echo '_OLD_VIRTUAL_PATH="$PATH"'
      echo 'PATH="$VIRTUAL_ENV/bin:$PATH"'
      echo 'export PATH'
    fi
    echo 'deactivate () { PATH="${_OLD_VIRTUAL_PATH:-$PATH}"; export PATH; unset VIRTUAL_ENV; unset -f deactivate; }'
  } > "$1/bin/activate"
  printf '#!/bin/bash\necho "Python 3.99.%s fake"\n' "$2" > "$1/bin/python3"
  printf '#!/bin/bash\necho "ansible-playbook fake %s"\n' "$2" > "$1/bin/ansible-playbook"
  chmod +x "$1/bin/python3" "$1/bin/ansible-playbook"
}
mkvenv "$T/venvA" A yes
mkvenv "$T/venvB" B yes
mkvenv "$T/venvC" C yes
mkvenv "$T/venvD" D no
mkdir -p "$T/stray"
printf '#!/bin/bash\necho stray\n' > "$T/stray/ansible-playbook"; chmod +x "$T/stray/ansible-playbook"

report() { echo "CASE $1 $2 ${3:-}"; }

# A. env override
out=$( ( export PATH="$BASEPATH" SE_ANSIBLE_VENV="$T/venvA" SE_ANSIBLE_VENV_CANDIDATES=""; . "$HELPER" 2>"$T/errA" || exit 9; echo "VE=$VIRTUAL_ENV PY=$(command -v python3)" ) ); rc=$?
if [ $rc -eq 0 ] && [ "$out" = "VE=$T/venvA PY=$T/venvA/bin/python3" ] && grep -q 'source=env' "$T/errA"; then report env_ok PASS; else report env_ok FAIL "rc=$rc out=$out err=$(cat "$T/errA")"; fi

# B. env override set but invalid — must not fall back to candidates
out=$( ( export PATH="$BASEPATH" SE_ANSIBLE_VENV="$T/nope" SE_ANSIBLE_VENV_CANDIDATES="$T/venvB"; . "$HELPER" 2>"$T/errB" || exit 9; echo SENTINEL ) ); rc=$?
if [ $rc -eq 9 ] && [ "$out" = "" ] && grep -q 'SE_ANSIBLE_VENV' "$T/errB"; then report env_invalid_no_fallback PASS; else report env_invalid_no_fallback FAIL "rc=$rc out=$out err=$(cat "$T/errB")"; fi

# C. PATH-derived (symlink if supported, else the real bin dir on PATH)
mkdir -p "$T/links"; ln -s "$T/venvB/bin/ansible-playbook" "$T/links/ansible-playbook" 2>/dev/null || true
if [ -L "$T/links/ansible-playbook" ]; then PPATH="$T/links:$BASEPATH"; note=symlink; else PPATH="$T/venvB/bin:$BASEPATH"; note=nosymlink; fi
out=$( ( export PATH="$PPATH" SE_ANSIBLE_VENV_CANDIDATES=""; unset SE_ANSIBLE_VENV; . "$HELPER" 2>"$T/errC" || exit 9; echo "VE=$VIRTUAL_ENV PY=$(command -v python3)" ) ); rc=$?
if [ $rc -eq 0 ] && [ "$out" = "VE=$T/venvB PY=$T/venvB/bin/python3" ] && grep -q 'source=path' "$T/errC"; then report path_derived PASS "$note"; else report path_derived FAIL "$note rc=$rc out=$out err=$(cat "$T/errC")"; fi

# D. stray ansible-playbook on PATH (no activate) → skipped → known candidates
out=$( ( export PATH="$T/stray:$BASEPATH" SE_ANSIBLE_VENV_CANDIDATES="$T/nope1 $T/venvC"; unset SE_ANSIBLE_VENV; . "$HELPER" 2>"$T/errD" || exit 9; echo "VE=$VIRTUAL_ENV PY=$(command -v python3)" ) ); rc=$?
if [ $rc -eq 0 ] && [ "$out" = "VE=$T/venvC PY=$T/venvC/bin/python3" ] && grep -q 'source=known' "$T/errD"; then report stray_then_known PASS; else report stray_then_known FAIL "rc=$rc out=$out err=$(cat "$T/errD")"; fi

# E. nothing found → fail, sentinel after `|| exit 1` never runs, diagnostics on stderr
out=$( ( export PATH="$T/stray:$BASEPATH" SE_ANSIBLE_VENV_CANDIDATES="$T/nope1 $T/nope2"; unset SE_ANSIBLE_VENV; . "$HELPER" 2>"$T/errE" || exit 1; echo SENTINEL ) ); rc=$?
if [ $rc -eq 1 ] && [ "$out" = "" ] && grep -q '찾지 못했습니다' "$T/errE" && grep -q "후보='$T/nope1 $T/nope2'" "$T/errE"; then report nothing_found_fails PASS; else report nothing_found_fails FAIL "rc=$rc out=$out err=$(cat "$T/errE")"; fi

# F. executed (not sourced) with nothing found → exit 1
( export PATH="$T/stray:$BASEPATH" SE_ANSIBLE_VENV_CANDIDATES="$T/nope1"; unset SE_ANSIBLE_VENV; bash "$HELPER" >/dev/null 2>"$T/errF" ); rc=$?
if [ $rc -eq 1 ]; then report executed_mode_exit1 PASS; else report executed_mode_exit1 FAIL "rc=$rc err=$(cat "$T/errF")"; fi

# G. source twice is harmless
out=$( ( export PATH="$BASEPATH" SE_ANSIBLE_VENV="$T/venvA" SE_ANSIBLE_VENV_CANDIDATES=""; . "$HELPER" 2>/dev/null || exit 9; . "$HELPER" 2>/dev/null || exit 8; echo "VE=$VIRTUAL_ENV PY=$(command -v python3)" ) ); rc=$?
if [ $rc -eq 0 ] && [ "$out" = "VE=$T/venvA PY=$T/venvA/bin/python3" ]; then report source_twice PASS; else report source_twice FAIL "rc=$rc out=$out"; fi

# H. activate that leaves python3 outside the venv → fail
out=$( ( export PATH="$BASEPATH" SE_ANSIBLE_VENV="$T/venvD" SE_ANSIBLE_VENV_CANDIDATES=""; . "$HELPER" 2>"$T/errH" || exit 9; echo SENTINEL ) ); rc=$?
if [ $rc -eq 9 ] && [ "$out" = "" ] && grep -q 'venv 밖' "$T/errH"; then report python_outside_venv_fails PASS; else report python_outside_venv_fails FAIL "rc=$rc out=$out err=$(cat "$T/errH")"; fi
"""


def _find_bash() -> str | None:
    """Git for Windows 의 bash 를 우선한다 — PATH 의 bash.exe 는 WSL 런처일 수 있다."""
    explicit = os.environ.get("SE_TEST_BASH")
    if explicit and pathlib.Path(explicit).is_file():
        return explicit
    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files\Git\usr\bin\bash.exe",
        ]
        try:
            exec_path = subprocess.run(["git", "--exec-path"], capture_output=True, text=True, timeout=10).stdout.strip()
            if exec_path:
                git_root = pathlib.Path(exec_path).parents[2]  # <root>/mingw64/libexec/git-core
                candidates.insert(0, str(git_root / "bin" / "bash.exe"))
        except Exception:  # noqa: BLE001
            pass
        for c in candidates:
            if pathlib.Path(c).is_file():
                return c
        found = shutil.which("bash")
        if found and "system32" not in found.lower() and "windowsapps" not in found.lower():
            return found
        return None
    return shutil.which("bash")


@pytest.fixture(scope="module")
def case_results() -> dict[str, tuple[str, str]]:
    bash = _find_bash()
    if not bash:
        pytest.skip("bash (Git for Windows / Linux) 를 찾지 못함")
    proc = subprocess.run(
        [bash, "-c", DRIVER, "driver", str(HELPER)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    results: dict[str, tuple[str, str]] = {}
    for line in proc.stdout.splitlines():
        if line.startswith("CASE "):
            _, name, verdict, *detail = line.split(" ", 3)
            results[name] = (verdict, detail[0] if detail else "")
    assert results, f"driver produced no CASE lines\nrc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    return results


@pytest.mark.parametrize("case", CASES)
def test_helper_behaviour(case_results, case):
    assert case in case_results, f"case '{case}' 결과 없음: {case_results}"
    verdict, detail = case_results[case]
    assert verdict == "PASS", f"{case}: {detail}"


def test_helper_has_lf_line_endings_and_bash_shebang():
    raw = HELPER.read_bytes()
    assert b"\r\n" not in raw, "CRLF 가 섞이면 Linux 에서 sourcing 이 깨진다"
    assert raw.startswith(b"#!/bin/bash\n")


def test_helper_keeps_callers_shell_state_untouched():
    """헬퍼는 호출자의 set 옵션·trap·작업 디렉터리를 바꾸지 않는다 (Gather 의 trap EXIT 보호)."""
    text = HELPER.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    for forbidden in ("set -e", "set -u", "set -x", "set -o", "trap ", "\ncd "):
        assert forbidden not in body, f"헬퍼에 '{forbidden.strip()}' 이 있으면 호출 Stage 의 셸 상태를 바꾼다"
