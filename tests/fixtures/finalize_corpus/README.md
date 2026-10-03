# finalize corpus — Layer A / Layer B 동치 검증 입력과 정답지

> **이 폴더는** 수집 결과 마무리(finalization — 접수한 대상 1개마다 envelope 1개를 만드는 단계)의 두 구현이 같은 규칙으로
> 동작하는지 확인하는 corpus 다. 작성일 2026-10-03 (Plan Phase 6 §6-4 "Python/Groovy 동치 검증").
>
> - Layer A: `scripts/finalize_gather_output.py` (Python, Gather stage 의 post{always} 에서 Agent 위에서 돈다)
> - Layer B: `seReconcileRaw` (Groovy, `Jenkinsfile_portal` 의 post{always} finalizer — Layer A 결과가 없을 때의 최소 경로.
>   같은 함수의 글자까지 같은 사본이 `scripts/jenkins/se_finalize.groovy` 에 있다)
>
> **출처**: 전부 합성(synthetic) 데이터다. 실장비 응답이 아니며 실제 사이트 · 호스트 · 계정 정보가 없다. 주소는 RFC 5737 문서용
> 대역(192.0.2.0/24 · 198.51.100.0/24 · 203.0.113.0/24), 호스트 이름 · 시리얼 · UUID · 펌웨어 값은 지어낸 것이다.
> 정답지는 사람이 쓰지 않았다 — **Layer A 를 실제로 실행한 결과**다 (oracle = Layer A).

## 1. 구조

```text
tests/fixtures/finalize_corpus/<case>/
├── gather_manifest.json      # Jenkins Validate 가 만드는 접수 manifest {schema, build, channel, request, ips[]}   [입력 · 필수]
├── gather_output.json        # json_only 가 OUTPUT 태스크마다 append 한 envelope JSONL                            [입력 · 선택]
├── gather_checkpoint.jsonl   # json_only 가 CHECKPOINT(Add-on 전 조립본) 마다 append 한 envelope JSONL              [입력 · 선택]
├── gather_progress.jsonl     # host 별 전이 이벤트 JSONL (Layer A 만 읽는다)                                          [입력 · 선택]
├── gather_rc.txt             # ansible-playbook(또는 timeout) rc                                                    [입력 · 선택]
├── outcome.txt               # Jenkinsfile 이 넘기는 --outcome (completed | timeout | timeout_killed | prep_failed …) [입력 · 필수]
├── expected_final.jsonl      # Layer A 의 gather_final.jsonl — 접수 순서대로 host 당 1줄                               [정답지]
├── expected_report.json      # Layer A 의 gather_finalize_report.json                                              [정답지]
└── expected_origins.json     # host 별 origin: "output" | "checkpoint" | "synthetic" (Groovy 쪽이 비교 규칙을 고르는 데 쓴다) [정답지]
```

## 2. case 목록

| case | 채널 | 시나리오 | Layer A 결과 (정답지) | Layer B 와 다른 점 |
|---|---|---|---|---|
| `01_normal` | os | host 3개 모두 OUTPUT, 줄 순서가 접수 순서와 다름 | output 3, exit 0, 접수 순서로 정렬 | 없음 |
| `02_dup_identical` | os | 같은 ip 의 OUTPUT 줄 2개가 글자까지 같음 + 키 순서가 다른 줄 1개 | output 2, conflicts 0, exit 0 (원문 그대로 통과) | 없음 |
| `03_dup_conflict` | os | 같은 ip 의 OUTPUT 줄 2개가 다름 (success → partial) | 뒤 줄 채택, conflicts 1 (`lines [1,3]`, `chosen 3`), exit 2 | conflicts 항목 shape 만 다름 (`ip`/`chosen` 은 같다) |
| `04_truncated_tail` | esxi | 마지막 줄이 개행 없이 잘림, 그 host 는 auth_proven 만 있음 | `truncated_tail` 1, host 는 합성 GATHER_FAILED(auth_success true), exit 2 | Layer B 는 'not JSON' dropped + OUTPUT_BUILD_FAILED 합성 |
| `05_corrupt_middle` | os | 가운데 줄이 깨진 JSON, 그 host 는 다른 증거 없음 | `corrupt_lines` 1, host 는 합성 OUTPUT_BUILD_FAILED, exit 2 | 분류 이름만 다름 (dropped) |
| `06_checkpoint_addon_interrupted` | os | OUTPUT 없는 host 에 CHECKPOINT 있음, progress 에 addon_started 만 | checkpoint 복원 + `addon` 오류 1건, exit 0 | Layer B 는 `gather` + emitFailed 오류 1건 |
| `07_checkpoint_addon_done` | redfish | CHECKPOINT 있음, addon_started · addon_done 둘 다 | checkpoint 복원 + `gather` EMIT_FAILED 오류 1건, exit 0 | 오류 message 같음, detail 만 다름 |
| `08_progress_precheck_failed` | os | precheck 실패 진단(TARGET_UNREACHABLE)만 관측, rc 파일 없음 | 합성, precheck 진단 보존(`reachable` 단계), exit 0 | Layer B 는 OUTPUT_BUILD_FAILED 합성 |
| `09_auth_proven_then_lost` | esxi | 인증된 태스크 성공 뒤 lost | 합성 GATHER_FAILED · `gather_connection_lost` 문장 · auth_success true, exit 0 | Layer B 는 OUTPUT_BUILD_FAILED 합성 |
| `10_nothing_synthetic` | redfish | 어떤 파일도 없음 (prep_failed, rc 90) | host 2개 모두 합성 OUTPUT_BUILD_FAILED, `bmc_ip`=ip, exit 0 | 문장 · 뼈대 같음 (`details.finalizer` 만 다름) |
| `11_wrong_target_type_dropped` | os | OUTPUT 줄의 target_type 이 redfish | dropped 1, host 는 합성 OUTPUT_BUILD_FAILED, exit 2 | 없음 (둘 다 drop) |
| `12_foreign_ip_dropped` | os | manifest 에 없는 ip 의 OUTPUT 줄 + 다른 host 는 인증 전 lost | dropped 1, 합성 AUTH_PROBE_FAILED(`auth_unconfirmed`, loc 치환), exit 2 | Layer B 는 OUTPUT_BUILD_FAILED 합성 |
| `13_mixed_blank_lines` | redfish | 빈 줄 · 공백 줄 · 12키 줄 · 동일 중복 · 외부 ip · 충돌 · 외부 ip CHECKPOINT · add-on 중단 · precheck 실패(TCP_CONNECTION_REFUSED) · 아무것도 없는 host | output 2 · checkpoint 1 · synthetic 2, dropped 3, conflicts 1, exit 2 | 위 항목들의 합 |
| `14_lost_without_auth` | os | 인증 전 lost — Vault 계정 있음 vs 계정 0개(`empty_accounts`) | 합성 AUTH_PROBE_FAILED 2건 (`auth_unconfirmed` / `loc_vault_no_account`), exit 0 | Layer B 는 OUTPUT_BUILD_FAILED 합성 |

줄 번호(`line`)는 두 Layer 모두 빈 줄 · 공백 줄을 포함해 1부터 센다 — `13_mixed_blank_lines` 가 이 정렬을 확인한다.

## 3. 두 Layer 가 같아야 하는 것 / 달라도 되는 것

같아야 하는 것 (= 비교 규칙. Groovy 쪽 `seCorpusCompare` 와 Python 쪽 검사기가 이 기준을 쓴다):

| origin | 비교 |
|---|---|
| 전체 | 줄 수 == 접수 ip 수, ip 순서 == manifest 순서, envelope 13 키 순서, `by_origin` · `kept` · `filled`, dropped 의 `file:line` 집합 (Layer A 의 `dropped` + `corrupt_lines` + `truncated_tail`), conflicts 의 `ip:chosen` 집합 |
| `output` | 줄 **원문** 동일 — 두 Layer 모두 OUTPUT 줄을 재직렬화하지 않는다 |
| `checkpoint` | `errors` 를 뺀 12 필드 동일 + 기존 `errors` 동일. 덧붙인 마지막 1건만 Layer 별 사유 (Layer B 는 `gather` + `emitFailed`) |
| `synthetic` | 뼈대 11 필드(`schema_version` … `data`) 동일, `sections` 키 순서 동일. Layer A 도 OUTPUT_BUILD_FAILED 이면 `failure_reason` · `errors[0].section` 까지 동일 |

달라도 되는 것 (설계상 — `Jenkinsfile_portal` 주석 "progress 이벤트 기반 분기는 Layer A 몫"):

- 합성 봉투의 `diagnosis` 세분: Layer A 는 progress 로 precheck 보존 / GATHER_FAILED / AUTH_PROBE_FAILED 를 가르고, Layer B 는 항상 OUTPUT_BUILD_FAILED.
- checkpoint 복원 시 덧붙이는 오류 1건의 원인(`addon` vs `gather`)과 detail 문구.
- `details.finalizer` (`layer_a` / `layer_b`), 손상 줄의 분류 이름(`truncated_tail`/`corrupt_lines` vs `dropped: not JSON`), dropped · conflicts 항목의 shape.
- shape gate 의 엄격함: Layer A 는 `schema_version` · `status` · `sections` · `diagnosis` 모양까지 보고, Layer B 는 13 키 집합 · `target_type` · ip 만 본다.
  corpus 는 두 Layer 가 **같이** 떨어뜨리는 줄(12키 · target_type 불일치 · 외부 ip · 깨진 JSON)만 넣었다.
- 직렬화 표기: Groovy `JsonOutput` 은 비ASCII 를 `\uXXXX` 로, Python 은 그대로 쓴다. 값은 같으므로 양쪽을 같은 파서로 읽어 비교한다.

## 4. 어떻게 쓰이나

| 어디서 | 무엇을 |
|---|---|
| `python tests/scripts/finalize_corpus_check.py` | Layer A 를 case 마다 실제로 실행해 정답지와 대조 (exit 0 일치 / 1 불일치 / 3 도구 실패) |
| `tests/unit/test_finalize_corpus.py` | 위 검사기 호출 + 불변식 + 변조 감지 + `--regenerate` 멱등 |
| `scripts/ai/ci_gate.sh` | "finalize corpus" 단계로 검사기 실행 (`CI_GATE_SKIP_CORPUS=1` 로 건너뛰면 PARTIAL) |
| `Jenkinsfile_ci` 'Finalize Corpus' | Python 쪽 검사기 + Groovy 쪽: `load 'scripts/jenkins/se_finalize.groovy'` 뒤 case 마다 `seReconcileRaw` 를 돌려 같은 정답지와 대조 |

## 5. 재생성 (입력을 바꾸거나 case 를 추가했을 때)

1. 새 case 디렉터리에 입력 파일을 둔다 (`gather_manifest.json` · `outcome.txt` 필수). 기존 case 를 복사해 고치는 것이 가장 안전하다.
2. `python tests/scripts/finalize_corpus_check.py --regenerate` — Layer A 를 실행해 `expected_*` 세 파일을 다시 쓴다 (LF).
3. **`git diff` 로 정답지 변화를 반드시 읽는다.** 정답지가 바뀌었다면 그것은 Layer A 의 동작이 바뀐 것이다 — 의도한 변경인지 확인하고
   같은 변경이 Layer B(`Jenkinsfile_portal` · `scripts/jenkins/se_finalize.groovy`)에도 필요한지 본다.
4. 이 README 의 case 표에 한 줄을 더한다 (`tests/unit/test_finalize_corpus.py` 가 case 이름이 표에 있는지 확인한다).
5. `python -m pytest tests/unit/test_finalize_corpus.py tests/unit/test_jenkinsfile_ci.py tests/unit/test_finalize_gather_output.py -q`

입력 파일을 손으로 고칠 때 — 모든 파일은 LF 로 저장한다. Groovy 쪽은 `expected_origins.json` 의 origin 으로 비교 규칙을 고르므로
정답지 세 파일은 항상 같은 실행에서 나온 것이어야 한다 (검사기가 `by_origin` 합과 origin 분류의 일치를 확인한다).
