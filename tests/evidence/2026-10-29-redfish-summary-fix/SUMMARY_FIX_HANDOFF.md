# 독립 재검증 핸드오프 — Redfish Summary 정합성 결함 수정 (2026-10-29)

- 작성: AI(Claude) · 2026-10-31. 구현과 측정은 2026-10-29 에 했다. 이 세션은 자기 결과를 PASS 로 확정하지 않는다 — 다른 세션의 독립 재검증을 요청한다.
- main 병합 · production 승격 · 운영 BMC 접속은 하지 않았다. 셋 다 사용자의 별도 승인 대상이다.
- 대상 브랜치 `fix/redfish-mock2-summary-20261028`, 기준 `104bcaf0`(= `fix/redfish-mock2-review-20261028` HEAD — 그 브랜치에는 커밋을 더하지 않았다).
- 입력 — 읽기만 했다(두 감사 폴더 `se-indep-20261027` · `se-indep-20261028` 는 수정 · 삭제하지 않았다).
  - 감사 보고서 `C:\github\ClovirONE\se-indep-20261028\SUMMARY_AUDIT_REPORT.md` — 137,054 B, sha256 `0875e9f473109105748893a929caad2a76a7b6b3562899b8df2f8014b10f2b31`
  - 재검증 결과 `C:\github\ClovirONE\se-indep-20261028\INDEPENDENT_REVERIFY_RESULT.md` — 27,287 B, sha256 `1f7375fde6e8b1aa3c7956827cc4874df3f51c0eb0f601eb9615e1f8deb9cd72`
  - 승인 Plan(저장소 밖, 사용자 승인본). 실측과 다른 Plan 문구는 8절에 적었다.
- 실장비 검증 0건. 근거는 Mock 미러(실장비 캡처본) 재생, 합성 미러, 함수 단위 시험이다.
- 공통 원칙: `null` = 원천이 주지 않음 또는 확정 불가, `0` = 확인한 0, 부분 합은 전체 합으로 쓰지 않는다.

## 1. SA 항목별 결과

감사 분류는 보고서 7절 · 10.2절 표의 표기다. "18대 변화"는 Tier 1(실제 ansible-playbook + HTTPS 미러) 봉투의 차이다.

| ID | 감사 분류 | 처리 | 18대 변화 | 커밋 | 시험 · 합성 |
|---|---|---|---|---|---|
| SA-01 | FAIL · 관측 | 개수는 원천 컬렉션을 끝까지 읽고 나열된 멤버를 모두 읽었을 때만 정수. 목록은 `[]` 유지(사용자 결정) | CSUS 7대 `multi_node.fabrics[].endpoint_count` 0 → null | `a1b6713f` | `tests/unit/test_multi_node_counts_sa01.py` |
| SA-02 | FAIL · 잠재 | `multi_node.summary.resource_block_count` · `fabric_count` — 링크 없음 · 실패면 null | 0 | `a1b6713f` | 같은 파일 · 합성 `syn_csus_nofab` · `syn_csus_nocomp` |
| SA-03 (SA-03f 포함) | CM 정책 미정의 · FAIL 잠재 | 파티션 cpu · memory · storage summary 를 top-level 규칙으로 맞춤(함수는 공유하지 않음). 제조사는 FIX 2 표. 파티션 network summary 는 계산하지 않고 `{groups: []}` 유지 · 문서화 | CSUS 7대 파티션 cpu 그룹 `manufacturer` 'Intel(R) Corporation' → 'Intel' | `d18f5ca3` (storage 는 `ca5e5c54`) | `tests/unit/test_partition_summary_rules_sa03.py` |
| SA-04 | FAIL · 잠재 | 부분 코어 합을 쓰지 않음. `cpu.cores_physical` 은 CPU 목록이 온전하고 모든 CPU 의 코어를 알 때만 합, 아니면 검사를 통과한 `ProcessorSummary.CoreCount`, 그것도 없으면 null. `cpu.sockets` 는 목록이 온전하면 목록 수, 아니면 검사를 통과한 `ProcessorSummary.Count` 또는 null. 미상 CPU 가 있는 그룹은 `total_cores` · `cores_per_socket` null. notice | 0 | `19e3af89` | `tests/unit/test_redfish_summary_null_rules.py`(cpu) · 합성 `syn_v4_partial` |
| SA-05 | FAIL · 잠재 | 부분 DIMM 합을 쓰지 않음. 모듈은 멤버 실패 시 `total_mib` None, NS 는 검사를 통과한 `MemorySummary` 또는 null. notice | 0 | `19e3af89` | 같은 파일(memory) · 합성 `syn_v4_partial` |
| SA-06 | CM 코드 오류 | 설치 PSU 0 → `health_rollup` null. Redfish · ESXi 함께(사용자 결정). PSU 가 있는데 상태를 모두 모르면 'Unknown' 유지 | dl380_gen12_03 'Unknown' → null | `866d28d8` | `tests/unit/test_power_rounding_sa17.py` · `tests/unit/test_esxi_sensors.py` · `tests/unit/test_power_summary_b58_b59.py` |
| SA-07 | CM null 의미 | `storage.summary.grand_total_gb` 는 드라이브 목록 원천의 구조로 판정한다 — 전원 상태는 쓰지 않음(사용자 의견). 원천을 읽고 비었으면 0, 원천 없음 · 실패 · 일부 실패면 null | dl380_gen12_03 0 → null + notice 1건 | `ca5e5c54` | `tests/unit/test_redfish_summary_null_rules.py`(storage) · 합성 `syn_g12_03_on` · `syn_r1csus01_off` |
| SA-08 | CM 벤더 차이 | Summary 그룹 키의 속도 0 → null. 상세 `interfaces[].speed_mbps` 원본 0 은 유지(사용자 결정) | 그룹 키 7개 0 → null | `92d03169` | `tests/unit/test_redfish_summary_null_rules.py` · `tests/unit/test_redfish_xcc3_shape.py` · 합성 `syn_dell_primary` |
| SA-09 | CM 코드 오류 | 일반 NIC · 포트의 Starting · Training(전이 상태) · Enabled · Active · 미인식 값 → unknown + 섹션당 notice 1건. HBA 값 · notice 는 그대로(`_HBA_LINK_DOWN_VALUES` 고정) | 0 | `92d03169` | `tests/unit/test_link_status_sa09.py` · `tests/unit/test_redfish_pure_helpers.py` · 합성 `syn_dell_links` |
| SA-10 | CM 정책 미정의 | `primary_speed_mbps` = 대표(`is_primary`) NIC 의 속도. 0 · null 이면 null(다른 NIC 으로 대체 안 함) | 0 | `92d03169` | `tests/unit/test_redfish_summary_null_rules.py::test_primary_speed_is_the_primary_nic_speed` · 합성 `syn_dell_primary` |
| SA-11 | CM 문서 | storage GiB 내림 유지 + 문서화(사용자 결정). 그룹 키 목록 · `memory.free_mb` · `network.portgroups` 등재 | 0 | `0bc68f71` | (문서) |
| SA-12 | CM 잠재 | Storage 가 가리킨 드라이브에 섀시가 광고한 `Drives` 컬렉션 · `Links.Drives` 를 합집합으로 더함. 중복은 `@odata.id` → SerialNumber 순으로 제거. 광고한 링크만 GET | 출력 0 · 새 GET 14 경로(전부 미러 실응답) | `ca5e5c54` | `tests/integration/test_chassis_drives_union_sa12.py` · `tests/integration/test_sa12_replay_miss_inventory.py` · 합성 `syn_dl380_partial_link` |
| SA-13 | CM 주석 · 시험 설명 · 증거 | 정정만(출력 영향 0) | 0 | `92d03169`(주석) · `9b34e1d7`(시험 설명) · 이 증거 커밋(`01-f01-nic-link-fill.md` 7절 addendum) | — |
| SA-14 | OBS · MOCK | 바꾸지 않음. 같은 MAC 이 두 카드 포트의 첫 주소인 장비(sr650_v4_02 · _04)에서 두 카드 모델이 같아 출력 영향 0. HOLD-a 와 같은 장비 | 0 | — | — |
| SA-15 | CM 문서 | FD: `network.summary.adapter_count` 는 식별 정보 · Controllers 가 없는 관리 카드(CSUS `Rmp`)를 세지 않는다 | 0 | `0bc68f71` | — |
| SA-16 | CM 문서 | FD: `thermal.fans[].reading` 이 Chassis `Sensors` 의 RelatedItem 으로 결합된다는 출처 | 0 | `0bc68f71` | — |
| SA-17 | CM 반올림 | 소비 · min/avg/max · PSU 입출력 측정값은 `_safe_round_int`(half-even, 사용자 결정). 정격(capacity)은 그대로 | 3대 × 3경로 +1 W | `866d28d8` | `tests/unit/test_power_rounding_sa17.py` · `tests/unit/test_csus_mirror_audit_fixes.py` |
| SA-18 | CM 문서 | CF: NIC → 카드 모델 · 제조사 귀속 규칙 | 0 | `0bc68f71` | — |
| SA-19 | FAIL · 잠재 | EnvironmentMetrics `PowerWatts.ReadingRangeMin/Max`(측정 가능 범위)를 min/max 소비전력으로 쓰지 않음 | 0 | `866d28d8` | `tests/unit/test_power_rounding_sa17.py` · `tests/unit/test_power_environment_metrics_f5.py` · 합성 `syn_g12_psub_range` |

- 문서(FD · 03-fields)는 모든 SA 에 대해 `0bc68f71` 에서 고쳤다.
- 감사가 든 S 번호 사례와 3.6 · 3.7 · 부록 A 의 시험 대응은 `audit_case_test_map.md` 에 있다.
- 각 수정을 하나씩 되돌리는 변이 31건이 모두 시험에 걸렸다(`mutation/mutation_results.txt`).

### 1.1 감사 권장안(보고서 12절 정책 결정표)과 다르게 간 것

| ID | 감사 권장 | 이번 선택 | 근거 |
|---|---|---|---|
| SA-01 | (A) 개수 · 목록 모두 null | 개수만 null, 목록 `[]` 유지 | 사용자 결정(2026-10-29) |
| SA-03 | (A) top-level 과 같은 함수 | 같은 규칙을 파티션 사본에 적용(함수 공유 안 함). 제조사 표는 drift 시험으로 NS 표와 대조 | 승인 Plan 1절 |
| SA-08 | 링크 다운 NIC 속도 null(사전 · OS/ESXi 와 통일) | Summary 그룹 키만 null, 상세 원본 0 유지 | 사용자 결정 |
| SA-09 | 통일(DMTF enum 만 up/down, 나머지 unknown + notice) | 일반 NIC · 포트만 그렇게 하고, HBA 는 up/down 정책 유지 | 지시서 SA-09 문단 · 사용자 의견 |
| SA-11 | half-even(세 채널 공통) | 내림 유지 + 문서화 | 사용자 결정 |
| SA-12 | 문서 정합 먼저, 합집합은 실장비 확인 뒤 | 합집합 구현 | 지시서 SA-12 문단("실제 결함으로 확인되면 … 단순 문서 정정만으로 완료 처리하지 않는다") · 승인 Plan 3절. 실장비 확인은 남아 있다(9절) |

## 2. 커밋

`git log --oneline 104bcaf0..HEAD`. 제품 코드 · 시험 · 문서 · 증거 · 하네스를 따로 커밋했다.

| # | SHA | 제목 |
|---|---|---|
| 1 | `a1b6713f` | fix: Redfish 다중 노드 미제공 개수를 null로 |
| 2 | `19e3af89` | fix: CPU·메모리 부분 합을 전체 합으로 쓰지 않음 |
| 3 | `d18f5ca3` | fix: 파티션 summary를 top-level 규칙으로 정렬 |
| 4 | `ca5e5c54` | fix: storage 미관측 null과 섀시 드라이브 합집합 |
| 5 | `92d03169` | fix: 링크 정규화와 NIC summary 규칙 정정 |
| 6 | `866d28d8` | fix: 전력 반올림·범위값 제외·PSU 0 rollup |
| 7 | `9b34e1d7` | test: Summary 정합성 합성·회귀 시험 추가 |
| 8 | `1b125686` | test: golden·baseline·요청 예산 근거 갱신 |
| 9 | `0bc68f71` | docs: Field Dictionary·필드 계약 Summary 규칙 |
| 9a | `b2fd9c0d` | test: 감사 3.7 M3·C2 전부 미상 사례 시험 추가 — Plan 에 없던 커밋 |
| 9b | `543a1794` | test: 전력 summary 종전 사례를 운영 템플릿과 대조 — Plan 에 없던 커밋(감사 부록 A · S14) |
| 10 | `578677a2` | docs: Summary 수정 증거와 재검증 handoff |
| 10a | `92ceb055` | docs: handoff에 구현 차이 6건·정책 질문 추가 — Plan 에 없던 커밋 |
| 11 | `90f9c0eb` | harness: Summary 수정 상태·후속·ADR·카탈로그 갱신 — Tier 0 시험 대상 커밋(7절) |
| 12 · 13 | (이 7절 · 2절을 담은 커밋과 그 뒤 — `git log 104bcaf0..HEAD`) | Tier 0 기록 · 하네스 시험 이력 — 기록만 바꾼다 |

- 제품 동작이 바뀐 파일은 셋이다: `redfish-gather/library/redfish_gather.py` · `redfish-gather/tasks/normalize_standard.yml` · `filter_plugins/power_summary.py`(SA-06, ESXi 공용).
- 제품 코드는 커밋 6(`866d28d8`) 뒤로 바뀌지 않았다. `git diff 866d28d8 HEAD -- redfish-gather filter_plugins callback_plugins common os-gather esxi-gather adapters vault` 는 비어 있다.
- 변경 0(기준 `104bcaf0` 대비): `callback_plugins` · `common/tasks/normalize` · `os-gather` · `esxi-gather` · `adapters` · `vault` · `Jenkinsfile_portal*` · `schema/sections.yml`.
- 커밋 9 는 additive-only 훅이 종전의 틀린 help 문장 삭제를 막아 `ADDITIVE_SKIP_NEW_CYCLE=1` 로 그 훅만 건너뛰었다. `--no-verify` 는 쓰지 않았고 다른 훅은 모두 돌았다.

## 3. 출력 · 계약 변화

### 3.1 Tier 1 봉투 (18대, 기준 `104bcaf0` → HEAD 제품 코드 `866d28d8`)

| SA | 경로(인덱스 생략) | 이전 → 새 | 대상 | 건수 |
|---|---|---|---|---|
| SA-01 | `data.multi_node.fabrics[].endpoint_count` | 0 → null | CSUS 7대 | 7 |
| SA-03 | `data.multi_node.partitions[].cpu.summary.groups[].manufacturer` | 'Intel(R) Corporation' → 'Intel' | CSUS 7대 | 7 |
| SA-17 | `data.power.power_control.power_consumed_watts` · `data.power.summary.consumed_watts` · `data.multi_node.chassis[].power.power_control.power_consumed_watts` | 815 → 816 · 591 → 592 · 945 → 946 | csus3200_02 · r1_HPE_CSUS3200_01 · r1_HPE_CSUS3200_04 | 9 |
| SA-08 | `data.network.summary.groups[].speed_mbps` | 0 → null | r1_DELL_R740_01 2 · r1_Lenovo_SR650_01 2 · sr650_v4_01 · _02 · _04 각 1 | 7 |
| SA-06 | `data.power.summary.health_rollup` | 'Unknown' → null | dl380_gen12_03 | 1 |
| SA-07 | `data.storage.summary.grand_total_gb` | 0 → null | dl380_gen12_03 | 1 |
| SA-07 | `diagnosis.details.notices[2].message` · `.section` | (없음) → `storage` · "드라이브 목록 원천(Storage Drives · 섀시 Drives 등)을 하나도 읽지 못함 — 디스크 0개를 확인할 근거가 없음: summary.grand_total_gb = null" | dl380_gen12_03 | 2 |

- 합 34건. 허용 목록(`tier1/allow.json`, 10항목)으로 전부 설명된다 — 미설명 0, 요청 집합 미설명 0.
- 18대 모두 rc 0 · status success · errors 0 · adapter 같음. 그룹이 합쳐지거나 늘어난 곳은 없다(SA-08 은 키 값만 바뀜).
- 소비전력 원천이 소수인데 값이 그대로인 CSUS 2대는 원천이 600.25 · 1000.5 다(절삭과 half-even 이 같은 값). 정수 원천(903.0 · 867.0)도 그대로다.

### 3.2 요청 변화 (Tier 1 미러 접근 로그)

| label | 새 GET 경로 | 새 고유 경로 수 |
|---|---|---|
| csus3200_01 · _02 · _03, r1_HPE_CSUS3200_03 · _04 | `Chassis/r001u01/Drives` | 각 +1 |
| dl380_gen12_01 · _02 · _04, r1_HPE_DL380_01 | `Chassis/DE00B000` · `Chassis/DE00B000/Drives` | 각 +2 |
| r1_DELL_R740_01 | `Chassis/Enclosure.Internal.0-1:RAID.Slot.6-1` | +1 |
| 나머지 8대(dl380_gen12_03 · r1_HPE_CSUS3200_01 · _02 · Lenovo 5대) | 없음 | 0 |

- r1_HPE_CSUS3200_01 · _02 는 종전 A-10(Storage 드라이브 0건 → 섀시 Drives 폴백)이 이미 `Chassis/r001u01/Drives` 를 요청하고 있었다.
- dl380_gen12_03 은 Storage 멤버가 0이라 `Links.Enclosures` 가 없고, System 섀시 `Chassis/1` 은 `Drives` · `Links.Drives` 를 광고하지 않는다.

### 3.3 golden · baseline · 요청 예산 (커밋 8)

- golden 4세트 12경로 — 대장 `golden_changes.json` 과 정확히 같을 때만 기존 recording 으로 재생성했다(recording 은 바꾸지 않았다).
  - `real_hpe_csus3200` 4 · `real_hpe_csus3200_01` 2 · `real_hpe_csus3200_02` 4 · `real_hpe_csus3200_03` 2.
  - 내용: `endpoint_count` 0 → null(4세트) · 파티션 `manufacturer` → 'Intel'(4세트) · 소비전력 591 → 592 · 815 → 816(각 2경로).
  - 나머지 golden 17세트(real 11 · 에뮬레이터 · DMTF 6)는 바뀌지 않았다.
- baseline `schema/baseline_v1/hpe_csus_3200_baseline.json` — FIX 5 와 같은 방법(csus3200_01 Tier 1 봉투, build `sa-after-866d28d8`)으로 다시 만들었다. 값 변경 2건(`endpoint_count` · 파티션 `manufacturer`), 그 밖은 `baseline_origin` 문장과 meta 시각이다.
- `request_budget.json` 8건. 늘어난 요청은 모두 golden recording 에 없는 경로(replay-miss 404)다.

| fixture | 예산 | 늘어난 경로 |
|---|---|---|
| `real_dell_r740` | 137 → 138 | `Chassis/Enclosure.Internal.0-1:RAID.Slot.6-1` ×1 |
| `real_hpe_dl380` · `real_hpe_dl380_gen12_01` · `_02` · `_04` | 132 → 133 · 153 → 154 · 144 → 145 · 144 → 145 | `Chassis/DE00B000` ×1. 본문이 replay-miss 라 `/Drives` 는 요청하지 않는다 |
| `real_hpe_csus3200_01` · `_02` · `_03` | 182 → 184 · 130 → 132 · 166 → 168 | `Chassis/r001u01/Drives` ×2. pytest 재생은 404 를 캐시하지 않아 top-level · 파티션 storage 가 각각 요청한다(Tier 1 미러는 200 이라 1회) |

### 3.4 JSON 계약

- Top-level 13 필드 · `schema_version` · `failure_stage` / `failure_code` · `status` 값은 그대로다. 키 추가 · 삭제 · 이름 변경은 0이다(shape 변화 0).
- 바뀐 것은 값이 null 로 나오는 조건이다.
  - 새로 null 이 나올 수 있게 된 키(종전에는 미제공 · 실패에도 정수가 나왔다): `multi_node.summary` 개수(`partition_count` · `manager_count` · `chassis_count` · `resource_block_count` · `fabric_count`) · `multi_node.fabrics[].switch_count` · `endpoint_count` · `multi_node.composition.resource_block_count` · `network.summary.adapter_count` · `port_count` · `cpu.summary.groups[].total_cores` · `cores_per_socket` · `storage.summary.grand_total_gb`, 그리고 파티션 `multi_node.partitions[].{cpu,memory,storage}.summary` 의 같은 키.
  - 종전에도 null 이 나오던 키 — null 조건만 넓어졌다: `network.summary.groups[].speed_mbps`(0 도 null) · `primary_speed_mbps`(대표 NIC 기준) · `cpu.sockets` · `cpu.cores_physical`(SA-04) · `memory.total_mb` · `memory.installed_mb` · `memory.summary.grand_total_gb`(SA-05) · `power.summary.health_rollup`(PSU 0, SA-06).
- FD 에 type 칸이 있는 키 가운데 `cpu.sockets` · `cpu.cores_physical` · `memory.total_mb` · `power.summary.health_rollup` · `power.summary.consumed_watts` 는 종전부터 `|null` 이다. FD 기존 항목의 type · channel · enum · priority 는 바꾸지 않았다. null 이 될 수 있다는 점은 FD 머리 메모(2026-10-29) · 관련 항목 help · `docs/contract/03-fields.md` 에 적었다. 새 항목은 2개(`memory.free_mb` · `network.portgroups` — 이미 나가던 키를 사전에 올림)다.
- Portal 같은 소비자가 이 키들의 null 을 처리하는지는 운영 담당자가 확인해야 한다(AI 환경에서 확인 불가).

## 4. 새 GET 경로별 404 출처 분류

판정 규칙(Plan 3절 SA-12): 실행 중의 코드는 404 출처를 알 수 없어 선택 링크의 404 를 "미제공"으로만 다룬다. 검증에서는 출처를 셋으로 나눈다. Mock 에 없는 응답은 검증 한계(MOCK_LIMITATION)로 남기고 정확성의 근거로 쓰지 않는다.

| 경로 | 대상 | Tier 1 미러 실응답 | 기록된 실제 404 | Mock 미포함(replay-miss) |
|---|---|---|---|---|
| `Chassis/r001u01/Drives` | csus3200_01 · _02 · _03 | 200(note `tree`) · 멤버 4, Storage 와 같은 URI → 추가 0 | 없음 | golden `real_hpe_csus3200_01` · `_02` · `_03` recording |
| `Chassis/r001u01/Drives` | r1_HPE_CSUS3200_03 · _04 | 200 · 멤버 2, 같은 URI → 추가 0 | 없음 | 대응 golden 없음 |
| `Chassis/DE00B000` | dl380_gen12_01 · _02 · _04 · r1_HPE_DL380_01 | 200 · `Drives` 광고 | 없음 | golden `real_hpe_dl380_gen12_01` · `_02` · `_04` · `real_hpe_dl380` recording |
| `Chassis/DE00B000/Drives` | 같은 4대 | 200 · 멤버 8, 같은 URI → 추가 0 | 없음 | pytest 는 앞 본문이 replay-miss 라 요청하지 않음 |
| `Chassis/Enclosure.Internal.0-1:RAID.Slot.6-1` | r1_DELL_R740_01 | 200 · `Drives` 광고 없음 · `Links.Drives` 4, 같은 URI → 추가 0. 미러 디렉터리 이름은 ':' 가 '_' 로 바뀌어 있고 `@odata.id` 키로 제공된다 | 없음 | golden `real_dell_r740` recording |
| `Chassis/DE00A000`(dl325 · dl360 · dl380a) · `Chassis/DE042000`(dl365) · `Chassis/DE00B000`(dl380a) — 5항목 | HPE 에뮬레이터 golden 4세트(`hpe_emulator_dl325_gen10plus_fc` · `hpe_emulator_dl360` · `hpe_emulator_dl365_gen10plus` · `hpe_emulator_dl380a`) | 대응 미러 없음(NO_MIRROR) — 실응답 미검증 | 없음 | 그 4세트의 recording |

- 18대 미러와 golden recording 에는 이 경로들의 "기록된 404" 가 없다. 기록된 404 동작은 합성 recording 으로만 확인했다: `tests/integration/test_chassis_drives_union_sa12.py::test_recorded_404_and_replay_miss_give_same_result_but_are_told_apart` · `::test_csus_chassis_drives_404_sources_full_replay`(같은 경로를 `[404, {}, "HTTP 404: Not Found"]` 로 기록한 것과 recording 에서 뺀 것을 구분).
- 대장: `replay_miss_ledger.json`(21사례, SA-12 항목 13 = MIRROR_REAL 8 · NO_MIRROR 5, 종전부터 있던 miss 33경로 6사례). `tests/integration/test_sa12_replay_miss_inventory.py` 가 실제 miss 집합이 대장과 정확히 같은지 본다 — 대장에 없는 새 GET 이 생기면 실패한다.
- Tier 1 새 GET 14 경로는 `tier1/new_get_sources.jsonl` 에서 모두 MIRROR_REAL(note `tree`)이다. Tier 2 재생 seam 은 표식 없는 404 를 돌려주므로 응답 맵 키와 따로 대조했다(`tier2-after/_newget_class.jsonl`, 16행 모두 MIRROR_REAL — r1 CSUS 01 · 02 의 종전 경로 2행 포함).

## 5. 검증 결과 (이 세션의 측정 — 독립 재검증 아님)

| 검사 | 결과 | 산출 |
|---|---|---|
| Tier 1 18대 | 18/18 rc 0 · success · errors 0. 차이 34 = 허용 목록 10항목으로 전부 설명 | `tier1-after/_summary.json` · `tier1/explained.md` · `tier1/diff.md` |
| Tier 1 기준 동치 | `104bcaf0` 재실행 출력 = `2026-10-28-redfish-mock2-review-fix/tier1-A`(차이 0 · 요청 키 같음) | `tier1/base_equiv.md` |
| Tier 1 불변 항목 | 위반 0. HBA 수 · 값 · 링크 notice = 기준, HBA 값 ⊂ {up, down}, `cpu.logical_threads` 0, 전원 Off notice 는 dl380_gen12_03 1건, 남은 NIC unknown = ToManager · NIC6 · NIC4 · CSUS · dl380_gen12_03 | `tier1/invariants.md` |
| 새 GET 출처 | 14 경로 전부 MIRROR_REAL | `tier1/new_get_sources.jsonl` |
| Tier 2 18 모듈 | 18/18 success. golden 15 label 의 GOLDEN_KEYS 차이 0(커밋 8 golden 기준). 2026-10-28 Tier 2 대비 56키 차이 = `aux.storage_inventory` 36 · `endpoint_count` 7 · 파티션 `manufacturer` 7 · 소비전력 6 | `tier2-after/_vs_golden.md` |
| 합성 미러 9건 | **등록 기준 head 7/9 PASS · FAIL 2.** FAIL 2는 기대값의 경로 이름 오기(`data.system.power_state` — 실제는 `data.hardware.power_state`)다. 두 사례의 값 단정은 모두 PASS. 그 경로만 고친 사후 점검은 head 9/9 · base 9/9 결함 재현(사전 등록 PASS 로 세지 않음) | `synthetic/results.md` · `synthetic/results_posthoc.md` · `synthetic/ERRATUM.md` |
| A/B/C 독립 비교 | head PASS 666 · CM 36 · FAIL 0, 두 번 실행 바이트 같음. base(`104bcaf0`) FAIL 24 · CM 36 · PASS 642. FAIL 24 = SA-01 7 · SA-03 7 · SA-17 3 · SA-08 5(대 단위) · SA-07 1 · SA-06 1. CM 36 은 전후 같은 집합 — NIC 원문에 link 가 없어 같은 MAC 포트 값으로 채운 것(F-01 규칙: DL380 3대 16건 down · SR650 V4 20건 up 14 · down 6) | `abc/head.md` · `abc/base.md` |
| 변이 | 31/31 KILLED(1건은 빠진 시험을 더한 뒤) | `mutation/mutation_results.txt` |
| 개수 정합 | 18/18 PASS(디스크 · FC 포트 = 원천). 2026-10-28 `_parity.md` 와 제목 줄만 다르다 | `preservation/parity/_parity.md` |
| 판별기 대조 · 132칸 · 처분 재집계 | 2026-10-28 산출과 sha256 이 같다: `oracle_compare.json`(불일치 69) · `cell_check.json` · `recount.md`(73 = FIXED 43 · DOC_CORRECTED 19 · OBSERVATION_ONLY 11, 병기 HOLD 3) | `preservation/` |
| LinkStatus 값 · CSUS 카드 조건 | `linkstatus_values.md` 2026-10-28 과 같음(미러 · fixture 에 Starting · Training · Enabled · Active 0건). CSUS 7대 PCIe 카드 49개 링크 조건 모두 LinkUp | `preservation/` |
| 새 시험 | 7파일 269 passed + `tests/unit/test_power_summary_b58_b59.py` 22 passed(HEAD `543a1794`, Windows) | — |
| pytest 4묶음 (커밋 8 시점, Windows) | unit 5531 passed · 33 skipped / integration(`-m "not live"`) 540 passed · 6 skipped · 1 deselected / e2e 876 passed · 6 skipped / regression 222 passed · 6 skipped · 5 xfailed — 실패 0 | — |
| pytest 전체 · Tier 0 | 7절 | `tier0/` |

- 보존 목록(Plan 12절): 디스크 · HBA 개수 = 원천, Lenovo XCC3 adapter 선택, F-01 보충 20건(up 14 · down 6), CSUS HBA A안, HBA 값 up/down, `data.cpu.logical_threads` 없음 — 위 표의 불변 항목 · A/B/C CM 36 · 개수 정합으로 확인했다. OS 출력 변화 0, ESXi 는 SA-06(PSU 센서 0 → null) 하나다.
- Tier 2 `*.module.json` 은 모듈 출력이라 normalize 가 만드는 top-level summary · notice 가 없다(파티션 · `multi_node` summary 는 모듈 값이라 들어 있다). SA-04 · 05 · 06 · 07 · 08 · 10 의 top-level summary 값은 Tier 1 봉투 · 합성 미러 · 렌더 시험으로만 확인했다.

## 6. 재현 명령 (저장소 루트 · Windows Git Bash)

```bash
P=tests/evidence/2026-10-28-redfish-mock2-review-fix
D=tests/evidence/2026-10-29-redfish-summary-fix
# 6.1 미러 준비 · Tier 1 · Tier 2 실행은 $P/REVIEW_FIX_HANDOFF.md 4.1 · 4.2 · 4.4 와 같다(같은 미러 · 18 label · 옵션). --build-id 와 출력 루트만 새로 정한다
# 6.2 Tier 1 대조 — 기준은 $P/tier1-A(104bcaf0 재실행과 내용 차이 0)
python -I -X utf8 -B $P/tools/tier1_explained.py $P/tier1-A <새 출력 루트> --allow $D/tier1/allow.json --out-md <md> --out-json <json>   # 설명 34 · 미설명 0
python -I -X utf8 -B $P/tools/tier1_invariants.py <새 출력 루트> --ref $P/tier1-A --out <md>                                            # 위반 0
python -I -X utf8 -B $D/tools/classify_new_gets.py $P/tier1-A <새 출력 루트> | grep -v '^classes:' > <jsonl>                         # 마지막 classes: 줄이 집계(MIRROR_REAL 14)
# 6.3 Tier 2 대조
python -I -X utf8 -B $P/tools/tier2_vs_golden.py <새 tier2 출력> --prev $P/tier2-A --out-md <md>
python -I -X utf8 -B $D/tools/tier2_newget_class.py . $D/tier1/new_get_sources.jsonl > <jsonl>
# 6.4 합성 미러 — 사본은 WSL Ubuntu-24.04 의 /root/se_syn_20261029(원본 미러 · 저장소는 바꾸지 않는다). 경로가 이미 있으면 지우고 다시 만든다
wsl -d Ubuntu-24.04 -u root -- python3 /mnt/c/github/ClovirONE/clovirone-server-gathering/$D/synthetic/make_syn.py /mnt/c/github/ClovirONE/clovirone-server-gathering/$D/synthetic/expected.json /root/syn_edits_manifest.json
Y=/root/se_syn_20261029; L="syn_v4_partial=$Y/syn_v4_partial syn_g12_psub_range=$Y/syn_g12_psub_range syn_csus_nofab=$Y/syn_csus_nofab syn_csus_nocomp=$Y/syn_csus_nocomp syn_dl380_partial_link=$Y/syn_dl380_partial_link syn_dell_links=$Y/syn_dell_links syn_dell_primary=$Y/syn_dell_primary syn_g12_03_on=$Y/syn_g12_03_on syn_r1csus01_off=$Y/syn_r1csus01_off"
MSYS_NO_PATHCONV=1 python tests/redfish-probe/mirror_replay/run_tier1.py $L --out-root <head 출력> --server-distro Ubuntu-24.04 --playbook-distro Ubuntu --loc yi --build-id <임의>
#   base 코드: 104bcaf0 worktree 의 run_tier1.py 를 돌리면 그 worktree 코드로 수집한다(SE_REPO_ROOT 를 설정하지 않을 때 스크립트 위치 기준)
git worktree add --detach <wt> 104bcaf0
MSYS_NO_PATHCONV=1 python <wt>/tests/redfish-probe/mirror_replay/run_tier1.py $L --out-root <base 출력> --server-distro Ubuntu-24.04 --playbook-distro Ubuntu --loc yi --build-id <임의>
python -I -X utf8 -B $D/synthetic/check_syn.py $D/synthetic/expected.json --head <head 출력> --base <base 출력> --head-ref $D/tier1-after --base-ref $P/tier1-A --out-md <md> --out-json <json>   # 등록 기준 7/9
#   사후 점검(ERRATUM.md): 위 명령에서 expected.json 대신 expected_posthoc.json — 9/9
# 6.5 A/B/C (비교기는 수집 코드 · 재생 도구 · 감사 도구를 import 하지 않는다)
#   run_abc.sh 는 원천 미러 압축 해제본을 고정 경로 두 곳(C:/github/ClovirONE/mock2-fix-20261028/extract · C:/github/서버mock데이터/1차)에서 읽는다. 다른 경로면 사본의 E · M1 을 바꾼다
bash $D/tools/run_abc.sh <Tier 1 출력 루트> <out 접두사>      # <out 접두사>.json · .md 를 쓴다. $D/tier1-after → abc/head.json 과 바이트 같음, $P/tier1-A → abc/base.json 과 바이트 같음
# 6.6 변이(저장소 루트에서 — 파일을 한 번에 하나씩 되돌리고 hash 로 복원한다. 다른 실행과 겹쳐 돌리지 않는다)
python -I -X utf8 -B $D/mutation/mutate.py ; python -I -X utf8 -B $D/mutation/mutate2.py
# 6.7 보존 확인 — $P/REVIEW_FIX_HANDOFF.md 4.5 · 4.6 의 명령에서 입력 출력 루트만 새 Tier 1 출력으로 바꾼다
```

## 7. Tier 0 (CI gate) · 최종 pytest

- 시험한 커밋은 `90f9c0eb678e83c0b171d5b6c61b09b86bb03095`(커밋 11)이다. 그 뒤 커밋은 기록(이 절 · `tier0/` · 하네스 문서)만 바꾼다.
- **공식 Runner: NOT_RUN.** `clovirone-server-gather-ci` 는 `*/main` 전용 Job 이라 이 브랜치를 돌릴 수 없고, 그 설정은 바꾸지 않았다. 아래 두 실행은 이 세션이 직접 돌린 로컬 등가 gate 이며 공식 Runner CI PASS 가 아니다.

| 실행 | 조건 | 결과 | 산출 |
|---|---|---|---|
| Linux 공식 등가 | WSL `Ubuntu` ext4 새 clone `~/se-fix-20261029`(`core.autocrlf` unset · `core.fileMode=true` · CRLF 파일 0). 격리 venv `~/venv-se-ci-20261028`(2026-10-28 Tier 0 와 같은 venv — Python 3.12.3 · ansible-core 2.20.3 · pytest 9.2.0 · `include-system-site-packages = false`). `env -i` PATH = venv · `/usr/local/bin` · `/usr/bin` · `/bin`(pwsh · powershell.exe 없음). 명령은 `Jenkinsfile_ci` Gate 와 같다: `. scripts/activate_ansible_venv.sh` → `CI_GATE_JUNIT_DIR=… bash scripts/ai/ci_gate.sh` | **`RESULT: PASS` · rc 0.** 단계 FAIL 0 · 건너뜀 0. 사전 검사 PASS(10 checks 중 8 passed · 0 failed · 경고 114) · schema 정합(sections 11 · 사전 경로 264) · 벤더 경계 · 하네스 일관성 통과 · corpus 20/20 MATCH · pytest 6504 passed · 183 skipped · 5 xfailed · integration 563 passed · 4 skipped · 1 deselected · JUnit failures 0 · errors 0 · syntax-check 3 채널 통과 | `tier0/linux-venv/`(env · pip freeze · 로그 · JUnit) |
| Windows 작업 트리 | 저장소 작업 트리(HEAD 같음 · 추적 파일 변경 0 — 시작과 끝의 untracked 는 `tier0/` · `tools/tier0_win.sh` 뿐). `core.autocrlf=true` · `core.fileMode=false`. Python 3.13.15 · pytest 9.1.1, ansible 없음. 명령 `CI_GATE_JUNIT_DIR=… bash scripts/ai/ci_gate.sh`(`tools/tier0_win.sh`) | **`RESULT: PARTIAL` · rc 2.** 단계 FAIL 0, 건너뜀 1(syntax-check — 실행할 수 있는 ansible-playbook 이 없다. ci_gate 설계상 ansible 없는 Windows 의 정상 판정). pytest 6642 passed · 45 skipped · 5 xfailed(1792 s) · integration 540 passed · 6 skipped · 1 deselected · JUnit failures 0 · errors 0 | `tier0/windows-worktree/`(env · 로그 · JUnit) |

- 수집 수: unit · e2e · regression 은 두 실행 모두 6692 다. integration 은 Linux 567 · Windows 546 이다(차이 21 은 2026-10-28 Tier 0 와 같다).
- skip(JUnit 기준, xfail 5 포함)은 Linux 188 · Windows 50 이고 2026-10-28 과 같은 수다. 사유: Linux 는 `powershell.exe 없음` 계열(43 · 42 · 32 · 26 · 12건 등), Windows 는 `Linux bash · coreutils timeout · flock 이 필요하다` 25건 · `failed 상태가 아님` 6건 등이다. 두 실행이 서로 빠진 쪽을 덮는다. syntax-check 는 Linux 실행 결과로 본다.
- 2026-10-28 Tier 0(`d552ae06`) 대비 passed 가 두 환경 모두 pytest +254 · integration +38 이다. 커밋 8 시점 Windows 4묶음(unit · e2e · regression 합 6629 passed · integration 540) 대비 +13 · 같음이다.
- Windows 에서 가끔 멈추던 `tests/unit/test_linux_hba_ib_markers.py::test_rate_parsing_keeps_decimal_and_nulls_when_not_active` 는 이번에 11개 경우 모두 통과했다(가장 긴 경우 7.8 s).
- 두 실행은 겹치지 않게 차례로 돌렸다(Linux 2026-10-31 00:35 UTC 시작 → 끝난 뒤 Windows 00:43 UTC 시작). 2026-10-28 에 겹쳐 돌려 메모리 부족으로 중단된 일이 있었기 때문이다.
- Windows 로그(`ci_gate.log` · `env.txt`)는 커밋 전에 줄 끝만 LF 로 바꿨다(CRLF 278 · 2건, 다른 바이트 같음). 11절 sha256 은 그 LF 파일 기준이다.
- 공식 Runner 에서 닫으려면 운영 담당자가 Runner 셸에서 이 브랜치를 clone 해 같은 명령을 돌린다. 확인 항목은 `2026-10-28-redfish-mock2-review-fix/tier0/tier0.md` 3절과 같다: venv `include-system-site-packages` · pytest 버전 · Gate 단계 PATH 에 pwsh 없음 · git `core.autocrlf` · `core.fileMode` · `RESULT: PASS` · JUnit 보관.

```bash
# 재현 — Linux(WSL Ubuntu). ~/se-fix-20261029 가 이미 있으면 exit 3 이다(지우고 돌린다). 결과는 tier0/linux-venv 에 덮어쓴다
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash /mnt/c/github/ClovirONE/clovirone-server-gathering/tests/evidence/2026-10-29-redfish-summary-fix/tools/tier0_wsl.sh <HEAD sha>
# 재현 — Windows(Git Bash, 작업 트리). 출력 폴더가 이미 있으면 exit 3 이므로 새 폴더를 준다
bash tests/evidence/2026-10-29-redfish-summary-fix/tools/tier0_win.sh <HEAD sha> <새 출력 폴더>
```

## 8. Plan 문구와 실측 · 구현이 다른 곳

Plan 은 저장소 밖(사용자 승인본)이라 고치지 않고 여기에 적는다. 저장소 문서에는 실측값만 넣었다. 뒤쪽 6행은 Plan 의 세부와 다르게 구현한 곳이다(의도는 같다).

| Plan 문구 | 실측 | 근거 |
|---|---|---|
| 5절: Dell R740 "속도 그룹 0 → null (10개)", Lenovo "r1 10개, V4 _01 · _02 · _04 각 2개" | 그룹 키 7개 — R740 2 · r1 SR650 2 · V4 _01 · _02 · _04 각 1. 합쳐진 그룹 0 | `tier1/explained.md` |
| 5절: CSUS 소비전력 "원천이 x.5 이상인 미러만 +1 W" | half-even 이라 1000.5 → 1000(짝수)은 그대로다. 바뀐 것은 815.75 · 591.5 · 945.75 셋 | `tier1/allow.json` SA-17 항목 |
| 8절: `request_budget.json` 8건 "replay-miss 404 로 +1" | DL380 4건 · Dell 1건은 +1, CSUS 3건은 +2(404 캐시 없음 — top-level · 파티션 storage 가 각각 요청) | 3.3절 표 |
| 9절: `syn_dell_primary` "25000 → null" | edit 은 대표 NIC `SpeedMbps` 10000 → 0. base 출력 10000(다른 NIC 값) → head null | `synthetic/results_posthoc.md` |
| 10절: 합성 `syn_v4_links`(sr650_v4_02) | `syn_dell_links`(r1_DELL_R740_01)로 만들었다. 같은 값(NIC `Enabled` · 포트 `Training` · `LinkFlapping`)을 NIC 자체 `LinkStatus` 와 카드 `NetworkPorts` 가 함께 있는 미러에 넣었다 | `synthetic/expected.json` |
| 14절: 커밋 11개 | 테스트 커밋 2개(`b2fd9c0d` · `543a1794`) · handoff 보완 커밋 1개(`92ceb055`) · Tier 0 기록 커밋 2개가 더 있다 | 2절 |
| 15절 조건 4: "합성 사례 전부 PASS (사전 기록한 기대값 기준)" | **등록 기준으로는 충족하지 못했다(7/9).** FAIL 2는 기대값 경로 오기이며 정오표 · 사후 점검(9/9)을 남겼다. 받아들일지는 검증자 · 사용자 판단이다(10절 질문 2) | `synthetic/ERRATUM.md` |
| 8절 SA-07: 드라이브 목록 신호를 storage 반환 dict 의 내부 키 `_inventory` 로 넘긴다 | `gather_storage(..., inventory_out=<dict>)` 출력 인자로 넘긴다. top-level 은 `aux_out['storage_inventory']`, 파티션은 `_normalize_storage_raw(sto_data, part_inv)` 로 간다. storage dict 에 비어 있지 않은 내부 키가 생기면 섹션 runner 의 빈 결과 판정(`_is_empty_result` — 404 만 난 빈 결과를 미지원으로 분류)이 깨지기 때문이다. 판정 의미와 출력은 Plan 과 같다 | RG `gather_storage` docstring |
| 3절 SA-07: incomplete 대상 목록(섀시는 `Drives` 컬렉션만 적음) | 섀시 본문(System 섀시 · `Links.Enclosures`)의 404 아닌 실패도 incomplete + errors[] 로 센다. 본문이 드라이브 목록 경로 위에 있기 때문이다. 404 는 미제공 | RG `_chassis_drives_union` |
| 3절 SA-09: network notice 섹션당 1건 | NIC 은 EthernetInterfaces 경로당 1건(섹션 `network` — 다중 System 이면 System 마다 1건), 포트는 NetworkAdapters 수집 1회당 1건(섹션 `network_adapters`) | RG `gather_network` · `gather_network_adapters` 끝 |
| 3절 SA-17: 절삭 → 반올림 | 부수 효과: legacy `PowerControl` 측정값이 소수 문자열('412.6')이면 종전 `_safe_int` 는 None 으로 버렸고 이제 413 이다. 18대 Tier 1 · golden 대장에서 None → 수 변화는 0 | RG `gather_power` 주석 |
| 9절 SA-17 예시(golden 소비전력 2건) | `data.multi_node.chassis[].power.power_control.power_consumed_watts` 도 같은 값으로 바뀐다(3.1절 — 3대 × 3경로) | `tier1/explained.md` |
| (Plan · 감사에 없음) 용량 미상 디스크 | 구현 중 "용량 미상 디스크가 있으면 grand null" 규칙을 넣었다가 되돌렸다. 승인 범위 밖이고, 기존 계약 시험 `tests/unit/test_partition_normalize_grouping.py::test_summarize_zero_and_none_capacity_skipped`(용량 0 · None 디스크는 그룹 · 합에서 뺀다)를 깨기 때문이다. 현행대로 그 디스크를 빼고 합한다. 18대 Tier 1 봉투의 디스크 52개(파티션 포함) 중 용량 미상 0개. 정책 질문은 9절 | 커밋 4 |

## 9. 남은 것

| 항목 | 상태 | 닫는 방법 |
|---|---|---|
| HOLD-a SR650 V4 NIC6 · NIC4 두 번째 MAC | [HOLD] 구현 안 함 | OS 가 어느 MAC 을 쓰는지 실장비 확인 + 별도 승인 |
| HOLD-b `05-thermal-003 (b)` Sensor GET | [HOLD] 구현 안 함(thermal 에는 Summary 가 없어 영향 0) | Status · Thresholds 값이 있는 실장비 캡처 + 요청 예산 승인 |
| HOLD-c `03-storage-001 (b)` 전원 Off 컨트롤러 보강 | [HOLD] 구현 안 함. gen12_03 storage null 은 SA-07 구조 규칙의 결과라 HOLD-c 와 독립 | 기존 계획 |
| SA-12 실장비 | [MOCK_LIMITATION] | 섀시에만 드라이브가 노출되는 장비(NVMe direct-attach 등), golden recording 에 없는 새 경로의 실장비 응답, 선택 링크가 5xx 를 줄 때의 동작, HPE 에뮬레이터 4세트 경로(NO_MIRROR) |
| SA-07 실장비 | [MOCK_LIMITATION] | 다른 벤더가 전원 Off 에서 내는 드라이브 목록 원천. `Drives: []` 를 주는 BMC 는 "확인한 0" 으로 처리되는 한계, 디스크 없는 장비가 원천을 전혀 노출하지 않으면 null |
| SA-09 · SA-17 실장비 | [MOCK_LIMITATION] | Starting · Training 을 실제로 내는 장비(18대 관측 0) · Telemetry 정밀도 |
| `power.summary.psu_count` 신호 | [TODO] | PSU 목록만 노출되지 않은 경우를 가를 신호가 없다 — 별도 설계 |
| 용량 미상 디스크가 섞인 storage 합계 | [DONE 2026-11-01 — 사용자 결정 a안] (작성 당시 [TODO / 사용자 결정]) | 현행은 그 디스크를 빼고 합한다. 일부만 확인한 합이 전체 합처럼 보일 수 있어 이번 원칙과 어긋난다. 선택지: (1) 현행 유지 + 문서화 (2) Redfish 에서 null + notice(SA-04 · 05 와 같은 방식 — 기존 계약 시험 기대값이 바뀐다). 18대 영향 0. **2026-11-01 사용자 결정: (1) 현행 유지 + 문서화(a안)** — 한계("실제 전체 용량보다 작을 수 있음")는 `docs/contract/03-fields.md` 6.3 의 2026-11-01 메모. 제품 코드 · 시험 변경 0 (2026-11-07 독립 재검증 D-01 정정) |
| OS · ESXi storage 미관측 정책 | [TODO] | SA-07 은 Redfish 만 바꿨다(OS · ESXi 는 수집 실패면 섹션 failed). 같은 구분이 필요한지 사용자 결정 |
| S22 중복 제거 키 구분자(NS `name~model~serial`) | [TODO] | 감사도 NOT_RUN · 낮은 위험. 별도 수정 |
| `test_power_summary_b58_b59.py` 복사 구현 | [INFO] 남겨 둠 | 모든 입력에서 운영 템플릿과 12키 동치를 단정하므로 drift 는 잡힌다(`543a1794`). 복사본 제거는 선택 |
| Summary 감사 도구 재판정 | [NOT_RUN] | 감사 12절 7단계(`recheck.py` · 합성 10종 재실행)는 독립성을 위해 이 세션이 돌리지 않았다 — 독립 재검증 세션 몫 |
| Portal null 처리 | [TODO] | 운영 담당자 — 3.4절 키 목록 |
| 공식 Runner ci_gate | [NOT_RUN] | 운영 담당자가 Runner 셸에서 이 브랜치를 clone 해 `scripts/ai/ci_gate.sh` 실행(`$P/tier0/tier0.md` 3절의 확인 항목) |
| 실장비 검증 | 0건 | — |

## 10. 검증자에게 묻는 질문

1. **S1~S22 의 정의 원천.** 감사 폴더에는 번호별 목록이 없다. 보고서 · 감사 도구 주석에 나온 13개는 `audit_case_test_map.md` 1절에 대응시켰다. S3 · S4 · S5 · S7 · S8 · S11 · S12 · S13 · S21 의 9개는 어디에도 없다 — 정의가 있으면 알려 주십시오.
2. **합성 등록 FAIL 2.** 기대값의 경로 이름 오기를 정오표(`synthetic/ERRATUM.md`)와 사후 점검으로 처리했다. 등록 기준 7/9 를 그대로 둔 채 받아들일지, 기대값을 새로 등록하고 다시 돌릴지 판단해 주십시오.
3. **SA-12 합집합.** 감사 권장(문서 먼저, 합집합은 실장비 확인 뒤)과 다르게 구현했다(1.1절). 18대 출력 변화 0 의 근거는 Tier 1 미러 실응답뿐이다. 실장비 확인 전에 main 에 넣을지는 사용자 결정이다.
4. **A/B/C CM 36.** 같은 MAC 포트 값 보충(F-01 규칙)을 문서화된 차이로 셌다. 감사 규칙표의 R-NET-6 해석과 같은지 확인해 주십시오.
5. **FD 표기.** null 이 될 수 있게 된 키를 FD 머리 메모 · help · 03-fields 로만 적었다(전용 type 칸이 있는 키는 이미 `|null`). 이것으로 충분한지 확인해 주십시오.

## 11. 산출물 sha256

sha256 은 저장소 blob(LF) 기준이다. `core.autocrlf=true` checkout 에서는 `git show HEAD:<경로> | sha256sum` 으로 계산한다. 묶음 행은 아래 명령의 출력이다(`r` = `tier1-after` · `tier2-after` · `synthetic/run-head` · `synthetic/run-base`).

```bash
D=tests/evidence/2026-10-29-redfish-summary-fix
git ls-files -- "$D/$r" | grep -E '/gather_output\.json$|\.module\.json$' | LC_ALL=C sort \
  | while read -r p; do printf '%s  ./%s\n' "$(git show "HEAD:$p" | sha256sum | cut -c1-64)" "${p#"$D/$r/"}"; done | sha256sum
```

| sha256 | 파일 (`tests/evidence/2026-10-29-redfish-summary-fix/` 기준) |
|---|---|
| `e4b5962479390d5af81decfa4abc416bc247ccf7d13a14a8e53a9a2a7b5ad99e` | `tier1-after/_summary.json` |
| `eaa75566769737b19b2f5fa522dc7be20135a9352d66b76696106d64bfdeaa95` | `tier1/explained.json` |
| `7f403ce02269357578f42461650d8fbbd0356b529b1d676bdeaf96e752f640ef` | `tier1/diff.md` |
| `60a300c7e3e03d9d42b539eb58788415063f17176ef5bf5e0019b4dc59819774` | `tier1/invariants.md` |
| `03121b30e9170c0ff462dd9e427b2a877691f2638622f9e8661d7f56309f8d47` | `tier1/allow.json` |
| `e47cb61722d66bb56c01cd4938a0fe13db474d2c9f9e0168d91ee16b9f9e7cce` | `tier1/new_get_sources.jsonl` |
| `02cc7a58b81fa5a2b005769af60ed85c30300e080c494ef0e43b4bf286e58f9d` | `tier1/base_equiv.md` |
| `c117448624c5b76a3146a311fcabbc712330eb15002f9715bea90c6a434cdc7b` | `tier2-after/_summary.adapter.json` |
| `73e33fb7ddb3f90f8443044093c500ab3b90e80e14cc4c216890e7f9a8fbc9c3` | `tier2-after/_summary.plain.json` |
| `752befc76e7cd6a2afb2560f6d1628f589576cbe3c5f09972d94a88e575b6087` | `tier2-after/_vs_golden.md` |
| `1327ed414c25d4b0fdf7d06cb0df2e3639f0ad3224c8d2b6bc5314163a54ba99` | `tier2-after/_newget_class.jsonl` |
| `88e1b69a37682a407083524cf21c1f07e7e76eb6841a4fd7807fea59f6e3cc35` | `synthetic/expected.json`(사전 등록 — `expected.sha256` 과 같음) |
| `b10221c0de6b6108cd7f2fddb2361c7dd38346ddfdb8bfcf8a9e17208960a612` | `synthetic/expected_posthoc.json` |
| `62ac2cdc1ed9038dbf532ec2836710109559820d53586f6856c336368769c3b7` | `synthetic/edits_manifest.json` |
| `af0e4927063b94cf062c0701d32c63680bae5ed9f2235fe3b15c6ba9cc89c1ed` | `synthetic/results.json` |
| `eb01e7c764dc961da75c58875f5ac1c933fa2287afc901c5cd0cac324ca88a70` | `synthetic/results_posthoc.json` |
| `d1ff632fcb436ee37c4e0310532be3e0197aac925525962553aaae776d8d831e` | `synthetic/run-head/_summary.json`(build `syn-head-0bc68f71`) |
| `f575aaeccbe91e180f0f349ed2ecef170f30a4a49b2e9761949aec7dabd44f7b` | `synthetic/run-base/_summary.json`(build `syn-base-104bcaf0`) |
| `5391d39c4827499bdf1916ef14f636676093a216c57251d4da79244144dcc91d` | `abc/head.json` |
| `3ba85c6ed5da37f84d282a30fae0a65143e212de64a1cc11d580fe087e7b9e9b` | `abc/base.json` |
| `ccf65a7200c49d6ec23087377d698769c44b9853846e020fc59c7e19e80538e1` | `preservation/oracle_compare.json`(2026-10-28 `oracle-A/oracle_compare.json` 과 같음) |
| `53a49f9231d0aa8e2f30aa470136bf21e13d7bd3d598a8ed40a049bf0d550486` | `preservation/cell_check.json`(2026-10-28 과 같음) |
| `f7c307e073ac4b6740bb8439d24f12294dee7e647d505570de92e0b12671195d` | `preservation/recount.md`(2026-10-28 과 같음) |
| `d9cb4f1c267be6587d670cc7156c0ccc7fa25467555136361f6f5792fb722482` | `preservation/linkstatus_values.md`(2026-10-28 과 같음) |
| `4944118d0ae1dfcf6da7bc95318786fc2f6c838ce0594ea309056a9802b56dde` | `preservation/parity/_parity.md`(2026-10-28 과 제목 줄만 다름) |
| `3e40f37c3bb29f403c5b58fb637ea774e8181987893d3a8d20c06e935e741583` | `preservation/csus_card_conditions.md` |
| `61a983d8735c18c2e5563342005cb270f98e5f78644369427223ba4f3635e392` | `mutation/mutation_results.txt` |
| `3fadb3cb077c745223c0d96b6e9b8d955fce4770f7aca613bb7e52a5c0c55537` | `replay_miss_ledger.json` |
| `f4d4171851183c3fc8f85544756f11d638fd4281263186d5861d93c813fe7b1c` | `golden_changes.json` |
| `b48a312a93b0ce07afc67b3801fac2b6230bf2fa838d0a56b6c8cb81abe4a258` | `audit_case_test_map.md` |
| `16b8685fea5385765e03e122f0f166c4a150f9d2dd2032a2b6bad77a421113ae` | `tier1-after` 의 `*/gather_output.json` 18개(정렬 `sha256sum` 목록의 sha256) |
| `84724a579326d23c4bfebb537fc9b57300c5e337f77e57df9300039d40e11ac1` | `tier2-after` 의 `*.module.json` 18개 같은 방법 |
| `2a42e2007d71a6055ff30194a44811d9e79e61272c85d539d8faa09697399f94` | `synthetic/run-head` 의 `*/gather_output.json` 9개 같은 방법 |
| `da64bdae6431c9163ef4d8bf3097c6b7f3f6f5c4b8ec62a047980d2735137fee` | `synthetic/run-base` 같은 방법 |
| `caee5156eed9c36ded8692d66db78daf19b67d4e8e562e417efb9c52858c1255` | `tier0/linux-venv/ci_gate.log` |
| `8886fd47e7b6cea165a634c24b3376e96fbc6040455df121336c1b9a905dba9c` | `tier0/linux-venv/env.txt` |
| `ce069c8da5f04bdf73b0e2e3cdfda0e1a5f8547b25682b4ade463f9320352bbc` | `tier0/linux-venv/pip_freeze.txt` |
| `6ab1e0bf50a6c6979dfeee982939e27f723df775ad549bdf589d3dbb5a6e9587` | `tier0/linux-venv/ci_gate_junit_unit.xml` |
| `4ee602d2648f68ca65f4435b63fd472157a173d4f65e87d2c1793bc77ffc73cf` | `tier0/linux-venv/ci_gate_junit_integration.xml` |
| `a4e1663594f5c7b709ec9e528df4d62e52fa2afdde8591cd4e3558d5420435ec` | `tier0/windows-worktree/ci_gate.log`(줄 끝 LF 로 바꾼 뒤) |
| `29530fb283ed76071a3257f4e96d52e1e29ba9bbde86cd5b6089bbb05aa66633` | `tier0/windows-worktree/env.txt`(줄 끝 LF 로 바꾼 뒤) |
| `749033e3e46cf0feabc4337598a52e2c9ec09f09ea7265b395660b1012463a20` | `tier0/windows-worktree/ci_gate_junit_unit.xml` |
| `f12676b21859d403f2d2d93d32498c1ed1364464bfa043d27736a6760733cbb9` | `tier0/windows-worktree/ci_gate_junit_integration.xml` |
