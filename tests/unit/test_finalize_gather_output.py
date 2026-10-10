"""scripts/finalize_gather_output.py (Layer A) — 요청 1개 = 결과 1개 계약 (2026-10-03, Plan §6-4).

Ansible 없이 파일만으로 구동한다. 정본 YAML(failure_reasons · supported_sections · init_fragments · build_meta ·
build_correlation)은 저장소의 실제 파일을 읽으므로 문장/shape drift 가 없다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "finalize_gather_output.py"
sys.path.insert(0, str(SCRIPT.parent))

import finalize_gather_output as fz  # noqa: E402

ALL = ["system", "hardware", "bmc", "cpu", "memory", "storage", "network", "firmware", "users", "power", "thermal"]
CATALOG = yaml.safe_load((REPO / "common/vars/failure_reasons.yml").read_text(encoding="utf-8"))["_fr_catalog"]


def _envelope(ip, status="success", channel="os"):
    return {
        "schema_version": "1", "target_type": channel, "collection_method": fz.CHANNEL_METHOD[channel],
        "ip": ip, "hostname": f"h-{ip}", "vendor": None, "status": status,
        "sections": {s: "success" for s in ALL},
        "diagnosis": {k: None for k in fz.DIAGNOSIS_KEYS} | {"details": {}},
        "meta": {}, "correlation": {}, "errors": [], "data": {"system": {"hostname": f"h-{ip}"}},
    }


def _ws(tmp_path, ips, channel="os", outputs=(), checkpoints=(), progress=(), rc=None, raw_output=None):
    (tmp_path / "gather_manifest.json").write_text(json.dumps({
        "schema": 1, "build": {"job": "j", "number": "7", "url": "u"}, "channel": channel,
        "request": {"loc": "git", "deploymentEnvironmentId": "1", "eventUuid": "e", "callbackUrl": "http://x"},
        "ips": list(ips)}), encoding="utf-8")
    if raw_output is not None:
        (tmp_path / "gather_output.json").write_text(raw_output, encoding="utf-8")
    elif outputs:
        (tmp_path / "gather_output.json").write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in outputs), encoding="utf-8")
    if checkpoints:
        (tmp_path / "gather_checkpoint.jsonl").write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in checkpoints), encoding="utf-8")
    if progress:
        (tmp_path / "gather_progress.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in progress), encoding="utf-8")
    if rc is not None:
        (tmp_path / "gather_rc.txt").write_text(f"{rc}\n", encoding="utf-8")
    return tmp_path


def _run(ws, outcome="completed"):
    names = {"manifest": "gather_manifest.json", "output": "gather_output.json", "checkpoint": "gather_checkpoint.jsonl",
             "progress": "gather_progress.jsonl", "rc": "gather_rc.txt", "final": "gather_final.jsonl",
             "report": "gather_finalize_report.json"}
    code, report = fz.finalize(ws, REPO, outcome, names)
    final = [json.loads(l) for l in (ws / "gather_final.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    return code, report, final


def test_all_outputs_present_are_passed_through_verbatim(tmp_path):
    ws = _ws(tmp_path, ["10.0.0.1", "10.0.0.2"], outputs=[_envelope("10.0.0.2"), _envelope("10.0.0.1")], rc=0)
    code, report, final = _run(ws)
    assert code == 0 and report["kept"] == 2 and report["filled"] == 0 and report["rc"] == 0
    assert [e["ip"] for e in final] == ["10.0.0.1", "10.0.0.2"], "접수 순서"
    raw = (ws / "gather_final.jsonl").read_text(encoding="utf-8").splitlines()
    assert raw[0] == json.dumps(_envelope("10.0.0.1"), ensure_ascii=False), "OUTPUT 줄은 재직렬화하지 않는다"


def test_missing_host_without_evidence_gets_output_build_failed(tmp_path):
    ws = _ws(tmp_path, ["10.0.0.1", "10.0.0.2"], outputs=[_envelope("10.0.0.1")])
    code, report, final = _run(ws, outcome="timeout")
    assert code == 0 and report["filled"] == 1 and report["by_origin"] == {"output": 1, "checkpoint": 0, "synthetic": 1}
    env = final[1]
    assert list(env) == list(fz.ENVELOPE_KEYS)
    assert env["ip"] == "10.0.0.2" and env["hostname"] is None and env["status"] == "failed"
    assert env["diagnosis"]["failure_stage"] == "fallback" and env["diagnosis"]["failure_code"] == "OUTPUT_BUILD_FAILED"
    assert env["diagnosis"]["failure_reason"] == CATALOG["output_build_failed"]["default"]
    assert env["errors"][0]["message"] == env["diagnosis"]["failure_reason"]
    assert "outcome=timeout" in env["errors"][0]["detail"]
    assert list(env["sections"]) == ALL and env["sections"]["users"] == "failed" and env["sections"]["bmc"] == "not_supported"
    assert set(env["meta"]) == {"started_at", "finished_at", "duration_ms", "adapter_id", "adapter_version", "ansible_version"}
    assert env["correlation"]["host_ip"] == "10.0.0.2" and env["data"]["storage"]["physical_disks"] == []


def test_auth_proven_then_stopped_is_gather_failed_with_auth_true(tmp_path):
    progress = [{"ts": "t", "host": "10.0.0.2", "ip": "10.0.0.2", "event": "first_seen"},
                {"ts": "t", "host": "10.0.0.2", "ip": "10.0.0.2", "event": "auth_proven", "task": "linux | preflight"},
                {"ts": "t", "host": "10.0.0.2", "ip": "10.0.0.2", "event": "cred_load", "outcome": "ok", "location": "git"}]
    ws = _ws(tmp_path, ["10.0.0.2"], progress=progress)
    code, report, final = _run(ws, outcome="timeout")
    d = final[0]["diagnosis"]
    assert d["failure_stage"] == "gather" and d["failure_code"] == "GATHER_FAILED" and d["auth_success"] is True
    assert d["failure_reason"] == CATALOG["gather_after_auth"]["os"]
    assert "outcome=timeout" in final[0]["errors"][0]["detail"] and "last_task=linux | preflight" in final[0]["errors"][0]["detail"]
    assert d["details"]["outcome"] == "timeout" and d["details"]["channel"] == "os"


def test_auth_proven_then_lost_uses_connection_lost_sentence(tmp_path):
    progress = [{"ts": "t", "host": "10.0.0.2", "ip": "10.0.0.2", "event": "auth_proven"},
                {"ts": "t", "host": "10.0.0.2", "ip": "10.0.0.2", "event": "lost", "detail": "Failed to connect"}]
    ws = _ws(tmp_path, ["10.0.0.2"], progress=progress)
    _, _, final = _run(ws)
    assert final[0]["diagnosis"]["failure_reason"] == CATALOG["gather_connection_lost"]["default"]
    assert final[0]["errors"][0]["detail"].startswith("Failed to connect | ")


def test_lost_without_auth_evidence_is_auth_probe_failed_with_loc(tmp_path):
    progress = [{"ts": "t", "host": "10.0.0.2", "ip": "10.0.0.2", "event": "cred_load", "outcome": "ok", "location": "git"},
                {"ts": "t", "host": "10.0.0.2", "ip": "10.0.0.2", "event": "lost"}]
    ws = _ws(tmp_path, ["10.0.0.2"], progress=progress)
    _, _, final = _run(ws)
    d = final[0]["diagnosis"]
    assert d["failure_stage"] == "auth" and d["failure_code"] == "AUTH_PROBE_FAILED" and d["auth_success"] is None
    assert d["failure_reason"] == CATALOG["auth_unconfirmed"]["os"].replace("{loc}", "git")

    progress[0]["outcome"] = "empty_accounts"
    ws2 = _ws(tmp_path / "b", ["10.0.0.2"], progress=progress) if (tmp_path / "b").mkdir() is None else None
    _, _, final2 = _run(ws2)
    assert final2[0]["diagnosis"]["failure_reason"] == CATALOG["loc_vault_no_account"]["os"].replace("{loc}", "git")


def test_precheck_failure_diagnosis_is_preserved(tmp_path):
    diag = {"reachable": False, "port_open": False, "protocol_supported": None, "auth_success": None,
            "failure_stage": "reachable", "failure_code": "TARGET_UNREACHABLE",
            "failure_reason": CATALOG["target_unreachable"].get("os") or CATALOG["target_unreachable"]["default"],
            "details": {"channel": "os", "checked_ports": [22]}}
    progress = [{"ts": "t", "host": "10.0.0.2", "ip": "10.0.0.2", "event": "precheck", "diagnosis": diag}]
    ws = _ws(tmp_path, ["10.0.0.2"], progress=progress)
    _, _, final = _run(ws, outcome="interrupted_unknown")
    d = final[0]["diagnosis"]
    assert d["failure_stage"] == "reachable" and d["failure_code"] == "TARGET_UNREACHABLE" and d["reachable"] is False
    assert d["details"]["checked_ports"] == [22] and d["details"]["outcome"] == "interrupted_unknown"
    assert final[0]["errors"][0]["section"] == "precheck"


def test_checkpoint_restores_assembled_envelope_with_cause_specific_error(tmp_path):
    cp = _envelope("10.0.0.3", status="partial")
    progress = [{"ts": "t", "host": "10.0.0.3", "ip": "10.0.0.3", "event": "checkpoint"},
                {"ts": "t", "host": "10.0.0.3", "ip": "10.0.0.3", "event": "addon_started"}]
    ws = _ws(tmp_path, ["10.0.0.3"], checkpoints=[cp], progress=progress)
    code, report, final = _run(ws, outcome="timeout")
    assert report["by_origin"]["checkpoint"] == 1 and report["filled"] == 0
    env = final[0]
    assert env["status"] == "partial" and env["sections"] == cp["sections"] and env["diagnosis"] == cp["diagnosis"]
    assert env["errors"][-1]["section"] == "addon" and env["errors"][-1]["message"] == fz.ADDON_INTERRUPTED

    progress.append({"ts": "t", "host": "10.0.0.3", "ip": "10.0.0.3", "event": "addon_done"})
    (tmp_path / "c").mkdir()
    ws2 = _ws(tmp_path / "c", ["10.0.0.3"], checkpoints=[cp], progress=progress)
    _, _, final2 = _run(ws2, outcome="timeout")
    assert final2[0]["errors"][-1]["section"] == "gather" and final2[0]["errors"][-1]["message"] == fz.EMIT_FAILED


def test_truncated_tail_and_corrupt_line_are_dropped_and_reported(tmp_path):
    good = json.dumps(_envelope("10.0.0.1"))
    raw = good + "\n" + "{not json}\n" + json.dumps(_envelope("10.0.0.2"))[:-20]   # 마지막 줄 절단(개행 없음)
    ws = _ws(tmp_path, ["10.0.0.1", "10.0.0.2"], raw_output=raw)
    code, report, final = _run(ws)
    assert code == 2
    assert len(report["corrupt_lines"]) == 1 and report["corrupt_lines"][0]["line"] == 2
    assert len(report["truncated_tail"]) == 1 and report["truncated_tail"][0]["line"] == 3
    assert [e["ip"] for e in final] == ["10.0.0.1", "10.0.0.2"] and final[1]["status"] == "failed", "절단된 host 는 보충"


def test_shape_gate_drops_foreign_ip_and_bad_shape(tmp_path):
    bad = _envelope("10.0.0.1"); bad.pop("meta")
    foreign = _envelope("10.9.9.9")
    wrong_channel = _envelope("10.0.0.1", channel="redfish")
    ws = _ws(tmp_path, ["10.0.0.1"], outputs=[bad, foreign, wrong_channel])
    code, report, final = _run(ws)
    assert code == 2 and len(report["dropped"]) == 3 and report["filled"] == 1
    reasons = " ".join(d["reason"] for d in report["dropped"])
    assert "13 envelope keys" in reasons and "not in accepted" in reasons and "target_type" in reasons


def test_duplicate_outputs_last_wins_and_conflict_is_reported(tmp_path):
    a = _envelope("10.0.0.1"); b = _envelope("10.0.0.1", status="partial")
    ws = _ws(tmp_path, ["10.0.0.1"], outputs=[a, b])
    code, report, final = _run(ws)
    assert final[0]["status"] == "partial" and report["conflicts"] == [{"ip": "10.0.0.1", "lines": [1, 2], "chosen": 2}]
    assert code == 2, "충돌은 조용히 넘기지 않는다"
    (tmp_path / "same").mkdir()
    ws2 = _ws(tmp_path / "same", ["10.0.0.1"], outputs=[a, a])
    code2, report2, _ = _run(ws2)
    assert code2 == 0 and report2["conflicts"] == [], "같은 내용의 중복은 충돌이 아니다"


def test_redfish_channel_shape(tmp_path):
    ws = _ws(tmp_path, ["10.1.1.1"], channel="redfish")
    _, _, final = _run(ws, outcome="prep_failed")
    env = final[0]
    assert env["collection_method"] == "redfish_api" and env["sections"]["users"] == "not_supported"
    assert env["sections"]["power"] == "failed" and env["correlation"]["bmc_ip"] == "10.1.1.1"


def test_cli_exit_codes(tmp_path):
    ws = _ws(tmp_path, ["10.0.0.1"], outputs=[_envelope("10.0.0.1")])
    r = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(ws), "--repo-root", str(REPO)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")   # 2026-10-10: Windows cp949 콘솔에서 한글 stderr 디코딩
    assert r.returncode == 0 and "accepted=1 kept=1 filled=0" in r.stderr
    (tmp_path / "nomanifest").mkdir()
    r = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(tmp_path / "nomanifest"), "--repo-root", str(REPO)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 3 and "manifest 없음" in r.stderr
    report = json.loads((tmp_path / "nomanifest" / "gather_finalize_report.json").read_text(encoding="utf-8"))
    assert report["exit_code"] == 3
    # FL-F18 (2026-10-10): 인자 오류는 argparse 기본(2 = 이 도구의 '손상 처리')이 아니라 도구 오류 3 이다
    for argv in (['--workspace', str(ws)], ['--workspace', str(ws), '--repo-root', str(REPO), '--no-such-flag']):
        r = subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert r.returncode == 3 and "인자 오류" in r.stderr and "usage:" in r.stderr, (argv, r.returncode, r.stderr[:200])


def test_synthetic_shape_matches_json_only_table():
    """json_only 의 복제표와 정본 YAML 로 만든 shape 가 같다 (두 경로가 갈리지 않게)."""
    import types
    sys.path.insert(0, str(REPO / "callback_plugins"))
    try:
        import ansible.plugins.callback  # noqa: F401
    except ImportError:                       # ansible 이 없으면 최소 대역 (콜백 계약만 본다)
        _cb = types.ModuleType("ansible.plugins.callback")
        _cb.CallbackBase = type("CallbackBase", (), {"__init__": lambda self, *a, **k: None})
        _plugins = sys.modules.setdefault("ansible.plugins", types.ModuleType("ansible.plugins"))
        _plugins.callback = _cb
        sys.modules.setdefault("ansible", types.ModuleType("ansible")).plugins = _plugins
        sys.modules["ansible.plugins.callback"] = _cb
    import json_only  # noqa: E402
    canon = fz.Canon(REPO)
    for ch in ("os", "esxi", "redfish"):
        mine = canon.shape(ch, "1.2.3.4")
        theirs = json_only._failed_shape(ch, "1.2.3.4")
        assert mine == theirs, ch


def test_infra_outcomes_use_the_execution_base_sentence_not_a_target_failure(tmp_path):
    """9차: 실행 기반(Runner)이 대기 한도 안에 돌아오지 않았거나(infra_wait_expired) 같은 작업 폴더로 이어 갈 수 없을 때(resume_impossible),
    끝나지 않은 대상은 대상 측 실패로 확정하지 않고 실행 기반 문장을 쓴다. failure_code 는 그대로(OUTPUT_BUILD_FAILED)다."""
    for outcome in ("infra_wait_expired", "resume_impossible"):
        ws = _ws(tmp_path / outcome, ["10.0.0.1", "10.0.0.2"], outputs=[_envelope("10.0.0.1")],
                 progress=[{"ts": "t", "host": "10.0.0.2", "ip": "10.0.0.2", "event": "auth_proven", "task": "linux | facts"}]) \
            if (tmp_path / outcome).mkdir() is None else None
        code, report, final = _run(ws, outcome=outcome)
        env = final[1]
        assert code == 0 and report["filled"] == 1
        assert env["diagnosis"]["failure_stage"] == "fallback" and env["diagnosis"]["failure_code"] == "OUTPUT_BUILD_FAILED"
        assert env["diagnosis"]["failure_reason"] == CATALOG["infra_unavailable"]["default"] == env["errors"][0]["message"]
        assert env["errors"][0]["section"] == "gather" and env["diagnosis"]["details"]["outcome"] == outcome
    assert fz.INFRA_OUTCOMES == ("infra_wait_expired", "resume_impossible")


def test_attempt_marker_resets_observations_of_resumed_hosts(tmp_path):
    """9차: 재개 표식(attempt) 뒤에는 그 대상의 지난 시도 관측(인증 · 끊김)을 쓰지 않는다 — 다시 수집한 시도의 관측만 분기를 정한다."""
    prog = [{"ts": "t", "host": "10.0.0.2", "ip": "10.0.0.2", "event": "auth_proven", "task": "linux | facts"},
            {"ts": "t", "host": "10.0.0.2", "ip": "10.0.0.2", "event": "lost", "task": "linux | disks", "detail": "x"},
            {"ts": "t", "host": None, "ip": None, "event": "attempt", "task": None, "detail": "attempt 2", "n": 2, "hosts": ["10.0.0.2"]}]
    ws = _ws(tmp_path, ["10.0.0.1", "10.0.0.2"], outputs=[_envelope("10.0.0.1")], progress=prog)
    code, report, final = _run(ws, outcome="timeout")
    env = final[1]
    assert env["diagnosis"]["failure_code"] == "OUTPUT_BUILD_FAILED", "지난 시도의 인증 · 끊김 관측으로 GATHER_FAILED 를 만들지 않는다"
    assert report["corrupt_lines"] == []



def test_unterminated_last_line_is_judged_on_the_original_bytes(tmp_path):
    """2026-10-10 (C2): 개행 없는 마지막 줄은 치환 전 bytes 로 판정한다 — 잘못된 UTF-8 은 정상 문자열로 둔갑하지 않는다."""
    ok = json.dumps(_envelope("10.0.0.1")).encode("utf-8") + b"\n"
    bad = json.dumps(dict(_envelope("10.0.0.2"), hostname="h-cafX")).encode("utf-8").replace(b"cafX", b"caf\xe9")
    ws = _ws(tmp_path, ["10.0.0.1", "10.0.0.2"])
    (ws / "gather_output.json").write_bytes(ok + bad)
    code, report, final = _run(ws)
    assert code == 2 and len(report["truncated_tail"]) == 1 and report["truncated_tail"][0]["line"] == 2
    assert final[1]["status"] == "failed", "손상 줄의 대상은 보충 결과"

    (tmp_path / "b").mkdir()
    good = json.dumps(dict(_envelope("10.0.0.2"), hostname="h-caf\u00e9"), ensure_ascii=False).encode("utf-8")
    ws2 = _ws(tmp_path / "b", ["10.0.0.1", "10.0.0.2"])
    (ws2 / "gather_output.json").write_bytes(ok + good)
    code2, report2, final2 = _run(ws2)
    assert code2 == 0 and not report2["truncated_tail"] and final2[1]["hostname"] == "h-caf\u00e9"


@pytest.mark.parametrize("data,expected", [
    (b'{"a": 1}', {"a": 1}),
    (b'  {"a": 1}  ', {"a": 1}),
    (b'{"a": NaN}', None),
    (b'[1]', None),
    (b'', None),
    (b'{"a": "\xff"}', None),
    (b'{' * 100000, None),
], ids=['object', 'padded', 'nan', 'array', 'empty', 'invalid_utf8', 'deep_nesting'])
def test_parse_tail_record(data, expected):
    assert fz.parse_tail_record(data) == expected


def test_every_synthetic_branch_and_checkpoint_restore_pass_the_shape_gate():
    """FL-F14 (2026-10-10): Layer A 가 스스로 만든 envelope 이 자기 shape_gate 를 통과해야 한다 — 그렇지 않으면 Layer B(Groovy 동형 검사)와
    결과 회수(C1)가 그 host 를 '결과 없음' 으로 센다. 4 분기(+실행 기반) × 3 채널, 그리고 실제 precheck 진단(corpus 08 의 progress 줄)과
    failure_reason 이 빈 precheck 진단(문장 보충 경로)을 모두 본다. 사용자 문장은 errors[0].message 와 같아야 한다 (CLAUDE.md §10)."""
    canon = fz.Canon(REPO)
    progress = (REPO / "tests/fixtures/finalize_corpus/08_progress_precheck_failed/gather_progress.jsonl").read_text(encoding="utf-8")
    precheck = next(json.loads(l)["diagnosis"] for l in progress.splitlines() if l.strip() and json.loads(l)["event"] == "precheck")
    assert set(precheck) == set(fz.DIAGNOSIS_KEYS) and precheck["failure_stage"] == "reachable"
    blank_reason = dict(precheck, failure_reason="")
    ip = "198.51.100.81"
    cases = [
        ("precheck_preserved", {"diagnosis": precheck}, "completed", None),
        ("precheck_blank_reason_filled", {"diagnosis": blank_reason}, "interrupted_unknown", None),
        ("infra_wait_expired", {}, "infra_wait_expired", "infra_wait"),
        ("resume_impossible", {}, "resume_impossible", None),
        ("auth_proven_stopped", {"auth_proven": True, "location": "ic", "last_task": "linux | facts"}, "gather_limit", "gather_limit"),
        ("auth_proven_lost", {"auth_proven": True, "lost": True, "fail_detail": "connection reset"}, "interrupted_unknown", None),
        ("lost_no_auth", {"lost": True, "location": "cj"}, "completed", None),
        ("lost_empty_vault", {"lost": True, "cred_load_outcome": "empty_accounts", "location": "yi"}, "completed", None),
        ("output_not_run", {"fail_detail": "x", "last_task": "OUTPUT"}, "attempt_limit", None),
    ]
    for ch in ("os", "esxi", "redfish"):
        for name, ctx, outcome, limit in cases:
            env = fz.synthetic_envelope(canon, ch, ip, ctx, outcome, limit_reason=limit)
            assert fz.shape_gate(env, ch, {ip}) is None, (ch, name, fz.shape_gate(env, ch, {ip}))
            d = env["diagnosis"]
            assert isinstance(d["failure_reason"], str) and d["failure_reason"].strip(), (ch, name)
            assert d["failure_stage"] and d["failure_code"], (ch, name)
            assert env["errors"][0]["message"] == d["failure_reason"], (ch, name)
            assert env["status"] == "failed" and d["details"]["outcome"] == outcome
            if limit:
                assert d["details"]["limit_reason"] == limit
        if ch == "os":
            assert fz.synthetic_envelope(canon, ch, ip, {"diagnosis": blank_reason}, "completed")["diagnosis"]["failure_reason"] == \
                CATALOG["output_build_failed"]["default"]
        # CHECKPOINT 복원도 shape 를 깨지 않는다 (추가 수집 중단 · 내보내기 실패 두 사유)
        cp = _envelope(ip, channel=ch)
        for ctx in ({"addon_started": True, "addon_done": False}, {"emitted": False}):
            restored = fz.envelope_from_checkpoint(cp, ctx, "interrupted_unknown")
            assert fz.shape_gate(restored, ch, {ip}) is None, (ch, ctx)
            assert restored["errors"][-1]["message"] in (fz.ADDON_INTERRUPTED, fz.EMIT_FAILED)
