import pytest

from molweigh.ui import structure_editor
from molweigh.ui.structure_editor import KetcherNotBundledError, StructureEditorDialog


class TestStructureEditorDialogNotBundled:
    def test_raises_when_vendor_dir_missing(self, qapp, monkeypatch, tmp_path):
        monkeypatch.setattr(structure_editor, "_VENDOR_DIR", tmp_path / "does_not_exist")
        with pytest.raises(KetcherNotBundledError):
            StructureEditorDialog()
