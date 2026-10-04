# 2026-10-04 — 사내 테스트 서버 전체 명부와 채널별 실수집 현황 (X6 `70e4ec8a` 기준 갱신)

검토 지시 §0-1 에 따른 **대상 명부**다. 출처는 저장소의 sanitized 기록(`docs/ai/catalogs/LAB_INVENTORY.md` 2026-08-13, `tests/evidence/2026-10-03-phase1-baseline.md`, `docs/reference/decision-log.md`)과 2026-10-04 main Job 실수집 envelope(`data.system.{os_family,distribution,version,kernel}` · `hosting_type` · `diagnosis`)이다. 접속 정보 파일(`vault/.lab-credentials.yml`)은 사용자 허용 뒤 **마스킹 구조만** 읽었다(값은 `<str:len>`) — 명부의 IP 축이 그 구조와 일치함을 확인했다. 범위 표기 없이 **개별 주소**로 쓴다.

상태 어휘: `PASS` · `FAIL` · `PARTIAL/SKIP` · `HOLD/권한` · `HOLD/환경` · `INVALID`. "main 실행" 열은 2026-10-03~04 의 main Job 실수집 빌드 번호(대표)다. production 실행은 승격 뒤 §5-3 에서 센다(성능 기준선 빌드 production #59~ 는 legacy `4ce90a00` 의 실행이라 별도 — `2026-10-04-review-c1-c6.md` §5-8).

## 1. 명부 (OS/ESXi 축 — `10.100.64.x`, 개별 주소)

| # | IP | hostname(실측) | 벤더·모델 | 물리/VM | OS·kernel / ESXi (실측) | 적용 채널 | main 실행(대표 빌드) | 결과 · 상태 |
|---|---|---|---|---|---|---|---|---|
| 1 | 10.100.64.1 | esxi01 | Cisco TA-UNODE-G1(BMC 10.100.15.1) | 물리 | ESXi 7.0.3 | esxi | #44(E2E-D) | **PASS(main)** — `vsphere_api` · adapter `esxi_7x` · sections 6 success · errors 0 · Portal 200 |
| 2 | 10.100.64.2 | esxi02 | Cisco TA-UNODE-G1(BMC 10.100.15.2) | 물리 | ESXi 7.0.3 | esxi | #44 | **PASS(main)** |
| 3 | 10.100.64.3 | esxi03 | Cisco TA-UNODE-G1(BMC 10.100.15.3) | 물리 | ESXi 7.0.3 | esxi | #44 | **PASS(main)** |
| 4 | 10.100.64.91 | r760-1 | Dell PowerEdge R760(BMC 10.100.15.27) | 물리 | ESXi 9.0.0 | esxi | #44 | **PASS(main)** — adapter `esxi_9x` |
| 5 | 10.100.64.92 | r760-2 | Dell PowerEdge R760(BMC 10.100.15.28) | 물리 | ESXi 9.0.0 | esxi | #44 | **PASS(main)** |
| 6 | 10.100.64.93 | r760-3 | Dell PowerEdge R760(BMC 10.100.15.31) | 물리 | ESXi 9.0.0 | esxi | #44 | **PASS(main)** |
| 7 | 10.100.64.95 | **r760-5** | Dell PowerEdge R760(BMC 10.100.15.33) | **물리**(`hosting_type=baremetal`) | **Ubuntu 24.04, kernel 6.8.0-101-generic**(main #54) — 종전 기록 "svr05 ESXi 9.0.0" 은 **stale** | **os(linux)** — ESXi 비적용 | #44(esxi: `PROTOCOL_CHECK_FAILED`, reachable·443 open·vSphere 응답 아님) · #54(os: 성공) | **PASS(main, os)** — sections 7 success · errors 0 · Portal 200. 비적용 판정 근거: #44 diagnosis + 워크스테이션 관측(443 = Traefik 기본 인증서·HTTP 404, 902 refused, 22 open) |
| 8 | 10.100.64.96 | r760-6 | Dell PowerEdge R760(BMC 10.100.15.34) | 물리(`baremetal`) | Ubuntu 24.04, kernel 6.8.0-88-generic | os(linux) | #15 · #24 | **PASS(main)** — DIMM slot 8(physical_installed) · errors 0 |
| 9 | 10.100.64.120 | WIN-TP7D9J9QKCB | VMware VM | VM(`virtual`) | Windows Server 2022 Standard 21H2(build 20348) | os(windows) | #12 #13 #14 · X6 #49 #50 #51 · 성능 #56~ | **PASS(main)** — sections 7 success · errors 0 · 약 70~95 s · Portal 200 |
| 10 | 10.100.64.161 | gmidbqa01 | VMware VM | VM | RHEL 8.10, kernel 4.18.0-553.el8_10 | os(linux) | #12 #14 · X6 #49 #51 | **PASS(main)** — DIMM slot 1 · 8 GB |
| 11 | 10.100.64.162 | gmidbqa02 | VMware VM | VM | RHEL 9.2, kernel 5.14.0-284.11.1.el9_2 | os(linux) | #12 #14 · X6 #49 #51 | **PASS(main)** |
| 12 | 10.100.64.163 | gmidbqa03cv | VMware VM | VM | RHEL 9.6, kernel 5.14.0-570.12.1.el9_6 | os(linux) | #12 #14 · X6 #49 #51 | **PASS(main)** |
| 13 | 10.100.64.165 | — | 미확인 | VM(저장소 기록) | RHEL 9.6(저장소 기록) | os(linux) | #15 · #24 · production #77 | **FAIL(reachable)** — `TARGET_UNREACHABLE`(TCP 5986/5985/22 · ICMP 모두 무응답) 3회. 워크스테이션 probe 도 전부 무응답. **Runner 망 net-probe #1(2026-10-04, 같은 /24 L2)**: ARP neighbour `INCOMPLETE` · ICMP 무응답 · 22 connect 실패 · tracepath `!H` → **그 주소에 켜진 호스트가 없다**(전원 꺼짐 · 주소 변경 · 폐기 중 하나). 자산 결정은 사용자 — 임의 제외하지 않는다 |
| 14 | 10.100.64.145 | — | 미확인 | VM(저장소 기록) | RHEL 9.6(저장소 기록) | os(linux) | #15 · #24 · production #77 | **FAIL(reachable)** — 위와 같은 관측 + net-probe #1 ARP `INCOMPLETE`(L2 에 없음). 자산 결정은 사용자 |
| 15 | 10.100.64.156 | cicd-gitlab | VMware VM | VM | Ubuntu 24.04, kernel 6.8.0-100-generic | os(linux) | #15 · #24 | **PASS(main)** — slot 1 · 사내 GitLab 호스트 |
| 16 | 10.100.64.135 | — | 미확인 | 미확인 | RHEL 계열(08-12 실측) | os(linux) | #15 · #24 · production #77 | **FAIL(reachable)** — 위와 같은 관측 + net-probe #1 ARP `INCOMPLETE`(L2 에 없음). 자산 결정은 사용자 |
| 17 | 10.100.64.33 · .34 · .35 · .36 | SKHynix-Jenkins-Runner01~04 | VMware VM | VM | RHEL 9.6, kernel 5.14.0-570.12.1.el9_6 | os(linux) | #16 · #25 | **PASS(main)** — 4대 slot 1 each · errors 0 |
| 18 | 10.100.64.37 · .38 | tanzu-esxi01 · tanzu-esxi02 | VMware VM(VMware7,1) | VM | **RHEL 10.2, kernel 6.12.0-211.7.3.el10_2** | os(linux) | #11 · #20 · #29 · X6 #48 | **PASS(main)** — DIMM 제보 재현(#11 slot 0) → 원인 dmidecode 3.6 IEC 단위(#20 raw_head `Size: 4 GiB`) → 수정 뒤 #29 · #48 slot 1 · 4096 MB · physical_installed · 경고 0 |
| 19 | 10.100.64.152 · .153 / .154 · .155 | Jenkins master / 구 agent | — | — | — | (인프라 — 대상 아님) | — | 비적용(인프라) |

## 2. 명부 (BMC 축 — Redfish, 개별 주소; 모든 실행은 `redfishAccountDryrun=true`)

| # | BMC IP | 장비 | 벤더·BMC | main 실행 | 결과 · 상태 |
|---|---|---|---|---|---|
| B1 | 10.100.15.1 | esxi01 | Cisco CIMC(UCSC-C220-M4S, 시리얼 FCH21167GH0) | #53 · production #80 | **FAIL(protocol) = 환경(BMC 설정)** — reachable · 443 open · `PROTOCOL_CHECK_FAILED`. 2026-10-04 무인증 `GET /redfish/v1/`(워크스테이션 + Runner net-probe #1 동일): **HTTP 503 `CiscoUCS.1.0.ServiceUnavailable` "Redfish Service is disabled. Resolution: Use CIMC WebUI/CLI/XMLAPI to enable REDFISH Service."** — 수집기 결함이 아니라 CIMC 에서 Redfish 가 꺼져 있다. 켜는 것은 BMC 설정 변경(G-5 금지) → 사용자 결정 |
| B2 | 10.100.15.2 | esxi02 | Cisco CIMC | #41 · #53 · #55(S3 의 timeout 대상 — 의도) | **PASS(main)** — adapter `redfish_cisco_cimc` · sections 9 success · 341~353 s(가장 느린 BMC) |
| B3 | 10.100.15.3 | esxi03 | Cisco CIMC | #53 · production #80 | **FAIL(reachable)** — `TARGET_UNREACHABLE`(2026-08-13 과 일치). net-probe #1(Runner 망: route via 10.100.64.254, ICMP·443 무응답) + 워크스테이션 무응답 — 같은 대역의 `.1` `.2` 는 응답하므로 경로가 아니라 **그 BMC 자체**(전원 · 주소) 문제다. 자산 결정은 사용자 |
| B4 | 10.100.15.27 | r760-1 | Dell iDRAC9 | #41 · #53 · #55 | **PASS(main)** — adapter `redfish_dell_idrac9` · 9 success · 34~41 s |
| B5 | 10.100.15.28 | r760-2 | Dell iDRAC9 | #53 · #55 | **PASS(main)** |
| B6 | 10.100.15.31 | r760-3 | Dell iDRAC9 | #53 · #55 | **PASS(main)** |
| B7 | 10.100.15.33 | r760-5 | Dell iDRAC9 | #53 · #55 | **PASS(main)** |
| B8 | 10.100.15.34 | r760-6 | Dell iDRAC9 | #53 · #55 | **PASS(main)** |
| B9 | 10.50.11.231 | ProLiant DL380 Gen11(iLO CN ILOSGH504HNZK) | HPE iLO6 | #53 · production #80 | **FAIL(reachable) = 경로** — Runner 망(net-probe #1: ICMP·443 무응답, tracepath 가 `10.12.2.1 → 10.12.1.2` 뒤에서 끊김)에서는 `TARGET_UNREACHABLE` 이나, **워크스테이션(10.11.11.x)에서는 ICMP 응답 · 443 open · 무인증 ServiceRoot HTTP 200(ServiceRoot v1_14_0)** — 장비는 살아 있고 Redfish 가 동작한다. 같은 대역 `.232`(Lenovo)는 Runner 에서 수집 성공이므로 **`.231` 만 Runner 망에서 막힌다**(iLO 접근 제한 또는 중간 ACL). 네트워크/iLO 담당 확인 — 설정 변경은 하지 않았다 |
| B10 | 10.50.11.232 | XCC-7Z73-J30AF7LC | Lenovo XCC | #53 · #55 | **PASS(main)** — adapter `redfish_lenovo_xcc` · 9 success · 61~63 s |

Redfish 공통 증거: 인증은 전역 표준 계정(`details.auth = {attempted_count: 1, used_label: common_infraops, used_role: primary, fallback_used: false}`, `credential_scope = common/redfish/standard`), `details.account_service = {}` — 복구/재조정 경로에 진입하지 않았으므로 **Account Write 0**(계약 "Primary 인증 성공 → Account Write 0 → Primary Gathering"). dry-run 플래그는 빌드 파라미터 `redfishAccountDryrun=True` 로 전달됐고 `Jenkinsfile_portal` 이 `-e _rf_account_service_dryrun=true` 로 넘긴다 — 재조정이 필요했다면 `account_service.dryrun` 에 기록된다(이번엔 미진입).

## 3. 집계 (X6 기준)

| 채널 | 명부 대상 수 | 실행 수 | 성공 | 미해결(실행했으나 실패) | 비고 |
|---|---|---|---|---|---|
| OS Linux | **15**(.33 .34 .35 .36 .37 .38 .95 .96 .135 .145 .156 .161 .162 .163 .165 — `.95` 는 ESXi 축에서 OS 축으로 이동) | **15** | **12** | **3**(.135 .145 .165 — `TARGET_UNREACHABLE`; L2 에 호스트 없음, 자산 결정 사용자) | Kernel 6.x(.37 .38) DIMM 해결 재확인(#48 · production #76). 종전 "16/13" 은 집계 오류(정정 2026-10-04 4차) |
| OS Windows | 1(.120) | **1** | **1** | 0 | S4 PASS |
| ESXi | 7(.1 .2 .3 .91 .92 .93 .95) | **7** | **6** | 0 — `.95` 는 **비적용**(ESXi 아님, OS 축에서 성공) | E2E-D #44, `esxi` 라벨 노드 준비 뒤 실행 |
| Redfish | 10 | **10** | **7** | **3**(B1 protocol · B3 reachable · B9 reachable) | E2E-E #41/#53, S3 #55 — 모두 dry-run |
| TEST-NET(통제 실패 경로) | 2(192.0.2.10 .11) | T2 #45 · T6 #52 · T5 #46 · S2 #51 · E2E-A #42 | — | — | 실호스트 수집이 아니다 |

- **대상 수 = 실행 수**: 명부의 모든 호스트/BMC 를 실제로 실행했다(누락 0). 적용 채널 기준 **32건 실행 = Linux 15 + Windows 1 + ESXi 6 + Redfish 10 — 성공 26 / 미해결 6**(도달 실패 5 + Redfish 프로토콜 1) / 비적용 1(.95 ESXi 축). 물리 장비 수와 채널별 대상 수는 다르다(예: R760 한 대가 OS 또는 ESXi 1건 + Redfish 1건).
- 미해결 6건은 **진단의 증거이지 정상 수집 완료가 아니다.** Job 과 워크스테이션 양쪽에서 응답이 없거나(5), Redfish 서비스 응답이 비정상(1)이다. 장비 상태·Redfish 설정 확인과 테스트 범위 포함 여부는 **사용자 결정** — 이 세션은 설정 변경·재부팅을 하지 않고 명부에서 빼지도 않는다.
- production Job 실행(P3 `915dec4e`, 2026-10-05): 11 빌드(#94~#104) 전부 checkout == P3 · 기대 결과 일치 · GP-23 `.96/.95` VLAN id 일치 — GP-23 수정 뒤 `.96`/`.95` 의 `driver_map[].vlan_id` 가 실제 VLAN id 를 낸다(main #121, production P-LINA).
- production Job 실행(P1 `1f725071`, 2026-10-04 19:15~19:27): Linux 15(#76 8 success · #77 4 success + `.135 .145 .165` unreachable) · Windows 1(#78) · ESXi 6(#79 전부 success) · Redfish 10(#80: 7 success · `.1` protocol · `.3`·`.231` unreachable) · S3-Redfish(#81) — **main 과 동일**(`2026-10-04-review-c1-c6.md` §5-13). 성능 기준선 빌드(#59~#70, legacy)는 별도.

## 4. 이번 작업에서 시도한 것 · 거부 · 부재 (최종)

| 시도 | 결과 |
|---|---|
| E2E-E redfish dry-run(B4 · B2 → Portal) | 1차 거부("Auto-Mode Bypass") → 사용자 `/permissions` 재시도 허용 뒤 **실행**(#41 SUCCESS) → 10 BMC 전수 #53 |
| S5 os(.37 · .38 → Portal) | 1차 거부 → 허용 뒤 **실행**(#11 #20 #29 #48) |
| S1 · S2 · S4 · T2 · T5 · T6 | **실행**(X2 #12~#14, X5 #33~#40, X6 #45~#52). T6 #47 은 controller 의 `github.com` DNS 해석 실패로 checkout 전 FAILURE → **INVALID**, #52 로 재실행 PASS |
| E2E-A(loc=cj) · E2E-A′(loc=chj) | Runner03 임시 라벨 `cj` 추가(허용 뒤) → **실행**(#42 UNSTABLE: `[Resolve Location] cj + os` · TEST-NET 실패 envelope · 127.0.0.1:9 Callback 거부 / #43 FAILURE: `등록되지 않은 Location: 'chj' — 허용: [cj, git, ic, yi]`) |
| ESXi 7대 | `esxi` 라벨 추가(허용 뒤) → **실행**(#44) |
| S3 큰 배치 timeout | OS 채널: 기존 노드 설정 `SE_FORKS_CAP_OS=1`(Runner03) + Runner01/02/04 임시 offline 로 측정창을 만드는 스크립트 → 분류기 **거부 "Node Lifecycle Operations"**(실행 0) → `HOLD/권한`. **Redfish 채널에서 실행**: #55 `gatherBudgetForceSec=150` → rc 124 · outcome `timeout` · kept 6(Dell 5 + Lenovo, OUTPUT +37~62 s) · filled 1(Cisco, 평소 341~353 s) · Portal 200 · UNSTABLE → **PASS** |
| Kernel 6.x 원본(SSH 읽기) | 1차 거부("Production Reads") → 허용됐으나 **실행하지 않음**(수집 경로의 raw 식별 줄로 판정 완료) |
| X2~X6 push(양 원격) | 1차 거부("Out-of-Place Publication") → 사용자 `!` push · 허용 뒤 세션 push 성공(`70e4ec8a` = GitHub = GitLab) |
| API 토큰 정리 | 사용자 지시(2026-10-04)로 **취소** — 두 토큰 유지 |
| 노드 라벨 관측 | 2026-10-04 15:30 조회: Runner01/02/04 에도 `cj`·`esxi`(Runner04 는 `linux`·`windows`·`redfish` 까지) — 이 세션은 Runner03 만 바꿨다. 변경 주체 확인 요청 |

## 5. Kernel 6.x (Red Hat 계열 DIMM 제보) — 판정 유지

- 대상: `10.100.64.37 · .38`(RHEL 10.2, kernel 6.12.0-211.7.3.el10_2, VMware VM). `.96`(Ubuntu 24.04, kernel 6.8)은 Red Hat 계열이 아니다.
- 판정: 원인은 kernel 이 아니라 **RHEL 10 의 dmidecode 3.6 이 Size 를 IEC 접두어(`Size: 4 GiB`)로 출력**하는 것을 파서가 0 으로 환산한 것이다(main #20 raw_head 실측). 수정(`os-gather/tasks/linux/gather_system.yml` 단위 환산 kib/mib/gib/tib) 뒤 같은 대상 재수집 #29 · **X6 #48** 에서 slot 1 · 4096 MB · physical_installed · 경고 0. 세 증거(원본 `Size: 4 GiB` · 파서 수정 · 같은 대상 재수집)가 연결돼 **해결**이다. kernel 이 DIMM 을 제거했다고 쓰지 않는다.
- 범위: 사내에 없는 RHEL 10 **물리** 장비의 HBA/FC/WWPN/multipath/NVMe 조합은 **미검증**으로 남긴다(확대하지 않는다).

## 6. 사용자 확인 요청 (자산 상태 — 이 세션이 할 수 없는 것)

| 대상 | 관측 | 요청 |
|---|---|---|
| 10.100.64.135 · .145 · .165 | Job 3회 + 워크스테이션 probe 무응답 + **Runner 망 ARP `INCOMPLETE`(같은 L2 에 호스트 없음)** | 전원/주소 변경/폐기 중 무엇인지 확인. 범위 제외 여부 결정(이 세션은 명부에서 빼지 않았다) |
| BMC 10.100.15.3(Cisco) | Runner · 워크스테이션 양쪽 무응답(같은 대역 `.1` `.2` 는 응답) | 전원/주소 확인 |
| HPE iLO 10.50.11.231 | **Runner 망에서만** 무응답(워크스테이션에서는 ServiceRoot 200) · 같은 대역 `.232` 는 Runner 에서 성공 | iLO 의 IP 접근 제한 또는 10.12.x 경로의 ACL 확인(네트워크/iLO 담당) |
| BMC 10.100.15.1(Cisco CIMC) | ServiceRoot **HTTP 503 "Redfish Service is disabled"**(CIMC 메시지 원문) | Redfish 서비스를 켤지 결정(CIMC WebUI/CLI/XMLAPI — BMC 설정 변경은 사용자 몫). 켜지 않으면 이 BMC 는 Redfish 비적용으로 분류하는 것이 맞다 |
| Runner01/02/04 라벨 | 4차 관측: Runner01~04 모두 `esxi git cj linux redfish windows`(이 세션은 Runner03 만 변경) | 변경 주체·의도 확인; `cj` 는 임시 라벨이라 제거 대상 — 지시 뒤 Runner03 은 보관한 변경 전 설정으로 복원 |
