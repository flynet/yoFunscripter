"""Stage 3: clips + sidecars -> one mp4 + one funscript.

Same algorithm as `funscript_video.py`: sidecars -> filter and order -> clip checks ->
tick offsets and seams -> merged funscript -> concat copy -> checks. The clips are read
**in place** with `-c copy`: stage 1 normalizes every clip at the cut (`fps/scale/
timescale/audio` in the cut graph), so the merge encodes nothing, copies nothing, writes
only the final file, and takes seconds instead of minutes of CPU.

GUI additions: videos and sidecars live in different directories (paired by stem through
`clips_dir`), the order is chosen by `sort_mode` (waves asc/desc, keep, random,
tick_rate), and progress is measured in seconds of source video, so the bar tracks real
work.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from . import scenedetect_run as sd
from .cancel import CancelToken
from .funscript_check import check_payload
from .funscript_common import write_rows
from .funscript_concat import (check_concat_inputs, check_final, concat, probe)
from .funscript_merge import (load_order, merged_gap_check, merge_segments, merged_payload,
                              write_merged)
from .funscript_select import SELECTION_COLUMNS, SORT_TICK_RATE, select
from .funscript_video import SUMMARY_COLUMNS
from .paths import layout
from .progress import ProgressMeter

PROBE_WEIGHT = 0.05
CONCAT_WEIGHT = 0.95


@dataclass
class MergeOptions:
    clips_dir: Path
    scripts_dir: Path
    out_dir: Path
    name: str = "result"
    pattern: str = "*.mp4"
    min_waves: int = 3
    max_waves: int = 0
    sort_mode: str = SORT_TICK_RATE
    force: bool = False
    no_check: bool = False


def gui_config(cfg: dict, opts: MergeOptions) -> dict:
    """Config copy with GUI dirs: artifacts in the work dir, final in `opts.out_dir`.

    `load_order`/`write_merged` resolve `out_dir`/`concat_dir`/`result_dir` through the
    layout, so the algorithm functions are reused unchanged. The target format comes from
    `configs/scenes.yaml` (the cut normalizes the clip to it), so the merge check and the
    final check use the same numbers as the cut, not a second copy of them.
    """
    lay = layout()
    scenes = sd.load_config()
    cfg = dict(cfg)
    cfg["out_dir"] = str(lay.work_dir / "funscript")
    cfg["concat_dir"] = str(lay.work_dir / "concat")
    cfg["result_dir"] = str(opts.out_dir)
    cfg["ffmpeg_bin"] = lay.ffmpeg_bin
    cfg["ffprobe_bin"] = lay.ffprobe_bin
    cfg["target_width"] = scenes["target_width"]
    cfg["target_height"] = scenes["target_height"]
    cfg["target_fps"] = scenes["target_fps"]
    cfg["video_track_timescale"] = scenes["timescale"]
    cfg["audio_rate"] = scenes["audio_rate"]
    cfg["audio"] = scenes["audio"]
    return cfg


def list_clips(opts: MergeOptions) -> list[Path]:
    return sorted(q for q in opts.clips_dir.glob(opts.pattern) if q.is_file())


def pair_sidecars(opts: MergeOptions, clips: list[Path], on_log=None) -> list[Path]:
    """Sidecars of `scripts_dir` paired with clips by stem, yolo freshness rule.

    A sidecar is usable only if it is **newer** than the clip: a replaced clip (same name,
    new mtime) must be regenerated, otherwise the merge pairs the new video with the old
    graph.
    """
    sidecars = []
    for clip in clips:
        sc = opts.scripts_dir / (clip.stem + ".funscript")
        if not sc.is_file():
            if on_log is not None:
                on_log(f"{clip.name}: sidecar missing in {opts.scripts_dir}")
            continue
        if sc.stat().st_mtime < clip.stat().st_mtime:
            if on_log is not None:
                on_log(f"{clip.name}: sidecar older than clip — regenerate it in stage 2")
            continue
        sidecars.append(sc)
    return sidecars


def plan(cfg: dict, opts: MergeOptions) -> dict:
    """Dry plan: selection of clips for the merge (nothing is written)."""
    cfg = gui_config(cfg, opts)
    clips = list_clips(opts)
    sidecars = pair_sidecars(opts, clips)
    rows = select(sidecars, opts.min_waves, opts.max_waves, opts.sort_mode, opts.clips_dir)
    kept = [r for r in rows if r["status"] == "kept"]
    total_ms = sum(int(r["duration_ms"]) for r in kept)
    return {"clips": len(clips), "sidecars": len(sidecars), "kept": len(kept),
            "total_ms": total_ms, "rows": rows}


def run(cfg: dict, opts: MergeOptions, *, on_progress=None, on_log=None,
        token: "CancelToken | None" = None) -> dict:
    """`_run` with SystemExit -> ValueError: ffmpeg failures are reported as one line.

    The vendored code raises SystemExit on ffmpeg errors and on "nothing selected"; in the
    app that must not kill the process, so the exception is converted at this boundary.
    `Cancelled` (the user pressed Cancel) passes through untouched.
    """
    try:
        return _run(cfg, opts, on_progress=on_progress, on_log=on_log, token=token)
    except SystemExit as exc:
        raise ValueError(str(exc)) from exc


def _run(cfg: dict, opts: MergeOptions, *, on_progress=None, on_log=None,
         token: "CancelToken | None" = None) -> dict:
    """Check + concat copy + merged funscript; `on_progress(done, total)` in seconds.

    Raises `ValueError` on a blocked run (no clips, nothing selected, locked output,
    clips not matching the target format); `Cancelled` when the user stops the run.
    """
    cfg = gui_config(cfg, opts)
    lay = layout()
    work_dir = lay.work_dir / "funscript"
    concat_dir = lay.work_dir / "concat"
    work_dir.mkdir(parents=True, exist_ok=True)
    concat_dir.mkdir(parents=True, exist_ok=True)
    for legacy in concat_dir.glob("*.mp4"):
        # segments of the old merge (encode at merge time) are pure trash now
        legacy.unlink(missing_ok=True)

    opts.out_dir.mkdir(parents=True, exist_ok=True)

    clips = list_clips(opts)
    if not clips:
        raise ValueError(f"no clips in {opts.clips_dir} ({opts.pattern})")

    t0 = time.time()
    sidecars = pair_sidecars(opts, clips, on_log)
    if not sidecars:
        raise ValueError(f"no sidecars for the clips of {opts.clips_dir} in {opts.scripts_dir}")
    rows = select(sidecars, opts.min_waves, opts.max_waves, opts.sort_mode, opts.clips_dir)
    write_rows(work_dir / "selection.csv", SELECTION_COLUMNS, rows)
    kept = [r for r in rows if r["status"] == "kept"]
    if not kept:
        raise ValueError(f"no clips selected (min_waves {opts.min_waves})")

    dur_s = {r["name"]: int(r["duration_ms"]) / 1000.0 for r in kept}
    total_s = sum(dur_s.values())
    meter = ProgressMeter(total_s, on_progress) if on_progress else None
    if on_log is not None:
        order = ", ".join(r["name"] for r in kept[:6])
        on_log(f"selected {len(kept)} of {len(rows)} clips "
               f"(min_waves {opts.min_waves}, sort {opts.sort_mode}): {order}"
               + (" ..." if len(kept) > 6 else ""))

    # the clips are measured as they are: `concat -c copy` needs identical codec
    # parameters, and the only way to fix a clip that differs is to re-cut it in stage 1
    infos: list[tuple[Path, dict]] = []
    encoded: dict[str, int] = {}
    summary: list[dict] = []
    for r in kept:
        if token is not None:
            token.check()
        clip = Path(r["clip"])
        info = probe(clip, cfg)
        infos.append((clip, info))
        encoded[r["name"]] = int(info["duration_ms"])
        if meter is not None:
            meter.set(r["name"], PROBE_WEIGHT * dur_s[r["name"]])
        summary.append({"order": r["order"], "name": r["name"], "segment_out": str(clip),
                        "sidecar": r["sidecar"], "waves": r["waves"],
                        "wave_rate": r["wave_rate"], "tick_rate": r["tick_rate"],
                        "source_ms": r["duration_ms"], "encoded_ms": encoded[r["name"]],
                        "offset_ms": "", "ticks": r["ticks"],
                        "status": "checked", "reason": ""})

    problems = check_concat_inputs(infos, cfg)
    if problems:
        for line in problems[:12]:
            if on_log is not None:
                on_log(line)
        raise ValueError(f"{len(problems)} clips do not match the target format — clips "
                        f"are normalized at the scene cut, re-cut them in stage 1: "
                        f"{'; '.join(problems[:4])}")

    clip_paths = [Path(r["clip"]) for r in kept]
    target = opts.out_dir / (opts.name + ".mp4")
    if target.exists():
        try:
            with open(target, "ab"):
                pass
        except PermissionError:
            raise ValueError(f"{target} is locked by another process (player): close it "
                             "and run again")

    concat_hook = (lambda sec: meter.set("concat", CONCAT_WEIGHT * min(sec, total_s))
                   if meter is not None else None)
    concat(clip_paths, target, cfg, concat_hook, concat_dir, token)
    if meter is not None:
        meter.set("concat", CONCAT_WEIGHT * total_s)

    info = probe(target, cfg)
    final_ms = info["duration_ms"]
    segments = load_order(opts.name, cfg, encoded)
    merged = merge_segments(segments, cfg)
    if merged and merged[-1]["ms"] != final_ms:
        merged[-1]["ms"] = final_ms
    payload = merged_payload(merged, segments, opts.name, cfg, final_ms)
    sidecar_out = write_merged(payload, merged, segments, opts.name, cfg, final_ms)
    for s in segments:
        row = next(x for x in summary if x["name"] == s["name"])
        row["offset_ms"] = s["offset_ms"]
        row["ticks"] = len(s["ticks"])

    results: list[tuple[bool, str]] = []
    if not opts.no_check:
        results = check_payload(payload, final_ms, cfg, target, skip_gaps=True)
        results.append(merged_gap_check(merged, segments, cfg))
        results += check_final(target, cfg, len(segments))
        results.append((int(merged[-1]["ms"]) == final_ms,
                        f"last tick {merged[-1]['ms']} = video duration {final_ms} ms"))
        src_ticks = sum(len(s["ticks"]) for s in segments)
        drops = sum(int(s.get("seam_drop", 0)) for s in segments)
        added = sum(int(s.get("seam_phase", 0)) for s in segments)
        seams = len(segments) - 1
        per_seam = [int(s.get("seam_drop", 0)) for s in segments[1:]]
        ok_drops = all(1 <= d <= 6 for d in per_seam)
        results.append((len(merged) == src_ticks - drops + added and ok_drops,
                        f"ticks {len(merged)} = segments {src_ticks} - removed {drops} "
                        f"(seams {seams}, per seam {per_seam}) + phase {added}"))

    fails = 0
    for ok, line in results:
        if on_log is not None:
            on_log(("PASS  " if ok else "FAIL  ") + line)
        fails += 0 if ok else 1
    if meter is not None:
        meter.finish()
    elapsed = time.time() - t0
    if on_log is not None:
        on_log(f"{opts.name}: {len(merged)} ticks, {final_ms} ms, "
               f"{len(merged) / (final_ms / 1000):.2f} ticks/s, waves "
               f"{payload['metadata']['waves']} ({payload['metadata']['wave_rate']} waves/s), "
               f"{elapsed:.0f} s -> {target}")
    return {"clips": len(clips), "sidecars": len(sidecars), "selected": len(kept),
            "checked": len(kept), "final_ms": final_ms, "ticks": len(merged),
            "waves": payload["metadata"]["waves"], "fails": fails,
            "elapsed_s": round(elapsed, 1), "video": str(target),
            "sidecar_out": str(sidecar_out),
            "report": str(work_dir / "video_summary.csv")}
