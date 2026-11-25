"""Rule of the funscript folder: a `.funscript` is paired by name, and must be fresh.

The merge reads the clips in place, so the track must describe the clip that is on disk
now. A re-cut clip (same name, new mtime) makes its track old: the pair is dropped, and
the merge says what the user must run — stage 2. No video is decoded in these tests.
"""

from __future__ import annotations

import os
from pathlib import Path

from yofunscripter.pipeline.merge_stage import MergeOptions, pair_sidecars


def _file(path: Path, mtime: float) -> Path:
    """A file with an exact modification time, so the freshness rule is tested by clock."""
    path.write_text("x", encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def _dirs(tmp_path: Path) -> tuple[Path, Path, MergeOptions]:
    clips = tmp_path / "scenes"
    scripts = tmp_path / "funscript"
    clips.mkdir()
    scripts.mkdir()
    return clips, scripts, MergeOptions(clips, scripts, tmp_path / "result")


def test_track_is_paired_by_name(tmp_path):
    clips, scripts, opts = _dirs(tmp_path)
    a = _file(clips / "input-s001.mp4", 1000.0)
    b = _file(clips / "input-s002.mp4", 1000.0)
    fresh = _file(scripts / "input-s002.funscript", 1001.0)
    logs: list[str] = []
    sidecars, missing, stale = pair_sidecars(opts, [a, b], logs.append)
    assert sidecars == [fresh]
    assert (missing, stale) == (1, 0)
    # the log names the clip and the folder, in the language of the window
    assert any("input-s001.mp4" in line and "funscript" in line for line in logs)


def test_old_track_is_dropped_and_counted(tmp_path):
    clips, scripts, opts = _dirs(tmp_path)
    a = _file(clips / "input-s001.mp4", 2000.0)
    _file(scripts / "input-s001.funscript", 1000.0)     # older than the clip
    logs: list[str] = []
    sidecars, missing, stale = pair_sidecars(opts, [a], logs.append)
    assert sidecars == []
    assert (missing, stale) == (0, 1)
    # the line says what to do: recompute in stage 2
    assert any("2" in line for line in logs)


def test_missing_folder_is_reported(tmp_path):
    clips, scripts, opts = _dirs(tmp_path)
    a = _file(clips / "input-s001.mp4", 1000.0)
    logs: list[str] = []
    sidecars, missing, stale = pair_sidecars(opts, [a], logs.append)
    assert sidecars == [] and (missing, stale) == (1, 0)
    assert any(str(scripts) in line for line in logs)
