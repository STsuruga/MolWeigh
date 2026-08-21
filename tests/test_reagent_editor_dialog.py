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


def _molblock_for(smiles: str) -> str:
    from rdkit import Chem
    from rdkit.Chem import AllChem

    mol = Chem.MolFromSmiles(smiles)
    AllChem.Compute2DCoords(mol)
    return Chem.MolToMolBlock(mol)


@pytest.fixture
def dialog(qapp, conn):
    d = ReagentEditorDialog(conn)
    yield d
    if d._ketcher is not None:
        d._ketcher.shutdown()
    d._tab_3d.shutdown()


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
        molblock = _molblock_for("CCO")
        dialog._on_molblock_received(molblock)
        assert dialog._formula_input.text() == "C2H6O"
        assert dialog._mw_input.value() == pytest.approx(46.069, rel=1e-4)
        assert dialog._smiles == "CCO"
        assert dialog._molblock == molblock

    def test_empty_smiles_shows_warning(self, dialog, monkeypatch):
        warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))
        dialog._on_molblock_received(None)
        assert warnings
        assert dialog._smiles is None

    def test_invalid_smiles_shows_warning(self, dialog, monkeypatch):
        warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))
        dialog._on_molblock_received("not a molblock")
        assert warnings


class TestStructure3DTabWiring:
    def test_empty_molblock_shows_error_in_3d_tab(self, dialog):
        dialog._on_molblock_for_3d(None)
        assert dialog._tab_3d._status_label.text() != ""

    def test_invalid_molblock_shows_error_in_3d_tab(self, dialog):
        dialog._on_molblock_for_3d("not a molblock")
        assert dialog._tab_3d._status_label.text() != ""

    def test_valid_molblock_starts_3d_build(self, dialog, monkeypatch):
        requested = []
        monkeypatch.setattr(dialog._tab_3d, "request_build", lambda smiles, molblock=None: requested.append(smiles))

        from rdkit import Chem

        molblock = Chem.MolToMolBlock(Chem.MolFromSmiles("CCO"))
        dialog._on_molblock_for_3d(molblock)

        assert requested == ["CCO"]

    def test_switching_to_3d_tab_requests_molblock_from_ketcher(self, dialog, monkeypatch):
        requested = []
        monkeypatch.setattr(dialog._ketcher, "get_molblock", lambda callback: requested.append(callback))
        dialog._on_tab_changed(1)
        assert len(requested) == 1

    def test_reflect_from_3d_applies_to_ketcher_and_switches_tab(self, dialog):
        received = []
        dialog._ketcher.set_smiles = lambda text: received.append(text)
        dialog._tabs.setCurrentIndex(1)

        dialog._on_reflect_from_3d("fake molblock")

        assert received == ["fake molblock"]
        assert dialog._tabs.currentIndex() == 0


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
        dialog._on_molblock_received(_molblock_for("CCO"))
        dialog._name_input.setText("Ethanol")
        dialog._on_save()
        saved = library_repo.get(conn, dialog.library_id)
        assert saved.smiles == "CCO"
        assert saved.molblock is not None

    def test_preview_svg_is_baked_and_persisted_when_structure_drawn(self, dialog, conn):
        dialog._on_molblock_received(_molblock_for("CCO"))
        dialog._name_input.setText("Ethanol")
        dialog._on_save()
        saved = library_repo.get(conn, dialog.library_id)
        assert saved.preview_svg is not None
        assert saved.preview_svg.startswith("<svg")

    def test_preview_svg_is_none_without_structure(self, dialog, conn):
        dialog._name_input.setText("X")
        dialog._mw_input.setValue(100.0)
        dialog._on_save()
        saved = library_repo.get(conn, dialog.library_id)
        assert saved.preview_svg is None
