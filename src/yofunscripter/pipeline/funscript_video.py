"""`video_source` -> `video_result`: отбор по волнам, энкод, склейка, один merged funscript.

    python scripts/funscript_video.py --dry                   # план
    python scripts/funscript_video.py                         # прогон
    python scripts/funscript_video.py --force --min-waves 5   # пересчитать, порог волн
    python scripts/funscript_video.py --name merged_2026-11-22

Порядок:
  1. sidecar'ы клипов `source_dir` (`funscript_run.py`, идемпотентно);
  2. отбор `waves >= min_waves` и сортировка по `tick_rate` (тиков в секунду) возрастает
     (`funscript_select.py`); `wave_rate` считается в сайдкаре и проверяется, по нему не сортируют;
  3. энкод каждого отобранного клипа в `concat_dir/<stem>.mp4`: 1920x1080@30, libx264 crf 18
     veryslow, yuv420p, единый timescale, AAC 48k stereo (`funscript_concat.py`);
  4. оффсеты по **измеренным после энкода** длительностям (`video_duration_ms`);
  5. мердж скрипта со стыками -> `result_dir/<name>.funscript` (`funscript_merge.py`);
  6. concat demuxer `-c copy` -> `result_dir/<name>.mp4` (без перекодирования, качество
     не теряется, PTS считает ffmpeg);
  7. проверка: длительность == последний тик, 30 fps, yuv420p, единый timescale, PTS строго
     возрастающие, и 17 проверок скрипта (`funscript_check.py`).

Отчёт: `runs/funscript/video_summary.csv` (порядок, волны, длительности, оффсеты) и
PASS/FAIL по строкам; код 1 при любом FAIL.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from .funscript_common import ROOT, load_config, video_duration_ms, write_rows

from .funscript_check import check_payload
from .funscript_concat import (check_final, clean_concat, concat, concat_gc, encode, load_manifest,
                              probe, record_segment, segment_fresh)
from .funscript_merge import load_order, merged_gap_check, merge_segments, merged_payload, write_merged
from .funscript_select import SELECTION_COLUMNS, select

SUMMARY_COLUMNS = ("order", "name", "segment_out", "sidecar", "waves", "wave_rate",
                   "tick_rate", "source_ms", "encoded_ms", "offset_ms", "ticks",
                   "status", "reason")


def build_sidecars(source: Path, pattern: str, force: bool, cfg_path: Path | None) -> None:
    """Sidecar-этап наследует конфиг прогона: `out_dir` и `weights` того же прогона
    (иначе A/B-прогон пишет артефакты в чужую папку, и проверка тиков его не видит)."""
    cmd = [sys.executable, str(ROOT / "scripts" / "funscript_run.py"),
           "--root", str(source), "--pattern", pattern]
    if cfg_path is not None:
        cmd += ["--cfg", str(cfg_path)]
    if force:
        cmd.append("--force")
    code = subprocess.run(cmd).returncode
    if code != 0:
        raise SystemExit(f"funscript_run.py (код {code})")


def print_plan(kept: list[dict], rows: list[dict], result_dir: Path, name: str,
              concat_dir: Path, min_waves: int, max_waves: int) -> None:
    print(f"отбор: {len(kept)} из {len(rows)} (min_waves {min_waves}, "
          f"max_waves {max_waves if max_waves > 0 else 'inf'}), порядок по тикам/сек")
    for r in kept:
        print(f"  {r['order']} {r['name']}: {r['tick_rate']} тиков/с, {r['wave_rate']} волн/с, "
              f"волн {r['waves']}, {r['ticks']} тиков, {r['duration_ms']} мс "
              f"-> {concat_dir / (r['name'] + '.mp4')}")
    for r in rows:
        if r["status"] != "kept":
            print(f"  пропуск {r['name']}: {r['reason']}")
    if kept:
        total_ms = sum(r["duration_ms"] for r in kept)
        total_waves = sum(r["waves"] for r in kept)
        print(f"  суммарно {total_waves} волн, {total_ms} мс, "
              f"{total_waves / (total_ms / 1000):.2f} волн/с")
    print(f"  финал {result_dir / (name + '.mp4')} и {result_dir / (name + '.funscript')}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", default=None, help="папка клипов (configs:source_dir)")
    p.add_argument("--pattern", default="*.mp4", help="шаблон клипов")
    p.add_argument("--result-dir", default=None, help="папка финала (configs:result_dir)")
    p.add_argument("--name", default=None, help="имя финала (configs:result_name)")
    p.add_argument("--min-waves", type=int, default=None, help="перекрыть configs:min_waves")
    p.add_argument("--max-waves", type=int, default=None, help="перекрыть configs:max_waves")
    p.add_argument("--cfg", default=None)
    p.add_argument("--dry", action="store_true", help="план, ничего не писать")
    p.add_argument("--force", action="store_true", help="пересчитать sidecar и переэнкодить")
    p.add_argument("--clean", action="store_true", help="очистить кэш сегментов и выйти")
    p.add_argument("--skip-sidecars", action="store_true", help="sidecar'ы уже готовы")
    a = p.parse_args()

    cfg = load_config(Path(a.cfg) if a.cfg else None)
    source = ROOT / cfg["source_dir"] if a.source is None else Path(a.source)
    result_dir = ROOT / cfg["result_dir"] if a.result_dir is None else Path(a.result_dir)
    concat_dir = ROOT / cfg["concat_dir"]
    name = a.name or str(cfg["result_name"])
    min_waves = int(cfg["min_waves"]) if a.min_waves is None else a.min_waves
    max_waves = int(cfg["max_waves"]) if a.max_waves is None else a.max_waves

    if a.clean:
        removed, freed = clean_concat(concat_dir)
        print(f"clean {concat_dir}: {len(removed)} файлов, {freed / 1e6:.0f} МБ")
        return

    clips = [q for q in sorted(source.glob(a.pattern)) if q.is_file()]
    if not clips:
        raise SystemExit(f"в {source} ({a.pattern}) клипов нет")
    print(f"клипов {len(clips)} в {source}, цель {int(cfg['target_width'])}x"
          f"{int(cfg['target_height'])}@{int(cfg['target_fps'])} crf {cfg['x264_crf']} "
          f"{cfg['x264_preset']}, финал {result_dir / (name + '.mp4')}")

    # кэш concat_dir переживает перезапуск (переэнкод = 4.9 с/клип), но сегмент клипа,
    # которого в папке клипов нет, — мусор, и имя может достаться новому клипу
    present = {q.stem for q in clips}
    stale = [p for p in sorted(concat_dir.glob("*.mp4")) if p.stem not in present]
    if stale:
        bytes_stale = sum(p.stat().st_size for p in stale)
        print(f"  мусор в {concat_dir}: {len(stale)} сегментов клипов, которых нет "
              f"({bytes_stale / 1e6:.0f} МБ){' — снимаю' if not a.dry else ''}")
        if not a.dry:
            removed, freed = concat_gc(concat_dir, present)
            print(f"  снято {len(removed)} сегментов, {freed / 1e6:.0f} МБ")

    def state() -> tuple[list[Path], list[Path]]:
        """(годные сайдкар'ы, клипы к пересчёту). Сайдкар годен только если он **новее**
        клипа: клип заменили (то же имя) — график старого клипа не годен."""
        ready, todo = [], []
        for q in clips:
            sc = q.parent / (q.stem + ".funscript")
            if sc.is_file() and sc.stat().st_mtime >= q.stat().st_mtime:
                ready.append(sc)
            else:
                todo.append(q)
        return ready, todo

    ready, todo = state()
    replaced = [q for q in todo if (q.parent / (q.stem + ".funscript")).is_file()]
    if a.dry:
        print(f"sidecar'ов готово {len(ready)}, к генерации {len(todo)}, "
              f"из них заменённых клипов {len(replaced)}")
        if ready:
            rows = select(ready, min_waves, max_waves)
            print_plan([r for r in rows if r["status"] == "kept"], rows, result_dir,
                       name, concat_dir, min_waves, max_waves)
        return

    if not a.skip_sidecars and todo:
        build_sidecars(source, a.pattern, a.force, Path(a.cfg) if a.cfg else None)
    ready, todo = state()
    if todo:
        # клип без детекций: sidecar не пишется; один такой клип не валит весь прогон
        print(f"  снято {len(todo)} клипов без сайдкар'а "
              f"(трек пуст): {', '.join(q.name for q in todo[:6])}")
    if not ready:
        raise SystemExit(f"сайдкар'ов нет: {', '.join(q.name for q in todo[:6])}")

    rows = select(ready, min_waves, max_waves)
    write_rows(ROOT / cfg["out_dir"] / "selection.csv", SELECTION_COLUMNS, rows)
    kept = [r for r in rows if r["status"] == "kept"]
    if not kept:
        raise SystemExit(f"отобранных клипов нет (min_waves {min_waves})")
    print_plan(kept, rows, result_dir, name, concat_dir, min_waves, max_waves)

    t0 = time.time()
    summary: list[dict] = []
    encoded: dict[str, int] = {}
    segment_paths: list[Path] = []
    manifest = load_manifest(concat_dir)
    reencoded = 0
    for r in kept:
        clip = Path(r["clip"])
        out = concat_dir / (r["name"] + ".mp4")
        if a.force or not segment_fresh(out, clip, cfg, manifest):
            info = encode(clip, out, cfg)
            reencoded += 1
            encoded_ms = int(info["duration_ms"])
        else:
            encoded_ms = int(probe(out, cfg)["duration_ms"])
        record_segment(concat_dir, out, clip, encoded_ms, cfg)
        encoded[r["name"]] = encoded_ms
        segment_paths.append(out)
        summary.append({"order": r["order"], "name": r["name"], "segment_out": str(out),
                        "sidecar": r["sidecar"], "waves": r["waves"],
                        "wave_rate": r["wave_rate"], "tick_rate": r["tick_rate"],
                        "source_ms": r["duration_ms"],
                        "encoded_ms": encoded_ms, "offset_ms": "", "ticks": r["ticks"],
                        "status": "encoded", "reason": ""})

    print(f"энкод: {reencoded} из {len(kept)} сегментов заново, "
          f"{len(kept) - reencoded} из кэша ({time.time() - t0:.0f} с)")
    # плеер держит результат открытым, и ffmpeg не может его перезаписать (Permission denied
    # в логе ffmpeg, прогон с кодом 1 без объяснения). Проверяем запись до склейки
    target = result_dir / (name + ".mp4")
    if target.exists():
        try:
            with open(target, "ab"):
                pass
        except PermissionError:
            raise SystemExit(f"{target} занят другим процессом (проигрывателем): закройте "
                             "плеер и повторите прогон")
    concat(segment_paths, target, cfg)

    video = result_dir / (name + ".mp4")
    info = probe(video, cfg)
    # скрипт выравнивается по format-длительности (той, что показывает плеер): каждый сегмент
    # с `-shortest` несёт AAC-хвост <= 21.3 мс (округление до AAC-кадра), видеопоток короче
    # контейнера на него. Скрипт по видеопотоку отставал от плеера на сумму хвостов
    # (55 сегм. ~ 1.2 с: ScriptPlayer проиграл скрипт и стоит, видео идёт)
    final_ms = info["duration_ms"]
    # округления длительностей сегментов при суммировании дают ±1 мс, поэтому последний
    # якорь ставится на измеренную длительность склейки: длина скрипта == длина видео ровно
    segments = load_order(name, cfg, encoded)
    merged = merge_segments(segments, cfg)
    if merged and merged[-1]["ms"] != final_ms:
        merged[-1]["ms"] = final_ms
    payload = merged_payload(merged, segments, name, cfg, final_ms)
    sidecar = write_merged(payload, merged, segments, name, cfg, final_ms)
    for s in segments:
        row = next(x for x in summary if x["name"] == s["name"])
        row["offset_ms"] = s["offset_ms"]
        row["ticks"] = len(s["ticks"])

    results = check_payload(payload, final_ms, cfg, video, skip_gaps=True)
    results.append(merged_gap_check(merged, segments, cfg))
    results += check_final(video, cfg, len(segments))
    results.append((int(merged[-1]["ms"]) == final_ms,
                    f"последний тик {merged[-1]['ms']} = длительность видео {final_ms} мс "
                    f"({info['frames']} кадров @ {info['r_fps']} fps)"))
    src_ticks = sum(len(s["ticks"]) for s in segments)
    drops = sum(int(s.get("seam_drop", 0)) for s in segments)
    added = sum(int(s.get("seam_phase", 0)) for s in segments)
    seams = len(segments) - 1
    per_seam = [int(s.get("seam_drop", 0)) for s in segments[1:]]
    ok_drops = all(1 <= d <= 6 for d in per_seam)
    results.append((len(merged) == src_ticks - drops + added and ok_drops,
                    f"тиков {len(merged)} = сегментов {src_ticks} минус снято {drops} "
                    f"(стыков {seams}, по стыкам {per_seam}: 2 якоря + совпавшие фазы), "
                    f"плюс фаза на швах {added}"))
    summary.append({"order": "", "name": name, "segment_out": str(video), "sidecar": str(sidecar),
                    "waves": payload["metadata"]["waves"],
                    "wave_rate": payload["metadata"]["wave_rate"],
                    "tick_rate": round(len(merged) / (final_ms / 1000), 3),
                    "source_ms": sum(int(s["source_ms"]) for s in segments),
                    "encoded_ms": final_ms, "offset_ms": "", "ticks": len(merged),
                    "status": "merged", "reason": ""})
    write_rows(ROOT / cfg["out_dir"] / "video_summary.csv", SUMMARY_COLUMNS, summary)

    fails = 0
    for ok, line in results:
        print(("PASS  " if ok else "FAIL  ") + line)
        fails += 0 if ok else 1
    print(f"INFO  {video.name}: {len(merged)} тиков, {final_ms} мс, "
          f"{len(merged) / (final_ms / 1000):.2f} тиков/с, волн "
          f"{payload['metadata']['waves']} ({payload['metadata']['wave_rate']} волн/с), "
          f"{time.time() - t0:.0f} с")
    print(f"отчёт: {ROOT / cfg['out_dir'] / 'video_summary.csv'}")
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()
