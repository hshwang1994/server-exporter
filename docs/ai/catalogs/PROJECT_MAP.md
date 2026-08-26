# PROJECT_MAP — server-exporter

> 디렉터리 구조 카탈로그. session_start hook이 fingerprint drift 자동 검사.
> fingerprint: `.claude/policy/project-map-fingerprint.yaml`

## 일자: 2026-05-11 (cycle 2026-05-11 harness-cycle 갱신 — fingerprint 갱신 + 본문 카운트 동기화)

## 최상위 트리

```
server-exporter/
├── CLAUDE.md, README.md, REQUIREMENTS.md  (정본)
├── ansible.cfg                                              (Ansible 설정)
├── Jenkinsfile, Jenkinsfile_portal                          (2종 4-Stage 파이프라인 — cycle-015 _grafana 제거)
├── adapters/                # 42 vendor adapter YAML + registry.yml — cycle 2026-05-07 실측
│   ├── redfish/             # 31 (generic + dell×4 + hpe×5 + lenovo×4 + supermicro×8 + cisco×3 + ucs_xseries×1
│   │                          + huawei×1 + inspur×1 + fujitsu×1 + quanta×1 + superdome_flex×1)
│   ├── os/                  # 7 (linux_*/windows_*)
│   └── esxi/                # 4 (generic + 6x/7x/8x)
├── callback_plugins/        # json_only.py (stdout callback, OUTPUT만 JSON)
├── common/
│   ├── library/             # precheck_bundle.py (4단계 진단)
│   ├── tasks/normalize/     # init_fragments / merge_fragment / build_*.yml (10개)
│   └── vars/                # vendor_aliases.yml + supported_sections.yml
├── filter_plugins/          # Jinja2 필터 (diagnosis_mapper / vendor_normalizer / serial_normalizer 등)
├── lookup_plugins/          # adapter_loader.py
├── module_utils/            # adapter_common.py
├── os-gather/               # 4-Play (포트감지 → 감지실패 OUTPUT → Linux → Windows)
├── esxi-gather/             # 1-Play (community.vmware)
├── redfish-gather/          # 1-Play (precheck → detect → adapter → collect → normalize)
│   └── library/redfish_gather.py    (stdlib only — vendor OEM 추출은 여기 _extract_oem_*)
│                                    ※ tasks/vendors/{vendor}/ 는 2026-08-13 제거 (기여 0)
├── schema/
│   ├── sections.yml         # 11 섹션 정의
│   ├── field_dictionary.yml # 항목별 priority = Must / Nice / Skip (개수는 세지 않는다 — rule 00)
│   ├── fields/              # 섹션별 상세
│   ├── baseline_v1/         # 9 baseline JSON (redfish 5 + esxi/ubuntu/windows + rhel810_raw_fallback)
│   ├── examples/            # success/partial/failed
│   └── redfish_dmtf_2026.1/ # DMTF DSP8010 2026.1 subset (28 리소스 json-schema reference, rule 96 대조용)
├── tests/
│   ├── redfish-probe/       # probe_redfish.py + deep_probe_redfish.py
│   ├── integration/         # HPE iLO 에뮬레이터 + DMTF 표준 mockup record/replay 오프라인 회귀 하네스
│   ├── fixtures/            # 398 JSON (실장비 380 + HPE 에뮬레이터 15 + DMTF mockup 3) (회귀 input)
│   ├── baseline_v1/         # 회귀 기준선
│   ├── evidence/            # Round 검증 결과
│   ├── scripts/             # conditional_review.py + os_esxi_verify.sh
│   └── reference/           # ★ Round 11 (2026-04-28): 실장비 종합 raw reference (회귀 input 아님)
│       ├── README.md, INDEX.md
│       ├── redfish/<vendor>/<ip>/  # 재귀 endpoint crawl 전수
│       ├── os/<distro>/<ip>/       # ansible setup + ~80 sh 명령
│       ├── esxi/<ip>/              # esxcli + pyvmomi
│       ├── agent/{agent,jenkins_master}/<ip>/
│       ├── scripts/                # 4 수집 스크립트
│       └── local/                  # gitignored (자격)
├── tools/                   # 운영 도우미
├── vault/                   # ansible-vault encrypted
│   ├── linux.yml, windows.yml, esxi.yml
│   └── redfish/{vendor}.yml
├── docs/
│   ├── 01_jenkins-setup ~ 23_debugging-entrypoints    (23 운영 문서)
│   ├── superpowers/specs/                    (설계서)
│   ├── superpowers/plans/                    (실행 계획)
│   └── ai/                                   (AI 협업 메타 — 본 디렉터리)
├── scripts/
│   └── ai/
│       ├── (8 supporting: detect_session_context /
│       │   validate_claude_structure / collect_repo_facts /
│       │   check_project_map_drift / check_gap_against_main /
│       │   verify_harness_consistency / verify_vendor_boundary /
│       │   scan_suspicious_patterns)
│       └── hooks/ (21 Python hooks + install-git-hooks.sh)
└── .claude/
    ├── settings.json                         (hooks 등록 — cycle-011에서 보안 deny 38건 제거)
    ├── settings.local.json                   (개인)
    ├── rules/         (28 .md)
    ├── skills/        (51 SKILL.md, 폴더당 1)
    ├── agents/        (60 .md)
    ├── policy/        (10 YAML)
    ├── role/          (6 README: gather/output-schema/infra/qa/po/tpm)
    ├── ai-context/    (18: common + gather/output-schema/infra/external + vendors×9)
    ├── templates/     (8)
    └── commands/      (5: harness-cycle / harness-full-sweep / review-guide / scheduler-guide / usage-guide)
```

## 채널 흐름 (호출자 → 결과)

```
호출자 (HTTP POST + inventory_json)
  ↓
Jenkins Job (Jenkinsfile / _portal, 4-Stage — cycle-015 _grafana 제거)
  ├─ [1 Validate] 입력값
  ├─ [2 Gather] ansible-playbook
  │   ├─ os-gather/site.yml (4-Play: 포트 → 감지실패 OUTPUT → Linux → Windows)
  │   ├─ esxi-gather/site.yml
  │   └─ redfish-gather/site.yml (precheck → detect → adapter → collect → normalize)
  ├─ [3 Validate Schema] field_dictionary 정합 (FAIL 게이트)
  ├─ [4 (pipeline별)] FAIL 게이트
  │   ├─ Jenkinsfile          → E2E Regression (pytest baseline)
  │   └─ Jenkinsfile_portal   → Callback (호출자 통보, master)
  └─ [Post] callback_plugins/json_only.py → JSON envelope
```

**vault binding (cycle-012)**: Jenkins credential `server-gather-vault-password` (Secret File) 등록 → Jenkinsfile×2 모두 `withCredentials([file(credentialsId: 'server-gather-vault-password', variable: 'VAULT_PWD')])` 패턴으로 사용.

## fingerprint 갱신

```bash
python scripts/ai/check_project_map_drift.py --update
```

세션 시작 시 자동 drift 체크 (rule 28 #2).

## 정본 reference

- `CLAUDE.md` "파일 구조" — 가장 상세 (정본)
- `docs/develop/01-gather-structure.md`
- `docs/develop/02-normalize-flow.md`
- `docs/develop/03-adapter-system.md`
