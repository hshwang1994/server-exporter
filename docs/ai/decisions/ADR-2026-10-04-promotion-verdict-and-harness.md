# ADR-2026-10-04 — 승격 판정 모델 · bootstrap 상태 전이 · 양 원격 ff 승격 · 고객사 main 형태 실행 검증(G19) · main 전용 실행 Harness

상태: Accepted (2026-10-04). 전신 `ADR-2026-10-03-production-generation.md` · `ADR-2026-10-03-pipeline-finalization.md` 를 보완한다 — Astra 2~4차 검토(2026-10-03)가 지적한 R1~R7 과 CI 미연결(R3)의 결정 기록.

## 컨텍스트 (Why)

- `verify` 는 SKIP · 빈 목록 · `--only` · `--skip-live` 를 모두 `ok` 로 보고했고(`ok = all(status != "FAIL")`), promote 는 netrc 없이 G13 을 항상 SKIP 한 채 실 승격이 가능했다. 커밋 본문은 실행하지 않은 gate 를 "passed" 로 적었다.
- legacy production(`4ce90a00`, provenance 없음)으로는 `restore` 가 불가능했고, drift 는 LEGACY 를 ok 로 봤다.
- 승격은 로컬 ref 만 보고 push 1회·사후 대조 없이 했다. 사내 GitLab 과 GitHub 의 production 은 이미 어긋나 있었다(`a03c4038` vs `4ce90a00`).
- 고객사는 **main 브랜치 하나**로 운영한다(사용자 2026-10-03). 생성 tree 가 개발 저장소 없이 돌아가는지는 정적 검사로 대체할 수 없다.
- finalizer 의 `lines = null` 뒤 `lines.size()`(R5) 같은 결함은 텍스트 테스트가 못 잡는다 — 실제 CPS·sandbox 에서 함수를 **실행**하는 regression 이 필요했다. 운영 코드에 장애 주입 분기를 넣지 않는다는 결정(3차 §5-2)과 함께.

## 결정 (What)

1. **판정 모델**: `verdict ∈ {COMPLETE_PASS, PARTIAL, FAIL}`. 필수 gate G01~G20 중 하나라도 보고서에 없거나 SKIP·partial 이면 PARTIAL, FAIL 이 하나라도 있으면 FAIL. `ok` = COMPLETE_PASS. 보고서는 `binding`(main_sha · main_tree · tree_hash · generator_hash · manifest_sha256 · 환경 식별자 · verify_mode · netrc_used · bootstrap_baseline) 과 `report_sha256`(정규화 JSON, 자기 필드 제외)을 담고 sidecar 에도 쓴다. `--skip-live` 는 `--dry-run` 과만. G14 는 필수 테스트 **그룹** 단위로 집계한다(수집 누락도 PARTIAL). 환경 의존 gate(G11/G12/G13/G14/G15/G19)는 환경 식별자가 같을 때만 재사용, G18/G20 은 promote 직전 항상 재실행.
2. **E2E 증거의 구조화 소비**: `prodgen e2e-evidence`(Jenkins 읽기) → `evidence-aggregate`(보고서에 `e2e_evidence` 결합 · digest 재계산). promote 는 같은 `main_sha` 의 필수 main 시나리오(S1 S2 S3 T2 T5 T6 E2E-A E2E-A')와 Harness 12 시나리오가 PASS 인지 코드로 확인한다. 시나리오 PASS 와 Jenkins 결과는 다르다(T5 ABORTED · T6 UNSTABLE 이 기대값).
3. **bootstrap 상태 전이**: production 상태 `LEGACY`(B) · `PROVENANCE`(P) · `RESTORED_BASELINE`(R: trailer + tree OID == B + 유효한 P1 이력) · `UNVERIFIED`. CLI 문법은 `--bootstrap-baseline <sha>` 하나(promote · drift-check · verify · restore · CI 파라미터 `BOOTSTRAP_BASELINE`). 첫 승격 커밋은 `Bootstrap-Baseline` · `Bootstrap-Baseline-Tree`(git tree OID — provenance `tree_hash` 와 이름을 구분) 를 기록하고, legacy 로의 restore 는 그 기록이 있을 때만 받는다. R 뒤 재승격은 parent = R, baseline = B, 조상 검사는 P1 의 `Main-SHA` 기준.
4. **양 원격 fast-forward 승격**: 승격 전 각 원격 `ls-remote` == 로컬(다르면 `push-sync` 먼저). 새 커밋은 `commit-tree -p <expected>` 로 만들고 ff 를 코드로 검사한 뒤 원격별로 사전 `ls-remote` → push(`--force-with-lease` 는 경쟁 탐지용) → 사후 `ls-remote`. 전부 성공했을 때만 로컬 ref 갱신, 둘째 원격이 새로 실패하면 `partial_push` 보고 + `push-sync`(ff 만). `ls-remote` 성공은 읽기 접근일 뿐 push 권한·protection 통과의 증거가 아니다. 알려진 자격 부재(GitLab 토큰 없음)를 이유로 GitHub 만 먼저 바꾸는 경로는 없다 — CI 는 dry-run 까지. commit-tree 는 env/git config 에 신원이 없으면 `prodgen <prodgen@clovirone.local>` 로 만든다(실행자에 의존하지 않는다).
5. **G19 고객사 main 형태 실행**: 임시 bare repo 에 생성 tree 를 orphan 커밋으로 `refs/heads/main` 에만 push → clean clone → 상속된 `ANSIBLE_*`/`PYTHONPATH` 제거, `tests/`·`scripts/ai`·`.claude` 부재 assert → vault 암호는 clone 밖 0600 파일(CI: `server-gather-vault-password` 바인딩) → 3채널 `ansible-playbook` 을 TEST-NET 대상으로 실제 실행 → host 당 envelope 1 · 13 키 · failure 3종 · silent failure 0 · 평문 0(일치값 미출력). 실패 조건은 **관측**으로 확인한다(TEST-NET 이라 `TARGET_UNREACHABLE` 을 단정하지 않는다). unreachable 실행은 초기 실행·precheck·failure envelope·출력의 검증이지 성공 수집의 보장이 아니다.
6. **승격 집행 조건 6항(코드)**: ① 필수 CI stage PASS(`ci_stage_results.json`) ② COMPLETE_PASS + binding 일치 ③ 같은 SHA 의 E2E 증거 PASS ④ tree hash 일치 ⑤ 양 원격 동일 · parent · G18/G20 재검사 ⑥ dry-run 아님 + 명시 요청. 하나라도 빠지면 원격 변경 0. CI 의 Promote 는 `when { expression { params.PROMOTE } }` + SHA 4값 일치(`PROMOTE_SHA` · `MAIN_SHA` · HEAD · 보고서 binding)로, `branch` 조건은 쓰지 않는다(일반 Pipeline).
7. **main 전용 실행 Harness**: 별도 Job(`clovirone-cicd/clovirone-server-gather-harness`, `tests/jenkins/harness/`), 시나리오당 빌드 1개. `Jenkinsfile_portal` 의 최상위 함수를 글자 그대로 잘라 wrapper(`archiveArtifacts`·`stash`·`unstash`·`unarchive`·`readTrusted`·`sh`·`httpRequest`·`unstable`·`getParams`)를 덧붙여 `load` 하고, fixture 를 **현재 빌드**의 manifest 로 재생성한 뒤 `sePreserveGatherOutput()` → `seFinalizeAndCallback()` 을 실제 step 으로 실행한다. Callback 은 `callback_sink.py`(POST 수신·검증·응답 통제·기록)가 받는다 — **controller(built-in) 의 127.0.0.1** 에서(아래 결과 ②). 판정은 `harness_verdict.py`(PASS/FAIL/PARTIAL). 운영 코드와 production tree 에는 장애 주입 분기 · sleep · 샘플러가 없다. 생성 tree 의 함수도 같은 Harness 로(`FUNCTIONS_SRC=artifact`, CI 빌드 artifact + sha256 대조).
8. **CI 12 stage**(`Jenkinsfile_ci`): Checkout → Toolchain(사용자 권한 `pwsh` bootstrap) → Gate → Finalize Corpus → Budget Self-test → Harness Driver → Prodgen Build → Harness(prodtree) → Prodgen Drift → Prodgen Verify → Evidence Aggregate → Prodgen Promote. 자격증명은 Verify(린터 토큰 `se-jenkins-lint` · vault 암호, mktemp 0600 + trap) · Evidence · Promote 블록 안에서만. `env.CI_STAGE_*` 를 post 가 `ci_stage_results.json` 으로 남기고 Promote 가 읽는다(Gate FAIL 뒤에도 뒤 stage 는 진단용으로 돈다).

## 결과 (Impact)

- ① 2026-10-04 CI #5(`5d2a8c8e`)에서 **Verify COMPLETE_PASS(G01~G20, Runner · netrc · vault 바인딩)** — G19 가 3채널을 실제로 돌렸다(28.9 s). CI #3 은 같은 설계가 실제 결함 3건(G09 생성 tree exec bit · G14 주석 의존 테스트 · G20 CI checkout 의 로컬 ref 부재)을 잡아냈다.
- ② Harness 가 실제 Jenkins 에서 드러낸 사실: `httpRequest` 는 node 컨텍스트의 노드에서 실행된다(http_request 1.25) → finalizer 의 Callback 은 controller 에서 나가고 Runner 는 controller 발 인바운드를 거부했다 → sink 는 controller loopback. 또 `JsonOutput.toJson(List)` sandbox 거부, NFS silly-rename 과 controller workspace, 비-daemon Timer 의 lingering. 운영 코드 결함 2건(한 mapping 의 `unarchive` 통째 실패 · `source` 의미) 도 Harness #30/#34 가 잡았다 — 텍스트 테스트는 못 잡는 종류다.
- ③ 승격은 하지 않았다: 필수 E2E(S1·S2·S3·T5·E2E-A/A')가 HOLD/권한(노드 라벨 변경 + 실호스트·Portal 트리거가 자동 분류기에서 거부), GitLab push 자격 없음(`se-gitlab-push`), `push-sync` 미실행. 조건이 갖춰지면 CLI 경로(`--push-remote origin,internal`)가 같은 보고서를 소비한다.
- ④ 고객사 전달 계약(`docs/operate/09`): main-only · tree 동일성 · 설치 시 맞출 값 · `cj` · `refs/heads/main` 복구 경계. 고객사 실환경 검증은 범위 밖임을 세 층으로 구분해 적는다.

## 대안 비교 (Considered)

- *SKIP 을 PASS 로 두고 문서로 경고* — 거부. R1 사고의 원인이 바로 그것이다.
- *bootstrap 을 값 없는 `--bootstrap` 플래그로* — 거부. 어떤 legacy SHA 를 baseline 으로 삼았는지 보고서·trailer 에 남지 않는다.
- *GitHub 만 먼저 승격하고 GitLab 은 뒤에* — 거부(3차 §8-1). 두 원격이 어긋난 상태를 승격이 만들면 안 된다.
- *G19 를 정적 검사(경로 grep)로 대체* — 거부(2차 §3-1). 실행해야만 보이는 것(상속 env · collection 경로 · vault 바인딩)이 있다.
- *운영 Jenkinsfile 에 `faultInject`/`perfSample` 파라미터* — 거부(3차 §5-2). production tree 에 장애 분기가 남는다. wrapper 로 밖에서 만든다.
- *경과 시간·원인 클래스로 timeout 판별* — 거부(3차 §4-1). `ExceededTimeout.nodeId` 식별이 안 되면 catch 하지 않고 재전파한다(기본 off, 보장 축소 명시).
- *Harness sink 를 agent 에 두고 Runner 방화벽을 연다* — 거부. Runner 시스템 변경이고 접근 경로도 없다. controller loopback 이 finalizer 가 실제로 요청을 보내는 지점이다.
