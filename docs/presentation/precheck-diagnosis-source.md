# Precheck 진단 메시지 · 결과 JSON 전수 분석 (원천 데이터)

> **작성 기준**: 저장소 HEAD `1e8947b9` (2026-08-10). 모든 라인 번호는 이 시점 실제 파일 기준.
> **작성 방법**: 관련 파일을 전부 직접 읽고 호출 흐름을 추적했다. 문서·주석은 근거로 쓰지 않았고,
> 주석과 코드가 다른 곳은 §18 에 분리 기록했다.
> **용도**: 다른 AI 가 현재 진단 체계·메시지 설계를 검토하기 위한 원천 데이터.
> **범위 제한**: 본 문서는 조사만 한다. 코드 수정·개선안·새 스키마 제안을 포함하지 않는다.

> ## [WARN] 이 문서는 **HEAD `1e8947b9` 시점의 스냅샷**이다 (2026-08-10 기준 stale)
>
> 이후 진단 체계 개선 작업으로 아래가 바뀌었다. **현재 동작의 정본은 코드**이며,
> 본 문서의 해당 절은 "개선 전 상태" 기록으로만 읽는다.
>
> | 변경 | 본 문서에서 stale 해진 절 |
> |---|---|
> | Phase 1-A: `_fail_error_detail` 배선 / Redfish 분기 복구 / `checked_ports` 정합 | §4 §8 §18 |
> | Phase 1-B: `status=failed` 에 `failure_reason` 보장 | §12 §16 |
> | Phase 2: `failure_stage` 에 `gather` 추가 + `failure_code` 7종 도입 | §10 §16 §17 |
> | Phase 3-A: OS 포트 감지를 공통 precheck 로 통합 (`wait_for` 3연타 제거) | §1-2 #3 §3 §5 |
> | Phase 3-B: OS 를 SSH identification / WinRM Identify 로 판정 | §6-4 |
> | Phase 4-A: Redfish 를 ServiceRoot **본문** 검증으로 판정 (status whitelist 제거) | §1-2 #5 §6-2 §17 |
> | Phase 4-B: ESXi 를 vim25 SOAP `RetrieveServiceContent` **본문** 검증으로 판정 (status whitelist 제거) | §1-2 #5 §6-3 §17 (ESX-004~007) |

---

## 1. Executive Summary

### 1-1. 구조 요약

`precheck_bundle` 은 Ansible custom module 이며 **컨트롤러에서** 실행된다(`delegate_to: localhost`).
외부 라이브러리를 쓰지 않고 `socket` / `ssl` / `urllib` / `json` / `base64` stdlib 만 사용한다.

4단계 진단(`reachable` → `port_open` → `protocol_supported` → `auth_success`)을 수행하지만,
**실제 운영에서 실행되는 것은 3단계뿐이다.**

### 1-2. 반드시 알아야 할 5가지 (전부 코드 실측)

| # | 사실 | 근거 |
|---|---|---|
| 1 | **Stage 1·2 는 별개 검사가 아니다.** `_check_ports()` 한 함수의 한 번의 포트 순회에서 갈린다 | `precheck_bundle.py:397-414`, 판정 `:489-505` |
| 2 | **Stage 4(인증)는 운영 경로에서 절대 실행되지 않는다.** 호출자가 username/password 를 넘기지 않음 | `run_precheck.yml:38-39` + `redfish-gather/site.yml:44-47` + `esxi-gather/site.yml:49-52` (`_precheck_username` 정의처 0건) |
| 3 | **OS 채널은 `precheck_bundle` 을 전혀 쓰지 않는다.** `wait_for` 3연타 별도 구현 | `run_precheck.yml` include 처 2곳뿐(`redfish-gather/site.yml:43`, `esxi-gather/site.yml:48`) / OS 는 `os-gather/site.yml:40-69` |
| 4 | **`detail` 필드(가장 구체적인 기술 오류 문자열)는 최종 envelope 에 도달하지 못한다.** `build_diagnosis` 가 버리고, `errors[].detail` 은 항상 `null` | `diagnosis_mapper.py:35-42`(detail 미포함) + `build_failed_output.yml:49` (`_fail_error_detail` 을 set 하는 코드가 저장소에 0건) |
| 5 | **프로토콜 검사는 응답 본문을 검증하지 않는다**(SSH 배너 제외). HTTP 2xx 면 내용 무관하게 통과 | `precheck_bundle.py:276-289`(redfish), `:363-364`(esxi) |

### 1-3. 실제 존재하는 failure_stage 값 (전 저장소 5종)

`reachable` / `port` / `protocol` / `auth` / `fallback` + `null`.
이 중 **`auth` 는 운영 경로에서 발생 불가**(§7), **`fallback` 은 precheck 와 무관한 최후 방어**(§11-6).

---

## 2. 실제 코드 기준 전체 호출 흐름

### 2-1. Redfish (BMC) 채널

| # | 파일 | Task / 함수 | 입력 | 출력 | 다음 |
|---|---|---|---|---|---|
| 1 | `redfish-gather/site.yml:36-38` | `redfish \| init fragments` | — | `_merged_data`(빈 뼈대), `_all_sec_*`, `_started_at`, `_started_epoch` | 2 |
| 2 | `redfish-gather/site.yml:41-47` | `redfish \| run precheck` (include) | `_precheck_host`, `_precheck_channel='redfish'`, `_precheck_timeout=30` | — | 3 |
| 3 | `run_precheck.yml:27-42` | `precheck \| 대상 호스트 연결 진단` | host, channel, ports=omit, timeout_port=3.0, timeout_protocol=30, timeout_auth=30, username=omit, password=omit | `_precheck_raw` | 4 |
| 4 | `precheck_bundle.py:461-556` | `run_module()` | AnsibleModule params | exit_json(result dict) | 5 |
| 4a | `precheck_bundle.py:397-414` | `_check_ports()` → `tcp_check()` `:109-142` | host, ports, 3.0 | any_response, target_port_open, open_port, port_errors | 4b |
| 4b | `precheck_bundle.py:426-434` | `_probe_protocol()` → `probe_redfish()` `:252-316` | host, open_port, 30 | ok, err, facts | 4c |
| 4c | `precheck_bundle.py:546-553` | Stage 4 분기 | username/password | **운영에서 미실행** | 5 |
| 5 | `run_precheck.yml:45-54` | `precheck \| 진단 결과 저장` | `_precheck_raw` | `_precheck_result`, `_precheck_ok` | 6 |
| 6 | `run_precheck.yml:56-58` | `precheck \| 공통 diagnosis 생성` | `_precheck_raw`, channel | `_diagnosis` (7키) | 7 |
| 7 | `run_precheck.yml:60-66` | `precheck \| 진단 실패 시 로그 출력` | `_precheck_ok` | stdout(callback 이 억제) | 8 |
| 8 | `redfish-gather/site.yml:49-56` | `redfish \| abort if precheck failed` | `_precheck_ok` | **fail → rescue** 또는 통과 | 9 / R1 |
| 9 | `redfish-gather/site.yml:59-60` | `detect vendor` | — | `_rf_detected_vendor`, `_rf_probe_facts`, `_va` | 10 |
| 10 | `redfish-gather/site.yml:63-70` | `select adapter` | `_rf_probe_facts` | `_selected_adapter` | 11 |
| 11 | `redfish-gather/site.yml:87-88` | `load vault` | adapter | `_rf_accounts` | 12 |
| 12 | `redfish-gather/site.yml:91-92` | `collect standard` | `_rf_accounts` | `_rf_raw_collect`, `_rf_collect_ok`, `_rf_attempts_meta` | 13 |
| 13 | `redfish-gather/site.yml:97-113` | `abort if collect completely failed` | `_rf_collect_ok` | **fail → rescue** 또는 통과 | 14 / R1 |
| 14 | `redfish-gather/site.yml:191-206` | `set output meta` | `_diagnosis` | `_diagnosis`(**auth_success=true 덮어쓰기** + details 확장) | 15 |
| 15 | `build_output.yml:32-63` | `build_output` | 누적 변수 전부 | `_output` (12 필드, details 에 `hostname_source` 추가) | 16 |
| 16 | `redfish-gather/site.yml:222-224` | `inject schema_version` | `_output` | `_output` (13 필드) | 17 |
| 17 | `redfish-gather/site.yml:256-272` | `OUTPUT` (always) | `_output` | `msg` = JSON 문자열 | 18 |
| 18 | `json_only.py:107-115` | `v2_runner_on_ok` | task name == `OUTPUT` | stdout 1줄 JSON (+`ANSIBLE_JSON_OUTPUT_FILE` append) | 19 |
| 19 | `Jenkinsfile_portal:241-272` | `Callback` stage | `gather_output.json` | `{"loc","deploymentEnvironmentId","gatherInfoJson":[...]}` | 20 |
| 20 | `Jenkinsfile_portal:285-321` | `httpRequest` | callbackBody | POST `{callbackUrl}/api/jenkins/gather/{target_type}` | 끝 |
| R1 | `redfish-gather/site.yml:226-252` | `rescue` | `ansible_failed_result` | `_fail_error_message` → `build_failed_output.yml` → `_output` | 17 |

### 2-2. ESXi (Virtualization) 채널

Redfish 와 동일 골격. 차이만 기록:

| # | 파일 | 차이점 |
|---|---|---|
| 2 | `esxi-gather/site.yml:46-52` | `_precheck_channel='esxi'`, `_precheck_timeout=30` (리터럴) |
| 4b | `precheck_bundle.py:433` | `probe_esxi()` `:350-372` 호출 |
| 8 | `esxi-gather/site.yml:54-61` | precheck 실패 시 fail (메시지 다름) |
| 9-11 | `esxi-gather/site.yml:64-78` | **vendor detect 없음.** 바로 `try_credentials` → 실패 시 fail `:69-78` |
| 12 | `esxi-gather/site.yml:80-92` | `collect facts` → `abort if facts failed` `:86-92` |
| 14 | `esxi-gather/site.yml:194-210` | `enrich diagnosis with adapter` — **auth_success=true 덮어쓰기** |
| R1 | `esxi-gather/site.yml:230-248` | rescue (메시지에 `[task: ...]` prefix **없음**) |

### 2-3. OS 채널 — **precheck_bundle 미사용, 완전 별도 구현**

| # | 파일 | Task | 입력 | 출력 | 다음 |
|---|---|---|---|---|---|
| 1 | `os-gather/site.yml:40-47` | `detect \| WinRM HTTPS (5986)` | host, port=5986, timeout=`_probe_timeout`(기본 2) | `_probe_winrm_https` (ignore_errors) | 2 |
| 2 | `os-gather/site.yml:49-57` | `detect \| WinRM HTTP (5985)` | `when: _probe_winrm_https is failed` | `_probe_winrm_http` | 3 |
| 3 | `os-gather/site.yml:59-69` | `detect \| SSH (22)` | `when: https failed and (http skipped or failed)` | `_probe_ssh` | 4 |
| 4 | `os-gather/site.yml:71-81` | `detect \| set os_type` | 3 probe 결과 | `_detected_os`(windows/linux/unknown), `_winrm_port`, `_winrm_scheme` | 5 |
| 5 | `os-gather/site.yml:87-131` | `add_host` ×3 | `_detected_os` | `_os_failed` / `_os_linux` / `_os_windows` 그룹 | 6 / 7 / 8 |
| 6 | `os-gather/site.yml:138-182` | PLAY 1.5 `failed-output` | `_os_failed` | **하드코딩 `_diagnosis`** `:158-166` → `build_failed_output` → OUTPUT | 끝 |
| 7 | `os-gather/site.yml:187-377` | PLAY 2 `linux` | `_os_linux` | try_credentials → gather ×8 → **하드코딩 `_diagnosis`** `:277-295` → OUTPUT | 끝 |
| 8 | `os-gather/site.yml:382-569` | PLAY 3 `windows` | `_os_windows` | try_credentials → gather ×8 → **하드코딩 `_diagnosis`** `:471-489` → OUTPUT | 끝 |

**핵심**: OS 채널에는 `reachable`/`port_open`/`protocol_supported` 를 **계산하는 코드가 없다.**
세 경로 전부 상수를 그대로 써넣는다(성공=전부 true / 실패=전부 false).

---

## 3. Target Type 및 Port Mapping

### 3-1. Target Type 전체 목록

`precheck_bundle.py:466` — `choices=["redfish", "os", "esxi"]`
Jenkins 파라미터(`Jenkinsfile_portal:238`)의 `target_type` 도 동일 3종.

### 3-2. 포트 후보 (실제 코드값)

**precheck_bundle 정의** (`precheck_bundle.py:95-99`):

```python
CHANNEL_DEFAULT_PORTS = {
    "redfish": [443],
    "os": [5986, 5985, 22],
    "esxi": [443],
}
```

**실제 검사 순서**

| Target Type | 포트 순서 | 검사 주체 | 타임아웃 |
|---|---|---|---|
| redfish | `443` | `precheck_bundle._check_ports` | 3.0초 (`run_precheck.yml:35`) |
| esxi | `443` | `precheck_bundle._check_ports` | 3.0초 |
| os (모듈 정의) | `5986 → 5985 → 22` | **운영 미사용** | 3.0초 |
| os (실제) | `5986 → 5985 → 22` | `os-gather/site.yml:40-69` `wait_for` | 2초/포트 (`:36`, `probe_timeout` 로 override 가능) |

**호출자가 `ports` 를 넘기는 코드는 저장소에 없다** — `_precheck_ports` 는 `run_precheck.yml:31` 에서
`| default(omit)` 로만 등장하고 정의처가 0건이므로 항상 채널 기본값이 쓰인다.

### 3-3. OS 포트 순서의 용도 — 3가지를 겸한다

`os-gather/site.yml:71-81` 기준:

| 용도 | 실제 수행 여부 |
|---|---|
| Port Detection | **O** — `wait_for` 가 TCP 연결 가능 여부 판정 |
| OS Detection | **O** — 열린 포트가 곧 OS 판정 (22=linux, 5985/5986=windows) |
| Protocol Detection | **X** — 배너·HTTP 응답 검사를 하지 않는다. TCP 연결만 본다 |

---

## 4. TCP Reachability 판정

### 4-1. `tcp_check()` — `precheck_bundle.py:109-142`

```python
last_err = "주소 해석 실패"                                    # :115
try:
    addr_infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
except socket.gaierror as e:
    return False, "DNS 해석 실패: {0}".format(e)               # :118-119
for family, socktype, proto, _canon, sockaddr in addr_infos:
    sock = None
    try:
        sock = socket.socket(family, socktype, proto)          # :126 (try 안 — Round 16)
        sock.settimeout(timeout)
        sock.connect(sockaddr)
        return True, None                                      # :129
    except socket.timeout:
        last_err = "연결 시간 초과 (timeout={0}s)".format(timeout)   # :130-131
    except ConnectionRefusedError:
        last_err = "연결 거부됨 (port={0})".format(port)             # :132-133
    except OSError as e:
        last_err = str(e)                                            # :134-135
    finally:
        ... sock.close()
return False, last_err                                          # :142
```

**동작 요약**

| 상황 | 반환 | 비고 |
|---|---|---|
| 3-way handshake 성공 | `(True, None)` | 첫 성공 주소에서 즉시 return |
| DNS 해석 실패 | `(False, "DNS 해석 실패: <gaierror>")` | 주소군 루프 진입 전 |
| `getaddrinfo` 가 빈 리스트 반환 | `(False, "주소 해석 실패")` | 루프 미실행 → 초기값 그대로 |
| RST(거부) | `(False, "연결 거부됨 (port=443)")` | — |
| 무응답 | `(False, "연결 시간 초과 (timeout=3.0s)")` | — |
| 기타 소켓 오류(`EAFNOSUPPORT`, `EHOSTUNREACH` 등) | `(False, str(OSError))` | Python 메시지 그대로 노출 |

**[관찰] `last_err` 는 마지막 주소군의 오류만 보존한다.**
`:115` 의 `last_err` 가 루프에서 매번 덮어써지고 `:142` 에서 마지막 값만 반환된다.
IPv6 가 RST, IPv4 가 timeout 인 경우 최종 err 는 timeout 이 되어 **RST 신호가 소실**된다.
영향은 §17-C 참조.

### 4-2. reachable / port_open 분리 — `_check_ports()` `:397-414`

```python
any_response = False
target_port_open = False
open_port = None
port_errors = []
for port in ports:
    ok, err = tcp_check(host, port, timeout_port)
    if ok:
        any_response = True; target_port_open = True; open_port = port; break   # :405-409
    if err and ("거부" in err or "refused" in err.lower()):
        any_response = True                                                     # :410-412
    port_errors.append("port={0}: {1}".format(port, err))                       # :413
```

**[관찰] `any_response` 판정은 한국어 부분 문자열 매칭에 의존한다** (`:411`).
`ConnectionRefusedError` 예외 타입이 아니라 `tcp_check` 가 만든 문자열 `"연결 거부됨 (port=N)"` 안의
`"거부"` 를 찾는다. `except OSError` `:134` 경로로 잡힌 `str(e)`(영문 `Connection refused` 포함 가능)는
`"refused" in err.lower()` 로 커버된다.

### 4-3. 최종 판정 — `run_module()` `:485-509`

```python
if not any_response:                                    # :489
    result["failure_stage"] = "reachable"               # :490
    result["failure_reason"] = ("대상 호스트에 연결할 수 없습니다. "
        "네트워크 도달 불가 또는 호스트가 꺼져 있습니다.")  # :491-493
    result["detail"] = "; ".join(port_errors)           # :495
    module.exit_json(**result)                          # :496  ← reachable=False, port_open=False
if not target_port_open:                                # :497
    result["reachable"] = True                          # :498
    result["failure_stage"] = "port"                    # :499
    result["failure_reason"] = ("호스트는 응답하지만 서비스 포트가 닫혀 있습니다. "
        "방화벽 또는 서비스 미기동 가능성.")               # :500-503
    result["detail"] = "; ".join(port_errors)           # :504
    module.exit_json(**result)                          # :505  ← port_open=False
result["reachable"] = True                              # :507
result["port_open"] = True                              # :508
result["selected_port"] = open_port                     # :509
```

---

## 5. Port 판정

### 5-1. 후보 포트 순회 결과별 분기 (redfish/esxi 는 후보 1개라 §5-2 만 유효)

| 상황 | any_response | target_port_open | failure_stage | selected_port |
|---|---|---|---|---|
| 첫 후보 성공 | true | true | null | 첫 후보 |
| 두 번째 후보 성공 | true | true | null | 두 번째 |
| 마지막 후보 성공 | true | true | null | 마지막 |
| 모든 후보 Refused | **true** | false | `port` | null |
| 일부 Refused + 일부 Timeout | **true** (거부가 하나라도 있으면) | false | `port` | null |
| 모든 후보 Timeout | false | false | `reachable` | null |
| 모든 후보 DNS 실패 | false | false | `reachable` | null |
| 예상 못 한 소켓 오류만 | false (문자열에 거부/refused 없으면) | false | `reachable` | null |

**주의**: "일부 Refused + 일부 Timeout" 은 **포트 단위** 로는 위 표대로 동작하지만,
**한 포트 안의 주소군 단위** 로는 §4-1 의 `last_err` 소실 때문에 다르게 동작할 수 있다(§17-C).

### 5-2. OS 채널 — `wait_for` 는 refused / timeout 을 구분하지 않는다

`os-gather/site.yml:41-46`:
```yaml
ansible.builtin.wait_for:
  host: "{{ ansible_host | default(inventory_hostname) }}"
  port: 5986
  timeout: "{{ _probe_timeout }}"
register: _probe_winrm_https
ignore_errors: yes
```

`state` 미지정 → 기본 `started`. `wait_for` 는 포트가 열릴 때까지 **폴링**하므로 RST 를 받아도
"아직 안 열림" 으로 보고 재시도하다가 timeout 시각에 실패한다. 결과적으로
**거부와 무응답이 동일한 실패 신호**가 되며, 판정에 쓰이는 것은 `is failed` 뿐이다(`:74-78`).

---

## 6. Protocol 판정

### 6-1. 공통 HTTP 계층 — `http_get()` `:177-216`

| 항목 | 값 | 근거 |
|---|---|---|
| 라이브러리 | `urllib.request` (stdlib) | `:189-197` |
| Method | GET (`Request(url)` 기본값) | `:189` |
| Request Header | **`Accept: application/json` 단 하나** | `:190` |
| 추가 헤더 | Basic auth 시에만 `Authorization` | `:191-193` |
| Timeout | 인자 `timeout` (protocol=30) | `:197` |
| TLS context | `_build_ssl_context(verify)` | `:188` |
| 인증서 검증 | `verify=False` 고정(호출자 전부) → `check_hostname=False`, `verify_mode=CERT_NONE` | `:153-155` |
| 응답 소켓 | `with` 컨텍스트 매니저로 결정적 close | `:197` |
| Body 파싱 | `json.loads` 시도, 실패 시 `json=None` (오류 아님) | `:200-203` |
| Response Header 검사 | **없음** | — |

TLS 완화(`verify=False` 한정, `:156-163`):
- `ssl.OP_LEGACY_SERVER_CONNECT` (존재할 때만)
- `ctx.set_ciphers('DEFAULT@SECLEVEL=0')` — 실패 시 `except ssl.SSLError: pass`

예외 → 반환 매핑:

| 예외 | 반환 `(ok, err, payload)` | 근거 |
|---|---|---|
| `urllib.error.HTTPError` | `(False, "HTTP {code}", {"status_code": code, "json": None})` | `:205-209` |
| `socket.timeout` | `(False, "요청 시간 초과 (timeout={t}s)", None)` | `:210-211` |
| `urllib.error.URLError` | `(False, "연결 실패: {reason[:200]}", None)` | `:212-214` |
| `ssl.SSLError` / `OSError` | `(False, str(e)[:200], None)` | `:215-216` |

**[관찰] `URLError` 는 `OSError` 의 하위 클래스이고 `except` 순서상 `:212` 가 먼저 잡는다.**
따라서 TLS 핸드셰이크 실패는 대부분 `:212` 의 `"연결 실패: ..."` 로 표현되고,
`:215` 는 `URLError` 로 감싸지지 않은 나머지 `OSError` 만 처리한다.

### 6-2. Redfish — `probe_redfish()` `:252-316`

| 항목 | 값 |
|---|---|
| Endpoint | `https://{host}:{port}/redfish/v1/` (`:269`) |
| Method | GET |
| 성공 인정 | HTTP 2xx **전부** (`ok=True`, `:276`) + status_code ∈ `{401, 403, 405, 406, 503}` (`:299`) |
| 실패 인정 | 그 외 모든 status_code (400/404/500/502/504 등) 및 연결 실패 |
| Body 검사 | **없음.** `json.loads` 성공 시 필드 추출만, 실패해도 성공 판정 유지 (`:277-289`) |
| Retry 조건 | `payload is None` 인 경우만 (`:310-312`) |
| Retry 횟수 | 최대 1회 (`for attempt in (1, 2)`, `:273`) |
| Retry 간격 | 1초 (`_time.sleep(1)`, `:314`) |

성공 시 `probe_facts`:

| 경로 | 필드 |
|---|---|
| 2xx + JSON dict (`:279-286`) | `redfish_version`(`RedfishVersion`), `product`(`Product`), `systems_uri`(`Systems.@odata.id`) |
| 2xx + 비-JSON 또는 비-dict | `{}` (빈 dict) |
| 401/403/405/406/503 (`:300-304`) | `root_status_code`, `requires_auth_at_root`(401·403), `header_negotiation_issue`(405·406) |
| retry 후 성공 (`:287-288`, `:305-306`) | 위에 더해 `retry_count: 1` |

### 6-3. ESXi — `probe_esxi()` `:350-372`

> [WARN] **Phase 4-B(2026-08-10)에서 이 절 전체가 stale 해졌다.** 아래 status whitelist 는
> 제거됐다. 현재는 `/sdk` 에 vim25 `RetrieveServiceContent` 를 POST 하고 응답이
> `{urn:vim25}RetrieveServiceContentResponse` → `returnval` → `about`(apiType/apiVersion)
> 인지, 또는 SOAP Fault detail 이 `urn:vim25`/`urn:internalvim25` 인지로 판정한다.
> HTTP status 는 Evidence 로만 남는다. 정본: `common/library/precheck_bundle.py`.

| 항목 | 값 |
|---|---|
| Endpoint | `https://{host}:{port}/sdk` (`:361`) |
| 성공 인정 | HTTP 2xx 전부 + status_code ∈ `{200, 301, 302, 401, 403, 404, 405, 500, 503}` (`:366`) |
| 실패 인정 | 그 외 (400/406/429/502/504 등) 및 연결 실패 |
| Retry | **없음** (단일 `http_get` 호출) |
| probe_facts | `vsphere_endpoint`; 비-2xx 허용 시 `root_status_code`, `requires_auth_at_root`(401·403) |

**Redfish 와의 차이**: esxi 는 **404 와 500 을 성공으로 인정**하고, redfish 는 인정하지 않는다.
반대로 redfish 는 **406 을 인정**하고 esxi 는 인정하지 않는다.

### 6-4. OS — `probe_os()` `:319-347` (**운영 미사용, 라이브러리 기능**)

| port | 동작 | 성공 조건 |
|---|---|---|
| 22 | `ssh_banner_check()` `:219-249` | 수신 배너가 `"SSH-"` 로 시작 (`:236`) |
| 5985 | `GET http://{host}:5985/wsman` | 2xx 또는 status ∈ `{200,401,403,405,503}` (`:336`) |
| 5986 | `GET https://{host}:5986/wsman` | 동일 |
| 그 외 | 즉시 실패 | `"지원하지 않는 OS 포트: {port}"` (`:347`) |

`ssh_banner_check` 세부:
- `sock.recv(256)` 로 배너 수신 (`:235`)
- 배너가 `SSH-` 로 시작 → `(True, None, {"ssh_banner": banner})`
- 아니면 `last_err = "SSH 배너가 아닙니다: {banner[:50]}"` 후 **다음 주소군 계속 시도** (`:238-240`)
- probe_facts: `{"transport":"winrm","scheme":...,"port":...}` (+`root_status_code`) `:337-344`

### 6-5. HTTP Status Code 전수 처리표

`probe_*` 함수가 status_code 를 명시 분기하는 것만 "특별 취급"으로 본다.

| Status | Redfish | ESXi | OS(WinRM) | 근거 |
|---|---|---|---|---|
| 200 | 성공(2xx 일반) | 성공(2xx + 명시) | 성공 | `:276` / `:363,366` / `:336` |
| 201 | 성공 (2xx — urlopen 이 예외 안 냄) | 성공 | 성공 | `:276` / `:363` / `:336` |
| 204 | 성공 (2xx) | 성공 | 성공 | 동상 |
| 301 | **미도달** — urllib 이 자동 리다이렉트 추적 | 명시 목록에 있으나 동일 이유로 대개 미도달 | 동일 | `:366` |
| 302 | **미도달** (동일) | 명시 목록에 있음 | 동일 | `:366` |
| 400 | **실패** (특별 취급 없음) | **실패** | **실패** | — |
| 401 | **성공 인정** + `requires_auth_at_root=true` | **성공 인정** + `requires_auth_at_root=true` | **성공 인정** | `:299,302` / `:366,370` / `:336` |
| 403 | **성공 인정** + `requires_auth_at_root=true` | **성공 인정** | **성공 인정** | 동상 |
| 404 | **실패** | **성공 인정** | **실패** | `:299`(없음) / `:366`(있음) / `:336`(없음) |
| 405 | **성공 인정** + `header_negotiation_issue=true` | **성공 인정** | **성공 인정** | `:299,303` / `:366` / `:336` |
| 406 | **성공 인정** + `header_negotiation_issue=true` | **실패** | **실패** | `:299,303` / `:366`(없음) |
| 408 | 실패 (특별 취급 없음) | 실패 | 실패 | — |
| 429 | 실패 (특별 취급 없음) | 실패 | 실패 | — |
| 500 | **실패** | **성공 인정** | **실패** | `:366` |
| 502 | 실패 (특별 취급 없음) | 실패 | 실패 | — |
| 503 | **성공 인정** | **성공 인정** | **성공 인정** | `:299` / `:366` / `:336` |
| 504 | 실패 (특별 취급 없음) | 실패 | 실패 | — |
| 그 외 | 실패, `detail="HTTP {code}"` | 동일 | 동일 | `:206` |

---

## 7. Authentication 판정

### 7-1. precheck Stage 4 — 실행 조건

```python
username = module.params.get("username")
password = module.params.get("password")
if username and password and channel == "redfish":        # :546-548
    if not _try_redfish_auth(...):                        # :549-552
        module.exit_json(**result)
# esxi/os 인증은 Ansible 본체 모듈이 처리 → auth_success는 None 유지   # :554
```

`_try_redfish_auth()` `:437-458`:
- `GET https://{host}:{port}/redfish/v1/Systems` + Basic auth (`:439-442`)
- 실패 → `auth_success=False`, `failure_stage="auth"`,
  `failure_reason="BMC 인증 실패: 사용자명 또는 비밀번호를 확인하세요."` (`:444-449`)
- 성공 → `auth_success=True`, `probe_facts["first_system_uri"]` (`:451-457`)

**운영에서 실행되지 않는 근거**: `_precheck_username` / `_precheck_password` 를
set 하는 코드가 저장소에 **0건**(`run_precheck.yml:38-39` 의 `| default(omit)` 만 존재).
따라서 `username=None` → `if` 불성립 → `auth_success` 는 `None` 유지.

### 7-2. 인증 상태별 실제 결과값

| 상태 | 실제 `auth_success` | 발생 위치 |
|---|---|---|
| 인증 자체를 수행하지 않음 (운영 precheck 전부) | **`null`** | `precheck_bundle.py:382` 초기값 유지 |
| Redfish 수집 성공 | `true` | `redfish-gather/site.yml:193` (덮어쓰기) |
| ESXi 수집 성공 | `true` | `esxi-gather/site.yml:202` (덮어쓰기) |
| OS 수집 성공 | `true` | `os-gather/site.yml:283`(linux) / `:477`(windows) — 상수 |
| **Redfish 인증 실패 (전 계정)** | **`null`** | rescue 경로. `_diagnosis` 는 precheck 값 그대로 |
| **ESXi 인증 실패 (전 계정)** | **`null`** | 동일 |
| **OS 인증 실패 (전 계정)** | **`null`** | rescue 경로. `_diagnosis` 미정의 → `build_failed_output.yml:79` 가 `none` |
| OS 포트 감지 실패 | **`false`** | `os-gather/site.yml:162` — 상수 |
| Credential 없음 (vault accounts 0개) | 위 성공/실패 규칙과 동일 | `collect_standard.yml:28-48` 빈 자격 1회 시도 |
| Vendor 미상으로 credential 선택 불가 | precheck 단계엔 해당 없음 (§7-1) | — |
| Account Locked / Auth timeout / Auth API 오류 | **구분 없음.** 전부 "수집 실패" 로 rescue | `try_one_account.yml:36-40` 은 status 만 봄 |
| 필드 자체가 없음 | **발생 안 함** — `_init_result` `:382` 가 항상 키를 만든다 | — |

### 7-3. 인증 실패가 `false` 가 아니라 `null` 인 이유 (코드 추적)

Redfish 기준:
1. `collect_standard.yml` → 전 계정 실패 → `_rf_collect_ok=false`
2. `redfish-gather/site.yml:97-113` `fail` → **rescue 진입**
3. rescue 는 `_diagnosis` 를 건드리지 않는다 (`:227-244` 는 `_out_*`/`_fail_*` 만 set)
4. `build_failed_output.yml:79` — `'diagnosis': _diagnosis | default(none)`
5. 따라서 precheck 가 만든 `auth_success: null` 이 그대로 최종 envelope 에 남는다

`auth_success=true` 를 쓰는 `site.yml:191-206` 은 **`abort if collect completely failed` 이후**
(`:97-113` → `:191`)라 실패 경로에서는 도달하지 않는다.

### 7-4. 채널별 실제 인증 수행 지점

| 채널 | 인증 코드 | 성공 판정식 |
|---|---|---|
| redfish | `try_one_account.yml:21-34` (`redfish_gather` 모듈) | `_rf_attempt is not failed and status != 'failed'` (`:38-40`) |
| esxi | `esxi-gather/tasks/try_credentials.yml:28-36` → `try_one_credential.yml` | `_e_auth_ok` |
| os linux | `os-gather/tasks/try_one_credential.yml:39-46` (`raw: echo __auth_ok__`) | `rc==0 and '__auth_ok__' in stdout` (`:62-63`) |
| os windows | `os-gather/tasks/try_one_credential.yml:48-54` (`win_ping`) | `ping == 'pong'` (`:68`) |

Redfish 계정 실패 시 **5초 backoff** (`try_one_account.yml:84-88`, BMC lockout 회피).

---

## 8. Retry 및 Timeout

### 8-1. Retry 전수

| 위치 | 조건 | 횟수 | 간격 |
|---|---|---|---|
| `probe_redfish` `:273,310-314` | `payload is None` (URLError/timeout/SSLError). **HTTP 응답이 오면 retry 안 함** | 1 | 1초 |
| `probe_esxi` | **없음** | — | — |
| `probe_os` | **없음** (`ssh_banner_check` 는 주소군 순회일 뿐 retry 아님) | — | — |
| `tcp_check` | **없음** (주소군 순회) | — | — |
| `try_one_account.yml:84-88` | 계정 실패 시 (retry 아니고 다음 계정 전 backoff) | 계정 수만큼 | 5초 |
| `Jenkinsfile_portal:281-321` | callback POST 비-2xx / 예외 | 3 | attempt×10초 (10s, 20s) |
| `wait_for` (OS) | 모듈 내부 폴링 | timeout 까지 | 기본 1초 |

### 8-2. Timeout 전수

| 단계 | 값 | 결정 위치 |
|---|---|---|
| precheck port | **3.0초 고정** | `run_precheck.yml:35` — `_precheck_timeout_port` 정의처 0건 |
| precheck protocol | 30초 | `run_precheck.yml:36` ← `_precheck_timeout` (redfish `_rf_timeout=30` `site.yml:29` / esxi 리터럴 30 `site.yml:52`) |
| precheck auth | 30초 (미사용) | `run_precheck.yml:37` |
| 모듈 기본값 | port 3.0 / protocol 15.0 / auth 8.0 | `precheck_bundle.py:469-471` |
| OS 포트 감지 | 2초/포트 | `os-gather/site.yml:36` (`probe_timeout` 로 override) |
| redfish 수집 | 30초 | `try_one_account.yml:29` |
| Jenkins callback | 300초 | `Jenkinsfile_portal:295` |

**[관찰] 듀얼스택에서 타임아웃은 주소군마다 적용된다.** `tcp_check` `:127` 의 `settimeout` 이
루프 안에 있어 IPv6+IPv4 둘 다 timeout 이면 실제 대기는 약 2×3=6초다.

---

## 9. PASS / FAIL 최종 조건

### 9-1. precheck PASS 조건 (실제 코드식)

`run_precheck.yml:48-54`:
```jinja
_precheck_ok: >-
  {{
    _precheck_raw.reachable | default(false) | bool
    and _precheck_raw.port_open | default(false) | bool
    and _precheck_raw.protocol_supported | default(false) | bool
    and (_precheck_raw.failure_stage is none or _precheck_raw.failure_stage | default('') == '')
  }}
```

| 질문 | 답 | 근거 |
|---|---|---|
| `auth_success` 가 PASS 판단에 포함되는가? | **아니오** | 조건식에 없음 |
| `failure_stage` 가 별도로 검사되는가? | **예** — 4번째 항으로 명시 검사 | `:53` |
| `protocol_supported=null` 이면? | `null \| bool` → **false** → FAIL | Jinja2 `bool` 필터 |
| 필드가 없으면? | `default(false)` → FAIL. `failure_stage` 만 `default('')` → 통과 취급 | `:50-53` |

### 9-2. PASS 후 게이트

| 채널 | 게이트 | 실패 시 |
|---|---|---|
| redfish | `site.yml:49-56` `when: not (_precheck_ok \| bool)` → `fail` | rescue |
| esxi | `site.yml:54-61` 동일 | rescue |
| os | **precheck 게이트 없음.** `_detected_os == 'unknown'` 이면 `_os_failed` 그룹 | PLAY 1.5 |

### 9-3. 최종 envelope `status` 는 precheck 와 무관하다

`build_status.yml:51-66` — **섹션 status 만** 본다.
```jinja
supported_vals = sections.values() | reject('equalto','not_supported')
if supported_vals|length == 0      -> failed
elif failed_count == 0             -> success
elif success_count == 0            -> failed
else                               -> partial
```
precheck 실패 경로는 `build_failed_output.yml:50,77` 이 `status: 'failed'` 를 **하드코딩**한다.

---

## 10. Target Type 별 전체 진단 Matrix

> 표의 문자열·Boolean·null 은 전부 코드에서 확인한 실제 값이다.
> `최종 판정` = envelope 최상위 `status`.
> `사용자 메시지` = envelope `errors[0].message` (§12 의 MSG-ID 로 표기).

### 10-1. Redfish (BMC)

| Case ID | 상황 | TCP 결과 | reachable | port_open | protocol_supported | auth_success | failure_stage | failure_reason | errors[0].message | status |
|---|---|---|---|---|---|---|---|---|---|---|
| BMC-001 | 443 open + ServiceRoot 200 + 수집·인증 성공 | success | true | true | true | **true** | null | null | (errors 없음 또는 경고) | success |
| BMC-002 | 443 open + 200 + 일부 섹션 실패 | success | true | true | true | true | null | null | 섹션별 경고 | partial |
| BMC-003 | 443 RST | refused | **true** | false | false | **null** | `port` | MSG-002 | MSG-101 | failed |
| BMC-004 | 443 무응답(장비 OFF / DROP) | timeout | false | false | false | **null** | `reachable` | MSG-001 | MSG-101 | failed |
| BMC-005 | DNS 해석 실패 | gaierror | false | false | false | null | `reachable` | MSG-001 | MSG-101 | failed |
| BMC-006 | 443 open + Redfish 아닌 응답(404 등) | success | true | true | **false** | null | `protocol` | MSG-003 | MSG-101 | failed |
| BMC-007 | 443 open + 200 이지만 Redfish 아님(일반 웹서버) | success | true | true | **true** | null | null | null | MSG-102 (수집 단계 실패) | failed |
| BMC-008 | 443 open + 401 | success | true | true | **true** | null | null | null | 이후 수집 결과에 따름 | (수집 결과) |
| BMC-009 | 443 open + 403 | success | true | true | **true** | null | null | null | 동상 | (수집 결과) |
| BMC-010 | 443 open + 405 | success | true | true | **true** | null | null | null | 동상 | (수집 결과) |
| BMC-011 | 443 open + 406 | success | true | true | **true** | null | null | null | 동상 | (수집 결과) |
| BMC-012 | 443 open + 503 | success | true | true | **true** | null | null | null | 동상 | (수집 결과) |
| BMC-013 | 443 open + 500 | success | true | true | **false** | null | `protocol` | MSG-003 | MSG-101 | failed |
| BMC-014 | 443 open + TLS 핸드셰이크 실패 | success | true | true | false | null | `protocol` | MSG-003 | MSG-101 | failed |
| BMC-015 | 프로토콜 1차 timeout → retry 성공 | success | true | true | true | null | null | null | — | (수집 결과) |
| BMC-016 | 프로토콜 timeout ×2 | success | true | true | false | null | `protocol` | MSG-003 | MSG-101 | failed |
| BMC-017 | precheck 통과 + 전 계정 인증 실패 | success | true | true | true | **null** | null | null | MSG-105 | failed |
| BMC-018 | precheck 통과 + 인증 성공 + system_uri 부재 | success | true | true | true | **null** | null | null | MSG-106 | failed |
| BMC-019 | block/rescue 모두 실패 (`_output` 미생성) | — | **null** | **null** | **null** | **null** | `fallback` | MSG-201 | MSG-201 | failed |

**BMC-008~012 주의**: precheck 는 통과하므로 `failure_stage=null` 이다. 최종 status 는
그 이후 `collect_standard` 결과로 결정되며 precheck 진단값은 성공 시 `auth_success=true` 로 덮인다.

### 10-2. ESXi (Virtualization)

| Case ID | 상황 | reachable | port_open | protocol_supported | auth_success | failure_stage | failure_reason | errors[0].message | status |
|---|---|---|---|---|---|---|---|---|---|
| ESX-001 | 443 open + /sdk 응답 + 인증·수집 성공 | true | true | true | **true** | null | null | — | success |
| ESX-002 | 443 RST | **true** | false | false | null | `port` | MSG-002 | MSG-103 | failed |
| ESX-003 | 443 무응답 | false | false | false | null | `reachable` | MSG-001 | MSG-103 | failed |
| ESX-004 | 443 open + /sdk 400·406·502·504 | true | true | **false** | null | `protocol` | MSG-004 | MSG-103 | failed |
| ESX-005 | 443 open + /sdk 404 | true | true | **true** | null | null | null | (이후 단계) | (수집 결과) |
| ESX-006 | 443 open + /sdk 500 | true | true | **true** | null | null | null | (이후 단계) | (수집 결과) |
| ESX-007 | 443 open + /sdk 401·403 | true | true | **true** | null | null | null | (이후 단계) | (수집 결과) |

> [WARN] **ESX-004~007 은 Phase 4-B(2026-08-10) 이후 성립하지 않는다.** status 로 판정하지
> 않으므로 404/500/401/403 이어도 본문이 vim25 가 아니면 `protocol_supported=false` +
> `failure_stage=protocol` + `failure_code=PROTOCOL_CHECK_FAILED` 다. 반대로 본문이 vim25
> ServiceContent 또는 vim25 Fault 면 status 와 무관하게 통과한다. `auth_success` 는
> 어느 경우에도 `null` 을 유지한다(Protocol Probe 는 자격증명을 보내지 않는다).
| ESX-008 | precheck 통과 + 전 계정 인증 실패 | true | true | true | **null** | null | null | MSG-107 | failed |
| ESX-009 | precheck·인증 통과 + vmware_host_facts 실패 | true | true | true | **null** | null | null | MSG-108 | failed |
| ESX-010 | block/rescue 모두 실패 | null | null | null | null | `fallback` | MSG-201 | MSG-201 | failed |

### 10-3. OS (Linux / Windows) — **precheck_bundle 미사용**

| Case ID | 상황 | reachable | port_open | protocol_supported | auth_success | failure_stage | failure_reason | errors[0].message | status |
|---|---|---|---|---|---|---|---|---|---|
| OS-001 | 5986 open + 인증·수집 성공 | true | true | true | true | null | null | — | success |
| OS-002 | 5986 closed + 5985 open + 성공 | true | true | true | true | null | null | — | success |
| OS-003 | 5986·5985 closed + 22 open + 성공 | true | true | true | true | null | null | — | success |
| OS-004 | 세 포트 모두 실패 (refused / timeout 구분 없음) | **false** | **false** | **false** | **false** | **`port`** | MSG-005 | MSG-005 | failed |
| OS-005 | 포트 감지 성공 + 전 계정 인증 실패 (linux) | **null**† | null† | null† | null† | null† | null† | MSG-109 | failed |
| OS-006 | 포트 감지 성공 + 전 계정 인증 실패 (windows) | null† | null† | null† | null† | null† | null† | MSG-110 | failed |
| OS-007 | 수집 중 예외 (linux) | null† | null† | null† | null† | null† | null† | MSG-111 | failed |
| OS-008 | 수집 중 예외 (windows) | null† | null† | null† | null† | null† | null† | MSG-112 | failed |
| OS-009 | 22 open 이지만 SSH 아님 | (OS-005 와 동일) | | | | | | MSG-109 | failed |
| OS-010 | block/rescue 모두 실패 | null | null | null | null | `fallback` | MSG-201 | MSG-201 | failed |

**† 중요**: OS-005~008 은 `_diagnosis` 자체가 **정의되지 않은 채** rescue 로 진입한다.
`build_failed_output.yml:79` 의 `'diagnosis': _diagnosis | default(none)` 에 의해
**`diagnosis` 필드 전체가 `null`** 이 된다 — 개별 필드가 null 인 것이 아니라 **객체가 통째로 null**이다.
(PLAY 2/3 의 `_diagnosis` set_fact 는 `:277`/`:471` 로, 모든 gather 완료 **후** 실행된다.)

---

## 11. Case 별 최종 JSON

### 11-0. 표기 규칙

- 실행 환경에 따라 달라지는 값은 `<...>` 또는 문서용 주소 `192.0.2.10` 사용.
- envelope 은 **6가지 형태**밖에 없다. 아래에 각 형태의 **전체 JSON** 을 싣고,
  나머지 Case 는 **달라지는 필드만** 표기한다(동일 구조 반복 회피).

### 11-1. [형태 A] 정상 — Redfish 수집 성공 (BMC-001)

생성 경로: `build_output.yml:47-63` + `site.yml:222-224`

```json
{
  "target_type": "redfish",
  "collection_method": "redfish_api",
  "ip": "192.0.2.10",
  "hostname": "<System.HostName 또는 BMC NetworkProtocol.HostName>",
  "vendor": "dell",
  "status": "success",
  "sections": {
    "system": "success", "hardware": "success", "bmc": "success",
    "cpu": "success", "memory": "success", "storage": "success",
    "network": "success", "firmware": "success", "users": "success",
    "power": "success", "thermal": "success"
  },
  "diagnosis": {
    "reachable": true,
    "port_open": true,
    "protocol_supported": true,
    "auth_success": true,
    "failure_stage": null,
    "failure_reason": null,
    "details": {
      "channel": "redfish",
      "adapter_candidate": "redfish_dell_idrac9",
      "checked_ports": [443],
      "selected_port": 443,
      "redfish_version": "1.17.0",
      "product": "Integrated Dell Remote Access Controller",
      "systems_uri": "/redfish/v1/Systems",
      "auth": {
        "attempted_count": 1,
        "used_label": "<label>",
        "used_role": "primary",
        "fallback_used": false
      },
      "account_service": {},
      "multi_node_layout": null,
      "rmc_activation_check": null,
      "hostname_source": "system"
    }
  },
  "meta": {
    "started_at": "<ISO8601>Z",
    "finished_at": "<ISO8601>Z",
    "duration_ms": "<int>",
    "adapter_id": "redfish_dell_idrac9",
    "adapter_version": "<str|null>",
    "ansible_version": "<str>"
  },
  "correlation": {
    "serial_number": "<str|null>",
    "system_uuid": "<str|null>",
    "bmc_ip": "192.0.2.10",
    "host_ip": "192.0.2.10"
  },
  "errors": [],
  "data": { "system": {}, "hardware": {}, "bmc": {}, "cpu": {}, "memory": {},
            "storage": {}, "network": {}, "firmware": [], "users": [],
            "power": {}, "thermal": {} },
  "schema_version": "1"
}
```

> `details` 키 순서는 `diagnosis_mapper.py:38-58`(channel, adapter_candidate, checked_ports,
> selected_port, probe_facts…) → `site.yml:194-205`(adapter_candidate 덮어쓰기, auth,
> account_service, multi_node_layout, rmc_activation_check) → `build_output.yml:55-58`
> (hostname_source) 순으로 누적된다.
> **타입 주의**: `ansible.cfg:44` 에 `jinja2_native = True` 가 설정돼 있어
> `"{{ ... | int }}"` / `"{{ ... | bool }}"` 형태의 단일 표현식은 문자열이 아니라
> **네이티브 타입(int/bool)으로 직렬화된다.** 따라서 `attempted_count`(`collect_standard.yml:76`),
> `duration_ms`(`build_meta.yml:22`), Windows `selected_port`(`os site.yml:486`) 는 전부 정수이고,
> `fallback_used`(`collect_standard.yml:79-81`) 는 불리언이다.

### 11-2. [형태 B] precheck 실패 — Redfish 도달 불가 (BMC-004 / CASE 1 / CASE 3)

생성 경로: `site.yml:49-56` fail → `:226-248` rescue → `build_failed_output.yml`

```json
{
  "target_type": "redfish",
  "collection_method": "redfish_api",
  "ip": "192.0.2.10",
  "hostname": null,
  "vendor": null,
  "status": "failed",
  "sections": {
    "system": "failed", "hardware": "failed", "bmc": "failed",
    "cpu": "failed", "memory": "failed", "storage": "failed",
    "network": "failed", "firmware": "failed",
    "users": "not_supported", "power": "not_supported", "thermal": "not_supported"
  },
  "diagnosis": {
    "reachable": false,
    "port_open": false,
    "protocol_supported": false,
    "auth_success": null,
    "failure_stage": "reachable",
    "failure_reason": "대상 호스트에 연결할 수 없습니다. 네트워크 도달 불가 또는 호스트가 꺼져 있습니다.",
    "details": {
      "channel": "redfish",
      "adapter_candidate": null,
      "checked_ports": [443]
    }
  },
  "meta": {
    "started_at": "<ISO8601>Z",
    "finished_at": "<ISO8601>Z",
    "duration_ms": null,
    "adapter_id": null,
    "adapter_version": null,
    "ansible_version": "<str>"
  },
  "correlation": {
    "serial_number": null, "system_uuid": null,
    "bmc_ip": null, "host_ip": "192.0.2.10"
  },
  "errors": [
    {
      "section": "redfish_gather",
      "message": "[task: redfish | abort if precheck failed] Redfish 호스트 연결 진단 실패 (192.0.2.10) — 단계=reachable, 사유=대상 호스트에 연결할 수 없습니다. 네트워크 도달 불가 또는 호스트가 꺼져 있습니다.. BMC 전원, 네트워크, Redfish API(443) 포트를 확인하세요.",
      "detail": null
    }
  ],
  "data": {
    "system": null, "hardware": null, "bmc": null, "cpu": null, "memory": null,
    "storage": {"filesystems": [], "physical_disks": [], "datastores": [],
                "controllers": [], "logical_volumes": [], "hbas": [], "infiniband": [],
                "summary": {"groups": [], "grand_total_gb": 0}},
    "network": {"dns_servers": [], "default_gateways": [], "interfaces": [],
                "adapters": [], "ports": [], "virtual_switches": [], "portgroups": [],
                "driver_map": [], "summary": {"groups": []}},
    "users": [], "firmware": [], "power": null,
    "thermal": {"temperatures": [], "fans": []}
  },
  "schema_version": "1"
}
```

**주목할 4가지**
1. `details` 에 **`selected_port` 키 자체가 없다** (`diagnosis_mapper.py:50-52` — falsy 면 미추가).
2. `details` 에 **`hostname_source` 가 없다** — `build_failed_output` 은 `build_output` 을 안 쓴다.
3. `errors[0].detail` 이 **`null`** — precheck 가 만든 `detail`
   (`"port=443: 연결 시간 초과 (timeout=3.0s)"`)이 전달 경로에서 **소실**된다(§1-2 #4).
4. `_fail_error_message` 의 `..사유=...다.. BMC` 부분에 **마침표가 2개** 연속 — `failure_reason`
   자체가 마침표로 끝나는데 템플릿이 `.` 를 또 붙인다(`site.yml:54`).

### 11-3. [형태 B'] precheck 실패 — 포트 닫힘 (BMC-003 / CASE 2)

형태 B 와 동일하고 `diagnosis` 만 다르다.

```json
"diagnosis": {
  "reachable": true,
  "port_open": false,
  "protocol_supported": false,
  "auth_success": null,
  "failure_stage": "port",
  "failure_reason": "호스트는 응답하지만 서비스 포트가 닫혀 있습니다. 방화벽 또는 서비스 미기동 가능성.",
  "details": { "channel": "redfish", "adapter_candidate": null, "checked_ports": [443] }
}
```
`errors[0].message` 의 `단계=port, 사유=호스트는 응답하지만...` 부분만 바뀐다.

### 11-4. [형태 B''] precheck 실패 — 프로토콜 (BMC-006/013/014/016 / CASE 4·7·10·12·14)

```json
"diagnosis": {
  "reachable": true,
  "port_open": true,
  "protocol_supported": false,
  "auth_success": null,
  "failure_stage": "protocol",
  "failure_reason": "이 장비는 Redfish를 지원하지 않습니다.",
  "details": {
    "channel": "redfish",
    "adapter_candidate": null,
    "checked_ports": [443],
    "selected_port": 443
  }
}
```
`selected_port` 가 **있다**(포트는 열렸으므로). `probe_facts` 는 `{}` 라 병합되지 않는다
(`diagnosis_mapper.py:57` — 빈 dict 는 update 안 함).

### 11-5. [형태 C] precheck 통과 후 수집 실패 — Redfish 인증 실패 (BMC-017 / CASE 5·6 이후)

형태 B 골격 + `diagnosis` 는 **precheck 성공값 그대로**:

```json
"diagnosis": {
  "reachable": true,
  "port_open": true,
  "protocol_supported": true,
  "auth_success": null,
  "failure_stage": null,
  "failure_reason": null,
  "details": {
    "channel": "redfish",
    "adapter_candidate": null,
    "checked_ports": [443],
    "selected_port": 443,
    "root_status_code": 401,
    "requires_auth_at_root": true,
    "header_negotiation_issue": false
  }
}
```
```json
"errors": [{
  "section": "redfish_gather",
  "message": "[task: redfish | abort if collect completely failed] Redfish 수집 실패 — 인증 실패 (192.0.2.10). 네트워크/Redfish API는 정상 (Redfish ? / Unknown).\nvault/redfish/dell.yml 자격증명을 확인하세요. 시도된 계정 수: 3.",
  "detail": null
}]
```

**주의**: 위 메시지의 `Redfish ? / Unknown` 은 `d.details.redfish_version` 이 없기 때문이다.
401 경로에서는 `redfish_version`/`product` 대신 `root_status_code` 만 채워진다(`:300-304`).
`site.yml:108` 이 `default('?')`/`default('Unknown')` 로 대체한다.
`sections` 는 `_selected_adapter.capabilities.sections_supported` 가 있으면 그 목록,
없으면 기본 8종(`site.yml:239-241`)이 `failed` 가 된다.

### 11-6. [형태 D] OS 포트 감지 실패 (OS-004 / CASE 24)

생성 경로: `os-gather/site.yml:149-182` (PLAY 1.5)

```json
{
  "target_type": "os",
  "collection_method": "agent",
  "ip": "192.0.2.20",
  "hostname": null,
  "vendor": null,
  "status": "failed",
  "sections": {
    "system": "failed", "hardware": "not_supported", "bmc": "not_supported",
    "cpu": "failed", "memory": "failed", "storage": "failed",
    "network": "failed", "firmware": "not_supported",
    "users": "failed", "power": "not_supported", "thermal": "not_supported"
  },
  "diagnosis": {
    "reachable": false,
    "port_open": false,
    "protocol_supported": false,
    "auth_success": false,
    "failure_stage": "port",
    "failure_reason": "SSH(22)/WinRM(5985/5986) 모두 응답 없음",
    "details": { "checked_ports": [22, 5985, 5986] }
  },
  "meta": { "started_at": "<ISO8601>Z", "finished_at": "<ISO8601>Z",
            "duration_ms": null, "adapter_id": null, "adapter_version": null,
            "ansible_version": "<str>" },
  "correlation": { "serial_number": null, "system_uuid": null,
                   "bmc_ip": null, "host_ip": "192.0.2.20" },
  "errors": [{
    "section": "os_detect",
    "message": "SSH(22)/WinRM(5985/5986) 모두 응답 없음 — 대상 서버의 방화벽, SSH/WinRM 서비스 상태, 네트워크 연결을 확인하세요.",
    "detail": null
  }],
  "data": { "...형태 B 와 동일한 빈 뼈대..." },
  "schema_version": "1"
}
```

**형태 B 대비 차이 4가지**
1. `details` 에 `channel` / `adapter_candidate` 가 **없다** (`build_diagnosis` 필터 미사용).
2. `checked_ports` 가 `[22, 5985, 5986]` — **실제 검사 순서(5986→5985→22)와 역순**.
3. `auth_success: false` — 인증을 시도조차 안 했는데 `false`(다른 채널은 `null`).
4. `failure_stage: "port"` 인데 `reachable: false` — 모듈 규약상 모순(§17-A).

### 11-7. [형태 E] OS 인증 실패 / 수집 예외 (OS-005~008)

```json
{
  "target_type": "os",
  "collection_method": "agent",
  "ip": "192.0.2.20",
  "hostname": null,
  "vendor": null,
  "status": "failed",
  "sections": { "system": "failed", "cpu": "failed", "memory": "failed",
                "storage": "failed", "network": "failed", "users": "failed",
                "hardware": "not_supported", "bmc": "not_supported",
                "firmware": "not_supported", "power": "not_supported",
                "thermal": "not_supported" },
  "diagnosis": null,
  "meta": { "...": "..." },
  "correlation": { "...": "..." },
  "errors": [{
    "section": "linux_gather",
    "message": "Linux SSH 인증 후보 3개 모두 실패 — vault/linux.yml accounts 와 대상 서버 sshd 설정을 확인하세요.",
    "detail": null
  }],
  "data": { "...빈 뼈대..." },
  "schema_version": "1"
}
```

**`"diagnosis": null`** — 진단 객체 자체가 없다. 전 채널 통틀어 유일하게 이 형태가 나온다.

### 11-8. [형태 F] 최후 fallback (BMC-019 / ESX-010 / OS-010)

생성 경로: `redfish-gather/site.yml:258-272` (esxi `:254-268`, os `:363-377`/`:555-569`).
`_output` 이 아예 만들어지지 못한 경우(block·rescue 모두 실패).

```json
{
  "schema_version": "1",
  "target_type": "redfish",
  "collection_method": "redfish_api",
  "ip": "192.0.2.10",
  "hostname": "192.0.2.10",
  "vendor": null,
  "status": "failed",
  "sections": {},
  "diagnosis": {
    "reachable": null, "port_open": null, "protocol_supported": null,
    "auth_success": null, "failure_stage": "fallback",
    "failure_reason": "_output 미생성 — block/rescue 모두 실패",
    "details": { "gather_mode": "fallback", "reason": "_output 미생성 — block/rescue 모두 실패" }
  },
  "meta": {},
  "correlation": {},
  "errors": [{ "section": "gather", "message": "_output 미생성 — block/rescue 모두 실패" }],
  "data": {}
}
```

**이 형태만의 특이점**: `schema_version` 이 **첫 키**이고, `sections`/`meta`/`correlation`/`data`
가 **빈 객체**이며, `hostname` 이 **IP 로 채워진다**(다른 경로는 IP fallback 금지 — `build_output.yml:26-31`).
`errors[0]` 에 **`detail` 키가 없다**(다른 경로는 항상 존재).

### 11-9. §16 요청 CASE 매핑

| CASE | 내용 | 결과 |
|---|---|---|
| 1 | 장비 전원 OFF | **BMC-004 / 형태 B** — `failure_stage="reachable"`, MSG-001 |
| 2 | 443 Closed, RST | **BMC-003 / 형태 B'** — `reachable=true`, `failure_stage="port"`, MSG-002 |
| 3 | 방화벽 DROP | **CASE 1 과 완전히 동일** (§17-B). 구분 불가 |
| 4 | 443 Open, 일반 HTTPS 웹서버 | 응답 코드에 따라 갈림: 404/400/500 → **형태 B''**(protocol) / **200 → 형태 C 계열로 통과**(§18-D) |
| 5 | Redfish 401 | precheck **통과**. `details.root_status_code=401`, `requires_auth_at_root=true`. 이후 수집 결과가 status 결정 |
| 6 | Redfish 403 | CASE 5 와 동일 (`requires_auth_at_root=true`) |
| 7 | Redfish 404 | **형태 B''** — `failure_stage="protocol"`, MSG-003 |
| 8 | Redfish 405 | precheck 통과. `header_negotiation_issue=true` |
| 9 | Redfish 406 | precheck 통과. `header_negotiation_issue=true` |
| 10 | Redfish 500 | **형태 B''** — protocol 실패 |
| 11 | Redfish 503 | precheck 통과. `root_status_code=503`, 두 플래그 모두 false |
| 12 | TLS 핸드셰이크 실패 | **형태 B''** — `detail`(내부)`="연결 실패: ..."`. **retry 1회 발생** |
| 13 | 프로토콜 1차 timeout → retry 성공 | precheck 통과 + `details.retry_count = 1` |
| 14 | timeout ×2 | **형태 B''** — `detail`(내부)`="요청 시간 초과 (timeout=30.0s)"` |
| 15 | IPv6 실패 → IPv4 성공 | 정상 통과. 대기 시간만 최대 2배 |
| 16 | 모든 주소 Refused | **형태 B'** — `reachable=true`, `failure_stage="port"` |
| 17 | 한 주소 Timeout + 다른 주소 Refused | **순서 의존** — 마지막 주소가 refused 면 형태 B', timeout 이면 형태 B (§17-C) |
| 18 | DNS 해석 실패 | **형태 B** — `failure_stage="reachable"`, MSG-001 (§17-D) |
| 19 | SSH 22 Open + 정상 배너 | **OS 경로엔 배너 검사 없음.** 포트만 보고 linux 판정 |
| 20 | 22 Open + SSH 아님 | **OS-009** — linux 로 판정 후 인증 단계에서 실패 → 형태 E |
| 21 | 5986 Open + WinRM 정상 | **OS-001** — windows, scheme=https |
| 22 | 5986 Closed + 5985 Open | **OS-002** — windows, `_winrm_port='5985'`, scheme=http (`site.yml:79-80`) |
| 23 | 5986/5985 Closed + 22 Open | **OS-003** — linux |
| 24 | 세 포트 모두 Closed | **OS-004 / 형태 D** |

CASE 19~24 는 **redfish/esxi 경로에는 존재하지 않는 Case** 다(포트 후보가 443 하나).
CASE 1~18 중 5~14 는 **OS 경로에 존재하지 않는 Case** 다(프로토콜 검사 자체가 없음).

---

## 12. 실제 사용자 메시지 전체 목록

> Message ID 는 **본 분석용 임시 ID** 다. 코드에는 메시지 ID 체계가 존재하지 않는다.

### 12-1. precheck 모듈 내부 (`common/library/precheck_bundle.py`)

| ID | 문자열 | 발생 조건 | failure_stage | Target | 위치 | 노출 |
|---|---|---|---|---|---|---|
| MSG-001 | `대상 호스트에 연결할 수 없습니다. 네트워크 도달 불가 또는 호스트가 꺼져 있습니다.` | `any_response == False` | `reachable` | redfish/esxi | `:491-493` | `diagnosis.failure_reason` |
| MSG-002 | `호스트는 응답하지만 서비스 포트가 닫혀 있습니다. 방화벽 또는 서비스 미기동 가능성.` | `target_port_open == False` | `port` | redfish/esxi | `:500-503` | `diagnosis.failure_reason` |
| MSG-003 | `이 장비는 Redfish를 지원하지 않습니다.` | protocol probe 실패 | `protocol` | redfish | `:103` | `diagnosis.failure_reason` |
| MSG-004 | `vSphere API endpoint가 응답하지 않습니다.` | protocol probe 실패 | `protocol` | esxi | `:105` | `diagnosis.failure_reason` |
| MSG-004b | `SSH 또는 WinRM 서비스가 응답하지 않습니다.` | protocol probe 실패 | `protocol` | os | `:104` | **운영 미도달** |
| MSG-004c | `프로토콜 확인 실패` | `CHANNEL_PROTOCOL_MESSAGES` 미등록 채널 | `protocol` | — | `:523-525` | **도달 불가**(choices 3종이 모두 등록됨) |
| MSG-100 | `BMC 인증 실패: 사용자명 또는 비밀번호를 확인하세요.` | Stage 4 인증 실패 | `auth` | redfish | `:446-448` | **운영 미도달** |

### 12-2. precheck `detail` 필드 (내부 진단용 — **최종 envelope 미도달**)

| ID | 문자열 | 위치 |
|---|---|---|
| DET-001 | `주소 해석 실패` | `:115` (getaddrinfo 빈 결과) / `:221` |
| DET-002 | `DNS 해석 실패: {gaierror}` | `:119`, `:225` |
| DET-003 | `연결 시간 초과 (timeout={t}s)` | `:131` |
| DET-004 | `연결 거부됨 (port={p})` | `:133` |
| DET-005 | `{str(OSError)}` — Python 원문 | `:135`, `:242` |
| DET-006 | `port={p}: {err}` (`; ` 로 join) | `:413` → `:495`, `:504` |
| DET-007 | `HTTP {code}` | `:206` |
| DET-008 | `요청 시간 초과 (timeout={t}s)` | `:211` |
| DET-009 | `연결 실패: {reason[:200]}` | `:214` |
| DET-010 | `{str(e)[:200]}` | `:216` |
| DET-011 | `SSH 배너가 아닙니다: {banner[:50]}` | `:240` |
| DET-012 | `지원하지 않는 OS 포트: {port}` | `:347` |
| DET-013 | `알 수 없는 채널: {channel}` | `:434` — **도달 불가**(argument_spec choices 로 차단) |

### 12-3. Playbook 사용자 메시지 (envelope `errors[].message` 로 노출)

| ID | 문자열(요약) | 발생 조건 | Target | 위치 |
|---|---|---|---|---|
| MSG-101 | `[task: {실패task}] Redfish 호스트 연결 진단 실패 ({ip}) — 단계={stage}, 사유={reason}. BMC 전원, 네트워크, Redfish API(443) 포트를 확인하세요.` | precheck FAIL | redfish | `site.yml:51-55` + rescue `:244` |
| MSG-102 | `Redfish 수집 실패 — BMC가 Redfish API 미응답 ({ip}:443). Redfish 서비스 활성화 / BMC 펌웨어 버전 호환성을 확인하세요.` | `_rf_collect_ok=false` + `protocol_supported=false` | redfish | `site.yml:105-106` |
| MSG-102a | `Redfish 수집 실패 — BMC 도달 불가 ({ip}). ICMP/네트워크 경로, BMC 전원 상태를 확인하세요.` | `reachable=false` | redfish | `site.yml:101-102` |
| MSG-102b | `Redfish 수집 실패 — BMC TCP/443 포트 닫힘 ({ip}). 방화벽 규칙, BMC 측 HTTPS 서비스 상태를 확인하세요.` | `port_open=false` | redfish | `site.yml:103-104` |
| MSG-105 | `Redfish 수집 실패 — 인증 실패 ({ip}). 네트워크/Redfish API는 정상 (Redfish {ver} / {product}). vault/redfish/{vendor}.yml 자격증명을 확인하세요. 시도된 계정 수: {n}.` | `auth_success` is none 또는 false | redfish | `site.yml:107-109` |
| MSG-106 | `Redfish 수집 실패 — 인증 후 endpoint 수집 단계 실패 ({ip}). 펌웨어 호환성 / OEM 경로 문제 가능. errors[] 상세 확인.` | 위 모든 분기 미해당 | redfish | `site.yml:110-111` |
| MSG-103 | `ESXi 호스트 연결 진단 실패 ({ip}) — 단계={stage}, 사유={reason}. ESXi 호스트 전원, 네트워크, vSphere API(443) 포트를 확인하세요.` | precheck FAIL | esxi | `esxi site.yml:56-60` |
| MSG-107 | `ESXi 인증 후보 {n}개 모두 실패 — vault/esxi.yml accounts 와 ESXi 호스트 lockdown/local user 설정을 확인하세요.` | `_e_auth_ok=false` | esxi | `esxi site.yml:71-73` |
| MSG-108 | `vmware_host_facts 수집 실패 ({ip}) — 인증/네트워크 모두 정상이나 vSphere API 호출 실패. 사용 계정: {label}. 가능한 원인: (1) 계정의 vSphere 권한 부족 (Read-Only / System.View 필요), (2) ESXi 펌웨어 호환성 (지원: 6.7 / 7.x / 8.x), (3) 라이선스 만료, (4) lockdown 모드.` | `_e_facts_ok=false` | esxi | `esxi site.yml:88-91` |
| MSG-005 | `SSH(22)/WinRM(5985/5986) 모두 응답 없음 — 대상 서버의 방화벽, SSH/WinRM 서비스 상태, 네트워크 연결을 확인하세요.` | `_detected_os == 'unknown'` | os | `os site.yml:157` |
| MSG-005r | `SSH(22)/WinRM(5985/5986) 모두 응답 없음` (짧은 판) | 동상 | os | `os site.yml:164` → `failure_reason` |
| MSG-109 | `Linux SSH 인증 후보 {n}개 모두 실패 — vault/linux.yml accounts 와 대상 서버 sshd 설정을 확인하세요.` | `_os_auth_ok=false` | os linux | `os site.yml:220-222` |
| MSG-110 | `Windows WinRM 인증 후보 {n}개 모두 실패 — vault/windows.yml accounts 와 대상 서버 WinRM 설정을 확인하세요.` | `_os_auth_ok=false` | os windows | `os site.yml:409-411` |
| MSG-111 | `Linux 수집 예외` (기본값) 또는 `ansible_failed_result.msg` | 수집 중 예외 | os linux | `os site.yml:349` |
| MSG-112 | `Windows 수집 예외` (기본값) 또는 `ansible_failed_result.msg` | 수집 중 예외 | os windows | `os site.yml:541` |
| MSG-113 | `Redfish 수집 예외` (기본값) | rescue 기본 메시지 | redfish | `site.yml:244` |
| MSG-114 | `ESXi 수집 예외` (기본값) | rescue 기본 메시지 | esxi | `esxi site.yml:240` |
| MSG-201 | `_output 미생성 — block/rescue 모두 실패` | `_output` undefined | 전 채널 | `redfish:267,270` / `esxi:263,266` / `os:372,375,564,567` |
| MSG-202 | `수집 실패 — 채널={t}, IP={ip} (자세한 사유는 diagnosis.failure_stage / failure_reason 참조)` | `_fail_error_message` 미정의 | 전 채널 | `build_failed_output.yml:43-48` — **현재 전 호출자가 메시지를 넘기므로 미도달** |

### 12-4. 내부 로그 전용 (callback 이 stdout 에서 제거 → 사용자 미노출)

| 문자열 | 위치 |
|---|---|
| `[진단 실패] {host}: 단계={stage}, 사유={reason}` | `run_precheck.yml:62-65` (debug) |
| `adapter={adapter_id}` | `redfish site.yml:74` (debug) |
| `attempt failed — label=..., role=..., username=..., status=..., vendor=..., first_error=...` | `try_one_account.yml:69-75` (debug) |
| `{os_type} auth attempt failed — label=..., role=...` | `try_one_credential.yml:85-88` (debug) |
| `vault accounts 비어 있음 (vault/redfish/{profile}.yml). 자격증명 없이 수집 시도.` | `collect_standard.yml:22-24` |
| `vault accounts 비어 있음 (esxi) — 자격증명 없이 진행 시도.` | `esxi try_credentials.yml:25` |
| `REPO_ROOT 환경변수가 설정되지 않았습니다. ...` | `init_fragments.yml:27-29` (assert fail_msg) |

**노출 여부 근거**: `json_only.py:142-157` 이 `v2_playbook_on_task_start` 등 전 이벤트를 `pass`
처리하고, `v2_runner_on_ok` `:107-109` 는 **task 이름이 정확히 `OUTPUT`** 일 때만 출력한다.
따라서 `debug` 태스크의 msg 는 stdout 에 나오지 않는다.

---

## 13. Exception 및 예외 처리

### 13-1. precheck 모듈 내부 예외

| 예외 | 처리 | 결과 |
|---|---|---|
| `socket.gaierror` | `:118-119` catch | `failure_reason` = MSG-001, `detail` = DET-002 |
| `socket.timeout` | `:130-131` catch | `detail` = DET-003 |
| `ConnectionRefusedError` | `:132-133` catch | `detail` = DET-004, `any_response=True` |
| `OSError` (그 외) | `:134-135` catch | `detail` = Python 원문 |
| `urllib.error.HTTPError` | `:205-209` catch | `detail` = `HTTP {code}`, payload 보존 |
| `urllib.error.URLError` | `:212-214` catch | `detail` = `연결 실패: {reason}` |
| `ssl.SSLError` | `:215-216` catch (대부분 URLError 가 선점) | `detail` = str(e)[:200] |
| JSON decode 오류 | `:200-203` catch | **오류 아님** — `json=None` 으로 계속 진행 |
| `ssl.SSLError` (set_ciphers) | `:162-163` catch → `pass` | 무시 |
| `sock.close()` 실패 | `:140-141` `except Exception: pass` | 무시 |
| SSH recv 중 임의 예외 | `:241-242` `except Exception` | `last_err = str(e)` |

**모듈이 raise 로 죽는 경로는 없다.** 전 예외를 흡수하고 `module.exit_json` 으로 정상 종료한다.
따라서 `precheck_bundle` 태스크가 Ansible `failed` 가 되는 경우는 실질적으로 없다.

### 13-2. Playbook 레벨 예외

| 상황 | 처리 | 사용자 도달 |
|---|---|---|
| `ansible.builtin.fail` (precheck/수집/인증 게이트) | block → rescue | `errors[0].message` 에 `ansible_failed_result.msg` |
| 수집 태스크 예외 | block → rescue | 동상 (redfish 는 `[task: ...]` prefix 포함 `:244`) |
| OEM 수집/정규화 예외 | **local rescue** `redfish site.yml:148-162` | `errors[]` 에 `[OEM 비치명] ...` 경고. 표준 섹션 보존, status 는 success/partial |
| rescue 자체 실패 | `always` 블록 fallback | 형태 F (MSG-201) |
| `REPO_ROOT` 미설정 | `init_fragments.yml:23-29` assert | rescue → 형태 B 계열 |
| Jinja2 undefined | rescue 로 흡수 | `ansible_failed_result.msg` 에 Ansible 원문 |
| host unreachable (SSH/WinRM) | `try_one_credential.yml:45,53` `ignore_unreachable: true` | host 보존 → 인증 실패로 처리 → 형태 E |
| OUTPUT 태스크 자체 실패 | `json_only.py:117-128` | **stderr** 로 `{"error_type":"task_failed",...}` |
| OUTPUT 태스크 host unreachable | `json_only.py:130-138` | **stderr** 로 `{"error_type":"host_unreachable",...}` |
| JSON 직렬화 불가 객체 | `json_only.py:75-78` | `str(data)` fallback |
| callback 출력 파일 쓰기 실패 | `json_only.py:85-92` | stderr 경고, stdout 은 정상 |

**[관찰] stderr 로 나가는 `error_type` 2종은 envelope 이 아니다.**
`Jenkinsfile_portal:243` 은 `gather_output.json`(stdout 파일)만 읽으므로, 이 경우 해당 host 의
결과 줄이 **아예 없다**. 포털은 그 host 를 "결과 없음" 으로 보게 된다.

---

## 14. `diagnosis.details` 전체 Schema

### 14-1. 필드 표

| 필드 | Type | 생성 위치 | 의미 | 언제 존재하는가 | Example |
|---|---|---|---|---|---|
| `channel` | string | `diagnosis_mapper.py:39` | 수집 채널 | redfish/esxi **항상**. os **없음** | `"redfish"` |
| `adapter_candidate` | string\|null | `diagnosis_mapper.py:40` → site.yml 덮어씀 | 선택된 adapter id | redfish/esxi 항상(precheck 시 null), os 성공 경로만 | `"redfish_dell_idrac9"` |
| `checked_ports` | list[int] | `diagnosis_mapper.py:41` | 검사한 포트 목록 | **항상** | `[443]` |
| `detected_os` | string\|null | `diagnosis_mapper.py:46` (os 채널) / `os site.yml:289,483` | 감지된 OS | precheck os 채널(미사용) + OS 성공 경로 | `"linux"` |
| `detected_port` | int\|null | `diagnosis_mapper.py:47` | 감지 포트 | precheck os 채널만 → **운영 미도달** | `22` |
| `selected_port` | int | `diagnosis_mapper.py:50-52` / `os site.yml:290,486` | 선택된 포트 | **truthy 일 때만** (falsy 면 키 자체 없음) | `443` |
| `redfish_version` | string\|null | `precheck_bundle.py:280` | ServiceRoot `RedfishVersion` | redfish 2xx + JSON dict | `"1.17.0"` |
| `product` | string\|null | `precheck_bundle.py:281` / `esxi site.yml:208` | 제품명 | 위 동일 / esxi 성공 | `"..."` |
| `systems_uri` | string\|null | `precheck_bundle.py:286` | Systems 컬렉션 URI | redfish 2xx + JSON dict | `"/redfish/v1/Systems"` |
| `root_status_code` | int | `precheck_bundle.py:301`, `:343`, `:369` | 비-200 허용 status | 401/403/405/406/503 등 허용 경로 | `401` |
| `requires_auth_at_root` | bool | `precheck_bundle.py:302`, `:370` | 401·403 여부 | 위 동일 | `true` |
| `header_negotiation_issue` | bool | `precheck_bundle.py:303` | 405·406 여부 | redfish 허용 경로 | `false` |
| `retry_count` | int | `precheck_bundle.py:288`, `:306` | 재시도 횟수 | **attempt > 1 일 때만** | `1` |
| `vsphere_endpoint` | string | `precheck_bundle.py:364`, `:368` | /sdk URL | esxi 성공 | `"https://.../sdk"` |
| `ssh_banner` | string | `precheck_bundle.py:237` | SSH 배너 원문 | os 22 성공 → **운영 미도달** | `"SSH-2.0-OpenSSH_8.0"` |
| `transport` | string | `precheck_bundle.py:339` | `"winrm"` 고정 | os 5985/5986 → **운영 미도달** | `"winrm"` |
| `scheme` | string | `precheck_bundle.py:340` | http/https | 위 동일 | `"https"` |
| `port` | int | `precheck_bundle.py:341` | winrm 포트 | 위 동일 | `5986` |
| `first_system_uri` | string | `precheck_bundle.py:457` | Systems 첫 멤버 | Stage 4 성공 → **운영 미도달** | `"/redfish/v1/Systems/1"` |
| `auth` | dict | `redfish site.yml:196` / `esxi:205` / `os:295,489` | 인증 시도 메타 | 성공 경로 | `{"attempted_count":"3",...}` |
| `account_service` | dict | `redfish site.yml:197` | 계정 자동복구 메타 | redfish 성공 경로 | `{}` |
| `multi_node_layout` | string\|null | `redfish site.yml:198` | RMC 레이아웃 | redfish 성공 경로 | `null` |
| `rmc_activation_check` | bool\|null | `redfish site.yml:199-204` | RMC 활성 확인 | redfish 성공 경로 | `null` |
| `esxi_version` | string\|null | `esxi site.yml:206` | ESXi 버전 | esxi 성공 | `"8.0.2"` |
| `esxi_build` | string\|null | `esxi site.yml:207` | 빌드 번호 | esxi 성공 | `"..."` |
| `gather_mode` | string | `os site.yml:292` / fallback `:267` 등 | python_ok / raw / fallback | OS linux 성공 + 형태 F | `"python_ok"` |
| `python_version` | string | `os site.yml:293` | 원격 Python 버전 | OS linux 성공 | `"3.12.3"` |
| `hostname_source` | string | `build_output.yml:39-43` | system / bmc / none | **성공 경로만** (build_output 경유 시) | `"system"` |
| `reason` | string | `redfish site.yml:267` 등 | fallback 사유 | 형태 F 만 | `"_output 미생성..."` |

### 14-2. §12 요청 필드 중 **존재하지 않는** 것

`resolved_addresses`, `address_family`, `tcp_result`, `tcp_error`, `connection_refused`,
`timeout`, `any_response`, `protocol`, `endpoint`(redfish/os), `http_status`(이름이 다름 —
`root_status_code`), `http_reason`, `response_headers`, `response_body`, `banner`(이름이 다름 —
`ssh_banner`), `tls_error`, `elapsed_time`, `vendor`(details 안에는 없음 — envelope 최상위에 존재),
`target_type`(details 안에는 없음 — envelope 최상위에 존재).

---

## 15. 최종 결과 JSON Schema

### 15-1. envelope (13 필드)

```
envelope
├─ target_type        : string   (required, non-null)  "redfish"|"esxi"|"os"
├─ collection_method  : string   (required, non-null)  "redfish_api"|"vsphere_api"|"agent"
├─ ip                 : string   (required, non-null)
├─ hostname           : string|null (required)
├─ vendor             : string|null (required)
├─ status             : string   (required, non-null)  "success"|"partial"|"failed"
├─ sections           : object   (required)  11키 각각 "success"|"failed"|"not_supported"
├─ diagnosis          : object|null (required)         ← null 은 OS 인증실패/수집예외 경로만
├─ meta               : object|null (required)
├─ correlation        : object|null (required)
├─ errors             : array    (required)
├─ data               : object   (required)
└─ schema_version     : string   (required)            "1" 고정
```

| 필드 | 생성 코드 | 수정되는 코드 | 최종 소비 |
|---|---|---|---|
| 전 13필드(성공) | `build_output.yml:47-63` | `site.yml` inject `schema_version` | json_only → Jenkins → 포털 |
| 전 13필드(실패) | `build_failed_output.yml:71-97` | 동상 | 동상 |
| 전 13필드(fallback) | 각 `site.yml` always 인라인 | — | 동상 |

### 15-2. diagnosis 하위

```
diagnosis  (object|null)
├─ reachable           : boolean|null   (required when diagnosis != null)
├─ port_open           : boolean|null   (required)
├─ protocol_supported  : boolean|null   (required)
├─ auth_success        : boolean|null   (required)   true|false|null 전부 발생
├─ failure_stage       : string|null    (required)   "reachable"|"port"|"protocol"|"auth"|"fallback"|null
├─ failure_reason      : string|null    (required)
└─ details             : object         (required)   §14 표 참조 (키 집합이 경로마다 다름)
```

| 필드 | 생성 | 수정 | 소비 |
|---|---|---|---|
| `reachable`/`port_open`/`protocol_supported` | `precheck_bundle.py:379-381` → `diagnosis_mapper.py:61-63` | 없음(precheck 이후 불변) | `redfish site.yml:101-106` 분기 / 포털 |
| `auth_success` | `precheck_bundle.py:382` | `redfish:193`, `esxi:202`, `os:283,477`(상수) | `redfish site.yml:107` 분기 / 포털 |
| `failure_stage` | `precheck_bundle.py:383,445,490,499,522` / `os:163` / fallback | 없음 | `run_precheck.yml:53` PASS 판정, 메시지 조립 |
| `failure_reason` | 동상 | 없음 | 메시지 조립 |
| `details` | `diagnosis_mapper.py:38-58` | `redfish:194-205`/`esxi:203-209`/`build_output.yml:55-58` | 포털 |

### 15-3. errors[] 요소

```
errors[i]
├─ section : string   (required)   "redfish_gather"|"esxi_gather"|"linux_gather"|
│                                  "windows_gather"|"os_detect"|"oem"|"gather"|"unknown"|<섹션명>
├─ message : string   (required)
└─ detail  : any|null (형태 F 에서는 키 자체 없음)
```
정규화: `build_errors.yml:13-47` (문자열/dict/비-iterable 방어).

---

## 16. 상태값과 메시지의 잠재적 모순

### 16-A. `reachable=false` + `failure_stage="port"` — **실제 발생**

`os-gather/site.yml:158-166` 이 두 값을 동시에 하드코딩한다.
`precheck_bundle` 규약(`:497-499`)상 `failure_stage="port"` 는 `reachable=True` 를 전제하므로,
같은 envelope 스키마 안에서 **모순된 조합**이 나온다. redfish/esxi 경로에서는 발생하지 않는다.

### 16-B. `protocol_supported=true` + `port_open=false` — **발생 불가**

`run_module()` `:497-505` 가 `port_open` 실패 시 `exit_json` 으로 즉시 종료하므로
`protocol_supported` 는 `False` 초기값을 벗어날 수 없다. OS 경로도 세 값을 함께 상수로 넣는다.

### 16-C. `failure_stage="protocol"` + `failure_reason`이 네트워크 문구 — **발생 불가**

`failure_reason` 은 `failure_stage` 를 set 하는 같은 블록에서 함께 set 된다
(`:490-493`, `:499-503`, `:522-525`, `:445-448`). 분리 대입 경로가 없다.

### 16-D. `auth_success=false` 인데 인증을 시도하지 않음 — **실제 발생**

`os-gather/site.yml:162`. 다른 모든 경로는 "시도 안 함 = `null`" 규약을 따르는데
OS 포트 실패 경로만 `false` 다. 소비자가 `auth_success === false` 를 "자격증명 오류" 로
해석하면 오판한다.

### 16-E. `status="failed"` 인데 `diagnosis=null` — **실제 발생**

OS 인증 실패/수집 예외(형태 E). 소비자가 `diagnosis.failure_stage` 를 무조건 참조하면
null 역참조가 난다.

### 16-F. `failure_stage=null` 인데 `status="failed"` — **실제 발생**

형태 C(BMC-017/018, ESX-008/009). precheck 는 전부 통과했고 그 이후 단계에서 실패했기 때문에
`failure_stage` 가 `null` 로 남는다. **"어디서 막혔는가" 를 `failure_stage` 만으로 알 수 없는
유일한 구간**이며, 사유는 `errors[0].message` 에만 있다.

### 16-G. `errors` 가 비어있지 않은데 `status="success"` — **의도된 동작**

`build_status.yml:19-49` 가 명시하는 시나리오 B. OEM 비치명 실패(`redfish site.yml:149-159`) 등.

### 16-H. `checked_ports` 순서가 실제 검사 순서와 불일치 — **실제 발생**

`os-gather/site.yml:166` 이 `[22, 5985, 5986]` 인데 실제 순서는 `5986 → 5985 → 22` (`:40-69`).

### 16-I. 마침표 중복 — **실제 발생**

`redfish site.yml:54` / `esxi site.yml:59` 가 `사유={{ failure_reason }}.` 형태인데
MSG-001~004 가 이미 마침표로 끝난다 → `...가능성..` / `...습니다..`.

---

## 17. 구현상 기술적으로 애매한 판정

### 17-A. Connection Refused → `reachable=true`

```
현재 구현: any_response=True → reachable=true (precheck_bundle.py:410-412, :498)
기술적 의미: TCP RST 를 받았으므로 완전한 무응답은 아니다.
주의: RST 가 최종 대상 장비에서 왔다고 단정할 수 없다. 경로상 방화벽·로드밸런서·
      라우터가 REJECT 정책으로 RST 를 대신 보낼 수 있다. 그 경우 장비가 꺼져 있어도
      reachable=true 로 판정된다.
```

### 17-B. 방화벽 DROP 과 장비 OFF 가 구분되지 않는다

```
현재 구현: 둘 다 socket.timeout → any_response=False → failure_stage="reachable"
기술적 의미: TCP 레벨에서 두 상황의 신호는 동일하다(무응답).
주의: failure_reason MSG-001 은 "네트워크 도달 불가 또는 호스트가 꺼져 있습니다" 로
      두 가능성을 병기하나, 세 번째 가능성(방화벽 DROP)은 문구에 없다.
```

### 17-C. 주소군별 오류가 마지막 것만 남는다

```
현재 구현: tcp_check 의 last_err 는 루프에서 덮어써지고 마지막 값만 반환 (:115, :142)
기술적 의미: IPv6=RST, IPv4=timeout 인 호스트는 last_err="연결 시간 초과" 가 되어
             :411 의 "거부" 매칭이 실패 → any_response=False → reachable=false.
             RST 를 받았음에도 "도달 불가" 로 판정된다.
주의: 반대 순서(IPv6=timeout, IPv4=RST)면 reachable=true 가 된다.
      즉 DNS 가 반환하는 주소 순서에 따라 진단 결과가 달라질 수 있다.
```

### 17-D. DNS 해석 실패가 "네트워크 도달 불가" 로 표현된다

```
현재 구현: gaierror → err="DNS 해석 실패: ..." → :411 매칭 실패 → failure_stage="reachable"
           → failure_reason=MSG-001
기술적 의미: 이름 해석 실패는 네트워크 도달성과 다른 층위의 문제다.
주의: 구체 사유(DET-002)는 detail 에만 있고 그 detail 은 envelope 에 실리지 않는다(§1-2 #4).
      소비자는 "DNS 문제" 임을 알 방법이 없다.
```

### 17-E. HTTP 2xx 면 본문 검증 없이 프로토콜 통과

```
현재 구현: probe_redfish :276-289 / probe_esxi :363-364 는 ok(2xx) 이면 본문과 무관하게
           True 를 반환한다. JSON 파싱 실패는 오류로 처리하지 않는다(:200-203).
기술적 의미: 443 에서 임의의 웹서버가 /redfish/v1/ 에 200 + HTML 을 주면
             protocol_supported=true 가 된다.
주의: SSH 경로(:236)만 배너 내용을 검증한다. HTTP 계열 3종은 내용 검증이 없다.
```

### 17-F. 401/403/405/406/503 → `protocol_supported=true`

```
현재 구현: precheck_bundle.py:299-307
기술적 의미: 해당 status 를 반환했다는 것은 HTTP 레이어가 동작한다는 증거이지,
             Redfish/vSphere 규격을 구현한다는 증거는 아니다(§17-E 와 같은 뿌리).
주의: 이 설계는 인증 강화 펌웨어를 살리기 위한 의도된 선택이다(:255-263 주석).
```

### 17-G. Redfish 와 ESXi 의 허용 status 목록이 다르다

```
현재 구현: redfish {401,403,405,406,503} / esxi {200,301,302,401,403,404,405,500,503}
기술적 의미: 같은 "프로토콜 살아있음" 판정인데 404 와 500 은 esxi 만, 406 은 redfish 만 인정.
주의: 두 목록이 서로 다른 근거는 코드 주석에 없다.
```

### 17-H. 22 open → Linux, 5986 open → Windows

```
현재 구현: os-gather/site.yml:71-81 (포트만 보고 OS 판정)
기술적 의미: 포트 번호는 관례일 뿐 OS 를 증명하지 않는다. Windows 에 OpenSSH 서버가
             있으면 22 가 열리고, 그 호스트는 linux 로 판정되어 SSH 경로로 수집된다.
주의: precheck_bundle 의 probe_os(:330-331)는 배너를 검증하지만 이 경로는 쓰이지 않는다.
```

### 17-I. `wait_for` 가 refused / timeout 을 구분하지 않는다

```
현재 구현: os-gather/site.yml:41-69 (state 기본값 started = 폴링)
기술적 의미: RST 를 받아도 "아직 안 열림" 으로 재시도하다 timeout 실패한다.
주의: 그 결과 OS 경로는 reachable / port_open 을 구분할 정보 자체가 없고,
      site.yml:159-160 이 둘 다 false 상수로 넣는다.
```

### 17-J. `_precheck_result` 는 만들어지지만 아무도 쓰지 않는다

```
현재 구현: run_precheck.yml:47 이 set_fact. 저장소 전체에서 소비처 0건(grep 실측).
기술적 의미: dead variable. 동작 영향 없음.
```

---

## 18. 코드와 주석·문서의 불일치

| # | 위치 | 주석/문서 서술 | 실제 코드 | 영향 |
|---|---|---|---|---|
| D-1 | `diagnosis_mapper.py:35-37` | "detail 정보는 envelope `errors[0].detail` 에 이미 존재. diagnosis.details 에 중복 추가 안 함" | `_fail_error_detail` 을 set 하는 코드가 **저장소에 0건** → `errors[0].detail` 은 항상 `null`. detail 은 **어디에도 남지 않는다** | 진단 정보 소실 (§1-2 #4) |
| D-2 | `precheck_bundle.py:9` | "1. reachable — TCP 포트 연결로 호스트 도달 가능성 확인" (단계 1·2 분리 서술) | `_check_ports()` `:397-414` 한 함수의 한 순회에서 동시 판정 | 흐름도 오작도 위험 |
| D-3 | `.claude/rules/27-precheck-guard-first.md` R1 | "ping → port → protocol → auth 순서" | ICMP ping 미사용. TCP connect | 용어 혼동 |
| D-4 | `precheck_bundle.py:11` | "3. protocol_supported — 프로토콜 핸드셰이크" | HTTP 계열은 핸드셰이크가 아니라 GET 1회 + status 코드 판정. 본문 미검증 | 판정 강도 오해 |
| D-5 | `run_precheck.yml:22` | 출력 변수로 `_precheck_result` 명시 | 소비처 0건 (§17-J) | 없음 (문서상 잔재) |
| D-6 | `build_sections.yml:15` | "10개 섹션" | `:23-24` 는 **11개** (thermal 포함) | 주석만 stale |
| D-7 | `precheck_bundle.py:87-94` | (2026-08-10 추가) "os 채널은 production 에서 호출되지 않는다" | **코드와 일치** — 본 분석에서 grep 재확인 | 없음 |
| D-8 | `precheck_bundle.py:534-545` | (2026-08-10 추가) "Stage 4 는 항상 skip" | **코드와 일치** | 없음 |
| D-9 | `os-gather/site.yml:166` | `checked_ports: [22, 5985, 5986]` | 실제 순서는 `5986 → 5985 → 22` (`:40-69`) | 소비자 오해 |
| D-10 | `diagnosis_mapper.py:11` | 사용 예시 `build_diagnosis('redfish', 'dell_idrac9')` | 실제 호출은 2인자 (`run_precheck.yml:58`) → `adapter_id` 항상 `None` | 예시만 불일치 |

---

## 19. AI REVIEW DATA

### A. Target Type

```
redfish   — BMC (Redfish API), collection_method="redfish_api"
esxi      — Virtualization (vSphere API), collection_method="vsphere_api"
os        — Operating System (Linux/Windows), collection_method="agent"
```
정의: `precheck_bundle.py:466` (`choices`), `Jenkinsfile_portal:238`.

### B. Port Mapping

```
redfish : [443]                   검사 주체 = precheck_bundle,  타임아웃 3.0s
esxi    : [443]                   검사 주체 = precheck_bundle,  타임아웃 3.0s
os      : [5986, 5985, 22]        검사 주체 = wait_for(os-gather/site.yml:40-69), 타임아웃 2s/포트
          (precheck_bundle 에도 동일 목록이 정의돼 있으나 운영 미사용)
검사 순서: 목록 순서대로, 첫 성공에서 중단
```

### C. Diagnosis State

| 필드 | 의미 | 실제 가능한 값 |
|---|---|---|
| `reachable` | TCP 연결 시도에 **어떤 형태로든 응답**이 있었는가 (성공 또는 RST) | `true` / `false` / `null`(fallback) |
| `port_open` | 대상 포트에 TCP 연결이 **성립**했는가 | `true` / `false` / `null`(fallback) |
| `protocol_supported` | 해당 포트가 기대 프로토콜로 **응답**했는가 (HTTP 는 status 기반, SSH 는 배너 기반) | `true` / `false` / `null`(fallback) |
| `auth_success` | 인증 성공 여부. **precheck 는 판정하지 않음** — 수집 성공 시 site.yml 이 true 로 덮어씀 | `true` / `false`(OS 포트실패 경로 한정) / `null` |
| `failure_stage` | 막힌 단계 | `"reachable"` / `"port"` / `"protocol"` / `"auth"`(운영 미발생) / `"fallback"` / `null` |
| `failure_reason` | 사람이 읽는 사유 | §E 목록 / `null` |
| `details` | 부가 진단 (§14) | object (키 집합은 경로마다 다름) |
| (diagnosis 자체) | — | object / **`null`** (OS 인증실패·수집예외 경로) |

### D. Failure Stage 전체 목록

```
"reachable"   precheck_bundle.py:490
"port"        precheck_bundle.py:499  /  os-gather/site.yml:163
"protocol"    precheck_bundle.py:522
"auth"        precheck_bundle.py:445   ← 운영 경로에서 발생 불가
"fallback"    redfish:267 / esxi:263 / os:372,564   ← precheck 무관, 최후 방어
null          성공 경로 및 precheck 통과 후 실패 경로
```

### E. Failure Reason 전체 목록 (실제 문자열)

```
"대상 호스트에 연결할 수 없습니다. 네트워크 도달 불가 또는 호스트가 꺼져 있습니다."
"호스트는 응답하지만 서비스 포트가 닫혀 있습니다. 방화벽 또는 서비스 미기동 가능성."
"이 장비는 Redfish를 지원하지 않습니다."
"SSH 또는 WinRM 서비스가 응답하지 않습니다."          ← 운영 미도달
"vSphere API endpoint가 응답하지 않습니다."
"프로토콜 확인 실패"                                  ← 도달 불가 (fallback of dict.get)
"BMC 인증 실패: 사용자명 또는 비밀번호를 확인하세요."   ← 운영 미도달
"SSH(22)/WinRM(5985/5986) 모두 응답 없음"
"_output 미생성 — block/rescue 모두 실패"
null
```

### F. Protocol Success 조건

```
redfish : HTTP 2xx (본문 무관) OR status ∈ {401, 403, 405, 406, 503}
esxi    : HTTP 2xx (본문 무관) OR status ∈ {200, 301, 302, 401, 403, 404, 405, 500, 503}
os/22   : recv(256) 결과가 "SSH-" 로 시작           ← 운영 미도달
os/5985 : HTTP 2xx OR status ∈ {200, 401, 403, 405, 503}   ← 운영 미도달
os/5986 : 동상 (https)                              ← 운영 미도달
os(실제): 검사 없음 — TCP 연결 성공이 곧 통과
```

### G. Retry 조건

```
probe_redfish : payload is None (URLError / socket.timeout / SSLError) 일 때만.
                HTTP 응답(status 존재)이면 retry 하지 않는다.
                최대 1회, 간격 1초.  (precheck_bundle.py:273, :310-314)
probe_esxi    : 없음
probe_os      : 없음
tcp_check     : 없음 (주소군 순회는 retry 아님)
```

### H. Final PASS 조건

```jinja
_precheck_ok =
      reachable          | default(false) | bool
  and port_open          | default(false) | bool
  and protocol_supported | default(false) | bool
  and (failure_stage is none or failure_stage | default('') == '')
```
`common/tasks/precheck/run_precheck.yml:48-54`. **auth_success 는 포함되지 않는다.**

게이트: `redfish-gather/site.yml:56` / `esxi-gather/site.yml:61` — `when: not (_precheck_ok | bool)` → `fail`.

### I. 대표 Case 최종 JSON

| Case | 형태 | 위치 |
|---|---|---|
| 정상 | A | §11-1 |
| 도달 실패 | B | §11-2 |
| 포트 실패 | B' | §11-3 |
| 프로토콜 실패 | B'' | §11-4 |
| 인증 미수행 | **모든 precheck 결과가 이 상태다** (`auth_success: null`) — §11-2/11-3/11-4 전부 해당 | — |
| 인증 실패 | C (`auth_success` 는 `false` 가 아니라 **`null`**) | §11-5 |
| 예외 발생 | E(diagnosis=null) / F(fallback) | §11-7 / §11-8 |

**"인증 실패 시 `auth_success=false`" 인 envelope 은 현재 구조에서 생성되지 않는다.**
`false` 가 나오는 유일한 경로는 OS 포트 감지 실패(§11-6)이며, 그 경우는 인증을 시도조차 하지 않는다.
근거: §7-3.

---

## 20. Source Evidence Index

### 20-1. 파일별 역할

> 줄 수는 `wc -l` 실측값 (2026-08-10). 파일 마지막 줄 번호와 1 차이가 날 수 있다.

| 파일 | 줄 수 | 본 분석에서의 역할 |
|---|---|---|
| `common/library/precheck_bundle.py` | 564 | 진단 본체 (Stage 1~4) |
| `common/tasks/precheck/run_precheck.yml` | 66 | 모듈 호출 + PASS 판정 + `_diagnosis` 생성 |
| `filter_plugins/diagnosis_mapper.py` | 77 | `build_diagnosis` — 모듈 결과 → diagnosis 7키 |
| `redfish-gather/site.yml` | 272 | redfish 오케스트레이션 + 게이트 + 메시지 |
| `esxi-gather/site.yml` | 268 | esxi 오케스트레이션 |
| `os-gather/site.yml` | 569 | OS 4-Play (포트감지 / 실패출력 / linux / windows) |
| `common/tasks/normalize/build_output.yml` | 63 | 성공 envelope 조립 |
| `common/tasks/normalize/build_failed_output.yml` | 97 | 실패 envelope 조립 |
| `common/tasks/normalize/build_sections.yml` | 43 | 섹션 status |
| `common/tasks/normalize/build_status.yml` | 66 | overall status |
| `common/tasks/normalize/build_errors.yml` | 47 | errors 정규화 |
| `common/tasks/normalize/build_meta.yml` | 25 | meta |
| `common/tasks/normalize/init_fragments.yml` | — | 누적 변수 초기화 |
| `redfish-gather/tasks/detect_vendor.yml` | 77 | 무인증 probe → vendor |
| `redfish-gather/tasks/collect_standard.yml` | 82 | 계정 순차 시도 |
| `redfish-gather/tasks/try_one_account.yml` | 88 | 계정 1개 시도 + 5초 backoff |
| `redfish-gather/library/redfish_gather.py` | 5,082 | 수집 본체 (status 산출 `:4422-4450`) |
| `esxi-gather/tasks/try_credentials.yml` | 47 | esxi 계정 순차 |
| `os-gather/tasks/try_one_credential.yml` | 88 | OS 계정 1개 시도 |
| `os-gather/tasks/normalize/build_output.yml` | 42 | OS 전용 build_* 체인 진입점 |
| `callback_plugins/json_only.py` | 157 | OUTPUT 태스크만 stdout JSON |
| `Jenkinsfile_portal` | 355 | Callback stage (포털 POST) |

### 20-2. 핵심 판단별 근거 라인

| 판단 | 근거 |
|---|---|
| Stage 1·2 가 한 함수 | `precheck_bundle.py:397-414`, `:485-509` |
| reachable / port_open 구분 기준 | `precheck_bundle.py:410-412` |
| ICMP 미사용 | `precheck_bundle.py:109-142` |
| 채널 포트 목록 | `precheck_bundle.py:95-99` |
| redfish 허용 status | `precheck_bundle.py:299-307` |
| esxi 허용 status | `precheck_bundle.py:366-371` |
| os 허용 status | `precheck_bundle.py:336-344` |
| SSH 배너 검사 | `precheck_bundle.py:236-240` |
| retry 조건·횟수·간격 | `precheck_bundle.py:273, 310-314` |
| TLS 완화 | `precheck_bundle.py:145-164` |
| 헤더 최소화 | `precheck_bundle.py:190` |
| Stage 4 조건 | `precheck_bundle.py:546-548` |
| Stage 4 운영 미실행 | `run_precheck.yml:38-39` + `_precheck_username` 정의처 0건 |
| PASS 조건식 | `run_precheck.yml:48-54` |
| diagnosis 7키 생성 | `diagnosis_mapper.py:60-68` |
| detail 소실 | `diagnosis_mapper.py:35-42` + `build_failed_output.yml:49` (`_fail_error_detail` 정의처 0건) |
| auth_success 덮어쓰기 | `redfish site.yml:191-206`, `esxi site.yml:194-210` |
| 실패 시 auth_success=null | `redfish site.yml:97-113`(fail) → `:226-248`(rescue) → `build_failed_output.yml:79` |
| OS 진단 하드코딩 | `os site.yml:158-166`, `:277-295`, `:471-489` |
| OS 포트 감지 | `os site.yml:40-81` |
| overall status 규칙 | `build_status.yml:51-66` |
| 섹션 status 규칙 | `build_sections.yml:20-43` |
| hostname_source 추가 | `build_output.yml:32-43, 55-58` |
| fallback envelope | `redfish site.yml:256-272`, `esxi:250-268`, `os:359-377, 551-569` |
| OUTPUT 완전일치 | `json_only.py:49, 108` |
| 포털 전달 형태 | `Jenkinsfile_portal:266-272, 290-298` |

### 20-3. 검증 스윕 (§26 요청 항목 실행 결과)

`failure_stage` / `failure_reason` / `reachable` / `port_open` / `protocol_supported` /
`auth_success` / `diagnosis` / `timeout` / `refused` / `ConnectionRefusedError` /
`socket.timeout` / `HTTPError` / `401` / `403` / `404` / `405` / `406` / `503` / `retry` /
`wait_for` / `5986` / `5985` / `22` / `443` / `Redfish` / `wsman` / `SSH-` / `/sdk`
전부 저장소 검색 수행. 1차 조사에서 놓쳤다가 스윕에서 추가로 발견해 본문에 반영한 항목:

1. `os-gather/site.yml:163` 의 `failure_stage: "port"` — precheck 외 두 번째 `port` 생성처 (§16-A)
2. `fallback` failure_stage — 4개 site.yml always 블록 (§11-8)
3. `_fail_error_detail` 정의처 0건 → `errors[].detail` 항상 null (§1-2 #4, §18 D-1)
4. `_precheck_result` 소비처 0건 (§17-J)
5. OS 인증 실패 시 `diagnosis` 필드 자체가 `null` (§11-7, §16-E)
6. esxi 가 404·500 을 허용하고 redfish 는 406 을 허용하는 비대칭 (§17-G)
