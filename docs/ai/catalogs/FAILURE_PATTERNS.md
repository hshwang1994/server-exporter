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
