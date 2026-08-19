import sqlite3

import pytest

from molweigh.db import library_repo, schema
from molweigh.db.library_repo import LibraryEntry


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    schema.migrate(connection)
    yield connection
    connection.close()


def _make_entry(**overrides) -> LibraryEntry:
    defaults = dict(
        id=None,
        name="DMAP",
        molecular_weight=122.17,
        source="pubchem",
        cas_number="1122-58-3",
        formula="C7H10N2",
        density=None,
        smiles="CN(C)c1ccncc1",
    )
    defaults.update(overrides)
    return LibraryEntry(**defaults)


class TestCreateAndGet:
    def test_create_assigns_id(self, conn):
        entry_id = library_repo.create(conn, _make_entry())
        assert entry_id is not None

    def test_get_returns_created_entry(self, conn):
        entry_id = library_repo.create(conn, _make_entry())
        fetched = library_repo.get(conn, entry_id)
        assert fetched.name == "DMAP"
        assert fetched.molecular_weight == pytest.approx(122.17)
        assert fetched.created_at != ""
        assert fetched.updated_at != ""

    def test_get_missing_returns_none(self, conn):
        assert library_repo.get(conn, 9999) is None

    def test_preview_svg_and_render_mode_defaults(self, conn):
        entry_id = library_repo.create(conn, _make_entry())
        fetched = library_repo.get(conn, entry_id)
        assert fetched.preview_svg is None
        assert fetched.render_mode == "auto"

    def test_preview_svg_and_render_mode_persisted(self, conn):
        entry_id = library_repo.create(conn, _make_entry(preview_svg="<svg></svg>", render_mode="solid"))
        fetched = library_repo.get(conn, entry_id)
        assert fetched.preview_svg == "<svg></svg>"
        assert fetched.render_mode == "solid"


class TestListAndSearch:
    def test_list_all_sorted_by_name(self, conn):
        library_repo.create(conn, _make_entry(name="Zinc chloride"))
        library_repo.create(conn, _make_entry(name="Acetic acid"))
        result = library_repo.list_all(conn)
        assert [e.name for e in result] == ["Acetic acid", "Zinc chloride"]

    def test_list_all_ordered_by_use_count(self, conn):
        low_id = library_repo.create(conn, _make_entry(name="Low use"))
        high_id = library_repo.create(conn, _make_entry(name="High use"))
        library_repo.increment_use_count(conn, high_id)
        library_repo.increment_use_count(conn, high_id)
        library_repo.increment_use_count(conn, low_id)
        result = library_repo.list_all(conn, order_by_use_count=True)
        assert result[0].name == "High use"

    def test_search_partial_match_on_name(self, conn):
        library_repo.create(conn, _make_entry(name="DMAP"))
        library_repo.create(conn, _make_entry(name="Triethylamine", formula="C6H15N"))
        result = library_repo.search(conn, "DMA")
        assert [e.name for e in result] == ["DMAP"]

    def test_search_partial_match_on_cas(self, conn):
        library_repo.create(conn, _make_entry(cas_number="1122-58-3"))
        result = library_repo.search(conn, "1122")
        assert len(result) == 1


class TestUpdate:
    def test_update_persists_changes(self, conn):
        entry_id = library_repo.create(conn, _make_entry())
        entry = library_repo.get(conn, entry_id)
        entry.molecular_weight = 999.0
        library_repo.update(conn, entry)
        refreshed = library_repo.get(conn, entry_id)
        assert refreshed.molecular_weight == pytest.approx(999.0)

    def test_update_without_id_raises(self, conn):
        with pytest.raises(ValueError):
            library_repo.update(conn, _make_entry(id=None))

    def test_update_persists_preview_svg_and_render_mode(self, conn):
        entry_id = library_repo.create(conn, _make_entry())
        entry = library_repo.get(conn, entry_id)
        entry.preview_svg = "<svg>updated</svg>"
        entry.render_mode = "flat"
        library_repo.update(conn, entry)
        refreshed = library_repo.get(conn, entry_id)
        assert refreshed.preview_svg == "<svg>updated</svg>"
        assert refreshed.render_mode == "flat"


class TestIncrementUseCount:
    def test_increments(self, conn):
        entry_id = library_repo.create(conn, _make_entry())
        library_repo.increment_use_count(conn, entry_id)
        library_repo.increment_use_count(conn, entry_id)
        assert library_repo.get(conn, entry_id).use_count == 2


class TestDelete:
    def test_delete_removes_entry(self, conn):
        entry_id = library_repo.create(conn, _make_entry())
        library_repo.delete(conn, entry_id)
        assert library_repo.get(conn, entry_id) is None
