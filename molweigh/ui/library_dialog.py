"""試薬ライブラリのカードグリッド(検索・選択・削除)と、それを包む独立ウィンドウ。

`LibraryGridWidget` がカードグリッド本体で、メイン画面への埋め込みと
`LibraryDialog`(独立ウィンドウ版)の両方から使う再利用可能な部品。
選択してもグリッドは閉じない(続けて複数の試薬をライブラリから追加できる
ようにするため)。各試薬は構造式画像付きのカードとして、複数列のグリッドで
表示する。
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
from . import theme

_CARD_COLUMNS = 3
_STRUCTURE_IMAGE_SIZE = (168, 128)


class LibraryGridWidget(QWidget):
    """検索欄+試薬カードグリッド本体。"""

    entry_selected = Signal(object)
    add_new_requested = Signal()

    def __init__(self, conn: sqlite3.Connection, parent: QWidget | None = None):
        super().__init__(parent)
        self._conn = conn

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("試薬名 / CAS / 化学式で絞り込み")
        self._search_input.textChanged.connect(self.refresh)

        self._grid_container = QWidget()
        self._grid = QGridLayout(self._grid_container)
        self._grid.setSpacing(16)
        self._grid.setContentsMargins(4, 4, 4, 4)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setWidget(self._grid_container)

        self._add_new_button = QPushButton("+ 新しい化合物を登録")
        self._add_new_button.clicked.connect(self.add_new_requested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._search_input)
        layout.addWidget(scroll_area, 1)
        layout.addWidget(self._add_new_button)

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


class LibraryDialog(QDialog):
    """`LibraryGridWidget` を包む独立ウィンドウ版(非モーダル)。"""

    def __init__(self, conn: sqlite3.Connection, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("試薬ライブラリ")
        self.resize(780, 620)

        self._grid_widget = LibraryGridWidget(conn, self)
        self.entry_selected = self._grid_widget.entry_selected
        self.add_new_requested = self._grid_widget.add_new_requested

        close_button = QPushButton("閉じる")
        close_button.clicked.connect(self.close)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch()
        bottom_row.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)
        layout.addWidget(self._grid_widget, 1)
        layout.addLayout(bottom_row)

    def refresh(self) -> None:
        self._grid_widget.refresh()


class _LibraryCard(QFrame):
    """構造式・化合物名・化学式・CAS番号・分子量・比重を表示する1試薬分のカード。"""

    add_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(self, entry: LibraryEntry, parent: QWidget | None = None):
        super().__init__(parent)
        self._entry = entry
        self.setFixedWidth(216)
        self.setStyleSheet(theme.card_frame_style("_LibraryCard"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(10)

        self._image_label = QLabel()
        self._image_label.setFixedSize(*_STRUCTURE_IMAGE_SIZE)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet(
            f"background: {theme.ACCENT_BG}; border-radius: 10px; "
            f"color: {theme.TEXT_MUTED}; font-size: 12px;"
        )
        self._set_structure_image(entry)
        layout.addWidget(self._image_label)

        name_label = QLabel(entry.name)
        name_label.setStyleSheet(f"font-weight: 600; font-size: 14px; color: {theme.TEXT_PRIMARY};")
        name_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        info_frame = QFrame()
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(0, 4, 0, 4)
        info_layout.setSpacing(5)
        info_layout.addWidget(_info_row("化学式", entry.formula or "—"))
        info_layout.addWidget(_info_row("CAS No", entry.cas_number or "—"))
        info_layout.addWidget(_info_row("分子量", f"{entry.molecular_weight:.4g}"))
        info_layout.addWidget(
            _info_row("比重", f"{entry.density:.4g}" if entry.density is not None else "—")
        )
        layout.addWidget(info_frame)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self._add_button = QPushButton("追加")
        self._add_button.setStyleSheet(theme.accent_button_style())
        self._add_button.clicked.connect(lambda: self.add_requested.emit(self._entry))

        self._delete_button = QPushButton("削除")
        self._delete_button.setStyleSheet(theme.danger_ghost_button_style())
        self._delete_button.clicked.connect(lambda: self.delete_requested.emit(self._entry))

        button_row.addWidget(self._add_button, 1)
        button_row.addWidget(self._delete_button, 1)
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
    label_widget.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px;")
    value_widget = QLabel(value)
    value_widget.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12px; font-weight: 500;")
    row_layout.addWidget(label_widget)
    row_layout.addStretch()
    row_layout.addWidget(value_widget)
    return row
