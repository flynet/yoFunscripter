"""The cut graph: one ffmpeg process per video, frame-accurate trim, one normalization.

Qt-free, no ffmpeg is launched: the tests check the command text (graph, flags, outputs),
which is what the real process runs.
"""

from __future__ import annotations

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
        assert cmd[cmd.index(str(out)) - 2] == "-b:a"
    assert cmd[-1] == str(outs[-1])
    assert cmd.count("-map") == 4


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
    assert codec == "libx264" and "лимит сессий" in reason
    assert sd.pick_vcodec({**c, "vcodec": "libx264"}, 1) == ("libx264", "")
