# 2026-10-04 — 복구 훈련: 실제 legacy baseline `4ce90a00` 을 복제한 두 bare 원격에서 B → P1 → P2 → R(B) → P3

검토 C2 의 요구("실제 `4ce90a00` baseline 을 복제한 임시 저장소 훈련")에 대한 기록. **실 원격(GitHub·GitLab)은 건드리지 않았다** — 복제본의 `origin` 원격을 먼저 제거하고
임시 bare 원격 2개(`origin`·`internal` 이름만 같다)를 붙였다. 훈련 뒤 실 저장소: HEAD `ae4db48b`, `refs/heads/production` = `4ce90a00`, `git ls-remote origin/internal production` = `4ce90a00`(변경 0).

## 조건 (운영 승격과 다른 점을 그대로 적는다)

| 항목 | 값 |
|---|---|
| 스크립트 | 세션 scratchpad `drill_4ce90a00.py`(저장소 밖, 일회성) — `git clone -n --no-local <실 저장소>` → `git remote remove origin` → `update-ref refs/heads/production 4ce90a00` → bare 2개에 `main`·`production` push |
| 생성기 | 작업 트리의 prodgen(검토 C1~C4 보완본, 커밋 전) — **tree 는 object store 의 `ae4db48b`**(X), manifest 는 실 저장소 파일 |
| live gate | **G11 G12 G13 G14 G15 G19 는 stub PASS**(이 Windows 세션에 WSL/ansible/Jenkins 린터 바인딩이 없다). G01~G10 · G16 · G17 · **G18 · G20 과 plumbing·publish 는 실제** |
| E2E · CI stage 증거 | **합성**(`note: SYNTHETIC drill evidence`) — 이 훈련은 X 의 검증이 아니라 복구 **기구**의 검증이다 |
| 배포 정책 | `DEPLOY_REMOTES=(origin, internal)` 그대로(bare 2개가 그 이름) |

## 전이 기록 (`drill_log.txt`)

| 단계 | 결과 |
|---|---|
| B | local = origin = internal = `4ce90a00`, state **LEGACY** ok(bootstrap 명시 시), tree OID `2f55bdbc9f41` |
| ① 정상 승격(baseline 미지정) | **거부** `stage=verify` — G18(LEGACY 는 기본 거부)·G20 FAIL → verdict FAIL. 원격·로컬 변경 0 |
| ② `--bootstrap-baseline 4ce90a00` | **P1 `c668c34c`** — parent B, trailer `Bootstrap-Baseline=4ce90a00` · `Bootstrap-Baseline-Tree=2f55bdbc` · `Main-SHA=ae4db48b` · `Tree-Hash=05ce23c3…`(192 파일) · `Verdict=COMPLETE_PASS`(stub 포함) · `CI-Stages=verified`; publish `origin`·`internal` 모두 사전/사후 ls-remote 일치, 로컬 ref 갱신. state PROVENANCE |
| ③ 정상 승격(같은 X) | **P2 `74ac5abc`** — parent P1, `Bootstrap-Baseline` **계승**(검토 C2), `Previous-Production=P1`. `baseline_record(P2, B)` → P2(가장 가까운 기록 커밋) |
| ④ `restore --to B`(baseline 인자 없음) | **거부** — "legacy tree 는 `--bootstrap-baseline <that sha>` 로만" |
| ④' `restore --to B --push-remote origin`(한 원격) | **거부** — 배포 정책(정확히 `origin,internal`) — 한 원격만 옮기면 두 원격이 어긋난다 |
| ④'' `restore --to B --bootstrap-baseline B --push-remote origin,internal` | **R `6078c716`** — tree OID `2f55bdbc9f41` == `git rev-parse 4ce90a00^{tree}` **True**, parent P2, `Restore-From=P2` · `Baseline-Recorded-By=P2` · `Bootstrap-Baseline=B`; 양 원격 = 로컬 = R; `classify_production(R)` = **RESTORED_BASELINE**, `previous_generated=P2`; `drift-check` mode RESTORED_BASELINE ok |
| ⑤ 정상 승격(R 위) | **P3 `9ea89deb`** — parent R, `Bootstrap-Baseline=B`, `Previous-Production=R`; 양 원격 = 로컬 = P3 |

first-parent 이력: … `4ce90a00`(B) → `c668c34c`(P1) → `74ac5abc`(P2) → `6078c716`(R) → `9ea89deb`(P3). P1·P2·P3 의 tree OID 는 같다(`1a98670fbf57`, 같은 X 에서 생성 — 결정성).

## 이 훈련이 말하는 것 / 말하지 않는 것

- 말하는 것: 연속 정상 승격 뒤에도 최초 baseline 으로 돌아갈 수 있다(C2 보완), R 의 tree 가 B 와 바이트 단위로 같다(tree OID), 양 원격 ff publish 와 로컬 ref 정합, 한 원격만 지정한 복구는 정책이 막는다, 복구 뒤 재승격이 R 을 parent 로 이어진다.
- 말하지 않는 것: X(또는 X2)의 live gate 통과(stub), 실 GitHub/GitLab 의 push 권한·branch protection(실 push 로만 확인), production Job 의 checkout(승격 뒤 canary). 실 운영 복구는 `docs/operate/09` §5 의 명령을 **실 원격**에 대해 실행하는 것이며 이번에 하지 않았다.
