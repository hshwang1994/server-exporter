"""ADR-2026-05-12 회귀 — `_resolve_all_member_uris` 단위 테스트 (cycle 2026-05-12).

`_resolve_first_member_uri` 의 Additive 확장. RMC (HPE CSUS 3200 / Superdome Flex)
단일 진입점이 N개 Manager / N개 nPartition / N개 Chassis 노출 환경에서 전수 수집.

검증 항목:
1. collection URI 없음 → ([], None, 'collection uri 없음')
2. HTTP fail → ([], st, err)
3. Members 비어있음 → ([], st, 'members 없음')
4. Members N개 → list of {uri, id} (ID = URI 마지막 segment, trailing '/' 제거)
5. @odata.id 누락 Member 는 skip
6. 기존 `_resolve_first_member_uri` 행동 보존 (Additive 검증)
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

_stub_basic = types.ModuleType("ansible.module_utils.basic")
_stub_basic.AnsibleModule = object
_stub_module_utils = types.ModuleType("ansible.module_utils")
_stub_module_utils.basic = _stub_basic
_stub_ansible = types.ModuleType("ansible")
_stub_ansible.module_utils = _stub_module_utils
sys.modules.setdefault("ansible", _stub_ansible)
sys.modules.setdefault("ansible.module_utils", _stub_module_utils)
sys.modules.setdefault("ansible.module_utils.basic", _stub_basic)

import redfish_gather as rg  # noqa: E402


def _patch_get(monkeypatch, response_map: dict) -> None:
    """`rg._get` 를 in-memory mock 으로 치환.

    response_map: {path: (status, data, err)}
    """
    def fake_get(bmc_ip, path, username, password, timeout, verify_ssl):
        # `_p()` 가 /redfish/v1/ prefix 를 제거해서 path 전달 — mock key 도 동일하게.
        if path in response_map:
            return response_map[path]
        return 404, None, f"path not mocked: {path}"
    monkeypatch.setattr(rg, "_get", fake_get)


# ── _resolve_all_member_uris ─────────────────────────────────────────────────


def test_resolve_all_no_collection_uri() -> None:
    """coll_uri=None 시 즉시 ([], None, 'collection uri 없음')."""
    members, st, err = rg._resolve_all_member_uris(
        "10.0.0.1", None, "u", "p", 10, False,
    )
    assert members == []
    assert st is None
    assert "없음" in err


def test_resolve_all_http_fail(monkeypatch) -> None:
    """HTTP fail (예: 401) → ([], 401, 'HTTP 401')."""
    _patch_get(monkeypatch, {
        "Managers": (401, None, None),
    })
    members, st, err = rg._resolve_all_member_uris(
        "10.0.0.1", "/redfish/v1/Managers", "u", "p", 10, False,
    )
    assert members == []
    assert st == 401
    assert err == "HTTP 401"


def test_resolve_all_members_empty(monkeypatch) -> None:
    """Members 컬렉션 비어있음 → ([], 200, 'members 없음')."""
    _patch_get(monkeypatch, {
        "Managers": (200, {"Members": []}, None),
    })
    members, st, err = rg._resolve_all_member_uris(
        "10.0.0.1", "/redfish/v1/Managers", "u", "p", 10, False,
    )
    assert members == []
    assert st == 200
    assert err == "members 없음"


def test_resolve_all_members_n_extracted(monkeypatch) -> None:
    """Members N개 → 모두 추출 (id = URI 마지막 segment)."""
    _patch_get(monkeypatch, {
        "Managers": (200, {
            "Members": [
                {"@odata.id": "/redfish/v1/Managers/RMC"},
                {"@odata.id": "/redfish/v1/Managers/PDHC0"},
                {"@odata.id": "/redfish/v1/Managers/PDHC1"},
                {"@odata.id": "/redfish/v1/Managers/Bay1.iLO5/"},  # trailing '/'
            ]
        }, None),
    })
    members, st, err = rg._resolve_all_member_uris(
        "10.0.0.1", "/redfish/v1/Managers", "u", "p", 10, False,
    )
    assert st == 200
    assert err is None
    assert len(members) == 4
    ids = [m["id"] for m in members]
    assert ids == ["RMC", "PDHC0", "PDHC1", "Bay1.iLO5"]
    uris = [m["uri"] for m in members]
    assert "/redfish/v1/Managers/RMC" in uris


def test_resolve_all_members_odata_id_missing_skipped(monkeypatch) -> None:
    """@odata.id 누락 Member 는 skip."""
    _patch_get(monkeypatch, {
        "Systems": (200, {
            "Members": [
                {"@odata.id": "/redfish/v1/Systems/Partition0"},
                {"foo": "bar"},  # @odata.id 누락
                {"@odata.id": "/redfish/v1/Systems/Partition1"},
            ]
        }, None),
    })
    members, _, _ = rg._resolve_all_member_uris(
        "10.0.0.1", "/redfish/v1/Systems", "u", "p", 10, False,
    )
    assert len(members) == 2
    assert [m["id"] for m in members] == ["Partition0", "Partition1"]


# ── 기존 `_resolve_first_member_uri` 행동 보존 (Additive 검증) ──────────────


def test_resolve_first_member_uri_unchanged(monkeypatch) -> None:
    """기존 함수 변경 0 — 첫 번째 Member 만 반환."""
    _patch_get(monkeypatch, {
        "Managers": (200, {
            "Members": [
                {"@odata.id": "/redfish/v1/Managers/RMC"},
                {"@odata.id": "/redfish/v1/Managers/PDHC0"},
            ]
        }, None),
    })
    uri, st, err = rg._resolve_first_member_uri(
        "10.0.0.1", "/redfish/v1/Managers", "u", "p", 10, False,
    )
    assert uri == "/redfish/v1/Managers/RMC"
    assert st == 200
    assert err is None
