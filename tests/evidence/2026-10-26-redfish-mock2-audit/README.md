# 2026-10-26 Redfish 2차 Mock 11대 전수 분석 Round — 증거 디렉터리

> 목적: 용인 2차 Redfish 전수 미러 11대(CSUS 3200 ×3, DL380 Gen12 ×4, SR650 V4 ×4)와 1차 미러 7대를 근거로 **기존 Gathering 코드·테스트·ADR 을 교차 검증**해
> 수집 누락·잘못된 값·오류·중복·탐색 부족·테스트 허점을 찾고 수정 계획을 만든다. **이 Round 는 분석 단계다 — 제품 소스·ADR·기존 테스트·Mock 원본은 수정하지 않았다.**
> 검증 기준은 Mock 실측이다(코드의 현재 동작을 정답으로 두지 않는다). JSON 결과 스키마(키·타입·계층)는 고정한다.

## 디렉터리

```text
tests/evidence/2026-10-26-redfish-mock2-audit/
├── README.md            ← 이 파일 (사전 점검 결과 · 구조 · 재현 절차)
├── precheck/            ← Git 상태 · 18개 미러 manifest 요약 · 비밀값 재스캔 · 아카이브 대조 결과
├── inventory/           ← 2차 11대 자원 단위 인벤토리(jsonl, 서버당 1파일) + INVENTORY.md 요약 + _summaries.json
├── baseline/            ← 수정 전 기준선: tier0(기존 회귀) · tier1(실제 playbook 경로) · tier2(모듈 수준 재생) · coverage(노출 vs 요청) · adapter 선택
├── tools/               ← 이 Round 에서 쓴 재생·인벤토리 스크립트 (분석 단계 산출물 — 제품 코드 아님, 저장소 편입 여부는 구현 계획의 결정 항목)
├── analysis/            ← 분석 작업자 6개의 영역별 보고서 01~06 (+ coverage.json) + 07 메인 추가 검증(2026-10-27, CSUS FC HBA 링크 유추 원천)
├── coverage/            ← 11대 × 12 영역 = 132칸 판정표
├── ISSUES.md            ← 통합 이슈 목록 (중복 제거 · 고유 ID · 공통 원인 → 증상 → 영향 → 수정 위치 → 회귀)
└── SUMMARY.md           ← 최종 요약
```

Mock 아카이브 자체는 `tests/reference/redfish/mock2/` (main 커밋 `7c22ca4a`, README 와 MANIFEST.json 포함). 1차 미러 7대는 저장소에 두지 않았다(외부 `C:\github\서버mock데이터\1차`, 읽기 전용) — 2026-10-26 사용자 결정.

## 사전 점검 결과 (2026-10-26)

| 항목 | 결과 |
|---|---|
| 모델 / 하네스 | 메인 Claude Fable 5.1 (`claude-fable-5-1`, effort=max), Claude Code 2.1.310. 분석 작업자도 Fable 5.1 / max, `Agent(isolation:"worktree")` 로 worktree·브랜치 격리, 동시 3개. Agent Teams 도구는 이 세션에 없음. Ultracode/Workflow 미사용 |
| Git | 시작 `main`=`e0a4f143`(clean). origin(GitHub+GitLab push)·internal(GitLab) 모두 응답, 세 브랜치 SHA 로컬과 일치. GitHub 는 공개 저장소 — 사용자가 "더미화된 안전 자료" 로 결정해 치환 없이 Push |
| Mock 보관 | `tests/reference/redfish/mock2/` zip 11 + run.log + SHA256SUMS + MANIFEST.json + README.md → main `7c22ca4a`, fingerprint 갱신 `e8b5ae9b`, `git push origin main` 뒤 origin/internal main = `e8b5ae9b` 대조 일치 |
| 아카이브 무결성 | zip 재추출 ↔ 원본 11대 파일 수·상대경로·sha256 전수 대조: 누락 0 · 차이 0 (`precheck/archive_verify.log`). 추출본 모듈 재생 = 원본 재생 11/11 동일 |
| 민감정보 | 비밀값 4종(X-Auth-Token 값 · Bearer · PRIVATE KEY · 실제 "Password" 값) 1차+2차 70,657 파일 스캔 0건 (`precheck/secret_rescan.log`; `"Password"` 12건은 Lenovo 스키마 설명문). 식별 정보(IP·호스트명·시리얼·MAC·계정명·인증서·첨부물)는 사용자 결정으로 보존 |
| 2차 11대 상태 | DL380 Gen12 ×4 COMPLETE, CSUS ×3 / SR650 V4 ×4 INCOMPLETE(장비 측 5xx·timeout 리소스 — Gathering 이 읽지 않는 경로). 상세 `precheck/manifests_summary.json`, `inventory/INVENTORY.md` |
| 1차 7대 | v1 레이아웃(헤더 있음, fsmap/links/raw 없음, 비-2xx 상태 정보 없음). 2차와 다른 장비. 저장소 축약 fixture `real_*` 는 이 미러에서 만든 것 |
| Replay 수단 | `replay_full_mirror.build_response_map` + `emulator_harness.run_gather`(모듈 수준) 11+7 모두 재생 가능. 실제 엔진 경로는 `tools/mirror_https_server.py`(미러 재생 HTTPS 서버, WSL root 배포판 127.0.0.1:443) + `tools/run_playbook.sh`(운영 `scripts/run_gather.sh`·`Jenkinsfile_portal seGatherEnv` 와 같은 인자·환경으로 `redfish-gather/site.yml` 실행, WSL Ubuntu ansible-core 2.20.7) |
| Vault | 실제 `vault/common/redfish/standard.yml` 과 `vault/<loc>/...` 전부 로컬 키로 복호화 가능(값 미출력). WSL 에서는 `/mnt/c` 의 `.vault_pass` 가 실행 비트 때문에 "script" 로 취급돼 실패 → 600 권한 사본(`~/.se_vault_pass`)으로 실행 |
| 환경 메모 | Windows `LongPathsEnabled=0` 이라 scratchpad 아래 추출 불가 → 추출 루트 `C:\github\ClovirONE\mock2-audit-20261026\extract\`. WSL `/mnt/c` 경유 미러 로딩은 분 단위로 느려 `/root/se_mirrors/` 로 복사해 재생(0.7초) |

## 재현 절차 (요약 — 명령은 `tools/` 와 `baseline/README.md`)

1. zip 추출: `python tools/verify_archive.py <archive_dir> <extract_root>` (원본 대조 포함) 또는 `python -m zipfile -e <zip> <dir>`.
2. Tier 2: `SE_REPO_ROOT=<repo> python tools/tier2_replay.py <out> <label>=<mirror_dir> ... [--layout rmc_primary --firmware-scope complex_only] --tag <tag>`.
3. Tier 1: WSL root 배포판에서 `bash tools/gen_cert.sh` → `bash tools/extract_mirrors.sh <scratchpad_linux_path>` → Windows 에서 `MSYS_NO_PATHCONV=1 python tools/run_tier1.py <label>=/root/se_mirrors/<server> ... --loc yi`
   (서버 시작 → `tools/run_playbook.sh` → 서버 종료를 미러마다 반복; 산출 `baseline/tier1/<label>/`).
4. 인벤토리: `python tools/build_inventory.py <extract_root> <out> --tier1-root baseline/tier1 --coverage-root baseline/coverage`, 요약 `tools/summarize_baseline.py`.
5. 노출 vs 요청: `python scripts/ai/redfish_coverage_diff.py <mirror> [--layout rmc_primary] --json out.json`.

## 관련

- 계획(분석 단계 지시서 반영): Plan Mode 승인본 — 이 디렉터리의 SUMMARY.md 에 요약
- 아카이브: `tests/reference/redfish/mock2/README.md`
- 수집 절차: `docs/develop/08-onsite-capture.md`
