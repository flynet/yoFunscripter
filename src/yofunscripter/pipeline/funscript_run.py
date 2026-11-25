r"""Batch: клипы -> sidecar `.funscript` + отчёт `runs/funscript/summary.csv`.

По умолчанию — ОДИН клип `video_debug/debug.mp4`. Папку задают явно: `--root video --pattern "**/*.mp4"`.

    python scripts/funscript_run.py                       # video_debug/debug.mp4
    python scripts/funscript_run.py --dry                 # что будет сделано
    python scripts/funscript_run.py --force               # пересчитывать поверх sidecar
    python scripts/funscript_run.py --limit 5             # первые N клипов
    python scripts/funscript_run.py --filter "2 (1)"      # только путь содержит подстроку
    python scripts/funscript_run.py --root video --pattern "**/*.mp4"   # папка клипов

Идемпотентность: клип пропускается, если sidecar уже есть **и новее клипа** (и не --force).
Клип заменили (то же имя) -> сайдкар пересчитывается. Отчёт пишется заново каждым прогоном
и содержит все посещённые клипы, включая пропуски.
Модель загружается один раз на весь прогон (замер: инференс 0.024 с на кадр @imgsz 1024,
RTX 4060; клип 5.1 с = 3.2-4.2 с).

model_version = sha1 весов (models/current/best.pt перезаписывается между циклами
обучения, поэтому версия пишется в каждую строку отчёта).
"""
from __future__ import annotations

import argparse
import sys
from .paths import model_path
import time
from pathlib import Path

from .funscript_common import (
    ROOT, TRACK_COLUMNS, clip_out_dir, frame_ms_of, load_config, load_model,
    sha1_short, video_duration_ms, write_rows,
)
from .funscript_build import build_clip
from .funscript_signal import signal_artifacts
from .funscript_track import track_clip

SUMMARY_COLUMNS = ("clip", "sidecar", "format", "status", "ticks", "duration_ms",
                   "tracks", "chosen_track", "chosen_class", "segment_start", "segment_end",
                   "amplitude_px", "coverage", "periodicity", "period_ms", "update_ratio",
                   "waves", "wave_rate", "reason",
                   "model_version", "elapsed_s")

FORMAT_NAME = "funscript"
PROGRESS_EVERY = 10


def sidecar_of(clip: Path) -> Path:
    return clip.parent / (clip.stem + ".funscript")


def sidecar_current(clip: Path) -> bool:
    """Sidecar годен, только если он **новее** клипа: клип заменили (то же имя, новый
    mtime) — сайдкар старого клипа не годен, иначе склейка получает видео нового клипа с
    графиком старого."""
    sc = sidecar_of(clip)
    return sc.is_file() and sc.stat().st_mtime >= clip.stat().st_mtime


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(ROOT / "video_debug"),
                   help="папка с клипами; по умолчанию один debug-клип")
    p.add_argument("--pattern", default="*.mp4")
    p.add_argument("--cfg", default=None)
    p.add_argument("--weights", default=None, help="перекрыть configs/funscript.yaml:weights")
    p.add_argument("--device", default=None, help="gpu = 0, cpu = хост; по умолчанию GPU, если есть")
    p.add_argument("--dry", action="store_true", help="ничего не писать, только список")
    p.add_argument("--force", action="store_true", help="пересчитывать поверх существующего sidecar")
    p.add_argument("--limit", type=int, default=0, help="обработать не больше N клипов")
    p.add_argument("--filter", default="", help="пропускать пути, не содержащие подстроку")
    p.add_argument("--points", action="store_true", default=True,
                   help="писать points.csv для viewer (по умолчанию включено)")
    p.add_argument("--no-points", dest="points", action="store_false",
                   help="не писать points.csv (viewer без слоёв точек)")
    a = p.parse_args()

    cfg = load_config(Path(a.cfg) if a.cfg else None)
    weights = Path(a.weights) if a.weights else model_path(cfg)
    root = Path(a.root)
    clips = sorted(q for q in root.glob(a.pattern) if q.is_file())
    if a.filter:
        clips = [q for q in clips if a.filter in str(q)]
    if a.limit:
        clips = clips[:a.limit]
    if not clips:
        raise SystemExit(f"в {root} ({a.pattern}) клипов не найдено")

    model_version = sha1_short(weights)
    pending = [q for q in clips if a.force or not sidecar_current(q)]
    stale = [q for q in clips if sidecar_current(q) is False and sidecar_of(q).is_file()]
    print(f"клипов {len(clips)}, к записи {len(pending)}, веса {weights.name} "
          f"sha1 {model_version}, формат {FORMAT_NAME}")
    if stale:
        print(f"  сайдкар'ы старше клипов (клип заменён): {len(stale)} "
              f"-> {', '.join(q.name for q in stale[:6])}")

    if a.dry:
        for q in pending:
            print(f"  {q}")
        for q in clips:
            if q not in pending:
                print(f"  пропуск {q} (sidecar есть)")
        return

    device = None if a.device is None else (0 if a.device == "gpu" else "cpu")
    model, device = load_model(weights, device)

    rows = []
    t_start = time.time()
    for i, clip in enumerate(clips, 1):
        sidecar = sidecar_of(clip)
        if not a.force and sidecar_current(clip):
            rows.append({"clip": str(clip), "sidecar": str(sidecar), "format": FORMAT_NAME,
                         "status": "skip", "ticks": "", "duration_ms": "", "tracks": "",
                         "chosen_track": "", "chosen_class": "", "segment_start": "",
                         "segment_end": "", "amplitude_px": "", "coverage": "",
                         "periodicity": "", "period_ms": "", "update_ratio": "",
                         "waves": "", "wave_rate": "", "reason": "sidecar current",
                         "model_version": model_version, "elapsed_s": ""})
            continue
        t0 = time.time()
        try:
            duration_ms = video_duration_ms(clip)
            r = track_clip(clip, cfg, model, device, a.points, quiet=True)
            out_dir = clip_out_dir(clip, cfg)
            write_rows(out_dir / "track.csv", TRACK_COLUMNS, r["rows"])
            if a.points:
                write_rows(out_dir / "points.csv",
                           ("frame", "ms", "track_id", "x", "y", "good"), r["point_rows"])
            frame_ms = frame_ms_of(r["rows"])
            fusion = signal_artifacts(cfg, clip, r["rows"], duration_ms, frame_ms)
            row = build_clip(cfg, clip, fusion, duration_ms, model_version, write=True)
            ticks = row.pop("tick_list")
            row.update({"status": "done" if ticks else "empty", "tracks": len(fusion["tracks"]),
                        "elapsed_s": round(time.time() - t0, 2)})
            rows.append(row)
            print(f"[{i}/{len(clips)}] {clip}: тиков {row['ticks']}, "
                  f"трек {row['chosen_track']} ({row['chosen_class']}), "
                  f"{row['elapsed_s']} с" + (f" -> {row['reason']}" if row["reason"] else ""))
            if i % PROGRESS_EVERY == 0:
                d = time.time() - t_start
                print(f"  {i} клипов за {d:.0f} с -> {d / i:.2f} с/клип, "
                      f"осталось {(len(clips) - i) * d / i / 60:.0f} мин", flush=True)
        except Exception as exc:            # batch не падает на одном битом клипе
            rows.append({"clip": str(clip), "sidecar": str(sidecar), "format": FORMAT_NAME,
                         "status": "error", "ticks": "", "duration_ms": "", "tracks": "",
                         "chosen_track": "", "chosen_class": "", "segment_start": "",
                         "segment_end": "", "amplitude_px": "", "coverage": "",
                         "periodicity": "", "period_ms": "", "update_ratio": "",
                         "waves": "", "wave_rate": "",
                         "reason": f"{type(exc).__name__}: {exc}",
                         "model_version": model_version,
                         "elapsed_s": round(time.time() - t0, 2)})
            print(f"[{i}/{len(clips)}] {clip}: ОШИБКА {type(exc).__name__}: {exc}")

    out_dir = ROOT / cfg["out_dir"]
    write_rows(out_dir / "summary.csv", SUMMARY_COLUMNS, rows)
    done = sum(1 for r in rows if r["status"] == "done")
    empty = sum(1 for r in rows if r["status"] == "empty")
    skipped = sum(1 for r in rows if r["status"] == "skip")
    errors = sum(1 for r in rows if r["status"] == "error")
    d = time.time() - t_start
    print(f"\nклипов {len(rows)}: записано {done}, пусто {empty}, пропущено {skipped}, "
          f"ошибок {errors}, времени {d:.0f} с ({d / max(len(clips), 1):.2f} с/клип)")
    print(f"отчёт: {out_dir / 'summary.csv'}")


if __name__ == "__main__":
    main()
