# ADR 2026-09-29 — Add-on 을 빌드마다 받는다: 켜기 1개 설정 · 추가 1개 파일 · Runner 무관

- 상태: Accepted (사용자 확정 2026-09-29)
- 대체: `ADR-2026-09-21-gathering-addon-hook.md` 의 **배포 부분**(배포 Job · `ADDON_HOME` · 노드 환경변수 `ADDON_DIR`).
  hook 계약(변수 5개 · 세 경우 · `errors[]` 문장 · timeout 없음)은 그대로다.
- 정본: `docs/reference/decision-log.md` 2026-09-29, `docs/operate/04-pipeline-runtime.md` 3절, `docs/develop/07-addon-hook.md` 2절,
  Add-on 저장소 README. 실측: `tests/evidence/2026-09-29-addon-per-build-checkout.md`.
- 이름: 변수 이름은 2026-09-30 변경 뒤 이름으로 적었다 (대응표: `docs/reference/decision-log.md` 2026-09-30).

## 컨텍스트 (Why)

- 신규 Jenkins(jenkins-prod.gooddi.lab)는 `git` 라벨 Runner 가 4대다. 종전 Add-on 은 배포 Job 이 **노드 한 대**의
  `ADDON_HOME` 에 파일을 놓고 그 노드의 환경변수 `ADDON_DIR` 로 켜는 구조라, 수집이 어느 Runner 에서 도는지(Jenkins
  스케줄링)와 Add-on 코드가 거기 있는지(availability)가 묶여 있었다. lab 은 Runner 가 한 대(155 가 `ic/chj/yi/git` 전부)라
  드러나지 않았다. 신규 Runner 의 Agent 계정 `jenkins` 는 `/home/cloviradmin/...`(700) 을 읽지도 못한다 (JV-3).
- 사용자 요구: 4대에 복사하는 땜질이 아니라 구조를 다시 세운다. 우선순위 ① 쓰기 쉬움 ② 운영하기 쉬움 ③ 추가/수정 쉬움
  ④ Runner 수 · 라벨 · 재설치 무관 ⑤ 단순 ⑥ 그 다음 보안 · 엄격함. Add-on 선택 기준은 `target_type` 하나 — `loc` · Agent 라벨 ·
  Runner 이름은 기준이 아니다. 저장소 접근은 GitHub · 내부 GitLab · http/https · 자체 서명 인증서 모두 Runner 사전 작업 없이.
  새 Add-on 은 파일 하나, 등록표 중복 없음. 저장소를 못 받아도 host 별 오류를 만들지 않는다. 작업 공간은 빌드마다 깨끗.
  실행할 것이 없으면 일찍 건너뛴다. Portal 계약(`data.addon` · `errors[] section: addon` · `status`) 유지.

## 결정 (What)

| 관심사 | 담당 | 근거 |
|---|---|---|
| Jenkins 스케줄링 | `Jenkinsfile_portal` Resolve Location + `locations.yml.agent_label` (변경 없음) | `loc` |
| Add-on availability | Gather stage 가 빌드마다 `scripts/addon_checkout.sh` 로 `${WORKSPACE}/addon` 에 받고 `addon/tools/check_layout.py` 로 검사한 뒤 ansible 실행에만 `withEnv(ADDON_DIR)` | Jenkins 전역 `ADDON_REPO_URL` 1개 (+선택 `ADDON_REPO_REF` · `ADDON_REPO_CREDENTIALS_ID` · `ADDON_REPO_SSL_VERIFY`) |
| Add-on resolution | Add-on 저장소 `collectors/<target>/<이름>.yml` — 디렉터리 = 지원 target, 파일 = Add-on 하나, 이름 = `data.addon.<이름>` | `_addon_target` (play 가 결정) |

1. 체크아웃은 Git 플러그인이 아니라 스크립트다 (`git init` → `fetch --depth 1 origin <ref>` → 실패 시 브랜치 · 태그 전체
   fetch 후 해석). 브랜치 · `refs/tags/<태그>` · 40자 해시가 같은 흐름이고 짧은 해시는 거부한다. `git clone --branch` 는
   해시를 받지 못해(실측) 쓰지 않는다. 인증서 검증 해제(`-c http.sslVerify=false`)는 이 git 명령들에만 붙는다 — 전역 git 설정 ·
   CA 설치 · 노드 설정 없음. 자격증명은 `withCredentials(usernamePassword)` + `GIT_ASKPASS`(`scripts/addon_askpass.sh`).
2. 실패(URL · ref · 인증 · 인증서 · 저장소 다운 · 검사)는 `unstable("[addon] unavailable: …")` + Add-on 없이 수집. host 별
   `errors[]` 없음. `currentBuild.description` 은 건드리지 않는다.
3. 이 빌드의 target(os→`linux,windows` · esxi · redfish)에 collector 가 없으면 켜지 않는다 (`check_layout.py --targets` rc 3).
4. Add-on 저장소: rule/match 제거 → `config.yml` 은 기능 이름별 설정, `software` 는 `linux`/`windows` 별 명령 목록 + 항목별
   `only`. collector 계약: `_addon_settings` 는 비어 있을 수 있으며 안전하게 처리(설정 필수면 `data: null`, 아니면 기본 동작),
   `false` 면 부르지 않음. `tools/check_layout.py` 는 최소 검사(YAML 문법 · `tasks/main.yml` · filter import). `deploy/` 삭제.
5. 메인 hook `common/tasks/addon/run_addon.yml` · 4 call site · 계약 테스트 무변경.

## 결과 (Impact)

- 메인: `Jenkinsfile_portal`(파라미터 `addonRef`, Validate 형식 검사, Gather 블록), `scripts/addon_checkout.sh` ·
  `scripts/addon_askpass.sh`(신규, 100755), 테스트 2(신규), 문서 6 + decision-log. `common/**` · `callback_plugins/**` ·
  `schema/**` · `vault/**` 무변경. 꺼진 빌드(전역 변수 없음)는 Groovy `if` 하나 차이 — 결과 byte 동일.
- Add-on 저장소 `ed8f320`(로컬 commit, push 는 사용자): 레이아웃 · 엔진 · filter · tools · config · README · 테스트 · e2e 시나리오.
- 운영: 켜기 = Master 전역 변수 등록(사용자), 끄기 = 삭제. 옛 배포 Job 과 lab 155 의 `/home/cloviradmin/clovirone-gathering-addon*`
  은 더는 쓰지 않는다.
- 하네스: rule 80 에 R1-B(Add-on 빌드별 체크아웃 Default/Allowed/Forbidden) 추가 — rule 70 R8 trigger 1 의 ADR 이 이 문서다.
  NEXT_ACTIONS 의 AO-7 · AO-10 · AO-13 · AO-14 · JV-3 을 AP 절이 대체한다.
- 실측(2026-09-29): 신규 Runner01(RHEL 9, 시스템 CA 가 GitLab 자체 서명 인증서를 모름 — `curl` 000)에서 기본값(검증 안 함)으로
  main · 40자 해시 체크아웃 성공, `ADDON_REPO_SSL_VERIFY=true` 는 실패. lab 155(Ubuntu, CA 신뢰됨)는 둘 다 성공. 짧은 해시는 둘 다 거부.
  단위 · e2e · 린터 결과와 Jenkins 실행은 evidence 파일.

## 대안 비교 (Considered)

| 안 | 내용 | 기각 이유 |
|---|---|---|
| A. 배포 Job 을 4대에 반복 | `AGENT_LABEL` 별로 노드마다 실행 | 노드 추가 · 재설치 때마다 사람이 다시 돌려야 한다. 스케줄링과 availability 의 결합 그대로 |
| B. 공유 스토리지(NFS) | 4대가 같은 경로를 마운트 | 인프라 의존 + Runner 사전 작업. 사용자 요구 ④ 위반 |
| C. Git 플러그인 `checkout` + `withEnv(GIT_SSL_NO_VERIFY)` | 자격증명 · URL 종류를 플러그인이 처리 | 플러그인이 `withEnv` 환경을 git 프로세스에 넘기는지 오프라인에서 확정 불가. 환경변수 방식은 범위 통제가 약하다. 스크립트는 단위 테스트로 행위를 고정할 수 있다 |
| D. `git clone --branch <ref> --depth 1` | 가장 짧다 | 커밋 해시를 받지 못한다 (`Remote branch <sha> not found`) — ref 계약 세 형태를 같은 흐름으로 지원해야 한다 |
| E. GitHub 미러 강제 / Runner 에 CA 설치 | TLS 문제를 인프라로 해결 | 사용자 명시 기각 — 설정으로 흡수, 환경 무관 |
| F. config 의 rule/match 유지 | 변경 최소 | rule 순서 · 첫 매치 · `match` 오타 실수 유형이 남고 "실행 여부 = target 만" 요구와 섞인다. 실제 쓰임(target 별 명령 · 용도별 명령)은 항목별 `only` 로 덮인다 |

## 후속

- JV-4: 설치 자동화 시드 사본은 production 전체(`git archive`)로 교체 — 설치 자동화 팀, 이번에 손대지 않음.
- 사용자: Add-on 저장소 push, lab · 신규 Master 에 `ADDON_REPO_URL` 등록, 옛 배포 Job 삭제.
