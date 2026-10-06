"""scripts/run_gather.sh — 서버 정보 수집 실행의 단일 진입점 (2026-10-05 8차 R1 · R2 · R3 · R6, 2026-10-06 9차 재개).

운영 스크립트를 그대로 bash 로 실행하고 ansible-playbook 만 가짜(임시 venv 의 bin/ansible-playbook)로 바꾼다. 축소한 한계(초 단위)로
한계 도달 · 기록 · 원격 연결 정리 · 취소 신호 · 남은 대상만 이어서 수집 · 잠금 대기를 확인한다 — 운영 파이프라인에 시험용 입력을 두지 않고
같은 코드를 시험한다(R1). 가짜 ansible 은 --limit @<파일> 의 대상만 결과(형태 검사를 통과하는 13필드 envelope)로 쓰고 받은 대상을 기록한다.
실제 대상의 원격 정리는 tests/jenkins/harness/remote_cleanup_probe.sh 가 확인한다(2026-10-05 Linux .161).
Linux(또는 WSL · Runner)에서만 돈다 — 프로세스 그룹 · 신호 · /proc · flock 을 쓴다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "run_gather.sh"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux") or BASH is None or shutil.which("timeout") is None
                                or shutil.which("flock") is None,
                                reason="Linux bash · coreutils timeout · flock 이 필요하다 (CI Runner · WSL 에서 실행)")
TIME_LINE = re.compile(r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d [+-]\d\d:\d\d\] \[수집\] ")
IPS = [f"10.9.0.{i}" for i in range(1, 8)]

EMIT = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
import finalize_gather_output as fz
out, n = sys.argv[2], int(sys.argv[3])
ips = [l.strip() for l in open(sys.argv[4], encoding="utf-8") if l.strip()]
all_ = ["system", "hardware", "bmc", "cpu", "memory", "storage", "network", "firmware", "users", "power", "thermal"]
with open(out, "a", encoding="utf-8") as fh:
    for ip in ips[: n if n >= 0 else len(ips)]:
        env = {"schema_version": "1", "target_type": "os", "collection_method": fz.CHANNEL_METHOD["os"], "ip": ip, "hostname": "h",
               "vendor": None, "status": "success", "sections": {s: "success" for s in all_},
               "diagnosis": {k: None for k in fz.DIAGNOSIS_KEYS} | {"details": {}}, "meta": {}, "correlation": {}, "errors": [],
               "data": {"system": {"hostname": "h"}}}
        fh.write(json.dumps(env) + "\n")
'''

STUB = r'''#!/bin/bash
# 가짜 ansible-playbook — 받은 인자 · 환경 · vault 파일 · 대상을 기록하고 STUB_MODE 대로 행동한다
out="$STUB_OUT"
printf '%s\n' "$@" > "$out/args.txt"
env > "$out/env.txt"
vf=""; lim=""
prev=""
for a in "$@"; do
    case "$a" in --vault-password-file=*) vf="${a#--vault-password-file=}" ;; esac
    if [ "$prev" = "--limit" ]; then lim="${a#@}"; fi
    prev="$a"
done
echo "$vf" > "$out/vault_path.txt"; cat "$vf" > "$out/vault_content.txt" 2>/dev/null
echo "$ANSIBLE_SSH_CONTROL_PATH_DIR" > "$out/cp_dir.txt"
[ -n "$lim" ] && cat "$lim" >> "$out/hosts_received.txt" && echo "--" >> "$out/hosts_received.txt"
if [ -n "${STUB_FAKE_MASTER:-}" ]; then
    # 이 실행의 다중화 위치를 명령줄에 가진 가짜 master(정리 대상)와, 그 위치가 없는 다른 프로세스(남아야 한다)
    # 출력 파이프를 물려받지 않게 끊는다(물려받으면 시험이 이 프로세스가 끝날 때까지 기다린다)
    bash -c "exec -a 'ssh -o ControlPath=\"$ANSIBLE_SSH_CONTROL_PATH_DIR/0123abcd\" -o ControlMaster=auto' sleep 300" </dev/null >/dev/null 2>&1 &
    echo $! > "$out/fake_master.pid"
    bash -c "exec -a 'ssh -o ControlPath=\"/tmp/someone-else/0123abcd\"' sleep 300" </dev/null >/dev/null 2>&1 &
    echo $! > "$out/other.pid"
fi
emit() { python3 "$STUB_EMIT" "$WORKSPACE/scripts" "$ANSIBLE_JSON_OUTPUT_FILE" "$1" "$lim"; }
case "${STUB_MODE:-ok}" in
    ok)      echo "stub ran"; exit 0 ;;
    emit)    emit -1; exit 0 ;;
    hosts)   exit 4 ;;
    hang)    sleep 60; exit 0 ;;
    killed)  kill -KILL $$ ;;
    crash)   # 결과 몇 개를 쓴 뒤 수집 셸 자체가 끝 기록 없이 사라진다(Runner 재부팅 · Agent 정지와 같은 흔적)
             emit "${STUB_EMIT_N:-3}"
             pid="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["attempts"][-1]["pid"])' "$WORKSPACE/gather_run.json")"
             kill -KILL "$pid"; exit 0 ;;
esac
'''


@pytest.fixture
def env(tmp_path):
    venv = tmp_path / "venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python3").symlink_to(shutil.which("python3"))
    (venv / "activate").write_text(f'export VIRTUAL_ENV="{venv.parent}"\nexport PATH="{venv}:$PATH"\n', encoding="utf-8")
    stub = venv / "ansible-playbook"
    stub.write_text(STUB, encoding="utf-8")
    stub.chmod(0o755)
    emit = tmp_path / "emit.py"
    emit.write_text(EMIT, encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "scripts").symlink_to(REPO / "scripts")
    (ws / "gather_manifest.json").write_text(json.dumps({"schema": 1, "build": {"job": "j", "number": "7"}, "channel": "os", "ips": IPS}),
                                             encoding="utf-8")
    inv = ws / "inventory.sh"
    inv.write_text("#!/bin/bash\necho '{}'\n", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    e = {k: v for k, v in os.environ.items() if not k.startswith(("SE_", "ANSIBLE_", "ADDON_"))}
    e.update({"WORKSPACE": str(ws), "SE_ANSIBLE_VENV": str(tmp_path / "venv"), "STUB_OUT": str(out), "STUB_EMIT": str(emit),
              "ANSIBLE_JSON_OUTPUT_FILE": str(ws / "gather_output.json"), "VAULT_PASSWORD": "pw-for-test", "LC_ALL": "C.UTF-8"})
    return {"env": e, "ws": ws, "out": out, "inv": inv, "tmp": tmp_path}


def _argv(env, gather_max="5", agent_lost=None):
    a = ["site.yml", str(env["inv"]), "git", "false", str(gather_max)]
    return a + ([agent_lost] if agent_lost is not None else [])


def _run(env, gather_max="5", mode="ok", extra=None, args=None, agent_lost=None):
    e = dict(env["env"], STUB_MODE=mode, **(extra or {}))
    argv = args if args is not None else _argv(env, gather_max, agent_lost)
    return subprocess.run([BASH, str(SCRIPT), *argv], env=e, capture_output=True, text=True, encoding="utf-8", timeout=180)


def _record(env):
    return json.loads((env["ws"] / "gather_run.json").read_text(encoding="utf-8"))


def _received(env):
    text = (env["out"] / "hosts_received.txt").read_text(encoding="utf-8") if (env["out"] / "hosts_received.txt").exists() else ""
    return [[h for h in block.split("\n") if h.strip()] for block in text.split("--\n") if block.strip()]


def _wait_lock_free(env):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:                        # 남은 프로세스(timeout · 가짜 ansible)가 잠금을 놓을 때까지
        if subprocess.run(["flock", "-n", str(env["ws"] / ".gather.lock"), "true"]).returncode == 0:
            return
        time.sleep(0.2)
    pytest.fail("잠금이 풀리지 않았다")


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        state = Path(f"/proc/{pid}/stat").read_text().split()[2]
    except OSError:
        return False
    return state != "Z"


def test_normal_run_records_times_and_passes_the_computed_inputs(env):
    r = _run(env, gather_max="21600", mode="emit")
    assert r.returncode == 0, r.stderr
    lines = [l for l in r.stdout.splitlines() if "[수집]" in l]
    assert TIME_LINE.match(lines[0]) and "시작합니다. 대상 7대(접수 7대), 동시 실행 7대, 이번 실행 한계 6시간(21600초)." in lines[0]
    assert TIME_LINE.match(lines[-1]) and "끝났습니다. 실행 시간" in lines[-1] and "종료 코드 0." in lines[-1]
    rec = _record(env)
    assert rec["schema"] == 2 and rec["rc"] == 0 and rec["timed_out"] is False and rec["limit_sec"] == 21600 and rec["ran_sec"] < 30
    assert rec["state"] == "completed" and rec["attempt_count"] == 1 and rec["attempts"][0]["completed_after"] == 7
    for k in ("started_at", "ended_at"):
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", rec[k]), rec[k]
    assert (env["ws"] / "gather_rc.txt").read_text().strip() == "0"
    args = (env["out"] / "args.txt").read_text().splitlines()
    assert args[:5] == ["site.yml", "-i", str(env["inv"]), "-f", "7"] and "-e" in args and "se_location=git" in args
    assert args[args.index("--limit") + 1] == f"@{env['ws']}/.gather_limit_hosts"
    assert _received(env) == [IPS]
    assert not any("dryrun" in a or "FORCE" in a for a in args), "시험용 extra-vars 배선이 없다"
    assert (env["ws"] / ".gather_alive").exists(), "생존 표시를 시작 직후 쓴다"


def test_vault_password_is_a_private_temp_file_removed_after_the_run(env):
    r = _run(env)
    assert r.returncode == 0
    path = (env["out"] / "vault_path.txt").read_text().strip()
    assert re.fullmatch(r"/tmp/se_vault\.\w{10}", path)
    assert (env["out"] / "vault_content.txt").read_text() == "pw-for-test"
    assert not Path(path).exists(), "끝나면 지운다"
    assert "pw-for-test" not in r.stdout + r.stderr, "값은 출력하지 않는다"
    assert "pw-for-test" not in (env["ws"] / "gather_run.json").read_text(encoding="utf-8"), "실행 기록에는 경로만 남는다"


def test_inherited_test_values_are_cleared_before_ansible(env):
    r = _run(env, extra={"SE_FORCE_LINUX_RAW_FALLBACK": "true", "ANSIBLE_STDOUT_CALLBACK": "default"})
    assert r.returncode == 0
    seen = (env["out"] / "env.txt").read_text()
    for name in ("SE_FORCE_LINUX_RAW_FALLBACK=", "ANSIBLE_STDOUT_CALLBACK="):
        assert name not in seen, name
    assert "ANSIBLE_INVENTORY_UNPARSED_FAILED=True" in seen


def test_limit_reached_is_confirmed_by_the_real_runtime(env):
    """한계 2초 · 60초 걸리는 수집 — timeout 이 INT 를 보내 rc 124, 실제 실행 시간이 한계 이상이라 timed_out=true."""
    t0 = time.monotonic()
    r = _run(env, gather_max="2", mode="hang")
    assert time.monotonic() - t0 < 30, "한계에서 멈춘다"
    assert r.returncode == 124
    rec = _record(env)
    assert rec["timed_out"] is True and rec["ran_sec"] >= 2 and rec["rc"] == 124 and rec["state"] == "gather_limit"
    assert any(TIME_LINE.match(l) and "이번 실행 한계 2초(2초)에 도달해 INT 로 멈췄습니다" in l for l in r.stdout.splitlines()), r.stdout
    assert (env["ws"] / "gather_rc.txt").read_text().strip() == "124"


def test_kill_before_the_limit_is_not_reported_as_the_limit(env):
    """한계 전에 KILL(137)로 끝났고 OOM 기록이 없으면 원인 미확인이다 — 종료 코드만으로 한계 도달 · 메모리 부족이라 하지 않는다."""
    r = _run(env, gather_max="600", mode="killed")
    assert r.returncode == 137
    rec = _record(env)
    assert rec["timed_out"] is False and rec["state"] in ("process_lost", "runner_oom")
    if rec["state"] == "process_lost":
        assert "실행 한계 전에 강제 종료됐습니다" in r.stdout and "원인 미확인" in r.stdout


def test_partial_host_failures_pass_the_ansible_code_through(env):
    r = _run(env, mode="hosts")
    assert r.returncode == 4 and _record(env)["rc"] == 4 and _record(env)["timed_out"] is False and _record(env)["state"] == "completed"


def test_missing_venv_is_a_preparation_failure(env):
    r = _run(env, extra={"SE_ANSIBLE_VENV": str(env["tmp"] / "nowhere")})
    assert r.returncode == 90
    assert not (env["ws"] / "gather_run.json").exists()


def test_missing_manifest_is_a_record_failure(env):
    (env["ws"] / "gather_manifest.json").unlink()
    r = _run(env)
    assert r.returncode == 91 and "실행 기록을 준비하지 못했습니다" in r.stdout
    assert not (env["out"] / "args.txt").exists(), "ansible 을 실행하지 않는다"


@pytest.mark.parametrize("args", [[], ["site.yml"], ["site.yml", "inv", "git", "false", "0"], ["site.yml", "inv", "git", "false", "abc"]])
def test_bad_arguments_exit_2(env, args):
    assert _run(env, args=args).returncode == 2


def test_resume_gathers_only_the_unfinished_hosts_and_keeps_the_time(env):
    """9차 — 결과 3개를 쓴 뒤 수집 셸이 끝 기록 없이 사라졌다. 다음 시도(이전 시도 중 Agent 끊김 보고)는 끝난 대상을 다시 수집하지 않고,
    이전 시도의 실행 시간을 누적에서 빼지 않는다."""
    e = dict(env["env"], STUB_MODE="crash", STUB_EMIT_N="3")
    with open(env["tmp"] / "first.log", "w", encoding="utf-8") as log:
        p = subprocess.Popen([BASH, str(SCRIPT), *_argv(env, "600")], env=e, stdout=log, stderr=subprocess.STDOUT)
        p.wait(timeout=120)
    assert p.returncode == -signal.SIGKILL
    first = _record(env)
    assert not first["attempts"][-1].get("state"), "끝 기록이 없다"
    _wait_lock_free(env)
    r = _run(env, gather_max="600", mode="emit", agent_lost="true")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _received(env) == [IPS, IPS[3:]], "두 번째 시도는 끝나지 않은 4대만 받는다"
    rec = _record(env)
    a1, a2 = rec["attempts"]
    assert a1["state"] == "agent_disconnect" and a1["agent_lost"] is True and a1["end_source"] in ("alive", "start")
    assert 0 <= a1["exec_sec"] <= 60 and a2["limit_sec"] == 600 - a1["exec_sec"], "이전 시도의 실행 시간을 누적에 넣고 남은 만큼만 준다"
    assert a2["completed_before"] == 3 and a2["pending"] == 4 and a2["state"] == "completed" and a2["completed_after"] == 7
    assert rec["exec_used_sec"] == a1["exec_sec"] + a2["exec_sec"] and rec["attempt_count"] == 2
    assert "2번째 시도로 이어서 수집합니다. 접수 7대 중 결과가 확정된 3대는 다시 수집하지 않습니다." in r.stdout
    assert "이전 시도는 끝 기록 없이 중단됐습니다: Runner 와 Jenkins 의 연결이 끊겼습니다" in r.stdout
    out_ips = [json.loads(l)["ip"] for l in (env["ws"] / "gather_output.json").read_text(encoding="utf-8").splitlines()]
    assert sorted(out_ips) == sorted(IPS) and len(out_ips) == 7, "대상마다 결과 한 줄 — 겹쳐 수집하지 않는다"


def test_nothing_pending_or_no_time_left_does_not_run_ansible(env):
    r = _run(env, mode="emit")
    assert r.returncode == 0 and _received(env) == [IPS]
    r = _run(env, mode="emit")
    assert r.returncode == 0 and _received(env) == [IPS], "남은 대상이 없으면 ansible 을 실행하지 않는다"
    assert "남은 대상이 없습니다. 접수 7대의 결과가 모두 확정돼 있어 ansible 을 실행하지 않습니다." in r.stdout
    assert _record(env)["attempts"][-1]["end_source"] == "no_pending"
    # 누적 한계를 다 쓴 빌드: 결과 줄을 지우고 한계를 1초로 — 앞 시도들이 쓴 시간이 이미 한계 이상이다
    (env["ws"] / "gather_output.json").write_text("", encoding="utf-8")
    time.sleep(1.1)
    r = _run(env, gather_max="1", mode="hang")
    rec = _record(env)
    if rec["exec_used_sec"] >= 1 and rec["attempts"][-1]["end_source"] == "limit_exhausted":
        assert r.returncode == 124 and "이미 다 썼습니다" in r.stdout and len(_received(env)) == 1


def test_a_previous_run_still_holding_the_lock_is_waited_for(env):
    """Agent 연결만 끊긴 동안 계속 돈 이전 수집이 있으면 끝나기를 기다린 뒤 남은 대상을 계산한다 — 겹쳐 실행하지 않는다."""
    holder = subprocess.Popen(["flock", str(env["ws"] / ".gather.lock"), "sleep", "3"])
    time.sleep(0.5)
    t0 = time.monotonic()
    r = _run(env, mode="emit")
    holder.wait(timeout=30)
    assert r.returncode == 0
    assert time.monotonic() - t0 >= 2, "잠금이 풀릴 때까지 기다렸다"
    assert "이 빌드의 이전 수집이 아직 실행 중입니다" in r.stdout


def test_truncated_tail_is_moved_aside_before_appending(env):
    whole = (env["ws"] / "gather_output.json")
    e = dict(env["env"], STUB_MODE="crash", STUB_EMIT_N="1")
    with open(env["tmp"] / "first.log", "w", encoding="utf-8") as log:
        subprocess.Popen([BASH, str(SCRIPT), *_argv(env, "600")], env=e, stdout=log, stderr=subprocess.STDOUT).wait(timeout=120)
    whole.write_text(whole.read_text(encoding="utf-8") + '{"schema_version": "1", "ip": "10.9', encoding="utf-8")
    _wait_lock_free(env)
    r = _run(env, gather_max="600", mode="emit")
    assert r.returncode == 0
    assert "쓰는 도중 끊긴 마지막 줄을 gather_tail_fragments.jsonl 로 옮겼습니다(gather_output.json)" in r.stdout
    frag = json.loads((env["ws"] / "gather_tail_fragments.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert frag["fragment"].startswith('{"schema_version": "1", "ip": "10.9')
    lines = whole.read_text(encoding="utf-8").splitlines()
    assert all(json.loads(l)["ip"] in IPS for l in lines) and len(lines) == 7


def test_only_this_runs_ssh_connections_are_closed_and_the_control_dir_removed(env):
    """R6: 이 실행만의 SSH 다중화 위치(/tmp/se_cp.*)를 두고, 끝나면 그 위치를 명령줄에 가진 프로세스만 끝낸다. 다른 프로세스는 건드리지 않는다."""
    r = _run(env, extra={"STUB_FAKE_MASTER": "1"})
    assert r.returncode == 0
    cp_dir = (env["out"] / "cp_dir.txt").read_text().strip()
    assert re.fullmatch(r"/tmp/se_cp\.\w{6}", cp_dir), "소켓 경로 길이 제한 때문에 짧은 /tmp 경로"
    assert not Path(cp_dir).exists(), "끝나면 지운다"
    master = int((env["out"] / "fake_master.pid").read_text())
    other = int((env["out"] / "other.pid").read_text())
    deadline = time.monotonic() + 5
    while _alive(master) and time.monotonic() < deadline:
        time.sleep(0.1)
    try:
        assert not _alive(master), "이 실행의 연결은 정리한다"
        assert _alive(other), "다른 연결(다른 위치)은 건드리지 않는다"
    finally:
        for pid in (master, other):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


def test_cleanup_runs_on_limit_and_on_cancel(env):
    """한계 도달 · 취소(Jenkins 처럼 실행의 프로세스 전체에 TERM) 모두 정리가 돌고, 취소도 끝 기록(믿을 수 있는 끝 시각)을 남긴다."""
    r = _run(env, gather_max="2", mode="hang", extra={"STUB_FAKE_MASTER": "1"})
    assert r.returncode == 124
    master = int((env["out"] / "fake_master.pid").read_text())
    other = int((env["out"] / "other.pid").read_text())
    try:
        time.sleep(1)
        assert not _alive(master) and _alive(other)
    finally:
        for pid in (master, other):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    # 취소: 새 세션으로 띄우고 그 프로세스 그룹 전체에 TERM
    (env["ws"] / "gather_run.json").unlink()
    e = dict(env["env"], STUB_MODE="hang", STUB_FAKE_MASTER="1")
    p = subprocess.Popen([BASH, str(SCRIPT), *_argv(env, "600")], env=e,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    deadline = time.monotonic() + 15
    while not (env["out"] / "other.pid").exists() or (env["out"] / "other.pid").read_text().strip() == str(other):
        if time.monotonic() > deadline:
            p.kill()
            pytest.fail("가짜 수집이 시작하지 않았다")
        time.sleep(0.2)
    time.sleep(0.5)
    master = int((env["out"] / "fake_master.pid").read_text())
    other = int((env["out"] / "other.pid").read_text())
    cp_dir = (env["out"] / "cp_dir.txt").read_text().strip()
    try:
        os.killpg(p.pid, signal.SIGTERM)
        p.wait(timeout=60)
        assert p.returncode == 143, p.returncode
        deadline = time.monotonic() + 5
        while _alive(master) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not _alive(master) and not Path(cp_dir).exists()
        rec = _record(env)
        assert rec["state"] == "aborted" and rec["rc"] == 143 and rec["attempts"][-1]["end_source"] == "signal" and rec["ended_at"]
    finally:
        for pid in (master, other):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
