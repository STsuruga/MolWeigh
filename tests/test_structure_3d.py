import pytest

from molweigh.core.structure_3d import embed_and_optimize


class TestEmbedAndOptimize:
    def test_ethanol_has_3d_conformer(self):
        mol = embed_and_optimize("CCO")
        assert mol.GetNumConformers() == 1
        assert mol.GetConformer().Is3D()

    def test_invalid_smiles_raises_value_error(self):
        with pytest.raises(ValueError):
            embed_and_optimize("not-a-smiles(((")
