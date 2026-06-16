#!/usr/bin/env python3
"""실측 전수 미러 → 오프라인 회귀 fixture(recording.json + expected_output.json) 변환.

`redfish_full_mirror.py` 가 실 BMC 에서 떠온 미러 트리(<dir>/redfish/v1/.../index.json
+ headers.json)를, gather 가 실제로 touch 하는 endpoint 만 골라 recording.json
(emulator_harness.make_replayer 호환 포맷: {"get::<path>": [status, body, err]})로 압축하고,
모듈 산출을 GOLDEN_KEYS 로 snapshot 해 expected_output.json 으로 저장한다.

이렇게 만든 fixture 는 tests/integration/test_real_capture_replay.py 가 오프라인(미러 트리
없이, 네트워크 없이) 재생해 redfish_gather.py 파싱/정규화를 4대 실장비 기준으로 회귀 검증한다.

사용:
    python tests/integration/capture_mirror_fixture.py <mirror_dir> <fixture_name> [--layout rmc_primary]
    # 예: ... "C:\\github\\서버mock데이터\\DELL_R740\\01" real_dell_r740
"""
from __future__ import annotations

import argparse
import json
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "tests" / "redfish-probe"))
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

for n in ("ansible", "ansible.module_utils", "ansible.module_utils.basic"):
    sys.modules.setdefault(n, types.ModuleType(n))
sys.modules["ansible.module_utils.basic"].AnsibleModule = object

import replay_full_mirror as RFM  # noqa: E402
import redfish_gather as rg  # noqa: E402
import emulator_harness as H  # noqa: E402

FIXTURE_ROOT = REPO / "tests" / "fixtures" / "redfish"


def build(mirror_dir: Path, manager_layout=None):
    """미러 → recording + golden. golden 은 test 와 동일한 H.run_gather 로 생성해
    (collected 정렬 등) 산출 경로를 1:1 일치시킨다 — golden flakiness 0."""
    response_map, service_root, stats = RFM.build_response_map(mirror_dir)
    recording: dict = {}
    miss = (404, {}, "HTTP 404: Not Found")

    def rec_get(bmc_ip, path, username, password, timeout, verify_ssl):
        resp = response_map.get(path, miss)
        recording[f"get::{path}"] = [resp[0], resp[1], resp[2]]
        return resp

    def rec_noauth(bmc_ip, path, timeout, verify_ssl):
        resp = response_map.get(path, miss)
        recording[f"noauth::{path}"] = [resp[0], resp[1], resp[2]]
        return resp

    def rec_realm(bmc_ip, timeout, verify_ssl):
        # Manufacturer 로 vendor 식별되는 4대(dell/hpe/lenovo)는 realm probe 미도달.
        # 네트워크 차단 위해 None 고정 (make_replayer 의 realm:: 부재와 동일).
        return None

    # test(make_replayer + run_gather)와 동일 함수로 산출 → golden strict 일치 보장.
    result = H.run_gather(rec_get, rec_noauth, realm_impl=rec_realm,
                          manager_layout=manager_layout)
    golden = {k: json.loads(json.dumps(result[k], ensure_ascii=False, sort_keys=True))
              for k in H.GOLDEN_KEYS}
    return recording, golden, stats, result["vendor"], result["status"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mirror_dir")
    ap.add_argument("fixture_name")
    ap.add_argument("--layout", default=None)
    args = ap.parse_args()

    mirror_dir = Path(args.mirror_dir)
    if not mirror_dir.exists():
        print(f"[FAIL] mirror_dir 없음: {mirror_dir}", file=sys.stderr)
        return 2

    recording, golden, stats, vendor, status = build(mirror_dir, manager_layout=args.layout)
    out_dir = FIXTURE_ROOT / args.fixture_name
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "recording.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(recording, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    with open(out_dir / "expected_output.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(golden, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")

    print(f"[OK] {args.fixture_name}: vendor={vendor} status={status} "
          f"recorded_endpoints={len(recording)} (mirror keyed={stats['keyed']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
