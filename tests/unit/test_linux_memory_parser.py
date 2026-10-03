"""C1 — Linux DIMM 파서 회귀 (os-gather/tasks/linux/gather_memory.yml).

무엇을 고정하나 (2026-10-03 Phase 2 C1)
--------------------------------------
1. dmidecode 종료 코드와 stderr 첫 줄이 별도 marker 로 남는다
   (``DMIDECODE_RC`` / ``DMIDECODE_ERR`` — 직접 실행과 sudo 재시도 둘 다). 명령이 없으면 127.
2. ``Size:`` 단위 GB / MB / kB / KB / TB 를 대소문자 무관하게 MB 로 환산한다.
   Volatile / Non-Volatile / Cache / Logical Size 는 지금처럼 제외한다.
3. DMI 레코드는 빈 줄 **또는 다음 Handle 줄**에서 끝난다 (빈 줄 없이 이어 붙은 레코드,
   끝 빈 줄 없이 잘린 마지막 레코드도 SLOT 을 낸다).
4. ``speed_mhz`` = Configured Memory Speed (숫자일 때) → 없으면 Speed. 단위 환산 없이 숫자만.
   field_dictionary 가 speed_mhz 를 "현재 동작 속도" 로 정의한다.
   **R760 실캡처는 5600 → 4400 으로 바뀐다** (정격 5600 MT/s DIMM 이 4400 MT/s 로 동작 중).
5. ``MEM_PHYS_MB > 0`` 인데 SLOT 이 0건이면 errors[] 에 정확히 1건 (섹션 status 는 success 유지).
   dmidecode 자체가 실패하면 기존 os_visible 경고 1건이 그대로 나간다.

검증 방법
---------
production raw 본문을 PATH shim 샌드박스에서 실제 ``sh`` + ``awk`` 로 실행하고
(dmidecode = 캡처를 cat 하는 shim, sudo = 인자를 그대로 실행하는 shim), 같은 파일의 태스크를
적힌 순서대로 렌더한다. 실캡처(tests/reference/os/*)는 **독립 oracle** — Python 으로 DMI
Type 16/17 레코드를 직접 나눠 계산한 값 — 과 비교한다.
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
    Sandbox,
    assert_user_sentence,
    raw_script,
    run_task_file,
)

MEM_YML = LINUX_TASKS / "gather_memory.yml"
REF_CAPTURES = sorted((REPO / "tests" / "reference" / "os").glob("*/*/cmd_dmidecode_memory.txt"))

MEMINFO = "MemTotal:       16127952 kB\nMemFree:         1000000 kB\nMemAvailable:   12000000 kB\n"

# 이번 변경으로 추가한 사용자 문장 (MEM_PHYS_MB > 0 + SLOT 0건)
ZERO_SLOT_MESSAGE = "메모리 모듈 상세 정보를 수집하지 못했습니다. 대상 상태와 수집 로그를 확인하세요."
# 기존 문장 (변경 금지 — 그대로 나가야 한다)
OS_VISIBLE_MESSAGE = ("메모리 총 용량을 물리 설치량이 아닌 운영체제 인식 값으로 수집했습니다. "
                      "수집 계정의 권한을 확인하세요.")

SUDO_OK = '[ "$1" = "-n" ] && shift\nSHIM_AS_ROOT=1; export SHIM_AS_ROOT\nexec "$@"\n'
SUDO_DENIED = 'echo "sudo: a password is required" >&2\nexit 1\n'

# 비루트 dmidecode 3.x 의 실제 모양: 버전 머리말은 stdout, 권한 오류는 stderr, rc=1
NONROOT_STDOUT = "# dmidecode 3.5\nScanning /dev/mem for entry point.\n"
NONROOT_STDERR = ("/sys/firmware/dmi/tables/smbios_entry_point: Permission denied\n"
                  "/dev/mem: Permission denied\n")


# ---------------------------------------------------------------------------
# 독립 oracle — 파서와 다른 방법(Handle 블록 분할 + 키 완전일치)으로 기대값을 만든다
# ---------------------------------------------------------------------------
_UNIT_MB = {"kb": 1 / 1024, "mb": 1, "gb": 1024, "tb": 1024 * 1024}


def dmidecode_stdout(capture: Path) -> str:
    """수집 도구 머리말(# command / # rc / __REDACTED__)을 걷어낸 dmidecode 원래 stdout (LF)."""
    lines = capture.read_text(encoding="utf-8", errors="replace").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("# dmidecode "))
    body = []
    for line in lines[start:]:
        if line.startswith("# === stderr ==="):
            break
        if line.strip() != "__REDACTED__":
            body.append(line)
    return "\n".join(body) + "\n"


def _dmi_blocks(text: str) -> list[dict]:
    blocks, cur = [], None
    for line in text.splitlines():
        if line.startswith("Handle "):
            if cur:
                blocks.append(cur)
            cur = {"handle": line, "fields": {}}
        elif not line.strip():
            if cur:
                blocks.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            key, value = line.strip().split(":", 1)
            cur["fields"].setdefault(key.strip(), value.strip())
    if cur:
        blocks.append(cur)
    return blocks


def _num(value: str | None) -> int | None:
    m = re.match(r"(\d+)\b", value or "")
    return int(m.group(1)) if m and int(m.group(1)) > 0 else None


def oracle_slots(text: str) -> list[dict]:
    out = []
    for block in _dmi_blocks(text):
        if "DMI type 17," not in block["handle"]:
            continue
        f = block["fields"]
        m = re.fullmatch(r"(\d+)\s+([A-Za-z]+)", f.get("Size", ""))
        if not m:                                   # No Module Installed / Unknown
            continue
        mb = int(int(m.group(1)) * _UNIT_MB[m.group(2).lower()])
        if mb <= 0:
            continue
        speed = (_num(f.get("Configured Memory Speed")) or _num(f.get("Configured Clock Speed"))
                 or _num(f.get("Speed")))
        out.append({"capacity_mb": mb, "speed_mhz": speed, "locator": f.get("Locator")})
    return out


def oracle_type17_count(text: str) -> int:
    return sum(1 for b in _dmi_blocks(text) if "DMI type 17," in b["handle"])


# ---------------------------------------------------------------------------
# 합성 캡처
# ---------------------------------------------------------------------------
HEADER = "# dmidecode 3.3\nGetting SMBIOS data from sysfs.\nSMBIOS 3.2.0 present.\n"
TYPE16 = ("Handle 0x1000, DMI type 16, 23 bytes\nPhysical Memory Array\n"
          "\tLocation: System Board Or Motherboard\n\tUse: System Memory\n"
          "\tError Correction Type: Multi-bit ECC\n\tMaximum Capacity: 2 TB\n"
          "\tError Information Handle: Not Provided\n\tNumber Of Devices: 4\n")


def rec(handle: str, size: str, *, speed: str = "Unknown", configured: str | None = None,
        locator: str = "DIMM_A1", cfg_label: str = "Configured Memory Speed",
        extra: tuple[str, ...] = ()) -> str:
    lines = [f"Handle {handle}, DMI type 17, 84 bytes", "Memory Device",
             "\tArray Handle: 0x1000", "\tTotal Width: 72 bits", "\tData Width: 64 bits",
             f"\tSize: {size}", "\tForm Factor: DIMM", "\tSet: None", f"\tLocator: {locator}",
             "\tBank Locator: P0 CHANNEL A", "\tType: DDR4",
             "\tType Detail: Synchronous Registered (Buffered)", f"\tSpeed: {speed}",
             "\tManufacturer: 00CE00B300CE", f"\tSerial Number: S{handle[-4:]}",
             "\tAsset Tag: Not Specified", "\tPart Number: M393A2K43DB3-CWE", "\tRank: 2"]
    if configured is not None:
        lines.append(f"\t{cfg_label}: {configured}")
    lines.extend(extra)
    return "\n".join(lines) + "\n"


def capture_of(*records: str, sep: str = "\n") -> str:
    return HEADER + "\n" + TYPE16 + "\n" + sep.join(records)


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
@pytest.fixture
def sbx(tmp_path: Path) -> Sandbox:
    # 이 스크립트가 쓰는 통제 대상 명령은 dmidecode / sudo 뿐이다
    return Sandbox(tmp_path / "sbx", hide=("dmidecode", "sudo"))


def install_dmidecode(sbx: Sandbox, *, stdout: str = "", stderr: str = "", rc: int = 0,
                      root_stdout: str | None = None, root_stderr: str = "",
                      root_rc: int = 0) -> None:
    """root_stdout 를 주면 sudo shim 을 거쳐 실행됐을 때(SHIM_AS_ROOT) 다른 결과를 낸다."""
    body = ""
    if root_stdout is not None:
        r_out = sbx.data_file("dmi_root.out", root_stdout)
        r_err = sbx.data_file("dmi_root.err", root_stderr)
        body += (f"if [ -n \"$SHIM_AS_ROOT\" ]; then cat '{r_out}'; cat '{r_err}' >&2; "
                 f"exit {root_rc}; fi\n")
    u_out = sbx.data_file("dmi_user.out", stdout)
    u_err = sbx.data_file("dmi_user.err", stderr)
    body += f"cat '{u_out}'; cat '{u_err}' >&2; exit {rc}\n"
    sbx.shim_cmd("dmidecode", body)


def run_raw(sbx: Sandbox, meminfo: str = MEMINFO) -> RunResult:
    script = raw_script(MEM_YML, "raw gather")
    meminfo_path = sbx.data_file("meminfo", meminfo)
    res = sbx.run(script.replace("/proc/meminfo", f"'{meminfo_path}'"))
    assert sbx.leftover_tmp() == [], "stderr 임시 파일을 지우지 않았다"
    return res


def render(res: RunResult) -> dict:
    run = run_task_file(MEM_YML, {"_l_mem_raw_result": res.register()})
    assert not run.rescued
    return run.ctx


def slot_lines(res: RunResult) -> list[str]:
    return [line for line in res.lines if line.startswith("SLOT|")]


# ═══════════════════════════════════════════════════════════════════════════
# 실캡처 × 독립 oracle
# ═══════════════════════════════════════════════════════════════════════════
def test_reference_captures_exist():
    assert len(REF_CAPTURES) >= 6, REF_CAPTURES


@pytest.mark.parametrize("capture", REF_CAPTURES, ids=[c.parts[-3] for c in REF_CAPTURES])
def test_reference_capture_matches_independent_oracle(sbx, capture):
    text = dmidecode_stdout(capture)
    expected = oracle_slots(text)
    install_dmidecode(sbx, stdout=text)
    res = run_raw(sbx)

    assert len(slot_lines(res)) == len(expected)
    ctx = render(res)
    slots = ctx["_data_fragment"]["memory"]["slots"]
    assert [s["capacity_mb"] for s in slots] == [e["capacity_mb"] for e in expected]
    assert [s["speed_mhz"] for s in slots] == [e["speed_mhz"] for e in expected]
    assert [s["locator"] for s in slots] == [e["locator"] for e in expected]
    assert int(res.marker("MEM_PHYS_MB")) == sum(e["capacity_mb"] for e in expected)
    assert res.marker("DMIDECODE_RC") == "0"
    assert res.marker("DMIDECODE_ERR") == ""
    assert res.marker("MEM_DEVICE_RECORDS") == str(oracle_type17_count(text))
    assert ctx["_errors_fragment"] == []
    assert ctx["_sections_collected_fragment"] == ["memory"]


def test_r760_reports_configured_speed_not_rated_speed(sbx):
    """R760 실캡처: 16 GB × 8, Speed 5600 MT/s, Configured 4400 MT/s.

    speed_mhz 는 field_dictionary 정의("현재 동작 속도")대로 4400 이다 — 종전 5600 에서 바뀐다.
    """
    capture = next(c for c in REF_CAPTURES if "rhel-baremetal" in c.parts)
    install_dmidecode(sbx, stdout=dmidecode_stdout(capture))
    res = run_raw(sbx)
    ctx = render(res)
    mem = ctx["_data_fragment"]["memory"]
    assert [s["capacity_mb"] for s in mem["slots"]] == [16384] * 8
    assert {s["speed_mhz"] for s in mem["slots"]} == {4400}
    assert res.marker("MEM_PHYS_MB") == "131072"
    assert res.marker("MEM_DEVICE_RECORDS") == "32"
    assert mem["total_mb"] == 131072
    assert mem["total_basis"] == "physical_installed"
    assert mem["summary"]["grand_total_gb"] == 128
    assert [g["speed_mhz"] for g in mem["summary"]["groups"]] == [4400]


def test_vm_capture_single_slot_with_unknown_speed(sbx):
    capture = next(c for c in REF_CAPTURES if "rhel960" in c.parts)
    install_dmidecode(sbx, stdout=dmidecode_stdout(capture))
    ctx = render(run_raw(sbx))
    slots = ctx["_data_fragment"]["memory"]["slots"]
    assert [(s["capacity_mb"], s["speed_mhz"]) for s in slots] == [(8192, None)]


# ═══════════════════════════════════════════════════════════════════════════
# 합성 캡처 — 단위 / 레코드 경계 / 속도 우선순위
# ═══════════════════════════════════════════════════════════════════════════
def test_size_units_are_case_insensitive_including_tb_and_kb(sbx):
    text = capture_of(rec("0x1100", "1 TB", locator="A1"),
                      rec("0x1101", "16384 kB", locator="A2"),     # dmidecode 2.x 표기
                      rec("0x1102", "8192 KB", locator="A3"),
                      rec("0x1103", "32 GB", locator="A4"),
                      rec("0x1104", "512 MB", locator="A5"))
    install_dmidecode(sbx, stdout=text)
    res = run_raw(sbx)
    ctx = render(res)
    caps = [s["capacity_mb"] for s in ctx["_data_fragment"]["memory"]["slots"]]
    assert caps == [1048576, 16, 8, 32768, 512] == [e["capacity_mb"] for e in oracle_slots(text)]
    assert res.marker("MEM_PHYS_MB") == str(sum(caps))


def test_volatile_cache_logical_sizes_are_not_capacity(sbx):
    extra = ("\tVolatile Size: 16 GB", "\tNon-Volatile Size: 8 GB", "\tCache Size: 4 GB",
             "\tLogical Size: 2 GB")
    text = capture_of(rec("0x1100", "No Module Installed", locator="A1", extra=extra),
                      rec("0x1101", "16 GB", locator="A2", extra=extra),
                      rec("0x1102", "Unknown", locator="A3"))
    install_dmidecode(sbx, stdout=text)
    res = run_raw(sbx)
    ctx = render(res)
    assert [s["capacity_mb"] for s in ctx["_data_fragment"]["memory"]["slots"]] == [16384]
    assert res.marker("MEM_PHYS_MB") == "16384"


def test_record_ends_on_next_handle_line_without_blank_line(sbx):
    """빈 줄 없이 이어 붙은 레코드 — 앞 레코드를 다음 'Memory Device' 가 덮어쓰면 안 된다."""
    text = capture_of(rec("0x1100", "16 GB", locator="A1", speed="3200 MT/s"),
                      rec("0x1101", "16 GB", locator="A2", speed="3200 MT/s"),
                      rec("0x1102", "8 GB", locator="A3", speed="3200 MT/s"), sep="")
    install_dmidecode(sbx, stdout=text)
    ctx = render(run_raw(sbx))
    slots = ctx["_data_fragment"]["memory"]["slots"]
    assert [s["locator"] for s in slots] == ["A1", "A2", "A3"]
    assert [s["capacity_mb"] for s in slots] == [16384, 16384, 8192]


def test_truncated_last_record_without_trailing_blank_line(sbx):
    last = rec("0x1101", "8 GB", locator="A2", speed="2933 MT/s")
    text = capture_of(rec("0x1100", "16 GB", locator="A1"), last.rstrip("\n"))
    install_dmidecode(sbx, stdout=text)
    ctx = render(run_raw(sbx))
    slots = ctx["_data_fragment"]["memory"]["slots"]
    assert [(s["locator"], s["capacity_mb"], s["speed_mhz"]) for s in slots] == [
        ("A1", 16384, None), ("A2", 8192, 2933)]


def test_speed_prefers_configured_then_falls_back_to_speed(sbx):
    text = capture_of(
        rec("0x1100", "16 GB", locator="A1", speed="Unknown", configured="Unknown"),
        rec("0x1101", "16 GB", locator="A2", speed="3200 MT/s", configured="Unknown"),
        rec("0x1102", "16 GB", locator="A3", speed="2933 MT/s", configured="2666 MT/s"),
        rec("0x1103", "16 GB", locator="A4", speed="1600 MHz", configured="1333 MHz",
            cfg_label="Configured Clock Speed"),                  # dmidecode < 3.2 표기
        rec("0x1104", "16 GB", locator="A5", speed="4800 MT/s"))  # Configured 줄 없음
    install_dmidecode(sbx, stdout=text)
    ctx = render(run_raw(sbx))
    speeds = [s["speed_mhz"] for s in ctx["_data_fragment"]["memory"]["slots"]]
    assert speeds == [None, 3200, 2666, 1333, 4800] == [e["speed_mhz"] for e in oracle_slots(text)]


# ═══════════════════════════════════════════════════════════════════════════
# 판정 — SLOT 0건 / dmidecode 실패
# ═══════════════════════════════════════════════════════════════════════════
def test_type16_only_yields_no_slot_and_single_existing_warning(sbx):
    """Type 17 이 없으면 Size 줄도 없다 → MEM_PHYS_MB=0 → 기존 os_visible 경고 1건 (새 경고 아님)."""
    install_dmidecode(sbx, stdout=HEADER + "\n" + TYPE16)
    res = run_raw(sbx)
    assert slot_lines(res) == []
    assert res.marker("MEM_PHYS_MB") == "0"
    assert res.marker("MEM_DEVICE_RECORDS") == "0"
    ctx = render(res)
    errors = ctx["_errors_fragment"]
    assert len(errors) == 1
    assert errors[0]["message"] == OS_VISIBLE_MESSAGE
    assert ctx["_data_fragment"]["memory"]["total_basis"] == "os_visible"
    assert ctx["_sections_collected_fragment"] == ["memory"]
    assert ctx["_sections_failed_fragment"] == []


def test_physical_total_without_any_slot_record_adds_exactly_one_error(sbx):
    """Size 줄은 있는데(MEM_PHYS_MB>0) 레코드 파서가 하나도 못 읽은 경우 — 조용히 slots=[] 금지."""
    text = HEADER + "\nHandle 0x1100, DMI type 17, 84 bytes\n\tSize: 8 GB\n\tSpeed: 3200 MT/s\n"
    install_dmidecode(sbx, stdout=text)
    res = run_raw(sbx)
    assert res.marker("MEM_PHYS_MB") == "8192"
    assert slot_lines(res) == []
    ctx = render(res)
    errors = ctx["_errors_fragment"]
    assert len(errors) == 1
    err = errors[0]
    assert err["section"] == "memory"
    assert err["message"] == ZERO_SLOT_MESSAGE
    assert "dmidecode_rc=0" in err["detail"]
    assert "records=0" in err["detail"]
    # 섹션 status 는 실제 결과(총량 > 0)로 — success 유지
    assert ctx["_sections_collected_fragment"] == ["memory"]
    assert ctx["_sections_failed_fragment"] == []
    assert ctx["_data_fragment"]["memory"]["total_mb"] == 8192
    assert ctx["_data_fragment"]["memory"]["total_basis"] == "physical_installed"


def test_permission_denied_keeps_rc_and_first_stderr_line(sbx):
    """비루트 dmidecode: 머리말은 stdout, 권한 오류는 stderr, rc=1 → 기존 os_visible 경고 + 근거."""
    install_dmidecode(sbx, stdout=NONROOT_STDOUT, stderr=NONROOT_STDERR, rc=1)
    res = run_raw(sbx)
    assert res.marker("DMIDECODE") == "present"
    assert res.marker("DMIDECODE_RC") == "1"
    assert res.marker("DMIDECODE_ERR") == ("/sys/firmware/dmi/tables/smbios_entry_point: "
                                          "Permission denied")
    assert res.marker("MEM_PHYS_MB") == "0"
    ctx = render(res)
    errors = ctx["_errors_fragment"]
    assert len(errors) == 1
    assert errors[0]["message"] == OS_VISIBLE_MESSAGE
    assert "dmidecode_rc=1" in errors[0]["detail"]
    assert "Permission denied" in errors[0]["detail"]
    assert ctx["_data_fragment"]["memory"]["total_basis"] == "os_visible"


def test_sudo_fallback_success_reports_the_attempt_that_produced_output(sbx):
    capture = next(c for c in REF_CAPTURES if "rhel-baremetal" in c.parts)
    install_dmidecode(sbx, stdout="", stderr=NONROOT_STDERR, rc=1,
                      root_stdout=dmidecode_stdout(capture))
    sbx.shim_cmd("sudo", SUDO_OK)
    res = run_raw(sbx)
    assert res.marker("DMIDECODE_RC") == "0"
    assert res.marker("DMIDECODE_ERR") == ""
    assert res.marker("DMIDECODE_OK") == "yes"
    assert len(slot_lines(res)) == 8


def test_sudo_fallback_denied_reports_sudo_error(sbx):
    install_dmidecode(sbx, stdout="", stderr=NONROOT_STDERR, rc=1)
    sbx.shim_cmd("sudo", SUDO_DENIED)
    res = run_raw(sbx)
    assert res.marker("DMIDECODE_RC") == "1"
    assert res.marker("DMIDECODE_ERR") == "sudo: a password is required"
    assert res.marker("DMIDECODE_OK") == "no"
    ctx = render(res)
    assert [e["message"] for e in ctx["_errors_fragment"]] == [OS_VISIBLE_MESSAGE]


def test_sudo_fallback_also_runs_when_direct_attempt_fails_with_header_output(sbx):
    """2026-10-03 C1 검수에서 발견 · 수정: 비루트 dmidecode 는 버전 머리말을 stdout 에 찍고 rc=1 로 끝나므로
    \'출력이 비었을 때만\' 재시도하던 종전 조건으로는 sudo 재시도가 일어나지 않았다. rc≠0 도 재시도 조건이다."""
    capture = next(c for c in REF_CAPTURES if "rhel-baremetal" in c.parts)
    install_dmidecode(sbx, stdout=NONROOT_STDOUT, stderr=NONROOT_STDERR, rc=1,
                      root_stdout=dmidecode_stdout(capture))
    sbx.shim_cmd("sudo", SUDO_OK)
    res = run_raw(sbx)
    assert len(slot_lines(res)) == 8


def test_dmidecode_missing_is_rc_127(sbx):
    res = run_raw(sbx)                       # dmidecode shim 없음
    assert res.marker("DMIDECODE") == "absent"
    assert res.marker("DMIDECODE_RC") == "127"
    assert res.marker("DMIDECODE_ERR") == ""
    ctx = render(res)
    errors = ctx["_errors_fragment"]
    assert [e["message"] for e in errors] == [OS_VISIBLE_MESSAGE]
    assert "dmidecode_rc=127" in errors[0]["detail"]
    assert "state=absent" in errors[0]["detail"]


def test_stderr_marker_strips_pipes_and_keeps_only_first_line(sbx):
    install_dmidecode(sbx, stdout=capture_of(rec("0x1100", "16 GB")),
                      stderr="warn | table quirk\nsecond line\n")
    res = run_raw(sbx)
    err = res.marker("DMIDECODE_ERR")
    assert err.startswith("warn") and "table quirk" in err
    assert "|" not in err and "second line" not in err


# ═══════════════════════════════════════════════════════════════════════════
# Jinja 판정만 (raw 실행 없이)
# ═══════════════════════════════════════════════════════════════════════════
_BASE_LINES = ["MEM_TOTAL_KB=16127952", "MEM_AVAIL_KB=12000000", "DMIDECODE=present",
               "DMIDECODE_RC=0", "DMIDECODE_ERR=", "DMIDECODE_OK=yes", "MEM_PHYS_MB=16384"]
_SLOT = "SLOT|16384|DDR4|3200|00CE00B300CE|M393A2K43DB3-CWE|S1100|A1"


@pytest.mark.parametrize("with_slot", [True, False], ids=["slot", "no-slot"])
def test_zero_slot_error_appears_only_without_slot_records(with_slot):
    lines = _BASE_LINES + ([_SLOT] if with_slot else []) + ["MEM_DEVICE_RECORDS=4"]
    ctx = render(RunResult(0, "\n".join(lines) + "\n", ""))
    errors = ctx["_errors_fragment"]
    if with_slot:
        assert errors == []
    else:
        assert len(errors) == 1
        assert errors[0]["section"] == "memory"
        assert errors[0]["message"] == ZERO_SLOT_MESSAGE
        assert "records=4" in errors[0]["detail"]
        assert "dmidecode_rc=0" in errors[0]["detail"]
    assert ctx["_sections_collected_fragment"] == ["memory"]
    assert ctx["_sections_failed_fragment"] == []


def test_zero_slot_render_survives_missing_new_markers():
    """새 marker 가 없는 출력(구버전 스크립트 / 잘린 stdout)에서도 렌더가 죽지 않는다."""
    lines = ["MEM_TOTAL_KB=16127952", "DMIDECODE=present", "DMIDECODE_OK=yes", "MEM_PHYS_MB=8192"]
    ctx = render(RunResult(0, "\n".join(lines) + "\n", ""))
    assert [e["message"] for e in ctx["_errors_fragment"]] == [ZERO_SLOT_MESSAGE]


def test_new_user_sentence_meets_portal_quality():
    assert_user_sentence(ZERO_SLOT_MESSAGE, "gather_memory zero-slot")


# ═══════════════════════════════════════════════════════════════════════════
# 이식성 — 레코드 파서 awk
# ═══════════════════════════════════════════════════════════════════════════
def test_slot_awk_program_avoids_posix_character_classes():
    """SLOT 을 만드는 awk 프로그램은 ``[[:space:]]`` 같은 POSIX 문자 클래스를 쓰지 않는다.

    mawk 1.3.3 (구형 Debian / Ubuntu 의 기본 awk) 은 POSIX 문자 클래스를 해석하지 못한다
    (1.3.4 에서 지원). 그러면 레코드 파서만 아무것도 못 읽고, grep 기반 MEM_PHYS_MB 는 정상이라
    slots=[] 가 조용히 나간다. 공백은 ``[ \\t]`` 로 쓴다.
    """
    script = raw_script(MEM_YML, "raw gather")
    programs = re.findall(r"awk '(.*?)'", script, flags=re.S)
    slot_programs = [p for p in programs if "SLOT|" in p]
    assert slot_programs, "SLOT 을 만드는 awk 프로그램을 찾지 못함"
    for program in slot_programs:
        assert "[[:" not in program
