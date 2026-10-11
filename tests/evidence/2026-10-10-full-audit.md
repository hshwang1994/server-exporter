# 2026-10-10 — 전체 감사 · 결함 수정 · 검증 · 승격 (지시서 17절)

> 증거 대장 정본은 저장소 밖 `C:\github\ClovirONE\evidence-audit-2026-10-10\`(ledger.json · expected_diffs.json · raw/ · probes/ · mutations/)다.
> 이 문서는 그 요약이다. 숫자는 그 실행 결과에서 옮겼고, 아직 돌지 않은 단계는 "미실행" 으로 적는다. 비밀값은 어디에도 없다.

## 1. 범위와 진행 방식

- 입력: 사용자 지시서(2026-10-10) 17절 + 계획 v3(사용자 보정 10개). 단계별 재승인 없이 끝까지. 결정은 작성자 결정(D-01~D-12, 근거 기록)과
  사용자 결정(BIOS 패키지 삭제 · `tests/reference` 유지 · Jenkins admin 자격 채팅 전달 · §8 운영 정책 유지)으로 나눠 적는다.
- 후보 SHA(main): X0 `3d053d36`(검수 C1~C10 반영) → X1 `b3c8ebf7`(B-R · B-J · B-H · DOC-01/02) → X2(이 문서의 결함 묶음 B-RD/RA · B-E · B-W · B-L · FL-F01b).
- 검증 사다리: unit_fixture → replay_capture → local_ansible_wsl(2.20.7) → runner_parity(2.20.3, 임시 Job) → jenkins_harness → main Job 매트릭스 → CI → production.

## 2. Harness · CI 를 먼저 신뢰할 수 있게 (B-H)

| 항목 | 결과 | 근거 |
|---|---|---|
| N1 기대값 뒤집은 scenarios.json | verdict **FAIL** · evidence 거부 | 임시 Job `se-audit-negative-control` (scratch 브랜치 `audit/negative-control`) |
| N2 수신기 미기동 `sink_5xx` | **PARTIAL** (PASS 아님) | 같은 임시 Job |
| N3 지난 PASS 증거 변조 | 결속 불일치 거부. 한계 2건 기록(digest 재계산 재결속 · 전부 다시 쓴 산출물은 Jenkins 산출물 무결성만 지킨다) | `mutations/n3_results.json` |
| N4 SKIPPED 가 든 stage 결과로 dry-run 승격 | 거부 | 로컬 |
| 변이 M1~M9 | 9/9 검출 — M1(OUTPUT 태스크 이름)은 처음 미검출 → `tests/unit/test_output_task_names.py` 신설 뒤 재검출 | `mutations/results*/` |
| HC-01/02 | CI Job XML 기본 목록 = Jenkinsfile 기본 = `evidence.REQUIRED_*` 강제 · `sink_close` 필수 집합 추가 | 단위 시험 |
| HC-06 | 공유 Harness Job 은 main 조상이 아닌 SHA 를 거부한다(NOT_ANCESTOR) — 설계대로 | 임시 Job 으로 우회 |

## 3. 후보별 실행 결과

| 후보 | WSL ci_gate | prodgen build | main Job 매트릭스(15) | strict compare | CI | 승격 |
|---|---|---|---|---|---|---|
| X0 `3d053d36` | PASS | class B 0 | #408~#422 계약대로(T5 재실행 뒤 ABORTED) | 차이 = 선언(T5 합성 봉투 진단 보존)만 | #40 SUCCESS · COMPLETE_PASS | 안 함(Harness 미신뢰 단계) |
| X1 `b3c8ebf7` | PASS | tree `96db8f5f…` | #423~#438 계약대로(T5 재실행 #438) | OK | **#41 FAILURE** — Harness 54 중 `prep_failed_on_resume` 1건 기대 불일치(FL-F01b) | 안 함 |
| X2 `32d4e307` | **FAIL 1**(시험이 Windows 샌드박스 가정) | class B 0 · tree `20fb2094…` | — | — | — | 안 함 |
| X2' `361d4484`(시험만 수정) | PASS(깨끗한 checkout · 4,879/182/7 · integration 333) | tree `20fb2094…`(X2 와 동일) | #454~#468 계약대로(T5 #456 → 재실행 #469 ABORTED) | 회귀 0 — 선언 D-03(Windows) · D-08 · WIN-02 · WIN-DM | **#42 SUCCESS · COMPLETE_PASS** | CLI dry-run 거부(PC G14 1건 HC-T6b) |
| X3 `00cb1bf3` → X4 `c2d76de2`(시험 · 문서 · 하네스만) | PASS(각 4,909/153/7) · PC G14 overlay 4,739 통과 0 실패 | tree `20fb2094…`(동일) | #470~#484 계약대로(T5 #472 → 재실행 #485 ABORTED) | 회귀 0 — ENV-01(10.50.11.231 복구) 선언 뒤 | **#43 SUCCESS · COMPLETE_PASS**(Gate 4,909/153) | **P11 `35b9ad5e`** |
| X6 `3b84b65f`(2026-10-11 — adapter 미참조 절 제거 · 삭제 묶음 · 문서, runtime tree 변경) | PASS(깨끗한 checkout 4,817/153/7 · integration 333; 첫 tip `0286a3ec` 는 adapter 계약 시험 1건 FAIL → 시험 수정) · PC 전체 suite 미완(저메모리 2회 중단, D-21) | class B 0 · tree `ab065f3d…` | #488~#503 계약대로(T5 #490 → 재실행 #503 ABORTED) | 회귀 0 — 선언 사용 D-03 (Windows) · D-08 · LX-F04 · WIN-02 · WIN-DM | **#44 FAILURE** — Prodgen Verify G14 2건(HC-T7: 새 시험이 manifest excluded 운영자 도구를 읽음) | 안 함 → X7 |
| X7 `9a6ee77b`(시험 표식 · 가드 시험 · FAILURE_PATTERNS 만, tree 동일) | PASS(깨끗한 checkout) | tree `ab065f3d…`(X6 와 동일) | #504~#519 계약대로(T5 #506 → 재실행 #519 ABORTED) | 회귀 0 — 선언 사용 D-03 (Windows) · D-08 · LX-F04 · WIN-02 · WIN-DM | **#45 SUCCESS · COMPLETE_PASS**(Gate 4819/153 · Harness 54+23) | **P12 `410317a7`** |

X1 의 Harness 불일치: 이어서 하는 시도가 begin 전에 끝나면(rc 90) Jenkins 가 아는 앞 시도의 연결 끊김 근거가 상태 파일에 전달되지 않아 앞 시도가
`process_lost` 로 닫혔다(기대 `agent_disconnect`). 파이프라인 outcome(`prep_failed`)은 설계대로였다. X2 에서 `seClassifyAttempt(agentLost)` 로 고쳤다.

## 4. 결함 묶음 (X2) — 바뀐 것과 증거 수준

증거 수준: U=unit/fixture · S=raw 스크립트 샌드박스(POSIX sh) · W=WSL ansible 2.20.7 · R=Runner ansible 2.20.3(임시 Job) · H=Jenkins Harness · M=main Job 매트릭스(lab).

| 묶음 | 항목 | 수준 |
|---|---|---|
| B-RD/RA (Redfish) | RD-F03 IncompleteRead 분류 · D-09 vendor alias(iBMC≠ibm) · RA-F05/F06 복구 인증 예산·간격 · RD-F18 하위 자원 404 아닌 실패 errors[] · RD-F15 FC/FCoE 포트 · D-07 PSU Absent 제외 · RD-FW1 RAID 분류 · RD-UNK/FW2 · 죽은 normalize 4개 삭제 | U (+M 예정) |
| B-E (ESXi) | ESXI-03 config_info `esxi_hostname` + DNS 오류 조건(dns_info 만 — 인자 오류는 전 host, partial 은 이름 서버가 빈 host 만) · ESXI-21 자격 변수 통일 · D-01 vCenter 거부 · ESXI-09 TB/GB/MB · ESXI-12 컨트롤러 종류 · ESXI-13 시도 수 · D-03 defaultPolicy | U · R(argspec) (+M 예정) |
| B-W (Windows) | WIN-02 fec0 · WIN-11/12 IPv6 게이트웨이 · WIN-DM 드라이버 전수 · D-02 VBS · D-03 ActiveStore · WIN-13 CIM 격리 · WIN-21 부분합 금지 · D-08 디스크 크기 | U(실제 powershell.exe 5.1) (+M 예정) |
| B-L (Linux) | LX-F08 기본 경로 토큰 파싱(ECMP·nhid·IPv6) · LX-F02 'None' 게이트웨이 · LX-F10 lspci 표식 · LX-F01 비특권/특권 분리 · D-03 유효 정책 · LX-F04 multipath · LX-F06 캐시 인스턴스 · LX-F12 자리표시자 집합 · D-10 JEDEC bank | U · S · W · **R**(LX-F02: Runner01/03 에서 'None' 재현) (+M 예정) |
| B-J 후속 | FL-F01b classify 에 연결 끊김 근거 전달 | H 예정(X2 CI) |

바꾸지 않은 것: envelope 13 필드 · 섹션 · field_dictionary 의미 · failure_code/stage 집합 · §8 운영 정책 · 계정 쓰기(HOLD).

## 5. 검증 (X2 working tree, 이 PC)

| 구분 | 결과 |
|---|---|
| 정적 | YAML 40 파일 parse OK · Python compile OK · verify_vendor_boundary 통과 · verify_harness_consistency 통과 · verify_docs_references(이 문서 생성 뒤) |
| 채널별 단위 | Redfish 감사 15 · ESXi 묶음 91 · Windows 325+98(실제 PowerShell) · Linux 388+45 · JEDEC/드리프트/메모리 104 · 식별자 자리표시자 묶음 171 · Jenkinsfile/Harness 157 |
| 전체 suite(unit · e2e · regression) | 이 PC 4,998 통과 · 63 건너뜀 · 7 xfail / WSL(깨끗한 `361d4484`) 4,879 통과 · 182 건너뜀(ID 보존) · integration 333 |
| lab 읽기 전용 probe(Runner02, `se-audit-labprobe` #1~#3) | Linux 4/7 도달(.165 .167 .169 미도달) · Windows .120(.135 미도달) · ESXi 3/3 — 가설 확정: fec0 자리표시자 · MSFT≠Win32 디스크 크기 · ActiveStore≠PersistentStore · config_info+esxi_hostname 성공 / 기각: LX-F09 / 미확정: LX-F11(IB 장치 없음) |

## 6. 삭제 · 정리

- 삭제(사용자 결정): `REDFISH_BIOS_GATHERING_PLAN_MODE_PACKAGE_00-11_2026-09-14/`(미추적 320K).
- 삭제(참조 0 확인): `redfish-gather/tasks/normalize_{system,network,storage}.yml` · `esxi-gather/tasks/normalize_sections.yml` · `_endpoint_with_fallback`.
- 유지(사용자 결정): `tests/reference` 전부.
- 임시 Jenkins 자원(D-12): `se-audit-parity` · `se-audit-negative-control` · `se-audit-labprobe` Job, 브랜치 `audit/negative-control` — 감사 끝에 삭제하고 확인했다(2026-10-11 재확인: REST 404 · ls-remote 0).
- 삭제(2026-10-11 정리 묶음 D-19 — 참조 0 · 고유 내용 없음 확인 뒤): adapter 43개의 미참조 절(`collect` · `normalize` · `credentials` · `graceful_degradation` · `auth` · `diagnosis` · `channel`) ·
  `adapters/registry.yml` · `common/vars/status_rules.yml` · `scripts/verify_account_provision.sh` + `jenkins/jobs/redfish-account-provision-verify/`(Jenkins 에 등록된 적 없음 — REST 확인) ·
  `scripts/ai/promote_to_production.sh`(shim) · `scripts/ai/one_off/` · `scripts/ai/bug_tracker/` · vault 일회성 스크립트 5 · `tests/e2e_browser/` · `tests/redfish-probe/{validate_fields,probe_volumes}.py` ·
  완료 ticket · 하네스 일회성 문서 3. 유지: `tests/evidence/2026-04-29-full-lab-sweep.md` · `tests/reference` 전부.

## 7. 결과 추가 (진행 중)

- [x] 전체 suite 결과(§5)
- [x] lab probe 결과(P4 · P8 · P11-lite — §5)
- [x] X2' · X4 push · WSL ci_gate · 매트릭스 · strict compare · CI(§3)
- [x] 승격 · canary · 명부 전수(§9)
- [x] 성능 전후(§9)
- [x] 정리 완료 확인 — 임시 Job 3 · scratch 브랜치 삭제(대장 cleanup-*, 2026-10-11 재확인)
- [x] 2026-10-11 후속 집행: X6 `3b84b65f` push · WSL ci_gate · 매트릭스 #488~#503 · strict compare · CI #44(G14 FAIL → HC-T7) · X7 `9a6ee77b` · 매트릭스 #504~#519 · CI #45 · 승격 P12 `410317a7` · 명부 #274~#279 · P11 대조(§9)

## 8. 감사 중 발견한 하네스 맹점 · 문서 정정 (X3 — 시험 · 문서만, runtime 불변)

- **HC-09**: `tests/e2e/test_diagnosis_template_ansible_render.py`(26) · `test_bios_attributes_ansible_render.py`(3) 가 전체 suite 에서 늘 skip 됐다 — unit 계층이 `sys.modules` 에 심는
  ansible 대역 때문에 수집 시점의 `from ansible.template import Templar` 가 "'ansible' is not a package" 로 실패했고, skip 사유는 "플랫폼" 이라 적혀 있었다. **Runner CI Gate 도 같았다**
  (CI #40 161 · #41 162 건너뜀). 수정: 첫 사용 시 `__spec__` 없는 `ansible*` 대역을 치우고 실물을 import(실패 시 복원 · 사유 표기) + 회귀 1건. WSL 전체 suite 4,879 → 4,909 통과 · 0 실패.
- **rule 12 R4**: "4개 키 필수(adapter_loader 파싱 실패)" 는 코드와 달랐다 — 로더는 `match` · `adapter_id` · `priority` · `generic` 만 읽고 강제 없음, 플레이북은 `capabilities.sections_supported` ·
  `vendor_notes.manager_layout` · `version`. `collect` · `normalize` · `credentials` · `graceful_degradation` 절은 아무 코드도 읽지 않는다(OS · ESXi adapter 12개는 `normalize` 없음).
  규칙 · skill · 개발 문서를 코드대로 고쳤다(`ADR-2026-10-10-adapter-required-keys.md` · DRIFT-024). 기록용 절 삭제는 별도 결정(NEXT_ACTIONS).
- **DRIFT-016/017 재번호**: 커밋 `32d4e307` 이 붙인 두 항목은 이미 쓰인 번호였다(2026-05-11 · 2026-06-08) → DRIFT-022/023 으로 재번호해 머리로 옮겼다(FAILURE_PATTERNS 기록).
- **HC-T6b**: X2' 의 CLI 승격 dry-run 이 이 PC 의 G14 재실행(생성 tree + tests overlay, `PYTHONIOENCODING` 없음)에서 `test_cli_exit_codes` 1건으로 거부됐다 — 자식 프로세스의
  한글 stderr 가 cp949 로 나오는데 시험은 utf-8 로 읽었다(X1 의 HC-T6 수정은 셸이 export 한 `PYTHONIOENCODING` 에 기대고 있었다). 자식 env 를 고정해 고쳤고(X4) 같은 overlay 에서
  재현 → 통과를 확인했다. 승격 대상은 X4 가 되며 매트릭스 · CI 를 다시 돈다(D-15 정정 · D-16).

## 9. 승격 · production 명부 · 성능 (2026-10-10)

- **승격**: X4 `c2d76de2` → **production P11 `35b9ad5e`**(parent P10 `9ddc174a`). CLI `prodgen promote`(CI #43 집계 보고서 재사용 · 환경 의존 gate G11~G15 · G18~G20 PC 재실행 · COMPLETE_PASS) ·
  origin(GitHub+GitLab) · internal · 로컬 동일 · drift-check PROVENANCE · 새 clone tree 동일(`b3a44151…`) · trailer Main-SHA/Tree-Hash/Previous-Production/CI-Build/Gates-Rerun.
  X2' 의 dry-run 은 PC G14 1건(HC-T6b)으로 거부 — 시험만 고친 X4 로 승격(runtime tree 는 X2 `32d4e307` 부터 `20fb2094…` 동일).
- **production 명부**(Job `clovirone-server-gather`, checkout == P11 전부, Portal HTTP 200 전부): canary #233 os 3/3 · Linux A #234 8/8 · Linux B #235 4 + 미도달 3(.135 .145 .165 기존) ·
  Windows #236 .120 · ESXi #237 6/6 success(P10 과 같음 — lab ESXi 는 이름 서버가 있어 ESXI-03 partial 조건에 해당하지 않았다) · Redfish #238 7 + 실패 3(10.100.15.1 프로토콜 · 미도달 2 기존).
  P10 빌드(#197 · #185~#189)와 대상별 strict 대조: 회귀 0 — 선언 사용 D-03 (Windows), LX-F04, WIN-02, WIN-DM(LX-F04 표기는 .120 `storage.summary` 행에 먼저 매칭된 선언 이름 — 실제 원인은 D-08). Portal 저장 확인은 계약 밖(2xx 만).
- **성능**(같은 Job, 고정 집합 단일 5 · 배치 3, 순차, P10 #198~#232 vs P11 — 관측값이며 새 제한으로 쓰지 않는다):
  Jenkins 중앙값 초(전→후, Δ): PE1 62.3 → 63.1s(0.8) · PE6 68.6 → 77.4s(8.8) · PL1 52.4 → 54.9s(2.5) · PL4 62.7 → 60.4s(-2.3) · PLB 70.9 → 72.4s(1.5) · PR1 69.1 → 70.2s(1.1) · PR10 385.7 → 388.9s(3.2) · PW1 131.0 → 132.8s(1.8) · S3 205.6 → 210.8s(5.2)
  host `meta.duration_ms` 중앙값(전→후, Δ): PE1 25300 → 25689ms(389) · PE6 34007 → 37345ms(3338) · PL1 12887 → 13288ms(401) · PL4 19192 → 19643ms(451) · PLB 19076 → 19824ms(748) · PR1 34450 → 32298ms(-2152) · PR10 45598 → 44986ms(-612) · PW1 74592 → 74077ms(-515) · S3 52269 → 53473ms(1204)
- **미해결 · 미검증**: lab 부재(AMD lscpu<2.34 L3 · multipath · ECMP/nhid · vCenter · VBS 물리 Windows · GPO Windows · CNA · RD-DOC partition · LX-F11 IB) — fixture 수준 · NEXT_ACTIONS.

### 2026-10-11 — 후속 집행 X6 → X7 → production P12 (사용자 "계속 진행해라 모두 진행해라" · "모든 승인 하겠다")

- **무엇을 바꿨나(X6 `3b84b65f`, runtime tree `ab065f3d…`)**: adapter 43개에서 코드가 읽지 않는 절 제거(D-17 · 설계 메모는 `vendor_notes.design_hints`) · 읽는 코드가 없는 `common/vars/status_rules.yml` ·
  `adapters/registry.yml` · 미등록 계정 provision 검증 도구 삭제 · `bootstrap_vault_encrypt.sh` 현 vault 배치 재귀 탐색(0건 실패). 정적 확인: 플레이북이 읽는 adapter 키는 `adapter_id` ·
  `capabilities.sections_supported` · `vendor_notes.manager_layout` · `version`(없음 → `meta.adapter_version` null 전후 동일) 뿐 — 제거한 키를 읽는 코드 0.
- **X6 검증과 CI #44**: WSL ci_gate PASS(깨끗한 checkout; 첫 tip `0286a3ec` 는 신규 vendor adapter 시험이 옛 4키 계약을 고정해 1건 FAIL → 시험만 고친 `3b84b65f`) · prodgen build class B 0 ·
  main Job #488~#503 15 시나리오 계약대로(T5 #490 → 재실행 #503 ABORTED, checkout 전부 `3b84b65f`) · strict compare 회귀 0(선언 사용 D-03 (Windows) · D-08 · LX-F04 · WIN-02 · WIN-DM) ·
  **CI #44 FAILURE** — Gate 4,817/153 PASS 였지만 Prodgen Verify G14(생성 tree 위 tests overlay)에서 `test_bootstrap_vault_encrypt.py` 2건이 `FileNotFoundError`: 시험이 읽는
  `scripts/bootstrap_vault_encrypt.sh` 를 `production_manifest.yml` 이 운영자 도구로 제외한다(HC-T7). 개발 tree 검사(WSL ci_gate · PC suite)로는 보이지 않는 종류다.
  이 PC 의 전체 pytest 는 저메모리로 2회 중단돼 재시작하지 않았다(D-21).
- **X7 `9a6ee77b`(시험 · FAILURE_PATTERNS 만)**: 시험에 `source_text` 표식(G14 가 제외하는 관례, 44건) + 가드 `tests/unit/test_overlay_excluded_paths_marked.py`(manifest excluded 경로를 쓰는 시험 파일은 표식 의무).
  로컬 4 통과 · overlay 식으로 4 deselected · WSL ci_gate PASS(깨끗한 checkout) · prodgen tree `ab065f3d…`(X6 와 동일) · main Job #504~#519 15 시나리오 계약대로(T5 #506 → 재실행 #519 ABORTED) · strict compare 회귀 0(선언 사용 D-03 (Windows) · D-08 · LX-F04 · WIN-02 · WIN-DM) ·
  **CI #45 SUCCESS**(필수 10단계 PASS · Gate 4819/153 · Harness 54/54 + 23/23 · Verify COMPLETE_PASS).
- **승격**: X7 → **production P12 `410317a7`**(parent P11 `35b9ad5e`). CLI `prodgen promote`(CI #45 집계 보고서 재사용 · Gates-Rerun G11 G12 G13 G14 G15 G18 G19 G20 · COMPLETE_PASS) · origin(GitHub+GitLab) ·
  internal · 로컬 동일 · drift-check PROVENANCE · trailer Main-SHA `9a6ee77b` / Tree-Hash `ab065f3d…` / Previous-Production `35b9ad5e` / CI-Build 45. 실 승격은 3차에 성공 — 1차는 PC 네트워크 단절(G13 Jenkins linter timeout · G20 ls-remote 실패), 2차는 PC 메모리 고갈(G14 PowerShell 시험 · G15/G19 WSL staging)로 gate 가 거부했고 원격 변경은 0 이었다.
- **production 명부**(Job `clovirone-server-gather`, checkout == P12 전부, Portal HTTP 200 전부): canary #274 os 3/3 · Linux A #275 8/8 · Linux B #276 4 + 실패 3/7 · Windows #277 1/1 · ESXi #278 6/6 · Redfish #279 7 + 실패 3/10.
  P11 빌드(#233~#238)와 대상별 직접 strict 대조: 회귀 0 — 선언 사용 없음. 입력 원본 P10 빌드(#185~#197)와의 대조도 회귀 0(선언 사용 D-03 (Windows) · LX-F04 · WIN-02 · WIN-DM). Portal 저장 확인은 계약 밖(2xx 만).
- **성능**: 재측정 생략(D-20 — 수집 경로 불변, P10→P11 비교 유효).
