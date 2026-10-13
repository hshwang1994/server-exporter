# ADR 2026-10-13 — Linux sudo 를 Vault 후보로 확인하고, OS 채널의 Serial Number 를 필수로 한다

- 상태: Accepted
- 결정: 사용자 (2026-10-13 대화 — 요구사항 제시 · 계획 승인 · 후보 수/순서/잠금 예산/버전 비의존 4개 항목 확정)
- 작성: AI (Claude Code)
- 관련: CLAUDE.md §4 §6 §12 (본문 의미 변경 → 본 ADR, rule 70 R8), rule 13 R8 (status 시나리오 매트릭스 동반 갱신),
  rule 96 R1-B (envelope shape 보존), rule 80 R1 (task timeout 금지), rule 27 (Precheck 에 인증 없음 — sudo 확인은 수집 단계)
- 뒤집는 결정: 2026-04-28 "식별자 수집 실패는 non-fatal (status · sections 불변)", 2026-10-10 C10 "sudo 비밀번호는 Vault 단일 값 또는 로그인 비밀번호 1개"

## 컨텍스트 (Why)

1. 고객 환경에 NOPASSWD 를 허용하지 않는 Linux 서버가 있다. 종전 코드는 sudo 비밀번호를 한 값(Vault `ansible_become_password`
   또는 로그인 비밀번호)으로 고정했고 NOPASSWD 확인도, 후보 목록도, 거부 뒤 멈추는 장치도 없었다. 값이 틀리면 특권 태스크 4개
   (제조번호 · UUID · dmidecode · 방화벽)가 각각 `Incorrect sudo password` 로 끝나 host 당 PAM 실패가 4번 쌓였다 —
   RHEL faillock 기본(deny=3 / fail_interval 900s)이면 SSH 계정이 잠긴다.
2. Serial Number 가 없어도 `hardware` 섹션은 vendor/model 만으로 success 라 **Serial 이 null 인 host 가 `status: success`** 로 나갔다.
   Portal 의 자산 매칭은 Serial 을 기준으로 하므로 사용자는 "Linux · Windows 모두 Serial 필수, 없으면 그 host 는 failed, 다른 섹션 값은 보존" 을 요구했다.
3. 사용자 제약: 계정이 절대 잠기면 안 된다 · 새 failure_code 를 만들지 않는다 · 수집 로직에 Ansible/sudo 버전을 고정하지 않는다 ·
   Windows 인증 구조는 바꾸지 않는다.

확인한 사실(코드 · 소스 · 실장비):
- sudo 는 표준 sudoers 에서 **호출 계정 자신의 비밀번호**를 PAM 으로 검증한다. 방금 SSH 를 통과한 로그인 비밀번호는 거부될 수 없으므로
  로그인 비밀번호를 먼저 보내면 SSH 계정의 잠금 카운터는 올라가지 않는다. 로그인 비밀번호와 다른 sudo 비밀번호는 `Defaults targetpw/rootpw`
  (root 비밀번호) 서버에서만 존재한다 → Vault 목록은 그 서버를 위한 것이고, 틀리면 root 카운터에 쌓인다.
- Ansible become(sudo 플러그인)은 비밀번호가 비면 `-n`(비대화식)을 유지해 비밀번호를 보내지 않고, 비밀번호가 있으면 prompt 에 응답한다.
  비밀번호 거부는 Ansible 이 prompt 단계에서 세션을 끊어 결과에 `rc` 가 없고(PAM 실패 1회), 정책 거부(sudoers 부재)는 sudo 가 끝까지 돌아 `rc` 가 남는다.
  → 결과 **구조**(rc 유무 · 값 · unreachable · 출력 줄)만으로 "비밀번호 거부" 와 "권한 없음" 을 가를 수 있다. 문자열 파싱이 필요 없다.
- 잠금 정책 파일(`/etc/security/faillock.conf`, `/etc/pam.d/*`)은 0644 라 비특권으로 읽을 수 있다.
- 10.100.64.132(사용자 지정 테스트 서버)는 Ubuntu 24.04 VM, cloviradmin NOPASSWD, pam_faillock 미사용.
- task `timeout:` 은 `failed_when` 을 우회해 rescue 로 떨어뜨린다(rule 80 R1 금지와 일치) — 프로브에 쓰지 않는다.

## 결정 (What)

1. **sudo 확인 단계 추가** (`os-gather/tasks/linux/try_sudo.yml` + `try_one_sudo.yml`, SSH 인증 · preflight 뒤):
   root 로그인 → 생략. NOPASSWD 확인 = become 없는 raw `sudo -k -n /bin/sh -c 'id -u'`(제출 0회). 비밀번호가 필요하면
   후보 = **로그인 비밀번호 → Vault `sudo_passwords` 순서**(같은 값 1회). 판정은 결과 구조만: 통과 / 비밀번호 거부(다음 후보) /
   정책 거부 · sudo 없음 · 전송 실패 · 대기 초과 · 알 수 없는 모양(즉시 중단). 결과 `_l_sudo_ok` 가 특권 태스크 4개를 게이트하고
   `_l_sudo_meta` 가 `diagnosis.details.sudo` 로 나간다(비밀번호 · 원격 출력 없음).
2. **잠금 예산** (`preflight.yml` 이 host 마다 계산, 변수 `_l_sudo_max_rejections` 하나): 잠금 모듈 없음 또는 `even_deny_root` 없음 → 3,
   `even_deny_root` 있음 → max(1, min(3, deny − 2))(`unlock_time=0` 이면 1 더 감산, 최소 1), pam 파일을 못 읽음 → 1.
   거부 횟수가 예산에 닿으면 후보가 남아도 멈춘다. 남는 위험(targetpw + even_deny_root 서버의 15분 안 반복 수집)은 콘솔 advisory 와 문서로 안내한다.
3. **Vault 스키마 확장** (`vault/<loc>/os/linux.yml`): `sudo_passwords: [{label, role, password}]`. 레거시 `ansible_become_password` 는 목록이 없을 때
   후보 1개. 정규화는 `module_utils/credential_common.normalize_sudo_passwords` 한 곳. 구성: git = Primary + Fallback 1 (2개), ic/yi/cj = Primary 1개.
   세 번째 후보로 제시된 값은 둘째 값의 대소문자 변형이고 근거가 없어 넣지 않았다.
4. **OS Serial Number 필수** (`os-gather/tasks/normalize/require_serial.yml`, 조립된 봉투 후처리 — 정상 경로 build_output 끝 · Linux/Windows rescue):
   `correlation.serial_number` 가 null(자리표시자 포함)이면 `status: failed`. `failure_reason` 이 비어 있으면 stage `gather` · code `GATHER_FAILED` ·
   문장 `serial_missing`(카탈로그 신설, `os` 채널) 을 채우고 대표 오류를 `errors[0]` 에 둔다. 이미 있으면(rescue · H12) 문장은 유지하고 status 만 failed.
   `failure_stage` 가 `auth` 등 gather 이전이면 손대지 않는다. sections · data · hostname · meta · correlation 은 보존한다 — status 시나리오 **E**.
   원인은 `diagnosis.details.serial_number.cause`(privilege_unavailable · read_failed · not_provided · facts_failed · not_collected · unknown).
5. **새 failure_code / stage / envelope 필드 없음.** 추가는 `diagnosis.details.sudo` · `diagnosis.details.serial_number`(확장 영역)와 문장 key 1개.
6. **버전 비의존**: `ansible_version` 분기 · 버전 고정 시험 없음. 검증은 Runner 의 현재 Ansible 로 실측하고 결과 모양을 fixture 로 기록한다.

## 결과 (Impact)

- Portal 은 이제 `status: failed` 인데 `sections.*: success` 이고 `data` 가 찬 봉투(시나리오 E)를 OS 채널에서 받을 수 있다
  (`docs/contract/03-fields.md` 4절 · `02-output-envelope.md` · `04-failure-and-diagnosis.md`).
- host 당 원격 실행 +1(NOPASSWD 확인) ~ +1+후보 수. 권한이 없는 host 는 특권 태스크 4개를 건너뛰어 PAM 실패가 종전 4회에서 0회로 준다.
- `REQUIREMENTS.md` 의 sudo 는 "선택" 에서 "필수(Serial Number)" 로 바뀐다. UUID · 메모리 슬롯은 종전처럼 non-fatal.
- 승격 전제(S1/S3/S4/S5 전 host success)에 Serial 이 들어가므로 명부 host 에 sudo 가 없으면 승격이 막힌다 — 사용자 결정 사항.

## 대안 비교 (Considered)

| 대안 | 기각 이유 |
|---|---|
| Vault 후보를 로그인 비밀번호보다 먼저 | 표준 sudoers 에서 Vault 값이 로그인 비밀번호와 다르면 매 실행 틀린 제출이 SSH 계정 카운터에 쌓인다(15분 누적 잠금) |
| 틀린 제출 고정 상한(2 또는 3) | deny 가 2 인 사이트·영구 잠금(unlock_time=0)·root 잠금(even_deny_root) 을 구분하지 못한다 → 대상 정책을 읽어 계산 |
| 새 failure_code `AUTHORIZATION_FAILED` 등 | code 는 호출자 분기용 고정 enum(field_dictionary · 계약 테스트). 원인 구분은 details 로 충분하고 소비자 영향이 없다 |
| 설치된 ansible-core 소스를 단언하는 계약 시험 | 수집 로직에 버전을 고정하는 행위 — 사용자 금지. 동작은 live 매트릭스와 결과 모양 fixture 로 재확인한다 |
| 프로브에 `timeout:` | `failed_when` 우회 → rescue 로 봉투가 실패하고 rule 80 R1 금지 항목 |
| Serial 누락을 `partial` 로 | 사용자 정책이 "failed" 다. 섹션 결과와 분리해 E 로 문서화 |
