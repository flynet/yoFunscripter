r"""Фикстуры реза сцен: известные границы, известные цвета, известные номера кадров.

    python tools/make_cut_fixture.py                       # tests/fixtures/
    python tools/make_cut_fixture.py --out work/test

Сцена = `frames` кадров одного цвета с номером сцены на каждом кадре; склейка ровно на
границе сцены, никаких вспышек между сценами: детектор находит ровно `scenes-1` склеек и
`scenes` сцен, как в реальном видео.

`cut-5scenes.mp4`       25 fps, 1280x720, libx264, 5 сцен по 50 кадров, gop 25.
`cut-5scenes-vfr.mp4`   23.976 fps, HEVC с B-кадрами, 5 сцен по 48 кадров, gop 24.
`cut-24chunks.mp4`      25 fps, 24 сцены по 30 кадров, gop 250: `max_outputs` 16 режет
                        фикстур ДВУМЯ чанками, второй чанк начинается `-ss` на ключевой
                        кадр в середине файла (кадр 250 = 10 с).
`cut-24chunks-vfr.mp4`  24 сцены, pts с джиттером 1.2 мс (`select` по источнику 1000 fps,
                        `fps_mode vfr`, HEVC с B-кадрами): шаг кадра ходит 40..43 мс, среднее
                        = 23.976 fps, база чанка `round(pts*fps)` округляет ключевой кадр на
                        1-2 кадра мимо = 1-2 кадра хвоста прошлой сцены.
`cut-24chunks-drift.mp4` 24 сцены, pts с пилой 1.2 мс (шаг = nominal + 1.2*(0.5 - (k mod 480)
                        /480)): к ключевому кадру второго чанка (кадр 250) pts набежало
                        +72 мс = 1.7 кадра, среднее за весь файл = 23.976 fps, и база чанка
                        `round(pts*fps)` = 252 против реального индекса 250: trim стартует
                        на 2 кадра РАНЬШЕ границы = 2 кадра прошлой сцены в начале клипа.
                        Это repro хвоста, на котором чинится база чанка (номер кадра ключа
                        = индекс его pts в списке pts всех пакетов, а не round(pts*fps)).

Цвета циклические (6 палитры), соседние сцены всегда разного цвета, номер сцены (`S01`..)
нарисован на каждом кадре. Хвост прошлой сцены в начале клипа = кадры цвета ПРОШЛОЙ сцены
с её номером: видно глазом и по среднему пикселю.

Нерегулярные pts делаются `select`-ом по источнику `color` c r=1000: `setpts` после `color`
работает в таймбейзе 1/fps, шаг кадра = 1 целая единица, и джиттер 0.4 мс в нём
округляется до нуля (`setpts=PTS+0.04*N` даёт те же 40 мс, замер). `select` берёт кадры с
номера 1000 fps, то есть pts со шagam 1 мс.

Рамки считаются фильтром `trim=end_frame=N`, а не длительностью `d=`: `d` в lavfi
округляется до кадра по своему расчётному времени.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "tests" / "fixtures"

W, H = 1280, 720
COLORS = ("red", "green", "blue", "yellow", "cyan", "magenta")
SRC_FPS = 1000                              #pts-шаг фикстура = 1 мс

# name, fps, кадров в сцене, сцен, энкод, gop, амплитуда пилы pts в мс (0 = CFR)
FIXTURES = (
    ("cut-5scenes", 25.0, 50, 5, "libx264", 25, 0.0),
    ("cut-5scenes-vfr", 23.976, 48, 5, "libx265", 24, 1.2),
    ("cut-24chunks", 25.0, 30, 24, "libx264", 250, 0.0),
    ("cut-24chunks-vfr", 23.976, 30, 24, "libx265", 240, 1.2),
    ("cut-24chunks-drift", 23.976, 30, 24, "libx265", 250, 1.2),
)


def scene_color(scene: int) -> str:
    """Цвет сцены: цикл палитры, соседние сцены всегда разного цвета."""
    return COLORS[(scene - 1) % len(COLORS)]


def label(text: str) -> str:
    """drawtext с номером сцены: крупно по центру, на белой подложке, читается на любом цвете."""
    font = "C:/Windows/Fonts/segoeui.ttf".replace(":", "\\:")
    return (f"drawtext=fontfile='{font}':text='{text}':fontsize=140:fontcolor=black:"
            f"box=1:boxcolor=white:boxborderw=20:x=(w-text_w)/2:y=(h-text_h)/2")


def pts_ms(fps: float, total: int, amp: float, period: int = 480) -> list[int]:
    """Номера кадров источника 1000 fps (= pts в мс): шаг = nominal - амплитуда пилы.

    Пила со знаком минус по циклу `period`: среднее шага = nominal, поэтому
    `avg_frame_rate` и fps проб = nominal, а локально pts ключевого кадра уходит от
    расчётного на `sum(пилы)` = база чанка `round(pts*fps)` считает номер кадра раньше,
    чем он есть. Шаг всегда > 0, pts монотонные.
    """
    step = 1000.0 / fps
    out, acc = [], 0
    for k in range(total):
        acc += step - amp * ((k % period) / period - 0.5)
        out.append(int(round(acc)))
    return out


def picks(idx: list[int]) -> str:
    """select по номерам кадров источника: запятые внутри eq экранируются, выражение в кавычках."""
    return "select='" + "+".join(f"eq(n\\,{i})" for i in idx) + "'"


def graph(fps: float, frames: int, scenes: int, amp: float) -> tuple[str, float]:
    """Сцены: `frames` кадров цвета с номером, и тишина на весь фикстур.

    Источник `color` c r=1000 (pts шаг 1 мс) при амплитуде, и r=fps при CFR: `fps_mode cfr`
    пишет частоту ИСТОЧНИКА, фикстур из источника 1000 fps probe-ится как 1000 fps.
    """
    rate = 1000.0 if amp else fps
    idx = pts_ms(fps, frames * scenes, amp) if amp else list(range(frames * scenes))
    parts = []
    labels = []
    for i in range(1, scenes + 1):
        tag = f"{i:02d}"
        sub = idx[(i - 1) * frames: i * frames]
        parts.append(f"color=c={scene_color(i)}:s={W}x{H}:r={rate},trim=end_frame="
                     f"{sub[-1] + 1},{picks(sub)},setpts=PTS-STARTPTS,{label(f'S{tag}')}[s{tag}]")
        labels.append(f"[s{tag}]")
    parts.append("".join(labels) + f"concat=n={scenes}:v=1:a=0[v]")
    total = idx[-1] / rate + 1.0 / rate
    parts.append(f"[0:a]atrim=end={total:.6f},asetpts=PTS-STARTPTS[a]")
    return ";".join(parts), total


def build(out: Path, name: str, fps: float, frames: int, scenes: int, codec: str,
          gop: int, amp: float) -> Path:
    """Один фикстур: lavfi-источники в filter_complex, единственный -i = тишина anullsrc."""
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{name}.mp4"
    graph_str, total = graph(fps, frames, scenes, amp)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
           "-filter_complex", graph_str,
           "-map", "[v]", "-map", "[a]", "-t", f"{total:.6f}"]
    if codec == "libx264":
        # ключевик каждые gop кадров, B-кадров нет: pts == dts, карта кадров простая
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0", "-bf", "0"]
    else:
        # HEVC с 2 B-кадрами: mp4 пишет edit list, dts первых пакетов отрицательный
        cmd += ["-c:v", "libx265", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
                "-x265-params", f"keyint={gop}:min-keyint={gop}:scenecut=0:bf=2", "-bf", "2"]
    cmd += ["-video_track_timescale", "30000", "-fps_mode", "vfr" if amp else "cfr",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(target)]
    run(cmd, name)
    return target


def sheet(target: Path, out: Path, frames: int, scenes: int) -> Path:
    """Лист кадров фикстура: последний кадр каждой сцены и первый кадр следующей, в ряд.

    Пара `кадр N-1 | кадр N` через каждую границу: при точном резе клип сцены N+1
    начинается с левого кадра правой пары.
    """
    picks_expr = "+".join(f"eq(n\\,{i * frames})+eq(n\\,{i * frames - 1})"
                          for i in range(1, scenes))
    png = out / f"{target.stem}-edges.png"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(target),
           "-vf", f"select='{picks_expr}',scale=240:135,tile={2 * (scenes - 1)}x1",
           "-frames:v", "1", "-pix_fmt", "rgb24", str(png)]
    run(cmd, target.stem)
    return png


def run(cmd: list[str], name: str) -> None:
    proc = subprocess.run(cmd, capture_output=True)
    text = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    if proc.returncode != 0:
        raise SystemExit(f"{name}: ffmpeg {proc.returncode} {text[-260:]}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=None, help="папка фикстур, по умолчанию tests/fixtures")
    p.add_argument("--no-sheet", dest="no_sheet", action="store_true",
                   help="не делать лист границ")
    a = p.parse_args()
    out = Path(a.out) if a.out else DEFAULT_OUT

    made = []
    for name, fps, frames, scenes, codec, gop, amp in FIXTURES:
        target = build(out, name, fps, frames, scenes, codec, gop, amp)
        made.append(target)
        rate = 1000.0 if amp else fps
        idx = pts_ms(fps, frames * scenes, amp) if amp else list(range(frames * scenes))
        steps = [round((b - a) / rate * 1000) for a, b in zip(idx, idx[1:])]
        key = min(gop, len(idx) - 1)
        print(f"{target}: {fps} fps, {scenes} сцен по {frames} кадров, gop {gop}, {codec}, "
              f"pts шаг {min(steps)}..{max(steps)} мс, кадр {key} pts {idx[key] / rate:.3f} с")
        if not a.no_sheet:
            made.append(sheet(target, out, frames, scenes))

    print("фикстуры:", ", ".join(str(q) for q in made))


if __name__ == "__main__":
    main()
