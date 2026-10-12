# DMTF Redfish 스키마 참조 사본 (DSP8010 2026.1)

Redfish 수집 코드가 쓰는 enum, 필드 이름, 경로를 DMTF 표준과 대조하기 위한 참조 사본입니다. 운영 코드는 이 파일들을 읽지 않습니다. 의존성이 아니라 참조 데이터입니다.

## 출처

- 번들: DMTF DSP8010 Redfish Schema Bundle
- 버전: `2026.1` (2026-04-02 공개, `dmtf_info.json`)
- 가져온 경로: 번들의 `json-schema/` 디렉터리
- 라이선스: DMTF 스키마는 구현과 참조 목적의 재배포를 허용합니다 (Copyright DMTF, 일부 SNIA Swordfish)
- 형식: JSON Schema. enum과 필드 대조에는 JSON Schema로 충분해 CSDL XML과 OpenAPI는 두지 않았습니다

## 범위

전체 번들이 아니라 server-exporter가 실제로 참조하는 리소스만 둡니다. 리소스마다 두 파일이 있습니다.

- `<Resource>.json`: 버전 없는 통합 파일
- `<Resource>.v1_X_Y.json`: 최신 버전. enum 정의가 인라인으로 들어 있어 대조의 정본

포함 리소스 (28):
`ServiceRoot, ComputerSystem, Chassis, Manager, ManagerAccount, Role, AccountService,
Processor, Memory, Storage, StorageController, SimpleStorage, Drive, Volume,
EthernetInterface, NetworkAdapter, NetworkPort, Port, NetworkDeviceFunction,
Power, PowerSubsystem, PowerSupply, EnvironmentMetrics, Thermal, ThermalSubsystem,
SoftwareInventory, UpdateService, Resource`

`Resource.json`이 공통 `Status.State`, `Status.Health` enum의 정본입니다. `Thermal`과 `ThermalSubsystem`은 `gather_thermal`이 읽는 리소스입니다.

## 사용법

```python
import json
d = json.load(open("Port.v1_19_0.json", encoding="utf-8"))
print(d["definitions"]["LinkStatus"]["enum"])
# ['LinkUp', 'Starting', 'Training', 'LinkDown', 'NoLink']
```

## 갱신 시점

- DMTF가 새 번들(DSP8010 2026.2 이후)을 공개했을 때
- 사이트 BMC 펌웨어 업그레이드로 응답 스키마 변화를 관측했을 때
- 새 벤더나 세대를 추가하며 참조 리소스가 늘었을 때

갱신할 때는 해당 리소스의 최신 JSON Schema를 같은 방식으로 복사하고 `dmtf_info.json`의 버전을 올립니다.

## 최초 대조 결과 (2026-06-08)

`redfish_gather.py`의 enum, 필드, 경로 대조 항목 10개 중 9개가 일치했고, 1개의 차이는 보정을 마쳤습니다.
