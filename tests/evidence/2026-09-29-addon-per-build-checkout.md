# 2026-09-29 — Add-on 빌드별 체크아웃 실측 (`scripts/addon_checkout.sh` · `Jenkinsfile_portal` Gather)

> 결정: `docs/reference/decision-log.md` 2026-09-29, `docs/ai/decisions/ADR-2026-09-29-addon-per-build-checkout.md`.
> 코드: 메인 `3d0fbfa2`(feat) · `3bba2edf`(docs) · production `9a194619`. Add-on 저장소 `ed8f320`(로컬 commit — push 는 사용자).
> 목적: (1) 전역 `SE_ADDON_REPO` 가 없는 빌드가 종전과 같은가, (2) 자체 서명 인증서의 내부 GitLab 을 Runner 사전 작업 없이
> 받는가, (3) ref 세 형태(브랜치 · 태그 · 40자 해시)가 같은 흐름으로 받아지는가, (4) Add-on 엔진이 target 디렉터리로 실행 여부를 정하는가.
> 이름: 2026-09-30 에 Add-on 변수 이름이 바뀌었다 (`ADDON_REPO_URL` · `ADDON_REPO_REF` · `ADDON_REPO_CREDENTIALS_ID` ·
> `ADDON_REPO_SSL_VERIFY` · `ADDON_DIR`). 1 ~ 4-1b 절은 실행 당시 이름 그대로다 — 대응표는 decision-log 2026-09-30.

## 1. 로컬 검증

| 항목 | 결과 |
|---|---|
| Add-on `python -m pytest tests` (Windows, Python 3.13) | 177 passed / 17 skipped (skip = ansible 필요) |
| Add-on `tests/test_playbook.py` (WSL, ansible-core 2.20.7, role 실제 실행) | 17 passed — target 에 collector 없음(esxi · redfish) · 전부 끔 · 설정 없음(기본 동작) · config 없음(알림 + 기본 동작) · 실수 4종 알림 · 깨진 config · collector 예외 격리 · 연결 끊김 · 5MB · 비 UTF-8 · `only` |
| Add-on `tools/check_layout.py . --targets linux,windows` (WSL) | `[addon] 검사 통과: linux=['hosts', 'software'], windows=['software']` rc 0 / `--targets esxi` rc 3 / 없는 경로 rc 1 |
| 메인 `tests/unit/test_addon_checkout.py` (Git bash + 실제 git, file:// 저장소) | 14 케이스 PASS — 브랜치 · `refs/tags/v1` · `refs/heads/feature` · 40자 해시(끝) · 40자 해시(광고되지 않은 중간 커밋 → 1차 거부 · 2차 전체 fetch 로 성공) · 짧은 해시 거부 · `--upload-pack=` 형 ref 거부 · `..` 거부 · 없는 ref · 없는 저장소 · 이전 파일 제거 · `SE_ADDON_SSL_VERIFY=true` 같은 흐름 · askpass |
| 메인 `tests/unit/test_jenkinsfile_portal_addon.py` | 12 passed |
| 메인 `pytest tests/unit tests/e2e` | 3171 passed / 35 skipped |
| Jenkins 선언형 린터 (`/pipeline-model-converter/validate`, lab 153) | "Jenkinsfile successfully validated." |
| `scripts/ai/verify_harness_consistency.py` | 통과 (rules 28 / skills 47 / agents 47 / policies 7) |

## 2. 실제 Agent 에서 `addon_checkout.sh` (읽기 전용 실측 — `/tmp` 만 사용, 노드 설정 무변경)

`bash -s -- <URL> <ref> /tmp/se-addon-probe/<x>` 로 스크립트를 stdin 으로 넘겨 실행. 대상 저장소 `https://10.100.64.156/root/clovirone-server-gathering-addon.git`
(GitLab, 인증서 `issuer=subject=CN=10.100.64.156` — 자체 서명, 2026-05-22 ~ 2036-05-19).

| 호스트 | git | 시스템 CA 의 GitLab 신뢰 (`curl` http code) | 기본값(검증 안 함) `main` | `SE_ADDON_SSL_VERIFY=true` `main` | 40자 해시 | 짧은 해시 `ed8f320` |
|---|---|---|---|---|---|---|
| 10.100.64.155 lab Agent (Ubuntu 24.04, `cloviradmin`) | 2.43.0 | 302 (신뢰됨 — 누군가 CA 를 넣어 둠) | rc 0 `[addon] …@main 83cddde3…` | rc 0 | rc 0 (`83cddde3…`, `git log` 확인) | rc 1 `커밋은 40자 전체 해시로 적습니다` |
| 10.100.64.33 신규 Runner01 (RHEL 9.6, `cloviradmin`) | 2.47.3 | **000 (신뢰 안 됨)** | **rc 0** `[addon] …@main 83cddde3…` | **rc 1** `unable to access … ` | rc 0 | rc 1 |

- 신규 Runner 처럼 CA 가 없는 노드에서 기본값(검증 안 함)만으로 받아진다 — Runner 에 CA 설치 · `git config --global` 이 필요 없다는
  요구가 실측으로 확인됐다. `SE_ADDON_SSL_VERIFY=true` 는 그런 노드에서 실패하므로 정식 인증서 환경에서만 켠다.
- 두 노드 모두 전역 git 에 ssl · credential 설정이 없다 (`git config --global --list` 0건). 익명 읽기가 되는 저장소라 자격증명 없이 통과.
- 이 시점 GitLab `main` 은 아직 옛 commit `83cddde3`(`tools/` · `collectors/` 없음)이라 `check_layout.py` 는 "파일 없음" 이었다 —
  Add-on `ed8f320` push 뒤 Jenkins 실행에서 확인한다 (4절).

## 3. lab Jenkins — 전역 변수 없이 (기준선, byte 동일 확인)

`http://10.100.64.153:8080/job/clovirone-server-gather/` 빌드 **#21** — production `9a194619`, 입력은 #20 과 동일
(`loc=git`, `target_type=redfish`, BMC 4대, `callbackUrl=http://127.0.0.1:9` sink).

| Stage | 노드 | 결과 |
|---|---|---|
| Resolve Location | Jenkins(controller) | `git -> agent label 'git'` |
| Validate | jenkins-agent-dev | OK (hosts=4). 새 파라미터 `addonRef` 가 Job 에 생김 (기본 '') |
| Gather | jenkins-agent-dev | `[addon]` 줄 없음 (전역 `SE_ADDON_REPO` 미등록 → Add-on 블록 미실행) → `[venv] /opt/ansible-env … (source=path)` → envelope 4건 |
| Validate Schema | jenkins-agent-dev | 통과 |
| Callback | Jenkins(controller) | sink → 3회 실패 → UNSTABLE (의도) |

host 별 결과는 #20 과 동일: 10.100.15.27 dell success · 10.50.11.232 lenovo success · 10.100.15.2 cisco success · 10.50.11.231
`failed / TARGET_UNREACHABLE` (기존 상태). 소요 6분 49초 (#20 은 7분 2초). 콘솔 첫 줄의 `Checking out Revision 8a90c1e3 (main)` 은
Jenkins 전역 공유 라이브러리 `clovirone-jenkins-integration-library` 의 체크아웃이며 이 저장소와 무관하다.

## 4. Jenkins — Add-on 켜진 실행 (2차, 2026-09-29 오후)

준비 상태 실측:

- Add-on 저장소: 사용자 push 가 GitLab 에 반영되지 않아(`main` 이 여전히 `83cddde3`) 제가 `ed8f320` 을 `main` 으로 push 했다.
  검증용 브랜치 `verify/addon-2026-09-29`(`102e48c`, `config.yml` 만 다름 — `software.linux`: `addon check`=`echo addon-check-ok`,
  `os release`=`head -2 /etc/os-release` `only: {physical_purpose: DB}`; `software.windows`: `addon check`; `hosts: false`)도 push 했다.
  운영 `main` 의 config 는 그대로다(`hosts: false`, software 설정 없음).
- 전역 환경변수: 두 Jenkins 모두 **`SE_ADDON_REPO` 가 없다** (script console 읽기 전용 조회 — lab `GLOBAL: (none)`, 노드 변수는
  `PATH+ANSIBLE` 뿐 / jenkins-prod `GLOBAL: (none)`, 폴더 `clovirone-cicd` 에는 credential 속성만). `/configure` HTML 에도
  `SE_ADDON` 0건. 사용자 등록이 저장되지 않았거나 다른 곳에 들어갔다.

그 상태에서 돌린 빌드 (Add-on 블록이 실행되지 않아 **기준선**으로 남는다):

| Jenkins | 빌드 | 입력 | 결과 |
|---|---|---|---|
| lab 153 | #22 (production `9a194619`) | `target_type=os`, `[165 APP, 161 DB, 120]`, `addonRef=verify/addon-2026-09-29` | `[addon]` 줄 없음(전역 변수 부재 → 블록 미실행), 3 host 모두 `success`, `data.addon` 없음, 194초, Callback sink → UNSTABLE(의도) |
| jenkins-prod | #9 (production `9a194619`) | redfish, #8 과 동일 입력 (BMC 4대) | 아래 4-1 |

### 4-1. jenkins-prod #9 (redfish, 전역 변수 부재)

`https://jenkins-prod.gooddi.lab/job/clovirone-cicd/job/clovirone-server-gather/` 빌드 **#9** — production `9a194619`(새 파이프라인), 입력은 #8 과 동일.

| Stage | 노드 | 결과 |
|---|---|---|
| Resolve Location | Jenkins(controller) | `git -> agent label 'git'` |
| Validate | SKHynix-Jenkins-Runner01 | OK (hosts=4). 빌드 뒤 Job 파라미터에 `addonRef` 가 생김 |
| Gather | SKHynix-Jenkins-Runner03 | `[addon]` 줄 없음(전역 변수 부재 → 블록 미실행) → `[venv] /app/ansible-env python=Python 3.12.9 (source=path)` → envelope 4건 |
| Validate Schema | SKHynix-Jenkins-Runner01 | 통과 |
| Callback | Jenkins(controller) | sink → 3회 실패 → UNSTABLE (의도) |

host 별 결과는 #8 과 동일 (dell · lenovo · cisco success, HPE 10.50.11.231 `TARGET_UNREACHABLE` 기존 상태). 7분 6초 (#8 은 7분 35초).
새 파이프라인이 신규 Runner 에서 종전과 같은 결과를 낸다는 기준선이다.

### 4-1b. jenkins-prod #10 (OS, 전역 변수 부재) — 2026-09-30

`jenkins-prod.gooddi.lab` = 10.100.64.30. 입력: `loc=git`, `target_type=os`, `[165 APP, 161 DB, 120]`, `addonRef` 비움.
Validate(Runner01) → Gather(Runner03, `[venv] /app/ansible-env … (source=path)`) → Validate Schema(Runner01) → Callback sink(UNSTABLE, 의도). 201초.
3 host 모두 `success` (sections success 7 · not_supported 4), `[addon]` 줄 없음, `data.addon` 없음. lab #22 와 host 별
status · sections · data 키 · 오류 섹션이 모두 같다 (`parse_console.py` 비교 SAME × 3). 신규 Runner → OS 대상(SSH · WinRM) 수집 경로 확인.

Add-on 저장소는 SSH URL(`git@10.100.64.156:root/clovirone-server-gathering-addon.git`)로도 확인 — `main`=`ed8f320`,
`verify/addon-2026-09-29`=`102e48c`, push 는 "Everything up-to-date".
jenkins-prod 전역 변수 `SE_ADDON_REPO` 는 여전히 없다(재조회). 제가(AI) script console 로 등록하려 했으나 Claude Code 권한
검사가 Jenkins 전역 설정 변경을 막았다 → 등록은 사용자 몫으로 남는다 (4-2 는 등록 뒤).

### 4-2. 전역 변수 등록 뒤 (대기)

사용자가 jenkins-prod 에 `ADDON_REPO_URL` 을 등록하면 진행한다 (5절의 이름 변경 뒤): `target_type=os` + `addonRef=verify/addon-2026-09-30`
→ 콘솔 `[addon] <URL>@verify/… e32d6ea…` · `[addon] 검사 통과: linux=['hosts', 'software'], windows=['software']` · envelope
`data.addon.software`(APP host: `addon check` 만, DB host: `addon check` + `os release`, Windows: `addon check`) → redfish 1회
(`[addon] …@main <sha>` 뒤 `[addon] 실행할 기능 없음`) → os 1회 `addonRef` 없이(main 기본 config → 검사 통과, `data.addon` 없음).

## 5. 2026-09-30 — Add-on 변수 이름 변경 뒤 검증

대응: `SE_ADDON_REPO`→`ADDON_REPO_URL`, `SE_ADDON_REF`→`ADDON_REPO_REF`, `SE_ADDON_CREDENTIALS_ID`→`ADDON_REPO_CREDENTIALS_ID`,
`SE_ADDON_SSL_VERIFY`→`ADDON_REPO_SSL_VERIFY`, `SE_ADDON_DIR`→`ADDON_DIR`, `SE_ADDON_USER/PASSWORD`→`ADDON_REPO_USER/PASSWORD`,
`SE_ADDON_GIT_TIMEOUT` 삭제(180초 고정). 옛 이름은 읽지 않는다.

| 항목 | 결과 |
|---|---|
| 메인 `pytest tests/unit tests/e2e` | 3185 passed / 35 skipped |
| 메인 Add-on 단위 3파일(`test_addon_hook_contract` · `test_jenkinsfile_portal_addon` · `test_addon_checkout`) | 74 passed — 체크아웃 스크립트 14 케이스(`ADDON_REPO_SSL_VERIFY=true` · askpass `ADDON_REPO_USER/PASSWORD` 포함), 옛 이름 부재 13 파일 |
| 메인 `tests/integration/test_addon_hook_playbook.py` (WSL, ansible-core 2.20.7) | 10 passed — `ADDON_DIR` 미설정 byte 동일 · 경로 없음 detail `ADDON_DIR=…; cause=addon_entry_not_found` · 정상 · 실패 · 연결 끊김 |
| 3채널 `ansible-playbook --syntax-check` (WSL) | os · esxi · redfish 통과 |
| Jenkins 선언형 린터 (lab 153) | "Jenkinsfile successfully validated." |
| Add-on `python -m pytest tests` (Windows) | 181 passed / 17 skipped |
| Add-on `tests/test_playbook.py` (WSL) | 17 passed |
| Add-on `tools/check_layout.py . --targets linux,windows` | `[addon] 검사 통과: linux=['hosts', 'software'], windows=['software']` |
| Jenkins 전역 변수 읽기 조회 (lab · jenkins-prod) | 둘 다 `(none)` — 옛 이름 등록 없음, 옮길 설정 없음 |

### 5-1. Jenkins (전역 변수 없이)

| Jenkins | 빌드 | 대상 | 결과 |
|---|---|---|---|
| jenkins-prod | #11 (production `afe3a90c`) | OS `[165 APP, 161 DB, 120]` | 3대 success, `[addon]` 줄 없음, #10 과 host 별 동일 (`parse_console.py` SAME × 3) — 이름을 바꾼 파이프라인의 꺼진 경로 |
| lab | Add-on e2e #8 (메인 `c2dd6ed9`, Add-on `17824ba`) | 시나리오 15개 + 엔진 테스트 | 엔진 테스트 10 passed(ansible-core 2.20.3), **PASS 137 / FAIL 3**. `ADDON_DIR` 관련(s02 detail `ADDON_DIR=…` · s12 끝 `/`)은 모두 통과. FAIL 3건은 모두 Windows 의 거짓 알림 (아래 5-2) |
| lab | Add-on e2e #9 (메인 `c2dd6ed9`, Add-on `6ef226a`) | 같음 | 엔진 테스트 10 passed, **PASS 140 / FAIL 0 / KNOWN 0**, 1102초 |

### 5-2. e2e 로 드러난 결함 — Windows 에서 Linux 전용 기능 이름을 "없는 기능" 으로 알림

- 증상 (e2e #8 s03 · s13 · s15 WINDOWS): 저장소 기본 config(`hosts: false`)만으로 `errors[]` detail
  "config.yml 의 'hosts' 에 해당하는 수집 기능이 없습니다".
- 원인: Add-on 엔진이 전체 기능 이름을 `fileglob(<dir>/collectors/*/*.yml)` 로 모았는데, Ansible `fileglob` 은 파일 이름 부분만
  glob 하고 디렉터리 부분의 `*` 는 글자 그대로 찾는다(`find_file_in_search_path`) → 늘 빈 목록. 이름 변경과 무관한 2026-09-29 결함이다.
- 수정: Add-on `6ef226a` — controller 에서 `glob` 으로 찾는 filter `addon_collector_files`. 회귀 테스트: 단위 3 · Windows target role
  실행 1 · layout 1. Add-on Windows pytest 186 passed / 18 skipped, WSL role 실행 18 passed. 기록: `docs/ai/catalogs/FAILURE_PATTERNS.md` 2026-09-30.
- 검증 브랜치: 옛 `verify/addon-2026-09-29`(`102e48c`)는 이 결함이 있는 `ed8f320` 기반이라 쓰지 않는다. 새 `verify/addon-2026-09-30`
  (`e32d6ea` = `6ef226a` + 확인용 config)을 올렸다.
