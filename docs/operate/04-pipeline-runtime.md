# 파이프라인이 실제로 하는 일

이 문서는 수집 파이프라인 `Jenkinsfile_portal`이 실행되는 순서, 각 단계가 어느 노드에서 도는지, 시간 한계, 실행 기반 장애 처리, 결과 전달, 실행 기록 보관과 장애 확인 방법을 현재 코드 기준으로 설명합니다.
`Jenkinsfile_portal`을 고치려면 이 문서의 구조를 먼저 읽으세요. 정본은 코드이며 이 문서는 코드와 다를 때 코드를 따릅니다.

## 1. 단계 구조

`Jenkinsfile_portal`은 최상위 `agent none`이고 단계마다 노드를 고릅니다. Controller에는 Python도 Ansible도 필요 없습니다.

| 단계 (Stage View 이름) | 노드 | 하는 일 | 실패 시 |
|---|---|---|---|
| 입력 확인 | 없음 (5분 한계) | 파라미터 검증, 대상 목록을 `inventory.sh`와 같은 규칙으로 검사, 접수 목록(manifest)을 만듭니다 | FAILURE. 보낼 결과가 없습니다 |
| 실행 위치 확인 | 없음 (5분 한계) | `readTrusted`로 `common/vars/locations.yml` 하나만 읽어 `loc`를 검증하고 Runner 라벨식을 정합니다. 등록된 Runner가 0이면 설정 오류입니다 | FAILURE. 접수된 대상마다 실패 결과는 보냅니다 |
| 서버 정보 수집 | 라벨식에 맞는 Runner. 단계 자체에는 agent와 timeout이 없습니다 | Runner를 기다려 작업 폴더를 만들고 저장소를 받고 `scripts/run_gather.sh`로 수집한 뒤 결과를 보존합니다 | 결과는 다음 단계가 보냅니다. 빌드 중단은 그대로 전파됩니다 |
| 결과 확인 및 전송 (`post { always }`) | Controller의 built-in 노드 (노드를 얻은 뒤 1시간 한계) | 결과를 회수해 접수 수와 맞추고 Portal에 POST한 뒤 요약과 본문을 보관합니다 | 전송 실패는 UNSTABLE, 결과 처리 노드를 끝내 얻지 못하면 FAILURE |

### 입력 확인

- `target_type`, `inventory_json`, `callbackUrl`, `deploymentEnvironmentId`를 검증합니다.
- `inventory_json`은 표준 JSON만 받습니다. 홑따옴표, 따옴표 없는 키, 끝 쉼표, 값 뒤의 주석은 거부합니다. `inventory.sh`의 규칙(JSON 배열, 원소는 객체, `service_ip`/`bmc_ip`/`ip` 중 첫 값, 문자열, ASCII IPv4, 중복 금지)으로 검사하고 하나라도 어긋나면 요청 전체를 거부합니다.
- `callbackUrl`은 `http://` 또는 `https://`로 시작해야 하고 따옴표, 백틱, 역슬래시, 공백, 계정 정보, `?`, `#`를 넣을 수 없습니다. 전송 주소는 이 값 뒤에 `/api/jenkins/gather/<target_type>`을 붙여 만듭니다.
- 접수 목록을 `env.SE_MANIFEST_JSON`에 두고 빌드 이름을 `#N <종류> N대`로 바꿉니다.

### 실행 위치 확인

- `common/vars/locations.yml`의 `agent_label`과 `target_type`의 능력 라벨을 `&&`로 이어 라벨식을 만듭니다. `os`는 `linux && windows`, `esxi`는 `esxi`, `redfish`는 `redfish`입니다.
- 그 라벨식을 가진 등록된 Runner 수를 셉니다. 0이면 설정 오류로 끝내고, 등록돼 있으면 지금 연결이 끊겨 있거나 바빠도 수집 단계가 기다립니다.

### 서버 정보 수집

시도를 반복하는 구조입니다. 시도마다 Runner를 Jenkins 큐로 기다리고(executor를 잡지 않습니다), 작업 폴더 `<Job 이름>-<빌드 번호>`를 씁니다.

1. 첫 시도는 저장소를 받고 소유 기록(`.se_workspace.json`, 받은 commit 포함)과 접수 목록 파일(`gather_manifest.json`), 접수 입력 파일(`.inventory_input.json`)을 만듭니다. 이어서 하는 시도는 저장소를 다시 받지 않고 revision을 대조합니다.
2. 전역 환경변수 `ADDON_REPO_URL`이 있으면 Add-on을 받고 검사합니다(3절).
3. `scripts/run_gather.sh`가 작업 폴더 잠금, 환경 경계(`scripts/env_guard.sh`), venv 선택(`scripts/activate_ansible_venv.sh`), 실행 기록 준비(`scripts/gather_state.py begin`: 남은 대상, 이번 한계, 동시 실행 수), vault 비밀번호 임시 파일을 준비한 뒤 `timeout --signal=INT --kill-after=90 <이번 한계> ansible-playbook ... --limit @<남은 대상 파일>`로 수집합니다. 실행 중 60초마다 생존 표시를 남기고 5분마다 진행 줄을 출력합니다. 끝나면 이 실행의 SSH 다중화 연결을 닫고 끝 기록(`gather_state.py end`)을 남깁니다.
4. `gather_state.py classify`로 이번 시도를 판정합니다. 끝(`completed`, `gather_limit`, `prep_failed`, `failed_run`, `process_lost`, `aborted`)이면 마지막 보존을 합니다. 실행 기반 장애(Runner 연결 끊김, 근거 있는 OOM, 재부팅)면 지금까지의 원본 결과만 넘겨 두고 같은 Runner를 기다려 다시 시도합니다.
5. 마지막 보존은 결과 정리(`scripts/finalize_gather_output.py`), 오래된 작업 폴더 정리(`scripts/workspace_cleanup.py`, 하루 한 번), 빌드 보관(`archiveArtifacts`, 있는 파일만, 빈 보관은 실패), 전달(`stash`, 전달할 파일이 없으면 하지 않음), 보관을 확인했을 때만 작업 폴더 삭제 순서입니다.

### 결과 확인 및 전송

`post { always }` 안의 표시 단계입니다. built-in 노드를 실행 기반 대기 합 안에서 기다리고(취소된 빌드는 5분까지만), 노드를 얻은 뒤 1시간 안에서 빌드별 폴더 `fin-<빌드 번호>`에서 처리합니다.

1. 회수: 전달본(stash)과 빌드 보관본(archive)을 각각 격리 폴더(`rec-<진입>/stash`, `rec-<진입>/archive`)에 받습니다. 마지막 보존의 전달 표식(`SE_FINAL_STASHED`)이 있고 그 정리 결과가 접수 대상마다 한 줄이면 전달본을 쓰고, 그 밖에는 보관본도 파일별로 받아 두 후보를 같은 검문으로 평가해 결과가 있는 대상이 많은 쪽을 고릅니다. 고른 근거는 `finalize_summary.json`의 `recovery`에 남습니다.
2. 조립: 정리 결과(`gather_final.jsonl`)가 있으면 그것을, 없으면 `scripts/jenkins/se_finalize.groovy`를 `readTrusted`로 읽어 OUTPUT 줄, CHECKPOINT 줄, 합성 실패 봉투 순으로 접수 수만큼 맞춥니다. 전송 직전에 봉투 형태를 검문합니다.
3. 전송: `{loc, deploymentEnvironmentId, eventUuid, gatherInfoJson:[...]}`를 POST합니다(5절).
4. 보관: `callback_body.json`, `finalize_summary.json`, 고른 입력의 `gather_final.jsonl`을 빌드에 보관하고 `[결과 파일]` 링크를 콘솔에 적습니다. 보관을 확인하면 폴더를 지웁니다.

## 2. 파라미터와 환경변수

파라미터 7개는 [03-job-registration.md](03-job-registration.md) 5절에 있습니다. 시험용 파라미터는 없습니다.

파이프라인이 수집 실행에 주는 환경변수입니다.

| 변수 | 값 | 뜻 |
|---|---|---|
| `REPO_ROOT` | `${WORKSPACE}` | 어댑터와 vault 로딩 기준 경로 |
| `ANSIBLE_CONFIG` | `${WORKSPACE}/ansible.cfg` | 프로젝트 Ansible 설정 |
| `INVENTORY_JSON_FILE` | `${WORKSPACE}/.inventory_input.json` | 접수 입력 원본 파일. `inventory.sh`가 환경변수보다 먼저 읽습니다. 환경변수로 넘기지 않는 이유는 Linux의 환경변수 하나 한도(131,072바이트)입니다 |
| `ANSIBLE_JSON_OUTPUT_FILE` | `${WORKSPACE}/gather_output.json` | `json_only` 콜백이 결과 봉투를 한 줄씩 씁니다 |
| `ANSIBLE_JSON_MANIFEST_FILE` | `${WORKSPACE}/gather_manifest.json` | 접수 목록. 콜백이 inventory와 대조합니다 |
| `ANSIBLE_JSON_PROGRESS_FILE` | `${WORKSPACE}/gather_progress.jsonl` | 서버별 진행 이벤트. 결과 정리가 빠진 봉투를 채울 때 읽습니다 |
| `ANSIBLE_JSON_CHECKPOINT_FILE` | `${WORKSPACE}/gather_checkpoint.jsonl` | Add-on 직전 조립본 |
| `SE_AUTH_EVIDENCE_DIR`, `SE_BUILD_ID`, `SE_EVENT_UUID` | `${WORKSPACE}/gather_auth_evidence`, `${BUILD_TAG}`, `eventUuid` | Redfish 인증 증거 파일(비밀값 없음) |
| `ANSIBLE_VERBOSITY` | `verbosity` 파라미터 | |
| `ADDON_DIR` | `${WORKSPACE}/addon` | Add-on을 켜고 검사를 통과한 빌드의 ansible 실행에만 |
| `ANSIBLE_SSH_CONTROL_PATH_DIR` | `/tmp/se_cp.XXXXXX` | 이 실행의 SSH 다중화 위치. 끝나면 그 연결만 닫고 지웁니다 |
| `ANSIBLE_INVENTORY_UNPARSED_FAILED` | `True` | inventory 스크립트가 요청을 거부하면 빈 inventory로 성공하지 않고 실행 실패로 끝냅니다 |

환경 경계(`scripts/env_guard.sh`)는 상위 환경에서 넘어온 시험용 값(`SE_FORCE_LINUX_RAW_FALLBACK`, `JSON_ONLY_NO_RECONCILE`, `ANSIBLE_JSON_OUTPUT_TASK`, `ANSIBLE_JSON_CHECKPOINT_TASK`, `ANSIBLE_STDOUT_CALLBACK`, `SE_VENDOR_ALIASES_PATH`, 검사 통과 전의 `ADDON_DIR`)을 지우고 콘솔에 이름만 남깁니다.

## 3. Add-on

전역 환경변수 네 개(`ADDON_REPO_URL`, `ADDON_REPO_REF`, `ADDON_REPO_CREDENTIALS_ID`, `ADDON_REPO_SSL_VERIFY`)의 뜻은 [03-job-registration.md](03-job-registration.md) 4절에 있습니다. `ADDON_REPO_URL`이 있으면 수집 단계가 빌드마다 다음을 합니다.

1. Add-on 저장소의 `ADDON_REPO_REF`(기본 `main`)를 `${WORKSPACE}/addon`에 받습니다(두 번까지 시도, git 명령마다 30분 한계). 콘솔 `[addon] <URL>@<ref> <커밋>`.
2. 받은 파일을 검사합니다. 콘솔 `[addon] 검사 통과: linux, windows` 또는 `[addon] 검사 실패: <파일>: <이유>`.
3. 통과하면 그 빌드의 수집에 Add-on을 넣습니다. ESXi와 Redfish 빌드는 Add-on이 할 일이 없어 켜지 않습니다(`[addon] 실행할 기능 없음`).
4. 받지 못하거나 검사에 실패하면 `[addon] unavailable: <사유>`를 남기고 UNSTABLE로 표시한 뒤 Add-on 없이 수집합니다. 서버별 결과에는 Add-on 오류가 붙지 않습니다.

결정(사용 여부, 받은 commit, 문제)은 작업 폴더의 `.se_addon.json`에 남고, 실행 기반 장애 뒤 이어서 하는 시도는 다시 받지 않고 그 결정을 씁니다. hook 계약은 [../develop/07-addon-hook.md](../develop/07-addon-hook.md)에 있습니다.

## 4. 시간 한계

기다린 시간과 실행한 시간을 따로 셉니다. 빌드 전체와 수집 단계에는 timeout이 없습니다. 정본 값은 `Jenkinsfile_portal`의 `seConstants()`와 `scripts/gather_state.py`입니다.

| 한계 | 값 | 어디서 | 넘었을 때 |
|---|---|---|---|
| 입력 확인, 실행 위치 확인 | 각 5분 | stage `options.timeout` | FAILURE |
| 실행 기반 대기 | 빌드 하나의 합 72시간 | `seWithNode`. Runner 배정, 장애 뒤 재대기, 결과 처리 노드 대기, 장애 반복 시 쉬는 시간을 모두 더합니다 | 큐 요청을 거두고 outcome `infra_wait_expired`. 끝난 대상은 그대로, 끝나지 않은 대상은 실행 기반 사유의 실패 결과 |
| 수집 실행 한계 | 누적 6시간. 이번 시도의 한계는 6시간에서 앞 시도의 실제 수집 시간을 뺀 값 | `gather_state.py begin`과 `run_gather.sh`의 `timeout --signal=INT --kill-after=90` | INT로 멈추고 90초 뒤 KILL. outcome `timeout` 또는 `timeout_killed`. 끝난 대상의 결과는 보존하고 끝나지 않은 대상만 실패 결과 |
| 시도 하나의 실행 한계 | 6시간 + 90초 + 2시간 | 작업 폴더를 얻은 뒤의 `timeout`. 멈춘 step이 빌드를 붙잡지 않게 하는 안전망 | outcome `attempt_limit`. Runner가 연결돼 있으면 확보한 결과를 보존해 보냅니다 (6절) |
| 결과 확인 및 전송 | 결과 처리에 실제로 쓴 시간의 합 1시간 | built-in 노드를 얻은 뒤의 `timeout` | 보내지 못했으면 FAILURE, 보냈지만 마무리만 못 했으면 UNSTABLE |
| Portal 응답 대기 | 시도마다 최대 10분, 최대 3번(취소된 빌드는 1번), 사이 대기 10초와 20초 | `seCallback` | 다음 시도 또는 실패 기록 |
| SSH 연결 | 60초, 연결 유지 확인 10초 × 3 | `os-gather/site.yml` | 그 서버의 연결 실패 |
| OS 후보 포트 연결 | 포트마다 10초 | `common/library/precheck_bundle.py` | 다음 후보 포트 |
| OS 프로토콜 확인 응답 | 60초 | `precheck_bundle.py` | 그 포트 실격 |
| ESXi와 Redfish 사전 진단 | 포트 60초, 프로토콜 응답 30분 | `run_precheck.yml` | 진단 단계 `port` 또는 `protocol` |
| Redfish 요청 | 연결 60초, 응답 대기 30분 | `redfish_gather.py` | 그 요청의 실패 |
| ESXi 응답 | 30분 | `esxi_disks.py` | 그 구성요소의 실패 |
| Add-on 받기 | git 명령마다 30분, 2번까지 | `scripts/addon_checkout.sh` | UNSTABLE, Add-on 없이 수집 |

실제 수집 시간은 Runner 시계로 잰 `ansible-playbook` 실행 시간의 합입니다. 끝 기록이 있으면 그 값, 없으면 마지막 생존 표시(60초마다) + 60초, 재부팅이면 새 부팅 시각까지입니다.

콘솔에는 시도마다 기계용 한 줄 `[기술 기록] 수집 시도 n=... node=... rc=... state=... new_record=... exec_used=... completed=.../...`과 사람이 읽는 `[수집]` 줄이 남습니다.

```text
[2026-10-12 10:00:05 +09:00] [수집] OS 서버 3대의 정보 수집을 시작합니다.
  Runner: <Runner 이름>
  동시 수집: 3대
[2026-10-12 10:00:30 +09:00] [수집] 수집 실행을 마쳤습니다. 소요 시간 25초.
```

## 5. 결과 전달

- 수집 단계의 `gather_output.json`은 서버마다 봉투 한 줄(JSON Lines)입니다. 결과 정리 스크립트가 `gather_final.jsonl`을 만듭니다. OUTPUT 줄이 없는 서버는 CHECKPOINT 줄(Add-on 직전 조립본)로, 그래도 없으면 진행 기록으로 실패 봉투를 합성합니다. 요청한 대상 하나마다 결과 하나입니다.
- 전송은 남은 시간 안에서 최대 3번입니다. HTTP 2xx를 받으면 Portal이 요청을 받은 것이고 전달은 끝입니다. Portal의 저장과 반영 확인은 이 Job의 역할이 아니며 응답 본문은 읽지 않습니다.
- 5xx, 408, 429, 연결 실패는 다시 보냅니다. 그 밖의 4xx는 Portal의 확정 거부로 보고 다시 보내지 않습니다.
- 요청 도구(HTTP Request 플러그인)가 주소를 해석하지 못해 만든 합성 404는 Portal의 거부가 아닙니다. 본문이 도구의 고정 문구이고 서버 헤더가 없는 경우만 그렇게 보고, 콘솔에 `Portal 주소를 해석하지 못했습니다(이름 풀이 실패).`를 적고 남은 횟수 안에서 다시 보냅니다. 실제 서버가 돌려준 404는 거부로 처리합니다.
- 모두 실패하면 UNSTABLE이고 본문은 `callback_body.json`에 남습니다. 수집 자체가 성공했으면 FAILURE로 만들지 않습니다.
- 결과 확인 중 실행 기반 오류로 끊기면 같은 빌드 안에서 built-in 노드를 다시 기다려 같은 폴더에서 다시 처리합니다. 2xx를 받은 전송과 확정 거부된 전송은 다시 보내지 않습니다.
- 파이프라인이 시작되기 전의 실패(Controller가 저장소에서 `Jenkinsfile_portal`을 읽지 못함)는 결과를 보내지 못합니다. 콘솔이 `hudson.plugins.git.GitException`으로 시작하고 stage가 없는 빌드입니다. 다시 보낼지는 호출 측이 정합니다.

콘솔에서 바로 읽는 줄은 `[Portal 전송]`(시도별 시작, 결과), `[결과]`(보낸 결과의 status 집계), `[수집 종료]`(정상 종료가 아닐 때 원인, 수집 시간, 확정 대상, 마치지 못한 대상, 결과 보존), `[경고]`, `[결과 파일]`, `[요약]`입니다. 기술 값은 `[기술 기록]` 줄과 `finalize_summary.json`에 있습니다.

`finalize_summary.json`의 주요 키: `accepted`, `lines`, `kept`, `filled`, `outcome`, `limit_reason`, `status_counts`, `warnings[]`, `callback{attempted, delivered, http_code, attempts, reason, receipt, tries[]}`, `times{...}`, `limits{...}`, `gather_run`(수집 시도 기록, 대상 IP 목록 제외), `infra{budget_sec, used_sec, expired, episodes[]}`, `finalize{entries, lost[]}`, `recovery`.

## 6. 실행 기반 장애와 같은 Runner 재개

실행 기반 장애는 근거가 있을 때만 그렇게 봅니다.

| 관측 | 판정 | 그다음 |
|---|---|---|
| Runner가 연결돼 있지 않거나 executor가 모두 사용 중 | 대기 | executor를 잡지 않고 Jenkins 큐로 기다립니다 |
| 실행 중 Runner 연결 끊김. Jenkins가 끊긴 Agent를 5분 기다린 뒤 step을 끝냅니다. `retry`의 `agent()`와 `nonresumable()` 조건이 판단합니다 | `agent_disconnect` | 같은 Runner를 기다립니다. Runner 쪽 수집이 계속 돌았으면 끝나기를 기다린 뒤 남은 대상만 수집합니다 |
| 바깥에서 끝남 + 커널 로그의 OOM 종료 기록 PID가 이 실행의 것 | `runner_oom` | 원본을 넘겨 두고 같은 Runner로 다시 시도 |
| Runner의 부팅 기록(boot_id)이 바뀜 | `runner_restart` | 같은 Runner로 다시 시도 |
| 근거 없이 끝 기록 없이 사라짐 | `process_lost` (원인 미확인) | 다시 시도하지 않습니다. 끝난 결과만 보내고 나머지는 실패 결과 |
| 대상 측 일시 장애 (SSH, WinRM, vSphere, Redfish 응답 없음, 401, 5xx) | 실행 기반 장애 아님 | 채널의 기존 timeout과 retry 안에서 처리하고 그 대상의 결과로 끝냅니다 |

빌드 중단과 시도 한계의 구분은 Jenkins가 중단 예외에 실어 보내는 분류로만 합니다. 경과 시간이나 Runner 연결 상태로 원인을 정하지 않습니다.

- 시도 하나의 실행 한계로 끊긴 것으로 Jenkins가 분류하면(`attempt_limit`) Runner가 연결돼 있을 때 확보한 결과를 한 번 보존해 보냅니다. Runner가 연결돼 있지 않으면 원본 예외를 그대로 Jenkins의 재시도 판정에 넘깁니다.
- Jenkins가 실제 중단(사용자 취소 등)으로 분류하면 원인을 적지 않고 outcome `aborted`로 결과를 보존한 뒤 그대로 전파합니다. 보존은 하지만 작업 폴더는 지우지 않고 오래된 작업 폴더 정리에 맡깁니다. 취소된 빌드는 Portal에 1번만 보냅니다.
- 보존 책임은 한 곳입니다. 같은 빌드에서 보존을 두 번 하거나 빈 전달본이 앞의 전달본을 덮지 않습니다.
- 이어서 하는 시도에서 수집 셸이 실행 기록을 남기기 전에 끝나면(venv 없음 90, 실행 기록 준비 실패 91, inventory 권한 93, 임시 파일 94, 잠금 파일 95) 앞 시도의 상태를 쓰지 않고 `prep_failed`로 끝냅니다. 그 밖의 종료 코드는 `failed_run`입니다. 원인 문장은 수집 셸이 콘솔에 적습니다.
- 끝난 대상은 다시 수집하지 않습니다. 결과 줄이 있는 대상과 사전 진단에서 실패로 확정된 대상은 빠지고, 실행 중이던 대상만 다시 수집합니다. 확정됐던 대상의 결과 줄이 작업 폴더에서 사라졌으면 다시 수집하지 않고 `resume_impossible`로 끝냅니다.
- 마지막 보존이 보관 또는 전달 중 하나라도 마친 뒤 끊기면 다시 시도하지 않습니다. 그 전에 끊기면 같은 Runner의 같은 작업 폴더에서 보존만 다시 합니다.
- 진척 없이 장애가 반복되면 5분부터 두 배씩(최대 1시간) executor를 잡지 않고 쉽니다.
- 수집을 시작한 뒤에는 그 Runner로만 다시 시도합니다. Runner가 등록 해제되거나 소유 기록이 없거나 받은 commit이 다르면 `resume_impossible`로 끝냅니다. 다른 Runner로 옮기지 않고 새 저장소를 쓰지 않습니다.
- Runner가 끝내 돌아오지 않으면 그 Runner에만 있던 결과는 보낼 수 없습니다. 그 대상은 실행 기반 사유의 실패 결과가 됩니다.

운영자가 볼 것은 빌드 설명(`실행 대기: <사유> (<대상>), 경과 ..., 남은 대기시간 ...`), 콘솔의 `[실행 대기]`와 `[수집]` 줄, 빌드 끝 `[요약]`의 소요 시간(수집과 실행 대기), `finalize_summary.json`의 `infra.episodes`입니다.

## 7. 원격 명령 정리

Linux 수집 명령은 raw로 터미널과 함께 실행됩니다. 실행 한계의 INT는 ansible 주 프로세스에만 가므로, `scripts/run_gather.sh`는 실행마다 자기 SSH 다중화 위치(`/tmp/se_cp.*`)를 쓰고, ansible이 어떻게 끝났든 그 위치의 연결에 종료(`ssh -O exit`)를 보낸 뒤 그 위치를 명령줄에 가진 ssh 프로세스만 끝냅니다. 이름으로 일반 프로세스를 끝내지 않고 대상 서버에서 프로세스를 찾아 죽이지 않습니다. 디스크 대기(D 상태) 프로세스와 네트워크가 갑자기 끊겨 대상 sshd가 모르는 연결은 대상 쪽 설정이 정리할 때까지 남을 수 있습니다. Windows(WinRM)는 셸 종료로 정리됩니다.

## 8. 시각 기록

- Timestamper 플러그인이 있으면 각 단계를 `timestamps {}`로 감싸 콘솔 줄마다 시각이 붙습니다. 없으면 감싸지 않고 그대로 진행합니다.
- 업무 사건 줄은 플러그인과 무관하게 본문에 날짜, 시각, 시간대를 적습니다. 그 줄을 쓴 노드의 시계입니다.
- 기록 파일의 시각은 UTC ISO 8601입니다(`finalize_summary.json`의 `times`와 `callback.tries[]`, `gather_run.json`).

## 9. 실행 기록 보관과 작업 폴더 정리

| 대상 | 기간 | 어디서 |
|---|---|---|
| 빌드 기록, 콘솔 로그, 결과 파일(artifact) | Jenkins 전역 보관 정책 | `Jenkinsfile_portal`은 Job별 보관 설정을 두지 않습니다. Manage Jenkins → System의 Global Build Discarders로 관리합니다 |
| Runner 작업 폴더 | 보관을 확인하면 그 빌드가 바로 지웁니다. 남은 폴더는 끝난 지 7일 뒤 하루 한 번 정리 | `scripts/workspace_cleanup.py` ([02-agent-node.md](02-agent-node.md) 9절) |
| Controller 결과 확인 폴더 `fin-<빌드 번호>` | 보관을 확인하면 지웁니다. 남은 폴더는 7일 뒤 하루 한 번 정리. 보관하지 못한 폴더는 지우지 않고 알립니다 | `seCleanOldFinalizerDirs` |

## 10. 장애 확인 방법

| 알고 싶은 것 | 보는 곳 |
|---|---|
| 어느 단계에서 멈췄나 | Stage View와 콘솔의 `[입력 확인]`, `[실행 위치]`, `[수집]`, `[결과 확인]`, `[Portal 전송]` 줄 |
| 수집이 왜 끝났나 | `[수집 종료]` 블록, `finalize_summary.json`의 `outcome`, `limit_reason`, `gather_run.attempts[].state` |
| Runner를 얼마나 기다렸나 | `[실행 대기]` 줄, `[요약]`의 실행 대기 시간, `finalize_summary.json`의 `infra` |
| Portal에 보냈나 | `[Portal 전송]` 줄, `finalize_summary.json`의 `callback.receipt` (`delivered`, `uncertain`, `not_delivered`, `not_attempted`) |
| 서버별 실패 이유 | `gather_final.jsonl`의 `diagnosis.failure_reason`과 `errors[]` ([../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md)) |
| 결과 파일이 어디 남았나 | `[결과 파일]` 줄, `[결과 보존]` 줄의 작업 폴더 위치, Controller의 `fin-<빌드 번호>` |
| 기술 값 | `[기술 기록]` 줄, `finalize_summary.json`, `gather_run.json` |

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| Job 등록과 첫 실행 | [03-job-registration.md](03-job-registration.md) |
| 업데이트와 되돌리기 | [07-update-and-rollback.md](07-update-and-rollback.md) |
| 결과 봉투와 실패 진단 | [../contract/02-output-envelope.md](../contract/02-output-envelope.md), [../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md) |
