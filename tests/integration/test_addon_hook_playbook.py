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
    - 끝나지 않는 Add-on 태스크는 apply.timeout 이 끊고 rescue 가 errors[] 1건을 남긴다.

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
HANG_TASK_TIMEOUT = 3
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
    # 끝나지 않는 태스크 — apply.timeout(3 s)이 끊는다 (fixture 의 sleep 은 40 s)
    "hang": (FIXTURES / "hang", True, ["-e", f"_addon_task_timeout={HANG_TASK_TIMEOUT}"]),
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


def test_hanging_addon_task_is_cut_by_the_per_task_timeout(runs):
    """fixture 의 sleep 40 이 3 s 에 끊긴다 — 실행 전체가 sleep 보다 훨씬 빨리 끝나고 rescue 가 errors[] 1건을 남긴다."""
    run = runs["hang"]
    assert run["elapsed"] < 30, f"hang 시나리오가 {run['elapsed']:.1f}s — timeout 이 태스크를 끊지 못했다"
    for ip, env in run["by_ip"].items():
        base = runs["baseline"]["by_ip"][ip]
        _same_except(env, base, "errors")      # before_hang 중간 결과는 버려진다 (rescue 경로)
        added = env["errors"][-1]
        assert env["errors"][:-1] == base["errors"]
        assert added["section"] == "addon"
        assert "cause=addon_failed" in added["detail"] and "task that never finishes" in added["detail"]
        assert "time frame" in added["detail"] or "timed out" in added["detail"].lower(), added["detail"]


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

