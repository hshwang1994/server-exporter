"""Live gates: G11 syntax-check, G12 config dump, G13 Jenkins linter, G14 tests overlay, G15 module smoke."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

from .. import PROVENANCE_FILE
from ..common import is_windows
from . import GateResult

CHANNEL_INV = {
    "os": '[{"service_ip": "192.0.2.1"}]',
    "esxi": '[{"service_ip": "192.0.2.1"}]',
    "redfish": '[{"bmc_ip": "192.0.2.1"}]',
}


# ── WSL / native shell helpers ───────────────────────────────────────────────
def _wsl_available() -> bool:
    return (not is_windows() and shutil.which("ansible-playbook") is not None) or \
           (is_windows() and shutil.which("wsl.exe") is not None)


def _wsl_path(win_path: str) -> str:
    if not is_windows():
        return win_path
    drive, rest = os.path.splitdrive(os.path.abspath(win_path))
    return "/mnt/" + drive[0].lower() + rest.replace("\\", "/")


def _bash(script: str, timeout: int = 900) -> subprocess.CompletedProcess:
    if is_windows():
        cmd = ["wsl.exe", "-e", "bash", "-lc", script]
    else:
        cmd = ["bash", "-lc", script]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")


def _stage_tree_in_linux(ctx, name: str) -> str:
    """Copy the generated tree to a Linux-native dir (exec bits from provenance). Returns the linux path."""
    prov = ctx["prov"]
    dest = f"/tmp/prodgen-{name}-{prov['tree_hash'][:12]}"
    execs = " ".join(f"'{p}'" for p, r in prov["files"].items() if r["mode"] == "100755")
    script = (
        f"rm -rf '{dest}' && mkdir -p '{dest}' && cp -r '{_wsl_path(ctx['tree_dir'])}/.' '{dest}/' "
        f"&& cd '{dest}' && chmod -R u+rwX,go-w . && find . -type f -exec chmod a-x {{}} + "
        + (f"&& chmod a+x {execs} " if execs else "")
        + f"&& echo '{dest}'"
    )
    proc = _bash(script, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"staging failed: {proc.stderr.strip()[:400]}")
    return dest


# ── G11 ──────────────────────────────────────────────────────────────────────
def g11_syntax_check(ctx) -> GateResult:
    if not _wsl_available():
        return GateResult("G11", "SKIP", ["no WSL / ansible-playbook available"])
    try:
        dest = _stage_tree_in_linux(ctx, "syntax")
    except RuntimeError as exc:
        return GateResult("G11", "FAIL", [str(exc)])
    details, data, failed = [], {}, False
    for channel, inv in CHANNEL_INV.items():
        script = (
            f"cd '{dest}' && export ANSIBLE_CONFIG='{dest}/ansible.cfg' REPO_ROOT='{dest}' "
            f"INVENTORY_JSON='{inv}' ANSIBLE_STDOUT_CALLBACK=default ANSIBLE_LOCALHOST_WARNING=False && "
            f"ansible-playbook --syntax-check '{dest}/{channel}-gather/site.yml' -i '{dest}/{channel}-gather/inventory.sh' 2>&1; echo \"RC=$?\""
        )
        proc = _bash(script, timeout=900)
        m = re.search(r"RC=(\d+)\s*$", proc.stdout)
        rc = int(m.group(1)) if m else -1
        tail = [l for l in proc.stdout.strip().splitlines() if not l.startswith("RC=")][-6:]
        data[channel] = {"rc": rc, "tail": tail}
        if rc != 0:
            failed = True
            details.append(f"{channel}: rc={rc}: " + " | ".join(tail[-3:]))
        else:
            details.append(f"{channel}: syntax-check OK")
    return GateResult("G11", "FAIL" if failed else "PASS", details, data)


# ── G12 ──────────────────────────────────────────────────────────────────────
def g12_config_dump(ctx) -> GateResult:
    if not _wsl_available():
        return GateResult("G12", "SKIP", ["no WSL / ansible-config available"])
    store, prov = ctx["store"], ctx["prov"]
    rec = prov["files"].get("ansible.cfg")
    if not rec:
        return GateResult("G12", "FAIL", ["ansible.cfg not in tree"])
    src = store.cat_blob(rec["source_blob"])
    with tempfile.TemporaryDirectory(prefix="prodgen-cfg-") as td:
        orig = os.path.join(td, "orig.cfg")
        with open(orig, "wb") as fh:
            fh.write(src)
        gen = os.path.join(ctx["tree_dir"], "ansible.cfg")
        outs = []
        for cfg in (orig, gen):
            lin = _wsl_path(cfg)
            # copy into a non-world-writable location so the file is accepted as a config source
            script = (f"t=$(mktemp -d) && cp '{lin}' \"$t/ansible.cfg\" && cd \"$t\" && "
                      f"ANSIBLE_CONFIG=\"$t/ansible.cfg\" ansible-config dump --only-changed 2>&1; echo \"RC=$?\"; rm -rf \"$t\"")
            proc = _bash(script, timeout=300)
            text = re.sub(r"\(/tmp/[^)]*\)", "(CFG)", proc.stdout)
            text = re.sub(r"/tmp/tmp\.[A-Za-z0-9]+", "/CFGDIR", text)
            outs.append(text)
    if outs[0] != outs[1]:
        diff = [l for l in outs[0].splitlines() if l not in set(outs[1].splitlines())][:8]
        return GateResult("G12", "FAIL", ["ansible-config dump --only-changed differs"] + diff)
    rc_ok = "RC=0" in outs[1]
    return GateResult("G12", "PASS" if rc_ok else "FAIL", ["identical --only-changed dump" if rc_ok else "ansible-config failed"],
                      {"lines": len(outs[1].splitlines())})


# ── G13 ──────────────────────────────────────────────────────────────────────
def g13_jenkins_linter(ctx, netrc=None, jenkins_url="https://jenkins-prod.gooddi.lab") -> GateResult:
    if not netrc or not os.path.isfile(netrc):
        return GateResult("G13", "SKIP", ["no --netrc given (Jenkins linter needs credentials)"])
    curl = shutil.which("curl")
    if not curl:
        return GateResult("G13", "SKIP", ["curl not available"])
    jf = os.path.join(ctx["tree_dir"], "Jenkinsfile_portal")
    base = jenkins_url.rstrip("/")
    with tempfile.TemporaryDirectory(prefix="prodgen-jl-") as td:
        jar = os.path.join(td, "cookies.txt")
        crumb = subprocess.run([curl, "-sk", "--netrc-file", netrc, "-c", jar, "-b", jar, "--max-time", "30",
                                f"{base}/crumbIssuer/api/json"], capture_output=True, text=True)
        headers = []
        try:
            cj = json.loads(crumb.stdout)
            headers = ["-H", f"{cj['crumbRequestField']}: {cj['crumb']}"]
        except (ValueError, KeyError):
            pass
        resp = subprocess.run([curl, "-sk", "--netrc-file", netrc, "-c", jar, "-b", jar, "--max-time", "60", *headers,
                               "-D", os.path.join(td, "headers.txt"),
                               "-X", "POST", "--data-urlencode", f"jenkinsfile@{jf}",
                               f"{base}/pipeline-model-converter/validate"], capture_output=True, text=True)
        jenkins_version = ""
        try:
            with open(os.path.join(td, "headers.txt"), encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if line.lower().startswith("x-jenkins:"):
                        jenkins_version = line.split(":", 1)[1].strip()
        except OSError:
            pass
    if not jenkins_version:
        # the validate endpoint's response has no X-Jenkins header (2026-10-04 실측, GP-29) — GET /api/json carries it
        from . import probe_jenkins_version
        jenkins_version = probe_jenkins_version(base, netrc)
    body = (resp.stdout or "").strip()
    ok = resp.returncode == 0 and "successfully validated" in body
    details = [body[:500] if body else f"curl rc={resp.returncode}, empty response"]
    if not ok and "<html" in body.lower():
        details = ["HTML response (authentication or endpoint problem); body suppressed"]
    return GateResult("G13", "PASS" if ok else "FAIL", details, {"crumb": bool(headers), "jenkins_version": jenkins_version})


# ── G14 ──────────────────────────────────────────────────────────────────────
# 필수 실행 regression 그룹 (2026-10-04, Astra 3차 §8-3 · 4차 §3). 판정 단위는 그룹이다: 그룹의 테스트가 수집되지 않았거나(conftest
# collect_ignore · 수집 오류) 전부 skip 이면 그 그룹은 "확인되지 않음" → G14 는 PASS 여도 partial → 보고서 verdict PARTIAL.
# prodgen 자체 테스트(tests/unit/prodgen)는 여기 넣지 않는다 — 생성 tree 에는 prodgen 이 없어 수집되지 않는 것이 정상이고, 그 검증은
# 개발 main 의 ci_gate.sh 가 맡는다. 선택 테스트의 skip 은 실패로 보지 않는다.
MANDATORY_TEST_GROUPS = {
    "runtime_regression": "tests/regression/",
    "runtime_e2e": "tests/e2e/",
    "budget_formula": "tests/unit/test_gather_budget.py",
    "portal_contract": "tests/unit/test_jenkinsfile_portal_finalize.py",
    "finalize_layer_a": "tests/unit/test_finalize_gather_output.py",
}


def _junit_executed(junit_path: str) -> dict:
    """{file: {"executed": n, "skipped": m}} from a pytest junit xml (classname → path)."""
    import xml.etree.ElementTree as ET
    out = {}
    try:
        root = ET.parse(junit_path).getroot()
    except (OSError, ET.ParseError):
        return out
    for tc in root.iter("testcase"):
        fname = tc.get("file") or (tc.get("classname") or "").replace(".", "/") + ".py"
        fname = fname.replace("\\", "/")
        rec = out.setdefault(fname, {"executed": 0, "skipped": 0})
        if tc.find("skipped") is not None:
            rec["skipped"] += 1
        else:
            rec["executed"] += 1
    return out


def _mandatory_groups_status(overlay_dir: str, junit_path: str) -> tuple[dict, list]:
    """Compare the expected test files (present in the overlay) with what the junit xml says executed."""
    executed = _junit_executed(junit_path)
    groups, problems = {}, []
    for name, prefix in MANDATORY_TEST_GROUPS.items():
        expected = []
        full = os.path.join(overlay_dir, *prefix.split("/"))
        if prefix.endswith(".py"):
            if os.path.isfile(full):
                expected = [prefix]
        elif os.path.isdir(full):
            for root, _dirs, files in os.walk(full):
                for f in files:
                    if f.startswith("test_") and f.endswith(".py"):
                        rel = os.path.relpath(os.path.join(root, f), overlay_dir).replace("\\", "/")
                        expected.append(rel)
        ran = {f: v for f, v in executed.items() if any(f.endswith(e) or e.endswith(f) or f == e for e in expected)}
        n_exec = sum(v["executed"] for v in ran.values())
        n_skip = sum(v["skipped"] for v in ran.values())
        missing = [e for e in expected if not any(f.endswith(e) or e.endswith(f) for f in ran)]
        groups[name] = {"prefix": prefix, "expected_files": len(expected), "collected_files": len(ran), "executed": n_exec,
                        "skipped": n_skip, "missing_files": missing[:20]}
        if not expected:
            problems.append(f"{name}: no test files under {prefix} in the overlay")
        elif missing:
            problems.append(f"{name}: {len(missing)} expected file(s) not collected (e.g. {missing[0]})")
        elif n_exec == 0:
            problems.append(f"{name}: collected but nothing executed (all {n_skip} skipped)")
    return groups, problems


def g14_tests_overlay(ctx) -> GateResult:
    store, prov = ctx["store"], ctx["prov"]
    td = tempfile.mkdtemp(prefix="prodgen-tests-")
    try:
        # copy of the tree (without provenance)
        for rel, full in ctx["files"].items():
            dest = os.path.join(td, *rel.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(full, dest)
        # overlay tests/, schema/, requirements-test.txt from the object store at main_sha
        archive = os.path.join(td, "overlay.tar")
        with open(archive, "wb") as fh:
            fh.write(store.run(["archive", "--format=tar", prov["main_sha"], "--", "tests", "schema", "requirements-test.txt", "pytest.ini"]))
        with tarfile.open(archive) as tf:
            # Python 3.12+ warns without an extraction filter; 'data' rejects absolute paths / links outside td (the archive is ours, from the object store)
            if hasattr(tarfile, "data_filter"):
                tf.extractall(td, filter="data")
            else:
                tf.extractall(td)
        os.unlink(archive)
        # No PYTHONIOENCODING override: tests that spawn repo scripts decode child output with the
        # locale codec, and forcing UTF-8 on the children alone would make such tests fail spuriously.
        env = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        junit = os.path.join(td, "g14_junit.xml")
        targets = [d for d in ("tests/unit", "tests/e2e", "tests/regression") if os.path.isdir(os.path.join(td, d))]
        cmd = [sys.executable, "-m", "pytest", *targets, "-q", "-m", "not source_text",
               "-p", "no:cacheprovider", "-rfE", "--no-header", "-o", "console_output_style=classic",
               "--continue-on-collection-errors", f"--junitxml={junit}", "-o", "junit_family=xunit1"]
        proc = subprocess.run(cmd, cwd=td, capture_output=True, text=True, timeout=3600, env=env,
                              encoding="utf-8", errors="replace")
        lines = proc.stdout.strip().splitlines()
        summary = lines[-1] if lines else ""
        failed = [l[len("FAILED "):] for l in lines if l.startswith("FAILED ")]
        errors = [l[len("ERROR "):] for l in lines if l.startswith("ERROR ")]
        by_file = {}
        for f in failed + errors:
            by_file[f.split("::")[0]] = by_file.get(f.split("::")[0], 0) + 1
        details = [f"pytest rc={proc.returncode}: {summary}"]
        details += [f"{k}: {v} failed/errored" for k, v in sorted(by_file.items(), key=lambda kv: -kv[1])[:25]]
        # 수집 오류(ERROR <module>)는 짧은 요약에 사유가 없다 — 진단용으로 ERRORS 절과 꼬리를 함께 남긴다 (2026-10-03, G14 run 3 의 설명 없는 6 errors).
        err_section = ""
        if "= ERRORS =" in proc.stdout:
            seg = proc.stdout.split("= ERRORS =", 1)[1]
            err_section = seg.split("short test summary", 1)[0][-6000:]
        groups, group_problems = _mandatory_groups_status(td, junit)
        data = {"rc": proc.returncode, "summary": summary, "failed_count": len(failed), "failed": failed[:200],
                "error_count": len(errors), "errors": errors[:200],
                "errors_section": err_section, "stdout_tail": lines[-120:],
                "overlay": "tests/, schema/, requirements-test.txt, pytest.ini from main_sha",
                "targets": targets, "mandatory_groups": groups}
        if proc.returncode == 0 and group_problems:
            data["partial"] = True
            data["partial_reason"] = "mandatory test group(s) not confirmed: " + "; ".join(group_problems)
            details.append("partial: " + "; ".join(group_problems))
        else:
            details.append("mandatory groups: " + ", ".join(f"{k}={v['executed']}" for k, v in groups.items()))
        return GateResult("G14", "PASS" if proc.returncode == 0 else "FAIL", details, data)
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ── G15 ──────────────────────────────────────────────────────────────────────
def g15_module_smoke(ctx) -> GateResult:
    if not _wsl_available():
        return GateResult("G15", "SKIP", ["no WSL / ansible available"])
    try:
        dest = _stage_tree_in_linux(ctx, "smoke")
    except RuntimeError as exc:
        return GateResult("G15", "FAIL", [str(exc)])
    cases = {
        "precheck_bundle": "host=192.0.2.1 channel=redfish timeout_port=1 timeout_protocol=1",
        "redfish_gather": "bmc_ip=192.0.2.1 username=u password=p timeout=2 mode=detect",
        "esxi_disks": "hostname=192.0.2.1 username=u password=p timeout=2",
    }
    details, data, failed = [], {}, False
    for module, args in cases.items():
        script = (
            f"cd '{dest}' && export ANSIBLE_CONFIG='{dest}/ansible.cfg' ANSIBLE_STDOUT_CALLBACK=minimal "
            f"ANSIBLE_LIBRARY='{dest}/common/library:{dest}/redfish-gather/library:{dest}/esxi-gather/library' "
            f"ANSIBLE_MODULE_UTILS='{dest}/module_utils' ANSIBLE_LOCALHOST_WARNING=False && "
            f"timeout 120 ansible localhost -c local -m {module} -a '{args}' 2>&1; echo \"RC=$?\""
        )
        proc = _bash(script, timeout=300)
        out = proc.stdout
        m = re.search(r"RC=(\d+)\s*$", out)
        rc = int(m.group(1)) if m else -1
        body = "\n".join(l for l in out.splitlines() if not l.startswith("RC="))
        has_traceback = "Traceback" in body
        json_start = body.find("{")
        structured = False
        if json_start != -1:
            try:
                json.loads(body[json_start:body.rfind("}") + 1])
                structured = True
            except ValueError:
                structured = False
        ok = structured and not has_traceback
        data[module] = {"rc": rc, "structured_json": structured, "traceback": has_traceback,
                        "head": body.strip()[:300]}
        if not ok:
            failed = True
            details.append(f"{module}: rc={rc} structured={structured} traceback={has_traceback}: {body.strip()[:200]}")
        else:
            details.append(f"{module}: structured failure JSON, no traceback (rc={rc})")
    return GateResult("G15", "FAIL" if failed else "PASS", details, data)
