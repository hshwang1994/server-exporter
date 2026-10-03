# production 브랜치 — runtime-only tree 생성 · 검증 · 반영 · 복구

> 2026-10-03 부터 `production` 브랜치는 사람이 편집하거나 main 을 병합하는 브랜치가 아니다. **고정된 main SHA 에서 생성기(`prodgen`)가 만든
> runtime-only tree** 를 append 커밋으로 올린다. 생성물에는 테스트 · 문서 · 스키마 · 하네스 · 운영자 도구가 없고 설명성 주석이 전부 제거돼 있다.
> 결정 근거는 `docs/ai/decisions/ADR-2026-10-03-production-generation.md`(main 전용 문서).

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

## 2. 명령 (main checkout 에서, Windows 또는 pwsh 가 있는 Linux)

```bash
SHA=$(git rev-parse main)
python -m scripts.ai.prodgen build   --sha "$SHA" --out /tmp/prodtree          # 생성 (object store 만 읽는다)
python -m scripts.ai.prodgen verify  --tree /tmp/prodtree [--netrc <netrc>]    # gate G01~G17 (--skip-live: WSL/Jenkins/pytest 제외)
python -m scripts.ai.prodgen drift-check --production origin/production        # 현재 production 이 provenance 대로인지
python -m scripts.ai.prodgen promote --sha "$SHA" --dry-run                    # 만들어질 커밋(parent · tree · trailer) 미리 보기
python -m scripts.ai.prodgen promote --sha "$SHA" --push-remote origin         # 실제 반영 (아래 3절 전제 충족 시에만)
python -m scripts.ai.prodgen restore --to <production commit> --dry-run        # 되돌리기(append 커밋, 이력 재작성 없음)
```

- 생성기는 PowerShell 주석 제거 검증에 **실제 PowerShell 파서**(`pwsh` 또는 `powershell.exe`)가 필요하다. 없으면 Windows task 의 PowerShell 주석이 "미제거" 로 남아 **승격이 차단**된다.
  Windows 호스트에서는 기본으로 있고, Linux Runner 에는 `pwsh` 설치가 필요하다.
- `build` 가 "class B" 를 보고하면 생성기가 제거를 증명하지 못한 주석이다 — 코드를 바꾸지 말고 보고된 파일·줄을 보고 생성기 규칙을 고친다.
- gate 중 G14 는 생성 tree 위에 `tests/` · `schema/` 를 얹어 pytest 를 돌린다. 저장소 메타·문서·주석을 읽는 테스트는 `source_text` 표식으로 제외된다(`pytest.ini`).

## 3. 반영(승격)의 전제 — 하나라도 빠지면 하지 않는다

1. `verify` 가 전부 PASS 이고 B 가 0 이다.
2. `drift-check` 가 현재 `origin/production` 이 기록된 provenance 와 같다고 한다(LEGACY 는 첫 승격에서만 허용 — bootstrap).
3. main 의 같은 SHA 가 **main Job(`clovirone-server-gather-main`)에서 실제로 1회 이상 성공** 했다(파이프라인 재설계는 Jenkins 에서 돌아 봐야 안다).
4. 승격 **직후** production Job(`clovirone-server-gather`)으로 canary 1회(os 1~3대 · Callback 2xx)를 확인한다. 실패하면 `restore` 로 되돌린다.
5. 수집 시간대 밖에서 한다(첫 승격은 983 → ≈190 파일로 줄어드는 큰 append 커밋이다).

2026-10-03 현재: 1 은 충족(main `f1221234` 기준 B 0, G01~G13 · G15~G17 PASS), 2 는 LEGACY(첫 승격), **3 · 4 미충족** — 작업 세션이 Jenkins 빌드를 실행할 수 없어 보류했다.
재개하려면 사용자가 main Job 을 1회 돌려 성공을 확인한 뒤 위 `promote --push-remote` 를 실행하고 production Job canary 를 본다.

## 4. 반영 뒤 확인

- `git ls-remote origin production` 과 `git ls-remote internal production` 이 같은 SHA 인가(두 push URL 은 원자적이지 않다).
- production Job 다음 빌드의 checkout SHA 가 그 커밋인가(`docs/operate/03-job-registration.md`).
- 커밋 trailer `Main-SHA` 가 테스트한 main SHA 와 같은가. 생성 tree 의 `.production-provenance.json` 과 `drift-check` 결과.

## 5. 되돌리기

`restore --to <마지막 정상 production 커밋>` 은 그 tree 를 **새 커밋**으로 올린다(force push · reset 금지, trailer `Restore-Of`). production Job 은 브랜치 고정이라 추가 조치가 없다.
사람이 production 을 직접 고치면 다음 `drift-check` 가 막는다 — 고칠 것은 main 이다.
