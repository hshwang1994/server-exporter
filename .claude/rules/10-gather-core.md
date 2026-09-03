# Gather Core 규칙 (Ansible / Python)

## 적용 대상
- `os-gather/**`, `esxi-gather/**`, `redfish-gather/**`
- `common/library/**`, `common/tasks/**`, `common/vars/**`
- `filter_plugins/**`, `lookup_plugins/**`, `module_utils/**`

## 현재 관찰된 현실

- 3-channel gather는 raw 수집 + fragment 생성으로 분리
- precheck_bundle.py 가 TCP 도달·포트를 한 번에 판정하고 프로토콜을 확인한 뒤 본 수집.
  도달성은 **TCP 응답 OR ICMP Echo 응답** 이며(2026-09-03), ICMP 는 TCP 가 전 포트 무응답일
  때만 1회 보는 보조 근거다 — Gate 가 아니다. 인증 단계는 운영 경로에서 실행되지 않는다 (rule 27)
- redfish_gather.py 는 stdlib 만 쓴다 (urllib / ssl / json). 줄 수는 적지 않는다 —
  2026-08-10 에 "3,867 → 5,082 정정" 이라 적어 뒀는데 사흘 만에 또 틀렸다
- Linux 2-tier (preflight.yml의 `_l_python_mode`로 Python ok / raw fallback 분기)

## 목표 규칙

### R1. Raw 수집과 Fragment 생성 분리

- **Default**: `gather_<section>.yml`은 외부 시스템에서 raw 데이터만 수집. fragment 변수는 별도 `set_fact` 단계 또는 `normalize_<section>.yml`에서 생성
- **Forbidden**: 한 task에서 수집 + fragment 생성 + JSON 조립을 동시 수행
- **Why**: 단계 분리 안 하면 부분 실패(authentication ok지만 일부 endpoint 미지원) 시 어떤 단계에서 막혔는지 추적 불가
- **재검토**: 단계 통합으로 명확히 단순화 가능한 케이스 발견 시

### R2. Python module은 stdlib 우선

- **Default**: `redfish-gather/library/redfish_gather.py`, `common/library/precheck_bundle.py`는 외부 라이브러리 의존 금지 (urllib / ssl / json / socket / subprocess만)
- **Allowed**: filter_plugins, lookup_plugins, module_utils는 jmespath / netaddr 등 ansible.cfg에 명시된 collection 사용 가능
- **Forbidden**: redfish library에 requests / urllib3 / paramiko 등 추가
- **Why**: Agent 환경에 라이브러리 누락 발생 시 핵심 수집 자체 실패. 의존성 최소화로 robustness 확보

### R3. 파일 / 함수 길이

- **Default**: Python 파일 500줄 이내, 함수 50줄 이내, Ansible task 한 파일 200줄 이내
- **Allowed**: redfish_gather.py 같은 단일 책임 모듈은 500줄 초과 가능 (단 함수 분리는 유지)
- **Forbidden**: 한 파일에 여러 책임 혼재 (예: precheck + gather + normalize)
- **Why**: 가독성 + 테스트 용이성 + Fragment 철학 (분리된 책임)

### R4. Linux 2-tier (raw fallback)

- **Default**: `os-gather/tasks/linux/preflight.yml`이 Python 버전 감지 → `_l_python_mode` 설정 → 본 gather가 모드별 분기
- **Allowed**: 개발/검증 시 `SE_FORCE_LINUX_RAW_FALLBACK=true`로 raw 강제
- **Forbidden**: Python 모드를 가정한 채 setup/shell만 사용 (raw 모드에서 실패)
- **Why**: RHEL 8.10 (Python 3.6) 같은 환경에서 setup 모듈 미동작. raw fallback이 필수
- **재검토**: Python 3.9+ 강제 운영 정책 확립 시

### R5. Adapter 점수 (rule 12와 연동)

- **Default**: 새 adapter는 `score = priority × 1000 + specificity × 10 + match_score` 공식 명시
- **Forbidden**: priority 임의 충돌 (같은 vendor의 dell_idrac9가 priority=10, dell_idrac=100 처럼 역순)
- **Why**: 점수 동률 시 정렬 결과 불확정 → 어떤 adapter가 선택될지 모름

### R6. Vendor 이름 하드코딩 금지 (rule 12 R1)

본 rule은 rule 12 (adapter-vendor-boundary)로 자세히 분리됨. 핵심: gather 코드에 "Dell", "HPE" 등 vendor 이름 하드코딩 금지. 분기는 adapter YAML 또는 Redfish 라이브러리의 OEM 추출 분기에서만.

## 금지 패턴

- raw 수집과 fragment 생성을 한 task에 혼합 — R1 위반
- redfish_gather.py에 외부 라이브러리 추가 — R2 위반
- 파일 800줄 이상 / 함수 100줄 이상 — R3 위반
- raw 모드 미고려한 Python 전용 gather — R4 위반
- adapter priority 충돌 — R5 위반

## 리뷰 포인트

- [ ] gather 코드와 fragment 생성이 분리됐는가
- [ ] redfish library가 stdlib만 사용하는가
- [ ] 파일 / 함수 길이 한계 준수
- [ ] Linux gather가 raw fallback 처리하는가
- [ ] adapter priority가 일관성 있는가

## 테스트 포인트

- `ansible-playbook --syntax-check` (3-channel)
- `tests/redfish-probe/probe_redfish.py` (각 vendor)
- raw fallback 검증: `SE_FORCE_LINUX_RAW_FALLBACK=true`
- 변경 영역 baseline 회귀

## 관련 문서

- rule: `11-gather-output-boundary`, `12-adapter-vendor-boundary`, `22-fragment-philosophy`, `27-precheck-guard-first`
- skill: `validate-fragment-philosophy`, `score-adapter-match`, `debug-precheck-failure`
- agent: `refactor-worker`, `fragment-engineer`, `adapter-author`, `precheck-engineer`
- 정본: `docs/develop/01-gather-structure.md`
