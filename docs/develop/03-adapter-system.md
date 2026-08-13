# 10. Adapter — 벤더 차이를 코드 밖으로 빼낸 장치

## 한 줄 요약

새 벤더 / 새 세대 BMC 가 들어와도 **Python / Ansible 코드는 안 만진다.** `adapters/` 폴더에 YAML 파일 1~3장 추가하면 끝.

이게 가능한 이유와 실제로 어떤 YAML 이 어떻게 매칭되는지를 풀어본다.

---

## 1. 왜 Adapter 가 필요한가

같은 "서버 정보 수집" 인데도 벤더마다 다음이 전부 다르다.

- BMC 응답 JSON 구조 (Dell `Oem.Dell.DellSystem`, HPE `Oem.Hpe.Bios`, …)
- 펌웨어 버전 표기 형식
- 일부 필드 존재 여부 (`storage.logical_volumes` 가 일부 세대에는 없다)
- 필요한 호출 순서 (HPE Gen11 부터는 Controllers 링크를 따로 호출해야 함)

이걸 전부 Python 코드에 `if vendor == "dell": ...` 분기로 박으면, 새 벤더 들어올 때마다 코드 깊숙이 손대야 한다. 5개 벤더면 어떻게든 버틴다. 9개, 12개 늘어나면 아무도 못 읽는다.

대신 **벤더 차이만 떼어내서 YAML 한 장에 적어두는 식으로 분리**한다. Python 코드는 "어떤 YAML 이 매칭되는지" 만 결정하고 **그 YAML 에 적힌 경로대로** 호출한다.

---

## 2. 실제 어떻게 동작하나 — 한 번의 호출 따라가기

호출자가 Dell 서버 BMC IP 를 넘긴 시점부터 어떤 adapter 가 어떻게 선택되는지.

```text
[ Step 1 ] precheck — 어디까지 닿는지 확인
    ping(10.50.11.162) → OK
    TCP 443 응답 → OK
    HTTPS handshake → OK
    Basic Auth → OK
    │
    이때 BMC 가 알려준 정보:
       Manufacturer: "Dell Inc."
       Product:      "Integrated Dell Remote Access Controller"
       FirmwareVersion: "iDRAC 9 4.00.00.00"
    │
    ▼
[ Step 2 ] vendor 정규화
    "Dell Inc." → vendor_aliases.yml 조회 → "dell"
    │
    ▼
[ Step 3 ] adapter_loader (Ansible lookup plugin) 실행
    │
    ├─ adapters/redfish/*.yml 31개 파일 모두 읽기
    │
    ├─ 각 파일의 match 조건 평가 (vendor / firmware / model 패턴)
    │   - redfish_generic.yml      → 매칭 (모든 vendor 대상, 점수 낮음)
    │   - dell_idrac.yml            → 매칭 (vendor=dell)
    │   - dell_idrac9.yml           → 매칭 (vendor=dell + firmware ~ /iDRAC.*9/)
    │   - dell_idrac8.yml           → 미매칭 (firmware 패턴 다름)
    │   - hpe_*, lenovo_*, ...      → 미매칭
    │
    ├─ 매칭된 adapter 들에 점수 매기기 (3절 공식 참조)
    │   - dell_idrac9.yml  = 100,345
    │   - dell_idrac.yml   =  10,120
    │   - redfish_generic  =    -400
    │
    └─ 최고 점수 → dell_idrac9.yml 선택
    │
    ▼
[ Step 4 ] 선택된 adapter 가 시키는 대로
    - credentials.profile = "dell"  → vault/<loc>/redfish/dell.yml 로드
    - collect.standard_tasks = "redfish-gather/tasks/collect_standard.yml" 실행
    - normalize.standard_tasks 실행 → fragment 생성
    - capabilities.sections_supported 가 출력 sections[].not_supported 의 기준
```

여기서 핵심: Ansible / Python 코드 **어디에도 "Dell" 이라는 단어가 없다.** 모든 분기가 YAML 안의 정보로 결정된다.

---

## 3. 점수 계산 — 누가 뽑히나

매칭된 adapter 가 여러 개일 때 점수가 가장 높은 것이 뽑힌다.

### 공식

```text
score = priority × 1000  +  specificity × 10  +  match_score
        (generic adapter 는 specificity 에 −40 이 포함 → 총점에 −400 기여)
```

### 각 요소

| 요소 | 어디서 오나 | 보통 값 |
|---|---|---|
| `priority` | YAML 의 `priority:` 값 | 0(generic) / 10(기본 vendor) / 50(세대별) / 100(최신 세대) |
| `specificity` | match 조건 개수 / 종류 | vendor 만 = 10, vendor+firmware = 30 |
| `match_score` | 실제 매칭 성공 보너스 | vendor +20, model +25, firmware +25 |
| `generic` | YAML 의 `generic: true` 면 specificity 에 −40 | fallback 용이라 점수 낮춤 (총점 −400 기여) |

### 예시 — Dell iDRAC 9 vs Dell 기본

| adapter | priority | specificity | match | 합계 |
|---|---:|---:|---:|---:|
| `dell_idrac9.yml` | 100×1000 | (10+20)×10 | 20+25 | **100,345** |
| `dell_idrac.yml` | 10×1000 | 10×10 | 20 | **10,120** |
| `redfish_generic.yml` | 0×1000 | −40×10 | 0 | **−400** |

세대별 (`dell_idrac9`) 이 항상 기본 (`dell_idrac`) 보다 압도적으로 높게 나오게 priority 차등을 둔다. 이게 깨지면 (예: dell_idrac9 의 priority 를 5 로 두면) 기본이 뽑히는 이상 동작이 생긴다.

---

## 3.5. Priority 정책표

새 adapter 의 priority 결정 시 다음 정책 따른다 (rule 50 R3):

| 분류 | priority 범위 | 의미 | 예시 |
|---|---:|---|---|
| **generic fallback** | `0` | 모든 vendor 대상, 점수 매우 낮음 (`generic: true` 감점 -40) | `redfish_generic`, `linux_generic`, `windows_generic`, `esxi_generic` |
| **vendor 기본** | `10` | vendor 정의는 됐으나 세대 / 모델 미특정. firmware probe 실패 시 fallback | `dell_idrac`, `hpe_ilo`, `lenovo_bmc`, `cisco_bmc`, `supermicro_bmc` |
| **세대 (구형)** | `30~50` | 5+ 년 전 세대 (지원 종료 / 호환성 영역) | `esxi_6x`, `dell_idrac8`, `hpe_ilo4`, `lenovo_imm2`, `supermicro_x9` |
| **세대 (메인)** | `80~100` | 운영 중 주력 세대 | `esxi_7x/8x`, `dell_idrac9`, `hpe_ilo5/6`, `lenovo_xcc`, `supermicro_x11~13`, `cisco_cimc`, lab 부재 신 vendor (`huawei_ibmc/inspur_isbmc/fujitsu_irmc/quanta_qct_bmc` = 80) |
| **세대 (최신)** | `110~120` | 신 generation (cycle 2026-05-01 추가 — F41/F47/F55) | `dell_idrac10`, `hpe_ilo7`, `lenovo_xcc3`, `supermicro_x14`, `cisco_ucs_xseries` |
| **특수 / lab 부재 보호** | `101` | 비표준 (Superdome / 비표준 폼팩터) — lab 없이 web sources 만 | `hpe_superdome_flex` |

**OS / ESXi 채널** (세대 / vendor 분기 단순):
- generic fallback: `0`
- 메이저 버전 (linux_rhel / linux_ubuntu / linux_suse / windows_2019/2022 / esxi_7x): `50`
- 최신 (esxi_8x): `100`
- 구형 (esxi_6x): `30`

### 31 redfish adapter priority 매트릭스 (2026-06-08 기준)

| priority | adapter |
|---:|---|
| `120` | dell_idrac10, hpe_ilo7, lenovo_xcc3 |
| `110` | cisco_ucs_xseries, supermicro_x14 |
| `102` | hpe_csus_3200 (lab 부재 — Compute Scale-up Server) |
| `101` | hpe_superdome_flex (lab 부재 — 비표준 폼팩터) |
| `100` | cisco_cimc, dell_idrac9, hpe_ilo6, lenovo_xcc, supermicro_x11, supermicro_x12, supermicro_x13 |
| `90` | hpe_ilo5 |
| `80` | fujitsu_irmc, huawei_ibmc, inspur_isbmc, quanta_qct_bmc (lab 부재 신 vendor), supermicro_ars |
| `75` | supermicro_x10 |
| `50` | dell_idrac8, hpe_ilo4, lenovo_imm2, supermicro_x9 (구형) |
| `10` | cisco_bmc, dell_idrac, hpe_ilo, lenovo_bmc, supermicro_bmc (vendor 기본) |
| `0` | redfish_generic (`generic: true`) |

### 새 세대 추가 시 priority 결정 절차

1. 같은 vendor 의 기존 세대 priority 확인 (예: dell_idrac9 = 100, dell_idrac10 = 120)
2. 신 세대는 기존 최고 priority + 20 (역전 방지 충분한 간격)
3. specificity 가 충분한지 확인 (`firmware_patterns` + `model_patterns` 정의)
4. 점수 동률 시 `-vvv` 로그가 경고 → priority 조정 검토
5. lab 부재 vendor (rule 96 R1-A) 는 `80` 으로 시작, lab 도입 후 메인 세대 격상

상세: rule 50 R2 9단계 + 단계 10 (lab 부재 처리), `docs/develop/04-add-vendor.md`.

---

## 4. Adapter YAML 한 장 뜯어보기

`adapters/redfish/dell_idrac9.yml` 같은 한 장에 들어가는 항목.

```yaml
adapter_id: redfish_dell_idrac9       # 고유 ID. envelope 의 meta.adapter_id 에 찍힘
channel:    redfish                   # 어떤 채널에서 쓸지 (redfish/os/esxi)
priority:   100                       # 이 vendor 안에서의 우선순위
version:    "1.0.0"
generic:    false                     # true 면 fallback adapter (점수 −40)

match:                                # ↓ 모두 만족해야 이 adapter 가 매칭됨
  vendor:             ["Dell", "Dell Inc."]
  firmware_patterns:  ["iDRAC.*9"]
  model_patterns:     []
  os_type:            linux           # OS 채널일 때만 사용
  distribution_patterns: ["RHEL"]
  version_patterns:   ["^7\\."]       # ESXi 채널일 때만 사용

capabilities:
  sections_supported: [system, hardware, bmc, cpu, memory, storage,
                       network, firmware, power]
                                      # ← 출력 JSON 의 sections 에서
                                      #   여기 없는 섹션은 자동으로 not_supported

collect:
  standard_tasks: "redfish-gather/tasks/collect_standard.yml"

normalize:
  standard_tasks: "redfish-gather/tasks/normalize_standard.yml"

credentials:
  profile:           "dell"   # vault/<loc>/redfish/dell.yml 을 로드
  fallback_profiles: []

graceful_degradation:
  critical_sections: [system, hardware]   # 이게 실패하면 abort
  optional_sections: [firmware, power]    # 이게 실패해도 다른 섹션 계속
```

읽는 법: 위에서부터 "**누구한테 매칭되는가 → 뭘 할 수 있는가 → 어떤 코드를 호출하는가 → 어떤 자격증명 쓰는가 → 실패 어떻게 다루는가**".

---

## 5. 새 벤더 추가 — 정확히 3단계

새 벤더 (예: Fujitsu) 를 붙일 때 만져야 하는 곳.

### 1단계 — 별칭 추가

`common/vars/vendor_aliases.yml` 에 BMC 가 보고할 만한 manufacturer 표기를 모두 적는다.

```yaml
fujitsu:
  - "Fujitsu"
  - "FUJITSU"
  - "FUJITSU LIMITED"
```

### 2단계 — Adapter YAML 만들기

`adapters/redfish/fujitsu_irmc.yml` 작성. 위 4절 구조 그대로.

### 3단계 — (선택) OEM 태스크

Fujitsu 만의 특이한 응답이 있으면 라이브러리 `_extract_oem_*` 에 vendor 분기를 넣는다.

OEM 이 필요 없으면 표준 필드만으로 충분하다. 그 경우 adapter YAML 의 `collect.oem_tasks` 를 비우면 된다.

**`site.yml` 은 수정하지 않는다.** adapter_loader 가 폴더를 동적으로 스캔한다.

---

## 6. 새 OS / ESXi 도 같은 패턴

| 들어온 것 | 만들 YAML |
|---|---|
| 새 Linux 배포판 (예: Rocky) | `adapters/os/linux_rocky.yml` (distribution_patterns 에 "Rocky") |
| 새 ESXi 메이저 버전 (예: 9.x) | `adapters/esxi/esxi_9x.yml` (version_patterns 에 `^9\.`) |

벤더가 아니라 **운영체제 / 가상화 버전** 이 분기 키일 뿐, 구조는 동일하다.

---

## 7. Python 코드와 Adapter 의 역할 분리

Adapter 가 모든 걸 해결하는 건 아니다. 세 계층이 각자 책임이 다르다.

| 계층 | 담당 |
|---|---|
| Python (`redfish_gather.py`) | HTTP 호출, 응답 파싱, 벤더 감지 (`_detect_vendor_from_service_root`) |
| Adapter YAML | 어떤 task 를 부를지, 어떤 vault 를 쓸지, 어떤 섹션을 지원하는지 |
| Normalize task | 응답 dict 를 envelope `data` 에 맞게 정리 |

Python 은 **"어떻게 가져오나"**, Adapter 는 **"누구에게 무엇을 할 수 있나"**, Normalize 는 **"어떻게 표준 JSON 으로 옮기나"**.

이렇게 나누면 Python 은 거의 안 바뀌고 (3년에 한 번 정도), Adapter 가 자주 바뀌어도 (분기 한 번에 1장씩) 충돌이 없다.

---

## 8. 디버깅 — 어느 adapter 가 뽑혔지?

세 가지 방법.

**(가) envelope 안 보기**
```json
"meta": { "adapter_id": "redfish_dell_idrac9", ... }
```

**(나) `-vvv` 로 ansible 실행해서 로그 보기**
```bash
ansible-playbook redfish-gather/site.yml -e target_ip=10.x.x.1 -vvv 2>&1 | grep -i adapter
```

**(다) `score-adapter-match` 절차 (skill) 사용**
점수 충돌이 의심될 때 각 adapter 의 점수를 풀어서 보여준다.

---

## 9. 자주 마주치는 사고

**Q. 새 adapter 만들었는데 선택이 안 됨**
match 조건이 실제 BMC 응답과 다른 경우가 90%. probe 로 raw 응답을 받아서 vendor / firmware / model 문자열을 직접 확인한다.

**Q. 같은 vendor 의 다른 generation 이 잘못 뽑힘**
priority 가 역전됐다 (세대별이 기본 보다 낮음). 또는 priority 는 같은데 specificity 가 비슷해서 정렬 결과가 불확정. **priority 를 100 / 50 / 10 / 0 으로 충분히 벌려놓는** 게 안전.

**Q. capabilities.sections_supported 에 적었는데 출력에 not_supported 로 나옴**
adapter 가 매칭은 됐는데 normalize task 가 그 섹션을 못 채운 경우. fragment 생성 단계의 raw 응답 / Jinja2 추출 / fragment merge 호출 누락을 차례로 점검.

---

## 10. 더 보고 싶을 때

| 보고 싶은 것 | 파일 |
|---|---|
| 벤더 / 세대 / 섹션 호환성 한 장 표 | `docs/reference/compatibility-matrix.md` |
| 새 벤더 추가 절차 (전체 9단계) | `docs/develop/04-add-vendor.md` |
| 실장비 검증 결과 | `docs/reference/live-validation.md` |
| 점수 계산 코드 | `module_utils/adapter_common.py` |
| adapter 동적 로딩 | `lookup_plugins/adapter_loader.py` |
| 벤더 별칭 사전 | `common/vars/vendor_aliases.yml` |
| adapter 인덱스 | `adapters/registry.yml` |

---

## 검증 상태 (요약)

| 벤더 | 검증 기준 장비 | 매칭 Adapter | 실장비 검증 |
|---|---|---|---|
| Dell | PowerEdge R740 (iDRAC 9, FW 4.00) | `redfish_dell_idrac9` (P100) | 완료 |
| HPE | DL380 Gen11 (iLO 6, FW 1.73) | `redfish_hpe_ilo6` (P100) | 완료 |
| Lenovo | SR650 V2 (XCC, FW 5.70) | `redfish_lenovo_xcc` (P100) | 완료 |
| Supermicro | — | 어댑터만 존재 | 미검증 |
| Cisco | UCS C220 M4 (CIMC 4.1(2g)) | `redfish_cisco_cimc` | M4 partial lab 검증 (M5~M8 미검증) |

> [!NOTE]
> 위 HPE 행은 현재 코드 기준 매칭이다. 커밋된 `schema/baseline_v1/hpe_baseline.json` 은 `redfish_hpe_ilo6` adapter 추가(2026-05-01) 이전 캡처라 `redfish_hpe_ilo5` 를 기록한다. baseline 재생성이 필요하다(후속 작업).

상세는 `docs/reference/live-validation.md`.
