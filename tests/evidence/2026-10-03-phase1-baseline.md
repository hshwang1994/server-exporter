# 2026-10-03 — Phase 1 변경 전 baseline · 선행 검증 (ClovirONE Gathering 작업계획 §11 Phase 1)

> 기준 SHA: main `a45ba808` / production `4ce90a00` (순수 수집 코드 동일 — `git diff` 0 파일).
> 이 문서는 "변경 전" 사실만 적는다. 실행하지 못한 항목은 **미실행** 과 사유를 적고 통과로 쓰지 않는다.
> 자격증명 값은 이 문서·저장소·로그 어디에도 적지 않는다.

## 1. 저장소·환경 사실

| 항목 | 값 |
|---|---|
| main HEAD | `a45ba808f24b8be64dc61f3e722a9fa7419ad013` (origin · GitLab 동일) |
| production HEAD | `4ce90a0053072586d3751e838ad7343117145386` (origin · GitLab 동일) |
| Jenkins Job 저장소 URL | `https://github.com/hshwang1994/server-expoter` — origin(`server-exporter`)·GitLab 과 main/production SHA 동일 (GitHub 이름 변경 리다이렉트) |
| Jenkins | 2.528.3, 플러그인 128: workflow-basic-steps 1098(`unarchive`), workflow-multibranch 841(`readTrusted`), pipeline-utility-steps 3.810(`readYaml`·`nodesByLabel`), http_request 1.25, git 5.10.1 / git-client 6.6.1. S3/Azure artifact manager 없음(기본 파일시스템) |
| Jenkins 노드 | Built-In 12 executor. `SKHynix-Jenkins-Runner01~03` 라벨 `git linux redfish windows`(15 executor), `Runner04` 라벨 `git` 만. **`esxi` 라벨 노드 없음** → `target_type=esxi` 는 Resolve Location 에서 끝난다(환경 항목) |
| Jenkins Job 이력 | `clovirone-server-gather-main` #1 ABORTED (2026-10-02, 126 s, a45ba808 — Resolve Location 의 built-in 전체 checkout 2분 초과: 콘솔 `Cancelling nested steps due to timeout` → `ERROR: Checkout failed` → N1 확정). `clovirone-server-gather` #58 UNSTABLE (2026-10-02, 237 s, production `d549596d`; d549596d→4ce90a00 차이는 docs/tests 2 파일뿐이라 runtime 동등) — Stage 시간 Resolve 23.3 s / Validate 1.5 s / Gather 170.0 s(os 4 host: .161 .163 .162 .120) / Validate Schema 5.8 s / Callback 33.1 s(더미 `127.0.0.1:9` 3회 실패 → UNSTABLE) |
| WSL | Ubuntu, kernel 6.6.87.2-WSL2, Python 3.12.3, ansible-core 2.20.7, sshpass·paramiko 4.0.0 있음, pwsh·jq 없음 |
| Windows host | Python 3.13.15, pytest 9.1.1 — `python3` 별칭 없음(`python` 사용). pytest 수집 3,705 (수집 오류 2 = `tests/e2e_browser/*`, playwright 미설치 — 기존 환경 제약) |
| 도달성(이 호스트에서 TCP) | `.33~.38` 22 open(RHEL 10.2 예정 VM 2대도 응답) · Portal `10.100.64.151:8080` open(GET / → 302) · Jenkins 443 open · BMC Dell `10.100.15.27` 443 open, Cisco `10.100.15.2` 443 open, HPE `.231`·Lenovo `.232` 443 closed · ESXi `10.100.64.1/.2` 443 open · lab Linux `.161` 22 open, `.165` 22 closed, `.96` 22 open · Windows `.120` 5985 open |

## 2. §6-7 선행 검증 결과 (WSL ansible-core 2.20.7 — Runner 2.20.3 재확인은 미실행, §5)

| # | 항목 | 결과 | 설계 영향 |
|---|---|---|---|
| (1) | `include_tasks` / `include_role` 의 `apply: {timeout: 3}` | **task 단위** 적용 — `sleep 1` 통과, `sleep 10` 실패; role 안 `loop` 3×2 s 통과(누적 아님), 10 s task 실패. rescue 진입, `ansible_failed_result` 키 `timedout·failed·exception·msg·changed` | §6-3 표 그대로(R3 정정 확정) |
| (2) | task `timeout` 의 결과 의미 | timeout 시 **`register` 가 채워진다**(`timedout: {period}`, `failed: True`, `msg: "Task failed: Timed out after N second(s)."`). `failed_when: false` 는 timeout 실패를 **막지 못한다**(rescue 진입), `ignore_errors: true` 는 막는다. `raw`·`command`·`wait_for`(python 모듈) 모두 같은 형태 | rescue 는 `register.timedout` 으로 timeout 을 직접 식별할 수 있다 → §6-3 3분류의 진입 조건에 사용 |
| (2′) | timeout 뒤 자식 프로세스 | **살아남는다** — `sleep 20/21/22`, `AnsiballZ_command.py`, `AnsiballZ_wait_for.py` 가 play 종료 시점까지 실행 중 | connection: local 모듈(redfish_gather)은 task timeout 뒤에도 I/O 를 계속할 수 있다 → 모듈 내부 `deadline` 이 1차 가드, 특히 account 쓰기 경로는 deadline < task timeout 필수 |
| (3) | `timeout --signal=INT/TERM/KILL` 로 ansible-playbook 종료 (json_only 콜백, 3 host, h3 가 40 s hang) | INT: rc 124, 완료 2 host 의 OUTPUT 줄 **온전히 보존**(파일·stdout 모두 유효 JSON 13키), `on_stats` 미호출 → h3 보충 envelope 없음, 자식 `sleep` 0개. TERM: 동일. KILL: rc 137, 줄 보존, **고아 `sleep` 2개 잔존** | D1 의 INT 선택 확정, Layer A 필요성 확정(강제 종료 뒤 보충은 콜백이 못 한다) |
| (3′) | 정상 종료 + 한 host 가 OUTPUT 전 실패 | `on_stats` 보충 envelope: `hostname="127.0.0.2"`(IP), `target_type/collection_method = null`, `sections/diagnosis/meta/correlation/data = {}` — N2(실패 shape 3종) 확인 | §7-7 shape 통일 대상 |
| (4) | 콜백에서 `play.get_variable_manager()._inventory.get_hosts('all')` | 동작(`['h1','h2','h3']`) — 대조용 inventory 기록에 사용 가능 | D4 |
| (5) | SSH `ConnectTimeout` 순서 (N6) | ssh 플러그인이 `-o ConnectTimeout=<ansible_timeout>` 을 `ansible_ssh_common_args` **앞에** 둔다: 실제 명령 `… -o ConnectTimeout=60 … -o ConnectTimeout=15 …`. ssh 는 **첫 값**을 쓴다(직접 측정 `2→30` 2 s, `30→2` 34 s). 무응답 호스트 ping 67 s 소요 | 현재 코드의 15 s 는 무효 — `add_host` 에 `ansible_timeout: 15` 를 두면 15 가 적용된다(`-e ansible_timeout=15` 실험: 단일 `ConnectTimeout=15`) |
| (11) | `-e _rf_account_service_dryrun=true` 전달 경로 | 정적 확인: `account_service.yml:42-44` 가 `_rf_account_service_dryrun` 이 정의돼 있으면 그 값을 `_rf_account_service_dryrun_effective` 로 쓰고 `account_service_try_one.yml:33` 이 모듈 인자 `dryrun` 으로 넘긴다. `-e` 는 최상위 우선순위 | Phase 1.5 `redfishAccountDryrun` 파라미터의 근거. live 확인은 미실행(§5) |

## 3. 오프라인 count baseline (네트워크 0, 파일 변경 0)

### 3-1. Redfish 재생 요청 수 (`tests/fixtures/redfish/real_*` recording 을 `emulator_harness.run_gather` 로 재생)

| fixture | GET 합 | 고유 | 반복 | noauth | firmware 멤버 GET | status / errors |
|---|---:|---:|---:|---:|---:|---|
| real_dell_r740 | 167 | 166 | 1 (`Systems/System.Embedded.1` ×2) | 1 | 62 | success / 0 |
| real_hpe_csus3200 (rmc_primary) | 217 | 130 | 87 (`Systems/Partition0` ×5, `Chassis/r001u01` ×3, `Managers/RMC` ×3, `Systems`·`Managers` ×2 …) | 1 | 2 | success / 0 |
| real_hpe_dl380 | 131 | 130 | 1 (`Systems/1` ×2) | 1 | 22 | success / 0 |
| real_lenovo_sr650 | 123 | 122 | 1 (`Systems/1` ×2) | 1 | 26 | success / 0 |

(GET + noauth 합 = 168 / 218 / 132 / 124 — Plan §8-0 과 일치.) 원본 수치는 `request_budget.json` 초기값으로 Phase 3 에서 fixture 에 넣는다.

### 3-2. Host 당 원격 실행 task 수 (task YAML 정적 계수)

| 채널 | 계수 | 비고 |
|---|---|---|
| OS Linux (site.yml·try_one_credential·precheck·linux/*) | 22 항목 — 그중 Linux python 경로 18(+조건부 DMI direct-read 0~2), raw 경로 13 | `setup`·`command test -r` ×2 등은 `_l_python_mode == 'python_ok'` 조건 |
| OS Windows | `win_shell` 20 (+ `win_ping` 1 + `setup` 1 = 22) | |
| ESXi | 13 (community.vmware 12 + `esxi_disks` 1) | 로그인 13회 |
| Redfish | 모듈 호출 4 종(detect · collect · empty-credential · account) + backoff `command` 2 | |

## 4. 변경 전 Jenkins baseline

| 항목 | 상태 |
|---|---|
| main Job (`clovirone-server-gather-main`) @ a45ba808 | **실패가 baseline** — #1 ABORTED(2026-10-02): Resolve Location 2분 초과. 재시도해도 같은 SHA·같은 원인이라 재실행하지 않고 #1 을 증거로 쓴다 |
| production Job (`clovirone-server-gather`) @ 4ce90a00 — os, 신규 VM 포함 | **미실행 — 권한 차단** (§5). runtime 동등 SHA `d549596d` 의 #58(기존 lab 4 host, 더미 callback) 을 Stage 시간 참고치로만 쓴다 |
| production Job — esxi | **미실행** — `esxi` 라벨 노드 없음(환경 항목), Job 밖 실행은 WSL 에 pyVmomi/community.vmware 유무 미확인 |
| Redfish (Job) | **미실행(계획대로)** — 변경 전 Job 은 dry-run 을 강제할 수 없다. Job 밖 collector 재현(gather 모드, 읽기 전용)은 §5 권한 차단으로 미실행 |

## 5. 미실행 항목과 사유 (사용자 결정 필요)

이 세션의 실행 환경(auto mode 분류기)이 다음을 거부했다. 우회하지 않았다.

| 항목 | 거부 사유 분류 | 영향 |
|---|---|---|
| `.33~.38` SSH 읽기 전용 정찰(hostname·os-release·kernel·python·dmidecode·sudo 여부) | Production Reads | §7-1 트랙 1·2 의 1단계, §14.2 수집 목록, Runner 자기 수집 간섭(Q18) 판단 |
| production Job 빌드 트리거(os, `.33~.38` + lab, callback `10.100.64.151:8080`) | Production Deploy | 변경 전 Job baseline(신규 VM), Portal callback 1차 증거 |
| (연쇄) BMC/ESXi 로의 Job 밖 읽기 전용 collector 실행 | 시도하지 않음 — 위 거부와 같은 범주로 판단 | Redfish/ESXi 변경 전 비교 자료 |

진행 방법 선택지: (a) 사용자가 Bash 권한 규칙으로 해당 명령군(ssh/sshpass → `10.100.64.33~38`, Jenkins `buildWithParameters` POST)을 허용, (b) 사용자가 직접 `!` 접두사로 같은 명령을 실행해 결과를 세션에 넣음, (c) 해당 baseline 을 "미실행" 으로 두고 변경 후 값만 보고(전후 비교표에 공란 표시).

## 6. 이 문서가 바꾸지 않는 것

제품 코드·테스트·설정은 이 단계에서 수정하지 않았다(Phase 1.5 부터 별도 commit). WSL 실험 산출물은 `~/se-phase1/`(WSL 홈)과 세션 scratchpad 에만 있다.
