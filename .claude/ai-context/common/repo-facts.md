# Repo Facts — server-exporter

> 검증 기준 Agent (10.100.64.154) 에서 2026-03-27 확인. 최소 요구사항은 `REQUIREMENTS.md` 4절 참조.

## 핵심 기술 스택

| 카테고리 | 기술 | 검증 기준 버전 | 용도 |
|---------|------|--------------|------|
| Orchestration | ansible-core | 2.20.3 | 플레이북 실행 |
| | ansible (package) | 13.4.0 | core + bundled collections |
| Language | Python | 3.12.3 | 커스텀 모듈 / 필터 / 플러그인 (venv: /opt/ansible-env/) |
| Runtime | Java (OpenJDK) | 21.0.10 | Jenkins Agent 실행 |
| Template | Jinja2 | 3.1.6 | Ansible 템플릿 엔진 |
| Protocol | SSH, WinRM, Redfish API | — | 정보 수집 |
| CI/CD | Jenkins | — | 파이프라인 (Java 21 필수) |
| Secrets | Ansible Vault | — | 인증 정보 관리 |
| Utils | Python stdlib | — | Redfish HTTP, XML, JSON (외부 라이브러리 없음) |

## Collections

- `ansible.windows` 3.3.0 — Windows gather
- `community.vmware` 6.2.0 — ESXi gather
- `community.windows` 3.1.0 — Windows 보조
- `ansible.posix` 2.1.0
- `community.general` 12.4.0
- `ansible.utils` 6.0.1

## pip 패키지

- `pywinrm` 0.5.0 — Windows WinRM
- `pyvmomi` 9.0.0 — ESXi vSphere API
- `redis` 7.3.0 — Ansible fact caching
- `jmespath` 1.1.0 — json_query 필터
- `netaddr` 1.3.0 — ipaddr 필터
- `lxml` 6.0.2 — VMware XML 파싱
- Redfish는 stdlib only (urllib / ssl / json)

## 모듈 / 채널

| 채널 | 디렉터리 | 핵심 파일 |
|---|---|---|
| OS gather | `os-gather/` | site.yml (4-Play: 포트감지 → 감지실패 OUTPUT → Linux → Windows), tasks/{linux,windows}/gather_*.yml |
| ESXi gather | `esxi-gather/` | site.yml (1-Play), tasks/collect_facts/config/datastores + normalize_*.yml |
| Redfish gather | `redfish-gather/` | site.yml (1-Play: precheck → detect vendor → 자격증명 해석 → vault → adapter → collect → normalize), library/redfish_gather.py |
| 공통 | `common/` | library/precheck_bundle.py (도달[TCP OR ICMP]·프로토콜 진단), tasks/normalize/init_fragments/merge_fragment/build_*.yml |
| 어댑터 | `adapters/{redfish,os,esxi}/` | 채널별 YAML. `registry.yml` 은 **읽는 코드가 없다** (문서용 색인) |
| Schema | `schema/` | sections.yml (11 섹션), field_dictionary.yml (런타임 미사용 — 테스트·CI·훅 전용), baseline_v1/ (vendor 별 회귀 기준선) |
| Vault | `vault/` | `vault/common/redfish/standard.yml`(전역 표준) + `<loc>/redfish/<vendor>.yml`(복구) + `<loc>/os/{linux,windows}.yml` + `<loc>/esxi.yml`. 평면 경로는 2026-08-12 삭제 |

## 테스트

- `tests/redfish-probe/` — probe_redfish.py + deep_probe_redfish.py
- `tests/fixtures/` — 실장비 JSON 응답 (개수는 세지 않는다)
- `schema/baseline_v1/` — 벤더별 baseline JSON
- `tests/evidence/` — Round 7-10 조건부 검토
- `tests/scripts/` — conditional_review.py, os_esxi_verify.sh

## 정본 reference (덮어쓰지 말 것)

- `REQUIREMENTS.md` — 벤더/버전별 최소 요구사항 (정본)
- `README.md` — 프로젝트 정체성, 3-channel 개요
- `CLAUDE.md` — Tier 0 정본
- `docs/` — 운영·계약·개발 문서
