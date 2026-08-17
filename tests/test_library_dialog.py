import sqlite3

import pytest
from PySide6.QtWidgets import QMessageBox

from molweigh.db import library_repo, schema
from molweigh.db.library_repo import LibraryEntry
from molweigh.ui.library_dialog import LibraryDialog, _LibraryCard


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


def _cards(dialog: LibraryDialog) -> list[_LibraryCard]:
    return [dialog._grid.itemAt(i).widget() for i in range(dialog._grid.count())]


class TestRefresh:
    def test_lists_all_entries_when_no_search(self, qapp, conn):
        _seed(conn, name="Zinc chloride")
        _seed(conn, name="Acetic acid")
        dialog = LibraryDialog(conn)
        assert dialog._grid.count() == 2

    def test_filters_by_search_text(self, qapp, conn):
        _seed(conn, name="DMAP")
        _seed(conn, name="Triethylamine", formula="C6H15N")
        dialog = LibraryDialog(conn)
        dialog._search_input.setText("DMA")
        cards = _cards(dialog)
        assert len(cards) == 1
        assert cards[0]._entry.name == "DMAP"

    def test_refresh_clears_previous_cards(self, qapp, conn):
        _seed(conn, name="DMAP")
        dialog = LibraryDialog(conn)
        assert dialog._grid.count() == 1
        dialog._search_input.setText("no-such-compound")
        assert dialog._grid.count() == 0


class TestCardContent:
    def test_card_shows_core_fields(self, qapp, conn):
        _seed(
            conn, name="DMAP", formula="C7H10N2", cas_number="1122-58-3",
            molecular_weight=122.17, density=1.02,
        )
        dialog = LibraryDialog(conn)
        card = _cards(dialog)[0]
        assert card._entry.name == "DMAP"
        assert card._entry.cas_number == "1122-58-3"
        assert card._entry.formula == "C7H10N2"
        assert card._entry.density == pytest.approx(1.02)

    def test_card_handles_missing_optional_fields(self, qapp, conn):
        _seed(conn, name="Unknown", formula=None, cas_number=None, density=None)
        dialog = LibraryDialog(conn)
        card = _cards(dialog)[0]
        assert card._entry.formula is None
        assert card._entry.density is None


class TestAdd:
    def test_add_emits_entry_and_increments_use_count(self, qapp, conn):
        entry_id = _seed(conn)
        dialog = LibraryDialog(conn)
        card = _cards(dialog)[0]

        received = []
        dialog.entry_selected.connect(received.append)
        card._add_button.click()

        assert len(received) == 1
        assert received[0].id == entry_id
        assert library_repo.get(conn, entry_id).use_count == 1

    def test_add_does_not_close_dialog_and_can_add_again(self, qapp, conn):
        _seed(conn, name="First")
        _seed(conn, name="Second")
        dialog = LibraryDialog(conn)

        received = []
        dialog.entry_selected.connect(received.append)
        for card in _cards(dialog):
            card._add_button.click()

        assert len(received) == 2


class TestDelete:
    def test_confirmed_delete_removes_entry(self, qapp, conn, monkeypatch):
        entry_id = _seed(conn)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

        dialog = LibraryDialog(conn)
        _cards(dialog)[0]._delete_button.click()

        assert library_repo.get(conn, entry_id) is None
        assert dialog._grid.count() == 0

    def test_declined_delete_keeps_entry(self, qapp, conn, monkeypatch):
        entry_id = _seed(conn)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)

        dialog = LibraryDialog(conn)
        _cards(dialog)[0]._delete_button.click()

        assert library_repo.get(conn, entry_id) is not None
