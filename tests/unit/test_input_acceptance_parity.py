"""F03 (2026-10-05): Jenkins Validate 와 inventory.sh 가 같은 요청을 같은 규칙으로 받아들이거나 거부한다.

종전 Validate 는 IP 값을 문자열로 바꾸고 비어 있지 않은지만 봤다. 같은 IP 두 개를 넣으면 inventory 는 exit 1 로 거부했는데
Validate 는 접수 manifest 에 두 번 넣었고, finalizer 는 같은 IP 결과를 두 줄 만들었다 (Astra 재현).

- Python 쪽: 사례 표(tests/fixtures/input_validation/cases.json)로 inventory.sh 3종을 실제로 실행한다.
- Groovy 쪽: 같은 표를 Jenkinsfile_ci 'Finalize Corpus' 가 Jenkinsfile_portal 의 seAcceptTargets 로 돌린다 — 여기서는 그 함수가
  inventory 와 같은 공백 집합 · IPv4 규칙을 쓰는지(글자 수준)를 고정한다.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CASES = json.loads((REPO / "tests" / "fixtures" / "input_validation" / "cases.json").read_text(encoding="utf-8"))["cases"]
PRIMARY = {"os": "service_ip", "esxi": "service_ip", "redfish": "bmc_ip"}
OTHER = {"os": "bmc_ip", "esxi": "bmc_ip", "redfish": "service_ip"}
PORTAL = (REPO / "Jenkinsfile_portal").read_text(encoding="utf-8")


def _materialize(inventory, channel):
    if not isinstance(inventory, list):
        return {(PRIMARY[channel] if k == "PRIMARY" else OTHER[channel] if k == "OTHER" else k): v
                for k, v in inventory.items()} if isinstance(inventory, dict) else inventory
    out = []
    for host in inventory:
        if isinstance(host, dict):
            host = {(PRIMARY[channel] if k == "PRIMARY" else OTHER[channel] if k == "OTHER" else k): v for k, v in host.items()}
        out.append(host)
    return out


def _run_inventory(channel, inventory):
    env = {k: v for k, v in os.environ.items() if k not in ("INVENTORY_JSON", "inventory_json", "WORKSPACE")}
    env["INVENTORY_JSON"] = json.dumps(inventory)
    env["WORKSPACE"] = str(REPO / "tests" / "fixtures" / "input_validation")    # .inventory_input.json 이 없는 곳
    env["PYTHONIOENCODING"] = "utf-8"    # Windows 에서도 자식의 한국어 오류를 UTF-8 로 받는다(기본은 cp949 — prodgen G14 로컬 실행에서 드러남)
    proc = subprocess.run([sys.executable, str(REPO / f"{channel}-gather" / "inventory.sh"), "--list"],
                          capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
    return proc


@pytest.mark.parametrize("channel", ["os", "esxi", "redfish"])
@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_inventory_follows_the_case_table(channel, case):
    proc = _run_inventory(channel, _materialize(case["inventory"], channel))
    if "accept" in case:
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout)["all"]["hosts"] == case["accept"]
    else:
        assert proc.returncode == 1, f"거부해야 한다: {proc.stdout[:200]}"
        assert "[inventory] ERROR:" in proc.stderr, "traceback 이 아니라 명확한 오류로 끝난다"
        assert "Traceback" not in proc.stderr


def test_case_table_covers_each_reject_kind():
    kinds = {c["reject"] for c in CASES if "reject" in c}
    assert kinds == {"missing", "type", "object", "ipv4", "duplicate", "array"}
    assert sum(1 for c in CASES if "accept" in c) >= 10


def _accept_function():
    m = re.search(r"@NonCPS\nMap seAcceptTargets\(.*?\n}\n", PORTAL, re.S)
    assert m, "seAcceptTargets 가 없다"
    return m.group(0)


def test_groovy_whitespace_set_equals_python_strip():
    """seAcceptTargets 의 공백 문자 집합 == Python str.strip() 이 지우는 문자 집합 (inventory 와 같은 정규화)."""
    cls = re.search(r"String ws = '\[(.*?)\]'", _accept_function()).group(1)
    groovy_chars = set()
    i = 0
    while i < len(cls):
        tok = re.match(r"\\\\u([0-9A-F]{4})-\\\\u([0-9A-F]{4})|\\\\u([0-9A-F]{4})|\\\\([tnfr])| ", cls[i:])
        assert tok, f"공백 집합을 해석하지 못했다: {cls[i:i + 20]!r}"
        if tok.group(1):
            groovy_chars.update(chr(c) for c in range(int(tok.group(1), 16), int(tok.group(2), 16) + 1))
        elif tok.group(3):
            groovy_chars.add(chr(int(tok.group(3), 16)))
        elif tok.group(4):
            groovy_chars.add({"t": "\t", "n": "\n", "f": "\f", "r": "\r"}[tok.group(4)])
        else:
            groovy_chars.add(" ")
        i += tok.end()
    python_chars = {chr(c) for c in range(0x110000) if chr(c).isspace()}
    assert groovy_chars == python_chars


def test_groovy_ipv4_rule_matches_inventory_regex():
    fn = _accept_function()
    assert "String octet = '(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])'" in fn
    for channel in ("os", "esxi", "redfish"):
        text = (REPO / f"{channel}-gather" / "inventory.sh").read_text(encoding="utf-8")
        assert "re.ASCII" in text and r"(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)" in text


def test_validate_uses_the_acceptance_function_only():
    validate = PORTAL[PORTAL.index("stage('입력 확인')"):PORTAL.index("stage('실행 위치 확인')")]
    assert "Map acceptance = seAcceptTargets(hosts, params.target_type.trim())" in validate
    assert "acceptedIps.add(" not in validate and "?.toString()?.trim()" not in validate
    fn = _accept_function()
    for message in ("inventory_json 은 JSON 배열이어야 합니다", "은 객체여야 합니다", "필드 누락", "유효하지 않은 IPv4 형식", "IP 가 중복됩니다",
                    "값은 문자열이어야 합니다"):
        assert message in fn, message
