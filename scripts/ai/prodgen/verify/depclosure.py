"""G08 dependency closure over the generated tree.

Checks (hard FAIL): include_tasks/import_tasks/include_vars/vars_files/lookup('file')
paths that resolve statically must exist; custom modules exist under library/; the
stdout callback and custom lookup plugins exist; filter names referenced in Jinja
expressions are Jinja builtins, Ansible builtins (list from `ansible-doc` when
available, embedded fallback otherwise) or defined by filter_plugins/; Python imports are
stdlib / module_utils / ansible / yaml / pyVmomi / pyVim; every repository path quoted by
Jenkinsfile_portal exists; the global Redfish standard vault exists.
Dynamic (templated) paths are reported, not failed.
"""
from __future__ import annotations

import ast
import configparser
import os
import posixpath
import re
import shutil
import subprocess
import sys

import jinja2
import yaml

from ..common import is_windows
from ..strip import groovystrip
from . import GateResult

TASK_KEYWORDS = {
    "name", "when", "register", "loop", "loop_control", "vars", "tags", "no_log", "changed_when", "failed_when",
    "ignore_errors", "ignore_unreachable", "delegate_to", "delegate_facts", "run_once", "block", "rescue", "always",
    "until", "retries", "delay", "args", "environment", "become", "become_user", "become_method", "become_flags",
    "timeout", "notify", "any_errors_fatal", "throttle", "connection", "module_defaults", "check_mode", "diff",
    "collections", "remote_user", "port", "vars_files", "hosts", "gather_facts", "tasks", "pre_tasks", "post_tasks",
    "handlers", "roles", "strategy", "serial", "max_fail_percentage", "order", "force_handlers", "debugger",
    "listen", "action", "local_action", "with_items", "with_dict", "with_fileglob", "with_sequence",
    "with_together", "with_subelements", "with_nested", "with_first_found", "with_lines", "with_random_choice",
    "with_indexed_items", "with_flattened", "with_inventory_hostnames", "poll", "async", "apply",
}
BUILTIN_SHORT_MODULES = {
    "set_fact", "debug", "include_tasks", "import_tasks", "include_vars", "raw", "shell", "command", "stat", "fail",
    "assert", "meta", "pause", "uri", "setup", "slurp", "copy", "file", "template", "win_shell", "win_command",
    "lineinfile", "add_host", "group_by", "wait_for", "ping", "win_ping", "script", "include_role", "import_role",
    "set_stats", "get_url", "fetch", "find", "tempfile", "blockinfile", "wait_for_connection", "gather_facts",
    "import_playbook", "win_stat", "win_copy", "win_file", "win_shell", "win_uri", "win_wait_for", "known_hosts",
}
BUILTIN_LOOKUPS = {
    "env", "file", "pipe", "vars", "items", "dict", "first_found", "template", "password", "url", "fileglob",
    "lines", "list", "sequence", "together", "subelements", "nested", "random_choice", "indexed_items",
    "flattened", "inventory_hostnames", "ini", "csvfile", "varnames", "config", "unvault", "cartesian",
}
FALLBACK_ANSIBLE_FILTERS = {
    "to_json", "from_json", "to_yaml", "from_yaml", "from_yaml_all", "to_nice_json", "to_nice_yaml", "b64encode",
    "b64decode", "regex_search", "regex_replace", "regex_findall", "regex_escape", "bool", "combine", "dict2items",
    "items2dict", "flatten", "mandatory", "type_debug", "hash", "quote", "ternary", "unique", "intersect",
    "difference", "union", "symmetric_difference", "strftime", "to_datetime", "splitext", "basename", "dirname",
    "realpath", "relpath", "expanduser", "expandvars", "win_basename", "win_dirname", "win_splitdrive", "checksum",
    "md5", "sha1", "password_hash", "random", "shuffle", "zip", "zip_longest", "subelements", "extract", "product",
    "permutations", "combinations", "path_join", "urlsplit", "urldecode", "comment", "human_readable",
    "human_to_bytes", "rekey_on_member", "log", "pow", "root", "to_uuid", "vault", "unvault", "split", "fileglob",
    "commonpath", "normpath", "ansible_distribution", "to_text", "to_bytes", "ipaddr", "ipv4", "ipv6", "json_query",
    "dict_kv", "version", "version_compare", "max", "min", "abs", "round", "parse_xml", "from_toml", "to_toml",
}
_PATHLIKE_RE = re.compile(r"(?:(?:scripts|common|os-gather|esxi-gather|redfish-gather|adapters|vault|callback_plugins|"
                          r"filter_plugins|lookup_plugins|module_utils)/[A-Za-z0-9_./-]+|ansible\.cfg)")


class Closure:
    def __init__(self, ctx):
        self.ctx = ctx
        self.tree = ctx["tree_dir"]
        self.files = ctx["files"]
        self.problems = []
        self.dynamic = []
        self.info = {}
        self.yaml_docs = {}
        self.yaml_text = {}
        for rel, full in self.files.items():
            if rel.endswith(".yml") and self.ctx["prov"]["files"].get(rel, {}).get("language") == "yaml":
                with open(full, "rb") as fh:
                    text = fh.read().decode("utf-8")
                self.yaml_text[rel] = text
                try:
                    self.yaml_docs[rel] = yaml.safe_load(text)
                except yaml.YAMLError as exc:
                    self.problems.append(f"{rel}: yaml.safe_load failed: {exc}")

    # ── helpers ─────────────────────────────────────────────────────────────
    def exists(self, rel: str) -> bool:
        return rel in self.files

    def _resolve_template_path(self, raw: str, including_file: str):
        """Return (resolved_rel_path_or_None, dynamic_bool)."""
        s = raw.strip()
        s = re.sub(r"\{\{\s*lookup\(\s*'env'\s*,\s*'REPO_ROOT'\s*\)\s*\}\}", "<ROOT>", s)
        s = re.sub(r"\{\{\s*playbook_dir\s*\}\}", "<PB>", s)
        if "{{" in s or "{%" in s:
            return None, True
        channel_dir = including_file.split("/")[0]
        if s.startswith("<ROOT>/"):
            return s[len("<ROOT>/"):], False
        if s.startswith("<PB>/"):
            return channel_dir + "/" + s[len("<PB>/"):], False
        if s.startswith("/"):
            return None, True
        # relative: including file dir first, then the playbook (channel) dir
        inc_dir = os.path.dirname(including_file)
        cand1 = (inc_dir + "/" + s) if inc_dir else s
        cand2 = channel_dir + "/" + s
        if self.exists(cand1):
            return cand1, False
        if self.exists(cand2):
            return cand2, False
        return cand1, False

    def _check_path(self, raw, including_file, what):
        rel, dynamic = self._resolve_template_path(raw, including_file)
        if dynamic:
            self.dynamic.append(f"{including_file}: {what} dynamic path {raw!r}")
            return
        if not self.exists(rel):
            self.problems.append(f"{including_file}: {what} -> {rel} missing")

    # ── walkers ─────────────────────────────────────────────────────────────
    def walk_tasks(self):
        counts = {"include_tasks": 0, "include_vars": 0, "vars_files": 0, "lookup_file": 0, "modules": 0}
        for rel, doc in sorted(self.yaml_docs.items()):
            for node in self._iter_dicts(doc):
                for key, val in node.items():
                    short = key.rsplit(".", 1)[-1]
                    if short in ("include_tasks", "import_tasks"):
                        counts["include_tasks"] += 1
                        target = val.get("file") if isinstance(val, dict) else val
                        if isinstance(target, str):
                            self._check_path(target, rel, short)
                    elif short == "include_vars":
                        counts["include_vars"] += 1
                        target = (val.get("file") or val.get("dir")) if isinstance(val, dict) else val
                        if isinstance(target, str):
                            self._check_path(target, rel, short)
                    elif key == "vars_files" and isinstance(val, list):
                        for item in val:
                            if isinstance(item, str):
                                counts["vars_files"] += 1
                                self._check_path(item, rel, "vars_files")
            for task in self._iter_tasks(doc):
                actions = [k for k in task if k not in TASK_KEYWORDS and not k.startswith("with_")]
                for key in actions:
                    counts["modules"] += 1
                    self._check_module(key, rel)
                if len(actions) > 1:
                    self.problems.append(f"{rel}: task {task.get('name', '?')!r} has several action keys {actions}")
            # lookup('file', ...) anywhere in the text
            for m in re.finditer(r"lookup\(\s*'file'\s*,\s*([^)]*\)[^)]*|[^)]*)\)", self.yaml_text[rel]):
                counts["lookup_file"] += 1
                self._check_lookup_file(m.group(1), rel)
        self.info["counts"] = counts

    def _iter_tasks(self, doc):
        """Yield task dicts: playbook plays' task lists, task files' top-level list, block/rescue/always."""
        if not isinstance(doc, list):
            return
        for item in doc:
            if not isinstance(item, dict):
                continue
            if "hosts" in item:                     # a play
                for section in ("pre_tasks", "tasks", "post_tasks", "handlers"):
                    yield from self._iter_task_list(item.get(section))
            else:
                yield from self._iter_task_list([item])

    def _iter_task_list(self, tasks):
        if not isinstance(tasks, list):
            return
        for task in tasks:
            if not isinstance(task, dict):
                continue
            if any(k in task for k in ("block", "rescue", "always")):
                for section in ("block", "rescue", "always"):
                    yield from self._iter_task_list(task.get(section))
                continue
            yield task

    def _iter_dicts(self, obj):
        if isinstance(obj, dict):
            yield obj
            for v in obj.values():
                yield from self._iter_dicts(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from self._iter_dicts(v)

    def _check_module(self, action: str, rel: str):
        if "." in action:
            return                      # FQCN from ansible-core / collections
        if action in BUILTIN_SHORT_MODULES:
            return
        libs = self._library_dirs(rel)
        if not any(self.exists(f"{d}/{action}.py") for d in libs):
            self.problems.append(f"{rel}: module '{action}' not found under {libs}")
        else:
            self.info.setdefault("custom_modules", set()).add(action)

    def _library_dirs(self, rel: str) -> list:
        dirs = list(self._cfg_paths("library"))
        channel_dir = rel.split("/")[0]
        dirs.append(f"{channel_dir}/library")
        return dirs

    def _cfg(self):
        cp = configparser.RawConfigParser(strict=False, interpolation=None, allow_no_value=True)
        if "ansible.cfg" in self.files:
            with open(self.files["ansible.cfg"], encoding="utf-8") as fh:
                cp.read_file(fh)
        return cp

    def _cfg_paths(self, key: str) -> list:
        raw = self._cfg().get("defaults", key, fallback="")
        return [p.strip().lstrip("./") for p in raw.split(":") if p.strip()]

    def _check_lookup_file(self, expr: str, rel: str):
        e = expr.strip()
        e = re.sub(r"lookup\(\s*'env'\s*,\s*'REPO_ROOT'\s*\)", "<ROOT>", e)
        if "lookup(" in e:
            self.dynamic.append(f"{rel}: lookup('file') with dynamic env path {e[:60]!r}")
            return
        parts = [p.strip().strip("'\"") for p in re.split(r"\s*[+~]\s*", e) if p.strip()]
        joined = "".join(parts)
        if joined.startswith("<ROOT>/"):
            target = joined[len("<ROOT>/"):]
            if not self.exists(target):
                self.problems.append(f"{rel}: lookup('file') -> {target} missing")
        else:
            self.dynamic.append(f"{rel}: lookup('file') unresolved {e[:60]!r}")

    # ── plugins ─────────────────────────────────────────────────────────────
    def _allowlisted(self, path: str) -> bool:
        manifest = self.ctx.get("manifest")
        return bool(manifest) and any(e.matches(path) for e in manifest.include)

    def check_plugins(self, builtin_filters: set, builtin_lookups: set, live: bool):
        if "ansible.cfg" not in self.files:
            if self._allowlisted("ansible.cfg"):
                self.problems.append("ansible.cfg missing from tree")
            else:
                self.info["ansible_cfg"] = "not allowlisted by this manifest; cfg-based checks skipped"
        cp = self._cfg()
        for key in ("stdout_callback", "callbacks_enabled"):
            for name in cp.get("defaults", key, fallback="").split(","):
                name = name.strip()
                if name and not self.exists(f"callback_plugins/{name}.py"):
                    self.problems.append(f"ansible.cfg {key}: callback plugin {name} missing")
        lookups_used = set()
        for text in self.yaml_text.values():
            lookups_used.update(re.findall(r"lookup\(\s*'([a-z_]+)'", text))
        for name in sorted(lookups_used):
            if name in BUILTIN_LOOKUPS or name in builtin_lookups:
                continue
            if not self.exists(f"lookup_plugins/{name}.py"):
                self.problems.append(f"lookup plugin '{name}' referenced but lookup_plugins/{name}.py missing")
        self.info["lookups_used"] = sorted(lookups_used)
        defined = set()
        for rel, full in self.files.items():
            if rel.startswith("filter_plugins/") and rel.endswith(".py"):
                defined |= self._filter_names(full)
        self.info["filters_defined"] = sorted(defined)
        used = self._filters_used()
        jinja_builtin = set(jinja2.defaults.DEFAULT_FILTERS)
        unknown = sorted(f for f in used if f not in defined and f not in jinja_builtin and f not in builtin_filters)
        self.info["filters_used"] = len(used)
        if unknown:
            if live:
                self.problems.append(f"filters referenced but not defined anywhere: {unknown}")
            else:
                fallback_unknown = [f for f in unknown if f not in FALLBACK_ANSIBLE_FILTERS]
                if fallback_unknown:
                    self.problems.append(f"filters not in Jinja/plugins/fallback-builtin list: {fallback_unknown}")
                self.info["filters_unverified_offline"] = unknown

    @staticmethod
    def _filter_names(path: str) -> set:
        with open(path, "rb") as fh:
            tree = ast.parse(fh.read().decode("utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "filters":
                for r in ast.walk(node):
                    if isinstance(r, ast.Return) and isinstance(r.value, ast.Dict):
                        for k in r.value.keys:
                            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                                names.add(k.value)
        return names

    def _filters_used(self) -> set:
        used = set()
        expr_keys = {"when", "failed_when", "changed_when", "until", "that"}
        for rel, doc in self.yaml_docs.items():
            for node in self._iter_dicts(doc):
                for key, val in node.items():
                    for s in self._strings(val):
                        exprs = re.findall(r"\{\{(.*?)\}\}|\{%(.*?)%\}", s, flags=re.S)
                        texts = [a or b for a, b in exprs]
                        if key in expr_keys and "{{" not in s:
                            texts.append(s)
                        for t in texts:
                            t = re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", "''", t)
                            used.update(re.findall(r"\|\s*([A-Za-z_]\w*)", t))
        return used

    def _strings(self, val):
        if isinstance(val, str):
            yield val
        elif isinstance(val, list):
            for v in val:
                yield from self._strings(v)
        elif isinstance(val, dict):
            for v in val.values():
                yield from self._strings(v)

    # ── python imports ──────────────────────────────────────────────────────
    def check_python_imports(self):
        stdlib = set(sys.stdlib_module_names)
        module_utils = {os.path.splitext(os.path.basename(p))[0] for p in self.files if p.startswith("module_utils/")}
        allowed_roots = {"ansible", "yaml", "pyVmomi", "pyVim", "__future__"}
        count = 0
        siblings = []
        for rel, full in sorted(self.files.items()):
            if self.ctx["prov"]["files"].get(rel, {}).get("language") != "python":
                continue
            with open(full, "rb") as fh:
                tree = ast.parse(fh.read().decode("utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level and node.level > 0:
                        self.problems.append(f"{rel}: relative import unsupported in flat plugin dirs")
                        continue
                    names = [node.module or ""]
                for name in names:
                    root = name.split(".")[0]
                    count += 1
                    if root in stdlib or root in allowed_roots or root in module_utils:
                        if name.startswith("ansible.module_utils."):
                            sub = name.split(".")[2]
                            if sub not in module_utils and sub not in {"basic", "common", "six", "urls", "parsing",
                                                                        "compat", "_text", "facts", "json_utils"}:
                                self.problems.append(f"{rel}: ansible.module_utils.{sub} not provided by tree")
                        continue
                    if self._sibling_script_module(rel, root):
                        siblings.append(f"{rel} -> {root}")
                        continue
                    self.problems.append(f"{rel}: import '{name}' is not stdlib/module_utils/ansible/yaml/pyVmomi")
        self.info["python_imports_checked"] = count
        self.info["python_sibling_imports"] = siblings

    def _sibling_script_module(self, rel: str, root: str) -> bool:
        # 직접 실행되는 스크립트(python_kind: script)는 python 이 자기 폴더를 sys.path 맨 앞에 둔다 — 그 폴더의 모듈이
        # 생성 tree 에 python 으로 함께 들어 있을 때만 의존이 닫힌 것으로 본다 (2026-10-06 9차: gather_state.py -> finalize_gather_output)
        if self.ctx["prov"]["files"].get(rel, {}).get("python_kind") != "script":
            return False
        sibling = posixpath.join(posixpath.dirname(rel), root + ".py")
        return sibling in self.files and self.ctx["prov"]["files"].get(sibling, {}).get("language") == "python"

    # ── Jenkinsfile quoted paths ────────────────────────────────────────────
    def check_jenkinsfile_paths(self):
        rel = "Jenkinsfile_portal"
        if rel not in self.files:
            if self._allowlisted(rel):
                self.problems.append("Jenkinsfile_portal missing from tree")
            else:
                self.info["jenkinsfile"] = "not allowlisted by this manifest; quoted-path check skipped"
            return
        with open(self.files[rel], "rb") as fh:
            text = fh.read().decode("utf-8")
        try:
            toks = groovystrip.tokenize(text)
        except groovystrip.Ambiguous as exc:
            self.problems.append(f"Jenkinsfile_portal: tokenizer ambiguity: {exc.reason}")
            return
        paths = set()
        for t in toks:
            if t.kind == "string":
                for m in _PATHLIKE_RE.finditer(t.text):
                    p = m.group(0).rstrip(".")
                    if "${" in p or "$" in p:
                        continue
                    paths.add(p)
        missing = sorted(p for p in paths if not self.exists(p) and not any(f.startswith(p.rstrip("/") + "/") for f in self.files))
        self.info["jenkinsfile_paths"] = sorted(paths)
        for p in missing:
            self.problems.append(f"Jenkinsfile_portal quotes {p} which is not in the tree")

    # ── vault patterns ──────────────────────────────────────────────────────
    def check_vault_patterns(self):
        has_redfish = any(p.startswith("redfish-gather/") for p in self.files)
        if has_redfish and not self.exists("vault/common/redfish/standard.yml"):
            self.problems.append("vault/common/redfish/standard.yml (global Redfish standard account) missing")
        locs = list((self.yaml_docs.get("common/vars/locations.yml") or {}).get("locations", {}).keys())
        vendors = list((self.yaml_docs.get("common/vars/vendor_aliases.yml") or {}).get("vendor_aliases", {}).keys())
        matrix_missing = []
        for loc in locs:
            for p in (f"vault/{loc}/esxi.yml", f"vault/{loc}/os/linux.yml", f"vault/{loc}/os/windows.yml"):
                if not self.exists(p):
                    matrix_missing.append(p)
            for v in vendors:
                if not self.exists(f"vault/{loc}/redfish/{v}.yml"):
                    matrix_missing.append(f"vault/{loc}/redfish/{v}.yml")
        vault_files = [p for p in self.files if p.startswith("vault/")]
        if not vault_files:
            self.problems.append("no vault files in tree")
        self.info["vault"] = {"files": len(vault_files), "locations": locs, "vendors": len(vendors),
                              "matrix_missing": matrix_missing}


def _ansible_doc_names(kind: str) -> set:
    """Names from `ansible-doc -t <kind> -l` (native or via WSL). Empty set if unavailable."""
    cmd = ["ansible-doc", "-t", kind, "-l"]
    if is_windows():
        if not shutil.which("wsl.exe"):
            return set()
        cmd = ["wsl.exe", "-e", "bash", "-lc", "ansible-doc -t %s -l 2>/dev/null" % kind]
    elif not shutil.which("ansible-doc"):
        return set()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (subprocess.TimeoutExpired, OSError):
        return set()
    names = set()
    for line in proc.stdout.splitlines():
        parts = line.split()
        if parts:
            names.add(parts[0].rsplit(".", 1)[-1])
    return names


def g08_dependency_closure(ctx) -> GateResult:
    c = Closure(ctx)
    c.walk_tasks()
    builtin_filters = _ansible_doc_names("filter")
    builtin_lookups = _ansible_doc_names("lookup") if builtin_filters else set()
    live = bool(builtin_filters)
    c.check_plugins(builtin_filters, builtin_lookups, live)
    c.check_python_imports()
    c.check_jenkinsfile_paths()
    c.check_vault_patterns()
    details = list(c.problems)
    for d in c.dynamic:
        details.append("INFO dynamic: " + d)
    data = {k: (sorted(v) if isinstance(v, set) else v) for k, v in c.info.items()}
    data["ansible_builtin_lists"] = "ansible-doc" if live else "embedded fallback"
    data["dynamic_paths"] = len(c.dynamic)
    return GateResult("G08", "FAIL" if c.problems else "PASS", details, data)
