"""メイン画面に常設する構造入力パネル。

起動時からKetcherを読み込んで常時表示する。「分子量を計算」ボタンで
描いた構造式の化学式・分子量をその場で確認でき(「試薬に追加」を押す
前でも見える)、「試薬に追加」ボタンで計算テーブルへ反映できる。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core import compound_source, structure
from . import theme
from .molecule_3d_web_viewer import Molecule3DNotBundledError, Molecule3DWebDialog
from .structure_editor import KetcherNotBundledError, KetcherView

_SIDE_COLUMN_WIDTH = 150
_INFO_FRAME_HEIGHT = 100
_ERROR_LABEL_HEIGHT = 48


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
            self._ketcher.setMinimumHeight(320)
            self._ketcher_container.addWidget(self._ketcher)
        except KetcherNotBundledError as exc:
            self._ketcher_container.addWidget(QLabel(str(exc)))

        info_frame = QFrame()
        info_frame.setFixedSize(_SIDE_COLUMN_WIDTH, _INFO_FRAME_HEIGHT)
        info_frame.setStyleSheet(
            f"QFrame {{ background: {theme.ACCENT_BG}; border-radius: {theme.RADIUS}px; }}"
        )
        self._formula_label = QLabel("化学式: —")
        self._formula_label.setWordWrap(True)
        self._formula_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mw_label = QLabel("分子量: —")
        self._mw_label.setWordWrap(True)
        self._mw_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mw_label.setStyleSheet(f"font-weight: 600; color: {theme.TEXT_PRIMARY};")
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(12, 12, 12, 12)
        info_layout.setSpacing(6)
        info_layout.addWidget(self._mw_label)
        info_layout.addWidget(self._formula_label)
        info_layout.addStretch(1)

        self._calc_button = QPushButton("分子量を計算")
        self._calc_button.setMaximumWidth(_SIDE_COLUMN_WIDTH)
        self._calc_button.clicked.connect(self._on_calculate)

        self._add_button = QPushButton("試薬に追加")
        self._add_button.setMaximumWidth(_SIDE_COLUMN_WIDTH)
        self._add_button.setStyleSheet(theme.accent_button_style())
        self._add_button.clicked.connect(self._on_add_to_table)

        self._preview_3d_button = QPushButton("3Dプレビュー")
        self._preview_3d_button.setMaximumWidth(_SIDE_COLUMN_WIDTH)
        self._preview_3d_button.setToolTip(
            "RDKitでエネルギー最小化した3D構造を表示します(2D構造には反映されません)"
        )
        self._preview_3d_button.clicked.connect(self._on_preview_3d)

        self._realign_button = QPushButton("橋かけ構造を整列")
        self._realign_button.setMaximumWidth(_SIDE_COLUMN_WIDTH)
        self._realign_button.setToolTip(
            "トリプチセンのような橋かけ構造を、重なりにくい向きに描き直します"
        )
        self._realign_button.clicked.connect(self._on_realign)

        # 固定サイズで常時レイアウトに存在させる(表示/非表示を切り替えると
        # エラーの有無でボタン位置がずれてしまうため、テキストの有無だけを切り替える)。
        self._error_label = QLabel("")
        self._error_label.setFixedSize(_SIDE_COLUMN_WIDTH, _ERROR_LABEL_HEIGHT)
        self._error_label.setWordWrap(True)
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._error_label.setStyleSheet(f"color: {theme.DANGER_TEXT};")

        side_column = QVBoxLayout()
        side_column.setSpacing(10)
        side_column.addWidget(info_frame)
        side_column.addWidget(self._error_label)
        side_column.addStretch(1)
        side_column.addWidget(self._calc_button)
        side_column.addWidget(self._preview_3d_button)
        side_column.addWidget(self._realign_button)
        side_column.addWidget(self._add_button)

        content_row = QHBoxLayout()
        content_row.setSpacing(16)
        content_row.addLayout(self._ketcher_container, 1)
        content_row.addLayout(side_column)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(title_label)
        outer.addLayout(content_row, 1)

    def _on_calculate(self) -> None:
        if self._ketcher is None:
            self._show_error("構造式エディタが利用できません。")
            return
        self._error_label.setText("")
        self._ketcher.get_smiles(self._on_smiles_for_calculate)

    def _on_smiles_for_calculate(self, smiles: str | None) -> None:
        info = self._resolve_smiles(smiles)
        if info is not None:
            self._update_info_labels(info)

    def _on_add_to_table(self) -> None:
        if self._ketcher is None:
            self._show_error("構造式エディタが利用できません。")
            return
        self._error_label.setText("")
        self._ketcher.get_smiles(self._on_smiles_for_add)

    def _on_smiles_for_add(self, smiles: str | None) -> None:
        info = self._resolve_smiles(smiles)
        if info is not None:
            self._update_info_labels(info)
            self.added_to_table.emit(info)

    def _on_preview_3d(self) -> None:
        if self._ketcher is None:
            self._show_error("構造式エディタが利用できません。")
            return
        self._error_label.setText("")
        self._ketcher.get_smiles(self._on_smiles_for_3d)

    def _on_smiles_for_3d(self, smiles: str | None) -> None:
        if not smiles:
            self._show_error("構造式が空です。原子を配置してください。")
            return
        try:
            molblock, view_data = structure.generate_3d_view(smiles)
        except ValueError as exc:
            self._show_error(str(exc))
            return
        try:
            dialog = Molecule3DWebDialog(molblock, view_data, smiles, self)
        except Molecule3DNotBundledError as exc:
            self._show_error(str(exc))
            return
        dialog.exec()
        if dialog.molblock_to_apply is not None and self._ketcher is not None:
            self._ketcher.set_smiles(dialog.molblock_to_apply)

    def _on_realign(self) -> None:
        if self._ketcher is None:
            self._show_error("構造式エディタが利用できません。")
            return
        self._error_label.setText("")
        self._ketcher.get_smiles(self._on_smiles_for_realign)

    def _on_smiles_for_realign(self, smiles: str | None) -> None:
        if not smiles:
            self._show_error("構造式が空です。原子を配置してください。")
            return
        try:
            molblock = structure.realign_bridged_structure_molblock(smiles)
        except ValueError as exc:
            self._show_error(str(exc))
            return
        if molblock is None:
            self._show_error("橋かけ構造ではないため、整列は不要です。")
            return
        self._ketcher.set_smiles(molblock)

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
        self._mw_label.setText(f"分子量: {info.molecular_weight:.2f}")

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)

    def shutdown(self) -> None:
        """メインウィンドウを閉じる際に呼び、Ketcherのローカルサーバーを止める。"""
        if self._ketcher is not None:
            self._ketcher.shutdown()
