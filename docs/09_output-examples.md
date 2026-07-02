# 09. 출력 JSON 예시

> **이 문서는** server-exporter 가 호출자에게 돌려주는 표준 JSON 의 실제 모양을 보여준다.
> 호출자(포털) 개발자가 "내가 받을 JSON 이 어떻게 생겼는지" 빠르게 이해할 때 가장 유용하다.
>
> 채널별 (Linux / Windows / ESXi / Redfish) 한 건씩 대표 예시를 수록한다.
> 모든 예시는 `schema_version: "1"` 과 일치하며, 전체 baseline 은 `schema/baseline_v1/` 디렉터리에 있다.

모든 예시는 표준 스키마(`schema_version: "1"`)와 일치한다.
채널별 대표 1건씩 수록하며, 긴 list(슬롯/디스크/펌웨어 등)는 대표 1~2개만 남기고 `(일부 생략)` 으로 표기했다.
전체·완전한 실 장비 결과는 `schema/baseline_v1/` (회귀 기준선) 과 `schema/output_examples/` (한글 주석본) 참조.

> **envelope 13 필드 작성 순서** (정본 `common/tasks/normalize/build_output.yml`):
> `target_type, collection_method, ip, hostname, vendor, status, sections, diagnosis, meta, correlation, errors, data` + `schema_version`.
> 실패 fallback 응답도 13 필드를 모두 채운다 (rule 13 R5).

---

## 참조 파일

### Field Dictionary

각 필드의 상세 의미, 단위, null 해석은 `schema/field_dictionary.yml`에 정의 (Must 47 + Nice 115 + Skip 6 = **168 entries**, 2026-07-02 재실측).

```bash
# 무결성 검사
python3 tests/validate_field_dictionary.py
```

### Baseline v1 출력 샘플 (9개 — 회귀 기준선)

| 파일 | 채널 | 대상 |
|------|------|------|
| `dell_baseline.json` | Redfish | Dell PowerEdge R740 (iDRAC9 / FW 4.00) |
| `hpe_baseline.json` | Redfish | HPE ProLiant DL380 Gen11 (iLO6 / FW 1.73) |
| `hpe_csus_3200_baseline.json` | Redfish | HPE Compute Scale-up Server 3200 (mock-derived — lab 부재) |
| `lenovo_baseline.json` | Redfish | Lenovo ThinkSystem SR650 V2 (XCC / FW 5.70) |
| `cisco_baseline.json` | Redfish | Cisco TA-UNODE-G1 (CIMC) |
| `esxi_baseline.json` | ESXi | VMware ESXi 7.0.3 (on Cisco UCS) |
| `ubuntu_baseline.json` | OS (Linux) | Ubuntu 24.04 |
| `windows_baseline.json` | OS (Windows) | Windows 10 22H2 |
| `rhel810_raw_fallback_baseline.json` | OS (Linux) | RHEL 8.10 (Python raw fallback 경로) |

> [!NOTE]
> `hpe_baseline.json` 의 `adapter_id` 는 `redfish_hpe_ilo5` 로 기록돼 있다. 이 baseline 은 `redfish_hpe_ilo6` adapter 추가(2026-05-01) 이전에 캡처됐기 때문이다. 현재 adapter 세트에서는 iLO6/FW 1.73 이 `redfish_hpe_ilo6`(P100) 로 매칭된다. baseline 재생성이 필요하다(후속 작업).

### 한글 주석본 (호출자/운영자 reference)

`schema/output_examples/*.jsonc` 에 실 장비 결과 + 라인별 한글 주석본이 있다 (JSON with Comments). 각 필드 의미를 캡처 응답 위에서 바로 읽고 싶을 때 사용.

### Safe Common 5 필드 (Redfish)

| 필드 | 타입 | 설명 |
|------|------|------|
| `hardware.health` | string\|null | 시스템 Health — OK/Warning/Critical |
| `hardware.power_state` | string\|null | 전원 — On/Off/PoweringOn/PoweringOff |
| `storage.physical_disks[].serial` | string\|null | 디스크 시리얼 |
| `storage.physical_disks[].is_os_disk` | boolean\|null | OS 설치(루트) 디스크 여부 — OS 채널 전용 |
| `storage.physical_disks[].failure_predicted` | boolean\|null | SMART 고장 예측 |
| `storage.physical_disks[].predicted_life_percent` | integer\|null | 수명 잔량 (0-100) |

### 디스크 필터 정책

| 정책 | 설명 |
|------|------|
| CapacityBytes == 0 → skip | FlexFlash, Empty Bay 제외 |
| Name contains "empty" → skip | 빈 베이 패턴 제외 |

---

## os-gather — success (Linux / Ubuntu 24.04)

```json
{
  "target_type": "os",
  "collection_method": "agent",
  "ip": "10.x.x.20",
  "hostname": "server01.example.com",
  "vendor": null,
  "status": "success",
  "sections": {
    "system": "success", "hardware": "not_supported", "bmc": "not_supported",
    "cpu": "success", "memory": "success", "storage": "success",
    "network": "success", "firmware": "not_supported", "users": "success",
    "power": "not_supported"
  },
  "diagnosis": {
    "reachable": true, "port_open": true, "protocol_supported": true,
    "auth_success": true, "failure_stage": null, "failure_reason": null,
    "details": {
      "channel": "os", "adapter_candidate": "os_linux_generic",
      "detected_os": "linux", "selected_port": 22, "checked_ports": [22]
    }
  },
  "meta": {
    "started_at": "2026-04-01T04:35:59Z", "finished_at": "2026-04-01T04:36:13Z",
    "duration_ms": 14000, "adapter_id": "os_linux_generic",
    "adapter_version": "1.0.0", "ansible_version": "2.20.3"
  },
  "correlation": {
    "serial_number": "VMware-42 04 87 42 ...", "system_uuid": "42870442-2b3c-0035-b72a-78db3648f403",
    "bmc_ip": null, "host_ip": "10.x.x.20"
  },
  "errors": [],
  "data": {
    "system": {
      "os_family": "Debian", "distribution": "Ubuntu", "version": "24.04",
      "kernel": "6.8.0-100-generic", "architecture": "x86_64", "hosting_type": "virtual",
      "uptime_seconds": 1228133, "selinux": "disabled", "fqdn": "server01.example.com",
      "serial_number": "VMware-42 04 87 42 ...", "system_uuid": "42870442-2b3c-0035-b72a-78db3648f403",
      "runtime": {
        "timezone": "Etc/UTC", "ntp_active": true, "ntp_synchronized": true,
        "firewall_tool": "ufw", "firewall_state": "inactive",
        "listening_ports": ["22", "53"], "swap_total_mb": 4095, "swap_used_mb": 0, "swap_free_mb": 4095
      }
    },
    "hardware": null, "bmc": null,
    "cpu": {
      "sockets": 2, "cores_physical": 2, "logical_threads": 2,
      "model": "Intel(R) Xeon(R) CPU E5-2699 v4 @ 2.20GHz", "architecture": "x86_64",
      "summary": { "groups": [
        {"model": "Intel(R) Xeon(R) CPU E5-2699 v4 @ 2.20GHz", "manufacturer": "Intel",
         "max_speed_mhz": null, "l2_cache_kb": null, "l3_cache_kb": null,
         "sockets": 2, "cores_per_socket": 1, "total_cores": 2}
      ] }
    },
    "memory": {
      "total_mb": 3915, "total_basis": "os_visible", "installed_mb": null, "visible_mb": 3915,
      "slots": [], "summary": { "groups": [], "grand_total_gb": 3 }
    },
    "storage": {
      "filesystems": [
        {"device": "/dev/sda2", "mount_point": "/", "filesystem": "ext4",
         "total_mb": 100217.9, "used_mb": 12596.7, "available_mb": 87621.2,
         "usage_percent": 12.6, "status": "mounted"}
      ],
      "physical_disks": [
        {"id": "/dev/sda", "device": "/dev/sda", "model": "Virtual disk", "total_mb": 102400,
         "media_type": "HDD", "protocol": null, "health": null}
      ],
      "controllers": [], "logical_volumes": [], "datastores": [], "hbas": [], "infiniband": [],
      "summary": { "groups": [
        {"unit_capacity_gb": 100, "media_type": "HDD", "protocol": null, "quantity": 1, "group_total_gb": 100}
      ], "grand_total_gb": 100 }
    },
    "network": {
      "dns_servers": ["127.0.0.53"],
      "default_gateways": [{"family": "ipv4", "address": "10.x.x.254"}],
      "interfaces": [
        {"id": "ens160", "name": "ens160", "kind": "os_nic", "mac": "00:50:56:84:66:3b",
         "mtu": 1500, "speed_mbps": 10000, "link_status": "up", "is_primary": true,
         "addresses": [{"family": "ipv4", "address": "10.x.x.20",
                        "prefix_length": 24, "subnet_mask": "255.255.255.0", "gateway": "10.x.x.254"}]}
      ],
      "summary": { "groups": [
        {"speed_mbps": 10000, "link_type": null, "quantity": 1, "link_up_count": 1}
      ] }
    },
    "users": [
      {"name": "root", "uid": "0", "groups": ["root"], "home": "/root", "last_access_time": null}
    ],
    "firmware": [], "power": null
  },
  "schema_version": "1"
}
```

> Linux 의 `total_basis` 는 `os_visible` (`/proc/meminfo`) 또는 `physical_installed` (dmidecode, raw fallback 경로) 두 값을 가질 수 있다.

---

## os-gather — success (Windows)

```json
{
  "target_type": "os",
  "collection_method": "agent",
  "ip": "10.x.x.120",
  "hostname": "WIN-HOST01",
  "vendor": null,
  "status": "success",
  "sections": {
    "system": "success", "hardware": "not_supported", "bmc": "not_supported",
    "cpu": "success", "memory": "success", "storage": "success",
    "network": "success", "firmware": "not_supported", "users": "success",
    "power": "not_supported"
  },
  "diagnosis": {
    "reachable": true, "port_open": true, "protocol_supported": true,
    "auth_success": true, "failure_stage": null, "failure_reason": null,
    "details": {
      "channel": "os", "adapter_candidate": "os_windows_generic",
      "detected_os": "windows", "selected_port": "5985", "checked_ports": [5985, 5986]
    }
  },
  "meta": {
    "started_at": "2026-04-01T04:36:21Z", "finished_at": "2026-04-01T04:37:05Z",
    "duration_ms": 44000, "adapter_id": "os_windows_generic",
    "adapter_version": "1.0.0", "ansible_version": "2.20.3"
  },
  "correlation": {
    "serial_number": "VMware-42 04 cc cc ...", "system_uuid": "CCCC0442-703A-67BF-4D8C-BEC6FB82C265",
    "bmc_ip": null, "host_ip": "10.x.x.120"
  },
  "errors": [],
  "data": {
    "system": {
      "os_family": "Windows", "distribution": "Microsoft Windows 10 Home", "version": "22H2",
      "kernel": "19045", "architecture": "x86_64", "hosting_type": "virtual",
      "uptime_seconds": 167596, "selinux": null, "fqdn": "WIN-HOST01",
      "serial_number": "VMware-42 04 cc cc ...", "system_uuid": "CCCC0442-703A-67BF-4D8C-BEC6FB82C265",
      "runtime": {
        "timezone": null, "ntp_active": null, "ntp_synchronized": null,
        "firewall_tool": "windows_firewall", "firewall_state": null,
        "listening_ports": [], "swap_total_mb": null, "swap_used_mb": null, "swap_free_mb": null
      }
    },
    "hardware": null, "bmc": null,
    "cpu": {
      "sockets": 1, "cores_physical": 2, "logical_threads": 2,
      "model": "Intel(R) Xeon(R) CPU E5-2699 v4 @ 2.20GHz", "architecture": "x86_64",
      "summary": { "groups": [
        {"model": "Intel(R) Xeon(R) CPU E5-2699 v4 @ 2.20GHz", "manufacturer": "Intel",
         "max_speed_mhz": null, "l2_cache_kb": null, "l3_cache_kb": null,
         "sockets": 1, "cores_per_socket": 2, "total_cores": 2}
      ] }
    },
    "memory": {
      "total_mb": 8192, "total_basis": "physical_installed", "installed_mb": 8192, "visible_mb": 8192,
      "slots": [], "summary": { "groups": [], "grand_total_gb": 8 }
    },
    "storage": {
      "filesystems": [
        {"device": "C:", "mount_point": "C:\\", "filesystem": "NTFS",
         "total_mb": 60747.5, "used_mb": 32078.9, "available_mb": 28668.6,
         "usage_percent": 52.8, "status": "mounted"}
      ],
      "physical_disks": [
        {"id": "\\\\.\\PHYSICALDRIVE0", "device": "\\\\.\\PHYSICALDRIVE0",
         "model": "VMware Virtual disk SCSI Disk Device", "total_mb": 61436,
         "media_type": "HDD", "protocol": null, "health": null}
      ],
      "controllers": [], "logical_volumes": [], "datastores": [], "hbas": [], "infiniband": [],
      "summary": { "groups": [
        {"unit_capacity_gb": 59, "media_type": "HDD", "protocol": null, "quantity": 1, "group_total_gb": 59}
      ], "grand_total_gb": 59 }
    },
    "network": {
      "dns_servers": ["10.x.x.251"],
      "default_gateways": [{"family": "ipv4", "address": "10.x.x.254"}],
      "interfaces": [
        {"id": "vmxnet3 Ethernet Adapter", "name": "Ethernet0 2", "kind": "os_nic",
         "mac": "00-50-56-84-59-D0", "mtu": 1500, "speed_mbps": 10000,
         "link_status": "up", "is_primary": true,
         "addresses": [{"family": "ipv4", "address": "10.x.x.120",
                        "prefix_length": 24, "subnet_mask": null, "gateway": "10.x.x.254"}]}
      ],
      "summary": { "groups": [
        {"speed_mbps": 10000, "link_type": null, "quantity": 1, "link_up_count": 1}
      ] }
    },
    "users": [
      {"name": "Administrator", "uid": "S-1-5-21-...-500", "groups": ["Administrators"],
       "home": null, "last_access_time": null}
    ],
    "firmware": [], "power": null
  },
  "schema_version": "1"
}
```

> Windows `users[].uid` 는 SID (예: `S-1-5-21-...`), Linux 는 숫자 UID. `firewall_tool` 은 `windows_firewall` 로 채워지나 상세 state 는 미수집(null)일 수 있다.

---

## esxi-gather — success (VMware ESXi 7.0.3)

```json
{
  "target_type": "esxi",
  "collection_method": "vsphere_api",
  "ip": "10.x.x.2",
  "hostname": "esxi02",
  "vendor": "cisco",
  "status": "success",
  "sections": {
    "system": "success", "hardware": "success", "bmc": "not_supported",
    "cpu": "success", "memory": "success", "storage": "success",
    "network": "success", "firmware": "not_supported", "users": "not_supported",
    "power": "not_supported"
  },
  "diagnosis": {
    "reachable": true, "port_open": true, "protocol_supported": true,
    "auth_success": true, "failure_stage": null, "failure_reason": null,
    "details": {
      "channel": "esxi", "adapter_candidate": "esxi_generic",
      "checked_ports": [443], "selected_port": 443,
      "vsphere_endpoint": "https://10.x.x.2:443/sdk",
      "auth": {"attempted_count": 2, "used_label": "esxi_legacy", "used_role": "primary", "fallback_used": false}
    }
  },
  "meta": {
    "started_at": "2026-04-29T08:16:22Z", "finished_at": "2026-04-29T08:16:38Z",
    "duration_ms": 16000, "adapter_id": "esxi_generic",
    "adapter_version": null, "ansible_version": "2.20.3"
  },
  "correlation": {
    "serial_number": "FCH2116V1V0", "system_uuid": "9f0190b1-ce56-d44e-a1dd-6571daaedad7",
    "bmc_ip": null, "host_ip": "10.x.x.2"
  },
  "errors": [],
  "data": {
    "system": {
      "os_family": "VMware ESXi", "distribution": "VMware ESXi", "version": "7.0.3",
      "kernel": "20842708", "architecture": "x86_64", "uptime_seconds": 12377407,
      "selinux": null, "hostname": "esxi02", "fqdn": "esxi02", "hosting_type": "hypervisor",
      "runtime": {
        "timezone": null, "ntp_active": null, "ntp_synchronized": null,
        "firewall_tool": "esxi_firewall", "firewall_state": null,
        "listening_ports": [], "swap_total_mb": null, "swap_used_mb": null, "swap_free_mb": null
      }
    },
    "hardware": {
      "vendor": "Cisco Systems Inc", "model": "TA-UNODE-G1", "serial": "FCH2116V1V0",
      "uuid": "9f0190b1-ce56-d44e-a1dd-6571daaedad7",
      "bios_version": "C220M4.4.1.2c.0.0202211901", "bios_date": "2021-02-02T00:00:00+00:00"
    },
    "bmc": null,
    "cpu": {
      "sockets": 2, "cores_physical": 44, "logical_threads": 88,
      "model": "Intel(R) Xeon(R) CPU E5-2699 v4 @ 2.20GHz", "max_speed_mhz": 2200, "architecture": "x86_64",
      "summary": { "groups": [
        {"model": "Intel(R) Xeon(R) CPU E5-2699 v4 @ 2.20GHz", "manufacturer": "Intel",
         "max_speed_mhz": 2200, "architecture": "x86_64", "sockets": 2, "cores_per_socket": 22, "total_cores": 44}
      ] }
    },
    "memory": {
      "total_mb": 1048464, "total_basis": "hypervisor_visible", "visible_mb": 1048464,
      "slots": [], "summary": { "groups": [], "grand_total_gb": 1023 }
    },
    "storage": {
      "filesystems": [], "physical_disks": [], "controllers": [], "logical_volumes": [], "infiniband": [],
      "datastores": [
        {"name": "ESXi02-Local-RAID5", "type": "VMFS", "total_mb": 5968384,
         "free_mb": 626472, "used_mb": 5341912, "usage_percent": 89.5, "accessible": true}
      ],
      "hbas": [
        {"name": "vmhba2", "driver": "nfnic", "model": "Cisco UCS VIC Fnic Controller",
         "vendor": null, "firmware": null, "adapter_type": "Fibre Channel", "link_status": "offline",
         "wwpn": "20:00:00:27:E3:6C:A6:6E", "wwnn": "10:00:00:27:E3:6C:A6:6E",
         "link_speed_gbps": null, "port_type": "FibreChannel", "pci": "0000:0d:00.0", "bus": 13, "source": "esxi"}
      ],
      "summary": { "groups": [], "grand_total_gb": 16556 }
    },
    "network": {
      "dns_servers": ["10.x.x.251"],
      "default_gateways": [],
      "interfaces": [
        {"id": "vmk0", "name": "vmk0", "kind": "vmkernel", "mac": "00:27:e3:6c:a6:6d",
         "mtu": 1500, "speed_mbps": null, "link_status": "unknown", "is_primary": false,
         "addresses": [{"family": "ipv4", "address": "10.x.x.2",
                        "prefix_length": 24, "subnet_mask": "255.255.255.0", "gateway": null}]}
      ],
      "adapters": [
        {"name": "vmnic3", "driver": "nenic", "mac": "00:27:e3:6c:a6:6d", "link_status": "Connected",
         "speed_mbps": 10000, "duplex": "Full Duplex", "pci": "0000:0c:00.0",
         "adapter": "Cisco Systems Inc Cisco VIC Ethernet NIC"}
      ],
      "virtual_switches": [
        {"name": "vSwitch0", "num_ports": 128, "mtu": 9000,
         "pnics": ["vmnic4", "vmnic3"],
         "portgroups": ["10.x.x.0/24", "VM Network", "Trunk", "Management Network"]}
      ],
      "portgroups": [
        {"portgroup": "Management Network", "vlan_id": 64, "vswitch": "vSwitch0"}
      ],
      "summary": { "groups": [
        {"speed_mbps": null, "link_type": null, "quantity": 1, "link_up_count": 0}
      ] }
    },
    "users": [], "firmware": [], "power": null
  },
  "schema_version": "1"
}
```

> ESXi 의 `total_basis` 는 항상 `hypervisor_visible`. NIC 는 `adapters[]`(물리 vmnic) + `interfaces[]`(vmkernel) + `virtual_switches[]` + `portgroups[]` 로 나뉜다. FC HBA 는 `storage.hbas[]`.

---

## redfish-gather — success (Dell PowerEdge R740 / iDRAC9)

```json
{
  "target_type": "redfish",
  "collection_method": "redfish_api",
  "ip": "10.x.x.162",
  "hostname": "R740-1",
  "vendor": "dell",
  "status": "success",
  "sections": {
    "system": "not_supported", "hardware": "success", "bmc": "success",
    "cpu": "success", "memory": "success", "storage": "success",
    "network": "success", "firmware": "success", "users": "not_supported",
    "power": "success"
  },
  "diagnosis": {
    "reachable": true, "port_open": true, "protocol_supported": true,
    "auth_success": true, "failure_stage": null, "failure_reason": null,
    "details": {
      "channel": "redfish", "adapter_candidate": "redfish_dell_idrac9",
      "checked_ports": [443], "selected_port": 443, "redfish_version": "1.6.0",
      "product": "Integrated Dell Remote Access Controller", "systems_uri": "/redfish/v1/Systems"
    }
  },
  "meta": {
    "started_at": "2026-04-01T04:35:36Z", "finished_at": "2026-04-01T04:37:22Z",
    "duration_ms": 106000, "adapter_id": "redfish_dell_idrac9",
    "adapter_version": "1.0.0", "ansible_version": "2.20.3"
  },
  "correlation": {
    "serial_number": "CNIVC009CP0282", "system_uuid": "4c4c4544-0042-4a10-8038-b2c04f303333",
    "bmc_ip": "10.x.x.162", "host_ip": "10.x.x.162"
  },
  "errors": [],
  "data": {
    "system": {
      "os_family": null, "distribution": null, "version": null, "kernel": null,
      "architecture": null, "uptime_seconds": null, "selinux": null, "fqdn": "R740-1"
    },
    "hardware": {
      "vendor": "Dell Inc.", "model": "PowerEdge R740", "serial": "CNIVC009CP0282",
      "uuid": "4c4c4544-0042-4a10-8038-b2c04f303333", "sku": "2BJ8033",
      "bios_version": "2.21.2", "bios_date": null, "power_state": "On", "health": "Critical",
      "oem": {
        "bios_release_date": "02/19/2024", "current_rollup_status": "OK",
        "cpu_rollup_status": "OK", "storage_rollup_status": "OK",
        "chassis_service_tag": "2BJ8033", "express_service_code": "5050978671",
        "estimated_exhaust_temp": 29
      }
    },
    "bmc": {
      "name": "iDRAC", "firmware_version": "4.00.00.00", "model": "14G Monolithic",
      "manager_type": "BMC", "health": "OK", "ip": "10.x.x.162", "oem": {}
    },
    "cpu": {
      "sockets": 2, "cores_physical": 24, "logical_threads": 24,
      "model": "Intel(R) Xeon(R) Silver 4214 CPU @ 2.20GHz", "max_speed_mhz": 4000, "architecture": null,
      "summary": { "groups": [
        {"model": "Intel(R) Xeon(R) Silver 4214 CPU @ 2.20GHz", "sockets": 2, "cores_per_socket": 12, "total_cores": 24}
      ] }
    },
    "memory": {
      "total_mb": 655360, "total_basis": "physical_installed", "installed_mb": 655360,
      "slots": [
        {"id": "DIMM.Socket.A1", "name": "DIMM A1", "capacity_mib": 32768, "type": "DDR4",
         "speed_mhz": 2400, "manufacturer": "Samsung", "serial": "355C2040",
         "part_number": "M386A4G40DM1-CRC", "health": "OK"}
      ],
      "summary": { "groups": [
        {"unit_capacity_gb": 32, "type": "DDR4", "quantity": 20, "group_total_gb": 640}
      ], "grand_total_gb": 640 }
    },
    "storage": {
      "filesystems": [], "datastores": [], "infiniband": [], "hbas": [],
      "physical_disks": [
        {"id": "Disk.Bay.0:Enclosure.Internal.0-1:RAID.Slot.6-1", "device": "Solid State Disk 0:1:0",
         "model": "MZ7KH480HAHQ0D3", "serial": "S5CNNA0MC03697", "total_mb": 457862,
         "media_type": "SSD", "protocol": "SATA", "health": null,
         "failure_predicted": false, "predicted_life_percent": 90}
      ],
      "controllers": [
        {"id": "RAID.Slot.6-1", "name": "PERC H330 Adapter", "health": null,
         "drives": [
           {"device": "Solid State Disk 0:1:0", "model": "MZ7KH480HAHQ0D3", "total_mb": 457862,
            "media_type": "SSD", "protocol": "SATA", "health": null}
         ]}
      ],
      "logical_volumes": [
        {"id": "Disk.Virtual.0:AHCI.Slot.2-1", "name": "RAID1_OS", "controller_id": "AHCI.Slot.2-1",
         "member_drive_ids": ["Disk.Direct.0-0:AHCI.Slot.2-1", "Disk.Direct.1-1:AHCI.Slot.2-1"],
         "raid_level": "RAID1", "total_mb": 228872, "health": "OK", "state": "Enabled", "boot_volume": false}
      ],
      "summary": { "groups": [
        {"unit_capacity_gb": 447, "media_type": "SSD", "protocol": "SATA", "quantity": 2, "group_total_gb": 894},
        {"unit_capacity_gb": 1788, "media_type": "SSD", "protocol": "SAS", "quantity": 4, "group_total_gb": 7152}
      ], "grand_total_gb": 8492 }
    },
    "network": {
      "dns_servers": [], "default_gateways": [],
      "interfaces": [
        {"id": "NIC.Integrated.1-1-1", "name": "System Ethernet Interface", "kind": "server_nic",
         "mac": "F0:D4:E2:E6:47:0C", "mtu": null, "speed_mbps": 1000,
         "link_status": "up", "is_primary": false, "addresses": []}
      ],
      "summary": { "groups": [
        {"speed_mbps": 1000, "link_type": null, "quantity": 2, "link_up_count": 2},
        {"speed_mbps": 10240, "link_type": null, "quantity": 2, "link_up_count": 2}
      ] }
    },
    "users": [],
    "firmware": [
      {"id": "Current-159-2.21.2", "name": "BIOS", "version": "2.21.2", "updateable": true, "component": "159"}
    ],
    "power": {
      "power_supplies": [
        {"name": "PS2 Status", "model": "PWR SPLY,750W,RDNT,ARTESYN", "serial": "PHARP009CM01M2",
         "manufacturer": "DELL", "power_capacity_w": 750, "firmware_version": "00.1B.53",
         "health": "OK", "state": "Enabled"}
      ],
      "power_control": {
        "power_consumed_watts": 261, "power_capacity_watts": 806, "interval_in_min": 1,
        "min_consumed_watts": 260, "avg_consumed_watts": 260, "max_consumed_watts": 261
      }
    }
  },
  "schema_version": "1"
}
```

> Redfish 채널은 `system` / `users` 가 보통 `not_supported` (OS 정보는 OS 채널 담당). 신세대 모델(iDRAC10 / iLO7 등)은 `memory.slots[].base_module_type`, `hardware.tpm`, `network.adapters[]` / `network.ports[]`, `firmware[].category`, `power.summary` 등 더 풍부한 필드를 채운다 — `schema/output_examples/redfish_dell_idrac10.jsonc` 참조.

> **멀티노드 (CSUS / Superdome RMC)**: HPE Compute Scale-up Server 처럼 RMC 가 여러 파티션을 관리하는 장비는 `data.multi_node` (Additive 컨테이너) 에 partitions / managers / chassis 가 추가로 채워진다 — `schema/output_examples/redfish_hpe_csus_3200.jsonc` 참조.

---

## partial / failed / not_supported

부분 성공·실패·미지원 시나리오는 `schema/examples/` 에 1대씩 수록:

| 파일 | 채널 | status | 의미 |
|------|------|--------|------|
| `os_partial.json` | os | partial | 일부 섹션만 `failed` (예: storage 만 실패) |
| `redfish_failed.json` | redfish | failed | protocol 단계 실패 — 모든 supported 섹션 `failed` |
| `redfish_not_supported.json` | redfish | failed | Redfish 미지원 장비 (구세대 추정) — 모든 섹션 `not_supported` |

failed/partial 응답도 envelope 13 필드를 모두 채우며, `diagnosis.failure_stage` / `failure_reason` 에 어디서 막혔는지 기록된다.

---

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| 모든 필드 의미 사전 (envelope 13 + sections 10 + field 83) | [20_json-schema-fields.md](20_json-schema-fields.md) |
| 호출자 입력 형식 | [05_inventory-json-spec.md](05_inventory-json-spec.md) |
| 실패 시 envelope 동작 | [08_failure-handling.md](08_failure-handling.md) |

## 자주 헷갈리는 점

| 질문 | 답 |
|------|----|
| `data.bmc.ip` 와 envelope 의 `ip` 가 다를 수 있나요? | 네. envelope 의 `ip` 는 호출자가 보낸 IP (보통 BMC IP), `data.bmc.ip` 는 BMC 가 자체 보고하는 IP 로 같은 의미지만 출처가 다름. |
| `vendor` 가 `null` 인 이유? | OS 채널은 vendor 가 envelope 최상위에 채워지지 않음 (`null`). ESXi / Redfish 채널만 자동 감지. |
| `status: success` 인데 errors[] 에 메시지가 있어요 | 정상 (rule 13 R8 시나리오 B). 비치명 경고 (예: dmidecode fallback 사용) 가 errors[] 에 기록될 수 있음 — sections 가 모두 success/not_supported 면 envelope status 는 success. |
| `diagnosis` 안에 `details` 가 채널마다 다른 키를 가져요 | 의도된 동작. `details` 는 채널별 추가 진단 정보 (os=detected_os, esxi=vsphere_endpoint/auth, redfish=redfish_version/product) 를 담는 free-form dict. 공통 6필드(reachable/port_open/protocol_supported/auth_success/failure_stage/failure_reason)는 항상 고정. |
