#!/usr/bin/env bash
# scripts/ai/promote_to_production.sh — DEPRECATED (2026-10-03, ADR-2026-10-03-production-generation).
#
# production 브랜치는 더 이상 main 의 파일 상태를 복사해 만들지 않는다. 고정 main SHA 에서 생성기가 만든
# runtime-only tree 를 gate(G01~G20) 통과 뒤 append 커밋으로 올린다:
#
#   python -m scripts.ai.prodgen build   --sha <main sha> --out <dir>
#   python -m scripts.ai.prodgen verify  --tree <dir>
#   python -m scripts.ai.prodgen promote --sha <main sha> --dry-run        # 전제: docs/operate/09-production-branch.md 3절
#
# 이 shim 은 1 cycle 뒤 삭제한다. 종전 denylist sync 는 하네스 외 모든 파일(테스트 · 문서 · 스키마 · 설명 주석)을 그대로 올렸고
# main SHA 도 기록하지 않았다 (H1). 자동 호출 경로(rule 24 R5 · rule 93 R4)도 prodgen 기준으로 바뀌었다.
echo "[promote] DEPRECATED: scripts/ai/promote_to_production.sh 는 더 이상 쓰지 않는다." >&2
echo "[promote] production 은 'python -m scripts.ai.prodgen build/verify/promote' 로만 만든다 — docs/operate/09-production-branch.md" >&2
exit 1
