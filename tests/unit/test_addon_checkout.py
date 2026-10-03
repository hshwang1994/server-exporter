"""scripts/addon_checkout.sh 행위 명세 — Add-on 저장소를 빌드마다 받는 규칙.

Jenkinsfile_portal Gather stage 가 부르는 스크립트를 bash + 실제 git(로컬 file:// 저장소)으로 실행해 확인한다.
  - ref 는 브랜치 · refs/tags/<태그> · refs/heads/<브랜치> · 40자 커밋 해시 — 네 형태가 같은 흐름으로 받아진다
  - 광고되지 않은(ref 끝이 아닌) 커밋 해시는 1차(얕은 fetch)가 거부돼도 2차(전체 fetch)로 받는다
  - 짧은 해시 · 옵션처럼 보이는 ref · '..' 가 든 ref · 없는 ref · 없는 저장소는 `[addon] unavailable:` 와 rc 1
  - 대상 디렉터리는 시작할 때 비운다 (이전 빌드 파일이 남지 않는다)
  - ADDON_REPO_SSL_VERIFY=true 도 같은 흐름 (TLS 가 없는 file:// 에서는 차이가 없다)

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
SCRIPT = REPO_ROOT / "scripts" / "addon_checkout.sh"
ASKPASS = REPO_ROOT / "scripts" / "addon_askpass.sh"

CASES = [
    "branch_main",
    "branch_feature",
    "tag",
    "refs_heads",
    "full_sha_tip",
    "full_sha_unadvertised_uses_fallback",
    "stale_files_removed",
    "short_sha_rejected",
    "option_like_ref_rejected",
    "dotdot_ref_rejected",
    "missing_ref_fails",
    "missing_repo_fails",
    "ssl_verify_true_same_flow",
    "askpass_answers_from_env",
]

DRIVER = r"""
set -u
SCRIPT_IN="$1"; ASKPASS_IN="$2"
if command -v cygpath >/dev/null 2>&1; then
  SCRIPT="$(cygpath -u "$SCRIPT_IN")"; ASKPASS="$(cygpath -u "$ASKPASS_IN")"
else
  SCRIPT="$SCRIPT_IN"; ASKPASS="$ASKPASS_IN"
fi
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
export GIT_CONFIG_NOSYSTEM=1 HOME="$T/home"; mkdir -p "$HOME"
git config --global user.email t@example.com; git config --global user.name t; git config --global init.defaultBranch main

# 원격 저장소: main 3 commit (c1 → c2 → c3), feature 는 c1 에서 분기, 태그 v1 = c1
R="$T/remote"; mkdir -p "$R"; git -C "$R" init -q
echo one > "$R/a.txt"; git -C "$R" add a.txt; git -C "$R" commit -q -m c1; C1="$(git -C "$R" rev-parse HEAD)"
git -C "$R" tag v1
git -C "$R" checkout -q -b feature; echo feat > "$R/b.txt"; git -C "$R" add b.txt; git -C "$R" commit -q -m f1; F1="$(git -C "$R" rev-parse HEAD)"
git -C "$R" checkout -q main
echo two > "$R/a.txt"; git -C "$R" commit -q -am c2; C2="$(git -C "$R" rev-parse HEAD)"
echo three > "$R/c.txt"; git -C "$R" add c.txt; git -C "$R" commit -q -m c3; C3="$(git -C "$R" rev-parse HEAD)"
if command -v cygpath >/dev/null 2>&1; then RW="$(cygpath -m "$R")"; else RW="$R"; fi
case "$RW" in /*) URL="file://$RW";; *) URL="file:///$RW";; esac
D="$T/work/addon"

report() { echo "CASE $1 $2 ${3:-}"; }
run() { out="$(bash "$SCRIPT" "$@" 2>"$T/err")"; rc=$?; err="$(cat "$T/err")"; }
head_of() { git -C "$D" rev-parse HEAD 2>/dev/null; }

run "$URL" main "$D"
if [ $rc -eq 0 ] && [ "$(head_of)" = "$C3" ] && [ -f "$D/c.txt" ] && [ "$out" = "[addon] ${URL}@main ${C3}" ]; then report branch_main PASS; else report branch_main FAIL "rc=$rc out=$out err=$err"; fi

run "$URL" feature "$D"
if [ $rc -eq 0 ] && [ "$(head_of)" = "$F1" ] && [ -f "$D/b.txt" ] && [ ! -f "$D/c.txt" ]; then report branch_feature PASS; else report branch_feature FAIL "rc=$rc out=$out err=$err"; fi

run "$URL" refs/tags/v1 "$D"
if [ $rc -eq 0 ] && [ "$(head_of)" = "$C1" ] && [ ! -f "$D/c.txt" ]; then report tag PASS; else report tag FAIL "rc=$rc out=$out err=$err"; fi

run "$URL" refs/heads/feature "$D"
if [ $rc -eq 0 ] && [ "$(head_of)" = "$F1" ]; then report refs_heads PASS; else report refs_heads FAIL "rc=$rc out=$out err=$err"; fi

run "$URL" "$C3" "$D"
if [ $rc -eq 0 ] && [ "$(head_of)" = "$C3" ] && [ "$out" = "[addon] ${URL}@${C3} ${C3}" ]; then report full_sha_tip PASS; else report full_sha_tip FAIL "rc=$rc out=$out err=$err"; fi

# c2 는 어떤 ref 의 끝도 아니다 → 서버가 1차(얕은 fetch)를 거부할 수 있다 → 2차로 받는다
run "$URL" "$C2" "$D"
if [ $rc -eq 0 ] && [ "$(head_of)" = "$C2" ] && [ ! -f "$D/c.txt" ] && [ "$(cat "$D/a.txt")" = two ]; then report full_sha_unadvertised_uses_fallback PASS; else report full_sha_unadvertised_uses_fallback FAIL "rc=$rc out=$out err=$err"; fi

mkdir -p "$D/leftover"; echo x > "$D/leftover/stale.txt"; echo x > "$D/stale.txt"
run "$URL" main "$D"
if [ $rc -eq 0 ] && [ ! -e "$D/stale.txt" ] && [ ! -e "$D/leftover" ] && [ -f "$D/c.txt" ]; then report stale_files_removed PASS; else report stale_files_removed FAIL "rc=$rc out=$out err=$err"; fi

run "$URL" "${C3:0:8}" "$D"
if [ $rc -eq 1 ] && [ -z "$out" ] && printf '%s' "$err" | grep -q '^\[addon\] unavailable: .*40자'; then report short_sha_rejected PASS; else report short_sha_rejected FAIL "rc=$rc out=$out err=$err"; fi

run "$URL" "--upload-pack=echo" "$D"
if [ $rc -eq 1 ] && [ -z "$out" ] && printf '%s' "$err" | grep -q '^\[addon\] unavailable: ref 형식 오류'; then report option_like_ref_rejected PASS; else report option_like_ref_rejected FAIL "rc=$rc out=$out err=$err"; fi

run "$URL" "main/../feature" "$D"
if [ $rc -eq 1 ] && printf '%s' "$err" | grep -q 'ref 형식 오류'; then report dotdot_ref_rejected PASS; else report dotdot_ref_rejected FAIL "rc=$rc out=$out err=$err"; fi

run "$URL" no-such-branch "$D"
if [ $rc -eq 1 ] && [ -z "$out" ] && printf '%s' "$err" | grep -q '^\[addon\] unavailable: ' && printf '%s' "$err" | grep -q 'no-such-branch'; then report missing_ref_fails PASS; else report missing_ref_fails FAIL "rc=$rc out=$out err=$err"; fi

run "file:///$T/no-such-repo" main "$D"
if [ $rc -eq 1 ] && [ -z "$out" ] && printf '%s' "$err" | grep -q '^\[addon\] unavailable: '; then report missing_repo_fails PASS; else report missing_repo_fails FAIL "rc=$rc out=$out err=$err"; fi

ADDON_REPO_SSL_VERIFY=true run "$URL" main "$D"
if [ $rc -eq 0 ] && [ "$(head_of)" = "$C3" ]; then report ssl_verify_true_same_flow PASS; else report ssl_verify_true_same_flow FAIL "rc=$rc out=$out err=$err"; fi

u="$(ADDON_REPO_USER=alice ADDON_REPO_PASSWORD='s3cr3t' bash "$ASKPASS" "Username for 'https://git.example':")"
p="$(ADDON_REPO_USER=alice ADDON_REPO_PASSWORD='s3cr3t' bash "$ASKPASS" "Password for 'https://alice@git.example':")"
if [ "$u" = alice ] && [ "$p" = s3cr3t ]; then report askpass_answers_from_env PASS; else report askpass_answers_from_env FAIL "u=$u p=$p"; fi
"""


def _find_bash() -> str | None:
    """Git for Windows 의 bash 를 우선한다 — PATH 의 bash.exe 는 WSL 런처일 수 있다."""
    explicit = os.environ.get("SE_TEST_BASH")
    if explicit and pathlib.Path(explicit).is_file():
        return explicit
    if sys.platform == "win32":
        candidates = [r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"]
        try:
            exec_path = subprocess.run(["git", "--exec-path"], capture_output=True, text=True, timeout=10).stdout.strip()
            if exec_path:
                candidates.insert(0, str(pathlib.Path(exec_path).parents[2] / "bin" / "bash.exe"))
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
    if not bash or not shutil.which("git"):
        pytest.skip("bash (Git for Windows / Linux) 또는 git 을 찾지 못함")
    proc = subprocess.run(
        [bash, "-c", DRIVER, "driver", str(SCRIPT), str(ASKPASS)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    results: dict[str, tuple[str, str]] = {}
    for line in proc.stdout.splitlines():
        if line.startswith("CASE "):
            _, name, verdict, *detail = line.split(" ", 3)
            results[name] = (verdict, detail[0] if detail else "")
    assert results, f"driver produced no CASE lines\nrc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    return results


@pytest.mark.parametrize("case", CASES)
def test_script_behaviour(case_results, case):
    assert case in case_results, f"case '{case}' 결과 없음: {case_results}"
    verdict, detail = case_results[case]
    assert verdict == "PASS", f"{case}: {detail}"


@pytest.mark.parametrize("path", [SCRIPT, ASKPASS], ids=lambda p: p.name)
def test_scripts_have_lf_line_endings_and_bash_shebang(path):
    raw = path.read_bytes()
    assert b"\r\n" not in raw, "CRLF 가 섞이면 Linux 에서 실행이 깨진다"
    assert raw.startswith(b"#!/bin/bash\n")


@pytest.mark.parametrize("path", [SCRIPT, ASKPASS], ids=lambda p: p.name)
@pytest.mark.source_text   # 저장소 메타/문서/주석 의존 — production tree overlay(G14) 제외
def test_scripts_are_executable_in_git_index(path):
    """Jenkins 가 받은 그대로 실행한다 (GIT_ASKPASS 는 git 이 직접 실행) — 인덱스 모드가 100755 여야 한다."""
    rel = path.relative_to(REPO_ROOT).as_posix()
    out = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "-s", "--", rel],
                         capture_output=True, text=True, timeout=10).stdout
    assert out.startswith("100755 "), f"{rel}: git index mode = {out.split(' ', 1)[0] or '(untracked)'}"


def test_ssl_verify_is_scoped_to_the_scripts_own_git_commands():
    text = SCRIPT.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "-c http.sslVerify=false" in body, "검증 해제는 git 명령 옵션(-c)으로만"
    for forbidden in ("git config --global", "git config --system", "GIT_SSL_NO_VERIFY", "update-ca-trust", "ca-certificates"):
        assert forbidden not in body, f"'{forbidden}' — 전역 설정 · Runner 변경은 하지 않는다"
    assert "GIT_TERMINAL_PROMPT=0" in body, "자격증명이 없을 때 묻지 않고 실패해야 빌드가 멈추지 않는다"
    assert "rm -rf -- \"$dest\"" in body, "대상 디렉터리는 시작할 때 비운다"
    assert "git clone" not in body, "clone --branch 는 커밋 해시를 받지 못한다 — fetch 흐름만 쓴다"


def test_askpass_never_prints_when_unset():
    text = ASKPASS.read_text(encoding="utf-8")
    assert "ADDON_REPO_USER" in text and "ADDON_REPO_PASSWORD" in text
    assert "echo $" not in text and "set -x" not in text
