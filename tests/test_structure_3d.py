import pytest

from molweigh.core.structure_3d import embed_and_optimize, generate_3d_conformer


class TestEmbedAndOptimize:
    def test_ethanol_has_3d_conformer(self):
        mol = embed_and_optimize("CCO")
        assert mol.GetNumConformers() == 1
        assert mol.GetConformer().Is3D()

    def test_invalid_smiles_raises_value_error(self):
        with pytest.raises(ValueError):
            embed_and_optimize("not-a-smiles(((")


class TestGenerate3DConformer:
    def test_ethanol_has_atoms_and_bonds_with_nonzero_coords(self):
        mol3d = generate_3d_conformer("CCO")
        assert len(mol3d.atoms) == 9  # C2H6O: 2C + 1O + 6H
        assert len(mol3d.bonds) == 8
        assert any(a.x != 0.0 or a.y != 0.0 or a.z != 0.0 for a in mol3d.atoms)

    def test_bridged_ring_structure_succeeds(self):
        # adamantane, a caged/bridged structure
        mol3d = generate_3d_conformer("C1C2CC3CC1CC(C2)C3")
        assert len(mol3d.atoms) > 0
        assert len(mol3d.bonds) > 0

    def test_invalid_smiles_raises_value_error(self):
        with pytest.raises(ValueError):
            generate_3d_conformer("not-a-smiles(((")

    def test_bond_orders_are_populated(self):
        mol3d = generate_3d_conformer("C=O")
        orders = {b.order for b in mol3d.bonds}
        assert 2.0 in orders
