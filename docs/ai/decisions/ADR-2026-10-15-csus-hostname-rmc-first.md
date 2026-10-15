# ADR-2026-10-15 — HPE CSUS 3200 hostname 은 RMC 이름 우선 · Redfish system.hostname/fqdn 계약 정렬

- 상태: Accepted (긴급 승격 production `31f9b804` → 정규 재승격 `28c38c17`, 2026-10-15)
- 일시: 2026-10-15
- 결정 주체: 사용자(hshwang1994) — 정책 결정 · 승격 승인. AI(Claude) — 조사 · 구현 · 검증
- 관련 rule: 12 R1 · R4, 13 R7, 22 R4, 92 R2, 96 R1 · R1-B, 70 R8(rule 본문 — adapter 가 코드에 주는 키 목록)
- 관련 결정: 2026-06-16 hostname 정책(IP 대체 폐지 · BMC 이름 대체) · 2026-09-03 OS/ESXi 전수 검수(`system.hostname` = 첫 라벨, `system.fqdn` = 도메인 있을 때만)

## 1. 컨텍스트 (Why)

사용자 사이트 CSUS 3200 실측: `Systems/Partition0.HostName = svu703327-net7`, `Managers/RMC/NetworkProtocol.HostName = ycgsfaibap01`.
종전 결과는 봉투 `hostname = svu703327-net7`(Partition 우선)이고 `bmc.dns_name` · `bmc.network_hostname` 은 `ycgsfaibap01` 이었다. 코드는 두 자원을 섞지 않았고 각자 받은 값을 냈다.
사용자 결정: **CSUS 장비의 서버 이름은 RMC 이름이다.** 사이트 운영 사실(사용자 확인): CSUS 1대 = RMC 1개 = 파티션 1개 = OS 1개.

조사 중 별도 결함도 찾았다. 2026-09-03 계약(`system.hostname` 첫 라벨, `system.fqdn` 은 도메인 있을 때만)이 OS · ESXi 에만 적용됐다(NEXT_ACTIONS GA-6).
Redfish 는 `system.hostname` 을 내지 않았고, `system.fqdn` 에 System.HostName 원본을 넣었다. 사전은 `system.hostname` 을 must · redfish 포함으로 선언하고 있었다.
`test_field_dictionary_channel_emit.py::test_system_hostname_declared_and_emitted_by_every_channel` 은 이름과 달리 Redfish emit 을 검사하지 않았다.
코드가 내는 `bmc.network_hostname` 은 사전에 항목이 없었다.

## 2. 결정 (What)

1. Redfish `normalize_standard.yml` 이 원천 이름 하나를 고른다. 그 첫 라벨을 `data.system.hostname` 에 넣고, 도메인이 붙어 있을 때만 전체를 `data.system.fqdn` 에 넣는다(없으면 null). trim 하고 비문자열은 없는 값으로 본다. Linux 와 같은 split 규칙이다.
2. 원천 순서는 adapter `vendor_notes.hostname_priority` 값으로 정한다 — vendor 이름 분기 0(rule 12).
   - 키 없음(기본): System.HostName. BMC 이름 대체는 종전처럼 `build_output.yml` 체인이 한다.
   - `bmc_first`: BMC NetworkProtocol 이름(`bmc.network_hostname`) → 없을 때만 System.HostName.
3. `bmc_first` 는 `adapters/redfish/hpe_csus_3200.yml` 에만 둔다(Superdome Flex 제외 — 결정 범위 밖). 시험이 "이 키를 가진 adapter 는 CSUS 하나" 를 고정한다.
4. 공통 builder(`build_output.yml` · `build_failed_output.yml`) · `redfish_gather.py` · baseline 은 바꾸지 않는다.
   `multi_node.partitions[].system.hostname`(파티션 원본)과 `bmc.dns_name` · `bmc.network_hostname`(RMC 원본)은 그대로다.
5. 사전에 `bmc.network_hostname`(nice, redfish)을 추가하고 `hostname` · `system.hostname` · `system.fqdn` · `bmc.dns_name` 설명을 맞춘다.

## 3. 결과 (Impact)

| 장비 | 종전 hostname | 이후 hostname | data.system.fqdn |
|---|---|---|---|
| 사용자 CSUS | `svu703327-net7` | `ycgsfaibap01` | null |
| CSUS node03 (2026-06 캡처) | `m10mesdb11` | `M10MESDB11-RMC` | null |
| CSUS node01 (2026-06 캡처) | `RMC7CA62A413692` (source=bmc) | 같은 값 (source=system) | null |
| Dell R760 (production #296) | `r760-1.gooddi.lab` | `r760-1` | `r760-1.gooddi.lab` |
| HPE iLO6 (production #296) | `test0004.hynix.com` | `test0004` | `test0004.hynix.com` |
| Cisco C220 (production #296) | `C220-FCH2116V1V0` | 같은 값 | null (종전 같은 값) |
| HPE DL380 · Lenovo SR650 | BMC 이름 (source=bmc) | 같은 값 | null |

- 봉투 13필드 · 섹션 · status 판정 변경 0. `data.system` 에 키 1개(`hostname` — 사전에는 이미 선언)가 생기고 `data.system.fqdn` 의 의미가 계약대로 바뀐다.
- CSUS 의 `diagnosis.details.hostname_source` 는 `system` 이다. 최종값이 `data.system.hostname` 에서 올라가기 때문이다. `bmc` 로 표시하려면 공통 builder 에 출처 힌트를 더해야 했다 — 하지 않았다(D2).
- RMC 를 "<서버명>-RMC" 로 지은 사이트(node03 형)는 hostname 이 RMC 이름이 된다(D1 — 결정 1 을 그대로 적용).
- 반영: 2026-10-15 긴급 승격 production `31f9b804`(main `fd7dfd6a`, HBA 수정 `846516e3` 포함). canary production Job #296(Redfish 3대) 기대값 일치 · Portal 200.
  같은 날 정규 재승격 production `28c38c17`(main `2c709fe8` — main Job 매트릭스 #617~#627 · CI #58 COMPLETE_PASS · gate G01~G20 PASS · `CI-Stages: verified`). runtime tree 는 `31f9b804` 와 같다.

## 4. 대안 비교 (Considered)

| 대안 | 기각 이유 |
|---|---|
| CSUS 도 Partition 우선 유지(종전) | 사용자 결정과 반대. CSUS 는 RMC 1 = 파티션 1 = OS 1 이라 RMC 이름이 서버 식별명이다 |
| `build_output.yml` 체인에 vendor/adapter 분기 | 공통 builder 에 장비별 규칙이 들어간다(rule 22 R5 · 12 R1). 실패 봉투 경로까지 고쳐야 한다 |
| `redfish_gather.py` 에서 CSUS 의 System.HostName 을 RMC 이름으로 바꿔 넣기 | 원본(`multi_node.partitions[]`)을 지켜야 한다는 요구 4 와 충돌. 보호 경로 변경 |
| Redfish 계약 정렬 중 `system.hostname` 키만 추가(fqdn 원본 유지) | 사용자가 계약대로 정렬(A)을 골랐다. fqdn 의미가 채널마다 달라진다 |
| Superdome Flex 에도 `bmc_first` | 사용자 결정 범위가 CSUS 3200 이다. 필요하면 adapter 키 한 줄로 확장 |

## 5. 검증

- 시험: `test_gather_identity_render.py`(Redfish 렌더 25건) · `test_hostname_fallback_chain.py`(새 모양 4건) · `test_field_dictionary_channel_emit.py`(Redfish emit · `bmc.network_hostname` 선언) ·
  신규 `tests/integration/test_redfish_hostname_policy_replay.py`(실 CSUS 녹화본 재생 → 실 adapter 점수 선택 → normalize → build_output, 사용자 사례 합성 변형 · RMC 이름 없음 변형 · Dell/HPE/Lenovo 무변화 · 키를 가진 adapter 는 CSUS 하나)
- 전체 회귀(`fd7dfd6a`): unit · e2e · regression 5215 passed · 36 skipped · 7 xfailed · 0 failed / integration(not live) 336 passed · 6 skipped. WSL 3채널 syntax-check 통과.
- 실장비: production Job #296 — checkout `31f9b804`, 접수 3 = 결과 3, Portal 200, Dell R760 · HPE iLO6 · Cisco 기대값 일치, HBA 수 #295 와 같음. **CSUS 실장비는 lab 부재 — 사이트 재수집으로 확인 필요.**
- 정규 재승격: main Job 매트릭스 11건(#617~#627) 기대 결과 · CI #58 SUCCESS(집계 COMPLETE_PASS, E2E 증거 88/88) · 작업 PC promote 재실행 gate G11~G15 · G18~G20 PASS → `28c38c17` · drift-check PROVENANCE ·
  세 원격 일치. canary 는 `docs/reference/live-validation.md` 2026-10-15 정규 재승격 절.
