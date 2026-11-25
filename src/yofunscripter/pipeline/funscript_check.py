"""Проверка .funscript: формат, времена, позиции, скорость.

    python scripts/funscript_check.py                    # debug.mp4 + debug.funscript
    python scripts/funscript_check.py --video "video/2 (1)/part_22_20.mp4"

Проверяется:
  - JSON читается, есть `actions`; формат эталона funscript/example.funscript: ключи
    actions/inverted/metadata/range/version, действия {at,pos}, version 1.0, inverted false,
    range из конфига, metadata.duration в секундах, `deviceTime`/`actionTrack` отсутствуют;
  - `at` целые >= 0, строго возрастают, нет двух одинаковых;
  - `pos` целые 0..100; при `pos_binary: true` — только 0 и 100;
  - плато нет: соседние тики с одинаковым pos (устройство стоит) — FAIL в обоих режимах pos;
  - интервалы >= min_interval_ms (configs/funscript.yaml);
  - разрывы <= 3.5 полупериода (медианный интервал экстремумов) **там, где консенсус мерит
    движение**: амплитуда консенсуса на интервале (`signal.csv`, колонка `amp`) >=
    min_amplitude_px. Где трекеры не видят колебания, плато честное (фазовые тики через
    пропажу больше не ставятся: `phase_fill: false`);
  - первый тик в 0, последний в duration_ms (плеер держит первую позицию до первого
    тика и последнюю после последнего — без якорей начало и конец клипа молчат);
  - скорость |delta pos| / delta time <= speed_limit_units_per_s (предел устройств);
  - `metadata.waves` и `metadata.wave_rate`: целые >= 0, wave_rate = waves / длителность
    (по нему сортируются клипы при склейке); waves = полных волн по измеренным тикам;
  - INFO: тиков, из них измеренных, поддержка тиков (`min_tick_support`).

Выход: построчно PASS/FAIL, код 0 при всех PASS, 1 при любом FAIL.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from .funscript_common import ROOT, SIGNAL_COLUMNS, clip_out_dir, load_config, read_rows

from .funscript_concat import probe
from .funscript_build import KIND_PROJECT, KIND_SLOPE, TICK_COLUMNS
from .funscript_merge import merged_gap_check

SPEED_LIMIT_DEFAULT = 500.0


def phase_step(clip: Path, cfg: dict, min_interval: int) -> int:
    """Шаг фазы = медианны интервал между экстремумами из ticks.csv (фактический
    полупериод колебания). Period_ms по автокорреляции — гармоника, по нему сетка редкая."""
    ticks_csv = clip_out_dir(clip, cfg) / "ticks.csv"
    if not ticks_csv.is_file():
        return min_interval
    ext_ms = [int(r["ms"]) for r in read_rows(ticks_csv, TICK_COLUMNS)
              if r["kind"] == "extremum"]
    gaps = [b - a for a, b in zip(ext_ms, ext_ms[1:])]
    return max(min_interval, int(round(statistics.median(gaps)))) if gaps else min_interval


def local_amp(signal_csv: Path, a: int, b: int) -> float:
    """Максимальная локальная амплитуда консенсуса на интервале [a, b] мс (колонка `amp`).

    Плато честно там, где измеренного движения нет: амплитуда консенсуса ниже
    `min_amplitude_px` — трекеры не видят колебания, тика ставить нечего. Плато на
    интервале с измеренным движением = пропущенный экстремум (замер sexy-s002: разрыв
    6160 мс при медианном шаге 160 мс).
    """
    if not signal_csv.is_file():
        return 0.0
    best = 0.0
    for r in read_rows(signal_csv, SIGNAL_COLUMNS):
        if a <= int(r["ms"]) <= b and r["amp"]:
            best = max(best, float(r["amp"]))
    return best


def merged_gap_rows(merged_csv: Path, cfg: dict) -> tuple[bool, str] | None:
    """Разрывы склейки по полупериоду **каждого сегмента** (merged.csv, колонка `seg`).

    Общий медианный шаг по всему скрипту (`phase_step`) режет натуральные интервалы экстремумов
    медленного сегмента: 1190 мс при полупериоде 440 = 2.7 полупериода, это полный цикл
    движения, а не плато. Прогон считает разрывы так же (`funscript_merge.merged_gap_check`),
    здесь тот же расчёт по merged.csv, чтобы `--video result.mp4` сходилась с прогоном.
    """
    if not merged_csv.is_file():
        return None
    rows = read_rows(merged_csv, ("ms", "pos", "kind", "peak", "seg"))
    merged = [{"ms": int(r["ms"]), "pos": int(r["pos"]), "kind": r["kind"],
               "peak": r["peak"], "seg": int(r["seg"])} for r in rows]
    by_seg: dict[int, list[dict]] = defaultdict(list)
    for t in merged:
        by_seg[t["seg"]].append(t)
    segments = [{"name": str(i), "ticks": by_seg[i]} for i in sorted(by_seg)]
    return merged_gap_check(merged, segments, cfg)


def check_payload(payload: dict, duration_ms: int, cfg: dict, clip: Path,
                  skip_gaps: bool = False) -> list[tuple[bool, str]]:
    out: list[tuple[bool, str]] = []
    actions = payload.get("actions")
    if not isinstance(actions, list):
        return [(False, "actions отсутствует")]
    if not actions:
        # волн нет: клип без измеренного движения (гейт low_amplitude/no_periodicity)
        # даёт пустой sidecar, и это честный ответ. Формат и metadata проверяются
        meta0 = payload.get("metadata") or {}
        waves0 = meta0.get("waves")
        rate0 = meta0.get("wave_rate")
        want_keys = ["actions", "inverted", "metadata", "range", "version"]
        out.append((True, "actions пуст = волн нет (0 тиков)"))
        out.append((sorted(payload.keys()) == want_keys,
                    f"ключи {want_keys} (фактически {sorted(payload.keys())})"))
        out.append((payload.get("version") == "1.0" and payload.get("inverted") is False
                    and int(payload.get("range", -1)) == int(cfg["range"]),
                    f"version 1.0, inverted false, range {cfg['range']} "
                    f"(фактически {payload.get('version')}, {payload.get('inverted')}, "
                    f"{payload.get('range')})"))
        out.append((isinstance(waves0, int) and waves0 == 0
                    and isinstance(rate0, (int, float)) and rate0 == 0,
                    f"волн 0 при пустых actions (waves {waves0}, wave_rate {rate0})"))
        out.append((int(meta0.get("duration", -1)) == int(round(duration_ms / 1000.0)),
                    f"metadata.duration = {int(round(duration_ms / 1000.0))} с "
                    f"(фактически {meta0.get('duration')})"))
        out.append(("deviceTime" not in json.dumps(payload) and "actionTrack" not in payload,
                    "deviceTime/actionTrack отсутствуют"))
        return out
    at = [a.get("at") for a in actions]
    pos = [a.get("pos") for a in actions]
    ok = all(isinstance(v, int) and v >= 0 for v in at)
    out.append((ok, f"at целые >= 0 ({len(at)} тиков)"))
    ok = all(isinstance(v, int) and 0 <= v <= 100 for v in pos)
    out.append((ok, "pos целые 0..100"))
    if bool(cfg.get("pos_binary", True)):
        # ход устройства 0 -> 100 -> 0: полный ход (prominence >= `full_stroke_ratio`
        # локальной амплитуды) = 0/100. Частичный wobble (`prom` ниже ratio) и середина
        # длинного монотонного хода (`slope`) = измеренная pos
        kinds = {}
        ticks_csv = clip_out_dir(clip, cfg) / "ticks.csv"
        if ticks_csv.is_file():
            for r in read_rows(ticks_csv, TICK_COLUMNS):
                kinds[int(r["ms"])] = (r["kind"], float(r["prom"]) if r["prom"] else 0.0)
        full = float(cfg["full_stroke_ratio"])
        bad = [p for p, a in zip(pos, at)
               if p not in (0, 100) and kinds.get(a, ("", 0.0))[1] >= full
               and kinds.get(a, ("", 0.0))[0] != KIND_SLOPE]
        out.append((not bad, f"pos 0/100 для полного хода (фактически {sorted(set(pos))}, "
                            f"вне {len(bad)} тиков)"))
        same = [(a, b) for (a, p1), (b, p2) in zip(zip(at, pos), zip(at[1:], pos[1:])) if p1 == p2]
        out.append((not same, f"pos чередуются 0/100 (подряд одинаковых: {len(same)} пар)"))
    out.append((all(b - a > 0 for a, b in zip(at, at[1:])), "at строго возрастают"))
    min_interval = int(cfg["min_interval_ms"])
    gaps = [b - a for a, b in zip(at, at[1:])]
    out.append((all(b - a >= min_interval for a, b in zip(at, at[1:])),
                f"минимальный интервал {min_interval} мс (фактически min {min(gaps) if gaps else 0} мс)"))
    # плато = соседние тики с одинаковым pos (устройство стоит). Правило для обоих режимов
    # pos: binary чередует 0/100, amplitude-aware меняет величину
    same = [(a, b) for (a, p1), (b, p2) in zip(zip(at, pos), zip(at[1:], pos[1:])) if p1 == p2]
    out.append((not same, f"pos меняются, плато нет (подряд одинаковых: {len(same)} пар)"))
    out.append((at[0] == 0, f"первый тик в 0 (фактически {at[0]}))"))
    out.append((at[-1] == duration_ms, f"последний тик в {duration_ms} мс (фактически {at[-1]}))"))
    speed_limit = float(cfg.get("speed_limit_units_per_s", SPEED_LIMIT_DEFAULT))
    speeds = [abs(p2 - p1) / ((b - a) / 1000.0) for (a, p1), (b, p2) in zip(zip(at, pos), zip(at[1:], pos[1:]))]
    worst = max(speeds) if speeds else 0.0
    out.append((worst <= speed_limit,
                f"скорость <= {speed_limit:.0f} ед/с (фактически max {worst:.0f})"))
    # разрывы: шаг фазы = медианный интервал между экстремумами (фактический полупериод).
    # Граница = **3.5 полупериода**: интервалы экстремумов не равны медиане (у seg-0141
    # 880 мс при медиане 400). 2.5 резало **движение** быстрых клипов: seg-0156 интервал
    # 320 мс при медиане 120, pos 100->0 = штрих 312 ед/с. Разрыв **допустим**, где
    # консенсус не мерит движение (амплитуда консенсуса на интервале < min_amplitude_px):
    # трекеров нет, плато честное. `phase_fill` выключен, фазовые тики через пропажу
    # не ставятся. Склейка считает так же (`funscript_merge.merged_gap_check`)
    step = phase_step(clip, cfg, min_interval)
    bound = round(3.5 * step)
    sig = clip_out_dir(clip, cfg) / "signal.csv"
    min_amp = float(cfg["min_amplitude_px"])
    min_stroke = int(cfg["min_stroke_units"])
    # длинный разрыв честен, где pos соседних тиков различаются < min_stroke: один долгий
    # glide устройства, а не серия циклов (замер sexy-s002: 14000 pos 37 -> 14960 pos 56 =
    # 19 единиц за 960 мс). Тот же критерий в `funscript_build.fill_gaps`
    bad_gaps = [(a, b) for (a, p1), (b, p2) in zip(zip(at, pos), zip(at[1:], pos[1:]))
                if b - a > bound and local_amp(sig, a, b) >= min_amp
                and abs(p2 - p1) >= min_stroke]
    # skip_gaps: склейка считает разрывы по шагу каждого сегмента (merged_gap_check),
    # общий медианный шаг по всему скрипту режет плато медленного сегмента
    binary = bool(cfg.get("pos_binary", True))
    if binary:
        # в бинарном режиме (0 -> 100 -> 0) длинный ход pos 0->100 без тика в середине
        # честен: середина монотонного хода = pos 50, которого в 0/100-скрипте нет.
        # Плато по-прежнему запрещён (соседний одинаковый pos). Разрывы, где трек пропал,
        # закрывает проекция; если измеренный ход один и длинный, тика по середине нет
        out.append((not same,
                    f"разрывы: бинарный 0/100 — длинный ход без pos 50 честен "
                    f"(плато {len(same)}, max {max(gaps) if gaps else 0} мс, "
                    f"полупериод {step} мс)"))
    elif not skip_gaps:
        out.append((not bad_gaps,
                    f"разрывы <= 3.5 полупериода ({step} мс) = {bound} мс там, где консенсус "
                    f"мерит движение (amax >= {min_amp} px); превышений {len(bad_gaps)}, "
                    f"max разрыв {max(gaps) if gaps else 0} мс"))
    # формат эталона funscript/example.funscript: ключи сортированы, действия {at,pos},
    # metadata.duration в секундах, deviceTime/actionTrack нет
    want_keys = ["actions", "inverted", "metadata", "range", "version"]
    out.append((sorted(payload.keys()) == want_keys,
                f"ключи {want_keys} (фактически {sorted(payload.keys())})"))
    out.append((payload.get("version") == "1.0" and payload.get("inverted") is False
                and int(payload.get("range", -1)) == int(cfg["range"]),
                f"version 1.0, inverted false, range {cfg['range']} "
                f"(фактически {payload.get('version')}, {payload.get('inverted')}, "
                f"{payload.get('range')})"))
    out.append((all(list(a.keys()) == ["at", "pos"] for a in actions),
                f"действия {list(actions[0].keys())} (порядок at, pos)"))
    meta = payload.get("metadata") or {}
    waves = meta.get("waves")
    wave_rate = meta.get("wave_rate")
    out.append((isinstance(waves, int) and waves >= 0 and isinstance(wave_rate, (int, float))
                and wave_rate >= 0,
                f"metadata.waves {waves} и wave_rate {wave_rate} целые >= 0"))
    expected = waves * 1000.0 / max(duration_ms, 1) if isinstance(waves, int) else 0.0
    out.append((isinstance(wave_rate, (int, float)) and abs(float(wave_rate) - expected) <= 0.05,
                f"wave_rate = waves / длительность ({expected:.3f} волн/с, "
                f"фактически {wave_rate})"))
    out.append((int(meta.get("duration", -1)) == int(round(duration_ms / 1000.0)),
                f"metadata.duration = {int(round(duration_ms / 1000.0))} с "
                f"(фактически {meta.get('duration')})"))
    out.append(("deviceTime" not in json.dumps(payload) and "actionTrack" not in payload,
                "deviceTime/actionTrack отсутствуют"))
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--video", default=str(ROOT / "video_debug" / "debug.mp4"))
    p.add_argument("--sidecar", default=None, help="путь к .funscript; по умолчанию рядом с клипом")
    p.add_argument("--cfg", default=None)
    a = p.parse_args()

    cfg = load_config(Path(a.cfg) if a.cfg else None)
    clip = Path(a.video)
    sidecar = Path(a.sidecar) if a.sidecar else clip.parent / (clip.stem + ".funscript")
    if not sidecar.is_file():
        raise SystemExit(f"{sidecar} не найден")
    # длительность = format контейнера: то, что показывает плеер. видеопоток короче
    # контейнера на AAC-хвост склейки, и скрипт выравнивается по концу плеера, не по потоку
    info = probe(clip, cfg)
    duration_ms = info["duration_ms"]
    payload = json.loads(sidecar.read_text(encoding="utf-8"))

    gap_merged = merged_gap_rows(clip_out_dir(clip, cfg) / "merged.csv", cfg)
    results = check_payload(payload, duration_ms, cfg, clip, skip_gaps=gap_merged is not None)
    if gap_merged is not None:
        results.append(gap_merged)
    fails = 0
    for ok, line in results:
        print(("PASS  " if ok else "FAIL  ") + line)
        fails += 0 if ok else 1
    n = len(payload["actions"])
    meta = payload.get("metadata") or {}
    waves, wave_rate = meta.get("waves"), meta.get("wave_rate")
    ticks_csv = clip_out_dir(clip, cfg) / "ticks.csv"
    kinds = ""
    if ticks_csv.is_file():
        rows = read_rows(ticks_csv, TICK_COLUMNS)
        ext = [r for r in rows if r["kind"] == "extremum"]
        kinds = (f", измеренных {len(ext)}, slope "
                 f"{sum(1 for r in rows if r['kind'] == KIND_SLOPE)}, "
                 f"проекций {sum(1 for r in rows if r['kind'] == KIND_PROJECT)}, "
                 f"фазы {sum(1 for r in rows if r['kind'] == 'phase')}, "
                 f"поддержка >= {cfg['min_tick_support']}: "
                 f"{sum(1 for r in ext if int(r['support']) >= int(cfg['min_tick_support']))}")
    print(f"INFO  {sidecar.name}: {n} тиков, {duration_ms} мм, волн {waves}, "
          f"{n / (duration_ms / 1000):.2f} тиков/с, {wave_rate} волн/с{kinds}")
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()
