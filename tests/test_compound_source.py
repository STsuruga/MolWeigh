import sqlite3

import pytest

from molweigh.core import compound_source
from molweigh.core.compound_source import CompoundInfo
from molweigh.core.pubchem_client import PubChemCompound
from molweigh.db import library_repo, schema
from molweigh.db.library_repo import LibraryEntry


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    schema.migrate(connection)
    yield connection
    connection.close()


class TestResolveFromLibrary:
    def test_exact_match_returns_library_source(self, conn):
        library_repo.create(
            conn,
            LibraryEntry(id=None, name="DMAP", molecular_weight=122.17, source="pubchem"),
        )
        result = compound_source.resolve_compound(conn, "DMAP")
        assert result.source == "library"
        assert result.molecular_weight == pytest.approx(122.17)
        assert result.library_id is not None

    def test_exact_match_case_insensitive(self, conn):
        library_repo.create(
            conn,
            LibraryEntry(id=None, name="DMAP", molecular_weight=122.17, source="pubchem"),
        )
        result = compound_source.resolve_compound(conn, "dmap")
        assert result.source == "library"

    def test_partial_match_single_hit(self, conn):
        library_repo.create(
            conn,
            LibraryEntry(id=None, name="4-Dimethylaminopyridine", molecular_weight=122.17, source="pubchem"),
        )
        result = compound_source.resolve_compound(conn, "Dimethylamino")
        assert result.source == "library"

    def test_library_hit_increments_use_count(self, conn):
        entry_id = library_repo.create(
            conn,
            LibraryEntry(id=None, name="DMAP", molecular_weight=122.17, source="pubchem"),
        )
        compound_source.resolve_compound(conn, "DMAP")
        assert library_repo.get(conn, entry_id).use_count == 1

    def test_library_hit_does_not_call_pubchem(self, conn, monkeypatch):
        library_repo.create(
            conn,
            LibraryEntry(id=None, name="DMAP", molecular_weight=122.17, source="pubchem"),
        )

        def fail_if_called(query):
            raise AssertionError("PubChemは呼ばれないはず")

        monkeypatch.setattr(compound_source.pubchem_client, "search_compound", fail_if_called)
        compound_source.resolve_compound(conn, "DMAP")


class TestResolveFromPubChem:
    def test_pubchem_hit_is_saved_to_library(self, conn, monkeypatch):
        fake_compound = PubChemCompound(
            cid=2244, name="aspirin", formula="C9H8O4", molecular_weight=180.16,
            smiles="CC(=O)OC1=CC=CC=C1C(=O)O", density=None,
        )
        monkeypatch.setattr(
            compound_source.pubchem_client, "search_compound", lambda q: fake_compound
        )
        result = compound_source.resolve_compound(conn, "aspirin")
        assert result.source == "pubchem"
        assert result.library_id is not None
        saved = library_repo.get(conn, result.library_id)
        assert saved.name == "aspirin"
        assert saved.formula == "C9H8O4"

    def test_no_hit_anywhere_returns_none(self, conn, monkeypatch):
        monkeypatch.setattr(compound_source.pubchem_client, "search_compound", lambda q: None)
        assert compound_source.resolve_compound(conn, "unknown-compound-xyz") is None


class TestResolveCompoundValidation:
    def test_empty_query_raises(self, conn):
        with pytest.raises(ValueError):
            compound_source.resolve_compound(conn, "   ")


class TestResolveFromFormula:
    def test_returns_formula_parser_source(self):
        result = compound_source.resolve_from_formula("C6H12O6")
        assert result.source == "formula_parser"
        assert result.molecular_weight == pytest.approx(180.156, rel=1e-5)
        assert result.formula == "C6H12O6"


class TestResolveFromSmiles:
    def test_returns_smiles_source(self):
        result = compound_source.resolve_from_smiles("CCO")
        assert result.source == "smiles"
        assert result.formula == "C2H6O"
        assert result.molecular_weight == pytest.approx(46.069, rel=1e-4)


class TestSaveToLibrary:
    def test_persists_and_returns_id(self, conn):
        info = CompoundInfo(
            name="Glucose", formula="C6H12O6", molecular_weight=180.156,
            density=None, smiles=None, source="formula_parser",
        )
        entry_id = compound_source.save_to_library(conn, info)
        saved = library_repo.get(conn, entry_id)
        assert saved.name == "Glucose"
        assert saved.source == "formula_parser"

    def test_custom_name_overrides_info_name(self, conn):
        info = CompoundInfo(
            name="C6H12O6", formula="C6H12O6", molecular_weight=180.156,
            density=None, smiles=None, source="formula_parser",
        )
        entry_id = compound_source.save_to_library(conn, info, name="グルコース")
        assert library_repo.get(conn, entry_id).name == "グルコース"
