"""수집 태스크 · 연결의 시간 제한 (2026-10-03 Plan §6-3 → 2026-10-05 8차 R3 개정).

8차 R3 (사용자 요구: 빠른 종료보다 실제 수집 완료가 우선, 운영 서버의 부하 · 작업량은 미리 알 수 없다):
    task 단위 `timeout:`(Linux 120 · Windows/ESXi 180 · Redfish 120/240/1260 · precheck 120 · 자격 probe 60 · Add-on 300)과
    명령 안의 짧은 강제 종료(df 20초)를 없앴다. 정상적으로 오래 걸리는 명령 · 출력이 없는 명령을 자르지 않는다.
    끝나지 않는 실행은 수집 실행 한계(최대 6시간, scripts/run_gather.sh)와 사용자 취소가 멈춘다.

남긴 것(통신 규약 — 명령 실행 시간과 다른 개념):
    - 연결 수립: SSH ConnectTimeout 60 · Redfish/ESXi 사전 진단 연결 60 · OS 후보 포트 탐색 10(linear Play 라 배치 전체를 늦춘다 — 근거는 site.yml)
    - 응답 대기: OS 프로토콜 확인 60 · Redfish 요청 응답 1800(_rf_timeout) · ESXi 프로토콜 확인 · vSphere 소켓 1800 · Windows setup 수집기 1800
    - WinRM operation 60 / read 70: 긴 명령은 이 주기로 응답을 다시 묻는 통신 규약이라 명령을 끊지 않는다(2026-10-05 Windows .120 실측 —
      Start-Sleep 120 이 read 70 을 넘어도 성공)
    - SSH ServerAliveInterval 10: 연결이 살아 있는지 보는 통신 규약 — 응답 없는 명령을 끊지 않는다
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
TASK_DIRS = ("os-gather", "esxi-gather", "redfish-gather", "common")


def _load(rel):
    return yaml.safe_load((REPO / rel).read_text(encoding="utf-8"))


def _walk(tasks):
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield t
        for k in ("block", "rescue", "always"):
            if isinstance(t.get(k), list):
                yield from _walk(t[k])


def _all_tasks(rel):
    doc = _load(rel)
    if isinstance(doc, list) and doc and isinstance(doc[0], dict) and "hosts" in doc[0]:
        for play in doc:
            for sec in ("pre_tasks", "tasks", "post_tasks", "handlers"):
                yield from _walk(play.get(sec))
    elif isinstance(doc, list):
        yield from _walk(doc)


YAML_FILES = sorted(str(p.relative_to(REPO)).replace("\\", "/") for d in TASK_DIRS for p in (REPO / d).rglob("*.yml")
                    if "/vars/" not in str(p).replace("\\", "/") and "adapters" not in p.parts)


@pytest.mark.parametrize("rel", YAML_FILES)
def test_no_task_level_timeouts_remain(rel):
    for t in _all_tasks(rel):
        assert "timeout" not in t, f"{rel}: {t.get('name')} — task 단위 timeout 은 없앴다(8차 R3)"
        for key, args in t.items():
            if key.split(".")[-1] in ("include_role", "import_role") and isinstance(args, dict):
                assert "timeout" not in (args.get("apply") or {}), f"{rel}: {t.get('name')} — include_role apply.timeout"


def test_old_timeout_variables_are_not_referenced():
    pat = re.compile(r"_(os|win|e|rf|rf_account|rf_detect|precheck|addon)_task_timeout|_os_probe_timeout")
    hits = [rel for rel in YAML_FILES if pat.search((REPO / rel).read_text(encoding="utf-8"))]
    assert hits == [], hits


def test_df_is_not_wrapped_in_a_short_timeout():
    text = (REPO / "os-gather/tasks/linux/gather_storage.yml").read_text(encoding="utf-8")
    code = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
    assert "timeout 20" not in code and "df -P -T -k 2>/dev/null | tail -n +2" in code


def _site_task(name):
    for play in _load("os-gather/site.yml"):
        for t in _walk(play.get("tasks")):
            if t.get("name") == name:
                return t
    raise AssertionError(f"{name} 태스크를 찾지 못했다")


def test_linux_connection_settings():
    args = _site_task("detect | register linux hosts")["ansible.builtin.add_host"]
    assert args["ansible_timeout"] == 60 and "-o ConnectTimeout=60" in args["ansible_ssh_common_args"]
    assert "-o ServerAliveInterval=10" in args["ansible_ssh_common_args"], "연결 생존 확인은 통신 규약 — 그대로"
    assert args["ansible_ssh_use_tty"] is True, "R6: raw 명령을 터미널과 함께 실행해 연결이 닫히면 원격 명령이 SIGHUP 으로 끝난다"


def test_windows_connection_settings():
    args = _site_task("detect | register windows hosts")["ansible.builtin.add_host"]
    assert args["ansible_winrm_operation_timeout_sec"] == 60 and args["ansible_winrm_read_timeout_sec"] == 70
    setup = _site_task("windows | setup")
    assert setup["ansible.builtin.setup"]["gather_timeout"] == 1800, "facts 수집기 하나당 기본 10초는 느린 WMI 에서 값을 빼먹는다"


def test_os_discovery_probe_limits():
    play = _load("os-gather/site.yml")[0]
    assert play["vars"]["_probe_timeout"] == "{{ probe_timeout | default(10) }}"
    t = next(t for t in _walk(play["tasks"]) if t.get("name", "") == "사전 점검: 관리 포트 연결 확인")
    v = t["vars"]
    assert v["_precheck_timeout_protocol"] == "{{ _probe_protocol_timeout | default(60) }}"
    assert v["_precheck_port_poll_interval"] == "{{ _probe_poll_interval | default(0) }}"


def test_precheck_default_connect_wait_is_60():
    text = (REPO / "common/tasks/precheck/run_precheck.yml").read_text(encoding="utf-8")
    assert 'timeout_port: "{{ _precheck_timeout_port | default(60) }}"' in text


def test_esxi_and_redfish_response_waits():
    esxi = (REPO / "esxi-gather/site.yml").read_text(encoding="utf-8")
    assert "_precheck_timeout: 1800" in esxi and "_precheck_timeout: 30" not in esxi
    disks = (REPO / "esxi-gather/library/esxi_disks.py").read_text(encoding="utf-8")
    assert re.search(r"^_DEFAULT_TIMEOUT_SEC = 1800\b", disks, re.M)
    site_vars = {}
    for play in _load("redfish-gather/site.yml"):
        site_vars.update(play.get("vars") or {})
    assert site_vars["_rf_timeout"] == 1800


def test_addon_checkout_has_a_generous_preparation_bound():
    """Add-on 저장소 받기는 수집 시작 전 준비 단계라 상한을 둔다(Git 서버가 응답하지 않으면 수집이 시작하지 못한다) — 정상 받기보다 충분히 길게."""
    text = (REPO / "scripts/addon_checkout.sh").read_text(encoding="utf-8")
    assert "tmo=(timeout 1800)" in text and "timeout 180)" not in text
