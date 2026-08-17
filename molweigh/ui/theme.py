"""アプリ全体で共有する配色・スタイル定数。

個々のWidgetファイルは色を直接ハードコードせず、ここから import して使う。
`APP_STYLESHEET` は起動時に `QApplication.setStyleSheet()` で全体に適用し、
個別Widgetの `setStyleSheet()` はここでカバーしきれない特殊なケース
(構造式パネルの淡色背景、eqセルの状態別配色等)に限定する。
"""

from __future__ import annotations

BG = "#F4F3EF"
SURFACE = "#FFFFFF"
BORDER = "#E3E1D9"
BORDER_STRONG = "#C9C7BC"

TEXT_PRIMARY = "#2C2C2A"
TEXT_SECONDARY = "#5F5E5A"
TEXT_MUTED = "#8B8A82"

ACCENT = "#185FA5"
ACCENT_HOVER = "#14507F"
ACCENT_BG = "#E6F1FB"

SUCCESS_BG = "#E1F5EE"
SUCCESS_TEXT = "#0F6E56"

WARNING_TEXT = "#BA7517"

DANGER_BG = "#FBEAEA"
DANGER_TEXT = "#A32D2D"
DANGER_BORDER = "#EAC6C6"

BASE_BG = "#D3D1C7"

RADIUS = 8
CARD_RADIUS = 14

APP_STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {TEXT_PRIMARY};
    font-size: 13px;
}}

QMainWindow, QDialog {{
    background: {BG};
}}

QLabel {{
    background: transparent;
}}

QLineEdit, QComboBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    padding: 6px 10px;
    selection-background-color: {ACCENT_BG};
}}
QLineEdit:focus, QComboBox:focus {{
    border: 1px solid {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 18px;
}}

QPushButton {{
    background: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: {RADIUS}px;
    padding: 6px 14px;
}}
QPushButton:hover {{
    background: #EAE8E0;
}}
QPushButton:pressed {{
    background: #DFDDD3;
}}

QTableWidget {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    gridline-color: {BORDER};
    selection-background-color: {ACCENT_BG};
    selection-color: {TEXT_PRIMARY};
}}

QScrollArea {{
    border: none;
    background: transparent;
}}

QListWidget {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}

QMessageBox, QInputDialog {{
    background: {BG};
}}
"""


def accent_button_style() -> str:
    """強調ボタン(照合・追加など、その画面の主操作)向けスタイル。"""
    return f"""
        QPushButton {{
            background: {ACCENT};
            color: white;
            border: none;
            border-radius: {RADIUS}px;
            padding: 7px 16px;
            font-weight: 600;
        }}
        QPushButton:hover {{ background: {ACCENT_HOVER}; }}
        QPushButton:pressed {{ background: #0F3F5C; }}
    """


def danger_ghost_button_style() -> str:
    """削除など破壊的操作向けの控えめなスタイル(ホバー時のみ警告色)。"""
    return f"""
        QPushButton {{
            background: transparent;
            color: {TEXT_MUTED};
            border: 1px solid {BORDER};
            border-radius: {RADIUS}px;
            padding: 7px 0;
        }}
        QPushButton:hover {{
            background: {DANGER_BG};
            color: {DANGER_TEXT};
            border-color: {DANGER_BORDER};
        }}
    """


def card_frame_style(class_name: str) -> str:
    """カード状Widget共通の外枠(白背景・角丸・薄いボーダー)。"""
    return f"""
        {class_name} {{
            background: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: {CARD_RADIUS}px;
        }}
    """
