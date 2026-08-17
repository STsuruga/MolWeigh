import sqlite3

import pytest
from PySide6.QtWidgets import QDialog, QMessageBox

from molweigh.db import library_repo, schema
from molweigh.ui.reagent_editor_dialog import ReagentEditorDialog


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    schema.migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def dialog(qapp, conn):
    d = ReagentEditorDialog(conn)
    yield d
    if d._ketcher is not None:
        d._ketcher.shutdown()


class TestFormulaEntry:
    def test_editing_formula_computes_molecular_weight(self, dialog):
        dialog._formula_input.setText("C6H12O6")
        dialog._on_formula_edited()
        assert dialog._mw_input.value() == pytest.approx(180.156, rel=1e-5)

    def test_invalid_formula_does_not_raise_or_change_mw(self, dialog):
        dialog._mw_input.setValue(42.0)
        dialog._formula_input.setText("NotAFormula123$$")
        dialog._on_formula_edited()
        assert dialog._mw_input.value() == pytest.approx(42.0)

    def test_empty_formula_does_nothing(self, dialog):
        dialog._mw_input.setValue(42.0)
        dialog._formula_input.setText("")
        dialog._on_formula_edited()
        assert dialog._mw_input.value() == pytest.approx(42.0)


class TestStructureEntry:
    def test_smiles_received_fills_formula_and_mw(self, dialog):
        dialog._on_smiles_received("CCO")
        assert dialog._formula_input.text() == "C2H6O"
        assert dialog._mw_input.value() == pytest.approx(46.069, rel=1e-4)
        assert dialog._smiles == "CCO"

    def test_empty_smiles_shows_warning(self, dialog, monkeypatch):
        warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))
        dialog._on_smiles_received(None)
        assert warnings
        assert dialog._smiles is None

    def test_invalid_smiles_shows_warning(self, dialog, monkeypatch):
        warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))
        dialog._on_smiles_received("not-a-smiles(((")
        assert warnings


class TestPreview3D:
    def test_empty_smiles_shows_warning(self, dialog, monkeypatch):
        warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))
        dialog._on_smiles_for_3d(None)
        assert warnings

    def test_invalid_smiles_shows_warning(self, dialog, monkeypatch):
        warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))
        dialog._on_smiles_for_3d("not-a-smiles(((")
        assert warnings

    def test_valid_smiles_opens_dialog(self, dialog, monkeypatch):
        opened = []
        monkeypatch.setattr(
            "molweigh.ui.reagent_editor_dialog.Molecule3DWebDialog",
            lambda molblock, view_data, smiles, parent: opened.append((molblock, view_data, smiles))
            or _FakeDialog(),
        )
        dialog._on_smiles_for_3d("CCO")
        assert len(opened) == 1
        assert "V2000" in opened[0][0]
        assert len(opened[0][1].atoms) == 3
        assert opened[0][2] == "CCO"

    def test_reflect_result_is_applied_to_ketcher(self, dialog, monkeypatch):
        monkeypatch.setattr(
            "molweigh.ui.reagent_editor_dialog.Molecule3DWebDialog",
            lambda molblock, view_data, smiles, parent: _FakeDialog(molblock_to_apply="fake molblock"),
        )
        received = []
        monkeypatch.setattr(dialog._ketcher, "set_smiles", lambda text: received.append(text))
        dialog._on_smiles_for_3d("CCO")
        assert received == ["fake molblock"]

    def test_not_bundled_shows_warning(self, dialog, monkeypatch):
        from molweigh.ui.molecule_3d_web_viewer import Molecule3DNotBundledError

        warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))
        monkeypatch.setattr(
            "molweigh.ui.reagent_editor_dialog.Molecule3DWebDialog",
            lambda molblock, view_data, smiles, parent: (_ for _ in ()).throw(
                Molecule3DNotBundledError("not bundled")
            ),
        )
        dialog._on_smiles_for_3d("CCO")
        assert warnings


class TestRealign:
    def test_empty_smiles_shows_warning(self, dialog, monkeypatch):
        warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))
        dialog._on_smiles_for_realign(None)
        assert warnings

    def test_invalid_smiles_shows_warning(self, dialog, monkeypatch):
        warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))
        dialog._on_smiles_for_realign("not-a-smiles(((")
        assert warnings

    def test_non_bridged_shows_information(self, dialog, monkeypatch):
        infos = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: infos.append(a))
        dialog._on_smiles_for_realign("CCO")
        assert infos

    def test_bridged_smiles_loads_molblock_into_ketcher(self, dialog, monkeypatch):
        received = []
        monkeypatch.setattr(dialog._ketcher, "set_smiles", lambda text: received.append(text))
        dialog._on_smiles_for_realign("c1ccc2c(c1)C1c3ccccc3C2c2ccccc21")
        assert len(received) == 1
        assert "V2000" in received[0]


class _FakeDialog:
    def __init__(self, molblock_to_apply=None):
        self.molblock_to_apply = molblock_to_apply

    def exec(self):
        return None


class TestPreviewUpdates:
    def test_preview_reflects_name_and_formula(self, dialog):
        dialog._name_input.setText("グルコース")
        dialog._formula_input.setText("C6H12O6")
        dialog._on_formula_edited()
        dialog._update_preview()

        assert dialog._preview_name.text() == "グルコース"
        formula_value = dialog._preview_formula_row.layout().itemAt(2).widget()
        assert formula_value.text() == "C6H12O6"

    def test_preview_shows_placeholder_name_when_empty(self, dialog):
        dialog._update_preview()
        assert dialog._preview_name.text() == "(未設定)"


class TestSave:
    def test_missing_name_shows_warning_and_does_not_save(self, dialog, monkeypatch, conn):
        warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))
        dialog._formula_input.setText("C6H12O6")
        dialog._on_formula_edited()

        dialog._on_save()

        assert warnings
        assert library_repo.list_all(conn) == []

    def test_missing_molecular_weight_shows_warning(self, dialog, monkeypatch, conn):
        warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))
        dialog._name_input.setText("Unknown")

        dialog._on_save()

        assert warnings
        assert library_repo.list_all(conn) == []

    def test_valid_input_creates_library_entry_and_accepts(self, dialog, conn):
        dialog._name_input.setText("グルコース")
        dialog._cas_input.setText("50-99-7")
        dialog._formula_input.setText("C6H12O6")
        dialog._on_formula_edited()

        dialog._on_save()

        assert dialog.library_id is not None
        saved = library_repo.get(conn, dialog.library_id)
        assert saved.name == "グルコース"
        assert saved.cas_number == "50-99-7"
        assert saved.formula == "C6H12O6"
        assert saved.molecular_weight == pytest.approx(180.156, rel=1e-5)
        assert saved.source == "manual"

    def test_density_zero_is_saved_as_none(self, dialog, conn):
        dialog._name_input.setText("X")
        dialog._mw_input.setValue(100.0)
        dialog._on_save()
        saved = library_repo.get(conn, dialog.library_id)
        assert saved.density is None

    def test_smiles_is_persisted_when_drawn(self, dialog, conn):
        dialog._on_smiles_received("CCO")
        dialog._name_input.setText("Ethanol")
        dialog._on_save()
        saved = library_repo.get(conn, dialog.library_id)
        assert saved.smiles == "CCO"
