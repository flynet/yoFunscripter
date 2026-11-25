"""Экстремумы консенсус-сигнала -> .funscript.

    python scripts/funscript_build.py                     # debug.mp4 (нужен track.csv)
    python scripts/funscript_build.py --video "video/2 (1)/part_22_20.mp4"

Выход:
    sidecar рядом с клипом: video/<dir>/<stem>.funscript
    runs/funscript/<stem>/funscript.json   тот же JSON (артефакт для viewer)
    runs/funscript/<stem>/ticks.csv        ms, pos, kind, peak, support

Тики:
  - экстремумы консенсуса всех живых треков (пики и впадины), время — субкадровая парабола
    по нативным кадрам, то есть natивно неравномерное;
  - тик остаётся, если его подтверждают >= `min_tick_support` трекеров (экстремум того же
    знака в +/- `tick_support_ms`): одиночный экстремум одного трекера = LK-джиттер;
  - `pos_binary: true`: пик = 100, впадина = 0. `pos_binary: false`: pos = нормировка
    консенсуса 0..100 по всему клипу, то есть слабый движок даёт pos около центра, сильный
    — весь диапазон, и длина волны равна измеренной амплитуде (замер sexy-s002: все 172
    тика по 0<->100 на равномерной сетке 400 мс при реальных полупериодах 160-180 мс);
  - якоря 0 и duration_ms = pos консенсуса в этих кадрах (измеренная позиция; если сигнала
    нет — 0, устройство в покое);
  - `phase_fill: false`: разрывы остаются плато. Фазовые тики = сетка по медианному шагу
    одного трека (замер sexy-s002: 138 из 172 тиков фазовые, waves 85 при 16 измеренных
    волнах);
  - `waves` = полных волн по **измеренным** тикам (минимум из пиков и впадин),
    `wave_rate` = waves / длительность. Оба пишутся в `metadata` sidecar'а: по `wave_rate`
    сортируют клипы при склейке, по waves отсекают клипы без движения (`min_waves`).
    По всем тикам (фазовые + якоря) waves мерилась по выдуманной сетке.

Формат sidecar единственный: `{"actions":[{"at":..,"pos":..}], "version":..., "inverted":...,
"range":...}` — как эталон funscript/example.funscript. deviceTime/actionTrack никогда:
смешанный формат ломает скрипт в редакторе и в ScriptPlayer.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from .paths import model_path
from pathlib import Path

import numpy as np

from .funscript_common import (
    ROOT, TRACK_COLUMNS, clip_out_dir, frame_ms_of, load_config, read_rows, sha1_short,
    video_duration_ms, write_rows,
)

from .funscript_signal import signal_artifacts

# вид тика: extremum (измеренный экстремум консенсуса) / phase(экстраполяция через пропажу)
# / anchor(0 и конец)
KIND_EXTREMUM = "extremum"
KIND_PHASE = "phase"
KIND_ANCHOR = "anchor"
KIND_SLOPE = "slope"        # измеренная pos на длинном ходе (экстремума нет, устройство идёт)
KIND_PROJECT = "project"    # экстремум проекции: волна продолжена по фазе через пропажу трека

# гейты консенсуса, при которых тиков не строится: движению нужно измеренное движение
# (`low_amplitude`), периодичность измеренного сегмента (`no_periodicity`) и подтверждения
# детекций (`weak_detections`). `low_coverage` и `low_support` тики не запрещают
FATAL_GATES = ("low_amplitude", "no_periodicity", "weak_detections")
TICK_COLUMNS = ("ms", "pos", "kind", "peak", "support", "prom")


def phase_fill(accepted: list[dict], step: int, min_interval: int) -> list[dict]:
    """Разрывы больше одного шага заполняются фазовыми тиками (`kind = phase`).

    Шаг = медианный интервал между принятыми экстремумами (фактический полупериод). Slots
    ставятся по сетке от предыдущего принятого тика: k = round(gap / step) - 1, pos
    чередуется. Slot, который попадает в ту же позицию, что следующий принятый тик,
    снимается. `phase_fill: false` в конфиге — разрывы остаются плато: сетка по медианному
    шагу одного трека выдумывает движения (замер sexy-s002: 138 фазовых тиков из 172,
    waves 85 при 16 измеренных волнах). Функция остаётся для стыков склейки
    (`funscript_merge.seam_join`).
    """
    out = [accepted[0]]
    for prev, t in zip(accepted, accepted[1:]):
        gap = t["ms"] - prev["ms"]
        k = max(0, int(round(gap / step)) - 1)
        # slot не должен съедать min_interval перед следующим тиком
        while k > 0 and prev["ms"] + k * step > t["ms"] - min_interval:
            k -= 1
        for i in range(1, k + 1):
            out.append({"ms": prev["ms"] + i * step,
                        "pos": prev["pos"] if i % 2 == 0 else 100 - prev["pos"],
                        "kind": KIND_PHASE, "peak": "", "support": 0, "prom": 0.0})
        if out[-1]["kind"] == KIND_PHASE and out[-1]["pos"] == t["pos"]:
            out.pop()
        out.append(t)
    return out


def waves_of(ticks: list[dict]) -> int:
    """Полных волн = минимум из пиков и впадин по **измеренным** тикам.

    Волна = пик + впадина, полный цикл. Считаем по тикам `kind = extremum` (у них есть
    `peak`), фазовые, slope и якоря не дают волн: по всем тикам sexy-s002 дал waves 85 при
    16 измеренных волнах, и `min_waves` отсеивал/ kept по выдуманной сетке.
    """
    peaks = sum(1 for t in ticks if t["kind"] == KIND_EXTREMUM and t.get("peak") == "peak")
    troughs = sum(1 for t in ticks if t["kind"] == KIND_EXTREMUM and t.get("peak") == "trough")
    return min(peaks, troughs)


def fill_gaps(accepted: list[dict], extrema: list[dict], bound: int, min_interval: int,
              min_amp: float, min_stroke: int, pos_of, prom_of, local_amp,
              mid_best) -> tuple[list[dict], int]:
    """Разрывы больше `bound` закрываются измеренными тиками, сетка не равномерная.

    Порядок честности:
      1. экстремум с поддержкой >= 1 (подтверждён хотя бы одним трекером);
      2. длинный монотонный ход (amax >= min_amp, экстремумов внутри нет — 11860..12460
         amax 121 px, 6820..7460 amax 68 px): pos в середине хода (`kind = slope`), время —
         кадр сигнала, разрыв делится пополам;
      3. цикл по всем интервалам, пока самый длинный разрыв <= bound.

    Экстремум консенсуса с поддержкой 0 (усреднение двух трекеров, ни один трекер сам не
    даёт экстремума) не принимается: его подтверждает только сам консенсус. `pos` тика не
    совпадает с соседним (плато = нет движения), интервалы >= min_interval.

    Slope-тик ставится только если pos соседей различаются >= `min_stroke` (замер sexy-s002:
    разрыв 48960..50760 = 1800 мс при размахе z 0.81, деление пополам даёт pos 25->9->8,
    то есть устройство стоит, а сетка придумана).
    """
    out = [accepted[0]]
    filled = 0
    for prev, nxt in zip(accepted, accepted[1:]):
        items = []
        if nxt["ms"] - prev["ms"] > bound and local_amp(prev["ms"], nxt["ms"]) >= min_amp:
            last = prev
            for e in sorted((e for e in extrema if prev["ms"] < e["ms"] < nxt["ms"]),
                            key=lambda e: e["ms"]):
                ms = int(round(e["ms"]))
                if ms - last["ms"] < min_interval or nxt["ms"] - ms < min_interval:
                    continue
                pos = pos_of(e)
                if pos == last["pos"] or e["support"] < 1:
                    continue
                items.append({"ms": ms, "pos": pos,
                              "kind": KIND_PROJECT if e.get("projected") else KIND_EXTREMUM,
                              "peak": e["kind"],
                              "support": int(e["support"]), "prom": round(prom_of(e), 3)})
                last = items[-1]
                filled += 1
            # хвост цепочки, совпадающий с `nxt` = плато (64140 pos 100 -> 66300 pos 0:
            # проверка pos == nxt на каждом экстремуме отбрасывала все впадины пары)
            while items and items[-1]["pos"] == nxt["pos"]:
                items.pop()
            segs = [prev] + items + [nxt]
            pairs = [(a, b) for a, b in zip(segs, segs[1:])
                     if b["ms"] - a["ms"] > bound and abs(b["pos"] - a["pos"]) >= min_stroke]
            while pairs:
                a, b = max(pairs, key=lambda s: s[1]["ms"] - s[0]["ms"])
                ms, pos = mid_best(a["ms"], b["ms"], a["pos"], b["pos"])
                if ms is None or ms - a["ms"] < min_interval or b["ms"] - ms < min_interval \
                        or pos == a["pos"] or pos == b["pos"]:
                    pairs.remove((a, b))
                    continue
                segs.insert(segs.index(a) + 1, {"ms": ms, "pos": pos, "kind": KIND_SLOPE,
                                                "peak": "", "support": 0, "prom": 0.0})
                filled += 1
                pairs = [(x, y) for x, y in zip(segs, segs[1:])
                         if y["ms"] - x["ms"] > bound and abs(y["pos"] - x["pos"]) >= min_stroke]
            out += segs[1:-1]
        out.append(nxt)
    return out, filled


def ticks_from(fusion: dict, cfg: dict, duration_ms: int) -> list[dict]:
    """Экстремумы консенсуса -> тики {ms, pos, kind, peak, support}. Пусто, если сигнала нет."""
    extrema = fusion["extrema_list"]
    strong = [e for e in extrema if e["support"] >= int(cfg["min_tick_support"])]
    if len(strong) < int(cfg["min_peaks"]):
        return []
    # проекционные экстремумы (разрыв поддержки) принимаются без `min_tick_support`: их
    # подтверждает сам консенсус (поддержка 1), трекеров в разрыве нет. Гейт min_peaks
    # меряется по измеренным, чтобы клип не проходил по выданному колебанию
    picked = sorted([e for e in extrema if e["support"] >= int(cfg["min_tick_support"])
                     or e.get("projected")], key=lambda e: e["ms"])
    binary = bool(cfg.get("pos_binary", True))
    frame_ms = float(fusion["frame_ms"])
    pos_arr = np.asarray(fusion["pos"], dtype=float)
    zamp_arr = np.asarray(fusion["z_amp"], dtype=float)
    full_ratio = float(cfg["full_stroke_ratio"])
    if binary:
        # полный ход = pos 0/100, и в бинарном режиме промежуточных позиций нет вовсе:
        # частичный wobble (ход < full_stroke_ratio) не становится тиком (замер sexy-s020:
        # 29 тиков стояли на pos 87..93 = дрожащий LK-бокс на статичном кадре, устройство
        # в этих кадрах не было ни в верху, ни в низу)
        picked = [e for e in picked if float(e.get("frac", 1.0)) >= full_ratio]

    def prom_of(e: dict) -> float:
        """Доля локального полного хода, которую делает экстремум: ход (z до ближайшего
        экстремума противоположного знака) ÷ медиана ходов по соседним экстремумам.
        Проставляет `stroke_fraction` в `funscript_signal`. Window-prominence не годится:
        оно мерит высоту над контуром к более высокому соседу и занижает ход рядом с
        глубокой впадиной (sexy-s002: 30 из 33 полных ходов имели prominence 0.40..0.74)."""
        return float(e.get("frac", 1.0))

    def pos_at(ms: float) -> int | None:
        """pos консенсуса в кадре `ms` (нормировка по всему клипу), None где сигнала нет."""
        i = int(round(ms / frame_ms))
        if 0 <= i < pos_arr.size and np.isfinite(pos_arr[i]):
            return int(round(float(pos_arr[i])))
        return None

    def pos_of(e: dict) -> int:
        """Позиция тика. Полный ход = 0/100, частичный — измеренная pos.

        Ход устройства 0 -> 100 -> 0: экстремум, чей **ход** (z до ближайшего экстремума
        противоположного знака) >= `full_stroke_ratio` медианы локальных ходов — полный ход,
        pos 0/100. Меньшая доля = частичный wobble; pos 0/100 приписала бы ему весь ход,
        ставится измеренная pos. Замер sexy-s002: 30 из 33 вне-0/100 экстремумов — полный
        ход по этому критерию, настоящих wobble 3.
        """
        if not binary:
            p = pos_at(e["ms"])
            return p if p is not None else 50
        if prom_of(e) >= full_ratio:
            return 100 if e["kind"] == "peak" else 0
        p = pos_at(e["ms"])
        return p if p is not None else (100 if e["kind"] == "peak" else 0)

    # интервал = max(floor из cfg["min_interval_ms"], 100 единиц / speed_limit). При
    # speed_limit 1000 ед/с это 100 мс, то есть каждый экстремум сигнала становится тиком:
    # 100 единиц (0->100) не быстрее лимита устройства. Интервал больше полупериода рвёт
    # чередование pos (замер debug: interval 200 при периоде 320 -> pos 100->100 подряд)
    speed_limit = float(cfg["speed_limit_units_per_s"])
    min_interval = max(int(cfg["min_interval_ms"]), int(math.ceil(100 * 1000.0 / speed_limit)))

    ticks: list[dict] = []
    for e in picked:
        ms = int(round(e["ms"]))
        pos = pos_of(e)
        # экстремум ближе min_interval к предыдущему, к началу или к концу клипа
        # отбрасывается: якоря 0 и duration фиксированы, и интервал якорь->экстремум =
        # движение (замер seg-0112, seg-0114: первый экстремум на 90 мс -> скорость 1111 ед/с)
        if (ticks and ms - ticks[-1]["ms"] < min_interval
                or ms < min_interval or duration_ms - ms < min_interval):
            continue
        # два тика подряд с одинаковой позицией = нет движения (0->100->100->0): плато
        # запрещён в обоих режимах pos
        if ticks and pos == ticks[-1]["pos"]:
            continue
        ticks.append({"ms": ms, "pos": pos,
                      "kind": KIND_PROJECT if e.get("projected") else KIND_EXTREMUM,
                      "peak": e["kind"],
                      "support": int(e["support"]), "prom": round(prom_of(e), 3)})
    if not ticks:
        return []
    # якоря: binary = позиция, противоположная соседнему экстремуму (0/100 чередуются,
    # якорь по знаку сигнала даёт n = 0 и плато на старте — замер seg-0102);
    # amplitude-aware = измеренный pos консенсуса в этих кадрах, где сигнала нет — 0
    anchor_first = 100 - ticks[0]["pos"] if binary else (pos_at(0) if pos_at(0) is not None else 0)
    anchor_last = 100 - ticks[-1]["pos"] if binary else (pos_at(duration_ms) if pos_at(duration_ms) is not None else 0)
    accepted = [{"ms": 0, "pos": anchor_first, "kind": KIND_ANCHOR, "peak": "", "support": 0,
                 "prom": 0.0}]
    accepted += ticks
    accepted.append({"ms": int(duration_ms), "pos": anchor_last, "kind": KIND_ANCHOR,
                     "peak": "", "support": 0, "prom": 0.0})

    # шаг фазы = медианный интервал сильных экстремумов (фактический полупериод); разрывы
    # больше 3.5 полупериодов закрывают измеренными тиками (замер sexy-s002: 8 разрывов
    # > 560 мс при амплитуде консенсуса 68..137 px = плато на измеренном движении).
    # Проекционные тики в медиану не входят: их темп = темп измеренного сегмента
    ext_ms = [t["ms"] for t in ticks if t["kind"] == KIND_EXTREMUM]
    gaps = [b - a for a, b in zip(ext_ms, ext_ms[1:])]
    step = max(min_interval, int(round(statistics.median(gaps)))) if gaps else min_interval
    amp_arr = np.asarray(fusion["amp"], dtype=float)
    z_arr = np.asarray(fusion["s"], dtype=float)
    min_stroke = int(cfg["min_stroke_units"])

    def local_amp(a_ms: int, b_ms: int) -> float:
        """Измеренное движение (px) на интервале = размах z на интервале * амплитуда.

        `fusion["amp"]` — скользящее окно локального периода, и в окно попадает дрейф:
        плато 48960..50760 (размах z 0.81) выглядит амплитудой 136 px. Размах z именно
        на интервале = реальный ход устройства, и плато с ним сравнивается.
        """
        i0 = max(0, int(a_ms // frame_ms))
        i1 = min(amp_arr.size - 1, int(b_ms // frame_ms))
        seg = amp_arr[i0:i1 + 1]
        z = z_arr[i0:i1 + 1]
        m = np.isfinite(seg) & np.isfinite(z)
        if not m.any():
            return 0.0
        return float(np.max(z[m]) - np.min(z[m])) * float(np.max(seg[m]))

    def mid_best(a_ms: int, b_ms: int, a_pos: int, b_pos: int) -> tuple[int | None, int | None]:
        """Тик в середине хода: кадр, где консенсус прошёл pos между `a_pos` и `b_pos`.

        Время — измеренный кадр сигнала (не половина интервала). В бинарном режиме pos
        тика = середина полного хода (`(a_pos + b_pos) / 2` = 50 для 0->100), то есть
        разрыв делится пополам там, где устройство реально прошло половину пути.
        """
        target = (a_pos + b_pos) / 2.0
        # кандидат только там, где остаются интервалы >= min_interval до обоих соседних
        # тиков (замер 48720..49780: пересечение цели на 49760 даёт интервал 20 мс до
        # экстремума 49780, тик отбрасывается и разрыв 1060 мс остаётся)
        lo = max(int(a_ms // frame_ms) + 1, int(math.ceil((a_ms + min_interval) / frame_ms)))
        hi = min(int(b_ms // frame_ms), int(math.floor((b_ms - min_interval) / frame_ms)))
        best: tuple[float, int] | None = None
        for i in range(lo, hi + 1):
            if 0 <= i < pos_arr.size and np.isfinite(pos_arr[i]):
                dev = abs(float(pos_arr[i]) - target)
                if best is None or dev < best[0]:
                    best = (dev, i)
        if best is None:
            return None, None
        ms = int(round(best[1] * frame_ms))
        p = int(round(target)) if binary else int(round(float(pos_arr[best[1]])))
        if p == a_pos or p == b_pos:
            return None, None
        return ms, p

    # разрывы закрываются только в amplitude-aware режиме: slope-тик ставится на
    # измеренную pos середины хода (50), а в бинарном режиме промежуточных pos нет
    if not binary:
        accepted, _ = fill_gaps(accepted, extrema, round(3.5 * step), min_interval,
                                float(cfg["min_amplitude_px"]), min_stroke, pos_of, prom_of,
                                local_amp, mid_best)
    if bool(cfg.get("phase_fill", False)):
        accepted = phase_fill(accepted, step, min_interval)
    return accepted


def build_clip(cfg: dict, clip: Path, fusion: dict, duration_ms: int,
              model_version: str, write: bool = True,
              sidecar_dir: Path | None = None) -> dict:
    """По консенсус-сигналу -> тики и .funscript. Возвращает строку summary.csv.

    `fusion` — результат funscript_signal.signal_artifacts (он же пишет signal.csv
    и signal_meta.json, нужные viewer).
    """
    sidecar = (sidecar_dir or clip.parent) / (clip.stem + ".funscript")
    out_dir = clip_out_dir(clip, cfg)
    reason = ""
    gates = fusion.get("gates") or []
    # гейты, при которых тиков нет вовсе: амплитуда меньше `min_amplitude_px` = бокс
    # дрожит на месте, и нормировка по локальной амплитуде превращает дрожание в волну
    # (замер sexy-s020: статичный клип, амплитуда консенсуса 1.7 px, 4 трека по 0.2..0.9 px,
    # periodicity 0.44..0.65 по дрожанию LK, и 125 тиков / 57 волн на одной картинке).
    # low_coverage и low_support не запрещают тики: разрывы закрыты проекцией, и темп
    # идёт по измеренному сегменту (sexy-s005 coverage 0.438)
    fatal = [g for g in gates if g in FATAL_GATES]
    ticks = [] if fatal else ticks_from(fusion, cfg, duration_ms)
    if gates:
        reason = ",".join(gates) or "no_signal"

    waves = waves_of(ticks)
    wave_rate = round(waves * 1000.0 / max(int(duration_ms), 1), 3)
    meta = {
        "title": clip.stem,
        "creator": "yolo funscript",
        "duration": int(duration_ms),
        "totalDuration": int(duration_ms),
        "tags": ["ai-generated"],
        "model_version": model_version,
        "chosen_track": fusion["dominant_track"],
        "chosen_class": fusion["dominant_class"],
        "segment": fusion["segment"],
        "axis": None,
        "waves": waves,
        "wave_rate": wave_rate,
        "clip_mtime": int(clip.stat().st_mtime),
    }
    fmt = "funscript"          # один формат: version/inverted/range/actions
    payload = funscript_payload(ticks, meta, fmt, int(cfg["range"]))
    if write:
        # sidecar минифицирован без пробелов, ключи сортированы — как эталон
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")), encoding="utf-8")
        (out_dir / "funscript.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                                                           sort_keys=True), encoding="utf-8")
        write_rows(out_dir / "ticks.csv", TICK_COLUMNS,
                   [{"ms": t["ms"], "pos": t["pos"], "kind": t["kind"],
                     "peak": t.get("peak", ""), "support": t.get("support", 0),
                     "prom": t.get("prom", 0.0)} for t in ticks])
    return {
        "tick_list": ticks,
        "clip": str(clip),
        "sidecar": str(sidecar),
        "format": fmt,
        "ticks": len(ticks),
        "duration_ms": int(duration_ms),
        "chosen_track": fusion["dominant_track"] if fusion["dominant_track"] else "",
        "chosen_class": fusion["dominant_class"] if fusion["dominant_class"] else "",
        "segment_start": int(fusion["segment"][0]) if fusion["segment"] else "",
        "segment_end": int(fusion["segment"][1]) if fusion["segment"] else "",
        "amplitude_px": fusion["amplitude_px"],
        "coverage": fusion["coverage"],
        "periodicity": fusion["periodicity"],
        "period_ms": fusion["period_ms"],
        "update_ratio": fusion["update_ratio"],
        "waves": waves,
        "wave_rate": wave_rate,
        "reason": reason,
        "model_version": model_version,
    }


def funscript_payload(ticks: list[dict], meta: dict, fmt: str, rng: int = 100) -> dict:
    """Sidecar в эталонной форме funscript/example.funscript: ключи сортированы
    (actions, inverted, metadata, range, version), действия {at, pos}, metadata.duration
    в секундах, type "basic". deviceTime/actionTrack нет — смешанный формат ломает
    скрипт в редакторе и визуализатор ScriptPlayer.
    """
    metadata = {
        "creator": str(meta.get("creator", "")),
        "description": "",
        "duration": int(round(int(meta["duration"]) / 1000.0)),
        "license": "",
        "notes": "",
        "performers": [],
        "script_url": "",
        "tags": list(meta.get("tags", [])),
        "title": str(meta.get("title", "")),
        "type": "basic",
        "video_url": "",
        "wave_rate": round(float(meta.get("wave_rate", 0.0)), 3),
        "waves": int(meta.get("waves", 0)),
    }
    return {
        "actions": [{"at": t["ms"], "pos": t["pos"]} for t in ticks],
        "inverted": False,
        "metadata": metadata,
        "range": int(rng),
        "version": "1.0",
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--video", default=str(ROOT / "video_debug" / "debug.mp4"))
    p.add_argument("--cfg", default=None)
    p.add_argument("--weights", default=None, help="перекрыть configs/funscript.yaml:weights")
    p.add_argument("--no-write", action="store_true", help="только посчитать и напечатать")
    a = p.parse_args()

    cfg = load_config(Path(a.cfg) if a.cfg else None)
    weights = Path(a.weights) if a.weights else model_path(cfg)
    clip = Path(a.video)
    out_dir = clip_out_dir(clip, cfg)
    rows = read_rows(out_dir / "track.csv", TRACK_COLUMNS)
    if not rows:
        raise SystemExit(f"{out_dir / 'track.csv'} пуст")
    duration_ms = video_duration_ms(clip)
    frame_ms = frame_ms_of(rows)
    fusion = signal_artifacts(cfg, clip, rows, duration_ms, frame_ms)

    row = build_clip(cfg, clip, fusion, duration_ms, sha1_short(weights), not a.no_write)
    ticks = row["tick_list"]
    ext = [t for t in ticks if t["kind"] == KIND_EXTREMUM]
    gaps = [b["ms"] - a["ms"] for a, b in zip(ext, ext[1:])]
    print(f"клип {clip.name}: {row['duration_ms']} мс, тиков {row['ticks']} "
          f"(измеренных {len(ext)}), формат {row['format']}, консенсус coverage "
          f"{row['coverage']:.3f}, A {row['amplitude_px']:.1f} px, волн {row['waves']} "
          f"({row['wave_rate']} волн/с), интервалы min {min(gaps) if gaps else 0} "
          f"median {int(statistics.median(gaps)) if gaps else 0} max {max(gaps) if gaps else 0} мс" +
          (f" -> {row['reason']}" if row["reason"] else ""))
    for t in ticks:
        print(f"  {t['ms']:5d} мс pos {t['pos']:3d} {t['kind']} {t.get('peak', '')} "
              f"support {t.get('support', 0)}")
    if not a.no_write:
        print(f"sidecar: {row['sidecar']}")


if __name__ == "__main__":
    main()
