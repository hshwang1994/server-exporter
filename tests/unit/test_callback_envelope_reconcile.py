"""envelope 소실 방지 계약 (Phase 6-B, 2026-08-11).

배경
----
호출자 계약은 **요청 대상 1개 = 결과 envelope 정확히 1개** 다. 그런데 수집 도중 호스트가
unreachable 이 되면 Ansible 이 그 호스트를 play 에서 제거한다. `rescue` 는 failed 전용이고
`always` 도 제거된 호스트에서는 돌지 않으므로 OUTPUT 태스크가 아예 실행되지 않는다.
2026-08-11 실측에서 2 대 투입 → envelope 1 개만 나왔다 (PLAY RECAP: `failed=0 rescued=0`).

`callback_plugins/json_only.py` 가 호스트별 진행 상황을 추적했다가 플레이북 종료 시점에
누락 envelope 을 보충한다. 본 테스트는 그 보충이

  - 빠짐없이 (누락 0)
  - 중복 없이 (이미 낸 호스트는 건드리지 않음)
  - 13 필드 / failure_stage · failure_code 계약을 지키면서
  - **관측된 사실에 맞는 단계**로

이뤄지는지를 고정한다. Ansible 은 실행하지 않고 콜백 인터페이스만 대역으로 구동한다.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "callback_plugins"))

try:                                          # ansible 이 있으면 실물 기반 클래스를 쓴다
    import ansible.plugins.callback  # noqa: F401
except ImportError:                           # 없으면 최소 대역 (콜백 계약만 검증하면 된다)
    _cb = types.ModuleType("ansible.plugins.callback")

    class _CallbackBase:                      # noqa: D401 - CallbackBase 대역
        def __init__(self, *_a, **_k):
            pass

    _cb.CallbackBase = _CallbackBase
    _plugins = sys.modules.setdefault("ansible.plugins", types.ModuleType("ansible.plugins"))
    _plugins.callback = _cb
    sys.modules.setdefault("ansible", types.ModuleType("ansible")).plugins = _plugins
    sys.modules["ansible.plugins.callback"] = _cb

import json_only  # noqa: E402

from tests.e2e.test_failure_code_contract import (  # noqa: E402
    ALLOWED_CODES,
    ALLOWED_STAGES,
    CODE_TO_STAGES,
)
from tests.e2e.test_failure_reason_contract import _assert_grid_ready  # noqa: E402

# build_output.yml 정본 순서 (rule 13 R5 / rule 20 R1)
ENVELOPE_FIELDS = (
    "schema_version", "target_type", "collection_method", "ip", "hostname",
    "vendor", "status", "sections", "diagnosis", "meta", "correlation",
    "errors", "data",
)
DIAGNOSIS_KEYS = (
    "reachable", "port_open", "protocol_supported", "auth_success",
    "failure_stage", "failure_code", "failure_reason", "details",
)


# ---------------------------------------------------------------------------
# Ansible 콜백 인터페이스 대역
# ---------------------------------------------------------------------------
class _Host:
    def __init__(self, name, host_vars=None):
        self.name = name
        self._vars = dict(host_vars or {})

    def get_name(self):
        return self.name

    def get_vars(self):
        return dict(self._vars)


class _Task:
    def __init__(self, name):
        self.name = name


class _Result:
    """CallbackTaskResult 대역 (공개 프로퍼티 + deprecated alias 둘 다 제공)."""

    def __init__(self, host, task_name, action="ansible.builtin.set_fact",
                 result=None, **fields):
        self.host = host
        self.task = _Task(task_name)
        self.result = dict(result or {})
        self.task_fields = {
            "name": task_name, "action": action, "delegate_to": None,
            "connection": "smart", "ignore_unreachable": None, "no_log": None,
        }
        self.task_fields.update(fields)

    _host = property(lambda self: self.host)
    _task = property(lambda self: self.task)
    _result = property(lambda self: self.result)
    _task_fields = property(lambda self: self.task_fields)


class _Stats:
    def __init__(self, hosts):
        self.processed = {h: 1 for h in hosts}


class _Playbook:
    def __init__(self, path):
        self._file_name = str(path)


PRECHECK_OK = {
    "reachable": True, "port_open": True, "protocol_supported": True,
    "auth_success": None, "failure_stage": None, "failure_code": None,
    "failure_reason": None,
    "details": {"channel": "os", "adapter_candidate": None,
                "checked_ports": [5986, 5985, 22], "detected_os": "linux",
                "detected_port": 22, "selected_port": 22},
}
PRECHECK_PORT_FAIL = {
    "reachable": True, "port_open": False, "protocol_supported": False,
    "auth_success": None, "failure_stage": "port",
    "failure_code": "TCP_CONNECTION_REFUSED",
    "failure_reason": "대상 서버의 관리 포트가 연결을 거부했습니다. 방화벽과 관리 서비스 상태를 확인하세요.",
    "details": {"channel": "os", "checked_ports": [5986, 5985, 22]},
}


class Driver:
    """os-gather 실행 순서를 그대로 흉내 내는 시나리오 빌더."""

    def __init__(self, capsys, channel="os"):
        self.cb = json_only.CallbackModule()
        self.capsys = capsys
        self.cb.v2_playbook_on_start(_Playbook(REPO / f"{channel}-gather" / "site.yml"))
        self.hosts = {}

    # -- PLAY 1 (connection: local) -----------------------------------------
    def precheck(self, ip, diagnosis=None):
        host = self.hosts.setdefault(ip, _Host(ip, {"ansible_host": ip}))
        self.cb.v2_runner_on_ok(_Result(
            host, "precheck | 공통 diagnosis 생성", connection="local",
            delegate_to=None,
            result={"ansible_facts": {"_diagnosis": diagnosis or PRECHECK_OK}}))

    def precheck_detail(self, ip, detail):
        """run_precheck.yml:84-86 — precheck 가 관측한 원본 오류를 _fail_error_detail 로 전달."""
        self.cb.v2_runner_on_ok(_Result(
            self.hosts[ip], "precheck | 실패 detail 을 errors[].detail 로 전달",
            connection="local", delegate_to=None,
            result={"ansible_facts": {"_fail_error_detail": detail}}))

    def classify(self, ip, connection="ssh"):
        """add_host 후 호스트가 실제 연결 정보를 갖는 상태."""
        self.hosts[ip]._vars["ansible_connection"] = connection

    # -- PLAY 2 (connection: ssh) -------------------------------------------
    def credential_probe(self, ip, reachable=True):
        """try_one_credential 의 probe. ignore_unreachable=true 로 호스트를 잃지 않는다.

        `ok` 로 끝나면 그 자체가 SSH 인증 통과의 증거다 (인증 실패는 unreachable).
        """
        res = _Result(self.hosts[ip], "os | try_one_credential | linux ssh probe",
                      action="ansible.builtin.raw", ignore_unreachable=True,
                      result={"censored": "no_log"})
        if reachable:
            self.cb.v2_runner_on_ok(res)
        else:
            self.cb.v2_runner_on_unreachable(res)

    def remote_task(self, ip, name="linux | preflight | detect python + commands",
                    unreachable=False):
        res = _Result(self.hosts[ip], name, action="ansible.builtin.raw",
                      result={"censored": "no_log"} if not unreachable
                      else {"unreachable": True, "msg": "ssh 연결 끊김"})
        if unreachable:
            self.cb.v2_runner_on_unreachable(res)
        else:
            self.cb.v2_runner_on_ok(res)

    def output(self, ip, envelope):
        self.cb.v2_runner_on_ok(_Result(
            self.hosts[ip], "OUTPUT", action="ansible.builtin.debug",
            result={"msg": json.dumps(envelope, ensure_ascii=False)}))

    # -- 종료 ---------------------------------------------------------------
    def finish(self):
        self.cb.v2_playbook_on_stats(_Stats(list(self.hosts)))
        out = self.capsys.readouterr().out
        return [json.loads(line) for line in out.splitlines() if line.strip()]


def _success_envelope(ip):
    return {
        "schema_version": "1", "target_type": "os", "collection_method": "agent",
        "ip": ip, "hostname": ip, "vendor": "dell", "status": "success",
        "sections": {"cpu": "success"},
        "diagnosis": {k: (True if k in ("reachable", "port_open",
                                        "protocol_supported", "auth_success")
                          else None) for k in DIAGNOSIS_KEYS} | {"details": {"channel": "os"}},
        "meta": {}, "correlation": {}, "errors": [], "data": {"cpu": {}},
    }


def _assert_envelope_contract(env, label):
    assert list(env) == list(ENVELOPE_FIELDS), f"[{label}] 13 필드 순서/구성 위반: {list(env)}"
    assert env["schema_version"] == "1", label
    assert env["target_type"] in ("os", "esxi", "redfish"), label
    diag = env["diagnosis"]
    assert isinstance(diag, dict) and set(diag) == set(DIAGNOSIS_KEYS), (
        f"[{label}] diagnosis shape 위반: {sorted(diag)}")
    assert isinstance(diag["details"], dict), label
    if env["status"] == "failed":
        stage, code = diag["failure_stage"], diag["failure_code"]
        assert stage in ALLOWED_STAGES, f"[{label}] 허용 밖 stage: {stage!r}"
        assert code in ALLOWED_CODES, f"[{label}] 허용 밖 code: {code!r}"
        assert stage in CODE_TO_STAGES[code], f"[{label}] code/stage 조합 위반: {code}/{stage}"
        _assert_grid_ready(diag["failure_reason"], label)
        assert env["errors"], f"[{label}] Portal Grid 는 errors[].message 를 읽는다"
        assert env["errors"][0].get("message"), label


# ═══════════════════════════════════════════════════════════════════════════
# 1. 정상 경로는 건드리지 않는다 (중복 0)
# ═══════════════════════════════════════════════════════════════════════════
def test_all_hosts_succeed_no_extra_envelope(capsys):
    d = Driver(capsys)
    for ip in ("192.0.2.11", "192.0.2.12", "192.0.2.13"):
        d.precheck(ip)
        d.classify(ip)
        d.credential_probe(ip)
        d.remote_task(ip)
        d.output(ip, _success_envelope(ip))

    envs = d.finish()
    assert len(envs) == 3, f"보충이 중복 envelope 을 만들었다: {len(envs)}"
    assert [e["ip"] for e in envs] == ["192.0.2.11", "192.0.2.12", "192.0.2.13"]
    assert all(e["status"] == "success" for e in envs)


def test_output_emitted_host_is_never_reconciled(capsys):
    """이미 envelope 을 낸 호스트는 unreachable 을 겪었어도 보충하지 않는다."""
    d = Driver(capsys)
    ip = "192.0.2.21"
    d.precheck(ip)
    d.classify(ip)
    d.remote_task(ip)
    d.output(ip, _success_envelope(ip))
    envs = d.finish()
    assert len(envs) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 2. 수집 도중 unreachable — 재현된 결함 그 자체
# ═══════════════════════════════════════════════════════════════════════════
def test_multi_host_one_lost_during_gather_still_yields_one_envelope_each(capsys):
    """2 대 투입 → 1 대는 수집 중 연결 끊김. envelope 은 여전히 2 개다."""
    d = Driver(capsys)
    alive, lost = "192.0.2.31", "192.0.2.32"
    for ip in (alive, lost):
        d.precheck(ip)
        d.classify(ip)
        d.credential_probe(ip)
        d.remote_task(ip)                       # preflight 성공 = 인증 통과 관측
    d.output(alive, _success_envelope(alive))
    d.remote_task(lost, name="linux | gather cpu", unreachable=True)

    envs = d.finish()
    assert len(envs) == 2, f"envelope 누락 (기대 2, 실제 {len(envs)})"
    by_ip = {e["ip"]: e for e in envs}
    assert set(by_ip) == {alive, lost}

    assert by_ip[alive]["status"] == "success"

    gone = by_ip[lost]
    _assert_envelope_contract(gone, "gather 중 unreachable")
    assert gone["status"] == "failed"
    diag = gone["diagnosis"]
    assert diag["failure_stage"] == "gather"
    assert diag["failure_code"] == "GATHER_FAILED"
    assert diag["auth_success"] is True, "대상 연결로 태스크가 성공했으므로 인증은 관측된 사실"
    # precheck 가 관측한 앞 단계 결과가 보존돼야 한다
    assert diag["reachable"] is True and diag["port_open"] is True
    assert diag["protocol_supported"] is True
    assert diag["details"]["checked_ports"] == [5986, 5985, 22]
    assert diag["details"]["channel"] == "os"


def test_unreachable_before_any_remote_success_is_auth_stage(capsys):
    """자격 단계에서 접속을 확인하지 못한 채 잃은 호스트는 auth 단계다."""
    d = Driver(capsys)
    ip = "192.0.2.41"
    d.precheck(ip)
    d.classify(ip)
    d.credential_probe(ip, reachable=False)     # ignore_unreachable → 호스트 유지
    d.remote_task(ip, unreachable=True)         # 첫 실 태스크에서 소실

    envs = d.finish()
    assert len(envs) == 1
    diag = envs[0]["diagnosis"]
    _assert_envelope_contract(envs[0], "auth 단계 unreachable")
    assert diag["failure_stage"] == "auth"
    assert diag["failure_code"] == "AUTH_PROBE_FAILED"
    assert diag["auth_success"] is None, "인증 '거부'를 관측한 것이 아니므로 false 로 확정하지 않는다"


def test_ignore_unreachable_probe_alone_does_not_lose_host(capsys):
    """자격 probe 의 unreachable 만으로는 호스트를 잃지 않는다 (rescue 가 정상 동작)."""
    d = Driver(capsys)
    ip = "192.0.2.42"
    d.precheck(ip)
    d.classify(ip)
    for _ in range(3):
        d.credential_probe(ip, reachable=False)
    failed = _success_envelope(ip) | {"status": "failed"}
    failed["diagnosis"] = failed["diagnosis"] | {
        "auth_success": None, "failure_stage": "auth",
        "failure_code": "AUTH_PROBE_FAILED",
        "failure_reason": "SSH 서비스는 확인되었지만 Linux 서버에 접속하지 못했습니다. 자격증명과 SSH 설정을 확인하세요.",
    }
    d.output(ip, failed)

    envs = d.finish()
    assert len(envs) == 1, "rescue 경로가 정상이면 보충이 개입하지 않는다"
    assert envs[0]["diagnosis"]["failure_code"] == "AUTH_PROBE_FAILED"


# ═══════════════════════════════════════════════════════════════════════════
# 3. precheck 실패 진단은 그대로 보존
# ═══════════════════════════════════════════════════════════════════════════
def test_precheck_failure_diagnosis_is_preserved(capsys):
    d = Driver(capsys)
    ip = "192.0.2.51"
    d.precheck(ip, diagnosis=PRECHECK_PORT_FAIL)
    # PLAY 1.5 가 돌지 못한 상황을 가정 (OUTPUT 없음)
    envs = d.finish()
    assert len(envs) == 1
    diag = envs[0]["diagnosis"]
    _assert_envelope_contract(envs[0], "precheck 실패 보존")
    assert diag["failure_stage"] == "port"
    assert diag["failure_code"] == "TCP_CONNECTION_REFUSED"
    assert diag["failure_reason"] == PRECHECK_PORT_FAIL["failure_reason"], (
        "precheck 가 만든 사유를 콜백이 덮어쓰면 안 된다")
    assert diag["port_open"] is False


# ═══════════════════════════════════════════════════════════════════════════
# 4. OUTPUT 이 아예 실행되지 않은 경우 (unreachable 아님)
# ═══════════════════════════════════════════════════════════════════════════
def test_missing_output_without_unreachable_is_fallback_stage(capsys):
    d = Driver(capsys)
    ip = "192.0.2.61"
    d.precheck(ip)
    d.classify(ip)
    d.remote_task(ip)
    # OUTPUT 태스크가 실행되지 않음 (play 중단 / 태스크명 변경 등)
    envs = d.finish()
    assert len(envs) == 1
    diag = envs[0]["diagnosis"]
    _assert_envelope_contract(envs[0], "OUTPUT 미실행")
    assert diag["failure_stage"] == "fallback"
    assert diag["failure_code"] == "OUTPUT_BUILD_FAILED"


def test_output_task_with_unparsable_result_is_reconciled(capsys):
    """OUTPUT 이 msg/ansible_facts 어느 쪽도 내지 못하면 보충 대상이다."""
    d = Driver(capsys)
    ip = "192.0.2.62"
    d.precheck(ip)
    d.classify(ip)
    d.cb.v2_runner_on_ok(_Result(d.hosts[ip], "OUTPUT", action="ansible.builtin.debug",
                                 result={"censored": "no_log"}))
    envs = d.finish()
    assert len(envs) == 1
    assert envs[0]["diagnosis"]["failure_code"] == "OUTPUT_BUILD_FAILED"


# ═══════════════════════════════════════════════════════════════════════════
# 5. 채널 판정 / 규모 / 안전장치
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("channel,target_type,method", [
    ("os", "os", "agent"),
    ("esxi", "esxi", "vsphere_api"),
    ("redfish", "redfish", "redfish_api"),
])
def test_channel_resolved_without_any_diagnosis(capsys, channel, target_type, method):
    """진단을 한 번도 관측하지 못해도 플레이북 위치로 채널을 확정한다."""
    d = Driver(capsys, channel=channel)
    ip = "192.0.2.71"
    d.hosts[ip] = _Host(ip, {"ansible_host": ip})
    d.cb.v2_runner_on_ok(_Result(d.hosts[ip], "init", connection="local"))
    envs = d.finish()
    assert len(envs) == 1
    assert envs[0]["target_type"] == target_type
    assert envs[0]["collection_method"] == method
    _assert_envelope_contract(envs[0], f"channel/{channel}")


def test_no_envelope_is_lost_at_scale(capsys):
    """호스트 20 대 혼합 시나리오 — 누락 0 / 중복 0."""
    d = Driver(capsys)
    expected_status = {}
    for i in range(20):
        ip = f"192.0.2.{100 + i}"
        d.precheck(ip)
        d.classify(ip)
        if i % 4 == 0:                       # 정상
            d.credential_probe(ip)
            d.remote_task(ip)
            d.output(ip, _success_envelope(ip))
            expected_status[ip] = ("success", None)
        elif i % 4 == 1:                     # 수집 중 소실
            d.credential_probe(ip)
            d.remote_task(ip)
            d.remote_task(ip, name="linux | gather memory", unreachable=True)
            expected_status[ip] = ("failed", "GATHER_FAILED")
        elif i % 4 == 2:                     # 접속을 한 번도 확인하지 못한 채 소실
            d.credential_probe(ip, reachable=False)
            d.remote_task(ip, unreachable=True)
            expected_status[ip] = ("failed", "AUTH_PROBE_FAILED")
        else:                                # OUTPUT 미실행
            d.credential_probe(ip)
            d.remote_task(ip)
            expected_status[ip] = ("failed", "OUTPUT_BUILD_FAILED")

    envs = d.finish()
    assert len(envs) == 20, f"누락/중복 발생: {len(envs)}"
    assert len({e["ip"] for e in envs}) == 20, "중복 envelope 존재"
    for env in envs:
        status, code = expected_status[env["ip"]]
        assert env["status"] == status, env["ip"]
        if code:
            assert env["diagnosis"]["failure_code"] == code, env["ip"]
            _assert_envelope_contract(env, env["ip"])


def test_reconcile_can_be_disabled(capsys, monkeypatch):
    """비상 스위치 — 종전 동작(보충 없음)으로 되돌릴 수 있다."""
    monkeypatch.setenv("JSON_ONLY_NO_RECONCILE", "1")
    d = Driver(capsys)
    ip = "192.0.2.81"
    d.precheck(ip)
    d.classify(ip)
    d.remote_task(ip, unreachable=True)
    assert d.finish() == []


def test_reconcile_failure_never_kills_normal_output(capsys):
    """보충 로직이 터져도 이미 나간 정상 envelope 은 그대로다."""
    d = Driver(capsys)
    ip = "192.0.2.82"
    d.precheck(ip)
    d.classify(ip)
    d.output(ip, _success_envelope(ip))
    d.cb._hosts = None                      # 내부 상태 강제 파손
    d.cb.v2_playbook_on_stats(_Stats([ip]))
    captured = capsys.readouterr()
    envs = [json.loads(line) for line in captured.out.splitlines() if line.strip()]
    assert len(envs) == 1 and envs[0]["status"] == "success"
    assert "reconcile_failed" in captured.err


def test_reconciled_envelope_is_reported_on_stderr(capsys):
    """운영 가시성 — 보충이 일어났다는 사실이 stderr 평문으로 남는다.

    2026-08-12: 종전에는 이 진단이 stderr 로 `message` 키를 가진 **JSON** 이었다.
    호출자는 Jenkins console log 를 라인 단위로 파싱하므로(Jenkinsfile:245-246)
    stdout envelope 과 키가 겹치는 JSON 이 같은 로그에 섞이면 진단 줄이 결과
    envelope 으로 오인될 수 있다. 그래서 `[json_only] ...` 평문으로 통일했다.
    """
    d = Driver(capsys)
    ip = "192.0.2.83"
    d.precheck(ip)
    d.classify(ip)
    d.remote_task(ip)
    d.remote_task(ip, name="linux | gather cpu", unreachable=True)
    d.cb.v2_playbook_on_stats(_Stats([ip]))
    captured = capsys.readouterr()
    assert json.loads(captured.out.strip())["ip"] == ip

    err = captured.err.strip()
    assert err.startswith("[json_only] envelope_reconciled:"), err
    assert "GATHER_FAILED" in err
    assert f"host={ip}" in err
    # 진단 줄이 envelope 으로 오인될 여지 자체를 없앤다 (JSON 이 아니어야 한다).
    for line in captured.err.splitlines():
        assert not line.lstrip().startswith("{"), f"stderr 에 JSON 줄이 남아있다: {line}"


def test_one_host_build_failure_does_not_block_the_others(capsys, monkeypatch):
    """한 호스트의 조립 실패가 남은 호스트의 보충까지 삼키면 안 된다 (per-host 격리).

    종전에는 보충 루프 전체가 `v2_playbook_on_stats` 의 try 하나에만 감싸여 있어
    첫 호스트에서 예외가 나면 남은 미방출 호스트 **전부**가 envelope 을 잃었다.
    소실을 막는 장치가 오히려 대량 소실 지점이 되는 구조였다.
    """
    d = Driver(capsys)
    ips = ["192.0.2.91", "192.0.2.92", "192.0.2.93"]
    for ip in ips:
        d.precheck(ip)
        d.classify(ip)
        d.remote_task(ip)
        d.remote_task(ip, name="linux | gather cpu", unreachable=True)

    original = d.cb._build_fallback_envelope

    def boom(host_name, ctx):
        if host_name == ips[0]:
            raise RuntimeError("조립 실패 재현")
        return original(host_name, ctx)

    monkeypatch.setattr(d.cb, "_build_fallback_envelope", boom)

    d.cb.v2_playbook_on_stats(_Stats(list(d.hosts)))
    captured = capsys.readouterr()
    envs = [json.loads(line) for line in captured.out.splitlines() if line.strip()]

    assert len(envs) == 3, f"첫 호스트의 예외가 나머지를 삼켰다 (기대 3, 실제 {len(envs)})"
    by_ip = {e["ip"]: e for e in envs}
    assert set(by_ip) == set(ips)

    degraded = by_ip[ips[0]]
    _assert_envelope_contract(degraded, "조립 실패 degrade")
    assert degraded["diagnosis"]["failure_stage"] == "fallback"
    assert degraded["diagnosis"]["failure_code"] == "OUTPUT_BUILD_FAILED"
    assert degraded["errors"][0]["message"] == degraded["diagnosis"]["failure_reason"]

    for ip in ips[1:]:
        assert by_ip[ip]["diagnosis"]["failure_code"] == "GATHER_FAILED", ip

    assert "envelope 조립 실패" in captured.err, "degrade 사유가 어디에도 남지 않았다"


def test_disabled_reconcile_leaves_a_stderr_notice(capsys, monkeypatch):
    """비상 스위치가 켜져 있다는 사실이 stderr 로 남는다 (stdout 오염 0)."""
    monkeypatch.setenv("JSON_ONLY_NO_RECONCILE", "1")
    json_only.CallbackModule()
    captured = capsys.readouterr()
    assert captured.out == "", "고지가 stdout 을 오염시키면 호출자 파싱이 깨진다"
    assert "JSON_ONLY_NO_RECONCILE" in captured.err


def test_enabled_reconcile_emits_no_notice(capsys, monkeypatch):
    """정상(보충 활성) 상태에서는 아무 잡음도 내지 않는다."""
    monkeypatch.delenv("JSON_ONLY_NO_RECONCILE", raising=False)
    json_only.CallbackModule()
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_precheck_observed_detail_survives_into_errors_detail(capsys):
    """precheck 가 포트별로 관측한 원본 오류가 보충 envelope 에서 사라지면 안 된다.

    종전에는 분기(1)의 detail 이 고정 문자열로 덮어써져, 실패 원인의 유일한 1차 증거인
    포트별 관측값이 통째로 없어졌다.
    """
    d = Driver(capsys)
    ip = "192.0.2.95"
    observed = "WinRM timeout; WinRM timeout; SSH connection refused"
    d.precheck(ip, diagnosis=PRECHECK_PORT_FAIL)
    d.precheck_detail(ip, observed)

    env = d.finish()[0]
    _assert_envelope_contract(env, "precheck detail 보존")
    err = env["errors"][0]
    assert observed in err["detail"], "precheck 가 관측한 원본 오류가 소실됐다"
    assert "precheck diagnosis preserved" in err["detail"], "콜백 표식도 유지돼야 한다"
    # 기술 근거는 detail 에만 — 사용자 문장은 정본 그대로다
    assert observed not in err["message"]
    assert err["message"] == env["diagnosis"]["failure_reason"]


def test_successful_credential_probe_is_auth_evidence(capsys):
    """자격 probe 가 ok 로 끝났으면 인증은 통과한 것이다 (인증 실패는 unreachable).

    probe 직후 첫 실제 태스크에서 연결이 끊긴 경우까지 gather 로 분류돼야 한다.
    `failed_when: false` 는 명령 실패만 가리며 연결 실패를 ok 로 바꾸지 못한다.
    """
    d = Driver(capsys)
    ip = "192.0.2.86"
    d.precheck(ip)
    d.classify(ip)
    d.credential_probe(ip)                            # ok (ignore_unreachable=true)
    d.remote_task(ip, unreachable=True)               # preflight 에서 소실
    envs = d.finish()
    assert len(envs) == 1
    diag = envs[0]["diagnosis"]
    assert diag["failure_stage"] == "gather"
    assert diag["failure_code"] == "GATHER_FAILED"
    assert diag["auth_success"] is True


def test_local_connection_task_is_not_auth_evidence(capsys):
    """controller 에서 돈 태스크 성공은 대상 인증 증거가 아니다 (보수적 판정)."""
    d = Driver(capsys)
    ip = "192.0.2.84"
    d.precheck(ip)                                    # connection=local, delegate 없음
    d.classify(ip)
    d.cb.v2_runner_on_ok(_Result(d.hosts[ip], "esxi | collect facts",
                                 action="community.vmware.vmware_host_facts",
                                 connection="local", delegate_to="localhost"))
    d.remote_task(ip, unreachable=True)
    envs = d.finish()
    assert envs[0]["diagnosis"]["failure_code"] == "AUTH_PROBE_FAILED"
    assert envs[0]["diagnosis"]["auth_success"] is None


def test_reconciled_envelope_carries_no_secret_material(capsys):
    d = Driver(capsys)
    ip = "192.0.2.85"
    d.precheck(ip)
    d.classify(ip)
    d.remote_task(ip, unreachable=True)
    blob = json.dumps(d.finish(), ensure_ascii=False)
    for token in ("password", "ansible_password", "Basic ", "vault"):
        assert token not in blob, f"민감 정보 노출 의심: {token!r}"


# ═══════════════════════════════════════════════════════════════════════════
# 통합 (2026-08-11): 보충 envelope 의 사용자 문구가 정본과 갈라지지 않는다
#
# Phase 6-B 는 두 작업이 같은 출력면을 건드렸다:
#   - 이 콜백이 소실된 envelope 을 **보충**하고 (envelope 소실 방지)
#   - 사용자 문구를 5 문장으로 **통일**했다 (Portal 실패 Grid)
# 통합 전에는 보충된 envelope 만 표준에 없는 문장을 썼고, errors[].message 가
# diagnosis.failure_reason 과 다른 문장을 담고 있었다. Portal 은 errors[].message 를
# 읽으므로 보충된 행만 다른 어휘로 보이게 된다. 아래 테스트가 그 재발을 막는다.
# ═══════════════════════════════════════════════════════════════════════════

_CANONICAL_YAML = REPO / "common" / "vars" / "failure_reasons.yml"


def _canonical_sentences():
    import yaml
    data = yaml.safe_load(_CANONICAL_YAML.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if isinstance(v, str)}


class TestCanonicalReasonsDoNotDrift:
    """콜백은 문구를 새로 정의하지 않는다 — 정본 값을 복제할 뿐이다.

    콜백 플러그인은 Ansible 자체 로더로 올라가 precheck_bundle 을 import 할 수 없어
    값을 복제한다. 복제본이 정본과 갈라지는 것을 여기서 고정한다.
    """

    def test_credential_sentence_matches_canonical(self):
        assert json_only._REASON_CREDENTIAL_FAILED == \
            _canonical_sentences()["_fr_credential_failed"], (
            "json_only._REASON_CREDENTIAL_FAILED 가 "
            "common/vars/failure_reasons.yml:_fr_credential_failed 와 다르다"
        )

    def test_gather_sentence_matches_canonical(self):
        assert json_only._REASON_GATHER_FAILED == \
            _canonical_sentences()["_fr_gather_failed"], (
            "json_only._REASON_GATHER_FAILED 가 "
            "common/vars/failure_reasons.yml:_fr_gather_failed 와 다르다"
        )

    def test_no_output_sentence_matches_canonical(self):
        """결과 객체 생성 실패 문장의 정본은 failure_reasons.yml 이다 (2026-08-12).

        종전에는 이 문장이 site.yml always 블록마다 두 자리(diagnosis.failure_reason /
        errors[0].message)에 리터럴로 있어서 3 채널 8곳을 동시에 고쳐야 했다 (H2).
        정본을 `_fr_output_build_failed` 로 옮겼으므로 site.yml 문자열이 아니라
        정본 값과 비교한다.
        """
        assert json_only._REASON_NO_OUTPUT == \
            _canonical_sentences()["_fr_output_build_failed"], (
            "json_only._REASON_NO_OUTPUT 가 "
            "common/vars/failure_reasons.yml:_fr_output_build_failed 와 다르다"
        )

    def test_site_yml_always_blocks_reference_the_canonical_variable(self):
        """3 채널 always 블록이 문장을 리터럴로 다시 적지 않는다 (H2 회귀 차단)."""
        for site in ("os-gather", "esxi-gather", "redfish-gather"):
            text = (REPO / site / "site.yml").read_text(encoding="utf-8")
            assert json_only._REASON_NO_OUTPUT not in text, (
                f"{site}/site.yml 에 fallback 문장이 하드코딩됐다 — "
                f"_fr_output_build_failed 를 참조할 것"
            )
            assert "_fr_output_build_failed" in text, (
                f"{site}/site.yml always 블록이 정본 변수를 참조하지 않는다"
            )

    def test_callback_defines_no_extra_user_sentences(self):
        """표준 문구 외의 한국어 사용자 문장을 콜백이 새로 만들지 않는다."""
        allowed = {
            json_only._REASON_CREDENTIAL_FAILED,
            json_only._REASON_GATHER_FAILED,
            json_only._REASON_NO_OUTPUT,
        }
        for name in dir(json_only):
            if not name.startswith("_REASON"):
                continue
            value = getattr(json_only, name)
            assert value in allowed, (
                f"json_only.{name} 이 표준에 없는 사용자 문구를 정의한다: {value!r}"
            )


class TestReconciledMessageEqualsFailureReason:
    """errors[].message == diagnosis.failure_reason (build_failed_output.yml §24 와 동일 계약).

    Portal 실패 Grid 가 읽는 값은 errors[].message 다. 이 값이 failure_reason 과 다르면
    사용자가 보는 문장과 시스템이 보는 문장이 갈라진다.
    """

    @staticmethod
    def _assert_pair(env, label):
        diag = env["diagnosis"]
        err = env["errors"][0]
        assert err["message"] == diag["failure_reason"], (
            f"[{label}] errors[0].message 가 diagnosis.failure_reason 과 다르다\n"
            f"  message        : {err['message']!r}\n"
            f"  failure_reason : {diag['failure_reason']!r}"
        )
        _assert_grid_ready(err["message"], f"{label} errors[0].message")

    def test_gather_lost_after_auth(self, capsys):
        d = Driver(capsys)
        ip = "192.0.2.61"
        d.precheck(ip)
        d.classify(ip)
        d.remote_task(ip)                      # 인증 통과 증거
        d.remote_task(ip, unreachable=True)
        env = d.finish()[0]
        assert env["diagnosis"]["failure_code"] == "GATHER_FAILED"
        self._assert_pair(env, "gather-lost")

    def test_connect_never_proven(self, capsys):
        d = Driver(capsys)
        ip = "192.0.2.62"
        d.precheck(ip)
        d.classify(ip)
        d.remote_task(ip, unreachable=True)
        env = d.finish()[0]
        assert env["diagnosis"]["failure_code"] == "AUTH_PROBE_FAILED"
        self._assert_pair(env, "connect-unproven")

    def test_technical_context_lives_in_detail_not_message(self, capsys):
        """§34 — 기술 정보는 detail 에만. message 에는 내부 어휘가 없다."""
        d = Driver(capsys)
        ip = "192.0.2.63"
        d.precheck(ip)
        d.classify(ip)
        d.remote_task(ip, unreachable=True)
        err = d.finish()[0]["errors"][0]
        assert err.get("detail"), "보충 envelope 이 기술 정보를 detail 에 남기지 않았다"
        for token in ("callback", "unreachable", "OUTPUT"):
            assert token not in err["message"], (
                f"errors[0].message 에 내부 어휘가 노출됐다: {token!r}"
            )
