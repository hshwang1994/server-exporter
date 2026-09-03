# 2026-09-03 — OS(Linux/Windows) / ESXi 전수 검수 후속 실장비 검증

> 대상 커밋: `1fb2ae16`(1차) → `0076ca67`(실장비 후속 4건 정정). Jenkins `clovirone-server-gather`(Jenkinsfile_portal, `*/main`)
> Agent: `jenkins-agent-ops`(loc=git, ansible-core 2.20.3). Callback URL 은 더미(192.0.2.1) → 빌드 결과는 UNSTABLE 이지만
> Gather / Validate Schema 는 통과. 원본 envelope 은 `tests/evidence/2026-09-03-live/*.json` 에 그대로 보존.

## 1. 실행 이력

| 빌드 | 커밋 | 대상 | 결과 |
|---|---|---|---|
| #190 | `1fb2ae16` | os: 10.100.64.161(RHEL 8.10, Python 3.6 → raw fallback), .165(RHEL 9.6), .96(Dell R760 베어메탈 Ubuntu 24.04), .120(Windows Server 2022) | 4/4 `status=success`, 계약 점검 이슈 4건(아래 §3) |
| #191 | `1fb2ae16` | esxi: 10.100.64.1 (ESXi 7.0.3, Cisco C220 M4) | `success`, 이슈 0 (값 2건 지적 — §3) |
| #192 | `0076ca67` | os: .96, .120 (재검증) | 2/2 `success`, 이슈 0 |
| #193 | `0076ca67` | esxi: 10.100.64.1 (재검증) | `success`, 이슈 0 |
| #194 | `0076ca67` | os: .167(Ubuntu 24.04), .163(RHEL 9.2), .169(Rocky 9.6) | §5 |
| #195 | `0076ca67` | esxi: 10.100.64.2 (esxi02 — `esxi_baseline.json` 대상 장비) | §5 |
| #196 | `d38bc31b` | os: .161(RHEL 8.10 raw VM), .96(R760) — 터보 가드 재검증 | 2/2 `success`, 이슈 0 (VM turbo `null`, R760 2400/4100 유지) |

점검 스크립트: 콘솔에서 envelope 을 추출해 hostname≠IP / hostname·fqdn 키 / UUID·MAC·WWN 표기 / cpu·runtime 키 /
enum / int 타입 / ESXi gateway·is_primary 등 25~42 항목을 자동 대조했다 (세션 스크래치, 저장소 밖).

## 2. 정정 전후 비교 (같은 장비 — 종전 빌드 #168 / #189 대비)

| 필드 | 장비 | 종전 (#168 / #189) | 이번 (#190~#193) |
|---|---|---|---|
| `system.hostname` | RHEL 9.6 VM | 키 없음 | `localhost` |
| `system.fqdn` | RHEL 8.10 raw ↔ RHEL 9.6 python | raw `localhost` / python `localhost.localdomain` (같은 설정, 다른 값) | 둘 다 `localhost.localdomain` |
| `system.fqdn` | R760 (도메인 없음) | `r760-6` (short 가 fqdn 자리에) | `null` |
| `sections.hardware` / `data.hardware` | Linux 4대 | `not_supported` / `null` — 모델·BIOS 유실 | `success` / `PowerEdge R760`, BIOS `2.3.5`, `2024-09-10` |
| `memory.slots[].serial / locator` | R760 | 키 없음 | `46FB6227` / `A1` (dmidecode 원문과 일치) |
| `cpu.max_speed_mhz` | R760 | `4100` (터보) | `2400` (SMBIOS Current Speed, 정격) + `turbo_max_mhz` `4100` |
| `cpu.max_speed_mhz` | ESXi esxi01 | 브랜드 문자열 `2200` | `2195` (cpuInfo.hz, vSphere 표시값과 동일) |
| `cpu.summary.groups[].l3_cache_kb` | RHEL 8.10 ↔ RHEL 9.6 (같은 CPU) | `56320` ↔ `225280` (lscpu 버전 차) | 둘 다 `56320` (소켓당) |
| `l2_cache_kb` | R760 | `49152` (24코어 합) | `24576` (소켓당) |
| `system.selinux` | RHEL VM | `enabled` | `enforcing` |
| `runtime.firewall_state` | RHEL VM | `running` (도구 원문) | `active` |
| `network.default_gateways` / `is_primary` | ESXi | `[]` / 전부 false | `10.100.64.254` / vmk0 true, `addresses[].gateway` 채움 |
| `storage.summary.grand_total_gb` | ESXi | 16556 (datastore 합) | 16684 (LUN 합, OS 와 같은 기준) |
| `memory.summary.grand_total_gb` | ESXi 1 TB | 1023 (floor) | 1024 |
| `network.adapters[]` | ESXi | name/driver/pci 만 | OS 와 같은 키 + pciDevice 제조사/모델 |
| `network.adapters[]` | Windows | `[]` | 6개 (PCI 주소·제조사·드라이버 버전) |
| `interfaces[].mac` | Windows | `00-50-56-84-C9-5F` | `00:50:56:84:c9:5f` (팀 멤버 포함) |
| `interfaces[].id` | Windows | `vmxnet3 Ethernet Adapter #6` | `Ethernet0` (+ `description`) |
| IPv6 | Windows | 미수집 | link-local 수집, zone(`%23`) 제거 |
| `filesystems[].total_mb` | Windows | `101684.0` (float) | `101683` (int) |
| `physical_disks[].health` | Windows | `healthy` | `OK` |
| `system.kernel` | Windows | `20348` (성공 시) / 실패 시 `"None"` | `20348` (없으면 null) |
| `ntp_synchronized` | ESXi | `true`(ntpd 실행 여부를 오기) | `null` (API 미제공) |
| `hosting_type` | R760 (Ubuntu python) | `baremetal` (OEM 목록 일치했던 경우) | `baremetal` (OEM 목록 없이 systemd-detect-virt) |

## 3. 실장비에서만 드러난 것 (렌더 테스트가 못 잡은 4건 → `0076ca67`)

| # | 현상 (빌드) | 원인 | 정정 |
|---|---|---|---|
| L1 | R760 `cpu.max_speed_mhz=null` (#190) | cpufreq `base_frequency` 부재 + 브랜드 문자열 `INTEL(R) XEON(R) SILVER 4510` 에 GHz 표기 없음 | SMBIOS Type 4 `Current Speed`/`Max Speed` 를 3순위 fallback (별도 become task) → 2400 / 4100 (#192) |
| L2 | Windows 팀 멤버 NIC 4개 MAC 이 `00-50-56-84-B0-78` (#190) | 팀 토폴로지 보강(`build_windows_network`) 이 WADP 보조 맵의 원문 MAC 을 그대로 사용 | WADP emit 에서 소문자 colon 정규화 → 전 인터페이스 일치 (#192) |
| L3 | Windows IPv6 `fe80::…%23` (#190) | Windows 는 link-local 에 zone index 를 붙임 | 주소에서 `%zone` 제거 (#192) |
| L4 | ESXi 관리 vmk0 `link_status=down` (#191) | `vmware_host_facts` 가 vmk 링크 상태를 주지 않음 → `active` 부재 = down 으로 오판 | 수집에 쓴 IP 를 가진 vmk 는 `up`, 나머지 `unknown` (#193) |
| L5 | ESXi `max_speed_mhz=2194` (#191) | `cpuInfo.hz` 절삭 | 반올림 → 2195 (#193) |

## 5. 추가 수집 (#194 / #195, 커밋 `0076ca67`)

| 대상 | 결과 | 비고 |
|---|---|---|
| 10.100.64.163 | `status=failed`, `failure_stage=reachable`, `TCP_CONNECT_FAILED` | 장비 무응답(5986 timeout / 5985 No route / 22 timeout). **실패 envelope 이 새 계약대로**: `hostname=null`(IP 대체 없음), 11 섹션(지원 7 = failed, hardware 포함), 표준 1번 문장, data 뼈대 |
| 10.100.64.169 | `success`, 이슈 0 | lab 목록의 "Rocky 9.6" 이 아니라 **10.100.64.161(RHEL 8.10) VM 의 bond1 IP** — serial/UUID 가 .161 과 동일. 목록 정정 필요 |
| 10.100.64.167 | `success`, 이슈 0 | 마찬가지로 **10.100.64.165(RHEL 9.6) VM 의 bond1 IP** ("Ubuntu 24.04" 아님). `ubuntu_baseline.json` 대상 장비는 현재 lab 목록에 없다 |
| 10.100.64.2 (esxi02) | `success`, 이슈 0 | `esxi_baseline.json` 대상 장비. hostname `esxi02`, FC HBA 2포트 WWPN 소문자 colon(`20:00:00:27:e3:6c:a6:6e`), vendor `Cisco Corporation`(컨트롤러 PCI 제조사), UUID `9f0190b1-…` = Redfish `B190019F-…` 와 `uuid_equal` 일치 |

| # | 실장비에서만 드러난 것 (추가) | 정정 |
|---|---|---|
| L6 | VM 에서 SMBIOS `Max Speed` 2093 < 정격 2200 이 `turbo_max_mhz` 로 실림 (#194) | 정격 ≤ 터보일 때만 값 인정, 아니면 null — `d38bc31b`, #196 에서 VM `null` / R760 `4100` 확인 |

## 4. 남은 것

- **baseline 10건 미갱신**: `schema/baseline_v1/README.md` 는 "본 폴더 JSON 은 수정하지 않는다" 이고 rule 13 R4 는 실장비 검증 후 갱신
  절차를 둔다 — 두 정본이 충돌하므로 갱신 여부는 **사용자 결정**. 갱신에 쓸 원본 envelope 은 §5 까지 포함해
  `tests/evidence/2026-09-03-live/` 에 있다 (`rhel810_raw_fallback` ← .161, `windows_2022` ← .120, `ubuntu` ← .167, `esxi` ← .2).
- 미수집: Windows 2대째(10.100.64.135, 자격 미검증), ESXi 9.0 R760 5대(자격 미제공), Redfish 채널(이번 범위 밖).
- `ansible-playbook --syntax-check` 는 Windows 세션 제약으로 로컬 미실행 — Jenkins Agent 에서 실제 실행으로 대체됐다.
