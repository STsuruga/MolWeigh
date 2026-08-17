"""化合物検索バー。名称/CAS/化学式/SMILES共通の入力欄から `compound_source` を呼び出す。

ライブラリ・PubChemのいずれにもヒットしない場合は、モーダルダイアログで
化学式またはSMILESの明示入力にフォールバックする(仕様書§4の3・4の経路)。
"""

from __future__ import annotations

import sqlite3

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtCore import QTimer, Signal

from ..core import compound_source
from ..core.compound_source import CompoundInfo
from ..core.pubchem_client import PubChemError
from . import theme
from .structure_editor import KetcherNotBundledError, StructureEditorDialog


class CompoundSearchBar(QWidget):
    """検索入力欄+照合ボタン。解決できた `CompoundInfo` を `compound_resolved` で通知する。"""

    compound_resolved = Signal(object)

    def __init__(self, conn: sqlite3.Connection, parent: QWidget | None = None):
        super().__init__(parent)
        self._conn = conn

        self._input = QLineEdit()
        self._input.setPlaceholderText("試薬名 / CAS / 化学式 / SMILES を入力")
        self._input.returnPressed.connect(self._on_search)

        self._button = QPushButton("照合")
        self._button.setStyleSheet(theme.accent_button_style())
        self._button.clicked.connect(self._on_search)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._input)
        layout.addWidget(self._button)

    def _on_search(self) -> None:
        query = self._input.text().strip()
        if not query:
            return
        try:
            info = compound_source.resolve_compound(self._conn, query)
        except PubChemError as exc:
            QMessageBox.warning(self, "PubChemとの通信に失敗しました", str(exc))
            return

        if info is not None:
            self.compound_resolved.emit(info)
            self._input.clear()
            return

        self._open_manual_dialog(query)

    def _open_manual_dialog(self, query: str) -> None:
        dialog = ManualCompoundDialog(query, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_info is not None:
            self.compound_resolved.emit(dialog.result_info)
            self._input.clear()


class ManualCompoundDialog(QDialog):
    """ライブラリ・PubChemで解決できなかった化合物を、化学式またはSMILESで手動確定する。"""

    def __init__(self, query: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("化合物を手動入力")
        self.result_info: CompoundInfo | None = None

        self._mode = QComboBox()
        self._mode.addItems(["化学式で入力", "SMILESで入力"])

        self._input = QLineEdit(query)

        self._draw_button = QPushButton("構造式を描く…")
        self._draw_button.clicked.connect(self._on_draw_button_clicked)

        self._error_label = QLabel("")
        self._error_label.setStyleSheet(f"color: {theme.DANGER_TEXT};")
        self._error_label.hide()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        input_row = QHBoxLayout()
        input_row.addWidget(self._input)
        input_row.addWidget(self._draw_button)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"「{query}」はライブラリ・PubChemのいずれにも見つかりませんでした。"))
        layout.addWidget(self._mode)
        layout.addLayout(input_row)
        layout.addWidget(self._error_label)
        layout.addWidget(buttons)

        # デフォルトの入力手段は構造式を描くこと。ダイアログ表示直後に自動で開き、
        # ユーザーがキャンセルした場合のみ化学式/SMILESのテキスト入力にフォールバックする。
        QTimer.singleShot(0, self._auto_open_structure_editor)

    def _on_draw_button_clicked(self) -> None:
        self._open_structure_editor(warn_if_missing=True)

    def _auto_open_structure_editor(self) -> None:
        self._open_structure_editor(warn_if_missing=False)

    def _open_structure_editor(self, warn_if_missing: bool) -> None:
        try:
            editor = StructureEditorDialog(self)
        except KetcherNotBundledError as exc:
            if warn_if_missing:
                QMessageBox.warning(self, "構造式エディタを開けません", str(exc))
            return
        if editor.exec() == QDialog.DialogCode.Accepted and editor.smiles:
            self._mode.setCurrentIndex(1)
            self._input.setText(editor.smiles)

    def _on_accept(self) -> None:
        text = self._input.text().strip()
        if not text:
            self._show_error("値を入力してください")
            return
        try:
            if self._mode.currentIndex() == 0:
                self.result_info = compound_source.resolve_from_formula(text)
            else:
                self.result_info = compound_source.resolve_from_smiles(text)
        except ValueError as exc:
            self._show_error(str(exc))
            return
        self.accept()

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.show()
