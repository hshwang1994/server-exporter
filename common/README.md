# common/ — 3 채널 공통 로직

> Linux/Windows OS gather, ESXi gather, Redfish gather 가 공유하는 precheck / normalize / fragment 빌더 / Python 모듈 / 변수.

## 디렉터리 구성

```text
common/
├── library/                    # Python 모듈 (Ansible custom modules)
│   └── precheck_bundle.py     # 4단계 진단 (ping → port → protocol → auth)
├── tasks/
│   ├── precheck/
│   │   └── run_precheck.yml   # precheck_bundle 호출 + diagnosis 생성
│   └── normalize/             # Fragment 정규화 빌더 (10 파일 — 핵심 빌더 8 + 실패 경로 보조 2) — README 별도
└── vars/
    ├── supported_sections.yml # 10 sections 정본
    ├── vendor_aliases.yml     # vendor 정규화 정본
    └── status_rules.yml       # status 판정 보조 규칙
```

## 책임 분리

| 영역 | 책임 |
|---|---|
| `library/precheck_bundle.py` | Python 4단계 진단 엔진 (stdlib only) |
| `tasks/precheck/run_precheck.yml` | Ansible wrapper — Python 모듈 호출 + diagnosis 변수 set |
| `tasks/normalize/build_*.yml` | Fragment → 누적 변수 → envelope 13 필드 빌더 |
| `vars/supported_sections.yml` | 10 sections enum |
| `vars/vendor_aliases.yml` | 벤더 정규화 매핑 (canonical: ['alias', ...]) |

## 왜 precheck 가 Python + Ansible 두 곳에 분산되어 있나

Python 모듈 (`precheck_bundle.py`) 가 4단계 진단 핵심 로직을 담당하고 (testable, stdlib only),
Ansible task (`run_precheck.yml`) 는 그 결과를 받아 `_diagnosis` 변수에 set + ansible 인벤토리와 통합하는 역할.

즉 분산이 아니라 **계층 분리**:

- Python: 알고리즘 (어떻게 진단)
- Ansible: orchestration (언제 호출 + 결과 어디에 저장)

## 디버깅 진입점

precheck 4단계 어디서 막혔는지 확인:

```bash
ansible-playbook ... -vvv | grep -i precheck
```

또는 envelope `diagnosis.details` 참조 (docs/12).

## 관련 문서

- `docs/06_gather-structure.md` — 3 채널 + common 구조
- `docs/07_normalize-flow.md` — Fragment 정규화 과정
- `docs/11_precheck-module.md` — 4단계 진단 상세
- `docs/23_debugging-entrypoints.md` — 디버깅 매트릭스
- `tasks/normalize/README.md` — 8 빌더 역할표
