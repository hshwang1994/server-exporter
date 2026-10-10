# ADR-2026-10-11 — adapter YAML 에서 코드가 읽지 않는 절을 제거하고 설계 메모를 `vendor_notes.design_hints` 로 옮긴다

- 상태: Accepted (2026-10-11, 작성자 결정 D-17 — 사용자 "모두 진행" 지시로 보류 항목 집행)
- 관련: `ADR-2026-10-10-adapter-required-keys.md`(서술 정정) · CONVENTION_DRIFT DRIFT-024 · rule 12 R4 · `docs/develop/03-adapter-system.md` · `docs/operate/05-vault.md` 6.6절

## 컨텍스트 (Why)

- 2026-10-10 감사에서 adapter 43개의 `collect` · `normalize` · `credentials` · `graceful_degradation` · `auth` · `diagnosis` · `channel` 절과 `capabilities` 의
  `sections_supported` 이외 하위 값을 읽는 코드가 저장소에 없음을 확인했다(로더는 `match` · `adapter_id` · `priority` · `generic`, 플레이북은
  `capabilities.sections_supported` · `vendor_notes.manager_layout` · `version` 만 읽는다). 전날 ADR 은 서술만 고치고 절은 "별도 결정" 으로 남겼다.
- 그 절들은 두 종류였다: (1) site.yml 에 고정된 경로의 복제(`*_tasks`, `tasks_dir`) 와 vault 의 복제(`credentials.profile` · `recovery_accounts`), (2) 설계 의도 메모
  (`collect.strategy`, `graceful_degradation.*`, `auth.preferred`, `diagnosis.*`, `capabilities.power_subsystem` 등). (1) 은 정본이 다른 곳에 있어 어긋날 수만 있고
  (`fallback_profiles: []` 처럼 존재하지 않는 기능을 암시), (2) 는 사실이 아닌 동작("critical_sections 가 실패하면 abort") 을 읽는 사람에게 약속한다.
- `tests/unit/test_adapter_vault_label_consistency.py` 는 adapter 사본과 vault label 을 맞추는 시험이었다 — 런타임 계약(vault 의 `role: recovery`)은 credential resolver 시험이 본다.

## 결정 (What)

1. adapter 최상위 절은 `adapter_id` · `priority` · `match` · `capabilities`(`sections_supported` 만) · `generic` · `vendor_notes` · `metadata` 로 한정한다.
2. 경로 · vault 복제(1)는 삭제한다. 설계 메모(2)는 내용을 잃지 않도록 `vendor_notes.design_hints` 로 옮기고 "코드가 읽지 않는다" 를 주석으로 적는다(§9 "고유 내용은 이동").
3. `test_adapter_vault_label_consistency.py` 를 삭제한다. 복구 계정 정본은 vault `accounts[*].role/label` 하나다.
4. 문서 · 규칙 · skill 의 adapter 예시와 "필수 키" 서술을 이 모양으로 맞춘다.

## 결과 (Impact)

- runtime tree 가 바뀐다(adapters 는 production 생성 대상) → 새 후보(X6)로 main Job 매트릭스 · strict compare · CI · 승격을 다시 돈다. 수집 동작은 바뀌지 않는다
  (읽는 값이 모두 그대로) — 매트릭스 대조에서 차이 0 이어야 한다.
- 새 vendor 추가 시 적을 것이 줄고, adapter 가 약속하지 않는 동작을 문서처럼 들고 다니지 않는다.

## 대안 비교 (Considered)

- *그대로 두고 "기록용" 이라 표시만* — 거부. 존재하지 않는 동작(`on_auth_fail: abort`, `fallback_profiles`)을 계속 약속한다.
- *모두 삭제(메모 포함)* — 거부. 설계 의도(전략 · generation 별 보조 능력)는 다음 작업자에게 쓸모가 있어 `vendor_notes` 로 옮겼다.
- *코드가 그 절을 읽게 구현* — 거부. 수집 · 정규화 경로는 site.yml 고정이 맞고(rule 12 R3 "site.yml 수정 금지" 와 짝), 복구 계정은 vault 가 정본이다.
