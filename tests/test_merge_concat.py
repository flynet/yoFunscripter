"""Merge: the clips must already be in the target format, and the concat copies nothing.

Qt-free, no ffmpeg is launched: `run_ffmpeg` is stubbed, so the tests read the command and
the list file the merge writes, and check the clip rules the merge refuses to fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yofunscripter.pipeline import funscript_concat as fc
from yofunscripter.pipeline import merge_stage
from yofunscripter.pipeline import scenedetect_run as sd
from yofunscripter.pipeline.cancel import Cancelled
from yofunscripter.pipeline.merge_stage import CONCAT_WEIGHT, MergeOptions, PROBE_WEIGHT, \
    gui_config, list_clips


def cfg() -> dict:
    """Merge cfg: the targets come from scenes.yaml, as in the app."""
    scenes = sd.load_config()
    fun = fc.load_config()
    out = dict(fun)
    for key in ("target_fps", "target_width", "target_height", "audio", "audio_rate"):
        out[key] = scenes[key]
    out["video_track_timescale"] = scenes["timescale"]
    return out


def info(**kw) -> dict:
    """One clip's `probe` result, in the target format, with one field changed."""
    c = cfg()
    base = {"vcodec": "h264", "width": int(c["target_width"]),
            "height": int(c["target_height"]), "r_fps": float(c["target_fps"]),
            "fps": float(c["target_fps"]), "pix_fmt": "yuv420p",
            "timescale": int(c["video_track_timescale"]),
            "acodec": "aac", "sample_rate": int(c["audio_rate"]), "channels": 2,
            "duration_ms": 1000, "video_ms": 1000, "frames": int(c["target_fps"])}
    base.update(kw)
    return base


def pairs(*infos: dict) -> list[tuple[Path, dict]]:
    return [(Path(f"clip-{k}.mp4"), info) for k, info in enumerate(infos, 1)]


def test_matching_clips_are_accepted():
    assert fc.check_concat_inputs(pairs(info(), info()), cfg()) == []


def test_a_clip_that_is_not_normalized_is_refused():
    c = cfg()
    bad = [
        info(vcodec="hevc"),
        info(width=1280, height=720),
        info(r_fps=23.976),
        info(pix_fmt="yuv420p10"),
        info(timescale=15360),
        info(acodec=None),
        info(acodec="mp3"),
        info(sample_rate=44100),
        info(channels=1),
        info(duration_ms=1030, video_ms=1000),
    ]
    problems = fc.check_concat_inputs(pairs(*bad), c)
    assert len(problems) == len(bad)
    assert any("h264" in p for p in problems)
    assert any("target_fps" in p for p in problems)
    assert any("пост-трим" in p for p in problems)


def test_a_video_without_sound_is_only_a_problem_when_the_config_wants_audio():
    c = {**cfg(), "audio": False}
    assert fc.check_concat_inputs(pairs(info(acodec=None)), c) == []


def test_concat_reads_the_clips_in_place(tmp_path: Path, monkeypatch):
    """The clips dir keeps its files, the merge writes only the list and the final mp4."""
    clips_dir = tmp_path / "scenes"
    clips_dir.mkdir()
    clips = [clips_dir / f"v-{i}.mp4" for i in (1, 2)]
    for c in clips:
        c.write_bytes(b"x")
    scratch = tmp_path / "work" / "concat"
    out = tmp_path / "result" / "final.mp4"
    seen: list[list[str]] = []
    monkeypatch.setattr(fc, "run_ffmpeg",
                        lambda cmd, cfg, on_s, prog, token=None: seen.append(cmd))
    lst = fc.concat(clips, out, cfg(), None, scratch)
    assert lst.parent == scratch
    text = lst.read_text(encoding="utf-8")
    assert text == "".join(f"file '{p.as_posix()}'\n" for p in clips)
    cmd = seen[0]
    assert cmd[cmd.index("-c") + 1] == "copy"
    assert cmd[cmd.index("-i") + 1] == str(lst)
    assert cmd[-1] == str(out)
    assert "-fflags" in cmd and "+genpts" in cmd
    assert "-movflags" in cmd and "+faststart" in cmd
    # no segment copies, no temp files: the clips dir is untouched
    assert sorted(p.name for p in clips_dir.iterdir()) == ["v-1.mp4", "v-2.mp4"]
    assert not (scratch / "v-1.mp4").exists()


def test_merge_targets_come_from_the_cut_config(tmp_path: Path):
    """The merge checks the same numbers the cut normalizes to, not its own copy."""
    scenes = sd.load_config()
    opts = MergeOptions(clips_dir=tmp_path / "scenes", scripts_dir=tmp_path / "scripts",
                       out_dir=tmp_path / "result")
    merged = gui_config(fc.load_config(), opts)
    for key in ("target_fps", "target_width", "target_height", "audio", "audio_rate"):
        assert merged[key] == scenes[key]
    assert merged["video_track_timescale"] == scenes["timescale"]
    assert merged["result_dir"] == str(opts.out_dir)
    assert merged["out_dir"] != str(opts.out_dir)      # artifacts live in the work dir


def test_list_clips_ignores_directories(tmp_path: Path):
    opts = MergeOptions(clips_dir=tmp_path, scripts_dir=tmp_path, out_dir=tmp_path)
    (tmp_path / "b.mp4").write_bytes(b"x")
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "sub.mp4").mkdir()
    assert [p.name for p in list_clips(opts)] == ["a.mp4", "b.mp4"]


def test_progress_weights_sum_to_the_whole_run():
    # the merge is one concat, so the bar is mostly the concat and a little the probes
    assert PROBE_WEIGHT + CONCAT_WEIGHT == 1.0


def test_run_turns_ffmpeg_failure_into_one_line(monkeypatch, tmp_path: Path):
    """`SystemExit` of the vendored code is a `ValueError` the worker shows as a reason."""
    opts = MergeOptions(clips_dir=tmp_path, scripts_dir=tmp_path, out_dir=tmp_path)
    monkeypatch.setattr(merge_stage, "_run",
                        lambda cfg, o, **kw: (_ for _ in ()).throw(SystemExit("ffmpeg code 1")))
    with pytest.raises(ValueError, match="ffmpeg code 1"):
        merge_stage.run({}, opts)


def test_run_does_not_swallow_the_cancel(monkeypatch, tmp_path: Path):
    opts = MergeOptions(clips_dir=tmp_path, scripts_dir=tmp_path, out_dir=tmp_path)
    monkeypatch.setattr(merge_stage, "_run",
                        lambda cfg, o, **kw: (_ for _ in ()).throw(Cancelled()))
    with pytest.raises(Cancelled):
        merge_stage.run({}, opts)
