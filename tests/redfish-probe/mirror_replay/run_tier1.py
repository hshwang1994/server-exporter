"""Tier 1 orchestrator (Windows host): 미러마다 WSL 배포판 A(root)에서 HTTPS 재생 서버(127.0.0.1:443)를 띄우고,
WSL 배포판 B 에서 실제 ansible-playbook(run_playbook.sh — 운영과 같은 env·인자)을 돌린 뒤 서버를 PID 로 끈다.

사용:
  python tests/redfish-probe/mirror_replay/run_tier1.py <label>=<linux mirror dir> [...] --out-root <win dir>
      [--server-distro Ubuntu-24.04] [--playbook-distro Ubuntu] [--loc yi] [--tls-dir <linux dir>]
      [--vault-password-file <linux path>] [--build-id ID] [--only a,b] [--ready-timeout 240]

- 미러 디렉터리는 서버 배포판 안의 Linux 경로다(ext4 권장: extract_mirrors.sh). /mnt/c 도 되지만 로딩이 느리다.
- 인증서: --tls-dir 이 없으면 서버 배포판 /tmp 에 gen_cert.sh 로 만들고 끝나면 지운다. 저장소 안에 두지 않는다.
- 저장소 경로는 이 파일 기준으로 찾아 각 배포판의 wslpath 로 바꿔 bash -c 문자열 안에 인라인한다
  (Windows 환경변수는 WSL 로 상속되지 않는다).
- 443 바인드는 서버 배포판의 root 가 필요하다(또는 sysctl net.ipv4.ip_unprivileged_port_start=443). 모듈이 포트 없는 URL 을
  만들므로(redfish_gather._get_impl) 다른 포트는 쓸 수 없다. Windows 에서 WSL 없이 실행하면 즉시 종료 코드 3 으로 끝난다.
- 산출(label 마다, --out-root 아래): gather_output.json(최종 봉투) · gather_manifest.json · gather_progress.jsonl · gather_checkpoint.jsonl ·
  server_access.jsonl(요청 로그 — 경로·상태·인증 구분만, 헤더 값 없음) · requested_keys.json(요청 집합) · server_ready.json ·
  run_meta.json · ansible_stdout/stderr.log · gather_auth_evidence/. evidence 에 커밋할 때는 gather_auth_evidence/ ·
  .inventory_input.json · ansible_*.log 를 빼거나 내용을 검사한다(비밀값은 없지만 환경 경로가 들어간다).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_WIN = Path(os.environ.get("SE_REPO_ROOT") or HERE.parents[2])
REL_TOOLS = "tests/redfish-probe/mirror_replay"


def _env():
    env = dict(os.environ)
    env["MSYS_NO_PATHCONV"] = "1"
    return env


def wsl(distro, cmd, **kw):
    """배포판 안에서 bash -c <cmd>. 출력은 바이트로 받아 UTF-8 로 푼다(wsl.exe 의 NUL 섞임 방어)."""
    kw.setdefault("capture_output", True)
    r = subprocess.run(["wsl", "-d", distro, "--", "bash", "-c", cmd], env=_env(), **kw)
    if kw.get("capture_output"):
        r.out = (r.stdout or b"").replace(b"\x00", b"").decode("utf-8", "replace")
        r.err = (r.stderr or b"").replace(b"\x00", b"").decode("utf-8", "replace")
    return r


def wslpath(distro, win_path):
    p = str(win_path).replace("\\", "/")
    r = wsl(distro, f"wslpath -a '{p}'")
    out = r.out.strip()
    if r.returncode != 0 or not out:
        raise SystemExit(f"wslpath 실패 ({distro}): {r.err.strip()}")
    return out


def start_server(server_distro, repo_lin, mirror_lin, tls_lin, out_lin, out_win, ready_timeout):
    ready = out_win / "server_ready.json"
    pidf = out_win / "server.pid"
    for f in (ready, pidf):
        if f.exists():
            f.unlink()
    cmd = (f"cd '{repo_lin}' && exec python3 {REL_TOOLS}/mirror_https_server.py '{mirror_lin}' "
           f"--cert '{tls_lin}/cert.pem' --key '{tls_lin}/key.pem' --log '{out_lin}/server_access.jsonl' "
           f"--ready-file '{out_lin}/server_ready.json' --pid-file '{out_lin}/server.pid'")
    stdout = open(out_win / "server_stdout.log", "w", encoding="utf-8")
    p = subprocess.Popen(["wsl", "-d", server_distro, "--", "bash", "-c", cmd], env=_env(),
                         stdout=stdout, stderr=subprocess.STDOUT)
    for _ in range(int(ready_timeout)):
        if ready.exists():
            try:
                return p, json.loads(ready.read_text(encoding="utf-8"))
            except ValueError:
                pass
        if p.poll() is not None:
            return p, None
        time.sleep(1)
    return p, None


def stop_server(server_distro, out_lin, p):
    """PID 파일 기준 SIGTERM (같은 포트 pkill 금지). 서버는 종료 시 PID 파일을 지운다."""
    wsl(server_distro, (f"f='{out_lin}/server.pid'; if [ -f \"$f\" ]; then pid=$(cat \"$f\"); kill \"$pid\" 2>/dev/null; "
                        f"for i in 1 2 3 4 5 6 7 8 9 10; do kill -0 \"$pid\" 2>/dev/null || break; sleep 1; done; "
                        f"kill -9 \"$pid\" 2>/dev/null; fi; true"))
    try:
        p.wait(timeout=20)
    except subprocess.TimeoutExpired:
        p.kill()


def summarize_access(acc: Path):
    reqs = []
    for line in acc.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            reqs.append(json.loads(line))
        except ValueError:
            continue
    by_status = Counter(str(q.get("s")) for q in reqs)
    notes = Counter(f"{q.get('a')}/{q.get('s')}/{q.get('n')}" for q in reqs)
    keys_by_status = {}
    for q in reqs:
        keys_by_status.setdefault(str(q.get("s")), set()).add(str(q.get("k")))
    distinct = sorted({str(q.get("k")) for q in reqs})
    return {"total": len(reqs), "distinct": len(distinct), "by_status": dict(by_status),
            "distinct_keys": distinct,
            "keys_by_status": {k: sorted(v) for k, v in keys_by_status.items()}}, dict(notes)


def last_envelope(outf: Path):
    lines = [ln for ln in outf.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return None, 0
    try:
        return json.loads(lines[-1]), len(lines)
    except ValueError:
        return None, len(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("targets", nargs="+", help="label=<linux mirror dir>")
    ap.add_argument("--out-root", required=True, help="Windows 쪽 산출 루트 (label 마다 하위 폴더)")
    ap.add_argument("--server-distro", default="Ubuntu-24.04")
    ap.add_argument("--playbook-distro", default="Ubuntu")
    ap.add_argument("--loc", default="yi")
    ap.add_argument("--tls-dir", default=None, help="서버 배포판의 cert.pem/key.pem 디렉터리 (없으면 /tmp 에 생성 뒤 삭제)")
    ap.add_argument("--vault-password-file", default=None, help="playbook 배포판의 vault 비밀번호 파일 (기본 $HOME/.se_vault_pass)")
    ap.add_argument("--build-id", default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("--ready-timeout", type=int, default=240)
    a = ap.parse_args()
    if shutil.which("wsl") is None:
        print("wsl 없음 — Tier 1 은 WSL(또는 Linux) 에서만 돌릴 수 있다", file=sys.stderr)
        return 3
    only = set(a.only.split(",")) if a.only else None
    out_root = Path(a.out_root).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    repo_lin_srv = wslpath(a.server_distro, REPO_WIN)
    repo_lin_pb = wslpath(a.playbook_distro, REPO_WIN)
    uid = wsl(a.server_distro, "id -u").out.strip()
    if uid != "0":
        print(f"[WARN] 서버 배포판 {a.server_distro} 의 사용자 uid={uid} — 443 바인드가 실패할 수 있다 "
              f"(root 배포판을 쓰거나 sysctl net.ipv4.ip_unprivileged_port_start=443)", file=sys.stderr)
    tls_lin = a.tls_dir
    tls_tmp = None
    if not tls_lin:
        tls_tmp = f"/tmp/se_mirror_tls.{os.getpid()}"
        r = wsl(a.server_distro, f"bash '{repo_lin_srv}/{REL_TOOLS}/gen_cert.sh' '{tls_tmp}'")
        if r.returncode != 0:
            print("인증서 생성 실패:", r.err.strip(), file=sys.stderr)
            return 4
        tls_lin = tls_tmp
    build_id = a.build_id or f"mirror-replay-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    vault = a.vault_password_file or "$HOME/.se_vault_pass"

    summary = []
    try:
        for t in a.targets:
            label, _, mirror_lin = t.partition("=")
            if not mirror_lin or (only and label not in only):
                continue
            out_win = out_root / label
            out_win.mkdir(parents=True, exist_ok=True)
            out_lin_srv = wslpath(a.server_distro, out_win)
            out_lin_pb = wslpath(a.playbook_distro, out_win)
            t0 = time.time()
            p, info = start_server(a.server_distro, repo_lin_srv, mirror_lin, tls_lin, out_lin_srv, out_win, a.ready_timeout)
            rec = {"label": label, "mirror": mirror_lin, "loc": a.loc, "server": info, "build_id": build_id}
            if info is None:
                rec["error"] = "server did not become ready (server_stdout.log 참조)"
                stop_server(a.server_distro, out_lin_srv, p)
                summary.append(rec)
                print(json.dumps(rec, ensure_ascii=False), flush=True)
                continue
            chk = wsl(a.playbook_distro, "curl -sk -o /dev/null -w '%{http_code}' --max-time 20 https://127.0.0.1/redfish/v1/")
            rec["root_probe"] = chk.out.strip()
            r = wsl(a.playbook_distro,
                    f"SE_REPO_ROOT='{repo_lin_pb}' SE_VAULT_PASSWORD_FILE=\"{vault}\" SE_BUILD_ID='{build_id}' "
                    f"bash '{repo_lin_pb}/{REL_TOOLS}/run_playbook.sh' '{out_lin_pb}' '{a.loc}' 127.0.0.1")
            rec["playbook_rc"] = r.returncode
            rec["playbook_tail"] = (r.out or "")[-300:]
            if r.err.strip():
                rec["playbook_stderr_tail"] = r.err.strip()[-300:]
            stop_server(a.server_distro, out_lin_srv, p)
            rec["elapsed_s"] = round(time.time() - t0, 1)
            outf = out_win / "gather_output.json"
            if outf.exists():
                env, n = last_envelope(outf)
                rec["envelopes"] = n
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
            acc = out_win / "server_access.jsonl"
            if acc.exists():
                keys, notes = summarize_access(acc)
                (out_win / "requested_keys.json").write_text(json.dumps(keys, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
                rec["requests"] = keys["total"]
                rec["requests_distinct"] = keys["distinct"]
                rec["req_notes"] = notes
            summary.append(rec)
            print(json.dumps({k: rec.get(k) for k in ("label", "playbook_rc", "status", "vendor", "adapter_id", "adapter_first_pass",
                                                       "errors", "requests", "requests_distinct", "elapsed_s", "root_probe")},
                             ensure_ascii=False), flush=True)
            (out_root / "_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    finally:
        if tls_tmp:
            wsl(a.server_distro, f"rm -rf '{tls_tmp}'")
    bad = [s["label"] for s in summary if s.get("playbook_rc") not in (0,) or s.get("status") != "success"]
    print(f"done: {len(summary)} label, not-success: {bad}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
