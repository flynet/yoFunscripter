"""`track.csv` -> консенсус-сигнал всех живых треков клипа.

    python scripts/funscript_signal.py                     # видео из --video
    python scripts/funscript_signal.py --video "video/2 (1)/part_22_20.mp4"

Выход:
    runs/funscript/<stem>/signal.csv        frame, ms, raw, detrended, pos, valid, support, amp
    runs/funscript/<stem>/signal_meta.json  фьюз, треки, оси, экстремумы

Как считается:
  - сигнал каждого трека по всем непрерывным живым run'ам, а не по `longest_run`: строки
    трека пишутся по кадрам, сетка = нативные кадры клипа (40 мс при 25 fps), интерполяции
    нет. Замер sexy-s002:coverage по кускам 0.287/0.474/0.487 при `min_coverage` 0.50 —
    ни один трек не проходил, union живых треков по клипу = 0.994;
  - run = непрерывный по кадрам интервал живых строк с good >= loss_good_ratio; за разрывом
    сигнал не экстраполируется, PCA-ось по каждому run своя;
  - де-тренд скользящей медианой `detrend_window_ms` по каждой координате — убирает панораму
    камеры и общее движение тела;
  - PCA де-трененной траектории run'а -> ось, проекция = s(t) в пикселях;
  - сглаживание: медианный фильтр, окно не больше половины локального периода (медианный
    интервал экстремумов): `smooth_ms` 100 при медианном полупериоде сигнала 160 мс срезает
    пики и сдвигает время тика;
  - фьюз = взвешенное среднее проекций всех живых трека по кадрам, вес = локальная амплитуда
    трека по окну `fusion_window_ms`. Записывается как `consensus = sum(s_i)/sum(amp_i)`:
    z в долях локальной амплитуды, `amp(t) = sum amp_i` = амплитуда консенсуса в px.
    Замер sexy-s002 (перекрывание cls0 и cls1, 827 точек): корреляция на нулевом лаге
    0.515, максимум 0.723 при лаге 100 мс; взвешенное по std среднее коррелирует с cls1
    0.95 — треки движутся в одну сторону, фаза при усреднении не схлопывается;
  - coverage фьюза = доля кадров с живым консенсусом (support >= 1) по всему клипу;
  - экстремум консенсуса = тик; поддержка тика = число треков с экстремумом того же знака
    в +/- `tick_support_ms` (одиночный тик одного трекера = LK-джиттер);
  - гейты фьюза: амплитуда, coverage, число экстремумов, update_ratio по контрольным кадрам,
    доля тиков с поддержкой >= `min_tick_support`.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from .funscript_common import (
    ROOT, SIGNAL_COLUMNS, STATE_LOST, STATE_UPDATE, autocorr_peak, clip_out_dir,
    find_extrema, find_extrema_runs, finite_runs, frame_ms_of, grid_times, load_config,
    local_amplitude, median_filter, median_filter_runs, moving_median, pca_axis, read_rows,
    TRACK_COLUMNS, video_duration_ms, write_rows,
)

# run короче этого числа кадров не анализируется: медианное окно де-тренда (detrend_window_ms
# / кадр = 25 при 25 fps) и локальная амплитуда на 6 точках — минимум, при котором де-тренд
# и prominence имеют смысл
MIN_RUN_FRAMES = 6


def _odd(n: int) -> int:
    return max(3, int(n) | 1)


def osc_window(values: np.ndarray, times: np.ndarray, cfg: dict, frame_ms: float) -> int:
    """Окно локальной амплитуды = два полупериода сигнала (нечётное число кадров).

    Фиксированное `fusion_window_ms` 2000 при полупериоде 160 мс мерит размах за 2 с: в него
    попадает дрейф, амплитуда раздувается, вес трекера `amp` и порог prominence
    (`prominence_ratio * amp`) растут, и реальные экстремумы (40..60 px при «амплитуде» 200 px)
    ниже порога — консенсус в разрывах sexy-s002 даёт `s` 0.2 при `amp` 200 px, экстремумов 0.
    Окно по медианному интервалу пробных экстремумов мерит один цикл колебания.
    """
    k0 = _odd(int(round(cfg["smooth_ms"] / frame_ms)))
    wide = _odd(int(round(cfg["fusion_window_ms"] / frame_ms)))
    probe = median_filter_runs(values, k0)
    loc = local_amplitude(values, wide, int(cfg["min_local_points"]))
    cand = find_extrema(probe, times, float(cfg["prominence_ratio"]) * loc,
                        int(cfg["min_interval_ms"]))
    if len(cand) >= 3:
        gaps = [b - a for a, b in zip([e["ms"] for e in cand], [e["ms"] for e in cand][1:])]
        win = _odd(int(round(2 * statistics.median(gaps) / frame_ms)))
    else:
        win = _odd(int(round(cfg["fusion_window_ms"] / frame_ms)))
    return max(_odd(int(cfg["min_local_points"])), min(win, wide))


def runs_of(rows: list[dict], alive: list[bool]) -> list[tuple[int, int]]:
    """[start, end) непрерывных по кадрам живых интервалов строк трека.

    Строки пишутся по кадрам, так что непрерывность = соседние номера кадров: разрыв по
    кадру (трек был потерян и возобновлён) = новый run.
    """
    out: list[tuple[int, int]] = []
    start = None
    for i, r in enumerate(rows):
        ok = alive[i]
        if start is None:
            if ok:
                start = i
            continue
        prev_frame = int(rows[i - 1]["frame"])
        if ok and int(r["frame"]) == prev_frame + 1:
            continue
        out.append((start, i))
        start = i if ok else None
    if start is not None:
        out.append((start, len(rows)))
    return out


def analyze_track(rows: list[dict], n_frames: int, cfg: dict, frame_ms: float) -> dict:
    """Сигнал одного трека по всем живым run'ам: arrays по кадрам + свои экстремумы.

    Индекс массива = номер кадра, кадры клипа = общая сетка фьюза, интерполяции нет:
    тик получает время измерения, а не квант сетки 20 мс.
    """
    rows = sorted(rows, key=lambda r: int(r["frame"]))
    frames = np.array([int(r["frame"]) for r in rows])
    ms = np.array([int(r["ms"]) for r in rows], dtype=float)
    x = np.array([float(r["cx"]) for r in rows])
    y = np.array([float(r["cy"]) for r in rows])
    ratio = float(cfg["loss_good_ratio"])
    alive = [r["state"] != STATE_LOST and int(r["good"]) / max(int(r["seeded"]), 1) >= ratio
             for r in rows]

    s = np.full(n_frames, np.nan)
    raw = np.full(n_frames, np.nan)
    times = np.full(n_frames, np.nan)
    times[frames] = ms
    axes: dict[tuple[int, int], list[float]] = {}
    k0 = _odd(int(round(cfg["smooth_ms"] / frame_ms)))
    min_points = int(cfg["min_local_points"])
    wins: dict[tuple[int, int], int] = {}

    for start, end in runs_of(rows, alive):
        if end - start < MIN_RUN_FRAMES:
            continue
        idx = frames[start:end]
        t = ms[start:end]
        win = _odd(int(round(cfg["detrend_window_ms"] / frame_ms)))
        dx = x[start:end] - moving_median(x[start:end], win)
        dy = y[start:end] - moving_median(y[start:end], win)
        axis, _ = pca_axis(np.column_stack([dx, dy]))
        proj = dx * axis[0] + dy * axis[1]
        amp0 = float(np.percentile(proj, 95) - np.percentile(proj, 5))
        if amp0 <= 0:
            continue
        # адаптивные окна по каждому run'у: медианный интервал пробных экстремумов =
        # локальный полупериод. smooth_ms 100 при полупериоде 160 мс = окно больше полупериода
        loc0 = local_amplitude(proj, _odd(int(round(cfg["fusion_window_ms"] / frame_ms))),
                               min_points)
        cand = find_extrema(median_filter(proj, k0), t, float(cfg["prominence_ratio"]) * loc0,
                            int(cfg["min_interval_ms"]))
        k = k0
        if len(cand) >= 3:
            gaps = [b - a for a, b in zip([e["ms"] for e in cand], [e["ms"] for e in cand][1:])]
            k = min(k0, _odd(int(statistics.median(gaps) / (2 * frame_ms))))
        s[idx] = median_filter(proj, k)
        raw[idx] = proj - float(np.median(proj))
        axes[(int(idx[0]), int(idx[-1]) + 1)] = [round(float(axis[0]), 4), round(float(axis[1]), 4)]
        # ключ = интервал кадров, а не index строк: `s` indexed by frame
        wins[(int(idx[0]), int(idx[-1]) + 1)] = osc_window(s[idx], t, cfg, frame_ms)

    # локальная амплитуда по окну локального периода каждого run'а, а не по единому
    # fusion_window_ms: в 2000-мс окно попадает дрейф, amplituda раздувается, и вес трекера
    # `amp` в фьюзе делит проекцию на раздутый размах (sexy-s002: z 0.2 при amp 200 px)
    amp = np.full(n_frames, np.nan)
    for (lo, hi), win in wins.items():
        seg = s[lo:hi]
        amp[lo:hi] = local_amplitude(seg, win, min_points)
    extrema: list[dict] = []
    for lo, hi in finite_runs(s):
        seg = s[lo:hi]
        seg_times = times[lo:hi]
        win = wins.get((lo, hi), _odd(int(round(cfg["fusion_window_ms"] / frame_ms))))
        loc = local_amplitude(seg, win, min_points)
        for e in find_extrema(seg, seg_times, float(cfg["prominence_ratio"]) * loc,
                              int(cfg["min_interval_ms"])):
            e["track_id"] = int(rows[0]["track_id"])
            extrema.append(e)

    # `str(...)`: в живом прогоне (`funscript_run`) rows идут из памяти, где `det` int,
    # а из track.csv — строка. Сравнение с "1" на строках из памяти давало control = 0 и
    # update_ratio = число обновлений (46 вместо 0.529) — FP-гейт weak_detections
    # никогда не срабатывал, и ложные треки попадали в консенсус
    control = sum(1 for r in rows if str(r["det"]) == "1")
    update = sum(1 for r in rows if str(r["state"]) == STATE_UPDATE)
    cover = float(np.isfinite(s).mean())
    best_run = max(finite_runs(s), key=lambda r: r[1] - r[0], default=None)
    periodicity, period_ms = (0.0, 0.0)
    if best_run is not None:
        seg = s[best_run[0]:best_run[1]]
        if seg.size > 8:
            periodicity, period_ms = autocorr_peak(seg, int(round(frame_ms)),
                                                   int(cfg["autocorr_min_ms"]),
                                                   int(cfg["autocorr_max_ms"]))
    amax = float(np.nanmax(amp)) if np.isfinite(amp).any() else 0.0
    out = {"track_id": int(rows[0]["track_id"]), "class": rows[0]["class"],
           "coverage": round(cover, 3), "amplitude_px": round(amax, 1),
           "periodicity": round(periodicity, 3), "period_ms": round(period_ms, 1),
           "score": round(amax * periodicity * cover, 2),
           "update_ratio": round(update / max(control, 1), 3),
           "control_frames": control, "update_frames": update,
           "extrema": len(extrema), "extrema_list": extrema, "axes": axes,
           "runs": [(int(a), int(b)) for a, b in finite_runs(s)],
           "s": s, "amp": amp, "times": times}
    gates = []
    if cover < float(cfg["min_coverage"]):
        gates.append("low_coverage")
    if amax < float(cfg["min_amplitude_px"]):
        gates.append("low_amplitude")
    if update / max(control, 1) < float(cfg["min_update_ratio"]):
        gates.append("weak_detections")
    out["gates"] = gates
    out["ok"] = not gates
    return out


def smooth_adaptive(values: np.ndarray, times: np.ndarray, cfg: dict,
                    frame_ms: float) -> tuple[np.ndarray, np.ndarray]:
    """Медианный фильтр консенсуса с окном <= половины локального периода + локальная амплитуда.

    Окно амплитуды = два полупериода (как `osc_window`), фиксированный `fusion_window_ms`
    раздувает амплитуду дрейфом и режет экстремумы prominence'ом. Возвращает
    (s, локальная амплитуда по окну локального периода).
    """
    min_points = int(cfg["min_local_points"])
    k0 = _odd(int(round(cfg["smooth_ms"] / frame_ms)))
    wide = _odd(int(round(cfg["fusion_window_ms"] / frame_ms)))
    probe = median_filter_runs(values, k0)
    loc0 = local_amplitude(values, wide, min_points)
    cand = find_extrema(probe, times, float(cfg["prominence_ratio"]) * loc0,
                        int(cfg["min_interval_ms"]))
    k = k0
    win = wide
    if len(cand) >= 3:
        gaps = [b - a for a, b in zip([e["ms"] for e in cand], [e["ms"] for e in cand][1:])]
        med = float(statistics.median(gaps))
        k = min(k0, _odd(int(med / (2 * frame_ms))))
        win = max(_odd(int(cfg["min_local_points"])),
                  min(_odd(int(round(2 * med / frame_ms))), wide))
    s = median_filter_runs(values, k)
    return s, local_amplitude(s, win, min_points)


def _gap_runs(values: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) внутренних разрывов массива: конечные значения с обеих сторон.

    Край клипа (разрыв у 0 или у конца) не проектируется: проектировать не от чего,
    и якорь там измеренный.
    """
    finite = np.isfinite(values)
    n = values.size
    out: list[tuple[int, int]] = []
    i = 0
    while i < n:
        if finite[i]:
            i += 1
            continue
        hi = i
        while hi < n and not finite[hi]:
            hi += 1
        if i > 0 and hi < n:
            out.append((i, hi))
        i = hi
    return out


def _sin_period_fit(t: np.ndarray, v: np.ndarray, cfg: dict, frame_ms: float):
    """(rms, period, coef) подгонки [1, t, cos(w t), sin(w t)] по сетке кандидатов периода.

    Автокорреляция по кадрам требует равномерной сетки: перед разрывом samples идут
    кусками (sexy-s005: runs по 7 кадров через 8 пустых кадров), лаг округляется по
    сетке, и период не находится (periodicity < 0.30, проекция пропускала все разрывы).
    Подгонка по известным временам (Lomb-Scargle) работает по разреженной выборке.
    Линейный член обязателен: `s` нормализуется по каждому run'у отдельно, и
    дрейф трека (sexy-s005: бокс cls4 за первые 3 с cy 385→400) даёт тренд по
    окну хвоста, который подгонка без тренда принимает за колебание и режет по
    `project_fit_tol`.
    """
    best = None
    step = max(int(round(frame_ms)), 10)
    for per in range(int(cfg["autocorr_min_ms"]), int(cfg["autocorr_max_ms"]) + 1, step):
        w = 2.0 * math.pi / per
        m = np.column_stack([np.ones(t.size), t - t.mean(), np.cos(w * t), np.sin(w * t)])
        coef, *_ = np.linalg.lstsq(m, v, rcond=None)
        rms = float(np.sqrt(np.mean((v - m @ coef) ** 2)))
        if best is None or rms < best[0]:
            best = (rms, per, coef)
    return best


def project_gaps(s: np.ndarray, times: np.ndarray, cfg: dict, frame_ms: float) -> np.ndarray:
    """Разрывы консенсуса продлеваются колебанием последнего цикла; возвращает маску проекции.

    `s` и `times` дополняются прямо на кадрах разрыва. Период, амплитуда и фаза —
    подгонка [1, t, cos(w t), sin(w t)] по последним `project_win_ms` измеренным кадрам
    (`_sin_period_fit`); фаза догоняется до первого измеренного кадра после разрыва,
    чтобы кривая не рвалась на стыке. Амплитуда держится не ниже `project_amp_floor`:
    волна идёт с тем же темпом и полным ходом до нового обнаружения, и на графике нет
    ямы (замер sexy-s005: 13 разрывов 5.96 с из 10.36 с, в том числе 1640 и 1280 мс).
    Разрыв короче `project_min_ms` не проектируется (медианный фильтр его закрывает);
    останок подгонки больше `project_fit_tol` амплитуды — фазы нет, разрыв плато.
    """
    proj = np.zeros(s.size, dtype=bool)
    if not bool(cfg.get("project", True)):
        return proj
    win = max(6, int(round(int(cfg["project_win_ms"]) / frame_ms)))
    decay = float(cfg["project_decay_per_s"])
    floor = float(cfg["project_amp_floor"])
    min_periodicity = float(cfg["project_min_periodicity"])
    tol = float(cfg["project_fit_tol"])
    for lo, hi in _gap_runs(s):
        if int(round((hi - lo) * frame_ms)) < int(cfg["project_min_ms"]):
            continue
        left = np.flatnonzero(np.isfinite(s[:lo]))
        if left.size < 6:
            continue
        idx = left[-min(win, left.size):]
        t = times[idx]
        v = s[idx]
        rms, per, coef = _sin_period_fit(t, v, cfg, frame_ms)
        a, _, b, c = (float(x) for x in coef)
        amp = math.hypot(b, c)
        if per <= 0 or amp <= 0.0:
            continue
        if rms > tol * amp or 1.0 - rms / amp < min_periodicity:
            continue
        w = 2.0 * math.pi / per
        t_ref = float(t[-1])
        phase = math.atan2(c, b)
        # фаза подтягивается к стыку: cos(w t_hi - psi) = (s[hi] - a) / amp, корень
        # ближайший к фазе левого сегмента, чтобы значение на первом кадре после
        # разрыва сшлось, а не перепрыгнуло
        theta = w * (hi * frame_ms - t_ref)
        target = max(-1.0, min(1.0, (float(s[hi]) - a) / amp))
        root = math.acos(target)
        cands = (theta - root, theta + root)
        psi = min(cands, key=lambda p: abs(((p - phase + math.pi) % (2.0 * math.pi)) - math.pi))
        for j in range(lo, hi):
            t_j = j * frame_ms
            g = max(amp * math.exp(-decay * (t_j - t_ref) / 1000.0), floor * amp)
            # линейный член подгонки в проекцию не переносится: тренд хвоста — дрейф
            # объекта, а не движение, и наружу по 1.6 с разрыва он уводит кривую
            s[j] = a + g * math.cos(w * t_j - psi)
            times[j] = t_j
            proj[j] = True
    return proj


def fuse(tracks: list[dict], n_frames: int, cfg: dict, frame_ms: float) -> dict:
    """Консенсус всех живых треков по кадрам: z в долях локальной амплитуды и amp в px.

    Взвешенное среднее нормированных проекций (вес = локальная амплитуда трека) =
    `sum(s_i)/sum(amp_i)`: сильный трек ведёт, слабый добавляет фазу, и z остаётся
    сопоставимой величиной по всему клипу.
    """
    times = np.full(n_frames, np.nan)
    for tr in tracks:
        m = np.isfinite(tr["times"])
        times[m] = tr["times"][m]
    num = np.zeros(n_frames)
    den = np.zeros(n_frames)
    support = np.zeros(n_frames, dtype=int)
    for tr in tracks:
        m = np.isfinite(tr["s"]) & np.isfinite(tr["amp"])
        num[m] += tr["s"][m]
        den[m] += tr["amp"][m]
        support[m] += 1
    ok = den > 0
    z = np.full(n_frames, np.nan)
    z[ok] = num[ok] / den[ok]
    s, _ = smooth_adaptive(z, times, cfg, frame_ms)
    # локальная амплитуда = по каждому живому run'у, как в `analyze_track`: окно по
    # всему ряду захватывает соседние run'ы через пустые кадры, амплитуда раздувается
    # дрейфом, и порог prominence (`prominence_ratio * loc`) режет реальные края run'а
    # (sexy-s005: run 45..52 z -0.22..0.78, окно через разрыв даёт loc 1.14, порог 0.28,
    # prominence края 0.56 — экстремум отброшен)
    proj = project_gaps(s, times, cfg, frame_ms)
    loc = np.full(n_frames, np.nan)
    for lo, hi in finite_runs(s):
        seg = s[lo:hi]
        win = osc_window(seg, times[lo:hi], cfg, frame_ms)
        loc[lo:hi] = local_amplitude(seg, win, int(cfg["min_local_points"]))
    amp = np.full(n_frames, np.nan)
    amp[ok] = den[ok]
    if proj.any():
        amp[proj] = float(np.median(den[ok])) if ok.any() else 0.0
    meas = np.isfinite(s) & ~proj
    return {"times": times, "s": s, "amp": amp, "z_amp": loc, "support": support,
            "projected": proj, "coverage": float(meas.mean())}


def stroke_fraction(extrema: list[dict], times, s) -> None:
    """Экстремуму проставляется `stroke` (ход в z до ближайшего экстремума противоположного
    знака) и `frac` = stroke / медиана ходов по 5 соседним экстремумам.

    Критерий полного хода = ход, а не prominence: prominence (высота над контуром, ведущим
    к более высокому соседу) занижает ход там, где рядом глубокая впадина. Замер sexy-s002:
    из 33 экстремумов с pos вне 0/100 **30 имеют frac >= 0.75** (ход = локальный полный ход,
    prominence при этом 0.40..0.74), настоящих частичных wobble 3 (frac 0.25/0.64/0.71).
    Медиана frac у тиков 0/100 = 1.0, p10 0.88 — критерий разделяет чисто.
    """
    ok = np.isfinite(times) & np.isfinite(s)
    T, Z = np.asarray(times)[ok], np.asarray(s)[ok]
    if T.size == 0:
        return

    def z_at(ms: float) -> float:
        return float(Z[int(np.argmin(np.abs(T - ms)))])

    ext = sorted(extrema, key=lambda e: e["ms"])
    strokes: list[float | None] = []
    for k, e in enumerate(ext):
        best = None
        for j in (k - 1, k + 1):
            if 0 <= j < len(ext) and ext[j]["kind"] != e["kind"]:
                d = abs(z_at(e["ms"]) - z_at(ext[j]["ms"]))
                if best is None or d > best:
                    best = d
        strokes.append(best)
    for k, e in enumerate(ext):
        w = [x for x in strokes[max(0, k - 2):k + 3] if x is not None]
        ref = statistics.median(w) if w else 0.0
        e["stroke"] = round(float(strokes[k]), 4) if strokes[k] is not None else 0.0
        e["frac"] = round(strokes[k] / ref, 3) if strokes[k] is not None and ref > 0 else 1.0


def tick_support(extrema: list[dict], track_extrema: list[dict], ms: float, kind: str,
                window_ms: int) -> int:
    """Сколько трекеров дают экстремум того же знака рядом с тиком.

    Все трекеры в клипе движутся в одну сторону (замер cls0/cls1: корреляция 0.515 на
    нулевом лаге, 0.723 при лаге 100 мс), поэтому согласие трекеров = уверенность тика.
    Одиночный экстремум одного трекера (LK-джиттер) — кандидата на фантомный тик.
    """
    return sum(1 for e in track_extrema
               if e["kind"] == kind and abs(e["ms"] - ms) <= window_ms)


def signal_artifacts(cfg: dict, clip: Path, rows: list[dict], duration_ms: int,
                     frame_ms: float) -> dict:
    """Анализ всех треков + фьюз + артефакты signal.csv / signal_meta.json."""
    n_frames = max(int(r["frame"]) for r in rows) + 1
    per_track = [analyze_track(tr, n_frames, cfg, frame_ms)
                 for _, tr in sorted(_group(rows).items())]
    # в консенсус берутся все треки, кроме ложных по FP-гейту (`weak_detections`):
    # coverage по всему клипу у фрагментированных треков 0.02..0.49 и `min_coverage`
    # режет живые куски (sexy-s002: 8 треков, union coverage 0.994); ложный трек
    # (детекции не подтверждают бокс) добавлял в консенсус LK-джиттер
    live = [tr for tr in per_track if "weak_detections" not in tr["gates"]]
    fused = fuse(live, n_frames, cfg, frame_ms)
    s, times, z_amp, support = fused["s"], fused["times"], fused["z_amp"], fused["support"]
    proj = fused["projected"]
    speed_limit = float(cfg["speed_limit_units_per_s"])
    interval = max(int(cfg["min_interval_ms"]), int(np.ceil(100 * 1000.0 / speed_limit)))
    extrema = find_extrema_runs(s, times, float(cfg["prominence_ratio"]) * z_amp, interval)
    track_extrema = [e for tr in live for e in tr["extrema_list"]]
    for e in extrema:
        i = min(int(round(e["ms"] / frame_ms)), n_frames - 1)
        e["projected"] = bool(proj[i])
        # поддержка = трекеры, дающие экстремум того же знака, + 1 за цикл консенсуса.
        # В разрыве трекеров нет, и проекционный тик подтверждён самим консенсусом
        # (поддержка 1): он закрывает яму, но не проходит гейт min_tick_support
        e["support"] = tick_support(extrema, track_extrema, e["ms"], e["kind"],
                                    int(cfg["tick_support_ms"])) + 1
        e["ms"] = int(round(e["ms"]))
    stroke_fraction(extrema, times, s)
    meas_extrema = [e for e in extrema if not e["projected"]]
    strong = [e for e in meas_extrema if e["support"] >= int(cfg["min_tick_support"])]

    # pos в signal.csv = нормировка консенсуса по всему клипу (0..100) — только для
    # кривой viewer; pos тика берётся из экстремума (`pos_of`: полный ход 0/100,
    # частичный wobble = измеренная величина), не отсюда. Проекция нормируется в той же
    # шкале, чтобы кривая через разрыв шла на уровне измеренных волн
    finite = np.isfinite(s)
    meas = finite & ~proj
    pos = np.full(n_frames, np.nan)
    if finite.any():
        zmin, zmax = float(np.min(s[finite])), float(np.max(s[finite]))
        pos[finite] = np.round(100.0 * (s[finite] - zmin) / max(zmax - zmin, 1e-6))

    # update_ratio фьюза = среднее по весу coverage: фьюз живёт треками, и FP-гейт
    # min_update_ratio мерит подтверждения контрольных прогонов (state по кадрам)
    wsum = sum(tr["coverage"] for tr in live)
    upd = sum(tr["coverage"] * tr["update_ratio"] for tr in live) / max(wsum, 1e-6)
    amp_meas = np.where(proj, np.nan, fused["amp"])
    amax = float(np.nanmax(amp_meas)) if np.isfinite(amp_meas).any() else 0.0
    # нижняя граница лага = 2 медианных интервала экстремумов = полный период: при
    # lo_ms 100 и кадре 40 мс лаг округляется до 2 кадров (80 мс) и автокорреляция
    # даёт гармоника, а не период (замер sexy-s002: period_ms 80 при полупериоде 160)
    spacing = sorted(b - a for a, b in zip([e["ms"] for e in strong],
                                           [e["ms"] for e in strong][1:]))
    period_lo = max(int(cfg["autocorr_min_ms"]),
                    int(round(2 * statistics.median(spacing))) if spacing else 0)
    periodicity, period_ms = autocorr_peak(s[meas], int(round(frame_ms)),
                                            period_lo,
                                            int(cfg["autocorr_max_ms"])) if meas.sum() > 8 else (0.0, 0.0)

    gates = []
    if amax < float(cfg["min_amplitude_px"]):
        gates.append("low_amplitude")
    if fused["coverage"] < float(cfg["min_coverage"]):
        gates.append("low_coverage")
    if len(strong) < int(cfg["min_peaks"]):
        gates.append("no_periodicity")
    if upd < float(cfg["min_update_ratio"]):
        gates.append("weak_detections")
    if strong and len(strong) / max(len(meas_extrema), 1) < float(cfg["min_tick_support_ratio"]):
        gates.append("low_support")

    # основной трек фьюза = трек с максимальным вкладом амплитуды (для viewer и summary)
    dominant = max(live, key=lambda tr: (tr["coverage"] * tr["amplitude_px"],
                                              -cfg["priority"].index(tr["class"])
                                              if tr["class"] in cfg["priority"] else 99),
                   default=None)
    # span = измеренный сегмент (проекция разрывов в него не входит: merge выбирает
    # клип по измеренному движению, выданное колебание не должно расширять сегмент)
    if meas.any():
        idx = np.flatnonzero(meas)
        span = (float(times[idx[0]]), float(times[idx[-1]]))
    else:
        span = None

    fusion = {"clip": clip.name, "duration_ms": int(duration_ms),
              "grid_ms": int(cfg["grid_ms"]), "frame_ms": round(frame_ms, 3),
              "n_frames": n_frames, "times": times, "s": s, "amp": fused["amp"],
              "z_amp": z_amp, "support": support, "pos": pos, "projected": proj,
              "coverage": round(fused["coverage"], 3), "amplitude_px": round(amax, 1),
              "periodicity": round(periodicity, 3), "period_ms": round(period_ms, 1),
              "update_ratio": round(upd, 3), "extrema": len(extrema),
              "strong_extrema": len(strong), "projected_extrema": sum(1 for e in extrema
                                                                     if e["projected"]),
              "projected_ms": int(round(proj.sum() * frame_ms)),
              "extrema_list": extrema,
              "gates": gates, "ok": not gates,
              "dominant_track": dominant["track_id"] if dominant else None,
              "dominant_class": dominant["class"] if dominant else None,
              "segment": span, "score": round(amax * periodicity * fused["coverage"], 2),
              "tracks": [{k: v for k, v in tr.items() if k in
                          ("track_id", "class", "coverage", "amplitude_px", "periodicity",
                           "period_ms", "score", "update_ratio", "control_frames",
                           "update_frames", "extrema", "gates", "ok")}
                         for tr in per_track]}

    out_dir = clip_out_dir(clip, cfg)
    rows_out = []
    for i in range(n_frames):
        rows_out.append({
            "frame": i,
            "ms": int(round(times[i])) if np.isfinite(times[i]) else int(round(i * frame_ms)),
            "raw": round(float(s[i]), 2) if np.isfinite(s[i]) else "",
            "detrended": round(float(s[i]), 2) if np.isfinite(s[i]) else "",
            "pos": int(pos[i]) if np.isfinite(pos[i]) else "",
            "valid": 1 if np.isfinite(s[i]) and not proj[i] else 0,
            "support": int(support[i]),
            "amp": round(float(fused["amp"][i]), 1) if np.isfinite(fused["amp"][i]) else "",
            "projected": 1 if proj[i] else 0,
        })
    write_rows(out_dir / "signal.csv", SIGNAL_COLUMNS, rows_out)
    meta = {k: v for k, v in fusion.items()
            if k not in ("times", "s", "amp", "z_amp", "support", "pos", "projected")}
    meta["extrema"] = [{"ms": e["ms"], "kind": e["kind"], "support": e["support"],
                        "projected": bool(e["projected"]),
                        "prominence": round(float(e["prominence"]), 3)} for e in extrema]
    meta["axes"] = {f"{a}-{b}": axes for tr in per_track for (a, b), axes in tr["axes"].items()}
    (out_dir / "signal_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
    return fusion


def _group(rows: list[dict]) -> dict[int, list[dict]]:
    by: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by[int(r["track_id"])].append(r)
    return by


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--video", default=str(ROOT / "video_debug" / "debug.mp4"))
    p.add_argument("--cfg", default=None)
    a = p.parse_args()

    cfg = load_config(Path(a.cfg) if a.cfg else None)
    clip = Path(a.video)
    out_dir = clip_out_dir(clip, cfg)
    rows = read_rows(out_dir / "track.csv", TRACK_COLUMNS)
    if not rows:
        raise SystemExit(f"{out_dir / 'track.csv'} пуст")
    duration_ms = video_duration_ms(clip)
    frame_ms = frame_ms_of(rows)
    fusion = signal_artifacts(cfg, clip, rows, duration_ms, frame_ms)

    print(f"клип {clip.name}: {duration_ms} мс, кадр {frame_ms:.2f} мс, кадров {fusion['n_frames']}, "
          f"треков {len(fusion['tracks'])}")
    for tr in fusion["tracks"]:
        print(f"  track {tr['track_id']} {tr['class']}: coverage {tr['coverage']:.3f}, "
              f"A {tr['amplitude_px']:.1f} px, P {tr['periodicity']:.3f}, score {tr['score']:.2f}, "
              f"экстремумов {tr['extrema']}, контрольных {tr['control_frames']}, "
              f"update {tr['update_ratio']:.3f}" +
              ("" if tr["ok"] else f" -> {','.join(tr['gates'])}"))
    print(f"фьюз: coverage {fusion['coverage']:.3f}, A {fusion['amplitude_px']:.1f} px, "
          f"P {fusion['periodicity']:.3f}, period {fusion['period_ms']:.0f} мс, "
          f"update {fusion['update_ratio']:.3f}, экстремумов {fusion['extrema']} "
          f"(поддержка >= {cfg['min_tick_support']}: {fusion['strong_extrema']}), "
          f"основной track {fusion['dominant_track']} ({fusion['dominant_class']}), "
          f"span {fusion['segment']}" + ("" if fusion["ok"] else f" -> {','.join(fusion['gates'])}"))


if __name__ == "__main__":
    main()
