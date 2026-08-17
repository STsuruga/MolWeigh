"""保存済みテンプレートをスクロール一覧で表示し、選択でテーブルへ呼び出せるパネル。"""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..db import template_repo
from ..db.template_repo import Template
from . import theme


class TemplateListPanel(QFrame):
    """テンプレート一覧をスクロール表示し、ダブルクリックで呼び出せるパネル。"""

    template_selected = Signal(object)

    def __init__(self, conn: sqlite3.Connection, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(theme.card_frame_style("TemplateListPanel"))
        self._conn = conn
        self._templates: list[Template] = []

        title_label = QLabel("テンプレート一覧")
        title_label.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {theme.TEXT_PRIMARY};")

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._empty_hint = QLabel("テンプレートを保存すると、ここから呼び出せます。")
        self._empty_hint.setWordWrap(True)
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")

        # 空状態のヒントとリストを同じ領域で切り替える(空の時に下に余白だけが
        # 残らないよう、ヒントは領域内で中央寄せにする)。
        self._stack = QStackedWidget()
        self._stack.addWidget(self._empty_hint)
        self._stack.addWidget(self._list)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)
        outer.addWidget(title_label)
        outer.addWidget(self._stack, 1)

        self.refresh()

    def refresh(self) -> None:
        self._templates = template_repo.list_all(self._conn)
        self._list.clear()
        for tmpl in self._templates:
            count = len(tmpl.payload.get("reagents", []))
            item = QListWidgetItem(f"{tmpl.name}  ({count}件)")
            item.setToolTip("ダブルクリックでテーブルに呼び出します。")
            self._list.addItem(item)
        has_entries = bool(self._templates)
        self._stack.setCurrentWidget(self._list if has_entries else self._empty_hint)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        row = self._list.row(item)
        if 0 <= row < len(self._templates):
            self.template_selected.emit(self._templates[row])
