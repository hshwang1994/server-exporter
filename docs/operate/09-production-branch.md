# production 브랜치 — runtime-only tree 생성 · 검증 · 반영 · 복구 · 고객사 전달

> 2026-10-03 부터 `production` 브랜치는 사람이 편집하거나 main 을 병합하는 브랜치가 아니다. **고정된 main SHA 에서 생성기(`prodgen`)가 만든
> runtime-only tree** 를 append 커밋으로 올린다. 생성물에는 테스트 · 문서 · 스키마 · 하네스 · 운영자 도구가 없고 설명성 주석이 전부 제거돼 있다.
> 2026-10-04 에 판정 모델(COMPLETE_PASS/PARTIAL/FAIL) · bootstrap 상태 전이 · 양 원격 fast-forward 승격 · 고객사 main 형태 실행 검증(G19)이 추가됐고,
> 같은 날 검토(C1~C6)로 시나리오 계약 기반 E2E 증거 · baseline 기록 탐색 · 환경 미확인 시 재실행 · 배포 원격 집합 정책 · CI stage 증거의 CLI 소비가 보강됐다.

## 0. 저장소와 브랜치 — 내부는 main+production, 고객사는 main 만

| 저장소 | 브랜치 | 역할 |
|---|---|---|
| 우리 GitHub(`origin`) | `main`, `production` | 개발 원본 / 검증된 runtime-only 배포 원본 |
| 사내 GitLab `10.100.64.156`(`internal`) | `main`, `production` | 같은 두 브랜치 대응. `promote`·`restore`·`push-sync` 는 **두 원격을 함께** 다룬다 |
| 고객사 Repository | **`main` 만** | 고객사 main = 고객사 운영 production. 별도 production 브랜치를 만들거나 요구하지 않는다 |

- 전달 방향: `개발 main → prodgen 생성·검증 → 우리 production → 고객사 main`. 고객사 main 을 개발 main 과 같은 내용으로 동기화하지 않는다.
- 현재 확인된 전달 방식은 설치 자동화의 **tree 사본 시딩**(`git archive` 사본, 별도 이력)이라 커밋 SHA 가 보존되지 않는다. 그래서 동일성은 **tree 로** 확인한다:
  `.production-provenance.json` 의 `tree_hash`(파일 목록 SHA-256) 를 고객사 형태 checkout 에서 다시 계산해 비교한다. "고객사 main SHA == 내부 production SHA" 를 가정하지 않는다.
  재계산 값이 다르면 다른 파일 목록을 전달 자료에 적는다(고객별 허용 설정 차이 식별 — 현재 코드에 고객별 설정 파일은 없고, Add-on 은 전역 env `ADDON_REPO_URL`, 자격은 `vault/<loc>/`).
- 고객사 main 독립 실행 조건(G19 가 같은 조건으로 검증한다): runtime 이 브랜치명을 가정하지 않는다 / `main` 을 checkout 해도 같은 수집 경로 / `production`·`origin/production` ref 부재에서 실행 /
  개발 main·생성기·내부 원격 접근 없음 / 필요한 외부 runtime 은 아래 "설치 시 맞출 값" 으로만 요구한다.
- **설치 시 맞출 값**(고객사 Jenkins): Gathering Job 의 Branch Specifier `*/main` · Script Path `Jenkinsfile_portal` · Secret text credential `server-gather-vault-password` ·
  Runner 라벨 `linux | windows | esxi | redfish` + `common/vars/locations.yml` 의 `agent_label`(Location 별, 예: 청주 = `cj`) · Agent 의 Ansible venv(`scripts/activate_ansible_venv.sh` 가 고른다:
  `SE_ANSIBLE_VENV` → PATH 의 `ansible-playbook` → `/app/ansible-env` → `/opt/ansible-env`) · 검증 파라미터 기본값(`redfishAccountDryrun` 등은 기본값이면 영향 없음).
  `pwsh` 는 **생성 시** 도구이지 runtime 요구가 아니다. 내부 Jenkins 주소 · credential ID · Runner 이름을 고객 공통 필수값으로 새로 고정하지 않는다.
- 세 층을 구분해 말한다: **고객사 main 형태 깨끗한 checkout 검증(G19)** / **사내 production Job E2E** / **실제 고객사 실행**(이 저장소의 작업 범위 밖). 앞 둘이 통과해도 "고객사 실환경 검증 완료" 라고 쓰지 않는다.

## 1. 무엇이 들어가나

| 분류 | 경로 | 비고 |
|---|---|---|
| 파이프라인 | `Jenkinsfile_portal`, `scripts/jenkins/se_finalize.groovy` | `Jenkinsfile_ci` 는 main 전용이라 제외 |
| Ansible 설정 · 인벤토리 | `ansible.cfg`, `{os,esxi,redfish}-gather/inventory.sh` | |
| Playbook · task · 변수 정본 | `*/site.yml`, `*/tasks/**`, `common/tasks/**`, `common/vars/{failure_reasons,section_messages,locations,vendor_aliases,supported_sections}.yml` | `common/vars/status_rules.yml` 은 제외(주석에서만 참조) |
| Adapter | `adapters/{redfish,os,esxi}/*.yml` | `adapters/registry.yml` 은 제외(런타임 미참조) |
| Vault | `vault/**/*.yml` | 바이트 그대로(헤더 검사) |
| 플러그인 · 라이브러리 | `callback_plugins/`, `filter_plugins/`, `lookup_plugins/`, `module_utils/`, `*/library/*.py` | 플러그인의 `DOCUMENTATION` 은 로더가 읽어 보존, library 모듈은 제거 |
| 운영 스크립트 | `scripts/activate_ansible_venv.sh`, `scripts/addon_*.sh`, `scripts/finalize_gather_output.py`, `scripts/gather_budget.sh`, `os-gather/files/get_last_login.sh` | |
| 저장소 메타 | `.gitattributes`, `.gitignore`, `.production-provenance.json` | provenance 는 생성기가 쓴다 |

제외: `tests/**`, `docs/**`, `schema/**`, `.claude/**`, `scripts/ai/**`, `jenkins/**`, `Jenkinsfile_ci`, `README.md`, `REQUIREMENTS.md`, `CLAUDE.md`, `requirements-test.txt`,
`scripts/bootstrap_vault_encrypt.sh`, `scripts/verify_account_provision.sh`(운영자는 main 에서 쓴다). 정본은 저장소 루트의 `production_manifest.yml`.
장애 주입 · 성능 샘플러 · Harness 는 운영 소스에 없다 — `tests/jenkins/harness/`(main 전용) 가 밖에서 만든다.

## 2. 명령 (main checkout 에서, Windows 또는 pwsh 가 있는 Linux)

```bash
SHA=$(git rev-parse main)
python -m scripts.ai.prodgen build   --sha "$SHA" --out /tmp/prodtree                       # 생성 (object store 만 읽는다). class B > 0 이면 실패
python -m scripts.ai.prodgen verify  --tree /tmp/prodtree --netrc <netrc> \
        --vault-password-file <file> --remote origin --remote internal \
        [--bootstrap-baseline <B>] --report-out verify.json                                  # gate G01~G20 → 종료 코드 0 COMPLETE_PASS · 2 PARTIAL · 1 FAIL
python -m scripts.ai.prodgen verify  --tree /tmp/prodtree --skip-live                        # 오프라인 미리보기 — 언제나 PARTIAL(통과가 아니다)
python -m scripts.ai.prodgen drift-check --production origin/production [--bootstrap-baseline <B>]   # production 상태 분류(아래 3절 표)
python -m scripts.ai.prodgen e2e-evidence --jenkins-url <url> --netrc <netrc> \
        --entry S1=clovirone-cicd/clovirone-server-gather-main:7 --entry T6=…:9:UNSTABLE --out e2e.json  # 시나리오 증거 수집(읽기 전용)
python -m scripts.ai.prodgen evidence-aggregate --report verify.json --evidence e2e.json --out verify.agg.json
python -m scripts.ai.prodgen promote --sha "$SHA" --dry-run [--skip-live]                    # 만들어질 커밋 미리 보기 — 원격 변경 0 (PARTIAL 이면 preview_only 표시)
python -m scripts.ai.prodgen promote --sha "$SHA" --verify-report verify.agg.json --e2e-evidence e2e.json \
        --ci-stage-results ci_stage_results.json [--bootstrap-baseline <B>] --push-remote origin,internal   # 실제 반영 (3절 전제 전부 충족 시에만)
python -m scripts.ai.prodgen push-sync --remote origin --remote internal                     # 뒤처진 원격·로컬 ref 를 fast-forward 로만 맞춤(분기 거부)
python -m scripts.ai.prodgen restore --to <production commit> [--bootstrap-baseline <B>] --push-remote origin,internal   # 되돌리기(append 커밋)
```

- 생성기는 PowerShell 주석 제거 검증에 **실제 PowerShell 파서**(`pwsh` 또는 `powershell.exe`)가 필요하다. 없으면 Windows task 의 PowerShell 주석이 class B 로 남아 **승격이 차단**된다.
  Linux Runner 에 `pwsh` 가 없으면 `scripts/ai/prodgen/ci_pwsh_bootstrap.sh` 가 사용자 권한으로 `$HOME/.local/powershell` 에 준비한다(시스템 변경 없음).
- `--skip-live` 는 `--dry-run` 과만 쓸 수 있다. SKIP 된 gate · 빠진 필수 gate · `--only` 는 모두 **PARTIAL** 이고, 승격은 COMPLETE_PASS 에서만 한다.
- **배포 원격 집합 정책**(2026-10-04 검토 C4): 실제 `promote`/`restore` 는 `--push-remote origin,internal` **정확히 그 집합**만 받는다 — 원격을 빼거나 하나만 지정하면
  `policy` 단계에서 거부되고 아무것도 만들지 않는다(dry-run 은 미리보기라 어느 집합이든 된다). 자격증명은 CI 의 폴더 credential 이든 세션의 git credential helper 든 상관없다 — 정책은 **집합**이다.
- `--ci-stage-results`: CI 빌드의 `ci_stage_results.json`(같은 main SHA · 필수 stage 전부 PASS). 실제 승격의 전제이며 CI 를 거치지 않은 세션의 CLI 도 같은 파일을 소비한다.
  보고서 `source.build_url` 과 다른 빌드의 파일을 섞으면 거부된다.
- `verify` 보고서는 `binding`(main_sha · main_tree · tree_hash · generator_hash · manifest_sha256) 과 환경 식별자(`python` · `platform` · `ansible_runtime` · `ansible_version` ·
  `collections_sha256` · `pwsh`/`groovy` **버전** · `jenkins_version`) 와 `report_sha256` 을 담는다. `promote --verify-report` 는 binding 이 같을 때만 재사용하고, 환경 식별자가
  **다르거나 한쪽이라도 비어 있으면**(미확인 = 동일이 아니다, 검토 C3) 환경 의존 gate(G11 G12 G13 G14 G15 G19)를 그 자리에서 다시 실행한다. G18(drift) · G20(조상·원격) 은 **항상 다시** 실행한다.
  어떤 gate 를 재사용하고 어떤 gate 를 다시 돌렸는지는 보고서 `gates_reused`/`gates_rerun` 과 커밋 trailer `Gates-Reused`/`Gates-Rerun` 에 남는다.
  보고서 digest 는 변조·혼용 탐지용이지 실행의 증명이 아니다 — 실행 출처(`--source-build-url`)를 같이 적는다.
- `e2e-evidence` 는 **시나리오 계약**(`scripts/ai/prodgen/evidence.py` `MAIN_CONTRACT`)으로 판정한다(검토 C1): main Job 빌드의 파라미터(loc · 대상 host · callbackUrl · gatherBudgetForceSec) ·
  `finalize_summary.json`(outcome · accepted==lines · by_origin · filled) · `callback_body.json`(host 당 envelope 1 · 성공/실패 필드) · 콘솔 표식(`[Callback] [OK] HTTP 2xx` / `Callback 전송 실패` /
  `[Gather] interrupted` / `[Resolve Location]`)을 대조한다. 기대 Jenkins 결과는 계약이 정한다(S3 UNSTABLE · T5 ABORTED · T6 UNSTABLE · E2E-A' FAILURE) — 호출자가 다른 값을 넣어도
  통과로 바꿀 수 없다. Harness 증거는 Job 파라미터 `SCENARIO`/`FUNCTIONS_SRC` · artifact `harness_result.json` 의 scenario·verdict · 함수 해시를 대조하고, main 함수 그룹과 생성 tree
  그룹(`provenance.tree_hash` == 승격 대상 tree)은 **따로** 충족해야 한다. 집계(`evidence-aggregate`)는 입력 evidence 의 digest 를 먼저 검증한다.
- gate: G01~G10 · G16 · G17 정적 / G11 syntax-check · G12 config dump · G15 module smoke(환경 의존) / G13 Jenkins 린터(`--netrc`) / G14 pytest overlay(필수 테스트 그룹이 하나라도 빠지면 PARTIAL) /
  G18 drift / **G19 고객사 main 형태 clean checkout 에서 3채널 실제 실행**(bare repo `main` 만, 개발 경로 금지, vault 암호 파일은 clone 밖, TEST-NET 대상, 실패 조건은 관측으로 확인) / G20 조상·양 원격 동일.

## 3. 반영(승격)의 전제 — 하나라도 빠지면 하지 않는다

| production 상태(`drift-check`) | 뜻 | 다음 승격 |
|---|---|---|
| `LEGACY` **B** | provenance 없는 첫 production(현재 `4ce90a00`) | `--bootstrap-baseline B` 를 명시했고 B 가 양 원격의 현재 SHA 일 때만 |
| `PROVENANCE` **P** | prodgen 이 만든 커밋(provenance · trailer · 양 원격 일치) | 일반 규칙(parent = P, G18 ok, G20 조상 = P 의 `Main-SHA`) |
| `RESTORED_BASELINE` **R** | B 의 tree 를 복원한 커밋(trailer `Restore-Of/Restore-From/Baseline-Recorded-By/Bootstrap-Baseline`, tree OID == B, 이력 어딘가의 생성 커밋이 B 를 기록) | parent = R, baseline = B, 조상 검사는 **마지막** 생성 커밋 P 의 `Main-SHA` 기준 |
| `UNVERIFIED` | 위 근거가 없거나 불일치(trailer 만 있고 tree 가 다름 포함) | 거부 — 사람이 production 을 직접 고쳤다면 고칠 것은 main 이다 |

승격 집행 조건(코드가 확인한다 — CI Promote 와 CLI 공통, CLI 는 `--ci-stage-results` 로 같은 stage 증거를 받는다): ① 필수 CI stage 전부 PASS(`ci_stage_results.json`: GATE · CORPUS · BUDGET · HARNESS_MAIN ·
PRODGEN_BUILD · HARNESS_TREE · PRODGEN_DRIFT · PRODGEN_VERIFY · EVIDENCE) ② G01~G20 COMPLETE_PASS + binding 일치 ③ 같은 `main_sha` 의 필수 main Job 시나리오(S1 S2 S3 T2 T5 T6 E2E-A E2E-A')와
main 함수 Harness(16) · 생성 tree Harness(4, 같은 `tree_hash`)가 `e2e_evidence` 에서 계약대로 PASS ④ 생성 tree hash == 검증 대상 ⑤ 양 원격(`origin` + `internal` 정확히) 동일 · 현재 parent ·
G18/G20 재검사 ⑥ dry-run 이 아니고 명시 요청(`--push-remote origin,internal`/`PROMOTE=true`). Tier 2(`SE_FINALIZER_BOUNDED=true`) Harness 시나리오는 그 모드를 켠 배포에서만 조건이 된다.
G20 은 원격 없이 돌면 PARTIAL(검증 안 됨)이고, 일부 원격만 보면 `deploy_set_complete=false` 로 적는다 — 실제 승격은 전체 집합으로 다시 돈다.
그 밖에: 수집 시간대 밖에서 한다. 승격 **직후** production Job(`clovirone-server-gather`) canary 1회(os 1~3대 · Callback 2xx · checkout SHA == 새 커밋) — 첫 확인 단계이지 완료 판정이 아니다.

## 4. 반영 뒤 확인

- `git ls-remote origin production` 과 `git ls-remote internal production` 이 같은 SHA 인가. `promote` 는 원격별로 push 직전 `ls-remote == expected`, push 직후 `ls-remote == new` 를 확인하고
  **모두 성공했을 때만** 로컬 ref 를 옮긴다. 둘째 원격이 새로 실패하면 `partial_push` 로 보고하고 `push-sync` 로 재개한다(ff 만, 분기 거부).
- production Job 다음 빌드의 checkout SHA 가 그 커밋인가(`docs/operate/03-job-registration.md`).
- 커밋 trailer `Main-SHA` · `Tree-Hash` · `Verdict` · `Gates` · `Verify-Report-SHA256` · `Bootstrap-Baseline(-Tree)`(첫 승격) 와 `.production-provenance.json` · `drift-check` 결과.
- `ls-remote` 성공은 읽기 접근 확인이지 push 권한·branch protection 통과의 증거가 아니다 — 그것은 실제 push 결과로만 적는다.

## 5. 되돌리기

- 내부: `restore --to <마지막 정상 production 커밋> --push-remote origin,internal` 은 그 tree 를 **새 커밋**으로 양 원격에 올린다(force push · reset 금지, trailer `Restore-Of`). legacy B 로 되돌릴 때만
  `--bootstrap-baseline B` 가 필요하고, production 이력의 **어느** 생성 커밋이든 그 baseline 을 기록해 두었을 때만 받는다(첫 승격 P1 이 기록하고 뒤의 정상 승격도 trailer 를 물려받으므로
  `B → P1 → P2 → restore(B)` 가 된다 — 2026-10-04 검토 C2). 원격을 하나만 지정한 restore 는 거부된다(두 원격이 어긋난다). production Job 은 브랜치 고정이라 추가 조치가 없다.
  실제 baseline `4ce90a00` 을 복제한 두 bare 원격 훈련 기록: `tests/evidence/2026-10-04-promotion-drill.md`.
- 고객사: 대상은 **고객사 `refs/heads/main`** 이다. 이전 정상 tree(`.production-provenance.json` 의 `tree_hash` 또는 첫 승격 trailer `Bootstrap-Baseline-Tree`)를 고객사 main 에 다시 적용한다
  (`git archive` 사본 재시딩 또는 고객사 운영 방식). 고객사에 production 브랜치 · prodgen · Harness 설치를 요구하지 않는다. 내부 ref 를 되돌린 것만으로 고객 복구를 보고하지 않는다.

## 6. 청주 Location 계약 변경 `chj → cj` (2026-10-04)

- 바뀐 것: `common/vars/locations.yml` 키·`agent_label` = `cj`, Vault 경로 `vault/cj/`(12 파일, 암호문 blob 동일 · 재암호화 없음). alias 는 없다 → **`loc=chj` 요청은 미등록 Location 으로 거부(fail-closed)** 된다.
- 필요한 것: 실 청주 Runner 에 라벨 `cj`(기존 라벨 유지). 요청 `loc` 값을 만드는 쪽(공급자)이 `cj` 를 보내야 한다. Portal 설정은 이 저장소 범위에서 바꾸지 않는다.
- 반영 순서(무중단을 약속하지 않는다): ① `loc` 공급자 확인 ② 청주 Runner 라벨 `cj` 준비 ③ 전환 시각 합의 ④ 진행 중 `chj` 빌드 완료 대기 ⑤ 코드 반영(main → 승격 → 고객사 전달) ⑥ `cj` 빌드 Resolve 성공 · `chj` 요청 0건 확인
  ⑦ 원복 조건 — `cj` 요청 준비 전에 코드가 먼저 나가 신규 요청이 실패하면 `git revert`(main) / `restore`(production) / 고객사 main 이전 tree 재적용으로 즉시 원복, 공급자 값 복귀는 담당 몫.
- lab 의 임시 `cj` 라벨 + TEST-NET 실패 envelope 검증은 라우팅·실패 처리 smoke 이지 **청주 실장비 성공 수집이 아니다**.

## 7. 현재 상태 (2026-10-04)

첫 승격은 아직 하지 않았다. `origin/production` = `internal/production` = legacy `4ce90a00`(2026-10-04 관측 — 전일 `a03c4038` 였던 internal 이 같아졌다, 이 저장소의 도구가 옮긴 것이 아니다).
진행 상태 · 보류 사유 · 증거는 `docs/reference/decision-log.md`(2026-10-04) 와 `tests/evidence/2026-10-04-*.md` 에 둔다.
