"""個人試薬ライブラリ(`library` テーブル)のCRUD。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class LibraryEntry:
    id: int | None
    name: str
    molecular_weight: float
    source: str
    cas_number: str | None = None
    formula: str | None = None
    density: float | None = None
    smiles: str | None = None
    use_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    preview_svg: str | None = None
    render_mode: str = "auto"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create(conn: sqlite3.Connection, entry: LibraryEntry) -> int:
    """新規登録し、採番されたidを返す。"""
    now = _now_iso()
    cur = conn.execute(
        """
        INSERT INTO library
            (name, cas_number, formula, molecular_weight, density, smiles,
             source, use_count, created_at, updated_at, preview_svg, render_mode)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry.name, entry.cas_number, entry.formula, entry.molecular_weight,
            entry.density, entry.smiles, entry.source, entry.use_count, now, now,
            entry.preview_svg, entry.render_mode,
        ),
    )
    conn.commit()
    return cur.lastrowid


def get(conn: sqlite3.Connection, entry_id: int) -> LibraryEntry | None:
    row = conn.execute("SELECT * FROM library WHERE id = ?", (entry_id,)).fetchone()
    return _row_to_entry(row) if row else None


def list_all(conn: sqlite3.Connection, order_by_use_count: bool = False) -> list[LibraryEntry]:
    """よく使う順(use_count降順)または名前順で一覧取得。"""
    order = "use_count DESC, name ASC" if order_by_use_count else "name ASC"
    rows = conn.execute(f"SELECT * FROM library ORDER BY {order}").fetchall()
    return [_row_to_entry(row) for row in rows]


def search(conn: sqlite3.Connection, query: str) -> list[LibraryEntry]:
    """試薬名・CAS番号・化学式に対する部分一致検索。"""
    like = f"%{query}%"
    rows = conn.execute(
        """
        SELECT * FROM library
        WHERE name LIKE ? OR cas_number LIKE ? OR formula LIKE ?
        ORDER BY use_count DESC, name ASC
        """,
        (like, like, like),
    ).fetchall()
    return [_row_to_entry(row) for row in rows]


def update(conn: sqlite3.Connection, entry: LibraryEntry) -> None:
    if entry.id is None:
        raise ValueError("idが未設定のエントリは更新できません")
    conn.execute(
        """
        UPDATE library
        SET name = ?, cas_number = ?, formula = ?, molecular_weight = ?,
            density = ?, smiles = ?, source = ?, use_count = ?, updated_at = ?,
            preview_svg = ?, render_mode = ?
        WHERE id = ?
        """,
        (
            entry.name, entry.cas_number, entry.formula, entry.molecular_weight,
            entry.density, entry.smiles, entry.source, entry.use_count,
            _now_iso(), entry.preview_svg, entry.render_mode, entry.id,
        ),
    )
    conn.commit()


def increment_use_count(conn: sqlite3.Connection, entry_id: int) -> None:
    conn.execute(
        "UPDATE library SET use_count = use_count + 1, updated_at = ? WHERE id = ?",
        (_now_iso(), entry_id),
    )
    conn.commit()


def delete(conn: sqlite3.Connection, entry_id: int) -> None:
    conn.execute("DELETE FROM library WHERE id = ?", (entry_id,))
    conn.commit()


def _row_to_entry(row: sqlite3.Row) -> LibraryEntry:
    return LibraryEntry(
        id=row["id"],
        name=row["name"],
        cas_number=row["cas_number"],
        formula=row["formula"],
        molecular_weight=row["molecular_weight"],
        density=row["density"],
        smiles=row["smiles"],
        source=row["source"],
        use_count=row["use_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        preview_svg=row["preview_svg"],
        render_mode=row["render_mode"],
    )
