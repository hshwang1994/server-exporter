# 추가 수집(Add-on) hook

고객마다 더 모아야 하는 정보(지정 Software 확인, `/etc/hosts` 의 DB IP 등)는 이 저장소 코드에 넣지 않고
별도 디렉터리의 Add-on 이 맡는다. 이 저장소에는 Add-on 을 부르는 범용 hook 하나만 있다. 이 문서는 그 hook
과 Add-on 사이의 약속이다. Add-on 설정 · 운영 방법은 Add-on 저장소의 README 에 있다.

수집 기능이 늘어도 이 저장소는 고치지 않는다. hook 은 Add-on 안의 수집 기능 이름도, 결과 모양도 모른다.

## 1. 어디서 불리나

| Play | 위치 | `_addon_target` |
|---|---|---|
| Linux | `os-gather/site.yml` "linux \| gather hba_ib" 뒤, "linux \| build diagnosis" 앞 | `linux` |
| Windows | `os-gather/site.yml` "windows \| gather runtime" 뒤, "windows \| build diagnosis" 앞 | `windows` |
| ESXi | `esxi-gather/site.yml` "esxi \| collect runtime" 뒤, "esxi \| build_sections" 앞 | `esxi` |
| Redfish | `redfish-gather/site.yml` "redfish \| normalize standard" 뒤, "redfish \| build_sections" 앞 | `redfish` |

- 인증과 기본 수집이 끝난 뒤, 조립(`build_*`) 직전이다. Add-on 은 이미 붙어 있는 연결을 그대로 쓴다.
  자격증명 해석 · 후보 시도 · 재접속 코드가 Add-on 에 없다.
- 기본 수집이 중간에 멈추면(인증 실패 등) 이 지점에 오지 않으므로 Add-on 도 실행되지 않는다.
- ESXi · Redfish 는 연결이 `local` 이라 Add-on 태스크가 Jenkins Agent 에서 실행된다. 명령을 실행하는 수집
  기능은 `linux` / `windows` 에서만 동작하게 만든다. 지원하지 않는 target 에서 수집 기능은 실행하지 않고 알림
  1문장을 남긴다 → 그 host 의 `errors[]` 에 `section: addon` 1건, `data.addon` 에는 그 기능이 생기지 않는다.
  rule 에 `target` 을 빼면 ESXi · Redfish host 에도 맞으므로 이 알림이 그 실수를 드러낸다 (2026-09-22 감사에서
  계약으로 확정 — 조용히 넘기지 않는다).
- 호출은 `SE_ADDON_DIR` 이 있을 때만 include 한다 (`when`). 없으면 host 당 건너뛴 태스크 1개로 끝난다.

## 2. 경로 — `SE_ADDON_DIR`

`common/tasks/addon/run_addon.yml` 은 세 경우만 구분한다. 자동 fallback 경로나 특수값은 없다.

| `SE_ADDON_DIR` | 동작 | 봉투 |
|---|---|---|
| 없음 | Add-on 을 쓰지 않는 환경. 아무 것도 하지 않는다 | hook 도입 전과 같다 |
| 있는데 `<경로>/tasks/main.yml` 이 없음 | Add-on 을 실행하지 않는다 | `errors[]` 에 `section: addon` 1건 (`detail`: `SE_ADDON_DIR=<경로>; cause=addon_entry_not_found`) |
| 있고 Add-on 이 있음 | `include_role` 로 실행 | 결과는 `data.addon`, 문제는 `errors[]` 1건 |

설정은 Agent 노드 환경변수로 한다 ([08-ansible-config.md](../operate/08-ansible-config.md) 3절). 절대경로를 쓴다.
Add-on 을 Agent 에 두는 일은 Add-on 저장소의 배포 Job(`deploy/Jenkinsfile`)이 한다 — 검사를 통과한 버전만
`/home/cloviradmin/clovirone-gathering-addon`(링크)으로 바꿔 끼운다. 사용법은 Add-on README 6절(관리자용).

설정 실수의 결과 (2.20.3 · 2.20.7 실측, 엔진 테스트로 고정):

- 끝에 `/` 가 붙은 경로는 그대로 동작한다.
- Add-on 상위 폴더 · `tasks/main.yml` 파일 자체 · 앞뒤 공백이 붙은 값은 "`tasks/main.yml` 이 없음" 과 같다.
  `detail` 에 받은 값이 그대로 보이므로 공백도 찾을 수 있다.
- 상대경로는 작업 디렉터리 기준으로 풀린다. Jenkins 작업 디렉터리는 빌드마다 달라 사실상 "경로 없음" 이 된다.

## 3. 주고받는 값 (변수 5개)

| 방향 | 변수 | 내용 |
|---|---|---|
| 메인 → Add-on | `_addon_dir` | `SE_ADDON_DIR` 값 |
| | `_addon_target` | `linux` / `windows` / `esxi` / `redfish` |
| | `se_host_input` | 호출자가 보낸 host object (`inventory.sh` 가 보존, 5절). 수기 인벤토리에는 없다 → `se_host_input \| default({})` |
| Add-on → 메인 | `_addon_result` | dict. `data.addon` 아래에 그대로 들어간다. 비어 있으면 `addon` 키를 만들지 않는다 |
| | `_addon_errors` | 문장 목록. 있으면 `errors[]` 에 `section: addon` 1건 (`detail` = 문장들을 ` \| ` 로 이은 것) |

hook 이 `{'addon': _addon_result}` 를 `_data_fragment` 로 만들어 `merge_fragment.yml` 로 합친다. Add-on 은
fragment 변수나 누적 변수를 직접 건드리지 않는다. 합칠 것이 없으면 merge 도 부르지 않는다.

Add-on 이 지킬 것: 돌려주는 두 변수의 글자는 UTF-8 로 쓸 수 있어야 한다. 원격 출력의 UTF-8 이 아닌 바이트는
Ansible 이 짝 없는 surrogate 글자로 담는데, 그대로 돌려주면 콜백이 그 host 봉투를 쓰지 못해 기본 결과까지 잃는다
(6절). `clovirone-gathering-addon` 은 돌려주기 직전 그 바이트만 `\xNN` 글자로 바꾸고 `errors[]` 에 알린다
(2026-09-22).

## 4. 봉투에 미치는 영향

- `status` · `sections` · `diagnosis` 는 바뀌지 않는다. hook 은 섹션을 만들지 않고, `errors[]` 는 `status`
  판정에 쓰이지 않는다 ([02-normalize-flow.md](02-normalize-flow.md)).
- Add-on 이 실행 중 실패하면 rescue 가 격리한다. 그때까지의 중간 결과는 버리고 `errors[]` 1건만 남긴다.
- 실행 도중 연결이 끊겨도 host 를 잃지 않는다 (`ignore_unreachable: true` — `try_one_credential.yml` 과 같은
  이유). 이 설정은 include 한 role · collector 안쪽 태스크까지 이어진다 (2.20.3 실측).
- 수집에 들어가기 전에 멈춘 실패 봉투(rescue · `always` fallback · 콜백 보충)에는 `addon` 이 없다.
- `meta.duration_ms` 에는 Add-on 실행 시간도 들어간다 (hook 이 `build_meta` 보다 앞에서 돈다).
- `errors[]` 문장 (`message`) 은 세 가지다. 변수명 · 경로 · 원인 코드는 `detail` 에만 있다.

| 경우 | `message` |
|---|---|
| 경로 없음 | 추가 수집 구성을 찾지 못해 추가 수집을 실행하지 않았습니다. 추가 수집 설치 경로를 확인하세요. |
| Add-on 이 참고 문장을 돌려줌 | 추가 수집 중 처리하지 못한 항목이 있습니다. 추가 수집 설정과 수집 로그를 확인하세요. |
| Add-on 실행 실패 | 추가 수집 중 오류가 발생했습니다. 추가 수집 설정과 수집 로그를 확인하세요. |

`detail` 은 기존 `errors_normalizer` 가 2000자에서 자른다 (Add-on 전용 제한이 아니라 모든 `errors[]` 에 같다).

## 5. `se_host_input` — 호출자 host object

`os-gather` · `esxi-gather` · `redfish-gather` 의 `inventory.sh` 는 호출자가 보낸 host object 전체를 hostvar
`se_host_input` 한 키 아래에 보존한다. 키 이름을 코드에 적지 않으므로 호출자가 새 키를 보내도 고칠 일이 없다.

- IP 선택 · IPv4 검증 · 중복 검사는 종전 그대로다. host object 를 최상위 hostvar 로 펼치지 않으므로
  `ansible_user` 같은 이름이 와도 연결에 쓰이지 않는다.
- 문자열은 `{"__ansible_unsafe": ...}` 로 감싼다. ansible-core 는 스크립트 인벤토리의 문자열을 템플릿으로
  신뢰하기 때문에, 감싸지 않으면 `{{ }}` 가 든 값이 해석된다.
- `__ansible_` 로 시작하는 키는 옮기지 않는다. Ansible JSON 의 예약 표식이라, 그대로 두면 인벤토리 해석이
  통째로 실패해 그 빌드의 모든 대상이 결과를 잃는다 (2.20.3 · 2.20.7 실측).

## 6. 알아둘 한계 (2026-09-21 실측)

- Add-on 의 태스크 YAML 문법 오류는 rescue 로 잡히지 않고 실행 전체를 멈춘다 (`strategy/free.py` 가
  `AnsibleParserError` 를 다시 던진다). 그래서 고객이 고치는 파일은 런타임에 읽는 `config.yml` 하나로
  두고, Add-on 태스크는 Add-on 테스트를 통과한 것만 배포한다.
- Add-on 전용 timeout 은 없다 (사용자 결정). 끝나지 않는 명령은 Jenkins Gather 단계 제한(60분,
  `Jenkinsfile_portal`)까지 play 를 붙잡고, 그 빌드의 모든 host 결과가 전달되지 않는다.
- Add-on 이 돌려준 글자에 짝 없는 surrogate(원격 출력의 UTF-8 이 아닌 바이트)가 남으면 콜백이 그 host 의 봉투를
  쓰지 못한다 (`surrogates not allowed`). 콜백 보충이 `OUTPUT_BUILD_FAILED` 실패 봉투를 대신 내므로 host 수는
  유지되지만 기본 수집 결과도 잃는다. 그래서 3절의 약속대로 Add-on 이 돌려주기 전에 글자를 정리한다.
- role 의 filter 와 메인 filter 이름이 같으면 한쪽이 가려진다 (2.20.3 실측에서는 메인 쪽이 쓰였다).
  Add-on filter 는 `addon_` 으로 시작한다.
- `data` 안의 키 순서는 실행마다 다를 수 있다. `merge_fragment.yml` 의 `union` 이 문자열 hash 에 따라 순서를
  정하는 기존 동작이며 hook 과 무관하다. 비교할 때는 키 순서가 아니라 값을 비교한다.

## 7. 테스트

| 테스트 | 무엇을 | 어디서 |
|---|---|---|
| `tests/unit/test_inventory_passthrough.py` | host object 보존 · 문자열 감싸기 · 예약 키 제외 · 기존 오류 경로 | 어디서나 |
| `tests/unit/test_addon_hook_contract.py` | 호출 4곳 · 경로 세 경우 · timeout 없음 · 문장 규칙 · 뼈대에 `addon` 없음 | 어디서나 |
| `tests/integration/test_addon_hook_playbook.py` | 실제 ansible-playbook 으로 공통 조립 코드 + hook: 미설정 시 byte 동일, 경로 없음 · 상위 폴더, 끝 `/`, 정상, 참고 문장, 실행 실패, 연결 끊김 | Linux / WSL / Jenkins Agent |
| Add-on 저장소 `tests/e2e/` (Jenkins Job) | 실제 Agent 에서 운영과 같은 명령 · vault 로 Linux · Windows · ESXi · Redfish 대상 시나리오를 돌리고, 위 엔진 테스트도 같은 Agent 에서 돌린다 | Jenkins |

엔진 테스트는 `tests/fixtures/addon/` 의 합성 Add-on 과 `harness.yml` 을 쓴다. `ANSIBLE_PLAYBOOK_BIN` 으로
다른 ansible-playbook(예: 운영과 같은 2.20.3)을 지정할 수 있다.
Add-on 저장소: `https://10.100.64.156/root/clovirone-server-gathering-addon.git` — e2e 사용법은 그 저장소 `tests/e2e/run.py` 머리.
GitLab 프로젝트 이름은 이 저장소 이름을 따른 것이고, 코드 · Jenkins Job · Agent 경로 · 문서에서는
`clovirone-gathering-addon` 으로 부른다 — 같은 것이다.
