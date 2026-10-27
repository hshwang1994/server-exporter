"""Redfish 전수 미러 재생 도구 (2026-10-27, FIX 8 로 저장소 편입 — 분석 Round 2026-10-26 의 tools/ 를 매개변수화한 판).

구성 (전부 stdlib, 네트워크 0, 비밀 0):
- mirror_policy.py       미러 트리(v1/v2) -> 재생 정책. Tier 1(HTTPS 서버)과 Tier 2(in-process)가 같은 정책을 쓴다.
- mirror_https_server.py 미러를 https://127.0.0.1/redfish/v1/... 로 되돌려 주는 재생 서버 (443 -> root 필요).
- tier2_replay.py        in-process 모듈 재생 (emulator_harness.run_gather 경로) -> GOLDEN_KEYS 산출.
- run_tier1.py           Windows 쪽 orchestrator: 미러마다 서버(WSL 배포판 A, root) -> 실제 ansible-playbook(WSL 배포판 B).
- run_playbook.sh        운영(Jenkinsfile_portal seGatherEnv + scripts/run_gather.sh)과 같은 환경·인자로 redfish-gather/site.yml 실행.
- gen_cert.sh            127.0.0.1 self-signed 인증서를 임시 디렉터리에 생성 (커밋 금지 - .gitignore).
- extract_mirrors.sh     tests/reference/redfish/mock2/*.zip 등을 ext4 로 푼다 (/mnt/c 보다 수십 배 빠르다).
- diff_tier1.py          두 Tier 1 산출 트리(before/after)의 봉투·요청 집합 diff 를 허용목록과 대조.

경로 규칙: 저장소 루트는 이 파일 기준(REPO_ROOT)으로 찾고 SE_REPO_ROOT 로만 덮어쓴다. 개인 경로·배포판 이름·vault 비밀번호
파일 경로는 전부 인자/환경변수다 (기본값에 비밀 없음). 절차·한계는 같은 디렉터리의 README.md.
"""
from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = Path(os.environ.get("SE_REPO_ROOT") or HERE.parents[2])
