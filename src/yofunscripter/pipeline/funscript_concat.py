"""Энкод сегментов и склейка concat demuxer (ffmpeg).

    python scripts/funscript_concat.py --video video_source/seg-0246.mp4     # один сегмент
    python scripts/funscript_concat.py --check video_result/result.mp4        # проверка финала

Энкод: каждый сегмент получает **identical** набор параметров кодека (разрешение, fps,
профиль, pix_fmt, timescale, аудио), иначе `concat` demuxer с `-c copy` рвёт PTS: он
склеивает потоки, не перекодируя их. Склейка без перекодирования = качество не теряется.

`fps=30` из 23.976 меняет число кадров, поэтому длительность сегмента измеряется
**после** энкода: по ней считаются оффсеты тиков (funscript_merge.py).

Клип без аудио получает тишину той же длительности (`anullsrc` + `-shortest`): concat copy
требует одинакового набора потоков у всех сегментов, и сегмент без аудио его ломает.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .funscript_common import ROOT, load_config, video_duration_ms
from .progress import run_ffmpeg_progress
from .no_window import run as bg_run


def ffprobe(path: Path, cfg: dict, extra: list[str]) -> dict:
    cmd = [cfg["ffprobe_bin"], "-v", "error", *extra, str(path)]
    r = bg_run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit(f"ffprobe {path} (код {r.returncode}): {r.stderr.strip()}")
    return json.loads(r.stdout)


def fraction(text: str) -> float:
    """`avg_frame_rate` = "30/1" -> 30.0; "0/0" -> 0."""
    if not text or text == "0/0":
        return 0.0
    num, den = text.split("/")
    return float(num) / float(den) if float(den) else 0.0


def probe(path: Path, cfg: dict) -> dict:
    j = ffprobe(path, cfg, ["-show_format", "-show_streams", "-of", "json"])
    streams = j.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v is None:
        raise SystemExit(f"{path}: видеопотока нет")
    frames = int(v.get("nb_frames", 0) or 0)
    r_fps = fraction(v.get("r_frame_rate", ""))
    # timescale mp4 отдаёт только как time_base ("1/30000"), ключа timescale нет
    base = (v.get("time_base") or "").split("/")
    timescale = int(base[1]) if len(base) == 2 and base[1] else 0
    return {
        "duration_ms": int(round(float(j["format"]["duration"]) * 1000)),
        # длительность видеопотока = кадры / кадр/с; format duration длиннее на AAC-прайминг
        "video_ms": int(round(frames * 1000 / r_fps)) if r_fps > 0 and frames > 0 else 0,
        "frames": frames,
        "fps": fraction(v.get("avg_frame_rate") or v.get("r_frame_rate", "")),
        "r_fps": r_fps,
        "width": int(v["width"]), "height": int(v["height"]),
        "pix_fmt": v.get("pix_fmt", ""), "vcodec": v.get("codec_name", ""),
        "timescale": timescale,
        "acodec": a.get("codec_name") if a else None,
        "sample_rate": int(a["sample_rate"]) if a else 0,
        "channels": int(a["channels"]) if a else 0,
    }


def run_ffmpeg(cmd: list[str], cfg: dict, on_seconds: "callable | None" = None,
               progress_file: Path | None = None) -> None:
    """Запуск ffmpeg; `on_seconds` — прогресс-хук GUI (флаг `-progress` добавляется в runner).

    Команда не меняется: прогресс-файл добавляется перед output, ffmpeg дописывает в него
    out_time. Клиентский прогон (on_seconds=None) идёт ровно той же командой.
    """
    if on_seconds is None:
        r = bg_run(cmd, capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0:
            raise SystemExit(f"{cmd[0]} (код {r.returncode}): {r.stderr.strip()}")
        return
    code, tail = run_ffmpeg_progress(cmd, progress_file, on_seconds)
    if code != 0:
        raise SystemExit(f"{cmd[0]} (код {code}): {tail}")


def encode_signature(cfg: dict) -> str:
    """Параметры энкода: кэш сегмента годен только при том же.sig (concat copy требует
    identical набора кодека, сегмент из старой конфигурации рвёт PTS финала).
    `trim=1` в сиге: сегменты старого энкода несут AAC-хвост, кэш с них снимается."""
    keys = ("target_width", "target_height", "target_fps", "x264_crf", "x264_preset",
            "x264_gop", "video_track_timescale", "audio_bitrate", "audio_rate")
    return "trim=1|setpts=1|" + "|".join(f"{k}={cfg[k]}" for k in keys)


def manifest_path(concat_dir: Path) -> Path:
    return concat_dir / "segments.json"


def load_manifest(concat_dir: Path) -> dict:
    p = manifest_path(concat_dir)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def save_manifest(concat_dir: Path, data: dict) -> None:
    concat_dir.mkdir(parents=True, exist_ok=True)
    manifest_path(concat_dir).write_text(
        json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8", newline="\n")


def segment_fresh(out: Path, clip: Path, cfg: dict, manifest: dict) -> bool:
    """Кэш сегмента годен: файл есть, он закодирован **после** последней записи клипа,
    и конфигурация энкода (в manifest) та же. Клип заменён (новый mtime) => кэш не годен.
    Legacy-сегментов без записи в manifest: принимаем по mtime и записываем sig."""
    if not out.is_file():
        return False
    if out.stat().st_mtime < clip.stat().st_mtime:
        return False
    rec = manifest.get(out.name)
    return rec is None or rec.get("sig") == encode_signature(cfg)


def record_segment(concat_dir: Path, out: Path, clip: Path, encoded_ms: int, cfg: dict) -> None:
    manifest = load_manifest(concat_dir)
    st = clip.stat()
    manifest[out.name] = {
        "src_size": int(st.st_size),
        "src_mtime": int(st.st_mtime),
        "sig": encode_signature(cfg),
        "encoded_ms": int(encoded_ms),
    }
    save_manifest(concat_dir, manifest)


def clean_concat(concat_dir: Path) -> tuple[list[Path], int]:
    """Полная чистка кэша сегментов (режим `clean`): следующий прогон энкодит всё заново."""
    removed, freed = [], 0
    for p in sorted(concat_dir.iterdir()):
        if not p.is_file():
            continue
        freed += p.stat().st_size
        p.unlink()
        removed.append(p)
    return removed, freed


def concat_gc(concat_dir: Path, present: set[str]) -> tuple[list[Path], int]:
    """Сегменты клипов, которых **нет** в папке клипов, — мусор: их никогда не берут в
    склейку, и имя может повториться у нового клипа. Сегмент клипа, отобранного по
    waves, оставляем: это кэш для будущих прогонов с другим порогом."""
    manifest = load_manifest(concat_dir)
    removed, freed = [], 0
    for p in sorted(concat_dir.glob("*.mp4")):
        if p.stem in present:
            continue
        freed += p.stat().st_size
        p.unlink()
        manifest.pop(p.name, None)
        removed.append(p)
    for legacy in concat_dir.glob("concat_list*.txt"):
        legacy.unlink()
        removed.append(legacy)
    for legacy in concat_dir.glob("*.progress.txt"):
        # the runner deletes the file of its own run; leftovers of an old run are trash
        legacy.unlink()
        removed.append(legacy)
    if removed:
        save_manifest(concat_dir, manifest)
    return removed, freed


def encode(clip: Path, out: Path, cfg: dict,
           on_seconds: "callable | None" = None) -> dict:
    """Клип -> сегмент target-формата. Возвращает замер encoded-сегмента."""
    src = probe(clip, cfg)
    w, h, fps = int(cfg["target_width"]), int(cfg["target_height"]), int(cfg["target_fps"])
    out.parent.mkdir(parents=True, exist_ok=True)
    # setpts=PTS-STARTPTS: видео клипа начинается на 66 мс позже аудио (прайминг source-mp4),
    # concat copy склеивает сегменты подряд -> pts-дыра 66 мс на каждом шве (плеер подмораживает
    # кадр), format сегмента = старт + длительность
    vf = (f"setpts=PTS-STARTPTS,scale={w}:{h}:force_original_aspect_ratio=decrease,"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}")
    cmd = [cfg["ffmpeg_bin"], "-hide_banner", "-loglevel", "error", "-y", "-i", str(clip)]
    if src["acodec"] is None:
        cmd += ["-f", "lavfi", "-t", f"{src['duration_ms'] / 1000:.3f}",
                "-i", f"anullsrc=r={int(cfg['audio_rate'])}:cl=stereo",
                "-map", "0:v", "-map", "1:a", "-shortest"]
    cmd += ["-vf", vf, "-c:v", "libx264", "-crf", str(cfg["x264_crf"]),
            "-preset", str(cfg["x264_preset"]), "-profile:v", "high",
            "-pix_fmt", "yuv420p", "-g", str(cfg["x264_gop"]),
            "-keyint_min", str(cfg["x264_gop"]), "-sc_threshold", "0",
            "-video_track_timescale", str(cfg["video_track_timescale"]),
            "-c:a", "aac", "-b:a", str(cfg["audio_bitrate"]),
            "-ar", str(cfg["audio_rate"]), "-ac", "2", "-shortest",
            "-movflags", "+faststart", str(out)]
    run_ffmpeg(cmd, cfg, on_seconds, out.with_name(out.stem + ".progress.txt"))
    info = probe(out, cfg)
    # хвост аудио: audio-поток клипа длиннее видео после fps=30 (`-shortest` его не
    # обрезает), format сегмента длиннее видеопотока (~66 мс), concat copy склеивает
    # format-длительности: mp4 длиннее скрипта (4739 мс на 55 сегментах: ScriptPlayer —
    # скрипт закончился, видео идёт), на каждом шве pts-дыра ~66 мс (плеер подмораживает
    # кадр). Срезаем аудио по измеренному концу видео (`-c copy -t` — без перекодирования)
    if info["duration_ms"] > info["video_ms"]:
        tmp = out.with_name(out.stem + ".trim.mp4")
        run_ffmpeg([cfg["ffmpeg_bin"], "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(out), "-c", "copy", "-t", f"{info['video_ms'] / 1000:.3f}",
                    "-movflags", "+faststart", str(tmp)], cfg)
        tmp.replace(out)
        info = probe(out, cfg)
    return info


def concat(segments: list[Path], out: Path, cfg: dict,
           on_seconds: "callable | None" = None) -> Path:
    """Сегменты в порядке списка -> один mp4 без перекодирования (PTS считает ffmpeg)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    # список сегментов и файл прогресса — рядом с сегментами (concat_dir), а не в
    # папке результата: в ней лежат только mp4 и funscript
    lst = (segments[0].parent if segments else out.parent) / "concat_list.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in segments),
                   encoding="utf-8", newline="\n")
    run_ffmpeg([cfg["ffmpeg_bin"], "-hide_banner", "-loglevel", "error", "-y",
                "-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", str(lst),
                "-c", "copy", "-movflags", "+faststart", str(out)],
               cfg, on_seconds, lst.with_name(out.stem + ".progress.txt"))
    return lst


def packets_monotonic(path: Path, cfg: dict) -> tuple[bool, str]:
    """Видео-пакеты: pts_time в порядке показа строго возрастающие, без дублей и провалов.

    В mp4 пакеты лежат в **порядке декодирования** (B-кадры), поэтому file-order pts
    строго возрастающим не бывает по определению. Проверяем порядок предъявления (sorted pts): каждый кадр
    уникален, интервал между соседними кадрами = кадр (33 мс), стык склейки не больше
    3 кадров (33 мс..100 мс — шов, где один кадр держится дольше, это терпимо), и
    рваный PTS (дыра > 3 кадров или интервал меньше кадра) = плеер встаёт.
    """
    j = ffprobe(path, cfg, ["-select_streams", "v:0", "-show_entries", "packet=pts_time",
                            "-of", "json"])
    pts = sorted(float(p["pts_time"]) for p in j.get("packets", [])
                 if p.get("pts_time") not in (None, "N/A"))
    frame = 1000.0 / int(cfg["target_fps"])
    dupes = len(pts) - len(set(pts))
    gaps = [(b - a) * 1000.0 for a, b in zip(pts, pts[1:])]
    short = sum(1 for g in gaps if g < frame * 0.9)
    seams = sum(1 for g in gaps if g > frame * 3.0)
    worst = round(max(gaps)) if gaps else 0
    ok = len(pts) > 1 and dupes == 0 and short == 0 and seams == 0
    return (ok, f"{len(pts)} пакетов, дублей {dupes}, интервалов меньше кадра {short}, "
                f"дыр > 3 кадров {seams}, максимальный интервал {worst} мс")


def check_final(video: Path, cfg: dict, segments: int = 1) -> list[tuple[bool, str]]:
    """Финальный mp4: целевые параметры, длительность видеопотока, PTS."""
    info = probe(video, cfg)
    fps = int(cfg["target_fps"])
    # каждый сегмент с `-shortest` несёт AAC-хвост округления до AAC-кадра (<= 21.3 мс):
    # format-длительность контейнера длиннее видеопотока на сумму хвостов сегментов.
    # Скрипт выравнивается по format (длине, которую показывает плеер)
    tail_tol = 22 * max(segments, 1)
    out = [
        # avg_frame_rate = кадры / stream duration, а stream duration длиннее на прайминг
        # AAC, поэтому правильная проверка — объявленный r_frame_rate
        (info["r_fps"] == fps, f"r_frame_rate {info['r_fps']} = {fps} (avg {info['fps']})"),
        (info["width"] == int(cfg["target_width"]) and info["height"] == int(cfg["target_height"]),
         f"разрешение {info['width']}x{info['height']} (цель {cfg['target_width']}x{cfg['target_height']})"),
        (info["pix_fmt"] == "yuv420p", f"pix_fmt {info['pix_fmt']} = yuv420p"),
        (info["vcodec"] == "h264", f"видео кодек {info['vcodec']} = h264"),
        (info["acodec"] == "aac", f"аудио кодек {info['acodec']} = aac"),
        (info["sample_rate"] == int(cfg["audio_rate"]) and info["channels"] == 2,
         f"аудио {info['sample_rate']} Гц {info['channels']} кан. (цель {cfg['audio_rate']} stereo)"),
        (info["timescale"] == int(cfg["video_track_timescale"]),
         f"time_base 1/{info['timescale']} = 1/{cfg['video_track_timescale']}"),
        # формат == видеопоток: `-shortest` срезает аудио по концу видео
        (info["duration_ms"] - info["video_ms"] <= tail_tol,
         f"длительность: видео {info['video_ms']} мс ({info['frames']} кадров), "
         f"формат {info['duration_ms']} мс (разница {info['duration_ms'] - info['video_ms']} мс "
         f"= AAC-округление {segments} сегм., допуск {tail_tol})"),
    ]
    ok, line = packets_monotonic(video, cfg)
    out.append((ok, f"PTS: {line}"))
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--video", default=None, help="энкод одного клипа в configs:concat_dir")
    p.add_argument("--check", default=None, help="проверка финального mp4")
    p.add_argument("--cfg", default=None)
    a = p.parse_args()

    cfg = load_config(Path(a.cfg) if a.cfg else None)
    fails = 0
    if a.video:
        clip = Path(a.video)
        out = ROOT / cfg["concat_dir"] / (clip.stem + ".mp4")
        src = probe(clip, cfg)
        info = encode(clip, out, cfg)
        print(f"{clip.name}: {src['width']}x{src['height']} {src['fps']} fps "
              f"{src['duration_ms']} мс, аудио {src['acodec']} -> {out.name}: "
              f"{info['width']}x{info['height']} {info['fps']} fps {info['duration_ms']} мс, "
              f"timescale {info['timescale']}, аудио {info['acodec']} {info['sample_rate']} Гц")
    if a.check:
        for ok, line in check_final(Path(a.check), cfg):
            print(("PASS  " if ok else "FAIL  ") + line)
            fails += 0 if ok else 1
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()
