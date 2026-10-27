# 01 — 2차 Mock 11대 축약 fixture 출처·생성 (WP1(b), FIX 8/9)

- 날짜: 2026-10-27 · 브랜치 `fix/redfish-mock2-20261027` · **제품 코드 변경 0 시점**(HEAD `5d8bbe21`, `b8985826` 이후 커밋은 test/docs/harness 뿐)에서 생성.
- 목적: `tests/integration/test_real_capture_replay.py` 등 자동 등록 테스트가 2차 실측 11대를 오프라인으로 재생하도록 축약 fixture 를 넣고, golden 을 **수정 전 값(기준선)** 으로 고정한다. 이후 WP 가 바꾸는 값은 항목별 before/after·원천·원인 표로만 갱신한다(FIX 9).

## 1. 원천

| fixture | zip (`tests/reference/redfish/mock2/`) | sha256 | 미러 수집(UTC, `_manifest.json` started→finished) | 인증 | 장비 식별 |
|---|---|---|---|---|---|
| `real_hpe_csus3200_01` | `csus3200_01.zip` | `7b239fa72998…` | 2026-10-22 05:51:00 → 06:13:00 | basic | Compute Scale-up Server 3200 / RMC 1.77.30-20260911_061319 / Redfish 1.19.0 |
| `real_hpe_csus3200_02` | `csus3200_02.zip` | `156d61cc53c4…` | 2026-10-22 05:51:00 → 06:13:20 | basic | 같음 (HThread Disabled, FC 없음) |
| `real_hpe_csus3200_03` | `csus3200_03.zip` | `b1f7c4963075…` | 2026-10-22 06:13:01 → 06:34:34 | basic | 같음 |
| `real_hpe_dl380_gen12_01` | `dl380_gen12_01.zip` | `9dbc6523298f…` | 2026-10-22 06:13:21 → 06:25:36 | session | HPE ProLiant Compute DL380 Gen12 / iLO 7 1.24.00 Aug 01 2026 / Redfish 1.22.1 / U68 v1.82 |
| `real_hpe_dl380_gen12_02` | `dl380_gen12_02.zip` | `4e48f847fdcb…` | 2026-10-22 06:25:37 → 06:35:39 | session | 같음 / U68 v1.90 |
| `real_hpe_dl380_gen12_03` | `dl380_gen12_03.zip` | `575f8392eb02…` | 2026-10-22 06:34:35 → 06:49:45 | session | 같음 / U68 v1.82 / **PowerState Off** |
| `real_hpe_dl380_gen12_04` | `dl380_gen12_04.zip` | `c35fea8e9439…` | 2026-10-22 06:35:40 → 06:47:26 | session | 같음 / U68 v1.82 |
| `real_lenovo_sr650_v4_01` | `sr650_v4_01.zip` | `9c4ef49fc9de…` | 2026-10-22 06:47:27 → 06:56:39 | session | ThinkSystem SR650 V4 / XCC3 IHX438R 2.97 20260910 / Redfish 1.22.0 / UEFI IHE120L |
| `real_lenovo_sr650_v4_02` | `sr650_v4_02.zip` | `cb33624d2967…` | 2026-10-22 06:49:46 → 06:54:13 | session | 같음 (FC QLE2772 ×2) |
| `real_lenovo_sr650_v4_03` | `sr650_v4_03.zip` | `021a4314f1e8…` | 2026-10-22 06:54:14 → 07:03:25 | session | 같음 / UEFI IHE120P (FC QLE2772 ×2) |
| `real_lenovo_sr650_v4_04` | `sr650_v4_04.zip` | `9aaeb9ef4ef5…` | 2026-10-22 06:56:40 → 07:06:18 | session | 같음 |

- sha256 전체 값은 `tests/reference/redfish/mock2/SHA256SUMS`(정본) — 위 표는 앞 12자만 적었다. fixture 마다 README.md 에 전체 값이 있다.
- 미러 도구: `redfish_full_mirror.py` 2.2.0(`_manifest.json.tool_version`). zip 보관: 2026-10-26(main `7c22ca4a`, `MANIFEST.json`).
- 입력 디렉터리: `C:\github\ClovirONE\mock2-audit-20261026\extract\<server>`(2026-10-26 분석 Round 추출본). **zip 과 동일함을 확인**: `_manifest.json`·`_fsmap.json` sha256 일치 11/11, 파일 수 일치(csus3200_01 4068 · csus3200_02 3974 · csus3200_03 3998 · dl380_gen12_01 3551 · 02 3009 · 03 2413 · 04 3575 · sr650_v4_01 4506 · 02 4730 · 03 5684 · 04 4426).
- zip 11개와 `MANIFEST.json`·`SHA256SUMS` 는 변경하지 않았다(FIX 8).

## 2. 생성 절차 (재현)

```bash
# CSUS 3대: RMC 가 primary manager, 펌웨어 인벤토리는 Complex 범위 (1차 real_hpe_csus3200 과 같은 플래그)
python tests/integration/capture_mirror_fixture.py <extract>/csus3200_01 real_hpe_csus3200_01 --layout rmc_primary --firmware-scope complex_only
# DL380 Gen12 4대 · SR650 V4 4대: 플래그 없음
python tests/integration/capture_mirror_fixture.py <extract>/dl380_gen12_01 real_hpe_dl380_gen12_01
# 각 fixture: meta.json(캡처 플래그와 동일 값) · README.md(출처) 수동 → request_budget.json 생성
python tests/scripts/gen_request_budget.py tests/fixtures/redfish/real_hpe_dl380_gen12_01
```

`capture_mirror_fixture.py` 는 gather 가 실제로 요청한 endpoint 만 `recording.json` 에 남기고 모듈 산출(GOLDEN_KEYS: vendor/status/collected/failed_sections/unsupported_sections/data/multi_node/probe_facts/error_count — notices 제외)을 `expected_output.json` 으로 쓴다. `gen_request_budget.py` 는 `test_request_budget._replay_counts` 와 같은 집계(in-process 재생·캐시 뒤 수)로 `baseline_http_calls == http_calls_budget == sum(expected)`, 빈 `path_set_delta` 를 쓴다.

## 3. 생성 결과 (golden = 기준선, 2026-10-27)

| fixture | status | recorded endpoints | 미러 키 | 요청 예산(total/distinct) | controllers/drives | hbas/ports | temps/fans | PSU | firmware | DIMM 슬롯(장착) | PowerState | bios attrs | multi_node | recording |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| csus3200_01 | success | 193 | 2004 | 196/193 | 1/4 | 4/12 | 63/10 | 4 | 13 | 32(32) | On | 있음 | 있음 | 317 KB |
| csus3200_02 | success | 141 | 1960 | 144/141 | 1/4 | 0/4 | 47/10 | 4 | 9 | 16(16) | On | 있음 | 있음 | 218 KB |
| csus3200_03 | success | 177 | 1969 | 180/177 | 1/4 | 4/12 | 47/10 | 4 | 13 | 16(16) | On | 있음 | 있음 | 260 KB |
| dl380_gen12_01 | success | 152 | 1769 | 152/152 | 1/2 | 4/14 | 56/6 | 2 | 25 | 16(16) | On | 있음 | — | 362 KB |
| dl380_gen12_02 | success | 143 | 1498 | 143/143 | 1/4 | 4/12 | 44/6 | 2 | 25 | 8(8) | On | 있음 | — | 333 KB |
| dl380_gen12_03 | success | 80 | 1200 | 80/80 | 0/0 | 0/4 | 42/6 | 2(Absent) | 13 | 32(16) | **Off** | 있음 | — | 206 KB |
| dl380_gen12_04 | success | 143 | 1781 | 143/143 | 1/4 | 4/12 | 54/6 | 2 | 25 | 8(8) | On | 있음 | — | 345 KB |
| sr650_v4_01 | success | 108 | 1897 | 108/108 | 1/4 | 0/4 | 8/6 | 2 | 28 | 2(2) | On | 있음 | — | 241 KB |
| sr650_v4_02 | success | 125 | 2009 | 125/125 | 1/4 | 4/8 | 8/6 | 2 | 30 | 2(2) | On | 있음 | — | 294 KB |
| sr650_v4_03 | success | 159 | 2486 | 159/159 | 1/2 | 4/14 | 22/6 | 2 | 40 | 16(16) | On | 있음 | — | 382 KB |
| sr650_v4_04 | success | 113 | 1857 | 113/113 | 1/6 | 0/4 | 14/6 | 2 | 30 | 8(8) | On | 있음 | — | 256 KB |

- 11/11 `status=success`, `failed_sections=[]`, `error_count=0`, collected 10 section(모듈 층). 값은 `expected_output.json` 에서 센 것이며 수정 전 코드의 산출이다 — 2026-10-26 분석 Round 가 지적한 이슈(Absent 센서 포함, 빈 DIMM 슬롯, PSU `0.00`, -Pending 항목 version 없음 등)가 **그대로 들어 있는 것이 의도**다(기준선).
- 1차 4세트(`real_dell_r740`·`real_hpe_csus3200`·`real_hpe_dl380`·`real_lenovo_sr650`)는 이름·내용을 유지했다(이름 참조 테스트 때문). `tests/fixtures/redfish/README.md` 표의 1차 4행 JSON 수는 실측(4)으로 정정했다.

## 4. 검증

| 검사 | 결과 | 로그 |
|---|---|---|
| 자동 등록 테스트 7종(`test_real_capture_replay` · `test_request_budget` · `test_port_classification_invariants` · `test_inventory_count_parity` · `test_redfish_service_root_fixtures` · `test_redfish_vendor_reselect_c5` · `test_vendor_normalizer_sot`) | **523 passed**, rc=0 | `tier0/pytest_wp1b_registration.log` |
| 디스크·FC 포트 개수 정합(`test_inventory_count_parity.py`, real_* 15세트) | PASS(위 523 에 포함) — 노출 0 장비(csus3200_02 FC, dl380_gen12_03 디스크/FC)의 수집도 0 | 같은 로그 |
| 평문 자격증명(`scripts/ai/verify_no_plaintext_secret.py`, 변경 114건 digest) | **0건** | 본 문서 |
| 새 Manufacturer/Vendor 문자열(`test_vendor_normalizer_sot`) | 추가 alias 없이 PASS | 같은 로그 |

## 5. 식별자·비밀

- 식별자(BMC IP·호스트명·시리얼·MAC·UUID)는 zip 과 같은 범위로 남겼다(2026-10-26 사용자 결정: 치환 없음). 비밀값(세션 토큰·비밀번호·개인키)은 미러 도구가 저장하지 않으며 digest 검사 0건.
- 재생 한계(익명 범위·인증 통과 규칙·timeout 근사 등)는 `tests/redfish-probe/mirror_replay/README.md` 5절과 같다.
