import pytest

from scripts.ai.prodgen import PROVENANCE_FILE
from scripts.ai.prodgen.common import PathMatcher, ProdgenError, expand_braces
from scripts.ai.prodgen.manifest import Manifest
from scripts.ai.prodgen.provenance import tree_hash

MANIFEST = """
version: 1
runtime_roots: [app, cfg.ini]
include:
  - glob: "app/{a,b}-gather/**/*.yml"
    language: yaml
    mode: "100644"
  - path: cfg.ini
    language: ini
    mode: "100644"
  - path: app/opt.groovy
    language: groovy
    mode: "100644"
    optional: true
  - glob: "app/**/*.py"
    language: python
    python_kind: plugin
    mode: "100644"
excluded:
  - path: app/notes.txt
    reason: docs
ignore: ["**/README.md"]
forbidden: ["docs/**", "app/secret/**"]
"""


def test_brace_expansion_and_globstar():
    assert expand_braces("x/{a,b}/{c,d}.yml") == ["x/a/c.yml", "x/a/d.yml", "x/b/c.yml", "x/b/d.yml"]
    m = PathMatcher(["app/**/*.yml", "**/README.md", "a/*.py"])
    assert m.matches("app/x.yml") and m.matches("app/d/e/x.yml") and m.matches("README.md") and m.matches("q/README.md")
    assert m.matches("a/b.py") and not m.matches("a/c/b.py")


def test_classification_buckets():
    man = Manifest.load_from_text(MANIFEST)
    paths = ["app/a-gather/site.yml", "app/b-gather/tasks/x.yml", "cfg.ini", "app/plug.py", "app/notes.txt",
             "app/README.md", "app/unknown.sh", "docs/x.md", "app/secret/k.py"]
    cls = man.classify(paths)
    assert set(cls.included) == {"app/a-gather/site.yml", "app/b-gather/tasks/x.yml", "cfg.ini", "app/plug.py", "app/secret/k.py"}
    assert cls.excluded == {"app/notes.txt": "docs"}
    assert cls.ignored == ["app/README.md"]
    assert cls.unclassified == ["app/unknown.sh"]       # docs/x.md is outside runtime roots
    assert cls.stale_entries == []                       # optional entry may match nothing
    assert cls.forbidden_hits == {"app/secret/k.py": ["app/secret/**"]}


def test_ambiguous_and_stale_detection():
    import yaml
    data = yaml.safe_load(MANIFEST)
    data["include"].append({"path": "app/plug.py", "language": "python", "python_kind": "plugin", "mode": "100644"})
    man = Manifest(data, "<dict>")
    cls = man.classify(["app/plug.py"])
    assert "app/plug.py" in cls.ambiguous
    assert "cfg.ini" in cls.stale_entries
    assert "app/opt.groovy" not in cls.stale_entries        # optional entries never count as stale


def test_manifest_validation_errors():
    with pytest.raises(ProdgenError):
        Manifest.load_from_text("version: 2\n")
    with pytest.raises(ProdgenError):
        Manifest.load_from_text("version: 1\ninclude:\n  - path: x\n    language: nope\n    mode: '100644'\n")
    with pytest.raises(ProdgenError):
        Manifest.load_from_text("version: 1\ninclude:\n  - path: x.py\n    language: python\n    mode: '100644'\n")
    with pytest.raises(ProdgenError):
        Manifest.load_from_text("version: 1\nexcluded:\n  - path: x\n")


def test_tree_hash_is_order_independent_and_ignores_provenance():
    a = {"b": ("100644", "2" * 64), "a": ("100755", "1" * 64), PROVENANCE_FILE: ("100644", "f" * 64)}
    b = {"a": ("100755", "1" * 64), "b": ("100644", "2" * 64)}
    assert tree_hash(a) == tree_hash(b)
    assert tree_hash({"a": ("100644", "1" * 64)}) != tree_hash({"a": ("100755", "1" * 64)})
