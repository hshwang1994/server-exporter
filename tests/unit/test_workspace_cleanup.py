"""scripts/workspace_cleanup.py — Runner 에 남은 이 Job 의 끝난 작업 폴더 정리 (2026-10-05, 8차 R8).

고정하는 것
  - 이 Job 의 `<job-base>-<번호>` 폴더만, 소유 기록(.se_workspace.json) 또는 옛 접수 목록(gather_manifest.json)이 이 Job · 이 번호를 가리킬 때만 본다.
  - 결과 보관을 확인한 폴더와 결과가 없는 폴더는 7일 뒤 지우고, 보관하지 못한 결과가 있는 폴더는 결과 파일만 그 자리에 남긴다(유일한 결과 보호).
  - 끝나지 않았을 수 있는 폴더 · 최근 폴더 · 지금 빌드 · 링크 · 다른 Job/빌드 · 쓰는 중인 폴더는 건드리지 않는다.
  - 하루 한 번(같은 Runner · 같은 Job), 겹치면 잠금으로 건너뛴다. 종료 코드는 언제나 0, 결과는 콘솔 줄과 JSON 보고서.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "workspace_cleanup.py"
_spec = importlib.util.spec_from_file_location("workspace_cleanup", SCRIPT)
wc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wc)

JOB = "clovirone-cicd/clovirone-server-gather-main"
BASE = "clovirone-server-gather-main"
DAY = 86400
LINUX = sys.platform.startswith("linux")


def _ws(root: Path, number: int, *, job=JOB, build=None, started=None, ended=None, preserved=None, results=("gather_output.json",),
        repo_copy=True, owner=True, manifest=False) -> Path:
    d = root / f"{BASE}-{number}"
    d.mkdir()
    if owner:
        rec = {"schema": 1, "job": job, "job_base": BASE, "build": str(build if build is not None else number)}
        if started is not None:
            rec["started_epoch"] = started
        if ended is not None:
            rec["ended_epoch"] = ended
        if preserved is not None:
            rec["preserved"] = preserved
        (d / ".se_workspace.json").write_text(json.dumps(rec), encoding="utf-8")
    for name in results:
        (d / name).write_text('{"ip":"10.0.0.1"}\n', encoding="utf-8")
    if manifest:
        (d / "gather_manifest.json").write_text(json.dumps({"build": {"job": job, "number": str(number)}}), encoding="utf-8")
    if repo_copy:
        (d / "os-gather").mkdir()
        (d / "os-gather" / "site.yml").write_text("- hosts: all\n" * 200, encoding="utf-8")
        (d / "ansible.cfg").write_text("[defaults]\n", encoding="utf-8")
    return d


def _run(root: Path, current: Path | None = None, **over):
    current = current or (root / f"{BASE}-999")
    current.mkdir(exist_ok=True)
    rep = root / "report.json"
    args = ["--current", str(current), "--job", over.get("job", JOB), "--job-base", BASE, "--build-limit-sec", "43200",
            "--keep-days", "7", "--every-sec", str(over.get("every", 86400)), "--report", str(rep)]
    assert wc.main(args) == 0
    return json.loads(rep.read_text(encoding="utf-8"))


def _reasons(rep):
    return {s["dir"]: s["reason"] for s in rep["skipped"]}


def test_preserved_and_empty_old_folders_are_deleted_and_unpreserved_results_stay_in_place(tmp_path):
    now = int(time.time())
    old = now - 8 * DAY
    preserved = _ws(tmp_path, 101, started=old - 3600, ended=old, preserved=True)
    empty = _ws(tmp_path, 102, started=old - 3600, ended=old, preserved=False, results=())
    unpreserved = _ws(tmp_path, 103, started=old - 3600, ended=old, preserved=False, results=("gather_output.json", "gather_manifest.json"))
    (unpreserved / "gather_auth_evidence").mkdir()
    (unpreserved / "gather_auth_evidence" / "a.json").write_text("{}", encoding="utf-8")
    rep = _run(tmp_path)
    assert rep["ran"] is True
    deleted = {d["dir"]: d["why"] for d in rep["deleted"]}
    assert deleted == {preserved.name: "preserved", empty.name: "no_results"}
    assert not preserved.exists() and not empty.exists()
    # 보관하지 못한 결과: 결과 파일만 그 자리에 남고, 다시 만들 수 있는 부분(저장소 사본)은 지운다
    assert sorted(p.name for p in unpreserved.iterdir()) == [".se_kept_results.json", ".se_workspace.json", "gather_auth_evidence",
                                                             "gather_manifest.json", "gather_output.json"]
    kept = json.loads((unpreserved / ".se_kept_results.json").read_text(encoding="utf-8"))
    assert kept["reason"] == "not_preserved" and {k["name"] for k in kept["kept"]} == {"gather_output.json", "gather_manifest.json", "gather_auth_evidence/"}
    assert rep["reduced"][0]["dir"] == unpreserved.name and rep["reduced"][0]["freed_bytes"] > 0
    assert [k["dir"] for k in rep["kept_results"]] == [unpreserved.name]
    # 다음 날 다시 돌아도 줄인 폴더는 지우지 않고 다시 알린다(사람이 확인한 뒤 지운다)
    (tmp_path / f".se-cleanup-{BASE}.json").write_text(json.dumps({"last": now - 2 * DAY}), encoding="utf-8")
    rep2 = _run(tmp_path)
    assert unpreserved.exists() and [k["dir"] for k in rep2["kept_results"]] == [unpreserved.name] and rep2["deleted"] == []


def test_recent_running_foreign_and_current_folders_are_untouched(tmp_path):
    now = int(time.time())
    recent = _ws(tmp_path, 201, started=now - 2 * DAY, ended=now - DAY, preserved=True)
    running = _ws(tmp_path, 202, started=now - 3600)                      # 끝 기록 없음, 빌드 한계 + 1시간 안
    other_job = _ws(tmp_path, 203, job="clovirone-cicd/other", started=now - 30 * DAY, ended=now - 30 * DAY, preserved=True)
    other_build = _ws(tmp_path, 204, build=1204, started=now - 30 * DAY, ended=now - 30 * DAY, preserved=True)
    no_owner = _ws(tmp_path, 205, owner=False)
    for f in [no_owner, *no_owner.rglob("*")]:
        os.utime(f, (now - 20 * DAY, now - 20 * DAY))                     # 오래된, 소유를 모르는 폴더
    fresh = _ws(tmp_path, 207, owner=False, results=())                    # 막 시작한 빌드(checkout 중, 소유 기록 전)
    current = _ws(tmp_path, 206, started=now - 30 * DAY, ended=now - 30 * DAY, preserved=True)
    for name in ("unrelated-dir", f"{BASE}", f"{BASE}-12x", f"other-{BASE}-5"):
        (tmp_path / name).mkdir()
    rep = _run(tmp_path, current=current)
    r = _reasons(rep)
    assert r[recent.name] == "recent" and r[running.name] == "may_be_running"
    assert r[other_job.name] == "owner_record_mismatch" and r[other_build.name] == "owner_record_mismatch"
    assert r[no_owner.name] == "no_owner_record"
    assert r[fresh.name] == "may_be_running", "소유 기록 전의 새 빌드 폴더를 '소유를 모르는 폴더' 로 알리지 않는다"
    assert current.name not in r and rep["deleted"] == [] and rep["reduced"] == []
    for d in (recent, running, other_job, other_build, no_owner, fresh, current):
        assert (d / "os-gather" / "site.yml").is_file(), d.name
    for name in ("unrelated-dir", f"{BASE}", f"{BASE}-12x", f"other-{BASE}-5"):
        assert (tmp_path / name).is_dir() and name not in r


def test_unknown_end_uses_start_plus_build_limit_and_legacy_manifest_folders_keep_their_results(tmp_path):
    now = int(time.time())
    no_end_old = _ws(tmp_path, 301, started=now - 10 * DAY, preserved=False, results=())   # 끝 기록 없음 → 시작 + 12시간을 끝으로
    no_end_mid = _ws(tmp_path, 302, started=now - 5 * DAY, preserved=False, results=())    # 그렇게 봐도 7일이 안 됐다
    legacy = _ws(tmp_path, 303, owner=False, manifest=True)
    for f in legacy.iterdir():
        if f.is_file():
            os.utime(f, (now - 9 * DAY, now - 9 * DAY))
    rep = _run(tmp_path)
    assert {d["dir"] for d in rep["deleted"]} == {no_end_old.name}
    assert _reasons(rep)[no_end_mid.name] == "recent"
    red = {x["dir"]: x for x in rep["reduced"]}
    assert red[legacy.name]["owner"] == "manifest_legacy" and set(red[legacy.name]["kept"]) == {"gather_output.json", "gather_manifest.json"}
    assert json.loads((legacy / ".se_kept_results.json").read_text(encoding="utf-8"))["reason"] == "legacy_not_verified"
    assert not (legacy / "os-gather").exists()


def test_control_dirs_follow_their_folder(tmp_path):
    now = int(time.time())
    old = now - 8 * DAY
    gone_base_tmp = tmp_path / f"{BASE}-401@tmp"
    gone_base_tmp.mkdir()
    young_tmp = tmp_path / f"{BASE}-402@tmp"
    young_tmp.mkdir()
    live = _ws(tmp_path, 403, started=now - 3600)
    live_tmp = tmp_path / f"{BASE}-403@tmp"
    live_tmp.mkdir()
    done = _ws(tmp_path, 404, started=old - 3600, ended=old, preserved=True)
    done_tmp = tmp_path / f"{BASE}-404@tmp"
    done_tmp.mkdir()
    for d in (gone_base_tmp, live_tmp, done_tmp):
        os.utime(d, (old, old))
    rep = _run(tmp_path)
    deleted = {d["dir"]: d["why"] for d in rep["deleted"]}
    assert deleted == {gone_base_tmp.name: "control_dir", done.name: "preserved", done_tmp.name: "control_dir"}
    assert young_tmp.is_dir(), "짝이 없어도 빌드 한계 + 1시간이 지나지 않은 제어 폴더는 남긴다"
    assert live.is_dir() and live_tmp.is_dir(), "짝 폴더가 아직 남아 있으면 제어 폴더도 남긴다"


def test_daily_stamp_and_lock(tmp_path):
    now = int(time.time())
    old = now - 8 * DAY
    _ws(tmp_path, 501, started=old - 3600, ended=old, preserved=True)
    (tmp_path / f".se-cleanup-{BASE}.json").write_text(json.dumps({"last": now - 3600}), encoding="utf-8")
    rep = _run(tmp_path)
    assert rep["ran"] is False and rep["skipped_reason"] == "checked_recently" and (tmp_path / f"{BASE}-501").is_dir()
    (tmp_path / f".se-cleanup-{BASE}.json").unlink()
    lock = tmp_path / f".se-cleanup-{BASE}.lock"
    lock.mkdir()
    rep = _run(tmp_path)
    assert rep["ran"] is False and rep["skipped_reason"] == "locked" and (tmp_path / f"{BASE}-501").is_dir()
    os.utime(lock, (now - 2 * 3600, now - 2 * 3600))                       # 1시간이 지난 잠금은 버려진 것으로 본다
    rep = _run(tmp_path)
    assert rep["ran"] is True and not (tmp_path / f"{BASE}-501").exists() and not lock.exists()
    stamp = json.loads((tmp_path / f".se-cleanup-{BASE}.json").read_text(encoding="utf-8"))
    assert abs(stamp["last"] - now) < 120
    assert "disk" in rep and rep["disk"]["total_bytes"] > 0


@pytest.mark.skipif(not LINUX, reason="심볼릭 링크 · /proc 은 Linux(Runner · WSL)에서 본다")
def test_links_and_in_use_folders_are_not_followed_or_deleted(tmp_path):
    now = int(time.time())
    old = now - 8 * DAY
    outside = tmp_path / "outside"
    outside.mkdir()
    target = _ws(outside, 601, started=old - 3600, ended=old, preserved=True)
    root = tmp_path / "root"
    root.mkdir()
    (root / f"{BASE}-601").symlink_to(target, target_is_directory=True)
    busy = _ws(root, 602, started=old - 3600, ended=old, preserved=True)
    inner_link_target = tmp_path / "keep_me.txt"
    inner_link_target.write_text("x", encoding="utf-8")
    deletable = _ws(root, 603, started=old - 3600, ended=old, preserved=True)
    (deletable / "link_out").symlink_to(inner_link_target)
    proc = subprocess.Popen(["sleep", "60"], cwd=str(busy))
    try:
        rep = _run(root)
    finally:
        proc.kill()
        proc.wait()
    r = _reasons(rep)
    assert r[f"{BASE}-601"] == "not_a_real_directory" and target.is_dir(), "링크 폴더와 그 대상은 건드리지 않는다"
    assert r[busy.name] == "in_use" and busy.is_dir()
    assert not deletable.exists() and inner_link_target.is_file(), "폴더 안의 링크는 따라가지 않고 링크만 지운다"


def test_cli_always_exits_zero_and_prints_timed_lines(tmp_path):
    now = int(time.time())
    _ws(tmp_path, 701, started=now - 9 * DAY, ended=now - 8 * DAY, preserved=False)
    cur = tmp_path / f"{BASE}-702"
    cur.mkdir()
    r = subprocess.run([sys.executable, str(SCRIPT), "--current", str(cur), "--job", JOB, "--job-base", BASE, "--report", str(tmp_path / "r.json")],
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines and all(__import__("re").match(r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d [+-]\d\d:\d\d\] \[작업 폴더 정리\] ", ln) for ln in lines), lines
    assert any("보관하지 못한 결과를 남긴 폴더 1개" in ln for ln in lines)
    # 잘못된 입력에도 수집 결과를 바꾸지 않는다 — 없는 위치를 줘도 0
    r = subprocess.run([sys.executable, str(SCRIPT), "--current", str(tmp_path / "nope" / "x"), "--job", JOB, "--job-base", BASE],
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0


@pytest.mark.source_text   # production_manifest.yml 은 main 전용 — production tree overlay(G14)에는 없다
def test_pipeline_wires_the_cleanup_and_records_ownership():
    portal = (REPO / "Jenkinsfile_portal").read_text(encoding="utf-8")
    assert "python3 scripts/workspace_cleanup.py --current" in portal and "exit 0" in portal
    assert "customWorkspace \"${env.JOB_BASE_NAME}-${env.BUILD_NUMBER}\"" in portal
    assert portal.count("writeFile(file: '.se_workspace.json'") == 2, "단계 시작(소유 · 시작 시각)과 보존 끝(끝 시각 · 보존 여부)"
    manifest = (REPO / "production_manifest.yml").read_text(encoding="utf-8")
    assert "scripts/workspace_cleanup.py" in manifest, "운영 runtime 파일 — production tree 에 들어간다"
