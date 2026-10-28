# 미러 출처 · 무결성 (2026-10-28)

이번 재검증의 Tier 1 · Tier 2 입력. 원본은 읽기만 했고 새 경로에 추출 · 복사했다(구현 · 독립 검증의 미러 폴더는 건드리지 않음).

| 구분 | 원본 | Tier 1 (WSL `Ubuntu-24.04`, HTTPS 재생 서버) | Tier 2 (Windows, 모듈 재생) |
|---|---|---|---|
| 2차 Mock 11대 | 저장소 `tests/reference/redfish/mock2/*.zip` | `/root/se_mirrors_fix_20261028/<label>` — `sha256sum -c SHA256SUMS` 통과 뒤 `tests/redfish-probe/mirror_replay/extract_mirrors.sh` 로 추출 | `C:/github/ClovirONE/mock2-fix-20261028/extract/<label>` — 같은 zip 을 SHA256SUMS 확인 뒤 추출 |
| 1차 Mock 7대 | `C:/github/서버mock데이터/1차/<VENDOR>/<nn>` | `/root/se_mirrors_fix_20261028/mock1/<VENDOR>/<nn>` — `cp -a` 사본 | 원본 경로를 그대로 읽음 |

- 준비 스크립트: `tools/prep_mirrors.sh`(대상 경로가 이미 있으면 중단 — 덮어쓰지 않음).
- digest = 미러 폴더 안 `find . -type f` 를 `LC_ALL=C` 로 정렬한 `sha256sum` 목록 전체의 sha256(경로 · 내용 둘 다 반영).

## 결과

- 2차 11대: WSL 추출본과 Windows 추출본의 파일 수 · digest 가 11대 모두 같다 → Tier 1 과 Tier 2 는 같은 입력을 읽었다.
  - Git Bash 의 `sha256sum` 은 줄 표기가 `<hash> *./path`(GNU 는 `<hash>  ./path`)라 그대로 계산하면 digest 가 전부 다르게 나온다. `*` 표기를 GNU 표기로 바꾼 뒤 계산했다(`pristine/mirror_digests_windows_extract.txt`).
    한 파일의 해시 값 자체는 두 쪽이 같다(예: dl380_gen12_03 `redfish/headers.json` `e53f6621…`).
- 1차 7대: 원본 digest == 사본 digest(7/7 SAME, `pristine/mirror_digests_wsl.txt`).

| label | 파일 수 | digest |
|---|---|---|
| csus3200_01 | 4068 | `2e440457da51ae8ccec7a92d854155642543fc05ef18340987285e984afb58fa` |
| csus3200_02 | 3974 | `4693ed75876f85c41edc0c03a270d2ea7db0ddb028dd677c79b3cdd36d1d7bda` |
| csus3200_03 | 3998 | `30b6642054fbd7977cb379ae3b4d83dccd7d6214dfd7108f61f5de42ffb1dc8a` |
| dl380_gen12_01 | 3551 | `a6fb67d5508cef042aecb97f776a79a6080c83da44cd145d7553f9d66d3484b7` |
| dl380_gen12_02 | 3009 | `6353c8cd1d6b380aae5bc9834aeec51c5fcefe01e984f31d4359687afdc8834d` |
| dl380_gen12_03 | 2413 | `46bba10564c59544ab92f581b103f6ea4af17fe059886e52d7ec7881f9eb27a4` |
| dl380_gen12_04 | 3575 | `40c867010ddf0b51b8c171f3235325df91d16b27d0bdee45d5c19a7ef243e7b8` |
| sr650_v4_01 | 4506 | `c94099557dd232e3e4c552f90b634991f0d03f36d209f06dbfceb65b3b82f181` |
| sr650_v4_02 | 4730 | `450f76bc39733cf64c12413cad4e93dedcc16003a8cf7d00879807ed08fbe605` |
| sr650_v4_03 | 5684 | `ecd700407405fcb73b66c4194570f07fe3d689c00a8ba4dc1043c0458c0c8f43` |
| sr650_v4_04 | 4426 | `59bc2b20bb91c0745439d15a76167320e97fc868647b410b59cd82c2e69f02d9` |
| r1 DELL_R740/01 | 12268 | `9692a3e942a51b1dc5525ead7760e9f991b7826cb42874b08eb286b666bba4c7` |
| r1 HPE_CSUS3200/01 | 982 | `e898854340a88969427b18213aab5b2036f535fa967b67f2d16426819af303f7` |
| r1 HPE_CSUS3200/02 | 988 | `44251b0ff91942a17b1158f463e5a5d35fc55041396ba2294cd3da43ff6913bc` |
| r1 HPE_CSUS3200/03 | 1276 | `22b7893695d29065f0815ab57abef405e9026f8281240f6843ba9dfd848abffa` |
| r1 HPE_CSUS3200/04 | 1274 | `0d761b9870adc42671a23833bf8e5e7c01f94d7d86a3c11f8c72c1ecabddcbc5` |
| r1 HPE_DL380/01 | 4112 | `1e4db516f449a12b997c92d994245168a993c04b2927e3d9a4e850187a37cdd2` |
| r1 Lenovo_SR650/01 | 5816 | `9f8d50b853f13d2548528d0a9646ca0cdef5bf3b16d7ad19bcc3d915042428c1` |
