# ADR-2026-10-19 — `storage.hbas[].link_status` 는 up/down 둘뿐 · ESXi hbas 는 vmhba 그대로 · Windows `system.version` 은 `연도-DisplayVersion`

- 상태: Accepted (사용자 결정 2026-10-19 — 긴급, production 반영 요청)
- 범위: 4채널 `storage.hbas[].link_status` · ESXi `storage.hbas[]` 항목 수 · Windows `system.version`
- 폐기하는 결정: `ADR-2026-10-18-hba-link-status-null-and-os-logical-volumes.md` 결정 1(미확정 → null) 과 결정 2 의 ESXi 부분(같은 (wwpn, wwnn) 1건),
  `docs/reference/decision-log.md` 2026-10-17 6항(Windows `system.version` 현행 유지)
- 정본: `docs/contract/03-fields.md` 6.3.1 · 6.3.2 · FAQ(Windows version) · `schema/field_dictionary.yml` `storage.hbas[].link_status` ·
  `docs/develop/05-field-mapping.md` · `tests/evidence/2026-10-19-hba-link-status-two-values-esxi-raw-windows-version.md`

## 컨텍스트 (Why)

- 사용자가 2026-10-19 에 "unknown 을 없애는 작업은 끝났나 — CSUS null 말고 up 을 모르는 것은 모두 down" 이라고 물었다. 현재 코드는 2026-10-18 결정 D2 대로
  키 없음 · 정규화 실패 둘 다 null 이었다. 그 차이를 보이자 사용자는 먼저 "키 없음만 null, 정규화 실패는 down" 을, 이어 **"null 이더라도 down 으로 통일 —
  무조건 값이 들어가도록, up · down 둘만 존재"** 를 결정했다. Portal 이 null 을 따로 해석하지 않아도 되게 하려는 뜻이다.
- 같은 대화에서 **"ESXi hbas 중복 제거는 없애고 있는 그대로 다 나오게"** 를 결정했다. 2026-10-18 에 ESXi 7 FC-NVMe 쌍둥이(포트당 SCSI vmhba + NVMe vmhba, 같은 WWPN)를
  1건으로 접었던 것이 "ESXi 8 vs Redfish 4" 의 설명이었지만, 사용자는 접은 결과보다 장비가 보여 주는 vmhba 목록 그대로를 원했다.
- "Windows 빌드에 날짜 추가" 는 `system.version` 이 `24H2` 로만 나오는 것을 `2025-24H2` 로 바꾸는 요청이었다. 2026-10-17 에는 "어떤 Windows API 도 그런 합성 문자열을
  주지 않으니 수집기는 그대로 내고 Portal 이 합친다" 로 결정했으나(03-fields FAQ), 사용자가 2026-10-19 에 수집기가 합성하도록 바꿨다.

## 결정 (What)

1. **`storage.hbas[].link_status` 는 항상 `up` 또는 `down`** — `null` · `unknown` 없음. `up` 은 장비가 링크 활성을 보고한 경우만, 그 밖은 전부 `down`
   (명시적 링크 없음 · 협상 중 · 관리상 offline · 진단/루프백 · **미제공(키/파일 없음) · 미확정 값(Unknown · null 값 · unbound · 미인식 문자열)**).
   사전 type 은 `string|null` → `string`(enum `up`/`down` 그대로). 채널별 매핑:
   - Redfish `_hba_link_status`: `LinkStatus` 가 up 으로 정규화되면 up, 그 밖 down. 키 없음은 `_hba_link_missing` → notice `링크 상태 미제공, down 으로 기록`,
     키는 있는데 up/down 이 아니면 `_hba_link_unresolved` → notice `링크 상태 값 미확정, down 으로 기록`(원문 포함). 고아 기능은 부모 포트를 상속하고 부모가 없으면 down + 미제공 notice.
   - Linux `port_state`: Online · Marginal → up, 그 밖(없음 · 읽기 실패 포함) → down. 읽기 실패는 종전처럼 errors[] attribute_unreadable 로 따로 남는다.
   - Windows: OperationalStatus 2 → up, 3~8 → down, 1/없음이면 MSFC PortState 2 만 up, 그 밖 → down.
   - ESXi `status`: online → up, 그 밖(offline · unbound · unknown · 없음) → down.
2. **ESXi `storage.hbas[]` 는 모듈(`vmware_host_vmhba_info`)이 준 FC/FCoE/iSCSI vmhba 를 있는 그대로 전부 낸다** — (wwpn, wwnn) 중복 제거 삭제. ESXi 는
   "항목 1개 = 물리 FC 포트 1개" 원칙의 예외(vmhba 1개 = 1건)이고, 교차 대조는 종전처럼 wwpn 집합으로 한다(`test_cross_channel_same_server.py` 불변).
3. **Windows `system.version`** 은 caption(없으면 `ansible_distribution`)의 `Server 20xx` 연도가 있고 DisplayVersion/ReleaseId 가 있으면 `<연도>-<DisplayVersion>`
   (`2025-24H2` · `2022-21H2` · `2019-1809`). 연도가 없는 클라이언트 Windows 는 DisplayVersion 그대로, DisplayVersion/ReleaseId 가 없으면 종전 폴백(`Win32_OperatingSystem.Version`) 그대로.
   `distribution` · `kernel` 불변. 다른 채널 `system.version` 불변.
4. 범위 밖(사용자 선택): `storage.infiniband[].link_status` · `network.*.link_status` 의 `unknown` 은 그대로.

## 결과 (Impact)

- envelope 13 필드 · `sections` · `status` 불변. 호출자가 볼 변화: `storage.hbas[].link_status` 에 `null` 이 더 이상 없다(HPE CSUS 3200 은 Redfish 에서 항상 `down`, notice `링크 상태 미제공` 으로 구분),
  ESXi 7 FC-NVMe 호스트의 hbas 가 포트당 2건, Windows Server 의 `system.version` 표기가 `2022-21H2` 형으로 바뀐다. Portal 안내는 NEXT_ACTIONS.
- 녹화본 golden 10종 중 `real_hpe_csus3200` 의 fc_hbas link_status 4건만 null → down. 다른 golden · 요청 집합 불변.
- lab 실장비 기대값: Cisco .2 hbas `up/up/up/down`(불변) · esxi02 FC 2건 `down/down`(불변, 쌍둥이 없음) · Windows .120 `system.version` `2022-21H2`(변경 — canary 로 확인, baseline 은 실측 뒤 갱신).
- 거짓 down 위험(사용자 수용): 장비가 Unknown 을 주거나 주지 않는 포트가 down 으로 보인다. Redfish 는 notice 로 흔적을 남기고, OS/ESXi 는 흔적을 남길 경로가 없다.

## 대안 비교 (Considered)

| 대안 | 평가 |
|---|---|
| 키 없음만 null, 정규화 실패는 down(사용자 1차 선택) | Portal 이 null 을 따로 해석해야 한다 — 사용자가 2차 결정으로 폐기 |
| 현행 유지(미확정 → null, ADR-2026-10-18) | 2026-10-19 사용자 재결정으로 폐기 |
| 미제공을 `unknown` 문자열로 | 2026-10-18 에 이미 폐지. 값은 up/down 둘만 두기로 했다 |
| ESXi 접기 유지 + 접힌 vmhba 를 notice 로 | 사용자가 "있는 그대로" 를 선택 — 접지 않으면 흔적도 필요 없다 |
| Windows version 은 그대로 두고 Portal 이 합성(2026-10-17) | 사용자 재결정으로 폐기 — 수집기가 합성한다. 연도 없는 클라이언트 Windows · 폴백 값은 합성하지 않아 추정이 들어가지 않는다 |
