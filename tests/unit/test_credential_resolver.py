"""Credential Resolver 순수 함수 단위 회귀 (2026-08-12).

설계 정본: docs/ai/contracts/vault-credential-resolver.md §4, §15.1

선택 Contract:
    OS      = location + os_type   (linux | windows)
    ESXi    = location
    Redfish = location + vendor    (canonical)
    Generation / Model / Firmware 는 **선택축이 아니다.**

이 파일이 잠그는 불변식:
    - 다른 Location / Vendor 로 넘어가는 경로가 나오지 않는다
    - 반환값에 Secret 이 없다
    - 미상 입력에 대해 경로를 **추측하지 않는다** (vault_relpath=None)
    - 후보 순서를 바꾸지 않는다
파일시스템을 건드리지 않으므로 fixture 없이 돈다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "module_utils"))

from credential_common import (  # noqa: E402
    OS_TYPES,
    REASON_RESOLVED,
    REASON_UNKNOWN_LOCATION,
    REASON_UNKNOWN_OS_TYPE,
    REASON_UNKNOWN_TARGET_TYPE,
    REASON_VENDOR_UNRESOLVED,
    REASONS,
    TARGET_TYPES,
    normalize_accounts,
    resolve_credential_scope,
)

LOCATIONS = ("ic", "chj", "yi")
VENDORS = ("dell", "hpe", "lenovo", "supermicro", "cisco",
           "huawei", "inspur", "fujitsu", "quanta")


def resolve(**kw):
    kw.setdefault("known_locations", LOCATIONS)
    kw.setdefault("known_vendors", VENDORS)
    return resolve_credential_scope(**kw)


# ── T1 / T3~T7: 정상 선택 ────────────────────────────────────────────────────
@pytest.mark.parametrize("kwargs,scope,relpath", [
    # T3 OS Linux
    (dict(location="ic", target_type="os", os_type="linux"),
     "ic/os/linux", "vault/ic/os/linux.yml"),
    # T4 OS Windows
    (dict(location="ic", target_type="os", os_type="windows"),
     "ic/os/windows", "vault/ic/os/windows.yml"),
    # T5 ESXi — 선택축이 location 하나뿐이라 2번째 경로 조각이 없다
    (dict(location="ic", target_type="esxi"),
     "ic/esxi", "vault/ic/esxi.yml"),
    # T6 Redfish Dell
    (dict(location="ic", target_type="redfish", vendor="dell"),
     "ic/redfish/dell", "vault/ic/redfish/dell.yml"),
    # T7 Redfish HPE
    (dict(location="ic", target_type="redfish", vendor="hpe"),
     "ic/redfish/hpe", "vault/ic/redfish/hpe.yml"),
    # 다른 Location 도 동일 규칙
    (dict(location="chj", target_type="redfish", vendor="lenovo"),
     "chj/redfish/lenovo", "vault/chj/redfish/lenovo.yml"),
    (dict(location="yi", target_type="os", os_type="linux"),
     "yi/os/linux", "vault/yi/os/linux.yml"),
])
def test_resolved_paths(kwargs, scope, relpath):
    r = resolve(**kwargs)
    assert r["reason"] == REASON_RESOLVED
    assert r["credential_scope"] == scope
    assert r["vault_relpath"] == relpath


def test_scope_and_relpath_agree():
    """`credential_scope` 는 경로에서 파생된 같은 정보여야 한다 (진단 신뢰성)."""
    for loc in LOCATIONS:
        for vendor in VENDORS:
            r = resolve(location=loc, target_type="redfish", vendor=vendor)
            assert r["vault_relpath"] == f"vault/{r['credential_scope']}.yml"


# ── T2: 존재하지 않는 Location ───────────────────────────────────────────────
@pytest.mark.parametrize("loc", ["nope", "IC_TYPO", "", None, "  ", "ic2"])
def test_unknown_location_makes_no_path(loc):
    r = resolve(location=loc, target_type="esxi")
    assert r["reason"] == REASON_UNKNOWN_LOCATION
    assert r["vault_relpath"] is None, "미등록 Location 에 경로를 추측해서 만들면 안 된다"
    assert r["credential_scope"] is None


def test_empty_known_locations_rejects_everything():
    """registry 가 비면 어떤 Location 도 통과하지 않는다 (fail closed)."""
    r = resolve_credential_scope("ic", "esxi", known_locations=(), known_vendors=VENDORS)
    assert r["reason"] == REASON_UNKNOWN_LOCATION
    assert r["vault_relpath"] is None


# ── T8: 지원하지 않는 Vendor ─────────────────────────────────────────────────
@pytest.mark.parametrize("vendor", ["unknown", "", None, "contoso", "Dell Inc.", "  "])
def test_vendor_unresolved_makes_no_path(vendor):
    r = resolve(location="ic", target_type="redfish", vendor=vendor)
    assert r["reason"] == REASON_VENDOR_UNRESOLVED
    assert r["vault_relpath"] is None
    assert r["credential_scope"] is None


def test_unknown_os_type():
    for bad in ("", None, "aix", "Linux2", "esxi"):
        r = resolve(location="ic", target_type="os", os_type=bad)
        assert r["reason"] == REASON_UNKNOWN_OS_TYPE
        assert r["vault_relpath"] is None


def test_unknown_target_type():
    for bad in ("", None, "bmc", "ipmi", "os_linux", "vsphere"):
        r = resolve(location="ic", target_type=bad)
        assert r["reason"] == REASON_UNKNOWN_TARGET_TYPE, f"{bad!r} → {r['reason']}"
        assert r["vault_relpath"] is None


def test_target_type_case_and_space_are_tolerated():
    """'OS ' 는 오타가 아니라 표기 차이다 — 정규화해서 받되 os_type 은 여전히 요구한다."""
    r = resolve(location="ic", target_type="OS ", os_type="LINUX")
    assert r["reason"] == REASON_RESOLVED
    assert r["vault_relpath"] == "vault/ic/os/linux.yml"


def test_os_channel_requires_os_type():
    """os 채널에서 os_type 을 빠뜨리면 linux 로 넘겨짚지 않는다."""
    r = resolve(location="ic", target_type="os")
    assert r["reason"] == REASON_UNKNOWN_OS_TYPE
    assert r["vault_relpath"] is None


# ── T15 / T16: Location · Vendor 격리 ────────────────────────────────────────
def test_location_isolation():
    """같은 vendor 라도 Location 이 다르면 다른 파일. 교차 참조가 없다."""
    a = resolve(location="ic", target_type="redfish", vendor="dell")
    b = resolve(location="chj", target_type="redfish", vendor="dell")
    assert a["vault_relpath"] != b["vault_relpath"]
    assert "chj" not in a["vault_relpath"]
    assert "ic" not in b["vault_relpath"]


def test_vendor_isolation():
    a = resolve(location="ic", target_type="redfish", vendor="dell")
    b = resolve(location="ic", target_type="redfish", vendor="hpe")
    assert a["vault_relpath"] != b["vault_relpath"]
    assert "hpe" not in a["vault_relpath"]
    assert "dell" not in b["vault_relpath"]


def test_result_never_carries_alternate_candidates():
    """결과에 '다음에 시도할 다른 경로' 같은 필드가 없어야 한다 (fallback 구조 부재)."""
    r = resolve(location="ic", target_type="redfish", vendor="dell")
    blob = json.dumps(r).lower()
    for word in ("fallback", "candidates", "alternate", "next_"):
        assert word not in blob, f"결과에 {word!r} 가 있다 — 교차 fallback 구조 의심"


def test_source_has_no_cross_scope_fallback():
    """구현 자체에 다른 Location/Vendor 로 넘어가는 반복 시도가 없는지 (정적)."""
    src = (REPO / "module_utils" / "credential_common.py").read_text(encoding="utf-8")
    body = "\n".join(
        line for line in src.splitlines()
        if not line.strip().startswith("#")
    )
    # 후보 목록을 순회하며 여러 경로를 만드는 구조가 있으면 안 된다.
    assert "for loc" not in body
    assert "fallback_profiles" not in body


# ── T17: Generation 불변 ─────────────────────────────────────────────────────
@pytest.mark.parametrize("generation_ish", [
    "14G", "15G", "16G", "17G", "iDRAC9", "7.10.30.00", "PowerEdge R760",
])
def test_generation_does_not_affect_selection(generation_ish):
    """세대/모델/펌웨어를 아무리 바꿔도 선택 결과가 같아야 한다.

    함수 시그니처에 그 축이 아예 없다는 것이 1차 증거이고, 여기서는
    호출자가 실수로 vendor 자리에 세대 문자열을 넣어도 경로를 만들지 않음을 본다.
    """
    base = resolve(location="ic", target_type="redfish", vendor="dell")
    assert base["vault_relpath"] == "vault/ic/redfish/dell.yml"

    wrong = resolve(location="ic", target_type="redfish", vendor=generation_ish)
    assert wrong["reason"] == REASON_VENDOR_UNRESOLVED
    assert wrong["vault_relpath"] is None


def test_signature_has_no_generation_axis():
    import inspect

    params = set(inspect.signature(resolve_credential_scope).parameters)
    for forbidden in ("generation", "model", "firmware", "version", "adapter_id"):
        assert forbidden not in params, f"선택축에 {forbidden} 이 들어왔다"


# ── T19: Secret 비노출 ───────────────────────────────────────────────────────
def test_result_contains_no_secret_keys():
    for kwargs in (
        dict(location="ic", target_type="os", os_type="linux"),
        dict(location="ic", target_type="esxi"),
        dict(location="ic", target_type="redfish", vendor="dell"),
    ):
        r = resolve(**kwargs)
        blob = json.dumps(r).lower()
        for word in ("password", "passwd", "username", "secret", "token"):
            assert word not in blob, f"resolver 결과에 {word!r} 가 있다"


def test_module_never_reads_files():
    """순수 함수 보장 — 파일/네트워크 접근 코드가 없어야 단위테스트가 fixture 없이 돈다."""
    src = (REPO / "module_utils" / "credential_common.py").read_text(encoding="utf-8")
    for forbidden in ("open(", "yaml.", "requests", "urllib", "subprocess", "os.path"):
        assert forbidden not in src, f"credential_common.py 에 {forbidden!r} 사용"


# ── 경로 안전성 ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("evil", [
    "../../etc", "ic/../chj", "ic/redfish", ".", "..", "ic ", "i c", "IC/",
])
def test_path_traversal_is_impossible_via_location(evil):
    r = resolve_credential_scope(
        evil, "esxi", known_locations=list(LOCATIONS) + [evil], known_vendors=VENDORS
    )
    # registry 가 오염돼 evil 값이 known 에 들어가더라도 경로 조각으로 못 쓴다.
    assert r["vault_relpath"] is None or ".." not in r["vault_relpath"]
    if r["vault_relpath"]:
        assert r["vault_relpath"].count("/") == 2


@pytest.mark.parametrize("evil", ["../hpe", "dell/../hpe", "dell ", "a/b"])
def test_path_traversal_is_impossible_via_vendor(evil):
    r = resolve_credential_scope(
        "ic", "redfish", known_locations=LOCATIONS,
        known_vendors=list(VENDORS) + [evil],
    )
    r2 = resolve_credential_scope(
        "ic", "redfish", known_locations=LOCATIONS,
        known_vendors=list(VENDORS) + [evil], vendor=evil,
    )
    for res in (r, r2):
        if res["vault_relpath"]:
            assert ".." not in res["vault_relpath"]


def test_case_and_whitespace_are_normalised():
    r = resolve(location="  IC ", target_type=" Redfish ", vendor=" Dell ")
    assert r["reason"] == REASON_RESOLVED
    assert r["vault_relpath"] == "vault/ic/redfish/dell.yml"


def test_reason_is_always_in_enum():
    for loc in ("ic", "bad"):
        for tt in ("os", "esxi", "redfish", "bad"):
            r = resolve(location=loc, target_type=tt, os_type="linux", vendor="dell")
            assert r["reason"] in REASONS


def test_selection_basis_records_the_axes_used():
    r = resolve(location="ic", target_type="redfish", vendor="dell")
    assert r["selection_basis"] == {
        "location": "ic", "target_type": "redfish", "vendor": "dell",
    }
    e = resolve(location="ic", target_type="esxi")
    assert "vendor" not in e["selection_basis"] and "os_type" not in e["selection_basis"]


def test_result_is_json_serialisable():
    json.dumps(resolve(location="ic", target_type="redfish", vendor="dell"))


# ── T20: 후보 순서 보존 (normalize_accounts) ─────────────────────────────────
def test_account_order_is_preserved_exactly():
    """vault 배열 순서 = 시도 순서. 재정렬은 이번 변경의 범위가 아니다."""
    accounts = [
        {"username": "u1", "password": "p1", "label": "l1", "role": "recovery"},
        {"username": "u2", "password": "p2", "label": "l2", "role": "primary"},
        {"username": "u3", "password": "p3", "label": "l3", "role": "secondary"},
    ]
    out = normalize_accounts({"accounts": accounts})
    assert [a["username"] for a in out] == ["u1", "u2", "u3"], (
        "recovery-first 입력을 primary-first 로 재정렬하면 안 된다 — "
        "인증 순서 변경은 Redfish reconcile 진입 조건까지 흔든다"
    )


def test_normalize_accounts_does_not_mutate_input():
    src = {"accounts": [{"username": "u1", "role": "primary"}]}
    out = normalize_accounts(src)
    out.append({"username": "injected"})
    assert len(src["accounts"]) == 1


def test_legacy_single_credential_compat():
    out = normalize_accounts({"ansible_user": "root", "ansible_password": "x"})
    assert len(out) == 1
    assert out[0]["username"] == "root"
    assert out[0]["role"] == "primary"
    assert out[0]["label"] == "legacy_single"


def test_accounts_take_precedence_over_legacy():
    out = normalize_accounts({
        "accounts": [{"username": "a", "role": "primary"}],
        "ansible_user": "legacy",
    })
    assert [a["username"] for a in out] == ["a"]


@pytest.mark.parametrize("bad", [None, [], "", 0, {"accounts": []}, {"accounts": "x"}])
def test_normalize_accounts_empty_inputs(bad):
    assert normalize_accounts(bad) == []


def test_no_sorting_code_in_normalizer():
    """정렬 코드가 들어오면 순서 계약이 깨진다 — 정적으로도 막는다."""
    src = (REPO / "module_utils" / "credential_common.py").read_text(encoding="utf-8")
    for forbidden in ("sorted(", ".sort(", "reverse=True"):
        assert forbidden not in src, f"credential_common.py 에 정렬 코드 {forbidden!r}"


# ── registry 와의 정합 ───────────────────────────────────────────────────────
def test_real_registry_locations_all_resolve():
    """실제 locations.yml 의 모든 Location 이 3채널에서 경로를 만든다."""
    data = yaml.safe_load(
        (REPO / "common" / "vars" / "locations.yml").read_text(encoding="utf-8")
    )
    locs = list(data["locations"].keys())
    aliases = yaml.safe_load(
        (REPO / "common" / "vars" / "vendor_aliases.yml").read_text(encoding="utf-8")
    )["vendor_aliases"]
    vendors = list(aliases.keys())

    for loc in locs:
        for os_type in OS_TYPES:
            r = resolve_credential_scope(loc, "os", locs, vendors, os_type=os_type)
            assert r["reason"] == REASON_RESOLVED
        assert resolve_credential_scope(loc, "esxi", locs, vendors)["reason"] == REASON_RESOLVED
        for v in vendors:
            r = resolve_credential_scope(loc, "redfish", locs, vendors, vendor=v)
            assert r["reason"] == REASON_RESOLVED, f"{loc}/{v} 해석 실패"


def test_target_types_match_channels():
    assert set(TARGET_TYPES) == {"os", "esxi", "redfish"}
    assert set(OS_TYPES) == {"linux", "windows"}
