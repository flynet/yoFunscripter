"""Один клип -> `track.csv`: детекция + LK-трекинг.

    python scripts/funscript_track.py                       # video_debug/debug.mp4
    python scripts/funscript_track.py --video "video/2 (1)/part_22_20.mp4"
    python scripts/funscript_track.py --points             # для viewer: точки LK в points.csv
    python scripts/funscript_track.py --verbose            # печать детекций по кадрам

`track_clip()` импортирует batch-прогон (funscript_run.py), который держит модель
загруженной один раз для всех клипов.

Логика (решения зафиксированы):
  - кадр уменьшен до ширины configs/funscript.yaml:width (высота по пропорциям);
  - детекция @conf каждый `detect_every`-й кадр (120 мс при 25 fps, `detect_every 3`);
  - каждый кадр — sparse LK по точкам, засеванным внутри бокса; центр трека = медиана
    смещений good-точек, бокс двигается как жёсткий (translation-only);
  - forward-backward LK (`lk_fb_tol_px`): второй вызов идёт назад (next -> prev), точка
    good только при возврате в исходную позицию с ошибкой <= порога;
  - детекция с IoU >= iou_gate к боксу трека того же класса -> бокс обновляется,
    центр двигается к детекции плавно (`adopt_gain`), точки пересевятся;
  - потеря: good-точек < loss_good_ratio, дрейф центра от эталонного бокса > loss_drift
    (в долях размера), бокс за кадром, `coast_max_ms` без подтверждения детекцией
    (коастинг: трек едет по LK, детекция его не видела);
  - возобновление: детекция того же класса с центром ближе `resume_center_tol` долей
    размера к эталонному боксу потерянного трека -> тот же track_id; иначе новый track_id;
  - состояние пишется **по кадрам** (`update` только на кадре детекции), колонки `det`
    (контрольный прогон) и `reason` (причина на строке `lost`).

Замер на RTX 4060: LK 8.8 мс/кадр на 25 точек (5 объектов ~25 мс), детекция 41.1 мс/кадр
(декод + resize + инференс, каждый 5-й кадр). CSRT отклонён: 35.5 мс на объект на шаг.

Центр и бокс — всё в системе уменьшенного кадра (ширина 1000).
"""
from __future__ import annotations

import argparse
import sys
from .paths import model_path
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .funscript_common import (
    ROOT, STATE_COAST, STATE_LOST, STATE_LIVE, STATE_RESUME, STATE_SEED, STATE_UPDATE,
    TRACK_COLUMNS, center_step, clip_out_dir, detect, iou, lk_update, load_config,
    load_model, loss_reason, reseed_points, scaled_size, seed_points,
    video_duration_ms, write_rows,
)

PROGRESS_EVERY = 30


@dataclass
class Track:
    id: int
    cls: str
    cx: float
    cy: float
    w: float
    h: float
    # эталонный бокс = последний детекционный; дрейф меряется от него
    ref_cx: float
    ref_cy: float
    ref_w: float
    ref_h: float
    pts: np.ndarray
    seeded: int
    conf: float
    state: str
    good: int
    misses: int
    frames: int = 0
    good_sum: int = 0
    # кадр (мс) последнего подтверждения детекцией: коастинг = ms - last_confirm_ms
    last_confirm_ms: float = 0.0
    coast_ms: float = 0.0
    control_frames: int = 0   # контрольных прогонов, пережитых треком
    # сырой центр LK (raw) и скорость Kalman-центра: LK двигает raw, cx = raw,
    # сглаженный фильтром (см. center_step), pts живут по raw
    raw_cx: float = 0.0
    raw_cy: float = 0.0
    last_raw_cx: float = 0.0
    last_raw_cy: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    events: list = field(default_factory=list)

    @property
    def box(self) -> tuple[float, float, float, float]:
        return (self.cx, self.cy, self.w, self.h)

    def drift(self) -> float:
        """Дрейф центра от эталонного бокса, в долях его размера (по худшей оси)."""
        return max(abs(self.cx - self.ref_cx) / self.ref_w, abs(self.cy - self.ref_cy) / self.ref_h)

    def drift_px(self) -> float:
        """Дрейф центра от эталонного бокса в пикселях (по худшей оси).

        Доля размера (`loss_drift` 0.40) на малом боксе мягче: при боксе 60 px это 24 px
        дрейфа, при боксе 200 px — 80 px. Абсолютный порог (`loss_drift_px`) одинаков для
        всех боксов и отсекает дрейф на малоамплитудных клипах, где доля не срабатывает.
        """
        return max(abs(self.cx - self.ref_cx), abs(self.cy - self.ref_cy))


def row_of(t: Track, frame: int, ms: int, det: int, state: str, reason: str) -> dict:
    return {"frame": frame, "ms": ms, "class": t.cls, "track_id": t.id,
            "cx": round(t.cx, 1), "cy": round(t.cy, 1), "w": round(t.w, 1), "h": round(t.h, 1),
            "good": t.good, "seeded": t.seeded, "conf": round(t.conf, 3),
            "state": state, "det": det, "reason": reason}


def adopt(t: Track, d, cfg: dict, ms: float) -> None:
    """Бокс трека = бокс детекции, центр двигается плавно, точки пересевятся.

    YOLO — контрол раз в `detect_every` (секунда), а не каждые 120 мс: визуальный
    трекер (LK) сам ведёт точки между контролями. Центр тянется к детекции долей
    `adopt_gain`, а не телепортируется: разница LK-центра и детекции (до `loss_drift`
    долей размера, при боксе 200 px — до 80 px) — это ступенька в ряду позиций. Медианный
    фильтр её размазывает, а парабола экстремума получает время ступеньки, а не движения;
    чем чаще контроль, тем больше ступенек (замер A/B `detect_every 3`: экстремумов на
    seg-0248 стало 8 -> 4). Эталонный бокс = детекция целиком, так что `loss_drift`
    меряется к свежему подтверждению.
    """
    gain = float(cfg["adopt_gain"])
    t.cx += gain * (d.cx - t.cx)
    t.cy += gain * (d.cy - t.cy)
    t.w, t.h = d.w, d.h
    t.ref_cx, t.ref_cy, t.ref_w, t.ref_h = d.cx, d.cy, d.w, d.h
    t.raw_cx, t.raw_cy = d.cx, d.cy
    t.last_raw_cx, t.last_raw_cy = d.cx, d.cy
    t.pts = seed_points(t.raw_cx, t.raw_cy, t.w, t.h,
                        int(cfg["seed_points"]), float(cfg["seed_margin"]))
    t.seeded = t.pts.shape[0]
    t.good = t.seeded
    t.conf = d.conf
    t.misses = 0
    t.last_confirm_ms = ms


def new_track(d, frame: int, next_id: int, cfg: dict, ms: float) -> Track:
    pts = seed_points(d.cx, d.cy, d.w, d.h, int(cfg["seed_points"]), float(cfg["seed_margin"]))
    return Track(id=next_id, cls=d.cls, cx=d.cx, cy=d.cy, w=d.w, h=d.h,
                 ref_cx=d.cx, ref_cy=d.cy, ref_w=d.w, ref_h=d.h,
                 pts=pts, seeded=pts.shape[0], conf=d.conf, state=STATE_SEED,
                 good=pts.shape[0], misses=0, frames=frame + 1, last_confirm_ms=ms,
                 raw_cx=d.cx, raw_cy=d.cy, last_raw_cx=d.cx, last_raw_cy=d.cy)


def resume_distance(t: Track, d) -> float:
    """Расстояние центра детекции к эталонному боксу потерянного трека, в долях его размера
    (по худшей оси)."""
    return max(abs(d.cx - t.ref_cx) / t.ref_w, abs(d.cy - t.ref_cy) / t.ref_h)


def match_tracks(tracks: list[Track], detections: list, cfg: dict, frame: int,
                ms: float) -> tuple[set[int], set[int]]:
    """Greedy-сопоставление живых треков с детекциями по IoU (пары по убыванию IoU,
    непересекающиеся), и возобновление потерянных треков по расстоянию центра.
    Возвращает индексы использованных треков и использованных детекций;
    несопоставленные детекции caller превращает в новые треки."""
    gate = float(cfg["iou_gate"])
    pairs = []
    for ti, t in enumerate(tracks):
        if t.state == STATE_LOST:
            continue
        for di, d in enumerate(detections):
            if d.cls != t.cls:
                continue
            v = iou(t.box, d.box)
            if v >= gate:
                pairs.append((v, ti, di))
    pairs.sort(key=lambda x: -x[0])
    used_tracks: set[int] = set()
    used_dets: set[int] = set()
    for v, ti, di in pairs:
        if ti in used_tracks or di in used_dets:
            continue
        used_tracks.add(ti)
        used_dets.add(di)
        t = tracks[ti]
        adopt(t, detections[di], cfg, ms)
        t.state = STATE_UPDATE

    # возобновление потерянных треков по расстоянию центра (`resume_center_tol`), а не по
    # IoU к эталону: IoU падает из-за дрейфа масштаба бокса, а объект тот же. Замер
    # sexy-s002: цепочка cls1 рвалась 2 -> 6 -> 3 -> 7 -> 2, coverage каждого куска
    # мерялась по всему клипу (0.364, 0.457 при min_coverage 0.50), union живых треков = 0.99
    for di, d in enumerate(detections):
        if di in used_dets:
            continue
        best = None
        for t in tracks:
            if t.state != STATE_LOST or t.cls != d.cls:
                continue
            v = resume_distance(t, d)
            if v <= float(cfg["resume_center_tol"]) and (best is None or v < best[0]):
                best = (v, t)
        if best:
            t = best[1]
            adopt(t, d, cfg, ms)
            t.state = STATE_RESUME
            t.frames = frame + 1
            t.events.append(f"resume dist={best[0]:.2f}")
            used_dets.add(di)
    return used_tracks, used_dets


def track_clip(clip: Path, cfg: dict, model, device, want_points: bool = False,
              verbose: bool = False, quiet: bool = False,
               on_frame: "callable | None" = None) -> dict:
    """Прогон одного клипа: детекция + трекинг -> строки track.csv (и points.csv)."""
    detect_every = int(cfg["detect_every"])
    duration_ms = video_duration_ms(clip)
    cap = cv2.VideoCapture(str(clip))
    fps = cap.get(cv2.CAP_PROP_FPS)
    w0 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    h0 = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    tw, th = scaled_size(w0, h0, int(cfg["width"]))
    tracks: list[Track] = []
    rows: list[dict] = []
    point_rows: list[dict] = []
    next_id = 1
    prev_gray = None
    frame = 0
    detections_total = 0
    t0 = time.time()

    while True:
        ok, img = cap.read()
        if not ok:
            break
        if (img.shape[1], img.shape[0]) != (tw, th):
            img = cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        ms = int(round(frame * 1000 / fps))

        # 1. LK по точкам всех живых треков разом (один вызов на кадр), Kalman-шаг
        # центра, и пересев точек внутри текущего бокса, когда LK их теряет. Визуальный
        # трекер первичен: YOLO-коррекция раз в `detect_every`, а точки LK живут и
        # обновляются каждый кадр (замер sexy-s005: YOLO-коррекция каждые 120 мс, coverage
        # 0.438 и провалы; LK-пересев держит трек между контролями)
        live = [t for t in tracks if t.state != STATE_LOST]
        dt = 1000.0 / fps
        lk_update(live, prev_gray, gray, cfg)
        prev_gray = gray
        reseed_every = int(cfg["reseed_every_frames"])
        for t in live:
            t.frames += 1  # трек жив на этом кадре (frame+1 == число обработанных кадров)
            center_step(t, cfg, dt)
            good_floor = max(int(cfg["reseed_min_points"]),
                             int(round(t.seeded * float(cfg["reseed_good_ratio"]))))
            if reseed_every > 0 and frame % reseed_every == 0 and t.good < good_floor:
                # пересев по текущему Kalman-центру: при пропаже точек тред идёт по
                # скорости, и новые LK-точки нужно засевать там, где бокс (cx), а не там,
                # где точки умерли (raw)
                t.pts = reseed_points(gray, t.cx, t.cy, t.w, t.h, cfg)
                t.raw_cx, t.raw_cy = t.cx, t.cy
                t.last_raw_cx, t.last_raw_cy = t.cx, t.cy
                t.seeded = t.pts.shape[0]
                t.good = t.seeded

        # 2. контрольная детекция
        det = 1 if frame % detect_every == 0 else 0
        detections = []
        if det:
            detections = detect(model, img, cfg, device)
            detections_total += len(detections)
            if verbose:
                print(f"frame {frame:3d} ms {ms:5d}: " +
                      (", ".join(f"{d.cls} {d.conf:.2f} ({d.cx:.0f},{d.cy:.0f} {d.w:.0f}x{d.h:.0f})"
                                 for d in detections) if detections else "нет боксов"))

        if frame == 0:
            for d in detections:
                tracks.append(new_track(d, frame, next_id, cfg, ms))
                next_id += 1
        elif detections:
            used_tracks, used_dets = match_tracks(tracks, detections, cfg, frame, ms)
            for di, d in enumerate(detections):
                if di not in used_dets:
                    tracks.append(new_track(d, frame, next_id, cfg, ms))
                    next_id += 1
            # живые треки без IoU-совпадения: коастинг (счётчик для событий, смерть по времени)
            for ti, t in enumerate(tracks):
                if ti not in used_tracks and t.state not in (STATE_LOST, STATE_SEED):
                    t.misses += 1
        if det:
            for t in tracks:
                if t.state != STATE_LOST:
                    t.control_frames += 1

        # 3. критерии потери, затем одна строка на каждый живой трек за кадр.
        # состояние = по кадрам: событие (seed/resume/update) пишется только на своём кадре,
        # контрольный прогон без подтверждения = coast, остальные кадры = live.
        for t in tracks:
            if t.state == STATE_LOST:
                continue
            reason = loss_reason(t, frame, cfg, detect_every, (tw, th), ms)
            if reason:
                t.state = STATE_LOST
                t.events.append(f"lost@{frame} {reason} coast={t.coast_ms:.0f}")
                rows.append(row_of(t, frame, ms, det, STATE_LOST, reason))
                continue
            state_out = t.state
            if t.state in (STATE_SEED, STATE_RESUME, STATE_UPDATE):
                t.state = STATE_LIVE  # событие живёт один кадр, иначе update_ratio завышен
            elif det:
                state_out = STATE_COAST
            t.good_sum += t.good
            t.coast_ms = ms - t.last_confirm_ms
            rows.append(row_of(t, frame, ms, det, state_out, ""))

        if want_points:
            for t in tracks:
                if t.state == STATE_LOST:
                    continue
                for k, (x, y) in enumerate(t.pts.reshape(-1, 2)):
                    point_rows.append({"frame": frame, "ms": ms, "track_id": t.id,
                                       "x": round(float(x), 1), "y": round(float(y), 1),
                                       "good": 1 if k < t.good else 0})

        frame += 1
        if on_frame is not None and frame % PROGRESS_EVERY == 0:
            on_frame(frame, total_frames)
        if frame % PROGRESS_EVERY == 0 and not quiet:
            d = time.time() - t0
            print(f"{frame} кадров, детекций {detections_total}, живых треков "
                  f"{sum(1 for t in tracks if t.state != STATE_LOST)}, {d / frame * 1000:.1f} мс/кадр",
                  flush=True)

    cap.release()
    if on_frame is not None:
        on_frame(frame, total_frames)
    rows.sort(key=lambda r: (int(r["frame"]), int(r["track_id"])))
    if want_points:
        point_rows.sort(key=lambda r: (int(r["frame"]), int(r["track_id"])))
    return {"clip": clip, "duration_ms": duration_ms, "fps": fps, "size": (w0, h0),
            "scaled": (tw, th), "rows": rows, "point_rows": point_rows,
            "tracks": tracks, "frames": frame, "detections": detections_total,
            "elapsed": time.time() - t0}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--video", default=str(ROOT / "video_debug" / "debug.mp4"))
    p.add_argument("--cfg", default=None)
    p.add_argument("--weights", default=None, help="перекрыть configs/funscript.yaml:weights")
    p.add_argument("--device", default=None, help="gpu = 0, cpu = хост; по умолчанию GPU, если есть")
    p.add_argument("--points", action="store_true", help="писать points.csv (для viewer)")
    p.add_argument("--verbose", action="store_true", help="печать детекции по кадрам")
    a = p.parse_args()

    cfg = load_config(Path(a.cfg) if a.cfg else None)
    weights = Path(a.weights) if a.weights else model_path(cfg)
    if not weights.is_file():
        raise SystemExit(f"веса {weights} не найдены")
    clip = Path(a.video)
    if not clip.is_file():
        raise SystemExit(f"клип {clip} не найден")

    detect_every = int(cfg["detect_every"])
    out_dir = clip_out_dir(clip, cfg)
    device = None if a.device is None else (0 if a.device == "gpu" else "cpu")
    model, device = load_model(weights, device)
    tw, th = scaled_size(1920, 1080, int(cfg["width"]))
    print(f"клип {clip.name}: -> кадр {tw}x{th}, веса {weights.name}, "
          f"детекция conf {cfg['conf']} каждый {detect_every}-й кадр, device {device}")

    r = track_clip(clip, cfg, model, device, a.points, a.verbose)
    out_dir = clip_out_dir(clip, cfg)
    write_rows(out_dir / "track.csv", TRACK_COLUMNS, r["rows"])
    if a.points:
        write_rows(out_dir / "points.csv",
                   ("frame", "ms", "track_id", "x", "y", "good"), r["point_rows"])

    d = r["elapsed"]
    print(f"\nклип {r['clip'].name}: {r['size'][0]}x{r['size'][1]} @ {r['fps']:.2f} fps, "
          f"{r['duration_ms']} мс, {r['frames']} кадров, детекций {r['detections']}")
    print(f"треков создано {len(r['tracks'])}, строк {len(r['rows'])}, времени {d:.1f} с "
          f"({d / max(r['frames'], 1) * 1000:.1f} мс/кадр), артефакты: {out_dir}")
    for t in r["tracks"]:
        mean_good = t.good_sum / max(t.frames, 1)
        print(f"  track {t.id} {t.cls}: кадров {t.frames}, контрольных {t.control_frames}, "
              f"финал {t.state}, средне good {mean_good:.1f}/{t.seeded}, коаст {t.coast_ms:.0f} мс, "
              f"событий {len(t.events)}"
              + (f" ({'; '.join(t.events[:4])})" if t.events else ""))


if __name__ == "__main__":
    main()
