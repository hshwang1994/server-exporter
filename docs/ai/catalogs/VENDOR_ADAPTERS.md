# VENDOR_ADAPTERS — server-exporter

> 9 vendor x 채널별 adapter 매트릭스 (rule 28 #3 측정 대상, TTL 14일).
> 2026-10-15: `hpe_csus_3200.yml` `vendor_notes.hostname_priority: bmc_first` — CSUS 는 RMC NetworkProtocol 이름이 서버 이름(없을 때만 Partition HostName). 이 키를 가진 adapter 는 CSUS 하나(시험 고정). ADR-2026-10-15-csus-hostname-rmc-first.
>
> 실측 (`ls adapters/redfish/*.yml | wc -l`) — 2026-05-12 (cycle hpe-csus-rmc-multi-node).
>
> **cycle 2026-06-15 변경** (실 미러 캡처 검수 — adapter 카운트 변경 없음, 31 그대로):
>   - **4 device 실 미러 캡처 + replay 검증**: HPE CSUS 3200(실 4노드) / Dell R740 / HPE DL380 Gen12 / Lenovo SR650 V4.
>     라이브러리(redfish_gather.py) 데이터 fix — CSUS 19 / Dell R740 4 / HPE DL380 7 / Lenovo 2, 전부 raw 1:1 + Additive (pytest 1204 passed).
>   - **adapter origin 최신화**: hpe_csus_3200 / hpe_ilo7 / lenovo_xcc3 = "lab 부재/추정" → "1회 실 캡처 검증" 승격.
>     dell_idrac9 = R740 14G 캡처 보강. CSUS firmware_patterns 에 실 1.x Additive (휴면 — 선택 시 facts.firmware 빈값, 실측 확인).
>   - **priority 정정**: 본 표가 구 96/95(csus/superdome) 표기였으나 실제 adapter 는 **102/101** (2026-06-04 ADR-csus-adapter-priority).
>   - **field_dictionary**: 개수는 적지 않는다 (rule 00). `grep -c '^\s*priority:' schema/field_dictionary.yml` 로 센다.
>   - **발견(gated)**: Dell/Lenovo 는 무인증 ServiceRoot 에 model 부재 → 세대 adapter 가 priority 로만 선택
>     (Dell→idrac10, Lenovo→xcc3 가 항상). collect/normalize tasks 동일이라 수집 데이터 무영향, diagnosis 라벨만 cosmetic. NEXT_ACTIONS 등재.
>
> **cycle 2026-05-12 변경**: adapter 카운트 변경 없음 (31 그대로). `vendor_notes` 보강만:
>   - `hpe_csus_3200.yml` / `hpe_superdome_flex.yml` 에 `multi_node_support: true` Additive (ADR-2026-05-12).
>   - `data.multi_node` Additive envelope 컨테이너 — RMC primary 시스템 (manager_layout=rmc_*) 전수 수집.
>   - field_dictionary → 83 entries (Must 39 / Nice 38 / Skip 6 — 2026-05-29 재실측).
>   - mock fixture `tests/fixtures/redfish/hpe_csus_3200/` 7 파일 합성 (3-partition × 4-manager × 3-chassis).
>
> **cycle 2026-05-11 변경**: 30 adapter → 31 adapter
>   - `hpe_csus_3200.yml` 신설 (priority=96, HPE Compute Scale-up Server 3200, lab 부재 — web sources 7건)
>   - HPE OEM tasks (collect_oem.yml / normalize_oem.yml) model regex 확장 Additive only (`Superdome|Flex` → `Superdome|Flex|Compute Scale-up|CSUS`)
>
> **cycle 2026-05-07 변경**: 27 adapter → 30 adapter
>   - Phase 1: supermicro_x10 신설 (M-B1) + supermicro_ars 신설 (M-B3) + 4 신규 vendor OEM tasks 신설 (M-J1 Cisco 추가 = 5 신설)
>   - Phase 3 M-K1: 30 adapter origin 주석 일관성 검증 (verify_adapter_origin_check.py --all --redfish-only PASS 30/30)
>   - Phase 3 M-J1: Cisco vendor task ((2026-08-13 제거 — 라이브러리 `_extract_oem_cisco`)) 신설 — 9 vendor OEM 모두 cover

## adapter 카운트 history

| 시점 | adapter 수 (Redfish) | 변경 |
|---|---|---|
| cycle 2026-04-29 (production-audit) | 16 | (이전 baseline) |
| cycle 2026-05-01 (gather-coverage) | 27 | +11 신규 vendor / generation (idrac10/ilo7/xcc3/superdome_flex/x12/x13/x14/cisco_ucs_xseries/huawei/inspur/fujitsu/quanta) |
| cycle 2026-05-06 (multi-session) | 28 | +1 hpe_superdome_flex 정밀 분리 |
| cycle 2026-05-07 (all-vendor-coverage) Phase 3 | 30 | +2 supermicro_x10 / supermicro_ars |
| **cycle 2026-05-11 (hpe-csus-add)** | **31** | **+1 hpe_csus_3200 (Compute Scale-up Server 3200, lab 부재)** |

→ 본 카탈로그는 Redfish adapter 만. OS (7) / ESXi (4) 별도 적용.

## Redfish 채널 (31 adapters — cycle 2026-05-11 hpe-csus-add 종료 시점)

### Dell (4 adapter)

| Adapter | adapter_id | priority | Vendor / Generation | lab |
|---|---|---|---|---|
| `dell_idrac10.yml` | redfish_dell_idrac10 | **120** | iDRAC10 (R770/Gen17, 사이트 5대) | **PASS** |
| `dell_idrac9.yml` | redfish_dell_idrac9 | 100 | iDRAC9 (5.x / 6.x / 7.x) | **R760 16G(Round11) + R740 14G 미러(2026-06-14)** — 단 실선택은 idrac10(아래) |
| `dell_idrac8.yml` | redfish_dell_idrac8 | 50 | iDRAC8 (2.40+) | 부재 |
| `dell_idrac.yml` | redfish_dell_idrac | 10 | generic Dell fallback (iDRAC7 legacy cover) | 부재 |

### HPE (7 adapter — cycle 2026-05-11 +1 hpe_csus_3200)

| Adapter | adapter_id | priority | Vendor / Generation | lab |
|---|---|---|---|---|
| `hpe_ilo7.yml` | redfish_hpe_ilo7 | **120** | iLO7 (Gen12) — DL380 Gen12 실 미러 fw 1.20.00 / Redfish 1.22.1 | **실 미러 캡처 2026-06-15 (replay 7 fix)** |
| `hpe_ilo6.yml` | redfish_hpe_ilo6 | 100 | iLO6 (Gen11 + 사이트 Gen12) | Round 11 부분 |
| `hpe_csus_3200.yml` | redfish_hpe_csus_3200 | **102** | **Compute Scale-up Server 3200 (CSUS, RMC + PDHC, DDR5) — RMC fw 1.75.108 / Redfish 1.19.0 / Oem #HpeH3Npar·#HpeH3Chassis (실측)** | **실 4노드 미러 캡처 2026-06-15 (replay 19 fix)** |
| `hpe_superdome_flex.yml` | redfish_hpe_superdome_flex | **101** | Superdome Flex (RMC + iLO5 dual-manager) — cycle 2026-05-12 multi_node_support 활성 | 부재 (web sources only — 미캡처) |
| `hpe_ilo5.yml` | redfish_hpe_ilo5 | 90 | iLO5 (Gen10/10+) | 부재 |
| `hpe_ilo4.yml` | redfish_hpe_ilo4 | 50 | iLO4 (Gen9, 2.30+) | 부재 |
| `hpe_ilo.yml` | redfish_hpe_ilo | 10 | generic HPE fallback (iLO 1/2/3 legacy) | 부재 |

### Lenovo (4 adapter)

| Adapter | adapter_id | priority | Vendor / Generation | lab |
|---|---|---|---|---|
| `lenovo_xcc3.yml` | redfish_lenovo_xcc3 | **120** | XCC3 (ThinkSystem V4) — SR650 V4 실 미러 fw IHX414J 1.22 / Redfish 1.15.0 | **실 미러 캡처 2026-06-15 (replay 2 fix)** |
| `lenovo_xcc.yml` | redfish_lenovo_xcc | 100 | XCC + XCC2 (firmware_patterns 분기) | 부재 |
| `lenovo_imm2.yml` | redfish_lenovo_imm2 | 50 | IMM2 (구 IMM2, IBM 인수 전) | 부재 |
| `lenovo_bmc.yml` | redfish_lenovo_bmc | 10 | generic Lenovo fallback (IBM legacy BMC) | 부재 |

### Cisco (3 adapter)

| Adapter | adapter_id | priority | Vendor / Generation | lab |
|---|---|---|---|---|
| `cisco_ucs_xseries.yml` | redfish_cisco_ucs_xseries | **110** | UCS X-series (standalone CIMC, 사이트 1대) | **PASS** |
| `cisco_cimc.yml` | redfish_cisco_cimc | 100 | CIMC (UCS C-series M4~M8 + S-series + B-series) | M4 lab tested 10.100.15.2 |
| `cisco_bmc.yml` | redfish_cisco_bmc | 10 | generic Cisco fallback (CIMC 1.x~3.x legacy) | 부재 |

### Supermicro (8 adapter — cycle 2026-05-07 +2 신설)

| Adapter | adapter_id | priority | Vendor / Generation | lab |
|---|---|---|---|---|
| `supermicro_x14.yml` | redfish_supermicro_x14 | 110 | X14 + H14 (Granite Rapids/Turin + Redfish 1.21.0) | 부재 |
| `supermicro_x13.yml` | redfish_supermicro_x13 | 100 | X13 + H13 + B13 (Eagle/Sapphire Rapids/Genoa) | 부재 |
| `supermicro_x11.yml` | redfish_supermicro_x11 | 100 | X11 + H11 (AST2500) | 부재 |
| `supermicro_x12.yml` | redfish_supermicro_x12 | 100 | X12 + H12 (Whitley/Tatlow + AST2600) — DRIFT-015 (cycle 2026-05-11 adapter-selection-review): 90→100 X11/X13 일관성 | 부재 |
| `supermicro_ars.yml` | redfish_supermicro_ars | 80 | **ARS (ARM) — cycle 2026-05-07 M-B3 신설** | 부재 |
| `supermicro_x10.yml` | redfish_supermicro_x10 | 75 | **X10 (AST2400) — cycle 2026-05-07 M-B1 신설** | 부재 |
| `supermicro_x9.yml` | redfish_supermicro_x9 | 50 | X9 (legacy) | 부재 |
| `supermicro_bmc.yml` | redfish_supermicro_bmc | 10 | generic Supermicro fallback | 부재 |

**Note: X11 / X13 priority 100 동률** — model_patterns 분리 (X11/H11 vs X13/H13/B13)로 tie-break.

### Huawei (1 adapter)

| Adapter | adapter_id | priority | Vendor / Generation | lab |
|---|---|---|---|---|
| `huawei_ibmc.yml` | redfish_huawei_ibmc | 80 | iBMC 1.x ~ 5.x + Atlas (firmware_patterns + model_patterns) | 부재 (cycle 2026-05-01) |

### Inspur (1 adapter)

| Adapter | adapter_id | priority | Vendor / Generation | lab |
|---|---|---|---|---|
| `inspur_isbmc.yml` | redfish_inspur_isbmc | 80 | ISBMC (NF/TS 시리즈) | 부재 (cycle 2026-05-01) |

### Fujitsu (1 adapter)

| Adapter | adapter_id | priority | Vendor / Generation | lab |
|---|---|---|---|---|
| `fujitsu_irmc.yml` | redfish_fujitsu_irmc | 80 | iRMC S2 / S4 / S5 / S6 + PRIMEQUEST | 부재 (cycle 2026-05-01) |

### Quanta (1 adapter)

| Adapter | adapter_id | priority | Vendor / Generation | lab |
|---|---|---|---|---|
| `quanta_qct_bmc.yml` | redfish_quanta_qct_bmc | 80 | QCT BMC (OpenBMC bmcweb, S/D/T/J series) | 부재 (cycle 2026-05-01) |

### Generic fallback (1 adapter)

| Adapter | adapter_id | priority | 용도 |
|---|---|---|---|
| `redfish_generic.yml` | redfish_generic | 0 | 매치 안 되는 vendor — DMTF Redfish 표준 fallback |

총 31 adapter (9 vendor + generic fallback).

## priority 일관성 검증 (rule 12 R2)

각 vendor 내부 priority 차등 — 역전 없음:

| Vendor | priority 순서 |
|---|---|
| Dell | 10 < 50 < 100 < 120 (generic < idrac8 < idrac9 < idrac10) [PASS] |
| HPE | 10 < 50 < 90 < 100 < 101 < 102 < 120 (generic < ilo4 < ilo5 < ilo6 < superdome_flex < csus_3200 < ilo7) [PASS] (2026-06-04 ADR — csus/superdome 를 ilo6 catch-all 위로) |
| Lenovo | 10 < 50 < 100 < 120 (bmc < imm2 < xcc < xcc3) [PASS] |
| Cisco | 10 < 100 < 110 (bmc < cimc < ucs_xseries) [PASS] |
| Supermicro | 10 < 50 < 75 < 80 < 90 < 100 < 100 < 110 (bmc < x9 < x10 < ars < x12 < x11/x13 < x14) [PASS — model_patterns tie-break] |
| Huawei | 80 (단일) [PASS] |
| Inspur | 80 (단일) [PASS] |
| Fujitsu | 80 (단일) [PASS] |
| Quanta | 80 (단일) [PASS] |
| generic | 0 (fallback) |

**[PASS]** 모든 vendor priority 역전 없음.

## OEM tasks 매트릭스 (M-J1 통합)

> **2026-08-13 제거.** 이 표에 있던 9 vendor OEM task 디렉터리는 전부 삭제됐다.
> 18개 파일이 모듈 출력에 없는 경로(`systems[0].Oem.*`, `data.chassis.Oem.*`)를 읽어
> 기여가 0이었다. 실장비 8대 envelope 에도 이들이 쓴다던 `data.bmc.oem_<vendor>` 키가
> 한 건도 없었다.
>
> 지금 OEM 은 라이브러리 `_extract_oem_{hpe,dell,lenovo,supermicro,cisco}` 와 Manager OEM
> 추출이 `data.system.oem` / `data.bmc.oem` 으로 내보낸다. 확장이 필요하면 그쪽을 넓힌다.
>
> 근거: `docs/ai/decisions/ADR-2026-08-13-vendor-oem-task-removal.md`



### 2026-08-10 실측 정정 — "디렉터리 보유 ≠ 실행됨"

adapter 의 `collect.oem_tasks` / `normalize.oem_tasks` 에 **경로가 실려 있어야만**
`redfish-gather/site.yml:140,145` 가 include 한다. 파일 존재 여부와 무관하다.
adapter 참조 여부 실측(`grep -rl "vendors/<v>/..._oem.yml" adapters/redfish/`):

| vendor | collect 참조 adapter 수 | normalize 참조 adapter 수 | 판정 |
|---|---:|---:|---|
| dell / lenovo | 4 | 4 | 정상 |
| hpe | 7 | 7 | 정상 |
| supermicro | 6 | 6 | 정상 |
| fujitsu / quanta | 1 | 1 | 정상 |
| huawei / inspur | 1 | **0 → 1 (2026-08-10 fix)** | 키 이름이 `oem_normalize` 오타였음 |
| **cisco** | **0** | **0** | **미해결 — 아래 참조** |

- **cisco 미해결 사유**: 연결하면 `data.bmc.oem_cisco` 가 신설되어 envelope 이 바뀌고
  `cisco_baseline.json` 갱신이 동반된다 → rule 92 R1-B / rule 13 R4 **사용자 승인 사항**.
  NEXT_ACTIONS 등재 대상.
- **huawei 부가 사항**: `firmware_patterns` 가 정규식 자리에 glob(`iBMC*3.*`)이라
  실펌웨어가 오면 -9999 실격 → `redfish_generic` 선택 → **adapter 자체가 안 붙어
  collect OEM 도 함께 죽어 있었다.** 2026-08-10 정규식 정정 + 회귀 12건 신설.

## recovery_accounts 메타 (cycle-012 + M-A 보강)

각 Redfish adapter에 `credentials.recovery_accounts:` 블록 — vault accounts list 순서대로 후보 인증 + AccountService dryrun 복구 매핑. 형식:

```yaml
credentials:
  profile: "dell"
  fallback_profiles: []
  recovery_accounts:
    - { vault_label: dell_recovery_root, role: recovery }
```

**커버리지 (30/30)**: 모든 Redfish adapter 가 credentials 블록 보유. cycle 2026-05-11 M-A5 결과 9 vendor 모두 primary infraops/__REDACTED__ + recovery vendor 공장 기본 (rule 27 R6 / `docs/operate/05-vault.md`).

**dryrun 정책 (cycle 2026-04-30 갱신)**: `_rf_account_service_dryrun: false` (기본 — 사용자 명시 승인으로 OFF 전환). 실 PATCH/POST 호출되어 BMC 에 infraops 자동 생성/enable 됨. 시뮬레이션 강제는 `-e _rf_account_service_dryrun=true` override. ADR-2026-04-30-account-service-dryrun-off 참조.

**Cisco 한정**: AccountService 미지원 (Round 11 실측). dryrun 의미 없음 — 운영자 수동 복구 절차 매뉴얼 별도 (DEC-3 매트릭스).

## origin 주석 일관성 (cycle 2026-05-07 M-K1)

검증 도구: `python adapter origin 검사(제거됨) --all --redfish-only`

| 검증 항목 | 결과 |
|---|---|
| origin sources 1개 이상 (vendor docs / DMTF / GitHub / 사이트 evidence) | 30/30 PASS |
| 사이트 검증 adapter (dell_idrac10/hpe_ilo7/lenovo_xcc3/cisco_ucs_xseries) — `lab tested` / `Lab status: PASS` / commit hash 표기 | 4/4 PASS |
| lab 부재 adapter — `부재` / `web sources` 명시 | 25/25 PASS |
| lab 부재 adapter — `Next action:` / `lab 도입 후 별도 cycle` 라인 | 25/25 PASS |
| Generic fallback (redfish_generic.yml) — vendor 면제 | 1/1 PASS |

## OS 채널 (7 adapters)

| Adapter | 대상 |
|---|---|
| `linux_rhel.yml` | RHEL / CentOS / Rocky / Alma |
| `linux_ubuntu.yml` | Ubuntu |
| `linux_suse.yml` | SUSE / SLES |
| `linux_generic.yml` | 기타 Linux fallback |
| `windows_2022.yml` | Windows Server 2022 |
| `windows_2019.yml` | Windows Server 2019 |
| `windows_generic.yml` | 기타 Windows fallback |

## ESXi 채널 (4 adapters)

| Adapter | 대상 |
|---|---|
| `esxi_9x.yml` | ESXi 9.x (2026-08-13 신설, priority 100 — 8x 와 동률) |
| `esxi_8x.yml` | ESXi 8.x |
| `esxi_7x.yml` | ESXi 7.x |
| `esxi_6x.yml` | ESXi 6.x |
| `esxi_generic.yml` | fallback |

## 갱신 history (cycle 단위)

| cycle | adapter 변경 (Redfish) | OEM tasks 변경 |
|---|---|---|
| 2026-04-29 (production-audit) | 16 | Dell/HPE/Lenovo/Supermicro placeholder |
| 2026-05-01 (gather-coverage) | 27 (+11) | (변경 없음) |
| 2026-05-06 (multi-session) | 28 (+1 hpe_superdome_flex) | (변경 없음) |
| 2026-05-07 (all-vendor-coverage) | 30 (+2: supermicro_x10/ars) | +5 (Cisco M-J1 / Huawei M-C2 / Inspur M-D1 / Fujitsu M-E2 / Quanta M-F1) |
| **2026-05-11 (hpe-csus-add)** | **31 (+1 hpe_csus_3200)** | **HPE regex 확장 Additive (Superdome|Flex → Superdome|Flex|Compute Scale-up|CSUS)** |
| **2026-05-12 (hpe-csus-rmc-multi-node)** | **31 (변경 없음)** | **HPE CSUS 3200 / Superdome Flex `vendor_notes.multi_node_support: true` Additive — RMC primary 시스템 전수 수집 (ADR-2026-05-12 / `data.multi_node` 컨테이너)** |

## 갱신 trigger (rule 28 #3)

- TTL 14일
- adapters/*.yml 수정
- vendor_aliases.yml 수정
- 새 vendor 추가 (rule 50 R2)
- 새 OEM tasks 디렉터리 추가 (vendor task)

## 측정 명령

```bash
ls adapters/redfish/*.yml | wc -l
for f in adapters/redfish/*.yml; do
  base=$(basename "$f")
  prio=$(grep -E '^priority:' "$f" | head -1)
  aid=$(grep -E '^adapter_id:' "$f" | head -1)
  printf '%-32s | %-26s | %s\n' "$base" "$aid" "$prio"
done

# origin 주석 일관성 검증
python adapter origin 검사(제거됨) --all --redfish-only
```

## 정본 reference

- `.claude/policy/vendor-boundary-map.yaml`
- `.claude/ai-context/vendors/{vendor}.md`
- `docs/reference/live-validation.md`
- `docs/develop/03-adapter-system.md`
- 외부 API 공식 문서
- `docs/ai/catalogs/EXTERNAL_CONTRACTS.md` (9 vendor × N gen × source URL 매트릭스 — M-K2)
- `docs/ai/catalogs/COMPATIBILITY-MATRIX.md` (vendor × generation × section — M-L3)
