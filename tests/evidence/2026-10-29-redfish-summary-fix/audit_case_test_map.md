# 감사 사례 ↔ 시험 대조표 (2026-10-29, 2026-10-31 보완)

- 작성: AI(Claude). 2026-10-29 에 쓰고 2026-10-31 에 0절 · 1절 · 5절을 보완했다.
- 감사 보고서 `C:\github\ClovirONE\se-indep-20261028\SUMMARY_AUDIT_REPORT.md`(sha256 `0875e9f473109105748893a929caad2a76a7b6b3562899b8df2f8014b10f2b31`)의 사례마다 이 브랜치의 시험 · 합성 미러가 하나 이상 대응하는지 적는다.
- 시험 경로는 저장소 기준이다. 합성 미러는 `synthetic/` 폴더(`expected.json` 사전 등록)를 가리킨다.

## 0. "S1~S22" 번호에 대해

- 지시서는 "기존 Summary 감사에서 발견한 S1~S22" 를 시험 반영 확인 대상으로 든다.
- S1~S22 목록(번호별 정의)은 감사 폴더 어디에도 없다. 찾은 곳: 보고서 · `INDEPENDENT_REVERIFY_RESULT.md` · `drafts/` · `out/`(md · txt · yml) · `logs/` · `tools/`.
- 번호가 쓰인 곳은 두 군데뿐이다(2026-10-31 재검색).
  - 보고서 본문: S1 · S2 · S6 · S9 · S14 · S15 · S16 · S17 · S18 · S20 · S22 — 11개.
  - 감사 도구 주석: S1 · S2 · S9 · S10 · S15 · S17 · S18 · S19 · S20 · S22. 파일은 `tools/syn/build_syn_mirrors.py` · `build_syn_mirrors_fix2.py` · `syn_compare_fix2.py` · `fn_partition_checks.py` 다.
  - 합치면 13개다. S1 · S2 · S15 는 위치마다 뜻이 다르고, S22 는 보고서 안에서도 두 뜻이다. 1절 표에 위치별로 나눠 적었다.
- 2026-10-29 판은 보고서에서 8개만 찾았다고 적었다. 부록 A 의 S2 · S15, 8.3절의 S16, 도구 주석의 S10 · S19 를 빠뜨린 것이다. 2026-10-31 에 1절에 더했다.
- 어디에도 나오지 않는 9개(S3 · S4 · S5 · S7 · S8 · S11 · S12 · S13 · S21)는 정의 원천을 확인해야 한다(handoff 10절 질문 1).

## 1. 번호로 불린 사례

| 번호 | 위치 · 뜻 | 이번 처리 | 시험 · 합성 |
|---|---|---|---|
| S1 | 보고서 8.4 · 9절, 도구 `build_syn_mirrors.py`: `multi_node.summary.resource_block_count` · `fabric_count` 의 null 분기(합성으로만 확인) | SA-02 수정 | `tests/unit/test_multi_node_counts_sa01.py` — `test_resource_block_count_only_when_confirmed` · `test_topology_summary_counts` · `test_csus_recording_service_root_without_fabrics_and_composition`. 합성 `syn_csus_nofab` · `syn_csus_nocomp` |
| S1 (부록 A) | `tests/unit/test_csus_extended_topology.py:418-419` · `:547` 이 링크 없음 → 0 을 고정 | SA-02 | 기대값을 null 로 갱신(커밋 `9b34e1d7`) |
| S1 (3.7 표 · `fn_partition_checks.py`) | 파티션 storage "디스크 없음" | SA-03 · SA-07 | `tests/unit/test_partition_summary_rules_sa03.py::test_partition_storage_follows_top_level_rules`(원천 없음 null · 확인한 0 · 미완결 null). 갱신 `tests/unit/test_partition_normalize_grouping.py` · `tests/unit/test_hpe_csus_multi_node.py` |
| S2 (부록 A) | `tests/regression/test_csus_mock_consistency.py` 한 시험 안에서 `:92`(세지 못한 것 ≠ 0, FIX 6)와 `:96`(Endpoints 링크 없음 → 0)이 충돌 | SA-01 | `:96` 기대값을 `endpoint_count is None and endpoints == []` 로 갱신(커밋 `1b125686`). 양성 사례 `tests/unit/test_csus_fixture_replay.py`(Endpoints 있음 → 2)는 그대로 |
| S2 (`fn_partition_checks.py`) | 파티션 디스크 457344 MiB(446.625 GiB) — storage 반올림 규칙 공백(내림 446 / half-even 447) | SA-11 — 내림 유지 + 문서화(사용자 결정) | `tests/unit/test_partition_summary_rules_sa03.py` storage 사례(1490.42 GiB → 1490) · `tests/unit/test_redfish_summary_null_rules.py` storage 사례(931.5 GiB → 931). 문서 `schema/field_dictionary.yml` · `docs/contract/03-fields.md`(커밋 `0bc68f71`) |
| S6 | 보고서 7.1 SA-10: DL380 계열 `primary_speed_mbps` null 은 원천 NIC 속도 없음([INFO]) | SA-10 정의(대표 NIC 의 속도) | `tests/unit/test_redfish_summary_null_rules.py::test_primary_speed_is_the_primary_nic_speed`(대표 NIC 속도 0 · null → null, 다른 NIC 으로 대체 안 함). A/B/C `network.primary_speed_mbps B↔C` 18대 PASS |
| S9 | 보고서 8.4, 도구 `build_syn_mirrors.py`: HBA `Enabled` · `Active` · DMTF 밖 링크 값(합성으로만 확인) | SA-09 — HBA 정책은 바꾸지 않음 | `tests/unit/test_link_status_sa09.py::test_hba_link_policy_is_unchanged_for_every_input` · `::test_r740_transitional_and_state_values_are_unknown_with_one_notice_per_section_and_hba_unchanged`. 기존 `tests/unit/test_redfish_pure_helpers.py` HBA 시험 그대로 통과. 합성 `syn_dell_links`(`data.storage.hbas` 가 수정 전과 같음) |
| S10 | 도구 `build_syn_mirrors.py`: 대표 NIC 속도 미상인데 다른 up NIC 속도가 다름 | SA-10 | `tests/unit/test_redfish_summary_null_rules.py::test_primary_speed_is_the_primary_nic_speed` · 합성 `syn_dell_primary`(대표 NIC 속도 0 → `primary_speed_mbps` null, 다른 NIC 10000 으로 바꾸지 않음) |
| S14 | 보고서 9절: `health_rollup` 'Unknown' 의미를 ESXi 와 공유 | SA-06 — 두 채널 함께(사용자 결정) | `tests/unit/test_power_rounding_sa17.py::test_health_rollup_same_rule_on_redfish_and_esxi` · `::test_dl380_gen12_03_all_absent_psus_rollup_null`. 갱신 `tests/unit/test_esxi_sensors.py` · `tests/unit/test_power_summary_b58_b59.py` |
| S14 (부록 A) | `tests/unit/test_power_summary_b58_b59.py` 가 Jinja 를 Python 으로 복사한 구현만 돌린다(운영 템플릿과 동치 확인은 입력 1건) | 시험 독립성 보강 | 복사본을 운영 템플릿과 맞추고(Absent 제외 · SA-06) SA-06 사례 4건을 템플릿과 대조(커밋 `9b34e1d7`). 종전 사례 5건(실측 power.json 3 · 손 입력 2)도 운영 템플릿과 12키 동치를 단정(커밋 `543a1794`, 템플릿 Critical 판정을 바꾸면 2건 실패 확인) |
| S15 (부록 A) | 파티션 storage · memory 가 비면 `grand_total_gb` 0, 파티션 GiB 내림 — CF:1470 · top-level 규칙과 충돌 | SA-03 · SA-07 | 갱신 `tests/unit/test_partition_normalize_grouping.py`(빈 storage · memory → null, 원천을 읽고 비었으면 0) · `tests/unit/test_hpe_csus_multi_node.py`(`_summarize_partition_disks` 빈 목록 → null · 확인한 0 → 0 · 미완결 → null). `tests/integration/test_redfish_normalize_robustness.py` 는 디스크 항목이 있는 입력이라 그대로 통과 |
| S15 (도구 `build_syn_mirrors.py`) | 파티션 DIMM 하나가 1536 MiB(1.5 GiB) | SA-03 | `tests/unit/test_partition_summary_rules_sa03.py::test_partition_memory_group_rounding_is_half_even`(1536 → 2 GiB) |
| S16 | 보고서 8.3: dl380_gen12_03(전원 Off)의 `grand_total_gb` 0 — 드라이브를 못 봤는데 0, 메모리는 null | SA-07 — 전원 상태가 아니라 드라이브 목록 원천 구조로 판정 | Tier 1 dl380_gen12_03 0 → null + notice. `tests/unit/test_redfish_summary_null_rules.py` storage 사례. 합성 `syn_g12_03_on`(전원만 On → 여전히 null) · `syn_r1csus01_off`(전원만 Off → 여전히 0) |
| S17 | 보고서 8.4 · 10.1: CPU `TotalCores` 일부 미상 → 부분 합 | SA-04 | `tests/unit/test_redfish_summary_null_rules.py::test_cpu_counts_use_full_sum_or_trusted_summary_or_null` · `::test_cpu_module_unread_processor_is_not_counted_as_total`. 파티션 `test_partition_summary_rules_sa03.py::test_partition_cpu_follows_top_level_rules` · `::test_partition_cpu_mixed_unknown_marks_only_that_group`. 합성 `syn_v4_partial` |
| S18 | 보고서 8.4 · 3.6: PSU 정격 일부 미상 · 비수치 정격 | 바꾸지 않음 — 감사 [INFO], 03-fields 대로(정격 부분 합 + `capacity_unknown_count`) | 기존 `capacity_unknown_count` 시험(`tests/unit/test_power_summary_b58_b59.py` · `tests/unit/test_redfish_csus_single_server.py` · `tests/unit/test_esxi_sensors.py`). 정격은 SA-17 반올림 대상이 아님 — `tests/unit/test_power_rounding_sa17.py::test_capacity_helper_still_truncates`(소수 문자열 정격 → null) |
| S19 | 도구 `build_syn_mirrors_fix2.py` · `syn_compare_fix2.py`: PowerSubsystem 경로의 min/max 소비전력 | SA-19 | `tests/unit/test_power_rounding_sa17.py::test_environment_metrics_reading_rounds_and_range_is_not_min_max` · 갱신 `tests/unit/test_power_environment_metrics_f5.py`. 합성 `syn_g12_psub_range` |
| S20 | 보고서 8.4: DIMM 용량 일부 미상 → 부분 합 | SA-05 | `tests/unit/test_redfish_summary_null_rules.py::test_memory_totals_use_full_sum_or_trusted_summary_or_null` · `::test_memory_module_unread_dimm_is_not_summed_as_total` · `::test_memory_module_full_read_keeps_dimm_sum`. 파티션 `::test_partition_memory_follows_top_level_rules`. 합성 `syn_v4_partial` |
| S22 | 보고서 8.4, 도구 `build_syn_mirrors.py`: Storage 가 일부 드라이브만 가리키는 장비(합성으로만 확인) | SA-12 | `tests/integration/test_chassis_drives_union_sa12.py` 시험 함수 13개(합집합 · 같은 URI · Serial 중복 · Serial 없는 섀시 전용 · 광고 없음 · 실패 · 404 두 종류). 합성 `syn_dl380_partial_link` |
| S22 (보고서 7.2 표) | 중복 제거 키 구분자 없음(NS:264 `name~model~serial`) — 감사도 NOT_RUN · 낮은 위험 | **이번 범위 밖 — 시험 없음** | 후속 작업으로 남김 |

## 2. 보고서 3.6 합성 변형

| 감사 변형(원본) | 감사 판정 | 이번 대응 |
|---|---|---|
| `syn_csus_nofab_dimm1536_fix1`(csus3200_02) | SA-02 FAIL · SA-03 CM | 합성 `syn_csus_nofab`(csus3200_01, 두 ServiceRoot 에서 `Fabrics` 삭제). 파티션 1536 MiB 는 `test_partition_memory_group_rounding_is_half_even`(1536 → 2 GiB) |
| `syn_csus_nocomp_fix1`(csus3200_02) | SA-02 FAIL | 합성 `syn_csus_nocomp` |
| `syn_v4_partial`(sr650_v4_01) | SA-04 · SA-05 FAIL · S18 [INFO] | 합성 `syn_v4_partial` — `TotalCores` · `CapacityMiB` 삭제. PSU 정격 삭제는 넣지 않았다(S18 은 변경 대상이 아님) |
| `syn_v4_bounds`(sr650_v4_01) | PASS | 동작 변경 없음. 512 MiB → 그룹 없음은 `test_partition_memory_group_rounding_is_half_even`, "N/A" 측정값 → null 은 `test_power_rounding_sa17.py::test_safe_round_int_is_half_even_and_rejects_non_numbers` |
| `syn_v4_links`(sr650_v4_02) | SA-09 CM | 합성 `syn_dell_links`(r1 R740 — NIC `Enabled` · 포트 `Training` · `LinkFlapping`). 시험 `tests/unit/test_link_status_sa09.py` |
| `syn_dell_primary`(r1 R740) | SA-10 CM | 합성 `syn_dell_primary`(대표 NIC 속도 0). 속도 키 삭제(null) 경우는 `test_primary_speed_is_the_primary_nic_speed` |
| `syn_dl380_partial_link`(dl380_gen12_01) | SA-12 CM | 합성 `syn_dl380_partial_link`(dl380_gen12_02). 시험 `tests/integration/test_chassis_drives_union_sa12.py` |
| `syn_g12_psub_range` fix2(dl380_gen12_01) | SA-19 FAIL | 합성 `syn_g12_psub_range`(+ `Reading` 521.5 → 522 반올림). 시험 `test_power_rounding_sa17.py::test_environment_metrics_reading_rounds_and_range_is_not_min_max` · 갱신 `tests/unit/test_power_environment_metrics_f5.py` |

## 3. 보고서 3.7 함수 단위 사례 (파티션 사본)

| 사례 | 감사 기대 | 시험 |
|---|---|---|
| M1 | 32 GiB ×15 + 1536 MiB → 그룹 (2,1,2) · grand 482 | `test_partition_memory_group_rounding_is_half_even`(1536 → 2) · `test_partition_memory_follows_top_level_rules` |
| M2 | 64 GiB + 512 MiB → 0 GB 그룹 없음 | `test_partition_memory_group_rounding_is_half_even`(512 → 그룹 없음) |
| M3 | 용량 모두 미상 → grand null | `test_partition_memory_follows_top_level_rules` · `test_memory_totals_use_full_sum_or_trusted_summary_or_null` 의 `[None, None]` 사례(커밋 `b2fd9c0d`에서 추가) |
| C1 | 2소켓 중 1개 미상 → null · 제조사 `Intel` | `test_partition_cpu_follows_top_level_rules` · `test_cpu_manufacturer_table_matches_normalize_jinja` · `test_cpu_manufacturer_table_literal_tokens_in_jinja` |
| C2 | 코어 모두 미상 → 그룹 `total_cores` · `cores_per_socket` null | `test_partition_cpu_follows_top_level_rules` · `test_cpu_counts_use_full_sum_or_trusted_summary_or_null` 의 `[None, None]` 사례(커밋 `b2fd9c0d`에서 추가). 그룹 값 (None, None)은 top-level 시험이 단정하고, 파티션 그룹 = top-level 그룹은 파티션 시험이 단정한다 |
| S1 | 디스크 없음 | 1절 S1(3.7 표) 행 |
| S2 | 디스크 457344 MiB 의 GiB 값 | 1절 S2(`fn_partition_checks.py`) 행 |
| N1 | 파티션 NIC 2개 → `{groups: []}` 유지(계산하지 않음) | `test_partition_summary_rules_sa03.py::test_csus_partition_summary_equals_top_level_and_source`(파티션 network summary == `{"groups": []}`). 03-fields 에 "미계산" 으로 적었다 |
| L1 | 링크 값 표(DMTF 밖 값 → unknown) | `tests/unit/test_link_status_sa09.py::test_network_link_mapping` |

## 4. SA 항목

SA 항목별 시험은 handoff 1절 표의 "시험" 열에 있다. 각 수정을 하나씩 되돌리면 시험이 실패하는지 31개 변이로 확인했고, 31개 모두 시험에 걸렸다(`mutation/mutation_results.txt`).

## 5. 보고서 부록 A (시험 독립성)

| 부록 A 의 시험(`104bcaf0`) | 감사 제안 | 이번 처리 |
|---|---|---|
| `tests/unit/test_power_summary_b58_b59.py` (복사 구현) | 운영 템플릿을 직접 렌더, 기대값은 사전 문장에서 유도 | 1절 S14(부록 A) 행. 복사본은 남겼지만, 그 복사본을 거치는 모든 입력에서 운영 템플릿과 12키 동치를 단정한다 |
| `tests/unit/test_csus_extended_topology.py:418-419` · `:547` | 정책 결정 뒤 기대값 null | 1절 S1(부록 A) 행 |
| `tests/regression/test_csus_mock_consistency.py:92` · `:96` | `:96` 기대값을 null 로 | 1절 S2(부록 A) 행 |
| 파티션 storage · memory 시험 4파일 | 파티션 summary 정책 결정 뒤 일괄 수정 | 1절 S15(부록 A) 행 |
| `tests/unit/test_redfish_csus_single_server.py:345` | 유지 | 기대값 그대로(top-level 메모리가 비면 null). 렌더 도우미가 `_rf_mem_basis` 를 먼저 렌더하도록만 바뀌었다(커밋 `9b34e1d7`) |
| `tests/unit/test_redfish_xcc3_shape.py:267-277` | HOLD 해제 시 같이 수정 | HOLD-a 그대로라 분할 그룹 튜플 유지. 속도 키만 SA-08 에 따라 0 → None(상세 0 은 유지, 커밋 `9b34e1d7`) |
| `tests/unit/test_network_summary_join_at1.py:60-90` | 좋은 사례 | 기대값 그대로. 렌더 입력에 `_rf_raw_collect`(수집 섹션)를 더했다(개수 null 규칙, 커밋 `9b34e1d7`). 새 시험은 NS 태스크를 Ansible 순서대로 렌더하는 `tests/integration/normalize_chain.py` 로 운영 템플릿을 돌린다 |
| `tests/unit/test_esxi_sensors.py:271` 이후 | S14 수정 시 함께 | 1절 S14 행(빈 PSU 목록 사례 'Unknown' → None) |
