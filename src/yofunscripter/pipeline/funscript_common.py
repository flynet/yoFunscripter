"""Общие утилиты генерации .funscript.

Разделение по времени:
  - acquisition = natивные кадры видео (30 fps = 33.33 мс). Реальных кадров каждые 20 мс нет;
  - grid = сетка 20 мс, на которую интерполируются позиции треков. Она нужна только для
    равномерного сглаживания и поиска экстремумов; выходные тики идут по времени реальных
    экстремумов (субкадровая интерполяция), то есть natивно неравномерные.

Пороги читаются только из configs/funscript.yaml. Формулы (LK, PCA, де-тренд, prominence)
реализованы на numpy, без scipy: окружение проекта не тянет scipy, и формулы должны быть
читаемы, а не заимствованы из чужой библиотеки.

CSV-формат трек-файла (`track.csv`), по одной строке на трека на кадр:
    frame, ms, class, track_id, cx, cy, w, h, good, seeded, conf, state, det, reason
state: seed (посев по детекции), live (LK-шаг), update (детекция обновила бокс),
       coast (LK-шаг без IoU-совпадения на контрольном прогоне),
       resume (возобновление потерянного трека), lost (потеря).
Состояние пишется **по кадрам**: `update` стоит только на кадре детекции, где бокс
обновили, на следующих кадрах — `live`. Иначе `update_ratio` = доля кадров после первого
совпадения (замер sexy-s002: `'update'`-строк поровну по всем фазам `frame % detect_every`
— 589/587/584/576/568 — то есть состояние живёт на всех кадрах), и FP-гейт `min_update_ratio`
мерит не подтверждения детекции.
`det` = 1 на контрольном проге детекции, 0 между ними: `update_ratio` = доля
`update`-кадров от контрольных, а не от всех кадров.
`reason` — причина потери на строке `lost` (`good` / `drift` / `coast` / `offframe`):
без неё потери не объяснимы (замер sexy-s002: 14 потерь из 34 при good = 100, то есть
LK держал все точки, умерли не по good).
"""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import yaml

from .paths import classes_config, funscript_config, layout

# ROOT = writable app root (install dir); refreshed by paths.configure() at startup,
# so `ROOT / cfg["out_dir"]` keeps the yolo convention with absolute packaged paths.
ROOT = layout().root
FUNSCRIPT_CONFIG = funscript_config()


def load_classes(path: Path | None = None) -> list[str]:
    """Классы из configs/classes.yaml. Vendored: без Label Studio и ls_common.

    Тот же формат и те же проверки, что в yolo: порядок = индекс класса в YOLO txt,
    `nc` сверяется с `names`, имена уникальны.
    """
    path = path or classes_config()
    if not path.exists():
        raise SystemExit(f"{path} не найден")
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    names = [str(n) for n in cfg["names"]]
    nc = int(cfg.get("nc", len(names)))
    if nc != len(names):
        raise SystemExit(f"{path}: nc={nc} не совпадает с числом names ({len(names)})")
    if len(set(names)) != len(names):
        raise SystemExit(f"{path}: в names есть повторяющиеся имена: {names}")
    return names

TRACK_COLUMNS = ("frame", "ms", "class", "track_id", "cx", "cy", "w", "h",
                 "good", "seeded", "conf", "state", "det", "reason")
SIGNAL_COLUMNS = ("frame", "ms", "raw", "detrended", "pos", "valid", "support", "amp",
                  "projected")

STATE_SEED = "seed"
STATE_LIVE = "live"
STATE_UPDATE = "update"
STATE_COAST = "coast"
STATE_RESUME = "resume"
STATE_LOST = "lost"


def load_config(path: Path | None = None) -> dict:
    path = path or FUNSCRIPT_CONFIG
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in ("width", "weights", "imgsz", "conf", "detect_every", "iou_gate",
                "seed_points", "seed_margin", "lk_win", "lk_level", "lk_fb_tol_px",
                "adopt_gain", "resume_center_tol", "loss_good_ratio",
                "loss_drift", "coast_max_ms",
                "reseed_every_frames", "reseed_good_ratio", "reseed_min_points",
                "reseed_quality", "reseed_min_dist",
                "kalman_pos_gain", "kalman_vel_gain", "kalman_min_good",
                "grid_ms", "smooth_ms", "detrend_window_ms",
                "fusion_window_ms", "min_local_points", "tick_support_ms",
                "min_tick_support", "min_tick_support_ratio", "phase_fill",
                 "project", "project_min_ms", "project_win_ms",
                 "project_min_periodicity", "project_fit_tol",
                 "project_decay_per_s", "project_amp_floor",
                "min_amplitude_px", "min_coverage", "min_peaks", "prominence_ratio",
                "min_interval_ms", "autocorr_min_ms", "autocorr_max_ms", "priority",
                "out_dir", "range", "pos_binary", "min_waves", "max_waves", "source_dir",
                "result_dir", "result_name", "concat_dir", "target_width", "target_height",
                "target_fps", "x264_crf", "x264_preset", "x264_gop", "audio_bitrate",
                "audio_rate", "video_track_timescale", "ffmpeg_bin", "ffprobe_bin"):
        if key not in cfg:
            raise SystemExit(f"{path}: нет ключа {key}")
    idx = [int(i) for i in cfg["priority"]]
    classes = load_classes()
    bad = [i for i in idx if not 0 <= i < len(classes)]
    if bad:
        raise SystemExit(
            f"{path}: priority вне 0..{len(classes) - 1}: {bad}. Индексы разрешаются "
            "из configs/classes.yaml (локальный, не в git)"
        )
    cfg["priority"] = [classes[i] for i in idx]
    return cfg


def clip_out_dir(clip: Path, cfg: dict) -> Path:
    """Артефакты клипа: runs/funscript/<stem>/ (runs/ не в git)."""
    return ROOT / cfg["out_dir"] / clip.stem


def scaled_size(width: int, height: int, target_width: int) -> tuple[int, int]:
    """(w, h) -> (target_width, nh) с сохранением пропорций. Меньшие не увеличиваются."""
    if width <= target_width:
        return width, height
    return target_width, int(round(height * target_width / width))


def sha1_short(path: Path, n: int = 12) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:n]


def load_model(weights: Path, device: str | int | None = None):
    """YOLO с хоста. device None = GPU, если доступен (замер: RTX 4060, инференс 0.024 с)."""
    from ultralytics import YOLO

    import torch

    model = YOLO(str(weights))
    if device is None:
        device = 0 if torch.cuda.is_available() else "cpu"
    return model, device


@dataclass
class Detection:
    cls: str
    conf: float
    cx: float
    cy: float
    w: float
    h: float

    @property
    def box(self) -> tuple[float, float, float, float]:
        return (self.cx, self.cy, self.w, self.h)


def detect(model, frame, cfg: dict, device) -> list[Detection]:
    """Боксы одной картинки. xywh = центр + размеры, как в YOLO txt."""
    res = model.predict(frame, imgsz=cfg["imgsz"], conf=cfg["conf"],
                        device=device, verbose=False)[0]
    out: list[Detection] = []
    if len(res.boxes) == 0:
        return out
    names = res.names
    for box in res.boxes:
        cx, cy, w, h = (float(v) for v in box.xywh[0])
        out.append(Detection(cls=str(names[int(box.cls)]), conf=float(box.conf),
                             cx=cx, cy=cy, w=w, h=h))
    return out


def iou(a, b) -> float:
    """IoU двух боксов в форме (cx, cy, w, h)."""
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ax1, ay1 = ax0 - aw / 2, ay0 - ah / 2
    bx1, by1 = bx0 - bw / 2, by0 - bh / 2
    ax2, ay2 = ax0 + aw / 2, ay0 + ah / 2
    bx2, by2 = bx0 + bw / 2, by0 + bh / 2
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def seed_points(cx: float, cy: float, w: float, h: float, n: int, margin: float) -> np.ndarray:
    """Сетка n x n точек LK внутри бокса, с отступом margin от краёв (доля размера).

    Точки внутри тела, не на фоне: фон при переносе бокса утаскивает трек за собой.
    """
    xs = np.linspace(cx - w / 2 + w * margin, cx + w / 2 - w * margin, n)
    ys = np.linspace(cy - h / 2 + h * margin, cy + h / 2 - h * margin, n)
    grid = np.array([[x, y] for y in ys for x in xs], dtype=np.float32)
    return grid.reshape(-1, 1, 2)


def reseed_points(gray, cx: float, cy: float, w: float, h: float, cfg: dict) -> np.ndarray:
    """Свежие LK-точки внутри текущего бокса (по углу Shi-Tomasi), без детекции.

    Точками LK живут между YOLO-контролями: сетка `seed_points` на гладкой коже даёт
    слабые точки, LK их теряет, трек умирает и coverage проседает. Пересев по углам
    внутри текущего бокса держит визуальный трекер непрерывным: он сам выбирает точки,
    за которыми можно идти, а YOLO только коррегирует бокс (раз в `detect_every`).
    Если углов нет (гладкая статика), возвращаем сетку — LK по ней дрожит, и гейт
    `low_amplitude` режет такой сигнал.
    """
    th, tw = gray.shape[:2]
    margin = float(cfg["seed_margin"])
    x0 = int(max(0, np.ceil(cx - w / 2 + w * margin)))
    x1 = int(min(tw, np.floor(cx + w / 2 - w * margin)))
    y0 = int(max(0, np.ceil(cy - h / 2 + h * margin)))
    y1 = int(min(th, np.floor(cy + h / 2 - h * margin)))
    pts = None
    if x1 - x0 > 6 and y1 - y0 > 6:
        # OpenCV 5.0: `maxCorners` positional, keyword `maxCnt` не принимается
        pts = cv2.goodFeaturesToTrack(
            gray[y0:y1, x0:x1], int(cfg["seed_points"]),
            float(cfg["reseed_quality"]), float(cfg["reseed_min_dist"]),
            int(cfg["lk_win"]),
        )
    if pts is None or pts.shape[0] < int(cfg["reseed_min_points"]):
        return seed_points(cx, cy, w, h, int(cfg["seed_points"]), margin)
    pts = pts.astype(np.float32)
    pts[:, 0, 0] += x0
    pts[:, 0, 1] += y0
    return pts


def lk_step(prev_gray, next_gray, pts: np.ndarray, cfg: dict) -> tuple[np.ndarray, np.ndarray]:
    """Sparse Lucas-Kanade по всем точкам разом. Возвращает (новые точки, статус good=1).

    OpenCV 5.0: winSize обязателен кортежем (21, 21), одиночное число падает
    (`Can't parse 'winSize'`).

    Forward-backward (`lk_fb_tol_px` > 0): второй вызов LK идёт назад (next -> prev), и
    точка остаётся good, только если возврат попал в исходную позицию с ошибкой <= порога.
    Прямой LK принимает точку, перепрыгнувшую на соседний объект, и на гладкой коже
    точечный дрейф накапливается — FB-проверка снимает такие точки, а с ними и дрейф центра
    (центр трека = медиана good-смещений). Стоимость — два вызова LK на кадр
    (замер: 8.8 мс на 25 точек на вызов), поэтому порог выключаем на 0.
    """
    win = (cfg["lk_win"], cfg["lk_win"])
    level = cfg["lk_level"]
    new_pts, status, _err = cv2.calcOpticalFlowPyrLK(prev_gray, next_gray, pts, None, win, level)
    tol = float(cfg.get("lk_fb_tol_px", 0) or 0)
    if tol <= 0:
        return new_pts, status
    rev, rev_status, _ = cv2.calcOpticalFlowPyrLK(next_gray, prev_gray, new_pts, None, win, level)
    err = np.linalg.norm(rev.reshape(-1, 2) - pts.reshape(-1, 2), axis=1)
    keep = (status.reshape(-1) == 1) & (rev_status.reshape(-1) == 1) & (err <= tol)
    return new_pts, keep.astype(np.uint8).reshape(-1, 1)


def lk_update(live: list, prev_gray, gray, cfg: dict) -> None:
    """LK-шаг по точкам всех живых треков разом (один вызов на кадр).

    `live` — объекты с полями pts/cx/cy/good (Track из funscript_track.py и live-сессия
    test_video_ui.py используют одну логику). `prev_gray` = кадр прошлого шага: None на
    первом кадре (LK нечего сравнивать). LK работает с (N,1,2); смещения считаются на
    плоском (N,2), иначе disp[:,1] падает (axis 1 размера 1).

    LK двигает `raw_cx/raw_cy` — сырой центр визуального трекера, а не `cx`. `cx`
    Kalman-фильтр `center_step` (замер: YOLO-коррекция каждые 3 кадра = 120 мс давала
    ступеньку в центре и рвала coverage; теперь YOLO раз в секунду, LK непрерывен,
    фильтр сглаживает LK-джиттер). Если у объекта нет raw-полей (старый вызов вне
    funscript-трека), raw заводится от cx, и шаг идёт по-старому.
    """
    if prev_gray is None or not live:
        return
    allpts = np.vstack([t.pts for t in live])
    new_pts, status = lk_step(prev_gray, gray, allpts, cfg)
    status = status.reshape(-1)
    offset = 0
    for t in live:
        n = t.pts.shape[0]
        sl = slice(offset, offset + n)
        old = allpts[sl].reshape(-1, 2)
        newp = new_pts[sl].reshape(-1, 2)
        good_mask = status[sl] == 1
        t.good = int(good_mask.sum())
        if not hasattr(t, "raw_cx"):
            t.raw_cx = t.cx
            t.raw_cy = t.cy
        if t.good >= 2:
            disp = newp[good_mask] - old[good_mask]
            t.raw_cx += float(np.median(disp[:, 0]))
            t.raw_cy += float(np.median(disp[:, 1]))
        t.pts = new_pts[sl]
        offset += n


def center_step(t, cfg: dict, dt: float) -> None:
    """Kalman-шаг центра: предсказание по скорости + LK-измерение.

    Визуальный трекер (LK) даёт измерение сырым центром, YOLO — коррекцию (`adopt`).
    Сглаживание по фильтру, а не по медианному фильтру сигнала: LK-джиттер на 1 px
    превращается локальной нормировкой амплитуды в волну (замер sexy-s020 — статичный
    клип, амплитуда консенсуса 1.7 px), а при потере точек `cx` едет по скорости
    (`coast`), то есть темп через пропажу не обрывается. `kalman_pos_gain` = доля,
    которой `cx` тянется к raw LK; `kalman_vel_gain` = доля сырой LK-скорости в
    оценке скорости. `kalman_min_good` = минимум good-точек, чтобы измерение принималось.
    """
    if dt <= 0:
        return
    t.cx += t.vx * dt
    t.cy += t.vy * dt
    if t.good >= int(cfg["kalman_min_good"]):
        raw_vx = (t.raw_cx - t.last_raw_cx) / dt
        raw_vy = (t.raw_cy - t.last_raw_cy) / dt
        t.vx += float(cfg["kalman_vel_gain"]) * (raw_vx - t.vx)
        t.vy += float(cfg["kalman_vel_gain"]) * (raw_vy - t.vy)
        t.cx += float(cfg["kalman_pos_gain"]) * (t.raw_cx - t.cx)
        t.cy += float(cfg["kalman_pos_gain"]) * (t.raw_cy - t.cy)
        t.last_raw_cx, t.last_raw_cy = t.raw_cx, t.raw_cy


def loss_reason(t, frame: int, cfg: dict, detect_every: int, size: tuple[int, int],
                ms: float) -> str | None:
    """Причина потери трека на кадре `frame`, None = трек жив.

    good-точек меньше доли от засеванных; дрейф центра от эталонного бокса (доля размера
    `loss_drift` и абсолютный порог `loss_drift_px`, 0 = выключен); бокс за кадром;
    `coast_max_ms` без подтверждения детекцией.

    `coast_max_ms` заменяет `loss_misses` контрольных прогонов без IoU: трек живёт по LK,
    а детекция его просто не видела несколько прогонов, и умирает он по времени без
    подтверждения, а не по счёту пропусков. Замер sexy-s002: у 34 потерь good =
    100,99,95,92,98,83,94,43,96,62 — LK держал точки, умерли не по good; при 25 fps
    три пропуска = 600 мс, а медианный полупериод движения 160 мс — живые по качеству
    треки обрезались по таймеру, и coverage каждого куска мерялась по всему клипу (0.364,
    0.457 при `min_coverage` 0.50).
    """
    tw, th = size
    drift_px = float(cfg.get("loss_drift_px", 0) or 0)
    if t.good / max(t.seeded, 1) < float(cfg["loss_good_ratio"]):
        return "good"
    if t.drift() > float(cfg["loss_drift"]):
        return "drift"
    if drift_px > 0 and t.drift_px() > drift_px:
        return "drift_px"
    if t.cx - t.w / 2 < 0 or t.cx + t.w / 2 > tw or t.cy - t.h / 2 < 0 or t.cy + t.h / 2 > th:
        return "offframe"
    if ms - t.last_confirm_ms > float(cfg["coast_max_ms"]):
        return "coast"
    return None


def grid_times(duration_ms: float, grid_ms: int) -> np.ndarray:
    return np.arange(0.0, duration_ms + grid_ms / 2, grid_ms, dtype=float)


def interp_to_grid(ms: np.ndarray, values: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Линейная интерполяция на сетку. Границы диапазона трека = NaN.

    `ms` монотонен (строки трека пишутся по кадрам), поэтому np.interp годится;
    за пределами первого/последнего кадра трека значения не экстраполируются.
    """
    out = np.full(grid.shape, np.nan)
    lo, hi = ms[0], ms[-1]
    inside = (grid >= lo) & (grid <= hi)
    out[inside] = np.interp(grid[inside], ms, values)
    return out


def median_filter(values: np.ndarray, k: int) -> np.ndarray:
    """Медианный фильтр по скользящему окну k (нечетное). Границы — сокращённое окно."""
    values = np.asarray(values, dtype=float)
    n = values.size
    if n == 0:
        return values
    half = k // 2
    out = np.empty(n, dtype=float)
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        out[i] = np.median(values[lo:hi])
    return out


def finite_runs(values: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) непрерывных конечных участков массива (NaN = разрыв)."""
    values = np.asarray(values, dtype=float)
    out: list[tuple[int, int]] = []
    start = None
    for i, v in enumerate(list(values) + [np.nan]):
        if np.isfinite(v):
            if start is None:
                start = i
        elif start is not None:
            out.append((start, i))
            start = None
    return out


def median_filter_runs(values: np.ndarray, k: int) -> np.ndarray:
    """Медианный фильтр по каждому конечному участку отдельно.

    `median_filter` на окнах с NaN возвращает NaN, и NaN распространяется по всему
    окну: фильтровать ряд с разрывами напрямую нельзя, участок за разрывом становится
    NaN целиком.
    """
    values = np.asarray(values, dtype=float)
    out = np.full(values.size, np.nan)
    for lo, hi in finite_runs(values):
        out[lo:hi] = median_filter(values[lo:hi], k)
    return out


def local_amplitude(values: np.ndarray, window: int, min_points: int) -> np.ndarray:
    """p95-p5 по скользящему окну `window` (центр на каждой точке), NaN где конечных
    значений меньше `min_points`.

    Локальная амплитуда = вес трекера в фьюзе и порог prominence экстремума: амплитуда
    движения в sexy-s002 меняется по клипу (cls1 61 px в 0-13 с, 38 px в 17-48 с, cls0
    25 px), один глобальный порог (`prominence_ratio * амплитуды всего сегмента`) режет
    слабые места и пропускает шум в сильных.

    `min_points` ограничивается окном: на краях run'а окно сокращается, и требование
    `min_points` 6 при адаптивном окне 7 кадров (два полупериода) даёт NaN на краях —
    покрытие фьюза sexy-s002 упало с 0.994 до 0.499, и консенсус исчез в разрывах.
    """
    values = np.asarray(values, dtype=float)
    n = values.size
    out = np.full(n, np.nan)
    half = window // 2
    pts = max(3, min(int(min_points), half + 1))
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        w = values[lo:hi]
        w = w[np.isfinite(w)]
        if w.size < pts:
            continue
        out[i] = float(np.percentile(w, 95) - np.percentile(w, 5))
    return out


def moving_median(values: np.ndarray, window: int) -> np.ndarray:
    """Скользящая медиана окна window точек. Де-тренд = values - moving_median(values)."""
    values = np.asarray(values, dtype=float)
    n = values.size
    if n == 0:
        return values
    half = window // 2
    out = np.empty(n, dtype=float)
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        out[i] = np.median(values[lo:hi])
    return out


def pca_axis(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Доминирующая ось траектории. points = (N, 2) де-трененных центров.

    Возвращает (axis, center). Ось нормирована. На прямой траектории (N < 2) — вертикаль.

    Знак канонический по **доминантной** компоненте (вертикальное движение: положительная
    проекция = вниз, y растёт): `axis[0] > 0` для вертикальной оси = знак по шуму x, и run'ы
    одного трека получают проекции в противофазе. Замер sexy-s002: cls0 x cls1 по 813 точкам
    корреляция −0.379 (сумма в фьюзе гасит движение, консенсус 0.0 при амплитуде треков
    160 px), после канонизации +0.824.
    """
    points = np.asarray(points, dtype=float)
    if points.shape[0] < 2:
        return np.array([0.0, 1.0]), np.zeros(2)
    center = points.mean(axis=0)
    centered = points - center
    cov = centered.T @ centered
    eigvals, eigvecs = np.linalg.eigh(cov)
    axis = eigvecs[:, -1]  # собственный вектор максимального разброса
    if abs(axis[1]) > abs(axis[0]):
        if axis[1] < 0:
            axis = -axis
    elif axis[0] < 0:
        axis = -axis
    return axis / np.linalg.norm(axis), center


def autocorr_peak(values: np.ndarray, grid_ms: int, lo_ms: int, hi_ms: int) -> tuple[float, float]:
    """(максимум нормированной автокорреляции, лаг этого максимума в мс) по лагам [lo_ms, hi_ms].
    Лаг = период сигнала (цикл), не нормированная величина.

    Нормировка по нулевому лагу (автоковариация), де-трененный сигнал, лаги целыми шагами сетки.
    """
    v = np.asarray(values, dtype=float)
    v = v - v.mean()
    n = v.size
    if n < 4:
        return 0.0, 0.0
    lo = max(1, int(round(lo_ms / grid_ms)))
    hi = min(n - 1, int(round(hi_ms / grid_ms)))
    zero = float(np.dot(v, v))
    if zero <= 0:
        return 0.0, 0.0
    best, best_lag = 0.0, 0
    for lag in range(lo, hi + 1):
        c = float(np.dot(v[: n - lag], v[lag:])) / zero
        if c > best:
            best, best_lag = c, lag
    return best, best_lag * grid_ms


def _prominences(values: np.ndarray, peaks: list[int]) -> list[float]:
    """Prominence локальных максимумов: наибольшая из двух «сторон» экстремума.

    Для пика i: слева идём до первого значения > values[i], берём минимум на этом пути
    (если выше значения слева нет — минимум всей левой части); аналогично справа.
    Условие пути `<=`, а не `<`: медианный фильтр даёт плато, и при `<` путь обрывается
    на равном соседнем значении, седловина = высота пика, prominence = 0 (измерено на
    debug.mp4: все 18 пиков имели prominence 0).

    Берётся max обеих сторон, а не классический min (седловина): run'ы коротких треков
    обрываются на границе tracking'а, и путь до края run'а не седловина, а реальная
    амплитуда хода (замер sexy-s005 run 3..20: peak 0.42, правый путь до края run'а
    даёт -0.58, drop 1.0 при локальной амплитуде 1.0, и min-седловина (0.37)
    отрезала пик с prominence 0.05 — тик полного хода пропал). Шумной wobble мал
    с обеих сторон, и max обеих сторон его тоже режет.
    """
    values = np.asarray(values, dtype=float)
    n = values.size
    out = []
    for i in peaks:
        best = 0.0
        for step in (-1, 1):
            lo = values[i]
            j = i + step
            while 0 <= j < n and values[j] <= values[i]:
                lo = min(lo, values[j])
                j += step
            best = max(best, float(values[i] - lo))
        out.append(best)
    return out


def local_maxima(values: np.ndarray) -> list[int]:
    """Индексы локальных максимумов (плато берётся по первому индексу)."""
    v = np.asarray(values, dtype=float)
    n = v.size
    out = []
    for i in range(1, n - 1):
        if v[i] > v[i - 1] and v[i] >= v[i + 1]:
            out.append(i)
    return out


def subframe_time(values: np.ndarray, times: np.ndarray, i: int) -> float:
    """Время экстремума с субкадровой интерполяцией параболой по 3 точкам сетки.

    Квант сетки (20 мс) и квант кадра (33.33 мс) оба крупнее точности тика: парабола
    даёт ±10 мс, и тик не кратен ни той, ни другой сетке.
    """
    if i <= 0 or i >= values.size - 1:
        return float(times[i])
    a, b, c = values[i - 1], values[i], values[i + 1]
    denom = a - 2 * b + c
    if denom == 0:
        return float(times[i])
    offset = 0.5 * (a - c) / denom
    offset = max(-1.0, min(1.0, offset))
    step = float(times[i] - times[i - 1])
    return float(times[i]) + offset * step


def _edge_prominences(values: np.ndarray) -> list[tuple[int, float, str]]:
    """Prominence краёв run'а: экстремум на границе живого segment'а.

    `local_maxima` смотрит только i в 1..n-2, и вершина хода на краю run'а не находится:
    замер sexy-s002 — peak 14280 (z 1.1, run 14240..14280, дальше LK теряет объект)
    исчезал, и разрыв 1020 мс закрывался slope-тиками вместо измеренного пика. Край
    сравнивается с соседним внутрь run'а значением, prominence меряется по одному пути.
    """
    v = np.asarray(values, dtype=float)
    n = v.size
    out: list[tuple[int, float, str]] = []
    if n < 3:
        return out
    for i, step in ((0, 1), (n - 1, -1)):
        j = i + step
        if v[i] > v[j]:
            path = v[i]
            k = j
            while 0 <= k < n and v[k] <= v[i]:
                path = min(path, v[k])
                k += step
            out.append((i, float(v[i] - path), "peak"))
        elif v[i] < v[j]:
            path = v[i]
            k = j
            while 0 <= k < n and v[k] >= v[i]:
                path = max(path, v[k])
                k += step
            out.append((i, float(path - v[i]), "trough"))
    return out


def find_extrema(values: np.ndarray, times: np.ndarray, prominence_min, min_interval_ms: int,
                 ) -> list[dict]:
    """Экстремуму сигнала: пики (max) и впадины (min), prominence-порог, min интервал.

    `prominence_min` — число (порог по всему сигналу) или массив по точкам `values`
    (локальный порог: `prominence_ratio * локальной амплитуды`). Один глобальный порог
    режет слабые места сигнала и пропускает шум в сильных: амплитуда в sexy-s002 меняется
    с 61 px до 25 px по клипу.

    Жадно по убыванию prominence: принимается экстремум, отстоящий от всех принятых
    не ближе min_interval_ms. Так порог «25% амплитуды» и 100 мс работают вместе:
    мелкое дрожание срезается prominence, частые тики — интервалом.
    """
    v = np.asarray(values, dtype=float)
    n = v.size
    if n < 3:
        return []
    thr = np.asarray(prominence_min, dtype=float)
    scalar = thr.ndim == 0
    peaks = local_maxima(v)
    peak_prom = _prominences(v, peaks)
    troughs = local_maxima(-v)
    trough_prom = _prominences(-v, troughs)
    cand = []
    for i, p in zip(peaks, peak_prom):
        if p >= (thr if scalar else thr[i]):
            cand.append({"ms": subframe_time(v, times, i), "prominence": p, "kind": "peak"})
    for i, p in zip(troughs, trough_prom):
        if p >= (thr if scalar else thr[i]):
            cand.append({"ms": subframe_time(v, times, i), "prominence": p, "kind": "trough"})
    for i, p, kind in _edge_prominences(v):
        if p >= (thr if scalar else thr[i]):
            cand.append({"ms": subframe_time(v, times, i), "prominence": p, "kind": kind})
    cand.sort(key=lambda e: -e["prominence"])
    accepted: list[dict] = []
    for e in cand:
        if all(abs(e["ms"] - a["ms"]) >= min_interval_ms for a in accepted):
            accepted.append(e)
    accepted.sort(key=lambda e: e["ms"])
    return accepted


def find_extrema_runs(values: np.ndarray, times: np.ndarray, prominence_min,
                      min_interval_ms: int) -> list[dict]:
    """Экстремумы по каждому живому run'у ряда с разрывами, затем интервал по клипу.

    `find_extrema` на ряду с NaN края run'а не видит: `local_maxima` сравнивает
    значение с обоих соседей, NaN-сосед (пустой кадр) даёт False, а `_edge_prominences`
    смотрит только края всего массива (замер sexy-s005: run 21..28 z -0.16..0.78,
    prominence края 0.94 против порога 0.29 — экстремум не найден, первые 4 run'а
    фьюза остались без тиков). Каждый run режется порогом своего участка, и все
    кандидаты принимаются жадно по prominence с `min_interval_ms` по всему клипу.
    """
    thr = np.asarray(prominence_min, dtype=float)
    cand = []
    for lo, hi in finite_runs(values):
        cand.extend(find_extrema(values[lo:hi], times[lo:hi],
                                 thr if thr.ndim == 0 else thr[lo:hi], min_interval_ms))
    cand.sort(key=lambda e: -e["prominence"])
    accepted: list[dict] = []
    for e in cand:
        if all(abs(e["ms"] - a["ms"]) >= min_interval_ms for a in accepted):
            accepted.append(e)
    accepted.sort(key=lambda e: e["ms"])
    return accepted


def read_rows(path: Path, columns: tuple[str, ...]) -> list[dict]:
    """CSV -> список dict по фиксированным колонкам. Файл пишется этим же модулем."""
    if not path.is_file():
        raise SystemExit(f"{path} не найден")
    rows = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header = tuple(reader.fieldnames or ())
        if header != columns:
            raise SystemExit(f"{path}: заголовки {header} не совпадают с {columns}")
        for row in reader:
            rows.append(row)
    return rows


def write_rows(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # mode="w": Path.open() по умолчанию чтение, и без него запись падает FileNotFoundError
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row[c] for c in columns})


def track_rows(clip: Path, cfg: dict) -> list[dict]:
    return read_rows(clip_out_dir(clip, cfg) / "track.csv", TRACK_COLUMNS)


def video_fps_frames(clip: Path) -> tuple[float, int]:
    """(fps, число кадров) по контейнеру — те же числа, что видит плеер."""
    cap = cv2.VideoCapture(str(clip))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    if fps <= 0 or frames <= 0:
        raise SystemExit(f"{clip}: fps={fps}, frames={frames} — клип не читается")
    return fps, frames


def video_duration_ms(clip: Path) -> int:
    fps, frames = video_fps_frames(clip)
    return int(round(frames * 1000 / fps))


def frame_ms_of(rows: list[dict]) -> float:
    """Средний кадр по строкам track.csv (мс/кадр)."""
    if len(rows) < 2:
        return 1000.0 / 30          # клип без детекций: строк трека нет
    frames = int(rows[-1]["frame"]) - int(rows[0]["frame"])
    if frames <= 0:
        return 1000.0 / 30
    return (int(rows[-1]["ms"]) - int(rows[0]["ms"])) / frames
