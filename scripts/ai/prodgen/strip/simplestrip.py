"""INI (ansible.cfg), .gitattributes/.gitignore, standalone shell files and vault files."""
from __future__ import annotations

import configparser
import io

from ..common import ClassB, ProdgenError, StripResult, sha256_text, split_lines_keep_final
from ..editlog import Edit, EditEngine
from . import shellstrip

VAULT_HEADER = "$ANSIBLE_VAULT;1.1;AES256"


# ── INI ──────────────────────────────────────────────────────────────────────
def _parse_ini(text: str) -> dict:
    cp = configparser.RawConfigParser(strict=False, interpolation=None, allow_no_value=True)
    cp.optionxform = str
    try:
        cp.read_string(text)
    except configparser.Error as exc:
        raise ProdgenError(f"ini parse failed: {exc}")
    return {s: dict(cp.items(s)) for s in cp.sections()} | {"DEFAULT": dict(cp.defaults())}


def ini_candidates(text: str) -> list:
    out = []
    lines, _ = split_lines_keep_final(text)
    for ln, line in enumerate(lines):
        s = line.lstrip()
        if s.startswith("#") or s.startswith(";"):
            out.append(ln)
    return out


def strip_ini(text: str, path: str) -> StripResult:
    cands = ini_candidates(text)
    result = StripResult(output=text)
    if not cands:
        return result
    edits = [Edit("delete_line", ln, rule="ini.comment") for ln in cands]
    out = EditEngine(text).apply(edits)
    if _parse_ini(text) != _parse_ini(out):
        raise ProdgenError(f"{path}: configparser result changed after comment removal")
    if ini_candidates(out):
        raise ProdgenError(f"{path}: residual INI comments")
    result.output = out
    result.removed_full_lines = len(cands)
    result.counters = {"ini_full": len(cands)}
    return result


def residual_ini(text: str) -> list:
    return [(ln + 1, None) for ln in ini_candidates(text)]


# ── .gitattributes / .gitignore ──────────────────────────────────────────────
def gitmeta_candidates(text: str) -> list:
    lines, _ = split_lines_keep_final(text)
    return [ln for ln, line in enumerate(lines) if line.startswith("#")]


def strip_gitmeta(text: str, path: str) -> StripResult:
    cands = gitmeta_candidates(text)
    result = StripResult(output=text)
    if not cands:
        return result
    out = EditEngine(text).apply([Edit("delete_line", ln, rule="gitmeta.comment") for ln in cands])
    a = [l for l in split_lines_keep_final(text)[0] if not l.startswith("#")]
    b = split_lines_keep_final(out)[0]
    if a != b:
        raise ProdgenError(f"{path}: non-comment lines changed")
    result.output = out
    result.removed_full_lines = len(cands)
    result.counters = {"gitmeta_full": len(cands)}
    return result


def residual_gitmeta(text: str) -> list:
    return [(ln + 1, None) for ln in gitmeta_candidates(text)]


# ── standalone shell files ───────────────────────────────────────────────────
def strip_shell(text: str, path: str, ctx) -> StripResult:
    result = shellstrip.strip_text(text, path)
    if result.class_b or result.output == text:
        return result
    checker = getattr(ctx, "shell_checker", None)
    if checker is not None and checker.available:
        rcs = checker.check([text, result.output])
        if rcs[0] != rcs[1]:
            blocked = StripResult(output=text)
            blocked.class_b.append(ClassB(0, f"shell: bash -n / sh -n parity failed {rcs[0]} -> {rcs[1]}"))
            return blocked
        result.notes.append(f"shell syntax parity bash/sh rc={rcs[0]} -> {rcs[1]}")
    else:
        result.notes.append("shell syntax parity (bash -n / sh -n) skipped: no checker available")
    result.counters = {"shell_full": result.removed_full_lines, "shell_trailing": result.removed_trailing}
    return result


# ── vault ────────────────────────────────────────────────────────────────────
def check_vault(data: bytes, path: str) -> list:
    problems = []
    first = data.split(b"\n", 1)[0].rstrip(b"\r")
    if first != VAULT_HEADER.encode("ascii"):
        problems.append(f"{path}: first line is not '{VAULT_HEADER}'")
    body = data.split(b"\n", 1)[1] if b"\n" in data else b""
    for ln, line in enumerate(body.split(b"\n"), start=2):
        if line and not all(c in b"0123456789abcdef" for c in line.strip()):
            problems.append(f"{path}: line {ln} is not hex vault payload")
            break
    return problems


def strip_vault(data: bytes, path: str) -> StripResult:
    problems = check_vault(data, path)
    result = StripResult(output=data.decode("ascii", "replace"))
    for p in problems:
        result.class_b.append(ClassB(1, "vault: " + p))
    return result
