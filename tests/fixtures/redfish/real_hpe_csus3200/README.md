# real_hpe_csus3200

- **출처(origin, rule 21 R2 / rule 96 R1-A)**: 실 HPE Compute Scale-up Server 3200 RMC(멀티노드) 전수 미러. 2026-06 사이트 캡처. MOCK baseline 대체용 실측.
- **vendor**: hpe(csus)
- **manager_layout**: rmc_primary
- **생성**: `tests/integration/capture_mirror_fixture.py` 로 전수 미러를 gather 가 touch 한
  endpoint 만 recording.json 으로 압축 + 모듈 산출 GOLDEN_KEYS snapshot.
- **용도**: `tests/integration/test_real_capture_replay.py` 가 오프라인(네트워크 0)으로 재생해
  redfish_gather.py 파싱/정규화를 **실장비 4대 기준**으로 회귀 검증.
- **주의**: 이건 모듈 산출(GOLDEN_KEYS) golden 이며 schema/baseline_v1/ 최종 envelope 와는
  다른 층이다. 최종 envelope baseline 은 ansible 정규화가 필요(lab).
