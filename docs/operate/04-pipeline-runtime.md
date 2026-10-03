# Jenkins 파이프라인 런타임

> 이 문서는 server-exporter 의 운영 파이프라인 `Jenkinsfile_portal` 이 실제로 어떤 단계로 실행되는지 정리한다.
> 각 단계가 어느 노드에서 도는지, 어디서 실패하면 어떻게 전파되는지, 호출자에게 어떤 형식으로 결과가 돌아가는지를 한 페이지에 모았다.
>
> Jenkinsfile 을 수정해야 한다면 본 문서의 단계 구조와 게이트 정책을 먼저 이해한 뒤 손댄다.

> 검증일: 2026-09-28 (lab Jenkins `clovirone-server-gather`, `production` 브랜치)

## 1. 파이프라인 구조

`Jenkinsfile_portal` 은 최상위 `agent none` 이고 단계마다 노드를 고른다. 컨트롤러(`built-in`)에는 Python 도 Ansible 도 필요 없다.

```text
parameters (loc, target_type, inventory_json, deploymentEnvironmentId, eventUuid, callbackUrl, verbosity
            + 검증용 redfishAccountDryrun, gatherBudgetForceSec — 기본값이면 운영 동작 불변)
  → Validate          [agent 없음]  파라미터 형식 검증 → 접수 manifest(env SE_MANIFEST_JSON: 빌드·채널·요청 식별·접수 IP 목록)
  → Resolve Location  [agent 없음]  readTrusted 로 common/vars/locations.yml 하나만 읽어 loc 검증, target_type 능력 라벨과 && 로 이어 노드 라벨식 결정 (맞는 온라인 노드 없으면 즉시 실패)
  → Gather            [Agent]     manifest 를 gather_manifest.json 으로 기록 → (전역 ADDON_REPO_URL 이 있으면 Add-on 체크아웃 · 검사)
                                  → 예산 계산(scripts/gather_budget.sh — ansible 직전 재계산) → timeout --signal=INT --kill-after=90 <예산> ansible-playbook … -f <forks>
                                  → rc → outcome(completed / timeout / timeout_killed / prep_failed / not_started_budget / failed_run)
                                  post{always}: Layer A(scripts/finalize_gather_output.py: 접수 = 결과 보충) → archiveArtifacts → stash → (manifest 가 이 빌드 것일 때만) deleteDir
  pipeline post{always} [컨트롤러, 합산 720 s]  unstash(없으면 unarchive) → Layer A 결과 또는 Groovy 최소 보충(scripts/jenkins/se_finalize.groovy 를 readTrusted→load)
                                               → 호출자에게 POST(남은 예산 안 ≤3회) → callback_body.json 보존
```

> 2026-10-03: Validate 와 Resolve Location 은 더 이상 노드를 잡지 않는다. 종전에는 Resolve Location 이 컨트롤러에서
> 저장소 **전체**를 체크아웃한 뒤 YAML 1개를 읽었고, `main`(약 17k 파일)은 2분 제한을 넘겨 끊겼다. `readTrusted` 는
> Job 의 SCM 설정(Lightweight checkout)으로 파일 하나만 읽는다.
>
> 2026-10-03 (Phase 4): `Validate Schema` 와 `Callback` stage 는 없어졌다. field_dictionary 정합은 커밋 전 `scripts/ai/ci_gate.sh`
> (pre-commit · CI) 가 맡고, 결과 전달은 **파이프라인 `post { always }`** 의 마무리 단계가 맡는다 — stage 가 어디서 끊겨도(agent 대기
> 초과 · ansible 강제 종료 · 1회 Abort) 실행 **경로**가 있다. 요청한 대상 1개마다 결과 1개를 보낸다: 완료된 host 는 OUTPUT 그대로,
> Add-on 도중 끊긴 host 는 `CHECKPOINT`(조립 직후 보존본), 그 밖은 진행 기록(`gather_progress.jsonl`)에 따라 실패 봉투로 채운다 (8절).

| Stage | 노드 | 하는 일 | 실패 시 |
|-------|------|--------|--------|
| Validate | 없음 | `target_type` / `inventory_json`(JSON 배열 · 원소 객체 · `service_ip`/`bmc_ip`/`ip`) / `callbackUrl` / `deploymentEnvironmentId` 검증, 접수 manifest 를 `env.SE_MANIFEST_JSON` 으로 | FAILURE |
| Resolve Location | 없음 | `readYaml text: readTrusted('common/vars/locations.yml')` — 미등록 `loc` 는 노드 대기 없이 즉시 실패 | FAILURE |
| Gather | `agent_label && 능력 라벨` 노드 (stage 합산 상한 115분 — agent 대기 포함) | `gather_manifest.json` 기록 → (전역 `ADDON_REPO_URL` 이 있으면 Add-on 저장소를 `${WORKSPACE}/addon` 에 받고 검사 — 3절) → venv 활성화 → **예산 재계산**(`scripts/gather_budget.sh`: 빌드 시작 기준 전체 150분 − 마무리 예비 990 s, stage 잔여, host 수·채널·forks 기반 상한 중 최소; 120 s 미만이면 수집을 시작하지 않는다) → `timeout --signal=INT --kill-after=90 <예산> ansible-playbook <채널>/site.yml -i <채널>/inventory.sh -f <forks> --vault-password-file=<임시파일> -e se_location=<loc>` (`redfishAccountDryrun` 이 켜진 빌드만 `-e _rf_account_service_dryrun=true`) → rc 를 `gather_rc.txt` 에, outcome 을 기록 → post{always}: Layer A(`scripts/finalize_gather_output.py`) → `archiveArtifacts` → `stash` → manifest 가 이 빌드의 것일 때만 `deleteDir` | Add-on 을 받지 못하면 UNSTABLE + Add-on 없이 수집; ansible 이 비정상 종료(rc 124/137 timeout, 그 밖)여도 stage 는 끊지 않고 outcome 만 남긴다 — 결과 전달은 마무리 단계가 한다 |
| (post) 마무리 | `built-in` — `timeout(720 s) { node('built-in') }` 합산 제한 | `unstash` → 없으면 `unarchive` → `gather_final.jsonl`(Layer A, exit 0/2) 우선, 없으면 Groovy 최소 경로(OUTPUT → CHECKPOINT+오류 1건 → 합성 실패 봉투) → `접수 수 == 결과 수` 단언 → `{loc, deploymentEnvironmentId, eventUuid, gatherInfoJson:[…]}` POST(남은 시간 안 ≤3회, 시도별 10~120 s, 4xx(408/429 제외)는 즉시 중단, ABORTED 면 1회) → `callback_body.json` · `finalize_summary.json` 보존 | 전송 실패 · 합성 보충 있음 · outcome ≠ completed → UNSTABLE. 접수 manifest 조차 없으면(Validate 전 실패) 보낼 것이 없다 |

### Ansible 실행환경(venv) 선택

Gather(수집과 Layer A 마무리)는 저장소의 `scripts/activate_ansible_venv.sh` 를 한 줄로 source 한다.

```bash
. "${WORKSPACE}/scripts/activate_ansible_venv.sh" || exit 1
```

이 스크립트가 다음 순서로 venv 를 고르고, 못 찾으면 시스템 python 으로 넘어가지 않고 Stage 를 실패시킨다.

1. 노드 환경변수 `SE_ANSIBLE_VENV` (값이 있는데 틀리면 다른 경로로 넘어가지 않는다)
2. PATH 의 `ansible-playbook` 실경로 옆의 `activate` (설치 자동화 Runner 는 `/usr/local/bin/ansible-*` 링크)
3. 알려진 경로 `/app/ansible-env` → `/opt/ansible-env`

성공하면 콘솔에 `[venv] <venv 경로> python=<버전> (source=env|path|known)` 한 줄이 남는다. 서버마다 다른 venv 경로가
파이프라인 코드에 적히지 않는 이유가 이것이다 ([02-agent-node.md](02-agent-node.md) 5절·9절).

> [!NOTE]
> pytest 회귀(`tests/e2e`, `tests/integration -m "not live"`, `tests/regression`)와 field_dictionary 정합
> (`tests/validate_field_dictionary.py`)은 Jenkins 수집 Job 의 단계가 아니다 (2026-10-03 부터 후자도). 커밋 전
> `bash scripts/ai/ci_gate.sh` 가 둘 다 돌린다 (main 전용 CI 는 `Jenkinsfile_ci` 로 분리 예정 — Phase 6).

### 시간 예산 (2026-10-03)

| 상수 | 값 | 뜻 |
|---|---|---|
| 전체 | 150 분 (빌드 시작 기준) | 이 안에 Callback 까지 끝낸다 |
| 마무리 예비 | 990 s = INT→KILL 유예 90 + Layer A 120 + archive/stash 60 + post 마무리 720 | 수집이 끝난 뒤 Callback 종료까지의 실제 경로 합 |
| Gather stage 합산 상한 | 115 분 | agent 대기 · checkout · Add-on 준비 · 수집 · post 를 모두 포함 |
| 수집 예산 | `clamp(300 + host_cap × waves, 600, 5400)` 과 위 두 잔여 중 **최소** — `ansible-playbook` 직전에 다시 계산 | host_cap: os/esxi 240 s, redfish 후보 수 × (540 + 65)(+복구 240); forks: os `min(H,50)`(Runner 노드 env `SE_FORKS_CAP_OS` 로 상향 — WSL 실측 슬롯당 ≈36 MB), esxi `min(H,2×vCPU)`, redfish `min(H,4×vCPU)` |
| 최소 시작 | 120 s | 그보다 적게 남으면 수집을 시작하지 않고(`not_started_budget`) 마무리로 넘어간다 |
| 검증용 강제값 | `gatherBudgetForceSec` | 공식 대신 쓰되 전체·stage 잔여는 넘지 못한다 |

예산 로그는 콘솔의 `[Budget] est=…`(node 진입) 와 `[Budget] exec=…`(ansible 직전) 두 줄이다. 공식은 `scripts/gather_budget.sh` 가 정본이고
`tests/unit/test_gather_budget.py` 가 고정한다. host 안에서는 Ansible task `timeout`(Linux 120 s · Windows 180 s · ESXi 180 s ·
Redfish detect 120/collect 600/account 240 s, 모듈 `deadline` 은 그보다 짧게)이 hang 한 태스크 하나를 끊는다 — 이것은 개별 hang 격리이지
host 상한이 아니다.

## 2. Jenkins 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|------|------|
| `loc` | string | 필수 | Location — `common/vars/locations.yml` 의 키 (ic / chj / yi / git) |
| `target_type` | choice | 필수 | os / esxi / redfish |
| `inventory_json` | text | 필수 | 호출자가 전달하는 호스트 JSON 배열 (os/esxi: `service_ip`, redfish: `bmc_ip`, fallback: `ip`) |
| `deploymentEnvironmentId` | string | 필수 | 포털 개발환경 ID |
| `eventUuid` | string | 선택 | 포털 이벤트 UUID (Callback 본문에 그대로) |
| `callbackUrl` | string | 필수 | 결과 전달 URL — `http(s)://` 로 시작, 따옴표·백틱·역슬래시·공백 불가 |
| `verbosity` | choice | 선택 | Ansible verbosity 0~4 (`ANSIBLE_VERBOSITY`) |
| `redfishAccountDryrun` | boolean | 선택 (기본 false) | **검증용.** true 면 `-e _rf_account_service_dryrun=true` 를 넘겨 Redfish 표준 계정 복구(쓰기)를 시뮬레이션만 한다. 운영 요청은 건드리지 않는다 |
| `gatherBudgetForceSec` | string | 선택 (기본 빈 값) | **검증용.** 정수(초)를 주면 `ansible-playbook` 을 `timeout --signal=INT --kill-after=90 <초>` 로 감싼다(rc 124/137 은 콘솔과 `gather_rc.txt` 에). 빈 값이면 종전과 같이 제한 없음 |

### inventory_json 형식
```jsonc
// os/esxi 는 service_ip, redfish 는 bmc_ip 키를 쓴다. 둘 다 없으면 ip 로 fallback.
[
  { "service_ip": "10.50.11.232" }
]
```

> 포털은 ip만 전달한다. 계정은 vault에서 자동 로딩된다.
> 상세 명세는 [docs/contract/01-input.md](../contract/01-input.md) 참조.

## 3. 환경변수

Jenkinsfile 이 설정한다.

| 변수 | 범위 | 값 |
|------|------|----|
| `INVENTORY_JSON` | 전체 | `${params.inventory_json}` — `inventory.sh` 가 읽는다 |
| `PYTHONDONTWRITEBYTECODE` | 전체 | `1` |
| `REPO_ROOT` | Gather | `${WORKSPACE}` — adapter / vault 로딩 기준 |
| `ANSIBLE_CONFIG` | Gather | `${WORKSPACE}/ansible.cfg` |
| `ANSIBLE_JSON_OUTPUT_FILE` | Gather | `${WORKSPACE}/gather_output.json` — `json_only` 콜백이 envelope 을 쓴다 (flush+fsync) |
| `ANSIBLE_JSON_MANIFEST_FILE` | Gather | `${WORKSPACE}/gather_manifest.json` — 접수 집합. 콜백이 inventory 와 대조해 다르면 stderr 로 알린다 (2026-10-03) |
| `ANSIBLE_JSON_PROGRESS_FILE` | Gather | `${WORKSPACE}/gather_progress.jsonl` — host 전이 이벤트(first_seen · precheck · cred_load · auth_proven · checkpoint · addon_started · addon_done · emitted · lost). Layer A 가 누락 봉투를 채울 때 읽는다 |
| `ANSIBLE_JSON_CHECKPOINT_FILE` | Gather | `${WORKSPACE}/gather_checkpoint.jsonl` — Add-on 직전 조립본(`CHECKPOINT` 태스크) host 당 1줄 |
| `SE_AUTH_EVIDENCE_DIR` / `SE_BUILD_ID` / `SE_EVENT_UUID` | Gather | `${WORKSPACE}/gather_auth_evidence` / `${BUILD_TAG}` / `${params.eventUuid}` — Redfish 모듈이 시도(attempt)마다 남기는 인증 증거 파일(비밀값 없음). task timeout 뒤 rescue 가 현재 시도의 파일만 읽어 401 / 인증 뒤 정지 / 확인 전 정지를 가른다 ([../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md)) |
| `ANSIBLE_VERBOSITY` | Gather | `${params.verbosity}` |
| `ADDON_DIR` | Gather 의 ansible 실행만 | `${WORKSPACE}/addon` — Add-on 을 켜고(아래 전역 변수) 받은 파일이 검사를 통과한 빌드에만 있다 |

노드 쪽 선택 환경변수(`SE_ANSIBLE_VENV`)는 [08-ansible-config.md](08-ansible-config.md) 3절.

### Add-on (고객별 추가 수집) — 전역 환경변수와 Gather 안의 흐름

Jenkins 관리 → System → Global properties → Environment variables. 노드 설정 · Runner 사전 작업은 없다.

| 변수 | 필수 | 기본값 | 의미 |
|---|---|---|---|
| `ADDON_REPO_URL` | 켤 때 필수 | (없음 = 꺼짐) | Add-on 저장소 URL (`https://` · `http://` · `ssh://`) |
| `ADDON_REPO_REF` | 선택 | `main` | 브랜치 · `refs/tags/<태그>` · 40자 커밋 해시 (짧은 해시는 거부) |
| `ADDON_REPO_CREDENTIALS_ID` | 선택 | 없음 (익명) | 비공개 저장소의 Jenkins credential ID — Username with password (사용자 이름 + 토큰) |
| `ADDON_REPO_SSL_VERIFY` | 선택 | `false` | `true` 면 TLS 인증서를 검증. 기본은 검증하지 않아 자체 서명 내부 GitLab 도 Runner 에 CA 설치 없이 된다. 검증 해제는 Add-on 을 받는 git 명령에만 붙는다 (`-c http.sslVerify=false`) — 전역 git 설정 · 메인 체크아웃 · 다른 Job 무관 |

`ADDON_REPO_URL` 이 없으면 Add-on 을 실행하지 않는다. 있으면 Gather 가 빌드마다 다음을 한다.

1. Add-on 저장소의 `ADDON_REPO_REF`(기본 `main`)를 `${WORKSPACE}/addon` 에 받는다 (두 번까지 시도). 콘솔
   `[addon] <URL>@<ref> <커밋>`.
2. 받은 파일을 검사한다 — 설정 파일(`config/`)의 형식, 태스크 YAML 문법 등. 설정 작성 오류는 여기서 한 번에 막혀
   서버마다 반복되지 않는다. 콘솔 `[addon] 검사 통과: linux, windows` 또는 `[addon] 검사 실패: <파일>: <이유>`.
3. 검사를 통과하면 그 빌드의 수집에 Add-on 을 넣는다. ESXi · Redfish 빌드는 Add-on 이 할 일이 없어 켜지 않는다
   (콘솔 `[addon] 실행할 기능 없음`, UNSTABLE 아님).
4. 받지 못하거나(URL · ref · 인증 · 인증서 · 저장소 다운) 검사에 실패하면 콘솔에 `[addon] unavailable: <사유>` 를 남기고
   빌드를 UNSTABLE 로 표시한 뒤 Add-on 없이 수집한다. 기본 수집 · 마무리(Callback) 은 정상이고 서버별
   결과(`errors[]`)에 Add-on 오류가 붙지 않는다 — 저장소 문제는 서버 문제가 아니다.

받은 파일은 빌드가 끝나면 작업 공간과 함께 지운다 (빌드마다 새로 받는다).

Add-on 안에서 무엇이 실행되는지(Software 설정 `config/linux/software.yml` · `config/windows/software.yml`, 자동으로
도는 hosts 기능의 DB IP 수집)는 Add-on 저장소 README, hook 계약은 [../develop/07-addon-hook.md](../develop/07-addon-hook.md).

## 4. Ansible 실행 방식

플러그인(`ansiblePlaybook` 스텝)을 쓰지 않는다. `sh` 로 직접 실행한다.

```bash
. "${WORKSPACE}/scripts/activate_ansible_venv.sh" || exit 1
chmod +x <채널>/inventory.sh
VAULT_TMP="$(mktemp)"; trap 'rm -f "$VAULT_TMP"' EXIT
printf '%s' "$VAULT_PASSWORD" > "$VAULT_TMP"; chmod 600 "$VAULT_TMP"
ansible-playbook <채널>/site.yml -i <채널>/inventory.sh --vault-password-file="$VAULT_TMP" -e se_location=<loc>
```

`VAULT_PASSWORD` 는 Jenkins credential `server-gather-vault-password`(Secret text)를 `withCredentials` 로 주입한 값이다
(콘솔 마스킹). 등록 절차는 [01-jenkins-master.md](01-jenkins-master.md) 7절.

### 채널별 실행 경로

| target_type | playbook | inventory |
|-------------|----------|-----------|
| redfish | `redfish-gather/site.yml` | `redfish-gather/inventory.sh` |
| os | `os-gather/site.yml` | `os-gather/inventory.sh` |
| esxi | `esxi-gather/site.yml` | `esxi-gather/inventory.sh` |

## 5. Jenkins 플러그인 요구사항

| 플러그인 | 필수 | 용도 |
|---------|------|------|
| Pipeline | 필수 | Declarative Pipeline |
| Pipeline Utility Steps | 필수 | `readYaml` (Resolve Location) |
| Credentials Binding | 필수 | `withCredentials` — vault 비밀번호 |
| HTTP Request | 필수 | `httpRequest` (Callback) |
| Git | 필수 | SCM checkout (Agent 에 CLI `git` 필요) |
| Ansible | 선택 | `ansiblePlaybook` 스텝을 쓰는 다른 파이프라인용 — 이 파이프라인은 쓰지 않는다 |

## 6. Credentials

| ID | 타입 | 용도 |
|----|------|------|
| `server-gather-vault-password` | Secret text | Ansible vault 복호화 (Gather) |
| 저장소 읽기 credential | Username/password 또는 token | Pipeline SCM checkout |

## 7. Jenkins Agent 요구사항

> Python / Java / Ansible / 패키지 버전 요건은 `REQUIREMENTS.md` 4절 참조.
> 설치 절차는 [02-agent-node.md](02-agent-node.md).

| 항목 | 요구사항 |
|------|---------|
| Label | `common/vars/locations.yml` 의 `agent_label` (ic / chj / yi / git) + 수집할 target_type 의 능력 라벨 (`os` 는 `linux` 와 `windows`, `esxi` 는 `esxi`, `redfish` 는 `redfish`) — [02-agent-node.md](02-agent-node.md) 8절 |
| venv | `/app/ansible-env` 또는 `/opt/ansible-env`, 아니면 노드 환경변수 `SE_ANSIBLE_VENV` |
| CLI `git` | Gather 의 체크아웃, Add-on 체크아웃(`scripts/addon_checkout.sh`)에 필요 |
| Add-on 저장소 접근 | 전역 `ADDON_REPO_URL` 을 켠 경우 Agent 에서 그 URL 에 닿아야 한다 (자체 서명 인증서는 기본값으로 통과 — CA 설치 불필요) |
| 네트워크 | 대상 서버 (SSH 22 / WinRM 5985·5986 / BMC 443) 접근 가능 |
| 디스크 | workspace + ansible 로그 공간 (빌드마다 `clovirone-server-gather-<번호>` 작업 공간을 만들고 끝나면 지운다) |

## 8. 결과 전달

- Gather 가 만든 `gather_output.json` 은 host 마다 envelope 한 줄(JSON Lines)이다. 파이프라인 `post { always }` 의 마무리 단계
  (컨트롤러)가 `unstash`(없으면 같은 빌드의 artifact 를 `unarchive`) 해서 `{loc, deploymentEnvironmentId, eventUuid, gatherInfoJson:[...]}`
  본문으로 `<callbackUrl>/api/jenkins/gather/<target_type>` 에 POST 한다.
- **요청한 대상 1개 = 결과 1개.** Gather 의 `post{always}` 가 먼저 Layer A(`scripts/finalize_gather_output.py`)로 `gather_final.jsonl` 을 만든다:
  OUTPUT 줄(13 필드 · 접수 IP 검사) → 없는 host 는 `CHECKPOINT` 줄(Add-on 직전 조립본; Add-on 중 끊겼으면 "추가 수집 중 처리가 중단되어 …"
  오류 1건, 아니면 "결과를 내보내는 단계에서 중단" 1건) → 그래도 없는 host 는 진행 기록으로 실패 봉투 합성(precheck 진단 보존 / 인증 뒤
  중단 `GATHER_FAILED` auth true / 연결 끊김 `AUTH_PROBE_FAILED` / 그 밖 `OUTPUT_BUILD_FAILED`). 보고서 `gather_finalize_report.json`
  (accepted · kept · filled · dropped · conflicts). Layer A 가 없거나 실패(exit 3)하면 컨트롤러 Groovy 가 OUTPUT → CHECKPOINT → 합성 봉투의
  최소 경로로 같은 수를 맞춘다 (progress 기반 stage 분류는 하지 않는다 — 보고서에 남는 차이).
- Callback 은 남은 예산 안에서 최대 3회(시도별 10~120 s; 5xx · 408 · 429 · 예외만 재시도, 그 밖 4xx 는 중단; 빌드가 ABORTED 면 1회 60 s).
  2xx 는 HTTP 응답 성공이지 Portal 의 저장 증거가 아니다. 모두 실패하면 UNSTABLE 이고 본문은 `callback_body.json` artifact 로 남는다 —
  수집 자체가 성공했으면 빌드를 FAILURE 로 만들지 않는다. 합성 보충이 1건이라도 있거나 outcome 이 `completed` 가 아니면 UNSTABLE.
- Groovy 최소 경로의 함수(`seReconcileRaw` 등)는 `scripts/jenkins/se_finalize.groovy` 하나가 정본이다 — 마무리 단계가 `readTrusted` 로 읽어 `load` 하고,
  CI Job(`Jenkinsfile_ci`)이 같은 파일로 Python Layer A 와의 동치를 검사한다. 파일을 못 읽으면 보충 없이 있는 OUTPUT 줄만 보내고 UNSTABLE(`layerB=unavailable`)이다.
- envelope 형식은 [../contract/02-output-envelope.md](../contract/02-output-envelope.md), 실패 봉투의 stage/code 는
  [../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md).

---

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| Jenkins Job 등록 | [03-job-registration.md](03-job-registration.md) |
| 호출자 입력 형식 | [../contract/01-input.md](../contract/01-input.md) |
| 실패 처리 정책 | [../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md) |
