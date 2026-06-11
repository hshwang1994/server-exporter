# 25. 운영망 Redfish 전수 캡처 런북 (1회 반입용)

> **언제 쓰나**: 실 BMC/RMC(특히 HPE CSUS 3200 / Superdome RMC)가 운영망에만 있고, 그
> 망은 접근이 제한돼 **딱 한 번만** 데이터를 빼올 수 있을 때. 인터넷망에는 장비가 없으니,
> 여기서 만든 캡처 도구를 운영망에 반입 → 전 트리 raw 를 뽑아 반출 → 다시 인터넷망에서
> AI 로 개더링 코드를 완성한다.

## 핵심 원칙

- **특정 경로를 지정하지 않는다.** 도구는 `/redfish/v1/` 부터 **장비가 실제로 주는
  `@odata.id` 링크만 재귀로** 따라가 트리 전체를 떠온다(우리 수집 코드의 가정 경로 비의존).
- **한 번뿐이라 전부 떠온다.** 향후 확장에 필요한 정보까지 남김없이. 부족하게 떠오면 못 돌아간다.
- 도구는 **stdlib 단일 파일** — 운영망 무설치 실행(`python3`만 있으면 됨).

## 준비 (인터넷망에서, 반입 전)

1. 반입 파일 1개: `tests/redfish-probe/redfish_full_mirror.py`.
2. dry-run 으로 도구 동작 확인(장비 없이):
   ```bash
   python -m pytest tests/unit/test_full_mirror_dryrun.py -q
   ```
   (합성 CSUS 트리를 라이브처럼 띄워 재귀·페이지네이션·자동발견·내성 검증)
3. 계정 확보: **최고 권한** Redfish 계정(권한 낮으면 일부 리소스가 트리에서 가려져 누락).
4. 선결 확인 항목 메모: RMC Redfish 활성화 + 라이선스(미활성 시 트리 자체가 빔 — docs RMC 활성화 가이드).

## 운영망 현장 — 캡처

```bash
python redfish_full_mirror.py -r <RMC_IP[:443]> -u <admin> -p <pw> -D csus_rmc_<fw>
```

| 플래그 | 의미 |
|---|---|
| `-r` | BMC/RMC 주소 `ip[:port]` |
| `-u` / `-p` | 최고 권한 계정 |
| `-D` | 출력 폴더 이름(아무거나 — `<fw>` 는 "어느 펌웨어 스냅샷인지" 라벨일 뿐, **캡처 범위와 무관**) |
| `--scheme` | 기본 `https` |
| (기본) | 인증서 검증 off(self-signed), `Accept`-only 헤더, Basic auth, 에러 내성, 자가진단 |

### 산출물

```
<out>/redfish/v1/.../index.json     리소스 raw 본문 (@odata.id 보존)
<out>/redfish/v1/.../headers.json   HTTP status + 응답 헤더
<out>/_manifest.json                크롤 요약·자가진단
<out>/_serviceroot_noauth.json      무인증 ServiceRoot
```

## 철수 전 완전성 검증 (못 돌아가니 필수)

`_manifest.json`(또는 stdout 요약)에서 확인:

- [ ] `reachable: true`, `auth_ok: true`
- [ ] `root_product` 가 실제 모델로 찍힘 (예: `Compute Scale-up Server 3200`)
- [ ] `fetched_ok` 가 충분히 큰 수
- [ ] `failed` 가 대부분 **진짜 404**(미지원 sub-resource)이고 **401/403(권한 갭)이 아님**
      → 401/403 多 = 계정 권한 부족, 더 높은 권한으로 재캡처
- [ ] 멀티노드 다 잡혔나: 전 Partition / 전 Manager(RMC·PDHC·iLO) / 전 Chassis(Base·Expansion)
- [ ] OEM 분기(`Oem.Hpe.*`) 디렉터리 존재
- [ ] **펌웨어 버전 기록**(`_manifest.json`의 `firmware_versions` + `-D` 폴더명)
- [ ] (여유 시) 별도 raw 덤프로 **이중화** + 압축 보관

## 반출 후 — 인터넷망에서 코드 완성

1. 반출 트리를 `tests/fixtures/redfish/hpe_csus_3200_real/` 에 투입.
2. 실 raw 재생 → 우리 코드가 어디서 틀렸는지 드러냄:
   ```bash
   python tests/integration/convert_dmtf_mockup.py --mockup-dir <반출트리>/redfish/v1 --name hpe_csus_3200_real ...
   # 또는 test_csus_fixture_replay.py 의 fixture 를 실측본으로 교체 후 재생
   ```
3. 드러난 불일치(ServiceRoot.Product 문자열 / Manager·System·Chassis ID 패턴 /
   `Oem.Hpe` schema — NEXT_ACTIONS C5/C6/C7) 를 AI 로 수정 → 회귀 고정 → baseline 승격.

## 한계 (read-only 스냅샷의 본질)

- 쓰기/Action(account_service POST/PATCH/DELETE, reset 등)은 스냅샷에 안 담김(라이브 전용).
- 캡처 시점 펌웨어/휘발값 스냅샷 — 펌웨어 업그레이드 후 응답은 달라질 수 있음.
- Basic auth 전용 — 장비가 Basic 막고 Session 만 받으면 `_manifest.json` 이 401 로 알려줌
  (그 경우 Session 지원 추가 필요).

## 관련

- 도구: `tests/redfish-probe/redfish_full_mirror.py`
- dry-run 회귀: `tests/unit/test_full_mirror_dryrun.py`
- 오프라인 재생: `tests/integration/convert_dmtf_mockup.py`, `tests/unit/test_csus_fixture_replay.py`
- CSUS 합성 fixture / 미검증 항목: `tests/fixtures/redfish/hpe_csus_3200/README.md`
