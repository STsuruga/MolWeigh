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
    # version 2: 構造式プレビューのSVGをキャッシュし、平面/立体モードの
    # ユーザー選択を保存する(core/lineart_render.py参照)。既存レコードは
    # preview_svgがNULLのままrender_structure_image()がオンザフライで
    # 生成する経路にフォールバックするため、一括再生成は不要。
    """
    ALTER TABLE library ADD COLUMN preview_svg TEXT;
    ALTER TABLE library ADD COLUMN render_mode TEXT NOT NULL DEFAULT 'auto';
    """,
    # version 3: Ketcherの2D座標つきMOLブロックを保持する(core/lineart_render.py
    # ::build_scene()のmolblock引数)。SMILESはトポロジーしか持たないため、SMILES
    # 経由の再構築のたびに座標(向き)が失われ再生成されていた問題への対処。
    # 既存レコードはmolblockがNULLのままSMILES経由の従来経路にフォールバックする。
    """
    ALTER TABLE library ADD COLUMN molblock TEXT;
    """,
    # version 4: 保存済みpreview_svgを焼いた時点のレンダラーバージョンを記録する
    # (core/lineart_render.py::CURRENT_RENDERER_VERSION)。レンダラーの実装を
    # 変更してもこの値と食い違うまで気づかず古い絵が残り続ける問題があったため、
    # 表示時に自動で焼き直す(ui/library_dialog.py)。既存レコードは0のままとなり、
    # 現行バージョン(1以上)と食い違うため次回表示時に自動的に焼き直される。
    """
    ALTER TABLE library ADD COLUMN renderer_version INTEGER NOT NULL DEFAULT 0;
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
