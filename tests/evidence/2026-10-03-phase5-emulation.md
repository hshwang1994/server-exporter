# 2026-10-03 — Phase 5 규모 에뮬레이션 (ClovirONE Gathering 작업계획 §10-3 / Phase 5) — WSL, 실장비 0대

> **이 문서의 모든 수치는 WSL 안의 에뮬레이션이다. 실장비 결과가 아니다.** 대상은 전부 `127.0.0.0/8` 합성 IP 이고, 어떤 장비·VM·BMC 에도
> 연결하지 않았다. Runner(Jenkins agent, ansible-core 2.20.3, 다른 하드웨어)에서의 절대값은 다르다 — 여기서 읽을 것은 **규모에 따른
> 증가 모양 · 결과 완전성(요청 == 결과) · 기록(progress/checkpoint) 비용의 크기 정도** 다.
> 기준 코드: main `5c2c8839`(Phase 4) 의 working tree 를 WSL ext4 로 복사(`rsync`, `.git`·`docs`·`tests`·`.claude` 제외). 복사 시점에
> `os-gather/tasks/windows/gather_*.yml` 5 파일이 다른 작업자에 의해 수정 중이었으나 이 문서의 실패 경로(PLAY 1 → PLAY 1.5)는 그 파일을 실행하지 않는다.
> 제품 코드는 바꾸지 않았다. 새 파일은 `tests/scripts/phase5_*` 4개와 이 문서뿐이다. 자격증명 값은 어디에도 적지 않았다
> (`--vault-password-file` 은 더미 문자열 — 실패 경로는 vault 를 열지 않는다).

## 0. 핵심 결과 (상세는 각 절)

| 항목 | 결과 |
|---|---|
| 실패 경로 wall (host 10 / 50 / 100 / 200, 3회 범위) | 10.6–11.0 / 24.7–37.5 / 52–68 / 104–116 s — host 수에 거의 비례(≈ 0.5–0.6 s/host), forks 50↔100 차이 없음. 예산 600/780 s 의 2–19 % |
| 메모리 | 트리 PSS 피크 forks 10 → 0.40–0.42 GB, 50 → 1.7–1.9 GB, 100 → 3.6–3.7 GB (≈ 36 MB/슬롯, 프로세스 `4×forks+3`); `time -v` maxRSS(메인 1개) 73 → 127 MB |
| 결과 완전성 | 완주 30회(matrix 27 + Task 2 의 완주 3) + 중단 6회 전부 `requested == results` (kept + filled = 접수 수, 중복 0, 누락 0) |
| progress 기록 | host 당 3줄 ≈ 0.83 KB (200 host 166.6 KB); checkpoint 는 이 경로에 없어 0 |
| 기록 비용 (Task 3) | 쌍 차이 +7.9 / −1.2 / +5.9 s — 같은 설정 반복 편차(52.7–68.4 s)보다 작아 **분리 불가**(상한 ≈ 80 ms/host) |
| 중단 (Task 2) | 타이머 INT → rc 124, 3.5–6.9 s 안에 종료, 고아 0, 보충은 관측된 만큼(진단 있으면 `port/TCP_CONNECTION_REFUSED`, 없으면 `fallback/OUTPUT_BUILD_FAILED`). **6회 중 1회는 INT 가 CPython weakref 콜백 안에서 소실**돼 메인이 멈췄고 `--kill-after=90` 의 KILL 로 rc **137** — 그래도 kept 98 + filled 2 = 100 |
| 혼합 상태 | 감시자 INT: 19/81, 55/45 — 완료 줄 전부 유효 JSON·절단 0, 교집합 0, 순서 보존 |
| Layer A 1000 host (Task 5) | 0.21 s(전원 OUTPUT) / 0.23 s(혼합) / 0.12 s(전원 합성) — 120 s 예산의 0.2 % |
| Redfish 에뮬레이터 (Task 4) | **불가** — 443 바인드 권한 없음(비특권·`sudo -n` 불가), 모듈 포트 고정, 표준 vault 복호화 필요 |

## 1. 환경

| 항목 | 값 |
|---|---|
| WSL | Ubuntu 24.04.3 LTS, kernel `6.6.87.2-microsoft-standard-WSL2`, systemd 켜짐 |
| CPU / RAM | AMD Ryzen 5 5600 (6C/12T → `nproc` 12), 15 GiB (`free -g`) |
| ansible / python | ansible-core **2.20.7** (`~/.local` pip), Python 3.12.3, PyYAML 6.0.1 — Runner 는 2.20.3 |
| 측정 도구 | GNU time 1.9 (`/usr/bin/time -v`), coreutils 9.4 `timeout`, `/proc` 기반 샘플러 `tests/scripts/phase5_mem_sampler.py`(0.5 s) |
| 파일시스템 | 저장소 복사본 `~/se-phase5/repo` 와 workspace `~/se-phase5/ws/<label>` 모두 **ext4** (`/mnt/c` 9p 는 fsync·append 비용을 왜곡하므로 쓰지 않았다) |
| loopback 상태 | `ss -ltn`: 22 / 443 / 5985 / 5986 리스너 없음 → `127.0.1.1` 등으로의 connect 는 즉시 **RST**(`ECONNREFUSED`) |
| 권한 | 비특권 사용자. `sudo -n true` → "a password is required". `capsh --print` Current 집합 비어 있음. `net.ipv4.ip_unprivileged_port_start = 1024` |

## 2. 방법 — Jenkinsfile_portal Gather stage 와의 대응

실행기 `tests/scripts/phase5_scale_run.sh` 가 1회 실행을 다음과 같이 재현한다 (요약은 `phase5_report.py summarize` 가 `summary.json` 으로 남긴다).

| Jenkinsfile_portal Gather | 에뮬레이션 |
|---|---|
| `environment { REPO_ROOT, ANSIBLE_CONFIG, ANSIBLE_JSON_OUTPUT_FILE, ANSIBLE_JSON_MANIFEST_FILE, ANSIBLE_JSON_PROGRESS_FILE, ANSIBLE_JSON_CHECKPOINT_FILE, SE_AUTH_EVIDENCE_DIR, SE_BUILD_ID, SE_EVENT_UUID }` | 같은 7 변수를 export (`REPO_ROOT=~/se-phase5/repo`, 파일들은 workspace 디렉터리 아래) |
| `writeFile gather_manifest.json ← SE_MANIFEST_JSON` | `{"schema":1,"build":{"job":"phase5-emulation","number":"<label>","url":null},"channel":"os","request":{"loc":"x",…},"ips":[…]}` (finalize 가 읽는 `channel`·`ips`·`build` 포함) |
| `INVENTORY_JSON` 파라미터 → `os-gather/inventory.sh` | `INVENTORY_JSON='[{"service_ip":"127.0.1.1"},…]'`, `-i <repo>/os-gather/inventory.sh` |
| `-f ${SE_GATHER_FORKS}` (`scripts/gather_budget.sh`: os = min(H, 100)) | `--forks 50` 과 `--forks 100` 두 값 (10·50 host 는 두 값이 같은 효과 — worker 수는 host 수에 묶인다) |
| `timeout --signal=INT --kill-after=90 ${SE_GATHER_BUDGET_SEC} ansible-playbook … --vault-password-file=… -e se_location=…` | 같은 명령. 완주 실행은 `--budget-sec 3600`(공식값은 §3 표 아래), 중단 실험만 짧은 값 |
| `rc → outcome` (0/2/4/8 completed · 124 timeout · 137 timeout_killed · 90 prep_failed · 그 밖 failed_run) | 같은 매핑 |
| post{always}: `timeout 120 python3 scripts/finalize_gather_output.py --workspace … --repo-root … --outcome …` | 같은 호출, `date +%s.%N` 전후 차로 시간 측정 |

측정값의 뜻:

- **wall(s)** — `time -v` 의 Elapsed (`timeout` 포함, `ansible-playbook` 시작부터 종료까지).
- **maxRSS single(MB)** — `time -v` Maximum resident set size. 이것은 wait4() rusage 의 `ru_maxrss` 라서 **트리 안에서 가장 큰 프로세스 하나**의 RSS 다 (worker 합이 아니다).
- **tree PSS peak / tree RSS peak(MB)** — 샘플러가 0.5 s 마다 `timeout` 의 자손 전체를 `/proc` 로 걸어 더한 Pss(공유 페이지 비례 배분)·VmRSS 합의 피크. fork 된 worker 가 COW 로 페이지를 공유하므로 **PSS 합이 실제 메모리 점유에 가깝고 RSS 합은 과대** 하다. 샘플러 자체가 CPU 1개 일부를 쓴다(모든 실행에 동일하게 포함).
- **progress lines / KB, checkpoint lines** — `gather_progress.jsonl`·`gather_checkpoint.jsonl` 의 줄 수·크기. 이 실패 경로에는 `CHECKPOINT` 태스크가 없다(PLAY 2/3 의 build_output 뒤에만 있다) → checkpoint 줄 수는 **구조상 0** 이다.
- **finalize(s)** — Layer A 실행 시간. **kept / filled** 는 `gather_finalize_report.json`, **req==res** 는 `accepted == kept + filled == gather_final.jsonl 유효 줄 수`.
- **orphans t0/t2** — ansible 종료 직후·2 s 뒤 `ps` 에 남은 `ansible-playbook|AnsiballZ|precheck_bundle` 프로세스 수.

실패 경로가 하는 일 (왜 host 당 시간이 이 모양인가):

1. PLAY 1 `detect`(linear, connection local) — host 마다 `precheck_bundle` 이 5986 → 5985 → 22 를 순서대로 확인. OS 채널은 포트당 예산 2 s 안에서 1 s 간격으로 **반복 확인**한다(`tcp_check_budget`, 종전 `wait_for` 의미 보존) → RST 가 즉시 와도 포트당 ~2 s, host 당 ~6–7 s 가 소요된다. 전 포트 RST 이므로 ICMP 는 호출되지 않는다(`reachable=true`, `port_open=false`, `failure_stage=port`, `failure_code=TCP_CONNECTION_REFUSED`).
2. `add_host` ×3(run_once + loop) 으로 `_os_failed` 그룹 등록.
3. PLAY 1.5 `failed-output`(strategy free) — host 마다 `set_fact` → `init_fragments.yml` → `build_failed_output.yml` → `inject schema_version` → `OUTPUT`. 콜백이 stdout 과 `gather_output.json` 에 envelope 1줄씩 append(flush+fsync) 하고 progress 에 `emitted` 를 남긴다.
4. PLAY 2/3 는 host 0 (`Could not match supplied host pattern` 경고 2줄) → rc 0.

`scripts/gather_budget.sh` 가 같은 host 수에 주는 집행 예산(참고 — 측정 wall 과 비교): 1·10·50·100 host → `gather=600`(MIN), 200 host → forks 100 · waves 2 → `gather=780` (SE_VCPU=12, 시작 직후 가정).

## 3. Task 1 — 실패 경로 규모 실행 (10 / 50 / 100 / 200 host × forks 50 / 100 × 3회)

27 실행(24 + Task 3 용 progress-off 3) 모두 `rc=0 / outcome=completed`, **OUTPUT 줄 수 = stdout envelope 수 = host 수**, 13키, 전원 `status=failed` ·
`failure_stage=port` · `failure_code=TCP_CONNECTION_REFUSED`, finalize `kept = host 수, filled = 0`, `requested == results`. 값은 3회를 모두 적는다(통계 없음).
"other ansible procs" 는 종료 직후 machine 전체 `ps` 에 보인 **다른 세션**의 ansible 프로세스 수다(동시 작업자 — 아래 §3 관찰 6) — 이 실행의 고아가 아니다
(PGID 기준 고아 판정은 Task 2 부터 기록했다).

| label | hosts | forks | wall(s) | user(s) | sys(s) | CPU% | maxRSS single(MB) | tree PSS peak(MB) | tree RSS peak(MB) | procs@peak | OUTPUT | progress lines / KB | checkpoint | finalize(s) | kept/filled | other ansible procs t0/t2 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|---|
| h10_f50_r1 | 10 | 50 | 10.62 | 9.40 | 6.10 | 146 | 72.9 | 400 | 1023 | 43 | 10 | 34 / 8.7 | 0 | 0.065 | 10/0 | 0/0 |
| h10_f50_r2 | 10 | 50 | 10.83 | 10.92 | 6.73 | 163 | 73.5 | 398 | 1024 | 43 | 10 | 34 / 8.7 | 0 | 0.065 | 10/0 | 2/6 |
| h10_f50_r3 | 10 | 50 | 10.69 | 10.45 | 6.54 | 158 | 73.2 | 396 | 1024 | 43 | 10 | 34 / 8.7 | 0 | 0.062 | 10/0 | 2/2 |
| h10_f100_r1 | 10 | 100 | 10.97 | 11.24 | 6.89 | 165 | 73.1 | 400 | 1024 | 43 | 10 | 34 / 8.7 | 0 | 0.064 | 10/0 | 0/0 |
| h10_f100_r2 | 10 | 100 | 11.02 | 11.25 | 6.98 | 165 | 72.9 | 399 | 1022 | 43 | 10 | 34 / 8.7 | 0 | 0.060 | 10/0 | 3/3 |
| h10_f100_r3 | 10 | 100 | 10.63 | 10.41 | 6.27 | 156 | 73.1 | 396 | 1025 | 43 | 10 | 34 / 8.7 | 0 | 0.062 | 10/0 | 2/2 |
| h50_f50_r1 | 50 | 50 | 33.60 | 64.20 | 52.46 | 347 | 83.4 | 1733 | 4884 | 203 | 50 | 154 / 41.7 | 0 | 0.077 | 50/0 | 0/0 |
| h50_f50_r2 | 50 | 50 | 30.56 | 56.67 | 42.03 | 322 | 84.0 | 1732 | 4892 | 203 | 50 | 154 / 41.7 | 0 | 0.059 | 50/0 | 0/0 |
| h50_f50_r3 | 50 | 50 | 24.69 | 50.33 | 36.22 | 350 | 83.7 | 1733 | 4898 | 203 | 50 | 154 / 41.7 | 0 | 0.057 | 50/0 | 6/6 |
| h50_f100_r1 | 50 | 100 | 37.50 | 73.14 | 58.32 | 350 | 83.7 | 1735 | 4893 | 203 | 50 | 154 / 41.7 | 0 | 0.100 | 50/0 | 0/0 |
| h50_f100_r2 | 50 | 100 | 30.68 | 58.11 | 42.57 | 328 | 83.7 | 1736 | 4890 | 203 | 50 | 154 / 41.7 | 0 | 0.061 | 50/0 | 0/0 |
| h50_f100_r3 | 50 | 100 | 26.80 | 47.67 | 34.20 | 305 | 84.0 | 1732 | 4900 | 203 | 50 | 154 / 41.7 | 0 | 0.063 | 50/0 | 0/0 |
| h100_f50_r1 | 100 | 50 | 67.47 | 125.57 | 100.62 | 335 | 97.9 | 1803 | 5010 | 203 | 100 | 304 / 83.1 | 0 | 0.186 | 100/0 | 0/0 |
| h100_f50_r2 | 100 | 50 | 61.15 | 118.83 | 90.04 | 341 | 98.0 | 1797 | 5010 | 203 | 100 | 304 / 83.1 | 0 | 0.068 | 100/0 | 0/0 |
| h100_f50_r3 | 100 | 50 | 52.47 | 95.22 | 71.18 | 317 | 98.1 | 1799 | 5008 | 203 | 100 | 304 / 83.1 | 0 | 0.065 | 100/0 | 0/0 |
| h100_f100_r1 | 100 | 100 | 68.44 | 147.95 | 128.10 | 403 | 98.9 | 3568 | 10062 | 403 | 100 | 304 / 83.1 | 0 | 0.112 | 100/0 | 0/0 |
| h100_f100_r2 | 100 | 100 | 52.73 | 112.47 | 88.36 | 380 | 98.9 | 3573 | 10079 | 403 | 100 | 304 / 83.1 | 0 | 0.061 | 100/0 | 0/0 |
| h100_f100_r3 | 100 | 100 | 57.70 | 120.08 | 93.92 | 370 | 98.6 | 3579 | 10086 | 403 | 100 | 304 / 83.1 | 0 | 0.065 | 100/0 | 0/0 |
| h100_f100_noprog_r1 (Task 3) | 100 | 100 | 60.52 | 135.51 | 119.32 | 421 | 99.0 | 2982 | 8366 | 335 | 100 | 0 / 0 (끔) | 0 | 0.089 | 100/0 | 0/0 |
| h100_f100_noprog_r2 (Task 3) | 100 | 100 | 53.92 | 112.79 | 86.63 | 369 | 98.8 | 3573 | 10077 | 403 | 100 | 0 / 0 (끔) | 0 | 0.062 | 100/0 | 0/0 |
| h100_f100_noprog_r3 (Task 3) | 100 | 100 | 51.82 | 119.25 | 95.34 | 414 | 99.0 | 3579 | 10071 | 403 | 100 | 0 / 0 (끔) | 0 | 0.060 | 100/0 | 0/0 |
| h200_f50_r1 | 200 | 50 | 108.00 | 213.23 | 165.14 | 350 | 126.9 | 1918 | 5326 | 203 | 200 | 604 / 166.6 | 0 | 0.068 | 200/0 | 0/0 |
| h200_f50_r2 | 200 | 50 | 114.17 | 232.92 | 177.32 | 359 | 127.1 | 1913 | 5327 | 203 | 200 | 604 / 166.6 | 0 | 0.086 | 200/0 | 0/0 |
| h200_f50_r3 | 200 | 50 | 115.87 | 229.90 | 177.79 | 351 | 127.1 | 1916 | 5330 | 203 | 200 | 604 / 166.6 | 0 | 0.068 | 200/0 | 0/0 |
| h200_f100_r1 | 200 | 100 | 103.89 | 246.10 | 192.91 | 422 | 128.6 | 3741 | 10640 | 403 | 200 | 604 / 166.6 | 0 | 0.084 | 200/0 | 3/2 |
| h200_f100_r2 | 200 | 100 | 116.04 | 269.33 | 215.65 | 417 | 128.6 | 3678 | 10630 | 403 | 200 | 604 / 166.6 | 0 | 0.072 | 200/0 | 3/1 |
| h200_f100_r3 | 200 | 100 | 104.93 | 246.16 | 195.08 | 420 | 128.5 | 3749 | 10646 | 403 | 200 | 604 / 166.6 | 0 | 0.077 | 200/0 | 0/0 |

진행 이벤트 타임라인(progress `ts` 기준, 각 실행의 첫 이벤트 = 0 s): precheck 결과가 모이는 시점 / PLAY 1.5 시작 / `emitted` 창.

| 실행 | precheck 완료 | PLAY 1.5 시작 | emitted 창 | 비고 |
|---|---|---|---|---|
| h50_f50_r1 | 11–12 s | 15 s | 32–33 s | 50 host 전부 ~2 s 안에 OUTPUT |
| h100_f50 r1/r2/r3 | 22–23 / 21–22 / 20–21 s | 29 / 28 / 25 s | 66–67 / 59–60 / 51 s | 2 wave precheck |
| h100_f100 r1/r2/r3 | 18–20 / 17–18 / 12–14 s | 25 / 23 / 23 s | 66–67 / 52 / 56–57 s | 1 wave precheck 인데 PLAY 1.5 가 f50 과 비슷 |
| h200_f50 r1/r2/r3 | 36–39 / 37–40 / 41–44 s | 52 / 50 / 53 s | 106–107 / 113 / 114–115 s | 4 wave |
| h200_f100 r1/r2/r3 | 27–29 / 28–31 / 27–30 s | 43 / 46 / 41 s | 102–103 / 114–115 / 103–104 s | 2 wave |

`gather_budget.sh` 집행 예산과 비교: 10·50·100 host → 600 s, 200 host → 780 s. 측정 wall 은 그 **2–19 %** 다 — 전원 dead-host 배치는 예산 근처에 가지 않는다(예산은 인증 뒤 수집 경로의 host_cap 240 s 로 잡혀 있다).

관찰:

1. **wall 은 host 수에 거의 비례**하고 forks 50 ↔ 100 차이는 없다. 100 host: f50 52–67 s / f100 53–68 s, 200 host: f50 108–116 s / f100 104–116 s (≈ 0.5–0.6 s/host). 10 host 는 고정비(precheck 1 wave ≈ 7 s + play 전환)가 지배해 ≈ 11 s. CPU 사용률이 300–420 % 에 머무는 것으로 보아 병목은 fork 수가 아니라 **controller 쪽 task 당 처리(worker fork · 모듈 패키징 · Jinja 렌더)** 이고, 12 thread 를 다른 세션과 나눠 쓰는 상태였다.
2. **CPU 시간(user+sys)은 host 당 ≈ 1.7–2.4 CPU-s** (10 host 16–18 s · 50 host 82–131 s · 100 host 166–276 s · 200 host 378–485 s). 같은 host 수에서 forks 100 이 forks 50 보다 CPU 를 더 쓴다(100 host: 166–226 vs 200–276 s) — 동시에 떠 있는 프로세스가 많을수록 오버헤드가 늘지만 wall 은 줄지 않는다.
3. **메모리는 host 수가 아니라 fork 슬롯 수에 비례**한다. 트리 PSS 피크: forks 10 → 0.40–0.42 GB(10 host · 100 host 모두), 50 → 1.73–1.92 GB, 100 → 3.57–3.75 GB (≈ 35–37 MB / 활성 슬롯). 피크 시점의 프로세스 수는 `4 × forks + 3` (슬롯마다 worker + `sh` 2 + AnsiballZ python — PLAY 1 precheck 때). `time -v` 의 maxRSS(가장 큰 프로세스 1개 = 메인) 는 73 → 84 → 98 → 127 MB 로 host 수에 따라 자란다(inventory·hostvars). 트리 RSS 합(COW 공유 중복 계산)은 PSS 의 ≈ 2.8배 — Runner 메모리 산정은 PSS 쪽을 써야 한다. 200 host·forks 100 에서 3.7 GB.
4. **progress 파일은 host 당 정확히 3줄**(`first_seen` · `precheck`(진단 dict 포함) · `emitted`) + play 당 1줄 `inventory`(4 play, host 0 인 PLAY 2/3 도 기록) → 34 / 154 / 304 / 604 줄, ≈ **0.83 KB/host**, 200 host 에 166.6 KB. `inventory` 줄은 host 목록 전체를 담아 play 수 × H 로 커진다(200 host 4줄 ≈ 10 KB). checkpoint 는 이 경로에 없어 0.
5. **finalize(Layer A)는 모든 규모에서 0.06–0.19 s** — Python 기동 + 정본 YAML 로드가 지배하고 host 수 영향은 보이지 않는다(1000 host 는 §7).
6. **노이즈**: 같은 설정 3회가 최대 ±20 % 벌어진다(50 host 24.7–37.5 s). `ps` 가 종료 직후 다른 세션의 `ansible-playbook`(scratchpad 플레이북 · `/usr/bin/ansible-playbook -i …/os-gather/inventory.sh` 를 `/mnt/c` 에서 실행) 을 보였고 load average 가 ~4 였다. 최솟값이 가장 덜 교란된 값이지만 그것도 보장은 아니다.
7. 콜백 `first_seen` 줄은 `ip: null` 로 찍힌다(`_ctx` 가 ip 조회 전에 기록) — Layer A 는 `ip or host` 로 키를 잡고 이 경로는 host 이름이 IP 라 영향 없음. 관찰만 적는다(제품 코드 변경 없음).

## 4. Task 2 — 중단(INT) 실행: 100 host, `timeout --signal=INT --kill-after=90 <N>`

같은 100 host 실행을 `timeout --signal=INT --kill-after=90 <N>` 의 N 만 바꿔 끊었다(forks 100 = Jenkins 규칙값). 타이머 만료 → `timeout` 이 자기 프로세스 그룹 전체에 SIGINT → ansible 메인의 `TaskQueueManager._signal_handler` 가 `KeyboardInterrupt` → `[ERROR]: User interrupted execution` → 자식 정리 → 종료. 고아 판정은 **그 실행의 PGID(= timeout PID)** 로 남은 프로세스 수다(t+0 s / t+2 s).

| 실행 | N | 끊긴 지점 | rc | wall(s) → INT 뒤 종료까지 | OUTPUT 줄(파일 / stdout) | 유효 JSON / 절단 | progress 이벤트 | finalize | filled 의 stage / code | 고아(pgid) |
|---|---:|---|---:|---|---|---|---|---|---|---|
| t2_int08_f100 | 8 | PLAY 1 precheck 진행 중 (진단 아직 없음) | **124** | 12.43 → **4.4 s** | 0 / 0 | — | inventory 1 · first_seen 100 | accepted 100 · kept 0 · **filled 100** · exit 0 · 0.086 s | 100 × `fallback` / `OUTPUT_BUILD_FAILED` (분기 4 — 관측 0) | 0 / 0 |
| t2_int40_f100 | 40 | PLAY 1.5 진행 중, OUTPUT 전 | **124** | 43.49 → **3.5 s** | 0 / 0 | — | inventory 2 · first_seen 100 · precheck 100 | accepted 100 · kept 0 · **filled 100** · exit 0 · 0.061 s | 100 × `port` / `TCP_CONNECTION_REFUSED` (분기 1 — precheck 진단 보존, `details.last_task="precheck \| 공통 diagnosis 생성"`) | 0 / 0 |
| t2_int56_f100 | 56 | (끊기 전 완주 — emitted 52–53 s) | 0 | 54.02 | 100 / 100 | 100 / 없음 | 전체 | kept 100 · filled 0 | — | 0 / 0 |
| t2_int62_f100 | 62 | (끊기 전 완주 — emitted 54–55 s) | 0 | 55.58 | 100 / 100 | 100 / 없음 | 전체 | kept 100 · filled 0 | — | 0 / 0 |
| t2_full_f10 (forks 10, 완주) | 3600 | — | 0 | 108.43 | 100 / 100 | 100 / 없음 | 전체 | kept 100 · filled 0 | — | 0 / 0 |

보충 envelope 예 (`t2_int40_f100`, `gather_final.jsonl` 첫 줄 — 13키, `hostname=null`, `status=failed`, 7 지원 섹션 `failed`):

```json
"diagnosis": {"reachable": true, "port_open": false, "protocol_supported": false, "auth_success": null,
              "failure_stage": "port", "failure_code": "TCP_CONNECTION_REFUSED",
              "failure_reason": "OS 접속이 거부되었습니다. 대상 서버의 OS 원격 접속 설정과 방화벽을 확인하세요.",
              "details": {"channel": "os", "adapter_candidate": null, "checked_ports": [5986, 5985, 22], "detected_os": null,
                          "detected_port": null, "finalizer": "layer_a", "outcome": "timeout", "last_task": "precheck | 공통 diagnosis 생성"}},
"errors": [{"section": "precheck", "message": "OS 접속이 거부되었습니다. 대상 서버의 OS 원격 접속 설정과 방화벽을 확인하세요.",
            "detail": "outcome=timeout | last_task=precheck | 공통 diagnosis 생성 | envelope finalized by Layer A; precheck diagnosis preserved"}]
```

`t2_int08_f100` 의 보충분은 `reachable/port_open/protocol_supported = null`, `details = {"channel":"os","finalizer":"layer_a","outcome":"timeout"}`, `errors[0] = {"section":"gather","message":"개더링 프로젝트에서 수집 결과를 만들지 못했습니다.","detail":"outcome=timeout | envelope finalized by Layer A; OUTPUT task did not run"}` 이다.

관찰:

1. **rc 124 · INT 뒤 3.5–4.4 s 안에 종료** — `--kill-after=90` 의 KILL 은 필요 없었다(`time -v` 에 signal 종료 없음). PLAY 1.5 도중 끊긴 실행은 stderr 에 `Process WorkerProcess-1547:` 한 줄(태스크 실행 중이던 worker 하나가 INT 에 걸림)이 추가로 남았다.
2. **고아 0** — 두 중단 실행 모두 t+0 s / t+2 s 에 남은 프로세스가 없다. 판정은 두 겹으로 했다: `timeout` 의 PGID 로 남은 것(이 실행 고유) **과** machine 전체 `ps` 의 `ansible-playbook|AnsiballZ|precheck_bundle`. 두 겹이 필요한 이유 — ansible-core 2.20.7 의 worker 는 `_detach()` 에서 **`os.setsid()`** 로 자기 세션을 만들므로(`executor/process/worker.py:159`) `timeout` 의 그룹 신호도, PGID 검사도 worker 에 닿지 않는다. worker 종료는 메인의 `_signal_handler` 가 worker 마다 `os.kill` 로 INT 를 전달하고 worker 의 `_term` 이 `killpg + kill + os._exit(1)` 하는 경로다(`worker.py:106-120`, `task_queue_manager.py:201-230`). 두 검사 모두 0 이었고, Phase 1 (3)의 "INT: 자식 sleep 0개" 와 일치한다. (Add-on 처럼 원격/장시간 자식을 가진 task 의 INT 거동은 이 경로에 없다.)
3. **Layer A 는 어느 지점에서 끊겨도 `requested == results`** — 두 경우 모두 accepted 100 = kept 0 + filled 100, `gather_final.jsonl` 100줄, dropped/conflicts/corrupt 0, exit 0. 보충 내용은 **관측된 만큼만** 올라간다: precheck 진단이 progress 에 남아 있으면(분기 1) 그 stage/code 를 그대로, 아무 관측도 없으면(분기 4) `fallback/OUTPUT_BUILD_FAILED`. 새 stage/code 는 만들어지지 않았다.
4. **"일부만 OUTPUT" 상태는 타이머로는 겨누기 어렵다.** free strategy 가 host 를 round-robin 으로 한 task 씩 전진시켜 100 host 의 OUTPUT 이 **1–2 s 창**에 몰린다 — forks 100 (52–67 s 사이에서 실행마다 흔들림) 이든 forks 10 (+106–107 s) 이든 마찬가지다. 56 s · 62 s 로 겨눈 두 실행은 창을 지나 완주했고(rc 0), 53 s 는 창 앞이었다. 54 s 한 번은 창 9–10 s 앞에 들어갔는데 그 실행은 INT 자체가 소실돼 다른 이유로 혼합 상태(98/2)가 됐다(§4-1). 그래서 §4-1 에서 **OUTPUT 줄 수를 보고 INT 를 보내는 감시자**로 혼합 상태를 결정적으로 만들었다.

### 4-1. 혼합 상태(일부 OUTPUT 완료 + 나머지 보충) — 타이머 재시도 2회 + 감시자 변형 2회

타이머 N 을 emitted 창(실행마다 52–67 s)에 겨눈 재시도 2회와, **OUTPUT 줄이 N개 쌓이는 순간 `timeout` 프로세스에 SIGINT 를 보내는 감시자**(`--int-when-output-lines N`, 20 ms 폴링) 변형 2회. 감시자 변형에서 `timeout` 은 타이머 만료 때와 똑같이 자식·그룹에 INT 를 전달하지만 타이머가 만료된 것이 아니므로 rc 는 ansible 의 **99** 다(Jenkinsfile 매핑으로는 `failed_run`). 시각은 driver 로그(초 단위)·progress `ts`·감시자 epoch 로 맞췄다.

| 실행 | INT 시점 | rc | wall(s) | OUTPUT 줄 (파일 = stdout) | 유효 JSON / 절단 | `emitted` 이벤트 | finalize kept / filled | filled 의 stage / code | 고아 pgid · 전체 |
|---|---|---:|---:|---|---|---:|---|---|---|
| t2_int53_f100 | 타이머 53 s — PLAY 1.5 중, emitted 전 | **124** | 59.93 (INT 뒤 6.9 s) | 0 (파일 미생성) | — | 0 | 0 / **100** | 100 × `port` / `TCP_CONNECTION_REFUSED` | 0 · 0 |
| t2_int54_f100 | 타이머 54 s ≈ 08:17:48 — PLAY 1.5 중, emitted(08:17:57–58) **9–10 s 전** | **137** | **160.67** (KILL) | **98** = 98 | 98 / 없음 | 98 | 98 / **2** (`127.0.1.4`, `.5`) | 2 × `port` / `TCP_CONNECTION_REFUSED` | 0 · 0 |
| t2_watch10_f100 | 감시자 — 파일 18줄 시점(08:20:38.85) | 99 | 61.57 (INT 뒤 ≤ 1 s) | **19** = 19 | 19 / 없음 | 18 | 19 / **81** | 81 × `port` / `TCP_CONNECTION_REFUSED` | 0 · 0 |
| t2_watch50_f100 | 감시자 — 파일 54줄 시점(08:21:30.96) | 99 | 49.71 (INT 뒤 ≤ 1 s) | **55** = 55 | 55 / 없음 | 54 | 55 / **45** | 45 × `port` / `TCP_CONNECTION_REFUSED` | 0 · 0 |

세 혼합 실행(int54 · watch10 · watch50) 모두: OUTPUT 파일 줄 = stdout envelope 수, 전부 유효 JSON 13키, 마지막 줄 절단 없음(`truncated_tail` 0), finalize `dropped/conflicts/corrupt 0`, `gather_final.jsonl` = manifest 순서 100줄, OUTPUT host 와 보충 host 의 교집합 0, 중복 0. 즉 **완료된 OUTPUT 줄은 온전하고, 나머지는 progress 의 precheck 진단으로 보충됐다.**

#### t2_int54_f100 — INT 가 소실되고 `--kill-after=90` 이 끝낸 경우 (이 문서의 가장 중요한 관찰)

stderr 전문(8줄):

```
Exception ignored in: <function WeakValueDictionary.__init__.<locals>.remove at 0x76117d39d760>
Traceback (most recent call last):
  File "/usr/lib/python3.12/weakref.py", line 105, in remove
    def remove(wr, selfref=ref(self), _atomic_removal=_remove_dead_weakref):

  File "/home/hshwang/.local/lib/python3.12/site-packages/ansible/executor/task_queue_manager.py", line 224, in _signal_handler
    raise KeyboardInterrupt()
KeyboardInterrupt:
```

일어난 일 (코드와 파일 증거로 재구성):

1. 타이머 INT 가 메인 프로세스에 도착했을 때 메인은 **CPython `weakref` 콜백(GC) 안**이었다. `TaskQueueManager._signal_handler`(`task_queue_manager.py:201-230`)는 ① 자기 핸들러를 `SIG_DFL` 로 되돌리고 ② **살아 있는 worker 에 `os.kill(pid, SIGINT)`** 를 보내고 ③ `raise KeyboardInterrupt()` 한다. ③ 이 weakref 콜백 안에서 일어나 CPython 이 "Exception ignored" 로 **삼켰다** — `[ERROR]: User interrupted execution` 이 없고 `cleanup()` 도 돌지 않았다.
2. ② 는 실행됐다. ansible-core 2.20 의 worker 는 task 마다 fork 되고(`setsid()` 로 자기 세션) `_term` 이 `killpg + kill + os._exit(1)` 로 즉시 죽는다(`worker.py:106-120, 159`). 그 순간 task 를 실행 중이던 worker 는 **`127.0.1.4` 와 `.5`** 의 것 두 개뿐이었고 그 결과는 영영 돌아오지 않았다.
3. 메인은 중단을 모른 채 계속 돌아 나머지 98 host 의 OUTPUT 을 08:17:57–58 에 정상 방출했다(파일·stdout 98줄, progress `emitted` 98). 그 뒤 free strategy 는 `while self._pending_results > 0 and not self._tqm._terminated`(`strategy/__init__.py:791`)에서 두 결과를 **무한히 기다렸다** — 샘플러가 +107 s 부터 끝까지 프로세스 3개(time·timeout·메인)·RSS 104 MB 평탄을 기록했다.
4. `timeout` 의 `--kill-after=90` 이 SIGKILL 을 그룹에 보내 끝냈다(`time -v`: "Command terminated by signal 9" → bash rc 137 → Jenkinsfile 매핑 `timeout_killed`). 예정 시각은 INT+90 s = 시작+144 s 인데 측정 wall 은 160.67 s 다 — **16 s 차이의 원인은 확인하지 못했다.** (`time -v` 의 user/sys/maxRSS 는 `timeout` 이 signal 로 죽어 0 / 1.8 MB 로 기록됐다 — 이 실행의 자원값은 샘플러만 유효.)
5. Layer A 는 `outcome=timeout_killed` 로 돌아 **kept 98 + filled 2 = 100**, filled 2건은 progress 의 precheck 진단을 그대로 보존(`port` / `TCP_CONNECTION_REFUSED`), exit 0.

이 세션의 INT 전달 6회(int08 · int40 · int53 · int54 · watch10 · watch50) 중 **1회가 소실**됐다. 소실은 ansible 코드가 아니라 CPython 의 "signal handler 가 weakref 콜백 실행 중에 호출되면 그 예외는 무시된다" 는 거동이고, 신호가 도착하는 순간에 좌우되므로 **재현 확률이지 결정적 결함이 아니다.** 운영 함의: D1 의 `timeout --signal=INT --kill-after=90` 에서 **90 s grace 와 rc 137 매핑은 장식이 아니라 실제로 쓰이는 경로**이며, `gather_budget.sh` 의 `GRACE_SEC=90` 이 reserve 에 들어 있어야 하는 이유가 실측으로 확인됐다. 또 핸들러가 `SIG_DFL` 로 되돌린 뒤라 **두 번째 INT 는 메인을 즉시 죽인다**(cleanup 없이) — Jenkins abort 가 INT 를 한 번 더 보내는 경우의 거동은 이 문서가 측정하지 않았다.

관찰 (혼합 상태):

- `emitted` progress 이벤트가 OUTPUT 줄보다 **1개 적다**(19 vs 18, 55 vs 54): 콜백은 stdout → 파일(fsync) → progress `emitted` 순서로 쓰므로 INT 가 그 사이에 들어오면 파일에는 있고 progress 에는 없는 host 가 생긴다. Layer A 는 OUTPUT 줄을 먼저 보므로 영향 0 — **OUTPUT 파일이 정본, progress 는 보조** 라는 순서가 맞게 동작했다.
- INT 가 OUTPUT 방출 한가운데 들어와도 **부분 줄(절단)은 생기지 않았다** — 줄 단위 write + fsync 가 지켜졌다.
- 감시자 변형 2회는 INT 뒤 **1 s 이내**에 끝났고(로그 초 단위), 타이머 변형은 3.5–6.9 s 였다(precheck/include task 를 실행 중인 worker 를 정리하는 시간으로 보이나 측정 분해능 밖).

## 5. Task 3 — progress/checkpoint 기록 비용 (100 host, forks 100, 3쌍)

같은 100 host · forks 100 실행을 `ANSIBLE_JSON_PROGRESS_FILE` / `ANSIBLE_JSON_CHECKPOINT_FILE` 을 **둔 채(on)** 와 **unset(off)** 로 번갈아 3쌍 돌렸다(각 쌍은 시간상 연속). OUTPUT·MANIFEST 파일 변수는 두 arm 모두 같다. off arm 에서도 콜백은 host 추적(메모리)을 계속하고 **파일 append 만** 건너뛴다. 이 경로의 기록량은 host 당 progress 3줄(open-append-close, fsync 없음) 이고 checkpoint 는 0 이다.

| 쌍 | on wall(s) | off wall(s) | Δwall (on−off) | on user+sys(s) | off user+sys(s) | ΔCPU | on progress |
|---|---:|---:|---:|---:|---:|---:|---|
| r1 | 68.44 | 60.52 | **+7.92** | 276.05 | 254.83 | +21.2 | 304줄 / 83.1 KB |
| r2 | 52.73 | 53.92 | **−1.19** | 200.83 | 199.42 | +1.4 | 304줄 / 83.1 KB |
| r3 | 57.70 | 51.82 | **+5.88** | 214.00 | 214.59 | −0.6 | 304줄 / 83.1 KB |

읽는 법: 세 쌍의 차이(+7.9 / −1.2 / +5.9 s)는 **같은 설정끼리의 반복 편차(on arm 만 52.7–68.4 s)보다 작다.** 이 machine 에서는 기록 비용이 노이즈 위로 분리되지 않는다. 가장 나쁜 쌍을 그대로 믿어도 상한은 100 host 에 ≈ 8 s(host 당 ≈ 80 ms)이고, 두 쌍은 0 근처다. CPU 시간도 r1 만 +21 s 이고 나머지 두 쌍은 ±1.4 s 안이다(r1 off 실행은 샘플러가 335 proc 피크를 찍은 유일한 실행 — 다른 세션과 겹친 흔적). 결론: **이 실패 경로에서 progress 기록은 측정 가능한 비용이 아니다.** 인증 뒤 수집 경로에서는 host 당 이벤트가 더 많고(`cred_load`·`auth_proven`·`checkpoint`·`addon_*`) CHECKPOINT 줄(envelope 1개, flush+fsync)이 추가되므로 그 경로의 비용은 별도 측정이 필요하다 — 이 문서는 그 값을 주장하지 않는다.

## 6. Task 4 — Redfish 에뮬레이터 실행 가능성: **불가 (skip)**

요청 항목은 "`tests/scripts/redfish_emulator.py`(stdlib http.server + 자체서명 TLS, `real_dell_r740/recording.json` 재생, `--bind` 다중 주소)를 127.0.0.x:**443** 에 띄우고 redfish 채널을 1 / 10 host 로 돌리는 것" 이었다. 두 겹의 차단이 있어 구현·실행 모두 하지 않았다 (권한 상승을 시도하지 않았다).

| # | 차단 | 근거 (이 세션에서 관측) |
|---|---|---|
| 1 | **443 바인드 불가** | `python3 socket.bind(("127.0.1.1",443))` → `PermissionError: [Errno 13] Permission denied` (8443 은 OK). `cat /proc/sys/net/ipv4/ip_unprivileged_port_start` = `1024`. `capsh --print` → `Current: =` (CAP_NET_BIND_SERVICE 없음), `getcap $(readlink -f $(which python3))` 비어 있음. `sudo -n true` → `sudo: a password is required` (비대화형 승격 불가). |
| 2 | **모듈은 포트를 바꿀 수 없다** | `redfish-gather/library/redfish_gather.py` 는 URL 을 `f'https://{bmc_ip}/redfish/v1/…'` 로 만든다 (`:479 :519 :558 :592 :951 :1304 :1345`) — 포트 인자가 없다. `bmc_ip` 에 `host:port` 를 넣는 우회도 막혀 있다: `redfish-gather/inventory.sh` 가 `_IP_PATTERN`(IPv4 정규식)으로 거부하고, `precheck_bundle` 도 `CHANNEL_DEFAULT_PORTS['redfish']=[443]` 을 쓴다 (precheck 쪽 `probe_redfish(host, port, …)` 만 포트를 받는다). |
| 3 | **표준 vault 없이는 수집 단계에 못 간다** (443 이 됐어도) | `redfish-gather/site.yml` 의 `abort if credential set unavailable` 게이트는 `vault/common/redfish/standard.yml` 이 **복호화**돼야 통과한다(`credential_set_missing` / `credential_set_undecryptable` 이면 fail → rescue → failed envelope). 이 세션은 vault 비밀번호를 갖고 있지 않고, 더미 계정을 담은 평문 vault 를 파일로 두는 것은 "파일에 자격증명 금지" 제약에 걸린다. `-e` 로 계정을 넘기는 경로는 없다(계정은 `load_one.yml` 의 `include_vars` 결과에서만 온다). 따라서 가능한 최대치는 `precheck → detect_vendor → credential gate 실패` 까지였다. |

에뮬레이터가 가능해지려면 (운영 결정 사항, 이 문서는 요구하지 않는다): Runner 급 환경에서 `setcap cap_net_bind_service=+ep` 를 **에뮬레이터 전용 python 복사본**에 주거나 root 로 띄우는 것, 그리고 테스트 전용 vault 비밀번호를 세션에 주입하는 것 — 둘 다 사용자 결정이 필요하다. 같은 loopback 다중 주소(`127.0.0.x`)는 추가 설정 없이 동작한다(위 connect 테스트가 `127.0.1.1` 에 RST 를 받았다).

대신 Redfish 모듈의 요청 수·파싱 회귀는 네트워크 없는 재생기(`tests/integration/emulator_harness.py`, `test_real_capture_replay.py`, `test_request_budget.py`)가 이미 덮는다 — Phase 1 baseline §3-1 참조. 그 층은 ansible·콜백·finalize 를 거치지 않으므로 이 문서의 규모 측정과 합쳐 읽어야 한다.

## 7. Task 5 — Layer A finalize 마이크로벤치 (1000 host 합성 입력)

`tests/scripts/phase5_finalize_bench.py` 가 실제 envelope 2개를 템플릿으로 1000 host 입력을 합성하고 `scripts/finalize_gather_output.py` 를 3회씩 돌렸다 (ansible 0, 네트워크 0, `~/se-phase5/bench/<scenario>/`).

- 성공 템플릿: `tests/evidence/2026-09-03-live/build199_rhel960_vm_10.100.64.145.json` (os, `status=success`, 13키, 압축 직렬화 ≈ 6.3 KB) — `ip` 와 `correlation.host_ip` 만 바꿔 OUTPUT/CHECKPOINT 줄로.
- 실패 템플릿: `tests/evidence/2026-09-03-live/build194_rhel920_down_10.100.64.163.json` (os, `failure_stage=reachable` / `TCP_CONNECT_FAILED` — 2026-09-03 당시 값) — 그 `diagnosis` 를 progress `precheck` 이벤트에 실어 "진단만 있고 OUTPUT 없는 host" 로.
- IP 는 `127.0.1.1 … 127.0.4.250` (연결 없음). progress 는 host 당 `first_seen` + 이벤트(OUTPUT host: precheck·auth_proven·checkpoint·emitted / CHECKPOINT host: precheck·auth_proven·checkpoint·addon_started / 진단만: precheck) + `inventory` 1줄.

| 시나리오 (1000 host) | 입력 | 입력 크기 | finalize wall(s) ×3 | 보고 | 출력 |
|---|---|---|---|---|---|
| all_output | OUTPUT 1000 | output 6,305 KB · progress 1,159 KB | **0.215 / 0.212 / 0.211** | accepted 1000 · kept 1000 (output 1000) · filled 0 · exit 0 | 1000줄 · 6,305 KB |
| mixed | OUTPUT 700 · CHECKPOINT 150 · 진단만 150 | output 4,413 KB · checkpoint 946 KB · progress 1,090 KB | **0.242 / 0.232 / 0.235** | accepted 1000 · kept 850 (output 700 + checkpoint 150) · filled 150 · exit 0 | 1000줄 · 5,671 KB |
| no_output | 진단만 1000 | progress 694 KB | **0.124 / 0.117 / 0.126** | accepted 1000 · kept 0 · filled 1000 · exit 0 | 1000줄 · 1,843 KB |

내용 확인(mixed): CHECKPOINT 복원 150건은 `status=success` 를 유지하고 `errors[]` 끝에 `{"section":"addon","message":"추가 수집 중 처리가 중단되어 추가 수집 결과가 없습니다. 기본 수집 결과는 그대로입니다.","detail":"finalized from checkpoint; add-on started but did not finish; outcome=timeout"}` 1건이 붙었다(D8). 합성 150건은 템플릿 진단을 그대로 보존해 `reachable` / `TCP_CONNECT_FAILED` 로 나왔다(분기 1 — 관측값 보존, 새 code 없음). status 분포 success 850 / failed 150. dropped · conflicts · corrupt 0.

읽는 법: 1000 host 에서도 Layer A 는 **0.12–0.24 s** — Jenkinsfile 의 `timeout 120`(LAYER_A 예산)의 0.2 % 다. 비용은 host 수보다 **OUTPUT 줄의 바이트 수**(JSON 파싱 + shape gate)에 비례한다(6.3 MB 파싱 ≈ 0.1 s). 합성만 하는 no_output 이 가장 빠르다. 실패 경로 100–200 host 의 0.06–0.19 s(§3)와 합치면, finalize 예산 120 s 는 수천 host 까지 여유가 있고 병목은 Layer A 가 아니라 그 앞 ansible 수집과 뒤 Groovy Layer B(이 문서 범위 밖)다. 이 벤치는 CPU 1개 짜리 단일 프로세스라 공유 machine 노이즈의 영향이 작았다(3회 편차 ≤ 5 %).

## 8. 하지 못한 것 · 한계 · 읽을 때 주의

- **실장비 0, 에뮬레이션 전용.** 대상은 loopback RST 뿐이라 **OS 실패 경로(precheck → PLAY 1.5)만** 쟀다. 인증 뒤 수집 경로(PLAY 2/3 — SSH/WinRM 원격 task, CHECKPOINT, Add-on)의 host 당 시간·메모리·기록 비용은 **측정하지 않았고 추정하지도 않는다.** 200 host 의 성공 경로 wall 은 이 문서로 알 수 없다.
- **Runner 와 다르다.** ansible-core 2.20.7(WSL) vs 2.20.3(Runner), CPU/메모리/디스크가 다르다. 절대값을 Runner 용량 산정에 그대로 쓰지 말고, "fork 슬롯당 ≈ 36 MB PSS · host 당 ≈ 0.5 s / 2 CPU-s(실패 경로)" 같은 **비율**만 참고한다.
- **공유 machine.** 측정 중 다른 작업자의 ansible/pytest 가 같은 WSL 에서 돌았다(§3 관찰 6). 3회 값의 벌어짐이 그 흔적이다. 반복 3회의 min/max 만 적고 분포 통계는 내지 않았다.
- **샘플러 한계.** 0.5 s 간격이라 그 사이의 순간 피크는 놓칠 수 있고(`h100_f100_noprog_r1` 의 335 proc 이 그 예), 샘플러 자신이 CPU 를 조금 쓴다(모든 실행에 동일).
- **`time -v` maxRSS 는 단일 프로세스 값**이다. 트리 합은 샘플러 열(PSS)을 봐야 한다.
- **progress 비용(Task 3)은 노이즈 아래**였다 — "비용 0" 이 아니라 "이 환경·이 경로에서 분리 불가" 다.
- **Redfish 에뮬레이터(Task 4)는 하지 않았다.** 443 바인드 권한 · 모듈의 고정 포트 · 표준 vault 세 가지가 막는다(§6). 권한 상승이나 더미 vault 파일로 우회하지 않았다.
- **INT 소실(§4-1)은 1/6 관측**이다 — 확률을 말할 표본이 아니다. Runner(2.20.3) 에서의 재현 여부, Jenkins abort 의 두 번째 INT 거동, 160.67 s 와 예정 144 s 의 16 s 차이는 미확인. 혼합 상태 감시자 변형의 rc 99 는 실제 Jenkins 가 만드는 값이 아니다(타이머 만료 아님).
- **고아 판정은 PGID + machine 전체 grep 두 겹**이지만, 다른 세션이 동시에 ansible 을 돌리면 전체 grep 은 오염된다(§3 matrix 분의 "other ansible procs" 열). Task 2 실행 시간대에는 다른 세션 프로세스가 0 이었다.
- 제품 코드의 거동 중 이 문서가 **바꾸지 않고 적기만 한 것**: `first_seen` progress 줄의 `ip: null`, PLAY 2/3 의 `Could not match supplied host pattern` 경고, 전 host OUTPUT 이 PLAY 1.5 마지막 1–2 s 에 몰리는 free strategy 의 모양(중단 시 "일부만 OUTPUT" 상태가 매우 짧은 창에서만 생긴다 — §4).

## 9. 산출물 · 재현 명령

저장소에 추가한 파일 (제품 코드 변경 0):

| 파일 | 역할 |
|---|---|
| `tests/scripts/phase5_scale_run.sh` | 1회 실행기 — 합성 inventory/manifest 생성, Jenkinsfile_portal Gather 와 같은 env·명령, `time -v`, 샘플러, PGID + 전체 고아 검사, Layer A 호출, `summary.json`. `--no-progress`(Task 3), `--budget-sec N`(Task 2 타이머), `--int-when-output-lines N`(Task 2 감시자) |
| `tests/scripts/phase5_mem_sampler.py` | `/proc` 기반 프로세스 트리 RSS/PSS 합 샘플러 (0.5 s) |
| `tests/scripts/phase5_report.py` | `summarize`(원본 파일 → `summary.json`) · `table`(여러 summary → Markdown 표) |
| `tests/scripts/phase5_finalize_bench.py` | Task 5 — 1000 host 입력 합성 + finalize 반복 측정 |
| `tests/evidence/2026-10-03-phase5-emulation.md` | 이 문서 |

WSL 쪽 산출물(저장소 밖, 이 machine 에만 있음): `~/se-phase5/repo`(ext4 복사본), `~/se-phase5/ws/<label>/`(실행마다 `gather_manifest.json` · `gather_output.json` · `gather_progress.jsonl` · `gather_checkpoint.jsonl`(있으면) · `gather_rc.txt` · `gather_final.jsonl` · `gather_finalize_report.json` · `time.txt` · `mem.json` · `stdout.log` · `stderr.log` · `orphans.txt` · `watcher_int.txt`(감시자 변형) · `summary.json`), driver 로그 `~/se-phase5/matrix.log` · `task2.log` · `task2b.log`(driver 스크립트 3개도 `~/se-phase5/` — 저장소 밖 1회용), Task 5 는 `~/se-phase5/bench/<scenario>/` + `finalize_bench.json`. label: Task 1 `h<hosts>_f<forks>_r<rep>`, Task 3 `h100_f100_noprog_r<rep>`, Task 2 `t2_int<N>_f100` · `t2_watch<N>_f100` · `t2_full_f10`.

재현 (WSL, 저장소 루트를 ext4 로 복사한 뒤):

```bash
# 복사본
rsync -a --delete --exclude .git --exclude docs --exclude tests --exclude .claude --exclude "REDFISH_BIOS_GATHERING_PLAN_MODE_PACKAGE_*" \
      /mnt/c/github/ClovirONE/clovirone-server-gathering/ ~/se-phase5/repo/
S=/mnt/c/github/ClovirONE/clovirone-server-gathering/tests/scripts
# Task 1 — 한 점 (예: 100 host, forks 100). --forks 생략 시 gather_budget.sh 의 os 규칙 min(H,100)
bash $S/phase5_scale_run.sh --repo-root ~/se-phase5/repo --workdir ~/se-phase5/ws/h100_f100_r1 --hosts 100 --forks 100 --budget-sec 3600 --label h100_f100_r1
# Task 3 — 기록 끔
bash $S/phase5_scale_run.sh --repo-root ~/se-phase5/repo --workdir ~/se-phase5/ws/h100_f100_noprog_r1 --hosts 100 --forks 100 --no-progress --label h100_f100_noprog_r1
# Task 2 — 중단 (INT 40 s)
bash $S/phase5_scale_run.sh --repo-root ~/se-phase5/repo --workdir ~/se-phase5/ws/t2_int40_f100 --hosts 100 --forks 100 --budget-sec 40 --label t2_int40_f100
# 표
python3 $S/phase5_report.py table --glob "$HOME/se-phase5/ws/h*/summary.json"
# Task 5
python3 $S/phase5_finalize_bench.py --repo-root ~/se-phase5/repo --workdir ~/se-phase5/bench --hosts 1000 --repeat 3 \
    --template-success /mnt/c/github/ClovirONE/clovirone-server-gathering/tests/evidence/2026-09-03-live/build199_rhel960_vm_10.100.64.145.json \
    --template-failed  /mnt/c/github/ClovirONE/clovirone-server-gathering/tests/evidence/2026-09-03-live/build194_rhel920_down_10.100.64.163.json
```

실행기가 ansible 에 넘기는 실제 명령 (Jenkinsfile_portal Gather 의 `sh` 블록과 같은 모양):

```bash
/usr/bin/time -v -o $WS/time.txt timeout --signal=INT --kill-after=90 $BUDGET \
    ansible-playbook $REPO_ROOT/os-gather/site.yml -i $REPO_ROOT/os-gather/inventory.sh -f $FORKS --vault-password-file=$VAULT_TMP -e se_location=x
timeout 120 python3 $REPO_ROOT/scripts/finalize_gather_output.py --workspace $WS --repo-root $REPO_ROOT --outcome $OUTCOME
```
