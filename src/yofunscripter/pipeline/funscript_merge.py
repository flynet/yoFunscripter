"""Слияние sidecar'ов отобранной последовательности в один скрипт (`video_result`).

    python scripts/funscript_merge.py --name result
    python scripts/funscript_merge.py --name result --min-waves 5

Сегменты идут в порядке `runs/funscript/selection.csv` (wave_rate возрастает). Оффсет
сегмента = сумма **измеренных после энкода** длительностей: `fps=30` из 23.976 меняет
число кадров, и оффсет по исходным длительностям уходил бы в сторону на доли кадра
на каждом стыке, а на длинной склейке — на десятки мс.

Стык: якорь конца сегмента i и якорь начала i+1 стоят в одном времени (на оффсете).
Два тика в один `at` запрещены (интервал 0 = скорость бесконечность, ScriptPlayer на этом
ломается), поэтому оба якоря снимаются, а на стыке ставится единственный якорь с
противоположным pos (`seam_join`): последний измеренный тик хвоста снимать нельзя. Дальше
голова i+1 проходится жадно — тик берётся, если pos чередуется и интервал >= min_interval,
тики совпавшей фазы снимаются.

Последний тик = якорь на суммарной измеренной длительности: длина скрипта равна длине
видео (проверяет `scripts/funscript_video.py`).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .funscript_common import ROOT, load_config, read_rows, write_rows

from .funscript_build import KIND_ANCHOR, KIND_EXTREMUM, funscript_payload, phase_fill
from .funscript_select import SELECTION_COLUMNS, read_sidecar

TICK_COLUMNS = ("ms", "pos", "kind", "peak", "support", "prom")
MERGED_COLUMNS = ("ms", "pos", "kind", "peak", "seg")


def segment_ticks(name: str, cfg: dict, encoded_ms: int) -> list[dict]:
    """ticks.csv клипа -> тики сегмента; якорь конца ставится на измеренную длительность."""
    ticks_csv = ROOT / cfg["out_dir"] / name / "ticks.csv"
    rows = read_rows(ticks_csv, TICK_COLUMNS)
    ticks = [{"ms": int(r["ms"]), "pos": int(r["pos"]), "kind": r["kind"],
              "peak": r["peak"], "support": int(r["support"]), "prom": float(r["prom"])}
             for r in rows]
    if not ticks:
        raise SystemExit(f"{ticks_csv}: тиков нет — клип не годится для склейки")
    ticks[0]["ms"] = 0
    ticks[-1]["ms"] = encoded_ms
    for i in range(1, len(ticks)):
        if ticks[i]["ms"] <= ticks[i - 1]["ms"]:
            raise SystemExit(f"{ticks_csv}: тик {i} ({ticks[i]['ms']}) не после {ticks[i-1]['ms']}")
    return ticks


KIND_SEAM = "seam"


def seam_join(tail: list[dict], head: list[dict], min_interval: int) -> tuple[list[dict], int, int]:
    """Хвост сегмента i + голова сегмента i+1 -> один ряд тиков без шва.

    Якорь конца i и якорь начала i+1 стоят в одном `at` (два тика в один `at` = интервал 0
    = бесконечная скорость, ScriptPlayer на этом ломается), поэтому оба снимаются. Снимать
    при этом последний **измеренный** тик хвоста нельзя (это реальный экстремум), поэтому
    на стыке ставится единственный якорь `pos = 100 - pos` последнего тика хвоста:
    чередование 0/100 сохраняется. Голова проходится жадно: тик берётся, если pos
    противоположен предыдущему и интервал >= min_interval; тики той же позиции (фаза
    совпала) снимаются — движения между ними нет. Якорь конца i+1 остаётся всегда
    (длина скрипта = длина видео): если он не проходит по pos, pos ставится противоположным.

    Снятие тика головы оставляет дыру: 1570 мс = 3.7 полупериода, это видимая пауза на стыке.
    Поэтому голова после жадного прохода заполняется фазовыми тиками (`phase_fill`) по шагу
    этого сегмента. Возвращает ряд, число снятых тиков (якоря + совпавшие фазы) и число
    добавленных фазовых.
    """
    out = tail[:-1]
    last = out[-1]
    seam_at = head[0]["ms"]
    acc: list[dict] = []
    if seam_at - last["ms"] >= min_interval:
        last = {"ms": seam_at, "pos": 100 - last["pos"], "kind": KIND_SEAM, "peak": "",
                "seg": head[0]["seg"], "support": 0, "prom": 0.0}
        acc.append(last)
    for h in head[1:]:
        if h["pos"] != last["pos"] and h["ms"] - last["ms"] >= min_interval:
            acc.append(h)
            last = h
    anchor = head[-1]
    if not acc or acc[-1]["ms"] != anchor["ms"]:
        acc.append({"ms": anchor["ms"], "pos": 100 - last["pos"], "kind": KIND_ANCHOR,
                    "peak": "", "seg": anchor["seg"], "support": 0, "prom": 0.0})
    steps = sorted(b["ms"] - a["ms"] for a, b in zip(head, head[1:]))
    step = int(steps[len(steps) // 2]) if len(steps) > 1 else min_interval
    filled = phase_fill(acc, step, min_interval) if len(acc) > 1 else acc
    for t in filled:
        t.setdefault("seg", head[0]["seg"])      # slots фазового fill'а без seg
    out.extend(filled)
    dropped = 1 + len(head) - len(acc)      # якорь хвоста + снятые тики головы
    return out, dropped, len(filled) - len(acc)


def merge_segments(segments: list[dict], cfg: dict) -> list[dict]:
    """Сегменты (в порядке склейки) -> тики единого скрипта с `seg` и оффсетами.

    Каждый segment: {"name", "clip", "sidecar", "ticks", "encoded_ms", "waves", "wave_rate"}.
    Поля "offset_ms" и "seam_drop" дописываются.
    """
    min_interval = int(cfg["min_interval_ms"])
    merged: list[dict] = []
    offset = 0
    for i, seg in enumerate(segments):
        seg["offset_ms"] = offset
        shifted = [{"ms": t["ms"] + offset, "pos": t["pos"], "kind": t["kind"],
                    "peak": t["peak"], "seg": i, "support": t.get("support", 0),
                    "prom": t.get("prom", 0.0)}
                   for t in seg["ticks"]]
        if not merged:
            merged = shifted
            seg["seam_drop"] = 0
            seg["seam_phase"] = 0
        else:
            merged, dropped, added = seam_join(merged, shifted, min_interval)
            seg["seam_drop"] = dropped
            seg["seam_phase"] = added
        seg["ticks_out"] = len(merged)
        offset += int(seg["encoded_ms"])
    return merged


def merged_gap_check(merged: list[dict], segments: list[dict], cfg: dict) -> tuple[bool, str]:
    """Разрывы по шагу экстремумов **каждого сегмента**, а не по общему медианному шагу.

    Интервал между соседними экстремумами = полупериод клипа, и он свой у каждого: 420 мс
    у быстрого, 620 мс у медленного. Медиана по всем тикам (экстремумы + фаза) меньше
    полупериода: по ней разрыв 880 мс у клипа с полупериодом 420 = 2.1 полупериода, то есть
    один полный цикл движения, а не плато.

    **Плато = соседние тики с одинаковым `pos`** ( device стоит). При чередующемся pos
    интервал = движение: 320 мс при 100 единицах = 312 ед/с, это медленный штрих, а не
    плато. Поэтому граница = **3.5 полупериода** сегмента: 2.5 резала натуральные
    медленные штрихи быстрых клипов (замер 97 клипов: seg-0154 320 мс при медиане 120,
    seg-0156 320 при 120 — pos 100->0, движение). Граница стыка = больший из двух.
    """
    min_interval = int(cfg["min_interval_ms"])
    min_stroke = int(cfg["min_stroke_units"])
    binary = bool(cfg.get("pos_binary", True))
    bounds = {}
    for i, seg in enumerate(segments):
        ext = [t for t in seg["ticks"] if t["kind"] == KIND_EXTREMUM]
        steps = sorted(b["ms"] - a["ms"] for a, b in zip(ext, ext[1:]))
        step = int(steps[len(steps) // 2]) if len(steps) > 1 else min_interval
        # бинарный 0 -> 100 -> 0: середина монотонного хода = pos 50, которого нет.
        # Граница разрыва не применяется; плато (одинаковый pos) по-прежнему запрещён
        bounds[i] = 0 if binary else max(round(3.5 * step), min_interval)
    worst, worst_at, bad, plateaus = 0, "", 0, 0
    for a, b in zip(merged, merged[1:]):
        gap = b["ms"] - a["ms"]
        bound = max(bounds[a["seg"]], bounds[b["seg"]])
        if a["pos"] == b["pos"]:
            plateaus += 1
            if gap > worst:
                worst, worst_at = gap, f"{a['ms']}->{b['ms']} плато (pos {a['pos']})"
        elif not binary and gap > bound and abs(b["pos"] - a["pos"]) >= min_stroke:
            bad += 1
            if gap > worst:
                worst, worst_at = gap, f"{a['ms']}->{b['ms']}"
    per = ", ".join(f"{s['name']}<={bounds[i]}" for i, s in enumerate(segments))
    mode = "бинарный 0/100: плато" if binary else "3.5 полупериода сегмента"
    return (bad == 0 and plateaus == 0,
            f"разрывы по {mode} ({per}), max из них "
            f"{max(bounds.values()) if bounds else 0} мс; превышений {bad}, плато (pos подряд) "
            f"{plateaus}{f' (max {worst} мс: {worst_at})' if worst else ''}")


def merged_ticks(merged: list[dict], cfg: dict, name: str, total_ms: int) -> None:
    """Артефакты мерджа в runs/funscript/<name>/ (viewer и check читают их по пути видео).

    `support` уmerged-тиков = поддержка сегмента (0 для шва и якорей): единый скрипт
    наследует поддержку тика того сегмента, из которого тик взят.
    """
    out_dir = ROOT / cfg["out_dir"] / name
    write_rows(out_dir / "ticks.csv", TICK_COLUMNS,
               [{"ms": t["ms"], "pos": t["pos"], "kind": t["kind"], "peak": t["peak"],
                 "support": t.get("support", 0), "prom": t.get("prom", 0.0)} for t in merged])
    write_rows(out_dir / "merged.csv", MERGED_COLUMNS,
               [{"ms": t["ms"], "pos": t["pos"], "kind": t["kind"], "peak": t["peak"],
                 "seg": t["seg"]} for t in merged])


def merged_payload(merged: list[dict], segments: list[dict], name: str, cfg: dict,
                   total_ms: int) -> dict:
    waves = sum(int(s["waves"]) for s in segments)
    meta = {
        "title": name,
        "creator": "yolo funscript merge",
        "duration": int(total_ms),
        "totalDuration": int(total_ms),
        "tags": ["ai-generated", "merged"],
        "notes": " | ".join(f"{s['name']}@{s['offset_ms']}" for s in segments),
        "waves": waves,
        "wave_rate": round(waves * 1000.0 / max(total_ms, 1), 3),
    }
    return funscript_payload(merged, meta, "funscript", int(cfg["range"]))


def write_merged(payload: dict, merged: list[dict], segments: list[dict], name: str,
                 cfg: dict, total_ms: int) -> Path:
    result_dir = ROOT / cfg["result_dir"]
    result_dir.mkdir(parents=True, exist_ok=True)
    out_dir = ROOT / cfg["out_dir"] / name
    out_dir.mkdir(parents=True, exist_ok=True)
    sidecar = result_dir / (name + ".funscript")
    sidecar.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")), encoding="utf-8")
    (ROOT / cfg["out_dir"] / name / "funscript.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    merged_ticks(merged, cfg, name, total_ms)
    meta = {
        "clip": str(ROOT / cfg["result_dir"] / (name + ".mp4")),
        "duration_ms": total_ms,
        "grid_ms": int(cfg["grid_ms"]),
        "frame_ms": round(1000.0 / int(cfg["target_fps"]), 3),
        "chosen_track": "merged",
        "chosen_class": f"{len(segments)} seg",
        "segments": [{"name": s["name"], "offset_ms": s["offset_ms"],
                      "encoded_ms": s["encoded_ms"], "waves": s["waves"],
                      "wave_rate": s["wave_rate"]} for s in segments],
        "waves": payload["metadata"]["waves"],
        "wave_rate": payload["metadata"]["wave_rate"],
        "reason": "",
        "tracks": [],
    }
    (ROOT / cfg["out_dir"] / name / "signal_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return sidecar


def load_order(name: str, cfg: dict, encoded: dict[str, int] | None = None) -> list[dict]:
    """selection.csv + measured длительности -> сегменты в порядке склейки."""
    rows = read_rows(ROOT / cfg["out_dir"] / "selection.csv", SELECTION_COLUMNS)
    out = []
    for r in rows:
        if r["status"] != "kept" or not r["order"]:
            continue
        encoded_ms = encoded[r["name"]] if encoded else int(r["duration_ms"])
        sidecar = Path(r["sidecar"])
        info = read_sidecar(sidecar)
        out.append({"order": int(r["order"]), "name": r["name"], "clip": r["clip"],
                    "sidecar": str(sidecar), "waves": info["waves"],
                    "wave_rate": info["wave_rate"], "source_ms": int(r["duration_ms"]),
                    "encoded_ms": encoded_ms, "ticks": segment_ticks(r["name"], cfg, encoded_ms)})
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", default=None, help="имя финала (configs:result_name)")
    p.add_argument("--cfg", default=None)
    p.add_argument("--no-write", action="store_true", help="только посчитать и напечатать")
    a = p.parse_args()

    cfg = load_config(Path(a.cfg) if a.cfg else None)
    name = a.name or str(cfg["result_name"])
    segments = load_order(name, cfg)
    if not segments:
        raise SystemExit("selection.csv: отобранных клипов нет")
    merged = merge_segments(segments, cfg)
    total_ms = int(segments[-1]["offset_ms"]) + int(segments[-1]["encoded_ms"])
    payload = merged_payload(merged, segments, name, cfg, total_ms)
    print(f"сегментов {len(segments)}, тиков {len(merged)}, длительность {total_ms} мс, "
          f"волн {payload['metadata']['waves']} "
          f"({payload['metadata']['wave_rate']} волн/с)")
    for s in segments:
        print(f"  {s['order']} {s['name']}: оффсет {s['offset_ms']}, "
              f"{s['encoded_ms']} мс, {len(s['ticks'])} тиков, волн {s['waves']}")
    at = [t["ms"] for t in merged]
    gaps = [b - a for a, b in zip(at, at[1:])]
    print(f"  интервалы min {min(gaps)}, max {max(gaps)}, стыки: "
          + ", ".join(f"{s['offset_ms']}" for s in segments[1:]))
    if not a.no_write:
        sidecar = write_merged(payload, merged, segments, name, cfg, total_ms)
        print(f"sidecar: {sidecar}")


if __name__ == "__main__":
    main()
