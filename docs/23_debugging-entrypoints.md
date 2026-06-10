# 23. 디버깅 진입점 (Debugging Entrypoints)

> 호출자 / Jenkins / Ansible / 외부 시스템 어디에서 무엇이 깨졌는지 1분 안에 추적할 수 있는 진입점 카탈로그.

## 0. 요약 매트릭스 — Stage / Section 별 진입 파일

| 사고 시점 | 1차 확인 파일 | 2차 확인 |
|---|---|---|
| Jenkins Stage 1 (Validate) 실패 | `Jenkinsfile` 74~126 line | console log 의 `--validate-input` 결과 |
| Jenkins Stage 2 (Gather) 실패 | `os-gather/site.yml` 또는 채널별 site.yml | ansible -vvv 로그 |
| Jenkins Stage 3 (Validate Schema) 실패 | `tests/validate_field_dictionary.py` | `schema/field_dictionary.yml` |
| Jenkins Stage 4 (E2E Regression) 실패 | `tests/e2e/` pytest 출력 | 영향 vendor `schema/baseline_v1/` |
| envelope 13 필드 일부 누락 | `common/tasks/normalize/build_output.yml` | `init_fragments.yml` skeleton |
| 섹션 status 잘못됨 | `common/tasks/normalize/build_status.yml` (4 시나리오) | `build_sections.yml` |
| hostname=IP 표시 (의도된 fallback) | `build_output.yml:31-33` | docs/20 fallback chain |
| vendor 미정규화 (예: `Cisco Systems Inc`) | `common/vars/vendor_aliases.yml` | `module_utils/adapter_common.py:normalize_vendor` |
| adapter 잘못 선택 | `lookup_plugins/adapter_loader.py` -vvv 로그 | `adapters/{channel}/*.yml` priority |
| Redfish endpoint 응답 파싱 실패 | `redfish-gather/library/redfish_gather.py` 의 `gather_*` 함수 | -vvv + `tests/redfish-probe/probe_redfish.py` |
| Linux gather 부분 실패 | `os-gather/tasks/linux/gather_*.yml` | `_l_python_mode` (preflight.yml) |
| Windows gather 부분 실패 | `os-gather/tasks/windows/gather_*.yml` | WinRM debug — pywinrm |
| ESXi gather 부분 실패 | `esxi-gather/tasks/collect_*.yml + normalize_*.yml` | community.vmware 모듈 출력 |
| Precheck 4단계 어디서 막힘 | `common/library/precheck_bundle.py` + `diagnosis.details` | `diagnosis.failure_stage` / `failure_reason` |
| Vault 로딩 실패 | `redfish-gather/tasks/load_vault.yml` | `vault/redfish/{vendor}.yml` 존재 / 권한 |
| Callback 실패 | `Jenkinsfile_portal` post 단계 | `callback_plugins/json_only.py` + URL 정규화 |
| 회귀 사고 (A 고치고 B 깨짐) | `pytest tests/regression/` | `tests/regression/test_cross_channel_consistency.py` |

---

## 1. Jenkins 4-Stage 별 진입

### Stage 1 — Validate (입력값)

**역할**: loc / target_type / inventory_json 형식 검증.
**위치**: `Jenkinsfile:74~126`
**실패 시 확인**:
- console log 의 `[Stage 1 Validate] FAIL: ...` 메시지
- 입력 파라미터 형식 (JSON valid? IP 형식? loc enum?)

### Stage 2 — Gather (Ansible 실행)

**역할**: 채널별 site.yml 실행 (os/esxi/redfish).
**위치**:
- `os-gather/site.yml` (4-Play: detect/포트감지 → failed-output → Linux → Windows)
- `esxi-gather/site.yml` (1-Play, community.vmware)
- `redfish-gather/site.yml` (precheck → detect → adapter → collect → normalize)

**실패 시 확인**:
1. `ansible -vvv` 로그에서 어느 PLAY 어느 task 가 실패했는지
2. **fragment 침범 의심** → 각 gather 가 자기 fragment 변수만 set 하는지 점검
3. **vendor 분기 의심** → gather 코드에 vendor 이름 하드코딩이 없는지 점검 (분기는 adapter YAML / OEM tasks 안에서만)

### Stage 3 — Validate Schema (정합)

**역할**: envelope 13 필드 + sections 10 + field_dictionary 83 정합.
**위치**: `tests/validate_field_dictionary.py` (Jenkinsfile 193~203, Stage 'Validate Schema')
**실패 시 확인**:
- `schema/field_dictionary.yml` 갱신 누락 (sections.yml + field_dictionary.yml + baseline 3종 동반)
- `schema/sections.yml` 의 sections 10 정의 누락
- `common/tasks/normalize/build_output.yml` envelope 13 필드

### Stage 4 — E2E Regression / Callback (pipeline 별)

**역할**:
- `Jenkinsfile`: pytest baseline 회귀 (영향 vendor)
- `Jenkinsfile_portal`: 호출자 callback POST

**위치**: `tests/e2e/` + `tests/regression/` + `Jenkinsfile_portal:post`

**실패 시 확인**:
- pytest 출력 — 어느 baseline 어느 필드가 차이
- callback URL 무결성 — `Jenkinsfile_portal` post 단계 console log

---

## 2. Fragment 정규화 과정 별 진입

전체 처리 과정 (정본: `docs/07_normalize-flow.md`):

```text
init_fragments.yml (skeleton 초기화)
  ↓
gather_<section>.yml × N (각 gather 의 fragment 생성)
  ↓
merge_fragment.yml (각 gather 후 호출, fragment → 누적 변수 병합)
  ↓
build_sections.yml → _norm_sections (섹션별 status)
  ↓
build_status.yml → _out_status (4 시나리오 A/B/C/D)
  ↓
build_errors.yml → _norm_errors
  ↓
build_meta.yml → _meta
  ↓
build_correlation.yml → _correlation
  ↓
build_output.yml → _output (envelope 13 필드 — 정본)
  ↓
OUTPUT task → callback_plugins/json_only.py → stdout JSON
```

**섹션 누락 시**:
1. 해당 gather (`gather_<section>.yml`) 가 fragment 변수를 set 했는지
2. `merge_fragment.yml` 호출이 gather 후에 있는지
3. `build_sections.yml` 에서 `_sections_collected_fragment` 가 누적됐는지

**envelope 필드 누락 시**:
1. `build_output.yml` 본문 (정본) 13 필드 모두 정의 확인
2. `init_fragments.yml` skeleton 에 모든 sections 정의
3. `build_failed_output.yml` rescue 경로도 13 필드 emit 확인

---

## 3. Adapter 선택 디버깅

### -vvv 로그 활용

`ansible-playbook -vvv` 실행 시 `lookup_plugins/adapter_loader.py` 가 다음 로그 출력:

```text
adapter_loader: channel=redfish, facts vendor=Dell Inc., model=PowerEdge R760, firmware=6.10.30.20
adapter_loader: scanned 31 candidates from /repo/adapters/redfish
adapter_loader: dell_idrac9 matched score=100345 (priority=100×1000 + specificity=30×10 + match=45)
adapter_loader: dell_idrac matched score=10120 (priority=10×1000 + specificity=10×10 + match=20)
adapter_loader: redfish_generic matched score=-400 (priority=0×1000 + specificity=-40×10 + match=0 — generic 감점)
adapter_loader: 후보 거부 — 28건
  - hpe_ilo6 (match 조건 불일치)
  - lenovo_xcc3 (match 조건 불일치)
  ...
adapter_loader: top 3 candidates (score 내림차순):
  #1 dell_idrac9 score=100345
  #2 dell_idrac score=10120
  #3 redfish_generic score=-400
adapter_loader: 선택됨 — dell_idrac9 (score=100345) [score = priority×1000 + specificity×10 + match]
```

### 의도와 다른 adapter 선택 시

1. **점수 breakdown 확인** — priority / specificity / match_score 중 어느 것 때문인지
2. **adapter YAML priority 확인** (`adapters/{channel}/*.yml` priority 키)
3. **priority 정책표** (`docs/10_adapter-system.md` 참조):
   - generic = 0
   - vendor 기본 = 10
   - 세대별 = 80~100
   - 모델별 = 100~120
4. **점수 동률 시** — `-vvv` 로그에 동률 경고 출력. 동률 발견 시 priority/specificity 일관성 점검

### 점수 동률 사고

`adapter_loader._match_and_score` 가 stable sort 사용 → 동률 시 파일명 알파벳 오름차순 tie-break. 그러나 **동률 자체가 priority/specificity 일관성 위반 신호**.

---

## 4. envelope 13 필드 디버깅

**정본**: `common/tasks/normalize/build_output.yml`

| 필드 | 생성 위치 |
|---|---|
| `target_type` | site.yml 첫 set_fact (`_out_target_type`) |
| `collection_method` | site.yml 첫 set_fact (`_out_collection_method`) |
| `ip` | site.yml 첫 set_fact (`_out_ip`) — inventory `service_ip` / `bmc_ip` |
| `hostname` | `build_output.yml:31-33` fallback chain (system.hostname OR system.fqdn OR _out_ip) |
| `vendor` | site.yml 의 vendor 정규화 (vendor_aliases.yml) |
| `status` | `build_status.yml` 4 시나리오 |
| `sections` | `build_sections.yml` (10 sections × success/not_supported/failed) |
| `diagnosis` | site.yml success/rescue 에서 set (`_diagnosis`) |
| `meta` | `build_meta.yml` |
| `correlation` | `build_correlation.yml` |
| `errors` | `build_errors.yml` (`_norm_errors`) |
| `data` | merge_fragment.yml 누적 (`_merged_data`) |
| `schema_version` | 각 채널 `site.yml` 이 inject |

**필드 누락 사고 (fragment 침범 회귀)**:
- 회귀 테스트: `pytest tests/regression/test_cross_channel_consistency.py::test_envelope_thirteen_fields_present`

---

## 5. hostname=IP fallback 디버깅

**의도된 동작** — 버그 아님.

**fallback chain** (`build_output.yml:31-33`):
```yaml
hostname = (system.hostname OR system.fqdn) OR _out_ip
```

**의미**:
- `system.hostname` 우선 (Linux ansible_hostname / Windows / Redfish HostName / ESXi)
- 없으면 `system.fqdn` 사용 (FQDN 표기 환경)
- 둘 다 없으면 `_out_ip` 로 fallback (BMC HostName 미응답 / DMTF spec 권장)

**호출자가 hostname/IP 구분 필요 시**:
- 정확한 결정: 호출자가 envelope.hostname 과 envelope.ip 비교
  - hostname == ip → ip_fallback 발생 (BMC가 hostname 미응답)
  - hostname != ip → 정상 hostname/fqdn 응답
- 또는 `ansible-playbook -vvv` 로그에서 `_merged_data.system` 의 raw 값 확인

**docs/20** 에 본 fallback 명시.

---

## 6. Redfish endpoint 추적

**위치**: `redfish-gather/library/redfish_gather.py`

**함수별 호출 endpoint**:

| 함수 | 호출 endpoint |
|---|---|
| `detect_vendor()` | `/redfish/v1/` (ServiceRoot 무인증) → Manufacturer 추출 |
| `gather_system()` | `/redfish/v1/Systems/{id}` + `/Bios` (선택) |
| `gather_bmc()` | `/redfish/v1/Managers/{id}` + EthernetInterfaces |
| `gather_processors()` | `/redfish/v1/Systems/{id}/Processors` |
| `gather_memory()` | `/redfish/v1/Systems/{id}/Memory` |
| `gather_storage()` | `/redfish/v1/Systems/{id}/Storage` + Volumes + Drives |
| `gather_network()` | `/redfish/v1/Systems/{id}/EthernetInterfaces` + Chassis NetworkAdapters |
| `gather_firmware()` | `/redfish/v1/UpdateService/FirmwareInventory` |
| `gather_power()` | `/redfish/v1/Chassis/{id}/Power` 또는 PowerSubsystem |

**vendor 분기 위치**:
- `_OEM_EXTRACTORS` dict (line 1416~) — vendor 별 OEM extractor 함수 매핑
- `_account_create_method_for_vendor(vendor)` (line 3887) — Dell PATCH vs 그 외 POST

---

## 7. 외부 시스템 응답 디버깅

### Redfish probe (실 응답 캡처)

```bash
python tests/redfish-probe/probe_redfish.py --bmc-ip <ip> --vendor <vendor>
python tests/redfish-probe/deep_probe_redfish.py --bmc-ip <ip>  # 신 펌웨어 프로파일링
```

### SSH (Linux)

`ansible -vvv` 로그에서 SSH 응답 확인. paramiko 디버그:
```bash
export ANSIBLE_DEBUG=1
ansible-playbook ... -vvv
```

### WinRM (Windows)

pywinrm 디버그 (envvar):
```bash
export PYWINRM_DEBUG=1
```

### vSphere (ESXi)

community.vmware 로그 → `-vvv` 출력의 `vmware_*` 모듈 응답.

---

## 8. 회귀 사고 디버깅

**A 고치고 B 깨지는 패턴 차단**:

1. **Cross-channel envelope 회귀**: `pytest tests/regression/test_cross_channel_consistency.py`
   - 13 검증 그룹 × 9 baseline + 채널 커버리지 3 = 120 테스트 (`tests/regression/` 디렉터리 전체는 158 — HBA/IB·vendor-display·csus-mock 포함)
2. **Jinja2 namespace 회귀 차단**
3. **Fragment skeleton sync 차단**
4. **사이트 fixture 캡처**
5. **외부 계약 drift** 점검

**회귀 검증 명령** (PR 머지 전):
```bash
pytest tests/                                      # 전체 회귀
pytest tests/regression/                           # 회귀 전체 158 (cross-channel 120 포함)
ansible-playbook --syntax-check os-gather/site.yml  # 3 채널 syntax
```

---

## 9. Diagnosis 출력 디버깅

**정본**: `docs/12_diagnosis-output.md`

`envelope.diagnosis` 최상위 (`details` 와 형제 레벨) 의 4단계 결과:

| key | 의미 |
|---|---|
| `reachable` | ICMP / TCP SYN 도달 |
| `port_open` | target_type 별 port 응답 (22/5986/443) |
| `protocol_supported` | TCP 응답 + 첫 응답 형식 (HTTPS handshake / SSH banner / Redfish JSON) |
| `auth_success` | 자격증명으로 인증 성공 |
| `failure_stage` | 실패 단계 (precheck/gather/normalize/...) |
| `failure_reason` | 실패 사유 (auth_failed / timeout / parse_error / ...) |

**precheck 디버그**: `diagnosis.failure_stage` / `failure_reason` 로 막힌 단계 식별

---

## 10. 관련 문서

- `docs/06_gather-structure.md` — 전체 구조
- `docs/07_normalize-flow.md` — Fragment 정규화 과정
- `docs/08_failure-handling.md` — block/rescue/always
- `docs/10_adapter-system.md` — Adapter 점수 정책
- `docs/11_precheck-module.md` — Precheck 4 단계
- `docs/12_diagnosis-output.md` — Diagnosis 구조
- `docs/17_jenkins-pipeline.md` — Jenkins 런타임
- `docs/20_json-schema-fields.md` — JSON envelope 13 필드
- `docs/22_compatibility-matrix.md` — 호환성 매트릭스
