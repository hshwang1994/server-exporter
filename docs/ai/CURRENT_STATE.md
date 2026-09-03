# server-exporter 현재 상태

## 일자: 2026-09-03 — reachable 판정에 ICMP Echo OR 조건 추가 (사용자 지시)

> 결정 근거: `docs/ai/decisions/ADR-2026-09-03-icmp-or-reachability.md`,
> `docs/reference/decision-log.md` 2026-09-03. 후속: `docs/ai/NEXT_ACTIONS.md` RE-1~RE-4.

- **도달성 = 관리 TCP 응답 OR ICMP Echo 응답.** `precheck_bundle._resolve_reachability` 가 정본.
  TCP 를 먼저 보고 **전 포트 무응답일 때만** ICMP Echo 1회(`icmp_check`, `ping` 명령)를 확인한다.
  TCP 가 응답하면(연결 성공/RST) ICMP 는 호출조차 되지 않는다 — 성공·RST 경로 예산 증가 0.
- **ICMP 는 Gate 가 아니다.** 무응답 / 차단 / `ping` 부재 / 권한 부족을 "근거 없음" 하나로 취급해
  판정이 종전(TCP 전용)과 같아진다. ICMP 전용 `failure_code` / `failure_stage` 없음.
  `icmp_probe=false`(`_precheck_icmp_probe`)로 완전히 끌 수 있다.
- **failure_code 9개** (8 → 9): `TARGET_UNREACHABLE` 신설(`stage=reachable`, TCP·ICMP 모두 무응답),
  `TCP_CONNECT_FAILED` 는 `stage=port` 로 범위 축소(ICMP 는 응답, 관리 TCP 만 무응답 — 방화벽 DROP).
  문장 매핑: `TARGET_UNREACHABLE`→1번(종전과 동일), `TCP_CONNECT_FAILED`→**2번으로 이동**
  (ICMP 로 존재가 확인된 대상에게 "IP 사용 여부" 를 묻지 않는다). 표준 5문장 집합은 불변.
- **envelope shape 불변**: 최상위 13 필드 / `diagnosis` 7키 + `details` 그대로. ICMP 관측 근거는
  `errors[].detail` 문자열에만 붙는다 (`icmp: Echo Reply 확인` / `icmp: 응답 없음 (rc=1)`).
- 변경 파일: `common/library/precheck_bundle.py`(+163줄), `common/tasks/precheck/run_precheck.yml`,
  `schema/field_dictionary.yml`(enum + help), `common/vars/failure_reasons.yml`(매핑 주석),
  3 channel `site.yml`(주석만), rule 27 / rule 10 / `CLAUDE.md` §7 §9, `docs/contract/{02,03,04}`,
  `docs/overview/02-architecture.md`, `docs/develop/06-debugging.md`.
- **회귀**: `tests/unit/test_precheck_icmp_reachability.py` 신설(24), 기존 precheck 하네스 10곳은
  `tests/precheck_stub.py` 로 ICMP 결과 주입(실 `ping` 금지). 전체 **3312 passed / 0 failed**.
- **실장비 검증 완료**: Jenkins `clovirone-server-gather` #200(`os`: .163/.145/.120) + #201(`redfish`: .145),
  둘 다 체크아웃 `1fd9fa6d` 확인. `.163` = `TARGET_UNREACHABLE`, redfish `.145`(ICMP 응답 + 443 DROP) =
  `reachable=true` / `stage=port` / `TCP_CONNECT_FAILED` / 2번 문장. `.145`(os) `.120`(Windows, **ICMP 차단**) 은
  vault 자격증명까지 태운 **실수집 success** — ICMP 가 Gate 가 아님이 end-to-end 로 확인됐다.
  에이전트 `ping` 은 `cap_net_raw=ep`, `ping_group_range = 1 0` (비특권 소켓 방식이었으면 실패했을 조건).
  dead host 예산 +1.0~1.1초/대. 증거 `tests/evidence/2026-09-03-icmp-reachability-live.md`.
  남은 것은 Portal 소비자 이행(RE-4) 하나다.

## 일자: 2026-09-03 — OS(Linux/Windows) / ESXi 게더링 전수 검수 후속 (37건 정정, Redfish 제외)

> 결정 근거: `docs/reference/decision-log.md` 2026-09-03 항목. 후속: `docs/ai/NEXT_ACTIONS.md` GA-1~GA-6.

- **hostname 계약**: `system.hostname`(짧은 이름) + `system.fqdn`(hostname + 설정 도메인, 없으면 null).
  Linux `uname -n`/`hostname -d`, Windows `DNSHostName` + AD 도메인/DNS 접미사, ESXi `dnsConfig.hostName/domainName`.
  IP 대체는 rescue(`build_failed_output.yml`) 와 `always` 최종 fallback 까지 제거 — `hostname: null` + `hostname_source`.
- **Linux 는 raw 명령 단일 구현**: `gather_system/cpu/memory/storage/network.yml` 을 다시 썼다. setup fact 는 system 필드
  1순위로만 쓰고 hardware/cpu/memory/storage/network 는 raw 명령(dmidecode/lscpu/lsblk/df/ip) 결과를 python·raw 공통 판정식으로
  만든다. `gather_runtime.yml` 은 삭제 (runtime 이중 구현 제거). hardware 섹션(vendor/model/serial/uuid/bios) 을 낸다.
- **Windows**: `gather_system.yml`(hostname/fqdn/kernel/version/architecture/hosting_type — OEM 목록 없음),
  `gather_hardware.yml`(sku, 수집 판정), `gather_cpu.yml`(캐시 0→null, turbo null), `gather_memory.yml`(JEDEC, null 정합),
  `gather_storage.yml`(int MB, 시리얼 디코딩 조건 강화, health OK/Warning/Critical, IB 벤더),
  `gather_network.yml`(id=어댑터 이름, IPv6, adapters[], MAC 정규화), `gather_runtime.yml`(단일 구현, tri-state, rescue all-null).
- **ESXi**: `esxi_disks.py` 에 `host_info` 파트(dnsConfig / ipRouteConfig / vnic IPv6 / pnic↔pciDevice / cpuInfo.hz / uptime).
  `normalize_system.yml`(hostname/fqdn/정격 클럭/arch 추론/uptime null), `normalize_network.yml`(gateway/is_primary/IPv6/MAC),
  `normalize_storage.yml`(summary = LUN 기준), `collect_runtime.yml`(gateway 경로 제거, `.get()|default` None 버그 제거,
  ntp_synchronized null, firewall enum), `collect_network_extended.yml`(adapters 키 통일, WWN 정규화, HBA vendor).
- **공통**: `common/tasks/normalize/resolve_vendor.yml` 신설(envelope.vendor 단일 경로, 미등록 제조사 null),
  `build_failed_output.yml`(성공 섹션 보존 + partial, hostname 체인, correlation 파생), `build_correlation.yml`(uuid 정규화),
  `filter_plugins/identity_normalizer.py`(normalize_mac / normalize_wwn / normalize_uuid / uuid_byteswap / uuid_equal),
  `supported_sections.yml` + `adapters/os/*.yml` + `schema/sections.yml` 에 hardware(os).
- **schema**: `field_dictionary.yml` +16 항목 / channel·enum 정정 (Must 52 / Nice 134 / Skip 6 = 192), `fields/{common,os,esxi}.yml`,
  `examples/os_partial.json` 정정(hostname IP / bare_metal / uid int / 10 섹션).
- **실장비 검증 완료 (같은 날, Jenkins #190~#196)**: RHEL 8.10 raw fallback / RHEL 9.6 / Dell R760 베어메탈 / Windows Server 2022 /
  ESXi 7.0.3 ×2 — 전부 `status=success`, 자동 계약 점검 이슈 0. 실장비에서만 드러난 6건은 같은 날 후속 커밋으로 정정했다:
  `0076ca67`(SMBIOS Current/Max Speed 3순위 클럭 fallback, Windows 팀 멤버 MAC·IPv6 zone, ESXi cpu_mhz 반올림·vmk link_status 근거),
  `d38bc31b`(정격보다 낮은 터보는 null). 무응답 장비(.163)의 실패 envelope 도 새 계약대로 나왔다.
  증거: `tests/evidence/2026-09-03-os-esxi-live-verification.md` (+ `2026-09-03-live/*.json`).
- **남은 것**: baseline 10건 미재생성 — `schema/baseline_v1/README.md`(수정 금지) 와 rule 13 R4(실장비 검증 후 갱신) 가 충돌해
  **사용자 결정 대기** (갱신용 원본 envelope 은 evidence 디렉터리에 있다). lab 목록의 .167/.169 는 Ubuntu/Rocky 가 아니라 RHEL VM 의
  bond IP 였다 (목록 정정 필요). `ansible-playbook --syntax-check` 로컬 미실행은 Jenkins Agent 실행으로 대체됐다.

## 일자: 2026-09-01 — OS Windows 자격증명 교체 (git 제외 3 Location)

- 사용자 지시로 `vault/{chj,ic,yi}/os/windows.yml` 의 Windows 계정을 교체했다.
  username 을 `administrator` 로, password 를 사용자 제공값으로 바꿨다.
  **`vault/git/os/windows.yml` 은 지시대로 건드리지 않았다** — 이 파일은 이미
  `administrator` 를 쓰고 있고 password 는 별개 값이라 3 Location 과 다르다.
- `locations.yml` 정본이 정의한 Location 은 `chj / git / ic / yi` 4개다.
  `git` 을 뺀 나머지가 정확히 3개이므로 대상 누락은 없다
  (`resolve_credential_scope()` 로 4 Location 전수 경로 판정 확인).
- **평문 구조는 이전과 같다.** `accounts[]` 1개(label `windows_current`, role `primary`)
  + legacy `ansible_user` / `ansible_password` 동기. 값만 바뀌었고 키 추가·삭제 0.
  `normalize_accounts()` 가 이전과 같이 후보 1개를 돌려준다.
- 코드·schema·envelope 무변경이다. Windows 계정 이름을 쓰는 코드가 없기 때문에
  (자격은 전부 vault → `_cred_accounts` 경로로만 흐른다) 분기 영향도 0이다.
- 검증: `vault_decrypt_check.py` 로 vault 49개 전량 복호화 + 구조 검증 통과(exit 0).
  변경 3파일은 기록 후 디스크에서 다시 읽어 복호화 대조까지 했다.
  `git diff --stat -- vault/git/` 0 으로 제외 대상 불변을 확인했다.
- **이 세션에서 못 한 것**: 실 Windows 호스트 WinRM 인증은 시도하지 않았다. 대상 장비에
  `administrator` 계정과 새 password 가 실제로 존재하는지는 저장소 밖 사실이다.
  Jenkins 로 os 채널을 한 번 돌려 `used_label=windows_current` / `fallback_used=false`
  를 확인하기 전까지 실장비 검증은 미완이다.
- `vault/.lab-credentials.yml` 은 손대지 않았다. gitignore 대상이고 vault resolver 가
  읽지 않는 lab 대상 목록이라 이번 계정 교체와 축이 다르다.

## 일자: 2026-08-27 — OS 채널 CSUS 3200 nPartition 시리얼 접미사 정규화

> 후속: `docs/ai/NEXT_ACTIONS.md` CSUS-OS-1

- HPE Compute Scale-up Server 3200 은 OS 안에서 읽는 SMBIOS Type 1 System Serial 이
  `<물리 시리얼>-<파티션번호 3자리>` 형식이다 (`SGHD3TLNDD-000`). 자산 관리 시스템은 물리
  시리얼(`SGHD3TLNDD`)로 서버를 관리하므로 그대로 내보내면 같은 서버가 다른 시리얼로 판정된다.
  **OS 채널에서만** 접미사를 뗀다.
- 새 필터 `filter_plugins/serial_normalizer.py` 하나에 벤더 지식을 모았다.
  `normalize_os_serial(serial, vendor, model)` 은 **세 조건을 모두** 만족할 때만 값을 바꾼다:
  vendor 가 HPE alias 완전 일치 · model 이 CSUS 3200 패턴 매칭 · 시리얼이 `-[0-9]{3}` 로 종료.
  하나라도 어긋나면 입력을 **글자 그대로** 돌려준다. `split('-')[0]` 같은 절단은 쓰지 않는다.
- 호출부 3곳(`linux/gather_system.yml`, `windows/gather_system.yml`,
  `windows/gather_hardware.yml`)은 필터만 부르고 vendor 이름을 모른다 — rule 12 R1 유지
  (`verify_vendor_boundary.py` 기본 모드 위반 증감 0).
- vendor / model 은 시리얼과 **같은 원천**에서 읽는다. Linux = DMI `sys_vendor` /
  `product_name` (setup fact → raw 경로 동일 sysfs), Windows = `Win32_ComputerSystem`.
  둘 다 판정에만 쓰는 task 범위 변수다 — **envelope 필드 추가 0, schema 변경 0**.
- 필터 안의 alias / model pattern 은 저장소 정본(`common/vars/vendor_aliases.yml`,
  `adapters/redfish/hpe_csus_3200.yml`)의 미러이고 drift 가드 테스트가 상시 비교한다.
- Redfish / ESXi 채널은 무변경이다. Redfish `data.hardware.serial` 은 여전히
  `Systems/Partition0.SerialNumber` 원문(`SGHD3TLNDD-000`)이다
  (`docs/ai/contracts/serial-number.md` 29-6). 즉 같은 장비를 OS 로 보면 `SGHD3TLNDD`,
  Redfish 로 보면 `SGHD3TLNDD-000` 이다 — 요구 범위가 OS 채널이라 의도된 차이다.
- **아직 확인 못 한 것**: CSUS 3200 의 **OS 측 DMI 값**(`sys_vendor` / `product_name`)
  실측이 없다. 모델 패턴은 2026-06-15 사이트 실 4노드 Redfish 미러 캡처의 표기를 그대로 썼다.
  사이트 DMI 표기가 다르면 패턴 미매치 → **정규화가 일어나지 않는다**(무해한 no-op).

## 일자: 2026-08-14 — Location ID `ich` → `ic` 개명

> 후속: `docs/ai/NEXT_ACTIONS.md` LOC-1 ~ LOC-3

- Location ID 를 `ich` 에서 `ic` 로 바꿨다. `agent_label` 도 같이 `ic` 로 맞췄다
  (사용자 결정 — 두 값을 분리해 둔 설계상 유지도 가능했으나 맞추기로 했다).
- 실제 변경은 셋뿐이다: `vault/ich/` → `vault/ic/` 디렉터리 rename(내용 무변경),
  `common/vars/locations.yml` 의 키와 label, 그리고 예시 문자열. **코드 분기는 0줄 바뀌었다** —
  Location 목록 정본이 `locations.yml` 하나라서 나머지는 전부 주석·문서·테스트 샘플값이다.
- 4 Location (`ic / chj / yi / git`) × 12 = 48개 + 전역 표준 1개 = 49개 vault 구성 유지.
  `vault_decrypt_check.py --layout-only` 로 `ic: 12/12 존재` 확인.
- **아직 반영 안 된 것**: Jenkins 노드의 실제 Labels 는 `ich` 다. 재설정 전까지 `loc=ic` 잡은
  Agent 를 못 잡는다. 호출자가 보내는 `loc` 값도 함께 바뀌어야 한다 (저장소 밖 작업).
- 과거 evidence 의 `ich` 문자열도 사용자 결정으로 함께 치환했다. 단
  `tests/reference/esxi/10_100_64_2/` 의 `nexus-ich` 는 실제 ESXi VM 이름이라 그대로 뒀다 —
  Location 참조가 아니고, 실측 덤프의 장비 사실을 고치면 fixture 가 거짓이 된다.

## 일자: 2026-08-13 — 9 Vendor 조사 반영: 계정 쓰기 계약 정합

> 정본: `tests/evidence/2026-08-13-account-write-contract-alignment.md`
> 계획: `docs/ai/contracts/redfish-account-write.md`

- blind write fallback 을 전부 걷어냈다. `PasswordChangeRequired` 를 덧붙여 다시 POST 하던
  경로와 거부 속성을 빼고 재PATCH 하던 사다리를 제거했다. 무엇을 보낼지는 쓰기 전에
  Family Property Contract 가 정한다. 응답을 보고 정하는 방식이 아니다. 허용되는 다중 쓰기는
  ETag 412 재시도(동일 URI·동일 payload)와 HPE 의 사전 확정 sequence 둘뿐이다.
- Property Contract 를 데이터로 만들었다. Family × Operation 별로
  `writable / read_only / verify_only / unsupported / unverified`. **표에 없는 Property 의
  기본값은 `unverified` 이고 자동으로 쓰지 않는다**. 모르는 속성을 writable 로 가정하는 일은 없다.
- Dell 정책 거부를 200 응답에서 잡는다. `RelatedProperties` / `Severity` 를 읽어 SYS474 류를
  포착한다. 같은 응답에 `Base.1.12.Success` 와 `SYS413` 이 함께 오기 때문에 "성공 메시지가 있으니
  성공" 도 "HTTP 200 이니 성공" 도 성립하지 않는다.
- HPE 는 Family 를 쪼개지 않고 근거만 분리했다. 쓰기 동작(Password 단독 PATCH)은 iLO5/6/7
  동일하다. Evidence 만 `live_proven`(iLO6 1.73) / `advisory_derived`(1.74·iLO7 1.19·1.20) /
  `safety_strategy`(iLO5·1.75+·1.21+) 로 갈린다. **한 대의 실측이 세대 전체로
  번지지 않는다.**
- 보호 계정 판정 축을 바로잡았다. 이제 DMTF `HostBootstrapAccount` Property 를
  본다(실미러 10.50.11.232 에 존재하므로 XCC3 전용 개념이 아니다). slot 번호는 판정 근거에서 뺐다.
  열거·진단에는 남기고 후보에서만 제외한다. 표준 계정 이름이 겹치면 `protected_conflict` → Write 0.
- Family 세분화: Lenovo XCC2/XCC3(PCR 계약 차이), Cisco IMC 3.x(Instance POST),
  QCT 3 Family(동작 동일·경계 기록), Supermicro Superchip 경계. Supermicro Create URI 는
  **장비값으로 Generation+Firmware 를 확정했을 때만** 최신 계약으로 전환한다.
- 진단 축 추가: Huawei 계정별 Redfish Login Interface(읽기 전용), HTTPBasicAuth/AuthMethods,
  `policy_conflict`, 계정 잠금 전 검증 중단, 미지원 RoleId. 전부 진단만 하고 정책은 그대로다.
- 실장비를 재검증했다. git 4대 × (Check Mode + 1차 + 2차) 전부 `success` / `used_role=primary` /
  **Account Write 0**. Create / Repair 는 조건이 발생하지 않아 이번에도 미증명이다.
- 테스트: **3063 passed** (종전 2843 → +220). 계약 불변식 146건을 Family 표 전수로 고정.
- envelope 13 필드 불변 — 신규 진단은 전부 `diagnosis.details.account_service` 하위.

## 일자: 2026-08-12 (r) — 표준 비밀번호 회전 수렴 + Repair 실증 + 평문 Secret 정리

> 정본: `tests/evidence/2026-08-12-standard-password-convergence.md`,
> `tests/evidence/2026-08-12-plaintext-secret-sanitization.md`

- 전역 표준 계정 비밀번호를 회전하고 git Redfish 4대에 수렴시켰다. Credential Contract
  불변: 전역 표준은 `vault/common/redfish/standard.yml` 1벌, Vendor Vault 는 recovery 전용,
  최종 수집은 표준 계정. Vault 49개 decrypt/YAML 전량 성공, Redfish `role: primary` 정확히 1개.
- 1·2차 실행 모두 4대 전부 `status=success` / `used_role=primary` / `attempts=1` /
  **Account Write 0**. Password Convergence 성공.
- Repair 경로 첫 실장비 완주 (Lenovo XCC): 표준 401 → recovery 인증 → `present` →
  `patch_existing` → `write_accepted` → **표준 자격 재인증 성공(`verification=verified`)** →
  표준 계정으로 수집 → 2차 실행 Write 0. Case B 를 `PROVEN` 으로 올렸다.
- Dell Password Strength HOLD → CLOSED. 회전된 값으로 1·2차 표준 인증 성공 + Write 0.
  BMC 정책은 건드리지 않았다. 다만 "Dell 은 선언된 규칙만으로 수용 여부를 알 수 없다"는
  계약은 유효하게 남긴다 (`Security.1.MinimumPasswordScore` 만 활성).
- HPE iLO 쓰기 계약 결함을 발견하고 수정했다. 실장비 통제 실험으로 확정: iLO 는 `Password` 가
  다른 속성과 같은 PATCH 에 오면 **검사도 적용도 하지 않고 버리면서 200 `AccountModified`
  를 준다.** 같은 잘못된 값이 단독일 때는 400 으로 걸린다. 응답으로는 구분 불가라
  Family 가 쓰기 전에 방식을 정해야 한다 → `hpe_ilo5plus.isolated_write_patch = True`.
  부수 2건도 고쳤다: `Locked` 를 실제 잠김일 때만 전송(쓰기 1회 감소),
  재인증 간격을 장비 선언값(`AuthFailureDelayTimeSeconds`)에서 산출.
  검증 의무화(audit H-1)가 없었다면 이 결함은 "쓰기 성공"으로 보고됐을 것이다.
- Dell 세대 판정 버그를 수정했다. `10.100.15.34` 는 iDRAC9(FW 7.10.70.00)인데 Family 가
  `dell_idrac10_slot_patch` 였다. 원인은 adapter 오선택(무인증 probe → fact 없음 →
  priority 로 결정) + 그 hint 를 세대 근거로 그대로 사용(`Manager.Model` 조건은 Dell 에서
  죽은 조건). `reserved_slot_ids` 가 `{1}` vs `{1,2}` 라 빈 슬롯이 2번일 때 PATCH 대상 URI 가
  갈린다. **이름만의 차이가 아니다.** 세대 근거를 Firmware major 로 교정.
  Adapter 오선택 자체는 별도 과제로 남았다(NEXT_ACTIONS PWC-4).
- 저장소 평문 Secret 을 전량 제거했다. tracked 391개 파일에 실 자격증명 10종이 평문으로
  있었다(이번 cycle 이 만든 것이 아니라 사전 존재). 그중 8개가 누출 방지 테스트 자신
  이었다. 가드를 sha256 digest 대조로 바꾸고(`tests/secret_guard.py`) 입력 자격은 합성
  canary 로 교체했다. tracked 17,982개 전수 검사 **digest 0건 / literal 0건**.
  Secret Leak Gate(`scripts/ai/verify_no_plaintext_secret.py`) 신설.
  Git history 와 rotation 은 사용자 지시(§12/§13)로 범위 밖 — NEXT_ACTIONS PWC-1/2.
- 테스트: unit+regression 2007 / e2e 590 / integration 243 = **2840 passed**. 게이트 전량 통과
  (3채널 syntax-check 포함).

---

## 일자: 2026-08-12 (q) — Credential Vault 정리 + git Location 실장비 검증

> 정본: `tests/evidence/2026-08-12-git-location-live-verification.md`

- Vault 26개를 갱신했다. 사용자 제공 Credential 을 기존 Schema 그대로 반영했다.
  표준 계정은 `vault/common/redfish/standard.yml` 1벌, Redfish vendor vault 36개는
  전부 `role: recovery` 단독. 사용자가 제공하지 않은 20개 파일은 확인만 하고 변경 0.
  `vault_decrypt_check.py` 전량 통과(마스터 키 제공, exit=0).
- 후보 정리에는 부수 효과가 따랐다. git Dell 4→1 / Lenovo 3→1 / HPE 3→1 후보. 실측에서 전 채널
  `attempted_count=1`, `fallback_used=false`. 실패 인증 0회로 lockout 위험이 줄었다.
- git Location 실장비 7대상 검증 (WSL ansible-core 2.20.7, production 과 동일 호출).
  Linux 10.100.64.161 / Windows 10.100.64.120 / ESXi 10.100.64.1 / Lenovo 10.50.11.232 /
  HPE 10.50.11.231 / Cisco 10.100.15.2 / Dell 10.100.15.34.
  - OS·ESXi 3대: `success`, scope `git/os/{linux,windows}` · `git/esxi`, used_role=primary
  - Redfish Lenovo·HPE·Cisco: `success`, `credential_scope=common/redfish/standard`,
    used_role=primary, Account Write 0. Lenovo·Cisco 는 **2차 실행도 Write 0** 확인
  - Dell: 표준 401 → 복구 인증 성공 → `presence=present` → `patch_existing` →
    `Locked` read-only 재시도 → 비밀번호가 Security Strengthen Policy 로 거부 →
    `verification=failed`. **계정 상태 변화 0건**(16 slot 전수 전후 비교)
- Family 판정이 Adapter 오선택을 이겼다. Cisco 10.100.15.2 는 adapter 가
  `redfish_cisco_ucs_xseries` 를 골랐지만 장비가 노출한 Roles 어휘
  (`admin/user/readonly/SNMPOnly`)를 근거로 `cisco_cimc_collection_post_id` + `RoleId=admin`
  으로 확정했다. "실제 Capability > Adapter hint" 설계가 실장비에서 동작한다.
- Dell 비밀번호 거부 원인을 규명했다. 길이/대문자/숫자/특수문자/정규식 규칙이 전부 비활성
  (`PasswordMinimumLength=0`, `Require*=Disabled`, `Regex=""`, `MaxPasswordLength=127`)인데도
  거부된다. 남은 강제 조건은 `Security.1.MinimumPasswordScore="Weak Protection"` 하나이며
  Registry 가 이를 *"Password must have this minimum strength score"* 로 정의한다.
  → 규칙이 아니라 **강도 점수(사전/패턴 기반)** 검사가 원인일 가능성이 높다(LIKELY).
  점수 산출 알고리즘·검증 endpoint 는 노출되지 않아 확정 불가(UNKNOWN).
- lockout 예산을 실측했다. Dell 실패 경로에서 `auth_budget={'infraops': 3}`. 종전 구조라면
  최대 9회였고 Dell IP Blocking 기본값(FailCount 3 / FailWindow 60s)을 넘겼을 값이다.
- Compatibility Matrix 를 갱신했다. `hpe_ilo5plus` / `lenovo_xcc_accounttypes` /
  `cisco_cimc_collection_post_id` 3 Family 를 Case A 한정 `PROVEN` 으로 승격
  (검증된 Model+Firmware 범위만). Dell iDRAC9 는 `HOLD`.
  **Account Create 경로는 여전히 어느 Family 에서도 실장비 미증명**. git 4대 모두 표준
  계정이 이미 존재해 `presence=absent` 조건이 발생하지 않았다.
- Production 승격 없음 (사용자 지시).

## 일자: 2026-08-12 (p) — Redfish 계정 Reconcile: Capability Discovery + Family Strategy

> 정본 기록: `tests/evidence/2026-08-12-redfish-standard-account-final-compatibility.md`
> 매트릭스: Vendor × Family 매트릭스
> 결정: `docs/ai/decisions/ADR-2026-08-12-account-family-strategy.md`

9 Vendor 공식조사 9건 + AS-IS 감사를 현재 HEAD 와 대조해 남아 있던 결함을 처리했다.

- C-1 (CRITICAL) 해소 — 계정 열거를 `complete/incomplete/failed` 3-상태로, 존재 판정을
  `present/absent/unknown/ambiguous` 4-상태로 만들었다. Accounts 컬렉션 403/5xx/timeout /
  링크 부재 / member 일부 실패 / `Members@odata.count` 불일치는 전부 `unknown` 이고
  **`unknown` 에서는 Account Write 0건**이다. 종전에는 이 상태가 "계정 없음" 이 되어 실제
  생성 POST 가 나갔다(감사가 production 함수를 실행해 증명).
- C-2 해소: `site.yml` 의 `_rf_auth_rejected` 분모를 `_rf_accounts`(표준+복구 병합) →
  `_rf_standard_accounts` 로 교정. 종전 구조에서는 복구 후보가 있으면 `auth_success` 가
  영영 false 로 확정되지 못했다. **정확히 reconcile 이 가능한 상황에서만 진단이 비는** 셈이었다.
- H-1 은 모든 쓰기 경로에 재조회(`_confirm_account_state`) + 표준 자격 재인증을
  의무화해 해소했다. Ansible 게이트를 `verification == 'verified'` 로 좁혔다(종전은 `'none'` 도 성공).
- H-2 는 `module.check_mode` 를 dryrun 에 OR 해서 해소했다. `--check` 가 실제 PATCH/POST 를
  내보내던 결함이 닫혔다.
- H-3 해소를 위해 `account_service_discover()` 를 신설했다. ServiceRoot 링크 추종(AccountService URI
  하드코딩 제거), Accounts/Roles URI, Password·Lockout 정책, AccountTypes, Manager Firmware
  까지 **읽기 전용**으로 확보한다. 생성 POST URI 하드코딩 5곳도 discovery 결과로 교체.
- Family Strategy 도입: vendor 이름 분기 + 실패 시 payload 사다리(무작위 Write fallback)
  제거. 읽기로 Family 를 확정하고 검증된 방식 하나만 실행한다. 판정 근거 우선순위는
  실제 Resource Capability -> Vendor -> BMC Family -> Firmware -> Generation -> Adapter hint.
  주요 교정: Lenovo Purley = 빈 slot PATCH(POST 아님), Cisco RoleId 는 Roles 어휘에서 선택
  (전 Cisco `admin` 고정 remap 제거), HPE iLO4 `Oem/Hp`, HPE CSUS/Superdome 을 iLO 로
  처리하지 않음, Supermicro 계정분리 세대는 AccountTypes/Firmware 로 판정,
  Inspur `Oem.Public.Status` + Family gated If-Match, Dell iDRAC10 reserved slot 2.
- Lockout: Dell 생성 슬롯 순회 3->1, 표준계정 실패 인증 최대 9회->3회, 후보 간 backoff 는
  **401 일 때만** 65초(설정 가능)로 확대하고 transport 오류는 종전 5초 유지.
- UNVERIFIED Family 는 현행 유지 (사용자 결정) — Fujitsu / Quanta / X-Series / IMM2 /
  Supermicro X9 / Inspur M5·M7 / HPE RMC 는 generic POST 경로와 400/405 retry 를 그대로 둔다.
- 실장비 미러 재생을 신설했다. `tests/reference/redfish/**` 를 읽는 테스트가 0건이던 것을
  (감사 D-8) `tests/integration/test_account_reconcile_replay.py` 로 연결했다. Dell 5 / HPE 1 /
  Lenovo 1 / Cisco 1 호스트 실응답으로 읽기 단계를 검증한다 (43 tests).
- 테스트 2694 -> 2794 passed (실패 0). unit+regression 실행 66.6s -> 18.1s (M-9 부수 효과).
- envelope 13 필드 / sections / field_dictionary 의미 변경 0. 추가는 전부
  `diagnosis.details.account_service` 하위 (Additive only).
- 미해결로 남긴 것: 실장비 Write E2E 0건(어떤 Family 도 `PROVEN` 아님), Dell `HOLD`(E-6
  비밀번호 정책), 운영 Job 은 게이트가 열리면 여전히 실쓰기(사용자 결정), audit H-5 는
  Portal 문장 변경을 수반해 미처리.

## 일자: 2026-08-12 (o) — 실환경 검증 + Fragment/include 버그 2건 수정

> 정본 기록: `tests/evidence/2026-08-12-runtime-verification-and-bugfix.md`.
> 실행 환경: WSL Ubuntu / ansible-core **2.20.7** / Python 3.12.3.

- BUG-1 ESXi `listening_ports` 항상 `[]` — `collect_runtime.yml` 이 `system.runtime` dict 를
  통째로 다시 만들면서 `listening_ports: []` 하드코딩 → `normalize_system.yml` 이 넣은 실제
  수집값을 덮어썼다. `merge_fragment` 는 깊이 2 에서 dict 를 통째로 교체한다.
  실측 `STEP1 ['22','443','902'] → STEP2 []`. 키 제거는 불가(`STEP3 MISSING`).
  → 같은 원본(`_e_raw_listening_ports`)을 이어받도록 수정. **실장비 검증: esxi02 13개 포트 관측.**
- BUG-2 Redfish vendor OEM include 경로 — `{{ playbook_dir }}` 는 `<repo>/redfish-gather`
  이고 그 아래 `common/` 이 없다. 실측 `exit=2 Could not find or access …`.
  영향은 병합 누락보다 크다 — site.yml OEM block 의 rescue 가 발동해 **OEM 데이터가 버려지고
  가짜 오류 1건이 매번 추가**됐다 (재현 실측: errors 1→0, OEM 소실→보존, collected []→['hardware']).
  adapter 전수 파싱 결과 실제 영향은 HPE 7 adapter 전 세대 / Fujitsu / Huawei / Inspur /
  Quanta. `cisco/collect_oem.yml` 은 어떤 adapter 도 참조하지 않는 dead file.
  → 저장소 정식 방식(`REPO_ROOT` 기준)으로 통일. 벤더별 실장비 확인은 lab 부재로 미수행.
- 회귀를 신설했다. `test_fragment_overwrite_and_include_paths.py`(84) /
  `test_auth_evidence_contract.py`(4). 두 버그 주입 실험에서 `exit=1` 검출 확인.
- 3채널 syntax-check os/esxi/redfish 모두 exit=0 (ansible-core 2.20.7).
- 실장비 스모크 6대상: esxi02 / Cisco CIMC / Dell iDRAC / Redfish 503 / RHEL 8.10 /
  Windows 2022. 전부 요청 1 → envelope 1, 13필드 정합.
  503 대상이 `failed + stage=protocol + code=PROTOCOL_CHECK_FAILED + 정본 3번 문장`,
  HTTP 503 은 `detail` 에만 → P0-2/P0-3/§10 실증.
  Dell 은 recovery fallback 성공 + `account_service.dryrun=true`(쓰기 0) 인데
  `status=success, errors=[]` → **P0-7 실증**.
- §4 인증 근거를 검증했다. `_all_sec_collected > 0` 을 인증 근거로 쓰는 것이 타당함을 전수 확인
  (controller-side / precheck / 빈 fragment 경로 모두 0건). 3경로를 테스트로 고정.
- **BLOCKED** — Jenkins 실제 checkout SHA(§8): `10.100.64.153:8080` 은 응답하나 API 가 403
  (자격증명 없음). GitLab internal(`10.100.64.156`)은 이 세션 네트워크에서 timeout.

## 일자: 2026-08-12 — errors[].message 계약 개선 (조사 → 실제 수정)

> 입력: 에러 메시지 전수조사(정리됨) (조사 전용, 코드 변경 0).
> 그 주장을 **현재 코드로 재검증**한 뒤 수정. 정본 기록: `tests/evidence/2026-08-12-errors-message-contract.md`.

- Message 4계층을 확정했다. 전체 실패(6문장, `failure_reasons.yml`) / 섹션 부분 실패(섹션 의미 유지,
  `section_messages.yml`) / 기술 Evidence(`errors[].detail`, string|null) /
  성공 fallback·정보성(`diagnosis.details.notices` — errors 아님).
- 문장은 `failure_code` 에서만 파생: `precheck_bundle.REASON_BY_FAILURE_CODE` 단일 매핑.
  종전에는 문장과 stage/code 가 서로 다른 조건으로 갈려 같은 결과를 Portal 과 대시보드가 다르게 해석했다.
  `TCP_CONNECTION_REFUSED` → 2번 문장("대상 IP의 관리 포트에 연결할 수 없습니다…").
  존재하지 않던 presence 판정(`ip_in_use`) 제거 — **ICMP/IPAM/ARP 기능은 만들지 않았다.**
- Redfish rescue 4필드를 `_rf_auth_outcome` 하나에서 파생 (passed/rejected/unknown).
  인증 통과가 관측된 뒤의 수집 실패에는 자격증명 문장을 붙이지 않는다.
- 성공한 fallback 이 status 를 partial 로 강등하던 경로를 제거했다.
  `redfish_gather.notices()` 신설. DMTF rackmount1 오프라인 재생이 `partial → success` (golden 재생성).
- 소실 경로 배선 — account_service errors 25지점(종전 전량 폐기) / 실패 후보·무인증 probe 근거 /
  rescue 진입 시 누적 섹션 errors / ESXi `_e_disks_ok`·`_e_dns_ok`·`_e_config_ok`(소비처 0건이었음).
- 정규화를 단일화했다. `filter_plugins/errors_normalizer.py` 신설(멱등).
  `message` 는 항상 비지 않은 문자열(파이썬 dict repr 노출 경로 제거), `detail` 은 string|null 통일.
- 게이트를 신설했다. `schema/field_dictionary.yml` 에 `errors[]` 4항목(종전 정의 **0건**),
  `tests/e2e/test_section_message_contract.py`(partial/success 문구 게이트 종전 0건),
  `tests/unit/test_esxi_section_errors.py`.
- 회귀: `pytest tests/` **2094 passed / 10 skipped / 7 xfailed** (착수 전 1974 passed) ·
  field_dictionary PASS · schema-drift exit 0 · vendor-boundary / harness-consistency 통과.
- 미검증: 실장비 / 실 Jenkins / `ansible-playbook --syntax-check` (이 환경에 ansible 미설치).
  Ansible 검증은 production YAML 템플릿을 추출해 Jinja 로 렌더하는 방식이며 실제 플레이북 실행이 아니다.


## 일자: 2026-08-11 (o) — Phase 6-C: 실제 Jenkins Agent / lab BMC 검증

> **코드 변경 0건.** Phase 6-B 결과를 실환경에서 검증만 했다.

- 실제 Jenkins Agent(10.100.64.154) 검증 성공
  - 환경: Ubuntu 24.04.4 / Python 3.12.3 / **ansible-core 2.20.3**(`/opt/ansible-env`)
  - 내부 GitLab main clone = **`ab7f687a`**(= 우리 HEAD). 최신 구현 9종 전부 존재
  - `ansible-playbook --syntax-check` 3채널 exit 0 — **운영 Agent 에서** 통과했다. WSL 통과가 아니다
  - 요청 host 2 → **envelope 정확히 2개**, 중복 0 / 미지 host 0 / 전부 13필드 /
    `errors[0].message == diagnosis.failure_reason`
- lab BMC 실측 (쓰기 강제 off: `-e _rf_account_service_dryrun=true`)
  - Lenovo 10.50.11.232 — `used_role=primary`, `fallback_used=false` →
    **account_service 미진입 = Write 0**. status success / 9 sections
  - Dell 10.100.15.28 — `used_role=recovery`, `attempted=5` → 401 게이트 통과,
    `account_existed=true` / `action=password_sync` / `method=patch_existing` /
    `slot_uri=.../Accounts/3` / `dryrun=true` 라 `recovered=false`, `verification=skipped`
    → **실제 PATCH 미발생 확인**. status success / 9 sections / errors 0
  - → A→B 동기화 경로가 실장비에서 의도대로 진입하고 override 로 쓰기를 막을 수 있음을 확인
- [발견] Dell 10.100.15.28 의 `infraops` password 가 vault 값과 다르다 —
  override 없이 운영 실행하면 이 장비는 password_sync PATCH 가 발생한다(설계된 동작).
- [BLOCKED] 실제 Jenkins 빌드 트리거 불가 — job 60여 개 전부 build token 0,
  익명 API 403, Jenkins admin 자격 없음. **"Job 이 실제로 최신 SHA 를 checkout" 은 미검증**.
  다만 전 job 의 SCM 이 내부 GitLab `origin/main` 이고 그 브랜치가 우리 HEAD 와 같음을 확인했다.
- 회귀: `pytest tests/` **1971 passed / 10 skipped / 7 xfailed** ·
  하네스/경계/schema-drift/envelope/cross-channel exit 0 · field_dictionary PASS.
- Phase 6-C 완료 (빌드 트리거 1건 blocked).


## 일자: 2026-08-11 (o) — Dell 대표 시리얼 1차 교정 (ServiceRoot Service Tag)

- Dell 만 원천을 교체했다. `data.hardware.serial` / `correlation.serial_number` 의 Dell 원천을
  `ComputerSystem.SerialNumber` → **`ServiceRoot.Oem.Dell.ServiceTag`** 로 바꿨다. 사용자 지시
  (2026-08-11) 로 수행한 독립 작업이며 Phase 6-B 와 무관하다. 커밋 `0fb63799`.
- 왜 — Dell 의 `System.SerialNumber` 는 보드 제조 시리얼이다. 동일 R760 실측에서 그 값
  (`CNIVC0048R0159`)은 SMBIOS Type 2(Baseboard) 문자열 `.GSBPK54.CNIVC0048R0159.` 안에만 있고
  Type 1/Type 3 에는 없다 → 같은 장비 Linux(`GSBPK54`)와 값이 달라 채널 매칭이 깨져 있었다.
  교정 후 **Redfish = Linux = `GSBPK54`** 로 일치.
- 원천 근거: Dell iDRAC9 Redfish API Guide "Table 70. Properties for DellServiceRoot" 가
  `ServiceTag` 를 "System Service Tag" 로 정의 (후보 4종 중 Dell 공식 정의가 있는 유일한 필드).
  `SKU` / `ChassisServiceTag` / `NodeID` / BIOS `SystemServiceTag` 는 **폴백으로도 쓰지 않는다**.
- 못 얻으면 실패 — Dell 시리얼은 필수값이라 null 인 채로 success/partial 을 내보내지 않는다.
  기존 실패 계약 재사용(`failure_stage=gather` / `failure_code=GATHER_FAILED`) — **신규 code 0**.
  무인증 ServiceRoot 에 OEM 블록이 없을 때만 인증 ServiceRoot 를 1회 재조회(정상 경로 추가 GET 0).
- schema 무변경 — envelope 13 필드 / sections / field_dictionary entry 추가·삭제 0.
  배선(`normalize_standard.yml` / `build_correlation.yml`) 무변경. 새 필드 만들지 않음.
- 다른 벤더 무변경 — `_SERIAL_RESOLVERS` 에 `dell` 만 등록. HPE / HPE CSUS(`SGHD3TLNDD-000`) /
  Lenovo / Cisco 외 전 벤더는 코드 경로 자체를 타지 않는다. 비-Dell baseline 9종 무변경.
- [INFO] 되돌림 → 재적용 경위 — 이 작업이 진행되는 동안 Phase 6-B 세션이 같은 작업 트리에서
  동시 작업했다. 그 세션은 미커밋 상태였던 본 변경을 "범위 밖 혼입" 으로 판단해 되돌렸다(그 세션
  기록은 아래 (n) 항목). 실제로는 사용자 지시로 수행 중이던 별개 작업이라 Phase 6-B 커밋 완료 후
  **다시 적용**해 `0fb63799` 로 커밋했다. 되돌림 당시 주석 블록 일부가 `5af488ef` 에 섞여
  들어가 있었고(함수 본문 없는 고아 주석) 이번 재적용으로 해소됐다.
- 회귀: unit 1186 / e2e 416 / integration 200 / regression 169 passed ·
  `validate_field_dictionary` / `verify_vendor_boundary` / `verify_harness_consistency` PASS.
- 실 Jenkins 검증 완료 — job `clovirone-server-gather` #188(redfish, Dell 2대) /
  #189(os, 짝 호스트). BMC 10.100.15.34 = OS 10.100.64.96 이 동일 `system_uuid` 위에서
  `correlation.serial_number` **둘 다 `GSBPK54`** → 교정 전 DIFFERENT 가 SAME 으로 해소.
  envelope 13필드 일치 / Stage 3 PASS / errors 0 / 콘솔 `CNIVC` 0회.
- 정본: `docs/ai/contracts/serial-number.md` Part III (29절) /
  `tests/evidence/2026-08-11-dell-serial-service-tag.md`.

## 일자: 2026-08-11 (n) — Phase 6-B: 계정 보정 안전화 + 결과 누락 제거 + 문구 통일

- 평문 자격증명을 제거했다. vault master 와 표준계정 password 가 추적 파일 4곳(3곳은 production)에
  평문으로 있었다. 전부 참조 표기로 교체했고 live vault 자격 16종 전수 잔존 0 확인.
  단 **git history 에는 그대로 남아 있다** (history rewrite 미수행 — 별도 대상).
- [BLOCKED] vault master rotation 미수행 — Jenkins credential store 를 갱신할 수단이 없다
  (익명 API 403 / `cloviradmin` 은 sudo 불가 / CLI SSH 비활성 / Jenkins admin 토큰 없음).
  갱신 없이 rekey 하면 **운영 수집이 전면 중단**되므로 실행하지 않았다.
- 과거 노출 영향 (실측) — BMC `infraops` 5/5 와 vendor recovery 5/5 가 **과거 커밋의 vault 로
  지금도 복호화 가능**. Linux/Windows/ESXi 는 그 사이 변경돼 해당 커밋으로는 유효하지 않다.
- 계정 보정 진입 조건을 강화했다. 종전 "primary 실패 + recovery 성공" → 이제
  **primary 가 구조화된 401 로 거부됐을 때만**. timeout / TLS / 5xx / transport / 403 은 write 0.
  동일 username 다중 slot 이면 중단. `delete_recreate` 는 opt-in(default off).
  A→B password 동기화 기능은 그대로 유지된다.
- unreachable host envelope 소실을 없앴다. 콜백이 host lifecycle 을 추적해 play 종료 시
  누락 host 를 보충한다. 요청 host 1개 = envelope 1개.
- Portal 문구 통일 — Portal 이 실제로 읽는 `errors[].message` 를 `diagnosis.failure_reason`
  에서 **복사**하도록 구조화(`build_failed_output.yml`). 문구는 5종으로 통일하고 정의를 1곳
  (`common/vars/failure_reasons.yml`)으로 모았다. DNS·호스트이름 안내 제거(Portal 은 IPv4 만 전달).
- 운영 Jenkins 정합화 — 내부 GitLab main 이 `c00e2422` 에 머물러 있었다.
  기존 커밋을 지우지 않는 **병합**으로 정합화(`e57598c3`). `Jenkinsfile_portal_test` 보존.
  force/rewrite/reset 미사용.
- 범위 밖 변경 되돌림 — 작업 중 Dell 대표 시리얼을 Service Tag 로 바꾸는 변경이 섞여 들어와
  `schema/baseline_v1/dell_baseline.json`(보호 경로)까지 수정돼 있었다. 이번 Phase 지시에 없고
  `correlation.serial_number` 의 **값 의미**를 바꾸므로 전부 되돌렸다.
- 회귀: `pytest tests/` **1926 passed / 10 skipped / 7 xfailed** ·
  Linux `--syntax-check` 3채널 exit 0 · 하네스/경계/schema-drift/envelope/cross-channel exit 0 ·
  `schema/baseline_v1` 무변경.
- Phase 6-B 완료. vault rotation 과 실장비 계정 검증은 미수행(사유는 위).


## 일자: 2026-08-11 (m) — 실환경 검증 (Phase 6-A) + WinRM 전송 버그 수정

> lab 네트워크가 개발 PC 에서 직접 도달 가능함을 확인해 **실장비 검증**을 처음 수행했다.
> 코드 수정은 실측으로 재현·대조군까지 확보한 **1건**만 했다.

- `ansible-playbook --syntax-check` 최초 실제 통과 — WSL Ubuntu 24.04.3 /
  ansible-core 2.20.7 / vault 암호 적용. 3 채널 전부 exit 0. Phase 1~5-A 내내 "미실행"
  이던 항목이 해소됐다. (`/mnt/c` 는 world-writable 이라 ansible.cfg 가 무시되므로
  Linux 네이티브 경로 사본에서 실행해야 한다.)
- [CRIT] WinRM Identify 전송 버그 수정 — lab Windows(10.100.64.120)가 5985/5986
  양쪽에서 HTTP 401 + 본문 0 을 반환해 정상 Windows 호스트가 전부
  `detected_os=None` 으로 떨어졌다. Phase 3-B 이후 **Windows 수집이 전면 차단**되는 상태.
  원인은 전송 계층이었다. `urllib.request` 가 헤더 이름을
  `capitalize()` / `title()` 로 두 번 정규화해 `WSMANIDENTIFY` 가 `Wsmanidentify` 로 나갔다.
  판정 로직 쪽 문제가 아니다.
  양성 대조군: 헤더 이름만 보존해 보내면 같은 호스트가 HTTP 200 + 완전한
  IdentifyResponse(ProductVendor=Microsoft Corporation)를 반환.
  → `http_post_soap` 의 전송만 `http.client` 로 교체(stdlib 유지). 요청 본문 / 판정 로직 /
  timeout / retry / 인증 시도 횟수 / JSON contract 전부 무변경.
  수정 후 실장비 재검증: `probe_os` OK, `detected_os=windows`, `winrm_scheme=https`.
- 테스트 seam 을 교정했다. 기존 WinRM 테스트는 `http_post_soap` 자체를 mock 해서 버그가 사는
  계층이 테스트에 없었다(전수 통과 ↔ 실장비 100% 실패 동시 성립).
  `tests/unit/test_soap_header_case_preserved.py` 15건이 `http.client` 를 seam 으로 잡는다.
- ESXi 7.0.3 실장비 3대 검증 완료 — `versionId=6.0` 수락, HTTP 200,
  `RetrieveServiceContentResponse`, `about.apiType=HostAgent` / `apiVersion=7.0.3.0`.
  Phase 4-B 의 "wire capture 없음" 한계 해소. probe 0.06~0.11s.
- Redfish BMC 11대 검증 — 9대 정상(Dell iDRAC9 ×5 / AMI ×1 / HPE iLO Gen11 / Lenovo XCC /
  Cisco ×1), cisco 1대는 502·503 흔들림, 1대는 다운. **무인증 ServiceRoot 에서 401/403 을
  반환한 장비 0대** → Phase 4-A 판정을 완화하지 않는다(근거 없음).
  Dell iDRAC 은 HTTP 200 과 함께 `WWW-Authenticate: Basic realm="RedfishService"` 를 보낸다
  — 과거 "401 반환" 기록의 출처로 보인다. trailing slash 는 실장비에서도 갈린다
  (Dell `/redfish/v1` / 그 외 `/redfish/v1/`) → Phase 4-A 의 양쪽 허용이 실제로 필요.
- [CRIT, 미수정] 운영 Jenkins 가 우리 코드를 실행하지 않는다 — job SCM 은 내부 GitLab
  `origin/main`(= `c00e2422`)이고 agent 워크스페이스 지문도 `a382bdee` 시점이다.
  Phase 1~5-A 33 커밋 **0% 반영**. `production` 은 최신이지만 그 브랜치를 보는 job 이 없다.
  → 사용자 결정 필요(rule 93 R1 force 계열 금지).
- [CRIT, 미수정] 수집 도중 unreachable 이면 해당 host envelope 이 사라진다 —
  2 host 투입 → 1 envelope 재현. 두 Jenkinsfile 모두 감지하지 못한다.
- [CRIT, 미수정] Portal 실패 Grid 의 실제 소스는 `errors[].message` —
  `diagnosis.failure_reason` 은 Portal 코드에서 읽는 곳이 0건. Phase 5-A 문구 정화가
  사용자에게 보이는 필드에 적용되지 않았다.
- [CRIT, 사고] 검증 중 BMC 쓰기 1건 발생 — `account_service.yml:43` 이 dryrun 을
  false 로 덮어써 Dell 10.100.15.27 에 `PATCH .../Accounts/3` 이 실행됐다.
- 회귀: `pytest tests/` **1775 passed / 11 skipped / 7 xfailed** · Linux syntax-check 3/3 exit 0 ·
  하네스/경계/schema-drift/envelope/cross-channel exit 0 · `schema/` 무변경.
- Phase 6-A 완료. 위 미수정 CRIT 3건은 사용자 지시 대기.


## 일자: 2026-08-11 (l) — Portal Grid 실패 사유 최종 정리 + 자격 실패 분류 (Phase 5-A)

> `diagnosis.failure_reason` 문구와 자격 실패 해석만 변경. Protocol Probe(OS TCP 폴링 /
> SSH Identification / WinRM Identify / Redfish ServiceRoot / ESXi RetrieveServiceContent)와
> Gathering / Timeout / Retry / 인증 시도 횟수는 손대지 않았다.

- failure_reason 을 Portal Grid 문장으로 통일 — "확인된 상태 + 실패한 현재 단계 +
  확인할 항목" 구조. 앞 단계 성공은 **실제 관측된 경우에만** 표현한다.
  TCP 실패에 "통신은 되지만", RST 에 "서버는 응답하지만" 을 쓰지 않는다(중간 방화벽이
  대신 응답했을 수 있다).
- 관리 포트 번호를 제거했다. os-gather PLAY 1.5 의 `failure_reason` 덮어쓰기 태스크를 삭제했다.
  종전 문구는 `SSH(22)/WinRM(5985, 5986)` 을 Grid 에 그대로 노출했다. 포트 정보는
  `errors[].message` 로 옮겼고 포트별 원본 사유는 `errors[].detail` 에 그대로 남는다.
- OS rescue 의 protocol_supported 정정 — 종전엔 자격 probe 결과를 그대로 썼다.
  Phase 3-B 이후 PLAY 1 이 SSH identification / WinRM Identify 를 실제로 확인해야만
  PLAY 2/3 에 도달한다. 자격 결과와 무관하게 `true` 가 관측된 사실이다.
- Redfish 구조화 인증 거부 — `redfish_gather` 가 module result 에
  `auth_evidence.first_auth_status`(정수)를 싣는다. **자격증명을 실은 요청의 첫 status** 만
  기록하며 새 요청을 만들지 않는다(인증 시도 횟수 = 계정 잠금 위험 불변). 401 이면
  `auth_success=false` + `failure_stage=auth`, 403 은 인증 이후 권한 부족일 수 있어
  거부로 확정하지 않는다(null 유지). 문자열 파싱은 쓰는 곳이 없다.
- Linux / Windows / ESXi 는 auth_success=null 유지 — HEAD 실측 결과 세 채널 모두
  인증 거부와 transport 실패 / 권한 부족 / 제한 쉘 / 모듈 오류를 구조적으로 구분할 필드가
  없다(판정식은 각각 `rc==0 and '__auth_ok__' in stdout` / `ping=='pong'` /
  `ansible_facts is defined`). 남는 단서는 `msg` 문자열뿐이라 확정하지 않는다.
- failure_stage / failure_code enum 무변경 — 7 stage / 7 code 그대로. 신규 stage·code 0개.
- JSON Contract 변경 0 — 새 envelope 필드 없음, `schema_version` `"1"`.
  `auth_evidence` 는 **module result 내부 키**이며 envelope 으로 나가지 않는다.
- 회귀: `pytest tests/` **1731 passed / 11 skipped / 7 xfailed**
  (unit 1063 / e2e 299 / integration 200 / regression 169). 신규
  `test_failure_reason_case_matrix.py` 27건(18 Case 전수 + 단계 진행 관계) +
  `test_credential_probe_classification.py` 13건 + `test_redfish_auth_evidence.py` 14건.
- 보정 3건 (2026-08-11):
  1. Redfish Stage 4 비-401 실패 문구를 `Redfish 서비스는 확인되었지만 BMC에 접속하지 못했습니다.
     자격증명과 계정 권한을 확인하세요.` 로 교체 (다른 채널과 같은 어휘).
  2. `REASON_PORT_REFUSED` 를 `관리 서비스 연결 시도가 거부되었습니다.` 로 교체 — RST 를
     보낸 주체가 최종 대상인지 중간 네트워크 장비인지 확정할 수 없다.
  3. Redfish 복수 후보 집계 규칙 도입 — 후보 하나의 401 로 전체를 확정하던 것을 고쳤다.
     `try_one_account.yml` 이 후보별 `first_auth_status` 를 `_rf_auth_statuses` 에 누적하고
     site.yml 이 (시도 후보 1개 이상) + (후보 수만큼 관측) + (전부 401) 셋을 모두 만족할 때만
     `auth_success=false`. timeout / TLS / 403 / 200 이 하나라도 섞이면 null 유지.
     `first_auth_status` 는 **첫** 인증 응답이라 인증 통과 후의 리소스 401 은 승격되지 않는다.
- Phase 5-A 완료. Authorization 별도 분류 / Portal Receiver 확인 / 실장비 검증 미착수.

## 일자: 2026-08-10 (k) — ESXi 판정을 실제 vim25 SOAP 응답 검증으로 강화 (Phase 4-B)

> ESXi Precheck 의 Protocol Detection 만 변경. Gathering(community.vmware / pyVmomi / facts /
> adapter / normalize)과 OS / Redfish 판정은 손대지 않았다.

- status 기반 판정 폐기 — 종전 `probe_esxi` 는 `GET /sdk` 의 HTTP status
  (`200/301/302/401/403/404/405/500/503`) 만 봤다. 443 에서 뭐라도 응답하면 통과라 일반
  HTTPS 서버가 vSphere 로 판정될 수 있었다. 이제 `/sdk` 에 vim25
  `RetrieveServiceContent` 를 POST 하고 **응답 본문 구조**로 판정한다.
- 요청은 추측하지 않았다 — 설치본 pyVmomi 9.x 의 `SoapStubAdapter.SerializeRequest` 가
  만드는 요청과 **바이트 단위로 동일**함을 오프라인 대조로 확인했다. Content-Type
  (`text/xml; charset=UTF-8`, SOAP 1.1) / `SOAPAction: "urn:vim25/6.0"` 도 pyVmomi
  `InvokeMethod` 헤더와 같다. `versionId=6.0` 은 VMware 자체 CLI govc 의 기본값
  (`GOVC_VIM_VERSION`)이며 저장소 지원 하한(ESXi 6.0)과도 맞는다.
- 비인증 호출 근거: `RetrieveServiceContent` 의 privId 는 `System.Anonymous`
  (pyVmomi typeinfo 실측). Broadcom vSphere WS API 문서도 ServiceInstance 는 인증 없이
  접근 가능하다고 기술한다.
- 최소 성공 조건 2가지
  1) `{urn:vim25}RetrieveServiceContentResponse` → `returnval` → `about` 에
     `apiType` / `apiVersion` 이 채워져 있다. (`about` 은 ServiceContent 필수,
     `apiType`/`apiVersion` 은 AboutInfo 필수 — 둘 다 **API 2.0(version1)부터** 존재해
     6.x/7.x/8.x 공통이다. pyVmomi typeinfo 로 실측.)
  2) SOAP Fault 인데 detail 안 요소의 네임스페이스가 `urn:vim25` / `urn:internalvim25`.
     vSphere 자신이 만든 구조화 Fault 이므로 endpoint 존재의 직접 증거다. 네임스페이스가
     없는 일반 SOAP Fault 는 구별할 수 없으므로 성공으로 쓰지 않는다(문자열 검색 아님).
- 인증과 분리(§9) — Probe 는 자격증명을 보내지 않는다. HTTP 401/403 을 받아도
  `auth_success` 는 `null` 을 유지한다. 실패 시 `protocol` / `PROTOCOL_CHECK_FAILED`.
- failure_reason 무변경 — "예상한 vSphere API 응답을 확인하지 못했습니다..." 문구가
  강화된 관측 수준과도 일치해 그대로 뒀다.
- Timeout / Retry 무변경 — 요청 1회, retry 없음. 최악 수행 시간은 종전과 같다
  (GET 1회 → POST 1회, `timeout_protocol` 은 esxi-gather 가 주는 30초 그대로).
- JSON Contract 변경 0 — 새 필드 없음, enum 추가 없음, `schema_version` `"1"`,
  `schema/` 파일 무변경. `diagnosis.details` 로 나가는 probe_facts 는 종전과 같은 키만
  싣는다(`vsphere_endpoint`, 비-200 일 때 `root_status_code`). 확보한 `apiType`/`apiVersion`
  은 판정 근거로만 쓰고 envelope 에 넣지 않았다(§21 — 필요하면 별도 결정).
  `requires_auth_at_root` 는 도달 불가가 되어 제거했다(baseline 에 없던 키).
- 공통 helper 영향 차단 — `http_post_soap` 에 `content_type` / `max_bytes` 인자를 더했으나
  **기본값이 종전 상수와 같아** WinRM Identify(OS) 동작은 그대로다. `http_get` 는 손대지 않아
  Redfish 경로도 무영향.
- 실장비 미검증(보고 대상) — 저장소에 `/sdk` **wire capture 가 없다.** Positive fixture 는
  lab ESXi 3대(모두 7.0.3 build-20842708)의 실측 AboutInfo 를 pyVmomi 직렬화기로 감싼 것이다.
  6.x / 8.x / vCenter fixture 는 합성이며 "해당 버전 검증 완료" 로 취급하지 않는다.
- 회귀: `pytest tests/` **1676 passed / 11 skipped / 7 xfailed**
  (unit 1049 / e2e 258 / integration 200 / regression 169). 신규
  `test_esxi_precheck_contract.py` 14건 + `test_precheck_probe_esxi.py` 재작성 54건.
  Stage 3(output_schema_drift) PASS / 하네스·경계·envelope·cross-channel 전부 exit 0 /
  Jinja2 239 표현식 컴파일 0 오류.
- Phase 4-B 완료. Credential Probe 원인 세분화 / Authorization 구분 / Portal Receiver 미착수.


---

> 이 아래로 76개 항목이 더 있었다. 작업 이력은 git log 에 그대로 있으므로 여기서는 최근 12건만 유지한다.
> 과거 항목이 필요하면 `git log -p -- docs/ai/CURRENT_STATE.md` 로 본다.
