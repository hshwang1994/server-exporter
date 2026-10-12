# 벤더, 세대, 섹션 추가

이 문서는 기존 세 채널에 새 벤더나 세대를 붙이거나, 새 섹션을 추가하는 절차입니다. 먼저 [01-gather-structure.md](01-gather-structure.md)(채널이 셋인 이유), [02-normalize-flow.md](02-normalize-flow.md)(자기 영역만 만지는 이유), [03-adapter-system.md](03-adapter-system.md)(벤더 차이를 어디에 두는지)를 읽으세요.

## 1. 새 Redfish 벤더

| 단계 | 파일 | 필수 여부 |
|---|---|---|
| 1 | `common/vars/vendor_aliases.yml`에 제조사 표기 추가 | 필수. 없으면 벤더가 정규화되지 않아 어댑터와 복구 vault 를 찾지 못합니다 |
| 2 | `adapters/redfish/<vendor>_<generation>.yml` | 필수. 없으면 `redfish_generic`으로 표준 필드만 수집합니다 |
| 3 | `redfish-gather/library/redfish_gather.py`의 `_OEM_EXTRACTORS`와 `_extract_oem_<vendor>` | 선택. 벤더 OEM 영역(`Oem.<Vendor>`)에서 뽑을 값이 있을 때 |
| 4 | `vault/<loc>/redfish/<vendor>.yml` (복구 계정) | 선택. 표준 계정 복구를 쓰는 환경만 ([../operate/05-vault.md](../operate/05-vault.md)) |
| 5 | `tests/fixtures/redfish/<name>/` 원본 응답과 재생 시험 | 필수. 실장비가 없으면 벤더 문서 기준 합성 응답이라도 두고 README에 출처를 적습니다 |
| 6 | `schema/baseline_v1/<vendor>_baseline.json` | 실장비 확인 뒤. 기준선은 실측으로만 만듭니다 |
| 7 | [../reference/compatibility-matrix.md](../reference/compatibility-matrix.md), [../reference/live-validation.md](../reference/live-validation.md), [../reference/decision-log.md](../reference/decision-log.md) | 필수 |

어댑터 YAML의 구조와 priority 결정은 [03-adapter-system.md](03-adapter-system.md) 3절과 4절에 있습니다. 벤더 별칭 예시입니다.

```yaml
# common/vars/vendor_aliases.yml
vendor_aliases:
  fujitsu:
    - "Fujitsu"
    - "FUJITSU"
    - "Fujitsu Limited"
```

실장비가 없는 벤더는 어댑터 파일 머리 주석에 참고한 벤더 문서나 DMTF 문서의 주소와 확인 날짜를 적고, 실장비 확인 전까지 문서에 "미확인"으로 표시합니다.

## 2. 기존 벤더의 새 세대

어댑터 YAML 하나를 추가합니다. OEM 구조가 같으면 코드는 바뀌지 않습니다.

1. 같은 벤더의 기존 어댑터 priority를 봅니다(예: `dell_idrac9` 100, `dell_idrac10` 120).
2. 새 세대는 기존 최고값보다 20 높게 둡니다.
3. `firmware_patterns`에 세대 토큰을 단어 경계로 적습니다(예: `"iDRAC\\s*11\\b"`). 버전 숫자 패턴은 보조로만 씁니다.
4. 기존 fixture 전체로 재생 시험을 돌려 다른 세대의 선택 결과가 바뀌지 않았는지 확인합니다(`tests/unit/test_adapter_generation_tokens.py`가 대표 사례를 고정합니다).

## 3. 새 Linux 배포판, Windows 버전, ESXi 버전

`adapters/os/`나 `adapters/esxi/`에 YAML을 추가합니다.

```yaml
# adapters/os/linux_<이름>.yml 의 예
adapter_id: os_linux_<이름>
priority: 50
match:
  os_type: linux
  distribution_patterns: ["Rocky"]
capabilities:
  sections_supported: [system, hardware, cpu, memory, storage, network, users]
```

수집 태스크는 배포판과 무관하게 같은 파일을 쓰므로, 어댑터는 결과의 `meta.adapter_id`와 지원 섹션 선언에만 영향을 줍니다. 배포판 고유 명령 차이는 `os-gather/tasks/linux/*.yml` 안에서 명령 존재 여부로 처리합니다.

## 4. 기존 채널에 새 섹션

예를 들어 Linux에 `sensors` 섹션을 더한다고 합시다.

1. `os-gather/tasks/linux/gather_<섹션>.yml`(예: sensors)을 만듭니다. fragment 변수 5개를 채우고 `merge_fragment.yml`을 부릅니다.

   ```yaml
   - name: "linux | sensors | collect"
     ansible.builtin.raw: "..."
     register: _raw_sensors
     changed_when: false
     failed_when: false

   - name: "linux | sensors | build fragment"
     ansible.builtin.set_fact:
       _data_fragment:
         sensors: { temperatures: [...] }
       _sections_supported_fragment: ['sensors']
       _sections_collected_fragment: "{{ ['sensors'] if (_raw_sensors.rc | default(1)) == 0 else [] }}"
       _sections_failed_fragment:    "{{ [] if (_raw_sensors.rc | default(1)) == 0 else ['sensors'] }}"
       _errors_fragment: []
     no_log: true

   - ansible.builtin.include_tasks:
       file: "{{ lookup('env','REPO_ROOT') }}/common/tasks/normalize/merge_fragment.yml"
   ```

2. `os-gather/site.yml`의 Linux 플레이에 `include_tasks` 한 줄을 추가합니다.
3. 정의 파일을 함께 갱신합니다. `schema/sections.yml`(섹션 정의와 채널), `common/vars/supported_sections.yml`(채널별 지원 섹션), `schema/field_dictionary.yml`(필드 사전), `common/tasks/normalize/init_fragments.yml`(빈 뼈대), 해당 채널 어댑터의 `capabilities.sections_supported`, `docs/contract/03-fields.md`.
4. 기준선 JSON(`schema/baseline_v1/`)과 회귀 시험을 갱신합니다.

`build_output.yml`과 `merge_fragment.yml`은 고치지 않습니다. 다른 채널은 새 섹션을 지원 목록에 넣지 않으면 자동으로 `not_supported`가 됩니다.

새 섹션은 호출자 계약의 변경입니다. 봉투 최상위 13 필드는 그대로이지만 `sections`와 `data`에 키가 늘어나므로 호출자와 합의한 뒤 진행합니다.

## 5. 새 채널

새 채널(예: SNMP)은 어댑터만으로 끝나지 않습니다. 다음이 함께 바뀝니다.

- `<channel>-gather/site.yml`, `inventory.sh`, `tasks/`: 공통 골격([01-gather-structure.md](01-gather-structure.md) 3절)을 같은 순서로 둡니다. `OUTPUT` 태스크 이름은 그대로여야 합니다.
- `Jenkinsfile_portal`의 `target_type` 허용값과 Runner 능력 라벨, `common/vars/supported_sections.yml`, `module_utils/credential_common.py`의 자격증명 범위 규칙, `vault/<loc>/<channel>.yml`.
- 호출자 계약 문서와 `schema/`.

범위가 커서 설계 결정이 먼저 필요합니다.

## 6. 검증

변경 범위에 맞게 다음을 돌립니다.

```bash
# 저장소 루트. Ansible 이 있는 Linux 또는 WSL
ansible-playbook --syntax-check redfish-gather/site.yml      # 바꾼 채널
python -m pytest tests/unit tests/e2e tests/regression -q    # 단위, 종단, 회귀
python -m pytest tests/integration -q -m "not live"          # fixture 재생
python tests/validate_field_dictionary.py                    # 섹션, 필드 사전 정합
```

어댑터 선택 결과는 재생 시험의 `meta.adapter_id`와 `-vvv` 로그로 봅니다. 실장비가 있으면 Jenkins Job으로 한 대를 수집해 결과 봉투를 확인하고 [../reference/live-validation.md](../reference/live-validation.md)에 기록합니다. 단위 시험 통과는 실장비 확인이 아닙니다.

## 7. 자주 막히는 곳

| 증상 | 원인과 조치 |
|---|---|
| 새 섹션이 봉투에 안 보임 | `merge_fragment.yml` 호출 누락 또는 `_sections_supported_fragment`에 추가하지 않음 |
| 다른 채널에서 새 섹션이 `failed`로 나옴 | 그 채널의 `supported_sections.yml` 목록에 넣지 않아야 `not_supported`가 됩니다 |
| 필드 사전 검사 실패 | `sections.yml`, `field_dictionary.yml`, 기준선 JSON 중 하나만 갱신했습니다 |
| 어댑터가 선택되지 않음 | `match`의 vendor, model_patterns, firmware_patterns가 실제 응답과 다릅니다. 원본 응답을 확인하세요 |
