import pytest
from PySide6.QtWidgets import QLabel

from molweigh.ui.reagent_table import (
    ROW_EQ,
    ROW_WEIGHT,
    ReagentColumn,
    ReagentTableWidget,
    recompute_all,
)


class TestRecomputeAllPureLogic:
    def test_empty_returns_empty(self):
        assert recompute_all([]) == []

    def test_base_only(self):
        base = ReagentColumn(name="Base", fw=458.27, weight_mg=200)
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
        base = ReagentColumn(fw=458.27, weight_mg=200)
        reagent = ReagentColumn(fw=122.17, target_eq=6.0)
        results = recompute_all([base, reagent])
        assert results[1].eq == pytest.approx(6.0)
        assert results[1].is_actual is False
        assert reagent.weight_mg == pytest.approx(results[1].mmol * 122.17)

    def test_actual_weight_override_computes_actual_eq(self):
        base = ReagentColumn(fw=458.27, weight_mg=200)
        reagent = ReagentColumn(fw=122.17, weight_mg=100, weight_is_actual=True)
        results = recompute_all([base, reagent])
        assert results[1].is_actual is True
        expected_mmol = 100 / 122.17
        assert results[1].mmol == pytest.approx(expected_mmol)
        base_mmol = 200 / 458.27
        assert results[1].eq == pytest.approx(expected_mmol / base_mmol)

    def test_density_volume_path_is_actual(self):
        base = ReagentColumn(fw=458.27, weight_mg=200)
        reagent = ReagentColumn(fw=100.0, density=1.2, volume_ml=0.5)
        results = recompute_all([base, reagent])
        assert results[1].is_actual is True
        assert results[1].mmol == pytest.approx(6.0)

    def test_no_input_gives_none_mmol(self):
        base = ReagentColumn(fw=458.27, weight_mg=200)
        reagent = ReagentColumn(fw=122.17)
        results = recompute_all([base, reagent])
        assert results[1].mmol is None
        assert results[1].eq is None


class TestReagentTableWidget:
    def test_add_and_remove_column(self, qapp):
        widget = ReagentTableWidget()
        widget.add_column(ReagentColumn(name="Base", fw=458.27, weight_mg=200))
        widget.add_column(ReagentColumn(name="DMAP", fw=122.17, target_eq=6.0))
        assert len(widget.columns()) == 2

        widget.remove_column(0)
        remaining = widget.columns()
        assert len(remaining) == 1
        assert remaining[0].name == "DMAP"

    def test_editing_eq_cell_updates_column_and_recomputes(self, qapp):
        widget = ReagentTableWidget()
        widget.add_column(ReagentColumn(name="Base", fw=458.27, weight_mg=200))
        widget.add_column(ReagentColumn(name="DMAP", fw=122.17))

        table_col = 2
        widget._table.item(ROW_EQ, table_col).setText("6.0")

        reagent = widget.columns()[1]
        assert reagent.target_eq == pytest.approx(6.0)
        assert reagent.weight_mg is not None

    def test_editing_weight_cell_marks_actual_and_recomputes_eq(self, qapp):
        widget = ReagentTableWidget()
        widget.add_column(ReagentColumn(name="Base", fw=458.27, weight_mg=200))
        widget.add_column(ReagentColumn(name="DMAP", fw=122.17))

        table_col = 2
        widget._table.item(ROW_WEIGHT, table_col).setText("100")

        reagent = widget.columns()[1]
        assert reagent.weight_is_actual is True
        assert reagent.weight_mg == pytest.approx(100)

    def test_add_reagent_requested_signal(self, qapp):
        widget = ReagentTableWidget()
        received = []
        widget.add_reagent_requested.connect(lambda: received.append(True))
        widget._add_button.click()
        assert received == [True]

    def test_columns_changed_signal_on_add(self, qapp):
        widget = ReagentTableWidget()
        received = []
        widget.columns_changed.connect(lambda: received.append(True))
        widget.add_column(ReagentColumn(name="Base", fw=458.27, weight_mg=200))
        assert received == [True]

    def test_repeated_rebuilds_do_not_leave_orphaned_header_widgets(self, qapp):
        # 再構築のたびに古いヘッダーWidgetが破棄されず幽霊表示として残るリグレッションの回帰テスト。
        widget = ReagentTableWidget()
        widget.add_column(ReagentColumn(name="Base", fw=458.27, weight_mg=200))
        widget.add_column(ReagentColumn(name="DMAP", fw=122.17, target_eq=6.0))
        widget._rebuild()
        widget._rebuild()
        widget._rebuild()

        labels = widget._table.viewport().findChildren(QLabel)
        names = [label.text() for label in labels if label.text() in ("Base", "DMAP")]
        assert names.count("Base") == 1
        assert names.count("DMAP") == 1
