"""試薬ライブラリを閲覧・検索・選択・削除するウィンドウ。

メインウィンドウとは独立した非モーダルウィンドウとして開き、選択のたびに
`entry_selected` を発行して試薬列へ反映する。選択してもウィンドウは
閉じない(続けて複数の試薬をライブラリから追加できるようにするため)。
"""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..db import library_repo
from ..db.library_repo import LibraryEntry


class LibraryDialog(QDialog):
    entry_selected = Signal(object)

    def __init__(self, conn: sqlite3.Connection, parent: QWidget | None = None):
        super().__init__(parent)
        self._conn = conn
        self.setWindowTitle("試薬ライブラリ")
        self.resize(480, 520)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("試薬名 / CAS / 化学式で絞り込み")
        self._search_input.textChanged.connect(self.refresh)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _item: self._on_select())

        select_button = QPushButton("選択して追加")
        select_button.clicked.connect(self._on_select)
        delete_button = QPushButton("ライブラリから削除")
        delete_button.clicked.connect(self._on_delete)
        close_button = QPushButton("閉じる")
        close_button.clicked.connect(self.close)

        button_row = QHBoxLayout()
        button_row.addWidget(select_button)
        button_row.addWidget(delete_button)
        button_row.addStretch()
        button_row.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._search_input)
        layout.addWidget(self._list)
        layout.addLayout(button_row)

        self.refresh()

    def refresh(self) -> None:
        query = self._search_input.text().strip()
        if query:
            entries = library_repo.search(self._conn, query)
        else:
            entries = library_repo.list_all(self._conn, order_by_use_count=True)

        self._list.clear()
        for entry in entries:
            label = entry.name
            if entry.formula:
                label += f"  ({entry.formula})"
            label += f"  Fw={entry.molecular_weight:.4g}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self._list.addItem(item)

    def _selected_entry(self) -> LibraryEntry | None:
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _on_select(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        library_repo.increment_use_count(self._conn, entry.id)
        self.entry_selected.emit(entry)

    def _on_delete(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        confirm = QMessageBox.question(
            self,
            "ライブラリから削除",
            f"「{entry.name}」をライブラリから削除しますか?\n(すでに試薬テーブルに追加済みの列には影響しません)",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        library_repo.delete(self._conn, entry.id)
        self.refresh()
