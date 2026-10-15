# 2026-10-15 — Redfish `storage.hbas` 누락 보완 (FC 판정 · 다중 섀시 · 빈 목록 · 미제공/실패 구분)

> 누가: 사용자 질문 → AI 조사 · 구현. 언제: 2026-10-15. 어디서: `redfish-gather/library/redfish_gather.py` (Redfish 채널 NetworkAdapters 수집).
> 무엇: `storage.hbas[]` 가 조용히 비거나 틀린 값이 들어가는 경로를 표준(DMTF) 근거의 공통 로직으로 막았다. 왜: 사용자 질문
> "HBA Adapter 를 어떻게 가져오나 · 누락은 없나 · Link Status 는 그대로인가 · unknown 은 무엇인가" 를 조사하다 누락 경로가 나왔다.

## 1. 조사에서 나온 누락 · 오값 경로 (수정 전 코드, HEAD `9f331cc8`)

메모리 안에서 실제 수집 함수에 응답을 주입해 재현했다(파일 변경 없음). 녹화본 변형은 `real_dell_r740` 을 바꾼 것이다.

| # | 조건 | 수정 전 결과 |
|---|---|---|
| S2 | FC 포트가 PortProtocol · FibreChannel 블록 없이 링크 기술만 준다(실측 Dell R740 `NetworkPort.ActiveLinkTechnology=FibreChannel`) + 기능(NDF) 컬렉션 404 | HBA 0건 · 오류 0건 · FC 카드 `network.adapters[].mac` = WWNN |
| S3 | 같은 구조 + NDF 컬렉션 500 | HBA 0건 · 오류 1건 |
| S6 | `ComputerSystem.Links.Chassis` 2개 이상, 카드가 둘째 섀시에 있음 | 첫 섀시만 읽음 — 둘째 섀시 HBA 0건 · 오류 0건 |
| S7 | 1순위 `Chassis/{id}/NetworkAdapters` 200 빈 목록 + 카드는 `Systems/{id}/NetworkAdapters` | 누락(2순위는 200 이 아닐 때만 시도) |
| S8 | 카드 본문의 제조사 · 모델 빈 값 + 포트 수 미노출 | 빈 슬롯으로 보고 카드째 제외 |
| — | 기능에 WWPN 이 없고 포트 주소가 8옥텟 | 포트 주소를 wwpn 으로 추측(`_make_fc_hba` Round 1 #22) — Dell 은 WWNN 이 들어간다 |
| — | iDRAC8 형 짝 없는 NDF(Id `<PortId>-1`, PhysicalPortAssignment 없음) | HBA 4건은 정상 · FC 카드 mac = WWNN |
| — | NetworkAdapters 404 · 빈 목록 | `hbas: []` 만 — "HBA 없음" 과 구분할 근거가 envelope 에 없음 |

## 2. 근거 (실측 · 표준)

- DMTF DSP8010 2026.1(`schema/redfish_dmtf_2026.1/`): `Port.LinkNetworkTechnology` = Ethernet/InfiniBand/**FibreChannel**/GenZ/PCIe,
  `NetworkPort.ActiveLinkTechnology` = Ethernet/InfiniBand/**FibreChannel**, `ComputerSystem.Links.Chassis` = "physical containers associated with this resource"(배열),
  `ComputerSystem` 에 NetworkAdapters 없음(표준 위치는 `Chassis.NetworkAdapters`), `NetworkAdapter.Controllers[].Links`(NDF · Ports · NetworkPorts) · `ControllerCapabilities.NetworkDeviceFunctionCount`.
- `real_dell_r740` 녹화본: FC `NetworkPort.AssociatedNetworkAddresses` = `20:00:34:80:0D:6C:2A:4C`(**WWNN**), NDF `FibreChannel.WWPN` = `21:00:…`.
  `real_hpe_dl380`: FC Port `Ethernet.AssociatedMACAddresses` = WWPN. → 포트 주소의 뜻이 장비마다 다르다.
- `real_hpe_csus3200`: FC Port 에 `LinkStatus` 필드 자체가 없다 → `link_status: unknown`(4포트).
- HPE CSUS 3200 백서(EXTERNAL_CONTRACTS 2026-05-12): "An nPartition is a set of … chassis" → 파티션은 섀시 단위로 묶인다.
- 녹화본 10종: `Links.Chassis` 모두 1개 · 200 빈 목록 0 · 목록에 있는데 404 인 NDF 0 · 빈 카드로 제외되는 카드는 CSUS `Rmp`(Controllers 없음) 1개 · FC HBA wwpn 은 모두 NDF 의 명시 `WWPN`.

### 설계 검토에서 폐기한 원안

원안 A(판정 함수 `_classify_port_protocol` 에 링크 기술 FC 신호 추가)를 녹화본 변형으로 재현했다.
NDF 404 에서는 wwpn 에 WWNN 이 들어갔고(4건), iDRAC8 형 짝 없는 NDF 에서는 HBA 가 **8건**으로 중복됐다. 판정 함수는 포트에 붙은 기능마다 다시 불리는데(RD-F15), 짝 없는 NDF 경로가 같은 포트를 따로 낸다.
→ 판정 함수는 그대로 두고 포트 루프에 조건부 규칙을 뒀다(3절 1).

## 3. 변경 (vendor 이름 분기 0 — `verify_vendor_boundary.py` 통과)

1. **링크 기술만 FC 인 포트** — 다음 조건을 모두 만족할 때만 FC 포트로 본다: 분류 결과 없음 · 연결된 NDF 없음 · `link_tech == FibreChannel` · `<PortId>-` 접두의 짝 없는 NDF 없음.
   HBA 는 내고 wwpn 은 null, link 는 `LinkStatus` 정규화(없으면 `unknown`). 어댑터 mac 접기에서 링크 기술 FibreChannel 포트를 뺀다.
2. **WWPN 추측 금지** — `_make_fc_hba` 의 wwpn 은 NDF `WWPN` / `PermanentWWPN` 만. 포트 주소 대체 경로 제거(포트 주소는 `network.ports[].associated_address` 에 남는다).
3. **System 연결 섀시** — `_resolve_system_chassis_uris()`(Links.Chassis[] 순서 · 중복 제거). `_collect_all_sections` 는 이것을 1번만 부른다(System GET 2회 유지).
   나머지 섀시는 `_extra_chassis_adapter_collections()` 가 본다: 다른 System 이 그 섀시를 연결하지 않았다는 것을 끝까지 확인했을 때만(`_chassis_linked_by_other_systems`),
   섀시의 `NetworkAdapters` 링크를 따라가며, 링크가 없으면 조용히 건너뛰고, 연결된 섀시 · 링크된 목록을 못 읽으면 비차단 오류다. 공유 섀시 · 확인 불가는 notice 를 남기고 수집하지 않는다.
   1순위 섀시는 종전 동작 그대로다(4절 잔여 위험).
4. **경로 순서** `_network_adapter_sources()` — 1순위 섀시(조립 경로) → 추가 섀시 → 카드를 하나도 못 얻었을 때만(실패 또는 200 빈 목록) `Systems/{id}/NetworkAdapters`. Systems 목록과 섀시 목록을 섞지 않는다.
5. **중복**(추가 섀시에서 온 것만, 확인된 단위만) — 카드 · 포트 `@odata.id` 중복은 건너뛴다. FC 항목은 null 이 아닌 같은 WWPN 일 때 그 항목만 빼고, 포트의 FC 항목이 모두 그렇게 확인된 중복이면 포트도 뺀다.
   null WWPN · 일부만 겹친 포트는 남긴다. `Id` · 시리얼로 판단하지 않는다.
6. **빈 카드 필터** — `NetworkDeviceFunctionCount == 0` 이고 `Controllers[].Links` 의 기능 · 포트 목록이 비어 있을 때만 이름 없는 카드를 뺀다(최상위 Ports 링크는 근거로 쓰지 않아 `Rmp` 는 그대로 제외).
7. **실패 가시화** — 목록에 있는데 404 인 NDF 멤버를 비차단 오류로 기록. `diagnosis.details.notices`(기존 배열)에 `NetworkAdapters 리소스 404, …미수집` · `NetworkAdapters 목록이 비어 있음, …미확인` ·
   소유 확인 불가 문장. status · sections · `link_status` 값 · envelope 13 필드 · data 키 변경 0.

## 4. 결과가 달라진 곳 (HEAD `9f331cc8` 모듈 vs 수정 모듈 — 같은 프로세스, 같은 녹화본)

비교 대상: 모듈 산출 전체(data 전 필드 · status · collected/failed/unsupported · error_count) + notices + HTTP 요청 다중집합(캐시 hit 제외).

| 대상 | 차이 | 의도 |
|---|---|---|
| `real_dell_r740` · `real_hpe_dl380` · `real_hpe_csus3200` · `real_lenovo_sr650` · HPE 에뮬레이터 5종 | **0** (요청 목록 포함) | — |
| `dmtf_rackmount1`(DMTF 표준 mockup — NetworkAdapters 없음) | notices +1 `NetworkAdapters 리소스 404, 네트워크 카드(FC HBA 포함) 정보 미수집` | 의도 — 미제공 구분 |
| R740 변형: FC NDF 컬렉션 404 | `fc_hbas` 0 → 4 (wwpn · wwnn null, link down) · FC 카드 2장 mac WWNN → null · FC 포트 4개 `port_type` null → FibreChannel | 의도 — S2 해결, 추측 금지 |
| R740 변형: FC NDF 컬렉션 500 | 위와 같음 (오류 2건은 종전과 같다) | 의도 — S3 해결 |
| R740 변형: iDRAC8 형 짝 없는 NDF | FC 카드 2장 mac WWNN → null (HBA 4건 · WWPN 그대로, 중복 0) | 의도 — WWNN 이 mac 으로 들어가던 오값 정정 |

> 섀시가 1개인 녹화본은 바이트 단위로 같다 — 기존에 잡히던 HBA · 카드 · 포트 정보는 유지된다.

## 5. 시험

- 신규: `tests/unit/test_fc_link_technology_hba.py`(11) · `tests/unit/test_network_adapters_multi_chassis.py`(27) · `tests/unit/test_network_adapters_absence_vs_failure.py`(11) ·
  `tests/integration/test_redfish_hba_coverage_replay.py`(11 — 실 녹화본 재생 + 주입 · 합성 섀시, 실제 normalize/build Jinja 렌더) ·
  `test_hba_ib_canonical::test_schema_example_hbas_use_the_canonical_shape` · `test_field_dictionary_channel_emit::test_hba_link_status_is_declared_with_the_canonical_values`.
- 의도 변경 2건: `test_network_adapters_aux_status::test_chassis_success_does_not_try_systems`(1순위 200 은 "카드가 있을 때" 만 2순위 미시도 — 빈 목록은 새 시험) ·
  `test_redfish_misc_robustness::test_fc_hba_port_address_is_not_used_as_wwpn`(종전 Round 1 #22 고정 시험 — 포트 주소를 wwpn 으로 쓰지 않는다).
- 결과: 7절에 기록.

## 6. 실장비 검증과 남은 것

- **실장비 미검증**(시험 통과 ≠ 해결 확정): 다중 섀시 수집 · 소유 판정(합성 자료만) · NDF 를 주지 않는 FC 장비(녹화본 변형만) · FC 링크업 장비(lab 녹화본 FC 는 모두 LinkDown, 에뮬레이터만 LinkUp).
- **잔여 위험**: 1순위 섀시는 소유를 확인하지 않는다(종전 동작) — DPU 같은 다른 ComputerSystem 이 같은 섀시를 연결하는 구조에서 기존 카드가 통째로 빠지는 위험을 피하려는 선택이다.
  BMC 가 카드 목록에서 FC 카드 자체를 빼면 이 채널로는 알 수 없다(OS 채널 교차 확인). 섀시 간 `adapter_id` 가 겹치면 `network.summary` 의 카드 모델 조인이 틀릴 수 있다(HBA 데이터는 영향 없음).
- jenkins-prod 매트릭스 · CI · 승격 결과는 7절.

## 7. 검증 결과

### 7.1 로컬

- 전체 pytest(unit · e2e · regression, Windows): 5,186 passed · 36 skipped · 7 xfailed · 0 failed (21분 13초).
- 통합(`-m "not live"`): Windows 317 passed · 6 skipped / WSL 351 passed · 4 skipped.
- WSL `scripts/ai/ci_gate.sh`(커밋 clone): 정적 · 통합 · 3채널 syntax-check 통과. unit 76 failed 는 수정 전 `9f331cc8` 에서도 시험 ID 가 같은 76건 — WSL 에 pwsh 가 없는 환경 문제(Windows PowerShell 시험 72 · prodgen 주석 제거 4). 수정 후에만 실패 0.
- 정적: vendor boundary · output schema drift · harness consistency · PROJECT_MAP · docs references · 평문 자격증명 · validate_field_dictionary 통과.

### 7.2 jenkins-prod main Job 매트릭스 (main `9aa2f8b5`, checkout 전부 == `9aa2f8b5` · E2E-A2 는 tip 관측)

| 시나리오 | 빌드 | 결과 | 확인 |
|---|---|---|---|
| S1 Linux 3 | #609 | SUCCESS | 74 s |
| S2 혼합 (실호스트 3 + TEST-NET 2) | #606 | SUCCESS | 112 s |
| S3 Linux 11 | #608 | SUCCESS | 139 s |
| S4 Windows 1 | #607 | SUCCESS | 167 s |
| T2 TEST-NET 2 | #610 | SUCCESS | 86 s |
| T5 사용자 중단 (6대) | #611 | ABORTED | 수집 단계 시작 15초 뒤 API stop · 53 s |
| T6 Callback 거부 주소 | #612 | UNSTABLE | `http://127.0.0.1:9` · 114 s |
| E2E-A loc=cj | #613 | UNSTABLE | cj Runner · TEST-NET 2 · 105 s |
| E2E-A2 loc=chj | #614 | FAILURE | fail-closed · 21 s · tip 관측 `9aa2f8b5` 전후 동일(직접 바인딩) |
| E2E-D ESXi 6 | #615 | SUCCESS | 80 s |
| **E2E-E Redfish 7 BMC** (Dell 5 · Cisco 1 · Lenovo 1) | #616 | SUCCESS | 388 s · 표준 계정 |

Redfish 7대 HBA 관련 필드 대조 — main Job **#602**(수정 전 코드, `fed0b9f1`) ↔ **#616**(수정 후, `9aa2f8b5`), 같은 대상 · 같은 입력.
대조 필드: `storage.hbas[]`(adapter_id · port_id · wwpn · wwnn · link_status · link_speed_gbps · port_type) · `network.adapters[]`(id · model · manufacturer · mac · link_status · port_count · firmware_version) ·
`network.ports[]`(adapter_id · port_id · port_type · link_status · associated_address) · `diagnosis.details.notices`(section network_adapters) · `errors[]`(section network) · `status` · `sections`.

| 대상 | 장비 | hbas | adapters | ports | 차이 |
|---|---|---|---|---|---|
| 10.100.15.2 | Cisco TA-UNODE-G1 | 4 → 4 (UCSC-PCIE-CSC-02 FC 기능 4 · link up 3 / down 1 · WWPN 있음) | 2 → 2 | 4 → 4 | **0** |
| 10.100.15.27 · .28 · .31 · .33 | Dell PowerEdge R760 | 0 → 0 | 2 → 2 | 4 → 4 | **0** |
| 10.100.15.34 | Dell PowerEdge R760 | 0 → 0 | 3 → 3 | 6 → 6 | **0** |
| 10.50.11.232 | Lenovo ThinkSystem SR650 V2 | 0 → 0 | 1 → 1 | 4 → 4 | **0** |

→ 실장비 7대 모두 기존에 잡히던 HBA · 카드 · 포트 정보가 그대로다. 이 7대는 모두 섀시 1개 · NDF 정상 노출이라 새 경로(다중 섀시 · NDF 미노출 · 빈 목록)는 실장비에서 실행되지 않았다.

### 7.3 CI · 승격

- CI #57(`9aa2f8b5`, PROMOTE_DRY_RUN=true · E2E 증거 11 · tip 관측): **SUCCESS 57.5분** — Checkout · Toolchain · Gate · Finalize Corpus · Time Limits · Prodgen Build · Prodgen Drift · Prodgen Verify · Harness Driver · Harness(prodtree) · Evidence Aggregate · Prodgen Promote(예행) 12 단계 전부 SUCCESS.
- **production 승격: 미완료 (production `338ed8d3` 그대로)** — 다른 세션이 이 HBA 수정과 CSUS hostname 핫픽스를 합쳐 긴급 승격하겠다던 계획(2026-10-15)은 사용자 지시로 철회돼 실행되지 않았다(핫픽스 `fba865f6` 은 `581700c8` 로 원복 — tree 는 `4a066660` 과 같고 runtime 은 `9aa2f8b5` 와 같다). 정규 승격은 다음 중 하나다. 정규 승격은 둘 중 하나다: (a) 작업 PC `python -m scripts.ai.prodgen promote --sha 9aa2f8b59ca3c4bc0870a78ba73374617f754484 --verify-report <CI #57 prodgen_verify_report.aggregated.json> --e2e-evidence <CI #57 e2e_evidence.json> --ci-stage-results <CI #57 ci_stage_results.json> --netrc <jenkins netrc> --vault-password-file <vault 비밀번호 파일> --push-remote origin,internal` (환경 의존 gate 재실행 — vault 비밀번호 파일 필요), (b) main tip 이 승격할 SHA 와 같을 때 CI 를 PROMOTE_DRY_RUN=false 로 실행(Jenkins 자격 사용). 승격 직후 production Job canary(OS 1~3 + Redfish).
- **2026-10-15 갱신 (CSUS hostname 세션 기록)**: 위 철회 뒤 사용자 승인으로 핫픽스를 다시 적용(`fd7dfd6a`)해 이 HBA 수정과 함께 긴급 승격 production `31f9b804` 에 들어갔다.
  이어 main `2c709fe8` 정규 재승격 — main Job 매트릭스 #617~#627 · CI #58 COMPLETE_PASS · gate G01~G20 PASS → production **`28c38c17`**(`CI-Stages: verified`).
  canary 는 `../../docs/reference/live-validation.md` 2026-10-15 정규 재승격 절.
