import pytest

from molweigh.ui import structure_editor
from molweigh.ui.structure_input_panel import StructureInputPanel


class TestInitialState:
    def test_starts_collapsed_without_ketcher(self, qapp):
        panel = StructureInputPanel()
        assert panel._expanded is False
        assert panel._ketcher is None
        assert panel._body.isHidden()


class TestToggle:
    def test_expanding_creates_ketcher(self, qapp):
        panel = StructureInputPanel()
        panel._on_toggle()
        assert panel._expanded is True
        assert panel._ketcher is not None
        assert not panel._body.isHidden()

    def test_collapsing_keeps_ketcher_instance(self, qapp):
        panel = StructureInputPanel()
        panel._on_toggle()
        ketcher = panel._ketcher
        panel._on_toggle()
        assert panel._expanded is False
        assert panel._body.isHidden()
        assert panel._ketcher is ketcher  # 破棄せず使い回す

    def test_reexpanding_does_not_recreate_ketcher(self, qapp):
        panel = StructureInputPanel()
        panel._on_toggle()
        first = panel._ketcher
        panel._on_toggle()
        panel._on_toggle()
        assert panel._ketcher is first

    def test_ketcher_not_bundled_shows_error(self, qapp, monkeypatch, tmp_path):
        monkeypatch.setattr(structure_editor, "_VENDOR_DIR", tmp_path / "missing")
        panel = StructureInputPanel()
        panel._on_toggle()
        assert panel._ketcher is None
        assert not panel._error_label.isHidden()


class TestAddToTable:
    def test_without_expanded_ketcher_shows_error(self, qapp):
        panel = StructureInputPanel()
        received = []
        panel.added_to_table.connect(received.append)
        panel._on_add_to_table()
        assert received == []
        assert not panel._error_label.isHidden()

    def test_smiles_updates_labels_and_emits(self, qapp):
        panel = StructureInputPanel()
        received = []
        panel.added_to_table.connect(received.append)

        panel._on_smiles_for_add("CCO")

        assert len(received) == 1
        assert received[0].formula == "C2H6O"
        assert "C2H6O" in panel._formula_label.text()
        assert "46.07" in panel._mw_label.text()

    def test_empty_smiles_shows_error_and_does_not_emit(self, qapp):
        panel = StructureInputPanel()
        received = []
        panel.added_to_table.connect(received.append)

        panel._on_smiles_for_add(None)

        assert received == []
        assert not panel._error_label.isHidden()

    def test_invalid_smiles_shows_error(self, qapp):
        panel = StructureInputPanel()
        panel._on_smiles_for_add("not-a-smiles(((")
        assert not panel._error_label.isHidden()


class TestShutdown:
    def test_shutdown_without_ketcher_does_not_raise(self, qapp):
        panel = StructureInputPanel()
        panel.shutdown()

    def test_shutdown_stops_ketcher_server(self, qapp):
        panel = StructureInputPanel()
        panel._on_toggle()
        panel.shutdown()
