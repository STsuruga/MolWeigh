import pytest

from molweigh.core.formula_parser import molecular_weight


class TestSimpleFormula:
    def test_glucose(self):
        # C6H12O6: 6*12.011 + 12*1.008 + 6*15.999
        assert molecular_weight("C6H12O6") == pytest.approx(180.156, rel=1e-5)

    def test_water(self):
        assert molecular_weight("H2O") == pytest.approx(18.015, rel=1e-5)

    def test_single_atom_no_count(self):
        assert molecular_weight("Fe") == pytest.approx(55.845)

    def test_implicit_count_one(self):
        # NaCl の各元素は個数省略(=1)
        assert molecular_weight("NaCl") == pytest.approx(22.98976928 + 35.45, rel=1e-6)


class TestNestedParentheses:
    def test_calcium_hydroxide(self):
        # Ca(OH)2
        assert molecular_weight("Ca(OH)2") == pytest.approx(74.092, rel=1e-5)

    def test_iron_nitrate_triple_group(self):
        # Fe(NO3)3
        assert molecular_weight("Fe(NO3)3") == pytest.approx(241.857, rel=1e-4)

    def test_unclosed_paren_raises(self):
        with pytest.raises(ValueError):
            molecular_weight("Ca(OH2")


class TestDeuterium:
    def test_heavy_water(self):
        # D2O: 2*2.014 + 15.999
        assert molecular_weight("D2O") == pytest.approx(20.027, rel=1e-5)

    def test_deuterated_chloroform(self):
        # CDCl3: 12.011 + 2.014 + 3*35.45
        assert molecular_weight("CDCl3") == pytest.approx(120.375, rel=1e-5)

    def test_d_followed_by_uppercase_is_not_merged(self):
        # DBr: D(重水素) + Br、"Db"(ドブニウム)と誤認しない
        assert molecular_weight("DBr") == pytest.approx(2.014 + 79.904, rel=1e-6)


class TestHydrate:
    def test_copper_sulfate_pentahydrate_middle_dot(self):
        assert molecular_weight("CuSO4·5H2O") == pytest.approx(249.677, rel=1e-4)

    def test_copper_sulfate_pentahydrate_period(self):
        assert molecular_weight("CuSO4.5H2O") == pytest.approx(249.677, rel=1e-4)

    def test_hydrate_without_leading_count(self):
        # 係数省略時は1として扱う
        assert molecular_weight("MgSO4·H2O") == pytest.approx(
            molecular_weight("MgSO4") + molecular_weight("H2O")
        )

    def test_hydrate_with_parenthetical_part(self):
        assert molecular_weight("CaCl2·6H2O") == pytest.approx(
            molecular_weight("CaCl2") + 6 * molecular_weight("H2O")
        )


class TestErrors:
    def test_empty_formula_raises(self):
        with pytest.raises(ValueError):
            molecular_weight("")

    def test_unknown_element_raises(self):
        with pytest.raises(ValueError):
            molecular_weight("Xx2O")

    def test_lowercase_start_raises(self):
        with pytest.raises(ValueError):
            molecular_weight("naCl")
