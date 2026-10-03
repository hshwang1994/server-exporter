# ClovirONE Server Gathering — 잔여 작업 최종 보고서 정정판 (2026-10-04)

이 문서는 `tests/evidence/2026-10-03-final-report.md` 를 **정정**한다. 2026-10-03 보고서의 "Phase 4 finalizer 완료 · Phase 6 완료 · Phase 7a 완료(코드 수준)" 는 틀렸다: Phase 6 은 CI 에 prodgen 이 연결되지 않았고(R3), Phase 7a 는 판정·복구·원격 기준점 결함(R1·R2·R4)을, Phase 4 는 finalizer 결함(R5·R6·R7)을 포함했다. 실환경은 전부 미검증이었다. 아래는 2026-10-04 작업 뒤의 상태다.

상태 어휘: `PASS` · `FAIL` · `PARTIAL/SKIP` · `HOLD/권한` · `HOLD/환경` · `INVALID`. 완료 수준 다섯: **코드 완료 / 로컬 회귀 완료 / Jenkins 실행 완료(main · CI · Harness) / 내부 production 검증 완료 / 고객사 형태 검증 완료** — 어느 하나가 다른 것을 대신하지 않는다. 세 층: 고객사 main 형태 깨끗한 checkout 검증(G19) / 사내 production Job E2E / 실제 고객사 실행(미수행).

## 0. 한눈에

| 수준 | 상태 |
|---|---|
| 코드 완료 | **PASS** — R1~R7 · Harness · CI 12 stage · prodgen 승격 모델 · G19/G20 · cj (커밋 목록 `tests/evidence/2026-10-04-residual-r1-r7.md` §0) |
| 로컬 회귀 완료 | **PASS(PARTIAL 표기)** — gate 4,070 passed(Windows 는 `ansible-playbook` 없음 → syntax-check 는 CI Runner 가 대신: CI Gate 3,999 passed + G11 PASS) |
| Jenkins 실행 완료 | **부분** — CI #7(X=`15e684b0`) **SUCCESS: Verify COMPLETE_PASS(20/20, G19 포함) · Harness 12/12 · 생성 tree 함수 4/4 · Evidence PASS**, main T2+T6 PASS(#6). **S1·S2·S3·S4·T5·E2E-A/A'·E2E-D/E 는 HOLD/권한·환경** |
| 내부 production 검증 | **미수행** — 승격 전제 미충족(필수 E2E · GitLab 자격 · push-sync) |
| 고객사 형태 검증 | **G19 PASS(CI #3 · #5)** — 생성 tree 만으로 3채널 실행. 고객사 실환경 검증이 아니다 |

## 1. R1~R7 · 보완별 변경 · 동작 · 실행 테스트 · 남은 조건

`tests/evidence/2026-10-04-residual-r1-r7.md` §1 표가 정본이다. 요약:

| ID | 핵심 변경 | 실행한 검증 | 남은 조건 |
|---|---|---|---|
| R5 | `lineCount` 선언을 `int accepted` 직후로 | Harness normal_success PASS(#27/#28/#44) · 텍스트 테스트 | S1 실빌드(HOLD/권한) |
| R6 | 기준점 = Resolve Location 끝 · `pre/wait_checkout/prep` · interruption 재전파(`aborted`) · Tier 1/2(opt-in) | main #4~#6 로그 3값 · `test_gather_budget`(930/120/119/30) · Harness outer_timeout PASS | Tier 2 는 승인 4 시그니처 없이는 재전파만(PARTIAL) · T5 HOLD/권한 |
| R7 | 보존 3단계 독립 · 조건부 deleteDir · **회수 사다리 파일별 unarchive · `source`=회수 매체** | Harness archive_fail/both_fail/… PASS, stash_fail·checkpoint_only_b 가 결함을 드러내 수정 | CI #7 재검증(아래 §3) |
| R6/R7 공통 | 손상 입력 → host 당 1개 유효 JSON(`unrecovered` · `damage`) | corpus 14/14 · Harness truncate_jsonl/report_corrupt/raw_fallback PASS · main #4 body 유효 | — |
| R1 | COMPLETE_PASS/PARTIAL/FAIL · 필수 G01~G20 · binding/digest · G14 필수 그룹 · E2E 증거 소비 | CI #5 COMPLETE_PASS · 거부 테스트 | — |
| R2 | LEGACY/PROVENANCE/RESTORED_BASELINE/UNVERIFIED · `--bootstrap-baseline <sha>` · B→P1→R→P2 | tmp 원격 순환 테스트 · CI #5 G18/G20 PASS | 실 `4ce90a00` 복제 훈련(GitLab 자격) |
| R4 | 양 원격 ls-remote 기준점 · ff 코드 강제 · 사전/사후 대조 · `partial_push`/`push-sync` · identity 기본값 | 테스트 · CI #3 가 G20 결함 발견 | 실 push·protection 은 승격 시점 |
| R3 | CI 12 stage · 승격 6항 · 자격증명 블록 한정 · Job 등록·갱신 · `pwsh` 사용자 권한 bootstrap | CI #3/#5/#7 실행 | 실 승격은 dry-run 까지(GitLab 자격 없음) |
| cj | registry · `vault/cj/`(blob 12 동일) · 테스트 · 문서 · 전달 자료 | 로컬·CI 테스트 | lab smoke(라벨) HOLD/권한 |

## 2. 후보 X · tree_hash · P1/R · 고객사 형태 checkout 연결

| 항목 | 값 |
|---|---|
| 개발 main 후보 X | **`15e684b0072d8681e064874dab7e029cdec2ab1f`**(최종, CI #7 · main #6). 중간 후보 `5d2a8c8e`(CI #5 COMPLETE_PASS, `tree_hash 4083ae08…`, `generator_hash 977a81c1…`, `manifest_sha256 02660e89…`) |
| 생성 tree `tree_hash`(파일 목록 SHA-256) | CI #7(X): **`05ce23c39424374b4479157d74edfbfd55e2e1e021bb3b2d13bacf91c875a2ca`**(192 파일 · 1,046,668 B · class B 0, `generator_hash 4f39484c…`, `manifest_sha256 02660e89…`, 집계 보고서 `report_sha256 f4f84136…`); CI #5(중간 후보): `4083ae08…` |
| P1 / R | **없음 — 승격 미수행**. production 은 legacy B `4ce90a00`(tree OID `2f55bdbc9f41…`), internal 은 `a03c4038`(뒤처짐) |
| 고객사 형태 checkout(G19) | CI #3 · #5: bare repo `main` 만 · clean clone · 개발 경로 0 · vault 암호 clone 밖 · 3채널 각 envelope 2 · `TARGET_UNREACHABLE` 관측 · 평문 0 · rc 0. 재계산 tree hash == provenance 는 G19 내부 assert |

## 3. Job 별 빌드 · checkout · 기대/관측

`tests/evidence/2026-10-04-live-e2e.md` §2~§5 가 정본. 요약: main #4(`5d2a8c8e`) · #5(`0ccb89eb`) · #6(`15e684b0`) T2+T6 PASS; Harness #27/#28/#44 normal_success PASS, #29~#39 F 시나리오 10 PASS · 2 FAIL(결함 → 수정), #40~#42 prodtree FAIL(PKIX → 수정); CI #1 SUCCESS · #2 FAILURE(컴파일) · #3 FAILURE(결함 3건 발견) · #4 ABORTED · #5 UNSTABLE(Verify COMPLETE_PASS) · #6 ABORTED · **#7 SUCCESS(모든 stage PASS — Harness 12/12 · prodtree 4/4 · Verify COMPLETE_PASS · Evidence 16 항목)** · #8 PROMOTE dry-run(결과는 `live-e2e.md` §5).

## 4. 완료 host 데이터 보존 · Callback 요청 · HTTP 수신 · Portal 저장

| 구분 | 증거 |
|---|---|
| 완료 host 데이터 보존 | Harness truncate_jsonl · checkpoint_only_a/b · stash_fail · both_fail: `kept` 와 `by_origin.output/checkpoint` 가 입력과 일치, deleteDir 은 보존 증거 있을 때만 |
| Callback 요청 | main #4~#6: POST 3회 시도(연결 거부 관측). Harness: POST 1회 → sink 수신(body sha256 일치) |
| HTTP 수신 | Harness sink `HTTP 200`(normal_success 등) · `503 ×3`(sink_5xx → `delivered=false`) · 미시도(outer_timeout) |
| Portal 저장 | **미확인** — Portal 로 보낸 빌드가 없다(S1 HOLD/권한). Portal `GET /api/jenkins/gather/os 200` 은 POST 수신 증거가 아니다 |

## 5. 승격 · 복구 훈련 · 양 원격 상태

- 승격 **미수행**. 전제 대조는 `live-e2e.md` §7. 복구 훈련은 tmp bare 원격 2개 regression(B→P1→R→P2 · 거부 8종 · 경쟁 · push-sync)만; 실 `4ce90a00` 복제 훈련은 GitLab 자격 뒤.
- 양 원격: `origin/production 4ce90a00` · `internal/production a03c4038`(뒤처짐, `push-sync` 미실행) · main 은 양쪽 동일(`15e684b0` 이후 문서 커밋 포함).
- 부분 반영/재개: 발생 없음.

## 6. 성능 비교

**미실행(HOLD/권한)** — 같은 host 집합(`.161 .162 .163 .120`) 전후 ≥5회가 S1 트리거 권한을 요구한다. 수집한 것: main #4~#6 의 `[Budget]` 로그(`pre/wait_checkout/prep`, `mem_avail_mb≈6.1 GB · mem_cap=62 · forks=2 waves=1` — host 2대 TEST-NET 라 성능 수치가 아니다). `per_fork_mb=36` 은 임시(미측정) 그대로.

## 7. cj · Vault 보존 · Runner 변경/원복 · 고객사 전달 계약

`tests/evidence/2026-10-04-location-cj.md` 정본. Vault blob 12/12 동일 · layout 4 Location × 12 · resolver 테스트 PASS; lab smoke(E2E-A/A')는 HOLD/권한; Runner 노드 설정 변경 **0건**(거부돼 시도 자체가 반영되지 않음); 고객사 전달 계약은 `docs/operate/09-production-branch.md` §0 · §6.

## 8. 권한 · 환경 — 거부/부재 목록 (우회하지 않았다)

| 대상 | 행위 | 결과 | 최소 조치 |
|---|---|---|---|
| Jenkins 노드 `SKHynix-Jenkins-Runner03` | `config.xml` POST(임시 라벨 `cj`) + main Job 트리거(E2E-A/A' · S1 실호스트→Portal) 한 묶음 | 자동 분류기 거부(사유 미표시) | 노드 설정 변경 1건 + main Job 트리거(실호스트·Portal) 허용 — 명령은 나눠서 |
| Jenkins API 토큰 revoke · credential 삭제/재생성 | 중복 토큰 정리 | "Secret-Store Writes" 거부 | UI 에서 토큰 1개 revoke(NEXT_ACTIONS GP-26) |
| GitLab `10.100.64.156` push 자격 | `se-gitlab-push` 생성 | 토큰 없음 | push 권한 토큰 1개 |
| `esxi` 라벨 노드 · Kernel 6.x 호스트 · Add-on hang 재현 · 실 BMC dry-run 트리거 | — | 환경 부재 / 같은 트리거 범주라 미시도 | GP-4 · GP-25 |
| `vault/.lab-credentials.yml` 읽기 | — | 2026-10-03 거부, 이번에 시도하지 않음 | — |

## 9. 보안 확인

평문 자격증명: 소스 · fixture · 테스트 출력 · 이 문서 · 커밋 메시지에 0(새 API 토큰 값은 생성 스크립트 프로세스 안에서만 쓰고 출력·저장하지 않았다; vault 암호는 Jenkins credential → mktemp 0600 → trap rm). G10 vault/평문 스캔 PASS(CI #5). Vault 재암호화·암호 변경 0, BMC 계정 쓰기 0(Redfish 실 BMC 미실행), 대상 OS 변경 0.
