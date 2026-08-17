"""試薬ライブラリを閲覧・検索・選択・削除するウィンドウ。

メインウィンドウとは独立した非モーダルウィンドウとして開き、選択のたびに
`entry_selected` を発行して試薬列へ反映する。選択してもウィンドウは
閉じない(続けて複数の試薬をライブラリから追加できるようにするため)。
各試薬は構造式画像付きのカードとして、複数列のグリッドで表示する。
"""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core import structure
from ..db import library_repo
from ..db.library_repo import LibraryEntry

_CARD_COLUMNS = 3
_STRUCTURE_IMAGE_SIZE = (160, 120)


class LibraryDialog(QDialog):
    entry_selected = Signal(object)

    def __init__(self, conn: sqlite3.Connection, parent: QWidget | None = None):
        super().__init__(parent)
        self._conn = conn
        self.setWindowTitle("試薬ライブラリ")
        self.resize(760, 600)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("試薬名 / CAS / 化学式で絞り込み")
        self._search_input.textChanged.connect(self.refresh)

        self._grid_container = QWidget()
        self._grid = QGridLayout(self._grid_container)
        self._grid.setSpacing(12)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self._grid_container)

        close_button = QPushButton("閉じる")
        close_button.clicked.connect(self.close)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch()
        bottom_row.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._search_input)
        layout.addWidget(scroll_area, 1)
        layout.addLayout(bottom_row)

        self.refresh()

    def refresh(self) -> None:
        query = self._search_input.text().strip()
        if query:
            entries = library_repo.search(self._conn, query)
        else:
            entries = library_repo.list_all(self._conn, order_by_use_count=True)

        self._clear_grid()
        for i, entry in enumerate(entries):
            card = _LibraryCard(entry)
            card.add_requested.connect(self._on_add)
            card.delete_requested.connect(self._on_delete)
            row, col = divmod(i, _CARD_COLUMNS)
            self._grid.addWidget(card, row, col)

    def _clear_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _on_add(self, entry: LibraryEntry) -> None:
        library_repo.increment_use_count(self._conn, entry.id)
        self.entry_selected.emit(entry)

    def _on_delete(self, entry: LibraryEntry) -> None:
        confirm = QMessageBox.question(
            self,
            "ライブラリから削除",
            f"「{entry.name}」をライブラリから削除しますか?\n(すでに試薬テーブルに追加済みの列には影響しません)",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        library_repo.delete(self._conn, entry.id)
        self.refresh()


class _LibraryCard(QFrame):
    """構造式・化合物名・化学式・CAS番号・分子量・比重を表示する1試薬分のカード。"""

    add_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(self, entry: LibraryEntry, parent: QWidget | None = None):
        super().__init__(parent)
        self._entry = entry
        self.setFrameShape(QFrame.Shape.Box)
        self.setFixedWidth(210)
        self.setStyleSheet("_LibraryCard { border: 1px solid #0B3D4F; border-radius: 4px; }")

        layout = QVBoxLayout(self)

        self._image_label = QLabel()
        self._image_label.setFixedSize(*_STRUCTURE_IMAGE_SIZE)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet("border: 1px solid #888780;")
        self._set_structure_image(entry)
        layout.addWidget(self._image_label)

        name_label = QLabel(entry.name)
        name_label.setStyleSheet("font-weight: 600;")
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        layout.addWidget(_info_row("化学式", entry.formula or "—"))
        layout.addWidget(_info_row("CAS No", entry.cas_number or "—"))
        layout.addWidget(_info_row("分子量", f"{entry.molecular_weight:.4g}"))
        layout.addWidget(
            _info_row("比重", f"{entry.density:.4g}" if entry.density is not None else "—")
        )

        button_row = QHBoxLayout()
        self._add_button = QPushButton("追加")
        self._add_button.clicked.connect(lambda: self.add_requested.emit(self._entry))
        self._delete_button = QPushButton("削除")
        self._delete_button.clicked.connect(lambda: self.delete_requested.emit(self._entry))
        button_row.addWidget(self._add_button)
        button_row.addWidget(self._delete_button)
        layout.addLayout(button_row)

    def _set_structure_image(self, entry: LibraryEntry) -> None:
        if entry.smiles:
            try:
                pixmap = structure.render_structure_image(entry.smiles, size=_STRUCTURE_IMAGE_SIZE)
                self._image_label.setPixmap(pixmap)
                return
            except ValueError:
                pass
        self._image_label.setText("構造式なし")


def _info_row(label: str, value: str) -> QWidget:
    row = QWidget()
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    label_widget = QLabel(label)
    label_widget.setStyleSheet("color: #888780; font-size: 11px;")
    value_widget = QLabel(value)
    value_widget.setStyleSheet("font-size: 11px;")
    row_layout.addWidget(label_widget)
    row_layout.addStretch()
    row_layout.addWidget(value_widget)
    return row
