# RMC (Rack Management Controller) Redfish 활성화 가이드

> HPE Compute Scale-up Server 3200 / Superdome Flex 사이트 배포 시 RMC Redfish 비활성화 / 라이선스 부재로 인한 수집 실패 진단 + 활성화 절차.

## 1. RMC 란?

HPE 의 스케일업 서버 군 (CSUS 3200 / Superdome Flex / Flex 280) 은 단일 BMC 가 아닌 **RMC (Rack Management Controller)** 가 N 개 chassis × N 개 nPartition × 다중 Manager 를 통합 관리한다. HPE 공식 인용:

> "supports large, partitionable systems managed by a **single aggregated controller like HPE Compute Scale-up Server 3200 RMC**."

server-exporter 는 RMC primary 시스템의 전 Partition/Manager/Chassis 를 수집한다 (`data.multi_node` Additive 컨테이너).

CSUS 3200 Redfish 모델 전체를 수집한다 — nPartition 별 부팅 순서(`partitions[].boot`), chassis 별 Thermal(`chassis[].thermal`, Power 와 쌍), RMC LogServices(`managers[].log_services`), CompositionService/ResourceBlocks(`multi_node.composition` — 각 ResourceBlock ↔ chassis 대응), Fabrics/FlexGrid(`multi_node.fabrics` — NUMAlink Switches+Endpoints). 상세 shape 는 `docs/20_json-schema-fields.md` 9절 (`data.multi_node` 확장 컴포넌트) 참조.

## 2. 알려진 위험 신호

HPE community 게시물 ([7200359 "impossible to get redfish answer from superdome flex rmc"](https://community.hpe.com/t5/servers-general/impossible-to-get-redfish-answer-from-superdome-flex-rmc/td-p/7200359?nobounce)):

> 사용자가 `redfishtool -u administrator -p passwd -r ilo Chassis list` 시도 → "Error getting service root, aborting"
>
> HPE Pro 답변: 근본 원인 미확정. reference doc (a00119177en_us) 만 제시.

→ **사이트 환경에서 RMC Redfish API 자체가 비활성화 / 라이선스 부재 가능성**.

## 3. server-exporter 자동 진단

`adapter.vendor_notes.manager_layout` 가 `rmc_primary` 또는 `rmc_primary_ilo_secondary` 인 vendor 에 대해 다음 진단 메타가 envelope 에 자동 노출:

```json
{
  "status": "failed",
  "errors": [
    {
      "section": "auth",
      "message": "ServiceRoot 응답 실패 — ..."
    }
  ],
  "diagnosis": {
    "auth_success": false,
    "details": {
      "multi_node_layout": "rmc_primary",
      "rmc_activation_check": false
    }
  }
}
```

**진단 hint 매트릭스:**

| `rmc_activation_check` | 의미 | 호출자 액션 |
|---|---|---|
| `true` | RMC Redfish 정상 동작 | 통상 처리 |
| `false` | manager_layout=rmc_* 지정 + collect 실패 | 본 문서 4 절 활성화 절차 확인 |
| `null` | manager_layout 미정의 (일반 BMC vendor) | 본 hint 무관 |

## 4. RMC Redfish 활성화 절차

> sd00002765en_us (HPE Compute Scale-up Server 3200 Administration Guide) 및 [HPE Server Management Portal](https://servermanagementportal.ext.hpe.com/docs/concepts/gettingstarted) 기반. 사이트 실측 시 본 절 정정 의무.

### 4.1 라이선스 / Subscription 확인

CSUS 3200 / Superdome Flex RMC Redfish API 는 일부 펌웨어 / 라이선스 조합에서 비활성. HPE Support 에 라이선스 상태 문의 권장:

- HPE Support Center: https://support.hpe.com/
- 문의 시 인용: serial number + RMC firmware version + "Redfish API enablement"

### 4.2 RMC Web GUI 로 활성화

기본적으로 RMC 는 표준 Redfish API host 로 동작하지만, 일부 환경에서 명시 enable 필요:

1. RMC Web GUI 로그인 (`https://<rmc-ip>/`)
2. **System Management** → **Network Services** → **Redfish API** 활성화 확인
3. **Account Service** → role 확인 — Redfish 호출에는 `administrator` 또는 `operator` role 필요

### 4.3 CLI 검증

```bash
# ServiceRoot 무인증 GET — 응답 200 + Product/Vendor 필드 확인
curl -k -s -o - https://<rmc-ip>/redfish/v1/

# 인증 GET — Managers / Systems / Chassis 컬렉션 응답 확인
curl -k -s -u <user>:<password> https://<rmc-ip>/redfish/v1/Managers
curl -k -s -u <user>:<password> https://<rmc-ip>/redfish/v1/Systems
curl -k -s -u <user>:<password> https://<rmc-ip>/redfish/v1/Chassis
```

기대 응답:
- ServiceRoot: `{"Product": "Compute Scale-up Server 3200", "Vendor": "HPE", "Managers": {...}, ...}`
- Managers Members: RMC + per-chassis PDHC + per-node iLO5 (CSUS 3200 + Superdome Flex)
- Systems Members: Partition0/Partition1/... (nPAR)
- Chassis Members: Base + Expansion 0~3

## 5. 사이트 실측 후 조치

사이트에서 RMC Redfish 활성화 확인 후 server-exporter 운영자가 다음 등재:

1. 실측 결과 + 환경 (펌웨어 / 라이선스 / 모델) 기록
2. `tests/fixtures/redfish/hpe_csus_3200/` 실 응답으로 합성 fixture 교체 (lab 도입 시)
3. `schema/baseline_v1/hpe_csus_3200_baseline.json` 교체 (현재 mock-derived → 실측 baseline)
4. `docs/19_decision-log.md` Round 신 항목

## 6. 트러블슈팅 매트릭스

| 증상 | 의심 원인 | 진단 |
|---|---|---|
| ServiceRoot 401 | 자격증명 오류 / role 부족 | vault/redfish/hpe.yml 점검 |
| ServiceRoot 404 | RMC Redfish API 비활성 | 4.2 Web GUI 확인 |
| ServiceRoot timeout | 방화벽 / TCP 443 차단 | precheck phase port 검토 |
| Managers Members 1개만 (RMC 누락) | RMC role / namespace 권한 부족 | RMC role 권한 격상 |
| Systems Partition0 만 응답 | nPAR 단일 partition 운영 (정상) | server-exporter `data.multi_node.summary.partition_count == 1` 노출 |
| Oem.Hpe.PartitionInfo 부재 | RMC firmware 노출 안 함 / 정규화 mock 미일치 | 4.3 raw curl 확인 |

## 7. 관련

- envelope reference: `docs/20_json-schema-fields.md` 9절 (`data.multi_node`)
- adapter: `adapters/redfish/hpe_csus_3200.yml` / `hpe_superdome_flex.yml`
- web sources:
  - https://servermanagementportal.ext.hpe.com/docs/concepts/gettingstarted
  - https://support.hpe.com/hpesc/public/docDisplay?docId=sd00002765en_us&docLocale=en_US
  - https://community.hpe.com/t5/servers-general/impossible-to-get-redfish-answer-from-superdome-flex-rmc/td-p/7200359
