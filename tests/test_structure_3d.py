import pytest

from molweigh.core.structure_3d import embed_and_optimize, generate_3d_molblock


class TestEmbedAndOptimize:
    def test_ethanol_has_3d_conformer(self):
        mol = embed_and_optimize("CCO")
        assert mol.GetNumConformers() == 1
        assert mol.GetConformer().Is3D()

    def test_invalid_smiles_raises_value_error(self):
        with pytest.raises(ValueError):
            embed_and_optimize("not-a-smiles(((")


class TestGenerate3DMolblock:
    def test_ethanol_returns_v2000_molblock(self):
        molblock = generate_3d_molblock("CCO")
        assert "V2000" in molblock
        assert "M  END" in molblock

    def test_bridged_ring_structure_succeeds(self):
        # adamantane, a caged/bridged structure
        molblock = generate_3d_molblock("C1C2CC3CC1CC(C2)C3")
        assert "V2000" in molblock

    def test_invalid_smiles_raises_value_error(self):
        with pytest.raises(ValueError):
            generate_3d_molblock("not-a-smiles(((")
