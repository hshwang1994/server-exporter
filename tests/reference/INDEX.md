# tests/reference/ — 전체 카탈로그

| 수집 일자 | 사용자 | 비고 |
|---|---|---|
| 2026-04-28 | hshwang1994 | Round 11 reference collection 1차 |
| 2026-10-22 | hshwang1994 | Redfish 2차 전수 미러 11대 (용인: CSUS 3200 ×3, DL380 Gen12 ×4, SR650 V4 ×4) — `redfish/mock2/` 에 서버당 zip 으로 보관 (2026-10-26 반영) |

> 이 카탈로그는 2026-04-28 수집분에서 멈춰 있다. 그 뒤로 reference 를 새로 뜬 적이
> 없어서 갱신할 내용이 없었다 — 낡은 게 아니라 그 시점이 마지막이다.
> 다음에 reference 를 새로 수집하면 위 표에 행을 추가하고 아래 채널별 항목도 함께 고친다.
> 수치와 디렉터리는 적어 두지 말고 그때그때 센다 (rule 00).

---

## 채널별 카탈로그

### Redfish (수집 완료 2026-04-28 17:15)

| Vendor | IP | 상태 | files | 비고 |
|---|---|---|---|---|
| Dell | 10.100.15.27 | OK | 2419 | iDRAC9, JsonSchemas 포함 / 15MB / 596s |
| Dell | 10.100.15.28 | OK | 1606 | iDRAC9 / 430s |
| Dell | 10.100.15.31 | OK | 1625 | iDRAC9 / 429s |
| Dell | 10.100.15.33 | OK | 1600 | iDRAC9 (10.100.64.96 OS의 BMC) / 419s |
| Dell | 10.100.15.34 | OK | 1737 | iDRAC9 / 467s |
| HPE | 10.50.11.231 | OK | 2531 | iLO5 (ProLiant DL380 Gen11) — IML/Event/SL log 포함 |
| Lenovo | 10.50.11.232 | OK | 2807 | XCC |
| Cisco | 10.100.15.1 | **FAIL** | 3 | HTTP 503 (CIMC 서비스 다운, BMC 재기동 필요) |
| Cisco | 10.100.15.2 | OK | 760 | TA-UNODE-G1 (CIMC) — JsonSchemas + Logs 포함 / 889s (BMC 자체 ~2초/req) |
| Cisco | 10.100.15.3 | **FAIL** | — | 연결 timeout (BMC 도달 불가) |

**합계**: 9 vendor 수집 OK / 2 환경 이슈 / 1 vendor 미상. 15089 redfish 파일 / 108MB.

### Redfish 2차 전수 미러 (2026-10-22 수집, `redfish/mock2/`)

용인 11대(CSUS 3200 ×3, DL380 Gen12 ×4, SR650 V4 ×4)를 `redfish_full_mirror.py` 2.2.0 으로 떠온 전수 미러를 서버당 zip 으로 보관한다 (치환 없음, 2026-10-26 사용자 결정). 서버별 상태·무결성·사용 절차는 `redfish/mock2/README.md`, 기계 판독 요약은 `redfish/mock2/MANIFEST.json`.

### OS

| Distro | IP | 상태 | 명령 | 디스크 |
|---|---|---|---|---|
| RHEL 8.10 | 10.100.64.161 | OK | 105 + ansible_setup | 911K |
| RHEL 9.2 | 10.100.64.163 | OK | 106 + ansible_setup | 848K |
| RHEL 9.6 | 10.100.64.165 | OK | 106 + ansible_setup | 856K |
| Rocky 9.6 | 10.100.64.169 | OK | 106 + ansible_setup | 818K |
| Ubuntu 24.04 | 10.100.64.167 | OK | 106 + ansible_setup | 950K |
| Windows Server 2022 | 10.100.64.135 | OK | 28 + setup | 4.3M |
| RHEL bare-metal | 10.100.64.96 | OK | 106 + ansible_setup | 1.5MB |

### ESXi

| IP | SSH | vSphere API | 명령 | 디스크 |
|---|---|---|---|---|
| 10.100.64.1 | FAIL | OK | 1 (pyvmomi만) | 2.2MB |
| 10.100.64.2 | OK | OK | 53 esxcli + pyvmomi | 4.4MB |
| 10.100.64.3 | FAIL | OK | 1 (pyvmomi만) | 3.8MB |

> SSH 비활성: vSphere Web Client → Configure → Services → SSH → Start

### Agent / Master

| Role | IP | 상태 | 명령 | 디스크 |
|---|---|---|---|---|
| Master | 10.100.64.152 | OK | 40 | 101K |
| Master | 10.100.64.153 | (수집 중) | 13 | 26K | sudo 명령 대기 의심 |
| Agent | 10.100.64.154 | OK | 40 | 98K |
| Agent | 10.100.64.155 | OK | 40 | 95K |

---

## 사고 / 발견

| # | 발견 | 영향 | 해결 |
|---|---|---|---|
| F1 | Dell BMC 사용자 user=admin이 아닌 user=root | targets.yaml + 향후 vault | RESOLVED — targets.yaml 정정 (사용자 확인) |
| F3 | Cisco 10.100.15.1 HTTP 503 / 15.3 timeout | 2대 수집 불가 | 사용자 측 BMC 재기동 / 인프라 점검 필요 |
| F4 | Win10 WinRM 5986/5985 모두 차단 | OS 1대 수집 불가 | task #10 follow-up — Windows 측 winrm quickconfig + WSL Python 측 ntlm 환경 |
| F5 | ESXi 10.100.64.1 / .3 SSH 비활성 | esxcli 53종 미수집 (pyvmomi만 OK) | SSH enable 후 `--skip-existing` 재실행 가능 |
| F6 | Master 10.100.64.153 sudo 명령 ~120s 대기 | gather_agent_env.py 개선 후보 | RESOLVED (모든 39 명령 timeout으로 자동 진행 완료) |
| F7 | HPE IML/Event/SL log entries / JsonSchemas → 시간 폭증 | crawl 시간 N배 | RESOLVED — `SKIP_PATH_PREFIXES` 확장 + `--include-logs` `--include-jsonschemas` 옵션 추가 |

---

## 통계

- **총 파일 수: 15964** (commit 대상; local/ 제외)
- **총 디스크 사용: 126MB**
  - redfish: 108MB (9 vendor)
  - os: 5.8MB (6 distro)
  - esxi: 11MB (3 host)
  - agent: 399K (4 host)
- 수집 스크립트: 4개 (`crawl_redfish_full.py`, `gather_os_full.py`, `gather_esxi_full.py`, `gather_agent_env.py`)
- 자격 처리: `tests/reference/local/targets.yaml` (gitignored)
- 모든 수집 도구 idempotent (`--skip-existing` 지원)
- Redfish crawl 옵션: `--include-jsonschemas`, `--include-logs`, `--vendor`, `--target`, `--max-depth`

## 재실행 명령

```bash
# Redfish
python tests/reference/scripts/crawl_redfish_full.py --skip-existing

# OS (WSL)
wsl python3 tests/reference/scripts/gather_os_full.py --skip-existing

# ESXi (WSL)
wsl python3 tests/reference/scripts/gather_esxi_full.py --skip-existing

# Agent + Master (WSL)
wsl python3 tests/reference/scripts/gather_agent_env.py --skip-existing
```

## 업데이트 절차

새 장비 / 새 펌웨어 / OS 업그레이드 후:
1. `tests/reference/local/targets.yaml`에 추가
2. 위 재실행 명령 (`--skip-existing`로 신규/누락분만)
3. 본 INDEX.md 표 갱신 (수치 실측 후)
4. `tests/evidence/<날짜>-<주제>.md` evidence 추가
5. 영향 시 `docs/reference/decision-log.md` Round 갱신

## 관련

- rule: 13 (output-schema-fields), 21 (output-baseline-fixtures), 96 (external-contract-integrity)
- 정본: `tests/fixtures/` (회귀 input), `schema/baseline_v1/` (회귀 기준선)
- 본 reference는 회귀 input이 아니며, 향후 schema 추가 / 매핑 검증 / vendor 온보딩 자료
