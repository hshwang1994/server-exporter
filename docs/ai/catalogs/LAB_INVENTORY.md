# LAB_INVENTORY — 실장비 토폴로지

> 2026-08-13 전면 재작성. 종전 문서는 cycle-015 / cycle-016 / 2026-08-12 정정이 겹겹이
> 쌓이면서 서로 어긋나 있었다 (§2는 `15.34 ↔ 64.96`, §4는 `15.33 ↔ 64.96`이라 적었다).
> 사용자가 제공한 장비 목록을 기준으로 다시 쓰고, 도달성은 직접 측정한 값을 적는다.

자격증명은 여기 없다. 세 곳으로 나뉜다.

| 내용 | 위치 |
|---|---|
| 계정·비밀번호 | `vault/.lab-credentials.yml` (gitignored) |
| IP·모델·짝 정보 | `inventory/lab/*.json` (gitignored) |
| sanitized 토폴로지 | 이 파일 |

수집 실행에 쓰는 자격증명은 또 다르다. `vault/<loc>/…` 의 ansible-vault 파일이며
`vault/.lab-credentials.yml` 과는 별개다. 후자는 브라우저 E2E(`tests/e2e_browser/lab_loader.py`)가 읽는다.

## 1. 권한

사용자 명시 (2026-04-29):

> 이 프로젝트는 ai에게 모든 권한을 준다 … 실장비 권한도 하네스에게 주겠다 어짜피 테스트서버이다

근거 ADR: `docs/ai/decisions/ADR-2026-04-28-security-policy-removal.md`,
`docs/ai/decisions/ADR-2026-04-29-lab-access-grant.md`

## 2. 베어메탈 8대 — BMC와 OS가 같은 기계

이 8쌍이 이 lab의 핵심 자산이다. 같은 물리 서버를 BMC 경로와 OS/ESXi 경로 양쪽에서
수집할 수 있어서, 채널 간 `correlation.serial_number` 일치 여부를 실증할 수 있다.

| # | 모델 | BMC | 얹힌 것 | OS/ESXi IP |
|---|---|---|---|---|
| esxi01 | Cisco-TA-UNODE-G1 | 10.100.15.1 | ESXi 7.0.3 | 10.100.64.1 |
| esxi02 | Cisco-TA-UNODE-G1 | 10.100.15.2 | ESXi 7.0.3 | 10.100.64.2 |
| esxi03 | Cisco-TA-UNODE-G1 | 10.100.15.3 | ESXi 7.0.3 | 10.100.64.3 |
| svr01 | Dell-PowerEdge R760 | 10.100.15.27 | ESXi 9.0.0 | 10.100.64.91 |
| svr02 | Dell-PowerEdge R760 | 10.100.15.28 | ESXi 9.0.0 | 10.100.64.92 |
| svr03 | Dell-PowerEdge R760 | 10.100.15.31 | ESXi 9.0.0 | 10.100.64.93 |
| svr05 | Dell-PowerEdge R760 | 10.100.15.33 | ESXi 9.0.0 | 10.100.64.95 |
| svr06 | Dell-PowerEdge R760 | 10.100.15.34 | Ubuntu 24.04 | 10.100.64.96 |

**시리얼 대조가 자명하지 않은 이유.** `common/tasks/normalize/build_correlation.yml:18-39`을
보면 채널마다 읽는 원본이 다르다. Redfish는 BMC가 보고하는 `ComputerSystem.SerialNumber`,
ESXi는 하이퍼바이저가 본 SMBIOS(`ansible_product_serial`), Linux는 DMI `product_serial`이다.
게다가 Linux는 `data.hardware` 섹션 자체가 없어 `data.system.serial_number` 분기로 떨어진다.
그래서 이 9쌍 대조는 "같은지 확인"이 아니라 **채널 간 시리얼 계약을 확정하는 작업**이다.

## 3. BMC 외 대상

| 구분 | IP | 비고 |
|---|---|---|
| HPE iLO6 | 10.50.11.231 | ProLiant DL380 Gen11 |
| Lenovo XCC | 10.50.11.232 | |
| Windows | 10.100.64.120 | |
| Linux VM | 10.100.64.161(RHEL 8.10, Python 3.6 raw fallback) / .165(RHEL 9.6) / .145(RHEL 9.6) / .156(Ubuntu 24.04 `cicd-gitlab`) | 2026-09-03 실측 정정: .167/.169 는 별도 장비가 아니라 .165/.161 의 bond1 IP. .163(RHEL 9.2) 은 TCP 무응답. RHEL 10 / Rocky 없음 |
| Jenkins master | 10.100.64.152 / .153 | |
| Jenkins agent | 10.100.64.154 / .155 | agent는 `ic/chj/yi/git` 4 label을 모두 갖는다 |

> 2026-08-14: Location ID `ich` 를 `ic` 로 바꿨다 (`agent_label` 포함). **Jenkins 노드의 실제
> label 은 아직 `ich` 다** — 재설정 전까지 `loc=ic` 잡은 Agent 를 못 잡고 대기한다.
> NEXT_ACTIONS `LOC-1` 참조.

미확인으로 남긴 것: `10.100.64.135`(2026-08-12 실측에서 Windows가 아니라 RHEL 계열이었다),
`10.100.64.163` / `.167` / `.169`(사용자 제공 목록에 없다).

## 4. 도달성 실측 (2026-08-13)

인증 없이 TCP 연결만 확인했다. BMC/ESXi는 443, Linux는 22, Windows는 5985·5986.

**21/22 도달.** 이 결과가 이전 기록 몇 개를 뒤집는다.

| 대상 | 이전 기록 | 실측 |
|---|---|---|
| 10.100.15.1 | cycle-016 "lab 부재 / non-Redfish" | [OK] 443 OPEN |
| 10.100.64.120 | cycle-015 "사내 부재" | [OK] 5985·5986 OPEN |
| 10.50.11.231 | 2026-08-12 정정본 "종전 timeout 기록은 stale" | [OK] 443 OPEN — 정정본이 맞다 |
| 10.100.15.3 | cycle-016 "ping fail 부재" | [WARN] 443/80/22/623/5000 전부 timeout |

`10.100.15.3`은 RST가 한 번도 오지 않았다. 짝인 `10.100.64.3`은 열려 있으니 라우팅
문제는 아니다. 다만 이 관측만으로 방화벽 drop인지 전원 off인지는 가려낼 수 없다.
`CLAUDE.md` §7이 금지하는 "timeout만 보고 IP 미사용 단정"을 하지 않고 관측 사실로만 남긴다.

## 5. 네트워크 구간

| 구간 | 용도 |
|---|---|
| 10.100.64.0/24 | Jenkins + OS/ESXi 수집 대상 |
| 10.100.15.0/24 | Dell + Cisco BMC |
| 10.50.11.0/24 | HPE + Lenovo BMC |

Jenkins agent(10.100.64.0/24)에서 세 구간 모두 닿는다.

## 6. 알려진 공백

**ESXi 9.0.0 어댑터 부재는 2026-08-13 에 해소됐다.** `adapters/esxi/esxi_9x.yml` 을
추가했고 실장비 3대(`10.100.64.91~93`)에서 `esxi_generic` → `esxi_9x` 로 바뀌는 것을
확인했다. 수집 섹션은 6개로 전후 동일하다 — 애초에 데이터 손실이 아니라 관측
정확도 문제였다. 근거: `tests/evidence/2026-08-13-adapter-oem-esxi9-live.md`.

**`vault/.lab-credentials.yml` 의 `credentials_provided: false` 는 그 파일 기준이다.**
실제 수집은 `vault/<loc>/esxi.yml` 을 쓰고, 그쪽 자격증명으로 9.0.0 호스트 수집이
된다는 것을 실측으로 확인했다.

**아직 수집이 안 되는 것 3대** (2026-08-13 실측, 전·후 동일)

| 대상 | 실패 | 관측 |
|---|---|---|
| 10.100.15.1 | protocol | 443 은 열려 있는데 ServiceRoot 를 제대로 주지 않는다 |
| 10.100.15.3 | reachable | 전 포트 무응답. 방화벽 drop 인지 전원 off 인지 안 갈린다 |
| 10.100.64.95 | protocol | 443 응답은 있으나 vSphere 응답이 아니다 |

## 7. 갱신 시점

호스트가 늘거나 줄 때, 벤더가 추가될 때, 도달성이 바뀔 때 이 문서를 고친다.
자격증명은 여기 적지 않는다 — `scripts/ai/verify_no_plaintext_secret.py`가 막는다.
