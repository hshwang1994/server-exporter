# tests/inventory: 보조 검증 장비 인벤토리

회귀 시험의 기준이 되는 장비(기준선)와 추가 검증용 장비(보조)를 나눠 다루는 이유와 방법입니다. 기준선 장비의 IP와 계정을 바꾸면 회귀의 의미가 깨지므로 신중히 다룹니다.

## 기준선 장비

기준선 장비는 운영과 같은 방식으로 수집합니다. 계정은 `vault/common/redfish/standard.yml`(Redfish 표준 계정)과 `vault/<loc>/...`(OS, ESXi, Redfish 복구)에 있고, 기준선 계정은 바꾸지 않습니다.

| 벤더 | 장비 | 기준선 파일 |
|---|---|---|
| Lenovo | ThinkSystem SR650 V2 | `schema/baseline_v1/lenovo_baseline.json` |
| HPE | ProLiant DL380 Gen11 | `schema/baseline_v1/hpe_baseline.json` |
| Dell | PowerEdge R740 | `schema/baseline_v1/dell_baseline.json` |
| Cisco | UCS C220 M4 | `schema/baseline_v1/cisco_baseline.json` |

## 보조 장비

추가 증거를 모으기 위한 장비입니다. 기준선 정책을 바꾸는 근거로 쓰지 않습니다. 계정은 다음 방식으로만 둡니다.

1. `tests/inventory/local/` 아래 보조 인벤토리 ini (`.gitignore`에 있어 저장소에 없습니다)
2. `tests/inventory/local/` 아래 ansible-vault로 암호화한 yml (저장소에 없습니다)
3. 일회성 `--extra-vars` (디버깅 용도)

```bash
# 저장소 루트
cp tests/inventory/supplemental.sample.ini tests/inventory/local/supplemental.ini
vi tests/inventory/local/supplemental.ini          # 실제 계정 입력
ansible-playbook redfish-gather/site.yml -i tests/inventory/local/supplemental.ini
```

## 주의

- 저장소에 commit되는 파일에 평문 계정을 넣지 마세요.
- 같은 벤더의 다른 세대 계정이 다르다고 해서 세대별로 vault를 쪼개지 마세요. 기준선의 의미가 깨집니다.

## 다음

| 다음 작업 | 문서 |
|---|---|
| 기준선 | `schema/baseline_v1/README.md` |
| vault 운영 | `docs/operate/05-vault.md` |
| 실장비 검증 | `docs/reference/live-validation.md` |
