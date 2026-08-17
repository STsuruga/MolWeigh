"""メイン画面に常設する、開閉式の構造入力パネル。

初期状態は折りたたみ。展開した時に初めてKetcherを読み込む(起動時から
常時読み込むと重いため)。描いた構造式から分子量・化学式を算出して表示し、
「試薬に追加」ボタンで計算テーブルへ反映できる。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core import compound_source
from . import theme
from .structure_editor import KetcherNotBundledError, KetcherView


class StructureInputPanel(QFrame):
    """開閉式の構造式入力パネル。「試薬に追加」で解決済みの `CompoundInfo` を通知する。"""

    added_to_table = Signal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(theme.card_frame_style("StructureInputPanel"))
        self._ketcher: KetcherView | None = None
        self._expanded = False

        self._toggle_button = QPushButton("▶ 構造入力")
        self._toggle_button.clicked.connect(self._on_toggle)

        self._body = QWidget()
        self._body.hide()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 8, 0, 0)

        self._ketcher_container = QVBoxLayout()
        self._ketcher_container.setContentsMargins(0, 0, 0, 0)

        info_row = QHBoxLayout()
        self._formula_label = QLabel("化学式: —")
        self._mw_label = QLabel("分子量: —")
        info_row.addWidget(self._formula_label)
        info_row.addWidget(self._mw_label)
        info_row.addStretch()

        self._add_button = QPushButton("試薬に追加")
        self._add_button.setStyleSheet(theme.accent_button_style())
        self._add_button.clicked.connect(self._on_add_to_table)

        self._error_label = QLabel("")
        self._error_label.setStyleSheet(f"color: {theme.DANGER_TEXT};")
        self._error_label.hide()

        body_layout.addLayout(self._ketcher_container)
        body_layout.addLayout(info_row)
        body_layout.addWidget(self._error_label)
        body_layout.addWidget(self._add_button)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(self._toggle_button)
        outer.addWidget(self._body)

    def _on_toggle(self) -> None:
        self._expanded = not self._expanded
        if self._expanded:
            self._body.show()
            self._toggle_button.setText("▼ 構造入力")
            if self._ketcher is None:
                self._create_ketcher()
        else:
            self._body.hide()
            self._toggle_button.setText("▶ 構造入力")

    def _create_ketcher(self) -> None:
        try:
            self._ketcher = KetcherView(self)
        except KetcherNotBundledError as exc:
            self._show_error(str(exc))
            return
        self._ketcher.setMinimumHeight(420)
        self._ketcher_container.addWidget(self._ketcher)

    def _on_add_to_table(self) -> None:
        if self._ketcher is None:
            self._show_error("構造式エディタが利用できません。")
            return
        self._error_label.hide()
        self._ketcher.get_smiles(self._on_smiles_for_add)

    def _on_smiles_for_add(self, smiles: str | None) -> None:
        if not smiles:
            self._show_error("構造式が空です。原子を配置してください。")
            return
        try:
            info = compound_source.resolve_from_smiles(smiles)
        except ValueError as exc:
            self._show_error(str(exc))
            return
        self._formula_label.setText(f"化学式: {info.formula or '—'}")
        self._mw_label.setText(f"分子量: {info.molecular_weight:.4g}")
        self.added_to_table.emit(info)

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.show()

    def shutdown(self) -> None:
        """メインウィンドウを閉じる際に呼び、Ketcherのローカルサーバーを止める。"""
        if self._ketcher is not None:
            self._ketcher.shutdown()
