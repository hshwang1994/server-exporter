"""Plan §8-2 — Linux 원격 실행 수 게이트 + raw 스크립트 PATH shim 실행 (2026-10-03).

무엇을 고정하나
---------------
1. **원격 실행 수 (호스트당, 정상 경로)** — os-gather/site.yml Linux play 가 include 하는 순서대로
   태스크 파일을 걸어, 모드별로 실제로 원격에서 도는 태스크 수를 센다 (자격 probe 포함).

   ========================  =====  =====
   경로                       종전    지금
   ========================  =====  =====
   Python (python_ok)          18     10   (+DMI direct-read 0~2 → raw sysfs 도 실패했을 때만 +2)
   raw (python 없음 / 강제)    13      9
   ========================  =====  =====

   줄어든 자리: DMI precheck 2(N5) · DMI direct-read 상시 2 → 조건부 · dmidecode(memory + cpu) 2 →
   system raw 에 합침 · users getent 2 + shell 1 → raw 1 · hba_ib 3 → 1 (driver map 은 network raw).
2. **명령 실행 수** — 모든 Linux raw 스크립트를 한 호스트 순서대로 PATH shim 샌드박스에서 돌리면
   dmidecode 는 정확히 1회(``-t memory -t processor``), getent 는 데이터베이스마다 1회
   (``passwd`` 1 · ``group`` 1)다. shim 은 ``$0 $*`` 를 ``$SE_SHIM_LOG`` 에 남긴다.

판정 규칙
---------
- 원격 = 컨트롤러에서 끝나지 않는 액션 전부 (raw / setup / command / shell / getent …).
  set_fact / include_tasks / debug / fail / meta 는 원격이 아니다.
- ``when`` 은 block 조건까지 이어 붙여 jinja2 로 평가한다 (Ansible 과 같은 AND).
- 정상 경로 = 첫 자격으로 인증 성공 · setup 의 DMI 식별자 null(비루트 계정 — 흔한 경우) ·
  raw gather(become) 의 sysfs 식별자는 읽힘.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import jinja2
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.unit.linux_raw_harness import (  # noqa: E402
    LINUX_TASKS,
    REPO,
    Sandbox,
    ansible_env,
    sh_path,
)

SITE = REPO / "os-gather" / "site.yml"
TRY_ONE = REPO / "os-gather" / "tasks" / "try_one_credential.yml"
REF = REPO / "tests" / "reference" / "os" / "rhel-baremetal" / "10_100_64_96"

LOCAL_ACTIONS = {"set_fact", "include_tasks", "import_tasks", "debug", "fail", "assert", "meta",
                 "add_host", "include_vars", "set_stats"}
TASK_KEYS = {"name", "when", "register", "no_log", "changed_when", "failed_when", "timeout", "become",
             "vars", "args", "tags", "loop", "loop_control", "block", "rescue", "always", "delegate_to",
             "run_once", "ignore_errors", "until", "retries", "delay", "environment", "check_mode",
             "ignore_unreachable"}

BASE = {"_os_type": "linux", "_os_auth_ok": False, "_l_setup_ok": False,
        "_l_serial_from_setup": None, "_l_uuid_from_setup": None,
        "_l_raw_serial": "SN-RAW", "_l_raw_uuid": "4c4c4544-0000-0000-0000-000000000000"}
SCENARIOS = {
    # 정상: setup 의 DMI 식별자 null (비루트), raw sysfs 는 읽힘
    "python": {**BASE, "_l_python_mode": "python_ok", "_l_setup_ok": True},
    "raw": {**BASE, "_l_python_mode": "raw_forced"},
    # raw sysfs 식별자도 못 읽은 경우 — direct-read 2건이 그때만 돈다
    "python_no_sysfs_dmi": {**BASE, "_l_python_mode": "python_ok", "_l_setup_ok": True,
                            "_l_raw_serial": None, "_l_raw_uuid": None},
}
EXPECTED = {"python": 10, "raw": 9, "python_no_sysfs_dmi": 12}


# ---------------------------------------------------------------------------
# 태스크 파일 걷기
# ---------------------------------------------------------------------------
def _action(task: dict) -> str | None:
    acts = [k for k in task if k not in TASK_KEYS]
    return acts[0] if acts else None


def _include_file(task: dict) -> str | None:
    inc = task.get("ansible.builtin.include_tasks") or task.get("include_tasks")
    if isinstance(inc, dict):
        inc = inc.get("file")
    return inc


def _resolve(inc: str, base: Path) -> Path | None:
    text = (inc.replace("{{ playbook_dir }}", str(REPO / "os-gather"))
            .replace("{{ lookup('env','REPO_ROOT') }}", str(REPO)))
    if "{{" in text:
        return None
    path = Path(text)
    return path if path.is_absolute() else base / path


def _when_true(env, conds: list, ctx: dict) -> bool:
    for cond in conds:
        if isinstance(cond, bool):
            if not cond:
                return False
            continue
        value = env.from_string("{{ " + str(cond).strip() + " }}").render(**ctx)
        assert isinstance(value, bool), f"when 결과가 bool 이 아니다: {cond!r} → {value!r}"
        if not value:
            return False
    return True


def remote_tasks(path: Path, ctx: dict, inherited: tuple = ()) -> list[tuple[str, str, str]]:
    """(파일, 태스크 이름, 액션) — 시나리오에서 실제로 도는 원격 태스크 (include 따라감)."""
    env = ansible_env()
    out: list[tuple[str, str, str]] = []

    def walk(tasks, conds, base):
        for task in tasks or []:
            when = task.get("when")
            here = conds + tuple(when if isinstance(when, list) else ([when] if when is not None else []))
            if "block" in task:
                walk(task["block"], here, base)       # 정상 경로 — rescue 는 돌지 않는다
                continue
            inc = _include_file(task)
            if inc:
                target = _resolve(inc, base)
                if target is not None and target.exists():
                    walk(yaml.safe_load(target.read_text(encoding="utf-8")), here, target.parent)
                continue
            action = _action(task)
            if not action or action.split(".")[-1] in LOCAL_ACTIONS or task.get("delegate_to") == "localhost":
                continue                              # 컨트롤러에서 끝난다 — 대상 원격 실행이 아니다
            # 원격 태스크만 조건을 평가한다 (지역 set_fact 의 조건 변수는 이 게이트의 관심 밖)
            if not _when_true(env, list(here), ctx):
                continue
            assert "loop" not in task and "with_items" not in task, f"반복 원격 태스크: {task.get('name')}"
            out.append((str(path.name), task.get("name") or "", action.split(".")[-1]))

    walk(yaml.safe_load(path.read_text(encoding="utf-8")), tuple(inherited), path.parent)
    return out


def linux_play_sequence() -> list[Path]:
    """site.yml Linux play 의 본 block 이 include 하는 자격 probe · linux 태스크 파일 (순서 그대로)."""
    plays = yaml.safe_load(SITE.read_text(encoding="utf-8"))
    play = next(p for p in plays if p.get("hosts") == "_os_linux")
    main = next(t for t in play["tasks"] if "block" in t)
    seq: list[Path] = []
    for task in main["block"]:
        inc = _include_file(task)
        if not inc:
            continue
        if inc.endswith("try_credentials.yml"):
            seq.append(TRY_ONE)             # 정상 경로: 첫 후보에서 성공 → probe 1회
        elif "tasks/linux/" in inc:
            seq.append(REPO / "os-gather" / inc)
    return seq


def count_remote(scenario: str) -> list[tuple[str, str, str]]:
    ctx = SCENARIOS[scenario]
    out: list[tuple[str, str, str]] = []
    for path in linux_play_sequence():
        out += remote_tasks(path, ctx)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# 1. 원격 실행 수 게이트
# ═══════════════════════════════════════════════════════════════════════════
def test_linux_play_block_itself_runs_nothing_remote():
    """원격 실행은 include 한 파일 안에만 있다 — play block 에 직접 원격 태스크가 생기면 게이트가 놓친다."""
    plays = yaml.safe_load(SITE.read_text(encoding="utf-8"))
    play = next(p for p in plays if p.get("hosts") == "_os_linux")
    for top in play["tasks"]:
        for sec in ("block", "rescue", "always"):
            for task in top.get(sec) or []:
                action = _action(task)
                assert action and action.split(".")[-1] in LOCAL_ACTIONS, (sec, task.get("name"), action)


def test_play_sequence_covers_every_linux_task_file():
    names = [p.name for p in linux_play_sequence()]
    assert names == ["try_one_credential.yml", "preflight.yml", "gather_system.yml", "gather_cpu.yml",
                     "gather_memory.yml", "gather_storage.yml", "gather_network.yml", "gather_users.yml",
                     "gather_hba_ib.yml"]
    on_disk = {p.name for p in LINUX_TASKS.glob("*.yml")} - {"build_identifier_diagnostics.yml"}
    assert on_disk <= set(names), on_disk - set(names)


@pytest.mark.parametrize("scenario", list(EXPECTED))
def test_remote_execution_count_per_host(scenario):
    tasks = count_remote(scenario)
    detail = "\n".join(f"  {f}: {n} ({a})" for f, n, a in tasks)
    assert len(tasks) == EXPECTED[scenario], f"{scenario}: {len(tasks)}건\n{detail}"


def test_remote_execution_targets_of_plan_8_2():
    """Plan §8-2 목표 상한 — Python 12 · raw 9 (자격 probe 포함)."""
    assert len(count_remote("python")) <= 12
    assert len(count_remote("raw")) <= 9


def test_python_and_raw_paths_differ_only_by_setup():
    py = [t for t in count_remote("python")]
    raw = [t for t in count_remote("raw")]
    assert [t for t in py if t[2] != "setup"] == raw
    assert [t[2] for t in py if t not in raw] == ["setup"]


def test_dmidecode_and_getent_live_in_exactly_one_remote_task():
    """명령 단위로도 한 곳 — dmidecode 는 system raw(공유 DMI collector), getent 는 users raw."""
    from tests.unit.linux_raw_harness import iter_tasks, load_tasks, set_fact_args  # noqa: PLC0415
    collector = set_fact_args(LINUX_TASKS / "gather_system.yml", "define shared dmi collector")["_l_dmi_collector"]
    hits = {"dmidecode": [], "getent": []}
    for yml in sorted(LINUX_TASKS.glob("*.yml")):
        for task in iter_tasks(load_tasks(yml)):
            action = _action(task)
            if not action or action.split(".")[-1] in LOCAL_ACTIONS:
                continue
            body = str(task[action]).replace("{{ _l_dmi_collector }}", collector)
            body = re.sub(r"command -v \w+", "", body)      # 존재 확인(preflight 등)은 실행이 아니다
            for cmd in hits:
                if cmd in body or action.split(".")[-1] == cmd:
                    hits[cmd].append(f"{yml.name}:{task.get('name')}")
    assert hits["dmidecode"] == ["gather_system.yml:linux | system | raw gather (os-release/uname/hostname/dmi)"]
    assert hits["getent"] == ["gather_users.yml:linux | users | raw getent + last logins"]


# ═══════════════════════════════════════════════════════════════════════════
# 2. raw 스크립트 PATH shim 실행 — 명령 실행 수
# ═══════════════════════════════════════════════════════════════════════════
def _capture(name: str) -> str:
    """수집 도구 머리말(# command … / __REDACTED__ / stderr 꼬리)을 걷어낸 원래 stdout (LF)."""
    lines = (REF / name).read_text(encoding="utf-8", errors="replace").splitlines()
    i = 0
    while i < len(lines) and (lines[i].startswith("# ") or lines[i] in ("#", "__REDACTED__")):
        if lines[i].startswith("# dmidecode "):
            break
        i += 1
    body = []
    for line in lines[i:]:
        if line.startswith("# === stderr ==="):
            break
        if line.strip() != "__REDACTED__":
            body.append(line)
    return "\n".join(body).strip("\n") + "\n"


def _dmidecode_types(full: str, types: set[int]) -> str:
    """``dmidecode -t …`` 흉내 — 요청 타입 레코드를 표 순서대로 (실제 동작)."""
    out, keep = [], True
    for line in full.splitlines(keepends=True):
        m = re.match(r"Handle 0x[0-9A-Fa-f]+, DMI type (\d+),", line)
        if m:
            keep = int(m.group(1)) in types
        elif re.match(r"\d+ structures occupying|Table at ", line):
            continue
        if keep:
            out.append(line)
    return "".join(out)


def _render_raw(body: str, facts: dict) -> str:
    """Ansible 이 raw 인자를 렌더하는 것처럼 — collector 주입 · lookup('file'/'env')."""
    def lookup(kind, arg):
        if kind == "env":
            return {"REPO_ROOT": str(REPO)}.get(arg, "")
        if kind == "file":
            return Path(arg).read_text(encoding="utf-8").rstrip("\n")
        raise AssertionError(kind)
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    return env.from_string(body).render(lookup=lookup, **facts)


def host_raw_scripts() -> list[tuple[str, str]]:
    """한 호스트가 정상 경로에서 실행하는 raw 스크립트 전부 (play 순서, 렌더 후)."""
    from tests.unit.linux_raw_harness import iter_tasks, load_tasks, set_fact_args  # noqa: PLC0415
    facts = {
        "_l_dmi_collector": set_fact_args(LINUX_TASKS / "gather_system.yml",
                                          "define shared dmi collector")["_l_dmi_collector"],
        "_l_net_collector": set_fact_args(LINUX_TASKS / "gather_network.yml",
                                          "define topology collector")["_l_net_collector"],
    }
    out = []
    for path in linux_play_sequence():
        for task in iter_tasks(load_tasks(path)):
            if "ansible.builtin.raw" in task:
                out.append((f"{path.name}:{task.get('name')}", _render_raw(task["ansible.builtin.raw"], facts)))
    return out


SHIM_LOG = 'echo "$0 $*" >> "$SE_SHIM_LOG"\n'


@pytest.fixture
def shim_host(tmp_path: Path):
    """rhel-baremetal 실캡처 기반 shim (root 로 도는 정상 경로 — sudo 재시도 없음)."""
    sbx = Sandbox(tmp_path / "sbx")
    log = tmp_path / "shim.log"
    log.write_text("", encoding="utf-8")
    full = _capture("cmd_dmidecode_full.txt")
    combined = sbx.data_file("dmi_mem_proc.out", _dmidecode_types(full, {4, 5, 6, 16, 17}))
    passwd = sbx.data_file("passwd.out", _capture("cmd_passwd_users.txt"))
    group = sbx.data_file("group.out", _capture("cmd_groups.txt"))
    sbx.shim_cmd("dmidecode", SHIM_LOG + (
        'if [ "$*" = "-t memory -t processor" ]; then cat \'' + combined + '\'; exit 0; fi\n'
        'echo "unexpected dmidecode args: $*" >&2; exit 2\n'))
    sbx.shim_cmd("getent", SHIM_LOG + (
        'case "$1" in passwd) cat \'' + passwd + '\';; group) cat \'' + group + '\';; *) exit 2;; esac\n'))
    sbx.shim_cmd("sudo", SHIM_LOG + '[ "$1" = "-n" ] && shift\nexec "$@"\n')
    # DMI sysfs 는 root 가 읽을 수 있는 상태 (raw gather 의 sudo -n cat 분기를 타지 않는다)
    dmi_id = sbx.root / "sys" / "class" / "dmi" / "id"
    for name, value in (("product_serial", "SN-RAW"), ("product_uuid", "4c4c4544-0000"),
                        ("sys_vendor", "Dell Inc."), ("product_name", "PowerEdge R760"),
                        ("bios_version", "2.3.5"), ("bios_date", "08/01/2024")):
        sbx.write(dmi_id / name, value + "\n", executable=False)
    meminfo = sbx.data_file("meminfo", _capture("cmd_meminfo.txt"))
    # os-release 는 실캡처로 (없는 파일을 '.' 로 읽으면 POSIX sh 는 스크립트를 끝낸다 — Windows sh 대비)
    os_release = sbx.data_file("os-release", _capture("cmd_os_release.txt"))
    return sbx, log, {"/sys/class/dmi/id": sbx.p(dmi_id), "/proc/meminfo": f"'{meminfo}'",
                      "/etc/os-release": f"'{os_release}'"}


def run_host(sbx: Sandbox, log: Path, paths: dict[str, str]) -> list[list[str]]:
    for label, script in host_raw_scripts():
        for old, new in paths.items():
            script = script.replace(old, new)
        res = sbx.run(script, env={"SE_SHIM_LOG": sh_path(log)})
        assert res.rc == 0 or label.endswith("probe"), f"{label}: rc={res.rc}\n{res.stderr[-400:]}"
    return [line.split(" ", 1) for line in log.read_text(encoding="utf-8").splitlines()]


def _calls(entries: list[list[str]], cmd: str) -> list[str]:
    return [(e[1] if len(e) > 1 else "") for e in entries if e[0].rsplit("/", 1)[-1] == cmd]


def test_every_raw_script_runs_and_dmidecode_runs_once(shim_host):
    sbx, log, paths = shim_host
    entries = run_host(sbx, log, paths)
    assert _calls(entries, "dmidecode") == ["-t memory -t processor"]
    assert _calls(entries, "sudo") == []          # root 정상 경로 — 재시도 없음


def test_getent_runs_once_per_database(shim_host):
    sbx, log, paths = shim_host
    entries = run_host(sbx, log, paths)
    assert sorted(_calls(entries, "getent")) == ["group", "passwd"]


def test_host_runs_exactly_the_counted_raw_scripts():
    """shim 으로 도는 raw 스크립트 수 = 원격 실행 수 게이트의 raw 경로 (setup 제외 전부 raw)."""
    assert len(host_raw_scripts()) == EXPECTED["raw"]
    assert all(a == "raw" for _, _, a in count_remote("raw"))
