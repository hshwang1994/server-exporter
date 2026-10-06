
from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os
import sys

UNKNOWN_VENDOR = "unknown"


def _import_normalize_vendor():
    candidates = []
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.normpath(os.path.join(here, "..", "module_utils")))
    except NameError:
        pass
    repo_root = os.environ.get("REPO_ROOT", "")
    if repo_root:
        candidates.append(os.path.join(repo_root, "module_utils"))

    for path in candidates:
        if path and os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)

    from adapter_common import normalize_vendor

    return normalize_vendor


def canonical_vendor(raw_vendor, aliases=None, unknown=UNKNOWN_VENDOR):
    if not aliases:
        return unknown

    canonical_keys = _canonical_key_set(aliases)
    if not canonical_keys:
        return unknown

    normalize_vendor = _import_normalize_vendor()
    result = normalize_vendor(raw_vendor, aliases)
    if result and result in canonical_keys:
        return result
    return unknown


def _canonical_key_set(aliases):
    if not isinstance(aliases, dict):
        return set()
    sample = next(iter(aliases.values()), None)
    if isinstance(sample, list):
        return {k for k in aliases.keys() if isinstance(k, str)}
    return {v for v in aliases.values() if isinstance(v, str)}


class FilterModule(object):

    def filters(self):
        return {
            "canonical_vendor": canonical_vendor,
        }
