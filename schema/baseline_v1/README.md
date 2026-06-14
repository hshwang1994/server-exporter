# schema/baseline_v1 — 회귀 검증용 표준 응답 샘플

> **이 폴더는** 서버별로 server-exporter 가 정상 동작했을 때의 출력 JSON 을 그대로 보존한 "정답지" 입니다.
> 코드를 변경한 뒤 이 정답지와 현재 출력을 비교하면, 의도치 않은 회귀가 있었는지 즉시 알 수 있습니다.

## 핵심 약속

- 이 폴더의 JSON 은 **수정하지 않습니다**. 새 정답지가 필요하면 별도 폴더 (예: `baseline_v2/`) 를 만들어 사용합니다.
- 각 파일은 callback (`callback_plugins/json_only.py`) 의 출력을 그대로 저장한 형태입니다.
- 식별자(serial_number, system_uuid 같은 DMI 정보) 는 권장 운영 모드 (sudo become 사용) 기준으로 기록되어 있습니다.

## 파일 명명 규칙

```text
{vendor 또는 os}_baseline.json   ← 회귀 비교용 표준 JSON (수정 금지, 본 폴더)
```

라인별 한글 주석본은 본 폴더가 아니라 **`schema/output_examples/`** 에 채널/벤더 대표 예시로 보존된다 (아래 표 "한글 주석 예시" 열). JSON 표준은 주석을 허용하지 않아 확장자가 `.jsonc` 다.

| 표준 JSON | 한글 주석 예시 (`schema/output_examples/`) | 채널 | 검증 시 사용된 장비 |
|---|---|---|---|
| `dell_baseline.json` | `redfish_dell_idrac10.jsonc` | Redfish | Dell PowerEdge R740 (iDRAC 9 / FW 4.00) |
| `hpe_baseline.json` | `redfish_hpe_ilo6.jsonc` | Redfish | HPE ProLiant DL380 Gen11 (iLO 6 / FW 1.73) |
| **`hpe_csus_3200_baseline.json`** (cycle 2026-05-12) | `redfish_hpe_csus_3200.jsonc` | Redfish | **HPE Compute Scale-up Server 3200 — mock-derived (lab 부재 / sdflexutils + DMTF v1.15 + iLO5 API ref 합성)** |
| `lenovo_baseline.json` | `redfish_lenovo_xcc.jsonc` | Redfish | Lenovo ThinkSystem SR650 V2 (XCC / FW 5.70) |
| `cisco_baseline.json` | `redfish_cisco_cimc.jsonc` | Redfish | Cisco TA-UNODE-G1 (CIMC) |
| `esxi_baseline.json` | `esxi_vmware.jsonc` | ESXi | ESXi 7.0.3 |
| `ubuntu_baseline.json` | `os_linux_ubuntu2404.jsonc` | OS (Linux) | Ubuntu 24.04 |
| `windows_baseline.json` | `os_windows2022.jsonc` | OS (Windows) | Windows 10 |
| `rhel810_raw_fallback_baseline.json` | `os_linux_rhel810_raw_fallback.jsonc` | OS (Linux) | RHEL 8.10 — Python raw fallback 경로 |

> 주석 예시는 채널/벤더 대표 1대 기준이라 baseline 과 장비가 정확히 같지는 않을 수 있다 (예: dell baseline = R740/iDRAC9, 주석 예시 = R760/iDRAC10 — 같은 Dell Redfish 채널 대표).

## mock-derived baseline 정책 (cycle 2026-05-12 신설)

> ADR-2026-05-12 Q6 결정 갱신 (2026-05-12 사용자 명시 승인): lab 부재 vendor 도 baseline_v1/ 에 추가 가능 — 단 **mock-derived marker 의무**.

mock-derived baseline 의 필수 marker (양쪽 모두):

1. **본 README 표 의 vendor 행 옆** "mock-derived (lab 부재 ...)" 명시
2. **baseline JSON 의 `diagnosis.details.baseline_origin`** 필드 — 출처 + cycle + NEXT_ACTIONS 교체 의무 명시
3. **호환 한글 주석본** (`schema/output_examples/{vendor}.jsonc`) 헤더에 "Lab 부재 — Mock 합성" 명시

회귀 비교 도구 (`tests/e2e/test_redfish_baseline.py` 등) 가 mock-derived baseline 을 사용할 때 의식할 점:
- mock-derived 통과 = 합성 fixture 통과 ≠ 사이트 통과
- NEXT_ACTIONS (`docs/ai/NEXT_ACTIONS.md`) 의 C1~C8 등 사이트 fixture 캡처 후속 작업 진행 시 mock-derived baseline 은 실측으로 교체 의무 (rule 13 R4 정신)
- mock-derived 가 실측 baseline 으로 잘못 인용되는 사고 차단을 위해 `diagnosis.details.baseline_origin` 자동 검사 hook 도입 검토 (NEXT_ACTIONS — 미래 작업)

### 한글 주석본을 보는 순서

1. **`schema/output_examples/redfish_dell_idrac10.jsonc` 부터 보세요.** Redfish 채널 전체 구조가 가장 자세히 설명되어 있습니다.
2. 그 다음 `esxi` / `ubuntu` / `windows` — 채널이 다르면 어떻게 달라지는지 비교.
3. `hpe` / `lenovo` / `cisco` — 같은 Redfish 채널 안에서 벤더별 차이점.
4. `rhel810_raw_fallback` — Python 이 없는 환경의 raw 모드 fallback 결과.

한글 주석 예시는 `schema/output_examples/` 에 채널/벤더 대표로 보존됩니다 (위 표 참조). JSON 표준은 주석을 허용하지 않아서 확장자가 `.jsonc` (JSON with Comments) 입니다. 운영 코드가 실제로 보내는 파일은 주석 없는 `.json` 입니다.

## 기준 시점

- 최초 수집일: 2026-03-23

## 변경이 필요할 때

1. 실장비에서 새로 응답을 수집한다 (`tests/redfish-probe/probe_redfish.py` 등).
2. 새 응답을 `baseline_v2/` 같은 별도 폴더로 저장한다.
3. 운영 변경 사유 / 검증 환경을 `tests/evidence/<날짜>-<주제>.md` 와 `docs/19_decision-log.md` 에 기록한다.
4. 회귀 비교 도구의 기준 폴더를 `baseline_v1` → `baseline_v2` 로 점진 전환한다.

본 폴더의 파일은 절대 in-place 로 덮어쓰지 않는다는 점이 핵심입니다 — 그래야만 회귀의 의미가 보존됩니다.

---

## 함께 보면 좋은 자료

| 자료 | 용도 |
|------|------|
| `tests/fixtures/` | 회귀 테스트의 입력 (raw 응답) |
| `tests/evidence/` | Round 단위 검증 결과 |
| [`../../docs/09_output-examples.md`](../../docs/09_output-examples.md) | 채널별 응답 실제 예시 |
| [`../../docs/13_redfish-live-validation.md`](../../docs/13_redfish-live-validation.md) | 실장비 검증 라운드 |
| [`../../docs/20_json-schema-fields.md`](../../docs/20_json-schema-fields.md) | envelope 13 필드 + 83 필드 의미 사전 |
