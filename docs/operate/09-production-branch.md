# production 브랜치 생성, 검증, 반영, 되돌리기

이 문서는 사내 저장소의 `production` 브랜치를 어떻게 만들고 올리는지 설명합니다. 고객사 저장소에는 이 브랜치가 없고 `main` 하나만 있으므로, 고객사 반영은 [07-update-and-rollback.md](07-update-and-rollback.md) 3절을 보세요.

## 1. 저장소와 브랜치

| 저장소 | 브랜치 | 역할 |
|---|---|---|
| 사내 GitHub(`origin`) | `main`, `production` | 개발 원본과 검증된 배포본 |
| 사내 GitLab(`internal`) | `main`, `production` | 같은 두 브랜치. 승격과 복구는 두 원격을 함께 다룹니다 |
| 고객사 저장소 | `main` | 고객사 운영 브랜치. 사내 `production`의 tree를 전달받습니다 |

`production`은 사람이 편집하거나 `main`을 병합하는 브랜치가 아닙니다. 생성기 `scripts/ai/prodgen`이 고정된 `main` 커밋에서 운영에 필요한 파일만 뽑아 설명 주석을 지운 tree를 만들고, 그 tree를 새 커밋으로 `production`에 덧붙입니다. 생성기는 개발 저장소(`main`)에만 있고 배포본에는 들어가지 않습니다.

전달 방향은 `개발 main → 생성 · 검증 → 사내 production → 고객사 main`입니다. 고객사 `main`과 개발 `main`을 같은 내용으로 맞추지 않습니다. 고객사 반영은 커밋이 아니라 tree 사본으로 이뤄질 수 있으므로 동일성은 `.production-provenance.json`의 `tree_hash`(파일 목록의 SHA-256)로 확인합니다.

## 2. 배포본에 들어가는 것

정본은 저장소 루트의 `production_manifest.yml`입니다. 요약하면 다음과 같습니다.

| 분류 | 경로 |
|---|---|
| 파이프라인 | `Jenkinsfile_portal`, `scripts/jenkins/se_finalize.groovy` |
| Ansible 설정과 인벤토리 | `ansible.cfg`, `os-gather/inventory.sh`, `esxi-gather/inventory.sh`, `redfish-gather/inventory.sh` |
| playbook과 task | 세 채널의 `site.yml`, `tasks/**`, `common/tasks/**`, `common/vars/`의 운영 변수 파일 |
| 어댑터 | `adapters/redfish/`, `adapters/os/`, `adapters/esxi/` |
| vault | `vault/**/*.yml` (바이트 그대로) |
| 플러그인과 라이브러리 | `callback_plugins/`, `filter_plugins/`, `lookup_plugins/`, `module_utils/`, 각 채널 `library/` |
| 운영 스크립트 | `scripts/activate_ansible_venv.sh`, `addon_checkout.sh`, `addon_askpass.sh`, `env_guard.sh`, `run_gather.sh`, `gather_state.py`, `finalize_gather_output.py`, `workspace_cleanup.py`, `os-gather/files/get_last_login.sh` |
| 저장소 메타 | `.gitattributes`, `.gitignore`, 생성기가 쓰는 `.production-provenance.json` |

테스트, 문서, 스키마, 개발용 도구(`scripts/ai/`, `jenkins/`, `Jenkinsfile_ci`), `README.md`, `REQUIREMENTS.md`, `scripts/bootstrap_vault_encrypt.sh`는 들어가지 않습니다. 문서만 바뀐 `main` 커밋은 tree가 같으므로 다시 승격할 필요가 없습니다.

## 3. 명령

`main`을 checkout한 작업 PC에서 실행합니다. 생성기는 PowerShell 주석 제거를 검증하기 위해 `pwsh` 또는 `powershell.exe`가 필요합니다. Linux에 `pwsh`가 없으면 `scripts/ai/prodgen/ci_pwsh_bootstrap.sh`가 사용자 홈 아래에 준비합니다.

```bash
SHA=$(git rev-parse main)

# 생성. 설명 주석을 지우지 못한 파일(class B)이 있으면 실패합니다
python -m scripts.ai.prodgen build --sha "$SHA" --out <출력 폴더>

# 검증 G01~G20. 종료 코드 0 COMPLETE_PASS, 2 PARTIAL, 1 FAIL
python -m scripts.ai.prodgen verify --tree <출력 폴더> --netrc <netrc 파일> \
    --vault-password-file <vault 비밀번호 파일> --remote origin --remote internal --report-out verify.json

# 오프라인 미리보기. Jenkins, WSL, pytest 를 건너뛰므로 언제나 PARTIAL 입니다
python -m scripts.ai.prodgen verify --tree <출력 폴더> --skip-live

# production 상태 분류 (4절 표)
python -m scripts.ai.prodgen drift-check --production origin/production

# main Job 빌드에서 시나리오 증거 수집 (읽기 전용)
python -m scripts.ai.prodgen e2e-evidence --jenkins-url <Jenkins 주소> --netrc <netrc 파일> \
    --entry S1=clovirone-cicd/clovirone-server-gather-main:<빌드 번호> ... --out e2e.json
python -m scripts.ai.prodgen evidence-aggregate --report verify.json --evidence e2e.json --out verify.agg.json

# 만들어질 커밋 미리 보기. 원격은 바뀌지 않습니다
python -m scripts.ai.prodgen promote --sha "$SHA" --dry-run

# 실제 승격. 4절의 전제가 모두 맞을 때만 커밋을 만들고 두 원격에 올립니다
python -m scripts.ai.prodgen promote --sha "$SHA" --verify-report verify.agg.json --e2e-evidence e2e.json \
    --ci-stage-results ci_stage_results.json --vault-password-file <vault 비밀번호 파일> --push-remote origin,internal

# 뒤처진 원격이나 로컬 ref 를 fast-forward 로만 맞춥니다. 갈라졌으면 거부합니다
python -m scripts.ai.prodgen push-sync --remote origin --remote internal

# 되돌리기. 이전 production 커밋의 tree 를 새 커밋으로 올립니다
python -m scripts.ai.prodgen restore --to <이전 production 커밋> --push-remote origin,internal
```

- `--skip-live`는 `--dry-run`과만 쓸 수 있습니다. 건너뛴 gate가 있으면 결과는 PARTIAL이고 승격은 COMPLETE_PASS에서만 합니다.
- 실제 `promote`와 `restore`는 `--push-remote origin,internal` 정확히 그 집합만 받습니다. 원격을 하나만 쓰면 거부되고 아무것도 만들지 않습니다.
- `--ci-stage-results`는 같은 `main` 커밋의 CI 빌드가 남긴 `ci_stage_results.json`입니다. 다른 빌드의 파일을 섞으면 거부됩니다.
- `--verify-report`는 바인딩(main SHA, tree hash, 생성기 해시, manifest 해시)이 같을 때만 재사용하고, 환경 식별자(Python, Ansible, PowerShell, Jenkins 버전 등)가 다르거나 비어 있으면 환경 의존 gate(G11 G12 G13 G14 G15 G19)를 다시 실행합니다. G18과 G20은 항상 다시 실행합니다. 어느 gate를 재사용했는지는 보고서의 `gates_reused`, `gates_rerun`과 커밋 trailer에 남습니다.
- gate 구성: G01~G10, G16, G17 정적 검사. G11 syntax-check, G12 config dump, G15 module smoke. G13 Jenkins 린터. G14 생성 tree 위 pytest. G18 drift. G19 고객사 `main` 형태의 깨끗한 checkout에서 3채널 실제 실행. G20 조상과 두 원격 동일.

- Windows 작업 PC에서 결과를 파일로 받으려면 `PYTHONIOENCODING=utf-8`을 붙입니다. 붙이지 않으면 결과 출력이 cp949로 인코딩되는데, 결과의 `—` 문자를 cp949로 쓸 수 없어 `UnicodeEncodeError`로 종료 코드 1이 납니다. 결과 출력은 승격과 push가 끝난 뒤에 하므로, 이 경우에도 원격은 이미 바뀌었을 수 있습니다. 다시 실행하기 전에 5절처럼 세 ref를 직접 확인하세요. G14는 이 변수를 pytest 자식 프로세스에 넘기지 않으므로 시험 결과는 달라지지 않습니다.

vault 비밀번호 파일은 실행 중에만 저장소 밖에 두고 끝나면 지우세요.

## 4. 승격의 전제

`drift-check`가 분류하는 production 상태입니다.

| 상태 | 뜻 | 다음 승격 |
|---|---|---|
| `PROVENANCE` | 생성기가 만든 커밋. provenance, trailer, 두 원격 일치 | 일반 규칙. parent는 현재 production, 조상 검사는 현재 production의 `Main-SHA` 기준 |
| `RESTORED_BASELINE` | 첫 production(`4ce90a00`)의 tree로 되돌린 커밋 | parent는 그 커밋, 조상 검사는 마지막 생성 커밋의 `Main-SHA` 기준 |
| `LEGACY` | provenance가 없는 첫 production | `--bootstrap-baseline <SHA>`를 명시했을 때만 |
| `UNVERIFIED` | 위 근거가 없거나 어긋남 | 거부. 사람이 production을 직접 고쳤다면 고칠 곳은 `main`입니다 |

승격 명령이 확인하는 조건입니다. 하나라도 빠지면 커밋을 만들지 않습니다.

1. 같은 `main` 커밋의 CI 빌드(`clovirone-server-gather-ci`)에서 필수 단계가 모두 PASS입니다(`ci_stage_results.json`).
2. gate G01~G20이 COMPLETE_PASS이고 보고서 바인딩이 일치합니다.
3. 같은 `main` 커밋의 main Job 시나리오(S1, S2, S3, T2, T5, T6, E2E-A, E2E-A′)와 Harness 증거가 `e2e.json`에서 계약대로 PASS입니다. 기대 결과(T5 ABORTED, T6 UNSTABLE, E2E-A′ FAILURE)는 계약이 정하고 호출자가 바꿀 수 없습니다.
4. 생성 tree의 hash가 검증한 tree와 같습니다.
5. 두 원격의 `production`이 같고 현재 parent이며 G18, G20 재검사를 통과합니다.
6. `--dry-run`이 아니고 `--push-remote origin,internal`을 명시했습니다.

승격은 수집 시간대 밖에서 하고, 직후 production Job(`clovirone-server-gather`)으로 OS 대상 1~3대를 한 번 실행해 checkout SHA가 새 커밋이고 Portal 전송이 2xx인지 확인합니다. 이 확인은 첫 단계이고 완료 판정은 아닙니다. 명부 전수 재검증은 [../reference/live-validation.md](../reference/live-validation.md)에 기록합니다.

## 5. 반영 뒤 확인

- `git ls-remote origin refs/heads/production`, `git ls-remote internal refs/heads/production`, 로컬 `git rev-parse production` 세 값이 같은지 봅니다. 승격 명령은 원격마다 push 직전과 직후의 ref를 확인하고 모두 성공했을 때만 로컬 ref를 옮깁니다. 두 번째 원격만 실패하면 `partial_push`로 보고하고, `push-sync`로 맞춥니다.
- 명령의 종료 코드만으로 원격 상태를 판단하지 마세요. 비정상 종료 뒤에도 원격이 바뀌었을 수 있고, 정상 종료 뒤에도 위 세 값을 확인합니다.
- production Job 다음 빌드의 콘솔에서 `Checking out Revision`이 새 커밋인지 봅니다.
- 커밋 trailer(`Main-SHA`, `Tree-Hash`, `Verdict`, `Gates`, `Verify-Report-SHA256`)와 `.production-provenance.json`이 맞는지 봅니다.

## 6. 되돌리기

`restore --to <마지막 정상 production 커밋> --push-remote origin,internal`은 그 커밋의 tree를 새 커밋으로 두 원격에 올립니다. force push와 reset은 쓰지 않습니다. 첫 production `4ce90a00`으로 되돌릴 때만 `--bootstrap-baseline 4ce90a00`이 함께 필요합니다. 원격을 하나만 지정한 restore는 거부됩니다. 운영 Job은 브랜치를 고정해 보므로 Job 설정은 바꾸지 않습니다.

고객사 `main`은 사내 production을 되돌린 것만으로 복구되지 않습니다. 이전 정상 tree를 고객사 `main`에 다시 반영하고 그 내용으로 확인합니다([07-update-and-rollback.md](07-update-and-rollback.md) 5절).

## 7. 현재 상태

| 항목 | 값 |
|---|---|
| production | `28c38c17` (`main` `2c709fe8`에서 생성, 2026-10-15, 정규 재승격 — CI #58 COMPLETE_PASS · gate G01~G20 PASS · main Job 매트릭스 11건 · `CI-Stages: verified`. runtime tree는 직전 긴급 승격 `31f9b804`와 같음) |
| 상태 | `PROVENANCE`, 두 원격 일치 |
| 직전 production | `31f9b804` (`main` `fd7dfd6a`, 2026-10-15 긴급 승격 — CI·E2E 증거 없이 올린 커밋, trailer `Verdict: PARTIAL` · `Emergency-Promotion`) · 그 이전 `338ed8d3` (`main` `fed0b9f1`, 2026-10-14 정규 승격) · `36745453` (`main` `59bc3a19`, 2026-10-14 긴급 승격) |
| 첫 production(baseline) | `4ce90a00` |

승격 이력과 각 승격의 검증 빌드는 [../reference/decision-log.md](../reference/decision-log.md)와 [../reference/live-validation.md](../reference/live-validation.md)에 있습니다.

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| 업데이트와 설정 보존, 고객사 반영 | [07-update-and-rollback.md](07-update-and-rollback.md) |
| Job 등록과 첫 실행 | [03-job-registration.md](03-job-registration.md) |
