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
| X2 | 미실행 | 미실행 | 미실행 | 미실행 | 미실행 | 미실행 |

X1 의 Harness 불일치: 이어서 하는 시도가 begin 전에 끝나면(rc 90) Jenkins 가 아는 앞 시도의 연결 끊김 근거가 상태 파일에 전달되지 않아 앞 시도가
`process_lost` 로 닫혔다(기대 `agent_disconnect`). 파이프라인 outcome(`prep_failed`)은 설계대로였다. X2 에서 `seClassifyAttempt(agentLost)` 로 고쳤다.

## 4. 결함 묶음 (X2) — 바뀐 것과 증거 수준

증거 수준: U=unit/fixture · S=raw 스크립트 샌드박스(POSIX sh) · W=WSL ansible 2.20.7 · R=Runner ansible 2.20.3(임시 Job) · H=Jenkins Harness · M=main Job 매트릭스(lab).

| 묶음 | 항목 | 수준 |
|---|---|---|
| B-RD/RA (Redfish) | RD-F03 IncompleteRead 분류 · D-09 vendor alias(iBMC≠ibm) · RA-F05/F06 복구 인증 예산·간격 · RD-F18 하위 자원 404 아닌 실패 errors[] · RD-F15 FC/FCoE 포트 · D-07 PSU Absent 제외 · RD-FW1 RAID 분류 · RD-UNK/FW2 · 죽은 normalize 4개 삭제 | U (+M 예정) |
| B-E (ESXi) | ESXI-03 config_info `esxi_hostname` + DNS 오류 조건(dns_info 만) · ESXI-21 자격 변수 통일 · D-01 vCenter 거부 · ESXI-09 TB/GB/MB · ESXI-12 컨트롤러 종류 · ESXI-13 시도 수 · D-03 defaultPolicy | U · R(argspec) (+M 예정) |
| B-W (Windows) | WIN-02 fec0 · WIN-11/12 IPv6 게이트웨이 · WIN-DM 드라이버 전수 · D-02 VBS · D-03 ActiveStore · WIN-13 CIM 격리 · WIN-21 부분합 금지 · D-08 디스크 크기 | U(실제 powershell.exe 5.1) (+M 예정) |
| B-L (Linux) | LX-F08 기본 경로 토큰 파싱(ECMP·nhid·IPv6) · LX-F02 'None' 게이트웨이 · LX-F10 lspci 표식 · LX-F01 비특권/특권 분리 · D-03 유효 정책 · LX-F04 multipath · LX-F06 캐시 인스턴스 · LX-F12 자리표시자 집합 · D-10 JEDEC bank | U · S · W · **R**(LX-F02: Runner01/03 에서 'None' 재현) (+M 예정) |
| B-J 후속 | FL-F01b classify 에 연결 끊김 근거 전달 | H 예정(X2 CI) |

바꾸지 않은 것: envelope 13 필드 · 섹션 · field_dictionary 의미 · failure_code/stage 집합 · §8 운영 정책 · 계정 쓰기(HOLD).

## 5. 검증 (X2 working tree, 이 PC)

| 구분 | 결과 |
|---|---|
| 정적 | YAML 40 파일 parse OK · Python compile OK · verify_vendor_boundary 통과 · verify_harness_consistency 통과 · verify_docs_references(이 문서 생성 뒤) |
| 채널별 단위 | Redfish 감사 15 · ESXi 묶음 91 · Windows 325+98(실제 PowerShell) · Linux 388+45 · JEDEC/드리프트/메모리 104 · 식별자 자리표시자 묶음 171 · Jenkinsfile/Harness 157 |
| 전체 suite(unit · e2e · regression) | 실행 중 — 결과는 §7 에 추가 |
| lab 읽기 전용 probe(Runner) | 실행 중(`se-audit-labprobe`) — Linux 7 · Windows 2 · ESXi 3 |

## 6. 삭제 · 정리

- 삭제(사용자 결정): `REDFISH_BIOS_GATHERING_PLAN_MODE_PACKAGE_00-11_2026-09-14/`(미추적 320K).
- 삭제(참조 0 확인): `redfish-gather/tasks/normalize_{system,network,storage}.yml` · `esxi-gather/tasks/normalize_sections.yml` · `_endpoint_with_fallback`.
- 유지(사용자 결정): `tests/reference` 전부.
- 임시 Jenkins 자원(D-12): `se-audit-parity` · `se-audit-negative-control` · `se-audit-labprobe` Job, 브랜치 `audit/negative-control` — 감사 끝에 삭제하고 확인한다.

## 7. 결과 추가 (진행 중)

- [ ] 전체 suite 결과
- [ ] lab probe 결과(P4 · P8 · P11-lite)
- [ ] X2 push · WSL ci_gate · 매트릭스 · strict compare · CI
- [ ] 승격 · canary · 명부 전수
- [ ] 성능 전후(P4)
- [ ] 정리 완료 확인
