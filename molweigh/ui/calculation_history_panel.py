"""計算テーブルの状態を自動で記録し、一覧から呼び出せる履歴パネル。"""

from __future__ import annotations

import dataclasses
from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from . import theme
from .reagent_table import ReagentColumn

_MAX_ENTRIES = 30


@dataclasses.dataclass
class _HistoryEntry:
    timestamp: datetime
    columns: list[ReagentColumn]


class CalculationHistoryPanel(QFrame):
    """テーブルの変更を自動記録し、選択した時点の状態を再度テーブルへ反映できるパネル。"""

    restore_requested = Signal(list)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(theme.card_frame_style("CalculationHistoryPanel"))
        self._entries: list[_HistoryEntry] = []

        title_label = QLabel("計算履歴")
        title_label.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {theme.TEXT_PRIMARY};")

        self._list = QListWidget()
        self._list.setAlternatingRowColors(False)
        self._empty_hint = QLabel("試薬情報を入力すると、ここに変更履歴が記録されます。")
        self._empty_hint.setWordWrap(True)
        self._empty_hint.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)
        outer.addWidget(title_label)
        outer.addWidget(self._empty_hint)
        outer.addWidget(self._list, 1)
        self._list.hide()

    def record(self, columns: list[ReagentColumn]) -> None:
        """現在のテーブル状態を履歴に記録する。空欄のみ、または直前と同一の場合は記録しない。"""
        if not _has_content(columns):
            return
        snapshot = [dataclasses.replace(c) for c in columns]
        if self._entries and self._entries[0].columns == snapshot:
            return

        self._entries.insert(0, _HistoryEntry(timestamp=datetime.now(), columns=snapshot))
        del self._entries[_MAX_ENTRIES:]
        self._refresh_list()

    def _refresh_list(self) -> None:
        self._list.clear()
        for entry in self._entries:
            item = QListWidgetItem(_summarize(entry))
            item.setToolTip("ダブルクリックでこの時点の状態をテーブルに反映します。")
            self._list.addItem(item)
        has_entries = bool(self._entries)
        self._list.setVisible(has_entries)
        self._empty_hint.setVisible(not has_entries)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        row = self._list.row(item)
        if 0 <= row < len(self._entries):
            snapshot = [dataclasses.replace(c) for c in self._entries[row].columns]
            self.restore_requested.emit(snapshot)


def _has_content(columns: list[ReagentColumn]) -> bool:
    return any(c.name or c.fw is not None for c in columns)


def _summarize(entry: _HistoryEntry) -> str:
    base = entry.columns[0] if entry.columns else None
    base_label = (base.name if base and base.name else "(未設定)") if base else "(空)"
    count = len(entry.columns)
    suffix = f" 他{count - 1}件" if count > 1 else ""
    return f"{entry.timestamp:%H:%M:%S}  {base_label}{suffix}"
