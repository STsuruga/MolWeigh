"""保存済みテンプレートをスクロール一覧で表示し、選択でテーブルへ呼び出せるパネル。"""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

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
        self._empty_hint.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)
        outer.addWidget(title_label)
        outer.addWidget(self._empty_hint)
        outer.addWidget(self._list, 1)
        self._list.hide()

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
        self._list.setVisible(has_entries)
        self._empty_hint.setVisible(not has_entries)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        row = self._list.row(item)
        if 0 <= row < len(self._templates):
            self.template_selected.emit(self._templates[row])
