"""Layout: the defaults of the stages are subfolders of the install dir, overrides win."""

from __future__ import annotations

from pathlib import Path

import pytest

from yofunscripter.pipeline import funscript_common, paths, scenedetect_run

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def restore_layout():
    yield
    paths.configure(root=ROOT)


def test_defaults_are_relative_to_the_install_dir(tmp_path):
    lay = paths.configure(root=tmp_path)
    assert lay.scenes_dir == tmp_path / "scenes"
    assert lay.scripts_dir == tmp_path / "scripts"
    assert lay.result_dir == tmp_path / "result"
    assert lay.work_dir == tmp_path / "work"
    assert lay.model_path.name == "best.pt"


def test_overrides_win(tmp_path):
    lay = paths.configure(root=tmp_path, scenes_dir=tmp_path / "s", scripts_dir="D:/x",
                          result_dir=tmp_path / "r", model_path=tmp_path / "m.pt")
    assert lay.scenes_dir == tmp_path / "s"
    assert lay.scripts_dir == Path("D:/x")
    assert lay.result_dir == tmp_path / "r"
    assert lay.model_path == tmp_path / "m.pt"


def test_pipeline_roots_follow_the_layout(tmp_path):
    paths.configure(root=tmp_path)
    assert funscript_common.ROOT == tmp_path
    assert scenedetect_run.ROOT == tmp_path


def test_bundled_configs_are_resolved():
    lay = paths.configure(root=ROOT)
    assert lay.resources == ROOT
    assert paths.scenes_config().is_file()
    assert paths.funscript_config().is_file()
    assert paths.classes_config().is_file()
    assert lay.ffmpeg_bin.endswith("ffmpeg.exe") or lay.ffmpeg_bin == "ffmpeg"


def test_model_path_resolves_relative_weights():
    paths.configure(root=ROOT)
    cfg = {"weights": "models/best.pt"}
    assert paths.model_path(cfg) == ROOT / "models" / "best.pt"


def test_model_path_keeps_absolute_weights(tmp_path):
    paths.configure(root=ROOT)
    other = tmp_path / "other.pt"
    assert paths.model_path({"weights": str(other)}) == other


def test_layout_is_cached_until_configured():
    assert paths.layout() is paths.layout()
