# redfish-gather/library/: Redfish 수집 모듈

`redfish_gather.py` 하나가 Redfish 호출 전부를 맡는 Ansible 모듈입니다. Python 표준 라이브러리(`urllib`, `ssl`, `json`, `socket`)만 쓰고 외부 패키지를 쓰지 않습니다. Runner에 패키지가 빠져 있어도 핵심 수집이 실패하지 않게 하기 위해서입니다.

## 모듈이 하는 일

플레이북(`redfish-gather/tasks/collect_standard.yml`)이 서버마다 한 번 호출합니다. 모듈은 다음 순서로 동작합니다.

1. 서비스 루트(`/redfish/v1/`)를 무인증으로 읽어 벤더를 감지합니다 (`detect_vendor`, `_detect_vendor_from_service_root`).
2. 받은 계정으로 인증하고 Systems, Managers, Chassis를 찾습니다. 첫 인증 응답의 HTTP 상태를 인증 증거 파일에 남깁니다 (비밀값 없음).
3. 섹션별 `gather_*` 함수를 차례로 부르고, 함수마다 돌려준 오류를 모아 섹션 상태(성공, 실패, 미지원)를 정합니다. 리소스가 404로 없으면 미지원입니다.
4. 멀티 노드 장비(어댑터의 `manager_layout`이 있는 경우)는 모든 Systems, Managers, Chassis와 CompositionService, Fabrics를 추가로 읽습니다.

## 함수와 리소스

위치는 모듈이 바뀌면서 달라지므로 함수 이름으로 찾습니다 (`grep -n 'def gather_power' redfish_gather.py`).

| 함수 | 리소스 |
|---|---|
| `detect_vendor`, `_detect_vendor_from_service_root` | `/redfish/v1/` (무인증) |
| `gather_system` | `Systems/{id}`. 응답의 `Bios` 링크를 `gather_bios`에 넘깁니다 |
| `gather_bios` | `Bios` 링크 1회 (있을 때만). `Attributes`를 키 이름순으로 정렬해 `data.bios.current.attributes`로 |
| `gather_bmc` | `Managers/{id}`, EthernetInterfaces, NetworkProtocol |
| `gather_processors`, `gather_memory` | `Systems/{id}/Processors`, `Systems/{id}/Memory` (컬렉션과 멤버) |
| `gather_storage` | `Systems/{id}/Storage`, Volumes, Drives. 없으면 SimpleStorage |
| `gather_network` | `Systems/{id}/EthernetInterfaces` |
| `gather_network_adapters_chassis` | `Chassis/{id}/NetworkAdapters`, NetworkPorts, NetworkDeviceFunctions |
| `gather_firmware` | `UpdateService/FirmwareInventory` |
| `gather_power` | `Chassis/{id}/Power`, 없으면 `PowerSubsystem`. 둘 다 없으면 미지원 |
| `gather_thermal` | `Chassis/{id}/Thermal`, 없으면 `ThermalSubsystem`. 둘 다 없으면 미지원 |
| `gather_boot`, `gather_manager_logs` | 멀티 노드 장비의 파티션 부팅 순서와 Manager LogServices |
| `gather_systems_multi`, `gather_managers_multi`, `gather_chassis_multi`, `gather_composition_service`, `gather_fabrics`, `_collect_multi_node_topology` | RMC 장비의 `data.multi_node` |
| `account_service_provision` | 표준 계정 생성 또는 비밀번호 동기화 (`mode: account_provision`). 조건은 `docs/operate/05-vault.md` 6절 |

## 벤더 분기가 허용된 곳

수집 코드는 벤더 이름을 쓰지 않습니다. 다음 영역만 예외이고, 모두 Redfish 표준 자체가 벤더 이름공간을 정의하거나 벤더가 다르게 구현한 쓰기 방식 때문입니다.

| 위치 | 분기 |
|---|---|
| `_OEM_EXTRACTORS`, `_extract_oem_<vendor>` | `Oem.Dell`, `Oem.Hpe`, `Oem.Lenovo`, `Oem.Supermicro`, `Oem.Cisco` 영역에서 추출 |
| `_FALLBACK_VENDOR_MAP` | `common/vars/vendor_aliases.yml`을 읽지 못했을 때의 최소 매핑 |
| `_detect_vendor_from_service_root` | 제조사와 제품 문자열로 벤더 추정 |
| `_ACCOUNT_FAMILIES`, `resolve_account_family`, `account_service_provision` | 계정 생성과 비밀번호 변경의 벤더별 쓰기 방식. 읽기 전용 확인으로 BMC 종류를 정한 뒤 검증된 방식 하나만 실행합니다 |

그 밖의 영역(`common/`, 세 채널의 태스크)에는 벤더 이름을 하드코딩하지 않습니다. 벤더 차이는 어댑터 YAML(`adapters/redfish/`)에 둡니다.

## 외부 의존성

| 구분 | 내용 |
|---|---|
| 표준 라이브러리 | `urllib`, `ssl`, `json`, `socket`, `time`, `re`, `sys`, `os` |
| 외부 패키지 | 쓰지 않습니다. `requests`, `urllib3`, `paramiko` 등을 추가하지 마세요 |

## 디버깅

| 상황 | 확인 |
|---|---|
| 응답 파싱 오류 | `errors[].detail`의 URI와 상태, 해당 `gather_*` 함수. 원본 응답은 `tests/redfish-probe/redfish_full_mirror.py`로 캡처합니다 (`docs/develop/08-onsite-capture.md`) |
| 벤더가 잘못 감지됨 | `_detect_vendor_from_service_root`, `common/vars/vendor_aliases.yml` |
| OEM 값 누락 | `_OEM_EXTRACTORS`에 해당 벤더가 있는지, 응답의 `Oem` 영역에 값이 있는지 |
| 계정 복구 경로 | `diagnosis.details.account_service`, `resolve_account_family` |

## 관련 문서

- `docs/develop/03-adapter-system.md`: 어댑터와 벤더 감지
- `docs/develop/06-debugging.md`: 디버깅 진입점
- `docs/operate/05-vault.md`: 표준 계정과 복구 계정
- `docs/reference/live-validation.md`: 실장비 검증
