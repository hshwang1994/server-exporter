# ADR-2026-10-19 — ESXi 전원·온도·팬(vSphere 하드웨어 센서) · Linux iSCSI 이니시에이터 → `storage.hbas[]`

- 상태: Accepted (사용자 승인 2026-10-19 — "ESXi 전원·온도·팬 수집, Linux iSCSI HBA 수집 구현 승인")
- 범위: ESXi 채널 `data.power` · `data.thermal`(새 섹션 2개 success), Linux 채널 `storage.hbas[]` iSCSI 항목(+ Windows `iqn` 키), 공통 필터 `power_summary`
- 선행: `ADR-2026-10-19-csus-single-server-and-summary-fixes.md` 의 "노출 vs 요청" 범위 감사가 결정 항목으로 올린 두 원천(ESXi `runtime.healthSystemRuntime` 센서 126 · Linux iSCSI 이니시에이터)
- 정본: `docs/contract/03-fields.md` 6.3.1 · 6.5 · 6.7, `schema/sections.yml` · `schema/field_dictionary.yml`, `tests/evidence/2026-10-19-esxi-sensors-linux-iscsi.md`, `docs/ai/catalogs/EXTERNAL_CONTRACTS.md` 2026-10-19

## 컨텍스트 (Why)

- ESXi 봉투는 `sections.power` · `sections.thermal` 이 늘 `not_supported` 였다. 범위 감사가 vSphere 호스트 덤프 3대(Cisco TA-UNODE-G1 · ESXi 7)에서
  `runtime.healthSystemRuntime.systemHealthInfo.numericSensorInfo` 센서 126개(온도 28 · 팬 12 · 전력 12 · 전압 33 …)를 읽지 않고 있음을 드러냈다.
  이 섹션이 `success` 로 바뀌는 것은 호출자 계약 변화라 결정 항목으로 두었고, 사용자가 구현을 승인했다.
- Linux 는 `storage.hbas[]` 에 FC(`/sys/class/fc_host`)만 넣었고 iSCSI 이니시에이터는 어디에도 없었다. Windows(`MSFT_InitiatorPort` iSCSI) · ESXi(`iscsi_vmk` · `InternetScsiHba`)는 넣는다 —
  채널 간 뜻 차이였다. 사용자가 구현을 승인했다.

## 결정 (What)

1. **ESXi power/thermal 원천 = vSphere 하드웨어 센서** (`HostNumericSensorInfo`). 모듈 `esxi-gather/library/esxi_disks.py` 에 `sensors` 파트를 더한다(연결 1회 재사용, 다른 파트와 격리).
   항목 모양은 Redfish `gather_power`/`gather_thermal` 과 같다 — temperature → `temperatures[]`(`reading_celsius` = `currentReading×10^unitModifier` 반올림 · `health` green/yellow/red →
   OK/Warning/Critical(unknown → null) · `state Enabled` · `upper_critical null` · `physical_context` 는 센서 이름 앞 엔티티), fan → `fans[]`(`reading` · `reading_units` RPM),
   "Power Supply N" 이름의 power 센서 → `power_supplies[]` 1건(health 최악값 · 식별 · 용량 null), PSU 가 아닌 Watts 센서가 **정확히 1개**일 때만 `power_control.power_consumed_watts`.
   이름을 보는 곳은 그 둘뿐이고 그 밖의 추정은 하지 않는다(벤더 BMC 가 정한 IPMI 엔티티 표기라서). 전압 · ECC · 프로세서 상태 센서는 계약에 없어 내지 않는다.
2. **판정**: `systemHealthInfo` 가 없는 호스트(센서 공급자 CIM/IPMI 부재) → `not_supported`, 모듈 파트 실패 → `failed` + errors[] 2건, 그 밖 → `success`(센서 0건이어도 빈 목록).
   ESXi adapter 5종 `sections_supported` 에 power · thermal 추가, `supported_sections.yml` · `sections.yml` · 사전 `channel` 에 esxi 추가. 새 태스크 `esxi-gather/tasks/normalize_power_thermal.yml`.
3. **`power.summary` 는 공통 필터** `filter_plugins/power_summary.py` — Redfish `normalize_standard.yml` `_rf_power_summary` 와 같은 규칙(용량 모르면 null · Absent 제외 · redundant 는 수량).
   Redfish Jinja 는 그대로 두고 시험이 두 구현을 대조한다(한쪽만 바꾸면 막힌다).
4. **Linux iSCSI 는 sysfs 만 읽는다** — `/sys/class/iscsi_host/*`(initiatorname · ipaddress · hwaddress · netdev · port_state · port_speed) + `scsi_host/<host>/proc_name` + host 아래
   `session*/iscsi_session/<id>/{state,targetname,initiatorname}`. `iscsiadm` · `/etc/iscsi/initiatorname.iscsi` 는 root 가 필요하고 sysfs 는 누구나 읽는다(Linux 특권 최소 원칙).
5. **항목 1개 = 이니시에이터 포트 1개**: 소프트웨어 iSCSI(`iscsi_tcp`)는 세션마다 Scsi_Host 가 생기므로 (driver, iqn, hwaddress, netdev) 가 같은 host 를 1건으로 묶고 `session_count` 를 적는다;
   하드웨어 오프로드(bnx2i · qla4xxx · be2iscsi · cxgb4i)는 포트(hwaddress)마다 1건. `link_status` 는 `port_state LINK UP` 또는 로그인 세션 ≥ 1 → up, 그 밖 down(2026-10-19 up/down 2값 규칙).
6. **키**: canonical 6개(`wwpn`/`wwnn` 은 iSCSI 에 없어 null) + `iqn`(이니시에이터 IQN — FC 의 wwpn 자리) + Linux 전용 `host` · `ip_address` · `mac_address` · `netdev` · `session_count`.
   Windows 도 iSCSI 포트에 `iqn`(`MSFT_InitiatorPort.NodeAddress`)을 낸다. ESXi 는 `vmware_host_vmhba_info` 가 iSCSI 이름을 주지 않아 `iqn` 이 없다(후속, NEXT_ACTIONS).
   사전에 `storage.hbas[].iqn`(channel os) 1건 추가 — 다른 하위 키는 `storage.hbas[]` help 에 적는다.

## 결과 (Impact)

- **호출자 계약 변화(승인됨)**: ESXi 봉투 `sections.power` · `sections.thermal` 이 `not_supported` → `success`(센서 있는 호스트), `data.power` = `{power_supplies[], power_control{}, summary{}}`,
  `data.thermal` = `{temperatures[], fans[]}`. envelope 13 필드 · `status` 판정 규칙 불변. 실측 덤프 3대 재생: PSU 2 · `power_consumed_watts` 472/432/456 · `total_capacity_w null` · 온도 28 · 팬 12.
- Linux `storage.hbas[]` 에 iSCSI 항목이 들어간다(lab 호스트에는 iSCSI 세션이 없어 실호스트 값은 불변 예상). Windows iSCSI 항목에 `iqn` 키 추가(기존 키 불변).
- ESXi **실패 봉투**(rescue · Jenkins 합성 fallback)의 `sections.power/thermal` 도 `not_supported` → `failed` 가 된다 — adapter 가 지원하는 섹션이 됐기 때문이다. 세 사본(`supported_sections.yml` · `callback_plugins/json_only.py` · `scripts/jenkins/se_finalize.groovy`)과 finalize corpus 를 같이 바꿨다(시험이 셋을 맞춘다).
- `schema/baseline_v1/esxi_baseline.json` 은 다음 실장비 라운드(Jenkins ESXi 매트릭스)의 봉투로 갱신한다 — AI 임의 편집 금지(rule 21 R1).
- 센서 이름 의존(PSU 묶기 · 소비전력 1개 규칙)은 Cisco 1종 실측이다. Dell/HPE ESXi 호스트의 이름 체계("System Board Pwr Consumption" · "Power Meter" 등)에서 소비전력이 null 로 남을 수 있다 —
  `power_sensors[]`(모듈 결과, 봉투 밖)가 근거로 남으므로 실측 시 규칙을 넓힌다(추정으로 넓히지 않는다).

## 대안 비교 (Considered)

| 대안 | 평가 |
|---|---|
| `esxcli hardware ipmi sdr list` / `ipmitool` 로 센서 | SSH 또는 호스트 셸 전제 — ESXi 채널은 vSphere API 만 쓴다. 같은 센서를 API 가 준다 |
| 새 모듈 `esxi_health.py` | 연결 1회 더 · 접속 코드 중복. `esxi_disks.py` 는 이미 "호스트 정보 수집기" 로 확장돼 파트 격리(`_safe_build`)가 있다 → 파트 추가 |
| PSU 입력/출력 전력(PIN/POUT)을 PSU 항목에 싣기 | Redfish PSU 항목에 그 키가 없다 — 모양을 벌리지 않고 `power_sensors[]`(모듈 결과)에만 둔다 |
| `power_consumed_watts` = PSU PIN 합 | PIN 합(464 W)과 시스템 센서(472 W)가 다르고 벤더마다 PIN 이름이 달라 추정이 된다 → 시스템 Watts 센서 1개일 때만 |
| Linux `iscsiadm -m session -P 3` | root(iscsid 소켓) 필요. sysfs 가 같은 사실(세션 · 상태 · IQN)을 준다 |
| iSCSI 항목을 세션 단위(host 단위)로 | Windows/ESXi 는 이니시에이터(어댑터) 단위 — 소프트웨어 iSCSI 세션 3개가 항목 3개로 부풀어 채널 간 수가 어긋난다 → 묶는다 |
