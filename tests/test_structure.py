import numpy as np
import pytest
from rdkit import Chem

from molweigh.core import structure_3d
from molweigh.core.structure import (
    _min_pairwise_distance_2d,
    build_molblock_from_2d_layout,
    generate_3d_view,
    orient_canonically,
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

    def test_bridged_structure_auto_switches_to_solid_mode(self, qapp):
        # トリプチセン(bridgehead原子を持つ橋かけ構造)。平面レイアウトが
        # 破綻するため、自動的に立体線画(solidモード)へ切り替わる。
        triptycene = "c1ccc2c(c1)C1c3ccccc3C2c2ccccc21"
        pixmap = render_structure_image(triptycene, size=(300, 300))
        assert not pixmap.isNull()
        assert pixmap.width() == 300

    def test_flat_structure_stays_flat(self, qapp):
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


class TestGenerate3DView:
    def test_ethanol_has_no_explicit_hydrogens_in_view_data(self):
        molblock, view_data = generate_3d_view("CCO")
        assert len(view_data.atoms) == 3  # C, C, O only (Hs removed)
        assert {a.symbol for a in view_data.atoms} == {"C", "O"}

    def test_molblock_has_explicit_hydrogens(self):
        molblock, view_data = generate_3d_view("CCO")
        mol = Chem.MolFromMolBlock(molblock, removeHs=False)
        assert mol is not None
        assert mol.GetNumAtoms() > len(view_data.atoms)  # Hs included in molblock

    def test_bond_count_and_orders(self):
        molblock, view_data = generate_3d_view("C=O")
        assert len(view_data.bonds) == 1
        assert view_data.bonds[0].order == pytest.approx(2.0)

    def test_bridged_structure_succeeds(self):
        triptycene = "c1ccc2c(c1)C1c3ccccc3C2c2ccccc21"
        molblock, view_data = generate_3d_view(triptycene)
        assert len(view_data.atoms) == Chem.MolFromSmiles(triptycene).GetNumAtoms()
        assert len(view_data.bonds) > 0

    def test_invalid_smiles_raises(self):
        with pytest.raises(ValueError):
            generate_3d_view("not-a-smiles(((")

    def test_molblock_and_view_data_share_coordinate_frame(self):
        # generate_3d_view()のmolblock(水素付き)とview_data(重原子のみ)は、
        # 3Dmol.js側のクォータニオンをview_dataへそのまま適用できるよう、
        # 同一の正準向き・原点を共有していなければならない。
        molblock, view_data = generate_3d_view("CCO")
        mol = Chem.MolFromMolBlock(molblock, removeHs=False)
        heavy_atoms = [a for a in mol.GetAtoms() if a.GetSymbol() != "H"]
        conformer = mol.GetConformer()
        # MOLブロックは座標を小数点以下4桁に丸めて保存するため、往復後は
        # そのオーダーの誤差が生じる(許容誤差はそれを見込んだもの)。
        for heavy_atom, view_atom in zip(heavy_atoms, view_data.atoms):
            pos = conformer.GetAtomPosition(heavy_atom.GetIdx())
            assert pos.x == pytest.approx(view_atom.x, abs=1e-3)
            assert pos.y == pytest.approx(view_atom.y, abs=1e-3)
            assert pos.z == pytest.approx(view_atom.z, abs=1e-3)


class TestBuildMolblockFrom2DLayout:
    def test_uses_given_xy_as_2d_layout(self):
        molblock, view_data = generate_3d_view("CCO")
        layout = [(0.0, 0.0), (1.5, 0.0), (2.2, 1.2)]

        result_molblock = build_molblock_from_2d_layout("CCO", layout)

        assert "V2000" in result_molblock
        mol = Chem.MolFromMolBlock(result_molblock)
        assert mol is not None
        assert mol.GetNumAtoms() == len(view_data.atoms)
        conformer = mol.GetConformer()
        for i, (x, y) in enumerate(layout):
            pos = conformer.GetAtomPosition(i)
            assert pos.x == pytest.approx(x)
            assert pos.y == pytest.approx(y)
            assert pos.z == pytest.approx(0.0)

    def test_mismatched_layout_length_raises(self):
        with pytest.raises(ValueError):
            build_molblock_from_2d_layout("CCO", [(0.0, 0.0)])

    def test_invalid_smiles_raises(self):
        with pytest.raises(ValueError):
            build_molblock_from_2d_layout("not-a-smiles(((", [])


class TestOrientCanonically:
    def test_reorients_in_place(self):
        mol = structure_3d.embed_and_optimize("c1ccc2c(c1)C1c3ccccc3C2c2ccccc21")
        before = [list(mol.GetConformer().GetAtomPosition(i)) for i in range(mol.GetNumAtoms())]
        orient_canonically(mol)
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

        orient_canonically(mol)
        rotated = np.array([list(mol.GetConformer().GetAtomPosition(i)) for i in range(mol.GetNumAtoms())])
        chosen_score = _min_pairwise_distance_2d(rotated[heavy_mask])

        assert chosen_score == pytest.approx(best_candidate_score)
