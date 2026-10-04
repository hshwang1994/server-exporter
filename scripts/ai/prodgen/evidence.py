"""E2E evidence for promotion (2026-10-04, Astra 3차 §8-2 · 4차 §2 · 검토 C1).

A verify report proves gates; it does not prove the pipeline ran. Promotion additionally needs structured evidence that the
required main-Job scenarios and Harness scenarios passed **for the same main SHA** — and (C1) that each registered scenario is
backed by a build whose *inputs and observed behaviour* are the ones that scenario defines, not merely a build whose Jenkins
result equals a caller-supplied expectation.

What is checked per entry (collect → item["checks"], all must hold for item["pass"]):
  main Job   : the scenario contract in MAIN_CONTRACT — Job parameters (loc · target_type · inventory hosts · callbackUrl ·
               gatherBudgetForceSec), finalize_summary.json (outcome · accepted==lines · by_origin · filled), callback_body.json
               (one envelope per requested host · status/failure fields per scenario) and console markers (Callback [OK]/실패 ·
               interruption · Resolve Location). The expected Jenkins result comes from the contract — a caller cannot turn S1 into
               a PASS by declaring FAILURE as the expectation.
  Harness    : Job parameters SCENARIO/FUNCTIONS_SRC must equal the registered scenario and source group, harness_result.json
               must name the same scenario with verdict PASS, meta carries the function hash (functions_sha256 / source_sha256);
               generated-tree evidence (FUNCTIONS_SRC=artifact) additionally carries the provenance tree_hash of the tree it ran.
check_evidence(): every required scenario present · pass · same main SHA; main-function Harness evidence and generated-tree
  Harness evidence are two separate groups (one never stands in for the other); the tree group must name the tree_hash under
  promotion; all main-function items share one functions_sha256 and all tree items one source_sha256 (no mixed sources).
aggregate(): every input evidence digest is verified before merging; the report digest is recomputed (mix-up detector, not proof).

Entry syntax (CLI): SCENARIO=<job path>:<build>[:<EXPECTED_RESULT>] — the optional expected result must equal the contract's.
"""
from __future__ import annotations

import datetime
import ipaddress
import json
import os
import re
import shutil
import subprocess

from .common import ProdgenError
from .verify import canonical_digest, report_digest_ok

# ── required scenario sets ────────────────────────────────────────────────────────
REQUIRED_MAIN = ("S1", "S2", "S3", "T2", "T5", "T6", "E2E-A", "E2E-A2")
# main-function Harness (FUNCTIONS_SRC=checkout) — F1~F6 + damaged input + Callback failure + interruption (3차 §4 ①~⑥ 중 Harness 몫)
REQUIRED_HARNESS = ("normal_success", "archive_fail", "stash_fail", "both_fail", "truncate_jsonl", "checkpoint_only_a",
                    "checkpoint_only_b", "layer_a_fail", "raw_fallback", "report_corrupt", "sink_5xx", "outer_timeout",
                    "recover_slow", "foreign_timeout_interruption", "user_abort", "aborted_outcome_finalize",
                    "archive_slow", "layer_a_read_slow")
# generated-tree Harness (FUNCTIONS_SRC=artifact) — the same functions from the prodgen tree. 2026-10-04 최종 지시 §6-1: the preservation
# failure paths (archive_fail · stash_fail · truncate_jsonl · checkpoint_only_a/b · layer_a_fail) are required on the generated tree too.
REQUIRED_HARNESS_TREE = ("normal_success", "archive_fail", "stash_fail", "both_fail", "truncate_jsonl", "checkpoint_only_a",
                         "checkpoint_only_b", "layer_a_fail", "raw_fallback", "report_corrupt")
# Tier 2 (SE_FINALIZER_BOUNDED=true) — required only when bounded mode is enabled for the deployment; PARTIAL without Script Approval
REQUIRED_HARNESS_BOUNDED = ("inner_recover_timeout", "inner_assemble_timeout", "inner_archive_timeout", "inner_stash_timeout",
                            "inner_layer_a_read_timeout")
HARNESS_MARKER = "harness"
# Harness scenarios that end in a Jenkins result other than SUCCESS by design (scenarios.json `jenkins_result`, e.g. user_abort → ABORTED).
# Read from the repository's scenario definition when present so the collector and the CI driver judge the same expectation
# (CI #12 dry-run: user_abort/aborted_outcome_finalize were PASS by verdict but refused here as `jenkins_result` != SUCCESS).
HARNESS_SCENARIOS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tests", "jenkins", "harness", "scenarios.json")
TESTNET = ipaddress.ip_network("192.0.2.0/24")


def harness_expected_results(path: str | None = None) -> dict:
    """scenario → expected Jenkins result from scenarios.json (`jenkins_result`, default SUCCESS). Empty dict when unavailable."""
    p = path or HARNESS_SCENARIOS_FILE
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {name: str(sc.get("jenkins_result") or "SUCCESS").upper() for name, sc in (data.get("scenarios") or {}).items() if isinstance(sc, dict)}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

# ── main Job scenario contract (정본) ─────────────────────────────────────────────
#   expected       : Jenkins result the scenario itself produces (set) — not caller-adjustable
#   hosts          : "real" (no TEST-NET), "testnet" (all TEST-NET), "mixed" (both), None (not constrained)
#   callback       : "portal" (not loopback/TEST-NET — a receiving system), "any" (attempted), None
#   outcome        : allowed finalize outcomes
#   envelopes      : "all_success" (every host success/partial, no failure fields), "all_failed", "mixed", None
#   delivered      : True → console "[Callback] [OK] HTTP 2xx"; False → "Callback 전송 실패" and callback_body.json archived
#   filled         : exact synthetic count (0) or None; filled_min / preserved_min for S3
#   force_sec      : gatherBudgetForceSec must be set (≥ 120, MIN_START_SEC)
#   loc            : required loc value; console: markers that must appear
MAIN_CONTRACT = {
    "S1": {"desc": "정상 수집 — 실호스트 성공 envelope · Callback 2xx", "expected": {"SUCCESS"}, "hosts": "real", "callback": "portal",
           "outcome": {"completed"}, "envelopes": "all_success", "delivered": True, "filled": 0},
    "S2": {"desc": "혼합 배치 — 성공 host 보존 + 실패 host 진단 3종", "expected": {"SUCCESS"}, "hosts": "mixed", "callback": "portal",
           "outcome": {"completed"}, "envelopes": "mixed", "delivered": True, "filled": 0},
    "S3": {"desc": "큰 배치 timeout — 완료 host 데이터 보존, 미완료만 보충", "expected": {"UNSTABLE"}, "hosts": "real", "callback": "portal",
           "outcome": {"timeout", "timeout_killed"}, "delivered": True, "force_sec": True, "preserved_min": 1, "filled_min": 1},
    "S4": {"desc": "Windows 단독 수집", "expected": {"SUCCESS"}, "hosts": "real", "callback": "portal", "outcome": {"completed"},
           "envelopes": "all_success", "delivered": True, "filled": 0, "os_family": "Windows"},
    "S5": {"desc": "Kernel 6.x 대상 Linux 수집(원본 대조는 별도)", "expected": {"SUCCESS"}, "hosts": "real", "callback": "portal",
           "outcome": {"completed"}, "envelopes": "all_success", "delivered": True, "filled": 0, "kernel_major_min": 6},
    "T2": {"desc": "빠른 실패 — 전 host 실패 envelope · Callback 2xx · UNSTABLE 아님", "expected": {"SUCCESS"}, "hosts": "testnet",
           "callback": "any", "outcome": {"completed"}, "envelopes": "all_failed", "delivered": True, "filled": 0},
    "T5": {"desc": "사용자 중단 — outcome aborted 기록 · 재전파 · ABORTED 유지 · body 보존", "expected": {"ABORTED"}, "hosts": None,
           "callback": None, "outcome": {"aborted"}, "console": ["[Gather] interrupted"], "body_required": True},
    "T6": {"desc": "Callback 실패 — delivered=false · callback_body.json 보존 · UNSTABLE", "expected": {"UNSTABLE"}, "hosts": None,
           "callback": "any", "outcome": {"completed"}, "delivered": False, "body_required": True},
    "E2E-A": {"desc": "cj routing smoke — loc=cj resolve · TEST-NET 실패 envelope", "expected": {"SUCCESS", "UNSTABLE"}, "hosts": "testnet",
              "callback": "any", "loc": "cj", "outcome": {"completed"}, "envelopes": "all_failed",
              "console": ["[Resolve Location] cj + "]},
    "E2E-A2": {"desc": "폐기 Location chj 거부 — Resolve Location fail-closed", "expected": {"FAILURE"}, "hosts": None, "callback": None,
               "loc": "chj", "console": ["[Resolve Location] 등록되지 않은 Location: 'chj'"], "fail_closed": True},
    "E2E-D": {"desc": "ESXi 성공 경로", "expected": {"SUCCESS"}, "hosts": "real", "callback": "portal", "outcome": {"completed"},
              "envelopes": "all_success", "delivered": True, "filled": 0, "target_type": "esxi"},
    "E2E-E": {"desc": "Redfish dry-run — 표준 계정 인증 · Account Write 0", "expected": {"SUCCESS"}, "hosts": "real", "callback": "portal",
              "outcome": {"completed"}, "envelopes": "all_success", "delivered": True, "filled": 0, "target_type": "redfish",
              "dryrun": True},
}
ENVELOPE_KEYS = {"schema_version", "target_type", "collection_method", "ip", "hostname", "vendor", "status", "sections",
                 "diagnosis", "meta", "correlation", "errors", "data"}


# ── Jenkins reads ────────────────────────────────────────────────────────────────
def _curl(url: str, netrc: str, *, text: bool = False):
    curl = shutil.which("curl")
    if not curl:
        raise ProdgenError("curl not available for the Jenkins read")
    # -g (--globoff): the Jenkins tree= query carries [] which curl would otherwise expand as a glob (CI #5: rc=3 "URL malformed")
    proc = subprocess.run([curl, "-skg", "--netrc-file", netrc, "--max-time", "120", "-w", "\n%{http_code}", url],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise ProdgenError(f"Jenkins read failed: {url} rc={proc.returncode}")
    body, _, code = proc.stdout.rpartition("\n")
    if code.strip() != "200":
        raise ProdgenError(f"Jenkins read HTTP {code.strip() or '?'}: {url}")
    if text:
        return body
    try:
        return json.loads(body)
    except ValueError as exc:
        raise ProdgenError(f"Jenkins read is not JSON: {url}: {exc}") from exc


def _curl_json(url: str, netrc: str) -> dict:
    return _curl(url, netrc)


def _try(fn, *a):
    try:
        return fn(*a), None
    except ProdgenError as exc:
        return None, str(exc)


def parse_entry(entry: str) -> dict:
    if "=" not in entry or ":" not in entry.split("=", 1)[1]:
        raise ProdgenError(f"bad evidence entry {entry!r} — expected SCENARIO=job/path:build[:EXPECTED]")
    scenario, rest = entry.split("=", 1)
    parts = rest.split(":")
    job, build = parts[0], parts[1]
    caller_expected = parts[2].strip().upper() if len(parts) > 2 else None
    kind = "harness" if HARNESS_MARKER in job else "main"
    if kind == "main":
        contract = MAIN_CONTRACT.get(scenario.strip())
        default = sorted(contract["expected"])[0] if contract else "SUCCESS"
    else:
        default = "PASS"
    return {"scenario": scenario.strip(), "job": job.strip(), "build": int(build), "expected": caller_expected or default,
            "caller_expected": caller_expected, "kind": kind}


# ── helpers over artifacts ───────────────────────────────────────────────────────
def _hosts_from_inventory(inv_json: str) -> list:
    try:
        arr = json.loads(inv_json or "[]")
    except ValueError:
        return []
    out = []
    for e in arr if isinstance(arr, list) else []:
        if isinstance(e, dict):
            v = e.get("service_ip") or e.get("bmc_ip") or e.get("ip")
            if v:
                out.append(str(v).strip())
    return out


def _is_testnet(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in TESTNET
    except ValueError:
        return False


def _callback_host(url: str) -> str:
    u = (url or "").strip()
    u = u.split("://", 1)[1] if "://" in u else u
    return u.split("/", 1)[0].split(":", 1)[0].strip("[]")


def _envelopes(body) -> list:
    if not isinstance(body, dict):
        return []
    arr = body.get("gatherInfoJson")
    return [e for e in arr if isinstance(e, dict)] if isinstance(arr, list) else []


def _env_failed(e: dict) -> bool:
    d = e.get("diagnosis") if isinstance(e.get("diagnosis"), dict) else {}
    return e.get("status") == "failed" or bool(d.get("failure_stage"))


def _env_failure_complete(e: dict) -> bool:
    d = e.get("diagnosis") if isinstance(e.get("diagnosis"), dict) else {}
    return all(d.get(k) for k in ("failure_stage", "failure_code", "failure_reason"))


def _kernel_major(e: dict):
    sysd = ((e.get("data") or {}).get("system") or {}) if isinstance(e.get("data"), dict) else {}
    k = str(sysd.get("kernel") or "")
    try:
        return int(k.split(".")[0])
    except ValueError:
        return None


def evaluate_main(scenario: str, item: dict, summary, body, manifest, console: str) -> list:
    """Scenario-contract checks for a main Job build. Returns [{name, ok, observed}]. Unknown scenario → one failing check."""
    c = MAIN_CONTRACT.get(scenario)
    checks = []

    def add(name, ok, observed=None):
        checks.append({"name": name, "ok": bool(ok), "observed": observed})

    if c is None:
        add("contract", False, f"unknown main scenario {scenario!r} — not in MAIN_CONTRACT")
        return checks
    params = item.get("params") or {}
    result = item.get("result")
    add("jenkins_result", result in c["expected"] and not item.get("building"), f"{result} (expected {sorted(c['expected'])})")
    if item.get("caller_expected") and item["caller_expected"] not in c["expected"]:
        add("caller_expected", False, f"caller expected {item['caller_expected']} but the contract says {sorted(c['expected'])} — override refused")
    hosts = _hosts_from_inventory(params.get("inventory_json", ""))
    add("hosts_given", bool(hosts), hosts)
    tn = [h for h in hosts if _is_testnet(h)]
    if c.get("hosts") == "real":
        add("hosts_real", hosts and not tn, f"testnet={tn}")
    elif c.get("hosts") == "testnet":
        add("hosts_testnet", hosts and len(tn) == len(hosts), f"testnet={len(tn)}/{len(hosts)}")
    elif c.get("hosts") == "mixed":
        add("hosts_mixed", hosts and tn and len(tn) < len(hosts), f"testnet={len(tn)}/{len(hosts)}")
    if c.get("loc"):
        add("loc", (params.get("loc") or "").strip() == c["loc"], params.get("loc"))
    if c.get("target_type"):
        add("target_type", params.get("target_type") == c["target_type"], params.get("target_type"))
    if c.get("dryrun"):
        add("redfish_dryrun", str(params.get("redfishAccountDryrun")).lower() == "true", params.get("redfishAccountDryrun"))
    cb_host = _callback_host(params.get("callbackUrl", ""))
    if c.get("callback") == "portal":
        add("callback_receiver", cb_host and cb_host not in LOOPBACK_HOSTS and not _is_testnet(cb_host), cb_host)
    elif c.get("callback") == "any":
        add("callback_url", bool(cb_host), cb_host)
    if c.get("force_sec"):
        raw = str(params.get("gatherBudgetForceSec") or "").strip()
        add("force_sec", raw.isdigit() and int(raw) >= 120, raw)
    # ── finalize summary
    if c.get("outcome") is not None or c.get("filled") is not None or c.get("preserved_min") or c.get("filled_min"):
        if not isinstance(summary, dict):
            add("finalize_summary", False, "finalize_summary.json missing/unreadable")
        else:
            if c.get("outcome"):
                add("outcome", summary.get("outcome") in c["outcome"], summary.get("outcome"))
            add("accepted_eq_lines", summary.get("accepted") == summary.get("lines") and summary.get("accepted"), f"{summary.get('accepted')}/{summary.get('lines')}")
            add("accepted_eq_hosts", not hosts or summary.get("accepted") == len(hosts), f"accepted={summary.get('accepted')} hosts={len(hosts)}")
            if c.get("filled") is not None:
                add("filled", summary.get("filled") == c["filled"], summary.get("filled"))
            if c.get("filled_min"):
                add("filled_min", (summary.get("filled") or 0) >= c["filled_min"], summary.get("filled"))
            if c.get("preserved_min"):
                bo = summary.get("by_origin") or {}
                real = (bo.get("output") or 0) + (bo.get("checkpoint") or 0)
                add("preserved_min", real >= c["preserved_min"], bo)
    # ── callback body
    envs = _envelopes(body)
    if c.get("envelopes") or c.get("body_required") or c.get("os_family") or c.get("kernel_major_min"):
        if body is None:
            add("callback_body", False, "callback_body.json missing/unreadable")
        else:
            add("body_one_per_host", not hosts or sorted(e.get("ip") for e in envs) == sorted(hosts), f"body={len(envs)} hosts={len(hosts)}")
            add("body_13_keys", envs and all(set(e) == ENVELOPE_KEYS for e in envs), len(envs))
            if c.get("envelopes") == "all_success":
                add("all_success", envs and all(e.get("status") in ("success", "partial") and not _env_failed(e) for e in envs),
                    [e.get("status") for e in envs])
                add("real_data", envs and all(isinstance(e.get("data"), dict) and e["data"] for e in envs), None)
            elif c.get("envelopes") == "all_failed":
                add("all_failed", envs and all(_env_failed(e) and _env_failure_complete(e) for e in envs), [e.get("status") for e in envs])
            elif c.get("envelopes") == "mixed":
                ok_hosts = [e for e in envs if not _env_failed(e)]
                bad = [e for e in envs if _env_failed(e)]
                add("mixed_success_present", bool(ok_hosts) and all(isinstance(e.get("data"), dict) and e["data"] for e in ok_hosts), len(ok_hosts))
                add("mixed_failed_complete", bool(bad) and all(_env_failure_complete(e) for e in bad), len(bad))
            if c.get("os_family"):
                fams = [((e.get("data") or {}).get("system") or {}).get("os_family") for e in envs]
                add("os_family", envs and all(f == c["os_family"] for f in fams), fams)
            if c.get("kernel_major_min"):
                majors = [_kernel_major(e) for e in envs]
                add("kernel_major", envs and all(m is not None and m >= c["kernel_major_min"] for m in majors), majors)
    # ── console markers
    con = console or ""
    if c.get("fail_closed"):
        add("jenkinsfile_obtained", "Obtained Jenkinsfile_portal from" in con, "lightweight checkout marker" if "Obtained Jenkinsfile_portal from" in con else "marker missing")
        gather_block = con.split("{ (Gather)")[1].split("{ (Declarative: Post Actions)")[0] if "{ (Gather)" in con else ""
        no_gather = ("[Budget] exec" not in con) and ("Running on " not in gather_block)
        add("stopped_before_agent", no_gather, "Gather stage never ran on an agent" if no_gather else "the Gather stage ran on an agent — not the fail-closed path")
    if c.get("delivered") is True:
        add("callback_delivered", "[Callback] [OK] HTTP 2" in con, "[Callback] [OK] HTTP 2xx" if "[Callback] [OK] HTTP 2" in con else "no 2xx marker")
    elif c.get("delivered") is False:
        add("callback_failed", ("Callback 전송 실패" in con) and "[Callback] [OK] HTTP 2" not in con, "실패 marker" if "Callback 전송 실패" in con else "no failure marker")
    for marker in c.get("console", []):
        add(f"console:{marker}", marker in con, None)
    if not con:
        add("console_available", False, "consoleText unavailable — markers cannot be verified")
    return checks


def evaluate_harness(scenario: str, item: dict, hr, control, expected_result: str) -> list:
    """Harness build: parameters, artifact scenario, verdict, hash and source-group consistency."""
    checks = []

    def add(name, ok, observed=None):
        checks.append({"name": name, "ok": bool(ok), "observed": observed})

    params = item.get("params") or {}
    add("param_scenario", params.get("SCENARIO") == scenario, params.get("SCENARIO"))
    add("param_functions_src", params.get("FUNCTIONS_SRC") in ("checkout", "artifact"), params.get("FUNCTIONS_SRC"))
    add("jenkins_result", item.get("result") == expected_result and not item.get("building"), f"{item.get('result')} (expected {expected_result})")
    if not isinstance(hr, dict):
        add("harness_result", False, "harness_result.json missing/unreadable")
        return checks
    add("artifact_scenario", hr.get("scenario") == scenario, hr.get("scenario"))
    add("verdict", hr.get("verdict") == "PASS", hr.get("verdict"))
    meta = hr.get("meta") or {}
    add("functions_sha256", bool(meta.get("functions_sha256")), meta.get("functions_sha256"))
    add("source_sha256", bool(meta.get("source_sha256") or (control or {}).get("source_sha256")), None)
    if isinstance(control, dict):
        add("control_source", control.get("functions_source") == params.get("FUNCTIONS_SRC"), control.get("functions_source"))
        if params.get("FUNCTIONS_SRC") == "artifact":
            prov = control.get("provenance") or {}
            add("provenance_tree_hash", bool(prov.get("tree_hash")), prov.get("tree_hash"))
    else:
        add("harness_control", False, "harness_control.json missing/unreadable")
    return checks


TRUSTED_RE = re.compile(r"^\[Trusted\] (\S+) len=(\d+) jhash=(-?\d+)\s*$", re.M)


def java_string_hash(text: str) -> int:
    """java.lang.String.hashCode() of `text` (over UTF-16 code units) — the value `Jenkinsfile_portal` seTrusted() echoes as jhash.
    The sandbox whitelists no digest API (MessageDigest · CRC32), so a 32-bit identification hash is what the runtime can emit."""
    h = 0
    for ch in text:
        o = ord(ch)
        if o > 0xFFFF:
            o -= 0x10000
            for unit in (0xD800 + (o >> 10), 0xDC00 + (o & 0x3FF)):
                h = (31 * h + unit) & 0xFFFFFFFF
            continue
        h = (31 * h + o) & 0xFFFFFFFF
    return h - 0x100000000 if h >= 0x80000000 else h


def _git_show_bytes(repo_root: str, sha: str | None, path: str):
    git = shutil.which("git")
    if not git or not sha:
        return None
    proc = subprocess.run([git, "-C", repo_root, "show", f"{sha}:{path}"], capture_output=True)
    return proc.stdout if proc.returncode == 0 else None


def trusted_report(console: str, sha: str | None, repo_root: str):
    """(trusted items, checks). Every `[Trusted] <path> len=N jhash=H` console line — emitted by seTrusted() for the content the build
    actually received from readTrusted — is compared with `git show <sha>:<path>` of the bound revision, decoded as UTF-8 and as
    ISO-8859-1 (the controller's default charset is not known in advance; the matching decoding is recorded). A revision whose
    Jenkinsfile_portal emits the marker but a console without any line is a failed check; an older revision that does not emit it
    adds no check. This identifies *which content* the build used (mixed-revision detection, Plan §0 ②) — it is not an integrity proof."""
    items, checks = [], []
    found = TRUSTED_RE.findall(console or "")
    jf = _git_show_bytes(repo_root, sha, "Jenkinsfile_portal") if sha else None
    emits = jf is not None and b"[Trusted]" in jf
    if not found:
        if emits:
            checks.append({"name": "trusted_lines", "ok": False,
                           "observed": "Jenkinsfile_portal at this revision emits [Trusted] lines but the console has none"})
        return items, checks
    for path, ln, jh in found:
        rec = {"path": path, "len": int(ln), "jhash": int(jh), "match": None}
        blob = _git_show_bytes(repo_root, sha, path) if sha else None
        if blob is None:
            rec["match"] = "unavailable"
            checks.append({"name": f"trusted:{path}", "ok": False,
                           "observed": f"len={ln} jhash={jh} — `git show {str(sha)[:12]}:{path}` unavailable, cannot compare"})
        else:
            match = [enc for enc, txt in (("utf-8", blob.decode("utf-8", "replace")), ("iso-8859-1", blob.decode("latin-1")))
                     if len(txt) == int(ln) and java_string_hash(txt) == int(jh)]
            rec["match"] = match[0] if match else "mismatch"
            checks.append({"name": f"trusted:{path}", "ok": bool(match),
                           "observed": f"len={ln} jhash={jh} match={match[0] if match else 'none'} (revision {str(sha)[:12]})"})
        items.append(rec)
    return items, checks


def load_tip_observations(path: str | None) -> list:
    """Trigger-side observations: [{job, build, sha_before, sha_after, before_epoch, after_epoch, remote, method}]."""
    if not path:
        return []
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    obs = data.get("observations") if isinstance(data, dict) else data
    if not isinstance(obs, list):
        raise ProdgenError(f"tip observations {path}: expected a list (or {{\"observations\": [...]}})")
    return obs


def _tip_observation_for(observations, job: str, build) -> dict | None:
    for o in observations or []:
        if isinstance(o, dict) and str(o.get("job")) == job and str(o.get("build")) == str(build):
            return o
    return None


def tip_frozen_revision(obs: dict | None, build_timestamp_ms, build_duration_ms):
    """Direct revision binding for a fail-closed build from a trigger-side observation (2026-10-04 최종 지시 §5): the Job's SCM tip
    (`git ls-remote <remote> refs/heads/main`) read before the build was queued and again after it finished. Both readings must be
    the same SHA and the build's [start, end] must lie inside [before, after] — lightweight checkout and readTrusted read that tip.
    Returns (sha, "tip_frozen:ls-remote", note) or (None, None, why)."""
    if not obs:
        return None, None, None
    try:
        sha_b = str(obs.get("sha_before") or obs.get("sha") or "")
        sha_a = str(obs.get("sha_after") or obs.get("sha") or "")
        before, after = float(obs["before_epoch"]), float(obs["after_epoch"])
    except (KeyError, TypeError, ValueError):
        return None, None, "observation incomplete (sha_before/sha_after/before_epoch/after_epoch)"
    if not sha_b or sha_b != sha_a:
        return None, None, f"tip moved during the window ({sha_b[:12]} → {sha_a[:12]})"
    if build_timestamp_ms is None or build_duration_ms is None:
        return None, None, "build timestamp/duration unavailable"
    t0 = float(build_timestamp_ms) / 1000.0
    t1 = t0 + float(build_duration_ms) / 1000.0
    if not (before - 1 <= t0 and t1 <= after + 1):
        return None, None, f"build window [{int(t0)},{int(t1)}] not inside the observation window [{int(before)},{int(after)}]"
    return sha_b, "tip_frozen:ls-remote", f"before={int(before)} after={int(after)} remote={obs.get('remote', '?')}"


def neighbour_revision(builds: list, number: int):
    """Revision binding for a build that stopped before any agent checkout (contract `fail_closed: True` — E2E-A2:
    Resolve Location refuses `chj` on the controller, so Jenkins records no BuildData for it; CI #14 2026-10-04).
    The same Job's nearest earlier AND later builds that do carry a revision pin the Job's SCM tip at that time:
    when both agree, that revision is the one the fail-closed build ran from. Any disagreement or a missing side → None.
    `builds` = [{"number": int, "sha": str | None}, …]. Returns (sha, source) with source "neighbours:#lo,#hi".
    2026-10-04 최종 지시 §5: this is an **estimate** (recorded as binding "estimated") — agreement of the neighbours is not the build's own
    SCM record. check_evidence() does not accept an estimate as the binding of a required scenario; the direct forms are Jenkins
    BuildData or a tip-frozen observation (tip_frozen_revision)."""
    lo = max((b for b in builds if b.get("sha") and b["number"] < number), key=lambda b: b["number"], default=None)
    hi = min((b for b in builds if b.get("sha") and b["number"] > number), key=lambda b: b["number"], default=None)
    if lo and hi and lo["sha"] == hi["sha"]:
        return lo["sha"], f"neighbours:#{lo['number']},#{hi['number']}"
    return None, None


def _job_builds(base: str, job_path: str, netrc: str) -> list:
    """[{"number", "sha"}] for the Job's recent builds (one read-only call)."""
    info = _curl_json(f"{base}/{job_path}/api/json?tree=builds[number,actions[lastBuiltRevision[SHA1]]]{{0,60}}", netrc)
    out = []
    for b in info.get("builds", []) or []:
        sha = None
        for a in b.get("actions", []) or []:
            if a.get("lastBuiltRevision"):
                sha = a["lastBuiltRevision"].get("SHA1")
        out.append({"number": b.get("number"), "sha": sha})
    return out


def collect(jenkins_url: str, netrc: str, entries: list, harness_results: dict | None = None,
            tip_observations: list | None = None, repo_root: str | None = None) -> dict:
    """Read-only Jenkins collection. `harness_results` (scenario → expected Jenkins result) overrides scenarios.json / SUCCESS.
    `tip_observations` (load_tip_observations) give fail-closed builds a direct binding; `repo_root` is where `git show <sha>:<path>`
    resolves the [Trusted] content comparison (default: cwd)."""
    base = jenkins_url.rstrip("/")
    repo_root = repo_root or os.getcwd()
    expected_results = dict(harness_expected_results())
    expected_results.update(harness_results or {})
    items = []
    job_builds_cache: dict = {}
    for raw in entries:
        e = parse_entry(raw) if isinstance(raw, str) else raw
        job_path = "/".join(f"job/{p}" for p in e["job"].split("/"))
        url = f"{base}/{job_path}/{e['build']}"
        info = _curl_json(f"{url}/api/json?tree=number,result,building,url,timestamp,duration,actions[lastBuiltRevision[SHA1],parameters[name,value]]", netrc)
        sha, params = None, {}
        for a in info.get("actions", []) or []:
            if a.get("lastBuiltRevision"):
                sha = a["lastBuiltRevision"].get("SHA1")
            for p in a.get("parameters", []) or []:
                params[p.get("name")] = p.get("value")
        kind = e.get("kind") or ("harness" if HARNESS_MARKER in e["job"] else "main")
        sha_source = "build_data" if sha else None
        binding = "direct" if sha else None
        tip_note = None
        if kind == "main" and not sha and (MAIN_CONTRACT.get(e["scenario"]) or {}).get("fail_closed"):
            # fail-closed scenario: no agent checkout ever happened. Direct evidence first — a tip-frozen observation made by the trigger
            # (same SCM tip before and after the build window) — and only then the neighbouring-build estimate, recorded as an estimate.
            obs = _tip_observation_for(tip_observations, e["job"], e["build"])
            sha, sha_source, tip_note = tip_frozen_revision(obs, info.get("timestamp"), info.get("duration"))
            if sha:
                binding = "direct"
            else:
                builds = job_builds_cache.get(job_path)
                if builds is None:
                    builds, _ = _try(_job_builds, base, job_path, netrc)
                    job_builds_cache[job_path] = builds if isinstance(builds, list) else []
                sha, sha_source = neighbour_revision(job_builds_cache[job_path], int(e["build"]))
                binding = "estimated" if sha else None
        item = {"scenario": e["scenario"], "kind": kind, "job": e["job"], "build": e["build"], "url": info.get("url") or url,
                "result": info.get("result"), "building": info.get("building"), "checkout_sha": sha, "checkout_sha_source": sha_source,
                "binding": binding, "tip_observation": tip_note, "timestamp": info.get("timestamp"), "duration": info.get("duration"),
                "expected": e.get("expected"), "caller_expected": e.get("caller_expected"),
                "params": {k: params[k] for k in ("loc", "target_type", "inventory_json", "callbackUrl", "gatherBudgetForceSec",
                                                   "redfishAccountDryrun", "SCENARIO", "MAIN_SHA", "FUNCTIONS_SRC", "BOUNDED") if k in params}}
        if kind == "harness":
            hr, err = _try(_curl_json, f"{url}/artifact/harness_result.json", netrc)
            control, _ = _try(_curl_json, f"{url}/artifact/harness_control.json", netrc)
            item["harness_verdict"] = hr.get("verdict") if isinstance(hr, dict) else None
            item["harness_problems"] = (hr.get("problems", [])[:5] if isinstance(hr, dict) else [err])
            item["harness_partial"] = (hr.get("partial", [])[:5] if isinstance(hr, dict) else [])
            item["functions_sha256"] = ((hr.get("meta") or {}).get("functions_sha256") if isinstance(hr, dict) else None)
            item["functions_src"] = params.get("FUNCTIONS_SRC")
            if isinstance(control, dict):
                item["source_sha256"] = control.get("source_sha256")
                item["provenance_tree_hash"] = (control.get("provenance") or {}).get("tree_hash")
                item["bounded"] = control.get("bounded")
            expected_result = expected_results.get(e["scenario"], "SUCCESS")
            item["checks"] = evaluate_harness(e["scenario"], item, hr, control, expected_result)
        else:
            summary, _ = _try(_curl_json, f"{url}/artifact/finalize_summary.json", netrc)
            body, _ = _try(_curl_json, f"{url}/artifact/callback_body.json", netrc)
            manifest, _ = _try(_curl_json, f"{url}/artifact/gather_manifest.json", netrc)
            console, _ = _try(lambda u, n: _curl(u, n, text=True), f"{url}/consoleText", netrc)
            item["summary"] = {k: summary.get(k) for k in ("accepted", "lines", "kept", "filled", "outcome", "layerA", "layerB", "source", "by_origin", "unrecovered", "damage")} if isinstance(summary, dict) else None
            envs = _envelopes(body)
            item["envelopes"] = [{"ip": x.get("ip"), "status": x.get("status"),
                                  "failure_code": ((x.get("diagnosis") or {}).get("failure_code") if isinstance(x.get("diagnosis"), dict) else None),
                                  "kernel": (((x.get("data") or {}).get("system") or {}).get("kernel") if isinstance(x.get("data"), dict) else None)}
                                 for x in envs]
            item["checks"] = evaluate_main(e["scenario"], item, summary, body, manifest, console or "")
            # §5: which helper/registry *content* this build read (seTrusted lines) vs the bound revision; fallback paths are recorded
            item["trusted"], trusted_checks = trusted_report(console or "", sha, repo_root)
            item["checks"].extend(trusted_checks)
            item["canon_fallback"] = "정본 읽기 실패 — 복제값 사용" in (console or "")
            item["layer_b_lib_unavailable"] = "se_finalize.groovy 적재 실패" in (console or "")
        item["pass"] = bool(item["checks"]) and all(ch["ok"] for ch in item["checks"]) and bool(sha)
        items.append(item)
    payload = {"collected_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
               "jenkins_url": base, "items": items}
    payload["evidence_sha256"] = canonical_digest(payload)
    return payload


def check_evidence(evidence: dict, main_sha: str, required_main=REQUIRED_MAIN, required_harness=REQUIRED_HARNESS,
                   required_harness_tree=REQUIRED_HARNESS_TREE, tree_hash: str | None = None, require_bounded: bool = False) -> list:
    """Problems list (empty = ok): every required scenario present, passed, recorded against `main_sha`, in its own source group."""
    problems = []
    if not isinstance(evidence, dict) or not isinstance(evidence.get("items"), list):
        return ["evidence has no items"]
    body = {k: v for k, v in evidence.items() if k != "evidence_sha256"}
    if evidence.get("evidence_sha256") and canonical_digest(body) != evidence["evidence_sha256"]:
        problems.append("evidence_sha256 does not match the evidence body")
    by = {}
    for it in evidence["items"]:
        by.setdefault(it.get("scenario"), []).append(it)

    def _why(items):
        return "; ".join(f"build {it.get('build')} result={it.get('result')} harness={it.get('harness_verdict')} src={it.get('functions_src')} "
                         f"sha={str(it.get('checkout_sha'))[:12]} failed={[c['name'] for c in (it.get('checks') or []) if not c.get('ok')][:4]}"
                         for it in items)[:300]

    for sc in required_main:
        items = [it for it in by.get(sc, []) if it.get("kind", "main") == "main"]
        if not items:
            problems.append(f"{sc}: no main-Job evidence")
            continue
        good = [it for it in items if it.get("pass") and it.get("checkout_sha") == main_sha and it.get("binding") != "estimated"]
        if not good:
            est = [it for it in items if it.get("pass") and it.get("checkout_sha") == main_sha and it.get("binding") == "estimated"]
            if est:
                problems.append(f"{sc}: revision binding is an estimate ({est[0].get('checkout_sha_source')}) — direct evidence required "
                                f"(Jenkins BuildData or a tip-frozen observation); an estimate is recorded, not promoted")
            else:
                problems.append(f"{sc}: no passing main-Job evidence for main {main_sha[:12]} ({_why(items)})")
    groups = [("main-function Harness", required_harness, "checkout"), ("generated-tree Harness", required_harness_tree, "artifact")]
    if require_bounded:
        groups.append(("bounded Harness", REQUIRED_HARNESS_BOUNDED, "checkout"))
    for label, req, src in groups:
        for sc in req:
            items = [it for it in by.get(sc, []) if it.get("kind") == "harness" and it.get("functions_src") == src]
            if not items:
                problems.append(f"{sc} ({label}, FUNCTIONS_SRC={src}): no evidence")
                continue
            good = [it for it in items if it.get("pass") and it.get("checkout_sha") == main_sha]
            if src == "artifact" and tree_hash:
                good = [it for it in good if it.get("provenance_tree_hash") == tree_hash]
            if not good:
                problems.append(f"{sc} ({label}): no passing evidence for main {main_sha[:12]}" + (f" / tree {tree_hash[:12]}" if src == "artifact" and tree_hash else "") + f" ({_why(items)})")
    # one source per group — a mixed set of function hashes means the items did not run the same functions
    hashes = {it.get("functions_sha256") for it in evidence["items"] if it.get("kind") == "harness" and it.get("functions_src") == "checkout" and it.get("pass") and it.get("checkout_sha") == main_sha}
    if len(hashes - {None}) > 1:
        problems.append(f"main-function Harness items carry {len(hashes - {None})} different functions_sha256 — mixed sources")
    srcs = {it.get("source_sha256") for it in evidence["items"] if it.get("kind") == "harness" and it.get("functions_src") == "artifact" and it.get("pass") and it.get("checkout_sha") == main_sha}
    if len(srcs - {None}) > 1:
        problems.append(f"generated-tree Harness items carry {len(srcs - {None})} different source_sha256 — mixed trees")
    return problems


def aggregate(report_path: str, evidence_paths: list, out_path: str) -> dict:
    """Merge evidence files into a verify report's e2e_evidence and recompute the report digest. Every input digest is verified first."""
    with open(report_path, encoding="utf-8") as fh:
        report = json.load(fh)
    if not report_digest_ok(report):
        raise ProdgenError("verify report digest mismatch — refusing to aggregate onto a tampered/hand-edited report")
    merged = {"items": [], "sources": []}
    for p in evidence_paths:
        with open(p, encoding="utf-8") as fh:
            ev = json.load(fh)
        if not isinstance(ev, dict) or not isinstance(ev.get("items"), list):
            raise ProdgenError(f"evidence {p}: no items")
        if not ev.get("evidence_sha256") or canonical_digest({k: v for k, v in ev.items() if k != "evidence_sha256"}) != ev["evidence_sha256"]:
            raise ProdgenError(f"evidence {p}: evidence_sha256 missing or does not match its body — refusing to aggregate")
        merged["items"].extend(ev["items"])
        merged["sources"].append({"path": os.path.abspath(p), "evidence_sha256": ev["evidence_sha256"], "collected_at": ev.get("collected_at"),
                                  "jenkins_url": ev.get("jenkins_url")})
    merged["evidence_sha256"] = canonical_digest({k: v for k, v in merged.items() if k != "evidence_sha256"})
    report["e2e_evidence"] = merged
    report.pop("report_sha256", None)
    report["report_sha256"] = canonical_digest(report)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1, sort_keys=True)
    return {"items": len(merged["items"]), "report_sha256": report["report_sha256"], "out": out_path}
