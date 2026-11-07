"""redfish-gather/tasks/normalize_standard.yml 의 set_fact 를 Ansible 순서대로 렌더하는 시험 도구 (2026-10-29, Summary 정합성).

모듈 결과(_rf_raw_collect)에서 각 섹션 Summary 까지는 순수 Jinja 계산이라 ansible 없이 재현할 수 있다.
  - Ansible set_fact 처럼 한 태스크의 키들은 그 태스크 **이전** 값으로 렌더한다.
  - 정의 안 된 값의 체인 접근(`a.b.c | default(..)`)은 Ansible 처럼 허용한다 — ChainableUndefined.
  - 태스크를 손으로 고르지 않고 파일 순서대로 `until` 태스크까지 렌더한다. 조건부(when · loop) 태스크를 만나면 멈춘다 —
    조건을 흉내 내지 않고 시험이 알게 한다.
golden(expected_output.json)은 모듈 산출만 담으므로 normalize 값은 이 도구로 시험한다.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from jinja2 import ChainableUndefined
from jinja2.nativetypes import NativeEnvironment

REPO = Path(__file__).resolve().parents[2]
NORM = REPO / "redfish-gather" / "tasks" / "normalize_standard.yml"
PREFIX = "redfish | normalize_standard | "
SUMMARIES = "compute group summaries"

_DOC = yaml.safe_load(NORM.read_text(encoding="utf-8"))
TASKS = [(t["name"][len(PREFIX):], t) for t in _DOC if isinstance(t, dict) and str(t.get("name", "")).startswith(PREFIX)]
FRAGMENT = next(t["ansible.builtin.set_fact"]["_data_fragment"] for n, t in TASKS if n == "build standard fragment")


def task(name):
    """태스크 이름(접두어 없이) → set_fact dict."""
    return next(t["ansible.builtin.set_fact"] for n, t in TASKS if n == name)


def env():
    e = NativeEnvironment(undefined=ChainableUndefined)
    e.filters["regex_replace"] = lambda s, pat, rep="", *a, **k: re.sub(pat, rep, "" if s is None else str(s))
    e.filters["combine"] = lambda a, *b, **k: {**a, **{kk: vv for d in b for kk, vv in d.items()}}
    e.filters["dict2items"] = lambda d, key_name="key", value_name="value": [{key_name: k, value_name: v} for k, v in d.items()]
    e.filters["items2dict"] = lambda items, key_name="key", value_name="value": {i[key_name]: i[value_name] for i in items}
    return e


def render(raw, until=SUMMARIES):
    """_rf_raw_collect → 파일 순서대로 `until` 태스크까지 렌더한 facts."""
    e, ctx = env(), {"_rf_raw_collect": raw}
    for name, t in TASKS:
        if "when" in t or "loop" in t:
            raise NotImplementedError(f"조건부 태스크는 렌더하지 않는다: {name}")
        sf = t.get("ansible.builtin.set_fact") or {}
        ctx.update({k: (e.from_string(v).render(**ctx) if isinstance(v, str) else v) for k, v in sf.items()})
        if name == until:
            return ctx
    raise KeyError(until)


def fragment(ctx, section, keys):
    """build standard fragment 의 _data_fragment.<section>.<key> 잎을 ctx 로 렌더한다."""
    e = env()
    return {k: e.from_string(FRAGMENT[section][k]).render(**ctx) for k in keys}


def raw_collect(res):
    """emulator_harness.run_gather 결과 → normalize 가 받는 _rf_raw_collect (data 밖 aux 포함)."""
    return {"data": res["data"], "collected": res["collected"], "failed_sections": res["failed_sections"],
            "unsupported_sections": res["unsupported_sections"], **(res.get("aux") or {})}


def notices(ctx, section):
    """normalize 층 notice(_rf_norm_notices) 중 그 섹션의 문장."""
    return [n["message"] for n in (ctx.get("_rf_norm_notices") or []) if n["section"] == section]
