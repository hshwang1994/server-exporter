"""Redfish Summary 의 null · 0 · 부분 합 규칙 (2026-10-29 SA-04 · SA-05 · SA-07 · SA-08 · SA-10 · 개수 점검).

공통 원칙: null 은 "미제공 또는 확정 불가", 0 은 "확인한 0", 부분 합은 전체 합이 아니다.
  SA-04  cpu.cores_physical · groups[].total_cores — 코어를 모르는 CPU 가 있거나 CPU 목록을 다 못 읽으면 아는 코어의 합을 쓰지 않는다.
         검사를 통과한 ProcessorSummary.CoreCount, 없으면 null. sockets 는 목록이 온전하면 목록 수, 아니면 검사를 통과한 Count 또는 null.
  SA-05  memory.total_mb · installed_mb · summary.grand_total_gb — DIMM 합이 미완결이면 검사를 통과한 MemorySummary 또는 null.
  SA-07  storage.summary.grand_total_gb — 전원 상태는 쓰지 않는다. 드라이브 목록 원천을 하나도 못 읽었거나 미완결이면 null,
         원천을 읽었고 비었으면 0, 그 밖은 합(GiB 내림).
  SA-08  network.summary.groups[].speed_mbps — 그룹 키의 0 은 null(interfaces[].speed_mbps 원본 0 은 그대로, 사용자 결정).
  SA-10  network.summary.primary_speed_mbps — is_primary NIC 의 속도(0 · null · 대표 없음 → null).
  개수   network.summary.port_count / adapter_count — 그 섹션을 끝까지 읽었을 때만 정수(0 포함).
수집 모듈 재생(emulator_harness) → normalize_standard.yml 태스크를 Ansible 순서대로 렌더한다(tests/integration/normalize_chain.py).
기대값은 원천 응답과 규칙으로 손으로 적었다(현재 출력 복사 아님, rule 95 R3).
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
_LEAVES = {"cpu": ("sockets", "cores_physical", "summary"), "memory": ("total_mb", "installed_mb", "summary"),
           "storage": ("physical_disks", "summary"), "network": ("interfaces", "summary")}


def _normalize(raw):
    """_rf_raw_collect(모듈 결과) → Summary 까지의 facts + fragment 의 cpu/memory/storage/network 잎(이 시험이 보는 키)."""
    ctx = NC.render(raw)
    return ctx, {sec: NC.fragment(ctx, sec, keys) for sec, keys in _LEAVES.items()}


_notices = NC.notices
_raw = NC.raw_collect


def _rec(name):
    return json.loads((FIX / name / "recording.json").read_text(encoding="utf-8"))


def _replay(name, rec=None):
    rec = _rec(name) if rec is None else rec
    meta = json.loads((FIX / name / "meta.json").read_text(encoding="utf-8")) if (FIX / name / "meta.json").is_file() else {}
    g, n, r = H.make_replayer(rec)
    return H.run_gather(g, n, realm_impl=r, manager_layout=meta.get("manager_layout"), firmware_scope=meta.get("firmware_inventory_scope"))


@pytest.fixture(autouse=True)
def _reset():
    rg._reset_notices()
    yield
    rg._reset_notices()


# ── SA-07 storage: 실측 recording 재생 ──────────────────────────────────────────────────────────────────────────────────

def test_storage_without_any_drive_list_source_is_null_not_zero():
    """dl380_gen12_03(전원 Off): Storage 컬렉션 200 · 멤버 0, System 섀시 Chassis/1 에 Drives · Links.Drives 가 없다 — 0개를 확인할 근거가 없다."""
    rec = _rec("real_hpe_dl380_gen12_03")
    assert rec["get::Systems/1/Storage"][1]["Members"] == []
    ch = rec["get::Chassis/1"][1]
    assert "Drives" not in ch and "Drives" not in (ch.get("Links") or {})
    res = _replay("real_hpe_dl380_gen12_03", rec)
    assert res["aux"]["storage_inventory"] == {"enumerated": False, "incomplete": False}
    ctx, frag = _normalize(_raw(res))
    assert frag["storage"]["physical_disks"] == [] and frag["storage"]["summary"]["grand_total_gb"] is None
    (msg,) = _notices(ctx, "storage")
    assert "하나도 읽지 못함" in msg and "grand_total_gb = null" in msg


def test_storage_confirmed_empty_drive_lists_are_zero():
    """r1 CSUS 01: Storage/1 의 Drives 가 빈 배열이고 섀시 r001u01/Drives 컬렉션이 200 · 멤버 0 — 확인한 0."""
    rec = _rec("real_hpe_csus3200")
    assert rec["get::Systems/Partition0/Storage/1"][1]["Drives"] == []
    assert rec["get::Chassis/r001u01/Drives"][1]["Members"] == []
    res = _replay("real_hpe_csus3200", rec)
    assert res["aux"]["storage_inventory"] == {"enumerated": True, "incomplete": False}
    ctx, frag = _normalize(_raw(res))
    assert frag["storage"]["summary"]["grand_total_gb"] == 0 and _notices(ctx, "storage") == []


@pytest.mark.parametrize("storage_drives,expected", [
    ([], 0),            # Storage 멤버의 Drives 빈 배열만 원천 — 빈 배열도 드라이브 목록을 읽은 것이다(확인한 0)
    ("absent", None),   # 같은 본문에 Drives 키 자체가 없음 — 읽은 원천이 없다(수집하지 못함)
])
def test_storage_empty_drives_array_alone_decides_zero_vs_null(storage_drives, expected):
    """r1 CSUS 01 에서 섀시 r001u01 의 Drives 광고를 지워 Storage/1 의 Drives 만 남긴다 — 둘의 차이는 Drives 키 하나뿐이다."""
    rec = _rec("real_hpe_csus3200")
    ch = rec["get::Chassis/r001u01"][1]
    assert ch.pop("Drives") == {"@odata.id": "/redfish/v1/Chassis/r001u01/Drives"} and "Drives" not in (ch.get("Links") or {})
    rec.pop("get::Chassis/r001u01/Drives")
    sto = rec["get::Systems/Partition0/Storage/1"][1]
    assert sto["Drives"] == []
    if storage_drives == "absent":
        sto.pop("Drives")
    res = _replay("real_hpe_csus3200", rec)
    assert res["aux"]["storage_inventory"] == {"enumerated": expected == 0, "incomplete": False}
    assert "storage" not in res["failed_sections"]
    ctx, frag = _normalize(_raw(res))
    assert frag["storage"]["physical_disks"] == [] and frag["storage"]["summary"]["grand_total_gb"] == expected
    assert bool(_notices(ctx, "storage")) == (expected is None)


def _set_power_state(rec, state):
    n = 0
    for k, v in rec.items():
        if k.startswith("get::") and isinstance(v[1], dict) and "PowerState" in v[1] and k.count("/") <= 2 \
                and (k.startswith("get::Systems/") or k.startswith("get::Chassis/")):
            v[1]["PowerState"] = state
            n += 1
    assert n, "PowerState 를 가진 System/Chassis 본문이 없다"


@pytest.mark.parametrize("name,state,expected", [
    ("real_hpe_dl380_gen12_03", "On", None),    # 원천 구조가 같으면 전원을 켜도 null — 판정에 전원 상태를 쓰지 않는다
    ("real_hpe_csus3200", "Off", 0),             # 원천 구조가 같으면 전원을 꺼도 0
])
def test_storage_null_or_zero_does_not_follow_power_state(name, state, expected):
    rec = _rec(name)
    _set_power_state(rec, state)
    _, frag = _normalize(_raw(_replay(name, rec)))
    assert frag["storage"]["summary"]["grand_total_gb"] == expected


def _storage_drive_keys(rec, system):
    keys = []
    coll = rec.get(f"get::Systems/{system}/Storage", [0, {}])[1]
    for m in coll.get("Members") or []:
        body = rec.get("get::" + rg._p(m["@odata.id"]), [0, {}])[1]
        keys += ["get::" + rg._p(d["@odata.id"]) for d in (body.get("Drives") or [])]
    return [k for k in keys if k in rec]


def test_storage_drive_member_failure_makes_total_null():
    rec = _rec("real_hpe_dl380_gen12_01")
    drives = _storage_drive_keys(rec, "1")
    assert len(drives) >= 2
    base = _normalize(_raw(_replay("real_hpe_dl380_gen12_01", copy.deepcopy(rec))))[1]["storage"]["summary"]["grand_total_gb"]
    assert isinstance(base, int) and base > 0
    rec[drives[0]] = [500, {}, "HTTP 500: Internal Server Error"]
    res = _replay("real_hpe_dl380_gen12_01", rec)
    assert res["aux"]["storage_inventory"]["incomplete"] is True
    assert "storage" in res["failed_sections"]
    ctx, frag = _normalize(_raw(res))
    assert frag["storage"]["summary"]["grand_total_gb"] is None, "아는 디스크만 더한 부분 합을 전체로 쓰지 않는다"
    assert any("다 읽지 못함" in m for m in _notices(ctx, "storage"))


def test_storage_volume_failure_does_not_touch_disk_total():
    rec = _rec("real_dell_r740")
    vols = [k for k, v in rec.items() if k.endswith("/Volumes") and v[0] == 200]
    assert vols, "Volumes 컬렉션이 있는 recording 이어야 한다"
    base = _normalize(_raw(_replay("real_dell_r740", copy.deepcopy(rec))))[1]["storage"]["summary"]["grand_total_gb"]
    rec[vols[0]] = [500, {}, "HTTP 500: Internal Server Error"]
    res = _replay("real_dell_r740", rec)
    assert res["aux"]["storage_inventory"] == {"enumerated": True, "incomplete": False}
    assert _normalize(_raw(res))[1]["storage"]["summary"]["grand_total_gb"] == base


@pytest.mark.parametrize("inv,disks,attempted,expected", [
    ({}, [], False, None),                                               # storage 를 수집하지 않음
    ({}, [], True, None),                                                # 원천을 하나도 읽지 못함
    ({"enumerated": True, "incomplete": False}, [], True, 0),            # 확인한 0
    ({"enumerated": True, "incomplete": True}, [], True, None),          # 미완결
    ({}, [1000204886016, 1000204886016], True, 1862),                    # 디스크가 있으면 원천을 읽은 것 — 931.5 GiB ×2 = 1863 → 각 내림 931
    ({"enumerated": True, "incomplete": True}, [1000204886016], True, None),
])
def test_storage_grand_total_rule_table(inv, disks, attempted, expected):
    drives = [{"name": f"Disk{i}", "model": "M", "serial": f"S{i}", "capacity_bytes": b, "media_type": "SSD", "protocol": "SAS"}
              for i, b in enumerate(disks)]
    raw = {"data": {"storage": {"controllers": [{"id": "C1", "name": "C1", "drives": drives}], "volumes": []}},
           "collected": (["storage"] if attempted else []), "failed_sections": [], "unsupported_sections": [], "storage_inventory": inv}
    _, frag = _normalize(raw)
    assert frag["storage"]["summary"]["grand_total_gb"] == expected


# ── SA-04 cpu ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _cpu_raw(cores, summary=None, failed=False):
    procs = [{"id": f"CPU{i}", "processor_type": "CPU", "model": "Xeon Gold 6430", "manufacturer": "Intel(R) Corporation", "total_cores": c}
             for i, c in enumerate(cores)]
    return {"data": {"processors": procs, "system": {"cpu_summary": summary or {}}},
            "collected": ([] if failed else ["processors"]), "failed_sections": (["processors"] if failed else []),
            "unsupported_sections": []}


@pytest.mark.parametrize("cores,summary,failed,sockets,total,group", [
    ([24, 24], {"count": 2, "core_count": 48}, False, 2, 48, (48, 24)),          # 목록 온전 · 코어 모두 앎 → 합
    ([24, None], {"count": 2, "core_count": 48}, False, 2, 48, (None, None)),    # 코어 미상 1 → 검사를 통과한 CoreCount(48 ≥ 24+1)
    ([24, None], {"count": 2, "core_count": 24}, False, 2, None, (None, None)),  # CoreCount 24 < 24+1 → 신뢰 불가
    ([24, 0], {}, False, 2, None, (None, None)),                                 # TotalCores 0 은 미상(설치된 CPU 의 0코어는 없다)
    ([24], {"count": 2, "core_count": 48}, True, 2, 48, (24, 24)),               # 목록을 다 못 읽음 → Count · CoreCount
    ([24], {}, True, None, None, (24, 24)),                                      # 목록을 다 못 읽음 + 요약 없음 → null
    ([24, None], {"count": 1, "core_count": 48}, False, 2, None, (None, None)),  # Count 1 < 목록 2 → 요약 신뢰 불가
    ([], {"count": 2, "core_count": 32}, False, 2, 32, None),                    # 목록이 빈 경로(BUG-13) — 종전처럼 요약
    ([None, None], {}, False, 2, None, (None, None)),                            # 코어 모두 미상 + 요약 없음 → null (감사 3.7 C2)
    ([None, None], {"count": 2, "core_count": 48}, False, 2, 48, (None, None)),  # 코어 모두 미상 → CoreCount(48 ≥ 0+2), 그룹은 null
])
def test_cpu_counts_use_full_sum_or_trusted_summary_or_null(cores, summary, failed, sockets, total, group):
    ctx, frag = _normalize(_cpu_raw(cores, summary, failed))
    assert (frag["cpu"]["sockets"], frag["cpu"]["cores_physical"]) == (sockets, total)
    groups = frag["cpu"]["summary"]["groups"]
    if group is None:
        assert groups == []
    else:
        (g,) = groups
        assert (g["total_cores"], g["cores_per_socket"]) == group and g["sockets"] == len(cores)
        assert g["manufacturer"] == "Intel"
    partial = failed or any(c is None or c == 0 for c in cores)
    assert bool(_notices(ctx, "cpu")) == partial


# ── SA-05 memory ───────────────────────────────────────────────────────────────────────────────────────────────────

def _mem_raw(total_mib, caps, ms_gib, failed=False):
    slots = [{"id": f"DIMM{i}", "capacity_mb": c, "type": "DDR5", "speed_mhz": 4800, "manufacturer": "Samsung", "part_number": "P"}
             for i, c in enumerate(caps)]
    return {"data": {"memory": {"total_mib": total_mib, "slots": slots},
                     "system": {"memory_summary": ({"total_gib": ms_gib} if ms_gib is not None else {})}},
            "collected": ([] if failed else ["memory"]), "failed_sections": (["memory"] if failed else []), "unsupported_sections": []}


@pytest.mark.parametrize("total_mib,caps,ms_gib,failed,total_mb,grand", [
    (65536, [32768, 32768], 64, False, 65536, 64),           # DIMM 합 완결
    (None, [32768, None], 128, False, 131072, 128),         # 용량 미상 DIMM + MemorySummary 128 GiB > 아는 합 32 GiB
    (None, [32768, None], 32, False, None, None),            # MemorySummary 32 GiB 는 아는 합보다 크지 않다 → 신뢰 불가
    (None, [32768, 32768], 64, True, 65536, 64),             # 멤버를 못 읽음 + MemorySummary ≥ 아는 합
    (None, [32768, 32768], 32, True, None, None),            # MemorySummary < 아는 합 → 신뢰 불가
    (0, [], 512, False, 524288, 512),                        # DIMM 0개(종전 B-1 경로) → MemorySummary
    (None, [None, None], None, False, None, None),           # 용량 모두 미상 + 요약 없음 → null (감사 3.7 M3, 종전 0)
    (None, [None, None], 64, False, 65536, 64),              # 용량 모두 미상 + MemorySummary 64 GiB > 아는 합 0
])
def test_memory_totals_use_full_sum_or_trusted_summary_or_null(total_mib, caps, ms_gib, failed, total_mb, grand):
    ctx, frag = _normalize(_mem_raw(total_mib, caps, ms_gib, failed))
    assert (frag["memory"]["total_mb"], frag["memory"]["installed_mb"]) == (total_mb, total_mb)
    assert frag["memory"]["summary"]["grand_total_gb"] == grand
    assert bool(_notices(ctx, "memory")) == (total_mib is None)


# ── SA-04 · SA-05 모듈 → normalize: 실측 recording(DL380 Gen12 · iLO 7)에 멤버 실패를 넣어 재생 ─────────────────────────────────
# 기대값은 recording 원천(장착 DIMM 의 CapacityMiB · MemorySummary · ProcessorSummary)에서 계산한다.

G12 = "real_hpe_dl380_gen12_01"
G12_DIMM = "get::Systems/1/Memory/proc1dimm1"


def _module_notes(section):
    return [n["message"] for n in rg.notices() if n["section"] == section]


def _g12_dimms(rec):
    """장착 DIMM(200 · Absent 아님 · CapacityMiB 양수)의 (키, MiB)."""
    return [(k, v[1]["CapacityMiB"]) for k, v in rec.items()
            if k.startswith("get::Systems/1/Memory/") and v[0] == 200 and isinstance(v[1], dict)
            and (v[1].get("Status") or {}).get("State") != "Absent" and (v[1].get("CapacityMiB") or 0) > 0]


def test_memory_module_full_read_keeps_dimm_sum():
    rec = _rec(G12)
    dimms = _g12_dimms(rec)
    ms_gib = rec["get::Systems/1"][1]["MemorySummary"]["TotalSystemMemoryGiB"]
    assert len(dimms) == 16 and sum(c for _, c in dimms) == ms_gib * 1024     # 원천: 96 GiB × 16 = 1536 GiB = MemorySummary
    res = _replay(G12, rec)
    assert res["data"]["memory"]["total_mib"] == sum(c for _, c in dimms) and "memory" not in res["failed_sections"]
    ctx, frag = _normalize(_raw(res))
    assert frag["memory"]["total_mb"] == sum(c for _, c in dimms) and frag["memory"]["summary"]["grand_total_gb"] == ms_gib
    assert _notices(ctx, "memory") == []


@pytest.mark.parametrize("member,summary_gib", [
    ("500", "keep"),     # 멤버 1개 500 — MemorySummary 1536 GiB ≥ 읽은 DIMM 합 1440 GiB → 총량은 MemorySummary
    ("404", "keep"),     # 컬렉션이 가리킨 멤버의 404 도 "못 읽음" 이다(미제공이 아니다)
    ("no_uri", "keep"),  # @odata.id 없는 멤버 — errors 가 없으므로 모듈 notice 로 남긴다
    ("500", None),       # MemorySummary 없음 → null
    ("500", 1024),       # MemorySummary 1024 GiB < 읽은 DIMM 합 1440 GiB → 신뢰 불가 → null
])
def test_memory_module_unread_dimm_is_not_summed_as_total(member, summary_gib):
    rec = _rec(G12)
    dimms = _g12_dimms(rec)
    known_mib = sum(c for k, c in dimms if k != G12_DIMM)
    sysb = rec["get::Systems/1"][1]
    if member == "no_uri":
        coll = rec["get::Systems/1/Memory"][1]
        coll["Members"] = [({} if "get::" + rg._p(m["@odata.id"]) == G12_DIMM else m) for m in coll["Members"]]
    else:
        rec[G12_DIMM] = [int(member), {}, f"HTTP {member}"]
    if summary_gib is None:
        sysb.pop("MemorySummary")
    elif summary_gib != "keep":
        sysb["MemorySummary"]["TotalSystemMemoryGiB"] = summary_gib
    ms = (sysb.get("MemorySummary") or {}).get("TotalSystemMemoryGiB")
    trusted = ms is not None and ms * 1024 >= known_mib     # 멤버만 못 읽었을 때의 검사(아는 합 이상) — 원천 값으로 계산
    res = _replay(G12, rec)
    mem = res["data"]["memory"]
    assert mem["total_mib"] is None, "읽은 DIMM 의 합(부분 합)을 total_mib 로 쓰지 않는다 — 104bcaf0 은 1440 GiB 를 적었다"
    assert len(mem["slots"]) == len(dimms) - 1
    # 섹션 상태는 104bcaf0 과 같다 — 멤버 조회 실패는 errors 로 memory failed, @odata.id 없는 멤버는 errors 가 없다
    assert ("memory" in res["failed_sections"]) == (member != "no_uri")
    assert any("@odata.id 없는 Memory 멤버 1개" in m for m in _module_notes("memory")) == (member == "no_uri")
    ctx, frag = _normalize(_raw(res))
    want = ms if trusted else None
    assert frag["memory"]["summary"]["grand_total_gb"] == want
    assert (frag["memory"]["total_mb"], frag["memory"]["installed_mb"]) == ((want * 1024,) * 2 if trusted else (None, None))
    (msg,) = _notices(ctx, "memory")
    assert "부분 합을 쓰지 않음" in msg


@pytest.mark.parametrize("summary,sockets", [
    ("keep", 2),    # ProcessorSummary.Count 2 ≥ 읽은 목록 1 → sockets 2. 원천에 CoreCount 가 없어 cores_physical 은 null
    (None, None),   # ProcessorSummary 없음 → sockets 도 null
])
def test_cpu_module_unread_processor_is_not_counted_as_total(summary, sockets):
    rec = _rec(G12)
    procs = sorted(k for k in rec if k.startswith("get::Systems/1/Processors/"))
    ps = rec["get::Systems/1"][1]["ProcessorSummary"]
    assert len(procs) == 2 and ps["Count"] == 2 and "CoreCount" not in ps
    rec[procs[0]] = [500, {}, "HTTP 500"]
    if summary is None:
        rec["get::Systems/1"][1].pop("ProcessorSummary")
    res = _replay(G12, rec)
    assert "processors" in res["failed_sections"]
    ctx, frag = _normalize(_raw(res))
    assert (frag["cpu"]["sockets"], frag["cpu"]["cores_physical"]) == (sockets, None), "읽은 CPU 의 목록 수 · 코어 합을 전체로 쓰지 않는다"
    (msg,) = _notices(ctx, "cpu")
    assert "CPU 목록을 다 읽지 못함" in msg


# ── SA-08 · SA-10 · 개수: network.summary ───────────────────────────────────────────────────────────────────────────────

NET_TPL = NC.task(NC.SUMMARIES)["_rf_summary_network"]


def _net_summary(interfaces, collected=("network", "network_adapters"), netad=None):
    return NC.env().from_string(NET_TPL).render(
        _rf_norm_interfaces=interfaces, _rf_d_netad=netad or {"adapters": [], "ports": []},
        _rf_raw_collect={"collected": list(collected)})


def _if(nid, speed, link, primary=False, mac=None):
    return {"id": nid, "mac": mac or f"aa:bb:cc:00:00:{nid[-1]}0", "speed_mbps": speed, "link_status": link, "is_primary": primary}


def test_group_key_zero_speed_is_null_and_merges_with_null_group():
    s = _net_summary([_if("N1", 0, "down"), _if("N2", None, "unknown"), _if("N3", 25000, "up", primary=True)])
    assert [(g["speed_mbps"], g["quantity"], g["link_up_count"]) for g in s["groups"]] == [(None, 2, 0), (25000, 1, 1)]


def test_interface_detail_keeps_source_zero_speed():
    raw = {"data": {"network": [{"id": "NIC1", "name": "NIC1", "mac": "aa:bb:cc:00:00:01", "link_status": "down", "speed_mbps": 0,
                                 "ipv4": []}]},
           "collected": ["network"], "failed_sections": [], "unsupported_sections": []}
    _, frag = _normalize(raw)
    assert frag["network"]["interfaces"][0]["speed_mbps"] == 0, "상세의 원본 0 은 그대로 (사용자 결정 — Summary 만 null)"
    assert frag["network"]["summary"]["groups"][0]["speed_mbps"] is None


@pytest.mark.parametrize("interfaces,expected", [
    ([_if("N1", 25000, "up"), _if("N2", 10000, "up", primary=True)], 10000),   # 종전 규칙(첫 link up NIC)이면 25000
    ([_if("N1", 25000, "up"), _if("N2", 0, "up", primary=True)], None),        # 대표 NIC 속도 0 → null (다른 NIC 으로 대체하지 않는다)
    ([_if("N1", 25000, "up"), _if("N2", None, "up", primary=True)], None),
    ([_if("N1", 25000, "up"), _if("N2", 10000, "up")], None),                  # 대표 NIC 없음
])
def test_primary_speed_is_the_primary_nic_speed(interfaces, expected):
    assert _net_summary(interfaces)["primary_speed_mbps"] == expected


@pytest.mark.parametrize("collected,ports,adapters", [
    (("network", "network_adapters"), 0, 0),        # 끝까지 읽었고 비었다 — 확인한 0
    (("network",), 0, None),                        # network_adapters 미지원 · 실패 · 일부 실패 · 미수집
    (("network_adapters",), None, 0),
    ((), None, None),
])
def test_port_and_adapter_counts_only_when_section_read(collected, ports, adapters):
    s = _net_summary([], collected=collected)
    assert (s["port_count"], s["adapter_count"]) == (ports, adapters) and s["groups"] == []


def test_dmtf_mockup_without_network_adapters_has_null_adapter_count():
    """dmtf_rackmount1: network_adapters 섹션을 수집하지 않았다(collected 에 없음) — 종전 adapter_count 0 은 "보지 못함" 이었다."""
    res = _replay("dmtf_rackmount1")
    assert "network_adapters" not in res["collected"] and "network" in res["collected"]
    _, frag = _normalize(_raw(res))
    s = frag["network"]["summary"]
    assert s["adapter_count"] is None and s["port_count"] == len(frag["network"]["interfaces"])
