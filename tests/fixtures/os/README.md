# tests/fixtures/os

OS 채널(Linux / Windows) 수집 fixture. 하위 디렉터리별로 출처가 나뉜다.

| 디렉터리 | 내용 |
|---|---|
| `net/` | 네트워크 섹션 raw 응답 — Linux `ip`/`ethtool`, Windows `Get-NetAdapter` |

출처 기록은 각 하위 디렉터리의 README 를 본다 (rule 21 R2).
새 fixture 를 넣을 때는 어느 장비·OS 버전에서 어떤 명령으로 떴는지 함께 적는다.
