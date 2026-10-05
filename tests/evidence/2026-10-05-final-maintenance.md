# 2026-10-05 — 최종 정비(7차): F01~F13 판정 · 수정 · 실수집 검증 · 승격

지시서 "ClovirONE Server Gathering 최종 정비 계획 및 실행 지시"(2026-10-05, 검토 결과 F01~F13)에 대한 실행 기록이다.
시작 기준은 main `27f7f4f1`(문서 `2973987a`) · production P3 `915dec4e` 다. 6차 기록은 `2026-10-04-review-c1-c6.md` §11.

## 0. 요약

| 항목 | 결과 |
|---|---|
| 최종 후보 (main) | **X13 `1e15bf6f`** — GitHub · GitLab 일치 |
| production | **P4 `5ac5566c`**(main X13, parent P3 `915dec4e`) — GitHub · GitLab · 로컬 일치, trailer 완비 (§8) |
| 커밋 | runtime · 시험 17개 (`5d1c17c5` ~ `1e15bf6f`) — 아래 2절 |
| 로컬 시험 (X13) | unit · e2e · regression 4,411 통과 · integration(not live) 308 통과 · corpus 18/18 · 3채널 syntax-check · 로컬 prodgen G14 · G15 PASS (§3) |
| main Job 실수집 | X12 #187~#198 · **X13 #231~#242** 핵심 12 시나리오 기대 결과 일치 + 추가 시나리오(X10 #170~#174) (§5) |
| CI | #21 실패(원인 · 수정 §5-4) → #22 SUCCESS(X12) → **#23 SUCCESS(X13)** — Verify COMPLETE_PASS 20/20 · 증거 46건 direct |
| F07 · 성능 | throttle 불필요(노드당 3~4 빌드에서 MemAvailable ≥ 4.68 GB · swap 0, §6) · P3 ↔ X12 퇴행 없음(§7) |
| §5 감사 | 예외 무시 지점 81개 · 필수 데이터를 숨기는 원인 8개 중 4개 수정(X13), 4개 기록 (§10) |
| production 검증 (P4) | production Job 12 빌드 #131~#142 전부 기대 결과 · checkout `5ac5566c` · 명부 전 채널 성공 26/32(미해결 6건은 명부 그대로) (§8-2) |
| 사용자 결정으로 바뀐 계약 | Portal 전송은 **HTTP 2xx 수신까지**가 이 Job 의 책임이다(응답 본문은 읽지도 기록하지도 않는다) — 지시서 F09 의 저장 증거 요구와 §8 완료 조건 5 를 대체 |

## 1. 판정표 (F01~F13)

판정 어휘: 이번 수정 · 이미 해결 · 환경 검증 · 사용자 결정.

| # | 판정 | 요지 | 커밋 |
|---|---|---|---|
| F01 | 이번 수정 | 정상 종료(on_stats) 때 callback 이 OUTPUT 없는 host 를 기본 실패로 채우면서 CHECKPOINT 를 무시했다 → checkpoint envelope 에 오류 1건을 붙여 내보낸다(Layer A 와 같은 문장). Add-on 의 "combine into output" 실패는 Add-on 오류 1건으로 가두고 기본 결과를 유지한다 | `5d1c17c5` |
| F02 | 이번 수정 | 결과 형태 검사가 값 종류를 보기 전에 비교해 한 행의 타입 오류로 Layer A 전체가 멈췄다 → Python Layer A · Groovy Layer B · 전송 직전 검문이 같은 최소 계약(값 종류 먼저, NaN 거부)을 쓴다. 나쁜 행만 격리 | `b482a5fb` |
| F03 | 이번 수정 | Validate 와 inventory 의 입력 규칙이 달랐다 → `seAcceptTargets` 가 inventory 3종과 같은 규칙(ASCII IPv4 · 공백 · 중복 · 원소 타입)으로 요청 전체를 거부한다. `unparsed_is_failed=True`. 계정 정보가 든 callbackUrl 거부(주소를 출력하지 않음) | `13984b64` · `6a74faf1` |
| F04 | 이번 수정 | Redfish redirect 가 다른 origin · https→http 로도 Authorization 을 보냈다 → 같은 origin 의 GET/HEAD 만 따라가고, 쓰기는 따라가지 않는다. 응답 캐시 총량 상한 8 MiB · ETag 읽기 상한 | `e06033c3` |
| F05 | 이번 수정 | 상위 환경의 `ADDON_DIR` · 시험값이 수집 셸로 넘어왔다 → `scripts/env_guard.sh` 가 지우고 이름만 기록한다(검사 통과한 Add-on 만 유지) | `2ba192b5` |
| F06 | 일부 이미 해결 + 이번 수정 | 본문 결합 · 기록과 마지막 보존이 Tier 2 상한 밖이었다 → `BODY` 60 s · 마지막 archive 30 s. CLI 승격이 CI 의 `require_bounded` 를 낮추지 못한다 | `c15a52c8` |
| F07 | 환경 검증 → 설정 변경 없음 | 노드당 수집 빌드 3~4개에서 MemAvailable 최소 4.68 GB · swap 증가 0 → throttle 미적용(권장값은 `docs/operate/04` 7절). Redfish 캐시 총량 상한은 F04 에서. 같은 BMC 동시 요청 시 느린 BMC 지연 관측 — §6 | `e06033c3`(캐시 상한) |
| F08 | 이번 수정(F12 모델) | Redfish 후보 수가 예산에 연결되지 않음 — 예상치는 표시용이 됐고 중단은 운영 상한 · 정체 감시가 맡는다 | `ef7575b2` |
| F09 | 사용자 결정 → 정리 | 2xx 수신까지가 계약. `httpRequest(quiet: true)` · 응답 본문 미판독 · `finalize_summary.callback{attempted, delivered, http_code, attempts}` | `6a74faf1` |
| F10 | 이번 수정(현재 파일) + 사용자 결정 | runbook 85행 평문 1건을 가렸다. 추적 파일 재검사: 현재 자격 값 0건(4절). 회전 · 이력 정리는 사용자 결정 | `71948b27` |
| F11 | 이번 수정(문서) | REQUIREMENTS 의 "Python 3.9 미만 수집 불가"를 정정 — raw 경로로 수집(RHEL 8.10 · Python 3.6.8 실측) | `71948b27` |
| F12 | 이번 수정 | 예상치와 중단 기준 분리(budget = 운영 상한), 정체 감시(`scripts/gather_watch.py`, 예상 시간 뒤 420 s 무진행), Redfish 진행 기반 마감(절대 1200 s · 무응답 120 s · heartbeat) | `ef7575b2` |
| §5 정확성 | 이번 수정 + 기록 | Windows · ESXi 예외 무시 지점 81개 전수 분류 → 필수 데이터를 숨기는 C 8건 중 4건 수정(사용자 목록 · 그룹 조회 · system 구성요소 · 물리 디스크), 4건은 근거와 함께 기록 — §10 · 영역별 범위 §11 | `1e15bf6f` |
| F13 + §6 | 이번 수정 | 단계 표시 이름 · sh label · 결과 집계 · 경고 한 줄씩 · 결과 파일 링크 · 빌드 이름 · 시험 표시 | `6a74faf1` · `444db56e` |

## 2. 커밋

| 커밋 | 제목 |
|---|---|
| `5d1c17c5` | fix: 결과 보존 — 종료 보충이 CHECKPOINT 를 쓴다 (F01) |
| `b482a5fb` | fix: 결과 형태 검사 공통 계약 — 값 종류 먼저 (F02) |
| `13984b64` | fix: 입력 확인을 inventory 규칙과 일치 (F03) |
| `e06033c3` | fix: Redfish 인증 리다이렉트를 같은 origin 으로 제한 (F04) |
| `abdfcb9c` | test: Redfish 캐시 시험 뒤 모듈 전역 캐시를 끈다 |
| `2ba192b5` | fix: 빌드 환경 경계 — 검증 안 된 Add-on·시험값 차단 (F05) |
| `ef7575b2` | feat: 수집 시간 — 예상치와 중단 기준 분리, 정체 감시 (F12) |
| `c15a52c8` | fix: 마무리 본문 단계 상한 · CLI 승격의 Tier 2 요구 (F06) |
| `6a74faf1` | refactor: 운영 표시 — 단계 이름·결과 요약·전송 문구 (F13·F09) |
| `71948b27` | docs: Linux Python 요건 정정 · runbook 평문 가림 (F11·F10) |
| `20010c59` | test: 원격 태스크 timeout 관측 플레이북 (F12 d·e) |
| `444db56e` | fix: 운영 화면 문구 4건 — 408 설명 · 괄호 · 소요 시간 |
| `6a2a7853` | test: 원격 timeout 관측 — 연결을 닫은 뒤 잔존도 본다 |
| `a25405be` | fix: CI syntax-check 를 실제 inventory 로 — unparsed_is_failed 정합 (제목 69자 — rule 90 의 50자 권고 초과, 이력 재작성 금지라 그대로) |
| `6f83cb33` | fix: inventory 해석 실패 처리를 Jenkins 수집에만 켠다 |
| `b33e278d` | test: inventory 대조 시험 — 자식 출력 UTF-8 고정 |
| `1e15bf6f` | fix: Windows 수집의 숨은 실패 기록 (C-1·2·3·6) — §10 |

계약 변경(envelope 13 필드 · failure_code enum 은 그대로):

- `diagnosis.details.limit_reason`(결과 정리 Layer A 의 합성 실패 봉투에만, `stalled` · `ceiling` · `forced`) — 수집이 시간으로 끝난 이유. CHECKPOINT 봉투는 `errors[].detail` 에만, 실행 단위 정본은 `finalize_summary.limit_reason`
- `finalize_summary.json`: `status_counts{success, partial, failed, missing}` · `warnings[]`(코드) · `callback{attempted, delivered, http_code, attempts}` · `limit_reason`
- 단계 표시 이름: 입력 확인 · 실행 위치 확인 · 서버 정보 수집 · 결과 확인 및 전송(post 안의 표시 단계)
- Redfish 수집 상한: 절대 1200 s(task 1260 s) + 무응답 120 s
- `ansible.cfg [inventory] unparsed_is_failed = True`
- 입력 확인: 계정 정보가 든 callbackUrl 거부

## 3. 로컬 검증

X13 `1e15bf6f`(최종 후보) — PC 메모리 부족으로 한 번에 돌린 전체 실행이 시스템에 의해 중단돼(사용자 선택: 나눠서 다시) 묶음별로 돌렸다:

| 검사 | 결과 |
|---|---|
| `pytest tests/unit` (prodgen · 일반 2묶음 · Windows 전용 6파일) + `tests/e2e` + `tests/regression` | 98 + 1,719 + 1,374 + 259 + 961 = **4,411 통과** · 건너뜀 20 · xfail 7 · 실패 0 |
| `pytest tests/integration -m "not live"` | 308 통과 · 건너뜀 4 |
| `ci_gate.sh` 정적 검사(`CI_GATE_SKIP_PYTEST=1`) | field_dictionary PASS · schema drift 정합 · 벤더 경계 통과 · 하네스 일관성 통과 · corpus MATCH 18/18 |
| `ansible-playbook --syntax-check` 3채널 (WSL ansible-core 2.20.7, `ANSIBLE_CONFIG` = 저장소 ansible.cfg) | rc 0 × 3 |
| 로컬 `prodgen build --sha 1e15bf6f` + `verify --only G14,G15` | 194 파일 · tree `1c16ca55…` · **G14 PASS**(생성 tree 위 4,131 통과) · **G15 PASS**(모듈 smoke 3종) |

X10 기준(아래 표)은 그 시점의 기록이다.


| 검사 | 결과 |
|---|---|
| `pytest tests/unit tests/e2e tests/regression` | 4,308 통과 · 1 실패 → 재실행 통과(`test_cli_exit_codes` — 이 PC 에서 `PYTHONIOENCODING=utf-8` 을 붙여 자식은 UTF-8, 시험은 cp949 로 읽은 환경 차이. 변수 없이 13/13 통과, 코드 무관) |
| `pytest tests/integration -m "not live"` | 308 통과 |
| `ci_gate.sh` 정적 검사(`CI_GATE_SKIP_PYTEST=1`) | field_dictionary PASS · schema drift 정합 · 벤더 경계 통과 · 하네스 일관성 통과 · finalize corpus MATCH 18/18 |
| `ansible-playbook --syntax-check` 3채널 (WSL ansible-core 2.20.7) | rc 0 × 3 |
| Groovy 2.4.21(Jenkins 와 같은 버전) 구문 | `Jenkinsfile_portal` · `Jenkinsfile_ci` · `se_finalize.groovy` OK. 새 순수 함수(`seFilterEnvelopeLines` 집계 · `seOutcomeText` · `seLimitText` · callbackUrl 계정 정보 검사식) 실행 확인 |
| Jenkins Declarative 검증기(`/pipeline-model-converter/validate`, 실행 없음) | "Jenkinsfile successfully validated." |
| Redfish 요청 수(실장비 녹화 재생, P3 의 main `17843cf0` ↔ X10) | Dell R740 136 · HPE CSUS3200 133 · HPE DL380 130 · Lenovo SR650 122 — **같다**, 4종 모두 success |

## 4. 원격 태스크 timeout (F12 (d)(e)) · 비밀값 재검사 (F10)

### 4-1. 원격 태스크 timeout — 실제 대상

시험 전용 플레이북 `tests/jenkins/harness/remote_timeout_probe.yml` (production 제외 경로). 연결 설정은 `os-gather/site.yml` 과 같다(SSH 22 · WinRM 5986 NTLM, SSH 다중화 ControlPersist 60s). 실행: 이 PC 의 WSL ansible-core 2.20.7, 자격 증명은 `vault/git/os/*.yml` 첫 계정(no_log).

| 대상 | (d) 무출력 장기 명령 | (e) 끝나지 않는 명령 | 끊긴 직후 원격 잔존 | 연결을 닫은 뒤(`meta: reset_connection`, 새 연결) | 정리 뒤 |
|---|---|---|---|---|---|
| Linux `10.100.64.161` (RHEL 8.10, raw — 모든 Python 상태의 경로) | `sleep 100` · 상한 120 s → **성공** | 상한 10 s → **끊김**("Timed out after 10 second(s)") | **1개** | **1개** | 0 |
| Windows `10.100.64.120` (Server 2022, WinRM) | `Start-Sleep 120` · 상한 180 s → **성공**(WinRM 읽기 제한 70 s 를 넘어도 유지) | 상한 10 s → **끊김** | 0 | 0 | 0 |

- 판정: 상한은 무출력 장기 명령을 살리고 끝나지 않는 명령을 끊는다(둘 다 기대대로). **Linux(SSH)는 끊긴 명령이 원격에 남는다** — 연결을 닫아도 남는다. GP-14(로컬 확인)를 원격에서 확인했다. Windows 는 WinRM 이 자식까지 정리한다.
- 운영 영향: 원격 명령이 멈춘 Linux 대상(예: 응답 없는 NFS 마운트의 `df`)은 수집이 상한에서 넘어간 뒤에도 그 명령이 대상에 남는다. 수집 결과에는 영향이 없다(그 섹션은 실패로 기록). 디스크 대기(D 상태) 프로세스는 SIGKILL 로도 끝나지 않으므로 원격 `timeout` 래핑으로도 다 막지 못한다 — 대응 검토는 NEXT_ACTIONS.
- 정리: 시험이 만든 marker 프로세스만 찾아 정리했다(정리 뒤 0). 첫 시도에서 `pkill -f <marker>` 가 자기 셸까지 끝내 연결이 끊겼다 — 패턴을 `[S]E_RTP…` 형태로 바꿔 해결(시험 도구 결함, 운영 코드와 무관).

### 4-2. 비밀값 재검사 (값은 출력 · 기록하지 않음)

- 현재 vault 마스터 암호로 `vault/**` 49/49 를 열어 password 계열 값 15개를 꺼내고, runbook 85행의 옛 값 1개를 더해 **모든 추적 텍스트 파일**을 검사했다(메모리에서만, 경로 · 개수만 출력).
- 결과: 현재 vault 마스터 암호 0 · 현재 자격 값 0 · Cisco 공장 기본값(`password` 라는 일반 단어) 452(노출 아님) · Huawei 공장 기본값 4(제조사 공개값, `docs/operate/05-vault.md` 표 · secret_guard 허용 목록) · runbook 85행 옛 값 1 → **0**(가림).
- 85행의 옛 값은 현재 vault 마스터 암호도 현재 vault 의 어떤 자격 값도 아니다. git 이력에는 그 값이 들어간 2026-08-12 commit 1개가 남아 있다 — 회전 · 이력 정리는 사용자 결정(사용자 지시: 토큰 폐기 · 재발급 금지). GitHub 저장소는 익명 읽기가 된다.

## 5. 후보 변천 · main Job 실수집 · CI

### 5-1. 후보 변천 (모두 GitHub · GitLab 일치 push)

| 후보 | SHA | 바뀐 것 | 결과 |
|---|---|---|---|
| X9 | `20010c59` | C1~C8 · C10 · 원격 시험 플레이북 | main #146~#157 기대 결과 일치. 실화면에서 표시 4건 발견 → X10 |
| X10 | `6a2a7853` | 표시 4건(`444db56e`) · 원격 시험 보강 | main #158~#169 일치 · 추가 시나리오 #170~#174. **CI #21 실패**(아래) |
| X11 | `a25405be` | `ci_gate.sh` syntax-check 를 실제 inventory 로 | main #175~#186 일치. CI #21 의 나머지 실패가 남아 바로 X12 로 |
| X12 | `b33e278d` | inventory 해석 실패 처리를 Jenkins 수집 실행에만(`6f83cb33`) · 시험 2개 `source_text` · 시험 자식 출력 UTF-8 | main #187~#198 일치 · CI #22 SUCCESS · F07 · 성능 비교 기준 |
| **X13** | **`1e15bf6f`** | Windows 숨은 실패 기록(§10 — C-1 · C-2 · C-3 · C-6) | main #231~#242 일치 · **CI #23 SUCCESS** → **승격(P4)** |

X10 → X12 사이 runtime 변경은 `6f83cb33` 하나(ansible.cfg 에서 설정 제거 + `Jenkinsfile_portal` 수집 셸에 환경변수 한 줄)다. 생성 tree 는 X12 에서 `1ad25d58…`, X13 에서 `1c16ca55…`(X12 → X13 runtime 변경은 Windows 수집 태스크 3개뿐).

### 5-2. main Job 핵심 12 시나리오 (X12, #187~#198 — 모두 checkout `b33e278d`)

| 시나리오 | 빌드 | 결과(기대) | 요지 |
|---|---|---|---|
| T2 빠른 실패 | #187 | SUCCESS | TEST-NET 2대 실패 결과 · Harness 수신기 200 |
| T5 사용자 중단 | #188 | ABORTED | `[수집] 중단됨: …` · 4대 실패 결과 전송(1회) · `warnings: filled, outcome_aborted` |
| T6 전송 실패 | #189 | UNSTABLE | `[Portal 전송] 실패 … HTTP 408 — 연결하지 못했거나 …` 3회 · `callback_failed` · 본문 보존 |
| S5 Kernel 6.x | #190 | SUCCESS | `.37` · `.38` RHEL 10.2 · 6.12 — DIMM slot 1 · 4096 MB · physical_installed · 오류 0 |
| S1 정상 | #191 | SUCCESS | Linux 3 + Windows 1, 4/4 success, Portal 200 |
| S4 Windows | #192 | SUCCESS | `.120` Server 2022 |
| S2 혼합 | #193 | SUCCESS | 4 success + TEST-NET 2 실패 진단 |
| E2E-A cj | #194 | UNSTABLE | `[실행 위치] cj · os → …` · 127.0.0.1:9 전송 거부(기대) |
| E2E-A2 chj | #195 | FAILURE | `[실행 위치] 등록되지 않은 Location: 'chj'` · 수집 단계 건너뜀 |
| E2E-D ESXi | #196 | SUCCESS | 6/6 |
| E2E-E Redfish | #197 | SUCCESS | dry-run, 표준 계정, Account Write 0 |
| S3 강제 제한 | #198 | UNSTABLE | `[시험: 강제 제한 150초]` · rc 124 · 6 success + 1 합성(Cisco) · `limit_reason=forced` |

### 5-3. 추가 시나리오 (X10 — X12 와 runtime 차이는 `6f83cb33` 한 줄 · 설정 한 줄)

| 시나리오 | 빌드 | 결과 |
|---|---|---|
| 중복 IP | #170 | FAILURE — `ERROR: [입력 확인] inventory_json[1] IP 가 중복됩니다: '10.100.64.161'` · 전송 없음 |
| 잘못된 IPv4 | #171 | FAILURE — `inventory_json[0] 유효하지 않은 IPv4 형식: '10.100.64.999'` |
| 계정 정보 든 callbackUrl | #172 | FAILURE — `callbackUrl 에 계정 정보(사용자:비밀번호@)를 넣을 수 없습니다 — 주소는 기록하지 않았습니다` · 콘솔에 계정 문자열 0회 |
| Redfish 10대 정상(운영 상한) | #173 | SUCCESS 6분 47초 — 7 success(Cisco `.2` 367 s · Dell 40~53 s · Lenovo 66 s) · `.1` PROTOCOL_CHECK_FAILED(Redfish 꺼짐) · `.3` · `.231` TARGET_UNREACHABLE — 명부와 같다. **150 s 를 넘는 정상 완료(F12 a)** |
| Linux 15대 큰 배치 | #174 | SUCCESS 1분 55초 — 12 success(Add-on 데이터 포함, `.161` raw 경로) · `.135 .145 .165` TARGET_UNREACHABLE — 명부와 같다 |

X9 실화면(#146~#157)은 문구 수정 전 후보의 기록이다(결과는 같다).

### 5-4. CI #21 (X10) — 실패와 원인

| 단계 | 결과 | 원인 · 조치 |
|---|---|---|
| Gate | FAIL | `ansible-playbook --syntax-check -i localhost,` rc 1 — F03 의 `unparsed_is_failed=True`(ansible.cfg)가 목록 인벤토리를 실패로 만들었다. 로컬 WSL 확인은 `/mnt/c` 가 world-writable 이라 저장소 ansible.cfg 를 무시해 통과했다 → X11 · X12 |
| Harness 22건 | FAILURE | CI 진행 중 X11 을 push 해 `MAIN_SHA != checkout`(설계된 보호). push 전 12건은 새 판정 기준으로 PASS(sink_5xx 포함) |
| Prodgen Verify G14 | FAIL | 새 시험 2개가 main 전용 `production_manifest.yml` 을 읽음 — `source_text` 누락(CI #17 과 같은 유형의 재발) → X12 |
| Prodgen Verify G15 | FAIL | 모듈 smoke(`ansible localhost -m …`)가 같은 설정으로 "No inventory was parsed" → X12: 설정을 Jenkins 수집 실행에만 |

X12 를 push 하기 전에 로컬에서 `prodgen build` + `verify --only G11,G12,G13,G14,G15` 를 돌려 G14(overlay 4,073 통과) · G15 PASS 를 먼저 확인했다(Windows 전용 인코딩 차이로 드러난 시험 1건도 고침).

### 5-5. CI #22 (X12) — SUCCESS

- 13 stage 전부 SUCCESS: Gate(4256 + 323 통과 · 3채널 syntax-check) · Finalize Corpus(Python · Groovy 18/18) · Budget · Harness Driver(main 18/18 — user_abort · aborted_outcome_finalize 는 ABORTED 기대 · 상한 모드 6/6, `inner_body_timeout` 포함) · Prodgen Build(194 파일, tree `1ad25d58…`) · Harness(prodtree) 10/10 · Drift · **Verify COMPLETE_PASS 20/20** · VAULT_DECRYPT · Evidence(46 항목 전부 PASS · 전부 direct 바인딩) · Promote dry-run(부모 P3 `915dec4e`, `require_bounded` = cli + ci_stage_results).
- `ci_stage_results.json`: `require_bounded: true` · 필수 stage 전부 PASS · `PROMOTE: DRY_RUN`.

### 5-6. main Job 핵심 12 시나리오 (X13, #231~#242 — 모두 checkout `1e15bf6f`, E2E-A2 는 수집 단계 없음 · SCM tip 전후 `1e15bf6f`)

| 시나리오 | 빌드 | 결과(기대) | 요지 |
|---|---|---|---|
| T2 빠른 실패 | #231 | SUCCESS | TEST-NET 2대 실패 결과 · Harness 수신기 200 |
| T5 사용자 중단 | #232 | ABORTED | 4대 실패 결과 전송(1/1) · `warnings: filled, outcome_aborted` |
| T6 전송 실패 | #233 | UNSTABLE | 408 ×3 · `callback_failed` · 본문 보존 |
| S5 Kernel 6.x | #234 | SUCCESS | `.37` · `.38` slot 1 × 4,096 MB · installed 4,096 · physical_installed · 오류 0 |
| S1 정상 | #235 | SUCCESS | Linux 3 + Windows `.120`, 4/4 · 오류 0 |
| S4 Windows | #236 | SUCCESS | `.120` 사용자 2명 · 오류 0 — X13 의 새 기록이 정상 경로에서 발동하지 않는다. users 는 X12 #192 와 같고(마지막 접속 시각 제외) system · storage 의 차이는 uptime · runtime · 파일시스템 사용량뿐 |
| S2 혼합 | #237 | SUCCESS | 4 success + TEST-NET 2 실패 진단 |
| E2E-A cj | #238 | UNSTABLE | `[실행 위치] cj · os → …`(Runner02 · 01 · 04) · 127.0.0.1:9 전송 거부(기대) |
| E2E-A2 chj | #239 | FAILURE | 미등록 Location `chj` · 2대 실패 결과 · 수집 단계 건너뜀 |
| E2E-D ESXi | #240 | SUCCESS | 6/6 |
| E2E-E Redfish | #241 | SUCCESS | Dell `.27` + Cisco `.2` 2/2 · dry-run |
| S3 강제 제한 | #242 | UNSTABLE | `[시험: 강제 제한 150초]` · 6 success + 1 합성 · `limit_reason=forced` |

### 5-7. CI #23 (X13) — SUCCESS

- 2026-10-05 19:27~20:05(37분 52초). 15 stage 전부 SUCCESS: Gate(Runner 에서 pytest 4,297 통과 · 건너뜀 134 · xfail 7, integration 323 통과, 3채널 syntax-check, `RESULT: PASS`) · Finalize Corpus(Python · Groovy 18/18) · Budget Self-test(17) · Harness Driver(main 18/18 — `user_abort` · `aborted_outcome_finalize` 는 ABORTED 기대 #431~#448 · 상한 모드 6/6 #449~#454) · Prodgen Build(194 파일, tree `1c16ca55…` — 로컬 build 와 같음) · Harness(prodtree) 10/10 #455~#464 · Drift · **Verify COMPLETE_PASS 20/20** · VAULT_DECRYPT · Evidence(46 항목 전부 PASS · 전부 direct 바인딩, main X13 12 시나리오 #231~#242 + E2E-A2 의 SCM tip 전후 관측) · Promote dry-run(부모 P3 `915dec4e`, `require_bounded` = cli + ci_stage_results).
- `ci_stage_results.json`: `main_sha 1e15bf6f…` · `require_bounded: true` · 필수 stage 전부 PASS · `PROMOTE: DRY_RUN`.

## 6. F07 — Runner 동시 실행 · Redfish 메모리

측정 방법: 노드를 지정한 관측 Job(`clovirone-server-gather-perf-observe`, `tests/jenkins/harness/perf_observe.py` — 2 s 간격으로 수집 프로세스 트리의 PSS · RSS · worker 수와 노드의 MemAvailable · swap 을 기록)을 Runner 4대에 먼저 띄우고 main Job 빌드를 동시에 실행했다. 모두 X12 `b33e278d`, 결과 전송은 `127.0.0.1:9`(Portal 로 보내지 않음 — UNSTABLE 은 기대값), Redfish 는 dry-run. 집계는 `tests/jenkins/harness/perf_observe_report.py`.

| 회차 | 빌드 | 배치 | 노드당 동시 수집 빌드 | 노드 PSS 합 최대 | MemAvailable 최소 (전체 7,680 MB) | swap 증가 |
|---|---|---|---|---|---|---|
| K=2 (Redfish 10대 × 2) | #199 · #200 | Runner01 · Runner02 로 분산 | 1 | 575 · 573 MB | 5,461 · 5,401 MB | 0 |
| K=12 혼합 (Linux 15 · Redfish 10 · ESXi 6, 각 4개) | #204~#215 | 노드마다 3개 | 3 (Runner01 · 02 · 04 는 시작 직후 정리 중이던 앞선 빌드 1개가 50~64 s 겹침) | 1,140 ~ 1,272 MB | 4,678 ~ 4,844 MB | 0 |

빌드 하나의 수집 트리 PSS 최대값과 worker 당 PSS(최대일 때 / 전체 최대 / 중앙값):

| 채널 | 트리 PSS 최대 | worker 당 PSS |
|---|---|---|
| Linux 15대 (forks 15) | 551 ~ 562 MB | 34 ~ 35 / 57 ~ 88 / 37 ~ 38 MB |
| Redfish 10대 (forks 10) | 496 ~ 575 MB | 62 ~ 64 / 81 ~ 86 / 78 ~ 84 MB |
| ESXi 6대 (forks 6) | 421 ~ 454 MB | 60 ~ 65 / 62 ~ 65 / 36 ~ 42 MB |

판정 (계획의 결정 규칙 — K≥3 에서 위험이 보이면 throttle):

- 노드당 3~4개가 겹쳐도 남은 메모리 최소 4.68 GB · swap 증가 0 이다. 위험이 보이지 않아 **throttle 은 켜지 않았다**(Jenkins 설정 변경 없음 — 두 수집 Job 의 throttle-concurrents 는 설치돼 있으나 비활성 그대로).
- 산술 여유: 빌드 하나가 최대 약 0.56 GB 를 쓰고 유휴 노드의 MemAvailable 이 약 6.0 GB 이므로, 한 노드에 무거운 빌드가 약 10개 겹치면 메모리가 모자랄 수 있다. 노드당 executor 는 15개다. 부하 분산은 12개를 노드마다 3개씩 나눴다.
- 그 수준의 동시 요청이 생길 수 있으면 두 수집 Job 에 throttle 카테고리(예: `clovirone-gather`, 노드당 6)를 켠다. 되돌리기는 Job 설정에서 끄면 된다(설정만 바뀌고 코드는 그대로). 설치 권장값으로 `docs/operate/04-pipeline-runtime.md` 7절(동시 실행과 메모리)에 적었다.
- 빌드 시작 때의 메모리 보호(`gather_budget.sh` 의 `mem_cap` — 그 시점 MemAvailable 기준)는 이번 측정에서 forks 를 줄이지 않았다(`mem_cap` 19~27 > forks 6~15). 같은 노드에서 늦게 시작한 빌드일수록 시작 시점 MemAvailable 이 낮아(6,080 → 4,436 MB) 몫도 작게 잡혔다 — 동시에 시작한 빌드끼리 몫이 겹치는 한계는 남아 있다.

**같은 BMC 에 대한 동시 요청 (관측)** — Runner 가 아니라 BMC 쪽 처리 한계다:

| 동시 빌드 수 | Cisco C220 CIMC `10.100.15.2` | Lenovo XCC `10.50.11.232` | Dell iDRAC 5대 | 빌드 결과 |
|---|---|---|---|---|
| 1 (#173) | 367 s · success | 66 s | 40 ~ 53 s | 7 success · 3 failed(명부와 같음) · 6분 47초 |
| 2 (#199 · #200) | 673 s · success | 95 ~ 98 s | — | 같음 · 12분 20초 |
| 4 (#205 · #208 · #211 · #214) | **1,245 ~ 1,253 s · partial** (thermal · network 30 s 응답 시간 초과, BIOS 는 마감으로 건너뜀) | 141 ~ 170 s | 64 ~ 104 s | 6 success · 1 partial · 3 failed · 22분 13~26초 |

- 4개 동시에서는 Redfish 수집 절대 상한(1,200 s, F12-3)이 Cisco 수집을 멈췄고, 결과는 부분 성공으로 보존됐다(요청 수 == 결과 수). 설계대로의 동작이다.
- 같은 BMC 를 여러 빌드가 동시에 요청하는 것은 운영에서 흔한 형태가 아니지만(중복 요청), 느린 BMC 는 부분 성공이 될 수 있다. 호출 측(Portal)의 같은 대상 중복 요청 정리를 NEXT_ACTIONS 에 남겼다.

## 7. 성능 — P3 ↔ X12

같은 대상 집합으로 production Job(P3 `915dec4e`)과 main Job(X12 `b33e278d`)을 채널마다 엄격히 교대로 5회씩 실행했다(채널끼리는 동시). 결과 전송은 Portal(운영과 같은 경로), Redfish 는 dry-run. 2026-10-05 18:01~19:13, 30 빌드 전부 SUCCESS · checkout 기대값과 일치. X13 은 Windows 실패 경로만 바꿨으므로(정상 경로 동작 동일) 이 비교를 그대로 쓴다.

| 채널 | P3 총 시간 중앙값 | X12 총 시간 중앙값 | 수집 단계 (P3 → X12) | 마무리 (P3 → X12) | host `duration_ms` 중앙값 | 성공/대상 |
|---|---|---|---|---|---|---|
| OS (Linux `.161` `.162` `.163` + Windows `.120`) | 154.0 s | 155.2 s (+1.1) | 141.6 → 142.0 s | 5.6 → 5.6 s | 17.2 → 17.1 s | 4/4 |
| ESXi 6대 | 72.5 s | 75.1 s (+2.6) | 60.2 → 61.6 s | 4.7 → 5.7 s | 39.2 → 39.8 s | 6/6 |
| Redfish 10대 (dry-run) | 400.4 s | 383.1 s (−17.3) | 388.9 → 368.1 s | 4.6 → 6.1 s | 45.0 → 42.8 s | 7/10 (2회 8/10 — 아래) |

- 판정: **명확한 퇴행 없음.** 총 시간 차이는 −4.3 % ~ +3.6 % 이고 회차 간 흩어짐(ESXi X12 67~78 s, P3 70~74 s) 안이다. 새 최적화는 넣지 않았다.
- 마무리 단계가 1.0~1.5 s 늘었다 — 결과 집계 · 요약 · 표시 단계(F13)의 몫으로 보이며 총 시간의 1~2 % 다.
- Redfish P3 5회차(#130)는 589 s 로 튀었다 — HPE iLO `10.50.11.231` 이 그 회차에만 닿아 응답 시간 초과로 562 s 동안 수집(partial)했기 때문이다. 중앙값에는 영향이 작다.
- **HPE `10.50.11.231` 은 Runner 망에서 간헐적으로 닿는다**(GP-37 의 새 근거): 10회 중 2회 — main #226(X12, Runner01) success 113 s(vendor 표시값 `hp`) · production #130(P3, Runner02) partial(firmware · power · thermal 응답 시간 초과). 같은 Runner01 의 다른 회차(#128)는 무응답이라 Runner 별 차이가 아니다. 이번 회차의 HPE 실장비 수집 사례이기도 하다.
- Cisco CIMC `.2` 는 매회 success, 338~368 s(단독 실행 — F07 의 동시 요청 지연과 대비).

## 8. 승격 · production 검증

### 8-1. 승격 X13 → P4

- 세션 CLI 1회(20:06~20:19): `python -m scripts.ai.prodgen promote --sha 1e15bf6f… --require-bounded --verify-report(CI #23) --e2e-evidence --ci-stage-results --netrc --vault-password-file --jenkins-url --ci-build #23 --push-remote origin,internal` → **COMPLETE_PASS → P4 `5ac5566c`**(부모 P3 `915dec4e`).
- 환경 의존 게이트 재실행 G11 G12 G13 G14 G15 G18 G19 G20 (G19 는 WSL 에서 고객사 main 형태 3채널 실제 실행) · 재사용 G01~G10 G16 G17.
- 게시: origin(GitHub) "accepted by remote" · internal(GitLab) "already at the new commit (reached via a shared push URL)" — 부분 게시 없음. `git ls-remote` 로 GitHub · GitLab · 로컬 production 모두 `5ac5566c` 확인.
- trailer: Main-SHA `1e15bf6f…` · Tree-Hash `1c16ca55…` · Previous-Production `915dec4e` · CI-Build #23 · Verdict COMPLETE_PASS · Gates-Rerun · Gates-Reused · E2E-Evidence-SHA256 · CI-Stages verified. 생성 tree 195 파일, 개발 경로(`.claude/` · `docs/ai/` · `scripts/ai/` · `tests/` · `CLAUDE.md` · `Jenkinsfile_ci`) 0.
- vault 암호 파일은 실행 동안만 0600 사본으로 만들고 끝나자 지웠다(값은 출력하지 않음).

### 8-2. production Job 검증 (P4)

2026-10-05 20:20~20:31, 승격 직후 시나리오 묶음(canary 먼저 — 실패하면 멈추고 복구 결정은 사용자). 결과 전송은 Portal(운영 경로) · 시험 수신기 · `127.0.0.1:9`(전송 실패 시험). Redfish 는 dry-run.

| 시나리오 | 빌드 | 결과(기대) | 요지 |
|---|---|---|---|
| CAN-1 canary | #131 | SUCCESS | Linux 3 → Portal 200 · 3/3 |
| S1 정상 | #132 | SUCCESS | Linux 3 + Windows `.120` 4/4 |
| S2 혼합 | #133 | SUCCESS | 4 success + TEST-NET 2 `TARGET_UNREACHABLE` |
| T2 빠른 실패 | #134 | SUCCESS | TEST-NET 2 실패 결과 · Harness 수신기 200 |
| T6 전송 실패 | #135 | UNSTABLE | 408 ×3 · `callback{delivered: false, attempts: 3}` · 본문 보존 |
| Linux A 8대 | #136 | SUCCESS | 8/8 — `.37` · `.38`(RHEL 10.2 · Kernel 6.12) 4,096 · `.96` 131,072 · `.95` 262,144 · `.156` 4,096 · `.161~.163` 8,192 MB, 모두 physical_installed · 오류 0 (Kernel 6.x 행렬과 같다) |
| Linux B 7대 | #137 | SUCCESS | Runner 4대 `.33~.36` success + `.135 .145 .165` `TARGET_UNREACHABLE`(명부와 같음, GP-37) |
| Windows | #138 | SUCCESS | `.120` 1/1 |
| ESXi 6대 | #139 | SUCCESS | 6/6 |
| Redfish 10대 | #140 | SUCCESS | 7 success · `.1` `PROTOCOL_CHECK_FAILED`(Redfish 꺼짐) · `.3` · `.231` `TARGET_UNREACHABLE`(명부와 같음) |
| S3 강제 제한 | #141 | UNSTABLE | `[시험: 강제 제한 150초]` · 6 success + Cisco `.2` 합성 실패 · `limit_reason=forced` · 전송 200 |
| 중복 IP | #142 | FAILURE | `[입력 확인] inventory_json[1] IP 가 중복됩니다: '10.100.64.161'` · 접수 manifest 없음 → 전송 없음 |

- 모든 빌드의 checkout == P4 `5ac5566c`(중복 IP 는 입력 확인에서 끝나 checkout 이 없다 — 기대값). 빌드 이름에 대상 수가 나온다(`#131 os 3대`).
- 결과는 main X13(#231~#242)과 같은 모양이다. 명부 전 채널: Linux 15(A 8 + B 7) · Windows 1 · ESXi 6 · Redfish 10 — 성공 26/32, 미해결 6건은 명부와 같은 상태(GP-37).

## 9. 운영 화면 (F13 · §6) — 판정과 실제 화면

### 9-1. 판정표 (수정 / 명확해서 유지 / 외부 원문 유지)

| 범위 | 판정 | 내용 |
|---|---|---|
| 단계 표시 이름 | 수정 | Validate → 입력 확인 · Resolve Location → 실행 위치 확인 · Gather → 서버 정보 수집 · post 안의 표시 단계 결과 확인 및 전송(finalizer 는 그 안에서 한 번) |
| sh label 7개 | 수정 | 결과 정리 (Layer A) · 이전 실행의 결과 파일 정리 · 수집 시간 계산 (예상) · 추가 수집(Add-on) 저장소 받기 · 추가 수집(Add-on) 파일 검사 · 수집 시간 계산 (실행 직전) · 서버 정보 수집 (ansible-playbook) |
| 콘솔 태그 | 수정 | `[입력 확인]` `[실행 위치]` `[수집]` `[시간]` `[결과 보존]` `[마무리]` `[Portal 전송]` `[결과]` `[경고]` `[결과 파일]` `[단계 상한]` `[요약]` |
| 결과 집계 | 수정 | `[결과] 요청 N대 — 성공 · 부분 성공 · 실패` 는 보낸 envelope 의 status 를 직접 센다. 실패 결과를 새로 만든 수 · CHECKPOINT 로 보낸 수는 줄을 나눈다 |
| 경고 | 수정 | 실제로 생긴 조건만 한 줄에 하나(`[경고]`), UNSTABLE 은 한 번. 결과 보존 경고는 수집 단계가 이미 표시하므로 목록에만 |
| 결과 파일 링크 | 신규 | 보존에 성공한 파일만: 서버별 수집 결과(JSONL) · Portal 로 보낸 본문 · 실행 요약 |
| 빌드 이름 | 신규 | `#N <대상 종류> N대` + 시험 표시 `[시험: 강제 제한 N초]` · `[시험: 계정 복구 모의]` |
| 파라미터 설명 | 수정 | 시험 전용 파라미터를 "시험 전용 — 운영은 비워 두세요/false" 로 |
| Portal 전송 줄 | 수정 | `[Portal 전송] 완료: HTTP 200 (1/3번째 시도)` · 실패 시 사유. 요청 도구의 요청 · 응답 출력은 끔(quiet). 연결 실패를 도구가 408 로 돌려주는 경우 그 뜻을 덧붙인다(`444db56e`) |
| `[Trusted]` · `[Budget] est/exec` | 명확해서 유지 | 기계 표식(승격 증거가 `[Trusted]` 를 정규식으로 읽는다) · 상세 수치. 사람이 읽는 시간 줄 `[시간]` 을 따로 추가 |
| `[addon]` · `[venv]` | 외부 원문 유지 | `scripts/addon_checkout.sh` · `activate_ansible_venv.sh` 출력과 같은 태그(문장은 이미 한국어) |
| Ansible task 이름 | 유지 | `channel \| area \| action` 형식 일관, json_only 가 콘솔에 내보내지 않음, 시험 28개 의존 |
| `errors[].message` | 유지 | `failure_reasons.yml` · `section_messages.yml` 카탈로그가 관리 |
| `[finalize]`(Layer A stderr) | 유지 | 기술 정보 한 줄 — 사람이 읽는 줄은 `[결과 보존]` |
| Ansible `[WARNING]` · Jenkins `Running on` | 외부 원문 유지 | 도구 원문 |
| CI · Harness · prodgen 출력 | 유지 | 개발자용, 의미 명확 |

### 9-2. 실제 화면 (main X10)

- Stage View(`wfapi`) #162: 입력 확인 · 실행 위치 확인 · 서버 정보 수집 · Declarative: Post Actions(Jenkins 고유) · 결과 확인 및 전송 — 모두 SUCCESS. #169(S3): 서버 정보 수집 · 결과 확인 및 전송 UNSTABLE. #166(chj): 실행 위치 확인 FAILURE · 서버 정보 수집 건너뜀 · 결과 확인 및 전송 UNSTABLE(전송 실패).
- Blue Ocean(REST `…/runs/162/nodes/`): 입력 확인 · 실행 위치 확인 · 서버 정보 수집 · 결과 확인 및 전송 4단계.
- 빌드 이름: `#162 os 4대` · `#169 redfish 7대 [시험: 강제 제한 150초] [시험: 계정 복구 모의]`.
- 콘솔 예(#146, X9 — 문구 수정 전 후보): `[입력 확인] 통과 — os 2대, 실행 위치 git` → `[실행 위치] git · os → 노드 라벨 …` → `[시간] 예상 600초 · 중단 기준 …` → `[결과 보존] …` → `[마무리] 처리 경로: …` → `[Portal 전송] 완료: HTTP 200 (1/3번째 시도)` → `[결과] 요청 2대 — 성공 0 · 부분 성공 0 · 실패 2` → `[결과 파일] …/artifact/gather_final.jsonl` → `[요약] …`.
- X9 실화면에서 찾아 X10 에서 고친 것(`444db56e`): 연결 거부가 `HTTP 408` 로만 보임 · `[시간]` · `[결과 보존]` 줄의 겹친 괄호 · `[요약]` 영문 소요 시간(`… sec and counting`) · 시작 전 종료를 "알 수 없는 이유로 중단" 으로 적던 문구.

## 10. 예외 무시 지점 감사 (지시서 §5 — Windows · ESXi)

방법: Windows 수집 태스크 8개 · ESXi 수집 태스크 · `esxi_disks.py` · `precheck_bundle.py`(Windows · ESXi 분기)의 `catch {}` · `SilentlyContinue` · `failed_when: false` · `except … pass` 를 전수 분류했다(읽기 전용 감사, 81개 지점). 분류: **A** = 실패가 다른 경로로 errors[] 나 섹션 실패에 드러남, **B** = 숨어도 nice 또는 계약 밖 필드이거나 정리(cleanup)뿐, **C** = 필수(must) 데이터의 실패가 기록 없이 숨음.

| 범위 | 지점 | A | B | C |
|---|---:|---:|---:|---:|
| Windows 태스크 | 50 | 14 | 26 | 10 |
| Windows 인접(`os-gather/site.yml` · `try_one_credential.yml`) | 2 | 1 | 0 | 1 |
| ESXi 태스크 | 10 | 5 | 4 | 1 |
| `esxi_disks.py` | 10 | 3 | 6 | 1 |
| `precheck_bundle.py` | 9 | 6 | 3 | 0 |
| 합계 | 81 | 29 | 39 | 13 (원인 8개) |

C 원인 8개와 처리:

| # | 지점 | 숨던 것 | 처리 |
|---|---|---|---|
| C-1 | `gather_users` 목록 조회 catch | 한 명도 못 읽으면 "미지원"(종료 코드 1), 일부만 읽으면 잘린 목록이 "성공" — 둘 다 기록 없음. `users[]` 는 must | **X13 수정** — 실패 표식 줄 → 0명이면 섹션 실패 + 오류 1건, 일부면 성공 + 부분 오류 1건. 명령 자체가 없을 때(F23)만 종전처럼 미지원 |
| C-2 | `gather_users` 그룹 조회 | 그룹 조회가 실패하면 관리자 그룹으로만 남기는 내장 계정(Administrator)이 목록에서 조용히 빠짐 | **X13 수정** — 섹션은 성공 그대로 + 오류 1건(detail 에 실패한 그룹 이름 `groups=…` · `effect=builtin_admin_may_be_omitted`) |
| C-3 | `gather_system` 구성요소 · 스크립트 실패 | setup fact 로 섹션은 성공하는데 `hosting_type`(must) `unknown` · vendor null 이 기록 없이 나감 | **X13 수정** — 실패한 구성요소를 모아 오류 1건(섹션 상태는 그대로, 시나리오 B) |
| C-4 | `gather_system` vmms 서비스 조회 | 서비스 부재와 조회 실패를 같게 봐 Hyper-V 호스트에서 조회가 실패하면 `virtual` | 기록만 — 로컬 서비스 조회 실패라 발생 가능성 낮음 · NEXT_ACTIONS |
| C-5 | `gather_network` Get-NetAdapter | 실패하면 모든 인터페이스 `link_status`(must) `unknown` · mac 등 null, 기록 없음 | 기록만 — 발생 가능성 낮음 · NEXT_ACTIONS |
| C-6 | `gather_storage` Win32_DiskDrive 조회 | 볼륨만 읽혀도 섹션 성공 → `physical_disks`(must)가 비거나 모자라도 기록 없음. 기존 시험이 이 동작을 고정하고 있었다 | **X13 수정** — 디스크 쪽 구성요소 실패를 오류 1건(실패 구성요소 · 남은 디스크 수) |
| C-7 | ESXi `collect_disks` 태스크 실패 | 모듈 고유 키가 없는 태스크 실패(모듈 traceback 등)면 디스크 실패 흔적이 없음 | 기록만 — 이론적(그 전에 community.vmware 가 먼저 실패) · NEXT_ACTIONS |
| C-8 | Windows `setup` 실패(`os-gather/site.yml`) | `memory.visible_mb`(must)가 null 인데 기록 없음(식별자 진단 오류는 나지만 원인을 권한으로 적는다) | 기록만 — 발생 가능성 낮음 · NEXT_ACTIONS |

B 중 must 필드를 건드리는 경계 3건 — `gather_hardware` SKU(대체 값도 비었을 때만 null), `gather_hardware` 부분 실패 때의 vendor · model, `gather_system` fqdn(`ansible_fqdn` 대체, null 도 정상값) — 은 그대로 뒀다.

수정 중 추가로 확인한 것(실측):

- **실제 `Get-CimInstance` 실패는 비종료 오류다.** 잘못된 클래스 · 네임스페이스로 이 PC 의 Windows PowerShell 5.1 에서 확인했다: try/catch 로 잡히지 않고 결과 0건, `-ErrorVariable` 에는 CimException 1건. 기존 시험의 가짜 cmdlet 은 종료 오류만 냈기 때문에 이 차이가 드러나지 않았다 → 공용 조회 3개(`read_operating_system` · `read_computer_system` · `read_disk_drives`)가 `-ErrorVariable` 로 받아 결과는 그대로 두고 구성요소만 실패로 표시한다(C-3 · C-6 의 실제 실패 경로). 같은 이유로 memory · network 의 공용 조회 실패 검사도 발동하지 않지만, 두 섹션은 다른 경로(설치 용량 없음 · 인터페이스 없음)로 실패가 드러나는 A 분류라 바꾸지 않았다.
- **users 의 F23(명령 부재)**: 종전 스크립트는 빈 catch 뒤 종료 코드 1 로 끝나 "미지원"이 됐다. 새 스크립트는 끝에 표식을 출력해 종료 코드가 0 이 되므로 F23 이 "성공 + 빈 목록"으로 바뀌는 회귀가 생겼다 — 실제 powershell.exe 대조에서 찾았다. 명령 부재(CommandNotFoundException)만 종전처럼 종료 코드 1 로 끝낸다.
- **볼륨(Get-Volume) 실패**도 디스크만 읽히면 섹션이 성공한다. `storage.filesystems` 는 field_dictionary 에 없는 필드(계약 밖)라 고치지 않고 NEXT_ACTIONS 에 남겼다.

시험: `tests/unit/test_windows_hidden_failures.py`(새로 — Jinja 체인은 모든 플랫폼, 실제 powershell.exe 시나리오는 Windows 호스트). users 9 시나리오(정상 · 목록 일부/전부 실패 · 그룹 조회 실패 3종 · Win32 경로 정상/실패 · 명령 부재)에서 표식 · 섹션 상태 · 오류 · 종료 코드를 보고, 사용자 데이터가 종전 스크립트와 같음을 확인한다. system · storage 는 종료 · 비종료 오류 모두. 기존 통합 동치 시험 2개는 의도한 차이(추가 오류)만 기대값에 넣었다. 변이 검사: 종전 users 파일 또는 `-ErrorVariable` 을 뺀 스크립트로 바꾸면 새 시험이 실패한다.

## 11. 정확성 범위 — 영역별 (지시서 §5)

Linux 항목별 세부(명령 · task 라인 · Kernel 6.12/6.8 판정)는 `2026-10-04-kernel6x-compat-matrix.md` 가 정본이다. 이 표는 영역마다 코드 경로 · 회귀 시험 · 이번 회차 실장비 근거 · 확인하지 못한 범위만 모은다.

| 영역 | 코드 경로 | 회귀 시험(대표) | 실장비 근거 (이번 회차) | 확인하지 못한 범위 |
|---|---|---|---|---|
| Linux Memory | `os-gather/tasks/linux/gather_system.yml` DMI 수집 · `gather_memory.yml` 파서 | `test_linux_memory_parser.py`, raw 경로 시험 | S5 #190: `.37` · `.38` RHEL 10.2 · Kernel 6.12 — DIMM slot 1 · 4,096 MB · physical_installed · 오류 0 (원문 `Size: 4 GiB` 대조는 2026-10-04 main #20, 행렬 §2) · Linux 15대 #174 | 6.12 베어메탈(다수 DIMM) 미보유 — 6.8 R760 베어메탈은 행렬 §2 |
| Linux CPU | `gather_cpu.yml`(cpuinfo · lscpu · cpufreq · SMBIOS Type 4) | `test_cpu_filter_b01.py`, 행렬 §2 의 fixture | S1 · S5 · #174 | cpufreq 노드 유무(관측 불가, 최종 값은 타당) |
| Linux Storage | `gather_storage.yml`(lsblk · udevadm · lspci · df) | `test_linux_storage_markers.py` | #174 | multipath · RAID 심화 · 디스크 health — 수집 경로 없음(계약 밖) |
| Linux Network | `gather_network.yml`(ip · sysfs · bonding · vlan) | `test_os_network_render.py`, `test_network_*` | #174 | 6.12 `ethtool -i` firmware-version(행렬 §2) |
| HBA · FC · WWPN · IB | Linux `gather_hba_ib.yml` · Windows Get-InitiatorPort/MSFC · ESXi `esxi_disks.py` | `test_hba_ib_canonical.py`, `test_linux_hba_ib_markers.py`, `test_fcoe_cna_not_fc_hba.py` | 장치 부재(사내 대상에 FC HBA · IB 없음) — 빈 값 · 오류 0 | 실제 FC HBA · IB 장치 — lab 부재 |
| Windows | `os-gather/tasks/windows/*.yml`(합친 스크립트 + Jinja) | `test_windows_*` 10개(실제 powershell.exe 실행 포함) · `test_windows_hidden_failures.py` | S4 #192 · S1 #191: `.120` Server 2022 | Server 2016 · 2019, 물리 서버, 도메인 컨트롤러, Server Core — 미보유 |
| ESXi | `esxi-gather`(community.vmware · `esxi_disks.py`) | `test_esxi_*` 8개 | E2E-D #196: 6대 6/6 | 명부 밖 버전 · 물리 HBA |
| Redfish | `redfish_gather.py` · `adapters/redfish/*.yml` | `test_redfish_*` 30개, 실장비 녹화 재생(Dell · HPE 2 · Lenovo 요청 수 동일 — §3) | #173: Dell 5 · Lenovo 1 · Cisco 1 success, `.1` Redfish 꺼짐 · `.3` · `.231` 무응답(명부와 같음) · E2E-E #197 dry-run | HPE 실장비(`.231`)는 Runner 망에서 간헐적 — 성능 비교 10회 중 2회 닿음(main #226 success · production #130 partial, §7), Supermicro · Huawei · Inspur · Fujitsu · Quanta — lab 부재 |
| 공통 정규화 · 결과 보존 | `common/tasks/normalize/*`, `callback_plugins/json_only.py`, Layer A · B | `test_envelope_*`, `test_callback_envelope_reconcile.py`, corpus 18/18 | 모든 빌드에서 요청 수 == 결과 수, T5 중단 · S3 강제 제한 · T6 전송 실패 | 런타임 장애 주입은 금지라 CHECKPOINT 뒤 OUTPUT 실패는 단위 · Driver 시험으로만(F01) |
| Add-on | `common/tasks/addon/run_addon.yml`, `scripts/addon_checkout.sh` | `test_addon_*` 4개, `test_env_guard.py`(실제 `scripts/env_guard.sh` 를 bash 로 source) | S1 #191: Linux 3대 `swList` · `dbIpList`, Windows `.120` `swList` · 오류 0 · #174 Linux 15대 | Add-on 내부 실패 경로(checkout · layout 실패 · 채널 미지원)는 단위 시험으로만 |

## 12. 지시서 §8 완료 조건 대응

| # | 조건 | 결과 | 근거 |
|---|---|---|---|
| 1 | 결함 수정 · 회귀 | F01~F06 · F08 · F09 · F12 · F13 수정, §5 감사 C 4건 수정(X13). 로컬 4,411 + 308 통과 · CI #23 SUCCESS | §1 · §2 · §3 · §5 |
| 2 | Kernel 6.x 재검증 | `.37` · `.38`(RHEL 10.2 · 6.12) DIMM slot 1 · 4,096 MB · physical_installed · 오류 0 — X12 #190 · X13 #234 · production #136. 원문 대조는 2026-10-04 main #20(`Size: 4 GiB`) | §5 · §11 |
| 3 | 명부 전 채널 | main: Linux 15(#174) · Windows(#191 · #192) · ESXi 6(#196) · Redfish 10(#173) · production P4: Linux A 8/8(#136) · Linux B 4 + 무응답 3(#137) · Windows(#138) · ESXi 6/6(#139) · Redfish 10: 7 + 실패 3(#140). 미해결 6건은 명부와 같은 상태(GP-37, 자산 결정은 사용자) | §5 · §8 |
| 4 | 느린 정상 · 정체 · 취소 · 보존 · Callback | (a) Redfish 10대 정상 6분 47초(#173, 예상 905 s · 강제 없음) (b) `test_redfish_progress_deadline.py`(축소 시간: 느리지만 계속 오는 BMC 는 옛 마감을 넘겨 수집 · 무응답 BMC 는 무응답 상한에서 멈춤) (c) `test_gather_watch.py`(한 대상만 멈춘 경우 · 진행 이벤트 · GNU timeout 배선으로 멈춘 실행 정지) (d)(e) 원격 timeout 실측 §4-1 (f) T5 사용자 중단 ABORTED + 결과 전송 (g) `test_env_guard.py`(상위 환경 시험값을 실제 bash 에서 지움) · 보존 S3 강제 제한 · 전송 실패 T6. 계획의 Harness `env_guard` · `watch_stub` 시나리오 대신 실제 스크립트를 실행하는 단위 시험으로 검증했다(CI Gate 가 Runner bash 에서도 실행) | §4 · §5 |
| 5 | Portal | **사용자 결정 — HTTP 2xx 수신까지가 계약**(응답 본문 미판독). 저장 · 반영 확인은 이 Job 의 역할 밖 | §0 · GP-42 |
| 6 | CI · Harness · tree 정합 | CI #23 SUCCESS — 필수 stage 전부 PASS(HARNESS_BOUNDED · VAULT_DECRYPT 포함) · Harness main 18/18 · 상한 6/6 · 생성 tree 10/10 · Verify COMPLETE_PASS 20/20 · 생성 tree `1c16ca55…` = P4 Tree-Hash | §5 |
| 7 | 고객사 main-only | CI G19(고객사 main 형태 3채널 실행) PASS(CI #23 · 승격 때 WSL 재실행 PASS) + production Job 실수집(같은 tree). 고객사 실환경 수집은 이번 범위 밖 | §5 · §8 |
| 8 | 양 원격 main · production | production: GitHub · GitLab · 로컬 = P4 `5ac5566c`. main: X13 `1e15bf6f` 뒤 7차 문서 커밋(runtime 변경 없음 — production tree 불변)을 push 하고 양 원격을 `git ls-remote` 로 확인 | §8 |
| 9 | 원격 production 으로 검증 | production Job 12 빌드 #131~#142 전부 기대 결과 · checkout `5ac5566c` (§8-2) | §8 |
| 10 | 문서 · 정리 · push | 문서 커밋 7차 문서 커밋(CURRENT_STATE · TEST_HISTORY · decision-log · NEXT_ACTIONS · FAILURE_PATTERNS · 운영 · 계약 문서 · 이 evidence) · 세션 임시 자원 정리(§13) | §13 |
| 11 | 시험 제한의 운영 유입 차단 | F05 환경 경계(`scripts/env_guard.sh`) · 시험 표시(`[시험: 강제 제한 150초]`) · `test_env_guard.py`. 2026-10-05 Jenkins 확인: 전역 환경변수는 `ADDON_REPO_URL` · `SE_FINALIZER_BOUNDED=true` 둘뿐, Runner 노드 환경변수 0 | §1 · §5 |
| 12 | 로그 · 이름 · 결과 접근 | 단계 표시 이름 · `[결과]` · `[경고]` · `[결과 파일]` · `[요약]` · 빌드 이름 — 실화면 §9 | §9 |

## 13. 세션 임시 자원 정리 (2026-10-05)

| 자원 | 처리 |
|---|---|
| 세션 Jenkins API 토큰 파일(netrc) · Runner SSH 비밀번호 파일 | 작업 PC scratchpad 에서 삭제(마지막 Jenkins · SSH 사용 뒤). Jenkins 에 등록된 API 토큰 2개 · CI 폴더 자격은 사용자 결정(GP-26)대로 유지 |
| vault 암호 사본 | 승격 래퍼가 실행 동안만 0600 사본을 만들고 끝나자 삭제(`vault_removed=yes`). WSL 사본 0 |
| WSL `/tmp` 시험 산출물 | 원격 timeout 관측 로그 · 보고, syntax-check 로그, prodgen 게이트 작업 디렉터리 삭제(pytest 자체 임시 폴더만 남김) |
| Runner01~04 `/tmp` | 샘플러 파일 0 · 프로세스 0(GP-43, 읽기 전용 확인) |
| 원격 대상 `.161` · `.120` | 원격 timeout 시험의 표식 프로세스 정리 뒤 0(§4-1) |
| Jenkins 빌드 · 대기열 | 실행 중 0 · 대기 0(Harness 수신기는 시나리오 묶음 끝에 중단) |
| Jenkins 설정 | 이번 차수 변경 없음 — 전역 환경변수 `ADDON_REPO_URL` · `SE_FINALIZER_BOUNDED=true` 그대로, 노드 환경변수 0, throttle 비활성 그대로, Runner01/02/04 `cj` 라벨 그대로(GP-38) |
| 진단 Job(perf-observe · net-probe · term-probe) | 유지 — 운영 문서(`docs/operate/03-job-registration.md`)에 등록된 main 전용 진단 Job |
| 사용자 자료 `REDFISH_BIOS_GATHERING_PLAN_MODE_PACKAGE_00-11_2026-09-14/` | 손대지 않음(추적 안 함) |
