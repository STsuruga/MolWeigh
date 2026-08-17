from molweigh.core.structure import generate_lineart_data
from molweigh.ui.molecule_lineart_viewer import MoleculeLineArtWebDialog, MoleculeLineArtWebView


class TestMoleculeLineArtWebView:
    def test_constructs_for_simple_molecule(self, qapp):
        data = generate_lineart_data("CCO")
        view = MoleculeLineArtWebView(data)
        assert view._view is not None
        view.shutdown()

    def test_constructs_for_bridged_structure(self, qapp):
        triptycene = "c1ccc2c(c1)C1c3ccccc3C2c2ccccc21"
        data = generate_lineart_data(triptycene)
        view = MoleculeLineArtWebView(data)
        assert view._view is not None
        view.shutdown()


class TestMoleculeLineArtWebDialog:
    def test_constructs_with_view(self, qapp):
        data = generate_lineart_data("CCO")
        dialog = MoleculeLineArtWebDialog(data, "CCO")
        assert dialog._view is not None
        assert dialog.molblock_to_apply is None
        dialog.reject()

    def test_reflect_builds_molblock_from_layout(self, qapp):
        data = generate_lineart_data("CCO")
        dialog = MoleculeLineArtWebDialog(data, "CCO")
        layout_json = '[[0.0, 0.0], [1.5, 0.0], [2.2, 1.2]]'

        dialog._on_layout_received(layout_json)  # accept()を内部で呼び、doneでshutdown済み

        assert dialog.molblock_to_apply is not None
        assert "V2000" in dialog.molblock_to_apply
