# 06. 수집 구조 — 한눈에

## 한 줄 요약

server-exporter 는 한 서버를 3가지 시점으로 본다.

- **OS-gather** — 서버 OS 안에서 (SSH / WinRM)
- **ESXi-gather** — 하이퍼바이저에서 (vSphere API)
- **Redfish-gather** — BMC 에서 (HTTP + Redfish)

각 시점이 자기 자리에서 본 정보만 모아 같은 모양의 JSON 으로 돌려준다. 호출자가 둘 이상을 합쳐 보면 한 서버의 그림이 더 완성된다.

---

## 1. 호출 과정

```text
[ 호출자 (Jenkins Job 트리거) ]
        │  inventory_json = [{ bmc_ip: "10.50.11.162" }]
        │  target_type    = "redfish"  (또는 os / esxi)
        │  loc            = "ic"
        ▼
[ Jenkins 4-Stage 파이프라인 ]
        │
        ├─ [1] Validate    : 입력값 형식 점검
        │
        ├─ [2] Gather      : ansible-playbook 실행
        │       │
        │       ├─→ os-gather/site.yml      (target_type=os 일 때)
        │       ├─→ esxi-gather/site.yml    (target_type=esxi 일 때)
        │       └─→ redfish-gather/site.yml (target_type=redfish 일 때)
        │
        ├─ [3] Validate Schema : 출력 JSON 이 정의된 키와 일치하는지
        │
        └─ [4] E2E Regression  : 벤더별 baseline 회귀 테스트
                │
                ▼
        [ callback plugin (json_only) 이 stdout 으로 OUTPUT JSON 만 흘려보냄 ]
                │
                ▼
        [ 호출자가 console log 파싱 또는 artifact 로 수령 ]
```

핵심: **호출자는 IP 만 넘긴다.** 자격증명은 Ansible vault 에서 자동 로딩되고 벤더는 BMC 가 보고하는 manufacturer 로 자동 감지된다.

---

## 2. 어느 시점이 뭘 보나

같은 한 대 서버를 세 시점에서 본 결과를 비교해 본다.

| 섹션 | OS 안에서 (Linux/Windows) | 하이퍼바이저에서 (ESXi) | BMC 에서 (Redfish) |
|---|:---:|:---:|:---:|
| OS / 호스트명 / 가동시간 | O | O | (X) |
| 벤더 / 모델 / 시리얼 / BIOS | | O | O |
| BMC 펌웨어 / 자체 상태 | | | O |
| CPU / 메모리 / 스토리지 / 네트워크 | O | O | O |
| 펌웨어 인벤토리 | | | O |
| 로컬 OS 계정 | O | | |
| PSU / 전력 사용 | | | O |

같은 서버라도 시점별로 채워지는 영역이 겹치되 다르다. 호출자가 **둘 이상을 동시에 호출** 해서 합치면:

- Redfish 만 호출 → 하드웨어와 펌웨어 그림이 풍부, OS 정보는 빈 칸
- OS-gather 만 호출 → OS 와 계정 그림이 풍부, BMC 정보는 빈 칸
- 둘 다 호출 → 한 서버 전체 그림 완성

상세 호환 표는 `docs/reference/compatibility-matrix.md`.

---

## 3. 공통 골격 — 세 채널이 모두 같은 패턴

세 채널 모두 다음 처리 과정을 똑같이 따른다.

```text
[ A ] init_fragments.yml          ← 누적 변수 비우기 (보고서 빈 종이 준비)
        │
[ B ] precheck (4단계 진단)        ← 어디까지 닿는지 (docs/11)
        │
[ C ] adapter_loader              ← 벤더 / 세대 맞춰 어떤 처리 쓸지 결정 (docs/10)
        │
[ D ] (Redfish 만) load_vault     ← 벤더에 맞는 자격증명 로드
        │
[ E ] gather_*  /  collect_*      ← 실제 수집. 자기 fragment 5개만 채움
        │   ↑
        │   └ 각 gather 후에 merge_fragment.yml 호출 (docs/07)
        │
[ F ] build_sections / status / errors / meta / correlation / output
        │                            ← envelope 13 필드 조립
        ▼
[ G ] OUTPUT 태스크 → callback plugin → stdout
```

이 골격을 깨면 새 채널 추가가 어려워진다. 같은 패턴이라서 OS / ESXi / Redfish 가 같은 모양 JSON 을 돌려준다.

---

## 4. os-gather

```text
site.yml (4 Play)
  Play 1 — 포트 감지 (hosts: all)
      SSH(22) 응답하면          → _os_linux 그룹에 add_host
      WinRM(5985/5986) 응답하면 → _os_windows 그룹에 add_host
      둘 다 실패                → _os_failed 그룹에 add_host

  Play 1.5 — 포트 감지 실패 (hosts: _os_failed)
      build_failed_output       → failed envelope 즉시 반환

  Play 2 — Linux (hosts: _os_linux)
      init_fragments
      adapter_loader (os 채널)
      tasks/linux/preflight.yml      → Python 버전 감지 → python_ok / raw_fallback 분기
      tasks/linux/gather_system.yml  → system fragment   → merge
      tasks/linux/gather_cpu.yml     → cpu fragment      → merge
      tasks/linux/gather_memory.yml  → memory fragment   → merge   (dmidecode)
      tasks/linux/gather_storage.yml → storage fragment  → merge   (lsblk + mounts)
      tasks/linux/gather_network.yml → network fragment  → merge   (gw / dns / speed)
      tasks/linux/gather_users.yml   → users fragment    → merge   (getent + lastlog)
      tasks/linux/gather_hba_ib.yml  → HBA / InfiniBand   → merge
      tasks/linux/gather_runtime.yml → runtime 보강       → merge
      build_*  → output

  Play 3 — Windows (hosts: _os_windows)
      tasks/windows/* 사용. preflight / raw fallback 은 없다.
      gather_system / gather_hardware / gather_cpu / gather_memory /
      gather_storage / gather_network / gather_users / gather_runtime → 각 merge → build_* → output
```

Linux 는 환경에 따라 두 가지 모드로 동작한다.

| 모드 | 조건 | 수집 방식 |
|---|---|---|
| Python 모드 | Python 3.9+ 설치됨 | setup / shell / command / getent 풀가동 |
| Raw fallback | Python 미설치 또는 3.8 이하 | `raw` 모듈만 + 컨트롤러에서 Jinja2 파싱 |

`SE_FORCE_LINUX_RAW_FALLBACK=true` 로 강제 raw 모드도 가능 (디버깅용). 6개 섹션 모두 raw 모드로도 수집 가능하며 출력 JSON 형식은 100% 동일하다.

---

## 5. esxi-gather

```text
site.yml (Play 1개)
  init_fragments
  tasks/collect_facts.yml             → _e_raw_facts   (vSphere API: HostSystem facts)
  tasks/collect_config.yml            → _e_raw_config  (vSphere API: HostNetworkSystem 등)
  tasks/collect_datastores.yml        → _e_raw_ds      (vSphere API: HostDatastoreSystem)
  tasks/collect_dns.yml               → DNS 보강
  tasks/normalize_system.yml          → system / hardware / cpu / memory fragment → merge
  tasks/normalize_network.yml         → network fragment                          → merge
  tasks/normalize_storage.yml         → storage fragment (datastore / 볼륨 포함)   → merge
  tasks/collect_network_extended.yml  → NIC / vmnic 상세 보강 (normalize 후)
  tasks/collect_runtime.yml           → 가동시간 / 상태 보강 (normalize 후)
  build_*  → output
```

ESXi 는 `community.vmware` 컬렉션 + `pyvmomi` 9.0.0 의존. Agent 환경 설치 필요는 `docs/operate/02-agent-node.md`.

---

## 6. redfish-gather

세 채널 중 가장 단계가 많다. Redfish 는 무인증 ServiceRoot 호출로 벤더를 먼저 알아내고 그 결과로 자격증명을 동적으로 로드한다.

```text
site.yml (Play 1개)
  init_fragments
  precheck_bundle              → 진단 (TCP 443 → /redfish/v1/ 응답 확인)
  tasks/detect_vendor.yml      → BMC manufacturer → vendor_aliases.yml 거쳐 정규화
                                 → _rf_detected_vendor = "dell" / "hpe" / ...
  adapter_loader (redfish)     → _selected_adapter = (예) redfish_dell_idrac9
  tasks/load_vault.yml         → vault/<loc>/redfish/dell.yml 등 동적 로드
  tasks/collect_standard.yml   → 표준 endpoint 호출 (Systems / Chassis / Managers / Storage / ...)
                                 → Storage 실패 시 SimpleStorage 로 fallback
  tasks/normalize_standard.yml → 표준 fragment 생성 → merge
  _selected_adapter.oem_tasks  → 벤더 OEM fragment → merge   (adapter 가 시키면 호출)
  build_*  → output
```

### 6.1 Redfish 의 Storage 구조

```text
storage
├── controllers[]       — RAID / HBA 컨트롤러
│   └── drives[]        — 컨트롤러에 매달린 드라이브
├── physical_disks[]    — 모든 물리 디스크 (중복 제거)
├── logical_volumes[]   — RAID 논리 볼륨 (Redfish 전용)
├── filesystems[]       — (Redfish 에서는 빈 배열)
└── datastores[]        — (Redfish 에서는 빈 배열)
```

연결 관계:
- `logical_volumes[].controller_id`    →  `controllers[].id`
- `logical_volumes[].member_drive_ids` →  `physical_disks[].id`

`logical_volumes` 는 `/Systems/{id}/Storage/{id}/Volumes` 에서 수집. Cisco v1_0_3 스키마는 `RAIDType` 필드가 없어 `VolumeType` → `RAIDType` 으로 fallback 매핑.

### 6.2 디스크 필터 정책

- `CapacityBytes == 0` 또는 Name 에 "empty" 포함 → 빈 베이로 보고 skip
- HPE `PredictedMediaLifeLeftPercent` 가 float 로 오면 `int()` 변환

### 6.3 지원 벤더

| 벤더 | 매칭 adapter | vault |
|---|---|---|
| Dell | `redfish_dell_idrac9` 외 | `vault/<loc>/redfish/dell.yml` |
| HPE | `redfish_hpe_ilo6` 외 | `vault/<loc>/redfish/hpe.yml` |
| Lenovo | `redfish_lenovo_xcc` 외 | `vault/<loc>/redfish/lenovo.yml` |
| Supermicro | `redfish_supermicro_*` | `vault/<loc>/redfish/supermicro.yml` |
| Cisco | `redfish_cisco_cimc` | `vault/<loc>/redfish/cisco.yml` |

신규 벤더 (Huawei / Inspur / Fujitsu / Quanta / HPE Superdome) 도 adapter 가 등록되어 있으나 lab 부재로 미검증. 상세는 `docs/reference/live-validation.md`.

> [!NOTE]
> 위 "매칭 adapter" 와 vault 는 내부 canonical 이름(`hpe` 등)을 쓴다.
> 호출자에게 나가는 envelope `vendor` 값은 표시값으로 한 번 더 매핑된다 — HPE → `hp`, HPE Compute Scale-up 패밀리(CSUS 3200 + Superdome Flex) → `hpCsus`, 나머지는 canonical 그대로. 상세는 `docs/contract/03-fields.md`.

---

## 7. callback plugin — JSON 만 깔끔하게

`callback_plugins/json_only.py` 가 stdout 출력을 통제한다.

- Ansible 의 `PLAY / TASK / ok / changed` 같은 진행 메시지를 모두 차단
- 이름이 정확히 `OUTPUT` 인 task 의 `msg` 만 stdout 으로 흘려보냄 (접두사 매칭 아님 — `name: OUTPUT` 그대로. `ANSIBLE_JSON_OUTPUT_TASK` 로 변경 가능)

호출자가 stdout 한 덩어리를 그대로 JSON 파싱하면 된다. 별도 artifact 도 가능.

위치: 프로젝트 루트의 `callback_plugins/json_only.py` 단일 사본. `ansible.cfg` 에서 `callback_plugins = ./callback_plugins` 로 참조.

---

## 8. inventory.sh — IP 만 넘기는 약속

세 채널 (`os-gather/`, `esxi-gather/`, `redfish-gather/`) 모두 동일한 동작의 `inventory.sh` 가 있다.

| 입력 우선순위 | 출처 |
|---|---|
| 1순위 | `INVENTORY_JSON` 환경변수 |
| 2순위 | `.inventory_input.json` 파일 (Jenkinsfile 의 `writeFile` 가 생성) |

두 가지 경로를 두는 이유: Jenkins `ansiblePlaybook` 플러그인이 멀티라인 환경변수를 일부 환경에서 못 넘긴다. 파일 fallback 으로 보완.

추가 약속:
- `inventory_hostname = ip` 로 통일. 호스트명 사전 등록 안 한다.
- 자격증명은 inventory 에 안 들어간다. vault 에서 자동 로딩.

입력 JSON 스펙은 `docs/contract/01-input.md`.

---

## 9. 새 섹션 추가는 site.yml 한 줄

새 수집 항목을 추가할 때:

1. `gather_<섹션>.yml` 작성. fragment 5개 set_fact 후 `merge_fragment.yml` 호출.
2. 채널의 `site.yml` 에 `include_tasks: tasks/gather_<섹션>.yml` 한 줄 추가.
3. `schema/sections.yml` + `schema/field_dictionary.yml` + `baseline_v1/*.json` 갱신.

**`build_output.yml` 도 `merge_fragment.yml` 도 안 만진다.** 정규화 엔진은 fragment 패턴만 따르면 자동으로 동작한다.

상세 절차 7단계 체크리스트는 `docs/develop/04-add-vendor.md`.

---

## 10. 더 보고 싶을 때

| 보고 싶은 것 | 파일 |
|---|---|
| Fragment 가 어떻게 envelope 으로 합쳐지나 | `docs/develop/02-normalize-flow.md` |
| 실패 처리 패턴 (block / rescue / always) | `docs/contract/04-failure-and-diagnosis.md` |
| 새 섹션 / 새 채널 추가 절차 | `docs/develop/04-add-vendor.md` |
| Adapter 점수 계산과 벤더 자동 감지 | `docs/develop/03-adapter-system.md` |
| 출력 JSON 키 의미 | `docs/contract/03-fields.md` |
| 진단 4단계 상세 | `docs/contract/04-failure-and-diagnosis.md` |
| inventory_json 입력 형식 | `docs/contract/01-input.md` |
