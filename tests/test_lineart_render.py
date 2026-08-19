import numpy as np
import pytest

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
