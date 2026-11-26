r"""Batch: видео -> сцены -> нарезанные клипы (PySceneDetect CLI + ffmpeg).

Видео из source_dir (по умолчанию video_full) режутся по границам сцен; выходы кладутся
плоско в out_dir (по умолчанию video_source): sexy.mp4 -> sexy-s001.mp4.

    python scripts/scenedetect_run.py                    # прогон video_full
    python scripts/scenedetect_run.py --dry              # план, ничего не пишет
    python scripts/scenedetect_run.py --force            # детект + рез поверх существующего
    python scripts/scenedetect_run.py --detect-only      # только списки сцен
    python scripts/scenedetect_run.py --cut-only         # рез из готовых списков
    python scripts/scenedetect_run.py --limit 20
    python scripts/scenedetect_run.py --root video --pattern "**/*.mp4" --jobs 6
    python scripts/scenedetect_run.py --filter VIXEN

Детект делает библиотека scenedetect (histogram_detector + frame_timecode, детектор и пороги
из `configs/scenes.yaml`): список сцен пишется в том же формате, что `list-scenes --skip-cuts`:

  <видео>-scene-list.csv

Рез: ЧАНКИ по `max_outputs` сцен — граф `split + trim=start_frame/end_frame` по номерам
кадров из CSV, и клип нормализуется ЗДЕСЬ, один раз: граф содержит `fps=target_fps`,
`scale/pad/setsar` до target_width x target_height, все выходы кодируются с одинаковым
набором (crf, gop, timescale, bframes 0, faststart, AAC 48k stereo). Склейка
(`funscript_concat.py`) читает такие клипы `-c copy` без перекодирования: перекод клипа
при склейке = вторая полная потеря качества и ~1.0x realtime на клип.

Чанк — это НЕ склейка и не второй проход: каждый клип кодируется один раз, файл клипа и
есть результат. Один ffmpeg на всё видео не влазит в Windows дважды: командная строка на
1623 выходов = ~330 000 символов при пределе `CreateProcess` 32768 (замер Project2.mp4,
2h37m: `FileNotFoundError: [WinError 206]`, ffmpeg не стартует, файлов 0), и `split=1623`
держит 1623 живых энкодеров x264 1080p (~15 MB каждый = ~24 GB). Чанк читает только свой
участок (`-ss` на ключевой кадр ≤ начала чанка, `-t` по концу чанка), и энкодирование всего
видео — один проход, как в одном процессе. Аргументы ffmpeg из файла (`ffmpeg @file`) этот
ffmpeg НЕ читает: бандль N-122110 принимает `@file` за выход (`Unable to choose an output
format for '@...`), поэтому все флаги выходов обязаны быть в командной строке.

trim по номеру кадра точен: проверено на 12 границах sexy.mp4, первые 4 кадра клипа =
кадры оригинала Start Frame - 1, последние кадры = End Frame - 1. До графа пробовали:

  -ss по границам без offset: сдвиг на 2 кадра. video_full/sexy.mp4: -ss 121.480 сажает
    ffmpeg на кадр 3035 вместо 3037; у 11 (2).mp4 первый pts_time = 0.08 с (edit list),
    offset = max(pts-dts) файла, и клип начинается с хвоста прошлой сцены.
  segment muxer с -segment_frames: режет по ключевым кадрам, границы съезжают
    (seg003=750 кадров вместо 533, seg001=325 вместо 78).

Граф идёт с `-reinit_filter 0`: у 11 (3).mp4 на 31.3 с кадры меняют цветовые метаданные
(unknown -> bt709/tv, пиксели те же yuv420p), ffmpeg пересобирал граф, trim/atrim
начинали счёт кадров заново, клипы после этой точки получали не те кадры, а последние
два не получали ничего ("Could not open encoder before EOF"). Замер без флага: 56
"Non-monotonic DTS", аудио 13.803 с вместо 14.000; с флагом — 0 и 14.000.

Энкод: CPU libx264 (crf 18, veryfast = 8.7x realtime). NVENC (GPU) включается, когда
устройство cuda: vcodec = h264_nvenc, но не больше nvenc_max_outputs выходов в одном
процессе — GeForce обрывает параллельные NVENC-сессии по лимиту (замер 11 (2).mp4, 20
сцен: "Error while opening encoder" на 13-м выходе, файлы 18-20 пустые). Чанк строится
не больше этого лимита, поэтому NVENC работает на всех чанках; скорость NVENC p5 (9x) и
x264 veryfast (8.7x) одинакова.

Границы CSV (docs): Length (frames) = End Frame - Start Frame + 1, то есть Start Frame и
End Frame = первый и последний кадр сцены (inclusive), следующая сцена = End Frame + 1.
Клип = кадры Start-1 .. End-1 (head_frames=0, tail_frames=0: чужих кадров ни в начале,
ни в конце). head_frames/tail_frames = отступ за границу, если склейку нужно видеть.

Качество: массовый прогон = crf 18 (1.4x объёма, 8.7x realtime); crf 0 = lossless, режим
для пилотов (19x объёма). preset = скорость кодирования, к потери качества отношения не
имеет.

Аудио режется atrim по секундам и кодируется AAC 192k 48000 stereo — ровно как формат
склейки (scripts/funscript_concat.py), файл которого ScriptPlayer играет. ALAC (44100)
в обычном видео-плеере играет, а ScriptPlayer звук потерял. Копировать аудио нельзя:
-c:a copy при -ss берёт звук от точки реза до конца ФАЙЛА, контейнер получается длиннее
видео (замер: 5.2 с видео -> 24.9 с контейнера), плеер стоит на последнем кадре и
«висит» до конца звука. audio: false = клипы без звука (-an).

Хвост AAC-округления (энкод даёт аудио длиннее видео до 21.3 мс) срезается `-t Length/fps`
в самом резовом процессе, а не пост-тримом: отдельный ffmpeg на каждый клип = 1623 процесса
на 2h37m (минуты простоя и `tmp.replace` на каждый файл). `-shortest` не используем: он
срезает ПОСЛЕДНИЙ КАДР (замер: клип 20, Length 751 -> 750 кадров). `-movflags +faststart`
тоже стоит в резе: moov в начале файла пишется сразу, второй проход не нужен.

Замер клипа, который ScriptPlayer показывал чёрным 10 с и без звука, против эталона
video_result/result_1.mp4 (30 fps, играет): у клипа time_base 1/12800, moov в конце файла
(offset 37255441 из 37292605), gop 250 = ключевые кадры каждые 10.0 с, первый видео-пакет
dts_time=-0.080000 (B-кадры). У эталона: time_base 1/30000, moov в начале, gop 60 =
ключевик каждые 2.0 с, первый dts 0.020333. Замер -bf 0: pts == dts и dts 0.000000, но
AAC даёт аудио pts_time=-0.023220 (priming), ALAC — 0.000000.

Идемпотентность: список сцен новее видео -> детект пропущен; нарезанных файлов ровно по
числу сцен -> рез пропущен. min_scenes: видео с одной сценой не режется (5-сек клик =
один план в 95% случаев). Отчёт runs/scenes/stats.csv пишется каждым прогоном и содержит
все посещённые видео, включая пропуски. Код 1, если хотя бы одно видео дало ошибку.
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import threading
import time
from bisect import bisect_left, bisect_right

from .cancel import CancelToken
from .progress import CMD_CHAR_LIMIT, run_ffmpeg_progress
from .paths import layout
from .no_window import run as bg_run
from yofunscripter.i18n import tr
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCENES_CONFIG = ROOT / "configs" / "scenes.yaml"

CFG_KEYS = ("ffmpeg", "ffprobe", "source_dir", "out_dir", "scenes_dir",
            "stats_dir", "pattern", "detector", "threshold", "bins", "min_scene_len",
            "min_scenes", "crf",
            "preset", "jobs", "name_template", "list_template", "head_frames",
            "tail_frames", "audio", "audio_codec", "audio_bitrate", "audio_rate",
            "audio_channels", "profile", "gop", "timescale", "faststart", "bframes",
            "target_fps", "target_width", "target_height", "vcodec", "encoder_threads",
            "nvenc_preset", "nvenc_rc", "nvenc_cq", "nvenc_max_outputs", "max_outputs")

#: `CreateProcess` fails above 32768 characters of the command line (WinError 206: the
#: process never starts), so the scenes of one ffmpeg process are counted from the bytes
#: one output block costs, with a margin for the graph name and the progress path.
CHUNK_CHAR_BUDGET = 30000

STATS_COLUMNS = ("video", "stem", "scene_list", "scenes", "out_files", "out_mb",
                 "status", "detect_s", "cut_s", "kf_max_gap", "min_dts", "moov_first",
                 "reason")

ST_PLAN = "plan"
ST_DETECT = "detect"
ST_CUT = "cut"
ST_SKIP = "skip"
ST_SINGLE = "single"
ST_ERROR = "error"

EMPTY_ROW = {"scenes": "", "out_files": "", "out_mb": "", "detect_s": "", "cut_s": "",
             "kf_max_gap": "", "min_dts": "", "moov_first": "", "reason": ""}


def load_config(path: Path | None = None) -> dict:
    path = path or SCENES_CONFIG
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in CFG_KEYS:
        if key not in cfg:
            raise SystemExit(f"{path}: нет ключа {key}")
    return cfg


def run_cli(cmd: list[str]) -> tuple[int, str]:
    """Список аргументов: путь с пробелами не требует кавычек. Вывод декодируется с
    errors=replace — бандл печатает в консольную кодовую страницу, и декод utf-8 на
    кириллице не должен ронять прогон. Хвост вывода нужен для причины ошибки в отчёте,
    поэтому stderr не выбрасывается."""
    proc = bg_run(cmd, capture_output=True)
    text = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    tail = " | ".join(line.strip() for line in text.splitlines() if line.strip())
    return proc.returncode, tail[-260:]


def probe_video(cfg: dict, video: Path) -> tuple[float, str]:
    """fps и пиксельный формат из ffprobe, без декодирования.

    format=yuv420p в графе запрещён: при crf 0 он конвертирует пиксели, и lossless
    теряется. x264 кодирует 8-битные yuv420p/yuv422p/yuv444p; 10-битные форматы
    (yuv420p10le) он не умеет, такой источник помечается пропуском."""
    proc = bg_run([cfg["ffprobe"], "-v", "error", "-select_streams", "v:0",
                           "-show_entries", "stream=avg_frame_rate,pix_fmt",
                           "-of", "default=noprint_wrappers=1", str(video)],
                          capture_output=True)
    fields = {}
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            fields[k] = v.strip()
    rate = fields.get("avg_frame_rate", "0/0").split("/")
    if len(rate) != 2 or float(rate[1]) == 0:
        raise ValueError(f"avg_frame_rate {rate} — fps неизвестен")
    return float(rate[0]) / float(rate[1]), fields.get("pix_fmt", "")


X264_FORMATS = ("yuv420p", "yuv422p", "yuv444p", "yuvj420p", "yuvj422p", "yuvj444p")


def has_audio(cfg: dict, video: Path) -> bool:
    """ffprobe без декодирования: есть ли аудиопоток (asplit на пустом потоке падает)."""
    proc = bg_run([cfg["ffprobe"], "-v", "error", "-select_streams", "a",
                           "-show_entries", "stream=index", "-of", "csv=p=0", str(video)],
                          capture_output=True)
    return bool(proc.stdout.decode("utf-8", "replace").strip())


def probe_stream(cfg: dict, path: Path, stream: str) -> dict:
    fields = {}
    proc = bg_run([cfg["ffprobe"], "-v", "error", "-select_streams", stream,
                           "-show_entries",
                           "stream=codec_name,sample_rate,channels,time_base,nb_frames,"
                           "duration,avg_frame_rate",
                           "-of", "default=noprint_wrappers=1", str(path)], capture_output=True)
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            fields[k] = v.strip()
    return fields


def keyframes(cfg: dict, path: Path) -> list[float]:
    """pts_time ключевых кадров (-skip_frame nokey декодирует только их). Первая строка
    ffprobe печатает с запятой («0.000000,»), поэтому запятые снимаются."""
    proc = bg_run([cfg["ffprobe"], "-v", "error", "-skip_frame", "nokey",
                           "-select_streams", "v:0", "-show_entries", "frame=pts_time",
                           "-of", "csv=p=0", str(path)], capture_output=True)
    pts = []
    for token in proc.stdout.decode("utf-8", "replace").split():
        clean = token.strip().strip(",")
        if clean:
            pts.append(float(clean))
    return sorted(pts)


def packets(cfg: dict, path: Path) -> list[tuple[float, bool]]:
    """(pts_time, ключевой) всех видеопакетов в порядке декодирования; pts без значения = None.

    Порядок ffprobe = порядок ДЕКОДИРОВАНИЯ, не показа: с B-кадрами pts идут 0, 0.1251,
    0.0834, 0.0417 (замер фикстура), поэтому порядок показа = сортировка pts.
    """
    proc = bg_run([cfg["ffprobe"], "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0",
                          str(path)], capture_output=True)
    rows = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        parts = line.strip().rstrip(",").split(",")
        if not parts[0]:
            continue
        try:
            pts = float(parts[0])
        except ValueError:
            continue
        rows.append((pts, len(parts) > 1 and parts[1].startswith("K")))
    return rows


def keyframe_index(cfg: dict, path: Path) -> list[tuple[float, int]]:
    """(pts, номер кадра в порядке ПОКАЗА) ключевых кадров, по pts.

    `trim=start_frame=N` считает кадры в порядке показа (декодер переупорядочивает
    B-кадры), поэтому номер кадра = число пакетов с pts МЕНЬШЕ pts ключевого.
    `round(pts*fps)` для номера не годится: нерегулярные pts (VFR, edit list,
    накопленный дрейф) округляют номер мимо реального кадра, trim стартует ДО границы
    сцены, и первые кадры клипа = хвост прошлой сцены (замер фикстура
    `cut-24chunks-drift`: база 252 против индекса 250 = 2 кадра прошлой сцены в s017).
    """
    rows = packets(cfg, path)
    shown = sorted(p for p, _ in rows if p is not None)
    return sorted((p, bisect_left(shown, p)) for p, key in rows if key and p is not None)


def stream_start(cfg: dict, video: Path) -> float:
    """start_time видеопотока = первый pts файла в секундах. У HEVC с B-кадрами и edit
    list он отрицательный (замер: -0.080), и номера кадров чанка идут от него, не от нуля."""
    proc = bg_run([cfg["ffprobe"], "-v", "error", "-select_streams", "v:0",
                           "-show_entries", "stream=start_time",
                           "-of", "default=noprint_wrappers=1", str(video)],
                          capture_output=True)
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        if line.startswith("start_time="):
            try:
                return float(line.split("=", 1)[1])
            except ValueError:
                return 0.0
    return 0.0


def keyframe_map(cfg: dict, video: Path) -> tuple[float, list[tuple[float, int]]]:
    """(start_time, (pts, номер кадра) ключевых кадров) — один снимок на видео, по нему чанки
    ищут вход.

    `-ss` перед `-i` сажает процесс на ключевой кадр <= времени, первый декодированный кадр =
    этот ключевой, и номера trim считаются от него. Без карты каждый чанк читал бы файл
    целиком: 2h37m x 102 процесса.
    """
    return stream_start(cfg, video), keyframe_index(cfg, video)


def seek_point(keys: list[tuple[float, int]], target_s: float) -> tuple[float | None, int]:
    """(-ss чанка, номер кадра первого декодированного кадра); None = чанк с нуля, -ss не нужен.

    Ключевой кадр берётся <= времени чанка: trim не отрезает кадр раньше границы, лишнее
    декодирование = один gop оригинала на чанк.
    """
    if not keys:
        return None, 0
    i = bisect_right(keys, (target_s, float("inf"))) - 1
    if i <= 0:
        return None, 0
    return keys[i]


def frame_avg(cfg: dict, source: Path, start_s: float | None,
              frame_index: int = 0) -> tuple[int, int, int] | None:
    """Средний пиксель кадра (rgb24): кадр оригинала на границе против первого кадра клипа.

    `-ss` перед `-i` сажает процесс на ключевой кадр <= времени, сам он даёт только этот
    ключевой кадр, поэтому кадр границы выбирает фильтр `trim`: от ключевого кадра до
    границы декодируется один gop. Пакетный CRC первого кадра клипа ВСЕГДА отличается от
    CRC оригинала: клип нормализуется (fps, scale) и переэнкодится (замер фикстура: кадр
    49 оригинала = CRC 0x6632d360, клип s002 кадр 0 = 0x2e901bdd), поэтому граница
    сверяется по пикселям, а не по CRC.
    """
    cmd = [cfg["ffmpeg"], "-hide_banner", "-loglevel", "error", "-nostats"]
    if start_s is not None:
        cmd += ["-ss", f"{start_s:.6f}"]
    cmd += ["-i", str(source)]
    vf = ["scale=1:1", "format=rgb24"]
    if frame_index:
        vf.insert(0, f"trim=start_frame={frame_index}:end_frame={frame_index + 1}")
    cmd += ["-vf", ",".join(vf), "-frames:v", "1", "-f", "rawvideo", "-"]
    proc = bg_run(cmd, capture_output=True)
    if proc.returncode != 0 or len(proc.stdout) < 3:
        return None
    return proc.stdout[0], proc.stdout[1], proc.stdout[2]



def min_dts(cfg: dict, path: Path) -> float | None:
    """Минимальный dts_time видеопотока: отрицательный = плеер, который открывается по
    .funscript, стартует с задержки (mp4 пишет edit list). Замер -bf 0: pts == dts = 0."""
    proc = bg_run([cfg["ffprobe"], "-v", "error", "-select_streams", "v:0",
                           "-show_entries", "packet=dts_time", "-of", "csv=p=0", str(path)],
                          capture_output=True)
    vals = [float(x.strip().strip(",")) for x in
            proc.stdout.decode("utf-8", "replace").split() if x.strip().strip(",")]
    return min(vals) if vals else None


def box_order(path: Path) -> list[str]:
    """Верхнеуровневые боксы mp4 по порядку: moov до mdat = индекс в начале файла."""
    types = []
    total = path.stat().st_size
    with path.open("rb") as fh:
        pos = 0
        while pos < total:
            fh.seek(pos)
            head = fh.read(8)
            if len(head) < 8:
                break
            size = int.from_bytes(head[:4], "big")
            if size == 1:
                size = int.from_bytes(fh.read(8), "big")
            elif size == 0:
                size = total - pos
            types.append(head[4:8].decode("ascii", "replace"))
            pos += size
    return types


def check_clips(cfg: dict, out_paths: list[Path], target_fps: float) -> tuple[dict, list[str]]:
    """Проверка клипа по критериям эталона (video_result/result_1.mp4, играет в
    ScriptPlayer): fps нормализации, timescale, шаг ключевых кадров, moov в начале, аудио
    48000 stereo, неотрицательный dts. Меряются ПЕРВЫЙ и ПОСЛЕДНИЙ клип видео: все клипы
    вышли одним процессом ffmpeg, и 2 части файла достаточно (клипы = 200-4000 кадров,
    ffprobe на все 12789 кликов video/ = часы). Агрегат: худший kf_max_gap, худший min_dts."""
    stats = {"kf_max_gap": 0.0, "min_dts": 0.0, "moov_first": True}
    problems = []
    fps = float(target_fps)
    gop_gap = int(cfg["gop"]) / fps
    for path in {out_paths[0], out_paths[-1]}:
        v = probe_stream(cfg, path, "v:0")
        rate = (v.get("avg_frame_rate") or "0/0").split("/")
        clip_fps = float(rate[0]) / float(rate[1]) if len(rate) == 2 and float(rate[1]) else 0.0
        if abs(clip_fps - fps) > 0.5:
            problems.append(f"{path.name}: fps {clip_fps} != {cfg['target_fps']} "
                            f"(граф реза нормализует клип)")
        ts = v.get("time_base", "").split("/")[-1]
        if ts != str(cfg["timescale"]):
            problems.append(f"{path.name}: time_base 1/{ts} != 1/{cfg['timescale']}")
        pts = keyframes(cfg, path)
        gaps = [b - a for a, b in zip(pts, pts[1:])]
        gap = round(max(gaps), 3) if gaps else 0.0
        # sc_threshold 0 ставит ключевик и на смену сцены, поэтому шаг строго не больше gop
        if gap > gop_gap + 1.0 / fps:
            problems.append(f"{path.name}: шаг ключевых кадров {gap} с > gop {cfg['gop']} "
                            f"({gop_gap:.3f} с)")
        stats["kf_max_gap"] = max(stats["kf_max_gap"], gap)
        dts = min_dts(cfg, path)
        if dts is not None and dts < 0:
            problems.append(f"{path.name}: min dts {dts} < 0")
        stats["min_dts"] = min(stats["min_dts"], dts if dts is not None else 0.0)
        types = box_order(path)
        fast = bool(cfg["faststart"])
        first = "moov" in types and (fast or "mdat" not in types
                                     or types.index("moov") < types.index("mdat"))
        stats["moov_first"] = stats["moov_first"] and first
        if fast and not first:
            problems.append(f"{path.name}: moov не в начале ({types[:3]})")
        a = probe_stream(cfg, path, "a:0")
        if cfg["audio"] and a.get("codec_name"):
            if a.get("codec_name") != cfg["audio_codec"]:
                problems.append(f"{path.name}: аудио {a.get('codec_name')} != {cfg['audio_codec']}")
            if int(a.get("sample_rate", 0)) != int(cfg["audio_rate"]):
                problems.append(f"{path.name}: аудио {a.get('sample_rate')} Гц != {cfg['audio_rate']}")
            if int(a.get("channels", 0)) != int(cfg["audio_channels"]):
                problems.append(f"{path.name}: аудио {a.get('channels')} кан. != {cfg['audio_channels']}")
            a_dur = float(a.get("duration", 0) or 0)
            v_dur = float(v.get("duration", 0) or 0)
            # AAC округляет до кадра (<= 21.3 мс), -shortest срезает хвост по концу видео
            if abs(a_dur - v_dur) > 0.05:
                problems.append(f"{path.name}: аудио {a_dur} с против видео {v_dur} с")
    return stats, problems


def scene_rows(csv_path: Path) -> list[dict]:
    """Список сцен CSV: строка Scene Number на сцену, та же колонка Start Frame, что
    печатает list-scenes --skip-cuts."""
    if not csv_path.is_file():
        return []
    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if rows and "Start Frame" not in rows[0]:
        raise ValueError(f"{csv_path}: нет колонки Start Frame — список не наш формат")
    return rows


def produced(out_dir: Path, stem: str) -> list[Path]:
    """Выходы этого видео: <stem>-sNNN.mp4. glob не используем: имена видео содержат
    скобки и [ ] трактуются как класс символов."""
    if not out_dir.is_dir():
        return []
    return [p for p in out_dir.iterdir()
            if p.is_file() and p.suffix.lower() == ".mp4" and p.name.startswith(f"{stem}-s")]


def list_of(stem: str, cfg: dict) -> str:
    """Имя CSV из шаблона list_template: $VIDEO_NAME = stem без расширения."""
    return cfg["list_template"].replace("$VIDEO_NAME", stem)


# Параметры, которые меняют bytes клипа: их сигнатура пишется в scenes_dir/<stem>-cut.sig.
# Сменили crf/gop/timescale/audio/нормализацию в конфиге -> клипы переэнкодятся; список сцен
# при этом не пере детектируется (детект от флагов кодирования не зависит).
SIGN_KEYS = ("crf", "preset", "profile", "gop", "bframes", "timescale", "faststart",
             "audio", "audio_codec", "audio_bitrate", "audio_rate", "audio_channels",
             "head_frames", "tail_frames", "target_fps", "target_width", "target_height",
             "vcodec", "nvenc_preset", "nvenc_rc", "nvenc_cq")


def signature(cfg: dict) -> str:
    return "|".join(f"{k}={cfg[k]}" for k in SIGN_KEYS)


def out_name(stem: str, scene: int, cfg: dict) -> str:
    """Имя клипа из шаблона: $SCENE_NUMBER дополняется до 3 цифр, расширение добавляется."""
    name = cfg["name_template"].replace("$VIDEO_NAME", stem).replace("$SCENE_NUMBER", f"{scene:03d}")
    return name if name.lower().endswith(".mp4") else name + ".mp4"


#: Имена для ключа `detector` — по CLI-командам `detect-*`.
DETECTORS = ("hist", "content", "adaptive", "hash", "threshold")


def make_detector(cfg: dict):
    """Детектор из configs/scenes.yaml: `detector` + `threshold`, `bins`, `min_scene_len`.

    `hist` = CLI `detect-hist --threshold 0.1 --bins 240`: гистограмма Y-канала YUV на кадр,
    склейка, когда разница гистограмм соседних кадров больше `threshold` (шкала 0.0..1.0).
    `bins` есть только у hist. Порог каждого детектора в своей шкале и читается из config
    как есть: 0.1 у hist и 27 у content — не одна шкала, переводить нечем.

    min_scene_len передаётся без пересчёта: `0.6s` — таймкод, FrameTimecode меряет его по
    fps текущего видео (25 fps -> 15 кадров, 30 -> 18), число — кадры. EXE-бандл в yolo был
    нужен только потому, что локальная папка scenedetect/ маскировала имя пакета; в
    приложении пакет импортируется напрямую, отдельного процесса не нужно.
    """
    from scenedetect import AdaptiveDetector, ContentDetector, HashDetector
    from scenedetect import HistogramDetector, ThresholdDetector

    name = str(cfg["detector"]).strip().lower()
    threshold = float(cfg["threshold"])
    min_len = cfg["min_scene_len"]
    if name == "hist":
        return HistogramDetector(threshold=threshold, bins=int(cfg["bins"]),
                                 min_scene_len=min_len)
    if name == "content":
        return ContentDetector(threshold=threshold, min_scene_len=min_len)
    if name == "adaptive":
        return AdaptiveDetector(adaptive_threshold=threshold, min_scene_len=min_len)
    if name == "hash":
        return HashDetector(threshold=threshold, min_scene_len=min_len)
    if name == "threshold":
        return ThresholdDetector(threshold=threshold, min_scene_len=min_len)
    raise SystemExit(f"configs/scenes.yaml: detector {name!r} — нет из {', '.join(DETECTORS)}")


def detect_scenes(video: Path, cfg: dict) -> list[dict]:
    """PySceneDetect как библиотека: make_detector(cfg) -> список сцен.

    `detector: hist` = CLI `detect-hist --threshold 0.1 --bins 240` — эталон, на котором
    границы находят точно. `detect()` добавляет backend opencv, auto_downscale по
    разрешению и frame_skip 0 — те же условия, что у CLI, поэтому список сцен = список
    того CLI-прогона; `scenedetect.split-video` здесь не нужен, рез делаем ffmpeg.

    Границы сцены: `Scene.end` исключительный, поэтому End Frame (1-базный, inclusive)
    = end.get_frames(), Start Frame = start.get_frames() + 1, Length = end - start
    = End Frame - Start Frame + 1. Проверено по списку video_full/sexy.mp4: сцена 1 =
    кадры 1..78, сцена 2 = 79..1784.
    """
    from scenedetect import detect

    scenes = detect(str(video), make_detector(cfg))
    rows = []
    for i, sc in enumerate(scenes, 1):
        # scenedetect 0.7 даёт пару (start, end) FrameTimecode; Scene с атрибутами — 0.6
        start_tc, end_tc = sc if isinstance(sc, tuple) else (sc.start, sc.end)
        start_f = start_tc.get_frames()
        end_f = end_tc.get_frames()
        length = end_tc - start_tc
        rows.append({"Scene Number": i,
                     "Start Frame": start_f + 1,
                     "Start Timecode": start_tc.get_timecode(),
                     "Start Time (seconds)": f"{start_tc.get_seconds():.3f}",
                     "End Frame": end_f,
                     "End Timecode": end_tc.get_timecode(),
                     "End Time (seconds)": f"{end_tc.get_seconds():.3f}",
                     "Length (frames)": length.get_frames(),
                     "Length (timecode)": length.get_timecode(),
                     "Length (seconds)": f"{length.get_seconds():.3f}"})
    return rows


SCENE_LIST_COLUMNS = ("Scene Number", "Start Frame", "Start Timecode", "Start Time (seconds)",
                      "End Frame", "End Timecode", "End Time (seconds)", "Length (frames)",
                      "Length (timecode)", "Length (seconds)")


def run_detect(cfg: dict, video: Path, scenes_dir: Path, on_phase: "callable | None" = None) -> tuple[int, str]:
    """Детект + список сцен CSV в том же формате, что list-scenes --skip-cuts.

    Возвращает (код, хвост) как run_cli, чтобы process() не менялся: 0 = список записан.
    """
    try:
        rows = detect_scenes(video, cfg)
    except Exception as exc:            # один битый видеофайл не валит прогон
        return 1, f"{type(exc).__name__}: {exc}"[:260]
    csv_path = scenes_dir / list_of(video.stem, cfg)
    write_rows(csv_path, SCENE_LIST_COLUMNS, rows)
    if on_phase is not None:
        on_phase("detect")
    return 0, ""


def run_cli_progress(cmd: list[str], progress_file: Path,
                     on_seconds: "callable | None" = None) -> tuple[int, str]:
    """`run_cli` с `-progress <file>`: команда та же, ffmpeg дописывает out_time.

    Возвращает (код, хвост) как run_cli. Команда не меняется — добавляется только
    файл прогресса, поэтому процесс кодируется ровно как в прогоне yolo.
    """
    return run_ffmpeg_progress(cmd, progress_file, on_seconds)


def pick_vcodec(cfg: dict, scenes: int) -> tuple[str, str]:
    """Энкод реза для этого видео: NVENC только когда сцен не больше лимита сессий.

    GeForce обрывает параллельные NVENC-сессии по лимиту (замер 11 (2).mp4, 20 сцен в
    одном графе: "Error while opening encoder" на 13-м выходе). Один процесс ffmpeg режет
    N сцен = N сессий, поэтому vcodec=h264_nvenc применяется при N <= nvenc_max_outputs,
    а видео с большим числом сцен режется libx264. Причина возвращается строкой — она
    пишется в лог GUI.
    """
    codec = str(cfg["vcodec"])
    if codec != "h264_nvenc":
        return "libx264", ""
    limit = int(cfg["nvenc_max_outputs"])
    if scenes > limit:
        return "libx264", tr("nvenc_limit", scenes=scenes, limit=limit)
    return "h264_nvenc", ""


def build_graph(rows: list[dict], cfg: dict, fps: float, with_audio: bool) -> str:
    """Один граф на видео: split на N веток, trim по номерам кадров, по одному выходу.

    trim:end_frame исключительный, поэтому хвост = End Frame - 1 + tail + 1.
    Граф пишется в одну строку: перевод строки ffmpeg разбирает как «trailing garbage».
    atrim считает в секундах, start/end берём из кадров / fps.

    Нормализация клипа — здесь, один раз: `fps=target_fps` и `scale/pad/setsar` до
    target_width x target_height, и склейка читает клипы `-c copy` без перекодирования.
    Без этой строки клип выходит fps источника (23.976/25), и каждый прогон мерджа
    переэнкодил бы весь клип.
    """
    head = int(cfg["head_frames"])
    tail = int(cfg["tail_frames"])
    w, h = int(cfg["target_width"]), int(cfg["target_height"])
    target_fps = int(cfg["target_fps"])
    n = len(rows)
    parts = [f"[0:v]split={n}" + "".join(f"[v{i}]" for i in range(n))]
    for i, r in enumerate(rows):
        start0 = max(0, int(r["Start Frame"]) - 1 - head)
        end0 = int(r["End Frame"]) - 1 + tail
        conv = f",fps={target_fps}" if target_fps != fps else ""
        parts.append(f"[v{i}]trim=start_frame={start0}:end_frame={end0 + 1},"
                     f"setpts=PTS-STARTPTS{conv},"
                     f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                     f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1[vo{i}]")
    if with_audio:
        parts.append(f"[0:a]asplit={n}" + "".join(f"[a{i}]" for i in range(n)))
        for i, r in enumerate(rows):
            start0 = max(0, int(r["Start Frame"]) - 1 - head)
            end0 = int(r["End Frame"]) - 1 + tail
            parts.append(f"[a{i}]atrim=start={start0 / fps:.6f}:end={(end0 + 1) / fps:.6f},"
                         f"asetpts=PTS-STARTPTS[ao{i}]")
    return ";".join(parts)


def video_args(cfg: dict, codec: str) -> list[str]:
    """Флаги видеопотока клипа: одинаковые для всех выходов (concat copy их требует)."""
    if codec == "h264_nvenc":
        # NVENC (GPU): -crf, -keyint_min, -sc_threshold, -threads encoder не принимает.
        # Качество = -cq в vbr-режиме, gop только -g. Потоков на каждый выход GPU не
        # заводит, память процесса = буферы split, не энкодеров.
        return ["-c:v", "h264_nvenc", "-preset", str(cfg["nvenc_preset"]),
                "-rc", str(cfg["nvenc_rc"]), "-cq", str(cfg["nvenc_cq"]), "-b:v", "0",
                "-spatial-aq", "1", "-temporal-aq", "1",
                "-profile:v", cfg["profile"], "-pix_fmt", "yuv420p",
                "-g", str(cfg["gop"]), "-bf", str(cfg["bframes"]),
                "-video_track_timescale", str(cfg["timescale"])]
    # Потоки x264 берутся из конфига. Замер Project2.mp4 (1080p, crf 18, veryfast, 900
    # кадров): -threads 1 = 15.3 кадров/с, -threads 0 (авто) = 107.5 кадров/с, то есть
    # threads 1 стоил 7x скорости. Энкодеры внутри одного процесса идут ПОСЛЕДОВАТЕЛЬНО
    # (замер чанка 16 выходов с threads 0 = 12.2 fps — скорость одного энкодера), поэтому
    # параллельность дают процессы `jobs`, а не потоки внутри x264.
    return ["-c:v", "libx264", "-crf", str(cfg["crf"]), "-preset", cfg["preset"],
            "-threads", str(cfg["encoder_threads"]),
            "-profile:v", cfg["profile"], "-pix_fmt", "yuv420p",
            "-g", str(cfg["gop"]), "-keyint_min", str(cfg["gop"]),
            "-sc_threshold", "0", "-bf", str(cfg["bframes"]),
            "-video_track_timescale", str(cfg["timescale"])]


def audio_flags(cfg: dict) -> list[str]:
    """Флаги аудиопотока клипа: AAC 192k, 48000, stereo = формат склейки."""
    codec_a = cfg["audio_codec"]
    args = ["-c:a", codec_a, "-ar", str(cfg["audio_rate"]), "-ac", str(cfg["audio_channels"])]
    if codec_a == "aac":
        args += ["-b:a", cfg["audio_bitrate"]]
    return args


def out_block(cfg: dict, codec: str, with_audio: bool, scene: int, out: Path,
              dur: float) -> list[str]:
    """Блок одного выхода ffmpeg: -map, флаги кодирования, -t, путь.

    Ровно то, что добавляет `cut_cmd`, — длина блока решает, сколько сцен влазит в
    командную строку. `-t Length/fps` срезает хвост AAC-округления в этом же процессе:
    отдельный ffmpeg на каждый клип = 1623 процесса на 2h37m. `-shortest` не используем,
    он срезает ПОСЛЕДНИЙ КАДР.
    """
    block = ["-map", f"[vo{scene}]"] + video_args(cfg, codec)
    block += (["-map", f"[ao{scene}]"] + audio_flags(cfg)) if with_audio else ["-an"]
    block += ["-t", f"{dur:.6f}"]
    if cfg["faststart"]:
        block += ["-movflags", "+faststart"]
    block += [str(out)]
    return block


def chunk_limit(cfg: dict, codec: str, video: Path, out_dir: Path, stem: str,
                with_audio: bool, scenes: int) -> int:
    """Сцен в одном процессе ffmpeg: команда влазит в CreateProcess, энкодеров хватает памяти.

    Один выход ~205 символов: 1623 выходов = ~330 000 символов, `CreateProcess` даёт
    WinError 206, ffmpeg не стартует, файлов 0 (замер Project2.mp4, 2h37m). Память: x264
    1080p при threads 1 ~15 MB на энкодер, `max_outputs` выходов = ~240 MB; NVENC режется
    лимитом сессий GeForce.
    """
    scene = 10 ** len(str(scenes)) - 1            # худшее имя: s9999 -> самые длинные -map
    work = layout().work_dir
    head = [cfg["ffmpeg"], "-y", "-hide_banner", "-loglevel", "error", "-nostats",
            "-reinit_filter", "0", "-ss", "12345.678901", "-i", str(video),
            "-filter_complex_script", str(work / "scenes" / f"{stem}-c0000-graph.txt"),
            "-progress", str(work / "progress" / f"{stem}-c0000-cut.txt")]
    base = len(subprocess.list2cmdline(head))
    per = len(subprocess.list2cmdline(out_block(cfg, codec, with_audio, scene,
                                                out_dir / out_name(stem, scene, cfg),
                                                123.456789))) + 1
    by_chars = (CHUNK_CHAR_BUDGET - base) // per
    by_memory = int(cfg["max_outputs"])
    if codec == "h264_nvenc":
        by_memory = min(by_memory, int(cfg["nvenc_max_outputs"]))
    return max(1, min(by_chars, by_memory))


@dataclass
class Chunk:
    """Группа сцен одного процесса ffmpeg.

    `rows` — номера кадров относительно `-ss` (head/tail уже применены), `base_s` — секунды
    оригинала, где чанк начинается: полоса прогресса идёт по всему видео, не по чанку.
    `tag` — имя графа и файла прогресса.
    """
    first: int
    last: int
    seek_s: "float | None"
    base_frame: int
    base_s: float
    rows: list[dict]
    out_paths: list[Path]
    tag: str


def plan_chunks(cfg: dict, video: Path, rows: list[dict], out_dir: Path, fps: float,
                codec: str, with_audio: bool, start_time: float,
                keys: list[tuple[float, int]]) -> list[Chunk]:
    """Сцены -> чанки по `chunk_limit`; кадры чанка считаются от ключевого кадра `-ss`.

    Чанк читает только свой участок: `-ss` на ключевой кадр <= начала чанка, `-t` по концу
    чанка. Клип кодируется ОДИН РАЗ: чанки не склеиваются и не перекодируются, второй
    проход по клипу не появляется.
    """
    stem = video.stem
    head, tail = int(cfg["head_frames"]), int(cfg["tail_frames"])
    limit = chunk_limit(cfg, codec, video, out_dir, stem, with_audio, len(rows))
    chunks: list[Chunk] = []
    i = 0
    while i < len(rows):
        group = rows[i:i + min(limit, len(rows) - i)]
        start0 = max(0, int(group[0]["Start Frame"]) - 1 - head)
        # кадр N оригинала живёт в pts_time = start_time + N/fps: искать ключевой кадр по
        # pts, иначе `start_time` (у HEVC отрицательный) сдвигает базу за границу чанка
        seek, base = seek_point(keys, start_time + start0 / fps)
        local: list[dict] = []
        outs: list[Path] = []
        for r in group:
            # окно head/tail в кадрах чанка: -t и проверка кадров идут по ОКНУ, не по
            # Length сцены — при head_frames -2 клип на 2 кадра короче, и `-t` по Length
            # оставляет лишние кадры, а проверка кадров требует Length
            s0 = max(0, int(r["Start Frame"]) - 1 - head - base)
            e0 = int(r["End Frame"]) - 1 + tail - base
            span = max(1, e0 - s0 + 1)
            # head/tail уже в номерах кадров: build_graph их больше не применяет
            local.append({"Start Frame": s0 + 1, "End Frame": s0 + span,
                          "Length (frames)": span})
            outs.append(out_dir / out_name(stem, int(r["Scene Number"]), cfg))
        chunks.append(Chunk(i, i + len(group) - 1, seek, base, start0 / fps, local, outs,
                            f"{stem}-c{i:04d}"))
        i += len(group)
    return chunks


def check_chunk(cfg: dict, video: Path, chunk: Chunk, fps: float) -> list[str]:
    """Границы чанка на реальном кадре: первый кадр клипа = кадр оригинала на границе
    сцены, и число кадров = Length сцены после конверсии fps.

    `-ss` сажает процесс на ключевой кадр, номер которого = индекс его pts в порядке показа
    (`keyframe_index`); сверка средних пикселей ловит чанк, где база съехала и клип
    начинается кадраньше границы = хвостом прошлой сцены. Первый клип чанка — единственный,
    чей старт зависит от `-ss`, остальные клипы идут из того же декодирования, поэтому
    кадр границы меряется на первом клипе, а кадры — на краях чанка (ffprobe на каждый из
    1623 клипов = часы).
    """
    problems = []
    target_fps = int(cfg["target_fps"])
    edges = [(chunk.out_paths[0], chunk.rows[0]), (chunk.out_paths[-1], chunk.rows[-1])]
    for path, r in edges:
        if not path.is_file():
            problems.append(f"{path.name}: клипа нет")
            continue
        want = int(round(int(r["Length (frames)"]) * target_fps / fps))
        frames = probe_stream(cfg, path, "v:0").get("nb_frames", "")
        # допуск 2 кадра: VFR-файл живёт по своим pts, сегмент в `fps=target_fps`
        # даёт кадры по времени сегмента, а `Length / fps_probe` — по средней частоте
        if frames != str(want) and abs(int(frames or 0) - want) > 2:
            problems.append(f"{path.name}: {frames} кадров, должно быть {want} "
                            f"(при {target_fps} fps)")
    first, row0 = edges[0]
    if first.is_file():
        scene = chunk.first + 1                                 # Scene Number, 1-базный
        # кадр оригинала на границе = локальный номер кадра чанка от `-ss` базы:
        # `-ss` сам даёт только ключевой кадр, кадр границы выбирает trim внутри frame_avg
        src_index = int(row0["Start Frame"]) - 1
        src = frame_avg(cfg, video, chunk.seek_s, src_index)
        clip = frame_avg(cfg, first, None, 0)
        # переэнкод и нормализация клипа дают разницу в несколько единиц на канале
        if src is None or clip is None:
            problems.append(f"{first.name}: кадр сцены {scene} не измерен")
        elif sum((a - b) ** 2 for a, b in zip(src, clip)) ** 0.5 > 24.0:
            problems.append(f"{first.name}: первый кадр сцены {scene} не кадр границы "
                            f"оригинала {src} против {clip}")
    return problems


def cut_cmd(cfg: dict, video: Path, rows: list[dict], out_paths: list[Path],
            graph_file: Path, with_audio: bool, fps: float, codec: str,
            seek_s: "float | None" = None) -> list[str]:
    """Один процесс ffmpeg на чанк: N выходов из одного декодирования участка видео.

    `seek_s` — `-ss` перед `-i`: процесс читает файл от ключевого кадра, и номера кадров
    trim считаются от него (plan_chunks снимает базу). Граф локальный, head/tail уже
    применены plan_chunks и здесь не применяются второй раз.

    Аудио при audio:true режется atrim в секундах (границы от кадров / fps) и кодируется
    AAC — копия аудио при -ss тянет звук до конца файла. Флаги timestamp/ключа совпадают
    с форматом склейки, файл которого ScriptPlayer играет: gop = шаг ключевых кадров
    (дефолт x264 = 250, то есть 10 с при 25 fps, и плеер, который открывается по
    .funscript, стоит на чёрном до ближайшего ключевого; gop 60 = ключевик каждые 2.4 с);
    bframes 0 -> pts == dts, mp4-muxer не пишет edit list с задержкой pts-dts; timescale
    задаёт time_base; faststart = moov в начало файла.
    """
    graph_file.write_text(build_graph(rows, {**cfg, "head_frames": 0, "tail_frames": 0},
                                      fps, with_audio), encoding="utf-8")
    cmd = [cfg["ffmpeg"], "-y", "-hide_banner", "-loglevel", "error", "-nostats",
           "-reinit_filter", "0"]
    if seek_s is not None:
        cmd += ["-ss", f"{seek_s:.6f}"]
    cmd += ["-i", str(video), "-filter_complex_script", str(graph_file)]
    for i, (row, out) in enumerate(zip(rows, out_paths)):
        cmd += out_block(cfg, codec, with_audio, i, out,
                         int(row["Length (frames)"]) / fps)
    return cmd


def run_cut(cfg: dict, video: Path, chunk: Chunk, with_audio: bool, fps: float,
            codec: str, on_seconds: "callable | None" = None,
            token: "CancelToken | None" = None) -> tuple[int, str, str]:
    """Рез чанка одним процессом ffmpeg; прогресс по секундам энкода чанка.

    Возвращает (код, хвост, причина энкода): первый неудачный процесс даёт код и текст.
    `on_seconds(секунды чанка)` зовётся с числом секунд, закодированных в чанке —
    вызывающий добавляет базу чанка, и полоса идёт по реальным секундам всего видео.
    `token` — Cancel пользователя: ffmpeg регистрируется в токене и terminate'ится при
    нажатии, `Cancelled` выходит наружу.
    """
    # граф и файл прогресса живут в work/, не рядом с клипами: папка выходов
    # пользователя должна содержать только клипы
    work = layout().work_dir
    graph_file = work / "scenes" / f"{chunk.tag}-graph.txt"
    graph_file.parent.mkdir(parents=True, exist_ok=True)
    progress_file = work / "progress" / f"{chunk.tag}-cut.txt"
    seek = chunk.seek_s if chunk.base_frame else None
    cmd = cut_cmd(cfg, video, chunk.rows, chunk.out_paths, graph_file, with_audio, fps,
                  codec, seek)
    rc, text = run_ffmpeg_progress(cmd, progress_file, on_seconds, token)
    if rc != 0 and codec == "h264_nvenc" and "opening encoder" in text.lower():
        # GeForce снял сессию (драйвер, лимит, перегрев): тот же рез на x264
        rc, text = run_ffmpeg_progress(
            cut_cmd(cfg, video, chunk.rows, chunk.out_paths, graph_file, with_audio, fps,
                    "libx264", seek),
            progress_file, on_seconds, token)
        return rc, text, tr("nvenc_fail", text=text[:120])
    graph_file.unlink(missing_ok=True)
    return rc, text, ""


def plan_row(video: Path, cfg: dict, out_dir: Path, scenes_dir: Path) -> dict:
    stem = video.stem
    csv_path = scenes_dir / list_of(stem, cfg)
    row = dict(EMPTY_ROW, video=str(video), stem=stem, scene_list=str(csv_path),
               status=ST_PLAN)
    rows = scene_rows(csv_path)
    row["scenes"] = len(rows)
    out = produced(out_dir, stem)
    row["out_files"] = len(out)
    row["detect"] = "нет" if (csv_path.is_file() and csv_path.stat().st_mtime >= video.stat().st_mtime) else "да"
    sig_ok = (scenes_dir / f"{stem}-cut.sig").is_file() and \
        (scenes_dir / f"{stem}-cut.sig").read_text(encoding="utf-8").strip() == signature(cfg)
    row["cut"] = "нет" if (rows and len(out) == len(rows) and sig_ok) else (
        "да" if len(rows) >= int(cfg["min_scenes"]) else "нет")
    return row


def process(video: Path, cfg: dict, out_dir: Path, scenes_dir: Path, a: argparse.Namespace,
            on_phase: "callable | None" = None, on_cut: "callable | None" = None,
            token: "CancelToken | None" = None,
            chunk_jobs: "int | None" = None) -> dict:
    """Один видеофайл прогона: детект -> рез чанками -> проверки.

    `token` — Cancel пользователя: ffmpeg каждого чанка регистрируется в нём, и `Cancelled`
    выходит из `run_cut` наружу (этот видео больше не пишется).

    `chunk_jobs` — сколько чанков этого видео режется параллельно. Вызывающий делит бюджет
    `jobs` между видео (один длинный фильм = все чанки параллельно, пачка кликов = по одному
    процессу на видео), суммарных процессов ffmpeg получается не больше `jobs`.
    """
    stem = video.stem
    if token is not None:
        # прогон остановлен: этот видео не детектится и не режется
        token.check()
    csv_path = scenes_dir / list_of(stem, cfg)
    row = dict(EMPTY_ROW, video=str(video), stem=stem, scene_list=str(csv_path), status="")
    t0 = time.time()

    if a.cut_only:
        if not csv_path.is_file():
            row["status"] = ST_SKIP
            row["reason"] = "cut-only: списка сцен нет"
            return row
    elif a.force or not csv_path.is_file() or csv_path.stat().st_mtime < video.stat().st_mtime:
        # список older = видео заменено (то же имя, новый mtime): детект обязателен
        rc, tail = run_detect(cfg, video, scenes_dir, on_phase)
        row["detect_s"] = round(time.time() - t0, 2)
        if rc != 0:
            row["status"] = ST_ERROR
            row["reason"] = f"детект: {tail}"
            return row

    rows = scene_rows(csv_path)
    row["scenes"] = len(rows)
    if a.detect_only:
        row["status"] = ST_DETECT
        return row

    if len(rows) < int(cfg["min_scenes"]):
        row["status"] = ST_SINGLE
        row["out_files"] = 0
        row["reason"] = f"сцен {len(rows)} < min_scenes {cfg['min_scenes']}"
        return row

    out = produced(out_dir, stem)
    sig_path = scenes_dir / f"{stem}-cut.sig"
    sig = signature(cfg)
    sig_ok = sig_path.is_file() and sig_path.read_text(encoding="utf-8").strip() == sig
    if out and len(out) == len(rows) and sig_ok and not a.force:
        row["status"] = ST_SKIP
        row["out_files"] = len(out)
        row["out_mb"] = round(sum(p.stat().st_size for p in out) / 1e6, 1)
        row["reason"] = "сцены нарезаны, параметры реза те же"
        return row

    fps, pix_fmt = probe_video(cfg, video)
    if pix_fmt not in X264_FORMATS:
        row["status"] = ST_SKIP
        row["out_files"] = 0
        row["reason"] = f"pix_fmt {pix_fmt}: x264 умеет только 8-бит {', '.join(X264_FORMATS)}"
        return row

    out_paths = [out_dir / out_name(stem, int(r["Scene Number"]), cfg) for r in rows]
    with_audio = bool(cfg["audio"]) and has_audio(cfg, video)
    codec, codec_note = pick_vcodec(cfg, int(cfg["max_outputs"]))
    # один снимок ключевых кадров на видео: чанк ищет, на какой кадр сажать -ss
    start_time, pts = keyframe_map(cfg, video)
    chunks = plan_chunks(cfg, video, rows, out_dir, fps, codec, with_audio, start_time, pts)
    t1 = time.time()
    problems: list[str] = []
    # Полоса = сумма секунд, закодированных во ВСЕХ чанках. `-progress out_time` чанка =
    # время его ПОСЛЕДНЕГО выхода (замер чанка 0 Project2: 16 клипов, 135 с encoded,
    # out_time 3.4 с), сумму по нему не восстановить, поэтому каждый чанк сообщает своё
    # закодированное время, и складывается здесь. Чанки идут параллельно (`jobs` процессов
    # x264: замер 4 процесса = 126.8 кадров/с суммарно при 12.2 fps одного), полоса растёт
    # монотонно: число по чанку только увеличивается.
    jobs = chunk_jobs if chunk_jobs is not None else max(1, int(cfg["jobs"]))
    encoded = {ch.tag: 0.0 for ch in chunks}
    lock = threading.Lock()

    def report(tag: str, sec: float, span: float) -> None:
        if on_cut is None:
            return
        with lock:
            encoded[tag] = min(sec, span)
            on_cut(sum(encoded.values()))

    def run_one(ch: Chunk) -> tuple[Chunk, int, str, str]:
        span = sum(int(r["Length (frames)"]) for r in ch.rows) / fps
        rc, text, note = run_cut(cfg, video, ch, with_audio, fps, codec,
                                 lambda sec: report(ch.tag, sec, span), token)
        if rc == 0:
            report(ch.tag, span, span)          # чанк готов: весь его участок закодирован
        return ch, rc, text, note

    if jobs == 1:
        results = [run_one(ch) for ch in chunks]
    else:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            results = list(pool.map(run_one, chunks))
    for ch, rc, text, note in results:
        if note:
            codec_note = note
        if rc != 0:
            problems.append(tr("cut_chunk_fail", tag=ch.tag, text=text[:120]))
            break
    row["cut_s"] = round(time.time() - t1, 2)
    out = produced(out_dir, stem)
    row["out_files"] = len(out)
    row["out_mb"] = round(sum(p.stat().st_size for p in out) / 1e6, 1)
    if problems:
        row["status"] = ST_ERROR
        row["reason"] = "; ".join(problems)[:250]
    elif len(out) != len(rows):
        # число выходов сверяется со списком: молчаливый пропуск сцены виден в отчёте
        row["status"] = ST_ERROR
        row["reason"] = f"файлов {len(out)}, сцен {len(rows)}"
    elif len(out_paths) != len(set(out_paths)):
        row["status"] = ST_ERROR
        row["reason"] = "имена клипов повторяются"
    else:
        row["status"] = ST_CUT
        if not a.no_check:
            stats, check_problems = check_clips(cfg, out_paths, int(cfg["target_fps"]))
            problems += check_problems
            for ch in chunks:
                problems += check_chunk(cfg, video, ch, fps)
            row["kf_max_gap"] = stats["kf_max_gap"]
            row["min_dts"] = stats["min_dts"]
            row["moov_first"] = str(stats["moov_first"])
        if problems:
            row["status"] = ST_ERROR
            row["reason"] = "; ".join(problems)[:250]
        else:
            # сигнатура пишется только после успешного реза: следующий прогон с теми же
            # параметрами пропускает рез, сменились параметры -> переэнкод
            sig_path.write_text(sig, encoding="utf-8")
            # какой энкод реально работал (NVENC / libx264) — в лог GUI
            row["reason"] = codec_note
    return row


def write_rows(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # mode="w": Path.open() по умолчанию чтение, и без него запись падает FileNotFoundError
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cfg", default=None)
    p.add_argument("--root", default=None, help="перекрыть configs/scenes.yaml:source_dir")
    p.add_argument("--pattern", default=None, help="шаблон имён, по умолчанию *.mp4")
    p.add_argument("--out", default=None, help="перекрыть configs/scenes.yaml:out_dir")
    p.add_argument("--jobs", type=int, default=0, help="параллельных процессов ffmpeg")
    p.add_argument("--limit", type=int, default=0, help="обработать не больше N видео")
    p.add_argument("--filter", default="", help="пропускать пути, не содержащие подстроку")
    p.add_argument("--dry", action="store_true", help="план, ничего не писать")
    p.add_argument("--force", action="store_true", help="детект и рез поверх существующего")
    p.add_argument("--detect-only", dest="detect_only", action="store_true",
                   help="только списки сцен, без реза")
    p.add_argument("--cut-only", dest="cut_only", action="store_true",
                   help="рез из готовых списков, без детекта")
    p.add_argument("--no-check", dest="no_check", action="store_true",
                   help="не мерить первый и последний клип по критериям эталона")
    a = p.parse_args()

    cfg = load_config(Path(a.cfg) if a.cfg else None)
    for tool in (cfg["ffmpeg"], cfg["ffprobe"]):
        if not Path(tool).is_file():
            import shutil
            if shutil.which(tool) is None:
                raise SystemExit(f"{tool} не найден: нужен ffmpeg (D:\\ffmpeg\\bin в PATH)")

    root = Path(a.root) if a.root else ROOT / cfg["source_dir"]
    pattern = a.pattern or cfg["pattern"]
    out_dir = Path(a.out) if a.out else ROOT / cfg["out_dir"]
    scenes_dir = ROOT / cfg["scenes_dir"]
    stats_dir = ROOT / cfg["stats_dir"]
    jobs = a.jobs or int(cfg["jobs"])

    videos = sorted(q for q in root.glob(pattern) if q.is_file())
    if a.filter:
        videos = [q for q in videos if a.filter in str(q)]
    if a.limit:
        videos = videos[:a.limit]
    if not videos:
        raise SystemExit(f"в {root} ({pattern}) видео не найдено")

    # выходы плоские: одинаковый stem двух видео даёт одну и ту же цель, и второй рез
    # затрёт первого. Коллизии находим до прогона
    by_stem: dict[str, list[Path]] = {}
    for v in videos:
        by_stem.setdefault(v.stem, []).append(v)
    dupes = {k: v for k, v in by_stem.items() if len(v) > 1}
    if dupes:
        raise SystemExit("имена видео дают коллизии в " + str(out_dir) + ": "
                         + "; ".join(f"{k} -> {[str(q) for q in v]}" for k, v in dupes.items()))

    # `bins` только у hist (гистограмма): печатать её для content — ввести в заблуждение
    det_part = f"detector {cfg['detector']}, threshold {cfg['threshold']}"
    if str(cfg["detector"]).strip().lower() == "hist":
        det_part += f", bins {cfg['bins']}"
    print(f"видео {len(videos)}, out {out_dir}, списки {scenes_dir}, "
          f"{det_part}, min_scene_len {cfg['min_scene_len']}, "
          f"min_scenes {cfg['min_scenes']}, crf {cfg['crf']}, preset {cfg['preset']}, "
          f"head {cfg['head_frames']}, tail {cfg['tail_frames']}, audio {cfg['audio']}, "
          f"jobs {jobs}")

    if a.dry:
        for v in videos:
            r = plan_row(v, cfg, out_dir, scenes_dir)
            print(f"  {v.name}: детект {r['detect']}, сцен {r['scenes']}, рез {r['cut']} "
                  f"(файлов {r['out_files']})")
        return

    scenes_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    t_start = time.time()
    # бюджет процессов делится между видео: один длинный фильм = параллельные чанки,
    # пачка кликов = по одному процессу на видео; суммарно не больше `jobs`
    chunk_jobs = max(1, jobs // min(jobs, len(videos)))
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futs = {pool.submit(process, v, cfg, out_dir, scenes_dir, a, None, None, None,
                            chunk_jobs): v for v in videos}
        done = 0
        for fut in as_completed(futs):
            v = futs[fut]
            try:
                row = fut.result()
            except Exception as exc:            # batch не падает на одном битом видео
                row = dict(EMPTY_ROW, video=str(v), stem=v.stem,
                           scene_list=str(scenes_dir / list_of(v.stem, cfg)),
                           status=ST_ERROR, reason=f"{type(exc).__name__}: {exc}")
            rows.append(row)
            done += 1
            print(f"[{done}/{len(videos)}] {v.name}: {row['status']} сцен {row['scenes']} "
                  f"файлов {row['out_files']} детект {row['detect_s']} с рез {row['cut_s']} с"
                  + (f" {row['reason']}" if row["reason"] else ""), flush=True)

    rows.sort(key=lambda r: r["video"])
    stats_path = stats_dir / "stats.csv"
    write_rows(stats_path, STATS_COLUMNS, rows)

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log = scenes_dir / "run.log"
    with log.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(f"{stamp} {row['status']} {row['video']} сцен {row['scenes']} "
                     f"файлов {row['out_files']} {row['out_mb']} MB "
                     f"детект {row['detect_s']} с рез {row['cut_s']} с {row['reason']}\n")

    d = time.time() - t_start
    cut = sum(1 for r in rows if r["status"] == ST_CUT)
    single = sum(1 for r in rows if r["status"] == ST_SINGLE)
    skipped = sum(1 for r in rows if r["status"] == ST_SKIP)
    detect = sum(1 for r in rows if r["status"] == ST_DETECT)
    errors = sum(1 for r in rows if r["status"] == ST_ERROR)
    files = sum(int(r["out_files"]) for r in rows if str(r["out_files"]).isdigit())
    print(f"\nвидео {len(rows)}: нарезано {cut}, одна сцена {single}, пропущено {skipped}, "
          f"списков {detect}, ошибок {errors}, файлов {files}, времени {d:.0f} с")
    print(f"отчёт: {stats_path}")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
