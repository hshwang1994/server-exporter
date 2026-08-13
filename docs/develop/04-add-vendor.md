# 14. 새 Gather 추가하는 법 — 작업자 절차서

## 누가 읽나

새로운 수집 채널 (예: IPMI / SNMP) 이나 새로운 섹션 (예: thermal / GPU) 을 server-exporter 에 붙이려는 사람.

## 시작 전 체크

다음 3 문서를 먼저 본다. 본문에서 가정하는 개념들이다.

- `docs/06` — 수집 구조 한눈에 (왜 채널이 셋인지)
- `docs/07` — Fragment 정규화 과정 (왜 자기 영역만 만져야 하는지)
- `docs/10` — Adapter 시스템 (벤더 차이를 어떻게 흡수하는지)

이 절차를 그대로 따르면 Fragment 철학을 위반하지 않고, 기존 3 채널에 영향 없이 새 수집 항목을 붙일 수 있다.

## 절차

### 1. 파일 생성

```bash
GATHER=ipmi
mkdir -p ${GATHER}-gather/tasks
cp os-gather/inventory.sh ${GATHER}-gather/inventory.sh
echo -e "---\nansible_user: CHANGE_ME\nansible_password: CHANGE_ME" > vault/${GATHER}.yml
# callback_plugins 복사 불필요 — ansible.cfg가 프로젝트 루트의 단일 사본을 참조
```

### 2. tasks/collect_standard.yml 작성 (수집)

```yaml
- name: "{gather} | collect raw data"
  your_module:
    host: "{{ _ip }}"
    username: "{{ ansible_user }}"
    password: "{{ ansible_password }}"
  register: _raw_collect
  failed_when: false
  no_log: true

- name: "{gather} | set collect status"
  set_fact:
    _collect_ok: "{{ _raw_collect is not failed }}"
```

### 3. tasks/normalize.yml 작성 (fragment 방식)

```yaml
- name: "{gather} | normalize | build fragment"
  set_fact:
    _data_fragment:
      hardware:
        vendor: "{{ _raw_collect.data.vendor | default(none) }}"
        model:  "{{ _raw_collect.data.model  | default(none) }}"
      cpu:
        sockets:         "{{ _raw_collect.data.sockets | default(none) }}"
        logical_threads: "{{ _raw_collect.data.threads | default(none) }}"
        model:           null
        cores_physical:  null
        architecture:    null
      memory:
        total_mb:     "{{ _raw_collect.data.mem_mb | default(none) }}"
        total_basis:  "physical_installed"
        installed_mb: "{{ _raw_collect.data.mem_mb | default(none) }}"
        visible_mb:   null
        free_mb:      null
        slots:        []
    _sections_supported_fragment: ['hardware','cpu','memory']
    _sections_collected_fragment: >-
      {{ ['hardware','cpu','memory'] if _collect_ok | bool else [] }}
    _sections_failed_fragment: >-
      {{ [] if _collect_ok | bool else ['hardware','cpu','memory'] }}
    _errors_fragment: []
  no_log: true

- include_tasks:
    file: "{{ lookup('env','REPO_ROOT') }}/common/tasks/normalize/merge_fragment.yml"
```

### 4. site.yml 작성

```yaml
- name: "{gather}-gather"
  hosts: all
  gather_facts: no
  connection: local

  vars_files:
    - "{{ lookup('env','REPO_ROOT') }}/vault/{gather}.yml"

  vars:
    _ip: "{{ ansible_host | default(inventory_hostname) }}"

  tasks:
    - name: "{gather} | gather"
      block:
        - include_tasks:
            file: "{{ lookup('env','REPO_ROOT') }}/common/tasks/normalize/init_fragments.yml"
        - include_tasks: tasks/collect_standard.yml
        - include_tasks: tasks/normalize.yml
        - include_tasks:
            file: "{{ lookup('env','REPO_ROOT') }}/common/tasks/normalize/build_sections.yml"
        - include_tasks:
            file: "{{ lookup('env','REPO_ROOT') }}/common/tasks/normalize/build_status.yml"
        - include_tasks:
            file: "{{ lookup('env','REPO_ROOT') }}/common/tasks/normalize/build_errors.yml"
        - set_fact:
            _out_target_type:       "{gather}"
            _out_collection_method: "{gather}_api"
            _out_ip:                "{{ _ip }}"
            _out_vendor:            null
          no_log: true
        - include_tasks:
            file: "{{ lookup('env','REPO_ROOT') }}/common/tasks/normalize/build_output.yml"
        - set_fact:
            _output: "{{ _output | combine({'schema_version': '1'}) }}"
          no_log: true

      rescue:
        - set_fact:
            _out_target_type:       "{gather}"
            _out_collection_method: "{gather}_api"
            _out_ip:                "{{ _ip }}"
            _out_vendor:            null
            _fail_sec_supported:    ['hardware','cpu','memory']
            _fail_error_section:    "{gather}_gather"
            _fail_error_message:    "{{ ansible_failed_result.msg | default('수집 예외') }}"
          no_log: true
        - include_tasks:
            file: "{{ lookup('env','REPO_ROOT') }}/common/tasks/normalize/build_failed_output.yml"
        - set_fact:
            _output: "{{ _output | combine({'schema_version': '1'}) }}"
          no_log: true

      always:
        - name: OUTPUT
          debug: msg="{{ _output | to_json }}"
```

---

## 체크리스트

- [ ] `{gather}-gather/inventory.sh` — ip 만 처리
- [ ] `vault/{gather}.yml` — 계정 placeholder
- [ ] `tasks/collect_standard.yml` — `_raw_collect`, `_collect_ok`
- [ ] `tasks/normalize.yml` — fragment 생성 + `merge_fragment` 호출
- [ ] `site.yml` — `init_fragments` → collect → normalize → build_* → `schema_version` 주입
- [ ] `OUTPUT` 태스크 — `name: OUTPUT` 유지 (절대 변경 금지)
- [ ] rule 22 (fragment-philosophy) — 섹션 지원 현황 표 업데이트

---

## 새 섹션 추가 (기존 gather 확장)

기존 gather 에 완전히 새로운 데이터가 필요할 때:

```yaml
# 새 tasks/gather_sensors.yml 추가 예시
- name: "linux | sensors | collect"
  shell: ...
  register: _raw_sensors

- name: "linux | sensors | build fragment"
  set_fact:
    _data_fragment:
      sensors:                         # 새 섹션 추가
        temperatures:
          - {name: CPU1, value_c: 48}
    _sections_supported_fragment: ['sensors']
    _sections_collected_fragment: ['sensors']
    _sections_failed_fragment:    []
    _errors_fragment:             []

- include_tasks: "{{ REPO_ROOT }}/common/tasks/normalize/merge_fragment.yml"
```

그 다음 `site.yml` 에 `include_tasks: tasks/linux/gather_sensors.yml` 한 줄 추가.
`build_sections.yml` 이 자동으로 `sensors: success` 를 생성한다.

---

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| 수집 구조 (왜 채널이 셋인가) | [01-gather-structure.md](01-gather-structure.md) |
| Fragment 정규화 과정 (왜 자기 섹션만 만지나) | [02-normalize-flow.md](02-normalize-flow.md) |
| Adapter 시스템 (점수 계산) | [03-adapter-system.md](03-adapter-system.md) |
| 새 벤더 추가 시 검증 절차 | [../reference/live-validation.md](../reference/live-validation.md) |

## 자주 막히는 곳

| 증상 | 원인 / 해결 |
|------|------------|
| 새 섹션이 envelope 에 안 보임 | `merge_fragment.yml` 호출 누락 또는 `_sections_supported_fragment` 에 추가 안 함 |
| 다른 채널에서 새 섹션이 `not_supported` 가 아닌 `failed` 로 보임 | 다른 채널 site.yml 의 supported_sections 에 영향이 가지 않도록 fragment 변수만 set_fact |
| `output_schema_drift_check.py` FAIL | sections.yml + field_dictionary.yml + baseline JSON 3종 동반 갱신이 누락됨 |
| 어댑터를 추가했는데 선택되지 않음 | match.manufacturer / model_patterns 가 실 응답과 일치하는지 raw fixture 비교 |

---

## 절차 B — 새 벤더 / 새 세대 추가 (기존 redfish/os/esxi 채널 안 — cycle 2026-05-07 추가)

> 우려 5 답변. 새 채널 (IPMI / SNMP) 가 아니라 **기존 redfish 채널에 신 vendor (예: Huawei) 또는 신 generation (예: dell_idrac10)** 을 추가할 때.

### 5 파일 동시 수정 매트릭스

| # | 파일 | 의무 | 누락 시 사고 |
|---|---|---|---|
| 1 | `common/vars/vendor_aliases.yml` | **의무** | vendor 정규화 실패 → adapter 매칭 실패 |
| 2 | `adapters/{redfish,os,esxi}/{vendor}_*.yml` | **의무** | adapter_loader 가 본 vendor 인식 못 함 |
| 3 | `redfish-gather/library/redfish_gather.py` `_OEM_EXTRACTORS` | 선택 (OEM 추출 시) | OEM 데이터 envelope `data.hardware.oem` 누락 |
| 4 | `redfish-gather/tasks/vendors/{vendor}/collect_oem.yml + normalize_oem.yml` | 선택 (vendor 특이 endpoint 시) | vendor-specific endpoint 미수집 |
| 5 | `schema/baseline_v1/{vendor}_baseline.json` | **의무 (실측 후)** / lab 부재 시 NEXT_ACTIONS 등재 | 회귀 테스트 미보호 → drift 가능 |

`vault/redfish/{vendor}.yml` (자격증명) + 내부 벤더 노트{vendor}.md` (도메인 노트) 도 의무 (rule 50 R2 9단계).

### 9 단계 (rule 50 R2 정본)

1. `common/vars/vendor_aliases.yml` 매핑 추가
2. `adapters/{channel}/{vendor}_*.yml` adapter 생성 (priority 정책표 — `docs/10` 3.5절)
3. (선택) `redfish-gather/tasks/vendors/{vendor}/` OEM tasks
4. `vault/redfish/{vendor}.yml` 생성 (ansible-vault encrypt) — lab 부재 시 placeholder + 사용자 명시 승인
5. `schema/baseline_v1/{vendor}_baseline.json` 추가 (실장비 검증 후) — lab 부재 시 단계 10 등재
6. 내부 벤더 노트{vendor}.md` 추가
7. 벤더 경계 정책 갱신
8. `docs/reference/live-validation.md` Round 갱신
9. `docs/reference/decision-log.md` ADR 추가

### 단계 10 — lab 부재 vendor 처리 (rule 50 R2 단계 10 / rule 96 R1-A + R1-C)

lab 환경에 vendor 장비 없을 때 (예: cycle 2026-05-01 Huawei/Inspur/Fujitsu/Quanta + cycle 2026-05-06 Superdome Flex):

| 단계 | lab 부재 처리 |
|---|---|
| 4 (vault) | placeholder 사용자 명시 승인 — 실 운영 vault 결정 보류 |
| 5 (baseline) | SKIP — 내부 후속 작업 목록 "사이트 fixture 캡처" + "baseline 추가" 등재 |
| 8 (Round) | "lab 부재 — web sources" 표기. rule 96 R1-A web sources 4종 의무 (vendor docs / DMTF / GitHub / 사이트 실측) |

`add-vendor-no-lab` skill 자동화 — lab 부재 vendor 추가 시 호출.

### Priority 값 결정 절차

```text
신 vendor / 신 세대 priority 결정
  ↓
같은 vendor 의 기존 priority 확인
  ├─ 기존 최고 priority + 20 (역전 방지 충분 간격)
  ├─ specificity 충분 (firmware_patterns + model_patterns 정의)
  └─ generic fallback (priority=0~10) 보다 항상 높음
  ↓
docs/10 3.5절 priority 정책표 매트릭스 참조
  ├─ generic = 0
  ├─ vendor 기본 = 10
  ├─ 세대 (구형) = 30~50
  ├─ 세대 (메인) = 80~100
  ├─ 세대 (최신) = 110~120
  └─ lab 부재 보호 = 101 (특수)
  ↓
ansible-playbook -vvv 로그에서 score 동률 경고 모니터링
  └─ 동률 발견 시 priority 조정
```

### dell_idrac9 walkthrough (예시)

다음은 Dell iDRAC 9 가 메인 세대로 추가될 때 수정한 5 파일 (cycle 2026-04-15 기준):

```yaml
# 1. common/vars/vendor_aliases.yml
vendor_aliases:
  dell:
    - "Dell Inc."
    - "Dell EMC"
    - "Dell"
```

```yaml
# 2. adapters/redfish/dell_idrac9.yml
adapter_id: redfish_dell_idrac9
channel:    redfish
priority:   100                       # 메인 세대
match:
  vendor:             ["Dell", "Dell Inc."]
  firmware_patterns:  ["iDRAC.*9"]
capabilities:
  sections_supported: [system, hardware, bmc, cpu, memory, storage, network, firmware, power]
collect:
  standard_tasks: "redfish-gather/tasks/collect_standard.yml"
  oem_tasks:      "redfish-gather/tasks/vendors/dell/collect_oem.yml"
normalize:
  standard_tasks: "redfish-gather/tasks/normalize_standard.yml"
  oem_tasks:      "redfish-gather/tasks/vendors/dell/normalize_oem.yml"
credentials:
  profile:           "dell"
graceful_degradation:
  critical_sections: [system, hardware]
  optional_sections: [firmware, power]
```

```python
# 3. redfish-gather/library/redfish_gather.py
_OEM_EXTRACTORS = {
    'dell': _extract_oem_dell,        # ← 신 vendor 시 추가
    'hpe':  _extract_oem_hpe,
    'lenovo': _extract_oem_lenovo,
    # ...
}
```

```yaml
# 4. redfish-gather/tasks/vendors/dell/collect_oem.yml + normalize_oem.yml
# vendor 특이 endpoint 수집 (예: /redfish/v1/Dell/...)
```

```bash
# 5. schema/baseline_v1/dell_baseline.json
# 실장비 (PowerEdge R740 iDRAC9 4.00) 캡처 후 추가
```

### 회귀 검증 (PR 머지 전)

```bash
pytest tests/regression/                       # 회귀 158 (cross-channel envelope 120 포함)
pytest tests/redfish-probe/probe_redfish.py --vendor {vendor}
python 내부 검증 스크립트    # vendor 경계 (rule 12)
ansible-playbook --syntax-check redfish-gather/site.yml
```
