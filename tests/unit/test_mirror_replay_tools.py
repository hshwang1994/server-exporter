"""replay_full_mirror / convert_dmtf_mockup 회귀 - 캡처(미러 트리) -> 변환 -> 재생 과정에서 데이터가 손실되거나 상태가 바뀌지 않는다.

검증 항목:
  1. 페이지로 나뉜 컬렉션: 마지막 페이지만 남던 문제(실측 DellSensors 62개 중 12개) - v1 / v2 트리 모두 62개 전부 재생.
  2. gather 의 실제 순회(_collection_walk)가 재생 맵에서 멤버를 누락하거나 중복하지 않는다.
  3. 페이지 수 / 멤버 수가 선언(Members@odata.count)과 다르거나 사슬이 끊기면 조용히 넘기지 않고 stats 에 기록한다.
  4. headers.json 의 HTTP 상태를 보존한다 - 오류 본문을 200 으로 되살리지 않는다 (200 / 204 / 400 / 401 / 403 / 404 / 405 / 500).
  5. 비-JSON / 바이너리 안내 파일은 건너뛰고 세고, v1 트리 / v2 manifest / DMTF mockup 이 모두 읽힌다.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for sub in ("tests/redfish-probe", "tests/integration"):
    if str(REPO / sub) not in sys.path:
        sys.path.insert(0, str(REPO / sub))

import replay_full_mirror as rep  # noqa: E402
import convert_dmtf_mockup as conv  # noqa: E402

SENSORS = "/redfish/v1/Chassis/1/Sensors"
PAGE2_QUERY = "$skip=50&$top=50"


def _put(tree, rel, body, status=200):
    d = tree.joinpath(*rel.split("/")) if rel else tree
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.json").write_text(json.dumps(body), encoding="utf-8")
    (d / "headers.json").write_text(json.dumps({"_status": status}), encoding="utf-8")


def _members(lo, hi):
    return [{"@odata.id": "%s/S%d" % (SENSORS, i)} for i in range(lo, hi)]


def _paged_tree(tmp_path, v2, total=62, declared=None, with_page2=True):
    """Dell 처럼 후속 페이지 본문의 @odata.id 가 컬렉션 id 그대로인 트리 (v1: 디렉터리명으로만 구분, v2: _fsmap.json)."""
    tree = tmp_path / ("v2" if v2 else "v1")
    root = {"@odata.id": "/redfish/v1", "Chassis": {"@odata.id": "/redfish/v1/Chassis"}}
    page1 = {"@odata.id": SENSORS, "Members@odata.count": total if declared is None else declared,
             "Members": _members(0, 50), "Members@odata.nextLink": "%s?%s" % (SENSORS, PAGE2_QUERY)}
    page2 = {"@odata.id": SENSORS, "Members@odata.count": total, "Members": _members(50, total)}
    _put(tree, "redfish/v1", root)
    _put(tree, "redfish/v1/Chassis/1/Sensors", page1)
    page2_dir = "redfish/v1/Chassis/1/Sensors_" + PAGE2_QUERY
    if with_page2:
        _put(tree, page2_dir, page2)
    if v2:
        paths = {"/redfish/v1": {"dir": "redfish/v1", "type": "json"},
                 SENSORS: {"dir": "redfish/v1/Chassis/1/Sensors", "type": "json"}}
        if with_page2:
            paths["%s?%s" % (SENSORS, PAGE2_QUERY)] = {"dir": page2_dir, "type": "json"}
        (tree / "_fsmap.json").write_text(json.dumps({"fsmap_schema": 1, "paths": paths}), encoding="utf-8")
    return tree


def _use_map(monkeypatch, rmap):
    """재생 transport 를 시험 안에서만 꽂는다 (replay.install_fakes 는 되돌릴 수 없다)."""
    def fake_get(bmc_ip, path, username, password, timeout, verify_ssl):
        return rmap.get(path, (404, {}, "HTTP 404: Not Found"))
    monkeypatch.setattr(rep.rg, "_get", fake_get)


@pytest.mark.parametrize("v2", [False, True])
def test_paginated_collection_keeps_every_page(tmp_path, v2):
    rmap, root, stats = rep.build_response_map(_paged_tree(tmp_path, v2))
    page2_key = "Chassis/1/Sensors?" + PAGE2_QUERY
    assert len(rmap["Chassis/1/Sensors"][1]["Members"]) == 50          # 1페이지가 마지막 페이지로 덮이지 않는다
    assert len(rmap[page2_key][1]["Members"]) == 12                    # 2페이지는 ?쿼리 로 구분된 자기 키를 갖는다
    assert root is not None and "Members" not in root
    assert stats["pages"] == [{"collection": "Chassis/1/Sensors", "pages": 2, "members": 62, "declared": 62,
                               "cut": None, "match": True}]
    assert stats["page_mismatch"] == [] and stats["dupes"] == []


@pytest.mark.parametrize("v2", [False, True])
def test_gather_collection_walk_gets_all_62_members_without_loss_or_duplicates(tmp_path, monkeypatch, v2):
    rmap, _root, _stats = rep.build_response_map(_paged_tree(tmp_path, v2))
    _use_map(monkeypatch, rmap)
    _st, first, _err = rep.rg._get("10.0.0.1", "Chassis/1/Sensors", "u", "p", 10, False)
    members, state = rep.rg._collection_walk("10.0.0.1", "Chassis/1/Sensors", first, "u", "p", 10, False)
    ids = [m["@odata.id"] for m in members]
    assert ids == ["%s/S%d" % (SENSORS, i) for i in range(62)]         # 62개 모두, 순서 그대로, 중복 없음
    assert state["pages"] == 2 and state["cut"] is None and state["duplicates"] == 0


def test_count_difference_and_broken_chain_are_recorded_not_dropped(tmp_path):
    # 살아 있는 로그: 1페이지가 선언한 개수(100)와 실제로 받은 멤버 수(62)가 다르다
    _rmap, _root, stats = rep.build_response_map(_paged_tree(tmp_path / "a", True, declared=100))
    [rec] = stats["page_mismatch"]
    assert (rec["collection"], rec["pages"], rec["members"], rec["declared"], rec["match"], rec["cut"]) == (
        "Chassis/1/Sensors", 2, 62, 100, False, None)
    # 후속 페이지 파일이 없다 -> 사슬이 끊겼음을 기록
    _rmap, _root, stats = rep.build_response_map(_paged_tree(tmp_path / "b", True, with_page2=False))
    [rec] = stats["page_mismatch"]
    assert rec["cut"] == "missing_page" and rec["pages"] == 1 and rec["members"] == 50


def test_pre_fix_behavior_would_have_lost_pages_regression_guard(tmp_path):
    """v1 트리에서 본문 @odata.id 로만 키잉하면 2페이지가 1페이지를 덮어 12개만 남는다 - 이 시험이 그 사례를 고정한다."""
    tree = _paged_tree(tmp_path, False)
    keyed_by_id = {}
    for fp in sorted(tree.rglob("index.json")):
        body = json.loads(fp.read_text(encoding="utf-8"))
        keyed_by_id[rep.rg._p(body["@odata.id"])] = body          # 종전 키잉 방식
    assert len(keyed_by_id["Chassis/1/Sensors"]["Members"]) == 12  # DellSensors 62 중 12
    rmap, _root, _stats = rep.build_response_map(tree)
    assert len(rmap["Chassis/1/Sensors"][1]["Members"]) + len(
        rmap["Chassis/1/Sensors?" + PAGE2_QUERY][1]["Members"]) == 62


STATUS_CASES = [(200, "Ok"), (204, "Nothing"), (400, "Bad"), (401, "NoLogin"), (403, "Forbidden"),
                (404, "Gone"), (405, "NoGet"), (500, "Boom")]


def _status_tree(tmp_path):
    """상태가 섞인 트리. 오류 본문은 @odata.id 가 없는 것과 있는 것(과거 변환기가 200 으로 되살리던 경우)을 둘 다 둔다."""
    tree = tmp_path / "statuses"
    _put(tree, "redfish/v1", {"@odata.id": "/redfish/v1"})
    _put(tree, "redfish/v1/Ok", {"@odata.id": "/redfish/v1/Ok", "Name": "fine"})
    _put(tree, "redfish/v1/Nothing", {"_empty": True, "_path": "/redfish/v1/Nothing"}, 204)
    _put(tree, "redfish/v1/Bad", {"@odata.id": "/redfish/v1/Bad", "error": {"code": "BadRequest"}}, 400)
    _put(tree, "redfish/v1/NoLogin", {"error": {"code": "NoValidSession"}}, 401)
    _put(tree, "redfish/v1/Forbidden", {"error": {"code": "InsufficientPrivilege"}}, 403)
    _put(tree, "redfish/v1/Gone", {"error": {"code": "ResourceNotFound"}}, 404)
    _put(tree, "redfish/v1/NoGet", {"error": {"code": "MethodNotAllowed"}}, 405)
    _put(tree, "redfish/v1/Boom", {"@odata.id": "/redfish/v1/Boom", "error": {"code": "InternalError"}}, 500)
    return tree


@pytest.mark.parametrize("status,name", STATUS_CASES)
def test_http_status_is_preserved_by_replay_and_convert(tmp_path, status, name):
    tree = _status_tree(tmp_path)
    rmap, _root, _stats = rep.build_response_map(tree)
    code, body, err = rmap[name]
    assert code == status                                              # 오류 본문을 200 으로 올리지 않는다
    assert (err is None) == (200 <= status < 300)
    if status >= 300:
        assert err == "HTTP %d: %s" % (status, rep._reason(status))
    if status == 204:
        assert body == {}                                              # 빈 응답 표식은 빈 본문으로
    full, n_files, _skipped = conv._load_mockup(tree)
    assert full["get::" + name] == [status, body, err] and n_files == len(STATUS_CASES) + 1
    get_impl, _noauth, _realm, used = conv._instrumented_replayer(full)
    assert get_impl("ip", name, "u", "p", 5, False)[0] == status         # recording.json 이 되는 재생 응답도 같은 상태
    assert used["get::" + name][0] == status


def test_convert_root_is_registered_for_noauth_and_auth(tmp_path):
    full, _n, _s = conv._load_mockup(_status_tree(tmp_path))
    assert full["noauth::"] == full["get::"] and full["get::"][0] == 200


def test_non_json_and_binary_stubs_are_skipped_and_counted(tmp_path):
    tree = _status_tree(tmp_path)
    _put(tree, "redfish/v1/Schema", {"_non_json": True, "_path": "/redfish/v1/Schema", "_raw_file": "raw.xml",
                                      "_bytes": 3, "_sha256": "00"})
    (tree / "redfish" / "v1" / "Schema" / "raw.xml").write_bytes(b"<x/>")
    bad = tree / "redfish" / "v1" / "Binary"
    bad.mkdir()
    (bad / "index.json").write_bytes(b"\xff\xfe not utf-8 \x00")           # 읽을 수 없는 파일도 도구가 죽지 않는다
    rmap, _root, stats = rep.build_response_map(tree)
    assert "Schema" not in rmap and "Binary" not in rmap
    assert stats["non_json"] == 1 and stats["skipped"] >= 1
    full, _n, skipped = conv._load_mockup(tree)
    assert "get::Schema" not in full and skipped >= 2


def test_v2_manifest_restores_non_2xx_statuses_and_ignores_transport_failures(tmp_path):
    tree = tmp_path / "t"
    _put(tree, "redfish/v1", {"@odata.id": "/redfish/v1"})
    _put(tree, "redfish/v1/Ok", {"@odata.id": "/redfish/v1/Ok"})
    manifest = {"manifest_schema": 2,
                "absent": [{"path": "/redfish/v1/Missing", "status": 404}],
                "outside_account": [{"path": "/redfish/v1/Secret", "status": 403}],
                "not_gettable": [{"path": "/redfish/v1/Act/Reset", "status": 405}],
                "rejected": [{"path": "/redfish/v1/Odd", "status": 400}],
                "device_error": [{"path": "/redfish/v1/Hang", "status": 0}, {"path": "/redfish/v1/Boom", "status": 500}],
                "wellknown": [{"path": "/redfish/v1/$metadata", "status": 404, "bucket": "absent", "saved": False}]}
    (tree / "_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    rmap, _root, stats = rep.build_response_map(tree)
    assert dict((k, v[0]) for k, v in rmap.items() if k not in ("", "Ok")) == {
        "Missing": 404, "Secret": 403, "Act/Reset": 405, "Odd": 400, "Boom": 500, "$metadata": 404}
    assert "Hang" not in rmap and stats["from_manifest"] == 6          # 응답이 없던 전송 실패는 HTTP 상태가 아니다
    assert rmap["Missing"][1] == {}                                    # 본문을 만들어 채우지 않는다


def test_v1_manifest_failed_lists_and_status0_files_are_handled(tmp_path):
    tree = tmp_path / "t"
    _put(tree, "redfish/v1", {"@odata.id": "/redfish/v1"})
    _put(tree, "redfish/v1/Timeout", {}, 0)                             # v1 이 전송 실패를 status 0 으로 남긴 파일
    (tree / "_manifest.json").write_text(json.dumps({
        "failed": [{"path": "/redfish/v1/Gone", "status": 404, "error": "HTTP 404"}],
        "auth_failures": [{"path": "/redfish/v1/Locked", "status": 403}]}), encoding="utf-8")
    rmap, _root, _stats = rep.build_response_map(tree)
    assert "Timeout" not in rmap
    assert (rmap["Gone"][0], rmap["Locked"][0]) == (404, 403)


def test_dmtf_mockup_without_headers_or_manifest_still_loads(tmp_path):
    tree = tmp_path / "mockup"
    (tree).mkdir()
    (tree / "index.json").write_text(json.dumps({"@odata.id": "/redfish/v1/", "Product": "Contoso"}), encoding="utf-8")
    _put(tree, "Systems/1", {"@odata.id": "/redfish/v1/Systems/1"})
    (tree / "Systems" / "1" / "headers.json").unlink()                      # DMTF mockup 에는 headers.json 이 없다
    full, n_files, skipped = conv._load_mockup(tree)
    assert full["noauth::"][0] == 200 and full["get::Systems/1"] == [200, {"@odata.id": "/redfish/v1/Systems/1"}, None]
    assert n_files == 2 and skipped == 0


def test_v2_alias_request_path_is_kept_even_when_body_id_differs(tmp_path):
    """링크가 가리킨 요청 경로와 장비가 돌려준 본문의 @odata.id 가 다른 별칭(실측 Dell FirmwareInventory 하위 62개):
    v2 트리는 _fsmap.json 의 요청 경로로 키잉하므로 별칭 경로가 재생에서 사라지지 않는다."""
    tree = tmp_path / "alias"
    _put(tree, "redfish/v1", {"@odata.id": "/redfish/v1"})
    nested = "redfish/v1/Inv/Current-1/Oem/Dell/DellSoftwareInventory/DCIM_CURRENT_1"
    canon = "/redfish/v1/Inv/Oem/Dell/DellSoftwareInventory/DCIM:CURRENT_1"
    _put(tree, nested, {"@odata.id": canon, "Version": "2.41"})
    request_path = "/redfish/v1/Inv/Current-1/Oem/Dell/DellSoftwareInventory/DCIM:CURRENT_1"
    (tree / "_fsmap.json").write_text(json.dumps({"fsmap_schema": 1, "paths": {
        "/redfish/v1": {"dir": "redfish/v1", "type": "json"}, request_path: {"dir": nested, "type": "json"}}}),
        encoding="utf-8")
    rmap, _root, _stats = rep.build_response_map(tree)
    assert rmap["Inv/Current-1/Oem/Dell/DellSoftwareInventory/DCIM:CURRENT_1"][1]["Version"] == "2.41"
    assert "Inv/Oem/Dell/DellSoftwareInventory/DCIM:CURRENT_1" not in rmap      # 장비에 묻지 않은 경로를 지어내지 않는다


def test_key_of_only_accepts_paths_under_redfish_v1():
    k = rep._key_of
    assert k("/redfish/v1") == "" and k("/redfish/v1/") == "" and k("https://bmc/redfish/v1/") == ""
    assert k("/redfish/v1/Systems/1") == "Systems/1" and k("https://bmc/redfish/v1/Systems/1?$skip=5") == "Systems/1?$skip=5"
    for outside in ("/redfish", "/html/login.html", "/rest/v1/Systems", "Systems/1", "", None, 5):
        assert k(outside) is None, outside                              # 다른 리소스와 충돌할 수 있는 키를 만들지 않는다


def test_v2_dirs_are_looked_up_case_insensitively_like_an_ntfs_extraction(tmp_path):
    """Windows(NTFS)에 풀면 중간 폴더 대소문자가 합쳐져 디스크의 폴더 이름과 _fsmap.json 의 dir 대소문자가 어긋난다.
    크롤러는 대소문자를 무시해도 유일하게 저장하므로, 재생기는 소문자 기준으로 조회해 별칭 경로를 잃지 않아야 한다."""
    tree = tmp_path / "ntfs"
    _put(tree, "redfish/v1", {"@odata.id": "/redfish/v1"})
    body = {"@odata.id": "/redfish/v1/Systems/1/hpsut", "Name": "sut"}
    # 디스크에는 두 폴더 모두 중간 폴더가 Systems 로 합쳐져 있다
    _put(tree, "redfish/v1/Systems/1/hpsut", body)                  # fsmap 상으로는 소문자 별칭 요청의 폴더
    _put(tree, "redfish/v1/Systems/1/hpsut~f61d0d9c", body)         # 정식 경로 요청의 폴더
    (tree / "_fsmap.json").write_text(json.dumps({"fsmap_schema": 1, "paths": {
        "/redfish/v1": {"dir": "redfish/v1", "type": "json"},
        "/redfish/v1/systems/1/hpsut": {"dir": "redfish/v1/systems/1/hpsut", "type": "json"},
        "/redfish/v1/Systems/1/hpsut": {"dir": "redfish/v1/Systems/1/hpsut~f61d0d9c", "type": "json"}}}),
        encoding="utf-8")
    rmap, _root, stats = rep.build_response_map(tree)
    assert "systems/1/hpsut" in rmap and "Systems/1/hpsut" in rmap      # 두 요청 경로가 각자의 키로 살아 있다
    assert stats["dupes"] == []
