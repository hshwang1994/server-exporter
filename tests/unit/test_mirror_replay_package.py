"""tests/redfish-probe/mirror_replay 패키지의 재생 정책 단위 시험 (2026-10-27, FIX 8 편입).

Tier 1(HTTPS 서버)과 Tier 2(in-process)가 같이 쓰는 mirror_policy.Mirror 의 정책을 합성 v2 미러 트리로 고정한다:
익명은 ServiceRoot/odata/$metadata 만 · 그 밖은 401(+realm) · 인증은 Basic 사용자 이름만 · 미러 밖 404 · timeout 은 hang(status 0).
네트워크 0, 저장소 파일 변경 0.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "redfish-probe"))
from mirror_replay import mirror_policy as MP  # noqa: E402

ROOT = {"@odata.id": "/redfish/v1", "@odata.type": "#ServiceRoot.v1_15_0.ServiceRoot", "Id": "RootService",
        "RedfishVersion": "1.15.0", "Vendor": "Lenovo", "Systems": {"@odata.id": "/redfish/v1/Systems"}}
SYSTEMS = {"@odata.id": "/redfish/v1/Systems", "Members": [{"@odata.id": "/redfish/v1/Systems/1"}], "Members@odata.count": 1}
SYSTEM = {"@odata.id": "/redfish/v1/Systems/1", "Id": "1", "Manufacturer": "Lenovo", "Model": "ThinkSystem SR650 V4"}


def _put(tree: Path, rel: str, body: dict, status: int = 200):
    d = tree / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.json").write_text(json.dumps(body), encoding="utf-8")
    (d / "headers.json").write_text(json.dumps({"_status": status, "Content-Type": "application/json", "ETag": "W/\"x\""}),
                                    encoding="utf-8")


@pytest.fixture
def tree(tmp_path):
    t = tmp_path / "m"
    _put(t, "redfish/v1", ROOT)
    _put(t, "redfish/v1/Systems", SYSTEMS)
    _put(t, "redfish/v1/Systems/1", SYSTEM)
    (t / "redfish" / "index.json").write_text(json.dumps({"v1": "/redfish/v1/"}), encoding="utf-8")
    (t / "_fsmap.json").write_text(json.dumps({"fsmap_schema": 1, "paths": {
        "/redfish/v1": {"dir": "redfish/v1", "type": "json"},
        "/redfish/v1/Systems": {"dir": "redfish/v1/Systems", "type": "json"},
        "/redfish/v1/Systems/1": {"dir": "redfish/v1/Systems/1", "type": "json"}}}), encoding="utf-8")
    (t / "_manifest.json").write_text(json.dumps({
        "realm": 'Basic realm="Lenovo XClarity Controller"',
        "device_error": [{"path": "/redfish/v1/Managers/1/LogServices/Slow", "status": 0, "cause": "timeout"}],
        "absent": [{"path": "/redfish/v1/Systems/1/Bios", "status": 404}]}), encoding="utf-8")
    return t


def test_anonymous_gets_only_service_root_and_401_with_realm_elsewhere(tree):
    m = MP.Mirror(tree)
    st, hs, body, note = m.lookup("", authed=False)
    assert st == 200 and json.loads(body)["Vendor"] == "Lenovo" and note == "tree"
    st, hs, body, note = m.lookup("Systems/1", authed=False)
    assert st == 401 and note == "anon-denied" and hs.get("WWW-Authenticate", "").startswith("Basic realm=")
    st, hs, body, note = m.lookup("Systems/1", authed=True)
    assert st == 200 and json.loads(body)["Model"] == "ThinkSystem SR650 V4"


def test_unknown_path_is_404_and_timeout_is_hang(tree):
    m = MP.Mirror(tree)
    assert m.lookup("Chassis/9", authed=True)[0] == 404
    assert m.lookup("Managers/1/LogServices/Slow", authed=True)[0] == 0           # hang: 서버는 응답 없이 연결을 닫는다
    st, data, err = m.module_response("Managers/1/LogServices/Slow", authed=True)
    assert st == 0 and err.startswith("Timeout")                                   # Tier 2 는 timeout 오류로 돌려준다
    st, data, err = m.module_response("Systems/1/Bios", authed=True)
    assert st == 404 and err.startswith("HTTP 404")                                # manifest 의 absent 는 기록된 상태코드


def test_module_response_matches_get_impl_contract(tree):
    m = MP.Mirror(tree)
    st, data, err = m.module_response("Systems", authed=True)
    assert (st, err) == (200, None) and data["Members@odata.count"] == 1
    st, data, err = m.module_response("Systems", authed=False)
    assert st == 401 and err.startswith("HTTP 401")                                # 익명은 ServiceRoot 밖에서 401
    st, data, err = m.module_response("", authed=False)
    assert st == 200 and data["Id"] == "RootService"


def test_repo_root_is_derived_from_file_location():
    assert MP.REPO == REPO, "저장소 루트는 파일 위치 기준(SE_REPO_ROOT 로만 덮어쓰기) — 개인 경로 하드코딩 금지"
