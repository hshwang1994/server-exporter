# tests/reference/redfish/mock2/ — 2차 Redfish 전수 미러 (용인 11대, 2026-10-22 수집)

> 실장비 BMC 에서 `tests/redfish-probe/redfish_full_mirror.py` v2.2.0 으로 떠온 **전수 미러** 11대를 서버당 zip 하나로 보관한다.
> 1차 보관 방식(`tests/fixtures/redfish/real_*` — gather 가 실제 요청한 경로만 축약한 recording)과 달리, 장비가 노출한 모든 GET 리소스를
> 그대로 담고 있어 "코드가 아직 요청하지 않는 정보" 까지 조사할 수 있다. 회귀 테스트가 직접 읽는 입력은 아니다(그 역할은 `tests/fixtures/`).
>
> 이 폴더는 production 브랜치에 나가지 않는다(`production_manifest.yml` 이 `tests/**` 를 제외).

## 출처

| 항목 | 값 |
|---|---|
| 수집 일시 | 2026-10-22 05:51 ~ 06:56 UTC (`run.log`, 각 `_manifest.json` 의 `started`/`finished`) |
| 수집 도구 | `redfish_full_mirror.py` 2.2.0, manifest schema 2, `mirror_many.sh` 로 11대 병렬 |
| 수집 계정 | 표준 수집 계정(`vault/common/redfish/standard.yml` 의 primary), CSUS 3대는 Basic, 나머지는 session 인증 |
| 원본 위치 | `C:\github\서버mock데이터\2차` (수집 PC, 읽기 전용 보관) — zip 은 그 폴더의 바이트 단위 사본이다 |
| 저장소 반영 | 2026-10-26, 분석 Round(Redfish 2차 Mock 전수 분석)의 근거 자료로 보관 |

## 서버별 상태 (수집 시점 실측 — 아카이브는 불변이므로 수치를 적는다)

| zip | 제품 (ServiceRoot.Product) | Redfish | 미러 결과 | 파일 | 원본 MB | zip MB | discovered / fetched 2xx | absent / not_gettable / rejected / device_error |
|---|---|---|---|---|---|---|---|---|
| csus3200_01 | Compute Scale-up Server 3200 | 1.19.0 | INCOMPLETE / exit 1 | 4068 | 8.7 | 3.3 | 2083 / 2020 | 57 / 0 / 0 / 6 |
| csus3200_02 | Compute Scale-up Server 3200 | 1.19.0 | INCOMPLETE / exit 1 | 3974 | 9.3 | 3.3 | 2040 / 1974 | 57 / 0 / 0 / 9 |
| csus3200_03 | Compute Scale-up Server 3200 | 1.19.0 | INCOMPLETE / exit 1 | 3998 | 8.6 | 3.3 | 2048 / 1985 | 57 / 0 / 0 / 6 |
| dl380_gen12_01 | HPE ProLiant Compute DL380 Gen12 | 1.22.1 | COMPLETE / exit 0 | 3551 | 6.7 | 2.4 | 2321 / 1777 | 263 / 3 / 278 / 0 |
| dl380_gen12_02 | HPE ProLiant Compute DL380 Gen12 | 1.22.1 | COMPLETE / exit 0 | 3009 | 5.9 | 2.0 | 1907 / 1501 | 127 / 3 / 276 / 0 |
| dl380_gen12_03 | HPE ProLiant Compute DL380 Gen12 | 1.22.1 | COMPLETE / exit 0 | 2413 | 3.3 | 1.6 | 1583 / 1208 | 91 / 3 / 281 / 0 |
| dl380_gen12_04 | HPE ProLiant Compute DL380 Gen12 | 1.22.1 | COMPLETE / exit 0 | 3575 | 6.7 | 2.4 | 2214 / 1790 | 144 / 3 / 277 / 0 |
| sr650_v4_01 | (ServiceRoot 에 Product 없음 — ThinkSystem SR650 V4, XCC3) | 1.22.0 | INCOMPLETE / exit 1 | 4506 | 34.3 | 9.6 | 3122 / 2130 | 894 / 97 / 0 / 1 |
| sr650_v4_02 | (같음) | 1.22.0 | INCOMPLETE / exit 1 | 4730 | 35.3 | 10.0 | 3235 / 2242 | 894 / 98 / 0 / 1 |
| sr650_v4_03 | (같음) | 1.22.0 | INCOMPLETE / exit 1 | 5684 | 38.1 | 11.1 | 3710 / 2719 | 894 / 96 / 0 / 1 |
| sr650_v4_04 | (같음) | 1.22.0 | INCOMPLETE / exit 1 | 4426 | 34.1 | 9.6 | 3083 / 2090 | 894 / 98 / 0 / 1 |

- INCOMPLETE 의 뜻: 폴더가 없는 것이 아니라 **장비가 반복해서 5xx/무응답을 준 리소스가 있었다**는 뜻이다 (`_manifest.json` 의 `device_error[]`).
  CSUS 는 `RawFruData/.../PCIE_SLOT*` HTTP 500 과 `Managers/RMC/LogServices/RmcConfig/RawConfig` timeout, SR650 V4 는 `LicenseService/Licenses/{LicenseId}`(템플릿 경로) HTTP 500 이다.
  Gathering 이 읽는 리소스가 아니므로 수집 결과에는 영향이 없다 — 각 서버의 분류는 분석 Round 의 인벤토리를 본다.
- `absent`(404/410) 는 장비가 링크는 냈지만 존재하지 않는 리소스, `rejected` 는 iLO 7 의 `SchemaStore` 406(Accept 협상) 이다. 둘 다 오류가 아니다.

## 보관 형태와 무결성

```text
tests/reference/redfish/mock2/
├── README.md            ← 이 파일
├── MANIFEST.json        ← 서버별 파일 수 · 바이트 · zip sha256 · manifest 요약 (기계 판독)
├── SHA256SUMS           ← zip 11개의 sha256 (텍스트 파일은 EOL 정규화 때문에 넣지 않는다)
├── run.log              ← mirror_many.sh 의 11대 실행 요약(원본 그대로)
└── <server>.zip         ← 내부 경로 <server>/… (원본 폴더 상대경로 그대로, deflate)
```

- 2026-10-26 검증: zip 을 풀어 원본과 **파일 수 · 상대경로 · sha256 을 전수 대조해 11대 모두 누락 0 · 차이 0**, zip 자체의 sha256 은 `SHA256SUMS` 와 일치.
  풀어낸 사본으로 오프라인 재생(`tests/integration/emulator_harness.py`)한 모듈 산출은 원본 폴더로 재생한 것과 11대 모두 동일했다.
- 검증 명령: `sha256sum -c SHA256SUMS` (Linux) 또는 `Get-FileHash <zip> -Algorithm SHA256` (PowerShell).

## 포함 내용물 — 치환하지 않았다 (2026-10-26 사용자 결정)

원본은 반출 전에 더미 기반 안전 정보로 준비된 자료라서 **익명화·제외 없이 그대로** 담았다. 안에는 BMC 관리 IP, BMC 호스트 이름, 시리얼, MAC,
수집 계정 이름(URL 경로 `AccountService/Accounts/<이름>`), 공개 인증서(PEM), CSUS 감사 로그(`LogService/Oem/Audit/raw.txt`), nPar 설정 첨부(`.npar`/`.bin`),
FRU raw(`.bin`), XCC3 디버그 로그 첨부(`DebugLog_*.tar.zst`, 서버당 약 5 MB), FoD 라이선스 키(`.key`), `$metadata`/스키마 XML 이 들어 있다.
비밀값(세션 토큰 · Bearer · 개인키 · 실제 비밀번호 값)은 검사해서 0건임을 확인했다(`headers.json` 은 미러 도구가 토큰/쿠키 헤더를 제거하고 저장한다).

## 사용 절차

1. **풀기** — `tests/fixtures/` 아래에는 풀지 않는다(`real_*` 이름과 `tests/fixtures/**/*.json` 전수 스캔 테스트에 자동 등록된다). 경로가 길어(최장 153자)
   Windows 에서는 짧은 루트(예: `C:\mock2\`)를 쓴다. WSL/Linux 는 어디든 된다.
   ```bash
   python -m zipfile -e tests/reference/redfish/mock2/dl380_gen12_01.zip /tmp/mock2/
   ```
2. **모듈 수준 재생(빠름, 네트워크 없음)** — gather 가 실제 요청하는 경로를 미러에서 찾아 돌려준다. 테스트와 같은 엔진(`emulator_harness.run_gather`)이다.
   ```bash
   PYTHONUTF8=1 python tests/redfish-probe/replay_full_mirror.py /tmp/mock2/dl380_gen12_01 --out env.json
   # CSUS 3200 은 adapter 가 주는 값과 같게: --layout rmc_primary --firmware-scope complex_only
   ```
   `replay_full_mirror.py` 단독 실행은 harness 와 달리 serial resolver 를 거치지 않고 ip 10.0.0.1 을 쓴다 — golden 비교에는 `capture_mirror_fixture.py` 경로를 쓴다.
3. **축약 fixture 로 변환(회귀 입력이 필요할 때)** — `python tests/integration/capture_mirror_fixture.py /tmp/mock2/<server> <fixture_name> [--layout rmc_primary --firmware-scope complex_only]`.
   fixture 이름을 `real_` 로 시작하면 golden/budget 테스트에 자동 등록되니 의도할 때만 쓴다.
4. **실제 엔진 경로 재생(ansible-playbook 까지)** — 분석 Round 에서는 미러를 HTTPS 로 되돌려 주는 임시 서버를 두고 `redfish-gather/site.yml` 을 그대로 돌렸다.
   그 서버는 저장소에 넣지 않았다(분석 단계 산출물 — 편입 여부는 후속 구현 계획의 결정 항목). 절차와 한계는 `tests/evidence/2026-10-26-redfish-mock2-audit/` 를 본다.
5. **노출 vs 요청 대조** — `python scripts/ai/redfish_coverage_diff.py /tmp/mock2/<server> [--layout rmc_primary] --json out.json` (main 전용 보조 도구).

## 관련

- 수집 절차 · 한계: `docs/develop/08-onsite-capture.md`
- 미러 도구: `tests/redfish-probe/redfish_full_mirror.py`, 재생: `tests/redfish-probe/replay_full_mirror.py`, `tests/integration/emulator_harness.py`
- 1차 축약 fixture: `tests/fixtures/redfish/real_*` (2026-06 수집, 다른 장비)
- 분석 Round 결과: `tests/evidence/2026-10-26-redfish-mock2-audit/`
