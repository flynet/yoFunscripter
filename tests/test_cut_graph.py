"""The cut graph: one ffmpeg process per chunk of scenes, frame-accurate trim, one normalization.

Qt-free, no ffmpeg is launched: the tests check the command text (graph, flags, outputs),
which is what the real process runs, and that the chunk commands stay under the Windows
CreateProcess limit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from yofunscripter.pipeline import scenedetect_run as sd

ROWS = [{"Start Frame": 101, "End Frame": 301, "Length (frames)": 200},
        {"Start Frame": 302, "End Frame": 602, "Length (frames)": 300}]


def cfg() -> dict:
    return sd.load_config()


def test_one_split_one_trim_per_scene():
    c = cfg()
    head, tail = int(c["head_frames"]), int(c["tail_frames"])
    graph = sd.build_graph(ROWS, c, 24.0, True)
    assert graph.startswith("[0:v]split=2[v0][v1]")
    # trim:end_frame is exclusive, so the tail is End Frame - 1 + tail + 1
    for i, r in enumerate(ROWS):
        start = max(0, int(r["Start Frame"]) - 1 - head)
        end = int(r["End Frame"]) - 1 + tail + 1
        assert f"[v{i}]trim=start_frame={start}:end_frame={end}" in graph
        assert f"[v{i}]trim" in graph
    assert "setpts=PTS-STARTPTS" in graph
    assert graph.count("[vo0]") == 1 and graph.count("[vo1]") == 1


def test_graph_normalizes_to_the_target_format():
    c = cfg()
    w, h, fps = int(c["target_width"]), int(c["target_height"]), int(c["target_fps"])
    graph = sd.build_graph(ROWS, c, 24.0, True)
    assert f"fps={fps}" in graph            # source 24 -> target 30
    assert f"scale={w}:{h}:force_original_aspect_ratio=decrease" in graph
    assert f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2" in graph
    assert "setsar=1" in graph


def test_no_fps_filter_when_source_is_already_the_target():
    c = cfg()
    graph = sd.build_graph(ROWS, c, float(c["target_fps"]), True)
    assert ",fps=" not in graph


def test_audio_trims_in_seconds_from_the_frame_numbers():
    c = cfg()
    fps = 24.0
    graph = sd.build_graph(ROWS, c, fps, True)
    head, tail = int(c["head_frames"]), int(c["tail_frames"])
    assert graph.startswith("[0:v]split=2[v0][v1];[v0]")
    assert "[0:a]asplit=2[a0][a1]" in graph
    start = max(0, 101 - 1 - head)
    end = 301 - 1 + tail + 1
    assert f"[a0]atrim=start={start / fps:.6f}:end={end / fps:.6f}" in graph
    assert "asetpts=PTS-STARTPTS[ao0]" in graph


def test_graph_is_one_line():
    # ffmpeg reads a trailing newline as garbage
    assert "\n" not in sd.build_graph(ROWS, cfg(), 24.0, True)


def test_cut_cmd_is_one_process_with_all_outputs(tmp_path: Path):
    c = cfg()
    graph = tmp_path / "graph.txt"
    outs = [tmp_path / "a-1.mp4", tmp_path / "a-2.mp4"]
    cmd = sd.cut_cmd(c, Path("a.mp4"), ROWS, outs, graph, True, 24.0, "libx264")
    text = graph.read_text(encoding="utf-8")
    assert text.startswith("[0:v]split=2")
    # the flags are global, then one output block per scene
    assert cmd[:cmd.index("-i")] == [c["ffmpeg"], "-y", "-hide_banner", "-loglevel", "error",
                                     "-nostats", "-reinit_filter", "0"]
    assert cmd[cmd.index("-filter_complex_script") + 1] == str(graph)
    for i, out in enumerate(outs):
        block = cmd[cmd.index(f"[vo{i}]") + 1: cmd.index(str(out))]
        assert block[:2] == ["-c:v", "libx264"]
        assert f"[ao{i}]" in cmd
        assert f"[ao{i}]" in block                      # one audio stream per clip
        # AAC tail trimming happens in the same process: -t Length/fps, no -shortest
        assert block[block.index("-c:a") + 1] == "aac"
        assert block[block.index("-t") + 1] == f"{ROWS[i]['Length (frames)'] / 24.0:.6f}"
        assert block[-1] == "+faststart"      # moov is written in the cut, no second pass
        assert "-shortest" not in block
    assert cmd[-1] == str(outs[-1])
    assert cmd.count("-map") == 4
    # head/tail are applied by the chunk plan, so the graph trims the local frame numbers:
    # scene 1 = frames 100..300 of the chunk, scene 2 = frames 301..601
    assert "[v0]trim=start_frame=100:end_frame=301" in text
    assert "[v1]trim=start_frame=301:end_frame=602" in text
    assert "atrim=start=4.166667:end=12.541667" in text      # 100/24 .. 301/24
    assert "atrim=start=12.541667:end=25.083333" in text     # 301/24 .. 602/24
    assert text.count("fps=30") == 2                        # normalized once, in the cut
    nv = sd.cut_cmd(c, Path("a.mp4"), ROWS, outs, graph, True, 24.0, "h264_nvenc")
    assert nv.count("h264_nvenc") == 2 and cmd.count("h264_nvenc") == 0
    assert nv[nv.index("h264_nvenc") + 1] == "-preset"
    assert nv[nv.index("-profile:v") + 1] == c["profile"]
    assert "-crf" not in nv


def test_cut_cmd_without_audio_is_video_only(tmp_path: Path):
    c = cfg()
    outs = [tmp_path / "a-1.mp4"]
    cmd = sd.cut_cmd(c, Path("a.mp4"), ROWS[:1], outs, tmp_path / "g.txt", False, 24.0,
                     "libx264")
    assert "-an" in cmd
    assert "[ao0]" not in cmd


def test_libx264_runs_one_thread_per_encoder():
    c = cfg()
    args = sd.video_args(c, "libx264")
    assert args[args.index("-threads") + 1] == "1"
    assert args[args.index("-crf") + 1] == str(c["crf"])
    assert args[args.index("-video_track_timescale") + 1] == str(c["timescale"])


def test_nvenc_args_have_no_crf():
    c = cfg()
    args = sd.video_args(c, "h264_nvenc")
    assert "-crf" not in args and "-keyint_min" not in args and "-sc_threshold" not in args
    assert args[args.index("-cq") + 1] == str(c["nvenc_cq"])
    assert args[args.index("-video_track_timescale") + 1] == str(c["timescale"])


def test_nvenc_only_up_to_the_session_limit():
    c = {**cfg(), "vcodec": "h264_nvenc"}
    limit = int(c["nvenc_max_outputs"])
    codec, reason = sd.pick_vcodec(c, limit)
    assert (codec, reason) == ("h264_nvenc", "")
    codec, reason = sd.pick_vcodec(c, limit + 1)
    assert codec == "libx264"
    # the note is in the language of the window: both texts name the numbers
    assert str(limit + 1) in reason and str(limit) in reason
    assert sd.pick_vcodec({**c, "vcodec": "libx264"}, 1) == ("libx264", "")


def big_rows(n: int) -> list[dict]:
    """Scenes of a 2h37m film: n scenes of 200 frames each, contiguous."""
    return [{"Scene Number": i, "Start Frame": i * 200 + 1, "End Frame": i * 200 + 200,
             "Length (frames)": 200} for i in range(1, n + 1)]


def key_list(n: int, fps: float = 30.0, gop: int = 60) -> list[tuple[float, int]]:
    """Keyframe map `keyframe_map` returns: (pts_time, frame number in display order)."""
    return [(i * gop / fps, i * gop) for i in range(n)]


def test_chunk_trim_counts_from_the_seek_keyframe(tmp_path: Path, repo_layout):
    """`-ss` lands on a keyframe <= the scene border, so trim is the distance to the border."""
    c = cfg()
    pts = key_list(1000)                                   # gop 60 at 30 fps = every 2 s
    head, tail = int(c["head_frames"]), int(c["tail_frames"])
    first = sd.plan_chunks(c, Path("v.mp4"), big_rows(1), tmp_path / "out", 30.0,
                           "libx264", True, 0.0, pts)[0]
    # scene 1 border = frame 201 - 1 - head: the last keyframe at or before its pts 6.667 s
    # is 6.0 s = frame 180, so the chunk seeks 6.0 and trims 20 frames
    assert first.seek_s == 6.0 and first.base_frame == 180
    assert first.rows[0]["Start Frame"] - 1 == (201 - 1 - head) - first.base_frame
    assert first.rows[0]["End Frame"] == (400 - 1 + tail) - first.base_frame + 1
    second = sd.plan_chunks(c, Path("v.mp4"), big_rows(2)[1:], tmp_path / "out", 30.0,
                            "libx264", True, 0.0, pts)[0]
    # scene 2 border = frame 400 - head -> pts 13.33 s, keyframe 12.0 s = frame 360
    assert second.seek_s == 12.0 and second.base_frame == 360
    assert second.rows[0]["Start Frame"] - 1 == (401 - 1 - head) - second.base_frame
    assert second.rows[0]["End Frame"] == (600 - 1 + tail) - second.base_frame + 1
    # keyframe map missing (ffprobe failed): the chunk runs from the file head
    assert sd.plan_chunks(c, Path("v.mp4"), big_rows(16), tmp_path / "out", 30.0,
                          "libx264", True, 0.0, [])[0].seek_s is None


def test_chunks_cover_every_scene_exactly_once(tmp_path: Path, repo_layout):
    """Chunks tile the scene list: each clip is encoded by exactly one ffmpeg process."""
    c = cfg()
    rows = big_rows(1623)
    pts = key_list(4800)
    chunks = sd.plan_chunks(c, Path("Project2.mp4"), rows, tmp_path / "Project2", 30.0,
                            "libx264", True, -0.067, pts)
    spans = [(ch.first, ch.last) for ch in chunks]
    assert spans[0][0] == 0 and spans[-1][1] == len(rows) - 1
    for a, b in zip(spans, spans[1:]):
        assert b[0] == a[1] + 1                           # no gap, no overlap
    assert sum(len(ch.rows) for ch in chunks) == len(rows)
    names = [p.name for ch in chunks for p in ch.out_paths]
    assert len(set(names)) == len(rows)
    # every chunk lands on a keyframe at or before its first border, trim = the gap
    for ch in chunks:
        border = int(rows[ch.first]["Start Frame"]) - 1 - int(c["head_frames"])
        assert 0 <= ch.base_frame <= border
        assert int(ch.rows[0]["Start Frame"]) - 1 == border - ch.base_frame


def test_chunk_command_fits_createprocess(tmp_path: Path, repo_layout):
    """A command of 1623 outputs is 330 000 chars: CreateProcess gives WinError 206, 0 files."""
    c = cfg()
    rows = big_rows(1623)
    pts = key_list(4800)
    chunks = sd.plan_chunks(c, Path("Project2.mp4"), rows, tmp_path / "Project2", 30.0,
                            "libx264", True, -0.067, pts)
    assert len(chunks) > 1
    for ch in chunks:
        cmd = sd.cut_cmd(c, Path("Project2.mp4"), ch.rows, ch.out_paths,
                         tmp_path / f"{ch.tag}-graph.txt", True, 30.0, "libx264", ch.seek_s)
        assert len(subprocess.list2cmdline(cmd)) <= sd.CHUNK_CHAR_BUDGET
        assert cmd.count("-filter_complex_script") == 1    # one decode per chunk
        assert len(ch.rows) <= int(c["max_outputs"])


def test_nvenc_chunk_stays_under_the_session_limit(tmp_path: Path, repo_layout):
    """GeForce drops NVENC sessions past `nvenc_max_outputs`, so the chunk is smaller."""
    c = {**cfg(), "vcodec": "h264_nvenc"}
    rows = big_rows(1623)
    pts = [i * 2.0 for i in range(4800)]
    chunks = sd.plan_chunks(c, Path("Project2.mp4"), rows, tmp_path / "Project2", 30.0,
                            "h264_nvenc", True, -0.067, pts)
    assert all(len(ch.rows) <= int(c["nvenc_max_outputs"]) for ch in chunks)
    assert sum(len(ch.rows) for ch in chunks) == len(rows)
