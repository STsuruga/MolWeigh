"""テーブル定義とスキーママイグレーション。

`PRAGMA user_version` でスキーマのバージョンを管理する。新しいフィールドや
テーブルを追加する際は `_MIGRATIONS` に1つずつSQLを追記し、既存の列を
追加する場合は `DEFAULT` 値を指定して既存データが無変更で読み込めるようにする。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_MIGRATIONS: list[str] = [
    # version 1: 初期スキーマ
    """
    CREATE TABLE IF NOT EXISTS library (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        cas_number TEXT,
        formula TEXT,
        molecular_weight REAL NOT NULL,
        density REAL,
        smiles TEXT,
        source TEXT NOT NULL,
        use_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
]


def get_connection(db_path: Path | str) -> sqlite3.Connection:
    """接続を確立し、スキーマを最新版までマイグレーションして返す。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """未適用のマイグレーションを順番に適用する。"""
    current_version = conn.execute("PRAGMA user_version").fetchone()[0]
    for version in range(current_version + 1, len(_MIGRATIONS) + 1):
        conn.executescript(_MIGRATIONS[version - 1])
        conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
