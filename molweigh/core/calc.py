"""当量(eq)計算の純粋関数群。UI・DB・OS固有処理に一切依存しない。

計算は2セクションに分かれる(既存Excel版のセル構造を踏襲):
  - 秤量計画: 基準試薬の実測値から、各試薬の目標当量に必要な量を算出する。
  - 実績記録: 実際に量った値から、実際のmmolと基準試薬に対する実績当量を逆算する。
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# セクション1: 秤量計画
# ---------------------------------------------------------------------------

def calc_base_mmol(fw: float, weight: float, weight_unit: str) -> float:
    """基準試薬のmmolを重量から算出。weight_unit は 'g' または 'mg'。"""
    if fw <= 0:
        raise ValueError("Fwが未入力です")
    mmol = weight / fw
    return mmol * 1000 if weight_unit == "g" else mmol


def calc_target_mmol(base_mmol: float, eq: float) -> float:
    """目標当量から必要mmolを算出。"""
    return base_mmol * eq


def calc_required_weight(fw: float, mmol: float, weight_unit: str) -> float:
    """必要mmolから必要重量を算出。"""
    weight = fw * mmol
    return weight / 1000 if weight_unit == "g" else weight


def calc_required_volume(
    mmol: float | None = None,
    molarity: float | None = None,
    weight: float | None = None,
    density: float | None = None,
    weight_unit: str = "mg",
) -> float:
    """必要体積(mL)を算出。molarity指定 or density指定のいずれか。"""
    if molarity and density:
        raise ValueError("molarityとdensityは同時に指定できません")
    if molarity:
        return mmol / molarity
    if density:
        weight_g = weight / 1000 if weight_unit == "mg" else weight
        return weight_g / density
    raise ValueError("molarityまたはdensityのいずれかが必要です")


# ---------------------------------------------------------------------------
# セクション2: 実績記録
# ---------------------------------------------------------------------------

def calc_actual_mmol(
    fw: float,
    weight: float | None = None,
    weight_unit: str = "mg",
    density: float | None = None,
    molarity: float | None = None,
    volume: float | None = None,
) -> float:
    """実測値から実際のmmolを算出。優先順位: weight > density×volume > molarity×volume。"""
    if weight and volume:
        raise ValueError("weightとvolumeは同時に指定できません(入力元が重複)")
    if weight:
        mmol = weight / fw
        return mmol * 1000 if weight_unit == "g" else mmol
    if density and volume:
        return (density * volume) / fw * 1000
    if molarity and volume:
        return molarity * volume
    raise ValueError("有効な入力の組み合わせがありません")


def calc_actual_eq(actual_mmol: float, base_actual_mmol: float) -> float:
    """基準試薬の実績mmolに対する実績当量。"""
    if base_actual_mmol <= 0:
        raise ValueError("基準試薬のmmolが未確定です")
    return actual_mmol / base_actual_mmol
