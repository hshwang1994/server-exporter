# Coding Glossary (한국어) — server-exporter

> 자주 쓰는 용어 사전. AI / 사람 모두 사용. rule 23 R7 풀이 첨부 의무 어휘.

## 도메인 핵심

| 용어 | 풀이 |
|---|---|
| **Fragment** | 각 gather가 만드는 자기 데이터 조각. 5 공통 변수: `_data_fragment` / `_sections_supported_fragment` / `_sections_collected_fragment` / `_sections_failed_fragment` / `_errors_fragment`. 변수 이름은 모든 gather 동일, 값으로 자기 섹션을 채움. `merge_fragment.yml`이 누적 병합. (rule 22) |
| **Fragment 철학** | 각 gather는 자기 fragment만 만들고, 다른 gather의 fragment를 절대 수정 안 함. 새 섹션 추가 시 build_output.yml 전체 수정 불필요 — site.yml에 include_tasks 한 줄만. |
| **3-channel** | os-gather (Linux/Windows) + esxi-gather + redfish-gather (BMC/IPMI). target_type 으로 자동 감지. |
| **Adapter** | 벤더/세대별 수집 방식을 추상화한 YAML. `adapters/{redfish,os,esxi}/{vendor}_*.yml`. match / capabilities / collect / normalize 경로 포함. |
| **Adapter 점수** | `score = priority × 1000 + specificity × 10 + match_score`. 높을수록 우선. priority=0(generic) / 10(기본 벤더) / 50-100(세대별) / +match.model_patterns. |
| **adapter_loader** | lookup plugin (`lookup_plugins/adapter_loader.py`). adapters/ 스캔 → match 평가 → 점수 계산 → 정렬 → 최고 점수 반환 (또는 generic fallback). |
| **Sections (11)** | system, hardware, bmc, cpu, memory, storage, network, firmware, users, power, thermal. `schema/sections.yml`에 정의. |
| **Field Dictionary** | `schema/field_dictionary.yml`. 항목마다 `priority` 가 Must(모든 vendor 필수) / Nice(vendor-specific 허용) / Skip(의도적 미수집) 중 하나다. 개수는 적지 않는다 — `grep -c '^\s*priority:' schema/field_dictionary.yml` 로 그때 센다 (rule 00). |
| **Baseline** | `schema/baseline_v1/{vendor}_baseline.json`. 실장비 회귀 기준선. schema 변경 시 영향 vendor 전수 회귀. |
| **target_type** | `os` / `esxi` / `redfish` 셋 중 하나. inventory_json + 입력으로 채널 결정. |
| **loc** | 운영 사이트. 정본은 `common/vars/locations.yml` (현재 ic / chj / yi / git). Jenkins agent 선택과 vault 경로에 쓰이고 코드 분기는 없다. |
| **vendor_aliases** | `common/vars/vendor_aliases.yml`. 벤더 이름 정규화 메타 (예: "Dell EMC" → "dell"). |

## 진단 / 안전

| 용어 | 풀이 |
|---|---|
| **Precheck** | `common/library/precheck_bundle.py` 의 진단 절차. TCP 도달·포트를 한 번에 판정하고 프로토콜을 확인한다. 도달성은 **TCP 응답 OR ICMP Echo 응답** 이며 ICMP 는 TCP 전멸 시 1회만 보는 보조 근거다(Gate 아님). 인증 단계는 운영에서 실행되지 않는다. |
| **Vault 2단계 로딩** | Redfish 특화. 1단계 무인증으로 ServiceRoot detect → vendor 결정 → 2단계 vendor vault 로드 후 인증으로 재수집. |
| **Linux 2-tier gather** | preflight.yml에서 `_l_python_mode` 자동 감지. `python_ok` (Python 3.9+) / `python_missing` / `python_incompatible` / `raw_forced`. raw 경로는 dmidecode 기반. |
| **Diagnosis** | 출력 envelope의 `diagnosis` 필드. 각 단계 결과 + gather_mode + python_version 등 메타. |

## 출력 / Schema

| 용어 | 풀이 |
|---|---|
| **JSON envelope** | callback_plugins/json_only.py가 출력하는 표준 13 필드 (rule 20 R1). 분석 6 분류(status/sections/data/errors/meta/diagnosis) + 라우팅·식별 7. |
| **build_*.yml** | `common/tasks/normalize/build_{sections,status,errors,meta,correlation,output}.yml`. fragment 누적 → 최종 JSON 조립. |
| **callback URL** | 호출자에게 결과 통지하는 URL. 공백/후행 슬래시 방어 필수 (commit 4ccc1d7). rule 31 무결성. |
| **Jenkins 4-Stage** | Validate (입력) → Gather (ansible-playbook) → Validate Schema (field_dictionary 정합) → E2E Regression (pytest baseline). 각 Stage FAIL 게이트. |

## 운영

| 용어 | 풀이 |
|---|---|
| **agent-master 망 분리** | Ingest 단계는 master에서 (8bd80c1 / 4ccc1d7), gather는 agent에서 실행. |
| **Round 검증** | 새 벤더/펌웨어 검증 단위 (Round 1, 2, ...). docs/reference/decision-log.md + tests/evidence/에 기록. |
| **graceful degradation** | precheck 일부 단계 실패 시 가능한 데이터만 수집하고 errors에 기록. status는 partial. |
| **post-merge** | `git merge / pull / rebase` 직후. `post_merge_gap_check + post_merge_incoming_review` hook 자동 실행 (rule 97). |

## 하네스 메타

| 용어 | 풀이 |
|---|---|
| **Tier 0/1/2/3** | 정본 / 진입 인덱스 / 상세 정책 / 이력 감사 (server-exporter 도입 시 계승된 4계층 분류). |
| **자기개선 루프** | observer → architect → reviewer → governor → updater → verifier 6단계. `harness-evolution-coordinator`가 조율. |
| **measurement-targets** | rule 28 R1 카탈로그 13종. TTL + 무효화 trigger 미리 확립 → 매번 재측정 vs 캐시 사용 자동 판정. |

## 외부 시스템

| 용어 | 풀이 |
|---|---|
| **Redfish ServiceRoot** | BMC API 진입점 (`/redfish/v1/`). 무인증 detect 가능. Chassis / Systems / Storage / Volumes 등 link 제공. |
| **iDRAC / iLO / XCC / CIMC** | 각각 Dell / HPE / Lenovo / Cisco의 BMC 이름. |
| **vSphere API** | ESXi 6.x/7.x/8.x. pyvmomi 라이브러리 사용. |
| **WinRM** | Windows Remote Management. pywinrm으로 Python에서 호출. |
