
from __future__ import absolute_import, division, print_function

__metaclass__ = type

import re

CSUS3200_VENDOR_ALIASES = frozenset(
    {
        "hpe",
        "hewlett packard enterprise",
        "hewlett packard enterprise co.",
        "hewlett-packard",
        "hp enterprise",
        "hp",
    }
)

CSUS3200_MODEL_PATTERNS = (
    r"^Compute Scale-up Server 3200.*",
    r"^HPE Compute Scale-up Server.*3200.*",
    r".*Compute Scale-up Server 3200.*",
    r".*CSUS.*3200.*",
)

SUPERDOME_FLEX_MODEL_PATTERNS = (
    r"^Superdome Flex 280.*",
    r"^Superdome Flex(?! 280).*",
    r".*Superdome.*Flex.*",
)

SCALEUP_NPAR_MODEL_PATTERNS = CSUS3200_MODEL_PATTERNS + SUPERDOME_FLEX_MODEL_PATTERNS

NPARTITION_SUFFIX_RE = re.compile(r"^(?P<base>.+)-[0-9]{3}$")

_WHITESPACE_RE = re.compile(r"\s+")


def _clean(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return _WHITESPACE_RE.sub(" ", value).strip()


def _model_matches(model, patterns=SCALEUP_NPAR_MODEL_PATTERNS):
    if not model:
        return False
    for pattern in patterns:
        try:
            if re.search(pattern, model, re.IGNORECASE):
                return True
        except re.error:
            if pattern.lower() in model.lower():
                return True
    return False


def _vendor_is_hpe(vendor):
    return _clean(vendor).lower() in CSUS3200_VENDOR_ALIASES


def is_csus_3200(vendor, model):
    if not _vendor_is_hpe(vendor):
        return False
    return _model_matches(_clean(model), CSUS3200_MODEL_PATTERNS)


def is_superdome_flex(vendor, model):
    if not _vendor_is_hpe(vendor):
        return False
    return _model_matches(_clean(model), SUPERDOME_FLEX_MODEL_PATTERNS)


def is_scaleup_npar(vendor, model):
    if not _vendor_is_hpe(vendor):
        return False
    return _model_matches(_clean(model), SCALEUP_NPAR_MODEL_PATTERNS)


def normalize_os_serial(serial, vendor=None, model=None):
    if not isinstance(serial, str):
        return serial

    stripped = serial.strip()
    if not stripped:
        return serial

    if not is_scaleup_npar(vendor, model):
        return serial

    matched = NPARTITION_SUFFIX_RE.match(stripped)
    if not matched:
        return serial

    return matched.group("base")


class FilterModule(object):

    def filters(self):
        return {
            "normalize_os_serial": normalize_os_serial,
        }
