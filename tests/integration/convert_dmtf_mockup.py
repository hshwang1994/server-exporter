"""DMTF Redfish 표준 mockup(DSP2043) 디렉터리 트리 → 오프라인 회귀 fixture 변환.

배경:
    본질적 제약은 lab 부재다. 특히 redfish_gather.py 의 **표준
    (vendor-agnostic, OEM 미사용) 추출 경로** 는 오프라인 회귀 커버리지가 없었다 —
    기존 hpe_emulator_* 캡처는 전부 vendor=hpe(Oem.Hpe 경로), baseline 5종도 전부
    벤더 특화. OEM 확장이 전혀 없는 순수 표준 Redfish 서버는 한 번도 오프라인으로
    회귀되지 않았다.

    DMTF 공식 mockup(예: public-rackmount1, "Simple Rack-mounted Server")은
    `@odata.id` 경로별 `index.json` 트리이고 BSD-3-Clause 다. 이 구조는
    test_hpe_emulator_replay 의 recording.json(`get::<path>`) 포맷에 1:1 매핑
    된다 — 엔진의 `_p()`(`/redfish/v1/` prefix + trailing slash 제거)와 동일.

    **mockup != 실장비.** 산출 fixture/golden 은 schema/baseline_v1/ 실측 baseline 으로
    승격하지 않는다. tests/fixtures/redfish/dmtf_* 아래 "DMTF-mockup-derived" 라벨.

설계:
    1. mockup 디렉터리의 모든 index.json 을 읽어 _p(@odata.id) → 응답 맵(full) 구성.
    2. 그 맵을 replayer 로 주입해 **실제** detect_vendor → _collect_all_sections 를
       오프라인 구동. 엔진이 실제로 요청한 path 만 recording.json 으로 기록(lean).
       (404 miss = mockup 에 없는 path. replayer 기본 miss 가 동일 404 를 주므로
        기록 불필요 — 호환성 fallback 경로는 그대로 탄다.)
    3. 모듈 산출을 expected_output.json(golden) 으로 snapshot + README 출처 기록.

    vendor=unknown 이 정상/기대값이다: Manufacturer 가 vendor_aliases 미매치(예:
    "Contoso") → OEM 추출 미진입 → 순수 표준 경로. 이것이 본 fixture 의 존재 이유다.

사용법:
    python tests/integration/convert_dmtf_mockup.py \\
        --mockup-dir <DSP2043 추출 public-rackmount1 경로> \\
        --name dmtf_rackmount1 \\
        --mockup-label public-rackmount1 \\
        --dsp-version 2021.4 \\
        --source-url https://redfish.dmtf.org/redfish/mockups/v1/1819 \\
        --captured 2026-06-08
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import emulator_harness as H  # noqa: E402  (rg import + ansible stub + _p)

REPO = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO / "tests" / "fixtures" / "redfish"


def _load_mockup(mockup_dir: Path) -> dict:
    """mockup 트리의 모든 index.json → {'get::<path>': [200, body, None], ...}.

    key 는 _p(@odata.id) — 엔진이 _get(path) 로 요청하는 path 와 동일. ServiceRoot
    (@odata.id '/redfish/v1/' → _p '')는 'noauth::' + 'get::' 양쪽 등재(엔진은
    ServiceRoot 를 _get_noauth 우선 조회).
    """
    full: dict[str, list] = {}
    files = sorted(mockup_dir.rglob("index.json"))
    skipped = 0
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                body = json.load(fh)
        except (json.JSONDecodeError, OSError):
            skipped += 1
            continue
        if not isinstance(body, dict):
            skipped += 1
            continue
        odata_id = body.get("@odata.id")
        if not isinstance(odata_id, str):
            skipped += 1
            continue
        key = H.rg._p(odata_id)
        full[f"get::{key}"] = [200, body, None]
        if key == "":  # ServiceRoot
            full["noauth::"] = [200, body, None]
    return full, len(files), skipped


def _instrumented_replayer(full: dict):
    """full 맵을 주입하되, 엔진이 실제로 요청해 hit 된 key 만 used 에 누적.

    Returns: (get_impl, noauth_impl, realm_impl, used)
    """
    used: dict[str, list] = {}

    def get_impl(bmc_ip, path, username, password, timeout, verify_ssl):
        rec = full.get(f"get::{path}")
        if rec is None:
            return H._REPLAY_MISS
        used[f"get::{path}"] = rec
        return rec[0], rec[1], rec[2]

    def noauth_impl(bmc_ip, path, timeout, verify_ssl):
        rec = full.get(f"noauth::{path}")
        if rec is None:
            return H._REPLAY_MISS
        used[f"noauth::{path}"] = rec
        return rec[0], rec[1], rec[2]

    def realm_impl(bmc_ip, timeout, verify_ssl):
        # 정적 mockup 에는 401 WWW-Authenticate realm 이 없다 → None.
        return None

    return get_impl, noauth_impl, realm_impl, used


def _write_json(path: Path, obj) -> None:
    # newline='\n': autocrlf 무관 LF 고정 → golden 재생성 시 EOL diff 노이즈 차단.
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="DMTF Redfish mockup → 오프라인 fixture 변환")
    ap.add_argument("--mockup-dir", required=True,
                    help="mockup 루트(= /redfish/v1/ 에 매핑되는 디렉터리, index.json 보유)")
    ap.add_argument("--name", required=True,
                    help="fixture 디렉터리 이름 (예: dmtf_rackmount1)")
    ap.add_argument("--mockup-label", default="",
                    help="DMTF mockup 명 (예: public-rackmount1)")
    ap.add_argument("--dsp-version", default="", help="DSP2043 버전 (예: 2021.4)")
    ap.add_argument("--source-url", default="", help="DMTF dev hub mockup URL")
    ap.add_argument("--captured", default="", help="변환 일자(YYYY-MM-DD) — README 기록용")
    args = ap.parse_args()

    mockup_dir = Path(args.mockup_dir).resolve()
    if not mockup_dir.is_dir():
        print(f"[FAIL] mockup-dir 없음: {mockup_dir}")
        return 2

    full, total_files, skipped = _load_mockup(mockup_dir)
    if "noauth::" not in full:
        print("[FAIL] ServiceRoot(@odata.id '/redfish/v1/') 미발견 — mockup 루트 확인.")
        return 2

    get_impl, noauth_impl, realm_impl, used = _instrumented_replayer(full)
    output = H.run_gather(get_impl, noauth_impl, realm_impl=realm_impl)

    if not used:
        print("[FAIL] recording 이 비어 있음 — 엔진이 아무 path 도 요청 안 함.")
        return 2

    out_dir = FIXTURE_ROOT / args.name
    out_dir.mkdir(parents=True, exist_ok=True)

    _write_json(out_dir / "recording.json", used)
    _write_json(out_dir / "expected_output.json",
                {k: output[k] for k in H.GOLDEN_KEYS})

    label = args.mockup_label or args.name
    readme = f"""# {args.name} — DMTF 표준 mockup 오프라인 fixture

> [WARN] **DMTF-mockup-derived — 실장비 아님 / baseline 아님.** 본 fixture/golden 은
> `schema/baseline_v1/` 실측 baseline 으로 **승격 금지**. DMTF 공식 표준 mockup(가공의
> Manufacturer="Contoso" 등)이라 실 BMC 펌웨어 동작이 아니라 **표준 스키마 준수 응답** 의
> 파싱 회귀만 보장한다.

## 존재 이유 (커버리지 갭)

redfish_gather.py 의 **표준(vendor-agnostic, OEM 미사용) 추출 경로** 는 그동안
오프라인 회귀가 없었다 — hpe_emulator_* 는 전부 vendor=hpe(Oem.Hpe 경로), baseline
5종도 전부 벤더 특화. 본 fixture 는 OEM 확장이 전혀 없는 순수 DMTF 표준 서버를
재생해 **벤더 미매치 → 표준 경로 + graceful degradation(legacy Power, SimpleStorage
fallback 등)** 을 결정적으로 회귀한다. vendor 감지 결과 `{output['vendor']}` 가 그 증거.

## 출처

- source: DMTF Redfish Mockup Bundle (DSP2043{', v' + args.dsp_version if args.dsp_version else ''}) — **BSD-3-Clause**
- mockup: `{label}`
- source URL: {args.source_url or '(미기재)'}
- 미러: https://github.com/DMTF/Redfish-Mockup-Server (public-rackmount1, BSD-3)
- converted: {args.captured or "(미기재 — --captured 로 지정)"}
- vendor(감지): `{output['vendor']}`  (표준 mockup 은 alias 미매치 → unknown 이 기대값)
- status(감지): `{output['status']}`
- collected: {output['collected']}

## 파일

- `recording.json` — redfish_gather.py 가 실제 요청한 GET 별 (path -> 응답) 기록.
  `test_dmtf_mockup_replay.py` 가 오프라인 재생 입력으로 사용.
- `expected_output.json` — 모듈 gather 산출 golden. 회귀 비교 기준.

## 재생성

DSP2043 mockup 트리를 확보한 뒤:

```
python tests/integration/convert_dmtf_mockup.py \\
    --mockup-dir <{label} 경로> --name {args.name} \\
    --mockup-label {label} --source-url {args.source_url or '<URL>'} \\
    --captured <YYYY-MM-DD>
```

redfish_gather.py 의 의도된 파싱 변경으로 golden 이 바뀌면 위 명령으로 재생성한다.
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8", newline="\n")

    print(f"[OK] {out_dir.name}: vendor={output['vendor']} status={output['status']} "
          f"collected={output['collected']} "
          f"recording={len(used)} paths (mockup files={total_files}, skipped={skipped})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
