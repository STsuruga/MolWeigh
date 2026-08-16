"""メインウィンドウ。ツールバー(テンプレート)・検索バー・試薬テーブル・構造式パネルを統合する。"""

from __future__ import annotations

import sqlite3

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.compound_source import CompoundInfo
from ..db import library_repo, template_repo
from .compound_search import CompoundSearchBar
from .reagent_table import ReagentColumn, ReagentTableWidget
from .structure_panel import StructurePanel


class MainWindow(QMainWindow):
    def __init__(self, conn: sqlite3.Connection, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("MolWeigh")
        self._conn = conn

        self._search_bar = CompoundSearchBar(conn)
        self._search_bar.compound_resolved.connect(self._on_compound_resolved)

        self._reagent_table = ReagentTableWidget()
        self._reagent_table.column_selected.connect(self._on_column_selected)
        self._reagent_table.add_reagent_requested.connect(self._search_bar._input.setFocus)

        self._structure_panel = StructurePanel()

        self._template_combo = QComboBox()
        load_button = QPushButton("読込")
        load_button.clicked.connect(self._on_load_template)
        save_button = QPushButton("名前を付けて保存")
        save_button.clicked.connect(self._on_save_template)

        toolbar_layout = QHBoxLayout()
        toolbar_layout.addWidget(QLabel("当量計算"))
        toolbar_layout.addStretch()
        toolbar_layout.addWidget(self._template_combo)
        toolbar_layout.addWidget(load_button)
        toolbar_layout.addWidget(save_button)

        table_row = QHBoxLayout()
        table_row.addWidget(self._reagent_table, 1)
        table_row.addWidget(self._structure_panel)

        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.addLayout(toolbar_layout)
        main_layout.addWidget(self._search_bar)
        main_layout.addLayout(table_row)
        self.setCentralWidget(central)

        self._refresh_template_combo()

    def _on_compound_resolved(self, info: CompoundInfo) -> None:
        self._reagent_table.add_column(_compound_info_to_column(info))

    def _on_column_selected(self, index: int) -> None:
        columns = self._reagent_table.columns()
        if 0 <= index < len(columns):
            self._structure_panel.show_compound(columns[index])

    def _refresh_template_combo(self) -> None:
        self._template_combo.clear()
        self._template_combo.addItem("テンプレート: 未選択", None)
        for tmpl in template_repo.list_all(self._conn):
            self._template_combo.addItem(tmpl.name, tmpl.id)

    def _on_load_template(self) -> None:
        template_id = self._template_combo.currentData()
        if template_id is None:
            QMessageBox.information(self, "テンプレート読込", "テンプレートを選択してください。")
            return
        tmpl = template_repo.get(self._conn, template_id)
        if tmpl is None:
            QMessageBox.warning(self, "テンプレート読込", "テンプレートが見つかりません。")
            return

        self._reagent_table.clear()
        missing = 0
        for reagent in tmpl.payload.get("reagents", []):
            entry = library_repo.get(self._conn, reagent.get("library_id"))
            if entry is None:
                missing += 1
                continue
            column = ReagentColumn(
                name=entry.name,
                formula=entry.formula,
                smiles=entry.smiles,
                source=entry.source,
                library_id=entry.id,
                fw=entry.molecular_weight,
                density=entry.density,
            )
            if reagent.get("role") != "base":
                column.target_eq = reagent.get("eq")
            self._reagent_table.add_column(column)

        if missing:
            QMessageBox.information(
                self, "テンプレート読込", f"{missing}件の試薬はライブラリから見つかりませんでした。"
            )

    def _on_save_template(self) -> None:
        name, ok = QInputDialog.getText(self, "テンプレートを保存", "テンプレート名:")
        if not ok or not name.strip():
            return

        columns = self._reagent_table.columns()
        if not columns:
            QMessageBox.information(self, "テンプレート保存", "試薬が登録されていません。")
            return

        reagents = []
        skipped = 0
        for i, column in enumerate(columns):
            if column.library_id is None:
                skipped += 1
                continue
            reagents.append(
                {
                    "name": column.name,
                    "library_id": column.library_id,
                    "role": "base" if i == 0 else "additive",
                    "eq": 1.0 if i == 0 else (column.target_eq or 1.0),
                }
            )

        if not reagents:
            QMessageBox.warning(
                self, "テンプレート保存", "ライブラリ未保存の試薬のみのため保存できません。先に各試薬を保存してください。"
            )
            return

        template_repo.create(self._conn, name.strip(), {"reagents": reagents})
        if skipped:
            QMessageBox.information(
                self, "テンプレート保存", f"ライブラリ未保存の{skipped}件は含まれませんでした。"
            )
        self._refresh_template_combo()


def _compound_info_to_column(info: CompoundInfo) -> ReagentColumn:
    return ReagentColumn(
        name=info.name,
        formula=info.formula,
        smiles=info.smiles,
        source=info.source,
        library_id=info.library_id,
        fw=info.molecular_weight,
        density=info.density,
    )
