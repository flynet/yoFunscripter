"""Window screenshots: the window is rendered offscreen and saved as PNG.

    python tools/make_screenshots.py

The window is built by the same code the app runs, so the screenshots cannot drift away
from the real UI: the same cards, the same progress panel, the same settings page. The
folders and the progress numbers are example values, so the screenshot shows a run in
progress, not an empty window. The PNGs are for local viewing and are not tracked in git.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from PySide6.QtWidgets import QApplication

from yofunscripter.config.settings import Settings
from yofunscripter.i18n import set_language, tr
from yofunscripter.pipeline.funscript_select import SORT_TICK_RATE
from yofunscripter.ui.main_window import MainWindow
from yofunscripter.ui.theme import apply_theme


def fill(win: MainWindow, values: dict[str, list[str]]) -> None:
    for name, texts in values.items():
        card = getattr(win, name)
        for row, text in zip(card.rows, texts):
            row.edit.setText(text)


def shot(win: MainWindow, out: Path) -> None:
    win.resize(1000, 760)
    win.show()
    app = QApplication.instance()
    app.processEvents()
    pix = win.grab()
    pix.save(str(out))
    win.close()
    print(f"{out} {pix.width()}x{pix.height()}")


def main() -> None:
    out_dir = REPO / "assets" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication([])

    s = Settings()
    apply_theme(app, s.theme)
    set_language("en")
    win = MainWindow(s)
    fill(win, {
        "scenes_card": ["D:/videos", "D:/videos/scenes"],
        "scripts_card": ["D:/videos/scenes", "D:/videos/scripts"],
        "merge_card": ["D:/videos/scenes", "D:/videos/scripts", "D:/videos/result"],
    })
    win.progress.start("Cut scenes", "unit_seconds")
    win.progress.update(7200, 12000)
    for line in (tr("stage1_video", done=1, total=40, name="sexy-01.mp4",
                    status=tr("status_cut"), scenes=5, files=5, detect="4.2",
                    cut="11.9", reason=""),
                  tr("stage1_video", done=2, total=40, name="sexy-02.mp4",
                     status=tr("status_single"), scenes=1, files=0, detect="3.1",
                     cut="", reason=""),
                  tr("stage1_video", done=3, total=40, name="sexy-03.mp4",
                     status=tr("status_cut"), scenes=9, files=9, detect="6.0",
                     cut="18.4", reason="")):
        win.log(line)
    shot(win, out_dir / "main-en.png")

    s2 = Settings()
    s2.language = "ru"
    s2.theme = "cartoons"
    apply_theme(app, s2.theme)
    set_language("ru")
    win2 = MainWindow(s2)
    win2.tabs.setCurrentIndex(1)
    shot(win2, out_dir / "settings-ru.png")


if __name__ == "__main__":
    main()
