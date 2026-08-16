import sqlite3

import pytest
from PySide6.QtWidgets import QDialog, QMessageBox

from molweigh.core.compound_source import CompoundInfo
from molweigh.core.pubchem_client import PubChemError
from molweigh.db import schema
from molweigh.ui import compound_search
from molweigh.ui.compound_search import CompoundSearchBar, ManualCompoundDialog


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    schema.migrate(connection)
    yield connection
    connection.close()


SAMPLE_INFO = CompoundInfo(
    name="DMAP", formula="C7H10N2", molecular_weight=122.17,
    density=None, smiles=None, source="library", library_id=1,
)


class TestCompoundSearchBarResolved:
    def test_hit_emits_signal_and_clears_input(self, qapp, conn, monkeypatch):
        monkeypatch.setattr(
            compound_search.compound_source, "resolve_compound", lambda c, q: SAMPLE_INFO
        )
        bar = CompoundSearchBar(conn)
        bar._input.setText("DMAP")
        received = []
        bar.compound_resolved.connect(received.append)

        bar._on_search()

        assert received == [SAMPLE_INFO]
        assert bar._input.text() == ""

    def test_empty_query_does_nothing(self, qapp, conn, monkeypatch):
        called = []
        monkeypatch.setattr(
            compound_search.compound_source,
            "resolve_compound",
            lambda c, q: called.append(q) or SAMPLE_INFO,
        )
        bar = CompoundSearchBar(conn)
        bar._input.setText("   ")
        bar._on_search()
        assert called == []


class TestCompoundSearchBarUnresolved:
    def test_no_hit_opens_manual_dialog_and_emits_on_accept(self, qapp, conn, monkeypatch):
        monkeypatch.setattr(compound_search.compound_source, "resolve_compound", lambda c, q: None)

        formula_info = CompoundInfo(
            name="C6H12O6", formula="C6H12O6", molecular_weight=180.156,
            density=None, smiles=None, source="formula_parser",
        )

        def fake_exec(self):
            self.result_info = formula_info
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(ManualCompoundDialog, "exec", fake_exec)

        bar = CompoundSearchBar(conn)
        bar._input.setText("unknown-xyz")
        received = []
        bar.compound_resolved.connect(received.append)

        bar._on_search()

        assert received == [formula_info]
        assert bar._input.text() == ""

    def test_dialog_rejected_emits_nothing(self, qapp, conn, monkeypatch):
        monkeypatch.setattr(compound_search.compound_source, "resolve_compound", lambda c, q: None)
        monkeypatch.setattr(ManualCompoundDialog, "exec", lambda self: QDialog.DialogCode.Rejected)

        bar = CompoundSearchBar(conn)
        bar._input.setText("unknown-xyz")
        received = []
        bar.compound_resolved.connect(received.append)

        bar._on_search()

        assert received == []


class TestCompoundSearchBarPubChemError:
    def test_pubchem_error_shows_warning_and_emits_nothing(self, qapp, conn, monkeypatch):
        def raise_error(c, q):
            raise PubChemError("network down")

        monkeypatch.setattr(compound_search.compound_source, "resolve_compound", raise_error)
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

        bar = CompoundSearchBar(conn)
        bar._input.setText("aspirin")
        received = []
        bar.compound_resolved.connect(received.append)

        bar._on_search()

        assert received == []


class TestManualCompoundDialog:
    def test_accept_formula_mode(self, qapp):
        dialog = ManualCompoundDialog("C6H12O6")
        dialog._mode.setCurrentIndex(0)
        dialog._input.setText("C6H12O6")
        dialog._on_accept()
        assert dialog.result_info.source == "formula_parser"
        assert dialog.result_info.molecular_weight == pytest.approx(180.156, rel=1e-5)

    def test_accept_smiles_mode(self, qapp):
        dialog = ManualCompoundDialog("CCO")
        dialog._mode.setCurrentIndex(1)
        dialog._input.setText("CCO")
        dialog._on_accept()
        assert dialog.result_info.source == "smiles"
        assert dialog.result_info.formula == "C2H6O"

    def test_invalid_formula_shows_error_and_does_not_set_result(self, qapp):
        dialog = ManualCompoundDialog("bad")
        dialog._mode.setCurrentIndex(0)
        dialog._input.setText("NotAFormula123$$")
        dialog._on_accept()
        assert dialog.result_info is None
        assert not dialog._error_label.isHidden()

    def test_empty_input_shows_error(self, qapp):
        dialog = ManualCompoundDialog("x")
        dialog._input.setText("")
        dialog._on_accept()
        assert dialog.result_info is None
        assert not dialog._error_label.isHidden()


class TestManualCompoundDialogDrawStructure:
    def test_ketcher_not_bundled_shows_warning(self, qapp, monkeypatch):
        def raise_not_bundled(parent=None):
            raise compound_search.KetcherNotBundledError("not bundled")

        monkeypatch.setattr(compound_search, "StructureEditorDialog", raise_not_bundled)
        warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))

        dialog = ManualCompoundDialog("x")
        dialog._on_draw_structure()

        assert warnings

    def test_accepted_drawing_fills_smiles_mode(self, qapp, monkeypatch):
        class FakeEditor:
            def __init__(self, parent=None):
                self.smiles = "CCO"

            def exec(self):
                return QDialog.DialogCode.Accepted

        monkeypatch.setattr(compound_search, "StructureEditorDialog", FakeEditor)

        dialog = ManualCompoundDialog("x")
        dialog._on_draw_structure()

        assert dialog._mode.currentIndex() == 1
        assert dialog._input.text() == "CCO"

    def test_cancelled_drawing_leaves_input_unchanged(self, qapp, monkeypatch):
        class FakeEditor:
            def __init__(self, parent=None):
                self.smiles = None

            def exec(self):
                return QDialog.DialogCode.Rejected

        monkeypatch.setattr(compound_search, "StructureEditorDialog", FakeEditor)

        dialog = ManualCompoundDialog("x")
        dialog._input.setText("original")
        dialog._on_draw_structure()

        assert dialog._input.text() == "original"
