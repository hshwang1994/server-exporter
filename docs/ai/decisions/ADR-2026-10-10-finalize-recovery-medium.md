# ADR-2026-10-10 — 결과 확인의 회수 매체 선택 (중간 전달본 · 마지막 보관본)

- 상태: Accepted (2026-10-10, 검수 후속 작업지시서 C1 · 사용자 보정 1 · 2 반영)
- 관련: rule 80 R1 · `Jenkinsfile_portal` `seFinalizeIn` ① · `docs/operate/04-pipeline-runtime.md` 8절 · Harness `recover_*`

## 컨텍스트 (Why)

- 결과 확인은 `unstash 'gather-output'` 이 되면 그 전달본(stash)을 무조건 썼다. stash 이름은 하나라 실행 기반 장애로 다시 시도하기 전에 넘긴 **중간** stash 가
  남아 있으면, 마지막 보존의 stash 가 실패하거나 끊긴 빌드에서 마지막 보존이 보관(archive)한 전체 결과 대신 중간의 일부 결과 + 실패 결과를 보냈다(검수 C1).
- 보관본의 원본 파일(`gather_output.json` · `gather_checkpoint.jsonl` · `gather_run.json`)은 마지막 보존만 저장하지만, 정리 결과 파일(`gather_final.jsonl` · report)은
  결과 확인 ⑦ 도 그 진입이 고른 입력에서 다시 저장한다 — 출처 가정만으로 고를 수 없다.

## 결정 (What)

1. 마지막 보존의 stash 가 끝났을 때만 `SE_FINAL_STASHED=true` 를 세운다(그 stash 직전 · 중간 보존 직전 · 수집 단계 시작에서 지운다).
2. 회수는 매체마다 격리 폴더(`fin-<번호>/rec-<진입>/stash` · `/archive`)에 받는다. unstash 가 예외면 그 폴더를 쓰지 않는다. 매체 사이에 파일을 섞지 않는다.
3. 표식이 있고 그 stash 의 정리 결과가 접수 대상마다 1줄이면 stash 를 쓴다(보관본 조회 없음). 그 밖에는 보관본도 파일별로 받아 두 후보를 **기존 검문**
   (정리 결과 → 보충 조립 → 원본 줄)으로 평가하고, 결과가 있는 대상(OUTPUT · CHECKPOINT, 새로 만든 실패 결과 제외)이 많은 쪽 → 같으면 정리 결과가 완결인 쪽 →
   같으면 표식이 있으면 stash, 없으면 보관본을 고른다. CHECKPOINT 만 있는 보관본도 보충 조립으로 쓴다.
4. 정리 결과 파일은 고른 입력에 있을 때만 다시 보관하고, 요약 · 본문 보관과 따로 기록한다(`.se_fin.json`). 보관 완료 = 수행한 보관이 모두 성공. 결과 파일 링크는
   실제로 보관한 것만. 선택 근거는 `finalize_summary.json` 의 `recovery`.

## 결과 (Impact)

- 보통 경로(마지막 보존의 stash 성공 · 정리 결과 완결)는 종전과 같고 보관본을 조회하지 않아 회수 시간이 늘지 않는다.
- 마지막 stash 실패 · 끊김 빌드는 보관본의 전체 결과를 보낸다(Harness `recover_final_archive_over_snapshot` · `recover_flag_unwritten_archive`: 3대 중 2대 + 실패 1대 → 3대).
  보관본 회수가 실패하거나 일부뿐이면 stash 의 유효한 결과를 버리지 않는다(`recover_archive_unavailable_stash` · `recover_partial_archive_keeps_stash`).
- 새 상태 저장소 · 큐 · 시간 한계는 없다. 재진입은 새 진입 번호의 격리 폴더를 쓴다.

## 대안 비교 (Considered)

- *항상 보관본 우선* — 거부. 보관 실패 · 일부 회수 때 유효한 stash 를 버린다(사용자 보정 2: OUTPUT 일부 · 정리 결과 회수 실패 대조).
- *`archive_files` 성공 목록 · 파일 존재로 매체 결정* — 거부(사용자 보정 2). 존재는 유효성 · 접수 대상 범위를 말하지 않는다.
- *stash 이름을 중간/마지막으로 나누기* — 거부. 같은 빌드 안에서 이름을 늘려도 끊긴 마지막 stash 의 성공 여부는 따로 기록해야 하고, 보관 실패 경로는 여전히 평가가 필요하다.
