# 운영망 Redfish 원본 캡처

이 문서는 실제 BMC나 RMC가 접근이 제한된 운영망에만 있어 데이터를 한 번만 가져올 수 있을 때, Redfish 트리 전체를 파일로 떠 오는 절차를 설명합니다. 떠 온 파일은 개발 환경에서 오프라인으로 재생해 수집 코드와 fixture를 맞추는 데 씁니다. HPE CSUS 3200과 Superdome Flex의 RMC처럼 사내에 장비가 없는 대상이 주 용도입니다.

## 1. 원칙

- 특정 경로를 지정하지 않습니다. 도구는 `/redfish/v1/`에서 시작해 장비가 실제로 돌려준 링크만 재귀로 따라가 트리 전체를 저장합니다. 수집 코드가 가정하는 경로에 의존하지 않습니다.
- 한 번뿐이므로 닿는 것은 전부 받습니다. `@odata.id`뿐 아니라 레지스트리와 스키마 본문(`Location[].Uri`), `Actions`의 `target` 주소, `*Uri` 키로만 연결된 OEM 리소스(로그, 설정), 응답의 `Link` 헤더, 바이너리 첨부(`AdditionalDataURI` 등)까지 따라갑니다. 표준 고정 주소 `/redfish`, `/redfish/v1/odata`, `/redfish/v1/$metadata`와 `$metadata`가 참조하는 로컬 스키마도 받습니다.
- 오류의 기준은 "이 계정으로 받을 수 있는데 못 받은 것"입니다. 장비가 링크는 냈지만 실제로 없는 경로(404, 410), 페이로드 없는 응답(204), GET이 안 되는 액션 주소(405, 501), 요청을 거절한 응답(400, 406 등), 계정 권한 밖(401, 403)은 오류가 아니라 정보입니다. 반대로 장비가 재시도 뒤에도 계속 5xx나 무응답을 주는 경로(`device_error`), 크기 상한 때문에 받지 않은 첨부(`oversize`), 저장에 실패한 항목은 **받지 못한 것**이므로 `COMPLETE`로 표시하지 않고 `INCOMPLETE`로 끝냅니다. 장비가 이상한 응답을 줘도 도구가 성공으로 처리하거나 데이터를 지어내지 않으며, 못 받은 항목마다 `origin`(device, device_or_network, storage, tool, interrupted)을 적어 장비 문제와 도구·저장소 문제를 구별합니다.
- 읽기 전용입니다. 장비에 보내는 요청 중 GET이 아닌 것은 세션 로그인 POST와 종료 DELETE뿐이고, 설정을 바꾸는 요청은 없습니다.
- 계정 잠금을 피합니다. 401과 403은 재시도하지 않고, 자격 거절 판정은 요청 1~2회 안에서 끝내고 중단합니다. 비밀번호는 환경변수나 파일로 받으며 어떤 산출물에도 쓰지 않습니다. 세션 토큰도 저장하지 않습니다.
- 도구는 표준 라이브러리만 쓰는 Python 파일 하나입니다. RHEL, Rocky 8의 기본 `python3`(3.6)에서도 설치 없이 실행됩니다. `python3` 명령이 없고 `/usr/libexec/platform-python`만 있으면 그 경로로 실행하세요. 여러 대를 동시에 받을 때만 셸 스크립트 `mirror_many.sh`를 함께 씁니다.

## 2. 준비 (개발 환경에서)

1. 반입할 파일은 `tests/redfish-probe/redfish_full_mirror.py`입니다. 여러 대를 병렬로 받으려면 `tests/redfish-probe/mirror_many.sh`도 같은 폴더에 둡니다.
2. 장비 없이 도구 동작을 확인합니다. 합성 CSUS 트리와 세션 로그인, 토큰 만료, 일시 오류, 바이너리, 중단 후 재개를 흉내 내는 가짜 서비스를 띄워 검사합니다.

   ```bash
   # 저장소 루트
   python -m pytest tests/unit/test_full_mirror_dryrun.py -q
   ```

3. 가장 높은 권한의 Redfish 계정을 확보하세요. 권한이 낮으면 일부 리소스가 트리에서 가려져 빠지고, 그 항목은 결과 요약의 `outside_account`로 나옵니다.
4. RMC 대상이면 Redfish 서비스가 켜져 있는지 먼저 확인하세요([../operate/06-rmc-activation.md](../operate/06-rmc-activation.md)). 꺼져 있으면 트리가 비어 있습니다.

## 3. 운영망 현장에서 캡처 (한 대)

```bash
# 운영망 서버, BMC 에 닿는 계정. <라벨> 은 출력 폴더 이름 (예: csus_rmc_<펌웨어 버전>)
read -rs -p "BMC password: " BMC_PASSWORD; echo; export BMC_PASSWORD
python3 redfish_full_mirror.py -r <BMC 주소[:포트]> -u <계정> -D <라벨>
```

비밀번호를 `-p`로 줄 수도 있지만 `ps`와 셸 기록에 남으므로 경고가 출력됩니다. 위처럼 환경변수(기본 이름 `BMC_PASSWORD`, `--password-env <이름>`으로 변경)나 `--password-file <경로>`를 쓰세요.

| 옵션 | 뜻 |
|---|---|
| `-r` | BMC 또는 RMC 주소. 포트를 생략하면 443 |
| `-u` | 계정 |
| `--password-env`, `--password-file`, `-p` | 비밀번호 전달 방법. 권장 순서는 환경변수, 파일, `-p` |
| `-D` | 출력 폴더 이름. 어느 펌웨어의 스냅샷인지 알 수 있게 붙입니다. 캡처 범위와는 무관합니다 |
| `--auth` | `auto`(기본)는 세션 로그인을 먼저 시도하고 안 되면 Basic. `session`은 세션만. `basic`은 세션 POST를 아예 보내지 않습니다(HPE CSUS, Superdome Flex RMC처럼 Basic 전용인 장비) |
| `--resume` | 같은 `-D`의 이전 결과 중 정상 저장분을 다시 받지 않고 빈 곳만 받습니다. 중단되었거나 `INCOMPLETE`일 때 씁니다 |
| `--retries`, `--timeout`, `--delay` | 일시 오류 재시도 횟수(기본 3), 요청 제한 시간(기본 30초), 요청 사이 대기(기본 0초). BMC 부하가 걱정되면 `--delay 0.2`처럼 줍니다 |
| `--legacy-tls` | TLS 1.0, 1.1만 되는 구형 BMC용. OS의 암호 정책이 막으면 효과가 없습니다 |
| `--exclude <정규식>` | 받지 않을 경로. 여러 번 줄 수 있습니다 |
| `--no-action-targets` | `Actions`의 `target` 주소를 GET으로 확인하지 않습니다 |
| `--no-binary` | 바이너리 첨부(2xx인데 Content-Type이 json, xml, text, html이 아닌 응답)는 본문을 받지 않고 `excluded`에 `reason: no-binary`로 기록합니다(오류 아님, 결과는 `COMPLETE` 유지). 응답 헤더와 본문 앞부분(최대 64 KiB)만 보고 연결을 닫으므로 크기가 얼마든 나머지는 내려받지 않고, `--max-bytes-per-resource`와도 무관합니다. 다만 Content-Type이 거짓인 JSON은 놓치지 않도록 본문이 `{`나 `[`로 시작하면 16 MiB까지만 읽어 JSON이면 저장합니다. 텍스트 본문은 건너뛰지 않으며 크기 상한이 그대로 적용됩니다 |
| `--max-bytes-per-resource` | 리소스 하나의 최대 크기(기본 256 MiB, 0은 무제한). 넘는 첨부는 받지 않고 `oversize`에 URI, Content-Type, 크기, 원인과 함께 기록하며 결과는 `INCOMPLETE`입니다. 바이너리는 디스크로 스트리밍하므로 메모리를 쓰지 않습니다 |
| `--strict` | 기본 판정에 더해 `outside_account`, `rejected`, `Members@odata.count` 불일치도 `INCOMPLETE`로 취급합니다 |
| `--scheme` | 기본 `https` |
| `--summarize <폴더>...` | 여러 출력 폴더의 `_manifest.json`을 표 하나로 요약하고 끝냅니다 |

기본 동작은 인증서 검증 끔(자체 서명 인증서), `Accept: application/json` 헤더만 전송, 세션 우선 인증, 일시 오류(5xx, 429, 408, 시간 초과, TLS 오류) 재시도, 끝에 자가진단 요약 출력입니다. 환경 프록시 설정은 무시합니다(`--use-env-proxy`로 켭니다). 진행 상황은 100개마다 표준 오류로 나옵니다(`--quiet`로 끔).

산출물입니다.

```text
<출력 폴더>/redfish/v1/.../index.json    리소스 본문 (@odata.id 그대로)
<출력 폴더>/redfish/v1/.../headers.json  HTTP 상태와 응답 헤더 (토큰과 쿠키는 제거)
<출력 폴더>/redfish/v1/.../raw.<확장자>  XML, 바이너리 같은 비-JSON 본문 전체 (index.json 은 @odata.id 없는 안내 파일이고 크기와 SHA-256을 담습니다)
<출력 폴더>/_manifest.json               크롤 요약과 자가진단
<출력 폴더>/_links.json                  경로마다 처음 참조한 곳, 링크 종류, 참조 횟수
<출력 폴더>/_fsmap.json                  경로와 디스크 폴더의 대응 (충돌, 예약어, 길이 축약 기록. --resume 이 읽습니다)
<출력 폴더>/_serviceroot_noauth.json     무인증 서비스 루트
```

### 바이너리 첨부를 받지 않기

펌웨어 이미지(`/fwrepo`), 디버그 로그 묶음(`.tar.zst`), 라이선스 키 같은 바이너리 첨부가 필요 없으면 `--no-binary`를 줍니다. 러너에서는 `MIRROR_ARGS="--no-binary" bash mirror_many.sh targets.txt`입니다. 건너뛴 첨부는 `_manifest.json`의 `excluded[]`에서 `reason`이 `no-binary`인 항목(경로, Content-Type, 크기, 참조한 곳)으로 확인합니다. `--resume`으로 이어받아도 같습니다. 이미 받아 둔 바이너리는 지우지 않습니다.

### 크기 제한 없이 받기 (용인 현장 권장)

펌웨어 이미지(`/fwrepo`)나 디버그 로그 묶음 같은 큰 첨부까지 전부 받으려면 `--max-bytes-per-resource 0`을 줍니다. 기본 상한(256 MiB)을 넘는 첨부는 `oversize`에 기록되고 결과가 `INCOMPLETE`가 되므로, 처음부터 상한 없이 받거나 `INCOMPLETE`가 된 뒤 같은 폴더에 `--max-bytes-per-resource 0 --resume`을 붙여 그 항목만 받으면 됩니다. 상한을 없앨 때 감안할 것입니다.

- 저장 공간: 호스트당 수 GB가 될 수 있으니 시작 전에 `df -h <출력폴더>`로 여유를 확인하세요. 도구는 여유가 1 GiB보다 적으면 경고하고, 저장 실패가 연속 10회면 BMC를 더 두드리지 않고 중단합니다(`storage_error`. 받은 곳은 `--resume`으로 재사용).
- BMC 부하와 시간: 큰 파일은 BMC 웹 서버가 느리게 내려주므로 동시 실행 수를 줄이세요(`MIRROR_JOBS=2`). 요청 사이 간격이 필요하면 `--delay`를 줍니다.
- 잘린 파일 방지: 내려받는 파일은 `.part`로 받다가 길이가 `Content-Length`와 같을 때만 정식 이름으로 바꿉니다. 중간에 끊기거나 디스크가 차면 정상 저장으로 치지 않고 다시 받으며, `--resume`은 크기(64 MiB 이하는 SHA-256까지)가 맞는 파일만 재사용합니다.

## 4. 여러 대를 동시에 캡처

대상마다 `targets.txt` 한 줄을 적습니다. 열은 `IP[:포트] 계정 출력폴더 [auth]`이고 `auth`를 생략하면 `auto`입니다. `#`으로 시작하는 줄과 빈 줄은 무시하며 비밀번호는 적지 않습니다.

```text
# HPE CSUS / Superdome RMC 는 Basic 전용이라 basic 으로 지정
10.0.0.11  infraops  /data/mock/csus_01  basic
10.0.0.21  infraops  /data/mock/dl380_01
10.0.0.31  infraops  /data/mock/sr650_01
```

```bash
read -rs -p "BMC password: " BMC_PW; echo; export BMC_PW
MIRROR_JOBS=4 bash mirror_many.sh targets.txt          # 동시 실행 수 기본 4
MIRROR_ARGS="--resume" bash mirror_many.sh targets.txt   # 크롤러에 넘길 추가 인자
```

러너는 호스트마다 크롤러를 하나씩 띄우고, 같은 IP는 동시에 두 개 띄우지 않습니다(BMC의 세션 한도와 잠금 카운터를 공유하기 때문입니다). 호스트별 로그는 `<출력폴더>/_crawl.log`, 종료코드는 `<출력폴더>/_exit_code`에 남고, 끝에 호스트별 결과 표가 나옵니다. 모두 `COMPLETE`면 종료코드 0, 아니면 1입니다. `Ctrl-C`나 `kill`을 받으면 크롤러에 종료를 전달해 세션을 로그아웃한 뒤 끝납니다. 나중에 표만 다시 보려면 `python3 redfish_full_mirror.py --summarize <폴더>...`를 씁니다. 캡처 파일은 소유자만 읽도록(`umask 077`) 만들고, 같은 출력 폴더나 같은 BMC에서 이미 다른 미러가 실행 중이면 그 호스트는 건너뛰고(종료코드 5) 표 아래에 알립니다. 크기 제한 없이 받으려면 `MIRROR_ARGS="--max-bytes-per-resource 0" MIRROR_JOBS=2 bash mirror_many.sh targets.txt`로 실행합니다.

## 5. 결과 판정과 철수 전 확인

한 번 나오면 다시 올 수 없으므로 화면 요약이나 `_manifest.json`에서 다음을 확인하세요.

| RESULT | 종료코드 | 뜻 | 다음 행동 |
|---|---|---|---|
| `COMPLETE` | 0 | 이 계정으로 닿는 모든 GET 리소스를 저장했습니다 | 아래 체크리스트 확인 후 철수 |
| `INCOMPLETE` | 1 | 못 받은 항목이 있습니다: `unresolved`(장비/망 불안정, 저장 실패, 도구 오류), `device_error`(재시도 뒤에도 계속 5xx나 무응답), `oversize`(크기 상한), 큐 잔량. 요약의 `origin`/`cause`가 장비 문제인지 도구·저장소 문제인지 알려 줍니다 | 원인을 처리한 뒤 같은 `-D`로 `--resume`. 0이 될 때까지 반복 |
| `EMPTY` | 2 | 2xx 응답이 0건입니다 | 도달, 인증, Redfish 활성화(RMC 라이선스) 확인 |
| `ABORT` | 3 | 인증 또는 세션 단계에서 중단했습니다 (`abort_reason`) | 계정과 비밀번호 확인. `session_unsupported`면 `--auth basic` |
| `ABORT` | 4 | 장비에 도달하지 못했습니다 | 주소, 방화벽, 443 포트 확인. TLS 오류 안내가 나오면 `--legacy-tls` |
| `ABORT` | 1 | 저장 공간 부족(`storage_error`) 또는 도구 내부 오류(`internal_error`) | `df -h` 확인 또는 stderr의 traceback 공유, 비운 뒤 `--resume` |
| (실행 안 함) | 5 | 같은 출력 폴더나 같은 BMC에서 다른 미러가 실행 중입니다 | 끝난 뒤 다시 실행 |
| (중단) | 130 | `Ctrl-C` 또는 종료 신호를 받았습니다 | `--resume`으로 이어받기 |

`COMPLETE`여도 아래 항목은 눈으로 확인합니다.

- `reachable`과 `auth_ok`가 `true`이고 `root_product`가 실제 모델명입니다(예: `Compute Scale-up Server 3200`).
- `incomplete_reasons`가 비어 있고 `unresolved`, `device_error`, `oversize`가 모두 0입니다(`COMPLETE`이면 이미 그렇습니다).
- 오류가 아닌 항목의 의미를 압니다. `absent`는 장비가 링크는 냈지만 없던 경로(참조한 곳이 함께 기록됨), `not_gettable`은 GET이 안 되는 액션 주소, `rejected`는 장비가 요청을 거절한 경우, `outside_account`는 계정 권한 밖입니다. `outside_account`가 많으면 일부 리소스가 가려진 것이므로 더 높은 권한 계정으로 다시 캡처합니다.
- `INCOMPLETE`의 `device_error`는 재시도와 마지막 재확인 뒤에도 같은 5xx 또는 무응답이지만 다른 요청은 정상인 경우입니다(`origin: device`). 장비가 그 경로를 제대로 내주지 않는 것이라 도구가 성공으로 바꾸지 않습니다. 시간을 두고 `--resume`으로 다시 시도하고, 시간 초과(`cause: timeout`)였다면 `--timeout`을 올립니다. 끝내 안 되는 경로는 `device_error[]`의 경로, 상태, 시도 횟수를 근거로 보고합니다.
- `excluded`는 사용자가 정한 제외(`--exclude`, `--no-action-targets`, `--no-binary`)와 정책 제외(`ServerSentEventUri`와 `.../SSE`는 GET하면 스트림이 끝나지 않아 요청하지 않음)이며 미완료로 세지 않습니다. 크기 상한으로 못 받은 첨부는 `oversize`에 URI, Content-Type, 크기, 원인과 함께 따로 있고 `INCOMPLETE`입니다.
- 멀티 노드 장비면 모든 파티션, 모든 Manager(RMC, chassis 컨트롤러, 노드 iLO), 모든 chassis가 들어 있습니다.
- OEM 리소스(`Oem.Hpe.*` 등) 디렉터리가 있습니다.
- 펌웨어 버전이 `_manifest.json`의 `firmware_versions`와 폴더 이름에 남았습니다.
- 반출 뒤 파일이 빠지지 않았는지 `summary.files_expected`(저장한 `index.json` 수)와 `find <폴더> -name index.json | wc -l`을 비교합니다. `integrity.missing_count`와 `unaccounted`가 0이어야 합니다(`unaccounted`가 있으면 이전 실행의 잔여가 섞인 것입니다. 새로 받으려면 폴더를 비우세요).
- Windows로 가져올 때 경로가 260자를 넘지 않는지 `summary.max_rel_path_chars`에 압축 푼 위치의 길이를 더해 봅니다. 도구는 상대경로를 200자 안으로 줄이고 `Aux`, `COM1` 같은 예약어와 대소문자만 다른 경로를 서로 다른 폴더로 저장하며, 그 대응은 `_fsmap.json`에 있습니다.
- 산출물에는 계정 이름, IP, 시리얼 번호가 들어 있으므로 외부로 옮길 때 취급에 주의하세요. 비밀번호와 세션 토큰은 저장하지 않습니다.
- 가능하면 사본을 하나 더 만들어 압축해 보관합니다.

## 6. 반출 뒤 개발 환경에서 재생

1. 반출한 트리를 그대로 가져옵니다.
2. 트리를 fixture로 변환해 오프라인으로 재생합니다. 멀티 노드 장비는 `--manager-layout`을 붙여야 `multi_node`가 채워집니다.

   ```bash
   # 저장소 루트
   python tests/integration/convert_dmtf_mockup.py \
       --mockup-dir <반출 트리>/redfish/v1 --name hpe_csus_3200_real \
       --manager-layout rmc_primary --captured <YYYY-MM-DD>
   ```

   산출된 `expected_output.json`의 `data`(섹션)와 `multi_node`(파티션, Manager, chassis)를 확인합니다. `tests/unit/test_csus_fixture_replay.py`는 평평한 fixture 디렉터리를 읽으므로 크롤러 트리를 직접 재생하지 못합니다. 트리 재생은 위 변환 경로만 씁니다. 트리에서 멀티 노드를 재구성하는 경로는 `tests/unit/test_full_mirror_dryrun.py`가 합성 데이터로 고정합니다.

   `raw.<확장자>` 파일과 `@odata.id`가 없는 `index.json` 안내 파일, `_links.json`, `_fsmap.json`은 변환기와 재생기가 알아서 건너뜁니다.
재생기(`tests/redfish-probe/replay_full_mirror.py`)와 변환기(`convert_dmtf_mockup.py`)는 같은 로더를 쓰며 다음을 지킵니다.

- 페이지로 나뉜 컬렉션은 페이지마다 `?쿼리`가 붙은 키로 재생해 모든 멤버가 나옵니다(예전에는 마지막 페이지만 남아 Dell의 `DellSensors` 62개 중 12개만 재생됐습니다). 페이지 수와 멤버 수가 1페이지의 `Members@odata.count`와 다르거나 사슬이 끊기면 `[WARN]`으로 보고합니다. 로그 같은 살아 있는 컬렉션은 캡처 도중 늘어나므로 차이가 날 수 있고, 조용히 넘기지 않고 기록합니다.
- `headers.json`의 HTTP 상태를 그대로 씁니다. 400, 401, 403, 404, 405, 500 같은 오류 응답을 200으로 바꾸지 않고, v2 manifest의 `absent`, `outside_account`, `not_gettable`, `rejected`, `device_error` 상태도 본문 없이 되살립니다. 응답이 없던 전송 실패(status 0)는 HTTP 상태가 아니므로 재생하지 않습니다.
- 요청 경로는 `_fsmap.json`을 따르므로 링크 경로와 본문 `@odata.id`가 다른 별칭도 사라지지 않습니다.

3. 재생에서 드러난 차이(서비스 루트 제품 문자열, Manager와 System과 Chassis의 ID 형식, OEM 필드 구조)를 코드에 반영하고 회귀 시험을 추가한 뒤 기준선을 갱신합니다.

CSUS의 OEM 필드(`Oem.Hpe.PartitionInfo`, `FlexNodeInfo`, `GlobalConfiguration`) 추출은 라이브러리에 있지만 실장비 응답으로 검증한 적이 없습니다. 실제 캡처가 들어오면 이 경로를 먼저 확인합니다.

## 7. 한계

- 읽기 전용 스냅샷입니다. 계정 생성이나 전원 제어 같은 쓰기 동작은 담기지 않습니다.
- 캡처 시점의 펌웨어와 상태입니다. 펌웨어를 올리면 응답이 달라질 수 있습니다. 로그처럼 살아 있는 컬렉션은 캡처하는 동안에도 늘어납니다.
- 링크로 닿는 것만 받습니다. 장비가 어디에서도 가리키지 않는 리소스는 찾지 못합니다(표준 고정 주소 3개는 예외로 직접 요청합니다).
- 장비가 세션 로그인과 Basic 인증을 모두 거절하면 받을 수 없습니다(`ABORT`).
- 예전(v1) 도구로 받은 트리에는 크롤러가 실제로 요청한 경로가 기록되어 있지 않습니다. 재생기는 본문 `@odata.id`로 키잉하고 `nextLink`로 후속 페이지를 복원하지만, 링크 경로와 본문 id가 다른 별칭은 복원하지 못합니다(실측 Dell의 `FirmwareInventory/<id>/Oem/Dell/DellSoftwareInventory/...` 62개). 새 도구로 받은 트리는 영향이 없습니다.

## 8. 원본 캡처의 민감정보와 보관

캡처 파일은 장비가 준 원본이라 관리 IP와 MAC, 호스트 이름, 시리얼 번호와 자산 태그, 계정 이름과 역할(`AccountService`), 인증서, 알림·원격 로그·SNMP 수신 대상과 일부 장비의 SNMP 커뮤니티 문자열, 라이선스 키, 디버그 로그 묶음(`AdditionalDataURI`) 안의 내부 정보가 들어 있을 수 있습니다. 도구는 비밀번호와 세션 토큰을 저장하지 않지만 장비가 본문에 담아 돌려주는 값까지 걸러 주지는 않습니다.

- 보관: 도구와 러너는 캡처를 소유자만 읽도록(`umask 077`) 만듭니다. 반출용 압축은 접근을 제한한 곳에만 두고, 반출이 끝나면 현장 서버의 원본 폴더를 지웁니다. 옮기거나 풀 때 권한이 넓어지지 않게 하세요.
- 저장소에 넣기 전 점검: 캡처 원본은 저장소에 커밋하지 않습니다. fixture나 외부에 공유할 mock으로 쓰려면 (1) 이름에 `Password`, `Community`, `Secret`, `Token`, `Key`, `Cert`가 들어간 키의 값을 검색해 지우거나 가상 값으로 바꾸고, (2) 실제 관리 IP, 호스트 이름, 시리얼, MAC, 계정 이름을 가상 값으로 치환한 사본을 만들고, (3) `raw.*` 첨부(디버그 로그, 라이선스)는 mock에 넣지 않습니다. 치환 뒤 같은 검색을 다시 하고, 저장소에 들어가는 파일은 `python scripts/ai/verify_no_plaintext_secret.py`(알려진 운영 자격증명을 다이제스트로 대조)를 통과해야 합니다.

## 관련

| 내용 | 위치 |
|---|---|
| 캡처 도구 | `tests/redfish-probe/redfish_full_mirror.py` |
| 여러 대 병렬 실행 | `tests/redfish-probe/mirror_many.sh` |
| 도구 동작 시험 | `tests/unit/test_full_mirror_dryrun.py` |
| 재생·변환 도구 시험 | `tests/unit/test_mirror_replay_tools.py` |
| 오프라인 재생기 | `tests/redfish-probe/replay_full_mirror.py` |
| 오프라인 재생 변환 | `tests/integration/convert_dmtf_mockup.py` |
| CSUS 합성 fixture와 미검증 항목 | `tests/fixtures/redfish/hpe_csus_3200/README.md` |
| RMC Redfish 확인 | [../operate/06-rmc-activation.md](../operate/06-rmc-activation.md) |
