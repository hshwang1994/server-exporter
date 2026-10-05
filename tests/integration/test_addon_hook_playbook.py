"""Add-on hook 엔진 테스트 — 실제 ansible-playbook 으로 공통 조립 코드와 hook 을 태운다 (2026-09-21, 2026-10-03 D8 개정).

왜 필요한가:
    hook 의 약속은 "ADDON_DIR 이 없으면 결과가 hook 도입 전과 같다" 와 "Add-on 이 무엇을 하든
    status · sections · diagnosis · 기존 data 는 바뀌지 않는다" 다. 이는 include_role · role
    filter_plugins · block/rescue · ignore_unreachable · apply.timeout 같은 Ansible 실행 동작에 달려 있어 정적
    검사로는 증명되지 않는다. tests/fixtures/addon/harness.yml 이 실제 init_fragments → merge_fragment →
    build_* → inject schema_version → CHECKPOINT → run_addon.yml → json_only 콜백을 그대로 태운다.

D8(2026-10-03) 이후 추가로 확인하는 것:
    - 콜백이 CHECKPOINT 를 gather_checkpoint.jsonl 에 host 당 1줄 남기고, 그 줄은 hook 이 없을 때의 OUTPUT 과 같다
      (Add-on 이 무엇을 하든 보존된 기본 결과는 동일).
    - 진행 이벤트(gather_progress.jsonl): checkpoint → addon_started → addon_done → emitted 순.
    - Add-on 이 돈 host 는 meta.finished_at / duration_ms 가 갱신된다 (harness 는 null 로 시작).
    - 2026-10-05 (8차 R3): Add-on 태스크별 시간 제한(apply.timeout)은 없다. 오래 걸리는 태스크는 끝까지 기다리고, 끝나지 않는
      Add-on 은 수집 실행 한계(INT, scripts/run_gather.sh 와 같은 timeout)가 멈춘다 — 그때 CHECKPOINT 의 기본 결과는 그대로다.

비교 방식:
    `data` 키 순서는 원래 실행마다 달라진다 (merge_fragment 의 union 이 문자열 hash 에 의존 —
    hook 과 무관한 기존 동작). byte 비교는 PYTHONHASHSEED 를 고정해 같은 조건에서 한다. Add-on 이 돈 결과는
    meta 의 두 시각 값만 빼고(`_core`) 비교한다 — 시각은 실행마다 다르다.

실행 조건:
    Linux / WSL 의 ansible-playbook 이 있어야 한다 (없거나 Windows 면 skip). 다른 버전으로 돌리려면
    ANSIBLE_PLAYBOOK_BIN 에 실행 파일 경로를 준다 (운영과 같은 2.20.3 확인용).
    unreachable 시나리오는 192.0.2.1(TEST-NET-1, 라우팅되지 않는 문서용 주소)로 SSH 연결을
    시도해 3초 안에 실패하는 것을 이용한다. 실장비에는 연결하지 않는다.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "addon"
# Windows 는 Ansible 제어 노드를 지원하지 않는다 (패키지가 깔려 있어도 CLI 가 시작 단계에서 멈춘다).
PLAYBOOK_BIN = os.environ.get("ANSIBLE_PLAYBOOK_BIN") or (
    None if os.name == "nt" else shutil.which("ansible-playbook"))

if not PLAYBOOK_BIN:
    pytest.skip("ansible-playbook 을 쓸 수 없는 환경 — 엔진 테스트는 Linux / WSL 에서 실행한다",
                allow_module_level=True)

HOSTS = [
    {"service_ip": "192.0.2.10", "physical_purpose": "DB", "note": "{{ 7*7 }}"},
    {"service_ip": "192.0.2.11", "physical_purpose": "APP", "note": "n2"},
]
SLOW_TASK_SEC = 6        # 오래 걸리지만 끝나는 Add-on 태스크 — 종전 태스크별 제한(시험값 3 s)보다 길다
HANG_LIMIT_SEC = 6       # 끝나지 않는 Add-on(sleep 40)을 멈추는 시험용 실행 한계 (운영은 최대 6시간)
SCENARIOS = {
    # 이름: (ADDON_DIR, hook 포함 여부, 추가 -e)
    "baseline": (None, False, []),
    "unset": (None, True, []),
    "missing": ("__missing__", True, []),
    # 디렉터리는 있지만 tasks/main.yml 이 없다 (Add-on 상위 폴더를 가리킨 실수)
    "no_entry": (FIXTURES, True, []),
    "empty": (FIXTURES / "empty", True, []),
    "ok": (FIXTURES / "ok", True, []),
    # 끝에 '/' 를 붙인 설정 실수 — 그대로 동작해야 한다
    "ok_trailing_slash": (f"{FIXTURES / 'ok'}/", True, []),
    "bad_config": (FIXTURES / "bad_config", True, []),
    "fail_runtime": (FIXTURES / "fail_runtime", True, []),
    "unreachable": (FIXTURES / "unreachable", True, []),
    # 오래 걸리는 태스크 — 태스크별 제한이 없으므로 끝까지 기다린다 (8차 R3)
    "slow": (FIXTURES / "hang", True, ["-e", f"addon_fixture_sleep={SLOW_TASK_SEC}"]),
}
HOOK_RAN = [n for n, (d, h, _) in SCENARIOS.items() if d is not None and h]


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """시나리오마다 playbook 을 한 번 실행해 결과 줄(raw) · envelope · checkpoint · progress 를 모은다."""
    tmp = tmp_path_factory.mktemp("addon_engine")
    out = {}
    for name, (addon_dir, with_hook, extra) in SCENARIOS.items():
        env = {k: v for k, v in os.environ.items() if k != "ADDON_DIR"}
        result_file = tmp / f"{name}.jsonl"
        checkpoint_file = tmp / f"{name}.checkpoint.jsonl"
        progress_file = tmp / f"{name}.progress.jsonl"
        env.update({
            "REPO_ROOT": str(REPO),
            "ANSIBLE_CONFIG": str(REPO / "ansible.cfg"),
            "INVENTORY_JSON": json.dumps(HOSTS, ensure_ascii=False),
            "ANSIBLE_JSON_OUTPUT_FILE": str(result_file),
            "ANSIBLE_JSON_CHECKPOINT_FILE": str(checkpoint_file),
            "ANSIBLE_JSON_PROGRESS_FILE": str(progress_file),
            "PYTHONHASHSEED": "0",
        })
        if addon_dir == "__missing__":
            env["ADDON_DIR"] = str(tmp / "no-such-addon")
        elif addon_dir is not None:
            env["ADDON_DIR"] = str(addon_dir)
        cmd = [PLAYBOOK_BIN, "-i", str(REPO / "os-gather" / "inventory.sh"),
               str(FIXTURES / "harness.yml")] + extra
        if not with_hook:
            cmd += ["-e", "harness_hook=false"]
        t0 = time.monotonic()
        proc = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=600)
        elapsed = time.monotonic() - t0
        assert proc.returncode == 0, f"{name}: rc={proc.returncode}\n{proc.stderr[-3000:]}"
        raw = result_file.read_text(encoding="utf-8")
        envelopes = [json.loads(line) for line in raw.splitlines() if line.strip()]
        cps = [json.loads(line) for line in checkpoint_file.read_text(encoding="utf-8").splitlines() if line.strip()] \
            if checkpoint_file.is_file() else []
        progress = [json.loads(line) for line in progress_file.read_text(encoding="utf-8").splitlines() if line.strip()] \
            if progress_file.is_file() else []
        out[name] = {"raw": raw, "by_ip": {e["ip"]: e for e in envelopes}, "count": len(envelopes),
                     "stdout_lines": [l for l in proc.stdout.splitlines() if l.strip()],
                     "checkpoint_by_ip": {c["ip"]: c for c in cps}, "checkpoint_count": len(cps),
                     "progress": progress, "elapsed": elapsed}
    return out


def _core(env: dict) -> dict:
    """Add-on 이 갱신하는 두 시각 값을 뺀 envelope (나머지는 글자 그대로 비교한다)."""
    e = copy.deepcopy(env)
    if isinstance(e.get("meta"), dict):
        e["meta"].pop("finished_at", None)
        e["meta"].pop("duration_ms", None)
    return e


def _dump(env: dict) -> str:
    return json.dumps(env, ensure_ascii=False, separators=(",", ":"))


def _same_except(env: dict, base: dict, *skip: str) -> None:
    env, base = _core(env), _core(base)
    for key in base:
        if key not in skip:
            assert env[key] == base[key], f"{key} 가 바뀌었다"
    assert set(env) == set(base), "envelope 최상위 키 구성이 바뀌었다"


def _events(run, ip):
    return [p["event"] for p in run["progress"] if p.get("host") == ip]


def _subsequence(needle, haystack):
    it = iter(haystack)
    return all(any(x == n for x in it) for n in needle)


def test_every_scenario_yields_one_envelope_per_host(runs):
    for name, run in runs.items():
        assert run["count"] == len(HOSTS), f"{name}: envelope {run['count']}개 (기대 {len(HOSTS)})"
        assert set(run["by_ip"]) == {h["service_ip"] for h in HOSTS}, name
        assert len(run["stdout_lines"]) == len(HOSTS), f"{name}: stdout 에는 OUTPUT 만 (CHECKPOINT 는 파일로만)"


def test_unset_addon_dir_output_is_byte_identical_to_no_hook(runs):
    assert runs["unset"]["raw"] == runs["baseline"]["raw"]


def test_checkpoint_is_written_once_per_host_and_equals_no_hook_output(runs):
    """CHECKPOINT 줄 = hook 이 없을 때의 OUTPUT. Add-on 이 무엇을 하든(빈 결과 · 실패 · 끊김 · hang) 보존본은 같다."""
    for name, run in runs.items():
        assert run["checkpoint_count"] == len(HOSTS), f"{name}: checkpoint {run['checkpoint_count']}줄"
        for ip, cp in run["checkpoint_by_ip"].items():
            assert _dump(cp) == _dump(runs["baseline"]["by_ip"][ip]), f"{name}/{ip}: checkpoint 가 기본 결과와 다르다"


def test_progress_events_order(runs):
    for name, run in runs.items():
        for h in HOSTS:
            ev = _events(run, h["service_ip"])
            assert ev[-1] == "emitted", f"{name}/{h['service_ip']}: {ev}"
            if name in HOOK_RAN:
                assert _subsequence(["checkpoint", "addon_started", "addon_done", "emitted"], ev), f"{name}: {ev}"
            else:
                assert _subsequence(["checkpoint", "emitted"], ev) and "addon_started" not in ev, f"{name}: {ev}"


def test_addon_run_restamps_meta_finish_time(runs):
    for name, run in runs.items():
        for ip, env in run["by_ip"].items():
            meta = env["meta"]
            if name in HOOK_RAN:
                assert isinstance(meta["finished_at"], str) and meta["finished_at"].endswith("Z"), f"{name}/{ip}"
                assert isinstance(meta["duration_ms"], int) and meta["duration_ms"] >= 0, f"{name}/{ip}"
            else:
                assert meta["finished_at"] is None and meta["duration_ms"] is None, f"{name}/{ip}"
            assert set(meta) == {"adapter_id", "finished_at", "duration_ms"}, "meta 키 구성 불변"


def test_addon_with_nothing_to_add_changes_only_the_time_stamps(runs):
    for ip, env in runs["empty"]["by_ip"].items():
        assert _dump(_core(env)) == _dump(_core(runs["baseline"]["by_ip"][ip]))


@pytest.mark.parametrize("scenario", ["missing", "no_entry"])
def test_missing_addon_dir_adds_exactly_one_addon_error(runs, scenario):
    for ip, env in runs[scenario]["by_ip"].items():
        base = runs["baseline"]["by_ip"][ip]
        _same_except(env, base, "errors")
        assert env["errors"][:-1] == base["errors"]
        added = env["errors"][-1]
        assert added["section"] == "addon"
        assert "ADDON_DIR" not in added["message"] and "/" not in added["message"]
        assert "ADDON_DIR=" in added["detail"] and "cause=addon_entry_not_found" in added["detail"]
        assert "addon" not in env["data"]


def test_trailing_slash_addon_dir_behaves_like_plain_path(runs):
    for ip, env in runs["ok_trailing_slash"]["by_ip"].items():
        assert _dump(_core(env)) == _dump(_core(runs["ok"]["by_ip"][ip]))


def test_addon_result_lands_only_in_data_addon(runs):
    by_ip = {h["service_ip"]: h for h in HOSTS}
    for ip, env in runs["ok"]["by_ip"].items():
        base = runs["baseline"]["by_ip"][ip]
        _same_except(env, base, "data")
        assert {k: v for k, v in env["data"].items() if k != "addon"} == base["data"]
        assert env["data"]["addon"] == {"fixture": {
            "target": "linux",
            "purpose": by_ip[ip]["physical_purpose"],
            "note": by_ip[ip]["note"],          # "{{ 7*7 }}" 가 해석되지 않고 글자 그대로
            "filter": "fixture:x",              # role filter_plugins 자동 로드
            "text": "line1\nline2\n",
        }}


def test_addon_notes_become_one_error_without_data(runs):
    for ip, env in runs["bad_config"]["by_ip"].items():
        base = runs["baseline"]["by_ip"][ip]
        _same_except(env, base, "errors")
        assert env["errors"][:-1] == base["errors"]
        assert env["errors"][-1]["section"] == "addon"
        assert env["errors"][-1]["detail"] == "config.yml 을 읽지 못했습니다 (fixture)"


def test_addon_runtime_failure_is_isolated(runs):
    for ip, env in runs["fail_runtime"]["by_ip"].items():
        base = runs["baseline"]["by_ip"][ip]
        _same_except(env, base, "errors")      # 실패 전 중간 결과(partial)는 data 에 남지 않는다
        added = env["errors"][-1]
        assert env["errors"][:-1] == base["errors"]
        assert added["section"] == "addon"
        assert "cause=addon_failed" in added["detail"] and "fixture failure" in added["detail"]


def test_connection_lost_during_addon_keeps_the_host(runs):
    for ip, env in runs["unreachable"]["by_ip"].items():
        base = runs["baseline"]["by_ip"][ip]
        _same_except(env, base, "errors", "data")
        assert {k: v for k, v in env["data"].items() if k != "addon"} == base["data"]
        assert env["data"]["addon"] == {"fixture": {"reached": False}}
        assert env["errors"][:-1] == base["errors"]
        assert env["errors"][-1]["detail"] == "remote command not run: target unreachable"


def test_slow_addon_task_is_waited_for_not_cut(runs):
    """8차 R3: 종전 태스크별 제한(시험값 3 s)보다 오래 걸리는 Add-on 태스크도 끝까지 기다린다 — 결과가 남고 Add-on 오류가 없다."""
    run = runs["slow"]
    assert run["elapsed"] >= SLOW_TASK_SEC, f"slow 시나리오가 {run['elapsed']:.1f}s — 태스크가 끝나기 전에 끊겼다"
    for ip, env in run["by_ip"].items():
        base = runs["baseline"]["by_ip"][ip]
        _same_except(env, base, "data")
        assert env["data"]["addon"] == {"partial": {"before_hang": True}}
        assert env["errors"] == base["errors"], "오래 걸린 것은 실패가 아니다"


def test_hanging_addon_is_stopped_by_the_run_limit_and_the_checkpoint_is_kept(runs, tmp_path):
    """8차 R3 · R1: 끝나지 않는 Add-on 은 수집 실행 한계(run_gather.sh 와 같은 timeout --signal=INT)가 멈춘다.
    CHECKPOINT 는 hook 없는 결과와 같고, 결과 정리(Layer A)는 그 값에 "추가 수집 중 중단" 1건만 붙여 host 당 1줄을 만든다."""
    timeout_bin = shutil.which("timeout")
    if not timeout_bin:
        pytest.skip("coreutils timeout 이 없다")
    env = {k: v for k, v in os.environ.items() if k != "ADDON_DIR"}
    ws = tmp_path / "ws"
    ws.mkdir()
    env.update({"REPO_ROOT": str(REPO), "ANSIBLE_CONFIG": str(REPO / "ansible.cfg"), "INVENTORY_JSON": json.dumps(HOSTS, ensure_ascii=False),
                "ANSIBLE_JSON_OUTPUT_FILE": str(ws / "gather_output.json"), "ANSIBLE_JSON_CHECKPOINT_FILE": str(ws / "gather_checkpoint.jsonl"),
                "ANSIBLE_JSON_PROGRESS_FILE": str(ws / "gather_progress.jsonl"), "PYTHONHASHSEED": "0", "ADDON_DIR": str(FIXTURES / "hang")})
    t0 = time.monotonic()
    proc = subprocess.run([timeout_bin, "--signal=INT", "--kill-after=30", str(HANG_LIMIT_SEC), PLAYBOOK_BIN, "-i",
                           str(REPO / "os-gather" / "inventory.sh"), str(FIXTURES / "harness.yml")],
                          cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    elapsed = time.monotonic() - t0
    assert proc.returncode == 124, f"rc={proc.returncode} — 실행 한계가 INT 로 멈춰야 한다\n{proc.stderr[-2000:]}"
    assert HANG_LIMIT_SEC <= elapsed < 40, f"{elapsed:.1f}s"
    cps = {json.loads(x)["ip"]: json.loads(x) for x in (ws / "gather_checkpoint.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()}
    assert set(cps) == {h["service_ip"] for h in HOSTS}
    for ip, cp in cps.items():
        assert _dump(cp) == _dump(runs["baseline"]["by_ip"][ip]), f"{ip}: CHECKPOINT 는 hook 없는 결과와 같다"
    out = (ws / "gather_output.json")
    assert not out.exists() or not out.read_text(encoding="utf-8").strip(), "OUTPUT 전에 멈췄다"
    manifest = {"schema": 1, "build": {"job": "t", "number": "1", "url": "u"}, "channel": "os",
                "request": {"loc": "git", "deploymentEnvironmentId": "d", "eventUuid": "e", "callbackUrl": "http://x"},
                "ips": [h["service_ip"] for h in HOSTS]}
    (ws / "gather_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (ws / "gather_rc.txt").write_text("124\n", encoding="utf-8")
    fin = subprocess.run([sys.executable, str(REPO / "scripts" / "finalize_gather_output.py"), "--workspace", str(ws), "--repo-root", str(REPO),
                          "--outcome", "timeout", "--limit-reason", "gather_limit"], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert fin.returncode == 0, fin.stderr
    report = json.loads((ws / "gather_finalize_report.json").read_text(encoding="utf-8"))
    assert report["by_origin"] == {"output": 0, "checkpoint": len(HOSTS), "synthetic": 0}, report
    for line in (ws / "gather_final.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        env_ = json.loads(line)
        base = runs["baseline"]["by_ip"][env_["ip"]]
        for key in ("status", "sections", "diagnosis", "data"):
            assert env_[key] == base[key], f"{env_['ip']}: {key} 는 CHECKPOINT(기본 결과) 그대로"
        assert env_["errors"][:-1] == base["errors"]
        assert env_["errors"][-1]["section"] == "addon" and "add-on started but did not finish" in env_["errors"][-1]["detail"]


def test_output_failure_after_checkpoint_is_reconciled_from_checkpoint(tmp_path):
    """F01 (2026-10-05) 실제 ansible 재현: CHECKPOINT 뒤 OUTPUT 태스크가 실패하면 콜백의 종료 보충이 CHECKPOINT 조립본을
    쓴다. 종전에는 기본 실패 envelope(OUTPUT_BUILD_FAILED)이 OUTPUT 파일에 들어가 CHECKPOINT 값을 가렸다."""
    env = {k: v for k, v in os.environ.items() if k != "ADDON_DIR"}
    out_file, cp_file, pg_file = tmp_path / "out.jsonl", tmp_path / "cp.jsonl", tmp_path / "pg.jsonl"
    env.update({
        "REPO_ROOT": str(REPO), "ANSIBLE_CONFIG": str(REPO / "ansible.cfg"),
        "INVENTORY_JSON": json.dumps(HOSTS, ensure_ascii=False),
        "ANSIBLE_JSON_OUTPUT_FILE": str(out_file), "ANSIBLE_JSON_CHECKPOINT_FILE": str(cp_file),
        "ANSIBLE_JSON_PROGRESS_FILE": str(pg_file), "PYTHONHASHSEED": "0",
    })
    cmd = [PLAYBOOK_BIN, "-i", str(REPO / "os-gather" / "inventory.sh"), str(FIXTURES / "harness.yml"),
           "-e", "harness_hook=false", "-e", "harness_break_output=true"]
    proc = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=600)
    assert proc.returncode != 0, "OUTPUT 태스크 실패 — ansible 은 실패 rc 를 낸다"
    envelopes = [json.loads(line) for line in out_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    checkpoints = {c["ip"]: c for c in (json.loads(line) for line in cp_file.read_text(encoding="utf-8").splitlines() if line.strip())}
    assert sorted(e["ip"] for e in envelopes) == sorted(h["service_ip"] for h in HOSTS), "host 당 1개"
    for e in envelopes:
        cp = checkpoints[e["ip"]]
        for key in ("status", "sections", "diagnosis", "data", "meta", "correlation"):
            assert e[key] == cp[key], f"{e['ip']}: {key} 는 CHECKPOINT 값 그대로"
        assert e["errors"][:-1] == cp["errors"]
        assert e["errors"][-1]["detail"].startswith("finalized from checkpoint; reconciled by callback")
    events = [json.loads(line) for line in pg_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert sorted(ev["host"] for ev in events if ev["event"] == "reconciled" and ev.get("source") == "checkpoint") == \
        sorted(h["service_ip"] for h in HOSTS)

