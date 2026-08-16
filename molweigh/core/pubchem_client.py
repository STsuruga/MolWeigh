"""PubChem PUG REST APIラッパー。

化合物名またはCAS番号(PubChemはCAS番号もシノニムとして名前検索できる)から、
分子量・化学式・SMILES、可能であれば密度を取得する。ネットワーク呼び出しは
このモジュールに閉じ込め、呼び出し側(`compound_source.py`)やこのモジュール
自体のテストでは `requests` をモック化する。

密度はPubChemの標準プロパティには含まれず、PUG-View(Experimental
Properties > Density)からのベストエフォート取得となる。多くの化合物で
未収載のため、取得できなくても例外にはせず `None` を返す。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote

import requests

_BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
_VIEW_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"
_TIMEOUT = 10
_DENSITY_VALUE_RE = re.compile(r"[-+]?\d*\.?\d+")


class PubChemError(Exception):
    """PubChemとの通信・応答解析に失敗した場合に送出する。"""


@dataclass
class PubChemCompound:
    cid: int
    name: str
    formula: str
    molecular_weight: float
    smiles: str
    density: float | None = None


def search_compound(query: str) -> PubChemCompound | None:
    """化合物名またはCAS番号からPubChemを照会する。ヒットしなければNoneを返す。"""
    cid = _find_cid(query)
    if cid is None:
        return None
    props = _fetch_properties(cid)
    return PubChemCompound(
        cid=cid,
        name=query,
        formula=props["MolecularFormula"],
        molecular_weight=float(props["MolecularWeight"]),
        smiles=props.get("CanonicalSMILES", ""),
        density=_fetch_density(cid),
    )


def _find_cid(query: str) -> int | None:
    url = f"{_BASE_URL}/compound/name/{quote(query, safe='')}/cids/JSON"
    response = _get(url)
    if response.status_code == 404:
        return None
    if not response.ok:
        raise PubChemError(f"PubChem検索に失敗しました(status={response.status_code}): {query!r}")
    try:
        cids = response.json()["IdentifierList"]["CID"]
    except (KeyError, ValueError):
        return None
    return cids[0] if cids else None


def _fetch_properties(cid: int) -> dict:
    url = (
        f"{_BASE_URL}/compound/cid/{cid}/property/"
        "MolecularFormula,MolecularWeight,CanonicalSMILES/JSON"
    )
    response = _get(url)
    if not response.ok:
        raise PubChemError(f"PubChemの物性取得に失敗しました(status={response.status_code}): cid={cid}")
    try:
        return response.json()["PropertyTable"]["Properties"][0]
    except (KeyError, IndexError, ValueError) as exc:
        raise PubChemError(f"PubChemの応答を解析できません: cid={cid}") from exc


def _fetch_density(cid: int) -> float | None:
    """密度はベストエフォート取得。通信・解析エラーは例外にせずNoneとして扱う。"""
    url = f"{_VIEW_URL}/data/compound/{cid}/JSON/?heading=Density"
    try:
        response = requests.get(url, timeout=_TIMEOUT)
    except requests.RequestException:
        return None
    if not response.ok:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    return _parse_density_value(payload)


def _get(url: str) -> requests.Response:
    try:
        return requests.get(url, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        raise PubChemError(f"PubChemへの通信に失敗しました: {exc}") from exc


def _parse_density_value(payload: dict) -> float | None:
    record = payload.get("Record", {})
    for node in _walk_sections(record):
        if node.get("TOCHeading") == "Density":
            value = _extract_first_number(node)
            if value is not None:
                return value
    return None


def _walk_sections(node: dict):
    yield node
    for child in node.get("Section", []):
        yield from _walk_sections(child)


def _extract_first_number(node: dict) -> float | None:
    for info in node.get("Information", []):
        for markup in info.get("Value", {}).get("StringWithMarkup", []):
            match = _DENSITY_VALUE_RE.search(markup.get("String", ""))
            if match:
                return float(match.group())
    return None
