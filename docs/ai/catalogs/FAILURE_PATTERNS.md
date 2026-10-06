# FAILURE_PATTERNS — server-exporter

> 발견된 실패 / 오탐 / 반복 실수 기록 (append-only, rule 70 트리거).
> 새 사례 발견 시 즉시 추가. 카테고리: scope-miss / ai-hallucination / external-contract-drift / vendor-boundary-violation / fragment-violation / vault-leak / convention-drift

## 형식

```
## YYYY-MM-DD — <한 줄 요약>

- 카테고리: scope-miss / ai-hallucination / ...
- 발견 위치: <파일 또는 commit>
- 증상: <관측>
- 원인: <분석>
- 영향: <범위>
- 수정: <commit / PR>
- 재발 방지: <rule / skill / hook 변경>
- 관련 rule: rule N
```

---

## 2026-06-09 — gather 엔진 외부 JSON 파싱 robustness gap (mutation 하네스로 검출)

- 카테고리: external-contract-drift / production-crash
- 발견 위치: `redfish_gather.py`(multi_node 정규화 + firmware/_p) / `precheck_bundle.py` / `merge_fragment.yml` (fault-injection 하네스 mutation.py 로 검출)
- 증상:
  1. **P0 crash**: BMC 가 `total_cores`/`capacity_mb`/`total_mb` 를 **문자열**로 반환 시 `int()`/`//` ValueError/TypeError → multi_node 정규화는 section runner 밖이라 **모듈 전체 죽음**(envelope 0). CSUS/Superdome 실재 위험.
  2. **P1 silent-loss**: 1 개 firmware 멤버의 `@odata.id` 가 비-str(dict/int) → `_p().lstrip` AttributeError → section runner catch → firmware 섹션 **전체**(23건) silent 손실.
  3. **P2 hang**: 무경계 `Members`/`Drives` 순회 → 악성/버그 BMC 수천 멤버에 멤버당 `_get` N회(각 timeout) → 사실상 hang.
  4. precheck `Members[0].get` 비-dict([null]/[str]) AttributeError. merge_fragment `list+dict` 같은 key → `bv+fv` TypeError.
- 원인: `_safe_int`/`_safe` 방어 헬퍼가 있는데도 일부 경로가 bare cast/접근. 직전 사이클이 golden 고정만 하고 **변형 입력으로 검증 안 함**.
- 영향: multi_node(CSUS/Superdome) 전 채널 / firmware·storage·memory 섹션 / precheck 전 채널.
- 수정: P0 `_safe_int` 통일 + P1 `_p()` 무효 path/split isinstance + P2 `MAX_COLLECTION_MEMBERS`/`_capped` + precheck isinstance + merge_fragment `is not mapping`. 커밋 ad1fc8d/c037ee3/dee9bfe/efe582b/6378453.
- 재발 방지: `tests/integration/mutation.py` fault-injection 하네스 영구화(변형 입력 회귀 38건). golden byte 불변으로 정상 경로 무침범 보장. rule 95 R1 #2/#7.
- 관련 rule: rule 95 R1, rule 92 R2(Additive), rule 96 R1-B

---

## 2026-06-08 — replay 하네스 _REPLAY_MISS 가 absent endpoint 를 failed 로 오분류 (fidelity)

- 카테고리: test-harness-fidelity
- 발견 위치: `tests/integration/emulator_harness.py:_REPLAY_MISS` (DMTF mockup fixture 편입 중 rule 95 R3 비판적 리뷰)
- 증상: DMTF `public-rackmount1`(Chassis 에 NetworkAdapters 없음) 재생 시 `network_adapters` 가 `failed` 로 분류 + error_count 증가. 실 BMC 라면 `unsupported`(capability 미지원).
- 원인: replayer 의 `_REPLAY_MISS = (404, {}, "replay-miss: path not in recording")` — err 문자열에 'HTTP 404' 토큰이 없어 `redfish_gather._is_404_only_error` 가 404 로 인식 못함. 실 `_get` 은 404 시 err="HTTP 404: Not Found" 를 줘 unsupported 로 분류됨. 즉 replay 가 실 BMC 의 404 를 충실히 모사하지 못한 인공물.
- 영향: recording 에 없는(=실 BMC 의 404) 모든 path. HPE fixture 는 make_recorder 가 모든 fetch(404 포함)를 기록해 _REPLAY_MISS 미도달 → 무영향. lean(404 미기록) DMTF fixture 만 표면화.
- 수정: `_REPLAY_MISS` → `(404, {}, "HTTP 404: Not Found (replay-miss: ...)")` 로 실 404 모사. test `test_absent_resource_graceful` 가 absent endpoint 의 unsupported 분류를 회귀 고정.
- 재발 방지: 신규 회귀 테스트 + 본 entry. (엔진 redfish_gather.py 무변경 — 순수 harness fidelity)
- 관련 rule: rule 95 R3, rule 40

## 2026-06-08 — storage: SimpleStorage fallback 성공인데 failed 로 분류 (기존 엔진 동작 관찰)

- 카테고리: external-contract-observation (engine status 분류 — 후속 검토 후보)
- 발견 위치: `redfish-gather/library/redfish_gather.py` gather_storage(:2069) + `_make_section_runner`(:2796) (DMTF rackmount1 재생 — modern Storage 부재 → SimpleStorage fallback)
- 증상: modern `/Storage` 404 → `/SimpleStorage` 200 파싱 성공(data.storage 정상: 1 controller / 4 drive). 그러나 엔진이 `_err('storage','Storage 미지원, SimpleStorage fallback 사용')` notice 를 남겨 storage 를 `failed` 로 분류 + status=partial.
- 원인: `_make_section_runner` 가 "errs 非空(404-only 아님) → collected+failed". fallback notice 는 404-only 가 아니므로 데이터가 있어도 failed.
- 영향: SimpleStorage fallback(legacy BMC / 표준 mockup) + HPE iLO4 SmartStorage fallback(:2077) — **동일·일관·기존 동작**. 파싱 버그 아님.
- 수정: **하지 않음**(본 cycle 범위 외). fallback 성공 시 failed→degraded/collected 재분류는 status 의미론 변경(rule 13 R8, 4-시나리오 매트릭스 + docs/19/20 + fixture 동반) + 호출자 계약 영향이라 사용자 승인 + 별도 cycle 필요. golden 은 현 동작을 충실 캡처(회귀 baseline), test 는 분류와 무관히 **파싱 정확성** 만 positive assert(현 동작 freeze 아님).
- 재발 방지: NEXT_ACTIONS 후속 후보 등재 + test docstring 명시.
- 관련 rule: rule 95 R3, rule 13 R8, rule 92 R2

## 2026-05-07 — netmask CIDR Jinja2 loop-scoping 사고 (4번째 동일 패턴)

- 카테고리: jinja2-loop-scoping (반복 패턴 — cycle-015 + cycle-016 + M-D2 다음 4번째)
- 발견 위치:
  - `os-gather/tasks/linux/gather_network.yml:99`
  - `esxi-gather/tasks/normalize_network.yml:67`
- 증상: `/23`, `/26`, `/30` 같은 비표준 CIDR 가 잘못 계산 (`/24`, `/32`, `/32` 로 보고)
- 원인: outer for(octet) 안 `set val = octet|int` + inner for(bit) 안 `set val = val - bit` — Jinja2 default for-scope 위반 (inner for set 이 다음 inner iteration 에 미반영). `/24`, `/16`, `/8`, `/0` 같은 all-FF octet 만 우연히 정상 (모든 bit 트리거 → 8 bits)
- 영향: 비표준 CIDR 사용 사이트 envelope `data.network.interfaces[].cidr` / `prefix` 잘못된 값 emit. lab 이 `/24` 만 사용 → 표면화 안 됐음
- 수정: cycle 2026-05-07-post — `val` 을 namespace 에 포함 (`ns.val`). commit 151c1386
- 재발 방지:
  - `pre_commit_jinja_namespace_check.py` advisory 가 본 사고 검출 (cycle 2026-05-07 Phase B 신설 hook)
  - `tests/unit/test_netmask_cidr_jinja_fix.py` 19 회귀 (broken algorithm 사고 명시 + fixed algorithm 정답)
  - 다른 동일 패턴 없는지 `find . -name "*.yml" | xargs grep -l "for octet\|for bit"` 추가 점검 권장
- 학습: 동일 Jinja2 namespace scoping 사고 4번째 발생 → hook advisory 정합. blocking 격상 검토 (1 cycle 모니터링 후)
- 관련 rule: rule 22 R7 (Fragment Jinja 안전), rule 95 R1 #2 (코드 critical review)

---

## 2026-05-01 — 외부 계약 advisory 다수 등재 (F91/F97/F104/F125/F126 — 10R extended audit)

- 카테고리: external-contract-drift (advisory)
- 발견 위치: 10-Round Extended Web Audit (아카이브(정리됨))
- 증상: 외부 계약 변종 / 보안 advisory / vendor 차이 — 사고 재현 전 사전 등재
- 등재 항목:
  - **F91 CVE-2024-54085** — AMI MegaRAC SPx Authentication Bypass (Critical 10.0). server-exporter read-only → 영향 0. 운영팀 BMC 펌웨어 업그레이드 권장.
  - **F97 SSL Unexpected EOF** — Dell iDRAC9 일부 펌웨어. F84 의 SSLContext min/max + SECLEVEL=0 fallback 일부 회피.
  - **F104 Session lockout** — Basic Auth 단발성 유지 시 영향 없음. F33 (X-Auth-Token 도입) 진행 시 DELETE session 보장 의무.
  - **F125 Cisco CIMC < 4.x** — cisco_cimc.yml firmware_patterns "^[4-6]\\." 로 4.x 이상만 매칭. 3.x 이하는 cisco_bmc.yml fallback.
  - **F126 DIMM error vendor 차이** — Health 만 raw passthrough. 호출자 시스템이 vendor 별 해석.
- 원인: web 검색 (DMTF / vendor docs / community) — lab 부재 영역 사전 식별 (rule 96 R1-A)
- 영향: 직접 코드 변경 0. 외부 계약 변종 등재 (`EXTERNAL_CONTRACTS.md` ## F91/F97/F104/F125/F126 절)
- 수정: docs only — `docs/ai/catalogs/EXTERNAL_CONTRACTS.md` 갱신
- 재발 방지: 사고 재현 시 본 advisory 참조 후 fix
- 관련 rule: rule 96 R1-A (lab 부재 web sources)

## 2026-05-01 — 신 generation BMC adapter 부재 사전 식별 (F41/F47/F55/F61/F69)

- 카테고리: external-contract-drift (사전 차단)
- 발견 위치: 7-loop Web Compatibility Audit
- 증상: 신 generation BMC (Dell iDRAC10 / HPE iLO7 / Lenovo XCC3 / Supermicro X12-X14 / Cisco UCS X-Series) 출하 시 기존 adapter 가 매칭은 되지만 schema 일부 차이로 envelope 누락 가능
- 사전 차단 적용:
  - dell_idrac10.yml (priority=120) — F41 (PowerEdge 17G)
  - hpe_ilo7.yml (priority=120) — F47 (Gen12)
  - lenovo_xcc3.yml (priority=120) — F55 (ThinkSystem V4 / OpenBMC)
  - supermicro_x12.yml / x13.yml / x14.yml — F61 (AST2600 + 신 features)
  - cisco_ucs_xseries.yml (priority=110) — F69 (X210c/X410c standalone)
- 추가 호환성:
  - F48: NetworkPorts deprecated → Ports fallback (이미 적용)
  - F83: redfish_gather.py GET only 명시
  - F84: SSLContext minimum_version=TLSv1_2 / maximum_version=TLSv1_3
  - F80: EXTERNAL_CONTRACTS.md DMTF spec 매트릭스
  - F56: lenovo_xcc.yml 을 V2/V3 로 좁힘 (XCC3 분리)
  - F68: cisco_cimc.yml 에 M5~M8 generation 매트릭스 + firmware_patterns 좁힘
- 원인: 사용자 명시 "redfish 코드의 벤더, 모델, 버전 호환성 전수조사. 루프 7번"
- 영향: 신 BMC 도입 시 envelope quality 저하 사전 차단 (호환성 fallback only — 새 데이터 추가 아님)
- 수정: 본 cycle commit
- 재발 방지: cycle 2026-05-01 cold start 가능 ticket fixes/F##.md 보존
- 관련 rule: rule 96 R1-A (web sources), rule 50 R2 (vendor 추가 절차 — 본 cycle 은 신규 vendor 가 아닌 기존 5 vendor 의 신 generation 만)

## 2026-05-01 — 404 'failed' 오분류 → 'not_supported' 분류 도입 (3채널 인프라)

- 카테고리: external-contract-drift + scope-miss
- 발견 위치: 사용자 사이트 envelope errors[] 보고 (Dell host)
  - `power 정보 실패: HTTP 404: Not Found`
  - `networkadapters 미지원 또는 실패: HTTP 404: Not Found`
- 증상:
  - 일부 vendor/펌웨어가 `/Chassis/{id}/Power` / `/Chassis/{id}/NetworkAdapters` 자체 미응답 (404)
  - 코드가 'failed'로 분류 → errors[] 노이즈 (호출자 입장에서 "수집 실패"로 오해)
  - DMTF 2020.4 (Redfish 1.13+)에서 Power schema deprecated → PowerSubsystem 권장
  - 신 펌웨어 (HPE Gen12 / Lenovo XCC2-3 / Dell iDRAC9 5+ / Supermicro X14+) 가 PowerSubsystem만 응답
  - 기존 fallback 패턴은 storage (Storage→SimpleStorage) 만 — power/network_adapters는 부재
- 원인:
  - **404 (endpoint 자체 부재 = capability 미지원) vs 5xx (진짜 fail) 구분 없이 같은 errors[] 분류**
  - 신 표준 (PowerSubsystem) fallback 미구현
  - sections 분류 enum이 success/failed/not_supported 인데 실제 코드는 not_supported 분류 안 함
- 영향: 5 vendor 모두 영향. iDRAC8 / 일부 PowerEdge / 구 Lenovo 등 capability 미지원 모델은 호출자 envelope에 영구적 noise.
- 수정 (cycle 2026-05-01 4 commit):
  1. `9eb11fe4` redfish `_make_section_runner` 404-only errs 분리 → unsupported list. `gather_power` PowerSubsystem fallback parser
  2. `a483811b` 3채널 fragment 인프라 — `_all_sec_unsupported` + `_sections_unsupported_fragment` 도입 (init/merge/build_sections). redfish normalize_standard wiring
  3. `5df5a9e1` 회귀 테스트 9건 (test_redfish_404_unsupported.py)
  4. (본 commit) 문서 governance
- 재발 방지:
  - DMTF schema 변천 (Power→PowerSubsystem / Thermal→ThermalSubsystem) 추적 의무
  - 새 vendor adapter 추가 시 `tested_against` 펌웨어별 endpoint 호환성 origin 주석 (rule 96 R1)
  - 404 분류 패턴을 다른 채널(OS/ESXi)로 점진 전환 — fragment 인프라 마련됨
- 외부 계약 sources:
  - DMTF Redfish 2020.4 (Power deprecated)
  - HPE iLO 6 v1.10 (BaseNetworkAdapters → Chassis/NetworkAdapters)
  - Lenovo XCC3 = Redfish 1.17.0 / XCC2 = 1.20.0
  - Supermicro X14+ PowerSubsystem
- 관련 rule: rule 96 (external-contract-integrity), rule 13 R5 (envelope), rule 95 R1 #11

## 2026-04-30 — Hotfix — OData-Version/User-Agent 추가가 Lenovo XCC reject

- 카테고리: external-contract-drift + reverse-regression
- 발견 위치: cycle 2026-04-30 첫 fix (commit 4715bb5b) 적용 후 사이트 빌드
- 증상:
  - HTTP 406 fix 적용 후 lenovo 장비 수집 안 됨 (이전엔 정상이던 BMC)
  - 사용자 검증: `Accept` 헤더만 추가했을 때는 OK / `OData-Version` + `User-Agent` 까지 추가한 commit 적용 후 fail
- 원인:
  - Lenovo XCC 일부 펌웨어가 추가 헤더 (`OData-Version` 또는 `User-Agent`)에 strict reject
  - 정확히 어느 헤더가 reject 원인인지는 follow-up 진단 필요 (lab에서 헤더 single 추가 비교 시험)
  - "표준 권장 = 모든 BMC 호환" 가정 실패 — Redfish 표준 권장 헤더가 일부 펌웨어 strict 처리에 부적합
- 영향: HTTP 406 fix를 Lenovo XCC 사이트에 적용 못 함. Hotfix로 즉시 정정.
- 수정: commit (Hotfix) — Accept 헤더만 유지, OData-Version + User-Agent 제거
  - precheck_bundle.py http_get: Accept만
  - redfish_gather.py _get/_post/_patch: User-Agent만 제거 (OData/Accept는 cycle 이전부터 잘 동작했으므로 유지)
- 재발 방지:
  - "표준 권장 헤더 = 안전" 가정 폐기. 실 BMC 펌웨어 검증 후 추가
  - 새 헤더 추가 시 lab + 사이트 BMC 둘 다 사전 검증 의무 (rule 92 R3 대형 변경 회귀 체크리스트 강화)
  - 사용자 실측 ("Accept 만으로 OK") 결과를 1순위 데이터로 채택 — 표준 spec보다 실 BMC 동작이 우선
- 관련 rule: rule 25 R7-A (실측 검증), rule 92 R2 (선제 변경 자제), rule 96 R2 (외부 계약 질의 우선)

## 2026-04-30 — Redfish BMC HTTP 406 (precheck Stage 3 false-positive 미지원)

- 카테고리: external-contract-drift + http-header-missing
- 발견 위치: `common/library/precheck_bundle.py` http_get (line 164~)
- 증상:
  - 사이트별 일부 Lenovo/HPE BMC만 precheck Stage 3에서 "Redfish 미지원" abort
  - curl `-k` 로는 ServiceRoot 200 정상 응답
  - 같은 Jenkins agent + 같은 Python에서 동일 URL Python urllib만 fail
  - root cause: HTTP 406 Not Acceptable
- 원인: `precheck_bundle.http_get` 가 `Accept`/`OData-Version` 헤더 명시 안 함.
  Python urllib는 default로 `Accept` 헤더 안 보내고, 일부 BMC 펌웨어
  (HPE iLO 펌웨어 ServiceRoot RedfishVersion 1.17.0 등)는 명시 요구. curl은
  default로 `Accept: */*` 보내서 OK. **본 수집 (`redfish_gather.py`) 은 이미
  헤더 보냄 — precheck만 누락된 drift**.
- 영향: precheck Stage 3 통과 못하는 BMC 사이트별 수집 0%. 본 수집까지 못 감.
- 수정: commit 4715bb5b (`fix: precheck/redfish HTTP 헤더 호환`)
  - http_get에 Accept/OData-Version/User-Agent 명시
  - probe_redfish status 허용 405/406 추가 (이중 안전)
  - redfish_gather.py _get/_post/_patch User-Agent 일관 추가
  - 회귀 테스트 2건 (test_service_root_405/406_treated_as_supported)
- 재발 방지:
  - 새 외부 통신 함수 추가 시 헤더 origin 주석 의무 (rule 96 R1 강화 검토)
  - 사이트별 BMC 펌웨어 다양성 회귀 — `tests/fixtures/redfish/` 에 1.17.0 fixture 추가 필요 (별도 cycle)
- 관련 rule: rule 96 (external-contract-integrity), rule 95 R1 #11

## 2026-04-30 — _compute_final_status partial 오판정 (vault fallback 차단)

- 카테고리: ai-hallucination + cross-flow-consistency
- 발견 위치: `redfish-gather/library/redfish_gather.py:1781` `_compute_final_status`
- 증상:
  - Dell vault accounts list 첫 자격 fail이어도 status='partial' 반환
  - try_one_account.yml `_rf_attempt_ok` (status != 'failed') 가드가 partial을 success로 판정
  - → 두 번째 자격증명으로 fallback 안 됨
  - 사용자 보고: vault 순서 [A, B] / [B, A] 둘 다 첫 자격 매칭 서버만 OK
- 원인: 1개 섹션이라도 collected에 들어가면 무조건 'partial' 반환. 인증 fail 흔적
  (errors[]에 HTTP 401/403) 무시.
- 영향: multi-account vault 시나리오 (recovery / 공통계정 fallback) 무력화. 데이터
  일부만 받은 상태로 호출자에 emit (호출자도 "부분 성공"으로 오해).
- 수정: commit 7b0afc0c (`fix: 401/403 발견 시 'failed' 강제`)
  - _compute_final_status 시그니처 errors 추가
  - errors[]에 HTTP 401/403 detail 발견 시 partial 무효화 → 'failed'
  - 회귀 테스트 7건 (test_redfish_compute_final_status.py)
- 재발 방지:
  - try_one_account loop 가드 + final_status 판정 일관성 cross-flow 회귀 의무
  - status 'partial' / 'failed' 분류 기준에 auth 차원 명시 (rule 13 R5 envelope 정의 보강 검토)
- 관련 rule: rule 95 R1 #6 (빈 callback message), rule 13 R5

## 2026-04-29 — production-audit-bundle (4 agent 전수조사로 일괄 발굴)

- 카테고리: scope-miss + cross-channel-drift + jinja2-loop-scoping
- 발견 위치: 4 agent audit 결과 (Redfish + OS-ESXi-common + Schema + Tests)
- 증상 (대표 6건):
  1. **Skeleton drift** — `init_fragments.yml` + `build_empty_data.yml` + `build_failed_output.yml` 3종이 sections.yml과 sync 안 됨 (storage.{hbas,infiniband,summary} / network.{adapters,...} 누락) — rescue path가 success path와 다른 envelope shape 출력
  2. **ESXi vendor 미정규화** — esxi_baseline.json `vendor: "Cisco Systems Inc"` (Redfish는 'cisco' lowercase canonical) — 호출자 라우팅 불가
  3. **diagnosis.details 형변환** — 성공 path는 dict, fallback은 list of strings — 호출자 파싱 시 TypeError
  4. **Windows runtime swap_total_mb 합계 버그** — Jinja2 loop scoping (cycle-016 namespace fix가 memory/storage만 적용, runtime 누락) → 마지막 pagefile 크기만 emit
  5. **ESXi DNS 항상 빈 list** — `vmware_host_config_info`의 `hosts_config_info[hostname]` 구조를 top-level iterate (production에서 DNS 정보 0건)
  6. **account_service.yml 복구 creds 미설정** — `ansible_user`/`ansible_password` Ansible connection var 사용했지만 set_fact 안 됨, 빈 string으로 401
- 원인: 점진적 cycle 누적 + cross-channel 일관성 검증 hook 부재 + Jinja2 scoping 패턴 유사 코드 일괄 적용 누락
- 영향: 모든 5 vendor + 모든 OS + ESXi (cross-channel JSON 호환성)
- 수정: 본 production-audit cycle 일괄 fix (Edit tool 직접 적용 / pytest 148/148 PASS / verify_* 4종 PASS)
- 재발 방지:
  - JSON envelope cross-channel consistency hook 추가 검토 (rule 13 R5 자동 검증)
  - cycle 종료 시 4 agent audit 패턴 정기화 (rule 28 R1 추가 측정 대상 검토)
  - Jinja2 loop scoping linter 검토
- 관련 rule: rule 13 R5 / rule 22 R1 / rule 80 R1

---

## 2026-04-29 — user-label-vs-redfish-manufacturer-drift (cycle-015)

- 카테고리: external-contract-drift
- 발견 위치: `inventory/lab/redfish.json` ↔ 실 Redfish ServiceRoot 응답 (rule 27 R3 1단계)
- 증상: 사용자가 BMC IP에 vendor 라벨 부여 ("dell" / "cisco") 했으나 무인증 ServiceRoot 응답이 다른 Manufacturer로 회신 (`AMI` / `TA-UNODE-G1`)
- 원인:
  1. 사용자가 호스트 라벨을 OS / 사용 환경 기준으로 부여 (e.g. "이 머신에 Dell 서버 OS 깔려있음")하지만 실제 BMC는 별도 OEM
  2. Whitebox / GPU 호스트는 보드 OEM과 BMC OEM이 다른 케이스 잦음
  3. Cisco TelePresence / Tetration 같은 비-UCS 제품도 Cisco 그룹으로 통칭
- 영향:
  - rule 27 R3 1단계가 자동 검출 → graceful degradation 가능 (회귀 영향 0)
  - 단, 사용자 라벨에 의존한 inventory 작업 / vault 매핑은 잘못된 vendor 사용 위험
- 수정: 본 cycle 시점 inventory/lab/redfish.json은 `_vendor` 메타 보존 + DRIFT-011 entry로 추적. 실측 deep_probe 후 라벨 정정.
- 재발 방지:
  - **rule 27 R3 1단계 (무인증 ServiceRoot detect) 의무 — 이미 채택**
  - rule 96 R4 — drift 발견 시 3 곳 기록 의무 (이미 채택)
  - **신규 권장**: 새 BMC inventory 등록 시 사용자 라벨 + Redfish 실 응답 1회 확인 의무 (skill `add-new-vendor` 본문에 추가 권장 — 후속)
- 관련 rule: rule 27 R3 (Vault 2단계 — 1단계가 본 drift 검출), rule 96 R1 (외부계약 origin), rule 50 R1 (vendor 정규화)
- 관련 evidence: `tests/evidence/cycle-015/connectivity-2026-04-29.md` 5절

## 2026-04-30 — http-200-only-protocol-classification (5 commits)

- 카테고리: external-contract-drift
- 발견 위치: `common/library/precheck_bundle.py` (probe_redfish/probe_esxi/probe_os) + `redfish_gather.py` (storage controller / network adapters) + `esxi-gather/tasks/collect_runtime.yml` (firewall_state)
- 증상: 호출자에게 "Redfish 미지원" / "vSphere endpoint 미응답" / "WinRM 미응답" / "controller 정보 부재" 보고가 발생하지만 실제 BMC/ESXi/Windows 는 정상 응답 중. 인증 강화 펌웨어 (HPE iLO5/6 일부, Lenovo XCC 일부) 가 ServiceRoot 무인증 시 401 던지는 케이스가 가장 흔함.
- 원인: HTTP 200 응답만 "프로토콜 살아있음"으로 분류, 401/403/503 등 의미 있는 응답을 모두 fail 로 분류. probe_esxi 는 이미 status_code 화이트리스트 패턴 갖고 있었으나 401/403/503 누락. probe_os WinRM 도 403/503 누락.
- 영향: 인증 강화 BMC + 다중 host vCenter + IIS 재시작 중 Windows 환경에서 false negative — 호출자가 "장비 자체 미지원" 으로 잘못 판단.
- 수정 (2026-04-30 push):
  - `c23d185f` probe_redfish 401/403/503 → protocol_supported (회귀 테스트 8건)
  - `31178f8c` probe_esxi/probe_os 401/403/503 + timeout_protocol 6→15s (회귀 13건)
  - `a60e42b5` redfish storage controller 401/403/503 silent fail 정정 (errors 누적 + status_code 메타, 회귀 7건)
  - `6ea2c292` ESXi firewall_state 빈 list ≠ disabled (보안 라벨 반대 보고 차단)
  - `9d5c957b` ESXi collect_runtime hostname 명시 lookup (multi-host 임의 host 참조 차단)
- 재발 방지:
  - 새 probe / endpoint 추가 시 status_code 화이트리스트 명시 의무 (별도 rule 검토 후속)
  - rule 96 R4 정합 — origin 주석에 "status_code 응답별 의미" 매트릭스 기록 권장 (`EXTERNAL_CONTRACTS.md` 매트릭스 참조)
- 관련 rule: rule 27 R5 (precheck layer), rule 96 R1 / R4 (외부계약), rule 95 R1 #11 (외부계약 drift)
- 관련 evidence: `tests/unit/test_precheck_probe_*.py` (3 파일 21 케이스), `tests/unit/test_redfish_storage_controller.py` (7 케이스)

---

## 2026-04-30 — errors-string-iteration (char 분해 회귀)

- 카테고리: jinja2-string-coerce + fragment-violation
- 발견 위치: `os-gather/tasks/linux/gather_system.yml:344-352` (root cause) + `common/tasks/normalize/merge_fragment.yml` (수신측 char iter)
- 증상: 호출자 envelope `errors[]` 가 단일 character 들로 분해된 5개 entry 보고 — `[{"section":"unknown","message":"["}, {"...":"]"}, {"...":"\n"}, {"...":"}"}, {"...":"}"}]`. 사용자가 의미 있는 메시지 받지 못함.
- 원인 (3 layer):
  1. **ROOT**: `_errors_fragment: >- ... }} }}` — `>-` folded scalar 끝에 잉여 `}}` 두 글자. Jinja list 결과가 string 으로 coerce 되며 `\n}}` 가 concat → `_errors_fragment` 가 list 가 아닌 string `"[]\n}}"` 로 들어감.
  2. **수신측 char iter**: `merge_fragment.yml` 의 `for e in (_errors_fragment | default([]))` 가 string 입력에 대해 character 단위 iterate (Jinja2 표준).
  3. **방어 부재**: `_errors_fragment` 가 list 가 아닌 경우의 가드 없음.
- 영향: 모든 OS gather Linux Python path. 호출자 시스템 파싱 오류 가능. 보안 영향 없음 (정보 손실만).
- 수정 (2026-04-30 push):
  - `88de692d` (root cause + 방어 layer 2겹) — gather_system.yml 잉여 `}}` 제거 + merge_fragment/build_errors 에 string/dict/None/int 입력 list 강제 wrap, char iter 차단, whitespace char skip. 회귀 테스트 10건.
  - `cfc24eee` (전수 스캔 후속) — 같은 패턴이 windows/gather_system + redfish/normalize_standard 의 `_errors_fragment` 에도 잠재 위험으로 존재 → 단일 ternary 로 단순화.
- 재발 방지:
  - **신규 패턴 식별**: fragment 변수에 `>-` block scalar + 다중 `{{}}` 분기 + plain text 혼재 = string-coerce 위험. 단일 expression 또는 별도 set_fact 분리 권장.
  - rule 22 R8 (fragment 타입) — list of dicts 강제 명시. 본 cycle entry 추가 검토.
  - 회귀 테스트 패턴: jinja2 라이브러리로 fragment Jinja 직접 evaluate (Ansible 환경 없이 단위 테스트 가능).
- 관련 rule: rule 22 R7/R8 (fragment 명명/타입), rule 23 R8 (ASCII 태그 — 다이어그램 정렬도 같은 폰트 폭 이슈)
- 관련 evidence: `tests/unit/test_errors_normalize.py` 10 케이스 (사용자 보고 케이스 정확 재현 + 차단 검증)

---

## 향후 가능 패턴 (Plan 1+2 도입 시점 예측)

참고 — clovirone에서 학습한 일반 패턴은 rule 95 R1 (의심 패턴 11종)에 흡수됨.

### 향후 가능 패턴

1. **Fragment 침범** (rule 22): gather가 다른 섹션의 fragment 변수 set_fact
2. **Vendor 하드코딩** (rule 12): common 코드에 "Dell" 등 직접 분기
3. **외부 계약 drift** (rule 96): 펌웨어 업그레이드로 Redfish path 변경 → adapter origin 주석 stale
4. **Vault 누설** (운영 권장 — cycle-011: rule 60 해제, cycle-012 vault encrypt 채택): Jenkins console log에 BMC password 노출
5. **Schema 3종 일부만 갱신** (rule 13): sections.yml만 수정하고 field_dictionary / baseline 미갱신
6. **adapter score 동률** (rule 95 R1 #4): 의도와 다른 adapter 선택
7. **Linux raw fallback 미고려** (rule 10 R4): Python 3.6 환경에서 setup 모듈 가정
8. **callback URL 후행 슬래시** (이미 commit 4ccc1d7로 fix): 입력 URL 정규화 누락
9. **Jenkinsfile cron 사용자 승인 누락** (rule 80): AI 임의 cron 변경
10. **incoming-merge 위반 무시** (rule 97): 자동 검사 보고서를 후속 PR으로 정리 안 함

## 2026-04-30 — Lenovo XCC2/XCC3 namespace prefix Oem 키로 vendor=null

- 카테고리: external-contract-drift
- 발견 위치: `redfish-gather/library/redfish_gather.py::_detect_vendor_from_service_root`
- 증상: Lenovo 장비인데 ServiceRoot vendor 감지 결과 `null`. envelope의 `vendor: null` 출력. 동적 vault 로딩 실패로 인증 단계 우회 가능성.
- 원인: 일부 Lenovo XCC2/XCC3 펌웨어가 Oem 키를 단순 `"Lenovo"`가 아닌 `"Lenovo_xxx"` namespace prefix 형식으로 반환. 기존 코드는 정확 매칭만 시도 (`if k in vm`).
- 영향: Lenovo 일부 펌웨어 전체. vendor=null → adapter 매칭 generic fallback → 일부 OEM 섹션 누락.
- 수정: cycle 2026-04-30 — `_detect_vendor_from_service_root`에 namespace prefix 매칭 1-B 단계 추가 (`k.startswith(alias + '_') or k.startswith(alias + '.')`)

## 2026-04-30 — 구 BMC TLS handshake 실패로 "Redfish 미지원" 오판정

- 카테고리: external-contract-drift
- 발견 위치: `common/library/precheck_bundle.py::_build_ssl_context`, `redfish-gather/library/redfish_gather.py::_ctx`
- 증상: curl `-k` 로는 ServiceRoot 정상 응답 받는데, server-exporter precheck Stage 3에서 "이 장비는 Redfish를 지원하지 않습니다" 메시지.
- 원인: Python 3.12 + OpenSSL 3.x default SSL context는 legacy renegotiation 차단 + weak cipher 차단. 구 BMC (HPE iLO4, Lenovo IMM2, 일부 iDRAC7/8 펌웨어)와 handshake 실패 → URLError → http_get payload=None → probe_redfish가 status_code 분기 못 타서 fail.
- 영향: 구 BMC 펌웨어 환경 전체. precheck Stage 3 false negative → 본 수집 진입 차단.
- 수정: cycle 2026-04-30 — verify=False 시 `OP_LEGACY_SERVER_CONNECT` + `DEFAULT@SECLEVEL=0` 적용 (curl `-k` 동등 관용성, BMC self-signed 망 한정)

## 2026-04-30 — BMC 제품명 시그니처 부족으로 vendor=null

- 카테고리: external-contract-drift
- 발견 위치: `redfish-gather/library/redfish_gather.py::_detect_vendor_from_service_root`
- 증상: ServiceRoot Vendor 필드 부재 + Oem 부재 펌웨어에서 Product에 "XClarity Controller" / "iDRAC9" / "AMI MegaRAC" 등 BMC 제품명만 있을 때 vendor=null.
- 원인: 기존 코드는 `'ilo' in product` / `'proliant' in product` 만 추가 매칭 (HPE만). Dell iDRAC / Lenovo XClarity / Supermicro MegaRAC / Cisco CIMC 시그니처 부재.
- 영향: ServiceRoot v1.0~1.4 펌웨어 + Oem 부재 BMC.
- 수정: cycle 2026-04-30 — `_BMC_PRODUCT_HINTS` 상수 도입 (idrac/ilo/proliant/xclarity/thinksystem/xcc/imm2/megarac/cimc/ucs). Product + Name 필드 둘 다 매칭.

## 2026-04-30 — ServiceRoot v1.0~1.4 펌웨어 vendor=unknown (G3 fix)

- 카테고리: external-contract-drift
- 발견 위치: `redfish-gather/library/redfish_gather.py::detect_vendor`
- 증상: ServiceRoot Vendor/Product 표준 필드 부재 + Oem 부재 BMC 펌웨어에서 vendor=unknown.
- 원인: Vendor는 ServiceRoot v1.5.0+, Product는 v1.3.0+ 표준 필드. 구 펌웨어 (구 iDRAC7/8, iLO 4, IMM2)는 두 필드 모두 부재. ServiceRoot 5단계 매칭 모두 fail.
- 영향: 구 BMC 펌웨어 환경. vendor=unknown → adapter 매칭 generic fallback.
- 수정: cycle 2026-04-30 — `detect_vendor`에 Chassis → Managers → Systems Manufacturer fallback 순회 추가. 표준 Manufacturer 필드는 v1.0+ 모든 BMC 표준.

## 2026-04-30 — probe_redfish transient URLError로 false negative (G5 fix)

- 카테고리: external-contract-drift
- 발견 위치: `common/library/precheck_bundle.py::probe_redfish`
- 증상: BMC 부팅 직후 / 일시 부하 시 1회 fail로 "Redfish 미지원" 오판정.
- 원인: payload=None (URLError/timeout/SSLError) 시 retry 부재 — 1회 fail 즉시 status 결정.
- 영향: BMC 재시작 / 운영 부하 transient 환경.
- 수정: cycle 2026-04-30 — payload=None 시 1초 backoff 후 1회 retry. probe_facts에 retry_count 노출.

## 2026-04-30 — ServiceRoot 본문 비어도 401 realm으로 vendor 식별 가능 (G6 fix)

- 카테고리: external-contract-drift
- 발견 위치: `redfish-gather/library/redfish_gather.py::_probe_realm_hint` (신규)
- 증상: 일부 보안 강화 BMC 펌웨어가 무인증 ServiceRoot에 401 + 본문 비어 반환. ServiceRoot 5단계 + G3 Chassis fallback 모두 인증 필요해 fail.
- 원인: 401 응답의 `WWW-Authenticate: Basic realm="iDRAC"` / `realm="iLO"` / `realm="XClarity Controller"` 헤더 미활용.
- 영향: 보안 강화 펌웨어 환경. vendor=unknown → vault 동적 로딩 차단 가능.
- 수정: cycle 2026-04-30 — `_probe_realm_hint` 신규. 401/403 응답의 realm에서 vendor_aliases + `_BMC_PRODUCT_HINTS` 매칭. detect_vendor 의 마지막 fallback로 통합.

## 2026-04-30 — Vendor 필드 'Dell Inc.' trailing dot 케이스 (G7 fix)

- 카테고리: external-contract-drift
- 발견 위치: `redfish-gather/library/redfish_gather.py::_detect_vendor_from_service_root` step 2
- 증상: ServiceRoot `Vendor: "Dell Inc."` 응답에서 vendor=null. (Product 매칭이 보통 회복하지만 Vendor 단독 케이스 fail)
- 원인: 기존 코드 `v.lower().strip().rstrip('.')` 로 `'dell inc'` 만들고 정확 매칭만. vm에 `'dell inc'` 키 없음 (`'dell inc.'` 만 있음).
- 영향: Vendor 필드만 채우고 Product/Oem 비어 있는 펌웨어.
- 수정: cycle 2026-04-30 — 정확 매칭은 원형 + trailing dot 제거 두 형식 모두 시도. 추가로 substring 매칭으로 보강.

## 2026-04-30 — Redfish multi-account fallback BMC lockout 회피 + 디버그 로그 보강

- 카테고리: external-contract-drift
- 발견 위치: `redfish-gather/tasks/try_one_account.yml`
- 증상: 5 accounts 순회 시 일부 BMC (iDRAC, iLO 일부 펌웨어)가 연속 fail에 source IP 일시 차단. 결과적으로 정답 자격증명도 401 받음. 디버깅 시 어느 단계에서 fail인지 message 부족.
- 원인: attempt 사이 backoff 부재 + failure log가 label/role 만 표시 (status/error 미포함).
- 영향: BMC lockout 환경 + 디버깅 시간 증가.
- 수정 (부분): cycle 2026-04-30 — 실패 시 1초 backoff + status/vendor/first_error 로그 보강.
- 미적용 (사용자 결정 대기): primary `partial` 결과를 fallback 시도 차단으로 처리하는 정책 변경 (`_rf_attempt_ok = status == 'success'` 강화).

## 2026-06-04 — PROJECT_MAP fingerprint Windows autocrlf/pyc noise (반복 churn 근절)

- 카테고리: tooling-noise (drift 오탐 — 반복 패턴)
- 발견 위치: `scripts/ai/check_project_map_drift.py::fingerprint_dir`
- 증상: 작업 트리 clean + 직전 fingerprint 갱신 커밋(ea71f04c) 직후에도 4개 디렉터리(redfish-gather/filter_plugins/module_utils/tests) drift 상시 감지. git log에 `PROJECT_MAP drift 갱신` 커밋 반복(434d0ada/18845699/61a1dba0/41056341/ea71f04c).
- 원인: fingerprint가 디스크 `f.stat().st_size` + `rglob("*")` 기반. (a) `core.autocrlf=true` + `.gitattributes` 부재 → 에이전트 Write(LF) ↔ git 체크아웃(CRLF) 크기 차이 (예: `module_utils/adapter_common.py` git 9307B / disk 9593B, Δ286=CRLF \r 개수). (b) `rglob`가 gitignore 무시 → `__pycache__/*.pyc` 62개 + `tests/reference/local/*` untracked 포함 → pytest 실행만으로 fingerprint 변동. **실제 구조 변경(추적 소스 add/remove)은 0건.**
- 영향: 매 세션 session_start hook이 false drift 경고 noise → 진짜 구조 변경 식별 곤란 + 불필요한 fingerprint 갱신 커밋 churn.
- 수정: cycle 2026-06-04 — `fingerprint_dir`을 `git ls-files -s -- <dir>`의 **경로 집합(정렬된 파일 목록)** 해싱으로 변경. 추적 파일 경로만 보므로 CRLF/pyc/local untracked + **파일 내용 편집**까지 전부 무관 — 파일/디렉터리 추가·삭제·이름변경(= 진짜 구조 변경)에만 반응 (rule 28 R1 #2 목적 정합). baseline 재측정. git 불가 환경 disk rglob 경로 fallback. 검증: ① .pyc 추가 ② 디스크 줄바꿈 토글 → fingerprint 불변(exit 0) 실증. (초기안은 blob OID 해싱이었으나 내용 편집마다 drift → 경로 집합으로 정밀화해 content-only commit churn 까지 제거.)
- 재발 방지: 이 사례 기록 + 스크립트 결정론화 (구조 변경만 추적). (`.gitattributes` 줄바꿈 정규화는 저장소 전반 영향이라 별도 검토 — 본 수정으로 fingerprint는 무관해짐.)
- 관련 rule: rule 28 R1 #2 (PROJECT_MAP 측정 대상), rule 70 R2

## 2026-06-17 — OS gather SSH unreachable가 rescue 우회 → host silent drop

- 카테고리: ansible-unreachable-escapes-rescue
- 발견 위치: `os-gather/tasks/try_one_credential.yml` (linux ssh / windows winrm probe)
- 증상: gatherOS #27~#29 FAILURE, `gather_output.json` 0바이트(Stashed 0), 콘솔엔 무해 경고 2줄(`_os_failed` could not match + `reset_connection when`)만. #26은 53 host 중 27개가 envelope 없이 증발(나머지 26개만 status:failed).
- 원인: SSH 인증 실패는 ansible에서 `failed`가 아니라 `unreachable`로 분류됨. probe에 `failed_when:false`만 있고 `ignore_unreachable:true` 누락 → 첫 후보(`infra/__REDACTED__`)에서 unreachable 발생 시 host가 block/rescue/always(OUTPUT)를 **우회**하고 play에서 제거 → 2번째 후보(`cloviradmin/__REDACTED__`) 미시도 → 0 envelope + 비정상 exit. `json_only` 콜백이 `v2_runner_on_unreachable`/`on_failed`를 OUTPUT task 외 전부 suppress → 사유 비가시.
- 영향: 인증 실패 host가 graceful failed envelope 없이 전량 증발 + fallback 후보 미시도. 모든 host가 unreachable이면 빌드 FAILURE(callback 빈 파일).
- 수정: probe 2종에 `ignore_unreachable:true` 추가 (commit `abe94783`) → unreachable host 보존 → 후보 loop 계속 → 정상 fallback 또는 graceful failed envelope. 검증: 빌드 #30 SUCCESS, 161/165 `status:success`, `auth.fallback_used:true`(infra 실패→cloviradmin 성공).
- 재발 방지: SSH/WinRM 연결성 probe·gather task에는 `ignore_unreachable:true` 필수. json_only가 unreachable/failed를 stderr로 표면화하도록 개선은 후속(NEXT_ACTIONS).
- 관련 rule: rule 95 R1 (의심패턴), rule 27 (precheck), rule 22 (rescue/always)

## 2026-09-21 — include_vars `failed_when: false` 가 Vault 복호화 실패를 지움

- 카테고리: ansible-failed-when-masks-failure
- 발견 위치: `common/tasks/credential/load_one.yml` (`credential | load_one | include vars`)
- 증상: Vault 비밀번호가 없거나 틀려도 `_cl_outcome=loaded` → 계정 0개 → `empty_accounts`.
  `credential_set_undecryptable` 은 실제로 한 번도 나오지 않았다. 사용자 문장이 "계정이 없습니다" 로 나갈 뻔했다.
- 원인: `failed_when: false` 는 결과의 `failed` 를 False 로 덮어쓴다. 바로 뒤 classify 의 `_cl_load is failed` 가 항상 거짓.
  (WSL ansible-core 2.20.7 최소 재현: `is failed=False`, `_cl_included={}`)
- 수정: `ignore_errors: true` (failed 표시 보존) + 회귀 테스트 `test_include_vars_keeps_failure_visible_to_classify`.
- 재발 방지: **`failed_when: false` 뒤에 `is failed` 로 판정하는 패턴 금지.** 실패를 판정해야 하면 `ignore_errors`.
- 관련 rule: rule 95 R1 #5 (상태 분기 혼동), CLAUDE.md §12

## 2026-09-21 — Redfish 자격 판정이 시도 0회를 GATHER_FAILED 로 떨어뜨림

- 카테고리: stage-misclassification
- 발견 위치: `redfish-gather/site.yml` rescue `_rf_auth_outcome` (cred_na 조건)
- 증상: 실행 위치 미등록 / 표준 계정 0개(vendor 식별) / vendor 미상 + 표준 Vault 부재 세 경우 인증을 시도하지
  않았는데 `GATHER_FAILED` + "대상 접속은 확인됐지만" 이 나갔다.
- 원인: 조건이 `_cred_load_outcome`(표준 Vault 결과)만 봤다 — 표준 Vault 는 전역이라 위치 미등록이어도 loaded,
  `empty_accounts` 는 목록에 없음, vendor 미상이면 조건 전체가 꺼짐.
- 수정: `unknown_location` OR 표준 결과 ∈ {missing, undecryptable, empty_accounts} OR (not_resolved AND vendor 식별).
  회귀: `test_redfish_credential_unavailable_is_not_gather` (4 케이스) + WSL 실제 실행.
- 관련 rule: CLAUDE.md §9 (failure_stage = 멈춘 위치), rule 13 R8

## 2026-09-30 — Ansible `fileglob` 은 디렉터리 부분의 `*` 를 풀지 않는다 (Add-on 기능 이름 검사가 빈 목록)

- 카테고리: scope-miss (테스트 범위 누락)
- 발견 위치: Add-on 저장소 `tasks/main.yml` plan 단계 (`ed8f320`, 2026-09-29 재설계) — lab Add-on e2e #8 (2026-09-30)
- 증상: Windows 서버에서 저장소 기본 config(`hosts: false`)만으로 `errors[]` 에 "config.yml 의 'hosts' 에 해당하는 수집 기능이
  없습니다" 가 남았다 (e2e s03 · s13 · s15 WINDOWS FAIL 3건). Add-on 을 켜면 모든 Windows 서버에 거짓 알림이 붙을 뻔했다.
- 원인: 전체 기능 이름 목록을 `query('ansible.builtin.fileglob', <dir>/collectors/*/*.yml)` 로 만들었다. fileglob 은 파일 이름
  부분만 glob 하고 디렉터리 부분은 `find_file_in_search_path` 로 글자 그대로 찾는다 → 늘 빈 목록 → 그 서버 종류에 없는
  기능 이름(Linux 전용 `hosts`)을 "없는 기능" 으로 판정. 단위 테스트는 목록을 직접 넘겨 통과했고, role 실행 테스트는 Linux 만 돌렸다.
- 수정: Add-on `6ef226a` — controller 에서 `glob` 으로 찾는 filter `addon_collector_files` 로 교체. 회귀: `test_core.py`
  (목록 · Windows 파일로 plan), `test_playbook.py` Windows target role 실행(설정 없는 software 는 win_shell 을 부르지 않는다),
  `test_layout.py` (plan 에 `collectors/*/` 금지).
- 재발 방지: Ansible `fileglob` 에 디렉터리 wildcard 를 쓰지 않는다. 서버 종류별로 갈리는 로직은 role 실행 테스트를 두 종류 이상에서 돌린다.
- 관련 rule: rule 95 R1 (의심 패턴), rule 25 R7-A (실측 검증)

## 2026-10-03 — dmidecode sudo 재시도가 "출력이 비었을 때" 만 발동해 비루트에서 한 번도 돌지 않음

- 카테고리: scope-miss (조건 가정 오류)
- 발견 위치: `os-gather/tasks/linux/gather_memory.yml` raw 스크립트 — C1 검수(서브 작업자 strict xfail)에서 발견, `4fe9712a` 에서 수정
- 증상: 비루트 계정의 `dmidecode -t memory` 는 버전 머리말을 stdout 에 찍고 rc=1 로 끝난다. `[ -z "$out" ]` 조건은 거짓이라 `sudo -n` 재시도가 일어나지 않았고
  DIMM 상세가 비어 os_visible fallback 으로 떨어졌다.
- 수정: `{ [ -z "$out" ] || [ "$dmi_rc" -ne 0 ]; }` 로 재시도, sudo 도 출력이 없으면 직접 실행의 출력 · rc · stderr 를 되살린다. 회귀:
  `test_sudo_fallback_also_runs_when_direct_attempt_fails_with_header_output`.
- 재발 방지: 외부 명령의 "실패" 를 stdout 유무로 판정하지 않는다 — rc 를 본다. 실패 분기는 synthetic 으로 양쪽(출력 없음 / 머리말+rc≠0)을 테스트한다.
- 관련 rule: rule 95 R1 #5, CLAUDE.md §10(관측한 것만)

## 2026-10-03 — awk `[[:space:]]` 가 mawk 1.3.3 에서 동작하지 않는다

- 카테고리: external-contract-drift (도구 호환)
- 발견 위치: `os-gather/tasks/linux/gather_memory.yml` SLOT awk (C1 작업 중) — `4fe9712a`
- 증상: 일부 배포판의 기본 awk(mawk 1.3.3)는 POSIX 문자 클래스를 지원하지 않아 DIMM 레코드 파싱이 0건이 될 수 있다. 저장소 reference 캡처는 gawk/mawk 1.3.4 라 드러나지 않았다.
- 수정: `[ \t]` 로 교체. 검증은 mawk 1.3.4 · gawk · dash 조합의 WSL 실행과 정적 테스트 — mawk 1.3.3 실물은 없다(추정 근거: 알려진 미지원).
- 재발 방지: raw 스크립트의 awk/sed 는 POSIX 문자 클래스 대신 명시 집합을 쓴다.
- 관련 rule: rule 10 R4 (raw fallback 환경), rule 96 R1-A (lab 부재 영역 근거 명시)

## 2026-10-03 — ESXi 자격 probe 가 `ansible_facts` 존재만으로 로그인 성공을 판정한다 (수정 안 함 — 결정 항목)

- 카테고리: scope-miss (판정 근거 과소)
- 발견 위치: `esxi-gather/tasks/try_one_credential.yml` `_e_probe_ok` — P5 작업자가 WSL ansible-core 2.20.7 에서 관측
- 증상: interpreter 를 고정하지 않으면 로그인에 실패한 `vmware_host_facts` 결과에도 `ansible_facts: {discovered_interpreter_python: …}` 가 실려 틀린 첫 자격이 승격됐다.
  운영은 `esxi-gather/site.yml:36` 이 interpreter 를 고정하므로 지금은 발생하지 않는다.
- 조치: 바꾸지 않았다(로그인 판정 계약 변경 = 사용자 결정, `docs/ai/NEXT_ACTIONS.md` GP-12). P5 의 facts 재사용은 summary 스키마 키가 있을 때만 재사용해 이 결과를 쓰지 않는다.
- 재발 방지: 모듈 결과의 "성공" 은 그 모듈이 **반드시** 돌려주는 키(스키마 표지)로 판정한다. `ansible_facts` 키 존재는 성공 증거가 아니다.
- 관련 rule: rule 95 R1 #5, rule 25 R7-A(실측 검증)

## 2026-10-03 — win_shell 스크립트는 `powershell.exe -EncodedCommand` 명령줄 32,767자 한도 안에 있어야 한다

- 카테고리: external-contract-drift (실행 환경 한도)
- 발견 위치: `os-gather/tasks/windows/gather_storage.yml` — P4(win_shell 통합) 작업 중 발견
- 증상: 종전 physical-disks 스크립트 하나가 이미 28,159자였다. 스크립트를 합치면 한도를 넘어 WinRM 실행이 통째로 실패할 수 있었다(실장비에서는 아직 미관측).
- 조치: PowerShell 주석을 YAML 주석으로 옮겨 코드 줄은 그대로 두고 22,155자로 줄였다. `tests/unit/test_windows_call_consolidation_static.py` 가 Windows 스크립트마다
  30,000자 상한을 고정한다.
- 재발 방지: win_shell 스크립트를 합치거나 늘릴 때 길이 테스트가 먼저 막는다. 설명은 YAML 주석에 둔다 (production 생성기도 스크립트 안 주석을 제거하므로 같은 방향).
- 관련 rule: rule 10 R3(파일 길이), rule 96 R1(외부 계약 — Windows 명령줄 한도)

## 2026-10-03 — ansible-playbook 이 SIGINT 를 CPython weakref 콜백 안에서 잃고 멈춤 (`--kill-after` 가 받아낸다)

- 카테고리: external-contract-drift (실행 엔진 동작)
- 발견 위치: Phase 5 WSL emulation `t2_int54_f100` (ansible-core 2.20.7, 100 host, PLAY 1.5 진행 중 INT) — `tests/evidence/2026-10-03-phase5-emulation.md` §Task 2
- 증상: 6회 INT 중 1회에서 `KeyboardInterrupt` 가 weakref 콜백 안에서 발생해 "Exception ignored in …" 로 삼켜졌다. 핸들러는 살아 있던 worker 2개를 이미 죽였고
  메인은 남은 98 host 의 OUTPUT 을 낸 뒤 2개 결과를 영원히 기다렸다. `timeout --signal=INT --kill-after=90` 의 KILL 이 rc 137(`timeout_killed`)로 끝냈다.
- 결과: Layer A 가 kept 98 + filled 2 = 100(진단 보존)로 접수 == 결과를 맞췄다. 90 s 유예 · rc 137 매핑 · Layer A 보충이 이 경우를 위해 있다.
- 재발 방지: 배치 제한에서 `--kill-after` 를 빼지 않는다(INT 만으로 끝난다고 가정 금지). Runner(2.20.3)에서 재현해 빈도를 확인한다(GP-19).
- 관련 rule: CLAUDE.md §11(Envelope 보존), rule 80 R1(Gather post 보존)

## 2026-10-03 — tests/ 아래 새 conftest.py 가 e2e 의 `from conftest import …` 를 깨뜨림 (모듈 이름 충돌)

- 카테고리: convention-drift (테스트 구조)
- 발견 위치: prodgen G14(생성 tree + tests overlay) run 3/4 — `tests/unit/prodgen/conftest.py` 추가 뒤 `tests/e2e/test_{output_schema,os_output,logical_volumes,redfish_baseline,cisco_baseline,esxi_output}.py` 수집 오류 6건
- 증상: `ImportError: cannot import name 'assert_array_element_fields' from 'conftest' (…/tests/unit/prodgen/conftest.py)`. pytest 는 인자 디렉터리의 conftest 를 시작 때 먼저 적재하고
  (tests/e2e/conftest.py), 수집 중 만난 다른 conftest 를 같은 모듈 이름 `conftest` 로 다시 적재한다(패키지가 아닌 디렉터리). 그 뒤 e2e 모듈의 `from conftest import` 는 **마지막으로
  적재된** conftest 를 가리킨다. e2e + integration 을 한 번에 돌리지 못하던 기존 현상과 같은 원인.
- 수정: `tests/unit/prodgen/__init__.py` 를 두어 `prodgen.conftest` 로 적재되게 했다(`ae3ec9e8` 이후 커밋). G14 overlay 에 `pytest.ini` 도 포함(표식 등록).
- 재발 방지: `tests/` 아래에 conftest.py 를 새로 두면 그 디렉터리는 **패키지(`__init__.py`)** 로 만든다. 장기적으로는 e2e 의 bare `from conftest import` 를
  `from tests.e2e.conftest import` 로 바꾸는 것이 근본 해결(파일 수가 많아 이번 범위 밖). `pytest tests/unit tests/e2e` 를 **한 번에** 돌려 충돌을 확인한다.
- 관련 rule: rule 40 R6(pytest 회귀), rule 95 R1


## 2026-10-04 — prodgen 순환 테스트 1회 flaky (전체 suite 안에서만, 모듈 단독·재실행은 PASS)

- 카테고리: flaky-test (원인 미확정 — 추정을 사실로 적지 않는다)
- 발견 위치: `bash scripts/ai/ci_gate.sh` 1회차(2026-10-04, Windows, 4,061 passed) 에서 `tests/unit/prodgen/test_promotion_cycle.py::test_refusals_evidence_skiplive_remotes_and_race` 가
  `res["stage"] == "verify"`(기대 `"e2e"`) 로 1건 실패. 같은 모듈 단독 실행(4 passed) · 단일 테스트 재실행 · 2회차 전체 gate(4,070 passed) 는 모두 PASS.
- 의미: world fixture 는 live gate(G11~G15·G19)를 PASS 로 stub 하므로, 그 실행에서는 **실제로 도는 gate(G01~G10·G16·G17 정적, G18 drift, G20 조상·원격)** 중 하나가 FAIL/SKIP 이었다는 뜻이다.
  어느 gate 였는지는 당시 assertion 메시지가 `res` 를 담지 않아 알 수 없다. `gates_static.py` 에는 subprocess timeout 이 없고 `ls_remote` 는 90 s 라 timeout 가설은 근거가 약하다.
- 조치: 세 refusal assertion 에 `, res` 를 붙여 다음 재현 때 `gates.results`·`gate_details`·`refused` 가 그대로 남게 했다(`62a3d440`). 재현되면 그 gate 를 이 항목에 적는다.
- 재발 방지: prodgen 테스트가 suite 안에서 실패하고 단독으로 통과하면 먼저 `res`/`gate_details` 를 확보한다. "다시 돌리니 됐다" 로 끝내지 않고 횟수를 기록한다(1/2 → 이번).
- 관련 rule: rule 40 R6, rule 95 R3(의심 발견 시 드러내기), rule 25 R7-B(추정 격상 금지)

## 2026-10-04 — 실제 Jenkins 에서만 드러난 것들 (Harness · CI 첫 실행 학습, append-only)

- 카테고리: environment-assumption / process
- (1) **`httpRequest` 는 node 컨텍스트의 노드에서 실행된다**(http_request 1.25). finalizer 의 Callback 은 `node('built-in')` 안이라 controller 에서 나간다. agent 에 띄운 sink 로 agent 에서 healthz 를 보고 "controller 도달" 로 적은 것이 오판(Harness #6 NoRouteToHost). → 도달성 확인은 **요청이 실제로 나가는 노드**에서.
- (2) **sandbox 가 거부하는 흔한 호출**: `new groovy.json.JsonSlurperClassic()`, `groovy.json.JsonOutput.toJson(Object)`(List 인자), `new java.lang.IllegalStateException(String)`. 허용: `JsonSlurper`, `readJSON(returnPojo:)`, `toJson(Map)`, `writeJSON`, `new Exception(String)`. 로컬 Groovy 로는 못 잡는다 — Harness 빌드에서만 보인다.
- (3) **CPS 컴파일**: 클로저 안 `for (def it in …)` 은 "The current scope already contains a variable of the name it"(CI #2). 선언형 린터는 통과시키지 않으므로 push 전에 `pipeline-model-converter/validate` 를 돌린다 — 이번엔 안 돌렸다.
- (4) **controller workspace 는 NFS**: 열린 파일을 `deleteDir()` 하면 `.nfs… Device or resource busy`(Harness #17/#25). 장수 프로세스의 파일은 finalizer 가 지우는 디렉터리 밖(`ws("…@sink")`)에 둔다. 비-daemon `threading.Timer` 는 SIGTERM 뒤에도 프로세스를 살려 포트를 쥔다(#26).
- (5) **Runner 는 git 신원이 없다**(`commit-tree` "Author identity unknown", CI #3) — prodgen 커밋은 기본 identity 로. **Runner 생성 tree 는 exec bit 가 빠진다**(build 가 POSIX chmod 안 함) — Windows 에서는 G09 가 fs 검사를 건너뛰어 못 봤다. **CI checkout 에는 로컬 `refs/heads/production` 이 없다**.
- (6) **curl 에 Jenkins `tree=…[…]` URL 을 그대로 주면 glob 으로 해석한다**(rc=3) — `-g`. 같은 함정을 이 세션 안에서 bash 와 Python 양쪽에서 각각 밟았다.
- (7) **main 이 움직이면 진행 중 CI 의 Harness 는 전부 `MAIN_SHA` 불일치로 실패한다**(설계대로 거부, CI #3). 검증 중에는 push 하지 않거나(이 세션은 세 번 어겼다 → CI #4/#6 중단 후 재실행), 문서 커밋은 CI 완료 뒤 한 번에.
- (8) **프로세스 실수**: `python -m pytest … | tail -1 && git commit` — 파이프라인 종료코드는 `tail` 의 것이라 수집 오류(`pytest` import 누락)가 가려진 채 커밋·push 됐다(`20354861`, CI #4 중단). `set -o pipefail` 또는 테스트를 별도 명령으로. heredoc 에 적은 `\n` 은 `\n` 으로 접혀 테스트 리터럴에 실제 개행이 들어갔다(Write/Edit 도구로 쓴다 — 2026-10-03 에 이미 적어 둔 패턴을 또 밟았다).
- (9) **자동 분류기 거부**: 노드 라벨 변경 + 실호스트/Portal 트리거를 **한 명령에 묶어** 요청해 어느 항목이 거부됐는지 알 수 없게 됐다. 다른 범주의 행위는 명령을 나눠 요청한다(각각 1회, 우회 없음).
- 관련 rule: rule 25 R7-A(실측 검증), rule 95 R3, rule 80 R1

## 2026-10-04 — 검증기가 "이름이 맞는 빌드" 를 증거로 받았다 (완료 보고 검토 C1)

- 카테고리: ai-hallucination / scope-miss
- 발견 위치: `scripts/ai/prodgen/evidence.py`(`collect()` · `check_evidence()`), 검토 재현 스크립트(같은 main 빌드를 S1~E2E-A' 전부로, 같은 normal_success Harness 빌드를 12 이름으로 등록 → `accepted=true`)
- 증상: main 시나리오 PASS = "Jenkins 결과 == 호출자가 넘긴 EXPECTED", Harness PASS = "Job 이름에 harness 포함 + artifact verdict". 등록 이름과 실제 파라미터·artifact·동작은 대조하지 않았다.
- 원인: 증거 모델을 "같은 SHA 의 필수 이름이 전부 PASS" 로만 설계했고, 시나리오가 요구하는 입력·관측(대상 host · Callback 수신 · outcome · 보존)을 정본에 적지 않았다. "T5 ABORTED · T6 UNSTABLE 이 기대값" 이라는 문장이 "결과값 비교" 로 축소됐다.
- 영향: 승격 조건 ③ 이 이름 바꾸기로 충족될 수 있었다(실제 조작은 없었음 — 검증기 결함).
- 수정: `MAIN_CONTRACT`(시나리오별 입력 조건·판정 항목·기대 Jenkins 결과) · Harness 파라미터/artifact/해시 대조 · main 함수 그룹 ↔ 생성 tree 그룹 분리(`tree_hash`) · 집계 입력 digest 선검증. 호출자 EXPECTED 는 계약과 같을 때만.
- 재발 방지: "증거" 는 항상 **입력 조건 + 관측 + 결과** 세 축으로 정의한다. 결과값 하나로 PASS 를 만드는 코드는 쓰지 않는다. regression `tests/unit/prodgen/test_verdict_evidence.py`.
- 관련 rule: rule 24 R2 · rule 95 R2

## 2026-10-04 — 환경 식별자가 비어 있으면 "같다" 로 통과시켰다 (검토 C3)

- 카테고리: ai-hallucination
- 발견 위치: `scripts/ai/prodgen/verify/__init__.py::environment_compatible`(`jenkins_version` 한쪽이 비면 continue), `promote.py` 재사용 경로(`collect_environment()` 에 Jenkins 버전 미전달), 주석("G13 재실행") ≠ 실제(G18/G20)
- 증상: 기록된 Jenkins 버전이 있고 현재가 빈 문자열인 입력이 호환 판정을 통과.
- 원인: "모르면 문제 삼지 말자" 를 기본값으로 뒀다. 미확인은 동일성의 증거가 아니다. 또 린터 endpoint 응답에 `X-Jenkins` 헤더가 없어(실측) 값이 항상 비었는데 정보성 TODO(GP-29)로 미뤘다.
- 영향: 다른 Jenkins/plugin 환경의 보고서가 G13 재실행 없이 재사용될 수 있었다.
- 수정: 미확인 = 불일치; 환경 의존 gate 를 promote 가 재실행하고 보고서/trailer 에 재사용·재실행 목록 기록; 식별자에 collections 해시·도구 버전 추가; `/api/json` 헤더로 버전 포착.
- 재발 방지: 비교 함수에서 "알 수 없음" 분기는 항상 **보수적(불일치)** 으로. 주석의 동작 설명은 코드와 같은 커밋에서 테스트로 고정한다.
- 관련 rule: rule 95 R1

## 2026-10-04 — "가장 가까운 provenance 커밋" 을 "baseline 을 기록한 커밋" 으로 썼다 (검토 C2)

- 카테고리: scope-miss
- 발견 위치: `scripts/ai/prodgen/drift.py::first_prodgen_commit`(이름과 달리 nearest), `promote.py::restore` 의 legacy 경로
- 증상: B → P1 → P2(정상 승격) 뒤 `restore --to B --bootstrap-baseline B` 가 "기록한 생성 커밋이 없다" 로 거부. 기존 테스트(B→P1→R→P2)는 이 경로를 지나지 않았다.
- 원인: 두 목적(최신 생성 main 찾기 · baseline 기록 찾기)을 한 함수로 섞었고, 정상 승격 커밋이 baseline trailer 를 물려받지 않았다.
- 영향: 운영에서 두 번째 정상 승격 뒤 최초 baseline 복구가 불가능했을 것이다.
- 수정: `baseline_record()`(이력 전체 탐색) + 정상 승격의 trailer 계승 + `Restore-From`/`Baseline-Recorded-By` 분리. regression B→P1→P2→R→P3 + 실 `4ce90a00` 복제 훈련.
- 재발 방지: 상태 전이 테스트는 "정상 경로가 두 번 이상 반복된 뒤의 복구" 를 반드시 포함한다.
- 관련 rule: rule 95 R1 · rule 24 R2

## 2026-10-04 — .gitignore 된 운영 도구를 CI 가 실행하려 했다 (VAULT_DECRYPT rc 2)

- 카테고리: scope-miss
- 발견 위치: CI #10 `vault_decrypt_check.txt` — "can't open file …/scripts/ai/vault_decrypt_check.py"
- 증상: 로컬에는 있는 파일이 Runner checkout 에 없어 새 CI 검사가 FAIL.
- 원인: 2026-05-01 에 fallback 평문 때문에 .gitignore 한 뒤 2026-08-12 에 비밀값은 제거했지만 ignore 는 남아 있었다. 새 검사를 설계하면서 `git ls-files` 로 추적 여부를 확인하지 않았다.
- 수정: 비밀값 0 확인(기본값 없음 · 토큰성 문자열은 vault 경로 문자열 3개뿐) 뒤 .gitignore 항목 제거·추적. `test_vault_check_no_secret_output.py` 가 미출력을 강제한다.
- 재발 방지: CI 에서 실행할 저장소 파일은 `git ls-files <path>` 로 추적을 확인한 뒤 Jenkinsfile 에 적는다.
- 관련 rule: rule 80 R1-C

## 2026-10-04 — 설계대로 재전파된 interruption 을 Harness 가 자기 것으로 받지 않아 빌드가 ABORTED (Harness #105/#106)

- 카테고리: scope-miss
- 발견 위치: `tests/jenkins/harness/Jenkinsfile_harness` ⑦ (`expectInterruption` 에 bounded 시나리오 누락)
- 증상: BOUNDED=true 시나리오에서 승인 부재 → finalizer 재전파 → Harness 도 다시 던짐 → ABORTED, 판정 artifact 없음.
- 원인: "우리가 만든 interruption 만 삼킨다" 규칙에서 "승인 없는 bounded 는 설계상 재전파가 기대값" 인 경우를 빠뜨렸다.
- 수정: bounded 시나리오를 expectInterruption 에 포함 → verdict 가 PARTIAL/승인 으로 기록.
- 재발 방지: 시나리오 정본(scenarios.json)에 "기대 종료 방식" 을 적고 Harness 가 그것으로 분기한다.
- 관련 rule: rule 24 R2

## 2026-10-04 — 파라미터 정의를 바꾼 첫 CI 빌드는 이전 기본값으로 돈다 (Harness 16 중 12 만 실행)

- 카테고리: scope-miss
- 발견 위치: CI #10 Harness Driver — `HARNESS_SCENARIOS` 가 종전 12 개 기본값
- 증상: 새 시나리오 4건이 돌지 않아 승격 조건(recover_slow) 이 "no evidence".
- 원인: Declarative `parameters{}` 변경은 그 빌드가 끝난 뒤 Job 정의에 반영된다 — 트리거 시점의 기본값은 이전 정의다.
- 수정: 파라미터 정의를 바꾼 직후의 빌드는 값을 **명시**해 트리거한다.
- 관련 rule: rule 80 R1-C

## 2026-10-04 — "Kernel 6.x DIMM" 제보의 실제 원인은 dmidecode 3.6 의 IEC 단위 (external-contract-drift)

- 카테고리: external-contract-drift
- 발견 위치: main #11/#20(`10.100.64.37/.38`, RHEL 10.2 · kernel 6.12.0-211) — raw_head `Size: 4 GiB`
- 증상: dmidecode rc 0 · stderr 없음 · Type 17 레코드 128개인데 SLOT 0 · `MEM_PHYS_MB=0` → os_visible fallback + 경고 1건.
- 원인: dmidecode 3.6 이 Size 단위를 IEC 접두어로 바꿨고 파서는 `kb/mb/gb/tb` 만 환산했다. 제보가 "kernel 6.x" 로 붙은 것은 RHEL 10(kernel 6.12)이 dmidecode 3.6 을 처음 싣기 때문 — kernel 6.8 Ubuntu(dmidecode 3.5)는 정상이었다.
- 영향: dmidecode ≥ 3.6 을 쓰는 모든 Linux 대상의 DIMM 상세·물리 총량 누락.
- 수정: 두 단위 환산에 `tib/gib/mib/kib` 추가 + 3.6 형태 캡처 regression. 원인 확보 방법: SSH 가 막혀 collector 가 SLOT 0 일 때 raw 식별 줄을 detail 에 남기게 해(X3) 승인된 수집 경로로 원본을 받았다.
- 재발 방지: 외부 도구 출력 단위를 파싱할 때 **알 수 없는 단위는 0 이 아니라 marker(`MEM_RAW|`)로 드러나게** 한다(이번 marker 유지). 새 OS 메이저(RHEL 10 등)가 lab 에 들어오면 dmidecode/lsblk 등 도구 버전과 출력 캡처를 `tests/reference/os/` 에 추가한다(rule 96 R1-A).
- 관련 rule: rule 96 R4 · rule 95 R1 #11

## 2026-10-05 — 원인 서술 정정: IEC 단위는 "dmidecode 3.6" 이 아니라 그 뒤의 upstream 커밋 (external-contract-drift 보정)

- 카테고리: external-contract-unverified
- 발견 위치: 위 2026-10-04 항목 "실제 원인은 dmidecode 3.6 의 IEC 단위" — Kernel 6.x 항목별 행렬 검토(`tests/evidence/2026-10-04-kernel6x-compat-matrix.md`) 중 저장소 RHEL 9.6 캡처(`# dmidecode 3.6`, `Size: 8 GB`)와 충돌
- 증상: 문서가 "dmidecode ≥ 3.6 이면 IEC" 로 일반화했다 — RHEL 9.6 의 3.6 은 SI 표기다.
- 원인: RHEL 10.2 raw_head 에는 버전 헤더가 없었는데 Runner(RHEL 9.6) 의 dmidecode 3.6 사실과 섞어 버전을 귀속했다. upstream 출처를 확인하지 않았다.
- 수정: upstream 로그로 확인 — "dmidecode: Use binary unit prefixes"(2025-04-24, 3.6 릴리스 이후). EXTERNAL_CONTRACTS 정정. 파서 수정(두 단위계 환산)과 DIMM 결론은 불변.
- 재발 방지: 외부 도구 출력 변화의 원인을 버전에 귀속할 때는 **대상 host 의 버전 헤더 원문**과 upstream 변경 이력을 같이 남긴다(rule 96 R1-A).
- 관련 rule: rule 96 R1-A · R4 · rule 25 R7-B

## 2026-10-05 — root 로 캡처한 fixture 가 비루트 수집의 권한 실패를 가렸다 (driver_map[].vlan_id 항상 null, GP-23)

- 카테고리: scope-miss
- 발견 위치: production #88(P2) `.96` `bond0.64`/`bond0.656` · `.95` `bond0.64` — `interfaces[].vlan_id` 64/656/64, `driver_map[].vlan_id` null (Kernel 6.x 행렬 O-1)
- 증상: 5a60d420 의 파싱 수정은 회귀 테스트(root 캡처 `/proc/net/vlan/bond0.64`)를 통과했지만 실수집에서는 여전히 null.
- 원인: 커널이 `/proc/net/vlan/<if>` 를 0600(root 전용)으로 만들고 network raw 는 become 없이(비루트 수집 계정) 돈다 — 파일은 있는데(-f 참) 읽기가 실패한다. fixture 는 root 로 캡처돼 그 조건을 재현하지 않았다.
- 수정: proc 읽기가 비면 VLAN 장치(proc 항목 또는 uevent DEVTYPE=vlan)에 한해 `ip -d link show dev <if>`(netlink, 권한 불필요 — interfaces[].vlan_id 와 같은 근거). become 추가 없음. 회귀 4건(비루트 재현은 Linux 에서 chmod 0 으로 — WSL uid 1000 실행 PASS).
- 재발 방지: 원격 파일을 읽는 수집은 **수집 계정 권한**으로 재현하는 테스트를 둔다(root 캡처 fixture 만으로 닫지 않는다). 실장비 확인 항목(GP-23)은 실제 VLAN 장치가 있는 host 의 envelope 로 닫는다.
- 관련 rule: rule 95 R1 · rule 25 R7-A-1

## 2026-10-05 — Windows 작업 PC 의 core.autocrlf 가 `git archive` export 를 CRLF 로 바꿔 G18 이 로컬에서만 FAIL (GP-45)

- 카테고리: environment-drift
- 발견 위치: X3 실 승격 1차 시도(세션 CLI) — drift A1(기록된 생성기 재실행): "manifest: CRLF line endings are not allowed"
- 증상: CI(Linux) 의 G18 은 PASS, 같은 SHA 의 로컬(Windows, autocrlf=true) 승격에서만 FAIL → 거부(원격 변경 0, ls-remote 확인).
- 원인: `git archive` 는 checkout 처럼 core.autocrlf/eol 변환을 적용한다. index 의 blob 은 LF.
- 수정: `drift.export_tar()` 가 `-c core.autocrlf=false -c core.eol=lf` 로 blob 그대로 내보낸다 + tmp repo(autocrlf=true) 회귀.
- 재발 방지: 생성기·검증기가 git 에서 파일을 꺼낼 때는 object store(cat-file/ls-tree) 또는 변환 없는 export 만 쓴다. Windows 세션 승격은 이 회귀가 지킨다.
- 관련 rule: rule 92 R3

## 2026-10-05 — 저장소 메타를 읽는 새 테스트에 `source_text` 표식이 없어 G14(production tree overlay) FAIL (CI #17)

- 카테고리: scope-miss
- 발견 위치: CI #17 Prodgen Verify — `tests/unit/test_perf_observe_tools.py` 가 `jenkins/jobs/*/config.xml` 을 읽음(production tree 에 없음)
- 증상: 로컬 pytest 는 PASS, G14(생성 tree 위 tests overlay, `-m "not source_text"`) 에서만 1 failed → COMPLETE_PASS 실패.
- 원인: 새 계약 테스트를 만들며 overlay 제외 표식 규칙(pytest.ini `source_text`)을 적용하지 않았다.
- 수정: 모듈 단위 `pytestmark = pytest.mark.source_text`(X3). 이후 새 진단 Job 계약 테스트(`test_term_probe_contract.py`)도 같은 표식.
- 재발 방지: `jenkins/` · `tests/jenkins/` · `.claude/` · `docs/` · `scripts/ai/` 를 읽는 테스트는 작성 시 `source_text` 를 붙인다 — 로컬에서 `-m "not source_text"` 와 production tree overlay 를 함께 돌려 본다.
- 관련 rule: rule 24 R1 · rule 40 R6

## 2026-10-05 — 전역 ansible.cfg 설정(unparsed_is_failed)이 운영 밖 실행까지 실패시켰고, 로컬 확인이 그 설정을 읽지 않았다 (CI #21)

- 카테고리: scope-miss · environment-drift
- 발견 위치: CI #21 Gate(`ci_gate.sh` 의 `--syntax-check -i localhost,` rc 1) · Prodgen Verify G15(모듈 smoke "No inventory was parsed")
- 증상: F03 의 `[inventory] unparsed_is_failed = True` 를 ansible.cfg 에 넣었더니 목록 · ini 인벤토리나 인벤토리 없는 ad-hoc 실행이 전부 실패했다. 로컬 WSL syntax-check 는 PASS 였다.
- 원인: ① 설정 범위를 운영 경로(Jenkins 수집, 항상 inventory 스크립트)만 보고 정했다 — 진단용 ad-hoc 명령 · 시험 도구(term-probe) · 승격 게이트도 같은 cfg 를 읽는다. ② WSL 의 `/mnt/c` 는 world-writable 이라 ansible 이 저장소 ansible.cfg 를 **무시**한다 — `ci_gate.sh` 처럼 `ANSIBLE_CONFIG` 를 고정하지 않은 로컬 확인은 다른 설정으로 돌았다.
- 수정: 설정을 ansible.cfg 에서 빼고 Jenkins 수집 실행에만 `ANSIBLE_INVENTORY_UNPARSED_FAILED=True`(`6f83cb33`). `ci_gate.sh` syntax-check 는 G11 처럼 채널 inventory.sh 로(`a25405be`).
- 재발 방지: 동작을 바꾸는 ansible.cfg 항목은 "이 cfg 를 읽는 모든 실행"(수집 · ad-hoc · 시험 도구 · 게이트)을 나열해 확인한다. WSL 에서 저장소 설정으로 확인할 때는 `ANSIBLE_CONFIG=$PWD/ansible.cfg` 를 붙인다.
- 관련 rule: rule 92 R3 · rule 24 R1

## 2026-10-05 — CI 실행 중 main 에 push 해 Harness 22건이 SHA 불일치로 스스로 멈췄다 (CI #21)

- 카테고리: process
- 발견 위치: CI #21 Harness Driver · bounded · prodtree — `ERROR: [Harness] MAIN_SHA <X10> != checkout <X11>`
- 증상: Gate 실패를 고친 커밋을 CI 가 도는 중에 push → 이후 Harness 빌드가 main 최신을 받아 후보 SHA 와 달라졌다(설계된 보호가 동작). 그 전 12건은 PASS.
- 원인: CI 는 시작 시점의 main SHA 를 후보로 고정하고, Harness Job 은 빌드마다 main 최신을 checkout 한다. 진행 중 push 는 후보와 다른 코드를 시험하게 만든다.
- 수정: CI #22 가 끝날 때까지 main push 를 멈췄다.
- 재발 방지: CI(Harness 포함)가 도는 동안 main 에 push 하지 않는다 — 고칠 것은 로컬 커밋으로 모아 CI 가 끝난 뒤 새 후보로 올린다.
- 관련 rule: rule 93 R4

## 2026-10-05 — production tree 에 없는 파일을 읽는 새 시험에 `source_text` 를 빠뜨렸다 (G14, CI #17 과 같은 유형의 재발)

- 카테고리: scope-miss (재발)
- 발견 위치: CI #21 Prodgen Verify G14 — `test_env_guard.py::test_guard_is_shipped_in_the_production_tree` · `test_gather_watch.py::test_watch_is_shipped_in_the_production_tree` 가 `production_manifest.yml`(main 전용)을 읽음
- 증상: 로컬 pytest PASS, 생성 tree overlay 에서만 2 failed.
- 원인: CI #17 기록의 재발 방지("로컬에서 production tree overlay 를 함께 돌려 본다")를 이번 커밋 전에 하지 않았다.
- 수정: 두 시험에 `@pytest.mark.source_text`(`6f83cb33`). 이후 `prodgen build` + `verify --only G14,G15` 를 로컬에서 먼저 돌려 PASS 확인 뒤 push(X12).
- 재발 방지: 새 시험이 `production_manifest.yml` · `jenkins/` · `docs/` · `scripts/ai/` · `Jenkinsfile_ci` 를 읽으면 `source_text`. CI 에 올리기 전 로컬 `prodgen verify --only G14,G15`.
- 관련 rule: rule 24 R1 · rule 40 R6

## 2026-10-05 — Windows 에서 자식 Python 의 한국어 출력이 cp949 로 나와 UTF-8 로 읽는 시험이 깨졌다

- 카테고리: environment-drift
- 발견 위치: 로컬 prodgen G14 overlay(Windows) — `test_input_acceptance_parity.py` 69 failed (`UnicodeDecodeError ... 0xc0`). 반대로 `PYTHONIOENCODING=utf-8` 을 붙인 로컬 전체 실행에서는 `test_cli_exit_codes` 1건이 같은 이유로 실패.
- 원인: 파이프로 연결된 자식 Python 의 출력 인코딩은 Windows 에서 로캘(cp949)이다. 시험은 UTF-8 로 읽는다. 리눅스 CI 는 UTF-8 이라 드러나지 않는다.
- 수정: 시험이 자식 환경에 `PYTHONIOENCODING=utf-8` 을 명시(`b33e278d`).
- 재발 방지: 자식 프로세스의 한국어 출력을 읽는 시험은 자식의 출력 인코딩을 명시한다. 로컬 실행에 `PYTHONIOENCODING` 을 덧붙여 결과를 바꾸지 않는다(덧붙였다면 결과 해석에 적는다).
- 관련 rule: rule 40 R6

## 2026-10-05 — 가짜 cmdlet 이 종료 오류만 내서, 실제 CIM 실패(비종료 오류)를 구성요소 try/catch 가 못 잡는다는 것을 시험이 놓쳤다

- 카테고리: test-fidelity · ai-hallucination(전제 미확인)
- 발견 위치: §5 감사 C-3 · C-6 수정 중(X13) — `os-gather/tasks/windows/gather_system.yml` · `gather_storage.yml` 의 공용 조회 `read_operating_system` · `read_computer_system` · `read_disk_drives`
- 증상: 구성요소 실패를 errors[] 로 옮기는 수정과 시험(가짜 `Get-CimInstance` 가 `ThrowTerminatingError`)이 모두 통과했지만, 실제 `Get-CimInstance` 실패(잘못된 클래스 · 네임스페이스)는 비종료 오류라 `try` 로 잡히지 않고 결과 0건 · 구성요소 `ok=true` 로 남는다(이 PC 의 Windows PowerShell 5.1 실측). 수정이 실환경 실패에서는 발동하지 않았을 것이다.
- 원인: P4 통합 하네스의 가짜 cmdlet 은 "실제 cmdlet 처럼" 문장 종료 오류를 낸다고 가정했다. CIM cmdlet 은 기본이 비종료 오류다. 가짜의 실패 방식을 실제와 대조하지 않았다.
- 수정: 공용 조회 3개가 `-ErrorAction SilentlyContinue -ErrorVariable seErr` 로 받아 결과는 그대로 두고 `if ($seErr) { throw $seErr[0] }` 로 구성요소만 실패 표시. 시험에 비종료 오류를 내는 가짜(`Write-Error`)와 "실제 CIM 실패는 try 로 안 잡힌다" 전제 시험을 추가(`tests/unit/test_windows_hidden_failures.py`), 변이 검사로 확인.
- 재발 방지: 실패 경로를 가짜 cmdlet 으로 시험할 때는 실제 cmdlet 의 오류 종류(종료 / 비종료)를 먼저 실측하고, 가짜가 같은 종류를 내게 한다. memory · network 공용 조회의 실패 검사도 같은 이유로 발동하지 않는다(현재는 다른 경로로 실패가 드러나는 A 분류).
- 관련 rule: rule 95 R1 · R3

## 2026-10-05 — 스크립트 끝에 문장을 추가하자 PowerShell 종료 코드가 바뀌어 "명령 부재 → 미지원"(F23) 분류가 깨질 뻔했다

- 카테고리: regression(사전 발견)
- 발견 위치: §5 감사 C-1 수정(X13) — `os-gather/tasks/windows/gather_users.yml`, 실제 powershell.exe 대조
- 증상: 실패 표식 줄을 스크립트 끝에 출력하도록 바꾸자, 명령이 없을 때(Get-LocalUser · Get-CimInstance 부재) 종료 코드가 1 → 0 으로 바뀌어 users 가 "미지원" 대신 "성공 + 빈 목록"이 됐다.
- 원인: `powershell.exe -EncodedCommand` 의 종료 코드는 마지막 문장의 성공 여부(`$?`)로 정해진다. 종전 스크립트는 빈 catch 가 마지막 문장이라 1 이었고, 분류(F23)가 그 종료 코드에 기대고 있었다.
- 수정: 명령 부재(CommandNotFoundException)만 표식 대신 `exit 1` 로 끝내 종전 분류를 지켰다. 시험이 종전 · 새 스크립트의 종료 코드를 시나리오별로 비교한다.
- 재발 방지: win_shell 스크립트의 마지막 문장을 바꿀 때는 종료 코드에 기대는 분류(`rc != 0`)가 있는지 찾고, 실제 powershell.exe 로 종전 · 새 종료 코드를 대조한다.
- 관련 rule: rule 95 R1 · rule 92 R2

## 2026-10-05 — 기능을 없앤 뒤 다른 시험 파일이 그 기능을 계속 기대했다 (8차 R3)

- 카테고리: scope-miss
- 발견 위치: 8차 로컬 전체 회귀(묶음 실행) — Redfish 모듈 마감(`_set_deadline`) · Add-on 태스크별 제한(`apply: timeout`) · `df` 20초 · 포트 재시도 간격 1초를 없앤 뒤
  `tests/integration/emulator_harness.py` · `test_redfish_phase3_contracts.py` · `test_dell_service_tag_serial.py`(같은 하네스 사용) · `test_addon_hook_contract.py` ·
  `test_addon_hook_playbook.py` · `test_linux_storage_markers.py` · `test_os_precheck_polling.py` · `test_redfish_redirect_boundary.py` · `test_windows_call_consolidation_static.py` 가 실패(합 50건 남짓)
- 원인: 없앤 이름을 바꾼 파일과 그 파일 전용 시험에서만 찾았다. 같은 함수를 부르는 시험 도구(emulator 하네스)와 다른 계약을 고정하던 시험은 전체 실행에서야 드러났다.
- 수정: 각 시험을 새 계약(작업 단위 제한 없음 · 연결 60초/응답 대기 · 포트당 1회)으로 바꿨다. Add-on 은 "오래 걸려도 기다린다" 와 "실행 한계가 멈추면 CHECKPOINT 로 복원" 두 실제 ansible 시험으로.
- 재발 방지: 기능 · 변수 · 함수를 없애면 그 이름을 `tests/` 전체와 시험 도구(`tests/integration/*harness*`, `tests/jenkins/`)에서 먼저 찾고, 커밋 전에 전체 회귀를 한 번 돌린다(메모리가 부족하면 묶음으로).
- 관련 rule: rule 24 R1 · rule 92 R3

## 2026-10-05 — 회귀를 백그라운드로 돌리는 동안 파일을 고쳐 가짜 실패 6건이 났다

- 카테고리: process
- 발견 위치: 8차 Windows `ci_gate.sh` 전체 실행(16분) 중 `redfish-gather/site.yml` 의 기술 근거 문구(`task_timeout` → `task_stopped`)와 그 시험을 함께 고침
- 증상: `test_redfish_timeout_auth_classification.py` 6 failed — 수집 시점의 시험 코드(종전 문구)가 실행 시점의 새 site.yml 을 읽었다(실패 표시는 새 시험 줄을 보여 혼동).
- 수정: 고친 뒤 그 시험만 다시 돌려 22 passed, 커밋 전 WSL 전체 회귀를 새로 돌려 확인했다.
- 재발 방지: 회귀가 도는 동안 저장소를 고치지 않는다. 고쳤다면 그 실행의 결과를 판정에 쓰지 않고 다시 돌린다.
- 관련 rule: rule 24 R2

## 2026-10-05 — 시험용 PowerShell 명령줄이 32,767 자 한도를 넘었다

- 카테고리: test-fidelity
- 발견 위치: 8차 R5 — Windows network 시험(가짜 cmdlet 머리말 + fixture JSON + 운영 스크립트를 `-EncodedCommand` 하나로)
- 원인: 운영 스크립트는 한도 안(가장 긴 storage 약 24,000)인데 시험이 fixture JSON 을 명령줄에 넣었다.
- 수정: fixture 는 환경변수(`SE_TEST_FIXTURE`)로 넘긴다 — 명령줄에는 운영과 같은 스크립트와 가짜 cmdlet 만.
- 재발 방지: 시험 하네스가 운영 명령에 덧붙이는 것은 운영 한도를 함께 써 버린다. 큰 입력은 파일 · 환경변수로 넘긴다.
- 관련 rule: rule 40 R6

## 2026-10-05 — 이 Bash 도구의 heredoc 이 `\\` 를 `\` 로 줄였다

- 카테고리: tooling
- 발견 위치: 8차 — Python 패치 스크립트를 `python - <<'EOF'` 로 넘겼는데 문자열 안의 `\\n` 이 실제 줄바꿈이 돼 시험 파일이 깨졌다(`test_time_limits.py` · `test_jenkinsfile_portal_finalize.py`). `sed` 의 치환 문자열 `\n` 도 줄바꿈이 됐다.
- 수정: 역슬래시가 든 패치는 파일로 쓴 스크립트(Write)로 실행했다. 깨진 줄은 같은 방식으로 되돌렸다.
- 재발 방지: 역슬래시가 하나라도 든 수정은 heredoc · sed 로 넘기지 않는다. 고친 뒤 그 파일을 import/parse 해 본다.
- 관련 rule: rule 24 R1

## 2026-10-06 — main 전용 파일을 읽는 새 시험의 `source_text` 표식 누락이 재발했다 (CI #24 G14)

- 카테고리: repeat
- 발견 위치: 8차 CI #24(`85630d2c`) Prodgen Verify G14 — `test_workspace_cleanup.py::test_pipeline_wires_the_cleanup_and_records_ownership`(`production_manifest.yml`) · `test_harness_tools.py::test_harness_pipeline_has_no_tier2_and_runs_the_real_run_gather`(`jenkins/jobs/…/config.xml`)
- 원인: 7차 항목(로컬에서 생성 tree G14 를 먼저 돌린다)을 새 시험 두 건에 적용하지 않고 push 했다. 두 시험 모두 production tree 에 없는 파일을 읽는다.
- 수정: `@pytest.mark.source_text` 표식(`8c9e04a9`) 뒤 로컬 `prodgen build` + `verify --only G14,G15` 통과를 확인하고 push → CI #25 COMPLETE_PASS.
- 재발 방지: 새 시험이 `production_manifest.yml` · `jenkins/` · `.claude/` · `docs/ai/` · `scripts/ai/` 를 읽으면 표식부터 단다. push 전 로컬 G14 를 생략하지 않는다(시간이 들어도 CI 한 바퀴보다 짧다).
- 관련 rule: rule 24 R1 · rule 93 R2

## 2026-10-06 — PROJECT_MAP 지문을 새 파일을 index 에 넣기 전에 갱신했다

- 카테고리: harness
- 발견 위치: 8차 세션 시작 훅의 drift 경고(tests `ae2fdd35a8e5` → `dbc2a88b4399`). `85630d2c` 가 커밋한 값이 `85630d2c` 를 포함해 그 뒤 어느 커밋의 추적 파일 목록과도 맞지 않았다.
- 원인: 지문은 git index 기준이다(`git ls-files -s`). 512개 조합을 대조한 결과 저장된 값은 "삭제한 시험 3개는 `git rm` 했고 새 시험 6개는 아직 `git add` 하지 않은" index 와 정확히 일치했다 — `--update` 를 새 파일을 넣기 전에 돌리고 그 값을 그대로 커밋했다.
- 수정: 8차 문서 커밋에서 `check_project_map_drift.py --update` 를 다시 돌려 커밋된 tree 와 같은 값(`dbc2a88b4399`)으로 맞췄다.
- 재발 방지: `--update` 는 변경 파일을 모두 index 에 넣은 뒤(커밋 직전)에 돌린다. 커밋 뒤 `check_project_map_drift.py`(update 없이)가 drift 0 인지 확인한다.
- 관련 rule: rule 70 R2
