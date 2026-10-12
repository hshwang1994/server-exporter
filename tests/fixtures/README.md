# tests/fixtures: 시험 입력

시험이 읽는 입력 자료입니다. 회귀 비교의 "정답지"(정규화된 출력)는 이 폴더가 아니라 `schema/baseline_v1/`에 있습니다.

- `tests/fixtures`: "이런 원본 응답이 들어올 때"
- `schema/baseline_v1`: "이렇게 표준 JSON으로 나와야 한다"

## 디렉터리

| 위치 | 내용 |
|---|---|
| `redfish/` | BMC별 Redfish 응답. 디렉터리마다 README에 장비, 펌웨어, 출처가 있습니다 |
| `os/` | Linux 네트워크 명령 출력 등 OS 채널 합성 입력 |
| `esxi/` | ESXi 채널 입력 (`lab/`는 실장비 캡처, `synthetic/`은 합성) |
| `outputs/` | 결과 봉투 예시 (e2e 시험 입력) |
| `finalize_corpus/` | 결과 정리(Layer A)와 Groovy 보충의 동치 검증용 corpus |
| `input_validation/` | `inventory_json` 입력 검사 사례 (Jenkins 입력 확인과 `inventory.sh` 대조) |
| `addon/` | 추가 수집(Add-on) hook 시험용 합성 Add-on |
| `prodgen/` | 배포본 생성기 시험 입력 |

## Redfish fixture의 종류

| 디렉터리 이름 | 종류 |
|---|---|
| `real_<vendor>_<model>/` | 실장비에서 캡처한 원본 응답 트리 (R740, DL380, SR650, CSUS 3200) |
| `<vendor>/` (`dell/`, `hpe/`, `lenovo/`, `cisco/`, `dell_r760/`) | 2026-03-18과 그 뒤에 실장비에서 받은 리소스별 응답 |
| `<vendor>_<generation>/` | 벤더 문서와 DMTF 스키마로 만든 세대별 합성 응답. 실장비가 없는 벤더(Supermicro, Huawei, Inspur, Fujitsu, Quanta)와 확인하지 않은 세대 |
| `hpe_emulator_*/` | HPE iLO 에뮬레이터 응답 |
| `dmtf_rackmount1/` | DMTF 공개 mockup |

각 디렉터리의 README가 정본입니다. 실장비 캡처와 합성을 구분해 읽으세요. 합성 fixture 통과는 사이트 실측 통과가 아닙니다.

## 파일 이름 규칙 (리소스별 응답)

| 패턴 | 의미 |
|---|---|
| `service_root.json` | 서비스 루트 |
| `system.json`, `system_<section>.json`, `system_<section>_<N>.json` | Systems 멤버와 하위 컬렉션, 멤버 |
| `storage_<id>.json`, `drive_<controller>_<N>.json` | Storage 컨트롤러와 드라이브 |
| `chassis_<section>.json` | Chassis 하위 (power, thermal) |
| `firmware_<N>.json` | FirmwareInventory 항목 |
| `manager_<section>.json` | Manager 하위 |

실장비 캡처 트리(`real_*/`)는 `redfish/v1/.../index.json` 구조이며 변환 도구가 읽습니다 (`docs/develop/08-onsite-capture.md`).

## 장비 정보 (실장비 캡처)

| 벤더 | 모델 | BMC | Redfish 버전 |
|---|---|---|---|
| Lenovo | ThinkSystem SR650 V2 | XCC 5.70 | 1.15.0 |
| HPE | ProLiant DL380 Gen11 | iLO 6 1.73 | 1.20.0 |
| Dell | PowerEdge R740 | iDRAC 9 4.00 | 1.6.0 |
| Cisco | UCS C220 M4 | CIMC 4.1(2g) | 1.2.0 |
| Dell | PowerEdge R760 | iDRAC 9 7.10 | 1.20.1 |

fixture 수는 세지 않습니다.

```bash
for d in tests/fixtures/redfish/*/; do echo "$(find "$d" -name '*.json' | wc -l)  $d"; done
```

## 주의

- fixture에는 실제 시리얼 번호와 MAC 주소가 들어 있습니다. 외부에 공개할 때는 마스킹하세요.
- 펌웨어를 올리면 응답 구조가 달라질 수 있습니다. 캡처 날짜는 각 README에 있습니다.

## 다음

| 다음 작업 | 문서 |
|---|---|
| 회귀 기준선 | `schema/baseline_v1/README.md` |
| 새 벤더 fixture 추가 | `docs/develop/04-add-vendor.md` |
| 실장비 검증 | `docs/reference/live-validation.md` |
