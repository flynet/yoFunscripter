"""Stage 2: clips -> `.funscript` sidecars.

Same pipeline as `funscript_run.py` (track -> signal -> build), with two GUI additions:
sidecars are written to a separate scripts directory (videos stay in the scenes
directory), and the frame loop reports progress, so the bar tracks real work.

The algorithm is untouched: model loaded once for the whole run, per clip
`track_clip` -> `signal_artifacts` -> `build_clip`, gates and checks exactly as in yolo.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .funscript_build import build_clip
from .funscript_common import (TRACK_COLUMNS, frame_ms_of, load_config, load_model,
                               sha1_short, video_duration_ms, video_fps_frames, write_rows)
from .funscript_signal import signal_artifacts
from .funscript_track import track_clip
from .paths import layout, model_path
from .progress import ProgressMeter

SUMMARY_COLUMNS = ("clip", "sidecar", "format", "status", "ticks", "duration_ms",
                   "tracks", "chosen_track", "chosen_class", "segment_start", "segment_end",
                   "amplitude_px", "coverage", "periodicity", "period_ms", "update_ratio",
                   "waves", "wave_rate", "reason",
                   "model_version", "elapsed_s")

FORMAT_NAME = "funscript"


@dataclass
class ScriptsOptions:
    source: Path
    scripts_dir: Path
    pattern: str = "*.mp4"
    device: str = "auto"
    force: bool = False
    limit: int = 0
    points: bool = True
    threads: int = 1
    #: YOLO weights chosen in the settings, `None` = the bundled model of the layout.
    weights: Path | None = None


def load_funscript_config(cfg_path: Path | None = None) -> dict:
    """funscript.yaml with ffmpeg/ffprobe resolved to the bundled binaries."""
    cfg = load_config(cfg_path)
    lay = layout()
    cfg["ffmpeg_bin"] = lay.ffmpeg_bin
    cfg["ffprobe_bin"] = lay.ffprobe_bin
    return cfg


def list_clips(opts: ScriptsOptions) -> list[Path]:
    clips = sorted(q for q in opts.source.glob(opts.pattern) if q.is_file())
    if opts.limit:
        clips = clips[:opts.limit]
    return clips


def sidecar_of(clip: Path, scripts_dir: Path) -> Path:
    return scripts_dir / (clip.stem + ".funscript")


def sidecar_current(clip: Path, scripts_dir: Path) -> bool:
    """Sidecar is valid only if it is **newer** than the clip (yolo rule): a replaced
    clip (same name, new mtime) must be regenerated, otherwise the merge would pair the
    new video with the old graph."""
    sc = sidecar_of(clip, scripts_dir)
    return sc.is_file() and sc.stat().st_mtime >= clip.stat().st_mtime


def plan(opts: ScriptsOptions) -> list[dict]:
    """Dry plan: which clips will be generated, which are skipped."""
    clips = list_clips(opts)
    rows = []
    for clip in clips:
        sc = sidecar_of(clip, opts.scripts_dir)
        frames = video_fps_frames(clip)[1]
        rows.append({"clip": str(clip), "sidecar": str(sc), "frames": frames,
                     "status": "skip" if sidecar_current(clip, opts.scripts_dir) else "todo"})
    return rows


def run(cfg: dict, opts: ScriptsOptions, *, on_progress=None, on_log=None) -> dict:
    """Generate sidecars for all clips; `on_progress(done_frames, total_frames)`.

    Units are frames, so a single long clip moves the bar, not only a finished file.
    """
    clips = list_clips(opts)
    if not clips:
        raise ValueError(f"no clips in {opts.source} ({opts.pattern})")

    weights = Path(opts.weights) if opts.weights else model_path(cfg)
    if not weights.is_file():
        raise ValueError(f"model {weights} not found")

    frames_of = {c: video_fps_frames(c)[1] for c in clips}
    total_frames = sum(frames_of.values())
    meter = ProgressMeter(total_frames, on_progress) if on_progress else None
    model_version = sha1_short(weights)

    todo = [c for c in clips if opts.force or not sidecar_current(c, opts.scripts_dir)]
    opts.scripts_dir.mkdir(parents=True, exist_ok=True)
    if on_log is not None:
        on_log(f"clips {len(clips)}, to generate {len(todo)}, weights "
               f"{weights.name} sha1 {model_version}")

    device = _device(opts.device, on_log)
    model, device = load_model(weights, device)
    if opts.threads and opts.threads > 1:
        try:
            import torch
            torch.set_num_threads(int(opts.threads))
        except Exception:
            pass

    rows: list[dict] = []
    t_start = time.time()
    for i, clip in enumerate(clips, 1):
        sidecar = sidecar_of(clip, opts.scripts_dir)
        if not opts.force and sidecar_current(clip, opts.scripts_dir):
            meter.set(str(clip), frames_of[clip]) if meter else None
            rows.append(_skip_row(clip, sidecar, model_version))
            if on_log is not None:
                on_log(f"[{i}/{len(clips)}] {clip.name}: skip (sidecar current)")
            continue
        t0 = time.time()
        try:
            def on_frame(done: int, total: int) -> None:
                if meter is not None:
                    meter.set(str(clip), done)
            duration_ms = video_duration_ms(clip)
            r = track_clip(clip, cfg, model, device, opts.points, quiet=True,
                           on_frame=on_frame)
            out_dir = layout().work_dir / "funscript" / clip.stem
            write_rows(out_dir / "track.csv", TRACK_COLUMNS, r["rows"])
            if opts.points:
                write_rows(out_dir / "points.csv",
                           ("frame", "ms", "track_id", "x", "y", "good"), r["point_rows"])
            frame_ms = frame_ms_of(r["rows"])
            fusion = signal_artifacts(cfg, clip, r["rows"], duration_ms, frame_ms)
            row = build_clip(cfg, clip, fusion, duration_ms, model_version, write=True,
                             sidecar_dir=opts.scripts_dir)
            ticks = row.pop("tick_list")
            row.update({"status": "done" if ticks else "empty",
                        "tracks": len(fusion["tracks"]),
                        "elapsed_s": round(time.time() - t0, 2)})
            rows.append(row)
            if meter is not None:
                meter.set(str(clip), frames_of[clip])
            if on_log is not None:
                on_log(f"[{i}/{len(clips)}] {clip.name}: ticks {row['ticks']}, track "
                       f"{row['chosen_track']} ({row['chosen_class']}), "
                       f"{row['elapsed_s']} s" + (f" -> {row['reason']}" if row["reason"] else ""))
        except Exception as exc:            # one bad clip does not kill the batch
            rows.append(_error_row(clip, sidecar, model_version, exc,
                                   round(time.time() - t0, 2)))
            if meter is not None:
                meter.set(str(clip), frames_of[clip])
            if on_log is not None:
                on_log(f"[{i}/{len(clips)}] {clip.name}: ERROR "
                       f"{type(exc).__name__}: {exc}")

    if meter is not None:
        meter.finish()

    write_rows(layout().work_dir / "funscript" / "summary.csv", SUMMARY_COLUMNS, rows)
    done = sum(1 for r in rows if r["status"] == "done")
    empty = sum(1 for r in rows if r["status"] == "empty")
    skipped = sum(1 for r in rows if r["status"] == "skip")
    errors = sum(1 for r in rows if r["status"] == "error")
    elapsed = time.time() - t_start
    summary = {"clips": len(rows), "done": done, "empty": empty, "skipped": skipped,
               "errors": errors, "elapsed_s": round(elapsed, 1),
               "scripts_dir": str(opts.scripts_dir),
               "report": str(layout().work_dir / "funscript" / "summary.csv")}
    if on_log is not None:
        on_log(f"clips {len(rows)}: written {done}, empty {empty}, skipped {skipped}, "
               f"errors {errors}, {elapsed:.0f} s -> {opts.scripts_dir}")
    return summary


def _device(name: str, on_log=None):
    """Settings device -> the device argument of `load_model` (auto = GPU if available).

    `cuda` in a build whose torch is CPU-only has no CUDA device: ultralytics answers the
    big `Invalid CUDA 'device=0'` error on every clip. The device is resolved once at the
    start of the stage, so the stage says the truth in one line and runs on the CPU.
    """
    import torch

    if name in ("auto", ""):
        return None
    if name == "cpu":
        return "cpu"
    if not torch.cuda.is_available():
        if on_log is not None:
            on_log("CUDA в этой сборке недоступна (torch без CUDA) → генерация на CPU")
        return "cpu"
    return 0


def _skip_row(clip: Path, sidecar: Path, model_version: str) -> dict:
    return dict.fromkeys(SUMMARY_COLUMNS, "") | {"clip": str(clip), "sidecar": str(sidecar),
                                                 "format": FORMAT_NAME, "status": "skip",
                                                 "reason": "sidecar current",
                                                 "model_version": model_version}


def _error_row(clip: Path, sidecar: Path, model_version: str, exc: Exception,
              elapsed: float) -> dict:
    return dict.fromkeys(SUMMARY_COLUMNS, "") | {
        "clip": str(clip), "sidecar": str(sidecar), "format": FORMAT_NAME,
        "status": "error", "reason": f"{type(exc).__name__}: {exc}",
        "model_version": model_version, "elapsed_s": elapsed}
