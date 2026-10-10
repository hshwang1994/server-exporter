"""inventory.sh 3종 — 호출자 host object 보존 계약.

왜 필요한가:
    Add-on 은 `physical_purpose` 같은 호출자 metadata 로 Software 항목의 실행 대상을 고른다 (when).
    inventory.sh 는 host object 전체를 hostvar `se_host_input` 한 키 아래에 그대로 보존한다. 특정 키 이름을
    코드에 적지 않으므로 호출자가 새 키를 보내도 inventory.sh 를 다시 고칠 일이 없다.

고정하는 것:
    - IP 선택 · IPv4 검증 · 중복 검사 · 오류 경로는 host object 보존과 관계없이 같다.
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


def _run(script: Path, payload, tmp_path: Path, *args: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k not in ("INVENTORY_JSON", "inventory_json", "WORKSPACE", "INVENTORY_JSON_FILE")}
    # .inventory_input.json fallback 이 저장소 파일을 줍지 않도록 빈 workspace 를 준다
    env["WORKSPACE"] = str(tmp_path)
    # Windows 콘솔 기본 인코딩(cp949)이 아니라 운영(Linux)과 같은 UTF-8 로 출력하게 한다
    env["PYTHONIOENCODING"] = "utf-8"
    if payload is not None:
        env["INVENTORY_JSON"] = payload if isinstance(payload, str) else json.dumps(payload)
    env.update(extra_env or {})
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


# ── FL-F11 (2026-10-10): 접수 목록은 파일로 넘어온다 ──────────────────────────────────────
# Linux 는 환경변수 하나가 131,072 바이트(MAX_ARG_STRLEN)를 넘으면 프로세스 실행 자체가 "Argument list too long" 으로 실패한다 —
# WSL 실측: 확장형 입력 5,000대(510 KB)를 INVENTORY_JSON 으로 넘기면 env 조차 뜨지 않았고, 파일로는 5,000대가 그대로 나왔다.
# 그래서 Jenkinsfile_portal 은 .inventory_input.json 을 쓰고 INVENTORY_JSON_FILE 로 알린다. 여기서는 그 읽기 계약을 고정한다.

def _big_inventory(key: str, n: int = 5000) -> list:
    return [{key: f"10.{i // 65536 % 256}.{i // 256 % 256}.{i % 256}", "physical_purpose": "db", "site": "ic", "note": "x" * 20}
            for i in range(1, n + 1)]


@pytest.mark.parametrize("channel", sorted(SCRIPTS))
def test_inventory_json_file_is_read_first_and_carries_large_batches(channel, tmp_path):
    key = PRIMARY_IP_KEY[channel]
    big = _big_inventory(key)
    f = tmp_path / "accepted.json"
    f.write_text(json.dumps(big), encoding="utf-8")
    assert f.stat().st_size > 131072, "환경변수 한도보다 큰 입력이어야 뜻이 있다"
    # 환경변수와 작업 폴더 파일이 둘 다 다른 내용을 가리켜도 INVENTORY_JSON_FILE 이 이긴다
    (tmp_path / ".inventory_input.json").write_text(json.dumps([{key: "192.0.2.99"}]), encoding="utf-8")
    proc = _run(SCRIPTS[channel], [{key: "192.0.2.98"}], tmp_path, extra_env={"INVENTORY_JSON_FILE": str(f)})
    assert proc.returncode == 0, proc.stderr
    inv = json.loads(proc.stdout)
    assert len(inv["all"]["hosts"]) == 5000 and inv["all"]["hosts"][0] == "10.0.0.1" and inv["all"]["hosts"][-1] == "10.0.19.136"
    hv = inv["_meta"]["hostvars"]["10.0.0.1"]
    assert set(hv) == {"ansible_host", "se_host_input"} and _unwrap(hv["se_host_input"]) == big[0]


@pytest.mark.parametrize("channel", sorted(SCRIPTS))
def test_inventory_json_file_set_but_missing_or_empty_is_an_error_not_a_fallback(channel, tmp_path):
    key = PRIMARY_IP_KEY[channel]
    missing = _run(SCRIPTS[channel], [{key: "192.0.2.98"}], tmp_path, extra_env={"INVENTORY_JSON_FILE": str(tmp_path / "nope.json")})
    assert missing.returncode == 1 and "INVENTORY_JSON_FILE" in missing.stderr and "없습니다" in missing.stderr
    empty = tmp_path / "empty.json"
    empty.write_text("  \n", encoding="utf-8")
    proc = _run(SCRIPTS[channel], [{key: "192.0.2.98"}], tmp_path, extra_env={"INVENTORY_JSON_FILE": str(empty)})
    assert proc.returncode == 1 and "비어 있습니다" in proc.stderr
    # 변수가 비어 있으면(정의만 됐을 때) 환경변수 경로로 간다 — 작은 입력 · syntax-check 호환
    proc = _run(SCRIPTS[channel], [{key: "192.0.2.98"}], tmp_path, extra_env={"INVENTORY_JSON_FILE": ""})
    assert proc.returncode == 0 and json.loads(proc.stdout)["all"]["hosts"] == ["192.0.2.98"]


@pytest.mark.parametrize("channel", sorted(SCRIPTS))
def test_workspace_file_is_the_last_fallback(channel, tmp_path):
    key = PRIMARY_IP_KEY[channel]
    (tmp_path / ".inventory_input.json").write_text(json.dumps([{key: "192.0.2.77"}]), encoding="utf-8")
    proc = _run(SCRIPTS[channel], None, tmp_path)
    assert proc.returncode == 0 and json.loads(proc.stdout)["all"]["hosts"] == ["192.0.2.77"]
    (tmp_path / "empty-ws").mkdir()
    nothing = _run(SCRIPTS[channel], None, tmp_path / "empty-ws")
    assert nothing.returncode == 1 and "모두 비어있습니다" in nothing.stderr
