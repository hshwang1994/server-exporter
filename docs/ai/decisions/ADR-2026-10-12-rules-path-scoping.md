# ADR-2026-10-12 — 경로별 규칙은 `paths` frontmatter 로 로드 범위를 지정하고, 코드 · 파일에서 바로 읽을 수 있는 서술은 CLAUDE.md · 규칙에서 뺀다

- 상태: Accepted (2026-10-12 — Claude Code `/doctor` 점검(2026-10-11)의 제안을 사용자가 "모두 정리" 로 승인했고, 서술 정정 항목은 작성자 결정)
- 관련: CLAUDE.md §13 · §17 · rule 00 · rule 70 R4/R8 · CONVENTION_DRIFT DRIFT-025 · `.claude/policy/surface-counts.yaml`(카운트 불변)

## 컨텍스트 (Why)

- 모든 세션이 `CLAUDE.md` 와 `.claude/rules/*.md` 28개를 통째로 읽었다 — 140,463자(est. 35.1k 토큰, 2026-10-11 측정). 그중 15개 규칙은 특정 경로(수집 코드 · adapter · schema ·
  시험 · Jenkinsfile · 문서 다이어그램)를 다룰 때만 뜻이 있다.
- 규칙 본문에 코드 · 파일에서 그대로 읽을 수 있는 복제가 섞여 있었다: CLAUDE.md §3 "주요 위치" 와 §18 의 docs 갈래 목록(정본 `docs/README.md`), rule 00 의 모듈 트리,
  rule 11 · 12 · 21 · 22 · 50 의 "현재 관찰된 현실", rule 20 의 envelope JSON 예시(정본 `common/tasks/normalize/build_output.yml`), rule 40 의 시험 분류 표와 pytest 명령 예시,
  rule 50 의 alias 표(정본 `common/vars/vendor_aliases.yml`). 복제는 정본이 바뀌면 그 자리에서 틀린다(CLAUDE.md §17).
- 설치된 Claude Code(2.1.296)는 규칙 파일의 `paths:` frontmatter 를 지원한다 — 그 glob 의 파일을 읽거나 고칠 때만 규칙을 로드한다(이 저장소에서 2026-10-12 확인:
  docs 아래 md 를 읽자 rule 41 만 추가로 로드됐다).
- 같은 점검에서 깨진 frontmatter 2건을 찾았다. `.claude/skills/add-new-vendor/SKILL.md` 는 따옴표 없는 description 이 YAML 파싱에 실패해 이름 · 설명이 폴더명 · 본문 첫 줄로
  대체되고 있었고, `.claude/commands/ultracode-human-docs-and-file-audit.md` 는 종결 `---` 자리에 `-` 80개가 있어 스킬 목록에 나타나지 않았다.
- 규칙 본문이 코드와 다른 곳도 있었다(DRIFT-025): 2026-10-03 에 삭제된 Jenkins `Validate Schema` · `Callback` stage 로 게이트 위치를 설명한 규칙 6개, field_dictionary 를
  고정 개수로 적은 rule 23, Redfish 표준 계정 vault 를 loc×vendor 경로로 적은 rule 30.

## 결정 (What)

1. 다음 15개 규칙 머리에 `paths:` 를 둔다(정확한 glob 은 각 규칙 파일 머리가 정본). 나머지 13개(00 · 23 · 24 · 25 · 28 · 70 · 90 · 91 · 92 · 93 · 95 · 96 · 97)와 CLAUDE.md 는
   모든 세션에서 로드한다.

   | rule | 로드 범위 |
   |---|---|
   | 10 gather-core | 3채널 gather 디렉터리, common/library · tasks · vars, filter_plugins, lookup_plugins, module_utils |
   | 11 gather-output-boundary | 3채널 gather 디렉터리, common/tasks/normalize |
   | 12 adapter-vendor-boundary | adapters, common, 3채널 gather 디렉터리 |
   | 13 output-schema-fields | schema, common/tasks/normalize, callback_plugins, docs/contract |
   | 20 output-json-callback | callback_plugins, common/tasks/normalize, 3채널 site.yml |
   | 21 output-baseline-fixtures | tests/fixtures, schema/baseline_v1, tests/evidence |
   | 22 fragment-philosophy | 3채널 gather 디렉터리, common/tasks/normalize, common/library |
   | 26 multi-session-guide | docs/ai/tickets |
   | 27 precheck-guard-first | common/library, common/tasks/precheck, 3채널 gather 디렉터리, ansible.cfg |
   | 30 integration-redfish-vmware-os | 3채널 gather 디렉터리 |
   | 31 integration-callback | Jenkinsfile_portal, Jenkinsfile_portal_Byid, scripts/jenkins |
   | 40 qa-pytest-baseline | tests, schema/baseline_v1 |
   | 41 mermaid-visualization | docs · .claude/skills · .claude/agents · prototypes 아래 md |
   | 50 vendor-adapter-policy | adapters, vault, common/vars/vendor_aliases.yml, .claude/ai-context/vendors, .claude/policy/vendor-boundary-map.yaml |
   | 80 ci-jenkins-policy | Jenkinsfile 전부, scripts/jenkins, 수집 · venv · 상태 · add-on 스크립트, scripts/ai/ci_gate.sh, scripts/ai/prodgen, ansible.cfg, jenkins, docs/operate, tests/jenkins |

2. 위에 적은 복제 서술을 뺀다. 남기는 것은 정본 포인터 한 줄이다(rule 20 "정본 = `common/tasks/normalize/build_output.yml`", rule 40 R1 · R3 포인터, CLAUDE.md §18 "문서 지도는
   `docs/README.md`"). Default / Allowed / Forbidden 절은 바꾸지 않았다.
3. 깨진 frontmatter 2건을 고치고, DRIFT-025 를 코드대로 정정한다 — 수집 Job 의 현 4단계(`입력 확인` / `실행 위치 확인` / `서버 정보 수집` / `결과 확인 및 전송`), schema 정합 게이트는
   CI gate(`scripts/ai/ci_gate.sh`), envelope 모양은 결과 처리의 shape gate(`scripts/finalize_gather_output.py`), Redfish 표준 계정은 전역 `vault/common/redfish/standard.yml`.
4. 규칙 수 · 스킬 수 · 표면 카운트는 바꾸지 않는다(rule 70 R8 트리거 2 해당 없음).

## 결과 (Impact)

- 모든 세션이 읽는 양: 140,463자(est. 35.1k 토큰) → 66,821자(est. 16.7k 토큰, 2026-10-12 측정). 범위 지정 규칙은 그 경로를 다룰 때 추가로 로드된다.
- 제품 코드 · runtime tree 변화 0 — `.claude/` · `CLAUDE.md` · `docs/ai/` 는 production 생성 대상이 아니다. production 승격 없음, P12 `410317a7` 그대로.
- 되돌리기: 규칙 머리의 `---` 블록을 지우면 다시 항상 로드된다. 뺀 서술은 이 커밋의 `git show` 에 있다.
- 한계: 규칙이 다루는 경로의 파일을 열지 않은 대화(예: Jenkinsfile 을 열지 않고 Jenkins 정책만 묻는 경우)에서는 그 규칙이 로드되지 않는다. 사용자가 규칙을 지목하거나 해당 파일을
  열면 로드된다.

## 대안 비교 (Considered)

- *그대로 둔다* — 거부. 매 세션 est. 18k 토큰을 경로와 무관한 규칙에 쓰고, 복제 서술이 코드와 어긋나는 일이 반복됐다(DRIFT-024 · DRIFT-025).
- *규칙을 CLAUDE.md 하나로 합친다* — 거부. 더 커지고 경로 범위를 줄 수 없다.
- *복제 서술을 "참고용" 으로 남긴다* — 거부. rule 00 "세어 놓은 수는 적지 않는다" 와 CLAUDE.md §17 에 어긋나고, 정본이 바뀔 때마다 같이 고쳐야 한다.
- *커뮤니케이션 · 완료 판정 · 커밋 규칙(23 · 24 · 90 등)도 범위 지정* — 거부. 어떤 작업에도 적용되는 규칙이다.
