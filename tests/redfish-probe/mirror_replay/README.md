# tests/redfish-probe/mirror_replay — 전수 미러 재생 (Tier 1 / Tier 2)

실장비 BMC 에서 `redfish_full_mirror.py` 로 떠온 **전수 미러**(예: `tests/reference/redfish/mock2/*.zip`)를 실제 Gathering 경로로 다시
돌리는 도구다. 2026-10-26 분석 Round 의 `tests/evidence/2026-10-26-redfish-mock2-audit/tools/` 를 2026-10-27 사용자 FIX 8 로
저장소에 편입하면서 개인 경로·배포판 이름·vault 파일 경로를 전부 인자/환경변수로 바꿨다. 실장비에는 접속하지 않는다.
이 디렉터리는 `tests/**` 라 production 브랜치에 나가지 않는다.

| 층 | 무엇을 돌리나 | 도구 | 네트워크 |
|---|---|---|---|
| Tier 2 | 모듈 수준 재생 — `emulator_harness.run_gather` 와 같은 엔진으로 `redfish_gather.py` 만 (Ansible normalize 층 없음) | `tier2_replay.py` | 0 |
| Tier 1 | **실제 `ansible-playbook redfish-gather/site.yml`** — precheck → detect_vendor → 실제 vault → adapter 1차 선택 → 수집(모듈 `main()`) → 재선택 → normalize → build → `json_only` 콜백 | `run_tier1.py` → `mirror_https_server.py` + `run_playbook.sh` | 127.0.0.1:443 만 |

## 1. 준비 (한 번)

1. WSL 배포판 둘: **서버용**(443 바인드 때문에 root 로 들어가는 배포판 — 예 `Ubuntu-24.04`)과 **playbook 용**(ansible-core 가 있는 배포판 — 예 `Ubuntu`).
   한 배포판에서 root 로 둘 다 해도 된다(`--server-distro` 와 `--playbook-distro` 를 같게).
2. playbook 배포판에 vault 비밀번호 파일(권한 600, 기본 `$HOME/.se_vault_pass`; `--vault-password-file` 로 지정). 저장소에 넣지 않는다.
3. 미러를 서버 배포판의 ext4 에 푼다(`/mnt/c` 는 index.json 수천 개 로딩이 수십 배 느리다):

   ```bash
   # 서버 배포판 안에서
   bash /mnt/c/<repo>/tests/redfish-probe/mirror_replay/extract_mirrors.sh /root/se_mirrors /mnt/c/<repo>/tests/reference/redfish/mock2/*.zip
   ```
   1차 7대(`DELL_R740/01`, `HPE_CSUS3200/01..04`, `HPE_DL380/01`, `Lenovo_SR650/01`)는 저장소 밖(`C:\github\서버mock데이터\1차`, 읽기 전용)에만 있다 —
   같은 방법으로 zip 을 풀거나 폴더를 그대로 가리킨다.

## 2. Tier 1 실행 (Windows 호스트에서)

```bash
python tests/redfish-probe/mirror_replay/run_tier1.py \
  csus3200_01=/root/se_mirrors/csus3200_01 dl380_gen12_01=/root/se_mirrors/dl380_gen12_01 ... \
  --out-root C:/path/to/tier1-out --server-distro Ubuntu-24.04 --playbook-distro Ubuntu --loc yi
```

- 인증서는 `--tls-dir` 이 없으면 서버 배포판 `/tmp/se_mirror_tls.<pid>` 에 `gen_cert.sh` 로 만들고 끝나면 지운다. `*.pem`/`*.key` 는 `.gitignore`.
- 서버 종료는 `server.pid` 기준 SIGTERM 이다(같은 포트 `pkill` 금지 — rule 80).
- `run_playbook.sh` 는 운영(`Jenkinsfile_portal` `seGatherEnv` + `scripts/run_gather.sh`)과 같은 변수·인자를 쓴다: `redfish-gather/inventory.sh` +
  `INVENTORY_JSON_FILE`(`[{"bmc_ip":"127.0.0.1"}]`), `ANSIBLE_JSON_{OUTPUT,MANIFEST,PROGRESS,CHECKPOINT}_FILE`, `SE_AUTH_EVIDENCE_DIR`, `SE_BUILD_ID`,
  `--limit @file`, `--vault-password-file`, `-e se_location`, `timeout --signal=INT --kill-after=90`.
  **운영과 다른 것**(검증 한계): `run_gather.sh` 의 작업 폴더 잠금 · `gather_state.py begin/end` · FORKS 계산 · 대상 목록 재개는 거치지 않는다.
  분석 Round(2026-10-26)의 임시 도구는 `os-gather/inventory.sh` + `service_ip` 로 돌았으므로, 그 기준선과 이 판의 산출은 `ip`/`correlation.host_ip` 류가 다를 수 있다.
- 산출(label 마다): `gather_output.json`(최종 봉투, 1줄 1봉투) · `requested_keys.json`(요청 집합) · `server_access.jsonl`(경로·상태·인증 구분만 — Authorization 값은 기록하지 않음) ·
  `run_meta.json` · `server_ready.json` · `ansible_stdout/stderr.log` · `gather_auth_evidence/`. evidence 로 커밋할 때 `gather_auth_evidence/` · `.inventory_input.json` ·
  `ansible_*.log` 는 빼거나 내용을 검사한다.

## 3. Tier 2 실행 (어디서나, 네트워크 0)

```bash
python tests/redfish-probe/mirror_replay/tier2_replay.py <out_dir> dl380_gen12_01=<mirror dir> ...            # plain
python tests/redfish-probe/mirror_replay/tier2_replay.py <out_dir> csus3200_01=<mirror dir> --layout rmc_primary --firmware-scope complex_only --tag adapter
```
Tier 2 통과만으로 실제 Ansible 경로(재선택 · 정규화 · category · hostname 정책 · serial 접미사)를 검증했다고 말하지 않는다.

## 4. before/after 대조

```bash
python tests/redfish-probe/mirror_replay/diff_tier1.py <before_root> <after_root> --allow allow.json --out report.md
```
허용목록(label · 경로 prefix/정규식 · 요청 prefix · 이슈 ID · 근거) 밖의 차이가 있으면 종료 코드 1. 휘발 경로(`meta.started_at/finished_at/duration_ms`)는 비교하지 않는다.

## 5. 재생이 흉내 내지 못하는 것 (분석 Round `baseline/README.md` 1~9 와 같다)

1. 익명 허용 범위: ServiceRoot · odata · $metadata · /redfish 만 무인증 200, 나머지는 401 — 실장비의 익명 허용 집합은 미러에 없다.
2. 인증: Basic 에 사용자 이름만 있으면 통과(비밀번호 검증 없음). 401/403 분기, 계정 잠금, 복구 경로는 재현되지 않는다.
3. 무응답(timeout) 리소스는 "응답 없이 연결 종료" 로 근사.
4. 미러에 없는 경로는 404 — 실장비가 다른 상태/본문을 줄 수 있다.
5. 401 본문 · `WWW-Authenticate` 는 실장비와 다를 수 있다.
6. 1차 v1 미러: 비-2xx 가 기록되지 않아 404 로만 재생.
7. 엔진 버전(WSL ansible-core)과 운영 Agent 버전이 다를 수 있다.
8. precheck 의 ICMP/TCP 는 127.0.0.1 대상 — 네트워크 경로 판정은 검증 대상이 아니다.
9. `correlation.bmc_ip` 는 미러 안의 BMC NIC 주소(원 장비 IP)로 채워진다 — `ip`/`host_ip`(127.0.0.1)와 다르다.
