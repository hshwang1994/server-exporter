"""inventory.sh 3종 — 호출자 host object 보존 계약 (2026-09-21).

왜 필요한가:
    Add-on 은 `physical_purpose` 같은 호출자 metadata 로 적용 대상을 고른다. 종전 inventory.sh
    는 IP 하나만 남기고 나머지 키를 전부 버렸다. 이제 host object 전체를 hostvar
    `se_host_input` 한 키 아래에 그대로 보존한다. 특정 키 이름을 코드에 적지 않으므로
    호출자가 새 키를 보내도 inventory.sh 를 다시 고칠 일이 없다.

고정하는 것:
    - IP 선택 · IPv4 검증 · 중복 검사 · 오류 경로는 종전 그대로다.
    - hostvar 는 정확히 `ansible_host` + `se_host_input` 두 개다 (연결 변수를 펼치지 않는다).
    - 문자열은 `__ansible_unsafe` 로 감싼다 — ansible-core 는 스크립트 인벤토리 문자열을
      템플릿으로 신뢰하므로, 감싸지 않으면 `{{ }}` 가 든 값이 해석돼 버린다.
    - `__ansible_` 로 시작하는 키는 옮기지 않는다 — Ansible JSON 의 예약 표식이라 그대로
      두면 인벤토리 해석이 통째로 실패한다 (2.20.3 / 2.20.7 실측: 대상 0개).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

SCRIPTS = {
    "os": REPO / "os-gather" / "inventory.sh",
    "esxi": REPO / "esxi-gather" / "inventory.sh",
    "redfish": REPO / "redfish-gather" / "inventory.sh",
}
# 채널별 1순위 IP 키 (fallback 은 셋 다 `ip`)
PRIMARY_IP_KEY = {"os": "service_ip", "esxi": "service_ip", "redfish": "bmc_ip"}


def _run(script: Path, payload, tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k not in ("INVENTORY_JSON", "inventory_json", "WORKSPACE")}
    # .inventory_input.json fallback 이 저장소 파일을 줍지 않도록 빈 workspace 를 준다
    env["WORKSPACE"] = str(tmp_path)
    # Windows 콘솔 기본 인코딩(cp949)이 아니라 운영(Linux)과 같은 UTF-8 로 출력하게 한다
    env["PYTHONIOENCODING"] = "utf-8"
    if payload is not None:
        env["INVENTORY_JSON"] = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(script), *(args or ("--list",))],
                          capture_output=True, text=True, encoding="utf-8", env=env)


def _inventory(script: Path, payload, tmp_path: Path) -> dict:
    proc = _run(script, payload, tmp_path)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _unwrap(value):
    """`{"__ansible_unsafe": s}` 를 원래 문자열로 되돌린다 (비교용)."""
    if isinstance(value, dict):
        if set(value) == {"__ansible_unsafe"}:
            return value["__ansible_unsafe"]
        return {k: _unwrap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_unwrap(v) for v in value]
    return value


RICH_HOST = {
    "ip": "192.0.2.10",
    "physical_purpose": "DB",
    "사용처": "결제",
    "note": "{{ 7*7 }}",
    "tags": ["a", "{{ lookup('env','HOME') }}", 3],
    "rack": 7,
    "ratio": 1.5,
    "active": True,
    "nothing": None,
    "nested": {"k": "v", "deep": {"n": 1, "s": "x"}},
    # 입력 계약상 받지 않는 값이 와도 연결에 쓰이지 않는다 (se_host_input 아래에만 있다)
    "ansible_user": "someone",
    "ansible_connection": "local",
    "password": "not-used",
}


@pytest.mark.parametrize("channel", sorted(SCRIPTS))
def test_ip_only_input_adds_only_se_host_input(channel, tmp_path):
    inv = _inventory(SCRIPTS[channel], [{"ip": "192.0.2.10"}], tmp_path)
    assert inv["all"] == {"hosts": ["192.0.2.10"]}
    hv = inv["_meta"]["hostvars"]["192.0.2.10"]
    assert set(hv) == {"ansible_host", "se_host_input"}
    assert hv["ansible_host"] == "192.0.2.10"
    assert hv["se_host_input"] == {"ip": {"__ansible_unsafe": "192.0.2.10"}}


@pytest.mark.parametrize("channel", sorted(SCRIPTS))
def test_every_caller_key_is_preserved(channel, tmp_path):
    inv = _inventory(SCRIPTS[channel], [RICH_HOST], tmp_path)
    got = inv["_meta"]["hostvars"]["192.0.2.10"]["se_host_input"]
    assert _unwrap(got) == RICH_HOST, "호출자 host object 의 키 · 값이 그대로 남아야 한다"


@pytest.mark.parametrize("channel", sorted(SCRIPTS))
def test_strings_are_wrapped_recursively_and_other_values_are_not(channel, tmp_path):
    got = _inventory(SCRIPTS[channel], [RICH_HOST], tmp_path)["_meta"]["hostvars"]["192.0.2.10"]["se_host_input"]
    assert got["note"] == {"__ansible_unsafe": "{{ 7*7 }}"}
    assert got["tags"] == [{"__ansible_unsafe": "a"},
                           {"__ansible_unsafe": "{{ lookup('env','HOME') }}"}, 3]
    assert got["nested"]["deep"] == {"n": 1, "s": {"__ansible_unsafe": "x"}}
    assert got["rack"] == 7 and got["ratio"] == 1.5
    assert got["active"] is True and got["nothing"] is None


@pytest.mark.parametrize("channel", sorted(SCRIPTS))
def test_caller_keys_never_become_connection_vars(channel, tmp_path):
    host = dict(RICH_HOST, ansible_host="203.0.113.9")
    hv = _inventory(SCRIPTS[channel], [host], tmp_path)["_meta"]["hostvars"]["192.0.2.10"]
    assert hv["ansible_host"] == "192.0.2.10", "연결 주소는 IP 선택 규칙으로만 정해진다"
    assert "ansible_user" not in hv and "ansible_connection" not in hv


@pytest.mark.parametrize("channel", sorted(SCRIPTS))
def test_reserved_ansible_keys_are_not_copied(channel, tmp_path):
    host = {
        "ip": "192.0.2.10",
        "keep": "yes",
        "__ansible_vault": "junk",
        "__ansible_unsafe": "junk",
        "meta": {"__ansible_type": "junk", "ok": "y"},
        "rows": [{"__ansible_unsafe": "junk", "n": 1}],
    }
    got = _inventory(SCRIPTS[channel], [host], tmp_path)["_meta"]["hostvars"]["192.0.2.10"]["se_host_input"]
    assert _unwrap(got) == {"ip": "192.0.2.10", "keep": "yes", "meta": {"ok": "y"}, "rows": [{"n": 1}]}


def test_three_scripts_produce_identical_host_input(tmp_path):
    outs = {c: _inventory(p, [RICH_HOST], tmp_path)["_meta"]["hostvars"]["192.0.2.10"]["se_host_input"]
            for c, p in SCRIPTS.items()}
    assert outs["os"] == outs["esxi"] == outs["redfish"]


@pytest.mark.parametrize("channel", sorted(SCRIPTS))
def test_ip_key_priority_unchanged(channel, tmp_path):
    primary = PRIMARY_IP_KEY[channel]
    host = {primary: "192.0.2.20", "ip": "192.0.2.30", "physical_purpose": "APP"}
    inv = _inventory(SCRIPTS[channel], [host], tmp_path)
    assert inv["all"]["hosts"] == ["192.0.2.20"]
    assert _unwrap(inv["_meta"]["hostvars"]["192.0.2.20"]["se_host_input"]) == host


@pytest.mark.parametrize("channel", sorted(SCRIPTS))
@pytest.mark.parametrize("payload,needle", [
    ([{"ip": "999.1.1.1"}], "유효하지 않은 IP 형식"),
    ([{"ip": "192.0.2.1"}, {"ip": "192.0.2.1"}], "IP 가 중복됩니다"),
    ([{"physical_purpose": "DB"}], "필드 누락"),
    ([], "비어있지 않은 배열"),
    ("{not json", "파싱 실패"),
])
def test_existing_error_paths_unchanged(channel, payload, needle, tmp_path):
    proc = _run(SCRIPTS[channel], payload, tmp_path)
    assert proc.returncode == 1
    assert needle in proc.stderr
    assert proc.stdout == ""


@pytest.mark.parametrize("channel", sorted(SCRIPTS))
def test_host_flag_output_unchanged(channel, tmp_path):
    proc = _run(SCRIPTS[channel], None, tmp_path, "--host", "192.0.2.10")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"ansible_host": "192.0.2.10"}
