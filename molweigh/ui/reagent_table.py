"""試薬テーブルWidget。列=試薬(動的に追加/削除)、行=Fw/weight/d/volume/molarity/mmol/eq。

先頭列(インデックス0)が常に基準試薬。基準試薬の重量から算出したmmolを基準に、
他の列は「目標eq入力→必要重量を自動計算」と「重量(または密度×体積)実測入力→
実績eqを逆算」の両方向に対応する(仕様書§3の秤量計画/実績記録を1つの表に統合)。

再計算のコアロジック(`recompute_column` / `recompute_all`)はQt非依存の純粋関数
として切り出し、Widget無しで単体テストできるようにしている。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import calc

ROW_LABELS = ["Fw", "weight", "d(g/cm3)", "volume(mL)", "molarity(M)", "mmol", "eq"]
HEADER_ROW = 0
# データ行は1始まり(row 0はヘッダー行のため)
(ROW_FW, ROW_WEIGHT, ROW_DENSITY, ROW_VOLUME, ROW_MOLARITY, ROW_MMOL, ROW_EQ) = range(1, len(ROW_LABELS) + 1)

WEIGHT_UNITS = ("mg", "g")


@dataclass
class ReagentColumn:
    name: str = ""
    formula: str | None = None
    smiles: str | None = None
    source: str = "manual"
    library_id: int | None = None
    fw: float | None = None
    density: float | None = None
    molarity: float | None = None
    weight_value: float | None = None
    weight_unit: str = "mg"
    volume_ml: float | None = None
    target_eq: float | None = None
    weight_is_actual: bool = False


@dataclass
class ComputedResult:
    mmol: float | None
    eq: float | None
    is_actual: bool


def recompute_all(columns: list[ReagentColumn]) -> list[ComputedResult]:
    """先頭列を基準として、全列のmmol/eqを算出する。"""
    if not columns:
        return []

    base = columns[0]
    base_mmol = None
    if base.fw and base.weight_value:
        base_mmol = calc.calc_base_mmol(base.fw, base.weight_value, base.weight_unit)
    results = [ComputedResult(mmol=base_mmol, eq=1.0 if base_mmol is not None else None, is_actual=True)]

    for col in columns[1:]:
        results.append(_recompute_column(col, base_mmol))
    return results


def _recompute_column(col: ReagentColumn, base_mmol: float | None) -> ComputedResult:
    if col.volume_ml is not None and col.density is not None and col.fw:
        mmol = calc.calc_actual_mmol(col.fw, density=col.density, volume=col.volume_ml)
        eq = calc.calc_actual_eq(mmol, base_mmol) if base_mmol else None
        return ComputedResult(mmol=mmol, eq=eq, is_actual=True)

    if col.weight_is_actual and col.weight_value is not None and col.fw:
        mmol = calc.calc_actual_mmol(col.fw, weight=col.weight_value, weight_unit=col.weight_unit)
        eq = calc.calc_actual_eq(mmol, base_mmol) if base_mmol else None
        return ComputedResult(mmol=mmol, eq=eq, is_actual=True)

    if col.target_eq is not None and base_mmol is not None:
        mmol = calc.calc_target_mmol(base_mmol, col.target_eq)
        if col.fw:
            col.weight_value = calc.calc_required_weight(col.fw, mmol, col.weight_unit)
        return ComputedResult(mmol=mmol, eq=col.target_eq, is_actual=False)

    return ComputedResult(mmol=None, eq=col.target_eq, is_actual=False)


_ACTUAL_EQ_COLOR = QColor("#E1F5EE")
_TARGET_EQ_COLOR = QColor("#E6F1FB")
_BASE_EQ_COLOR = QColor("#D3D1C7")


class ReagentTableWidget(QWidget):
    """試薬テーブル本体。列選択・列追加要求・列内容変更をシグナルで通知する。"""

    column_selected = Signal(int)
    add_reagent_requested = Signal()
    columns_changed = Signal()
    save_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._columns: list[ReagentColumn] = []

        self._table = QTableWidget(len(ROW_LABELS) + 1, 1, self)
        self._table.horizontalHeader().hide()
        self._table.verticalHeader().hide()
        self._table.setRowHeight(HEADER_ROW, 165)
        self._table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.EditKeyPressed)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.currentCellChanged.connect(self._on_current_cell_changed)

        for row, label in enumerate(ROW_LABELS, start=1):
            item = QTableWidgetItem(label)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 0, item)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._table)

        self._rebuild()

    def add_column(self, column: ReagentColumn) -> None:
        self._columns.append(column)
        self._rebuild()
        self.columns_changed.emit()

    def replace_column(self, index: int, column: ReagentColumn) -> None:
        if 0 <= index < len(self._columns):
            self._columns[index] = column
            self._rebuild()
            self.columns_changed.emit()

    def first_blank_column_index(self) -> int | None:
        """名前もFwも未設定の空き列(デフォルト表示用プレースホルダ)を先頭から探す。"""
        for i, column in enumerate(self._columns):
            if not column.name and column.fw is None:
                return i
        return None

    def remove_column(self, index: int) -> None:
        if 0 <= index < len(self._columns):
            del self._columns[index]
            self._rebuild()
            self.columns_changed.emit()

    def clear(self) -> None:
        self._columns = []
        self._rebuild()
        self.columns_changed.emit()

    def columns(self) -> list[ReagentColumn]:
        return list(self._columns)

    def selected_column(self) -> ReagentColumn | None:
        col = self._table.currentColumn() - 1
        if 0 <= col < len(self._columns):
            return self._columns[col]
        return None

    def _on_current_cell_changed(self, row: int, col: int, prev_row: int, prev_col: int) -> None:
        index = col - 1
        if 0 <= index < len(self._columns):
            self.column_selected.emit(index)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        row, col = item.row(), item.column()
        index = col - 1
        if row == 0 or not (0 <= index < len(self._columns)):
            return
        column = self._columns[index]
        text = item.text().strip()
        value = None
        if text:
            try:
                value = float(text)
            except ValueError:
                value = None

        if row == ROW_FW:
            column.fw = value
        elif row == ROW_DENSITY:
            column.density = value
        elif row == ROW_VOLUME:
            column.volume_ml = value
            if value is not None:
                column.weight_is_actual = False
        elif row == ROW_MOLARITY:
            column.molarity = value
        elif row == ROW_WEIGHT:
            column.weight_value = value
            if index > 0:
                column.weight_is_actual = value is not None
                if value is not None:
                    column.volume_ml = None
        elif row == ROW_EQ and index > 0:
            column.target_eq = value
            column.weight_is_actual = False
            column.volume_ml = None

        self._rebuild()

    def _on_weight_unit_changed(self, index: int, new_unit: str) -> None:
        if not (0 <= index < len(self._columns)):
            return
        column = self._columns[index]
        if new_unit == column.weight_unit:
            return
        if column.weight_value is not None:
            if column.weight_unit == "mg" and new_unit == "g":
                column.weight_value /= 1000
            elif column.weight_unit == "g" and new_unit == "mg":
                column.weight_value *= 1000
        column.weight_unit = new_unit
        self._rebuild()

    def _rebuild(self) -> None:
        self._table.blockSignals(True)

        for c in range(self._table.columnCount()):
            self._clear_cell_widget(HEADER_ROW, c)
        self._table.setColumnCount(len(self._columns) + 2)
        self._table.setColumnWidth(0, 84)

        results = recompute_all(self._columns)

        for i, column in enumerate(self._columns):
            table_col = i + 1
            self._table.setColumnWidth(table_col, 110)
            self._render_header(table_col, i, column)
            result = results[i] if i < len(results) else ComputedResult(None, None, False)
            self._render_data_rows(table_col, i, column, result)

        add_col = len(self._columns) + 1
        self._table.setColumnWidth(add_col, 70)
        add_button = QPushButton("+ 試薬")
        add_button.clicked.connect(self.add_reagent_requested)
        self._table.setCellWidget(0, add_col, add_button)

        self._table.blockSignals(False)

    def _clear_cell_widget(self, row: int, col: int) -> None:
        old = self._table.cellWidget(row, col)
        if old is None:
            return
        # 同じWidgetインスタンスをセル間で使い回す(removeCellWidgetで外して
        # 別のセルにsetCellWidgetし直す)と、このPySide6環境では再描画時に
        # ネイティブクラッシュする。既存Widgetは必ず破棄し、置き換え先には
        # 常に新規インスタンスを使う。
        self._table.removeCellWidget(row, col)
        old.setParent(None)
        old.deleteLater()

    def _render_header(self, table_col: int, index: int, column: ReagentColumn) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)

        if index == 0:
            layout.addWidget(QLabel("基準"))

        name_label = QLabel(column.name or "(未設定)")
        name_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(name_label)

        formula_label = QLabel(column.formula or "")
        formula_label.setStyleSheet("color: #888780; font-size: 11px;")
        layout.addWidget(formula_label)

        if column.library_id is None and (column.name or column.fw is not None):
            unsaved_label = QLabel("未保存")
            unsaved_label.setStyleSheet("color: #BA7517; font-size: 10px;")
            layout.addWidget(unsaved_label)

            save_button = QPushButton("ライブラリに追加")
            save_button.clicked.connect(lambda _=False, i=index: self.save_requested.emit(i))
            layout.addWidget(save_button)

        weight_unit_combo = QComboBox()
        weight_unit_combo.addItems(list(WEIGHT_UNITS))
        weight_unit_combo.setCurrentText(column.weight_unit)
        weight_unit_combo.setFixedWidth(55)
        weight_unit_combo.currentTextChanged.connect(
            lambda unit, i=index: self._on_weight_unit_changed(i, unit)
        )
        layout.addWidget(weight_unit_combo)

        delete_button = QPushButton("×")
        delete_button.setFixedWidth(20)
        delete_button.clicked.connect(lambda _=False, i=index: self.remove_column(i))
        layout.addWidget(delete_button)

        self._table.setCellWidget(0, table_col, container)
        if index == 0:
            container.setStyleSheet("background-color: #E6F1FB;")

    def _render_data_rows(
        self, table_col: int, index: int, column: ReagentColumn, result: ComputedResult
    ) -> None:
        self._set_cell(table_col, ROW_FW, _fmt(column.fw), editable=True)
        self._set_cell(table_col, ROW_WEIGHT, _fmt(column.weight_value), editable=True)
        self._set_cell(table_col, ROW_DENSITY, _fmt(column.density), editable=True)
        self._set_cell(table_col, ROW_VOLUME, _fmt(column.volume_ml), editable=True)
        self._set_cell(table_col, ROW_MOLARITY, _fmt(column.molarity), editable=True)
        self._set_cell(table_col, ROW_MMOL, _fmt(result.mmol), editable=False)

        eq_text = _fmt(result.eq)
        eq_item = self._set_cell(table_col, ROW_EQ, eq_text, editable=(index > 0))
        if index == 0:
            eq_item.setBackground(_BASE_EQ_COLOR)
        elif result.eq is not None:
            eq_item.setBackground(_ACTUAL_EQ_COLOR if result.is_actual else _TARGET_EQ_COLOR)

    def _set_cell(self, table_col: int, row: int, text: str, editable: bool) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        if not editable:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, table_col, item)
        return item


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.4g}"
