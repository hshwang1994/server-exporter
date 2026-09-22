# Evidence — 고객별 추가 수집(Add-on) hook: gate spike · 엔진 테스트 · 실장비 검증

작성일: 2026-09-21 (5절 이후는 2026-09-22 — main 병합 뒤)
기준: `413bc039` + 브랜치 `feature/gathering-addon` 변경 (worktree), Add-on 저장소 `clovirone-gathering-addon`
실행 환경: WSL Ubuntu (Python 3.12)
- ansible-core **2.20.3** — 운영과 같은 버전. 세션 scratchpad 에 `pip install --target` 으로 고정 설치
  (collection 은 시스템 `/usr/lib/python3/dist-packages` 의 것: ansible.windows 2.2.0)
- ansible-core **2.20.7** — WSL 기본 (사용자 설치 ansible 13.x 번들: ansible.windows 3.3.0, pywinrm 0.5.0).
  운영 Agent 의 collection · pywinrm 버전(ansible 13.4.0 번들)과 같아 Windows 실장비 검증은 이쪽으로 했다
실행 방식: 운영과 같은 `ansible-playbook <ch>-gather/site.yml -i <ch>-gather/inventory.sh --vault-password-file … -e se_location=git`
(`REPO_ROOT` / `ANSIBLE_CONFIG` / `INVENTORY_JSON` / `ANSIBLE_JSON_OUTPUT_FILE` 은 Jenkinsfile_portal 과 같게 주입)

## 요약

| 확인 | 결과 |
|---|---|
| 0절 gate — 외부 절대경로 `include_role` + role `filter_plugins` (2.20.3, 200 host, forks 200, free) | [PASS] |
| `SE_ADDON_DIR` 미설정 → 봉투가 hook 도입 전과 byte 동일 | [PASS] (hash seed 고정 — 아래 3절) |
| 실장비 V1 (Add-on 유무 비교: 차이는 `data.addon` + addon 오류 1건뿐) | [PASS] Linux 3 IP · Windows 1 · ESXi 1 · Redfish 1 |
| V2 (`se_host_input` 이 `add_host` 뒤에도 남고 `{{ 7*7 }}` 이 글자 그대로) | [PASS] |
| V3 (Linux value 줄바꿈 · stderr · 끝 개행) | 측정: `\r\n`, stderr 합쳐짐, 끝 개행 유지 — `\r\n` 은 그대로 두기로 결정 (2026-09-22 사용자, 결정 T) |
| V4 (Add-on 도중 연결 끊김 → 기본 결과 유지) | [PASS] |
| V5 (Windows stdout / stderr) | 측정: stdout 만 `value` 에 담긴다 → 2026-09-22 감싸기 변경으로 오류도 담김 (9절) |
| V6 (UTF-8 이 아닌 바이트) | 측정: 그 host 봉투가 `OUTPUT_BUILD_FAILED` 로 바뀐다 → 2026-09-22 `\xNN` 보존으로 기본 결과 유지 (9절) |
| V7 (ESXi · Redfish 에 맞는 rule 없음 → 결과 불변) | [PASS] |
| V8 (200 host 시간) | 측정 — 4절. 결과로 호출부 `when` 추가 |
| AO-3 · AO-2 추가 조사 (2026-09-22) | 원인 · 추천안 — 5 · 6절 (사용자 지시로 수정은 적용하지 않음) |
| `SE_ADDON_DIR` 설정 실수 (끝 `/`, 상대경로, 상위 폴더, 공백) | [PASS] 어느 경우도 기본 결과 유지 — 7절 |
| Jenkins e2e (실제 Agent `jenkins-agent-dev`, 2.20.3) | [PASS] FAIL 0 — 8절 |
| AO-2 · AO-3 적용 뒤 e2e · Agent 규모 시험(host 200 · forks 200 · 동시 2회) | [PASS] PASS 127 / FAIL 0 / KNOWN 0, 규모 시험 8/8 — 9절 |

## 1. 0절 gate — 핵심 전제 검증 (2.20.3)

위치: 세션 scratchpad (두 저장소 밖, 끝난 뒤 삭제). spike 설정은 메인 핵심값과 같다 (`filter_plugins=./filter_plugins`,
`jinja2_native=True`, `forks=200`, `gathering=explicit`, script 인벤토리). Add-on 흉내 role 은 다른 절대경로에 둔다.
(계획서는 spike 결과를 별도 파일 `…-addon-include-role-spike.md` 에 적는다고 했으나, 실측을 한 곳에서 찾도록
이 문서 1절에 합쳤다.)

| 확인 항목 | 결과 |
|---|---|
| 외부 절대경로 `include_role` | 200/200 host 가 role 태스크 실행 |
| role `filter_plugins` 자동 로드 | 200/200 — role 태스크와 role 안 `include_tasks` 두 곳 모두 |
| 메인 필터 공존 | role 로드 전 · 후 모두 정상 |
| `strategy: free` + forks 200, 같은 spike 2개 동시 실행 | 3회 실행 모두 failed 0 · unreachable 0 · rescued 0 |
| role 내부 상대경로 `include_tasks` + loop | 400/400 |
| `SE_ADDON_DIR` 미설정 | hook 건너뜀, 나머지 play 정상 |

덤으로 확인한 것
- script 인벤토리의 `{"__ansible_unsafe": "{{ 7*7 }}"}` 는 글자 그대로 남는다. 숫자는 숫자로 남는다.
- **같은 이름의 filter 가 메인과 role 에 모두 있으면 메인 쪽이 쓰였다** (role 안에서도). 계획서는 반대로
  예상했으나 어느 쪽이든 한쪽이 가려지므로 `addon_` 접두사 규칙은 유지한다.
- 실제 Agent 재실행은 그때 못 했다: `jenkins-agent-ops`(10.100.64.154)에는 Ansible 이 설치돼 있지 않고
  (`/opt/ansible-env` 없음), 10.100.64.155 는 키 인증이 거부됐다. 2026-09-22 에 Jenkins Job 으로 Agent
  `jenkins-agent-dev` 에서 include_role · role filter_plugins 를 실제 대상과 함께 확인했다 (8절). 200 host × 동시 2회
  규모 시험은 공유 Agent 메모리(7.8GB, 가용 3.8GB) 때문에 Agent 에서 돌리지 않았다 (NEXT_ACTIONS AO-8).

## 2. inventory.sh — host object 보존

입력에 `{{ 7*7 }}` 문자열, 목록, 숫자, bool, null, 중첩 dict, 예약 키(`__ansible_vault`, 중첩 `__ansible_unsafe`)를 넣어
2.20.3 · 2.20.7 로 해석했다.

| 구현 | 결과 |
|---|---|
| 수정본 (`__ansible_*` 키 제외) | 값 전부 글자 그대로 (`{{ 7*7 }}`, `{{ x }}` 해석 안 됨), `rack` 은 int, 예약 키 2개만 빠짐 |
| 예약 키를 거르지 않은 사본 | `__ansible_unsafe is <class '_Untrusted'> not <class 'str'>` → **인벤토리 해석 실패, 대상 0개** |

원인: ansible-core 는 JSON 안의 dict 에 `__ansible_unsafe` · `__ansible_vault` · `__ansible_type` 키가 하나라도
있으면 다른 키가 있어도 그 dict 를 특수값으로 바꾼다 (`module_utils/_internal/_json/_profiles/__init__.py:373-375`).

## 3. 엔진 테스트 (`tests/integration/test_addon_hook_playbook.py`)

실제 `init_fragments → merge_fragment → run_addon.yml → build_* → json_only` 를 태우는 harness, host 2개.

| 시나리오 | 결과 |
|---|---|
| hook 없음(baseline) vs `SE_ADDON_DIR` 미설정 | byte 동일 |
| baseline vs Add-on 있음 · 돌려줄 것 없음 | byte 동일 |
| 경로 없음 | `errors[]` 끝에 `section: addon` 1건만 추가. 경로는 `detail` 에만. 나머지 11키 동일 |
| 정상 | `data.addon` 만 추가 — role filter 동작, `{{ 7*7 }}` 글자 그대로, 여러 줄 값 그대로 |
| 참고 문장만 / 실행 실패 | `errors[]` 1건. 실패 시 중간 결과는 `data` 에 남지 않음 |
| 연결 끊김(192.0.2.1) | host 당 봉투 1개 유지, `ignore_unreachable` 이 role 안까지 이어짐 |

2.20.3 · 2.20.7 모두 통과.

**발견 (hook 과 무관한 기존 동작)**: hook 없는 같은 코드를 세 번 돌려도 `data` 의 키 순서가 매번 달랐다
(`['memory','thermal',…]`, `['thermal','memory',…]`, `['hardware','system',…]`). `merge_fragment.yml` 의
`union` 결과 순서가 Python 문자열 hash 난수에 따라 바뀐다. 값은 같다. 그래서 byte 비교는 `PYTHONHASHSEED=0`
으로 조건을 고정해 한다.

## 4. 실장비 검증

대상 (IP 는 lab 기준, `.167` · `.169` 는 `NEXT_ACTIONS` GA-8 대로 `.165` · `.161` 의 두 번째 IP)

| IP | 장비 | 모드 | 호출자 metadata |
|---|---|---|---|
| 10.100.64.161 | RHEL 8.10 | raw fallback (Python 3.6) | `physical_purpose: DB` |
| 10.100.64.165 | RHEL 9.6 | python_ok | `note: "{{ 7*7 }}"` |
| 10.100.64.167 | (= .165 bond1) | python_ok | `physical_purpose: APP` |
| 10.100.64.120 | Windows 2022 | WinRM 5986 | `physical_purpose: APP` |
| 10.100.64.1 | ESXi 7 | vSphere | `physical_purpose: DB` |
| 10.100.15.34 | Dell iDRAC9 (R760) | Redfish, `_rf_account_service_dryrun=true` | `physical_purpose: DB` |

### V1 · V2 · V3 · V4 — Linux (2.20.3)

Add-on 없음 ↔ 있음 비교: 3 host 모두 `status`(success) · `sections` · `diagnosis` · 최상위 키 · `data` 키(addon 제외)
· `errors`(addon 제외) 동일. 달라진 것은 `data.addon` 과 addon 오류 1건뿐.

| host | 적용 rule | 결과 |
|---|---|---|
| .161 | Linux DB 검증 | 아래 표 |
| .165 | `match: {note: "{{ 7*7 }}"}` | `matched by literal note` = `literal-ok\r\n` — **V2**: 값이 `49` 로 해석됐다면 이 rule 은 맞지 않는다 |
| .167 | Linux 기타 | `uname` = `Linux 5.14.0-570.12.1.el9_6.x86_64 x86_64\r\n` |

.161 의 `swList` (V3 · V4)

| name | 명령 | value |
|---|---|---|
| lines | `printf 'a\nb\n'` | `a\r\nb\r\n` |
| stderr only | `printf 'err\n' 1>&2` | `err\r\n` |
| both | `printf 'out\n'; printf 'err\n' 1>&2` | `out\r\nerr\r\n` |
| no trailing newline | `printf 'x'` | `x` |
| not found | `no-such-command-xyz` | `bash: no-such-command-xyz: command not found\r\n` |
| template text | `echo '{{ 7*7 }}'` | `{{ 7*7 }}\r\n` |
| korean | `echo '한글 출력'` | `한글 출력\r\n` |
| lose connection (V4) | `kill -9 $PPID` (SSH 세션 종료) | `""` + `errors[]` 참고 문장 |
| after reconnect | `echo still-here` | `still-here\r\n` — 다시 접속해 실행 |

`hosts: true` → `dbIpList: []` + "DB 판별 규칙이 아직 정해지지 않아" 참고 문장. `.161` 봉투는 `success` 그대로.

**V3 (결정 T 근거)**: SSH 로 실행한 raw 출력의 줄바꿈은 `\r\n` 이다 (Ansible 이 원격 명령에 PTY 를 붙인다).
stderr 는 실행 순서대로 합쳐지고 끝 개행은 남는다.

### V5 — Windows 2022 (2.20.7, ansible.windows 3.3.0)

Add-on 없음 ↔ 있음: `status` success, 나머지 동일 (차이는 `data.addon` 뿐).

| 명령 | 지금 방식 `& { … } 2>&1` 의 value | 그때 task stderr | `\| Out-String -Stream` 추가 시 value (측정만) |
|---|---|---|---|
| `Write-Output 'out-text'` | `out-text\r\n` | — | 같음 |
| `Write-Error 'err-text'` | `""` | PowerShell 오류 표시 (평문) | 오류 표시 9줄 (win_shell 내부 앞머리 줄이 위치 정보에 보인다) |
| `cmd /c 'echo err-native 1>&2'` | `""` | `err-native` | `cmd : err-native` + 위치 · 분류 줄 (PowerShell 오류 레코드 모양) |
| stdout + 외부 stderr | `out-text\r\n` | `err-native` | 실행 순서대로 둘 다 |
| `Write-Output ('x' * 3000)` | 3002자 한 줄 | — | 같음 (잘림 없음) |
| `Get-Service WinRM \| Select Name, Status` | 표 형식 6줄 | — | 같음 |
| `$ErrorActionPreference='Stop'` + 없는 경로 | `before\r\n` | `Get-Item : Cannot find path …` | `before\r\n` (두 방식 모두 오류 글자 없음) |
| `Write-Output '한글 출력'` | `한글 출력\r\n` | — | — |

로컬 PowerShell 5.1(`powershell.exe -File` / `-Command`)에서도 같았다: `2>&1` 로 합친 오류 레코드를 마지막
출력 단계(Out-Default)가 stderr 로 다시 보낸다. **확정된 감싸기만으로는 Windows 오류 글자가 `value` 에
들어가지 않는다** — `NEXT_ACTIONS` AO-2.

2.20.3 환경(시스템 ansible.windows 2.2.0 · 시스템 pywinrm)으로는 `.120` 이 두 실행 모두 `AUTH_PROBE_FAILED` 였다.
같은 자격증명으로 2.20.7 환경(3.3.0 · pywinrm 0.5.0)은 성공했으므로 검증 환경 차이다. Add-on 과 무관하다.

### V6 — UTF-8 이 아닌 바이트 (2.20.3, .169 = RHEL 8.10)

명령 `printf '\xb0\xa1\n'` (EUC-KR "가") 를 다른 두 명령 사이에 넣었다. 처리 코드는 넣지 않았다.

- stderr: `Callback dispatch 'v2_runner_on_ok' failed for plugin 'json_only': 'utf-8' codec can't encode characters … surrogates not allowed`
- 봉투: 1개 (host 수 유지 — 콜백 보충). `status: failed`, `failure_stage: fallback`, `OUTPUT_BUILD_FAILED`,
  `data: {}`, `errors[0].detail: envelope reconciled by callback; OUTPUT task did not run`
- 즉 **Add-on 명령 하나의 출력 때문에 그 host 의 기본 수집 결과까지 잃는다** — `NEXT_ACTIONS` AO-3.

### V7 — ESXi · Redfish (2.20.7)

config 에 esxi · redfish rule 이 없는 상태.

| 대상 | Add-on 없음 → 있음 | 차이 |
|---|---|---|
| ESXi 10.100.64.1 (`esxi_7x`) | success → success | 없음 (`data.addon` 없음, errors 동일) |
| Redfish 10.100.15.34 (`redfish_dell_idrac9`) | success → success | 없음 |

### V8 — 200 host 시간 (엔진 harness, local 연결, 2.20.3)

실 원격 명령 시간은 빼고 Ansible 엔진이 쓰는 추가 시간만 본다. WSL · `/mnt/c` 라 절대값은 운영보다 크다.

| 경우 | 1차 (개선 전) | 2차 (개선 후) |
|---|---|---|
| hook 없음 | 209.2초 | 210.0초 |
| hook 있음 · `SE_ADDON_DIR` 미설정 | 274.3초 (+65) | **211.0초 (+1)** |
| Add-on 있음 · 맞는 rule 없음 | 335.5초 (+126) | 324.3초 (+114) |
| Add-on 이 명령 2개 실행 | 493.8초 (+285), 200/200 `data.addon` | 475.0초 (+265), 200/200 `data.addon` |

1차 결과로 두 가지를 고쳤다. Ansible 은 `when` 으로 건너뛰는 태스크도 host 마다 작업 프로세스를 띄워
평가하므로, 미설정일 때 hook 안 태스크 약 8개가 host 마다 평가되고 있었다.
- 호출부 4곳에 `when: lookup('env', 'SE_ADDON_DIR') | length > 0` — 미설정이면 include 자체를 건너뛴다.
- Add-on 진입부의 "config 읽기" 와 "rule 선택" 을 한 태스크로 합쳤다.

2차 측정 중 load average 가 9~10 이었다 (같은 PC 의 다른 작업). 절대값은 참고용이고, 비교는 같은 조건의
상대값으로 본다. Add-on 을 쓰는 환경의 추가 시간은 host 당 Add-on 태스크 수(약 10개)에 비례한다.

## 5. AO-3 추가 조사 — UTF-8 이 아닌 바이트 (2026-09-22, 수정 적용 안 함)

사용자 지시: 원인 · 가장 작은 해결안 · `\xNN` 보존의 안전성만 조사하고 수정은 적용하지 않는다.

실패 경로 (ansible-core 2.20.3 소스 + 실행으로 확인)

1. Ansible 은 원격 출력을 `surrogate_then_replace` 로 풀어 문자열에 담는다
   (`plugins/action/__init__.py:1292`, `:1350`). UTF-8 이 아닌 바이트는 짝 없는 surrogate(`\udcb0`)로 남는다.
2. 그 문자열이 `_addon_result` → `_merged_data.addon` → `OUTPUT` 태스크 결과까지 그대로 간다.
3. `json_only._emit` 이 봉투 한 줄을 출력 · 파일에 쓸 때 UTF-8 인코딩이 실패한다 (`surrogates not allowed`).
4. 콜백 예외는 경고로 삼켜진다 (`executor/task_queue_manager.py:503`). 그 host 는 `OUTPUT` 이 나가지 않은
   것으로 남고, 콜백 보충이 data 없는 `OUTPUT_BUILD_FAILED` 봉투를 채운다.

기본 결과까지 사라지는 이유: 봉투는 host 당 JSON 한 줄로 한 번에 인코딩된다. 섹션 단위 격리가 없어서
글자 하나가 줄 전체를 실패시킨다.

실험 (엔진 harness `tests/fixtures/addon/harness.yml`, 2.20.3 · 2.20.7 같은 결과, `PYTHONHASHSEED=0`, host 1개)

| 경우 | 결과 |
|---|---|
| 기준 (Add-on 없음) | `partial` (harness 고정값: system 성공 + cpu 실패) |
| E1 — Add-on 이 원래 바이트(`\xb0\xa1`)를 담아 돌려줌 | 경고 `Callback dispatch 'v2_runner_on_ok' failed … surrogates not allowed` → `failed` / `OUTPUT_BUILD_FAILED`, 기본 `data` 사라짐 |
| E2 — Add-on 이 돌려주기 직전 surrogate 만 `\xNN` 글자로 | `partial` (기준과 같음), 기본 `data` 기준과 동일, JSON 텍스트 `"ok \\xb0\\xa1 end\n"` (ASCII), Callback 본문 조립(`Jenkinsfile_portal` 과 같게 줄을 `,` 로 이음) · 파싱 정상 |

추천 (결정 대기 — `NEXT_ACTIONS` AO-3): Add-on 이 결과를 돌려주기 직전 surrogate 바이트만 `\xNN` 글자로
바꾸고 `errors[]` 참고 문장 1건을 남긴다 (Add-on 태스크 1 + filter 1, 메인 0줄). 알아둘 점: 명령이 원래
`\xNN` 글자를 출력한 경우와 구분되지 않고, Portal 화면에는 escape 글자로 보인다.
대안: 해당 value 를 비움 / hook 에서 addon 결과를 버림(메인 filter) / 콜백 안전망(보호 파일 — 별도 결정).

## 6. AO-2 추가 조사 — Windows 오류 출력 (2026-09-22, 수정 적용 안 함)

Windows 2022(.120)에서 실제 `win_shell` 로 명령 8개 × 감싸기 6개 = 48 조합을 실행했다 (병합된 main 의
os-gather + 측정 전용 Add-on 사본, 2.20.7 · ansible.windows 3.3.0). 로컬 PowerShell 5.1
(`-EncodedCommand`)에서도 같은 결과였다. 아래는 stdout(= `value` 가 되는 것) 기준이다.

| 명령 | `& { } 2>&1` · `*>&1` (지금) | `2>&1 \| Out-String -Stream` | `*>&1 \| Out-String -Stream` | try/catch + `*>&1 \| Out-String -Stream` |
|---|---|---|---|---|
| `Write-Output 'o1'` | `o1\r\n` | 같음 | 같음 | 같음 |
| `Write-Error 'e1'` | 없음 (stderr 로 감) | 빈 줄 + 오류 표시 (위치 정보에 win_shell 앞머리 줄이 보임) | 같음 | 같음 (catch 글자 포함) |
| 외부 명령 stderr (`cmd /c 'echo e2 1>&2'`) | 없음 (`e2` 는 stderr) | `cmd : e2` + 위치 · 분류 줄 | 같음 | 같음 |
| 종료 오류 (`$ErrorActionPreference='Stop'` + 없는 경로) | `before\r\n`, 오류는 stderr, rc 1 | 같음 | 같음 | 오류 글자도 stdout, **rc 0** |
| 섞인 순서 (o1 → Write-Error → 외부 stderr → o2) | `o1`, `o2` 만 | 실행 순서대로 전부 | 같음 | 같음 |
| Warning · Verbose · Host · Information | Host · Information 만 | 같음 | Warning · Verbose 까지 (앞말 없이) | 같음 |
| `exit 3` | rc 3 | 같음 | 같음 | 같음 |
| 객체 (`Get-Service … \| Select Name, Status`) | 표 6줄 | byte 동일 | byte 동일 | byte 동일 |

- `2>&1` · `*>&1` 로 합친 오류 레코드는 마지막 출력 단계(Out-Default)가 다시 stderr 로 보낸다.
  `Out-String -Stream` 은 모든 객체를 글자로 만들어 stdout 으로 내보내므로 오류가 실행 순서대로 남는다.
- stdout 만 내는 명령은 어느 방식이든 byte 동일하다 (추가 변환 없음).
- 종료 오류는 try/catch 없이는 어느 방식도 stdout 에 담지 못한다. try/catch 는 rc 를 바꾼다.

추천 (결정 대기 — `NEXT_ACTIONS` AO-2): `& { <command> } *>&1 | Out-String -Stream` + task stderr 가 비어 있지
않으면 `errors[]` 참고 문장.

## 7. `SE_ADDON_DIR` 설정 실수 (2026-09-22, 엔진 harness, 2.20.3 · 2.20.7 같은 결과)

운영자가 낼 수 있는 경로 실수를 넣어 봤다. 모든 경우 봉투 1개, 기본 결과(`status` · `sections` · 기본 `data`) 불변.

| `SE_ADDON_DIR` | 결과 |
|---|---|
| 끝에 `/` (`…/ok/`) · 중간 `//` | 정상 실행 (`data.addon` 동일) |
| 작업 디렉터리 기준 상대경로 (`tests/…/ok`, `./tests/…/ok`) | 정상 실행 — 문서상 절대경로이지만 Jenkins 작업 디렉터리는 빌드마다 달라 실제로는 "경로 없음" 이 된다 |
| 없는 상대경로 · `tasks/main.yml` 이 없는 상위 폴더 · `tasks/main.yml` 파일 자체 | `errors[]` 1건 `cause=addon_entry_not_found` |
| 앞뒤 공백이 붙은 경로 | `errors[]` 1건 — `detail` 에 공백이 그대로 보여 원인을 찾을 수 있다 |

엔진 테스트에 "상위 폴더"(`no_entry`) 와 "끝 `/`"(`ok_trailing_slash`) 를 추가했다 (`tests/integration/test_addon_hook_playbook.py`).

## 8. Jenkins e2e — 실제 Agent · 실제 대상 (2026-09-22)

Job: `http://10.100.64.153:8080/job/형섭/job/clovirone-gathering-addon-e2e/` (Add-on 저장소 `tests/e2e/Jenkinsfile`,
Pipeline from SCM). Agent `jenkins-agent-dev` (label `git`), ansible-core 2.20.3 / Python 3.12.3. 메인 수집은 운영 Job 과
같은 저장소 · 브랜치에서 받고, `Jenkinsfile_portal` Gather 단계와 같은 명령 · vault 자격증명 · 환경변수로 실행한다.
`SE_ADDON_DIR` 은 Job 안에서 시나리오마다 정한다 (노드 설정 불변). 시나리오마다 host 당 봉투 수와 Callback 본문 조립
(`Jenkinsfile_portal` 과 같게 줄을 `,` 로 이어 `gatherInfoJson` 배열) · 파싱을 확인한다.

| 빌드 | 메인 / Add-on | 결과 |
|---|---|---|
| #1 | `d6ed2278` / `c7447b9` | FAILURE — 새 Job 의 첫 빌드에서 Jenkinsfile 에 선언한 파라미터가 셸 환경변수로 들어오지 않았다 (`SE_LOCATION: unbound variable`). `params` 를 `withEnv` 로 넘기도록 수정 (`a75e726`) |
| #2 | `d6ed2278` / `a75e726` | SUCCESS — 시나리오 11개, PASS 99 / FAIL 0 / KNOWN 1 (AO-2), 705초 |
| #3 | `d6ed2278` / `db9b31e` | SUCCESS — 시나리오 14개 (s12 ~ s14 추가), PASS 116 / FAIL 0 / KNOWN 2 (AO-2 · AO-3), 888초 |
| #4 | `eafddf0b` / `0dd4d7b` | SUCCESS — PASS 116 / FAIL 0 / KNOWN 2. s10 에 hosts 알림 확인 추가 |
| #5 | `eafddf0b` / `18115fe` | SUCCESS — PASS 119 / FAIL 0 / KNOWN 2. s04 Windows here-string(`here a\nhere b\r\n` — 안쪽 LF 는 그대로) · `{{ 7*7 }}` 글자 그대로. 새 "엔진 테스트(Agent)" 단계는 Agent python3 에 pytest 가 없어 건너뜀 → 빌드 작업 디렉터리에만 받아 쓰도록 수정 (`9097425`) |
| #6 | `eafddf0b` / `9097425` | SUCCESS — 엔진 테스트(Agent, ansible-core 2.20.3) **10 passed** (Test Result pass 10 / fail 0) + 시나리오 14개 PASS 119 / FAIL 0 / KNOWN 2 (AO-2 · AO-3), 956초 |
| **#7 (최종)** | `d67005b9` / `951366d` | SUCCESS — AO-2 · AO-3 적용 뒤. 엔진 테스트 10 passed, 규모 시험 PASS 8/8, 시나리오 14개 **PASS 127 / FAIL 0 / KNOWN 0**, 1086초 (9절) |

시나리오 (`clovirone-gathering-addon/tests/e2e/run.py` `SCENARIOS`)

| 시나리오 | 대상 | 확인한 것 |
|---|---|---|
| s01 미설정 | Linux raw(.161) · Linux(.165) · Windows(.120) | `data.addon` · addon 오류 없음, success — 이후 비교 기준 |
| s02 경로 없음 · s03 기본 config(`rules: []`) | Linux · Windows | 기본 결과가 s01 과 같음 (s02 는 addon 오류 1건) |
| s04 software | 3대 | Linux 값 7종(`\r\n`, stderr 합침, 끝 개행 없음, not found, `{{ 7*7 }}` 글자 그대로, 한글), first-match, 호출자 metadata `{{ 7*7 }}` 로 rule 선택, hosts 미확정 알림, Windows 값 4종 |
| s05 깨진 config · s06 설정 실수 | Linux | 기본 결과 유지 + 원인 1건 / 맞는 항목만 실행 |
| s07 연결 끊김 | Linux raw | `kill -9 $PPID` 뒤 다음 명령은 재접속해 실행, 목록 모양 유지 |
| s08 host 4개 · s09 응답 없는 대상 섞임 | Linux 4 IP / .163 + Linux | host 마다 다른 rule, 죽은 대상은 수집 전 실패(addon 없음) |
| s10 ESXi · s11 Redfish(dry-run) | .1 / .15.34 | success 유지, ESXi 는 명령 없이 알림만 |
| s12 경로 끝 `/` | Linux | 정상 실행, 기본 결과 s01 과 같음 |
| s13 수 MB 출력 | Linux(.165) · Windows(.120) | Linux `seq 1 300000` 2,288,895자 · 1,000,000자 한 줄, Windows 100,000줄 1,188,895자 · 1,000,002자 한 줄 — 실제 SSH · WinRM 전송 뒤 **전부 글자 그대로**, 기본 결과 s01 과 같음 (151초) |
| s14 UTF-8 아닌 출력 | Linux | `KNOWN` — 그 host 봉투가 `OUTPUT_BUILD_FAILED` (5절과 같음, AO-3 결정 대기) |

빌드 화면에서 보이는 것: 빌드 설명(시나리오 요약 + 엔진 테스트 요약), "Add-on e2e 보고서"(HTML — 태그 속성만 쓰고
style · script 가 없어 Jenkins 기본 CSP 에서도 그대로 보인다), Test Result(엔진 테스트 JUnit), 보관 파일
(`results/*.jsonl` 원본 · `*.log` · `report.json` · `*summary.txt` · `engine-junit.xml`).
Jenkins 는 익명 읽기가 막혀 있어(403) 브라우저로는 로그인 뒤에 보인다. 이번 확인은 REST API(빌드 설명 · 보관 파일 ·
Test Result)와 보고서 HTTP 응답(200, `text/html;charset=utf-8`)으로 했다.

## 9. AO-2 · AO-3 적용과 Agent 규모 시험 (2026-09-22, 사용자 결정 "추천대로")

변경은 Add-on 저장소뿐이다 (메인 코드 0줄).

- Add-on `c3c34ff`: Windows 감싸기 `& { … } *>&1 | Out-String -Stream`. 종료 오류로 task stderr 가 남으면 그 첫 줄을
  `software '<이름>': value 에 담기지 않은 오류 출력이 있습니다 — …` 로 알린다 (Linux stderr 는 SSH 메시지 자리라 보지
  않는다). 마지막 태스크가 `_addon_result` · `_addon_errors` 의 짝 없는 surrogate 만 `\xNN`(원래 바이트 0x80~0xFF)
  또는 `\uXXXX` 글자로 바꾸고 위치를 알린다 (`filter_plugins/addon_text.py`).
- Add-on `951366d`: e2e 에 규모 시험(`SCENARIOS` 에 `scale`) — MemAvailable 을 0.5초마다 보고 1GiB 아래면 중단,
  동시 2회는 1회 사용량 ×2 가 남은 메모리 안에 여유 있게 들어갈 때만.
- Add-on `7dec7d2`: 배포 Job (`deploy/Jenkinsfile`).

로컬 PowerShell 5.1 에서 예전(`2>&1`) · 새 감싸기의 stdout 을 byte 로 비교했다: 문자열 안 LF(`a\nb`), here-string,
끝 LF, 표(`Get-Service | Select`), 300자 한 줄, 외부 프로그램 여러 줄 — **모두 byte 동일**. (Out-String -Stream 이
여러 줄 문자열을 줄로 나눌까 우려했으나 그렇지 않았다.)

Jenkins e2e #7 (Agent `jenkins-agent-dev`, ansible-core 2.20.3, 메인 `d67005b9`, Add-on `951366d`, `SCENARIOS=all,scale`):
**SUCCESS — 엔진 테스트 10 passed, 규모 시험 PASS 8/8, 시나리오 14개 PASS 127 / FAIL 0 / KNOWN 0**, 1086초.

| 확인 | 결과 (Windows 2022 .120 · Linux .165) |
|---|---|
| `Write-Error 'err-text'` | `value` = `\r\nWrite-Error 'err-text'\r\n : err-text\r\nAt line:1 char:65 …` (PowerShell 오류 표시 그대로) |
| stdout + 외부 stderr (`cmd /c 'echo err-native 1>&2'`) | `out-text\r\ncmd : err-native \r\nAt line:3 char:1 …` — 실행 순서대로 |
| 종료 오류 (`$ErrorActionPreference='Stop'` + 없는 경로) | `value` = `before\r\n`, `errors[]` 1건: `software 'terminating': value 에 담기지 않은 오류 출력이 있습니다 — Get-Item : Cannot find path 'C:\no-such-path-xyz' …` |
| 오류 없는 출력 (stdout · 한글 · 여러 줄 · here-string `here a\nhere b\r\n` · `{{ 7*7 }}`) | #5 (예전 감싸기)와 글자까지 같음 |
| 수 MB (Windows 100,000줄 1,188,895자 · 1,000,002자 한 줄) | 전부 일치 |
| 비 UTF-8 (`printf 'ok \260\241 end\n'`, Linux) | `value` = `ok \xb0\xa1 end\r\n`, `status` success, 기본 결과 s01 과 같음, `errors[]` 1건: `UTF-8 로 읽을 수 없는 바이트를 \xNN 글자로 바꿔 담았습니다: software.swList['non utf8'].value` |

규모 시험 (계획서 0절 gate 를 실제 Agent 에서, host 200 · forks 200 · strategy free · local 연결)

| 단계 | 실행 | 시간 | 최대 메모리 사용 (시작 가용 → 최저) | 결과 |
|---|---|---|---|---|
| 미설정 | 1회 | 12.8초 | 0.35GiB (6.51 → 6.16) | 실패 0 · hook 건너뜀 200/200 |
| Add-on | 1회 | 35.6초 | 0.26GiB (6.55 → 6.28) | 실패 0 · role filter · 메인 filter(전 · 후) · 상대 include(loop 2) 200/200 |
| Add-on | 동시 2회 | 64.2초 | 0.28GiB (6.49 → 6.22) | 두 실행 모두 위와 같음 |

앞서(8절 무렵) 이 시험을 "공유 Agent 메모리 7.8GB(가용 3.8GB)에서 위험" 이라 보고 미뤘는데, WSL 에서 같은 규모를
먼저 재 보니 동시 2회 0.79GiB 였고 Agent 에서는 0.28GiB 였다. forks 로 갈라진 작업 프로세스가 메모리를 대부분
공유하기 때문이다.

배포 (AO-7 일부): 배포 Job #1 → `/home/cloviradmin/clovirone-gathering-addon` → `…-releases/20260922-085019-7dec7d2`
(검사 통과, 기본 config `rules: []`). 노드 환경변수 `SE_ADDON_DIR` 등록 · 임시 Callback 수신 Job 은 공유 자원
변경이라 자동 권한 검사가 막았다 — 하지 않았다.

## 10. 하지 못한 것

- 운영 Agent 노드 환경변수 `SE_ADDON_DIR` 등록 (AO-7 — 사용자), 그 뒤 실제 `Jenkinsfile_portal` 빌드 확인 (AO-10).
  Portal 수신은 Portal 측 (AO-9).
- hosts DB matcher — 고객 샘플 전 (AO-5).
- 수 MB `value` 가 실제 `Jenkinsfile_portal` 콘솔 · Callback POST 에 주는 부담 — e2e 는 본문 조립 · 파싱까지만 봤다.
