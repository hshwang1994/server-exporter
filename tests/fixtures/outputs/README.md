# tests/fixtures/outputs

**완성된 envelope** fixture. 위 계층의 fixture 가 "외부 시스템 raw 응답"인 것과 달리,
여기 있는 것은 normalize 를 다 거친 최종 출력이다. envelope 형식 회귀와 status 판정
회귀가 이걸 입력으로 쓴다.

| 파일 | 쓰임 |
|---|---|
| `dell_r760_output.json` | Dell PowerEdge R760(iDRAC9) 성공 envelope. 13 필드 형식 회귀 |
| `status_success_with_warnings.json` | 시나리오 B — `errors[]` 가 있는데 `status=success` 인 경우. rule 13 R8 매트릭스 회귀 |

시나리오 B 는 모순이 아니라 의도된 동작이다. 섹션이 전부 성공했는데 경고성
`errors[]` 만 있는 상태를 가리킨다. 이 fixture 는 그 판정이 바뀌지 않게 잡아 둔다.

`schema/baseline_v1/*.json` 과는 다르다. 저쪽은 vendor 별 회귀 기준선이고
갱신하려면 실장비 근거가 필요하다 (rule 13 R4). 이쪽은 형식 검증용 고정 입력이다.
