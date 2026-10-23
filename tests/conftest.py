import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# the bot from this checkout; the library installed, or cloned next to it (../fragment-web-api)
for path in (ROOT.parent / "fragment-web-api", ROOT):
    if path.is_dir() and str(path) not in sys.path:
        sys.path.insert(0, str(path))

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    path = FIXTURES / name
    if name.endswith(".json"):
        return json.loads(path.read_text(encoding="utf-8"))
    return path.read_text(encoding="utf-8")
