# tests/reference/ — 실장비 종합 참조 데이터

> 이 폴더는 실장비 한 대에서 뽑을 수 있는 raw 정보를 한 번에 다 긁어와 보관하는 참조용 자료실입니다. Redfish 전체 endpoint, OS 명령 결과, ESXi pyvmomi dump 등이 여기 들어옵니다.
>
> 회귀 테스트의 입력으로 직접 사용되지는 않습니다 — 회귀 입력은 `tests/fixtures/`, 기준선은 `schema/baseline_v1/` 입니다.
>
> 언제 이 폴더를 보는가?
> - 새 벤더 / 새 펌웨어가 들어왔을 때 어떤 endpoint 가 응답하는지 전수 비교
> - 새 schema 필드 후보를 검토할 때 그 정보가 raw 어디에 있는지 추적
> - 펌웨어 업그레이드 후 응답 변경을 회귀 분석으로 비교
> - 정상 시점의 raw 응답을 보존해뒀다가 장애 시점과 비교

최초 수집: 2026-04-28 (Round 11 검증 단위)

---

## 디렉터리 구조

```text
tests/reference/
├── README.md                  ← 이 파일
├── INDEX.md                   ← 전체 카탈로그 (수집 일자 / 장비 list / endpoint 수 / 디스크 사용)
├── redfish/
│   └── <vendor>/<ip>/
│       ├── _manifest.json     ← endpoint list / 상태 / timing
│       ├── _summary.txt       ← 사람이 읽는 요약
│       └── <path-derived>.json ← 각 endpoint의 raw 응답 (수천 개 가능)
├── os/
│   └── <distro>/<ip>/
│       ├── _manifest.json
│       ├── _summary.txt
│       ├── ansible_setup.json ← ansible setup 모듈 facts
│       └── cmd_<name>.txt     ← 각 shell 명령 출력 (~80개)
├── esxi/
│   └── <ip>/
│       ├── _manifest.json
│       ├── pyvmomi_host_dump.json ← pyvmomi 객체 dump
│       └── esxcli_<name>.txt  ← esxcli / vim-cmd / SSH 명령 출력 (~40개)
├── agent/
│   ├── agent/<ip>/             ← Jenkins agent 환경 (ansible / python / collection / 도구)
│   └── jenkins_master/<ip>/    ← Jenkins master 환경
├── scripts/                    ← 수집 스크립트 (재실행 가능)
│   ├── crawl_redfish_full.py
│   ├── gather_os_full.py
│   ├── gather_esxi_full.py
│   └── gather_agent_env.py
└── local/                      ← 자격 (gitignored)
    ├── targets.yaml.sample
    └── targets.yaml            ← .gitignore 등록 — 절대 commit 금지
```

## 보안

| 항목 | 위치 | commit |
|---|---|---|
| 수집 자격 (BMC user/pass, OS user/pass) | `local/targets.yaml` | **NO** (.gitignore) |
| Sample 자격 파일 | `local/targets.yaml.sample` | YES (빈 password) |
| Raw 수집 데이터 | `redfish/`, `os/`, `esxi/`, `agent/` | YES (단 OS의 sshd_config / sudoers 등 민감 파일은 사용자 검토 후 commit 결정) |
| 수집 로그 | `local/crawl_*.log` | NO |

`.gitignore`에 등록된 패턴 (해당 경로는 실행 때 생기고 저장소에는 없다):

- `tests/reference/local/*` — 단 `tests/reference/local/.gitkeep` 은 추적한다
- `tests/reference/.cache/` — 실행 때 생기는 캐시, 저장소에는 없다
- `tests/reference/**/.crawl_inflight/`

## 사용 시나리오

1. **새 vendor 온보딩**: `redfish/<vendor>/` 디렉터리에서 그 vendor의 endpoint 구조를 파악하고 adapter YAML metadata (`tested_against`, `oem_path`) 채움
2. **새 schema 필드 후보 검토**: `redfish/<vendor>/<ip>/_summary.txt`에서 OEM endpoint list 확인 → 어느 vendor에 어떤 데이터가 있는지 비교
3. **OS 매핑 검증**: `os/<distro>/<ip>/cmd_*.txt`의 raw 명령 출력을 ansible setup facts와 대조해 field_dictionary 갱신 검증
4. **회귀 비교**: 펌웨어 / OS 업그레이드 후 동일 명령을 다시 수집해 diff
5. **장애 분석 사전 자료**: 정상 동작 시점의 endpoint 응답을 확보해두고 장애 시점과 비교

## 재수집

sample을 참고해 수집 자격 (`local/targets.yaml`)을 채운 후:

```bash
# Redfish (Windows에서 직접 실행 가능)
python tests/reference/scripts/crawl_redfish_full.py --skip-existing

# OS (WSL 권장 — paramiko + ansible CLI 필요)
wsl python3 tests/reference/scripts/gather_os_full.py --skip-existing

# ESXi (WSL — paramiko + pyvmomi 필요)
wsl python3 tests/reference/scripts/gather_esxi_full.py --skip-existing

# Agent / Master 환경
wsl python3 tests/reference/scripts/gather_agent_env.py --skip-existing
```

옵션:
- `--target <name>`: 특정 장비 1대만
- `--vendor <name>`: vendor 전수 (Redfish 만)
- `--skip-existing`: 기존 파일 그대로 두고 누락분만
- `--max-depth N`: Redfish 재귀 깊이 제한

## 수집 후 정리

수집이 끝나면 사용자 검토를 거쳐 다음을 결정:
1. 디스크 비용과 가치를 견줘 raw 디렉터리 자체를 commit
2. BMC raw는 commit하고 OS sudoers 같은 민감 파일은 제외하는 식으로 일부 vendor / 일부 카테고리만 commit
3. 자격 평문을 남기지 않도록 `local/targets.yaml` 삭제

## 관련

| 자료 | 용도 |
|------|------|
| `tests/fixtures/` | 회귀 테스트의 input (raw 응답) |
| `schema/baseline_v1/` | 회귀 테스트의 기준선 (정답지) |
| `tests/evidence/` | Round 단위 검증 결과 (`tests/evidence/2026-04-28-reference-collection.md` 등) |
| [docs/reference/live-validation.md](../../docs/reference/live-validation.md) | 검증 라운드 누적 |
| [docs/develop/04-add-vendor.md](../../docs/develop/04-add-vendor.md) | 새 gather / 새 벤더 추가 절차 |
