"""승격 체인 — main Job 매트릭스 → CI → prodgen promote → production canary (2026-11-09).

단계: preflight → matrix → matrix_cmp → ci → promote → canary → canary_cmp
기대와 다른 결과가 나오면 그 단계에서 멈춘다(종료 코드 2). 원인을 확인한 뒤 같은 명령에 `--from <단계>` 로 이어 돌린다.
이어 돌리기는 기본 동작이다 — 기대대로 끝난 빌드는 두고, 넣고 끝나지 않은 빌드는 새로 넣지 않고 기다린다(submit.py).

계획 파일(JSON) — 직전 승격 기록에서 만든다. 끝나면 작업 폴더에 다음 승격용 `next_plan.json` 을 쓴다.
  {"jenkins_url": "...", "scm_url": "<CI 가 자격 없이 읽는 GitHub 주소>",
   "jobs": {"main": "...", "ci": "...", "production": "..."},
   "ci_prev": <직전 CI 빌드 — 파라미터 원본>,
   "matrix": [{"scenario": "S1", "prev": <직전 main Job 빌드 — 파라미터 원본 · 비교 기준>}, ...],
   "canary": [{"name": "C-OS", "prev": <직전 production Job 빌드 — 파라미터 원본>, "main_scenario": "S3",
               "baseline": <직전 production 결과 — 비교 기준>}, ...]}
시나리오 기대 결과는 계획 파일이 아니라 prodgen 계약(`scripts.ai.prodgen.evidence.MAIN_CONTRACT`)에서 온다.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import REPO_ROOT
from . import bodies as B
from .detached import acquire
from .jenkins import Jenkins, params_of
from .submit import TIP_OBSERVED, last_by_scenario, run_plan

PHASES = ["preflight", "matrix", "matrix_cmp", "ci", "promote", "canary", "canary_cmp"]
COMPARE_INFO_ONLY = {"T5"}  # 중단 시점에 따라 봉투가 달라진다 — 비교는 참고만
RESUME_HINT = {
    "preflight": "원인을 고친 뒤 같은 명령을 다시 실행",
    "matrix": "원인을 확인한 뒤 --from matrix (기대대로 끝난 시나리오는 다시 넣지 않는다)",
    "matrix_cmp": "cmp_*.txt 의 차이가 장비 쪽 상태 변화로 설명되면 --from ci, 코드 회귀면 승격 중단",
    "ci": "CI 콘솔을 확인한 뒤 --from ci",
    "promote": "다시 돌리기 전에 세 ref(GitHub production · GitLab main · 로컬 production)를 직접 확인 - "
               "docs/operate/09-production-branch.md 5절. 일부만 올라갔으면 prodgen push-sync",
    "canary": "production 은 이미 바뀌었다 - 원인을 보고 되돌릴지 결정 (prodgen restore --to <prod_before> --push-remote origin,internal)",
    "canary_cmp": "production 은 이미 바뀌었다 - 차이를 보고 되돌릴지 결정 (prodgen restore --to <prod_before> --push-remote origin,internal)",
}
JOB_KEYS = ("main", "ci", "production")


class Chain:
    def __init__(self, sha: str, plan: dict, work: Path, netrc: Path, vault_pw: Path, *, fresh: bool = False,
                 repo: Path = REPO_ROOT, py: str = sys.executable):
        self.sha, self.plan, self.work, self.netrc, self.vault_pw = sha, plan, work, netrc, vault_pw
        self.fresh, self.repo, self.py = fresh, repo, py
        self.jk = Jenkins(plan["jenkins_url"], netrc, jar=work / "_session_cookies.txt")
        self.st: dict = {}

    # ------------------------------------------------------------------ 공통
    def log(self, msg: str) -> None:
        line = time.strftime("%H:%M:%S ") + msg
        sys.stdout.buffer.write((line + "\n").encode("utf-8", "replace"))
        sys.stdout.flush()
        with open(self.work / "run.log", "a", encoding="utf-8") as fp:
            fp.write(line + "\n")

    def git(self, *args: str, timeout: int = 120) -> tuple[int, str]:
        p = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, timeout=timeout)
        return p.returncode, p.stdout.decode("utf-8", "replace").strip()

    def ls_remote(self, remote: str, ref: str) -> str:
        rc, out = self.git("ls-remote", remote, ref)
        return out.split()[0] if rc == 0 and out else ""

    def anonymous_read_ok(self) -> bool:
        """CI 의 Prodgen Drift · Verify 처럼 자격 없이 GitHub 를 읽을 수 있는가 (= 저장소 공개)."""
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
        try:
            p = subprocess.run(["git", "-c", "credential.helper=", "-c", "core.askPass=", "ls-remote", self.plan["scm_url"],
                                "refs/heads/production"], capture_output=True, timeout=90, env=env)
        except subprocess.TimeoutExpired:
            return False
        return p.returncode == 0 and bool(p.stdout.strip())

    def job(self, key: str) -> str:
        return self.plan["jobs"][key]

    def params_file(self, key: str, build: int) -> Path:
        return self.work / "params" / f"{key}_{build}.json"

    def body_file(self, key: str, build) -> Path:
        return self.work / "bodies" / f"{key}_{build}.json"

    def params(self, key: str, build: int) -> dict:
        return params_of(json.loads(self.params_file(key, build).read_text(encoding="utf-8")))

    def runs(self, phase: str) -> Path:
        return self.work / f"runs_{phase}.jsonl"

    def entries_for(self, builds: dict) -> str:
        return ",".join(f"{m['scenario']}={self.job('main')}:{builds[m['scenario']]}" for m in self.plan["matrix"])

    def load_state(self) -> None:
        f = self.work / "state.json"
        self.st = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

    def save_state(self) -> None:
        (self.work / "state.json").write_text(json.dumps(self.st, ensure_ascii=False, indent=1), encoding="utf-8")

    def set_fresh(self, phase: str) -> None:
        if not self.fresh:
            return
        for p in (self.runs(phase), self.runs(phase).with_name(self.runs(phase).name + ".started")):
            if p.exists():
                p.rename(p.with_name(f"{p.name}.prev-{int(time.time())}"))

    def already_promoted(self, commit: str) -> bool:
        if not commit:
            return False
        self.git("fetch", "-q", "origin", "production")
        _, body = self.git("log", "-1", "--format=%B", commit)
        return f"Main-SHA: {self.sha}" in body and "Verdict: COMPLETE_PASS" in body

    def compare(self, prev: Path, new: Path, label: str) -> int:
        if not new.exists():
            self.log(f"  [NG] {label}: 새 결과 파일 없음 {new}")
            return 9
        if not prev.exists():
            self.log(f"  [NG] {label}: 비교 기준 파일 없음 {prev}")
            return 9
        bad, lines = B.compare(prev, new, label)
        (self.work / f"cmp_{label}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.log(f"  {'[SAME]' if not bad else '[DIFF]'} {lines[0]}")
        return 1 if bad else 0

    # ------------------------------------------------------------------ 계획
    def contract(self) -> dict:
        from scripts.ai.prodgen.evidence import MAIN_CONTRACT  # 기대 결과의 정본
        return MAIN_CONTRACT

    def validate_plan(self) -> list[str]:
        from scripts.ai.prodgen.evidence import REQUIRED_MAIN
        problems = []
        for k in ("jenkins_url", "scm_url", "jobs", "ci_prev", "matrix", "canary"):
            if k not in self.plan:
                problems.append(f"계획 파일에 {k} 없음")
        if problems:
            return problems
        missing_jobs = [k for k in JOB_KEYS if not self.plan["jobs"].get(k)]
        if missing_jobs:
            problems.append(f"jobs 에 {missing_jobs} 없음")
        names = [m.get("scenario") for m in self.plan["matrix"]]
        if len(names) != len(set(names)):
            problems.append("matrix 시나리오 중복")
        unknown = [n for n in names if n not in self.contract()]
        if unknown:
            problems.append(f"prodgen 계약에 없는 시나리오 {unknown}")
        lack = [n for n in REQUIRED_MAIN if n not in names]
        if lack:
            problems.append(f"필수 시나리오 누락 {lack}")
        for c in self.plan["canary"]:
            if c.get("main_scenario") not in names:
                problems.append(f"canary {c.get('name')} 의 main_scenario {c.get('main_scenario')} 가 matrix 에 없음")
        return problems

    def accept(self, scenario: str) -> tuple[str, ...]:
        return tuple(sorted(self.contract()[scenario]["expected"]))

    def fetch_reference(self) -> list[str]:
        """비교 기준 · 파라미터 원본을 읽어 둔다(GET 만). 이미 있으면 다시 받지 않는다."""
        (self.work / "params").mkdir(parents=True, exist_ok=True)
        (self.work / "bodies").mkdir(parents=True, exist_ok=True)
        want = [("main", m["prev"], True) for m in self.plan["matrix"]] + [("ci", self.plan["ci_prev"], False)]
        want += [("production", c["prev"], False) for c in self.plan["canary"]]
        problems = []
        for key, build, with_body in want:
            pf = self.params_file(key, build)
            if not pf.exists():
                try:
                    d = self.jk.get_json(f"{self.jk.job_url(self.job(key))}/{build}/api/json?tree=actions[parameters[name,value]]")
                    pf.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
                except Exception as exc:  # noqa: BLE001 — 보고하고 멈춘다
                    problems.append(f"{key} #{build} 파라미터 읽기 실패: {exc}")
            if with_body and not self.body_file(key, build).exists():
                code = self.jk.download(f"{self.jk.job_url(self.job(key))}/{build}/artifact/callback_body.json", self.body_file(key, build))
                if code != 200:
                    self.body_file(key, build).unlink(missing_ok=True)
                    problems.append(f"{key} #{build} callback_body.json HTTP {code}")
        for c in self.plan["canary"]:
            bf = self.body_file("production", c["baseline"])
            if not bf.exists():
                code = self.jk.download(f"{self.jk.job_url(self.job('production'))}/{c['baseline']}/artifact/callback_body.json", bf)
                if code != 200:
                    bf.unlink(missing_ok=True)
                    problems.append(f"production #{c['baseline']} callback_body.json HTTP {code}")
        return problems

    # ------------------------------------------------------------------ preflight (읽기 전용)
    def preflight(self, start: str, plan_only: bool) -> list[str]:
        problems = self.validate_plan()
        if problems:
            return problems
        idx = PHASES.index(start)
        for f, why, need in ((self.netrc, "Jenkins 읽기 · 투입", True),
                             (self.vault_pw, "prodgen G19", idx <= PHASES.index("promote"))):
            if need and not f.exists():
                problems.append(f"자격 파일 없음({why}): {f}")
        rc, _ = self.git("cat-file", "-e", f"{self.sha}^{{commit}}")
        if rc != 0:
            problems.append(f"로컬 저장소에 커밋 {self.sha[:12]} 없음")
        if idx <= PHASES.index("promote"):
            tip = self.ls_remote("origin", "refs/heads/main")
            self.log(f"origin main = {tip[:12]} (기대 {self.sha[:12]})")
            if tip != self.sha:
                problems.append(f"origin main({tip[:12]}) 이 --sha 와 다름 - main Job 은 tip 을 받으므로 매트릭스가 다른 커밋을 시험하게 된다")
        if idx <= PHASES.index("ci"):
            public = self.anonymous_read_ok()
            self.st.setdefault("repo_visibility", []).append({"at": int(time.time()), "public": public})
            if not public:
                self.st["repo_was_private"] = True
                problems.append("GitHub 저장소를 자격 없이 읽을 수 없다(비공개) - CI 의 Prodgen Drift · Verify 가 실패한다. "
                                "사용자에게 공개 전환을 요청하고, 바뀐 뒤 같은 명령으로 다시 실행 (끝나면 다시 비공개로 바꾸라고 안내)")
            else:
                self.log("GitHub 저장소 자격 없이 읽기 가능(공개)")
        o, i = self.ls_remote("origin", "refs/heads/production"), self.ls_remote("internal", "refs/heads/main")
        _, heads = self.git("ls-remote", "--heads", "internal")
        nheads = len([ln for ln in heads.splitlines() if ln.strip()])
        self.log(f"production: GitHub production {o[:12]} · GitLab main {i[:12]} · GitLab 브랜치 {nheads}개")
        if not o or o != i:
            problems.append("GitHub production 과 GitLab main 이 다름 - 승격 전에 원인 확인 필요")
        if nheads != 1:
            problems.append(f"GitLab 브랜치가 {nheads}개 (main 하나여야 함)")
        try:
            self.jk.get_json(f"{self.jk.job_url(self.job('main'))}/api/json?tree=name", timeout=60)
            self.log("Jenkins 읽기 OK")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"Jenkins 읽기 실패: {exc}")
            return problems
        problems += self.fetch_reference()
        if idx <= PHASES.index("promote"):
            pb = self.st.get("prod_before")
            if pb and o != pb and self.already_promoted(o):
                self.log(f"production {o[:12]} 은 이 SHA 의 승격 커밋 - 앞 시도에서 승격까지 끝났다(promote 단계가 이어받는다)")
            elif pb and o != pb:
                problems.append(f"production 이 처음 점검 때({pb[:12]})와 다름 - 다른 승격이 있었는지 확인")
            elif not pb and not plan_only:
                self.st["prod_before"] = o
        elif o != self.st.get("prod_after"):
            problems.append(f"production({o[:12]}) 이 이번 승격 커밋({str(self.st.get('prod_after'))[:12]})이 아님")
        if problems:
            return problems
        mprev = {m["scenario"]: m["prev"] for m in self.plan["matrix"]}
        for c in self.plan["canary"]:
            a, b = self.params("production", c["prev"]), self.params("main", mprev[c["main_scenario"]])
            same = B_canon(a.get("inventory_json")) == B_canon(b.get("inventory_json")) and a.get("target_type") == b.get("target_type")
            self.log(f"  {c['name']}(production #{c['prev']}) 대상 == main {c['main_scenario']}(#{mprev[c['main_scenario']]}) 대상: "
                     f"{'같음' if same else '다름'}")
            if not same:
                problems.append(f"{c['name']} 대상이 {c['main_scenario']} 와 다름 - canary 비교 기준을 다시 정해야 함")
        prevp = self.params("ci", self.plan["ci_prev"])
        if self.entries_for(mprev) != prevp.get("E2E_MAIN_ENTRIES"):
            problems.append(f"E2E_MAIN_ENTRIES 형식이 CI #{self.plan['ci_prev']} 와 다름 - 투입 형식 확인 필요")
        else:
            self.log(f"  E2E_MAIN_ENTRIES 형식 == CI #{self.plan['ci_prev']} (빌드 번호만 바뀐다)")
        return problems

    def print_plan(self) -> None:
        self.log("=== plan-only: Jenkins 에 아무것도 보내지 않았다. 실제 실행 시 보낼 내용:")
        self.log(f"[1] main Job {self.job('main')} - {len(self.plan['matrix'])}건 차례로 (직전 빌드와 같은 파라미터, eventUuid 만 새 값)")
        for m in self.plan["matrix"]:
            p = self.params("main", m["prev"])
            try:
                n = len(json.loads(p.get("inventory_json") or "[]"))
            except ValueError:
                n = "?"
            self.log(f"    {m['scenario']:7} <- #{m['prev']} loc={p.get('loc')} target_type={p.get('target_type')} 대상 {n} "
                     f"기대 {'/'.join(self.accept(m['scenario']))}{' (비교 참고만)' if m['scenario'] in COMPARE_INFO_ONLY else ''}")
        self.log(f"[2] 비교: 새 callback_body.json vs 직전 빌드 (status · sections · errors · correlation · serial · diagnosis 일부)")
        self.log(f"[3] CI {self.job('ci')} 1건 - CI #{self.plan['ci_prev']} 파라미터에서 PROMOTE=false · PROMOTE_DRY_RUN=true · "
                 f"PROMOTE_SHA={self.sha} · E2E_MAIN_ENTRIES · E2E_TIP_OBSERVATIONS_JSON 만 바꾼다")
        self.log(f"[4] 작업 PC: python -m scripts.ai.prodgen promote --sha {self.sha} (CI 산출물 3개 · --push-remote origin,internal)")
        self.log(f"[5] production Job {self.job('production')} - {len(self.plan['canary'])}건, 기대 SUCCESS · checkout = 새 production")
        self.log("[6] 비교: canary vs 이번 main 매트릭스 같은 대상 · canary vs 직전 production 결과")

    # ------------------------------------------------------------------ 단계
    def phase_matrix(self) -> list[str]:
        self.set_fresh("matrix")
        if self.fresh and (self.work / "tip_observations.json").exists():
            (self.work / "tip_observations.json").unlink()
        entries = [(m["scenario"], m["prev"], self.accept(m["scenario"])) for m in self.plan["matrix"]]
        problems = []
        try:
            self.jk.login()
            run_plan(self.jk, self.job("main"), entries, runs=self.runs("matrix"), prev_params=lambda b: self.params("main", b),
                     bodies=self.work / "bodies", body_name=lambda n: f"main_{n}.json", expect_sha=self.sha,
                     tip_of_main=lambda: self.ls_remote("origin", "refs/heads/main"), tip_file=self.work / "tip_observations.json",
                     log=self.log)
        except Exception as exc:  # noqa: BLE001 — 보고하고 멈춘다(이어 돌리기로 재개)
            problems.append(f"투입 중 오류: {exc}")
        finally:
            self.jk.drop()
        recs = last_by_scenario(self.runs("matrix"))
        self.st["matrix"] = {s: r.get("build") for s, r in recs.items()}
        self.save_state()
        for m in self.plan["matrix"]:
            s, r = m["scenario"], recs.get(m["scenario"])
            if not r:
                problems.append(f"{s}: 기록 없음")
                continue
            if r.get("result") not in self.accept(s):
                problems.append(f"{s} #{r.get('build')}: {r.get('result')} (기대 {'/'.join(self.accept(s))})")
            if s != TIP_OBSERVED and r.get("checkout_sha") != self.sha:
                problems.append(f"{s} #{r.get('build')}: checkout {r.get('checkout_sha')} (기대 {self.sha[:12]})")
            if r.get("callback_body_http") != 200:
                problems.append(f"{s} #{r.get('build')}: callback_body.json HTTP {r.get('callback_body_http')}")
        a2 = recs.get(TIP_OBSERVED) or {}
        if a2 and not (a2.get("tip_before") == a2.get("tip_after") == self.sha):
            problems.append(f"{TIP_OBSERVED} tip 관측 {a2.get('tip_before')} -> {a2.get('tip_after')} (기대 둘 다 {self.sha[:12]})")
        return problems

    def phase_matrix_cmp(self) -> list[str]:
        problems = []
        for m in self.plan["matrix"]:
            s, prev = m["scenario"], m["prev"]
            num = self.st["matrix"].get(s)
            label = f"{s}_{prev}_vs_{num}"
            rc = self.compare(self.body_file("main", prev), self.body_file("main", num), label)
            if rc and s not in COMPARE_INFO_ONLY:
                problems.append(f"{s}: 직전 #{prev} 대비 차이 - {self.work / ('cmp_' + label + '.txt')}")
            elif rc:
                self.log(f"  [INFO] {s} 차이는 참고만 (중단 시점 의존)")
        return problems

    def phase_ci(self) -> list[str]:
        m = self.st.get("matrix") or {}
        if any(not m.get(x["scenario"]) for x in self.plan["matrix"]):
            return ["매트릭스 빌드 번호가 state.json 에 없음 - --from matrix"]
        tip_f = self.work / "tip_observations.json"
        if not tip_f.exists():
            return [f"tip_observations.json 없음 - {TIP_OBSERVED} 가 이번 매트릭스에서 돌지 않았다 (--from matrix)"]
        tips = json.loads(tip_f.read_text(encoding="utf-8"))
        t = tips[0] if isinstance(tips, list) and len(tips) == 1 else {}
        if not (t.get("build") == m[TIP_OBSERVED] and t.get("sha_before") == t.get("sha_after") == self.sha):
            return [f"tip_observations.json 이 이번 {TIP_OBSERVED}(#{m[TIP_OBSERVED]}) 관측이 아님"]
        self.set_fresh("ci")
        sets = {"PROMOTE": "false", "PROMOTE_DRY_RUN": "true", "PROMOTE_SHA": self.sha, "E2E_MAIN_ENTRIES": self.entries_for(m)}
        problems = []
        try:
            self.jk.login()
            run_plan(self.jk, self.job("ci"), [("CI", self.plan["ci_prev"], ("SUCCESS",))], runs=self.runs("ci"),
                     prev_params=lambda b: self.params("ci", b), bodies=self.work / "bodies", body_name=lambda n: f"ci_{n}.json",
                     expect_sha=self.sha, sets=sets, set_files={"E2E_TIP_OBSERVATIONS_JSON": str(tip_f)}, log=self.log)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"투입 중 오류: {exc}")
        finally:
            self.jk.drop()
        r = last_by_scenario(self.runs("ci")).get("CI") or {}
        self.st["ci"] = r.get("build")
        self.save_state()
        if r.get("result") != "SUCCESS":
            problems.append(f"CI #{r.get('build')}: {r.get('result')} (기대 SUCCESS)")
        if r.get("checkout_sha") != self.sha:
            problems.append(f"CI #{r.get('build')}: checkout {r.get('checkout_sha')} (기대 {self.sha[:12]})")
        if problems or not r.get("build"):
            return problems or ["CI 빌드 번호 없음"]
        d = self.work / f"ci_{r['build']}"
        d.mkdir(exist_ok=True)
        for f in ("ci_stage_results.json", "e2e_evidence.json", "prodgen_verify_report.aggregated.json"):
            code = self.jk.download(f"{self.jk.job_url(self.job('ci'))}/{r['build']}/artifact/{f}", d / f)
            self.log(f"  {f} HTTP {code}")
            if code != 200:
                problems.append(f"CI 산출물 {f} HTTP {code}")
        if problems:
            return problems
        csr = json.loads((d / "ci_stage_results.json").read_text(encoding="utf-8"))
        agg = json.loads((d / "prodgen_verify_report.aggregated.json").read_text(encoding="utf-8"))
        bad = {k: v for k, v in (csr.get("stages") or {}).items() if not (v == "PASS" or (k == "PROMOTE" and v == "not_run"))}
        self.log(f"  ci_stage_results: main_sha={str(csr.get('main_sha'))[:12]} result={csr.get('result')} stages={csr.get('stages')}")
        self.log(f"  집계 verdict={agg.get('verdict')} ok={agg.get('ok')}")
        if csr.get("main_sha") != self.sha:
            problems.append(f"ci_stage_results.main_sha {csr.get('main_sha')} != {self.sha[:12]}")
        if csr.get("result") != "SUCCESS" or bad:
            problems.append(f"CI 단계 결과 {csr.get('result')} · PASS 아닌 단계 {bad}")
        if agg.get("verdict") != "COMPLETE_PASS" or agg.get("ok") is not True:
            problems.append(f"집계 verdict {agg.get('verdict')} ok={agg.get('ok')}")
        return problems

    def refs(self) -> tuple[str, str, str, int]:
        o, i = self.ls_remote("origin", "refs/heads/production"), self.ls_remote("internal", "refs/heads/main")
        _, local = self.git("rev-parse", "production")
        _, heads = self.git("ls-remote", "--heads", "internal")
        return o, i, local, len([ln for ln in heads.splitlines() if ln.strip()])

    def phase_promote(self) -> list[str]:
        o0 = self.ls_remote("origin", "refs/heads/production")
        if o0 and o0 != self.st.get("prod_before") and self.already_promoted(o0):
            i0 = self.ls_remote("internal", "refs/heads/main")
            if i0 == o0:
                self.log(f"  이미 승격됨 - production {o0[:12]} (Main-SHA {self.sha[:12]}) - 승격을 다시 하지 않는다")
                self.st["prod_after"] = o0
                self.save_state()
                return []
            return [f"GitHub production {o0[:12]} 은 이 SHA 의 승격 커밋인데 GitLab main({i0[:12]})이 다름 - prodgen push-sync 로 맞춘다"]
        problems = []
        if self.ls_remote("origin", "refs/heads/main") != self.sha:
            problems.append("origin main 이 매트릭스 뒤에 움직였다 - 매트릭스부터 다시 (승격 SHA 와 시험 SHA 가 같아야 한다)")
        o, i = self.ls_remote("origin", "refs/heads/production"), self.ls_remote("internal", "refs/heads/main")
        if not (o == i == self.st.get("prod_before")):
            problems.append(f"승격 전 production 이 기대와 다름: GitHub {o[:12]} · GitLab {i[:12]} · 기대 {str(self.st.get('prod_before'))[:12]}")
        num = self.st.get("ci")
        d = self.work / f"ci_{num}"
        arts = [d / f for f in ("prodgen_verify_report.aggregated.json", "e2e_evidence.json", "ci_stage_results.json")]
        if not num or not all(p.exists() for p in arts):
            problems.append("CI 산출물이 없음 - --from ci")
        if problems:
            return problems
        cmd = [self.py, "-m", "scripts.ai.prodgen", "promote", "--sha", self.sha,
               "--verify-report", str(arts[0]), "--e2e-evidence", str(arts[1]), "--ci-stage-results", str(arts[2]),
               "--netrc", str(self.netrc), "--vault-password-file", str(self.vault_pw), "--push-remote", "origin,internal"]
        self.log(f"  prodgen promote --sha {self.sha[:12]} (CI #{num} 산출물 3개 · --push-remote origin,internal) - "
                 "G11~G15 · G18~G20 을 이 PC 에서 다시 돌린다. 이 단계가 도는 동안 다른 무거운 실행을 겹치지 않는다")
        t0 = time.time()
        with open(self.work / "promote_result.json", "wb") as out, open(self.work / "promote_stderr.log", "wb") as err:
            rc = subprocess.run(cmd, cwd=str(self.repo), env=dict(os.environ, PYTHONIOENCODING="utf-8"), stdout=out, stderr=err).returncode
        self.log(f"  promote rc={rc} ({round(time.time() - t0)} s)")
        o, i, local, nheads = self.refs()
        self.st["promote_rc"] = rc
        self.st["refs_after"] = {"github_production": o, "gitlab_main": i, "local_production": local, "gitlab_heads": nheads}
        self.save_state()
        self.log(f"  뒤 ref: GitHub production {o[:12]} · GitLab main {i[:12]} · 로컬 production {local[:12]} · GitLab 브랜치 {nheads}개")
        try:
            res = json.loads((self.work / "promote_result.json").read_text(encoding="utf-8"))
        except ValueError:
            res = {}
            problems.append("promote 결과 JSON 을 읽지 못함 - promote_result.json · promote_stderr.log 확인")
        if rc != 0:
            problems.append(f"promote 종료 코드 {rc}")
        if res and res.get("ok") is not True:
            problems.append(f"promote ok={res.get('ok')}")
        if not (o == i == local) or o == self.st.get("prod_before"):
            problems.append("세 ref 가 새 커밋으로 같지 않음")
        if nheads != 1:
            problems.append(f"GitLab 브랜치 {nheads}개")
        _, body = self.git("log", "-1", "--format=%B", o) if o else (1, "")
        for want in (f"Main-SHA: {self.sha}", "Verdict: COMPLETE_PASS", "CI-Stages: verified"):
            if want not in body:
                problems.append(f"새 production trailer 에 '{want}' 없음")
        if not problems:
            self.st["prod_after"] = o
            self.save_state()
        return problems

    def phase_canary(self) -> list[str]:
        prod = self.st.get("prod_after")
        if not prod:
            return ["state.json 에 승격 커밋이 없음 - --from promote"]
        self.set_fresh("canary")
        entries = [(c["name"], c["prev"], ("SUCCESS",)) for c in self.plan["canary"]]
        problems = []
        try:
            self.jk.login()
            run_plan(self.jk, self.job("production"), entries, runs=self.runs("canary"),
                     prev_params=lambda b: self.params("production", b), bodies=self.work / "bodies",
                     body_name=lambda n: f"production_{n}.json", expect_sha=prod, log=self.log)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"투입 중 오류: {exc}")
        finally:
            self.jk.drop()
        recs = last_by_scenario(self.runs("canary"))
        self.st["canary"] = {n: r.get("build") for n, r in recs.items()}
        self.save_state()
        for c in self.plan["canary"]:
            r = recs.get(c["name"])
            if not r:
                problems.append(f"{c['name']}: 기록 없음")
                continue
            if r.get("result") != "SUCCESS":
                problems.append(f"{c['name']} #{r.get('build')}: {r.get('result')} (기대 SUCCESS)")
            if r.get("checkout_sha") != prod:
                problems.append(f"{c['name']} #{r.get('build')}: checkout {r.get('checkout_sha')} (기대 {prod[:12]})")
            if r.get("callback_body_http") != 200:
                problems.append(f"{c['name']} #{r.get('build')}: callback_body.json HTTP {r.get('callback_body_http')}")
        return problems

    def phase_canary_cmp(self) -> list[str]:
        problems = []
        for c in self.plan["canary"]:
            n, ms = c["name"], c["main_scenario"]
            num, mnum = self.st["canary"].get(n), self.st["matrix"][ms]
            new = self.body_file("production", num)
            l1, l2 = f"{n}_{num}_vs_main_{ms}_{mnum}", f"{n}_{num}_vs_prod_{c['baseline']}"
            if self.compare(self.body_file("main", mnum), new, l1):
                problems.append(f"{n}: 같은 코드의 main {ms} 결과와 다름 - {self.work / ('cmp_' + l1 + '.txt')}")
            if self.compare(self.body_file("production", c["baseline"]), new, l2):
                problems.append(f"{n}: 직전 production #{c['baseline']} 결과와 다름 - {self.work / ('cmp_' + l2 + '.txt')}")
        return problems

    def next_plan(self) -> dict:
        nxt = json.loads(json.dumps(self.plan))
        nxt["ci_prev"] = self.st.get("ci")
        for m in nxt["matrix"]:
            m["prev"] = self.st["matrix"][m["scenario"]]
        for c in nxt["canary"]:
            c["prev"] = c["baseline"] = self.st["canary"][c["name"]]
        return nxt

    # ------------------------------------------------------------------ 실행
    def halt(self, phase: str, problems: list[str]) -> int:
        for p in problems:
            self.log(f"[NG] {phase}: {p}")
        self.log(f"[HOLD] {phase} 에서 멈췄다. 다음: {RESUME_HINT[phase]}")
        self.log(f"       기록: {self.work}")
        return 2

    def run(self, start: str, stop: str, plan_only: bool) -> int:
        self.work.mkdir(parents=True, exist_ok=True)
        other = acquire(self.work)
        if other:
            print(f"이미 실행 중: pid={other} (작업 폴더 {self.work}) - 같은 작업 폴더로 둘 띄우지 않는다")
            return 3
        self.load_state()
        self.st.setdefault("sha", self.sha)
        self.log(f"=== 시작 sha={self.sha[:12]} from={start} to={stop} plan_only={plan_only}")
        steps = {"matrix": self.phase_matrix, "matrix_cmp": self.phase_matrix_cmp, "ci": self.phase_ci,
                 "promote": self.phase_promote, "canary": self.phase_canary, "canary_cmp": self.phase_canary_cmp}
        try:
            problems = self.preflight(start, plan_only)
            self.save_state()
            if problems:
                return self.halt("preflight", problems)
            self.log("[PASS] preflight")
            if plan_only:
                self.print_plan()
                return 0
            for ph in PHASES[PHASES.index(start):PHASES.index(stop) + 1]:
                if ph == "preflight":
                    continue
                self.log(f"--- {ph}")
                problems = steps[ph]()
                self.st.setdefault("history", []).append({"phase": ph, "ok": not problems, "at": int(time.time())})
                self.save_state()
                if problems:
                    return self.halt(ph, problems)
                self.log(f"[PASS] {ph}")
            summary = {k: self.st.get(k) for k in ("sha", "prod_before", "prod_after", "matrix", "ci", "canary", "promote_rc",
                                                   "refs_after", "repo_was_private")}
            (self.work / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
            if stop == "canary_cmp":
                (self.work / "next_plan.json").write_text(json.dumps(self.next_plan(), ensure_ascii=False, indent=1), encoding="utf-8")
            self.log(f"=== 끝: {json.dumps(summary, ensure_ascii=False)}")
            if self.st.get("repo_was_private"):
                self.log("[INFO] 이번 실행 중 GitHub 저장소가 비공개였던 적이 있다 - 사용자에게 다시 비공개로 바꾸라고 안내한다")
            return 0
        finally:
            self.jk.drop()


def B_canon(inv) -> str:
    try:
        return json.dumps(json.loads(inv) if isinstance(inv, str) else inv, sort_keys=True, ensure_ascii=False)
    except ValueError:
        return str(inv)


def valid_sha(sha: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{40}", sha))
