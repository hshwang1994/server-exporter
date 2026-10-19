# 수집 구조

server-exporter는 한 서버를 세 시점에서 봅니다.

- OS 안에서 (`os-gather/`, SSH 또는 WinRM)
- 하이퍼바이저에서 (`esxi-gather/`, vSphere API)
- BMC에서 (`redfish-gather/`, Redfish API)

각 시점이 자기 자리에서 본 정보만 모아 같은 모양의 JSON으로 돌려줍니다. 호출자가 둘 이상을 합쳐 보면 한 서버의 그림이 더 완성됩니다.

## 1. 호출 과정

```text
[ 호출자 ]
   │  inventory_json = [{ "bmc_ip": "192.0.2.201" }], target_type = redfish (또는 os, esxi), loc = ic
   ▼
[ Jenkins — Jenkinsfile_portal ]
   ├─ 입력 확인          파라미터 형식, 대상 목록 (inventory.sh 와 같은 규칙), callbackUrl   (Controller)
   ├─ 실행 위치 확인     loc → Runner 라벨 (common/vars/locations.yml)                        (Controller)
   ├─ 서버 정보 수집     저장소 checkout → scripts/run_gather.sh → ansible-playbook         (Runner)
   │       ├─ os-gather/site.yml       (target_type = os)
   │       ├─ esxi-gather/site.yml     (target_type = esxi)
   │       └─ redfish-gather/site.yml  (target_type = redfish)
   │           └─ callback_plugins/json_only.py 가 OUTPUT 태스크의 봉투를 gather_output.json 에 한 줄씩 씁니다
   └─ 결과 확인 및 전송  결과 회수 → 접수 수 = 결과 수 → callbackUrl 로 POST                 (Controller)
```

호출자는 IP만 넘깁니다. 자격증명은 vault에서 로딩되고, OS 종류는 포트와 프로토콜 확인으로, BMC 제조사는 Redfish 서비스 루트의 응답으로 정해집니다. 파이프라인의 동작은 [../operate/04-pipeline-runtime.md](../operate/04-pipeline-runtime.md)에 있습니다.

## 2. 어느 시점이 뭘 보나

| 섹션 | OS 안에서 (Linux, Windows) | 하이퍼바이저에서 (ESXi) | BMC에서 (Redfish) |
|---|:---:|:---:|:---:|
| `system` (OS, 호스트명, 가동시간) | O | O | |
| `hardware` (벤더, 모델, 시리얼, BIOS) | O | O | O |
| `bmc` (BMC 펌웨어, 상태) | | | O |
| `cpu`, `memory`, `storage`, `network` | O | O | O |
| `firmware` (펌웨어 목록) | | | O |
| `users` (로컬 계정) | O | | |
| `power`, `thermal` (전원, 온도, 팬) | | | O |

표에 없는 칸은 결과에서 `not_supported`로 나옵니다. 벤더와 세대별 상세는 [../reference/compatibility-matrix.md](../reference/compatibility-matrix.md)에 있습니다.

## 3. 공통 골격

세 채널이 같은 순서를 따릅니다.

```text
[ A ] common/tasks/normalize/init_fragments.yml    누적 변수를 비웁니다 (섹션별 빈 뼈대)
[ B ] common/tasks/precheck/run_precheck.yml       사전 진단: 도달 → 포트 → 프로토콜 (common/library/precheck_bundle.py)
[ C ] lookup_plugins/adapter_loader.py             벤더, 세대, OS 종류에 맞는 어댑터 선택
[ D ] common/tasks/credential/                     vault 경로 결정과 로딩 (Redfish 는 표준 계정과 복구 계정 두 파일)
[ E ] gather_* / collect_* 태스크                   실제 수집. 자기 fragment 만 채우고 merge_fragment.yml 을 부릅니다
[ F ] common/tasks/normalize/build_*.yml           sections, status, errors, meta, correlation → 봉투 13 필드 조립
[ G ] CHECKPOINT 태스크 → (Add-on hook) → OUTPUT 태스크
```

`CHECKPOINT`는 조립이 끝난 봉투의 보존본입니다. 추가 수집(Add-on)이 켜져 있으면 그 뒤에 Add-on이 돌고, 어떻게 끝나든 기본 결과는 남습니다([07-addon-hook.md](07-addon-hook.md)). 이 골격을 깨지 않아야 새 채널과 새 섹션이 같은 봉투를 냅니다.

## 4. os-gather

`site.yml`은 플레이 넷으로 되어 있습니다.

```text
플레이 1  os-gather | detect        (hosts: all)
    5986 → 5985 → 22 순으로 포트와 프로토콜을 확인합니다
    SSH 응답           → _os_linux 그룹
    WinRM 응답         → _os_windows 그룹
    둘 다 아니면       → _os_failed 그룹
플레이 2  os-gather | failed-output (hosts: _os_failed)
    build_failed_output 으로 실패 봉투를 바로 냅니다
플레이 3  os-gather | linux         (hosts: _os_linux)
    tasks/try_credentials.yml                vault 의 계정 후보를 순서대로 시도 (try_one_credential.yml)
    tasks/linux/preflight.yml                Python 버전 확인 → 모듈 경로 또는 raw 경로
    tasks/linux/gather_system.yml            system, hardware fragment (비특권 raw + sudo raw)
    tasks/linux/build_identifier_diagnostics.yml   시리얼, UUID 를 못 읽은 이유를 errors[] 로
    tasks/linux/gather_cpu.yml               cpu
    tasks/linux/gather_memory.yml            memory (dmidecode, 실패 시 /proc/meminfo)
    tasks/linux/gather_storage.yml           storage (lsblk, df, multipath)
    tasks/linux/gather_network.yml           network (ip, /sys/class/net, resolv.conf)
    tasks/linux/gather_users.yml             users (getent, lastlog)
    tasks/linux/gather_hba_ib.yml            FC HBA, InfiniBand 포트 — link_layer 가 InfiniBand 인 포트만 (storage 섹션 안)
    build_* → CHECKPOINT → OUTPUT
플레이 4  os-gather | windows       (hosts: _os_windows)
    tasks/windows/gather_system, gather_hardware, gather_cpu, gather_memory, gather_storage,
    gather_network, gather_users, gather_runtime → build_* → CHECKPOINT → OUTPUT
```

Linux는 대상의 Python 상태에 따라 두 경로로 동작합니다. 결과 형식은 같습니다.

| 경로 | 조건 | 수집 방식 |
|---|---|---|
| 모듈 경로 (`python_ok`) | 대상에 Python 3.9 이상 | setup 모듈의 facts 를 먼저 쓰고 셸 명령으로 보강 |
| raw 경로 (`python_missing`, `python_incompatible`, `raw_forced`) | Python 이 없거나 3.8 이하 | `raw` 모듈로 셸 명령만 실행하고 Runner 에서 Jinja2 로 해석 |

`SE_FORCE_LINUX_RAW_FALLBACK=true`를 주면 Python이 있는 대상에서도 raw 경로를 씁니다. 디버깅과 시험용입니다. 어느 경로였는지는 결과의 `diagnosis.details.gather_mode`에 남습니다.

## 5. esxi-gather

```text
site.yml (플레이 하나)
    tasks/try_credentials.yml            vault 계정 후보 시도 (vmware_host_facts 로 확인)
    tasks/collect_facts.yml              vmware_host_facts      → _e_raw_facts (자격 확인 때 받은 결과를 재사용)
    tasks/collect_config.yml             vmware_host_config_info → _e_raw_config
    tasks/collect_datastores.yml         vmware_datastore_info  → _e_raw_ds
    tasks/collect_dns.yml                vmware_host_dns_info 로 DNS 보강
    tasks/collect_disks.yml              esxi_disks (이 저장소의 pyvmomi 모듈) → 물리 디스크, 가동시간, 게이트웨이
    tasks/normalize_system.yml           system, hardware, cpu, memory fragment
    tasks/normalize_network.yml          network fragment
    tasks/normalize_storage.yml          storage fragment (datastore, 볼륨 포함)
    tasks/normalize_power_thermal.yml    power · thermal fragment — esxi_disks sensors 파트(vSphere 하드웨어 센서, 2026-10-19)
    tasks/collect_network_extended.yml   vmnic, vswitch, portgroup, vmhba 상세 보강
    tasks/collect_runtime.yml            NTP, 방화벽, 서비스 상태 보강
    build_* → CHECKPOINT → OUTPUT
```

vCenter 주소를 주면 서비스 응답의 `apiType`이 `VirtualCenter`라서 자격증명을 보내지 않고 `protocol` 단계에서 멈춥니다. Runner에는 `community.vmware` 컬렉션과 `pyvmomi`가 필요합니다([../../REQUIREMENTS.md](../../REQUIREMENTS.md)).

## 6. redfish-gather

세 채널 중 단계가 가장 많습니다. 무인증 서비스 루트로 벤더를 먼저 알아내고, 그 결과로 어댑터와 복구 계정 범위를 정합니다.

```text
site.yml (플레이 하나)
    run_precheck                        TCP 443 → /redfish/v1/ 응답 확인
    tasks/detect_vendor.yml             Manufacturer, Product → common/vars/vendor_aliases.yml 로 정규화 (예: dell)
    adapter_loader                      예: redfish_dell_idrac9
    tasks/load_vault.yml                표준 계정 (vault/common/redfish/standard.yml) + 복구 계정 (vault/<loc>/redfish/<vendor>.yml)
    tasks/collect_standard.yml          표준 계정으로 인증하고 수집 (library/redfish_gather.py 한 번 호출, try_one_account.yml)
    tasks/account_service.yml           표준 계정이 401 로 거부됐고 복구 계정이 있을 때만: 표준 계정 생성 또는 비밀번호 동기화
    tasks/reselect_adapter.yml          복구 뒤 재수집이 성공하면 모델, 펌웨어로 어댑터를 다시 고릅니다
    tasks/normalize_standard.yml        표준 fragment 생성
    build_* → CHECKPOINT → OUTPUT
```

### 6.1 storage 구조

```text
storage
├── controllers[]       RAID, HBA 컨트롤러
│   └── drives[]        컨트롤러에 매달린 드라이브
├── physical_disks[]    모든 물리 디스크 (중복 제거)
├── logical_volumes[]   RAID 논리 볼륨 (Redfish 전용)
├── hbas[], infiniband[]
├── filesystems[], datastores[]   Redfish 에서는 빈 배열
└── summary             그룹 합계
```

`logical_volumes[].controller_id`는 `controllers[].id`를, `logical_volumes[].member_drive_ids`는 `physical_disks[].id`를 가리킵니다. 용량이 0이거나 이름에 `empty`가 든 드라이브는 빈 베이로 보고 넣지 않습니다.

### 6.2 벤더와 vault

| 벤더 | 어댑터 예 | 복구 vault |
|---|---|---|
| Dell | `redfish_dell_idrac9` 외 | `vault/<loc>/redfish/dell.yml` |
| HPE | `redfish_hpe_ilo6` 외 | `vault/<loc>/redfish/hpe.yml` |
| Lenovo | `redfish_lenovo_xcc` 외 | `vault/<loc>/redfish/lenovo.yml` |
| Supermicro | `redfish_supermicro_x12` 외 | `vault/<loc>/redfish/supermicro.yml` |
| Cisco | `redfish_cisco_cimc` 외 | `vault/<loc>/redfish/cisco.yml` |
| Huawei, Inspur, Fujitsu, Quanta | 벤더별 1개 | `vault/<loc>/redfish/<vendor>.yml` |

수집 계정은 벤더와 무관하게 `vault/common/redfish/standard.yml` 하나입니다. 어댑터와 vault는 내부 대표 이름(`hpe` 등)을 쓰고, 결과 봉투의 `vendor` 값은 호출자 표시값으로 한 번 더 바뀝니다(HPE는 `hp`, Superdome Flex와 CSUS 3200은 `hpCsus`, 나머지는 그대로). 어느 벤더를 실장비로 확인했는지는 [../../REQUIREMENTS.md](../../REQUIREMENTS.md)에 있습니다.

## 7. 출력 플러그인 json_only

`callback_plugins/json_only.py`가 Ansible의 출력을 통제합니다.

- 이름이 정확히 `OUTPUT`인 태스크의 `msg`만 봉투로 다룹니다. 접두사 매칭이 아니며 `ANSIBLE_JSON_OUTPUT_TASK`로 이름을 바꿀 수 있습니다.
- 봉투는 표준출력과 `ANSIBLE_JSON_OUTPUT_FILE`에 서버마다 한 줄씩 씁니다.
- `CHECKPOINT` 태스크의 봉투는 `ANSIBLE_JSON_CHECKPOINT_FILE`에, 사전 진단과 진행 이벤트는 `ANSIBLE_JSON_PROGRESS_FILE`에 씁니다. Jenkins의 결과 확인 단계가 OUTPUT까지 못 간 서버를 이 파일들로 복원합니다.
- 실행이 끝났는데 OUTPUT이 없는 서버는 플러그인이 진단 기록으로 실패 봉투를 보충합니다. 요청한 서버 수와 봉투 수가 같아야 하기 때문입니다.

환경변수 전체는 [../operate/08-ansible-config.md](../operate/08-ansible-config.md)에 있습니다.

## 8. inventory.sh

세 채널에 같은 동작의 `inventory.sh`가 있습니다. 호출자가 보낸 JSON을 읽어 Ansible 인벤토리를 만듭니다.

| 우선순위 | 출처 |
|---|---|
| 1 | `INVENTORY_JSON_FILE`이 가리키는 파일. `Jenkinsfile_portal`이 작업 폴더에 쓴 `.inventory_input.json` |
| 2 | `INVENTORY_JSON` 또는 `inventory_json` 환경변수 (작은 입력의 편의 경로) |
| 3 | `$WORKSPACE/.inventory_input.json` (Jenkins 밖 직접 실행) |

- `inventory_hostname`은 IP입니다. 호스트명을 미리 등록하지 않습니다.
- 자격증명은 인벤토리에 들어가지 않습니다.
- 호출자가 보낸 서버 객체 전체는 `se_host_input` 아래에 보존되어 Add-on이 참조합니다.
- 대상 목록 검사(배열, 객체, IPv4, 중복)는 Jenkins의 입력 확인과 같은 규칙입니다. 한 대라도 틀리면 전체를 거부합니다.

입력 규칙은 [../contract/01-input.md](../contract/01-input.md)에 있습니다.

## 9. 새 섹션 추가

1. `gather_<섹션>.yml`을 만들어 fragment 변수를 채우고 `merge_fragment.yml`을 부릅니다.
2. 채널 `site.yml`에 `include_tasks` 한 줄을 추가합니다.
3. `schema/sections.yml`, `schema/field_dictionary.yml`, `common/vars/supported_sections.yml`, 어댑터의 `capabilities.sections_supported`, 기준선 JSON을 갱신합니다.

`build_output.yml`과 `merge_fragment.yml`은 고치지 않습니다. 절차는 [04-add-vendor.md](04-add-vendor.md)에 있습니다.

## 10. 더 보고 싶을 때

| 보고 싶은 것 | 문서 |
|---|---|
| fragment 가 봉투로 합쳐지는 과정 | [02-normalize-flow.md](02-normalize-flow.md) |
| 어댑터 점수와 벤더 감지 | [03-adapter-system.md](03-adapter-system.md) |
| 새 벤더, 세대, 섹션 추가 | [04-add-vendor.md](04-add-vendor.md) |
| 원본에서 필드까지의 매핑 | [05-field-mapping.md](05-field-mapping.md) |
| 실패 봉투와 진단 | [../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md) |
| 출력 필드의 의미 | [../contract/03-fields.md](../contract/03-fields.md) |
