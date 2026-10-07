# TEST_HISTORY — server-exporter

## 2026-10-07 (최종 마무리) — 로그 보관 전역화 · forks 50 · Windows vault 도메인 · Portal 재진입 4.1/4.2 · GP-64

| 구분 | 결과 |
|---|---|
| 로컬 | WSL `ci_gate`(오프라인 gate) — python compile · field_dictionary 정합 · output schema drift · vendor/harness 일관성 · finalize corpus · pytest(unit·e2e·regression) **4,516 통과 · 145 건너뜀 · 7 xfail** · integration · 3채널 `ansible-playbook --syntax-check`. 영향 단위 시험 별도 실행 PASS(`test_jenkinsfile_portal_finalize` · `test_jenkinsfile_ci` · `test_time_limits` · `test_gather_state` · `test_harness_tools` · `test_finalize_corpus` · prodgen `test_verdict_evidence`) |
| 새 시험 | `test_gather_state.py::test_worker_fork_oom_is_not_this_runs_oom_gp64`(지시 6 — 작업자 fork OOM 은 link 안 됨 · rc=1 은 failed_run · 137+작업자 PID 는 process_lost) · `test_jenkinsfile_portal_finalize`(4.1 refused 유지·재진입 미전송 · 4.2 interrupted→uncertain) · Harness 시나리오 `finalize_refused_no_resend`(확정 거부 HTTP 400 뒤 재진입 재전송 0 · sink 1회) — scenarios.json · build_functions.SCENARIOS · Jenkinsfile_ci · prodgen REQUIRED_HARNESS 동기 |
| 항목별 | 1 buildDiscarder 제거(portal·ci) · 2 `ansible.cfg` forks 200→50 · 3 Windows vault 재암호화(yi·ic·cj secondary username, 비밀 fingerprint `14465ae6…` 불변 확인) · 4 seCallback refused/receipt · 6 GP-64 한계 확인 |
| 미수행(자격 부재) | **이 세션 Jenkins 인증 netrc 없음** → CI 실행 · production 승격·canary · production 실환경 재검증 · GP-57 실장비 미수행(우회 안 함). Jenkins controller 는 닿음(HTTP 200). main 양 원격 push, production P7 `61b9dd4a` 유지 |

## 2026-10-07 (10차) — 결과 처리 재진입 · 기록 읽기 · 끊긴 준비 · OOM 귀속 · `fa05d122` → production P7 `61b9dd4a`

| 구분 | 결과 |
|---|---|
| 로컬 | WSL `ci_gate` PASS — unit · e2e · regression **4,476 통과** · 182 건너뜀 · 7 xfail · integration **324** · corpus 20/20 · 3채널 syntax-check. 커밋마다(`88c9250a` · `574454f5` · `dcd89274`) 회귀 통과(줄끝 4건은 내보내기 CRLF — LF 로 다시 확인). Groovy 문법 · 로컬 driver R1~R4 15/15 |
| 새 시험 | `test_gather_state.py` 반례(다른 프로세스 OOM + rc 1 · `kill -9` · 사용자 취소 · 시도 시작 뒤 들어온 프로세스 · 이 실행의 OOM + 신호 · 커널 로그 시계 지연) · `test_run_gather.py`(PID 기록 · rc 92) · 구조 시험 · Harness 21 시나리오(재진입 5 · 읽기 2 · 준비 5 · 보존 6 · Add-on 3) |
| se-probe 실기 | L3 #1 · L4 #2 · L5 #3 · L6 #4 · L8 #5 기대 동작(대기는 감지 시각부터) · **L9 #6** Add-on A 재사용 3/3 · **R6** #7~#10(Linux 15 s 회복 · 600 s 그 대상만 실패 · Windows 8 s 회복 · 20 s 대상 쪽 연결 종료로 그 대상만 실패 · Redfish 20 s 회복 · 600 s partial) |
| Runner03 OOM | 실제 커널 OOM 6사례 — 고치기 전 이 실행의 OOM 2건 `aborted`(커널 로그 시계 결함) → `f9f38cea` 뒤 `runner_oom` · 반례 4건 기대대로 |
| CI | #31 중단(실행 중 push) · **#32(`5dc8d0af`) UNSTABLE** — Gate PASS(4,515 + 324) · Harness main 42/43 · tree 21/21 · Verify COMPLETE_PASS(G14 4,288 · G19) · 고친 시나리오 단일 실행 #762 · #764 PASS · **최종 CI #33(`fa05d122`) SUCCESS** — Gate 4,515 + 324 · Harness main 44/44 · tree 21/21 · Verify COMPLETE_PASS(G14 4,288 · G19) · Evidence PASS · 필수 stage 전부 PASS |
| main `fa05d122` #327~#344 | 17/17 기대 결과(T2 SUCCESS · T5 ABORTED · T17 FAILURE config_error 전송 200 · T6 UNSTABLE · S5 2/2(.37 .38 DIMM 1 × 4,096 MB) · S1 4/4 · S4 1/1 · S2 4+2 · E2E-A UNSTABLE · E2E-A2 FAILURE · ESXi 6/6 · E2E-E 2/2 · S3 13/13 · Linux A 8/8 · Linux B 4+3 · Redfish 7+3(#342 는 controller DNS 실패로 시작 전 실패 → #344) · 중복 IP 거부). 명부 32대 성공 26 · 실패 6(9차와 같은 환경 항목) |
| 승격 · production | 세션 CLI 2026-10-07 09:36~09:51 COMPLETE_PASS → **P7 `61b9dd4a`**(parent P6 `a8833d47` · Main-SHA `fa05d122` · Tree-Hash `9816ed3b…` · 196 파일 · 다시 실행 G11~G15 · G18~G20) · GitHub · GitLab production `61b9dd4a` · 승격 뒤 두 원격 새 사본 G07 PASS · production #176 canary 3/3 · #177~#190 매트릭스 · 명부 32대 성공 26 · 실패 6 |

## 2026-10-06 (9차) — 실행 기반 대기 · 같은 Runner 재개 · `8af81613` → production P6 `a8833d47`

| 구분 | 결과 |
|---|---|
| 로컬(`e4bbd2cb`) | WSL `ci_gate` PASS — unit · e2e · regression **4,490 통과** · 145 건너뜀 · 7 xfail · integration **324** · 동치 corpus 20/20 · Windows PowerShell 관련 185 통과 · 3채널 syntax-check · prodgen 로컬 build(195 · class B 0 · tree `e6b06e99…`) · 오프라인 gate PASS |
| 새 시험 | `test_gather_state.py`(43 + Linux) · `test_account_lost_write_response.py` · `test_credential_candidate_stop.py` · `tests/unit/prodgen/test_depclosure_imports.py`(4) · Harness `infra_resume` · `infra_wait_expired` · `resume_impossible` · `gather_wait_abort` · corpus 19 · 20 |
| 실기 se-probe | L1 #7 · L2 #9 · L3 #10 · L4 #11(50대) · L5 #12 · L6 #13/#15 · L8 #14/#16 — 전부 기대 동작(증거 §4). #7~#11 의 FAILURE 는 시험 드라이버 정리 결함(`8beb4e81` 수정) |
| Runner03 OOM 격리 | 64 MiB scope: 고치기 전 `aborted (signal TERM)` → `9ba237a6` 뒤 `runner_oom` · 대조 `kill -9` → `process_lost` |
| CI | #26 · #28 중단(결함 발견 뒤 새 후보) · **#27(`b3bc02dd`) SUCCESS** — Harness 23/23 · 생성 tree 13/13 · Verify COMPLETE_PASS(G14 4,260) · #29(`e4bbd2cb`) SUCCESS(Verify COMPLETE_PASS · tree `e6b06e99…` · G14 4,263) 이나 증거 48항목 중 `gather_wait_abort` #609 판정 FAIL — #27 의 #551 도 같았다(시험 판정기 · CI 집계 결함, `d1e86297`) · **#30(`8af81613`) SUCCESS** — Harness 23/23(판정 PASS) · 생성 tree 13/13 · Verify COMPLETE_PASS(G14 4,264) · Evidence 48/48 |
| main `8beb4e81` #276~#292 · `e4bbd2cb` #293~#309 · `8af81613` #310~#326 | 17/17 × 3 기대 결과(T2 SUCCESS · T5 ABORTED · T17 FAILURE config_error 전송 200 · T6 UNSTABLE · S5 2/2 · S1 4/4 · S4 1/1 · S2 4+2 · E2E-A UNSTABLE · E2E-A2 FAILURE · ESXi 6/6 · E2E-E 2/2 · S3 13/13 · Linux A 8/8 · Linux B 4+3 · Redfish 7+3 · 중복 IP FAILURE) |
| 승격 · production | 세션 CLI 2026-10-06 19:20~19:33 COMPLETE_PASS → **P6 `a8833d47`**(parent P5 `f43af470` · Main-SHA `8af81613` · Tree-Hash `e6b06e99…` · 196 파일 · 다시 실행 G11~G15 · G18~G20) · GitHub · GitLab production `a8833d47` · 승격 뒤 새 사본 G07 PASS(두 원격 동일 · 로컬 tree 와 동일) · production Job #160~#174 15/15 기대 결과 |

## 2026-10-05~06 (8차) — R1~R8 · `8c9e04a9` → production P5 `f43af470`

| 구분 | 결과 |
|---|---|
| 로컬(`8c9e04a9`) | WSL unit · e2e · regression **4,380 통과** · 건너뜀 145(Windows 전용) · xfail 7 · integration(not live) **324 통과** · Windows PowerShell 99 + 71 통과 · `ci_gate`(pytest 제외) PASS · 생성 tree G14 **4,220** · G15 PASS |
| 새 시험 | `test_run_gather.py`(13, Linux) · `test_time_limits.py`(6) · `test_workspace_cleanup.py`(8) · `test_redfish_request_timeouts.py`(5) · Windows 숨은 실패 R5 · Harness `gather_limit_preserve` · Add-on 실제 ansible 2건(오래 걸리는 태스크 대기 · 한계로 멈춘 뒤 CHECKPOINT 복원) |
| R6 실측 | `remote_cleanup_probe.sh` → `.161`: 고치기 전 한계 1 · sudo 3 남음 → 고친 뒤 7 상황 0(WSL 2.20.7 · Runner02 2.20.3) |
| main `85630d2c` #243~#259 | 등록 실행 #243 + 16 빌드 기대 결과 · 첫 정리 Runner01 81 · Runner04 39 · Runner03 38 · Runner02 52 개 삭제 |
| CI #24(`85630d2c`) | FAILURE — Gate PASS(4,378 + 324) · Corpus · Time Limits 39 · Harness main 19/19 · 생성 tree 11/11 · **Verify G14 2 failed**(main 전용 파일을 읽는 새 시험 표식 누락) |
| main `8c9e04a9` #260~#275 | 16/16 기대 결과(T2 SUCCESS · T5 ABORTED · T6 UNSTABLE · S5 2/2 · S1 4/4 · S4 1/1 · S2 4+2 · E2E-A UNSTABLE · E2E-A2 FAILURE · ESXi 6/6 · E2E-E 2/2 · S3 13/13 · Linux A 8/8 · Linux B 4+3 · Redfish 7+3 · 중복 IP FAILURE) |
| CI #25(`8c9e04a9`) | SUCCESS 37분 — Gate PASS(Runner 4,380 + 324 · 3채널 syntax-check) · Corpus 18/18 MATCH · Time Limits Self-test 39 · Harness main 19/19(#498~#516) · 생성 tree 11/11(#517~#527) · Build tree `54cf8028…`(195 파일) · Drift PASS · Verify COMPLETE_PASS(G14 4,166) · Vault PASS · Evidence 42/42 |
| 승격 | 세션 CLI 2026-10-06 09:34~09:50 COMPLETE_PASS → **P5 `f43af470`**(parent P4 `5ac5566c` · Main-SHA `8c9e04a9` · Tree-Hash `54cf8028…` · 196 파일) · 다시 실행한 게이트 G11~G15 · G18~G20(G19 WSL 3채널) · origin accepted · internal 은 공유 push URL 로 도달 · GitHub · GitLab · 로컬 production 일치 |
| production | #144 canary SUCCESS(파라미터 7개 · 보존 14일/100 · 7일/50 등록) · S1 4/4 · S2 4+2 · T2 SUCCESS · T5 ABORTED(전송 200) · T6 UNSTABLE(408 × 3) · S5 2/2 · S3 13/13 · Linux A 8/8 · Linux B 4+3 · Windows 1/1 · ESXi 6/6 · Redfish 7+3(표준 계정 7/7 · 계정 쓰기 0) · 중복 IP FAILURE · Tier 2 해제 뒤 #158 SUCCESS · #159 ABORTED(승인 오류 0) · 첫 정리 production 157개 · 수집 빌드 checkout 전부 `f43af470` |

## 2026-10-05 (7차) — 최종 정비 F01~F13 · §5 예외 무시 감사 · X13 → P4

| 구분 | 결과 |
|---|---|
| 로컬(X13 `1e15bf6f`) | unit · e2e · regression **4,411 통과** · 건너뜀 20 · xfail 7 — PC 메모리 부족으로 한 번에 돌린 실행이 시스템에 의해 중단돼 묶음별로(prodgen 98 · unit 1,719 · 1,374 · Windows 전용 259 · e2e+regression 961) · integration 308 · `ci_gate.sh` 정적 PASS(corpus 18/18) · 3채널 syntax-check rc 0(WSL 2.20.7, 저장소 ansible.cfg) · 로컬 prodgen G14 PASS(생성 tree 위 4,131) · G15 PASS |
| 새 시험 | `tests/unit/test_windows_hidden_failures.py` — users 9 시나리오 실제 powershell.exe(종전 스크립트와 데이터 · 종료 코드 대조), 비종료 CIM 오류 · 전제 시험, 변이 검사 |
| CI #21(X10) | FAILURE — Gate(전역 `unparsed_is_failed`) · G14(`source_text` 누락) · G15 · Harness SHA 불일치(CI 중 push) → X11 · X12 |
| CI #22(X12 `b33e278d`) | SUCCESS — 13 stage · Harness 18/18 · 상한 6/6 · 생성 tree 10/10 · Verify COMPLETE_PASS 20/20(tree `1ad25d58…`) · Evidence 46 direct · Promote dry-run |
| main X12 #187~#198 · X10 추가 #170~#174 | 12 시나리오 기대 결과 일치 · 입력 거부 3종 · Redfish 10 정상 6분 47초 · Linux 15 |
| F07(X12) | perf-observe K=2(#199 · #200) · K=12 혼합(#204~#215): 노드 PSS 합 최대 1.27 GB · MemAvailable 최소 4.68 GB · swap 0 → throttle 미적용. 같은 BMC 4개 동시에서 Cisco partial(상한 1,200 s) |
| 성능 P3 ↔ X12 | 채널별 5회 교대(production #116~#130 · main #216~#230, 30 SUCCESS): OS +1.1 s · ESXi +2.6 s · Redfish −17.3 s(중앙값) — 퇴행 없음 |
| main X13 #231~#242 | 12/12 기대 결과(T2 SUCCESS · T5 ABORTED · T6 UNSTABLE · S5/S1/S4/S2 SUCCESS · E2E-A UNSTABLE · E2E-A2 FAILURE · ESXi/Redfish SUCCESS · S3 UNSTABLE `limit_reason=forced`) · 전부 checkout `1e15bf6f`(E2E-A2 는 수집 단계 없음) · S4 `.120` 오류 0 · users 는 X12 #192 와 동일 · SCM tip 전후 `1e15bf6f` |
| CI #23(X13) | SUCCESS(37분 52초) — Gate(Runner pytest 4,297 + integration 323 · 3채널 syntax-check) · Corpus 18/18 ×2 · Harness main 18/18(#431~#448) · 상한 6/6(#449~#454) · 생성 tree 10/10(#455~#464) · Verify COMPLETE_PASS 20/20 · tree `1c16ca55…` · VAULT_DECRYPT · Evidence 46 direct · Promote dry-run(부모 P3, require_bounded cli+ci) |
| 승격 P4 | 세션 CLI 1회(20:06~20:19) **COMPLETE_PASS → P4 `5ac5566c`**(parent P3): Gates-Rerun G11~G15 G18~G20(G19 WSL 3채널 실제 실행) · Reused G01~G10 G16 G17 · origin "accepted by remote" · internal "already at the new commit" · 양 원격 · 로컬 동일 · 개발 경로 0 · vault 사본 삭제 |
| production P4 | #131~#142: canary SUCCESS 3/3 → S1 4/4 · S2 4+2 · T2 · Linux A 8/8 · Linux B 4+3(명부) · Windows 1/1 · ESXi 6/6 · Redfish 10 7+3(명부) SUCCESS, T6 UNSTABLE(408 ×3) · S3 UNSTABLE(`limit_reason=forced`) · 중복 IP FAILURE(입력 거부) — 전부 checkout `5ac5566c` |

## 2026-10-05 (6차) — Tier 2 승인 완료 · 사내 Jenkins 상한 모드 적용 · 적용 뒤 검증

| 구분 | 결과 |
|---|---|
| Script Approval(읽기 전용) | 4 서명 승인 · 대기 0 |
| bounded Harness #318~#322(main `031a15e6`) | 5/5 PASS — `inner_recover_timeout`(archive 회수) · `inner_assemble_timeout`(최소 경로) · `inner_archive_timeout`(stash 계속 · workspace 보존) · `inner_stash_timeout`(unarchive 회수) · `inner_layer_a_read_timeout`(최소 경로), 재전파 0 |
| 단계 시간 실측(기본 모드 production #99 · #103) | archive 0.45/0.55 s · stash 0.25/0.14 s · unstash 0.23/0.21 s · 조립 경로 약 0.8 s |
| production P3 #105~#115(상한 모드) | 11 빌드 전부 checkout == P3 · 기대 결과 일치(T6 · S3 UNSTABLE 기대) · 빌드마다 30 s ×3 · 60 s ×1 · 초과 0 |
| main X5 `27f7f4f1` #134~#145(상한 모드) | 12/12 기대 결과(T5 ABORTED · T6/E2E-A/S3 UNSTABLE · E2E-A2 FAILURE) · 상한 표시 3·1(#142 는 2·1 — Gather 없음) · 초과 0 · Layer B 경로 4.96 s(#142) |
| 로컬(X5) | CI 계약 34 passed · prodgen 95 passed · `ci_gate.sh` pytest 4112 passed / 37 skipped / 7 xfailed · 통합 308 passed — PARTIAL(Windows syntax-check 건너뜀) |
| CI #20(X5, PROMOTE dry-run, REQUIRE_BOUNDED 미등록 → 기본 true) | SUCCESS · 필수 stage PASS(HARNESS_BOUNDED 포함) · Harness 18/18 · bounded 5/5 · tree 10/10 · COMPLETE_PASS 20/20 · tree_hash `fd93e76b…`(P3 동일) · E2E 45 direct · Promote dry-run ok(require_bounded=true) |

## 2026-10-05 (5차) — 남은 실행 검증 · GP-23 수정 · X4 → P3

| 구분 | 결과 |
|---|---|
| 로컬 단위(GP-23 수정 후) | `tests/unit` + e2e + regression **4017 passed** · 37 skipped · 7 xfailed; `test_linux_hba_ib_markers.py` 17 passed(WSL uid 1000 — 비루트 재현 포함) · prodgen 94 passed(drift CRLF 회귀 포함) |
| term-probe #1(Runner03) · #2(Runner01) | A 태스크 timeout rc 2 · 자식 1 잔존→정리 0 / B INT rc 124 / C1 rc 124 / C2 rc 137 · Add-on hook 통합 14 passed ×2 |
| main #121(GP-23 실장비) | `.96` bond0.64=64 · bond0.656=656, `.95` bond0.64=64 (driver_map == interfaces), `.161` 대조 빈 값 |
| main X4 `17843cf0` 12 시나리오 | 12/12 계약 PASS(#122~#133: T2 SUCCESS · T5 ABORTED · T6 UNSTABLE · S5/S1/S4/S2 SUCCESS · E2E-A UNSTABLE · E2E-A2 FAILURE · E2E-D/E SUCCESS · S3 UNSTABLE kept 6 · filled 1 — 기대값) · SCM tip 전후 `17843cf0` 동일 |
| CI #19(X4, PROMOTE dry-run) | SUCCESS — 12 stage PASS(bounded PARTIAL) · Harness main 18/18 · 생성 tree 10/10 · Verify COMPLETE_PASS 20/20(tree `fd93e76b…`) · VAULT_DECRYPT PASS · Evidence PASS(main 12 항목 전부 `binding=direct` — 11 BuildData + E2E-A2 `tip_frozen:ls-remote`, `[Trusted]` 전부 utf-8 일치) · Promote DRY_RUN `e2e ok, problems []` · parent P2 `07ecf7ac` |
| 실 승격 P3 | 세션 CLI 1회(02:59~03:10, **autocrlf=true 그대로** — GP-45 수정 효과) **COMPLETE_PASS → P3 `915dec4e`**: Gates-Rerun G11 G12 G13 G14 G15 G18 G19 G20(G19 WSL 3채널 실제 실행) · Gates-Reused G01~G10 G16 G17 · publish origin "accepted by remote" · internal "already at the new commit (reached via a shared push URL)" · 로컬 ref 갱신 · 193 파일 · 개발 경로 0 · P2 대비 runtime 차이 `os-gather/tasks/linux/gather_network.yml` 1 파일 · trailer Main-SHA `17843cf0` · Tree-Hash `fd93e76b…` · Previous-Production `07ecf7ac` · CI-Build #19 · Verdict COMPLETE_PASS · CI-Stages verified. vault 암호 파일은 실행 동안만 존재(래퍼가 삭제 확인) |
| production Job(P3) | production Job(P3 `915dec4e`, 11 빌드 #94~#104): 전부 checkout == P3 · 기대 결과 전부 일치(CAN-1/S1/S2/T2/Linux 15/Windows/ESXi 6/Redfish 10 SUCCESS, T6·S3 UNSTABLE 기대) — main 과 동일한 결과 |

## 2026-10-04 (4차) — 최종 실행 지시 대응 (timeout 상한 범위 · readTrusted 식별 · 증거 직접/추정 · Runner 자원 실측 · 자산 진단 · X2 → P2)

| 구분 | 결과 |
|---|---|
| 로컬 단위(Phase A, `def22479`) | `tests/unit` + e2e + regression **4011 passed · 36 skipped · 7 xfailed**, `tests/unit/prodgen` **93 passed**(11.5 min, Windows git) |
| 로컬 단위(X2 runtime, `d8d2bf9f`) | Jenkinsfile 텍스트 계약 · 예산 · harness · CI 테스트 PASS(constants per_fork 80 반영); Jenkins Declarative linter "successfully validated" |
| net-probe #1(Runner02, 읽기 전용) | `.135 .145 .165` ARP INCOMPLETE · `10.100.15.3` 무응답 · `10.100.15.1` ServiceRoot 503 "Redfish Service is disabled" · `10.50.11.231` Runner 망 무응답(tracepath 10.12.1.2 뒤 끊김) · `.232` 200 |
| perf-observe #1~#16 + main #92~#96 · production #82 | 13 host peak PSS 463 MB(worker 12 · 평균 slot 36 MB) · 18 host 620 MB · 단일 worker 최대 69 MB · 메인 python 86 MB · swap 0 · 겹침 2회 모두 다른 Runner 배치 — `tests/evidence/2026-10-04-review-c1-c6.md` §9-6 |
| main Job X2 `ec6a494f` 12 시나리오 | X2 `e2afb2ef` #97~#108 과 X3 `ec6a494f` #109~#120 두 번 모두 12/12 계약 PASS(T5 ABORTED · T6/cj/S3 UNSTABLE · chj FAILURE 기대값) · Portal 200 · `[Trusted]` 전부 일치 |
| CI #18(X2, PROMOTE dry-run) | SUCCESS — Gate · Corpus · Budget · Harness main 18/18 · Build · prodtree 10/10 · Drift · Verify COMPLETE_PASS 20/20(tree `de9422fb…`) · VAULT_DECRYPT · Evidence PASS(main 12 항목 전부 direct 바인딩) · Promote DRY_RUN `e2e ok, problems []`; bounded 5 PARTIAL/승인(`getNodeId` pending); Harness main 18/18 PASS · bounded 0/5 (PARTIAL/승인 — 네 번째 서명 `getNodeId` pending, 보존 단계 재전파도 Harness 가 기록) · prodtree 10/10 PASS(archive_fail · stash_fail · truncate_jsonl · checkpoint_only_a/b · layer_a_fail 포함) |
| 실 승격 P2 | 세션 CLI `promote --sha ec6a494f … --verify-report(CI #18) --e2e-evidence --ci-stage-results --push-remote origin,internal` — 1차(00:50) G18 FAIL 로 거부(원인: 작업 PC git `core.autocrlf=true` 가 drift A1 의 `git archive` export 를 CRLF 로 → manifest 거부, GP-45; 원격 변경 0) · 2차(01:06) G14/G15/G19 FAIL 로 거부(같은 시각 PC 메모리 부족 사건으로 WSL staging·하위 프로세스 실패; 원격 변경 0) · 3차(01:17~01:28, 저장소 설정을 잠시 autocrlf=false) **COMPLETE_PASS → P2 `07ecf7ac`**: Gates-Rerun G11 G12 G13 G14 G15 G18 G19 G20(G19 WSL 3채널 실제 실행 PASS) · Gates-Reused G01~G10 G16 G17 · publish origin "accepted by remote" · internal "already at the new commit (reached via a shared push URL)"(GP-40 수정 동작 확인, partial_push 없음) · 로컬 ref 갱신 · 193 파일 · 개발 경로 0 · trailer Main-SHA `ec6a494f` · Tree-Hash `de9422fb…` · Previous-Production `1f725071` · CI-Build #18 · Verdict COMPLETE_PASS · CI-Stages verified. vault 암호 파일은 실행마다 생성·삭제. |
| production Job(P2) 재검증 | production Job(P2 `07ecf7ac`, 11 빌드 #83~#93): 전부 checkout == P2 · 기대 결과 전부 일치(CAN-1/S1/S2/T2/Linux 15/Windows/ESXi 6/Redfish 10 SUCCESS, T6·S3 UNSTABLE 기대) — main X3 와 동일한 결과 |
| Portal | 정상 전달(main #100 S5 · #101 S1 · #102 S4 · #106 ESXi, body 12~47 KB)의 Portal 응답은 **HTTP 200 · 본문 0 B**(JSON 확인 없음) — Harness sink 는 `{"received": true, …}` 를 돌려주므로 echo 자체는 동작한다. 세션의 통제된 중복 재전송(curl, 같은 eventUuid·body)은 200 + HTML 예외 페이지(3,047 B)였다 — 중복 거절일 가능성이 있으나 요청 헤더(Jenkins httpRequest vs curl) 차이 때문일 수도 있어 **미확정**. 저장·반영은 Portal 측 로그/DB 로만 확인 가능(GP-42) |

## 2026-10-04 (3차) — 재개 지시 대응 (전체 명부 실수집 · S3 Redfish · CI #14 · 성능 전후 · 수집기 수정)

> 실측 `tests/evidence/2026-10-04-review-c1-c6.md` §5-7·§5-8 · `2026-10-04-test-server-roster.md`. 상태 어휘 PASS/FAIL/PARTIAL/HOLD/INVALID.

| 항목 | 결과 |
|---|---|
| main Job X6 `70e4ec8a` 시나리오 | T2 #45 · T5 #46(ABORTED=기대) · T6 #52(UNSTABLE=기대; #47 은 DNS 로 INVALID) · S5 #48(DIMM slot 1 재확인) · S1 #49 · S4 #50 · S2 #51 · E2E-A #42 · E2E-A′ #43 · E2E-D #44→**#61**(ESXi 6/6) · E2E-E #41 · Redfish 10 BMC #53 · `.95` OS #54 · **S3 Redfish #55**(forced 150 s · timeout · kept 6 · filled 1 · Portal 200) — 전부 계약 PASS(실행 기준) |
| CI #14(X6) | **SUCCESS** — Gate·Corpus·Budget PASS · Harness 16/16 · bounded 2 PARTIAL/승인 · prodtree 4/4 · Verify COMPLETE_PASS 20/20(tree `8d0f05c3…`) · VAULT_DECRYPT PASS · Evidence PASS · Promote DRY_RUN(E2E 탈락 2 = 수집기/입력 결함 → X7) |
| 성능 전후(같은 host 집합, 교대 5회) | production legacy #59~#63 vs main X6 #56~#60: 총 191.2→151.7 s · Gather 152.4→141.0 s · `.120` 97.2→74.5 s · `.161` 12.6→14.5 s · Portal 전부 200 |
| 로컬 단위 | `tests/unit/prodgen/test_verdict_evidence.py` 12 PASS(+`test_fail_closed_scenario_binds_to_agreeing_neighbour_builds_only`) · `tests/unit/prodgen` 전체 PASS(X7 수정 뒤) |
| Script Approval | 요구 3건 승인(사용자) → bounded #187/#188 PARTIAL(네 번째 `getNodeId` pending) |
| 거부(실제) | S3 forks 측정창(노드 offline/env) `Node Lifecycle Operations` · 노드 상태 조회 `Interfere With Workloads` — 다른 경로로 추구하지 않음 |
| Runner SSH(사용자 허용 뒤) | Runner01~04 읽기 전용 사실 + 자원 샘플러 5쌍(/tmp, 종료 후 제거): legacy 297~327 MB / 15~16 % vs X6·X7 288~332 MB / 17 %, swap 0 — §5-9·§5-10 |
| main Job X7 `24c9fd34` 재실행 | T2 #68 · T5 #69 · T6 #70 · S5 #71(slot 1·4096) · S1 #72 · S4 #73 · S2 #74 · E2E-A #75 · E2E-A′ #76 · E2E-D #77(6/6) · E2E-E #78 · S3 #79(timeout·kept 6·filled 1) — 12/12 계약 PASS(§5-11). CI #15 는 수집기 검사 결함으로 중단 |
| main Job X7b `ce50ccf7` 재실행 + CI #16 | T2 #80 · T5 #81 · T6 #82 · S5 #83(slot 1·4096) · S1 #84 · S4 #85 · S2 #86 · E2E-A #87 · E2E-A′ #88(neighbours:#87,#89 바인딩) · E2E-D #89(6/6) · E2E-E #90 · S3 #91(timeout·kept 6·filled 1) — 12/12 계약 PASS / CI #16: SUCCESS — COMPLETE_PASS 20/20(tree 8d0f05c3…) · VAULT_DECRYPT PASS · Harness 16/16 + prodtree 4/4 · bounded 2 PARTIAL/승인 · Promote DRY_RUN e2e ok(problems []) · parent 4ce90a00 — 실 push 는 credential 대기 |
| 로컬 단위(X7b) | `tests/unit/prodgen` 91 PASS(E2E-A2 Gather 블록 검사 fixture 포함); 실제 #76 콘솔 6/6 검사 True |
| **실 승격**(세션 CLI, vault 암호 사용자 제공) | P1 `1f725071` 양 원격 — Gates-Rerun G11 G12 G13 G14 G15 G18 G19 G20 전부 PASS(G19 WSL 3채널 실제 실행) · COMPLETE_PASS · `internal` 거짓 partial_push(origin push URL 2개) → `push-sync` 정합 · 결함 수정 regression `test_shared_push_url_between_remotes_is_idempotent_not_partial` → `tests/unit/prodgen` **92 PASS** |
| **production Job(P1) 재검증** | canary #71 · P-S1 #72 · P-S2 #73 · P-T2 #74 · P-T6 #75(UNSTABLE=기대) · Linux 8 #76 · Linux 7 #77(3 unreachable) · Windows #78 · ESXi 6 #79 · Redfish 10 #80(7 success) · S3-Redfish #81(UNSTABLE=기대) — 전부 checkout == P1, Portal 200 |

## 2026-10-04 (2차) — 완료 보고 검토 C1~C6 대응 (시나리오 계약 · baseline 복구 · 환경 재실행 · 배포 정책 · interruption Harness · vault 복호화)

> 실측 `tests/evidence/2026-10-04-review-c1-c6.md` · `2026-10-04-promotion-drill.md` · `2026-10-04-test-server-roster.md`. 상태 어휘 PASS/FAIL/PARTIAL/HOLD/INVALID.

| 항목 | 결과 |
|---|---|
| 단위 묶음(Windows) | `tests/unit/prodgen/test_verdict_evidence.py` 9 · `test_promotion_cycle.py` 7(B→P1→R→P2 · **B→P1→P2→R→P3** · 배포 정책/CI stage 증거 · G20 원격 없음 PARTIAL · 거부 · 경쟁 · push-sync) · `test_pipeline_tmp_repo.py` · `test_jenkinsfile_ci.py` 34 · `test_harness_tools.py` 11 · `test_harness_callback_sink.py` 5 — 모두 PASS |
| Jenkins 선언형 린터 | `Jenkinsfile_ci`(C4·C6·GP-4 수정본) validated(Toolchain 의 `\.` 이스케이프 1건 수정 뒤) |
| 로컬 `bash scripts/ai/ci_gate.sh`(Windows, X2 작업 트리) | pytest **4,091 passed · 36 skipped · 7 xfailed**(unit·e2e·regression, 15 min) + integration(not live) **308 passed · 4 skipped**; python compile · field_dictionary · schema drift · vendor boundary · harness consistency PASS; corpus 14/14 MATCH. **전체 결과 PARTIAL** — `ansible-playbook --syntax-check` 는 이 호스트에 ansible 이 없어 건너뜀(같은 후보의 CI Gate·G11 이 보완) |
| 실 `4ce90a00` 복구 훈련(두 bare 원격, live gate stub) | **PASS(기구)** — B→P1→P2→R→P3 전이 전부 기대대로(R tree OID == B^{tree}, baseline 계승, 한 원격 restore 거부, 양 원격 ff). 실 원격 변경 0. `tests/evidence/2026-10-04-promotion-drill.md` |
| CI #10(X2 `33eb29b7`, 사용자가 `!` 로 push 한 뒤 트리거) | **UNSTABLE** — Gate·Corpus·Budget PASS · Harness 12/12(#93~#104; 새 4 시나리오는 stale 파라미터 기본값으로 미실행) · bounded 2 ABORTED(승인 부재 재전파를 Harness 가 받지 못함 → X3 수정) · Build·prodtree 4/4·Drift PASS · **Verify COMPLETE_PASS 20/20**(환경 식별자 전부 채워짐, `jenkins_version 2.528.3`) · **VAULT_DECRYPT FAIL rc 2**(도구가 .gitignore 라 Runner 에 없음 → X3 추적) · Evidence PASS · Promote DRY_RUN(환경 재실행에 자격 없음 → G13/G19 SKIP → PARTIAL 미리보기; X3 에서 Promote 에 자격 바인딩) |
| main Job(X2) 실호스트 | **S5 #11**(.37/.38 RHEL 10.2 kernel 6.12 — 수집 success · Portal 200 · **DIMM slot 0 재현**) · **S1 #12**(.161/.162/.163/.120 전부 success · Portal 200) · **S4 #13**(.120) · **S2 #14**(4 success + TEST-NET 2 실패 진단) — 계약 PASS; **S3 INVALID(환경 — 최장 host 105 s < MIN_START 120 s)** |
| 거부(실제) | E2E-E redfish dry-run 트리거 ×2 · Runner03 `cj` 라벨 POST · 접속정보 파일 구조 읽기(값 마스킹) — 자동 분류기 "Auto-Mode Bypass"/"Credential Exploration" |
| X5 `07affa30`(수집기 수정) | main #33 T2 · #34 T5 · #35 T6 · #36 S5 · #37 S1 · #38 S4 · #40 S2(#39 는 컨트롤러 DNS 일시 오류) 전부 계약 PASS; CI #13(X5 `07affa30`) **SUCCESS** — Gate·Corpus·Budget PASS · Harness main **16/16**(#142~#157, user_abort·aborted_outcome_finalize ABORTED=기대) · bounded 2 PARTIAL/승인(#158/#159) · Build · prodtree **4/4**(#160~#163) · Drift · **Verify COMPLETE_PASS 20/20**(tree_hash `8d0f05c3…` = X4 와 동일 — runtime 불변 확인, report `ae834e29…`) · **VAULT_DECRYPT PASS** · Evidence PASS(31 항목: Harness 22 + main 7 중 29 pass) · **Promote DRY_RUN**: 보고서 재사용(환경 일치, 재실행 0) · ci_stages ok · 배포 정책 ok · parent `4ce90a00` · tree OID `0b5e13a5…`; **E2E 미충족 = S3 · E2E-A · E2E-A2 뿐** → 설계대로 실 승격 불가(원격 변경 0) |
| X3 `515ff827`(DIMM raw 근거 marker · Promote 자격 · vault 도구 추적 · Harness bounded) | push 허용(사용자 명시 승인 뒤). main #17 T2 · #18 T5 · #19 T6 · **#20 S5(raw_head → 원인 = dmidecode 3.6 IEC 단위)** · #21 S1 · #22 S4 · #23 S2 · #15/#16 명부 배치 — 전부 계약대로. CI #11 은 X4 로 넘어가며 중단 |
| X4 `41fb14b9`(dmidecode 3.6 IEC 단위 수정) | 로컬 `test_linux_memory_parser.py` 78 PASS(+`test_dmidecode_36_iec_units_are_parsed`) · 전체 gate pytest 4094 passed · 36 skipped · 7 xfailed + integration 308 passed, corpus 14/14, 결과 PARTIAL(syntax-check 는 Windows 라 건너뜀). main **#29 S5: `.37/.38` slot 1 · 4096 MB · physical_installed · 경고 0(해결 확인)** · #26 T2 · #27 T5 · #28 T6 · #30 S1 · #31 S4 · #32 S2 · #24/#25 명부 배치(GB host 회귀 0) — 전부 Portal/sink 수신 200. CI #12: **SUCCESS** — Gate·Corpus·Budget PASS · Harness main **16/16**(#119~#134: 12 + recover_slow · foreign_timeout_interruption · user_abort(ABORTED=기대) · aborted_outcome_finalize(ABORTED=기대)) · bounded 2 PARTIAL/승인(UNSTABLE, 재전파 기록 — 승인 전) · Build·prodtree 4/4·Drift PASS · **Verify COMPLETE_PASS 20/20**(tree `8d0f05c3…`, 환경 일치 → 재실행 0) · **VAULT_DECRYPT PASS**(49 파일 복호화·구조 검증, ic/cj/yi/git 12/12 — C6 증거) · Evidence PASS · **Promote DRY_RUN**(보고서 재사용, ci_stages ok, 정책 ok, parent `4ce90a00`; E2E 미충족 = S3 · E2E-A · E2E-A2 + 수집기가 ABORTED 기대 시나리오를 SUCCESS 로 판정한 결함 → X5 수정) |
| main Job(X2 `33eb29b7`) | **T2 #8 SUCCESS**(sink_hold 수신 `HTTP 200`, output 2) · **T6 #9 UNSTABLE**(연결 거부 3/3 · body 보존) · **T5 #10 ABORTED**(`outcome=aborted` 재전파 · Callback 1회 200) — 셋 다 계약 PASS |
| main Job(현재 원격 main `ae4db48b`) | **#7 T5 PASS(계약)** — 중단 → `outcome=aborted` 기록·재전파 · ABORTED 유지 · Callback 1회 시도(거부 관측) · body 보존. E2E-E · S5 트리거는 자동 거부("Auto-Mode Bypass") |

## 2026-10-04 — 잔여 결함 R1~R7 · Harness · CI 연결 · prodgen 강화 (Jenkins 실측 포함)

> 실측 `tests/evidence/2026-10-04-residual-r1-r7.md` · `2026-10-04-live-e2e.md` · `2026-10-04-location-cj.md`. 상태 어휘 PASS/FAIL/PARTIAL/HOLD/INVALID.

| 항목 | 결과 |
|---|---|
| 로컬 `bash scripts/ai/ci_gate.sh`(Windows) | 1회차 4,061 passed + `test_promotion_cycle.py::test_refusals…` 1 failed(flaky, 재현 안 됨 — FAILURE_PATTERNS 2026-10-04) → 2회차 **4,070 passed · 36 skipped · 7 xfailed**, corpus 14/14, field_dictionary PASS; `ansible-playbook` 없음 → syntax-check 건너뜀 = **PARTIAL(rc 2)** |
| CI #5 Gate(Runner, `5d2a8c8e`) | **3,999 passed · 99 skipped · 7 xfailed**, corpus Python+Groovy 14/14, Budget self-test PASS |
| CI #3 Gate(Runner) | 2 errors — `commit-tree` "Author identity unknown"(Runner 에 git 신원 없음) → `21b811b0` 기본 identity |
| prodgen Verify (CI #3, Runner, netrc + vault) | FAIL — G09(생성 tree exec bit 누락) · G14(`test_bounded_recovery…` 가 주석 의존) · G20(CI checkout 로컬 production ref 부재 + LEGACY 미지정); **G19 PASS 28.8 s**(os/esxi/redfish 각 envelope 2, `TARGET_UNREACHABLE`), G13 PASS(`se-jenkins-lint`) |
| prodgen Verify (CI #5, `BOOTSTRAP_BASELINE=4ce90a00…`) | **COMPLETE_PASS 20/20** — G14 PASS(106.8 s, 필수 그룹 runtime_regression 169 · runtime_e2e 743 · budget_formula 13 · portal_contract 19 · finalize_layer_a 13) · G19 PASS 29.0 s · G18/G20 PASS; `report_sha256 7b81b8b8…`, 환경 `Runner01 · Python 3.12.9 · ansible-core 2.20.3 · pwsh True · Linux 5.14.0-570.12.1.el9_6` |
| Harness Job(main 함수, `5d2a8c8e`, CI #5 Driver) | normal_success #28 · archive_fail #29 · both_fail #31 · truncate_jsonl #32 · checkpoint_only_a #33 · layer_a_fail #35 · raw_fallback #36 · report_corrupt #37 · sink_5xx #38 · outer_timeout #39 **PASS**; stash_fail #30 · checkpoint_only_b #34 **FAIL → 운영 코드 결함 2건 수정(`0ccb89eb`)**; 생성 tree 함수 #40~#42 FAIL(agent JVM 자체 서명 PKIX → `ignoreSslErrors`) |
| Harness 첫 PASS 까지 | #4~#26 FAILURE(HARNESS binding · 정본 복사 · sink 위치 · toJson(List) · NFS .nfs* · lingering Timer) → **#27 normal_success PASS**(verdict 14/14) |
| main Job | #4(`5d2a8c8e`) · #5(`0ccb89eb`) · #6(`15e684b0`) T2+T6: TEST-NET 2 → `TARGET_UNREACHABLE` ×2 · 13 키 · Layer A ok · Callback `127.0.0.1:9` 연결 거부 3회 관측 → `delivered=false` · `callback_body.json` 유효 · UNSTABLE; R6 `pre=5~6s wait_checkout=5s prep=2~4s` · P-1 `mem_avail_mb≈6.1 GB mem_cap=62 mem_guard=active` |
| CI #7(`15e684b0`, 최종 후보) | **SUCCESS** — Gate PASS · Corpus 14/14 · Budget PASS · Harness Driver **12/12** · Build(192 파일 · class B 0 · `tree_hash 05ce23c3…`) · Harness(prodtree) **4/4** · Drift PASS · **Verify COMPLETE_PASS 20/20**(G14 104.4 s · G19 28.3 s) · Evidence PASS(16 항목) · Promote not_run |
| CI #8 / #9(`15e684b0`, `PROMOTE=true` dry-run) | #8 FAILURE — Harness #60 `checkout scm` GitHub fetch rc 128(일시) → Promote 조건 ① 거부(원격 변경 0); **#9 SUCCESS — Promote DRY_RUN**(전 stage PASS · GitLab 자격 부재 감지 · 보고서 재사용 · E2E `ok=false`(main 증거 없음) · 미리보기 parent `4ce90a00` tree `d296aa32…`) |
| Jenkins 선언형 린터 | `Jenkinsfile_ci`(it→hr 수정본) validated · `Jenkinsfile_portal`(회수 매체 수정본) validated |
| 단위 묶음(Windows) | `test_jenkinsfile_ci` 30 · `test_jenkinsfile_portal_finalize` 20(+source_text 1) · `test_jenkinsfile_portal_preserve_and_params` · `test_harness_tools` 8 · `test_harness_callback_sink` 5 · `test_gitstore_identity` 4 · `test_verdict_evidence` 7 · `test_promotion_cycle` 4(162 s) · `test_pipeline_tmp_repo` |

## 2026-10-03 — Gathering 개선 Phase 2 · 3 · 4 (정확성 · 성능 · 예산/마무리/Callback)

> 실측 `tests/evidence/2026-10-03-phase2-correctness.md` · `tests/evidence/2026-10-03-phase4-finalization.md`. live 는 권한 차단으로 미실행 — 아래는 오프라인뿐.

| 항목 | 결과 |
|---|---|
| WSL(ansible-core 2.20.7) `pytest tests/unit` / `tests/e2e` | 2730 passed · 1 skipped · 8 xfailed(+ Windows P4 진행 중 파일 1 failed) / 761 passed · 6 skipped |
| WSL `ansible-playbook --syntax-check` 3채널 · `pre_commit_jinja_compile_check.py --all` | 통과 |
| WSL `tests/integration/test_addon_hook_playbook.py` | 14 passed (D8 재배치 · CHECKPOINT · 진행 이벤트 · apply.timeout 으로 `sleep 40` 3 s 절단) |
| WSL Linux C1/C2/C7 (`test_linux_memory_parser` · `_storage_markers` · `_hba_ib_markers`) | 72 passed (sudo 재시도 수정 뒤 xfail 1 → pass) — 실제 ansible-playbook 3 시나리오(정상 · 도구 열화 · JSON 손상) 통과 |
| WSL ESXi P5 (`test_esxi_facts_reuse` 14) + 실제 ansible-playbook fake 모듈 4 시나리오 | vmware_host_facts 호출 2→1 · 2→1 · 3→2 · 1→1, `_e_raw_facts` 29 키 동일 |
| Windows 단위 묶음(auth evidence 18 · addon contract 46 · Jenkinsfile 4 파일 · finalize 13 · budget 8 · redfish phase2 31/phase3 10 · account · esxi reuse · progress 6) | 243 passed |
| Windows e2e 묶음(timeout 3분류 18 · failure_reason/code/diagnosis/multi_credential/credential_scope/errors_message/case_matrix) | 402 passed · 28 skipped |
| `tests/integration/test_request_budget.py` (Phase 3) | R740 168→137 · CSUS 218→134 · DL380 132→131 · SR650 124→123, added 0, golden 동일 |
| Jenkins 선언형 린터 (jenkins-prod 2.528.3) | `Jenkinsfile_portal` validated (Phase 4 최종본 · GP-11 load 전환본), `Jenkinsfile_ci` validated |
| Windows P4 (`pytest tests/unit -k windows`) | 151 → 279 passed(+128: 통합 static 29 · render 57 · powershell 42); 종전 vs 신규 fragment 동일 27 시나리오, `.120` live 출력 재현, powershell.exe `-EncodedCommand` 실행 15 시나리오 동일; 타임아웃 적용 뒤 Windows 7 파일 + remote timeouts 242 passed |
| Phase 6 (`test_jenkinsfile_ci` 20 · `test_finalize_corpus` 35 · portal finalize/agent_label/addon/params) | 59 passed(load 전환 뒤); Groovy 동치 corpus 14 MATCH(Groovy 4.0.24 · 2.4.21, 음성 대조 4건 검출 — 작업자 로컬 실행) |
| Phase 5 WSL emulation (`tests/scripts/phase5_scale_run.sh`, Ubuntu 24.04 · ansible-core 2.20.7 · Ryzen 5 5600/15 GiB) | 실패 경로 10/50/100/200 host × forks 50/100 × 3회: wall 10.6–11.0 / 24.7–37.5 / 52–68 / 104–116 s, 트리 PSS forks 10/50/100 → 0.4/1.8/3.7 GB, 2,460 envelope 13키 · 요청 == 결과; INT 6회 rc 124 ×5 · rc 137 ×1(weakref 콜백 소실) 고아 0 보충 정확; 기록 비용 Δ ≤ 노이즈; Layer A 1000 host 0.21/0.23/0.12 s; Redfish 에뮬레이터 불가 |
| `test_gather_budget.py` (OS forks 상한 50 + `SE_FORKS_CAP_OS`) · 콜백 first_seen ip | 9 passed / 92 passed |
| Linux P3 (`test_linux_*` 4 파일 · `test_linux_remote_consolidation` 19 · `tests/e2e/test_linux_raw_scripts_shim` 11) | WSL 153 passed(vlan_id 수정 뒤 xfail → pass); e2e 772 passed; 작업자: 6 캡처 × 6 권한 × 2 모드 432 fragment 집합 동일, 실제 play 4회 envelope 동일 |
| prodgen (`tests/unit/prodgen` 69) | Windows 69 passed / WSL 61 passed · 8 skipped(PowerShell 파서 없음); 생성 `dcfbfded`~`25bb5343` 192 파일 · 1,035,135 B · tree `49bd0d88…` 동일 · B 0 · **G01~G17 PASS**(G14 run 5: 3674 passed · 87 skipped · 31 deselected; run 1~4 는 overlay 수집 오류 — 생성 tree 에 없는 scripts/ai·Jenkinsfile_ci import, conftest 이름 충돌 → 수정) · `promote --dry-run` parent `4ce90a00` tree `88280034` |
| WSL `pytest tests/unit tests/e2e` 동시 실행(`-m "not source_text"`, PowerShell 테스트 probe skip) | 3747 passed, 97 skipped, 51 deselected, 4 warnings in 103.04s (0:01:43) |
| G14 overlay 제외 표식 7 파일 | 126 passed(전체) / 75 passed · 51 deselected(`-m "not source_text"`) |

## 2026-10-03 — Gathering 개선 Phase 1 baseline · Phase 1.5 (Jenkinsfile 최소 선행 변경 · ci_gate)

> 실측 `tests/evidence/2026-10-03-phase1-baseline.md`. live(Jenkins 빌드 · VM SSH · BMC) 는 권한 차단으로 미실행 — 아래는 오프라인뿐.

| 항목 | 결과 |
|---|---|
| `bash scripts/ai/ci_gate.sh` (Windows, Python 3.13.15) | compile · field_dictionary PASS · drift 정합 · vendor boundary 0건 · harness consistency 통과; `pytest tests/unit tests/e2e tests/regression` **3369 passed / 35 skipped / 7 xfailed** (80 s); `pytest tests/integration -m "not live"` **300 passed / 4 skipped / 1 deselected**; syntax-check 건너뜀 → PARTIAL |
| `bash scripts/ai/ci_gate.sh` (WSL, ansible-core 2.20.7, `CI_GATE_SKIP_PYTEST=1`) | 3채널 `ansible-playbook --syntax-check` 통과 |
| Jenkinsfile 계약 테스트 4 파일 | 69 passed — 신규 `test_jenkinsfile_portal_preserve_and_params.py` 10 (stage 순서 · agent 없음 · readTrusted · manifest · 검증 파라미터 기본값 · dry-run/timeout guard · post 보존 순서 · 입력 구조 오류 · LF) |
| Jenkins 선언형 린터 (jenkins-prod 2.528.3 `pipeline-model-converter/validate`) | Jenkinsfile_portal validated |
| WSL §6-7 실험 (1)(2)(3)(4)(5) | apply timeout task 단위 / timeout register·failed_when·ignore_errors·자식 잔존 / INT·TERM·KILL 종료와 JSONL 보존 / `_inventory` 접근 / ConnectTimeout 순서 — 결과는 evidence §2 |
| 오프라인 count baseline | Redfish 재생 GET 167 · 217 · 131 · 123 (+noauth 1), firmware 멤버 GET 62 · 2 · 22 · 26; 원격 실행 task Linux 18/13 · Windows 20 · ESXi 13 |
| pytest 전체 수집 | 3,705 (수집 오류 2 = `tests/e2e_browser`, playwright 미설치 — 기존 환경 제약, ci_gate 범위 밖) |

## 2026-09-30 — Add-on 변수 이름 정리 (`ADDON_REPO_*` · `ADDON_DIR`)

> 대응표 `docs/reference/decision-log.md` 2026-09-30. 실측 `tests/evidence/2026-09-29-addon-per-build-checkout.md` 5절.

| 항목 | 결과 |
|---|---|
| `pytest tests/unit tests/e2e` | 3185 passed / 35 skipped |
| Add-on 단위 3파일 (hook 계약 · Jenkinsfile 계약 · 체크아웃 스크립트) | 74 passed — 옛 이름 부재 13 파일 포함 |
| `tests/integration/test_addon_hook_playbook.py` (WSL, ansible-core 2.20.7) | 10 passed |
| `ansible-playbook --syntax-check` 3채널 (WSL) | 통과 |
| Jenkins 선언형 린터 (lab 153) | validated |
| Add-on `python -m pytest tests` (Windows) / `tests/test_playbook.py` (WSL) | 이름 변경 뒤 181 passed · 17 skipped / 17 passed → 결함 수정(`6ef226a`) 뒤 186 passed · 18 skipped / 18 passed |
| jenkins-prod #11 (production `afe3a90c`, 변수 없음) | OS 3대 success, #10 과 host 별 동일 |
| lab Add-on e2e #8 → #9 | #8 PASS 137 / FAIL 3 (Windows 거짓 알림 — Add-on 결함) → 수정 뒤 #9 PASS 140 / FAIL 0, 엔진 테스트 10 passed (ansible-core 2.20.3) |

## 2026-09-29 — Add-on 빌드별 체크아웃 (`scripts/addon_checkout.sh` · `Jenkinsfile_portal` Gather · Add-on `ed8f320`)

> 코드 `3d0fbfa2` · 문서 `3bba2edf` · production `9a194619`. 실측 `tests/evidence/2026-09-29-addon-per-build-checkout.md`.

| 항목 | 결과 |
|---|---|
| Add-on `python -m pytest tests` (Windows) | 177 passed / 17 skipped (playbook 테스트는 ansible 필요) |
| Add-on `tests/test_playbook.py` (WSL, ansible-core 2.20.7, role 실제 실행) | 17 passed — target 디렉터리 없음 · 전부 끔 · 설정 없음 · config 없음 · 실수 4종 · 깨진 config · collector 예외 격리 · 연결 끊김 · 5MB · 비 UTF-8 · `only` |
| Add-on `tools/check_layout.py` (WSL · Windows) | rc 0 (`linux=['hosts','software'], windows=['software']`) / rc 3 (esxi) / rc 1 (경로 없음) |
| `pytest tests/unit/test_addon_checkout.py` (Git bash + 실제 git, file:// 저장소) | 14 케이스 PASS + LF·100755·정적 계약 6건 |
| `pytest tests/unit/test_jenkinsfile_portal_addon.py` | 12 passed |
| `pytest tests/unit tests/e2e` | 3171 passed / 35 skipped |
| Jenkins 선언형 린터 (lab 153) | Jenkinsfile_portal validated |
| 실제 Agent `addon_checkout.sh` stdin 실행 (lab 155 · 신규 Runner01 33) | GitLab 자체 서명: 기본값(검증 안 함) main · 40자 해시 rc 0 양쪽, `SE_ADDON_SSL_VERIFY=true` 는 CA 없는 Runner01 에서 rc 1(기대) · 155 는 rc 0(CA 신뢰됨), 짧은 해시 rc 1 양쪽 |
| lab Jenkins `clovirone-server-gather` #21 (production `9a194619`, 전역 변수 없음) | `[addon]` 줄 없음, envelope 4건 #20 과 동일(dell·lenovo·cisco success, HPE TARGET_UNREACHABLE 기존), Callback sink → UNSTABLE(의도), 6분 49초 |
| Jenkins Add-on 켜진 실행 | 대기 — 사용자의 Add-on push(AP-1) · `SE_ADDON_REPO` 등록(AP-2) 뒤 (evidence 4절) |
| `verify_harness_consistency.py` / `verify_docs_references.py` | 통과 / 이번 변경 관련 지적 0건 |
| `ansible-playbook --syntax-check` (메인) | 미실행 — 메인 playbook 변경 없음 (hook · site.yml 무변경), 로컬에 ansible 없음 |

## 2026-09-28 — Agent venv 경로 분리 (`scripts/activate_ansible_venv.sh`)

> 코드 `8170ae7d` · 문서 `da91b274` · 하네스 `7b36aaa6` · production `e7baaa55`. 실측 `tests/evidence/2026-09-28-runner-venv-path.md`.

| 항목 | 결과 |
|---|---|
| `pytest tests/unit/test_activate_ansible_venv.py` (Git for Windows bash) | 10 passed — env override 정상/무효, PATH 파생, stray→후보, 전부 없음 실패+센티널 미실행, 실행 모드 exit 1, 재source, python 밖 실패, LF·셸 상태 |
| `pytest tests/unit` | 2446 passed |
| `pytest tests/e2e` | 723 passed / 6 skipped |
| Jenkins 선언형 린터 (lab 153) | Jenkinsfile_portal validated |
| Runner 33~36 + lab 155 헬퍼 stdin 실행 | 양성 5/5 (`/app` source=path × 4, `/opt` source=known × 1), 음성 2종 × 5 = rc 1 |
| lab Jenkins `clovirone-server-gather` #20 (production `e7baaa55`) | Gather·Validate Schema `[venv] /opt/ansible-env (source=path)`, envelope 4건(#18 과 동일: dell·lenovo·cisco success, HPE 10.50.11.231 TARGET_UNREACHABLE 기존 상태), Callback sink → UNSTABLE(의도) |
| 신규 Jenkins `clovirone-cicd/clovirone-server-gather` #8 (production `e7baaa55`, Runner git 설치 + credential 등록 뒤) | Gather(Runner03)·Validate Schema(Runner01) `[venv] /app/ansible-env python=3.12.9 (source=path)`, envelope 4건 lab 과 동일, Callback sink → UNSTABLE(의도). #7 은 credential 미등록으로 Gather 진입 전 실패 |
| `verify_harness_consistency.py` / `verify_docs_references.py` / `check_project_map_drift.py` | 통과 / 삭제 파일 지적 0건(기존 무관 지적만) / fingerprint 일치 |
| `ansible-playbook --syntax-check` | 미실행 — playbook 변경 없음, 로컬에 ansible 없음 |

## 2026-09-22 (4) — Add-on 사용자 관점 감사 (README · 주석 · match 누락 알림)

> Add-on `f59d819` · `4be4bfb` · `83cddde`, 메인 `18b59ad9`(문서만).

| 항목 | 결과 |
|---|---|
| Add-on `python -m pytest tests` (Windows) | 133 passed / 14 skipped — 신규 `test_rule_without_match_is_reported_and_later_rules_still_apply` |
| Add-on `tests/test_playbook.py` (WSL, ansible-core 2.20.7, role 실제 실행) | 14 passed |
| 흔적 grep (`2026-` · `AO-` · `NEXT_ACTIONS` · `사용자 결정` · `실측` · `결정대로` · `계획서` · `형섭` · `10.100.` · `cloviradmin` · `AI`) | README · config · runtime · 테스트 0건. 남은 것은 `deploy/Jenkinsfile` 의 `ADDON_HOME` 기본값과 e2e 의 lab IP 파라미터 기본값 |
| 문체 grep (금지 표현 10종 · "습니다" · "할 수 있") | README · config 0건 — 코드가 내는 알림 문장을 인용한 "습니다" 5곳만 |
| `scripts/ai/verify_harness_consistency.py` / `tests/secret_guard.py` | 통과 / exit 0 |
| Agent e2e 재실행 | 없음 — runtime 변경은 `addon_plan` 의 알림 1가지. e2e s06 은 `errors[]` 1건 안에 문장이 더해질 뿐 |

## 2026-09-22 (3) — Add-on 구조 감사 · 문서 정합 · `rules` 키 알림

> 결정 `docs/reference/decision-log.md` "2026-09-22 구조 감사". 메인 코드 변경 없음 (문서만) · Add-on 필터 3줄.

| 항목 | 결과 |
|---|---|
| Add-on `python -m pytest tests` (Windows, `3b1df8e` · `30080c2`) | 132 passed / 14 skipped — 신규 `test_core` 1건(`rule:` 오타 → `config.yml 에 rules 가 없습니다 (있는 키: rule)`), `test_empty_config_is_silent` 그대로 통과 |
| 메인 `tests/integration/test_addon_hook_playbook.py` (WSL, ansible-core 2.20.7, `SE_ADDON_DIR` 없음 · Add-on 저장소 미참조) | 10 passed in 49.3s — "미설정 시 hook 도입 전과 byte 동일" 포함 (사용자 질문 "Add-on 없이도 문제 없나" 의 실측 근거) |
| 메인 `tests/unit/test_addon_hook_contract.py` + `test_inventory_passthrough.py` (Windows) | 66 passed |
| `scripts/ai/verify_harness_consistency.py` / `tests/secret_guard.py` | 통과 (rules 28 · skills 47 · agents 47 · policies 7) / exit 0 |
| 메인 코드의 Add-on 저장소 참조 | 0건 (문서 제외 — `test_addon_hook_contract.py:121` 은 hook 안의 Add-on 경로를 금지하는 검사) |
| Agent e2e · Ansible 재실행 | 하지 않음 — runtime 변경이 필터 3줄이고 단위 테스트로 덮인다. e2e s06(설정 실수)는 `rules` 키가 있어 영향 없음 |

## 2026-09-22 (2) — Add-on AO-2 · AO-3 적용, Agent 규모 시험

> 실측 `tests/evidence/2026-09-21-addon-hook-live.md` 9절. 메인 코드 변경 없음 (문서만).

| 항목 | 결과 |
|---|---|
| Jenkins e2e #7 (Agent `jenkins-agent-dev`, ansible-core 2.20.3, 메인 `d67005b9`, Add-on `951366d`, `all,scale`) | **SUCCESS** — 엔진 테스트 10 passed · 규모 시험 PASS 8/8 · 시나리오 14개 **PASS 127 / FAIL 0 / KNOWN 0** |
| 규모 시험 (host 200 · forks 200 · 미설정 / 1회 / 동시 2회) | 실패 0 · 연결 끊김 0 · 200/200, 최대 메모리 0.35GiB (감시 중단 0) |
| Add-on `python -m pytest tests` | Windows 131 passed / 14 skipped (xfail 0 — PowerShell 5.1 오류 스트림 시험이 이제 통과), WSL 135 passed / 10 skipped (2.20.7, 비 UTF-8 바이트 playbook 시험 포함) |
| 로컬 PowerShell 5.1 예전 · 새 감싸기 stdout 비교 (6종) | 모두 byte 동일 |
| 배포 Job `형섭/clovirone-gathering-addon-deploy` #1 | SUCCESS — 검사 통과, release `20260922-085019-7dec7d2` 로 링크 |

## 2026-09-22 — Add-on Jenkins e2e · 추가 조사 · 경로 실수

> 실측 `tests/evidence/2026-09-21-addon-hook-live.md` 5 ~ 8절. 메인 제품 코드 변경 없음 (테스트만 추가).

| 항목 | 결과 |
|---|---|
| Jenkins e2e Job `형섭/clovirone-gathering-addon-e2e` #1 | FAILURE — 새 Job 첫 빌드에서 파라미터가 셸 환경변수로 안 들어옴 → Jenkinsfile 수정 |
| Jenkins e2e #2 (Agent `jenkins-agent-dev`, ansible-core 2.20.3, 메인 `d6ed2278`) | SUCCESS — 시나리오 11개 PASS 99 / FAIL 0 / KNOWN 1 (AO-2) |
| Jenkins e2e #3 (메인 `d6ed2278`, Add-on `db9b31e`) | SUCCESS — 시나리오 14개 PASS 116 / FAIL 0 / KNOWN 2 (AO-2 · AO-3). 수 MB 출력(Linux 2.29MB · Windows 1.19MB 등)이 실제 SSH · WinRM 전송 뒤 글자 그대로 |
| Jenkins e2e #4 (메인 `eafddf0b`, Add-on `0dd4d7b`) | SUCCESS — PASS 116 / FAIL 0 / KNOWN 2 (s10 hosts 알림 확인 추가) |
| Jenkins e2e #5 (Add-on `18115fe`) | SUCCESS — PASS 119 / FAIL 0 / KNOWN 2 (s04 Windows here-string · `{{ }}` 추가). 엔진 테스트 단계는 Agent 에 pytest 가 없어 건너뜀 → 수정 |
| Jenkins e2e #6 (Add-on `9097425` — 최종) | SUCCESS — 엔진 테스트(Agent, ansible-core 2.20.3) **10 passed** (Test Result pass 10 / fail 0) + 시나리오 14개 **PASS 119 / FAIL 0 / KNOWN 2** (AO-2 · AO-3), 956초 |
| `pytest tests/ --ignore=tests/e2e_browser` (Windows, 테스트 추가 뒤) | **3628 passed**, 11 skipped, 7 xfailed, 0 failed (경고 4 — 기존) |
| 따로 실행 (계획서 12절): `tests/unit` · `tests/e2e` · `tests/regression` · `tests/integration -m "not live"` | 2436 passed / 723 passed 6 skipped / 169 passed 7 xfailed / 300 passed 4 skipped |
| `validate_field_dictionary.py` · `output_schema_drift_check.py` | PASS (경고 81 — 기존) · rc=0 (sections=11) |
| `verify_vendor_boundary.py` | rc=2 — 기존 2건 (`redfish_gather.py:5746` iLO, `:5890` XCC). 이번 변경과 무관 |
| `ansible-playbook --syntax-check` 3채널 (WSL 2.20.7, main `eafddf0b`) | 모두 rc=0 |
| `tests/integration/test_addon_hook_playbook.py` (상위 폴더 · 끝 `/` 추가) | 10 passed — WSL ansible-core 2.20.3 · 2.20.7 |
| `SE_ADDON_DIR` 설정 실수 9가지 (엔진 harness) | 2.20.3 · 2.20.7 같은 결과 — 기본 결과 유지, 실행 못 하면 `errors[]` 1건 |
| AO-3 재현 E1 / E2 (엔진 harness) | 2.20.3 · 2.20.7 같은 결과 — E1 `OUTPUT_BUILD_FAILED`, E2 기본 결과 유지 + Callback 본문 파싱 정상 |
| AO-2 Windows 2022 `win_shell` 48 조합 · 로컬 PowerShell 5.1 | 측정 (evidence 6절) |
| Add-on 저장소 `python -m pytest tests` | Windows 114 passed / 13 skipped / 2 xfailed (PowerShell 5.1 here-string · `{{ }}` 추가), WSL 122 passed / 7 skipped, 2.20.3 playbook 13 passed |
| `verify_harness_consistency.py` · `check_project_map_drift.py` · `secret_guard.py` | 통과 |

## 2026-09-21 — 고객별 추가 수집(Add-on) hook

> 정본: `docs/ai/decisions/ADR-2026-09-21-gathering-addon-hook.md`, 실측 `tests/evidence/2026-09-21-addon-hook-live.md`.
> 브랜치 `feature/gathering-addon` (worktree = `413bc039` + 이번 변경 — main 작업 트리의 다른 세션 변경은 섞이지 않음).

| 항목 | 결과 |
|---|---|
| `pytest tests/ --ignore=tests/e2e_browser` (Windows) | **3507 passed**, 12 skipped, 7 xfailed, 0 failed (경고 4 — 기존 Jinja escape 경고) |
| 신규 `tests/unit/test_inventory_passthrough.py` | 37 passed (Windows · WSL) |
| 신규 `tests/unit/test_addon_hook_contract.py` | 29 passed |
| 신규 `tests/integration/test_addon_hook_playbook.py` | 8 passed — ansible-core **2.20.3** · 2.20.7 (WSL). Windows 는 skip (Ansible 제어 노드 미지원 — CLI 가 `WinError 87` 로 기동 불가) |
| Add-on 저장소 `python -m pytest tests` | Windows 112 passed / 10 skipped / 2 xfailed (PowerShell 5.1 오류 출력 — AO-2), WSL 119 passed / 5 skipped, 2.20.3 로 playbook 테스트 10 passed |
| `ansible-playbook --syntax-check` 3채널 | 2.20.3 · 2.20.7 모두 rc=0 (WSL) |
| `tests/validate_field_dictionary.py` | PASS (경고 81 — 기존) |
| `tests/secret_guard.py` · `output_schema_drift_check.py` · `verify_harness_consistency.py` | 통과 (sections=11, rules 28 / skills 47 / agents 47 / policies 7) |
| `verify_vendor_boundary.py` | rc=2 — 기존 2건 (`redfish_gather.py:5746` iLO, `:5890` XCC — 마지막 변경 `413bc039`). 이번 변경과 무관 |
| `check_project_map_drift.py` | 기존 drift(`tests`) → `--update` 로 fingerprint 갱신 |
| gate spike (2.20.3, 200 host, forks 200, free, 동시 2회) | PASS — include_role · role filter_plugins · 메인 filter 공존 · 상대 include · 미설정 skip |
| 실장비 V1~V8 | Linux(.161 raw / .165 / .167) · Windows(.120) · ESXi(.1) · Redfish(.15.34 dry-run) — V1 · V2 · V4 · V7 PASS, V3 · V5 · V6 · V8 측정 (evidence) |

## 2026-09-21 — failure_reason 문장 카탈로그 개편 회귀

> 정본: `docs/ai/decisions/ADR-2026-09-21-failure-reason-catalog.md`

| 항목 | 결과 |
|---|---|
| 변경 전 기준선 `pytest tests/ --ignore=tests/e2e_browser` | 3455 passed, 10 skipped, 7 xfailed |
| 변경 후 전수 (커밋 직전) | **3561 passed**, 10 skipped, 7 xfailed (+106) |
| `tests/unit/test_failure_reason_filter.py` (신설) | 30 passed — 채널/default 선택, 누락 키 예외, loc 표시 규칙, callback 복제본 동치 |
| `tests/e2e/test_errors_message_contract.py` (재설계) | 162 passed — 카탈로그 키 집합 고정, 전 문장 Grid 품질, precheck 복제본 drift, `_fr_code_keys` ↔ field_dictionary enum |
| `tests/e2e/test_failure_reason_case_matrix.py` | 50 passed — Vault 원인 5종 × 3대상, Redfish 시도 0회 3경우 CREDENTIAL_SET_UNAVAILABLE, loc fallback |
| `tests/e2e/test_diagnosis_template_ansible_render.py` (실제 Ansible Templar + filter_loader) | 22 passed (skip 0) |
| `ansible-playbook --syntax-check` 3채널 | Windows CLI 는 WinError 87 → **WSL ansible-core 2.20.7 에서 통과** |
| WSL 실제 실행 — 127.0.0.1 관리 포트 거부 (redfish / esxi / os) | 3건 모두 `TCP_CONNECTION_REFUSED` + 채널별 거부 문장, message == failure_reason, detail 보존 |
| WSL 실제 실행 — 가짜 ServiceRoot(8443) + `se_location=nope` | `auth` / `CREDENTIAL_SET_UNAVAILABLE` / "해당 위치(nope)가 개더링 프로젝트에 등록되지 않았습니다." (종전 GATHER_FAILED) |
| WSL 실제 실행 — 가짜 ServiceRoot + `se_location=ic`, Vault 비밀번호 없음 | 수정 전 `AUTH_PROBE_FAILED` + "…Redfish 표준 계정이 없습니다"(오분류) → 수정 후 `CREDENTIAL_SET_UNAVAILABLE` + "개더링 프로젝트의 Vault를 읽을 수 없습니다." |
| WSL 최소 재현 — include_vars + `failed_when: false` | 비밀번호 없음·틀린 비밀번호 모두 `is failed=False` (결함 확인) / `ignore_errors: true` 로 `is failed=True` |
| 실장비 / Portal | **미실행** — NEXT_ACTIONS FR-1 |

## 2026-09-03 — reachable ICMP OR 판정 회귀 (오프라인)

> 정본: `docs/ai/decisions/ADR-2026-09-03-icmp-or-reachability.md`

| 항목 | 결과 |
|---|---|
| `pytest tests/ --ignore=tests/e2e_browser` (전수) | **3312 passed**, 10 skipped, 7 xfailed |
| `pytest tests/unit/test_precheck_icmp_reachability.py` (신설) | 24 passed — OR 판정 / Gate 아님(TCP 응답 시 ICMP 미호출) / RST·DNS 경로 skip / 예산 1회 / 전용 code 금지 / envelope shape 불변 |
| 변경 전 기준선 대비 | 3269 → 3312 (+43: ICMP 24 + 채널별 OR 케이스 + 문장 매핑) |
| `python scripts/ai/hooks/output_schema_drift_check.py` | exit 0 — sections=11 fd_paths=192 |
| `python scripts/ai/verify_harness_consistency.py` | 통과 (rules 28 / skills 47 / agents 47 / policies 7) |
| `python scripts/ai/check_project_map_drift.py` | fingerprint 일치 |
| `python scripts/ai/verify_vendor_boundary.py` | exit 0 (기존 advisory 2건 — 본 변경과 무관) |
| `python -m py_compile common/library/precheck_bundle.py` | OK |
| YAML parse (`run_precheck.yml`, 3 channel `site.yml`, `field_dictionary.yml`, `failure_reasons.yml`) | OK |
| `ansible-playbook --syntax-check` | **로컬 미실행 — 환경 제약** (Windows 개발 PC 의 ansible CLI 가 `OSError WinError 87` 로 기동 불가). Jinja2 인라인 템플릿 컴파일은 `tests/e2e/test_section_message_contract.py` 가 대체 검증 |
| 실장비 (러너 10.100.64.154 직접 실행) | **4/4 확인** — 증거 `tests/evidence/2026-09-03-icmp-reachability-live.md` |
| RE-1 `ping` 가용성 | `cap_net_raw=ep` 로 비특권 동작. `ping_group_range = 1 0` → **비특권 ICMP 소켓 방식이었으면 실패**했을 조건 (구현 선택 실측 확인) |
| RE-2 ICMP만 응답 (redfish/.145, 관리 443 DROP) | `reachable=true` / `stage=port` / `TCP_CONNECT_FAILED` / 2번 문장. 종전이면 1번 문장이 나갔을 상황 |
| RE-2 TCP·ICMP 무응답 (os/.163) | `TARGET_UNREACHABLE` / 1번 문장(종전과 동일) / `detail` 에 `icmp: 응답 없음 (rc=1)` |
| RE-2 ICMP 차단 + TCP 정상 (os/.120 Windows) | precheck 정상 통과 (`reachable/port/protocol` 전부 true) — **Gate 아님 실측 확인** |
| RE-3 dead host 예산 | ICMP on 8.62·8.75s ↔ off 7.69·7.50s → **+1.0~1.1초/대** (설계값 일치) |
| Jenkins 파이프라인 `clovirone-server-gather` #200 (`os`: .163/.145/.120) | UNSTABLE(더미 callback — 의도) / 체크아웃 `1fd9fa6d` / envelope 3건: `.163` = `TARGET_UNREACHABLE`, `.145` `.120` = **`success`** (vault 자격증명까지 태운 실수집). `.120` 은 ICMP 차단 장비의 정상 수집 — Gate 아님 end-to-end 증거 |
| Jenkins 파이프라인 #201 (`redfish`: .145) | UNSTABLE(더미 callback) / 체크아웃 `1fd9fa6d` / `reachable=true` + `stage=port` + `TCP_CONNECT_FAILED` + 2번 문장. Stage 전량(Resolve Location→Validate→Gather→Validate Schema→Callback) 실행 |

## 2026-09-03 — 실장비 검증 (Jenkins `clovirone-server-gather` #190~#196, 운영 파이프라인 Jenkinsfile_portal)

> 증거: `tests/evidence/2026-09-03-os-esxi-live-verification.md` + 원본 envelope `tests/evidence/2026-09-03-live/*.json`

| 빌드 | 커밋 | 대상 | 결과 |
|---|---|---|---|
| #190 | `1fb2ae16` | os ×4: RHEL 8.10(raw fallback) / RHEL 9.6 / Dell R760 베어메탈 Ubuntu 24.04 / Windows Server 2022 | 4/4 success. 계약 점검 이슈 4건(Windows 팀 멤버 MAC 대시, IPv6 `%zone`, R760 정격 클럭 null, ESXi 값 2건) |
| #191 | `1fb2ae16` | esxi: 10.100.64.1 (7.0.3) | success, 이슈 0 (정격 2194 절삭·vmk0 down 지적) |
| #192 / #193 | `0076ca67` | os: R760 + Windows / esxi: 10.100.64.1 | 전부 success, 이슈 0 — 4건 정정 확인 |
| #194 | `0076ca67` | os ×3: .163(무응답) / .167 / .169 | .163 실패 envelope 이 새 계약대로(hostname null, 11 섹션, 표준 문장). .167/.169 는 .165/.161 VM 의 bond IP (lab 목록 오류). VM turbo 2093<2200 발견 → `d38bc31b` |
| #195 | `0076ca67` | esxi: 10.100.64.2 (esxi02, baseline 대상 장비) | success, 이슈 0. FC WWPN 소문자 colon, HBA vendor, UUID ↔ Redfish `uuid_equal` 일치 |
| #196 | `d38bc31b` | os: .161 raw VM + .96 R760 (turbo 가드 재검증) | 2/2 success, 이슈 0 — VM turbo `null`, R760 2400/4100 |
| #197 | `43a9f155` | os: .156(Ubuntu 24.04 VM) + .163 | .156 success (VMware SMBIOS `Max Speed 30000` 이 turbo 로 실림 → `549f84ff`), .163 무응답 |
| #198 | `43a9f155` | os: 10.100.64.145 (RHEL 9.6 VM, 사용자 지정) | success, 이슈 0 |
| #199 | `549f84ff` | os: .156 + .145 (SMBIOS 클럭 범위 가드 재검증) | 2/2 success, 이슈 0 — .156 turbo `null` |
| `pytest tests/ --ignore=tests/e2e_browser` (d38bc31b) | — | — | **3269 passed, 10 skipped, 7 xfailed (2026-09-03, d38bc31b)** |
| Jenkins Stage 3 (Validate Schema) | — | 7 빌드 | 전부 통과 (WARN 은 예시 미포함 advisory) |
| Stage 4 Callback | — | 7 빌드 | 더미 URL(192.0.2.1) → 408 → **UNSTABLE 은 의도된 결과** (rule 31 R2) |

**Jenkins 체크아웃 SHA 확인**: 각 빌드 콘솔의 Gather stage `Checking out Revision` = 대상 커밋 (rule 14). Agent `jenkins-agent-ops`, ansible-core 2.20.3.

## 2026-09-03 — OS(Linux/Windows) / ESXi 게더링 전수 검수 후속 (37건 정정) 회귀

| 항목 | 결과 |
|---|---|
| `pytest tests/ --ignore=tests/e2e_browser` (전수) | **3265 passed**, 10 skipped, 7 xfailed (변경 전 기준선 2873 passed → 신규 테스트 7 파일 반영) |
| `pytest tests/unit` | 2222 passed |
| `pytest tests/regression` | 169 passed, 7 xfailed |
| `pytest tests/e2e` | 631 passed, 6 skipped |
| `pytest tests/integration -m "not live"` | 243 passed, 3 skipped |
| 신규 테스트 | `test_identity_normalizer.py`(30) / `test_gather_identity_render.py`(21) / `test_always_fallback_envelope.py`(3) / `test_failed_output_partial_and_hostname.py`(6) / `test_field_dictionary_channel_emit.py`(8) / `test_cross_channel_uuid_equal.py`(2) / `test_esxi_disks_host_info.py`(4) |
| 갱신 테스트 | `test_os_network_render.py`(raw 단일 구현 + normalize_mac) / `test_esxi_section_errors.py`(host_info 스텁, 인터페이스 컨텍스트, 섹션 failed 케이스) / `test_windows_runtime_ports_str_r18.py`(gather_runtime 정본) / `test_windows_firewall_state_r19.py`(빈 프로필 = null) / `test_envelope_failure_modes.py`(hostname null 허용 + `hostname != ip`) |
| `tests/validate_field_dictionary.py` | RESULT: PASS (8/8 — 신규 3 path 는 예시 미포함 WARN) |
| `output_schema_drift_check` | exit 0 (sections=11 / fd_paths=192) |
| `envelope_change_check` | advisory 1건 — `diagnosis.auth_success` 후보(기존 사전 항목, 이번 변경 무관). envelope 13 필드 무변경 |
| `pre_commit_jinja_compile_check --all --blocking` / `pre_commit_jinja_namespace_check` / `pre_commit_fragment_skeleton_sync` | 전부 exit 0 |
| `pre_commit_placeholder_fallback_check --all` (신규 advisory) | self-test PASS, 저장소 전수 0건 |
| `verify_harness_consistency` | exit 0 (rules 28 / skills 47 / agents 47 / policies 7) |
| `verify_vendor_boundary` | exit 2 — **기준선과 동일** 2건(`redfish_gather.py` iLO/XCC), OS/ESXi 신규 위반 0 |
| YAML parse / `py_compile` | 변경 YAML 45종 + `esxi_disks.py` + `identity_normalizer.py` OK |
| `ansible-playbook --syntax-check` | **미실행 — 환경 제약** (Windows 세션 ansible-core 2.21.3 CLI 진입부 `os.get_blocking` 예외). YAML parse + 저장소 전수 Jinja compile + 표현식 렌더 테스트로 대체 |
| **실장비** | **미실행** — Linux(python/raw) / Windows / ESXi / R760 bare-metal 재수집 0건. baseline 10건 미재생성 (NEXT_ACTIONS GA-1 / GA-2) |

값 대조 근거: `tests/reference/os/{rhel-baremetal,win2022,rhel810,ubuntu2404}` 캡처와
`tests/reference/esxi/10_100_64_1/pyvmomi_host_dump.json` (cpuMhz=2195 / dnsConfig.hostName=esxi01 /
vnic ipRouteSpec.defaultGateway=10.100.64.254) 을 렌더 테스트 입력으로 썼다.

## 2026-08-27 — OS 채널 CSUS 3200 nPartition 시리얼 접미사 정규화 회귀

| 항목 | 결과 |
|---|---|
| `pytest tests/unit` | **2131 passed**, 1 skipped (종전 2130 → +1 파일 79건 중 기존 중복 제외) |
| 신규 테스트 파일 | `tests/unit/test_csus_partition_serial.py` — **79 passed** |
| `pytest tests/regression` | 169 passed, 7 xfailed |
| `pytest tests/e2e` | 558 passed, 28 skipped |
| `pytest tests/integration -m "not live"` | 243 passed, 3 skipped |
| Jinja 렌더 회귀 | 신규 task 3종을 `NativeEnvironment`(= `jinja2_native=True` 등가)로 렌더해 **값 + 타입** 확인. 비-CSUS 입력은 변경 전후 결과가 전부 동일 (숫자 시리얼의 int 변환은 `resolve identifiers` 단계에서 이미 발생하는 기존 동작) |
| `output_schema_drift_check` / `envelope_change_check` / `pre_commit_additive_only_check` | 전부 exit 0 (envelope 13 필드 무변경) |
| `pre_commit_jinja_compile_check` / `pre_commit_jinja_namespace_check` / `pre_commit_regex_search_conditional_check` / `pre_commit_fragment_skeleton_sync` / `pre_commit_harness_drift` | 전부 exit 0 |
| `verify_harness_consistency` | exit 0 |
| `verify_vendor_boundary` | exit 2 — **기준선과 동일**. 2건 모두 `redfish-gather/library/redfish_gather.py`(iLO / XCC)로 이번 변경 이전부터 존재. os-gather 신규 위반 0건 (stash 대조 확인) |
| `validate_field_dictionary.py` | RESULT: PASS (8/8, 실패 0) |
| YAML parse / `py_compile` | 변경 YAML 3종 + `serial_normalizer.py` 전부 OK |
| `ansible-playbook --syntax-check` | **미실행 — 환경 제약** (Windows 세션에 ansible 미설치). YAML parse + 저장소 전수 Jinja compile 회귀(`test_section_message_contract`)로 대체 |
| **실장비** | **미실행** — CSUS 3200 lab 부재. OS 측 DMI 표기 실측이 후속 (NEXT_ACTIONS CSUS-OS-1) |

목데이터 근거: `tests/fixtures/redfish/real_hpe_csus3200/recording.json`
(`Systems/Partition0.SerialNumber="SGHD3TLNDD-000"` / `Chassis/r001u01` =
`HPE` + `"Compute Scale-up Server 3200, 4S XNC Base Chassis"` + `"SGHD3TLNDD"`)
→ 정규화 결과가 물리 Chassis 시리얼과 일치함을 테스트가 직접 대조한다.

## 2026-08-14 — Location ID `ich` → `ic` 개명 회귀

| 항목 | 결과 |
|---|---|
| `pytest tests/` | **3062 passed**, 10 skipped, 7 xfailed |
| Location 직접 영향 4 파일 | `test_credential_resolver` / `test_location_registry` / `test_redfish_standard_recovery_contract` / `test_vault_check_no_secret_output` + `test_failure_code_contract` = 194 passed |
| `vault_decrypt_check.py --layout-only` | `ic: 12/12` / `chj: 12/12` / `yi: 12/12` / `git: 12/12` |
| `output_schema_drift_check` | exit 0 (sections=11 fd_paths=176) |
| `verify_harness_consistency` | exit 0 |
| YAML parse / `py_compile` | locations.yml / field_dictionary.yml / credential task 2종 / `credential_common.py` 전부 OK |
| `ansible-playbook --syntax-check` | **미실행 — 환경 제약** (Windows 세션에 ansible 미설치). 변경분이 주석뿐이라 YAML parse 로 대체 |
| **실장비** | **미실행** — Jenkins 노드 label 재설정(LOC-1) 전까지 `loc=ic` 잡이 Agent 를 못 잡는다 |

## 2026-08-13 — 계정 쓰기 계약 정합 (9 Vendor 조사 반영)

| 항목 | 결과 |
|---|---|
| `pytest tests/` | **3063 passed**, 10 skipped, 7 xfailed (종전 2843 → +220) |
| 신규 테스트 파일 | `test_account_no_write_fallback.py`(27) / `test_account_diagnosis_axes.py`(15) / `test_account_write_contract_invariants.py`(146) |
| 반전 테스트 | `test_unverified_family_keeps_the_legacy_post_retry` → `..._writes_once_and_never_retries`, `test_m_b3_inspur_isbmc_post_400_then_retry` → `..._writes_once_and_fails` (제거 대상 동작을 고정하고 있었다) |
| `ansible-playbook --syntax-check` ×3 | PASS (WSL ansible-core 2.20.7) |
| `output_schema_drift_check` / `verify_vendor_boundary` / `verify_harness_consistency` / `verify_no_plaintext_secret` / `check_project_map_drift` | 전부 exit 0 |
| baseline / replay / envelope 회귀 | 385 passed |
| e2e | 590 passed |
| **실장비** git 4대 × (Check Mode + 1차 + 2차) | 전부 `success` / `used_role=primary` / **Account Write 0** |

정본: `tests/evidence/2026-08-13-account-write-contract-alignment.md`

미증명 유지: Account CREATE 는 조건이 발생하지 않았다. 4대 모두 표준 계정이 정상이었다.
Supermicro / Huawei / Inspur / Fujitsu / Quanta 는 실장비 0대.


> 테스트 실행 / Round 검증 / Baseline 갱신 이력 (append-only, rule 70).

## 2026-08-12 (q) — Vault 갱신 후 전량 회귀 + git 실장비 검증

- **정적 회귀**: unit 1792 / regression 169 (+7 xfailed) / e2e 590 (+6 skipped) /
  integration(not live) 243 (+3 skipped) = **2794 passed**, 실패 0.
  Vault 값 변경이 코드 회귀를 유발하지 않음을 확인했다.
- **py_compile**: `redfish_gather.py`, `precheck_bundle.py`, `credential_common.py`,
  `credential_resolver.py`, `credential_accounts.py` 전부 OK.
- **ansible syntax-check** (WSL ansible-core 2.20.7): os / esxi / redfish 전부 exit=0.
- **Gate**: verify_vendor_boundary 0 / verify_harness_consistency 0 /
  output_schema_drift_check 0 / validate_field_dictionary PASS /
  **vault_decrypt_check 전량 통과(exit=0)**.
- **실장비 7대상 (git Location)**: production 과 동일한 ansible-playbook 을 호출했다.
  성공 6 / HOLD 1(Dell). Redfish 3대는 `credential_scope=common/redfish/standard` +
  used_role=primary + **Account Write 0**, Lenovo·Cisco 는 **2차 실행 Write 0** 까지 확인.
- **read-only Redfish probe**: Dell 2대(.34/.27), Lenovo, HPE, Cisco 에서 ServiceRoot /
  Manager / AccountService / Roles / Accounts / OEM Attributes / Attribute Registry 를
  쓰기 0건으로 수집했다. Dell 비밀번호 정책을 규명한 근거다.
- 정본: `tests/evidence/2026-08-12-git-location-live-verification.md`

## 2026-08-12 (p) — Redfish 계정 Reconcile Family Strategy 회귀

- **기준선(변경 전 직접 측정)**: unit+regression 1907 passed / 7 xfailed (66.55s),
  e2e 587 passed / 6 skipped (13.07s), integration(not live) 200 passed / 3 skipped (1.71s)
  = **2694 passed**.
- **변경 후**: unit+regression 1961 (18.05s), e2e 590 (12.46s),
  integration 243 (2.75s) = **2794 passed**, 실패 0.
- **신규 파일**
  - `tests/unit/test_account_capability_and_presence.py` (20). 3-상태 열거 / 4-상태 존재 판정 /
    ServiceRoot 링크 추종 / 정책 파싱, 그리고 **부분 조회 실패 시 Write 0건** 회귀(C-1).
  - `tests/unit/test_account_family_and_write_contract.py` (33). Family 결정성, Dell iDRAC10
    reserved slot 2, Cisco Roles 어휘 기반 판정, Lenovo Purley slot PATCH, Supermicro
    Firmware 경계, Inspur OEM Status/ETag, 검증 의무화, check_mode, lockout 예산,
    상태 수렴(Disabled/Locked/Role/PasswordChangeRequired/AccountTypes).
  - `tests/integration/account_replay.py` + `tests/integration/test_account_reconcile_replay.py` (43)
    로 **실장비 미러 재생** (Dell 5호스트 / HPE 1 / Lenovo 1 / Cisco 1). 감사 D-8 해소.
  - `tests/unit/account_seam.py` 는 기존 3-tuple fake 를 discovery dict 로 감싸는 공용 seam 이다.
- **갱신 파일**: 계정 관련 unit 5종 + e2e 2종. seam 이동(`account_service_get` ->
  `account_service_discover`)과 의도된 동작 변경(POST 사다리 제거 / 검증 의무화 /
  `verification='none'` 불인정 / backoff 조건화)을 반영.
- **부수 효과**: 계정 테스트에 `time.sleep` monkeypatch autouse fixture 를 넣어 audit M-9 을
  해소했다. 8개 테스트가 각 6초씩 블로킹하던 건이다. unit+regression 수트가 **66.55s -> 18.05s**.
- **Ansible syntax-check** (WSL Ubuntu, ansible-core 2.20.7): os/esxi/redfish 전부 exit=0.
- **게이트**: verify_vendor_boundary exit=0 (신규 Family 표 13라인 `# nosec rule12-r1` 표기 후),
  verify_harness_consistency exit=0, output_schema_drift_check exit=0,
  validate_field_dictionary PASS, vault_decrypt_check --layout-only exit=0.
- **실장비 0건.** `ansible-playbook` 실행 0건, Account Write 0건.

## 2026-08-11 (o) — Dell 대표 시리얼 교정 회귀 (ServiceRoot Service Tag)

- **신규**: `tests/unit/test_dell_service_tag_serial.py` 41건.
  ServiceTag 정상 + System 정상(fixture `dell` / `dell_r760` / `real_dell_r740`) /
  ServiceTag 정상 + System 수집 실패(→ partial+null 금지) / ServiceTag 없음 4종 /
  invalid 10종(`NA` `N/A` `None` `Not Specified` `To Be Filled By O.E.M.`
  `System Serial Number` `0` `00000000` `""` 공백).
  **폴백 금지 실증** 14케이스에서는 결과에 `SerialNumber`·`SKU`·`ChassisServiceTag`·`NodeID` 가
  0회 등장한다. 무인증↔인증 ServiceRoot 노출 차이와 재조회 횟수도 확인.
  **serial null 0건 불변식** / 비-Dell 무회귀.
- **신규**: `tests/e2e/test_redfish_baseline.py::TestDellServiceTagIsRepresentativeSerial`.
  최종 envelope 의 `data.hardware.serial` == `correlation.serial_number` ==
  raw fixture `Oem.Dell.ServiceTag` 를 비교한다. 기대값은 하드코딩하지 않고 fixture 에서 읽는다.
- **기준선 갱신 (Dell 3종만, 전부 재생 산출값)**:
  `real_dell_r740/expected_output.json` `CNIVC0098G0600`→`J0KV603` ·
  `dell_r760_output.json` `CNIVC004950455`→`64CXJ54` ·
  `schema/baseline_v1/dell_baseline.json` `CNIVC009CP0282`→`2BJ8033`.
  비-Dell baseline 9종 + 실미러 골든 3종(HPE/Lenovo/CSUS) **무변경 통과**.
- **실장비 대조 7대**: reference 미러 5대 + fixture 2대 전부 `Oem.Dell.ServiceTag` 가 있고
  `SerialNumber` 와 상이. R760-6 은 Redfish `GSBPK54` == Linux SMBIOS Type 1 `GSBPK54`.
- **결과**: unit 1186 passed / e2e 416 passed·6 skipped / integration 200 passed·3 skipped /
  regression 169 passed·7 xfailed. `validate_field_dictionary` / `verify_vendor_boundary` /
  `verify_harness_consistency` PASS.
- **실 Jenkins 실행 (2026-08-11 사후)**, job `clovirone-server-gather`:
  - **#188** `target_type=redfish`, BMC 10.100.15.27 / 10.100.15.34 → 각각
    `hardware.serial` = `correlation.serial_number` = `64CXJ54` / `GSBPK54`,
    status=success, errors 0, envelope 13필드 일치, Stage 3 Validate Schema PASS,
    콘솔 전체 `CNIVC` 0회.
  - **#189** `target_type=os`, 10.100.64.96 (위 .34 의 짝) → `correlation.serial_number=GSBPK54`.
  - 동일 `system_uuid` 위에서 두 채널 serial **SAME** (교정 전 DIFFERENT).
  - 두 빌드 `UNSTABLE` 은 미라우팅 콜백(`192.0.2.1`) timeout 때문이며 수집과는 무관하다 (rule 31 R2).
- 증거: `tests/evidence/2026-08-11-dell-serial-service-tag.md`.

## 2026-08-11 (m) — 실환경 검증 (Phase 6-A)

- **실장비 실측** (lab 네트워크 직접 도달):
  - ESXi 3대(10.100.64.1/2/3, 전부 7.0.3 build-20842708) 에서 `/sdk` POST wire 응답 확인.
    `versionId=6.0` 수락 / HTTP 200 / `RetrieveServiceContentResponse` /
    `about.apiType=HostAgent` / `apiVersion=7.0.3.0` / `parse_service_content` True.
  - BMC 11대 중 9대는 `probe_redfish` OK. **무인증 ServiceRoot 401/403 = 0대**.
    cisco .1 은 502/503 으로 흔들려 테스트 flaky 위험. cisco .3 다운.
  - OS 7대 중 Linux 5대는 SSH identification 확인(`SSH-2.0-OpenSSH_8.0/8.7/9.6p1`).
    rhel920 .163 은 전 포트 timeout 이며 `TCP_CONNECT_FAILED` 의 실제 사례다.
  - Windows 1대는 수정 전 401 실패, **수정 후 200 + IdentifyResponse 확인**.
- **Linux 실제 Ansible CLI**: `ansible-playbook --syntax-check` 3 채널 exit 0
  (WSL Ubuntu 24.04.3 / ansible-core 2.20.7 / vault 암호 적용). **최초 실제 통과**.
- **신규**: `tests/unit/test_soap_header_case_preserved.py` 15건.
  `http.client` 를 seam 으로 잡아 헤더 이름 정규화 재발을 차단한다.
  `WSMANIDENTIFY` / `SOAPAction` / `Content-Type` 보존, 요청 shape 불변,
  http/https 분기, 비-2xx status 보존, timeout·refused 분류, max_bytes, 민감정보 미포함,
  실장비 응답 그대로를 넣은 `probe_os` 통합 확인.
- **전체 회귀**: `pytest tests/` → **1775 passed, 11 skipped, 7 xfailed**
- **하네스**: harness / boundary / output_schema_drift / envelope_change / cross_channel exit 0,
  field_dictionary PASS, `schema/` 무변경.
- **수행 시간 실측**: ESXi probe 0.06~0.11s / Redfish probe 0.13~1.20s(죽은 호스트 31.1s) /
  Linux precheck 4.06~4.09s / Windows precheck 0.19s(수정 후) / OS 전 포트 실패 6.03s /
  전체 playbook: ESXi 25.1s, Redfish 133.3s, Linux 29.7s.

## 2026-08-11 (l) — Portal Grid 실패 사유 + 자격 실패 분류 검증 (Phase 5-A)

- **신규**: `tests/e2e/test_failure_reason_case_matrix.py` 27건
  - 18 Case 를 최종 diagnosis 까지 렌더 (precheck 6건은 `run_module()` 실제 실행,
    rescue 12건은 site.yml `_diagnosis` 템플릿 추출 렌더)
  - **§29 단계 진행 관계 Contract**: 문장이 주장하는 앞 단계 성공을 Machine Diagnosis 로
    증명 (`관리 연결은 확인되었지만`→port_open / `<서비스>는 확인되었지만`→protocol_supported /
    `접속은 확인되었지만`→auth_success). 문구와 Boolean 이 어긋나면 실패
  - reachable 단계가 "통신은 되지만" 을, port 단계가 "서버는 응답하지만" 을 쓰지 않는지
  - `정보 수집 후` 는 수집 성공이 관측된 경로에서만
  - 18 Case 전수 민감정보 미노출
- **신규**: `tests/e2e/test_credential_probe_classification.py` 13건. 4 채널 자격 probe
  파일이 문자열 파싱으로 인증 실패를 확정하지 않는지, `auth_success` 를 분산 판정하지 않는지,
  **인증 시도 횟수 / retry / lockout backoff 가 그대로인지**, 403 을 거부로 만들지 않는지
- **신규**: `tests/unit/test_redfish_auth_evidence.py` 14건. `auth_evidence` 가
  자격증명 요청의 첫 정수 status 만 기록 / 무인증 요청 미기록 / status=0 미기록 /
  첫 관측 고정 / 반환값 불변 / invocation 단위 초기화 / 자격증명 미포함 / 문자열 미수용
- **갱신**: `test_failure_reason_contract.py` 에 §26·§27 단언 추가
  (관리 포트 `22/443/5985/5986` 금지, HTTP status 금지, timeout 초 금지,
  내부 기술 용어 14종 금지). OS 포트 실패 검증은 precheck 실제 실행 기반으로 교체했고,
  삭제한 PLAY 1.5 덮어쓰기 태스크가 되살아나면 실패하는 가드를 넣었다
- **갱신**: `test_esxi_precheck_contract.py` / `test_os_candidate_search.py` /
  `test_os_precheck_polling.py` / `test_failure_code_contract.py` 를 새 문구 계약으로
- **동기화**: `schema/examples/redfish_{failed,not_supported}.json`,
  `schema/output_examples/redfish_failed.jsonc`, `docs/contract/03-fields.md` 예시 문구
- **전체 회귀**: `pytest tests/` → **1731 passed, 11 skipped, 7 xfailed**
- **Jenkins 등가**: Stage 3(output_schema_drift) PASS / unit 1063 / e2e 299 /
  integration 200 / regression 169 / field_dictionary PASS
- **하네스**: harness / boundary / output_schema_drift / envelope_change / cross_channel exit 0
- **정적**: py_compile 2파일 / YAML 78파일 파싱 / Jinja2 문자열 스칼라 893개 컴파일 0오류
- **보정 회귀 (2026-08-11)**: `tests/e2e/test_redfish_multi_credential_auth.py` 29건
  - 사용자 지정 8 조합(401+401 / timeout+401 / 401+timeout / 403+401 / 401+403 /
    transport+401 / 401+성공 / 단일 401) → **1번과 8번만 false, 나머지 전부 null**
  - 경계: 후보 0개 / 관측 누락 / 관측 초과 / 비-401 혼입 10종 / 후보 1·2·3·5개 전부 401
  - `first_auth_status` 가 첫 인증 응답임을 고정 (200 뒤의 401 은 승격 안 됨),
    무인증 요청은 기록 안 됨, 집계에 문자열 파싱 없음
  - 판정식은 **실제 Jinja2 `select('equalto', 401)`** 로도 동일 결과 교차 확인
- **전체 회귀 (보정 후)**: `pytest tests/` → **1760 passed, 11 skipped, 7 xfailed**
  (unit 1063 / e2e 328 / integration 200 / regression 169)
- **미실행**: `ansible-playbook --syntax-check`. Windows 개발 환경에 `ansible-playbook` 이
  없다. 성공으로 표기하지 않는다.

## 2026-08-10 (k) — ESXi vim25 SOAP 판정 검증 (Phase 4-B)

- **신규 fixture**: `tests/fixtures/esxi/` (README 에 출처 기록, rule 21 R2)
  - `lab/esxi_7_0_3_service_content.xml` 은 lab ESXi 3대(10.100.64.1/2/3, 모두
    ESXi 7.0.3 build-20842708, `apiType=HostAgent` / `apiVersion=7.0.3.0`)의 실측
    AboutInfo(`tests/reference/esxi/*/pyvmomi_host_dump.json` → `config_product`)를
    pyVmomi 직렬화기로 감싼 것이다. 생성 후 pyVmomi `SoapResponseDeserializer` 로 되읽어
    `vim.ServiceInstanceContent` 복원까지 확인.
  - `synthetic/` 에는 ESXi 6.0 / 6.7 / 8.0 / vCenter 8.0 ServiceContent(합성) +
    vim25 Fault 2종 + 일반 SOAP Fault 1종(음성 표본).
  - **wire capture 아님** — 해당 버전을 "검증 완료" 로 표기하지 않는다.
- **재작성**: `tests/unit/test_precheck_probe_esxi.py` 54건
  - 요청 검증: `POST /sdk` / `RetrieveServiceContent` 본문 / SOAP 1.1 Content-Type /
    `SOAPAction: "urn:vim25/6.0"` / ServiceContent 전용 본문 상한 / **자격증명 미전송** /
    TLS 정책 유지 / **retry 없음(요청 1회)**
  - Positive: lab ServiceContent / 버전 4종 fixture / 네임스페이스 접두사 변형 /
    비-200 이어도 본문이 ServiceContent 면 통과 / vim25·internalvim25 Fault 2종
  - **False Positive 13 본문 + HTTP status 단독 9종 전부 거부**: 일반 HTML / 일반 JSON /
    일반 XML / 빈 SOAP Envelope / 다른 SOAP 서비스 Response / 일반 SOAP Fault / 잘린 XML /
    vSphere 문자열만 있는 XML / 다른 vim25 응답(LoginResponse) / about 없음 /
    apiType 없음 / apiVersion 공백 / 네임스페이스 없는 Response /
    **HTTP 200·301·302·401·403·404·405·500·503 단독**
  - Evidence 위생: 실패 사유에 raw SOAP 덤프 금지 / 본문 상한 초과 거부
- **신규**: `tests/unit/test_esxi_precheck_contract.py` 14건. `run_module()` 전 경로에서
  Diagnosis 계약을 고정한다. protocol_supported / `auth_success` 항상 `null`(401·403 포함) /
  `protocol` + `PROTOCOL_CHECK_FAILED` / Phase 1 failure_reason 문구 / probe_facts 키 집합
  불변 / TCP 실패 시 Probe 미전송 / timeout 전달 / 민감정보 미노출
- **수정**: `test_os_candidate_search.py`·`test_os_precheck_integration.py` 의 esxi 회귀
  케이스에 `http_post_soap` stub 추가, `test_failure_reason_contract.py` 의 `_run_precheck`
  가 두 seam 을 함께 대체하도록 보정(+ stale 주석 정정).
- **전체 회귀**: `pytest tests/` → **1676 passed, 11 skipped, 7 xfailed**
- **Jenkins 등가**: Stage 3(output_schema_drift) PASS / unit 1049 / e2e 258 /
  integration 200 / regression 169
- **하네스**: harness / boundary / output_schema_drift / envelope_change / cross_channel exit 0
- **OS / Redfish 회귀 0**: `probe_os` / `ssh_banner_check` / `parse_identify_response` /
  `probe_redfish` / `parse_service_root` / `http_get` 전부 미변경. 공통 `http_post_soap` 는
  인자만 추가했고 **기본값이 종전과 같아** WinRM Identify 동작 불변.
- **미실행**: `ansible-playbook --syntax-check`. Windows 개발 환경에는 `ansible-playbook` 이
  없다. POSIX 전용 `os.get_blocking` 에 의존하기 때문이다. 성공으로 표기하지 않는다.
  대안으로 YAML 파싱 28파일 + Jinja2 문자열 스칼라 239개 컴파일 0오류 확인.

## 2026-08-10 (j) — Redfish ServiceRoot 판정 검증 (Phase 4-A)

- **신규**: `tests/unit/test_redfish_service_root_fixtures.py` 40건.
  저장소의 ServiceRoot 응답을 **전수** 판정한다.
  - `service_root.json` 28개 (cisco 4 / dell 5 / fujitsu 2 / hpe 6 / huawei 3 /
    inspur 1 / lenovo 3 / quanta 1 / supermicro 3) → **전부 PASS**
  - `recording.json` 의 비인증 `noauth::` 10개 (DMTF 표준 mockup 1 + HPE 에뮬레이터 5 +
    실장비 캡처 4: dell_r740 / hpe_csus3200 / hpe_dl380 / lenovo_sr650) → **전부 PASS**
  - fixture 개수 감소 감시 + "ServiceRoot 에서 비-200 을 반환하는 캡처가 생기면 실패" 가드
- **재작성**: `tests/unit/test_precheck_probe_redfish.py`.
  - Positive: ServiceRoot 인정 / trailing slash 2종 / RedfishVersion 4종 /
    ServiceRoot 스키마 버전 3종 / 자격증명 미전송 / verify=False 유지
  - **False Positive 17조합 전부 거부**: HTML(JSON 아님) / 빈 JSON / 일반 JSON /
    Redfish 무관 OData JSON / JSON Array / JSON 문자열 / @odata.type 없는 유사 JSON /
    @odata.id 불일치 / RedfishVersion 빈 문자열 / RedfishVersion 부재 /
    **HTTP 401·403·404·405·406·500·503 단독**
  - retry 정책 불변 확인 3건 (payload=None 만 재시도 / HTTP 응답 시 재시도 없음 /
    200 이지만 ServiceRoot 아닐 때도 재시도 없음), evidence 길이 제한
- **수정**: 다른 테스트의 ServiceRoot stub 4곳을 유효 shape 로 교체.
  `test_precheck_robustness.py` 의 비-dict JSON 케이스는 "crash 안 함 + ok=True" 에서
  "crash 안 함 + Redfish 아님으로 거부" 로 기대값 갱신.
- **전체 회귀**: `pytest tests/` → **1631 passed, 11 skipped, 7 xfailed**
- **Jenkins 등가**: Stage 3 PASS / e2e 258 / integration 200 / unit 1001 / regression 169
- **하네스**: harness / boundary / output_schema_drift / envelope_change / cross_channel exit 0
- **OS / ESXi**: `probe_os` / `probe_esxi` / 후보 탐색 / 포트 폴링 미변경.
  `http_get` 도 미변경(Phase 3-B 에서 추가한 headers 키 그대로). 두 채널 회귀 0.
- **schema/**: 파일 변경 0
- **환경 제약**: `ansible-playbook --syntax-check` **미실행**. Windows 에서는
  `os.get_blocking` 이 POSIX 전용이다. 대신 YAML 파싱 5종과 Jinja2 166 표현식을
  전수 컴파일해 실패 0.
- **실장비 미검증 영역**: ServiceRoot 에서 인증을 요구하는 펌웨어. 저장소에 캡처가 없어
  제거된 401/403 예외가 실제로 필요한지 확인할 수 없다. 해당 장비를 만나면
  PROTOCOL_CHECK_FAILED 로 차단된다.

## 2026-08-10 (i) — WinRM WS-Management Identify 판정 검증 (Phase 3-B 최종)

- **재작성**: `tests/unit/test_precheck_probe_os.py` 30건.
  - Positive: 5985 / 5986 정상 IdentifyResponse, 네임스페이스 표기 변형 2종,
    Identify 요청 형식(SOAP POST + `WSMANIDENTIFY: unauthenticated` + `/wsman` + verify=False)
  - **False Positive 11조합 전부 거부**: 단순 200(일반 웹서버 HTML) / 401 / 403 / 404 /
    405 / 500 / 일반 XML / 다른 네임스페이스의 IdentifyResponse / ProtocolVersion 없음 /
    ProtocolVersion 이 WS-Management 아님 / 잘린 IdentifyResponse
  - **헤더 heuristic 제거 확인**: `_looks_like_wsman` 부재 + Microsoft-HTTPAPI/401 거부
  - **비-Windows WS-Man 장비**(Openwsman) 를 Windows 로 판정하지 않음
  - XML 폭탄 방어(64KB 상한) / TLS handshake 실패 / timeout / 자격증명 미전송
- **SSH**: 구현 변경 없음. 기존 23건 중 SSH 관련 테스트 그대로 통과
  (identification 2종 / 선행 추가 줄 / SMTP 배너 거부 / 무응답 / 알 수 없는 protoversion / 읽기 상한).
- **Timeout 최악 계산**: 죽은 호스트 6초(Phase 3-A 대비 불변) / 정상 Windows 7초 /
  정상 Linux 11초 / 전 포트 열림 + 프로토콜 전멸 21초.
- **전체 회귀**: `pytest tests/` → **1566 passed, 11 skipped, 7 xfailed**
- **Jenkins 등가**: Stage 3 PASS / e2e 258 / integration 200 / unit 936 / regression 169
- **하네스**: harness / boundary / output_schema_drift / envelope_change / cross_channel exit 0
- **Redfish/ESXi**: `http_get` 미변경(새 `http_post_soap` 분리) → 두 채널 소비 경로 영향 0.
  regression 169 · integration 200 · baseline 10 통과.
- **schema/**: 파일 변경 0
- **환경 제약**: Windows 개발 환경이라 `ansible-playbook --syntax-check` 는 **미실행**
  (`os.get_blocking` 이 POSIX 전용). 대체 수단은 YAML 파싱 5종 + Jinja2 166 표현식
  전수 컴파일이며 실패 0.
- **한계 (보고 대상)**: lab 에 Windows WinRM 실장비가 없어 IdentifyResponse 는 **규격 기반**이며
  실측 캡처가 아니다. 네임스페이스 표기(http/https, .xsd 유무)를 4가지 허용해 방어했으나
  실장비 확보 시 실제 응답으로 재확인이 필요하다.
- **SSH 읽기 상한은 정책값**: 8줄 / 2048바이트. RFC 4253 은 선행 줄 상한을 정하지 않으며
  OpenSSH banner(/etc/issue.net)는 통상 3~10줄이다. 매우 긴 banner 를 쓰는 사이트에서는
  identification 을 놓칠 수 있어 상한 조정이 필요할 수 있다.

## 2026-08-10 (h) — OS Protocol 판정 강화 검증 (Phase 3-B)

- **신규**: `tests/unit/test_os_candidate_search.py` 24건. run_module 을 실제로 돌려
  후보 탐색 전 경로를 검증한다.
  - Case 1~4 정상 판정(5986 / 5985 / 22) + scheme + checked_ports
  - Case 12 열린 포트는 있으나 프로토콜 전멸 → `protocol` + `PROTOCOL_CHECK_FAILED`,
    `port_open=true` / `protocol_supported=false` / `detected_os=None`
  - Case 13 앞 후보 실패 후 뒤 후보 성공 → 전체 성공
  - Case 11 TCP 전멸 4조합 → Phase 3-A 매핑 유지, 프로토콜 probe 미호출
  - Case 16 auth_success 는 어떤 경우에도 null
  - Case 14 checked_ports 5조합 (중복 없음)
  - 폴링 인자 보존 (포트별 예산 2초 / poll 1초 / 순서)
  - Case 18 redfish/esxi 는 후보 탐색을 타지 않음 + probe_protocol=false 경로 잔존 확인
- **재작성**: `tests/unit/test_precheck_probe_os.py` 23건. 종전 상태 코드 whitelist
  테스트(200/401/403/405/503 → WinRM)를 폐기하고 헤더 근거 기반으로 교체.
  - **False Positive 8조합**: nginx/Apache 의 200 / 404 / 403 / 405 / 503 /
    `Basic realm="Restricted"` 401 / 헤더 없음 → **전부 거부**
  - WSMAN realm / Microsoft-HTTPAPI + 인증요구 → 인정
  - SSH: 정상 identification 2종 / 선행 추가 줄 3줄 후 identification / SMTP 배너 거부 /
    무응답 거부 / 알 수 없는 protoversion 거부 / 읽기 상한 확인
  - `/wsman` 기본 경로 + `verify=False` 확인, probe 가 자격증명 미전송 확인
- **PLAY 1 → PLAY 1.5 시뮬레이션**: 9 시나리오를 실제 템플릿으로 렌더.
  OS 판정 / scheme / protocol_supported / stage / code / auth / checked_ports / reason 전부 기대 일치.
- **전체 회귀**: `pytest tests/` → **1559 passed, 11 skipped, 7 xfailed**
- **Jenkins 등가**: Stage 3 PASS / e2e 258 / integration 200 / unit 929 / regression 169
- **하네스**: harness / boundary / output_schema_drift / envelope_change / cross_channel exit 0
- **Baseline / schema**: 파일 변경 0
- **환경 제약**: `ansible-playbook --syntax-check` 는 **미실행** 이다. Windows 이고
  `os.get_blocking` 이 POSIX 전용이다. 갈음한 확인은 YAML 파싱 5종, Jinja2 166 표현식
  전수 컴파일 실패 0.
- **구현 한계 (보고 대상)**: 자격증명 없이 WS-Management handshake 를 완결할 수 없어 WinRM
  판정은 **헤더 근거 기반**이다. (2) `Server=Microsoft-HTTPAPI + 인증요구` 는 결정적 증거가
  아니라 강한 정황이다. 완전한 판정은 Credential Probe 영역이며 이번 범위 밖이다.

## 2026-08-10 (g) — Phase 3-A 보정 검증 (폴링 복원 / 문구 정정)

- **신규**: `tests/unit/test_os_precheck_polling.py` 21건.
  실제 시간 기반 소켓 상태 전환을 만들 수 없어 **결정적 mock clock** 사용
  (`pb.time.monotonic` / `pb.time.sleep` 대체 → 실제 대기 0초).
  - **핵심 회귀 Case**: t=0 에 닫혀 있고 t=1.0 에 기동되는 서비스 →
    폴링(예산 2초, sleep 1) 으로 **2회째 시도에서 성공**. 대조군(단일 시도)은 실패.
  - 예산 초과 대기 없음(clock <= 2.0) / 시도별 타임아웃 = `min(5, ceil(남은))` = [2, 1]
  - timeout 실패는 1회로 끝남(wait_for 와 동일) / refused 후 예산 내 성공
  - 여러 시도의 kind 종합 우선순위 4조합
  - checked_ports 중복 없음 / 첫 성공에서 중단
  - **DNS 규칙**: 주소 시도 실패는 timeout kind, getaddrinfo 실패만 DNS kind /
    복수 주소 중 하나 실패해도 다른 주소 성공이 우선
  - **§9 채널 보호**: redfish/esxi 는 `(443, 3.0)` 단일 시도 유지, stage/code/checked_ports 불변
  - os-gather/run_precheck 배선 검증 + RST 문구에 "서버는 응답하지만" 부재 확인
- **수정**: 공유 테스트 하네스 2곳에 `port_poll_interval` 파라미터 추가,
  RST 문구 기대값 갱신.
- **전체 회귀**: `pytest tests/` → **1519 passed, 11 skipped, 7 xfailed**
- **Jenkins 등가**: Stage 3 PASS / e2e 258 / integration 200 / unit 889 / regression 169
- **하네스**: harness / boundary / output_schema_drift / envelope_change / cross_channel exit 0
- **Baseline**: 10건 변경 없음
- **환경 제약**: `ansible-playbook --syntax-check` **미실행** (Windows, `os.get_blocking` POSIX 전용).
  대체 확인으로 YAML 파싱 5종, Jinja2 165 표현식 전수 컴파일 실패 0.
- **wait_for 실측 근거**: `ansible/modules/wait_for.py` argument_spec
  (`timeout=300`, `connect_timeout=5`, `sleep=1`, `delay=0`) + started 분기 폴링 루프 :619-628.

## 2026-08-10 (f) — OS 공통 Precheck 통합 검증 (Phase 3-A)

- **신규**: `tests/unit/test_os_precheck_integration.py` 18건. `run_module()` 을 실제로
  돌려 포트별 결과를 주입한다. 네트워크는 0.
  - Case 1~3 포트 우선순위 + OS Type + scheme + checked_ports
  - Case 4~7 전 포트 timeout / 전 포트 refused / 혼합 4조합 / DNS 실패
  - Case 8~9 IPv6 → IPv4 graceful degradation (주소군 순서)
  - 포트 점검 단계는 auth_success 를 만들지 않음 / 프로토콜을 확인했다고 위장하지 않음
  - 타임아웃 2초가 실제 전달되는지(모듈 기본 3.0 이 조용히 적용되지 않는지) / 포트당 재시도 없음
  - Case 18 민감정보 비노출
  - **Cross-channel**: redfish/esxi 는 probe_protocol 기본 true 로 Stage 3 유지,
    checked_ports=[443] 불변
- **수정**: `test_precheck_detail_propagation.py` 의 포트 순서 회귀를 공통 모듈 정본
  (`CHANNEL_DEFAULT_PORTS['os']`) 기준으로 재작성하고 `_check_ports` 실측 probed 목록 검증을
  추가했다. `test_failure_code_contract.py` 의 OS 매핑 예외 제거(해소됨) →
  code↔stage 전 채널 1:1 로 강화. `test_failure_reason_contract.py` OS 포트 전멸 3분기 검증.
- **PLAY 1 → PLAY 1.5 배선 시뮬레이션**: site.yml 템플릿을 직접 추출해 7 시나리오 렌더.
  OS 판정 / stage / code / auth / checked_ports / reason 전부 기대와 일치.
- **전체 회귀**: `pytest tests/` → **1498 passed, 11 skipped, 7 xfailed**
- **Jenkins 등가**: Stage 3 PASS / Stage 4-a 258 / Stage 4-b 200 / unit 868 / regression 169
- **하네스**: harness / boundary / output_schema_drift / envelope_change / cross_channel 전부 exit 0
- **Baseline**: 10건 shape·값 검사 통과 (변경 없음)
- **환경 제약**: `ansible-playbook --syntax-check` **미실행**. Windows 에서 Ansible CLI 진입부가
  POSIX 전용 `os.get_blocking` 을 호출한다. 대체로 YAML 파싱 5종 + Jinja2 163 표현식 전수
  컴파일 실패 0, 그리고 7 시나리오 실제 렌더까지 수행했다. lab/Jenkins 재확인 필요.
- **알려진 동작 차이 (보고 대상)**: `wait_for` 는 timeout 안에서 재시도(polling)하지만
  `tcp_check_ex` 는 포트당 1회 시도다. 부팅 중 서비스가 t=1.5s 에 열리는 경계 사례에서
  결과가 달라질 수 있다. 재시도 정책 변경은 이번 범위 밖이라 1회 시도를 채택했다.

---

> 이 아래로 60개 항목이 더 있었다. 테스트 이력은 git log 에 그대로 있으므로 여기서는 최근 12건만 유지한다.
> 과거 항목이 필요하면 `git log -p -- docs/ai/catalogs/TEST_HISTORY.md` 로 본다.
