from molweigh.core.structure import generate_lineart_data
from molweigh.ui.molecule_lineart_viewer import MoleculeLineArtWebDialog, MoleculeLineArtWebView


class TestMoleculeLineArtWebView:
    def test_constructs_for_simple_molecule(self, qapp):
        data = generate_lineart_data("CCO")
        view = MoleculeLineArtWebView(data)
        assert view._view is not None

    def test_constructs_for_bridged_structure(self, qapp):
        triptycene = "c1ccc2c(c1)C1c3ccccc3C2c2ccccc21"
        data = generate_lineart_data(triptycene)
        view = MoleculeLineArtWebView(data)
        assert view._view is not None


class TestMoleculeLineArtWebDialog:
    def test_constructs_with_view(self, qapp):
        data = generate_lineart_data("CCO")
        dialog = MoleculeLineArtWebDialog(data)
        assert dialog._view is not None
        dialog.reject()
