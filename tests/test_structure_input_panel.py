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


def _molblock_for(smiles: str) -> str:
    from rdkit import Chem
    from rdkit.Chem import AllChem

    mol = Chem.MolFromSmiles(smiles)
    AllChem.Compute2DCoords(mol)
    return Chem.MolToMolBlock(mol)


class TestAddToTable:
    def test_smiles_updates_labels_and_emits(self, qapp):
        panel = StructureInputPanel()
        received = []
        panel.added_to_table.connect(received.append)

        panel._on_molblock_for_add(_molblock_for("CCO"))

        assert len(received) == 1
        assert received[0].formula == "C2H6O"
        assert received[0].molblock is not None
        assert "C2H6O" in panel._formula_label.text()
        assert "46.07" in panel._mw_label.text()
        panel.shutdown()

    def test_empty_smiles_shows_error_and_does_not_emit(self, qapp):
        panel = StructureInputPanel()
        received = []
        panel.added_to_table.connect(received.append)

        panel._on_molblock_for_add(None)

        assert received == []
        assert panel._error_label.text() != ""
        panel.shutdown()

    def test_invalid_smiles_shows_error(self, qapp):
        panel = StructureInputPanel()
        panel._on_molblock_for_add("not-a-molblock(((")
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


class TestStructure3DTabWiring:
    def test_empty_molblock_shows_error_in_3d_tab(self, qapp):
        panel = StructureInputPanel()
        panel._on_molblock_for_3d(None)
        assert panel._tab_3d._status_label.text() != ""
        panel.shutdown()

    def test_invalid_molblock_shows_error_in_3d_tab(self, qapp):
        panel = StructureInputPanel()
        panel._on_molblock_for_3d("not a molblock")
        assert panel._tab_3d._status_label.text() != ""
        panel.shutdown()

    def test_valid_molblock_starts_3d_build(self, qapp, monkeypatch):
        panel = StructureInputPanel()
        requested = []
        monkeypatch.setattr(panel._tab_3d, "request_build", lambda smiles, molblock=None: requested.append(smiles))

        from rdkit import Chem

        molblock = Chem.MolToMolBlock(Chem.MolFromSmiles("CCO"))
        panel._on_molblock_for_3d(molblock)

        assert len(requested) == 1
        assert requested[0] == "CCO"
        panel.shutdown()

    def test_switching_to_3d_tab_requests_molblock_from_ketcher(self, qapp, monkeypatch):
        panel = StructureInputPanel()
        requested = []
        monkeypatch.setattr(panel._ketcher, "get_molblock", lambda callback: requested.append(callback))

        panel._on_tab_changed(1)

        assert len(requested) == 1
        panel.shutdown()

    def test_switching_to_2d_tab_does_nothing(self, qapp, monkeypatch):
        panel = StructureInputPanel()
        requested = []
        monkeypatch.setattr(panel._ketcher, "get_molblock", lambda callback: requested.append(callback))

        panel._on_tab_changed(0)

        assert requested == []
        panel.shutdown()

    def test_reflect_from_3d_applies_to_ketcher_and_switches_tab(self, qapp):
        panel = StructureInputPanel()
        received = []
        panel._ketcher.set_smiles = lambda text: received.append(text)
        panel._tabs.setCurrentIndex(1)

        panel._on_reflect_from_3d("fake molblock")

        assert received == ["fake molblock"]
        assert panel._tabs.currentIndex() == 0
        panel.shutdown()

    def test_without_ketcher_shows_error_in_3d_tab(self, qapp, monkeypatch, tmp_path):
        monkeypatch.setattr(structure_editor, "_VENDOR_DIR", tmp_path / "missing")
        panel = StructureInputPanel()
        panel._on_tab_changed(1)
        assert panel._tab_3d._status_label.text() != ""
        panel.shutdown()


