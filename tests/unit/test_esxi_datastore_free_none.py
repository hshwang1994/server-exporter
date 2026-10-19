"""ESXi storage.datastores[] — freeSpace None 은 모르는 값 (2026-10-19 B-6) · 문자열 단위 표 B/KB/MB/GB/TB/PB (B-7).

종전 normalize_storage.yml 의 _e_norm_datastores:
  - `ds.freeSpace | default(ds.free_space | default(0)) | int` — default 는 None 을 못 잡아 freeSpace None 이 0 이 됐고 free_mb 0 ·
    usage_percent 100% 가 나갔다 (값을 지어낸 것). 이제 free 는 None → free_mb/used_mb/usage_percent null, total_mb 는 그대로.
    진짜 0(가득 찬 datastore) 은 0 으로 남긴다.
  - 문자열 용량(total/free) 은 TB·MB 만 알아 KB·PB·Bytes 를 GB 로 읽었다. 이제 B/BYTES·KB·MB·GB·TB·PB (1024 배수, IEC 'TiB' 도 접음),
    표에 없는 단위·단위 없음은 종전처럼 GB.

실제 set_fact 템플릿을 jinja2 NativeEnvironment 로 렌더한다 (실장비 미검증).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "unit"))

from linux_raw_harness import ansible_env, render_tree  # noqa: E402

STORAGE = REPO / "esxi-gather" / "tasks" / "normalize_storage.yml"
GIB = 1073741824


def _template(var):
    for t in yaml.safe_load(STORAGE.read_text(encoding="utf-8")):
        sf = t.get("ansible.builtin.set_fact") if isinstance(t, dict) else None
        if isinstance(sf, dict) and var in sf:
            return sf[var]
    raise AssertionError(var)


def _datastores(raw):
    return render_tree(ansible_env(), _template("_e_norm_datastores"), {"_e_raw_ds": raw})


def _unsized(raw):
    return render_tree(ansible_env(), _template("_e_unsized_ds"), {"_e_raw_ds": raw})


def _one(ds):
    out = _datastores([ds])
    assert len(out) == 1
    return out[0]


# ── B-6: freeSpace None ───────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ds", [
    {"name": "ds-nfs", "type": "NFS", "capacity": GIB, "freeSpace": None, "accessible": True},
    {"name": "ds-nfs", "type": "NFS", "capacity": GIB, "accessible": True},                       # 키 자체가 없다
    {"name": "ds-nfs", "type": "NFS", "capacity": GIB, "free_space": None, "accessible": True},   # 대체 키도 None
    {"name": "ds-nfs", "type": "NFS", "capacity": GIB, "freeSpace": "", "accessible": True},      # 빈 문자열도 모르는 값
], ids=["none", "missing", "alt-key-none", "empty-string"])
def test_unknown_free_space_keeps_total_and_nulls_free_used_usage(ds):
    assert _one(ds) == {"name": "ds-nfs", "type": "NFS", "total_mb": 1024, "free_mb": None, "used_mb": None, "usage_percent": None, "accessible": True}


def test_real_zero_free_space_is_a_full_datastore_not_unknown():
    out = _one({"name": "ds-full", "type": "VMFS", "capacity": GIB, "freeSpace": 0, "accessible": True})
    assert (out["total_mb"], out["free_mb"], out["used_mb"], out["usage_percent"]) == (1024, 0, 1024, 100.0)


def test_bytes_path_with_free_space_is_unchanged():
    out = _one({"name": "ds", "type": "VMFS", "capacity": GIB, "freeSpace": GIB // 2, "accessible": True})
    assert (out["total_mb"], out["free_mb"], out["used_mb"], out["usage_percent"]) == (1024, 512, 512, 50.0)
    alt = _one({"name": "ds", "capacity": GIB, "free_space": GIB // 4})
    assert (alt["free_mb"], alt["usage_percent"]) == (256, 75.0)


def test_capacity_zero_is_still_unsized_and_unknown_free_space_is_not():
    """용량 0(미제공) 은 종전처럼 _e_unsized_ds 에 들어가고 전부 null — freeSpace None 만으로는 unsized 가 아니다."""
    raw = [{"name": "vsan", "type": "vsan", "capacity": 0, "freeSpace": 0}, {"name": "nfs", "type": "NFS", "capacity": GIB, "freeSpace": None}]
    out = _datastores(raw)
    assert out[0] == {"name": "vsan", "type": "vsan", "total_mb": None, "free_mb": None, "used_mb": None, "usage_percent": None, "accessible": None}
    assert out[1]["total_mb"] == 1024 and out[1]["free_mb"] is None
    assert _unsized(raw) == ["vsan"]


# ── B-7: 문자열 단위 ────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("total, total_mb", [
    ("1.20 PB", int(1.2 * 1024 ** 3)),      # 1288490188 — 종전엔 GB 로 읽어 1228 MB
    ("500 TB", 500 * 1024 * 1024),          # 524288000
    ("1.5 TB", 1572864),
    ("500 GB", 512000),
    ("2048 MB", 2048),                      # = 2 GB
    ("512 MB", 512),
    ("1024 KB", 1),                         # 종전엔 GB 로 읽어 1 TB 로 나갔다
    ("1073741824 B", 1024),
    ("1073741824 bytes", 1024),
    ("1.5 TiB", 1572864),                   # IEC 표기는 같은 1024 배수
    ("2 tb", 2097152),                      # 대소문자 무관 (종전과 같다)
    ("500 XB", 512000),                     # 모르는 단위 → 종전처럼 GB
    ("500", 512000),                        # 단위 없음 → GB
], ids=lambda v: str(v))
def test_text_total_units(total, total_mb):
    out = _one({"name": "ds", "type": "VMFS", "total": total, "free": "0 GB", "accessible": True})
    assert out["total_mb"] == total_mb, out


def test_text_free_uses_the_same_unit_table():
    out = _one({"name": "ds", "type": "VMFS", "total": "1.20 PB", "free": "500 TB", "accessible": True})
    assert (out["total_mb"], out["free_mb"]) == (int(1.2 * 1024 ** 3), 524288000)
    assert out["used_mb"] == out["total_mb"] - out["free_mb"]
    assert out["usage_percent"] == round(out["used_mb"] / out["total_mb"] * 100, 1)
    small = _one({"name": "ds", "total": "2048 MB", "free": "1048576 KB"})
    assert (small["total_mb"], small["free_mb"], small["used_mb"], small["usage_percent"]) == (2048, 1024, 1024, 50.0)


@pytest.mark.parametrize("ds", [
    {"name": "ds", "type": "VMFS", "total": "1.20 PB", "free": None},
    {"name": "ds", "type": "VMFS", "total": "1.20 PB"},
    {"name": "ds", "type": "VMFS", "total": "1.20 PB", "free": ""},
], ids=["none", "missing", "empty"])
def test_text_path_unknown_free_is_null_not_zero(ds):
    """문자열 경로도 같은 규칙 — free 가 없으면 '0 GB' 로 바꾸지 않는다 (종전엔 free 0 · usage 100%)."""
    out = _one(ds)
    assert out["total_mb"] == int(1.2 * 1024 ** 3) and out["free_mb"] is None and out["used_mb"] is None and out["usage_percent"] is None


def test_text_total_missing_is_unsized_as_before():
    raw = [{"name": "ds", "type": "VMFS", "free": "10 GB"}]
    out = _datastores(raw)
    assert out[0]["total_mb"] is None and out[0]["free_mb"] is None and out[0]["usage_percent"] is None
    assert _unsized(raw) == ["ds"]


def test_datastore_entry_keys_are_unchanged():
    out = _one({"name": "ds", "capacity": GIB, "freeSpace": None})
    assert set(out) == {"name", "type", "total_mb", "free_mb", "used_mb", "usage_percent", "accessible"}
