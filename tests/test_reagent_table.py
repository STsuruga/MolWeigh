import pytest
from PySide6.QtWidgets import QLabel

from molweigh.ui.reagent_table import (
    ROW_EQ,
    ROW_FW,
    ROW_WEIGHT,
    ReagentColumn,
    ReagentTableWidget,
    recompute_all,
)


class TestRecomputeAllPureLogic:
    def test_empty_returns_empty(self):
        assert recompute_all([]) == []

    def test_base_only(self):
        base = ReagentColumn(name="Base", fw=458.27, weight_value=200)
        results = recompute_all([base])
        assert results[0].eq == pytest.approx(1.0)
        assert results[0].mmol == pytest.approx(0.4364239, rel=1e-6)
        assert results[0].is_actual is True

    def test_base_without_weight_gives_none(self):
        base = ReagentColumn(name="Base", fw=458.27)
        results = recompute_all([base])
        assert results[0].mmol is None
        assert results[0].eq is None

    def test_target_eq_fills_weight_and_mmol(self):
        base = ReagentColumn(fw=458.27, weight_value=200)
        reagent = ReagentColumn(fw=122.17, target_eq=6.0)
        results = recompute_all([base, reagent])
        assert results[1].eq == pytest.approx(6.0)
        assert results[1].is_actual is False
        assert reagent.weight_value == pytest.approx(results[1].mmol * 122.17)

    def test_actual_weight_override_computes_actual_eq(self):
        base = ReagentColumn(fw=458.27, weight_value=200)
        reagent = ReagentColumn(fw=122.17, weight_value=100, weight_is_actual=True)
        results = recompute_all([base, reagent])
        assert results[1].is_actual is True
        expected_mmol = 100 / 122.17
        assert results[1].mmol == pytest.approx(expected_mmol)
        base_mmol = 200 / 458.27
        assert results[1].eq == pytest.approx(expected_mmol / base_mmol)

    def test_density_volume_path_is_actual(self):
        base = ReagentColumn(fw=458.27, weight_value=200)
        reagent = ReagentColumn(fw=100.0, density=1.2, volume_ml=0.5)
        results = recompute_all([base, reagent])
        assert results[1].is_actual is True
        assert results[1].mmol == pytest.approx(6.0)

    def test_no_input_gives_none_mmol(self):
        base = ReagentColumn(fw=458.27, weight_value=200)
        reagent = ReagentColumn(fw=122.17)
        results = recompute_all([base, reagent])
        assert results[1].mmol is None
        assert results[1].eq is None


class TestReagentTableWidget:
    def test_add_and_remove_column(self, qapp):
        widget = ReagentTableWidget()
        widget.add_column(ReagentColumn(name="Base", fw=458.27, weight_value=200))
        widget.add_column(ReagentColumn(name="DMAP", fw=122.17, target_eq=6.0))
        assert len(widget.columns()) == 2

        widget.remove_column(0)
        remaining = widget.columns()
        assert len(remaining) == 1
        assert remaining[0].name == "DMAP"

    def test_first_blank_column_index(self, qapp):
        widget = ReagentTableWidget()
        widget.add_column(ReagentColumn())
        widget.add_column(ReagentColumn())
        assert widget.first_blank_column_index() == 0

        widget.replace_column(0, ReagentColumn(name="Base", fw=458.27, weight_value=200))
        assert widget.first_blank_column_index() == 1

        widget.replace_column(1, ReagentColumn(name="DMAP", fw=122.17))
        assert widget.first_blank_column_index() is None

    def test_replace_column_keeps_length_and_position(self, qapp):
        widget = ReagentTableWidget()
        widget.add_column(ReagentColumn())
        widget.add_column(ReagentColumn(name="Keep", fw=1.0))
        widget.replace_column(0, ReagentColumn(name="Filled", fw=458.27))

        columns = widget.columns()
        assert len(columns) == 2
        assert columns[0].name == "Filled"
        assert columns[1].name == "Keep"

    def test_editing_eq_cell_updates_column_and_recomputes(self, qapp):
        widget = ReagentTableWidget()
        widget.add_column(ReagentColumn(name="Base", fw=458.27, weight_value=200))
        widget.add_column(ReagentColumn(name="DMAP", fw=122.17))

        table_col = 2
        widget._table.item(ROW_EQ, table_col).setText("6.0")

        reagent = widget.columns()[1]
        assert reagent.target_eq == pytest.approx(6.0)
        assert reagent.weight_value is not None

    def test_editing_weight_cell_marks_actual_and_recomputes_eq(self, qapp):
        widget = ReagentTableWidget()
        widget.add_column(ReagentColumn(name="Base", fw=458.27, weight_value=200))
        widget.add_column(ReagentColumn(name="DMAP", fw=122.17))

        table_col = 2
        widget._table.item(ROW_WEIGHT, table_col).setText("100")

        reagent = widget.columns()[1]
        assert reagent.weight_is_actual is True
        assert reagent.weight_value == pytest.approx(100)

    def test_editing_fw_cell_directly_sets_fw(self, qapp):
        widget = ReagentTableWidget()
        widget.add_column(ReagentColumn(name="Manual", weight_value=200))

        table_col = 1
        widget._table.item(ROW_FW, table_col).setText("180.16")

        assert widget.columns()[0].fw == pytest.approx(180.16)

    def test_clearing_fw_cell_sets_none(self, qapp):
        widget = ReagentTableWidget()
        widget.add_column(ReagentColumn(name="Manual", fw=100.0, weight_value=200))

        table_col = 1
        widget._table.item(ROW_FW, table_col).setText("")

        assert widget.columns()[0].fw is None

    def test_weight_unit_toggle_converts_stored_value(self, qapp):
        widget = ReagentTableWidget()
        widget.add_column(ReagentColumn(name="Base", fw=458.27, weight_value=200, weight_unit="mg"))

        widget._on_weight_unit_changed(0, "g")
        column = widget.columns()[0]
        assert column.weight_unit == "g"
        assert column.weight_value == pytest.approx(0.2)

        widget._on_weight_unit_changed(0, "mg")
        column = widget.columns()[0]
        assert column.weight_unit == "mg"
        assert column.weight_value == pytest.approx(200)

    def test_weight_unit_g_computes_same_physical_mmol(self, qapp):
        mg_col = ReagentColumn(fw=458.27, weight_value=200, weight_unit="mg")
        g_col = ReagentColumn(fw=458.27, weight_value=0.2, weight_unit="g")
        mg_result = recompute_all([mg_col])[0]
        g_result = recompute_all([g_col])[0]
        assert mg_result.mmol == pytest.approx(g_result.mmol)

    def test_add_reagent_requested_signal(self, qapp):
        widget = ReagentTableWidget()
        received = []
        widget.add_reagent_requested.connect(lambda: received.append(True))
        add_col = widget._table.columnCount() - 1
        widget._table.cellWidget(0, add_col).click()
        assert received == [True]

    def test_columns_changed_signal_on_add(self, qapp):
        widget = ReagentTableWidget()
        received = []
        widget.columns_changed.connect(lambda: received.append(True))
        widget.add_column(ReagentColumn(name="Base", fw=458.27, weight_value=200))
        assert received == [True]

    def test_repeated_rebuilds_do_not_leave_orphaned_header_widgets(self, qapp):
        # 再構築のたびに古いヘッダーWidgetが破棄されず幽霊表示として残るリグレッションの回帰テスト。
        widget = ReagentTableWidget()
        widget.add_column(ReagentColumn(name="Base", fw=458.27, weight_value=200))
        widget.add_column(ReagentColumn(name="DMAP", fw=122.17, target_eq=6.0))
        widget._rebuild()
        widget._rebuild()
        widget._rebuild()

        labels = widget._table.viewport().findChildren(QLabel)
        names = [label.text() for label in labels if label.text() in ("Base", "DMAP")]
        assert names.count("Base") == 1
        assert names.count("DMAP") == 1
