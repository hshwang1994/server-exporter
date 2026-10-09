"""Jenkinsfile_portal_Byid — Jenkinsfile_portal 의 사본 (2026-10-09 사용자 결정: 유지하고 portal 과 맞춘다).

2026-10-08 GitLab 웹 편집으로 main 에 들어온 사본이다(DRIFT-019). 차이는 inventory_json 파라미터의 기본값 1줄뿐이어야 한다 —
portal 을 고치고 Byid 를 맞추지 않으면 이 시험이 실패한다. 결정: docs/ai/decisions/ADR-2026-10-09-portal-byid-copy.md
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PORTAL = REPO / "Jenkinsfile_portal"
BYID = REPO / "Jenkinsfile_portal_Byid"
UNIQUE = "            defaultValue: '[{\"bmc_ip\":\"\",\"by_id\":\"\"}]',"
ANCHOR = "            name        : 'inventory_json',"


def test_byid_is_portal_plus_its_inventory_default_line():
    portal = PORTAL.read_text(encoding="utf-8").split("\n")
    byid = BYID.read_text(encoding="utf-8").split("\n")
    assert byid.count(UNIQUE) == 1, "Byid 고유 줄(inventory_json 기본값)은 정확히 1개"
    i = byid.index(UNIQUE)
    assert byid[i - 1] == ANCHOR, "고유 줄은 inventory_json 파라미터 이름 바로 다음에 있다"
    assert byid[:i] + byid[i + 1:] == portal, "고유 줄을 빼면 Jenkinsfile_portal 과 같아야 한다 — portal 을 고쳤으면 Byid 도 맞춘다"


def test_byid_keeps_lf_line_endings_like_portal():
    assert b"\r" not in BYID.read_bytes(), "Jenkinsfile* 는 LF (.gitattributes) — 1566454a 에서 맞춘 줄끝"
    assert b"\r" not in PORTAL.read_bytes()
