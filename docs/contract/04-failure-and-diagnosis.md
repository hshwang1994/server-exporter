# 실패했을 때 무엇을 보나

실패해도 봉투는 옵니다. 모양도 성공했을 때와 같습니다. 그래서 호출자는 "응답이 없다"를 따로 처리할 필요가 없고, 봉투 안의 몇 개 필드로 무슨 일이 있었는지 읽으면 됩니다. 이 문서는 그 읽는 법을 다룹니다.

## 어디를 먼저 보나

세 곳이면 충분합니다.

1. `status`: 전부 실패인가, 일부만인가
2. `diagnosis.failure_stage`: 어느 단계에서 멈췄나
3. `errors[].message`: 사용자에게 보여 줄 문장

`diagnosis.failure_reason`과 `errors[0].message`는 같은 문장을 씁니다. 화면에 그대로 띄우면 됩니다.

## failure_stage: 멈춘 위치

여섯 값입니다. "근본 원인"이 아니라 작업 흐름이 어디까지 갔는가를 나타냅니다.

| 값 | 여기까지는 됐다 | 여기서 막혔다 |
|---|---|---|
| `reachable` | 없음 | 관리 TCP도 ICMP도 응답이 없다 |
| `port` | 대상이 응답한다 (RST 또는 ICMP Echo Reply) | 관리 포트에 붙지 못한다 |
| `protocol` | 포트는 열려 있다 | 기대한 프로토콜로 응답하지 않는다 |
| `auth` | 프로토콜은 맞다 | 자격증명이 거부됐거나 vault를 못 열었다 |
| `gather` | 접속과 인증은 됐다 | 정보를 읽는 중에 실패했다 |
| `fallback` | 없음 | 봉투 조립 자체가 실패해 최후 수단으로 만들었다 |

성공하면 `failure_stage`, `failure_code`, `failure_reason` 셋 다 `null`입니다. 반대로 실패인데 `failure_reason`이 `null`인 봉투는 나오지 않습니다.

## failure_code: 기계가 분기할 값

아홉 개로 고정입니다. `message`는 사람이 읽는 문장이라 다듬어질 수 있지만 이 코드는 호출자가 조건문에 써도 되는 안정된 값입니다.

| 코드 | 언제 |
|---|---|
| `DNS_RESOLUTION_FAILED` | 주소 해석 실패 (IPv4만 받으므로 실제로는 나오지 않습니다) |
| `TARGET_UNREACHABLE` | 관리 TCP도 ICMP도 응답이 없다 |
| `TCP_CONNECT_FAILED` | ICMP는 답하는데 관리 TCP 포트가 응답 없이 끝났다 |
| `TCP_CONNECTION_REFUSED` | RST를 받았다. 장비는 있고 포트가 닫혔다 |
| `PROTOCOL_CHECK_FAILED` | 포트는 열렸는데 기대한 응답이 아니다 |
| `AUTH_PROBE_FAILED` | 자격증명이 거부됐다 |
| `CREDENTIAL_SET_UNAVAILABLE` | vault 파일이 없거나 못 열었다 |
| `GATHER_FAILED` | 수집 중 실패 |
| `OUTPUT_BUILD_FAILED` | 봉투 조립 실패, 또는 실행 기반이 돌아오지 않아 수집을 마치지 못함 |

`TARGET_UNREACHABLE`은 2026-09-03에 추가됐습니다. 그 전에는 `TCP_CONNECT_FAILED` 하나가 "아무 응답 없음"과 "관리 포트만 응답 없음"을 겸했습니다. `TCP_CONNECT_FAILED`와 `stage: reachable`로 분기하던 호출자는 `TARGET_UNREACHABLE`을 받도록 고쳐야 합니다.

## 사용자에게 보이는 문장

문장은 정해진 카탈로그(`common/vars/failure_reasons.yml`)에서 고릅니다. 고르는 기준은 `failure_code`, 대상 종류(OS, ESXi, Redfish), 세부 사유입니다. 전체 표는 [03-fields.md](03-fields.md) 4-1절에 있습니다. 포트 번호, 타임아웃 값, HTTP 상태 코드, 예외 문자열은 들어가지 않고 `errors[].detail`에 갑니다.

| 상황 | 문장 |
|---|---|
| 응답 없음 | 대상 서버가 응답하지 않습니다. 서버 전원 상태와 네트워크 연결을 확인하세요. |
| ICMP는 되는데 관리 포트 무응답 | 대상 서버와 통신은 되지만 관리 포트에 연결할 수 없습니다. 방화벽과 접속 설정을 확인하세요. |
| 관리 포트 거부 (Redfish) | Redfish 접속이 거부되었습니다. 대상 장비의 Redfish 접속 설정과 방화벽을 확인하세요. |
| 응답이 기대와 다름 (ESXi) | 접속한 대상에서 ESXi 응답을 확인하지 못했습니다. 대상 종류와 ESXi 서비스 상태를 확인하세요. |
| 위치 vault 복호화 실패 | 해당 위치(ic)의 Vault를 읽을 수 없습니다. |
| 인증 실패, 원인 미확정 (OS) | 해당 위치(ic)의 Vault 계정으로 대상 OS에 로그인하지 못했습니다. |
| 인증 거부 확인 (Redfish) | 대상 Redfish 계정과 개더링 표준 계정이 다르거나 권한이 없습니다. |
| 인증 후 수집 실패 (ESXi) | 대상 ESXi에는 로그인했지만 정보를 가져오지 못했습니다. |

문장의 원칙입니다.

- 관측한 것만 말합니다. "통신은 되지만"은 ICMP 응답을 실제로 봤을 때만, "로그인했지만"은 인증 통과를 실제로 봤을 때만 씁니다.
- 거부의 주체를 단정하지 않습니다. 연결 거부는 중간 방화벽이 보낼 수도 있어서 "서버가 거부했다"고 쓰지 않습니다.
- "계정이 다르거나 권한이 없다"는 확인된 경우에만 씁니다. 지금 확인할 수 있는 것은 Redfish 표준 계정 전원의 401뿐입니다. OS와 ESXi는 거부 사실이 오류 문자열로만 와서 확정하지 않습니다.
- Redfish 표준 계정은 위치와 무관한 전역 vault입니다. 그래서 Redfish 문장은 "해당 위치의 Vault"가 아니라 "개더링 표준 계정"이라고 씁니다.

## 진단이 실제로 무엇을 했나

`diagnosis`의 앞 네 필드는 사전 진단 결과입니다. 오해하기 쉬운 지점을 짚습니다.

`reachable`은 TCP와 ICMP의 OR이고 핑 관문이 아닙니다. 먼저 관리 TCP 포트를 봅니다. 연결이 되거나 RST를 받으면 거기서 끝이고 ICMP는 호출하지 않습니다. TCP가 아무 응답도 주지 않았을 때만 Echo를 한 번 보냅니다.

| 관측 | `reachable` | `port_open` | `failure_stage` |
|---|---|---|---|
| TCP 연결 성공 | `true` | `true` | 없음 |
| RST 수신 | `true` | `false` | `port` |
| TCP 무응답 + Echo Reply | `true` | `false` | `port` |
| TCP 무응답 + Echo 없음 | `false` | `false` | `reachable` |

ICMP가 막혀 있어도 TCP가 답하면 통과이고, ICMP 무응답은 그 자체로 아무것도 실패시키지 않습니다. ICMP 전용 실패 코드도 없습니다. 방화벽이 관리 포트 TCP를 조용히 버리는 구간에서는 Echo 응답이 "장비는 있다"를 증명해 `stage: port`와 "방화벽과 접속 설정을 확인하세요"가 나갑니다.

확인은 Runner의 `ping` 명령으로 합니다 (Echo 1회, 기본 1초). `ping`이 없거나 권한이 없는 환경이면 근거 없음으로 떨어져 판정이 TCP 전용과 같아지고, 그 사실은 `errors[].detail`에 남습니다.

`auth_success`는 사전 진단에서 채워지지 않습니다. 사전 진단에는 자격증명을 넘기지 않기 때문입니다. Redfish는 이 시점에 제조사가 아직 확정되지 않았고, 억지로 인증을 시도하면 본 수집 전에 실패 횟수가 쌓여 계정이 잠길 위험이 있습니다. 이 값은 본 수집 단계에서 채워집니다. `false`는 장비가 명시적으로 거부했다는 뜻으로만 쓰고, 타임아웃, TLS 오류, 전송 오류, HTTP 5xx, HTTP 403은 `false`로 만들지 않습니다. 확정할 수 없으면 `null`입니다.

Redfish에서 첫 인증이 2xx로 통과한 뒤 일부 리소스가 403을 돌려주면 그 섹션만 `failed`가 되고 서버 전체는 `partial`입니다. 첫 인증 자체가 403이면 서버 전체가 실패입니다.

### 수집 모듈이 결과 없이 멈춘 서버

작업 단위 시간 제한은 없습니다. 정상적으로 오래 걸리는 수집은 끝까지 기다리고, 배치 전체는 수집 실행 한계(누적 6시간)가 멈춥니다. 모듈이 예외, 연결 끊김, 강제 종료로 결과를 돌려주지 못하면 그 서버는 `failure_stage`가 멈춘 단계로 분류됩니다. Redfish는 모듈이 시도마다 남긴 인증 증거 파일(첫 자격 응답의 HTTP 상태, 비밀값 없음)의 현재 시도분만 읽어 셋으로 가릅니다.

| 현재 시도의 증거 | `failure_stage` / `failure_code` | `auth_success` | 문장 |
|---|---|---|---|
| 자격 응답 401 | 표준 계정 전원 401이면 `auth` / `AUTH_PROBE_FAILED` | `false` (전원 401), `null` (일부) | "계정이 다르거나 권한이 없습니다", "원인을 확정하지 못했습니다" |
| 자격 응답 2xx 뒤 정지 | `gather` / `GATHER_FAILED` | `true` | "대상 Redfish 인증은 성공했지만 정보를 가져오지 못했습니다" |
| 증거 없음, 응답 전 정지, 다른 시도의 파일 | `gather` / `GATHER_FAILED` | `null` | "개더링 프로젝트에서 정보 수집 중 오류가 발생했습니다" |

성공도 거부도 추정하지 않습니다. 이미 있는 성공 증거를 뒤의 정지가 지우지 않고, 과거 시도의 401로 지금 시도를 거부로 적지 않습니다. 기술 근거(`status=task_stopped first_auth=… last_request=…`)는 `errors[].detail`에 남습니다.

### 배치가 실행 한계로 끝나 결과를 못 낸 서버

수집 배치를 멈추는 것은 수집 실행 한계(실제 수집 시간의 누적 최대 6시간. Runner를 기다린 시간은 넣지 않습니다)와 빌드 중단뿐입니다. 한계에 닿아 결과를 내지 못한 서버는 결과 정리 단계가 진행 기록으로 실패 봉투를 만들고, 끝난 서버의 결과는 그대로 보냅니다. 그 봉투의 `diagnosis.details.limit_reason`에 어떤 한계였는지 남습니다. `gather_limit`은 수집 실행 한계, `infra_wait`는 실행 기반 대기 한도(72시간)입니다. 새 `failure_code`는 없습니다. 어느 경우든 실행 요약 `finalize_summary.json`의 `limit_reason`이 정본입니다.

### Runner가 돌아오지 않아 끝나지 않은 서버

Runner나 Jenkins Agent의 장애(연결 끊김, 근거 있는 OOM, 재부팅)는 대상 측 장애가 아닙니다. 파이프라인은 끝난 결과를 보존한 채 같은 Runner와 같은 작업 폴더가 돌아오기를 빌드 하나의 합으로 최대 72시간 기다렸다가 끝나지 않은 서버만 이어서 수집합니다. 끝난 서버와 사전 진단에서 실패로 확정된 서버는 다시 수집하지 않습니다. 대기 한도를 넘었거나 같은 작업 폴더로 이어 갈 수 없으면 끝나지 않은 서버는 대상 측 실패로 확정하지 않고 아래 문장의 실패 봉투로 보냅니다.

| 경우 | `failure_stage` / `failure_code` | `auth_success` | 문장 |
|---|---|---|---|
| 실행 기반 대기 한도 초과, 같은 Runner로 이어 갈 수 없음 | `fallback` / `OUTPUT_BUILD_FAILED` | `null` | "수집을 실행하던 Runner가 회복되지 않아 이 대상의 수집을 마치지 못했습니다." |

사전 진단 결과가 이미 있는 서버는 그 진단을 그대로 보냅니다. Portal은 72시간 대기 빌드의 결과를 최대 약 79시간 뒤(대기 72 + 수집 6 + 결과 확인 1)에 받을 수 있습니다. 실행 단위 기록은 `finalize_summary.json`의 `infra`와 `callback.receipt`(`delivered`, `not_delivered`, `uncertain`, `not_attempted`)입니다.

### 빌드가 중단된 경우

사용자가 빌드를 중단하면 그때까지 끝난 서버의 결과는 보존해 보내고, 끝나지 않은 서버는 진행 기록으로 실패 봉투를 만듭니다. 파이프라인은 중단 원인을 추정하지 않습니다. 콘솔에는 "빌드가 중단됐습니다(사용자 취소 또는 그 밖의 중단)"로만 남습니다.

## 실제로 이렇게 나옵니다

사내 실장비에서 나온 두 경우입니다.

포트는 열렸는데 프로토콜이 아닌 경우입니다. Cisco BMC 한 대는 TCP 443이 열려 있었지만 Redfish 서비스 루트를 주지 않았습니다 (CIMC에서 Redfish 서비스가 꺼져 있었습니다).

```jsonc
"status": "failed",
"diagnosis": { "reachable": true, "port_open": true, "protocol_supported": false,
               "failure_stage": "protocol", "failure_code": "PROTOCOL_CHECK_FAILED" }
```

이 경우 "장비가 없다"고 결론 내리면 틀립니다. 장비는 있고 443도 답합니다. Redfish 서비스가 꺼져 있거나 다른 것이 그 포트를 쓰고 있는 상태입니다. ESXi 대상이 실제로는 vCenter인 경우도 같은 `protocol` 단계입니다. vSphere 서비스의 `apiType`이 `VirtualCenter`면 자격증명을 보내지 않고 멈추며 `errors[].detail`에 `apiType=VirtualCenter`가 남습니다.

자격증명이 거부된 경우입니다. 표준 계정 비밀번호가 장비에 반영되지 않아 401을 받았습니다.

```jsonc
"status": "failed",
"sections": { "system": "failed", "hardware": "failed", ... },
"diagnosis": { "failure_stage": "auth", "failure_code": "AUTH_PROBE_FAILED" }
```

섹션이 전부 `failed`로 나오는 것이 정상입니다. 접속을 못 했으니 지원 여부를 판단할 근거도 없기 때문입니다.

## partial은 실패가 아닙니다

일부 섹션만 실패하면 `partial`이고 성공한 섹션의 데이터는 그대로 들어 있습니다. 이것을 실패로 처리하면 쓸 수 있는 정보를 버리게 됩니다.

```jsonc
"status": "partial",
"sections": { "cpu": "success", "memory": "success", "storage": "failed", ... },
"data":     { "cpu": { ... }, "memory": { ... }, "storage": null }
```

`not_supported`도 실패가 아닙니다. 그 경로로는 원래 못 얻는 정보라는 뜻입니다. 예를 들어 Redfish로 조회하면 `users`는 항상 `not_supported`입니다. BMC는 OS 계정을 모릅니다.

섹션 상태는 그대로 두고 `errors[]`에만 1건을 남기는 경우도 있습니다. 구성요소 일부(예: Windows의 볼륨 조회, Linux의 사용자 목록 일부, 메모리의 OS 인식 용량)를 못 읽었을 때입니다. Linux `users`는 `getent` 명령이 없을 때만 `not_supported`이고, 명령은 있는데 실패하면 `failed`와 `errors[]` 1건입니다. Linux에서 sudo가 안 되면 시리얼과 UUID는 `null`, 메모리는 OS 인식 용량으로 채우고 각각 `errors[]`에 이유를 남깁니다.

## detail은 어디서 오나

`errors[].detail`에는 기술 근거가 들어갑니다. 사전 진단이 남긴 실패 사유와 수집 중 잡힌 예외 메시지가 ` | `로 이어 붙습니다. 없으면 `null`입니다. 길이는 2000자에서 잘립니다. 원인 추적은 Jenkins 콘솔 로그를 함께 봐야 합니다 ([../develop/06-debugging.md](../develop/06-debugging.md)).

## 다음

- 봉투 전체 모양: [02-output-envelope.md](02-output-envelope.md)
- 어디부터 볼지: [../develop/06-debugging.md](../develop/06-debugging.md)
