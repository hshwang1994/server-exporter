"""Linux raw 수집 스크립트 실행 하네스 — tests/unit 공용 (pytest 수집 대상 아님).

test_linux_memory_parser / test_linux_storage_markers / test_linux_hba_ib_markers /
tests/e2e/test_linux_raw_scripts_shim 이 쓴다.

2026-10-03 (Plan §8-2): dmidecode 는 gather_system.yml 의 raw gather 에 주입되는 공유 DMI collector
(``_l_dmi_collector``)가 1회 실행하고, NIC driver map 줄은 gather_network.yml raw gather 첫머리가 낸다.
``dmi_collector_script()`` · ``shared_dmi_raw()`` · ``network_nic_block()`` 가 그 자리를 꺼낸다.

무엇을 재현하나
---------------
1. production YAML 의 ``ansible.builtin.raw`` 본문을 **그대로** 꺼낸다.
   Ansible 은 모듈 인자를 Jinja 로 한 번 렌더한다. 본문이 Jinja 문법(``{#`` 등)을 실수로 품으면
   원격에서 실행되기 전에 깨지므로 그것부터 확인한다.
2. 그 본문을 샌드박스에서 ``sh`` 로 실행한다. PATH 에는 shim 디렉터리와 허용 목록 도구의 래퍼만
   둔다. 호스트에 깔린 dmidecode / lsblk / sudo (Windows 의 sudo.exe 포함) 가 섞이지 않는다.
3. 같은 파일의 태스크를 **파일에 적힌 순서대로** 흉내 낸다. raw 태스크는 2의 결과를 register 에
   넣고, set_fact 는 jinja2 NativeEnvironment(ansible.cfg ``jinja2_native``)로 렌더하며,
   block 이 예외로 끝나면 Ansible 처럼 rescue 를 돈다.

왜 실제 ansible-core Templar 가 아닌가
--------------------------------------
tests/unit 의 여러 모듈이 import 시점에 ``sys.modules["ansible"]`` 를 stub 으로 채운다.
수집 순서에 따라 실제 Templar import 가 깨지므로 unit 계층은 순수 jinja2 로 렌더한다.
대신 ansible-core 2.19+ 처럼 **정의되지 않은 값을 타입 테스트에 넘기면 죽게** 만들어 둔다.
"""
from __future__ import annotations

import atexit
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jinja2
import pytest
import yaml
from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment

REPO = Path(__file__).resolve().parents[2]
LINUX_TASKS = REPO / "os-gather" / "tasks" / "linux"

for _p in (str(REPO), str(REPO / "filter_plugins")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from identity_normalizer import normalize_wwn  # noqa: E402
from jedec_mapper import jedec_to_vendor  # noqa: E402

SH = shutil.which("sh")
AWK = shutil.which("awk")
CYGPATH = shutil.which("cygpath") if os.name == "nt" else None

# raw 스크립트가 쓰는 일반 도구.
BASE_TOOLS = ("awk", "grep", "head", "tail", "tr", "cut", "sed", "cat", "rm", "mktemp",
              "readlink", "basename", "dirname", "ls", "wc")
# 테스트가 shim 으로 넣을 때만 존재해야 하는 명령 (호스트 것이 섞이면 결과가 호스트에 따라 바뀐다).
CONTROLLED = ("dmidecode", "sudo", "lsblk", "udevadm", "findmnt", "lspci", "df", "timeout",
              "multipath")


def require_posix_shell() -> None:
    if not SH:
        pytest.skip("sh 가 없다 — raw 스크립트를 실행할 수 없다 (Windows 는 Git for Windows 의 sh 필요)")
    if not AWK:
        pytest.skip("awk 가 없다 — raw 스크립트의 awk 파서를 실행할 수 없다")


@functools.lru_cache(maxsize=1)
def _tool_paths() -> dict[str, str]:
    """원래 환경의 sh 가 보는 도구 실경로 (래퍼가 exec 할 대상)."""
    probe = "".join(f'printf "%s=%s\\n" {t} "$(command -v {t})"\n' for t in BASE_TOOLS)
    res = subprocess.run([SH, "-s"], input=probe.encode(), capture_output=True, timeout=120)
    found: dict[str, str] = {}
    for line in res.stdout.decode("utf-8", "replace").splitlines():
        key, _, value = line.partition("=")
        if value.startswith("/"):
            found[key] = value
    return found


@functools.lru_cache(maxsize=None)
def _direct_tool_dirs(hide: tuple[str, ...]) -> tuple[str, ...] | None:
    """도구 실경로 디렉터리를 PATH 에 바로 써도 되면 그 목록, 아니면 None.

    ``hide`` 의 명령이 그 디렉터리에 하나라도 있으면(예: Linux 의 /usr/bin/lsblk) 래퍼 디렉터리를
    써야 한다. Windows(Git Bash)는 래퍼 exec 가 프로세스를 하나 더 만들어 느리므로 가능하면 피한다.
    """
    dirs = tuple(sorted({real.rsplit("/", 1)[0] for real in _tool_paths().values()}))
    if not dirs:
        return None
    probe = "".join(f'[ -x "{d}/{c}" ] && echo "{d}/{c}"\n' for d in dirs for c in hide) + "true\n"
    res = subprocess.run([SH, "-s"], input=probe.encode(), capture_output=True, timeout=120)
    return None if res.stdout.strip() else dirs


@functools.lru_cache(maxsize=1)
def _cygdrive_prefix() -> str:
    """Windows 드라이브가 sh 에서 보이는 접두 (Git Bash 는 ``/`` → ``/c/...``). 세션당 1회만 묻는다."""
    if CYGPATH:
        res = subprocess.run([CYGPATH, "-u", "C:\\"], capture_output=True, text=True, timeout=60)
        out = res.stdout.strip()
        idx = out.lower().rfind("/c")
        if res.returncode == 0 and idx >= 0:
            return out[:idx + 1]
    return "/"


def sh_path(path: Path | str) -> str:
    """호스트 경로 → sh 경로 (Windows 는 /c/... — PATH 의 ':' 구분과 충돌하지 않게)."""
    text = str(path)
    if os.name != "nt":
        return text
    drive, rest = os.path.splitdrive(text)
    return _cygdrive_prefix() + drive.rstrip(":").lower() + rest.replace("\\", "/")


@functools.lru_cache(maxsize=1)
def _session_tools() -> Path:
    """허용 목록 도구의 래퍼 디렉터리 (세션당 1개 — 샌드박스마다 만들면 Windows 에서 느리다)."""
    base = Path(tempfile.mkdtemp(prefix="se_raw_tools_"))
    atexit.register(shutil.rmtree, base, True)
    for name, real in _tool_paths().items():
        Sandbox.write(base / name, f"#!/bin/sh\nexec '{real}' \"$@\"\n")
    return base


@dataclass
class RunResult:
    rc: int
    stdout: str
    stderr: str

    @property
    def lines(self) -> list[str]:
        return self.stdout.splitlines()

    def marker(self, key: str) -> str | None:
        """``KEY=value`` 줄의 값 (마지막 것). 없으면 None."""
        value = None
        prefix = key + "="
        for line in self.lines:
            if line.startswith(prefix):
                value = line[len(prefix):]
        return value

    def rows(self, prefix: str) -> list[list[str]]:
        """``PREFIX|a|b`` 줄을 필드 목록으로."""
        return [line.split("|")[1:] for line in self.lines if line.startswith(prefix + "|")]

    def register(self) -> dict[str, Any]:
        """Ansible raw 모듈이 register 에 남기는 모양."""
        return {"rc": self.rc, "stdout": self.stdout, "stdout_lines": self.lines,
                "stderr": self.stderr, "stderr_lines": self.stderr.splitlines()}


class Sandbox:
    """shim / 도구 / TMPDIR 를 가진 실행 공간.

    ``hide`` — shim 으로 넣지 않는 한 **보이면 안 되는** 명령. 기본은 CONTROLLED 전부.
    """

    def __init__(self, base: Path, hide: tuple[str, ...] = CONTROLLED):
        require_posix_shell()
        tools = _tool_paths()
        missing = [t for t in BASE_TOOLS if t not in tools]
        if missing:
            pytest.skip(f"raw 스크립트 실행에 필요한 도구가 없다: {missing}")
        self.root = base
        self.shim = base / "shim"
        self.tmp = base / "tmp"
        self.data = base / "data"
        for d in (self.shim, self.tmp, self.data):
            d.mkdir(parents=True, exist_ok=True)
        direct = _direct_tool_dirs(tuple(sorted(hide)))
        self.tool_path = ":".join(direct) if direct else self.p(_session_tools())

    @staticmethod
    def p(path: Path) -> str:
        """호스트 경로 → sh 경로."""
        return sh_path(path)

    @staticmethod
    def write(path: Path, text: str, executable: bool = True) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        if executable:
            path.chmod(0o755)
        return path

    def data_file(self, name: str, text: str) -> str:
        return self.p(self.write(self.data / name, text, executable=False))

    def shim_cmd(self, name: str, body: str) -> None:
        self.write(self.shim / name, "#!/bin/sh\n" + body)

    def leftover_tmp(self) -> list[str]:
        return sorted(p.name for p in self.tmp.iterdir())

    def run(self, script: str, env: dict[str, str] | None = None) -> RunResult:
        prologue = (f"PATH='{self.p(self.shim)}:{self.tool_path}'; export PATH\n"
                    f"TMPDIR='{self.p(self.tmp)}'; export TMPDIR\n")
        path = self.write(self.root / "script.sh", prologue + script)
        run_env = {k: v for k, v in os.environ.items() if not k.startswith("SHIM_")}
        run_env.update(env or {})
        res = subprocess.run([SH, path.as_posix()], capture_output=True, timeout=180, env=run_env)
        return RunResult(res.returncode, res.stdout.decode("utf-8", "replace"),
                         res.stderr.decode("utf-8", "replace"))


# ---------------------------------------------------------------------------
# production YAML 읽기
# ---------------------------------------------------------------------------
def load_tasks(yml: Path) -> list[dict[str, Any]]:
    return yaml.safe_load(yml.read_text(encoding="utf-8"))


def iter_tasks(node: Any):
    if isinstance(node, list):
        for item in node:
            yield from iter_tasks(item)
    elif isinstance(node, dict):
        yield node
        for key in ("block", "rescue", "always"):
            if key in node:
                yield from iter_tasks(node[key])


def raw_script(yml: Path, name_part: str) -> str:
    """raw 태스크 본문. Ansible 이 인자를 렌더해도 본문이 그대로인지(= Jinja 구문 없음) 확인한다."""
    for task in iter_tasks(load_tasks(yml)):
        if name_part in (task.get("name") or "") and "ansible.builtin.raw" in task:
            text = task["ansible.builtin.raw"]
            rendered = jinja2.Environment(keep_trailing_newline=True).from_string(text).render()
            assert rendered == text, f"{yml.name}:{name_part} raw 본문에 Jinja 구문이 섞였다"
            return text
    raise AssertionError(f"{yml.name} 에서 raw 태스크를 찾지 못함: {name_part!r}")


def set_fact_args(yml: Path, name_part: str) -> dict[str, Any]:
    for task in iter_tasks(load_tasks(yml)):
        if name_part in (task.get("name") or "") and "ansible.builtin.set_fact" in task:
            return task["ansible.builtin.set_fact"]
    raise AssertionError(f"{yml.name} 에서 set_fact 를 찾지 못함: {name_part!r}")


SYSTEM_YML = LINUX_TASKS / "gather_system.yml"
NETWORK_YML = LINUX_TASKS / "gather_network.yml"


def assert_jinja_free(text: str, label: str) -> None:
    """Ansible 이 한 번 렌더해도 글자 그대로인지 (= Jinja 구문이 섞이지 않았는지)."""
    rendered = jinja2.Environment(keep_trailing_newline=True).from_string(text).render()
    assert rendered == text, f"{label} 본문에 Jinja 구문이 섞였다"


def dmi_collector_script() -> str:
    """gather_system.yml 의 공유 DMI collector 본문 (set_fact ``_l_dmi_collector``).

    raw gather(become) 가 ``{{ _l_dmi_collector }}`` 로 주입한다 — 주입 자리가 있는지도 확인한다.
    """
    text = set_fact_args(SYSTEM_YML, "define shared dmi collector")["_l_dmi_collector"]
    assert_jinja_free(text, "gather_system.yml:_l_dmi_collector")
    raw = next(t for t in iter_tasks(load_tasks(SYSTEM_YML))
               if "raw gather" in (t.get("name") or "") and "ansible.builtin.raw" in t)
    assert "{{ _l_dmi_collector }}" in raw["ansible.builtin.raw"], "raw gather 에 DMI collector 주입이 없다"
    assert raw.get("become") is True, "DMI collector 를 싣는 raw gather 는 become 이어야 한다"
    return text


def shared_dmi_raw(system_register: dict[str, Any]) -> dict[str, Any]:
    """gather_system.yml 의 ``_l_dmi_raw`` set_fact 를 그대로 렌더한다 (입력 = raw gather register)."""
    args = set_fact_args(SYSTEM_YML, "shared dmi raw")
    return render_tree(ansible_env(), args["_l_dmi_raw"], {"_l_raw_sys_result": system_register})


def collector_output(mem_lines: list[str], proc_lines: list[str] = ()) -> str:
    """공유 DMI collector 출력 모양 (구간 marker 로 감싼다) — Jinja 판정만 보는 테스트용."""
    lines = ["DMI_MEM_BEGIN", *mem_lines, "DMI_MEM_END", "DMI_PROC_BEGIN", *proc_lines, "DMI_PROC_END"]
    return "".join(line + "\n" for line in lines)


def network_nic_block() -> str:
    """gather_network.yml raw gather 첫머리의 NIC driver map 하위 셸 블록 (gather_hba_ib 가 읽는 NIC| 줄)."""
    raw = next(t for t in iter_tasks(load_tasks(NETWORK_YML))
               if "raw gather" in (t.get("name") or "") and "ansible.builtin.raw" in t)["ansible.builtin.raw"]
    lines = raw.splitlines(keepends=True)
    start = lines.index("(\n")
    end = lines.index(")\n", start)
    block = "".join(lines[start:end + 1])
    assert_jinja_free(block, "gather_network.yml NIC driver map 블록")
    assert 'echo "NIC|' in block
    # LANG=C 보다 앞 (종전 별도 raw 처럼 세션 locale 의 glob 순서를 쓴다)
    assert raw.index(block) < raw.index("export LANG=C LC_ALL=C")
    return block


# ---------------------------------------------------------------------------
# Ansible 렌더 대역 (jinja2_native)
# ---------------------------------------------------------------------------
def _regex_replace(value: Any = "", pattern: str = "", replacement: str = "",
                   ignorecase: bool = False, multiline: bool = False, count: int = 0,
                   mandatory_count: int = 0) -> str:
    flags = (re.I if ignorecase else 0) | (re.M if multiline else 0)
    return re.sub(pattern, replacement, str(value), count=count, flags=flags)


def _split(value: Any, sep: str | None = None, maxsplit: int = -1) -> list[str]:
    return str(value).split(sep, maxsplit)


def _ansible_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "on", "1")
    return bool(value)


def _strict_test(name: str, func):
    def _test(value, *args, **kwargs):
        if isinstance(value, jinja2.Undefined):
            raise jinja2.UndefinedError(
                f"ansible-core 2.19+ 는 정의되지 않은 값을 '{name}' 테스트에 넘기면 실패한다")
        return func(value, *args, **kwargs)
    return _test


def ansible_env() -> NativeEnvironment:
    env = NativeEnvironment(undefined=StrictUndefined)
    env.filters.update({
        "regex_replace": _regex_replace,
        "split": _split,
        "from_json": json.loads,          # 형식 오류면 예외 — Ansible 과 같다
        "bool": _ansible_bool,
        "jedec_to_vendor": jedec_to_vendor,
        "normalize_wwn": normalize_wwn,
    })
    env.tests["search"] = lambda value, pattern: re.search(pattern, str(value)) is not None
    env.tests["match"] = lambda value, pattern: re.match(pattern, str(value)) is not None
    for name in ("mapping", "sequence", "string", "number", "iterable", "none", "integer"):
        if name in env.tests:
            env.tests[name] = _strict_test(name, env.tests[name])
    return env


def render_tree(env: NativeEnvironment, node: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(node, str):
        if "{{" in node or "{%" in node:
            return env.from_string(node).render(**ctx)
        return node
    if isinstance(node, dict):
        return {k: render_tree(env, v, ctx) for k, v in node.items()}
    if isinstance(node, list):
        return [render_tree(env, v, ctx) for v in node]
    return node


@dataclass
class TaskRun:
    ctx: dict[str, Any]
    rescued: list[tuple[str, str]] = field(default_factory=list)


def run_task_file(yml: Path, registers: dict[str, dict[str, Any]],
                  ctx: dict[str, Any] | None = None) -> TaskRun:
    """태스크 파일을 적힌 순서대로 흉내 낸다 (raw = 주어진 register, include_tasks = 건너뜀)."""
    env = ansible_env()
    run = TaskRun(ctx=dict(ctx or {}))
    _run_list(env, load_tasks(yml), registers, run)
    return run


def _when_ok(env: NativeEnvironment, cond: Any, ctx: dict[str, Any]) -> bool:
    if cond is None:
        return True
    for item in (cond if isinstance(cond, list) else [cond]):
        if isinstance(item, bool):
            value = item
        else:
            value = env.from_string("{{ " + str(item) + " }}").render(**ctx)
        assert isinstance(value, bool), f"when 결과가 bool 이 아니다 (ansible-core 2.19+ 는 실패): {item!r}"
        if not value:
            return False
    return True


def _run_list(env, tasks, registers, run: TaskRun) -> None:
    for task in tasks:
        if not _when_ok(env, task.get("when"), run.ctx):
            continue
        if "block" in task:
            try:
                _run_list(env, task["block"], registers, run)
            except Exception as exc:  # noqa: BLE001 - Ansible block 은 어떤 실패든 rescue 로 보낸다
                if "rescue" not in task:
                    raise
                run.rescued.append((task.get("name") or "", f"{type(exc).__name__}: {exc}"))
                run.ctx["ansible_failed_result"] = {"msg": str(exc)}
                _run_list(env, task["rescue"], registers, run)
            if "always" in task:
                _run_list(env, task["always"], registers, run)
        elif "ansible.builtin.raw" in task:
            reg = task.get("register")
            if reg:
                assert reg in registers, f"raw 결과가 주어지지 않았다: {reg}"
                run.ctx[reg] = registers[reg]
        elif "ansible.builtin.set_fact" in task:
            args = task["ansible.builtin.set_fact"]
            run.ctx.update({k: render_tree(env, v, run.ctx) for k, v in args.items()})
        elif "ansible.builtin.include_tasks" in task:
            continue                      # merge_fragment — 이 하네스의 대상 밖
        else:
            raise AssertionError(f"하네스가 모르는 태스크 종류: {task.get('name')!r}")


# ---------------------------------------------------------------------------
# 사용자 문장 품질 (tests/e2e 계약과 같은 기준)
# ---------------------------------------------------------------------------
def assert_user_sentence(message: str, label: str) -> None:
    from tests.e2e.test_failure_reason_contract import FR_CATALOG, _assert_grid_ready  # noqa: PLC0415
    from tests.e2e.test_section_message_contract import _BANNED_TOKENS  # noqa: PLC0415

    _assert_grid_ready(message, label)
    for token in _BANNED_TOKENS:
        assert token not in message, f"[{label}] 내부 어휘 {token!r} 노출: {message!r}"
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", message), f"[{label}] IP 노출: {message!r}"
    assert ".." not in message and "[task:" not in message, f"[{label}] {message!r}"
    for claim in ("정상 수집", "정상적으로 수집", "수집은 완료", "수집을 완료", "완료했습니다"):
        assert claim not in message, f"[{label}] 다른 부분의 성공을 단언한다: {message!r}"
    catalog = {text for entry in FR_CATALOG.values() for text in entry.values()}
    assert message not in catalog, f"[{label}] 전체 실패 대표 문장을 섹션 오류에 썼다: {message!r}"
