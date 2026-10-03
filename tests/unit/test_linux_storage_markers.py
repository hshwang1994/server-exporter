"""C2 — Linux 스토리지: lsblk 실패를 숨기지 않는다 (os-gather/tasks/linux/gather_storage.yml).

무엇을 고정하나 (2026-10-03 Phase 2 C2)
--------------------------------------
1. ``lsblk -J`` 실패를 ``{"blockdevices":[]}`` 로 가리지 않는다. ``LSBLK_RC`` / ``LSBLK_ERR``
   (stderr 첫 줄) marker 를 남기고, 명령이 없으면 127.
2. rc != 0 (127 제외) 이면 구형 util-linux 용 ``lsblk -b -d -n -o NAME,SIZE,TYPE,ROTA,MODEL`` 을
   **한 번** 실행해 ``LSBLK_TXT|name|size|type|rota|model`` 줄로 남긴다 → physical_disks 를 그래도 만든다.
3. ``SYS_BLOCK_COUNT`` (/sys/block 항목 수, loop/ram 제외) — 완전성 근거로 detail 에만 쓴다.
4. df 는 ``timeout`` 이 있고 ``timeout 초 명령`` 형식을 받으면(``timeout 20 true`` 로 확인 — 구형 busybox
   는 ``-t`` 형식) ``timeout 20`` 으로 감싼다. ``-l`` 은 쓰지 않는다 — NFS 포함 계약.
5. JSON 이 깨져도 호스트가 죽지 않는다. lsblk 이상 시 errors[] 에 정확히 1건, detail 에
   ``lsblk_rc / state / disks / sys_block / stderr``. state 분류:
   127 → unknown, invalid option / unknown column → unsupported, Permission denied → permission,
   rc 0 + JSON 아님 → malformed, rc 0 + 장치 0개 → empty (오류 아님).
   파일시스템만 수집돼도 섹션은 success (섹션 기준 판정) + 오류 1건 — 문서화된 "success + errors".

검증 방법
---------
production raw 본문을 PATH shim 샌드박스에서 실제 sh + awk 로 실행한다 (lsblk / udevadm / df /
timeout = shim, /proc/mounts · /sys/block = 샌드박스 경로로 치환). 같은 파일의 태스크를 적힌
순서대로 렌더한다 (block 이 예외로 끝나면 rescue — Ansible 과 같다). 실캡처 JSON 은
(``lsblk -JO`` → ``-J -b -d -o ...`` 모양으로 바꿔) 독립 oracle 과 비교한다.
"""
from __future__ import annotations

import json
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

STOR_YML = LINUX_TASKS / "gather_storage.yml"
REF_LSBLK = sorted((REPO / "tests" / "reference" / "os").glob("*/*/cmd_lsblk_json.txt"))

# 이번 변경으로 추가한 사용자 문장
LSBLK_MESSAGE = "물리 디스크 정보 수집에 실패한 항목이 있습니다. 대상 상태와 수집 로그를 확인하세요."
LSBLK_PERMISSION_MESSAGE = "물리 디스크 정보 수집에 실패한 항목이 있습니다. 수집 계정의 권한을 확인하세요."
# 기존 문장 (변경 금지)
TOTAL_FAILURE_MESSAGE = "스토리지 정보 수집에 실패했습니다. 대상 상태와 수집 로그를 확인하세요."

DF_OUT = ("Filesystem     Type 1024-blocks    Used Available Capacity Mounted on\n"
          "/dev/sda2      xfs     52403200 8123456  44279744      16% /\n"
          "/dev/sda1      xfs      1038336  250000    788336      25% /boot\n"
          "tmpfs          tmpfs    8000000       0   8000000       0% /dev/shm\n")
DF_HEADER_ONLY = "Filesystem     Type 1024-blocks    Used Available Capacity Mounted on\n"
MOUNTS = "/dev/sda2 / xfs rw,relatime 0 0\nproc /proc proc rw 0 0\n"
SYS_BLOCK = ("sda", "sdb", "nvme0n1", "dm-0", "loop0", "loop1", "ram0")       # loop/ram 제외 → 4
SLAVES = "sda2 part\nsda  disk\n"                                          # lsblk -s → OS 디스크 sda

# 구형 util-linux (RHEL 7 의 2.23 등) — -J 없음
OLD_LSBLK_STDERR = "lsblk: invalid option -- 'J'\nTry 'lsblk --help' for more information.\n"
LEGACY_ROWS = ("sda    53687091200 disk    1 Virtual disk\n"
               "sdb   107374182400 disk    0 SAMSUNG MZ7LH960HAJR-00005\n"
               "sr0     1073741823 rom     1 VMware SATA CD00\n")
UDEVADM = ('case "$*" in\n'
           '  *"/dev/sda"*) printf "ID_SERIAL_SHORT=UDEVSERIALA\\nID_WWN=0x5000c500a1b2c3d4\\n" ;;\n'
           'esac\n')


# ---------------------------------------------------------------------------
# 실캡처(lsblk -JO) → production 명령(-J -b -d -o NAME,SIZE,TYPE,ROTA,MODEL,TRAN,SERIAL,WWN) 모양
# ---------------------------------------------------------------------------
_SIZE_UNITS = {"": 1, "B": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4, "P": 1024 ** 5}


def _to_bytes(size) -> int:
    if isinstance(size, int):
        return size
    m = re.fullmatch(r"([\d.]+)([BKMGTP]?)", str(size))
    return int(float(m.group(1)) * _SIZE_UNITS[m.group(2)])


def lsblk_b_json(capture: Path) -> tuple[str, list[dict]]:
    lines = capture.read_text(encoding="utf-8", errors="replace").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("{"))
    end = next((i for i, line in enumerate(lines) if line.startswith("# === stderr")), len(lines))
    doc = json.loads("\n".join(lines[start:end]))
    devs = []
    for d in doc["blockdevices"]:                       # -d: 최상위 장치만
        typed = not isinstance(d.get("rota"), str)       # util-linux 2.33+ 는 숫자/불리언 그대로
        size = _to_bytes(d["size"])
        devs.append({"name": d["name"], "size": size if typed else str(size), "type": d["type"],
                     "rota": d.get("rota"), "model": d.get("model"), "tran": d.get("tran"),
                     "serial": d.get("serial"), "wwn": d.get("wwn")})
    return json.dumps({"blockdevices": devs}, indent=3), devs


_PROTO = {"sata": "SATA", "sas": "SAS", "nvme": "NVMe", "usb": "USB", "fc": "FibreChannel",
          "iscsi": "iSCSI"}


def oracle_disks(devs: list[dict], osdisks: set[str]) -> list[dict]:
    out = []
    for d in devs:
        if d["type"] != "disk" or int(d["size"]) <= 0:
            continue
        rota = d.get("rota")
        out.append({
            "id": f"/dev/{d['name']}",
            "total_mb": int(d["size"]) // 1048576,
            "media_type": None if rota is None else
            ("HDD" if str(rota).lower() in ("1", "true") else "SSD"),
            "protocol": _PROTO.get(str(d.get("tran") or "").lower()),
            "model": (d.get("model") or "").strip() or None,
            "serial": (d.get("serial") or "").strip() or None,
            "wwn": (d.get("wwn") or "").strip() or None,
            "is_os_disk": f"/dev/{d['name']}" in osdisks,
        })
    return out


def _view(disks: list[dict]) -> list[dict]:
    keys = ("id", "total_mb", "media_type", "protocol", "model", "serial", "wwn", "is_os_disk")
    return [{k: d.get(k) for k in keys} for d in disks]


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
_HIDE_ALL = ("lsblk", "udevadm", "findmnt", "lspci", "multipath", "df", "timeout", "sudo",
             "dmidecode")


@pytest.fixture
def sbx(tmp_path: Path) -> Sandbox:
    # df 는 항상 shim 으로 넣는다. timeout 은 호스트 것(있으면)을 그대로 써도 결과가 같다.
    return Sandbox(tmp_path / "sbx", hide=("lsblk", "udevadm", "findmnt", "lspci", "multipath"))


def install_lsblk(sbx: Sandbox, *, json_out: str = "", json_err: str = "", json_rc: int = 0,
                  txt_out: str = "", txt_rc: int = 0, names: str = "", slaves: str = SLAVES) -> str:
    """lsblk shim — 인자로 호출 모양을 가른다. 호출 기록 파일 경로(sh 경로)를 돌려준다."""
    if json_out and not json_out.endswith("\n"):
        json_out += "\n"                                # 실제 lsblk 는 줄 단위로 끝난다
    log = sbx.data_file("lsblk.log", "")
    j_out = sbx.data_file("lsblk_json.out", json_out)
    j_err = sbx.data_file("lsblk_json.err", json_err)
    t_out = sbx.data_file("lsblk_txt.out", txt_out)
    n_out = sbx.data_file("lsblk_names.out", names)
    s_out = sbx.data_file("lsblk_slaves.out", slaves)
    sbx.shim_cmd("lsblk", (
        f"echo \"$*\" >> '{log}'\n"
        'case " $* " in\n'
        f"  *\" -J \"*) cat '{j_out}'; cat '{j_err}' >&2; exit {json_rc} ;;\n"
        f"  *\" -s \"*) cat '{s_out}'; exit 0 ;;\n"
        f"  *NAME,SIZE,TYPE,ROTA,MODEL*) cat '{t_out}'; exit {txt_rc} ;;\n"
        f"  *) cat '{n_out}'; exit 0 ;;\n"
        "esac\n"))
    return log


def lsblk_calls(sbx: Sandbox) -> list[str]:
    path = sbx.data / "lsblk.log"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def run_raw(sbx: Sandbox, *, df: str | None = DF_OUT, timeout_log: bool = False) -> RunResult:
    script = raw_script(STOR_YML, "raw gather")
    mounts = sbx.data_file("mounts", MOUNTS)
    sysblock = sbx.root / "sysblock"
    for name in SYS_BLOCK:
        (sysblock / name).mkdir(parents=True, exist_ok=True)
    script = script.replace("/proc/mounts", f"'{mounts}'").replace("/sys/block", sbx.p(sysblock))
    if df is not None:
        sbx.shim_cmd("df", f"cat '{sbx.data_file('df.out', df)}'\n")
    if timeout_log:
        log = sbx.data_file("timeout.log", "")
        # exec 하지 않는다 — 'true' 가 셸 내장일 뿐 샌드박스 PATH 에 실행 파일로 없을 수 있다
        sbx.shim_cmd("timeout", f"echo \"$*\" >> '{log}'\nshift\n\"$@\"\n")
    res = sbx.run(script)
    assert sbx.leftover_tmp() == [], "stderr 임시 파일을 지우지 않았다"
    return res


def render(res: RunResult):
    return run_task_file(STOR_YML, {"_l_stor_raw": res.register()})


def storage_errors(run) -> list[dict]:
    return [e for e in run.ctx["_errors_fragment"] if e["section"] == "storage"]


def detail_fields(detail: str) -> dict[str, str]:
    return dict(part.strip().split("=", 1) for part in detail.split("; ") if "=" in part)


# ═══════════════════════════════════════════════════════════════════════════
# 정상 — 실캡처 JSON × 독립 oracle
# ═══════════════════════════════════════════════════════════════════════════
def test_reference_captures_exist():
    assert len(REF_LSBLK) >= 6, REF_LSBLK


@pytest.mark.parametrize("capture", REF_LSBLK, ids=[c.parts[-3] for c in REF_LSBLK])
def test_reference_json_builds_physical_disks(capture):
    """정상 JSON 은 셸 단계가 모두 같은 cat 이라 Jinja 체인만 캡처별로 검증한다 (셸 1회는 아래)."""
    text, devs = lsblk_b_json(capture)
    stdout = "\n".join(["LSBLK_BEGIN", text, "LSBLK_END", "LSBLK_RC=0", "LSBLK_ERR=",
                        "SYS_BLOCK_COUNT=3", "OSDISK|/dev/sda", _FS]) + "\n"
    run = render(RunResult(0, stdout, ""))
    assert not run.rescued
    disks = run.ctx["_data_fragment"]["storage"]["physical_disks"]
    assert _view(disks) == oracle_disks(devs, {"/dev/sda"})
    assert run.ctx["_errors_fragment"] == []
    assert run.ctx["_sections_collected_fragment"] == ["storage"]


def test_reference_json_through_raw_script(sbx):
    capture = next(c for c in REF_LSBLK if "rhel-baremetal" in c.parts)
    text, devs = lsblk_b_json(capture)
    install_lsblk(sbx, json_out=text, names="".join(d["name"] + "\n" for d in devs))
    res = run_raw(sbx)
    assert res.marker("LSBLK_RC") == "0"
    assert res.marker("LSBLK_ERR") == ""
    assert res.rows("LSBLK_TXT") == []
    assert not any("NAME,SIZE,TYPE,ROTA,MODEL" in c and "-J" not in c for c in lsblk_calls(sbx)), \
        "rc 0 인데 구형 fallback 을 돌렸다"
    run = render(res)
    assert not run.rescued
    disks = run.ctx["_data_fragment"]["storage"]["physical_disks"]
    assert _view(disks) == oracle_disks(devs, {"/dev/sda"})
    assert run.ctx["_errors_fragment"] == []
    assert run.ctx["_sections_collected_fragment"] == ["storage"]


def test_sys_block_count_excludes_loop_and_ram(sbx):
    install_lsblk(sbx, json_out='{"blockdevices": []}')
    assert run_raw(sbx).marker("SYS_BLOCK_COUNT") == "4"


def test_valid_json_without_devices_is_empty_not_error(sbx):
    install_lsblk(sbx, json_out='{"blockdevices": []}')
    run = render(run_raw(sbx))
    assert run.ctx["_data_fragment"]["storage"]["physical_disks"] == []
    assert run.ctx["_errors_fragment"] == []
    assert run.ctx["_sections_collected_fragment"] == ["storage"]


# ═══════════════════════════════════════════════════════════════════════════
# lsblk 이상 — 숨기지 않는다
# ═══════════════════════════════════════════════════════════════════════════
def test_lsblk_missing_is_rc_127_and_one_error(sbx):
    res = run_raw(sbx)                                   # lsblk shim 없음
    assert res.marker("LSBLK_RC") == "127"
    assert res.rows("LSBLK_TXT") == []
    run = render(res)
    assert run.ctx["_data_fragment"]["storage"]["physical_disks"] == []
    assert len(run.ctx["_data_fragment"]["storage"]["filesystems"]) == 2
    errors = storage_errors(run)
    assert len(errors) == 1
    assert errors[0]["message"] == LSBLK_MESSAGE
    fields = detail_fields(errors[0]["detail"])
    assert fields["lsblk_rc"] == "127"
    assert fields["state"] == "unknown"
    assert fields["disks"] == "0"
    assert fields["sys_block"] == "4"
    # 파일시스템은 수집됐다 — 섹션은 success (섹션 기준 판정) + 오류 1건
    assert run.ctx["_sections_collected_fragment"] == ["storage"]
    assert run.ctx["_sections_failed_fragment"] == []


def test_old_util_linux_without_json_falls_back_to_legacy_rows(sbx):
    install_lsblk(sbx, json_err=OLD_LSBLK_STDERR, json_rc=1, txt_out=LEGACY_ROWS,
                  names="sda\nsdb\nsr0\n")
    sbx.shim_cmd("udevadm", UDEVADM)
    res = run_raw(sbx)
    assert res.marker("LSBLK_RC") == "1"
    assert res.marker("LSBLK_ERR") == "lsblk: invalid option -- 'J'"
    assert res.rows("LSBLK_TXT") == [
        ["sda", "53687091200", "disk", "1", "Virtual disk"],
        ["sdb", "107374182400", "disk", "0", "SAMSUNG MZ7LH960HAJR-00005"],
        ["sr0", "1073741823", "rom", "1", "VMware SATA CD00"],
    ]
    legacy = [c for c in lsblk_calls(sbx) if "NAME,SIZE,TYPE,ROTA,MODEL" in c and "-J" not in c]
    assert legacy == ["-b -d -n -o NAME,SIZE,TYPE,ROTA,MODEL"], "구형 fallback 은 정확히 한 번"

    run = render(res)
    assert not run.rescued
    disks = run.ctx["_data_fragment"]["storage"]["physical_disks"]
    assert _view(disks) == [
        {"id": "/dev/sda", "total_mb": 51200, "media_type": "HDD", "protocol": None,
         "model": "Virtual disk", "serial": "UDEVSERIALA", "wwn": "0x5000c500a1b2c3d4",
         "is_os_disk": True},
        {"id": "/dev/sdb", "total_mb": 102400, "media_type": "SSD", "protocol": None,
         "model": "SAMSUNG MZ7LH960HAJR-00005", "serial": None, "wwn": None,
         "is_os_disk": False},
    ]
    errors = storage_errors(run)
    assert len(errors) == 1
    assert errors[0]["message"] == LSBLK_MESSAGE
    fields = detail_fields(errors[0]["detail"])
    assert fields["lsblk_rc"] == "1"
    assert fields["state"] == "unsupported"
    assert fields["disks"] == "2"
    assert fields["sys_block"] == "4"
    assert fields["stderr"] == "lsblk: invalid option -- 'J'"
    assert run.ctx["_data_fragment"]["storage"]["summary"]["grand_total_gb"] == 150


def test_unknown_column_is_unsupported(sbx):
    install_lsblk(sbx, json_err="lsblk: unknown column: TRAN\n", json_rc=1, txt_out=LEGACY_ROWS)
    run = render(run_raw(sbx))
    errors = storage_errors(run)
    assert len(errors) == 1
    assert detail_fields(errors[0]["detail"])["state"] == "unsupported"
    assert len(run.ctx["_data_fragment"]["storage"]["physical_disks"]) == 2


def test_permission_denied_state_and_privilege_sentence(sbx):
    err = "lsblk: failed to access sysfs directory: /sys/dev/block: Permission denied\n"
    install_lsblk(sbx, json_err=err, json_rc=1, txt_rc=1)
    run = render(run_raw(sbx))
    assert run.ctx["_data_fragment"]["storage"]["physical_disks"] == []
    errors = storage_errors(run)
    assert len(errors) == 1
    assert errors[0]["message"] == LSBLK_PERMISSION_MESSAGE
    fields = detail_fields(errors[0]["detail"])
    assert fields["state"] == "permission"
    assert fields["lsblk_rc"] == "1"
    assert "Permission denied" in fields["stderr"]


@pytest.mark.parametrize("json_out", [
    '{"blockdevices": [ {"name": "sda", "size": 53687091200, "type": "disk"',   # 잘린 JSON
    "",                                                                           # 출력 없음
    "[]",                                                                         # 객체 아님
    '{"devices": []}',                                                            # 키 없음
], ids=["truncated", "empty", "not-object", "no-blockdevices"])
def test_rc0_malformed_json_does_not_crash_host(sbx, json_out):
    install_lsblk(sbx, json_out=json_out)
    res = run_raw(sbx)
    assert res.marker("LSBLK_RC") == "0"
    assert res.rows("LSBLK_TXT") == [], "rc 0 이면 구형 fallback 을 돌리지 않는다"
    run = render(res)                      # 여기서 예외가 나면 linux 블록 전체가 rescue 로 간다
    assert run.ctx["_data_fragment"]["storage"]["physical_disks"] == []
    errors = storage_errors(run)
    assert len(errors) == 1
    assert errors[0]["message"] == LSBLK_MESSAGE
    assert detail_fields(errors[0]["detail"])["state"] == "malformed"
    assert run.ctx["_sections_collected_fragment"] == ["storage"]


def test_total_failure_keeps_existing_single_error_with_lsblk_evidence(sbx):
    res = run_raw(sbx, df=DF_HEADER_ONLY)                # lsblk 없음 + df 행 없음
    run = render(res)
    assert run.ctx["_sections_collected_fragment"] == []
    assert run.ctx["_sections_failed_fragment"] == ["storage"]
    errors = storage_errors(run)
    assert len(errors) == 1, "섹션 전체 실패는 기존 문장 1건 — lsblk 근거는 detail 에 합친다"
    assert errors[0]["message"] == TOTAL_FAILURE_MESSAGE
    fields = detail_fields(errors[0]["detail"])
    assert fields["cause"] == "no_output"
    assert fields["lsblk_rc"] == "127"


# ═══════════════════════════════════════════════════════════════════════════
# df
# ═══════════════════════════════════════════════════════════════════════════
def test_df_runs_under_timeout_when_available(sbx):
    install_lsblk(sbx, json_out='{"blockdevices": []}')
    res = run_raw(sbx, timeout_log=True)
    log = (sbx.data / "timeout.log").read_text(encoding="utf-8").splitlines()
    # 형식 확인(timeout 20 true) 뒤 df 를 감싼다
    assert log == ["20 true", "20 df -P -T -k"]
    assert len([line for line in res.lines if line.startswith("FS=")]) == 3


def test_df_runs_directly_when_timeout_rejects_positional_seconds(sbx):
    """구형 busybox timeout 은 ``-t 초`` 형식만 받는다 — 그런 timeout 으로 df 를 잃으면 안 된다."""
    install_lsblk(sbx, json_out='{"blockdevices": []}')
    sbx.shim_cmd("timeout", 'echo "timeout: can\'t execute \'$1\': No such file or directory" >&2\nexit 127\n')
    res = run_raw(sbx)
    assert len([line for line in res.lines if line.startswith("FS=")]) == 3


def test_df_runs_directly_without_timeout(tmp_path):
    sbx = Sandbox(tmp_path / "sbx", hide=_HIDE_ALL)     # timeout 이 보이지 않는 환경
    install_lsblk(sbx, json_out='{"blockdevices": []}')
    res = run_raw(sbx)
    assert len([line for line in res.lines if line.startswith("FS=")]) == 3
    run = render(res)
    assert [f["mount_point"] for f in run.ctx["_data_fragment"]["storage"]["filesystems"]] == \
        ["/", "/boot"]


# ═══════════════════════════════════════════════════════════════════════════
# Jinja 판정만 (raw 실행 없이) — state 분류표
# ═══════════════════════════════════════════════════════════════════════════
_FS = "FS=/dev/sda2|/|xfs|51175|7933|43241|16"


def _lines(rc: str | None, err: str = "", json_text: str = "", txt: tuple[str, ...] = ()) -> str:
    out = ["LSBLK_BEGIN"] + ([json_text] if json_text else []) + ["LSBLK_END"]
    if rc is not None:
        out += [f"LSBLK_RC={rc}", f"LSBLK_ERR={err}"]
    out += list(txt) + ["SYS_BLOCK_COUNT=3", _FS]
    return "\n".join(out) + "\n"


_ONE_DISK = ('{"blockdevices": [{"name": "sda", "size": 53687091200, "type": "disk", "rota": true, '
             '"model": "Virtual disk", "tran": null, "serial": null, "wwn": null}]}')


@pytest.mark.parametrize("rc,err,json_text,txt,state", [
    ("0", "", _ONE_DISK, (), None),
    ("0", "", '{"blockdevices": []}', (), None),
    ("127", "", "", (), "unknown"),
    ("1", "lsblk: invalid option -- 'J'", "", ("LSBLK_TXT|sda|53687091200|disk|1|Virtual disk",),
     "unsupported"),
    ("1", "lsblk: unknown column: WWN", "", (), "unsupported"),
    ("1", "lsblk: unrecognized option '--json'", "", (), "unsupported"),
    ("32", "lsblk: /dev/sda: Permission denied", "", (), "permission"),
    ("1", "lsblk: something else", "", (), "unknown"),
    ("0", "", "not json", (), "malformed"),
    ("0", "", "", (), "malformed"),
    ("0", "", '{"blockdevices": {"name": "sda"}}', (), "malformed"),  # 목록이 아닌 객체
    (None, "", _ONE_DISK, (), None),               # 새 marker 가 없는 구버전 출력 — 종전처럼 해석
], ids=["ok", "empty", "missing", "invalid-option", "unknown-column", "unrecognized",
        "permission", "other-rc", "not-json", "no-output", "devices-not-list", "legacy-no-markers"])
def test_state_classification(rc, err, json_text, txt, state):
    run = render(RunResult(0, _lines(rc, err, json_text, txt), ""))
    errors = storage_errors(run)
    if state is None:
        assert errors == []
        return
    assert len(errors) == 1
    fields = detail_fields(errors[0]["detail"])
    assert fields["state"] == state
    assert fields["lsblk_rc"] == (rc or "none")
    assert fields["sys_block"] == "3"
    expected = LSBLK_PERMISSION_MESSAGE if state == "permission" else LSBLK_MESSAGE
    assert errors[0]["message"] == expected
    assert run.ctx["_sections_collected_fragment"] == ["storage"]


@pytest.mark.parametrize("message", [LSBLK_MESSAGE, LSBLK_PERMISSION_MESSAGE])
def test_new_user_sentences_meet_portal_quality(message):
    assert_user_sentence(message, "gather_storage lsblk")


def test_raw_script_never_masks_lsblk_failure():
    script = raw_script(STOR_YML, "raw gather")
    assert '{"blockdevices":[]}' not in script, "lsblk 실패를 빈 JSON 으로 가리면 안 된다"
    assert "df -l" not in script and "df -P -T -k -l" not in script, "NFS 포함 계약 (-l 금지)"
