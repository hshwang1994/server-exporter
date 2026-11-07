# 2차 Mock 11대 전수 인벤토리 요약 (2026-10-26)

분류: exists=2xx JSON 이고 gather 가 요청함 / exists_untouched=2xx JSON 인데 gather 미요청 / not_mounted_or_empty=빈 컬렉션 / not_supported=404·405·410·501 / rejected=400·406 / outside_account=401·403 / collect_error=5xx·timeout / binary_or_non_json=raw.* / excluded_or_skipped_policy=크롤러 정책 제외(SSE·cross-host)

| server | 자원 수 | exists | exists_untouched | not_mounted_or_empty | not_supported | rejected | outside_account | collect_error | binary_or_non_json | excluded_or_skipped_policy | other | gather 요청(distinct) | 미러에 없는 요청 | manifest result |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| csus3200_01 | 2316 | 182 | 1807 | 18 | 57 | 0 | 0 | 6 | 16 | 230 | 0 | 182 | 11 | INCOMPLETE |
| csus3200_02 | 2273 | 130 | 1815 | 18 | 57 | 0 | 0 | 9 | 14 | 230 | 0 | 130 | 11 | INCOMPLETE |
| csus3200_03 | 2281 | 166 | 1788 | 18 | 57 | 0 | 0 | 6 | 16 | 230 | 0 | 166 | 11 | INCOMPLETE |
| dl380_gen12_01 | 2434 | 152 | 1570 | 49 | 266 | 278 | 0 | 0 | 9 | 110 | 0 | 152 | 0 | COMPLETE |
| dl380_gen12_02 | 2020 | 143 | 1308 | 49 | 130 | 276 | 0 | 0 | 4 | 110 | 0 | 143 | 0 | COMPLETE |
| dl380_gen12_03 | 1696 | 79 | 1067 | 56 | 94 | 281 | 0 | 0 | 9 | 110 | 0 | 80 | 0 | COMPLETE |
| dl380_gen12_04 | 2327 | 143 | 1595 | 45 | 147 | 277 | 0 | 0 | 10 | 110 | 0 | 143 | 0 | COMPLETE |
| sr650_v4_01 | 3129 | 108 | 1780 | 11 | 991 | 0 | 0 | 1 | 234 | 4 | 0 | 108 | 0 | INCOMPLETE |
| sr650_v4_02 | 3242 | 123 | 1875 | 13 | 992 | 0 | 0 | 1 | 234 | 4 | 0 | 125 | 0 | INCOMPLETE |
| sr650_v4_03 | 3717 | 157 | 2318 | 13 | 990 | 0 | 0 | 1 | 234 | 4 | 0 | 159 | 0 | INCOMPLETE |
| sr650_v4_04 | 3090 | 113 | 1735 | 11 | 992 | 0 | 0 | 1 | 234 | 4 | 0 | 113 | 0 | INCOMPLETE |

## 미요청(exists_untouched) @odata.type 상위 (서버별)

- **csus3200_01**: Signature 1315, Sensor 72, Processor 64, Port 57, ? 39, Certificate 37, JsonSchemaFile 28, ActionInfo 19, PortCollection 14, LogEntry 12, CertificateCollection 9, Assembly 8, SecureBootDatabase 8, Task 8, PCIeFunctionCollection 6, PCIeFunction 6, ProcessorCollection 6, NetworkInterface 6, NetworkDeviceFunctionCollection 6, MessageRegistryFile 5, MetricReportDefinition 5, ManagerAccount 4, Role 4, LogEntryCollection 4, MessageRegistry 4
- **csus3200_02**: Signature 1315, Processor 112, Port 57, Sensor 56, ? 38, Certificate 37, JsonSchemaFile 28, ActionInfo 19, LogEntry 12, Task 12, PortCollection 10, CertificateCollection 9, SecureBootDatabase 8, ProcessorCollection 6, MessageRegistryFile 5, MetricReportDefinition 5, ManagerAccount 4, Role 4, Assembly 4, LogEntryCollection 4, MessageRegistry 4, MetricReport 4, MetricDefinition 3, PCIeFunctionCollection 2, PCIeFunction 2
- **csus3200_03**: Signature 1315, Processor 64, Port 57, Sensor 56, ? 39, Certificate 37, JsonSchemaFile 28, ActionInfo 19, PortCollection 14, LogEntry 12, CertificateCollection 9, Assembly 8, SecureBootDatabase 8, Task 8, PCIeFunctionCollection 6, PCIeFunction 6, ProcessorCollection 6, NetworkInterface 6, NetworkDeviceFunctionCollection 6, MessageRegistryFile 5, MetricReportDefinition 5, ManagerAccount 4, Role 4, LogEntryCollection 4, MessageRegistry 4
- **dl380_gen12_01**: LogEntry 714, JsonSchemaFile 260, Sensor 44, MetricReportDefinition 41, Certificate 34, MetricReport 33, BootOption 23, MetricDefinition 22, PCIeFunction 20, Assembly 18, Port 18, HpeServerDevice 14, PCIeDevice 14, PCIeFunctionCollection 14, MessageRegistryFile 14, PortMetrics 12, Fan 12, CertificateCollection 12, SecureBootDatabase 12, NetworkDeviceFunctionMetrics 10, HpeiLOSecurityParam 10, Signature 10, HpeUSBPort 10, HpeServerPciDevice 9, HpeServerPCISlot 9
- **dl380_gen12_02**: LogEntry 476, JsonSchemaFile 260, Sensor 44, MetricReportDefinition 41, Certificate 34, MetricReport 33, MetricDefinition 22, BootOption 20, Assembly 17, PCIeFunction 17, Port 16, MessageRegistryFile 14, HpeServerDevice 12, PCIeDevice 12, PCIeFunctionCollection 12, Fan 12, CertificateCollection 12, SecureBootDatabase 12, PortMetrics 10, HpeiLOSecurityParam 10, Signature 10, HpeUSBPort 10, NetworkDeviceFunctionMetrics 8, HpeServerPciDevice 8, HpeServerPCISlot 7
- **dl380_gen12_03**: LogEntry 478, JsonSchemaFile 260, Sensor 44, Certificate 22, MessageRegistryFile 14, Assembly 13, Fan 12, BootOption 12, SecureBootDatabase 12, HpeServerDevice 10, HpeiLOSecurityParam 10, HpeUSBPort 10, CertificateCollection 9, HpeServerPCISlot 7, HpeComponent 7, HpeBaseConfigs 6, Role 5, Port 5, PCIeFunction 5, LogService 5, PCIeDevice 4, PCIeFunctionCollection 4, LogEntryCollection 4, HpeServerPciDevice 4, ? 3
- **dl380_gen12_04**: LogEntry 742, JsonSchemaFile 260, Certificate 46, Sensor 44, MetricReportDefinition 41, MetricReport 33, MetricDefinition 22, BootOption 20, Assembly 17, PCIeFunction 17, Port 16, CertificateCollection 15, MessageRegistryFile 14, HpeServerDevice 12, PCIeDevice 12, PCIeFunctionCollection 12, Fan 12, SecureBootDatabase 12, PortMetrics 10, HpeiLOSecurityParam 10, Signature 10, HpeUSBPort 10, HpeComponent 9, NetworkDeviceFunctionMetrics 8, HpeServerPciDevice 8
- **sr650_v4_01**: LogEntry 603, ? 408, JsonSchemaFile 390, Job 36, LenovoLED 28, Sensor 25, JobCollection 17, Task 16, LenovoPortForwardingMap 15, MetricReportDefinition 14, MessageRegistryFile 13, LenovoHistoryMetricValueContainer 13, VirtualMedia 10, MessageRegistry 9, ActionInfo 7, LogService 7, MetricReport 7, Fan 6, Certificate 5, PCIeFunction 5, BootOption 5, LogEntryCollection 5, CertificateCollection 4, Role 4, LenovoBuiltInImageService 4
- **sr650_v4_02**: LogEntry 681, ? 408, JsonSchemaFile 390, Job 36, LenovoLED 28, Sensor 25, JobCollection 17, Task 16, LenovoPortForwardingMap 15, MetricReportDefinition 14, MessageRegistryFile 13, LenovoHistoryMetricValueContainer 13, VirtualMedia 10, PCIeFunction 9, MessageRegistry 9, ActionInfo 7, LogService 7, MetricReport 7, Fan 6, Certificate 5, PCIeDevice 5, PCIeFunctionCollection 5, Chassis 5, BootOption 5, LogEntryCollection 5
- **sr650_v4_03**: LogEntry 1095, ? 408, JsonSchemaFile 390, Sensor 39, Job 39, LenovoLED 28, JobCollection 17, Task 16, PCIeFunction 15, LenovoPortForwardingMap 15, MetricReportDefinition 14, MessageRegistryFile 13, LenovoHistoryMetricValueContainer 13, VirtualMedia 10, MessageRegistry 9, PCIeDevice 8, PCIeFunctionCollection 8, Chassis 8, ActionInfo 7, LogService 7, NetworkInterface 7, MetricReport 7, Fan 6, Certificate 5, BootOption 5
- **sr650_v4_04**: LogEntry 548, ? 408, JsonSchemaFile 390, Job 36, Sensor 31, LenovoLED 28, JobCollection 17, Task 16, LenovoPortForwardingMap 15, MetricReportDefinition 14, MessageRegistryFile 13, LenovoHistoryMetricValueContainer 13, VirtualMedia 10, MessageRegistry 9, ActionInfo 7, LogService 7, MetricReport 7, Fan 6, Certificate 5, PCIeFunction 5, BootOption 5, LogEntryCollection 5, CertificateCollection 4, Role 4, LenovoBuiltInImageService 4

## 미러에 없는데 gather 가 요청한 경로 (서버별)

- **csus3200_01**: `Chassis/Rack1/Power`, `Chassis/Rack1/PowerSubsystem`, `Chassis/Rack1/Thermal`, `Chassis/Rack1/ThermalSubsystem`, `Chassis/RackGroup/Power`, `Chassis/RackGroup/PowerSubsystem`, `Chassis/RackGroup/Thermal`, `Chassis/RackGroup/ThermalSubsystem`, `Chassis/r001u01/EnvironmentMetrics`, `Chassis/r001u01/Power`, `Chassis/r001u01/Thermal`
- **csus3200_02**: `Chassis/Rack1/Power`, `Chassis/Rack1/PowerSubsystem`, `Chassis/Rack1/Thermal`, `Chassis/Rack1/ThermalSubsystem`, `Chassis/RackGroup/Power`, `Chassis/RackGroup/PowerSubsystem`, `Chassis/RackGroup/Thermal`, `Chassis/RackGroup/ThermalSubsystem`, `Chassis/r001u01/EnvironmentMetrics`, `Chassis/r001u01/Power`, `Chassis/r001u01/Thermal`
- **csus3200_03**: `Chassis/Rack1/Power`, `Chassis/Rack1/PowerSubsystem`, `Chassis/Rack1/Thermal`, `Chassis/Rack1/ThermalSubsystem`, `Chassis/RackGroup/Power`, `Chassis/RackGroup/PowerSubsystem`, `Chassis/RackGroup/Thermal`, `Chassis/RackGroup/ThermalSubsystem`, `Chassis/r001u01/EnvironmentMetrics`, `Chassis/r001u01/Power`, `Chassis/r001u01/Thermal`
- **dl380_gen12_01**: 없음
- **dl380_gen12_02**: 없음
- **dl380_gen12_03**: 없음
- **dl380_gen12_04**: 없음
- **sr650_v4_01**: 없음
- **sr650_v4_02**: 없음
- **sr650_v4_03**: 없음
- **sr650_v4_04**: 없음

## collect_error(5xx·timeout) 경로 (서버별)

- **csus3200_01**: `/redfish/v1/Managers/RMC/LogServices/RmcConfig/RawConfig`, `/redfish/v1/RawFruData/r001u01/PCIE_SLOT1`, `/redfish/v1/RawFruData/r001u01/PCIE_SLOT16`, `/redfish/v1/RawFruData/r001u01/PCIE_SLOT3`, `/redfish/v1/RawFruData/r001u01/PCIE_SLOT8`, `/redfish/v1/RawFruData/r001u01/PCIE_SLOT9`
- **csus3200_02**: `/redfish/v1/Managers/RMC/LogServices/RmcConfig/RawConfig`, `/redfish/v1/RawFruData/r001u01/PCIE_SLOT1`, `/redfish/v1/RawFruData/r001u01/PCIE_SLOT3`, `/redfish/v1/RawFruData/r001u01/PCIE_SLOT9`, `/redfish/v1/TaskService/Tasks/285c98658ca14dba83d662becbb72127/Monitor`, `/redfish/v1/TaskService/Tasks/7aae16ed3a4a413f9309862f0cc19ca2/Monitor`, `/redfish/v1/TaskService/Tasks/7d2077aa8eac43318ecbbd797039bcee/Monitor`, `/redfish/v1/TaskService/Tasks/9efba28dc57347ef8af05994580c491f/Monitor`, `/redfish/v1/TaskService/Tasks/bab3bef6f86b43fbbb0e17534ebe497a/Monitor`
- **csus3200_03**: `/redfish/v1/Managers/RMC/LogServices/RmcConfig/RawConfig`, `/redfish/v1/RawFruData/r001u01/PCIE_SLOT1`, `/redfish/v1/RawFruData/r001u01/PCIE_SLOT16`, `/redfish/v1/RawFruData/r001u01/PCIE_SLOT3`, `/redfish/v1/RawFruData/r001u01/PCIE_SLOT8`, `/redfish/v1/RawFruData/r001u01/PCIE_SLOT9`
- **dl380_gen12_01**: 없음
- **dl380_gen12_02**: 없음
- **dl380_gen12_03**: 없음
- **dl380_gen12_04**: 없음
- **sr650_v4_01**: `/redfish/v1/LicenseService/Licenses/{LicenseId}`
- **sr650_v4_02**: `/redfish/v1/LicenseService/Licenses/{LicenseId}`
- **sr650_v4_03**: `/redfish/v1/LicenseService/Licenses/{LicenseId}`
- **sr650_v4_04**: `/redfish/v1/LicenseService/Licenses/{LicenseId}`
