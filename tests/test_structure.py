import numpy as np
import pytest
from rdkit import Chem

from molweigh.core import lineart_render, structure_3d
from molweigh.core.structure import (
    _min_pairwise_distance_2d,
    build_molblock_from_scene,
    generate_preview_svg,
    orient_canonically,
    parse_smiles,
    rasterize_svg,
    realign_bridged_structure_molblock,
    render_structure_image,
    smiles_from_molblock,
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


class TestSmilesFromMolblock:
    def test_preserves_wedge_based_stereochemistry(self):
        from rdkit.Chem import AllChem

        mol = Chem.MolFromSmiles("C[C@H](N)C(=O)O")  # L-アラニン
        AllChem.Compute2DCoords(mol)
        Chem.WedgeMolBonds(mol, mol.GetConformer())
        molblock = Chem.MolToMolBlock(mol)

        result = smiles_from_molblock(molblock)

        assert "@" in result
        assert Chem.MolToSmiles(Chem.MolFromSmiles(result)) == Chem.MolToSmiles(
            Chem.MolFromSmiles("C[C@H](N)C(=O)O")
        )

    def test_invalid_molblock_raises(self):
        with pytest.raises(ValueError):
            smiles_from_molblock("not a molblock")


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


class TestGeneratePreviewSvg:
    def test_returns_svg_string(self, qapp):
        svg = generate_preview_svg("CCO")
        assert svg.startswith("<svg")
        assert svg.rstrip().endswith("</svg>")

    def test_invalid_smiles_raises(self, qapp):
        with pytest.raises(ValueError):
            generate_preview_svg("not-a-smiles(((")

    def test_render_mode_forces_solid(self, qapp):
        # ベンゼンは平面判定になるはずだが、mode="solid"を明示すれば立体化する。
        flat_svg = generate_preview_svg("c1ccccc1", render_mode="flat")
        solid_svg = generate_preview_svg("c1ccccc1", render_mode="solid")
        assert flat_svg != solid_svg


class TestRasterizeSvg:
    def test_rasterizes_to_requested_size(self, qapp):
        svg = generate_preview_svg("CCO")
        pixmap = rasterize_svg(svg, (90, 70))
        assert not pixmap.isNull()
        assert pixmap.width() == 90
        assert pixmap.height() == 70


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


class TestBuildMolblockFromScene:
    def test_identity_rotation_matches_scene_xy(self):
        scene = lineart_render.build_scene("CCO", mode="auto")
        molblock = build_molblock_from_scene(scene)

        assert "V2000" in molblock
        mol = Chem.MolFromMolBlock(molblock)
        assert mol is not None
        assert mol.GetNumAtoms() == len(scene.coords)
        conformer = mol.GetConformer()
        rotated = scene.coords @ scene.initial_rotation.T
        for i in range(len(scene.coords)):
            pos = conformer.GetAtomPosition(i)
            # MOLブロックは座標を小数点以下4桁に丸めて保存する。
            assert pos.x == pytest.approx(rotated[i, 0], abs=1e-3)
            assert pos.y == pytest.approx(rotated[i, 1], abs=1e-3)
            assert pos.z == pytest.approx(0.0)

    def test_bond_orders_preserved(self):
        scene = lineart_render.build_scene("C=O", mode="flat")
        molblock = build_molblock_from_scene(scene)
        mol = Chem.MolFromMolBlock(molblock)
        assert mol is not None
        bond = mol.GetBondWithIdx(0)
        assert bond.GetBondTypeAsDouble() == pytest.approx(2.0)

    def test_formal_charge_preserved(self):
        scene = lineart_render.build_scene("CC(=O)[O-].[Na+]", mode="auto")
        molblock = build_molblock_from_scene(scene)
        mol = Chem.MolFromMolBlock(molblock)
        assert mol is not None
        assert Chem.rdMolDescriptors.CalcMolFormula(mol) == "C2H3NaO2"

    def test_rotation_changes_output_coordinates(self):
        scene = lineart_render.build_scene("c1ccc2c(c1)C1c3ccccc3C2c2ccccc21", mode="solid")
        identity_block = build_molblock_from_scene(scene, rotation=(1, 0, 0, 0))
        rotated_block = build_molblock_from_scene(scene, rotation=(0.9, 0.3, 0.2, 0.1))
        assert identity_block != rotated_block


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
