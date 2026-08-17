"""メイン画面に常設する構造入力パネル。

起動時からKetcherを読み込んで常時表示する。「分子量を計算」ボタンで
描いた構造式の化学式・分子量をその場で確認でき(「試薬に追加」を押す
前でも見える)、「試薬に追加」ボタンで計算テーブルへ反映できる。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core import compound_source
from . import theme
from .structure_editor import KetcherNotBundledError, KetcherView


class StructureInputPanel(QFrame):
    """構造式入力パネル。「試薬に追加」で解決済みの `CompoundInfo` を通知する。"""

    added_to_table = Signal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(theme.card_frame_style("StructureInputPanel"))
        self._ketcher: KetcherView | None = None

        title_label = QLabel("構造入力")
        title_label.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {theme.TEXT_PRIMARY};")

        self._ketcher_container = QVBoxLayout()
        self._ketcher_container.setContentsMargins(0, 0, 0, 0)
        try:
            self._ketcher = KetcherView(self)
            self._ketcher.setMinimumHeight(360)
            self._ketcher_container.addWidget(self._ketcher)
        except KetcherNotBundledError as exc:
            self._ketcher_container.addWidget(QLabel(str(exc)))

        info_row = QHBoxLayout()
        self._formula_label = QLabel("化学式: —")
        self._mw_label = QLabel("分子量: —")
        info_row.addWidget(self._formula_label)
        info_row.addWidget(self._mw_label)
        info_row.addStretch()

        self._calc_button = QPushButton("分子量を計算")
        self._calc_button.clicked.connect(self._on_calculate)

        self._add_button = QPushButton("試薬に追加")
        self._add_button.setStyleSheet(theme.accent_button_style())
        self._add_button.clicked.connect(self._on_add_to_table)

        button_row = QHBoxLayout()
        button_row.addWidget(self._calc_button)
        button_row.addWidget(self._add_button)

        self._error_label = QLabel("")
        self._error_label.setStyleSheet(f"color: {theme.DANGER_TEXT};")
        self._error_label.hide()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(title_label)
        outer.addLayout(self._ketcher_container, 1)
        outer.addLayout(info_row)
        outer.addWidget(self._error_label)
        outer.addLayout(button_row)

    def _on_calculate(self) -> None:
        if self._ketcher is None:
            self._show_error("構造式エディタが利用できません。")
            return
        self._error_label.hide()
        self._ketcher.get_smiles(self._on_smiles_for_calculate)

    def _on_smiles_for_calculate(self, smiles: str | None) -> None:
        info = self._resolve_smiles(smiles)
        if info is not None:
            self._update_info_labels(info)

    def _on_add_to_table(self) -> None:
        if self._ketcher is None:
            self._show_error("構造式エディタが利用できません。")
            return
        self._error_label.hide()
        self._ketcher.get_smiles(self._on_smiles_for_add)

    def _on_smiles_for_add(self, smiles: str | None) -> None:
        info = self._resolve_smiles(smiles)
        if info is not None:
            self._update_info_labels(info)
            self.added_to_table.emit(info)

    def _resolve_smiles(self, smiles: str | None):
        if not smiles:
            self._show_error("構造式が空です。原子を配置してください。")
            return None
        try:
            return compound_source.resolve_from_smiles(smiles)
        except ValueError as exc:
            self._show_error(str(exc))
            return None

    def _update_info_labels(self, info) -> None:
        self._formula_label.setText(f"化学式: {info.formula or '—'}")
        self._mw_label.setText(f"分子量: {info.molecular_weight:.4g}")

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.show()

    def shutdown(self) -> None:
        """メインウィンドウを閉じる際に呼び、Ketcherのローカルサーバーを止める。"""
        if self._ketcher is not None:
            self._ketcher.shutdown()
