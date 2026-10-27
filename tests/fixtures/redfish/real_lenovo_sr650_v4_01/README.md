# real_lenovo_sr650_v4_01

- **출처**: 용인 2차 전수 미러 `tests/reference/redfish/mock2/sr650_v4_01.zip`(sha256 `9c4ef49fc9deb5210bde06a2adf89524e4f39affd1c7effc6d47525895285f43`), 실장비 Lenovo ThinkSystem SR650 V4 (XCC3 IHX438R 2.97 20260910, Redfish 1.22.0, UEFI IHE120L, Hyper-Threading Disabled, FC HBA 없음, firmware -Pending 항목 4(version 없음), PSU1 Health Critical).
  수집 2026-10-22(`redfish_full_mirror.py` 2.2.0, 인증 모드 session(미러 `_manifest.json` auth_mode)), 저장소 보관 2026-10-26(main `7c22ca4a`), fixture 생성 2026-10-27(WP1(b), 제품 코드 변경 0 시점).
- **vendor**: lenovo
- **manager_layout**: 없음(기본) / **firmware_inventory_scope**: 없음(기본) — meta.json `{"manager_layout": null}`
- **생성**: `python tests/integration/capture_mirror_fixture.py <extract>/sr650_v4_01 real_lenovo_sr650_v4_01` — gather 가 touch 한 endpoint 만
  recording.json 으로 압축 + 모듈 산출 GOLDEN_KEYS snapshot(expected_output.json). request_budget.json 은 `tests/scripts/gen_request_budget.py`.
- **용도**: `tests/integration/test_real_capture_replay.py`·`test_request_budget.py`·`test_inventory_count_parity.py`·`test_port_classification_invariants.py` 가
  오프라인(네트워크 0)으로 재생해 redfish_gather.py 파싱/정규화를 2차 실측 기준으로 회귀 검증. golden 은 **수정 전(기준선)** 값으로 먼저 고정했고,
  이후 WP 의 의도된 차이만 항목별 근거와 함께 갱신한다(`tests/evidence/2026-10-27-redfish-mock2-impl/`).
- **주의**: 모듈 산출(GOLDEN_KEYS) golden 이며 schema/baseline_v1/ 최종 envelope 와 다른 층. 식별자(BMC IP·호스트명·시리얼·MAC)는 zip 과 같은 범위(2026-10-26 사용자 결정: 치환 없음),
  비밀값(토큰·비밀번호·개인키)은 없다.
