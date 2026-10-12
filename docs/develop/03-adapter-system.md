# 어댑터: 벤더 차이를 코드 밖으로 빼낸 장치

새 벤더나 새 세대의 BMC가 들어와도 Python과 Ansible 코드는 고치지 않습니다. `adapters/` 아래에 YAML 파일을 추가하면 됩니다. 이 문서는 그것이 가능한 이유와 어떤 YAML이 어떻게 선택되는지를 설명합니다.

## 1. 왜 어댑터가 필요한가

같은 "서버 정보 수집"인데도 벤더마다 다음이 다릅니다.

- BMC 응답 JSON의 OEM 구조 (`Oem.Dell`, `Oem.Hpe` 등)
- 펌웨어 버전 표기
- 세대별로 있는 리소스와 없는 리소스

이것을 전부 수집 코드에 `if vendor == "dell"` 분기로 넣으면 벤더가 늘 때마다 코드 깊숙이 손대야 합니다. 대신 벤더 차이만 떼어내 YAML 한 장에 적어 두고, 코드는 "어떤 YAML이 맞는지"만 정합니다. 수집 경로 자체는 세 채널 모두 `site.yml`에 고정되어 있고, 어댑터는 두 가지만 정합니다. 누구에게 맞는가(`match`)와 어떤 섹션을 지원하는가(`capabilities.sections_supported`)입니다.

## 2. 한 번의 호출 따라가기

호출자가 Dell 서버의 BMC IP를 넘겼을 때 어댑터가 어떻게 선택되는지입니다.

```text
[ 1 ] 사전 진단 — TCP 443 → /redfish/v1/ 응답 확인 (무인증)
      ServiceRoot 가 알려주는 것: Vendor "Dell Inc.", Product, RedfishVersion
[ 2 ] 벤더 정규화 — "Dell Inc." → common/vars/vendor_aliases.yml → "dell"
[ 3 ] adapter_loader (lookup 플러그인)
      adapters/redfish/*.yml 을 모두 읽고 match 조건을 평가합니다
        redfish_generic   매칭 (모든 벤더, 점수 낮음)
        dell_idrac        매칭 (vendor = dell)
        dell_idrac9       매칭 (vendor = dell, firmware 가 iDRAC 9 또는 3.x~7.x)
        dell_idrac8       불일치 (firmware 패턴 다름)
        hpe_*, lenovo_*   불일치
      매칭된 어댑터에 점수를 매겨 가장 높은 것을 고릅니다 (3절)
[ 4 ] 선택된 어댑터에서 플레이북이 읽는 것
      adapter_id                       결과 meta.adapter_id 와 진단
      capabilities.sections_supported  출력 sections 에서 not_supported 를 가르는 기준
      vendor_notes.manager_layout      (Redfish 멀티 노드 장비만) 수집 모듈 인자
[ 5 ] 복구 계정은 정규화된 벤더 이름으로 고릅니다 — vault/<loc>/redfish/dell.yml
```

표준 계정으로 인증해 모델과 펌웨어를 읽은 뒤 `tasks/reselect_adapter.yml`이 어댑터를 한 번 더 고릅니다. 무인증 서비스 루트만으로는 세대를 정하기 어려운 벤더(예: 서비스 루트의 Product가 BMC 이름인 Dell)가 있기 때문입니다. 수집 코드 어디에도 벤더 이름은 없고, 모든 분기는 YAML 안의 정보로 정해집니다.

## 3. 점수 계산

매칭된 어댑터가 여러 개일 때 점수가 가장 높은 것이 선택됩니다. 구현은 `module_utils/adapter_common.py`입니다.

```text
score = priority × 1000 + specificity × 10 + match_score
```

| 요소 | 어디서 오나 | 값 |
|---|---|---|
| `priority` | YAML의 `priority` | 0 (generic), 10 (벤더 기본), 50 (구형 세대), 80~100 (주력 세대), 110~120 (최신 세대) |
| `specificity` | `match`에 적은 조건의 종류 | vendor 10, model_patterns 20, firmware_patterns 20, version_patterns 15, distribution_patterns 15, os_type 5. `generic: true`면 40 감점 |
| `match_score` | 실제로 맞은 조건 | vendor 20, model 25, firmware 25, version 15, distribution 15, os_type 5 |

패턴을 적었는데 장비가 그 값을 주지 않으면(예: 펌웨어 문자열이 비어 있음) 그 조건은 더하지도 빼지도 않습니다. 값을 줬는데 패턴과 맞지 않으면 그 어댑터는 거부됩니다.

예를 들어 Dell iDRAC 9 장비에서는 다음과 같이 갈립니다.

| 어댑터 | priority | specificity | match | 합계 |
|---|---:|---:|---:|---:|
| `dell_idrac9` | 100 × 1000 | (10 + 20) × 10 | 20 + 25 | 100,345 |
| `dell_idrac` | 10 × 1000 | 10 × 10 | 20 | 10,120 |
| `redfish_generic` | 0 | −40 × 10 | 0 | −400 |

세대별 어댑터가 벤더 기본보다 항상 높게 나오도록 `priority` 차이를 둡니다. 같은 점수가 나오면 파일 이름 순으로 정해지는데, 동률 자체가 priority와 specificity가 어긋났다는 신호이므로 `-vvv` 로그에 경고가 남습니다.

### 3.1 priority 정책

| 분류 | priority | 예 |
|---|---:|---|
| generic fallback | 0 | `redfish_generic`, `linux_generic`, `windows_generic`, `esxi_generic` |
| 벤더 기본 (세대 미특정) | 10 | `dell_idrac`, `hpe_ilo`, `lenovo_bmc`, `cisco_bmc`, `supermicro_bmc` |
| 구형 세대 | 50 | `dell_idrac8`, `hpe_ilo4`, `lenovo_imm2`, `supermicro_x9` |
| 주력 세대 | 75~100 | `supermicro_x10` (75), 실장비 없이 작성한 벤더 (`huawei_ibmc`, `inspur_isbmc`, `fujitsu_irmc`, `quanta_qct_bmc`, `supermicro_ars`: 80), `hpe_ilo5` (90), `dell_idrac9`, `hpe_ilo6`, `lenovo_xcc`, `cisco_cimc`, `supermicro_x11`~`x13` (100) |
| 비표준 폼팩터 | 101~102 | `hpe_superdome_flex` (101), `hpe_csus_3200` (102) |
| 최신 세대 | 110~120 | `cisco_ucs_xseries`, `supermicro_x14` (110), `dell_idrac10`, `hpe_ilo7`, `lenovo_xcc3` (120) |

OS와 ESXi 채널은 단순합니다. generic 0, 배포판과 Windows 버전과 ESXi 7.x는 50, ESXi 6.x는 30, ESXi 8.x와 9.x는 100입니다. 현재 값은 다음 명령으로 확인합니다.

```bash
# 저장소 루트
grep -H '^priority:' adapters/redfish/*.yml adapters/os/*.yml adapters/esxi/*.yml
```

새 세대를 추가할 때는 같은 벤더의 기존 최고 priority보다 20 높게 두고, `firmware_patterns`나 `model_patterns`로 specificity를 충분히 줍니다. 세대 토큰(`iLO 6`, `iDRAC 9`, `XCC3`)은 단어 경계(`\b`)로 정확히 맞추어 `iLO 5 v2.65`가 iLO 6 어댑터에 맞지 않게 합니다. 펌웨어 버전 숫자만으로 세대를 정하는 패턴은 모델이나 세대 토큰이 없을 때의 보조 조건으로만 둡니다.

## 4. 어댑터 YAML 한 장

코드가 읽는 키는 다음이 전부입니다. 그 밖의 설명은 `vendor_notes`에 메모로만 둡니다.

```yaml
adapter_id: redfish_dell_idrac9       # 고유 ID. 결과의 meta.adapter_id 에 찍힙니다
priority: 100                         # 3절의 정책
generic: false                        # true 면 fallback 어댑터 (specificity 40 감점). 생략하면 false

match:                                # 적은 조건을 모두 만족해야 매칭됩니다
  vendor: ["Dell", "Dell Inc.", "DELL"]            # vendor_aliases.yml 로 정규화한 값과 비교
  firmware_patterns: ["iDRAC\\s*9\\b", "^[3-7]\\."] # 정규식 (하나라도 맞으면 됨)
  model_patterns: []                               # 정규식
  os_type: linux                                   # OS 채널만 (linux, windows)
  distribution_patterns: ["Red Hat", "RHEL"]       # OS 채널만
  version_patterns: ["^9\\."]                      # ESXi 채널만

capabilities:
  sections_supported: [hardware, bmc, cpu, memory, storage, network, firmware, power, thermal]
                                      # 여기 없는 섹션은 결과에서 not_supported. 채널이 지원하는 섹션 안에서만 고릅니다

vendor_notes:                         # 기록용. Redfish 멀티 노드 장비는 manager_layout 하나만 코드가 읽습니다
  manager_layout: rmc_primary
  design_hints: {...}
```

`capabilities.sections_supported`는 채널이 지원하는 섹션(`common/vars/supported_sections.yml`)의 부분집합이어야 합니다. Redfish 어댑터는 `system`을 넣지 않습니다. Redfish 채널은 `system` 섹션을 내지 않기 때문입니다. 시험 `tests/unit/test_adapter_capabilities_channel_sections.py`가 이 관계를 검사합니다.

## 5. 새 벤더 추가

1. `common/vars/vendor_aliases.yml`에 BMC가 보고할 만한 제조사 표기를 모두 적습니다.
2. `adapters/redfish/<vendor>_<generation>.yml`을 4절 구조로 만듭니다.
3. 벤더만의 OEM 응답이 필요하면 `redfish-gather/library/redfish_gather.py`의 `_OEM_EXTRACTORS`에 추출 함수를 더합니다. 표준 필드만으로 충분하면 이 단계는 필요 없습니다.

`site.yml`은 수정하지 않습니다. `adapter_loader`가 디렉터리를 동적으로 읽습니다. 전체 절차와 검증은 [04-add-vendor.md](04-add-vendor.md)에 있습니다.

## 6. 새 OS와 ESXi도 같은 패턴

| 들어온 것 | 만들 YAML |
|---|---|
| 새 Linux 배포판 | `adapters/os/linux_<이름>.yml` (`os_type: linux`, `distribution_patterns`) |
| 새 Windows 버전 | `adapters/os/windows_<버전>.yml` (`os_type: windows`, `distribution_patterns`) |
| 새 ESXi 메이저 버전 | `adapters/esxi/esxi_<N>x.yml` (`version_patterns: ["^N\\."]`) |

벤더가 아니라 OS 배포판이나 가상화 버전이 분기 키일 뿐 구조는 같습니다.

## 7. 코드와 어댑터의 역할

| 계층 | 담당 |
|---|---|
| Python (`redfish_gather.py`, `precheck_bundle.py`) | HTTP 호출, 응답 파싱, 벤더 감지, OEM 추출 |
| 어댑터 YAML | 누구에게 맞는가, 어떤 섹션을 지원하는가 |
| normalize 태스크 | 응답을 봉투 `data` 형식으로 정리 |

Python은 "어떻게 가져오나", 어댑터는 "누구에게 무엇을 할 수 있나", normalize는 "어떻게 표준 JSON으로 옮기나"입니다.

## 8. 어느 어댑터가 뽑혔는지 보기

결과 봉투의 `meta.adapter_id`를 봅니다. 점수까지 보려면 `-vvv`로 실행합니다.

```text
adapter_loader: dell_idrac9 matched score=100345 (priority=100×1000 + specificity=30×10 + match=45)
adapter_loader: dell_idrac matched score=10120 (priority=10×1000 + specificity=10×10 + match=20)
adapter_loader: 후보 거부 — 28건
  - hpe_ilo6 (match 조건 불일치)
adapter_loader: top 3 candidates (score 내림차순):
  #1 dell_idrac9 score=100345
  #2 dell_idrac score=10120
  #3 redfish_generic score=-400
adapter_loader: 선택됨 — dell_idrac9 (score=100345)
```

직접 실행 방법은 [../operate/08-ansible-config.md](../operate/08-ansible-config.md) 5절에 있습니다.

## 9. 자주 마주치는 문제

| 증상 | 확인할 것 |
|---|---|
| 새 어댑터를 만들었는데 선택되지 않음 | `match` 조건이 실제 응답과 다른 경우가 대부분입니다. 장비의 원본 응답에서 Vendor, Model, 펌웨어 문자열을 확인하세요 ([08-onsite-capture.md](08-onsite-capture.md)) |
| 같은 벤더의 다른 세대가 뽑힘 | priority가 역전됐거나 세대 토큰 패턴이 다른 세대 문자열에도 맞는 경우입니다. `-vvv` 점수 내역을 보세요 |
| `sections_supported`에 적었는데 `not_supported`로 나옴 | 어댑터는 매칭됐는데 normalize가 그 섹션을 못 채운 경우입니다. 원본 응답과 fragment 병합 호출을 확인하세요 |

## 10. 실장비 확인 상태

| 벤더 | 확인 장비 | 선택된 어댑터 |
|---|---|---|
| Dell | PowerEdge R760 (iDRAC 9) 5대, PowerEdge R740 (iDRAC 9 FW 4.00) | `redfish_dell_idrac9` |
| HPE | ProLiant DL380 Gen11 (iLO 6 FW 1.73) | `redfish_hpe_ilo6` |
| Lenovo | ThinkSystem SR650 V2 (XCC FW 5.70), 사내 명부 XCC 1대 | `redfish_lenovo_xcc` |
| Cisco | UCS C220 M4 (CIMC) | `redfish_cisco_cimc` |
| Supermicro, Huawei, Inspur, Fujitsu, Quanta | 없음 | 어댑터만 존재 |

상세는 [../reference/live-validation.md](../reference/live-validation.md)에 있습니다.

## 11. 더 보고 싶을 때

| 보고 싶은 것 | 위치 |
|---|---|
| 벤더 × 세대 × 섹션 표 | [../reference/compatibility-matrix.md](../reference/compatibility-matrix.md) |
| 새 벤더 추가 절차 | [04-add-vendor.md](04-add-vendor.md) |
| 점수 계산 코드 | `module_utils/adapter_common.py` |
| 동적 로딩 | `lookup_plugins/adapter_loader.py` |
| 벤더 별칭 | `common/vars/vendor_aliases.yml` |
