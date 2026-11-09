"""장시간 실행 도구 — 메모리 압박으로 Claude Code 가 백그라운드 셸을 정리해도 끊기지 않는 실행 (2026-11-09).

배경: 시스템 메모리가 부족해지면 Claude Code 는 백그라운드 셸을 정리하고, 그 셸이 잡고 있던 대기 · 실행도 함께 끝난다
(2026-10-15 · 2026-10-28 전체 시험, 2026-11-09 승격 체인의 CI 대기). 그래서 수십 분이 넘는 일은 셸에 묶지 않는다.

  1. 분리 실행   — `start` / `promote-chain --detach`: 호출한 셸과 분리된 프로세스로 띄운다(Windows: 새 프로세스 그룹 · 창 없음 ·
                   가능하면 job object 이탈, Linux: 새 세션). 출력은 작업 폴더의 `detached_<시각>.log`, PID 는 `pid.txt`.
  2. 빌드 기록   — Jenkins 빌드 번호를 얻자마자 `<기록>.started` 에 한 줄 남긴다. 프로세스가 중간에 죽어도 번호가 남는다.
  3. 이어받기    — 다시 실행하면 기대대로 끝난 시나리오는 두고, 넣고 끝나지 않은 빌드는 새로 넣지 않고 이어서 기다린다.
                   투입 시점의 관측이 증거인 시나리오(E2E-A2 tip 관측 · T5 중단 시점)는 이어받지 않고 새로 넣는다.
  4. 파일 감시   — `watch`: 로그의 새 줄만 읽고 읽은 위치를 `watch_offset.txt` 에 남긴다. 감시(Monitor)가 끊겨도 다시 걸면
                   빠짐 · 중복 없이 이어진다. 감시가 죽어도 실행은 계속된다.

명령: `python -m scripts.ai.longrun {start,watch,status,promote-chain}` (저장소 루트에서). 정본 규칙: `.claude/rules/80-ci-jenkins-policy.md` R7 · R8.
자격 파일(netrc · vault 비밀번호)은 경로만 자식 프로세스(curl · prodgen)에 넘긴다. 이 패키지는 그 내용을 읽지도 출력하지도 않는다.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_HOME = Path.home() / ".se_longrun"
