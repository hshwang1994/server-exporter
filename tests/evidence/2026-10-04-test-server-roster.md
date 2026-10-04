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
| 8 | 10.100.64.96 | svr06 | Dell PowerEdge R760(BMC 10.100.15.34) | 물리 | Ubuntu 24.04 (kernel 6.8 — 저장소 기록, Red Hat 계열 아님) | os(linux) | 22 open(10-03) | 0 | 0 | HOLD/권한 |
| 9 | 10.100.64.120 | — | 미확인 | 미확인(VM 추정 — 미확인) | Windows(버전 미확인) | os(windows) | 5985·5986 open(10-03); production #57/#58(2026-10-03, legacy) 수집 이력 | 0 | 0(이번) | HOLD/권한(S4) |
| 10 | 10.100.64.161 | — | 미확인 | VM | RHEL 8.10, Python 3.6(raw fallback) | os(linux) | 22 open(10-03); production #57/#58 이력 | 0 | 0 | HOLD/권한(S1) |
| 11 | 10.100.64.162 | — | 미확인 | VM(추정) | 미확인(production #57/#58 입력) | os(linux) | production #57/#58 이력 | 0 | 0 | HOLD/권한(S1) |
| 12 | 10.100.64.163 | — | 미확인 | VM | RHEL 9.2(09-03: TCP 무응답) | os(linux) | 무응답(09-03) · production #57/#58 입력 | 0 | 0 | HOLD/권한 — 실행 뒤 조건 기록 |
| 13 | 10.100.64.165 | — | 미확인 | VM | RHEL 9.6 | os(linux) | 22 closed(10-03) | 0 | 0 | HOLD/권한 — 실행 뒤 조건 기록 |
| 14 | 10.100.64.145 | — | 미확인 | VM | RHEL 9.6 | os(linux) | 미측정(10-03) | 0 | 0 | HOLD/권한 |
| 15 | 10.100.64.156 | cicd-gitlab | 미확인 | VM | Ubuntu 24.04 | os(linux) | 사내 GitLab 호스트 — 수집 대상 포함 여부 사용자 확인 | 0 | 0 | HOLD/권한 |
| 16 | 10.100.64.135 | — | 미확인 | 미확인 | RHEL 계열(08-12 실측, 상세 미확인) | os(linux) | production #56 입력(10-03) | 0 | 0 | HOLD/권한 |
| 17 | 10.100.64.33~.36 | Jenkins Runner01~04 | 미확인 | VM | RHEL 계열(Runner; `/app/ansible-env` python 3.12.9) — 자기 자신 수집 대상 포함 여부 사용자 확인 | os(linux) | 22 open(10-03) | 0 | 0 | HOLD/권한 |
| 18 | 10.100.64.37 · .38 | — | 미확인 | VM | **RHEL 10.2 예정(저장소 기록 "RHEL 10.2 예정 VM 2대") — Kernel 6.x 후보. 실제 `uname -r` 미확인** | os(linux) | 22 open(10-03) | 0 | 0 | **HOLD/권한 — S5 Kernel 6.x** |
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
| OS Linux | 13(+Runner 4 · GitLab 1 포함 여부 확인) | 0 | 13 | S1/S2/S3/S5 HOLD/권한 |
| OS Windows | 1 | 0 | 1 | S4 HOLD/권한 |
| ESXi | 7 | 0 | 7 | `esxi` 라벨 노드 없음(GP-4) + 트리거 HOLD |
| Redfish | 10 | 0 | 10 | E2E-E dry-run HOLD/권한(시도 기록 §4) |
| TEST-NET(통제 실패 경로) | 2(192.0.2.10/.11) | main #4~#6(10-03~04) · CI #10 T2/T6(§4) | — | 실호스트 수집이 아니다 |

**전체 완료 조건(§0-4 "누락 0건") 미충족.** 접속 실패·환경 미준비 대상을 명부에서 빼지 않았다 — 각 행의 "실행 뒤 조건 기록" 은 실제 실행에서 관측한 `diagnosis` 로만 비적용/실패를 구분한다는 뜻이다.

## 4. 이번 작업에서 시도한 것 · 거부/부재

(채움 — CI #10 · main Job 트리거 결과)

## 5. Kernel 6.x (Red Hat 계열 DIMM 제보)

- 후보: `10.100.64.37 · .38`(RHEL 10.2 예정 — kernel 6.12 계열로 추정되나 **미확인**). `.96`(Ubuntu 24.04, kernel 6.8)은 Red Hat 계열이 아니라 제보 재현 환경이 아니다. RHEL 9.6/kernel 5.14 자료는 재현 자료가 아니다(검토 §0-2).
- 필요한 원본: `uname -r` · `/etc/os-release` · `dmidecode -t 17` 원문+rc+stderr · `/sys/firmware/dmi/tables/DMI` 접근 가능 여부 · `/proc/meminfo` · 같은 시점의 `data.memory`. 획득 경로는 SSH 읽기(2026-10-03 "Production Reads" 거부) 또는 main Job S5 실수집(실호스트 트리거 — HOLD/권한). 어느 쪽도 이번에 열리지 않았다.
- 코드 쪽에서 미리 해 둔 것: `MAIN_CONTRACT["S5"]` 가 envelope 의 `data.system.kernel` major ≥ 6 을 요구해, 5.x 호스트 결과가 S5 증거로 섞이지 못하게 한다. DIMM 정확성은 원본 대조 없이는 말하지 않는다(미재현 ≠ 해결).
