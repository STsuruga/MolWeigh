import sqlite3

import pytest

from molweigh.db import schema, template_repo


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    schema.migrate(connection)
    yield connection
    connection.close()


SAMPLE_PAYLOAD = {
    "reagents": [
        {"name": "化合物A", "library_id": 12, "role": "base", "eq": 1.0},
        {"name": "DMAP", "library_id": 8, "role": "additive", "eq": 6.0},
    ]
}


class TestCreateAndGet:
    def test_create_and_get_roundtrip(self, conn):
        template_id = template_repo.create(conn, "アミド化", SAMPLE_PAYLOAD)
        fetched = template_repo.get(conn, template_id)
        assert fetched.name == "アミド化"
        assert fetched.payload == SAMPLE_PAYLOAD

    def test_get_missing_returns_none(self, conn):
        assert template_repo.get(conn, 9999) is None


class TestListAll:
    def test_sorted_by_name(self, conn):
        template_repo.create(conn, "Z反応", SAMPLE_PAYLOAD)
        template_repo.create(conn, "A反応", SAMPLE_PAYLOAD)
        result = template_repo.list_all(conn)
        assert [t.name for t in result] == ["A反応", "Z反応"]


class TestUpdate:
    def test_update_persists_payload_change(self, conn):
        template_id = template_repo.create(conn, "アミド化", SAMPLE_PAYLOAD)
        fetched = template_repo.get(conn, template_id)
        fetched.payload["reagents"].append({"name": "NEt3", "library_id": 3, "role": "base", "eq": 2.0})
        template_repo.update(conn, fetched)
        refreshed = template_repo.get(conn, template_id)
        assert len(refreshed.payload["reagents"]) == 3

    def test_update_without_id_raises(self, conn):
        from molweigh.db.template_repo import Template

        with pytest.raises(ValueError):
            template_repo.update(conn, Template(id=None, name="x", payload={}))


class TestDelete:
    def test_delete_removes_template(self, conn):
        template_id = template_repo.create(conn, "アミド化", SAMPLE_PAYLOAD)
        template_repo.delete(conn, template_id)
        assert template_repo.get(conn, template_id) is None
