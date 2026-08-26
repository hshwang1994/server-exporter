# 16. OS / ESXi raw → normalize → output 매핑 표

> 이 문서는 OS (Linux / Windows) 와 ESXi 채널에서 원본(raw) 데이터가 표준 JSON 의 어느 필드로 들어가는지를 한 줄씩 매핑한 참조표다.
>
> 새 필드를 추가하거나, 어떤 raw 소스가 어떤 output 필드를 만드는지 추적할 때 이 표를 검색한다.
> "어떤 ansible facts / shell 명령 / WMI 쿼리 결과가 무엇으로 변환되는지" 가 한눈에 보인다.

---

> [!NOTE]
> 표의 파일 위치 — Linux: `os-gather/tasks/linux/`, Windows: `os-gather/tasks/windows/`, ESXi: `esxi-gather/tasks/`.
> OS 채널은 `gather_*.yml` 한 파일이 수집과 fragment 생성을 같이 한다 (별도 `normalize_*.yml` 은 ESXi 일부에만 있다). 그래서 "Normalize File" 칸이 `gather_*.yml` 을 가리키기도 한다.

## Linux (Ubuntu)

| Output Field | Raw Source | Normalize File | 비고 |
|---|---|---|---|
| `system.os_family` | `ansible_os_family` (setup) | `gather_system.yml` | |
| `system.distribution` | `ansible_distribution` | `gather_system.yml` | |
| `system.version` | `ansible_distribution_version` | `gather_system.yml` | |
| `system.kernel` | `ansible_kernel` | `gather_system.yml` | |
| `system.architecture` | `ansible_architecture` | `gather_system.yml` | |
| `system.uptime_seconds` | `ansible_uptime_seconds \| int` | `gather_system.yml` | |
| `system.selinux` | `ansible_selinux.status` | `gather_system.yml` | |
| `system.hosting_type` | `systemd-detect-virt` + `ansible_virtualization_type/role` + `ansible_system_vendor` | `gather_system.yml` | OS 채널 전용. enum: virtual/baremetal/unknown |
| `system.fqdn` | `ansible_fqdn` | `gather_system.yml` | |
| `system.serial_number` | setup fact → DMI direct-read fallback (`become: true`) → nPartition 접미사 정규화 | `gather_system.yml` | setup fact가 NA일 경우 `/sys/class/dmi/id/product_serial` 직접 읽기. become 필수. 마지막에 파티션 접미사 정규화 (아래 별도 절) |
| `system.system_uuid` | setup fact → DMI direct-read fallback (`become: true`) | `gather_system.yml` | setup fact가 NA일 경우 `/sys/class/dmi/id/product_uuid` 직접 읽기. cross-channel 연결 키 |
| `cpu.sockets` | `ansible_processor_count` | `gather_cpu.yml` | |
| `cpu.cores_physical` | `shell grep "cpu cores" × sockets` | `gather_cpu.yml` | |
| `cpu.logical_threads` | `ansible_processor_vcpus` | `gather_cpu.yml` | |
| `cpu.model` | `shell grep "model name"` | `gather_cpu.yml` | |
| `cpu.architecture` | `ansible_architecture` | `gather_cpu.yml` | system.architecture와 동일 값 |
| `memory.total_mb` | `ansible_memtotal_mb` | `gather_memory.yml` | |
| `memory.total_basis` | hardcoded `"os_visible"` | `gather_memory.yml` | |
| `storage.physical_disks[]` | `lsblk -J` (`+SERIAL,WWN`) | `gather_storage.yml` | `serial`/`wwn` 추가(2026-06-22). 빈값 시 `udevadm info`(ID_SERIAL_SHORT/ID_WWN) 보강. virtio=null. `is_os_disk` 추가(2026-07-02): `findmnt /`→`lsblk -s` 로 OS 루트 물리 디스크 판정(SAN/NFS 루트=null) |
| `storage.filesystems[]` | `df -BM` | `gather_storage.yml` | |
| `network.interfaces[]` | `ansible_interfaces` + `ansible_{iface}` | `gather_network.yml` | |
| `network.interfaces[].addresses[]` (alias/secondary) | `ip -j addr show` → `ip -o addr show` → `ifconfig -a` (다중 소스 폴백) | `gather_network.yml` + `merge_linux_addresses` | `label`/`parent_interface`/`is_alias`/`scope`/`is_secondary` Additive. bond alias(bond1:1)는 parent addresses[] 에 병합 |
| `network.bonds[].addresses[]` | bond master 인터페이스 addresses 미러 (`build_linux_network`) | `gather_network.yml` | interfaces ↔ bonds 일관 |
| `network.default_gateways[]` | `ansible_default_ipv4.gateway` | `gather_network.yml` | |
| `users[]` | `getent passwd` + `last`/`lastlog` | `gather_users.yml` | |

---

## Windows

| Output Field | Raw Source | Normalize File | 비고 |
|---|---|---|---|
| `system.os_family` | `ansible_os_family` (setup) | `gather_system.yml` | WMI |
| `system.distribution` | `ansible_distribution` | `gather_system.yml` | WMI |
| `system.version` | `ansible_distribution_version` | `gather_system.yml` | WMI |
| `system.kernel` | `ansible_kernel` | `gather_system.yml` | WMI |
| `system.architecture` | `ansible_architecture` (정규화 적용) | `gather_system.yml` | "64비트"/"64-bit"/"AMD64"→"x86_64" 매핑 |
| `system.uptime_seconds` | `ansible_uptime_seconds \| int` | `gather_system.yml` | WMI |
| `system.selinux` | N/A | `gather_system.yml` | Windows에는 SELinux 없음 → null |
| `system.hosting_type` | `Win32_ComputerSystem` (Model, Manufacturer, HypervisorPresent) | `gather_system.yml` | OS 채널 전용. enum: virtual/baremetal/unknown |
| `system.fqdn` | `ansible_fqdn` | `gather_system.yml` | WMI |
| `system.serial_number` | `ansible_product_serial` (WMI/setup) | `gather_system.yml` | NA/빈값→null 정규화 + nPartition 접미사 정규화 (아래 별도 절) |
| `system.system_uuid` | `ansible_product_uuid` (WMI/setup) | `gather_system.yml` | NA/빈값→null 정규화. cross-channel 연결 키 |
| `cpu.sockets` | `Win32_Processor` (WMI) | `gather_cpu.yml` | WMI |
| `cpu.cores_physical` | `Win32_Processor.NumberOfCores` | `gather_cpu.yml` | WMI |
| `cpu.logical_threads` | `Win32_Processor.NumberOfLogicalProcessors` | `gather_cpu.yml` | WMI |
| `cpu.model` | `Win32_Processor.Name` | `gather_cpu.yml` | WMI |
| `cpu.architecture` | `ansible_architecture` (정규화 적용) | `gather_cpu.yml` | `'64' in _arch` 조건으로 "64비트"→"x86_64" 매핑 |
| `memory.total_mb` | `Win32_ComputerSystem.TotalPhysicalMemory` | `gather_memory.yml` | WMI |
| `memory.total_basis` | hardcoded `"physical_installed"` | `gather_memory.yml` | |
| `storage.physical_disks[]` | `Win32_DiskDrive` + `Get-PhysicalDisk` | `gather_storage.yml` | WMI. `serial`/`wwn` 추가(2026-06-22): serial=Get-PhysicalDisk→Win32 fallback(hex/공백 정규화), wwn=UniqueId(UniqueIdFormat EUI64/FCPHName/SCSIName 일 때만, 로컬 SATA=null). `is_os_disk` 추가(2026-07-02): `%SystemDrive%`→`Get-Partition.DiskNumber`(WMI fallback), `Win32_DiskDrive.Index` 매칭 |
| `storage.filesystems[]` | `Win32_LogicalDisk` | `gather_storage.yml` | WMI |
| `network.interfaces[]` | `Win32_NetworkAdapterConfiguration` | `gather_network.yml` | WMI |
| `network.default_gateways[]` | `Win32_NetworkAdapterConfiguration.DefaultIPGateway` | `gather_network.yml` | WMI |
| `users[]` | `Win32_UserAccount` + `Win32_NetworkLoginProfile` | `gather_users.yml` | WMI |

---

## ESXi

| Output Field | Raw Source | Normalize File | 비고 |
|---|---|---|---|
| `system.os_family` | `vmware_host_facts` → `ansible_distribution` | `normalize_system.yml` | vSphere API |
| `system.distribution` | `vmware_host_facts` → `ansible_distribution` | `normalize_system.yml` | vSphere API |
| `system.version` | `vmware_host_facts` → `ansible_distribution_version` | `normalize_system.yml` | vSphere API |
| `system.kernel` | `vmware_host_facts` → build number | `normalize_system.yml` | vSphere API |
| `system.architecture` | `vmware_host_facts` → `ansible_machine` | `normalize_system.yml` | `ansible_machine` 없으면 `x86_64` 기본 (ESXi 7.x/8.x 모두 x86_64) |
| `system.uptime_seconds` | `vmware_host_facts` → uptime | `normalize_system.yml` | vSphere API |
| `system.selinux` | N/A | `normalize_system.yml` | ESXi에는 SELinux 없음 → null |
| `system.fqdn` | `vmware_host_facts` → FQDN | `normalize_system.yml` | vSphere API |
| `hardware.vendor` | `vmware_host_facts` → `ansible_system_vendor` | `normalize_system.yml` | vSphere API |
| `hardware.model` | `vmware_host_facts` → `ansible_product_name` | `normalize_system.yml` | vSphere API |
| `hardware.serial` | `vmware_host_facts` → `ansible_product_serial` | `normalize_system.yml` | vSphere API |
| `hardware.uuid` | `vmware_host_facts` → `ansible_product_uuid` | `normalize_system.yml` | vSphere API |
| `hardware.bios_version` | `vmware_host_facts` → `ansible_bios_version` | `normalize_system.yml` | vSphere API |
| `hardware.bios_date` | `vmware_host_facts` → `ansible_bios_date` | `normalize_system.yml` | vSphere API |
| `cpu.sockets` | `vmware_host_facts` → `ansible_processor_count` | `normalize_system.yml` | vSphere API |
| `cpu.cores_physical` | `vmware_host_facts` → `ansible_processor_cores` | `normalize_system.yml` | vSphere API |
| `cpu.logical_threads` | `vmware_host_facts` → `ansible_processor_vcpus` | `normalize_system.yml` | vSphere API |
| `cpu.model` | `vmware_host_facts` → processor model | `normalize_system.yml` | vSphere API |
| `cpu.architecture` | `vmware_host_facts` → `ansible_machine` | `normalize_system.yml` | system.architecture와 동일 — 없으면 `x86_64` 기본 |
| `memory.total_mb` | `vmware_host_facts` → `ansible_memtotal_mb` | `normalize_system.yml` | vSphere API |
| `memory.total_basis` | hardcoded `"hypervisor_visible"` | `normalize_system.yml` | |
| `storage.datastores[]` | `vmware_host_facts` → datastore info | `normalize_storage.yml` | vSphere API |
| `network.interfaces[]` | `vmware_host_facts` → vmkernel interfaces | `normalize_network.yml` | vSphere API |
| `network.default_gateways[]` | `ansible_default_ipv4.gateway` (보통 미반환) | `normalize_network.yml` | vSphere schema 가 보통 ansible_default_ipv4 를 안 줘서 `[]` 유지. ESXi는 vmkernel 기반 네트워크 모델이라 host-level default gateway 의미가 OS와 다름 |

---

## 식별자 수집 경로 (serial_number / system_uuid)

| 채널 | 수집 경로 | 비고 |
|------|----------|------|
| Linux | setup fact → DMI direct-read fallback (`become: true`) | setup fact가 NA인 경우 DMI fallback이 사실상 필요. become 필수 |
| Windows | WMI (setup fact에서 직접 취득) | NA/센티널 → null 정규화 |
| ESXi | vmware_host_facts / normalize 결과 기준으로 수집 | 수집 경로와 정합성은 별도 관리 |
| Redfish | Systems/{id} SerialNumber, UUID | normalize_standard.yml에서 매핑 |

**Linux DMI fallback 동작:**
- `become_password` 제공 시: `/sys/class/dmi/id/product_serial`, `/sys/class/dmi/id/product_uuid` 직접 읽기
- `become_password` 미제공 시: block/rescue로 격리, null + `insufficient_privilege` diagnostic
- 어느 경우든 status는 success (식별자 수집 실패는 non-fatal)

### nPartition 시리얼 접미사 정규화 (OS 채널 전용)

HPE Compute Scale-up Server 3200 은 파티션(nPartition) 장비다. OS 안에서 읽는 시스템
시리얼에 파티션 번호가 접미사로 붙는다.

```
물리 장비 시리얼                       SGHD3TLNDD
Partition0 의 OS DMI product_serial    SGHD3TLNDD-000
```

자산 관리는 물리 장비 시리얼 기준이라, OS 채널은 이 접미사를 떼고 내보낸다.
구현은 `filter_plugins/serial_normalizer.py` 의 `normalize_os_serial` 필터 하나뿐이고,
`os-gather` 의 세 곳(Linux `system.serial_number`, Windows `system.serial_number`,
Windows `hardware.serial`)이 이 필터를 부른다.

**세 조건을 모두 만족할 때만** 값이 바뀐다.

| 조건 | 판정에 쓰는 값 |
|------|----------------|
| 제조사가 HPE 계열 | Linux `/sys/class/dmi/id/sys_vendor`, Windows `Win32_ComputerSystem.Manufacturer` |
| 모델이 Compute Scale-up Server 3200 계열 | Linux `/sys/class/dmi/id/product_name`, Windows `Win32_ComputerSystem.Model` |
| 시리얼이 하이픈 + 숫자 3자리로 끝남 | `-000`, `-001` … |

하나라도 어긋나면 시리얼을 **글자 그대로** 돌려준다. 하이픈만 보고 뒤를 자르는 일은 없다.

| 입력 (제조사 / 모델 / 시리얼) | 출력 |
|---|---|
| HPE / Compute Scale-up Server 3200 / `SGHD3TLNDD-000` | `SGHD3TLNDD` |
| HPE / ProLiant DL380 Gen11 / `CZ12345678` | `CZ12345678` (그대로) |
| HPE / ProLiant DL360 Gen10 / `ABC-123` | `ABC-123` (그대로) |
| Dell / PowerEdge R760 / `ABCDEF-000` | `ABCDEF-000` (그대로) |
| HPE / Compute Scale-up Server 3200 / `SGHD3TLNDD-ABC` | `SGHD3TLNDD-ABC` (그대로) |

Redfish 채널은 이 정규화를 적용하지 않는다. Redfish `hardware.serial` 은
`Systems/Partition0` 의 `SerialNumber` 원문(`SGHD3TLNDD-000`)을 유지한다. 같은 장비라도
OS 채널과 Redfish 채널의 시리얼 표기가 다를 수 있다는 뜻이다.

---

## Redfish와의 차이점

| 채널 | system | hardware | bmc | cpu | memory | storage | network | firmware | users | power |
|------|--------|----------|-----|-----|--------|---------|---------|----------|-------|-------|
| **Redfish** | not_supported | success | success | success | success | success | success | success | not_supported | success |
| **OS** | success | not_supported | not_supported | success | success | success | success | not_supported | success | not_supported |
| **ESXi** | success | success | not_supported | success | success | success | success | not_supported | not_supported | not_supported |

---

## HBA / InfiniBand 채널 매핑 (cycle 2026-05-29)

`data.storage.hbas[]` (FC HBA) / `data.storage.infiniband[]` 는 전 채널 동일 canonical 키
(`wwpn`/`wwnn`/`port_type`/`link_speed_gbps`/`source` 등). 채널별 수집원:

| 채널 | FC HBA 수집원 | InfiniBand 수집원 | 비고 |
|---|---|---|---|
| OS Linux | `/sys/class/fc_host/*` (port_name/node_name/driver/fw) | `/sys/class/infiniband/*` (node_guid/port GID/rate/fw) — **IB 정본** | raw fallback 양 모드 |
| OS Windows | `Get-InitiatorPort` (FC 만 필터) + `MSFC_*` WMI (model/vendor/driver/fw/speed) | `Get-NetAdapter` PhysicalMediaType=InfiniBand + `Get-PnpDevice VEN_15B3`. **node_guid=null** (표준 API 부재) | try/catch graceful |
| ESXi | `vmware_host_vmhba_info` (type+driver 2-signal, FC/iSCSI 만 — SAS/RAID 제외) | native IB 미노출 → `nmlx` NIC best-effort 추론 (`note`) | **API-only** (SSH 미사용, D1) |
| Redfish | `Chassis/NetworkAdapters/NetworkDeviceFunctions` (FC=`PortProtocol`/`NetDevFuncType`) | `Port.LinkNetworkTechnology` / `NetworkDeviceFunction` IB GUID | 주류 BMC 는 add-in IB 거의 미노출 → OS 채널 정본 |

- `source` ∈ {redfish, os, esxi} 로 출처 식별. `wwpn`/`node_guid` 로 동일 장치 cross-channel 상관.
- FC/IB 미보유 호스트 → 빈 list (graceful, error 아님). `port_type` ∈ {FibreChannel, FCoE, iSCSI}.
- 상세: [../contract/03-fields.md §6.3.1](../contract/03-fields.md), `schema/field_dictionary.yml`.

---

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| envelope 13 필드 + field 의미 | [../contract/03-fields.md](../contract/03-fields.md) |
| 채널별 실제 응답 예시 | [../contract/02-output-envelope.md](../contract/02-output-envelope.md) |
| OS / ESXi 환경 요건 | [REQUIREMENTS.md](../REQUIREMENTS.md) |

---

# Linux 수집 상세

아래는 Linux 채널이 각 값을 어디서 어떻게 얻는지 정리한 상세다. Python 경로와 raw
경로가 같은 필드를 서로 다른 소스에서 만들기 때문에, 값이 어긋날 때 어느 쪽을 보고
있는지 아는 게 중요하다.

## Linux 2-Tier Gather 참고사항

- **Memory**: raw fallback 경로에서 dmidecode 접근이 성공하면 `physical_installed` (물리 장착 메모리)를 반환한다. Python 경로의 `ansible_memtotal_mb`는 커널 예약 후 `os_visible` 값이므로, raw 경로가 하드웨어 인벤토리 용도에 더 정밀하다.
- **SELinux**: `getenforce` 출력(`Enforcing`/`Permissive`/`Disabled`)은 Ansible 컨벤션에 맞게 `enabled`/`disabled`로 정규화된다.
- **Ubuntu SELinux**: Ubuntu에서는 `getenforce`가 미설치이므로 `selinux = null`이 정상이다 (Python 경로의 `disabled`와 다르지만 허용 범위).

## Network 수집 정책

### primary 판단 규칙

| 경로 | primary 판단 기준 |
|------|-------------------|
| Python 경로 | `ansible_default_ipv4.interface` = primary |
| Raw 경로 | `ip route show default \| head -1`의 `dev` 필드 = primary (lowest metric wins) |

양쪽 모두 "IPv4 default route가 걸린 인터페이스 = primary" 원칙이다.

- **bond master**에 default route가 걸리면 bond master가 primary
- **bridge**에 default route가 걸리면 bridge가 primary
- slave/port 인터페이스는 IP가 없으므로 primary 불가

### default_gateways 추출

| 경로 | 추출 방식 |
|------|----------|
| Python 경로 | `ansible_default_ipv4.gateway` |
| Raw 경로 | `ip route show default \| head -1` → 3번째 필드 (gateway IP) |

- 다중 default route 존재 시: metric 순으로 정렬된 **첫 번째만** 사용
- IPv6 default gateway: 현재 미수집 (P3)

### skip 패턴 (제외되는 가상 인터페이스)

아래 패턴에 매칭되는 인터페이스는 수집에서 제외된다:

| 패턴 | 대상 |
|------|------|
| `lo` | loopback |
| `docker*`, `br-*` | Docker bridge networks |
| `veth*` | container veth pairs |
| `virbr*`, `vir*` | libvirt virtual bridges |
| `cni*`, `flannel*`, `cali*` | Kubernetes CNI |
| `tunl*`, `dummy*` | tunnel, dummy interfaces |
| `kube-*` | Kubernetes internal |

**중요**: `br0`, `bond0`, `team0`, `eth0.100`(VLAN) 등 일반 네트워크 인터페이스는 제외 대상이 아니다. 이들은 IP가 할당된 정상 인터페이스이므로 수집된다.

- **bond slave / bridge port 자동 제외**: `/sys/class/net/$dev/master`가 존재하면서 자신이 bridge/bond master가 아닌 인터페이스는 수집 제외 (raw path). Python path에서는 IP 없는 인터페이스가 자동 제외됨

### bond/team/bridge/VLAN 해석

| 유형 | 수집 여부 | 비고 |
|------|----------|------|
| bond master | IP 있으면 수집됨 | kind=os_nic, slave는 IP 없어 자동 제외 |
| bridge (br0) | IP 있으면 수집됨 | 하위 port는 IP 없어 자동 제외 |
| VLAN (eth0.100) | IP 있으면 수집됨 | — |

- **speed**: bond/bridge는 `/sys/class/net/*/speed`가 없거나 `-1` → `null`

### speed/link_status 해석

| 필드 | 소스 | 비고 |
|------|------|------|
| `speed` | `/sys/class/net/*/speed` | 가상 NIC는 `-1` 또는 미보고 → `null` |
| `link_status` | `/sys/class/net/*/operstate` | `up`/`down`/`unknown` |

- bond master speed는 kernel이 보고 안 할 수 있음 → `null`

### DNS 해석

- `/etc/resolv.conf`의 `nameserver` 행에서 추출
- `127.0.0.53` = systemd-resolved stub resolver (실제 upstream DNS가 아님)
- **운영 해석**: stub resolver가 보이면 `resolvectl status`로 실제 DNS 확인 필요

### 현재 한계

- IPv6 주소/gateway 미수집
- policy routing (`ip rule`, `table`) 미반영
- 다중 default route 중 첫 번째만 사용

### 배포판별 명령어 지원 매트릭스

실측 기준 (5대 서버 검증, SLES 15는 공식 문서 기준 예측):

| 명령/소스 | 패키지 | RHEL 8 | RHEL 9 | Rocky 9 | Ubuntu 24 | SLES 15 | gather 사용 | fallback |
|-----------|--------|--------|--------|---------|-----------|---------|------------|---------|
| `ip` | iproute | [OK] | [OK] | [OK] | [OK] | [OK] | 핵심 (addr/route/link) | 없음 — 필수 |
| `getent` | glibc-common | [OK] | [OK] | [OK] | [OK] | [OK] | users 수집 | 없음 — 필수 |
| `lsblk` | util-linux | [OK] | [OK] | [OK] | [OK] | [OK] | storage 물리디스크 | 빈 배열 반환 |
| `df` | coreutils | [OK] | [OK] | [OK] | [OK] | [OK] | storage 파일시스템 | 빈 배열 반환 |
| `getenforce` | libselinux-utils | [OK] | [OK] | [OK] | [NG] | [NG] | system.selinux | null |
| `lastlog` | shadow-utils/login | [OK] | [OK] | [OK] | [OK] | [OK] | users.last_access_time | last → utmpdump |
| `utmpdump` | util-linux | [OK] | [OK] | [OK] | [OK] | [OK] | users 3차 fallback | null |
| `systemd-detect-virt` | systemd | [OK] | [OK] | [OK] | [OK] | [OK] | system.hosting_type | unknown |
| `dmidecode` | dmidecode | [OK] | [OK] | [OK] | [OK] | [OK] | memory, serial/uuid | 권한 의존 |
| `resolvectl` | systemd-resolved | [OK](8) | [NG](9) | [NG] | [OK] | [NG] | 미사용 (참고용) | — |
| `nmcli` | NetworkManager | [OK] | [OK] | [OK] | [NG] | [NG] | 미사용 | — |
| `networkctl` | systemd | [NG] | [NG] | [NG] | [OK] | [NG] | 미사용 | — |
| `/sys/class/net/*` | kernel sysfs | [OK] | [OK] | [OK] | [OK] | [OK] | network 핵심 (mac/mtu/speed/state/master) | — |
| `/proc/cpuinfo` | kernel | [OK] | [OK] | [OK] | [OK] | [OK] | cpu 수집 | — |
| `/proc/meminfo` | kernel | [OK] | [OK] | [OK] | [OK] | [OK] | memory 수집 | — |
| `/etc/os-release` | filesystem | [OK] | [OK] | [OK] | [OK] | [OK] | system 수집 | — |
| `/etc/resolv.conf` | filesystem | [OK] | [OK] | [OK] | [OK] | [OK] | dns_servers | — |

- SLES 15 값은 공식 문서 기준 예측 (실증 미완)
- `ip`, `getent`, `/sys/class/net`, `/proc/*`, `/etc/os-release`는 모든 배포판에서 보장
- `nmcli`, `resolvectl`, `networkctl`은 배포판/네트워크 스택에 따라 상이하므로 gather 주 수집 소스로 사용하지 않음
- gather는 kernel sysfs + POSIX 명령 + /proc 의존 → 배포판 무관 동작 설계

### Network raw fallback source 우선순위

| 데이터 | 1순위 | 2순위 | 3순위 | 미지원 시 |
|--------|-------|-------|-------|----------|
| IPv4 주소/프리픽스 | `ip -o -4 addr show` | — | — | 빈 addresses |
| IPv6 주소 | — | — | — | **미수집 (P3)** |
| default gateway | `ip route show default \| head -1` | — | — | 빈 default_gateways |
| primary 판정 | default route의 `dev` 필드 | — | — | 전체 is_primary=false |
| DNS | `/etc/resolv.conf` nameserver 행 | — | — | 빈 dns_servers |
| MAC | `/sys/class/net/*/address` | — | — | 인터페이스 제외 |
| MTU | `/sys/class/net/*/mtu` | — | — | null |
| speed | `/sys/class/net/*/speed` | — | — | null (-1 → null) |
| link state | `/sys/class/net/*/operstate` | — | — | unknown |
| slave/port 판정 | `/sys/class/net/*/master` sysfs | — | — | slave 미감지 → 수집 |
| bridge 판정 | `/sys/class/net/*/bridge/` dir | — | — | bridge 미감지 |
| bond 판정 | `/sys/class/net/*/bonding/` dir | — | — | bond 미감지 |
