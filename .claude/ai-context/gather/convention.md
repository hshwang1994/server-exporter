# Gather Convention — server-exporter

> 3-channel gather (os/esxi/redfish) 작업 컨벤션.
> 정본: rule 22 (fragment-philosophy) (Fragment 철학 / 새 gather 템플릿 / 변수 네이밍).

## 0. 정본 reference

본 문서는 인덱스. 본문은 정본 참조 (rule 70 중복 보존 금지):

- rule 22 (fragment-philosophy) — Fragment 철학, 변수 네이밍, 실패 처리 패턴
- `docs/develop/01-gather-structure.md` — 3-channel 구조
- `docs/develop/02-normalize-flow.md` — Fragment 정규화 흐름
- `docs/contract/04-failure-and-diagnosis.md` — block/rescue/always 실패 처리
- `docs/contract/04-failure-and-diagnosis.md` — 4단계 진단

## 1. Fragment 철학 (rule 22)

각 gather는 **자기 fragment만** 만든다. 5 공통 변수 사용 (변수 이름은 동일, 값으로 자기 섹션을 채움):
- `_data_fragment` — 섹션별 raw 데이터 dict
- `_sections_supported_fragment` — 지원 섹션 list
- `_sections_collected_fragment` — 수집 성공 섹션 list
- `_sections_failed_fragment` — 수집 실패 섹션 list
- `_errors_fragment` — 수집 오류 list

`merge_fragment.yml`이 누적 병합 → 공통 builder가 최종 JSON 조립.

**Forbidden**: 누적 변수 (`_collected_data` 등) 직접 수정. 다른 gather 섹션을 자기 fragment에 포함.

```yaml
# WRONG — 누적 변수 직접 수정 (merge_fragment.yml 영역)
- set_fact:
    _collected_data: "{{ _collected_data | combine(...) }}"

# WRONG — 다른 gather의 섹션을 자기 fragment에 포함
- set_fact:
    _sections_collected_fragment: ['cpu', 'memory']  # memory는 다른 gather 영역

# CORRECT — 자신의 fragment만 (5 공통 변수)
- set_fact:
    _data_fragment:
      cpu: {...}
    _sections_supported_fragment: ['cpu']
    _sections_collected_fragment: ['cpu']
    _sections_failed_fragment: []
```

## 2. 명명 규칙

| 패턴 | 위치 | 용도 |
|---|---|---|
| `gather_<section>.yml` | `os-gather/tasks/{linux,windows}/`, `esxi-gather/tasks/`, `redfish-gather/tasks/` | raw 수집 |
| `normalize_<section>.yml` | `esxi-gather/tasks/` 등 | 채널-specific 정규화 |
| `build_<artifact>.yml` | `common/tasks/normalize/` | 공통 builder (sections / status / errors / meta / correlation / output) |
| `precheck_*.yml` | gather entry | 본 수집 전 4단계 진단 |
| `_*_fragment` | set_fact 변수 | fragment 변수 prefix `_` (5 공통 이름) |

## 3. 새 gather 추가 (template)

rule 22 (fragment-philosophy) "새 gather 템플릿" 섹션 그대로 따른다. 핵심:

1. `gather_<section>.yml` 또는 `collect_<section>.yml` 작성 (raw 수집)
2. Fragment 변수 set_fact (5 공통 변수 — `_data_fragment`, `_sections_supported_fragment`, `_sections_collected_fragment`, `_sections_failed_fragment`, `_errors_fragment`)
3. `normalize_<section>.yml` 또는 `common/tasks/normalize/build_<section>.yml` 작성
4. `merge_fragment.yml` 호출 확인
5. `common/vars/supported_sections.yml` 업데이트
6. `schema/sections.yml` + `schema/fields/*.yml` 추가
7. Baseline JSON 예시 추가 + 문서 갱신

## 4. Linux 2-tier (Python 감지 + Raw Fallback)

`os-gather/tasks/linux/preflight.yml`이 `_l_python_mode` 자동 설정:

| 모드 | 조건 | 수집 방식 |
|---|---|---|
| `python_ok` | Python 3.9+ | 기존 Python 경로 (setup/shell/command/getent) |
| `python_missing` / `python_incompatible` | 미설치 또는 3.8↓ | raw-only |
| `raw_forced` | `SE_FORCE_LINUX_RAW_FALLBACK=true` | raw-only (개발/검증) |

raw 경로 원칙:
- remote는 `raw` 모듈만, controller-side `set_fact`/Jinja2 파싱 허용
- 6 섹션 모두 수집 가능, JSON 스키마 호환 100%
- `diagnosis.details`에 `gather_mode` + `python_version` 추가
- SELinux: `getenforce` → `enabled`/`disabled` 정규화 (Round 2 수정)
- Memory raw 경로는 dmidecode 기반 → `physical_installed` (Python 경로의 `os_visible`보다 정밀)

## 5. Vault 2단계 로딩 (Redfish 특화)

```yaml
# 1단계: 무인증으로 ServiceRoot detect
- redfish_gather:
    ip: "{{ target_ip }}"
    # 계정 없음 (ServiceRoot 무인증)
  register: _rf_probe

# 2단계: 자격증명 해석 → vault 적재
#   경로를 직접 조립하지 않는다. credential_resolver lookup 이 location/vendor 로
#   표준(전역 1벌)과 복구(loc x vendor) 두 축을 각각 해석한다.
- include_tasks: common/tasks/credential/resolve_and_load_redfish.yml
  vars:
    _cred_target_type: redfish
    _cred_vendor: "{{ _rf_detected_vendor }}"

# 3단계: 인증으로 재수집
- redfish_gather:
    ip: "{{ target_ip }}"
    username: "{{ (_rf_standard_accounts | first).username }}"
    password: "{{ (_rf_standard_accounts | first).password }}"
```

## 6. Adapter 점수

```
score = priority × 1000 + specificity × 10 + match_score
```

priority:
- generic = 0
- 기본 vendor = 10
- 세대별 = 50~100
- 구체적 모델 = match.model_patterns + 높은 specificity

## 7. 4단계 Precheck (precheck_bundle.py)

```
도달/포트(TCP 응답 OR ICMP 응답) → 프로토콜 → 인증(운영 미실행)
```

ICMP 는 Gate 가 아니다 — TCP 가 응답하면 호출조차 하지 않고, TCP 전 포트 무응답일 때만
Echo 1회를 본다 (rule 27 R1).

각 단계 실패 시 `diagnosis.details`에 어디서 막혔는지 기록 + graceful degradation.

## 8. 자주 호출하는 Skill / Agent

- `task-impact-preview` — 코드 변경 전 영향
- `validate-fragment-philosophy` — 다른 gather fragment 침범 검증
- `score-adapter-match` — 점수 디버깅
- `add-new-vendor` — 벤더 추가 3단계
- `probe-redfish-vendor` — 새 펌웨어 프로파일링
- agent: `refactor-worker`, `fragment-engineer`, `adapter-author`, `vendor-onboarding-worker`, `precheck-engineer`
