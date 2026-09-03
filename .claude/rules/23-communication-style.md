# AI 커뮤니케이션 스타일 규칙

> AI는 사용자에게 말할 때 **일상어 + WHY + WHAT + IMPACT + 결정 주체 명시** 원칙을 따른다.

## 적용 대상

- AI (Claude Code)가 사용자에게 보내는 모든 답변
- 특히 **승인 요청** / **결정 필요 안내** / **완료 보고** / **진행 공유**
- 사람 대상 문서 작성·수정 시 R5 육하원칙 적용

## 목표 규칙

### R1. 승인 요청 필수 포맷

승인 필요 시 **4요소 모두 포함**:

```
무엇을 바꾸나?  (한 줄, 결과 중심 — 사용자가 2초 안에 이해 가능)
왜?            (현재 문제 or 필요)
영향은?         (어느 파일 몇 개 / 어떤 vendor 몇 개 / 어떤 채널 등 숫자로)
결정 필요:      (예 / 아니오 / 조정 — 선택지 명시)
```

**Forbidden**: 4요소 중 하나라도 누락

#### 예시

##### 좋은 예 (벤더 추가 승인)

> **무엇**: 새 벤더 Huawei를 server-exporter에 추가
> **왜**: 신규 호출자가 Huawei iBMC 기반 서버 수집 요청
> **영향**: `common/vars/vendor_aliases.yml` 1줄 추가 + `adapters/redfish/huawei_*.yml` 신규 1~3개 (필요 시 라이브러리 OEM 분기). 기존 5개 vendor (Dell/HPE/Lenovo/Supermicro/Cisco) 영향 없음
> **결정 필요**: 진행 / 펌웨어 검증 우선 / 보류 중 택일

##### 나쁜 예

> `rule 12 vendor-adapter 슬롯에 Huawei 추가 승인 요청`

왜 나쁜가: rule 번호만, 영향 숫자 없음, 결정 주체 미표시

### R2. 내부 용어 괄호 주석

내부 용어는 **첫 등장 시 풀이 첨부**.

#### 어휘 치환표 (server-exporter 도메인)

| 내부 용어 (단독 금지) | 사람 친화 표현 |
|---|---|
| `rule NN` | "공통 [규칙명] 규칙 (rule NN)" |
| `task-impact-preview` | "'변경 영향 미리보기' 절차 (task-impact-preview skill)" |
| `agent` | "서브 작업자 (agent, 특정 역할의 별도 AI)" |
| `skill` | "작업 플레이북 (skill, 재사용 가능한 AI 절차)" |
| `hook` | "자동 실행 스크립트 (hook)" |
| `Tier 0/1/2/3` | "계층 0/1/2/3 (정본/진입/상세/감사)" |
| `Fragment` | "Fragment (각 gather 자기 데이터 조각)" |
| `Adapter` | "Adapter (벤더/세대별 YAML)" |
| `Adapter 점수` | "Adapter 점수 (priority×1000 + specificity×10 + match)" |
| `3-channel` | "3-채널 (os/esxi/redfish 통합 수집)" |
| `Precheck` | "사전 진단 (도달[TCP 응답 OR ICMP 응답] → 프로토콜 → 인증)" |
| `Vault 2단계` | "Vault 2단계 로딩 (무인증 detect → vendor vault → 인증 수집)" |
| `Linux 2-tier` | "Linux 2-tier (Python ok / raw fallback)" |
| `Sections 11` | "11 섹션 (system/hardware/bmc/cpu/memory/storage/network/firmware/users/power/thermal)" |
| `Field Dictionary 47 Must` | "Field Dictionary (47 Must + 115 Nice + 6 Skip = 168 entries)" |
| `Baseline` | "Baseline (실장비 회귀 기준선 JSON)" |
| `loc` | "loc (운영 사이트 — 정본은 common/vars/locations.yml)" |
| `target_type` | "target_type (os/esxi/redfish)" |
| `JSON envelope` | "JSON envelope (13 필드 — 분석 6 + 라우팅·식별 7)" |
| `Round 검증` | "Round 검증 (실장비 검증 단위)" |
| `iDRAC / iLO / XCC / CIMC` | "iDRAC (Dell BMC) / iLO (HPE) / XCC (Lenovo) / CIMC (Cisco)" |
| `squash merge` | "squash 병합 (여러 커밋을 1개로 압축)" |
| `force push` | "강제 푸시 (원격 이력 덮어쓰기 — 위험)" |
| `worktree` | "작업 트리 (같은 저장소의 평행 작업 공간)" |
| `4-Stage` | "Jenkins 4-Stage (Validate / Gather / Validate Schema / E2E Regression)" |

### R3. 결정 주체(AI vs 사람) 명시

- AI 수행: "제가(AI) ~ 했습니다 / 할 예정입니다"
- AI 제안: "제가(AI) ~ 을 **초안 제안**합니다"
- 사람 결정: "**개발자 님 / 운영 담당자 / 아키텍트 님의 결정**이 필요합니다"
- 사람 승인 완료: "사용자께서 YYYY-MM-DD 대화에서 승인하신 바에 따라 ~"

**Forbidden**:
- 수동태로 주체 은폐 ("~ 됩니다", "결정됩니다")
- 주어 없이 결정 선언
- "추천합니다" 만 있고 결정 주체 누락

### R4. 완료 보고 6체크 (rule 24 참조)

상세는 rule 24 (completion-gate). 본 rule은 어휘만:
- 6체크 통과 전 "완료" / "끝났다" / "완결" / "다 했다" 사용 금지

### R5. 육하원칙 (사람용 문서)

사람 대상 문서 (ADR / 기획서 / 리뷰 요약 / 장애 보고서) 새로 만들 때 5W1H 중 최소 4요소 이상 포함.

**Allowed (예외)**: AI 전용 (`.claude/rules/`, `.claude/skills/`, `.claude/agents/`)는 컨텍스트 효율 위해 간결.

### R6. 사람 친화 vs AI 친화

| 상대 | 어휘 | 문장 |
|---|---|---|
| 사람 | 약어 풀어쓰기 | 완결된 문장 |
| AI | 약어 허용 | 단어 나열 허용 (컨텍스트 절약) |

### R7. 풀이 첨부 필수 어휘 12 범주

1. 규칙 번호 / 2. Skill / 3. Agent / 4. Policy 파일 / 5. Catalog 파일 / 6. ADR 번호 / 7. Git 용어 / 8. 하네스 용어 / 9. 상태 (Proposed/Accepted/Deprecated) / 10. 기술 약어 (BMC/iDRAC/IPMI/vSphere/WinRM 등) / 11. 티켓 표기 / 12. Fail 표기

### R8. 상태 표시는 ASCII 태그 통일

상태/카테고리는 이모지 대신 ASCII 태그.

| 태그 | 의미 |
|---|---|
| `[PASS]` | 성공 |
| `[FAIL]` | 실패 |
| `[OK]` | 정상 |
| `[NG]` | 문제 |
| `[SKIP]` | 건너뜀 |
| `[DEL]` | 삭제됨 |
| `[NEW]` | 신규 |
| `[MOD]` | 수정 |
| `[WIP]` | 진행 중 |
| `[HOLD]` | 보류 |
| `[TODO]` | 할 일 |
| `[WARN]` | 경고 |
| `[INFO]` | 참고 |
| `[CRIT]` | 치명 |

**Forbidden**: 이모지 (`✅`, `❌`, `🗑`, `⏸`, `🔄`) — 폰트별 폭 차이로 표 정렬 깨짐

## 금지 패턴

- 4요소 중 누락 — R1
- 약어 단독 (첫 등장 풀이 없이) — R2 / R7
- 결정 주체 생략 / 수동태 — R3
- 6체크 전 "완료" — R4
- 사람 문서에서 5W1H 중 2개 이상 누락 — R5
- 사람 문서에 AI체 / AI 문서에 사람체 — R6
- 이모지로 상태 표시 — R8

## 리뷰 포인트

- [ ] 승인 요청에 4요소 (R1)
- [ ] 내부 용어 풀이 (R2 / R7)
- [ ] 결정 주체 명시 (R3)
- [ ] 5W1H (R5, 사람 문서)
- [ ] ASCII 태그 (R8)

## 관련

- rule: `24-completion-gate`
- 정본: `CLAUDE.md` §13
