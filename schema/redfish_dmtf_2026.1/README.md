# DMTF Redfish Schema — vendored subset (DSP8010 2026.1)

> 외부 시스템 계약(rule 96)의 **정본 reference**. server-exporter 의 Redfish 수집 코드가
> 참조하는 enum / 필드명 / path 를 DMTF 표준과 대조·검증하기 위한 큐레이션 스냅샷이다.
> **런타임 코드는 이 파일들을 import 하지 않는다** — 순수 reference 데이터(의존성 아님).

## 출처 (origin)

- **번들**: DMTF DSP8010 Redfish Schema Bundle
- **버전**: `2026.1` (release 2026-04-02 — `dmtf_info.json` 참조)
- **다운로드 경로(사용자)**: `C:\Users\hshwa\Downloads\DSP8010_2026.1\DSP8010_2026.1\json-schema\`
- **라이선스**: DMTF 스키마는 구현/참조 목적 자유 재배포 허용 (Copyright DMTF / 일부 SNIA Swordfish)
- **포맷**: JSON Schema (CSDL XML / OpenAPI 는 미포함 — enum/필드 대조에 json-schema 가 충분)

## 범위 (전체 번들 아님)

전체 번들은 약 14,000 파일(json-schema 6,890 + CSDL 279 + OpenAPI 6,863 + registries).
본 디렉터리는 **server-exporter 가 실제 참조하는 리소스만** subset 으로 보관한다.

각 리소스마다 2개 파일:
- `<Resource>.json` — 무버전(consolidated). 일부 리소스는 enum 을 인라인 포함(예: Volume).
- `<Resource>.v1_X_Y.json` — 최신 버전. **enum definition 이 인라인**으로 들어있어 대조의 정본.

포함 리소스 (28):
`ServiceRoot, ComputerSystem, Chassis, Manager, ManagerAccount, Role, AccountService,
Processor, Memory, Storage, StorageController, SimpleStorage, Drive, Volume,
EthernetInterface, NetworkAdapter, NetworkPort, Port, NetworkDeviceFunction,
Power, PowerSubsystem, PowerSupply, EnvironmentMetrics, Thermal, ThermalSubsystem,
SoftwareInventory, UpdateService, Resource`

> `Resource.json` = 공통 `Status.State` / `Status.Health` enum 정본.
> `Thermal` / `ThermalSubsystem` = 현재 코드 미구현(fallback 후보) — 참조용 포함.

## 사용법 (대조 예시)

```python
import json
d = json.load(open("Port.v1_19_0.json", encoding="utf-8"))
print(d["definitions"]["LinkStatus"]["enum"])
# ['LinkUp', 'Starting', 'Training', 'LinkDown', 'NoLink']
```

## 갱신 trigger (rule 28 #11 — 외부 계약, TTL 90일)

- DMTF 신 release (DSP8010 2026.2+) 발표
- 사이트 BMC 펌웨어 업그레이드로 응답 schema 변경 관측
- 신규 vendor / 세대 추가 시 참조 리소스 확장

갱신 시: 동일 절차로 해당 리소스 최신 json-schema 재복사 + `dmtf_info.json` 버전 갱신 +
`docs/ai/catalogs/EXTERNAL_CONTRACTS.md` 의 대조 스냅샷 갱신.

## 최초 대조 결과 (2026-06-08)

`redfish_gather.py` 의 enum/필드/path 10개 대조 항목 중 **9 MATCH + 1 GAP(보정 완료)**.
상세는 `docs/ai/catalogs/EXTERNAL_CONTRACTS.md` "DMTF DSP8010 2026.1 대조" 절 참조.
