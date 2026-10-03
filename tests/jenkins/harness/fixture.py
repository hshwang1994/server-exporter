#!/usr/bin/env python3
"""fixture.py — Harness workspace 준비: corpus case 입력 복사 · 현재 빌드에 맞는 manifest 재생성 · 시나리오별 변형 (2026-10-04).

왜 있나(Astra 3차 §5-3): fixture 의 manifest 를 그대로 쓰면 build.number=101 · 다른 job/request 라 운영 함수의
"manifest 가 이 빌드 것인가" 검사(sePreserveGatherOutput)와 Callback body(loc/eventUuid)가 현재 시험과 어긋난다.
여기서 **현재 Harness 빌드**(job · number · url)와 시험 request(loc · deploymentEnvironmentId · eventUuid · callbackUrl)로
manifest 를 다시 만들고, 시나리오가 요구하는 입력 상태(예: report 손상)는 **운영 함수 호출 전**에 만든다.

사용:
  python3 tests/jenkins/harness/fixture.py --scenarios tests/jenkins/harness/scenarios.json --scenario normal_success \
      --corpus tests/fixtures/finalize_corpus --workspace "$WORKSPACE" --job "$JOB_NAME" --number "$BUILD_NUMBER" --url "$BUILD_URL" \
      --loc git --deployment-env harness --event-uuid "$BUILD_TAG" --callback-url http://10.0.0.5:18080 --out fixture_state.json
출력: fixture_state.json {scenario, case, channel, ips, manifest_path, files_copied, mutations, manifest_json}
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

INPUT_FILES = ("gather_output.json", "gather_checkpoint.jsonl", "gather_progress.jsonl", "gather_rc.txt")


def load_scenarios(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "scenarios" not in data:
        raise SystemExit("scenarios.json: 'scenarios' 키가 없다")
    return data["scenarios"]


def regenerate_manifest(case_manifest: dict, *, job: str, number: str, url: str, loc: str, deployment_env: str,
                        event_uuid: str, callback_url: str) -> dict:
    return {
        "schema": 1,
        "build": {"job": job, "number": str(number), "url": url},
        "channel": case_manifest["channel"],
        "request": {"loc": loc, "deploymentEnvironmentId": deployment_env, "eventUuid": event_uuid, "callbackUrl": callback_url},
        "ips": list(case_manifest["ips"]),
    }


def apply_mutations(workspace: Path, mutations: list[str]) -> list[str]:
    done = []
    for m in mutations:
        if m == "corrupt_report":
            # Layer A 가 만든 report 를 깨뜨린다 — 호출자는 Layer A 를 먼저 돌린 뒤 이 변형을 적용한다 (fixture.py --post-layer-a)
            p = workspace / "gather_finalize_report.json"
            if not p.is_file():
                raise SystemExit("corrupt_report: gather_finalize_report.json 이 없다 — Layer A 를 먼저 돌려야 한다")
            p.write_text('{"accepted": 3, "exit_code": 0, "kept": 3, "fil', encoding="utf-8")   # 잘린 JSON
            done.append(m)
        elif m == "remove_output":
            p = workspace / "gather_output.json"
            if p.exists():
                p.unlink()
            done.append(m)
        elif m == "remove_layer_a_files":
            for name in ("gather_final.jsonl", "gather_finalize_report.json"):
                p = workspace / name
                if p.exists():
                    p.unlink()
            done.append(m)
        else:
            raise SystemExit(f"unknown mutation {m!r}")
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenarios", required=True)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--job", required=True)
    ap.add_argument("--number", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--loc", default="git")
    ap.add_argument("--deployment-env", default="harness")
    ap.add_argument("--event-uuid", default="")
    ap.add_argument("--callback-url", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--post-layer-a", action="store_true", help="Layer A 실행 **뒤** 적용할 변형만 수행(입력 복사·manifest 생성은 건너뜀)")
    a = ap.parse_args(argv)

    scenarios = load_scenarios(Path(a.scenarios))
    if a.scenario not in scenarios:
        raise SystemExit(f"unknown scenario {a.scenario!r}")
    sc = scenarios[a.scenario]
    ws = Path(a.workspace)
    ws.mkdir(parents=True, exist_ok=True)

    if a.post_layer_a:
        done = apply_mutations(ws, sc.get("mutations_after_layer_a", []))
        Path(a.out).write_text(json.dumps({"scenario": a.scenario, "post_layer_a_mutations": done}, ensure_ascii=False, indent=2),
                               encoding="utf-8", newline="\n")
        sys.stdout.write(json.dumps({"post_layer_a_mutations": done}) + "\n")
        return 0

    case_dir = Path(a.corpus) / sc["case"]
    if not case_dir.is_dir():
        raise SystemExit(f"corpus case 없음: {case_dir}")
    case_manifest = json.loads((case_dir / "gather_manifest.json").read_text(encoding="utf-8"))
    copied = []
    for name in INPUT_FILES:
        src = case_dir / name
        if src.is_file():
            shutil.copyfile(src, ws / name)
            copied.append(name)
    # 전 시험의 잔재가 섞이지 않게 Layer A 산출물은 지운다 (시나리오가 만들기 전까지 없어야 한다)
    for name in ("gather_final.jsonl", "gather_finalize_report.json", "callback_body.json", "finalize_summary.json"):
        p = ws / name
        if p.exists():
            p.unlink()
    manifest = regenerate_manifest(case_manifest, job=a.job, number=a.number, url=a.url, loc=a.loc,
                                   deployment_env=a.deployment_env, event_uuid=a.event_uuid, callback_url=a.callback_url)
    manifest_text = json.dumps(manifest, ensure_ascii=False)
    (ws / "gather_manifest.json").write_text(manifest_text + "\n", encoding="utf-8", newline="\n")
    mutations = apply_mutations(ws, sc.get("mutations", []))
    state = {"scenario": a.scenario, "case": sc["case"], "channel": manifest["channel"], "ips": manifest["ips"],
             "manifest_path": str(ws / "gather_manifest.json"), "files_copied": copied, "mutations": mutations,
             "manifest_json": manifest_text, "run_preserve": bool(sc.get("run_preserve", True)),
             "outcome": sc.get("outcome", "completed"), "sink": sc.get("sink", {"status": "200"})}
    Path(a.out).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    sys.stdout.write(json.dumps({"case": sc["case"], "ips": manifest["ips"], "copied": copied, "mutations": mutations}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
