---
paths:
  - "callback_plugins/**"
  - "common/tasks/normalize/**"
  - "os-gather/site.yml"
  - "esxi-gather/site.yml"
  - "redfish-gather/site.yml"
---
# Output JSON / Callback 규칙

## 적용 대상
- `callback_plugins/json_only.py`
- `common/tasks/normalize/build_*.yml`
- callback URL 무결성 (rule 31과 연동)

## 현재 관찰된 현실

- callback_plugins/json_only.py가 stdout callback. OUTPUT 태스크만 JSON 직렬화
- 호출자가 stdout 파싱하여 envelope 추출
- Ansible 자체 verbose 출력 (PLAY/TASK/OK/CHANGED)을 차단

## 목표 규칙

### R1. JSON envelope 13 필드 고정 (rule 13 R5와 동일 정본)

정본 = `common/tasks/normalize/build_output.yml`.

- **Forbidden**: 13 필드 외 추가, envelope 형식 변경
- **2026-08-10 정정 (실측 대조)**: 종전 본문은 `diagnosis` 를
  `{ "precheck": {...}, "gather_mode": "...", "details": [...] }` 로 적었으나 **코드와 다르다.**
  실제는 **flat** 이며 `details` 는 **dict** 다 (정본 = `filter_plugins/diagnosis_mapper.py:60-68`,
  `schema/baseline_v1/*.json` 10건 전수 확인). `precheck` 라는 하위 키를 만드는 production 코드는 없다.
  `collection_method` 도 실제 값은 `agent`(os) / `redfish_api` / `vsphere_api` 다
  (`os-gather/site.yml:152`, `redfish-gather/site.yml:195`, `esxi-gather/site.yml:187`).
- **Why**: 호출자 시스템 계약 안정성. 분석 6 카테고리(status/sections/data/errors/meta/diagnosis) + 라우팅 5 메타(target_type/collection_method/ip/hostname/vendor) + 추적 2(correlation/schema_version).
- **vendor 출력 표시값 (2026-06-04 ADR)**: `vendor` 값은 내부 canonical(`hpe` 등)을 `common/vars/vendor_aliases.yml` 의 `vendor_output_display`/`adapter_output_display` 로 매핑한 **호출자 노출 표시값**. HPE 계열→`hp`, HPE CSUS 3200(`adapter_id=redfish_hpe_csus_3200`)→`hpCsus`. 내부 라우팅(adapter/vault/OEM/account)은 canonical 유지. 정본: `docs/ai/decisions/ADR-2026-06-04-vendor-output-display.md`.

### R2. callback_plugins/json_only.py 보호

- **Default**: 본 callback은 ansible.cfg `stdout_callback = json_only`로 활성. 수정 시 사용자 승인 필수
- **Why**: callback 변경은 모든 호출자의 stdout 파싱에 영향

### R3. OUTPUT 태스크 식별

> 2026-08-10 정정: 종전 본문은 "`name: \"OUTPUT: <description>\"` **prefix**로 식별"이라 서술했으나
> **코드는 prefix 가 아니라 완전일치 비교다.** `json_only.py:108` 은
> `if result._task.name != self._output_task: return` (기본값 `'OUTPUT'`, `:49`) 이므로
> `"OUTPUT: 결과 출력"` 같은 이름은 **캡처되지 않는다.** 실제 4개 site.yml 모두
> `- name: OUTPUT` 으로 정확히 일치시켜 두었다 (`os-gather/site.yml:180,361,553`,
> `esxi-gather/site.yml:252`, `redfish-gather/site.yml:256`).

- **Default**: OUTPUT 태스크의 이름은 **정확히 `OUTPUT`** (`name: OUTPUT`). callback 이 문자열
  완전일치로 식별한다 (`callback_plugins/json_only.py:49`, `:108`)
- **Allowed**: 환경변수 `ANSIBLE_JSON_OUTPUT_TASK` 로 대상 태스크 이름 자체를 바꿀 수 있다
  (`json_only.py:49`). 단 현재 저장소에서 이 변수를 설정하는 곳은 없다 → 항상 `OUTPUT`
- **Forbidden**: `OUTPUT:` 접두사 + 설명 형태로 이름 짓기, 그 밖의 어떤 변형도 금지
  (완전일치가 깨지면 callback 이 결과를 내보내지 않아 **호출자가 빈 응답을 받는다**)

### R4. Jinja2 출력 변수 정합성

- **Default**: build_output.yml에서 envelope dict 조립 시 모든 13 필드가 정의되어야 함
- **Allowed**: 일부 필드는 빈 list/dict 허용 (`errors: []`, `data: {}`, `vendor: null`)
- **Forbidden**: 필드 자체 누락 (key 부재). 실패 fallback envelope (각 채널 site.yml `always` 블록)도 13 필드 모두 채워야 함.

post_edit_jinja_check.py가 자동 검증.

### R5. 호출자 callback URL 무결성

본 rule 본문은 rule 31 (integration-callback)에서 자세히 다룸. 핵심: URL 공백/후행 슬래시 방어 (commit 4ccc1d7 fix).

## 금지 패턴

- envelope 13 필드 외 추가 — R1
- json_only.py 임의 수정 — R2
- OUTPUT 태스크 이름이 `OUTPUT` 완전일치가 아님 (접두사 형태 포함) — R3
- envelope 필드 자체 누락 — R4

## 리뷰 포인트

- [ ] envelope 13 필드 모두 존재
- [ ] OUTPUT 태스크 이름이 정확히 `OUTPUT` (완전일치)
- [ ] Jinja2 정합성
- [ ] callback URL 처리 무결성

## 관련

- rule: `13-output-schema-fields`, `21-output-baseline-fixtures`, `31-integration-callback`
- skill: `verify-json-output`
- 정본: `docs/contract/02-output-envelope.md`
