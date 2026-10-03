# ClovirONE Server Gathering 개선 — 최종 작업결과서 (2026-10-03)

> 기준: 사용자 승인 Plan(Astra 3차 검토 조건부 통과, 2026-10-03) · 작업지시서 "ClovirONE Server Gathering 최종 작업지시서"(기준일 2026-10-02).
> 저장소 `main` — 시작 `70859e08` → 종료 `25bb5343` 이후 결과서 커밋(27+ 커밋, github + gitlab 동기). production 브랜치는 **바꾸지 않았다**(`4ce90a00` 그대로 — 아래 7절).
> 완료는 G-11 계층으로 나눈다: **코드 수준 완료 · 생성물 수준 완료 · 실환경 수준 미검증**. 미실행을 통과로 적지 않았다.

## 0. 한눈에

| 계층 | 상태 | 근거 |
|---|---|---|
| 코드 수준 (Phase 2 · 3 · 4 · 5 · 6 · 7a) | **완료** | 단위 · 렌더 · 재생 · WSL 실제 ansible 실행 · Groovy 로컬 실행 · Jenkins 선언형 린터. 아래 2~6절 |
| 생성물 수준 (production runtime-only tree) | **완료 (반영은 보류)** | prodgen: 192 파일 · 1.04 MB · class B 0 · **gate G01~G17 전부 PASS**(G14 = 생성 tree 위 pytest 3,674 passed) · 결정성 |
| 실환경 수준 (두 Job E2E · RHEL 9.6/10.2 · Kernel 6.x 두 트랙 · BMC/ESXi 실장비) | **미검증** | 이 세션의 실행 환경(auto 권한 모드 분류기)이 SSH(`10.100.64.33~38`) · Jenkins 빌드 트리거 · BMC/ESXi 접근을 거부했다 — 8절 |

## 1. 성능 — 변경 전 → 후 (사용자 요구: 수치와 개선율)

측정 종류를 구분한다: **재생(오프라인, 실장비 recording)** · **정적 계수(task 파일)** · **WSL 실제 ansible 실행** · **WSL emulation**. 실장비 · Runner 시간 측정은 없다(8절).

### 1-1. Redfish — HTTP 요청 수 (real_* recording 재생, `tests/integration/test_request_budget.py` 가 다중집합을 고정)

| fixture | 전 | 후 | Δ | 정당한 증가 | 비고 |
|---|---:|---:|---:|---:|---|
| Dell R740 (iDRAC9) | 168 | 137 | −31 (−18.5 %) | 0 | firmware 멤버 GET 62 → 32 (동일 version 중복 GET 전 제거, first-seen · id 불변) + Systems 캐시 −1 |
| HPE CSUS 3200 (RMC primary) | 218 | 134 | −84 (−38.5 %) | 0 | 200 응답 프로세스 내 캐시(deep copy) — Partition0 하위 · Power/Thermal · 컬렉션 재조회 제거 |
| HPE DL380 (iLO) | 132 | 131 | −1 | 0 | Systems/<id> 캐시 |
| Lenovo SR650 (XCC) | 124 | 123 | −1 | 0 | Systems/<id> 캐시 |

- golden(`expected_output.json`) 전부 동일 — 요청이 줄었는데 데이터도 준 경우 없음(coverage 는 golden 동치가 더 강한 조건).
- 재생에 없는 절감: `mode: detect`(익명 Systems 허용 장비에서 전 섹션 ≈120~170 GET → 식별 + 2 GET), 마지막 후보 뒤 backoff 생략(N3 — 표준 계정 1벌 환경에서 401 host 당 65 s).

### 1-2. 채널별 host 당 원격 실행 수 (정적 계수 + WSL 실제 ansible 실행으로 확인)

| 채널 | 전 | 후 | Δ | 확인 방법 |
|---|---:|---:|---:|---|
| Linux Python 모드 | 18 (+0~2) | 10 | −44 % | 6 reference 캡처 × 6 권한 × 2 모드 fragment 동일(432 집합), WSL 실제 play 4회 envelope 동일. dmidecode 2~3 → 1, getent 3 → 2 |
| Linux raw 모드 | 13 | 9 | −31 % | 위와 같음 |
| Windows win_shell | 20 | 11 | −45 % | 27 시나리오 종전 vs 신규 fragment 동일, powershell.exe `-EncodedCommand` 실행 15 시나리오 동일, `.120` live 출력 재현. WinRM 왕복 22 → 13 |
| ESXi 모듈 실행 | 13 | 12 | −8 % | 자격 probe facts 재사용 — WSL 실제 play(fake 모듈) 호출 2→1 · 2→1 · 3→2 · 1→1. `esxi_disks` view 4 → 1 |

### 1-3. 규모 (WSL emulation — 실장비 아님, `tests/evidence/2026-10-03-phase5-emulation.md`)

| 항목 | 결과 |
|---|---|
| 실패 경로 wall (10 / 50 / 100 / 200 host) | 10.6–11.0 / 24.7–37.5 / 52–68 / 104–116 s ≈ 0.5–0.6 s/host, forks 50 ↔ 100 차이 없음 |
| 메모리 | fork 슬롯당 트리 PSS ≈ 36 MB (forks 100 ≈ 3.7 GB) → **OS forks 기본 상한 100 → 50**(`SE_FORKS_CAP_OS` 로 상향) |
| 결과 완전성 | 완주 30회 + 중단 6회 전부 요청 == 결과 (kept + filled = 접수) |
| 중단 | INT → rc 124, 3.5–6.9 s 종료, 고아 0; 6회 중 1회 INT 소실(weakref 콜백) → `--kill-after=90` rc 137 — 그래도 보충 정확 |
| 기록 비용 (progress/checkpoint) | 같은 설정 반복 편차보다 작아 분리 불가 (상한 ≈ 80 ms/host) |
| Layer A 1000 host | 0.21 / 0.23 / 0.12 s (전원 OUTPUT / 혼합 / 전원 합성) |

### 1-4. production 경량화 (runtime 개선이 아니다 — 분리 보고)

| 항목 | 전 (production `4ce90a00`) | 후 (생성 tree, main `dcfbfded`) |
|---|---:|---:|
| 파일 수 | 983 | 192 (−80 %) |
| 바이트 | 10,361,592 | 1,035,135 (−90 %) |
| 설명성 주석 | 남아 있음 | 전행 6,427 · 꼬리 556 제거, runtime-required 57줄만 보존(셔뱅 9 · coding 17 · 셸 셔뱅 8 · argparse docstring 23), 미제거(B) 0 |

## 2. 정확성 · 호환성 (Phase 2, 커밋 `9f94c2ef` `b935b20e` `6371ba57` `4fe9712a` `5a60d420`)

| ID | 결과 |
|---|---|
| C1 Linux DIMM | dmidecode rc/stderr 마커 · kB/TB · 레코드 경계 · Configured 속도 우선(dmidecode<3.2 포함) · 총량>0 & DIMM 0 → errors 1건. **검수 중 발견**: 비루트 dmidecode 머리말+rc≠0 에서 sudo 재시도가 한 번도 돌지 않던 조건 수정 |
| C2 Linux storage | lsblk 실패 마스킹 제거 → rc/상태(unknown·unsupported·permission·malformed·empty) · 레거시 열 fallback · `from_json` 가드 · df `timeout 20`. multipath 는 조건부(R8) 그대로 |
| C3/C4 Windows | 공식 BusType 표(enum 밖 → null + detail) · UInt16/Int32/문자열 통합 · HBA 미매칭 null · ConnectionType 1/2 · OperationalStatus · `-EncodedCommand` 32,767자 한도 발견(주석 이동 + 테스트) |
| C5 Redfish collection | opaque `nextLink` 페이지네이션(same-origin · 순환 차단 · 64 페이지/1024 멤버) · memory 용량 미확인 구분(일부 → 합계 null, 전부 → null + error, MemorySummary fallback 1회) |
| C6 firmware | 동일 version 중복만 GET 전 제거(first-seen) · 대체 후보 fallback · Name-only 상세 GET · 실패 → errors(비차단) |
| C7 HBA | Linux sysfs 읽기 실패 마커 → errors, Redfish NDF 실패 errors, `normalize_wwn`(all-zero → null) |
| C8 ESXi | 존재하지 않던 `portRange` → `endPort`, Host 선택 규칙(유일 / 안정 식별자 / 모호 시 오류 — `hosts[0]` 금지), view 1회, `httpConnectionTimeout` + SmartConnect 소켓 timeout |
| C9 계정 복구 판정 | `_confirm_account_state` 불일치 → `recovered` false(`state_mismatch`). 실장비 write 는 미검증(AWC) |
| C10/N2/N8 | 실패 envelope shape 통일(hostname null · 11 sections · meta 6 · correlation 4 · data 뼈대), redfish rescue 지원 섹션 목록 = adapter capabilities → `supported_sections.yml` |
| S1/N4 | 멤버 수준 401/403 은 host failed 판정 제외(`_CODE_NON_BLOCKING_SUBRESOURCE`), 컬렉션/앵커 401/403 은 종전대로 |
| 추가 발견 | Linux driver_map `vlan_id` 가 항상 null(/proc/net/vlan 파싱) → 수정; ESXi `_e_probe_ok` 판정 근거 과소(수정 안 함 — GP-12) |
| Kernel 6.x (Red Hat 계열) 두 트랙 | **미검증** — `.37/.38` 접근 불가. 저장소 증거는 Ubuntu 24.04 kernel 6.8(R760)뿐. 재현 여부를 말할 수 없다(미재현 아님) |

## 3. Pipeline (Phase 4, `5c2c8839` 외)

- Timeout 계층: 전체 150분 → Gather stage 합산 115분 → **ansible 직전 재계산 예산**(`scripts/gather_budget.sh`) → task `timeout`(Linux 120 · Windows 180 · ESXi 180 · Redfish 120/600/240) → 모듈 `deadline`(90/540/180) · Add-on 태스크 300 · SSH `ansible_timeout` 15(N6).
- Partial failure: 요청 1 = 결과 1 — Layer A(`scripts/finalize_gather_output.py`) OUTPUT → CHECKPOINT → 진행 기록 합성, Layer B(Groovy `scripts/jenkins/se_finalize.groovy`, `load`) 최소 경로. 콜백 진행 이벤트 · CHECKPOINT · manifest 대조.
- Finalization · Callback: `Validate Schema` · `Callback` stage 삭제 → pipeline `post { always }` 마무리(720 s 합산, 단축 사다리, ≤3회, 4xx 중단, ABORTED 1회), Runner 부재는 접수 후 실패 + Callback.
- Add-on: 조립 뒤(D8) · CHECKPOINT 보존 · 태스크별 timeout(2026-09-21 결정 변경).
- Redfish 인증 증거: attempt 파일 → task timeout 뒤 401 / 2xx 정지 / 증거 없음 3분류 (Astra 3차 acceptance ②), 예산 재계산(acceptance ①).

## 4. CI · Harness (Phase 6, `f1221234` `5683a778` `5a441259`)

- `Jenkinsfile_ci`(main 전용 일반 Pipeline, 트리거 없음): Checkout MAIN_SHA → Toolchain → Gate(`scripts/ai/ci_gate.sh`) → Finalize Corpus(Python + Groovy `load`) → Budget Self-test. Job 등록은 사용자(GP-15) — Jenkins 에서는 아직 돈 적 없다.
- finalize corpus 14 case(Layer A oracle) + Groovy 동치 로컬 실행(Groovy 4.0.24 · 2.4.21) MATCH 14 / 음성 대조 4 검출.
- rule 80 R1·R1-C, rule 93/24/90, CLAUDE.md §14, ADR 2건, 운영 문서 `docs/operate/03·04·09`, 카탈로그 갱신.

## 5. 테스트 (최종 상태, 2026-10-03)

| 묶음 | 결과 |
|---|---|
| WSL `pytest tests/e2e` | 772 passed · 6 skipped |
| WSL `pytest tests/unit tests/e2e` **동시 실행** | 3747 passed, 97 skipped, 51 deselected, 4 warnings in 103.04s (0:01:43) (PowerShell · prodgen 파서 의존 테스트는 skip) |
| Windows 신규/변경 단위 묶음 | Phase 4 243 · Windows 279(+128) · Phase 6 59 · prodgen 69 · Linux P3 153 · G14 표식 126 |
| WSL 실제 ansible-playbook | Add-on 엔진 14, Linux C1/C2 3 시나리오, Linux P3 4회, ESXi P5 4 시나리오, 3채널 `--syntax-check` |
| Jenkins 선언형 린터 | `Jenkinsfile_portal`(최종본) · `Jenkinsfile_ci` validated |

## 6. Repository 반영

27+ 커밋(`70859e08` → `25bb5343` 이후 결과서 커밋), 제품 코드(`feat/fix/test`) 와 하네스(`harness/docs`) 분리, github + gitlab 동시 push. force push 없음. production 미반영.

## 7. Production (Phase 7a 완료 · 7b 보류)

- 생성기 `scripts/ai/prodgen` + `production_manifest.yml`(allowlist, 언어 명시) + gate G01~G17 + provenance + drift-check + plumbing promote/restore + 테스트 69.
- main `dcfbfded` 생성: 192 파일 · 1,035,135 B(원본 blob 1,783,330 B) · tree `49bd0d88…` · B 0 · 분류 included 192 / ignored 161 / excluded 5 / 미분류 0.
  gate: G01~G13 · G15~G17 **PASS**(G11 3채널 syntax-check, G12 config dump 동일, G13 린터 validated, G15 모듈 smoke 3종 구조화 실패 JSON, G16 inventory 동치, G17 2회 생성 동일).
  G14(tests overlay): 1차 수집 오류 2건(생성 tree 에 없는 `scripts/ai` · `Jenkinsfile_ci` import) → 2차 conftest 이름 충돌 6건(`tests/unit/prodgen/conftest.py` 가 `conftest` 를 차지해 e2e 의 `from conftest import` 가 깨짐)
  → 패키지화 · module skip · overlay 에 `pytest.ini` 포함 뒤 **PASS: 3,674 passed · 87 skipped · 31 deselected(source_text) · 0 failed/errors**(main `25bb5343`, tree hash 동일 `49bd0d88…`).
- `promote --sha 42cc213f --dry-run --skip-live`: parent `4ce90a00`(현재 production), git tree `88280034`(193 entries, provenance 포함), trailer `Main-SHA 42cc213f` · `Tree-Hash 49bd0d88…`
  — 문서/규칙만 바뀐 `dcfbfded`→`42cc213f` 사이 tree hash 가 같다(runtime 외 파일은 tree 에 영향 없음). 객체 · ref 변경 없음(`origin/production` = `4ce90a00` 확인).
- **7b 보류 사유**: Plan 은 7b 직후 production Job canary(7c)를 완료 조건으로 둔다. 이 세션은 Jenkins 빌드를 실행할 수 없고, Phase 1.5·4 파이프라인은 Jenkins 에서 한 번도 돌지 않았다. Portal 이
  바로 쓰는 브랜치에 미검증 파이프라인을 올리지 않는다. 재개: `docs/operate/09-production-branch.md` 3절 (main Job 1회 성공 → `promote --push-remote origin` → canary → 실패면 `restore`).
- 환경 전제: Runner `pwsh`(없으면 PowerShell 주석이 B 로 남아 승격 차단, GP-16), CI Job 등록(GP-15).

## 8. 실행하지 못한 것과 재개 방법 (사용자 결정)

| 항목 | 상태 | 막힌 이유 · 재개 |
|---|---|---|
| main Job · production Job 실제 빌드(§10-4 · §10-5 전 시나리오, Callback → `10.100.64.151:8080`) | 미실행 | 세션 권한 모드가 Jenkins `buildWithParameters` POST 를 "Production Deploy" 로 거부. 사용자가 세션 권한 모드를 바꾸거나(해당 Bash 규칙 허용) 직접 빌드를 돌려 build 번호를 알려 주면 콘솔·artifact 로 검증한다 |
| `.33~.38` RHEL 9.6/10.2 읽기 전용 정찰 · Kernel 6.x 두 트랙 · 실장비 동등성 | 미실행 | SSH 를 "Production Reads" 로 거부. 같은 방법으로 재개 |
| BMC 4대 · ESXi 2대 · Windows `.120` 실장비 | 미실행 | 같은 범주로 판단해 시도하지 않음(Redfish 는 dry-run 강제 경로로만) |
| Runner(ansible-core 2.20.3)에서 timeout/apply.timeout/INT 소실 재현 | 미실행 | GP-10 · GP-19 |
| Redfish 성공 경로 규모 측정 | 불가 | 443 바인드 권한 · 모듈 포트 고정 · vault — GP-20 |
| production 반영 + canary | 보류 | 7절, GP-21 |

전체 후속 표는 `docs/ai/NEXT_ACTIONS.md` GP-1 ~ GP-23.

## 9. 보안 확인

자격증명은 scratchpad(netrc) 와 WSL 홈에만 두었고 저장소 · fixture · 테스트 · 로그 · 커밋에 복사하지 않았다. 증거 파일(인증 evidence)에는 username/password 가 없다(테스트가 grep 으로 고정).
production Credential · 운영 계정 · BMC 계정 · VM 설정은 바꾸지 않았다.
