#!/usr/bin/env python3
"""harness_verdict.py — Harness 시나리오의 관측값을 scenarios.json 기대값과 대조해 PASS / FAIL / PARTIAL 을 정한다 (2026-10-04).

입력(모두 Harness 빌드가 만든 파일; 없는 파일은 "관측 없음" 으로 처리)
  --summary   finalize_summary.json   (finalizer 가 archive 한 것을 unarchive 로 회수)
  --body      callback_body.json      (위와 같음 — sha256 을 sink 기록과 대조)
  --calls     harness_calls.json      (wrapper 가 기록한 step 호출 · unstable 메시지)
  --sink      sink/record.jsonl       (callback_sink.py 수신 기록)
  --preserve  preserve_state.json     (sePreserveGatherOutput() 뒤 env 플래그 · 파일 존재)
  --control   harness_control.json    (Harness 자체 관측: rethrown · sink_reachable · functions_sha256 · source)
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


def observe(summary, body_path, calls, sink, preserve, control) -> dict:
    calls = calls or []
    unstable_msgs = [c[len("unstable:"):] for c in calls if isinstance(c, str) and c.startswith("unstable:")]
    sink = sink or []
    posts = [r for r in sink if r.get("method") == "POST"]
    last_status = posts[-1].get("status_sent") if posts else None
    delivered = None
    if control is not None and control.get("rethrown"):
        delivered = False
    elif posts or unstable_msgs or summary is not None:
        delivered = any(isinstance(r.get("status_sent"), int) and 200 <= r["status_sent"] < 300 for r in posts) and \
            not any("Callback 전송 실패" in m for m in unstable_msgs)
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
        "by_origin": None,
        "delivered": delivered,
        "unstable_msgs": unstable_msgs,
        "calls": calls,
        "sink_posts": len(posts),
        "sink_last_status": last_status,
        "sink_last_ok": posts[-1].get("ok") if posts else None,
        "sink_body_sha256": posts[-1].get("body_sha256") if posts else None,
        "body_sha256": body_sha,
        "preserve": preserve or {},
        "control": control or {},
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

    for key in ("layerA", "layerB", "source", "filled", "recovery_limited"):
        if key in expect:
            if not obs["summary_present"]:
                partial.append(f"{key}: finalize_summary.json 없음")
                continue
            add(key, expect[key], obs[key], obs[key] == expect[key])
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
    return checks, partial


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
    obs = observe(summary, a.body, calls, sink, preserve, control)
    checks, partial = check(expect, obs)
    failed = [c for c in checks if not c["ok"]]
    if failed:
        verdict = "FAIL"
    elif partial:
        verdict = "PARTIAL"
    elif not checks and not partial:
        verdict = "INFO"   # sandbox_probe 처럼 기대값이 없는 정보성 시나리오
    else:
        verdict = "PASS"
    result = {"scenario": a.scenario, "verdict": verdict, "checks": checks, "partial": partial,
              "problems": [f"{c['name']}: expected {c['expected']!r} observed {c['observed']!r}" for c in failed],
              "observed": {k: v for k, v in obs.items() if k != "calls"}, "calls": obs["calls"],
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
