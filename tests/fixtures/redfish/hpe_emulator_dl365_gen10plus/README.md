# hpe_emulator_dl365_gen10plus — 에뮬레이터 캡처 fixture

> [WARN] **emulator-derived — 실장비 아님.** 본 fixture/golden 은
> `schema/baseline_v1/` 실측 baseline 으로 **승격 금지**.

## 출처

- source: HPE official iLO Redfish Interface Emulator (BSD-3-Clause) v1.7.0
- mockup: `DL365_Gen10Plus`
- captured: 2026-06-08
- manager_fw(감지): `iLO 5 v3.14`
- vendor(감지): `hpe`
- status(감지): `success`
- collected: ['bmc', 'firmware', 'memory', 'network', 'network_adapters', 'power', 'processors', 'storage', 'system']

## 파일

- `recording.json` — redfish_gather.py 의 GET 요청별 (path -> 응답) 기록.
  `test_hpe_emulator_replay.py` 가 오프라인 재생 입력으로 사용.
- `expected_output.json` — 모듈 gather 산출 golden. 회귀 비교 기준.

## 재생성

에뮬레이터를 호스트 443 에 `MOCKUP_FOLDER=DL365_Gen10Plus` 로 띄운 뒤:

```bash
python tests/integration/capture_emulator.py --mockup DL365_Gen10Plus --captured <YYYY-MM-DD>
```

redfish_gather.py 의 의도된 파싱 변경으로 golden 이 바뀌면 위 명령으로 재생성한다.
