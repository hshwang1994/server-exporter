# Redfish `LinkStatus` 값 분포

## 미러 원문 18 label

| `LinkStatus` 값 | 수 | 상위 리소스 형식 |
|---|---|---|
| LinkUp | 86 | Port 53, EthernetInterface 33 |
| LinkDown | 81 | Port 60, EthernetInterface 21 |
| NoLink | 43 | Port 37, EthernetInterface 6 |
| Down | 14 | NetworkPort 14 |
| null | 13 | HpeNetworkAdapter 8, EthernetInterface 5 |
| Disconnected | 4 | DellAttributes 4 |
| Up | 2 | NetworkPort 2 |

- `Enabled` · `Active` · `Connected`: Enabled 0 · Active 0 · Connected 0
- 키가 `..._LinkStatus` 로 끝남(BIOS 속성 — 링크 키 아님): Connected 24, Disconnected 20

## 저장소 fixture (골든 제외)

| `LinkStatus` 값 | 수 | 상위 리소스 형식 |
|---|---|---|
| LinkUp | 123 | EthernetInterface 72, Port 51 |
| LinkDown | 61 | Port 35, EthernetInterface 26 |
| null | 45 | EthernetInterface 41, HpeNetworkAdapter 4 |
| NoLink | 22 | Port 16, EthernetInterface 6 |
| Down | 16 | NetworkPort 16 |
| Up | 4 | NetworkPort 4 |

- `Enabled` · `Active` · `Connected`: Enabled 0 · Active 0 · Connected 0
- 키가 `..._LinkStatus` 로 끝남(BIOS 속성 — 링크 키 아님): Disconnected 12, Connected 12
