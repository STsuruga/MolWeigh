"""化合物情報の解決を統括する。

優先順位:
  1. 個人ライブラリ照合(完全一致優先、なければ部分一致が1件のみの場合に採用)
  2. PubChem検索(ヒットすれば自動でライブラリに保存する)
  3. 化学式パーサー / 4. SMILES+RDKit は、ライブラリ・PubChemのいずれにも
     ヒットしない場合にUI側が明示的に呼び出すフォールバック経路。
     これらの経路で確定した化合物は、UIの保存ボタン操作で
     `save_to_library` を呼んでライブラリに追加する(自動保存はしない)。

ライブラリの部分一致検索で複数件ヒットした場合の候補選択UIは未実装
(仕様書§10の「あいまい検索」検討事項)。現状は完全一致を優先し、
それが無ければ最初の1件のみを自動採用する簡易実装とする。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal

from . import formula_parser, pubchem_client, structure
from ..db import library_repo
from ..db.library_repo import LibraryEntry

Source = Literal["library", "pubchem", "formula_parser", "smiles"]


@dataclass
class CompoundInfo:
    name: str
    formula: str | None
    molecular_weight: float
    density: float | None
    smiles: str | None
    source: Source
    library_id: int | None = None


def resolve_compound(conn: sqlite3.Connection, query: str) -> CompoundInfo | None:
    """ライブラリ→PubChemの順で解決を試みる。どちらもヒットしなければNoneを返し、
    呼び出し側(UI)が化学式/SMILES入力へフォールバックさせる。"""
    query = query.strip()
    if not query:
        raise ValueError("検索クエリが空です")

    library_hit = _resolve_from_library(conn, query)
    if library_hit is not None:
        return library_hit

    return _resolve_from_pubchem(conn, query)


def resolve_from_formula(formula: str) -> CompoundInfo:
    """化学式文字列から分子量を算出する(ライブラリへの自動保存はしない)。"""
    weight = formula_parser.molecular_weight(formula)
    return CompoundInfo(
        name=formula,
        formula=formula,
        molecular_weight=weight,
        density=None,
        smiles=None,
        source="formula_parser",
    )


def resolve_from_smiles(smiles: str) -> CompoundInfo:
    """SMILES文字列から分子量・化学式を算出する(ライブラリへの自動保存はしない)。"""
    info = structure.parse_smiles(smiles)
    return CompoundInfo(
        name=smiles,
        formula=info.formula,
        molecular_weight=info.molecular_weight,
        density=None,
        smiles=smiles,
        source="smiles",
    )


def save_to_library(conn: sqlite3.Connection, info: CompoundInfo, name: str | None = None) -> int:
    """CompoundInfoをライブラリへ保存し、採番されたidを返す。"""
    entry = LibraryEntry(
        id=None,
        name=name or info.name,
        molecular_weight=info.molecular_weight,
        source=info.source,
        formula=info.formula,
        density=info.density,
        smiles=info.smiles,
    )
    return library_repo.create(conn, entry)


def _resolve_from_library(conn: sqlite3.Connection, query: str) -> CompoundInfo | None:
    matches = library_repo.search(conn, query)
    if not matches:
        return None

    exact = [m for m in matches if m.name.lower() == query.lower()]
    entry = exact[0] if exact else matches[0]

    library_repo.increment_use_count(conn, entry.id)
    return CompoundInfo(
        name=entry.name,
        formula=entry.formula,
        molecular_weight=entry.molecular_weight,
        density=entry.density,
        smiles=entry.smiles,
        source="library",
        library_id=entry.id,
    )


def _resolve_from_pubchem(conn: sqlite3.Connection, query: str) -> CompoundInfo | None:
    result = pubchem_client.search_compound(query)
    if result is None:
        return None

    info = CompoundInfo(
        name=query,
        formula=result.formula,
        molecular_weight=result.molecular_weight,
        density=result.density,
        smiles=result.smiles,
        source="pubchem",
    )
    info.library_id = save_to_library(conn, info)
    return info
