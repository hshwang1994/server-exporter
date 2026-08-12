"""섹션 단위(partial / success) errors[].message 품질 계약 — 2026-08-12 신설.

왜 필요한가
-----------
Portal 실패 Grid 는 status 와 무관하게 **같은 errors[] 배열**을 읽는다. 그런데 품질 게이트는
`status=failed` 경로에만 있었다 (`tests/e2e/test_errors_message_contract.py`).
그래서 사용자는 한 화면에서

    "대상에 접속할 수 없습니다. 자격증명과 계정 권한을 확인하세요."   (failed 경로 — 정제됨)
    "Processor /redfish/v1/Systems/1/Processors/CPU1 실패: 401"      (partial 경로 — 날것)

를 섞어 보게 됐다. 실장비에서 일부 endpoint 미지원 / 권한 부족은 상시라 후자가 **정상 수집
결과에 항상** 붙는다.

본 테스트가 고정하는 것
-----------------------
1. production 코드가 만드는 **모든** 섹션 단위 message 문장이 failed 경로와 **같은 품질 기준**을
   통과한다 (포트 번호 / HTTP status / URI / raw stderr / 예외 / 내부 변수명 / 긴 대시 금지).
2. 섹션 message 를 5문장 표준으로 **뭉개지 않는다** — 섹션 오류는 전체 실패와 다른 사건이다.
3. Redfish 모듈이 만든 기술 문자열이 message 로 새어나가지 않고 detail 로만 간다.
4. errors[].section 이 schema 11 섹션 또는 정해진 workflow 단계 이름만 쓴다.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.e2e.test_failure_reason_contract import (
    FAILURE_REASONS,
    _assert_grid_ready,
    _env,
    _iter_tasks,
)

REPO = Path(__file__).resolve().parents[2]

SECTION_MESSAGES: dict[str, Any] = yaml.safe_load(
    (REPO / "common/vars/section_messages.yml").read_text(encoding="utf-8")
)
SCHEMA_SECTIONS: dict[str, Any] = yaml.safe_load(
    (REPO / "schema/sections.yml").read_text(encoding="utf-8")
)["sections"]

# errors[].section 으로 허용되는 값 = schema 11 섹션 + workflow 단계
_WORKFLOW_SECTIONS = {
    "precheck", "auth", "gather", "oem", "vendor_detect", "account_service",
    "multi_node", "unknown",
    # 각 채널 rescue 가 쓰는 대표 섹션 이름 (build_failed_output 의 _fail_error_section)
    "redfish_gather", "esxi_gather", "linux_gather", "windows_gather", "os_detect",
}
ALLOWED_SECTIONS = set(SCHEMA_SECTIONS) | _WORKFLOW_SECTIONS

# 섹션 message 를 만드는 production 파일 (섹션당 문장이 적은 os / esxi 는 태스크에 직접 쓴다)
_TASK_GLOBS = (
    "os-gather/tasks/**/*.yml",
    "esxi-gather/tasks/**/*.yml",
    "redfish-gather/tasks/**/*.yml",
)


# ---------------------------------------------------------------------------
# production 에서 섹션 message 리터럴 수집
# ---------------------------------------------------------------------------
def _literal_messages() -> list[tuple[str, str]]:
    """`_errors_fragment` 안에 **리터럴로 적힌** message 를 (파일, 문장) 으로 모은다.

    Jinja 표현식으로 조립되는 message(모듈 결과 기반)는 여기서 잡히지 않는다 — 그건 아래
    렌더 테스트가 따로 검증한다.
    """
    found: list[tuple[str, str]] = []
    for pattern in _TASK_GLOBS:
        for path in sorted(REPO.glob(pattern)):
            try:
                docs = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
            except yaml.YAMLError:  # pragma: no cover - 파싱 실패는 별도 테스트가 잡는다
                continue
            for doc in docs:
                for task in _iter_tasks(doc):
                    frag = (task.get("ansible.builtin.set_fact") or {}).get("_errors_fragment")
                    if not isinstance(frag, list):
                        continue
                    for entry in frag:
                        if not isinstance(entry, dict):
                            continue
                        msg = entry.get("message")
                        if isinstance(msg, str) and "{{" not in msg and "{%" not in msg:
                            found.append((str(path.relative_to(REPO)), msg))
    return found


# Jinja 표현식 안에 리터럴로 박힌 message ('message': '...' / "message": "...")
_INLINE_MESSAGE_RE = re.compile(
    r"""['"]message['"]\s*:\s*(?P<q>['"])(?P<msg>(?:(?!(?P=q)).)*)(?P=q)""", re.S)


def _inline_messages() -> list[tuple[str, str]]:
    """`_errors_fragment` 가 **Jinja 문자열**인 경우의 message 리터럴을 뽑는다.

    os 채널 다수가 `_errors_fragment: "{{ [...] if cond else [] }}"` 형태라
    YAML 파서로는 list 가 아니라 문자열 하나로 보인다. 이 경로를 놓치면 정작
    가장 많은 문장이 게이트 밖에 남는다.
    """
    found: list[tuple[str, str]] = []
    for pattern in _TASK_GLOBS:
        for path in sorted(REPO.glob(pattern)):
            try:
                docs = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
            except yaml.YAMLError:  # pragma: no cover
                continue
            for doc in docs:
                for task in _iter_tasks(doc):
                    frag = (task.get("ansible.builtin.set_fact") or {}).get("_errors_fragment")
                    if not isinstance(frag, str):
                        continue
                    for m in _INLINE_MESSAGE_RE.finditer(frag):
                        text = m.group("msg")
                        # 조립형(Jinja 보간 포함)은 값이 런타임에 정해지므로 별도 렌더 테스트 영역
                        if "{{" in text or "~" in text or "{%" in text:
                            continue
                        found.append((str(path.relative_to(REPO)), text))
    return found


def _literal_sections() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for pattern in _TASK_GLOBS:
        for path in sorted(REPO.glob(pattern)):
            try:
                docs = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
            except yaml.YAMLError:  # pragma: no cover
                continue
            for doc in docs:
                for task in _iter_tasks(doc):
                    frag = (task.get("ansible.builtin.set_fact") or {}).get("_errors_fragment")
                    if not isinstance(frag, list):
                        continue
                    for entry in frag:
                        if isinstance(entry, dict) and isinstance(entry.get("section"), str):
                            sec = entry["section"]
                            if "{{" not in sec:
                                found.append((str(path.relative_to(REPO)), sec))
    return found


_LITERAL_MESSAGES = _literal_messages() + _inline_messages()
_LITERAL_SECTIONS = _literal_sections()


def test_production_defines_section_messages_at_all():
    """수집 자체가 실패하면(0건) 이 테스트가 통째로 무의미해진다 — 방어."""
    assert _LITERAL_MESSAGES, "production 에서 섹션 message 리터럴을 하나도 찾지 못했다"


@pytest.mark.parametrize("path,message", _LITERAL_MESSAGES,
                         ids=[f"{p}:{m[:24]}" for p, m in _LITERAL_MESSAGES])
def test_section_message_is_grid_ready(path, message):
    """failed 경로와 **같은** 품질 기준을 섹션 message 에도 적용한다."""
    _assert_grid_ready(message, f"{path}")
    assert "[task:" not in message, f"[{path}] 내부 태스크명 노출: {message!r}"
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", message), f"[{path}] IP 노출: {message!r}"
    assert ".." not in message, f"[{path}] 이중 마침표: {message!r}"


# 사용자 문장에 들어가면 안 되는 내부 어휘 (조사 영역별로 실제 발견된 것들)
_BANNED_TOKENS = (
    "best-effort", "skip", "fallback", "insufficient_privilege", "identifier_not_available",
    "setup fact", "become", "DMI direct-read", "total_basis", "os_visible",
    "dmidecode", "lspci", "getent", "stderr", "stdout", "rc=",
    "ansible_system_vendor", "_l_raw_vendor", "manager_uri", "chassis_uri",
    "vmnic", "vmhba", "vSwitch", "portgroup", "datastore capacity",
    "graceful degradation", "undefined", "unset",
)


@pytest.mark.parametrize("path,message", _LITERAL_MESSAGES,
                         ids=[f"{p}:{m[:24]}" for p, m in _LITERAL_MESSAGES])
def test_section_message_has_no_internal_vocabulary(path, message):
    for token in _BANNED_TOKENS:
        assert token not in message, (
            f"[{path}] 사용자 문장에 내부 어휘 {token!r} 노출 — detail 로 옮길 것: {message!r}"
        )


@pytest.mark.parametrize("path,message", _LITERAL_MESSAGES,
                         ids=[f"{p}:{m[:24]}" for p, m in _LITERAL_MESSAGES])
def test_section_message_never_asserts_success_of_other_parts(path, message):
    """다른 부분이 **성공했다고 단언하는 절**을 넣지 않는다 (2026-08-12).

    섹션 오류 문장은 `status=failed` envelope 의 errors[] 로도 합류할 수 있다
    (`build_failed_output.yml` 이 누적 오류를 보존한다). "표준 항목은 정상 수집되었습니다"
    같은 절이 섞이면 Portal 한 화면에 "수집 실패" 와 "정상 수집 완료" 가 함께 뜬다.
    어느 섹션이 성공했는지는 envelope 의 `sections` 가 이미 정확히 표현한다.
    """
    for claim in ("정상 수집", "정상적으로 수집", "수집은 완료", "수집을 완료",
                  "정상 수집되었습니다", "완료했습니다"):
        assert claim not in message, (
            f"[{path}] 다른 부분의 성공을 단언한다 — failed envelope 에 합류하면 모순: {message!r}"
        )


@pytest.mark.parametrize("path,message", _LITERAL_MESSAGES,
                         ids=[f"{p}:{m[:24]}" for p, m in _LITERAL_MESSAGES])
def test_section_message_is_not_a_failed_path_sentence(path, message):
    """섹션 오류를 전체 실패 5문장으로 뭉개지 않는다.

    "대상에 접속할 수 없습니다" 는 접속이 된 상태에서 CPU 만 못 읽은 결과를 설명하지 못한다.
    """
    assert message not in set(FAILURE_REASONS.values()), (
        f"[{path}] 섹션 오류에 전체 실패 대표 문장을 썼다 — 섹션 의미를 유지할 것: {message!r}"
    )


@pytest.mark.parametrize("path,section", _LITERAL_SECTIONS,
                         ids=[f"{p}:{s}" for p, s in _LITERAL_SECTIONS])
def test_section_name_is_known(path, section):
    assert section in ALLOWED_SECTIONS, (
        f"[{path}] errors[].section 에 정의되지 않은 이름 {section!r} — "
        f"schema 11 섹션 또는 정해진 workflow 단계만 쓴다"
    )


# ═══════════════════════════════════════════════════════════════════════════
# section_messages.yml 정본 자체의 품질
# ═══════════════════════════════════════════════════════════════════════════
def test_section_labels_cover_every_schema_section():
    labels = SECTION_MESSAGES["_sm_labels"]
    missing = [s for s in SCHEMA_SECTIONS if s not in labels]
    assert not missing, f"섹션 라벨 누락: {missing}"


def test_section_message_map_targets_are_schema_sections():
    for raw, mapped in SECTION_MESSAGES["_sm_section_map"].items():
        assert mapped in SCHEMA_SECTIONS, f"{raw} → {mapped} 는 schema 섹션이 아니다"


def test_composed_section_sentences_are_grid_ready():
    """라벨 + 템플릿 + 조치 로 조립되는 모든 문장이 품질 기준을 통과한다."""
    suffix = SECTION_MESSAGES["_sm_tpl_suffix"]
    for advice in SECTION_MESSAGES["_sm_advice"].values():
        for key, label in SECTION_MESSAGES["_sm_labels"].items():
            _assert_grid_ready(label + suffix + advice, f"_sm_labels:{key}")


def test_section_overrides_are_grid_ready():
    for key, sentence in SECTION_MESSAGES["_sm_overrides"].items():
        _assert_grid_ready(sentence, f"_sm_overrides:{key}")
        for claim in ("정상 수집", "정상적으로 수집", "완료했습니다"):
            assert claim not in sentence, (
                f"_sm_overrides:{key} 가 다른 부분의 성공을 단언한다: {sentence!r}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# production YAML 의 inline Jinja 가 **컴파일**은 되는가
# ═══════════════════════════════════════════════════════════════════════════
# 2026-08-12: `>-` folded block scalar 안에 YAML 주석(`#`)을 쓰면 그것은 주석이 아니라
#   Jinja 표현식 본문이 되어 템플릿이 통째로 깨진다. 그 태스크가 실패하면 rescue 로 빠져
#   **정상 수집한 결과가 status=failed 로 나간다.** pytest 는 렌더하지 않는 템플릿을
#   컴파일조차 하지 않으므로 이 클래스는 테스트로 잡히지 않았다. 여기서 전수 컴파일한다.
def _iter_inline_templates():
    import jinja2  # noqa: PLC0415

    for pattern in ("os-gather/**/*.yml", "esxi-gather/**/*.yml",
                    "redfish-gather/**/*.yml", "common/**/*.yml"):
        for path in sorted(REPO.glob(pattern)):
            try:
                docs = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
            except yaml.YAMLError:  # pragma: no cover
                continue
            stack = [(str(path.relative_to(REPO)), docs)]
            while stack:
                where, node = stack.pop()
                if isinstance(node, dict):
                    stack.extend((f"{where}/{k}", v) for k, v in node.items())
                elif isinstance(node, list):
                    stack.extend((f"{where}[{i}]", v) for i, v in enumerate(node))
                elif isinstance(node, str) and ("{{" in node or "{%" in node):
                    yield where, node


def test_every_inline_jinja_template_compiles():
    import jinja2  # noqa: PLC0415

    env = jinja2.Environment()
    broken = []
    checked = 0
    for where, tpl in _iter_inline_templates():
        checked += 1
        try:
            env.parse(tpl)
        except jinja2.TemplateSyntaxError as exc:
            broken.append(f"{where}: {exc}")
    assert checked > 100, f"템플릿을 {checked}개만 훑었다 — 수집 로직이 깨졌다"
    assert not broken, (
        "Jinja 템플릿 컴파일 실패 — 해당 태스크가 런타임에 죽어 envelope 이 "
        "failed 로 뒤집힌다:\n  " + "\n  ".join(broken)
    )


# ═══════════════════════════════════════════════════════════════════════════
# Redfish — 모듈 기술 문자열은 message 로 새지 않고 detail 로만 간다
# ═══════════════════════════════════════════════════════════════════════════
def _redfish_errors_template() -> str:
    docs = list(yaml.safe_load_all(
        (REPO / "redfish-gather/tasks/normalize_standard.yml").read_text(encoding="utf-8")))
    for doc in docs:
        for task in _iter_tasks(doc):
            frag = (task.get("ansible.builtin.set_fact") or {}).get("_errors_fragment")
            if isinstance(frag, str):
                return frag
    raise AssertionError("normalize_standard.yml 에서 _errors_fragment 템플릿을 찾지 못함")


# 실제 redfish_gather.py 가 만드는 문자열 표본 (원문 유지 — 모듈은 건드리지 않는다)
_MODULE_ERRORS = [
    {"section": "processors", "message": "Processor /redfish/v1/Systems/1/Processors/CPU1 실패: 401"},
    {"section": "memory", "message": "Memory 컬렉션 실패: HTTP 500", "detail": None},
    {"section": "storage", "message": "Controllers 컬렉션 fetch 실패 (/redfish/v1/x): 503",
     "detail": {"status_code": 503}},
    {"section": "network_adapters", "message": "NetworkAdapters 미지원 또는 실패: HTTP 400",
     "detail": "tried: /a | /b"},
    {"section": "firmware", "message": "FirmwareInventory 실패: 404"},
    {"section": "power", "message": "chassis_uri 없음 (detect_vendor 에서 Chassis 미발견)"},
    {"section": "thermal", "message": "예외 발생", "detail": "TypeError: 'NoneType'"},
    {"section": "bmc", "message": "manager_uri 없음"},
    {"section": "log_services", "message": "LogServices 컬렉션 실패: 404"},
    {"section": "multi_node.managers", "message": "Managers 컬렉션 실패: timeout"},
    {"section": "vendor_detect", "message": "ServiceRoot에서 벤더 식별 불가",
     "code": "vendor_unresolved"},
    {"section": "boot", "message": "system_uri 없음"},
    {"section": "memory",
     "message": "collection 멤버 900 > 상한 512 — 절단(DoS 방어)"},
]


def _render_redfish_errors(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _env().from_string(_redfish_errors_template()).render(
        _rf_raw_collect={"errors": raw}, **SECTION_MESSAGES)


def test_redfish_module_strings_never_reach_message():
    """모듈 원문은 message 로 새지 않고 detail 에만 남는다.

    2026-08-12: 같은 (section, message) 는 1건으로 합치므로 원소 수가 입력보다 적을 수 있다
    (같은 섹션의 멤버 오류 24건이 글자까지 같은 문장 24개가 되던 것을 막는다).
    """
    rendered = _render_redfish_errors(_MODULE_ERRORS)
    assert 0 < len(rendered) <= len(_MODULE_ERRORS)
    all_detail = " | ".join(e["detail"] or "" for e in rendered)
    for src in _MODULE_ERRORS:
        assert src["message"] in all_detail, f"모듈 원문이 detail 에서 사라졌다: {src['message']!r}"
    for entry in rendered:
        label = f"redfish/{entry['section']}"
        _assert_grid_ready(entry["message"], label)
        assert "/redfish/" not in entry["message"], label
        assert not re.search(r"HTTP\s*\d{3}", entry["message"]), label
        assert "예외" not in entry["message"], label
        assert "—" not in entry["message"], label
        assert entry["detail"], label


def test_redfish_same_section_errors_are_merged():
    """같은 섹션의 오류 N건이 동일 문장 N개로 Grid 를 채우지 않는다."""
    raw = [{"section": "memory", "message": f"Memory /redfish/v1/Systems/1/Memory/{i} 실패: 401"}
           for i in range(24)]
    rendered = _render_redfish_errors(raw)
    assert len(rendered) == 1, "같은 (section, message) 는 1건으로 합쳐야 한다"
    detail = rendered[0]["detail"]
    assert "외 19건" in detail, f"절단 사실이 남아야 한다: {detail!r}"


def test_redfish_error_sections_are_normalized_to_schema():
    rendered = _render_redfish_errors(_MODULE_ERRORS)
    for entry in rendered:
        assert entry["section"] in ALLOWED_SECTIONS, entry
    by_src = {src["section"]: e["section"] for src, e in zip(_MODULE_ERRORS, rendered)}
    assert by_src["processors"] == "cpu"
    assert by_src["network_adapters"] == "network"
    assert by_src["log_services"] == "bmc"
    assert by_src["boot"] == "system"
    assert by_src["multi_node.managers"] == "multi_node"


def test_redfish_dict_detail_is_flattened_to_string():
    rendered = _render_redfish_errors(_MODULE_ERRORS)
    storage = [e for e in rendered if e["section"] == "storage"][0]
    assert isinstance(storage["detail"], str)
    assert "status_code=503" in storage["detail"]
    assert "{'" not in storage["detail"], "파이썬 dict repr 이 detail 에 남았다"


def test_redfish_empty_errors_render_to_empty_list():
    assert _render_redfish_errors([]) == []


# ═══════════════════════════════════════════════════════════════════════════
# 성공한 fallback 은 error 가 아니다 (H11)
# ═══════════════════════════════════════════════════════════════════════════
def test_successful_fallback_is_not_an_error():
    """SimpleStorage / SmartStorage fallback 은 **수집에 성공한** 정보다.

    errors[] 에 넣으면 `_make_section_runner` 의 `if errs: failed.append(section)` 때문에
    데이터를 정상 수집했는데도 섹션이 failed 로, overall status 가 partial 로 강등된다.
    HPE iLO4 같은 구세대 BMC 는 **매 수집마다** partial 로 보고됐다.
    """
    source = (REPO / "redfish-gather/library/redfish_gather.py").read_text(encoding="utf-8")
    for phrase in ("SimpleStorage fallback 사용",
                   "SmartStorage (HPE OEM legacy) fallback 사용",
                   "Manufacturer fallback로 vendor=",
                   "WWW-Authenticate realm fallback로 vendor="):
        idx = source.find(phrase)
        assert idx > 0, f"표본 문구를 찾지 못함: {phrase!r}"
        head = source[max(0, idx - 400):idx]
        assert "_notice(" in head.split("\n")[-6:][0] or "_notice(" in head[-300:], (
            f"{phrase!r} 가 아직 errors 로 간다 — 성공한 fallback 은 notice 여야 한다"
        )
        assert "errors.append" not in head[-160:], (
            f"{phrase!r} 직전에 errors.append 가 남아 있다"
        )


def test_user_facing_text_is_not_used_as_control_key():
    """사용자 문구 부분일치로 제어 분기를 하지 않는다.

    종전에는 vendor fallback 성공 시 `'ServiceRoot에서 벤더 식별 불가' not in e['message']`
    로 앞선 error 를 지웠다. 문구를 다듬는 순간 분류가 깨지는 구조였다.
    """
    source = (REPO / "redfish-gather/library/redfish_gather.py").read_text(encoding="utf-8")
    assert "'ServiceRoot에서 벤더 식별 불가' not in" not in source
    assert "_CODE_VENDOR_UNRESOLVED" in source, "내부 code 기반 분기로 바뀌어야 한다"
