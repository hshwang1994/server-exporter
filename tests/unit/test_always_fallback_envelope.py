"""site.yml `always` 최종 fallback envelope — 실제 표현식 렌더 (2026-09-03, B-01/B-04).

종전 `test_envelope_failure_modes.py` 는 손으로 만든 fixture 를 검사해 `hostname: <IP>` /
`sections: {}` / `data: {}` 를 잡지 못했다. 여기서는 3 채널 site.yml 의 OUTPUT 태스크 msg 를
추출해 `_output` 미정의 상태로 렌더하고, rescue 경로(build_failed_output)와 같은 shape 인지 본다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jinja2.nativetypes import NativeEnvironment

REPO = Path(__file__).resolve().parents[2]
SITES = {
    "os": REPO / "os-gather" / "site.yml",
    "esxi": REPO / "esxi-gather" / "site.yml",
}
INIT = REPO / "common" / "tasks" / "normalize" / "init_fragments.yml"
ALL_SECTIONS = ["system", "hardware", "bmc", "cpu", "memory", "storage", "network", "firmware", "users", "power", "thermal"]


def _skeleton() -> dict:
    for t in yaml.safe_load(INIT.read_text(encoding="utf-8")):
        sf = (t or {}).get("ansible.builtin.set_fact") or {}
        if "_merged_data" in sf:
            return sf["_merged_data"]
    raise AssertionError("init_fragments _merged_data 미발견")


def _output_templates(path: Path):
    """각 play 의 always 블록 OUTPUT debug msg 템플릿."""
    out = []
    for play in yaml.safe_load(path.read_text(encoding="utf-8")):
        for task in play.get("tasks") or []:
            for a in (task.get("always") or []):
                if a.get("name") == "OUTPUT":
                    out.append((play.get("name"), a["ansible.builtin.debug"]["msg"]))
    return out


def _render(tmpl: str) -> dict:
    env = NativeEnvironment()
    env.filters["to_json"] = lambda v: json.dumps(v, ensure_ascii=False)
    ctx = {"_ip": "10.0.0.9", "_e_ip": "10.0.0.9", "inventory_hostname": "10.0.0.9",
           "_fr_output_build_failed": "결과를 만들지 못했습니다."}
    rendered = env.from_string(tmpl).render(**ctx)
    return json.loads(rendered) if isinstance(rendered, str) else rendered


@pytest.mark.parametrize("channel", sorted(SITES))
def test_always_fallback_envelope_shape(channel):
    templates = _output_templates(SITES[channel])
    assert templates, f"{channel}: always OUTPUT 미발견"
    skeleton = _skeleton()
    for play_name, tmpl in templates:
        env = _render(tmpl)
        label = f"{channel}/{play_name}"
        assert set(env) == {"schema_version", "target_type", "collection_method", "ip", "hostname", "vendor", "status",
                            "sections", "diagnosis", "meta", "correlation", "errors", "data"}, label
        assert env["ip"] == "10.0.0.9", label
        assert env["hostname"] is None, f"{label}: hostname 이 IP 로 대체됐다 (B-01)"
        assert env["status"] == "failed", label
        assert list(env["sections"]) == ALL_SECTIONS, f"{label}: sections 11 키 (B-04)"
        assert set(env["sections"].values()) <= {"failed", "not_supported"}, label
        assert set(env["meta"]) == {"started_at", "finished_at", "duration_ms", "adapter_id", "adapter_version", "ansible_version"}, label
        assert set(env["correlation"]) == {"serial_number", "system_uuid", "bmc_ip", "host_ip"}, label
        assert env["correlation"]["host_ip"] == "10.0.0.9", label
        assert list(env["data"]) == list(skeleton), f"{label}: data 뼈대가 init_fragments 와 다르다"
        assert set(env["data"]["storage"]) == set(skeleton["storage"]), label
        assert set(env["data"]["network"]) == set(skeleton["network"]), label
        assert env["diagnosis"]["failure_stage"] == "fallback" and env["diagnosis"]["failure_code"] == "OUTPUT_BUILD_FAILED", label
        assert env["errors"][0]["message"] == "결과를 만들지 못했습니다.", label


def test_os_always_marks_hardware_as_supported_section():
    """B-05: hardware 는 OS 채널 정식 섹션 — fallback 에서도 not_supported 가 아니라 failed."""
    for _, tmpl in _output_templates(SITES["os"]):
        assert _render(tmpl)["sections"]["hardware"] == "failed"
    for _, tmpl in _output_templates(SITES["esxi"]):
        env = _render(tmpl)
        assert env["sections"]["hardware"] == "failed" and env["sections"]["users"] == "not_supported"
