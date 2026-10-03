import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from scripts.ai.prodgen.strip import StripContext  # noqa: E402


@pytest.fixture
def ctx():
    """Stripper context without external checkers (pure-Python verification only)."""
    return StripContext(policy={"jinja_trim_blocks": "ansible", "powershell_strip": True})


@pytest.fixture
def ctx_both():
    return StripContext(policy={"jinja_trim_blocks": "both", "powershell_strip": True})


@pytest.fixture
def fixtures_dir():
    return REPO_ROOT / "tests" / "fixtures" / "prodgen"
