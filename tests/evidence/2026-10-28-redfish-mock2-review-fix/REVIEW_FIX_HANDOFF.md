# 독립 재검증 핸드오프 — 2차 Mock 구현 독립 검증 결함 정정 (2026-10-28)

- 작성: AI(Claude) · 2026-10-28. 이 세션은 자기 결과를 PASS 로 확정하지 않는다 — 새 독립 세션의 재검증을 요청한다. 병합 여부는 그 뒤 사용자 결정이다(main 병합 · production 승격 안 함).
- 대상 브랜치 `fix/redfish-mock2-review-20261028`, 기준 `f92ebe6a`(독립 검증을 받은 구현 브랜치 `fix/redfish-mock2-20261027` 의 HEAD — 그 브랜치에는 커밋을 더하지 않았다).
- 입력: 독립 검증 보고서 `C:\github\ClovirONE\se-indep-20261027\INDEPENDENT_REVIEW_RESULT.md`(52,739 B, sha256 `0e9ab0e6a6f9b13d809dc38ebe73c830a28b46cfd0baa4714a102f0c8e01b60b`) — 읽기만 했다.
- 실장비 검증 0건. 근거는 전부 Mock 미러(실장비 캡처본) 재생과 합성 시험이다.

## 1. 결함별 결과

| # | 처분 ID | 종류 | 결과 | 커밋 |
|---|---|---|---|---|
| F-01 | 03-network-002 | 코드 · 문서 · 처분 | **부분 해결** — SR650 V4 20건 보충(up 14 · down 6), sr650_v4_02 `NIC6` · _04 `NIC4` 미해결 HOLD(`unknown` 유지). `01-f01-nic-link-fill.md` | `db606f1c` |
| F-02 | 05-thermal-003 | 처분 | FIXED (a)(c) + HOLD (b) 병기 — (b) Sensor GET 보충은 구현하지 않음(CSUS +377 GET, 미러 Sensor 377개 값 없음) | 처분 문서 |
| F-03 | 03-storage-001 (a) | 코드 · 처분 | 전원 Off notice 에 '네트워크'(사용자 결정 Q2). dl380_gen12_03 network 칸 근거를 새 notice 로 교체(PASS 유지) | `ac368a4b` |
| F-04 | 01-correlation-010 · 06-bmc-005 | 문서 · 주석 | 사전 · 03-fields `correlation.bmc_ip` = `data.bmc.ip`(①②③), `host_ip` = 요청 대상 주소 | `0e3bcbb3` · `ac368a4b`(주석) |
| F-05 | 02-cpu-002 | 문서 · 하네스 | RMC 1.77.30 LPC 는 HT 설정과 무관하게 ΣTotalThreads | `0e3bcbb3` · C8 |
| F-06 | 02-cpu-006 | 처분 | 활성 코어 신호 11대(6 + 5) == TotalCores, CSUS 7 신호 없음 | 처분 문서 |
| F-07 | 03-network-003 | 문서 | 예시 25600 ↔ 25000 | `0e3bcbb3` |
| F-08 | 05-power-005 | 문서 | 원천 legacy `PowerControl[0].PowerCapacityWatts` → PSU 용량 합, `CapacityWatts` 미사용 | `0e3bcbb3` |
| F-09 | 04-firmware-012 | 문서 | sr650_v4_02 봉투 2항목 그대로 | `0e3bcbb3` |
| F-10 | (하네스) | 하네스 | 지문을 `core.quotepath` · 콘솔 인코딩 무관하게, 마지막 커밋에서 갱신 | `499ed7c5` · C10 |
| CI gate 102 | — | 시험 · 저장소 속성 | 제품 결함 0. G1 · G2 · G4 · G5 시험 보강(skip 추가 · 시험 삭제 0), G3 81건은 후속 | `c73db2ce` |
| HBA 정책 | (73건 밖) | 코드 | up 값 = `LinkUp` · `Up` · `Connected` 만, `Enabled` · `Active` → down + '값 미확정' notice(사용자 결정 Q1). Mock 18대 출력 변화 0. `02-hba-link-policy.md` | `0227e2cb` |

처분 재집계(`recount.md`): 최상위 FIXED 43 · DOC_CORRECTED 19 · OBSERVATION_ONLY 11 = 73(불변), 병기 HOLD 1 → 3. 132칸 PASS 120 · ISSUE 2 · MOCK_LIMITATION 2 · N/A 8(불변), 근거 문장 13칸 정정.

## 2. 커밋

`git log --oneline f92ebe6a..HEAD` — 제품 코드와 하네스는 따로 커밋했다.

| | SHA | 제목 |
|---|---|---|
| C1 | `db606f1c` | fix: XCC3 NIC 링크를 같은 MAC 포트 값으로 보충 |
| C2 | `0227e2cb` | fix: HBA 링크 up 판정을 표준 링크 값으로 한정 |
| C3 | `ac368a4b` | fix: 전원 Off notice 에 네트워크 인벤토리 명시 |
| C4 | `c73db2ce` | test: CI gate 환경 의존 시험 이식성 보강 |
| C5 | `0e3bcbb3` | docs: 사전·계약 문서 출처와 예시 정정 |
| C6 | `499ed7c5` | harness: PROJECT_MAP 지문을 quotepath 무관하게 |
| C7 | `3490f210` | docs: 처분표·132칸 정정과 재검증 증거 추가 |
| C8 | `d552ae06` | harness: 재검증 결과와 후속 작업 문서 갱신 — Tier 0 를 돌린 커밋 |
| C9 · C10 | `git log` | Tier 0 기록(이 문서 7절 갱신) · PROJECT_MAP 지문 — 기록과 지문만 바꾼다 |

제품 동작이 바뀐 곳은 셋뿐이다: `redfish-gather/tasks/normalize_standard.yml`(F-01), `redfish-gather/library/redfish_gather.py` 의 HBA 판정 2함수 + 상수(HBA 정책) · 전원 Off notice 문구 1줄(F-03).
변경 0: `_normalize_link_status` · CSUS A안 코드 · 요청 경로(새 HTTP 요청 0) · adapters(`lenovo_xcc3.yml` 주석 외) · vault · baseline · golden · Jenkinsfile · callback · `common/tasks/normalize/**` · os-gather · esxi-gather · envelope 13 필드 · `schema_version`.

## 3. 보존 확인

| 항목 | 기대 | 확인 방법 |
|---|---|---|
| 구현 브랜치 | 로컬 · origin 모두 `f92ebe6ad338693c7d993434ca7190129a4b7639` | `git rev-parse fix/redfish-mock2-20261027 origin/fix/redfish-mock2-20261027` |
| main | `e8b5ae9b2f0e4075d1e9f65d6e47475e3bd7b17c`(시작과 같음) | `git rev-parse main origin/main` |
| 독립 검증 폴더 | 시작 목록과 차이 0(보고서 + `out/` + `tools/` 1,930 파일) | `python -I -B tools/hash_tree.py C:/github/ClovirONE/se-indep-20261027 <out>` 를 `pristine/se-indep-manifest-start.txt`(sha256 `06d8d13336cad854ae62e6dea43abef99b8e402882c48902bb1df291f48d060a`)와 비교. 끝 목록 `pristine/se-indep-manifest-end.txt`(Tier 0 뒤, 2026-10-28)는 시작 목록과 바이트가 같다(1,930 파일, 같은 sha256) |
| 구현 측 Tier 산출물 | 차이 0 | `git diff f92ebe6a -- 'tests/evidence/2026-10-27-redfish-mock2-impl/tier*'` |
| 감사 원문 | 차이 0 | `git diff f92ebe6a -- tests/evidence/2026-10-26-redfish-mock2-audit` |
| 구현 측 서술 · 처분 문서 | in-place 정정 + 각 파일 끝 "2026-10-28 정정" 표 | `git diff f92ebe6a -- tests/evidence/2026-10-27-redfish-mock2-impl/*.md` |

## 4. 재현 명령 (새 HEAD, 저장소 루트 · Windows Git Bash)

```bash
D=tests/evidence/2026-10-28-redfish-mock2-review-fix
# 4.1 미러 — 2차는 저장소 zip(SHA256SUMS), 1차는 외부 폴더 사본. 경로가 이미 있으면 스크립트가 중단한다
wsl -d Ubuntu-24.04 -u root -- bash /mnt/c/github/ClovirONE/clovirone-server-gathering/$D/tools/prep_mirrors.sh /root/mirror_digests.txt   # mirrors.md 의 digest 와 같아야 함
# 4.2 Tier 1 (실제 ansible-playbook + HTTPS 미러, 18 label 약 14분). MSYS_NO_PATHCONV 는 이 명령 한 줄에만 붙인다(전역 export 금지)
M=/root/se_mirrors_fix_20261028
MSYS_NO_PATHCONV=1 python tests/redfish-probe/mirror_replay/run_tier1.py \
  csus3200_01=$M/csus3200_01 csus3200_02=$M/csus3200_02 csus3200_03=$M/csus3200_03 \
  dl380_gen12_01=$M/dl380_gen12_01 dl380_gen12_02=$M/dl380_gen12_02 dl380_gen12_03=$M/dl380_gen12_03 dl380_gen12_04=$M/dl380_gen12_04 \
  sr650_v4_01=$M/sr650_v4_01 sr650_v4_02=$M/sr650_v4_02 sr650_v4_03=$M/sr650_v4_03 sr650_v4_04=$M/sr650_v4_04 \
  r1_DELL_R740_01=$M/mock1/DELL_R740/01 r1_HPE_CSUS3200_01=$M/mock1/HPE_CSUS3200/01 r1_HPE_CSUS3200_02=$M/mock1/HPE_CSUS3200/02 \
  r1_HPE_CSUS3200_03=$M/mock1/HPE_CSUS3200/03 r1_HPE_CSUS3200_04=$M/mock1/HPE_CSUS3200/04 r1_HPE_DL380_01=$M/mock1/HPE_DL380/01 \
  r1_Lenovo_SR650_01=$M/mock1/Lenovo_SR650/01 \
  --out-root <새 출력 루트> --server-distro Ubuntu-24.04 --playbook-distro Ubuntu --loc yi --build-id <임의>
# 4.3 대조 — 구현 측 최종(허용 목록 3항목) · 독립 검증 출력(같은 허용 목록) · 이번 A(허용 목록 없음)
python -I -X utf8 -B $D/tools/tier1_explained.py tests/evidence/2026-10-27-redfish-mock2-impl/tier1-final <새 출력 루트> --allow $D/tier1-A/_allow.json --out-md <md>
python -I -X utf8 -B $D/tools/tier1_explained.py C:/github/ClovirONE/se-indep-20261027/out/tier1-after <새 출력 루트> --allow $D/tier1-A/_allow.json --out-md <md>
python -I -X utf8 -B $D/tools/tier1_explained.py $D/tier1-A <새 출력 루트> --allow $D/tier1-B/_allow.json --out-md <md>      # _allow.json = []
python tests/redfish-probe/mirror_replay/diff_tier1.py tests/evidence/2026-10-27-redfish-mock2-impl/tier1-final <새 출력 루트> --allow $D/tier1-A/_allow.json --out <md>
python -I -X utf8 -B $D/tools/tier1_invariants.py <새 출력 루트> --ref tests/evidence/2026-10-27-redfish-mock2-impl/tier1-final --out <md>
# 4.4 Tier 2 (Windows, 네트워크 0)
E=C:/github/ClovirONE/mock2-fix-20261028/extract; M1="C:/github/서버mock데이터/1차"; OUT=<새 tier2 출력>
python tests/redfish-probe/mirror_replay/tier2_replay.py $OUT csus3200_01=$E/csus3200_01 csus3200_02=$E/csus3200_02 csus3200_03=$E/csus3200_03 r1_HPE_CSUS3200_01="$M1/HPE_CSUS3200/01" r1_HPE_CSUS3200_02="$M1/HPE_CSUS3200/02" r1_HPE_CSUS3200_03="$M1/HPE_CSUS3200/03" r1_HPE_CSUS3200_04="$M1/HPE_CSUS3200/04" --layout rmc_primary --firmware-scope complex_only --pcie-link-registries H3Alert --tag adapter
python tests/redfish-probe/mirror_replay/tier2_replay.py $OUT dl380_gen12_01=$E/dl380_gen12_01 dl380_gen12_02=$E/dl380_gen12_02 dl380_gen12_03=$E/dl380_gen12_03 dl380_gen12_04=$E/dl380_gen12_04 sr650_v4_01=$E/sr650_v4_01 sr650_v4_02=$E/sr650_v4_02 sr650_v4_03=$E/sr650_v4_03 sr650_v4_04=$E/sr650_v4_04 r1_DELL_R740_01="$M1/DELL_R740/01" r1_HPE_DL380_01="$M1/HPE_DL380/01" r1_Lenovo_SR650_01="$M1/Lenovo_SR650/01" --tag plain
python -I -X utf8 -B $D/tools/tier2_vs_golden.py $OUT --prev tests/evidence/2026-10-27-redfish-mock2-impl/tier2-final --out-md <md>
# 4.5 개수 정합 · 판별기 · 132칸 · 처분 재집계
python -I -X utf8 -B $D/tools/run_parity.py <새 출력 루트> <out_dir> csus3200_01=$E/csus3200_01 ... r1_Lenovo_SR650_01="$M1/Lenovo_SR650/01"   # 4.4 와 같은 18 label=미러
# 독립 검증 도구는 사본으로 돌린다(원본 sha256 과 같음 — 아래 6절). 원본 폴더 안에서 실행하지 않는다
python -I -X utf8 -B <사본>/oracle_compare.py <oracle.json> <새 출력 루트> --out-json <json> --out-md <md>   # oracle.json = se-indep out/oracle/oracle.json 과 같은 내용
python -I -X utf8 -B <사본>/cell_check.py <새 출력 루트> tests/evidence/2026-10-27-redfish-mock2-impl/tier1-before tests/evidence/2026-10-26-redfish-mock2-audit/coverage/coverage-132.json tests/evidence/2026-10-27-redfish-mock2-impl/coverage-132-after.json --out <md> --json <json>
python -I -X utf8 -B $D/tools/recount.py tests/evidence/2026-10-27-redfish-mock2-impl tests/evidence/2026-10-26-redfish-mock2-audit --out <md>
# 4.6 HBA 값 분포 · CSUS 카드 조건
python -I -X utf8 -B $D/tools/linkstatus_values.py --fixtures tests/fixtures <18 label=미러> --out <md>
python -I -X utf8 -B $D/tools/csus_card_conditions.py csus3200_01=$E/csus3200_01 ... --out <md>   # CSUS 7 label
# 4.8 Tier 0 — tier0/tier0.md 4절 (tools/tier0_wsl.sh · tier0_win.sh · tier0_mk_venv.sh · tier0_summary.py, 한 번에 하나씩)
```

### 4.7 독립 검증 보고서 §11 재현 명령의 새 기대값

| # | 보고서 명령 | `f92ebe6a` 값(보고서) | 새 HEAD 값(이번 `tier1-A`) |
|---|---|---|---|
| F-01 | sr650_v4_03 `interfaces[].link_status` · `summary.groups[].link_up_count` | 11건 모두 `unknown` · `[0, 0, 0]` 계열 | `['unknown', 'up' ×10]`(ToManager 만 unknown) · `[0, 4, 6]` |
| F-01 | 나머지 SR650 V4 | — | v4_01 `['unknown','down','up','down','up']` · `[0, 0, 2]` / v4_02 `['unknown','down','up','down','unknown']` · `[0, 0, 1, 0]` / v4_04 같은 형태 · `[0, 0, 1, 0]` |
| F-03 | `grep -n "저장/메모리/전원/온도" redfish-gather/library/redfish_gather.py` | 7001 | 0건 — `저장/네트워크/메모리/전원/온도` 가 7022 |
| F-10 | `python scripts/ai/check_project_map_drift.py` | rc 2 | 마지막 커밋(C10) 뒤 rc 0 |

## 5. 기대값 (이번 실측 — 18 label)

| 검사 | 결과 | 산출 |
|---|---|---|
| Tier 1 A · B | 18/18 rc 0 · success · errors 0 · 요청 수 = 구현 측 최종 | `tier1-A/_summary.json` · `tier1-B/_summary.json` |
| A ↔ B (허용 목록 없음) | 차이 0 · 요청 집합 차이 0 | `tier1-B/_explained_vs_A.md` · `_diff_vs_A.md` |
| A ↔ 구현 측 `tier1-final` | 설명된 차이 34 · 설명되지 않은 차이 0 · 요청 차이 0 · status/sections/adapter 같음 | `tier1-A/_explained_vs_final.md` · `_diff_vs_final.md` |
| A ↔ 독립 검증 `out/tier1-after` | 같은 34 · 미설명 0 | `tier1-A/_explained_vs_indep.md` |
| 불변 항목 | HBA 값 · 수 · 링크 notice 16건 = 구현 측 최종, HBA 값 ⊂ {up, down}, `cpu.logical_threads` 0, 전원 Off notice dl380_gen12_03 1건뿐, 남은 NIC unknown = NIC6 · NIC4(+ ToManager · CSUS · 전원 Off 호스트) | `tier1-A/_invariants.md` · `tier1-B/_invariants.md` |
| Tier 2 | 18/18 success · golden 15 label 차이 0 · 구현 측 Tier 2 와 전 키 차이 0 | `tier2-A/_vs_golden.md` |
| 개수 정합 | 18/18 PASS(디스크 · FC 포트, 구현 측 `inventory-parity.md` 와 같은 수) | `parity-A/_parity.md` |
| 판별기 대조 | 불일치 69 — 구현 측 최종 · 독립 검증 `cmp_after.json` 과 내용이 같다(새 불일치 0) | `oracle-A/oracle_compare.json` |
| 132칸 칸 검사 | 독립 검증 `cell_check.json` 과 비교해 SR650 V4 4칸 `if_link` 집합(F-01 효과)과 정정한 근거 문장 13칸만 다름 | `cell_check.md` · `cell_check.json` |
| 처분 재집계 | 73 = 감사 73 · FIXED 43 · DOC 19 · OBS 11 · HOLD 3 · 132칸 120/2/2/8 | `recount.md` |
| `LinkStatus` 값 | 미러 · fixture 모두 `Enabled` · `Active` · `Connected` 0 | `linkstatus_values.md` |
| 요청 예산 | `tests/integration/test_request_budget.py` 30 passed | — |
| pytest 전체(Windows, HEAD = C6 + 이 증거) | `tests/unit tests/e2e tests/regression` 6388 passed · 45 skipped · 5 xfailed · 실패 0 / `tests/integration -m "not live"` 502 passed · 6 skipped · 1 deselected · 실패 0 | `pytest/env.txt` · `pytest/*.log` |

- Tier 2 `*.module.json` 에는 notice 가 없다(모듈 `notices()` 는 `exit_json` 에서 따로 붙는다 — `redfish_gather.py:9657` · `:9709`). 전원 Off 문구(F-03)는 Tier 1 봉투로만 확인했다.

## 6. 허용 목록 · 산출물 sha256

`tier1-A/_allow.json`(3 항목): SR650 V4 4 label `data.network.interfaces[].(link_status|is_primary)` · `data.network.summary.(groups[].link_up_count|primary_speed_mbps)`(03-network-002), dl380_gen12_03 `diagnosis.details.notices[].message`(03-storage-001).

sha256 은 저장소 blob(LF) 기준이다 — `core.autocrlf=true` checkout 에서는 `git show HEAD:<경로> | sha256sum` 으로 계산한다.

- 2026-10-28 정정(C9): C7 판본의 이 표는 11행의 값을 Windows 작업 트리 파일(CRLF — Windows Python 이 쓴 파일)로 계산해 blob 기준과 달랐다. 아래 값은 C7 blob 에서 다시 계산했다(내용은 같고 줄 끝만 다르다). `tier2-A/_summary.*.json` 2행과 묶음 3행은 원래 LF 파일이라 그대로다.
- 묶음 3행은 아래 명령의 출력이다(`r` = `tier1-A` · `tier1-B` · `tier2-A`, 어느 checkout 에서나 같다).

```bash
D=tests/evidence/2026-10-28-redfish-mock2-review-fix
git ls-files -- "$D/$r" | grep -E '/gather_output\.json$|\.module\.json$' | LC_ALL=C sort \
  | while read -r p; do printf '%s  ./%s\n' "$(git show "HEAD:$p" | sha256sum | cut -c1-64)" "${p#"$D/$r/"}"; done | sha256sum
```

| sha256 | 파일 (`tests/evidence/2026-10-28-redfish-mock2-review-fix/` 기준) |
|---|---|
| `aca967d5c323967d8ade82836b3931d01a5969851c21a32e9688ddccf4b55fad` | `tier1-A/_summary.json` |
| `354c2f23abaa21cf5e4c1e2113ba9df295604abb4da299713b9078086300c4b1` | `tier1-B/_summary.json` |
| `fb9a61db277f24f27112aa45ba08c5a5049673a64d462631dd9accb232908542` | `tier1-A/_explained_vs_final.json`(= `_explained_vs_indep.json`) |
| `6652976faca4289ed93ec45069e949b5e5fe61fb7c09b2e5316ea1e2ee2d4154` | `tier1-B/_explained_vs_A.json` |
| `07a6b5a691bb264b3d9c982b94463723ecd32208740c2bed59b8058187a3e221` | `tier1-A/_invariants.md` |
| `db4a194812d1979e507282ffa3247247dcbc6e4df3d0ea2d035e01aa8e5cce18` | `tier2-A/_summary.adapter.json` |
| `a54cf5d7a42f4b98f8e4376026f870e66ed45357e716e2d5c3f2c5a369de33da` | `tier2-A/_summary.plain.json` |
| `bd11c1599a1b33753b88f2f8c578b5ceea6cccefd3db346732375f0c3110680d` | `tier2-A/_vs_golden.md` |
| `06683d5dced6e6587cf0ad968c72de07addda96afae1347e043ee9f833b1c006` | `parity-A/_parity.md` |
| `ccf65a7200c49d6ec23087377d698769c44b9853846e020fc59c7e19e80538e1` | `oracle-A/oracle_compare.json` |
| `53a49f9231d0aa8e2f30aa470136bf21e13d7bd3d598a8ed40a049bf0d550486` | `cell_check.json` |
| `f7c307e073ac4b6740bb8439d24f12294dee7e647d505570de92e0b12671195d` | `recount.md` |
| `d9cb4f1c267be6587d670cc7156c0ccc7fa25467555136361f6f5792fb722482` | `linkstatus_values.md` |
| `68d848a82dbdd24f7641b6f0ba21eebfa20a9cc40ab28dcb50eee647f3561a1e` | `tier1-A` 의 `*/gather_output.json` 18개(정렬 `sha256sum` 목록의 sha256) |
| `9f2bd03078e1f5ffe4a32e1ceae865e6bd1df4bdaf0cbcb021e87b61893a0c4d` | `tier1-B` 같은 방법(meta 시각이 달라 A 와 파일 해시는 다르다 — 내용 차이는 0) |
| `4cbb8051af7a53baf48ae6dd7da5394b22ea77758a7f5922cd630fc9c67ff70e` | `tier2-A` 의 `*.module.json` 18개 같은 방법 |

독립 검증 도구 사본(scratchpad)의 sha256 은 원본 `se-indep-20261027/tools/` 와 같다: `cell_check.py` `f3d95eee…` · `oracle.py` `29ae3385…` · `oracle_compare.py` `f5bd22a6…` · `labels.py` `3758ad3d…` · `mirror_loader.py` `efc9370f…`.

## 7. Tier 0 (CI gate)

C8 `d552ae06` 에서 돌렸다. 정본은 `tier0/tier0.md`(조건 · skip 사유 · 재현 명령 · sha256)다. **공식 runner(`Jenkinsfile_ci`)는 NOT_RUN** 이라 "Linux 공식 등가 PASS, 공식 runner 실행 대기" 로 보고한다.

| 실행 | 결과 |
|---|---|
| Linux 공식 등가(WSL ext4 새 clone · 격리 venv · `env -i` · pwsh 없음 · `Jenkinsfile_ci` Gate 명령) | `RESULT: PASS` rc 0 — pytest 6250 passed · 183 skipped · 5 xfailed / integration 525 passed · syntax-check 3 채널 · corpus 20/20 |
| Windows 새 clone(`core.autocrlf=true` · 전역 `MSYS_NO_PATHCONV=1`) | `RESULT: PARTIAL` rc 2 — 실패 0, 건너뜀은 syntax-check 1(ansible 없음 — 설계상). pytest 6388 passed · 45 skipped · 5 xfailed / integration 502 passed |
| 묶음별 재현(수정 전 `f92ebe6a` → 수정 후) | G1 2 failed → 2 passed · G2 4 failed → 19 passed · G4 · G5 15 failed → 67 passed · G3 81 failed = 81 failed(실패 ID 같음 — 후속) |

- 독립 검증이 보고한 실패 102건(Windows 15 · WSL 87)과 묶음별 수가 같다.
- Windows gate 한 번은 다른 실행(Linux gate, 이어서 WSL 재현)과 겹쳐 돌다 메모리 부족으로 중단돼 판정에서 뺐다(`tier0/windows-clone-aborted-oom/README.md`). 이후 사용자 결정에 따라 한 번에 하나씩 다시 돌렸다.
- 계획서 7.3절의 Windows 기대값 "rc 0" 은 ci_gate 설계(ansible 없으면 PARTIAL)와 달라 실측대로 적었다.

## 8. 계획서(2026-10-28) 문구 정정 — 실행 중 발견

계획서는 저장소 밖(사용자 승인본)이라 고치지 않고 여기에 적는다. 저장소 문서에는 아래 실측값만 들어갔다.

| 계획서 문구 | 실측 | 근거 |
|---|---|---|
| XCC3 RedfishVersion: mock2 미러 1.17.0 ↔ adapter 주석 1.15.0 | 1차 미러(SR650 V4, `IHX414J 1.22`) 1.17.0 · 2차 Mock 4대(`IHX438R 2.97`) 1.22.0 · 1.15.0 은 어느 미러에도 없음 | 미러 ServiceRoot 원문 — `adapters/redfish/lenovo_xcc3.yml` drift 주석(C5) |
| 저장소 fixture `LinkStatus` 분포 "LinkUp 244 · LinkDown 122 · NoLink 44 · Down 32 · Up 8" | 재현 안 됨. LinkUp 123 · LinkDown 61 · null 45 · NoLink 22 · Down 16 · Up 4(골든 제외, 같은 `@odata.id` 1번). 결론(`Enabled` · `Active` · `Connected` 0)은 같다 | `linkstatus_values.md` |
| dl380_gen12_03 network "adapters DA000004/DA000007 ports 0" | adapters 2(각 `port_count` 2) · `ports[]` 4 — link 전부 `unknown`, interfaces 4 `unknown` | 새 Tier 1 봉투 |
| §5.1 R1 코드 초안: speed 보충을 link 분기 밖 별도 조건(`speed is none`, 포트 속도 null 제외)으로 | 구현은 종전처럼 link `unknown` 분기 안 · 포트 속도는 null 포함 일치(구현 선택 — 초안대로면 자체 link `up` 인 DL380 iLO NIC 16개에 speed 25000 이 새로 채워져 계획서의 "speed 변화 0" · 범위와 어긋남) | `01-f01-nic-link-fill.md` 2절 |
| F-09 "BMC 값(`IHX414J 1.22` · `BMC-IHX4-10`)" | 종전 예시 값은 `"version": "IHX414J 1.22"` · `"component": "UEFI-IHX4-10"`(BMC 값 계열 — 1차 SR650 V4 Manager `FirmwareVersion` `IHX414J 1.22 20250402` · BMC SoftwareId `BMC-IHX4-10`) | `git show f92ebe6a:docs/contract/03-fields.md` 1200행 |

## 9. 남은 것

| 항목 | 상태 | 닫는 방법 |
|---|---|---|
| 03-network-002 잔여 2 NIC(sr650_v4_02 `NIC6` · _04 `NIC4`) | [HOLD] `unknown` 유지 | 모듈 포트 · NDF 출력 변경(보호 경로) + golden 원장 + 18 미러 조인 대조 — 별도 사용자 승인 |
| 05-thermal-003 (b) Sensor 보충 | [HOLD] | Sensor 에 Status/Thresholds 값이 있는 실장비 캡처 + 요청 예산 승인 |
| 03-storage-001 (b) | [HOLD] 그대로 | 기존 계획 |
| CSUS FC 포트 단위 링크 · XCC3 인증 복구 · RMC `WriteableProperties` | [MOCK_LIMITATION] 그대로 | 실장비 |
| OEM 포트별 링크 정규화 | [TODO] 조건부 | 포트별 필드의 Link Up 의미 근거 확인 시 별도 cycle(`02-hba-link-policy.md` 5절) |
| DL380 iLO NIC 16개(자체 link `up` · speed null)의 포트 속도 보충 | [INFO] 하지 않음 — 값 `null` 유지 | 계획서 초안의 별도 speed 조건이면 채워졌을 값(25000). 기능 개선이라 범위 밖 — 사용자 결정(`01-f01-nic-link-fill.md` 2절) |
| 공식 runner ci_gate | [NOT_RUN] | 운영 담당자 — Runner 셸에서 새 브랜치로 `scripts/ai/ci_gate.sh` |
| G3 WSL interop PowerShell 탐침 81건 | [TODO] | skip 동작 변경이라 별도 승인 |
| 실장비 검증 | 0건 | — |
