# ADR-2026-10-06 — 실행 기반 대기 · 같은 Runner 재개 · 사전 차단 제거 (9차)

상태: Accepted (2026-10-06). 사용자 지시서 "ClovirONE Gathering 대기 및 일시 장애 처리 재검토 지시서" 최종본(2026-10-06)과 사용자가 승인한
9차 실행계획(추가 지시 3건 포함)의 결정 기록. `ADR-2026-10-05-time-limits-and-test-inputs.md` 의 "시간 한계 셋(빌드 12 h · 수집 단계 39,000 s ·
결과 확인 1 h)" 과 `scripts/gather_budget.sh` 부분을 대체한다. 그 ADR 의 나머지(시험 입력 제거 · 원격 명령 정리 · 보존 기간 · 운영 문구)는 그대로다.

## 컨텍스트 (Why)

- 8차 main(`09a5f442`, 실행 코드는 `8c9e04a9` 와 같다)은 지시서와 반대로 움직였다.
  - 실행 위치 확인이 **지금 온라인인** Runner 만 셌고, 0 이면 `no_agent` 로 수집을 건너뛰려 했다(실제로는 `when` 에 `beforeAgent` 가 없어 queue 에서 39,000 s 를 기다렸을 가능성이 크다).
  - 빌드 12 h · 수집 단계 39,000 s 한계가 Runner 를 기다린 시간까지 셌다. 기다린 만큼 실제 수집 시간이 줄었고(`build_limit`), 120 s 보다 적게 남으면 시작하지 않았다(`not_started_budget`).
  - 가용 메모리(MemAvailable)로 동시 실행 수를 줄이거나 시작을 거부했다(`not_started_memory`, `SE_MEM_AVAILABLE_MB` 등). 실제 Runner 의 정상 작업을 막는 사전 차단이었다.
  - 수집 단계에 들어갈 때 지난 결과 파일을 지웠고, 실행 기록(`gather_run.json`)은 끝날 때만 썼다. Agent 연결이 끊기면 끝난 대상의 결과도 다시 수집할 방법이 없었다.
- 지시서 기준: (1) Precheck 실패 대상은 실패로 확정하고 다른 대상은 계속한다. (2) 수집 중 대상 측 일시 장애는 채널의 기존 timeout · retry 로만 처리한다.
  (3) Runner · Jenkins 실행 기반 장애만 최대 72 h 기다리고, 끝난 결과는 보존한 채 **같은 Runner · 같은 작업 폴더**에서 끝나지 않은 대상만 이어서 수집한다.
- P1 실측(2026-10-06, Runner03 호스트의 임시 노드 se-probe · 임시 Job, 운영 Runner 설정 변경 없음):
  오프라인 노드는 executor 를 잡지 않고 queue 에서 기다린다(연결되면 같은 빌드가 이어 실행). 실행 중 연결이 끊기면 Jenkins 가 5분 기다린 뒤
  `sh` step 을 끝내고(`RemovedNodeTimeoutCause`) `retry(conditions: [agent()])` 가 본문을 한 번 더 부른다. Runner 쪽 프로세스는 계속 살아 있었다(고아 실행).
  5분보다 짧은 끊김은 step 이 다시 붙는다. 연결된 채 프로세스를 죽이면 약 10분 뒤 rc -1. 사용자 취소 직후 catch 안의 `currentBuild.result` 는 null 이라 취소 판정에 쓸 수 없다.

## 결정 (What)

1. **기다리는 방법 (D1 · D2)**: 실행 기반을 기다린 시간은 빌드 하나의 합으로 센다(`seConstants().INFRA_WAIT` 72 h). Runner 배정 · 실행 중 연결 끊김 ·
   결과 처리 노드 · 진척 없는 장애 뒤 쉬는 시간이 모두 같은 합에 들어가고, 다시 시도하거나 재개해도 처음부터 세지 않는다. 기다림은 Jenkins queue 다 —
   `seWithNode` 가 `parallel(failFast)` 로 `node()` 요청과 대기 한도 타이머를 함께 띄우고, 한도에 닿으면 표식을 남긴 뒤 요청을 거둔다. executor 를 잡지 않는다.
   조회 간격은 5 s 에서 두 배씩 300 s 까지, 30분마다 상태 줄과 빌드 설명을 바꾼다. 한도를 이미 다 썼어도 지금 바로 얻을 수 있는 노드는 얻는다 —
   요청을 거두는 판단은 첫 조회(5 s) 뒤에 한다. 그래서 Runner 를 기다리다 한도를 다 쓴 빌드도 결과 처리 노드를 얻어 끝나지 않은 대상의 실패 결과를 보낸다. 대기 구간마다 사유 · 대상 · 시작 · 끝 · 초 · 결과를 `finalize_summary.json` 의 `infra` 에 남긴다.
2. **끊김 판정 (D3 · D4, P1 반영으로 바뀐 점)**: 계획의 "15분 출력 없음 감시" 를 버렸다 — Jenkins 의 5분 판정과 겹쳐 사용자 취소로 잘못 읽힐 수 있었다.
   대신 `retry(count: 2, conditions: [agent(), nonresumable()])` 가 본문을 두 번째로 부르면 그것이 끊김이다(두 번째 호출은 일을 하지 않고 표식만 남긴다).
   sandbox 밖 API(`getCauses` 등)는 쓰지 않는다. 그 외 interruption 은 사용자 취소로 보고 다시 시도하지 않는다. 끊김 시각은 Jenkins 가 기다린 5분만큼 대기로 앞당겨 센다.
3. **같은 Runner · 같은 작업 폴더 (D5 · D10)**: 수집(`run_gather.sh`)을 시작하기 전에는 라벨을, 시작한 뒤에는 그 Runner 이름을 기다린다. 그 Runner 가 등록 해제되거나
   작업 폴더의 소유 기록이 없거나(지워짐) 받은 commit 이 다르면 **전체를 다시 수집하지 않고** `resume_impossible` 로 끝낸다. 이어서 하는 시도는 저장소를 다시 받지 않는다.
   다른 Runner 로 옮기지 않고 외부 큐 · 공유 폴더 같은 새 저장소를 만들지 않는다. 실행 기반 장애로 다시 시도하기 전, Runner 에 닿아 있으면 원본 결과만 stash 해 둔다
   (그 Runner 가 끝내 돌아오지 않을 때 결과 확인이 쓰는 입력). 결과 정리 · archive · 작업 폴더 삭제는 마지막 시도에서만 한다.
4. **재개 대상 (D8 · D9)**: `scripts/gather_state.py` 가 접수 IP 중 형태 검사(Layer A `shape_gate`)를 통과한 결과 줄이 없는 대상만 남긴다. Precheck 실패가 관측된 대상
   (`precheck | …` 태스크의 reachable · port · protocol 실패)은 확정이라 제외한다. 실행 중이던 대상(CHECKPOINT 만 있음)은 다시 수집한다. 넘기는 방법은
   `ansible-playbook --limit @<남은 대상 파일>` 이다(Job 파라미터를 늘리지 않는다). 쓰는 도중 끊긴 마지막 줄은 `gather_tail_fragments.jsonl` 로 옮겨 다음 시도가 이어 쓸 때
   두 줄이 같이 깨지지 않게 한다. 재개 표식(progress 의 `attempt` 사건)이 지난 시도의 관측을 지운다. 같은 작업 폴더의 수집은 `flock` 으로 한 번에 하나 —
   끊긴 동안 계속 돈 이전 실행이 있으면 끝나기를 기다린다.
5. **실행 시간 (D6, 사용자 추가 지시 2)**: Runner 시계로 잰 ansible 실행 시간의 합이다(동시에 수집한 Host 를 겹쳐 세지 않는다). 믿을 수 있는 끝 시각이 있으면 그 값,
   없으면 마지막 생존 표시(60 s 마다 `.gather_alive`) + 60 s, 생존 표시가 없으면 시작 + 60 s. 재부팅이면 새 부팅 시각을, 그리고 지금을 넘지 않는다. 그래서 비정상 종료가
   반복돼도 누적을 덜 세지 않는다(한 번에 최대 60 s 를 더 셀 수는 있다). 이번 시도의 한계 = 6 h − 누적, 0 이면 시작하지 않고 `gather_limit`.
   빌드 전체 · 수집 단계 timeout 은 없앴고, 시도 하나에 `timeout(6 h + 90 s + 2 h)` 를 node 를 얻은 뒤에만 건다(멈춘 step 이 빌드를 붙잡지 않게 하는 안전망).
6. **원인은 근거가 있을 때만 (D7)**: Runner 재부팅(boot_id 바뀜) · Runner OOM(비정상 종료 + 같은 cgroup v2 `memory.events` oom_kill 증가, cgroup 을 못 읽을 때만
   `/proc/vmstat`) · 연결 끊김(Jenkins 보고)만 실행 기반 장애다. 근거가 없으면 원인 미확인(`process_lost`)이고 다시 시도하지 않는다. 진척 없이 장애가 반복되면
   5분부터 두 배씩(최대 1 h) executor 를 잡지 않고 쉰다.
7. **사전 차단 제거 (W01 · W02 · W03 · D12)**: `scripts/gather_budget.sh`, 메모리 상한 · 시험 입력, `no_agent` · `not_started_budget` · `not_started_memory`, 빌드 12 h ·
   수집 단계 39,000 s 를 지웠다. 등록된 Runner 가 하나도 없으면(잘못된 Location · Label) 실행 위치 확인이 `config_error` 로 FAILURE 이고 접수된 대상마다 실패 결과는 보낸다.
   동시 실행 상한은 그대로다(OS 50 또는 `SE_FORKS_CAP_OS`, ESXi 2×vCPU, Redfish 4×vCPU).
8. **결과 확인 · Portal (W07 · W08)**: 결과 처리 노드(built-in)도 같은 대기 합 안에서 기다리고(취소된 빌드는 5분), 노드를 얻은 뒤 1 h 다. 끝내 얻지 못하면 보내지 못한 채
   FAILURE 이고 결과는 stash · 보관본에 남는다. Portal 은 그대로(최대 3번 · 시도당 10분, 72 h 대기 · 재수집 없음)이고 수신 여부를 `callback.receipt`
   (`delivered` · `not_delivered` · `uncertain` · `not_attempted`)로 남긴다.
9. **실행 기반 장애 문장**: 대기 한도 초과 · 재개 불가로 끝나지 않은 대상은 대상 측 실패로 확정하지 않고 `infra_unavailable` 문장을 쓴다("수집을 실행하던 Runner 가
   회복되지 않아 이 대상의 수집을 마치지 못했습니다."). `failure_code` 는 `OUTPUT_BUILD_FAILED` 그대로(새 code · stage 없음), Layer A · B 가 같은 문장을 쓴다(corpus 19 · 20).
10. **대상 측 장애 · 자격 (W05 · W06 · 쓰기 응답 유실)**: 수집 중 대상 측 장애는 기다리지 않는다. Redfish 표준 후보는 구조화된 401 일 때만 다음으로 넘어가고, 복구(계정 쓰기)는
    시도한 표준 후보 전원이 401 일 때만 들어간다. 복구 후보도 명시 거부일 때만 다음으로 간다. OS · ESXi 는 실패 뒤 관리 포트에 TCP 를 1회 다시 확인해 연결되지 않으면 남은
    후보를 보내지 않는다. 저장장치 Controllers 의 하위 401/403 은 host 를 failed 로 끌어내리지 않는다. 응답을 잃은 계정 쓰기는 다시 보내지 않고 다시 읽고 다시 인증해
    판정하며, 만든 슬롯을 비우는 PATCH 는 확인이 확정적으로(401) 실패했을 때만 보낸다.
11. **Add-on (W09)**: 저장소 오류 처리는 그대로(UNSTABLE · Add-on 없이 수집). 결정을 작업 폴더의 `.se_addon.json` 에 남겨 재개 때 같은 commit 을 쓴다.
12. **production 주석 (D13, 사용자 추가 지시 1)**: prodgen 의 Python 스트리퍼가 UTF-8 인코딩 선언을 지운다(Python 3 기본값 — 다른 인코딩 선언은 남긴다).
    두 스크립트의 argparse 설명을 문자열 상수로 바꿔 `doc_runtime` 보존을 없앴다. main 의 주석 · docstring 은 그대로다. 승격 전 G07 · 승격 뒤 양 원격 재검사로 확인한다.
13. **시험 축약 (D11)**: 한계 값은 `seGatherStage(C)` 의 인자다. 운영은 `seConstants()`, Harness 는 짧은 값을 넣는다. Job 파라미터 · 환경변수 스위치는 없다.

## 결과 (Impact)

- 운영 Job 의 입력 · envelope 13 필드 · `failure_code` · `failure_stage` 는 바뀌지 않는다. `finalize_summary.json` 에 `limits.infra_wait_sec` · `infra{}` ·
  `callback.receipt` · `times.finalize_node_acquired_at` 이 더해졌고 `limits.build_sec` · `stage_sec` 는 없어졌다. outcome 값에 `infra_wait_expired` · `resume_impossible` ·
  `process_lost` · `attempt_limit` · `config_error` 가 더해지고 `no_agent` · `not_started_budget` · `not_started_memory` 는 없어졌다. 한계 사유는 `gather_limit` · `infra_wait`.
- Portal 은 72 h 대기 빌드의 결과를 최대 약 79 h 뒤(대기 72 h + 수집 6 h + 결과 확인 1 h)에 받을 수 있다. Portal 쪽 대기 한도가 그보다 짧으면 맞지 않는다(사용자 확인 필요).
- Runner 가 끝내 돌아오지 않으면 그 Runner 에만 있던 결과(마지막 중간 보존 이후)는 보낼 수 없고, 그 대상은 실행 기반 문장의 실패 결과가 된다.
- 끝 기록 없는 작업 폴더를 실행 중으로 보는 기간이 82 h 로 늘었다(`workspace_cleanup.py --build-limit-sec 295200`).
- 원복: 실행 코드 커밋 하나를 되돌리면 8차 동작으로 돌아간다. production 은 prodgen restore 로 이전 생성 커밋을 되살린다.

## 대안 비교 (Considered)

| 대안 | 채택하지 않은 이유 |
|---|---|
| 빌드 timeout 을 82 h 로 늘리기 | 기다린 시간이 여전히 실행 시간과 섞이고, 끊긴 Agent 를 82 h 붙잡을 수 있다. 실제 실행에만 한계를 거는 지시서와 맞지 않는다 |
| 15분 출력 없음 감시로 끊김 판정 | P1 실측에서 Jenkins 가 끊긴 Agent 의 step 을 5분 뒤 끝냈다 — 감시가 그 끝을 사용자 취소와 구분하지 못한다. `retry(agent())` 가 sandbox 안의 정확한 신호다 |
| 끊기면 다른 Runner 로 옮겨 처음부터 수집 | 지시서 금지(새 저장소 · Runner 간 이관). 끝난 대상을 다시 수집하고, 고아 실행과 겹쳐 같은 대상을 두 번 건드린다 |
| 남은 대상을 Job 파라미터 · 환경변수 스위치로 넘기기 | 운영 입력 표면이 늘어난다(8차 R1 원칙). 작업 폴더의 실행 기록에서 계산하면 같은 정보가 Runner 에만 있다 |
| 메모리 측정은 남기고 경고만 | 측정값이 정상 작업을 막은 실제 사례가 있었고, Runner OOM 은 사후 근거(카운터 증가)로만 판정하는 것이 지시서 기준이다 |
| 수집 중 주기적으로 결과를 stash | Runner 가 돌아오지 않을 때 보낼 수 있는 결과가 늘지만, 큰 배치에서 controller 로 반복 전송이 커진다. 9차 계획(D10)은 시도마다 1회로 정했다 — 필요하면 별도 결정 |
