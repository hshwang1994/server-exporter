# 2026-11-09 — Serial Number 필수 3채널 확장 · Dell 데이터 보존 (검증 기록)

> 누가: 사용자 요청 · 결정(2026-11-09 대화 — 범위 Redfish + ESXi, Dell 통일, 공통 규칙 1개, 3채널 중복 제거, Redfish · ESXi 문장 지정, OS sudo 문장 제안)
> → AI 가 구현 · 검증 · 기록. 결정 근거: `docs/reference/decision-log.md` 2026-11-09 · `docs/ai/decisions/ADR-2026-11-09-serial-required-redfish-esxi.md`.
> 언제: 2026-11-09. 무엇: 커밋 `e25e57d9` · `6f93375d` · `f5592a0f` · `e75f7589` · `22f44e20` (+ 문서 `59344d96`).
> **실장비 검증이 아니다.** Serial 을 주지 않는 실제 Redfish · ESXi 장비와 Service Tag 가 없는 실제 Dell 은 없다. 누락 분기는 아래 대조 · 미러 사본 재생 ·
> 시험으로만 확인했다. 정상 장비 무변화의 실장비 확인은 main Job 매트릭스 · production canary(별도 기록)다.

## 1. 환경

- 작업 PC: Windows 11 · Python 3.13 — pytest(e2e · regression · 단위 일부) · 정적 검사.
- WSL Ubuntu: venv `ansible-core 2.20.3` · Python 3.12 — ansible-playbook 대조 · syntax-check · 전체 pytest.
- Tier 1 재생: `tests/redfish-probe/mirror_replay/run_tier1.py`(재생 서버 WSL Ubuntu-24.04, `--loc yi`) + `diff_tier1.py`(휘발 meta 제외 봉투 전체 · 요청 집합 대조).

## 2. OS 출력 대조 (단계별)

- 방법: 같은 흉내 playbook 에 구 규칙(`git show HEAD:os-gather/tasks/normalize/require_serial.yml`)과 새 규칙을 각각 넣고, 입력 행렬 741 사례를 돌려 봉투 전체를
  비교했다. 입력 행렬: serial(있음 · None · 빈칸 · 자리표시자) × status(success · partial · failed) × stage(null · gather · auth · port) × 기존 사유 유무 ×
  Linux/Windows × 식별자 진단 토큰(없음 · 빈 목록 · 권한 부족 · 미제공 · facts 실패 · UUID 만 · cause 없음 · 섞임) × sudo 모드. 문장 기대값은 HEAD 카탈로그 사본에서
  뽑아 시험 대상 코드에 의존하지 않게 했다.

| 단계 | 커밋 | 기대 | 결과 |
|---|---|---|---|
| 1 순수 리팩터 | `e25e57d9` | 전부 같음 | [PASS] 741/741 같음 |
| 2 중복 행 제거 | `6f93375d` | 기존 사유가 있는데 Serial 행을 붙이던 사례만 꼬리 행이 빠짐 | [PASS] 307 사례 꼬리 행만 빠짐 · 나머지 같음 |
| 3 OS 문장 원인별 | `f5592a0f` | Serial 이 대표 사유인 사례의 `failure_reason` · `errors[0].message` 만 원인별 문장 | [PASS] 362 사례(sudo 문장 90 · 일반 문장 272) · Windows 와 Linux 의 sudo 외 원인에서 sudo 문장 0 |
| 4 ESXi · Redfish 확장 | `e75f7589` | OS 는 3단계와 같음 | [PASS] |

실제 Ansible 하네스(`tests/fixtures/no_data/harness.yml` 7사례 + add-on 하네스 기준선, HEAD 대비):

| 단계 | 결과 |
|---|---|
| 1 | 8/8 같음 |
| 2 | no_data `many` · `no_data` · `no_errors` · `windows` 만 다름 — 대표 문장과 같은 문장의 꼬리 Serial 행 1건이 빠짐(예: windows `errors[2]` `cause=not_collected`) |
| 3 | + add-on 기준선 2대의 `failure_reason` · `errors[0].message` 가 종전 OS 문장 → 새 OS 일반 문장 |
| 4 | ESXi · Redfish 사례: 성공 섹션 0개(H12)는 `errors` 그대로(2건) + `details.serial_number`(`not_collected`) · 섹션 성공 + Serial 없음은 `failed` / `gather` / `GATHER_FAILED` · `errors` 1건 · `not_provided` · Redfish 미독취(BMC 를 읽지 않음)는 `success` 그대로 |

## 3. Tier 1 미러 재생 (Redfish)

대상 21대: mock2 11대(CSUS 3200 ×3 · DL380 Gen12 ×4 · SR650 V4 ×4) + 1차 7대(R740 · CSUS 3200 ×4 · DL380 · SR650) + 사본 3대.
상태 3개: `before`(`e25e57d9` 앞, 2026-11-09 시작 시 HEAD) · `after4`(`e75f7589`) · `after5`(`22f44e20`).

사본 만드는 법(원본 미러는 읽기 전용, WSL 서버 배포판의 별도 폴더에 복사본):

| 사본 | 원본 | 바꾼 것 | 노린 경우 |
|---|---|---|---|
| `doc_dl380_nosn` | `dl380_gen12_01` | `Systems/1` 의 `SerialNumber` 키 삭제 | C1 — 섹션 성공, Serial 없음 |
| `doc_dl380_sys500` | `dl380_gen12_01` | `Systems/1` GET 을 500 + 빈 본문으로 | C2 — Serial 을 담는 섹션 실패 |
| `doc_r740_notag` | 1차 `DELL_R740/01` | 무인증 · 인증 ServiceRoot 둘 다 `Oem.Dell.ServiceTag` 삭제 | C8 — Dell Service Tag 없음 |

| 대조 | 결과 |
|---|---|
| before → after4, 정상 18대 | [PASS] 봉투 차이 0 · 요청 차이 0 |
| before → after4, 사본 | [PASS] nosn 11경로 · sys500 13경로 · notag 3경로 — 전부 허용 목록(status · 대표 사유 · `errors` · `details.serial_number`), 미설명 0, 요청 차이 0 |
| before → after5, 정상 18대 | [PASS] 봉투 차이 0 · 요청 차이 0 (Dell R740 정상 미러 포함 — adapter `redfish_dell_idrac9` · 142 요청 그대로) |
| after4 → after5, 20대(Dell 사본 제외) | [PASS] 봉투 차이 0 · 요청 차이 0 |
| before → after5, nosn · sys500 | [PASS] after4 와 같음(11 · 13경로, 미설명 0) |
| after5 정상 R740 → after5 Dell 사본 | [PASS] 16경로 — 전부 허용 목록, 미설명 0, 요청 집합 같음(distinct 138) |

Dell 사본(C8)의 값 — 같은 재생의 정상 R740 과 다른 곳만:

| 경로 | 정상 R740 | Service Tag 없는 사본 |
|---|---|---|
| `status` | `success` | `failed` |
| `diagnosis.failure_stage` · `failure_code` | null · null | `gather` · `GATHER_FAILED` |
| `diagnosis.failure_reason` = `errors[0].message` | null | "서버의 Serial Number를 확인하지 못했습니다. BMC에서 Serial Number가 정상적으로 제공되는지 확인하세요." |
| `errors` | 0건 | 1건(`section: redfish_gather`, `detail: field=serial_number; mandatory=true; cause=not_provided`) |
| `diagnosis.details.notices` | 0건 | 1건(`system` — "서버 대표 시리얼을 확인하지 못했습니다 — ServiceRoot.Oem.Dell.ServiceTag 없음") |
| `diagnosis.details.serial_number` | 없음 | `{present: false, cause: not_provided, sudo: null}` |
| `data.hardware.serial` · `correlation.serial_number` | Service Tag | null (보드 시리얼 · SKU 로 대체 없음) |

`sections` 11개와 `data` 의 나머지 값은 정상 R740 과 같다. 요청은 143건(정상 142 + 인증 ServiceRoot 재조회 1건 — 무인증 ServiceRoot 에 태그가 없을 때만, 종전 동작 그대로).
변경 전(before · after4) 같은 사본은 adapter `redfish_dell_idrac10`(재선택 전) · 요청 9건에서 멈춰 `failed`, 성공 섹션 0개, 문장 "대상 Redfish 인증은 성공했지만
정보를 가져오지 못했습니다." 였다.

## 4. pytest

| 실행 | 범위 | 결과 |
|---|---|---|
| Windows, `e75f7589` + 5단계 작업본 | `tests/e2e tests/regression` | [PASS] 1104 passed · 12 skipped · 5 xfailed |
| Windows, 5단계 작업본 | `tests/unit/test_dell_service_tag_serial.py` | [PASS] 73 passed |
| WSL, `e75f7589` tar 추출본(git 저장소 아님) | `tests/` 전체 | 7211 passed · 80 skipped · 5 xfailed · **74 failed — 전부 환경**: Windows PowerShell 시험 5파일 69건(WSL 에서 PowerShell 을 부르지 못함) · git index 실행 비트 시험 2파일 5건(추출본이라 index 없음) |
| Windows, 실제 저장소 | 위 실패 7파일 | [PASS] 197 passed |
| WSL, HEAD(`59344d96`) git clone | `tests/` 전체 | 6절 |

## 5. 정적 검사 (작업본 = 5단계 커밋 직전)

- `verify_vendor_boundary.py` 통과 · `verify_harness_consistency.py` 통과 · `tests/validate_field_dictionary.py` PASS(0 failed) ·
  `output_schema_drift_check.py` 정합(sections 11 · fd_paths 264) · `pre_commit_jinja_compile_check.py --all --blocking` rc 0 ·
  `py_compile`(`redfish_gather.py` · `emulator_harness.py` · Dell 시험) OK.

## 6. 최종 (HEAD `59344d96` — 코드는 이 커밋이 마지막, 뒤 커밋은 문서뿐)

- WSL ext4 git clone(LF) · venv ansible-core 2.20.3:
  - `ansible-playbook --syntax-check` 3채널 rc 0 (os · esxi · redfish — 대상 목록을 넘기지 않아 inventory 경고만).
  - `pytest tests/` — 7296 passed · 18 skipped · 5 xfailed · **84 failed — 전부 환경**:
    - Windows PowerShell 시험 5파일 81건 — WSL 에서 PowerShell 을 부르지 못한다(2026-10-28 기록의 G3 와 같은 81건). 같은 파일은 Windows 에서 통과(4절, 코드 동일).
    - `tests/unit/test_env_guard.py` 3건 — 이 실행 래퍼가 `REPO_ROOT` 를 export 해 시험이 "남은 변수" 로 본 것. `env -u REPO_ROOT` 로 다시 돌려 9 passed.
- 변경 YAML 10개 PyYAML 파싱 OK(yamllint 는 Windows · WSL venv 모두 미설치 — 환경 제약, CI gate 에도 없음).

## 7. 훅 우회 기록

- additive-only 훅(`scripts/ai/hooks/pre_commit_additive_only_check.py`)만 `ADDITIVE_SKIP_NEW_CYCLE=1` 로 넘겼다. 감시 대상 중 바뀐 파일과 이유:
  - `e75f7589`: `common/tasks/normalize/build_status.yml`(시나리오 E 주석 행 교체) · `schema/field_dictionary.yml`(help · channel 줄 교체).
  - `22f44e20`: `schema/field_dictionary.yml`(`hardware.serial` help 한국어 · 영어 교체 — 삭제 4줄 · 추가 7줄). 커밋 본문의 괄호 설명("모듈 실패 분기 · 고정
    시험 교체")은 같은 커밋의 다른 변경을 가리킨 것이고, 훅이 본 파일은 이것 하나다.
  - 1~3단계(`e25e57d9` · `6f93375d` · `f5592a0f`)는 감시 대상 파일을 건드리지 않았다(이 훅이 검사할 것이 없음).
  - 두 커밋 모두 envelope 키 · 섹션 · field_dictionary 항목(경로 · 타입 · priority) 변화 0.
- `--no-verify` 는 쓰지 않았다.

## 8. 실장비에서만 확인 가능

- Serial 을 주지 않는 실제 Redfish · ESXi 장비, Service Tag 를 노출하지 않는 실제 Dell(iDRAC7/8 후보 — `docs/ai/NEXT_ACTIONS.md` DELL-ST-1).
