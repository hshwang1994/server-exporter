# 16. OS / ESXi raw → normalize → output 매핑 표

> **이 문서는** OS (Linux / Windows) 와 ESXi 채널에서 원본(raw) 데이터가 표준 JSON 의 어느 필드로 들어가는지를 한 줄씩 매핑한 참조표다.
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
| `system.serial_number` | setup fact → DMI direct-read fallback (`become: true`) | `gather_system.yml` | setup fact가 NA일 경우 `/sys/class/dmi/id/product_serial` 직접 읽기. become 필수 |
| `system.system_uuid` | setup fact → DMI direct-read fallback (`become: true`) | `gather_system.yml` | setup fact가 NA일 경우 `/sys/class/dmi/id/product_uuid` 직접 읽기. cross-channel 연결 키 |
| `cpu.sockets` | `ansible_processor_count` | `gather_cpu.yml` | |
| `cpu.cores_physical` | `shell grep "cpu cores" × sockets` | `gather_cpu.yml` | |
| `cpu.logical_threads` | `ansible_processor_vcpus` | `gather_cpu.yml` | |
| `cpu.model` | `shell grep "model name"` | `gather_cpu.yml` | |
| `cpu.architecture` | `ansible_architecture` | `gather_cpu.yml` | system.architecture와 동일 값 |
| `memory.total_mb` | `ansible_memtotal_mb` | `gather_memory.yml` | |
| `memory.total_basis` | hardcoded `"os_visible"` | `gather_memory.yml` | |
| `storage.physical_disks[]` | `lsblk -J` | `gather_storage.yml` | |
| `storage.filesystems[]` | `df -BM` | `gather_storage.yml` | |
| `network.interfaces[]` | `ansible_interfaces` + `ansible_{iface}` | `gather_network.yml` | |
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
| `system.serial_number` | `ansible_product_serial` (WMI/setup) | `gather_system.yml` | NA/빈값→null 정규화 |
| `system.system_uuid` | `ansible_product_uuid` (WMI/setup) | `gather_system.yml` | NA/빈값→null 정규화. cross-channel 연결 키 |
| `cpu.sockets` | `Win32_Processor` (WMI) | `gather_cpu.yml` | WMI |
| `cpu.cores_physical` | `Win32_Processor.NumberOfCores` | `gather_cpu.yml` | WMI |
| `cpu.logical_threads` | `Win32_Processor.NumberOfLogicalProcessors` | `gather_cpu.yml` | WMI |
| `cpu.model` | `Win32_Processor.Name` | `gather_cpu.yml` | WMI |
| `cpu.architecture` | `ansible_architecture` (정규화 적용) | `gather_cpu.yml` | `'64' in _arch` 조건으로 "64비트"→"x86_64" 매핑 |
| `memory.total_mb` | `Win32_ComputerSystem.TotalPhysicalMemory` | `gather_memory.yml` | WMI |
| `memory.total_basis` | hardcoded `"physical_installed"` | `gather_memory.yml` | |
| `storage.physical_disks[]` | `Win32_DiskDrive` | `gather_storage.yml` | WMI |
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

---

## Redfish와의 차이점

| 채널 | system | hardware | bmc | cpu | memory | storage | network | firmware | users | power |
|------|--------|----------|-----|-----|--------|---------|---------|----------|-------|-------|
| **Redfish** | not_supported | success | success | success | success | success | success | success | not_supported | success |
| **OS** | success | not_supported | not_supported | success | success | success | success | not_supported | success | not_supported |
| **ESXi** | success | success | not_supported | success | success | success | success | not_supported | not_supported | not_supported |

---

## HBA / InfiniBand 채널 매핑

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
- 상세: [20_json-schema-fields.md §6.3.1](20_json-schema-fields.md), `schema/field_dictionary.yml`.

---

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| envelope 13 필드 + field 의미 | [20_json-schema-fields.md](20_json-schema-fields.md) |
| 채널별 실제 응답 예시 | [09_output-examples.md](09_output-examples.md) |
| OS / ESXi 환경 요건 | [REQUIREMENTS.md](../REQUIREMENTS.md) |
