# 독립 검증 핸드오프 — Redfish 2차 Mock 11대 구현 Round (지시서 2, 2026-10-27)

> 수신: **새 Fable 5.1 / effort=max 세션**(구현 세션과 컨텍스트를 공유하지 않는다). 목적: 구현 세션의 자기 보고(`IMPLEMENTATION_SUMMARY.md`)를 믿지 말고 같은 브랜치 SHA 에서 Tier 0/1/2 와 처분표를 **직접 재실행·대조**해 PASS/FAIL 을 내는 것. 독립 검증 PASS 와 사용자 승인 전에는 `main` 병합 · `production` 승격을 하지 않는다(FIX 11).

## 1. 대상

- 브랜치 `fix/redfish-mock2-20261027`(origin github + gitlab 동시 push). 분기점 `b8985826`. 검증 대상 SHA 는 이 문서가 들어간 WP12 커밋 = `git log -1 --format=%H origin/fix/redfish-mock2-20261027`(구현 세션 종료 보고의 SHA 와 같아야 한다). `git status` clean 이어야 한다.
- 변경 파일: `git diff --stat b8985826..HEAD`(제품 30 파일: `redfish-gather/library/redfish_gather.py` · `redfish-gather/tasks/normalize_standard.yml` · `site.yml` · `tasks/{collect_standard,detect_vendor,reselect_adapter,try_one_account}.yml` · `module_utils/adapter_common.py` · `adapters/redfish/{lenovo_xcc3,hpe_csus_3200,hpe_superdome_flex,cisco_cimc}.yml` · `schema/**`). **OS/ESXi · common/tasks · callback_plugins · Jenkinsfile · vault 는 변경 0 이어야 한다** — `git diff --stat b8985826..HEAD -- os-gather esxi-gather common/tasks callback_plugins Jenkinsfile_portal vault` 가 비어 있는지 확인.
- 처분표: `ISSUE_DISPOSITION.md`(73 ID 전부). 각 FIXED 는 코드 diff + 테스트 + Tier 1 allowlist diff(`tier1-after-WPn/_diff_vs_after_wp*.md`) 로, DOC_CORRECTED 는 문서 diff 로, OBSERVATION_ONLY 는 변경 0 으로 대조한다.
- golden 원장: `golden-changes.md` G-01~G-25 — 바뀐 golden 마다 before/after/원천/원인이 있어야 하고(FIX 9), 원천이 "코드 출력" 인 항목이 있으면 FAIL.

## 2. 환경 (구현 세션 실측)

| 항목 | 값 |
|---|---|
| Windows | Python 3.13.15 · pytest 9.1.1 · Git Bash(`MSYS_NO_PATHCONV=1` 필요 — WSL 경로 변환 방지) · `PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1` |
| WSL `Ubuntu`(hshwang) | ansible-core 2.20.7 · Python 3.12.3 · `~/.se_vault_pass` — **playbook 실행** |
| WSL `Ubuntu-24.04`(root) | Python 3.12.3 · openssl · `/root/se_mirrors/`(아래) · 443 바인드 — **재생 HTTPS 서버**(인증서는 runner 가 임시 생성) |
| 2차 미러(11대) | 저장소 `tests/reference/redfish/mock2/<server>.zip`(불변, SHA256SUMS) → WSL `/root/se_mirrors/<server>` 로 추출(`tests/redfish-probe/mirror_replay/extract_mirrors.sh`). Windows 추출본 `C:\github\ClovirONE\mock2-audit-20261026\extract\<server>`(zip 과 동일함을 WP1 에서 확인) |
| 1차 미러(7대, **저장소 밖**) | `C:\github\서버mock데이터\1차\{DELL_R740,HPE_CSUS3200,HPE_DL380,Lenovo_SR650}\<nn>` → WSL `/root/se_mirrors/mock1/<VENDOR>/<nn>`. 없으면 1차 7 label 은 건너뛰고 11 label 만 돌린 뒤 그 사실을 적는다 |
| label ↔ 미러 | `csus3200_01..03` · `dl380_gen12_01..04` · `sr650_v4_01..04` = `/root/se_mirrors/<label>`; `r1_DELL_R740_01=/root/se_mirrors/mock1/DELL_R740/01` · `r1_HPE_CSUS3200_01..04=/root/se_mirrors/mock1/HPE_CSUS3200/0N` · `r1_HPE_DL380_01=/root/se_mirrors/mock1/HPE_DL380/01` · `r1_Lenovo_SR650_01=/root/se_mirrors/mock1/Lenovo_SR650/01`(`tier1-final/_summary.json` 의 `label`/`mirror` 와 같다) |

## 3. 재실행 절차 (각 단계의 기대값은 구현 세션 측정치 — 다르면 원인을 적고 FAIL/PASS 를 판단)

```bash
# Tier 0 (Windows, 저장소 루트)
export PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1
python -m pytest tests/unit -q -p no:cacheprovider                      # 기대 5226 passed · 33 skipped · 0 failed (≈23분)
python -m pytest tests/integration -m "not live" -q -p no:cacheprovider  # 기대 497 passed · 6 skipped
python -m pytest tests/e2e tests/regression -q -p no:cacheprovider       # 기대 1098 passed · 12 skipped · 5 xfailed
python -m pytest tests/unit tests/e2e tests/regression -q -p no:cacheprovider   # 한 프로세스 — seam 누출 0 (WP1)
python tests/validate_field_dictionary.py                                 # PASS (262)
python scripts/ai/hooks/output_schema_drift_check.py                      # 정합
python scripts/ai/verify_vendor_boundary.py && python scripts/ai/verify_harness_consistency.py
# WSL 엔진·syntax (Ubuntu)
wsl -d Ubuntu -- bash -lc 'cd /mnt/c/github/ClovirONE/clovirone-server-gathering && for c in os-gather esxi-gather redfish-gather; do ansible-playbook --syntax-check $c/site.yml; done'
wsl -d Ubuntu -- bash -lc 'cd /mnt/c/github/ClovirONE/clovirone-server-gathering && python3 -m pytest tests/unit/test_build_output_no_data_playbook.py tests/unit/test_addon_hook_playbook.py -q'   # 23 passed
# Tier 1 (Windows Git Bash — 실제 ansible-playbook + HTTPS 미러, 18 label ≈ 14분)
M=/root/se_mirrors
MSYS_NO_PATHCONV=1 python tests/redfish-probe/mirror_replay/run_tier1.py \
  csus3200_01=$M/csus3200_01 csus3200_02=$M/csus3200_02 csus3200_03=$M/csus3200_03 \
  dl380_gen12_01=$M/dl380_gen12_01 dl380_gen12_02=$M/dl380_gen12_02 dl380_gen12_03=$M/dl380_gen12_03 dl380_gen12_04=$M/dl380_gen12_04 \
  sr650_v4_01=$M/sr650_v4_01 sr650_v4_02=$M/sr650_v4_02 sr650_v4_03=$M/sr650_v4_03 sr650_v4_04=$M/sr650_v4_04 \
  r1_DELL_R740_01=$M/mock1/DELL_R740/01 r1_HPE_CSUS3200_01=$M/mock1/HPE_CSUS3200/01 r1_HPE_CSUS3200_02=$M/mock1/HPE_CSUS3200/02 \
  r1_HPE_CSUS3200_03=$M/mock1/HPE_CSUS3200/03 r1_HPE_CSUS3200_04=$M/mock1/HPE_CSUS3200/04 r1_HPE_DL380_01=$M/mock1/HPE_DL380/01 \
  r1_Lenovo_SR650_01=$M/mock1/Lenovo_SR650/01 \
  --out-root tests/evidence/2026-10-27-redfish-mock2-impl/tier1-independent --server-distro Ubuntu-24.04 --playbook-distro Ubuntu --loc yi --build-id mirror-replay-independent
# 기대: _summary.json 18 label rc 0 · status success · errors 0. 구현 세션 최종과 대조(허용목록 없음 → 차이 0 이어야 함; meta 시각류는 도구가 무시):
echo "[]" > tests/evidence/2026-10-27-redfish-mock2-impl/tier1-independent/_allow.json
python tests/redfish-probe/mirror_replay/diff_tier1.py tests/evidence/2026-10-27-redfish-mock2-impl/tier1-final tests/evidence/2026-10-27-redfish-mock2-impl/tier1-independent --allow tests/evidence/2026-10-27-redfish-mock2-impl/tier1-independent/_allow.json --out tests/evidence/2026-10-27-redfish-mock2-impl/tier1-independent/_diff_vs_final.md
# 수정 전 기준선과의 전체 차이(설명 의무): tier1-before ↔ tier1-independent 를 WP 별 allowlist(tier1-after-WP*/_allow.json)의 합으로 설명할 수 있어야 한다.
# Tier 2 (Windows, 네트워크 0 — 2차는 extract 디렉터리, 1차는 외부 미러)
E=C:/github/ClovirONE/mock2-audit-20261026/extract; M1="C:/github/서버mock데이터/1차"; OUT=tests/evidence/2026-10-27-redfish-mock2-impl/tier2-independent
python tests/redfish-probe/mirror_replay/tier2_replay.py $OUT csus3200_01=$E/csus3200_01 csus3200_02=$E/csus3200_02 csus3200_03=$E/csus3200_03 r1_HPE_CSUS3200_01="$M1/HPE_CSUS3200/01" r1_HPE_CSUS3200_02="$M1/HPE_CSUS3200/02" r1_HPE_CSUS3200_03="$M1/HPE_CSUS3200/03" r1_HPE_CSUS3200_04="$M1/HPE_CSUS3200/04" --layout rmc_primary --firmware-scope complex_only --pcie-link-registries H3Alert --tag adapter
python tests/redfish-probe/mirror_replay/tier2_replay.py $OUT dl380_gen12_01=$E/dl380_gen12_01 dl380_gen12_02=$E/dl380_gen12_02 dl380_gen12_03=$E/dl380_gen12_03 dl380_gen12_04=$E/dl380_gen12_04 sr650_v4_01=$E/sr650_v4_01 sr650_v4_02=$E/sr650_v4_02 sr650_v4_03=$E/sr650_v4_03 sr650_v4_04=$E/sr650_v4_04 r1_DELL_R740_01="$M1/DELL_R740/01" r1_HPE_DL380_01="$M1/HPE_DL380/01" r1_Lenovo_SR650_01="$M1/Lenovo_SR650/01" --tag plain
# 기대: 18/18 success; <label>.<tag>.module.json 의 GOLDEN_KEYS(vendor/status/collected/failed_sections/unsupported_sections/data/multi_node/probe_facts/error_count) 가 tests/fixtures/redfish/real_*/expected_output.json 과 15 label 차이 0 (tier2-final/_vs_golden.md 형식).
# 개수 정합(사용자 3차 지시) — 노출 수 == 수집 수, UNEXPLAINED 0 (18 label 전수 미러 × Tier 1 봉투)
python tests/scripts/inventory_parity.py --help
```

## 4. 대조 체크리스트 (PASS 조건)

1. Tier 0 네 묶음 0 failed, 한 프로세스 실행에서도 0 failed(seam 누출 재발 없음).
2. Tier 1 18/18 success · errors 0, 구현 세션 `tier1-final` 과 차이 0, `tier1-before` 와의 차이가 WP allowlist 합으로 전부 설명됨(미설명 0). `status` · `sections` 는 18 label 모두 수정 전과 같음.
3. Tier 2 18/18 success · golden 15 label 차이 0. golden 변경 25건(G-01~G-25)마다 원장의 원천이 전수 미러/실측 봉투이고, 코드 출력 스냅샷이 아님.
4. 개수 정합 18/18 PASS · UNEXPLAINED 0 · INV-5 0.
5. `ISSUE_DISPOSITION.md` 73 ID 전부 처분이 있고, FIXED 43 건이 코드 diff·테스트·Tier 1 diff 로 뒷받침됨. OBSERVATION_ONLY 11 건은 코드 변경 0. HOLD 1(03-storage-001 (b)).
6. FIX 1~11 각각 확인: (1) Redfish 봉투 18 label 에 `data.cpu.logical_threads` 없음 · OS/ESXi baseline 5종에는 있음, (2) `cpu.manufacturer` Intel/AMD, (3) CSUS `speed_mhz` 3200 원값, (4) `sections.system = not_supported` + hostname, (5) `hpe_csus_3200_baseline.json` = csus3200_01 봉투(수정 2곳: `ip`·`correlation.host_ip`), (6) composition count null, (7) firmware category enum 에 새 값 없음(`hba` 없음) · FC HBA other, (8) `tests/redfish-probe/mirror_replay/` + fixture 11세트 커밋, (9) 원장, (10) `data.users` 불변, (11) `main`/`production` 미접촉(`git log origin/main`·`origin/production` 이 2026-10-26 이후 이 브랜치 커밋을 포함하지 않음).
7. 벤더 이름 분기 없음: `python scripts/ai/verify_vendor_boundary.py` exit 0, `redfish_gather.py` 의 신규 분기가 DMTF enum/OEM 네임스페이스/장비 값(`Manager.Model` · `ManagerType` · `@Redfish.WriteableProperties` · `Oem.Hpe.Links.DateTimeService`)으로만 가름. 서버 이름/IP/Mock 경로 하드코딩 없음(`grep -rn "11\.65\.\|10\.173\.\|se_mirrors\|서버mock" redfish-gather module_utils adapters` 의 결과는 `adapters/redfish/hpe_csus_3200.yml` 의 2026-06-15 origin 주석 1줄(사이트 IP 기록, 종전부터 있음)뿐이어야 한다 — 코드 값은 0).
8. 비밀: `python scripts/ai/verify_no_plaintext_secret.py --base b8985826` 0건; `tier1-*/` 에 `gather_auth_evidence/` · `.inventory_input.json` · `ansible_*.log` 가 커밋되지 않음(`.gitignore`).
9. 사전·계약: `validate_field_dictionary.py` PASS, `docs/contract/03-fields.md` 가 사전·실제 봉투와 어긋나지 않음(샘플: 6.2 캐시/rank · 6.3.2 FC down 폴백 문구 · 6.4 (1)~(4) · 6.6 bmc · 6.9 firmware · §9 실측 구조).
10. 재생 한계 명시: `MOCK_LIMITATION`(03-storage-004 포트 단위 · 06-bmc-001 복구 경로)을 PASS 로 올리지 않았는지(`coverage-132-after.md` PASS 120 · ISSUE 2 · MOCK 2 · N/A 8).

## 5. 알려진 한계 · 하지 않은 것

- 전부 Mock 재생이다(HTTPS 미러 + 실제 playbook). 실장비 401/복구 · 서버 측 상태 변화 · 포트 단위 FC 링크는 재현되지 않는다(`tests/redfish-probe/mirror_replay/README.md` 5절).
- `schema/output_examples/redfish_hpe_csus_3200.jsonc` 는 주석 예시로 둔 채 합성 구조다(README 의 "기준선과 장비가 정확히 같지 않을 수 있다").
- 03-storage-001 (b) controllers 보강(PCIeFunctions)은 사용자 결정 HOLD. dl380_gen12_03 의 firmware `MR416i-o` 가 `other` 인 것은 같은 원인(Storage 0건 → 조인 근거 없음).
- 구현 세션의 unit 전체 로그는 WP11 시점(`pytest_unit_after_wp11.log`)이고 FIX 5 뒤에는 regression/e2e/integration 만 다시 돌렸다(FIX 5 는 baseline·회귀 테스트 변경). 독립 검증은 전체를 한 번에 돌린다.
- `docs/ai/incoming-review/` 의 advisory 보고 파일(gitignored)은 커밋하지 않았다.
- 최종 Tier 1/2(`tier1-final` · `tier2-final`)는 `e1ee7bb8` 상태에서 돌렸고, 그 뒤 제품 코드 커밋은 `b31d131d`(`_memory_rank_count` 의 OEM Label 접근에 `# nosec rule12-r1` 주석 1줄 — 동작 변경 0, `verify_vendor_boundary.py` 가 잡은 표기 누락) 하나다. 독립 검증은 최종 SHA 에서 Tier 1/2 를 다시 돌리므로 이 차이는 거기서 해소된다.

## 6. 보고 형식 (독립 검증 세션)

- `tests/evidence/2026-10-27-redfish-mock2-impl/INDEPENDENT_REVIEW_RESULT.md`: 검증 SHA · 환경 · 3절 각 단계의 실제 수치 · 4절 체크리스트 10항목 PASS/FAIL · 불일치 목록(재현 명령 포함) · 판정(PASS / FAIL / PASS-with-notes). PASS 여도 `main` 병합은 사용자 승인 뒤 별도 세션(rule 93 R2 — squash 기본, 4요소 승인 포맷).
