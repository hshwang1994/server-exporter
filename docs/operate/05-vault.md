# 자격증명(Vault) 관리

이 문서는 수집이 대상 서버(SSH, WinRM, vSphere, Redfish)에 접속할 때 쓰는 계정을 어디에 어떻게 두는지, 어떻게 고치고 확인하는지, 비밀번호를 바꿀 때 무엇을 해야 하는지 설명합니다.
계정은 저장소 안의 `vault/` 디렉터리에 ansible-vault로 암호화해 두고, 복호화 비밀번호(마스터 비밀번호)는 Jenkins credential `server-gather-vault-password`(Secret text)에만 둡니다.

## 1. 바뀐 값은 다음 실행부터 적용됩니다

수집은 실행할 때마다 vault 파일을 디스크에서 읽어 복호화합니다. 결과를 fact 캐시나 다른 곳에 저장하지 않으므로, 파일을 고쳐 commit하고 Job이 그 커밋을 받으면 다음 빌드부터 새 값이 쓰입니다. 재기동이나 캐시 삭제는 필요 없습니다.

이미 시작한 빌드는 시작할 때 읽은 값으로 끝까지 갑니다. 값을 바꾸는 작업은 진행 중인 빌드가 없을 때 하세요.

## 2. 파일 배치

수집은 요청의 `loc`(실행 위치)과 대상 종류로 파일 하나를 정해 엽니다. 다른 위치나 다른 벤더의 파일로 넘어가는 경로는 없습니다.

| 채널 | 파일 | 결정 기준 |
|---|---|---|
| Linux | `vault/<loc>/os/linux.yml` | 위치 + OS 종류 |
| Windows | `vault/<loc>/os/windows.yml` | 위치 + OS 종류 |
| ESXi | `vault/<loc>/esxi.yml` | 위치 |
| Redfish 표준 수집 계정 | `vault/common/redfish/standard.yml` | 없음. 모든 위치와 벤더에 공통인 파일 하나 |
| Redfish 복구 계정 | `vault/<loc>/redfish/<vendor>.yml` | 위치 + 벤더 |

- `<loc>`은 `common/vars/locations.yml`에 등록된 ID만 쓸 수 있습니다. 등록되지 않은 값이면 파일을 열지 않고 대상이 자격증명 단계 실패(`failure_code: CREDENTIAL_SET_UNAVAILABLE`)로 끝납니다.
- `<vendor>`는 `common/vars/vendor_aliases.yml`의 대표 이름(`dell`, `hpe`, `lenovo`, `supermicro`, `cisco`, `huawei`, `inspur`, `fujitsu`, `quanta`)입니다.
- Redfish는 계정이 둘입니다. 수집은 언제나 표준 계정으로 합니다. 복구 계정은 표준 계정이 BMC에서 거부됐을 때 표준 계정을 만들거나 비밀번호를 맞추는 데만 쓰고, 복구 계정으로 수집한 결과가 정상 결과로 나가는 경로는 없습니다. 벤더를 식별하지 못한 대상은 표준 계정 인증만 시도합니다.
- `vault/.lab-credentials.yml`은 평문 참고 파일이며 `.gitignore`에 있어 commit되지 않고 수집도 읽지 않습니다.

### 위치 추가

1. `common/vars/locations.yml`에 `<loc>: { agent_label: <라벨> }`을 추가합니다. ID는 `[a-z0-9_-]+`만 허용됩니다.
2. `vault/<loc>/os/linux.yml`, `os/windows.yml`, `esxi.yml`, `redfish/<vendor>.yml`(필요한 벤더)을 만들어 암호화합니다(4절).
3. Jenkins에 그 라벨과 수집할 대상 종류의 능력 라벨을 가진 Runner를 등록합니다([02-agent-node.md](02-agent-node.md) 8절).

코드는 바꾸지 않습니다.

## 3. 파일 내용

세 채널 모두 같은 형식입니다. `accounts` 배열의 순서가 인증 시도 순서이고, 코드는 순서를 바꾸지 않습니다.

```yaml
# vault/<loc>/os/linux.yml 예시 (암호화 전)
accounts:
  - username: "<계정>"
    password: "<비밀번호>"
    label: "primary"          # 사람이 읽는 이름. 콘솔 요약과 진단에만 나옵니다
    role: "primary"
  - username: "<보조 계정>"
    password: "<비밀번호>"
    label: "fallback"
    role: "recovery"
sudo_passwords:                              # Linux만, 선택. sudo 가 비밀번호를 요구하는 서버용 후보 — 순서가 시도 순서입니다
  - label: "sudo_primary"
    role: "primary"
    password: "<sudo 비밀번호>"
  - label: "sudo_fallback1"
    role: "secondary"
    password: "<이전 sudo 비밀번호>"
ansible_become_password: "<sudo 비밀번호>"   # Linux만, 선택. 옛 형식 — sudo_passwords 가 없을 때 후보 1개로 읽습니다
```

| 키 | 필수 | 뜻 |
|---|---|---|
| `accounts[].username`, `accounts[].password` | 필수 | 로그인 계정 |
| `accounts[].label` | 권장 | 사람이 구분하는 이름. 콘솔 요약에 label만 나오고 비밀번호는 나오지 않습니다 |
| `accounts[].role` | Redfish는 필수 | `primary` 또는 `recovery`. OS와 ESXi는 순서대로 시도할 뿐 role을 쓰지 않습니다 |
| `sudo_passwords[]` | 선택 (Linux) | sudo 가 비밀번호를 요구하는 서버의 후보 목록. `password` 필수, `label`/`role`(`primary`/`secondary`) 권장. 2026-10-13 신설 |
| `ansible_become_password` | 선택 (Linux) | 옛 형식. `sudo_passwords` 가 없을 때만 후보 1개로 읽습니다 |

Linux 의 sudo 는 이렇게 시도합니다(`os-gather/tasks/linux/try_sudo.yml`). root 로그인이면 건너뛰고, 먼저 NOPASSWD 인지 확인합니다(비밀번호를 보내지 않습니다).
비밀번호가 필요하면 **로그인 비밀번호 → `sudo_passwords` 순서** 로 보냅니다. 표준 sudoers 는 호출 계정 자신의 비밀번호를 묻기 때문에 로그인 비밀번호가 먼저이고,
`sudo_passwords` 는 root 비밀번호를 묻는 서버(`Defaults targetpw`/`rootpw`)나 다른 값을 쓰는 서버를 위한 것입니다. 같은 값은 한 번만 보냅니다.
sudoers 에 없는 계정(정책 거부)이나 sudo 를 쓸 수 없는 서버는 첫 관측에서 멈추고, 비밀번호 거부는 대상의 잠금 정책(`faillock.conf`·`pam.d` 의 `deny`,
`even_deny_root`)으로 계산한 예산 안에서만 이어집니다 — 한 번의 수집으로 계정이 잠기지 않게 하기 위해서입니다. 결과는 봉투의 `diagnosis.details.sudo` 에
비밀번호 없이 남습니다. Serial Number 를 얻지 못한 서버는 `status: failed` 입니다([../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md)).
후보 수는 위치마다 1~2개를 권장합니다 — 값이 틀릴수록 잠금 횟수만 늘어납니다.

Redfish 파일의 규칙입니다.

- `vault/common/redfish/standard.yml`에서는 `role: primary`인 항목만 표준 계정 후보가 됩니다. 다른 role은 버립니다.
- `vault/<loc>/redfish/<vendor>.yml`에서는 `role: primary`인 항목을 버리고 나머지가 복구 후보가 됩니다. 복구 파일에 표준 계정을 넣어도 표준 계정 대용으로 쓰이지 않습니다.
- 표준 계정을 만들거나 복구할 때 쓰는 사용자 이름, 비밀번호, 권한(Administrator)은 표준 파일의 `primary` 항목에서 가져옵니다.
- 복구 계정 label은 `<vendor>_factory`(공장 기본 계정), `<vendor>_current`(사이트 운영 계정), `<vendor>_fallback`(이전 계정) 같은 이름을 씁니다. 값은 vault 안에만 두고 문서에 적지 않습니다.

`accounts` 없이 `ansible_user`, `ansible_password`만 있는 옛 형식도 읽힙니다. 그 경우 `label: legacy_single`, `role: primary`인 계정 하나로 취급합니다.

## 4. 편집과 암호화

작업 PC나 Runner처럼 ansible-vault가 있는 곳에서 저장소를 checkout해 작업합니다. 마스터 비밀번호 파일은 저장소 밖에 권한 600으로 두세요. 저장소 루트의 `.vault_pass`는 `.gitignore`에 있어 commit되지 않지만, 작업이 끝나면 지우는 편이 안전합니다.

```bash
# 저장소 루트. <비밀번호 파일>은 마스터 비밀번호가 든 권한 600 파일
ansible-vault edit   --vault-password-file <비밀번호 파일> vault/<loc>/os/linux.yml      # 있는 파일 수정
ansible-vault create --vault-password-file <비밀번호 파일> vault/<loc>/redfish/<vendor>.yml   # 새 파일
ansible-vault view   --vault-password-file <비밀번호 파일> vault/common/redfish/standard.yml   # 내용 확인 (화면에 비밀번호가 나옵니다)
```

WSL에서 Windows 드라이브의 비밀번호 파일을 쓰면 실행 비트가 붙어 ansible-vault가 그 파일을 스크립트로 실행하려다 실패합니다(`Exec format error`). 비밀번호 파일은 WSL 쪽 경로에 두세요.

평문으로 처음 만든 파일을 한 번에 암호화할 때는 `scripts/bootstrap_vault_encrypt.sh`를 씁니다. 저장소 루트의 `.vault_pass`를 읽어 `vault/` 아래 아직 암호화되지 않은 `*.yml`을 암호화하고, 이미 암호화된 파일은 건너뜁니다.

```bash
# 저장소 루트
echo -n '<마스터 비밀번호>' > .vault_pass && chmod 600 .vault_pass
bash scripts/bootstrap_vault_encrypt.sh
rm .vault_pass
```

편집한 뒤 commit하기 전에 확인합니다.

```bash
# 암호화됐는지 (첫 줄이 $ANSIBLE_VAULT 로 시작)
head -c 14 vault/<loc>/os/linux.yml; echo
# 복호화되고 구조가 맞는지 — label 과 role 만 출력하고 비밀번호는 출력하지 않습니다
ansible-vault view --vault-password-file <비밀번호 파일> vault/<loc>/os/linux.yml \
  | python3 -c 'import sys,yaml; d=yaml.safe_load(sys.stdin) or {}; print([(a.get("label"), a.get("role")) for a in d.get("accounts", [])])'
```

편집기가 남긴 `.swp` 같은 임시 파일을 commit하지 마세요.

## 5. 반영 확인

값을 바꾼 위치와 채널마다 대상 한 대로 수집을 한 번 실행합니다.

- 결과 봉투의 `diagnosis.details.credential_scope`가 기대한 파일과 맞는지 봅니다. OS는 `<loc>/os/linux` 같은 값, Redfish 표준 계정은 `common/redfish/standard`, Redfish 복구 범위는 `diagnosis.details.recovery_credential_scope`입니다.
- 콘솔의 `credential_scope=... outcome=loaded accounts=N labels=[...]` 줄에서 파일을 열었고 계정 수가 맞는지 봅니다. `outcome`이 `credential_set_missing`이면 파일이 없고, `credential_set_undecryptable`이면 마스터 비밀번호가 맞지 않습니다.
- 인증에 실패한 대상은 `failure_stage: auth`로 끝납니다. 어느 단계에서 막혔는지는 [../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md)를 보세요.

## 6. Redfish 표준 계정 복구

표준 계정 인증이 실패하면 코드가 다음 조건을 모두 만족할 때만 복구 계정으로 AccountService에 접근합니다.

1. 표준 계정으로 수집이 실패했습니다.
2. 표준 계정이 HTTP 401로 명시적으로 거부됐습니다. 403, timeout, TLS 오류, 5xx는 해당하지 않습니다.
3. 그 위치와 벤더의 복구 계정이 한 개 이상 있습니다.

조건이 맞으면 복구 계정을 파일 순서대로 시도해 BMC 계정 목록을 읽고, 표준 계정이 없으면 만들고 있으면 비밀번호를 표준 파일 값으로 맞춥니다. 계정 목록을 끝까지 읽지 못하면 쓰지 않습니다. 쓰기 뒤에는 표준 계정으로 다시 인증해 수집해야 성공이고, 결과는 `diagnosis.details.account_service`에 비밀번호 없이 남습니다. 조건이 맞지 않으면 시뮬레이션(dryrun)으로만 돌고 BMC를 바꾸지 않습니다.

복구 계정이 없는데 표준 계정이 거부되면 `errors[]`에 `section: account_service` 항목이 남습니다. 이때 할 일은 그 위치와 벤더의 복구 파일을 두는 것이고, 복구 계정은 있는데 표준 계정이 계속 거부되면 표준 파일의 비밀번호를 BMC와 맞추는 것입니다.

실장비에서 계정 쓰기까지 검증한 기록은 없습니다. 쓰기 경로는 단위 시험과 모의 BMC로만 확인했습니다. 새 사이트에 처음 적용할 때는 수집 명령에 `-e _rf_account_service_dryrun=true`를 붙여 시뮬레이션 결과를 먼저 보는 방법이 있습니다. Jenkins Job은 이 변수를 넘기지 않으므로 직접 실행([08-ansible-config.md](08-ansible-config.md) 5절)에서만 쓸 수 있습니다.

## 7. 비밀번호 변경

### 마스터 비밀번호(ansible-vault 비밀번호) 변경

모든 vault 파일을 새 비밀번호로 다시 암호화하고 Jenkins credential을 바꿉니다. 두 작업 사이에 실행된 빌드는 복호화에 실패하므로 빌드가 없는 시간에 합니다.

```bash
# 저장소 루트. <현재 파일>, <새 파일> 은 각각 현재 · 새 마스터 비밀번호가 든 권한 600 파일
find vault -type f -name '*.yml' ! -name '.*' -print0 \
  | xargs -0 ansible-vault rekey --vault-password-file <현재 파일> --new-vault-password-file <새 파일>
git add vault && git commit -m "chore: vault 마스터 비밀번호 교체"
```

그다음 Jenkins의 Manage Jenkins → Credentials에서 `server-gather-vault-password`의 Secret을 새 값으로 바꾸고, 커밋이 운영 브랜치에 반영된 뒤 수집을 한 번 실행해 `outcome=loaded`를 확인합니다. 사내처럼 `production` 브랜치를 쓰는 환경은 [09-production-branch.md](09-production-branch.md) 절차로 반영합니다.

### 계정 비밀번호 변경

대상 서버나 BMC에서 비밀번호를 바꾼 뒤 해당 파일만 `ansible-vault edit`로 고칩니다. Redfish 표준 계정은 `vault/common/redfish/standard.yml` 한 곳입니다. 바꾸는 동안 표준 계정이 BMC와 어긋나면 6절의 복구가 동작할 수 있으므로, BMC 쪽과 vault 쪽을 같은 작업 시간에 맞추세요.

변경 기록은 날짜와 대상 파일만 남기고 비밀번호는 어디에도 적지 않습니다.

## 8. 자주 막히는 곳

| 증상 | 원인과 조치 |
|---|---|
| 콘솔에 `outcome=credential_set_undecryptable` | Jenkins credential의 값과 파일을 암호화한 마스터 비밀번호가 다릅니다. credential 값을 확인하세요 |
| 콘솔에 `outcome=credential_set_missing` | 그 위치, 채널의 파일이 없습니다. 2절 표의 경로에 파일을 추가하세요 |
| 콘솔에 `outcome=empty_accounts` | 파일은 열렸는데 `accounts`가 비었거나 Redfish 파일에서 role이 맞는 항목이 없습니다 |
| Jenkins 콘솔에 `Could not find credentials entry` | credential ID `server-gather-vault-password`가 Jenkins에 없습니다([03-job-registration.md](03-job-registration.md) 1절) |
| `ansible-vault edit`에서 `Decryption failed` | 비밀번호 파일의 값이 다르거나 파일이 다른 비밀번호로 암호화돼 있습니다 |
| 요청한 `loc`이 등록되지 않음 | Jenkins의 실행 위치 확인 단계에서 빌드가 바로 실패합니다. `common/vars/locations.yml`에 추가하세요 |

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| Jenkins credential 등록 | [03-job-registration.md](03-job-registration.md) |
| Runner 라벨과 위치 | [02-agent-node.md](02-agent-node.md) |
| 인증 실패 진단 | [../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md) |
| 새 벤더 추가 | [../develop/04-add-vendor.md](../develop/04-add-vendor.md) |
