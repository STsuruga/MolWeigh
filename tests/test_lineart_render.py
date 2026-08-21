from dataclasses import replace

import numpy as np
import pytest
from rdkit import Chem

from molweigh.core import lineart_render as lr


class TestBuildFlatScene:
    def test_benzene_has_six_atoms_and_bonds(self):
        scene, dmin, cross = lr.build_flat_scene("c1ccccc1")
        assert len(scene.coords) == 6
        assert len(scene.bonds) == 6
        assert dmin == pytest.approx(1.0, abs=0.05)
        assert cross == 0

    def test_invalid_smiles_raises(self):
        with pytest.raises(ValueError):
            lr.build_flat_scene("not-a-smiles(((")

    def test_carbon_atoms_have_no_label(self):
        scene, _, _ = lr.build_flat_scene("c1ccccc1")
        assert all(label == "" for label in scene.labels)

    def test_wedges_present_for_stereocenter(self):
        # L-アラニン(立体中心1つ)。楔形が1本以上あるはず。
        scene, _, _ = lr.build_flat_scene("C[C@H](N)C(=O)O")
        assert np.any(scene.wedges != 0)


class TestFlatVsSolidJudgment:
    """仕様書6.1節の判定表を回帰テストとして固定する。"""

    @pytest.mark.parametrize(
        "smiles,expected_mode",
        [
            ("c1ccccc1", "flat"),  # ベンゼン
            ("CN1C=NC2=C1C(=O)N(C(=O)N2C)C", "flat"),  # カフェイン
            ("CCCCCCCCCC", "flat"),  # デカン
            ("C1CCCCC1", "flat"),  # シクロヘキサン
            ("OCC1OC(O)C(O)C(O)C1O", "flat"),  # グルコース
            ("c1ccc2c(c1)C1c3ccccc3C2c2ccccc21", "solid"),  # トリプチセン
            ("C1C2CC3CC1CC(C2)C3", "solid"),  # アダマンタン
            ("CC1(C)C2CCC1(C)C(=O)C2", "solid"),  # カンファー
            ("C12C3C4C1C5C4C3C25", "solid"),  # キュバン
        ],
    )
    def test_auto_mode_matches_reference_table(self, smiles, expected_mode):
        scene, dmin, cross = lr.build_flat_scene(smiles)
        chosen = "flat" if (dmin >= lr.FLAT_DMIN_MIN and cross <= lr.FLAT_MAX_CROSSINGS) else "solid"
        assert chosen == expected_mode

    def test_camphor_needs_both_indicators(self):
        # カンファーは交差数はゼロだが原子間距離だけが破綻している
        # (交差数だけを見る実装だと見逃す、というのが仕様書の指摘)。
        scene, dmin, cross = lr.build_flat_scene("CC1(C)C2CCC1(C)C(=O)C2")
        assert cross == 0
        assert dmin < lr.FLAT_DMIN_MIN


class TestBuildScene:
    def test_flat_molecule_stays_flat(self):
        scene = lr.build_scene("c1ccccc1", mode="auto")
        assert np.allclose(scene.coords[:, 2], 0.0)

    def test_bridged_molecule_becomes_solid(self):
        triptycene = "c1ccc2c(c1)C1c3ccccc3C2c2ccccc21"
        scene = lr.build_scene(triptycene, mode="auto")
        assert not np.allclose(scene.coords[:, 2], 0.0)

    def test_force_flat_mode(self):
        triptycene = "c1ccc2c(c1)C1c3ccccc3C2c2ccccc21"
        scene = lr.build_scene(triptycene, mode="flat")
        assert np.allclose(scene.coords[:, 2], 0.0)

    def test_force_solid_mode(self):
        scene = lr.build_scene("c1ccccc1", mode="solid")
        # solidモードは3D埋め込みなので厳密平面にはならない
        assert len(scene.coords) == 6

    def test_invalid_smiles_raises(self):
        with pytest.raises(ValueError):
            lr.build_scene("not-a-smiles(((")

    def test_salt_fragments_do_not_overlap(self):
        # 酢酸ナトリウム: フラグメントが横並びに配置され、重ならないこと
        scene = lr.build_scene("CC(=O)[O-].[Na+]", mode="auto")
        xs = scene.coords[:, 0]
        assert xs.max() - xs.min() > 2.0  # 重なっていれば幅が小さいまま

    def test_single_atom_fragment_has_no_bonds_and_no_index_error(self):
        scene = lr.build_scene("O.[Na+]", mode="auto")
        assert scene.bonds.shape[1] == 2

    def test_hydrate_label_puts_hydrogen_first(self):
        scene = lr.build_scene("CC(=O)O.O", mode="auto")
        assert "OH2" in scene.labels or "H2O" in scene.labels


def _molblock_for(smiles: str):
    from rdkit import Chem
    from rdkit.Chem import AllChem

    mol = Chem.MolFromSmiles(smiles)
    AllChem.Compute2DCoords(mol)
    return mol, Chem.MolToMolBlock(mol)


class TestBuildSceneFromMolblock:
    """フェーズ3(molblock一次表現化): Ketcherの2D座標をそのまま使う経路。"""

    def test_uses_provided_2d_coordinates_instead_of_regenerating(self):
        from rdkit import Chem

        mol, _ = _molblock_for("c1ccccc1CCO")
        conf = mol.GetConformer()
        for i in range(mol.GetNumAtoms()):  # 90度回転させ、CoordGen再生成との区別を付ける
            p = conf.GetAtomPosition(i)
            conf.SetAtomPosition(i, (-p.y, p.x, 0.0))
        molblock = Chem.MolToMolBlock(mol)

        scene = lr.build_scene("c1ccccc1CCO", mode="auto", molblock=molblock)
        rotated = np.array([list(conf.GetAtomPosition(i))[:2] for i in range(mol.GetNumAtoms())])
        rotated -= rotated.mean(axis=0)
        assert np.allclose(np.sort(scene.coords[:, :2], axis=0), np.sort(rotated, axis=0), atol=1e-3)

    def test_invalid_molblock_returns_none(self):
        assert lr.build_flat_scene_from_molblock("not a molblock") is None

    def test_falls_back_to_smiles_path_when_molblock_invalid(self):
        scene = lr.build_scene("c1ccccc1", mode="auto", molblock="not a molblock")
        assert len(scene.coords) == 6

    def test_overlapping_molblock_fragments_fall_back_to_auto_arrangement(self):
        # 水和物のフラグメントをmolblock内でわざと重ねて配置(Ketcherで整理し忘れた想定)。
        # auto判定のdminが破綻を検知し、既存のSMILES経由の自動横並び配置にフォールバックする。
        from rdkit import Chem

        mol, _ = _molblock_for("CC(=O)O.O")
        conf = mol.GetConformer()
        frags = Chem.GetMolFrags(mol)
        main_atoms = [g for g in frags if len(g) > 1][0]
        cx = sum(conf.GetAtomPosition(i).x for i in main_atoms) / len(main_atoms)
        cy = sum(conf.GetAtomPosition(i).y for i in main_atoms) / len(main_atoms)
        for group in frags:
            if len(group) == 1:
                for i in group:
                    conf.SetAtomPosition(i, (cx, cy, 0.0))
        molblock = Chem.MolToMolBlock(mol)

        scene = lr.build_scene("CC(=O)O.O", mode="auto", molblock=molblock)
        xs = scene.coords[:, 0]
        assert xs.max() - xs.min() > 2.0  # 自動配置にフォールバックしていれば重ならない

    def test_chirality_preserved_through_molblock_round_trip(self):
        # キラル分子(アラニン)。molblock経由でもSMILES立体表記が変化しないこと。
        from rdkit import Chem
        from rdkit.Chem import AllChem

        smiles = "C[C@@H](N)C(=O)O"
        mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
        AllChem.Compute2DCoords(mol)
        Chem.WedgeMolBonds(mol, mol.GetConformer())
        molblock = Chem.MolToMolBlock(mol, kekulize=True)

        scene = lr.build_scene(smiles, mode="auto", molblock=molblock)
        assert np.any(scene.wedges != 0)

    def test_hydrate_label_puts_hydrogen_first(self):
        _, molblock = _molblock_for("CC(=O)O.O")
        scene = lr.build_scene("CC(=O)O.O", mode="auto", molblock=molblock)
        assert "H2O" in scene.labels


class TestRenderSvg:
    def test_returns_valid_svg_wrapper(self):
        scene = lr.build_scene("CCO", mode="auto")
        svg = lr.render_svg(scene)
        assert svg.startswith("<svg")
        assert svg.rstrip().endswith("</svg>")

    def test_respects_custom_size(self):
        scene = lr.build_scene("CCO", mode="auto")
        svg = lr.render_svg(scene, params=lr.RenderParams(width=90, height=70))
        assert 'width="90"' in svg
        assert 'height="70"' in svg

    def test_rotation_changes_output(self):
        scene = lr.build_scene("c1ccc2c(c1)C1c3ccccc3C2c2ccccc21", mode="auto")
        svg_identity = lr.render_svg(scene, q=(1, 0, 0, 0))
        svg_rotated = lr.render_svg(scene, q=(0.9, 0.3, 0.2, 0.1))
        assert svg_identity != svg_rotated

    def test_all_rotations_render_without_complex_number_error(self):
        # depth_t()の(zv-zmin)/zspanは数学的には[0,1]のはずだが、隠線ギャップの
        # 補間点では浮動小数点誤差でわずかに範囲外になることがあり、それを
        # 分数乗(depth_gamma)すると複素数になりTypeErrorで落ちていた回帰。
        scene = lr.build_scene("CC(=O)O", mode="solid")
        for angle_deg in range(0, 360, 5):
            angle = np.radians(angle_deg)
            q = (np.cos(angle / 2), np.sin(angle / 2), 0.0, 0.0)
            lr.render_svg(scene, q=q)  # 例外が出なければOK

    def test_double_bond_renders_two_lines_minimum(self):
        scene = lr.build_scene("C=C", mode="flat")
        svg = lr.render_svg(scene)
        assert svg.count("<line") >= 2

    def test_wedge_renders_filled_triangle(self):
        scene, _, _ = lr.build_flat_scene("C[C@H](N)C(=O)O")
        svg = lr.render_svg(scene)
        assert "<path" in svg

    def test_atom_label_appears_as_text(self):
        scene = lr.build_scene("CCO", mode="flat")
        svg = lr.render_svg(scene)
        assert "<text" in svg
        assert ">O<" in svg or "O</text>" in svg or "OH" in svg


class TestQuatToMatrix:
    def test_identity_quaternion_gives_identity_matrix(self):
        m = lr.quat_to_matrix((1, 0, 0, 0))
        assert np.allclose(m, np.eye(3))

    def test_returns_orthonormal_matrix(self):
        m = lr.quat_to_matrix((0.7, 0.3, 0.5, 0.1))
        assert np.allclose(m @ m.T, np.eye(3), atol=1e-6)


class TestCanonicalRotation:
    def test_symmetric_molecule_does_not_degenerate(self):
        # トリプチセンのような対称分子でPCA縮退の影響を受けないこと
        # (退化した固有ベクトルで潰れた向きにならない)。
        scene = lr.build_scene("c1ccc2c(c1)C1c3ccccc3C2c2ccccc21", mode="solid")
        rotated = scene.coords @ scene.initial_rotation.T
        xy = rotated[:, :2]
        d = xy[:, None, :] - xy[None, :, :]
        dist = np.sqrt((d**2).sum(-1))
        np.fill_diagonal(dist, np.inf)
        assert dist.min() > 0.3  # 潰れていれば非常に小さい値になる


class TestRotationMatchingDrawing:
    """フェーズ6(Stage 2): 橋かけ構造などsolidモードでも、molblockの2D座標に
    近い3D姿勢をKabsch法で選ぶ。"""

    def test_kabsch_rotation_recovers_known_rotation(self):
        rng = np.random.default_rng(0)
        X = rng.normal(size=(8, 3))
        X -= X.mean(axis=0)
        # 既知の回転(適当なオイラー角)
        a, b, g = 0.3, 0.5, -0.2
        Rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
        Ry = np.array([[np.cos(b), 0, np.sin(b)], [0, 1, 0], [-np.sin(b), 0, np.cos(b)]])
        Rx = np.array([[1, 0, 0], [0, np.cos(g), -np.sin(g)], [0, np.sin(g), np.cos(g)]])
        R_true = Rz @ Ry @ Rx
        Y = X @ R_true.T

        R_est = lr._kabsch_rotation(X, Y)
        assert np.allclose(R_est, R_true, atol=1e-8)
        assert np.linalg.det(R_est) == pytest.approx(1.0, abs=1e-8)  # 鏡像解を除外できている

    def test_solid_with_molblock_stays_readable_for_bridged_molecule(self):
        # トリプチセン: Kabsch解を初期値にした狭い局所探索では、CoordGenの
        # 破綻したレイアウト(auto判定でsolidに切り替わった原因そのもの)に
        # 引きずられて読みにくい向きに落ち込んだ(実測で確認済みの回帰)。
        # 全方位探索+描画との近さペナルティに変更したことで、既存の
        # canonical_rotation相当の読みやすさを維持できることを確認する。
        smi = "c1ccc2c(c1)C1c3ccccc3C2c2ccccc21"
        _, molblock = _molblock_for(smi)
        scene = lr.build_scene(smi, mode="solid", molblock=molblock)
        xy = (scene.coords @ scene.initial_rotation.T)[:, :2]
        d = xy[:, None, :] - xy[None, :, :]
        dist = np.sqrt((d**2).sum(-1))
        np.fill_diagonal(dist, np.inf)
        assert dist.min() > 0.3  # 潰れていれば非常に小さい値になる

    @pytest.mark.parametrize(
        "smiles",
        [
            "c1ccc2c(c1)C1c3ccccc3C2c2ccccc21",  # トリプチセン
            "C1C2CC3CC1CC(C2)C3",  # アダマンタン
            "CC1(C)C2CCC1(C)C(=O)C2",  # カンファー
            "C12C3C4C1C5C4C3C25",  # キュバン
        ],
    )
    def test_matches_atom_count_of_plain_solid_mode(self, smiles):
        _, molblock = _molblock_for(smiles)
        scene_plain = lr.build_scene(smiles, mode="solid")
        scene_matched = lr.build_scene(smiles, mode="solid", molblock=molblock)
        assert len(scene_matched.coords) == len(scene_plain.coords)
        assert not np.isnan(scene_matched.coords).any()

    def test_chirality_preserved(self):
        # キラル分子はソースの都合上flatになりやすいので、橋かけ+キラル中心を
        # 持つ構造で確認する必要はないが、少なくとも解析でエラーにならず
        # 立体表記が変化しないことを確認する。
        smi = "C[C@@H](N)C(=O)O"
        _, molblock = _molblock_for(smi)
        scene = lr.build_scene(smi, mode="solid", molblock=molblock)
        mol = lr.scene_to_mol(scene)
        Chem.AssignStereochemistryFrom3D(mol)
        assert Chem.MolToSmiles(mol) == Chem.CanonSmiles(smi)

    def test_invalid_molblock_falls_back_to_smiles_path(self):
        smi = "c1ccc2c(c1)C1c3ccccc3C2c2ccccc21"
        scene = lr.build_scene(smi, mode="solid", molblock="not a molblock")
        assert len(scene.coords) == 20  # トリプチセンの重原子数


class TestRecomputeInitialRotation:
    def test_keeps_coords_unchanged(self):
        scene = lr.build_scene("CCCCCCCCCC", mode="solid")
        result = lr.recompute_initial_rotation(scene)
        assert np.array_equal(result.coords, scene.coords)

    def test_recomputes_rotation_matrix(self):
        scene = lr.build_scene("CCCCCCCCCC", mode="solid")
        # わざと崩れた初期姿勢にしてから再計算し、単位行列以外に変わることを確認する。
        scrambled = replace(scene, initial_rotation=np.eye(3))
        result = lr.recompute_initial_rotation(scrambled)
        assert not np.allclose(result.initial_rotation, np.eye(3))


class TestSceneToMol:
    def test_roundtrip_preserves_atom_and_bond_count(self):
        scene = lr.build_scene("CCO", mode="solid")
        mol = lr.scene_to_mol(scene)
        assert mol.GetNumAtoms() == len(scene.coords)
        assert mol.GetNumBonds() == len(scene.bonds)

    def test_flatten_zeroes_z_coordinate(self):
        scene = lr.build_scene("c1ccc2c(c1)C1c3ccccc3C2c2ccccc21", mode="solid")
        mol = lr.scene_to_mol(scene, flatten=True)
        conf = mol.GetConformer()
        assert all(abs(conf.GetAtomPosition(i).z) < 1e-9 for i in range(mol.GetNumAtoms()))


class TestCleanupGeometry:
    """フェーズ4: 3Dタブのクリーンアップ機能(向きを整える/形を整える/配座を選び直す)。"""

    def test_optimize_preserves_chirality(self):
        # キラル分子(アラニン)。MMFF最適化前後でCIP/立体表記が変化しないこと。
        scene = lr.build_scene("C[C@@H](N)C(=O)O", mode="solid")
        result = lr.cleanup_geometry(scene, mode="optimize")
        assert result.stereo_changed is False

    def test_optimize_does_not_change_atom_count(self):
        scene = lr.build_scene("CCCCCCCCCC", mode="solid")
        result = lr.cleanup_geometry(scene, mode="optimize")
        assert len(result.scene.coords) == len(scene.coords)

    def test_reembed_preserves_chirality(self):
        scene = lr.build_scene("C[C@@H](N)C(=O)O", mode="solid")
        result = lr.cleanup_geometry(scene, mode="reembed")
        assert result.stereo_changed is False

    def test_reembed_handles_salt_fragments_without_crashing(self):
        scene = lr.build_scene("CC(=O)[O-].[Na+]", mode="solid")
        result = lr.cleanup_geometry(scene, mode="reembed")
        assert len(result.scene.coords) == len(scene.coords)

    def test_optimize_handles_salt_fragments_without_crashing(self):
        scene = lr.build_scene("CC(=O)[O-].[Na+]", mode="solid")
        result = lr.cleanup_geometry(scene, mode="optimize")
        assert len(result.scene.coords) == len(scene.coords)

    def test_does_not_mutate_original_scene(self):
        scene = lr.build_scene("CCCCCCCCCC", mode="solid")
        original_coords = scene.coords.copy()
        lr.cleanup_geometry(scene, mode="optimize")
        assert np.array_equal(scene.coords, original_coords)


class TestGetOrBuildScene:
    """フェーズ5(Stage 3): render_structure_image/generate_preview_svg/3Dタブが
    それぞれ個別にbuild_sceneを呼んでいた計算を1回に集約するキャッシュ。"""

    def setup_method(self):
        lr.clear_scene_cache()

    def teardown_method(self):
        lr.clear_scene_cache()

    def test_same_key_returns_identical_cached_object(self):
        a = lr.get_or_build_scene("CCO", mode="auto")
        b = lr.get_or_build_scene("CCO", mode="auto")
        assert a is b

    def test_different_mode_is_a_cache_miss(self):
        a = lr.get_or_build_scene("CCO", mode="flat")
        b = lr.get_or_build_scene("CCO", mode="solid")
        assert a is not b

    def test_different_molblock_is_a_cache_miss(self):
        a = lr.get_or_build_scene("CCO", mode="auto", molblock=None)
        b = lr.get_or_build_scene("CCO", mode="auto", molblock="not a molblock")
        assert a is not b

    def test_clear_scene_cache_forces_rebuild(self):
        a = lr.get_or_build_scene("CCO", mode="auto")
        lr.clear_scene_cache()
        b = lr.get_or_build_scene("CCO", mode="auto")
        assert a is not b
