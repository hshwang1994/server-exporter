# ADR-2026-10-10 — adapter YAML 의 "필수 4키" 서술을 코드가 읽는 키로 정정

- 상태: Accepted (2026-10-10, 작성자 결정 D-14 — 전체 감사)
- 관련: CONVENTION_DRIFT DRIFT-024 · rule 12 R4 · rule 70 R8 · `docs/develop/03-adapter-system.md` 4절 · `.claude/skills/add-vendor-no-lab/SKILL.md`

## 컨텍스트 (Why)

- rule 12 R4 는 "adapter 는 `match` / `capabilities` / `collect` / `normalize` 4개 키 필수 — 누락 시 adapter_loader 파싱 실패" 라고 적고 있었다.
- 2026-10-10 전체 감사에서 adapter 44개를 기계 검사하니 OS · ESXi adapter 12개에 `normalize` 키가 없는데 운영 중이었다. 코드를 대조했다:
  - 로더(`module_utils/adapter_common.py` · `lookup_plugins/adapter_loader.py`)가 읽는 adapter 키는 `match`(없으면 `{}`) · `adapter_id` · `priority` · `generic` 이고 어떤 키도 강제하지 않는다.
  - 플레이북(`*-gather/site.yml` · `common/tasks/normalize/build_meta.yml`)이 읽는 속성은 `adapter_id` · `capabilities.sections_supported` · (redfish) `vendor_notes.manager_layout` ·
    `version`(meta.adapter_version — 현 adapter 들에는 없어 null)이다.
  - `collect.standard_tasks` · `normalize.standard_tasks` · `credentials.profile` · `graceful_degradation` 을 읽는 코드는 저장소에 없다(grep 0). 수집 · 정규화 task 경로는
    site.yml 에 고정(`include_tasks: tasks/collect_standard.yml` · `tasks/normalize_standard.yml`)이고, 복구 vault 는 감지된 vendor 로 고른다(CLAUDE.md §6).
- 즉 rule 의 Default · Forbidden 절이 동작과 다르다. rule 본문 의미 변경은 ADR 트리거다(rule 70 R8 trigger 1).

## 결정 (What)

1. rule 12 R4 를 코드대로 고친다 — Default: `adapter_id` · `priority` · `match` · `capabilities.sections_supported` (코드가 읽는 키). Allowed: `metadata` · `vendor_notes`
   origin 주석, 그리고 `collect` · `normalize` · `credentials` · `graceful_degradation` 절은 **기록용**. Forbidden: `match` · `capabilities.sections_supported` 누락, 기록용 절을
   "실행된다" 고 적기.
2. 기록용 절은 **지우지 않는다**(이번 감사 범위에서는). 지우면 runtime tree(production 생성 대상)가 바뀌어 새 후보 · 매트릭스가 필요하고, 설계 기록으로서 해가 없다.
   지울지는 별도 결정으로 NEXT_ACTIONS 에 남긴다.
3. 같은 서술을 가진 `docs/develop/03-adapter-system.md` 4절 Step 4 · 예시 주석 · `add-vendor-no-lab` skill 을 함께 고친다.

## 결과 (Impact)

- 수집 동작 · production tree 변화 0 (문서 · 규칙만). 새 vendor 추가자가 "normalize 절이 없으면 파싱 실패" 라는 잘못된 전제로 작업하지 않는다.
- adapter 검사(기계)는 `match` · `capabilities.sections_supported` 존재만 요구하면 된다.

## 대안 비교 (Considered)

- *코드를 rule 에 맞춰 4키를 실제로 강제(로더에서 검증)* — 거부. 12개 OS · ESXi adapter 가 즉시 실패하고, `collect`/`normalize` 절은 어차피 실행 경로를 정하지 않아 강제할 이유가 없다.
- *기록용 절을 adapter 에서 즉시 삭제* — 보류. runtime tree 변경 → 새 후보 · 매트릭스 · 승격 비용. 설계 기록 가치가 있어 별도 결정.
- *rule 만 고치고 문서 · skill 은 두기* — 거부. 세 곳이 서로 다르게 말하면 다음 작업자가 어느 쪽을 믿을지 모른다.
