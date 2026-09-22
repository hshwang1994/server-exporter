# ADR 2026-09-21 — 고객별 추가 수집(Add-on) 확장점: 범용 hook 1개 + 별도 Add-on

- 상태: Accepted
- 결정: 사용자 (2026-09-21 대화 — 계획서 4회 피드백 후 최종안 승인, 구현 시작 지시)
- 작성: AI (Claude Code)
- 관련 rule: 22 R1/R3 (fragment 경계 · merge 호출), 11 R4, 13 R7 (03-fields.md 동반 갱신),
  96 R1-B (새 보조 키 — 사용자 승인), 30 R3 (외부 호출 timeout — 아래 "예외")

## 컨텍스트 (Why)

고객마다 추가로 확인할 항목(지정 Software 의 버전 확인, `/etc/hosts` 의 DB IP 등)이 계속 생긴다.
이것을 메인 수집 코드에 하나씩 넣으면 고객별 분기가 메인에 쌓이고, 현장 엔지니어가 고칠 수 없다.
요구는 "메인은 한 번만 범용 확장점을 열고, 이후 고객별 수집은 메인을 고치지 않는다" 였다.

## 결정 (What)

1. 메인에는 범용 hook `common/tasks/addon/run_addon.yml` 하나만 둔다. 4 play(Linux · Windows · ESXi ·
   Redfish)가 마지막 수집 뒤 · 조립 앞에서 include 한다 (`SE_ADDON_DIR` 이 있을 때만).
2. Add-on 은 별도 디렉터리(별도 저장소 `clovirone-gathering-addon`)의 Ansible role 이다. 메인이 이미 연
   연결을 그대로 쓴다 — 인벤토리 · vault · 자격증명 · precheck · 접속 코드를 복제하지 않는다.
3. 계약은 변수 5개다: 메인 → `_addon_dir`, `_addon_target`, `se_host_input` / Add-on → `_addon_result`,
   `_addon_errors`. 결과는 `data.addon`, 문제는 `errors[]` 의 `section: addon` 1건. `status` ·
   `sections` · `diagnosis` 는 바뀌지 않는다.
4. `inventory.sh` 3종은 호출자 host object 전체를 hostvar `se_host_input` 으로 보존한다 (키 예외 목록
   없음, 문자열은 `__ansible_unsafe`, Ansible 예약 키 `__ansible_*` 만 제외).
5. 경로는 `SE_ADDON_DIR` 하나. 미설정 → 조용히 건너뜀 / 설정했는데 `tasks/main.yml` 없음 → `errors[]`
   1건 / 있으면 실행. 자동 fallback 경로 · 특수값 없음.
6. Add-on 설정은 `config.yml` 의 `rules` 하나 — 위에서부터 처음 맞는 rule 하나만 적용 (병합 없음),
   `match` 필수. software 는 `name` + `command` 만, 출력은 가공 없이 `value`.

### 예외 — Add-on 전용 timeout 없음

rule 30 R3 은 "외부 호출에 timeout 명시" 를 요구하지만, 사용자가 Add-on 명령 · hook 에 전용 timeout 을 두지
않기로 결정했다 (기존 상위 실행 정책 = Jenkins Gather 단계 60분만 사용). 결과로 끝나지 않는 명령은 그 빌드
전체를 붙잡는다 — Add-on README 의 운영 주의사항과 config 검토로 관리한다.

## 결과 (Impact)

- 메인 변경: `inventory.sh` 3, hook 1(신규), `site.yml` include 4곳, 테스트 3(신규) + fixture, 문서.
  `common/tasks/normalize/**`, `callback_plugins/**`, `ansible.cfg`, `schema/**`, `vault/**`, `Jenkinsfile*` 는
  고치지 않았다.
- `SE_ADDON_DIR` 미설정(현재 모든 환경): 봉투가 hook 도입 전과 byte 단위로 같다 (엔진 테스트, hash seed 고정).
- 새 수집 기능은 Add-on 안에서만 추가한다 (`tasks/collectors/<이름>.yml` → `data.addon.<이름>`).
- 실측 근거: `tests/evidence/2026-09-21-addon-hook-live.md` (2.20.3 gate spike, 엔진 테스트, 실장비 V1~V8).

### 실측으로 드러나 결정한 것 (2026-09-22 사용자)

- 결정 T: Linux(SSH) 출력 줄바꿈 `\r\n` 은 그대로 둔다.
- Windows(AO-2): `& { … } 2>&1` 로는 PowerShell 5.1 이 오류 레코드를 stderr 로 다시 보내 `value` 에 담기지
  않았다 → 감싸기를 `& { … } *>&1 | Out-String -Stream` 으로 바꾸고, 종료 오류로 stderr 가 남으면 첫 줄을
  `errors[]` 알림으로 남긴다. 확정 사항 "허용하는 처리는 실행 단계의 stream 통합뿐" 안에서 합치는 방식만 바꿨다 —
  `Out-String -Stream` 은 콘솔에 보이는 그대로의 글자로 내보내는 PowerShell 기본 표시이고, Message 추출 ·
  `ForEach-Object` 변환 · parsing 은 없다 (오류 없는 출력은 byte 동일, e2e 실측).
- UTF-8 이 아닌 바이트(AO-3): 확정 사항 "자동 치환 없음 — 실제 환경에서 재현되고 JSON 생성에 꼭 필요할 때만 검토"
  의 조건이 충족됐다 (재현 + 그 host 봉투 전체 손실). Add-on 이 돌려주기 직전 그 바이트만 `\xNN` 글자로 바꾸고
  위치를 알린다. 메인은 고치지 않고, "돌려주는 글자는 UTF-8 로 쓸 수 있어야 한다" 를 hook 약속에 적었다.

### 남은 것

- `/etc/hosts` DB 판별 규칙 — 고객 샘플 확인 후.
- 운영 Agent 노드 환경변수 `SE_ADDON_DIR` 등록 — 사용자 (Add-on 배치는 배포 Job 으로 끝남).

## 대안 비교 (Considered)

| 대안 | 기각 이유 |
|---|---|
| 고객별 수집을 메인 채널 태스크에 계속 추가 | 고객 분기가 메인에 쌓이고 현장에서 고칠 수 없다 |
| Add-on 이 자체 인벤토리 · 접속으로 별도 실행 | 자격증명 · precheck · fallback 을 복제해야 하고 결과 JSON 이 둘로 갈린다 |
| `include_tasks` 진입 + 순수 Jinja (role 아님) | filter plugin 을 쓸 수 없어 `/etc/hosts` 해석 · rule 선택이 중첩 Jinja 가 된다. role 의 filter_plugins 자동 로드가 2.20.3 에서 확인돼(200 host, forks 200) role 형태를 택했다 |
| `inventory.sh` 가 `physical_purpose` 만 골라 전달 | 새 host 항목마다 메인을 고쳐야 한다 |
| 여러 rule 병합 / 우선순위 | 숨은 우선순위가 생겨 현장에서 결과를 예측하기 어렵다 |
| `schema/field_dictionary.yml` 에 addon 등록 | 실행 · 기존 테스트에 불필요 (런타임 검증 없음, 검증기는 사전 → 예제 한 방향) |
