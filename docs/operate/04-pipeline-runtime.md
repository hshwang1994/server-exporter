# Jenkins 파이프라인 런타임

> 이 문서는 server-exporter 의 운영 파이프라인 `Jenkinsfile_portal` 이 실제로 어떤 단계로 실행되는지 정리한다.
> 각 단계가 어느 노드에서 도는지, 어디서 실패하면 어떻게 전파되는지, 호출자에게 어떤 형식으로 결과가 돌아가는지를 한 페이지에 모았다.
>
> Jenkinsfile 을 수정해야 한다면 본 문서의 단계 구조와 게이트 정책을 먼저 이해한 뒤 손댄다.

> 검증일: 2026-10-05 (사내 Jenkins main X13 `1e15bf6f` → production P4 `5ac5566c` — 단계 표시 이름 · 시간 제한 · 결과 전달 계약 · 입력 규칙 · 동시 실행 측정 갱신)

## 1. 파이프라인 구조

`Jenkinsfile_portal` 은 최상위 `agent none` 이고 단계마다 노드를 고른다. 컨트롤러(`built-in`)에는 Python 도 Ansible 도 필요 없다.

```text
parameters (loc, target_type, inventory_json, deploymentEnvironmentId, eventUuid, callbackUrl, verbosity
            + 시험 전용 redfishAccountDryrun, gatherBudgetForceSec — 기본값이면 운영 동작 불변, 값을 주면 빌드 이름에 [시험: …])
  → 입력 확인 (Validate)             [agent 없음]  대상 목록을 inventory.sh 와 같은 규칙(ASCII IPv4 · 앞뒤 공백 · 중복 · 원소 타입)으로 검사,
                                                  계정 정보가 든 callbackUrl 거부 → 접수 manifest(env SE_MANIFEST_JSON) · 빌드 이름 `#N <종류> N대`
  → 실행 위치 확인 (Resolve Location) [agent 없음]  readTrusted 로 common/vars/locations.yml 하나만 읽어 loc 검증 → 노드 라벨식
                                                  (맞는 온라인 노드가 없으면 수집을 건너뛰고 실패 결과로 보충 — UNSTABLE)
  → 서버 정보 수집 (Gather)           [Agent]     manifest 기록 → (전역 ADDON_REPO_URL 이 있으면 Add-on 체크아웃 · 검사)
                                                  → 시간 계산(scripts/gather_budget.sh — ansible 직전 재계산: 예상 시간 · 중단 기준) → 환경 경계(scripts/env_guard.sh)
                                                  → 정체 감시(scripts/gather_watch.py) + timeout --signal=INT --kill-after=90 <중단 기준> ansible-playbook … -f <forks>
                                                  → rc → outcome(completed / timeout / timeout_killed / prep_failed / not_started_* / failed_run) · limit_reason
                                                  post{always}: 결과 정리 Layer A(접수 = 결과 보충) → archiveArtifacts → stash → (manifest 가 이 빌드 것일 때만) deleteDir
  pipeline post{always} → 표시 단계 '결과 확인 및 전송' [컨트롤러, 합산 720 s]
        unstash(없으면 unarchive) → Layer A 결과 또는 Groovy 최소 보충(scripts/jenkins/se_finalize.groovy 를 readTrusted→load)
        → Portal 로 POST(남은 예산 안 ≤3회, HTTP 2xx 수신 = 전달 완료) → callback_body.json · finalize_summary.json 보존 → [결과 파일] 링크 → [요약]
```

> 2026-10-03: Validate 와 Resolve Location 은 더 이상 노드를 잡지 않는다. 종전에는 Resolve Location 이 컨트롤러에서
> 저장소 **전체**를 체크아웃한 뒤 YAML 1개를 읽었고, `main`(약 17k 파일)은 2분 제한을 넘겨 끊겼다. `readTrusted` 는
> Job 의 SCM 설정(Lightweight checkout)으로 파일 하나만 읽는다.
>
> 2026-10-03 (Phase 4): `Validate Schema` 와 `Callback` stage 는 없어졌다. field_dictionary 정합은 커밋 전 `scripts/ai/ci_gate.sh`
> (pre-commit · CI) 가 맡고, 결과 전달은 **파이프라인 `post { always }`** 의 마무리 단계가 맡는다 — stage 가 어디서 끊겨도(agent 대기
> 초과 · ansible 강제 종료 · 1회 Abort) 실행 **경로**가 있다. 요청한 대상 1개마다 결과 1개를 보낸다: 완료된 host 는 OUTPUT 그대로,
> Add-on 도중 끊긴 host 는 `CHECKPOINT`(조립 직후 보존본), 그 밖은 진행 기록(`gather_progress.jsonl`)에 따라 실패 봉투로 채운다 (8절).

| 단계 (Stage View 표시 이름) | 노드 | 하는 일 | 실패 시 |
|-------|------|--------|--------|
| 입력 확인 (Validate) | 없음 | `target_type` · `inventory_json`(JSON 배열 · 원소 객체 · `service_ip`/`bmc_ip`/`ip` 중 처음 값 · 문자열 · ASCII IPv4 · 중복 금지 — `inventory.sh` 와 같은 규칙, 위반이 하나라도 있으면 요청 전체 거부) · `callbackUrl`(`http(s)://`, 계정 정보 `사용자:비밀번호@` 금지 — 이 오류는 주소를 출력하지 않는다) · `deploymentEnvironmentId` 검증 → 접수 manifest 를 `env.SE_MANIFEST_JSON` 으로, 빌드 이름 `#N <종류> N대` | FAILURE — 접수 manifest 가 없어 보낼 것이 없다 |
| 실행 위치 확인 (Resolve Location) | 없음 | `readYaml text: readTrusted('common/vars/locations.yml')` — 미등록 `loc` 는 노드 대기 없이 즉시 실패. 라벨식을 모두 가진 온라인 노드가 없으면 수집을 건너뛴다 | 미등록 loc: FAILURE · 온라인 노드 없음: UNSTABLE + outcome `no_agent`(접수 대상마다 실패 결과 전송) |
| 서버 정보 수집 (Gather) | `agent_label && 능력 라벨` 노드 (stage 합산 상한 115분 — agent 대기 포함) | `gather_manifest.json` 기록 → (전역 `ADDON_REPO_URL` 이 있으면 Add-on 저장소를 `${WORKSPACE}/addon` 에 받고 검사 — 3절) → **시간 계산**(`scripts/gather_budget.sh`, 아래 "시간 제한") → 환경 경계(`scripts/env_guard.sh`: 상위 환경의 시험용 · 재정의 값을 지우고 이름만 기록) → venv 활성화 → 정체 감시를 옆에 띄우고 `timeout --signal=INT --kill-after=90 <중단 기준> ansible-playbook <채널>/site.yml -i <채널>/inventory.sh -f <forks> --vault-password-file=<임시파일> -e se_location=<loc>` (`redfishAccountDryrun` 이 켜진 빌드만 `-e _rf_account_service_dryrun=true`; inventory 해석 실패는 실행 실패 — `ANSIBLE_INVENTORY_UNPARSED_FAILED=True`) → rc 를 `gather_rc.txt` 에, outcome · limit_reason 을 기록 → post{always}: 결과 정리 Layer A(`scripts/finalize_gather_output.py`) → `archiveArtifacts` → `stash` → manifest 가 이 빌드의 것일 때만 `deleteDir` | Add-on 을 받지 못하면 UNSTABLE + Add-on 없이 수집; ansible 이 비정상 종료(rc 124/137 시간 제한, 그 밖)여도 stage 는 끊지 않고 outcome 만 남긴다 — 결과 전달은 다음 단계가 한다 |
| 결과 확인 및 전송 (post 안의 표시 단계) | `built-in` — `timeout(720 s) { node('built-in') }` 합산 제한 | `unstash` → 없으면 `unarchive` → `gather_final.jsonl`(Layer A, exit 0/2) 우선, 없으면 Groovy 최소 경로(OUTPUT → CHECKPOINT+오류 1건 → 합성 실패 봉투) → 전송 직전 형태 검문 → `{loc, deploymentEnvironmentId, eventUuid, gatherInfoJson:[…]}` POST(남은 시간 안 ≤3회, 시도별 10~120 s, 결정적 4xx(408/429 제외)는 즉시 중단, ABORTED 면 1회) → `[결과]` 집계 · `[경고]` · `callback_body.json` · `finalize_summary.json` 보존 · `[결과 파일]` 링크 | 전송 실패 · 본문 상한 초과 · 합성 보충 · outcome ≠ completed · 보충 라이브러리 없음 · 결과 수 ≠ 접수 수 → UNSTABLE 한 번(사유는 `[경고]` 줄). 접수 manifest 조차 없으면(입력 확인 실패) 보낼 것이 없다 |

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

### 시간 제한 (2026-10-05 — 예상 시간과 중단 기준을 나눴다)

종전(2026-10-03)에는 공식이 낸 **예상 시간**이 그대로 `timeout` 값이었다 — 예상이 빗나가면 정상으로 진행 중인 수집도 잘렸다
(예: Redfish 복구 경로 최악 약 2,595 s · OS 태스크 합 1,200~2,200 s 가 host 예상 240 s 를 넘는다). 지금은 **중단 기준 = 운영 상한**이고,
예상 시간은 표시와 정체 감시의 기준점으로만 쓴다(F12). 숫자 상향은 없다 — 외곽 115 분 · 150 분은 그대로다.

| 단계 | 값 | 근거 | 넘었을 때 |
|---|---|---|---|
| 빌드 전체 | 150 분 (빌드 시작 기준, `options.timeout`) | 입력 확인 · 실행 위치 ≤ 4 분 + 서버 정보 수집 ≤ 115 분 + 마무리 12 분 + 여유 | Jenkins 가 ABORTED 로 끝낸다. 결과 전송은 남은 시간 안에서 시도 |
| 입력 확인 · 실행 위치 확인 | 각 2 분 | 파라미터 검사 · 파일 1개 읽기 | FAILURE |
| 서버 정보 수집 단계 합산 | 115 분 (agent 대기 · checkout · Add-on 준비 · 수집 · post 보존 포함) | 대기 300 + checkout 600 + Add-on 300 + 수집 상한 5,400 + 300 | 단계 timeout → outcome `aborted`, 결과 전송은 이어서 시도 |
| 마무리 예비 | 990 s = INT→KILL 유예 90 + Layer A 120 + archive · stash 60 + 결과 확인 및 전송 720 | 수집이 끝난 뒤 전송 종료까지의 실제 경로 합 | 중단 기준에서 미리 빼 둔다 |
| **중단 기준** (`budget`) | `min(빌드 남은 시간 − 마무리 예비, 단계 남은 시간 − 유예 90 − post 180)` — ansible 직전에 다시 계산 | 운영 상한. 예상 시간과 무관(`limit_source=ceiling`) | `timeout` 이 INT, 90 s 뒤에도 남으면 KILL → outcome `timeout`/`timeout_killed`, `limit_reason=ceiling` |
| 예상 시간 (`expected`) | `clamp(300 + host_cap × waves, 600, 5400)` — host_cap: os · esxi 240 s, redfish 후보 수 × 605 s(+복구 240) | 2026-09-03 실측 host 최대 78 s × 3 등 경험값. 표시용 | 넘어도 멈추지 않는다 — 아래 정체 감시가 시작되는 시점일 뿐 |
| **정체 감시** (`scripts/gather_watch.py`) | 예상 시간이 지난 뒤 **모든 대상에서** 진행이 420 s 동안 없을 때만 `timeout` 프로세스에 INT | 420 = 가장 긴 단일 태스크 상한(Add-on 300) + 120. 진행 = host 의 작업 태스크 완료(`alive`, 10 s 마다 최대 1회) · Redfish 새 응답(heartbeat, 5 s 마다 최대 1회) · checkpoint · 결과 출력. 재시도 · 실패 · 같은 페이지 재요청 · 프로세스 생존은 진행이 아니다 | outcome `timeout`, `limit_reason=stalled`, `gather_watch.json` 보존, 콘솔 `[수집] 진행이 없어 정체 감시가 …` |
| 최소 시작 | 120 s | 그보다 적게 남으면 의미 있는 수집이 안 된다 | 시작하지 않는다(`not_started_budget`) — 접수 대상은 실패 결과로 |
| 메모리 보호 | forks ≤ `floor((MemAvailable × 40 % − 200) / 80)` | 2026-10-04 Runner 실측: slot 최악 69 MB · 메인 python 86 MB (`per_fork_mb` 80 · `fixed_mb` 200) | forks 를 줄인다. 1 도 안 되면 시작 안 함(`not_started_memory`) |
| 태스크 상한 (host 안) | Linux 120 s · Windows 180 s · ESXi 180 s · Add-on 300 s · Redfish 탐지 120 s(모듈 90) · Redfish 수집 1,260 s(모듈 절대 1,200 + 새 응답 없음 120) · Redfish 계정 240 s(모듈 180) | 실측 host 전체 시간 — Linux 42~59 s(Add-on 포함) · Windows 70~97 s · ESXi 33~35 s · Redfish Dell 40~53 s · Lenovo 66 s · Cisco 341~367 s — 의 3 배 이상 | 그 태스크만 끊고 섹션을 실패로 기록한 뒤 다음으로. **Linux(SSH)는 끊긴 명령이 원격에 남을 수 있다**(2026-10-05 `.161` 실측 — 연결을 닫아도 남음; Windows WinRM 은 정리됨) |
| 시험용 강제 제한 | `gatherBudgetForceSec` | 시험 전용 — 빌드 이름에 `[시험: 강제 제한 N초]` | 중단 기준을 대체(남은 시간은 넘지 못함), 정체 감시는 끈다, `limit_reason=forced` |

콘솔에는 기계용 `[Budget] est …`(node 진입) · `[Budget] exec …`(ansible 직전) 두 줄과 사람이 읽는 한 줄이 남는다:
`[시간] 예상 600초 · 중단 기준 6620초 — 운영 상한(빌드 · 단계의 남은 시간) · 예상 시간이 지난 뒤 420초 동안 어떤 대상도 진행하지 않으면 중단 · 동시 2대`.
공식은 `scripts/gather_budget.sh` 가 정본이고 `tests/unit/test_gather_budget.py` · `test_gather_watch.py` 가 고정한다.
시간으로 끝난 host 의 합성 결과에는 `diagnosis.details.limit_reason` 이 붙는다(CHECKPOINT 결과는 `errors[].detail`, 실행 단위 정본은 `finalize_summary.json` 의 `limit_reason`).

### 실제 상한(선점) 과 Tier 2 (2026-10-04)

위 표의 "Layer A 120 + archive/stash 60" 과 finalizer 안의 "회수 30 · 조립 60" 은 **예산 배분(예약)** 이다. 실제로 그 구간을 **끊는** 수단은 모드에 따라 다르다.
Declarative 소스(pipeline-model-definition `ModelInterpreter`)로 확인: stage `options.timeout` 은 agent 할당과 stage `post` 를 **모두** 감싸고, pipeline `post` 는 전역 `options.timeout` 안에서 돈다.

| 구간 | 기본 모드(`SE_FINALIZER_BOUNDED` 미설정/false — 설치 기본값, 고객사 main-only 설치) | Tier 2(`SE_FINALIZER_BOUNDED=true` + 승인 4 서명 — 사내 Jenkins main · production, 2026-10-05~) |
|---|---|---|
| 입력 확인 · 실행 위치 확인 (Validate · Resolve Location) | stage timeout 2 min 각 | 같다 |
| Gather 전체(agent 대기 · checkout · 준비 · Add-on · 수집 · 유예 · post 보존) | stage timeout 115 min — post 포함 | 같다 |
| 수집(ansible) | `timeout --signal=INT --kill-after=90 <budget>`; budget 은 stage 안에 유예 90 + post 180 을 **예약**한 값 | 같다 |
| Layer A | shell `timeout 120`(step 자체 상한 없음) | 같다 |
| 보존 archive · stash | **상한 없음** — stage 합산 안(예약 60) | 각 30 s(`PRESERVE_STEP`): 넘긴 수단만 실패로 두고 다음 수단으로(archive→stash · stash→unarchive) |
| 마무리 전체 | `timeout(720){ node('built-in') }` 합산(node 대기 포함), 전역 150 min 안 | 같다 |
| 회수 unstash · unarchive | 상한 없음(예약 30 + 30) | 각 30 s(`RECOVER`) |
| 조립 — Layer A 결과 읽기·검문 → Layer B 적재(readTrusted ×3 · load · 정본 · 조립) → raw 검문 | 상한 없음(예약 60) | 60 s(`ASSEMBLE`) 하나 — 초과(자기 timeout 으로 식별된 경우만)면 최소 경로 20 s(`ASSEMBLE_MIN`): 이미 읽은 OUTPUT 줄만 검문해 전송(`layerA=timeout` · `layerB=unavailable` · `damage: assemble_timeout`); 그래도 못 끝내면 보낼 줄 없이 `unrecovered` 전부 |
| 본문 결합 · 기록 (`callback_body.json`) | 상한 없음(입력은 위에서 확정된 줄 집합뿐) | 60 s(`BODY`, 2026-10-05 F06) — 넘기면 보내지 않고 `body_timeout` 을 남긴다. 보존한 결과(`gather_final.jsonl` · `gather_output.json`)는 그대로 |
| 마지막 보존 archive (요약 · 본문) | 상한 없음 | 30 s(`PRESERVE_STEP`) — 넘기면 controller 작업공간을 지우지 않는다 |
| Callback | 시도별 `min(120, 남은 시간 − 10)`, ≤ 3회(ABORTED 1회 · 60), 대기 10/20 s, 남은 시간 < 20 이면 미시도 기록 | 같다 |
| 검산 | 720 = node 대기 120 + 회수 60 + 조립 60 + 최소 조립 20 + 본문 60 + 마지막 보존 30 → 전송에 370 남음(시도 120 × 3 + 대기 30 = 390 은 남은 시간이 자른다) · 마무리 예비 990 = 90 + 120 + 60 + 720 | |

- Tier 2 의 식별 규칙: interruption 의 `ExceededTimeout.nodeId` 가 **자기 timeout step** 의 id 와 같을 때만 "상한 초과" 로 보고 다음 단계로 간다. 외곽 timeout · 사용자 취소 · 식별 불가(승인 없음 포함)는 전부 재전파하며 ABORTED 를 SUCCESS 로 바꾸지 않는다. 원인 클래스나 경과 시간으로 판정하지 않는다.
- Tier 2 를 켜는 조건(둘 다): ① Jenkins 전역/노드/Job 환경변수 `SE_FINALIZER_BOUNDED=true` ② In-process Script Approval 에 `FlowInterruptedException getCauses` · `TimeoutStepExecution$ExceededTimeout getNodeId` · `FlowNode getEnclosingBlocks` · `FlowNode getId` 승인. 승인 없이 켜면 상한을 걸고도 식별을 못 해 재전파만 하므로(느리지만 끝날 회수까지 끊긴다) **켜지 않는다**. 기본 false 가 설치 기본값이고 고객사 main-only 설치의 요구 조건이 아니다.
- 켜고 끄는 법: Jenkins 관리 → System → Global properties → Environment variables 에 `SE_FINALIZER_BOUNDED` = `true` 를 **추가**한다(다른 전역 변수는 그대로 둔다). 끄려면 그 항목 하나를 지운다 — 다음 빌드부터 기본 모드이고 코드 변경은 없다. 승인을 회수하거나 Jenkins 를 옮기면 이 변수도 함께 지운다. 켜진 빌드는 콘솔에 `Timeout set to expire in 30 sec`(보존 archive · stash, 회수 unstash) 와 `Timeout set to expire in 1 min 0 sec`(조립 · 본문) 이 찍히고, 상한을 넘긴 단계는 `[단계 상한] <단계> 단계가 <초>초를 넘겨 다음 단계로 넘어갑니다` 를 남긴다.
- 사내 Jenkins 적용(2026-10-05): 승인 4 서명(대기 0) 확인 → Harness Tier 2 시나리오 5종 실행 PASS → 전역 환경변수 추가(기존 `ADDON_REPO_URL` 유지). 실측 여유 — 기본 모드 production 큰 배치(Linux 8대 · Redfish 10대)에서 archive 0.45~0.55 s · stash 0.14~0.25 s · unstash 0.21~0.23 s · 조립 경로 약 0.8 s 로 상한(30 s · 60 s)의 2 % 이내다. 적용 뒤 production(P3) 11 빌드 전부 상한 표시(30 s 3회 · 60 s 1회)가 찍혔고 상한 초과 0건, 결과는 적용 전과 같다.
- 보장 범위(기본 모드): 느린 archive/stash 나 느린 회수·조립을 **그 단계에서 선점하지 않는다.** 보장은 ① 예산이 수집 뒤 stage 안에 270 s(유예 90 + post 180)를 남기고, ② 마무리는 720 s 합산 · 전역 150 min 으로 끝나며, ③ 그 안에서 Callback 은 남은 시간을 보고 시도한다는 것이다. 느린 보존·회수가 그 합산 제한까지 끌면 Callback 을 못 보낼 수 있다 — 그것이 기본 모드에 남는 보장 축소이며, Tier 2 는 그 구간을 단계별로 끊어 다음 수단과 Callback 시간을 확보한다. Harness(`tests/jenkins/harness/`)의 `*_slow` 시나리오가 기본 모드의 완주를, `inner_*_timeout` 시나리오가 Tier 2 의 단계 전환을 실행으로 확인한다.
- `[Trusted] <경로> len=<글자 수> jhash=<Java String.hashCode>` 콘솔 줄(2026-10-04): 빌드가 `readTrusted` 로 실제 읽은 정본(Location registry · `se_finalize.groovy` · failure reason · supported sections)의 식별값이다. 증거 수집기(`scripts/ai/prodgen/evidence.py`)가 bound revision 의 같은 파일과 대조한다(혼합 revision 탐지). sandbox 가 digest API 를 허용하지 않아 32-bit 해시다 — 무결성 증명이 아니라 내용 식별이다.
- `[Portal 전송] 완료: HTTP 200 (1/3번째 시도)` (2026-10-05 사용자 결정): Portal 로 POST 해서 HTTP 2xx 를 받으면 **전달 완료**다. Portal 의 저장 · 반영 확인은 이 Job 의 역할이 아니므로 응답 본문은 읽지도 기록하지도 않는다(`httpRequest quiet: true`). 결정적 4xx(408 · 429 제외)는 다시 보내지 않는다. 요청 도구(http_request)는 연결 실패 · 응답 시간 초과도 408 로 돌려주므로 실패 줄에 그 뜻을 덧붙인다. 결과는 `finalize_summary.json` 의 `callback{attempted, delivered, http_code, attempts}`.

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
| `redfishAccountDryrun` | boolean | 선택 (기본 false) | **시험 전용.** true 면 `-e _rf_account_service_dryrun=true` 를 넘겨 Redfish 표준 계정 복구(쓰기)를 모의 실행만 한다. 빌드 이름에 `[시험: 계정 복구 모의]` |
| `gatherBudgetForceSec` | string | 선택 (기본 빈 값) | **시험 전용.** 정수(초)를 주면 중단 기준을 그 값으로 바꾼다(남은 시간은 넘지 못함, 정체 감시 꺼짐, rc 124/137 은 콘솔과 `gather_rc.txt` 에). 빌드 이름에 `[시험: 강제 제한 N초]`. 빈 값이면 운영 상한(1절 "시간 제한") |

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
| `ANSIBLE_JSON_PROGRESS_FILE` | Gather | `${WORKSPACE}/gather_progress.jsonl` — host 전이 이벤트(first_seen · precheck · cred_load · auth_proven · alive · checkpoint · addon_started · addon_done · emitted · reconciled · lost). Layer A 가 누락 봉투를 채울 때, 정체 감시가 진행을 볼 때 읽는다 |
| `ANSIBLE_JSON_CHECKPOINT_FILE` | Gather | `${WORKSPACE}/gather_checkpoint.jsonl` — Add-on 직전 조립본(`CHECKPOINT` 태스크) host 당 1줄 |
| `SE_AUTH_EVIDENCE_DIR` / `SE_BUILD_ID` / `SE_EVENT_UUID` | Gather | `${WORKSPACE}/gather_auth_evidence` / `${BUILD_TAG}` / `${params.eventUuid}` — Redfish 모듈이 시도(attempt)마다 남기는 인증 증거 파일(비밀값 없음). task timeout 뒤 rescue 가 현재 시도의 파일만 읽어 401 / 인증 뒤 정지 / 확인 전 정지를 가른다 ([../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md)) |
| `ANSIBLE_VERBOSITY` | Gather | `${params.verbosity}` |
| `ADDON_DIR` | Gather 의 ansible 실행만 | `${WORKSPACE}/addon` — Add-on 을 켜고(아래 전역 변수) 받은 파일이 검사를 통과한 빌드에만 있다. 상위 환경에서 넘어온 값은 환경 경계가 지운다 |
| `SE_GATHER_BUDGET_SEC` · `SE_GATHER_FORKS` · `SE_GATHER_EXPECTED_SEC` · `SE_GATHER_STALL_SEC` · `SE_GATHER_WATCH` | Gather 의 ansible 실행만 | 중단 기준 · forks · 예상 시간 · 정체 판단 시간(420) · 정체 감시 켬(운영 상한일 때만 true) — `scripts/gather_budget.sh` 결과 |
| `SE_PROGRESS_DIR` | Gather 의 ansible 실행만 | `${WORKSPACE}/gather_heartbeat` — Redfish 모듈이 새 응답마다 갱신하는 heartbeat 파일(`redfish-<ip>`) |
| `ANSIBLE_INVENTORY_UNPARSED_FAILED` | Gather 의 ansible 실행만 | `True` — inventory 스크립트가 요청을 거부하면 빈 inventory 로 rc 0 을 내지 않고 실행 실패(outcome `failed_run`). ansible.cfg 가 아니라 이 실행에만 켠다(진단용 ad-hoc 명령 · 시험 도구는 영향 없음) |

환경 경계(`scripts/env_guard.sh`, 2026-10-05 F05): 수집 셸은 상위 환경에서 넘어온 시험용 · 재정의 값(`SE_FORCE_LINUX_RAW_FALLBACK` · `JSON_ONLY_NO_RECONCILE` · `ANSIBLE_JSON_OUTPUT_TASK` · `ANSIBLE_JSON_CHECKPOINT_TASK` · `ANSIBLE_STDOUT_CALLBACK` · `SE_VENDOR_ALIASES_PATH` · `SE_FORCE_SEC` · `SE_MEM_AVAILABLE_MB`, 검사 통과 전 `ADDON_DIR`)을 지우고 콘솔에 **이름만** 남긴다: `[수집] 상위 환경에서 넘어온 시험용 설정을 이번 실행에서 지웠습니다: …`.

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
   최악치: git 명령마다 180 s 제한 × (1차 fetch + 2차 fetch) × retry 2 ≈ 720 s+ — 이것은 `include_role` 의 태스크별 300 s 와 **다른 축**이며, 준비가 길어진 만큼 `[Budget] exec` 재계산이 수집 예산을 줄인다(마무리 예비는 줄지 않는다).
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
| 디스크 | workspace + ansible 로그 공간 (빌드마다 `clovirone-server-gather-<번호>` 작업 공간을 만들고 끝나면 지운다) |

### 동시 실행과 메모리 (2026-10-05 측정)

- Runner 1대(RAM 7.5 GB · executor 15)에 수집 빌드 3~4개가 겹쳐도 남은 메모리는 4.6 GB 이상이었고 swap 은 늘지 않았다. 빌드 하나는
  최대 약 0.56 GB(Linux 15대 · Redfish 10대 배치)를 쓴다. 측정표는 `tests/evidence/2026-10-05-final-maintenance.md` 6절.
- 기본값은 제한 없음이다(두 수집 Job 의 Throttle Concurrent Builds 비활성). 한 Runner 에 무거운 빌드가 10개 가까이 겹칠 수 있는 규모라면
  전역 설정에 throttle 카테고리(예: `clovirone-gather`, 노드당 6)를 만들고 두 수집 Job 에서 그 카테고리를 켠다. 끄면 원래대로 돌아간다(코드 변경 없음).
- 빌드 시작 때의 메모리 보호(`scripts/gather_budget.sh` 의 `mem_cap`)는 그 시점 MemAvailable 로 forks 를 줄인다. 같은 순간에 시작한 빌드끼리는
  같은 여유를 보고 몫을 잡는다는 한계가 있다.
- 같은 BMC 를 여러 빌드가 동시에 요청하면 느린 BMC(예: Cisco C220 CIMC)는 Redfish 수집 상한(1,200 s)에 걸려 부분 성공이 될 수 있다.
  같은 대상의 중복 요청은 호출 측에서 정리한다.

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
- 전송은 남은 예산 안에서 최대 3회(시도별 10~120 s; 5xx · 408 · 429 · 연결 실패만 재시도, 그 밖 4xx 는 중단; 빌드가 ABORTED 면 1회 60 s).
  **HTTP 2xx 를 받으면 전달 완료**다(2026-10-05 사용자 결정 — Portal 의 저장 · 반영 확인은 이 Job 의 역할이 아니고 응답 본문은 보지 않는다).
  모두 실패하면 UNSTABLE 이고 본문은 `callback_body.json` artifact 로 남는다 — 수집 자체가 성공했으면 빌드를 FAILURE 로 만들지 않는다.
- 운영자가 콘솔에서 바로 읽는 줄(2026-10-05 F13):
  `[결과] 요청 N대 — 성공 a · 부분 성공 b · 실패 c`(보낸 결과의 status 를 직접 센다) · 실패 결과를 새로 만든 수 · CHECKPOINT 로 보낸 수(있을 때만) ·
  `[경고] …`(실제로 생긴 조건만, 한 줄에 하나) · `[결과 파일]` 링크(보존에 성공한 파일만: 서버별 수집 결과 `gather_final.jsonl` · Portal 로 보낸 본문
  `callback_body.json` · 실행 요약 `finalize_summary.json`) · `[요약]`(빌드 결과 · 소요 시간 · 대상 · 결과 · 전송 · 경고 코드).
- `finalize_summary.json`: `accepted · lines · kept · filled · outcome · limit_reason · status_counts{success, partial, failed, missing} ·
  warnings[](body_timeout · callback_failed · count_mismatch · filled · outcome_<값> · layer_b_unavailable · preserve_failed · preserve_archive_failed) ·
  callback{attempted, delivered, http_code, attempts} · layerA · layerB · source · unrecovered · damage · by_origin · preserve`.
  UNSTABLE 은 한 번만 표시한다 — 본문 상한 초과 · 전송 실패 · 그 밖 경고(보존 경고는 수집 단계가 이미 표시) 순.
- Groovy 최소 경로의 함수(`seReconcileRaw` 등)는 `scripts/jenkins/se_finalize.groovy` 하나가 정본이다 — 마무리 단계가 `readTrusted` 로 읽어 `load` 하고,
  CI Job(`Jenkinsfile_ci`)이 같은 파일로 Python Layer A 와의 동치를 검사한다. 파일을 못 읽으면 보충 없이 있는 OUTPUT 줄만 보내고 UNSTABLE(`layerB=unavailable`)이다.
- envelope 형식은 [../contract/02-output-envelope.md](../contract/02-output-envelope.md), 실패 봉투의 stage/code 는
  [../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md).

---

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| Jenkins Job 등록 | [03-job-registration.md](03-job-registration.md) |
| 호출자 입력 형식 | [../contract/01-input.md](../contract/01-input.md) |
| 실패 처리 정책 | [../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md) |
