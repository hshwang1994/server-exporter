"""HPE iLO 에뮬레이터에서 fixture(recording) + golden(expected_output) 캡처.

용도: 실행 중인 HPE 공식 iLO Redfish 에뮬레이터(BSD-3)를 향해 redfish_gather.py
의 gather 흐름을 1 회 돌려, (1) 모든 GET 요청/응답을 recording.json 으로 기록하고
(2) 모듈 산출을 expected_output.json(golden) 으로 snapshot 한다.

이 산출물은 tests/integration/test_hpe_emulator_replay.py 가 **오프라인**(에뮬레이터
없이)으로 재생해 회귀 검증에 쓴다.

주의: 에뮬레이터 != 실장비. 본 산출물은 절대
schema/baseline_v1/ 실측 baseline 으로 승격하지 않는다. "emulator-derived" 라벨 유지.

사용법:
    # 에뮬레이터를 호스트 443 에 띄운 상태에서:
    python tests/integration/capture_emulator.py --mockup DL380a --ip 127.0.0.1

    # 여러 BMC type 순차 캡처 (각 docker run 후):
    python tests/integration/capture_emulator.py --mockup DL360
    ...

출력: tests/fixtures/redfish/hpe_emulator_<mockup_lower>/
    recording.json        — (path -> 응답) 기록 (replay 입력)
    expected_output.json  — 모듈 gather 산출 golden
    README.md             — 출처
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# 같은 디렉터리의 공용 모듈.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import emulator_harness as H  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO / "tests" / "fixtures" / "redfish"

EMULATOR_VERSION = "1.7.0"
EMULATOR_SOURCE = "HPE official iLO Redfish Interface Emulator (BSD-3-Clause)"


def _manager_fw(output) -> str:
    """golden 산출에서 BMC 펌웨어 식별자 추출 (README 기록용)."""
    bmc = (output.get("data") or {}).get("bmc") or {}
    fw = bmc.get("firmware_version")
    if fw:
        return str(fw)
    pf = output.get("probe_facts") or {}
    return str(pf.get("firmware_hint") or pf.get("manager_type") or "unknown")


def main() -> int:
    ap = argparse.ArgumentParser(description="HPE iLO 에뮬레이터 캡처")
    ap.add_argument("--mockup", required=True,
                    help="에뮬레이터 MOCKUP_FOLDER (예: DL380a, DL360, DL325_Gen10Plus_FC)")
    ap.add_argument("--ip", default="127.0.0.1", help="에뮬레이터 host (기본 127.0.0.1)")
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default="root_password")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--captured", default="", help="캡처 일자(YYYY-MM-DD) — README 기록용")
    args = ap.parse_args()

    get_impl, noauth_impl, recording = H.make_recorder()
    output = H.run_gather(
        get_impl, noauth_impl,
        ip=args.ip, user=args.user, pw=args.password, timeout=args.timeout,
    )

    if output["vendor"] != "hpe":
        print(f"[WARN] vendor 감지 결과가 hpe 가 아님: {output['vendor']!r} "
              f"(에뮬레이터/네트워크 확인 필요)")
    if not recording:
        print("[FAIL] recording 이 비어 있음 — 에뮬레이터에 도달하지 못함.")
        return 2

    out_dir = FIXTURE_ROOT / f"hpe_emulator_{args.mockup.lower()}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # newline="\n": autocrlf / 플랫폼 무관하게 LF 로 기록 → golden 재생성 시 EOL
    # diff 노이즈 차단 (.gitattributes 와 이중 안전).
    (out_dir / "recording.json").write_text(
        json.dumps(recording, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
        newline="\n",
    )
    (out_dir / "expected_output.json").write_text(
        json.dumps({k: output[k] for k in H.GOLDEN_KEYS}, indent=2,
                   ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
        newline="\n",
    )

    fw = _manager_fw(output)
    readme = f"""# hpe_emulator_{args.mockup.lower()} — 에뮬레이터 캡처 fixture

> [WARN] **emulator-derived — 실장비 아님.** 본 fixture/golden 은
> `schema/baseline_v1/` 실측 baseline 으로 **승격 금지**.

## 출처

- source: {EMULATOR_SOURCE} v{EMULATOR_VERSION}
- mockup: `{args.mockup}`
- captured: {args.captured or "(미기재 — capture 시 --captured 로 지정)"}
- manager_fw(감지): `{fw}`
- vendor(감지): `{output['vendor']}`
- status(감지): `{output['status']}`
- collected: {output['collected']}

## 파일

- `recording.json` — redfish_gather.py 의 GET 요청별 (path -> 응답) 기록.
  `test_hpe_emulator_replay.py` 가 오프라인 재생 입력으로 사용.
- `expected_output.json` — 모듈 gather 산출 golden. 회귀 비교 기준.

## 재생성

에뮬레이터를 호스트 443 에 `MOCKUP_FOLDER={args.mockup}` 로 띄운 뒤:

```
python tests/integration/capture_emulator.py --mockup {args.mockup} --captured <YYYY-MM-DD>
```

redfish_gather.py 의 의도된 파싱 변경으로 golden 이 바뀌면 위 명령으로 재생성한다.
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8", newline="\n")

    print(f"[OK] {out_dir.name}: vendor={output['vendor']} status={output['status']} "
          f"collected={output['collected']} fw={fw} "
          f"recording={len(recording)} paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
