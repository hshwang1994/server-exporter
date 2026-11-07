"""Tier 1 orchestrator (Windows side): 미러마다 재생 HTTPS 서버(WSL Ubuntu-24.04, root, 127.0.0.1:443) -> 실제 ansible-playbook(WSL Ubuntu).
사용: python run_tier1.py <label>=<linux_mirror_dir> [...] [--loc yi] [--out-root <win path>] [--only label,...]
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

SP_WIN = Path(__file__).resolve().parents[1]
SP_LIN = "/mnt/c/" + str(SP_WIN).replace("\\", "/")[3:]
SERVER_DISTRO = "Ubuntu-24.04"
PLAYBOOK_DISTRO = "Ubuntu"


def wsl(distro, cmd, **kw):
    env = dict(os.environ)
    env["MSYS_NO_PATHCONV"] = "1"
    return subprocess.run(["wsl", "-d", distro, "--", "bash", "-c", cmd], env=env, **kw)


def start_server(mirror_lin, label, out_lin):
    ready = SP_WIN / "baseline" / "tier1" / label / "server_ready.json"
    if ready.exists():
        ready.unlink()
    access = f"{out_lin}/server_access.jsonl"
    cmd = (f"exec python3 {SP_LIN}/server/mirror_https_server.py '{mirror_lin}' --cert /root/se_mirror_tls/cert.pem "
           f"--key /root/se_mirror_tls/key.pem --log {access} --ready-file {out_lin}/server_ready.json")
    p = subprocess.Popen(["wsl", "-d", SERVER_DISTRO, "--", "bash", "-c", cmd],
                         stdout=open(SP_WIN / "baseline" / "tier1" / label / "server_stdout.log", "w", encoding="utf-8"),
                         stderr=subprocess.STDOUT)
    for _ in range(240):  # 최대 4분 (/mnt/c 에서 index.json 수천 개 로딩)
        if ready.exists():
            return p, json.loads(ready.read_text(encoding="utf-8"))
        if p.poll() is not None:
            return p, None
        time.sleep(1)
    return p, None


def stop_server(p):
    wsl(SERVER_DISTRO, "pkill -f mirror_https_server.py >/dev/null 2>&1; sleep 1; pkill -9 -f mirror_https_server.py >/dev/null 2>&1; true",
        capture_output=True)
    try:
        p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        p.kill()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--loc", default="yi")
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    summary = []
    for t in a.targets:
        label, _, mirror_lin = t.partition("=")
        if only and label not in only:
            continue
        out_win = SP_WIN / "baseline" / "tier1" / label
        out_win.mkdir(parents=True, exist_ok=True)
        out_lin = f"{SP_LIN}/baseline/tier1/{label}"
        t0 = time.time()
        p, info = start_server(mirror_lin, label, out_lin)
        rec = {"label": label, "mirror": mirror_lin, "loc": a.loc, "server": info}
        if info is None:
            rec["error"] = "server did not become ready"
            stop_server(p)
            summary.append(rec)
            print(json.dumps(rec, ensure_ascii=False), flush=True)
            continue
        # 서버 응답 확인 (무인증 root)
        chk = wsl(PLAYBOOK_DISTRO, "curl -sk -o /dev/null -w '%{http_code}' --max-time 20 https://127.0.0.1/redfish/v1/", capture_output=True, text=True)
        rec["root_probe"] = chk.stdout.strip()
        r = wsl(PLAYBOOK_DISTRO, f"bash {SP_LIN}/server/run_playbook.sh {out_lin} {a.loc} 127.0.0.1", capture_output=True, text=True)
        rec["playbook_rc"] = r.returncode
        rec["playbook_tail"] = (r.stdout or "")[-300:]
        stop_server(p)
        rec["elapsed_s"] = round(time.time() - t0, 1)
        # 결과 요약
        outf = out_win / "gather_output.json"
        if outf.exists():
            lines = [ln for ln in outf.read_text(encoding="utf-8").splitlines() if ln.strip()]
            rec["envelopes"] = len(lines)
            try:
                env = json.loads(lines[-1]) if lines else None
            except ValueError:
                env = None
            if isinstance(env, dict):
                rec["status"] = env.get("status")
                rec["vendor"] = env.get("vendor")
                rec["hostname"] = env.get("hostname")
                rec["adapter_id"] = (env.get("meta") or {}).get("adapter_id")
                rec["adapter_first_pass"] = ((env.get("diagnosis") or {}).get("details") or {}).get("adapter_first_pass")
                rec["sections"] = env.get("sections")
                rec["errors"] = len(env.get("errors") or [])
                rec["failure"] = {k: (env.get("diagnosis") or {}).get(k) for k in ("failure_stage", "failure_code", "auth_success")}
        else:
            rec["envelopes"] = 0
        # 서버 접근 로그 요약
        acc = out_win / "server_access.jsonl"
        if acc.exists():
            reqs = [json.loads(x) for x in acc.read_text(encoding="utf-8").splitlines() if x.strip()]
            rec["requests"] = len(reqs)
            rec["req_notes"] = {}
            for q in reqs:
                k = f"{q.get('a')}/{q.get('s')}/{q.get('n')}"
                rec["req_notes"][k] = rec["req_notes"].get(k, 0) + 1
        summary.append(rec)
        print(json.dumps({k: rec.get(k) for k in ("label", "playbook_rc", "status", "vendor", "adapter_id", "adapter_first_pass", "errors", "requests", "elapsed_s", "root_probe")}, ensure_ascii=False), flush=True)
        with open(SP_WIN / "baseline" / "tier1" / "_summary.json", "w", encoding="utf-8", newline="\n") as f:
            json.dump(summary, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
