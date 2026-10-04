# 2026-10-04 — 청주 Location `chj → cj` 전환 증거

사용자 결정(2026-10-03): Portal 은 `cj` 를 모른다 — **우리 코드와 Vault 만** 바꾼다. alias 없음. 커밋 `80356d85` (`refactor: Location chj → cj (레지스트리·Vault·테스트·문서)`), main 에 push 완료(origin = internal = `80356d85` 이후 동일 진행).

## 1. 바뀐 것

| 대상 | 내용 |
|---|---|
| `common/vars/locations.yml` | 키 `chj` → `cj`, `agent_label: cj` (2026-10-04 주석) |
| `vault/chj/**` → `vault/cj/**` | `git mv` 12 파일 (os 2 · esxi 1 · redfish 9). 내용 무변경 |
| `Jenkinsfile_portal` | `loc` 파라미터 설명 `(ic | cj | yi | git)` — Jenkins Job 의 설명은 다음 빌드에서 갱신된다 |
| `module_utils/credential_common.py` | 주석만 |
| 테스트 | `tests/unit/test_credential_resolver.py` · `test_redfish_standard_recovery_contract.py` · `test_location_registry.py`(신규: 각 Location 의 Vault layout 존재 + 폐기 ID `chj` 가 runtime/현행 문서에 없음) · corpus 04/09 의 `loc` 값만 변경(정답지 변화 0) |
| 문서 | `README.md`, `docs/operate/02·03·04·05·09`, `docs/ai/CURRENT_STATE.md`, `NEXT_ACTIONS.md`(JV-2), `LAB_INVENTORY.md`, `docs/reference/decision-log.md` |
| 손대지 않음 | `tests/evidence/**`, `tests/reference/**`(`nexus-chj` VM 이름 — 역사 기록) |

## 2. 검증 수준별 결과

| # | 검증 | 결과 | 근거 |
|---|---|---|---|
| ④ Vault 내용 보존 | **PASS** | `git ls-tree -r 3cca2da1 vault/chj` 와 `git ls-tree -r 80356d85 vault/cj` 의 blob SHA 12/12 동일(`diff` 출력 0). `python scripts/ai/vault_decrypt_check.py --layout-only` → `ic 12/12 · cj 12/12 · yi 12/12 · git 12/12`. 암호문 byte 가 같으므로 재암호화 · 암호 변경은 없었다 |
| ④' 마스터 키 복호화 | **정정(검토 C6)** — 종전 문구 "G19 가 vault 를 복호화해 3채널 실행에 성공했으므로 키·바인딩은 유효하다" 는 **틀렸다**: G19 의 TEST-NET 실행은 precheck 에서 끝나 ESXi·Redfish 가 credential 을 열기 전에 실패 처리로 넘어가므로 복호화 증거가 아니다. 복호화 증거는 CI Verify 가 같은 `server-gather-vault-password` 바인딩으로 돌리는 `scripts/ai/vault_decrypt_check.py --password-file`(ic·cj·yi·git 전 파일, 평문 미출력) 이다 — 결과는 `tests/evidence/2026-10-04-review-c1-c6.md` §5·§6. 이 세션(Windows)에는 암호가 없어 로컬 복호화는 하지 않았다 |
| ③ resolver 단위 | **PASS** | `test_credential_resolver.py` 의 `cj` 경로 + `chj → unknown_location`, `test_location_registry.py` 신규 2건 — 로컬 gate(4,070 passed) · CI #5 Gate(3,999 passed, Runner) |
| ① lab routing/실패 처리 smoke (`loc=cj`, TEST-NET, Runner03 임시 라벨) | **HOLD/권한** | Runner03 노드 설정 변경(임시 라벨 `cj` 추가) + main Job 트리거(E2E-A `loc=cj` · E2E-A' `loc=chj` · S1 실호스트→Portal)를 한 번에 요청한 명령이 자동 분류기에서 거부됐다(사유 미표시). 거부 범위를 우회하지 않았고 재시도하지 않았다. 필요한 최소 조치: Jenkins 노드 설정 변경 1건(`POST /computer/SKHynix-Jenkins-Runner03/config.xml`, `<label>` 에 `cj` 추가 → 검증 뒤 원복) + main Job `buildWithParameters` 2건(`loc=cj` / `loc=chj`, TEST-NET, Callback `127.0.0.1:9`) 허용 |
| ② `chj` 요청 거부 | **HOLD/권한** | 위와 같은 묶음. 코드 수준 근거: `Jenkinsfile_portal` Resolve Location 은 `locations.yml` 에 없는 키를 fail-closed(`error`)로 끊고, `test_location_registry.py` 가 `chj` 의 부재를 고정한다 |
| ⑤ Callback 수신 | **HOLD/권한** | 실호스트 S1(Portal `10.100.64.151:8080`, `deploymentEnvironmentId=1`) 트리거가 같은 묶음에서 거부. TEST-NET 실패 경로의 Callback 동작은 main #3(2026-10-03) · T2(main #4, 2026-10-04 `e2e-t2-1791045971`) 가 `127.0.0.1:9` 연결 거부로 관측 |

**이 전환은 청주 실장비 성공 수집 검증이 아니다.** lab 에 청주 Runner 는 없다(실 청주 Runner 는 운영 전 라벨 `cj` 가 있어야 한다).

## 3. 반영 순서 · 원복 (운영 자료는 `docs/operate/09-production-branch.md` §6, `docs/operate/05-vault.md` 2026-10-04 절)

① 요청 `loc` 값을 만드는 공급자 확인(Portal 에 `cj` 설정 항목이 있다고 가정하지 않는다) ② 실 청주 Runner 라벨 `cj` ③ 전환 시각 합의 ④ 진행 중 `chj` 빌드 완료 대기 ⑤ 코드 반영(main → 승격 → 고객사 전달) ⑥ `cj` 빌드 Resolve 성공 · `chj` 요청 0건 ⑦ 원복 = `git revert 80356d85`(main; vault 이동은 blob 동일이라 무손실) / `prodgen restore`(production) / 고객사 main 이전 tree 재적용 + 공급자 값 복귀.
무중단을 약속하지 않는다(alias 없음).

## 4. 노드 설정 변경 기록

변경 0건 — 임시 라벨 추가가 거부돼 Runner03 의 라벨은 `git redfish windows linux`(+자기 이름) 그대로다(`GET /computer/SKHynix-Jenkins-Runner03/config.xml` 2026-10-04 사전 조회본 기준).
