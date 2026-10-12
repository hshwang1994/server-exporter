# common/: 세 채널 공통 로직

Linux와 Windows(os-gather), ESXi(esxi-gather), Redfish(redfish-gather)가 공유하는 사전 진단, 자격증명 로딩, 정규화 빌더, 변수 정본이 있습니다.

## 디렉터리

```text
common/
├── library/
│   └── precheck_bundle.py         사전 진단 모듈 (도달 → 포트 → 프로토콜). 표준 라이브러리만 씁니다
├── tasks/
│   ├── precheck/run_precheck.yml  precheck_bundle 호출과 diagnosis 변수 설정
│   ├── credential/                vault 경로 결정과 로딩 (OS, ESXi 는 resolve_and_load.yml, Redfish 는 resolve_and_load_redfish.yml)
│   ├── normalize/                 fragment 정규화 빌더 (tasks/normalize/README.md)
│   └── addon/run_addon.yml        추가 수집(Add-on) hook (docs/develop/07-addon-hook.md)
└── vars/
    ├── supported_sections.yml     섹션 11종과 채널별 지원 섹션
    ├── vendor_aliases.yml         벤더 정규화 (대표 이름과 별칭, 호출자 표시값)
    ├── locations.yml              실행 위치(loc)와 Runner 라벨
    ├── failure_reasons.yml        실패 사유 문장 카탈로그 (failure_reason 정본)
    └── section_messages.yml       섹션별 오류 문장
```

## 책임

| 영역 | 책임 |
|---|---|
| `library/precheck_bundle.py` | 진단 알고리즘. 관리 TCP → (무응답일 때만) ICMP → 프로토콜 확인. 자격증명은 받지 않습니다 |
| `tasks/precheck/run_precheck.yml` | Python 모듈을 부르고 결과를 `_diagnosis` 변수에 둡니다 |
| `tasks/credential/` | `loc`와 대상 종류로 vault 파일 하나를 정해 엽니다. 다른 위치나 벤더로 넘어가지 않습니다 |
| `tasks/normalize/` | fragment → 누적 변수 → 봉투 13 필드 |
| `vars/` | 코드가 읽는 변수 정본. 벤더 이름과 위치 이름이 코드에 하드코딩되지 않게 합니다 |

사전 진단이 Python과 Ansible 두 곳에 있는 것은 계층 분리입니다. Python은 어떻게 진단하는지, Ansible은 언제 부르고 결과를 어디에 두는지를 맡습니다.

## 디버깅

사전 진단이 어디서 막혔는지는 결과 봉투의 `diagnosis`(`reachable`, `port_open`, `protocol_supported`, `failure_stage`)와 `diagnosis.details`에 있습니다. 읽는 법은 `docs/contract/04-failure-and-diagnosis.md`, 진입점은 `docs/develop/06-debugging.md`입니다.

## 관련 문서

- `docs/develop/01-gather-structure.md`: 세 채널과 common 의 관계
- `docs/develop/02-normalize-flow.md`: fragment 정규화 과정
- `docs/operate/05-vault.md`: 자격증명 파일 배치
- `tasks/normalize/README.md`: 빌더 역할표
