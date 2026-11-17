# 2026-11-17 — Job 이름의 공백 때문에 `--limit` 파일을 찾지 못해 모든 대상이 실패 (검증 기록)

> 누가: 사용자가 Jenkins 콘솔 로그를 붙여 원인을 물었다(2026-11-17 대화). AI 가 원인 분석 · 수정 · 검증 · 긴급 승격을 했다. 계획과 승격 방식("긴급 승격")은 같은 대화에서 사용자가 정했다.
> 언제: 2026-11-17. 무엇: 코드 · 시험 커밋 `8249f79a`, production `ce1647c7`. 결정 근거: `docs/reference/decision-log.md` 2026-11-17.
> **실장비 범위**: 실장비 확인은 production Job canary #334 하나다(lab OS 11대, Job 이름에 공백 없음). 공백이 든 작업 폴더는 WSL 의 실제 Ansible 로 재현했다.
> 공백이 든 Job 을 실제 Jenkins 에서 다시 돌리는 일은 사용자 몫이다.

## 1. 사이트 관측 (사용자가 붙여 넣은 콘솔)

| 항목 | 내용 |
|---|---|
| Job · 빌드 | `DAY_1/git/os 게더링 소연` #1 (이 Job 의 첫 빌드) · OS 244대 · `loc=git` |
| 작업 폴더 | `/home/cloviradmin/jenkins-agent/os 게더링 소연-1` |
| 오류 | `[ERROR]: Unable to find limit file b'/home/cloviradmin/jenkins-agent/os'` — ansible rc 1 · 1초. 다른 오류 없음 |
| 결과 | 244대 모두 `failure_stage=fallback` · `OUTPUT_BUILD_FAILED` · "개더링 프로젝트에서 수집 결과를 만들지 못했습니다."(`details.outcome=failed_run`) · Portal 전송 · 빌드 UNSTABLE |

## 2. 원인

1. `Jenkinsfile_portal` 은 `ws("${env.JOB_BASE_NAME}-${env.BUILD_NUMBER}")` 로 작업 폴더를 잡는다. 상대 경로라 Jenkins 는 노드 root(Agent remote root) 아래에 만든다.
2. `scripts/run_gather.sh` 는 `--limit "@$WS/.gather_limit_hosts"` 를 넘겼다. 셸에서는 인자 하나다.
3. Ansible `InventoryManager.subset()` 은 이 값을 `split_host_pattern()` 으로 나눈다. 쉼표가 없고 주소 형식이 아니면 정규식 `[^\s:\[\]]+` 로 자른다.
   첫 조각 `@/home/cloviradmin/jenkins-agent/os` 만 limit 파일로 찾았고, 그런 파일이 없어 AnsibleError 로 끝났다.
   WSL ansible-core 2.20.7 의 실제 함수 결과: `split_host_pattern("@/home/cloviradmin/jenkins-agent/os 게더링 소연-1/.gather_limit_hosts")` →
   `['@/home/cloviradmin/jenkins-agent/os', '게더링', '소연-1/.gather_limit_hosts']`.
4. 수집 기록 판정은 `failed_run` 이었다. `finalize_gather_output.py` 가 접수된 244대 모두에 합성 결과를 채웠다(`filled=244`).
   inventory 해석은 통과했다 — 오류는 limit 단계에서 났다. 한글은 원인이 아니다.

## 3. 수정

`--limit "@.gather_limit_hosts"` — 작업 폴더 기준 상대 경로다.
- `run_gather.sh` 는 앞부분에서 `cd "$WS"` 하고 그 뒤로 cwd 를 바꾸지 않는다. `env_guard.sh` · `activate_ansible_venv.sh` 에는 `cd` 가 없고, `timeout` 과 `bash -c … exec` 는 cwd 를 물려받는다.
- limit 파일은 `gather_state.py begin` 이 `$WS/.gather_limit_hosts` 에 쓴다. 같은 폴더다.

## 4. 재현 — 실제 `run_gather.sh` + 실제 `ansible-playbook os-gather/site.yml` (WSL)

- 저장소 사본(`git archive HEAD`)을 `/tmp/se-e2e.XXXX/os 게더링 소연-1/` 에 풀었다.
- Jenkins 수집 단계와 같은 환경변수로 `run_gather.sh` → `gather_state.py classify` → `finalize_gather_output.py` 를 차례로 돌렸다.
  finalize 에 넘긴 outcome 은 `Jenkinsfile_portal` `seOutcomeFromState` 와 같이 정했다.
- 대상은 TEST-NET-1 2대(192.0.2.10 · .11, 라우팅되지 않는 주소)다. 수정 전 실행은 `run_gather.sh` 만 `f3cf7678` 판으로 바꿨다.

| | 수정 전 (`f3cf7678`) | 수정 후 (`8249f79a`) |
|---|---|---|
| ansible 인자 | `--limit "@$WS/.gather_limit_hosts"` | `--limit "@.gather_limit_hosts"` |
| 오류 | `[ERROR]: Unable to find limit file b'/tmp/se-e2e.2xsB/os'` | 없음 |
| `run_gather.sh` rc · 실행 시간 | 1 · 1초 | 0 · 33초 |
| 수집 기록 | `failed_run` · 끝난 대상 0 · 결과 줄 0 | `completed` · 끝난 대상 2 · 결과 줄 2 |
| finalize | `kept=0 filled=2` · outcome `failed_run` | `kept=2 filled=0` · outcome `completed` |
| 최종 결과 2대 | `fallback` · `OUTPUT_BUILD_FAILED` · "개더링 프로젝트에서 수집 결과를 만들지 못했습니다." — 사고와 같다 | `reachable` · `TARGET_UNREACHABLE` · "대상 서버가 응답하지 않습니다. 서버 전원 상태와 네트워크 연결을 확인하세요." — 실제 사전 점검 결과 |

쉼표도 같은 Ansible 로 확인했다(작업 폴더 `os,gather-1`, 실행 가능한 inventory 스크립트 1개).

| 인자 | 결과 |
|---|---|
| `--limit "@<절대 경로>/limit"` | `Unable to find limit file b'/tmp/se-comma.n9x7/os'` — 쉼표에서 잘린다 |
| `--limit "@limit"` (cwd 기준) | 대상 1개 정상 |
| `-i "<절대 경로>/inv.sh"` | script 인벤토리로 정상 해석 — 실제 파일이면 대상 목록으로 읽지 않는다 |

## 5. 시험

- `tests/unit/test_run_gather.py`
  - fixture 본문을 `_make_env(tmp_path, ws_name="ws")` 로 뺐고, limit 기대값을 `@.gather_limit_hosts` 로 바꿨다.
  - 새 시험 `test_workspace_path_with_spaces_reaches_ansible_as_one_limit_file`: 작업 폴더 `os 게더링 소연-1` 에서 돌린다.
    limit 값에 공백 · `:` · 쉼표가 없는지는 항상 확인한다. Ansible 이 있으면 실제 `split_host_pattern` 이 조각 하나로 읽는지도 확인한다.
- 시험의 가짜 ansible 은 셸이 넘긴 인자를 그대로 파일로 연다. 그래서 모양 단언이 없으면 수정 전 코드도 통과한다. 새 시험은 수정 전 코드에서 이 단언으로 실패한다.
- 실행 결과: `docs/ai/catalogs/TEST_HISTORY.md` 2026-11-17.

## 6. 승격 · canary

- 긴급 승격(사용자 지시): production `ce1647c7` — main `8249f79a` · parent `673edaa4` · 198 파일 · gate PARTIAL(G11~G15 · G19 SKIP, 나머지 PASS).
  직전 production 대비 바뀐 것은 `scripts/run_gather.sh` 1줄과 provenance 다. GitHub `production` = GitLab `main` = 로컬 `production` · force 0 · drift-check PROVENANCE.
- canary production Job #334(직전 canary #332 와 같은 입력, OS 11대): SUCCESS 129초 · checkout `ce1647c7` · Portal HTTP 200(1번째 전송) ·
  11/11 success · errors 0 · 13키 · #332 대비 값이 다른 host 0.

## 7. 확인하지 못한 것

- 공백이 든 Job 의 실제 Jenkins 재실행. DAY_1 Jenkins 는 사내 GitLab `main` 을 받으므로 지금은 수정본을 받는다(사용자 몫).
- 사고 빌드의 Add-on 커밋 `21db2a48`(저장소 밖). 로컬 사본 `6b1d6e2` 는 `_addon_dir` 를 `lookup('file')` · `is file` 에만 쓴다.
- 쉼표가 든 이름에서 Add-on role 이름이 거부되는지, 따옴표가 든 이름에서 `Jenkinsfile_portal` 셸 인용이 깨지는지.
- 도달 가능한 대상의 인증 · 수집 단계는 e2e 에서 타지 않았다(대상이 TEST-NET). canary #334 가 공백 없는 이름으로 그 경로를 탔다.
