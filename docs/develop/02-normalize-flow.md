# Fragment 정규화 과정

## 비유부터

세 채널의 수집은 "여러 사람이 한 보고서를 같이 쓰는 일"과 같습니다.

- CPU 담당자, 메모리 담당자, 네트워크 담당자가 각자 자기 영역을 한 장씩 적어 냅니다.
- 본인은 자기 페이지만 만지고 옆 사람 페이지는 손대지 않습니다.
- 페이지가 다 모이면 편집자가 차례로 받아 한 권으로 묶습니다.
- 편집자가 목차, 머리말, 페이지 번호 같은 공통 항목을 채웁니다.

| 비유 | 코드 |
|---|---|
| 담당자 | gather 태스크 (`gather_cpu.yml`, `normalize_system.yml` 등) |
| 한 장 | fragment 변수 (`_data_fragment`, `_sections_*_fragment`, `_errors_fragment`) |
| 편집자 | `common/tasks/normalize/merge_fragment.yml`과 `build_*.yml` |
| 한 권의 보고서 | 최종 JSON 봉투 (`_output`) |

## 1. 전체 과정

```text
init_fragments.yml          ① 누적 변수를 빈 상태로 초기화
   │
gather_cpu.yml              ② 담당자 1: fragment 변수 5개를 채움
merge_fragment.yml             누적 변수에 합치고 fragment 를 비움
   │
gather_memory.yml           ③ 담당자 2: 같은 패턴
merge_fragment.yml
   │
   … (다른 담당자들도 같은 패턴)
   │
build_sections.yml          ⑤ 어떤 섹션이 success, failed, not_supported 인가
build_status.yml               전체가 success, partial, failed 인가
build_errors.yml               errors[] 표준화
build_meta.yml                 시작, 종료 시각, 소요 시간, 어댑터
build_correlation.yml          시리얼, UUID, IP 묶음
build_output.yml               13개 필드 봉투 조립
   │
[ 결과 = _output ]
```

## 2. fragment란

fragment는 "이번 한 태스크가 만들어낸 자기 영역의 변경분"입니다. 변수 5개가 한 묶음입니다.

```yaml
_data_fragment:               { cpu: { sockets: 2, cores_physical: 24 } }
_sections_supported_fragment: ['cpu']     # 내가 원래 다룰 수 있는 섹션
_sections_collected_fragment: ['cpu']     # 이번에 실제 수집에 성공한 섹션
_sections_failed_fragment:    []          # 실패한 섹션
_errors_fragment:             []          # 수집 중 본 오류
```

규칙은 둘입니다.

- 자기 영역만 채웁니다. CPU 담당자는 `_data_fragment`의 `cpu` 키만 만지고 `memory` 키는 만지지 않습니다.
- 누적 변수는 만지지 않습니다. `_merged_data`, `_all_sec_*`, `_all_errors`는 편집자(`merge_fragment.yml`)의 영역입니다.

이 규칙을 어기면 누가 무엇을 만들었는지 추적할 수 없습니다.

벤더나 펌웨어가 원래 주지 않는 섹션을 명시하려면 `_sections_unsupported_fragment`도 채울 수 있습니다. 대부분의 gather는 비워 둡니다.

## 3. `init_fragments.yml`: 빈 보고서 준비

수집 맨 처음에 한 번만 부릅니다. 누적 변수를 비웁니다.

```yaml
_merged_data:         {}    # 실제로는 섹션별 빈 뼈대로 초기화 (storage, network 의 하위 구조 포함)
_all_sec_supported:   []
_all_sec_collected:   []
_all_sec_failed:      []
_all_sec_unsupported: []
_all_errors:          []
```

빠뜨리면 이전 서버의 데이터가 남아 다음 서버에 섞일 수 있습니다.

## 4. `merge_fragment.yml`: 편집자가 받아 묶기

각 gather 태스크가 fragment 5개를 채운 직후 부릅니다. 하는 일은 넷입니다.

1. `_merged_data`에 `_data_fragment`를 병합합니다. dict와 dict는 한 단계 재귀 병합(같은 키의 하위 dict도 한 단계 병합, 충돌하면 fragment 값), list와 list는 합산, null과 값은 값 채택입니다.
2. `_all_sec_supported`, `_all_sec_collected`, `_all_sec_failed`, `_all_sec_unsupported`에 fragment의 섹션 목록을 합집합으로 더합니다.
3. `_all_errors`에 errors를 누적합니다.
4. fragment 5개를 다시 비웁니다. 다음 태스크에 새지 않게 하기 위해서입니다.

호출을 빠뜨리면 그 fragment는 다음 태스크가 덮어써서 사라지고, 출력 JSON에서 그 섹션이 빠집니다.

## 5. `build_*.yml`: 보고서 조립

merge가 다 끝나면 누적 변수로 봉투의 각 필드를 만듭니다.

### 5.1 `build_sections.yml`

`sections` 객체(11개 섹션 각각 `success`, `failed`, `not_supported`)를 만듭니다.

| 누적 변수에서 이 섹션이 | `sections` 값 |
|---|---|
| unsupported에 있다 | `not_supported` (벤더, 펌웨어 미지원. 가장 먼저 적용) |
| supported에 없다 | `not_supported` |
| failed에 있다 | `failed` |
| collected에 있다 | `success` |
| 어디에도 없다 | `failed` |

### 5.2 `build_status.yml`

전체 `status`를 정합니다. `not_supported`인 섹션은 계산에서 뺍니다.

| 지원 섹션 중에서 | `status` |
|---|---|
| 남은 섹션이 없다 | `failed` |
| 전부 success | `success` |
| success가 하나도 없다 | `failed` |
| 그 밖 | `partial` |

`errors`가 있다고 곧바로 `failed`가 되지는 않습니다. `status`는 섹션을 채웠는가, `errors`는 채우는 과정에서 알아둘 일이 있었는가입니다([../contract/02-output-envelope.md](../contract/02-output-envelope.md)).

예외 하나(2026-10-13): OS 채널은 조립이 끝난 뒤 `os-gather/tasks/normalize/require_serial.yml` 이 Serial Number 를 확인하고, 없으면 섹션과 무관하게 `failed` 로 확정합니다(시나리오 E — [../contract/03-fields.md](../contract/03-fields.md) 4절). 이 파일의 판정은 바뀌지 않습니다.

### 5.3 `build_errors.yml`

`_all_errors`를 `{ section, message, detail }` 형식으로 정리합니다. `message`는 사용자에게 보일 문장, `detail`은 기술 근거입니다.

### 5.4 `build_meta.yml`

`started_at`, `finished_at`, `duration_ms`, `adapter_id`, `adapter_version`, `ansible_version`을 만듭니다.

### 5.5 `build_correlation.yml`

`serial_number`, `system_uuid`, `bmc_ip`, `host_ip`를 모읍니다. 다른 채널의 결과와 같은 서버를 맞출 때 쓰는 키입니다.

### 5.6 `build_output.yml`

위 결과를 봉투 12개 필드로 조립하고, 각 채널의 `site.yml`이 마지막에 `schema_version`을 붙여 13개가 됩니다. 조립 직전에 두 가지를 보정합니다. 정상 경로로 `status=failed`가 됐는데 사유가 비어 있으면(성공 섹션 0개) `gather` / `GATHER_FAILED` / "수집된 정보가 없다" 문장을 채우고, 그 뒤 `errors[0]`이 그 문장이 아니면 대표 오류를 앞에 둡니다(예외 경로의 `build_failed_output.yml`과 같은 규칙, 2026-10-13). OS 채널은 그 사이에 `os-gather/tasks/normalize/require_serial.yml`(Serial Number 필수 규칙, `CHECKPOINT` 앞)이 한 번 더 돕니다. `hostname`은 `data.system.hostname`, `data.system.fqdn`, `data.bmc.network_hostname` 순으로 찾고 셋 다 없으면 `null`입니다. IP로 대체하지 않습니다.

## 6. 이렇게 만든 이유

새 섹션, 새 채널, 새 벤더가 들어와도 편집자 코드를 고치지 않습니다.

- 새 섹션: 새 gather 태스크가 fragment 5개를 채우는 패턴만 따르면 됩니다.
- 새 채널: `init_fragments.yml` → gather → `merge_fragment.yml` → `build_*.yml` 호출을 같은 순서로 둡니다.
- 새 벤더: 어댑터 YAML만 추가합니다([03-adapter-system.md](03-adapter-system.md)).

## 7. 자주 나는 사고

수집 결과가 이상할 때 대부분 이 셋 중 하나입니다.

- `merge_fragment.yml` 호출을 빠뜨렸습니다. 다음 gather가 fragment를 덮어써서 그 섹션 데이터가 통째로 사라집니다. 증상은 "수집은 됐는데 출력 JSON에서 그 섹션만 비어 있음"입니다.
- 자기 영역 밖을 만졌습니다. CPU gather가 `memory` 키도 채우는 식입니다. 동작은 하지만 추적이 안 되고 다른 채널과 합칠 때 충돌합니다.
- 누적 변수를 직접 수정했습니다. gather 안에서 `_merged_data`나 `_all_errors`를 `set_fact`로 고치면 편집자 패턴이 깨집니다. 회귀 시험이 가장 먼저 잡는 사고입니다.

## 8. 더 보고 싶을 때

| 보고 싶은 것 | 위치 |
|---|---|
| 출력 JSON 키의 의미 | [../contract/03-fields.md](../contract/03-fields.md) |
| 어느 채널이 어떤 gather 를 부르나 | [01-gather-structure.md](01-gather-structure.md) |
| 빌더 코드 | `common/tasks/normalize/build_*.yml` |
| 누적 병합 코드 | `common/tasks/normalize/merge_fragment.yml` |
