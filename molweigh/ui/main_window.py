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

from ..core import compound_source
from ..core.compound_source import CompoundInfo
from ..db import library_repo, template_repo
from ..db.library_repo import LibraryEntry
from ..db.template_repo import Template
from . import theme
from .compound_search import CompoundSearchBar
from .library_dialog import LibraryGridWidget
from .pubchem_browser_panel import PubChemBrowserPanel
from .reagent_editor_dialog import ReagentEditorDialog
from .reagent_table import WEIGHT_UNITS, ReagentColumn, ReagentTableWidget
from .structure_input_panel import StructureInputPanel
from .structure_panel import StructurePanel
from .template_list_dialog import TemplateListDialog

DEFAULT_COLUMN_COUNT = 5


class MainWindow(QMainWindow):
    def __init__(self, conn: sqlite3.Connection, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("MolWeigh")
        self._conn = conn

        self._search_bar = CompoundSearchBar(conn)
        self._search_bar.compound_resolved.connect(self._on_compound_resolved)

        self._reagent_table = ReagentTableWidget()
        self._reagent_table.column_selected.connect(self._on_column_selected)
        self._reagent_table.add_reagent_requested.connect(self._on_add_reagent_requested)
        self._reagent_table.save_requested.connect(self._on_save_column_requested)
        for _ in range(DEFAULT_COLUMN_COUNT):
            self._reagent_table.add_column(ReagentColumn())

        self._structure_input_panel = StructureInputPanel()
        self._structure_input_panel.added_to_table.connect(self._on_compound_resolved)

        self._structure_panel = StructurePanel()

        self._library_grid = LibraryGridWidget(conn)
        self._library_grid.entry_selected.connect(self._on_library_entry_selected)
        self._library_grid.add_new_requested.connect(self._on_open_reagent_editor)

        self._pubchem_panel = PubChemBrowserPanel()

        self._template_list_dialog: TemplateListDialog | None = None

        add_template_button = QPushButton("テンプレートに追加")
        add_template_button.clicked.connect(self._on_save_template)
        load_template_button = QPushButton("テンプレートを呼び出し")
        load_template_button.clicked.connect(self._on_open_template_list)
        list_template_button = QPushButton("テンプレート一覧")
        list_template_button.clicked.connect(self._on_open_template_list)

        title_label = QLabel("当量計算")
        title_label.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {theme.TEXT_PRIMARY};")

        toolbar_layout = QHBoxLayout()
        toolbar_layout.addWidget(title_label)
        toolbar_layout.addStretch()
        toolbar_layout.addWidget(add_template_button)
        toolbar_layout.addWidget(load_template_button)
        toolbar_layout.addWidget(list_template_button)

        self._weight_unit_combo = QComboBox()
        self._weight_unit_combo.addItems(list(WEIGHT_UNITS))
        self._weight_unit_combo.currentTextChanged.connect(
            self._reagent_table.set_global_weight_unit
        )

        table_toolbar = QHBoxLayout()
        table_toolbar.addWidget(QLabel("weight単位:"))
        table_toolbar.addWidget(self._weight_unit_combo)
        table_toolbar.addStretch()

        middle_column = QVBoxLayout()
        middle_column.setSpacing(16)
        middle_column.addWidget(self._structure_input_panel)
        middle_column.addWidget(self._structure_panel)
        middle_column.addWidget(self._library_grid, 1)

        table_row = QHBoxLayout()
        table_row.setSpacing(16)
        table_row.addWidget(self._reagent_table, 1)
        table_row.addLayout(middle_column, 1)
        table_row.addWidget(self._pubchem_panel, 1)

        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(20, 16, 20, 20)
        main_layout.setSpacing(14)
        main_layout.addLayout(toolbar_layout)
        main_layout.addWidget(self._search_bar)
        main_layout.addLayout(table_toolbar)
        main_layout.addLayout(table_row)
        self.setCentralWidget(central)

    def closeEvent(self, event) -> None:
        self._structure_input_panel.shutdown()
        super().closeEvent(event)

    def _on_compound_resolved(self, info: CompoundInfo) -> None:
        self._add_or_fill_column(_compound_info_to_column(info))

    def _on_add_reagent_requested(self) -> None:
        self._reagent_table.add_column(ReagentColumn())

    def _on_save_column_requested(self, index: int) -> None:
        columns = self._reagent_table.columns()
        if not (0 <= index < len(columns)):
            return
        column = columns[index]
        if column.fw is None:
            QMessageBox.warning(self, "保存できません", "Fw(分子量)が未設定です。")
            return

        name, ok = QInputDialog.getText(self, "ライブラリに保存", "試薬名:", text=column.name or "")
        if not ok or not name.strip():
            return

        info = CompoundInfo(
            name=name.strip(),
            formula=column.formula,
            molecular_weight=column.fw,
            density=column.density,
            smiles=column.smiles,
            source=column.source,
        )
        column.library_id = compound_source.save_to_library(self._conn, info)
        column.name = name.strip()
        self._reagent_table.replace_column(index, column)
        self._library_grid.refresh()

    def _on_library_entry_selected(self, entry: LibraryEntry) -> None:
        self._add_or_fill_column(_library_entry_to_column(entry))

    def _on_open_reagent_editor(self) -> None:
        dialog = ReagentEditorDialog(self._conn, self)
        if dialog.exec() == ReagentEditorDialog.DialogCode.Accepted:
            self._library_grid.refresh()

    def _add_or_fill_column(self, column: ReagentColumn) -> None:
        blank_index = self._reagent_table.first_blank_column_index()
        if blank_index is not None:
            self._reagent_table.replace_column(blank_index, column)
        else:
            self._reagent_table.add_column(column)

    def _on_column_selected(self, index: int) -> None:
        columns = self._reagent_table.columns()
        if 0 <= index < len(columns):
            self._structure_panel.show_compound(columns[index])

    def _on_open_template_list(self) -> None:
        if self._template_list_dialog is None:
            self._template_list_dialog = TemplateListDialog(self._conn, self)
            self._template_list_dialog.template_loaded.connect(self._on_template_loaded)
        self._template_list_dialog.refresh()
        self._template_list_dialog.show()
        self._template_list_dialog.raise_()
        self._template_list_dialog.activateWindow()

    def _on_template_loaded(self, tmpl: Template) -> None:
        self._reagent_table.clear()
        missing = 0
        for reagent in tmpl.payload.get("reagents", []):
            entry = library_repo.get(self._conn, reagent.get("library_id"))
            if entry is None:
                missing += 1
                continue
            column = _library_entry_to_column(entry)
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

        columns = [c for c in self._reagent_table.columns() if c.name or c.fw is not None]
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
        if self._template_list_dialog is not None:
            self._template_list_dialog.refresh()


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


def _library_entry_to_column(entry: LibraryEntry) -> ReagentColumn:
    return ReagentColumn(
        name=entry.name,
        formula=entry.formula,
        smiles=entry.smiles,
        source=entry.source,
        library_id=entry.id,
        fw=entry.molecular_weight,
        density=entry.density,
    )
