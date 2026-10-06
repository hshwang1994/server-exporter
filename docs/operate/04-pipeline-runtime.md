# Jenkins 파이프라인 런타임

> 이 문서는 server-exporter 의 운영 파이프라인 `Jenkinsfile_portal` 이 실제로 어떤 단계로 실행되는지 정리한다.
> 각 단계가 어느 노드에서 도는지, 어디서 실패하면 어떻게 전파되는지, 호출자에게 어떤 형식으로 결과가 돌아가는지를 한 페이지에 모았다.
>
> Jenkinsfile 을 수정해야 한다면 본 문서의 단계 구조와 게이트 정책을 먼저 이해한 뒤 손댄다.

> 검증일: 2026-10-05 (8차 — 시험 입력 제거 · 실제 시각 · 장시간 대기 · 원격 정리 · 보존 기간과 작업 폴더 정리. 코드 · 회귀 기준이며 사내 Jenkins 실행 결과는
> `tests/evidence/2026-10-05-8th-time-limits.md` 에 적는다)

## 1. 파이프라인 구조

`Jenkinsfile_portal` 은 최상위 `agent none` 이고 단계마다 노드를 고른다. 컨트롤러(`built-in`)에는 Python 도 Ansible 도 필요 없다.

```text
parameters (loc, target_type, inventory_json, deploymentEnvironmentId, eventUuid, callbackUrl, verbosity — 운영 입력 7개뿐, 시험용 입력 없음)
  → 입력 확인 (5분)                 [agent 없음]  대상 목록을 inventory.sh 와 같은 규칙(ASCII IPv4 · 앞뒤 공백 · 중복 · 원소 타입)으로 검사,
                                                  계정 정보가 든 callbackUrl 거부 → 접수 manifest(env SE_MANIFEST_JSON) · 빌드 이름 `#N <종류> N대`
  → 실행 위치 확인 (5분)            [agent 없음]  readTrusted 로 common/vars/locations.yml 하나만 읽어 loc 검증 → 노드 라벨식
                                                  (맞는 온라인 노드가 없으면 수집을 건너뛰고 실패 결과로 보충 — UNSTABLE)
  → 서버 정보 수집 (39,000초)       [Agent]       작업 폴더 소유 기록 · manifest → (전역 ADDON_REPO_URL 이 있으면 Add-on 체크아웃 · 검사)
                                                  → 실행 한계 계산(scripts/gather_budget.sh — ansible 직전, 최대 6시간)
                                                  → scripts/run_gather.sh: 환경 경계 · venv · timeout --signal=INT --kill-after=90 <한계> ansible-playbook …
                                                    · 끝나면 이 실행의 SSH 연결을 닫아 원격 명령 정리 · gather_run.json(시작 · 끝 · 실행 시간 · 한계 도달)
                                                  → 종료 상태(seGatherOutcome: completed / timeout / timeout_killed / prep_failed / not_started_* / failed_run / aborted)
                                                  post{always}: 결과 정리(서버마다 결과 한 줄) → 오래된 작업 폴더 정리(하루 한 번) → archive → stash
                                                                → 이 빌드의 결과를 보관한 것을 확인했을 때만 작업 폴더 삭제
  pipeline post{always} → 표시 단계 '결과 확인 및 전송' [컨트롤러, 최대 1시간 — 빌드 12시간 안]
        빌드별 폴더 fin-<번호> → unstash(없으면 unarchive) → 정리된 결과 또는 Groovy 최소 보충(scripts/jenkins/se_finalize.groovy 를 readTrusted→load)
        → Portal 로 POST(시도마다 응답 최대 10분, 최대 3번, HTTP 2xx 수신 = Portal 이 요청을 받음) → callback_body.json · finalize_summary.json 보존
        → [결과 파일] 링크 → [요약]
```

> 2026-10-03: 입력 확인과 실행 위치 확인은 노드를 잡지 않는다. 종전에는 실행 위치 확인이 컨트롤러에서 저장소 **전체**를 체크아웃한 뒤
> YAML 1개를 읽었고, `main`(약 17k 파일)은 제한 시간을 넘겨 끊겼다. `readTrusted` 는 Job 의 SCM 설정(Lightweight checkout)으로 파일 하나만 읽는다.
>
> 2026-10-03 (Phase 4): `Validate Schema` 와 `Callback` stage 는 없어졌다. field_dictionary 정합은 커밋 전 `scripts/ai/ci_gate.sh`
> (pre-commit · CI) 가 맡고, 결과 전달은 **파이프라인 `post { always }`** 의 결과 확인 및 전송 단계가 맡는다 — stage 가 어디서 끊겨도(agent 대기
> 초과 · ansible 강제 종료 · 1회 Abort) 실행 **경로**가 있다. 요청한 대상 1개마다 결과 1개를 보낸다: 완료된 host 는 OUTPUT 그대로,
> Add-on 도중 끊긴 host 는 `CHECKPOINT`(조립 직후 보존본), 그 밖은 진행 기록(`gather_progress.jsonl`)에 따라 실패 봉투로 채운다 (8절).
>
> 2026-10-05 (8차): 시험용 파라미터 2개(`redfishAccountDryrun` · `gatherBudgetForceSec`)와 그 배선을 없앴다. 시간 한계는 빌드 12시간 · 수집
> 실행 최대 6시간 · 결과 확인 및 전송 1시간 셋으로 줄였다(아래 "시간 한계"). 단계 · 작업(task)마다 두던 짧은 제한, 정체 감시, 안쪽 단계 상한
> (Tier 2 · Script Approval)은 없다.

| 단계 (Stage View 표시 이름) | 노드 | 하는 일 | 실패 시 |
|-------|------|--------|--------|
| 입력 확인 | 없음 (5분) | `target_type` · `inventory_json`(JSON 배열 · 원소 객체 · `service_ip`/`bmc_ip`/`ip` 중 처음 값 · 문자열 · ASCII IPv4 · 중복 금지 — `inventory.sh` 와 같은 규칙, 위반이 하나라도 있으면 요청 전체 거부) · `callbackUrl`(`http(s)://`, 계정 정보 `사용자:비밀번호@` 금지 — 이 오류는 주소를 출력하지 않는다) · `deploymentEnvironmentId` 검증 → 접수 manifest 를 `env.SE_MANIFEST_JSON` 으로, 빌드 이름 `#N <종류> N대` | FAILURE — 접수 manifest 가 없어 보낼 것이 없다 |
| 실행 위치 확인 | 없음 (5분) | `readYaml text: readTrusted('common/vars/locations.yml')` — 미등록 `loc` 는 노드 대기 없이 즉시 실패. 라벨식을 모두 가진 온라인 노드가 없으면 수집을 건너뛴다. 콘솔 `[실행 위치] <loc> 위치의 <종류> 대상은 노드 라벨 '<라벨식>' 에서 실행합니다. 후보: …` | 미등록 loc: FAILURE · 온라인 노드 없음: UNSTABLE + outcome `no_agent`(접수 대상마다 실패 결과 전송) |
| 서버 정보 수집 | `agent_label && 능력 라벨` 노드, 작업 폴더 `<Job 이름>-<빌드 번호>` (단계 39,000초 — Runner 대기 · checkout · Add-on 준비 · 수집 · 결과 보존 포함) | `.se_workspace.json`(작업 폴더 소유 기록) · `gather_manifest.json` 기록 → (전역 `ADDON_REPO_URL` 이 있으면 Add-on 저장소를 `${WORKSPACE}/addon` 에 받고 검사 — 3절) → **실행 한계 계산**(`scripts/gather_budget.sh`, 아래 "시간 한계") → `bash scripts/run_gather.sh <playbook> <inventory> <forks> <한계> <loc> <Add-on 검사 통과> <대상 수>` — 환경 경계(`scripts/env_guard.sh`) · venv 활성화 · inventory 해석 실패는 실행 실패(`ANSIBLE_INVENTORY_UNPARSED_FAILED=True`) · vault 비밀번호 임시 파일(600) · `timeout --signal=INT --kill-after=90 <한계> ansible-playbook <채널>/site.yml -i <채널>/inventory.sh -f <forks> --vault-password-file=<임시파일> -e se_location=<loc>` · 끝나면 이 실행의 SSH 다중화 연결 종료 → `gather_rc.txt` · `gather_run.json` → 종료 상태 · 한계 사유(`seGatherOutcome`) → post{always}: 결과 정리(`scripts/finalize_gather_output.py`) → 오래된 작업 폴더 정리(`scripts/workspace_cleanup.py`, 하루 한 번) → `archiveArtifacts`(있는 파일만, 빈 보관은 실패) → `stash` → 보관을 확인했을 때만 `deleteDir` | Add-on 을 받지 못하면 UNSTABLE + Add-on 없이 수집; ansible 이 비정상 종료(한계 도달 rc 124/137, 그 밖)여도 stage 는 끊지 않고 종료 상태만 남긴다 — 결과 전달은 다음 단계가 한다. 단계 한계 · 사용자 취소는 그대로 전파(ABORTED) |
| 결과 확인 및 전송 (post 안의 표시 단계) | `built-in` — `timeout(최대 1시간) { node('built-in') { dir("fin-<빌드 번호>") } }` | `unstash` → 없으면 파일별 `unarchive` → `gather_final.jsonl`(정리 결과, exit 0/2) 우선, 없으면 Groovy 최소 경로(OUTPUT → CHECKPOINT+오류 1건 → 합성 실패 봉투) → 전송 직전 형태 검문 → `{loc, deploymentEnvironmentId, eventUuid, gatherInfoJson:[…]}` POST(시도마다 응답 최대 10분, 남은 시간 안에서 최대 3번, 결정적 4xx(408/429 제외)는 다시 보내지 않음, ABORTED 면 1번) → `[결과]` 집계 · `[경고]` · `callback_body.json` · `finalize_summary.json` 보존 · `[결과 파일]` 링크 → 보관을 확인했을 때만 폴더 삭제 | 전송 실패 · 시작 못 한 전송 · 합성 보충 · outcome ≠ completed · 보충 라이브러리 없음 · 결과 수 ≠ 접수 수 → UNSTABLE 한 번(사유는 `[경고]` 줄). 접수 manifest 조차 없으면(입력 확인 실패) 보낼 것이 없다 |

### Ansible 실행환경(venv) 선택

Gather(수집과 Layer A 마무리)는 저장소의 `scripts/activate_ansible_venv.sh` 를 한 줄로 source 한다.

```bash
. "${WORKSPACE}/scripts/activate_ansible_venv.sh" || exit 1
```

이 스크립트가 다음 순서로 venv 를 고르고, 못 찾으면 시스템 python 으로 넘어가지 않고 Stage 를 실패시킨다.

1. 노드 환경변수 `SE_ANSIBLE_VENV` (값이 있는데 틀리면 다른 경로로 넘어가지 않는다)
2. PATH 의 `ansible-playbook` 실경로 옆의 `activate` (설치 자동화 Runner 는 `/usr/local/bin/ansible-*` 링크)
3. 알려진 경로 `/app/ansible-env` → `/opt/ansible-env`

성공하면 콘솔에 `[venv] <venv 경로> python=<버전> (source=env|path|known)` 한 줄이 남는다. 서버마다 다른 venv 경로가
파이프라인 코드에 적히지 않는 이유가 이것이다 ([02-agent-node.md](02-agent-node.md) 5절·9절).

> [!NOTE]
> pytest 회귀(`tests/e2e`, `tests/integration -m "not live"`, `tests/regression`)와 field_dictionary 정합
> (`tests/validate_field_dictionary.py`)은 Jenkins 수집 Job 의 단계가 아니다 (2026-10-03 부터 후자도). 커밋 전
> `bash scripts/ai/ci_gate.sh` 가 둘 다 돌린다. 같은 검사를 Jenkins 에서 돌리는 main 전용 CI Job 은 `Jenkinsfile_ci`
> (`clovirone-cicd/clovirone-server-gather-ci`, 2026-10-04 등록 — `03-job-registration.md`) 이며 수집 Job 과 별개다.

### 시간 한계 (2026-10-05 8차 — 셋으로 줄였다)

정상적으로 오래 걸리는 수집을 자르지 않는다. 멈추는 것은 **수집 실행 한계(최대 6시간)** 와 **사용자 취소**뿐이고, 빌드 전체 12시간과
결과 확인 및 전송 1시간은 그 바깥 틀이다. 연결 · 응답 대기는 통신 규약 값이라 "작업이 오래 걸린다" 로 끊지 않는다.
정본 값은 `Jenkinsfile_portal` 의 `seConstants()` 와 `scripts/gather_budget.sh` 이고, `tests/unit/test_time_limits.py` 가 두 파일 · 파이프라인 옵션 · 각 채널 값이 같은지 본다.

| 한계 | 값 | 어디서 | 넘었을 때 |
|---|---|---|---|
| 빌드 전체 | 12시간 (43,200초) | `options { timeout(12 시간) }` | Jenkins 가 ABORTED 로 끝낸다. 결과 확인 및 전송은 이 안에서 돈다 |
| 입력 확인 · 실행 위치 확인 | 각 5분 | stage `options.timeout` | FAILURE |
| 서버 정보 수집 단계 | 39,000초 (10시간 50분) = 12시간 − 10분 − 1시간 | stage `options.timeout` — Runner 대기 · checkout · Add-on 준비 · 수집 · INT 뒤 정리 · 결과 보존 포함 | outcome `aborted`(`interruption=stage_limit`) 기록 뒤 전파, 결과 확인 및 전송은 이어서 시도 |
| **수집 실행 한계** | `min(6시간, 단계 남은 시간 − 90 − 900, 빌드 남은 시간 − 1시간 − 90 − 900)` — ansible 직전에 실제 수집 시작 기준으로 계산 | `scripts/gather_budget.sh` → `scripts/run_gather.sh` 의 `timeout --signal=INT --kill-after=90` | INT 로 멈추고 90초 뒤에도 남으면 KILL → outcome `timeout`/`timeout_killed`, `limit_reason` = `gather_limit`(6시간) 또는 `build_limit`(Runner 대기 · 준비가 길어 6시간을 보장하지 못한 경우 — 콘솔 `[시간]` 줄이 미리 알린다). 끝난 대상의 결과는 보존하고 끝나지 않은 대상만 실패 결과로 채운다 |
| INT 뒤 정리 시간 | 90초 | `--kill-after=90` (= `GRACE_SEC`) | KILL |
| 결과 보존 몫 | 900초 | `AGENT_POST_SEC` — 수집 단계 안에 미리 남긴다(결과 정리 · 작업 폴더 정리 · archive · stash, 단계별 제한 없음) | — |
| 최소 시작 | 120초 | 남은 한계가 이보다 짧으면 시작하지 않는다 | `not_started_budget` — 접수 대상은 실패 결과로 |
| 메모리 보호 | forks ≤ `floor((MemAvailable × 40 % − 200) / 80)` | 2026-10-04 Runner 실측(slot 최악 69 MB · 메인 86 MB) | forks 를 줄인다. 1 도 안 되면 `not_started_memory` |
| 결과 확인 및 전송 | `min(1시간, 빌드 끝 − 지금 − 60초)` | `timeout { node('built-in') }` — 노드 대기 · 회수 · 조립 · 본문 · 전송 · 보관을 모두 합해 센다 | 전파(ABORTED). 시작 못 한 전송은 `callback_not_attempted` 로 남는다 |
| Portal 응답 대기 | 시도마다 최대 10분(남은 시간 − 10초 안), 최대 3번(취소된 빌드 1번), 사이 대기 10 · 20초, 남은 시간 30초 미만이면 시작하지 않음 | `seCallback` — 요청 도구(http_request)는 연결과 응답 대기에 같은 값을 쓴다 | 다음 시도 또는 실패 기록. 2xx 는 Portal 이 요청을 받았다는 뜻이다 |
| SSH 연결 | 60초 (`ansible_timeout` · `ConnectTimeout=60`), 연결 유지 확인 10초 × 3 | `os-gather/site.yml` | 그 host 의 연결 실패로 기록 |
| OS 후보 포트 탐색 연결 | 포트마다 10초 (`_probe_timeout`) | DROP 방화벽에서 SYN 재시도 3회를 허용하는 값. 연결 거부는 바로 다음 후보로(포트당 1회) | 다음 후보 포트 |
| OS 프로토콜 확인 응답 | 60초 (SSH 배너 · WinRM Identify) | `_precheck_timeout_protocol` | 그 포트 실격 |
| WinRM | 작업 60초 · 읽기 70초 | WS-Management 통신 규약 값(긴 명령은 응답을 다시 받아 계속 기다린다) — 유지 | — |
| Windows setup 사실 수집 | 수집기마다 30분 (`gather_timeout: 1800`) | 모듈 기본 10초는 느린 WMI 에서 값을 조용히 빼먹는다 | 그 수집기의 값만 빠진다 — `_w_setup_ok` 로 기록하고 메모리 · 식별자 진단이 이유를 적는다 |
| 사전 점검(ESXi · Redfish) | 포트 연결 60초 · 프로토콜 응답 30분 | `run_precheck.yml` · `_precheck_timeout` | 진단 단계 `port` / `protocol` |
| Redfish 요청 | 연결 60초(`CONNECT_TIMEOUT_SEC`) · 응답 대기 30분(`_rf_timeout: 1800`, 읽기 한 번마다) | `redfish_gather.py` · `redfish-gather/site.yml` | 그 요청의 실패로 기록 |
| ESXi 응답 | 30분 (`_precheck_timeout` · `esxi_disks.py` `_DEFAULT_TIMEOUT_SEC`) | vSphere API 읽기 한 번마다 | 그 구성요소의 실패로 기록 |
| Add-on 받기 | git 명령마다 30분, 2번까지 | `scripts/addon_checkout.sh` — 준비 단계. 길어진 만큼 수집 실행 한계가 줄어든다(보존 몫 · 결과 확인 및 전송 1시간은 줄지 않는다) | UNSTABLE + Add-on 없이 수집 |

없앤 것(2026-10-05 8차 R3 — 정상 작업을 잘랐다): 작업(task) 단위 제한(Linux 120초 · Windows/ESXi 180초 · Add-on 300초 · Redfish 탐지 120 · 수집 1,260 · 계정 240초),
Redfish 모듈 마감(절대 1,200초 · 새 응답 없음 120초 · 탐지 90 · 계정 180초)과 진행 표시, 정체 감시(420초, `gather_watch.py`), `df` 20초,
결과 정리 120초, 보존 archive · stash 30초, 조립 · 본문 60초(Tier 2 `SE_FINALIZER_BOUNDED` · Script Approval 4 서명 포함), 시험용 강제 한계.
예상 시간(`expected`)은 안내용으로만 계산하고 멈추는 데 쓰지 않는다.

콘솔에는 기계용 `[Budget] exec …` 한 줄과 사람이 읽는 `[시간]` 줄이 남는다:
`[시간] 실제 수집은 최대 6시간(21600초) 실행합니다. 예상 시간은 약 10분이며 안내용입니다. 예상보다 오래 걸려도 중단하지 않습니다.`
한계에 닿으면 `[수집 종료] 수집은 수집 실행 한계(6시간) 6시간(21600초)에 도달해 멈췄습니다. 실행 시간 …. 끝난 대상 N대, 끝나지 않은 대상 M대(…)` 와
`[수집 종료] 결과 보존: 완료. Portal 전송: HTTP 200 응답 받음.` 이 이어진다. 시간으로 끝난 host 의 합성 결과에는 `diagnosis.details.limit_reason` 이 붙는다
(CHECKPOINT 결과는 `errors[].detail`, 실행 단위 정본은 `finalize_summary.json` 의 `limit_reason` · `limits` · `gather_run`).

### 원격 명령 정리 (2026-10-05 8차 R6)

Linux 수집 명령은 raw 로, 터미널(pty)과 함께 실행된다(`ansible_ssh_use_tty`). SSH 연결이 닫히면 원격 명령과 그 자식은 SIGHUP 으로 끝난다.
그런데 ansible 의 작업 프로세스는 자기 세션에서 돌아 실행 한계의 INT 가 ansible 주 프로세스에만 간다 — 주 프로세스가 멈춰도 SSH 다중화 연결
(ControlMaster, ControlPersist 60초)이 남아 원격 명령이 계속 돌았다. `scripts/run_gather.sh` 는 실행마다 자기 다중화 위치(`/tmp/se_cp.*`)를 쓰고,
ansible 이 어떻게 끝났든(정상 · 한계 · 취소 신호) 그 위치의 연결에 종료(`ssh -O exit`)를 보낸 뒤 그 위치를 명령줄에 가진 ssh 프로세스만 끝낸다.
이름으로 일반 프로세스를 끝내지 않고, 대상 서버에서 프로세스를 찾아 죽이지 않는다.

| 상황 (Linux `.161` RHEL 8.10 실측, 2026-10-05) | 고치기 전 남은 원격 명령 | 고친 뒤 |
|---|---|---|
| 출력 없이 200초 걸리는 명령, 한계 400초 | 정상 완료 | 정상 완료(202초) |
| 실행 한계(25초) | 1개 | 0 |
| 실행 한계 + sudo(become) | 3개 | 0 |
| 빌드 취소(빌드 프로세스 전부 TERM → KILL) | 0 | 0 |
| 연결 종료(ssh 프로세스 KILL) | 0 | 0 |
| 취소 · 연결 종료 + sudo | 0 | 0 |

남는 한계: 디스크 대기(D 상태)처럼 신호로 끝나지 않는 원격 프로세스, 네트워크가 갑자기 끊겨 대상 sshd 가 연결이 닫힌 것을 모르는 경우
(대상 쪽 TCP keepalive · ClientAlive 설정이 정리할 때까지 남을 수 있다). Windows(WinRM)는 셸 종료로 정리된다.

### 시각 기록 (2026-10-05 8차 R2)

- Timestamper 플러그인이 있으면 각 단계를 `timestamps { }` 로 감싸 콘솔 줄마다 시각이 붙는다(Job 범위 — 전역 설정을 바꾸지 않는다).
  플러그인이 없는 Jenkins 에서는 감싸지 않고 그대로 진행한다(블록에 들어가기 전의 `NoSuchMethodError` 만 확인 — 고객사 Jenkins 를 깨지 않는다).
- 업무 사건 줄은 플러그인과 무관하게 본문에 날짜 · 시각 · 시간대를 적는다: `[2026-10-05 21:10:03 +09:00] [수집] 시작합니다. …` —
  수집 시작 · 끝, 결과 보존 시작 · 끝, Portal 전송 시도마다 시작 · 응답(또는 예외) · 재시도 대기 · 최종 결과 또는 미시도, 결과 확인 시작.
  시각은 그 줄을 쓴 노드의 시계다(Runner 의 `run_gather.sh` · 컨트롤러의 Groovy).
- 기록용 값은 UTC ISO 8601 이다: `finalize_summary.json` 의 `times{build_started_at, gather_started_at, gather_ended_at, finalize_started_at}` ·
  `callback{started_at, ended_at, tries[{attempt, started_at, timeout_sec, ended_at, elapsed_ms, http_code, outcome, error, retry_wait}]}` ·
  `gather_run.json` 의 `started_at · ended_at`. 전송을 시작하지 않았으면 `attempted=false · attempts=0` 이고 시각이 없다.
- 기계가 읽는 줄(`[Budget] exec …` · `[Trusted] …` · `[기술 기록] …`)과 결과 JSON 줄에는 시각 접두어를 붙이지 않는다.
  증거 수집기(`scripts/ai/prodgen/evidence.py`)는 Timestamper 접두어가 붙은 콘솔도 같은 값으로 읽는다.
- envelope 13 필드와 `meta.duration_ms` 는 바꾸지 않았다.

## 2. Jenkins 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|------|------|
| `loc` | string | 필수 | 실행 위치 — `common/vars/locations.yml` 의 키 (ic / cj / yi / git) |
| `target_type` | choice | 필수 | os / esxi / redfish |
| `inventory_json` | text | 필수 | 대상 목록 JSON 배열 (os/esxi: `service_ip`, redfish: `bmc_ip`, 없으면 `ip`) — ASCII IPv4 만, 중복 불가, 하나라도 어긋나면 요청 전체 거부(`inventory_json[<번호>] …` 오류) |
| `deploymentEnvironmentId` | string | 필수 | Portal 배포 환경 ID — 전송 본문에 그대로 |
| `eventUuid` | string | 선택 | Portal 이벤트 UUID — 전송 본문에 그대로 |
| `callbackUrl` | string | 필수 | 결과를 보낼 Portal 주소 — `http(s)://` 로 시작, 따옴표·백틱·역슬래시·공백 불가, 계정 정보(`사용자:비밀번호@`) 불가(2026-10-05). 뒤에 `/api/jenkins/gather/<target_type>` 을 붙여 POST |
| `verbosity` | choice | 선택 | Ansible verbosity 0~4 (`ANSIBLE_VERBOSITY`) |

시험용 파라미터는 없다(2026-10-05 8차 R1). 종전 `redfishAccountDryrun` · `gatherBudgetForceSec` 와 그 배선(`-e _rf_account_service_dryrun` ·
`SE_FORCE_SEC` · 빌드 이름의 `[시험: …]`)을 지웠고, 옛 값을 다시 넣어도 아무것도 켜지지 않는다. Redfish 모듈의 dry-run 과 계정 복구
계약은 그대로다. 계정 쓰기 방지와 한계 도달 · 보존은 후보 코드의 시험 경로가 증명한다 — CI Gate 의 단위 시험(같은 main SHA)과
Harness `gather_limit_preserve`(실제 `run_gather.sh` 가 시험 한계에 닿은 뒤 운영 함수가 보존 · 전송). 운영 Job 은 정상 입력만 받는다.

### inventory_json 형식
```jsonc
// os/esxi 는 service_ip, redfish 는 bmc_ip 키를 쓴다. 둘 다 없으면 ip 로 fallback.
[
  { "service_ip": "10.50.11.232" }
]
```

> 포털은 ip만 전달한다. 계정은 vault에서 자동 로딩된다.
> 상세 명세는 [docs/contract/01-input.md](../contract/01-input.md) 참조.

## 3. 환경변수

Jenkinsfile 이 설정한다.

| 변수 | 범위 | 값 |
|------|------|----|
| `INVENTORY_JSON` | 전체 | `${params.inventory_json}` — `inventory.sh` 가 읽는다 |
| `PYTHONDONTWRITEBYTECODE` | 전체 | `1` |
| `REPO_ROOT` | Gather | `${WORKSPACE}` — adapter / vault 로딩 기준 |
| `ANSIBLE_CONFIG` | Gather | `${WORKSPACE}/ansible.cfg` |
| `ANSIBLE_JSON_OUTPUT_FILE` | Gather | `${WORKSPACE}/gather_output.json` — `json_only` 콜백이 envelope 을 쓴다 (flush+fsync) |
| `ANSIBLE_JSON_MANIFEST_FILE` | Gather | `${WORKSPACE}/gather_manifest.json` — 접수 집합. 콜백이 inventory 와 대조해 다르면 stderr 로 알린다 (2026-10-03) |
| `ANSIBLE_JSON_PROGRESS_FILE` | Gather | `${WORKSPACE}/gather_progress.jsonl` — host 전이 이벤트(first_seen · precheck · cred_load · auth_proven · checkpoint · addon_started · addon_done · emitted · reconciled · lost). 결과 정리가 누락 봉투를 채울 때 읽는다 |
| `ANSIBLE_JSON_CHECKPOINT_FILE` | Gather | `${WORKSPACE}/gather_checkpoint.jsonl` — Add-on 직전 조립본(`CHECKPOINT` 태스크) host 당 1줄 |
| `SE_AUTH_EVIDENCE_DIR` / `SE_BUILD_ID` / `SE_EVENT_UUID` | Gather | `${WORKSPACE}/gather_auth_evidence` / `${BUILD_TAG}` / `${params.eventUuid}` — Redfish 모듈이 시도(attempt)마다 남기는 인증 증거 파일(비밀값 없음). task timeout 뒤 rescue 가 현재 시도의 파일만 읽어 401 / 인증 뒤 정지 / 확인 전 정지를 가른다 ([../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md)) |
| `ANSIBLE_VERBOSITY` | Gather | `${params.verbosity}` |
| `ADDON_DIR` | Gather 의 ansible 실행만 | `${WORKSPACE}/addon` — Add-on 을 켜고(아래 전역 변수) 받은 파일이 검사를 통과한 빌드에만 있다. 상위 환경에서 넘어온 값은 환경 경계가 지운다 |
| `ANSIBLE_SSH_CONTROL_PATH_DIR` | Gather 의 ansible 실행만 | `run_gather.sh` 가 실행마다 만드는 `/tmp/se_cp.XXXXXX` — 이 실행의 SSH 다중화 연결 위치. 끝나면 그 연결만 닫고 지운다(원격 명령 정리) |
| `ANSIBLE_INVENTORY_UNPARSED_FAILED` | Gather 의 ansible 실행만 | `True` — inventory 스크립트가 요청을 거부하면 빈 inventory 로 rc 0 을 내지 않고 실행 실패(outcome `failed_run`). ansible.cfg 가 아니라 이 실행에만 켠다(진단용 ad-hoc 명령 · 시험 도구는 영향 없음) |

환경 경계(`scripts/env_guard.sh`, 2026-10-05 F05): 수집 셸은 상위 환경에서 넘어온 시험용 · 재정의 값(`SE_FORCE_LINUX_RAW_FALLBACK` · `JSON_ONLY_NO_RECONCILE` · `ANSIBLE_JSON_OUTPUT_TASK` · `ANSIBLE_JSON_CHECKPOINT_TASK` · `ANSIBLE_STDOUT_CALLBACK` · `SE_VENDOR_ALIASES_PATH` · `SE_MEM_AVAILABLE_MB`, 검사 통과 전 `ADDON_DIR`)을 지우고 콘솔에 **이름만** 남긴다: `[수집] 상위 환경에서 넘어온 시험용 설정을 이번 실행에서 지웠습니다: …`.

노드 쪽 선택 환경변수(`SE_ANSIBLE_VENV`)는 [08-ansible-config.md](08-ansible-config.md) 3절.

### Add-on (고객별 추가 수집) — 전역 환경변수와 Gather 안의 흐름

Jenkins 관리 → System → Global properties → Environment variables. 노드 설정 · Runner 사전 작업은 없다.

| 변수 | 필수 | 기본값 | 의미 |
|---|---|---|---|
| `ADDON_REPO_URL` | 켤 때 필수 | (없음 = 꺼짐) | Add-on 저장소 URL (`https://` · `http://` · `ssh://`) |
| `ADDON_REPO_REF` | 선택 | `main` | 브랜치 · `refs/tags/<태그>` · 40자 커밋 해시 (짧은 해시는 거부) |
| `ADDON_REPO_CREDENTIALS_ID` | 선택 | 없음 (익명) | 비공개 저장소의 Jenkins credential ID — Username with password (사용자 이름 + 토큰) |
| `ADDON_REPO_SSL_VERIFY` | 선택 | `false` | `true` 면 TLS 인증서를 검증. 기본은 검증하지 않아 자체 서명 내부 GitLab 도 Runner 에 CA 설치 없이 된다. 검증 해제는 Add-on 을 받는 git 명령에만 붙는다 (`-c http.sslVerify=false`) — 전역 git 설정 · 메인 체크아웃 · 다른 Job 무관 |

`ADDON_REPO_URL` 이 없으면 Add-on 을 실행하지 않는다. 있으면 Gather 가 빌드마다 다음을 한다.

1. Add-on 저장소의 `ADDON_REPO_REF`(기본 `main`)를 `${WORKSPACE}/addon` 에 받는다 (두 번까지 시도). 콘솔
   `[addon] <URL>@<ref> <커밋>`. 실측(2026-10-04 production #76/#79/#80) 받기 + 검사 ≈ **2~3 s/빌드**(`[Budget] est … prep=2s` → `exec … prep=4~5s`);
   ESXi · Redfish 빌드도 "실행할 기능 없음" 을 알기 위해 이 시간을 쓴다(지원 여부는 Add-on 저장소 안의 layout 이라 받기 전에는 알 수 없다 — 비용이 작아 그대로 둔다).
   최악치: git 명령마다 30분 제한(2026-10-05 8차 — 종전 180 s) × 2번 시도. 준비가 길어진 만큼 `[Budget] exec` 재계산이 수집 실행 한계를 줄인다(보존 몫 · 결과 확인 및 전송 1시간은 줄지 않는다). Add-on 의 태스크별 시간 제한(종전 300 s)은 없앴다 — 끝나지 않는 Add-on 은 수집 실행 한계가 멈춘다.
2. 받은 파일을 검사한다 — 설정 파일(`config/`)의 형식, 태스크 YAML 문법 등. 설정 작성 오류는 여기서 한 번에 막혀
   서버마다 반복되지 않는다. 콘솔 `[addon] 검사 통과: linux, windows` 또는 `[addon] 검사 실패: <파일>: <이유>`.
3. 검사를 통과하면 그 빌드의 수집에 Add-on 을 넣는다. ESXi · Redfish 빌드는 Add-on 이 할 일이 없어 켜지 않는다
   (콘솔 `[addon] 실행할 기능 없음`, UNSTABLE 아님).
4. 받지 못하거나(URL · ref · 인증 · 인증서 · 저장소 다운) 검사에 실패하면 콘솔에 `[addon] unavailable: <사유>` 를 남기고
   빌드를 UNSTABLE 로 표시한 뒤 Add-on 없이 수집한다. 기본 수집 · 마무리(Callback) 은 정상이고 서버별
   결과(`errors[]`)에 Add-on 오류가 붙지 않는다 — 저장소 문제는 서버 문제가 아니다.

받은 파일은 빌드가 끝나면 작업 공간과 함께 지운다 (빌드마다 새로 받는다).

Add-on 안에서 무엇이 실행되는지(Software 설정 `config/linux/software.yml` · `config/windows/software.yml`, 자동으로
도는 hosts 기능의 DB IP 수집)는 Add-on 저장소 README, hook 계약은 [../develop/07-addon-hook.md](../develop/07-addon-hook.md).

## 4. Ansible 실행 방식

플러그인(`ansiblePlaybook` 스텝)을 쓰지 않는다. `sh` 로 직접 실행한다.

```bash
. "${WORKSPACE}/scripts/activate_ansible_venv.sh" || exit 1
chmod +x <채널>/inventory.sh
VAULT_TMP="$(mktemp)"; trap 'rm -f "$VAULT_TMP"' EXIT
printf '%s' "$VAULT_PASSWORD" > "$VAULT_TMP"; chmod 600 "$VAULT_TMP"
ansible-playbook <채널>/site.yml -i <채널>/inventory.sh --vault-password-file="$VAULT_TMP" -e se_location=<loc>
```

`VAULT_PASSWORD` 는 Jenkins credential `server-gather-vault-password`(Secret text)를 `withCredentials` 로 주입한 값이다
(콘솔 마스킹). 등록 절차는 [01-jenkins-master.md](01-jenkins-master.md) 7절.

### 채널별 실행 경로

| target_type | playbook | inventory |
|-------------|----------|-----------|
| redfish | `redfish-gather/site.yml` | `redfish-gather/inventory.sh` |
| os | `os-gather/site.yml` | `os-gather/inventory.sh` |
| esxi | `esxi-gather/site.yml` | `esxi-gather/inventory.sh` |

## 5. Jenkins 플러그인 요구사항

| 플러그인 | 필수 | 용도 |
|---------|------|------|
| Pipeline | 필수 | Declarative Pipeline |
| Pipeline Utility Steps | 필수 | `readYaml` · `readJSON` (실행 위치 확인 · 결과 확인 및 전송) |
| Credentials Binding | 필수 | `withCredentials` — vault 비밀번호 |
| HTTP Request | 필수 | `httpRequest` (Callback) |
| Git | 필수 | SCM checkout (Agent 에 CLI `git` 필요) |
| Ansible | 선택 | `ansiblePlaybook` 스텝을 쓰는 다른 파이프라인용 — 이 파이프라인은 쓰지 않는다 |

## 6. Credentials

| ID | 타입 | 용도 |
|----|------|------|
| `server-gather-vault-password` | Secret text | Ansible vault 복호화 (Gather) |
| 저장소 읽기 credential | Username/password 또는 token | Pipeline SCM checkout |

## 7. Jenkins Agent 요구사항

> Python / Java / Ansible / 패키지 버전 요건은 `REQUIREMENTS.md` 4절 참조.
> 설치 절차는 [02-agent-node.md](02-agent-node.md).

| 항목 | 요구사항 |
|------|---------|
| Label | `common/vars/locations.yml` 의 `agent_label` (ic / cj / yi / git) + 수집할 target_type 의 능력 라벨 (`os` 는 `linux` 와 `windows`, `esxi` 는 `esxi`, `redfish` 는 `redfish`) — [02-agent-node.md](02-agent-node.md) 8절 |
| venv | `/app/ansible-env` 또는 `/opt/ansible-env`, 아니면 노드 환경변수 `SE_ANSIBLE_VENV` |
| CLI `git` | Gather 의 체크아웃, Add-on 체크아웃(`scripts/addon_checkout.sh`)에 필요 |
| Add-on 저장소 접근 | 전역 `ADDON_REPO_URL` 을 켠 경우 Agent 에서 그 URL 에 닿아야 한다 (자체 서명 인증서는 기본값으로 통과 — CA 설치 불필요) |
| 네트워크 | 대상 서버 (SSH 22 / WinRM 5985·5986 / BMC 443) 접근 가능 |
| 디스크 | 작업 폴더 + ansible 로그 공간 (빌드마다 `<Job 이름>-<빌드 번호>` 작업 폴더를 만들고, 결과 보관을 확인하면 지운다 — 남은 폴더는 9절의 정리) |

### 동시 실행과 메모리 (2026-10-05 측정)

- Runner 1대(RAM 7.5 GB · executor 15)에 수집 빌드 3~4개가 겹쳐도 남은 메모리는 4.6 GB 이상이었고 swap 은 늘지 않았다. 빌드 하나는
  최대 약 0.56 GB(Linux 15대 · Redfish 10대 배치)를 쓴다. 측정표는 `tests/evidence/2026-10-05-final-maintenance.md` 6절.
- 기본값은 제한 없음이다(두 수집 Job 의 Throttle Concurrent Builds 비활성). 한 Runner 에 무거운 빌드가 10개 가까이 겹칠 수 있는 규모라면
  전역 설정에 throttle 카테고리(예: `clovirone-gather`, 노드당 6)를 만들고 두 수집 Job 에서 그 카테고리를 켠다. 끄면 원래대로 돌아간다(코드 변경 없음).
- 빌드 시작 때의 메모리 보호(`scripts/gather_budget.sh` 의 `mem_cap`)는 그 시점 MemAvailable 로 forks 를 줄인다. 같은 순간에 시작한 빌드끼리는
  같은 여유를 보고 몫을 잡는다는 한계가 있다.
- 같은 BMC 를 여러 빌드가 동시에 요청하면 느린 BMC(예: Cisco C220 CIMC)의 응답이 길어진다. 8차부터 Redfish 모듈 마감이 없어 끊기지 않고 기다리며,
  멈추는 것은 수집 실행 한계뿐이다. 같은 대상의 중복 요청은 호출 측에서 정리한다.

## 8. 결과 전달

- Gather 가 만든 `gather_output.json` 은 host 마다 envelope 한 줄(JSON Lines)이다. 파이프라인 `post { always }` 의 마무리 단계
  (컨트롤러)가 `unstash`(없으면 같은 빌드의 artifact 를 `unarchive`) 해서 `{loc, deploymentEnvironmentId, eventUuid, gatherInfoJson:[...]}`
  본문으로 `<callbackUrl>/api/jenkins/gather/<target_type>` 에 POST 한다.
- **요청한 대상 1개 = 결과 1개.** Gather 의 `post{always}` 가 먼저 Layer A(`scripts/finalize_gather_output.py`)로 `gather_final.jsonl` 을 만든다:
  OUTPUT 줄(13 필드 · 접수 IP 검사) → 없는 host 는 `CHECKPOINT` 줄(Add-on 직전 조립본; Add-on 중 끊겼으면 "추가 수집 중 처리가 중단되어 …"
  오류 1건, 아니면 "결과를 내보내는 단계에서 중단" 1건) → 그래도 없는 host 는 진행 기록으로 실패 봉투 합성(precheck 진단 보존 / 인증 뒤
  중단 `GATHER_FAILED` auth true / 연결 끊김 `AUTH_PROBE_FAILED` / 그 밖 `OUTPUT_BUILD_FAILED`). 보고서 `gather_finalize_report.json`
  (accepted · kept · filled · dropped · conflicts). Layer A 가 없거나 실패(exit 3)하면 컨트롤러 Groovy 가 OUTPUT → CHECKPOINT → 합성 봉투의
  최소 경로로 같은 수를 맞춘다 (progress 기반 stage 분류는 하지 않는다 — 보고서에 남는 차이).
- 전송은 남은 시간 안에서 최대 3번(시도마다 응답 최대 10분; 5xx · 408 · 429 · 연결 실패만 다시 보내고, 그 밖 4xx 는 중단; 빌드가 ABORTED 면 1번).
  **HTTP 2xx 를 받으면 Portal 이 요청을 받았다는 뜻이고 이 Job 의 전달은 끝난다**(2026-10-05 사용자 결정 — Portal 의 저장 · 반영 확인은 이 Job 의 역할이
  아니고 응답 본문은 보지 않는다). 콘솔은 2xx 를 "Portal DB 저장 완료" 로 적지 않는다.
  모두 실패하면 UNSTABLE 이고 본문은 `callback_body.json` artifact 로 남는다 — 수집 자체가 성공했으면 빌드를 FAILURE 로 만들지 않는다.
- 운영자가 콘솔에서 바로 읽는 줄(2026-10-05 F13):
  `[결과] 요청 N대: 성공 a, 부분 성공 b, 실패 c.`(보낸 결과의 status 를 직접 센다) · 실패 결과를 새로 만든 수 · CHECKPOINT 로 보낸 수(있을 때만) ·
  `[수집 종료] …`(정상 종료가 아닐 때: 어떤 한계 · 실행 시간 · 끝난/끝나지 않은 대상 수 · 보존 · 전송) · `[경고] …`(실제로 생긴 조건만, 한 줄에 하나) ·
  `[결과 파일]` 링크(보관을 확인한 파일만: 서버별 수집 결과 `gather_final.jsonl` · Portal 로 보낸 본문 `callback_body.json` · 실행 요약 `finalize_summary.json`) ·
  `[요약]`(빌드 결과 · 시작 시각 · 소요 시간 · 대상 · 결과 · 전송 · 확인할 것). 문구는 운영자가 읽는 말로 쓴다 — 구분 기호 대신 문장, 내부 용어(Layer A 등) 대신 하는 일.
  기술 값은 `[기술 기록] …` 한 줄에 모은다.
- `finalize_summary.json`: `accepted · lines · kept · filled · outcome · limit_reason · status_counts{success, partial, failed, missing} ·
  warnings[](callback_failed · callback_not_attempted · callback_interrupted · body_not_saved · count_mismatch · filled · outcome_<값> · layer_b_unavailable ·
  preserve_failed · preserve_archive_failed) · callback{attempted, delivered, http_code, attempts, reason, interrupted, started_at, ended_at, tries[]} ·
  times{…} · limits{build_sec, stage_sec, finalizer_sec, gather_max_sec, gather_limit_sec, gather_limit_source, finalize_limit_sec} · gather_run · interruption ·
  layerA · layerB · source · node_wait_sec · unrecovered · damage · by_origin · recovery_limited · preserve`.
  UNSTABLE 은 한 번만 표시한다 — 전송 실패(또는 시작 못 함) · 그 밖 경고(보존 경고는 수집 단계가 이미 표시) 순.
- Groovy 최소 경로의 함수(`seReconcileRaw` 등)는 `scripts/jenkins/se_finalize.groovy` 하나가 정본이다 — 마무리 단계가 `readTrusted` 로 읽어 `load` 하고,
  CI Job(`Jenkinsfile_ci`)이 같은 파일로 Python Layer A 와의 동치를 검사한다. 파일을 못 읽으면 보충 없이 있는 OUTPUT 줄만 보내고 UNSTABLE(`layerB=unavailable`)이다.
- **파이프라인이 시작되기 전의 실패는 결과를 보내지 못한다.** Jenkins 가 Jenkinsfile 을 저장소에서 읽지 못하면(예: 2026-10-06 07:48 production #143 —
  컨트롤러가 `github.com` 이름을 해석하지 못해 `production` 브랜치를 가져오지 못했다) 파이프라인 코드가 하나도 실행되지 않으므로 결과 · 전송 · artifact 가 없다.
  콘솔이 `hudson.plugins.git.GitException` 으로 시작하고 stage 가 없는 빌드다. 결과를 받지 못한 요청을 다시 보낼지는 호출 측(Portal)이 정한다.
- envelope 형식은 [../contract/02-output-envelope.md](../contract/02-output-envelope.md), 실패 봉투의 stage/code 는
  [../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md).

## 9. 보존 기간과 작업 폴더 정리 (2026-10-05 8차 R8)

| 대상 | 기간 · 개수 | 어디서 |
|---|---|---|
| 빌드 기록 | 14일, 최대 100개 | `buildDiscarder(logRotator(daysToKeepStr '14', numToKeepStr '100', …))` — Job 범위(두 수집 Job 이 같은 Jenkinsfile 을 쓴다) |
| 결과 파일(artifact) | 7일, 최대 50개 빌드 | 같은 설정의 `artifactDaysToKeepStr '7'` · `artifactNumToKeepStr '50'` |
| Runner 작업 폴더 | 보관을 확인하면 그 빌드가 바로 지운다. 남은 폴더는 끝난 지 7일 뒤 하루 한 번 정리 | `scripts/workspace_cleanup.py` (서버 정보 수집 단계의 결과 보존 중에 부른다) |
| 컨트롤러 결과 확인 폴더 | 빌드마다 `fin-<빌드 번호>`. 보관을 확인하면 지운다. 남은 폴더는 7일 뒤 하루 한 번 정리(보관하지 않은 폴더는 지우지 않고 알린다) | `seCleanOldFinalizerDirs` |

작업 폴더 정리 규칙(`scripts/workspace_cleanup.py`, 같은 Runner · 같은 Job 기준 하루 한 번, 잠금으로 겹침 방지):
- 이 Job 의 `<Job 이름>-<번호>` 폴더만, 소유 기록(`.se_workspace.json`) 또는 옛 접수 목록이 이 Job · 이 번호를 가리킬 때만 본다.
  지금 빌드 · 링크 · 상위 밖 경로 · 다른 Job/번호 · 아직 실행 중일 수 있는 폴더(끝 기록이 없고 시작 뒤 12시간 + 1시간 안 · 프로세스가 쓰는 중) · 7일이 안 된 폴더는 건드리지 않는다.
- 결과 보관을 확인한 폴더와 결과 파일이 없는 폴더는 통째로 지운다.
- **보관하지 못한 결과가 있는 폴더는 결과 파일(`gather_*` · `callback_body.json` · `finalize_summary.json` · `gather_auth_evidence/`)만 그 자리에 남기고**
  다시 만들 수 있는 부분(저장소 사본 · Add-on 사본)만 지운다. 남긴 목록은 `.se_kept_results.json` 에 적고, 실행할 때마다 수와 크기를 알린다 — 그 빌드의
  유일한 결과일 수 있어 자동으로 지우지 않는다(사람이 확인한 뒤 지운다).
- 결과는 콘솔 `[작업 폴더 정리] …` 줄(지운 폴더 · 줄인 폴더 · 남긴 결과 · 디스크 남은 공간)과 빌드에 보관하는 `workspace_cleanup.json`. 정리 실패는 수집 결과 ·
  빌드 결과를 바꾸지 않는다(종료 코드 항상 0).
- 고객사 main-only 설치에도 같은 코드로 적용된다(Jenkinsfile · 스크립트에 들어 있다 — 별도 설정 없음).

---

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| Jenkins Job 등록 | [03-job-registration.md](03-job-registration.md) |
| 호출자 입력 형식 | [../contract/01-input.md](../contract/01-input.md) |
| 실패 처리 정책 | [../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md) |
