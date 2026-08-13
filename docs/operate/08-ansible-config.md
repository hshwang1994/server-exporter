# Ansible 프로젝트 설정

> **이 문서는** server-exporter 저장소가 사용하는 Ansible 의 프로젝트 고유 설정을 정리한다.
> ansible.cfg 의 의미, 커스텀 플러그인 경로, 환경변수, vault 사용 방법, 로컬 실행 예시 등을 다룬다.
>
> Agent 노드 자체의 설치 / 컬렉션 / Python 패키지 절차는 본 문서가 아니라 `docs/operate/02-agent-node.md` 5절을 참고한다.
> 버전 요건은 `REQUIREMENTS.md` 4절.

---

## 1. 프로젝트 ansible.cfg

프로젝트 루트의 `ansible.cfg` 설정:

```ini
[defaults]
lookup_plugins  = ./lookup_plugins         # adapter_loader
filter_plugins  = ./filter_plugins         # diagnosis_mapper, jedec_mapper
callback_plugins = ./callback_plugins       # json_only (단일 사본)
library         = ./common/library:./redfish-gather/library
module_utils    = ./module_utils           # adapter_common
stdout_callback = json_only
callbacks_enabled = json_only
gathering = explicit                        # gather_facts: no
jinja2_native = True                        # JSON 출력 타입 보존 (int/bool 유지)
host_key_checking = False
interpreter_python = auto
forks = 200
timeout = 60
gather_timeout = 60
```

> 위 블록은 핵심 발췌다. 실제 `ansible.cfg` 에는 `[ssh_connection]`(pipelining + 레거시 `ssh_args`), `[winrm]`(`transport = ntlm`), `[inventory]` 섹션도 있다. 전체는 `ansible.cfg` 를 직접 본다.
> 이 ansible.cfg는 CWD 우선순위로 `/etc/ansible/ansible.cfg`(시스템 설정)보다 우선 적용된다.

---

## 2. 커스텀 플러그인 경로

| 플러그인 타입 | 경로 | 파일 |
|-------------|------|------|
| lookup | `./lookup_plugins/` | `adapter_loader.py` |
| filter | `./filter_plugins/` | `diagnosis_mapper.py`, `jedec_mapper.py` |
| callback | `./callback_plugins/` | `json_only.py` |
| library | `./common/library/`, `./redfish-gather/library/` | `precheck_bundle.py`, `redfish_gather.py` |
| module_utils | `./module_utils/` | `adapter_common.py` |

### 플러그인 발견 경로 우선순위

1. `ansible.cfg`의 설정값
2. 환경변수 (`ANSIBLE_LOOKUP_PLUGINS` 등)
3. Playbook 인접 디렉토리 (각 채널의 `library/`, `callback_plugins/`)
4. `~/.ansible/plugins/`

> **주의**: `ansible.cfg` 없이 실행하면 채널별 `library/` (예: `redfish-gather/library/`)는 인식 안됨. `ansible.cfg` 필수.

---

## 3. 환경변수

| 변수 | 필수 | 설명 | 설정 위치 |
|------|------|------|----------|
| `REPO_ROOT` | 필수 | 프로젝트 루트 경로 (adapter/vault 로딩) | Jenkinsfile: `${WORKSPACE}` |
| `INVENTORY_JSON` | 필수 | 호출자가 전달하는 호스트 배열 JSON (os/esxi: `service_ip`, redfish: `bmc_ip`, fallback: `ip`) | Jenkinsfile: `${params.inventory_json}` |
| `ANSIBLE_CONFIG` | 권장 | ansible.cfg 경로 (미설정 시 CWD 기준) | Jenkins workspace 루트 |

---

## 4. Vault 설정

```bash
# vault 비밀번호 파일 방식
ansible-playbook --vault-password-file .vault_pass site.yml

# 환경변수 방식
export ANSIBLE_VAULT_PASSWORD_FILE=.vault_pass

# Jenkins credentials binding 방식 (권장)
withCredentials([file(credentialsId: 'vault-pass', variable: 'VAULT_PASS')]) {
    sh "ansible-playbook --vault-password-file ${VAULT_PASS} site.yml"
}
```

---

## 5. 실행 명령 예시

```bash
# Redfish gather
cd ${REPO_ROOT}
export REPO_ROOT=$(pwd)
export INVENTORY_JSON='[{"ip":"10.50.11.232"}]'
ansible-playbook redfish-gather/site.yml -i redfish-gather/inventory.sh

# OS gather
ansible-playbook os-gather/site.yml -i os-gather/inventory.sh

# ESXi gather
ansible-playbook esxi-gather/site.yml -i esxi-gather/inventory.sh
```

---

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| Agent 노드 자체 설치 | [02-agent-node.md](02-agent-node.md) |
| 환경 요건 | [REQUIREMENTS.md](../REQUIREMENTS.md) |
| Vault 운영 | [05-vault.md](05-vault.md) |
