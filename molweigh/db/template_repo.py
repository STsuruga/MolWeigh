"""実験テンプレート(`templates` テーブル)のCRUD。

`payload` には試薬セット・当量比等をJSONでシリアライズして格納する。
試薬の参照はFw等の値そのものではなく `library_id` で行う設計とし、
ライブラリ側の情報更新が自動的に反映されるようにする(呼び出し側の責務)。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Template:
    id: int | None
    name: str
    payload: dict = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create(conn: sqlite3.Connection, name: str, payload: dict) -> int:
    now = _now_iso()
    cur = conn.execute(
        "INSERT INTO templates (name, payload, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (name, json.dumps(payload, ensure_ascii=False), now, now),
    )
    conn.commit()
    return cur.lastrowid


def get(conn: sqlite3.Connection, template_id: int) -> Template | None:
    row = conn.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
    return _row_to_template(row) if row else None


def list_all(conn: sqlite3.Connection) -> list[Template]:
    rows = conn.execute("SELECT * FROM templates ORDER BY name ASC").fetchall()
    return [_row_to_template(row) for row in rows]


def update(conn: sqlite3.Connection, template: Template) -> None:
    if template.id is None:
        raise ValueError("idが未設定のテンプレートは更新できません")
    conn.execute(
        "UPDATE templates SET name = ?, payload = ?, updated_at = ? WHERE id = ?",
        (template.name, json.dumps(template.payload, ensure_ascii=False), _now_iso(), template.id),
    )
    conn.commit()


def delete(conn: sqlite3.Connection, template_id: int) -> None:
    conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
    conn.commit()


def _row_to_template(row: sqlite3.Row) -> Template:
    return Template(
        id=row["id"],
        name=row["name"],
        payload=json.loads(row["payload"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
