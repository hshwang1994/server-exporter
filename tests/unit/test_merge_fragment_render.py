"""merge_fragment.yml data-merge 식 렌더 검증 (Jinja2 레벨 — ansible-playbook 불필요).

배경:
    merge_fragment.yml 의 data 재귀 병합은 같은 key 의 두 값이 'iterable & not string' 이면
    `bv + fv` 로 concat 한다. dict 는 Jinja2 에서 iterable=True / mapping=True 라, base 가
    list 이고 fragment 가 dict(또는 반대)인 오염 케이스에서 `list + dict` TypeError 가 난다
    (Fragment 철학상 드물지만, 한 gather 버그가 전체 채널 rescue 를 타게 함).

    가드: concat 분기에 `is not mapping` 추가 → 오염 list+dict 는 else(fv 우선)로 떨어져
    crash 없음. 정상 list+list 는 그대로 concat (불변).

검증 가능: 실제 YAML 의 식을 추출해 Jinja2 로 렌더 — ansible 없이 동작 검증.
ansible filter `union` 만 shim 으로 제공(set 합집합, a 순서 우선).
"""
from __future__ import annotations

import ast
from pathlib import Path

import jinja2
import pytest
import yaml

NORM = Path(__file__).resolve().parents[2] / "common" / "tasks" / "normalize"


def _union(a, b):
    """ansible.builtin union 근사 — a 순서 유지 + b 의 신규 원소 append."""
    out = list(a)
    for x in b:
        if x not in out:
            out.append(x)
    return out


def _merge_expr():
    """merge_fragment.yml 에서 _merged_data set_fact 식(실제 코드) 추출."""
    tasks = yaml.safe_load((NORM / "merge_fragment.yml").read_text(encoding="utf-8"))
    for t in tasks:
        sf = t.get("ansible.builtin.set_fact") or t.get("set_fact") or {}
        if "_merged_data" in sf:
            return sf["_merged_data"]
    raise AssertionError("_merged_data set_fact 식 없음")


def _render(base, frag):
    env = jinja2.Environment()
    env.filters["union"] = _union
    tmpl = env.from_string(_merge_expr())
    out = tmpl.render(_merged_data=base, _data_fragment=frag)
    return ast.literal_eval(out.strip())


def test_wellformed_list_keys_concatenate():
    """정상: 같은 key 의 list 끼리 concat (firmware/users 누적 — 동작 불변)."""
    out = _render({"firmware": [{"id": "a"}]}, {"firmware": [{"id": "b"}]})
    assert out["firmware"] == [{"id": "a"}, {"id": "b"}]


def test_wellformed_dict_keys_deep_merge():
    """정상: 같은 key 의 dict 끼리 deep merge (fv 우선)."""
    out = _render({"system": {"x": 1, "y": 2}}, {"system": {"y": 9}})
    assert out["system"] == {"x": 1, "y": 9}


def test_pathological_list_base_dict_frag_does_not_crash():
    """오염: base[k]=list, frag[k]=dict → 가드 전 `list+dict` TypeError. 가드 후 fv 우선."""
    out = _render({"users": [{"name": "a"}]}, {"users": {"corrupt": True}})
    assert out["users"] == {"corrupt": True}  # else 분기(fv 우선)


def test_pathological_dict_base_list_frag_does_not_crash():
    """오염: base[k]=dict, frag[k]=list → 역시 crash 없이 fv 우선."""
    out = _render({"storage": {"a": 1}}, {"storage": [1, 2, 3]})
    assert out["storage"] == [1, 2, 3]


def test_none_handling_preserved():
    """none 처리 불변 — fv none 이면 bv 유지, bv none 이면 fv."""
    out = _render({"cpu": {"m": 1}, "power": None}, {"cpu": None, "power": {"w": 5}})
    assert out["cpu"] == {"m": 1}      # fv none → bv 유지
    assert out["power"] == {"w": 5}    # bv none → fv
