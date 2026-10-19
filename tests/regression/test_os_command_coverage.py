"""OS 전수 덤프 명령 vs os-gather 사용 명령 — 덤프가 보여 주는 명령 가운데 수집기가 호출하지 않는 것은 허용 목록에 사유가 있어야 한다 (2026-10-19).

노출(Linux): tests/reference/os/<distro>/<ip>/cmd_*.txt 의 첫 줄 `# command: …` 를 세미콜론·파이프·&&·$() 로 쪼개 실행 파일 이름을
             뽑는다 (`/opt/MegaRAID/storcli/storcli64` → storcli · `cat /proc/cpuinfo` 처럼 파일을 읽는 명령은 그 경로를 토큰으로).
             head/tail/grep/awk 같은 필터와 for/do/echo 같은 셸 제어어는 명령으로 세지 않는다. 헤더가 없으면 파일 이름의 첫 토큰
             (cmd_ipmitool_sensor → ipmitool)으로 대신한다.
소비(Linux): os-gather/tasks/linux/*.yml (raw 스크립트) + os-gather/files/* 텍스트(주석·Jinja 제거)에 그 이름이 영숫자 경계로 있으면
             소비 — 경로 토큰은 전체 경로 / 글롭 앞부분 / 마지막 파일명 가운데 하나가 있으면 소비.
노출(Windows): 헤더가 Ansible ad-hoc 출력이라 명령이 없다 — cmd_<name>.txt 의 <name> 을 밑줄/대소문자 무시·단복수 허용 정규식으로
             os-gather/tasks/windows/*.yml 텍스트와 대조한다 (computer_system ↔ Win32_ComputerSystem · local_users ↔ Get-LocalUser).
허용 목록: tests/reference/os/coverage_allowlist.yml — linux/windows 각각 commands(사유) + aliases(같은 정보를 읽는 다른 코드 토큰;
             토큰 실존을 시험이 확인). 허용 목록의 명령이 코드에 나타나기 시작하면 "허용 목록에서 지워라" 고 한다.
production tree 에는 tests/reference 가 없으므로 덤프가 없으면 skip 한다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
DUMP_ROOT = REPO / "tests" / "reference" / "os"
ALLOWLIST = DUMP_ROOT / "coverage_allowlist.yml"
LINUX_CODE_FILES = sorted((REPO / "os-gather" / "tasks" / "linux").glob("*.yml")) + sorted((REPO / "os-gather" / "files").glob("*"))
WINDOWS_CODE_FILES = sorted((REPO / "os-gather" / "tasks" / "windows").glob("*.yml"))

DUMP_DIRS = sorted(d for d in DUMP_ROOT.glob("*/*/") if any(d.glob("cmd_*.txt"))) if DUMP_ROOT.is_dir() else []

_CONTROL = {"for", "do", "done", "if", "then", "else", "elif", "fi", "while", "until", "in", "echo", "printf", "test",
            "[", "[[", "]", "]]", "true", "false", "exit", "sleep", "sudo", "env", "nice", "timeout", "command", "exec"}
_FILTERS = {"head", "tail", "sort", "uniq", "grep", "egrep", "fgrep", "awk", "sed", "cut", "tr", "wc", "xargs", "tee", "column", "paste", "less", "more"}
_READERS = {"cat", "ls", "stat", "file", "find", "head", "tail"}
_EXE_ALIASES = {"storcli64": "storcli"}          # 같은 바이너리의 아키텍처 접미사
_EXE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.+-]*$")


def _strip_comments(text: str) -> str:
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    text = re.sub(r"\{\{.*?\}\}", " ", text, flags=re.S)      # Jinja 표현식 — 변수 이름(ip 등)이 명령으로 오인되지 않게
    text = re.sub(r"\{%.*?%\}", " ", text, flags=re.S)        # Jinja 문장(set/if) — 문자열 리터럴('podman' 등)은 명령이 아니다
    text = re.sub(r"(?m)^\s*-?\s*name:\s.*$", "", text)      # YAML task 이름은 산문이다 ("raw getent + last logins")
    text = re.sub(r"(?m)^\s*#.*$", "", text)
    return text


def _text(files) -> str:
    return "\n".join(_strip_comments(p.read_text(encoding="utf-8", errors="replace")) for p in files if p.is_file())


def _header_command(path: Path):
    with path.open(encoding="utf-8", errors="replace") as fh:
        first = fh.readline().strip()
    if first.startswith("# command:"):
        return first[len("# command:"):].strip()
    return None


def commands_from_header(cmd: str) -> list:
    """`# command:` 한 줄 → 실행 파일 이름/읽는 파일 경로 토큰 목록 (중복 제거, 순서 유지)."""
    cmd = re.sub(r"'[^']*'|\"[^\"]*\"", " ", cmd)                       # 따옴표 안(정규식·포맷 문자열)은 명령이 아니다
    out = []
    for seg in re.split(r"\s*(?:;|&&|\|\||\||\$\(|\)|\n)\s*", cmd):
        toks = seg.strip().split()
        if not toks:
            continue
        if toks[0] == "for":                                               # for X in /path/* … → 경로가 대상이다
            out.extend(t for t in toks if t.startswith("/"))
            continue
        while toks and (toks[0] in _CONTROL - {"echo", "printf"} or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0])):
            toks = toks[1:]
        if not toks or toks[0] in ("echo", "printf"):                     # echo N/A 같은 출력 문장은 명령이 아니다
            continue
        first = toks[0]
        if not re.match(r"^[A-Za-z/]", first) or ">" in first or "<" in first:
            continue
        if first in _READERS:
            for arg in toks[1:]:
                if arg.startswith("/"):
                    out.append(re.split(r"[<>]", arg)[0])
                    break
            continue
        if first in _FILTERS:
            continue
        exe = first.rsplit("/", 1)[-1]
        exe = _EXE_ALIASES.get(exe, exe)
        if _EXE_RE.match(exe):
            out.append(exe)
    seen, uniq = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def _found_exe(exe: str, code: str) -> bool:
    """명령 위치에 있는 실행 파일 이름만 — 줄 처음/공백/;/(/백틱/`/bin/`·`/sbin/` 뒤, 공백/줄 끝/;/)/&/> 앞.

    `lo|docker*|virbr*` 같은 case 패턴·정규식 대안(`|` 바로 뒤), `'podman'` 같은 문자열 리터럴, `-w` 같은 옵션은 호출이 아니다.
    """
    pat = r"(?:^|(?<=[\s;(`])|(?<=/bin/)|(?<=/sbin/))" + re.escape(exe) + r"(?=$|[\s;)&>])"
    return re.search(pat, code, re.M) is not None


def _found_path(path: str, code: str) -> bool:
    """읽는 파일 경로 — 전체 경로(글롭 `*` 는 `[^/]*`) 또는 (글롭 없는) 마지막 파일명이 코드에 있으면 소비."""
    cands = [re.escape(path.rstrip("/")).replace(r"\*", r"[^/]*")]
    base = path.rstrip("/").rsplit("/", 1)[-1]
    if base and "*" not in base and len(base) > 3:
        cands.append(r"(?<![A-Za-z0-9_])" + re.escape(base) + r"(?![A-Za-z0-9_])")
    return any(re.search(c, code) for c in cands)


def _found(token: str, code: str) -> bool:
    return _found_path(token, code) if token.startswith("/") else _found_exe(token, code)


def _is_windows(dump_dir: Path) -> bool:
    files = sorted(dump_dir.glob("cmd_*.txt"))
    return bool(files) and _header_command(files[0]) is None


def _ident_words(ident: str) -> list:
    """'Win32_ComputerSystem' → ['win32','computer','system'] · 'Get-DnsClientServerAddress' → ['get','dns','client','server','address']."""
    words = []
    for part in re.split(r"[_-]", ident):
        words.extend(m.lower() for m in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+|[A-Z]+", part))
    return words


def _plural_norm(s: str) -> str:
    return s[:-1] if s.endswith("s") and len(s) > 3 else s


def _windows_consumed(name: str, code: str) -> bool:
    """cmd_<name> 의 <name> 이 코드 식별자의 연속한 단어 묶음과 같으면 소비 (밑줄·대소문자·단복수 무시).

    'computer_system' ↔ Win32_ComputerSystem · 'timezone' ↔ Get-TimeZone · 'local_users' ↔ Get-LocalUser.
    `$env:` 처럼 `$` 로 시작하는 PowerShell 변수는 식별자로 세지 않는다.
    """
    target = _plural_norm("".join(name.split("_")).lower())
    for ident in set(re.findall(r"(?<![$\w])[A-Za-z][A-Za-z0-9_-]*", code)):
        words = _ident_words(ident)
        for i in range(len(words)):
            joined = ""
            for j in range(i, len(words)):
                joined += words[j]
                if len(joined) > len(target) + 1:
                    break
                if _plural_norm(joined) == target:
                    return True
    return False


def _allowlist() -> dict:
    doc = yaml.safe_load(ALLOWLIST.read_text(encoding="utf-8")) or {}
    out = {}
    for os_name in ("linux", "windows"):
        sec = doc.get(os_name) or {}
        out[os_name] = {"commands": sec.get("commands") or {}, "aliases": sec.get("aliases") or {}}
    return out


def exposed_tokens(dump_dir: Path) -> dict:
    """{토큰: [덤프 파일 이름, …]} — Linux 는 헤더 명령에서, Windows 는 파일 이름에서."""
    tokens = {}
    for f in sorted(dump_dir.glob("cmd_*.txt")):
        name = f.name[len("cmd_"):-len(".txt")]
        cmd = _header_command(f)
        toks = commands_from_header(cmd) if cmd else [name if _is_windows(dump_dir) else name.split("_")[0]]
        for t in toks:
            tokens.setdefault(t, []).append(f.name)
    return tokens


@pytest.fixture(scope="module")
def linux_code():
    if not LINUX_CODE_FILES:
        pytest.skip("os-gather/tasks/linux 없음")
    return _text(LINUX_CODE_FILES)


@pytest.fixture(scope="module")
def windows_code():
    if not WINDOWS_CODE_FILES:
        pytest.skip("os-gather/tasks/windows 없음")
    return _text(WINDOWS_CODE_FILES)


def _consumed(token: str, is_windows: bool, code: str) -> bool:
    if is_windows:
        return _windows_consumed(token, code)
    return _found(token, code)


@pytest.mark.skipif(not DUMP_DIRS, reason="tests/reference/os/*/*/cmd_*.txt 없음")
@pytest.mark.skipif(not ALLOWLIST.is_file(), reason="tests/reference/os/coverage_allowlist.yml 없음")
@pytest.mark.parametrize("dump_dir", DUMP_DIRS, ids=[f"{d.parent.name}/{d.name}" for d in DUMP_DIRS])
def test_exposed_commands_are_consumed_or_allowlisted(dump_dir: Path, linux_code: str, windows_code: str):
    win = _is_windows(dump_dir)
    code = windows_code if win else linux_code
    allow = _allowlist()["windows" if win else "linux"]
    unlisted = {}
    for token, files in exposed_tokens(dump_dir).items():
        if _consumed(token, win, code):
            continue
        if token in allow["commands"]:
            continue
        alias = allow["aliases"].get(token)
        if alias and any(_found(a, code) for a in alias):
            continue
        unlisted[token] = files
    if unlisted:
        kind = "windows" if win else "linux"
        lines = [
            f"{dump_dir.parent.name}/{dump_dir.name} ({kind}): os-gather 가 호출하지 않는데 허용 목록에도 없는 명령 {len(unlisted)}개",
            f"읽기 시작했거나 허용 목록에 사유를 적어라 — tests/reference/os/coverage_allowlist.yml ({kind}.commands / {kind}.aliases)",
        ]
        lines.extend(f"  - {t}   <- {files[:3]}" for t, files in sorted(unlisted.items()))
        pytest.fail("\n".join(lines))


@pytest.mark.skipif(not ALLOWLIST.is_file(), reason="허용 목록 없음")
def test_allowlist_commands_are_still_unconsumed(linux_code: str, windows_code: str):
    """허용 목록의 명령이 코드에 나타나기 시작했으면 목록에서 지워야 한다 (stale 허용 목록 방지)."""
    allow = _allowlist()
    stale = {
        "linux": sorted(t for t in allow["linux"]["commands"] if _consumed(t, False, linux_code)),
        "windows": sorted(t for t in allow["windows"]["commands"] if _consumed(t, True, windows_code)),
    }
    stale = {k: v for k, v in stale.items() if v}
    assert not stale, "코드가 이제 호출하는 명령 — 허용 목록(commands)에서 지워라: %s" % json.dumps(stale, ensure_ascii=False)


@pytest.mark.skipif(not ALLOWLIST.is_file(), reason="허용 목록 없음")
def test_allowlist_is_well_formed(linux_code: str, windows_code: str):
    allow = _allowlist()
    for os_name, code in (("linux", linux_code), ("windows", windows_code)):
        sec = allow[os_name]
        assert sec["commands"], f"{os_name}.commands 절이 비었다"
        for t, reason in sec["commands"].items():
            assert isinstance(reason, str) and reason.strip(), f"{os_name}.commands.{t}: 사유가 없다"
            assert t not in sec["aliases"], f"{os_name}: {t} 가 commands 와 aliases 양쪽에 있다"
        for t, tokens in sec["aliases"].items():
            assert isinstance(tokens, list) and tokens, f"{os_name}.aliases.{t}: 토큰 목록이 비었다"
            assert any(_found(a, code) for a in tokens), f"{os_name}.aliases.{t}: 토큰 {tokens} 가 os-gather 코드에 없다 — alias 가 stale 하다"


@pytest.mark.skipif(not DUMP_DIRS or not ALLOWLIST.is_file(), reason="덤프/허용 목록 없음")
def test_allowlist_commands_exist_in_some_dump():
    """덤프 어디에도 없는 명령이 허용 목록에 남아 있으면 오타이거나 덤프 수집 명령이 바뀐 것이다."""
    exposed = {"linux": set(), "windows": set()}
    for d in DUMP_DIRS:
        exposed["windows" if _is_windows(d) else "linux"] |= set(exposed_tokens(d))
    allow = _allowlist()
    for os_name in ("linux", "windows"):
        listed = set(allow[os_name]["commands"]) | set(allow[os_name]["aliases"])
        unknown = sorted(listed - exposed[os_name])
        assert not unknown, f"{os_name}: 덤프에 없는 명령이 허용 목록에 있다: {unknown}"


def test_header_tokenizer_examples():
    """토크나이저 자기시험 — 덤프 헤더의 대표 형태."""
    assert commands_from_header("ipmitool sensor list 2>&1") == ["ipmitool"]
    assert commands_from_header("/opt/MegaRAID/storcli/storcli64 /call show all J 2>&1; storcli /call show all J 2>&1") == ["storcli"]
    assert commands_from_header("cat /proc/cpuinfo") == ["/proc/cpuinfo"]
    assert commands_from_header("for b in /proc/net/bonding/*; do [ -f $b ] && echo '=== '$b' ===' && cat $b; done 2>/dev/null") == ["/proc/net/bonding/*"]
    assert commands_from_header("journalctl -p err -b --no-pager 2>&1 | tail -100") == ["journalctl"]
    assert commands_from_header("for d in $(lsblk -dno NAME | grep -E '^(sd|nvme|hd)'); do echo '=== /dev/'$d' ==='; smartctl -a /dev/$d 2>&1; done") == ["lsblk", "smartctl"]
    assert commands_from_header("tail -200 /var/log/messages 2>/dev/null || tail -200 /var/log/syslog 2>/dev/null") == ["/var/log/messages", "/var/log/syslog"]
    assert commands_from_header("rpm -qa --queryformat '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\\n' 2>/dev/null | sort") == ["rpm"]
    assert commands_from_header("cat /etc/redhat-release 2>/dev/null || echo N/A") == ["/etc/redhat-release"]
    assert commands_from_header("uptime; cat /proc/uptime") == ["uptime", "/proc/uptime"]


def test_matcher_examples():
    """매처 자기시험 — 명령 위치만 호출로 본다 · Windows 는 식별자 단어 묶음으로 본다."""
    code = 'case "$dev" in lo|docker*|br-*) continue;; esac\nif command -v nvme >/dev/null 2>&1; then\n  x=$(systemd-detect-virt 2>/dev/null)\nfi\nawk \'{print $1}\' /proc/uptime\n/usr/sbin/dmidecode -t system\n'
    assert not _found_exe("docker", code)
    assert _found_exe("nvme", code)
    assert _found_exe("systemd-detect-virt", code)
    assert _found_exe("dmidecode", code)
    assert not _found_exe("uptime", code)           # /proc/uptime 는 파일 읽기 — 명령 uptime 호출이 아니다
    assert _found_path("/proc/uptime", code)
    assert not _found_path("/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq", "cat /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq")
    assert _found_path("/proc/net/bonding/*", "for pf in /proc/net/bonding/*; do")
    win = "Get-CimInstance Win32_ComputerSystem | Select-Object Model\n$env:COMPUTERNAME\nGet-TimeZone\nGet-LocalUser\nGet-DnsClientServerAddress\n[Environment]::OSVersion"
    assert _windows_consumed("computer_system", win)
    assert _windows_consumed("timezone", win)
    assert _windows_consumed("local_users", win)
    assert _windows_consumed("dns_client", win)
    assert not _windows_consumed("env", win)
    assert not _windows_consumed("memory_module", win)
