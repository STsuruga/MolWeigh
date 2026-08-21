"""試薬テーブルWidget。列=試薬(動的に追加/削除)、行=Fw/weight/d/volume/molarity/mmol/eq。

先頭列(インデックス0)が常に基準試薬。基準試薬の重量から算出したmmolを基準に、
他の列は「目標eq入力→必要重量を自動計算」と「重量(または密度×体積)実測入力→
実績eqを逆算」の両方向に対応する(仕様書§3の秤量計画/実績記録を1つの表に統合)。

再計算のコアロジック(`recompute_column` / `recompute_all`)はQt非依存の純粋関数
として切り出し、Widget無しで単体テストできるようにしている。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QPushButton,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import calc, structure
from . import theme

ROW_LABELS = ["Fw", "weight", "d(g/cm3)", "volume(mL)", "molarity(M)", "mmol", "eq"]
HEADER_ROW = 0
_THUMBNAIL_SIZE = (90, 70)
_HEADER_ROW_HEIGHT = 235
_DATA_ROW_HEIGHT = 34
_DATA_COLUMN_WIDTH = 110
_ADD_COLUMN_WIDTH = 40
# 固定列(行ラベル)の幅はデータ列と揃える。横スクロール時に固定列の
# オーバーレイ幅とスクロールで先頭に来る列の幅が食い違うと、境界に
# 隣の列の断片が透けて見えてしまうため。
_LABEL_COLUMN_WIDTH = _DATA_COLUMN_WIDTH
# データ行は1始まり(row 0はヘッダー行のため)
(ROW_FW, ROW_WEIGHT, ROW_DENSITY, ROW_VOLUME, ROW_MOLARITY, ROW_MMOL, ROW_EQ) = range(1, len(ROW_LABELS) + 1)

WEIGHT_UNITS = ("mg", "g")


@dataclass
class ReagentColumn:
    name: str = ""
    formula: str | None = None
    smiles: str | None = None
    molblock: str | None = None  # Ketcherの2D座標(見た目専用。同一性判定はsmilesを使う)
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
        if base.density is not None:
            base.volume_ml = calc.calc_required_volume(
                weight=base.weight_value, density=base.density, weight_unit=base.weight_unit
            )
    results = [ComputedResult(mmol=base_mmol, eq=1.0 if base_mmol is not None else None, is_actual=True)]

    for col in columns[1:]:
        results.append(_recompute_column(col, base_mmol))
    return results


def _recompute_column(col: ReagentColumn, base_mmol: float | None) -> ComputedResult:
    # 比重を入力した場合は重量⇔体積を相互に補完して両方表示する。
    if col.volume_ml is not None and col.density is not None and col.fw:
        mmol = calc.calc_actual_mmol(col.fw, density=col.density, volume=col.volume_ml)
        col.weight_value = calc.calc_required_weight(col.fw, mmol, col.weight_unit)
        eq = calc.calc_actual_eq(mmol, base_mmol) if base_mmol else None
        return ComputedResult(mmol=mmol, eq=eq, is_actual=True)

    if col.weight_is_actual and col.weight_value is not None and col.fw:
        mmol = calc.calc_actual_mmol(col.fw, weight=col.weight_value, weight_unit=col.weight_unit)
        if col.density is not None:
            col.volume_ml = calc.calc_required_volume(
                weight=col.weight_value, density=col.density, weight_unit=col.weight_unit
            )
        eq = calc.calc_actual_eq(mmol, base_mmol) if base_mmol else None
        return ComputedResult(mmol=mmol, eq=eq, is_actual=True)

    if col.target_eq is not None and base_mmol is not None:
        mmol = calc.calc_target_mmol(base_mmol, col.target_eq)
        if col.fw:
            col.weight_value = calc.calc_required_weight(col.fw, mmol, col.weight_unit)
            if col.density is not None:
                col.volume_ml = calc.calc_required_volume(
                    weight=col.weight_value, density=col.density, weight_unit=col.weight_unit
                )
        # 濃度(molarity)のみ入力されている場合は重量を介さず体積だけ算出する。
        if col.molarity is not None and col.density is None:
            col.volume_ml = calc.calc_required_volume(mmol=mmol, molarity=col.molarity)
        return ComputedResult(mmol=mmol, eq=col.target_eq, is_actual=False)

    return ComputedResult(mmol=None, eq=col.target_eq, is_actual=False)


_ACTUAL_EQ_COLOR = QColor(theme.SUCCESS_BG)
_TARGET_EQ_COLOR = QColor(theme.ACCENT_BG)
_BASE_EQ_COLOR = QColor(theme.BASE_BG)


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
        # 列単位でスクロールし、固定列との境界に他列の一部が透けて見えるのを防ぐ。
        self._table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerItem)
        self._table.verticalHeader().setDefaultSectionSize(_DATA_ROW_HEIGHT)
        self._table.setRowHeight(HEADER_ROW, _HEADER_ROW_HEIGHT)
        self._table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.EditKeyPressed)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.currentCellChanged.connect(self._on_current_cell_changed)
        self._table.installEventFilter(self)

        corner_item = QTableWidgetItem("")
        corner_item.setFlags(corner_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(HEADER_ROW, 0, corner_item)

        for row, label in enumerate(ROW_LABELS, start=1):
            item = QTableWidgetItem(label)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            self._table.setItem(row, 0, item)
            if row == ROW_WEIGHT:
                self._weight_label_item = item
        self._update_weight_label(WEIGHT_UNITS[0])

        # 横スクロールしても左端の行ラベル列(Fw/weight/...)が常に見えるよう、
        # 同じモデルを共有する固定ビューをcolumn 0の上に重ねて表示する。
        self._frozen_table = QTableView(self._table)
        self._frozen_table.setModel(self._table.model())
        self._frozen_table.setSelectionModel(self._table.selectionModel())
        self._frozen_table.horizontalHeader().hide()
        self._frozen_table.verticalHeader().hide()
        self._frozen_table.verticalHeader().setDefaultSectionSize(_DATA_ROW_HEIGHT)
        self._frozen_table.setRowHeight(HEADER_ROW, _HEADER_ROW_HEIGHT)
        self._frozen_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._frozen_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._frozen_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._frozen_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._frozen_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._frozen_table.setColumnWidth(0, _LABEL_COLUMN_WIDTH)
        self._frozen_table.setStyleSheet(
            f"QTableView {{ background: {theme.SURFACE}; border: none; "
            f"border-right: 1px solid {theme.BORDER_STRONG}; }}"
        )
        self._table.verticalScrollBar().valueChanged.connect(self._frozen_table.verticalScrollBar().setValue)
        self._frozen_table.verticalScrollBar().valueChanged.connect(self._table.verticalScrollBar().setValue)

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

    def content_height(self) -> int:
        """行の合計高さぴったりにWidgetを収める(下に無駄な余白を作らない)ための高さ。"""
        scrollbar_allowance = 16
        frame_allowance = 4
        return _HEADER_ROW_HEIGHT + len(ROW_LABELS) * _DATA_ROW_HEIGHT + scrollbar_allowance + frame_allowance

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
            column.fw = round(value, 4) if value is not None else None
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
        self.columns_changed.emit()

    def set_global_weight_unit(self, new_unit: str) -> None:
        """全列のweight単位を一括で切り替え、表示値も換算する。"""
        for column in self._columns:
            if new_unit == column.weight_unit:
                continue
            if column.weight_value is not None:
                if column.weight_unit == "mg" and new_unit == "g":
                    column.weight_value /= 1000
                elif column.weight_unit == "g" and new_unit == "mg":
                    column.weight_value *= 1000
            column.weight_unit = new_unit
        self._update_weight_label(new_unit)
        self._rebuild()
        self.columns_changed.emit()

    def _update_weight_label(self, unit: str) -> None:
        self._weight_label_item.setText(f"weight({unit})")

    def _rebuild(self) -> None:
        self._table.blockSignals(True)
        # setColumnCount()は横スクロール位置をリセットしてしまうため、退避して再適用する。
        scroll_value = self._table.horizontalScrollBar().value()

        for c in range(self._table.columnCount()):
            self._clear_cell_widget(HEADER_ROW, c)
        self._table.setColumnCount(len(self._columns) + 2)
        self._table.setColumnWidth(0, _LABEL_COLUMN_WIDTH)

        results = recompute_all(self._columns)

        for i, column in enumerate(self._columns):
            table_col = i + 1
            self._table.setColumnWidth(table_col, _DATA_COLUMN_WIDTH)
            self._render_header(table_col, i, column)
            result = results[i] if i < len(results) else ComputedResult(None, None, False)
            self._render_data_rows(table_col, i, column, result)

        add_col = len(self._columns) + 1
        self._table.setColumnWidth(add_col, _ADD_COLUMN_WIDTH)
        add_button = QPushButton("+")
        add_button.setToolTip("試薬を追加")
        add_button.setStyleSheet(theme.accent_button_style())
        add_button.clicked.connect(self.add_reagent_requested)
        self._table.setCellWidget(0, add_col, add_button)

        for col in range(1, self._table.columnCount()):
            self._frozen_table.setColumnHidden(col, True)
        self._schedule_frozen_geometry_update()

        self._table.horizontalScrollBar().setValue(scroll_value)
        self._table.blockSignals(False)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._table and event.type() == QEvent.Type.Resize:
            self._schedule_frozen_geometry_update()
        return super().eventFilter(obj, event)

    def _schedule_frozen_geometry_update(self) -> None:
        # viewport()のサイズは、リサイズイベントがself._table自身のイベント
        # ハンドラでまだ反映されていない時点では古い値のことがあるため、
        # イベントループが一巡した後(サイズ確定後)に更新する。
        QTimer.singleShot(0, self._update_frozen_geometry)

    def _update_frozen_geometry(self) -> None:
        frame = self._table.frameWidth()
        self._frozen_table.setGeometry(
            frame,
            frame,
            self._table.columnWidth(0),
            self._table.viewport().height() + frame * 2,
        )

    def _clear_cell_widget(self, row: int, col: int) -> None:
        old = self._table.cellWidget(row, col)
        if old is None:
            return
        # 同じWidgetインスタンスをセル間で使い回す(removeCellWidgetで外して
        # 別のセルにsetCellWidgetし直す)と、このPySide6環境では再描画時に
        # ネイティブクラッシュする。既存Widgetは必ず破棄し、置き換え先には
        # 常に新規インスタンスを使う。
        self._table.removeCellWidget(row, col)
        old.hide()
        old.setParent(None)
        old.deleteLater()

    def _render_header(self, table_col: int, index: int, column: ReagentColumn) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)

        if index == 0:
            layout.addWidget(QLabel("基準"))

        thumbnail_label = QLabel()
        thumbnail_label.setFixedSize(*_THUMBNAIL_SIZE)
        thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumbnail_label.setStyleSheet(
            f"background: {theme.ACCENT_BG}; border-radius: 6px; "
            f"color: {theme.TEXT_MUTED}; font-size: 10px;"
        )
        _set_thumbnail(thumbnail_label, column)
        layout.addWidget(thumbnail_label)

        name_label = QLabel(column.name or "(未設定)")
        name_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(name_label)

        formula_label = QLabel(column.formula or "")
        formula_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(formula_label)

        if column.library_id is None and (column.name or column.fw is not None):
            unsaved_label = QLabel("未保存")
            unsaved_label.setStyleSheet(f"color: {theme.WARNING_TEXT}; font-size: 10px;")
            layout.addWidget(unsaved_label)

            save_button = QPushButton("追加")
            save_button.setToolTip("ライブラリに追加")
            save_button.clicked.connect(lambda _=False, i=index: self.save_requested.emit(i))
            layout.addWidget(save_button)

        delete_button = QPushButton("×")
        delete_button.setFixedWidth(20)
        delete_button.setStyleSheet(theme.danger_ghost_button_style())
        delete_button.clicked.connect(lambda _=False, i=index: self.remove_column(i))
        layout.addWidget(delete_button)

        self._table.setCellWidget(0, table_col, container)
        if index == 0:
            container.setStyleSheet(f"background-color: {theme.ACCENT_BG};")

    def _render_data_rows(
        self, table_col: int, index: int, column: ReagentColumn, result: ComputedResult
    ) -> None:
        self._set_cell(table_col, ROW_FW, _fmt_fw(column.fw), editable=True)
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


def _fmt_fw(value: float | None) -> str:
    """分子量(Fw)は小数点以下2桁で表示する(内部の計算値は4桁精度のまま)。"""
    if value is None:
        return ""
    return f"{value:.2f}"


def _set_thumbnail(label: QLabel, column: ReagentColumn) -> None:
    if column.smiles:
        try:
            label.setPixmap(
                structure.render_structure_image(
                    column.smiles,
                    size=_THUMBNAIL_SIZE,
                    device_pixel_ratio=label.devicePixelRatioF(),
                    molblock=column.molblock,
                )
            )
            return
        except ValueError:
            pass
    if column.formula:
        label.setText(column.formula)
    else:
        label.setText("構造式なし")
