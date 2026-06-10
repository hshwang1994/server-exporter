# HPE CSUS 3200 — Mock-derived Expected Envelope

> **Lab 부재 — fixture-derived expected. baseline 아님.**

이 디렉터리의 `*.json` 은 `tests/fixtures/redfish/hpe_csus_3200/` 합성 fixture 를 통해
`redfish_gather` 모듈을 거친 후의 **예상 envelope** 입니다. **`schema/baseline_v1/` 의
실측 baseline 과 다른 목적** — baseline 은 실측만 두는 보호를 위해 경로 분리.

## 용도

- 호출자 시스템 / 운영자 **reference** — `data.multi_node` 컨테이너 shape 요약 확인 (compact)
- 실제 fixture → run 회귀는 **`tests/unit/test_csus_fixture_replay.py`** (fixture 를 `@odata.id` 로 키잉해 `_collect_multi_node_topology` 재생 + 구조 assert). 본 `mock_v1.json` 은 테스트가 직접 로드하지 않는 요약 reference 다 (`test_hpe_csus_multi_node.py` 는 inline map 사용).
- 실장비 도입 시 `schema/baseline_v1/hpe_csus_3200_baseline.json` 으로 승격 후 본 디렉터리 삭제

## 출처

- fixture 출처: `tests/fixtures/redfish/hpe_csus_3200/README.md` 참조 (sdflexutils + DMTF v1.15 + iLO5 API ref 합성)
- envelope shape: `docs/20_json-schema-fields.md` 9절 (`data.multi_node`)

## 미래 작업

`schema/baseline_v1/hpe_csus_3200_baseline.json` 실측 baseline 추가 시
본 디렉터리는 실측 baseline 으로 교체할 수 있다.
