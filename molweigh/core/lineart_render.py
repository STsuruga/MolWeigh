"""ChemDraw風 線画レンダラ(Qt非依存 / SVG出力)。

平面構造式(楔形つき)と、3D配座を正射影した立体線画(隠線ギャップ・深度
キューつき)の両方を、同じジオメトリパイプラインで描く。`build_scene()`が
分子1つ分の前計算済みシーンを作り、`render_svg()`が任意の回転(クォータ
ニオン)を適用してSVG文字列化する。回転は非破壊(`Scene.coords`自体は
書き換えない)なので、やり直し・保存・比較が素直にできる。

`core/structure.py::render_structure_image()`が主な呼び出し元(唯一の
共通レンダリング入口)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Literal, Sequence

import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem, rdDepictor
from rdkit.Geometry import Point3D

# --------------------------------------------------------------------------
# 3D配座生成(見やすさ優先。core/structure_3d.pyとは別経路)
# --------------------------------------------------------------------------

ETKDG_SEED = 0xC0FFEE


def _clarity(coords: np.ndarray, n_dir: int = 48) -> tuple[float, np.ndarray]:
    """その配座の「一番見やすい向き」のスコアと回転行列を返す。

    スコア = 最良視線方向における、2D投影後の全原子ペア最小距離。
    大きいほど原子が重ならず、線が潰れずに見える。
    """
    c = coords - coords.mean(axis=0)
    best, bestR = -np.inf, np.eye(3)
    for d in _fibonacci_directions(n_dir):
        R = _basis_from_view(d)
        sc = _min_pairwise_distance_2d((c @ R.T)[:, :2])
        if sc > best:
            best, bestR = sc, R
    return best, bestR


def embed_and_optimize(smiles: str, n_confs: int = 24, sanity_window: float = 40.0) -> tuple[Chem.Mol, np.ndarray]:
    """見やすさ優先で3D配座を選ぶ。配座と初期姿勢を同時に決める。

    MolWeighが3D構造に求めるのは「試薬の構造が一目で分かること」であり、
    最安定配座の厳密さではない。そこで力場は「破綻した形を弾く」役割に留め、
    採用する配座は投影したときの見やすさ(`_clarity`)で選ぶ。
    `sanity_window`は明らかに歪んだ配座を除くための緩い上限にすぎない。

    単一配座のETKDGでは鎖状分子がゴーシュに折れることがある(デカンで
    二面角が-60,-60,-175,-179,180,97,-64となることを実測確認済み)。
    化学者が期待するのは伸びたall-antiのジグザグなので、複数配座からの
    選択は必須。
    """
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"SMILES解析に失敗: {smiles}")
    mol = Chem.AddHs(mol)

    ps = AllChem.ETKDGv3()
    ps.randomSeed = ETKDG_SEED  # 再現性
    ps.numThreads = 0  # 0 = システムが対応する最大コア数を使う
    cids = list(AllChem.EmbedMultipleConfs(mol, numConfs=n_confs, params=ps))
    if not cids:
        ps.useRandomCoords = True
        cids = list(AllChem.EmbedMultipleConfs(mol, numConfs=n_confs, params=ps))
    if not cids:
        raise ValueError("3D埋め込みに失敗")

    if AllChem.MMFFHasAllMoleculeParams(mol):
        res = AllChem.MMFFOptimizeMoleculeConfs(mol, numThreads=0, maxIters=2000)
    else:
        res = AllChem.UFFOptimizeMoleculeConfs(mol, numThreads=0, maxIters=2000)
    energies = [e for _, e in res]
    emin = min(energies)
    ok = [c for c, e in zip(cids, energies) if e - emin <= sanity_window] or cids

    heavy = [a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() > 1]
    scored = [(*_clarity(np.array(mol.GetConformer(c).GetPositions())[heavy]), c) for c in ok]
    _, bestR, best = max(scored, key=lambda t: t[0])

    keep = Chem.Mol(mol)
    keep.RemoveAllConformers()
    conf = Chem.Conformer(mol.GetConformer(best))
    conf.SetId(0)
    keep.AddConformer(conf, assignId=True)
    return keep, bestR


# --------------------------------------------------------------------------
# 初期姿勢の決定
# --------------------------------------------------------------------------


def _min_pairwise_distance_2d(xy: np.ndarray) -> float:
    d = xy[:, None, :] - xy[None, :, :]
    dist = np.sqrt((d**2).sum(-1))
    np.fill_diagonal(dist, np.inf)
    return float(dist.min())


def _fibonacci_directions(n: int) -> np.ndarray:
    """半球上のほぼ均等な視線方向 (n,3)。逆向きは同じ絵になるので半球で足りる。"""
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - i / n)
    theta = np.pi * (1 + 5**0.5) * i
    return np.column_stack([np.sin(phi) * np.cos(theta), np.sin(phi) * np.sin(theta), np.cos(phi)])


def _basis_from_view(d: np.ndarray) -> np.ndarray:
    d = d / np.linalg.norm(d)
    tmp = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(tmp, d)) > 0.9:
        tmp = np.array([1.0, 0.0, 0.0])
    x = np.cross(tmp, d)
    x /= np.linalg.norm(x)
    return np.column_stack([x, np.cross(d, x), d]).T


def _in_plane_align(xy: np.ndarray) -> np.ndarray:
    """投影の長軸を画面横方向に合わせる面内回転 (3,3)。"""
    c = xy - xy.mean(0)
    cov = c.T @ c / max(len(c), 1)
    _, v = np.linalg.eigh(cov)
    major = v[:, -1]
    a = np.arctan2(major[1], major[0])
    ca, sa = np.cos(-a), np.sin(-a)
    return np.array([[ca, -sa, 0], [sa, ca, 0], [0, 0, 1]])


def canonical_rotation(coords: np.ndarray, bonds: np.ndarray, n_dir: int = 160) -> np.ndarray:
    """原子同士が2D投影で最も重なりにくい向きの回転行列 (3,3) を返す。

    PCAの3主軸から3候補だけを試す旧方式は使わない。トリプチセンのような
    対称分子は共分散行列の固有値が縮退し、固有ベクトルが不定になるため
    機能しない。視線方向を球面上に密サンプリングして総当たりする。
    """
    if len(coords) < 3:
        return np.eye(3)
    c = coords - coords.mean(axis=0)
    best_score, best_R = -np.inf, np.eye(3)
    for d in _fibonacci_directions(n_dir):
        R = _basis_from_view(d)
        xy = (c @ R.T)[:, :2]
        score = _min_pairwise_distance_2d(xy)
        if score > best_score:
            best_score, best_R = score, R
    return _in_plane_align((c @ best_R.T)[:, :2]) @ best_R


# --------------------------------------------------------------------------
# 初期姿勢の決定(Kabsch法によるKetcher描画向きとの一致、Stage 2)
# --------------------------------------------------------------------------

_DRAWING_MATCH_LAMBDA = 0.4  # 見やすさ(clarity)と描いた向きとの一致度のバランス


def _kabsch_rotation(X: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """X(3D配座)をY(2D+z=0)に最も近づける回転行列を返す。

    XとYは同じ原子順序で対応が取れており、両方とも重心が原点に移動済みで
    あること。鏡像解(det=-1)を除外し、立体化学の反転を防ぐ。
    """
    H = X.T @ Y
    U, S, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T)) or 1.0
    D = np.diag([1.0, 1.0, d])
    return Vt.T @ D @ U.T


def _rotation_matching_drawing(coords: np.ndarray, drawn_xy: np.ndarray, n_dir: int = 160) -> tuple[np.ndarray, float]:
    """「描いた向きに近く、かつ見やすい」3D姿勢の回転行列とスコアを返す。

    `coords`(3D配座)と`drawn_xy`(molblockの2D座標)は同じ原子順序で対応が
    取れていること。

    当初はKabsch法で得た回転を初期値に±20°の局所探索で補正する設計だった
    (改善提案書の案)が、実測でトリプチセンのような橋かけ構造では機能しない
    ことが判明した: molblockの2D座標自体がCoordGenによる破綻したレイアウト
    (auto判定で立体化に切り替わった原因そのもの)であることが多く、Kabsch解が
    最初から悪い向きになり、狭い局所探索ではそこから抜け出せず
    `canonical_rotation`の全方位探索より明らかに読みにくい結果になった。
    そのため`canonical_rotation`と同じFibonacci格子160方向の全探索に、
    「描いた向きとの近さ」のペナルティ項を加える方式に変更した(Kabsch解も
    候補の1つとして含める)。計算量はKabsch局所探索案より増えるが、
    `canonical_rotation`と同等(実測で誤差の範囲)。
    `canonical_rotation`と違い`_in_plane_align`は適用しない(適用すると
    描いた向きとの一致がずれてしまうため)。
    """
    c = coords - coords.mean(axis=0)
    y = drawn_xy - drawn_xy.mean(axis=0)
    y3 = np.zeros((len(y), 3))
    y3[:, :2] = y

    candidates = [_kabsch_rotation(c, y3)] + [_basis_from_view(d) for d in _fibonacci_directions(n_dir)]
    best_score, best_R = -np.inf, candidates[0]
    for R in candidates:
        xy = (c @ R.T)[:, :2]
        clarity_score = _min_pairwise_distance_2d(xy)
        rmsd = float(np.sqrt(((xy - y) ** 2).sum(axis=1).mean()))
        score = clarity_score - _DRAWING_MATCH_LAMBDA * rmsd
        if score > best_score:
            best_score, best_R = score, R
    return best_R, best_score


# --------------------------------------------------------------------------
# シーン(レンダリング用の前計算済みデータ)
# --------------------------------------------------------------------------


@dataclass
class Scene:
    coords: np.ndarray  # (n_atoms, 3) 重心を原点に移動済み・水素除去済み
    symbols: list[str]
    labels: list[str]  # 表示用ラベル(炭素は空文字)。例: O, OH, H2O
    charges: list[str]  # 電荷の上付き文字(表示用)。例: +, 2-
    formal_charges: list[int]  # 実際の形式電荷(RWMol再構築時にRDKitへ渡す用)
    wedges: np.ndarray  # (n_bonds,) 0=通常, +1=実楔(手前), -1=破線楔(奥)
    bonds: np.ndarray  # (n_bonds, 2) int
    orders: np.ndarray  # (n_bonds,) int 1/2/3 (芳香環はケクレ化済み)
    ring_center: np.ndarray  # (n_bonds, 3) 環結合なら環重心、非環はnan
    initial_rotation: np.ndarray  # (3, 3)
    bond_length: float  # 標準結合長(Å)。スケール決定に使う


def _layout_quality(coords2d: np.ndarray, bonds: np.ndarray) -> tuple[float, int]:
    """平面レイアウトの破綻度。(最小原子間距離 / 標準結合長, 結合交差数)"""
    if len(bonds) == 0:
        return 1.0, 0
    bl = float(np.median(np.linalg.norm(coords2d[bonds[:, 0]] - coords2d[bonds[:, 1]], axis=1))) or 1.0
    dmin = _min_pairwise_distance_2d(coords2d) / bl

    P = coords2d[bonds[:, 0]]
    D = coords2d[bonds[:, 1]] - P
    cr = lambda A, B: A[..., 0] * B[..., 1] - A[..., 1] * B[..., 0]  # noqa: E731
    with np.errstate(divide="ignore", invalid="ignore"):
        den = cr(D[:, None], D[None, :])
        diff = P[None, :] - P[:, None]
        t = cr(diff, D[None, :]) / den
        u = cr(diff, D[:, None]) / den
    E = 1e-6
    hit = (np.abs(den) > E) & (t > E) & (t < 1 - E) & (u > E) & (u < 1 - E)
    shared = (bonds[:, None, :, None] == bonds[None, :, None, :]).any(-1).any(-1)
    return dmin, int(np.triu(hit & ~shared, 1).sum())


# 平面レイアウトが「破綻している」とみなす閾値
FLAT_DMIN_MIN = 0.42  # 原子間距離が標準結合長の42%を切ったら重なりとみなす
FLAT_MAX_CROSSINGS = 0  # 結合が1本でも交差したら破綻


def _scene_from_mol(mol: Chem.Mol, coords: np.ndarray, rotation: np.ndarray, wedges: np.ndarray) -> Scene:
    # 「単原子フラグメント(対イオン・結晶水)か」はmol全体ではなく連結成分ごとに
    # 判定する。molblock由来のシーンは塩・水和物を分割せず1つのmolとして渡す
    # ことがあるため(通常のSMILES経路は事前にフラグメント分割済みで常に単一
    # 連結成分だが、その場合でもこの判定は従来と同じ結果になる)。
    lone_atoms = {idx for group in Chem.GetMolFrags(mol) if len(group) == 1 for idx in group}

    def _label(a: Chem.Atom) -> str:
        n = a.GetTotalNumHs()
        is_lone = a.GetIdx() in lone_atoms
        if a.GetSymbol() == "C" and a.GetFormalCharge() == 0 and not is_lone:
            return ""
        h = "" if n == 0 else "H" if n == 1 else f"H{n}"
        return (h + a.GetSymbol()) if is_lone else (a.GetSymbol() + h)

    def _charge(a: Chem.Atom) -> str:
        c = a.GetFormalCharge()
        if c == 0:
            return ""
        sign = "+" if c > 0 else "−"
        return sign if abs(c) == 1 else f"{abs(c)}{sign}"

    ri = mol.GetRingInfo()
    rings = [np.array(r, dtype=int) for r in ri.AtomRings()]
    bonds, orders, centers = [], [], []
    for b in mol.GetBonds():
        i, j = b.GetBeginAtomIdx(), b.GetEndAtomIdx()
        bonds.append((i, j))
        orders.append(int(round(b.GetBondTypeAsDouble())))
        c = np.full(3, np.nan)
        for r in rings:
            if i in r and j in r:
                c = coords[r].mean(axis=0)
        centers.append(c)
    bonds = np.array(bonds, dtype=int).reshape(-1, 2)
    lengths = (
        np.linalg.norm(coords[bonds[:, 0]] - coords[bonds[:, 1]], axis=1) if len(bonds) else np.array([1.5])
    )
    return Scene(
        coords=coords,
        symbols=[a.GetSymbol() for a in mol.GetAtoms()],
        labels=[_label(a) for a in mol.GetAtoms()],
        charges=[_charge(a) for a in mol.GetAtoms()],
        formal_charges=[a.GetFormalCharge() for a in mol.GetAtoms()],
        wedges=wedges,
        bonds=bonds,
        orders=np.array(orders, dtype=int).reshape(-1),
        ring_center=np.array(centers, dtype=float).reshape(-1, 3),
        initial_rotation=rotation,
        bond_length=float(np.median(lengths)),
    )


def _wedge_array(mol: Chem.Mol) -> np.ndarray:
    wedge_map = {Chem.BondDir.BEGINWEDGE: 1, Chem.BondDir.BEGINDASH: -1}
    return np.array([wedge_map.get(b.GetBondDir(), 0) for b in mol.GetBonds()], dtype=int).reshape(-1)


def build_flat_scene(smiles: str) -> tuple[Scene, float, int]:
    """従来型の平面構造式。RDKitの2Dレイアウト + 楔形。

    戻り値の2要素目以降はレイアウトの破綻度で、自動判定に使う。
    """
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"SMILES解析に失敗: {smiles}")
    rdDepictor.SetPreferCoordGen(True)  # CoordGenの方が環系の見た目が良い
    rdDepictor.Compute2DCoords(mol)
    Chem.WedgeMolBonds(mol, mol.GetConformer())
    Chem.Kekulize(mol, clearAromaticFlags=True)

    coords = np.array(mol.GetConformer().GetPositions())
    coords[:, 2] = 0.0
    coords -= coords.mean(axis=0)

    scene = _scene_from_mol(mol, coords, np.eye(3), _wedge_array(mol))
    dmin, cross = _layout_quality(coords[:, :2], scene.bonds)
    return scene, dmin, cross


def build_flat_scene_from_molblock(molblock: str) -> tuple[Scene, float, int] | None:
    """Ketcherの2Dレイアウト(molblock)をそのまま使う平面構造式。

    ユーザーが整えた向き・配置(塩や水和物を離して描いた場合の位置関係も含む)を
    そのまま座標として使い、CoordGenでの再レイアウトをスキップする。フラグメントを
    分割・再配置しないため(`_scene_from_mol`は連結成分をまたいでも動作する)、
    Ketcher上で重ねて描かれていた場合はそのまま重なった`dmin`/`cross`が返る。
    呼び出し側の`auto`判定がこれを検知すれば、自然に既存のSMILES経由の自動配置
    (`_arrange_fragments`)にフォールバックする。

    解析に失敗した場合はNoneを返し、呼び出し側にSMILES経由の通常経路を使わせる。
    """
    mol = Chem.MolFromMolBlock(molblock)
    if mol is None or mol.GetNumConformers() == 0:
        return None
    mol = Chem.RemoveHs(mol)
    Chem.Kekulize(mol, clearAromaticFlags=True)
    Chem.WedgeMolBonds(mol, mol.GetConformer())

    coords = np.array(mol.GetConformer().GetPositions())
    coords[:, 2] = 0.0
    coords -= coords.mean(axis=0)

    scene = _scene_from_mol(mol, coords, np.eye(3), _wedge_array(mol))
    dmin, cross = _layout_quality(coords[:, :2], scene.bonds)
    return scene, dmin, cross


def _arrange_fragments(frag_scenes: list[Scene], gap: float = 1.6) -> Scene:
    """塩や水和物を横並びに配置する。

    ETKDGはイオンや結晶水を分子本体の任意の位置に置くため、そのまま描くと
    対イオンが鎖の上に重なる。フラグメントごとに向きを決めてから、重原子数の
    多い順に左から並べ直す。
    """
    frag_scenes = sorted(frag_scenes, key=lambda s: -len(s.coords))
    coords, labels, charges, formal_charges, symbols, bonds, orders, centers, wedges = (
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
    )
    x_cursor, offset = 0.0, 0
    for sc in frag_scenes:
        c = sc.coords @ sc.initial_rotation.T  # 各自の見やすい向きを焼き込む
        c -= c.mean(axis=0)
        width = c[:, 0].max() - c[:, 0].min()
        c[:, 0] += x_cursor - c[:, 0].min()
        x_cursor += width + gap
        coords.append(c)
        labels += sc.labels
        charges += sc.charges
        formal_charges += sc.formal_charges
        wedges.append(sc.wedges)
        symbols += sc.symbols
        bonds.append(sc.bonds + offset)
        orders.append(sc.orders)
        rc = sc.ring_center @ sc.initial_rotation.T
        rc[:, 0] += x_cursor - width - gap
        centers.append(rc)
        offset += len(sc.coords)

    all_coords = np.vstack(coords)
    all_coords -= all_coords.mean(axis=0)
    return Scene(
        coords=all_coords,
        symbols=symbols,
        labels=labels,
        charges=charges,
        formal_charges=formal_charges,
        wedges=np.concatenate(wedges) if wedges else np.zeros(0, int),
        bonds=np.vstack(bonds) if bonds else np.zeros((0, 2), int),
        orders=np.concatenate(orders) if orders else np.zeros(0, int),
        ring_center=np.vstack(centers),
        initial_rotation=np.eye(3),  # 配置済みなので追加回転はしない
        bond_length=frag_scenes[0].bond_length,
    )


def build_scene(smiles: str, mode: str = "auto", molblock: str | None = None) -> Scene:
    """構造シーンを組み立てる。

    mode="flat"  従来型の平面構造式(楔形つき)
    mode="solid" 3D配座を正射影した立体線画
    mode="auto"  まず平面で描き、レイアウトが破綻していれば立体に切り替える
                 (シクロヘキサンやステロイドは非平面だが平面で描けるので平面のまま、
                  トリプチセンやアダマンタンのように環が重なるものだけ立体になる)

    `molblock`(Ketcherの2Dキャンバスから取得した座標つきのMOLブロック)を渡すと、
    flat/auto判定時にCoordGenでの再レイアウトをスキップし、ユーザーが整えた
    向き・配置をそのまま使う(SMILES経由では2D座標が失われ、描画のたびに
    向きが再生成されてしまう問題への対処)。molblockの解析に失敗した場合や
    立体化が必要と判定された場合は、通常のSMILES経由の経路にフォールバックする。
    `molblock`は座標(見た目)専用で、化合物の同一性判定には常にSMILESを使う。

    立体化が必要になった場合(橋かけ構造など2D座標をそのまま使えない分子)も、
    molblockがあれば「描いた向きに近い3D姿勢」をKabsch法で選ぶ
    (`_build_solid_scene_matching_drawing`、Stage 2)。失敗時は
    `canonical_rotation`による見やすさ最優先の従来経路にフォールバックする。
    """
    if molblock is not None and mode in ("flat", "auto"):
        from_molblock = build_flat_scene_from_molblock(molblock)
        if from_molblock is not None:
            flat, dmin, cross = from_molblock
            if mode == "flat" or (dmin >= FLAT_DMIN_MIN and cross <= FLAT_MAX_CROSSINGS):
                return flat

    parts = smiles.split(".")
    if len(parts) > 1:  # 塩・水和物・共結晶
        return _arrange_fragments([build_scene(p, mode) for p in parts if p])

    if mode in ("flat", "auto"):
        flat, dmin, cross = build_flat_scene(smiles)
        if mode == "flat" or (dmin >= FLAT_DMIN_MIN and cross <= FLAT_MAX_CROSSINGS):
            return flat

    if molblock is not None:
        matched = _build_solid_scene_matching_drawing(molblock)
        if matched is not None:
            return matched

    mol3d, coarse_R = embed_and_optimize(smiles)
    mol = Chem.RemoveHs(mol3d)
    Chem.Kekulize(mol, clearAromaticFlags=True)
    return _scene_from_mol3d(mol)


# --------------------------------------------------------------------------
# シーンキャッシュ(Stage 3): render_structure_image/generate_preview_svg/3D
# タブがそれぞれ個別にbuild_sceneを呼んでいた構造をやめ、計算を1回に集約する。
# --------------------------------------------------------------------------

# レンダラーの出力(見た目)が変わるような修正をするたびにインクリメントする。
# `LibraryEntry.renderer_version`と比較し、食い違えば保存済みpreview_svgを
# 自動で焼き直す(`ui/library_dialog.py`)。
CURRENT_RENDERER_VERSION = 1

_scene_cache: dict[tuple[str | None, str, str], Scene] = {}


def get_or_build_scene(smiles: str, mode: str = "auto", molblock: str | None = None) -> Scene:
    """`build_scene`の結果をインメモリでキャッシュする。

    `Scene`は生成後に書き換えられない設計(回転は非破壊、姿勢は別パラメータ
    として都度適用する)なので、複数の呼び出し元で同じインスタンスを安全に
    共有できる。キーに`molblock`を含めるため、Ketcherで構造を描き直せば
    (=molblockが変われば)別エントリとして扱われ、古い座標を誤って使い回す
    ことはない。
    """
    key = (molblock, smiles, mode)
    cached = _scene_cache.get(key)
    if cached is not None:
        return cached
    scene = build_scene(smiles, mode=mode, molblock=molblock)
    _scene_cache[key] = scene
    return scene


def clear_scene_cache() -> None:
    """インメモリのシーンキャッシュを全て破棄する(主にテスト用)。"""
    _scene_cache.clear()


def _scene_from_mol3d(mol: Chem.Mol, rotation: np.ndarray | None = None) -> Scene:
    """3D配座つきのMol(水素除去・Kekulize済み)からSceneを組み立てる。

    立体モード(`build_scene`)と3Dクリーンアップ機能(`cleanup_geometry`)の
    両方が使う共有経路。`rotation`省略時は`canonical_rotation`で初期姿勢を
    毎回再探索する(力場最適化やクリーンアップで形が変わるたびに見やすい
    向きも変わるため)。`rotation`を渡すとそれをそのまま採用する
    (`_build_solid_scene_matching_drawing`がKabsch法で得た回転を使う場合)。
    """
    conf = mol.GetConformer()
    coords = np.array(conf.GetPositions(), dtype=float)
    coords -= coords.mean(axis=0)
    bonds = np.array([(b.GetBeginAtomIdx(), b.GetEndAtomIdx()) for b in mol.GetBonds()], dtype=int).reshape(-1, 2)
    wedges = np.zeros(len(bonds), dtype=int)
    if rotation is None:
        rotation = canonical_rotation(coords, bonds)
    return _scene_from_mol(mol, coords, rotation, wedges)


def _build_solid_scene_matching_drawing(molblock: str, n_confs: int = 24, sanity_window: float = 40.0) -> Scene | None:
    """molblockの2D座標に最も近い3D姿勢を選んでSceneを組み立てる(Stage 2)。

    `embed_and_optimize`と違い、SMILESから独立に再パースしない
    (再パースすると原子の並び順が変わり、molblockの2D座標とKabsch法で
    対応が取れなくなるため)。`Chem.RemoveHs` → `Chem.AddHs`は既存原子の
    順序を変えない(新しい水素は末尾に追加される)ことを利用し、molblock
    由来の重原子2D座標と、これから生成する3D配座の重原子を同じ添字で
    対応づける。

    採用する配座・回転は、既存の見やすさ指標(`_min_pairwise_distance_2d`)と
    「描いた向きとの近さ」を両立するスコア(`_rotation_matching_drawing`)で
    選ぶ。molblockの解析に失敗した場合はNoneを返し、呼び出し側にSMILES経由の
    通常経路(`embed_and_optimize`)を使わせる。一方、3D埋め込み自体が失敗する
    場合はValueErrorを送出する(molblock経由かSMILES経由かに依らず同じ分子・
    立体配置で同じ結果になるため、Noneを返してフォールバックさせても
    embed_and_optimizeが同じ失敗を繰り返すだけで数秒の二度手間になる)。
    """
    mol = Chem.MolFromMolBlock(molblock)
    if mol is None or mol.GetNumConformers() == 0:
        return None
    mol = Chem.RemoveHs(mol)
    if mol.GetNumAtoms() < 3:
        return None
    heavy_xy = np.array(mol.GetConformer().GetPositions())[:, :2]
    mol = Chem.AddHs(mol)

    ps = AllChem.ETKDGv3()
    ps.randomSeed = ETKDG_SEED
    ps.numThreads = 0
    cids = list(AllChem.EmbedMultipleConfs(mol, numConfs=n_confs, params=ps))
    if not cids:
        ps.useRandomCoords = True
        cids = list(AllChem.EmbedMultipleConfs(mol, numConfs=n_confs, params=ps))
    if not cids:
        # 埋め込みそのものが失敗するのは分子の結合・立体配置に起因し、molblock
        # 経由かSMILES経由かに依らず同じ結果になる(実測で確認済み)。ここで
        # Noneを返すとbuild_scene()がSMILES経由のembed_and_optimizeへ
        # フォールバックし、同じ失敗を待ってから同じ例外を出すだけで二度手間に
        # なる(埋め込み失敗は数秒かかる)。ここで直接例外を出して打ち切る。
        raise ValueError("3D埋め込みに失敗")

    if AllChem.MMFFHasAllMoleculeParams(mol):
        res = AllChem.MMFFOptimizeMoleculeConfs(mol, numThreads=0, maxIters=2000)
    else:
        res = AllChem.UFFOptimizeMoleculeConfs(mol, numThreads=0, maxIters=2000)
    energies = [e for _, e in res]
    emin = min(energies)
    ok = [c for c, e in zip(cids, energies) if e - emin <= sanity_window] or cids

    heavy = [a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() > 1]
    best_score, best_R, best_cid = -np.inf, np.eye(3), ok[0]
    for cid in ok:
        coords3d = np.array(mol.GetConformer(cid).GetPositions())[heavy]
        R, score = _rotation_matching_drawing(coords3d, heavy_xy)
        if score > best_score:
            best_score, best_R, best_cid = score, R, cid

    keep = Chem.Mol(mol)
    keep.RemoveAllConformers()
    conf = Chem.Conformer(mol.GetConformer(best_cid))
    conf.SetId(0)
    keep.AddConformer(conf, assignId=True)

    final_mol = Chem.RemoveHs(keep)
    Chem.Kekulize(final_mol, clearAromaticFlags=True)
    return _scene_from_mol3d(final_mol, rotation=best_R)


# --------------------------------------------------------------------------
# 3Dクリーンアップ機能(3Dタブの「向きを整える/形を整える/配座を選び直す」)
# --------------------------------------------------------------------------


def recompute_initial_rotation(scene: Scene) -> Scene:
    """現在の配座はそのまま、初期姿勢(見やすい向き)だけを再計算する。

    3Dタブの「向きを整える」機能(改善提案書の機能C)。ほぼ無コストなので、
    形を整える・配座を選び直す前に気軽に試せる。
    """
    return replace(scene, initial_rotation=canonical_rotation(scene.coords, scene.bonds))


def scene_to_mol(scene: Scene, rotation: Sequence[float] = (1, 0, 0, 0), flatten: bool = False) -> Chem.Mol:
    """Sceneから(水素を持たない)Molを再構築する。

    `flatten=True`は「この向きを2Dに反映」用(z=0の2D配座)、`flatten=False`は
    3Dクリーンアップ機能用(実際のZ座標を保持する3D配座)。`flatten=False`の
    場合のみ、3D座標から立体化学を再判定する(`AssignStereochemistryFrom3D`)。
    `Scene`はもともと化学的な同一性情報(原子・結合・形式電荷)を自己完結で
    持っているため、3D配座を再生成せずに直接組み立て直せる。
    """
    R = quat_to_matrix(rotation) @ scene.initial_rotation
    xyz = scene.coords @ R.T

    bond_type_map = {1: Chem.BondType.SINGLE, 2: Chem.BondType.DOUBLE, 3: Chem.BondType.TRIPLE}
    mol = Chem.RWMol()
    for symbol, charge in zip(scene.symbols, scene.formal_charges):
        atom = Chem.Atom(symbol)
        atom.SetFormalCharge(charge)
        mol.AddAtom(atom)
    for (begin, end), order in zip(scene.bonds, scene.orders):
        mol.AddBond(int(begin), int(end), bond_type_map.get(int(order), Chem.BondType.SINGLE))

    conformer = Chem.Conformer(mol.GetNumAtoms())
    for i in range(mol.GetNumAtoms()):
        x, y, z = xyz[i]
        conformer.SetAtomPosition(i, Point3D(float(x), float(y), 0.0 if flatten else float(z)))
    conformer.Set3D(not flatten)
    mol.AddConformer(conformer, assignId=True)

    result = mol.GetMol()
    Chem.SanitizeMol(result)
    if not flatten:
        Chem.AssignStereochemistryFrom3D(result)
    return result


def _get_forcefield(mol: Chem.Mol):
    if AllChem.MMFFHasAllMoleculeParams(mol):
        props = AllChem.MMFFGetMoleculeProperties(mol)
        return AllChem.MMFFGetMoleculeForceField(mol, props)
    return AllChem.UFFGetMoleculeForceField(mol)  # MMFFがパラメータを持たない原子種のフォールバック


def _compute_energy(mol: Chem.Mol) -> float:
    ff = _get_forcefield(mol)
    return float(ff.CalcEnergy()) if ff is not None else 0.0


def _restore_and_relax_hydrogens(mol: Chem.Mol) -> Chem.Mol:
    """水素なしの3D Molに近似座標つきの水素を復元し、重原子を固定して水素だけを緩和する。

    `Chem.AddHs(mol, addCoords=True)`が与える水素座標はあくまで近似値で、
    そのまま力場最適化にかけると孤立電子対の空間を埋める水素が見つからず
    sp3中心の角度が破綻することがあるため、本番の最適化前にこの一手間を挟む。
    """
    mol_h = Chem.AddHs(mol, addCoords=True)
    ff = _get_forcefield(mol_h)
    if ff is not None:
        for i in range(mol.GetNumAtoms()):  # 重原子を固定し、追加した水素だけ動かす
            ff.AddFixedPoint(i)
        ff.Minimize(maxIts=200)
    return mol_h


def _stereo_smiles(mol_with_h: Chem.Mol) -> str:
    """3D座標から立体化学を再判定し、比較用の正準SMILESを返す(元のmolは変更しない)。"""
    mol_copy = Chem.Mol(mol_with_h)
    Chem.AssignStereochemistryFrom3D(mol_copy)
    return Chem.MolToSmiles(Chem.RemoveHs(mol_copy))


@dataclass
class CleanupResult:
    scene: Scene
    energy_delta: float  # kcal/mol(MMFF)相当。after - before(負なら安定化)
    stereo_changed: bool  # 最適化前後で立体表記(CIP)が変化したか。真ならUIで警告


def cleanup_geometry(scene: Scene, mode: Literal["optimize", "reembed"] = "optimize") -> CleanupResult:
    """3Dタブの「クリーンアップ」機能。

    mode="optimize": 現配座をMMFF94(フォールバックUFF)で最小化する(機能A、
        歪んだ結合長・結合角を正す。ChemDrawのClean Up相当)。
    mode="reembed": 配座を生成し直し(`build_scene`と同じ経路)、見やすさで
        再選択する(機能B、折れ曲がった鎖状分子を伸ばす等、より重い処理)。

    塩・水和物(複数フラグメント)は、reembedの場合はSMILESで分割して
    フラグメントごとに生成し直し、既存の`_arrange_fragments`で再配置する
    (`embed_and_optimize`に複数フラグメントのSMILESを直接渡すと、既存の
    `build_scene`の設計上の前提=事前分割済み、から外れて重なる恐れがある
    ため)。optimizeの場合は現在の相対配置を尊重し、分割しない。

    Sceneは水素を保持していないため、`Chem.AddHs(addCoords=True)`で近似
    座標を復元してから最適化にかける(水素なしでの最適化は破綻するため)。
    `scene.initial_rotation`は書き換えない(呼び出し側がカメラ維持のため
    別途上書きする前提)。
    """
    heavy_mol = scene_to_mol(scene)
    mol_h_before = _restore_and_relax_hydrogens(heavy_mol)
    before_smiles = _stereo_smiles(mol_h_before)
    energy_before = _compute_energy(mol_h_before)

    if mode == "reembed":
        smiles = Chem.MolToSmiles(heavy_mol)
        parts = [p for p in smiles.split(".") if p]
        if len(parts) > 1:
            new_scene = _arrange_fragments([build_scene(p, "solid") for p in parts])
        else:
            new_scene = build_scene(smiles, "solid")
    else:
        ff = _get_forcefield(mol_h_before)
        if ff is not None:
            ff.Minimize(maxIts=2000)
        mol_final = Chem.RemoveHs(mol_h_before)
        Chem.Kekulize(mol_final, clearAromaticFlags=True)
        new_scene = _scene_from_mol3d(mol_final)

    mol_h_after = _restore_and_relax_hydrogens(scene_to_mol(new_scene))
    after_smiles = _stereo_smiles(mol_h_after)
    energy_after = _compute_energy(mol_h_after)

    return CleanupResult(
        scene=new_scene,
        energy_delta=energy_after - energy_before,
        stereo_changed=before_smiles != after_smiles,
    )


# --------------------------------------------------------------------------
# 描画パラメータ
# --------------------------------------------------------------------------


@dataclass
class RenderParams:
    width: int = 260
    height: int = 200
    padding: float = 0.08  # 枠に対する余白比

    # 深度キュー
    depth_cue: bool = True
    near_color: tuple[int, int, int] = (0x1A, 0x1A, 0x1A)
    far_color: tuple[int, int, int] = (0xB8, 0xB8, 0xB8)
    width_near: float = 1.7
    width_far: float = 1.1
    min_span: float = 0.6  # Å。これ未満の厚みは平面とみなし薄さを抑制
    gradient_steps: int = 6  # 1本の結合を何分割して色を付けるか
    depth_gamma: float = 0.55  # <1 で中間深度を手前寄り(濃いめ)に寄せる
    label_min_t: float = 0.45  # 原子ラベルの濃さの下限(奥でも読める)
    min_t: float = 0.22  # 結合の濃さの下限。長鎖の奥端が消えるのを防ぐ

    # 隠線
    hidden_line: bool = True
    gap_ratio: float = 2.5  # ギャップ幅 = 手前側の線幅 × この値

    # 投影
    perspective: float = 0.0  # 0 = 正射影。0.15 程度で弱い透視

    # スケール
    max_bond_px: float = 46.0  # 小分子で線が太く見えすぎるのを防ぐ上限

    # 原子ラベル
    font_size: float = 12.0
    label_pad: float = 1.6  # ラベル半径 = font_size * 0.5 * この値

    # 楔形(平面構造式の立体表記)
    wedge_width: float = 5.6  # 太い側の幅 px
    hash_pitch: float = 3.4  # 破線楔の縞の間隔 px


# --------------------------------------------------------------------------
# 幾何ユーティリティ
# --------------------------------------------------------------------------


def quat_to_matrix(q: Sequence[float]) -> np.ndarray:
    w, x, y, z = np.array(q, dtype=float) / np.linalg.norm(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


@dataclass
class Segment:
    """画面座標の1本の線分。"""

    p0: np.ndarray
    p1: np.ndarray
    z0: float
    z1: float
    parent: int  # 元の結合index
    atoms: tuple[int, int]
    cuts: list[tuple[float, float]] = field(default_factory=list)  # 隠線ギャップ区間


def _segment_pieces(seg: Segment) -> list[tuple[float, float]]:
    """cuts を除いた可視区間 [(t0,t1), ...] を返す。"""
    if not seg.cuts:
        return [(0.0, 1.0)]
    merged: list[list[float]] = []
    for a, b in sorted(seg.cuts):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    out, cur = [], 0.0
    for a, b in merged:
        if a > cur:
            out.append((cur, min(a, 1.0)))
        cur = max(cur, b)
    if cur < 1.0:
        out.append((cur, 1.0))
    return [(a, b) for a, b in out if b - a > 1e-3]


# --------------------------------------------------------------------------
# レンダリング本体
# --------------------------------------------------------------------------
#
# `compute_geometry()`が幾何計算(投影・隠線ギャップ・深度キュー)を一度だけ
# 行い、結果をQt非依存の描画片(線分・楔形・ラベル、色はRGB整数タプル)として
# 返す。SVG出力(`render_svg`)とQPainter直描き(`ui/molecule_3d_view.py`)の
# 両方がこれを共有することで、幾何ロジックの二重実装を避けている。


@dataclass
class LinePiece:
    """1本の描画線分(色・太さ込み、深度でグラデーション分割済み)。"""

    p0: np.ndarray
    p1: np.ndarray
    color: tuple[int, int, int]
    width: float


@dataclass
class WedgePiece:
    """1本の楔形結合。"""

    p0: np.ndarray
    p1: np.ndarray
    normal: np.ndarray
    kind: int  # +1 実楔(手前), -1 破線楔(奥)
    color: tuple[int, int, int]


@dataclass
class LabelPiece:
    """1個の原子ラベル。"""

    pos: np.ndarray
    text: str
    charge: str
    color: tuple[int, int, int]


@dataclass
class RenderGeometry:
    lines: list[LinePiece]
    wedges: list[WedgePiece]
    labels: list[LabelPiece]
    params: RenderParams


def compute_geometry(scene: Scene, q: Sequence[float] = (1, 0, 0, 0), params: RenderParams | None = None) -> RenderGeometry:
    p = params or RenderParams()
    R = quat_to_matrix(q) @ scene.initial_rotation

    xyz = scene.coords @ R.T
    z = xyz[:, 2].copy()

    xy = xyz[:, :2].copy()
    if p.perspective > 0:
        zr = z.max() - z.min()
        if zr > 1e-6:
            f = zr / p.perspective
            xy *= (f / (f - (z - z.mean())))[:, None]

    # --- スケール決定(ラベル分の余白も見込む) -------------------------
    # 分子全体の3D直径(全原子ペア間の最大距離、回転に依存しない)を基準にする。
    # 現在の投影後バウンディングボックスでスケールを決めると、インタラクティブに
    # 回転させたときに見かけの輪郭の大きさが伸縮し「回転中にズームしているよう
    # に見える」ため(ユーザー報告により判明、2026-08-22)。直径基準なら分子の
    # 見かけの大きさは向きによらず一定になる。
    diff = scene.coords[:, None, :] - scene.coords[None, :, :]
    diameter = float(np.max(np.linalg.norm(diff, axis=2)))
    diameter = max(diameter, 1e-6)
    avail = np.array([p.width, p.height]) * (1 - 2 * p.padding)
    scale = float(min(avail)) / diameter
    # 結合長は`scene.bond_length`(3D座標・回転前から計算済み、回転に依存しない)を
    # 使う。投影後(xy)の結合長を使うと、結合が視線方向に近づくほど0に潰れて
    # 回転依存になり、直径基準にした意味が失われるため(ユーザー報告により判明、
    # 2026-08-22。直径基準の初回修正ではここが投影後の値のまま残っていた)。
    typical_bond = max(scene.bond_length, 1e-6)
    if typical_bond * scale > p.max_bond_px:  # 小分子の過拡大を抑制
        scale = p.max_bond_px / typical_bond
    # 画面中心 = 分子の重心(scene.coordsは重心が原点になるよう構築済みのため、
    # 回転してもxy.mean(axis=0)は常に(0,0)近傍を保つ)。旧実装は投影後バウンディング
    # ボックスの中心を使っており、非対称な分子では回転につれてこの中心が分子本体
    # に対して揺れ動き、「回転の重心が分子の重心からズレる」ように見えていた。
    center = xy.mean(axis=0)
    sxy = (xy - center) * np.array([scale, -scale]) + np.array([p.width / 2, p.height / 2])

    # --- 深度の正規化 ---------------------------------------------------
    zmin, zmax = float(z.min()), float(z.max())
    zspan = zmax - zmin
    k = min(zspan / p.min_span, 1.0) if p.depth_cue else 0.0

    def depth_t(zv: float) -> float:
        raw = (zv - zmin) / zspan if zspan > 1e-9 else 1.0
        raw = min(max(raw, 0.0), 1.0)  # 端点以外の補間点は浮動小数点誤差でわずかに[0,1]を外れうる。
        raw = raw**p.depth_gamma  # 中間深度が一律に灰色化するのを防ぐ(負数に分数乗すると複素数になるため上でクランプ)
        return max(1.0 - k * (1.0 - raw), p.min_t)  # 1=手前, 0=最奥

    def color_at(t: float) -> tuple[int, int, int]:
        c = [int(round(f + (n - f) * t)) for n, f in zip(p.near_color, p.far_color)]
        return (c[0], c[1], c[2])

    def width_at(t: float) -> float:
        return p.width_far + (p.width_near - p.width_far) * t

    # --- 結合 → 線分 ----------------------------------------------------
    label_r = {
        i: p.font_size * 0.5 * p.label_pad * (1 + 0.42 * (len(t) - 1)) for i, t in enumerate(scene.labels) if t
    }
    segments: list[Segment] = []
    wedge_shapes: list[tuple] = []

    for bi, ((a, b), order) in enumerate(zip(scene.bonds, scene.orders)):
        p0, p1 = sxy[a].copy(), sxy[b].copy()
        v = p1 - p0
        L = np.linalg.norm(v)
        if L < 1e-6:
            continue
        u = v / L
        # 原子ラベルの分だけ結合端を削る
        s0 = label_r.get(a, 0.0) / L
        s1 = label_r.get(b, 0.0) / L
        za, zb = z[a], z[b]
        p0, p1 = p0 + v * s0, p1 - v * s1
        za, zb = za + (zb - za) * s0, zb - (zb - za) * s1

        n = np.array([-u[1], u[0]])

        if bi < len(scene.wedges) and scene.wedges[bi] != 0:
            wedge_shapes.append((p0, p1, n, int(scene.wedges[bi]), depth_t(float((za + zb) / 2))))
            continue

        offs: list[tuple[float, float, float]] = []  # (法線オフセット, 端の縮み0, 1)
        if order == 1:
            offs = [(0.0, 0.0, 0.0)]
        elif order == 2:
            c = scene.ring_center[bi]
            if not np.isnan(c).any():  # 環内二重結合は内側に1本
                cs = (c @ R.T)[:2]
                cs = (cs - center) * np.array([scale, -scale]) + np.array([p.width / 2, p.height / 2])
                sign = np.sign(np.dot(cs - p0, n)) or 1.0
                offs = [(0.0, 0.0, 0.0), (sign * 3.6, 0.16, 0.16)]
            else:
                offs = [(2.0, 0.0, 0.0), (-2.0, 0.0, 0.0)]
        else:
            offs = [(0.0, 0.0, 0.0), (3.4, 0.0, 0.0), (-3.4, 0.0, 0.0)]

        for off, c0, c1 in offs:
            d = p1 - p0
            q0 = p0 + d * c0 + n * off
            q1 = p1 - d * c1 + n * off
            segments.append(Segment(q0, q1, float(za), float(zb), bi, (int(a), int(b))))

    # --- 隠線ギャップ(全ペア交差判定をベクトル化) ----------------------
    if p.hidden_line and len(segments) > 1:
        P = np.array([s.p0 for s in segments])
        D = np.array([s.p1 - s.p0 for s in segments])
        cross = lambda A, B: A[..., 0] * B[..., 1] - A[..., 1] * B[..., 0]  # noqa: E731
        denom = cross(D[:, None, :], D[None, :, :])
        diff = P[None, :, :] - P[:, None, :]
        with np.errstate(divide="ignore", invalid="ignore"):
            t = cross(diff, D[None, :, :]) / denom
            u_ = cross(diff, D[:, None, :]) / denom
        E = 1e-6
        hit = (np.abs(denom) > E) & (t > E) & (t < 1 - E) & (u_ > E) & (u_ < 1 - E)
        # 同じ結合由来 / 原子を共有する結合同士は無視
        atoms = [set(s.atoms) for s in segments]
        for i, j in zip(*np.where(np.triu(hit, 1))):
            si, sj = segments[i], segments[j]
            if si.parent == sj.parent or atoms[i] & atoms[j]:
                continue
            ti, tj = float(t[i, j]), float(u_[i, j])
            zi = si.z0 + (si.z1 - si.z0) * ti
            zj = sj.z0 + (sj.z1 - sj.z0) * tj
            if zi < zj:  # i が奥 → i を切る
                back, tb, front_t = si, ti, tj
                front = sj
            else:
                back, tb, front_t = sj, tj, ti
                front = si
            gap = width_at(depth_t(front.z0 + (front.z1 - front.z0) * front_t)) * p.gap_ratio
            half = gap / (2 * max(np.linalg.norm(back.p1 - back.p0), 1e-6))
            back.cuts.append((tb - half, tb + half))

    # --- 描画片へ展開して奥から順に並べる --------------------------------
    raw_pieces = []
    for s in segments:
        d = s.p1 - s.p0
        for a0, b0 in _segment_pieces(s):
            n_sub = p.gradient_steps if (p.depth_cue and k > 0) else 1
            for m in range(n_sub):
                f0 = a0 + (b0 - a0) * m / n_sub
                f1 = a0 + (b0 - a0) * (m + 1) / n_sub
                zm = s.z0 + (s.z1 - s.z0) * (f0 + f1) / 2
                tm = depth_t(zm)
                raw_pieces.append((zm, s.p0 + d * f0, s.p0 + d * f1, color_at(tm), width_at(tm)))
    raw_pieces.sort(key=lambda x: x[0])
    lines = [LinePiece(p0=q0, p1=q1, color=col, width=w) for _, q0, q1, col, w in raw_pieces]

    wedges = [
        WedgePiece(p0=q0, p1=q1, normal=nv, kind=kind, color=color_at(t))
        for q0, q1, nv, kind, t in wedge_shapes
    ]

    labels = [
        LabelPiece(
            pos=sxy[i],
            text=sym,
            charge=scene.charges[i],
            color=color_at(max(depth_t(float(z[i])), p.label_min_t)),
        )
        for i, sym in enumerate(scene.labels)
        if sym
    ]

    return RenderGeometry(lines=lines, wedges=wedges, labels=labels, params=p)


def _tspans(text: str, charge: str, fs: float) -> str:
    """H2O の 2 を下付き、電荷を上付きにする。dy は累積なので都度戻す(SVG専用)。"""
    out, dy = [], 0.0
    for run in re.findall(r"\d+|\D+", text):
        if run.isdigit():
            shift = fs * 0.22 - dy
            out.append(f'<tspan font-size="{fs*0.72:.1f}" dy="{shift:.1f}">{run}</tspan>')
            dy = fs * 0.22
        else:
            out.append(f'<tspan dy="{-dy:.1f}">{run}</tspan>' if dy else run)
            dy = 0.0
    if charge:
        shift = -fs * 0.38 - dy
        out.append(f'<tspan font-size="{fs*0.72:.1f}" dy="{shift:.1f}">{charge}</tspan>')
    return "".join(out)


def render_svg(scene: Scene, q: Sequence[float] = (1, 0, 0, 0), params: RenderParams | None = None) -> str:
    """`compute_geometry()`の結果をSVG文字列化する。"""
    geom = compute_geometry(scene, q, params)
    p = geom.params

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {p.width} {p.height}" '
        f'width="{p.width}" height="{p.height}">',
        f'<rect width="{p.width}" height="{p.height}" fill="#ffffff"/>',
    ]
    out.append('<g stroke-linecap="round" stroke-linejoin="round">')
    for line in geom.lines:
        col = "#%02x%02x%02x" % line.color
        out.append(
            f'<line x1="{line.p0[0]:.2f}" y1="{line.p0[1]:.2f}" x2="{line.p1[0]:.2f}" y2="{line.p1[1]:.2f}" '
            f'stroke="{col}" stroke-width="{line.width:.2f}"/>'
        )
    for wedge in geom.wedges:
        half = p.wedge_width / 2
        col = "#%02x%02x%02x" % wedge.color
        q0, q1, nv = wedge.p0, wedge.p1, wedge.normal
        if wedge.kind > 0:  # 実楔: 手前に出る三角形
            a, b = q1 + nv * half, q1 - nv * half
            out.append(
                f'<path d="M{q0[0]:.2f},{q0[1]:.2f} L{a[0]:.2f},{a[1]:.2f} '
                f'L{b[0]:.2f},{b[1]:.2f} Z" fill="{col}" stroke="none"/>'
            )
        else:  # 破線楔: 奥へ引っ込む縞
            L = float(np.linalg.norm(q1 - q0))
            steps = max(int(L / p.hash_pitch), 2)
            for m in range(1, steps + 1):
                f = m / steps
                c = q0 + (q1 - q0) * f
                w = half * f
                out.append(
                    f'<line x1="{c[0]-nv[0]*w:.2f}" y1="{c[1]-nv[1]*w:.2f}" '
                    f'x2="{c[0]+nv[0]*w:.2f}" y2="{c[1]+nv[1]*w:.2f}" '
                    f'stroke="{col}" stroke-width="{p.width_near*0.85:.2f}"/>'
                )
    out.append("</g>")

    for label in geom.labels:
        col = "#%02x%02x%02x" % label.color
        out.append(
            f'<text x="{label.pos[0]:.2f}" y="{label.pos[1]:.2f}" fill="{col}" '
            f'font-family="Helvetica,Arial,sans-serif" font-size="{p.font_size}" '
            f'text-anchor="middle" dominant-baseline="central">'
            + _tspans(label.text, label.charge, p.font_size)
            + "</text>"
        )
    out.append("</svg>")
    return "\n".join(out)


__all__ = [
    "Scene",
    "RenderParams",
    "RenderGeometry",
    "LinePiece",
    "WedgePiece",
    "LabelPiece",
    "build_scene",
    "build_flat_scene",
    "build_flat_scene_from_molblock",
    "compute_geometry",
    "render_svg",
    "quat_to_matrix",
    "canonical_rotation",
    "embed_and_optimize",
    "recompute_initial_rotation",
    "scene_to_mol",
    "cleanup_geometry",
    "CleanupResult",
    "get_or_build_scene",
    "clear_scene_cache",
    "CURRENT_RENDERER_VERSION",
    "replace",
]
