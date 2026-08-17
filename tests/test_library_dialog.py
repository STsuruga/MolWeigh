import sqlite3

import pytest
from PySide6.QtWidgets import QMessageBox

from molweigh.db import library_repo, schema
from molweigh.db.library_repo import LibraryEntry
from molweigh.ui.library_dialog import LibraryDialog


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    schema.migrate(connection)
    yield connection
    connection.close()


def _seed(conn, **overrides):
    defaults = dict(id=None, name="DMAP", molecular_weight=122.17, source="pubchem", formula="C7H10N2")
    defaults.update(overrides)
    return library_repo.create(conn, LibraryEntry(**defaults))


class TestRefresh:
    def test_lists_all_entries_when_no_search(self, qapp, conn):
        _seed(conn, name="Zinc chloride")
        _seed(conn, name="Acetic acid")
        dialog = LibraryDialog(conn)
        assert dialog._list.count() == 2

    def test_filters_by_search_text(self, qapp, conn):
        _seed(conn, name="DMAP")
        _seed(conn, name="Triethylamine", formula="C6H15N")
        dialog = LibraryDialog(conn)
        dialog._search_input.setText("DMA")
        assert dialog._list.count() == 1
        assert "DMAP" in dialog._list.item(0).text()


class TestSelect:
    def test_select_emits_entry_and_increments_use_count(self, qapp, conn):
        entry_id = _seed(conn)
        dialog = LibraryDialog(conn)
        dialog._list.setCurrentRow(0)

        received = []
        dialog.entry_selected.connect(received.append)
        dialog._on_select()

        assert len(received) == 1
        assert received[0].id == entry_id
        assert library_repo.get(conn, entry_id).use_count == 1

    def test_select_without_selection_does_nothing(self, qapp, conn):
        dialog = LibraryDialog(conn)
        received = []
        dialog.entry_selected.connect(received.append)
        dialog._on_select()
        assert received == []

    def test_select_does_not_close_dialog_and_can_select_again(self, qapp, conn):
        _seed(conn, name="First")
        _seed(conn, name="Second")
        dialog = LibraryDialog(conn)

        received = []
        dialog.entry_selected.connect(received.append)

        dialog._list.setCurrentRow(0)
        dialog._on_select()
        dialog._list.setCurrentRow(1)
        dialog._on_select()

        assert len(received) == 2


class TestDelete:
    def test_confirmed_delete_removes_entry(self, qapp, conn, monkeypatch):
        entry_id = _seed(conn)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

        dialog = LibraryDialog(conn)
        dialog._list.setCurrentRow(0)
        dialog._on_delete()

        assert library_repo.get(conn, entry_id) is None
        assert dialog._list.count() == 0

    def test_declined_delete_keeps_entry(self, qapp, conn, monkeypatch):
        entry_id = _seed(conn)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)

        dialog = LibraryDialog(conn)
        dialog._list.setCurrentRow(0)
        dialog._on_delete()

        assert library_repo.get(conn, entry_id) is not None
