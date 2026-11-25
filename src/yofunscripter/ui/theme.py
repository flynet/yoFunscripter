"""Three color schemes of the window, taken from PyDownload.

The theme is applied as a QSS stylesheet and as the palette of the application, so the
widgets of the window follow the choice in the settings: a widget with no rule of its own
paints the palette, and the palette of Windows is not the theme.

Every color of a theme is a key, so one role is one color in the whole window: the accent
of the buttons, the wall of the console, the gradient of the progress bar. The three
schemes — «Cartoons», «Neon», «Pink» — are named by their style; Neon is the default of
the app, the bar of a running stage is the violet→cyan gradient of the theme.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from yofunscripter.config.settings import ThemeName, THEMES

CARTOONS = {
    "background": "#fff6e0",
    "panel": "#ffffff",
    "text": "#2d2a4a",
    "muted": "#6b6890",
    # «Cartoons» is bright, so the accent and the red go to the darker edge of the
    # family: the white letters of a button read on them.
    "accent": "#257de1",
    "accent_hover": "#3d95f0",
    "accent_pressed": "#1d6fd6",
    "border": "#2d2a4a",
    "success": "#4cd964",
    "error": "#e63e45",
    "warn": "#ffc93c",
    "warn_hover": "#ffd45c",
    "warn_pressed": "#e0a92e",
    "warn_text": "#2d2a4a",
    "console_bg": "#fffdf5",
    "console_text": "#2d2a4a",
    "chunk_start": "#ff8a3d",
    "chunk_end": "#ff8a3d",
    "done": "#4cd964",
}
NEON = {
    "background": "#0e0e1a",
    "panel": "#1a1a2e",
    "text": "#ededff",
    "muted": "#9a9ac0",
    "accent": "#8b5cf6",
    "accent_hover": "#9d70f8",
    "accent_pressed": "#7343d1",
    "border": "#2e2e4d",
    "success": "#a3e635",
    "error": "#e53252",
    "warn": "#fbbf24",
    "warn_hover": "#fcd34d",
    "warn_pressed": "#d9a413",
    "warn_text": "#1a1a2e",
    "console_bg": "#08080f",
    "console_text": "#cfcff5",
    # The bar of a running stage is the gradient of the theme: violet into cyan.
    "chunk_start": "#8b5cf6",
    "chunk_end": "#22d3ee",
    "done": "#a3e635",
}
PINK = {
    "background": "#fff0f6",
    "panel": "#ffffff",
    "text": "#4a2340",
    "muted": "#8a5c7e",
    # «Pink» is pastel, and pastel is bright: the accent goes to the deeper edge of the
    # family so the white letters of the buttons read.
    "accent": "#d7447e",
    "accent_hover": "#e5558b",
    "accent_pressed": "#b83364",
    "border": "#f8c8dc",
    "success": "#5ed3b0",
    "error": "#e04448",
    "warn": "#ffb86b",
    "warn_hover": "#ffc484",
    "warn_pressed": "#e79c50",
    "warn_text": "#4a2340",
    "console_bg": "#ffffff",
    "console_text": "#4a2340",
    "chunk_start": "#ff5fa2",
    "chunk_end": "#b794f6",
    "done": "#5ed3b0",
}
#: Theme value -> the colors of its palette, in the order of the settings combo.
PALETTES: dict[ThemeName, dict[str, str]] = {
    "neon": NEON,
    "cartoons": CARTOONS,
    "pink": PINK,
}
QSS_TEMPLATE = """
QMainWindow, QWidget#central, QDialog {{ background: {background}; }}
QPlainTextEdit#console {{
    background: {console_bg}; color: {console_text}; border: 1px solid {border};
    font-family: Consolas; font-size: 9pt;
}}
QFrame#card {{
    background: {panel}; border: 1px solid {border}; border-radius: 6px;
    padding: 8px;
}}
QLabel#cardTitle {{ color: {text}; font-size: 10pt; font-weight: bold; }}
QLabel#cardHint {{ color: {muted}; font-size: 9pt; }}
QLabel {{ color: {text}; }}
QLabel#pathValue {{ color: {muted}; font-size: 9pt; }}
QLabel#progressLabel {{ color: {text}; font-weight: bold; }}
QPushButton {{
    background: {accent}; color: #ffffff; border: 1px solid {border};
    border-radius: 4px; padding: 6px 12px;
}}
QPushButton:hover {{ background: {accent_hover}; }}
QPushButton:pressed {{ background: {accent_pressed}; }}
QPushButton:disabled {{ color: {muted}; background: {panel}; }}
QPushButton#browse {{
    background: {panel}; color: {text};
}}
QPushButton#browse:hover {{ background: {border}; }}
QPushButton#danger {{ background: {error}; }}
QCheckBox {{ color: {text}; }}
QGroupBox {{ color: {text}; border: 1px solid {border}; border-radius: 4px; }}
QProgressBar {{
    background: {panel}; border: 1px solid {border}; border-radius: 4px;
    text-align: center; color: {text};
}}
QProgressBar::chunk {{
    background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 {chunk_start}, stop: 1 {chunk_end});
}}
QStatusBar {{ background: {panel}; color: {text}; }}
QStatusBar QLabel {{ color: {text}; }}
QSpinBox, QComboBox, QLineEdit {{
    background: {background}; color: {text}; border: 1px solid {border};
    border-radius: 4px; padding: 3px;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background: {panel}; border-left: 1px solid {border};
}}
QComboBox QAbstractItemView {{
    background: {panel}; color: {text}; border: 1px solid {border};
    selection-background-color: {accent}; selection-color: #ffffff;
}}
QTabWidget::pane {{ border: 1px solid {border}; }}
QTabBar::tab {{
    background: {panel}; color: {text}; padding: 5px 12px;
    border: 1px solid {border}; border-bottom: none;
}}
QTabBar::tab:selected {{ background: {background}; color: {text}; }}
QScrollBar:vertical {{ background: {background}; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {border}; border-radius: 6px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {muted}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
"""


def qss_for(theme: ThemeName) -> str:
    """The stylesheet for the chosen theme."""
    return QSS_TEMPLATE.format(**PALETTES[theme])


def apply_palette(app: QApplication, theme: ThemeName) -> None:
    """Set the palette of the app to the colors of the theme.

    The QSS covers the widgets it names, but a widget with no rule of its own (the wall
    behind the cards, the box of a checkbox) paints the color of the palette. The palette
    Qt reads from Windows follows the system theme, so the palette of the app is set to
    the colors of the chosen theme: every widget takes the theme, whatever Windows says.
    """
    palette = app.style().standardPalette()
    colors = PALETTES[theme]
    window = QColor(colors["background"])
    panel = QColor(colors["panel"])
    text = QColor(colors["text"])
    accent = QColor(colors["accent"])
    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, panel)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, panel)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.ToolTipBase, panel)
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(colors["muted"]))
    palette.setColor(QPalette.ColorRole.Highlight, accent)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)


def color_for(theme: ThemeName, key: str) -> QColor:
    """Color of a theme key, used by the window for the state colors."""
    return QColor(PALETTES[theme][key])


def luminance(color: QColor) -> float:
    """The relative luminance of a color, the WCAG formula."""
    channels = []
    for value in (color.red(), color.green(), color.blue()):
        part = value / 255
        channels.append(part / 12.92 if part <= 0.03928 else ((part + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(a: QColor, b: QColor) -> float:
    """The WCAG contrast ratio of two colors: 1 is the same color, 21 is black on white."""
    first, second = luminance(a), luminance(b)
    high, low = max(first, second), min(first, second)
    return (high + 0.05) / (low + 0.05)


def theme_is_light(theme: ThemeName) -> bool:
    """Whether the wall of the theme is light (the text of the cards is dark)."""
    return luminance(QColor(PALETTES[theme]["background"])) > 0.5


def apply_theme(app: QApplication, theme: ThemeName) -> None:
    """Apply the stylesheet and the palette of the theme.

    The Fusion style is used for every theme: the Windows style paints parts of the
    widgets natively and ignores the stylesheet, which is what makes buttons of a dark
    theme look broken.
    """
    if app.style().objectName().lower() != "fusion":
        app.setStyle("Fusion")
    app.setStyleSheet(qss_for(theme))
    apply_palette(app, theme)


__all__ = ["CARTOONS", "NEON", "PALETTES", "PINK", "THEMES", "apply_palette",
           "apply_theme", "color_for", "contrast_ratio", "luminance", "qss_for",
           "theme_is_light"]
