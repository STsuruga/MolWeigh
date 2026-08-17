import pytest

from molweigh.core.structure import generate_3d_view
from molweigh.ui import molecule_3d_web_viewer
from molweigh.ui.molecule_3d_web_viewer import (
    Molecule3DNotBundledError,
    Molecule3DWebDialog,
    Molecule3DWebView,
)


class TestMolecule3DWebView:
    def test_constructs_and_serves_locally(self, qapp):
        molblock, view_data = generate_3d_view("CCO")
        view = Molecule3DWebView(molblock, view_data)
        assert view._server is not None
        view.shutdown()

    def test_not_bundled_raises(self, qapp, monkeypatch, tmp_path):
        monkeypatch.setattr(molecule_3d_web_viewer, "_VENDOR_DIR", tmp_path / "missing")
        molblock, view_data = generate_3d_view("CCO")
        with pytest.raises(Molecule3DNotBundledError):
            Molecule3DWebView(molblock, view_data)


class TestMolecule3DWebDialog:
    def test_constructs_with_view(self, qapp):
        molblock, view_data = generate_3d_view("CCO")
        dialog = Molecule3DWebDialog(molblock, view_data, "CCO")
        assert dialog._view is not None
        assert dialog.molblock_to_apply is None
        dialog.reject()

    def test_reflect_builds_molblock_from_layout(self, qapp):
        molblock, view_data = generate_3d_view("CCO")
        dialog = Molecule3DWebDialog(molblock, view_data, "CCO")
        layout_json = "[[0.0, 0.0], [1.5, 0.0], [2.2, 1.2]]"

        dialog._on_layout_received(layout_json)  # accept()を内部で呼び、doneでshutdown済み

        assert dialog.molblock_to_apply is not None
        assert "V2000" in dialog.molblock_to_apply
