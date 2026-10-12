# 디버깅 진입점

호출자, Jenkins, Ansible, 대상 장비 어디에서 무엇이 깨졌는지 빠르게 찾기 위한 진입점입니다. 실패 봉투 자체를 읽는 법은 [../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md)에 있습니다.

## 0. 요약: 증상별로 먼저 볼 곳

| 증상 | 1차 확인 | 2차 확인 |
|---|---|---|
| 빌드가 입력 확인에서 FAILURE | 콘솔의 `ERROR: [입력 확인] …` 줄. 규칙은 `Jenkinsfile_portal`의 `seAcceptTargets`(각 채널 `inventory.sh`와 같음) | [../contract/01-input.md](../contract/01-input.md) 5절 |
| 빌드가 실행 위치 확인에서 FAILURE | 콘솔의 `[실행 위치] …` 줄. `loc`이 `common/vars/locations.yml`에 있는지 | Runner 라벨 ([../operate/02-agent-node.md](../operate/02-agent-node.md)) |
| 수집 단계가 시작되지 않음 (`실행 준비`, 종료 코드 90~95) | 콘솔의 `[수집] 수집을 시작하지 못했습니다` 줄과 `원인:` 줄 (`scripts/run_gather.sh`) | venv ([../operate/02-agent-node.md](../operate/02-agent-node.md) 5절), 작업 폴더 권한 |
| Runner를 기다리다 끝남 | 콘솔의 `[실행 대기]` 줄, `finalize_summary.json`의 `infra` | Runner 연결 상태 ([../operate/04-pipeline-runtime.md](../operate/04-pipeline-runtime.md)) |
| 특정 서버만 실패 봉투 | 봉투의 `diagnosis.failure_stage`, `failure_code`, `errors[].detail` | 아래 2절 |
| 섹션 하나가 `failed` | `errors[]`의 그 섹션 항목 (`detail`에 명령, rc, cause) | 채널의 `gather_*.yml` 또는 `collect_*.yml` |
| 봉투 수가 접수 수와 다름 | `finalize_summary.json`의 `accepted`, `lines`, `by_origin`, `warnings` | `gather_progress.jsonl`, `gather_checkpoint.jsonl` (빌드 artifact) |
| Portal 전송 실패 | 콘솔의 `[Portal 전송]` 줄(시도 번호, HTTP 상태 또는 전송 도구 상태), `finalize_summary.json`의 `callback` | callbackUrl, Portal 로그 |
| 어댑터가 잘못 선택됨 | 봉투의 `meta.adapter_id`, `-vvv` 로그의 `adapter_loader:` 줄 | [03-adapter-system.md](03-adapter-system.md) 8절 |
| 벤더가 정규화되지 않음 (`vendor: null`) | `common/vars/vendor_aliases.yml`에 제조사 표기가 있는지 | `module_utils/adapter_common.py`의 `normalize_vendor` |
| Redfish 응답 파싱 오류 | `errors[].detail`의 URI와 상태, `redfish-gather/library/redfish_gather.py`의 `gather_*` 함수 | 원본 응답 캡처 ([08-onsite-capture.md](08-onsite-capture.md)) |
| 회귀 (A를 고치니 B가 깨짐) | `python -m pytest tests/regression` | `tests/regression/test_cross_channel_consistency.py` |

## 1. Jenkins 단계별

파이프라인은 `Jenkinsfile_portal` 하나이고 단계는 넷입니다. 콘솔의 줄은 `[입력 확인]`, `[실행 위치]`, `[수집]`, `[결과 보존]`, `[결과 확인]`, `[Portal 전송]`, `[요약]` 접두사로 시작하고, 기술 근거는 `[기술 기록]` 줄에 따로 있습니다.

### 입력 확인 (Controller)

파라미터 형식과 대상 목록을 검사합니다. 거부되면 접수 자체가 없으므로 Portal로 결과가 가지 않습니다. 콘솔의 `ERROR: [입력 확인]` 줄에 어느 항목이 왜 틀렸는지 있습니다.

### 실행 위치 확인 (Controller)

`loc`을 `common/vars/locations.yml`에서 찾아 Runner 라벨을 정합니다. 등록된 Runner가 없으면 여기서 실패합니다.

### 서버 정보 수집 (Runner)

`scripts/run_gather.sh`가 `ansible-playbook`을 실행합니다. 실패 시 확인 순서입니다.

1. 콘솔의 `[수집]` 줄로 시작했는지, 어떤 한계에 닿았는지, 중단됐는지 봅니다. `[기술 기록] 수집 시도 n=… rc=… state=…` 줄에 종료 코드와 판정이 있습니다.
2. 서버별 결과는 빌드 artifact `gather_output.json`(서버마다 한 줄)에서 봅니다. 없는 서버는 `gather_progress.jsonl`에서 어디까지 갔는지 봅니다.
3. Ansible 자체의 오류는 `verbosity` 파라미터를 올려(1~4) 다시 실행하면 콘솔에 나옵니다.

### 결과 확인 및 전송 (Controller)

결과를 회수해 접수 수와 맞추고 Portal로 보냅니다. `finalize_summary.json`과 `callback_body.json`이 artifact로 남습니다. `finalize_summary.json`의 주요 키입니다.

| 키 | 뜻 |
|---|---|
| `accepted`, `lines`, `filled`, `by_origin` | 접수 수, 결과 줄 수, 보충한 수, 결과의 출처 (`output`, `checkpoint`, `synthetic`) |
| `outcome`, `limit_reason`, `interruption` | 수집이 어떻게 끝났는지 (`completed`, `timeout`, `attempt_limit`, `aborted`, `prep_failed`, …), 한계 종류, 중단 분류 |
| `gather_run` | 시도별 기록 (`attempts[].state`, `rc`, 실행 시간) |
| `infra` | Runner를 기다린 구간과 합 |
| `callback` | 전송 시도마다 시각, HTTP 상태, 결과 (`delivered`, `refused`, `not_delivered`) |
| `warnings` | 보충이 있었는지, 비정상 종료였는지 |

## 2. 실패 봉투에서 거꾸로 찾기

`diagnosis.failure_stage`는 작업 흐름이 멈춘 위치입니다.

| `failure_stage` | 코드 위치 | 보는 것 |
|---|---|---|
| `reachable`, `port`, `protocol` | `common/library/precheck_bundle.py` (사전 진단) | `diagnosis.details.checked_ports`, `errors[].detail` |
| `auth` | 채널의 `try_credentials.yml`, `try_one_credential.yml` (Redfish는 `try_one_account.yml`) | `diagnosis.details.credential_scope`, 콘솔의 `credential_scope=… outcome=…` 줄 |
| `gather` | 채널의 수집 태스크 | `errors[].section`과 `detail` |
| `fallback` | `common/tasks/normalize/build_failed_output.yml`, `callback_plugins/json_only.py`의 보충 | 실행이 결과 없이 끝난 서버입니다. `gather_progress.jsonl`과 콘솔 |

`errors[].message`는 사용자 문장이고 기술 근거는 `errors[].detail`입니다. `detail`의 `cause=` 값(예: `insufficient_privilege`, `identifier_not_available`, `dmidecode_unavailable`, `command_failed`)이 분기 기준입니다.

## 3. fragment 정규화 과정

```text
init_fragments.yml → gather_<섹션>.yml × N → merge_fragment.yml (gather 마다) → build_sections → build_status → build_errors → build_meta → build_correlation → build_output → CHECKPOINT → OUTPUT
```

- 섹션이 통째로 빠짐: 그 gather가 fragment를 채웠는지, 바로 뒤에 `merge_fragment.yml`을 불렀는지, `_sections_collected_fragment`에 넣었는지 순서로 봅니다.
- 봉투 필드가 빠짐: `build_output.yml`(13 필드 정본), `init_fragments.yml`(빈 뼈대), `build_failed_output.yml`(실패 경로)을 봅니다. `tests/regression/test_cross_channel_consistency.py`가 13 필드를 검사합니다.

## 4. 어댑터 선택

`-vvv`로 실행하면 `lookup_plugins/adapter_loader.py`가 후보별 점수와 거부 사유를 남깁니다.

```text
adapter_loader: dell_idrac9 matched score=100345 (priority=100×1000 + specificity=30×10 + match=45)
adapter_loader: 후보 거부 — 28건
  - hpe_ilo6 (match 조건 불일치)
adapter_loader: 선택됨 — dell_idrac9 (score=100345)
```

점수가 같으면 파일 이름 순으로 정해지고 `점수 동률 발견` 경고가 남습니다. 동률은 priority와 specificity가 어긋났다는 신호입니다. 정책은 [03-adapter-system.md](03-adapter-system.md) 3절에 있습니다.

## 5. 봉투 13 필드가 만들어지는 곳

| 필드 | 생성 위치 |
|---|---|
| `target_type`, `collection_method`, `ip` | 각 채널 `site.yml`의 첫 `set_fact` |
| `hostname` | `build_output.yml`: `data.system.hostname` → `data.system.fqdn` → `data.bmc.network_hostname` → `null`. IP로 대체하지 않습니다. 출처는 `diagnosis.details.hostname_source` |
| `vendor` | `common/tasks/normalize/resolve_vendor.yml` (`vendor_aliases.yml`의 표시값) |
| `status` | `build_status.yml` |
| `sections` | `build_sections.yml` |
| `diagnosis` | 사전 진단 결과와 채널의 인증, 수집 판정 |
| `meta` | `build_meta.yml` |
| `correlation` | `build_correlation.yml` |
| `errors` | `build_errors.yml` |
| `data` | `merge_fragment.yml` 누적 |
| `schema_version` | 각 채널 `site.yml` |

## 6. Redfish 함수와 호출 리소스

`redfish-gather/library/redfish_gather.py`가 한 번의 모듈 호출로 전부 수집합니다.

| 함수 | 리소스 |
|---|---|
| `detect_vendor` | `/redfish/v1/` (무인증) |
| `gather_system` | `Systems/{id}` |
| `gather_bios` | `Systems/{id}`의 `Bios` 링크 (있을 때만) |
| `gather_bmc` | `Managers/{id}`, EthernetInterfaces, NetworkProtocol |
| `gather_processors`, `gather_memory` | `Systems/{id}/Processors`, `Systems/{id}/Memory` |
| `gather_storage` | `Systems/{id}/Storage`, Volumes, Drives (없으면 SimpleStorage) |
| `gather_network`, `gather_network_adapters_chassis` | `Systems/{id}/EthernetInterfaces`, `Chassis/{id}/NetworkAdapters` |
| `gather_firmware` | `UpdateService/FirmwareInventory` |
| `gather_power`, `gather_thermal` | `Chassis/{id}/Power` 또는 `PowerSubsystem`, `Chassis/{id}/Thermal` 또는 `ThermalSubsystem`. 둘 다 404면 `not_supported` |
| `_collect_multi_node_topology` | RMC 장비의 모든 Systems, Managers, Chassis, CompositionService, Fabrics |

벤더 분기는 `_OEM_EXTRACTORS`(벤더별 OEM 추출)와 계정 복구의 벤더별 쓰기 방식에만 있습니다.

## 7. 대상 쪽 응답 확인

```bash
# Redfish — Runner 나 작업 PC 에서. 무인증 서비스 루트와 인증 조회
curl -k -s -w '\n%{http_code}\n' https://<BMC 주소>/redfish/v1/
curl -k -s -u '<계정>:<비밀번호>' https://<BMC 주소>/redfish/v1/Systems
# 전체 트리 캡처 (개발 환경 재생용)
python tests/redfish-probe/redfish_full_mirror.py -r <BMC 주소> -u <계정> -p <비밀번호> -D <라벨>
```

SSH와 WinRM은 `verbosity`를 올린 빌드의 콘솔에서 연결 오류를 봅니다. ESXi는 `community.vmware` 모듈의 오류 문장이 `errors[].detail`에 남습니다.

## 8. 회귀 확인

```bash
# 저장소 루트
python -m pytest tests/unit tests/e2e tests/regression -q
python -m pytest tests/integration -q -m "not live"
python tests/validate_field_dictionary.py
ansible-playbook --syntax-check os-gather/site.yml esxi-gather/site.yml redfish-gather/site.yml   # Ansible 이 있는 Linux 또는 WSL
```

## 9. 관련 문서

- [01-gather-structure.md](01-gather-structure.md): 전체 구조
- [02-normalize-flow.md](02-normalize-flow.md): fragment 정규화
- [03-adapter-system.md](03-adapter-system.md): 어댑터 점수
- [../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md): 실패 봉투 읽는 법
- [../operate/04-pipeline-runtime.md](../operate/04-pipeline-runtime.md): 파이프라인 동작과 장애 확인
- [../contract/03-fields.md](../contract/03-fields.md): 필드 사전
