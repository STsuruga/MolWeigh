import sqlite3

from molweigh.db import schema


class TestMigrate:
    def test_creates_expected_tables(self):
        conn = sqlite3.connect(":memory:")
        schema.migrate(conn)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {"library", "templates"}.issubset(tables)

    def test_sets_user_version(self):
        conn = sqlite3.connect(":memory:")
        schema.migrate(conn)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == len(schema._MIGRATIONS)

    def test_idempotent(self):
        conn = sqlite3.connect(":memory:")
        schema.migrate(conn)
        schema.migrate(conn)  # 2回目も安全に実行できる
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == len(schema._MIGRATIONS)


class TestGetConnection:
    def test_returns_connection_with_row_factory(self, tmp_path):
        conn = schema.get_connection(tmp_path / "test.db")
        assert conn.row_factory is sqlite3.Row
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'library'"
        ).fetchone()
        assert row is not None
