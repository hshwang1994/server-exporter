# -*- coding: utf-8 -*-

__metaclass__ = type

import re
import yaml


def load_vendor_aliases(aliases_path):
    mapping = {}
    try:
        with open(aliases_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        aliases = data.get("vendor_aliases", {})
        for canonical, alias_list in aliases.items():
            if not isinstance(canonical, str):
                continue
            for alias in (alias_list if isinstance(alias_list, list) else []):
                if isinstance(alias, str):
                    mapping[alias.strip().lower()] = canonical
    except (IOError, OSError, yaml.YAMLError, AttributeError, TypeError) as exc:
        import sys
        print(f"[adapter_common] vendor_aliases 로드 경고: {exc}", file=sys.stderr)
    return mapping


def _flatten_aliases(aliases):
    if not aliases:
        return {}
    sample = next(iter(aliases.values()), None)
    if isinstance(sample, list):
        flat = {}
        for canonical, alias_list in aliases.items():
            for alias in alias_list:
                if isinstance(alias, str):
                    flat[alias.strip().lower()] = canonical
        return flat
    return {str(k).strip().lower(): v for k, v in aliases.items() if isinstance(v, str)}


def normalize_vendor(raw_vendor, aliases=None):
    if not raw_vendor:
        return None

    v = str(raw_vendor).strip().lower()
    if not v:
        return None
    flat = _flatten_aliases(aliases)

    if flat:
        canonical = flat.get(v)
        if canonical:
            return canonical
        v_tokens = set(re.split(r"[^a-z0-9]+", v))
        best_alias, best_canon = "", None
        for alias, canon in flat.items():
            if not alias:
                continue
            hit = (alias in v) if len(alias) >= 3 else (alias in v_tokens)
            if hit and len(alias) > len(best_alias):
                best_alias, best_canon = alias, canon
        if best_canon:
            return best_canon

    return v


def pattern_match_any(patterns, value):
    if not patterns or not value:
        return False
    if not isinstance(patterns, (list, tuple)):
        patterns = [patterns]
    value = str(value)
    for pattern in patterns:
        if not isinstance(pattern, str):
            continue
        try:
            if re.search(pattern, value, re.IGNORECASE):
                return True
        except re.error:
            if pattern.lower() in value.lower():
                return True
    return False


def adapter_matches(adapter, facts, aliases=None):
    match = adapter.get("match")
    if not isinstance(match, dict):
        match = {}
    if not match:
        return True

    vendor_patterns = match.get("vendor", [])
    if isinstance(vendor_patterns, str):
        vendor_patterns = [vendor_patterns]
    if vendor_patterns:
        raw_vendor = facts.get("vendor", "")
        norm_vendor = normalize_vendor(raw_vendor, aliases)

        matched = False
        for vp in vendor_patterns:
            norm_vp = normalize_vendor(vp, aliases)
            if norm_vendor and norm_vp and norm_vendor == norm_vp:
                matched = True
                break
        if not matched:
            return False

    model_patterns = match.get("model_patterns", [])
    if model_patterns:
        model = facts.get("model", "")
        if model and not pattern_match_any(model_patterns, model):
            return False

    firmware_patterns = match.get("firmware_patterns", [])
    if firmware_patterns:
        firmware = facts.get("firmware", "")
        if firmware and not pattern_match_any(firmware_patterns, firmware):
            return False

    os_type = match.get("os_type")
    if os_type:
        detected = facts.get("detected_os") or facts.get("os_type") or ""
        if str(detected).lower() != str(os_type).lower():
            return False

    distribution_patterns = match.get("distribution_patterns", [])
    if distribution_patterns:
        distro = facts.get("distribution", "")
        if distro and not pattern_match_any(distribution_patterns, distro):
            return False

    version_patterns = match.get("version_patterns", [])
    if version_patterns:
        version = facts.get("version", "")
        if version and not pattern_match_any(version_patterns, version):
            return False

    return True


def adapter_specificity(adapter):
    match = adapter.get("match")
    if not isinstance(match, dict):
        match = {}
    score = 0

    if match.get("vendor"):
        score += 10
    if match.get("model_patterns"):
        score += 20
    if match.get("firmware_patterns"):
        score += 20
    if match.get("version_patterns"):
        score += 15
    if match.get("distribution_patterns"):
        score += 15
    if match.get("os_type"):
        score += 5

    if adapter.get("generic", False):
        score -= 40

    return score


def adapter_match_score(adapter, facts, aliases=None):
    match = adapter.get("match")
    if not isinstance(match, dict):
        match = {}
    score = 0

    vendor_patterns = match.get("vendor", [])
    if isinstance(vendor_patterns, str):
        vendor_patterns = [vendor_patterns]
    if vendor_patterns:
        raw_vendor = facts.get("vendor", "")
        norm_vendor = normalize_vendor(raw_vendor, aliases)
        matched = False
        for vp in vendor_patterns:
            norm_vp = normalize_vendor(vp, aliases)
            if norm_vendor and norm_vp and norm_vendor == norm_vp:
                matched = True
                break
        if matched:
            score += 20
        else:
            return -9999

    model_patterns = match.get("model_patterns", [])
    if model_patterns:
        if pattern_match_any(model_patterns, facts.get("model", "")):
            score += 25
        elif not facts.get("model", ""):
            pass
        else:
            return -9999

    firmware_patterns = match.get("firmware_patterns", [])
    if firmware_patterns:
        if pattern_match_any(firmware_patterns, facts.get("firmware", "")):
            score += 25
        elif not facts.get("firmware", ""):
            pass
        else:
            return -9999

    version_patterns = match.get("version_patterns", [])
    if version_patterns:
        if pattern_match_any(version_patterns, facts.get("version", "")):
            score += 15
        elif not facts.get("version", ""):
            pass
        else:
            return -9999

    distribution_patterns = match.get("distribution_patterns", [])
    if distribution_patterns:
        if pattern_match_any(distribution_patterns, facts.get("distribution", "")):
            score += 15
        elif not facts.get("distribution", ""):
            pass
        else:
            return -9999

    os_type = match.get("os_type")
    if os_type:
        detected = facts.get("detected_os") or facts.get("os_type") or ""
        if detected and str(detected).lower() == str(os_type).lower():
            score += 5
        elif not detected:
            pass
        else:
            return -9999

    return score


def adapter_score(adapter, facts, aliases=None):
    try:
        priority = int(adapter.get("priority", 0))
    except (ValueError, TypeError):
        priority = 0
    specificity = adapter_specificity(adapter)
    match_sc = adapter_match_score(adapter, facts, aliases)

    if match_sc == -9999:
        return -9999

    return priority * 1000 + specificity * 10 + match_sc
