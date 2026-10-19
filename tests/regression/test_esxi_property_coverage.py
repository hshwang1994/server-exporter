"""ESXi 노출 속성 그룹 vs 소비 — pyvmomi 전수 덤프의 속성 그룹 가운데 esxi-gather 가 쓰지 않는 것은 허용 목록에 사유가 있어야 한다 (2026-10-19).

노출: tests/reference/esxi/<ip>/pyvmomi_host_dump.json 의 1단계 키(비-dict 값 → 그 키 자체)와 2단계 키(dict 값 → 'parent.child').
      예: 'runtime.healthSystemRuntime' · 'hardware_systemInfo.otherIdentifyingInfo' · 'host_summary.quickStats' · 'network_pnic'.
소비: esxi-gather/**/*.py + esxi-gather/tasks/*.yml + esxi-gather/site.yml 텍스트(주석 `#…` · Jinja `{# … #}` 제거)에 leaf 이름이
      원형·소문자·snake_case 가운데 하나로 (영숫자 경계) 나타나면 소비로 친다. 1단계 키는 덤프 이름과 pyvmomi 속성명이 다르므로
      TOP_LEVEL_TOKENS 로 대응한다 (network_pnic → pnic, storage_device → scsiLun …). 허용 목록 aliases 는 community.vmware 가
      이름을 바꿔 전달하는 그룹(memorySize → ansible_memtotal_mb)을 코드 토큰으로 잇는다 — 토큰 실존을 시험이 확인한다.
한계: leaf 가 일반 단어(name·vendor·version…)인 그룹은 텍스트 일치가 과대평가된다. 이 시험은 "소비하지 않는데 사유도 없는 그룹"
      을 잡는 것이 목적이고, 허용 목록의 그룹이 소비되기 시작하면 "허용 목록에서 지워라" 고 한다 (stale 방지).
production tree 에는 tests/reference 가 없으므로 덤프가 없으면 skip 한다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
DUMP_ROOT = REPO / "tests" / "reference" / "esxi"
ALLOWLIST = DUMP_ROOT / "coverage_allowlist.yml"
GATHER = REPO / "esxi-gather"

DUMPS = sorted(DUMP_ROOT.glob("*/pyvmomi_host_dump.json")) if DUMP_ROOT.is_dir() else []

# 덤프 1단계 키 → 코드에서 찾을 토큰 (pyvmomi 속성명 · community.vmware 모듈 이름 조각). 덤프 키 자체도 항상 후보에 넣는다.
TOP_LEVEL_TOKENS = {
    "name": ["name"],
    "network_pnic": ["pnic", "vmnic"],
    "network_vnic": ["vnic", "vmk"],
    "network_vswitch": ["vswitch"],
    "network_portgroup": ["portgroup"],
    "storage_device": ["scsiLun", "storageDevice"],
    "storage_hba": ["hostBusAdapter", "vmhba"],
    "filesystem": ["fileSystemVolume", "mountInfo"],
    "service": ["service"],
    "firewall_rules": ["firewall"],
}


def _strip_comments(text: str) -> str:
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)        # Jinja 주석
    text = re.sub(r"(?m)^\s*#.*$", "", text)                 # 전체 줄 주석 (YAML/Python)
    text = re.sub(r"(?m)\s#\s.*$", "", text)                 # 줄 끝 ' # …' 주석 ('#/' 같은 문자열 내부 '#' 은 남긴다)
    return text


def _code_text() -> str:
    files = set(GATHER.rglob("*.py")) | set((GATHER / "tasks").glob("*.yml")) | {GATHER / "site.yml"}
    return "\n".join(_strip_comments(p.read_text(encoding="utf-8", errors="replace")) for p in sorted(files) if p.is_file())


def _snake(s: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", s).lower()


def _variants(token: str) -> set:
    return {token, token.lower(), _snake(token)}


def _found(token: str, code: str) -> bool:
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])", code, re.I) is not None


def _groups(dump: dict) -> list:
    out = []
    for k, v in dump.items():
        if isinstance(v, dict):
            out.extend(f"{k}.{k2}" for k2 in v)
        else:
            out.append(k)
    return sorted(out)


def _tokens_for(group: str) -> set:
    if "." in group:
        return _variants(group.split(".")[-1])
    toks = set(_variants(group))
    for t in TOP_LEVEL_TOKENS.get(group, []):
        toks |= _variants(t)
    return toks


def _consumed_tokens(group: str, code: str) -> list:
    return sorted(t for t in _tokens_for(group) if _found(t, code))


def _allowlist() -> dict:
    doc = yaml.safe_load(ALLOWLIST.read_text(encoding="utf-8")) or {}
    return {"groups": doc.get("groups") or {}, "aliases": doc.get("aliases") or {}}


@pytest.fixture(scope="module")
def code():
    if not GATHER.is_dir():
        pytest.skip("esxi-gather 없음")
    return _code_text()


@pytest.mark.skipif(not DUMPS, reason="tests/reference/esxi/*/pyvmomi_host_dump.json 없음")
@pytest.mark.skipif(not ALLOWLIST.is_file(), reason="tests/reference/esxi/coverage_allowlist.yml 없음")
@pytest.mark.parametrize("dump_path", DUMPS, ids=[p.parent.name for p in DUMPS])
def test_exposed_groups_are_consumed_or_allowlisted(dump_path: Path, code: str):
    dump = json.loads(dump_path.read_text(encoding="utf-8"))
    assert isinstance(dump, dict) and dump, f"{dump_path}: dict 덤프가 아니다"
    allow = _allowlist()
    unlisted = []
    for g in _groups(dump):
        if _consumed_tokens(g, code):
            continue
        if g in allow["groups"]:
            continue
        alias_tokens = allow["aliases"].get(g)
        if alias_tokens and any(_found(t, code) for t in alias_tokens):
            continue
        unlisted.append(g)
    if unlisted:
        lines = [
            f"{dump_path.parent.name}: esxi-gather 가 소비하지 않는데 허용 목록에도 없는 속성 그룹 {len(unlisted)}개",
            "읽기 시작했거나 허용 목록에 사유를 적어라 — tests/reference/esxi/coverage_allowlist.yml (groups / aliases)",
        ]
        lines.extend(f"  - {g}   (찾은 토큰: {sorted(_tokens_for(g))})" for g in unlisted)
        pytest.fail("\n".join(lines))


@pytest.mark.skipif(not ALLOWLIST.is_file(), reason="허용 목록 없음")
def test_allowlist_groups_are_still_unconsumed(code: str):
    """허용 목록의 그룹이 코드에서 소비되기 시작했으면 목록에서 지워야 한다 (stale 허용 목록 방지)."""
    allow = _allowlist()
    stale = {g: _consumed_tokens(g, code) for g in allow["groups"] if _consumed_tokens(g, code)}
    assert not stale, "코드가 이제 소비하는 그룹 — 허용 목록(groups)에서 지워라: %s" % json.dumps(stale, ensure_ascii=False)


@pytest.mark.skipif(not ALLOWLIST.is_file(), reason="허용 목록 없음")
def test_allowlist_is_well_formed(code: str):
    allow = _allowlist()
    assert allow["groups"], "groups 절이 비었다"
    for g, reason in allow["groups"].items():
        assert isinstance(reason, str) and reason.strip(), f"groups.{g}: 사유가 없다"
        assert g not in allow["aliases"], f"{g}: groups 와 aliases 양쪽에 있다"
    for g, tokens in allow["aliases"].items():
        assert isinstance(tokens, list) and tokens, f"aliases.{g}: 토큰 목록이 비었다"
        present = [t for t in tokens if _found(t, code)]
        assert present, f"aliases.{g}: 토큰 {tokens} 가 esxi-gather 코드에 없다 — alias 가 stale 하다"


@pytest.mark.skipif(not DUMPS or not ALLOWLIST.is_file(), reason="덤프/허용 목록 없음")
def test_allowlist_groups_exist_in_some_dump():
    """덤프 어디에도 없는 그룹이 허용 목록에 남아 있으면 오타이거나 pyvmomi 속성이 사라진 것이다."""
    exposed = set()
    for p in DUMPS:
        exposed |= set(_groups(json.loads(p.read_text(encoding="utf-8"))))
    allow = _allowlist()
    unknown = sorted((set(allow["groups"]) | set(allow["aliases"])) - exposed)
    assert not unknown, f"덤프에 없는 그룹이 허용 목록에 있다: {unknown}"
