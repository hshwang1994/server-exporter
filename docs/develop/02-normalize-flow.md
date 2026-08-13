# 07. Fragment 정규화 과정

## 비유부터

3-채널 수집을 "**여러 사람이 한 보고서를 같이 쓰는 일**"로 비유하면 정확히 들어맞는다.

- CPU 담당자, 메모리 담당자, 네트워크 담당자 등이 각자 자기 영역을 **A4 한 장**에 적어 낸다.
- 본인은 **자기 페이지만** 만진다. 옆 사람 페이지는 손대지 않는다.
- 페이지가 다 모이면 **편집자**가 차례로 받아서 한 권으로 묶는다.
- 편집자는 목차 / 머리말 / 페이지 번호 같은 **공통 항목**을 채운다.

server-exporter 의 정규화는 그대로다.

| 비유 | 코드 |
|---|---|
| 담당자 | gather 태스크 (`gather_cpu.yml`, `collect_memory.yml` 등) |
| A4 한 장 | **fragment 변수** (`_data_fragment`, `_sections_*_fragment`, `_errors_fragment`) |
| 편집자 | `merge_fragment.yml` 과 `build_*.yml` 빌더들 |
| 한 권의 보고서 | 최종 JSON envelope (`_output`) |

이 비유를 머리에 두고 아래 그림을 본다.

---

## 1. 전체 과정

```text
[ 시작 ]
   │
   │  ① 빈 보고서 준비
   ▼
init_fragments.yml
   │  → 누적 변수를 빈 상태로 초기화
   │
   │  ② 담당자 1: CPU 정보 수집
   ▼
gather_cpu.yml ─→ fragment 변수 5개 채움
   │
   ▼
merge_fragment.yml ─→ 누적 변수에 합치고, fragment 비우기
   │
   │  ③ 담당자 2: 메모리 정보 수집
   ▼
gather_memory.yml ─→ fragment 5개 채움
   │
   ▼
merge_fragment.yml ─→ 누적 변수에 또 합치기
   │
   │  ④ ... (다른 담당자들도 같은 패턴)
   ▼
   │  ⑤ 편집자가 보고서 조립
   ▼
build_sections   ─→ "어떤 섹션이 success/failed/not_supported 인가"
build_status     ─→ "전체적으로 success/partial/failed 인가"
build_errors     ─→ errors[] 표준화
build_meta       ─→ 시작/종료 시각, 소요 시간
build_correlation─→ 시리얼/UUID/IP 묶음
build_output     ─→ 13개 필드 JSON 한 통으로 조립
   │
   ▼
[ 결과 = _output ]
```

---

## 2. Fragment 가 뭐야

Fragment 는 "**이번 한 태스크가 만들어낸 자기 영역의 변경분**"이다. 5개 변수가 한 묶음.

```yaml
_data_fragment:               { cpu: { sockets: 2, cores_physical: 24 } }
_sections_supported_fragment: ['cpu']     # 내가 원래 다룰 수 있는 섹션
_sections_collected_fragment: ['cpu']     # 이번에 실제 수집 성공한 섹션
_sections_failed_fragment:    []          # 실패한 섹션 (이번엔 없음)
_errors_fragment:             []          # 수집 중 본 오류 (이번엔 없음)
```

규칙은 단순하다.

- **자기 영역만 채운다.** CPU 담당자는 `_data_fragment` 의 `cpu` 키만 만진다. memory 키는 절대 안 만진다.
- **누적 변수는 만지지 않는다.** `_merged_data`, `_all_sec_*`, `_all_errors` 는 편집자(merge_fragment.yml) 의 영역이다.

이 규칙을 어기면 (다른 사람 페이지에 손대거나 한 권짜리 보고서 자체를 직접 고치면) 누가 뭘 만들었는지 추적이 안 된다.

---

## 3. `init_fragments.yml` — 빈 보고서 준비

수집 맨 처음에 한 번만 호출. 누적 변수를 비운다.

```yaml
_merged_data:         {}    # data 그릇 (실제로는 sections 별 빈 skeleton 으로 초기화 — storage/network 하위 구조 포함)
_all_sec_supported:   []
_all_sec_collected:   []
_all_sec_failed:      []
_all_sec_unsupported: []    # vendor/펌웨어 미지원 섹션 (cycle 2026-05-01)
_all_errors:          []
```

빠뜨리면 이전 호스트의 데이터가 남아 다음 호스트에 섞일 수 있다.

---

## 4. `merge_fragment.yml` — 편집자가 받아 묶기

각 gather 태스크가 fragment 5개를 채운 **직후** 호출한다.

**하는 일 4가지**

1. `_merged_data` 에 `_data_fragment` 를 재귀 병합
   - dict + dict → 1단계 재귀 병합 (top-level 키를 합치고 같은 키의 하위 dict 도 한 단계 병합. 충돌하면 fragment 값 채택)
   - list + list → 합산
   - null + 값 → 값 채택
2. `_all_sec_supported / collected / failed / unsupported` 에 fragment 의 섹션 list 를 union 으로 추가
   - `unsupported` 는 vendor/펌웨어가 원래 못 주는 섹션을 명시적으로 표시할 때만 채운다. 대부분 gather 는 비워 둔다 (그래서 gather 가 만지는 fragment 는 5개)
3. `_all_errors` 에 errors 누적
4. fragment 5개를 **다시 비운다** (다음 태스크에 안 새도록)

쉽게 말하면 "**받아서 누적해주고, 책상 정리해줌**".

호출을 빠뜨리면 그 fragment 는 그냥 사라진다 (다음 태스크가 덮어씀). 출력 JSON 에 해당 섹션이 빠진다.

---

## 5. `build_*.yml` — 보고서 5개 절 만들기

merge 가 다 끝나면 누적 변수가 가득 차 있다. 이걸로 envelope 의 각 필드를 만든다.

### 5.1 `build_sections.yml`

`sections` 객체 (10개 섹션 각각 success/failed/not_supported) 를 만든다.

| 누적 변수에서 이 섹션이… | sections 값 |
|---|---|
| unsupported 에 **있다** | `not_supported` (vendor/펌웨어 미지원 — 우선 적용) |
| supported 에 **없다** | `not_supported` |
| failed 에 **있다** | `failed` |
| collected 에 **있다** | `success` |
| 어디에도 없다 | `failed` (미분류 fallback) |

### 5.2 `build_status.yml`

전체 `status` 한 단어 (success / partial / failed) 를 정한다.

| 지원 섹션 중에서… | status |
|---|---|
| 전부 success | `success` |
| success 도 있고 failed 도 있음 | `partial` |
| success 가 하나도 없음 | `failed` |

`errors` 가 있다고 곧바로 `failed` 가 되지는 않는다. 이게 docs/20 의 4가지 시나리오가 갈리는 이유다.

### 5.3 `build_errors.yml`

`_all_errors` 에 쌓인 항목을 표준 형식 `{ section, message, detail }` 로 정리.

### 5.4 `build_meta.yml`

`started_at / finished_at / duration_ms / adapter_id / adapter_version` 등 메타정보 생성.

### 5.5 `build_correlation.yml`

`serial_number / system_uuid / bmc_ip / host_ip` 식별자를 모은다. 다른 시스템 데이터와 묶을 때 쓰는 키.

### 5.6 `build_output.yml`

위 모든 결과를 envelope 13 필드로 조립한다 (`schema_version: "1"` 은 마지막에 각 채널 `site.yml` 이 주입).

---

## 6. 이렇게 만든 이유

비유 그림이 답이다. 새 섹션 / 새 채널 / 새 벤더가 들어왔을 때 **편집자 코드를 안 고친다.**

- **새 섹션 추가**: 새 gather 태스크가 fragment 5개 채우는 패턴만 따르면 끝. `merge_fragment.yml` 도 `build_*.yml` 도 안 건드린다.
- **새 채널 추가**: 똑같이 `init_fragments.yml` → gather → `merge_fragment.yml` → `build_*.yml` 호출 한 줄만 추가하면 된다.
- **새 벤더 추가**: 다른 차원이라 더 단순하다. 기존 fragment 패턴 그대로 가고 `adapters/` 에 YAML 만 추가한다 (docs/10).

같은 패턴으로 모든 변화가 흡수된다는 게 fragment 정규화의 가치다.

---

## 7. 자주 나는 사고 3가지

수집 결과가 이상할 때 90% 는 이 셋 중 하나다.

**(가) `merge_fragment.yml` 호출을 빠뜨림**
gather 태스크가 fragment 를 만들었는데 merge 호출을 안 한 경우. 다음 gather 가 fragment 를 덮어쓰면서 그 섹션 데이터가 통째로 사라진다. 증상은 "수집은 됐는데 출력 JSON 에서 그 섹션만 비어있음".

**(나) 자기 영역 밖을 만짐**
CPU gather 가 `_data_fragment` 의 memory 키도 같이 채우는 식. 기능은 동작하지만 누가 뭘 만들었는지 추적 안 된다. 다른 채널과 합칠 때 충돌.

**(다) 누적 변수를 직접 수정**
gather 안에서 `_merged_data` 나 `_all_errors` 를 set_fact 로 직접 고침. 편집자 패턴이 깨진다. 회귀 테스트가 잡아내는 1순위 사고.

---

## 8. 더 보고 싶을 때

| 보고 싶은 것 | 파일 |
|---|---|
| 출력 JSON 의 키 의미 | `docs/contract/03-fields.md` |
| 채널 구조 (어떤 채널이 어떤 gather 호출하나) | `docs/develop/01-gather-structure.md` |
| Fragment 철학 (왜 자기 영역만 만지나) | rule 22 (fragment-philosophy) 의 Fragment 절 |
| 빌더 코드 본체 | `common/tasks/normalize/build_*.yml` |
| 누적 합치기 코드 | `common/tasks/normalize/merge_fragment.yml` |
