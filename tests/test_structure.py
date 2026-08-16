import pytest

from molweigh.core.structure import parse_smiles, render_structure_image


class TestParseSmiles:
    def test_ethanol(self):
        info = parse_smiles("CCO")
        assert info.formula == "C2H6O"
        assert info.molecular_weight == pytest.approx(46.069, rel=1e-4)

    def test_benzene_aromatic_ring(self):
        info = parse_smiles("c1ccccc1")
        assert info.formula == "C6H6"
        assert info.molecular_weight == pytest.approx(78.114, rel=1e-4)

    def test_invalid_smiles_raises(self):
        with pytest.raises(ValueError):
            parse_smiles("not-a-smiles(((")


class TestRenderStructureImage:
    def test_returns_pixmap_of_requested_size(self, qapp):
        pixmap = render_structure_image("CCO", size=(200, 150))
        assert not pixmap.isNull()
        assert pixmap.width() == 200
        assert pixmap.height() == 150

    def test_invalid_smiles_raises(self, qapp):
        with pytest.raises(ValueError):
            render_structure_image("not-a-smiles(((")
