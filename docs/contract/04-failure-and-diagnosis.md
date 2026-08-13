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
| `reachable` | — | TCP 연결 자체가 안 된다 |
| `port` | 장비는 살아 있다 (RST를 받았다) | 그 포트가 닫혀 있다 |
| `protocol` | 포트는 열려 있다 | 기대한 프로토콜로 응답하지 않는다 |
| `auth` | 프로토콜은 맞다 | 자격증명이 거부됐거나 금고를 못 열었다 |
| `gather` | 접속과 인증은 됐다 | 정보를 캐는 중에 실패했다 |
| `fallback` | — | 봉투 조립 자체가 실패해 최후 수단으로 만들었다 |

성공하면 셋 다 `null`이다. 반대로 실패인데 `failure_reason`이 `null`인 봉투는 나오지
않는다 — 조립기가 그 경우를 막는다.

## failure_code — 기계가 분기할 값

여덟 개로 고정이다. `message`는 사람이 읽는 문장이라 다듬어질 수 있지만 이 코드는
호출자가 조건문에 써도 되는 안정된 값이다.

| 코드 | 언제 |
|---|---|
| `DNS_RESOLUTION_FAILED` | 주소 해석 실패 |
| `TCP_CONNECT_FAILED` | 연결 시도가 응답 없이 끝났다 |
| `TCP_CONNECTION_REFUSED` | RST를 받았다 — 장비는 있고 포트가 닫혔다 |
| `PROTOCOL_CHECK_FAILED` | 포트는 열렸는데 기대한 응답이 아니다 |
| `AUTH_PROBE_FAILED` | 자격증명이 거부됐다 |
| `CREDENTIAL_SET_UNAVAILABLE` | 금고 파일이 없거나 못 열었다 |
| `GATHER_FAILED` | 수집 중 실패 |
| `OUTPUT_BUILD_FAILED` | 봉투 조립 실패 |

`DNS_RESOLUTION_FAILED`가 목록에 있지만 이 시스템은 IPv4만 받는다. 사용자 안내에서
DNS나 호스트명 확인을 권하지 않는다.

## 사용자에게 보이는 문장

다섯 개로 정해져 있다. 포트 번호, 타임아웃 값, HTTP 상태 코드, 예외 문자열 같은 건
들어가지 않는다. 그런 건 `errors[].detail`에 간다.

| 상황 | 문장 |
|---|---|
| 응답 없음 | 대상 IP에서 응답을 확인할 수 없습니다. IP 사용 여부와 네트워크 상태를 확인하세요. |
| 포트 닫힘 | 대상 IP의 관리 포트에 연결할 수 없습니다. 방화벽과 관리 서비스 상태를 확인하세요. |
| 프로토콜 불일치 | 관리 포트에는 연결됐지만 서버 정보 수집에 필요한 응답을 확인할 수 없습니다. 관리 서비스 설정과 상태를 확인하세요. |
| 인증 실패 | 대상에 접속할 수 없습니다. 자격증명과 계정 권한을 확인하세요. |
| 수집 실패 | 대상 접속은 확인됐지만 정보 수집에 실패했습니다. 대상 상태와 수집 로그를 확인하세요. |

## 진단이 실제로 무엇을 했나

`diagnosis`의 앞 네 필드는 사전 점검 결과다. 여기서 오해하기 쉬운 지점 둘을 짚는다.

**`reachable`은 핑이 아니다.** ICMP는 아예 구현되어 있지 않다
(`common/library/precheck_bundle.py:138,181`). 관리망은 핑을 막아 두는 일이 흔한데,
핑으로 판정하면 443으로 멀쩡히 답하는 BMC를 죽었다고 오판한다. 그래서 TCP 연결로만
본다. `reachable: true`는 "연결이 됐거나 RST를 받았다"는 뜻이다.

RST를 받았다는 건 장비가 살아서 거절했다는 신호다. 그래서 이 경우는 `reachable: true`,
`port_open: false`, `failure_stage: port`가 된다. 아무 응답이 없으면 `reachable: false`,
`failure_stage: reachable`이다.

**`auth_success`는 사전 점검에서 채워지지 않는다.** 실제 운영 경로에서는 사전 점검
단계에 자격증명을 넘기지 않는다 (`precheck_bundle.py:1399-1410`). Redfish는 이 시점에
제조사가 아직 확정되지 않아 금고를 열 수 없고 억지로 인증을 시도하면 본 수집 전에
실패 횟수가 쌓여 계정이 잠길 위험이 커진다. 그래서 이 값은 본 수집 단계에서 채워진다.

`auth_success: false`는 장비가 **명시적으로** 거부했다는 뜻으로만 쓴다. 타임아웃, TLS
오류, 전송 오류, HTTP 5xx, HTTP 403은 `false`로 만들지 않는다. 확정할 수 없으면 `null`이다.

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

## detail 은 어디서 오나

`errors[].detail`에는 기술 근거가 들어간다. 사전 점검이 남긴 실패 사유와 수집 중 잡힌
예외 메시지가 ` | `로 이어 붙는다. 없으면 `null`이다.

길이는 2000자에서 잘린다. 로그 전체가 들어오지는 않으니 원인 추적은 Jenkins 콘솔
로그를 함께 봐야 한다.

## 다음

- 봉투 전체 모양: [02-output-envelope.md](02-output-envelope.md)
- 어디부터 볼지: [develop/06-debugging.md](../develop/06-debugging.md)
