"""Portal 실패 Grid 계약 — 실제 소스는 `errors[].message` 다 (Phase 6-B / §24).

배경 (2026-08-11 사용자 확인)
----------------------------
Phase 5-A 는 `diagnosis.failure_reason` 만 정화했다. 그런데 Portal 실패 Grid 가 실제로 읽는
값은 **`errors[].message`** 다. 그 자리에는 아직 아래가 남아 있었다:

  - `[task: linux | gather cpu]` 같은 **내부 Ansible 태스크명**
  - `SSH(22), WinRM(5985, 5986)` / `Redfish API(443)` 같은 **관리 포트 번호**
  - 대상 IP, 긴 대시(—), 이중 마침표

본 테스트는 두 가지를 고정한다.

  1. `errors[].message` 도 `failure_reason` 과 **같은 품질 기준**을 통과한다
     (`_assert_grid_ready` / `_assert_no_ports` / `_assert_no_technical_noise` 재사용).
  2. `errors[].message` 와 `diagnosis.failure_reason` 이 **같은 이야기**를 한다.
     구현상 build_failed_output.yml 이 failure_reason 을 그대로 복사하므로 문자열이 동일해야 한다.

추가로 문구 정본이 두 곳(Ansible / Python)에 있으므로 drift 를 막는다:
  - `common/vars/failure_reasons.yml`      (Ansible rescue 가 참조)
  - `common/library/precheck_bundle.py`    (precheck 단계가 참조)

렌더는 합성 fixture 가 아니라 **production YAML 자체**를 추출해 수행한다.
"""
from __future__ import annotations

import re
import sys
import types
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.e2e.test_failure_reason_contract import (
    FAILURE_REASONS,
    FR_CATALOG,
    fr,
    _assert_grid_ready,
    _assert_no_ports,
    _assert_no_technical_noise,
    _env,
    _iter_tasks,
    _plays,
    _render_diagnosis,
    _render_fallback_envelopes,
    render_redfish_rescue,
    _task_by_name,
)

REPO = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO / "common" / "library"))
_b = types.ModuleType("ansible.module_utils.basic")
_b.AnsibleModule = object
_m = types.ModuleType("ansible.module_utils")
_m.basic = _b
_a = types.ModuleType("ansible")
_a.module_utils = _m
sys.modules.setdefault("ansible", _a)
sys.modules.setdefault("ansible.module_utils", _m)
sys.modules.setdefault("ansible.module_utils.basic", _b)
import precheck_bundle as pb  # noqa: E402

_BUILD_FAILED = "common/tasks/normalize/build_failed_output.yml"
_ERROR_TASK = "build_failed_output | build sections (all failed)"

_RF_TASK = "redfish | rescue | Portal 표시용 failure_reason 보장"
_ESXI_TASK = "esxi | rescue | Portal 표시용 failure_reason 보장"
_OS_TASKS = {
    "linux": "linux | rescue | Portal 표시용 diagnosis 보장",
    "windows": "windows | rescue | Portal 표시용 diagnosis 보장",
}

_PRECHECK_OK = {
    "reachable": True, "port_open": True, "protocol_supported": True,
    "auth_success": None, "failure_stage": None, "failure_code": None,
    "failure_reason": None, "details": {},
}


# ---------------------------------------------------------------------------
# build_failed_output.yml 의 errors[] 템플릿을 실제로 추출해 렌더
# ---------------------------------------------------------------------------
def _error_templates() -> dict[str, str]:
    """`_norm_errors` 의 message / detail 템플릿 원문을 production YAML 에서 꺼낸다."""
    tasks = list(yaml.safe_load_all((REPO / _BUILD_FAILED).read_text(encoding="utf-8")))[0]
    for task in _iter_tasks(tasks):
        errors = task.get("ansible.builtin.set_fact", {}).get("_norm_errors")
        if errors:
            return {"message": errors[0]["message"], "detail": errors[0]["detail"]}
    raise AssertionError(f"{_BUILD_FAILED} 에서 _norm_errors 템플릿을 찾지 못함")


def _render_error(ctx: dict[str, Any]) -> dict[str, Any]:
    tpl = _error_templates()
    # build_failed_output.yml 의 fallback 문장이 리터럴이 아니라 카탈로그
    #   (_fr_catalog.output_build_failed)를 참조하므로 vars_files 로드분을 함께 주입한다.
    return {
        key: _env().from_string(text).render(**{**FAILURE_REASONS, **ctx})
        for key, text in tpl.items()
    }


# ---------------------------------------------------------------------------
# 실패 경로 표본 — 각 채널의 rescue 가 만든 진단 + 그 채널이 넘기는 기술 문자열
# ---------------------------------------------------------------------------
def _rf_diag(collect_ok: bool, rejected: bool) -> dict[str, Any]:
    return render_redfish_rescue(
        {"_diagnosis": dict(_PRECHECK_OK), "_rf_collect_ok": collect_ok,
         "_rf_auth_rejected": rejected})


def _esxi_diag(auth_ok: bool, facts_ok: bool) -> dict[str, Any]:
    return _render_diagnosis(
        "esxi-gather/site.yml", _ESXI_TASK,
        {"_diagnosis": {**_PRECHECK_OK, "details": {"channel": "esxi"}},
         "_e_auth_ok": auth_ok, "_e_facts_ok": facts_ok})


def _os_diag(os_type: str, auth_ok: bool) -> dict[str, Any]:
    ctx: dict[str, Any] = {"_os_auth_ok": auth_ok, "_os_attempts_meta": {"attempted_count": 2}}
    if os_type == "windows":
        ctx["ansible_port"] = "5986"
    return _render_diagnosis("os-gather/site.yml", _OS_TASKS[os_type], ctx)


def _precheck_diag(channel: str, stage: str) -> dict[str, Any]:
    """precheck 단계 실패 진단 — 사유 문자열은 precheck_bundle 정본을 그대로 쓴다."""
    code = {
        "reachable": "TARGET_UNREACHABLE",
        "port": "TCP_CONNECTION_REFUSED",
        "protocol": "PROTOCOL_CHECK_FAILED",
        "auth": "AUTH_PROBE_FAILED",
    }[stage]
    return {**_PRECHECK_OK, "failure_stage": stage, "failure_code": code,
            "failure_reason": pb.reason_for_failure(code, channel)}


# 실제 운영에서 각 경로가 넘기는 기술 문자열 (모두 detail 로 가야 한다)
_TECHNICAL = {
    "redfish": "[task: redfish | abort if collect completely failed] "
               "Redfish 정보 수집에 실패했습니다 (192.0.2.10). 시도된 계정 수 2개.",
    "esxi": "[task: esxi | abort if all credentials failed] "
            "ESXi 자격증명 후보 2개가 모두 실패했습니다.",
    "os": "[task: linux | gather cpu] Linux 수집 예외",
    "os_detect": "확인한 관리 포트: WinRM 5986, WinRM 5985, SSH 22",
}

_CASES: list[tuple[str, dict[str, Any], str, str]] = [
    # label, diagnosis, _fail_error_message, _fail_error_detail
    ("precheck/redfish/reachable", _precheck_diag("redfish", "reachable"),
     _TECHNICAL["redfish"], "port=443: 연결 시간 초과 (timeout=3.0s)"),
    ("precheck/redfish/port", _precheck_diag("redfish", "port"),
     _TECHNICAL["redfish"], "port=443: 연결 거부됨 (port=443)"),
    ("precheck/redfish/protocol", _precheck_diag("redfish", "protocol"),
     _TECHNICAL["redfish"], "HTTP 500"),
    ("precheck/esxi/protocol", _precheck_diag("esxi", "protocol"),
     _TECHNICAL["esxi"], "vim25 SOAP 응답 아님"),
    ("precheck/os/reachable", _precheck_diag("os", "reachable"),
     _TECHNICAL["os_detect"],
     "port=5986: 연결 시간 초과 (timeout=2.0s); port=5985: 연결 거부됨 (port=5985)"),
    ("precheck/redfish/auth", _precheck_diag("redfish", "auth"),
     _TECHNICAL["redfish"], "HTTP 401"),
    ("rescue/redfish/credential", _rf_diag(False, False), _TECHNICAL["redfish"], None),
    ("rescue/redfish/rejected", _rf_diag(False, True), _TECHNICAL["redfish"], None),
    ("rescue/redfish/gather", _rf_diag(True, False), _TECHNICAL["redfish"], None),
    ("rescue/esxi/credential", _esxi_diag(False, False), _TECHNICAL["esxi"], None),
    ("rescue/esxi/gather", _esxi_diag(True, False), _TECHNICAL["esxi"], None),
    ("rescue/linux/credential", _os_diag("linux", False), _TECHNICAL["os"], None),
    ("rescue/linux/gather", _os_diag("linux", True), _TECHNICAL["os"], None),
    ("rescue/windows/credential", _os_diag("windows", False), _TECHNICAL["os"], None),
    ("rescue/windows/gather", _os_diag("windows", True), _TECHNICAL["os"], None),
]

_IDS = [c[0] for c in _CASES]


def _ctx(diag, message, detail) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "_diagnosis": diag,
        "_fail_error_section": "gather",
        "_out_target_type": "os",
        "_out_ip": "192.0.2.10",
        "inventory_hostname": "192.0.2.10",
        "_fail_error_message": message,
    }
    if detail is not None:
        ctx["_fail_error_detail"] = detail
    return ctx


# ═══════════════════════════════════════════════════════════════════════════
# §24 — errors[].message 도 Portal Grid 품질 기준을 통과해야 한다
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("label,diag,message,detail", _CASES, ids=_IDS)
def test_errors_message_is_grid_ready(label, diag, message, detail):
    rendered = _render_error(_ctx(diag, message, detail))
    _assert_grid_ready(rendered["message"], f"errors[].message {label}")


@pytest.mark.parametrize("label,diag,message,detail", _CASES, ids=_IDS)
def test_errors_message_has_no_ports_or_noise(label, diag, message, detail):
    """§25 §26 — 관리 포트 번호 / 태스크명 / IP / HTTP status 는 message 에 없다."""
    msg = _render_error(_ctx(diag, message, detail))["message"]
    tag = f"errors[].message {label}"
    _assert_no_ports(msg, tag)
    _assert_no_technical_noise(msg, tag)
    assert "[task:" not in msg, f"[{tag}] 내부 태스크명 노출: {msg!r}"
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", msg), f"[{tag}] IP 노출: {msg!r}"
    assert ".." not in msg, f"[{tag}] 이중 마침표: {msg!r}"


# ═══════════════════════════════════════════════════════════════════════════
# §24 — failure_reason 과 errors[].message 정합 (같은 단계면 같은 이야기)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("label,diag,message,detail", _CASES, ids=_IDS)
def test_errors_message_matches_failure_reason(label, diag, message, detail):
    rendered = _render_error(_ctx(diag, message, detail))
    assert rendered["message"] == diag["failure_reason"], (
        f"[{label}] Portal 이 읽는 errors[].message 와 diagnosis.failure_reason 이 다르다 — "
        f"사용자가 보는 문장과 시스템 문장이 갈린다"
    )


def test_errors_message_falls_back_when_reason_missing():
    """failure_reason 이 비어 있어도 message 가 빈 칸이 되지 않는다."""
    for diag in ({}, {"failure_reason": None}, {"failure_reason": "   "}, None):
        rendered = _render_error(_ctx(diag, _TECHNICAL["os"], None))
        _assert_grid_ready(rendered["message"], f"fallback/{diag!r}")
        assert "[task:" not in rendered["message"]


# ═══════════════════════════════════════════════════════════════════════════
# §34 — 기술 정보는 errors[].detail 에 그대로 보존된다
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("label,diag,message,detail", _CASES, ids=_IDS)
def test_errors_detail_preserves_technical_evidence(label, diag, message, detail):
    rendered = _render_error(_ctx(diag, message, detail))
    got = rendered["detail"]
    assert isinstance(got, str) and got.strip(), f"[{label}] detail 이 비어 있다"
    assert message in got, f"[{label}] 기술 메시지가 detail 에서 사라졌다: {got!r}"
    if detail is not None:
        assert detail in got, f"[{label}] precheck 원본 오류가 detail 에서 사라졌다: {got!r}"


def test_errors_detail_is_null_when_nothing_technical():
    rendered = _render_error({
        "_diagnosis": _precheck_diag("redfish", "protocol"),
        "_fail_error_section": "gather",
    })
    assert rendered["detail"] is None, "기술 정보가 없으면 detail 은 null 이어야 한다"


def test_errors_detail_holds_port_numbers_for_os_portfail():
    """§25 — 포트 번호는 message 가 아니라 detail 이 보존한다 (운영자용)."""
    rendered = _render_error(_ctx(
        _precheck_diag("os", "reachable"), _TECHNICAL["os_detect"],
        "port=5986: 연결 시간 초과 (timeout=2.0s); port=22: 연결 거부됨 (port=22)"))
    for port in ("5986", "5985", "22"):
        assert port in rendered["detail"], f"detail 에 포트 {port} 근거가 없다"
        assert port not in rendered["message"], "message 에 포트가 노출됐다"


# ═══════════════════════════════════════════════════════════════════════════
# fallback envelope (block/rescue 모두 실패) 도 같은 계약을 지킨다
# ═══════════════════════════════════════════════════════════════════════════
_FALLBACK_CTX = {
    "redfish-gather/site.yml": {"_rf_ip": "192.0.2.10", "inventory_hostname": "192.0.2.10"},
    "esxi-gather/site.yml": {"_e_ip": "192.0.2.20", "inventory_hostname": "192.0.2.20"},
    "os-gather/site.yml": {"_ip": "192.0.2.30", "inventory_hostname": "192.0.2.30"},
}


@pytest.mark.parametrize("site", list(_FALLBACK_CTX))
def test_fallback_envelope_message_matches_reason(site):
    for idx, env in enumerate(_render_fallback_envelopes(site, _FALLBACK_CTX[site])):
        label = f"fallback/{site}#{idx}"
        errors = env["errors"]
        assert errors, f"[{label}] fallback envelope 에 errors 가 비어 있다"
        msg = errors[0]["message"]
        _assert_grid_ready(msg, label)
        _assert_no_ports(msg, label)
        _assert_no_technical_noise(msg, label)
        assert msg == env["diagnosis"]["failure_reason"], (
            f"[{label}] fallback 도 message 와 failure_reason 이 같아야 한다"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 문구 카탈로그 계약 — 정본 YAML ↔ Python 복제본 / code ↔ 문장 키
# ═══════════════════════════════════════════════════════════════════════════
# 2026-09-21 (사용자 확정): 문장을 failure_code 하나가 아니라 (code, 대상 종류, 세부 사유) 로
#   고른다. 종전 6문장 집합 고정 테스트를 카탈로그 키 집합 고정으로 바꿨다. 키 추가/삭제는
#   사용자 확정 사항이다 (docs/ai/decisions/ADR-2026-09-21-failure-reason-catalog.md).
_EXPECTED_KEYS = {
    "ip_invalid", "target_unreachable", "port_silent", "port_refused",
    "protocol_unconfirmed",
    "loc_unregistered", "loc_vault_missing", "loc_vault_unreadable", "loc_vault_no_account",
    "project_vault_missing", "project_vault_unreadable", "project_vault_no_account",
    "auth_unconfirmed", "auth_rejected",
    "gather_after_auth", "gather_connection_lost", "gather_no_data", "gather_internal",
    "output_build_failed",
}
_CHANNELS = {"os", "esxi", "redfish", "default"}


def _catalog_texts():
    """(키, 채널, 문장 틀) 전부."""
    for key, entry in FR_CATALOG.items():
        for channel, text in entry.items():
            yield key, channel, text


def test_catalog_has_exactly_the_confirmed_keys():
    assert set(FR_CATALOG) == _EXPECTED_KEYS, (
        "사용자 문구 카탈로그 키 집합이 바뀌었다. 추가/삭제는 사용자 확정이 필요하다: "
        f"추가={sorted(set(FR_CATALOG) - _EXPECTED_KEYS)}, "
        f"삭제={sorted(_EXPECTED_KEYS - set(FR_CATALOG))}"
    )
    for key, entry in FR_CATALOG.items():
        assert isinstance(entry, dict) and entry, key
        assert set(entry) <= _CHANNELS, f"{key}: 알 수 없는 채널 {set(entry) - _CHANNELS}"


@pytest.mark.parametrize("loc", ["ic", None, "", "  seoul-dc1  "])
def test_every_catalog_sentence_is_grid_ready(loc):
    """모든 (키, 채널) 문장이 {loc} 치환 후 Portal Grid 품질 기준을 통과한다."""
    for key, channel, _text in _catalog_texts():
        rendered = fr(key, None if channel == "default" else channel, loc)
        tag = f"{key}/{channel}/loc={loc!r}"
        _assert_grid_ready(rendered, tag)
        assert "{loc}" not in rendered and "{" not in rendered, f"[{tag}] 틀이 남았다"


def test_loc_placeholder_renders_actual_location():
    """사용자 결정 (2026-09-21) — 문장의 위치는 실제 loc 값으로 보인다. 값이 없으면 '미지정'."""
    assert fr("loc_vault_unreadable", None, "ic") == "해당 위치(ic)의 Vault를 읽을 수 없습니다."
    assert "해당 위치(미지정)" in fr("loc_vault_unreadable", None, "")
    assert "해당 위치(미지정)" in fr("loc_vault_unreadable", None, None)
    # 문장을 깨뜨리는 문자는 표시하지 않는다 (미등록 입력값이 그대로 보일 수 있다)
    assert "{" not in fr("loc_unregistered", None, "{{ evil }}")


@pytest.mark.parametrize("key,channel", [
    (k, c) for k, e in FR_CATALOG.items() for c in e if c != "default"])
def test_channel_sentences_name_their_target_kind(key, channel):
    """대상 종류별 문장은 그 종류 어휘를 담는다 — 채널 문장을 따로 둔 이유다."""
    word = {"os": "OS", "esxi": "ESXi", "redfish": "Redfish"}[channel]
    assert word in FR_CATALOG[key][channel], f"{key}/{channel}"


def test_sentences_are_unique_across_catalog():
    texts = [t for _k, _c, t in _catalog_texts()]
    assert len(texts) == len(set(texts)), "같은 문장이 두 키에 있으면 원인을 구분할 수 없다"


@pytest.mark.parametrize("key,text", sorted(
    (f"{k}/{c}", t) for k, c, t in _catalog_texts()))
def test_standard_sentences_have_no_dns_guidance(key, text):
    """§25 §28 — Portal 은 IPv4 만 넘긴다. DNS / 호스트 이름 안내를 쓰지 않는다."""
    for banned in ("DNS", "호스트 이름", "도메인", "이름 확인"):
        assert banned not in text, f"[{key}] DNS 계열 안내가 남아 있다: {text!r}"


def test_precheck_catalog_copy_does_not_drift():
    """precheck_bundle 의 부분 복제본은 정본과 글자까지 같다."""
    for key, entry in pb.FAILURE_REASON_CATALOG.items():
        assert key in FR_CATALOG, f"precheck 에만 있는 키 {key}"
        assert entry == FR_CATALOG[key], (
            f"문구 drift — common/vars/failure_reasons.yml:_fr_catalog.{key} 와 "
            f"precheck_bundle.FAILURE_REASON_CATALOG[{key!r}] 가 다르다"
        )


_CODE_KEYS = FAILURE_REASONS["_fr_code_keys"]


def test_code_key_table_covers_every_enum_value():
    """failure_code enum 전량이 문장 키를 갖는다 (누락 시 문장이 조용히 퇴화하는 것 방지).

    개수를 세지 않고 **field_dictionary 의 enum 과 직접 대조**한다.
    """
    fd = yaml.safe_load(
        (REPO / "schema" / "field_dictionary.yml").read_text(encoding="utf-8")
    )
    fields = fd.get("fields", fd)
    enum_values = set(fields["diagnosis.failure_code"]["enum"])
    assert set(_CODE_KEYS) == enum_values, (
        "_fr_code_keys 와 field_dictionary enum 이 어긋났다: "
        f"표만={sorted(set(_CODE_KEYS) - enum_values)}, "
        f"enum만={sorted(enum_values - set(_CODE_KEYS))}"
    )
    listed = {k for keys in _CODE_KEYS.values() for k in keys}
    assert listed == set(FR_CATALOG), (
        f"code 에 매이지 않은 키={sorted(set(FR_CATALOG) - listed)}, "
        f"카탈로그에 없는 키={sorted(listed - set(FR_CATALOG))}"
    )


@pytest.mark.parametrize("code,key", sorted(pb.PRECHECK_REASON_KEYS.items()))
@pytest.mark.parametrize("channel", ["os", "esxi", "redfish"])
def test_precheck_code_maps_to_catalog_sentence(code, key, channel):
    """사전 점검 문장 = 카탈로그 (키, 채널) 문장. 키는 그 code 가 허용하는 키여야 한다."""
    assert key in _CODE_KEYS[code], f"{code} → {key} 는 _fr_code_keys 가 허용하지 않는다"
    assert pb.reason_for_failure(code, channel) == fr(key, channel, "미지정")


def test_precheck_distinguishes_every_connect_failure():
    """TCP 무응답(ICMP 응답) 과 거부는 조치가 달라 다른 문장이다 (2026-09-21)."""
    for ch in ("os", "esxi", "redfish"):
        silent = pb.reason_for_failure("TCP_CONNECT_FAILED", ch)
        refused = pb.reason_for_failure("TCP_CONNECTION_REFUSED", ch)
        unreachable = pb.reason_for_failure("TARGET_UNREACHABLE", ch)
        dns = pb.reason_for_failure("DNS_RESOLUTION_FAILED", ch)
        assert len({silent, refused, unreachable, dns}) == 4, ch


def test_no_site_yml_hardcodes_a_catalog_sentence():
    """정본 문장을 site.yml 이 리터럴로 다시 적지 않는다 (H2 회귀 차단)."""
    for site in ("redfish-gather/site.yml", "esxi-gather/site.yml", "os-gather/site.yml"):
        text = (REPO / site).read_text(encoding="utf-8")
        for key, channel, tpl in _catalog_texts():
            for piece in tpl.split("{loc}"):
                if len(piece.strip()) >= 12:
                    assert piece not in text, (
                        f"{site} 에 정본 문장이 하드코딩됐다 ({key}/{channel}) — 카탈로그를 참조할 것"
                    )


def test_sentence_selection_has_no_presence_guess():
    """문장은 관측값(code / 채널 / Vault 적재 결과)에서만 고른다.

    - presence 추정 문장 분기(reason_for_connect_failure / ip_in_use)를 되살리지 않는다.
    - ICMP 는 실패를 만들지 않으므로 ICMP 전용 문장 키도 없다.
    """
    assert not hasattr(pb, "reason_for_connect_failure"), (
        "presence 기반 문장 분기가 되살아났다"
    )
    source = (REPO / "common" / "library" / "precheck_bundle.py").read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "ip_in_use" not in line, f"presence 판정 잔재: {line!r}"
    assert not any("icmp" in k for k in FR_CATALOG), "ICMP 전용 문장이 생겼다"


def test_icmp_probe_is_not_a_gate():
    """ICMP 는 앞단 Gate 가 아니다 — TCP 응답 경로에서는 호출조차 되지 않는다.

    2026-09-03 사용자 지시의 핵심 경계다. ICMP 를 Gate 로 만들면 ICMP 가 차단된 관리망의
    정상 장비가 전부 도달 실패로 뒤집힌다 (CLAUDE.md §7).
    """
    import inspect
    src = inspect.getsource(pb._resolve_reachability)
    assert "icmp_check" in src, "ICMP 확인 지점이 사라졌다"
    # 호출부는 'TCP 가 아무 응답도 주지 않은' 경로 두 곳뿐이다.
    module_src = (REPO / "common" / "library" / "precheck_bundle.py").read_text(encoding="utf-8")
    call_lines = [ln.strip() for ln in module_src.splitlines()
                  if "_resolve_reachability(" in ln and "def " not in ln]
    assert len(call_lines) == 2, f"_resolve_reachability 호출부가 늘었다: {call_lines}"


def test_site_yml_rescues_reference_shared_constants_not_literals():
    """중복 문자열 정의 금지 — rescue 는 문장을 직접 쓰지 않고 카탈로그 필터를 쓴다."""
    targets = [
        ("redfish-gather/site.yml", _RF_TASK),
        ("esxi-gather/site.yml", _ESXI_TASK),
        ("os-gather/site.yml", _OS_TASKS["linux"]),
        ("os-gather/site.yml", _OS_TASKS["windows"]),
    ]
    for site, task_name in targets:
        tpl = _task_by_name(site, task_name)["ansible.builtin.set_fact"]["_diagnosis"]
        assert "_fr_catalog | failure_reason(" in tpl, (
            f"{site}:{task_name} 이 카탈로그 필터를 쓰지 않는다")
        for _k, _c, sentence in _catalog_texts():
            assert sentence not in tpl, (
                f"{site}:{task_name} 에 문구가 하드코딩됐다 — 카탈로그를 쓸 것"
            )


@pytest.mark.parametrize("site", ["redfish-gather/site.yml", "esxi-gather/site.yml",
                                  "os-gather/site.yml"])
def test_site_yml_loads_failure_reason_vars_where_needed(site):
    """정본 변수를 쓰는 play 는 반드시 그 vars_files 를 로드한다 (미정의 변수 방지).

    2026-08-12: play 본문에 `_fr_` 가 없어도 **include 로 들어오는 공통 태스크**가 쓰면
    같은 위험이다. `build_output.yml`(_fr_gather_failed) / `build_failed_output.yml`
    (_fr_output_build_failed) 를 include 하는 play 도 대상에 넣는다.
    미로드면 undefined → 태스크 실패 → **그 호스트의 envelope 전량 소실**이다.
    """
    for play in _plays(site):
        blob = yaml.safe_dump(play.get("tasks", []), allow_unicode=True)
        needs = ("_fr_" in blob
                 or "build_output.yml" in blob
                 or "build_failed_output.yml" in blob)
        if not needs:
            continue
        files = " ".join(play.get("vars_files", []))
        assert "common/vars/failure_reasons.yml" in files, (
            f"{site} 의 play '{play.get('name')}' 가 _fr_* 를 (직접 또는 include 로) 쓰는데 "
            f"vars_files 미로드 — undefined 로 envelope 이 통째로 사라진다"
        )


def test_section_message_vars_are_loaded_where_used():
    """_sm_* 정본을 쓰는 태스크 파일을 include 하는 play 는 section_messages.yml 을 로드한다."""
    users = [p for p in REPO.rglob("*.yml")
             if "common/vars" not in p.as_posix() and "docs/" not in p.as_posix()
             and "_sm_" in p.read_text(encoding="utf-8")]
    assert users, "_sm_* 사용처를 하나도 찾지 못했다 (테스트가 무의미해짐)"
    for site in ("redfish-gather/site.yml", "esxi-gather/site.yml", "os-gather/site.yml"):
        site_dir = (REPO / site).parent
        # 이 site 아래에서 _sm_* 를 쓰는 파일이 있으면 play 가 정본을 로드해야 한다
        local = [u for u in users if site_dir in u.parents or u == (REPO / site)]
        if not local:
            continue
        loaded = any("common/vars/section_messages.yml" in " ".join(p.get("vars_files", []))
                     for p in _plays(site))
        assert loaded, (
            f"{site} 아래 {[str(u.relative_to(REPO)) for u in local]} 가 _sm_* 를 쓰는데 "
            f"어떤 play 도 section_messages.yml 을 로드하지 않는다"
        )


# ═══════════════════════════════════════════════════════════════════════════
# H1 — rescue 진입이 누적된 섹션 오류를 통째로 버리지 않는다
# ═══════════════════════════════════════════════════════════════════════════
def _keep_template() -> str:
    tasks = list(yaml.safe_load_all((REPO / _BUILD_FAILED).read_text(encoding="utf-8")))[0]
    for task in _iter_tasks(tasks):
        tpl = (task.get("ansible.builtin.set_fact") or {}).get("_fail_errors")
        if isinstance(tpl, str):
            return tpl
    raise AssertionError(f"{_BUILD_FAILED} 에서 _fail_errors 템플릿을 찾지 못함")


def _render_kept(rep, all_errors):
    sys.path.insert(0, str(REPO / "filter_plugins"))
    from errors_normalizer import normalize_errors  # noqa: PLC0415

    env = _env()
    env.filters["normalize_errors"] = normalize_errors
    return env.from_string(_keep_template()).render(
        **{**FAILURE_REASONS, "_norm_errors": rep, "_all_errors": all_errors})


_REP = [{"section": "gather", "message": fr("gather_after_auth", "os"), "detail": "raw"}]


def test_failed_envelope_keeps_representative_error_first():
    kept = _render_kept(_REP, [])
    assert kept[0]["message"] == _REP[0]["message"], (
        "대표 Fatal Error 는 항상 errors[0] 이어야 한다 (Portal 이 첫 원소만 읽어도 동작 불변)"
    )


def test_failed_envelope_preserves_accumulated_section_errors():
    """종전에는 rescue 진입 순간 식별자 진단 / OEM 경고 / 섹션 실패가 통째로 사라졌다."""
    accumulated = [
        {"section": "system", "message": "시스템 제조번호를 읽을 수 없습니다. 수집 계정의 권한을 확인하세요."},
        {"section": "cpu", "message": "CPU 정보 수집에 실패한 항목이 있습니다. 대상 상태와 수집 로그를 확인하세요.",
         "detail": "Processor /x 실패: 401"},
    ]
    kept = _render_kept(_REP, accumulated)
    messages = [e["message"] for e in kept]
    assert messages[0] == _REP[0]["message"]
    for src in accumulated:
        assert src["message"] in messages, f"섹션 오류가 사라졌다: {src['message']!r}"


def test_failed_envelope_deduplicates_representative_sentence():
    """대표 원소와 **완전히 같은** 원소만 두 번 보여주지 않는다.

    2026-08-12: 중복 판정 기준을 message 단독 → (message, detail) 로 좁혔다.
    섹션 message 가 섹션당 고정 문장으로 통일된 뒤로 message 는 원소 식별자가 아니라서,
    message 만 보고 버리면 그 원소의 유일한 1차 증거인 detail 이 함께 사라진다.
    """
    exact_dup = [{"section": "gather", "message": _REP[0]["message"], "detail": _REP[0]["detail"]}]
    assert len(_render_kept(_REP, exact_dup)) == 1


def test_failed_envelope_caps_error_count():
    """Portal Grid 가 과도한 행으로 채워지지 않도록 상한을 둔다 — 단 조용히 자르지 않는다."""
    many = [{"section": "cpu", "message": f"항목 {i} 수집에 실패했습니다. 로그를 확인하세요."}
            for i in range(30)]
    kept = _render_kept(_REP, many)
    assert len(kept) == 11, "상한 10건 + 절단 사실 1건"
    assert "표시하지 않은 오류" in kept[-1]["detail"], (
        "잘렸다는 사실이 남아야 한다 (rule 70 — silent 절단 금지)"
    )
    # 절단 행은 대표 실패 문장을 빌려 쓰지 않는다 (2026-09-21 — 인증 실패 envelope 에
    # '로그인했지만' 같은 문장이 섞이면 서로 반대되는 이야기가 된다).
    assert kept[-1]["message"] == FAILURE_REASONS["_fr_errors_truncated"]


def test_failed_envelope_keeps_distinct_details_even_with_same_message():
    """섹션 message 가 고정 문장이라 message 만으로 중복 판정하면 유일한 증거가 사라진다."""
    same_msg = _REP[0]["message"]
    accumulated = [{"section": "cpu", "message": same_msg, "detail": "IMPORTANT EVIDENCE"}]
    kept = _render_kept(_REP, accumulated)
    assert any((e.get("detail") or "").find("IMPORTANT EVIDENCE") >= 0 for e in kept), kept


def test_failed_envelope_errors_all_have_usable_messages():
    """보존한 원소도 message 계약(비지 않은 문자열)을 지킨다."""
    messy = [{"section": "cpu"}, {"section": "memory", "message": None}, 42, None]
    kept = _render_kept(_REP, messy)
    for entry in kept:
        assert isinstance(entry["message"], str) and entry["message"].strip()
        assert entry["detail"] is None or isinstance(entry["detail"], str)


# ═══════════════════════════════════════════════════════════════════════════
# H12 — status=failed 인데 failure_* 가 전부 null 인 envelope 을 만들지 않는다
# ═══════════════════════════════════════════════════════════════════════════
_BUILD_OUTPUT = "common/tasks/normalize/build_output.yml"
_ENSURE_TASK = "build_output | ensure failed diagnosis"


def _ensure_failed_task() -> dict[str, Any]:
    tasks = list(yaml.safe_load_all((REPO / _BUILD_OUTPUT).read_text(encoding="utf-8")))[0]
    for task in _iter_tasks(tasks):
        if _ENSURE_TASK in (task.get("name") or ""):
            return task
    raise AssertionError(f"{_BUILD_OUTPUT} 에서 '{_ENSURE_TASK}' 태스크를 찾지 못함")


def _render_ensure(diag, status):
    task = _ensure_failed_task()
    tpl = task["ansible.builtin.set_fact"]["_diagnosis"]
    return _env().from_string(tpl).render(
        **{**FAILURE_REASONS, "_diagnosis": diag, "_out_status": status})


def _ensure_guard_fires(diag, status) -> bool:
    conds = _ensure_failed_task()["when"]
    for cond in conds:
        got = _env().from_string("{{ " + cond + " }}").render(
            **{**FAILURE_REASONS, "_diagnosis": diag, "_out_status": status})
        if got is not True:
            return False
    return True


_SUCCESS_PATH_DIAG = {
    "reachable": True, "port_open": True, "protocol_supported": True,
    "auth_success": True, "failure_stage": None, "failure_code": None,
    "failure_reason": None, "details": {"channel": "os"},
}


def test_normal_path_failed_status_gets_failure_fields():
    """정상 build_output 경로로 status=failed 가 되는 케이스 (supported 0건 / success 0건).

    이 경로는 rescue 가 아니라서 rescue 의 when 가드가 닿지 않는다. 종전에는 성공 경로
    diagnosis(failure_* 전부 null)가 그대로 실려 CLAUDE.md §9 를 정면으로 깼다.
    """
    assert _ensure_guard_fires(_SUCCESS_PATH_DIAG, "failed") is True
    diag = _render_ensure(_SUCCESS_PATH_DIAG, "failed")
    assert diag["failure_stage"] == "gather"
    assert diag["failure_code"] == "GATHER_FAILED"
    # 예외 없이 끝났는데 성공 섹션이 0개 → '수집된 정보가 없다' (2026-09-21)
    assert diag["failure_reason"] == fr("gather_no_data")
    _assert_grid_ready(diag["failure_reason"], "build_output/failed")
    # 앞 단계 관측은 보존한다
    assert diag["reachable"] is True and diag["port_open"] is True
    # 인증 거부를 관측한 근거가 없으므로 손대지 않는다
    assert diag["auth_success"] is True
    assert diag["details"] == {"channel": "os"}


@pytest.mark.parametrize("status", ["success", "partial"])
def test_success_and_partial_are_untouched(status):
    assert _ensure_guard_fires(_SUCCESS_PATH_DIAG, status) is False


def test_precheck_reason_is_not_overwritten():
    diag = {**_SUCCESS_PATH_DIAG, "failure_stage": "protocol",
            "failure_code": "PROTOCOL_CHECK_FAILED",
            "failure_reason": fr("protocol_unconfirmed", "os")}
    assert _ensure_guard_fires(diag, "failed") is False


def test_ensure_failed_diagnosis_keeps_eight_key_shape():
    """_diagnosis 가 비-mapping 이어도 8키 shape 를 잃지 않는다 (NEW-2)."""
    diag = _render_ensure(None, "failed")
    assert set(diag) == {"reachable", "port_open", "protocol_supported", "auth_success",
                         "failure_stage", "failure_code", "failure_reason", "details"}


def test_no_secrets_in_rendered_errors():
    for label, diag, message, detail in _CASES:
        blob = str(_render_error(_ctx(diag, message, detail)))
        for secret in ("password", "Passw0rd", "Authorization", "Cookie", "Basic ", "token"):
            assert secret not in blob, f"[{label}] 민감정보 노출: {secret}"
