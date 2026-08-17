from molweigh.ui.calculation_history_panel import CalculationHistoryPanel
from molweigh.ui.reagent_table import ReagentColumn


class TestRecord:
    def test_blank_columns_are_not_recorded(self, qapp):
        panel = CalculationHistoryPanel()
        panel.record([ReagentColumn(), ReagentColumn()])
        assert panel._entries == []
        assert panel._list.isHidden()

    def test_meaningful_change_is_recorded(self, qapp):
        panel = CalculationHistoryPanel()
        panel.record([ReagentColumn(name="Base", fw=100.0)])
        assert len(panel._entries) == 1
        assert not panel._list.isHidden()
        assert panel._list.count() == 1

    def test_identical_consecutive_snapshot_is_not_duplicated(self, qapp):
        panel = CalculationHistoryPanel()
        columns = [ReagentColumn(name="Base", fw=100.0)]
        panel.record(columns)
        panel.record([ReagentColumn(name="Base", fw=100.0)])
        assert len(panel._entries) == 1

    def test_changed_snapshot_adds_new_entry_at_top(self, qapp):
        panel = CalculationHistoryPanel()
        panel.record([ReagentColumn(name="Base", fw=100.0)])
        panel.record([ReagentColumn(name="Base", fw=200.0)])
        assert len(panel._entries) == 2
        assert panel._entries[0].columns[0].fw == 200.0

    def test_caps_entries_at_max(self, qapp):
        panel = CalculationHistoryPanel()
        for i in range(35):
            panel.record([ReagentColumn(name="Base", fw=float(i))])
        assert len(panel._entries) == 30
        assert panel._entries[0].columns[0].fw == 34.0

    def test_recording_does_not_mutate_original_columns(self, qapp):
        panel = CalculationHistoryPanel()
        columns = [ReagentColumn(name="Base", fw=100.0)]
        panel.record(columns)
        columns[0].fw = 999.0
        assert panel._entries[0].columns[0].fw == 100.0


class TestRestore:
    def test_double_click_emits_restore_requested_with_copy(self, qapp):
        panel = CalculationHistoryPanel()
        panel.record([ReagentColumn(name="Base", fw=100.0)])
        received = []
        panel.restore_requested.connect(received.append)

        item = panel._list.item(0)
        panel._on_item_double_clicked(item)

        assert len(received) == 1
        assert received[0][0].name == "Base"
        assert received[0][0].fw == 100.0
        # 履歴側の内部コピーとは独立していること
        received[0][0].fw = 1.0
        assert panel._entries[0].columns[0].fw == 100.0
