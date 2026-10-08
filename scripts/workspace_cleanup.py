#!/usr/bin/env python3
"""scripts/workspace_cleanup.py — Runner 에 남은 이 Job 의 끝난 작업 폴더 정리 (2026-10-05, 8차 R8). 운영 runtime 파일이다.

Jenkinsfile_portal 의 서버 정보 수집 단계(post)가 결과 보존 중에 부른다. 하루 한 번만 실제로 본다(같은 Runner · 같은 Job 기준).

왜 필요한가: 작업 폴더는 빌드마다 다르다(`<Job 이름>-<빌드 번호>`). 결과를 보관한 빌드는 자기 폴더를 지우지만, 보관에 실패한 빌드나
Runner 연결이 끊긴 빌드의 폴더는 다음 빌드가 다시 쓰지 않아 계속 남는다. Jenkins 의 기본 작업 폴더 정리는 이런 빌드별 폴더를 보지 않는다.

무엇을 지우나 (모두 이 Job 의 폴더만 — 이름 `<job-base>-<숫자>` 이고 그 안의 소유 기록이 이 Job · 이 빌드 번호를 가리킬 때)
  - 결과 보관을 확인한 폴더(.se_workspace.json preserved=true): 끝난 지 --keep-days 가 지나면 통째로 지운다.
  - 보관하지 못한 결과가 있는 폴더: 결과 파일(gather_* · callback_body.json · finalize_summary.json …)만 **그 자리에 남기고**
    다시 만들 수 있는 부분(저장소 사본 · Add-on 사본 등)만 지운다. 남긴 파일 목록 · 크기 · 이유는 .se_kept_results.json 에 적는다.
    이 폴더는 자동으로 지우지 않는다 — 그 빌드의 유일한 결과일 수 있다. 실행할 때마다 수와 크기를 알린다(사람이 확인한 뒤 지운다).
  - 결과 파일이 하나도 없는 폴더(수집 전에 끝난 빌드): 지킬 결과가 없어 통째로 지운다.
  - `<폴더>@tmp`(Jenkins 의 실행 제어 폴더): 같은 이름의 폴더가 없거나 위에서 정리됐으면 지운다. 결과가 들어 있지 않다.
건드리지 않는 것
  - 소유를 확인할 수 없는 폴더(소유 기록 · 접수 목록이 없거나 다른 Job · 다른 빌드 번호) — 수와 이름만 알린다.
  - 아직 실행 중일 수 있는 폴더: 끝 기록이 없고 시작 뒤 최대 빌드 수명(--build-limit-sec) + 1시간이 지나지 않았거나, 어떤 프로세스가
    그 안을 쓰는 중. 2026-10-06(9차)부터 빌드는 실행 기반(Runner)을 최대 72시간 기다리고 같은 폴더에서 이어서 수집하므로 최대 빌드 수명은
    실행 기반 대기 72시간 + 수집 6시간 + 결과 확인 1시간 + 여유 3시간 = 82시간이다(Jenkinsfile_portal seConstants MAX_BUILD).
  - 지금 빌드의 폴더, 링크(심볼릭 링크)인 폴더, 실제 경로가 작업 폴더 상위 밖인 폴더. 폴더 안의 링크는 따라가지 않고 링크만 지운다.
기간은 빌드 끝 시각(소유 기록의 ended_epoch)으로 센다. 끝 기록이 없으면 시작 + 빌드 한계를 끝으로 본다(늦은 쪽으로 어림).
옛 폴더(소유 기록이 생기기 전)는 접수 목록(gather_manifest.json)으로 소유를 확인하고, 결과 파일의 마지막 수정 시각을 끝으로 어림한다.

동시 실행: 같은 Job 의 정리가 겹치지 않게 잠금 폴더(.se-cleanup-<job-base>.lock)를 쓴다. 1시간이 지난 잠금은 버려진 것으로 본다.
결과: 콘솔에 [작업 폴더 정리] 줄, --report 에 JSON. 비밀값은 다루지 않는다. 종료 코드는 언제나 0 이다(정리 실패가 수집 결과를 바꾸지 않는다).
Python 3.6 이상 · 표준 라이브러리만 (Runner 의 venv 가 없을 때 시스템 python3 로도 돈다).
"""
import argparse
import json
import os
import re
import shutil
import stat
import sys
import time

RESULT_NAMES = (
    "gather_output.json", "gather_manifest.json", "gather_rc.txt", "gather_run.json", "gather_progress.jsonl",
    "gather_checkpoint.jsonl", "gather_final.jsonl", "gather_finalize_report.json", "workspace_cleanup.json",
    "callback_body.json", "finalize_summary.json", "gather_tail_fragments.jsonl",
)
RESULT_DIRS = ("gather_auth_evidence",)
OWNER_FILE = ".se_workspace.json"
KEPT_FILE = ".se_kept_results.json"
STALE_LOCK_SEC = 3600
RUN_MARGIN_SEC = 3600


def now_show(ts=None):
    """날짜 · 시각 · 시간대 — 이 Runner 의 시간대 그대로(예: 2026-10-05 21:10:03 +09:00)."""
    t = time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime(ts if ts is not None else time.time()))
    if len(t) >= 5 and t[-5] in "+-":
        t = t[:-2] + ":" + t[-2:]           # +0900 → +09:00
    return t


def say(line):
    """콘솔 한 줄 — 로캘과 무관하게 UTF-8 로 쓴다(Jenkins 콘솔은 UTF-8 로 읽는다. ASCII 로캘의 python3 에서도 한글 줄로 멈추지 않는다)."""
    text = "[%s] [작업 폴더 정리] %s\n" % (now_show(), line)
    out = getattr(sys.stdout, "buffer", None)
    if out is not None:
        out.write(text.encode("utf-8", "replace"))
        out.flush()
    else:
        sys.stdout.write(text)
        sys.stdout.flush()


def mb(n):
    return "%.1f MB" % (n / 1048576.0)


def tree_size(path):
    total = 0
    for base, dirs, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                total += os.lstat(os.path.join(base, name)).st_size
            except OSError:
                pass
    return total


def read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def within(root_real, path_real):
    return path_real == root_real or path_real.startswith(root_real.rstrip(os.sep) + os.sep)


def paths_in_use(candidates):
    """프로세스의 현재 위치(cwd) · 연 파일이 candidates(실제 경로) 안에 있으면 그 경로들을 돌려준다. 읽을 수 없는 프로세스는 건너뛴다."""
    used = set()
    if not candidates or not os.path.isdir("/proc"):
        return used
    prefixes = [(c, c.rstrip(os.sep) + os.sep) for c in candidates]

    def hit(target):
        for c, pre in prefixes:
            if target == c or target.startswith(pre):
                used.add(c)

    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        base = os.path.join("/proc", pid)
        try:
            hit(os.readlink(os.path.join(base, "cwd")))
        except OSError:
            pass
        try:
            for fd in os.listdir(os.path.join(base, "fd")):
                try:
                    hit(os.readlink(os.path.join(base, "fd", fd)))
                except OSError:
                    pass
        except OSError:
            pass
    return used


def remove_path(path):
    """폴더 · 파일 · 링크를 지운다. 링크는 따라가지 않는다(rmtree 는 안의 링크를 링크로 지운다)."""
    st = os.lstat(path)
    if stat.S_ISDIR(st.st_mode):
        shutil.rmtree(path)
    else:
        os.unlink(path)


class Lock(object):
    def __init__(self, path):
        self.path = path
        self.held = False

    def acquire(self):
        for _ in range(2):
            try:
                os.mkdir(self.path)
                self.held = True
                return True
            except FileExistsError:
                try:
                    age = time.time() - os.lstat(self.path).st_mtime
                except OSError:
                    continue
                if age > STALE_LOCK_SEC:
                    try:
                        os.rmdir(self.path)
                    except OSError:
                        return False
                    continue
                return False
        return False

    def release(self):
        if self.held:
            try:
                os.rmdir(self.path)
            except OSError:
                pass


def owner_of(path, number, job):
    """(확인됨?, 근거, 시작 epoch, 끝 epoch 또는 None, 보존됨?) — 소유 기록, 없으면 접수 목록(옛 폴더)."""
    rec = read_json(os.path.join(path, OWNER_FILE))
    if isinstance(rec, dict):
        if str(rec.get("job")) == job and str(rec.get("build")) == str(number):
            started = rec.get("started_epoch") if isinstance(rec.get("started_epoch"), int) else None
            ended = rec.get("ended_epoch") if isinstance(rec.get("ended_epoch"), int) else None
            return True, "owner_record", started, ended, rec.get("preserved") is True
        return False, "owner_record_mismatch", None, None, False
    man = read_json(os.path.join(path, "gather_manifest.json"))
    build = man.get("build") if isinstance(man, dict) else None
    if isinstance(build, dict) and str(build.get("job")) == job and str(build.get("number")) == str(number):
        stamps = []
        for name in RESULT_NAMES:
            try:
                stamps.append(int(os.lstat(os.path.join(path, name)).st_mtime))
            except OSError:
                pass
        return True, "manifest_legacy", (min(stamps) if stamps else None), (max(stamps) if stamps else None), False
    return False, "no_owner_record", None, None, False


def newest_mtime(path):
    """폴더와 그 바로 아래 항목 중 가장 최근 수정 시각 — 소유 기록을 쓰기 전(checkout 중)의 새 빌드 폴더를 가린다."""
    stamps = []
    try:
        stamps.append(int(os.lstat(path).st_mtime))
        for name in os.listdir(path):
            try:
                stamps.append(int(os.lstat(os.path.join(path, name)).st_mtime))
            except OSError:
                pass
    except OSError:
        pass
    return max(stamps) if stamps else 0


def present_results(path):
    found = []
    for name in RESULT_NAMES:
        p = os.path.join(path, name)
        try:
            st = os.lstat(p)
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode):
            found.append((name, st.st_size))
    for name in RESULT_DIRS:
        p = os.path.join(path, name)
        try:
            st = os.lstat(p)
        except OSError:
            continue
        if stat.S_ISDIR(st.st_mode):
            found.append((name + "/", tree_size(p)))
    return found


def reduce_to_results(path, results, reason):
    """결과 파일만 남기고 나머지를 지운다. 남길 파일을 먼저 확인하고 기록한 뒤 지운다. (지운 바이트, 남긴 바이트)."""
    keep = set(n.rstrip("/") for n, _ in results) | {OWNER_FILE, KEPT_FILE}
    for name, size in results:
        p = os.path.join(path, name.rstrip("/"))
        if name.endswith("/"):
            if not os.path.isdir(p):
                raise OSError("kept dir vanished: %s" % name)
        elif os.lstat(p).st_size != size:
            raise OSError("kept file changed while checking: %s" % name)
    record = {"schema": 1, "reduced_at_epoch": int(time.time()), "reason": reason,
              "kept": [{"name": n, "bytes": s} for n, s in results]}
    with open(os.path.join(path, KEPT_FILE), "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=1)
    freed = 0
    for entry in os.listdir(path):
        if entry in keep:
            continue
        p = os.path.join(path, entry)
        try:
            freed += tree_size(p) if os.path.isdir(p) and not os.path.islink(p) else os.lstat(p).st_size
        except OSError:
            pass
        remove_path(p)
    return freed, sum(s for _, s in results)


def main(argv=None):
    ap = argparse.ArgumentParser(description="이 Job 의 끝난 작업 폴더 정리 (하루 한 번)")
    ap.add_argument("--current", required=True, help="지금 빌드의 작업 폴더")
    ap.add_argument("--job", required=True, help="JOB_NAME (폴더 포함 전체 이름)")
    ap.add_argument("--job-base", required=True, help="JOB_BASE_NAME (작업 폴더 이름의 앞부분)")
    ap.add_argument("--build-limit-sec", type=int, default=295200, help="최대 빌드 수명(초) — 끝 기록이 없는 폴더를 실행 중으로 보는 기간")
    ap.add_argument("--keep-days", type=int, default=7)
    ap.add_argument("--every-sec", type=int, default=86400)
    ap.add_argument("--report", default="")
    a = ap.parse_args(argv)

    now = int(time.time())
    current = os.path.realpath(a.current)
    root = os.path.dirname(current)
    report = {"schema": 1, "root": root, "job": a.job, "ran": False, "checked_at_epoch": now,
              "keep_days": a.keep_days, "deleted": [], "reduced": [], "kept_results": [], "skipped": [], "errors": []}

    def finish(rep):
        if a.report:
            try:
                with open(a.report, "w", encoding="utf-8") as fh:
                    json.dump(rep, fh, ensure_ascii=False, indent=1)
            except OSError:
                pass
        return 0

    stamp_path = os.path.join(root, ".se-cleanup-%s.json" % a.job_base)
    stamp = read_json(stamp_path)
    last = stamp.get("last") if isinstance(stamp, dict) and isinstance(stamp.get("last"), int) else 0
    if now - last < a.every_sec:
        report["skipped_reason"] = "checked_recently"
        report["last_checked_epoch"] = last
        say("마지막 확인(%s) 뒤 %d시간이 지나지 않아 이번에는 건너뜁니다." % (now_show(last), max(1, a.every_sec // 3600)))
        return finish(report)
    lock = Lock(os.path.join(root, ".se-cleanup-%s.lock" % a.job_base))
    if not lock.acquire():
        report["skipped_reason"] = "locked"
        say("같은 Job의 다른 빌드가 정리 중이라 이번에는 건너뜁니다.")
        return finish(report)
    try:
        report["ran"] = True
        pat = re.compile(r"^%s-(\d+)(@tmp)?$" % re.escape(a.job_base))
        root_real = os.path.realpath(root)
        keep_sec = a.keep_days * 86400
        bases, tmps = {}, {}
        for entry in sorted(os.listdir(root)):
            m = pat.match(entry)
            if not m:
                continue
            p = os.path.join(root, entry)
            if os.path.realpath(p) == current or entry == os.path.basename(current) + "@tmp":
                continue
            (tmps if m.group(2) else bases)[entry] = (p, int(m.group(1)))
        # 삭제 · 축소 대상을 정한다
        plan = []
        for entry, (p, number) in bases.items():
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
                report["skipped"].append({"dir": entry, "reason": "not_a_real_directory"})
                continue
            if not within(root_real, os.path.realpath(p)):
                report["skipped"].append({"dir": entry, "reason": "outside_root"})
                continue
            if os.path.exists(os.path.join(p, KEPT_FILE)):
                report["kept_results"].append({"dir": entry, "bytes": tree_size(p)})
                continue
            ok, why, started, ended, preserved = owner_of(p, number, a.job)
            if not ok:
                # 소유 기록이 아직 없는 최근 폴더는 막 시작한 빌드(checkout 중)일 수 있다 — "소유를 모르는 폴더" 로 알리지 않는다(2026-10-06 main #244 관측)
                if why == "no_owner_record" and now - newest_mtime(p) < a.build_limit_sec + RUN_MARGIN_SEC:
                    why = "may_be_running"
                report["skipped"].append({"dir": entry, "reason": why})
                continue
            if ended is None:
                if started is None or now < started + a.build_limit_sec + RUN_MARGIN_SEC:
                    report["skipped"].append({"dir": entry, "reason": "may_be_running"})
                    continue
                ended = started + a.build_limit_sec          # 끝 기록 없음 — 빌드 한계로 늦은 쪽 어림
            if now - ended < keep_sec:
                report["skipped"].append({"dir": entry, "reason": "recent", "ended_epoch": ended})
                continue
            plan.append((entry, p, number, why, ended, preserved))
        busy = paths_in_use([os.path.realpath(x[1]) for x in plan])
        done = set()
        for entry, p, number, why, ended, preserved in plan:
            if os.path.realpath(p) in busy:
                report["skipped"].append({"dir": entry, "reason": "in_use"})
                continue
            try:
                # 삭제 직전에 다시 확인한다 — 그 사이 소유 · 끝 기록이 바뀌었으면 건너뛴다
                ok2, _, _, ended2, preserved2 = owner_of(p, number, a.job)
                if not ok2 or (ended2 is not None and ended2 != ended) or preserved2 != preserved:
                    report["skipped"].append({"dir": entry, "reason": "changed_before_delete"})
                    continue
                results = present_results(p)
                if preserved or not results:
                    size = tree_size(p)
                    remove_path(p)
                    report["deleted"].append({"dir": entry, "bytes": size, "why": "preserved" if preserved else "no_results", "owner": why})
                else:
                    freed, kept = reduce_to_results(p, results, "not_preserved" if why == "owner_record" else "legacy_not_verified")
                    report["reduced"].append({"dir": entry, "freed_bytes": freed, "kept_bytes": kept,
                                              "kept": [n for n, _ in results], "owner": why})
                    report["kept_results"].append({"dir": entry, "bytes": kept})
                done.add(entry)
            except OSError as exc:
                report["errors"].append({"dir": entry, "error": "%s: %s" % (type(exc).__name__, exc)})
        # 실행 제어 폴더(@tmp) — 짝 폴더가 없거나 방금 정리됐고, 오래됐으면 지운다
        for entry, (p, number) in tmps.items():
            base = entry[:-len("@tmp")]
            try:
                st = os.lstat(p)
                if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
                    continue
                if base in bases and base not in done:
                    continue
                if now - int(st.st_mtime) < a.build_limit_sec + RUN_MARGIN_SEC:
                    continue
                if os.path.realpath(p) in paths_in_use([os.path.realpath(p)]):
                    continue
                size = tree_size(p)
                remove_path(p)
                report["deleted"].append({"dir": entry, "bytes": size, "why": "control_dir"})
            except OSError as exc:
                report["errors"].append({"dir": entry, "error": "%s: %s" % (type(exc).__name__, exc)})
        with open(stamp_path, "w", encoding="utf-8") as fh:
            json.dump({"last": now}, fh)
    finally:
        lock.release()

    try:
        du = shutil.disk_usage(root)
        report["disk"] = {"total_bytes": du.total, "free_bytes": du.free}
    except OSError:
        pass
    deleted_b = sum(d["bytes"] for d in report["deleted"])
    freed_b = sum(r["freed_bytes"] for r in report["reduced"])
    kept = report["kept_results"]
    # 사람이 읽는 줄 — 결과 한 줄(디스크 남은 공간 포함), 그 밖에는 사람이 확인할 폴더 · 오류가 있을 때만
    disk = (" 디스크 남은 공간 %s / %s." % (mb(report["disk"]["free_bytes"]), mb(report["disk"]["total_bytes"]))) if "disk" in report else ""
    if report["deleted"] or report["reduced"]:
        say("%d일이 지난 작업 폴더를 정리했습니다. 삭제 %d개(%s), 결과 파일만 남김 %d개(%s 확보).%s" % (
            a.keep_days, len(report["deleted"]), mb(deleted_b), len(report["reduced"]), mb(freed_b), disk))
    else:
        say("정리할 오래된 작업 폴더가 없습니다.%s" % disk)
    if kept:
        say("보관하지 못한 결과를 남긴 폴더 %d개(%s)가 있습니다. 결과를 확인한 뒤 지우세요: %s (위치 %s)" % (
            len(kept), mb(sum(k["bytes"] for k in kept)), ", ".join(k["dir"] for k in kept[:10]) + (" 외" if len(kept) > 10 else ""), root))
    unknown = [s for s in report["skipped"] if s["reason"] in ("no_owner_record", "owner_record_mismatch")]
    if unknown:
        say("소유 빌드를 확인할 수 없어 건드리지 않은 폴더 %d개: %s" % (len(unknown), ", ".join(s["dir"] for s in unknown[:10])))
    for err in report["errors"]:
        say("폴더를 정리하지 못했습니다: %s (%s)" % (err["dir"], err["error"]))
    return finish(report)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                      # noqa: BLE001 — 정리 실패가 빌드를 바꾸지 않는다
        say("정리 중 예상하지 못한 오류로 멈췄습니다. 수집 결과에는 영향이 없습니다. 오류: %s: %s" % (type(exc).__name__, exc))
        sys.exit(0)
