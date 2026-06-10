"""빈 alias substring 매칭 가드.

배경: vendor_aliases.yml 에 빈 alias 키('')가 들어가면(오타/병합 사고) substring 매칭
`if alias in product` 가 **모든** 문자열에 매치돼(`'' in s` 는 항상 True) 잘못된 벤더로
오감지된다. 같은 함수의 OEM(L619)·Vendor(L635) 루프는 이미 `if alias` 가드가 있는데
Product(L643)·Name(L655)·_normalize_vendor_from_aliases(L510)만 누락 — 일관성 회복.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "redfish-gather" / "library"))
_b = types.ModuleType("ansible.module_utils.basic"); _b.AnsibleModule = object
_mu = types.ModuleType("ansible.module_utils"); _mu.basic = _b
_a = types.ModuleType("ansible"); _a.module_utils = _mu
sys.modules.setdefault("ansible", _a)
sys.modules.setdefault("ansible.module_utils", _mu)
sys.modules.setdefault("ansible.module_utils.basic", _b)

import redfish_gather as rg  # noqa: E402


def test_normalize_vendor_empty_alias_no_wildcard_match(monkeypatch):
    """빈 alias 가 임의 Manufacturer 를 잘못 매칭하면 안 됨."""
    monkeypatch.setattr(rg, "_load_vendor_aliases_file",
                        lambda: {"": "evilvendor", "dell inc.": "dell"})
    assert rg._normalize_vendor_from_aliases("totally unknown brand xyz") != "evilvendor"
    # 정상 매칭 불변
    assert rg._normalize_vendor_from_aliases("dell inc.") == "dell"


def test_detect_vendor_empty_alias_product_no_wildcard(monkeypatch):
    """ServiceRoot.Product 경로에서 빈 alias wildcard 매칭 방어."""
    monkeypatch.setattr(rg, "_load_vendor_aliases_file",
                        lambda: {"": "evilvendor", "idrac": "dell"})
    assert rg._detect_vendor_from_service_root({"Product": "SomeRandomServerXYZ"}) != "evilvendor"


def test_detect_vendor_empty_alias_name_no_wildcard(monkeypatch):
    """ServiceRoot.Name 경로에서 빈 alias wildcard 매칭 방어."""
    monkeypatch.setattr(rg, "_load_vendor_aliases_file",
                        lambda: {"": "evilvendor", "cisco": "cisco"})
    assert rg._detect_vendor_from_service_root({"Name": "Generic RESTful Root"}) != "evilvendor"


def test_detect_vendor_normal_product_match_unchanged(monkeypatch):
    """정상 alias 매칭 불변 (idrac → dell)."""
    monkeypatch.setattr(rg, "_load_vendor_aliases_file", lambda: {"idrac": "dell"})
    assert rg._detect_vendor_from_service_root({"Product": "Integrated Dell Remote Access (iDRAC)"}) == "dell"
