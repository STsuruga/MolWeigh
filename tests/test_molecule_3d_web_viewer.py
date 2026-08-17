import pytest

from molweigh.core.structure_3d import generate_3d_molblock
from molweigh.ui import molecule_3d_web_viewer
from molweigh.ui.molecule_3d_web_viewer import (
    Molecule3DNotBundledError,
    Molecule3DWebDialog,
    Molecule3DWebView,
)


class TestMolecule3DWebView:
    def test_constructs_and_serves_locally(self, qapp):
        molblock = generate_3d_molblock("CCO")
        view = Molecule3DWebView(molblock)
        assert view._server is not None
        view.shutdown()

    def test_not_bundled_raises(self, qapp, monkeypatch, tmp_path):
        monkeypatch.setattr(molecule_3d_web_viewer, "_VENDOR_DIR", tmp_path / "missing")
        molblock = generate_3d_molblock("CCO")
        with pytest.raises(Molecule3DNotBundledError):
            Molecule3DWebView(molblock)


class TestMolecule3DWebDialog:
    def test_constructs_with_view(self, qapp):
        molblock = generate_3d_molblock("CCO")
        dialog = Molecule3DWebDialog(molblock)
        assert dialog._view is not None
        dialog.reject()
