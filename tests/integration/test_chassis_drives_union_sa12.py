"""storage 드라이브 = Storage 가 가리킨 드라이브 ∪ 섀시가 광고한 드라이브 (2026-10-29 SA-12 · SA-07).

대상 섀시 = System Links.Chassis ∪ Storage 멤버 Links.Enclosures. 섀시 본문이 광고한 `Drives` 컬렉션과 `Links.Drives` 만 따른다.
중복은 @odata.id 로 먼저, 새로 읽은 드라이브는 SerialNumber 로 지운다. Serial 이 없어 같은지 모르는 섀시 전용 드라이브는 더하지 않고
합계를 미산출로 둔다. 선택 링크(섀시 본문 · 섀시 Drives 컬렉션)의 404 는 "미제공", 가리킨 드라이브의 404 · 그 밖의 실패는 미완결이다.

입력은 실측 recording(HPE DL380 Gen12 · CSUS 3200)을 메모리에서만 고친 것이다 — recording 파일은 바꾸지 않는다.
**404 출처 구분 (사용자 의견 2026-10-29)**: 수집 코드는 실행 중에 404 의 출처를 알 수 없다. 재생기는 recording 에 없는 경로를
`replay-miss: path not in recording` 표식이 붙은 404 로 돌려준다(emulator_harness._REPLAY_MISS). 이 시험은 두 404 가 같은 출력을
낸다는 것만 확인하고, 표식으로 둘을 갈라 적는다 — replay-miss 로 지나간 경로는 실장비 응답을 검증한 것이 아니다(MOCK_LIMITATION).
"""
from __future__ import annotations

import copy
import json
import sys
import types
from contextlib import contextmanager
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
REPLAY_MISS_MARK = "replay-miss: path not in recording"
assert REPLAY_MISS_MARK in H._REPLAY_MISS[2]

SYS = "/redfish/v1/Systems/1"
SYS_CHASSIS = ["/redfish/v1/Chassis/1"]
ENC = "Chassis/DE00B000"                  # Storage DE00B000 의 Links.Enclosures — gen12 recording 에는 본문이 없다(replay-miss)
ENC_URI = "/redfish/v1/" + ENC
STO = "get::Systems/1/Storage/DE00B000"
DISK_GIB = 1600321314816 // (1 << 30)     # 1.60TB SAS SSD 2개(S7R1NE0YB01554 · S7R1NE0YB01553) — 1490 GiB(내림)


def _rec(name="real_hpe_dl380_gen12_01"):
    return json.loads((FIX / name / "recording.json").read_text(encoding="utf-8"))


def _storage_drive_uris(rec):
    return [d["@odata.id"] for d in rec[STO][1]["Drives"]]


def _enclosure(rec, coll=None, links=None):
    """Storage 의 Enclosures 섀시 본문을 recording 에 넣는다 — coll: Drives 컬렉션 멤버, links: Links.Drives (None 이면 광고 없음)."""
    body = {"@odata.id": ENC_URI, "Id": "DE00B000", "Name": "Drive Enclosure"}
    if coll is not None:
        body["Drives"] = {"@odata.id": ENC_URI + "/Drives"}
        rec["get::" + ENC + "/Drives"] = [200, {"@odata.id": ENC_URI + "/Drives", "Members": [{"@odata.id": u} for u in coll],
                                                "Members@odata.count": len(coll)}, None]
    if links is not None:
        body["Links"] = {"Drives": [{"@odata.id": u} for u in links]}
    rec["get::" + ENC] = [200, body, None]
    return rec


@contextmanager
def _transport(rec):
    """recording 재생 + 요청 기록. 응답 캐시는 main() 과 같게 켠다."""
    log = []
    g, _n, _r = H.make_replayer(rec)

    def get_impl(ip, path, user, pw, timeout, verify):
        st, data, err = g(ip, path, user, pw, timeout, verify)
        log.append({"path": path, "status": st, "err": err})
        return st, data, err

    saved = rg._get_impl
    rg._get_impl = get_impl
    rg._reset_response_cache(enabled=True)
    rg._reset_notices()
    try:
        yield log
    finally:
        rg._get_impl = saved
        rg._reset_response_cache(enabled=False)


def _storage(rec, system=SYS, chassis=SYS_CHASSIS):
    inv = {}
    with _transport(rec) as log:
        val, errs = rg.gather_storage("127.0.0.1", system, "u", "p", 30, False, chassis, inventory_out=inv)
        notices = [n["message"] for n in rg._NOTICES if n["section"] == "storage"]
    rg._reset_notices()
    ctx = NC.render({"data": {"storage": val}, "collected": ([] if errs else ["storage"]),
                     "failed_sections": (["storage"] if errs else []), "unsupported_sections": [], "storage_inventory": inv})
    return {"val": val, "errs": errs, "inv": inv, "notices": notices, "log": log,
            "disks": ctx["_rf_norm_physical_disks"], "grand": ctx["_rf_summary_storage"]["grand_total_gb"],
            "norm_notices": NC.notices(ctx, "storage")}


def _serials(r):
    return sorted(d["serial"] for d in r["disks"])


def _requested(r, path):
    return [e for e in r["log"] if e["path"] == path]


# ── 기준: recording 그대로 ────────────────────────────────────────────────────────────────────────────────────

def test_recording_enclosure_is_replay_miss_and_does_not_change_storage():
    """gen12 recording 에는 Enclosures 섀시 본문이 없다 — 재생기 표식 404(replay-miss)로 지나간다. 결과는 변하지 않지만 이것은
    섀시 경로의 검증이 아니다(MOCK_LIMITATION — 실응답은 Tier 1 미러에서 확인)."""
    rec = _rec()
    assert "get::" + ENC not in rec
    r = _storage(rec)
    (enc,) = _requested(r, ENC)
    assert enc["status"] == 404 and REPLAY_MISS_MARK in enc["err"]
    assert r["errs"] == [] and r["inv"] == {"enumerated": True, "incomplete": False}
    assert _serials(r) == ["S7R1NE0YB01553", "S7R1NE0YB01554"] and r["grand"] == 2 * DISK_GIB
    assert not any("섀시" in n for n in r["notices"])


def test_recorded_404_and_replay_miss_give_same_result_but_are_told_apart():
    rec_404 = _rec()
    rec_404["get::" + ENC] = [404, {}, "HTTP 404: Not Found"]      # (i) 기록된 실제 404 — 장비가 "없다" 고 답함
    rec_miss = _rec()                                                # (ii) recording 에 없는 경로 — 재생기 표식 404
    a, b = _storage(rec_404), _storage(rec_miss)
    for k in ("val", "errs", "inv", "notices", "grand"):
        assert a[k] == b[k], k
    (ea,), (eb,) = _requested(a, ENC), _requested(b, ENC)
    assert ea["status"] == eb["status"] == 404
    assert REPLAY_MISS_MARK not in (ea["err"] or "") and REPLAY_MISS_MARK in eb["err"]


def test_csus_chassis_drives_404_sources_full_replay():
    """CSUS 3200 (mock2 01): System 섀시 r001u01 이 Drives 컬렉션을 광고하지만 recording 에는 그 컬렉션이 없다. 기록된 404 와 replay-miss 404
    는 같은 봉투를 낸다 — 섀시 Drives 의 실응답(미러: Storage 와 같은 URI 4건)은 pytest 가 아니라 Tier 1 에서만 확인된다."""
    name = "real_hpe_csus3200_01"
    meta = json.loads((FIX / name / "meta.json").read_text(encoding="utf-8"))
    rec_miss = _rec(name)
    assert rec_miss["get::Chassis/r001u01"][1]["Drives"]["@odata.id"] == "/redfish/v1/Chassis/r001u01/Drives"
    assert "get::Chassis/r001u01/Drives" not in rec_miss
    rec_404 = copy.deepcopy(rec_miss)
    rec_404["get::Chassis/r001u01/Drives"] = [404, {}, "HTTP 404: Not Found"]
    outs, marks = [], []
    for rec in (rec_404, rec_miss):
        seen = []
        g, n, rlm = H.make_replayer(rec)

        def logged(ip, path, *a, _g=g, _seen=seen):
            st, data, err = _g(ip, path, *a)
            _seen.append((path, st, err))
            return st, data, err
        res = H.run_gather(logged, n, realm_impl=rlm, manager_layout=meta.get("manager_layout"),
                           firmware_scope=meta.get("firmware_inventory_scope"))
        outs.append({k: res[k] for k in ("status", "collected", "failed_sections", "data", "error_count")} | {"aux": res["aux"]})
        marks.append([REPLAY_MISS_MARK in (e or "") for p, s, e in seen if p == "Chassis/r001u01/Drives"])
    assert outs[0] == outs[1]
    # top-level storage 와 partition storage 가 각각 묻는다(404 는 응답 캐시에 남지 않는다 — 미러 실응답 200 은 1회)
    assert marks[0] and not any(marks[0]) and marks[1] and all(marks[1])


# ── 합집합 · 중복 제거 ──────────────────────────────────────────────────────────────────────────────────────────

def test_union_adds_drive_the_storage_did_not_point_to():
    rec = _rec()
    all_uris = _storage_drive_uris(rec)
    rec[STO][1]["Drives"] = [{"@odata.id": u} for u in all_uris if not u.endswith("/Drives/1")]   # Storage 가 Drives/1 을 빠뜨림
    _enclosure(rec, coll=all_uris)
    r = _storage(rec)
    added = [c for c in r["val"]["controllers"] if c["id"] == "Chassis.DE00B000"]
    assert [d["serial"] for d in added[0]["drives"]] == ["S7R1NE0YB01553"] and len(added) == 1
    assert added[0]["name"] == "Drive Enclosure Drives"
    assert _serials(r) == ["S7R1NE0YB01553", "S7R1NE0YB01554"] and r["grand"] == 2 * DISK_GIB
    assert "섀시 DE00B000 의 드라이브 1건 — Storage 가 가리키지 않아 추가" in r["notices"]
    assert r["inv"] == {"enumerated": True, "incomplete": False} and r["errs"] == []


def test_union_does_not_reread_or_double_count_same_uri():
    rec = _rec()
    _enclosure(rec, coll=_storage_drive_uris(rec))                  # 미러 실측과 같은 모양: 섀시 Drives 8건 = Storage 가 가리킨 8건
    r = _storage(rec)
    assert [c["id"] for c in r["val"]["controllers"]] == ["DE00B000"]
    assert _serials(r) == ["S7R1NE0YB01553", "S7R1NE0YB01554"] and r["grand"] == 2 * DISK_GIB
    assert len(_requested(r, ENC + "/Drives")) == 1 and r["errs"] == []
    assert not any("섀시" in n for n in r["notices"])


def test_union_drops_same_disk_under_another_uri_by_serial():
    rec = _rec()
    alias = ENC_URI + "/Drives/0-alias"
    rec["get::" + ENC + "/Drives/0-alias"] = copy.deepcopy(rec["get::" + ENC + "/Drives/0"])
    _enclosure(rec, links=[alias])
    r = _storage(rec)
    assert len(_requested(r, ENC + "/Drives/0-alias")) == 1, "새 URI 는 읽는다"
    assert [c["id"] for c in r["val"]["controllers"]] == ["DE00B000"], "Serial 이 같은 디스크는 더하지 않는다"
    assert r["grand"] == 2 * DISK_GIB and r["inv"] == {"enumerated": True, "incomplete": False}


def test_serialless_chassis_only_drive_is_not_added_and_total_is_unknown():
    rec = _rec()
    extra = ENC_URI + "/Drives/99"
    rec["get::" + ENC + "/Drives/99"] = [200, {"@odata.id": extra, "Id": "99", "Name": "1.60TB 22.5G SAS SSD",
                                               "Model": "MO001600PYHRE", "CapacityBytes": 1600321314816}, None]
    _enclosure(rec, links=[extra])
    r = _storage(rec)
    assert _serials(r) == ["S7R1NE0YB01553", "S7R1NE0YB01554"], "같은 디스크인지 판정할 수 없어 더하지 않는다"
    assert r["inv"]["incomplete"] is True and r["grand"] is None
    assert any(n.startswith("SerialNumber 없는 섀시 전용 드라이브 1건") for n in r["notices"])
    assert r["norm_notices"] == ["드라이브 목록을 다 읽지 못함 — 부분 합을 쓰지 않음: summary.grand_total_gb = null"]


def test_storage_without_drives_uses_chassis_drives_as_before():
    """Storage 가 드라이브를 하나도 가리키지 않으면 종전 A-10 경로와 같다 — Empty Bay 는 거르고 notice 문장도 같다."""
    rec = _rec()
    all_uris = _storage_drive_uris(rec)
    rec[STO][1]["Drives"] = []
    _enclosure(rec, coll=all_uris)
    r = _storage(rec)
    (added,) = [c for c in r["val"]["controllers"] if c["id"] == "Chassis.DE00B000"]
    assert sorted(d["serial"] for d in added["drives"]) == ["S7R1NE0YB01553", "S7R1NE0YB01554"]
    assert "Storage 에 드라이브 0건 — 섀시 DE00B000 의 Drives 2건 사용" in r["notices"]
    assert r["grand"] == 2 * DISK_GIB and r["inv"] == {"enumerated": True, "incomplete": False}


def test_chassis_without_advertised_drive_links_is_not_queried_further():
    rec = _rec()
    _enclosure(rec)                                                  # 본문만 있고 Drives · Links.Drives 광고 없음
    r = _storage(rec)
    assert len(_requested(r, ENC)) == 1 and not _requested(r, ENC + "/Drives"), "경로를 조립해 묻지 않는다"
    assert r["grand"] == 2 * DISK_GIB and r["errs"] == []


# ── 실패 · 미완결 ────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key,resp,msg", [
    ("get::" + ENC, [500, {}, "HTTP 500: Internal Server Error"], "Chassis /redfish/v1/Chassis/DE00B000 실패"),
    ("get::" + ENC + "/Drives", [500, {}, "HTTP 500: Internal Server Error"], "Chassis Drives /redfish/v1/Chassis/DE00B000/Drives 실패"),
])
def test_chassis_or_chassis_drives_failure_makes_total_unknown(key, resp, msg):
    rec = _enclosure(_rec(), coll=[ENC_URI + "/Drives/0"])
    rec[key] = resp
    r = _storage(rec)
    assert any(msg in e["message"] for e in r["errs"])
    assert r["inv"]["incomplete"] is True and r["grand"] is None
    assert _serials(r) == ["S7R1NE0YB01553", "S7R1NE0YB01554"], "읽은 디스크 목록은 남는다"


def test_chassis_drives_collection_404_is_not_provided_not_failure():
    rec = _enclosure(_rec(), coll=[ENC_URI + "/Drives/0"])
    rec["get::" + ENC + "/Drives"] = [404, {}, "HTTP 404: Not Found"]
    r = _storage(rec)
    assert r["errs"] == [] and r["inv"] == {"enumerated": True, "incomplete": False} and r["grand"] == 2 * DISK_GIB


def test_advertised_drive_member_404_is_incomplete():
    """섀시가 가리킨 드라이브의 404 는 "가리킨 것을 못 읽음" — 선택 링크의 404(미제공)와 다르다."""
    rec = _rec()
    gone = ENC_URI + "/Drives/77"
    rec["get::" + ENC + "/Drives/77"] = [404, {}, "HTTP 404: Not Found"]
    _enclosure(rec, links=[gone])
    r = _storage(rec)
    assert any("Drive " + gone + " 실패" in e["message"] for e in r["errs"])
    assert r["inv"]["incomplete"] is True and r["grand"] is None


# ── 확인한 0 (SA-07) — 섀시가 비어 있다고 답함 ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("advert", ["links_empty", "collection_empty"])
def test_empty_storage_with_chassis_saying_no_drives_is_confirmed_zero(advert):
    """gen12_03: Storage 컬렉션 200 · 멤버 0. 원본 그대로면 원천이 없어 null 이다(시험 test_redfish_summary_null_rules). System 섀시가
    `Links.Drives: []` 나 멤버 0 인 Drives 컬렉션으로 "없다" 고 답하면 그것이 확인한 0 이다 — 전원 상태는 보지 않는다."""
    rec = _rec("real_hpe_dl380_gen12_03")
    assert rec["get::Systems/1/Storage"][1]["Members"] == []
    base = _storage(copy.deepcopy(rec))
    assert base["inv"] == {"enumerated": False, "incomplete": False} and base["grand"] is None
    body = rec["get::Chassis/1"][1]
    if advert == "links_empty":
        body["Links"]["Drives"] = []
    else:
        body["Drives"] = {"@odata.id": "/redfish/v1/Chassis/1/Drives"}
        rec["get::Chassis/1/Drives"] = [200, {"@odata.id": "/redfish/v1/Chassis/1/Drives", "Members": [], "Members@odata.count": 0}, None]
    r = _storage(rec)
    assert r["inv"] == {"enumerated": True, "incomplete": False} and r["grand"] == 0 and r["disks"] == []
    assert r["norm_notices"] == []
