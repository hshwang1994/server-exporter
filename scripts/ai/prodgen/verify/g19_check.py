#!/usr/bin/env python3
"""G19 checker — runs *inside the Linux environment* against a customer-main-form clone of the generated tree (2026-10-04).

Invoked by gates_promotion.g19_customer_main_form via WSL/bash with:
  --work <dir> --clone <dir> --bare <dir> --vault-password-file <path outside the clone> --expected-failure-code TARGET_UNREACHABLE
Prints one JSON object (last line) and exits 0 (PASS / PARTIAL) or 1 (FAIL). stdlib only.

Checks
  1. refs: bare repo has refs/heads/main only; clone has no `production` ref (local or remote-tracking).
  2. no dev files in the clone: tests/, scripts/ai/, .claude/, docs/, Jenkinsfile_ci, requirements-test.txt.
  3. environment scrub: PYTHONPATH and every ANSIBLE_* variable removed; ANSIBLE_CONFIG = <clone>/ansible.cfg; REPO_ROOT = <clone>.
     Project paths in `ansible-config dump --only-changed` (plugin/module/inventory keys) must resolve under the clone; allowed
     external dependencies (ansible venv, collections path, python3, OS tools) are recorded with their resolved paths.
  4. per channel: ansible-playbook <clone>/<ch>-gather/site.yml with 2 TEST-NET hosts, dry-run forced for redfish, time-boxed.
     Output: exactly one envelope per host, 13 keys, target_type == channel, ip ∈ hosts, failure_stage/code/reason all present,
     rc 0 with 0 envelopes = silent failure. The observed failure condition is recorded; mismatch with --expected-failure-code is
     reported as condition_mismatch (PARTIAL at the gate level).
  5. plaintext secret scan: the vault password text must not appear in any output/stdout/stderr (hit count only, never the value).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

KEYS13 = {"schema_version", "target_type", "collection_method", "ip", "hostname", "vendor", "status",
          "sections", "diagnosis", "meta", "correlation", "errors", "data"}
HOSTS = ["192.0.2.10", "192.0.2.11"]
DEV_PATHS = ["tests", "scripts/ai", ".claude", "docs", "Jenkinsfile_ci", "requirements-test.txt", "pytest.ini"]
PROJECT_PATH_KEYS = ("DEFAULT_MODULE_PATH", "DEFAULT_CALLBACK_PLUGIN_PATH", "DEFAULT_FILTER_PLUGIN_PATH", "DEFAULT_LOOKUP_PLUGIN_PATH",
                     "DEFAULT_MODULE_UTILS_PATH", "DEFAULT_ROLES_PATH", "DEFAULT_ACTION_PLUGIN_PATH", "DEFAULT_LOCAL_TMP", "INVENTORY")


def sh(cmd, cwd=None, env=None, timeout=120):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")


def scrubbed_env(clone: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not (k.startswith("ANSIBLE_") or k == "PYTHONPATH")}
    env["ANSIBLE_CONFIG"] = os.path.join(clone, "ansible.cfg")
    env["REPO_ROOT"] = clone
    env["ANSIBLE_LOCALHOST_WARNING"] = "False"
    env["ANSIBLE_STDOUT_CALLBACK"] = "json_only"
    return env


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--clone", required=True)
    ap.add_argument("--bare", required=True)
    ap.add_argument("--vault-password-file", required=True)
    ap.add_argument("--expected-failure-code", default="TARGET_UNREACHABLE")
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args(argv)
    details, failed = [], False
    result = {"failed": False, "channels": {}, "refs": {}, "dev_paths_present": [], "external_deps": {}, "config_paths": {},
              "secret_hits": 0, "condition_mismatch": None, "observed_failure_codes": {}}

    # 1. refs
    bare_refs = sh(["git", "for-each-ref", "--format=%(refname)"], cwd=a.bare).stdout.split()
    clone_refs = sh(["git", "for-each-ref", "--format=%(refname)"], cwd=a.clone).stdout.split()
    result["refs"] = {"bare": bare_refs, "clone": clone_refs}
    if bare_refs != ["refs/heads/main"]:
        failed = True
        details.append(f"bare repo refs != [refs/heads/main]: {bare_refs}")
    if any("production" in r for r in clone_refs):
        failed = True
        details.append(f"clone has a production ref: {clone_refs}")
    else:
        details.append("refs: main only, no production ref (bare + clone)")

    # 2. dev files
    present = [p for p in DEV_PATHS if os.path.exists(os.path.join(a.clone, p))]
    result["dev_paths_present"] = present
    if present:
        failed = True
        details.append(f"dev paths present in the customer-form clone: {present}")
    else:
        details.append("no dev files (tests · scripts/ai · .claude · docs · Jenkinsfile_ci) in the clone")

    # 3. environment + config paths + external deps
    env = scrubbed_env(a.clone)
    dump = sh(["ansible-config", "dump", "--only-changed"], cwd=a.clone, env=env, timeout=180)
    bad_paths = {}
    for line in dump.stdout.splitlines():
        m = re.match(r"^([A-Z_]+)\(([^)]*)\)\s*=\s*(.*)$", line.strip())
        if not m:
            continue
        key, value = m.group(1), m.group(3)
        if key in PROJECT_PATH_KEYS:
            result["config_paths"][key] = value
            vals = re.findall(r"'([^']+)'", value) or [value]
            for v in vals:
                if v.startswith("/") and not v.startswith(a.clone) and not v.startswith("/tmp") and "ansible_collections" not in v and ".ansible" not in v:
                    bad_paths[key] = v
    if dump.returncode != 0:
        failed = True
        details.append(f"ansible-config dump failed rc={dump.returncode}: {dump.stderr.strip()[-200:]}")
    if bad_paths:
        failed = True
        details.append(f"project paths resolve outside the clone: {bad_paths}")
    else:
        details.append(f"config: project paths ({len(result['config_paths'])} keys) resolve under the clone")
    for tool in ("ansible-playbook", "python3", "ansible"):
        which = sh(["bash", "-lc", f"command -v {tool}"]).stdout.strip()
        result["external_deps"][tool] = which
    result["external_deps"]["ansible_version"] = (sh(["ansible", "--version"], env=env).stdout.splitlines() or [""])[0]
    coll = sh(["ansible-config", "dump"], cwd=a.clone, env=env, timeout=180).stdout
    m = re.search(r"COLLECTIONS_PATHS[^=]*=\s*(.*)", coll)
    result["external_deps"]["collections_paths"] = m.group(1).strip() if m else ""

    # 4. channels
    with open(a.vault_password_file, encoding="utf-8", errors="replace") as fh:
        pw_text = fh.read().strip()
    for ch in ("os", "esxi", "redfish"):
        out_dir = os.path.join(a.work, "out", ch)
        os.makedirs(out_dir, exist_ok=True)
        key = "bmc_ip" if ch == "redfish" else "service_ip"
        inv = json.dumps([{key: h} for h in HOSTS])
        cenv = dict(env)
        cenv.update({"INVENTORY_JSON": inv, "ANSIBLE_JSON_OUTPUT_FILE": os.path.join(out_dir, "gather_output.json"),
                     "ANSIBLE_JSON_MANIFEST_FILE": os.path.join(out_dir, "gather_manifest.json"),
                     "ANSIBLE_JSON_PROGRESS_FILE": os.path.join(out_dir, "gather_progress.jsonl"),
                     "ANSIBLE_JSON_CHECKPOINT_FILE": os.path.join(out_dir, "gather_checkpoint.jsonl"),
                     "SE_AUTH_EVIDENCE_DIR": os.path.join(out_dir, "evidence"), "SE_BUILD_ID": "g19", "SE_EVENT_UUID": "g19"})
        cmd = ["timeout", str(a.timeout), "ansible-playbook", os.path.join(a.clone, f"{ch}-gather", "site.yml"),
               "-i", os.path.join(a.clone, f"{ch}-gather", "inventory.sh"), "-e", "se_location=git",
               "-e", "_rf_account_service_dryrun=true", "--vault-password-file", a.vault_password_file]
        try:
            proc = sh(cmd, cwd=a.clone, env=cenv, timeout=a.timeout + 60)
            rc, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            rc, stdout, stderr = 124, "", "python-side timeout"
        with open(os.path.join(out_dir, "stdout.txt"), "w", encoding="utf-8") as fh:
            fh.write(stdout)
        with open(os.path.join(out_dir, "stderr.txt"), "w", encoding="utf-8") as fh:
            fh.write(stderr)
        envs = []
        out_file = os.path.join(out_dir, "gather_output.json")
        if os.path.isfile(out_file):
            with open(out_file, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        envs.append(json.loads(line))
                    except ValueError:
                        envs.append({"_invalid": line[:80]})
        # stdout callback json_only also prints OUTPUT lines; the file is the contract
        problems = []
        if rc == 0 and not envs:
            problems.append("silent failure: rc=0 but no envelope was produced")
        if len(envs) != len(HOSTS):
            problems.append(f"envelopes={len(envs)} != hosts={len(HOSTS)}")
        ips = []
        codes = []
        for i, e in enumerate(envs):
            if "_invalid" in e:
                problems.append(f"envelope[{i}] is not JSON")
                continue
            if set(e.keys()) != KEYS13:
                problems.append(f"envelope[{i}] keys != 13")
            if e.get("target_type") != ch:
                problems.append(f"envelope[{i}] target_type {e.get('target_type')} != {ch}")
            ips.append(str(e.get("ip")))
            d = e.get("diagnosis") or {}
            if not (d.get("failure_stage") and d.get("failure_code") and d.get("failure_reason")):
                problems.append(f"envelope[{i}] failure fields missing: stage={d.get('failure_stage')} code={d.get('failure_code')}")
            codes.append(d.get("failure_code"))
        if set(ips) != set(HOSTS) and envs:
            problems.append(f"ip set {sorted(set(ips))} != {HOSTS}")
        result["channels"][ch] = {"rc": rc, "envelopes": len(envs), "failure_codes": codes, "problems": problems,
                                 "stderr_tail": stderr.strip().splitlines()[-3:]}
        result["observed_failure_codes"][ch] = sorted(set(c for c in codes if c))
        if problems:
            failed = True
            details.append(f"{ch}: " + "; ".join(problems))
        else:
            details.append(f"{ch}: rc={rc} envelopes={len(envs)} codes={sorted(set(codes))}")
        if codes and any(c != a.expected_failure_code for c in codes):
            result["condition_mismatch"] = (result["condition_mismatch"] or "") + f"{ch}:{sorted(set(codes))} "

    # 5. plaintext secret scan (count only)
    hits = 0
    if pw_text:
        for root, _dirs, files in os.walk(os.path.join(a.work, "out")):
            for name in files:
                try:
                    with open(os.path.join(root, name), encoding="utf-8", errors="replace") as fh:
                        if pw_text in fh.read():
                            hits += 1
                except OSError:
                    pass
    result["secret_hits"] = hits
    if hits:
        failed = True
        details.append(f"vault password text found in {hits} output file(s) — plaintext leak (value not shown)")
    else:
        details.append("no plaintext vault password in outputs")

    result["failed"] = failed
    result["details"] = details
    print(json.dumps(result, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
