"""BIOS Current Attributes 가 실제 Ansible 템플릿 경로를 지나도 원본 그대로인지 (2026-09-15).

경로 — 운영 파일에서 템플릿 원문을 꺼내 실제 ansible-core 템플릿 엔진으로 렌더한다:

    redfish_gather 모듈 data.bios
      → redfish-gather/tasks/normalize_standard.yml  `_data_fragment.bios`  (단일 표현식 passthrough)
      → common/tasks/normalize/merge_fragment.yml     `_merged_data`         (새 키 통째 삽입)
      → common/tasks/normalize/build_output.yml       `_output`              ('data': _merged_data)
      → redfish-gather/site.yml                       schema_version 주입 / OUTPUT msg (`| to_json`)
      → callback_plugins/json_only.py                 `_emit` (json.loads → json.dumps)

마지막 JSON 을 다시 파싱해 source Attributes 와 **값·자료형까지** 비교한다
(`==` 는 False 와 0, True 와 1 을 같게 보므로 자료형 트리를 따로 비교한다).

G1 기술 경계 (사용자 결정 2026-09-15 — 문서화 전용, 제품 코드 대응 없음)
-------------------------------------------------------------------------
AnsibleModule 은 exit_json 결과 전체에 no_log 파라미터 값 치환(remove_values)을 적용한다.
redfish_gather 의 no_log 파라미터는 password 계열뿐이며, 그 값과 **같거나 그 값을 포함하는**
문자열·숫자만 바뀐다. 제품 코드는 비밀번호를 비교·검출하지 않는다 — 아래 테스트는 경계를
기록할 뿐이다. 실제 수집 계정 비밀번호는 쓰지 않는다(합성 값).
"""
from __future__ import annotations

import ast
import copy
import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.e2e.test_diagnosis_template_ansible_render import _iter_tasks, _templar, _trust

REPO = Path(__file__).resolve().parents[2]

FAILURE_REASONS: dict[str, Any] = yaml.safe_load(
    (REPO / "common/vars/failure_reasons.yml").read_text(encoding="utf-8"))

# 지시서 13.1
SAMPLE = {
    "StringValue": "Enabled",
    "StringZero": "0",
    "IntegerZero": 0,
    "BooleanTrue": True,
    "BooleanFalse": False,
    "EmptyString": "",
    "NullValue": None,
    "LeadingZero": "00000",
    "DecimalText": "00.00",
}


def _doc(rel: str):
    return list(yaml.safe_load_all((REPO / rel).read_text(encoding="utf-8")))[0]


def _task(rel: str, name: str) -> dict[str, Any]:
    for task in _iter_tasks(_doc(rel)):
        if task.get("name") == name:
            return task
    raise AssertionError(f"{rel}: 태스크를 찾지 못함 {name!r}")


def _set_fact(rel: str, name: str, key: str):
    return _task(rel, name)["ansible.builtin.set_fact"][key]


def _type_tree(value):
    if isinstance(value, dict):
        return {k: _type_tree(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_type_tree(v) for v in value]
    return type(value).__name__


def _json_only():
    sys.path.insert(0, str(REPO / "callback_plugins"))
    try:
        import json_only  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - 플랫폼 의존
        pytest.skip(f"json_only 콜백을 불러올 수 없다: {exc}")
    return json_only


def _render_to_final_json(module_bios: Any) -> dict[str, Any]:
    """모듈 data.bios → 최종 json_only 출력(파싱본). 각 단계는 운영 템플릿 원문이다."""
    templar = _templar()

    # 1) normalize_standard — `bios` 한 줄만 렌더한다 (나머지 키는 이 계약과 무관)
    frag = _set_fact("redfish-gather/tasks/normalize_standard.yml",
                     "redfish | normalize_standard | build standard fragment", "_data_fragment")
    templar.available_variables = {"_rf_raw_collect": {"data": {"bios": module_bios}}}
    bios_fragment = templar.template(_trust(frag["bios"]))

    # 2) merge_fragment — init_fragments 뼈대 위에 병합
    skeleton = copy.deepcopy(_set_fact("common/tasks/normalize/init_fragments.yml",
                                       "normalize | init_fragments", "_merged_data"))
    templar.available_variables = {
        "_merged_data": skeleton,
        "_data_fragment": {"bios": bios_fragment, "system": {"fqdn": "host.example"}},
    }
    merged = templar.template(_trust(_set_fact(
        "common/tasks/normalize/merge_fragment.yml", "normalize | merge_fragment | merge data",
        "_merged_data")))

    # 3) build_output
    templar.available_variables = {
        "_out_target_type": "redfish", "_out_collection_method": "redfish_api",
        "_out_ip": "10.0.0.1", "_out_hostname": "host.example", "_out_vendor": "dell",
        "_out_status": "success", "_out_hostname_source": "system",
        "_norm_sections": {"system": "not_supported", "hardware": "success"},
        "_diagnosis": {"reachable": True, "port_open": True, "protocol_supported": True,
                       "auth_success": True, "failure_stage": None, "failure_code": None,
                       "failure_reason": None, "details": {}},
        "_meta": {}, "_correlation": {}, "_norm_errors": [], "_merged_data": merged,
    }
    output = templar.template(_trust(_set_fact(
        "common/tasks/normalize/build_output.yml", "normalize | build_output", "_output")))

    # 4) site.yml — schema_version 주입 → OUTPUT msg
    templar.available_variables = {"_output": output}
    output = templar.template(_trust(_set_fact(
        "redfish-gather/site.yml", "redfish | inject schema_version", "_output")))
    msg_tpl = _task("redfish-gather/site.yml", "OUTPUT")["ansible.builtin.debug"]["msg"]
    variables = dict(FAILURE_REASONS)
    variables.update({"_output": output, "_rf_ip": "10.0.0.1", "inventory_hostname": "10.0.0.1"})
    templar.available_variables = variables
    msg = templar.template(_trust(msg_tpl))
    assert isinstance(msg, str), f"OUTPUT msg 는 to_json 문자열이어야 한다: {type(msg)}"

    # 5) json_only 콜백
    buf = io.StringIO()
    _json_only().CallbackModule()._emit(msg, file=buf)
    lines = [line for line in buf.getvalue().splitlines() if line.strip()]
    assert len(lines) == 1
    return json.loads(lines[0])


def test_attributes_survive_the_whole_ansible_path_with_types():
    source = copy.deepcopy(SAMPLE)
    final = _render_to_final_json({"current": {"attributes": source}})

    got = final["data"]["bios"]
    assert got == {"current": {"attributes": SAMPLE}}
    assert _type_tree(got) == _type_tree({"current": {"attributes": SAMPLE}})
    assert list(got["current"]["attributes"]) == list(SAMPLE)
    # 보조 데이터 — sections 에 bios 가 생기지 않는다
    assert "bios" not in final["sections"]
    assert source == SAMPLE, "렌더 과정이 원본 dict 를 바꾸면 안 된다"


@pytest.mark.parametrize("module_bios", [
    {"current": {"attributes": None}},
    {"current": {"attributes": {}}},
], ids=["attributes-null", "attributes-empty"])
def test_null_and_empty_attributes_are_not_confused(module_bios):
    """null(조회 못 함)과 {}(장비가 빈 목록을 줌)는 다른 사실이다 — truthiness 로 뭉개지지 않는다."""
    final = _render_to_final_json(copy.deepcopy(module_bios))
    assert final["data"]["bios"] == module_bios
    assert _type_tree(final["data"]["bios"]) == _type_tree(module_bios)


def test_large_attributes_survive_the_whole_ansible_path():
    """지시서 13.4 — 1,223개 이상·약 100KB 가 개수·값·자료형 그대로 도착한다."""
    source = {}
    for i in range(1400):
        kind = i % 7
        key = f"Attribute_{i:04d}_" + "K" * 32
        source[key] = ("V" * 120 + str(i), i, i % 2 == 0, None, "", f"{i:05d}", i + 0.5)[kind]
    assert len(json.dumps(source)) >= 90_000

    final = _render_to_final_json({"current": {"attributes": copy.deepcopy(source)}})
    attrs = final["data"]["bios"]["current"]["attributes"]
    assert len(attrs) == len(source)
    assert list(attrs) == list(source)
    assert _type_tree(attrs) == _type_tree(source) and attrs == source


# ═══════════════════════════════════════════════════════════════════════════
# G1 기술 경계 — 문서화 테스트 (제품 코드에는 비교·검출 로직이 없다)
# ═══════════════════════════════════════════════════════════════════════════
def _module_no_log_params() -> set[str]:
    """redfish_gather.main() 의 argument_spec 에서 no_log=True 인 파라미터 이름."""
    tree = ast.parse((REPO / "redfish-gather/library/redfish_gather.py").read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "argument_spec" \
                and isinstance(node.value, ast.Call):
            for param in node.value.keywords:
                opts = param.value
                if isinstance(opts, ast.Call) and any(
                        k.arg == "no_log" and isinstance(k.value, ast.Constant) and k.value.value is True
                        for k in opts.keywords):
                    names.add(param.arg)
    return names


def _no_log_tools():
    try:
        from ansible.module_utils.common.parameters import (  # noqa: PLC0415
            _list_no_log_values,
            remove_values,
        )
    except Exception as exc:  # pragma: no cover - ansible-core 내부 경로 변경 시
        pytest.skip(f"ansible-core no_log 치환 함수를 불러올 수 없다: {exc}")
    return _list_no_log_values, remove_values


def test_g1_boundary_only_password_parameters_are_no_log():
    assert _module_no_log_params() == {"password", "target_password"}, (
        "no_log 파라미터가 바뀌면 G1 경계 문서(field_dictionary / 03-fields.md)도 다시 봐야 한다")


def test_g1_boundary_replaces_only_values_matching_the_password():
    list_no_log_values, remove_values = _no_log_tools()
    spec = {"password": {"type": "str", "no_log": True},
            "target_password": {"type": "str", "no_log": True, "default": ""}}
    password = "Synthetic-Pw0rd-2026"   # 합성 값 — 실제 계정 비밀번호가 아니다
    attributes = copy.deepcopy(SAMPLE)
    attributes.update({"SameAsPassword": password,
                       "ContainsPassword": "prefix-" + password + "-suffix"})
    result = {"status": "success", "data": {"bios": {"current": {"attributes": attributes}}}}

    no_log_values = list_no_log_values(spec, {"password": password, "target_password": ""})
    scrubbed = json.loads(json.dumps(remove_values(result, no_log_values)))
    got = scrubbed["data"]["bios"]["current"]["attributes"]

    # 비밀번호와 무관한 값은 값·자료형 그대로
    unrelated = {k: got[k] for k in SAMPLE}
    assert unrelated == SAMPLE and _type_tree(unrelated) == _type_tree(SAMPLE)
    # 경계: 비밀번호와 같거나 포함하는 값만 치환된다. Key 이름·순서는 그대로다.
    assert list(got) == list(attributes)
    assert got["SameAsPassword"] == "VALUE_SPECIFIED_IN_NO_LOG_PARAMETER"
    assert got["ContainsPassword"] == "prefix-********-suffix"


def test_g1_boundary_numbers_containing_the_password_become_strings():
    list_no_log_values, remove_values = _no_log_tools()
    spec = {"password": {"type": "str", "no_log": True}}
    no_log_values = list_no_log_values(spec, {"password": "7351"})   # 합성 숫자형 비밀번호
    got = remove_values({"PortNumber": 17351, "Other": 42, "Flag": True, "Nothing": None},
                        no_log_values)
    assert got["PortNumber"] == "VALUE_SPECIFIED_IN_NO_LOG_PARAMETER"   # 숫자 → 문자열
    assert got["Other"] == 42 and type(got["Other"]) is int
    assert got["Flag"] is True and got["Nothing"] is None


def test_g1_boundary_empty_password_is_not_registered():
    """무인증 probe / 빈 자격 시도는 치환 대상 값이 없어 결과가 그대로다."""
    list_no_log_values, remove_values = _no_log_tools()
    spec = {"password": {"type": "str", "no_log": True},
            "target_password": {"type": "str", "no_log": True, "default": ""}}
    no_log_values = list_no_log_values(spec, {"password": "", "target_password": ""})
    assert not no_log_values
    result = {"data": {"bios": {"current": {"attributes": copy.deepcopy(SAMPLE)}}}}
    scrubbed = json.loads(json.dumps(remove_values(result, no_log_values)))
    assert scrubbed == result and _type_tree(scrubbed) == _type_tree(result)
