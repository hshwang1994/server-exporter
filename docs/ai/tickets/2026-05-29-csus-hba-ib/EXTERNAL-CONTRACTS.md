# 외부 계약 evidence — CSUS 3200 / HBA / InfiniBand

> rule 96 R1-A: lab 부재 영역은 web sources 명시 의무. 본 문서는 2026-05-29 web-research (redfish-specialist / network-specialist / system-engineer agents) 결과를 정본화. adapter / 코드 origin 주석은 본 문서를 인용.

---

## 1. Redfish — FC HBA (`storage.hbas[]`)

**DMTF-first 수집 경로** (vendor-agnostic):

```
Chassis/<id>/NetworkAdapters/<na>        → model / Manufacturer / Controllers[].FirmwarePackageVersion
  └ NetworkDeviceFunctions/<ndf>         → 식별 (WWPN/WWNN)
        NetDevFuncType == "FibreChannel" | "FibreChannelOverEthernet"
        FibreChannel.WWPN | .PermanentWWPN
        FibreChannel.WWNN | .PermanentWWNN   (Lenovo/Supermicro 종종 null)
  └ Ports/<port> (신) | NetworkPorts/<port> (구)  → link/speed/protocol
        PortProtocol == "FC" | "FCP" | "FCoE"   ← FC 판정 정본 (PortType 아님!)
        LinkStatus (LinkUp/LinkDown/NoLink | 구: Up/Down)
        CurrentSpeedGbps | (구) CurrentLinkSpeedMbps / 1000
fallback: Systems/<id>/Storage/<ctl> StorageControllers[]
        SupportedDeviceProtocols contains "FC"
        Identifiers[] where DurableNameFormat == "FC_WWN"  → WWN
```

**[CRIT]** DMTF `Port.PortType` enum = `Upstream|Downstream|Interswitch|Management|Bidirectional|UnconfiguredPort` — **FC/IB 값 없음**. `port_type` 는 반드시 `PortProtocol` / `NetDevFuncType` 로 도출. 현 코드의 `'fibrechannel' in PortType` 는 dead code.

**필드 우선순위 (normalize)**:
- `wwpn` ← NDF.FibreChannel.WWPN ‖ PermanentWWPN ‖ StorageController.Identifiers[FC_WWN]
- `wwnn` ← NDF.FibreChannel.WWNN ‖ PermanentWWNN ‖ null
- `model` ← NetworkAdapter.Model ‖ StorageController.Model
- `vendor` ← NetworkAdapter.Manufacturer (vendor_aliases 정규화)
- `firmware` ← Controllers[].FirmwarePackageVersion ‖ StorageController.FirmwareVersion
- `link_status` ← Port.LinkStatus (정규화 up/down/no_link/null)
- `link_speed_gbps` ← Port.CurrentSpeedGbps ‖ NetworkPort.CurrentLinkSpeedMbps/1000
- `port_type` ← "FibreChannel" if PortProtocol∈{FC,FCP} ; "FCoE" ; else NDF.NetDevFuncType

**상시 null 가능 필드**: wwnn, link_status, link_speed_gbps (미연결/SFP 부재 시 정상 — error 아님).

**벤더 drift** (분기는 adapter YAML / vendors/ 안에서만 — rule 12 R1):
- Dell iDRAC: Systems + Chassis 양쪽 NetworkAdapters; FC HBA 가 StorageController 로도 노출; FCoE CNA disabled-partition WWPN null 버그.
- HPE iLO5(구): `NetworkPort` (Up/Down, CurrentLinkSpeedMbps); iLO6+: `Port`. Oem.Hpe.VirtualLinkStatus.
- Lenovo XCC: `Chassis/1/NetworkAdapters/{ob-X|slot-Y}/NetworkDeviceFunctions/{M.N}`, WWNN 종종 없음.
- Cisco CIMC: VIC vHBA (WWPN pool/SP 할당, PermanentWWPN 상이).
- Supermicro/AMI: 표준 tree 이나 FC NDF 희소 (대개 Ethernet 만).

**sources**: `Port.v1_9_0.json`, `NetworkDeviceFunction.v1_9_0.json`, `Protocol.json` (FC enum), `StorageController.v1_7_0.json`, `Resource.v1_19_0.json` (FC_WWN), HPE iLO5/6 resourcedefns, Lenovo XCC restapi, Dell iDRAC9 Redfish guide, Cisco IMC REST API guide. (전체 URL은 workflow 결과 / adapter origin 주석)

---

## 2. Redfish — InfiniBand (`storage.infiniband[]`)

```
Chassis/<id>/NetworkAdapters/<na>/Ports/<port>
        LinkNetworkTechnology == "InfiniBand"   ← IB 판정 정본 (PortType 아님!)
        CurrentSpeedGbps (200=HDR/NDR200, 400=NDR) / MaxSpeedGbps
        LinkStatus
        InfiniBand.AssociatedNodeGUIDs[] / AssociatedPortGUIDs[] / AssociatedSystemGUIDs[]
  └ NetworkDeviceFunctions/<ndf>
        NetworkDeviceTechnology == "InfiniBand"      ← (2026-10-17 정정) 이런 속성은 없다. 열거형 이름이다. 실제 속성은 NetDevFuncType
        InfiniBand.NodeGUID / PortGUID / SystemGUID (+ Permanent*)
        Links.PhysicalPortAssignment → Port join      ← 신 스키마는 Links.PhysicalNetworkPortAssignment (Port), 구는 PhysicalPortAssignment (NetworkPort)
```

**2026-10-17 추기 (InfiniBand 전면 검증 — ADR-2026-10-17-infiniband-port-decision.md)**: 판정은 `_ib_decision` 하나 — 포트의 현재 모드
(`Port.LinkNetworkTechnology` / `NetworkPort.ActiveLinkTechnology` / `Port.PortProtocol`) 와 연결 기능의 `NetDevFuncType`("configured capability").
둘이 충돌하면 IB 로 확정하지 않고 notice. `NetDevFuncCapabilities` · `Port.InfiniBand` 블록 존재 · GUID 존재는 근거가 아니다(VPI 카드의 Ethernet 모드).
`AssociatedNodeGUIDs/AssociatedPortGUIDs` 는 "lowest-numbered function · configured-but-not-active · teaming 주소" 를 함께 담을 수 있어(Port.v1_19_0
longDescription) 서로 다른 값이 하나일 때만 쓴다. 연결되지 않은 IB 기능은 항목이 아니다. 실 IB 모드 BMC 페이로드는 2026-10-17 기준 공개 mockup 0건 —
`tests/fixtures/redfish/synthetic_ib_mode` 합성.

**[중대 커버리지 갭]** 주류 enterprise BMC (Dell iDRAC / HPE iLO5-6 / Lenovo XCC) 는 add-in Mellanox IB HCA 를 Redfish 로 거의 노출 안 함 (capability flag 만). **표준 서버의 IB 정본은 OS 채널 (ibstat / sysfs)**. Redfish IB 는 NVIDIA BlueField/DPU 자체 BMC 에서만 실측 가능. → Redfish IB 는 best-effort, 미노출 시 `not_supported` + OS 채널 의존.

- Port.InfiniBand / NDF.InfiniBand 객체는 Redfish 2020.3+ schema. 구 펌웨어 미노출 → None 가드 필수 (rule 95 R1 #5/#12).
- `CurrentSpeedGbps` 숫자(Gbps)를 source-of-truth 로, HDR/NDR 라벨은 파생.

**sources**: Redfish 2020.3 release note, `Port_v1.xml` / `NetworkDeviceFunction_v1.xml` CSDL (DSP2053), NVIDIA BlueField BMC docs, iLO5/XCC resourcedefns (gap 증거), RHEL IB networking guide (OS fallback).

---

## 3. ESXi — FC HBA + InfiniBand

**현 채널 = 순수 vSphere API (community.vmware, SSH 없음)**.

- **FC HBA 정본**: `community.vmware.vmware_host_vmhba_info` → `vmhba_details[]` {device, driver, model, type, status, location, bus, **node_wwn, port_wwn, port_type, speed**} (뒤 4개 FC-only → `| default(none)`).
  - 분류: `type=='Fibre Channel'` 또는 driver∈{lpfc,qlnativefc,brcmnvmefc} → `hbas[]`; `iSCSI`/iscsi_vmk → `hbas[]`(subtype=iscsi); SAS/RAID(nhpsa,lsi_mr3,smartpqi,vmw_ahci) → `storage.controllers[]` (HBA 아님).
  - **현 코드 갭**: `port_type`/`speed` 드랍, `wwnn` 미보존. classification 의 `'infiniband' in type` 은 **dead code** (type 에 InfiniBand 없음).
- **InfiniBand**: ESXi 는 native IB 를 host adapter 로 노출 **안 함** (NVIDIA/VMware 공식: SR-IOV/passthrough-to-VM 만). ConnectX VPI(IB 모드) = `esxcli network nic list` 에 downed vmnic. → `storage.infiniband[]` 는 거의 항상 빈/추론. driver `^nmlx` NIC 로 best-effort 추론 entry 만 (note 명시).
  - **2026-10-17 정정**: 위 `^nmlx` 추론은 제거했다 — 네이티브 nmlx5 드라이버는 Ethernet 전용(NVIDIA ESXi 인박스 드라이버 RN), IB 모드 카드는 vmnic 없이 PCI `Infiniband controller`(class 0x0207) 로만 보인다(Broadcom KB 381748). `HostRdmaDeviceCapability` 에도 IB 플래그가 없다. 이 채널의 `storage.infiniband[]` 는 항상 `[]` 이다. `HostPciDevice.classId` 로 컨트롤러 존재만 적는 안은 `esxi_disks.py` 변경 + 새 필드가 필요해 보류(NEXT_ACTIONS §2.4).
- **raw esxcli** (`storage san fc list` / `rdma device list`) = SSH 필요. 현 설계는 API-only → **운영/보안 결정 사항** (rule 92 R1).

**sources**: community.vmware vmware_host_vmhba_info module docs, Broadcom esxcli reference, govmomi #1811 (WWN decimal int64), VMware IB-on-vSphere 백서, NVIDIA ConnectX VPI on ESXi.

---

## 4. Windows — FC HBA + InfiniBand

- **FC HBA 정본**: `Get-InitiatorPort -ConnectionType FibreChannel` (CIM `MSFT_InitiatorPort`, Win2012+, 무 role) → NodeAddress(WWNN)/PortAddress(WWPN)/PortType/OperationalStatus. **FC 필터 필수** (SAS/iSCSI 제외).
- **enrich (model/vendor/driver/firmware/speed)**: `root\WMI` legacy `MSFC_FCAdapterHBAAttributes` (Manufacturer/Model/Driver/Firmware/NodeWWN) + `MSFC_FibrePortHBAAttributes` (PortWWN/PortState/PortSpeed). HBA miniport driver 가 T11 FC-HBA API 등록 시만 존재 → try/catch + Get-CimClass 존재 검사. uint8[8] WWN → hex-join.
- **InfiniBand**: `Get-NetAdapter -IncludeHidden | ? {PhysicalMediaType -eq 'InfiniBand' -or NdisPhysicalMedium -eq 11}` (11=Infiniband; 9 아님). LinkSpeed→rate, Status→link_status. fallback `Get-PnpDevice -Class Net | ? HardwareID -match 'VEN_15B3'` (Mellanox). **node_guid 는 Windows 표준 API 부재 → null** (날조 금지, 갭 문서화).
  - **2026-10-17 정정**: PnP 폴백(`VEN_15B3` · 서비스명 `ibbus/ibal/ipoib`)은 제거 — 장치 상태 `OK` 를 링크 `up` 으로 적고 속도가 없었으며 2026-06-22 팀 멀티플렉서 오탐 경로였다. 2차 신호는 `Get-NetAdapterRdma` 의 `RdmaAdapterInfo.RdmaTechnology == 'InfiniBand'`(NDK `*NetworkDirectTechnology` 2 — iWARP 1 · RoCE 3 · RoCEv2 4 는 제외, Enabled 여부는 근거 아님). 속도 숫자는 `ReceiveLinkSpeed`(bps). `port` 는 null(물리 포트 번호 표준 API 없음). NVIDIA WinOF-2 known issue 1702662: WS2019 의 IPoIB NIC 는 물리 매체가 802.3 — 실장비 미확인(lab 부재). 팀 멀티플렉서 INF 는 `*PhysicalMediaType=14`, HWID `COMPOSITEBUS\MS_IMPLAT_MP`.
- 모든 probe = `Get-Command`/`Get-CimClass` 존재 검사 + try/catch → 부재 시 빈 list (graceful, Linux best-effort 동일).

**sources**: MS docs MSFT_InitiatorPort / Get-InitiatorPort / MSFC_FCAdapterHBAAttributes / MSFC_FibrePortHBAAttributes / MSFC_HBAPortAttributesResults / Get-NetAdapterRdma / OID_GEN_PHYSICAL_MEDIUM / Get-NetAdapter.

---

## 5. CSUS 3200 / Superdome Flex — Redfish topology

> 실 evidence: HPE Superdome Flex Server Administration Guide P/N 10-192008-Q123 의 **verbatim Partition0 ComputerSystem.v1_15_0 JSON**. CSUS 3200 = 동일 아키텍처/RMC/Redfish 후속 (Sapphire Rapids/DDR5/PCIe5/최대 16-socket).

```
/redfish/v1/Systems            → Members[] = Partition0..N  (전 Member 순회 — 현 adapter Members[0] 한계)
/redfish/v1/Systems/Partition<N>  ComputerSystem.v1_15_0
    SystemType == "PhysicallyPartitioned"   (현 fixture 'Physical' → 정정)
    ProcessorSummary / MemorySummary / Status / BiosVersion / UUID
    Processors / Memory / Storage / EthernetInterfaces / NetworkInterfaces  (전부 PER-PARTITION, 표준 DMTF)
    Links.Chassis[]  (다중 — 현 fixture None → 정정), Links.ManagedBy=[Managers/RMC], Links.ResourceBlocks[]
    Oem.Hpe (#HpeNpar.v1_0_0 — IPv4Addresses/OSType/OSVersion/ProductId/DCD/OV/SystemUsage) ← HPE OEM task 재사용
/redfish/v1/Systems/Partition<N>/Storage   표준 Storage{StorageControllers[],Drives[],Volumes}
    물리 현실: base IO = Intel RSTe SATA + 2~4 SATA SSD;  SAN-boot partition = FC StorageController + Drives[]=[]
    → mission-critical 박스는 storage+network 둘 다 빈 채로 두면 안 됨 (최소 FC HBA 노출)
/redfish/v1/Chassis/<id>   (id = 'r001u01b' 류 rack/U 인코딩 — 'Base'/'Expansion' 리터럴 아님)
    PCIeDevices[] / NetworkAdapters (물리) / PowerSubsystem||Power / ThermalSubsystem||Thermal
    NetworkAdapters/<n>/NetworkDeviceFunctions → FibreChannel.WWPN(→hbas) / InfiniBand.PortGUID(→infiniband) / Ethernet.MAC
/redfish/v1/Managers/RMC   (RMC = Redfish service host, NOT /Managers/1)  ManagerType / FirmwareVersion(3.x/4.x)
    + per-chassis BMC/RMP/PDHC (펌웨어별 노출 — 부재 graceful)
```

**핵심 교훈**:
- sdflexutils.System 은 sushy 표준 System subclass → Storage/Ethernet/Memory/Processors **표준 DMTF** (iLO SmartStorage OEM tree 아님). → 표준 collect 경로 재사용, Oem.Hpe(HpeNpar)만 OEM.
- Superdome Flex Grid 공유메모리 fabric (UPI 2.0 + ASIC crossbar) 은 **Redfish NetworkAdapter 로 안 보임** → IB 로 모델링 금지. IB 는 물리 ConnectX HBA 설치 시만.
- multi-CHASSIS (Links.Chassis count) ≠ multi-PARTITION (Systems Members count) — 독립. 단일 partition 이 다중 chassis 점유 가능.

**sources**: HPE Superdome Flex Admin Guide P/N 10-192008-Q123 (verbatim JSON), CSUS 3200 FAQ (Intel cdrdv2 792357), sdflexutils (github HewlettPackard), HPE SDF Architecture/RAS 백서, HPE support a00119177 (RMC Redfish), DMTF DSP2046 2024.2, OpsRamp SUS3200 monitoring.

**DRIFT 추적**: Manufacturer/Model/firmware/Chassis ID 문자열은 사이트 실측 시 정정 (rule 25 R7-A-1). 사이트 fixture 캡처 + 실 baseline 교체 = NEXT_ACTIONS (rule 96 R1-C).
