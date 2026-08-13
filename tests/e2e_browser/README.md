# tests/e2e_browser — Playwright Browser E2E

> **이 폴더는** Jenkins / BMC 같은 외부 시스템의 웹 UI 까지 포함해서 server-exporter 가 정상 동작하는지 브라우저로 직접 확인하는 E2E (end-to-end) 테스트 모음입니다.
>
> 백엔드 JSON 응답만 검증하는 회귀 테스트(`tests/e2e/`)와 다르게, 본 폴더는 실제 사람이 보는 웹 화면까지 검증합니다.
> Playwright (Chromium) 으로 자동화되어 있고, lab 자격증명이 없으면 자동으로 skip 됩니다.

## 사전 조건

```bash
# 1. test deps 설치
python -m pip install -r requirements-test.txt

# 2. Playwright Chromium 브라우저 다운로드 (~150MB, 최초 1회)
python -m playwright install chromium

# 3. lab 자격증명 (gitignored)
ls vault/.lab-credentials.yml
```

자격증명 파일이 없으면 `lab` marker 테스트는 자동 skip (conftest.py).

## 실행

```bash
# 전체 Browser E2E
pytest tests/e2e_browser/ -v

# Jenkins UI만
pytest tests/e2e_browser/ -v -m jenkins

# BMC UI만
pytest tests/e2e_browser/ -v -m bmc

# 헤드 모드 (브라우저 창 보기)
pytest tests/e2e_browser/ -v --headed

# 트레이스 캡처 (디버그)
pytest tests/e2e_browser/ -v --tracing on
```

## 시나리오 list

| 파일 | 시나리오 | 상태 |
|---|---|---|
| `test_jenkins_master.py` | 마스터 dashboard 도달 | [PASS] 활성 |
| `test_jenkins_master.py` | 로그인 + jobs list | [PASS] 활성 |
| `test_bmc_webui.py` | BMC WebUI 도달 (iDRAC/iLO/XCC/CIMC) | lab 자격 있으면 활성 (marker `bmc`/`lab`) |

## Marker 정의

| Marker | 의미 |
|---|---|
| `lab` | `vault/.lab-credentials.yml` 필요 (auto-skip 미존재 시) |
| `jenkins` | Jenkins master Web UI |
| `bmc` | BMC Web UI (iDRAC / iLO / XCC / CIMC) |
| `slow` | 30초 이상 |

## CI 통합 (예정)

Jenkins agent (10.100.64.154/155)에서 실행 시:
- Chromium binary cache 필요 (150MB) → `~/.cache/ms-playwright/`
- xvfb-run 또는 `--headed=False` (default)

## 비고

- 본 디렉터리는 기존 `tests/e2e/` (pytest baseline E2E)와 별개. 기존은 backend JSON 검증 / 본 디렉터리는 Browser UI.
- 사용자 권한 부여 후: SSH 사용자 = Jenkins UI 사용자. Browser E2E 로그인 활성.

---

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| Jenkins 마스터 자체 설치 | [docs/operate/01-jenkins-master.md](../../docs/operate/01-jenkins-master.md) |
| 회귀 테스트 (백엔드 JSON) | `tests/e2e/` |
| 호환성 매트릭스 | [docs/reference/compatibility-matrix.md](../../docs/reference/compatibility-matrix.md) |
