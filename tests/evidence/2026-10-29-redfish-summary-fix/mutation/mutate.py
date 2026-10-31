"""Scratch: mutation checks for the commit-7 tests. Run from the repo root.

Each mutation reverts one SA fix in redfish_gather.py (exactly-one string replace), runs the given pytest files in a fresh
process and records the outcome; the original file bytes are restored after every mutation (and verified by hash).
A mutation is "killed" when pytest exits non-zero.
"""
import hashlib
import subprocess
import sys
from pathlib import Path

RG = Path("redfish-gather/library/redfish_gather.py")
ORIG = RG.read_bytes()
H0 = hashlib.sha256(ORIG).hexdigest()
NL = "\n"
CRLF = (b"\r" + b"\n") in ORIG

MUTATIONS = [
    ("SA-17 telemetry truncation (revert _safe_round_int at the telemetry site)",
     "return _safe_round_int(num)   # 2026-10-29 (SA-17): 절삭 대신 반올림",
     "return _safe_int(num)   # MUTANT",
     ["tests/unit/test_power_rounding_sa17.py"]),
    ("SA-17 helper truncates",
     "    return int(round(f))",
     "    return int(f)",
     ["tests/unit/test_power_rounding_sa17.py"]),
    ("SA-09 Starting/Training back to down for NIC/ports",
     "_LINK_DOWN_VALUES = frozenset(('linkdown', 'down', 'nolink', 'disconnected', 'disabled', 'inactive', 'offline'))",
     "_LINK_DOWN_VALUES = frozenset(('linkdown', 'down', 'nolink', 'disconnected', 'disabled', 'inactive', 'offline', 'starting', 'training'))",
     ["tests/unit/test_link_status_sa09.py"]),
    ("SA-09 Enabled/Active back to up for NIC/ports",
     NL + "_LINK_UP_VALUES = frozenset(('linkup', 'up', 'connected'))",
     NL + "_LINK_UP_VALUES = frozenset(('linkup', 'up', 'connected', 'enabled', 'active'))",
     ["tests/unit/test_link_status_sa09.py"]),
    ("SA-09 HBA-only down set loses Starting/Training (HBA policy must not move)",
     "                                   'starting', 'training'))",
     "                                   ))",
     ["tests/unit/test_link_status_sa09.py"]),
    ("SA-12 union only when Storage has no drives (old A-10)",
     "    if chassis_uris or refs['enclosures']:" + NL + "        extra_ctrls, extra_errs = _chassis_drives_union(",
     "    if (chassis_uris or refs['enclosures']) and not any((c.get('drives') or []) for c in controllers):" + NL
     + "        extra_ctrls, extra_errs = _chassis_drives_union(",
     ["tests/integration/test_sa12_replay_miss_inventory.py", "tests/integration/test_chassis_drives_union_sa12.py"]),
]

src = ORIG.decode("utf-8").replace("\r" + NL, NL)
results = []
try:
    for title, old, new, files in MUTATIONS:
        assert src.count(old) == 1, (title, src.count(old))
        mut = src.replace(old, new)
        if CRLF:
            mut = mut.replace(NL, "\r" + NL)
        RG.write_bytes(mut.encode("utf-8"))
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header", *files],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        last = [line for line in p.stdout.splitlines() if line.strip()][-1:]
        results.append((title, p.returncode, last[0] if last else ""))
        RG.write_bytes(ORIG)
finally:
    RG.write_bytes(ORIG)
assert hashlib.sha256(RG.read_bytes()).hexdigest() == H0, "restore failed"
for title, rc, last in results:
    print(("KILLED   " if rc != 0 else "SURVIVED ") + title + " :: " + last)
