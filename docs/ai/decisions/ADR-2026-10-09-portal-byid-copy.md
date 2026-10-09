# ADR-2026-10-09 — `Jenkinsfile_portal_Byid` 사본 유지 · portal 과 동기화 강제

- 상태: Accepted (2026-10-09, 사용자 결정 "맞춰라 … 승인한다")
- 관련: CONVENTION_DRIFT DRIFT-019 · rule 80 R1 · rule 00 · `docs/ai/catalogs/JENKINS_PIPELINES.md`

## 컨텍스트 (Why)

- 2026-10-08 GitLab 관리자가 웹 편집으로 `Jenkinsfile_portal` 의 통째 사본 `Jenkinsfile_portal_Byid` 를 main 에 올렸다(`87c47f8d` · `09fb4890` → 병합 `2cd63067`).
  원본과 차이는 `inventory_json` 의 `defaultValue: '[{"bmc_ip":"","by_id":""}]'` 1줄이다. 줄끝만 `1566454a` 에서 LF 로 맞췄다.
- rule 80 · rule 00 은 "파이프라인은 `Jenkinsfile_portal` 하나" 라고 적고 있었고(2026-09-28 portal 사본 삭제), 결정 전에는 사본을 고치지 않기로 했다(DRIFT-019).
- 2026-10-09 로그 문구 작업지시서가 Byid 에도 같은 표현을 적용하라고 해서 내용을 portal 과 맞췄다(`11907cb6` · `2c6d71f3`). 사용자는 같은 날 "맞춰라" 로
  사본을 유지하고 portal 과 맞추는 쪽을 골랐다.
- 이 Jenkins(jenkins-prod `clovirone-cicd`)에는 Byid 를 Script Path 로 쓰는 Job 이 없다(2026-10-09 Job 목록 확인). production 생성 대상(`production_manifest.yml`)도 아니다.

## 결정 (What)

1. `Jenkinsfile_portal_Byid` 를 지우지 않고 유지한다. 내용은 `Jenkinsfile_portal` 과 같고 `inventory_json` 파라미터 이름 바로 다음의 기본값 1줄만 다르다.
2. `Jenkinsfile_portal` 을 고치면 같은 커밋에서 Byid 를 다시 만든다(portal + 고유 1줄). `tests/unit/test_jenkinsfile_portal_byid_sync.py` 가 차이 · 위치 · 줄끝을 강제한다
   (Gate 의 `tests/unit` 에서 돈다 — 맞추지 않으면 CI Gate FAIL).
3. Byid 는 main 에만 둔다(production 생성 대상 아님). Byid 를 production 브랜치에서 쓰는 Job 이 생기면 그때 `production_manifest.yml` 포함을 따로 정한다.

## 결과 (Impact)

- portal 변경 때 손이 하나 더 간다(사본 재생성 1회). 대신 사본이 조용히 어긋나는 일은 시험이 막는다.
- rule 80 · rule 00 의 "파이프라인은 하나" 서술을 "실행 정본은 portal, Byid 는 동기화된 사본" 으로 고쳤다. DRIFT-019 는 resolved.
- 수집 동작 · production tree 변화 없음(Byid 는 runtime 대상이 아니다).

## 대안 비교 (Considered)

- *원본에 기본값만 반영하고 사본 삭제* — 거부. 기본값 `[{"bmc_ip":"","by_id":""}]` 는 Byid 용 입력 형식이라 portal 기본값으로 쓰면 다른 호출자의 기본 입력이
  바뀐다. 사본을 올린 쪽(GitLab 관리자)이 쓰는 Job 이 이 Jenkins 밖에 있을 수 있어 삭제는 되돌리기 어렵다.
- *사본 유지 · 동기화는 사람 손에만 맡김* — 거부. DRIFT-019 의 영향("원본 수정이 사본에 따라가지 않는다")이 그대로 남는다.
- *portal 을 파라미터 기본값만 다르게 생성하는 생성기* — 거부. 1줄 차이에 생성 단계를 더하는 것은 과하다. 시험 한 개로 충분하다.
