import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

# production 생성 tree 위에 tests/ 를 얹어 돌리는 G14 overlay 에는 scripts/ai/ 가 없다(forbidden). 그 환경에서는 이 패키지의
# 테스트 수집 자체를 건너뛴다 — 표식(-m)은 import 뒤에나 평가되고, conftest 의 import 가 먼저 깨지기 때문이다.
_PRODGEN_PRESENT = (REPO_ROOT / "scripts" / "ai" / "prodgen").is_dir()
if _PRODGEN_PRESENT:
    from scripts.ai.prodgen.strip import StripContext  # noqa: E402
else:
    collect_ignore_glob = ["test_*.py"]
    StripContext = None  # fixtures 는 수집되지 않으므로 쓰이지 않는다


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
