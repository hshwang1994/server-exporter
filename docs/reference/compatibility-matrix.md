# 22. 호환성 매트릭스 — 어느 벤더 / 어느 세대가 무엇을 주나

## 누가 읽나

"**내가 호출하면 어떤 섹션을 받게 될까?**" 가 궁금한 사람.

호출자 시스템 개발자가 응답을 미리 예상할 때, 새로 들어온 작업자가 지원 범위를 파악할 때, 다음 cycle 진입자가 GAP 영역을 찾을 때 본다.

9개 벤더 × 여러 세대 × 10 섹션 = 240 칸짜리 표 한 장으로 정리했다.

## 매트릭스를 만든 재료

3가지를 종합해서 만든다.

1. **Adapter YAML** 의 `capabilities.sections_supported` (어떤 섹션을 다룰 수 있다고 선언했나)
2. **Baseline JSON** (실장비 검증 결과) — `schema/baseline_v1/<vendor>_baseline.json`
3. **Web sources** — lab 에 장비가 없어 직접 검증 못한 영역의 vendor 공식 문서 / DMTF 스펙

세 재료가 모두 있는 칸이 가장 신뢰도가 높다 (`OK` 표기). 일부만 있으면 `OK★` / `GAP` / `BLOCK` 으로 갈린다.

## 판정 기호 7개

| 기호 | 무슨 뜻 | 호출자 입장 |
|---|---|---|
| `OK` | 코드 + adapter + baseline 모두 확보 (lab 검증 완료) | 안심하고 사용 |
| `OK★` | 코드 + adapter 는 있고 baseline 은 없음 | 동작 가능성 높음, 첫 사용 시 응답 확인 권장 |
| `FB` | fallback 코드 적용됨 (옛 펌웨어 호환) | 사용 가능, 일부 필드 null 가능 |
| `GAP` | adapter 에서 명시적으로 미지원 선언 | 응답에 `not_supported` 로 옴 |
| `BLOCK` | lab 장비도 없고 spec 도 불명 | 미검증. 새 cycle 에서 추가 필요 |
| `N/A` | 채널 자체가 그 섹션을 안 다룸 | `not_supported` 로 옴 (정상) |
| `?` | adapter 도 없고 spec 도 불명확 | 추가 조사 필요 |

## 매트릭스 — Redfish 채널 (24 row × 10 col)

OS / ESXi 채널은 별도다. Redfish 채널은 OS 로컬 계정을 안 보기 때문에 `users` 섹션이 모든 행에서 `N/A` 로 표시된다.

| vendor | generation | system | hardware | bmc | cpu | memory | storage | network | firmware | users | power |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Dell** | iDRAC 7 | FB | FB | FB | FB | FB | FB | FB | FB | N/A | FB |
| **Dell** | iDRAC 8 | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | N/A | FB |
| **Dell** | iDRAC 9 | OK | OK | OK | OK | OK | OK | OK | OK | N/A | OK |
| **Dell** | iDRAC 10 | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | N/A | OK★ |
| **HPE** | iLO 4 | OK★ | OK★ | OK★ | OK★ | OK★ | FB | OK★ | OK★ | N/A | FB |
| **HPE** | iLO 5 | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | N/A | OK★ |
| **HPE** | iLO 6 | OK | OK | OK | OK | OK | OK | OK | OK | N/A | OK |
| **HPE** | iLO 7 | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | N/A | OK★ |
| **Lenovo** | IMM2 / XCC1 (legacy) | OK★ | OK★ | OK★ | OK★ | OK★ | FB | OK★ | OK★ | N/A | FB |
| **Lenovo** | XCC v2 | OK | OK | OK | OK | OK | OK | OK | OK | N/A | OK |
| **Lenovo** | XCC v3 (OpenBMC) | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | N/A | OK★ |
| **Supermicro** | X9 | BLOCK | BLOCK | BLOCK | BLOCK | BLOCK | GAP | BLOCK | GAP | N/A | GAP |
| **Supermicro** | X10 / X11 | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | N/A | OK★ |
| **Supermicro** | X12 / H12 | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | N/A | OK★ |
| **Supermicro** | X13 / H13 / B13 | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | N/A | OK★ |
| **Supermicro** | X14 / H14 | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | N/A | OK★ |
| **Cisco** | CIMC M4 | OK | OK | OK | OK | OK | OK | OK | OK | N/A | OK |
| **Cisco** | CIMC M5 | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | N/A | OK★ |
| **Cisco** | CIMC M6 / M7 / M8 | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | N/A | OK★ |
| **Cisco** | UCS X-Series (standalone) | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | N/A | OK★ |
| **Huawei** | iBMC (FusionServer V5/V6) | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | N/A | OK★ |
| **Inspur** | iSBMC (NF / TS) | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | N/A | OK★ |
| **Fujitsu** | iRMC (PRIMERGY M5/M6/M7) | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | N/A | OK★ |
| **Quanta** | QCT BMC (OpenBMC) | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | OK★ | N/A | OK★ |

## 칸 분포 — 한눈에

240 칸을 기호별로 모아보면:

| 기호 | 개수 | 비율 | 상태 |
|---|---:|---:|---|
| `OK` (lab 검증 완료) | 36 | 15% | 가장 신뢰 |
| `OK★` (코드는 있고 baseline 만 부재) | 157 | 65% | 보통 동작 |
| `FB` (옛 펌웨어 fallback) | 14 | 6% | 사용 가능 |
| `GAP` (명시 미지원) | 3 | 1% | not_supported 응답 |
| `BLOCK` (미검증) | 6 | 2.5% | 신규 추가 필요 |
| `N/A` (Redfish 가 안 다루는 영역) | 24 | 10% | 정상 |
| **합계** | **240** | **100%** | |

baseline 을 가진 lab tested 벤더 4개 (Dell iDRAC9 / HPE iLO6 / Lenovo XCC v2 / Cisco CIMC M4) 가 36 칸 (각 9 섹션)을 차지한다. Cisco M4 는 partial lab 검증이다 (`docs/reference/live-validation.md` 참조). 나머지는 코드 / 어댑터는 있지만 실장비 검증을 못한 상태.

## lab 에 장비가 없는 영역

| 영역 | 부재 사유 | 보완 |
|---|---|---|
| Dell iDRAC 7 (9 FB) | EOL 펌웨어 | 옛 펌웨어 fallback 코드로 대응 중 |
| Dell iDRAC 8 (power FB) | M-D3 W1 PowerSubsystem fallback 적용 (cycle 2026-05-06) | lab 도입 시 baseline 캡처 |
| HPE iLO 4 (storage/power FB) | M-D3 W2/W3 fallback 적용 (cycle 2026-05-06) | lab 도입 시 baseline 캡처 |
| Lenovo IMM2/XCC1 (storage/power FB) | M-D3 W4/W5 fallback 적용 (cycle 2026-05-06) | lab 도입 시 baseline 캡처 |
| Supermicro X9 (6 BLOCK) | EOL + lab fixture 부재 | lab 도입 cycle 에서 fixture 캡처 필요 |
| Supermicro X9 (3 GAP) | OEM 미지원 generation | adapter capabilities 추가 후보 |
| 신규 4 vendor (Huawei / Inspur / Fujitsu / Quanta) | lab 부재 + vault 미설정 | vendor 공식 docs / DMTF 스펙 기반으로 작성 |
| HPE Superdome Flex | lab 부재 + sub-line | priority=101 어댑터 + web sources 14건 |
| **Huawei iBMC (2026-08-10 정정)** | **어댑터가 선택조차 되지 않던 상태였음** — `firmware_patterns` 가 정규식 자리에 glob(`iBMC*3.*`)으로 작성돼 실제 `FirmwareVersion`(`3.01` / `iBMC 3.01` 등)이 전부 미매치 → `-9999` 실격 → `redfish_generic`(-400) 선택 | 정규식 정정 후 `redfish_huawei_ibmc`(score 80570) 선택 확인. **위 행의 `OK★` 는 여전히 web sources 기반 추정이며, 실장비 확보 시 재검증 대상** (회귀: `tests/unit/test_adapter_huawei_firmware_regex.py`) |
| **Cisco OEM (2026-08-10 실측)** | `tasks/vendors/cisco/{collect,normalize}_oem.yml` 이 **어느 어댑터에서도 참조되지 않아 미실행** (cisco 3 어댑터 모두 `oem_tasks` 키 부재) | 연결 시 `data.bmc.oem_cisco` 신설 → envelope 변경 + `cisco_baseline` 갱신 동반 → **사용자 승인 사항**(rule 92 R1-B / rule 13 R4). 위 Cisco 행의 값은 표준 수집 기준이라 영향 없음 |

## BIOS Current Attributes (`data.bios`) — 근거 수준 (2026-09-15)

`data.bios` 는 섹션이 아니라서 위 표에 칸이 없다. 코드는 Vendor 구분 없이 한 경로로 동작한다 —
대표 ComputerSystem 응답의 `Bios.@odata.id` 로 1회 조회하고 `Attributes` 원본을 담는다.
링크가 없거나 표준 Bios 리소스가 아니면 조회·변환하지 않고 `null` + notice 로 남긴다.
아래 표는 **코드가 그렇게 동작한다**는 뜻이지 해당 세대를 검증했다는 뜻이 아니다.

| Vendor / 계열 | 공식 자료의 표준 Current `Bios.Attributes` | 저장소 실캡처 재생 | 확인하지 못한 것 |
|---|---|---|---|
| Dell iDRAC8 / iDRAC9 | 확인 | PowerEdge R760 5대 (571개) 통과 | 운영 계정 조회 권한, iDRAC8 구형 펌웨어 응답 |
| Dell iDRAC10 | BIOS Registry 상위 URI 까지만 확인 | 없음 | Current 응답, 조회 권한 |
| HPE iLO5 / iLO6 / iLO7 | 확인 | ProLiant DL380 Gen11 (285개, 링크가 소문자·후행 `/`) 통과 | iLO5·iLO7 실응답, BIOS 조회 권한 |
| HPE iLO4 (Gen9) | 표준 형식 아님 (OEM `HpBios`) — 계약 밖 | 없음 | 실응답. 코드는 변환하지 않는다 |
| HPE Compute Scale-up (CSUS 3200 / Superdome Flex) | 대표 System(Partition0) 1개만 조회 | 없음 | 실응답, 다른 Partition |
| Lenovo XCC / XCC2 / XCC3 | 확인 | ThinkSystem SR650 V2 (392개) 통과 | XCC2·XCC3 실응답 |
| Lenovo TSM | 확인 (`/Systems/Self/Bios`) | 없음 | 실응답, 이 저장소의 TSM 수집 지원 여부 |
| Lenovo IMM2 | 확인 불가 | 없음 | 표준 Current 제공 여부 |
| Cisco CIMC 4.1 / 6.0 표준 | 확인 | CIMC 4.1(2g) 장비 1대 (87개, 전부 문자열) 통과 | 다른 모델 |
| Cisco C885A M8 BMC | 확인 (공식 가이드) | 없음 | 실제 payload |
| Cisco UCS X-Series | Current 응답 미확인 | 없음 | 응답 구조 |
| Cisco CIMC 3.1(3) | 표준 형식 아님 (OEM `/BIOS`, `#Cisco_BiosToken`) — 계약 밖 | 없음 | 코드는 변환하지 않는다 |
| Supermicro (Intel X10 / AMD H11 이후) | 확인 | 없음 | 실응답, X9·ARS |
| Huawei (Kunpeng 공식 문서 범위) | 확인 | 없음 | 일부 x86·TaiShan 세대 |
| Inspur (M6) | 확인 | 없음 | M5·G7 |
| Fujitsu (iRMC S5) | 확인 | 없음 | iRMC S4·S6 |
| Quanta QCT | Redfish 지원만 확인 — Current Bios 응답은 공식 자료에서 확인하지 못함 | 없음 | URI, System ID, 응답 구조 |

"공식 자료" 는 Vendor 공식 문서와 DMTF 스키마 조사 결과다. "실캡처 재생" 은 저장소에 보관된 실장비
응답을 오프라인으로 다시 돌린 결과이며 운영 계정으로 새로 수집한 것이 아니다. Vendor 값만 바꿔 같은
표준 응답을 넣는 mock 테스트는 Vendor 독립성 확인용이고 위 표의 근거로 쓰지 않는다.

## 매트릭스를 갱신해야 하는 시점

| 트리거 | 어느 칸이 바뀌나 |
|---|---|
| Adapter 의 `capabilities` 가 바뀜 | 해당 row 의 칸들 |
| 새 vendor / 새 세대 추가 | 새 row 추가 |
| 펌웨어 업그레이드 후 실장비로 검증 | `OK★` → `OK` 격상 |
| Baseline JSON 추가 | 해당 row `OK★` → `OK` |
| `schema/sections.yml` 의 섹션 변경 | column 수정 |

TTL 은 14일. 현재 수동 갱신이다 (자동 측정 도구는 없다).

## 칸을 격상 / 격하하는 절차

- `OK★` → `OK` — 실장비 검증 후 `schema/baseline_v1/<vendor>_baseline.json` 추가
- `GAP` → `FB` — 호환성 fallback 코드 추가 (Additive only — 기존 동작 유지)
- `BLOCK` → `OK★` — 사이트 fixture 캡처 + adapter capabilities 명시
- `?` → `OK★` / `GAP` — 벤더 공식 문서 / DMTF 스펙 확인 후 결정

## 변경 이력

| 시점 | 어떤 변화 | 표에서의 영향 |
|---|---|---|
| 2026-04-30 | power 섹션 `Members[0]` 단일 진입 fix | Lenovo XCC v3 power `?` → `OK★` |
| 2026-05-01 | 신 세대 BMC 7종 + 호환성 fallback 22건 일괄 | iDRAC 7 / 10, iLO 7, XCC v3, X12~14, UCS X-Series — 신규 row |
| 2026-05-01 | 신규 4 vendor 도입 | Huawei / Inspur / Fujitsu / Quanta — 신규 row |
| 2026-05-01 | Lenovo XCC 권한 캐시 fix | XCC v3 auth recovery `BLOCK` → `OK★` |
| 2026-05-06 | 호환성 fallback 9 라인 (Additive only) | 칸 자체는 불변 (기존 path 유지 + 새 fallback path 추가) |
| 2026-05-06 | HPE Superdome Flex 추가 | 신규 row (HPE sub-line) |
| 2026-09-15 | BIOS Current Attributes 보조 수집 추가 (`data.bios`) | 섹션 표는 불변. 근거 수준은 별도 표 |

---

## 더 보고 싶을 때

| 보고 싶은 것 | 파일 |
|---|---|
| Adapter 가 어떻게 선택되나 (점수 계산) | `docs/develop/03-adapter-system.md` |
| 새 벤더 / 새 세대 추가 절차 | `docs/develop/04-add-vendor.md` |
| 실장비 검증 라운드 결과 | `docs/reference/live-validation.md` |
| Vault 관리 / 회전 | `docs/operate/05-vault.md` |
| 출력 envelope 의 `not_supported` 가 어떻게 나오는지 | `docs/contract/03-fields.md` |
