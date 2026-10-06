# 실패했을 때 무엇을 보나

실패해도 봉투는 온다. 모양도 성공했을 때와 같다. 그래서 호출자는 "응답이 없다"를
따로 처리할 필요가 없다. 대신 봉투 안의 몇 개 필드로 무슨 일이 있었는지 읽으면 된다.

이 문서는 그 읽는 법을 다룬다.

## 어디를 먼저 보나

세 곳이면 충분하다.

1. `status` — 전부 실패인가, 일부만인가
2. `diagnosis.failure_stage` — 어느 단계에서 멈췄나
3. `errors[].message` — 사용자에게 보여 줄 문장

`failure_reason`과 `errors[0].message`는 같은 문장을 쓴다. 화면에 그대로 띄우면 된다.

## failure_stage — 멈춘 위치

여섯 값이다. 이건 "근본 원인"이 아니라 **작업 흐름이 어디까지 갔는가**를 나타낸다.

| 값 | 여기까지는 됐다 | 여기서 막혔다 |
|---|---|---|
| `reachable` | — | 관리 TCP 도 ICMP 도 응답이 없다 |
| `port` | 대상이 응답한다 (RST 또는 ICMP Echo Reply) | 관리 포트에 붙지 못한다 |
| `protocol` | 포트는 열려 있다 | 기대한 프로토콜로 응답하지 않는다 |
| `auth` | 프로토콜은 맞다 | 자격증명이 거부됐거나 금고를 못 열었다 |
| `gather` | 접속과 인증은 됐다 | 정보를 캐는 중에 실패했다 |
| `fallback` | — | 봉투 조립 자체가 실패해 최후 수단으로 만들었다 |

성공하면 셋 다 `null`이다. 반대로 실패인데 `failure_reason`이 `null`인 봉투는 나오지
않는다 — 조립기가 그 경우를 막는다.

## failure_code — 기계가 분기할 값

아홉 개로 고정이다. `message`는 사람이 읽는 문장이라 다듬어질 수 있지만 이 코드는
호출자가 조건문에 써도 되는 안정된 값이다.

| 코드 | 언제 |
|---|---|
| `DNS_RESOLUTION_FAILED` | 주소 해석 실패 |
| `TARGET_UNREACHABLE` | 관리 TCP 도 ICMP 도 응답이 없다 |
| `TCP_CONNECT_FAILED` | ICMP 는 답하는데 관리 TCP 포트가 응답 없이 끝났다 |
| `TCP_CONNECTION_REFUSED` | RST를 받았다 — 장비는 있고 포트가 닫혔다 |
| `PROTOCOL_CHECK_FAILED` | 포트는 열렸는데 기대한 응답이 아니다 |
| `AUTH_PROBE_FAILED` | 자격증명이 거부됐다 |
| `CREDENTIAL_SET_UNAVAILABLE` | 금고 파일이 없거나 못 열었다 |
| `GATHER_FAILED` | 수집 중 실패 |
| `OUTPUT_BUILD_FAILED` | 봉투 조립 실패 |

`DNS_RESOLUTION_FAILED`가 목록에 있지만 이 시스템은 IPv4만 받는다. 사용자 안내에서
DNS나 호스트명 확인을 권하지 않는다.

`TARGET_UNREACHABLE`은 2026-09-03에 추가됐다. 그 전에는 `TCP_CONNECT_FAILED` 하나가
"아무 응답 없음"과 "관리 포트만 응답 없음"을 겸했다. 도달 판정에 ICMP가 들어오면서
둘이 갈렸다 — **종전에 `TCP_CONNECT_FAILED` + `stage: reachable`로 분기하던 호출자는
`TARGET_UNREACHABLE`을 받도록 고쳐야 한다.**

## 사용자에게 보이는 문장

문장은 정해진 카탈로그에서 고른다 (정본: `common/vars/failure_reasons.yml`). 고르는 기준은
**`failure_code` + 대상 종류(OS / ESXi / Redfish) + 세부 사유**다 (2026-09-21). 전체 표는
[03-fields.md §4-1](03-fields.md) 에 있다. 포트 번호, 타임아웃 값, HTTP 상태 코드, 예외 문자열 같은 건
들어가지 않는다. 그런 건 `errors[].detail`에 간다.

대표 문장 몇 개만 보면 이렇다.

| 상황 | 문장 |
|---|---|
| 응답 없음 | 대상 서버가 응답하지 않습니다. 서버 전원 상태와 네트워크 연결을 확인하세요. |
| ping 은 되는데 관리 포트 무응답 | 대상 서버와 통신은 되지만 관리 포트에 연결할 수 없습니다. 방화벽과 접속 설정을 확인하세요. |
| 관리 포트 거부 (Redfish) | Redfish 접속이 거부되었습니다. 대상 장비의 Redfish 접속 설정과 방화벽을 확인하세요. |
| 응답이 기대와 다름 (ESXi) | 접속한 대상에서 ESXi 응답을 확인하지 못했습니다. 대상 종류와 ESXi 서비스 상태를 확인하세요. |
| 위치 Vault 복호화 실패 | 해당 위치(ic)의 Vault를 읽을 수 없습니다. |
| 인증 실패, 원인 미확정 (OS) | 해당 위치(ic)의 Vault 계정으로 대상 OS에 로그인하지 못했습니다. |
| 인증 거부 확인 (Redfish) | 대상 Redfish 계정과 개더링 표준 계정이 다르거나 권한이 없습니다. |
| 인증 후 수집 실패 (ESXi) | 대상 ESXi에는 로그인했지만 정보를 가져오지 못했습니다. |

몇 가지 원칙이 있다.

- **관측한 것만 말한다.** "통신은 되지만"은 ICMP 응답을 실제로 봤을 때만, "로그인했지만"은
  인증 통과를 실제로 봤을 때만 쓴다. 계약 테스트가 문장과 `diagnosis` 값이 어긋나는지 검사한다.
- **거부의 주체를 단정하지 않는다.** 연결 거부는 중간 방화벽이 보낼 수도 있어서 "서버가 거부했다"고
  쓰지 않는다.
- **"계정이 다르거나 권한이 없다"는 확인된 경우에만 쓴다.** 지금 확인할 수 있는 것은 Redfish 표준
  후보 전원의 401뿐이다. OS/ESXi는 거부 사실이 오류 문자열로만 와서 확정하지 않는다.
- **Redfish 표준 계정은 위치와 무관한 전역 Vault다.** 그래서 Redfish 문장은 "해당 위치의 Vault"가
  아니라 "개더링 프로젝트의 Vault" / "개더링 표준 계정"이라고 쓴다.

## 진단이 실제로 무엇을 했나

`diagnosis`의 앞 네 필드는 사전 점검 결과다. 여기서 오해하기 쉬운 지점 둘을 짚는다.

**`reachable`은 TCP와 ICMP의 OR다. 핑 게이트가 아니다.** (2026-09-03 변경)

순서가 중요하다. 먼저 관리 TCP 포트를 본다. 연결이 되거나 RST를 받으면 거기서 끝이고
ICMP는 **호출조차 하지 않는다**. TCP가 아무 응답도 주지 않았을 때만 마지막으로 Echo를
한 번 보낸다.

| 관측 | `reachable` | `port_open` | `failure_stage` |
|---|---|---|---|
| TCP 연결 성공 | `true` | `true` | — |
| RST 수신 | `true` | `false` | `port` |
| TCP 무응답 + Echo Reply | `true` | `false` | `port` |
| TCP 무응답 + Echo 없음 | `false` | `false` | `reachable` |

이 순서가 옛 결정("핑으로 판정하면 443으로 멀쩡히 답하는 BMC를 죽었다고 오판한다")을
그대로 지킨다. ICMP가 막혀 있어도 TCP가 답하면 통과이고, ICMP 무응답은 그 자체로 아무것도
실패시키지 않는다. ICMP 전용 실패 코드도 없다.

반대 방향의 오판을 막는 것이 이번 변경의 목적이다. 방화벽이 관리 포트 TCP를 조용히
버리는 구간에서는 서버가 살아 있어도 TCP만으로는 아무것도 관측되지 않아 "IP 사용 여부를
확인하세요"가 나갔다. 운영자가 봐야 할 곳은 방화벽인데 IP 대장을 뒤지게 된다. 이제 그
경우는 `stage: port` + "방화벽과 관리 서비스 상태를 확인하세요"가 된다.

확인은 controller의 `ping` 명령으로 한다 (Echo 1회, 기본 1초). raw socket은 root 권한이
필요하고 비특권 대안은 커널 설정에 좌우돼 에이전트마다 갈리기 때문이다. `ping`이 없거나
권한이 없는 환경이면 "근거 없음"으로 떨어져 판정이 종전 TCP 전용과 같아진다 — 그 사실은
`errors[].detail`에 남는다. 필요하면 `_precheck_icmp_probe: false`로 아예 끌 수 있다.

**`auth_success`는 사전 점검에서 채워지지 않는다.** 실제 운영 경로에서는 사전 점검
단계에 자격증명을 넘기지 않는다 (`precheck_bundle.py:1399-1410`). Redfish는 이 시점에
제조사가 아직 확정되지 않아 금고를 열 수 없고 억지로 인증을 시도하면 본 수집 전에
실패 횟수가 쌓여 계정이 잠길 위험이 커진다. 그래서 이 값은 본 수집 단계에서 채워진다.

`auth_success: false`는 장비가 **명시적으로** 거부했다는 뜻으로만 쓴다. 타임아웃, TLS
오류, 전송 오류, HTTP 5xx, HTTP 403은 `false`로 만들지 않는다. 확정할 수 없으면 `null`이다.

**수집 모듈이 결과 없이 멈춘 host 는 멈춘 위치로 분류한다.** (2026-10-03, 2026-10-05 개정) 2026-10-05(8차) 부터
작업(task) 단위 시간 제한과 Redfish 모듈 마감은 없다 — 정상적으로 오래 걸리는 수집은 끝까지 기다리고, 배치 전체는
수집 실행 한계(최대 6시간)가 멈춘다(아래). 모듈이 예외 · 연결 끊김 · 강제 종료로 결과를 돌려주지 못하면 그 host 는 rescue 로 가고
`failure_stage` 는 멈춘 단계다. Redfish 는 모듈이 시도마다 남긴 **인증 증거 파일**(첫 자격 응답의 HTTP status, 비밀값 없음)의
현재 시도분만 읽어 셋으로 가른다 — 다른 시도의 파일은 이력일 뿐 현재 시도를 분류하지 않는다.

| 현재 시도의 증거 | `failure_stage` / `failure_code` | `auth_success` | 문장 |
|---|---|---|---|
| 자격 응답 401 | 기존 규칙 그대로 — 표준 후보 전원 401 이면 `auth` / `AUTH_PROBE_FAILED` | `false` (전원 401) · `null` (일부) | "계정이 다르거나 권한이 없습니다" · "원인을 확정하지 못했습니다" |
| 자격 응답 2xx 뒤 정지 | `gather` / `GATHER_FAILED` | `true` | "대상 Redfish 인증은 성공했지만 정보를 가져오지 못했습니다" |
| 증거 없음 · 응답 전 정지 · 익명 응답 · 다른 빌드/시도의 파일 | `gather` / `GATHER_FAILED` | `null` | "개더링 프로젝트에서 정보 수집 중 오류가 발생했습니다" |

성공도 거부도 **추정하지 않는다**: 이미 있는 성공 증거를 뒤의 정지가 지우지 않고, 과거 시도의 401 로 지금
시도를 거부로 적지 않는다. 표준 계정 시도가 결과 없이 멈추면 복구 계정 경로에는 들어가지 않는다(401 이 아니다).
기술 근거(`status=task_stopped first_auth=… last_request=…`, 2026-10-05 전에는 `task_timeout`)는 `errors[].detail` 에 남는다.

**배치가 실행 한계로 끝나 결과를 못 낸 host** (2026-10-05 8차, 2026-10-06 9차 개정). 수집 배치를 멈추는 것은 수집 실행 한계(실제 수집 시간의
누적 최대 6시간 — 실행 기반을 기다린 시간은 넣지 않는다)와 사용자 취소뿐이다. 한계에 닿아 결과를 내지 못한 host 는 결과 정리 단계가 진행 기록으로
실패 봉투를 만든다(code 는 위 표의 기존 값). 끝난 host 의 결과는 그대로 보낸다. 그 봉투의 `diagnosis.details.limit_reason` 에 어떤 한계였는지
남는다 — `gather_limit`(수집 실행 한계 6시간) · `infra_wait`(실행 기반 대기 한도 72시간, 아래). 새 `failure_code` 는 없다. 2026-10-05 의
`build_limit`(빌드 12시간 안의 남은 시간)은 9차에 빌드 한계와 함께 없앴다. (2026-10-05 7차의 `stalled` · `ceiling` · `forced` 는 정체 감시 ·
시험용 강제 한계와 함께 없앴다.) CHECKPOINT(조립 직후 보존본)로 보낸 봉투는 `errors[].detail` 의 `limit_reason=` 에만 남고, 결과 정리(Layer A)가
실패해 보충 라이브러리가 조립한 경우에는 봉투에 남지 않는다 — 어느 경우든 실행 요약 `finalize_summary.json` 의 `limit_reason` 이 정본이다.

**실행 기반(Runner)이 돌아오지 않아 끝나지 않은 host** (2026-10-06 9차, 2026-10-07 10차 보완). Runner · Jenkins Agent 장애(연결 끊김 · 근거 있는 OOM — 커널 로그에 이 수집 실행의 프로세스가 OOM 으로 끝났다는 기록이 있을 때 · 재부팅)는 대상 측
장애가 아니다. 파이프라인은 끝난 결과를 보존한 채 같은 Runner · 같은 작업 폴더가 돌아오기를 빌드 하나의 합으로 최대 72시간 기다렸다가 끝나지 않은
host 만 이어서 수집한다(끝난 host · 사전 점검에서 실패로 확정된 host 는 다시 수집하지 않는다). 대기 한도를 넘었거나(outcome `infra_wait_expired`)
같은 작업 폴더로 이어 갈 수 없으면(`resume_impossible` — Runner 등록 해제 · 작업 폴더 사라짐 · 결과가 확정됐던 host 의 결과가 작업 폴더에서 사라짐) 끝나지 않은 host 는 대상 측 실패로 확정하지 않고
아래 문장의 실패 봉투로 보낸다.

| 경우 | `failure_stage` / `failure_code` | `auth_success` | 사용자 문장 (`failure_reason` = `errors[0].message`) |
|---|---|---|---|
| 실행 기반 대기 한도 초과 · 같은 Runner 로 이어 갈 수 없음 | `fallback` / `OUTPUT_BUILD_FAILED` (기존 값) | `null` | "수집을 실행하던 Runner 가 회복되지 않아 이 대상의 수집을 마치지 못했습니다." |

사전 점검(Precheck) 진단이 이미 있는 host 는 그 진단을 그대로 보낸다. 문장 정본은 `common/vars/failure_reasons.yml` 의 `_fr_catalog.infra_unavailable`
(Groovy 보충 라이브러리의 `infraReason` 이 같은 문장이고 drift 테스트가 막는다). 실행 단위 기록은 `finalize_summary.json` 의 `infra`
(예산 · 사용 · 만료 · 대기 구간마다 사유 · 대상 · 시작 · 끝 · 초 · 결과)와 `callback.receipt`(`delivered` · `not_delivered` · `uncertain` · `not_attempted`)다.
Portal 은 72시간 대기 빌드의 결과를 최대 약 79시간 뒤(대기 72 + 수집 6 + 결과 확인 1)에 받을 수 있다.

## 실제로 이렇게 나온다

2026-08-13 실장비 측정에서 나온 두 경우다.

**포트는 열렸는데 프로토콜이 아닌 경우** — Cisco BMC `10.100.15.1`. TCP 443은 열려
있었지만 Redfish ServiceRoot를 제대로 주지 않았다.

```jsonc
"status": "failed",
"diagnosis": { "reachable": true, "port_open": true, "protocol_supported": false,
               "failure_stage": "protocol", "failure_code": "PROTOCOL_CHECK_FAILED" }
```

이 경우 "장비가 없다"고 결론 내리면 틀린다. 장비는 있고 443도 답한다. Redfish 서비스가
꺼져 있거나 다른 것이 그 포트를 쓰고 있는 상태다.

**자격증명이 거부된 경우** — Dell BMC `10.100.15.27`. 표준 계정 비밀번호가 이 장비까지
반영되지 않아 401을 받았다.

```jsonc
"status": "failed",
"sections": { "system": "failed", "hardware": "failed", ... },
"diagnosis": { "failure_stage": "auth", "failure_code": "AUTH_PROBE_FAILED" }
```

섹션이 전부 `failed`로 나오는 게 정상이다. 접속을 못 했으니 지원 여부를 판단할 근거도
없기 때문이다.

## partial 은 실패가 아니다

일부 섹션만 실패하면 `partial`이고 성공한 섹션의 데이터는 그대로 들어 있다.
이걸 실패로 처리하면 쓸 수 있는 정보를 버리게 된다.

```jsonc
"status": "partial",
"sections": { "cpu": "success", "memory": "success", "storage": "failed", ... },
"data":     { "cpu": { ... }, "memory": { ... }, "storage": null }
```

`not_supported`도 실패가 아니다. 그 경로로는 원래 못 얻는 정보라는 뜻이다. 예를 들어
Redfish로 조회하면 `users`는 항상 `not_supported`다 — BMC는 OS 계정을 모른다.

Windows `users` 는 계정 목록 명령 자체가 없을 때만 `not_supported` 다. 명령은 있는데 조회가 실패해 한 명도
못 읽으면 `failed`(오류 1건)이고, 일부만 읽었거나 그룹 조회가 실패하면 섹션은 `success` 그대로 `errors[]` 에
1건이 붙는다. Windows `system` · `storage` 도 구성요소 일부(컴퓨터 정보 · 물리 디스크 조회)가 실패하면 섹션 상태는
그대로 두고 `errors[]` 에 1건을 남긴다(2026-10-05 — 종전에는 기록 없이 빈 값이나 `unknown` 이 나갔다).

2026-10-05 (8차 R5) 에 같은 방식으로 더 드러낸 것 — 모두 섹션 상태는 그대로 두고 받은 값은 보존하며 `errors[]` 에 1건:

| 채널 · 섹션 | 종전 | 지금 `errors[].message` (기술 근거는 `detail`) |
|---|---|---|
| Windows `memory` | setup(사실 수집) 실패 시 `visible_mb` · `free_mb` 가 이유 없이 비었다 | "메모리 정보 중 OS 가 인식한 용량을 읽지 못했습니다. 대상 상태와 수집 로그를 확인하세요." (`cause=facts_failed` 또는 `no_value`) |
| Windows `system` 식별자 | setup 실패도 "권한" 문제로 적었다 | "시스템 제조번호를 읽지 못했습니다. …" / "시스템 고유 식별자를 읽지 못했습니다. …" (`cause=facts_failed`) |
| Windows `system` 실행 형태 | Hyper-V 서비스(vmms) **조회 실패**도 "역할 없음" 으로 보고 `virtual` 로 적을 수 있었다 | 조회 실패면 `hosting_type=unknown` + 구성요소 실패 1건. 서비스 없음(조회 성공) · 멈춤(설치됨)은 실패가 아니다 |
| Windows `network` | 어댑터 · 경로 · DNS · 주소 조회의 끝나지 않는 오류(SilentlyContinue)를 버렸다 | "네트워크 정보 중 일부를 읽지 못했습니다. 대상 상태와 수집 로그를 확인하세요." (`parts=…`). "찾는 항목 없음"(예: IPv6 기본 경로가 없음)은 실패가 아니다 |
| Windows `storage` | `Get-Volume` 실패를 볼륨 0개와 구분하지 못했다 | "스토리지 정보 중 파일시스템(볼륨) 정보를 읽지 못했습니다. 대상 상태와 수집 로그를 확인하세요." |
| ESXi `storage` 디스크 | 디스크 모듈이 형태가 틀린 결과로 끝나면 빈 목록이 "성공" 이었다 | 기존 디스크 구성요소 오류 문장에 `cause=module_failed` |

## detail 은 어디서 오나

`errors[].detail`에는 기술 근거가 들어간다. 사전 점검이 남긴 실패 사유와 수집 중 잡힌
예외 메시지가 ` | `로 이어 붙는다. 없으면 `null`이다.

길이는 2000자에서 잘린다. 로그 전체가 들어오지는 않으니 원인 추적은 Jenkins 콘솔
로그를 함께 봐야 한다.

## 다음

- 봉투 전체 모양: [02-output-envelope.md](02-output-envelope.md)
- 어디부터 볼지: [develop/06-debugging.md](../develop/06-debugging.md)
