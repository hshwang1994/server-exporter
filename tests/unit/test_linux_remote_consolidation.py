"""Plan §8-2 (2026-10-03) — Linux 원격 실행 통합의 출력 불변 회귀.

무엇을 고정하나
---------------
1. users: Python / raw 두 경로가 같은 raw 1회를 쓴다. 그 결과가 **종전 Python 경로**(getent 모듈 2회 +
   사용자별 그룹 전체 순회)와 같다 — 독립 oracle(모듈 분해 규칙 + U×G 순회)로 실캡처 6대를 대조한다.
   gid → 이름 사전으로 바꾼 주 그룹 판정은 같은 gid 가 여럿일 때도 종전처럼 **뒤에 나온** 그룹이다.
2. system: 쓰이지 않던 DMI precheck(`test -r`) 가 없고, DMI direct-read 는 setup 값도 raw sysfs 값도
   없을 때만 돈다. 건너뛴 경우의 식별자 · 진단은 direct-read 가 같은 값을 읽었을 때와 같다.
3. system raw 출력에 공유 DMI collector 줄이 붙어도 system 파서(_l_raw_sys) 값은 그대로이고,
   ``_l_dmi_raw`` 는 DMI 구간만 담는다.
4. network: raw 첫머리에 붙은 NIC driver map 줄(``NIC|``)은 network 파서가 읽지 않는다 —
   실장비 raw stdout fixture 로 렌더 결과가 같음을 확인한다.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.unit.linux_raw_harness import (  # noqa: E402
    LINUX_TASKS,
    REPO,
    RunResult,
    ansible_env,
    iter_tasks,
    load_tasks,
    render_tree,
    run_task_file,
    set_fact_args,
    shared_dmi_raw,
)

USERS_YML = LINUX_TASKS / "gather_users.yml"
SYSTEM_YML = LINUX_TASKS / "gather_system.yml"
DIAG_YML = LINUX_TASKS / "build_identifier_diagnostics.yml"
REF_HOSTS = sorted(p.parent for p in (REPO / "tests" / "reference" / "os").glob("*/*/cmd_passwd_users.txt"))


def _capture(path: Path) -> str:
    """수집 도구 머리말(# …) · __REDACTED__ · stderr 꼬리를 뺀 원래 출력."""
    out = []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ln.startswith("# === stderr ==="):
            break
        if ln.startswith("#") or ln.strip() in ("", "__REDACTED__"):
            continue
        out.append(ln)
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════════════════
# 1. users
# ═══════════════════════════════════════════════════════════════════════════
def _getent_module(text: str) -> dict:
    """ansible.builtin.getent 의 분해 규칙 (중복 키는 목록의 목록) — 종전 Python 경로 입력."""
    results, seen = {}, {}
    for line in text.splitlines():
        record = line.split(":")
        if record[0] in seen:
            if seen[record[0]] == 1:
                results[record[0]] = [results[record[0]]]
            results[record[0]].append(record[1:])
            seen[record[0]] += 1
        else:
            results[record[0]] = record[1:]
            seen[record[0]] = 1
    return results


def old_python_users(passwd: str, group: str, last: dict) -> list[dict]:
    """종전 Python 경로 판정식의 독립 구현 (주 그룹 = 그룹 전체 순회, 마지막 일치)."""
    gp, gg = _getent_module(passwd), _getent_module(group)
    ug: dict[str, list[str]] = {}
    for gname, gdata in gg.items():
        for member in (gdata[2] if len(gdata) > 2 else "").split(","):
            if member:
                ug.setdefault(member, []).append(gname)
    users = []
    for uname, udata in gp.items():
        uid, gid, home = int(udata[1]), int(udata[2]), udata[4]
        is_sys = (uid < 1000 and uid != 0) or uname in ("nobody", "nfsnobody") \
            or home.startswith("/var/") or home == "/nonexistent"
        if is_sys and uname != "root":
            continue
        primary = ""
        for gn, gd in gg.items():
            if int(gd[1]) == gid:
                primary = gn
        groups = list(ug.get(uname, []))
        if primary and primary not in groups:
            groups = [primary] + groups
        users.append({"name": uname, "uid": udata[1], "groups": groups, "home": home or None,
                      "last_access_time": last.get(uname)})
    return sorted(users, key=lambda u: int(u["uid"]))


def users_raw_stdout(passwd: str, group: str, last: dict) -> str:
    """raw 스크립트 출력 모양 (PASSWD / GROUP / LASTLOG marker)."""
    lines = ["PASSWD_START", *passwd.splitlines(), "PASSWD_END", "GROUP_START", *group.splitlines(), "GROUP_END",
             "LASTLOG_START", *[f"{u}:{v if v is not None else 'null'}" for u, v in last.items()], "LASTLOG_END"]
    return "".join(ln + "\n" for ln in lines)


def render_users(stdout: str) -> dict:
    run = run_task_file(USERS_YML, {"_l_users_raw_result": RunResult(0, stdout, "").register()})
    assert not run.rescued
    return run.ctx


def test_users_file_runs_one_raw_for_both_modes():
    tasks = list(iter_tasks(load_tasks(USERS_YML)))
    actions = [k for t in tasks for k in t if k.startswith("ansible.builtin.")]
    assert actions.count("ansible.builtin.raw") == 1
    assert not {"ansible.builtin.getent", "ansible.builtin.shell", "ansible.builtin.command"} & set(actions)
    assert not any("_l_python_mode" in str(t.get("when", "")) for t in tasks), "모드별 분기가 다시 생겼다"


def test_users_script_reads_each_database_once():
    raw = next(t["ansible.builtin.raw"] for t in iter_tasks(load_tasks(USERS_YML)) if "ansible.builtin.raw" in t)
    assert len(re.findall(r"\bgetent passwd\b", raw)) == 1
    assert len(re.findall(r"\bgetent group\b", raw)) == 1


@pytest.mark.parametrize("host", REF_HOSTS, ids=[h.parts[-2] for h in REF_HOSTS])
def test_reference_users_match_old_python_path(host):
    passwd = _capture(host / "cmd_passwd_users.txt")
    group = _capture(host / "cmd_groups.txt")
    last = {}                      # raw 스크립트는 root 와 uid >= 1000 에 대해서만 last login 을 낸다
    for ln in passwd.splitlines():
        name, _, uid = ln.split(":")[:3]
        if name == "root" or int(uid) >= 1000:
            last[name] = "2026-04-28T06:44:00Z" if name == "root" else None
    ctx = render_users(users_raw_stdout(passwd, group, last))
    expected = old_python_users(passwd, group, last)
    assert expected, "실캡처에 root 가 없다"
    assert ctx["_data_fragment"]["users"] == expected
    assert ctx["_sections_collected_fragment"] == ["users"]
    assert ctx["_sections_unsupported_fragment"] == []


def test_primary_group_with_duplicate_gid_is_the_last_one():
    passwd = "root:x:0:0:root:/root:/bin/bash\nalice:x:1001:1001::/home/alice:/bin/bash\nbob:x:1002:2000::/home/bob:/bin/sh"
    group = "root:x:0:\nstaff:x:1001:\ndevs:x:1001:alice\nfirst:x:2000:\nsecond:x:2000:\nwheel:x:10:alice,bob"
    last = {"root": None, "alice": "2026-01-01T00:00:00Z", "bob": None}
    users = render_users(users_raw_stdout(passwd, group, last))["_data_fragment"]["users"]
    assert users == old_python_users(passwd, group, last)
    by = {u["name"]: u for u in users}
    assert by["alice"]["groups"] == ["devs", "wheel"]          # gid 1001 → 뒤에 나온 devs
    assert by["bob"]["groups"] == ["second", "wheel"]          # gid 2000 → 뒤에 나온 second


def test_users_unsupported_when_getent_is_missing():
    ctx = render_users(users_raw_stdout("", "", {}))
    assert ctx["_data_fragment"]["users"] == []
    assert ctx["_sections_collected_fragment"] == []
    assert ctx["_sections_unsupported_fragment"] == ["users"]
    assert ctx["_sections_failed_fragment"] == [] and ctx["_errors_fragment"] == []


# ═══════════════════════════════════════════════════════════════════════════
# 2. system — N5 · direct-read 조건
# ═══════════════════════════════════════════════════════════════════════════
def test_dead_dmi_precheck_is_gone_and_nothing_reads_it():
    tasks = list(iter_tasks(load_tasks(SYSTEM_YML)))
    assert not [t for t in tasks if "ansible.builtin.command" in t and str(t["ansible.builtin.command"]).startswith("test ")]
    for root in ("os-gather", "common", "callback_plugins", "filter_plugins"):
        for path in (REPO / root).rglob("*"):
            if path.suffix in (".yml", ".yaml", ".py", ".j2"):
                text = path.read_text(encoding="utf-8", errors="replace")
                assert "_l_dmi_serial_access" not in text and "_l_dmi_uuid_access" not in text, path


def _direct_read_tasks():
    block = next(t for t in iter_tasks(load_tasks(SYSTEM_YML)) if t.get("name") == "linux | system | DMI direct-read fallback")
    return block, {t["name"].rsplit(" ", 1)[-1]: t for t in block["block"]}


def _cond(expr, ctx) -> bool:
    value = ansible_env().from_string("{{ " + str(expr).strip() + " }}").render(**ctx)
    assert isinstance(value, bool)
    return value


@pytest.mark.parametrize("setup,raw,runs", [
    (None, None, True),          # setup 도 raw sysfs 도 없음 → direct-read
    (None, "SN-RAW", False),     # raw gather(become) 가 이미 읽음 → 건너뜀 (§8-2)
    ("SN-SETUP", None, False),   # setup 이 줬음 → 종전처럼 건너뜀
    ("SN-SETUP", "SN-RAW", False),
], ids=["both-missing", "raw-only", "setup-only", "both"])
def test_direct_read_runs_only_when_setup_and_raw_sysfs_both_miss(setup, raw, runs):
    block, tasks = _direct_read_tasks()
    for field in ("serial", "uuid"):
        # 다른 식별자는 setup 값이 있는 상태 — 이 식별자의 조건만 block / 태스크 판정을 가른다
        ctx = {"_l_python_mode": "python_ok", "_l_serial_from_setup": "x", "_l_uuid_from_setup": "x",
               "_l_raw_serial": "x", "_l_raw_uuid": "x"}
        ctx.update({f"_l_{field}_from_setup": setup, f"_l_raw_{field}": raw})
        assert _cond(block["when"], ctx) is runs, field
        assert _cond(tasks[field]["when"], ctx) is runs, field
    raw_mode = {"_l_python_mode": "raw_forced", "_l_serial_from_setup": None, "_l_uuid_from_setup": None,
                "_l_raw_serial": None, "_l_raw_uuid": None}
    assert _cond(block["when"], raw_mode) is False


def _resolve(ctx: dict) -> dict:
    env = ansible_env()
    ctx = dict(ctx)
    args = set_fact_args(SYSTEM_YML, "resolve identifiers")
    ctx.update({k: render_tree(env, v, ctx) for k, v in args.items()})
    diag = load_tasks(DIAG_YML)[0]
    dctx = dict(ctx)
    dctx.update(diag.get("vars") or {})
    ctx["_l_id_diagnostics"] = render_tree(env, diag["ansible.builtin.set_fact"]["_l_id_diagnostics"], dctx)
    return ctx


SKIPPED = {"changed": False, "skipped": True, "skip_reason": "Conditional result was False"}


def test_skipped_direct_read_resolves_like_a_successful_one():
    """raw 값이 있으면 건너뛴다 — 종전(direct-read 가 같은 파일을 같은 권한으로 읽어 성공)과 결과가 같다."""
    base = {"_l_python_mode": "python_ok", "_l_serial_from_setup": None, "_l_uuid_from_setup": None,
            "_l_raw_serial": "GSBPK54", "_l_raw_uuid": "4c4c4544-0053-4210-8050-c7c04f4b3534"}
    old = _resolve({**base, "_l_dmi_serial_direct": {"rc": 0, "stdout": "GSBPK54"},
                    "_l_dmi_uuid_direct": {"rc": 0, "stdout": "4c4c4544-0053-4210-8050-c7c04f4b3534"}})
    new = _resolve({**base, "_l_dmi_serial_direct": SKIPPED, "_l_dmi_uuid_direct": SKIPPED})
    for key in ("_l_serial_val", "_l_uuid_val", "_l_id_diagnostics"):
        assert new[key] == old[key], key
    assert new["_l_serial_val"] == "GSBPK54" and new["_l_id_diagnostics"] == []


# ═══════════════════════════════════════════════════════════════════════════
# 3. system raw 출력 + 공유 DMI collector 줄
# ═══════════════════════════════════════════════════════════════════════════
SYSTEM_LINES = ["OS_ID=ubuntu", "OS_ID_LIKE=debian", "OS_VERSION=24.04", "OS_PRETTY=Ubuntu 24.04.3 LTS",
                "KERNEL=6.8.0-88-generic", "ARCH=x86_64", "NODENAME=r760-6", "DOMAIN=", "UPTIME=12275793",
                "SELINUX=", "SDV=none", "DMI_PRODUCT_SERIAL=GSBPK54",
                "DMI_PRODUCT_UUID=4c4c4544-0053-4210-8050-c7c04f4b3534", "DMI_SYS_VENDOR=Dell Inc.",
                "DMI_PRODUCT_NAME=PowerEdge R760", "DMI_BIOS_VERSION=2.3.5", "DMI_BIOS_DATE=09/10/2024"]
DMI_LINES = ["DMI_MEM_BEGIN", "MEM_TOTAL_KB=131481148", "MEM_AVAIL_KB=120000000", "DMIDECODE=present",
             "DMIDECODE_RC=0", "DMIDECODE_ERR=", "DMIDECODE_OK=yes", "MEM_PHYS_MB=16384",
             "SLOT|16384|DDR5|4400|80AD000080AD|HMCG78AGBRA190N|4=6FB6227|A1", "MEM_DEVICE_RECORDS=1",
             "DMI_MEM_END", "DMI_PROC_BEGIN", "DMI_MAX_MHZ=4000", "DMI_CUR_MHZ=2400", "DMI_PROC_END"]


def _raw_sys(lines: list[str]) -> dict:
    reg = RunResult(0, "".join(ln + "\n" for ln in lines), "").register()
    args = set_fact_args(SYSTEM_YML, "parse raw results")
    # LX-F01: 비특권 · 특권 두 register — 같은 줄을 둘 다에 주면 종전(한 register)과 같은 사전이다
    return render_tree(ansible_env(), args["_l_raw_sys"], {"_l_raw_sys_result": reg, "_l_raw_priv_result": reg})


def test_system_parser_values_unchanged_by_collector_lines():
    alone, both = _raw_sys(SYSTEM_LINES), _raw_sys(SYSTEM_LINES + DMI_LINES)
    assert {k: both[k] for k in alone} == alone
    # 추가로 생기는 키는 DMI 구간의 marker 뿐 (system 이 읽는 키와 겹치지 않는다)
    assert set(both) - set(alone) <= {ln.split("=", 1)[0] for ln in DMI_LINES if "=" in ln}


def test_shared_dmi_raw_holds_only_the_collector_section():
    reg = RunResult(0, "".join(ln + "\n" for ln in SYSTEM_LINES + DMI_LINES), "").register()
    dmi = shared_dmi_raw(reg)
    assert dmi == {"stdout_lines": DMI_LINES, "rc": 0}


# ═══════════════════════════════════════════════════════════════════════════
# 4. network 파서는 NIC| 줄을 읽지 않는다
# ═══════════════════════════════════════════════════════════════════════════
def test_network_render_ignores_nic_driver_map_rows():
    from tests.unit.test_os_network_render import FIX, _render_raw_path  # noqa: PLC0415
    stdout = (FIX / "rhel810_rawpath_stdout.txt").read_text(encoding="utf-8")
    nic = "".join(f"NIC|{n}|{d}||{m}\n" for n, d, m in (("bond1", "", ""), ("ens161", "vmxnet3", "bond1"),
                                                         ("ens192", "vmxnet3", ""), ("ens193", "vmxnet3", "bond1"),
                                                         ("virbr0", "", "")))
    assert _render_raw_path(nic + stdout) == _render_raw_path(stdout)
