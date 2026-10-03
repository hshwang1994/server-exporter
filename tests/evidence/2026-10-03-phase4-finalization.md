# 2026-10-03 — Gathering 개선 Phase 4: 시간 예산 · 마무리(finalization) · Callback · task timeout · 인증 증거

> 승인 Plan §6 (D1~D8) · §6-2 · §6-3 · §6-4 · §6-5 · 부록 G-4 의 구현 증거. **오프라인 검증만** — Jenkins 실제 빌드(§10-4 #1~#12 live 열) ·
> 실장비 · BMC 는 권한 차단으로 실행하지 못했다 (`docs/ai/NEXT_ACTIONS.md` GP-1~GP-5). 코드 수준 완료이고 실환경 수준은 미검증이다.
> 커밋: `5c2c8839` (feat), 선행 `4fe9712a`(Linux C1/C2/C7) · `954b1b0c`(ESXi P5). 결정 요약: `docs/reference/decision-log.md` 2026-10-03 (Phase 2~4).

## 1. 무엇을 만들었나 (Plan 항목 ↔ 파일)

| Plan | 구현 | 파일 |
|---|---|---|
| D1 배치 제한 = 셸 `timeout --signal=INT --kill-after=90`, 집행 예산은 ansible 직전 재계산 | `[Budget] est=`(node 진입) / `[Budget] exec=`(sh 직전) 두 번 계산, rc → outcome(0/2/4/8 completed · 124 timeout · 137 timeout_killed · 90 prep_failed · 그 밖 failed_run), 120 s 미만이면 `not_started_budget` | `Jenkinsfile_portal` Gather, `scripts/gather_budget.sh` |
| D2 마무리는 pipeline `post { always }`, 합산 제한 720 s | `timeout(FINALIZER_TOTAL){ node('built-in') }` 하나, node 진입 뒤 남은 시간 재계산, 단축 사다리(Layer A 생략 → unarchive 생략 → 시도 축소 → 미시도 기록) | `Jenkinsfile_portal` `seFinalizeAndCallback()` |
| D3 2계층 마무리 | Layer A `scripts/finalize_gather_output.py`(exit 0/2/3, `gather_final.jsonl` + `gather_finalize_report.json`), Layer B `@NonCPS seReconcileRaw`(OUTPUT → CHECKPOINT+오류 1건 → 합성) | `scripts/finalize_gather_output.py`, `Jenkinsfile_portal` |
| D4 콜백 진행·checkpoint 파일 | `ANSIBLE_JSON_PROGRESS_FILE`(host 당 append 이벤트) · `ANSIBLE_JSON_CHECKPOINT_FILE`(CHECKPOINT 태스크 msg) · `ANSIBLE_JSON_MANIFEST_FILE`(inventory 대조) · OUTPUT/CHECKPOINT flush+fsync | `callback_plugins/json_only.py` |
| D5 agent 없는 Validate/Resolve, Validate Schema 제거 | Phase 1.5 에서 입구를 바꿨고 이번에 `Validate Schema` · `Callback` stage 삭제, Runner 부재는 `no_agent` 접수 후 실패 | `Jenkinsfile_portal` |
| D6 예산 상수 한 곳 | GLOBAL 9000 · RESERVE 990 · STAGE_LIMIT 6900 · GRACE 90 · POST 180 · BASE 300 · MIN 600 · CAP 5400 · MIN_START 120 · host_cap os/esxi 240 · redfish 후보×(540+65)(+240) · forks 규칙 | `scripts/gather_budget.sh`(정본), `seConstants()`(Groovy 상수) |
| D7 task `timeout` + 모듈 `deadline` + 인증 증거 side-channel | Linux 120 · 자격 probe 60(+`ansible_timeout: 15`) · precheck 120 · ESXi 180 · redfish detect 120/collect 600/account 240 (deadline 90/540/180); `attempt` 모듈 인자 → `<SE_AUTH_EVIDENCE_DIR>/<ip>/<attempt_id>.json`; rescue 3분류(`parse_auth_evidence` 필터) | `os-gather/tasks/**`, `common/tasks/precheck/run_precheck.yml`, `esxi-gather/tasks/*.yml`, `redfish-gather/tasks/*.yml`, `redfish-gather/library/redfish_gather.py`, `filter_plugins/auth_evidence.py`, `redfish-gather/site.yml` rescue |
| D8 조립 → CHECKPOINT → Add-on → 결합 → OUTPUT | 4 play 재배치, `run_addon.yml` 은 `_output` 의 data.addon · errors[] · meta 시각에만 결합, `ADDON_START`/`ADDON_DONE` 마커, `include_role apply: timeout`(기본 300) | `os-gather/site.yml`, `esxi-gather/site.yml`, `redfish-gather/site.yml`, `common/tasks/addon/run_addon.yml` |

Windows win_shell 180 s 는 P4(win_shell 통합) 작업과 충돌을 피하려고 미적용 — `tests/unit/test_remote_task_timeouts.py` 가 strict xfail 로 추적한다.

## 2. 검증 (오프라인)

| 검증 | 결과 |
|---|---|
| Jenkins 선언형 린터 (jenkins-prod 2.528.3) | `Jenkinsfile successfully validated.` (Phase 4 최종본) |
| Jenkinsfile 계약 테스트 4 파일 (`test_jenkinsfile_portal_{finalize,agent_label,addon,preserve_and_params}.py`) | 통과 — 구조(stage 3 + post), 회수 순서, Callback 규칙, 예산 스크립트 2회 호출, rc 매핑, post 순서, no_agent, fallback canon drift(YAML/Layer A/budget) |
| `tests/unit/test_finalize_gather_output.py` 13 · `test_gather_budget.py` 8 · `test_callback_progress_manifest.py` 6 | 통과 |
| `tests/unit/test_addon_hook_contract.py` 46 | 통과 — CHECKPOINT 위치 · hook 마지막 · 결합 범위 · 태스크별 timeout 하나 · 마커 이름 |
| `tests/integration/test_addon_hook_playbook.py` (WSL ansible-core 2.20.7) 14 | 통과 — checkpoint 줄 = hook 없는 OUTPUT, 진행 이벤트 순서, meta 시각 갱신, `sleep 40` 이 `apply.timeout 3` 에 끊겨 rescue → errors[] 1건, 연결 끊김 host 유지 |
| `tests/unit/test_remote_task_timeouts.py` | 23 passed · 8 xfailed(Windows 대기) — Linux/probe/precheck/ESXi/Redfish 값과 deadline < timeout |
| `tests/unit/test_redfish_auth_evidence.py` 18 · `tests/e2e/test_redfish_timeout_auth_classification.py` 18 | 통과 — 파일 초기화 · 첫 응답 1회 · 익명 구분 · throttle · 원자적 쓰기 · 비밀값 0 · 식별자 불일치 · A401→B200/B정지 · 복구 시도 정지 · recovery 미진입 구조 |
| WSL `ansible-playbook --syntax-check` 3채널 · `pre_commit_jinja_compile_check.py --all` | 통과 |
| WSL `pytest tests/unit` / `tests/e2e` | 2730 passed(+ Windows P4 진행 중 파일 1 failed) / 761 passed |
| Windows `pytest` 단위 묶음(evidence · addon · Jenkinsfile · finalize · budget · redfish phase2/3 · account · esxi reuse) | 243 passed |

## 3. Astra 3차 acceptance 대응

- **수집 직전 예산 재계산**: `seBudget` 역할은 `scripts/gather_budget.sh`(시각 입력만의 순수 계산)이며 Jenkinsfile 이 node 진입 시(est)와 `sh` 직전(exec) 두 번 부른다. 테스트 `test_gather_budget.py` 가 긴 대기 뒤 준비 지연으로 est ≥ MIN_START 인데 exec < MIN_START 가 되는 경우, stage 잔여 항이 최소가 되는 경우, force 가 네 항을 넘지 못하는 경우를 포함한다. live `[Budget] est/exec` 타임스탬프 확인은 미실행.
- **인증 증거 시도별 격리**: attempt 파일 `<ip>/<attempt_id>.json`, 시작 시 초기화, build/event/ip/attempt 대조, anonymous 구분, 현재 attempt 파일만 분류에 사용, 과거 401 은 이력, 표준 timeout 시 recovery 미진입 — 위 36 테스트.

## 4. 미실행 · 한계

- §10-4 live 열 전부(두 Job 실제 빌드, Abort, Agent 단절, Callback sink, 예산 소진 타임스탬프) — 권한 차단. 오프라인으로 대체한 항목은 위 표.
- WSL 실측은 ansible-core 2.20.7 이고 Runner 는 2.20.3 — apply.timeout · task timeout 동작은 Runner 에서 재확인해야 한다(§6-7 (7)).
- Add-on 태스크 timeout 이 끊은 원격 자식 프로세스는 남을 수 있다(WSL 실측 한계 그대로).
- Layer B(Groovy)는 Jenkins 에서만 실행되므로 Python/Groovy 동치는 corpus self-test(Phase 6 `Jenkinsfile_ci`)로 검증한다 — 아직 Job 미등록.
