# Precheck Guard First

> 본 수집 전에 도달성·프로토콜을 확인하고, 실패 지점을 `diagnosis` 에 남긴다.
> 목적은 단순 alive 판정이 아니라 TCP·프로토콜·인증·수집 실패를 **구분**하는 것이다.
> 도달성은 **관리 TCP 응답 OR ICMP Echo 응답** 이다 (2026-09-03 — ICMP 는 Gate 가 아니다).

## 적용 대상

- `common/library/precheck_bundle.py`
- `os-gather/`, `esxi-gather/`, `redfish-gather/` 의 entry tasks (precheck 호출)
- `classify-precheck-layer` skill 호출

## 현재 관찰된 현실

`common/library/precheck_bundle.py` 실측 (2026-09-03).

- **ICMP 는 TCP 뒤에 붙는 보조 근거다.** 2026-09-03 사용자 지시로 도달성이
  "관리 TCP 응답 OR ICMP Echo 응답" 이 됐다 (`_resolve_reachability`). 종전에는 ICMP 구현
  자체가 없었고, 그 결정의 이유("ICMP 로 판정하면 정상 장비를 죽은 것으로 오판한다")는
  **호출 순서**로 그대로 보존된다 — TCP 가 응답하면 ICMP 는 호출조차 되지 않는다.
  구현은 `ping` 명령 1회(stdlib subprocess)다. raw socket 은 root 권한이 필요하고 비특권
  대안(SOCK_DGRAM+IPPROTO_ICMP)은 커널 `net.ipv4.ping_group_range` 에 좌우돼 에이전트마다
  갈리기 때문이다. `ping` 부재/권한 부족이면 "근거 없음" 으로 떨어져 판정이 종전과 같아진다.
- `reachable` 과 `port_open` 은 **한 번의 TCP 연결 순회로 함께 판정**된다 (`_check_ports`).
  단계가 둘로 나뉘어 순차 실행되는 게 아니다. ICMP 는 그 순회가 **전부 무응답으로 끝났을
  때만** 1회 소비된다 (성공 경로·RST 경로의 예산 증가 0).
- **인증 단계는 운영에서 실행되지 않는다.** `precheck_bundle.py:1399-1410` 이 측정 결과를
  기록해 뒀다 — 어떤 채널도 precheck 에 자격증명을 넘기지 않는다. Redfish 는 이 시점에
  제조사가 미확정이라 금고를 못 열고, 억지로 인증하면 본 수집 전에 실패 시도가 쌓여
  **계정 잠금 위험**이 커진다.
- 실패 지점은 `diagnosis` 의 `failure_stage` / `failure_code` 로 나온다.

## 목표 규칙

### R1. 판정 순서와 각 판정의 의미

- **Default**: 아래 순서로 판정한다. 앞 단계가 실패하면 뒤는 시도하지 않는다.

  | 판정 | 실제로 하는 일 | 실패 시 `failure_stage` |
  |---|---|---|
  | `reachable` + `port_open` | 채널 기본 포트를 TCP connect. 첫 성공에서 중단. RST 를 받으면 "살아 있고 포트가 닫힘". **전 포트 무응답이면 ICMP Echo 1회** | `reachable` / `port` |
  | `protocol_supported` | redfish=ServiceRoot GET 상태코드, os=SSH 배너 또는 무인증 WS-Man Identify, esxi=vSphere 응답 | `protocol` |
  | `auth_success` | redfish 전용이며 자격증명이 넘어온 경우만. **운영 경로에서는 실행되지 않는다** | `auth` |

  기본 포트 — redfish `[443]`, esxi `[443]`, os `[5986, 5985, 22]`. ICMP 도입으로 포트 후보를
  바꾸지 않았다.

  도달성 판정표 (`_resolve_reachability` 정본):

  | 관측 | `reachable` | `failure_stage` | `failure_code` |
  |---|---|---|---|
  | TCP 연결 성공 | true | — | `null` |
  | TCP 거부(RST) | true | `port` | `TCP_CONNECTION_REFUSED` |
  | TCP 무응답 + ICMP 응답 | true | `port` | `TCP_CONNECT_FAILED` |
  | TCP 무응답 + ICMP 무응답 | false | `reachable` | `TARGET_UNREACHABLE` |
  | 주소 해석 실패 | false | `reachable` | `DNS_RESOLUTION_FAILED` |

- **Allowed**: ICMP Echo 를 **TCP 뒤의 보조 근거로** 쓰는 것 (2026-09-03 사용자 지시).
  `icmp_probe=false` 로 끄면 종전(TCP 전용) 판정으로 되돌아간다.
- **Forbidden**: ICMP 를 **앞단 Gate 로** 만드는 것 — TCP 보다 먼저 보거나, ICMP 무응답만으로
  reachable 을 실패시키는 것. 관리망에서 ICMP 가 막혀 있어도 BMC 는 443 으로 답한다.
  ICMP 를 관문으로 쓰면 정상 장비를 죽은 것으로 오판한다.
- **Forbidden**: `ICMP_CONNECT_FAILED` 같은 ICMP 전용 `failure_code` / `failure_stage` 신설.
  ICMP 는 도달 근거를 더할 뿐 실패를 만들지 않는다.
- **Forbidden**: IPAM / ARP 기반 presence probe 추가, ICMP 를 포트마다 반복 전송(예산 증가).
- **Forbidden**: timeout 만 보고 "IP 미사용" 으로 단정, Connection Refused 만 보고
  "장비가 직접 응답했다" 고 단정. `TARGET_UNREACHABLE` 도 "장비 다운" 확정이 아니라
  "우리가 쓴 probe(TCP·ICMP)로 응답을 못 봤다" 는 관측이다.
- **Why**: `CLAUDE.md` §7 이 요구하는 계약이다. ICMP 를 금지했던 이유는 "핑으로 **판정**하면
  안 된다" 였지 "핑을 보면 안 된다" 가 아니었다. OR 조건 + TCP 우선 호출이 그 이유를 그대로
  지키면서, 반대 방향 오판(방화벽이 관리 포트 TCP 를 DROP 하는 구간에서 살아 있는 장비를
  `reachable` 실패로 떨어뜨리던 것)을 없앤다.
  근거 ADR: `docs/ai/decisions/ADR-2026-09-03-icmp-or-reachability.md`

### R2. OS 채널은 후보 포트를 끝까지 훑는다

- **Default**: OS 는 `5986 → 5985 → 22` 순으로 각 포트마다 TCP 연결 후 **그 포트에 맞는
  프로토콜까지 확인**한다. TCP 는 열렸는데 프로토콜이 안 맞으면 실격시키고 다음 후보로 넘어간다.
- **Why**: 다른 서비스가 5985 를 쓰고 있는 환경에서 WinRM 으로 오판하지 않기 위해서다.
- 확인된 포트로 OS 종류를 정한다 — 22=linux, 5985=windows(http), 5986=windows(https).

### R3. Redfish 자격증명은 축이 둘이다

- **Default**: precheck 뒤 순서는 `detect_vendor` → 자격증명 해석 → vault 적재 → adapter 선택.
  자격증명 해석이 adapter 선택보다 **앞**이다 (`redfish-gather/site.yml:70-83`).
  경로는 두 축으로 나뉜다.

  | 구분 | 경로 | 축 |
  |---|---|---|
  | 표준 수집 계정 | `vault/common/redfish/standard.yml` | **전역 1벌.** location 도 vendor 도 보지 않는다 |
  | 복구 계정 | `vault/<loc>/redfish/<vendor>.yml` | location × vendor |

- **Allowed**: vendor 미식별(`vendor_unresolved`)이어도 **표준 vault 는 연다.** 복구 경로만
  None 이 된다. site.yml 의 중단 게이트가 이 사유를 명시적으로 통과시킨다.
- **Forbidden**: 평면 경로(`vault/<loc>/redfish/<vendor>.yml`, `vault/<loc>/os/linux.yml` 등) 사용.
  2026-08-12 에 삭제됐다. 교차 location / 교차 vendor fallback 도 없다.

### R4. 실패해도 봉투는 나온다

- **Default**: 어디서 막히든 13필드 envelope 를 돌려준다. 막힌 지점은 `failure_stage` 로,
  사용자 문장은 `failure_reason` 으로 구분된다.
  - 프로토콜 실패 → `status: failed`, 전 섹션 `failed`
  - 자격증명 실패 → `status: failed`, `failure_stage: auth`
  - 일부 섹션만 실패 → `status: partial`, 성공 섹션 데이터는 유지
- **Forbidden**: 일부 실패로 전체 abort. 호출자가 부분 결과도 못 받는다.

### R5. Validation Layer 분류 (classify-precheck-layer skill)

새 검증을 추가할 때 어디서 차단할지 결정:

| 검증 종류 | 위치 |
|---|---|
| 입력 형식 (JSON 파싱 / IP 형식) | Jenkins Stage 1 (Validate) |
| 호스트 도달성 | precheck TCP 판정 (reachable/port_open) |
| 프로토콜 응답 | precheck protocol 판정 |
| 자격증명 | 본 수집의 자격증명 시도 (precheck 인증 단계는 운영 미실행) |
| 데이터 형식 (envelope schema) | Jenkins Stage 3 (Validate Schema) |
| 비즈니스 규칙 (vendor-specific) | adapter YAML capabilities |

각 검증이 적절한 layer에서 차단 — 늦은 차단은 시간 낭비, 이른 차단은 graceful degradation 무력화.

### R6. Vault 자동 반영 단서 3개 (cycle 2026-05-06-post M-C 학습 형식화)

vault 파일 변경 시 다음 ansible 실행에서 자동 반영 보장. 의심 시 다음 3 단서 검증:

- **단서 1: include_vars cacheable 옵션 부재**
  - **Default**: `redfish-gather/tasks/load_vault.yml` 의 `include_vars` 호출에 `cacheable: yes` 옵션 **금지**
  - **검증 명령**: `grep -rn 'cacheable' redfish-gather/tasks/load_vault.yml` 0 결과
  - **Why**: `cacheable: yes` 시 fact_cache (Redis) 에 host facts 로 저장 → 다음 run 에서도 stale vault 사용 위험
- **단서 2: set_fact host facts 미등록**
  - **Default**: `_rf_accounts` / `_rf_vault_data` 변수는 task scope 만. host facts (`ansible_facts.*`) 또는 `cacheable: yes` 등록 **금지**
  - **검증 명령**: `grep -rn 'cacheable' redfish-gather/tasks/load_vault.yml common/tasks/normalize/` 0 결과
  - **Why**: host facts 등록 시 fact_cache 영향 — vault 변경 후에도 다음 run 에서 stale 가능
- **단서 3: ansible-vault decrypt 캐시 부재**
  - **Default**: `ansible.cfg` 또는 환경변수에 vault decrypt 결과 캐시 옵션 부재 (Ansible default — decrypt 매 run 수행)
  - **검증 명령**: `grep -rn 'vault_password_file\|vault_identity\|VAULT_PASSWORD_FILE' ansible.cfg` — vault password file 만 있어야 함 (decrypt 캐시 옵션 없음)
  - **Why**: Ansible 은 vault decrypt 결과 캐시 안 함 (default) — vault password file 만 있고 decrypt 결과 캐시 옵션 없으면 매 run 새로 decrypt
- **Forbidden**:
  - `cacheable: yes` 옵션 추가 (vault 자동 반영 무효화)
  - host facts 영역에 `_rf_accounts` / `_rf_vault_data` 등록
  - vault decrypt 캐시 옵션 도입 (사용자 명시 승인 외)
- **Why**: M-C 학습 (cycle 2026-05-06) — 사용자 의심 "vault 변경이 자동 반영되는지" 발생 → 3 단서 (cacheable 0건 / fact_caching 0건 / vault decrypt 캐시 0건) 검증 후 자동 반영 보장 확인. 향후 의심 재발 시 본 R6 lookup 로 1턴에 검증
- **재검토**: vault 자동 반영 자동 검증 hook 도입 시 advisory → blocking 격상

## 금지 패턴

- ICMP 를 앞단 Gate 로 만들기 / ICMP 무응답만으로 실패 / ICMP 전용 code 신설 — R1
- IPAM / ARP presence probe 추가 — R1
- timeout 만 보고 IP 미사용 단정 / OS 후보 포트를 프로토콜 확인 없이 채택 — R1, R2
- 삭제된 평면 vault 경로 사용 — R3
- 일부 실패 시 전체 abort — R4
- 검증을 잘못된 layer에 배치 — R5
- vault include_vars cacheable / host facts 등록 / decrypt 캐시 도입 — R6

## 리뷰 포인트

- [ ] precheck 판정 순서 (TCP 먼저, ICMP 는 TCP 전멸 시 1회) 와 OR 판정표 준수
- [ ] 각 단계 실패 시 diagnosis.details 기록
- [ ] Redfish 표준 vault 는 전역, 복구만 loc×vendor
- [ ] graceful degradation 설계
- [ ] 새 검증의 layer 분류 (R5)
- [ ] vault 자동 반영 3 단서 (cacheable 0 / fact_caching 0 / decrypt 캐시 0) — R6

## 관련

- rule: `10-gather-core`, `12-adapter-vendor-boundary`
- skill: `debug-precheck-failure`, `classify-precheck-layer`, `rotate-vault`
- agent: `precheck-engineer`
- 정본: `docs/contract/04-failure-and-diagnosis.md`, `docs/operate/05-vault.md`
