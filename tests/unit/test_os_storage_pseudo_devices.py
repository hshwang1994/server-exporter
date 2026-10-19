"""Linux storage.physical_disks — lsblk 가 type=disk 로 내는 가상 블록 장치 제외 (2026-10-19, B-9).

os-gather/tasks/linux/gather_storage.yml 을 linux_raw_harness.run_task_file 로 **파일 순서대로** 렌더한다
(jinja2_native + StrictUndefined — Ansible 과 같은 평가). 입력은 raw gather register(`_l_stor_raw`) 하나다.

- zram(압축 swap) · nbd(network block device) · drbd · ram(brd RAM disk) · fd(floppy) 는 물리 디스크가 아니다 —
  JSON 경로와 구형 util-linux 의 LSBLK_TXT 경로 모두에서 physical_disks · summary 합계에서 뺀다.
- pmem(영구 메모리) 은 실제 장치라 남긴다. 제외 패턴은 태스크 `vars` 의 `_l_stor_pseudo_disk_re` 하나다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("jinja2")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "unit"))
from linux_raw_harness import RunResult, iter_tasks, load_tasks, run_task_file  # noqa: E402

STOR_YML = REPO / "os-gather" / "tasks" / "linux" / "gather_storage.yml"
TASK = "linux | storage | normalize physical disks"

TB = 1000204886016          # 1 TB SATA (lsblk -b)
GIB = 1024 ** 3


def _dev(name, size, **kw):
    d = {"name": name, "size": size, "type": "disk", "rota": False, "model": None, "tran": None, "serial": None, "wwn": None}
    d.update(kw)
    return d


def _json_lines(devs, extra=()):
    return ["LSBLK_BEGIN", json.dumps({"blockdevices": devs}), "LSBLK_END", "LSBLK_RC=0", "LSBLK_ERR=",
            "SYS_BLOCK_COUNT=", *extra]


def _run(lines):
    reg = RunResult(0, "".join(ln + "\n" for ln in lines), "").register()
    run = run_task_file(STOR_YML, {"_l_stor_raw": reg}, ctx={})
    assert not run.rescued, run.rescued
    return run.ctx


def _pseudo_re() -> str:
    task = next(t for t in iter_tasks(load_tasks(STOR_YML)) if t.get("name") == TASK)
    return task["vars"]["_l_stor_pseudo_disk_re"]


def test_json_path_drops_pseudo_block_devices_and_keeps_pmem():
    devs = [
        _dev("sda", TB, rota=True, model="ST1000NM0008", tran="sata", serial="ZA1"),
        _dev("zram0", 8 * GIB),
        _dev("nbd0", 10 * GIB),
        _dev("fd0", 1474560),
        _dev("ram0", 16 * 1024 * 1024),
        _dev("drbd0", 100 * GIB),
        _dev("pmem0", 256 * GIB, model=None),
    ]
    ctx = _run(_json_lines(devs))
    disks = ctx["_l_norm_physical_disks"]
    assert [d["id"] for d in disks] == ["/dev/sda", "/dev/pmem0"]
    assert ctx["_data_fragment"]["storage"]["physical_disks"] == disks
    summary = ctx["_data_fragment"]["storage"]["summary"]
    assert [g["unit_capacity_gb"] for g in summary["groups"]] == [931, 256]      # zram 8 GB · drbd 100 GB 그룹 없음
    assert summary["grand_total_gb"] == 931 + 256
    assert ctx["_sections_collected_fragment"] == ["storage"] and ctx["_errors_fragment"] == []


def test_legacy_text_rows_drop_pseudo_block_devices_too():
    """구형 util-linux(--json 없음) 의 LSBLK_TXT|name|size|type|rota|model 경로도 같은 패턴으로 뺀다."""
    lines = ["LSBLK_RC=1", "LSBLK_ERR=lsblk: unrecognized option '--json'", "SYS_BLOCK_COUNT=4",
             f"LSBLK_TXT|sda|{TB}|disk|1|ST1000NM0008",
             f"LSBLK_TXT|zram0|{8 * GIB}|disk|0|",
             f"LSBLK_TXT|nbd0|{10 * GIB}|disk|0|",
             f"LSBLK_TXT|pmem0|{256 * GIB}|disk|0|"]
    ctx = _run(lines)
    assert [d["id"] for d in ctx["_l_norm_physical_disks"]] == ["/dev/sda", "/dev/pmem0"]
    assert ctx["_data_fragment"]["storage"]["summary"]["grand_total_gb"] == 931 + 256


def test_only_pseudo_disks_leave_no_physical_disk():
    ctx = _run(_json_lines([_dev("zram0", 8 * GIB), _dev("nbd0", 10 * GIB)]))
    assert ctx["_l_norm_physical_disks"] == []
    assert ctx["_data_fragment"]["storage"]["summary"]["groups"] == []


@pytest.mark.parametrize("name", ["zram0", "zram1", "nbd0", "nbd15", "drbd0", "ram0", "ram15", "fd0"])
def test_pseudo_pattern_matches_virtual_block_devices(name):
    assert re.match(_pseudo_re(), name), name


@pytest.mark.parametrize("name", ["sda", "sdb", "nvme0n1", "vda", "xvda", "mmcblk0", "pmem0", "dm-0", "md0", "hda"])
def test_pseudo_pattern_keeps_real_disk_names(name):
    assert not re.match(_pseudo_re(), name), name
