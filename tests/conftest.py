import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

CORPUS = ROOT / "samples" / "corpus"


@pytest.fixture(scope="session", autouse=True)
def corpus():
    if not CORPUS.exists():
        sys.path.insert(0, str(ROOT / "samples"))
        import generate
        generate.main()
    return CORPUS
