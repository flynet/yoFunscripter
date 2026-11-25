"""Merge selection: the wave filter, tick-rate ordering, the empty script, the modes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yofunscripter.pipeline import funscript_select as sel


def _sidecar(path: Path, waves: int, ticks: int, rate: float = 1.0) -> Path:
    payload = {"metadata": {"waves": waves, "wave_rate": rate},
               "actions": [{"at": i * 100, "pos": 50} for i in range(ticks)]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture
def clips(tmp_path, monkeypatch):
    """Three sidecars; durations are fixed, so no video is decoded in the test."""
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    for name in ("a", "b", "c"):
        (clips_dir / (name + ".mp4")).write_bytes(b"")
    sidecars = [_sidecar(tmp_path / "a.funscript", 5, 100),
                _sidecar(tmp_path / "b.funscript", 9, 20),
                _sidecar(tmp_path / "c.funscript", 2, 50)]
    monkeypatch.setattr(sel, "video_duration_ms", lambda _clip: 10_000)
    return clips_dir, sidecars


def test_min_waves_filter(clips):
    clips_dir, sidecars = clips
    rows = sel.select(sidecars, 3, 0, sel.SORT_KEEP, clips_dir)
    kept = [r["name"] for r in rows if r["status"] == "kept"]
    skipped = {r["name"]: r["reason"] for r in rows if r["status"] == "skip"}
    assert kept == ["a", "b"]
    assert "min 3" in skipped["c"]
    assert [r["order"] for r in rows if r["status"] == "kept"] == [1, 2]


def test_min_waves_zero_keeps_everything(clips):
    clips_dir, sidecars = clips
    rows = sel.select(sidecars, 0, 0, sel.SORT_KEEP, clips_dir)
    assert len([r for r in rows if r["status"] == "kept"]) == 3


def test_max_waves(clips):
    clips_dir, sidecars = clips
    rows = sel.select(sidecars, 0, 5, sel.SORT_KEEP, clips_dir)
    assert [r["name"] for r in rows if r["status"] == "kept"] == ["a", "c"]


def test_empty_script_is_skipped(clips, tmp_path):
    clips_dir, sidecars = clips
    empty = _sidecar(tmp_path / "d.funscript", 7, 0)
    (clips_dir / "d.mp4").write_bytes(b"")
    rows = sel.select(sidecars + [empty], 0, 0, sel.SORT_KEEP, clips_dir)
    row = next(r for r in rows if r["name"] == "d")
    assert row["status"] == "skip" and row["reason"] == "empty_script"


def test_order_modes(clips):
    clips_dir, sidecars = clips
    tick = [r["name"] for r in sel.select(sidecars, 0, 0, sel.SORT_TICK_RATE, clips_dir)
            if r["status"] == "kept"]
    asc = [r["name"] for r in sel.select(sidecars, 0, 0, sel.SORT_WAVES_ASC, clips_dir)
           if r["status"] == "kept"]
    desc = [r["name"] for r in sel.select(sidecars, 0, 0, sel.SORT_WAVES_DESC, clips_dir)
            if r["status"] == "kept"]
    keep = [r["name"] for r in sel.select(sidecars, 0, 0, sel.SORT_KEEP, clips_dir)
            if r["status"] == "kept"]
    # tick rate: b = 2.0, c = 5.0, a = 10.0 ticks/s
    assert tick == ["b", "c", "a"]
    assert asc == ["c", "a", "b"]
    assert desc == ["b", "a", "c"]
    assert keep == ["a", "b", "c"]


def test_random_is_reproducible(clips):
    clips_dir, sidecars = clips
    one = [r["name"] for r in sel.select(sidecars, 0, 0, sel.SORT_RANDOM, clips_dir)
           if r["status"] == "kept"]
    two = [r["name"] for r in sel.select(sidecars, 0, 0, sel.SORT_RANDOM, clips_dir)
           if r["status"] == "kept"]
    assert one == two
    assert sorted(one) == ["a", "b", "c"]


def test_unknown_mode_raises(clips):
    clips_dir, sidecars = clips
    with pytest.raises(ValueError):
        sel.select(sidecars, 0, 0, "shuffle", clips_dir)
