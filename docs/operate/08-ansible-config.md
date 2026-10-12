# Ansible 프로젝트 설정

이 문서는 이 저장소가 쓰는 Ansible 설정(`ansible.cfg`), 플러그인 경로, 수집 실행이 읽는 환경변수, vault 비밀번호 전달 방식, Jenkins 밖에서 직접 실행하는 방법을 설명합니다.
Runner 자체의 설치는 [02-agent-node.md](02-agent-node.md), 환경 요건은 [../../REQUIREMENTS.md](../../REQUIREMENTS.md)에 있습니다.

## 1. 프로젝트 `ansible.cfg`

저장소 루트의 `ansible.cfg`가 정본입니다. Ansible은 설정 파일을 병합하지 않고 하나만 읽으며, 수집 실행은 `ANSIBLE_CONFIG`로 이 파일을 지정합니다. 그래서 Runner의 `/etc/ansible/ansible.cfg`는 수집에 적용되지 않습니다.

핵심 항목입니다. 전체는 파일을 직접 보세요.

```ini
[defaults]
lookup_plugins   = ./lookup_plugins          ; adapter_loader
filter_plugins   = ./filter_plugins          ; 정규화 필터
callback_plugins = ./callback_plugins        ; json_only
library          = ./common/library:./redfish-gather/library
module_utils     = ./module_utils            ; adapter_common
stdout_callback  = json_only
callbacks_enabled = json_only
gathering        = explicit                  ; gather_facts 는 playbook 이 명시적으로 호출
jinja2_native    = True                      ; JSON 출력에서 int, bool 유지
host_key_checking = False
interpreter_python = auto
forks            = 50
timeout          = 60
gather_timeout   = 60
```

`[ssh_connection]`(pipelining), `[winrm]`(`transport = ntlm`), `[inventory]`(스크립트 인벤토리 사용) 섹션도 있습니다. fact 캐시는 쓰지 않으므로 Redis 같은 캐시 서버는 필요 없습니다.

`forks`는 Ansible의 동시 실행 상한입니다. 실제 동시 실행 수는 `scripts/gather_state.py`가 채널과 대상 수로 정해 `ansible-playbook -f`로 넘깁니다(OS는 최대 50 또는 노드 환경변수 `SE_FORKS_CAP_OS`, ESXi는 vCPU의 2배, Redfish는 vCPU의 4배).

## 2. 플러그인 경로

| 종류 | 경로 | 파일 |
|---|---|---|
| lookup | `lookup_plugins/` | `adapter_loader.py` (어댑터 선택) |
| filter | `filter_plugins/` | 진단, 식별자, 단위, 오류 문장 정규화 필터 |
| callback | `callback_plugins/` | `json_only.py` (결과 봉투 출력과 진행 기록) |
| library | `common/library/`, `redfish-gather/library/` | `precheck_bundle.py` (사전 진단), `redfish_gather.py` (Redfish 수집) |
| module_utils | `module_utils/` | `adapter_common.py` (어댑터 매칭과 점수) |

`ansible.cfg` 없이 실행하면 이 경로들이 인식되지 않습니다. 저장소 루트에서 실행하거나 `ANSIBLE_CONFIG`로 지정하세요.

## 3. 환경변수

수집 실행이 읽는 변수입니다. Jenkins에서는 `Jenkinsfile_portal`이 설정하고([04-pipeline-runtime.md](04-pipeline-runtime.md) 2절), 직접 실행할 때는 사람이 설정합니다.

| 변수 | 필수 | 뜻 | Jenkins에서 |
|---|---|---|---|
| `REPO_ROOT` | 필수 | 저장소 루트. 공통 task, 어댑터, vault 경로의 기준 | `${WORKSPACE}` |
| `ANSIBLE_CONFIG` | 권장 | `ansible.cfg` 경로 | `${WORKSPACE}/ansible.cfg` |
| `INVENTORY_JSON_FILE` | 셋 중 하나 | 대상 목록 JSON 파일. `inventory.sh`가 가장 먼저 읽습니다 | `${WORKSPACE}/.inventory_input.json` |
| `INVENTORY_JSON` 또는 `inventory_json` | 셋 중 하나 | 대상 목록 JSON 문자열. 작은 입력의 편의 경로 | 쓰지 않음 |
| `$WORKSPACE/.inventory_input.json` 파일 | 셋 중 하나 | 변수가 없을 때 찾는 파일 | |
| `ANSIBLE_JSON_OUTPUT_FILE` | 선택 | 결과 봉투를 한 줄씩 쓸 파일. 없으면 stdout만 | `${WORKSPACE}/gather_output.json` |
| `ANSIBLE_JSON_PROGRESS_FILE`, `ANSIBLE_JSON_CHECKPOINT_FILE`, `ANSIBLE_JSON_MANIFEST_FILE` | 선택 | 진행 기록, Add-on 직전 조립본, 접수 목록 | 작업 폴더의 파일 |
| `SE_AUTH_EVIDENCE_DIR` | 선택 | Redfish 인증 증거 파일 폴더 | `${WORKSPACE}/gather_auth_evidence` |
| `ADDON_DIR` | 선택 | 추가 수집(Add-on) 디렉터리 절대 경로. 없으면 Add-on을 실행하지 않습니다. 있는데 `<경로>/tasks/main.yml`이 없으면 `errors[]`에 `section: addon` 1건을 남깁니다 | 검사를 통과한 빌드의 ansible 실행에만 `${WORKSPACE}/addon` |
| `SE_ANSIBLE_VENV` | 선택 | Ansible 실행환경(venv) 루트. `scripts/activate_ansible_venv.sh`가 읽습니다 | Runner 노드 환경변수 |

`se_location`은 환경변수가 아니라 playbook 변수입니다. `-e se_location=<loc>`로 넘기며, `common/vars/locations.yml`에 없는 값이면 세 채널 모두 대상이 자격증명 단계 실패 결과로 끝납니다.

## 4. vault 비밀번호

Jenkins에서는 credential `server-gather-vault-password`(Secret text)를 `withCredentials`로 주입하고, `scripts/run_gather.sh`가 임시 파일(권한 600)에 써서 `--vault-password-file`로 넘긴 뒤 실행이 끝나면 지웁니다. `ansible.cfg`에는 vault 비밀번호 파일 설정이 없습니다.

직접 실행할 때는 비밀번호 파일을 만들어 넘기세요. 파일은 저장소 밖에 두고 권한을 600으로 하세요.

## 5. Jenkins 밖에서 직접 실행

Runner와 같은 환경(venv, 대상으로 가는 통신 경로)이 있는 Linux에서 실행합니다.

```bash
# 저장소 루트, Runner 와 같은 계정
export REPO_ROOT="$(pwd)"
export ANSIBLE_CONFIG="$REPO_ROOT/ansible.cfg"
export INVENTORY_JSON='[{"service_ip":"192.0.2.10"}]'      # redfish 는 bmc_ip
. scripts/activate_ansible_venv.sh

ansible-playbook os-gather/site.yml      -i os-gather/inventory.sh      --vault-password-file <비밀번호 파일> -e se_location=<loc>
ansible-playbook esxi-gather/site.yml    -i esxi-gather/inventory.sh    --vault-password-file <비밀번호 파일> -e se_location=<loc>
ansible-playbook redfish-gather/site.yml -i redfish-gather/inventory.sh --vault-password-file <비밀번호 파일> -e se_location=<loc>
```

결과 봉투는 stdout에 서버마다 한 줄씩 나옵니다. `ANSIBLE_JSON_OUTPUT_FILE`을 설정하면 파일에도 씁니다. Jenkins의 수집 실행 한계와 재개는 `scripts/run_gather.sh`와 `scripts/gather_state.py`가 맡으므로, 직접 실행에서는 적용되지 않습니다. 같은 동작이 필요하면 `scripts/run_gather.sh`를 Jenkins와 같은 인자로 실행하세요.

```bash
# 인자: <playbook> <inventory> <loc> <Add-on 검사 통과 여부 true|false> <수집 실행 한계 초> [이전 시도 중 Runner 끊김 true|false]
VAULT_PASSWORD='<값>' WORKSPACE="$REPO_ROOT" bash scripts/run_gather.sh redfish-gather/site.yml redfish-gather/inventory.sh <loc> false 21600
```

위 명령의 비밀번호는 셸 기록에 남을 수 있습니다. 운영에서는 Jenkins 경로를 쓰세요.

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| Runner 설치 | [02-agent-node.md](02-agent-node.md) |
| 환경 요건 | [../../REQUIREMENTS.md](../../REQUIREMENTS.md) |
| vault 구조와 편집 | [05-vault.md](05-vault.md) |
| 파이프라인이 주는 환경변수 전체 | [04-pipeline-runtime.md](04-pipeline-runtime.md) |
