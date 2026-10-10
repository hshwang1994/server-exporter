# AI 문서 지도

여기 있는 문서는 **AI가 개발 작업을 하려고 읽는 것**이다. `production` 브랜치에는
나가지 않는다 (`production_manifest.yml` 의 runtime roots 밖이라 prodgen 생성 tree 에 들어가지 않는다).

사람이 읽는 문서는 `docs/README.md` 에서 시작한다.

## 어디에 무엇이 있나

| 위치 | 성격 | 언제 읽나 |
|---|---|---|
| `contracts/` | 지금도 유효한 계약 | 계정 쓰기·자격증명·시리얼·에러 메시지를 건드릴 때 |
| `catalogs/` | 주기적으로 재측정하는 현황표 | 벤더·필드·테스트 현황이 필요할 때 |
| `decisions/` | ADR — 왜 이렇게 정했나 | 기존 결정을 뒤집으려 할 때 |
| `references/` | 외부 API 레퍼런스 사본 | Ansible·Redfish·vSphere 문법이 필요할 때 |
| `policy/` | 하네스 운영 정책 | 보안·회전 절차 |
| `archive/` | 지나간 것 | 보통 안 읽는다 |

`CURRENT_STATE.md` 와 `NEXT_ACTIONS.md` 는 훅이 갱신을 권고하는 파일이다.

## 읽기 전에 알아 둘 것

**정본은 코드다.** 이 디렉터리의 문서와 코드가 다르면 코드가 맞다. 문서 쪽을 고쳐라.
`CLAUDE.md` §2 가 그 우선순위를 정해 두었다.

**세어 놓은 수를 믿지 마라.** 어댑터 개수, fixture 개수, 파일 줄 수 같은 건 문서에
적어 두면 곧 틀린다. 실제로 `field_dictionary` 항목 수가 저장소 안에서 다섯 가지 값으로
갈렸던 적이 있다. 필요하면 그때 세라 — 세는 명령은 `.claude/rules/00-core-repo.md` 에 있다.

**주석도 믿지 마라.** 2026-08-13 실측에서 코드 주석이 코드와 어긋난 곳이 여러 건 나왔다.
대표적으로 `precheck_bundle.py:92-99` 는 "os 채널은 production 에서 호출되지 않는다" 고
적지만 실제로는 호출된다.

## 사람용 문서를 고칠 때

`docs/` 아래 사람용 문서는 `production` 브랜치로 나간다. 그래서 거기서 `docs/ai/`,
`.claude/`, `scripts/ai/` 를 참조하면 **배포본에서 깨진 링크**가 된다.

`scripts/ai/verify_docs_references.py` 가 문서가 가리키는 저장소 경로의 실존을 검사한다.
`verify_harness_consistency.py` 는 `.claude/` 안쪽만 보므로 이 검사가 따로 필요하다.
