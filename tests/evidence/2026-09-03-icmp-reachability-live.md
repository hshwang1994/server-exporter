# 2026-09-03 — reachable ICMP OR 판정 실장비 검증

> **§5 에 Jenkins 파이프라인 실행(#200 / #201) 결과가 있다.** 아래 §0~§3 은 그 전에
> 러너에서 Gather stage 만 재현한 예비 실행이며, 파이프라인 결과가 상위 증거다.
>
> 대상 커밋: `66e8303c` (main). 정본: `docs/ai/decisions/ADR-2026-09-03-icmp-or-reachability.md`
> 실행 위치: Jenkins Agent `jenkins-agent-ops` (10.100.64.154, Ubuntu 24.04 / kernel 6.8.0-111,
> ansible-core 2.20.3, `/opt/ansible-env`). 계정 `cloviradmin` (비특권, sudo 그룹).
> 실행 형태: `Jenkinsfile_portal` Gather stage 와 동일한 환경변수·명령
> (`REPO_ROOT` / `ANSIBLE_CONFIG` / `ANSIBLE_JSON_OUTPUT_FILE` / `INVENTORY_JSON` +
> `ansible-playbook <site.yml> -i <inventory.sh> -e se_location=git`).
> **차이 1건**: vault 비밀번호(Jenkins credential `server-gather-vault-password`)를 쓰지 않았다.
> 그래서 자격증명이 필요한 **본 수집 단계는 실행되지 않았다** — 이 검증의 대상인 precheck 판정
> 구간은 자격증명 이전이라 영향이 없다 (아래 CASE 3/4 의 auth·fallback 실패가 그 결과다).

## 0. 에이전트 전제 (RE-1)

```
$ ls -l /usr/bin/ping ; getcap /usr/bin/ping
-rwxr-xr-x 1 root root 89800 Feb 10  2026 /usr/bin/ping
/usr/bin/ping cap_net_raw=ep
$ sysctl net.ipv4.ping_group_range
net.ipv4.ping_group_range = 1	0
```

- `ping` 은 `cap_net_raw=ep` 라 **비특권 계정에서 그대로 동작**한다.
- `ping_group_range = 1 0` 은 **비특권 ICMP 소켓이 꺼져 있다**는 뜻이다. ADR 대안 F
  (`SOCK_DGRAM + IPPROTO_ICMP` 직접 구현)를 골랐다면 이 에이전트에서 **작동하지 않았다.**
  `ping` 명령 선택이 실측으로 확인됐다.

## 1. 대상 사전 관측 (러너에서 직접)

| IP | ICMP | 5986 | 5985 | 22 | 443 | 성격 |
|---|---|---|---|---|---|---|
| 10.100.64.163 | 없음 | timeout | No route | timeout | — | TCP·ICMP 모두 무응답 |
| 10.100.64.145 | **REPLY** | **timeout** | **timeout** | open | **timeout** | RHEL 9.6 VM — 관리 포트 DROP, ICMP 는 열림 |
| 10.100.64.120 | **없음** | open | open | — | open | Windows 2022 — **ICMP 차단**, 관리 포트 열림 |

`.145` 가 이번 변경이 겨냥한 상황(방화벽이 관리 TCP 를 버리고 ICMP 는 답함)을 lab 설정 변경
없이 그대로 갖고 있었고, `.120` 이 그 반대(ICMP 차단 + TCP 정상)를 갖고 있었다.

## 2. 실행 결과

### CASE 1 — ICMP 만 응답 (신규 분기) : `redfish` / 10.100.64.145

원본: `2026-09-03-icmp-live/redfish_icmp_only_10.100.64.145.json`

| 항목 | 값 |
|---|---|
| `status` | `failed` |
| `diagnosis.reachable` | **`true`** (ICMP Echo Reply 근거) |
| `diagnosis.port_open` | `false` |
| `diagnosis.failure_stage` | **`port`** |
| `diagnosis.failure_code` | **`TCP_CONNECT_FAILED`** |
| `diagnosis.failure_reason` | 대상 IP의 관리 포트에 연결할 수 없습니다. 방화벽과 관리 서비스 상태를 확인하세요. (2번) |
| `errors[0].detail` | `port=443: [Errno 113] No route to host; icmp: Echo Reply 확인 \| ...` |
| `diagnosis.details` | `channel/adapter_candidate/checked_ports/hostname_source` — **새 키 없음** |

**종전 동작과의 차이**: 같은 상황이 종전에는 `reachable=false` / `stage=reachable` /
`TCP_CONNECT_FAILED` / **1번 문장("IP 사용 여부와 네트워크 상태를 확인하세요")** 이었다.
운영자를 방화벽이 아니라 IP 대장으로 보내던 오안내가 실제로 사라진 것을 확인했다.

### CASE 2 — TCP·ICMP 모두 무응답 : `os` / 10.100.64.163

원본: `2026-09-03-icmp-live/os_unreachable_10.100.64.163.json`

| 항목 | 값 |
|---|---|
| `diagnosis.reachable` | `false` |
| `diagnosis.failure_stage` | `reachable` |
| `diagnosis.failure_code` | **`TARGET_UNREACHABLE`** (종전 `TCP_CONNECT_FAILED`) |
| `diagnosis.failure_reason` | 대상 IP에서 응답을 확인할 수 없습니다. IP 사용 여부와 네트워크 상태를 확인하세요. (1번 — **종전과 동일**) |
| `errors[0].detail` | `port=5986: 연결 시간 초과 (timeout=2s); port=5985: [Errno 113] No route to host; port=22: 연결 시간 초과 (timeout=2s); icmp: 응답 없음 (rc=1) \| 확인한 관리 포트: ...` |
| `details.checked_ports` | `[5986, 5985, 22]` — 포트 후보 종전 그대로 |

### CASE 3 — ICMP 차단 + TCP 정상 (Gate 아님 확인) : `os` / 10.100.64.120

| 항목 | 값 |
|---|---|
| `diagnosis.reachable` / `port_open` / `protocol_supported` | **`true` / `true` / `true`** |
| `details.checked_ports` | `[5986]` (첫 후보에서 중단) |
| `details.detected_os` / `selected_port` | `windows` / `5986` |

ICMP 가 완전히 차단된 실장비에서 precheck 가 **정상 통과**했다. ICMP 를 앞단 Gate 로 만들었다면
이 호스트는 도달 실패로 뒤집혔을 것이다 — 금지 결정의 원래 이유가 실측으로 지켜졌다.
(이후 `fallback` / `OUTPUT_BUILD_FAILED` 는 위 §0 의 vault 미사용 때문이며 본 변경과 무관하다.)

### CASE 4 — ICMP 응답 + 일부 포트 DROP, 다른 후보로 성공 : `os` / 10.100.64.145

| 항목 | 값 |
|---|---|
| `diagnosis.reachable` / `port_open` / `protocol_supported` | `true` / `true` / `true` |
| `details.checked_ports` | `[5986, 5985, 22]` |
| `details.detected_os` / `selected_port` | `linux` / `22` |

5986·5985 가 DROP 이어도 22 에서 SSH 를 확인해 **후보 포트를 끝까지 훑는 기존 동작(rule 27 R2)이
유지**됐다. TCP 가 성공했으므로 ICMP 는 개입하지 않았다.
(이후 `auth` / `AUTH_PROBE_FAILED` 는 §0 의 vault 미사용 때문이다.)

## 3. 예산 실측 (RE-3)

dead host(10.100.64.163) 1대, `precheck_bundle` 단독 호출 2회씩:

| `icmp_probe` | 1회차 | 2회차 |
|---|---|---|
| `true` | 8.62 s | 8.75 s |
| `false` | 7.69 s | 7.50 s |

→ **+1.0 ~ 1.1 초 / dead host**. 설계값(Echo 1회, 기본 1초)과 일치한다.
성공 경로·RST 경로는 ICMP 를 호출하지 않으므로 증가분이 없다 (CASE 3/4 에서 확인).

## 4. 예비 실행의 한계 (→ §5 에서 해소)

- 러너 재현이라 Stage 1(Validate) / Stage 3(Validate Schema) / Stage 4(Callback) 는 돌지 않았다.
- vault 를 쓰지 않아 본 수집 성공 경로의 end-to-end 를 확인하지 못했다.

두 항목 모두 아래 §5 의 파이프라인 실행으로 해소됐다.

## 5. Jenkins 파이프라인 실행 (정식 경로)

Job `clovirone-server-gather` (`Jenkinsfile_portal`, `*/main`), Jenkins 마스터 10.100.64.152.

| 빌드 | 체크아웃 | 대상 | 결과 |
|---|---|---|---|
| #200 | `1fd9fa6d` | `os`: .163 / .145 / .120 | UNSTABLE (더미 callback) — Gather·Validate Schema 통과, envelope 3건 |
| #201 | `1fd9fa6d` | `redfish`: .145 | UNSTABLE (더미 callback) — envelope 1건 |

Stage 전량 실행 확인: `Resolve Location` → `Validate` → `Gather` → `Validate Schema` →
`Callback` → `Post Actions`. `UNSTABLE` 은 callback URL 이 더미(192.0.2.1)라 POST 가 실패한
결과이며 종전 빌드와 동일한 의도된 상태다 (rule 31 R2).
**체크아웃 SHA 는 두 빌드 모두 `1fd9fa6d679ef0c71fff915a0058d6f380ed6a82`** — push 성공이
아니라 실제 Job 체크아웃으로 확인했다 (rule 14).

### #200 — `os` 3대 (원본: `2026-09-03-icmp-live/build200_*.json`)

| 대상 | status | reachable / port / proto / auth | stage / code | 비고 |
|---|---|---|---|---|
| 10.100.64.163 | `failed` | F / F / F / null | `reachable` / **`TARGET_UNREACHABLE`** | 1번 문장. `detail` 에 `icmp: 응답 없음 (rc=1)` |
| 10.100.64.145 | **`success`** | T / T / T / **T** | — / — | ICMP 응답 + 5986·5985 DROP 이어도 22 로 **실수집 성공**. `adapter=os_linux_rhel`, `gather_mode=python_ok`, `credential_scope=git/os/linux` |
| 10.100.64.120 | **`success`** | T / T / T / **T** | — / — | **ICMP 차단 장비가 정상 수집**. `checked_ports=[5986]`, `adapter=os_windows_2022`, WinRM 인증 성공 |

`.145` / `.120` 는 vault 자격증명까지 태운 **본 수집 성공**이다. ICMP 도입이 성공 경로를
건드리지 않았음을 파이프라인 end-to-end 로 확인했고, 특히 `.120` 은 ICMP 가 완전히 차단된
실장비가 정상 수집된 사례라 "Gate 아님" 의 직접 증거다.

### #201 — `redfish` / 10.100.64.145 (원본: `build201_redfish_icmp_only_10.100.64.145.json`)

| 항목 | 값 |
|---|---|
| `status` | `failed` |
| `diagnosis.reachable` / `port_open` | **`true`** / `false` |
| `failure_stage` / `failure_code` | **`port`** / **`TCP_CONNECT_FAILED`** |
| `failure_reason` = `errors[0].message` | 대상 IP의 관리 포트에 연결할 수 없습니다. 방화벽과 관리 서비스 상태를 확인하세요. (2번) |
| `errors[0].detail` | `port=443: [Errno 113] No route to host; icmp: Echo Reply 확인 \| ...` |
| envelope | 13 필드 / 11 섹션 / `diagnosis` 키 7 + `details` — **shape 불변** |

종전 코드였다면 같은 장비가 `stage=reachable` + 1번 문장("IP 사용 여부와 네트워크 상태를
확인하세요")으로 나갔다. 방화벽을 봐야 할 상황에서 IP 대장을 뒤지게 하던 오안내가
정식 경로에서 사라진 것을 확인했다.

## 6. 남은 미검증

- **Portal 소비자 이행** — `failure_code == "TCP_CONNECT_FAILED"` 로 "대상 무응답" 을 분기하던
  코드가 있으면 `TARGET_UNREACHABLE` 을 받도록 갱신해야 한다 (NEXT_ACTIONS RE-4).
  이 저장소 밖 영역이라 여기서 확인할 수 없다.
- callback 수신 측 검증은 이번에도 더미 URL 이라 하지 않았다 (종전 빌드와 동일).
