# dmtf_rackmount1 — DMTF 표준 mockup 오프라인 fixture

> [WARN] **DMTF-mockup-derived — 실장비 아님 / baseline 아님.** rule 21 R1 /
> rule 25 R7-B 에 따라 본 fixture/golden 은 `schema/baseline_v1/` 실측 baseline 으로
> **승격 금지**. DMTF 공식 표준 mockup(가공의 Manufacturer="Contoso" 등)이라
> 실 BMC 펌웨어 동작이 아니라 **표준 스키마 준수 응답** 의 파싱 회귀만 보장한다.

## 존재 이유 (커버리지 갭)

redfish_gather.py 의 **표준(vendor-agnostic, OEM 미사용) 추출 경로** 는 그동안
오프라인 회귀가 없었다 — hpe_emulator_* 는 전부 vendor=hpe(Oem.Hpe 경로), baseline
5종도 전부 벤더 특화. 본 fixture 는 OEM 확장이 전혀 없는 순수 DMTF 표준 서버를
재생해 **벤더 미매치 → 표준 경로 + graceful degradation(legacy Power, SimpleStorage
fallback 등)** 을 결정적으로 회귀한다. vendor 감지 결과 `unknown` 가 그 증거.

## 출처 (rule 96 R1-A / rule 21 R2)

- source: DMTF Redfish Mockup Bundle (DSP2043, v2021.4) — **BSD-3-Clause**
- mockup: `public-rackmount1`
- source URL: https://redfish.dmtf.org/redfish/mockups/v1/1819
- 미러: https://github.com/DMTF/Redfish-Mockup-Server (public-rackmount1, BSD-3)
- converted: 2026-06-08
- vendor(감지): `unknown`  (표준 mockup 은 alias 미매치 → unknown 이 기대값)
- status(감지): `partial`
- collected: ['bmc', 'firmware', 'memory', 'network', 'power', 'processors', 'system']

## 파일

- `recording.json` — redfish_gather.py 가 실제 요청한 GET 별 (path -> 응답) 기록.
  `test_dmtf_mockup_replay.py` 가 오프라인 재생 입력으로 사용.
- `expected_output.json` — 모듈 gather 산출 golden. 회귀 비교 기준.

## 재생성

DSP2043 mockup 트리를 확보한 뒤:

```bash
python tests/integration/convert_dmtf_mockup.py \
    --mockup-dir <public-rackmount1 경로> --name dmtf_rackmount1 \
    --mockup-label public-rackmount1 --source-url https://redfish.dmtf.org/redfish/mockups/v1/1819 \
    --captured <YYYY-MM-DD>
```

redfish_gather.py 의 의도된 파싱 변경으로 golden 이 바뀌면 위 명령으로 재생성한다.
