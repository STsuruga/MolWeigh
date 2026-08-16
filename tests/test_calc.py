import pytest

from molweigh.core.calc import (
    calc_actual_eq,
    calc_actual_mmol,
    calc_base_mmol,
    calc_required_volume,
    calc_required_weight,
    calc_target_mmol,
)


# ---------------------------------------------------------------------------
# セクション1: 秤量計画
# ---------------------------------------------------------------------------

class TestCalcBaseMmol:
    def test_mg_input(self):
        # Fw458.27 / 200mg はExcel版の代表サンプル値
        assert calc_base_mmol(458.27, 200, "mg") == pytest.approx(0.4364239, rel=1e-6)

    def test_g_input_matches_mg_equivalent(self):
        mmol_from_g = calc_base_mmol(458.27, 0.2, "g")
        mmol_from_mg = calc_base_mmol(458.27, 200, "mg")
        assert mmol_from_g == pytest.approx(mmol_from_mg)

    def test_fw_zero_raises(self):
        with pytest.raises(ValueError):
            calc_base_mmol(0, 200, "mg")

    def test_fw_negative_raises(self):
        with pytest.raises(ValueError):
            calc_base_mmol(-1, 200, "mg")


class TestCalcTargetMmol:
    def test_eq6(self):
        base_mmol = calc_base_mmol(458.27, 200, "mg")
        assert calc_target_mmol(base_mmol, 6) == pytest.approx(base_mmol * 6)
        assert calc_target_mmol(base_mmol, 6) == pytest.approx(2.6185437, rel=1e-6)


class TestCalcRequiredWeight:
    def test_mg_output(self):
        assert calc_required_weight(100, 5, "mg") == pytest.approx(500)

    def test_g_output(self):
        assert calc_required_weight(100, 5, "g") == pytest.approx(0.5)


class TestCalcRequiredVolume:
    def test_molarity_path(self):
        assert calc_required_volume(mmol=5, molarity=2) == pytest.approx(2.5)

    def test_density_path_mg(self):
        assert calc_required_volume(
            weight=500, density=1.2, weight_unit="mg"
        ) == pytest.approx(500 / 1000 / 1.2)

    def test_density_path_g(self):
        assert calc_required_volume(
            weight=0.5, density=1.2, weight_unit="g"
        ) == pytest.approx(0.5 / 1.2)

    def test_molarity_and_density_together_raises(self):
        with pytest.raises(ValueError):
            calc_required_volume(mmol=5, molarity=2, weight=500, density=1.2)

    def test_neither_raises(self):
        with pytest.raises(ValueError):
            calc_required_volume(mmol=5)


# ---------------------------------------------------------------------------
# セクション2: 実績記録
# ---------------------------------------------------------------------------

class TestCalcActualMmol:
    def test_weight_path_mg(self):
        assert calc_actual_mmol(458.27, weight=200, weight_unit="mg") == pytest.approx(
            0.4364239, rel=1e-6
        )

    def test_weight_path_g(self):
        mmol_g = calc_actual_mmol(458.27, weight=0.2, weight_unit="g")
        mmol_mg = calc_actual_mmol(458.27, weight=200, weight_unit="mg")
        assert mmol_g == pytest.approx(mmol_mg)

    def test_weight_and_volume_together_raises(self):
        with pytest.raises(ValueError):
            calc_actual_mmol(458.27, weight=200, volume=1)

    def test_density_volume_path(self):
        assert calc_actual_mmol(100, density=1.2, volume=0.5) == pytest.approx(6.0)

    def test_molarity_volume_path(self):
        assert calc_actual_mmol(100, molarity=2, volume=0.5) == pytest.approx(1.0)

    def test_no_valid_input_raises(self):
        with pytest.raises(ValueError):
            calc_actual_mmol(100)


class TestCalcActualEq:
    def test_eq_ratio(self):
        assert calc_actual_eq(2.5, 0.5) == pytest.approx(5.0)

    def test_base_mmol_zero_raises(self):
        with pytest.raises(ValueError):
            calc_actual_eq(2.5, 0)

    def test_base_mmol_negative_raises(self):
        with pytest.raises(ValueError):
            calc_actual_eq(2.5, -1)
