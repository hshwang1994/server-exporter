# 문서 지도

server-exporter 문서는 읽는 목적에 따라 다섯 갈래로 나뉜다. 경로만 봐도 어디를 읽어야
하는지 알 수 있게 해 뒀다.

| 갈래 | 누구에게 | 무엇이 들어 있나 |
|---|---|---|
| `overview/` | 처음 온 사람 | 이 시스템이 왜 있는지, 전체가 어떻게 맞물리는지 |
| `operate/` | 인프라·운영 담당 | Jenkins·에이전트 구축, 잡 등록, 자격증명 관리, 현장 작업 |
| `contract/` | 호출자 시스템 개발자 | 무엇을 보내고 무엇을 받는지. 필드 하나하나의 의미 |
| `develop/` | 이 저장소를 고치는 사람 | 수집 코드 구조, 벤더 추가, 디버깅 |
| `reference/` | 검증·이력 추적 | 벤더별 지원 현황, 실장비 검증 결과, 결정 기록 |

## 처음이라면

1. [overview/01-what-and-why.md](overview/01-what-and-why.md) — 이 시스템이 푸는 문제
2. [overview/02-architecture.md](overview/02-architecture.md) — 전체 그림

이 둘이면 "무슨 시스템인지" 는 잡히고 그다음은 역할에 따라 갈린다.

## 역할별 읽는 순서

**운영을 맡았다면**
[operate/01-jenkins-master.md](operate/01-jenkins-master.md) →
[02-agent-node.md](operate/02-agent-node.md) →
[03-job-registration.md](operate/03-job-registration.md) →
[05-vault.md](operate/05-vault.md)

**호출자 시스템을 붙인다면**
[contract/01-input.md](contract/01-input.md) →
[02-output-envelope.md](contract/02-output-envelope.md) →
[03-fields.md](contract/03-fields.md) →
[04-failure-and-diagnosis.md](contract/04-failure-and-diagnosis.md)

**코드를 고친다면**
[develop/01-gather-structure.md](develop/01-gather-structure.md) →
[02-normalize-flow.md](develop/02-normalize-flow.md) →
[03-adapter-system.md](develop/03-adapter-system.md) →
[04-add-vendor.md](develop/04-add-vendor.md)

**장애를 보고 있다면**
[develop/06-debugging.md](develop/06-debugging.md) 부터. 실패 봉투의 의미는
[contract/04-failure-and-diagnosis.md](contract/04-failure-and-diagnosis.md) 에 있다.

## 전체 목록

### overview
- [01-what-and-why.md](overview/01-what-and-why.md) — 문제 정의와 세 가지 약속
- [02-architecture.md](overview/02-architecture.md) — 호출부터 응답까지 전체 흐름

### operate
- [01-jenkins-master.md](operate/01-jenkins-master.md) — Jenkins 마스터 구축
- [02-agent-node.md](operate/02-agent-node.md) — 실행 노드 구축
- [03-job-registration.md](operate/03-job-registration.md) — 잡 등록
- [04-pipeline-runtime.md](operate/04-pipeline-runtime.md) — 파이프라인이 실제로 하는 일
- [05-vault.md](operate/05-vault.md) — 자격증명 보관과 회전
- [06-rmc-activation.md](operate/06-rmc-activation.md) — HPE RMC Redfish 활성화
- [07-onsite-capture.md](operate/07-onsite-capture.md) — 폐쇄망 반입 캡처
- [08-ansible-config.md](operate/08-ansible-config.md) — 프로젝트 Ansible 설정

### contract
- [01-input.md](contract/01-input.md) — 호출자가 보내는 것
- [02-output-envelope.md](contract/02-output-envelope.md) — 돌려받는 봉투의 모양
- [03-fields.md](contract/03-fields.md) — 필드 사전
- [04-failure-and-diagnosis.md](contract/04-failure-and-diagnosis.md) — 실패했을 때 무엇을 보나

### develop
- [01-gather-structure.md](develop/01-gather-structure.md) — 채널별 수집 구조
- [02-normalize-flow.md](develop/02-normalize-flow.md) — 조각을 모아 봉투를 만드는 과정
- [03-adapter-system.md](develop/03-adapter-system.md) — 어댑터 선택 규칙
- [04-add-vendor.md](develop/04-add-vendor.md) — 벤더·세대 추가
- [05-field-mapping.md](develop/05-field-mapping.md) — 원본에서 필드까지의 매핑
- [06-debugging.md](develop/06-debugging.md) — 어디부터 볼 것인가

### reference
- [compatibility-matrix.md](reference/compatibility-matrix.md) — 벤더 × 세대 × 섹션 지원표
- [live-validation.md](reference/live-validation.md) — 실장비 검증 결과
- [decision-log.md](reference/decision-log.md) — 왜 지금 이 모습인지

## 이 문서들이 지키는 것

섹션 11종, 봉투 13필드, `failure_stage` 6종 같은 건 호출자와의 약속이라 적는다.
어댑터 개수나 테스트 개수는 하나만 늘어도 틀리니 적지 않고 대신 세는 방법을 적어 둔다.
숫자는 계약인 것만 적는다.

**진술에는 근거가 붙는다.** 코드에서 확인했으면 `파일:줄`을 가리킨다. 장비 쪽은 검증 기록이다.

AI 협업용 문서는 개발 저장소에만 따로 있고 배포본에는 포함되지 않으니 이 디렉터리의
문서는 그쪽을 참조하지 않는다 — 참조하면 배포본에서 끊긴 링크가 된다.
