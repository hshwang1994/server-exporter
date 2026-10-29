"""multi_node.partitions[] Summary 가 top-level 과 같은 규칙인지 (2026-10-29 SA-03).

파티션 cpu · memory · storage 는 모듈(_normalize_cpu_raw · _normalize_memory_raw · _normalize_storage_raw)이, top-level 은
normalize_standard.yml 이 만든다. 함수를 공유하지 않으므로 같은 입력을 두 구현에 넣어 값이 같은지 대조하고(parity),
경계값은 원천과 규칙으로 손으로 적은 기대값과 비교한다(현재 출력 복사 아님, rule 95 R3).
  cpu     — 코어 미상(TotalCores 없음 · 0 이하)이 있거나 목록 미완결이면 부분 합 대신 그 파티션 System 의 ProcessorSummary(검사 통과) 또는 null.
            제조사는 _CPU_MFR_CANON 표(= normalize_standard.yml FIX 2 표)로 정규화.
  memory  — 그룹 용량 GiB 는 half-even 반올림, 0 GB 그룹 없음. total_mib 가 null 이면 그 파티션 MemorySummary(검사 통과) 또는 null.
  storage — GiB 내림. 원천을 못 읽음 · 미완결 → null, 원천을 읽었고 비었음 → 0.
  network — 파티션은 카드 · 포트를 수집하지 않으므로 Summary 를 계산하지 않는다({groups: []}).
"""
from __future__ import annotations

import copy
import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))
sys.path.insert(0, str(REPO / "tests" / "integration"))
for _n in ("ansible", "ansible.module_utils", "ansible.module_utils.basic"):
    sys.modules.setdefault(_n, types.ModuleType(_n))
if not hasattr(sys.modules["ansible.module_utils.basic"], "AnsibleModule"):
    sys.modules["ansible.module_utils.basic"].AnsibleModule = object

import redfish_gather as rg  # noqa: E402
import emulator_harness as H  # noqa: E402
import normalize_chain as NC  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "redfish"
_CPU_GROUP_KEYS = ("model", "manufacturer", "sockets", "cores_per_socket", "total_cores")
_CPU_SUMMARY_TPL = NC.task(NC.SUMMARIES)["_rf_summary_cpu"]


def _top(raw):
    """top-level normalize — Summary 까지 렌더한 뒤 fragment 의 cpu · memory · storage 잎."""
    ctx = NC.render(raw)
    return {"cpu": NC.fragment(ctx, "cpu", ("sockets", "cores_physical", "summary")),
            "memory": NC.fragment(ctx, "memory", ("total_mb", "installed_mb", "summary")),
            "storage": NC.fragment(ctx, "storage", ("summary",))}


def _cpu_groups(summary):
    return [{k: g.get(k) for k in _CPU_GROUP_KEYS} for g in summary["groups"]]


# ── FIX 2 표 drift — Python 상수와 normalize_standard.yml 의 두 Jinja 표 ─────────────────────────────────────────────

_MFR_SAMPLES = ["Intel(R) Corporation", "Intel", "GenuineIntel", "AMD", "Advanced Micro Devices, Inc.", "AuthenticAMD",
                "Ampere(R)", "  Ampere Computing  ", "ARM", "", None]


@pytest.mark.parametrize("value", _MFR_SAMPLES)
def test_cpu_manufacturer_table_matches_normalize_jinja(value):
    e = NC.env()
    top_scalar = e.from_string(NC.FRAGMENT["cpu"]["manufacturer"]).render(_rf_d_cpus=[{"manufacturer": value}])
    top_scalar = top_scalar.strip() if isinstance(top_scalar, str) else top_scalar
    top_group = e.from_string(_CPU_SUMMARY_TPL).render(
        _rf_d_cpus=[{"model": "M", "manufacturer": value, "total_cores": 8}])["groups"][0]["manufacturer"]
    assert rg._canon_cpu_manufacturer(value) == top_scalar == top_group


def test_cpu_manufacturer_table_literal_tokens_in_jinja():
    """표의 토큰이 두 Jinja 표에 그대로 있다 — 한쪽에 토큰을 더하거나 빼면 시험이 잡는다."""
    for tpl in (NC.FRAGMENT["cpu"]["manufacturer"], _CPU_SUMMARY_TPL):
        for tokens, name in rg._CPU_MFR_CANON:
            for t in tokens:
                assert f"'{t}' in _mf_l" in tpl
            assert name in tpl


# ── cpu · memory · storage — 같은 입력, 두 구현 ────────────────────────────────────────────────────────────────

def _procs(cores, mfr="Intel(R) Corporation", model="Xeon Gold 6430"):
    return [{"id": f"CPU{i}", "processor_type": "CPU", "model": model, "manufacturer": mfr, "total_cores": c} for i, c in enumerate(cores)]


@pytest.mark.parametrize("cores,summary,failed,sockets,total", [
    ([24, 24], {"count": 2, "core_count": 48}, False, 2, 48),
    ([24, None], {"count": 2, "core_count": 48}, False, 2, 48),
    ([24, None], {"count": 2, "core_count": 24}, False, 2, None),
    ([24, 0], {}, False, 2, None),
    (["16", "16"], {}, False, 2, 32),                      # 문자열 정수는 정수로 읽는다
    (["n/a", 16], {"count": 2, "core_count": 40}, False, 2, 40),
    ([24], {"count": 2, "core_count": 48}, True, 2, 48),
    ([24], {}, True, None, None),
    ([24, None], {"count": 1, "core_count": 48}, False, 2, None),
    ([], {"count": 2, "core_count": 32}, False, 2, 32),
])
def test_partition_cpu_follows_top_level_rules(cores, summary, failed, sockets, total):
    procs = _procs(cores)
    part = rg._normalize_cpu_raw(copy.deepcopy(procs), {"cpu_summary": summary}, failed)
    top = _top({"data": {"processors": procs, "system": {"cpu_summary": summary}},
                "collected": ([] if failed else ["processors"]), "failed_sections": (["processors"] if failed else []),
                "unsupported_sections": []})["cpu"]
    assert (part["sockets"], part["cores_physical"]) == (sockets, total) == (top["sockets"], top["cores_physical"])
    assert _cpu_groups(part["summary"]) == _cpu_groups(top["summary"])
    for g in part["summary"]["groups"]:
        assert g["manufacturer"] == "Intel"


def test_partition_cpu_mixed_unknown_marks_only_that_group():
    procs = _procs([24, 24], model="Xeon A") + _procs([None, 16], model="Xeon B")
    part = rg._normalize_cpu_raw(procs, {}, False)
    assert [(g["model"], g["sockets"], g["total_cores"], g["cores_per_socket"]) for g in part["summary"]["groups"]] == \
        [("Xeon A", 2, 48, 24), ("Xeon B", 2, None, None)]
    assert part["cores_physical"] is None and part["sockets"] == 4


def _slots(caps):
    return [{"id": f"DIMM{i}", "capacity_mb": c, "type": "DDR5", "speed_mhz": 4800, "manufacturer": "Samsung", "part_number": "P"}
            for i, c in enumerate(caps)]


@pytest.mark.parametrize("total_mib,caps,ms_gib,total_mb,grand", [
    (65536, [32768, 32768], 64, 65536, 64),
    (None, [32768, None], 128, 131072, 128),
    (None, [32768, None], 32, None, None),
    (None, [32768, 32768], 64, 65536, 64),        # 멤버를 못 읽음(모듈 total_mib null) + MemorySummary ≥ 아는 합
    (None, [32768, 32768], 32, None, None),
    (0, [], 512, 524288, 512),
    (0, [], None, None, None),                    # DIMM 0개 + 요약 없음 → null (0 GB 아님)
    (None, [], None, None, None),
])
def test_partition_memory_follows_top_level_rules(total_mib, caps, ms_gib, total_mb, grand):
    mem = {"total_mib": total_mib, "slots": _slots(caps)}
    sys_ = {"memory_summary": ({"total_gib": ms_gib} if ms_gib is not None else {})}
    part = rg._normalize_memory_raw(copy.deepcopy(mem), sys_)
    top = _top({"data": {"memory": mem, "system": sys_}, "collected": ["memory"], "failed_sections": [],
                "unsupported_sections": []})["memory"]
    assert (part["total_mb"], part["installed_mb"], part["summary"]["grand_total_gb"]) == (total_mb, total_mb, grand)
    assert (top["total_mb"], top["installed_mb"], top["summary"]["grand_total_gb"]) == (total_mb, total_mb, grand)
    assert part["summary"]["groups"] == top["summary"]["groups"]


@pytest.mark.parametrize("cap_mib,unit_gb", [
    (512, None),      # 0.5 GiB → 0 (half-even) — 0 GB 그룹을 만들지 않는다
    (1536, 2),        # 1.5 → 2 (짝수)
    (2560, 2),        # 2.5 → 2 (짝수 — 종전 파티션 내림도 2, top-level 과 같음)
    (3584, 4),        # 3.5 → 4 (짝수 — 종전 파티션 내림은 3 이라 top-level 과 갈렸다)
    (16384, 16),
])
def test_partition_memory_group_rounding_is_half_even(cap_mib, unit_gb):
    mem = {"total_mib": cap_mib, "slots": _slots([cap_mib])}
    part = rg._normalize_memory_raw(mem, {})
    top = _top({"data": {"memory": mem, "system": {}}, "collected": ["memory"], "failed_sections": [],
                "unsupported_sections": []})["memory"]
    units = [g["unit_capacity_gb"] for g in part["summary"]["groups"]]
    assert units == ([] if unit_gb is None else [unit_gb]) == [g["unit_capacity_gb"] for g in top["summary"]["groups"]]


def _drives(sizes):
    return [{"id": f"D{i}", "name": f"Disk{i}", "model": "M", "serial": f"S{i}", "capacity_bytes": b, "media_type": "SSD",
             "protocol": "NVMe"} for i, b in enumerate(sizes)]


@pytest.mark.parametrize("inv,sizes,grand", [
    ({}, [], None),                                                      # 원천을 하나도 읽지 못함
    ({"enumerated": True, "incomplete": False}, [], 0),                  # 확인한 0
    ({"enumerated": True, "incomplete": True}, [], None),
    ({"enumerated": False, "incomplete": True}, [], None),
    ({}, [1600321314816] * 4, 5960),                                     # 1490.42 GiB → 1490 (내림) × 4
    ({"enumerated": True, "incomplete": True}, [1600321314816], None),   # 아는 디스크만 더한 부분 합을 쓰지 않는다
    ({"enumerated": True, "incomplete": False}, [0, None], 0),           # 용량을 모르는 디스크는 그룹 · 합에서 뺀다(종전과 같다)
])
def test_partition_storage_follows_top_level_rules(inv, sizes, grand):
    raw = {"controllers": [{"id": "C1", "name": "C1", "drives": _drives(sizes)}], "volumes": []}
    part = rg._normalize_storage_raw(copy.deepcopy(raw), inv)["summary"]
    top = _top({"data": {"storage": raw}, "collected": ["storage"], "failed_sections": [], "unsupported_sections": [],
                "storage_inventory": inv})["storage"]["summary"]
    assert part["grand_total_gb"] == grand == top["grand_total_gb"]
    assert part == top


def test_partition_storage_without_inventory_argument_keeps_old_caller_behavior():
    """inventory 를 넘기지 않는 종전 호출부: 디스크가 있으면 원천을 읽은 것, 없으면 null(확인 근거 없음)."""
    assert rg._summarize_partition_disks([])["grand_total_gb"] is None
    one = rg._normalize_storage_raw({"controllers": [{"id": "C1", "drives": _drives([1600321314816])}]})
    assert one["summary"]["grand_total_gb"] == 1490


# ── CSUS 3200 실측 recording — 파티션 0 은 top-level System 과 같은 System 이다 ──────────────────────────────────────────

CSUS = ["real_hpe_csus3200", "real_hpe_csus3200_01", "real_hpe_csus3200_02", "real_hpe_csus3200_03"]


def _rec(name):
    return json.loads((FIX / name / "recording.json").read_text(encoding="utf-8"))


def _replay(name, rec):
    meta = json.loads((FIX / name / "meta.json").read_text(encoding="utf-8"))
    g, n, r = H.make_replayer(rec)
    return H.run_gather(g, n, realm_impl=r, manager_layout=meta.get("manager_layout"), firmware_scope=meta.get("firmware_inventory_scope"))


_raw = NC.raw_collect


def _source_disk_gib(rec, system="Partition0"):
    """원천에서 직접: 그 System 의 Storage 멤버가 가리킨 드라이브 중 용량이 있는 것의 floor(CapacityBytes / 2^30) 합 (Empty Bay 제외)."""
    total, members = 0, rec[f"get::Systems/{system}/Storage"][1].get("Members") or []
    for m in members:
        for d in rec["get::" + rg._p(m["@odata.id"])][1].get("Drives") or []:
            st, body = rec["get::" + rg._p(d["@odata.id"])][:2]
            cap = body.get("CapacityBytes") or 0
            if st == 200 and cap and "empty" not in str(body.get("Name") or "").lower():
                total += cap // (1 << 30)
    return total


@pytest.mark.parametrize("name", CSUS)
def test_csus_partition_summary_equals_top_level_and_source(name):
    rec = _rec(name)
    res = _replay(name, rec)
    top = _top(_raw(res))
    (part,) = res["multi_node"]["partitions"]
    assert part["id"] == "Partition0" and part["system_uri"].rstrip("/").endswith("Systems/Partition0")
    assert (part["cpu"]["sockets"], part["cpu"]["cores_physical"]) == (top["cpu"]["sockets"], top["cpu"]["cores_physical"])
    assert _cpu_groups(part["cpu"]["summary"]) == _cpu_groups(top["cpu"]["summary"])
    raw_mfrs = {p.get("manufacturer") for p in res["data"]["processors"]}
    assert raw_mfrs == {"Intel(R) Corporation"}, "원천 Processor.Manufacturer 는 원문 그대로 모듈 raw 에 남는다"
    assert [g["manufacturer"] for g in part["cpu"]["summary"]["groups"]] == ["Intel"]
    assert part["memory"]["summary"] == top["memory"]["summary"]
    assert part["memory"]["total_mb"] == top["memory"]["total_mb"]
    assert part["storage"]["summary"] == top["storage"]["summary"]
    assert part["storage"]["summary"]["grand_total_gb"] == _source_disk_gib(rec)
    assert part["network"]["summary"] == {"groups": []}, "파티션 network Summary 는 계산하지 않는다(카드 · 포트 미수집)"


def test_csus_partition_cpu_uses_its_own_processor_summary_when_list_incomplete():
    """Processor 멤버 1개 500: 목록이 미완결 — sockets 는 Partition0 ProcessorSummary.Count(4 ≥ 읽은 3), CoreCount 가 없어 cores 는 null."""
    rec = _rec("real_hpe_csus3200_01")
    ps = rec["get::Systems/Partition0"][1]["ProcessorSummary"]
    assert ps["Count"] == 4 and "CoreCount" not in ps
    first = rec["get::Systems/Partition0/Processors"][1]["Members"][0]["@odata.id"]
    rec["get::" + rg._p(first)] = [500, {}, "HTTP 500: Internal Server Error"]
    res = _replay("real_hpe_csus3200_01", rec)
    (part,) = res["multi_node"]["partitions"]
    top = _top(_raw(res))["cpu"]
    assert (part["cpu"]["sockets"], part["cpu"]["cores_physical"]) == (4, None) == (top["sockets"], top["cores_physical"])
    assert [g["sockets"] for g in part["cpu"]["summary"]["groups"]] == [3]
