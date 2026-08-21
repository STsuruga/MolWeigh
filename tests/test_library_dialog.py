import sqlite3

import pytest
from PySide6.QtWidgets import QMessageBox

from molweigh.core import lineart_render
from molweigh.db import library_repo, schema
from molweigh.db.library_repo import LibraryEntry
from molweigh.ui.library_dialog import LibraryDialog, LibraryGridWidget, _LibraryCard


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


def _cards(grid: LibraryGridWidget) -> list[_LibraryCard]:
    return [grid._grid.itemAt(i).widget() for i in range(grid._grid.count())]


class TestRefresh:
    def test_lists_all_entries_when_no_search(self, qapp, conn):
        _seed(conn, name="Zinc chloride")
        _seed(conn, name="Acetic acid")
        grid = LibraryGridWidget(conn)
        assert grid._grid.count() == 2

    def test_filters_by_search_text(self, qapp, conn):
        _seed(conn, name="DMAP")
        _seed(conn, name="Triethylamine", formula="C6H15N")
        grid = LibraryGridWidget(conn)
        grid._search_input.setText("DMA")
        cards = _cards(grid)
        assert len(cards) == 1
        assert cards[0]._entry.name == "DMAP"

    def test_refresh_clears_previous_cards(self, qapp, conn):
        _seed(conn, name="DMAP")
        grid = LibraryGridWidget(conn)
        assert grid._grid.count() == 1
        grid._search_input.setText("no-such-compound")
        assert grid._grid.count() == 0


class TestCardContent:
    def test_card_shows_core_fields(self, qapp, conn):
        _seed(
            conn, name="DMAP", formula="C7H10N2", cas_number="1122-58-3",
            molecular_weight=122.17, density=1.02,
        )
        grid = LibraryGridWidget(conn)
        card = _cards(grid)[0]
        assert card._entry.name == "DMAP"
        assert card._entry.cas_number == "1122-58-3"
        assert card._entry.formula == "C7H10N2"
        assert card._entry.density == pytest.approx(1.02)

    def test_card_handles_missing_optional_fields(self, qapp, conn):
        _seed(conn, name="Unknown", formula=None, cas_number=None, density=None)
        grid = LibraryGridWidget(conn)
        card = _cards(grid)[0]
        assert card._entry.formula is None
        assert card._entry.density is None


class TestAdd:
    def test_add_emits_entry_and_increments_use_count(self, qapp, conn):
        entry_id = _seed(conn)
        grid = LibraryGridWidget(conn)
        card = _cards(grid)[0]

        received = []
        grid.entry_selected.connect(received.append)
        card._add_button.click()

        assert len(received) == 1
        assert received[0].id == entry_id
        assert library_repo.get(conn, entry_id).use_count == 1

    def test_add_does_not_reset_grid_and_can_add_again(self, qapp, conn):
        _seed(conn, name="First")
        _seed(conn, name="Second")
        grid = LibraryGridWidget(conn)

        received = []
        grid.entry_selected.connect(received.append)
        for card in _cards(grid):
            card._add_button.click()

        assert len(received) == 2


class TestDelete:
    def test_confirmed_delete_removes_entry(self, qapp, conn, monkeypatch):
        entry_id = _seed(conn)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

        grid = LibraryGridWidget(conn)
        _cards(grid)[0]._delete_button.click()

        assert library_repo.get(conn, entry_id) is None
        assert grid._grid.count() == 0

    def test_declined_delete_keeps_entry(self, qapp, conn, monkeypatch):
        entry_id = _seed(conn)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)

        grid = LibraryGridWidget(conn)
        _cards(grid)[0]._delete_button.click()

        assert library_repo.get(conn, entry_id) is not None


class TestRefreshPreview:
    def test_click_regenerates_and_persists_preview_svg(self, qapp, conn):
        # renderer_versionを現行に合わせておく(食い違うとrefresh()時点で自動焼き直しが
        # 起き、このテストが検証したい「手動クリック」経路と切り分けられなくなるため)。
        entry_id = _seed(
            conn, name="Ethanol", smiles="CCO", renderer_version=lineart_render.CURRENT_RENDERER_VERSION
        )
        grid = LibraryGridWidget(conn)
        assert library_repo.get(conn, entry_id).preview_svg is None

        _cards(grid)[0]._refresh_button.click()

        saved = library_repo.get(conn, entry_id)
        assert saved.preview_svg is not None
        assert saved.preview_svg.startswith("<svg")

    def test_no_smiles_does_nothing(self, qapp, conn):
        entry_id = _seed(conn, name="No structure", smiles=None)
        grid = LibraryGridWidget(conn)

        _cards(grid)[0]._refresh_button.click()

        assert library_repo.get(conn, entry_id).preview_svg is None


class TestAutoRebakeStalePreview:
    """Stage 3: レンダラーのバージョンが古い保存済みpreview_svgを表示時に自動で焼き直す。"""

    def test_stale_renderer_version_is_rebaked_and_persisted_on_refresh(self, qapp, conn):
        entry_id = _seed(conn, name="Ethanol", smiles="CCO", renderer_version=0)
        assert library_repo.get(conn, entry_id).preview_svg is None

        LibraryGridWidget(conn)  # コンストラクタがrefresh()を呼ぶ

        saved = library_repo.get(conn, entry_id)
        assert saved.preview_svg is not None
        assert saved.renderer_version == lineart_render.CURRENT_RENDERER_VERSION

    def test_current_renderer_version_is_not_rebaked(self, qapp, conn):
        entry_id = _seed(
            conn, name="Ethanol", smiles="CCO", renderer_version=lineart_render.CURRENT_RENDERER_VERSION
        )
        LibraryGridWidget(conn)
        assert library_repo.get(conn, entry_id).preview_svg is None

    def test_no_smiles_is_left_untouched(self, qapp, conn):
        entry_id = _seed(conn, name="No structure", smiles=None, renderer_version=0)
        LibraryGridWidget(conn)
        saved = library_repo.get(conn, entry_id)
        assert saved.preview_svg is None
        assert saved.renderer_version == 0


class TestAddNewRequested:
    def test_button_click_emits_signal(self, qapp, conn):
        grid = LibraryGridWidget(conn)
        received = []
        grid.add_new_requested.connect(lambda: received.append(True))
        grid._add_new_button.click()
        assert received == [True]


class TestLibraryDialogWrapsGrid:
    def test_entry_selected_forwards_from_grid(self, qapp, conn):
        entry_id = _seed(conn)
        dialog = LibraryDialog(conn)
        received = []
        dialog.entry_selected.connect(received.append)

        card = _cards(dialog._grid_widget)[0]
        card._add_button.click()

        assert len(received) == 1
        assert received[0].id == entry_id

    def test_refresh_delegates_to_grid(self, qapp, conn):
        dialog = LibraryDialog(conn)
        assert dialog._grid_widget._grid.count() == 0
        _seed(conn, name="New")
        dialog.refresh()
        assert dialog._grid_widget._grid.count() == 1
