# 운영망 Redfish 원본 캡처

이 문서는 실제 BMC나 RMC가 접근이 제한된 운영망에만 있어 데이터를 한 번만 가져올 수 있을 때, Redfish 트리 전체를 파일로 떠 오는 절차를 설명합니다. 떠 온 파일은 개발 환경에서 오프라인으로 재생해 수집 코드와 fixture를 맞추는 데 씁니다. HPE CSUS 3200과 Superdome Flex의 RMC처럼 사내에 장비가 없는 대상이 주 용도입니다.

## 1. 원칙

- 특정 경로를 지정하지 않습니다. 도구는 `/redfish/v1/`에서 시작해 장비가 실제로 돌려준 `@odata.id` 링크만 재귀로 따라가 트리 전체를 저장합니다. 수집 코드가 가정하는 경로에 의존하지 않습니다.
- 한 번뿐이므로 전부 떠 옵니다. 지금 수집하지 않는 리소스도 나중에 필요할 수 있습니다.
- 도구는 표준 라이브러리만 쓰는 Python 파일 하나입니다. 운영망 서버에 `python3`만 있으면 설치 없이 실행됩니다.

## 2. 준비 (개발 환경에서)

1. 반입할 파일은 `tests/redfish-probe/redfish_full_mirror.py` 하나입니다.
2. 장비 없이 도구 동작을 확인합니다. 합성 CSUS 트리를 띄워 재귀, 페이지 나눔, 자동 발견, 오류 내성을 검사합니다.

   ```bash
   # 저장소 루트
   python -m pytest tests/unit/test_full_mirror_dryrun.py -q
   ```

3. 가장 높은 권한의 Redfish 계정을 확보하세요. 권한이 낮으면 일부 리소스가 트리에서 가려져 빠집니다.
4. RMC 대상이면 Redfish 서비스가 켜져 있는지 먼저 확인하세요([../operate/06-rmc-activation.md](../operate/06-rmc-activation.md)). 꺼져 있으면 트리가 비어 있습니다.

## 3. 운영망 현장에서 캡처

```bash
# 운영망 서버, BMC 에 닿는 계정. <라벨> 은 출력 폴더 이름 (예: csus_rmc_<펌웨어 버전>)
python3 redfish_full_mirror.py -r <BMC 주소[:포트]> -u <계정> -p <비밀번호> -D <라벨>
```

| 옵션 | 뜻 |
|---|---|
| `-r` | BMC 또는 RMC 주소. 포트를 생략하면 443 |
| `-u`, `-p` | 계정과 비밀번호. 명령줄에 적은 비밀번호는 셸 기록에 남으므로 끝난 뒤 기록을 지우세요 |
| `-D` | 출력 폴더 이름. 어느 펌웨어의 스냅샷인지 알 수 있게 붙입니다. 캡처 범위와는 무관합니다 |
| `--scheme` | 기본 `https` |

기본 동작은 인증서 검증 끔(자체 서명 인증서), `Accept` 헤더만 전송, Basic 인증, 오류가 나도 다음 리소스로 계속, 끝에 자가진단 요약 출력입니다.

산출물입니다.

```text
<출력 폴더>/redfish/v1/.../index.json     리소스 본문 (@odata.id 그대로)
<출력 폴더>/redfish/v1/.../headers.json   HTTP 상태와 응답 헤더
<출력 폴더>/_manifest.json                크롤 요약과 자가진단
<출력 폴더>/_serviceroot_noauth.json      무인증 서비스 루트
```

## 4. 철수 전 확인

다시 올 수 없으므로 `_manifest.json`(또는 화면의 요약)에서 다음을 확인하세요.

- `reachable`과 `auth_ok`가 `true`입니다.
- `root_product`가 실제 모델명입니다(예: `Compute Scale-up Server 3200`).
- `fetched_ok`가 장비 규모에 맞게 충분히 큽니다.
- `failed`의 대부분이 404(장비가 지원하지 않는 하위 리소스)이고 401이나 403이 아닙니다. 401, 403이 많으면 계정 권한이 부족하므로 더 높은 권한으로 다시 캡처합니다.
- 멀티 노드 장비면 모든 파티션, 모든 Manager(RMC, chassis 컨트롤러, 노드 iLO), 모든 chassis가 들어 있습니다.
- OEM 리소스(`Oem.Hpe.*` 등) 디렉터리가 있습니다.
- 펌웨어 버전이 `_manifest.json`의 `firmware_versions`와 폴더 이름에 남았습니다.
- 가능하면 사본을 하나 더 만들어 압축해 보관합니다.

## 5. 반출 뒤 개발 환경에서 재생

1. 반출한 트리를 그대로 가져옵니다.
2. 트리를 fixture로 변환해 오프라인으로 재생합니다. 멀티 노드 장비는 `--manager-layout`을 붙여야 `multi_node`가 채워집니다.

   ```bash
   # 저장소 루트
   python tests/integration/convert_dmtf_mockup.py \
       --mockup-dir <반출 트리>/redfish/v1 --name hpe_csus_3200_real \
       --manager-layout rmc_primary --captured <YYYY-MM-DD>
   ```

   산출된 `expected_output.json`의 `data`(섹션)와 `multi_node`(파티션, Manager, chassis)를 확인합니다. `tests/unit/test_csus_fixture_replay.py`는 평평한 fixture 디렉터리를 읽으므로 크롤러 트리를 직접 재생하지 못합니다. 트리 재생은 위 변환 경로만 씁니다. 트리에서 멀티 노드를 재구성하는 경로는 `tests/unit/test_full_mirror_dryrun.py`가 합성 데이터로 고정합니다.
3. 재생에서 드러난 차이(서비스 루트 제품 문자열, Manager와 System과 Chassis의 ID 형식, OEM 필드 구조)를 코드에 반영하고 회귀 시험을 추가한 뒤 기준선을 갱신합니다.

CSUS의 OEM 필드(`Oem.Hpe.PartitionInfo`, `FlexNodeInfo`, `GlobalConfiguration`) 추출은 라이브러리에 있지만 실장비 응답으로 검증한 적이 없습니다. 실제 캡처가 들어오면 이 경로를 먼저 확인합니다.

## 6. 한계

- 읽기 전용 스냅샷입니다. 계정 생성이나 전원 제어 같은 쓰기 동작은 담기지 않습니다.
- 캡처 시점의 펌웨어와 상태입니다. 펌웨어를 올리면 응답이 달라질 수 있습니다.
- Basic 인증만 씁니다. 장비가 Basic을 막고 세션 인증만 받으면 `_manifest.json`에 401로 남고 캡처되지 않습니다.

## 관련

| 내용 | 위치 |
|---|---|
| 캡처 도구 | `tests/redfish-probe/redfish_full_mirror.py` |
| 도구 동작 시험 | `tests/unit/test_full_mirror_dryrun.py` |
| 오프라인 재생 변환 | `tests/integration/convert_dmtf_mockup.py` |
| CSUS 합성 fixture와 미검증 항목 | `tests/fixtures/redfish/hpe_csus_3200/README.md` |
| RMC Redfish 확인 | [../operate/06-rmc-activation.md](../operate/06-rmc-activation.md) |
