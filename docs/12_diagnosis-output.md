# 12. `diagnosis` / `meta` / `correlation` — 응답에 같이 따라오는 메타 3개

## 한 줄 요약

JSON 응답에는 알맹이(`data`) 외에도 "**언제 / 어디서 / 어떻게 만들어졌는가**" 를 알려주는 3개 필드가 같이 온다.

| 필드 | 답하는 질문 | 주된 용도 |
|---|---|---|
| `diagnosis` | "어디서 막혔지?" | 장애 분석, 운영 알람 |
| `meta` | "언제, 얼마나, 어떤 어댑터로?" | 회귀 비교, 성능 추적 |
| `correlation` | "이 응답을 다른 데이터와 어떻게 묶지?" | 다중 채널 결과 매칭, trace ID |

이 셋은 envelope 의 다른 필드(`status`, `sections`, `data`, `errors`) 와 **별개 축**이다. 호출자가 안 써도 무방하지만, 운영 / 분석 단계에서 큰 차이를 만든다.

---

## 1. `diagnosis` — 어디서 막혔지

precheck 4단계 (`docs/11`) 의 결과가 그대로 들어온다.

### 정상

```json
"diagnosis": {
  "reachable":          true,
  "port_open":          true,
  "protocol_supported": true,
  "auth_success":       true,
  "failure_stage":      null,
  "failure_reason":     null,
  "details": {
    "channel": "redfish", "adapter_candidate": "redfish_dell_idrac9",
    "checked_ports": [443], "selected_port": 443,
    "redfish_version": "1.6.0", "product": "Integrated Dell Remote Access Controller",
    "systems_uri": "/redfish/v1/Systems"
  }
}
```

### 실패 (예: protocol 단계)

```json
"diagnosis": {
  "reachable":          true,
  "port_open":          true,
  "protocol_supported": false,           ← 여기서 false
  "auth_success":       false,
  "failure_stage":      "protocol",
  "failure_reason":     "Redfish ServiceRoot (/redfish/v1/) 응답 없음 — iDRAC 7 등 구 세대 추정",
  "details": {
    "channel": "redfish", "checked_ports": [443], "selected_port": 443
  }
}
```

### `failure_stage` 5가지 값

| 값 | 무슨 뜻 | 어디 점검? |
|---|---|---|
| `null` | 정상. 모든 단계 통과 | — |
| `reachable` | 호스트 자체가 응답 없음 | 호스트 전원 / 네트워크 / 라우팅 |
| `port` | 호스트는 응답하나 서비스 포트 닫힘 | 방화벽 / 서비스 기동 / 포트 번호 |
| `protocol` | 포트는 열렸는데 응답 형식 이상 | TLS / cipher / 펌웨어 / Redfish 미지원 BMC |
| `auth` | 자격증명 거부 | 비밀번호 회전 / 계정 잠김 / 권한 부족 |

> `reachable` 과 `port` 는 TCP connect 한 번으로 판정한다 (ping ICMP 차단 환경이 흔해서). 응답 자체가 없으면 `reachable`, 응답은 있으나 대상 포트가 닫혀 있으면 `port`.

---

## 2. `meta` — 언제, 얼마나, 어떤 어댑터로

```json
"meta": {
  "started_at":      "2026-03-18T10:00:00Z",   // 수집 시작 (UTC ISO8601)
  "finished_at":     "2026-03-18T10:00:18Z",   // 수집 종료
  "duration_ms":     18420,                     // 소요 시간 (호스트 1대 기준)
  "adapter_id":      "redfish_dell_idrac9",     // 매칭된 adapter
  "adapter_version": "1.0.0",
  "ansible_version": "2.20.3"
}
```

### 활용

- **`duration_ms`** — 정상 시간 대비 이상 추적 (예: Redfish Dell 평균 5초 → 어느 호스트가 15초로 튀면 경고)
- **`adapter_id`** — 회귀 시 어떤 adapter 결과인지 명시. 새 펌웨어가 나와 generation adapter 가 바뀌면 여기서 추적
- **`adapter_version`** — adapter YAML 자체의 버전. 변경 추적용

---

## 3. `correlation` — 다른 데이터와 어떻게 묶지

같은 물리 서버를 OS / ESXi / Redfish 채널 각각으로 수집한 결과를 매칭할 때 쓰는 키들.

```json
"correlation": {
  "serial_number": "ABC1234XYZ",                                // 섀시 시리얼
  "system_uuid":   "550e8400-e29b-41d4-a716-446655440000",      // SMBIOS UUID
  "bmc_ip":        "10.0.0.10",                                  // BMC 자체 IP
  "host_ip":       "10.0.1.10"                                   // 서버 OS 가 올라간 IP
}
```

### 매칭 전략

| 키 | 어디서 채워지나 | 매칭 우선순위 |
|---|---|---|
| `serial_number` | 모든 채널 (Redfish 가 제일 정확) | 1순위 (벤더에서 부여한 고유값) |
| `system_uuid` | Redfish / ESXi 가 채움 | 2순위 (재시스템 시 동일 보장) |
| `bmc_ip` | Redfish 만 | 3순위 (네트워크 변경 시 바뀜) |
| `host_ip` | 모든 채널 | 4순위 (가장 변동성 큼) |

호출자가 두 응답을 받았을 때 같은 서버인지 판단하려면 위에서부터 차례로 비교한다.

---

## 4. 하위 호환

- 세 필드 모두 `| default(none)` 처리되어 있어 옛날 호출자 코드와 호환된다.
- 기존 envelope 필드 (`target_type`, `status`, `sections`, `errors`, `data`) 의 의미는 변경되지 않는다.
- `schema_version` 은 여전히 `"1"` 이다.

새 호출자가 `diagnosis` / `meta` / `correlation` 을 활용하더라도, 옛 호출자가 무시해도 동작에 차이 없다.

---

## 5. 관련 코드

| 파일 | 역할 |
|---|---|
| `common/tasks/normalize/build_meta.yml` | meta dict 생성 |
| `common/tasks/normalize/build_correlation.yml` | correlation dict 생성 |
| `common/tasks/normalize/build_output.yml` | 위 셋을 envelope 에 삽입 |
| `common/tasks/normalize/build_failed_output.yml` | 실패 시에도 같은 3개 필드 포함하여 반환 |
| `common/tasks/normalize/init_fragments.yml` | `_started_at` 타임스탬프 초기화 |
| `filter_plugins/diagnosis_mapper.py` | precheck 결과를 diagnosis 형태로 변환 |

---

## 6. 자주 헷갈리는 점

**Q. `meta.duration_ms` 나 `correlation` 안 써도 되는가?**
필수 아니다. trace 분석 / 회귀 / 사용자 알림에 활용하는 영역.

**Q. `correlation.host_ip` 가 envelope `ip` 와 다를 수 있나?**
- OS 채널: 같다 (서비스 IP 로 직접 수집).
- ESXi 채널: 같다 (vCenter 가 아니라 호스트 직접 수집 시).
- Redfish 채널: BMC IP 가 envelope `ip` 이고, 서버 OS 가 올라간 host IP 는 별도. BMC 가 보고할 수 있으면 채워진다.

**Q. `diagnosis.details` 에 vendor / firmware 가 안 보이는데 정상인가?**
실패 단계에서 멈췄을 때 비는 게 정상. 단계 3 (protocol) 까지 통과해야 probe 가 vendor / firmware 를 `details` 에 병합한다 (별도 `probe_facts` 키는 출력에 없음 — `details` 안으로 합쳐진다).

**Q. `failure_stage` 가 `null` 인데 status 가 `partial` 이다. 모순 아닌가?**
모순 아니다. precheck 는 통과했는데 본 수집의 일부 endpoint 가 실패한 케이스. 어느 섹션이 실패인지는 `errors[]` + `sections.<섹션>: failed` 로 확인한다.

---

## 7. 더 보고 싶을 때

| 보고 싶은 것 | 파일 |
|---|---|
| precheck 4단계 상세 | `docs/11_precheck-module.md` |
| envelope 전체 13 필드 사전 | `docs/20_json-schema-fields.md` |
| 실패 시 호출자 처리 | `docs/08_failure-handling.md` |
| 출력 빌더 처리 과정 | `docs/07_normalize-flow.md` |
