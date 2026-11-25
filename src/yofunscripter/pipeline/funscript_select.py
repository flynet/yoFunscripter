"""Sidecar'ы папки источников -> порядок склейки по плотности тиков и отбор по порогу.

    python scripts/funscript_select.py                              # configs: source_dir
    python scripts/funscript_select.py --source video_source --min-waves 3 --max-waves 0

Выход: runs/funscript/selection.csv — отобранные клипы с `order` 1..N (`tick_rate`
возрастает) и отброшенные с причиной. Файл фиксирует порядок, чтобы повторный прогон
дал ту же последовательность.

Мера порядка — `tick_rate` = тиков в секунду (все тики: экстремумы + фаза + якоря),
то есть то, что реально ощущается на устройстве. Раньше сортировка была по `wave_rate`
(волны в секунду), и клипы с рваным треком вставали в начало: `seg-0144` 0.8 волн/с
(6 принятых экстремумов), но сетка фазы по медиане 120 мс даёт 7.96 тиков/с — плотность
как у самого быстрого клипа склейки, и график в начале круче, чем в середине. `wave_rate`
остаётся в сайдкаре и в проверке (он = волны / длительность), порядок по нему больше не
считается. Отбор: `waves >= min_waves` (клипы без волн отсекаются), `waves <= max_waves`
(0 = верхнего порога нет). Пустой sidecar (0 тиков) отсекается отдельно.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from .funscript_common import ROOT, load_config, read_rows, write_rows, video_duration_ms

SELECTION_COLUMNS = ("order", "name", "clip", "sidecar", "waves", "wave_rate",
                     "tick_rate", "duration_ms", "ticks", "status", "reason")

SORT_TICK_RATE = "tick_rate"
SORT_WAVES_ASC = "waves_asc"
SORT_WAVES_DESC = "waves_desc"
SORT_KEEP = "keep"
SORT_RANDOM = "random"
SORT_MODES = (SORT_TICK_RATE, SORT_WAVES_ASC, SORT_WAVES_DESC, SORT_KEEP, SORT_RANDOM)
#: The key of the catalog for each mode: the window shows the label, the console of the
#: merge names the order in the language of the window. One source for both.
SORT_LABEL_KEYS = {
    SORT_TICK_RATE: "sort_tick_rate",
    SORT_WAVES_ASC: "sort_waves_asc",
    SORT_WAVES_DESC: "sort_waves_desc",
    SORT_KEEP: "sort_keep",
    SORT_RANDOM: "sort_random",
}


def order_kept(kept: list[dict], sort_mode: str) -> None:
    """Порядок отобранных клипов по `sort_mode` (ряд перезаписывается на месте).

    `tick_rate` = плотность тиков в секунду, как в yolo (tick_rate возрастает).
    `waves_asc` / `waves_desc` = по числу волн; `keep` = порядок имён; `random` =
    перемешивание, посев = имена клипов, поэтому повторный прогон той же папки даёт
    ту же последовательность (selection.csv фиксирует порядок).
    """
    if sort_mode == SORT_TICK_RATE:
        kept.sort(key=lambda r: (r["tick_rate"], r["name"]))
    elif sort_mode == SORT_WAVES_ASC:
        kept.sort(key=lambda r: (r["waves"], r["tick_rate"], r["name"]))
    elif sort_mode == SORT_WAVES_DESC:
        kept.sort(key=lambda r: (-r["waves"], -r["tick_rate"], r["name"]))
    elif sort_mode == SORT_KEEP:
        kept.sort(key=lambda r: r["name"])
    elif sort_mode == SORT_RANDOM:
        kept.sort(key=lambda r: r["name"])
        rng = random.Random("|".join(r["name"] for r in kept))
        rng.shuffle(kept)
    else:
        raise ValueError(f"sort_mode {sort_mode} не из {SORT_MODES}")



def read_sidecar(sidecar: Path) -> dict:
    """waves/wave_rate/тики из metadata готового sidecar'а."""
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    meta = payload.get("metadata") or {}
    return {"waves": int(meta.get("waves", 0)),
            "wave_rate": float(meta.get("wave_rate", 0.0)),
            "ticks": len(payload.get("actions") or [])}


def select(sidecars: list[Path], min_waves: int, max_waves: int,
           sort_mode: str = SORT_TICK_RATE, clips_dir: Path | None = None) -> list[dict]:
    """Сайдкары -> строки selection.csv: отобранные по order, отброшенные без order."""
    rows = []
    for sidecar in sorted(sidecars):
        clip = (clips_dir or sidecar.parent) / (sidecar.stem + ".mp4")
        info = read_sidecar(sidecar)
        duration_ms = video_duration_ms(clip)
        row = {"order": "", "name": sidecar.stem, "clip": str(clip), "sidecar": str(sidecar),
               "waves": info["waves"], "wave_rate": info["wave_rate"],
               "tick_rate": round(info["ticks"] / (duration_ms / 1000), 3) if duration_ms else 0.0,
               "duration_ms": duration_ms, "ticks": info["ticks"],
               "status": "kept", "reason": ""}
        if info["ticks"] == 0:
            row["status"], row["reason"] = "skip", "empty_script"
        elif info["waves"] < min_waves:
            row["status"], row["reason"] = "skip", f"waves {info['waves']} < min {min_waves}"
        elif max_waves > 0 and info["waves"] > max_waves:
            row["status"], row["reason"] = "skip", f"waves {info['waves']} > max {max_waves}"
        rows.append(row)
    kept = [r for r in rows if r["status"] == "kept"]
    order_kept(kept, sort_mode)
    for i, r in enumerate(kept, 1):
        r["order"] = i
    return kept + [r for r in rows if r["status"] != "kept"]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", default=None, help="папка клипов (configs:source_dir)")
    p.add_argument("--pattern", default="*.funscript", help="шаблон сайдкар'ов")
    p.add_argument("--min-waves", type=int, default=None, help="перекрыть configs:min_waves")
    p.add_argument("--max-waves", type=int, default=None, help="перекрыть configs:max_waves (0 = инфинитум)")
    p.add_argument("--sort", default=SORT_TICK_RATE, choices=SORT_MODES,
                   help="порядок склейки (см. order_kept)")
    p.add_argument("--clips", default=None,
                   help="папка видео, если сайдкар'ы лежат в другой папке")
    p.add_argument("--cfg", default=None)
    p.add_argument("--no-write", action="store_true", help="только посчитать и напечатать")
    a = p.parse_args()

    cfg = load_config(Path(a.cfg) if a.cfg else None)
    min_waves = int(cfg["min_waves"]) if a.min_waves is None else a.min_waves
    max_waves = int(cfg["max_waves"]) if a.max_waves is None else a.max_waves
    source = ROOT / cfg["source_dir"] if a.source is None else Path(a.source)
    sidecars = [q for q in sorted(source.glob(a.pattern)) if q.is_file()]
    if not sidecars:
        raise SystemExit(f"в {source} ({a.pattern}) сайдкар'ов нет")

    rows = select(sidecars, min_waves, max_waves, a.sort,
                  Path(a.clips) if a.clips else None)
    kept = [r for r in rows if r["status"] == "kept"]
    print(f"сайдкар'ов {len(rows)}, отобрано {len(kept)}, min_waves {min_waves}, "
          f"max_waves {max_waves if max_waves > 0 else 'inf'}")
    for r in kept:
        print(f"  {r['order']} {r['name']}: {r['tick_rate']} тиков/с, {r['wave_rate']} волн/с, "
              f"волн {r['waves']}, {r['ticks']} тиков, {r['duration_ms']} мс")
    for r in rows:
        if r["status"] != "kept":
            print(f"  пропуск {r['name']}: {r['reason']}")
    if kept:
        total_ms = sum(r["duration_ms"] for r in kept)
        total_waves = sum(r["waves"] for r in kept)
        total_ticks = sum(r["ticks"] for r in kept)
        print(f"суммарно {total_waves} волн, {total_ticks} тиков, {total_ms} мс, "
              f"{total_waves / (total_ms / 1000):.2f} волн/с, "
              f"{total_ticks / (total_ms / 1000):.2f} тиков/с")
    if not a.no_write:
        out = ROOT / cfg["out_dir"] / "selection.csv"
        write_rows(out, SELECTION_COLUMNS, rows)
        print(f"порядок: {out}")


if __name__ == "__main__":
    main()
