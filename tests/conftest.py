"""Shared setup: the source tree is importable and the app roots are the repository.

The tests must reach the modules the same way a development run does: `src` on the path,
the install dir = repo root, the bundled configs and model of the checkout.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

from yofunscripter.pipeline import paths


@pytest.fixture(scope="session", autouse=True)
def repo_layout():
    """Resolve the layout once: bundled ffmpeg/ffprobe if present, repo root as install."""
    return paths.configure(root=ROOT)
