# Adapter / Vendor 경계 보호

## 적용 대상
- `adapters/{redfish,os,esxi}/**`
- `common/`, `os-gather/`, `esxi-gather/`, `redfish-gather/` (vendor 하드코딩 금지 영역)
- `common/vars/vendor_aliases.yml`

## 현재 관찰된 현실

- adapter YAML 은 `adapters/{redfish,os,esxi}/` 아래에 있다 (개수는 세지 않는다 — rule 00 의 세는 명령 참조)
- 9 vendor (Dell / HPE / Lenovo / Supermicro / Cisco / Huawei / Inspur / Fujitsu / Quanta) + generic fallback
- adapter_loader (lookup plugin)이 동적 점수 계산으로 선택
- vendor-specific OEM 추출은 라이브러리 `_extract_oem_*` (task 디렉터리는 2026-08-13 제거)

## 목표 규칙

### R1. Vendor 이름 하드코딩 금지

- **Default**: `common/`, `os-gather/`, `esxi-gather/`, `redfish-gather/` 코드에 vendor 이름 하드코딩 금지
- **Allowed**: `adapters/{channel}/{vendor}_*.yml` 안, `common/vars/vendor_aliases.yml`
- **2026-08-13 변경**: 종전에는 `redfish-gather/tasks/vendors/{vendor}/` 도 Allowed 였다.
  그 디렉터리는 삭제됐다 — 9 vendor 18개 task 가 전부 모듈 출력에 없는 경로를 읽어
  기여가 0이었다. vendor OEM 확장 지점은 이제 라이브러리 층이다
  (근거: `docs/ai/decisions/ADR-2026-08-13-vendor-oem-task-removal.md`)
- **Allowed (cycle-006 추가)**: `redfish-gather/library/redfish_gather.py` 의 다음 영역
  - `_FALLBACK_VENDOR_MAP` (vendor_aliases.yml load 실패 시 fallback)
  - OEM schema 추출 분기 (`if vendor == 'hpe': oem = _safe(data, 'Oem', 'Hpe')` 등) — Redfish API spec 자체가 vendor namespace를 정의 (`Oem.Hpe`, `Oem.Dell`, `Oem.Lenovo`, `Oem.Supermicro`). 외부 계약 (rule 96)에 직접 의존
  - `_detect_from_product` 의 vendor 시그니처 매핑 (`if 'idrac' in p: return 'dell'` 등)
  - `bmc_names = {'dell': 'iDRAC', 'hpe': 'iLO', ...}` 같은 BMC 표시명 매핑
- **Allowed (cycle-006 추가)**: `os-gather/tasks/{linux,windows}/gather_system.yml` 의 hosting_type 판정용 OEM vendor 인식 list — 분기 코드 (`if vendor == 'X'`)가 아닌 set membership (`vendor in oem_vendors`) 패턴
- **Forbidden**: 위 Allowed 영역 외 코드의 `if vendor == "Dell"` 분기, `Dell` / `HPE` / `Lenovo` / `Supermicro` / `Cisco` 문자열 비교
- **Why**: gather 코드는 vendor-agnostic 원칙. 단, **Redfish API의 OEM 영역은 spec 자체가 vendor namespace 사용 (rule 96 외부 계약)** 이라 라이브러리에서 추출 외 대안이 없음. set membership 패턴도 분기 의미가 약함.
- **재검토**: 6개월 vendor 추가 0건 시 일부 완화 가능

`scripts/ai/verify_vendor_boundary.py`가 자동 검출. 의도된 예외 라인은 라인 또는 직전 라인에 `# nosec rule12-r1` (또는 `{# nosec rule12-r1 ... #}`) 주석으로 silence.

### R2. Adapter 점수 일관성

- **Default**: 같은 vendor 내 adapter는 priority 역전 금지
  - generic vendor adapter (예: dell_idrac.yml) priority = 10
  - 세대별 (예: dell_idrac8.yml) priority = 50
  - 최신 (예: dell_idrac9.yml) priority = 100
- **Forbidden**: 세대별 adapter가 generic보다 priority 낮음 (generic이 매번 선택됨)
- **Why**: 점수 계산 일관성 + 디버깅 용이성

### R3. Vendor 추가 3단계

- **Default**: 새 vendor 추가는 정확히 3단계:
  1. `common/vars/vendor_aliases.yml`에 alias 매핑
  2. `adapters/{redfish,os,esxi}/{vendor}_*.yml` adapter 생성
  3. (선택) OEM 확장이 필요하면 `redfish-gather/library/redfish_gather.py` 의
     `_extract_oem_*` 에 vendor 분기 추가 (rule 12 R1 Allowed 영역)
- **Forbidden**: site.yml 수정 (adapter_loader가 동적 감지)
- **Why**: site.yml을 vendor마다 수정하면 vendor 수만큼 site.yml이 비대해짐

### R4. Adapter YAML 필드 (2026-10-10 코드 대조 정정 — `docs/ai/decisions/ADR-2026-10-10-adapter-required-keys.md`)

- **Default**: adapter 는 `adapter_id` · `priority` · `match` · `capabilities.sections_supported` 를 가진다. 코드가 읽는 것은 이것뿐이다 —
  로더(`module_utils/adapter_common.py` · `lookup_plugins/adapter_loader.py`)는 `match`(없으면 `{}` — 어느 장비에도 매칭되지 않음) · `adapter_id` · `priority` · `generic` 을
  읽고 어떤 키도 강제하지 않는다. site.yml 은 `capabilities.sections_supported` 로 `not_supported` 를 정하고, redfish site.yml 은 `vendor_notes.manager_layout` 을 모듈에 넘기며, `build_meta.yml` 은 `version` 을 `meta.adapter_version` 에 적는다(현 adapter 들에는 없어 null).
- **Allowed**: `metadata` · `vendor_notes` 로 vendor / firmware / tested_against / oem_path 등 origin 주석 (rule 96 R1). `collect` · `normalize` · `credentials` ·
  `graceful_degradation` 절은 **기록용**이다 — 어떤 코드도 읽지 않는다(수집 · 정규화 task 경로는 site.yml 고정, 복구 vault 는 감지된 vendor 로 선택). OS · ESXi adapter 는 `normalize` 키가 없다.
- **Forbidden**: `match` 누락(선택되지 않는 adapter) · `capabilities.sections_supported` 누락(모든 섹션이 not_supported) · 기록용 절을 "실행된다" 고 문서에 적기
- **종전 서술** "4개 키 필수(adapter_loader 파싱 실패)" 는 코드와 달랐다 — DRIFT-024

### R5. Generic fallback

- **Default**: 모든 채널에 generic adapter 1개 (`{channel}/redfish_generic.yml` 등) priority = 0 (fallback)
- **Why**: 매치 안 되는 vendor에 대해서도 graceful degradation

## 금지 패턴

- gather 코드에 vendor 이름 하드코딩 — R1 (verify_vendor_boundary.py 자동 검출)
- adapter priority 역전 — R2
- 새 vendor 추가하면서 site.yml 수정 — R3
- adapter 4개 필수 필드 누락 — R4
- generic fallback 부재 — R5

## 리뷰 포인트

- [ ] verify_vendor_boundary.py 통과 (vendor 하드코딩 0건)
- [ ] 새 adapter priority가 같은 vendor 다른 generation과 일관성
- [ ] vendor 추가 시 정확히 3단계만
- [ ] adapter YAML 4개 필수 필드 모두 존재
- [ ] origin 주석 (rule 96 R1) 존재

## 테스트 포인트

- `python scripts/ai/verify_vendor_boundary.py` (exit 0)
- `score-adapter-match` skill로 점수 디버깅
- 새 vendor: deep_probe_redfish.py로 프로파일링 후 baseline 검증

## 관련

- rule: `10-gather-core`, `22-fragment-philosophy`, `96-external-contract-integrity`
- skill: `add-new-vendor`, `score-adapter-match`, `verify-adapter-boundary`, `vendor-change-impact`
- agent: `adapter-author`, `vendor-onboarding-worker`, `adapter-boundary-reviewer`, `vendor-boundary-guardian`
- policy: `.claude/policy/vendor-boundary-map.yaml`
- 정본: `docs/develop/03-adapter-system.md`, `docs/develop/04-add-vendor.md`
