"""Vault sudo 비밀번호 후보 정규화 (2026-10-13) — module_utils/credential_common.normalize_sudo_passwords.

무엇을 고정하나
  - `sudo_passwords` 목록 순서 = 시도 순서. 같은 값은 처음 항목만 남긴다(같은 비밀번호를 두 번 보내 PAM 실패를 두 번 쌓지 않는다).
  - 목록이 없으면 레거시 `ansible_become_password` 1개. 둘 다 없으면 []. 입력이 dict 가 아니어도 예외 없이 [].
  - 값은 다듬지 않는다(C10 과 같다). None / 빈 값 / bool / 비-스칼라는 버린다. 숫자 0 도 값이다.
  - 로더(common/tasks/credential/resolve_and_load.yml)는 필터 한 곳에 위임하고 no_log 를 지킨다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO), str(REPO / "module_utils"), str(REPO / "filter_plugins")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from credential_common import SUDO_LEGACY_LABEL, normalize_sudo_passwords  # noqa: E402


def _labels(items):
    return [(i["label"], i["role"], i["password"]) for i in items]


def test_list_order_labels_and_roles_are_preserved():
    out = normalize_sudo_passwords({"sudo_passwords": [
        {"label": "sudo_primary", "role": "primary", "password": "one"},
        {"label": "sudo_fallback1", "role": "secondary", "password": "two"},
    ]})
    assert _labels(out) == [("sudo_primary", "primary", "one"), ("sudo_fallback1", "secondary", "two")]
    assert all(set(i) == {"password", "label", "role"} for i in out), "username 은 없다 — sudo 는 계정을 고르지 않는다"


def test_duplicate_values_keep_only_the_first():
    out = normalize_sudo_passwords({"sudo_passwords": [
        {"label": "a", "password": "same"}, {"label": "b", "password": "same"}, {"label": "c", "password": "other"},
    ]})
    assert [i["label"] for i in out] == ["a", "c"]


@pytest.mark.parametrize("bad", [None, "", "   ", True, False, {"nested": 1}, ["x"]])
def test_empty_bool_and_non_scalar_passwords_are_dropped(bad):
    out = normalize_sudo_passwords({"sudo_passwords": [{"label": "bad", "password": bad}, {"label": "ok", "password": "v"}]})
    assert [i["label"] for i in out] == ["ok"]


def test_scalar_items_get_default_labels_and_roles():
    out = normalize_sudo_passwords({"sudo_passwords": ["p1", "p2", 0]})
    assert _labels(out) == [("sudo_1", "primary", "p1"), ("sudo_2", "secondary", "p2"), ("sudo_3", "secondary", "0")]


def test_values_are_not_trimmed():
    out = normalize_sudo_passwords({"sudo_passwords": [{"password": " pw "}]})
    assert out[0]["password"] == " pw "


def test_legacy_single_become_password():
    out = normalize_sudo_passwords({"ansible_become_password": "legacy"})
    assert _labels(out) == [(SUDO_LEGACY_LABEL, "primary", "legacy")]


def test_list_wins_over_legacy_and_empty_list_falls_back():
    assert [i["password"] for i in normalize_sudo_passwords({"sudo_passwords": [{"password": "L"}], "ansible_become_password": "old"})] == ["L"]
    assert [i["password"] for i in normalize_sudo_passwords({"sudo_passwords": [], "ansible_become_password": "old"})] == ["old"]
    assert normalize_sudo_passwords({"sudo_passwords": [{"password": ""}], "ansible_become_password": "old"}) == [], \
        "목록이 있으면(비어 있지 않으면) 목록만 본다 — 전부 버려져도 레거시로 돌아가지 않는다"


@pytest.mark.parametrize("data", [None, "text", 7, [], {"sudo_passwords": "oops"}, {"ansible_become_password": ""}])
def test_missing_or_malformed_input_is_empty_without_raising(data):
    assert normalize_sudo_passwords(data) == []


def test_role_default_first_primary_then_secondary_and_explicit_kept():
    out = normalize_sudo_passwords({"sudo_passwords": [{"password": "a"}, {"password": "b", "role": " recovery "}, {"password": "c"}]})
    assert [i["role"] for i in out] == ["primary", "recovery", "secondary"]


def test_filter_plugin_delegates_to_the_single_implementation():
    from credential_accounts import FilterModule, credential_sudo_passwords  # noqa: PLC0415
    assert "credential_sudo_passwords" in FilterModule().filters()
    assert credential_sudo_passwords({"sudo_passwords": [{"password": "x"}]}) == normalize_sudo_passwords({"sudo_passwords": [{"password": "x"}]})


def _tasks(rel):
    doc = yaml.safe_load((REPO / rel).read_text(encoding="utf-8"))
    out = []

    def walk(items):
        for t in items or []:
            out.append(t)
            for k in ("block", "rescue", "always"):
                if k in t:
                    walk(t[k])
    walk(doc)
    return out


def test_loader_exposes_candidates_through_the_filter_under_no_log():
    tasks = {t.get("name"): t for t in _tasks("common/tasks/credential/resolve_and_load.yml")}
    norm = tasks["credential | normalize accounts"]
    assert norm["no_log"] is True
    assert "credential_sudo_passwords" in norm["ansible.builtin.set_fact"]["_cred_sudo_candidates"]
    assert tasks["credential | not resolved"]["ansible.builtin.set_fact"]["_cred_sudo_candidates"] == []
    summary = tasks["credential | summary"]["ansible.builtin.debug"]["msg"]
    assert "sudo_candidates=" in summary and "password" not in summary.lower()
