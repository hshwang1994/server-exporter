# Tier 0 — CI gate 재검증 (HEAD `d552ae06` = C8)

- 작성: AI(Claude) · 2026-10-28. 이 세션이 직접 측정한 결과다. 공식 runner(`Jenkinsfile_ci` · `clovirone-server-gather-ci`)는 실행하지 않았다(NOT_RUN).
- 시험한 커밋은 `d552ae06041caa74d7eeb002c61c23467dccaf8f` 다. 그 뒤 커밋(C9 이 기록, C10 이 PROJECT_MAP 지문)은 기록과 지문만 바꾼다.
- 표의 수치는 `../tools/tier0_summary.py` 로 다시 낼 수 있다.

## 1. 전체 gate

| 실행 | 조건 | 결과 | 산출 |
|---|---|---|---|
| Linux 공식 등가 | WSL `Ubuntu` ext4 새 clone `~/se-fix-20261028`(`core.autocrlf` unset · `core.fileMode=true` · CRLF 파일 0). 격리 venv `~/venv-se-ci-20261028`(Python 3.12.3 · ansible-core 2.20.3 · pytest 9.2.0 · `include-system-site-packages = false`). `env -i` PATH = venv · `/usr/local/bin` · `/usr/bin` · `/bin`(pwsh · powershell.exe 없음). 명령은 `Jenkinsfile_ci` Gate 와 같다: `. scripts/activate_ansible_venv.sh` → `CI_GATE_JUNIT_DIR=… bash scripts/ai/ci_gate.sh` | **`RESULT: PASS` · rc 0**. 단계 FAIL 0 · 건너뜀 0. pytest 6250 passed · 183 skipped · 5 xfailed. integration 525 passed · 4 skipped · 1 deselected. JUnit failures 0 · errors 0. corpus 20/20 MATCH. syntax-check 3 채널 통과 | `linux-venv/`(env · pip freeze · 로그 · JUnit) |
| Windows 새 clone | `C:/github/ClovirONE/se-fix-20261028-win/new`(시스템 설정 `core.autocrlf=true` · `core.fileMode=false`). 전역 `MSYS_NO_PATHCONV=1` · `PYTHONUTF8=1` — 독립 검증의 Windows 실행과 같은 조건. Python 3.13.15 · pytest 9.1.1, ansible 없음 | **`RESULT: PARTIAL` · rc 2**. 단계 FAIL 0, 건너뜀 1(syntax-check — 실행할 수 있는 ansible-playbook 이 없다). pytest 6388 passed · 45 skipped · 5 xfailed. integration 502 passed · 6 skipped · 1 deselected. JUnit failures 0 · errors 0 | `windows-clone/` |
| (판정 제외) Windows 중단 실행 | 위와 같은 조건인데 다른 실행과 겹쳐 돌렸다(Linux gate, 이어서 WSL 재현) | 메모리 부족으로 중단됐다 — 경위와 진단은 `windows-clone-aborted-oom/README.md` | `windows-clone-aborted-oom/` |

- 계획서 7.3절의 Windows 기대값 "rc 0" 은 ci_gate 설계와 다르다. ansible 이 없는 Windows 에서는 syntax-check 를 건너뛰므로 PARTIAL(rc 2)이 나온다. 이번에 확인한 것은 실패 0 이다. syntax-check 는 Linux 실행 결과로 본다.
- 두 실행의 skip 은 서로 빠진 쪽을 덮는다.
  - Linux skip 188(JUnit 기준, xfail 5 포함): PowerShell 이 있어야 도는 시험 156(`powershell.exe 없음`) · prodgen PowerShell 파서 14 · 그 밖 18
  - Windows skip 50: Linux 전용 시험 33(bash · coreutils timeout · flock 27, `/tmp` 규칙 · symlink · 읽기 권한 · `/proc` 6) · 그 밖 17
  - 양쪽 공통 skip 17: `failed 상태가 아님` 6 · baseline stale(thermal 5 · infiniband 5) · turbo 1. Linux 의 그 밖 18 은 이 17 + `Windows 전용 quirk` 1 이다

## 2. 묶음별 FAIL → PASS 재현

조건은 같고, 수정 전(`f92ebe6a`)과 수정 후(`d552ae06`)만 다르다.

| 묶음 | 환경 | 수정 전 | 수정 후 | 원인과 수정 | 산출 |
|---|---|---|---|---|---|
| G1 seam guard | WSL 로그인 셸 — 시스템 python3 + 사용자 site pytest 9.0.3, `core.fileMode=true`, PATH 에 interop `powershell.exe` | 2 failed — 하위 실행에서 `No module named pytest` | 2 passed | pytester 하위 실행이 `HOME` 을 바꿔 사용자 site 를 못 봤다 → `PYTHONUSERBASE` 고정 + 하위 pytest 실행 단언(C4 `c73db2ce`) | `repro-wsl/G1_*.log` |
| G2 prodgen 임시 저장소 | 위와 같음 | 4 failed · 14 passed — `G09 app/run.sh: git mode 100644 != manifest mode 100755` | 19 passed(기존 18 + G09 음성 시험 1) | `core.fileMode=true` 에서 `commit -a` 가 실행 비트를 644 로 되돌렸다 → 디스크 파일 `chmod 0o755`, class B 단언 강화(C4) | `repro-wsl/G2_*.log` |
| G3 `tests/unit/test_windows_*` 13파일 | 위와 같음 | 81 failed · 310 passed | 81 failed · 310 passed — 실패 시험 ID 81개가 전후 같다 | interop `powershell.exe` 에 Linux 경로 · 환경변수가 전달되지 않는다. 공식 runner 에는 PowerShell 이 없는 조건이라 이번에 고치지 않았다(skip 동작 변경 — 별도 승인 후속) | `repro-wsl/G3_*.log` · `G3_files.txt` |
| G4 · G5 | Windows 새 clone(`core.autocrlf=true` · 전역 `MSYS_NO_PATHCONV=1`). 수정 전은 `--no-checkout` clone 뒤 `f92ebe6a` 를 처음부터 checkout 했다(CR: `sample.cfg` 12 · `finalize_corpus_check.py` 254 · `SHA256SUMS` 11) | 15 failed · 52 passed — `test_addon_checkout` 10(G4) + prodgen golden 4 · `test_jenkinsfile_ci` LF 1(G5) | 67 passed(같은 3파일 CR 0) | G4: 시험 하위 프로세스 env 에서 `MSYS_NO_PATHCONV` · `MSYS2_ARG_CONV_EXCL` 을 뺀다. G5: `.gitattributes` 에 eol=lf 3줄(C4) | `repro-windows/G4G5_*.log` |

- 독립 검증이 보고한 수와 같다: Windows 15 = G4 10 + G5 5, WSL 87 = G1 2 + G2 4 + G3 81.
- `repro-windows/G4G5_base_mixed_checkout.log` · `G4G5_new_run1.log` 는 첫 시도다.
  - 첫 시도의 base clone 은 브랜치 HEAD(eol 속성 있음)를 먼저 풀고 `f92ebe6a` 로 옮겼다. git 은 blob 이 같은 파일을 다시 쓰지 않아 LF 가 남았고, 그래서 G5 가 재현되지 않았다(10 failed — G4 만).
  - 스크립트를 `--no-checkout` 으로 고쳐 다시 돌렸다. 판정은 `G4G5_base.log` · `G4G5_new.log` 로 한다.

## 3. 공식 runner 와 다른 점 · 남은 것

- **공식 runner: NOT_RUN** — `clovirone-server-gather-ci` 는 `*/main` 수동 빌드라 이 브랜치를 그대로 돌릴 수 없다. 운영 담당자가 Runner 셸에서 이 브랜치를 clone 해 같은 명령을 실행해야 닫힌다.
  - 확인할 것: venv `pyvenv.cfg` 의 `include-system-site-packages` · pytest 버전 · Gate 단계 PATH 에 pwsh 없음 · git `core.autocrlf` · `core.fileMode` · `RESULT: PASS` · JUnit 보관
- Linux 등가 실행은 Toolchain 단계의 pwsh 부트스트랩을 거치지 않았다. Gate 단계가 별도 `sh` 이므로 그 PATH 에 pwsh 가 없다고 보았다. 이 가정은 공식 runner 에서 확인해야 한다.
- WSL 기본 셸(interop 켜짐)에서 ci_gate 를 돌리면 G3 81건 때문에 FAIL 이다. 공식 runner 에는 없는 조건이라 후속으로 남긴다.
- 실행 경위
  - 첫 Windows clone 을 scratchpad 아래에 두었다가 경로가 260자를 넘어 checkout 단계에서 실패했다(`Filename too long`, 산출물 없음). 그래서 짧은 경로로 옮겼다.
  - Windows gate 를 Linux gate 와 겹쳐 돌렸고, Linux gate 가 끝난 뒤 WSL 재현까지 겹쳐 시작했다가 메모리 부족으로 둘 다 중단됐다. 사용자 결정(2026-10-28, "순차로 다시 실행")에 따라 한 번에 하나씩 다시 돌렸다. `repro-wsl/` 은 그 재실행 결과다.
- git 설정은 판정에 쓰는 키(`core.autocrlf` · `core.fileMode` · `core.quotepath`)만 `env.txt` 에 적었다. 전체 `git config -l` 은 사용자 정보가 섞여 있어 남기지 않았다.
- Windows 에서 만든 로그는 커밋 전에 줄 끝만 LF 로 바꿨다(내용 변화 없음). 아래 sha256 은 그 LF 파일 기준이다.

## 4. 재현 (`../tools/`)

```bash
# Linux 공식 등가 — WSL Ubuntu. venv: tier0_mk_venv.sh (python3.12 -m venv --without-pip → 시스템 pip --python 부트스트랩 →
#   pip install -r requirements-test.txt 'ansible-core==2.20.3' pywinrm pyvmomi → ansible-galaxy collection install community.vmware ansible.windows -p <venv site-packages>)
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash /mnt/c/<저장소>/tests/evidence/2026-10-28-redfish-mock2-review-fix/tools/tier0_wsl.sh <HEAD> gate
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash /mnt/c/<저장소>/tests/evidence/2026-10-28-redfish-mock2-review-fix/tools/tier0_wsl.sh <HEAD> repro   # G1 · G2 · G3
# Windows — Git Bash. 스크립트 안에서 전역 MSYS_NO_PATHCONV=1 을 켠다(독립 검증 조건). 그래서 경로는 전부 C:/… 형식이어야 한다
bash tests/evidence/2026-10-28-redfish-mock2-review-fix/tools/tier0_win.sh <HEAD> gate
bash tests/evidence/2026-10-28-redfish-mock2-review-fix/tools/tier0_win.sh <HEAD> repro      # G4 · G5
python -I -X utf8 -B tests/evidence/2026-10-28-redfish-mock2-review-fix/tools/tier0_summary.py tests/evidence/2026-10-28-redfish-mock2-review-fix/tier0
```

- 스크립트 안의 경로(clone · venv · 저장소 · 증거 폴더)는 이 세션의 값이다. 다른 환경에서는 바꿔 쓴다. 한 번에 하나씩 돌린다.
- `tools/tier0_*` 는 실행한 스크립트와 바이트가 같다. `tier0_win.sh` 의 gate 부분은 최종 Windows gate 를 만든 그대로이고, repro 부분은 `--no-checkout` 수정 뒤 판본이다.

| sha256 | 파일 (`tier0/` 기준, `../` 는 증거 폴더) |
|---|---|
| `2a7d5dc295f5447d67ee91afb0ad3dedc1b737c30a16b1e25054af4e2ff690a7` | `linux-venv/ci_gate.log` |
| `7a3ce7e5edd7f5052431040daa0b827a1446f7d1b21ed8c9861ca052db4f3bde` | `linux-venv/ci_gate_junit_unit.xml` |
| `f4bcf191176984d2517d4cb6838866e86aae8d1a7bd9ec9d9b5f32368b00fa2d` | `linux-venv/ci_gate_junit_integration.xml` |
| `98e3a40d6850068598fa091dcb25af12eb4224789cf169f0e96ef16a90367b95` | `windows-clone/ci_gate.log` |
| `5d49f24b65dfcb54de8f2c2635330daa3f15ae5b7bcf6079a796aa0051c72636` | `windows-clone/ci_gate_junit_unit.xml` |
| `6fac3b7df3ab86fea815376cb90620bfbd5b70573b6ac7423affdac976caf7f9` | `windows-clone/ci_gate_junit_integration.xml` |
| `95e61c4dc9e486c38463fbf136ce3694451325159360e565c517fbcfb487856e` | `repro-wsl/*.log` · `repro-windows/*.log` 10개 — `tier0/` 에서 `sha256sum repro-wsl/*.log repro-windows/*.log` 를 이 순서로 돌린 출력(`<hash>  <경로>`, 공백 2칸 — Git Bash 의 ` *` 표시는 공백으로 바꿈)의 sha256 |
| `a7993fe5a8ef7c5a5601ceb287d7ce72c973d5ed091f03e8e6ea97915d6be775` | `../tools/tier0_wsl.sh` |
| `e64109bd28b32e764d65aea1bc6b2f704855d9bb804e64efeba9920aea160a4f` | `../tools/tier0_win.sh` |
| `2345bd947464b9d790b00cb07b60b1aebe4e5c2d9ed08fe23f7dc2cdfdc59415` | `../tools/tier0_mk_venv.sh` |
| `65d4893cdbce707d3d5d542ddd5a0b1a4118cb6ba7c1a3fa858c6d8092ce2127` | `../tools/tier0_summary.py` |
