import pathlib

# production 생성 tree 위에 tests/ 를 얹어 돌리는 G14 overlay 에는 scripts/ai/ 가 없다(forbidden). 그때 이 패키지의 import 가
# 수집 단계에서 깨지지 않도록 수집 자체를 건너뛴다 — 표식(-m)은 import 뒤에나 평가되기 때문이다.
import pathlib as _pathlib
if not (_pathlib.Path(__file__).resolve().parents[3] / "scripts" / "ai" / "prodgen").is_dir():
    collect_ignore_glob = ["test_*.py"]
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
