---
paths:
  - "docs/**/*.md"
  - ".claude/skills/**/*.md"
  - ".claude/agents/**/*.md"
  - "prototypes/**/*.md"
---
# Mermaid 시각화 규칙

## 규칙 표기 구조

본 rule의 각 항목은 **Default / Allowed / Forbidden + Why + 재검토 조건** 3단 구조.

## 적용 대상

- `docs/**/*.md` 중 ` ```mermaid ` 블록 포함 파일
- `.claude/skills/**/*.md`, `.claude/agents/**/*.md` 예시 블록
- `prototypes/**/*.md` (해당 시)

## 현재 관찰된 현실

- 다이어그램 다수가 `docs/` 문서에 분산
- 폰트별 폭 차이로 이모지 사용 시 표 정렬 깨짐 사고
- 색상 미지정 시 디스플레이 환경별 가독성 차이

## 목표 규칙

### R1. 다이어그램 유형 선택은 "목적" 기반

- **Default**: 전달 목적에 따라 타입 선택
  | 전달 목적 | 권장 타입 |
  |---|---|
  | 분기 / 판단 / 프로세스 흐름 | flowchart |
  | 시간축 상호작용 (외부 연동, callback) | sequenceDiagram |
  | 상태 전이 (precheck 4단계, gather lifecycle) | stateDiagram-v2 |
  | 데이터 구조 (sections × fields × baseline) | erDiagram |
  | 일정·배치 타임라인 | gantt |
  | 이벤트 순서 이력 (Round 진행) | timeline |
  | 후보안 평가 | quadrantChart |
  | 양적 흐름 (벤더 어댑터 매트릭스) | sankey |
  | 모듈 의존성 | block-beta 또는 flowchart BT |
- **Allowed**: 한 다이어그램에 두 목적 (예: 흐름 + 일부 데이터 구조) 시 주 목적 우선
- **Forbidden**: flowchart로 모든 목적 강제 (특히 시간축 / 상태 전이)
- **Why**: 타입 일치 시 독자가 다이어그램 의도를 즉시 파악. 잘못된 타입은 해석 비용 증가
- **재검토**: mermaid 신규 타입 추가 시

### R2. 가시성 강제

- **Default**: 모든 style/classDef에 다음 적용
  ```
  color:#000, stroke-width:2px, fill:<파스텔 색>
  ```
- **Allowed**: dark theme 환경에서 color 별도 지정
- **Forbidden**: 텍스트 색 미지정 (디스플레이 환경별 가독성 차이)
- **Why**: 사용자 환경별 brightness 차이로 텍스트가 안 보이는 사고 방지
- **재검토**: mermaid theme 시스템 정착 시

### R3. 색상 팔레트

- **Default**:
  | 의미 | fill | stroke |
  |---|---|---|
  | OK / 신규 / 성공 | `#dfd` | `#3c3` |
  | NG / 실패 / 제거 | `#fdd` | `#c33` |
  | 대기 / 분기 | `#ffd` | `#c93` |
  | 시작 / 진입 | `#eee` | `#999` |
  | 외부 시스템 (Redfish/IPMI/SSH/WinRM/vSphere) | `#def` | `#39c` |
- **Allowed**: 같은 의미의 노드는 동일 색상
- **Forbidden**: 의미와 무관한 색상 (예: 성공 노드를 빨간색)
- **Why**: 색상 일관성 → 다이어그램 간 cross-reference 가능
- **재검토**: 색맹 접근성 정책 도입 시

### R4. 노드 형상 (시작·종료·외부)

- **Default**:
  - 시작/종료: `([텍스트])` stadium
  - 외부 시스템: `[[텍스트]]` subroutine
  - 결정: `{텍스트}`
  - DB/저장소: `[(텍스트)]`
- **Allowed**: 같은 의미는 같은 형상
- **Forbidden**: 무작위 형상 사용
- **Why**: 형상으로 노드 종류를 즉시 식별
- **재검토**: 신규 형상 추가 시

### R5. 노드 ID는 의미 기반

- **Default**: ID는 영문 + 의미 (`START_GATHER`, `CHECK_AUTH`, `SAVE_BASELINE`, `FAIL_PRECHECK`)
- **Allowed**: subgraph 내 단순 ID는 짧게 (`A1`, `B2` — 단 라벨이 의미 가짐)
- **Forbidden**: A, B, C, X1 같은 단독 약어 (의미 추적 불가)
- **Why**: 다이어그램 수정 시 어떤 노드가 무엇인지 ID만으로 추정 가능
- **재검토**: ID 자동 생성 도구 도입 시

### R6. 라벨 규칙

- **Default**:
  - 설명형 한국어
  - 특수문자 포함 시 쌍따옴표
  - 노드 1개 3줄 이내
- **Allowed**: 영문 기술 용어 (예: `Redfish API`)
- **Forbidden**: 노드 라벨 4줄 이상 (다이어그램 비대화)
- **Why**: 라벨이 길면 다이어그램 가독성 급락
- **재검토**: 폰트 폭 변경 시

### R7. 30 노드 / 6 단계 이내

- **Default**: 한 다이어그램에 30 노드 / 6 단계 이내
- **Allowed**: 초과 시 subgraph로 그룹화 또는 별도 다이어그램 분리
- **Forbidden**: 30 노드 초과 + subgraph 미사용 (한눈에 파악 불가)
- **Why**: 인간 작업 메모리 한계 (Miller's law 7±2). 분할이 가독성에 도움
- **재검토**: 인터랙티브 mermaid (zoom/pan) 도입 시

### R8. 성공 / 실패 / 재시도 모두 표시

- **Default**: flowchart에서 성공 / 실패 / 재시도 / 롤백 경로 모두
- **Allowed**: trivially 단순한 흐름은 성공만 (단 "실패 없음" 주석 추가)
- **Forbidden**: 성공만 표시 + 실패 경로 묵시 (실패 분석 불가)
- **Why**: 다이어그램 목적은 의사결정 지원. 실패 경로 누락 시 trouble-shooting 불가
- **재검토**: 자동 실패 경로 추출 도구 도입 시

### R9. AS-IS / TO-BE 쌍 (변경 시)

- **Default**: 기존 변경 / 리팩토링 다이어그램은 AS-IS ↔ TO-BE 쌍
- **Allowed**: TO-BE만 있는 신규 기능
- **Forbidden**: AS-IS 없이 TO-BE만 (변경 의도 불명)
- **Why**: 변경 비교가 핵심. AS-IS 없으면 "왜 바꿨는지" 추적 불가
- **재검토**: git diff 자동 다이어그램화 도입 시

### R10. 벤더 분기 표현

- **Default**: subgraph로 vendor profile 분리
  ```
  subgraph profile-default
  subgraph profile-dell
  subgraph profile-hpe
  subgraph profile-lenovo
  subgraph profile-supermicro
  subgraph profile-cisco
  ```
- **Allowed**: common 다이어그램은 "분기가 어디" 만 표시. 실 구현은 vendor-specific 별도
- **Forbidden**: vendor별 다이어그램에 다른 vendor 분기 혼재
- **Why**: rule 12 (vendor 경계) 정신을 다이어그램에도 적용
- **재검토**: vendor 추가 시 자동 다이어그램 생성 도입 시

### R11. 상단·하단 문맥 의무

- **Default**:
  - 앞: `> 이 그림이 말하는 것: <한 문장>`
  - 뒤: `> 읽는 법: 방향 ..., 색 ..., 핵심 분기 ...`
- **Allowed**: 본문이 바로 위/아래에서 충분히 설명하면 생략
- **Forbidden**: 다이어그램 단독 + 문맥 부재
- **Why**: 독자가 다이어그램 단독 인용 시 이해 가능해야 함
- **재검토**: 자동 문맥 생성 도구 도입 시

### R12. 범례 (3색+ 사용 시)

- **Default**: 3색 이상 사용 시 LEGEND subgraph 첨부
  ```mermaid
  flowchart TD
    subgraph LEGEND ["범례"]
      L1([시작/종료]):::ok
      L2[일반 단계]
      L3{결정 분기}:::warn
      L4[실패]:::ng
      L5[(저장소)]
    end
  ```
- **Allowed**: 1~2색은 본문 설명으로 충분
- **Forbidden**: 3색 이상 + 범례 부재
- **Why**: 색상 의미는 인접 다이어그램이 다를 수 있어 매번 명시
- **재검토**: 통일 색상 팔레트가 모든 문서에 적용 시

### R13. 문법 호환성

- **Default**:
  - `graph TD` / `flowchart TD` 둘 다 허용. 신규는 `flowchart` 권장
  - 점선: `-.->` 또는 `-. "label" .->`
- **Allowed**: 기존 `graph TD` 유지
- **Forbidden**:
  - `classDef`와 `style`을 같은 노드에 동시 사용
  - 고립 노드 (다이어그램 밖에 떠 있는 노드)
- **Why**: 동시 사용은 mermaid 렌더러 버전별 처리 다름
- **재검토**: mermaid 메이저 버전 업그레이드 시

### R14. sequenceDiagram 규칙

- **Default**:
  - 한국어 alias
  - 메시지 라벨 한국어
  - alt/opt/loop 2단계 이내
  - Note over에 비즈니스 설명
- **Forbidden**: alt 3단계 이상 중첩
- **Why**: 시간축 추적이 본 목적. 중첩 깊을수록 추적 비용 급증
- **재검토**: 도구 지원 시

### R15. stateDiagram-v2 규칙

- **Default**:
  - 상태명 대문자 스네이크 (`PRECHECK_PING`)
  - `[*]` 시작/종료
  - 전이 라벨에 트리거
- **Forbidden**: 시작/종료 누락
- **Why**: 명확한 진입/종료 지점이 상태 다이어그램의 의미
- **재검토**: 상태 자동 추출 도입 시

### R16. gantt 규칙

- **Default**:
  - title 한국어
  - dateFormat YYYY-MM-DD
  - section 그룹화
- **Forbidden**: 상대 날짜 (rule 70 R3)
- **Why**: 절대 날짜로 시간 경과 후 해석 가능
- **재검토**: 자동 일정 추출 도입 시

### R17. erDiagram 규칙

- **Default**:
  - 관계식 한 줄당 하나
  - 카디널리티 일관 (`||--o{` 1:N)
  - self-reference 시 노드명 2번
- **Forbidden**: 카디널리티 혼재 (1:N과 N:M 혼합 표기)
- **Why**: 데이터 모델 정확성
- **재검토**: schema 자동 추출 도입 시

### R18. ASCII 태그 통일 (rule 23 R8 연동)

- **Default**: 다이어그램 안 상태 표시는 이모지 대신 ASCII 태그 (`[OK]`, `[FAIL]`, `[SKIP]`, `[WARN]`)
- **Forbidden**: 이모지 (`✅`, `❌`, `🗑`, `⏸`, `🔄`)
- **Why**: 폰트별 폭 차이로 표/다이어그램 정렬 깨짐. mermaid 환경에서 더 두드러짐
- **재검토**: 모든 문서가 일관된 폰트 환경 보장 시

## 금지 패턴

- 텍스트 색 미지정 — R2
- flowchart로 모든 목적 강제 — R1
- 약어만의 노드 라벨 — R5
- 라벨 4줄 이상 — R6
- 30 노드 초과 + subgraph 미사용 — R7
- 성공 경로만 — R8
- AS-IS 없이 TO-BE만 — R9
- vendor 분기 혼재 — R10
- 문맥 부재 — R11
- 3색 + 범례 부재 — R12
- classDef + style 중복 — R13
- 이모지로 상태 표시 — R18

## 리뷰 포인트

- [ ] 타입이 목적에 맞는가 — R1
- [ ] color #000 + stroke-width 2px — R2
- [ ] 색상 팔레트 일관 — R3
- [ ] 노드 ID 의미 기반 — R5
- [ ] 30 노드 / 6 단계 이내 — R7
- [ ] 성공/실패/재시도 — R8
- [ ] AS-IS/TO-BE (해당 시) — R9
- [ ] 상단·하단 문맥 — R11
- [ ] ASCII 태그 — R18

## 관련

- rule: `23-communication-style` R8 (ASCII 태그)
- skill: `mermaid-visualization`
- agent: `flow-visualizer`, `flowchart-reviewer`, `flow-visualizer`
