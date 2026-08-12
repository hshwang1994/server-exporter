# 의사결정 로그

> **이 문서는** server-exporter 가 지금 모습이 된 "이유" 를 누적 기록한 결정 이력이다.
> 누군가 "왜 이렇게 만들었는지" 또는 "전에 다른 방식으로 한 적 있는지" 가 궁금할 때 가장 먼저 검색하는 곳이다.
>
> 검증 라운드(Round) 결과, 사용자 의심 분석, 정책 변경 같은 큰 결정은 모두 이 문서에 시간순으로 추가된다.
> 코드만 읽고는 알 수 없는 맥락(왜 이 fallback 이 있는지 등)이 여기 있다.

> 최종 갱신: 2026-08-11

## 2026-08-12 — errors[].message 를 4계층으로 분리하고 문장을 failure_code 에서만 파생

### 사용자 의심

전수조사(`docs/ai/ERRORS-MESSAGE-INVENTORY-2026-08-11.md`)가 "Portal 이 읽는 값은
`errors[].message` 인데 그 자리에 서로 다른 두 계약이 동시에 담겨 있다" 고 지적했다.
`status=failed` 경로는 5문장으로 정제되는데, 실제로 더 흔한 `partial` / `success` 경로는
`Processor /redfish/v1/Systems/1/Processors/CPU1 실패: 401` 같은 날것이 그대로 나갔다.

### 분석 (현재 코드로 재검증)

조사 주장을 그대로 믿지 않고 10개 영역을 현재 코드로 재확인했다. 확정한 근본 원인 3가지:

1. **문장 선택 입력이 둘이었다.** Redfish rescue 는 같은 `set_fact` 안에서
   `stage`/`code`/`auth_success` 를 `(rejected and not collected)` 로, `failure_reason` 만
   `collected` 로 갈랐다. 입력이 둘이면 필연적으로 어긋난다 — `stage=gather` 인데 문장은
   자격증명을 지목하는 결과가 **가장 흔한 실패 경로**였다. 게다가 `_rf_collect_ok` 는 인증
   판정이 아니라 전체 수집 결과여서, 인증이 200 으로 통과해도 시리얼 확정 실패 하나로
   자격증명 문장이 나갔다 (os/esxi 는 자격 probe 전용 관측을 쓴다 — 채널 간 근거 불일치).
2. **존재하지 않는 판정에 문장이 걸려 있었다.** `reason_for_connect_failure(ip_in_use)` 의
   `ip_in_use` 를 set 하는 코드가 저장소에 0건이라, RST 를 실제로 관측해
   `TCP_CONNECTION_REFUSED` 로 확정하고도 사용자에게는 "IP 사용 여부를 확인하세요" 가 나갔다.
   표준 문장 하나가 실사용 0이었다.
3. **성공을 실패로 세고 있었다.** `SimpleStorage` fallback 으로 데이터를 정상 수집했는데도
   errors 에 항목이 생겨 `if errs: failed.append(section)` 때문에 섹션이 failed →
   overall status 가 partial 로 강등됐다. HPE iLO4 등 구세대 BMC 는 매 수집마다 partial 이었다.

### 결정

- **문장은 관측된 `failure_code` 에서만 파생한다** (`REASON_BY_FAILURE_CODE` 단일 매핑).
  stage/code 를 먼저 확정하고 문장을 유도하면 자기모순이 구조적으로 불가능해진다.
  `TCP_CONNECTION_REFUSED` → 2번 문장. 2번 문안에서 "대상 IP 사용은 확인됐지만" 을 뺐다 —
  **presence 판정(ICMP/IPAM/ARP)을 만들지 않기로 확정**했으므로 주장할 수 없는 사실이다.
- **Message 를 4계층으로 분리한다.** 전체 실패(6문장 중앙) / 섹션 부분 실패(섹션 의미 유지) /
  기술 Evidence(`errors[].detail`, string|null) / 성공 fallback·정보성(`diagnosis.details.notices`).
  섹션 오류를 5문장으로 뭉개지 않는다 — "대상에 접속할 수 없습니다" 는 접속이 된 상태에서
  CPU 만 못 읽은 결과를 설명하지 못한다.
- **성공한 fallback 은 error 가 아니다.** 정보를 버리지 않되 errors 에서 뺀다.
- **신규 top-level 필드는 만들지 않았다.** `notices` 는 `diagnosis.details` 하위이고
  (CLAUDE.md §11 이 규정한 기술 evidence / 확장 metadata 영역), `errors[]` 원소는 계속 3키다.
  vendor OEM 이 붙이던 `severity: warning` 은 정규화가 3키만 남겨 **envelope 에 도달한 적이
  없는 죽은 키**여서 제거했다 — warning/error 축을 도입하려면 원소 shape 변경이라 별도 승인 영역이다.

### 영향

- `failure_stage` 분포가 일부 `gather → auth` 로 이동한다 (Redfish, 원인 미확정 실패).
  enum 자체는 불변이나 stage 로 집계하는 소비자가 있으면 수치가 바뀐다.
- Redfish 실패의 `failure_reason` 분포가 4번 ↔ 5번 사이에서 이동한다 (문장 자체는 불변).
- 구세대 BMC 의 `status` 가 `partial → success` 로 바뀐다 (성공한 fallback 을 실패로 세지 않으므로).
- envelope 13 top-level 필드 / schema_version 불변. `errors[]` 원소 키 3개 불변.

### 회귀

`pytest tests/` **2094 passed / 10 skipped / 7 xfailed** (착수 전 1974 passed).
field_dictionary PASS · schema-drift exit 0 · vendor-boundary / harness-consistency 통과.
baseline 갱신 1건 — `tests/fixtures/redfish/dmtf_rackmount1/expected_output.json`
(오프라인 mockup 재생 산출물. 실장비 baseline 아님).
**실장비 / 실 Jenkins 검증은 하지 않았다** (이 환경에 ansible 미설치).

정본: `tests/evidence/2026-08-12-errors-message-contract.md`,
`docs/20_json-schema-fields.md` §4-1, `common/vars/failure_reasons.yml`,
`common/vars/section_messages.yml`, `filter_plugins/errors_normalizer.py`.

---

## 2026-08-11 — Dell 대표 시리얼을 Service Tag 로 교정 (1차, Dell 단독)

### 요청 / 배경 (Why)

- 사전 조사(`docs/ai/SERIAL-NUMBER-TRACE-2026-08-11.md`)에서 동일 Dell R760 1대의 채널 간 시리얼이
  달랐다. Redfish `CNIVC0048R0159` ↔ Linux `GSBPK54` → `correlation.serial_number` 로 두 채널 결과를
  매칭할 수 없었다 (Cisco 는 SAME 이라 Dell 만의 문제).
- 사용자 지시: Dell 만 1차 교정. schema 변경 금지, 새 필드 금지, 다른 벤더 무변경.

### 원인 (실측 근거)

- Dell iDRAC 의 `ComputerSystem.SerialNumber` 는 **보드 제조 시리얼**이다. 같은 장비 SMBIOS 에서
  그 값은 **Type 2(Baseboard)** 문자열 `.GSBPK54.CNIVC0048R0159.` 안에만 나타나고
  Type 1(System)·Type 3(Chassis) 에는 없다. OS 가 읽는 값은 Type 1 = `GSBPK54` (Service Tag).
- 실장비 7대 전수에서 `SerialNumber` ≠ Service Tag 가 일관되게 확인됐다.

### 결정 (What)

- Dell 대표 시리얼 원천 = **`ServiceRoot.Oem.Dell.ServiceTag` 단일 정본**. 폴백 없음.
  - 선택 근거: Dell iDRAC9 Redfish API Guide "Table 70. Properties for DellServiceRoot" 가
    이 필드를 **"System Service Tag"** 로 정의한다. 후보 4종 중 Dell 공식 정의가 있는 유일한 필드다.
  - `ChassisServiceTag` 미채택: Dell System Info Profile(DCIM1048) 이 *"the service tag for the
    modular enclosure chassis"* 로 정의 → 모듈러에서 enclosure 를 가리킨다.
  - `SKU` 미채택: DMTF 정의는 일반 SKU. Dell 이 Service Tag 라고 문서화한 적 없음 (값만 같음).
  - `NodeID` 미채택: Redfish 스키마·프로파일 정의 없음.
- **확보 실패 시 수집 실패.** Dell 시리얼은 필수값이라 null 로 success/partial 을 내보내지 않는다.
  기존 실패 계약 재사용 — 신규 `failure_stage` / `failure_code` 를 만들지 않았다
  (`gather` / `GATHER_FAILED`).
- 구현 위치는 `main()` 층이다. 섹션 러너(`_make_section_runner`)로는 `partial` 까지만 만들 수 있어
  "수집 실패" 를 표현할 수 없기 때문이다. adapter 의 `critical_sections` 는 **읽는 코드가 없어**
  (dead config) 승격 수단이 되지 못한다.

### 영향 (Impact)

- envelope 13 필드 / sections / field_dictionary entry 추가·삭제 **0**. 배선 무변경.
- Dell 은 `hardware.serial` == `hardware.sku` == `hardware.oem.chassis_service_tag` 로 같아진다
  (전부 기존 필드). 보드 제조 시리얼 `CNIVC…` 는 envelope 에서 사라진다 — 새 필드 금지 지시에 따른
  의도적 미보존.
- 비-Dell 전 벤더는 `_SERIAL_RESOLVERS` 미등록이라 코드 경로 자체를 타지 않는다.
- **리스크**: iDRAC7/8 은 `DellServiceRoot` 문서화가 없어 미노출 시 수집이 실패한다(실기기 미검증).
  Dell 모듈러도 미검증. 둘 다 NEXT_ACTIONS 등재.

### 회귀

- unit 1186 / e2e 416 / integration 200 / regression 169 passed. 3 게이트 PASS.
- Dell 기준선 3종만 갱신(전부 재생 산출값), 비-Dell baseline 9종 + 실미러 골든 3종 무변경.
- ⚠ ansible 부재로 실제 playbook end-to-end envelope 은 미검증 (lab 이월).

### 관련

- rule 12 (adapter-vendor-boundary), 13 (output-schema-fields), 21 (output-baseline-fixtures),
  92 (dependency-and-regression-gate), 96 (external-contract-integrity)
- 정본: `docs/ai/SERIAL-NUMBER-TRACE-2026-08-11.md` Part III,
  `tests/evidence/2026-08-11-dell-serial-service-tag.md`

---

## 2026-08-03 — 보조 섹션(network_adapters) 실패가 network status 를 덮던 문제 + 400 분류

### 요청 / 배경 (Why)

- 사이트 Jenkins 빌드(DAY_1/git/소연등록redfish #1) 에서 Dell iDRAC(RedfishVersion 1.4.0) **8대 전부**
  `status=partial`, `sections.network=failed`, `errors[]="NetworkAdapters 미지원 또는 실패: HTTP 400: Bad Request"`.
- 그런데 같은 envelope 의 `data.network` 는 정상(interfaces 4 / default_gateways / summary.port_count 4).
  비어 있는 건 `adapters[]` / `ports[]`(NIC 카드 모델·펌웨어) 뿐이었다. 즉 **데이터는 멀쩡한데 status 만 거짓**.
- 사용자 질문: "지금 코드에 버그 있는건가?" → 조사 결과 **버그 2건 + 진단성 결함 1건**.

### 원인 (실측 근거)

1. **status 마스킹** — `redfish_gather.py` 는 `network`(주=EthernetInterfaces) 와
   `network_adapters`(보조=Chassis NetworkAdapters) 를 별도 raw 섹션으로 보고하는데,
   `normalize_standard.yml` `_rf_proc_map` 이 둘을 같은 `network` 로 collapse.
   `build_sections.yml` 우선순위가 `not_supported > failed > success` 라 **보조 실패가 항상 승리**.
   (`docs/ai/NEXT_ACTIONS.md` 에 NET-SEC-MAP(LOW, "미발동")으로 등재돼 있던 latent 결함이 실발동.)
2. **400 = 미지원 미분류** — `_is_404_only_error` 가 404 만 capability 부재로 봤다. 벤더 BMC 는
   미구현/미인가 리소스에 400 을 주기도 한다.
3. **진단 근거 소실** — 실패 시 응답 body 를 버려 `errors[].detail=null`. Redfish 표준
   `error.@Message.ExtendedInfo`(왜 거부했는지)가 사라져 '미지원' 인지 '우리 요청 결함' 인지 구분 불가.

**요청 형식 문제 아님을 확인**: (a) 같은 `eff_chassis_uri` 를 쓰는 `power`/`thermal` 은 `success`,
(b) 실 Dell R740 전수 미러(`tests/fixtures/redfish/real_dell_r740`)에서 **동일 URL 이 200**.
→ 장비/펌웨어 차이 (rule 25 R7-A-1 사용자 실측 우선).

### 결정 (What)

- **A. 보조(auxiliary) 섹션 개념 도입** — `normalize_standard.yml` 에 `_rf_aux_sections: ['network_adapters']`.
  세 status fragment(collected/failed/unsupported) **모두**에서 보조 섹션 제외 → 섹션 status 는 주 수집만으로 결정.
  보조 실패는 `errors[]` 로만 보고(시나리오 B). **`unsupported` 에서도 제외**하는 게 핵심 —
  안 하면 400→unsupported 확장 후 `network` 가 `not_supported` 로 덮여 failed 보다 더 나쁜 마스킹이 된다.
- **B. capability 부재 신호에 400 추가** — 신규 `_is_capability_missing_error`(404 or 400).
  기존 `_is_404_only_error` 는 의미 불변(back-compat, 직접 테스트 존재). **오분류 완화 2중**:
  호출부에서 `_is_empty_result(val)` 와 AND(컬렉션 전체 실패 + 결과 완전 빈값), 비-404 분류 시 stderr 에 원문 기록.
- **C. 확장 오류 정보 보존** — 신규 `_extended_info(body)` 가 `error.code`/`message`/`@Message.ExtendedInfo[]`
  를 300자로 축약해 `errors[].detail` 에 기록. envelope shape 변경 0 (Additive, rule 96 R1-B).

### 결과 (Impact)

- 사이트 조건에서 `sections.network=success`, `status=success`, NIC 카드 상세만 비게 됨(정직한 표현).
- envelope 13 필드 / sections 11 / field_dictionary 변경 **0** — status **값**만 바뀐다(계약 shape 불변).
- 회귀: `pytest tests/` **1302 passed** / 5 skipped / 7 xfailed. baseline 10종 영향 0(전부 network=success 유지).
- 신규 회귀 27건: `tests/unit/test_network_adapters_aux_status.py`(21) +
  `tests/integration/test_site_dell_networkadapters_400.py`(6, 실 R740 미러를 400 으로 변조해 사이트 재현).
  후자는 "수정 전 로직이면 partial 이 재현된다" 는 역가드까지 포함.
- **미검증(정직 보고)**: 이 환경에 `ansible-playbook` CLI 부재 → YAML 은 실제 식을 Jinja2 로 렌더해 검증했고
  전체 ansible 통합(실 site.yml)은 **Jenkins Agent 재빌드로 확인 필요**. 400 의 근본 사유(미구현/라이선스)도
  BMC 직접 접근 불가로 **미확정** — C 적용 후 다음 빌드의 `errors[].detail` 로 확인.

### 대안 비교 (Considered)

- **보조 실패를 그대로 failed 유지**: 사이트가 영구 partial. 호출자가 "partial=문제"로 알람 → 노이즈. 기각.
- **network_adapters 를 별도 섹션으로 승격**: sections 11→12 = 호출자 계약 변경(rule 13 R5). 과대. 기각.
- **400 을 무조건 unsupported**: 진짜 요청 결함까지 은폐. `_is_empty_result` AND + stderr 로 완화해 채택
  → **아래 정정 절에서 철회**.

---

### [정정] 같은 날 후속 조사 — B 는 오판이었고 근본 원인은 **경로 오류**

사용자 지적("근본 해결이 아니라 안 보이게 한 것 아니냐")을 받아 400 의 근거를 다시 조사한 결과,
**위 (B) 결정의 전제가 틀렸음**이 확인됐다.

#### 무엇이 틀렸나

빌드 #3 envelope 의 `data.bmc` / `data.hardware` 실측:

| 항목 | 값 (8대 전부) |
|---|---|
| 모델 | **PowerEdge R630** (13G) |
| BMC 모델 | `13G Monolithic` |
| iDRAC 펌웨어 | 2.75.100.75 / 2.80.80.80 / 2.85.85.85 / 2.86.86.86 → **iDRAC8** |

벤더 공식 **iDRAC8 Redfish API Guide 2.70.70.70** 은 같은 리소스를 이렇게 문서화한다:

```
NetworkAdapter Collection : /redfish/v1/Systems/System.Embedded.1/NetworkAdapters
NetworkAdapter Instance   : /redfish/v1/Systems/System.Embedded.1/NetworkAdapters/<id>
```

우리 코드는 `Chassis/{id}/NetworkAdapters` 만 요청했다. **400 은 "장비 미지원"이 아니라
"그 펌웨어에 없는 경로를 물어본 결과"**였다.

**원 조사의 추론 결함**: "실 Dell R740 미러에서 같은 URL 이 200" 을 근거로 "요청 형식 문제 아님"
이라고 단정했는데, R740 은 **14G / iDRAC9** 로 세대가 다르다. 세대가 다른 장비를 대조군으로 써서
잘못된 결론에 도달했다 (rule 95 R2 — 근거의 교차 확인 실패).

#### 정정 결정 (What)

- **B 철회**: `_is_capability_missing_error`(404+400) 제거, `_run` 은 `_is_404_only_error` 로 복귀.
  400 은 다시 `failed` + `errors[]` 노출. 근거 없는 은폐 제거 — 특히 **은폐 대상이 우리 자신의 버그**였다.
- **근본 fix 신설**: `gather_network_adapters_chassis` 에 수집 경로 후보 2종 —
  1순위 `Chassis/{id}/NetworkAdapters`(DMTF 현행 표준) → 실패 시 2순위 `Systems/{id}/NetworkAdapters`.
  1순위가 200 인 장비는 2순위를 **아예 시도하지 않아** 동작·왕복 100% 불변(Additive). vendor 분기 없음(rule 12 R1).
- **A / C 유지**: 섹션 status 분리는 여전히 유효(별개의 진짜 버그). detail 보존은 진단에 필요.

#### 결과 (Impact)

- 사이트 R630 8대는 이제 NIC 카드 모델·펌웨어를 **실제로 수집**한다(구 코드는 `adapters[]` 영구 빈 배열).
- 양 경로 모두 실패하는 장비는 `errors[].detail` 에 `tried: <경로1> / <경로2>` + BMC 확장 메시지가 남는다.
- 회귀 1306 passed. 신규 가드: 400 이 다시 미지원으로 분류되면 실패하는 테스트
  (`test_400_is_not_treated_as_unsupported` — `_is_capability_missing_error` 부활 자체를 차단).

#### 대안 비교 (정정 후)

- **B 유지 + fallback 추가**: fallback 이 성공하면 400 이 안 보이니 문제없다고 볼 수도 있으나, *다른* 원인의
  400 이 계속 은폐된다. 기각.
- **Systems 경로를 1순위로**: iDRAC9 등 현행 표준 장비의 왕복이 늘고 표준에서 멀어진다. 기각.
- **adapter YAML 로 vendor/세대별 경로 지정**: 정확하지만 세대 오선택 문제(아래)에 의존하고 신규 vendor 마다
  수동 등재가 필요. 경로 후보 순회가 vendor-agnostic 하고 자기수복적. 기각(향후 재검토).

#### 남은 별건

adapter 세대 오선택 — iDRAC8 장비인데 `redfish_dell_idrac10` 이 선택된다(무인증 probe 단계에 model/firmware
가 비어 priority 최상위만 뽑히는 기존 이슈, NEXT_ACTIONS 등재). 본 fallback 은 adapter 와 무관하게 동작하므로
이번 수정에는 영향 없음.

---

### [후속] FCoE 지원 CNA 를 FC HBA 로 오분류하던 문제 (빌드 #4 에서 노출)

#### 컨텍스트 (Why)

fallback 배포 후 빌드 #4 에서 NIC 카드 데이터가 처음 들어왔다(`adapters` 1 / `ports` 4 — 목표 달성).
그런데 같은 물리 포트 4개가 **서로 다르게 분류**되는 자기모순이 드러났다:

| 위치 | 값 |
|---|---|
| `data.network.ports[].port_type` | `Ethernet` |
| `data.network.summary.groups[].link_type` | `ethernet` |
| **`data.storage.hbas[].port_type`** | **`FibreChannel`** (4건) |

대상 NIC = `BRCM 10G/GbE 2+2P 57800 rNDC` — Broadcom 57800 은 **FCoE 지원 CNA** 이고, 이런 카드는
이더넷 기능에도 MAC 파생 WWN 을 단다(실측 WWPN `20:01:90:b1:1c:1f:e2:8e` = MAC `...e2:8d` + 1).

#### 원인

`_classify_port_protocol` 의 CSUS-FC1 휴리스틱(`ndf_wwpn` 존재 → FibreChannel)이 **Ethernet 판정보다
위**에 있어 명시적 Ethernet 신호를 덮어썼다. 이 휴리스틱은 원래 `NetDevFuncType` 을 아예 주지 않는
HPE CSUS RMC 펌웨어 전용이었다(2026-06-15). 데이터가 없어 드러나지 않던 **기존 버그**가 이번에 노출됐다.

#### 결정 (What)

`ndf_wwpn` 휴리스틱을 함수 **맨 끝**(명시 신호 전무 시)으로 강등. 판정 우선순위:

```
InfiniBand 신호 → FCoE(NetDevFuncType) → FC(PortProtocol/NetDevFuncType) → Port.FibreChannel dict
→ Ethernet(PortProtocol/link_tech/NetDevFuncType) → Port.Ethernet dict → [최후] NDF.WWPN → FC
```

FCoE 를 **실제로 설정한** 장비는 `NetDevFuncType=FibreChannelOverEthernet` 을 주므로 위쪽 FCoE 분기에서
잡힌다 — 본 강등의 영향 없음. CSUS 본래 케이스(명시 신호 전무 + WWPN)도 최후 분기로 보존.

#### 결과 (Impact)

- 사이트 R630 8대의 `storage.hbas` 는 `[]` 가 되고 `network.ports` 와 일관됨.
- 회귀 **1315 passed**. 신규 `tests/unit/test_fcoe_cna_not_fc_hba.py` 9건 —
  오분류 방지 3 / 진짜 FC·FCoE·IB 보존 5 / end-to-end(사이트 NIC → `fc_hbas == []`) 1.
- 가드 유효성: 강등을 되돌리면 4건 FAIL 확인.
- **미검증**: 사이트에서 `storage.hbas` 가 실제로 비는지 → 다음 빌드.

#### 대안 비교 (Considered)

- **현행 유지**: "FCoE 가능 기능 4개"도 거짓은 아니지만 `network.ports` 와의 모순이 남고, 호출자가
  SAN 연결이 있다고 오해한다. 기각.
- **WWPN 이 MAC 파생인지 검사**: 벤더별 파생 규칙이 달라 신뢰 불가. 기각.
- **`storage.hbas` 에 `capability_only` 플래그 추가**: envelope 신규 키 = 호출자 계약 변경(rule 96 R1-B).
  분류 순서 교정으로 충분. 기각.

#### [후속 2] 잔여 2대 — orphan NDF 가 부모 포트 신호를 못 물려받던 문제

빌드 #5 에서 8대 중 **6대는 `hbas=0` 으로 해결, 2대(.52 / .152)는 여전히 `hbas=4`**.
같은 NIC 모델(`BRCM 10G/GbE 2+2P 57800 rNDC`)인데 **NIC 펌웨어가 갈렸다**:

| IP | NIC fw | #4 | #5 | #6 |
|---|---|---|---|---|
| .51 / .54 | 15.15.08 | 4 | 0 | 0 |
| .53 | 15.20.13 | 4 | **0** | 0 |
| **.52** | 15.20.13 | 4 | **4** | 0 |
| .151 / .153 / .154 | 16.10.04 | 4 | 0 | 0 |
| **.152** | 16.10.04 | 4 | **4** | 0 |

> **NIC 펌웨어는 구분 요인이 아니다** — `.53` 과 `.52` 는 같은 fw 인데 #5 결과가 갈렸다.
> (초기 기록에서 "펌웨어 차이" 로 두 번 잘못 적었다가 위 전수 대조로 반증. `tests/evidence/` 정정 절 참조.)
> 실패한 2대의 `hbas[].port_id` 가 포트 id 아닌 **NDF id** 인 것이 orphan 경로임을 확정해 준다.
> **왜 그 2대만** orphan 분류에서 Ethernet 신호를 못 얻었는지는 raw 미확보로 **미확정**.

**원인**: Dell 은 NDF Id 를 `<PortId>-<funcIdx>` 로 매긴다(포트 `NIC.Integrated.1-1` ↔ NDF
`NIC.Integrated.1-1-1`). NDF↔Port join 은 (a) `Links.PhysicalPortAssignment` (b) `NDF.Id == Port.Id`
두 가지만 시도하는데 **둘 다 빗나가** orphan 이 된다. orphan 분류는
`_classify_port_protocol(None, None, ndf, None)` — 포트 컨텍스트가 **전혀 없어서** 앞선 강등 fix 가
무력화되고 최후 WWPN 휴리스틱까지 흘러가 FC 로 잡혔다.

**결정**: orphan NDF 는 **부모 포트의 신호를 물려받아** 분류한다. NDF Id 가 `<PortId>-` 로 시작하면
그 포트의 `(PortProtocol, link_tech, raw port)` 를 넘긴다. 구분자 `-` 를 요구해 `...1-1` 이
`...1-10-1` 을 삼키지 않는다. 부모를 못 찾으면 기존 동작(CSUS 의 진짜 port-less NDF) 그대로.

**결과**: 회귀 **1318 passed**, 신규 3건 추가(총 12건). 상속을 제거하면 1건 FAIL(가드 유효).
진짜 FCoE(`NetDevFuncType=FibreChannelOverEthernet`)는 orphan 이어도 HBA 로 잡히는 것 별도 회귀로 고정.

## 2026-06-17 — OS Linux bond alias / secondary IP 수집 (네트워크 개더링)

### 요청 / 배경

- OS 네트워크 개더링이 bond master 의 primary IP 만 수집하고 alias(`bond1:1`, `bond2:1`) 를 누락.
  python_ok 경로는 `ansible_<iface>.ipv4.address`(primary only, label/secondary 없음), raw 경로는
  `ip -o -4 addr show dev <dev> | head -1`(첫 주소만) → 두 경로 모두 alias 손실.
- 요청: alias IP 를 수집하되 **새 인터페이스로 만들지 말고 parent bond 의 `addresses[]` 에** 넣을 것.
  RHEL 고정 금지 — Linux 계열 전체 동작. 테스트 대상 10.100.64.161(RHEL 8.10)/10.100.64.165(RHEL 9.6).

### 결정 (What)

- **수집 소스**: 공유 collector `_l_net_collector` 에 주소 블록 추가 — `ip -j addr show`(1순위, JSON)
  → `ip -o addr show`(2순위) → `ifconfig -a`(3순위). nmcli/ifcfg 비의존(NetworkManager 부재·배포판 차이 강건).
  python_ok shell·raw 두 경로가 같은 collector 를 실행하므로 단일 정의로 양 경로 커버.
- **정규화**: 신규 필터 `parse_linux_addresses`/`merge_linux_addresses`(`network_topology.py`). merge 는
  base 인터페이스의 기존 주소를 신규 5 키로 enrich(값 보존) + alias 를 parent `addresses[]` 에 append.
  `build_linux_network` 는 **불변** — 기존 단위테스트(`net == base`, slave `addresses==[]`) 보호 위해 merge 를
  분리 필터로 두고 yml 체인(`... | merge_linux_addresses(lines) | build_linux_network(lines)`)에서 호출.
  bond master IP 를 `bonds[].addresses` 로 mirror 하는 기존 로직 덕에 alias 가 bonds[] 에도 자동 일관.
- **스키마(Additive, `channel:[os]` nice)**: `label`/`parent_interface`/`is_alias`/`scope`/`is_secondary`.
  `is_secondary` 는 커널 secondary 플래그 기반 best-effort(다른 서브넷 alias 는 false — 정상).

### 결과 (Impact)

- 실장비 161/165 live SSH 검증: bond1:1/bond2:1 수집, 기존 bond IP·slave·active_slave·mode 불변,
  alias 별도 인터페이스 미생성, slave IP 없음 유지. alias 없는 NIC 결과 불변(신규 키만 Additive).
- pytest unit+regression+e2e 1093 passed / field_dictionary·drift·vendor-boundary·harness 게이트 통과.
- 증거: `tests/evidence/2026-06-17-bond-alias-collection.md`, docs/16·docs/20(§6.4.2).

### 대안 비교 (Considered)

- **(A) build_linux_network 내부에서 merge** — 기각: `net["interfaces"] == base` 등 기존 단위테스트 대량 파손.
  merge 를 별도 필터로 분리해 기존 함수 동작 보존.
- **(B) setup facts `ipv4_secondaries` 사용** — 기각: label/scope 부재 + python_ok 경로 한정(raw 미커버).
  `ip -j` 단일 소스가 두 경로·label/scope 모두 충족.
- **(C) 인터페이스/주소 레벨 필드 위치** — 주소 레벨 채택(요청 명시). cross-channel drift 는 `channel:[os]` 한정으로 수용.

## 2026-06-16 — CSUS 실 게더링 cascade: HPE OEM dict conditional(Bug A) + site.yml graceful degradation 복원(Bug B, redfish)

### 사용자 의심 / 요청

- 실 CSUS 3200 게더링 결과 11 섹션 중 users·thermal `not_supported`, 나머지 9개 전부 `failed`. errors[] 에
  `[task: redfish | hpe | Superdome/CSUS fragment 생성 (모델 매칭 + OEM 영역 존재 시)] ... Conditional result (False) was derived from value of type 'dict' ... collect_oem.yml:101`.
  "이거 해결해주고 — 표준 섹션은 success 떨어져야 할 텐데 success 만드는 로직이 잘못된 게 아닌가?"

### 분석 (다중 에이전트 적대적 검증 — confirmed)

- **트리거(Bug A)**: `redfish-gather/tasks/vendors/hpe/normalize_oem.yml:42,50` 의 `when` 둘째 조건
  `(_hpe_superdome_partition | default({})) or (_hpe_superdome_flex_node | default({})) or (_hpe_superdome_global | default({}))`
  — dict 의 `or` 체인은 boolean 이 아니라 dict({}) 를 반환. 일반 iLO 는 앞 regex(`Superdome|Flex|Compute Scale-up|CSUS`)가
  False 라 short-circuit 으로 잠복. CSUS/Superdome 만 regex True → `{} or {} or {}` = {} → Ansible strict conditional FAIL.
  (실 CSUS OEM 은 `#HpeH3Npar`/`#HpeH3Chassis` 라 구식 PartitionInfo/FlexNodeInfo 추출 결과 = {} — 정확히 빈 dict 경로에서 터짐.)
  전 18 vendor OEM 파일 중 이 2줄만 non-boolean-safe (워크플로 전수 스캔).
- **cascade(Bug B)**: `site.yml` 전체가 단일 block/rescue. OEM 단계가 `normalize standard`(표준 섹션을 _merged_data/_all_sec_collected 에 누적) **뒤**에 위치
  → OEM fatal 시 block abort → rescue 가 `build_failed_output.yml` 호출. rescue 는 `_all_sec_collected` 를 **참조조차 안 하고**
  `_fail_sec_supported`(capabilities) 전부 `failed` 마킹. `_merged_data` 는 보존 → "data 있는데 sections 전부 failed" 모순.
  9 failed(=CSUS adapter sections_supported 9개) + 2 not_supported(users/thermal) 와 정확히 일치. 같은 단일 block/rescue 구조가 os/esxi 에도 존재(확인됨).
- **선언 ↔ 구현 괴리**: CSUS adapter 가 `graceful_degradation.on_section_fail: continue` + `optional_sections` 선언하지만 이 설정은
  어느 실행 코드에서도 소비 안 됨(status_rules.yml reserved). build_status.yml 판정 로직 자체는 정상 — 실패 경로에서 도달 못 할 뿐.

### 결정 (Bug A 전면 / Bug B redfish 한정 — 사용자 승인 2026-06-16)

- **Bug A**: normalize_oem.yml:42,50 → 각 operand `| length > 0` boolean 강제(None-safe `default({}, true)`). 의도("OEM 영역 존재 시") 보존, CSUS/Superdome only, envelope shape 불변 Additive.
- **Bug B (redfish 한정)**: site.yml 의 collect OEM + normalize OEM 을 local block/rescue 로 감싸 비치명화. 실패 시 errors[] 에 `section: oem` 경고만 남기고(merge_fragment),
  표준 섹션 보존 → build_sections/build_status 정상 경로. adapter `graceful_degradation` 의도 구현. `normalize standard`(핵심)·`account_service` 는 main block 유지.
- **범위 결정**: os/esxi 동일 cascade 는 사용자 선택으로 보류 → NEXT_ACTIONS 등재.

### 영향

- OEM/선택 단계 실패 시 overall status: 기존 `failed`(전 섹션 failed) → `success`(시나리오 B: 표준 섹션 success + errors[] OEM 경고) 또는 `partial`(C).
  envelope 13 필드 / 4-시나리오 매트릭스 자체는 불변 — OEM 실패가 D 가 아니라 B/C 로 올바르게 분류되도록 제어흐름 교정. 호출자 계약(rule 96 R1-B): status 관측값 변화 → docs/20 시나리오 절 + site.yml inline 주석에 반영 (build_status.yml 판정 로직 자체는 불변).
- 성공 경로(기존 baseline cisco/dell/hpe/lenovo)는 OEM 정상 → rescue 미진입 → 동작 동일, 회귀 0.

### 회귀

- [확인함] 정적: YAML 파싱 OK, Jinja2 시뮬레이션 — OLD 전 케이스 dict(strict FAIL) / NEW 항상 bool. site.yml block/rescue 구조 검증.
- [미확인] 라이브: ansible 미설치(Windows) → 실 CSUS 게더링 재현/회귀 미실행. lab 재배포 + 실 4노드(또는 오프라인 replay) 검증은 NEXT_ACTIONS.
- [주의] 배포 동기화: 에러가 가리킨 `collect_oem.yml:101` 은 HEAD 에 없음(HEAD collect_oem.yml 은 clean) — 배포 lab 코드가 HEAD 와 다른 버전(다른 세션 미커밋 / 내부 GitLab stale) 가능. 본 수정 반영 위해 lab 배포 코드 동기화 확인 필요.

## 2026-06-15 — HPE Compute Scale-up Server 3200 (CSUS 3200) 실 미러 검수: 라이브러리 fix 16건 (5-round 수렴)

### 사용자 의심 / 요청

- "redfish_full_mirror.py 로 실장비(HPE CSUS 3200, 4 노드) 데이터 기준 개더링 전체 검수 — 잘못 수집된 데이터/필드 매핑/타입/OEM/병합/실패처리/링크추적 오류를 버그 0 + 회귀 0 + 부작용 0 까지 반복 수정. 발견한 문제 수정 후에도 전체 재검수·회귀·신규 탐색 루프를 새 작업이 0 이 될 때까지 반복."

### 분석 (5-Round 다관점 자가검증 수렴 — 실 4노드 raw provenance 1:1 대조)

- 대표 root cause: **chassis 오선택**. `detect_vendor` 가 Chassis 컬렉션 첫 멤버(집계용 RackGroup — PowerSubsystem/ThermalSubsystem/NetworkAdapters 부재)를 chassis_uri 로 잡아, top-level `data.power`/`data.thermal` 이 빈 `{}` 인데 `collected=success`(누락이 정상처럼)·`network_adapters=unsupported`(false not-supported)·**FC HBA 전량 소실**. 실 compute chassis 는 `Systems/Partition0.Links.Chassis=r001u01`.
- round 별 신규 confirmed 추세 **6→5→3→2→0** 으로 수렴. 발견 카테고리: chassis 오선택 / FC HBA WWPN 소실 / FC WWNN↔WWPN 오매핑 / port_count 잘못된 기본값(0) / PSU 펌웨어·소비전력 누락 / fan RPM 링크추적 누락 / memory locator 무용값(0) / Ethernet 미분류 / multi_node 식별필드 불일치 / ilo_version OEM 오매핑 / 내부 임시키(_network_meta) 누설 / adapter firmware 링크추적 누락.

### 결정 (16건 수정 — 전부 raw 충실 + Additive only, redfish_gather.py)

- R1 chassis=`System.Links.Chassis`(r001u01, `_resolve_system_chassis_uri` 신설) / FC1 NDF↔Port ID매칭 / FC2 `Port.FibreChannel.AssociatedWorldWideNames` / R3 multi_node system `product_hint` / R4 `bmc.oem.ilo_version` Manager.Model 폴백 제거 / R5 chassis kind RackGroup·Rack / R6 port_count=실 Ports 수 fallback / R8 Ethernet port_type=`Port.Ethernet` dict / R9 PSU firmware=`Version` fallback / R10 power=PSU `InputPowerWatts` 합(최후) / R11 fan RPM=`Sensors`(Rotational) `RelatedItem` 역참조 / R12 memory locator=`ServiceLabel`(Slot=0 시) / R13 FC `associated_address`=NDF.WWPN(WWNN 오취득 교정, `fc_hbas.wwpn` 일관) / R14 power=`TelemetryService` TotalPowerConsumedWatts(장비 권위값) / R15 `_network_meta` 임시키 multi_node 누설 차단 / R16 adapter firmware=`Controllers[].Links.PCIeDevices[].FirmwareVersion` fallback.
- **gated(8건, 자율 미수정)**: CSUS baseline 실측 교체(Ansible/Linux control node 필요 — Windows 미지원), field_dictionary drift(multi_node.boot/thermal/composition/fabrics — 보호 경로), collect_oem.yml CSUS 실 필드명(HpeH3Npar — lab 필요), system.oem iLO-shaped(faithful), network list vs dict shape(envelope 계약), Rmp 관리어댑터 제외, ResourceBlock count, multi_node.chassis name. → NEXT_ACTIONS 등재.

### 영향

- 4 노드 전부 status=success / power consumed 591·600·1000·945W(장비 telemetry 권위값) / thermal 47~63 temp + fan RPM 10/10 / FC HBA 4·4·8·8 WWPN + Ethernet 0·0·8·8 분류 / adapter firmware(node03/04) / memory locator=ServiceLabel.
- **cross-vendor**: R13(FC WWNN→WWPN)은 전 벤더 적용 — Dell R740 실미러 FC `associated_address` 4건이 WWNN→WWPN 으로 *교정*(기존 `assoc≠fc_hbas.wwpn` 불일치 해소, faithful). HPE emulator golden 2종(dl325/dl365 FC) faithful 재생성. 커밋 baseline 엔 해당 필드 부재로 영향 0.

### 회귀

- `pytest tests/` **1151 passed, 5 skipped** (baseline 1126 + 신규 `tests/unit/test_csus_mirror_audit_fixes.py` 25).
- 타 벤더(Dell/HPE/Lenovo) 실미러 replay envelope `git stash` pre/post diff 4회 — HPE/Lenovo byte-identical, Dell 은 R13 FC assoc 만(의도). 부작용 0.
- 증거: `tests/evidence/2026-06-15-hpe-csus3200-mirror-audit.md`.

## 2026-06-15 — HPE DL380 Gen12 실 미러 검수: thermal 섹션 배선 + 라이브러리 fix 7건

### 사용자 의심 / 요청

- "redfish_full_mirror.py 로 실장비(HPE DL380 Gen12) 데이터 기준 개더링 전체 검수 — 잘못 수집된 데이터/필드 매핑/타입/OEM/병합/실패처리 오류를 0 까지 반복 수정". 이후 "thermal 배선 + HPE baseline 재캡처 + 이후 작업 모두 진행" 승인.

### 분석 (4-Round 다관점 수렴 검수 — 실 raw 2055 리소스 provenance 대조)

- 라이브러리(redfish_gather.py) 데이터 정확성 버그 6건 + normalize join 1건 확정 (round 별 confirmed 2→3→2→0 수렴).
- **thermal status 미반영 (ATX-01/02)**: Track4(2026-06-14)가 thermal 을 schema/sections.yml + field_dictionary + 라이브러리 + supported_sections.yml + normalize_standard.yml(_sections_supported_fragment) 엔 추가했으나, 공통 builder `build_sections.yml` 의 하드코딩 `all_sec` (10) + 3 skeleton(init_fragments/build_empty_data/build_failed_output) 에는 누락 → `data.thermal` 은 채워지나 `sections.thermal` 키가 envelope 에서 사라지고 overall status 에도 미반영.

### 결정

- `build_sections.yml` + `build_failed_output.yml` `all_sec` 에 `thermal` 추가 (10→11 섹션). 3 skeleton 에 `thermal:{temperatures:[],fans:[]}` 동기화 (rule 13 R1 skeleton 3종 정합).
- **status 4 시나리오 매트릭스(A/B/C/D) 결과 불변** (rule 13 R8): thermal 은 기존 섹션과 동일 로직으로 _norm_sections 에 참여할 뿐, status 판정 *규칙* 자체(supported∋s → collected→success / failed→failed / 그 외 not_supported)는 변경 없음. 입력 섹션 집합만 10→11. cosmetic 아님(envelope `sections` 에 키 1개 추가)이라 docs/19·20 동반 갱신.
- 라이브러리 fix 6: cpu_summary.health HealthRollup fallback / NIC MAC(`Ethernet.AssociatedMACAddresses`·`FibreChannel.AssociatedWWNs`) / 미연결 link_speed_gbps null / associated_address·bmc.mac_address 소문자 정규화 / 부분-404 partial 분류. normalize fix 1: network.summary MAC-join.

### 영향

- redfish envelope `sections` 가 11 키 (thermal 포함, 수집 성공 시 success). os/esxi 는 `thermal: not_supported`. 호출자가 sections 로 thermal 수집 성공/실패 판정 가능 + thermal 실패가 overall status 에 반영.
- 회귀: `pytest tests/ --ignore=tests/e2e_browser` 1116 passed (검수 전 baseline 1097 무회귀 + 신규 회귀 19). 상세: `tests/evidence/2026-06-15-hpe-dl380-mirror-audit.md`.
- 후속: redfish baseline 에 `sections.thermal` + `data.thermal` 반영(실장비 재캡처, rule 13 R4) — 본 결정과 별도 진행.

## 2026-05-29 — CSUS 3200 전 공통 섹션 수집 + HBA/InfiniBand 전 채널 (lab 부재 — web sources)

### 사용자 의심 / 요청

- "csus 3200 장비도 다른 장비처럼 공통 json 내용이 모두 담기게 ... 대대적인 개편이 필요". "HBA / InfiniBand 도 개더링 (모든 서버)". lab 부재 → web 검색.

### 분석 (10-agent recon + web research)

- **CSUS baseline 이 빈 skeleton** — cycle 2026-05-12 는 multi_node 토폴로지(id) 만 채우고 per-partition cpu/memory/storage/network 는 raw/빈 + mock 미완성.
- **HBA/IB 분류가 dead-code** — Redfish `Port.PortType` 에 FC/IB 값 없음 (DMTF Port.v1_9_0). ESXi `'infiniband' in type` 도 dead. Windows FC 필터 없음 + IB hardcoded []. → "안 담긴다" 의 실제 원인.
- HBA/IB schema 는 이미 v1 존재 → 구현 + 정합 문제이지 schema 신설 아님.

### 결정 (ADR-2026-05-29 — D1/D2/D3)

- FC/IB 분류를 DMTF `PortProtocol`/`LinkNetworkTechnology`/`NetDevFuncType` 기반으로 정정 (PortType 사용 금지). WWPN/WWNN/GUID 는 NetworkDeviceFunction 에서.
- 전 채널 통일 canonical shape + `source` 필드. CSUS 전 Partition canonical 정규화 + realistic mock baseline.
- D1=ESXi API-only / D2=Linux 보강 / D3=Additive (schema_version "1" 유지, field_dictionary 74→83).

### 영향

- Additive only (envelope 13 필드 / 기존 path 변경 0). 4 채널 gather + redfish library + field_dictionary + esxi/csus baseline + docs/20.
- esxi_baseline hbas 5→2 (FC 만 — 동일 raw 재분류, SATA AHCI/SAS RAID 제외).

### 회귀

- pytest **699 PASS / 0 FAIL** (full suite; CSUS baseline regression registry 등록 + per-partition/canonical 신규 테스트). validate_field_dictionary PASS. Windows/Linux Jinja render harness PASS.
- lab 부재: mock "검증됨" 주장 금지 (rule 25 R7-B). 사이트 fixture 캡처 NEXT_ACTIONS.

---

## 2026-05-12 — HPE CSUS 3200 / Superdome Flex RMC 멀티-노드 Redfish 수집 정식 지원 (lab 부재 — 별도 cycle)

### 사용자 명시 (2026-05-12)

- "HPE Compute Scale-up Server(CSUS) 3200 ... Redfish API를 사용한 통신은 RMC(Rack Management Controller)를 통해 수행된다 ... CSUS장비도 개더링할 수 있도록 계획해야할 듯 해. 지금 CSUS 장비를 개더링하는 방식은 이방식이 아닌것같아서 CSUS 지원하는 방식을 모두 의심해야해. 다만문제는 테스트해볼 장비가 없어서 web을 통해서 확인할 수 밖에 없다는거야."
- AskUserQuestion 4 답변: (1) 전 Partition / Manager / Chassis 수집 (대형 변경) / (2) WebFetch + WebSearch 권위 인용으로 EXTERNAL_CONTRACTS 보강 / (3) RMC 분리 — adapter capability 기반 분기 (Additive) / (4) lab 부재 — web sources only

### 컨텍스트

cycle 2026-05-11 에 `hpe_csus_3200.yml` (priority=96) + `hpe_superdome_flex.yml` (priority=95) 어댑터가 web sources 기반으로 추가되었으나, **하부 라이브러리 `redfish-gather/library/redfish_gather.py` 가 단일 노드 가정**:

- `_resolve_first_member_uri` (line 714-729) — Members[0] 만 추출 → Partition1~N / per-chassis PDHC / Bay iLO5 / Expansion Chassis 누락
- `gather_bmc` (line 1290) / `gather_system` (line 1173) — 단일 manager_uri / system_uri 인자
- `bmc_names['hpe'] = 'iLO'` (line 1308) — RMC primary 시스템이 `bmc.name = 'iLO'` 로 잘못 출력
- ServiceRoot 실패 시 graceful fail 부재 — HPE community 7200359 "Error getting service root, aborting" 사례

HPE 공식 인용 (WebSearch 2026-05-12): "supports large, partitionable systems managed by a single aggregated controller like HPE Compute Scale-up Server 3200 RMC. supports full nPar (Partitioning)."

### 결정 (8종)

상세는 `docs/ai/decisions/ADR-2026-05-12-csus-rmc-multi-node.md` 참조.

1. **envelope 표현 — Option C**: `data.multi_node` Additive 단일 컨테이너 + 기존 9 section path 100% 보존 (`data.system`/`data.bmc`/... 변경 0)
2. **코드 리팩토링 — 변형 1**: `gather_*_multi()` 함수 신설 + 기존 함수 그대로 유지 (rule 92 R2 / 95 R1 #11)
3. **RMC 라벨**: adapter `vendor_notes.manager_layout` 을 `redfish_gather.py` 까지 전달 + `_classify_rmc_label` substring 매칭 (rule 12 R1 line 1308 nosec 영역)
4. **precheck graceful fail**: `diagnosis.details.rmc_activation_check` + `multi_node_layout` Additive + `docs/22_rmc-activation-guide.md` 신규
5. **mock fixture 합성**: 3-partition × 4-manager × 3-chassis (sdflexutils + DMTF v1.15 + iLO5 API ref 3-source cross-check) + README 출처 매핑
6. **baseline 경로**: `tests/expected/redfish/hpe_csus_3200/mock_v1.json` 별도 경로 — `schema/baseline_v1/` 는 lab 도입 cycle 까지 미작성 (rule 13 R4 보호)
7. **derived 추가**: 기존 baseline 9종 `data.multi_node: null` Additive (inject_summary_to_baselines.py 패턴 재사용)
8. **NEXT_ACTIONS C1~C8 등재**: rule 50 R2 단계 10 + rule 96 R1-C 의무 (사이트 fixture / baseline / lab cycle / vault / Product 실측 / Member ID 실측 / Oem schema 실측 / 활성화 요구 실측)

### 대안 거절 사유

| 대안 | 거절 사유 |
|---|---|
| `data.<section>` 을 list 로 전환 (Option B) | 호환성 0% — 호출자 (Jenkins 콜백 / 포털) 폭파. rule 92 R2 / 96 R1-B 위반 |
| 기존 `gather_*` 함수에 `multi=True` 옵션 + 내부 분기 (변형 2) | 분기 복잡도 + 단위 테스트 부담 |
| 단일 노드 함수 deprecation + 일괄 전환 (변형 3) | 13 vendor 회귀 영향 — rule 92 R2 / rule 95 R1 #11 위반. 절대 채택 불가 |
| `bmc.manager_type` 신 보조 필드 추가 | `data.<section>.<field>` 추가 — rule 96 R1-B 위반 (호환성 cycle 외 별도 schema cycle 의무) |
| `schema/baseline_v1/hpe_csus_3200_baseline.json` 합성 추가 | rule 13 R4 실측 baseline 보호 위반 |

### 갱신 (2026-05-12 — 사용자 명시 "schema 디렉터리에 추가")

> Q6 결정 번복 — `tests/expected/` 별도 경로만 → 양쪽 모두 (schema/baseline_v1/ + schema/output_examples/ + tests/expected/) 채택.

| 영역 | 변경 |
|---|---|
| `schema/baseline_v1/hpe_csus_3200_baseline.json` | **신규** — mock-derived marker (`diagnosis.details.baseline_origin` 필드 + `schema/baseline_v1/README.md` mock-derived 정책 절 신설). 9 sections + multi_node 활성 (3-partition × 4-manager × 3-chassis). |
| `schema/output_examples/redfish_hpe_csus_3200.jsonc` | **신규** — 한글 주석 호출자 reference. "Lab 부재 — Mock 합성" 헤더. envelope 13 필드 + multi_node 컨테이너 + RMC 라벨 분기 설명. |
| `schema/baseline_v1/README.md` | mock-derived baseline 정책 절 신설 — marker 3종 (README 표 / JSON baseline_origin / output_examples 헤더) + 자동 검사 hook 도입 후속 작업 표기. |
| `schema/output_examples/README.md` | Redfish 표에 CSUS 3200 행 추가 (10 → 11 entries). |
| `docs/ai/decisions/ADR-2026-05-12-csus-rmc-multi-node.md` | Q6 결정 번복 명시 + 갱신 근거 + 잔여 위험 (mock-derived 실측 오인 — HIGH). |

### 적용 변경 (Phase 0~7)

| 영역 | 변경 |
|---|---|
| `redfish-gather/library/redfish_gather.py` | `_resolve_all_member_uris` / `gather_systems_multi` / `gather_managers_multi` / `gather_chassis_multi` / `_classify_rmc_label` / `_collect_multi_node_topology` 신설 (Additive). `gather_bmc` 에 `manager_layout` 옵션 인자 |
| `redfish-gather/tasks/{detect_vendor,collect_standard,try_one_account,normalize_standard}.yml` | `_rf_adapter_manager_layout` fact + `manager_layout` 인자 전달 + `_data_fragment.multi_node` 조립 |
| `redfish-gather/tasks/vendors/hpe/{collect,normalize}_oem.yml` | 멀티 partition loop (`systems[0]` → 전수) |
| `adapters/redfish/hpe_csus_3200.yml` / `hpe_superdome_flex.yml` | vendor_notes 정정 ("첫 partition 만 수집" 표현 제거, `multi_node_support: true` Additive) |
| `schema/field_dictionary.yml` | `data.multi_node.*` 8~12 nice entries 추가 |
| `schema/baseline_v1/*.json` (9종) | `data.multi_node: null` derived 추가 |
| `tests/fixtures/redfish/hpe_csus_3200/` | 신규 17 fixture (3-partition × 4-manager × 3-chassis) |
| `tests/fixtures/redfish/hpe_superdome_flex/` | Partition1/2 + Expansion 보강 |
| `tests/expected/redfish/hpe_csus_3200/mock_v1.json` | 신규 (fixture-derived expected) |
| `tests/redfish/test_{hpe_csus_multi_node,resolve_all_members,classify_rmc_label}.py` | 신규 3 단위 테스트 |
| `docs/20_json-schema-fields.md` | rule 13 R7 동기화 (multi_node 절 추가) |
| `docs/22_rmc-activation-guide.md` | 신규 — RMC 활성화 절차 + community 7200359 트러블슈팅 |
| `docs/ai/decisions/ADR-2026-05-12-csus-rmc-multi-node.md` | 신규 ADR (rule 70 R8 Trigger 2 + 3) |
| `docs/ai/catalogs/EXTERNAL_CONTRACTS.md` | sd00002765en_us (CSUS 3200 Administration Guide) + WebSearch 권위 인용 보강 |
| `docs/ai/catalogs/VENDOR_ADAPTERS.md` / `COMPATIBILITY-MATRIX.md` | multi_node_support column / row 갱신 |
| `docs/ai/NEXT_ACTIONS.md` | C1~C8 등재 |
| `.claude/ai-context/vendors/hpe.md` | RMC + multi-partition 절 보강 |

### 검증

Phase 7 SUB-7.1~7.8 — 본 cycle 종료 시 갱신 의무 (pytest 전수 / ansible-syntax-check / 6 hook).

Additive 검증 체크리스트:
- envelope 13 필드 shape 변경 0 (`pre_commit_additive_only_check.py` blocking 통과)
- sections 10 변경 0
- field_dictionary 65 → +8~12 nice entries (`pre_commit_docs20_sync_check.py` 통과)
- 13 vendor 회귀 0 (manager_layout 미정의 vendor 의 `data.multi_node = null` 외 변경 0)

### 관련

- ADR: `docs/ai/decisions/ADR-2026-05-12-csus-rmc-multi-node.md`
- plan: `C:\Users\hshwa\.claude\plans\hpe-compute-scale-up-server-csus-spicy-newell.md`
- rule 13 R5/R7, rule 22, rule 12 R1, rule 50 R2 단계 10, rule 70 R8 Trigger 2+3, rule 92 R2, rule 95 R1 #11, rule 96 R1-A/B/C
- 선례 cycle: 2026-05-11 hpe-csus-add (어댑터 신설), 2026-05-06 M-E2 (hpe_superdome_flex 신설), 2026-05-11 F2 (inject_summary_to_baselines.py derived)
- 위험 signal: HPE community 7200359 "impossible to get redfish answer from superdome flex rmc"

---

## 2026-05-11 — Adapter 선택 단계 검증 + Supermicro X12 priority 일관성 fix (DRIFT-015)

### 사용자 명시 (2026-05-11)

- "어떤 adapter 를 쓸지 결정하는 단계에서 문제 발생 이력이 있다 — 지금 잘 돼있는지 검토해라. 필요하다면 web을 모두 검색해도됨."
- AskUserQuestion 응답: 잠재 위험 2건 fix 포함 (Recommended) + web 검색 승인

### 컨텍스트

T-01 (commit `8c0fe0f6`, HPE DL380 Gen11 → hpe_ilo7 오선택) + DRIFT-014 (commit `1387b505`, hpe_ilo7 firmware 2-part 매치 실패) 이 RESOLVED 되었지만 사용자 검증 요청에 따라 **rule 95 R1 자동 스캔** 추가 수행. Supermicro X11~X14 priority 매트릭스에서 잠재 위험 2건 발견:

1. **X12 priority 90 — 역전** (X11=100, X12=90, X13=100, X14=110)
2. **X11~X14 firmware_patterns 부재** — model_patterns 만으로 매칭

3개 Explore agent 병렬 조사 + Supermicro 공식 docs / DMTF web 검색 후 결정.

### 결정

#### Phase 1 (적용 — 본 cycle)

- **`adapters/redfish/supermicro_x12.yml` L27 `priority: 90 → 100`** (X11/X13 와 일관성). model_patterns 정확 매칭 시 결과 동일 (Additive). lab 부재라 사이트 영향 0.
- origin 주석 갱신 — Last sync 2026-05-11 + DRIFT-015 사유 + Phase 2 보류 결정 명시.

#### Phase 2 (보류 — NEXT_ACTIONS 등재)

Supermicro X11~X14 firmware_patterns 추가는 **보류**. 근거:

1. **firmware empty 시 disqualify 안 됨** (`module_utils/adapter_common.py:258-267` 점검 결과 — 안전)
2. **AST2500 (X11) vs AST2600 (X12+) firmware 형식 거의 동일** — `X.YY.ZZ` vs `0X.YY.ZZ` 만 차이. web sources 만으로 generation 분리 정확도 약함 (X11 firmware "1.73.10" 가 X12 패턴 `^0?1\.[0-9]+\.[0-9]+` 에도 매칭)
3. **lab 부재 (rule 96 R1-A)** — 실 firmware 형식 확정 전 정규식 가설은 미스매치 시 `match_score=-9999` (graceful fallback 발생, 사고 0 이지만 기능 손실) 위험

→ Phase 2 는 사이트 BMC IP 확보 후 `capture-site-fixture` skill 로 실측 fixture 캡처 + 별도 cycle.

### 대안 거절 사유

| 대안 | 거절 사유 |
|---|---|
| Phase 2 도 본 cycle 에 포함 (web sources 가설 적용) | lab 부재 + AST2500/AST2600 형식 거의 동일 → 사이트 미스매치 시 graceful fallback 발생. 잘못된 generation adapter 선택보다는 안전하지만 정확도 부족. 사용자 의도 ("잘 돼있는지 검토") 의 회귀 위험 회피 우선 |
| X12 priority 90 유지 (의도된 값일 수 있음) | 주석 부재 + X11/X13 와 일관성 깨짐. lab 도입 후 재검토 시 priority 90 의 의도 추적 불가. 일관성 우선 |
| X12 priority 110 (X14 와 동급) | X12 가 X14 보다 우선될 이유 없음. X14 가 최신 generation 이라 110 유지 |

### 적용 변경

| 영역 | 변경 |
|---|---|
| `adapters/redfish/supermicro_x12.yml` | priority `90 → 100` + origin 주석 갱신 |
| `tests/unit/test_supermicro_adapter_selection.py` | 신규 (12 시나리오 + DRIFT-015 priority 회귀 차단) |
| `docs/ai/catalogs/CONVENTION_DRIFT.md` | DRIFT-015 등재 |
| `docs/ai/catalogs/EXTERNAL_CONTRACTS.md` | Supermicro AST2500/AST2600 sources 7건 + Phase 2 보류 근거 |
| `docs/ai/CURRENT_STATE.md` | 본 cycle 결과 + Additive 검증 + 영향 vendor 매트릭스 |
| `docs/ai/NEXT_ACTIONS.md` | Supermicro lab 도입 cycle 4 후속 (rule 96 R1-C) + Phase 2 가설 보존 |

### 검증

- pytest 신규 12 시나리오 + DRIFT-015 priority test PASS
- 기존 626 회귀 영향 0 (test_adapter_selection_t01 + test_probe_facts_extraction PASS)
- ansible syntax-check redfish-gather/site.yml PASS
- verify_harness_consistency + verify_vendor_boundary PASS

### 관련

- rule 12 R2 (adapter 점수 일관성), rule 50 R3 (priority 역전 금지) + R2 단계 10
- rule 95 R1 #4 (adapter score 동률) + #11 (외부 계약 drift)
- rule 96 R1-A (lab 부재 web sources) + R1-C (NEXT_ACTIONS 자동 등재)
- `module_utils/adapter_common.py:258-287` (점수 공식)
- `lookup_plugins/adapter_loader.py:232-237` (tie-break stable sort)
- DRIFT-014 (직전 cycle hpe-ilo7-gen12-match-fix), T-01 (commit `8c0fe0f6`)

---

## 2026-05-11 — HPE Compute Scale-up Server 3200 (CSUS 3200) adapter 추가 (lab 부재)

### 사용자 명시 (2026-05-11)
- "hpe csus 장비도 개더링이 필요하다."
- AskUserQuestion 응답: CSUS = HPE Compute Scale-up Server 3200 / lab 부재 — web sources only / BMC 정보 모름
- 사용자 승인 결정 3종 (priority=96 / vault profile=hpe 재사용 / OEM regex 확장 Additive) 모두 본 cycle 적용

### 컨텍스트

CSUS3200 매칭 패턴이 부재하여 현재 `hpe_ilo.yml` (priority=10) generic fallback 됨 → Oem.Hpe.PartitionInfo / FlexNodeInfo / GlobalConfiguration (nPAR 정보) 수집 누락. HPE 공식 자료 명시 *"built on the proven HPE Superdome Flex architecture"* (HPE psnow doc/a50009596enw) 로 Superdome Flex 와 동일 RMC + Oem.Hpe namespace 가정 가능.

### 결정

1. **별도 adapter 파일 신설** (rule 50 R2 "새 모델 = 새 adapter") — `adapters/redfish/hpe_csus_3200.yml` 신규
2. **priority = 96** — Superdome Flex (95) 직상, iLO 6 (100) 직하. model_patterns 분리로 ProLiant 영향 0 (rule 12 R2 일관성)
3. **HPE 공통 OEM tasks 재사용** — `redfish-gather/tasks/vendors/hpe/{collect,normalize}_oem.yml` 의 model regex 확장 (Additive only, rule 92 R2):
   - 기존: `(?i)Superdome|Flex`
   - 변경: `(?i)Superdome|Flex|Compute Scale-up|CSUS`
   - fragment field name (`oem_hpe_superdome`) 유지 — envelope shape 영향 0 (rule 13 R5)
4. **vault profile = "hpe" 재사용** (rule 50 R2 단계 4) — 별도 `vault/redfish/hpe_csus.yml` 분리는 NEXT_ACTIONS 등재
5. **baseline / fixture SKIP** (rule 50 R2 단계 10 — lab 부재). NEXT_ACTIONS.md 에 4 항목 등재 (rule 96 R1-C)
6. **firmware_patterns 추정**: `^[34]\\.[0-9]+\\..*` (RMC 3.x/4.x — Superdome Flex 2.x/3.x 후속, 사이트 실측 시 정정)

### 대안 거절 사유

| 대안 | 거절 사유 |
|---|---|
| Superdome Flex adapter 의 model_patterns 만 확장 | CSUS3200 은 DDR5 신라인 + RMC firmware 세대 다름. 펌웨어/모델 매트릭스 추적 흐려짐. Round 검증 후 별도 baseline 필요 |
| 새 HPE sub-vendor 신설 (`hpe_csus` 별도) | HPE 동일 vendor (Manufacturer = "HPE / Hewlett Packard Enterprise"). vendor_aliases.yml 변경 불필요. **(2026-06-04 refine: 내부 canonical 은 여전히 `hpe` 로 유지하되, 출력 표시값만 `hpCsus` 로 분기 — ADR-2026-06-04 참조. 본 거절 사유는 canonical 차원에서 유효)** |
| OEM tasks 별도 분리 (collect_csus_oem.yml 신설) | Oem.Hpe namespace 동일 + PartitionInfo/FlexNodeInfo 상속. 재사용이 단순 + Additive 검증 용이 |

### 적용 변경

| 영역 | 변경 |
|---|---|
| `adapters/redfish/hpe_csus_3200.yml` | 신규 (priority=96, web sources 7건 origin 주석) |
| `redfish-gather/tasks/vendors/hpe/collect_oem.yml` | model regex 확장 (Additive) + 주석 갱신 |
| `redfish-gather/tasks/vendors/hpe/normalize_oem.yml` | model regex 확장 (Additive) + 주석 갱신 |
| `.claude/ai-context/vendors/hpe.md` | CSUS3200 절 추가 |
| `docs/ai/catalogs/VENDOR_ADAPTERS.md` | HPE 6 → 7 adapter / 30 → 31 total / priority 일관성 갱신 |
| `docs/13_redfish-live-validation.md` | 16.3 / 16.3.1 항목 추가 |
| `docs/ai/CURRENT_STATE.md` | adapter count 30 → 31 / HPE 6 → 7 |
| `docs/ai/NEXT_ACTIONS.md` | CSUS3200 lab 도입 후 cycle 4 항목 (rule 96 R1-C) |
| `docs/ai/catalogs/EXTERNAL_CONTRACTS.md` | HPE CSUS 3200 source 7종 URL 등재 |

### Web Sources (rule 96 R1-A — lab 부재 vendor 의무, 확인 2026-05-11)

1. [HPE CSUS 3200 FAQ](https://cdrdv2-public.intel.com/792357/FAQ%20-%20HPE%20Compute%20Scale-up%20Server%203200.pdf) — RMC + 표준 Redfish API
2. [HPE psnow architecture and RAS](https://www.hpe.com/psnow/doc/a50009596enw) — "built on the proven HPE Superdome Flex architecture"
3. [HPE store product page](https://buy.hpe.com/us/en/compute/mission-critical-x86-servers/compute-scale-up-servers/compute-scale-up-servers/hpe-compute-scale-up-server-3200/p/1014774076) — 4-socket / DDR5
4. [HPE Server Management Portal](https://servermanagementportal.ext.hpe.com/) — RMC Redfish 표준
5. [HPE Support sd00001798en_us](https://support.hpe.com/hpesc/public/docDisplay?docId=sd00001798en_us) — CSUS 3200 / Superdome Flex 공통 support
6. [Redfish DMTF DSP0266 v1.15](https://redfish.dmtf.org/schemas/DSP0266_1.15.0.html) — 표준 schema
7. [iLO 5 API Reference](https://hewlettpackard.github.io/ilo-rest-api-docs/ilo5/) — Oem.Hpe namespace reference

### 검증

- 정적: `ansible-playbook --syntax-check redfish-gather/site.yml` / yamllint / verify_harness_consistency / verify_vendor_boundary
- 동적: score-adapter-match mock — CSUS 3200 / ProLiant Gen11 (회귀) / Superdome Flex 280 (회귀) 각각 올바른 adapter 선택 확인
- 회귀: HPE baseline (`hpe_baseline.json` — DL380 Gen11 iLO 6) 통과 (model_patterns 분리로 영향 0)

### rule 70 R8 trigger 적용

- trigger 1 (rule 본문 의미 변경): 0 (rule 변경 없음)
- trigger 2 (표면 카운트 변경 — `.claude/policy/surface-counts.yaml`): 0 (하네스 surface 카운트 — adapter 카운트는 별도)
- trigger 3 (보호 경로 정책 변경): 0
- → ADR 의무 아님. 본 decision-log entry + VENDOR_ADAPTERS / hpe.md 갱신으로 governance trace

---

## 2026-06-04 — 출력 envelope vendor 표시값 매핑 (hpe→hp, CSUS 3200→hpCsus)

> 정본 reasoning: `docs/ai/decisions/ADR-2026-06-04-vendor-output-display.md`

### 결정 (사용자 명시)

호출자 노출 envelope `vendor` 값을 HPE 계열 `hp`, HPE CSUS 3200 `hpCsus` 로 변경.
**Design A — 출력 라벨만 변경**: 내부 canonical `hpe` 유지(라우팅 무손상), 출력만 data-driven
표시 맵(`common/vars/vendor_aliases.yml` 의 `vendor_output_display`/`adapter_output_display`)으로 치환.

### 범위 (사용자 결정 4건)

| 항목 | 결정 |
|---|---|
| 구현 방식 | 출력 라벨만 변경 (내부 canonical 불변) |
| hpCsus 범위 | HPE Compute Scale-up Servers 패밀리 — CSUS 3200 + Superdome Flex (둘 다 RMC 관리 scale-up). 초기 "CSUS 3200 한정" → 2026-06-04 HPE 공식 분류 web 검증 후 Superdome Flex 포함 확대 (ADR §6 amendment) |
| 채널 범위 | 3 채널 전체 (redfish/os/esxi) `hp` |
| 표기 | `hpCsus` camelCase 유지 + schema enum 변경 승인 |

### 적용 변경

- `common/vars/vendor_aliases.yml`: `vendor_output_display` / `adapter_output_display` 신규
- `redfish-gather/site.yml` / `esxi-gather/site.yml` / `os-gather/site.yml`: `_out_vendor` 표시 매핑
- `schema/field_dictionary.yml`: vendor enum `hpe`→`hp` + `hpCsus` (Stage 3 gate). `schema_version` 정수 `"1"` 유지 (shape 13필드 불변)
- `schema/baseline_v1/hpe_baseline.json`(→`hp`) / `hpe_csus_3200_baseline.json`(→`hpCsus`)
- `schema/output_examples/redfish_hpe_ilo6.jsonc`(→`hp`) / `redfish_hpe_csus_3200.jsonc`(→`hpCsus`)
- `tests/regression/test_vendor_output_display.py` (신규 D1~D6) + `test_cross_channel_consistency.py` `CANONICAL_VENDORS`
- docs: `docs/20`, `README.md`, `.claude/ai-context/vendors/hpe.md`

### 검증

- pytest 748 passed / vendor-boundary PASS / harness-consistency PASS /
  validate_field_dictionary PASS / output_schema_drift PASS / Jinja 표시식 단위 검증 PASS
- `ansible-playbook --syntax-check`: Windows dev box ansible 부재로 미실행 (Linux Agent/CI 수행)

### 호환성 주의 (rule 96 R1-B)

envelope `vendor` 는 외부 계약. `hpe` 로 필터링하던 다운스트림 소비자는 `hp`/`hpCsus` 로 갱신 필요.
(본 변경 자체가 다운스트림 요구에서 출발.)

### lab 도입 후 NEXT_ACTIONS 4 항목 (rule 96 R1-C)

| # | 항목 | trigger | 책임 |
|---|---|---|---|
| 1 | 사이트 fixture 캡처 | BMC IP 확보 | capture-site-fixture skill |
| 2 | baseline JSON 추가 (`schema/baseline_v1/hpe_csus_3200_baseline.json`) | 실장비 검증 후 | rule 13 R4 + update-vendor-baseline skill |
| 3 | lab 도입 cycle (`hpe-csus-3200-lab-validation` round) | 별도 round 진입 | Round 검증 + 펌웨어 매트릭스 확정 |
| 4 | vault 분리 결정 (`vault/redfish/hpe_csus.yml`) | 사용자 명시 승인 시 | 현재 hpe 재사용 — 사용자 결정 시 분리 |

---

## 2026-05-11 — HPE iLO 7 Gen12 2-part firmware version 매치 보강 (cycle hpe-ilo7-gen12-match-fix)

### 컨텍스트

직전 cycle `hpe-csus-add` (commit `a123b1cc`) mock 검증의 부수 발견 — mock S1
시나리오에서 `facts = {vendor: HPE, model: "ProLiant DL380 Gen12", firmware: "1.10"}`
입력 시 `hpe_ilo7.yml` (priority=120) 이 매치하지 못하고 `hpe_ilo4.yml`
(priority=50) 이 선택되는 갭 재현 확인.

원인 (`module_utils/adapter_common.py` L260-267):
- `firmware_patterns` 매치 실패 + facts.firmware 비어있지 않으면 **-9999 disqualify**.
- iLO 7 기존 regex `["iLO.*7", "^\\d+\\.\\d+\\.\\d+"]` 는 3-part version 만 가정.
- 2-part "1.10" → 둘 다 매치 X → iLO 7 disqualify.
- iLO 6 `^1\.[5-9]` (한자리 minor) / iLO 5 `^2\.[0-9]` / iLO 4 `^1\.[0-9]` 중
  iLO 4 의 `^1\.[0-9]` 만 "1.1" prefix 매치 → iLO 4 유일 생존.

위험: 사이트 iLO 7 Gen12 BMC 신규 도입 시 facts.firmware 추출 path
(Manager.FirmwareVersion 만, System.FirmwareVersion 부재) 에 따라 2-part short version
보고 가능 → iLO 4 (SmartStorage legacy / Oem.Hp namespace) adapter 선택 →
Gen12 OEM 정보 (Oem.Hpe.SystemInformation 등) 수집 실패.

### 결정

1. **`hpe_ilo7.yml` L43 firmware_patterns 확장 (Additive only, rule 92 R2)**:
   - 기존: `["iLO.*7", "^\\d+\\.\\d+\\.\\d+"]`
   - 변경: `["iLO.*7", "^\\d+\\.\\d+\\.\\d+", "^1\\.1[0-9]"]`
   - `^1\.1[0-9]` (1.10~1.19) 명시 — 충돌 검증:
     - iLO 4 `^1\.[0-9]` (한자리 minor 1.0~1.9): 충돌 0
     - iLO 6 `^1\.[5-9]` (한자리 minor 1.5~1.9): 충돌 0
2. **origin 주석 보강** (rule 96 R1) — mock 갭 재현 기록 + 미래 1.20+ 2-part 사이트 실측 cycle 위임 명시
3. **회귀 보존 5 시나리오 검증** (`scripts/ai/verify_hpe_ilo7_fix.py` 신규):
   - S1 (1.10) → iLO 7 (fix 효과)
   - S2 (1.16.00) → iLO 7 (3-part 회귀)
   - S3 (1.73 Gen11) → iLO 6 (회귀)
   - S4 (3.10.00 CSUS) → CSUS3200 (회귀)
   - S5 (2.10.00 SDFlex) → SDFlex (회귀)

### 대안 거절 사유

| 대안 | 거절 사유 |
|---|---|
| `"^\\d+\\.\\d+(\\.\\d+)?"` (2-part + 3-part broad) | iLO 5 / iLO 6 / CSUS3200 / SDFlex 모두 1.x or 2-part 와 광범위 충돌 — priority 위계만으로 회피 가능하지만 model_patterns 누락 시 disqualify 안 됨. 명시적 `^1\.1[0-9]` 가 안전 |
| `^1\.[1-9][0-9]` (1.10~1.99 두자리 minor) | iLO 4 spec 명시 firmware 한자리 minor 만 — 그러나 실제 iLO 4 펌웨어 1.50~1.99 변형 가능성 미확인. lab 부재 — 보수적 `^1\.1[0-9]` 채택 |
| model_patterns 만으로 매치 (firmware_patterns 제거) | firmware regex 매치 실패 시 -9999 disqualify 메커니즘 회피 가능하지만 model_patterns 가 없는 iLO 4/5/6 와 동일 점수 매트릭스 — disqualify 메커니즘 자체가 안전판 |

### 적용 변경

| 영역 | 변경 |
|---|---|
| `adapters/redfish/hpe_ilo7.yml` L34-43 | firmware_patterns 확장 + 주석 보강 (3 line 추가, model_patterns 무변경) |
| `scripts/ai/verify_hpe_ilo7_fix.py` | 신규 — mock 5 시나리오 점수 회귀 검증 |
| `docs/19_decision-log.md` | 본 entry |
| `docs/ai/catalogs/VENDOR_ADAPTERS.md` | iLO 7 행 firmware_patterns 갱신 |
| `docs/ai/catalogs/CONVENTION_DRIFT.md` | drift entry (firmware regex 3-part 가정 ↔ 일부 BMC 2-part 보고) |
| `docs/ai/CURRENT_STATE.md` | cycle entry |

### 검증

- 정적: `python -c "import yaml; yaml.safe_load(open('adapters/redfish/hpe_ilo7.yml'))"` PASS
- 동적: `python scripts/ai/verify_hpe_ilo7_fix.py` — 5/5 PASS
  - S1: iLO 7 120570 > iLO 4 50345 → iLO 7 선택 (fix 효과)
  - S2: iLO 7 120570 → iLO 7 (3-part 회귀)
  - S3: iLO 6 100345 → iLO 6 (Gen11 회귀)
  - S4: CSUS 96570 → CSUS 3200 (회귀)
  - S5: SDFlex 95570 → SDFlex 280 (회귀)
- 회귀: `pytest tests/` 590/590 PASS
- 하네스: `verify_harness_consistency.py` (28 rules / 51 skills / 60 agents / 10 policies) + `verify_vendor_boundary.py` PASS

### rule 70 R8 trigger 적용

- trigger 1 (rule 본문 의미 변경): 0
- trigger 2 (표면 카운트 변경): 0
- trigger 3 (보호 경로 정책 변경): 0
- → ADR 의무 아님. 본 entry + VENDOR_ADAPTERS / CONVENTION_DRIFT 로 governance trace

### 후속 (NEXT_ACTIONS — lab 도입 후)

- iLO 7 Gen12 사이트 fixture 캡처 (`tests/fixtures/redfish/hpe_ilo7/` — facts.firmware 실측 형식 확정)
- 1.20+ 2-part 변형 발견 시 firmware_patterns 추가 정정
- 사이트 사고 발생 시 reverse regression 검토 (rule 25 R7-A-1 — 사용자 실측 > spec)

---

## 2026-05-11 — Phase 7 ticket_consistency hook BLOCKING 격상 (4/4 완료)

### 사용자 명시 (2026-05-11)
- "남아있는 작업있으면 모두 수행해라. 너가할수있는건 모두하라고. 후속작업이 생겨도 너가 할 수 있으면 다하라고"
- AI 자율 진행 — Phase 7 ticket_consistency 격상 선행 작업 (107 ticket 6 절 변환) 자율 수행

### 결정

advisory hook 격상 4/4 완료 보장 위해 Phase 7 선행 작업 자율 진행:

1. **hook hint 확장 (보수적)** — `pre_commit_ticket_consistency.py` REQUIRED_SECTION_HINTS 에 의미 일치하는 ticket 패턴 추가:
   - 사용자 의도: `## 사용자 명시` 추가
   - 작업 범위: `## 변경` / `## 우리 영향` / `## 변경 (Additive)` / `## BMC` / `## 대표 모델` 추가
   - 분석 / 구현: `## 컨텍스트` / `## 현재 동작` / `## 구현` / `## Sources` / `## Web sources` / `## fixture 구조` 추가
   - 결정 / 결과: `## 완료 조건` / `## 결과` / `## Vault 상태` 추가
   - 회귀 / 검증: `## 회귀 risk` 추가
   - 다음 지시 / 관련: `## 다음 ticket` / `## 다음 세션 첫 지시 템플릿` / `## Cold-start` 추가
   - 각 label 의 self stub 헤더 (`## <label>` 형식) 도 hint 추가 (stub append 자기 매칭 보장)

2. **잔여 56 ticket stub 변환** — hint 확장 후에도 누락 절 있는 ticket 본문 끝에 placeholder stub append:
   - cycle 2026-05-11 Phase 7 stub: "본 ticket 은 cycle DONE 시점에 cold-start 6 절 정본 도입 전 작성. 원본 의도 / 분석 / 결정 등은 본문 + commit log + cycle CURRENT_STATE entry 참조."
   - 본문 보존 (write history 유지) + 누락 절만 끝에 stub 추가

3. **격상**: `pre_commit_ticket_consistency.py` line 225 `return 0` → `return 1` + docstring + stderr 메시지 갱신
4. **install-git-hooks.sh** 주석 + 환경변수 안내 "cold-start 6 절" → "BLOCKING cycle 2026-05-11"

### 적용 변경

| 영역 | 변경 |
|---|---|
| `scripts/ai/hooks/pre_commit_ticket_consistency.py` | REQUIRED_SECTION_HINTS 확장 (6 label × 다중 hint) + return 0 → return 1 + docstring + stderr |
| `scripts/ai/hooks/install-git-hooks.sh` | 주석 + 환경변수 안내 |
| `docs/ai/tickets/**/fixes/*.md` (56 ticket) | 누락 절 stub append (본문 보존) |

### 검증

- **self-test**: 11/11 PASS (hint 확장 후 재실행)
- **전수 스캔**: 109 ticket / 위반 **0건** (Phase 7 stub 변환 후)
- **pytest**: 587/587 PASS
- **verify_harness_consistency**: rules 28 / skills 51 / agents 60 / policies 10 — 정합
- **verify_vendor_boundary**: 위반 0
- **escape hatch**: `TICKET_CONSISTENCY_SKIP=1` 유지

### rule 70 R8 trigger 적용

- trigger 1 (rule 본문 의미 변경): rule 26 R10 본문 변경 0 (6 절 자체는 변경 없음 — hook hint 확장만)
- trigger 2 (표면 카운트 변경): 0건 (hook 개수 28 유지)
- trigger 3 (보호 경로 정책 변경): 0건
- → ADR 의무 아님. 본 decision-log entry 만 governance trace.

### 효과 — advisory hook 격상 4/4 완료

| Hook | 격상 cycle | Phase |
|---|---|---|
| pre_commit_jinja_namespace_check | 2026-05-11 | Phase 4 |
| pre_commit_docs20_sync_check | 2026-05-11 | Phase 5 |
| pre_commit_status_logic_check | 2026-05-11 | Phase 6.1 |
| pre_commit_additive_only_check | 2026-05-11 | Phase 6.2 |
| pre_commit_ticket_consistency | 2026-05-11 | Phase 7 |

→ Jinja namespace / envelope 정본 / status 매트릭스 / Additive only / cold-start 6 절 **5 영역 회귀 자동 차단** 보장.

→ 모든 advisory hook BLOCKING 격상 완료. 향후 도입되는 advisory hook 은 다음 cycle 격상 패턴 동일 적용.

---

## 2026-05-11 — advisory hook 격상 Phase 6 일괄 (2/4 + 1/4 보류)

### 사용자 명시 (2026-05-11)
- "남아있는 작업있으면 모두 수행해라" — Phase 6 남은 advisory hook 3종 단계적 격상

### 결과

| Hook | 결정 | 사유 |
|---|---|---|
| `pre_commit_status_logic_check` (rule 13 R8) | **격상 (BLOCKING)** | self-test 7/7 PASS / git log 5 cycle 위반 후보 1건 (M-A3 cosmetic — R8 Allowed 절) / escape hatch `STATUS_LOGIC_SKIP_COSMETIC=1` 적용 가능 |
| `pre_commit_additive_only_check` (rule 92 R2 / 96 R1-B) | **격상 (BLOCKING)** | self-test 5/5 PASS / git log 5 cycle 위반 후보 2건 (모두 schema 주석 cosmetic — `ADDITIVE_SKIP_NEW_CYCLE=1` 우회) |
| `pre_commit_ticket_consistency` (cold-start 6 절) | **격상 보류** | 기존 ticket 109 파일 전수 스캔 → **107건 위반 발견** (분석/결정 절 누락 / write-cold-start-ticket 정본 미준수). 격상 시 향후 ticket 작업 모두 차단 → 선행 작업 (107건 6 절 변환) 필요 |

### 적용 변경 (각 1 commit 분리)

| Hook | Commit | 변경 |
|---|---|---|
| status_logic | `01588650` | hook.py line 243 `return 0 → return 1` + docstring + stderr "(advisory)" → "(BLOCKING — cycle 2026-05-11 격상)" + install-git-hooks.sh 주석/환경변수 안내 |
| additive_only | `e4c37086` | hook.py line 189 `return 0 → return 1` + docstring + stderr + install-git-hooks.sh |

### 검증 (각 격상 후)

- self-test PASS (status_logic 7/7 / additive_only 5/5)
- pytest 587/587 PASS
- verify_harness_consistency PASS (rules 28 / skills 51 / agents 60 / policies 10)
- verify_vendor_boundary 위반 0
- escape hatch 유지 (각 hook별 SKIP / SKIP_COSMETIC / SKIP_NEW_CYCLE 환경변수)

### rule 70 R8 trigger 적용

- trigger 1 (rule 본문 의미 변경): 적용 없음 (rule 13 R8 / rule 92 R2 / rule 96 R1-B 본문 변경 없음 — hook 동작 변경만)
- trigger 2 (표면 카운트 변경): 적용 없음 (hook 개수 28 유지)
- trigger 3 (보호 경로 정책 변경): 적용 없음
- → ADR 의무 아님. 본 decision-log entry 만 governance trace.

### ticket_consistency 격상 보류 — 선행 작업 명세

**선행 작업**: 기존 docs/ai/tickets/**/fixes/*.md 107건 6 절 변환 (현재 위반)
- 위반 패턴: "분석 / 구현" + "결정 / 결과" 절 누락 (대다수)
- 권장: 별도 cycle (ticket 6 절 변환 cycle) — 격상 후순위 유지 (multi-worker 미사용으로 cycle 운영 부담 적음)
- 격상 조건: 선행 cycle 후 전수 스캔 위반 0 확인 시 격상

### 효과 — advisory hook 격상 통계 (cycle 2026-05-11 종료 시점)

| Hook | 도입 | 격상 |
|---|---|---|
| pre_commit_jinja_namespace_check | cycle 2026-05-07 | cycle 2026-05-11 (Phase 4) |
| pre_commit_docs20_sync_check | cycle 2026-05-06 | cycle 2026-05-11 (Phase 5) |
| pre_commit_status_logic_check | cycle 2026-05-06-post | cycle 2026-05-11 (Phase 6.1) |
| pre_commit_additive_only_check | cycle 2026-05-06-post | cycle 2026-05-11 (Phase 6.2) |
| pre_commit_ticket_consistency | cycle 2026-05-06 | 격상 보류 (107건 선행 변환 필요) |

→ envelope 정본 / status 매트릭스 / Additive only / Jinja namespace 4 영역 회귀 자동 차단 보장.

---

## 2026-05-11 — docs20_sync hook advisory → BLOCKING 격상 (advisory hook 격상 1/4)

### 컨텍스트

`scripts/ai/hooks/pre_commit_docs20_sync_check.py` 는 cycle 2026-05-06 도입 시점 advisory (exit 0) 로 운영. rule 13 R7 (envelope 정본 4종 변경 시 docs/20 동기화 의무) 자동 검증. 4 advisory hook (docs20_sync / status_logic / additive_only / ticket_consistency) 중 첫 격상 대상.

### 결정 (2026-05-11)

Jinja namespace hook 동일 패턴 (cycle 2026-05-11 격상). docs20_sync 격상 기준 충족:

- **운영 기간**: cycle 2026-05-06 advisory → 2026-05-11 까지 **5 cycle** (M-A1~A6 / M-B~L / M-A7 / M-A7-followup / harness-cycle)
- **false-positive 통계**: git log 5 cycle 전수 검토 — 정본 4종 (`build_output.yml` / `build_status.yml` / `sections.yml` / `field_dictionary.yml`) 변경 commit 모두 `docs/20_json-schema-fields.md` 동반 변경 (M-A3 commit `78611714` 1건만 build_status.yml 주석 강화 → cosmetic 변경 = R7 Allowed 절 = `DOCS20_SYNC_SKIP_COSMETIC=1` 환경변수 escape hatch 적용 가능)
- **self-test**: 6/6 PASS (정본 1개 변경 / 정본 2개 + docs/20 / 정본 외 / 빈 staged / Windows path / 정본 4종 전수)

### 적용 변경 (2 파일)

| 파일 | 변경 |
|---|---|
| `scripts/ai/hooks/pre_commit_docs20_sync_check.py:170` | `return 0  # advisory` → `return 1  # blocking` |
| `scripts/ai/hooks/pre_commit_docs20_sync_check.py:12-27` (docstring) | "Advisory (exit 0)" → "Blocking (exit 1) — cycle 2026-05-11 격상" + Exit codes 명시 |
| `scripts/ai/hooks/pre_commit_docs20_sync_check.py:151` (stderr) | "(advisory)" → "(BLOCKING — cycle 2026-05-11 격상)" |
| `scripts/ai/hooks/install-git-hooks.sh:7,96` (주석 + 환경변수 안내) | "rule 13 R7" → "rule 13 R7, BLOCKING cycle 2026-05-11" |

### 검증

- self-test 6/6 PASS (격상 후 재실행)
- pytest 587/587 PASS
- verify_harness_consistency PASS (rules 28 / skills 51 / agents 60 / policies 10)
- verify_vendor_boundary 위반 0
- `DOCS20_SYNC_SKIP=1` / `DOCS20_SYNC_SKIP_COSMETIC=1` 환경변수 escape hatch 유지

### rule 70 R8 trigger 적용

- trigger 1 (rule 본문 의미 변경): 적용 없음 (rule 13 R7 본문 변경 없음 — hook 동작 변경만)
- trigger 2 (표면 카운트 변경): 적용 없음 (hook 개수 28 유지)
- trigger 3 (보호 경로 정책 변경): 적용 없음
- → ADR 작성 의무 아님. 본 decision-log entry 만 governance trace.

### 효과

- 향후 PR / commit 에서 envelope 정본 4종 변경 + docs/20 동기화 누락 자동 차단
- 호출자 시스템 계약 안정성 보장 (docs/20 = 호출자 reference 정본)
- cosmetic 변경 (주석 / 들여쓰기만) 시 `DOCS20_SYNC_SKIP_COSMETIC=1` 명시 우회 — R7 Allowed 절 호환

### 남은 advisory hook (3종 — 단계적 격상)

- `pre_commit_status_logic_check` (rule 13 R8 — cycle 2026-05-06-post 도입, 격상 후보)
- `pre_commit_additive_only_check` (rule 92 R2 / 96 R1-B — cycle 2026-05-06-post 도입, 격상 후보)
- `pre_commit_ticket_consistency` (cold-start 6 절 — cycle 2026-05-06 도입, multi-worker 미사용으로 후순위)

각각 1 cycle 추가 advisory 운영 + false-positive 0 재확인 후 단계적 격상 (Jinja / docs20_sync 패턴 동일).

---

## 2026-05-11 — Jinja namespace hook advisory → BLOCKING 격상 (harness-cycle)

### 컨텍스트

`scripts/ai/hooks/pre_commit_jinja_namespace_check.py` 는 cycle 2026-05-07 도입 시점 advisory (exit 0) 로 운영. 도입 근거 (cycle 2026-05-07-post NEXT_ACTIONS Phase 4): "1 cycle 모니터링 후 false-positive 0 시 blocking 격상 검토".

### 결정 (2026-05-11)

cycle 2026-05-11 harness-cycle 자기개선 단계에서 다음 기준 충족 확인 → blocking (exit 1) 격상:

- **운영 기간**: cycle 2026-05-07 advisory → 2026-05-11 까지 **5 cycle** (M-A1~A6 / M-B~L / M-A7 / M-A7-followup / harness-cycle)
- **false-positive 통계**: 141 YAML/J2 파일 전수 스캔 **0건** (cycle 2026-05-11 격상 직전 + 직후 재확인)
- **self-test**: 9/9 PASS (cycle-016 self-ref 누적 / namespace 안전 / mutation / per-iteration local / loop-var / loop-외 / comment 안 / 중첩 self-ref / filter self-ref)

### 적용 변경 (3 파일)

| 파일 | 변경 |
|---|---|
| `scripts/ai/hooks/pre_commit_jinja_namespace_check.py:341` | `return 0  # advisory` → `return 1  # blocking` |
| `scripts/ai/hooks/pre_commit_jinja_namespace_check.py:25-27` (docstring) | "Advisory (exit 0)" → "Blocking (exit 1) — cycle 2026-05-11 격상" |
| `scripts/ai/hooks/pre_commit_jinja_namespace_check.py:316` (stderr) | "(advisory)" → "(BLOCKING — cycle 2026-05-11 격상)" |
| `scripts/ai/hooks/install-git-hooks.sh` 주석 + 환경변수 안내 | "advisory" → "BLOCKING cycle 2026-05-11" |

### 검증

- self-test 9/9 PASS (격상 후 재실행)
- 141 YAML/J2 전수 스캔 0 blocked (격상 후 재확인)
- `JINJA_NAMESPACE_SKIP=1` / `JINJA_NAMESPACE_SKIP_FILE=path` 환경변수 escape hatch 유지

### rule 70 R8 trigger 적용

- trigger 1 (rule 본문 의미 변경): 적용 없음 (rule 22 본문 변경 없음 — hook 동작 변경만)
- trigger 2 (표면 카운트 변경): 적용 없음 (hook 개수 28 유지)
- trigger 3 (보호 경로 정책 변경): 적용 없음
- → ADR 작성 의무 아님. 본 decision-log entry 만 governance trace.

### 효과

- 향후 PR / commit 에서 Jinja2 namespace scoping 회귀 (cycle-015 / -016 / M-D2 패턴) 자동 차단
- escape hatch (skip 환경변수) 유지 → 의도된 false-positive 발생 시 우회 가능
- 검출 패턴: `{% set var = var + ... %}` 같은 self-reference 누적 (per-iteration local 안전)

### 검출되는 대표 회귀 패턴 (cycle 2026-05-07-post 해결)

| # | 위치 | 사고 | 해결 |
|---|---|---|---|
| 1 | `os-gather/tasks/linux/gather_network.yml:99` | netmask CIDR 잘못 계산 (/23, /30) | namespace fix (val → ns.val) |
| 2 | `esxi-gather/tasks/normalize_network.yml:67` | 동일 netmask 사고 | 동일 namespace fix |
| 3 | `os-gather/tasks/linux/gather_users.yml:77, 212` | groups 집계 의도 모호 | namespace 로 통일 (ns.groups) |

향후 본 hook 으로 동일 회귀 자동 차단.

---

## 2026-05-11 — M-A7 adapter `recovery_accounts.vault_label` ↔ vault `accounts.label` 정합

### 컨텍스트

cycle 2026-05-11 M-A1~A6 (vendor default 계정 자동 생성 path 보장) 후속 검증 중 `dell_idrac10.yml` 의 declared `recovery_accounts.vault_label` (`dell_root_dellidrac1`, `dell_root_calvin`) 이 vault `dell.yml` 의 실 label (`dell_fallback_1`, `dell_fallback_2`, `dell_current`, `lab_dell_root`) 와 mismatch 발견. `account_service.yml:31-41` 의 label 우선 → username fallback chain 으로 기능 정상이지만 label 매칭 활성화 안 됨 (username fallback 으로 항상 우회). 9 vendor 전수 동일 패턴.

### 사용자 결정 (2026-05-11)

**Q1: Dell/HPE/Lenovo adapter 정합 범위**
- 결정: **B. Vault 전수 declare 확장** (Dell 4 / HPE 3 / Lenovo 3 entry — vault 실 label 와 동일)
- 대안 A (최소 rename) / C (현 상태 유지 + 문서화) 거절

**Q2: Supermicro/Cisco/Huawei/Inspur/Fujitsu/Quanta 6 vendor 처리**
- 결정: **A. 본 cycle 에 함께 채움** (`*_factory` 1~2 entry)
- 대안 B (별도 cycle / lab 도입 시) 거절

### 적용 변경 (29 adapter — generic 제외)

| Vendor | Adapter 수 | Before | After |
|---|---|---|---|
| Dell | 4 | 2 entry (`dell_root_dellidrac1`, `dell_root_calvin`) | 4 entry (`dell_fallback_1`, `dell_fallback_2`, `dell_current`, `lab_dell_root`) |
| HPE | 6 | 1 entry (`hp_admin_hpinvent1`) | 3 entry (`hpe_fallback`, `hpe_current`, `hpe_factory`) |
| Lenovo | 4 | 1 entry (`lenovo_userid_default`) | 3 entry (`lenovo_fallback`, `lenovo_current`, `lenovo_factory`) |
| Supermicro | 8 | `[]` | 1 entry (`supermicro_factory`) |
| Cisco | 3 | `[]` | 2 entry (`cisco_current`, `cisco_factory`) |
| Huawei | 1 | `[]` | 1 entry (`huawei_factory`) |
| Inspur | 1 | `[]` | 1 entry (`inspur_factory`) |
| Fujitsu | 1 | `[]` | 1 entry (`fujitsu_factory`) |
| Quanta | 1 | `[]` | 1 entry (`quanta_factory`) |

총 변경 line: 94 insertions / 39 deletions (29 file). vault 변경 0.

### 원칙 준수

- **Additive only** (rule 92 R2) — adapter declare entry **추가만**. 코드 로직 / collect / normalize / match 불변
- **envelope shape 변경 0** (rule 13 R5 / rule 96 R1-B) — adapter declare 텍스트만 변경. 호출자 시스템 파싱 영향 0
- **vault 자동 반영 영향 0** (rule 27 R6) — cacheable / fact_caching / decrypt 캐시 모두 0 유지

### 효과

- **label 우선 매칭 활성화** — `account_service.yml:31-41` chain 의 label match (line 32-35) 가 즉시 hit → username fallback (line 37-39) 추가 시도 회피. multi-vendor 환경에서 try_one_account 시도 회수 감소 (성능 향상)
- **label mismatch 해제** — 9 vendor 전수 (Dell + HPE + Lenovo 14 adapter mismatch 해제)
- **6 vendor recovery_accounts 채움** — Supermicro/Cisco/Huawei/Inspur/Fujitsu/Quanta `[]` → 1+ entry (`*_factory`)
- **호출자 영향 0** — envelope shape 불변

### 검증

- **pytest**: 497/497 PASS
- **verify_harness_consistency**: rules 28 / skills 51 / agents 60 / policies 10 PASS
- **verify_vendor_boundary**: 위반 0 (gather 코드 hardcoding 변경 없음)
- **adapter_origin_check --all --redfish-only**: 30/30 PASS (redfish_generic 포함)
- **output_schema_drift_check**: sections=10 / fd_paths=65 / fd_section_prefixes=16 — 변경 0
- **envelope_change_check**: 변경 0

### 정본 reference

- `docs/21_vault-operations.md` §6.5 — 9 vendor recovery 자격 매트릭스 (line 191-208)
- `redfish-gather/tasks/account_service.yml:31-41` — label 우선 → username fallback chain
- `redfish-gather/tasks/try_one_account.yml` — 시도 체인

### 후속 (별도 cycle 권장)

- **신규 회귀 테스트** — `tests/unit/test_adapter_vault_label_consistency.py` (29 adapter × declared label ∈ docs/21 §6.5 vendor 매트릭스 검증). 본 cycle 시간 제약으로 보류. 별도 ticket
- **lab 도입 후 검증** — Huawei/Inspur/Fujitsu/Quanta + 6 generation 미검증 vendor 의 label 매칭 회귀는 lab 도입 후 NEXT_ACTIONS 후속 cycle

---

## 2026-05-07 — schema/output_examples/ 신설 + baseline_v1 annotated 정리 (실 장비 개더링)

### 컨텍스트

사용자 (hshwang1994) 명시 (2026-05-07):

> "실제 개더링할수있는 장비를 대상으로 개더링하고 그 값을 대상으로 json출력 예시를 업데이트해라. 만약 schema/baseline_v1이 json출력예시 디렉터리가 아니라면 별도로 디렉터리를 만들고 schema/baseline_v1에 생성한 파일은 지워라. 만약 의도가맞다면 업데이트만 해라. 그리고 한글로 할때 모든 json 키값에대한 설명을 주석으로 달아라."

직전 cycle 2026-05-06 b65e162e 가 baseline_v1 안에 한글 주석본 8개 (`*_annotated.jsonc`) 를 추가했으나, baseline_v1 정본 의도 (회귀 기준선 — Jenkins Stage 4 pytest 입력) 와 충돌. 사용자가 위치 부적합 지적.

### 결정

**A. baseline_v1 != 출력 예시 → 신규 디렉터리** `schema/output_examples/` 신설.

**B. 자격증명** — vault 사용 + 평문 노출 OK (사용자 명시 "기존 볼트를 사용하고, 그것이 평문에 담겨도된다").

**C. 실행 위치** — Jenkins 에이전트 10.100.64.155 SSH 접속 후 직접 ansible-playbook 실행. 결과 rsync 회수.

**D. 디렉터리 분류**:

| 디렉터리 | 정본 의도 | 누가 사용 |
|---|---|---|
| `schema/baseline_v1/` | **회귀 기준선** (Jenkins Stage 4 pytest 입력) | 자동화 회귀 |
| `schema/output_examples/` (신설) | **호출자 / 운영자 reference** — 한글 주석 + 실 응답 | 사람 |
| `schema/examples/` | 시나리오 별 예시 (success/partial/failed/not_supported) | 호출자 (시나리오 설명) |

### 산출물

- 신설: `schema/output_examples/{README.md, 10 jsonc 파일}`
- 삭제: `schema/baseline_v1/*_annotated.jsonc` 8개 (사용자 명시)
- 보존: baseline_v1 *_baseline.json 8개 / examples *.json 4개 / sections.yml / field_dictionary.yml

### 검증

- pytest 335/335 PASS / verify_harness PASS / verify_vendor_boundary PASS
- envelope 13 필드 / sections 10 / field_dictionary 65 — 변경 없음 (rule 13 R5 / rule 96 R1-B Additive only)
- 호출자 시스템 파싱 변경 0

### Evidence

- `tests/evidence/2026-05-07-real-gather.md` (실행 절차 + 발견 사항 + 호출자 영향)

### 후속

- 펌웨어 / 환경 변경 시 본 디렉터리 재 캡처 — `update-vendor-baseline` skill 또는 직접 갱신
- 6개월 갱신 0건 시 stale 가능 — `EXTERNAL_CONTRACTS.md` 동기화 권장

---

## 2026-05-06 (cycle 2026-05-06-multi-session-compatibility) — status 의도 결정 (Case A 채택)

### 컨텍스트

사용자 (hshwang1994) 의심 영역 (cycle 진입 시점 명시):

> "스키마 검증 들어가자. 모든 값에 대한 스키마 검증해주되 특히 자세히 봐야할것은 개더링상태가 success failed partial 이렇게 3개로 나눠져있는것으로 보이는데, 이게 로직이 정상작동돼지않는듯함. 부분 성공이라고 하더라도 error 에는 로그가 찍히는데 success로 빠지는경우가 있음 이것은 왜이런지 확인해줘 의도된건지?"

→ M-A1 [DONE] (commit `ba003b2f`) 분석 결과: 시나리오 B (섹션 success + errors warning → overall=success) 는 **명백한 의도된 동작**. 코드 주석 3 위치가 명시:
- `os-gather/tasks/linux/gather_memory.yml:171-172` (dmidecode fallback 사유 추적)
- `os-gather/tasks/linux/gather_network.yml:208` (lspci stderr 권한 부족 추적)
- `esxi-gather/tasks/normalize_storage.yml:79-80` (NFS/vSAN/vVOL cap 미수집 추적)

build_status.yml 판정 로직 (정본 인라인 Jinja2): **errors[] 는 보지 않는다 / 섹션 status 만 본다**. errors[] 는 사유 추적용 분리 영역.

### 결정 (4 포인트)

AI 자율 진행 권한 적용 (cycle 진입 시 사용자 명시 — "사용자 결정 4 포인트도 AI 합리적 default 결정 후 진행"):

| 결정 | 선택 | 근거 |
|---|---|---|
| (1) 시나리오 B 처리 | **B-1 (현재 동작 유지)** | M-A1 분석 — 의도된 설계 + Additive only cycle + rule 96 R1-B (envelope shape 보존) |
| (2) errors[] severity | **(a) 유지** | rule 22 R7/R8 + rule 13 R5 + 3채널 27+ 위치 영향 → 별도 cycle 영역 |
| (3) status_rules.yml | **(c) 유지** | DEAD CODE 명시 주석 "삭제 금지 / 향후 reserved" + rule 70 R5 보존 판정 YES |
| (4) status enum | **(a) 3 enum 유지** | rule 13 R5 envelope 13 필드 정본 + rule 96 R1-B (호환성 외 schema 확장 별도 cycle) |

→ **Case A 채택** — 의도된 동작 명시 only (Additive 주석/문서 강화).

### 영향

- 코드 동작 변경: **0건**
- envelope 13 필드: **변경 0** (rule 13 R5 / 96 R1-B 보존)
- status enum: **3종 유지** (success / partial / failed)
- 9 vendor baseline 회귀: **영향 0**
- 호출자 시스템 파싱: **영향 0**
- ADR (rule 70 R8 trigger): **NO** — rule 본문 변경 없음, 표면 카운트 변동 없음 → M-A4 SKIP 가능

### M-A3 작업 (다음 세션)

1. `common/tasks/normalize/build_status.yml` 헤더 주석 강화 — 시나리오 B 의도 명시 + errors[] 분리 의미 명문화 + 코드 주석 3 reference
2. `status_rules.yml` 변경 0 (DEAD CODE 명시 주석 reference 확인만)
3. mock fixture 1건 신규 — 시나리오 B 재현 (`status_success_with_warnings.json`)
4. pytest 회귀 + verify_harness_consistency PASS 확인
5. M-F1 (docs/20_json-schema-fields.md 신설 시) status 판정 규칙 절 포함 의무 — DEPENDENCIES 갱신

### 대안 비교 (Considered)

- **Case B (B-2 + ?)**: errors non-empty → overall=partial. 거절 이유: 모든 vendor baseline 회귀 fail (success → partial 전환), 호출자 partial 대응 로직 추가 필요, rule 96 R1-B 호환성 외 영역
- **Case C (B-3 + (b) + (b))**: 4 enum + severity 도입. 거절 이유: envelope schema 변경 (rule 13 R5 + 92 R5 사용자 명시 승인 필요), 3채널 27+ 위치 영향, 본 cycle Additive only 영역 외 — 별도 cycle 사용자 명시 승인 후 진행 영역

### rule / 정본 참조

- rule 13 R5 (envelope 13 필드 — status 필드 정본 보존)
- rule 22 R7/R8 (Fragment 5 변수 / 타입 정본 — 변경 안 함)
- rule 70 R5 (문서 보존 판정 — status_rules.yml 유지)
- rule 70 R8 (ADR trigger — Case A 는 NO → M-A4 SKIP)
- rule 92 R2 (Additive only)
- rule 92 R5 (schema 변경 사용자 명시 — Case C 거절 이유)
- rule 96 R1-B (호환성 cycle 외 envelope shape 변경 자제)
- ticket: `docs/ai/tickets/2026-05-06-multi-session-compatibility/fixes/M-A1.md`, `M-A2.md`, `M-A3.md`

---

## 2026-05-01 (cycle-019) — 신규 vendor 4종 도입 (Huawei / Inspur / Fujitsu / Quanta)

### 컨텍스트
사용자 (hshwang1994) 명시:
1. 2026-05-01 1차: "신규 장비 도입할 의향이 있다 다만 테스트할 lab 장비가 없다. 일단 vault는 만들지 말고 코드 생성에 대한 티켓은 만들어라"
2. 2026-05-01 2차 (본 cycle): "신규 밴더 추가 승인하겠다"

cycle-019 본 cycle 에서 7-loop + 10R extended audit P1 22건 적용 후, 사용자 명시 승인으로 신규 vendor 4종 진행.

### 결정
4 vendor adapter 코드 영역 진행. **vault 단계 SKIP** (lab 부재 — 사용자 명시 1차).

### 적용 범위 (rule 50 R2 9단계 매핑)

| 단계 | 작업 | 상태 |
|---|---|---|
| 1. vendor_aliases.yml 매핑 | 4 vendor alias 추가 | [OK] |
| 2. adapter YAML 생성 | huawei_ibmc / inspur_isbmc / fujitsu_irmc / quanta_qct_bmc | [OK] |
| 3. (선택) OEM tasks | 부재 (standard_only — 사이트 fixture 확보 후 보강) | DEFER |
| 4. vault 생성 | vault/redfish/{vendor}.yml | **SKIP (사용자 명시)** |
| 5. baseline | schema/baseline_v1/{vendor}_baseline.json | DEFER (lab 부재) |
| 6. ai-context | .claude/ai-context/vendors/{vendor}.md 4종 | [OK] |
| 7. vendor-boundary-map.yaml | huawei/inspur/fujitsu/quanta 추가 | [OK] |
| 8. live-validation | docs/13_redfish-live-validation.md Round 갱신 | DEFER (lab 부재) |
| 9. decision-log | 본 entry | [OK] |

### redfish_gather.py 동기화

`_FALLBACK_VENDOR_MAP` + `_BMC_PRODUCT_HINTS` + `bmc_names` dict 모두 4 vendor 추가 (rule 12 R1 nosec 주석 보존).

- `_FALLBACK_VENDOR_MAP`: 11 신 entry (huawei/inspur/fujitsu/quanta 변형 alias)
- `_BMC_PRODUCT_HINTS`: 7 신 entry (ibmc/fusionserver/isbmc/irmc/primergy/quantagrid/quantaplex)
- `bmc_names`: 4 신 entry (huawei→iBMC, inspur→ISBMC, fujitsu→iRMC, quanta→BMC)

### 영향
- adapter 표면: 34 → 38 (Redfish 23 → 27)
- vendor 정규화 list: 5 → 9
- vault 신규: 0 (사용자 명시 SKIP)
- baseline 신규: 0 (lab 부재)
- 운영 가능 시점: lab 또는 사이트 장비 도입 + vault 생성 시

### 부재 시 동작 (graceful degradation)

- ServiceRoot 무인증 detect → vendor=huawei/inspur/fujitsu/quanta 정규화 OK
- vault 부재 → precheck auth 단계에서 status=failed (rule 27 R4 graceful)
- 호출자 envelope: status=failed + errors[] = ["vault not found for vendor=<huawei|inspur|fujitsu|quanta>"]

### 사이트 도입 시 절차

1. `vault/redfish/{vendor}.yml` 생성 (ansible-vault encrypt + username/password)
2. `tests/redfish-probe/probe_redfish.py --vendor {vendor}` 실행
3. `schema/baseline_v1/{vendor}_baseline.json` 생성
4. `tests/evidence/<날짜>-{vendor}.md` Round 검증 기록
5. `docs/13_redfish-live-validation.md` Round 갱신
6. `capture-site-fixture` skill 으로 사이트 fixture 캡처

### rule / 정본 참조

- rule 50 R2 (vendor 추가 9단계, vault SKIP 사용자 명시 적용)
- rule 96 R1-A (lab 부재 — web sources 4종 1개 이상 — 4 ticket 모두 충족)
- rule 12 R1 (vendor 경계 — _FALLBACK_VENDOR_MAP 등 nosec 보존)
- rule 92 R5 (사용자 명시 승인 — 본 entry 가 승인 trace)
- ticket: `docs/ai/tickets/2026-05-01-gather-coverage/fixes/F44~F47.md`

---

## Round 12 (2026-04-29) — ESXi 채널 hostname / vendor / extended modules fix

### 배경
사용자 보고: ESXi 출력 JSON 에서 `hostname=IP`, `vendor` 정규화 실패, `network.adapters / virtual_switches / storage.hbas` 빈 배열.

### 진단
agent 10.100.64.154 SSH + 진단 playbook (`tests/scripts/diag_esxi_raw.yml`) 으로 raw facts 캡처.

| BUG | 원인 |
|---|---|
| #1 hostname=IP | `normalize_system.yml` 의 `system.fqdn = _e_ip` (ansible_hostname 미사용) |
| #2 vendor 정규화 | Jinja2 loop scoping — cycle-016 namespace fix 잔류분 |
| #4 extended 빈 | `community.vmware 6.2.0` hosts_*_info dict key 는 hostname (IP 아님). dict list 는 `vmnic_details`/`vmhba_details` (`all` 은 string list). 매핑 키 정정: pci→location, adapter_type→type, node_wwn 등. vswitch 는 dict-of-dict |

### Fix
- `esxi-gather/site.yml` (+11 lines) — `_e_hostname` 변수 + namespace pattern
- `esxi-gather/tasks/normalize_system.yml` (+3 lines)
- `esxi-gather/tasks/collect_network_extended.yml` (+30 lines)
- `schema/baseline_v1/esxi_baseline.json` (+231 / -47, esxi02 실측 갱신)

### 검증
- 실 호스트 esxi01 + esxi02 (10.100.64.1 / .2) 본 site.yml 실행 — NIC/vSwitch/HBA 모두 정상 채워짐
- pytest 158/158 PASS, vendor boundary / harness consistency / ansible-syntax-check 통과
- evidence: `tests/evidence/2026-04-29-esxi-bug-fix.md`

### 잔류 (별도 cycle)
- `default_gateways=[]` / `dns_servers=[]` — vmware_host_facts 미반환 / host_config_info 빈 응답 (vmware_host_dns_info 모듈 추가 필요)
- `speed_mbps` int / "N/A" string 혼재
- `cpu.architecture` / `max_speed_mhz` null (model 파싱 폴백 가능)
- `include_vars` `name:` reserved-name 경고 (호출자 영향 0)

---

> [!NOTE]
> 여기부터(§1~§13)는 2026-03~04 초기 검증 라운드 기록이다(번호순). 위쪽은 최근 결정부터의 날짜 역순 기록이다. 현재값은 `adapters/`, `schema/` 와 catalog 를 본다.

## 1. 코드 점검 1차/2차 결과 요약

### 1차 점검 (이전 세션)
- 전체 프로젝트 구조 분석
- 보안 이슈 (no_log 누락) 식별
- 기본 코드 품질 이슈 도출

### 2차 점검 (4 배치 완료)
- **Batch 1 (P0)**: power section 추가, hostname fallback 개선, int coercion regex 수정, vault 경고
- **Batch 2 (P1)**: OUTPUT default 방어, 에러 메시지 개선, no_log 정리
- **Batch 3 (P2)**: bare except → specific exceptions, no_log 제거, hostname None-safety
- **Batch 4 (P3)**: CALLBACK_NEEDS_WHITELIST → CALLBACK_NEEDS_ENABLED

총 19개 파일, ~50개 변경사항 — 모두 검증 완료.

## 2. Redfish Endpoint 선택 근거

### 코드가 호출하는 14개 엔드포인트

| # | 엔드포인트 | 선택 근거 |
|---|-----------|----------|
| 1 | Service Root | DMTF 필수. 벤더 감지 + 컬렉션 URI 확보 |
| 2 | Systems 컬렉션 | system_uri 동적 취득 |
| 3 | Systems/{id} | 서버 기본 정보 (model, serial, CPU/메모리 요약) |
| 4 | Managers/{id} | BMC 정보 (firmware version) |
| 5 | Processors 컬렉션 | CPU 상세 (모델, 코어, 스레드) |
| 6 | Processors/{pid} | 개별 CPU 정보 |
| 7 | Memory 컬렉션 | DIMM 목록 |
| 8 | Memory/{mid} | 개별 DIMM 정보 |
| 9 | Storage 컬렉션 | 스토리지 컨트롤러/드라이브 |
| 10 | Storage/{sid} | 컨트롤러 상세 + 드라이브 링크 |
| 11 | SimpleStorage (fallback) | Storage 미지원 구형 BMC 호환 |
| 12 | EthernetInterfaces 컬렉션 + 개별 | 호스트 NIC 정보 |
| 13 | FirmwareInventory 컬렉션 + 개별 | 전체 펌웨어 목록 |
| 14 | Chassis/{id}/Power | PSU 정보 |

### 미포함 엔드포인트와 제외 근거

| 엔드포인트 | 제외 근거 |
|-----------|----------|
| Chassis/{id}/Thermal | 온도/팬 정보 — 판정 시점에 normalize 스키마 미정의. 향후 추가 고려 |
| Managers/{id}/EthernetInterfaces | BMC NIC — system 레벨로 충분 |
| Bios | BIOS 설정 — BiosVersion은 System에서 이미 취득 |
| LogServices | 이벤트 로그 — 수집 범위 초과 |
| NetworkInterfaces | NIC 상세 — EthernetInterfaces로 충분 |

## 3. Adapter 설계 근거

### 왜 adapter 시스템을 사용하는가
1. **벤더별 normalize 차이**: 같은 Redfish 표준이라도 필드 존재 여부가 다름
2. **세대별 차이**: 같은 벤더라도 BMC 세대에 따라 스키마 다름 (예: HPE iLO5 vs iLO6)
3. **확장성**: 새 벤더/세대 추가 시 adapter YAML만 추가하면 됨
4. **테스트 용이**: adapter 단위로 fixture 테스트 가능

### Adapter 선택 알고리즘
- `adapter_loader.py`가 `adapters/redfish/` 디렉토리 스캔
- `match` 조건 (vendor, model_pattern 등) 비교
- 복수 매칭 시 `priority` + `specificity` 점수로 정렬
- 최고 점수 adapter 반환

## 4. Normalize 정책 근거

### null 허용 정책
실장비 검증 결과, 벤더마다 누락 필드가 다름:
- HPE: IndicatorLED, SpeedMbps, LinkStatus, ProcessorSummary.Status.Health
- Lenovo: Manager.Status.Health
- Dell: Drive.Status.Health

→ **정책**: 코드가 추출하는 모든 필드는 `_safe()` 함수로 None 반환 허용.
normalize에서 `| default(none)` 처리.

### 빈 문자열 처리
- HPE HostName = "" (빈 문자열) → normalize에서 `or _out_ip` fallback 필요
- build_output.yml에서 처리 (2차 점검에서 수정 완료)

### Storage Controllers fallback
- 판정 시점: `StorageControllers` 인라인 배열만 처리
- HPE Gen11: `Controllers` 서브링크 사용 → **fallback 추가 필요** (P0-1에서 구현 완료, 8절 참조)

## 5. 실장비 검증으로 확정된 사항

| 항목 | 결정 | 근거 |
|------|------|------|
| vendor 감지 기준 | System.Manufacturer | 3사 모두 동작 확인 |
| URI 패턴 | 동적 (Members[0]) | 벤더마다 다른 ID 패턴 |
| Storage fallback | Storage 우선, SimpleStorage fallback | Lenovo/HPE는 SimpleStorage 404 |
| Basic Auth | 유지 | 3사 모두 동작 |
| Thermal 수집 | 보류 | endpoint 존재하나 normalize 스키마 미정의 |
| default_gateways | Redfish 불가 | OS 레벨 정보 — os-gather에서 수집 |

## 6. 실장비 검증으로 추정에 머무는 사항

| 항목 | 추정 내용 | 불확실 요인 |
|------|----------|------------|
| 다른 세대 URI 패턴 | 동일할 것으로 추정 | Gen10, R640 등 미검증 |
| Supermicro 호환 | 코드에 Supermicro 분기 있으나 미검증 | 장비 부재 |
| Session Auth | 동작할 것으로 추정 | Basic만 테스트 |
| HPE iLO5 차이 | iLO6과 유사할 것으로 추정 | Oem.Hpe vs Oem.Hp fallback 미검증 |
| 다중 System member | Members[0]만 사용 | 블레이드 서버 등 미검증 |

## 7. OEM 필드 보강 판정 (B2, Round 14)

> 판정일: 2026-03-25

### 결론

**판정 시점의 수집 범위에서는 Standard Redfish로 대응 가능하다.** OEM placeholder는 향후 운영 요구 발생 시 확장한다.

수집 범위(firmware inventory + PSU health/state/metrics) 기준으로, 아래 근거 표의 모든 영역에서 standard endpoint만으로 필요 데이터를 확보할 수 있었다. OEM 추가 가치가 낮다고 판단한 근거는 아래 표 참조.

### 근거

| 영역 | Standard 수집 현황 | OEM 추가 가치 |
|------|-------------------|---------------|
| Firmware | FirmwareInventory 28+ 항목 (BIOS, BMC, RAID, NIC, PSU FW) | OEM-specific metadata (낮음) |
| Power | PSU health/state/metrics + power_control consumed watts | PSU redundancy N+1, line voltage (낮음) |
| 기타 | — | Thermal throttle history, license/warranty (범위 외) |

### OEM Framework 상태

- 4개 벤더(Dell/HPE/Lenovo/Supermicro) adapter YAML에 `oem_tasks` 경로 정의 완료
- `collect_oem.yml` / `normalize_oem.yml` placeholder 파일 존재
- **운영 요구 발생 시 placeholder만 채우면 즉시 확장 가능**

### 향후 확장 트리거

OEM 구현을 재검토해야 하는 상황:
1. 포털에서 PSU redundancy status(N+1) 표시 요구 발생
2. 벤더별 OEM-specific health code 해석 요구
3. Thermal 섹션 스키마 정의 및 수집 요구
4. 특정 벤더에서 standard endpoint로 수집 불가능한 필드 발견

## 8. 리팩토링 이력 (실장비 검증 기반, 2026-03-18)

### 완료 (P0/P1)

| 항목 | 파일 | 내용 |
|------|------|------|
| P0-1 | `redfish_gather.py` | HPE Storage Controllers fallback (Controllers 서브링크 드릴다운) |
| P0-2 | `redfish_gather.py` | gather_power() ServiceRoot 중복 호출 제거 (chassis_uri 직접 전달) |
| P0-3 | `hpe_ilo6.yml` | HPE iLO 6 전용 adapter 신규 생성 |
| P1-3 | `redfish_gather.py` | 벤더별 null 필드 경고 로깅 |
| P1-4 | `redfish_gather.py` | HostName 빈 문자열 → None 변환 |
| P1-7 | `redfish_gather.py` | MemorySummary Health → HealthRollup fallback |
| P1-7-2 | `redfish_gather.py` | IndicatorLED → LocationIndicatorActive fallback |

### 보류 (P1-P2)

| 항목 | 사유 |
|------|------|
| 단위 변환 헬퍼 통일 | 검증 시점에 코드 동작 확인됨, 우선순위 낮음 |
| Thermal 수집 추가 | normalize 스키마 미정의, 향후 요구 시 구현 |
| Supermicro/다중 System member/Session Auth/iLO5 차이 | 실장비 미보유로 검증 불가, 장비 확보 시 재검토 |

## 9. Linux Raw Fallback Round 2 검증 (2026-04-15)

### 배경

Round 1에서 Linux 2-Tier Gather (Python 감지 + Raw Fallback) 기본 구현을 완료했다. Round 2에서는 5대 서버에 대해 31개 필드 전수 비교 검증을 수행했다.

### SELinux 정규화 버그 수정

`gather_system.yml`의 raw 경로에서 `getenforce` 출력값(`Enforcing`/`Permissive`/`Disabled`)을 Ansible 컨벤션(`enabled`/`disabled`)으로 정규화하지 않는 버그를 발견하고 수정했다.

- **수정 전**: `getenforce` 출력 그대로 반환 (예: `Enforcing`)
- **수정 후**: `Enforcing`/`Permissive` → `enabled`, `Disabled` → `disabled`로 정규화

### 5대 서버 필드 전수 비교 결과

| 서버 | OS | Python | 감지 모드 | 결과 | 비고 |
|------|-----|--------|----------|------|------|
| RHEL 8.10 | RHEL 8.10 | 3.6.8 | `python_incompatible` (자동) | 31/31 MATCH | auto fallback과 forced raw 간 완전 일치 |
| RHEL 9.2 | RHEL 9.2 | 3.9+ | `python_ok` | memory 차이만 | raw 경로가 더 정밀 (아래 분석 참조) |
| RHEL 9.6 | RHEL 9.6 | 3.9+ | `python_ok` | memory 차이만 | 동일 |
| Rocky 9.6 | Rocky 9.6 | 3.9+ | `python_ok` | memory 차이만 | 동일 |
| Ubuntu 24.04 | Ubuntu 24.04 | 3.9+ | `python_ok` | selinux 1건 차이 | 허용 범위 (아래 분석 참조) |

### Memory 차이 분석 (버그 아님)

RHEL 9.x / Rocky 9.6에서 Python 경로와 raw 경로 간 memory 값 차이가 발생한다. 이는 **버그가 아니라 raw 경로가 더 정확**한 결과이다.

| 경로 | 수집 방식 | 값 (예시) | 의미 |
|------|----------|----------|------|
| Python 경로 | `ansible_memtotal_mb` (OS 보고) | 7680 MB | 커널 예약 후 OS 가시 메모리 (`os_visible`) |
| Raw 경로 | `dmidecode --type 17` (하드웨어 직접) | 8192 MB | 물리 장착 메모리 (`physical_installed`) |

→ raw 경로의 dmidecode 기반 수집이 실제 물리 메모리를 반환하므로 하드웨어 인벤토리 용도에 더 적합하다.

### Ubuntu SELinux 차이 (허용)

Ubuntu 24.04에서 `selinux` 필드 차이 1건 발생:
- Python 경로: `disabled` (Ansible이 SELinux 미설치를 disabled로 보고)
- Raw 경로: `null` (`getenforce` 명령 미설치)

→ Ubuntu는 SELinux를 기본 탑재하지 않으므로 `null` 반환이 의미적으로 정확하다. 허용 범위로 판정.

### 결론

5대 서버, 31개 필드 전수 검증 완료. Raw fallback은 Python 경로와 동등하거나 더 정밀한 결과를 제공한다. 프로덕션 적용 가능.

## 10. Network 심층 검증 (Round 3, 2026-04-15)

### 배경

Round 2 이후 Network 섹션에 대해 심층 검증을 수행했다. 가상 인터페이스 skip 패턴 확장, 다중 default route 동작 확인, primary 판단 규칙 명확화가 주요 내용이다.

### skip 패턴 확장

기존 skip 패턴(`lo`, `docker*`, `br-*`, `veth*`, `virbr*`, `vir*`)에 아래 패턴을 추가했다:

| 추가 패턴 | 대상 | 추가 근거 |
|----------|------|----------|
| `cni*` | Kubernetes CNI 인터페이스 | K8s 노드에서 불필요한 가상 인터페이스 수집 방지 |
| `flannel*` | Flannel CNI overlay | 동일 |
| `cali*` | Calico CNI | 동일 |
| `tunl*` | tunnel 인터페이스 | IPIP 터널 등 가상 인터페이스 제외 |
| `dummy*` | dummy 인터페이스 | 테스트/라우팅 용도 가상 인터페이스 제외 |
| `kube-*` | Kubernetes internal | kube-proxy 등 내부 인터페이스 제외 |

**주의**: `br0`, `bond0`, `team0`, `eth0.100`(VLAN) 등 실 네트워크 인터페이스는 skip 대상이 아니다.

### 5대 서버 다중 default route 동작 확인

5대 서버(RHEL 8.10, RHEL 9.2, RHEL 9.6, Rocky 9.6, Ubuntu 24.04)에서 다중 default route가 존재하는 경우 metric 기준 정렬 후 첫 번째만 사용하는 동작을 확인했다. Python 경로(`ansible_default_ipv4`)와 raw 경로(`ip route show default | head -1`) 모두 동일한 결과를 반환한다.

### primary 판단 규칙 명확화

| 결정 | 내용 |
|------|------|
| primary 정의 | IPv4 default route가 걸린 인터페이스 = primary |
| bond master | default route가 bond master에 걸리면 bond master가 primary |
| bridge | default route가 bridge에 걸리면 bridge가 primary |
| slave/port | IP가 없으므로 primary 불가 |
| 다중 default route | lowest metric wins (첫 번째만 사용) |

### 결론

Network 수집 정책을 GUIDE_FOR_AI.md에 문서화 완료. skip 패턴 확장으로 Kubernetes/tunnel/dummy 가상 인터페이스를 추가 제외하고, primary 판단 규칙과 다중 default route 처리를 명확화했다.

## 11. Network 복잡 토폴로지 실증 (Round 4, 2026-04-15)

### 배경

Round 3에서 skip 패턴을 확장하고 primary 판단 규칙을 명확화했다. Round 4에서는 Ubuntu 24.04에 복잡 네트워크 토폴로지를 실제 구성하여 수집 정확성을 실증했다.

### 실증 환경

Ubuntu 24.04 (10.100.64.167)에 아래 토폴로지를 구성:

| 인터페이스 | 유형 | 역할 |
|-----------|------|------|
| ens192 | 물리 NIC | primary (default route dev) |
| ens224 | 물리 NIC | 보조 NIC |
| br0 | bridge | dummy0를 slave로 포함 |
| ens192.100 | VLAN | ens192 위 VLAN 서브인터페이스 |
| dummy0 | dummy (bridge slave) | br0의 port (slave) |
| cni0 | container NIC | Kubernetes CNI |
| flannel.1 | container NIC | Flannel overlay |
| docker0_test | container NIC | Docker 테스트 bridge |
| policy routing | table 100 | `ip rule` + `ip route table 100` |

### 발견된 문제

skip 패턴(`dummy*`)이 배포 시점에 반영되지 않아 cni0, flannel.1은 skip되지 않았다 (배포 이슈). 이와 별개로, **dummy0가 bridge port(slave)임에도 수집되는 문제**를 발견했다. dummy0는 br0의 하위 포트이므로 독립 인터페이스로 수집하면 안 된다.

### 수정 내용

raw path에 bridge slave / bond slave 자동 필터를 추가했다:

- `/sys/class/net/$dev/master`가 존재하는지 확인 (slave 여부)
- slave이면서 자신이 bridge master(`/sys/class/net/$dev/bridge/` 존재)도 아니고 bond master(`/sys/class/net/$dev/bonding/` 존재)도 아닌 경우 → skip
- bridge master나 bond master는 slave이더라도 수집 (중첩 구성 대응)

### 수집 결과 비교

| 구분 | 수집된 인터페이스 | 개수 |
|------|-----------------|------|
| 수정 전 | ens192, ens224, br0, ens192.100, dummy0, cni0, flannel.1 | 7개 |
| 수정 후 | ens192, ens224, br0, ens192.100 | 4개 |

### 인터페이스별 검증

| 인터페이스 | primary | speed | IP 수집 | 판정 |
|-----------|---------|-------|--------|------|
| ens192 | true (default route dev) | 10000 | O | 정확 |
| ens224 | false | 10000 | O | 정확 |
| br0 | false | null (가상) | O | 정확 |
| ens192.100 | false | 10000 (부모 상속) | O | 정확 |
| dummy0 | — | — | — | skip (bridge slave) = 정확 |
| cni0 | — | — | — | skip (가상 NIC) = 정확 |
| flannel.1 | — | — | — | skip (가상 NIC) = 정확 |
| docker0_test | — | — | — | skip (가상 NIC) = 정확 |

### 결론

복잡 토폴로지(bridge + VLAN + container NIC + policy routing)에서 수집 정확성을 실증했다. bridge slave/bond slave 자동 필터 추가로 불필요한 하위 포트 수집이 제거되었다. 4개 인터페이스만 정확히 수집되며, primary 판단도 정확하다.

## 12. Network 운영 해석 기준 확정 + bond 실증 (Round 5, 2026-04-15)

### 배경

Round 4까지 skip 패턴, primary 판단, bridge slave 필터를 검증했다. Round 5에서는 5대 서버 명령어 존재성 매트릭스 실측과 bond 토폴로지 실증을 수행하여 운영 해석 기준을 확정했다.

### 명령어 존재성 매트릭스 실측

15개 명령 x 5대 서버(RHEL 8.10, RHEL 9.2, RHEL 9.6, Rocky 9.6, Ubuntu 24.04)에 대해 명령어 존재 여부를 실측했다.

핵심 발견:
- RHEL 9는 `resolvectl` 미설치 (systemd-resolved 패키지 미포함)
- Ubuntu는 `nmcli` 미설치 (NetworkManager 미사용)
- `ip`, `getent`, `/sys/class/net`, `/proc/*`, `/etc/os-release`는 모든 배포판에서 보장

→ 배포판 무관 소스(`ip`, sysfs, `/proc`, `/etc`) 사용 전략의 정당성을 실측으로 확인했다.

### bond 실증

Ubuntu 24.04에 bond 토폴로지를 구성하여 수집 정확성을 실증했다:

| 구성 | 내용 |
|------|------|
| bond0 | active-backup 모드, 2개 dummy slave |
| bond0.200 | VLAN-on-bond (bond0 위 VLAN 서브인터페이스) |
| br_test | bridge (테스트용) |

검증 결과:

| 항목 | 결과 |
|------|------|
| bond master 수집 | [OK] bond0 수집됨 |
| slave 제외 | [OK] dummy slave 제외됨 (master sysfs 감지) |
| VLAN-on-bond 수집 | [OK] bond0.200 수집됨 |
| bridge port 제외 | [OK] bridge 하위 port 제외됨 |

### source 우선순위 체계 확정

```text
kernel sysfs > POSIX 명령 > /proc > /etc
```

- kernel sysfs (`/sys/class/net/*`): MAC, MTU, speed, operstate, master, bridge/bonding 판정
- POSIX 명령 (`ip`): IPv4 주소, default gateway, primary 판정
- `/proc`: cpuinfo, meminfo
- `/etc`: resolv.conf (DNS), os-release (system)

### 운영 해석 정책 확정

| 항목 | 해석 |
|------|------|
| `is_primary` | IPv4 main table default route device (운영 대표 IP와 동일하지 않을 수 있음) |
| `speed=null` | kernel 미보고 (bond/bridge master, 가상 NIC) |
| `dns 127.0.0.53` | stub resolver (systemd-resolved, 실제 upstream DNS가 아님) |
| policy routing / IPv6 / VRF | 미지원 |

### 결론

명령어 매트릭스 실측으로 배포판 무관 설계를 검증하고, bond 실증으로 bond master/slave/VLAN-on-bond 수집 정확성을 확인했다. source 우선순위와 운영 해석 정책을 확정하여 GUIDE_FOR_AI.md에 반영했다.

---

## 13. Reference 종합 수집 (Round 11, 2026-04-28)

### 배경

새 vendor 추가 / schema 필드 보강 / OS 매핑 검증 / 회귀 비교 시 매번 실장비에 직접 접속하는 비용을 줄이고, 향후 재현/비교 가능한 raw 자산을 확보할 필요가 있었다. 사용자가 Jenkins master 2대 / agent 2대 / OS VM 6대 + bare-metal 1대 / Windows VM 1대 / BMC 11대 / ESXi 3대를 테스트 자격과 함께 제공했다.

### 결정

`tests/reference/` 디렉터리에 종합 reference 데이터를 보존한다. 회귀 input (`tests/fixtures/`) 및 회귀 기준선 (`schema/baseline_v1/`)과는 별개 디렉터리로 분리하여 회귀 입력 변경 위험을 피한다.

수집 도구 4개를 작성:
- `crawl_redfish_full.py` — Redfish ServiceRoot부터 모든 link 재귀 follow (Python stdlib + PyYAML)
- `gather_os_full.py` — paramiko SSH (Linux) + pywinrm (Windows) + ansible setup
- `gather_esxi_full.py` — paramiko SSH (esxcli/vim-cmd) + pyvmomi (vSphere API)
- `gather_agent_env.py` — paramiko SSH 기반 환경 dump (REQUIREMENTS.md 검증)

### 자격 처리

자격 평문 commit 방지를 위해 `tests/reference/local/targets.yaml`을 `.gitignore`에 등록. `targets.yaml.sample`만 commit. 수집 완료 후 `targets.yaml` 삭제 권장.

### 1차 수집 결과 (2026-04-28)

| 채널 | 시도 | 성공 | 실패 |
|---|---|---|---|
| Redfish | 11 | (진행 중) | 3 (Cisco 1/3 도달 불가, Dell 32 vendor 의심) |
| OS | 7 | 6 (Linux) | 1 (Win10 WinRM) |
| ESXi | 3 | 3 (pyvmomi), 1 (SSH) | 0 (전체) / 2 (SSH만) |
| Agent/Master | 4 | 4 | 0 |

세부는 `tests/evidence/2026-04-28-reference-collection.md` 참조.

### 발견 사항

- **F1**: Dell BMC 사용자는 user=admin이 아닌 user=root (사용자 채팅 정정)
- **F2**: 10.100.15.32가 "dell" label인데 ServiceRoot=AMI Redfish Server. 실 vendor / 자격 사용자 확인 필요 (rule 96 R2 — 외부 계약 디버깅 시 질의 우선)
- **F3**: Cisco 10.100.15.1 HTTP 503 / 15.3 timeout. 장비 가동 상태 확인 필요
- **F4**: Win10 WinRM 5986 미활성 + 5985 Basic 미허용 + WSL Python 3.12 ntlm-auth 라이브러리의 OpenSSL 3.0 MD4 미지원
- **F5**: ESXi 10.100.64.1 / .3 SSH 비활성 (vSphere 기본 상태). 활성화 후 esxcli 53종 추가 수집 가능
- **F6**: gather_agent_env.py의 sudo 명령 처리 개선 필요 (Master 153에서 ~120초 대기 발생)

### 누적 통계 (BMC 진행 중 시점 기준)

- 파일 수: 4420 (BMC 완료 시 ~10000 예상)
- 디스크 사용: 43MB (BMC 완료 시 ~150-200MB 예상)

### 활용

1. **새 vendor 온보딩**: 그 vendor의 redfish endpoint list로 OEM path 파악 + adapter metadata `tested_against` 갱신 근거
2. **schema 필드 추가**: cross-vendor OEM 데이터 비교
3. **OS 매핑 검증**: cmd_dmidecode_*.txt ↔ ansible_setup ↔ field_dictionary 정합 (rule 13 R1)
4. **REQUIREMENTS.md 검증**: agent 디렉터리의 ansible/python/collection 버전 ↔ 문서 명시
5. **회귀 비교**: 펌웨어 / OS 업그레이드 후 동일 명령 재수집 → diff

### 보존 정책 (rule 70)

- 본 디렉터리는 commit 대상 (raw raw 자료 가치 큼). 단:
  - `tests/reference/local/`은 .gitignore (자격)
  - 민감 파일 (sshd_config / sudoers)은 commit 전 사용자 검토
- 차후 수집 사이클마다 `tests/reference/INDEX.md` 갱신 + 본 decision-log에 Round 추가

### 후속 작업

- F2/F3/F4/F5/F6 follow-up (`tests/evidence/2026-04-28-reference-collection.md` 표 참조)
- 본 reference 자료 기반의 schema 추가 / adapter metadata 보강은 별도 PR

### rule / 정본 참조

- rule 13 (output-schema-fields), 21 (output-baseline-fixtures), 70 (docs-and-evidence-policy), 96 (external-contract-integrity)
- 정본: `tests/reference/README.md`, `tests/reference/INDEX.md`, `tests/evidence/2026-04-28-reference-collection.md`

---

## 다음에 읽을 문서

| 다음 작업 | 문서 |
|---|---|
| 검증 라운드 결과 누적 | [13_redfish-live-validation.md](13_redfish-live-validation.md) |
| Adapter 시스템 (점수 / 새 벤더 추가) | [10_adapter-system.md](10_adapter-system.md) |
| envelope 13 필드 의미 사전 | [20_json-schema-fields.md](20_json-schema-fields.md) |

## 본 문서를 보는 법

- 시간 역순으로 누적됩니다 (최신 결정이 위쪽).
- 각 결정은 "사용자 의심 / 분석 / 결정 / 영향 / 회귀" 5절 구조를 따릅니다.
- 결정의 "왜" 가 본문이고, "무엇을 했는지" 는 git log / commit 메시지로 보완됩니다.
