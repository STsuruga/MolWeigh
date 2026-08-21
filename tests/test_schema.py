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

    def test_adds_preview_svg_and_render_mode_columns(self):
        conn = sqlite3.connect(":memory:")
        schema.migrate(conn)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(library)").fetchall()}
        assert {"preview_svg", "render_mode"}.issubset(columns)

    def test_render_mode_defaults_to_auto_for_existing_rows(self):
        conn = sqlite3.connect(":memory:")
        schema.migrate(conn)
        conn.execute(
            "INSERT INTO library (name, molecular_weight, source, created_at, updated_at) "
            "VALUES ('X', 1.0, 'manual', '', '')"
        )
        row = conn.execute("SELECT render_mode, preview_svg FROM library").fetchone()
        assert row[0] == "auto"
        assert row[1] is None

    def test_adds_molblock_column_defaulting_to_null(self):
        conn = sqlite3.connect(":memory:")
        schema.migrate(conn)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(library)").fetchall()}
        assert "molblock" in columns
        conn.execute(
            "INSERT INTO library (name, molecular_weight, source, created_at, updated_at) "
            "VALUES ('X', 1.0, 'manual', '', '')"
        )
        row = conn.execute("SELECT molblock FROM library").fetchone()
        assert row[0] is None

    def test_adds_renderer_version_column_defaulting_to_zero(self):
        conn = sqlite3.connect(":memory:")
        schema.migrate(conn)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(library)").fetchall()}
        assert "renderer_version" in columns
        conn.execute(
            "INSERT INTO library (name, molecular_weight, source, created_at, updated_at) "
            "VALUES ('X', 1.0, 'manual', '', '')"
        )
        row = conn.execute("SELECT renderer_version FROM library").fetchone()
        assert row[0] == 0

    def test_migrating_from_version_1_preserves_existing_data(self):
        # version 1のスキーマだけを素朴に作り、そこにレコードを入れてから
        # migrate()した場合でも、既存データが失われないことを確認する。
        conn = sqlite3.connect(":memory:")
        conn.executescript(schema._MIGRATIONS[0])
        conn.execute("PRAGMA user_version = 1")
        conn.execute(
            "INSERT INTO library (name, molecular_weight, source, created_at, updated_at) "
            "VALUES ('Existing', 42.0, 'manual', '', '')"
        )
        conn.commit()

        schema.migrate(conn)

        row = conn.execute("SELECT name, molecular_weight, render_mode FROM library").fetchone()
        assert row[0] == "Existing"
        assert row[1] == 42.0
        assert row[2] == "auto"


class TestGetConnection:
    def test_returns_connection_with_row_factory(self, tmp_path):
        conn = schema.get_connection(tmp_path / "test.db")
        assert conn.row_factory is sqlite3.Row
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'library'"
        ).fetchone()
        assert row is not None
