# 2026-10-04 — GP-36: `.161` host `duration_ms` +1.9 s 의 task 단위 분석 (legacy production #59~#63 vs X6 main #56~#60)

> 작성: 세션 서브에이전트(읽기 전용 — Jenkins artifact/console GET · 두 SHA 의 `git show/diff`). 원본과 CSV 는 세션 scratchpad `gp36/`. 결론: 어느 gather task 도 느려지지 않았고, 차이의 59~74 % 는 `meta.duration_ms` 창이 Add-on·CHECKPOINT 뒤로 옮겨진 측정 정의 차이, 잔여 +0.4~0.7 s 는 통계적으로 한계(p=0.068)다. 코드 변경 없음.

# GP-36 report: why host 10.100.64.161 is +1.9 s slower per host (legacy production #59-#63 vs new main #56-#60)

Date: 2026-10-04. Method: read-only HTTP GET against Jenkins (artifacts, consoleText, api/json) + read-only `git show/diff/grep` of two SHAs (`4ce90a005307` = legacy production, `70e4ec8ab483` = new main). The git working tree and Jenkins were not modified.
Tags: [MEASURED] taken directly from artifacts, [DERIVED] arithmetic on measured values, [STATIC] read from code at the two SHAs (not a timing), [UNMEASURED] no data exists in the artifacts.

## 0. Answer

1. [MEASURED] Confirmed: .161 `meta.duration_ms` median 12.635 s (legacy) -> 14.526 s (new) = **+1.891 s (+15.0%)**; mean +1.732 s. Welch t=7.82, p=0.0002 (n=5 vs 5, interleaved A/B runs), so the increase is real in the metric.
2. [UNMEASURED] **A legacy-vs-new per-task comparison cannot be produced from the artifacts.** The production Job (legacy runtime) archives no artifacts at all (`gather_progress.jsonl` and `callback_body.json` return HTTP 404 for #59-#63) and its console has only the final envelope lines (no per-task lines, no per-line timestamps). Even the new runtime's `gather_progress.jsonl` has only ~10 milestone events per host, not one per task.
3. [STATIC+MEASURED] **What the numbers do show is a change in what `duration_ms` covers.** In the legacy runtime `finished_at` is stamped by `normalize | build_meta` and the Add-on runs *before* it; in the new runtime the Add-on runs *after* assembly and `addon | combine into output` re-stamps `finished_at`/`duration_ms` at the very end. So the new window additionally contains 15 assembly tasks (`linux | build_correlation` ... `linux | inject schema_version`) plus the new `CHECKPOINT` task that the legacy window never counted. Measured on the new side that tail costs **1.12 s median (1.29 s mean) on .161** (1.58 s on .162, 1.58 s on .163).
4. [DERIVED] Like-for-like (new final duration minus that tail): .161 **+0.67 s median / +0.44 s mean (+5.3% / +3.5%), Welch p=0.068 (marginal)**. So about 59-74% of the +1.7..+1.9 s is window accounting (an upper bound: B also contains the new `CHECKPOINT` task itself, real new work of unknown size), and what is left is small and statistically marginal.
5. [DERIVED] Control hosts, like-for-like: .162 -3.30 s (-17.3%), .163 -2.72 s (-14.7%). The headline -8.2% / -7.0% *understates* their real gain by the same ~1.6 s window effect. .162/.163 (`python_ok`) also had python-module-only remote tasks consolidated into raw calls in the new code (static example: `gather_users` `getent` x2 + `shell` -> 1 `raw`; `setup` is still used for them), a gain .161 cannot get because it was already on the raw path (python 3.6.8, `python_incompatible`); so .161 mostly sees the window effect.
6. Conclusion on concentration: **the +1.9 s is not concentrated in any gather task.** It is (a) the 15-task assembly tail + `CHECKPOINT` that moved inside the measured window (about 59-74%), plus (b) a residual of +0.4..+0.7 s that lives somewhere in {core gather, Add-on wrapper tasks, CHECKPOINT callback fsync} and cannot be split with this data; no gather task was found slower (the raw-path core has 4 fewer SSH `raw` calls in the new code).
7. To split the residual a per-task ms trace of ONE run per runtime is needed (see section 9). I did not run anything against hosts or Jenkins.

## 1. What data exists

| builds | Job | SHA | `gather_progress.jsonl` | `callback_body.json` | other artifacts | console |
|---|---|---|---|---|---|---|
| prod #59-#63 | `clovirone-server-gather` (production) | `4ce90a005307` | **HTTP 404** (no file) | **HTTP 404** | none (`api/json` `artifacts[]` empty) | yes: 4 envelope JSON lines/build, no per-task lines, no per-line timestamps |
| main #56-#60 | `clovirone-server-gather-main` | `70e4ec8ab483` | HTTP 200, 44 lines each | HTTP 200 | `gather_checkpoint.jsonl`, `gather_final.jsonl`, `gather_output.json`, `gather_manifest.json`, `gather_rc.txt`, `finalize_summary.json`, `gather_finalize_report.json` | yes |

- Files saved here: `main_<n>_progress.jsonl`, `main_<n>_callback.json`, `main_<n>_gather_*.jsonl/json`, `main_<n>_console.txt`, `prod_<n>_console.txt`. `prod_<n>_progress.jsonl` / `prod_<n>_callback.json` do **not** exist (the 404 HTML pages were deleted so they cannot be mistaken for data).
- Legacy per-host `meta.duration_ms` comes from the envelope lines in the prod consoles (4 unique envelopes per build). New-side values come from `callback_body.json` -> `gatherInfoJson`; cross-checked against console and `gather_final.jsonl` for 20 host-builds: **0 mismatches**.
- Timestamper plugin (1.30) is installed but recorded no per-line times for any of the 10 builds (`/timestamps/?...` returns untimed lines), so no legacy console timing either.
- Design: the 10 runs alternated in time (start stamps: prod#59, main#56, prod#60, main#57, prod#61, main#58, prod#62, main#59, prod#63, main#60; no overlap), so clock/host drift is controlled. Same Add-on revision `c9a4c3825fc4` in all 10, same venv (`/app/ansible-env`, Python 3.12.9, ansible-core 2.20.3). Gather Runner varies per build (R01-R04) - checked in section 6.
- `ansible.cfg` is identical in both SHAs (`forks = 200`); the new Jenkinsfile passes `-f 4`. With <=4 hosts per play concurrency is identical, so this is not a plausible factor (not separately measured).

## 2. Inferred schema of `gather_progress.jsonl`

One JSON object per line, UTF-8, append order = time order. Verified against code (`callback_plugins/json_only.py` `_progress`/`_now_iso`).

| field | meaning |
|---|---|
| `ts` | ISO-8601 UTC, **whole seconds, truncated** (`isoformat(timespec='seconds')`). Calibration: `ts(emitted) - final.finished_at` has mean -0.26 s over 15 samples and 0 violations of `ts >= floor(finished_at)`, i.e. truncation, so an event's unbiased time is `ts + 0.5 s`. |
| `host` | inventory host name (= IP here); `null` on play-level `inventory` events |
| `ip` | host IP (equals `host` for host events) |
| `event` | `inventory`, `first_seen`, `precheck`, `cred_load`, `auth_proven`, `checkpoint`, `addon_started`, `addon_done`, `emitted` (code also defines `lost`; none occurred) |
| `task` | name of the task whose result produced the event (or play name for `inventory`) |
| `detail` | always `null` in these builds |
| extras | `hosts` (inventory), `diagnosis` (precheck), `location` + `outcome` (cred_load) |

Events are **milestones, not every task**: 44 lines/build = 4 `inventory` + 10 per Linux host (`first_seen`, `precheck`, `cred_load` x2, `auth_proven`, `precheck`, `checkpoint`, `addon_started`, `addon_done`, `emitted`). There are ~150 tasks per Linux host, so "per-task elapsed" is only available per event segment (time since the host's previous event; 1 s quantisation, +-1 s per value). The event/shape sequence is identical in all 5 builds for every host.

## 3. Per-host totals [MEASURED]

Seconds, `meta.duration_ms`/1000. n=5 builds per side. `new ckpt` = the `CHECKPOINT` envelope's `duration_ms` (stamped at `build_meta`, **before** the Add-on).

| host | gather mode | legacy median (mean) | new final median (mean) | delta median | delta mean | Welch p | new ckpt median |
|---|---|---|---|---|---|---|---|
| .161 | raw fallback (`python_incompatible`, py 3.6.8) | 12.635 (12.645) | 14.526 (14.376) | +1.891 (+15.0%) | +1.732 | 0.0002 | 10.562 |
| .162 | python mode (`python_ok`, py 3.9.16) | 19.061 (18.724) | 17.507 (17.559) | -1.554 (-8.2%) | -1.165 | 0.0060 | 13.497 |
| .163 | python mode (`python_ok`, py 3.9.21) | 18.490 (18.251) | 17.187 (17.260) | -1.303 (-7.0%) | -0.991 | 0.0215 | 13.039 |
| .120 (Windows, out of scope) | winrm | 97.187 (96.841) | 74.513 (75.201) | -22.674 (-23.3%) | -21.640 | - | 52.265 |

Raw values (s): legacy .161 [12.48, 12.41, 12.635, 12.706, 12.992]; new .161 [13.652, 14.319, 14.583, 14.801, 14.526]; legacy .162 [19.109, 17.948, 18.315, 19.188, 19.061]; new .162 [17.507, 17.146, 17.488, 17.964, 17.692]; legacy .163 [18.49, 17.564, 17.645, 18.537, 19.018]; new .163 [16.781, 17.181, 17.227, 17.922, 17.187]. Spread: .161 legacy sd 0.227 s, new sd 0.440 s.

## 4. Per-task timing

### 4a. Requested table: top 15 tasks by absolute delta for .161

**Cannot be produced per task**: legacy per-task times are [UNMEASURED] (section 1). The closest honest equivalent is a table of *task groups* whose time is measurable on at least one side. Medians, seconds.

| rank | task group | legacy median s | new median s | delta s | basis |
|---|---|---|---|---|---|
| 1 | Tail after `normalize \| build_meta`: 15 assembly tasks (`linux \| build_correlation` ... `linux \| inject schema_version`, see section 5) + new `CHECKPOINT` | 0.00 (outside legacy window by construction) | 1.12 (mean 1.29; range 1.02-1.78) | **+1.12** | new: [MEASURED]; legacy: [STATIC] (`finished_at` stamped at build_meta) |
| 2 | Everything that is inside *both* windows: core gather (`init_fragments` ... `hba_ib`, `normalize \| build_meta`, ~95 tasks) **plus** the Add-on region | 12.635 | 13.300 (= final - row 1; mean 13.088) | **+0.665** (mean +0.443) | [DERIVED]; core vs Add-on region cannot be separated (legacy ran the Add-on before build_meta) |
| 3 | any individual gather task (`linux \| system \| raw gather`, `linux \| storage \| raw gather`, `linux \| users \| raw getent + last logins`, ...) | [UNMEASURED] | [UNMEASURED] | [UNMEASURED] | no per-task data on either side |

Rows 1+2 add up to the total: with means +1.29 + +0.44 = +1.73 s = measured mean delta +1.732 s (exact per build); with medians +1.12 + +0.67 = +1.79 s vs +1.891 s (a median of sums is not a sum of medians).

### 4b. New-side event segments for .161 [MEASURED, new runtime only]

Each row is the time from the host's previous event to this event (so it covers every task in between). Seconds, over 5 builds; values are whole-second quantised. Legacy: [UNMEASURED].

| seq | event | ending task | median | mean | min-max | legacy | what lies in the segment (static, new SHA) |
|---|---|---|---|---|---|---|---|
| 1 | precheck | precheck \| 공통 diagnosis 생성 | 5.0 | 4.80 | 4-5 | [UNMEASURED] | precheck_bundle TCP/protocol probe (Play 1; outside `duration_ms`) |
| 2 | cred_load | credential \| expose scope | 1.0 | 0.60 | 0-1 | [UNMEASURED] | credential vault scope (outside `duration_ms`) |
| 3 | cred_load | credential \| classify load outcome | 1.0 | 1.40 | 1-2 | [UNMEASURED] | credential load/classify (outside `duration_ms`) |
| 4 | auth_proven | os \| try_one_credential \| linux ssh probe | 2.0 | 1.60 | 1-2 | [UNMEASURED] | SSH probe `raw` (outside `duration_ms`) |
| 5 | precheck | linux \| build diagnosis (success path) | 12.0 | 11.60 | 11-12 | [UNMEASURED] | ~1.6 s from the probe to `init_fragments` (rest of try_credentials, `linux \| preflight` incl. 1 `raw`; outside `duration_ms`), then system, cpu, storage, network, users, hba_ib gather (7 `raw` calls inside the window) up to `linux \| build diagnosis`; the window opens in this segment |
| 6 | checkpoint | CHECKPOINT | 2.0 | 1.80 | 1-2 | [UNMEASURED] | `set output meta vars`, `resolve vendor` x3, `build_meta`, then tail B (15 tasks) + `CHECKPOINT` (callback append+fsync) |
| 7 | addon_started | ADDON_START | 1.0 | 0.80 | 0-1 | [UNMEASURED] | `include_tasks linux \| addon`, `addon \| locate`, `ADDON_START` (3 controller tasks) |
| 8 | addon_done | ADDON_DONE | 2.0 | 2.00 | 2-2 | [UNMEASURED] | `addon \| reset result`, `include_role` (Add-on proper, remote), `addon \| result`, `addon \| combine into output`, `ADDON_DONE` |
| 9 | emitted | OUTPUT | 0.0 | 0.00 | 0-0 | [UNMEASURED] | `OUTPUT` |

Sum of medians first_seen -> emitted = 26.0 s; the `duration_ms` window (median 14.53 s) is the slice from `started_at` (about 1.5 s after the SSH-probe event) to the `combine` task just before `ADDON_DONE`.

## 5. What `meta.duration_ms` covers in each runtime [STATIC, from code at the two SHAs]

`started_at`/`_started_epoch` are stamped in `common/tasks/normalize/init_fragments.yml` (task `normalize | init_fragments | timestamp`), `finished_at`/`duration_ms` in `common/tasks/normalize/build_meta.yml`. Both files are **identical** in the two SHAs and everything before the gather tasks is identical. What changed is where the Add-on sits and a new re-stamp. Order of the Linux play (raw path):

Legacy (`4ce90a005307`):
1. `normalize | init_fragments | timestamp` -> `started_at` stamped (**window opens**)
2. gather tasks (system, cpu, memory, storage, network, users, hba_ib) and their merges
3. `linux | addon` region: `addon | locate`, (missing-add-on fragment + merge: skipped at runtime), `addon | reset result`, `include_role` Add-on, `addon | result fragment`, `addon | merge result fragment` (+3 `normalize | merge_fragment` set_facts)
4. `linux | build diagnosis (success path)`, `linux | set output meta vars`, `resolve vendor` x3
5. `normalize | build_meta` -> `finished_at` + `duration_ms` stamped (**window closes**)
6. outside the window: the 15 tail tasks listed below, then `OUTPUT`

New (`70e4ec8ab483`):
1. `normalize | init_fragments | timestamp` -> `started_at` stamped (**window opens**)
2. gather tasks and their merges (same list; 4 fewer SSH `raw` calls)
3. `linux | build diagnosis (success path)`, `linux | set output meta vars`, `resolve vendor` x3
4. `normalize | build_meta` -> `finished_at` of the `CHECKPOINT` envelope (what the legacy window would have ended at)
5. **tail B** = the same 15 tail tasks listed below
6. new `CHECKPOINT` (debug `to_json` of the whole envelope; callback JSON append + flush + fsync + progress event)
7. `linux | addon` region: `addon | locate`, new `ADDON_START`, `addon | reset result`, `include_role` Add-on (`apply.timeout`), `addon | result`, new **`addon | combine into output` -> re-stamps `finished_at` + `duration_ms` (the final window closes here)**
8. outside the window: `ADDON_DONE`, `OUTPUT`

The 15 tail tasks (identical task list in both SHAs, from the static sequence): `linux | build_correlation` (include) and `normalize | build_correlation`; `linux | build output` (include); `os | normalize | build_sections` (include) and `normalize | build_sections`; `os | normalize | build_status` (include) and `normalize | build_status`; `os | normalize | build_errors` (include) and `normalize | build_errors`; `os | normalize | set output meta (defaults preserve)`; `os | normalize | build_output` (include), `normalize | build_output | ensure failed diagnosis` (skipped on the success path), `normalize | build_output | resolve hostname + source`, `normalize | build_output`; `linux | inject schema_version`.

Consequences: legacy window = core + Add-on(legacy style). New final window = core + **tail B** (15 tasks + `CHECKPOINT`) + Add-on(new style). New ckpt window = core only. The re-stamp only happens when `ADDON_DIR` is set, which is the case for all 10 runs (the envelope has `data.addon` on both sides).

## 6. Decomposition of the .161 delta [MEASURED / DERIVED]

Per A/B pair, seconds. A = ckpt window (core only, Add-on excluded). B = build_meta -> CHECKPOINT event (event time + 0.5 s truncation correction, ms-anchored on `ckpt.finished_at`). C1 = CHECKPOINT -> ADDON_START event; C2 = ADDON_START event -> final `finished_at`. LFL (like-for-like) = final - B.

| pair (prod -> main) | runner prod / main | legacy | new final | A | B | C1 | C2 | LFL | LFL - legacy | final - legacy |
|---|---|---|---|---|---|---|---|---|---|---|
| #59 -> #56 | Runner04 / Runner04 | 12.480 | 13.652 | 10.022 | 1.11 | 1.00 | 1.53 | 12.546 | +0.066 | +1.172 |
| #60 -> #57 | Runner03 / Runner04 | 12.410 | 14.319 | 10.562 | 1.02 | 1.00 | 1.74 | 13.300 | +0.890 | +1.909 |
| #61 -> #58 | Runner03 / Runner01 | 12.635 | 14.583 | 10.645 | 1.78 | 0.00 | 2.16 | 12.800 | +0.165 | +1.948 |
| #62 -> #59 | Runner04 / Runner01 | 12.706 | 14.801 | 10.720 | 1.41 | 1.00 | 1.67 | 13.387 | +0.681 | +2.095 |
| #63 -> #60 | Runner01 / Runner03 | 12.992 | 14.526 | 10.498 | 1.12 | 1.00 | 1.91 | 13.406 | +0.414 | +1.534 |

Medians/means over the 5 pairs: B 1.12 / 1.29; C1 1.00 / 0.80; C2 1.74 / 1.80; A 10.59 / 10.52. (C1 is quantised to 0/1 s, so use the mean.) legacy median - new ckpt median = 2.073 s = (legacy Add-on region) + (core delta); new Add-on region (C1+C2, mean) = 2.60 s.

Like-for-like for all three Linux hosts (final - B vs legacy):

| host | B median (mean) | legacy median | LFL median (mean) | LFL delta median | LFL delta mean | Welch p | headline delta median |
|---|---|---|---|---|---|---|---|
| 161 | 1.12 (1.29) | 12.635 | 13.300 (13.088) | +0.665 (+5.3%) | +0.443 (+3.5%) | 0.0681 | +1.891 (+15.0%) |
| 162 | 1.58 (1.55) | 19.061 | 15.765 (16.014) | -3.296 (-17.3%) | -2.710 (-14.5%) | 0.0001 | -1.554 (-8.2%) |
| 163 | 1.58 (1.63) | 18.490 | 15.772 (15.633) | -2.718 (-14.7%) | -2.618 (-14.3%) | 0.0002 | -1.303 (-7.0%) |

Runner check for .161 (means, s; n legacy/new in brackets): Runner01: legacy 12.99 [1] -> new final 14.69 / LFL 13.09 [2]; Runner03: legacy 12.52 [2] -> new final 14.53 / LFL 13.41 [1]; Runner04: legacy 12.59 [2] -> new final 13.99 / LFL 12.92 [2]. The increase appears on every Runner; the Runner is not the cause (samples per Runner are 1-2, so this is only a sanity check).

Uncertainty: each B value carries +-0.3 s quantisation (1 s truncated stamp); the .161 mean of 5 has SE about 0.13 s. The LFL delta for .161 (+0.44..+0.67 s) is within about 2 SE of zero (p=0.068).

## 7. Tasks only in one runtime for the .161 path [STATIC, not timings]

Linux play for a raw-fallback host, literal includes expanded, `python_ok`-only branches dropped: legacy 153 tasks (12 SSH `raw`, 139 controller-side), new 151 tasks (**8** SSH `raw`, 141 controller-side); inside the `duration_ms` window (after `init_fragments`; the preflight `raw` is before it) that is 11 vs **7** SSH `raw` calls. (`stat` x2 in the credential step are `delegate_to: localhost` vault checks.)

Only in **new**:
- `CHECKPOINT` (debug, inside the new window via tail B)
- `ADDON_START` (set_fact, inside the window), `addon | combine into output` (set_fact; heavy `combine`/`normalize_errors`/`now()`; inside), `ADDON_DONE` (set_fact; after the re-stamp, outside)
- `addon | missing add-on error`, `addon | result` (replace the legacy fragment/merge pair)
- `linux | system | define shared dmi collector`, `linux | system | shared dmi raw (memory / cpu 공용)`, `linux | cpu | select shared dmi raw (processor 구간)`, `linux | memory | select shared dmi raw (memory 구간)` (controller set_facts; the `dmidecode` now runs once inside the existing system raw call)
- `linux | storage | parse lsblk json (from_json)`, `linux | storage | classify lsblk result` (controller set_facts)
- `linux | hba_ib | enumerate fc_host + infiniband` (1 raw)
- `timeout:` keyword on all 8 raw tasks and on every Add-on role task (`include_role apply.timeout`); `ansible_timeout: 15`

Only in **legacy**:
- `linux | cpu | raw dmi processor speed (become)` (raw), `linux | memory | raw gather (/proc/meminfo + dmidecode)` (raw)
- `linux | hba_ib | enumerate fc_host`, `enumerate infiniband`, `NIC driver map` (3 raws; replaced by 1)
- `addon | missing add-on fragment` + `addon | merge missing add-on fragment` (skipped at runtime, Add-on present), `addon | result fragment`, `addon | merge result fragment` and the 3 `normalize | merge_fragment` set_facts it runs (x2 incl. skipped)

Callback (`callback_plugins/json_only.py`) additions run inline in the controller process: ~10 small file appends per host (progress), 1 append+fsync per host for `CHECKPOINT`, an fsync added to the OUTPUT file write. Cost per event is small; the fsync cost on the Runner disk is [UNMEASURED].

## 8. Conclusion

- The +1.9 s on .161 is **not concentrated in specific gather tasks**. No gather task can be shown slower; the raw-path core even has 4 fewer SSH round trips in the new code.
- **About 1.12 s (median; 1.29 s mean) = 59-74% of the delta is the tail B** - `linux | build_correlation` (+ `normalize | build_correlation`), the `linux | build output` chain (`os | normalize | build_sections`, `build_status`, `build_errors`, `set output meta (defaults preserve)`, `build_output` + its 3 set_facts), `linux | inject schema_version`, and the new `CHECKPOINT` - which now fall inside `duration_ms` because the Add-on moved after assembly and re-stamps `finished_at`. Except for `CHECKPOINT` they ran in the legacy too, just outside its window. `CHECKPOINT`'s own cost is inside B and not separable (average task in B is ~0.07 s; the fsync cost is unmeasured).
- The remainder, **+0.67 s median / +0.44 s mean (+5.3% / +3.5%, p=0.068)**, is marginal vs run-to-run noise (new sd 0.44 s) and sits in {core gather + Add-on region + wrapper tasks}; candidates by code reading, all unconfirmed: `addon | combine into output`, `ADDON_START`, `CHECKPOINT` fsync, `include_tasks linux | addon` (C1 = 0.80 s for 3 tasks).
- For .162/.163 the same window effect hides most of a real gain: like-for-like -3.30 s (-17.3%) and -2.72 s (-14.7%).
- If the goal is a defensible before/after statement, compare on the same window (new ckpt + Add-on region, or final - B), or record the window change as an intentional contract change. That is a decision for the owner of the envelope contract (`meta.duration_ms` semantics, `docs/contract/`); I changed nothing.

## 9. Unmeasured / caveats / how to close the gap

- [UNMEASURED] Any legacy per-task or per-segment time (no artifact, no console timing, no Timestamper data). The legacy tail after `build_meta` and the legacy Add-on region duration are therefore not directly known; the like-for-like numbers rely on the structural fact that the legacy window ends at `build_meta`.
- [UNMEASURED] Split of the residual (+0.44..+0.67 s) between core gather, Add-on wrapper tasks and callback fsync; cost of `CHECKPOINT` alone; fsync latency on the Runners.
- Event times are 1 s truncated; B/C1/C2 are +-0.3 s per sample (corrected by +0.5 s where combined with ms stamps). n=5 per side.
- Static task counts say nothing about wall time (loops, remote command duration, controller overhead per task grows with hostvars size).
- Shortest way to settle the residual: one traced run per runtime with an env-gated callback that appends `{host, task, start_ms, end_ms}` for **every** task (the new callback already has the append infrastructure). For the legacy side run `4ce90a005307` with the same callback overlaid in a scratch/harness Job (not production). Compare per-task, then re-run the 5+5 A/B only if the residual matters.

## 10. Files (all under `scratchpad/gp36/`)

- `gp36_report.md` (this file), `gp36_tasks.csv` (kinds: `host_total` both sides, `window_segment` A/B/C1/C2/LFL per host-build, `event_segment` new side per event, legacy rows marked UNMEASURED)
- Inputs: `main_<56..60>_{progress.jsonl,callback.json,gather_*,console.txt}`, `prod_<59..63>_console.txt`
- Scripts: `parse_all.py`, `analyze.py`, `analyze2.py`, `static_tasks.py`, `static_sequence.py`, `make_report.py`; intermediates `parsed.json`, `analysis.json`, `analysis2.json`, `static_tasks.json`, `static_sequence.json`
