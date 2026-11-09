"""시나리오 묶음 투입 — 빌드 기록(journal) · 이어받기(adopt) (2026-11-09).

한 시나리오 = 직전 빌드의 파라미터를 그대로(eventUuid 만 새 값, overrides 는 덮어씀) 한 번 넣고 끝날 때까지 기다린다.

- 기록 `<runs>` : 끝난 시나리오 한 줄씩(결과 · checkout SHA · callback_body HTTP · 기대 일치 여부).
- 기록 `<runs>.started` (journal): 빌드 번호를 얻자마자 한 줄. 이 프로세스가 기다리는 중에 죽어도 번호가 남는다.
- adopt=True(기본 동작): 기대대로 끝난 시나리오는 그대로 두고, journal 에만 있는 빌드는 Jenkins 에서 아직 돌거나 기대 결과로
  끝났으면 새로 넣지 않고 그 빌드를 이어서 기다린다. 다른 결과로 끝났으면 새로 넣는다.
- NO_ADOPT 시나리오는 투입 시점의 관측이 증거라서 이어받지 않는다: E2E-A2(투입 전후 origin main tip), T5(시작 표지 + 10초 중단).
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Callable

TIP_OBSERVED = "E2E-A2"
STOP_AFTER_MARKER = {"T5": "정보 수집을 시작합니다"}
STOP_DELAY_S = 10
NO_ADOPT = {TIP_OBSERVED, *STOP_AFTER_MARKER}


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def last_by_scenario(path: Path) -> dict:
    out: dict = {}
    for r in read_jsonl(path):
        out[r["scenario"]] = r  # 같은 시나리오가 두 번 있으면 마지막 것
    return out


def append_jsonl(path: Path, rec: dict) -> None:
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(rec, ensure_ascii=False) + "\n")


def build_params(prev: dict, sets: dict, set_files: dict) -> dict:
    params = dict(prev)
    if "eventUuid" in params:
        params["eventUuid"] = str(uuid.uuid4())
    for k, v in sets.items():
        if k not in params:
            raise KeyError(f"unknown parameter {k}")
        params[k] = v
    for k, fp in set_files.items():
        if k not in params:
            raise KeyError(f"unknown parameter {k}")
        params[k] = Path(fp).read_text(encoding="utf-8").strip()
    return params


def run_plan(jk, job: str, entries: list[tuple[str, int, tuple[str, ...]]], *, runs: Path, prev_params: Callable[[int], dict],
             bodies: Path, body_name: Callable[[int], str], expect_sha: str = "", sets: dict | None = None,
             set_files: dict | None = None, adopt: bool = True, tip_of_main: Callable[[], str] | None = None,
             tip_file: Path | None = None, log: Callable[[str], None] = print) -> dict:
    """entries = [(시나리오, 직전 빌드, 허용 결과들)]. 시나리오별 마지막 기록을 돌려준다."""
    sets, set_files = sets or {}, set_files or {}
    journal = runs.with_name(runs.name + ".started")
    done: dict = {}
    for r in read_jsonl(runs):
        done.setdefault(r["scenario"], []).append(r)
    started: dict = {}
    for e in read_jsonl(journal):
        started.setdefault(e["scenario"], []).append(e)
    bodies.mkdir(parents=True, exist_ok=True)
    for scen, prev, accept in entries:
        if adopt:
            last = (done.get(scen) or [None])[-1]
            if last and last.get("ok_expected") and last.get("job", job) == job:
                log(f"[{scen}] keep #{last.get('build')} ({last.get('result')} - 앞 시도에서 기대대로 끝남)")
                continue
        params = build_params(prev_params(prev), sets, set_files)
        rec = {"scenario": scen, "job": job, "prev_build": prev, "expected": list(accept), "eventUuid": params.get("eventUuid"),
               "overrides": sorted([*sets, *set_files]), "loc": params.get("loc"), "target_type": params.get("target_type")}
        adopt_num = None
        if adopt and scen not in NO_ADOPT:
            recorded = {r0.get("build") for r0 in done.get(scen, [])}
            cands = [e0 for e0 in started.get(scen, []) if e0.get("job") == job and e0.get("build") not in recorded]
            if cands:
                e0 = cands[-1]
                b0 = jk.build_info(job, int(e0["build"]))
                if b0.get("building") or b0.get("result") in accept:
                    adopt_num = int(e0["build"])
                    rec["eventUuid"] = e0.get("eventUuid")
                    rec["adopted"] = True
                else:
                    log(f"[{scen}] 앞 시도의 #{e0['build']} 은 {b0.get('result')} 로 끝남 - 새로 넣는다")
        before_sha = before_epoch = None
        if adopt_num:
            num = adopt_num
            log(f"[{scen}] adopt #{num} (앞 시도가 넣은 빌드를 이어서 기다린다)")
        else:
            if scen == TIP_OBSERVED and tip_of_main:
                before_sha, before_epoch = tip_of_main(), int(time.time())
            log(f"[{scen}] trigger (prev #{prev}, loc={params.get('loc')}, target_type={params.get('target_type')})")
            num = jk.wait_build_number(jk.trigger(job, params))
            append_jsonl(journal, {"scenario": scen, "build": num, "job": job, "eventUuid": params.get("eventUuid"),
                                   "started_epoch": int(time.time())})
        rec["build"] = num
        log(f"[{scen}] build #{num} started")
        marker = STOP_AFTER_MARKER.get(scen)
        if marker and not adopt_num:
            t0 = time.time()
            while time.time() - t0 < 900:
                if jk.console_has(job, num, marker):
                    rec["marker_seen_epoch"] = int(time.time())
                    log(f"[{scen}] marker seen -> stop in {STOP_DELAY_S} s")
                    time.sleep(STOP_DELAY_S)
                    rec["stop_http"] = jk.stop(job, num)
                    rec["stop_epoch"] = int(time.time())
                    log(f"[{scen}] stop -> HTTP {rec['stop_http']}")
                    break
                time.sleep(2)
        b = jk.wait_done(job, num)
        rec["result"] = b.get("result")
        rec["duration_s"] = round((b.get("duration") or 0) / 1000)
        rec["checkout_sha"] = next((x["lastBuiltRevision"]["SHA1"] for x in b.get("actions", []) if x and "lastBuiltRevision" in x), None)
        code, body = jk.artifact_text(job, num, "callback_body.json")
        if code == 200:
            (bodies / body_name(num)).write_text(body, encoding="utf-8")
        rec["callback_body_http"] = code
        rec["ok_expected"] = rec["result"] in accept
        if expect_sha and rec["checkout_sha"] and not rec["checkout_sha"].startswith(expect_sha):
            rec["ok_expected"] = False
            rec["sha_mismatch"] = True
        if scen == TIP_OBSERVED and tip_of_main and not adopt_num:
            after_sha, after_epoch = tip_of_main(), int(time.time())
            tips = [{"job": job, "build": num, "sha_before": before_sha, "sha_after": after_sha, "before_epoch": before_epoch,
                     "after_epoch": after_epoch, "remote": "origin", "method": "git ls-remote origin refs/heads/main"}]
            if tip_file:
                tip_file.write_text(json.dumps(tips, ensure_ascii=False), encoding="utf-8")
            rec["tip_before"], rec["tip_after"] = before_sha, after_sha
        append_jsonl(runs, rec)
        done.setdefault(scen, []).append(rec)
        log(f"[{scen}] #{num} {rec['result']} {rec['duration_s']} s checkout={(rec['checkout_sha'] or '')[:8]} "
            f"{'[OK]' if rec['ok_expected'] else '[NG]'}")
    return {s: rs[-1] for s, rs in done.items()}
