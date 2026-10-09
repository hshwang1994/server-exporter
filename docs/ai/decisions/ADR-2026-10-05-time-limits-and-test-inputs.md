# ADR-2026-10-05 — 시험 입력 제거 · 시간 한계 셋 · 원격 명령 정리 · 보존 기간 (8차)

상태: Accepted (2026-10-05). 사용자 작업지시서 "ClovirONE Gathering 최종 통합 후속 작업지시서"(2026-10-05) R1~R8 의 결정 기록.
전신 `ADR-2026-10-03-pipeline-finalization.md` 의 시간 예산 · Tier 2 부분과 `ADR-2026-10-04-promotion-verdict-and-harness.md` 의 S3/E2E-E 증거 정의를 대체한다.

## 컨텍스트 (Why)

- 운영 수집 Job 두 개(main · production)에 시험 전용 파라미터 `redfishAccountDryrun` · `gatherBudgetForceSec` 가 남아 있었다. 기본값이면 영향이 없다고
  적었지만 운영 Job 의 입력 표면이고, 승격 증거(S3 · E2E-E)가 그 입력에 기대고 있었다.
- 시간 제한이 여러 겹이었다: 작업(task) 단위(Linux 120 · Windows/ESXi 180 · Add-on 300 s), Redfish 모듈 마감(절대 1,200 · 새 응답 없음 120 s),
  예상 시간 뒤 정체 감시(420 s), `df` 20 s, 결과 정리 120 s, 보존 · 조립 · 본문 30~60 s(Tier 2, Script Approval 4 서명). 정상적으로 오래 걸리는 수집
  (느린 BMC · 느린 NFS · 큰 배치)이 진행과 무관하게 잘렸고, 진행 판정이 JSON 해석보다 먼저라 잘못된 HTML 200 응답도 "진행" 으로 셌다.
- Linux 원격 명령이 남았다(2026-10-05 `.161` 실측): ansible 작업 프로세스는 자기 세션에서 돌아 실행 한계의 INT 가 주 프로세스에만 가고, SSH 다중화
  연결이 남아 원격 `sleep` 1개(sudo 경로 3개)가 계속 돌았다.
- 콘솔에 실제 시각이 없었고(`attempts=0` 인데 `attempted=true` 같은 기록 오류 포함), 운영자 문구에 구분 기호 · 내부 용어가 섞여 있었다.
- 빌드 기록 · 결과 파일 보존 기간이 없었고, 보관에 실패한 빌드의 작업 폴더가 Runner 에 계속 남았다(`allowEmptyArchive` 로 빈 보관도 성공으로 셌다).

## 결정 (What)

1. **시험 입력 제거(R1)**: 두 파라미터와 배선(`-e _rf_account_service_dryrun` · `SE_FORCE_SEC` · 빌드 이름 `[시험: …]` · 감시 끄기)을 지운다. 다른 환경변수 ·
   파라미터로 옮기지 않는다. Redfish 모듈 dry-run 과 복구 계약은 유지한다. 증거는 나눈다 — 운영 Job 은 정상 입력만 증명하고(S3 = 실호스트 10대 이상 큰 배치를
   운영 한계 안에서 끝까지, E2E-E = 정상 Redfish 수집의 표준 계정 인증 · 계정 쓰기 0), 한계 도달 · 보존은 Harness `gather_limit_preserve`(실제 `run_gather.sh` 가
   시험 한계에 닿은 뒤 운영 함수가 보존 · 전송, main 함수 · 생성 tree 두 그룹), 계정 쓰기 방지는 CI Gate 단위 시험이 같은 main SHA 로 증명한다. 증거 수집기는
   없앤 파라미터가 빌드에 남아 있거나 콘솔에 `[시험:` 이 있으면 그 빌드를 증거로 받지 않는다.
2. **시간 한계 셋(R3 · R4)**: 빌드 12 h(43,200 s) = 입력 확인 5 min + 실행 위치 확인 5 min + 수집 단계 39,000 s + 결과 확인 및 전송 1 h. 실제 수집은 실제 시작
   기준 최대 6 h(`scripts/gather_budget.sh` 가 계산, `scripts/run_gather.sh` 의 `timeout --signal=INT --kill-after=90` 이 집행, 한계 사유 `gather_limit` /
   `build_limit`). 작업 단위 제한 · 모듈 마감 · 진행 표시 · 정체 감시 · `df` 20 s · 결과 정리 120 s · Tier 2 를 지운다. 연결 60 s · 응답 대기(수집 API 30 min ·
   Portal 시도당 10 min)는 통신 규약 값으로 남긴다. 값은 `seConstants()` · `gather_budget.sh` · 파이프라인 옵션에 있고 `tests/unit/test_time_limits.py` 가 맞춘다.
3. **실제 시각(R2)**: Timestamper `timestamps {}` 는 Job 범위에서 쓰되 플러그인이 없으면 생략한다(블록 진입 전 `NoSuchMethodError` 만). 업무 사건 줄은 본문에
   날짜 · 시각 · 시간대를, 기록 JSON 은 UTC ISO 8601 을 쓴다. 기계가 읽는 줄 · JSON 줄에는 접두어를 붙이지 않는다. envelope · `duration_ms` 는 바꾸지 않는다.
4. **숨은 실패 드러내기(R5)**: ESXi 디스크 모듈 실패 · Windows Hyper-V 서비스 조회 실패(없음 · 멈춤과 구분) · `Get-NetAdapter` 등 끝나지 않는 오류 · setup 실패 ·
   `Get-Volume` 실패를 섹션 상태는 그대로 두고 `errors[]` 1건으로 남긴다. "찾는 항목 없음" 은 실패가 아니다.
5. **원격 명령 정리(R6)**: `run_gather.sh` 가 실행마다 자기 SSH 다중화 위치를 쓰고, 끝나면 그 연결에 종료를 보낸 뒤 그 위치를 명령줄에 가진 ssh 만 끝낸다.
   Linux 명령은 pty 와 함께 돌아(`ansible_ssh_use_tty`) 연결이 닫히면 SIGHUP 으로 끝난다. 이름으로 프로세스를 끝내지 않고 대상에서 프로세스를 찾아 죽이지 않는다.
6. **운영 문구(R7)**: 구분 기호 대신 문장, 내부 용어 대신 하는 일. 한계로 끝난 실행은 어떤 한계 · 실행 시간 · 끝난/끝나지 않은 대상 수 · 보존 · 전송을 나눠 적는다.
   2xx 는 "Portal 이 요청을 받았다" 이고 "Portal DB 저장 완료" 가 아니다(2xx 계약은 사용자 결정 그대로).
7. **보존 기간과 정리(R8)**: `buildDiscarder` 빌드 기록 14일/100 · 결과 파일 7일/50(Job 범위). 작업 폴더는 빌드마다 `<Job>-<번호>` 이고, 이 빌드의 필수 결과를
   이름으로 보관한 것을 확인했을 때만 지운다(빈 보관은 실패). 남은 폴더는 `scripts/workspace_cleanup.py` 가 하루 한 번, 7일 뒤 — 보관한 폴더와 결과 없는 폴더는 지우고,
   보관하지 못한 결과가 있는 폴더는 결과 파일만 남긴다. 컨트롤러 결과 확인 폴더도 빌드별(`fin-<번호>`)이다.

## 결과 (Impact)

- 운영 입력 표면이 7개 파라미터로 줄었다. Script Approval · `SE_FINALIZER_BOUNDED` 전역 변수가 필요 없다 — 고객사 main-only 설치에 맞출 값이 줄었다.
- 비정상 배치가 끝나는 시점은 늦어질 수 있다(작업 단위 제한 대신 실행 한계 최대 6 h). 대신 정상 작업은 잘리지 않는다. 바깥 틀(12 h)은 있다.
- 원격 잔존: 고치기 전 한계 1 · sudo 한계 3 → 고친 뒤 7 상황 모두 0(`.161` 실측, `docs/operate/04-pipeline-runtime.md` "원격 명령 정리").
  남는 한계 — D 상태 프로세스, 네트워크가 끊겨 대상 sshd 가 모르는 연결.
- 계약 영향: `finalize_summary.json` 에 `times` · `limits` · `gather_run` · `interruption` · `callback.tries[]` 가 더해지고 `limit_reason` 값이 `gather_limit`/`build_limit` 로
  바뀐다(7차 `stalled`/`ceiling`/`forced` 삭제). envelope 13 필드 · `failure_code` 는 그대로. Redfish rescue 의 기술 근거는 `status=task_stopped` 로 바뀐다.
- CI · prodgen: `HARNESS_BOUNDED` · `REQUIRE_BOUNDED` · `--require-bounded` 삭제, 필수 stage 집합은 하나. Budget Self-test 가 Time Limits Self-test(stage 키 `BUDGET`)가 됐다.

## 대안 비교 (Considered)

- *시험 파라미터를 환경변수로 옮겨 운영 Job 에서 숨긴다* — 거부(지시서 R1). 입력 표면이 사라지지 않고 상속으로 다시 켜질 수 있다.
- *작업 단위 제한을 늘리기만 한다(예: 120 → 600 s)* — 거부. 정상 작업 길이에 상한이 없는 곳(느린 BMC · NFS · 큰 Add-on)에서 같은 문제가 다시 생긴다.
- *정체 감시를 고쳐 남긴다(진행 판정을 JSON 해석 뒤로)* — 거부. 진행 신호가 채널마다 다르고(SSH raw 는 출력이 없다), 오판의 비용이 정상 결과 손실이다.
- *원격 잔존을 대상 서버에서 이름으로 찾아 끝낸다* — 거부. 남의 프로세스를 끝낼 수 있다. 이 실행이 연 연결만 닫는다.
- *`options { timestamps() }`* — 거부. 플러그인이 없는 고객사 Jenkins 에서 파이프라인 검증이 실패한다. 블록 진입 전 확인으로 대신한다.
- *보관하지 못한 작업 폴더도 7일 뒤 통째로 지운다* — 거부. 그 빌드의 유일한 결과일 수 있다. 결과 파일만 남기고 사람이 확인한다.

## 보완 (2026-10-09 — 운영 로그 문구 정리)

R7 의 **의미는 그대로** 두고 표시 방식만 바꿨다(사용자 작업지시서 "로그 문구 개선", 정본 `docs/reference/decision-log.md` 2026-10-09).

- 2xx: 콘솔은 `[Portal 전송] HTTP 200 응답을 받았습니다. 소요 시간 ….` 만 쓴다. "2xx 는 Portal 이 요청을 받았다는 뜻" 이라는 설명 줄은 정상 안내에서 뺐다.
  2xx 를 "저장 · 반영 완료" 로 쓰지 않는 것은 그대로다. 받지 못한 경우는 기록(delivered · refused · 시도 기록)으로 문장을 고른다 — 확인 못함 · 거부 · 시작 못함.
- 한계로 끝난 실행: 어떤 한계 · 실행 시간 · 끝난/끝나지 않은 대상 수 · 보존은 `[수집 종료]` 한 블록(첫 줄 + 상세 줄)에, 전송 결과는 바로 앞 `[Portal 전송]` 줄과
  빌드 끝 `[요약]` 에 둔다(같은 단계에서 두 번 쓰지 않는다). 수집을 시작하지 않은 빌드는 머리 문장이 그 사실을 말한다.
- 구분 기호 대신 문장(R7)은 더 좁혔다 — 한 사건은 출력 한 번(첫 줄 + 두 칸 들여쓴 상세 줄), 업무 시각은 첫 줄에만. 기술 값은 기존 `[기술 기록]` 줄과
  `finalize_summary.json` 에 둔다(새 상시 기술 줄은 만들지 않았다).
