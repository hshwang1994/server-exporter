#!/usr/bin/env python3
"""harness_verdict.py — Harness 시나리오의 관측값을 scenarios.json 기대값과 대조해 PASS / FAIL / PARTIAL 을 정한다 (2026-10-04).

입력(모두 Harness 빌드가 만든 파일; 없는 파일은 "관측 없음" 으로 처리)
  --summary   finalize_summary.json   (finalizer 가 archive 한 것을 unarchive 로 회수 — C1: recovery 로 회수 매체 선택 근거도 본다)
  --body      callback_body.json      (위와 같음 — sha256 을 sink 기록과 대조)
  --calls     harness_calls.json      (wrapper 가 기록한 step 호출 · unstable 메시지)
  --sink      sink/record.jsonl       (callback_sink.py 수신 기록)
  --preserve  preserve_state.json     (sePreserveGatherOutput() 뒤 env 플래그 · 파일 존재)
  --control   harness_control.json    (Harness 자체 관측: rethrown · sink_reachable · functions_sha256 · source · gather)
  --received  gather_received.jsonl   (9차 gather_stage: 가짜 ansible 이 시도마다 받은 대상 {attempt, hosts})
  --fixture   fixture_state.json      (접수 대상 순서 — 기대값의 대상 번호(1부터)를 IP 로 바꾼다)
  --event-uuid harness-<BUILD_TAG>    (2026-10-08 — 같은 Job 의 빌드가 동시에 돈다. 이 빌드의 요청만 수신 기록에 있어야 한다)
기대값이 있는 시나리오에는 격리 검사 둘이 더 붙는다(2026-10-08): 수신 기록의 eventUuid 가 전부 이 빌드의 것인가(sink_isolation) ·
  readTrusted 가 고정 후보 밖(Job branch 최신)을 읽지 않았는가(trusted_pinned). 기대값이 없는 보조 시나리오(sink_hold — main Job 의 POST 를 받는다)는 제외.
출력: harness_result.json {scenario, verdict, checks: [{name, expected, observed, ok}], problems, observed, meta}
종료 코드: 0 PASS · 1 FAIL · 2 PARTIAL(필요 관측이 없어 판정 불가 — 통과가 아니다) · 3 도구 실패
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

EXIT_PASS, EXIT_FAIL, EXIT_PARTIAL, EXIT_TOOL = 0, 1, 2, 3



def _write_lf(path, text):
    """LF 고정 쓰기 — Path.write_text(newline=) 는 Python 3.10+ 라 Runner 시스템 python3(3.9) 에서 못 쓴다."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)

def _load_json(path: str | None):
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return {"_unparsable": True}


def _load_jsonl(path: str | None) -> list[dict] | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"_unparsable": line[:80]})
    return out


def _body_envelopes(body_path) -> list | None:
    if not body_path or not Path(body_path).is_file():
        return None
    try:
        body = json.loads(Path(body_path).read_text(encoding="utf-8"))
    except ValueError:
        return None
    envs = body.get("gatherInfoJson") if isinstance(body, dict) else None
    return envs if isinstance(envs, list) else None


def _catalog() -> dict:
    """실패 문장 정본(common/vars/failure_reasons.yml) — 기대값이 문장 대신 키를 쓴다(복제 없음)."""
    try:
        import yaml
    except ImportError:
        return {}
    path = Path(__file__).resolve().parents[3] / "common" / "vars" / "failure_reasons.yml"
    try:
        return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("_fr_catalog") or {}
    except (OSError, ValueError):
        return {}


def observe(summary, body_path, calls, sink, preserve, control, received=None, fixture=None) -> dict:
    calls = calls or []
    unstable_msgs = [c[len("unstable:"):] for c in calls if isinstance(c, str) and c.startswith("unstable:")]
    sink_known = sink is not None
    sink = sink or []
    posts = [r for r in sink if r.get("method") == "POST"]
    last_status = posts[-1].get("status_sent") if posts else None
    sink_ok = any(isinstance(r.get("status_sent"), int) and 200 <= r["status_sent"] < 300 for r in posts)
    cb = (summary or {}).get("callback") if isinstance(summary, dict) else None
    claimed = cb.get("delivered") if isinstance(cb, dict) and isinstance(cb.get("delivered"), bool) else None
    delivered = None
    # finalizer 밖으로 다시 던진 interruption 은 전송을 끊는다(outer_timeout 류). 수집 단계에서 다시 던진 것(실행 기반 대기 중 취소 등)은
    #   전송을 막지 않는다 — post{always} 자리의 결과 확인이 한 번 보낸다(2026-10-06 CI #27 · #29 의 gather_wait_abort 판정 오류).
    #   rethrown_in 이 없는 옛 control 은 finalizer 로 본다(종전 판정 그대로).
    if control is not None and control.get("rethrown") and control.get("rethrown_in", "finalize") != "gather":
        delivered = False
    elif claimed is not None:
        # 2026-10-05 (F09 · F13): finalizer 가 요약에 남긴 전송 결과 — 수신 기록이 있으면 그 기록과 맞아야 전달로 본다
        delivered = (claimed and sink_ok) if sink_known else claimed
    elif posts or unstable_msgs or summary is not None:
        # 이전 형식(요약에 callback 없음): 수신 기록 + 실패 문구(구 · 신)
        delivered = sink_ok and not any(("Callback 전송 실패" in m) or ("Portal 전송 실패" in m) or ("Portal 전송에 실패했습니다" in m)
                                        for m in unstable_msgs)
    body_sha = None
    if body_path and Path(body_path).is_file():
        body_sha = hashlib.sha256(Path(body_path).read_bytes()).hexdigest()
    obs = {
        "summary_present": summary is not None,
        "layerA": (summary or {}).get("layerA"),
        "layerB": (summary or {}).get("layerB"),
        "source": (summary or {}).get("source"),
        "filled": (summary or {}).get("filled"),
        "lines": (summary or {}).get("lines"),
        "accepted": (summary or {}).get("accepted"),
        "unrecovered": (summary or {}).get("unrecovered"),
        "damage": (summary or {}).get("damage"),
        "recovery_limited": (summary or {}).get("recovery_limited"),
        "outcome": (summary or {}).get("outcome"),
        "limit_reason": (summary or {}).get("limit_reason"),
        "gather_run": (summary or {}).get("gather_run") if isinstance(summary, dict) else None,
        "warnings": (summary or {}).get("warnings") if isinstance(summary, dict) else None,
        "callback": cb if isinstance(cb, dict) else None,
        "by_origin": None,
        "delivered": delivered,
        "unstable_msgs": unstable_msgs,
        "calls": calls,
        "sink_posts": len(posts),
        "sink_event_uuids": [r.get("eventUuid") for r in posts],
        "sink_last_status": last_status,
        "sink_last_ok": posts[-1].get("ok") if posts else None,
        "sink_body_sha256": posts[-1].get("body_sha256") if posts else None,
        "body_sha256": body_sha,
        "preserve": preserve or {},
        "control": control or {},
        "infra": (summary or {}).get("infra") if isinstance(summary, dict) else None,
        "finalize": (summary or {}).get("finalize") if isinstance(summary, dict) else None,
        "recovery": (summary or {}).get("recovery") if isinstance(summary, dict) else None,
        "finalize_result": (control or {}).get("finalize_result"),
        "received": received,
        "fixture_ips": (fixture or {}).get("ips") if isinstance(fixture, dict) else None,
        "body_envelopes": _body_envelopes(body_path),
    }
    bo = (summary or {}).get("by_origin") if isinstance(summary, dict) else None
    if isinstance(bo, dict):
        obs["by_origin"] = bo
    return obs


def check(expect: dict, obs: dict) -> tuple[list[dict], list[str]]:
    checks: list[dict] = []
    partial: list[str] = []

    def add(name, expected, observed, ok):
        checks.append({"name": name, "expected": expected, "observed": observed, "ok": bool(ok)})

    for key in ("layerA", "layerB", "source", "filled", "recovery_limited", "outcome", "limit_reason"):
        if key in expect:
            if not obs["summary_present"]:
                partial.append(f"{key}: finalize_summary.json 없음")
                continue
            add(key, expect[key], obs[key], obs[key] == expect[key])
    if "gather_run" in expect:
        # 8차 (stub_gather): 수집 실행 기록(gather_run.json → finalize_summary.gather_run) — 실제 run_gather.sh 가 한계에 닿았는가
        run = obs.get("gather_run")
        if not obs["summary_present"] or not isinstance(run, dict):
            partial.append("gather_run: finalize_summary.json 에 gather_run 없음")
        else:
            for k, v in expect["gather_run"].items():
                add(f"gather_run.{k}", v, run.get(k), run.get(k) == v)
            if "limit_sec" in expect["gather_run"]:
                ran = run.get("ran_sec")
                ok = isinstance(ran, int) and ran >= expect["gather_run"]["limit_sec"]
                add("gather_run.ran_sec>=limit_sec", f">={expect['gather_run']['limit_sec']}", ran, ok)
    if "lines_eq_accepted" in expect:
        if not obs["summary_present"]:
            partial.append("lines_eq_accepted: finalize_summary.json 없음")
        else:
            eq = obs["lines"] is not None and obs["lines"] == obs["accepted"]
            add("lines_eq_accepted", expect["lines_eq_accepted"], eq, eq == expect["lines_eq_accepted"])
    if "lines_count" in expect:
        if not obs["summary_present"]:
            partial.append("lines_count: finalize_summary.json 없음")
        else:
            add("lines_count", expect["lines_count"], obs["lines"], obs["lines"] == expect["lines_count"])
    if "unrecovered_count" in expect:
        if not obs["summary_present"]:
            partial.append("unrecovered_count: finalize_summary.json 없음")
        else:
            n = len(obs["unrecovered"] or [])
            add("unrecovered_count", expect["unrecovered_count"], n, n == expect["unrecovered_count"])
    if "damage_contains" in expect:
        dmg = " | ".join(obs["damage"] or []) if obs["summary_present"] else ""
        for needle in expect["damage_contains"]:
            add(f"damage_contains:{needle}", True, needle in dmg, needle in dmg)
    if "by_origin" in expect:
        if obs["by_origin"] is None:
            partial.append("by_origin: finalize_summary.json 에 by_origin 없음")
        else:
            for k, v in expect["by_origin"].items():
                add(f"by_origin.{k}", v, obs["by_origin"].get(k), obs["by_origin"].get(k) == v)
    if "preserve" in expect:
        pres = obs["preserve"] or {}
        if not pres:
            partial.append("preserve: preserve_state.json 없음")
        else:
            for k, v in expect["preserve"].items():
                got = pres.get(k)
                add(f"preserve.{k}", v, got, got == v)
    if "unstable_count" in expect:
        add("unstable_count", expect["unstable_count"], len(obs["unstable_msgs"]), len(obs["unstable_msgs"]) == expect["unstable_count"])
    if "unstable_contains" in expect:
        joined = " || ".join(obs["unstable_msgs"])
        for needle in expect["unstable_contains"]:
            add(f"unstable_contains:{needle}", True, needle in joined, needle in joined)
    if "warnings_include" in expect:
        # 2026-10-05 (F13): 경고는 문장이 아니라 finalize_summary.json 의 warnings 코드로 판정한다
        if not obs["summary_present"]:
            partial.append("warnings_include: finalize_summary.json 없음")
        elif obs["warnings"] is None:
            partial.append("warnings_include: finalize_summary.json 에 warnings 없음(이전 형식)")
        else:
            for code in expect["warnings_include"]:
                add(f"warnings_include:{code}", True, code in obs["warnings"], code in obs["warnings"])
    if "warnings_empty" in expect:
        if not obs["summary_present"] or obs["warnings"] is None:
            partial.append("warnings_empty: finalize_summary.json 의 warnings 없음")
        else:
            add("warnings_empty", expect["warnings_empty"], obs["warnings"] == [], (obs["warnings"] == []) == expect["warnings_empty"])
    if "delivered" in expect:
        if obs["delivered"] is None:
            partial.append("delivered: 관측 없음(sink 기록·호출 기록 모두 없음)")
        else:
            add("delivered", expect["delivered"], obs["delivered"], obs["delivered"] == expect["delivered"])
    if "sink_posts_min" in expect:
        if not obs["control"].get("sink_reachable", True):
            partial.append("sink_posts_min: controller 에서 sink 에 닿지 못함")
        else:
            add("sink_posts_min", f">={expect['sink_posts_min']}", obs["sink_posts"], obs["sink_posts"] >= expect["sink_posts_min"])
    if "sink_posts_eq" in expect:
        # 10차 R1: 재진입해도 확인된 전송을 다시 보내지 않는다 — 정확히 몇 번 받았는가
        add("sink_posts_eq", expect["sink_posts_eq"], obs["sink_posts"], obs["sink_posts"] == expect["sink_posts_eq"])
    if "summary_present" in expect:
        add("summary_present", expect["summary_present"], obs["summary_present"], obs["summary_present"] == expect["summary_present"])
    if "finalize" in expect:
        fz = obs.get("finalize")
        if not obs["summary_present"] or not isinstance(fz, dict):
            partial.append("finalize: finalize_summary.json 에 finalize 없음")
        else:
            for k, v in expect["finalize"].items():
                if k.endswith("_min"):
                    key = k[:-4]
                    got = fz.get(key)
                    add(f"finalize.{key}>={v}", f">={v}", got, isinstance(got, (int, float)) and got >= v)
                else:
                    add(f"finalize.{k}", v, fz.get(k), fz.get(k) == v)
    if "recovery" in expect:
        # C1 (2026-10-10): 회수 매체 선택 근거(finalize_summary.recovery) — 마지막 보존 전달 표식 · 빠른 길 · 고른 매체 · 후보마다 결과가 있는 대상 수
        rc = obs.get("recovery")
        if not obs["summary_present"] or not isinstance(rc, dict):
            partial.append("recovery: finalize_summary.json 에 recovery 없음")
        else:
            for k, v in expect["recovery"].items():
                if k in ("stash_real", "archive_real", "stash_recovered", "archive_looked_up"):
                    medium, field = k.split("_", 1)
                    field = {"real": "real", "recovered": "recovered", "looked_up": "looked_up"}[field]
                    got = (rc.get(medium) or {}).get(field)
                else:
                    got = rc.get(k)
                add(f"recovery.{k}", v, got, got == v)
    if "finalize_result" in expect:
        fr = obs.get("finalize_result")
        if not isinstance(fr, dict):
            partial.append("finalize_result: harness_control.json 에 결과 확인 반환값 없음")
        else:
            for k, v in expect["finalize_result"].items():
                add(f"finalize_result.{k}", v, fr.get(k), fr.get(k) == v)
    if "sink_posts_max" in expect:
        add("sink_posts_max", f"<={expect['sink_posts_max']}", obs["sink_posts"], obs["sink_posts"] <= expect["sink_posts_max"])
    if "sink_last_status" in expect:
        if not obs["control"].get("sink_reachable", True) or (obs["sink_posts"] == 0 and obs["control"].get("sink_reachable") is None):
            partial.append("sink_last_status: sink 미도달 또는 수신 기록 없음")
        else:
            add("sink_last_status", expect["sink_last_status"], obs["sink_last_status"], obs["sink_last_status"] == expect["sink_last_status"])
    if expect.get("body_sha_matches_sink"):
        ok = obs["body_sha256"] is not None and obs["body_sha256"] == obs["sink_body_sha256"]
        if obs["body_sha256"] is None or obs["sink_body_sha256"] is None:
            partial.append("body_sha_matches_sink: body 또는 sink 기록 없음")
        else:
            add("body_sha_matches_sink", True, ok, ok)
    if "rethrown" in expect:
        got = obs["control"].get("rethrown")
        if got is None:
            partial.append("rethrown: harness_control.json 에 관측 없음")
        else:
            add("rethrown", expect["rethrown"], got, got == expect["rethrown"])
    if "gather" in expect:
        _check_gather(expect["gather"], obs, add, partial)
    if "infra" in expect:
        _check_infra(expect["infra"], obs, add, partial)
    if "body_reasons" in expect:
        envs = obs["body_envelopes"]
        cat = _catalog()
        if envs is None:
            partial.append("body_reasons: callback_body.json 없음")
        elif not cat:
            partial.append("body_reasons: 실패 문장 정본을 읽지 못함(PyYAML)")
        else:
            for key, want in expect["body_reasons"].items():
                sentence = (cat.get(key) or {}).get("default")
                got = sum(1 for e in envs if isinstance(e, dict) and (e.get("diagnosis") or {}).get("failure_reason") == sentence)
                add(f"body_reasons.{key}", want, got, sentence is not None and got == want)
    if "body_outcome" in expect:
        # 2026-10-10 (FL-F12): Layer A 가 합성한 envelope 의 diagnosis.details.outcome — 보존이 어떤 종료 상태로 돌았는지 Portal 본문에서 본다
        envs = obs["body_envelopes"]
        if envs is None:
            partial.append("body_outcome: callback_body.json 없음")
        else:
            synth = [e for e in envs if isinstance(e, dict) and isinstance((e.get("diagnosis") or {}).get("details"), dict)
                     and e["diagnosis"]["details"].get("finalizer") == "layer_a"]
            got = sorted({str(e["diagnosis"]["details"].get("outcome")) for e in synth})
            add("body_outcome", [expect["body_outcome"]], got, bool(synth) and got == [expect["body_outcome"]])
    if "calls_include" in expect:
        joined = "\n".join(c for c in obs["calls"] if isinstance(c, str))
        for needle in expect["calls_include"]:
            add(f"calls_include:{needle}", True, needle in joined, needle in joined)
    if "calls_count" in expect:
        for needle, want in expect["calls_count"].items():
            got = sum(1 for c in obs["calls"] if isinstance(c, str) and c.startswith(needle))
            add(f"calls_count:{needle}", want, got, got == want)
    return checks, partial


def isolation_checks(obs: dict, event_uuid: str | None) -> list[dict]:
    """2026-10-08 — 동시 빌드 격리: 수신 기록에 다른 요청이 섞이지 않았는가, readTrusted 가 고정 후보 밖을 읽지 않았는가."""
    checks = []
    if event_uuid:
        foreign = [u for u in obs.get("sink_event_uuids") or [] if u != event_uuid]
        checks.append({"name": "sink_isolation", "expected": f"모든 POST eventUuid == {event_uuid}", "observed": foreign, "ok": not foreign})
    unpinned = [c for c in obs.get("calls") or [] if isinstance(c, str) and c.startswith("readTrusted:unpinned:")]
    checks.append({"name": "trusted_pinned", "expected": "readTrusted 는 고정 후보 사본만", "observed": unpinned, "ok": not unpinned})
    return checks


def _check_gather(exp: dict, obs: dict, add, partial) -> None:
    """9차 gather_stage — 시도마다 받은 대상 · 시도 판정 · 누적 한계 · 같은 Runner 고정."""
    ips = obs["fixture_ips"] or []
    if "received" in exp:
        rec = obs["received"]
        if rec is None or not ips:
            partial.append("gather.received: gather_received.jsonl 또는 fixture_state.json 없음")
        else:
            want = [[ips[i - 1] for i in group] for group in exp["received"]]
            got = [r.get("hosts") for r in rec if isinstance(r, dict)]
            add("gather.received", want, got, got == want)
    run = obs.get("gather_run")
    atts = run.get("attempts") if isinstance(run, dict) else None
    if "attempt_states" in exp:
        if not isinstance(atts, list):
            partial.append("gather.attempt_states: finalize_summary.gather_run.attempts 없음")
        else:
            got = [a.get("state") for a in atts]
            add("gather.attempt_states", exp["attempt_states"], got, got == exp["attempt_states"])
    if exp.get("limit_chain"):
        if not isinstance(atts, list) or not atts:
            partial.append("gather.limit_chain: 시도 기록 없음")
        else:
            gmax = run.get("gather_max_sec")
            used = 0
            chain = []
            ok = isinstance(gmax, int)
            for a in atts:
                expected_limit = max(0, gmax - used) if isinstance(gmax, int) else None
                chain.append((a.get("limit_sec"), expected_limit, a.get("exec_sec")))
                ok = ok and a.get("limit_sec") == expected_limit
                used += int(a.get("exec_sec") or 0)
            add("gather.limit_chain", "limit_sec == gather_max - 앞 시도 실행 시간 합", chain, ok)
    if "pinned" in exp:
        targets = [c.split(":")[1] for c in obs["calls"] if isinstance(c, str) and c.startswith("node:") and not c.startswith("node:built-in")]
        ok = len(targets) >= 2 and targets[0] == "harness-runner-label" and all(t == targets[1] for t in targets[1:]) and targets[1] != targets[0]
        add("gather.pinned", exp["pinned"], targets, ok == exp["pinned"])
    if "outcome" in exp:
        got = (obs["control"].get("gather") or {}).get("outcome")
        add("gather.outcome", exp["outcome"], got, got == exp["outcome"])
    if "addon_commits" in exp:
        # 10차 R4: 시도마다 가짜 ansible 이 받은 Add-on commit — 앞 시도의 결정(commit)을 재사용했는가(ref 가 바뀌어도)
        rec = obs["received"]
        commits = ((obs["control"].get("gather") or {}).get("addon") or {}).get("commits") or {}
        if rec is None or not commits:
            partial.append("gather.addon_commits: gather_received.jsonl 또는 시험 Add-on 정보 없음")
        else:
            want = [commits.get(x) for x in exp["addon_commits"]]
            got = [r.get("addon_commit") for r in rec if isinstance(r, dict)]
            add("gather.addon_commits", exp["addon_commits"], got, got == want)
    if "node_calls" in exp:
        # 10차: 수집 단계가 실행 기반(Runner)을 몇 번 요청했는가 — 보존 뒤 끊김에서 다시 시도하지 않았는지 · 보존만 다시 했는지
        got = (obs["control"].get("gather") or {}).get("node_calls")
        add("gather.node_calls", exp["node_calls"], got, got == exp["node_calls"])
    if "addon_none" in exp:
        rec = obs["received"]
        if rec is None:
            partial.append("gather.addon_none: gather_received.jsonl 없음")
        else:
            got = [bool(r.get("addon_dir")) for r in rec if isinstance(r, dict)]
            add("gather.addon_none", exp["addon_none"], got, (not any(got)) == exp["addon_none"])


def _check_infra(exp: dict, obs: dict, add, partial) -> None:
    """9차 — 실행 기반 대기 기록(finalize_summary.infra): 만료 여부 · 대기 구간(사유 · 결과 · 최소 초) · 합이 한도를 넘지 않음."""
    infra = obs["infra"]
    if not isinstance(infra, dict):
        partial.append("infra: finalize_summary.json 에 infra 없음")
        return
    if "expired" in exp:
        add("infra.expired", exp["expired"], infra.get("expired"), infra.get("expired") == exp["expired"])
    eps = infra.get("episodes") or []
    for want in exp.get("episodes", []):
        hit = [e for e in eps if want["reason_contains"] in str(e.get("reason")) and (want.get("result") is None or e.get("result") == want["result"])
               and int(e.get("sec") or 0) >= int(want.get("min_sec", 0))]
        add(f"infra.episode:{want['reason_contains']}:{want.get('result')}>={want.get('min_sec', 0)}s", True,
            [(e.get("reason"), e.get("result"), e.get("sec")) for e in eps], bool(hit))
    if exp.get("within_budget"):
        used, budget = infra.get("used_sec"), infra.get("budget_sec")
        ok = isinstance(used, int) and isinstance(budget, int) and used <= budget + 15
        add("infra.within_budget", "used_sec <= budget_sec(+15s 판정 간격)", (used, budget), ok)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenarios", required=True)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--summary")
    ap.add_argument("--body")
    ap.add_argument("--calls")
    ap.add_argument("--sink")
    ap.add_argument("--preserve")
    ap.add_argument("--control")
    ap.add_argument("--meta", help="harness_functions_meta.json (functions_sha256 · source)")
    ap.add_argument("--received", help="gather_received.jsonl (9차 gather_stage)")
    ap.add_argument("--fixture", help="fixture_state.json (접수 대상 순서)")
    ap.add_argument("--event-uuid", help="이 빌드가 보낸 요청의 eventUuid — 수신 기록에 다른 값이 있으면 FAIL (2026-10-08 동시 빌드 격리)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        scenarios = json.loads(Path(a.scenarios).read_text(encoding="utf-8"))["scenarios"]
    except (OSError, ValueError, KeyError) as e:
        sys.stderr.write(f"[verdict] scenarios.json 읽기 실패: {e}\n")
        return EXIT_TOOL
    if a.scenario not in scenarios:
        sys.stderr.write(f"[verdict] unknown scenario {a.scenario}\n")
        return EXIT_TOOL
    expect = scenarios[a.scenario].get("expect", {})
    summary = _load_json(a.summary)
    calls = _load_json(a.calls)
    sink = _load_jsonl(a.sink)
    preserve = _load_json(a.preserve)
    control = _load_json(a.control)
    meta = _load_json(a.meta)
    obs = observe(summary, a.body, calls, sink, preserve, control, _load_jsonl(a.received), _load_json(a.fixture))
    checks, partial = check(expect, obs)
    if any(k != "note" for k in expect):          # 기대값이 있는 시나리오만 — sink_hold(note 뿐)는 main Job 의 POST 를 받는 보조 시나리오
        checks += isolation_checks(obs, a.event_uuid)
    failed = [c for c in checks if not c["ok"]]
    if failed:
        verdict = "FAIL"
    elif partial:
        verdict = "PARTIAL"
    elif not checks and not partial:
        verdict = "INFO"   # sink_hold 처럼 기대값이 없는 보조 시나리오
    else:
        verdict = "PASS"
    result = {"scenario": a.scenario, "verdict": verdict, "checks": checks, "partial": partial,
              "problems": [f"{c['name']}: expected {c['expected']!r} observed {c['observed']!r}" for c in failed],
              "observed": {k: v for k, v in obs.items() if k not in ("calls", "body_envelopes")}, "calls": obs["calls"],
              "meta": meta or {}, "note": expect.get("note", "")}
    _write_lf(Path(a.out), json.dumps(result, ensure_ascii=False, indent=2))
    sys.stdout.write(f"[verdict] {a.scenario}: {verdict} checks={len(checks)} failed={len(failed)} partial={len(partial)}\n")
    for p in result["problems"]:
        sys.stdout.write(f"[verdict]   FAIL {p}\n")
    for p in partial:
        sys.stdout.write(f"[verdict]   PARTIAL {p}\n")
    return {"PASS": EXIT_PASS, "INFO": EXIT_PASS, "FAIL": EXIT_FAIL, "PARTIAL": EXIT_PARTIAL}[verdict]


if __name__ == "__main__":
    sys.exit(main())
