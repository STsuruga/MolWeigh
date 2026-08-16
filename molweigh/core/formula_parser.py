"""化学式文字列から分子量を算出する。

対応する表記:
  - 元素記号 + 任意の個数(例: ``C6H12O6``)
  - 括弧のネスト + 個数(例: ``Ca(OH)2``, ``Fe(NO3)3``)
  - 重水素 D(例: ``D2O``, ``CDCl3``)。T(トリチウム)等の同位体全般は非対応。
  - 水和物表記(``·`` / ``.`` / ``*`` 区切り、例: ``CuSO4·5H2O``)
"""

from __future__ import annotations

import re

# IUPAC標準原子量(2021版に準拠、安定同位体が支配的な元素は概数)。
# D(重水素)は元素記号ではないが、実験化学での使用頻度が高いため特別に追加。
ATOMIC_WEIGHTS: dict[str, float] = {
    "H": 1.008, "D": 2.014, "He": 4.002602,
    "Li": 6.94, "Be": 9.0121831, "B": 10.81, "C": 12.011, "N": 14.007,
    "O": 15.999, "F": 18.998403163, "Ne": 20.1797,
    "Na": 22.98976928, "Mg": 24.305, "Al": 26.9815384, "Si": 28.085,
    "P": 30.973761998, "S": 32.06, "Cl": 35.45, "Ar": 39.948,
    "K": 39.0983, "Ca": 40.078, "Sc": 44.955908, "Ti": 47.867,
    "V": 50.9415, "Cr": 51.9961, "Mn": 54.938043, "Fe": 55.845,
    "Co": 58.933194, "Ni": 58.6934, "Cu": 63.546, "Zn": 65.38,
    "Ga": 69.723, "Ge": 72.630, "As": 74.921595, "Se": 78.971,
    "Br": 79.904, "Kr": 83.798,
    "Rb": 85.4678, "Sr": 87.62, "Y": 88.90584, "Zr": 91.224,
    "Nb": 92.90637, "Mo": 95.95, "Tc": 98.0, "Ru": 101.07,
    "Rh": 102.90549, "Pd": 106.42, "Ag": 107.8682, "Cd": 112.414,
    "In": 114.818, "Sn": 118.710, "Sb": 121.760, "Te": 127.60,
    "I": 126.90447, "Xe": 131.293,
    "Cs": 132.90545196, "Ba": 137.327, "La": 138.90547, "Ce": 140.116,
    "Pr": 140.90766, "Nd": 144.242, "Pm": 145.0, "Sm": 150.36,
    "Eu": 151.964, "Gd": 157.25, "Tb": 158.925354, "Dy": 162.500,
    "Ho": 164.930328, "Er": 167.259, "Tm": 168.934218, "Yb": 173.045,
    "Lu": 174.9668, "Hf": 178.49, "Ta": 180.94788, "W": 183.84,
    "Re": 186.207, "Os": 190.23, "Ir": 192.217, "Pt": 195.084,
    "Au": 196.966570, "Hg": 200.592, "Tl": 204.38, "Pb": 207.2,
    "Bi": 208.98040, "Po": 209.0, "At": 210.0, "Rn": 222.0,
    "Fr": 223.0, "Ra": 226.0, "Ac": 227.0, "Th": 232.0377,
    "Pa": 231.03588, "U": 238.02891, "Np": 237.0, "Pu": 244.0,
    "Am": 243.0, "Cm": 247.0, "Bk": 247.0, "Cf": 251.0, "Es": 252.0,
    "Fm": 257.0, "Md": 258.0, "No": 259.0, "Lr": 262.0,
    "Rf": 267.0, "Db": 268.0, "Sg": 271.0, "Bh": 272.0, "Hs": 270.0,
    "Mt": 276.0, "Ds": 281.0, "Rg": 280.0, "Cn": 285.0,
    "Nh": 284.0, "Fl": 289.0, "Mc": 288.0, "Lv": 293.0,
    "Ts": 294.0, "Og": 294.0,
}

_SYMBOL_RE = re.compile(r"[A-Z][a-z]?")
_COUNT_RE = re.compile(r"\d*\.?\d*")
_HYDRATE_SEP_RE = re.compile(r"[·.*]")
_HYDRATE_PART_RE = re.compile(r"^(\d*\.?\d*)(.*)$", re.DOTALL)


def molecular_weight(formula: str) -> float:
    """化学式文字列から分子量を算出する。水和物表記(先頭以外の部分に係数を付けてよい)にも対応。"""
    formula = formula.strip()
    if not formula:
        raise ValueError("化学式が空です")

    parts = _HYDRATE_SEP_RE.split(formula)
    total = _formula_weight(parts[0])
    for part in parts[1:]:
        part = part.strip()
        if not part:
            raise ValueError(f"化学式を解析できません: {formula!r}")
        count_str, sub_formula = _HYDRATE_PART_RE.match(part).groups()
        count = float(count_str) if count_str else 1.0
        total += count * _formula_weight(sub_formula)
    return total


def _formula_weight(formula: str) -> float:
    counts, pos = _parse_group(formula, 0)
    if pos != len(formula):
        raise ValueError(f"化学式を解析できません: {formula!r}(位置{pos}以降が不正)")
    return sum(ATOMIC_WEIGHTS[symbol] * n for symbol, n in counts.items())


def _parse_group(formula: str, pos: int) -> tuple[dict[str, float], int]:
    counts: dict[str, float] = {}
    while pos < len(formula) and formula[pos] != ")":
        if formula[pos] == "(":
            sub_counts, pos = _parse_group(formula, pos + 1)
            if pos >= len(formula) or formula[pos] != ")":
                raise ValueError(f"括弧が閉じていません: {formula!r}")
            count, pos = _read_count(formula, pos + 1)
            for symbol, n in sub_counts.items():
                counts[symbol] = counts.get(symbol, 0.0) + n * count
        else:
            symbol, pos = _read_symbol(formula, pos)
            count, pos = _read_count(formula, pos)
            counts[symbol] = counts.get(symbol, 0.0) + count
    return counts, pos


def _read_symbol(formula: str, pos: int) -> tuple[str, int]:
    m = _SYMBOL_RE.match(formula, pos)
    if not m:
        raise ValueError(f"元素記号を解析できません: {formula[pos:]!r}")
    symbol = m.group(0)
    if symbol not in ATOMIC_WEIGHTS:
        raise ValueError(f"未知の元素記号です: {symbol!r}")
    return symbol, m.end()


def _read_count(formula: str, pos: int) -> tuple[float, int]:
    m = _COUNT_RE.match(formula, pos)
    if not m.group(0):
        return 1.0, pos
    return float(m.group(0)), m.end()
