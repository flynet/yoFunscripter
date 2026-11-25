"""Stage 1: source videos -> scene segments.

Thin GUI-facing wrapper over the vendored `scenedetect_run` (same algorithm, same
parameters from `configs/scenes.yaml`): scene detection by PySceneDetect as a library,
cutting by one ffmpeg process per scene (`-ss` before `-i` with the source's first-pts
offset, `-frames:v` = scene length + head + tail), post-trim of the AAC tail, and the
clip checks against the ScriptPlayer reference.

The wrapper adds only reporting: a plan (dry) and a progress meter in seconds of source
video, split 15% detection / 85% ffmpeg cut, so the progress bar tracks real duration.
"""
from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from . import scenedetect_run as sd
from .cancel import Cancelled, CancelToken
from .paths import layout
from .progress import ProgressMeter
from .no_window import run as bg_run
from yofunscripter.i18n import tr

DETECT_WEIGHT = 0.15
CUT_WEIGHT = 0.85

#: The console words for a status: a person reads «cut»/«нарезан», not the code token.
STATUS_KEYS = {sd.ST_CUT: "status_cut", sd.ST_SINGLE: "status_single",
               sd.ST_SKIP: "status_skip", sd.ST_ERROR: "status_error"}

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".webm")


@dataclass
class ScenesOptions:
    source: Path
    out_dir: Path
    pattern: str = "*.mp4"
    jobs: int = 1
    force: bool = False
    limit: int = 0
    no_check: bool = False
    device: str = "auto"


def load_scenes_config(cfg_path: Path | None = None) -> dict:
    """scenes.yaml with ffmpeg/ffprobe resolved to the bundled binaries."""
    cfg = sd.load_config(cfg_path)
    lay = layout()
    cfg["ffmpeg"] = lay.ffmpeg_bin
    cfg["ffprobe"] = lay.ffprobe_bin
    return cfg


def cut_vcodec(cfg: dict, device: str) -> tuple[str, str]:
    """Энкод реза из устройства из настроек: cuda -> NVENC, иначе/авто -> libx264.

    NVENC даёт GPU-энкод клипа, и один процесс ffmpeg режет N сцен = N параллельных
    сессий; лимит сессий GeForce проверяется на число сцен в `pick_vcodec`. `auto`
    остаётся на CPU: GPU-энкод включается только когда пользователь выбрал cuda.
    """
    if str(device).strip().lower() == "cuda":
        cfg["vcodec"] = "h264_nvenc"
        return "h264_nvenc", tr("cut_gpu")
    cfg["vcodec"] = "libx264"
    return "libx264", tr("cut_cpu")


def duration_s(cfg: dict, video: Path) -> float:
    """Duration of a source video in seconds (ffprobe, no decoding)."""
    proc = bg_run([cfg["ffprobe"], "-v", "error", "-show_entries", "format=duration",
                   "-of", "default=noprint_wrappers=1", str(video)],
                  capture_output=True)
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        if "=" in line:
            key, val = line.split("=", 1)
            if key.strip() == "duration":
                try:
                    return float(val.strip())
                except ValueError:
                    return 0.0
    return 0.0


def plan(cfg: dict, opts: ScenesOptions, scenes_dir: Path) -> list[dict]:
    """Dry plan: what each video will do (detect / cut / skip), same rules as the CLI."""
    videos = list_videos(opts)
    rows = []
    for v in videos:
        row = sd.plan_row(v, cfg, opts.out_dir, scenes_dir)
        row["duration_s"] = round(duration_s(cfg, v), 2)
        rows.append(row)
    return rows


def list_videos(opts: ScenesOptions) -> list[Path]:
    videos = sorted(q for q in opts.source.glob(opts.pattern) if q.is_file())
    if opts.limit:
        videos = videos[:opts.limit]
    return videos


def run(cfg: dict, opts: ScenesOptions, *, on_progress=None, on_log=None,
        token: "CancelToken | None" = None) -> dict:
    """Cut all videos of `opts.source` into `opts.out_dir`; returns the run summary.

    `on_progress(done_units, total_units)` — units are seconds of source video.
    `on_log(line)` — one line per video, in the language of the window.
    `token` — the user's Cancel: the ffmpeg of each video is registered in it, and
    `Cancelled` leaves the stage at the next loop boundary, so nothing is written after
    the stop.
    """
    videos = list_videos(opts)
    if not videos:
        raise ValueError(tr("no_videos", dir=opts.source, pattern=opts.pattern))

    by_stem: dict[str, list[Path]] = {}
    for v in videos:
        by_stem.setdefault(v.stem, []).append(v)
    dupes = {k: v for k, v in by_stem.items() if len(v) > 1}
    if dupes:
        raise ValueError(tr("stage1_collisions", count=len(dupes), dir=opts.out_dir,
                           list="; ".join(f"{k} -> {[str(q) for q in v]}"
                                          for k, v in dupes.items())))

    scenes_dir = layout().work_dir / "scenes"
    stats_dir = layout().work_dir / "scenes" / "runs"
    durations = {v: duration_s(cfg, v) for v in videos}
    total_s = sum(durations.values())
    meter = ProgressMeter(total_s, on_progress) if on_progress else None

    scenes_dir.mkdir(parents=True, exist_ok=True)
    opts.out_dir.mkdir(parents=True, exist_ok=True)

    codec, note = cut_vcodec(cfg, opts.device)
    if on_log is not None:
        on_log(note)

    a = argparse.Namespace(force=opts.force, cut_only=False, detect_only=False,
                           no_check=opts.no_check)
    jobs = max(1, int(opts.jobs))
    rows: list[dict] = []
    t_start = time.time()

    def hooks(video: Path):
        def on_phase(phase: str) -> None:
            if meter is not None and phase == "detect":
                meter.set(str(video), DETECT_WEIGHT * durations[video])

        def on_cut(seconds: float) -> None:
            if meter is None:
                return
            dur = durations[video]
            share = CUT_WEIGHT * min(seconds, dur) if dur > 0 else CUT_WEIGHT * dur
            meter.set(str(video), DETECT_WEIGHT * dur + share)

        return on_phase, on_cut

    cancelled = False
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futs = {}
        for v in videos:
            on_phase, on_cut = hooks(v)
            futs[pool.submit(sd.process, v, cfg, opts.out_dir, scenes_dir, a,
                             on_phase, on_cut, token)] = v
        done = 0
        for fut in as_completed(futs):
            v = futs[fut]
            try:
                row = fut.result()
            except Cancelled:
                # the user stopped the run: every ffmpeg is already terminated, so the
                # rest of the pool unwinds at once; the stage reports the cancel itself
                cancelled = True
                break
            except Exception as exc:            # one bad video does not kill the batch
                row = dict(sd.EMPTY_ROW, video=str(v), stem=v.stem,
                           scene_list=str(scenes_dir / sd.list_of(v.stem, cfg)),
                           status=sd.ST_ERROR, reason=f"{type(exc).__name__}: {exc}")
            if meter is not None:
                meter.set(str(v), (DETECT_WEIGHT + CUT_WEIGHT) * durations[v])
            rows.append(row)
            done += 1
            if on_log is not None:
                on_log(tr("stage1_video", done=done, total=len(videos), name=v.name,
                          status=tr(STATUS_KEYS.get(row["status"], row["status"])),
                          scenes=row["scenes"], files=row["out_files"],
                          detect=row["detect_s"], cut=row["cut_s"],
                          reason=" " + row["reason"] if row["reason"] else ""))

    if cancelled:
        if meter is not None:
            meter.finish()
        raise Cancelled()

    if meter is not None:
        meter.finish()

    rows.sort(key=lambda r: r["video"])
    stats_path = stats_dir / "stats.csv"
    sd.write_rows(stats_path, sd.STATS_COLUMNS, rows)

    cut = sum(1 for r in rows if r["status"] == sd.ST_CUT)
    single = sum(1 for r in rows if r["status"] == sd.ST_SINGLE)
    skipped = sum(1 for r in rows if r["status"] == sd.ST_SKIP)
    errors = sum(1 for r in rows if r["status"] == sd.ST_ERROR)
    files = sum(int(r["out_files"]) for r in rows if str(r["out_files"]).isdigit())
    elapsed = time.time() - t_start
    summary = {"videos": len(rows), "cut": cut, "single": single, "skipped": skipped,
               "errors": errors, "files": files, "elapsed_s": round(elapsed, 1),
               "out_dir": str(opts.out_dir), "report": str(stats_path)}
    if on_log is not None:
        on_log(tr("stage1_summary", videos=len(rows), cut=cut, single=single,
                  skipped=skipped, errors=errors, files=files,
                  elapsed=f"{elapsed:.0f}", out=opts.out_dir))
    return summary
