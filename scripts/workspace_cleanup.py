#!/usr/bin/env python3
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
    t = time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime(ts if ts is not None else time.time()))
    if len(t) >= 5 and t[-5] in "+-":
        t = t[:-2] + ":" + t[-2:]
    return t


def say(line):
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
        say("하루 한 번 확인합니다. 마지막 확인 %s 이후라 이번에는 건너뜁니다." % now_show(last))
        return finish(report)
    lock = Lock(os.path.join(root, ".se-cleanup-%s.lock" % a.job_base))
    if not lock.acquire():
        report["skipped_reason"] = "locked"
        say("같은 Job 의 다른 빌드가 정리 중이라 이번에는 건너뜁니다.")
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
                if why == "no_owner_record" and now - newest_mtime(p) < a.build_limit_sec + RUN_MARGIN_SEC:
                    why = "may_be_running"
                report["skipped"].append({"dir": entry, "reason": why})
                continue
            if ended is None:
                if started is None or now < started + a.build_limit_sec + RUN_MARGIN_SEC:
                    report["skipped"].append({"dir": entry, "reason": "may_be_running"})
                    continue
                ended = started + a.build_limit_sec
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
    say("%d일이 지난 이 Job 의 작업 폴더를 확인했습니다. 지운 폴더 %d개(%s), 결과 파일만 남기고 줄인 폴더 %d개(%s 확보)." % (
        a.keep_days, len(report["deleted"]), mb(deleted_b), len(report["reduced"]), mb(freed_b)))
    if kept:
        say("보관하지 못한 결과를 남긴 폴더 %d개, 크기 %s. 결과를 확인한 뒤 지우세요: %s (위치 %s)" % (
            len(kept), mb(sum(k["bytes"] for k in kept)), ", ".join(k["dir"] for k in kept[:10]) + (" 외" if len(kept) > 10 else ""), root))
    unknown = [s for s in report["skipped"] if s["reason"] in ("no_owner_record", "owner_record_mismatch")]
    if unknown:
        say("소유 빌드를 확인할 수 없어 건드리지 않은 폴더 %d개: %s" % (len(unknown), ", ".join(s["dir"] for s in unknown[:10])))
    for err in report["errors"]:
        say("정리하지 못했습니다: %s (%s)" % (err["dir"], err["error"]))
    if "disk" in report:
        say("작업 폴더가 있는 디스크의 남은 공간: %s / %s" % (mb(report["disk"]["free_bytes"]), mb(report["disk"]["total_bytes"])))
    return finish(report)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        say("정리 중 예상하지 못한 오류로 멈췄습니다(이 빌드의 결과와는 무관합니다): %s: %s" % (type(exc).__name__, exc))
        sys.exit(0)
