"""選択中の試薬の構造式(大)・化学式・出典を表示するパネル。

`ReagentColumn` / `CompoundInfo` のいずれも `name` / `formula` / `smiles` /
`source` 属性を持つため、`show_compound` はダックタイピングでどちらも受け取れる。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ..core import structure
from . import theme

_SOURCE_LABELS = {
    "library": "出典: ライブラリ",
    "pubchem": "出典: PubChem",
    "formula_parser": "出典: 化学式入力",
    "smiles": "出典: SMILES入力",
}

_IMAGE_SIZE = (180, 160)


class StructurePanel(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedWidth(216)
        self.setStyleSheet(theme.card_frame_style("StructurePanel"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title_label = QLabel("選択中の試薬")
        title_label.setStyleSheet(f"font-size: 11px; color: {theme.TEXT_MUTED};")
        layout.addWidget(title_label)

        self._image_label = QLabel()
        self._image_label.setFixedSize(*_IMAGE_SIZE)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet(
            f"background: {theme.ACCENT_BG}; border-radius: 10px; "
            f"color: {theme.TEXT_MUTED}; font-size: 12px;"
        )

        self._name_label = QLabel()
        self._name_label.setStyleSheet(f"font-weight: 600; font-size: 14px; color: {theme.TEXT_PRIMARY};")
        self._name_label.setWordWrap(True)

        self._formula_label = QLabel()
        self._formula_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px;")

        self._source_label = QLabel()
        self._source_label.setStyleSheet(f"font-size: 10px; color: {theme.TEXT_SECONDARY};")

        layout.addWidget(self._image_label)
        layout.addWidget(self._name_label)
        layout.addWidget(self._formula_label)
        layout.addWidget(self._source_label)
        layout.addStretch()

        self.clear()

    def clear(self) -> None:
        self._image_label.setPixmap(_blank_pixmap())
        self._image_label.setText("未選択")
        self._name_label.setText("")
        self._formula_label.setText("")
        self._source_label.setText("")

    def show_compound(self, column) -> None:
        self._name_label.setText(column.name or "")
        self._formula_label.setText(column.formula or "")
        self._source_label.setText(_SOURCE_LABELS.get(column.source, column.source or ""))

        smiles = getattr(column, "smiles", None)
        if smiles:
            try:
                pixmap = structure.render_structure_image(smiles, size=_IMAGE_SIZE)
                self._image_label.setPixmap(pixmap)
                self._image_label.setText("")
                return
            except ValueError:
                pass
        self._image_label.setPixmap(_blank_pixmap())
        self._image_label.setText("構造式なし")


def _blank_pixmap() -> QPixmap:
    pixmap = QPixmap(*_IMAGE_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap
