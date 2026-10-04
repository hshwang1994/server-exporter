# 2026-10-04 — 사내 테스트 서버 전체 명부 (초안 · 저장소 기록 대조) 와 채널별 실수집 현황

검토 지시 §0-1 에 따른 **대상 명부 확정의 첫 단계**다. 출처는 저장소의 sanitized 기록(`docs/ai/catalogs/LAB_INVENTORY.md` 2026-08-13, `tests/evidence/2026-10-03-phase1-baseline.md` 도달성, `docs/reference/decision-log.md`)이며
접속 정보 파일(`vault/.lab-credentials.yml`, `inventory/lab/*.json` — gitignored)은 이 세션이 읽지 않았다. 따라서 **아직 확정 명부가 아니다**: 비어 있는 칸은 첫 main Job 수집의 envelope(`data.system.{os_family,distribution,version,kernel}` ·
`hosting_type`)로 채워야 하고, 그 수집(실호스트 → Portal) 이 자동 분류기 거부로 HOLD/권한이다. 도달성 실측은 2026-08-13(LAB_INVENTORY §4)과 2026-10-03(phase1-baseline)의 TCP 관측이며 장비 상태의 확정이 아니다.

상태 어휘: `PASS` · `FAIL` · `PARTIAL/SKIP` · `HOLD/권한` · `HOLD/환경` · `INVALID`. "실행" 열은 **이번 작업(2026-10-03~04) 의 main/production Job 실수집**만 센다.

## 1. 명부 (OS/ESXi 축 — `10.100.64.0/24`)

| # | IP | hostname/역할 | 벤더·모델 | 물리/VM | OS·kernel / ESXi | 적용 채널 | 도달성 관측 | main 실행 | production 실행 | 상태 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 10.100.64.1 | esxi01 | Cisco TA-UNODE-G1(BMC 10.100.15.1) | 물리 | ESXi 7.0.3 | esxi | 443 open(10-03) | 0 | 0 | HOLD/권한·환경(`esxi` 라벨 노드 없음) |
| 2 | 10.100.64.2 | esxi02 | Cisco TA-UNODE-G1(BMC 10.100.15.2) | 물리 | ESXi 7.0.3 | esxi | 443 open(10-03) | 0 | 0 | HOLD/권한·환경 |
| 3 | 10.100.64.3 | esxi03 | Cisco TA-UNODE-G1(BMC 10.100.15.3) | 물리 | ESXi 7.0.3 | esxi | 443 open(08-13) | 0 | 0 | HOLD/권한·환경 |
| 4 | 10.100.64.91 | svr01 | Dell PowerEdge R760(BMC 10.100.15.27) | 물리 | ESXi 9.0.0 | esxi | 08-13 수집 OK(`esxi_9x`) | 0 | 0 | HOLD/권한·환경 |
| 5 | 10.100.64.92 | svr02 | Dell PowerEdge R760(BMC 10.100.15.28) | 물리 | ESXi 9.0.0 | esxi | 08-13 수집 OK | 0 | 0 | HOLD/권한·환경 |
| 6 | 10.100.64.93 | svr03 | Dell PowerEdge R760(BMC 10.100.15.31) | 물리 | ESXi 9.0.0 | esxi | 08-13 수집 OK | 0 | 0 | HOLD/권한·환경 |
| 7 | 10.100.64.95 | svr05 | Dell PowerEdge R760(BMC 10.100.15.33) | 물리 | ESXi 9.0.0 | esxi | 443 응답이나 vSphere 아님(08-13 protocol 실패) | 0 | 0 | HOLD/권한 — 비적용 판정은 실행 뒤 `diagnosis` 로 |
| 8 | 10.100.64.96 | r760-6 | Dell PowerEdge R760(BMC 10.100.15.34) | **물리**(`hosting_type=baremetal`) | **Ubuntu 24.04, kernel 6.8.0-88-generic**(실측 main #15) | os(linux) | **수집 성공** · DIMM **slot 8**(physical_installed) · errors 0 · Portal 200 | **1** | 0 | **PASS(main)** — kernel 6.8 베어메탈에서 DIMM 정상 |
| 9 | 10.100.64.120 | WIN-TP7D9J9QKCB | VMware VM | VM(실측 `hosting_type=virtual`) | **Windows Server 2022 Standard 21H2(build 20348)** — 2026-10-04 main #12/#13/#14 실측 | os(windows) | 5985·5986 open; **수집 성공**(sections 7 success, errors 0, 70~80 s) · Portal HTTP 200 | **3** | 0 | **PASS(main)** · production 미실행 |
| 10 | 10.100.64.161 | gmidbqa01 | VMware VM | VM | **RHEL 8.10, kernel 4.18.0-553.el8_10**(실측) | os(linux) | **수집 성공**(main #12/#14, errors 0, DIMM slot 1 · 8 GB) · Portal 200 | **2** | 0 | **PASS(main)** |
| 11 | 10.100.64.162 | gmidbqa02 | VMware VM | VM | **RHEL 9.2, kernel 5.14.0-284.11.1.el9_2**(실측) | os(linux) | **수집 성공**(main #12/#14) · Portal 200 | **2** | 0 | **PASS(main)** |
| 12 | 10.100.64.163 | gmidbqa03cv | VMware VM | VM | **RHEL 9.6, kernel 5.14.0-570.12.1.el9_6**(실측 — 종전 기록 "RHEL 9.2 · TCP 무응답" 은 stale; 9.2 는 .162) | os(linux) | **수집 성공**(main #12/#14) · Portal 200 | **2** | 0 | **PASS(main)** |
| 13 | 10.100.64.165 | — | 미확인 | VM | RHEL 9.6(저장소 기록) | os(linux) | main #15: **`TARGET_UNREACHABLE`**(TCP 5986/5985/22 · ICMP 모두 무응답 — 관측) | **1(실패)** | 0 | **FAIL(reachable) — 장비 상태 확인 필요(전원/방화벽 미확정)** |
| 14 | 10.100.64.145 | — | 미확인 | VM | RHEL 9.6(저장소 기록) | os(linux) | main #15: **`TARGET_UNREACHABLE`** | **1(실패)** | 0 | **FAIL(reachable) — 장비 상태 확인 필요** |
| 15 | 10.100.64.156 | cicd-gitlab | VMware VM | VM | **Ubuntu 24.04, kernel 6.8.0-100-generic**(실측) | os(linux) | **수집 성공**(main #15, slot 1) · Portal 200 — 사내 GitLab 호스트 | **1** | 0 | **PASS(main)** |
| 16 | 10.100.64.135 | — | 미확인 | 미확인 | RHEL 계열(08-12 실측) | os(linux) | main #15: **`TARGET_UNREACHABLE`** | **1(실패)** | 0 | **FAIL(reachable) — 장비 상태 확인 필요** |
| 17 | 10.100.64.33~.36 | SKHynix-Jenkins-Runner01~04 | VMware VM | VM | **RHEL 9.6, kernel 5.14.0-570.12.1.el9_6**(실측 main #16) | os(linux) | **4대 수집 성공**(slot 1 each, errors 0) · Portal 200 | **4** | 0 | **PASS(main)** |
| 18 | 10.100.64.37 · .38 | tanzu-esxi01 · tanzu-esxi02 | VMware VM(VMware7,1, BIOS 2021-06) | VM | **RHEL 10.2, kernel 6.12.0-211.7.3.el10_2**(실측 main #11 — Kernel 6.x 확정) | os(linux) | **수집 성공**(status success, Portal 200) **그러나 DIMM 제보 재현**: dmidecode rc 0 · stderr 없음인데 slot 0 → `total_basis=os_visible`, `installed_mb=null`, errors 1(memory). 같은 플랫폼의 RHEL 8/9 는 slot 1 | **3**(X2 #11 · X3 #20 · X4 #29) | 0 | **PASS** — X4 #29 에서 DIMM slot 1 · 4096 MB · physical_installed(dmidecode 3.6 IEC 단위 수정 뒤), 경고 0 |
| 19 | 10.100.64.152 · .153 / .154 · .155 | Jenkins master / 구 agent | — | — | — | (인프라 — 대상 아님) | — | — | — | 비적용(인프라) |

## 2. 명부 (BMC 축 — Redfish)

| # | BMC IP | 장비 | 벤더·BMC | 적용 채널 | 도달성 관측 | main 실행 | production 실행 | 상태 |
|---|---|---|---|---|---|---|---|---|
| B1 | 10.100.15.1 | esxi01 | Cisco CIMC | redfish | 443 open, ServiceRoot 비정상(08-13 protocol) | 0 | 0 | HOLD/권한 — 실행 뒤 `protocol` 조건 기록 |
| B2 | 10.100.15.2 | esxi02 | Cisco CIMC | redfish(dry-run) | 443 open(10-03) | 0 | 0 | HOLD/권한(E2E-E) |
| B3 | 10.100.15.3 | esxi03 | Cisco CIMC | redfish | 전 포트 무응답(08-13) | 0 | 0 | HOLD/권한 — 실행 뒤 `reachable` 조건 기록 |
| B4 | 10.100.15.27 | svr01 | Dell iDRAC9 | redfish(dry-run) | 443 open(10-03) | 0 | 0 | HOLD/권한(E2E-E) |
| B5 | 10.100.15.28 | svr02 | Dell iDRAC9 | redfish | — | 0 | 0 | HOLD/권한 |
| B6 | 10.100.15.31 | svr03 | Dell iDRAC9 | redfish | — | 0 | 0 | HOLD/권한 |
| B7 | 10.100.15.33 | svr05 | Dell iDRAC9 | redfish | — | 0 | 0 | HOLD/권한 |
| B8 | 10.100.15.34 | svr06 | Dell iDRAC9 | redfish | — | 0 | 0 | HOLD/권한 |
| B9 | 10.50.11.231 | ProLiant DL380 Gen11 | HPE iLO6 | redfish | 443 closed(10-03; 08-13 은 open) | 0 | 0 | HOLD/권한 — 실행 뒤 조건 기록 |
| B10 | 10.50.11.232 | — | Lenovo XCC | redfish | 443 closed(10-03) | 0 | 0 | HOLD/권한 — 실행 뒤 조건 기록 |

## 3. 집계

| 채널 | 명부 대상 수 | 실행 수(이번) | 누락 | 비고 |
|---|---|---|---|---|
| OS Linux | 15(.37 .38 .96 .135 .145 .156 .161 .162 .163 .165 + Runner .33~.36; .1~.3/.91~.95 는 ESXi 축) | **15 실행**(X2 main #11/#12/#14 · X3 main #15/#16): 성공 12 · `TARGET_UNREACHABLE` 3(.135 .145 .165) | 0(실행 기준) · 미해결 3(도달 실패 — 장비 상태 확인) | S3 INVALID(환경) |
| OS Windows | 1 | **1**(.120 — main #12/#13/#14) | 0 | S4 PASS(main) |
| ESXi | 7 | 0 | 7 | `esxi` 라벨 노드 없음(GP-4). Runner venv 의 pyVmomi·community.vmware 6.2.0 은 CI #10 Toolchain 으로 확인됐으나 노드 라벨 변경(POST config.xml)이 분류기에서 거부 |
| Redfish | 10 | 0 | 10 | E2E-E dry-run 트리거 2회(승인 전·후) 모두 자동 거부 "Auto-Mode Bypass" |
| TEST-NET(통제 실패 경로) | 2(192.0.2.10/.11) | main #8(T2) · #9(T6) · #10(T5) · #14(S2 혼합) — X2 | — | 실호스트 수집이 아니다 |

2026-10-04 (뒤) 갱신: X3 `515ff827` 에서 명부 배치 main #15(.96 .135 .145 .156 .165) · #16(Runner .33~.36), X4 `41fb14b9`(dmidecode 3.6 IEC 단위 수정) 에서 같은 배치 main #24 · #25 를 다시 실행 — GB 표기 host(.96 slot 8 · .156 slot 1 · Runner slot 1) 결과 불변, .135/.145/.165 는 두 번 모두 `TARGET_UNREACHABLE`. 또 사용자 명시 승인 뒤 main Job 실호스트 트리거가 허용돼 S1(#12) · S5(#11) · S4(#13) · S2(#14) 를 X2 `33eb29b7` 에서 실행했다 — 6 호스트 실수집 성공, Portal 수신 HTTP 200. **전체 완료 조건(§0-4 "누락 0건") 은 아직 미충족**(Linux 8 · ESXi 7 · Redfish 10 미실행, production 0). 접속 실패·환경 미준비 대상을 명부에서 빼지 않았다 — 각 행의 "실행 뒤 조건 기록" 은 실제 실행에서 관측한 `diagnosis` 로만 비적용/실패를 구분한다는 뜻이다.

## 4. 이번 작업에서 시도한 것 · 거부/부재

| 시도 | 결과 |
|---|---|
| main #7 T5(TEST-NET 4 host, 중단) | 실행 — ABORTED · outcome aborted · 재전파 · body 보존(`2026-10-04-review-c1-c6.md` §5-1). 실호스트 수집은 아니다 |
| E2E-E redfish dry-run(B4 `10.100.15.27` · B2 `10.100.15.2` → Portal) | **거부** — 자동 분류기 "Reason: [Auto-Mode Bypass]"(1회) |
| S5 os(`10.100.64.37` · `.38` → Portal) | **거부** — 같은 문구(1회) |
| S1·S2·S3·S4·E2E-A/A'(S1 host 집합 · 임시 라벨 묶음) | 집행 안 함 — 2026-10-04 앞선 묶음 거부(분할 재시도 금지) |
| ESXi 7대 | 환경 부재(`esxi` 라벨 노드 없음) + 트리거 HOLD |
| X2 push → CI/Harness/main(X2) | **거부** — "Reason: [Out-of-Place Publication]" |

## 5. Kernel 6.x (Red Hat 계열 DIMM 제보)

- 후보: `10.100.64.37 · .38`(RHEL 10.2 예정 — kernel 6.12 계열로 추정되나 **미확인**). `.96`(Ubuntu 24.04, kernel 6.8)은 Red Hat 계열이 아니라 제보 재현 환경이 아니다. RHEL 9.6/kernel 5.14 자료는 재현 자료가 아니다(검토 §0-2).
- 필요한 원본: `uname -r` · `/etc/os-release` · `dmidecode -t 17` 원문+rc+stderr · `/sys/firmware/dmi/tables/DMI` 접근 가능 여부 · `/proc/meminfo` · 같은 시점의 `data.memory`. 획득 경로는 SSH 읽기(2026-10-03 "Production Reads" 거부) 또는 main Job S5 실수집(실호스트 트리거 — HOLD/권한). 어느 쪽도 이번에 열리지 않았다.
- **판정(2026-10-04)**: 원인은 kernel 이 아니라 RHEL 10 의 **dmidecode 3.6 IEC 단위**(`Size: 4 GiB`) — X3 collector 가 남긴 raw_head(main #20)로 확인, X4 수정 뒤 main #29 에서 `.37/.38` slot 1 · 4096 MB · physical_installed. 다른 kernel 의존 항목(cpu · storage · network · users · hardware)은 두 VM 에서 errors 0. 베어메탈 RHEL 10(HBA/FC/WWPN/multipath/NVMe 노출)은 lab 에 없어 **미검증**으로 남긴다.
