# HPE Compute Scale-up Server 3200 (CSUS 3200) Mock Fixture

> Lab 부재 — Web Sources 합성 (rule 96 R1-A). 사이트 실측 후 정정 의무.

## 메타

- **Product**: HPE Compute Scale-up Server 3200 (CSUS 3200)
- **Manager**: RMC (Rack Management Controller) — single aggregated controller
- **Architecture**: "built on the proven HPE Superdome Flex architecture" (HPE psnow doc/a50009596enw)
- **Multi-partition**: YES (nPAR — Partition0/Partition1/Partition2 합성 시나리오)
- **Multi-chassis**: YES (Base + Expansion1 + Expansion2 합성 시나리오 — 최대 4 chassis)
- **Multi-manager**: YES (RMC + PDHC0 + PDHC1 + Bay1.iLO5 4-manager 합성)
- **Firmware**: RMC 3.10.00 (추정 — 사이트 실측 시 정정)
- **Lab**: 부재 — web sources only (rule 96 R1-A)
- **cycle**: 2026-05-12 (ADR-2026-05-12) — RMC 멀티-노드 토폴로지 정식 지원

## 합성 출처 매핑 (rule 96 R1-A)

| 파일 | Source | Confidence |
|---|---|---|
| service_root.json | HPE Server Management Portal (servermanagementportal.ext.hpe.com/docs/concepts/gettingstarted) + DMTF DSP0266 v1.15.0 | HIGH (표준 구조) |
| managers_collection.json | sdflexutils GitHub README (Partition0 명시) + HPE Superdome Flex Admin Guide (P06150-401a) | MED — Member ID 패턴 추정 (`RMC` / `PDHC0~N` / `Bay1.iLO5`) |
| systems_collection.json | sdflexutils 1.5.1 (`/redfish/v1/Systems/Partition<N>` 명시) | MED |
| chassis_collection.json | DMTF Chassis v1.20 + HPE FlexNodeInfo 추정 | MED |
| Oem.Hpe.PartitionInfo | sdflex-ironic-driver wiki + sdflexutils 1.5.1 | MED |

### cycle 2026-06-09 (ADR-2026-06-09) 신규 — CSUS 3200 모델 5종 누락분 fixture

> 사용자 제시 CSUS 3200 Redfish 모델 검수 → boot / thermal / power / log_services / CompositionService / Fabrics 추가.
> `test_csus_fixture_replay.py` 가 @odata.id 로 키잉해 `_collect_multi_node_topology` end-to-end 재생.

| 파일 | Redfish 리소스 | Source | Confidence |
|---|---|---|---|
| chassis_base_thermal.json / chassis_expansion{1,2}_thermal.json | `Chassis/{id}/Thermal` | DMTF Thermal.v1 | MED |
| chassis_base_power.json / chassis_expansion{1,2}_power.json | `Chassis/{id}/Power` | DMTF Power.v1 | MED |
| manager_rmc_logservices.json + manager_rmc_logservice_{iml,iel}.json | `Managers/RMC/LogServices` | DMTF LogServiceCollection (IML/IEL 추정 — HPE 관례) | MED |
| compositionservice.json + resourceblocks_collection.json + resourceblock_block{0,1,2}.json | `CompositionService` + `ResourceBlocks` | DMTF CompositionService/ResourceBlock + HPE CSUS Admin Guide (각 RB ↔ chassis) | MED |
| fabrics_collection.json + fabric_flexgrid.json + switches_collection.json + switch_switch{0,1}.json + endpoints_collection.json + endpoint_endpoint{0,1}.json | `Fabrics` + FlexGrid (Switches/Endpoints) | DMTF Fabric/Switch/Endpoint + HPE CSUS architecture (NUMAlink) | LOW — FabricType=PCIe placeholder (DMTF enum 에 NUMAlink 부재) |
| chassis_expansion{1,2}.json | `Chassis/Expansion{1,2}` | DMTF Chassis v1.20 (3-chassis 시나리오 완성) | MED |

system_partition0.json `Boot` 에 `BootOrder` 추가 / manager_rmc.json 에 `LogServices` 링크 추가 / service_root.json 에 `Fabrics` + `CompositionService` 링크 추가.

## 핵심 web sources

- https://servermanagementportal.ext.hpe.com/docs/concepts/gettingstarted — HPE Server Management Portal (확인 2026-05-12)
- https://support.hpe.com/hpesc/public/docDisplay?docId=sd00002765en_us&docLocale=en_US — HPE Compute Scale-up Server 3200 Administration Guide
- https://www.hpe.com/psnow/doc/a50009596enw — CSUS 3200 architecture and RAS ("built on the proven HPE Superdome Flex architecture")
- https://cdrdv2-public.intel.com/792357/FAQ%20-%20HPE%20Compute%20Scale-up%20Server%203200.pdf — CSUS 3200 FAQ (RMC + 표준 Redfish API 명시)
- https://github.com/HewlettPackard/sdflexutils — sdflexutils 1.5.1 (Partition0 명시)
- https://redfish.dmtf.org/schemas/DSP0266_1.15.0.html — DMTF Redfish v1.15

## 위험 신호 (rule 96 R2)

HPE community 게시물 7200359 ("impossible to get redfish answer from superdome flex rmc"):
- 사이트 환경에서 RMC Redfish API 비활성화 / 라이선스 부재 사례 보고
- 본 server-exporter 의 precheck graceful fail + `diagnosis.details.rmc_activation_check` 메타로 진단 hint 제공
- 트러블슈팅: `docs/22_rmc-activation-guide.md` 참조

## 한계

- 사이트 실측 부재 → 모든 fixture 합성 (Confidence MED)
- ServiceRoot.Product 정확 문자열 / Manager ID 패턴 / Oem.Hpe schema → lab 도입 cycle 정정 의무 (후속 작업 C1, C5, C6, C7)
- pytest 통과 = 합성 fixture 통과 ≠ 사이트 실측 통과

## 후속 작업 (NEXT_ACTIONS C1~C8)

- C1: 사이트 fixture 캡처 (`capture-site-fixture` skill)
- C2: baseline JSON 추가 (`schema/baseline_v1/hpe_csus_3200_baseline.json`)
- C3: lab 도입 cycle `hpe-csus-rmc-lab-validation` round
- C4: vault 분리 결정 (`vault/redfish/hpe_csus.yml`)
- C5: ServiceRoot.Product 실측
- C6: Manager / System / Chassis Member ID 패턴 실측
- C7: Oem.Hpe.PartitionInfo / FlexNodeInfo / GlobalConfiguration schema 실측
- C8: RMC 활성화 / Subscription License 요구 실측
