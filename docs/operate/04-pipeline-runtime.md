# Jenkins 파이프라인 런타임

> 이 문서는 server-exporter 의 운영 파이프라인 `Jenkinsfile_portal` 이 실제로 어떤 단계로 실행되는지 정리한다.
> 각 단계가 어느 노드에서 도는지, 어디서 실패하면 어떻게 전파되는지, 호출자에게 어떤 형식으로 결과가 돌아가는지를 한 페이지에 모았다.
>
> Jenkinsfile 을 수정해야 한다면 본 문서의 단계 구조와 게이트 정책을 먼저 이해한 뒤 손댄다.

> 검증일: 2026-09-28 (lab Jenkins `clovirone-server-gather`, `production` 브랜치)

## 1. 파이프라인 구조

`Jenkinsfile_portal` 은 최상위 `agent none` 이고 단계마다 노드를 고른다. 컨트롤러(`built-in`)에는 Python 도 Ansible 도 필요 없다.

```text
parameters (loc, target_type, inventory_json, deploymentEnvironmentId, eventUuid, callbackUrl, verbosity)
  → Resolve Location  [컨트롤러]  loc 를 common/vars/locations.yml 로 검증, target_type 능력 라벨과 && 로 이어 노드 라벨식 결정 (맞는 온라인 노드 없으면 즉시 실패)
  → Validate          [Agent]     파라미터 형식 검증 (체크아웃 없음)
  → Gather            [Agent]     (전역 ADDON_REPO_URL 이 있으면 Add-on 체크아웃 · 검사) → ansible-playbook 실행 → gather_output.json → stash
  → Validate Schema   [Agent]     field_dictionary.yml 정합 (FAIL 게이트)
  → Callback          [컨트롤러]  unstash → 호출자에게 POST (실패해도 빌드는 UNSTABLE)
```

| Stage | 노드 | 하는 일 | 실패 시 |
|-------|------|--------|--------|
| Resolve Location | `built-in` | `readYaml common/vars/locations.yml` — 미등록 `loc` 는 노드 대기 없이 즉시 실패 | FAILURE |
| Validate | `agent_label && 능력 라벨` 노드 | `target_type` / `inventory_json` / `callbackUrl` / `deploymentEnvironmentId` 검증 | FAILURE |
| Gather | `agent_label && 능력 라벨` 노드 | (전역 `ADDON_REPO_URL` 이 있으면 Add-on 저장소를 `${WORKSPACE}/addon` 에 받고 검사 — 3절) → venv 활성화 → `ansible-playbook <채널>/site.yml -i <채널>/inventory.sh --vault-password-file=<임시파일> -e se_location=<loc>` | Add-on 을 받지 못하면 UNSTABLE + Add-on 없이 수집, ansible 실패는 UNSTABLE, 결과 파일 0바이트면 FAILURE |
| Validate Schema | `agent_label && 능력 라벨` 노드 | venv 활성화 → `python3 tests/validate_field_dictionary.py` | FAILURE |
| Callback | `built-in` | `httpRequest` POST, 3회 재시도 (10s · 20s backoff) | UNSTABLE (수집 결과는 콘솔에 남는다) |

### Ansible 실행환경(venv) 선택

Gather 와 Validate Schema 는 저장소의 `scripts/activate_ansible_venv.sh` 를 한 줄로 source 한다.

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
> pytest 회귀(`tests/e2e`, `tests/integration -m "not live"`, `tests/regression`)는 Jenkins 단계가 아니다. 예전의
> 비운영 `Jenkinsfile` 이 Stage 4 로 돌리던 것을 2026-09-28 에 파일과 함께 걷어냈다. 커밋 전 로컬에서 돌린다.

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
| `ANSIBLE_JSON_OUTPUT_FILE` | Gather | `${WORKSPACE}/gather_output.json` — `json_only` 콜백이 envelope 을 쓴다 |
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
   빌드를 UNSTABLE 로 표시한 뒤 Add-on 없이 수집한다. 기본 수집 · Validate Schema · Callback 은 정상이고 서버별
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
| CLI `git` | Gather · Validate Schema 의 체크아웃, Add-on 체크아웃(`scripts/addon_checkout.sh`)에 필요 |
| Add-on 저장소 접근 | 전역 `ADDON_REPO_URL` 을 켠 경우 Agent 에서 그 URL 에 닿아야 한다 (자체 서명 인증서는 기본값으로 통과 — CA 설치 불필요) |
| 네트워크 | 대상 서버 (SSH 22 / WinRM 5985·5986 / BMC 443) 접근 가능 |
| 디스크 | workspace + ansible 로그 공간 (빌드마다 `clovirone-server-gather-<번호>` 작업 공간을 만들고 끝나면 지운다) |

## 8. 결과 전달

- Gather 가 만든 `gather_output.json` 은 host 마다 envelope 한 줄(JSON Lines)이다. 컨트롤러가 `unstash` 해서
  `{loc, deploymentEnvironmentId, eventUuid, gatherInfoJson:[...]}` 본문으로 `<callbackUrl>/api/jenkins/gather/<target_type>` 에 POST 한다.
- Callback 이 3회 모두 실패하면 빌드는 UNSTABLE 이고 envelope 은 콘솔 로그에 남는다 — 수집 자체는 성공했으므로 빌드를 FAILURE 로 만들지 않는다.
- envelope 형식은 [../contract/02-output-envelope.md](../contract/02-output-envelope.md).

---

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| Jenkins Job 등록 | [03-job-registration.md](03-job-registration.md) |
| 호출자 입력 형식 | [../contract/01-input.md](../contract/01-input.md) |
| 실패 처리 정책 | [../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md) |
