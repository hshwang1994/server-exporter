# Gather 엔지니어 역할

## 역할 설명
Ansible 기반 3-channel 서버 정보 수집 개발. 각 채널이 자기 fragment만 만들고, 공통 정규화 파이프라인이 병합한다 (Fragment 철학). Linux/Windows OS / ESXi / Redfish (BMC) 프로토콜로 raw 수집 후 build_*.yml로 표준화.

## 주요 영역
- `os-gather/site.yml` — 4-Play (포트감지 → 감지실패 OUTPUT → Linux → Windows) + tasks/{linux,windows}/gather_*.yml (각 6개 섹션)
- `esxi-gather/site.yml` — 1-Play, community.vmware 의존
- `redfish-gather/site.yml` — 1-Play (precheck → detect → adapter → collect → normalize)
- `redfish-gather/library/redfish_gather.py` — Python Redfish API 엔진 (약 3,830줄, stdlib only)
- `common/library/precheck_bundle.py` — 진단(도달[TCP 응답 OR ICMP 응답] → 프로토콜 → 인증)
- `filter_plugins/`, `lookup_plugins/`, `module_utils/` — Ansible custom plugin
- `adapters/{redfish,os,esxi}/` — 벤더/세대별 YAML adapter

## 로드할 ai-context 문서
1. `.claude/ai-context/gather/convention.md` — Fragment 철학, 명명 규칙, raw vs fragment 분리
2. `.claude/ai-context/output-schema/convention.md` — sections.yml + field_dictionary.yml 매핑 (gather 산출물 → output)
3. `.claude/ai-context/vendors/{dell,hpe,lenovo,supermicro,cisco}.md` — 벤더 OEM 특이사항
4. `.claude/ai-context/external/integration.md` — Redfish / IPMI / SSH / WinRM / vSphere
5. `docs/ai/catalogs/PROJECT_MAP.md`
6. `.claude/ai-context/common/repo-facts.md`

## 정본 reference (덮어쓰지 말 것)
- rule 22 (fragment-philosophy) — Fragment 철학 정본
- `docs/develop/01-gather-structure.md` — 3-channel 구조
- `docs/develop/02-normalize-flow.md` — Fragment 정규화 흐름
- `docs/develop/03-adapter-system.md` — Adapter 점수 / 매트릭스
- `docs/contract/04-failure-and-diagnosis.md` — Precheck 4단계

## 자주 사용하는 Skills
| Skill | 용도 |
|-------|------|
| `task-impact-preview` | 코드 변경 전 영향 미리보기 (rule 91) |
| `validate-fragment-philosophy` | 다른 gather의 fragment 침범 안 했는지 검증 |
| `score-adapter-match` | Adapter 점수 디버깅 (-vvv 분석) |
| `add-new-vendor` | 새 벤더 추가 3단계 가이드 |
| `probe-redfish-vendor` | 새 펌웨어 프로파일링 (deep_probe_redfish.py) |
| `debug-precheck-failure` | Precheck 4단계 어디서 막혔는지 |
| `review-existing-code` | 기존 코드 4축 리뷰 |
| `prepare-regression-check` | 회귀 테스트 대상 선정 |
| `write-quality-tdd` | TDD 작성 (Python 모듈 부분) |

## 자주 사용하는 Agents
| Agent | 용도 |
|-------|------|
| `refactor-worker` | 3-channel gather 리팩토링 |
| `fragment-engineer` | Fragment 철학 보호 / merge_fragment 검증 |
| `adapter-author` | 벤더 adapter YAML 작성 |
| `vendor-onboarding-worker` | 새 벤더 추가 (vendor_aliases + adapter + OEM tasks) |
| `precheck-engineer` | precheck_bundle.py 4단계 |
| `adapter-boundary-reviewer` | 벤더 경계 위반 검토 |
| `vendor-boundary-guardian` | gather 코드에 vendor 하드코딩 검출 |
| `qa-regression-worker` | 변경 후 baseline 회귀 |

(cycle-011: security-reviewer agent 제거 + rule 60 해제)

## 주의사항 (Critical)
- **Fragment 철학 (rule 22)**: 각 gather는 자기 fragment만 만든다. 5 공통 변수 (`_data_fragment` / `_sections_supported_fragment` / `_sections_collected_fragment` / `_sections_failed_fragment` / `_errors_fragment`) 사용 — 변수 이름은 모든 gather 동일, **값**으로 자기 섹션을 채움. 누적 변수 (`_collected_data` 등) 직접 수정 금지.
- **벤더 경계 (rule 12)**: gather 코드에 벤더 이름 (Dell/HPE/Lenovo/...) 하드코딩 금지. 벤더 분기는 `adapters/` YAML 또는 Redfish 라이브러리의 `_extract_oem_*` 안에만.
- **Vault 2단계 로딩 (Redfish)**: 1단계 무인증으로 ServiceRoot detect → vendor 결정 → 2단계 vendor vault 로드 후 인증 수집.
- **Linux 2-tier (preflight.yml)**: `_l_python_mode`로 Python 3.9+ vs raw fallback 자동 분기. raw 경로는 `raw` 모듈만 remote 실행, controller-side `set_fact`/Jinja2 파싱 허용.
- **merge_fragment.yml 호출**: 각 gather 후에 반드시 호출해야 누적 병합됨.
- **새 섹션 추가**: `schema/sections.yml` + `schema/field_dictionary.yml` + `schema/baseline_v1/` 3종 동반 갱신.
