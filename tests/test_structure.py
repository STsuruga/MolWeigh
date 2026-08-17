import numpy as np
import pytest

from molweigh.core import structure_3d
from molweigh.core.structure import (
    _min_pairwise_distance_2d,
    _orient_canonically,
    parse_smiles,
    realign_bridged_structure_molblock,
    render_structure_image,
)


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

    def test_bridged_structure_renders_via_3d_projection(self, qapp):
        # トリプチセン(bridgehead原子を持つ橋かけ構造)
        triptycene = "c1ccc2c(c1)C1c3ccccc3C2c2ccccc21"
        pixmap = render_structure_image(triptycene, size=(300, 300))
        assert not pixmap.isNull()
        assert pixmap.width() == 300

    def test_non_bridged_structure_unaffected(self, qapp):
        pixmap = render_structure_image("c1ccccc1", size=(200, 200))
        assert not pixmap.isNull()


class TestRealignBridgedStructureMolblock:
    def test_non_bridged_returns_none(self, qapp):
        assert realign_bridged_structure_molblock("CCO") is None

    def test_bridged_returns_molblock_with_matching_atom_count(self, qapp):
        triptycene = "c1ccc2c(c1)C1c3ccccc3C2c2ccccc21"
        molblock = realign_bridged_structure_molblock(triptycene)
        assert molblock is not None
        assert "V2000" in molblock

        from rdkit import Chem

        reloaded = Chem.MolFromMolBlock(molblock)
        assert reloaded is not None
        assert reloaded.GetNumAtoms() == Chem.MolFromSmiles(triptycene).GetNumAtoms()

    def test_invalid_smiles_raises(self, qapp):
        with pytest.raises(ValueError):
            realign_bridged_structure_molblock("not-a-smiles(((")


class TestOrientCanonically:
    def test_reorients_in_place(self):
        mol = structure_3d.embed_and_optimize("c1ccc2c(c1)C1c3ccccc3C2c2ccccc21")
        before = [list(mol.GetConformer().GetAtomPosition(i)) for i in range(mol.GetNumAtoms())]
        _orient_canonically(mol)
        after = [list(mol.GetConformer().GetAtomPosition(i)) for i in range(mol.GetNumAtoms())]
        assert before != after

    def test_chooses_best_of_the_three_candidate_axes(self):
        # 3方向(どの主軸を奥行きにするか)のうち、実際にスコア最大の
        # 向きが選ばれていることを確認する。
        mol = structure_3d.embed_and_optimize("c1ccc2c(c1)C1c3ccccc3C2c2ccccc21")
        heavy_mask = np.array([atom.GetAtomicNum() != 1 for atom in mol.GetAtoms()])
        conformer = mol.GetConformer()
        coords = np.array([list(conformer.GetAtomPosition(i)) for i in range(mol.GetNumAtoms())])
        centered = coords - coords.mean(axis=0)
        _, eigenvectors = np.linalg.eigh(np.cov(centered[heavy_mask].T))

        candidate_scores = []
        for depth_axis in range(3):
            other_axes = [i for i in range(3) if i != depth_axis]
            rotation = np.column_stack(
                [eigenvectors[:, other_axes[0]], eigenvectors[:, other_axes[1]], eigenvectors[:, depth_axis]]
            )
            if np.linalg.det(rotation) < 0:
                rotation[:, -1] *= -1
            candidate_scores.append(_min_pairwise_distance_2d((centered @ rotation)[heavy_mask]))
        best_candidate_score = max(candidate_scores)

        _orient_canonically(mol)
        rotated = np.array([list(mol.GetConformer().GetAtomPosition(i)) for i in range(mol.GetNumAtoms())])
        chosen_score = _min_pairwise_distance_2d(rotated[heavy_mask])

        assert chosen_score == pytest.approx(best_candidate_score)
