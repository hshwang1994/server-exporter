"""Stripper dispatch by manifest language."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..common import ProdgenError, StripResult
from . import groovystrip, psstrip, pystrip, shellstrip, simplestrip, yamlstrip


@dataclass
class StripContext:
    policy: dict = field(default_factory=dict)
    shell_checker: object = None     # shellstrip.ShellSyntaxChecker or None
    ps_parser: object = None         # psstrip.PowerShellParser or None

    @classmethod
    def build(cls, policy: dict, live_checkers: bool = True) -> "StripContext":
        ctx = cls(policy=dict(policy or {}))
        if live_checkers:
            ctx.shell_checker = shellstrip.ShellSyntaxChecker()
            if ctx.policy.get("powershell_strip", True):
                ctx.ps_parser = psstrip.PowerShellParser()
        return ctx

    def tool_summary(self) -> dict:
        return {
            "shell_checker": getattr(self.shell_checker, "mode", None),
            "powershell_parser": getattr(self.ps_parser, "exe", None) if self.ps_parser and self.ps_parser.available else None,
        }


def strip_file(language: str, data: bytes, path: str, entry, ctx: StripContext) -> StripResult:
    if language == "vault":
        return simplestrip.strip_vault(data, path)
    text = data.decode("utf-8")
    if language == "python":
        return pystrip.strip(text, entry.python_kind, entry.doc_runtime, path)
    if language == "yaml":
        return yamlstrip.strip(text, path, ctx)
    if language == "groovy":
        return groovystrip.strip(text, path, ctx)
    if language == "ini":
        return simplestrip.strip_ini(text, path)
    if language == "gitmeta":
        return simplestrip.strip_gitmeta(text, path)
    if language == "shell":
        return simplestrip.strip_shell(text, path, ctx)
    if language == "text":
        return StripResult(output=text)
    raise ProdgenError(f"{path}: unknown language {language}")


def residual_scan(language: str, data: bytes, path: str, entry, ctx: StripContext) -> list:
    """[(line_1based, rule_or_None)] comment-like text found in an already-stripped file."""
    if language == "vault":
        return []
    text = data.decode("utf-8")
    if language == "python":
        return pystrip.residual(text, entry.python_kind, entry.doc_runtime)
    if language == "yaml":
        return yamlstrip.residual(text, ctx)
    if language == "groovy":
        return groovystrip.residual(text, ctx)
    if language == "ini":
        return simplestrip.residual_ini(text)
    if language == "gitmeta":
        return simplestrip.residual_gitmeta(text)
    if language == "shell":
        return shellstrip.residual(text)
    if language == "text":
        return []
    raise ProdgenError(f"{path}: unknown language {language}")
