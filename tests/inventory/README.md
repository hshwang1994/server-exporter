# Test Inventory

> **이 폴더는** 회귀 테스트용 인벤토리 정책을 정리합니다.
> "기준선이 되는 baseline 장비" 와 "추가 검증용 supplemental 장비" 를 분리해서 관리하는 이유와 방법을 설명합니다.
> baseline 의 자격증명 / IP 변경은 회귀 의미를 깨뜨리므로 신중히 다룹니다.

## baseline vs supplemental 분리 원칙

### Baseline 장비 (기준선)
기존 `redfish-gather/inventory.sh` + `vault/<loc>/redfish/<vendor>.yml`(ansible-vault encrypted)로 관리.
baseline credential 변경 금지.

| 벤더 | vault 파일 | 비고 |
|---|---|---|
| Lenovo | vault/<loc>/redfish/lenovo.yml | baseline 고정 |
| HPE | vault/<loc>/redfish/hpe.yml | baseline 고정 |
| Dell | vault/<loc>/redfish/dell.yml | baseline 고정 (R740 기준) |
| Cisco | vault/<loc>/redfish/cisco.yml | baseline 고정 |

### Supplemental 장비 (추가 검증)
추가 evidence 수집 전용. baseline 정책을 변경하는 근거로 사용하면 안 됨.

credential은 다음 방식으로만 관리:
1. `tests/inventory/local/supplemental.ini` — gitignored 로컬 파일이라 저장소에는 없다.
   아래 사용 방법대로 샘플에서 복사해 만든다
2. `tests/vault/supplemental.yml` (ansible-vault encrypted)
3. 일회성 `--extra-vars` (디버깅 용도 한정)

### 사용 방법
```bash
# 1. 샘플 파일을 local/로 복사
cp tests/inventory/supplemental.sample.ini tests/inventory/local/supplemental.ini

# 2. 실제 credential 입력 (에디터로 편집)
vi tests/inventory/local/supplemental.ini

# 3. 실행
ansible-playbook redfish-gather/site.yml -i tests/inventory/local/supplemental.ini
```

### 주의사항
- 저장소에 commit 되는 파일에 평문 자격증명을 넣지 마세요.
- Dell R760 자격증명이 Dell baseline 과 다르다고 해서 세대별로 vault 를 쪼개면 안 됩니다 (baseline 의 의미가 깨짐).
- supplemental 장비는 baseline 정책을 변경하는 근거가 아니라, 추가 evidence 수집용입니다.

---

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| 정답지 (baseline) | [`schema/baseline_v1/`](../../schema/baseline_v1/) |
| Vault 운영 (회전 / 검증) | [docs/operate/05-vault.md](../../docs/operate/05-vault.md) |
| 실장비 검증 절차 | [docs/reference/live-validation.md](../../docs/reference/live-validation.md) |
