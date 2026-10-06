# ADR-2026-10-07 — 결과 처리 재진입 · 기록 읽기 예외 · 끊긴 준비 · OOM 귀속 (10차)

상태: Accepted (2026-10-07). 사용자 지시서 "ClovirONE Gathering 최종 결함 보완 및 실환경 검증 작업지시서"(2026-10-06)와 같은 날의
"10차 실행계획 최종 보정기준" · "10차 계획 검토 결과와 구현 확인 사항" 의 결정 기록. `ADR-2026-10-06-infra-wait-and-host-resume.md` 의
결정 2(끊김 시각을 Jenkins 가 기다린 5분만큼 앞당겨 센다)와 결정 6 의 OOM 판정(같은 cgroup 의 OOM 종료 횟수 증가)을 대체한다. 그 ADR 의 나머지
(72 h 실행 기반 대기 · 같은 Runner · 같은 작업 폴더 · Host 단위 재개 · 사전 차단 제거)는 그대로다.

## 컨텍스트 (Why)

- 9차(main `8af81613`, production P6 `a8833d47`)의 재개 경로를 외부 검토가 실제 함수로 재현해 결함 다섯을 찾았다.
  - R1: 결과 확인 및 전송(`seFinalizeAndCallback`)이 `retry(agent(), nonresumable())` 의 재진입 표식(`agent_lost`)을 처리하지 않아 `null` 을 돌려줬고,
    빌드 요약은 "접수 전에 끝나" 와 SUCCESS 로 끝났다 — 결과를 보내지 않고 성공으로 끝나는 경로.
  - R2: 소유 기록 읽기(`seReadOwner`)가 모든 예외를 `null` 로 바꿨다. 채널 오류 같은 일시적인 읽기 실패가 "기록 없음" 이 되어 `resume_impossible` 로 끝났다(GP-61).
  - R3: 첫 준비 순서가 소유 기록 → 정리 → 접수 목록이었고, 재진입은 소유 기록만 보고 준비 전체를 건너뛰었다. 그 사이에 끊기면 접수 목록 없이 재개해 `prep_failed` 로 끝났다.
  - R4: Add-on 결정 읽기 예외를 `null` 로 바꾼 뒤 기본 ref 를 새로 받았다 — 한 빌드 안에서 Add-on 버전이 섞일 수 있었다(GP-58).
  - R5: 같은 cgroup 의 OOM 종료 횟수 증가만 보고 `runner_oom` 으로 정했다. Agent 세션 범위는 여러 빌드가 함께 쓰므로 다른 프로세스의 OOM 과 구분할 수 없고,
    종료 코드 1(스스로 실패)도 OOM 으로 읽었다.
- 구현 중 하나를 더 찾았다(N1): 마지막 보존(`sePreserveGatherOutput`)이 보관 · 전달 뒤 소유 기록을 `commit` 없이 다시 쓰고 작업 폴더를 지웠다. 그 사이에 끊기면
  다음 시도가 기록이 없다고 보고 `resume_impossible` · UNSTABLE 로 끝났다(결과는 이미 보관돼 있었다).
- 9차의 "끊김 시각을 5분 앞당겨 센다" 는 Jenkins 가 끊긴 Agent 를 기다리는 경우에만 맞다. 즉시 난 읽기 오류나 controller 재시작 뒤 이어 갈 수 없는 step 은
  5분을 기다리지 않았는데도 대기로 5분을 더 셌다.

## 결정 (What)

1. **결과 처리 재진입 (R1)**: 결과 처리를 반복 구조로 바꾼다. 빌드 안 상태(진입 수 · 전송 기록 · 결과 처리 실행 시간 합 · 취소 빌드의 노드 대기 사용량 · 진행 표식)를
   진입 사이에 이어 쓴다. 실행 기반 오류로 다시 불리면 같은 빌드의 실행 기반 대기 예산 안에서 결과 처리 노드를 다시 기다려 같은 폴더(`fin-<빌드>`)에서 다시 조립한다.
   - 2xx 를 이미 받은 전송은 다시 보내지 않는다. 받지 못한 전송은 기존 계약(최대 3번)의 남은 횟수만 쓴다(`seCallback` 이 기존 시도 수를 이어받는다).
   - 결과 처리 1 h 는 진입마다 초기화하지 않는다. 노드를 얻은 때부터 끝(또는 오류 감지)까지를 진입마다 더하고 남은 합으로 `timeout` 을 건다. 노드 대기는 빼고 센다.
   - 취소된 빌드의 노드 대기 5분도 합으로 한 번만 준다.
   - 같은 단계에서 진척 없이 다시 끊기면 기존 `seInfraPause` 로 쉬고, 쉰 시간은 대기 예산에 넣는다.
   - 끝내 처리하지 못하면: 보내지 못했으면 FAILURE, 보냈지만 마무리만 못 했으면 UNSTABLE. "접수 전" 문구는 접수 목록이 없을 때만 쓴다.
2. **확인된 시각부터 센다 (보정 1)**: 끊긴 뒤의 대기는 retry 본문이 기록한 실패 감지 시각부터 센다. `OFFLINE_GRACE` 상수와 5분 앞당김을 없앤다.
   Runner 배정 대기 · 입력 확인 · 실행 위치 확인 · `seQueueTimer` 조회 간격(GP-59)은 바꾸지 않는다.
3. **기록 읽기 예외는 감싸지 않는다 (R2 · R4)**: 공용 `seReadJsonFile` 은 파일이 없으면 `absent`, 읽은 문자열을 해석하지 못하면 `corrupt` 이고, `readFile` 자체의 예외는
   원래 형태로 상위 `retry(agent(), nonresumable())` 로 넘긴다. 어떤 예외가 실행 기반 오류인지는 설치된 Jenkins 의 조건(`agent()` · `nonresumable()`)이 판단한다 —
   Groovy 에 예외 종류 목록을 복제하지 않는다. 소유 기록 · 수집 실행 기록 · Add-on 결정에 쓴다.
   Add-on 결정이 손상됐으면 작업 폴더의 `addon/` 사본 commit 으로 복원하고, 사본도 없고 수집이 이미 시작됐으면 다른 ref 로 바꾸지 않고 Add-on 없이 수집한다(UNSTABLE + 사유).
4. **끊긴 준비 · 접수 목록 · 사라진 결과 (R3)**: 소유 기록에 `prepared` 를 둔다(시작 `false`, 정리 · 접수 목록 뒤 `true`). `prepared:false` 이고 수집 전이면 남은 준비만 한다
   (받은 commit 이 같으면 다시 받지 않는다). 수집 시작 뒤 접수 목록 파일만 없으면 이 빌드가 접수한 원본(`SE_MANIFEST_JSON`)으로 다시 쓴다.
   결과가 확정됐던 대상(진행 기록의 `emitted` · `reconciled`, 앞 시도의 `completed_ips` · `precheck_failed_ips`)의 결과 줄이 작업 폴더에 없으면 다시 수집하지 않고
   `resume_impossible` 로 끝낸다(`run_gather.sh` rc 92). 개수가 아니라 IP 로 대조하고, 확정 기록이 없는 대상은 끝나지 않은 대상이다.
5. **보존 뒤 재시도 중단 (N1)**: 마지막 보존이 결과를 포함한 보관(archive) **또는** 전달(stash) 중 하나라도 마치면 표식(`SE_FINAL_PRESERVED`)을 남긴다.
   그 뒤에 끊기면 다시 시도하지 않고 직전 판정으로 끝낸다. 둘 다 성공해야 한다는 조건은 만들지 않는다. 다시 쓰는 소유 기록은 `commit` · `prepared` 를 유지한다.
6. **OOM 은 관측과 원인을 나눈다 (R5)**: cgroup `memory.events` · `/proc/vmstat` 의 OOM 종료 증가는 관측(`oom_observed`)으로만 남긴다.
   원인(`runner_oom`)은 바깥에서 끝난 시도(신호 · 한계가 아닌 137 · 끝 기록 없음)이면서 커널 로그(`dmesg`, 시도 시작 기준점 이후)의 OOM 종료 기록 PID 가 이 실행
   (`run_gather.sh` · ansible-playbook 주 프로세스)의 것일 때만이다. ansible-playbook PID 는 `run_gather.sh` 가 `exec` 직전에 기록한다(PID 가 같아 신호 동작은 그대로).
   스스로 끝난 실패(rc 1 등)는 `failed_run`, 근거 없는 바깥 종료는 `process_lost` / `aborted`(원인 미확인)다. 사용자 취소는 Groovy 가 확인한 뒤
   `gather_state.py classify --user-abort` 로 `aborted` 를 확정한다. 커널 로그를 읽을 수 없는 Runner 에서는 공유 범위의 OOM 을 원인으로 정하지 않는다.
   시도 시작 때 cgroup 구성원만으로 "격리 범위" 를 인정하지 않는다 — 시작 뒤에 다른 프로세스가 들어올 수 있기 때문이다.
   시도 시작 기준점은 **커널 로그 자신의 시계**(시작 때 마지막 줄의 시각)로 잡는다. `/proc/uptime` 과 비교하지 않는다 — 실기(Runner03, VMware)에서
   커널 로그 시각이 `/proc/uptime` 보다 약 22초 늦어, uptime 으로 잡은 기준점이 이 실행의 OOM 종료 기록을 "시작 전" 으로 빼 버렸다.
   시작 때 커널 로그를 읽지 못했으면 기준점이 없어 연결하지 않는다(오래된 같은 PID 번호를 잇지 않는다).
   ansible 작업자(fork) 프로세스의 PID 는 남지 않아 연결하지 못한다 — 작업자만 OOM 으로 끝나면 원인 미확인이다(systemd 가 범위를 멈추면 연결 끊김 경로로 재개).
7. **R6 시험 조건 (보정 5)**: 운영 경로에 새 SSH · WinRM · HTTP 제한을 넣지 않는다. 시험 6 · 18 은 운영 유효 설정(Linux `os-gather/site.yml` 의
   `ConnectTimeout=60` · `ServerAliveInterval=10` · ansible `timeout` 60, Windows operation 60 · read 70)과 실제 실행 인자를 기록한 뒤 그 값으로 기대 결과를 정한다.
   가짜 시계 · 축약 상수를 쓰는 Harness · pytest 는 별도 동작 시험으로 표시한다.

## 결과 (Impact)

- 제품 코드: `Jenkinsfile_portal`(결과 처리 · 대기 계산 · 기록 읽기 · 준비 · 보존 · Add-on), `scripts/gather_state.py`(OOM 귀속 · 확정 결과 대조 · `--user-abort`),
  `scripts/run_gather.sh`(PID 기록 · rc 92). Portal HTTP 계약 · envelope · 결과 형태는 바뀌지 않는다.
- 판정 이름이 하나 늘었다: 시도 상태 `resume_impossible`(확정 결과가 사라짐). `runner_oom` 은 드물어지고, 종전에 `runner_oom` 이던 일부는 `failed_run` · `process_lost` 가 된다.
  `process_lost` 는 다시 시도하지 않으므로 공유 범위의 원인 미확인 종료는 재수집하지 않는다(그 Runner 에 다른 프로세스의 OOM 이 있었다는 관측은 남는다).
- 드물게 실행 기반이 아닌 읽기 예외가 빌드 오류로 드러난다(종전에는 "기록 없음" 으로 숨었다). 결과 확인 및 전송은 그대로 돈다.
- 시험: pytest(`test_gather_state.py` 반례 — 다른 프로세스 OOM + rc 1 / `kill -9` / 사용자 취소, 이 실행의 OOM + 신호, 시도 시작 뒤 들어온 프로세스),
  Harness 새 시나리오(재진입 · 기록 읽기 · 끊긴 준비 · 보존 표식 · Add-on 결정 — CI 기본 목록과 prodgen `REQUIRED_HARNESS` · `REQUIRED_HARNESS_TREE` 에 추가).

## 대안 비교 (Considered)

| 대안 | 채택 여부 | 이유 |
|---|---|---|
| 예외 종류 목록(ClosedChannelException 등)을 Groovy 에 두고 읽기 예외를 분류 | 거절 | 설치된 Jenkins 의 `AgentErrorCondition` 과 어긋나면 같은 오류를 두 곳이 다르게 판정한다. 원래 예외를 넘기면 Jenkins 가 판정한다 |
| 결과 처리를 재진입마다 새 1 h 로 | 거절 | 끊김이 반복되면 한계가 사라진다. 실제로 쓴 시간의 합으로 센다 |
| 같은 cgroup + 가까운 시각을 OOM 원인으로 | 거절 | Agent 세션 범위는 여러 빌드가 공유한다. 다른 프로세스의 OOM 을 이 실행의 원인으로 읽어 재수집한다 |
| 시도 시작 때 cgroup 구성원이 이 실행뿐이면 격리로 인정 | 거절 | 시작 뒤에 다른 프로세스가 들어오면 그 OOM 도 같은 카운터에 쌓인다. 시도 전 구간의 격리를 확인할 방법이 없다 |
| 보존 표식을 보관 · 전달 둘 다 성공일 때만 | 거절 | 결과 확인은 둘 중 하나로 회수한다. 둘 다 요구하면 하나가 실패한 빌드가 다시 수집 경로로 간다 |
| 접수 목록이 없으면 `resume_impossible` | 거절 | 같은 빌드 · 같은 revision 이면 접수 원본으로 같은 파일을 만들 수 있다. 확정 결과가 사라졌을 때만 재개 불가다 |
| 시험 6 · 18 에 짧은 SSH · WinRM 설정 | 거절 | 운영과 다른 조건의 결과가 된다. 운영 유효 설정으로 시험한다 |
