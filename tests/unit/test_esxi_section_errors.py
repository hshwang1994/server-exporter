"""ESXi 섹션 단위 errors[] 계약 (2026-08-12).

무엇을 고정하는가
-----------------
전체 실패(status=failed)의 대표 사유는 `common/vars/failure_reasons.yml` 6문장이 정본이고
`tests/e2e/test_failure_reason_contract.py` 가 검사한다. 이 파일은 그 **밖**, 즉 수집은
됐는데 일부만 실패한 경우 ESXi 채널이 `errors[]` 에 싣는 문장을 고정한다.

종전 상태 (모두 실제로 나가던 결과):

  1. H8  — `normalize_storage.yml` 이 "datastore capacity 미수집 (type/accessible 보존,
           size=null): " 뒤에 datastore 이름을 **개수 제한 없이** 붙였다. 괄호 안은
           envelope 내부 필드를 설명하는 개발자 메모이고 문장 길이는 예측 불가였다.
  2. C5/N32 — `vmware_datastore_info` 가 실패하면 storage 섹션이 failed 로 표시되는데
           `_e_unsized_ds` 가 비어 errors 가 0건이 될 수 있었다. Portal 은 "부분 실패" 를
           띄우고 사유 칸은 공백이었다.
  3. N36 — `esxi_disks` 모듈이 어떤 예외든 성공으로 반환했고, 그 결과를 받는
           `_e_disks_ok` / `_e_config_ok` / `_e_dns_ok` 는 소비처가 0건이었다 (침묵 실패).
  4. M1/N33 — 확장 네트워크 rescue 가 `section: esxi_network_extended` (schema 밖) 와
           "best-effort skip" 이라는 개발자 용어를 그대로 사용자 문장에 실었다.

렌더는 합성 fixture 가 아니라 **production YAML 자체**를 추출해 수행한다.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.e2e.test_failure_reason_contract import (
    _assert_grid_ready,
    _assert_no_ports,
    _assert_no_technical_noise,
    _env,
    _iter_tasks,
)

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "filter_plugins"))
from errors_normalizer import normalize_errors  # noqa: E402

# schema/sections.yml 의 11 섹션. errors[].section 은 여기서 벗어나지 않는다.
SCHEMA_SECTIONS = {
    "system", "hardware", "bmc", "cpu", "memory", "storage",
    "network", "firmware", "users", "power", "thermal",
}

_STORAGE = "esxi-gather/tasks/normalize_storage.yml"
_STORAGE_TASK = "esxi | normalize storage | build fragment"
_DISKS = "esxi-gather/tasks/collect_disks.yml"
_DISKS_TASK = "esxi | collect | build disks errors fragment"
_DISKS_RAW_TASK = "esxi | collect | store raw disks/controllers/ports"
_NET = "esxi-gather/tasks/normalize_network.yml"
_NET_TASK = "esxi | normalize network | build fragment"
_EXT = "esxi-gather/tasks/collect_network_extended.yml"
_EXT_TASK = "esxi | extended | rescue"


# ---------------------------------------------------------------------------
# production YAML 추출 / 렌더
# ---------------------------------------------------------------------------
def _tasks(rel: str):
    return list(_iter_tasks(list(yaml.safe_load_all(
        (REPO / rel).read_text(encoding="utf-8")))[0]))


def _template(rel: str, needle: str, key: str) -> Any:
    for task in _tasks(rel):
        if needle in (task.get("name") or ""):
            return task["ansible.builtin.set_fact"][key]
    raise AssertionError(f"{rel} 에서 태스크를 찾지 못함: {needle!r}")


def _render(rel: str, needle: str, key: str, ctx: dict[str, Any]) -> Any:
    tpl = _template(rel, needle, key)
    if not isinstance(tpl, str):
        return tpl
    return _env().from_string(tpl).render(**ctx)


def _errors(rel: str, needle: str, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """`_errors_fragment` 를 렌더한 뒤 merge_fragment 와 같은 정규화를 통과시킨다."""
    return normalize_errors(_render(rel, needle, "_errors_fragment", ctx))


def _assert_section_error(entry: dict[str, Any], label: str) -> None:
    """섹션 단위 errors[] 1건이 지켜야 할 계약."""
    message = entry["message"]
    _assert_grid_ready(message, label)
    _assert_no_ports(message, label)
    _assert_no_technical_noise(message, label)
    assert "[task:" not in message, f"[{label}] 내부 태스크명 노출: {message!r}"
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", message), f"[{label}] IP 노출"
    assert ".." not in message, f"[{label}] 이중 마침표: {message!r}"
    assert entry["section"] in SCHEMA_SECTIONS, (
        f"[{label}] errors[].section 이 schema 11 섹션 밖이다: {entry['section']!r} — "
        f"Portal 이 어느 섹션에도 묶지 못한다"
    )
    detail = entry["detail"]
    assert detail is None or (isinstance(detail, str) and detail.strip()), (
        f"[{label}] detail 은 비지 않은 문자열이거나 null 이어야 한다: {detail!r}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# H8 — datastore 이름은 message 가 아니라 detail 이 보존한다
# ═══════════════════════════════════════════════════════════════════════════
_UNSIZED = ["nfs-vol-01", "vsan-datastore", "vvol-prod"]


def _storage(ds_ok: bool, ds_err: Any, unsized: list[str]) -> list[dict[str, Any]]:
    return _errors(_STORAGE, _STORAGE_TASK,
                   {"_e_ds_ok": ds_ok, "_e_ds_err": ds_err, "_e_unsized_ds": unsized})


def test_unsized_datastore_warning_is_a_fixed_sentence():
    out = _storage(True, None, _UNSIZED)
    assert len(out) == 1
    _assert_section_error(out[0], "storage/unsized")
    for name in _UNSIZED:
        assert name not in out[0]["message"], "datastore 이름이 사용자 문장에 붙었다"
        assert name in out[0]["detail"], "datastore 이름이 detail 에서 사라졌다"


def test_unsized_datastore_message_length_is_independent_of_count():
    """이름을 concat 하면 문장 길이가 datastore 수에 비례해 늘어났다 (H8)."""
    few = _storage(True, None, ["a"])[0]["message"]
    many = _storage(True, None, [f"datastore-{i:03d}" for i in range(200)])[0]["message"]
    assert few == many, "datastore 개수가 문장을 바꾸면 안 된다"


def test_unsized_datastore_detail_is_capped():
    out = _storage(True, None, [f"datastore-{i:03d}" for i in range(200)])
    assert len(out[0]["detail"]) <= 500, "detail 상한 500자를 넘겼다"


def test_unsized_datastore_message_has_no_internal_field_names():
    """'type/accessible 보존, size=null' 같은 envelope 내부 필드 설명을 쓰지 않는다."""
    message = _storage(True, None, _UNSIZED)[0]["message"]
    for token in ("size=null", "accessible", "capacity", "type/", "null"):
        assert token not in message, f"내부 필드 설명이 남아 있다: {token!r} in {message!r}"


def test_no_error_when_every_datastore_reports_capacity():
    assert _storage(True, None, []) == []


# ═══════════════════════════════════════════════════════════════════════════
# C5 / N32 — 섹션이 failed 인데 errors 가 비는 일이 없어야 한다
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("ds_err", ["Unable to connect to ESXi host", None])
def test_datastore_module_failure_always_emits_one_error(ds_err):
    out = _storage(False, ds_err, [])
    assert len(out) == 1, (
        "datastore 수집이 실패했는데 errors 가 비었다 — "
        "Portal 이 사유 없는 부분 실패를 띄운다 (C5/N32)"
    )
    _assert_section_error(out[0], "storage/module-failed")
    assert out[0]["section"] == "storage"
    assert out[0]["detail"] == ds_err


def test_datastore_failure_takes_priority_over_capacity_warning():
    """모듈 실패가 우선. 두 문장을 동시에 내보내 사용자를 헷갈리게 하지 않는다."""
    out = _storage(False, "boom", _UNSIZED)
    assert len(out) == 1
    assert "실패" in out[0]["message"]


def test_datastore_module_message_does_not_leak_module_error():
    out = _storage(False, "MODULE FAILURE\nTraceback (most recent call last):", [])
    assert "Traceback" not in out[0]["message"]
    assert "Traceback" in out[0]["detail"], "기술 근거는 detail 에 보존한다"


@pytest.mark.parametrize("raw,expected", [
    ({"msg": "  MODULE FAILURE  "}, "MODULE FAILURE"),
    ({"msg": ""}, None),
    ({"msg": None}, None),
    ({}, None),
])
def test_datastore_error_detail_is_string_or_null(raw, expected):
    """빈 문자열 detail 을 만들지 않는다 (문자열 또는 null)."""
    got = _render("esxi-gather/tasks/collect_datastores.yml",
                  "esxi | collect | store raw datastores", "_e_ds_err",
                  {"_e_ds_result": raw})
    assert got == expected


# ═══════════════════════════════════════════════════════════════════════════
# N36 (b) — esxi_disks 실패가 errors[] 로 승격된다 (섹션 status 는 그대로)
# ═══════════════════════════════════════════════════════════════════════════
def _disks(parts: list[str], err: Any = "boom") -> list[dict[str, Any]]:
    return _errors(_DISKS, _DISKS_TASK,
                   {"_e_disks_failed_parts": parts, "_e_disks_err": err})


@pytest.mark.parametrize("parts,sections", [
    (["physical_disks"], {"storage"}),
    (["controllers"], {"storage"}),
    (["listening_ports"], {"system"}),
    (["controllers", "listening_ports"], {"storage", "system"}),
    (["connect"], {"storage", "system"}),
])
def test_disks_failure_is_promoted_to_errors(parts, sections):
    out = _disks(parts)
    assert out, f"{parts} 실패가 errors 에 안 남았다 (침묵 실패 — N36)"
    for entry in out:
        _assert_section_error(entry, f"disks/{parts}")
        assert entry["detail"] == "boom", "모듈 사유가 detail 에서 사라졌다"
    assert {e["section"] for e in out} == sections


def test_disks_success_emits_nothing():
    assert _disks([], None) == []


def test_disks_fragment_does_not_change_section_status():
    """datastore 는 성공했는데 물리 디스크만 실패한 부분 실패다.

    섹션 전체를 failed 로 강등하면 과잉이라 `_sections_*_fragment` 는 비어 있어야 한다.
    """
    task = next(t for t in _tasks(_DISKS) if _DISKS_TASK in (t.get("name") or ""))
    facts = task["ansible.builtin.set_fact"]
    for key in ("_sections_supported_fragment", "_sections_collected_fragment",
                "_sections_failed_fragment"):
        assert facts[key] == [], f"{key} 가 비어 있지 않다 — 섹션 status 를 바꾸면 안 된다"


def test_disks_errors_fragment_is_followed_by_merge():
    """rule 22 — `_errors_fragment` 를 set 한 자리 뒤에는 merge_fragment 호출이 온다."""
    names = [t.get("name") or "" for t in _tasks(_DISKS)]
    idx = next(i for i, n in enumerate(names) if _DISKS_TASK in n)
    rest = " ".join(names[idx + 1:])
    assert "merge" in rest, "fragment 를 만들고 merge 를 호출하지 않으면 누적되지 않는다"


@pytest.mark.parametrize("result,expected", [
    ({"physical_disks": [], "failed_parts": ["connect"], "error": "x"}, ["connect"]),
    ({"physical_disks": [], "failed_parts": ["listening_ports"], "error": "x"},
     ["listening_ports"]),
    # 구버전 모듈(failed_parts 미반환) 은 error 키만으로 최소 판정한다
    ({"physical_disks": [], "error": "legacy"}, ["connect"]),
    ({"physical_disks": [{"id": "naa.1"}]}, []),
])
def test_failed_parts_wiring(result, expected):
    got = _render(_DISKS, _DISKS_RAW_TASK, "_e_disks_failed_parts",
                  {"_e_disks_result": result})
    assert list(got) == expected


# ═══════════════════════════════════════════════════════════════════════════
# N36 (a) — 모듈이 파트별 실패를 격리해 보고한다
# ═══════════════════════════════════════════════════════════════════════════
class _ExitJson(Exception):
    """AnsibleModule.exit_json 대역 — 반환 payload 를 그대로 들고 나온다."""

    def __init__(self, payload):
        super().__init__("exit_json")
        self.payload = payload


class _StubAnsibleModule:
    def __init__(self, argument_spec=None, supports_check_mode=False):
        self.params = dict(hostname="host", username="u", password="p",
                           port=443, validate_certs=False)

    def exit_json(self, **kwargs):
        raise _ExitJson(kwargs)

    def fail_json(self, **kwargs):
        raise _ExitJson(dict(kwargs, _failed=True))


def _load_module():
    """ansible / pyvmomi 를 스텁으로 채우고 esxi_disks 를 import (한 번만)."""
    import types

    basic = sys.modules.get("ansible.module_utils.basic")
    if basic is None:
        basic = types.ModuleType("ansible.module_utils.basic")
        utils = types.ModuleType("ansible.module_utils")
        utils.basic = basic
        root = types.ModuleType("ansible")
        root.module_utils = utils
        sys.modules["ansible"] = root
        sys.modules["ansible.module_utils"] = utils
        sys.modules["ansible.module_utils.basic"] = basic
    basic.AnsibleModule = _StubAnsibleModule

    if "pyVim.connect" not in sys.modules:
        connect = types.ModuleType("pyVim.connect")
        connect.SmartConnect = lambda **kw: None
        connect.Disconnect = lambda si: None
        pyvim = types.ModuleType("pyVim")
        pyvim.connect = connect
        sys.modules["pyVim"] = pyvim
        sys.modules["pyVim.connect"] = connect
        pyvmomi = types.ModuleType("pyVmomi")
        pyvmomi.vim = types.SimpleNamespace()
        sys.modules["pyVmomi"] = pyvmomi

    library = str(REPO / "esxi-gather" / "library")
    if library not in sys.path:
        sys.path.insert(0, library)
    import esxi_disks  # noqa: E402

    # 다른 테스트가 이미 import 해 뒀을 수 있으므로 진입점을 매번 스텁으로 고정한다.
    esxi_disks.AnsibleModule = _StubAnsibleModule
    esxi_disks.HAS_PYVMOMI = True
    return esxi_disks


def _run_module(disks=None, controllers=None, ports=None, connect_fail=False):
    module = _load_module()

    class _ServiceInstance:
        def RetrieveContent(self):
            return object()

    def _connect(**_kwargs):
        if connect_fail:
            raise RuntimeError("Cannot complete login")
        return _ServiceInstance()

    module.SmartConnect = _connect
    module.Disconnect = lambda si: None
    module._build_disks = disks or (lambda c: [{"id": "naa.1"}])
    module._build_controllers = controllers or (lambda c: [{"id": "vmhba0"}])
    module._build_listening_ports = ports or (lambda c: ["443"])
    try:
        module.main()
    except _ExitJson as exc:
        return exc.payload
    raise AssertionError("exit_json 이 호출되지 않았다")


def _boom(message):
    def _fn(_content):
        raise RuntimeError(message)
    return _fn


def test_module_reports_success_without_error_key():
    got = _run_module()
    assert got["connect_ok"] is True
    assert got["failed_parts"] == []
    assert "error" not in got


def test_module_isolates_one_failing_part():
    """listening_ports 하나가 죽어도 이미 만든 디스크/컨트롤러는 살아남는다."""
    got = _run_module(ports=_boom("firewall denied"))
    assert got["physical_disks"] == [{"id": "naa.1"}]
    assert got["controllers"] == [{"id": "vmhba0"}]
    assert got["listening_ports"] == []
    assert got["failed_parts"] == ["listening_ports"]
    assert "firewall denied" in got["error"]


def test_module_distinguishes_connect_failure_from_part_failure():
    got = _run_module(connect_fail=True)
    assert got["connect_ok"] is False
    assert got["failed_parts"] == ["connect"]
    assert got["physical_disks"] == [] and got["listening_ports"] == []

    got = _run_module(disks=_boom("scsiLun denied"))
    assert got["connect_ok"] is True
    assert got["failed_parts"] == ["physical_disks"]
    assert got["listening_ports"] == ["443"], "다른 파트까지 같이 죽으면 안 된다"


def test_module_keeps_existing_return_keys():
    """반환 키는 추가만 한다 (삭제/리네임 금지) — 기존 소비처 보존."""
    got = _run_module()
    for key in ("physical_disks", "disk_count", "controllers", "listening_ports"):
        assert key in got, f"기존 반환 키 {key} 가 사라졌다"


def test_module_failed_parts_is_deterministic():
    got = _run_module(disks=_boom("a"), ports=_boom("b"))
    assert got["failed_parts"] == ["listening_ports", "physical_disks"]


# ═══════════════════════════════════════════════════════════════════════════
# N36 (c) — dns / config 플래그 배선. 성공한 fallback 은 error 가 아니다
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("servers,dns_ok,config_ok,expected", [
    (["10.0.0.1"], True, True, 0),     # 정상
    (["10.0.0.1"], False, True, 0),    # 1순위 실패 + 폴백 성공 = 성공한 fallback
    ([], True, True, 0),               # 두 경로 모두 성공 + 결과 없음 = 실제 미설정
    ([], False, True, 1),
    ([], True, False, 1),
    ([], False, False, 1),
])
def test_dns_error_only_when_result_empty_and_a_source_failed(
        servers, dns_ok, config_ok, expected):
    out = _errors(_NET, _NET_TASK, {
        "_e_dns_servers": servers, "_e_dns_ok": dns_ok, "_e_config_ok": config_ok})
    assert len(out) == expected, (servers, dns_ok, config_ok, out)
    for entry in out:
        _assert_section_error(entry, "network/dns")
        assert entry["section"] == "network"


def test_dns_error_does_not_change_section_status():
    facts = _template(_NET, _NET_TASK, "_sections_collected_fragment")
    assert facts == ["network"]
    assert _template(_NET, _NET_TASK, "_sections_failed_fragment") == []


def test_dns_flags_are_actually_consumed():
    """`_e_dns_ok` / `_e_config_ok` 가 다시 죽은 변수로 돌아가지 않게 고정한다."""
    text = (REPO / _NET).read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))
    for flag in ("_e_dns_ok", "_e_config_ok"):
        assert flag in body, f"{flag} 이 주석 밖에서 소비되지 않는다 (N36)"


# ═══════════════════════════════════════════════════════════════════════════
# M1 / N33 — 확장 네트워크 rescue
# ═══════════════════════════════════════════════════════════════════════════
def _extended(failed_msg: dict[str, Any]) -> list[dict[str, Any]]:
    raw = _template(_EXT, _EXT_TASK, "_errors_fragment")
    rendered = []
    for item in raw:
        entry = dict(item)
        if isinstance(entry.get("detail"), str):
            entry["detail"] = _env().from_string(entry["detail"]).render(
                ansible_failed_result=failed_msg)
        rendered.append(entry)
    return normalize_errors(rendered)


def test_extended_rescue_message_is_user_facing():
    out = _extended({"msg": "vmnic module crashed"})
    assert len(out) == 1
    _assert_section_error(out[0], "extended/rescue")
    message = out[0]["message"]
    for token in ("best-effort", "skip", "vmnic", "vmhba", "vSwitch", "portgroup"):
        assert token not in message, f"개발자 용어가 남아 있다: {token!r} in {message!r}"
    assert out[0]["detail"] == "vmnic module crashed"


def test_extended_rescue_section_is_schema_section():
    out = _extended({"msg": "x"})
    assert out[0]["section"] == "network", (
        "esxi_network_extended 는 schema 11 섹션 밖이라 Portal 이 묶지 못한다 (M1)"
    )


@pytest.mark.parametrize("failed", [{"msg": ""}, {}])
def test_extended_rescue_detail_is_null_when_empty(failed):
    assert _extended(failed)[0]["detail"] is None, "빈 문자열 detail 을 만들지 않는다"


def test_extended_rescue_keeps_network_section_status():
    """확장 수집 실패로 기본 network 정보까지 partial 로 강등하지 않는다."""
    task = next(t for t in _tasks(_EXT) if _EXT_TASK in (t.get("name") or ""))
    assert task["ansible.builtin.set_fact"]["_sections_failed_fragment"] == []
