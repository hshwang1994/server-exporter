# 2026-10-04 — Kernel 6.x 항목별 호환성 행렬 (최종 실행 지시 §8-1, production #76 P1 envelope 기준)

> 작성: 세션 서브에이전트(읽기 전용 — Jenkins GET · `git show`; 실장비 접속 0 · 추적 파일 수정 0). 원본은 세션 scratchpad `k6x/`. 판정 어휘 `실제 확인` / `fixture 확인` / `장치 부재` / `미확인` 은 §0-2 정의대로다. 계정 이름은 마스킹했다.

# k6x — Kernel 6.x 항목별 호환성 증거 매트릭스 (지시 §8-1)

- 작성일: 2026-10-04
- 성격: 읽기 전용 분석. 추적 파일 수정 0, 실장비 SSH 0. 한 일은 Jenkins 읽기(빌드 #76 callback body · 빌드 메타), 저장소 읽기, 로컬 pytest 실행(`-p no:cacheprovider`, 바이트코드 미생성)이다.
- 같은 폴더의 부속 파일: `prod76_body.json`(callback body 원본) · `prod76_build_api.json`(빌드 메타) · `extract76.py` / `extract76_out.txt`(호스트별 전체 추출) · `fieldstatus76.py` / `fieldstatus76_out.md`(필드 상태표) · `errors76_out.md`(호스트별 errors 표)
- 대상 호스트
  - Kernel 6.12 = `10.100.64.37` · `.38` (RHEL 10.2, VMware VM)
  - Kernel 6.8 = `.156` (Ubuntu 24.04 VM) · `.96` · `.95` (Ubuntu 24.04, Dell R760 베어메탈)
  - 대조군 = `.161` (RHEL 8.10 · 4.18 · python 3.6.8 → raw fallback) · `.162` · `.163` (RHEL 9.2 / 9.6 · 5.14)

## 0. 증거 기반과 판정 어휘

### 0-1. 증거 기반

| 증거 | 내용 |
|---|---|
| 실데이터 | production Job `clovirone-cicd/clovirone-server-gather` **#76**: result SUCCESS, 85.9 s, 시작 2026-10-04T10:18:06Z, checkout `1f72507124bec025116a7ad7b6e2636d6ea9a7e0` (`refs/remotes/origin/production`), loc=git, target_type=os. envelope 8개(`gatherInfoJson[]`), 전부 status=success. |
| #76 이 돌린 코드 = 아래 task 라인 | production P1 `1f725071` 은 main `ce50ccf7` 의 runtime-only 트리다. `os-gather/tasks/linux/*.yml` 8개를 main 과 줄 단위로 비교하면 차이는 주석뿐이다(shell 주석 줄 · Jinja 주석 · timeout 줄의 후행 주석). 실행 로직은 같다. `git diff ce50ccf7 HEAD -- os-gather filter_plugins common lookup_plugins callback_plugins adapters schema` 는 비어 있다(HEAD `b3585c23`). 그래서 이 문서의 라인 번호는 HEAD 기준이며 #76 이 실행한 로직과 같다. |
| 핵심 수정이 #76 에 들어 있나 | IEC 단위 환산(`tib/gib/mib/kib`)은 P1 `gather_system.yml` 55·87행, driver_map VID 파서(`5a60d420`)는 P1 `gather_network.yml` 127행에서 확인했다. |
| 참조 캡처 | `tests/reference/os/` 2026-04-28 실캡처: `rhel-baremetal/10_100_64_96`(디렉터리명과 달리 **Ubuntu 24.04 · 6.8.0-88-generic · R760**) · `ubuntu2404/10_100_64_167`(6.8.0-107-generic VM) · `rhel810`(4.18) · `rhel920` · `rhel960` · `rocky960`(5.14) · `win2022`. **RHEL 10 디렉터리 없음.** |
| 로컬 테스트 실행(2026-10-04) | Linux 관련 9개 파일 259 passed · 1 skipped(`test_nic_block_reads_driver_link_and_any_master` — Windows 에서 symlink 생성 권한 없음). C3~C10 관련 18개 파일 665 passed(267 + 398). 실패 0. (Python 3.13.15 · pytest 9.1.1 · Windows, `sh`/`awk` = Git for Windows) |
| 수집 계정 | 8개 호스트 모두 `<비루트 수집 계정>`(uid 1000)의 `users[].last_access_time` 이 해당 빌드의 `started_at ~ finished_at` 안에 있고 root 는 null 이다 → 수집은 **비루트 계정**이며 become 은 system/runtime raw 에서만 쓴다(정황 증거). |

### 0-2. 판정 어휘

| 라벨 | 이 문서에서의 뜻 |
|---|---|
| `실제 확인` | #76 envelope 에 값이 채워져 있고 내부 정합이 맞다(예: DIMM 용량 합 == installed_mb). 해당 section 에 errors[] 가 없다. |
| `fixture 확인` | 파서/수집 스크립트를 **6.x 모양의 입력**으로 돌리는 단위 테스트가 있다. 괄호로 입력 종류를 적는다. (6.8 실캡처) = tests/reference/os 의 6.8.0-88 / -107 캡처, (6.12 모사) = RHEL 10.2 출력을 흉내 낸 합성. 4.18/5.14 실캡처나 커널 비특정 합성은 **보조 근거**일 뿐 이 라벨의 근거로 쓰지 않는다. |
| `장치 부재` | 그 호스트 군이 해당 장치를 갖고 있지 않고(VM 등) envelope 값이 비어 있으며 errors[] 가 없다. 빈 값이 기대 동작이다. |
| `미확인` | 실데이터도 6.x fixture 도 그 항목을 검증하지 않는다. 수집 경로 자체가 없는 항목도 여기에 둔다. |

한 칸에 라벨이 둘이면 둘 다 성립한다. 하위 경로마다 판정이 다르면 항목 안에서 나눠 적었다. 값을 모르면 "absent" 또는 "관측 불가"라고 적고 추정으로 채우지 않았다.

## 1. 명령 → 항목 → task 파일

Linux 수집은 `os-gather/site.yml` Linux play 가 `preflight → adapter 선택 → gather_system → gather_cpu → gather_memory → gather_storage → gather_network → gather_users → gather_hba_ib` 순으로 include 한다(`site.yml` 282~322행).

**raw fallback 은 별도 파일이 없다.** `preflight.yml:58-66` 이 `_l_python_mode`(python_ok / python_missing / python_incompatible / raw_forced)를 정하고, python_ok 일 때만 `ansible.builtin.setup`(`gather_system.yml:170-179`)과 식별자 진단(`build_identifier_diagnostics.yml`)이 더해진다. 나머지 수집 스크립트는 두 경로가 같다(각 파일 상단 2026-09-03 주석). `preflight.yml` 의 `_l_has_*` 플래그는 preflight 밖에서 쓰이지 않는다(grep 0).

| 명령 / 경로 | 항목 | task 파일:라인 | 권한 · 비고 |
|---|---|---|---|
| `/sys/class/dmi/id/` 의 product_serial · product_uuid · sys_vendor · product_name · bios_version · bios_date | system/hardware 식별 | `gather_system.yml:222-230`(raw), direct-read 481·491(조건부) | become. python_ok 는 setup facts 1순위, 같은 raw 값이 fallback. **system 식별은 dmidecode 가 아니라 이 sysfs 와 setup facts 다.** |
| `/proc/meminfo`(MemTotal · MemAvailable) | memory.visible_mb · free_mb | `gather_system.yml:58-59`(공유 DMI collector) | gather_memory.yml 이 MEM_TOTAL_KB / MEM_AVAIL_KB 를 파싱 |
| `dmidecode -t memory -t processor`(+ `sudo -n` 재시도) | memory.slots · installed_mb / cpu 클럭 3순위 | collector `gather_system.yml:74-163`(실행 76·82행), 파서 `gather_memory.yml:30-183`, Type 4 `gather_cpu.yml:53-64` | become. 호스트당 1회. 단위 kB/MB/GB/TB 와 kiB/MiB/GiB/TiB 를 모두 환산(99행, 129-135행) |
| `/proc/uptime`, `getenforce`, `systemd-detect-virt` | system.uptime_seconds · selinux · hosting_type | `gather_system.yml:209-221` | |
| `/proc/cpuinfo`(model name · vendor_id · cpu cores · physical id · processor 줄 수 · cache size) | cpu.model · manufacturer · sockets · cores · logical · L3 보조 | `gather_cpu.yml:21-27` | |
| `lscpu`(Socket(s) · Core(s) per socket · CPU max MHz · L2/L3 cache) | cpu 소켓/코어 보조 · 캐시 · turbo | `gather_cpu.yml:30-38`, 캐시 계산 124-161 | 합계 표기(N instances)와 구형 표기를 모두 받는다 |
| `/sys/devices/system/cpu/cpu0/cpufreq/` 의 base_frequency · cpuinfo_max_freq | cpu.max_speed_mhz · turbo | `gather_cpu.yml:28-29` | 1순위. 없으면 브랜드 문자열 `@ N.NNGHz`, 그다음 SMBIOS Type 4 |
| `lsblk -J -b -d -o NAME,SIZE,TYPE,ROTA,MODEL,TRAN,SERIAL,WWN`(+ 구형 `lsblk -b -d -n -o …`, `lsblk -dn -o NAME`, `lsblk -s -l -n -o NAME,TYPE`) | storage.physical_disks (NVMe 는 TRAN=nvme) | `gather_storage.yml:30-53, 68, 81`, 정규화 148-230, 분류 236-261 | LSBLK_RC / LSBLK_ERR 로 실패를 드러냄(C2) |
| `udevadm info --query=property`(ID_SERIAL_SHORT · ID_WWN), `findmnt -n -o SOURCE /`(+ /proc/mounts) | disks serial/wwn 보강 · is_os_disk | `gather_storage.yml:68-82` | |
| `/sys/block/*` 항목 수 | SYS_BLOCK_COUNT | `gather_storage.yml:55-65` | **오류 detail 전용**. 정상 수집에서는 envelope 에 나오지 않는다 |
| `lspci -Dmm` + `lspci -ks <slot>`(class: RAID · SATA · SAS · Serial Attached SCSI · Non-Volatile memory · SCSI storage · Mass storage) | storage.controllers[] (RAID · NVMe · SAS · SATA · SCSI) | `gather_storage.yml:85-96`, 분류 324-353 | Fibre Channel class 는 대상이 아니다 |
| `df -P -T -k`(timeout 20) | storage.filesystems | `gather_storage.yml:101-110` | |
| `lspci -k -mm -d ::0200` + `lspci -k -s <slot>` | network.adapters[] (vendor · model · driver · pci) | `gather_network.yml:212-220` | 도메인(0000:) 없는 slot |
| `ethtool -i <if>` — **bus-info 와 firmware-version 만** 읽음 | network.adapters[].firmware_version | `gather_network.yml:221-229` | driver version 줄은 읽지 않는다 |
| `/sys/class/net/<if>/` 의 address · mtu · speed · operstate · master · device · device/driver | interfaces mac · mtu · **speed(ethtool 아님)** · link, driver_map | `gather_network.yml:146-168, 185-210` | |
| `ip -j addr` > `ip -o addr` > `ifconfig -a`, `ip -o -4/-6 addr`, `ip route show default`, resolvectl · resolv.conf | addresses · gateway · dns | `gather_network.yml:122-132, 171-209` | |
| `/sys/class/net/*/bonding/*`, `/proc/net/bonding/*`, `ip -d link show`(bond_slave state) | network.bonds[] | `gather_network.yml:30-79` | /proc/net/bonding 은 world-readable |
| `/proc/net/vlan/config`, `ip -d link show`(vlan protocol … id) | interfaces[].vlan_id · vlan_parent | `gather_network.yml:80-93` | /proc/net/vlan/config 는 root 전용이라 `ip -d link` 가 실제 소스 |
| `/proc/net/vlan/<if>` | network.driver_map[].vlan_id | `gather_network.yml:157-160` | network raw 는 **become 없음** → 부가 관찰 O-1 |
| `/sys/class/net/*/bridge`, `brif/*`, `*/team` | network.bridges[] · teams[] | `gather_network.yml:94-116` | |
| `/sys/class/fc_host/host*/` 의 port_name · node_name · symbolic_name · port_state · speed · device/driver … | storage.hbas[] (WWPN · WWNN) | `gather_hba_ib.yml:39-69` | 읽기 실패는 ERR 줄 → errors[] 1건 |
| `/sys/class/infiniband/*/` 의 node_guid · fw_ver · hca_type · board_id · ports/*/state · rate · gids/0 | storage.infiniband[] | `gather_hba_ib.yml:74-91` | |
| **(없음)** multipath · nvme-cli · modinfo · lsscsi · smartctl · RAID CLI(storcli · perccli · ssacli) · ibstat | multipath · driver 버전 · RAID 심화 · 디스크 health · IB 도구 | production 코드에 **호출 0건**(grep, tests · docs 제외). 문자열로는 `gather_storage.yml:20` 주석(multipath "보류")과 schema/field_dictionary.yml 설명(smartctl · ibstat)에만 나온다 | NVMe 는 nvme-cli 가 아니라 lsblk TRAN=nvme 와 lspci class 로만 식별. 디스크 health 는 Linux 에서 설계상 null(field_dictionary: smartctl 도입 시 채움) |

## 2. 항목 × 분류 (a)

### 2-1. 요약표

| # | 항목 | Kernel 6.12 (`.37` `.38` · RHEL 10.2 VM) | Kernel 6.8 (`.156` VM · `.96` `.95` R760 베어메탈) |
|---|---|---|---|
| 1 | /sys 사용 | `실제 확인`(dmi/id · class/net) · `장치 부재`(fc_host · infiniband) · `미확인`(cpufreq 유무 — 관측 불가) | `실제 확인`(dmi/id · class/net · bonding · bridge) + `fixture 확인`(dmi/id 파서 — 6.8 모사) · `장치 부재`(fc_host · infiniband) · `미확인`(cpufreq — 관측 불가) |
| 2 | /proc 사용 | `실제 확인`(meminfo · uptime · cpuinfo) · `장치 부재`(net/bonding · net/vlan) | `실제 확인`(meminfo · uptime · cpuinfo · net/bonding). net/vlan 은 config 가 root 전용 → `ip -d link` 가 실제 소스. 장치별 `/proc/net/vlan/<if>` 는 [WARN] 실제 VLAN 장치에서 null → 부가 관찰 O-1 |
| 3 | dmidecode (system/memory) | `실제 확인` + `fixture 확인`(6.12 모사). system 식별은 dmidecode 가 아니라 sysfs | `실제 확인` + `fixture 확인`(6.8 실캡처) |
| 4 | lsblk / storage disks | `실제 확인` | `실제 확인` + `fixture 확인`(6.8 실캡처) |
| 5 | lspci (storage controller · NIC) | `실제 확인` (SAS/SCSI 계열 컨트롤러는 잡히지만 **FC HBA 는 lspci 로 찾지 않음** — 13번) | `실제 확인` |
| 6 | ethtool (NIC driver/speed) | speed · driver: `실제 확인`(sysfs · lspci 경유) / `ethtool -i`(firmware-version): `미확인` | `실제 확인`(R760: firmware-version 채움) |
| 7 | CPU 토폴로지 (sockets/cores/threads) | `실제 확인` | `실제 확인` |
| 8 | Memory (DIMM slots/size) | `실제 확인` + `fixture 확인`(6.12 모사) | `실제 확인` + `fixture 확인`(6.8 실캡처) |
| 9 | Storage RAID controller | `장치 부재` | `실제 확인`(컨트롤러 식별만 — drives/health/논리볼륨은 Linux 계약 밖) |
| 10 | NVMe | `장치 부재` | `실제 확인` + `fixture 확인`(6.8 실캡처 lsblk) |
| 11 | multipath | `미확인`(수집 경로 없음) | `미확인`(수집 경로 없음) |
| 12 | NIC (interfaces/bonding/vlan) | interfaces `실제 확인` · bonding/vlan/bridge/team `장치 부재` | interfaces · bonding · vlan · bridge `실제 확인` · team `장치 부재` · driver_map.vlan_id 는 [WARN] O-1 |
| 13 | HBA / FC / WWPN | `장치 부재` | `장치 부재` |
| 14 | Driver versions (modinfo / ethtool -i) | driver **이름** `실제 확인` · driver **버전** `미확인`(수집 경로 없음) | 동일 |
| 15 | InfiniBand | `장치 부재` | `장치 부재` |

6.12 요약: `실제 확인` = 3 · 4 · 5 · 7 · 8 과 1 · 2 · 6 · 12 의 일부. `장치 부재` = 9 · 10 · 13 · 15 와 1 · 2 · 12 의 일부. `미확인` = 11 · 14 와 6(ethtool -i) · 1(cpufreq)의 일부.

### 2-2. 항목별 근거 (호스트 · 필드 · 값)

호스트 × 필드 전체 상태표는 3절, 원본 추출은 `extract76_out.txt` 에 있다.

#### (1) /sys 사용

- **dmi/id** `실제 확인`. `.37`: hardware 6/6 채움 — vendor "VMware, Inc." · model "VMware7,1" · bios_version "VMW71.00V.18227214.B64.2106252220" · bios_date "2021-06-25" · serial/uuid 존재. `.38` 은 구조가 같고 serial/uuid 만 다르다. 6.8: `.96` `.95` Dell Inc. / PowerEdge R760 / bios 2.3.5 / 2024-09-10, `.156` VMware, Inc. / VMware Virtual Platform / bios 6.00 / 2020-11-12. sections.hardware=success, errors[] 0. fixture: `tests/unit/test_linux_remote_consolidation.py` 가 `.96`(6.8.0-88 · R760) 모양의 합성 system raw stdout(OS_ID · KERNEL · DMI_* marker)으로 `_l_raw_sys` 파싱 불변과 식별자 resolve 를 고정한다(합성 · 6.8 모사). RHEL 10 모양의 system raw 입력은 없다.
- **class/net** `실제 확인`. `.37` ens192: mtu 1500 · speed_mbps 10000 · link up · driver_map ens192 → vmxnet3. `.96`: eno8303 1000 · bond 슬레이브 10000 · 링크 다운 NIC(eno8403 · eno12399np0 · eno12409np1)는 speed null(sysfs speed -1 처리).
- **cpufreq** `미확인`(관측 불가). 값은 3단 fallback(cpufreq → 브랜드 문자열 → SMBIOS Type 4)이 채운다. `.37` `.38` max_speed_mhz 2200 · turbo null, `.96` `.95` 2400 · 4100. raw 원본이 envelope 에 남지 않아 어느 단이 채웠는지, cpufreq 노드가 있었는지 알 수 없다. 최종 값은 타당하다.
- **/sys/block** — SYS_BLOCK_COUNT 는 lsblk 이상일 때 errors[].detail 에만 실린다. 정상 수집에서는 관측되지 않는다. 단위 테스트 `test_sys_block_count_excludes_loop_and_ram`(합성 트리)만 있다.
- **fc_host · infiniband** `장치 부재`. 8개 호스트 전부 hbas [] · infiniband [] 이고 ERR 로 인한 errors[] 가 없다. 파서 검증은 13 · 15번.

#### (2) /proc 사용

- **meminfo · uptime · cpuinfo** `실제 확인`. `.37`: memory.visible_mb 3652(MemTotal) · free_mb 2581(MemAvailable) · system.uptime_seconds 117326 · cpu.model "Intel(R) Xeon(R) CPU E5-2699 v4 @ 2.20GHz" · manufacturer Intel · sockets 2 · logical_threads 2. `.38`: visible 3652 · free 2580. fixture: `tests/e2e/test_linux_raw_scripts_shim.py` 가 `.96`(6.8.0-88)의 cmd_meminfo.txt · cmd_os_release.txt 로 raw 스크립트를 실행한다(`fixture 확인`, 6.8 실캡처).
- **/proc/net/bonding** 6.12 `장치 부재`(bonds []) / 6.8 `실제 확인`. `.96` `.95` bonds[bond0].slaves[] 에 mii_status up · perm_hwaddr · speed_mbps 10000 · **link_failure_count 0**. link_failure_count 는 /proc/net/bonding 만 주는 필드라 이 경로가 읽혔다는 증거다.
- **/proc/net/vlan** — 6.12 `장치 부재`(VLAN 없음). 6.8 은 config 가 root 전용(커널 v6.8 `net/8021q/vlanproc.c` 가 `S_IFREG | 0600` 으로 생성)이라 interfaces[].vlan_id 는 `ip -d link` 에서 나오고(정상), 장치별 파일 읽기는 부가 관찰 O-1.
- **/proc/mounts** — findmnt 결과가 비었을 때만 쓰는 fallback 이라 envelope 로 관측되지 않는다. `test_linux_storage_markers.py` 의 합성 mounts 로 실행된다.

#### (3) dmidecode (system/memory)

- **memory(Type 16/17)** 6.12 `실제 확인`. `.37` `.38`: slots 1 — capacity_mb 4096 · type DRAM · speed_mhz null(`Speed: Unknown`) · manufacturer "VMware Virtual RAM" · part_number VMW-4096MB · serial 00000001 · locator "RAM slot #0". installed_mb 4096 == total_mb 4096 == slots 합, total_basis physical_installed, memory errors[] 0. 이 두 호스트는 IEC 수정 전에는 SLOT 0 이던 대상이다(main #11 재현 → #20 raw_head `Size: 4 GiB` → #29 · #48 해결, `tests/evidence/2026-10-04-test-server-roster.md` §1 표의 18번 행). #76 은 production 트리에서 같은 결과를 확인한 것이다.
- 6.8 `실제 확인`: `.96` slots 8 × 16384 MB DDR5 4400 MT/s(SK hynix, A1~A4 · B1~B4) 합 131072 == installed_mb. `.95` slots 4 × 65536 MB DDR5 4400(A1 · A2 · B1 · B2) 합 262144 == installed_mb. `.156` slots 1 × 4096 MB(manufacturer · part · serial null).
- **processor(Type 4)** — CPU 클럭 3순위. `.37` 은 브랜드 문자열이 먼저 채워 관측되지 않는다. fixture: `test_linux_smbios_clock_fallback_plausibility`(R760 2400/4100, VMware 가상 SMBIOS 30000 MHz 자리표시자 → null), `test_memory_module_current_speed_is_not_read_as_cpu_clock`.
- **fixture** — 6.12 모사: `test_linux_memory_parser.py::test_dmidecode_36_iec_units_are_parsed`(합성: Type 16 Maximum Capacity 5 GiB · Type 17 `Size: 4 GiB` / `No Module Installed` / `512 KiB`; 기대 MEM_PHYS_MB 4096 · SLOT 1 · MEM_DEVICE_RECORDS 3 · errors[] []). 6.8 실캡처: `test_reference_capture_matches_independent_oracle` 가 `rhel-baremetal`(R760 · 16 GB × 8)과 `ubuntu2404`(8 GB × 1)를 독립 oracle 과 대조하고, `test_r760_reports_configured_speed_not_rated_speed` 가 4400 MT/s 를 고정한다. 단위 표기는 참조 캡처 전부 `GB`/`MB` 이며 IEC 표기 캡처는 저장소에 없다(M5).

#### (4) lsblk / storage disks

- 6.12 `실제 확인`. `.37` `.38`: physical_disks 1 — /dev/sda · model "Virtual disk" · total_mb 30720 · media_type HDD · protocol null · serial/wwn null · is_os_disk true. storage.summary 30 GB, filesystems 3(`/dev/mapper/rhel-root` xfs · `/dev/sda2` /boot · `/dev/sda1` /boot/efi vfat), storage errors[] 0 → lsblk JSON 정상 경로. VM 가상 디스크는 ROTA=1 이라 HDD 로 표기된다(플랫폼 특성 — 4월 참조 캡처도 rota true/1, 6.x 이슈 아님). protocol null 은 PVSCSI 가 TRAN 을 비우기 때문이다. physical_disks[].health 는 8개 호스트 전부 null 인데 Linux 에서 설계상 미수집이다(field_dictionary: smartctl 도입 시 채움).
- 6.8 `실제 확인`: `.96` physical_disks 3 — sda(model "RAID" · 10984704 MB · SSD · wwn 있음) · sdb(model "RAID" · 1715328 MB · HDD) · nvme0n1(Dell BOSS-N1 · 457798 MB · SSD · protocol NVMe · is_os_disk true). `.95` 1 — nvme0n1. `.156` 2 가상 디스크.
- `fixture 확인`(6.8 실캡처): `test_linux_storage_markers.py::test_reference_json_builds_physical_disks` 가 tests/reference 의 lsblk 캡처 6개(그중 6.8 은 `rhel-baremetal` · `ubuntu2404`)를 운영 열 모양으로 바꿔 독립 oracle 과 대조하고, `test_reference_json_through_raw_script` 가 `rhel-baremetal`(NVMe tran=nvme · RAID model)을 실제 sh+awk 로 실행한다. RHEL 10 의 lsblk 캡처는 없다.

#### (5) lspci (storage controller · NIC 탐지)

- 6.12 `실제 확인`. `.37`: storage.controllers 2 — 0000:02:00.0 "SATA AHCI controller"(VMware · ahci · SATA), 0000:03:00.0 "PVSCSI SCSI Controller"(VMware · vmw_pvscsi · SAS — PCI class "Serial Attached SCSI controller [0107]" 기준, 4월 참조 캡처 cmd_lspci_nn.txt 와 일치). network.adapters 1 — 0b:00.0 "VMXNET3 Ethernet Controller"(VMware · vmxnet3). lspci 가 RHEL 10.2 에도 있고 동작한다(두 목록이 채워졌고 lspci stderr 경고가 없다). SAS/SCSI 계열 컨트롤러(HBA 포함)는 controller_type SAS/SCSI 로 잡히지만 Fibre Channel class 는 정규식에 없어 **FC HBA 는 lspci 로 찾지 않는다**(sysfs fc_host 만 — 13번).
- 6.8 `실제 확인`: `.96` controllers 4(Sapphire Rapids SATA AHCI ×2 · "88NR2241 Non-Volatile memory controller"/nvme · "Fusion-MPT 24GSAS/PCIe SAS40xx/41xx"/mpi3mr RAID), adapters 6(BCM5720 tg3 ×2 · BCM57414 bnxt_en ×2 · XXV710 i40e ×2). `.156` controllers 2(LSI Logic Parallel SCSI/mptspi → SCSI · SATA AHCI), adapters 1.
- fixture: **없음**. lspci 는 테스트 샌드박스에서 숨겨져 controllers[] 를 만드는 줄과 class → controller_type 분류가 어떤 입력으로도 단위 검증된 적이 없다. adapters 는 RHEL 8.10 raw stdout fixture(`tests/fixtures/os/net/rhel810_rawpath_stdout.txt`)의 ADAPTER 줄이 렌더 입력으로만 쓰인다(보조, 4.18).

#### (6) ethtool (NIC driver / speed)

- **speed** — ethtool 이 아니라 /sys/class/net/`<if>`/speed. 6.12 `.37` 10000 `실제 확인`, 6.8 `.96` 1000 / 10000 / 링크 다운 null.
- **driver** — lspci -k 의 "Kernel driver in use" 와 /sys/class/net/`<if>`/device/driver 링크. `실제 확인`(6.12 vmxnet3 · 6.8 tg3 · bnxt_en · i40e).
- **ethtool -i**(firmware-version) 6.12 `미확인`: `.37` `.38` adapters[0].firmware_version null. vmxnet3 은 ethtool 이 설치돼 있어도 `firmware-version:` 이 비어 있어(2026-04-28 RHEL 9.6 · Ubuntu 24.04 VM 캡처) null 이 정상이지만, RHEL 10.2 에 ethtool 이 설치돼 있는지는 envelope 로 구분할 수 없다.
- 6.8 `실제 확인`: `.96` tg3 "FFV22.91.5 bc 5720-v1.39" · bnxt_en "229.2.52.0/pkg 22.92.06.10" · i40e "8.40 0x8000b1fb 20.5.16"(`.95` 도 tg3 · i40e 동일, 4월 `.96` 의 ethtool -i 캡처와 같은 값). ETHFW → firmware_version 매핑을 검증하는 단위 테스트는 없다(driver_map 테스트가 ETHFW 줄이 섞이지 않는지만 본다).

#### (7) CPU 토폴로지 (sockets / cores / threads)

- 6.12 `실제 확인`. `.37` `.38`: sockets 2 × cores_per_socket 1 = cores_physical 2, logical_threads 2, l2_cache_kb 256 · l3_cache_kb 56320(소켓당), model "Intel(R) Xeon(R) CPU E5-2699 v4 @ 2.20GHz", max_speed_mhz 2200, turbo null. 내부 정합(sockets × cps == cores_physical, logical == 2)이 맞다.
- 6.8 `실제 확인`: `.96` `.95` sockets 2 × 12 = 24, logical 48, l2 24576 KB · l3 30720 KB(소켓당), "INTEL(R) XEON(R) SILVER 4510", 2400 / 4100. `.156` 2 × 1 = 2.
- fixture: lscpu · /proc/cpuinfo 파서를 돌리는 테스트는 **없다**(터보 ≥ 정격 규칙, SMBIOS 클럭 fallback, 키 emit 검사만 있다). `tests/reference` 에 cmd_lscpu.txt · cmd_cpuinfo.txt 가 있지만 어떤 테스트도 읽지 않는다.

#### (8) Memory (DIMM slots / size)

3번과 같은 근거다. 6.12 `실제 확인` + `fixture 확인`(6.12 모사), 6.8 `실제 확인` + `fixture 확인`(6.8 실캡처). 합계 정합: `.37` `.38` 4096 == 4096, `.96` 131072, `.95` 262144, `.156` 4096, 대조군 `.161` `.162` `.163` 8192.

#### (9) Storage RAID controller

- 6.12 `장치 부재`: controllers 는 가상 SATA AHCI 와 PVSCSI 뿐이고 RAID class 가 없다.
- 6.8 `실제 확인`: `.96` `.95` controllers[0000:52:00.0] "PERC H965i Front"(Broadcom / LSI, model "Fusion-MPT 24GSAS/PCIe SAS40xx/41xx", driver mpi3mr, controller_type RAID). `.96` 은 PERC 가상 디스크 sda · sdb(model "RAID")도 보인다. `.95` 는 컨트롤러만 식별되고 PERC 뒤 디스크 정보는 없다(Linux 수집에 RAID CLI 가 없고, 있었는지 여부도 envelope 로 알 수 없다).
- **범위 한계** — controllers[].drives 와 health 는 8개 호스트 모두 비어 있고(0/0) logical_volumes 는 항상 []. field_dictionary 가 `storage.controllers[].drives[]` · `storage.logical_volumes[]` 를 Redfish 전용으로 선언하므로 설계상 Linux 계약 밖이다.
- fixture: **없음**(5번과 같은 이유).

#### (10) NVMe

- 6.12 `장치 부재`: NVMe 디스크도 Non-Volatile memory controller 도 없다.
- 6.8 `실제 확인`: `.96` `.95` physical_disks nvme0n1 "Dell BOSS-N1" · 457798 MB · SSD · protocol NVMe(lsblk TRAN=nvme) · wwn "eui.…" · serial 있음 · is_os_disk true. controllers[0000:01:00.0] "BOSS-N1 Monolithic" · model "88NR2241 Non-Volatile memory controller" · Marvell · driver nvme · controller_type NVMe.
- `fixture 확인`(6.8 실캡처): `test_reference_json_builds_physical_disks[rhel-baremetal]` 의 입력에 nvme0n1(tran nvme)이 들어 있어 protocol NVMe 가 oracle 과 일치한다. 컨트롤러 분류는 fixture 없음.
- nvme-cli 는 쓰지 않는다. `.96` 4월 캡처에서도 `nvme list` 는 rc 127(미설치)이었다.

#### (11) multipath

- `미확인`(전 커널). 수집 경로 자체가 없다: production 코드에 multipath 호출 0건, `gather_storage.yml:20` 주석이 "multipath 처리는 변경 없음 (보류)". 스키마에도 multipath 필드가 없다(absent). 테스트 harness 는 오히려 multipath 를 숨기는 목록에 둔다.
- 참고: `.96` 4월 캡처 `multipath -ll` 은 rc 0 · 출력 없음(맵 없음). 다중경로 호스트에서는 `lsblk -d` 가 경로 디스크를 각각 disk 로 낼 것으로 **추론**한다 — `schema/field_dictionary.yml` 의 is_os_disk 설명("RAID/LVM/multipath 는 멤버 디스크 모두 true")도 그 전제이지만, 실데이터 · 테스트 어느 쪽으로도 검증한 적이 없다.

#### (12) NIC (interfaces / bonding / vlan)

- **interfaces** 6.12 `실제 확인`: `.37` 1개(ens192 · ipv4 10.100.64.37/24 · gateway 10.100.64.254 · ipv6 link-local · is_primary true). 6.8 `실제 확인`: `.96` 10개, `.95` 7개, `.156` 1개.
- **bonding** 6.8 `실제 확인`: `.96` bonds[bond0] mode active-backup · active_slave enp190s0f0np0 · slaves 2(active/backup, mii up, 10000) · miimon 0 · lacp_rate slow · xmit_hash_policy layer2. interfaces[] 에는 bond_role master/slave · bond_slaves · slave_state 가 붙는다. `.95` 도 같은 구조. 6.12 `장치 부재`(bonds []).
- **vlan**(interfaces[].vlan_id / vlan_parent) 6.8 `실제 확인`: `.96` bond0.64 → 64 · bond0.656 → 656, `.95` bond0.64 → 64, vlan_parent bond0, 자체 IPv4 보유. 6.12 `장치 부재`.
- **bridge / team** 6.8 `실제 확인`(bridges: `.96` docker0 멤버 veth 4 · `.95` docker0 멤버 3). team 은 8개 호스트 모두 [] → `장치 부재`. 6.12 는 둘 다 `장치 부재`. (`.161` 의 virbr0 는 멤버 없는 bridge.)
- **driver_map[].vlan_id** — `.96` `.95` 의 VLAN 장치에서 null → 부가 관찰 O-1.
- fixture: bond/vlan/bridge/team 파서 테스트는 많지만 입력이 RHEL 8.10(4.18) · RHEL 9.6(5.14) 실캡처와 합성이다(`tests/fixtures/os/net/rhel810_*` · `rhel96_*` · `bond_vlan_realkernel_topo.txt`, `test_network_topology.py`, `test_os_network_render.py`). 6.x 입력은 없으므로 `fixture 확인` 라벨의 근거로 쓰지 않는다. 6.8 `.96` 의 `cmd_bonding.txt` 는 저장소에 있으나 어떤 테스트도 읽지 않는다.

#### (13) HBA / FC / WWPN

- 6.12 · 6.8 모두 `장치 부재`: 8개 호스트 전부 hbas [] 이고 fc_host 읽기 실패로 인한 errors[] 가 없다. `.96` 4월 lspci 목록에도 Fibre Channel 컨트롤러가 없다.
- 파서 검증은 합성뿐이다: `test_linux_hba_ib_markers.py`(Emulex LPe32002-M2 · WWPN `10:00:00:90:fa:1b:2c:3d` · 16 Gbit · fw 12.8.351.0 · ERR 규칙)와 `test_identity_normalizer.py::test_wwn_normalized_to_lower_colon`. 커널 비특정 sysfs ABI 이므로 `fixture 확인` 라벨의 근거로 쓰지 않았다. 실 FC HBA 장비는 lab 에 없다(LAB_INVENTORY 에 기록 없음).

#### (14) Driver versions (modinfo / ethtool -i)

- driver **이름**은 `실제 확인`: adapters[].driver · driver_map[].driver · controllers[].driver 가 8개 호스트에서 채워진다.
- driver **버전**은 `미확인`(전 커널): modinfo 호출이 없고 ethtool -i 는 bus-info 와 firmware-version 만 읽는다. field_dictionary 에 Linux driver 버전 필드가 없다(driver_version 은 Windows gather 에만 있다).
- 6.x 참고(구현 시 주의): `.96` 4월 ethtool -i 캡처에서 in-tree 드라이버 bnxt_en · tg3 · i40e 의 `version:` 은 커널 릴리스 문자열(`6.8.0-88-generic`)이다. vmxnet3 은 자체 버전(`1.7.0.0-k-NAPI` · `1.9.0.0-k-NAPI`)을 낸다.

#### (15) InfiniBand

- 6.12 · 6.8 모두 `장치 부재`: 8개 호스트 전부 infiniband [] 이고 ERR errors[] 없음. `.96` `.95` 의 BCM57414 는 RDMA 지원 NIC 이나 envelope 에 infiniband 항목은 없다(원인은 envelope 로 알 수 없음).
- 파서 검증은 합성뿐: `test_linux_hba_ib_markers.py`(mlx5_0 · 100 Gb/sec EDR · node_guid 0c42:a103:0012:3456 · hca_type MT4123 → Mellanox · board_id fallback). `tests/regression/test_hba_ib_canonical.py` 는 Linux baseline 이 빈 리스트라 사실상 통과만 한다.

### 2-3. tests/ grep 기록 (6.x · RHEL 10 · 장치 키워드)

`tests/reference/` · `tests/evidence/` · Redfish/ESXi fixture 는 제외하고 테스트 코드와 fixture 파일 이름만 적었다. 일치한다고 6.x 입력을 검증한다는 뜻은 아니다 — 해석 열을 본다.

| 키워드 | 파일 | 해석 |
|---|---|---|
| 6.12 | `tests/unit/test_linux_memory_parser.py` · `tests/unit/prodgen/test_verdict_evidence.py` | 앞의 것은 docstring(RHEL 10.2 · 6.12 DIMM 제보 재현 근거). 뒤의 것은 E2E 증거 계약용 합성 envelope(`kernel 6.12.0-55.el10`)이라 파서 테스트가 아니다 |
| 6.8. | `tests/unit/test_linux_remote_consolidation.py` | system raw 합성 stdout(`KERNEL=6.8.0-88-generic`, R760). 그 밖의 6.8 입력은 `tests/reference/os/rhel-baremetal` · `ubuntu2404` 캡처를 읽는 `test_linux_memory_parser.py` · `test_linux_storage_markers.py` · `test_linux_remote_consolidation.py` · `tests/e2e/test_linux_raw_scripts_shim.py` |
| el10 · RHEL 10 | `tests/unit/test_linux_memory_parser.py` · `tests/unit/prodgen/test_verdict_evidence.py` | 위와 같다. RHEL 10 **캡처 fixture 는 없다** |
| GiB | `tests/unit/test_linux_memory_parser.py` | IEC 단위 합성 입력(`test_dmidecode_36_iec_units_are_parsed`). `test_hpe_csus_multi_node.py` · `test_partition_normalize_grouping.py` 는 Redfish 라 무관 |
| nvme | `tests/unit/test_linux_storage_markers.py` | lsblk 캡처의 nvme0n1(tran nvme)과 /sys/block 이름. `test_firmware_category.py` 는 Redfish firmware 분류라 무관 |
| multipath | `tests/unit/linux_raw_harness.py` · `tests/unit/test_linux_storage_markers.py` | 샌드박스에서 **숨기는** 도구 목록에만 나온다(검증 아님) |
| fc_host | `tests/unit/test_linux_hba_ib_markers.py` · `tests/unit/test_identity_normalizer.py` | 앞의 것은 합성 sysfs 트리, 뒤의 것은 fc_host port_name 형식의 WWN 정규화 한 줄 |
| wwpn | Linux: `tests/unit/test_linux_hba_ib_markers.py` · Windows: `test_windows_storage_enum_render.py` · `test_windows_storage_powershell_static.py` · 공통 shape: `tests/regression/test_hba_ib_canonical.py` · Redfish: `test_fcoe_cna_not_fc_hba.py` · `test_csus_mirror_audit_fixes.py` · `test_hpe_dl380_audit_fixes.py` · `tests/integration/test_hpe_emulator_replay.py` | Linux 는 합성뿐이다 |
| ethtool | `tests/fixtures/os/README.md` | 설명 문구뿐이다. ethtool 실행 · 파싱 테스트 없음(`test_linux_hba_ib_markers.py` 는 ETHFW 줄이 driver_map 에 섞이지 않는지만 본다) |
| lspci | `tests/unit/linux_raw_harness.py` · `tests/unit/test_linux_storage_markers.py` · `tests/e2e/test_section_message_contract.py` · `tests/unit/test_errors_normalize.py` · `tests/fixtures/outputs/status_success_with_warnings.json` | 샌드박스에서 숨김, 문장 품질 검사, detail 정규화, 출력 예시. lspci 파싱 테스트 없음 |

## 3. 호스트 × 필드 상태 (#76 body 추출)

숫자는 배열 길이, `a / b` 는 항목별로 아래 표 왼쪽 열에 설명한 두 값이다. 배열이 비면 0 이고, 스키마에 필드가 없으면 `absent` 로 적었다. 열 순서는 Kernel 6.12(`.37` `.38`) · Kernel 6.8(`.156` `.96` `.95`) · 대조군(`.161` `.162` `.163`)이다.

| 항목 | .37 | .38 | .156 | .96 | .95 | .161 | .162 | .163 |
|---|---|---|---|---|---|---|---|---|
| kernel | 6.12.0-211.7.3.el10_2 | 6.12.0-211.7.3.el10_2 | 6.8.0-100-generic | 6.8.0-88-generic | 6.8.0-101-generic | 4.18.0-553.el8_10 | 5.14.0-284.11.1.el9_2 | 5.14.0-570.12.1.el9_6 |
| hosting_type | virtual | virtual | virtual | baremetal | baremetal | virtual | virtual | virtual |
| hardware.* (vendor/model/serial/uuid/bios_version/bios_date) 채움 | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 |
| cpu sockets x cores_per_socket = cores_physical / logical | 2x1=2 / 2 | 2x1=2 / 2 | 2x1=2 / 2 | 2x12=24 / 48 | 2x12=24 / 48 | 4x1=4 / 4 | 4x1=4 / 4 | 4x1=4 / 4 |
| cpu l2_kb / l3_kb (socket당) | 256 / 56320 | 256 / 56320 | 256 / 56320 | 24576 / 30720 | 24576 / 30720 | 256 / 56320 | 256 / 56320 | 256 / 56320 |
| cpu max_speed_mhz / turbo_max_mhz | 2200 / None | 2200 / None | 2200 / None | 2400 / 4100 | 2400 / 4100 | 2200 / None | 2200 / None | 2200 / None |
| memory slots 수 (합 MB == installed_mb) | 1 (합 4096 == 4096: True) | 1 (합 4096 == 4096: True) | 1 (합 4096 == 4096: True) | 8 (합 131072 == 131072: True) | 4 (합 262144 == 262144: True) | 1 (합 8192 == 8192: True) | 1 (합 8192 == 8192: True) | 1 (합 8192 == 8192: True) |
| memory slots[].type / speed_mhz | ['DRAM'] / ['None'] | ['DRAM'] / ['None'] | ['DRAM'] / ['None'] | ['DDR5'] / ['4400'] | ['DDR5'] / ['4400'] | ['DRAM'] / ['None'] | ['DRAM'] / ['None'] | ['DRAM'] / ['None'] |
| memory total_basis | physical_installed | physical_installed | physical_installed | physical_installed | physical_installed | physical_installed | physical_installed | physical_installed |
| storage.physical_disks 수 (NVMe protocol / model=RAID) | 1 (NVMe 0 / RAID 0) | 1 (NVMe 0 / RAID 0) | 2 (NVMe 0 / RAID 0) | 3 (NVMe 1 / RAID 2) | 1 (NVMe 1 / RAID 0) | 2 (NVMe 0 / RAID 0) | 2 (NVMe 0 / RAID 0) | 2 (NVMe 0 / RAID 0) |
| storage.physical_disks media_type | ['HDD'] | ['HDD'] | ['HDD'] | ['HDD', 'SSD'] | ['SSD'] | ['HDD'] | ['HDD'] | ['HDD'] |
| storage.controllers (type별) | {'SAS': 1, 'SATA': 1} | {'SAS': 1, 'SATA': 1} | {'SATA': 1, 'SCSI': 1} | {'NVMe': 1, 'RAID': 1, 'SATA': 2} | {'NVMe': 1, 'RAID': 1, 'SATA': 2} | {'SAS': 1, 'SATA': 1} | {'SAS': 1, 'SATA': 1} | {'SAS': 1, 'SATA': 1} |
| storage.controllers[].drives / health 채움 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| storage.hbas / infiniband / logical_volumes / datastores 수 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| storage.filesystems 수 | 3 | 3 | 1 | 5 | 4 | 3 | 3 | 4 |
| (multipath 필드) | absent (스키마·수집 없음) | absent (스키마·수집 없음) | absent (스키마·수집 없음) | absent (스키마·수집 없음) | absent (스키마·수집 없음) | absent (스키마·수집 없음) | absent (스키마·수집 없음) | absent (스키마·수집 없음) |
| network.interfaces 수 (speed_mbps 채움) | 1 (1) | 1 (1) | 1 (1) | 10 (7) | 7 (5) | 6 (6) | 6 (6) | 6 (6) |
| network.bonds / bridges / teams 수 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 1 / 1 / 0 | 1 / 1 / 0 | 0 / 1 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| interfaces[].vlan_id 채움 (값) | 0 ([]) | 0 ([]) | 0 ([]) | 2 ([64, 656]) | 1 ([64]) | 0 ([]) | 0 ([]) | 0 ([]) |
| network.adapters 수 (driver / firmware_version 채움) | 1 (1 / 0) | 1 (1 / 0) | 1 (1 / 0) | 6 (6 / 6) | 4 (4 / 4) | 6 (6 / 0) | 6 (6 / 0) | 6 (6 / 0) |
| network.driver_map 수 (driver 채움 / vlan_id 채움) | 1 (1 / 0) | 1 (1 / 0) | 1 (1 / 0) | 16 (6 / 0) | 51 (4 / 0) | 7 (6 / 0) | 6 (6 / 0) | 6 (6 / 0) |
| errors[] 수 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| status / failure_stage | success / None | success / None | success / None | success / None | success / None | success / None | success / None | success / None |
| gather_mode (python) | python_ok (3.12.13) | python_ok (3.12.13) | python_ok (3.12.3) | python_ok (3.12.3) | python_ok (3.12.3) | python_incompatible (3.6.8) | python_ok (3.9.16) | python_ok (3.9.21) |
| duration_s | 40.2 | 40.8 | 35.2 | 36.1 | 38.8 | 23.0 | 29.6 | 32.4 |

읽는 법:
- `.37` 과 `.38` 은 data 의 구조와 배열 길이가 같다(구조 비교 True). 값이 다른 leaf 는 mac · IP · serial · uuid · hostname · fqdn · uptime · free_mb · filesystems[0] 사용량뿐이다.
- 6.12 두 호스트에서 비어 있는 배열(hbas · infiniband · logical_volumes · bonds · bridges · teams)은 모두 VM 에 그 장치가 없어서이며 errors[] 가 없다.
- controllers[].drives · health 가 8개 호스트 전부 0 / 0 인 것은 Linux 계약 밖이라서다(2-2 (9)).
- driver_map 의 `vlan_id 채움` 이 `.96` `.95` 에서도 0 이라는 점이 O-1 이다.

## 4. 호스트별 errors[] (b)

| host | hostname | OS · kernel | gather_mode (python) | adapter | status | sections | errors[] | 소요 |
|---|---|---|---|---|---|---|---|---|
| .37 | tanzu-esxi01 | RedHat 10.2 · 6.12.0-211.7.3.el10_2 | python_ok (3.12.13) | os_linux_rhel | success | success 7 · not_supported 4 | **0** | 40.2 s |
| .38 | tanzu-esxi02 | RedHat 10.2 · 6.12.0-211.7.3.el10_2 | python_ok (3.12.13) | os_linux_rhel | success | success 7 · not_supported 4 | **0** | 40.8 s |
| .156 | cicd-gitlab | Ubuntu 24.04 · 6.8.0-100-generic | python_ok (3.12.3) | os_linux_ubuntu | success | success 7 · not_supported 4 | **0** | 35.2 s |
| .96 | r760-6 | Ubuntu 24.04 · 6.8.0-88-generic | python_ok (3.12.3) | os_linux_ubuntu | success | success 7 · not_supported 4 | **0** | 36.1 s |
| .95 | r760-5 | Ubuntu 24.04 · 6.8.0-101-generic | python_ok (3.12.3) | os_linux_ubuntu | success | success 7 · not_supported 4 | **0** | 38.8 s |
| .161 | gmidbqa01 | RedHat 8.10 · 4.18.0-553.el8_10 | python_incompatible (3.6.8) | os_linux_rhel | success | success 7 · not_supported 4 | **0** | 23.0 s |
| .162 | gmidbqa02 | RedHat 9.2 · 5.14.0-284.11.1.el9_2 | python_ok (3.9.16) | os_linux_rhel | success | success 7 · not_supported 4 | **0** | 29.6 s |
| .163 | gmidbqa03cv | RedHat 9.6 · 5.14.0-570.12.1.el9_6 | python_ok (3.9.21) | os_linux_rhel | success | success 7 · not_supported 4 | **0** | 32.4 s |

- **8개 호스트 모두 errors[] 가 비어 있다(0건).** memory 의 두 경고(`total_basis=os_visible` · zero-slot), storage 의 lsblk 이상, network 의 lspci 경고, hba_ib 의 ERR 경고 어느 것도 나오지 않았다. 8개 diagnosis 가 같은 값이다: reachable · port_open · protocol_supported · auth_success 모두 true, failure_stage · failure_code · failure_reason 모두 null, credential_scope `git/os/linux`, auth.attempted_count 2 · used_label `linux_current`(primary) · fallback_used false.
- section 상태: system · hardware · cpu · memory · storage · network · users 가 success, bmc · firmware · power · thermal 은 Linux 채널에서 not_supported(정상).
- "errors[] 0" 의 의미: 이 수집은 **오류가 없었다**는 뜻이지 모든 항목이 채워졌다는 뜻이 아니다. 예를 들어 `.95` 는 PERC 컨트롤러 뒤 디스크 정보가 없어도 errors[] 가 0 이다(Linux 계약 밖).
- raw fallback 경로의 실데이터는 `.161`(python_incompatible 3.6.8)뿐이다. Kernel 6.x 호스트는 전부 python_ok(3.12.x)다.

## 5. 원 결함 C1~C10 → 기존 테스트 (c)

원 결함 정의는 `tests/evidence/2026-10-03-phase2-correctness.md`(Phase 2 정확성 수정)의 C1~C10 이고, C1 의 IEC 단위 보강은 2026-10-04 에 같은 파서에 더해졌다. 아래는 테스트 **파일 이름만**이다. "로컬 실행"은 2026-10-04 이 세션에서 실제로 돌린 결과다(전부 통과).

| ID | 항목 | 테스트 파일 (1~3개) | 로컬 실행 |
|---|---|---|---|
| C1 | DIMM · IEC · GiB | `tests/unit/test_linux_memory_parser.py` · `tests/e2e/test_linux_raw_scripts_shim.py` · `tests/unit/test_linux_remote_consolidation.py` | PASS (259 passed / 1 skipped 묶음) |
| C2 | Linux storage 진단 (lsblk 실패 은폐 제거) | `tests/unit/test_linux_storage_markers.py` · `tests/e2e/test_section_message_contract.py` · `tests/e2e/test_linux_raw_scripts_shim.py` | PASS |
| C3 | Windows HBA 매핑 | `tests/unit/test_windows_storage_enum_render.py` · `tests/unit/test_windows_storage_powershell_static.py` | PASS (267 passed 묶음) |
| C4 | Windows storage enum · BusType | `tests/unit/test_windows_storage_enum_render.py` · `tests/unit/test_windows_storage_powershell_static.py` | PASS |
| C5 | Redfish pagination · nextLink | `tests/unit/test_redfish_phase2_contracts.py` · `tests/unit/test_full_mirror_dryrun.py` | PASS |
| C6 | Firmware | `tests/unit/test_redfish_phase2_contracts.py` · `tests/integration/test_real_capture_replay.py` · `tests/unit/test_firmware_category.py` | PASS |
| C7 | HBA · NDF · WWPN | `tests/unit/test_linux_hba_ib_markers.py` · `tests/unit/test_redfish_phase2_contracts.py` · `tests/unit/test_identity_normalizer.py` | PASS |
| C8 | ESXi identity · endPort | `tests/unit/test_esxi_disks_host_select.py` · `tests/unit/test_esxi_disks_host_info.py` · `tests/unit/test_gather_identity_render.py` | PASS |
| C9 | 계정 검증 · 복구 | `tests/unit/test_redfish_phase2_contracts.py` · `tests/unit/test_account_family_and_write_contract.py` · `tests/unit/test_account_write_contract_invariants.py` | PASS |
| C10 | failure envelope · 외부 계약 | `tests/unit/test_json_only_fallback_shape.py` · `tests/unit/test_always_fallback_envelope.py` · `tests/e2e/test_envelope_failure_modes.py` | PASS |

주의:
- C1 · C2 · C7 의 Linux 테스트는 production raw 스크립트를 샌드박스의 실제 `sh` + `awk` 로 실행한다(Windows 에서는 Git for Windows 의 sh). 실제 ansible-playbook 실행은 아니다.
- C3 · C4 의 PowerShell 테스트, C9 의 계정 쓰기, C8 의 vSphere 는 실장비 검증이 아니라 합성/재생이다(`phase2-correctness.md` §5 의 "미실행·한계"와 같다).
- 한 파일이 여러 C 에 걸린다: `test_redfish_phase2_contracts.py` 는 C5 · C6 · C7 · C9 를 함께 고정하고, `test_windows_storage_*` 는 C3 · C4 를 함께 고정한다.

## 6. 여전히 `미확인` 인 항목과 이유 (d)

Kernel 6.12 호스트(`.37` `.38`) 기준이다. "닫는 데 필요한 것" 중 접근 · 범위에 관한 것은 사용자 결정 사항이다.

| # | 항목 | 범위 | 왜 미확인인가 | 닫는 데 필요한 것 |
|---|---|---|---|---|
| M1 | multipath | 전 커널 | Linux 수집에 multipath 경로가 없다(production 코드 0건, `gather_storage.yml:20` "보류", 스키마 필드 없음). 어떤 실데이터도 fixture 도 이 항목을 검증하지 않는다. 다중경로 호스트가 lsblk -d 에서 경로 디스크를 각각 disk 로 낼 것이라는 점(field_dictionary 의 is_os_disk 설명이 같은 전제)은 추론이며 검증한 적이 없다. | 요구 여부 결정(사용자). 필요하면 SAN lab 이 없어 합성 fixture 로만 검증 가능 |
| M2 | driver 버전(modinfo / ethtool -i version) | 전 커널 | 수집 경로와 스키마 필드가 없다. 6.8 참조 캡처의 in-tree 드라이버는 `version:` 이 커널 릴리스 문자열이라 구현해도 의미 없는 값이 나올 수 있다. | 요구 여부 결정(사용자) |
| M3 | ethtool -i (firmware-version) | 6.12 | `.37` `.38` adapters[0].firmware_version 이 null 이다. vmxnet3 은 ethtool 이 있어도 null 이 정상이지만 RHEL 10.2 에 ethtool 이 설치돼 있는지는 envelope 로 구분할 수 없다. ETHFW → firmware_version 매핑 단위 테스트도 없다. 6.8 R760 에서는 `실제 확인`. | RHEL 10.2 에서 `command -v ethtool` 확인 + ETHFW 매핑 단위 테스트 |
| M4 | RHEL 10 **물리** 조합 — NVMe · RAID · FC HBA/WWPN · multipath · bonding/VLAN/bridge/team · InfiniBand | 6.12 | lab 에 RHEL 10 물리 장비가 없다(`test-server-roster.md` §5 도 "RHEL 10 물리 장비의 HBA/FC/WWPN/multipath/NVMe 조합은 미검증"). 6.12 VM 은 가상 SATA/PVSCSI 와 단일 vmxnet3 NIC 뿐이다. 6.8 R760(Ubuntu)이 NVMe · RAID · bonding · VLAN 을 커널 6.x 에서 보였지만 RHEL 10 의 사용자영역 도구(util-linux · iproute2 · pciutils · dmidecode) 조합은 아니다. FC HBA 와 InfiniBand 는 어떤 커널에서도 실장비가 0이다(합성 fixture 만). | RHEL 10 물리 장비 확보 또는 사용자 사이트 실측(사용자 결정) |
| M5 | RHEL 10.2 reference 캡처 부재와 IEC 귀속 | 6.12 | `tests/reference/os/` 에 RHEL 10 디렉터리가 없다. IEC fixture(`test_dmidecode_36_iec_units_are_parsed`)는 main #20 raw_head 발췌(최대 24줄 · 600자)를 모사한 합성이다. 코드 주석 · 테스트 docstring · FAILURE_PATTERNS 는 "dmidecode 3.6 이 IEC 접두어를 쓴다"고 적지만 저장소의 RHEL 9.6 · Rocky 9.6 캡처(`# dmidecode 3.6`)는 `Size: 8 GB` 로 찍는다. IEC 를 내는 정확한 dmidecode 빌드는 확정되지 않았다. 수정은 두 단위계를 모두 환산하므로 기능상 안전하다. | 읽기 전용 SSH 허가가 나면 `.37` 의 `dmidecode -t memory` · `lsblk -JO` · `lspci -nn` · `ip -d link` · `ethtool -i` 를 `tests/reference/os/<rhel10 디렉터리>/` 에 캡처(기존 glob 테스트가 자동으로 대상에 넣는다). 사용자 허가 필요 |
| M6 | Kernel 6.x × raw fallback 조합 | 6.x | 6.x 호스트는 전부 python_ok(3.12.x)다. 수집 스크립트는 두 경로가 같고 setup facts 유래 필드(system.os_family · distribution · version · kernel · architecture · hostname · uptime)만 다르다. raw 경로 실데이터는 `.161`(4.18)뿐이고 `test_linux_raw_scripts_shim.py` 의 raw 시나리오가 구조를 검증한다. | Agent 환경변수 SE_FORCE_LINUX_RAW_FALLBACK=true 로 `.37` 재수집 1회(운영 영향 판단은 사용자) |
| M7 | /sys cpufreq 노드 유무 | 6.12 · 6.8 | 값(max_speed_mhz · turbo)은 3단 fallback 이 채우고 raw 원본이 envelope 에 남지 않아 어느 단이 채웠는지 알 수 없다. 최종 값은 타당하다. | 영향 낮음. 필요하면 근거 marker 추가 |
| M8 | Linux RAID 심화(controllers[].drives · health · logical_volumes, PERC 뒤 디스크) | 6.8 베어메탈 | 계약상 Redfish 전용이라 Linux 는 항상 [] / null 이다. RAID CLI(storcli · perccli · ssacli) 호출도 없다. 오류가 아니라 범위 밖이다. | 스키마 · 계약 변경이 필요하므로 사용자 결정 |

## 7. `실제 확인` 이지만 6.x 입력의 회귀 fixture 가 없는 항목

실데이터로는 맞게 나오지만 6.x 입력으로 회귀를 막아 주는 단위 테스트가 없다. 파서가 바뀌면 이 항목은 production 에서야 드러난다.

1. lscpu · /proc/cpuinfo → cpu.* (7번). 테스트가 읽는 입력이 없다. `tests/reference` 의 cmd_lscpu.txt · cmd_cpuinfo.txt 는 미사용.
2. lspci → storage.controllers[] 와 class → controller_type 분류(RAID · NVMe · SAS · SATA · SCSI) (5 · 9 · 10번). 샌드박스가 lspci 를 숨긴다.
3. ethtool -i → network.adapters[].firmware_version (6번).
4. bonding · VLAN · bridge 의 6.x 입력(12번). 입력 fixture 는 RHEL 8.10 · 9.6 과 합성이고 6.8 `cmd_bonding.txt` 는 미사용.
5. NVMe 컨트롤러 분류(Non-Volatile memory controller → NVMe) (10번).

## 8. 부가 관찰 (분류 밖)

### O-1. driver_map[].vlan_id 가 실제 VLAN 장치에서 null (6.8 실데이터)

- 관측: #76 의 `.96`(bond0.64 · bond0.656)과 `.95`(bond0.64)에서 `network.driver_map[]` 의 해당 행이 vlan_id null 이다. 같은 장치의 `network.interfaces[]` 는 vlan_id 64 · 656 · 64, vlan_parent bond0 이다. driver_map 의 vlan_id 채움 수는 8개 호스트 전부 0 이다.
- 코드: `gather_network.yml:157-160` 이 `/proc/net/vlan/<if>` 를 읽는다. 이 raw 태스크에는 become 이 없다.
- 정황 3가지:
  1. 커널 v6.8 `net/8021q/vlanproc.c` 가 장치별 파일과 config 를 `S_IFREG | 0600` 으로 만든다(v6.8 `vlanproc.c` 119행 · 143행 — 2026-10-04 에 raw 소스를 직접 조회해 확인).
  2. 8개 호스트 모두 비루트 `<비루트 수집 계정>` 으로 수집한다(0절).
  3. 저장소 `tests/unit/test_network_topology.py::test_real_kernel_vlan_on_bond_fixture` docstring 이 실장비 RHEL 8.10 에서 `/proc/net/vlan/config` 가 Permission denied 였다고 이미 적어 두었다.
- 수정 `5a60d420`(2026-10-03, P1 에 포함)은 읽을 수 있는 합성 proc 파일로만 검증된다(`test_nic_block_vlan_id_from_proc_net_vlan`). 비루트 실환경에서는 효과가 없다.
- 상태: **가설**이다. `.96` 에서 root 로 `/proc/net/vlan/bond0.64` 를 읽어 확인하지는 않았다(실장비 접속 0). 영향은 낮다 — interfaces[].vlan_id 가 정상이고 driver_map 은 보조 뷰이며 필드 사전은 `network.driver_map[]` 만 선언한다. Kernel 6.x 한정 문제가 아니라 모든 커널에서 같다.

### O-2. PCI 주소 표기가 section 마다 다름

`.37` network.adapters[0].pci 는 "0b:00.0"(도메인 없음), storage.controllers[0].pci 는 "0000:02:00.0"(lspci -D). network 쪽은 ethtool bus-info 와 맞추려고 도메인을 뗀다(`gather_network.yml:228`). PCI 주소로 두 목록을 교차 참조하려면 정규화가 필요하다. 6.x 와 무관하고 영향은 낮다.

## 9. 한계와 주의

- #76 은 production Job 의 1회 실행이다. `.37` `.38` 의 반복 재현은 main #29 · #48 과 `tests/evidence/2026-10-04-test-server-roster.md` 에 기록돼 있고 이 문서에서 다시 돌리지 않았다.
- `실제 확인` 은 envelope 값의 존재와 내부 정합을 뜻한다. 호스트의 정답(예: hypervisor 의 vCPU 토폴로지 설정)과 대조한 것은 아니다.
- raw 명령 출력 원본은 envelope 에 남지 않는다(SLOT 0 같은 오류 detail 제외). 도구의 설치 여부와 버전은 envelope 로 알 수 없다.
- `fixture 확인` 은 6.x 입력 기준으로 엄격히 적용했다. 4.18 · 5.14 캡처와 커널 비특정 합성은 보조 근거로만 적었다.
- 로컬 테스트는 이 세션의 Windows 에서 돌렸다(sh · awk = Git for Windows). 1건 skip(symlink 권한). 실제 `ansible-playbook` 실행은 하지 않았다.
- 작업 트리에는 이 분석과 무관한 미커밋 변경이 있다(`Jenkinsfile_ci` · `scripts/ai/prodgen/*` · `tests/jenkins/harness/*` · `tests/unit/prodgen/*` 등과 untracked 파일). 이 분석은 그 파일을 읽지도 쓰지도 않았고 pytest 는 캐시 · 바이트코드 없이 실행했다.
