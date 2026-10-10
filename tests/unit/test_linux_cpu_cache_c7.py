"""Linux lscpu 캐시 — 합계와 인스턴스당 값을 util-linux 버전으로 가른다 (2026-10-10 C7).

공식 소스(util-linux sys-utils/lscpu.c, 확인 2026-10-10):
  - v2.33 이하 print_summary: 인스턴스 하나의 sysfs 문자열(예 "256K") 그대로.
  - v2.34 ~ v2.36: get_cache_full_size 로 모든 인스턴스 합계를 size_to_human_string 으로("48 MiB") — 인스턴스 문구 없음.
  - v2.37 이상: 합계 + "(N instances)" (출력이 터미널이 아니면 평면 "L2 cache:" 형태).
field_dictionary 계약: cpu.summary.groups[].l2_cache_kb / l3_cache_kb = 소켓당 KB.
종전 결함(검수 재현): 2.34 의 "L2 cache: 48 MiB" 를 인스턴스당으로 보고 코어 수(12)를 곱해 589824 KB, L3 61440 KB 를 냈다(정답 24576 · 30720).
사내 장비에는 2.34~2.36 이 없다 — 이 시험은 원본 출력 형식 재현이다(실장비 확인 아님).
"""
from __future__ import annotations

import pytest

from tests.unit.linux_raw_harness import CONTROLLED, LINUX_TASKS, Sandbox, raw_script, run_task_file

CPU_YML = LINUX_TASKS / "gather_cpu.yml"


def _cache(lines):
    run = run_task_file(CPU_YML, {"_l_cpu_raw_result": {"stdout_lines": lines, "rc": 0}}, ctx={"_l_dmi_raw": {"stdout_lines": []}})
    return run.ctx["_l_cpu_l2_kb"], run.ctx["_l_cpu_l3_kb"]


BASE = ["CPU_MODEL=Example CPU", "CPU_VENDOR=GenuineIntel", "CPU_ARCH=x86_64"]


@pytest.mark.parametrize("label,extra,expected", [
    # 감사 재현: 2.34 · 2소켓 · 12코어 — 합계를 소켓 수로 나눈다
    ("2.34_total", ["CPU_SOCKETS=2", "CPU_CPS=12", "LSCPU_VERSION=2.34", "L2_CACHE=48 MiB", "L3_CACHE=60 MiB"], (24576, 30720)),
    ("2.36_total", ["CPU_SOCKETS=2", "CPU_CPS=12", "LSCPU_VERSION=2.36", "L2_CACHE=48 MiB", "L3_CACHE=60 MiB"], (24576, 30720)),
    # 신형: 인스턴스 문구가 있으면 버전을 몰라도 합계
    ("2.37_instances", ["CPU_SOCKETS=2", "CPU_CPS=12", "LSCPU_VERSION=2.37", "L2_CACHE=48 MiB (24 instances)",
                        "L3_CACHE=60 MiB (2 instances)"], (24576, 30720)),
    ("instances_no_version", ["CPU_SOCKETS=2", "CPU_CPS=12", "L2_CACHE=48 MiB (24 instances)", "L3_CACHE=60 MiB (2 instances)"],
     (24576, 30720)),
    # VM(사내 RHEL9 형식): 4소켓 · "1 MiB (4 instances)" / "220 MiB (4 instances)"
    ("vm_instances", ["CPU_SOCKETS=4", "CPU_CPS=1", "LSCPU_VERSION=2.37", "L2_CACHE=4 MiB (4 instances)",
                      "L3_CACHE=220 MiB (4 instances)"], (1024, 56320)),
    # 구형(사내 RHEL 8.10 형식 · util-linux 2.32): 인스턴스당 — L3 그대로, L2 × 코어
    ("2.32_per_instance", ["CPU_SOCKETS=4", "CPU_CPS=1", "LSCPU_VERSION=2.32", "L2_CACHE=256K", "L3_CACHE=56320K"], (256, 56320)),
    ("2.33_per_instance", ["CPU_SOCKETS=2", "CPU_CPS=14", "LSCPU_VERSION=2.33", "L2_CACHE=1024K", "L3_CACHE=19712K"], (14336, 19712)),
    ("2.17ng_per_instance", ["CPU_SOCKETS=2", "CPU_CPS=8", "LSCPU_VERSION=2.17", "L2_CACHE=256K", "L3_CACHE=20480K"], (2048, 20480)),
    # 버전도 문구도 없으면 추측하지 않는다 — L2 null, L3 는 /proc/cpuinfo 경로
    ("unknown_semantics", ["CPU_SOCKETS=2", "CPU_CPS=12", "L2_CACHE=48 MiB", "L3_CACHE=60 MiB", "CPU_CACHE_SIZE=30720 KB"],
     (None, 30720)),
    ("unknown_no_cpuinfo", ["CPU_SOCKETS=2", "CPU_CPS=12", "L2_CACHE=48 MiB", "L3_CACHE=60 MiB"], (None, None)),
    # lscpu 부재: /proc/cpuinfo 'cache size' 만
    ("no_lscpu", ["CPU_SOCKETS=2", "CPU_CPS=12", "CPU_CACHE_SIZE=56320 KB"], (None, 56320)),
    # 합계인데 소켓 수를 모르면 null(나누지 못한다)
    ("total_without_sockets", ["CPU_CPS=12", "LSCPU_VERSION=2.38", "L2_CACHE=48 MiB", "L3_CACHE=60 MiB"], (None, None)),
])
def test_cache_per_socket_by_lscpu_version(label, extra, expected):
    assert _cache(BASE + extra) == expected, label


LSCPU_SUMMARY = """Architecture:        x86_64
CPU(s):              48
Socket(s):           2
Core(s) per socket:  12
L1d cache:           1.1 MiB
L2 cache:            48 MiB
L3 cache:            60 MiB
"""


@pytest.mark.parametrize("version_line,expected", [
    ("lscpu from util-linux 2.34", "2.34"),
    ("lscpu from util-linux 2.36.1", "2.36"),
    ("lscpu from util-linux 2.39.3", "2.39"),
    ("lscpu (util-linux-ng 2.17.2)", "2.17"),
    ("lscpu from util-linux 2.32.1", "2.32"),
    ("", None),
])
def test_raw_script_reports_the_lscpu_version(tmp_path, version_line, expected):
    sbx = Sandbox(tmp_path / "sbx", hide=CONTROLLED + ("lscpu",))
    sbx.data_file("summary.txt", LSCPU_SUMMARY)
    sbx.data_file("version.txt", version_line + ("\n" if version_line else ""))
    sbx.shim_cmd("lscpu", f'if [ "$1" = "--version" ]; then cat \'{sbx.p(sbx.data / "version.txt")}\'; exit 0; fi\n'
                          f'cat \'{sbx.p(sbx.data / "summary.txt")}\'\n')
    res = sbx.run(raw_script(CPU_YML, "raw gather"))
    assert res.rc == 0, res.stderr
    got = [l.split("=", 1)[1] for l in res.lines if l.startswith("LSCPU_VERSION=")]
    assert got == ([expected] if expected else [])
    assert "L2_CACHE=48 MiB" in res.lines and "L3_CACHE=60 MiB" in res.lines
