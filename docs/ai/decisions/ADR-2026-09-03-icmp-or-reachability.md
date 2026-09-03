# ADR 2026-09-03 — reachable 판정에 ICMP Echo 를 OR 조건으로 추가

- 상태: Accepted
- 결정: 사용자 (2026-09-03 대화 — 지시 원문 그대로 반영)
- 작성: AI (Claude Code)
- 관련 rule: 27 R1 (판정 순서), 13 R1/R5/R7 (schema 3종 + 문서 동반 갱신),
  96 R1-B (envelope shape 보존), 70 R8 (rule 본문 의미 변경 → 본 ADR)

## 컨텍스트 (Why)

종전 `reachable` 은 **관리 TCP 포트의 응답만** 근거로 삼았다 — 연결 성공 또는 RST 관측.
ICMP 는 구현 자체가 없었고, 그 결정은 2026-08-12 에 코드 주석 두 곳
(`precheck_bundle.py:138,181`)과 rule 27 Forbidden 절에 명시돼 있었다.

그 결정의 이유는 **한 방향의 오판**을 막는 것이었다.

> 관리망은 ICMP 를 막아 두는 일이 흔하다. 핑으로 판정하면 443 으로 멀쩡히 답하는 BMC 를
> 죽은 장비로 오판한다.

맞는 지적이고 지금도 유효하다. 그런데 **반대 방향 오판**이 남아 있었다.

방화벽이 관리 포트 TCP 를 **DROP**(reject 가 아니라 조용히 버림)하는 구간에서는, 서버가
살아 있어도 TCP 로는 아무것도 관측되지 않는다. RST 조차 오지 않으므로 종전 코드는
`reachable=false` / `stage=reachable` / `TCP_CONNECT_FAILED` 로 확정했고, 운영자에게는
표준 1번 문장이 나갔다.

> 대상 IP에서 응답을 확인할 수 없습니다. IP 사용 여부와 네트워크 상태를 확인하세요.

즉 **봐야 할 곳은 방화벽인데 IP 대장을 뒤지게** 만들었다. 이 상태에서 ICMP 는 이미
"장비는 있다" 를 증명할 수 있는 유일한 관측 수단이었는데 쓰지 않고 있었다.

## 결정 (What)

`reachable` 을 **TCP 응답 OR ICMP 응답** 으로 넓힌다. 단, ICMP 는 Gate 가 아니다.

### 판정표 (정본: `precheck_bundle._resolve_reachability`)

| 관측 | `reachable` | `port_open` | `failure_stage` | `failure_code` | 사용자 문장 |
|---|---|---|---|---|---|
| 관리 TCP 연결 성공 | true | true | — | `null` | — |
| 관리 TCP 거부(RST) | true | false | `port` | `TCP_CONNECTION_REFUSED` | 2번 |
| TCP 무응답 + ICMP 응답 | true | false | `port` | `TCP_CONNECT_FAILED` | 2번 |
| TCP 무응답 + ICMP 무응답 | false | false | `reachable` | `TARGET_UNREACHABLE` | 1번 |
| 주소 해석 실패 | false | false | `reachable` | `DNS_RESOLUTION_FAILED` | 1번 |

### 지켜야 할 경계 (사용자 명시)

1. ICMP 를 **앞단 필수 Gate 로 만들지 않는다** — TCP 를 먼저 보고, TCP 가 아무 응답도
   주지 않았을 때만 마지막으로 1회 확인한다. TCP 가 응답하면 `icmp_check` 는 **호출조차
   되지 않는다.** 종전 결정의 이유가 그대로 지켜지는 지점이다.
2. **ICMP 실패는 아무것도 실패시키지 않는다** — 무응답 / 차단 / `ping` 부재 / 권한 부족을
   구분 없이 "추가 근거 없음" 으로만 취급한다. 판정이 종전(TCP 전용)과 같아진다.
3. **`ICMP_CONNECT_FAILED` 같은 전용 code 를 만들지 않는다** — ICMP 는 도달 근거를 더할 뿐
   실패를 만들지 않으므로 소비 시스템이 분기할 상태가 아니다.
4. `reachable=true` 인데 관리 포트를 못 열었으면 **기존 흐름대로 `port` 단계 실패**.
5. `protocol → auth → gather → fallback` 흐름과 포트 후보(OS `5986/5985/22`,
   ESXi·Redfish `443`)는 **변경 없다.**
6. 예산: ICMP 는 "TCP 전 포트 무응답" 경로에서만, Echo **1회**(기본 1초)만 소비한다.
   성공 경로와 RST 경로의 추가 시간은 **0** 이다.

### failure_code — 이름 정리

`TCP_CONNECT_FAILED` 라는 이름이 ICMP 를 포함한 최종 도달 실패를 가리키는 것은 사실과
어긋난다. 그래서 code 를 둘로 나눴다.

- **`TARGET_UNREACHABLE`** (신규, `stage=reachable`) — TCP 도 ICMP 도 무응답.
- **`TCP_CONNECT_FAILED`** (유지, `stage=port` 로 **범위 축소**) — ICMP 는 응답하는데 관리
  TCP 포트만 무응답(RST 미관측). 이름이 가리키는 사실("TCP 연결에 실패했다")은 그대로다.

문장 매핑도 관측을 따라 옮겼다. ICMP 로 존재가 확인된 대상에게 "IP 사용 여부를 확인하세요"
는 사실과 어긋나므로 `TCP_CONNECT_FAILED` 는 1번 → **2번**(방화벽·관리 서비스 확인)이다.
`TARGET_UNREACHABLE` 은 사용자 지시대로 **종전과 같은 1번 문장**을 유지한다.
표준 문장 집합은 5개 그대로다 — 문장을 늘리지 않고 매핑만 옮겼다.

### 구현 수단 — raw socket 이 아니라 `ping` 명령

ICMP raw socket 은 `CAP_NET_RAW`(root)가 필요하다. 비특권 대안인
`SOCK_DGRAM + IPPROTO_ICMP` 는 커널 `net.ipv4.ping_group_range` 설정에 좌우돼 배포판·
에이전트마다 되고 안 되고가 갈린다. 배포판 `ping` 은 setuid/capability 가 붙어 있어
비특권 계정에서 그대로 동작하고, 외부 파이썬 의존도 늘지 않는다(stdlib `subprocess` —
rule 10 R2 허용 목록). `ping` 이 없는 환경이면 "확인 불가" 로 떨어져 종전 동작이 된다.

## 결과 (Impact)

### 코드

| 파일 | 변경 |
|---|---|
| `common/library/precheck_bundle.py` | `icmp_check` / `_icmp_command` / `_resolve_reachability` / `_join_detail` 추가, `_tcp_failure_code` 반환값 변경, 호출부 2곳 재배선, `icmp_probe` / `timeout_icmp` 파라미터 |
| `common/tasks/precheck/run_precheck.yml` | `_precheck_icmp_probe` / `_precheck_timeout_icmp` passthrough (`default(omit)` — 기본값 정본은 모듈) |
| `schema/field_dictionary.yml` | `diagnosis.failure_code` enum 8 → 9, `failure_stage` / `failure_code` help 갱신 |
| `common/vars/failure_reasons.yml` | code → 문장 매핑 주석 갱신 (문장 자체는 불변) |
| 3 channel `site.yml` | 주석만 (stale 한 "ping→port→protocol→auth" 표기 정정) |

### envelope

**shape 불변.** 최상위 13 필드도, `diagnosis` 7키 + `details` 도 그대로다. ICMP 관측 근거는
`errors[].detail` 문자열에만 붙는다(`icmp: Echo Reply 확인` / `icmp: 응답 없음 (rc=1)`).
`diagnosis.details` 에 새 키를 넣지 않았다 — rule 96 R1-B 와 2026-05-01
`diagnosis.details.detail` revert 선례를 따른 것이다.

### 호출자 (Portal) 영향 — **유일한 breaking 지점**

종전 `failure_code == "TCP_CONNECT_FAILED"` 로 "대상 무응답" 을 분기하던 소비자는
`TARGET_UNREACHABLE` 을 받도록 갱신해야 한다. `failure_reason` / `errors[].message` 는
바뀌지 않으므로 **문장을 표시만 하는 화면은 영향이 없다.**

### 운영

- dead host 1대당 최대 +1초 (ICMP 1회). 정상 수집 경로는 +0.
- controller(Jenkins Agent)에 `ping` 이 있어야 이득을 본다. 없으면 종전과 동일 동작이며
  그 사실이 `errors[].detail` 에 남는다.

### 회귀

- `tests/unit/test_precheck_icmp_reachability.py` 신설 (24 케이스) — OR 판정 / Gate 아님 /
  예산 / 전용 code 금지 / envelope shape 불변을 잠근다.
- 기존 precheck 하네스 10곳은 `tests/precheck_stub.py` 로 ICMP 결과를 주입한다
  (실 `ping` 프로세스 금지 — 느리고 실행 환경에 따라 결과가 갈린다).
- 전체 3312 passed / 0 failed (`tests/e2e_browser` 제외 — playwright 미설치).

## 대안 비교 (Considered)

| 안 | 내용 | 판단 |
|---|---|---|
| **A. 채택** | TCP 우선 → 전멸 시 ICMP 1회, OR 판정, 전용 code 없음 | 사용자 지시 그대로. 양방향 오판을 모두 막고 예산 증가가 실패 경로에 국한된다 |
| B. ICMP 를 앞단 Gate | 종전 "ping → port" 구조 | **거부.** ICMP 차단 관리망에서 정상 BMC 를 전부 죽은 것으로 오판한다. 금지 이유가 그대로 살아 있다 |
| C. `TCP_CONNECT_FAILED` 이름 유지 | code 추가 없이 의미만 확장 | **거부.** ICMP 를 포함한 최종 실패를 "TCP 연결 실패" 라 부르면 이름이 관측과 어긋난다 |
| D. `PORT_CONNECT_FAILED` 신설 + `TCP_CONNECT_FAILED` 폐기 | 값 재활용 없이 완전 교체 | 보류. 의미가 더 깨끗하지만 enum 이 2개 흔들려 호출자 이행 비용이 두 배다. `TCP_CONNECT_FAILED` 의 문자적 의미가 새 용법에서도 참이라 재활용이 안전하다 |
| E. ICMP 결과를 `diagnosis.details` 에 노출 | 소비 시스템이 ICMP 여부로 분기 | **거부.** envelope 확장은 호환성 작업 범위 밖이다 (rule 96 R1-B). 근거는 `errors[].detail` 로 충분하다 |
| F. raw / dgram socket 직접 구현 | 프로세스 미기동 | 보류. root 권한 또는 커널 설정 의존이라 에이전트마다 갈린다. `ping` 이 실제로 막히는 사례가 관측되면 2-tier 로 확장 |

## 미확인 (실장비)

본 변경은 **오프라인 회귀까지만 검증됐다.** 다음은 실 환경에서 확인해야 한다.

1. Jenkins Agent(controller)에 `ping` 이 있고 비특권 계정에서 Echo 가 나가는가.
2. 방화벽 DROP 구간의 실제 대상에서 `stage=port` + `TCP_CONNECT_FAILED` 가 나오는가.
3. dead host N대 배치 실행의 wall-clock 증가폭이 예상(+1초/대) 범위인가.
