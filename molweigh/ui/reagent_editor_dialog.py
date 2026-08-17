"""化合物を新規にライブラリへ登録するダイアログ。

左にカードプレビュー、中央に構造入力(Ketcher)+化合物名・CAS・化学式・
分子量・比重の入力欄、右にPubChem埋め込み検索パネルを配置する
(ユーザー提供モックアップに準拠)。分子量は構造式/化学式から自動算出する
が、手入力で上書きもできる。
"""

from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import formula_parser, structure, structure_3d
from ..db import library_repo
from ..db.library_repo import LibraryEntry
from . import theme
from .library_dialog import _info_row
from .molecule_3d_web_viewer import Molecule3DNotBundledError, Molecule3DWebDialog
from .pubchem_browser_panel import PubChemBrowserPanel
from .structure_editor import KetcherNotBundledError, KetcherView

_STRUCTURE_IMAGE_SIZE = (168, 128)


class ReagentEditorDialog(QDialog):
    """新しい化合物をライブラリに登録するダイアログ。保存成功時に `library_id` を持つ。"""

    def __init__(self, conn: sqlite3.Connection, parent: QWidget | None = None):
        super().__init__(parent)
        self._conn = conn
        self.setWindowTitle("化合物を登録")
        self.resize(1400, 800)
        self.setMinimumSize(1200, 700)

        self.library_id: int | None = None
        self._smiles: str | None = None
        self._ketcher: KetcherView | None = None

        left_column = self._build_preview_column()
        middle_column = self._build_form_column()
        right_column = self._build_search_column()

        columns_row = QHBoxLayout()
        columns_row.setSpacing(16)
        columns_row.addWidget(left_column)
        columns_row.addWidget(middle_column, 2)
        columns_row.addWidget(right_column, 1)

        save_button = QPushButton("保存")
        save_button.setStyleSheet(theme.accent_button_style())
        save_button.clicked.connect(self._on_save)
        cancel_button = QPushButton("キャンセル")
        cancel_button.clicked.connect(self.reject)

        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(save_button)
        button_row.addWidget(cancel_button)

        layout = QVBoxLayout(self)
        layout.addLayout(columns_row, 1)
        layout.addLayout(button_row)

        self._update_preview()

    # --- 左: プレビューカード -------------------------------------------------

    def _build_preview_column(self) -> QWidget:
        card = QFrame()
        card.setFixedWidth(216)
        card.setStyleSheet(theme.card_frame_style("_PreviewFrame"))

        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(10)

        self._preview_image = QLabel()
        self._preview_image.setFixedSize(*_STRUCTURE_IMAGE_SIZE)
        self._preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_image.setStyleSheet(
            f"background: {theme.ACCENT_BG}; border-radius: 10px; "
            f"color: {theme.TEXT_MUTED}; font-size: 12px;"
        )
        layout.addWidget(self._preview_image)

        self._preview_name = QLabel()
        self._preview_name.setStyleSheet(f"font-weight: 600; font-size: 14px; color: {theme.TEXT_PRIMARY};")
        self._preview_name.setWordWrap(True)
        layout.addWidget(self._preview_name)

        self._preview_formula_row = _info_row("化学式", "—")
        self._preview_cas_row = _info_row("CAS No", "—")
        self._preview_mw_row = _info_row("分子量", "—")
        self._preview_density_row = _info_row("比重", "—")
        for row in (
            self._preview_formula_row,
            self._preview_cas_row,
            self._preview_mw_row,
            self._preview_density_row,
        ):
            layout.addWidget(row)
        layout.addStretch()

        return card

    # --- 中央: 構造入力+情報入力欄 --------------------------------------------

    def _build_form_column(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._ketcher_container = QVBoxLayout()
        self._ketcher_container.setContentsMargins(0, 0, 0, 0)
        try:
            self._ketcher = KetcherView()
            self._ketcher.setMinimumHeight(320)
            self._ketcher_container.addWidget(self._ketcher)
        except KetcherNotBundledError as exc:
            self._ketcher_container.addWidget(QLabel(str(exc)))

        apply_structure_button = QPushButton("構造式を反映")
        apply_structure_button.clicked.connect(self._on_apply_structure)

        preview_3d_button = QPushButton("3Dプレビュー")
        preview_3d_button.setToolTip(
            "RDKitでエネルギー最小化した3D構造を表示します(2D構造には反映されません)"
        )
        preview_3d_button.clicked.connect(self._on_preview_3d)

        realign_button = QPushButton("橋かけ構造を整列")
        realign_button.setToolTip("トリプチセンのような橋かけ構造を、重なりにくい向きに描き直します")
        realign_button.clicked.connect(self._on_realign)

        structure_button_row = QHBoxLayout()
        structure_button_row.addWidget(apply_structure_button)
        structure_button_row.addWidget(preview_3d_button)
        structure_button_row.addWidget(realign_button)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("入力")
        self._name_input.textChanged.connect(self._update_preview)

        self._cas_input = QLineEdit()
        self._cas_input.setPlaceholderText("入力")
        self._cas_input.textChanged.connect(self._update_preview)

        self._formula_input = QLineEdit()
        self._formula_input.setPlaceholderText("入力(例: C6H12O6)")
        self._formula_input.editingFinished.connect(self._on_formula_edited)
        self._formula_input.textChanged.connect(self._update_preview)

        self._mw_input = QDoubleSpinBox()
        self._mw_input.setRange(0.0, 100000.0)
        self._mw_input.setDecimals(4)
        self._mw_input.valueChanged.connect(self._update_preview)

        self._density_input = QDoubleSpinBox()
        self._density_input.setRange(0.0, 100.0)
        self._density_input.setDecimals(3)
        self._density_input.setSpecialValueText("—")
        self._density_input.valueChanged.connect(self._update_preview)

        layout.addLayout(self._ketcher_container, 1)
        layout.addLayout(structure_button_row)
        layout.addWidget(_field_row("化合物名", self._name_input))
        layout.addWidget(_field_row("CAS No", self._cas_input))
        layout.addWidget(_field_row("化学式", self._formula_input))
        layout.addWidget(_field_row("分子量", self._mw_input))
        layout.addWidget(_field_row("比重", self._density_input))

        return container

    # --- 右: オンライン検索 ---------------------------------------------------

    def _build_search_column(self) -> QWidget:
        return PubChemBrowserPanel()

    # --- 構造式・化学式からの自動算出 ------------------------------------------

    def _on_apply_structure(self) -> None:
        if self._ketcher is None:
            QMessageBox.warning(self, "構造式を反映", "構造式エディタが利用できません。")
            return
        self._ketcher.get_smiles(self._on_smiles_received)

    def _on_preview_3d(self) -> None:
        if self._ketcher is None:
            QMessageBox.warning(self, "3Dプレビュー", "構造式エディタが利用できません。")
            return
        self._ketcher.get_smiles(self._on_smiles_for_3d)

    def _on_smiles_for_3d(self, smiles: str | None) -> None:
        if not smiles:
            QMessageBox.warning(self, "3Dプレビュー", "構造式が空です。原子を配置してください。")
            return
        try:
            molblock = structure_3d.generate_3d_molblock(smiles)
        except ValueError as exc:
            QMessageBox.warning(self, "3Dプレビュー", str(exc))
            return
        try:
            Molecule3DWebDialog(molblock, self).exec()
        except Molecule3DNotBundledError as exc:
            QMessageBox.warning(self, "3Dプレビュー", str(exc))

    def _on_realign(self) -> None:
        if self._ketcher is None:
            QMessageBox.warning(self, "橋かけ構造を整列", "構造式エディタが利用できません。")
            return
        self._ketcher.get_smiles(self._on_smiles_for_realign)

    def _on_smiles_for_realign(self, smiles: str | None) -> None:
        if not smiles:
            QMessageBox.warning(self, "橋かけ構造を整列", "構造式が空です。原子を配置してください。")
            return
        try:
            molblock = structure.realign_bridged_structure_molblock(smiles)
        except ValueError as exc:
            QMessageBox.warning(self, "橋かけ構造を整列", str(exc))
            return
        if molblock is None:
            QMessageBox.information(self, "橋かけ構造を整列", "橋かけ構造ではないため、整列は不要です。")
            return
        self._ketcher.set_smiles(molblock)

    def _on_smiles_received(self, smiles: str | None) -> None:
        if not smiles:
            QMessageBox.warning(self, "構造式を反映", "構造式が空です。原子を配置してください。")
            return
        try:
            info = structure.parse_smiles(smiles)
        except ValueError as exc:
            QMessageBox.warning(self, "構造式を反映", str(exc))
            return
        self._smiles = smiles
        self._formula_input.setText(info.formula or "")
        self._mw_input.setValue(round(info.molecular_weight, 4))
        self._update_preview()

    def _on_formula_edited(self) -> None:
        text = self._formula_input.text().strip()
        if not text:
            return
        try:
            mw = formula_parser.molecular_weight(text)
        except ValueError:
            return
        self._mw_input.setValue(round(mw, 4))

    # --- プレビュー更新 ---------------------------------------------------

    def _update_preview(self) -> None:
        name = self._name_input.text().strip() or "(未設定)"
        formula = self._formula_input.text().strip() or None
        cas = self._cas_input.text().strip() or None
        mw = self._mw_input.value()
        density = self._density_input.value()

        self._preview_name.setText(name)
        _set_info_row(self._preview_formula_row, formula or "—")
        _set_info_row(self._preview_cas_row, cas or "—")
        _set_info_row(self._preview_mw_row, f"{mw:.2f}" if mw > 0 else "—")
        _set_info_row(self._preview_density_row, f"{density:.4g}" if density > 0 else "—")

        if self._smiles:
            try:
                pixmap = structure.render_structure_image(self._smiles, size=_STRUCTURE_IMAGE_SIZE)
                self._preview_image.setPixmap(pixmap)
                self._preview_image.setText("")
                return
            except ValueError:
                pass
        self._preview_image.setPixmap(QPixmap())
        self._preview_image.setText("構造式なし")

    # --- 保存 ---------------------------------------------------------------

    def _on_save(self) -> None:
        name = self._name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "化合物を登録", "化合物名を入力してください。")
            return
        mw = self._mw_input.value()
        if mw <= 0:
            QMessageBox.warning(self, "化合物を登録", "分子量が未設定です。構造式または化学式を入力してください。")
            return

        entry = LibraryEntry(
            id=None,
            name=name,
            cas_number=self._cas_input.text().strip() or None,
            formula=self._formula_input.text().strip() or None,
            molecular_weight=mw,
            density=self._density_input.value() or None,
            smiles=self._smiles,
            source="manual",
        )
        self.library_id = library_repo.create(self._conn, entry)
        self.accept()

    def done(self, result: int) -> None:
        if self._ketcher is not None:
            self._ketcher.shutdown()
        super().done(result)


def _field_row(label: str, field_widget: QWidget) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    label_widget = QLabel(label)
    label_widget.setFixedWidth(70)
    layout.addWidget(label_widget)
    layout.addWidget(field_widget, 1)
    return row


def _set_info_row(row: QWidget, value: str) -> None:
    value_label = row.layout().itemAt(row.layout().count() - 1).widget()
    value_label.setText(value)
