import pytest

from molweigh.ui import structure_editor
from molweigh.ui.structure_input_panel import StructureInputPanel


class TestInitialState:
    def test_ketcher_is_created_immediately(self, qapp):
        panel = StructureInputPanel()
        assert panel._ketcher is not None
        panel.shutdown()

    def test_ketcher_not_bundled_falls_back_gracefully(self, qapp, monkeypatch, tmp_path):
        monkeypatch.setattr(structure_editor, "_VENDOR_DIR", tmp_path / "missing")
        panel = StructureInputPanel()
        assert panel._ketcher is None


class TestCalculate:
    def test_calculate_updates_labels_without_emitting(self, qapp):
        panel = StructureInputPanel()
        received = []
        panel.added_to_table.connect(received.append)

        panel._on_smiles_for_calculate("CCO")

        assert "C2H6O" in panel._formula_label.text()
        assert "46.07" in panel._mw_label.text()
        assert received == []
        panel.shutdown()

    def test_calculate_without_ketcher_shows_error(self, qapp, monkeypatch, tmp_path):
        monkeypatch.setattr(structure_editor, "_VENDOR_DIR", tmp_path / "missing")
        panel = StructureInputPanel()
        panel._on_calculate()
        assert panel._error_label.text() != ""

    def test_empty_smiles_shows_error(self, qapp):
        panel = StructureInputPanel()
        panel._on_smiles_for_calculate(None)
        assert panel._error_label.text() != ""
        panel.shutdown()

    def test_invalid_smiles_shows_error(self, qapp):
        panel = StructureInputPanel()
        panel._on_smiles_for_calculate("not-a-smiles(((")
        assert panel._error_label.text() != ""
        panel.shutdown()


class TestAddToTable:
    def test_smiles_updates_labels_and_emits(self, qapp):
        panel = StructureInputPanel()
        received = []
        panel.added_to_table.connect(received.append)

        panel._on_smiles_for_add("CCO")

        assert len(received) == 1
        assert received[0].formula == "C2H6O"
        assert "C2H6O" in panel._formula_label.text()
        assert "46.07" in panel._mw_label.text()
        panel.shutdown()

    def test_empty_smiles_shows_error_and_does_not_emit(self, qapp):
        panel = StructureInputPanel()
        received = []
        panel.added_to_table.connect(received.append)

        panel._on_smiles_for_add(None)

        assert received == []
        assert panel._error_label.text() != ""
        panel.shutdown()

    def test_invalid_smiles_shows_error(self, qapp):
        panel = StructureInputPanel()
        panel._on_smiles_for_add("not-a-smiles(((")
        assert panel._error_label.text() != ""
        panel.shutdown()


class TestShutdown:
    def test_shutdown_without_ketcher_does_not_raise(self, qapp, monkeypatch, tmp_path):
        monkeypatch.setattr(structure_editor, "_VENDOR_DIR", tmp_path / "missing")
        panel = StructureInputPanel()
        panel.shutdown()

    def test_shutdown_stops_ketcher_server(self, qapp):
        panel = StructureInputPanel()
        panel.shutdown()


class TestPreview3D:
    def test_empty_smiles_shows_error(self, qapp):
        panel = StructureInputPanel()
        panel._on_smiles_for_3d(None)
        assert panel._error_label.text() != ""
        panel.shutdown()

    def test_invalid_smiles_shows_error(self, qapp):
        panel = StructureInputPanel()
        panel._on_smiles_for_3d("not-a-smiles(((")
        assert panel._error_label.text() != ""
        panel.shutdown()

    def test_valid_smiles_opens_dialog(self, qapp, monkeypatch):
        panel = StructureInputPanel()
        opened = []
        monkeypatch.setattr(
            "molweigh.ui.structure_input_panel.MoleculeLineArtWebDialog",
            lambda data, smiles, parent: opened.append((data, smiles)) or _FakeDialog(),
        )

        panel._on_smiles_for_3d("CCO")

        assert len(opened) == 1
        assert len(opened[0][0].atoms) == 3
        assert opened[0][1] == "CCO"
        assert panel._error_label.text() == ""
        panel.shutdown()

    def test_reflect_result_is_applied_to_ketcher(self, qapp, monkeypatch):
        panel = StructureInputPanel()
        monkeypatch.setattr(
            "molweigh.ui.structure_input_panel.MoleculeLineArtWebDialog",
            lambda data, smiles, parent: _FakeDialog(molblock_to_apply="fake molblock"),
        )
        received = []
        monkeypatch.setattr(panel._ketcher, "set_smiles", lambda text: received.append(text))

        panel._on_smiles_for_3d("CCO")

        assert received == ["fake molblock"]
        panel.shutdown()

    def test_without_ketcher_shows_error(self, qapp, monkeypatch, tmp_path):
        monkeypatch.setattr(structure_editor, "_VENDOR_DIR", tmp_path / "missing")
        panel = StructureInputPanel()
        panel._on_preview_3d()
        assert panel._error_label.text() != ""


class TestRealign:
    def test_empty_smiles_shows_error(self, qapp):
        panel = StructureInputPanel()
        panel._on_smiles_for_realign(None)
        assert panel._error_label.text() != ""
        panel.shutdown()

    def test_invalid_smiles_shows_error(self, qapp):
        panel = StructureInputPanel()
        panel._on_smiles_for_realign("not-a-smiles(((")
        assert panel._error_label.text() != ""
        panel.shutdown()

    def test_non_bridged_shows_not_needed_message(self, qapp):
        panel = StructureInputPanel()
        panel._on_smiles_for_realign("CCO")
        assert panel._error_label.text() != ""
        panel.shutdown()

    def test_bridged_smiles_loads_molblock_into_ketcher(self, qapp, monkeypatch):
        panel = StructureInputPanel()
        received = []
        monkeypatch.setattr(panel._ketcher, "set_smiles", lambda text: received.append(text))

        panel._on_smiles_for_realign("c1ccc2c(c1)C1c3ccccc3C2c2ccccc21")

        assert len(received) == 1
        assert "V2000" in received[0]
        assert panel._error_label.text() == ""
        panel.shutdown()

    def test_without_ketcher_shows_error(self, qapp, monkeypatch, tmp_path):
        monkeypatch.setattr(structure_editor, "_VENDOR_DIR", tmp_path / "missing")
        panel = StructureInputPanel()
        panel._on_realign()
        assert panel._error_label.text() != ""


class _FakeDialog:
    def __init__(self, molblock_to_apply=None):
        self.molblock_to_apply = molblock_to_apply

    def exec(self):
        return None
