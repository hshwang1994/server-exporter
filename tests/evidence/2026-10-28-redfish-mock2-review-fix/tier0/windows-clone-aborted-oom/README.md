# 중단된 Windows gate 실행 — 판정에 쓰지 않는다

- 실행: 2026-10-28 12:57 KST 시작, HEAD `d552ae06`(C8), 새 clone `C:/github/ClovirONE/se-fix-20261028-win/new`(`core.autocrlf=true` 시스템 설정 · `core.fileMode=false`), 전역 `MSYS_NO_PATHCONV=1` · `PYTHONUTF8=1`(독립 검증 Windows 실행과 같은 조건). 환경은 `env.txt`.
- 경위:
  - 앞부분은 Linux 공식 등가 gate(WSL, `../linux-venv/`, 12:56~13:03)와 **겹쳐** 돌았다. Linux gate 가 끝난 뒤 13:04 에 WSL 재현(G1 · G2 · G3)을 또 겹쳐 시작했고, 23초 뒤 시스템 메모리가 부족해져 Claude Code 가 두 백그라운드 작업(이 Windows gate · WSL 재현)을 멈췄다(직후 32 GB 중 여유 약 3.9 GB, 브라우저 약 6 GB · WSL VM 약 2 GB 사용).
  - 같이 멈춘 WSL 재현은 G1 까지만 끝나 있었다. 순차 재실행이 같은 `../repro-wsl/` 에 다시 썼고, 판정은 그 결과로 한다.
  - 바깥 셸만 멈추고 하위 프로세스는 살아남았다. AI 가 13:06 무렵 남은 프로세스(python · bash)를 직접 멈췄다.
  - 그래서 main pytest 는 수집 6,438건 중 앞 2,230건 지점에서 `FAIL (rc=127)`(강제 종료)로 기록됐다. ci_gate 는 integration(`502 passed, 6 skipped, 1 deselected`)을 마친 뒤 `RESULT: FAIL` 로 끝났고, unit JUnit 은 쓰이지 않았다.
- 멈춘 지점까지 F 20 · E 31 이 나왔다. 진행 문자열을 같은 clone 의 `--collect-only` 순서에 대응시키면, 하위 프로세스(git · bash · PowerShell)를 쓰는 시험 12파일이다(`diagnosis/fe_positions_by_file.txt`).
- 같은 clone · 같은 환경변수(`MSYS_NO_PATHCONV=1 PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1`)로 그중 4파일을 따로 돌렸더니 전부 통과했다.
  - `test_check_project_map_drift.py` · `test_env_guard.py` · `test_activate_ansible_venv.py`: 23 passed(`diagnosis/rerun_3files.log`)
  - `test_addon_checkout.py`: 20 passed(`diagnosis/rerun_addon_checkout.log`). 독립 검증에서 G4 10건이 실패했던 파일이다.
- 판단: 메모리 압박 아래서 하위 프로세스 생성이 실패한 환경 요인으로 본다. **추정**이다 — 실패 메시지가 담긴 JUnit 이 쓰이기 전에 멈춰서 메시지는 없다.
- 처리: 사용자 결정(2026-10-28, "순차로 다시 실행")에 따라 다른 실행과 겹치지 않게 단독으로 다시 돌렸다. 판정은 `../windows-clone/` 결과로 한다.
- 앞선 시도(12:5x)는 clone 을 scratchpad 아래에 두었다가 경로가 260자를 넘어 checkout 단계에서 실패했다(`Filename too long`, 산출물 없음). 그래서 clone 경로를 위의 짧은 경로로 옮겼다.
