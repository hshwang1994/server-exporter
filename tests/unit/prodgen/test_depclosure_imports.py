"""G08 dependency closure - sibling-module imports of directly-run scripts (2026-10-06, 9th round).

python puts a directly-run script's own directory first on sys.path, so `scripts/gather_state.py` can import
`scripts/finalize_gather_output.py`. The gate accepts that only for python_kind "script" and only when the sibling
module is itself part of the generated tree.
"""
from scripts.ai.prodgen.verify.depclosure import Closure


def _closure(tmp_path, files):
    paths, prov = {}, {}
    for rel, (kind, text) in files.items():
        full = tmp_path / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(text, encoding="utf-8")
        paths[rel] = str(full)
        prov[rel] = {"language": "python", "python_kind": kind}
    c = Closure({"tree_dir": str(tmp_path), "files": paths, "prov": {"files": prov}})
    c.check_python_imports()
    return c


def test_script_may_import_sibling_module_in_tree(tmp_path):
    c = _closure(tmp_path, {
        "scripts/gather_state.py": ("script", "import json\nfrom finalize_gather_output import read_jsonl\n"),
        "scripts/finalize_gather_output.py": ("script", "import json\n"),
    })
    assert c.problems == []
    assert c.info["python_sibling_imports"] == ["scripts/gather_state.py -> finalize_gather_output"]


def test_script_import_missing_from_tree_still_fails(tmp_path):
    c = _closure(tmp_path, {"scripts/gather_state.py": ("script", "from finalize_gather_output import read_jsonl\n")})
    assert c.problems == ["scripts/gather_state.py: import 'finalize_gather_output' is not stdlib/module_utils/ansible/yaml/pyVmomi"]


def test_non_script_does_not_get_sibling_imports(tmp_path):
    c = _closure(tmp_path, {
        "redfish-gather/library/redfish_gather.py": ("library", "import helper\n"),
        "redfish-gather/library/helper.py": ("library", "import json\n"),
    })
    assert c.problems == ["redfish-gather/library/redfish_gather.py: import 'helper' is not stdlib/module_utils/ansible/yaml/pyVmomi"]


def test_sibling_in_another_directory_is_not_accepted(tmp_path):
    c = _closure(tmp_path, {
        "scripts/gather_state.py": ("script", "import finalize_gather_output\n"),
        "scripts/jenkins/finalize_gather_output.py": ("script", "import json\n"),
    })
    assert len(c.problems) == 1 and "finalize_gather_output" in c.problems[0]
