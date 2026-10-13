# Linux sudo 프로브 live 매트릭스 fixture

`tests/integration/test_sudo_probe_live.py`(-m live, 기본 skip) 가 쓴다. 실 Linux 대상이 필요하며 실장비 캡처값은 없다.

| 경로 | 무엇 |
|---|---|
| `harness.yml` | 운영 site.yml 과 같은 순서로 `os-gather/tasks/linux/preflight.yml` → `try_sudo.yml` 만 태우고 결과 fact(비밀번호 · 원격 출력 없음)를 제어 노드 파일에 적는 playbook |
| `fake_sudo.sh` | sudo 의 겉모습(prompt · `Sorry, try again.` · 종료 코드 · 무응답)만 흉내 내는 스크립트. PAM 을 건드리지 않고 Ansible 이 만드는 결과 모양(rc 없음 · rc 1 · unreachable)을 재현한다. 모드는 설치 파일 이름 끝(`reject` · `rc1` · `hang`), 호출마다 `<경로>.log` 에 한 줄 |

실 sudo 로 보는 것: NOPASSWD 계정(확인 명령 1회 · 제출 0) · 비밀번호 요구 계정의 로그인 비밀번호 통과 · Vault 후보가 로그인 값과 같을 때 1회만 ·
sudo 권한 없는 계정의 정책 거부(인증은 통과, rc 1, 제출 1). 가짜 sudo 로 보는 것: 거부 → 다음 후보 · 예산에서 중단(후보당 제출 1회) ·
`passwd_tries=1` 모양(rc 1 → 보수적으로 denied) · prompt 뒤 무응답(unreachable → unavailable) · sudo 부재(rc 127).
틀린 비밀번호를 실 PAM 에 보내는 경우는 이 매트릭스에 없다 — 그 실측은 Jenkins 빌드 + auth.log 로 한다(`tests/evidence/2026-10-13-sudo-fallback-serial-required.md`).
