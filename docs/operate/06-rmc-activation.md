# HPE RMC Redfish 확인과 활성화

이 문서는 HPE Compute Scale-up Server 3200(CSUS 3200)과 Superdome Flex처럼 RMC(Rack Management Controller)가 여러 chassis와 파티션을 한 Redfish 서비스로 묶어 내보내는 장비에서, 수집이 실패했을 때 RMC 쪽을 어떻게 확인하는지 설명합니다.
일반 BMC(iLO, iDRAC, XCC 등) 장비의 실패 진단은 [../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md)를 보세요.

## 1. 수집이 RMC를 어떻게 다루나

어댑터 `adapters/redfish/hpe_csus_3200.yml`(`manager_layout: rmc_primary`)과 `adapters/redfish/hpe_superdome_flex.yml`(`manager_layout: rmc_primary_ilo_secondary`)이 선택된 대상은 일반 섹션 외에 `data.multi_node`를 채웁니다.

| 키 | 내용 |
|---|---|
| `enabled`, `layout` | `true`와 어댑터의 `manager_layout` 값 |
| `summary` | `partition_count`, `manager_count`, `chassis_count`, `representative_partition`, `resource_block_count`, `fabric_count` |
| `partitions[]` | 파티션(Systems)마다 식별, 부팅 순서 등 |
| `managers[]` | RMC, chassis 관리 컨트롤러, 노드 iLO 등 Manager마다 역할과 LogServices |
| `chassis[]` | chassis마다 Power와 Thermal |
| `composition`, `fabrics` | CompositionService/ResourceBlocks와 Fabrics. 서비스 루트에 링크가 없으면 `null` |
| `errors[]` | 하위 리소스 조회 중 난 오류 |

다른 벤더와 일반 HPE 장비에서는 `data.multi_node`가 `null`입니다. 필드 정의는 [../contract/03-fields.md](../contract/03-fields.md) 9절에 있습니다.

RMC 전용 진단 필드는 없습니다. RMC의 Redfish가 꺼져 있거나 응답하지 않으면 다른 장비와 같은 사전 진단 결과로 나타납니다.

| 결과 봉투 | 뜻 |
|---|---|
| `diagnosis.failure_stage: port`, `failure_code: TCP_CONNECT_FAILED` | TCP 443에 연결하지 못했습니다. 방화벽이나 RMC 네트워크 설정을 확인합니다 |
| `diagnosis.failure_stage: protocol`, `failure_code: PROTOCOL_CHECK_FAILED` | 443은 열렸는데 `/redfish/v1/`이 Redfish 서비스 루트로 응답하지 않았습니다. RMC Redfish 서비스가 꺼져 있을 때 이렇게 나옵니다 |
| `diagnosis.failure_stage: auth`, `failure_code: AUTH_PROBE_FAILED` | 서비스 루트는 있는데 표준 계정 인증이 거부됐습니다. 계정과 권한을 확인합니다([05-vault.md](05-vault.md)) |
| `status: partial`, `data.multi_node.summary.manager_count`가 기대보다 작음 | 계정 권한이 낮아 일부 Manager나 chassis가 목록에서 가려졌을 수 있습니다 |

## 2. 알려진 사례

HPE 커뮤니티 게시물(["impossible to get redfish answer from superdome flex rmc"](https://community.hpe.com/t5/servers-general/impossible-to-get-redfish-answer-from-superdome-flex-rmc/td-p/7200359))에서 사용자가 RMC에 Redfish 도구로 접근했을 때 서비스 루트를 얻지 못했고, HPE 답변은 근본 원인을 확정하지 않고 참고 문서만 안내했습니다. 사이트 RMC에서 Redfish 서비스가 꺼져 있거나 사용 조건이 맞지 않을 가능성이 있습니다.

## 3. RMC 쪽 확인 절차

아래 절차는 HPE 문서([HPE Compute Scale-up Server 3200 Administration Guide](https://support.hpe.com/hpesc/public/docDisplay?docId=sd00002765en_us&docLocale=en_US), [HPE Server Management Portal](https://servermanagementportal.ext.hpe.com/docs/concepts/gettingstarted)) 기준입니다. 사내에는 RMC 장비가 없어 실장비에서 확인하지 않았습니다. 사이트에서 확인한 내용이 다르면 이 절을 고치세요.

### 3.1 Redfish 서비스 상태

1. RMC 웹 화면(`https://<RMC 주소>/`)에 로그인하세요.
2. 시스템 관리 메뉴의 네트워크 서비스에서 Redfish API가 켜져 있는지 확인하세요. 메뉴 이름은 펌웨어에 따라 다를 수 있습니다.
3. 계정 설정에서 수집 계정의 역할을 확인하세요. 전체 트리를 읽으려면 administrator 또는 operator 권한이 필요합니다.

Redfish를 켤 수 없거나 라이선스 안내가 나오면 HPE 지원에 장비 일련번호, RMC 펌웨어 버전, "Redfish API enablement"로 문의하세요.

### 3.2 명령으로 확인

Runner나 RMC에 닿는 서버에서 실행합니다.

```bash
# 무인증 서비스 루트. HTTP 200 과 Product, Vendor 필드가 나와야 합니다
curl -k -s -o - -w '\n%{http_code}\n' https://<RMC 주소>/redfish/v1/

# 인증 조회. 각 컬렉션의 Members 수를 확인합니다
curl -k -s -u '<계정>:<비밀번호>' https://<RMC 주소>/redfish/v1/Managers
curl -k -s -u '<계정>:<비밀번호>' https://<RMC 주소>/redfish/v1/Systems
curl -k -s -u '<계정>:<비밀번호>' https://<RMC 주소>/redfish/v1/Chassis
```

기대하는 응답입니다.

- 서비스 루트에 `"Vendor": "HPE"`와 제품명(`Compute Scale-up Server 3200` 등)이 있습니다.
- Managers에 RMC와 chassis 관리 컨트롤러, 노드 iLO가 함께 나옵니다.
- Systems에 파티션(Partition0 등)이 나옵니다. 단일 파티션 운영이면 한 개입니다.
- Chassis에 기본 chassis와 확장 chassis가 나옵니다.

명령줄에 비밀번호를 적으면 셸 기록에 남습니다. 확인이 끝나면 기록을 지우세요.

## 4. 증상별 확인

| 증상 | 의심 원인 | 확인 |
|---|---|---|
| 서비스 루트 401 | 계정 오류 또는 권한 부족 | `vault/<loc>/redfish/hpe.yml`과 표준 계정([05-vault.md](05-vault.md)) |
| 서비스 루트 404 또는 HTML 응답 | RMC Redfish 서비스 꺼짐 | 3.1 |
| 서비스 루트 timeout | TCP 443 차단 | 네트워크 경로, 사전 진단 결과 `failure_stage: port` |
| Managers Members가 RMC 하나만 | 계정 권한이 낮아 하위 Manager가 가려짐 | 계정 역할 격상 뒤 재확인 |
| Systems에 Partition0만 | 단일 파티션 운영 | 정상. `data.multi_node.summary.partition_count`가 1 |
| `Oem.Hpe.PartitionInfo` 없음 | 펌웨어가 노출하지 않음 | 3.2의 원본 응답을 보관해 개발 담당에게 전달 |

## 5. 사이트에서 확인한 뒤 할 일

사내에는 RMC 실장비가 없어 현재 fixture와 기준선은 합성 데이터입니다. 사이트에서 실제 응답을 확보하면 다음을 갱신합니다.

1. 원본 응답 트리를 캡처합니다([../develop/08-onsite-capture.md](../develop/08-onsite-capture.md)).
2. `tests/fixtures/redfish/hpe_csus_3200/`의 합성 fixture를 실제 응답으로 바꾸고 회귀 시험을 돌립니다.
3. `schema/baseline_v1/hpe_csus_3200_baseline.json`을 실측 결과로 바꿉니다. 기준선은 실측으로만 갱신합니다.
4. 결과와 환경(펌웨어, 모델, 파티션 구성)을 [../reference/live-validation.md](../reference/live-validation.md)와 [../reference/decision-log.md](../reference/decision-log.md)에 기록합니다.

## 관련 문서

| 내용 | 문서 |
|---|---|
| `data.multi_node` 필드 정의 | [../contract/03-fields.md](../contract/03-fields.md) 9절 |
| 실패 단계와 코드 | [../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md) |
| 어댑터 선택 | [../develop/03-adapter-system.md](../develop/03-adapter-system.md) |
| 운영망 원본 캡처 | [../develop/08-onsite-capture.md](../develop/08-onsite-capture.md) |
