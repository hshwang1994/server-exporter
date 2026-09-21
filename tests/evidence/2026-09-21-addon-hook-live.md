# Evidence — 고객별 추가 수집(Add-on) hook: gate spike · 엔진 테스트 · 실장비 검증

작성일: 2026-09-21
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
| V3 (Linux value 줄바꿈 · stderr · 끝 개행) | 측정: `\r\n`, stderr 합쳐짐, 끝 개행 유지 |
| V4 (Add-on 도중 연결 끊김 → 기본 결과 유지) | [PASS] |
| V5 (Windows stdout / stderr) | 측정: stdout 만 `value` 에 담긴다 — **결정 필요** |
| V6 (UTF-8 이 아닌 바이트) | 측정: 그 host 봉투가 `OUTPUT_BUILD_FAILED` 로 바뀐다 — **결정 필요** |
| V7 (ESXi · Redfish 에 맞는 rule 없음 → 결과 불변) | [PASS] |
| V8 (200 host 시간) | 측정 — 4절. 결과로 호출부 `when` 추가 |

## 1. 0절 gate — 핵심 전제 검증 (2.20.3)

위치: 세션 scratchpad (두 저장소 밖). spike 설정은 메인 핵심값과 같다 (`filter_plugins=./filter_plugins`,
`jinja2_native=True`, `forks=200`, `gathering=explicit`, script 인벤토리). Add-on 흉내 role 은 다른 절대경로에 둔다.

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
- 실제 Agent 재실행은 못 했다: `jenkins-agent-ops`(10.100.64.154)에는 Ansible 이 설치돼 있지 않고
  (`/opt/ansible-env` 없음), 10.100.64.155 는 키 인증이 거부됐다 (NEXT_ACTIONS AO-8).

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

## 5. 하지 못한 것

- 실제 Jenkins Agent 에서 spike · 엔진 테스트 재실행 (AO-8), Jenkins 파이프라인 1회 (AO-10).
- hosts DB matcher — 고객 샘플 전 (AO-5).
- 수 MB 출력의 실장비 전송 — 5.5MB 보존은 local 연결 테스트(`clovirone-gathering-addon/tests/test_playbook.py`)로만 확인.
