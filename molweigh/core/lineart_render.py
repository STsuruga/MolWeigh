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
from typing import Sequence

import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem, rdDepictor

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
    cids = list(AllChem.EmbedMultipleConfs(mol, numConfs=n_confs, params=ps))
    if not cids:
        ps.useRandomCoords = True
        cids = list(AllChem.EmbedMultipleConfs(mol, numConfs=n_confs, params=ps))
    if not cids:
        raise ValueError("3D埋め込みに失敗")

    if AllChem.MMFFHasAllMoleculeParams(mol):
        res = AllChem.MMFFOptimizeMoleculeConfs(mol, maxIters=2000)
    else:
        res = AllChem.UFFOptimizeMoleculeConfs(mol, maxIters=2000)
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
# シーン(レンダリング用の前計算済みデータ)
# --------------------------------------------------------------------------


@dataclass
class Scene:
    coords: np.ndarray  # (n_atoms, 3) 重心を原点に移動済み・水素除去済み
    symbols: list[str]
    labels: list[str]  # 表示用ラベル(炭素は空文字)。例: O, OH, H2O
    charges: list[str]  # 電荷の上付き文字。例: +, 2-
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
    lone = mol.GetNumAtoms() == 1

    def _label(a: Chem.Atom) -> str:
        n = a.GetTotalNumHs()
        if a.GetSymbol() == "C" and a.GetFormalCharge() == 0 and not lone:
            return ""
        h = "" if n == 0 else "H" if n == 1 else f"H{n}"
        return (h + a.GetSymbol()) if lone else (a.GetSymbol() + h)

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
        wedges=wedges,
        bonds=bonds,
        orders=np.array(orders, dtype=int).reshape(-1),
        ring_center=np.array(centers, dtype=float).reshape(-1, 3),
        initial_rotation=rotation,
        bond_length=float(np.median(lengths)),
    )


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

    wedge_map = {Chem.BondDir.BEGINWEDGE: 1, Chem.BondDir.BEGINDASH: -1}
    wedges = np.array([wedge_map.get(b.GetBondDir(), 0) for b in mol.GetBonds()], dtype=int).reshape(-1)

    scene = _scene_from_mol(mol, coords, np.eye(3), wedges)
    dmin, cross = _layout_quality(coords[:, :2], scene.bonds)
    return scene, dmin, cross


def _arrange_fragments(frag_scenes: list[Scene], gap: float = 1.6) -> Scene:
    """塩や水和物を横並びに配置する。

    ETKDGはイオンや結晶水を分子本体の任意の位置に置くため、そのまま描くと
    対イオンが鎖の上に重なる。フラグメントごとに向きを決めてから、重原子数の
    多い順に左から並べ直す。
    """
    frag_scenes = sorted(frag_scenes, key=lambda s: -len(s.coords))
    coords, labels, charges, symbols, bonds, orders, centers, wedges = [], [], [], [], [], [], [], []
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
        wedges=np.concatenate(wedges) if wedges else np.zeros(0, int),
        bonds=np.vstack(bonds) if bonds else np.zeros((0, 2), int),
        orders=np.concatenate(orders) if orders else np.zeros(0, int),
        ring_center=np.vstack(centers),
        initial_rotation=np.eye(3),  # 配置済みなので追加回転はしない
        bond_length=frag_scenes[0].bond_length,
    )


def build_scene(smiles: str, mode: str = "auto") -> Scene:
    """構造シーンを組み立てる。

    mode="flat"  従来型の平面構造式(楔形つき)
    mode="solid" 3D配座を正射影した立体線画
    mode="auto"  まず平面で描き、レイアウトが破綻していれば立体に切り替える
                 (シクロヘキサンやステロイドは非平面だが平面で描けるので平面のまま、
                  トリプチセンやアダマンタンのように環が重なるものだけ立体になる)
    """
    parts = smiles.split(".")
    if len(parts) > 1:  # 塩・水和物・共結晶
        return _arrange_fragments([build_scene(p, mode) for p in parts if p])

    if mode in ("flat", "auto"):
        flat, dmin, cross = build_flat_scene(smiles)
        if mode == "flat" or (dmin >= FLAT_DMIN_MIN and cross <= FLAT_MAX_CROSSINGS):
            return flat

    mol3d, coarse_R = embed_and_optimize(smiles)
    mol = Chem.RemoveHs(mol3d)
    Chem.Kekulize(mol, clearAromaticFlags=True)

    conf = mol.GetConformer()
    coords = np.array(conf.GetPositions(), dtype=float)
    coords -= coords.mean(axis=0)
    symbols = [a.GetSymbol() for a in mol.GetAtoms()]

    lone = mol.GetNumAtoms() == 1  # 単原子フラグメント(対イオン・結晶水)

    def _label(a: Chem.Atom) -> str:
        n = a.GetTotalNumHs()
        if a.GetSymbol() == "C" and n >= 0 and a.GetFormalCharge() == 0 and not lone:
            return ""
        h = "" if n == 0 else "H" if n == 1 else f"H{n}"
        # H2O / HCl / NH3 のように、単独で存在する分子は水素を先に書く慣習
        return (h + a.GetSymbol()) if lone else (a.GetSymbol() + h)

    def _charge(a: Chem.Atom) -> str:
        c = a.GetFormalCharge()
        if c == 0:
            return ""
        sign = "+" if c > 0 else "−"
        return sign if abs(c) == 1 else f"{abs(c)}{sign}"

    labels = [_label(a) for a in mol.GetAtoms()]
    charges = [_charge(a) for a in mol.GetAtoms()]

    ri = mol.GetRingInfo()
    rings = [np.array(r, dtype=int) for r in ri.AtomRings()]

    bonds, orders, centers = [], [], []
    for b in mol.GetBonds():
        i, j = b.GetBeginAtomIdx(), b.GetEndAtomIdx()
        bonds.append((i, j))
        orders.append(int(round(b.GetBondTypeAsDouble())))
        c = np.full(3, np.nan)
        for r in rings:  # この結合を含む最小の環の重心
            if i in r and j in r:
                cand = coords[r].mean(axis=0)
                if np.isnan(c).all():
                    c = cand
        centers.append(c)

    bonds = np.array(bonds, dtype=int).reshape(-1, 2)  # 単原子イオンは0本
    lengths = (
        np.linalg.norm(coords[bonds[:, 0]] - coords[bonds[:, 1]], axis=1) if len(bonds) else np.array([1.5])
    )

    return Scene(
        coords=coords,
        symbols=symbols,
        labels=labels,
        charges=charges,
        wedges=np.zeros(len(bonds), dtype=int),
        bonds=bonds,
        orders=np.array(orders, dtype=int).reshape(-1),
        ring_center=np.array(centers, dtype=float).reshape(-1, 3),
        initial_rotation=canonical_rotation(coords, bonds),  # 全原子で細かく再探索
        bond_length=float(np.median(lengths)),
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


def render_svg(scene: Scene, q: Sequence[float] = (1, 0, 0, 0), params: RenderParams | None = None) -> str:
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
    span = xy.max(axis=0) - xy.min(axis=0)
    span = np.maximum(span, 1e-6)
    avail = np.array([p.width, p.height]) * (1 - 2 * p.padding)
    scale = float(min(avail / span))
    proj_bond = np.median(np.linalg.norm(xy[scene.bonds[:, 0]] - xy[scene.bonds[:, 1]], axis=1))
    if proj_bond * scale > p.max_bond_px:  # 小分子の過拡大を抑制
        scale = p.max_bond_px / proj_bond
    center = (xy.max(axis=0) + xy.min(axis=0)) / 2
    sxy = (xy - center) * np.array([scale, -scale]) + np.array([p.width / 2, p.height / 2])

    # --- 深度の正規化 ---------------------------------------------------
    zmin, zmax = float(z.min()), float(z.max())
    zspan = zmax - zmin
    k = min(zspan / p.min_span, 1.0) if p.depth_cue else 0.0

    def depth_t(zv: float) -> float:
        raw = (zv - zmin) / zspan if zspan > 1e-9 else 1.0
        raw = raw**p.depth_gamma  # 中間深度が一律に灰色化するのを防ぐ
        return max(1.0 - k * (1.0 - raw), p.min_t)  # 1=手前, 0=最奥

    def color_at(t: float) -> str:
        c = [int(round(f + (n - f) * t)) for n, f in zip(p.near_color, p.far_color)]
        return "#%02x%02x%02x" % tuple(c)

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
    pieces = []
    for s in segments:
        d = s.p1 - s.p0
        for a0, b0 in _segment_pieces(s):
            n_sub = p.gradient_steps if (p.depth_cue and k > 0) else 1
            for m in range(n_sub):
                f0 = a0 + (b0 - a0) * m / n_sub
                f1 = a0 + (b0 - a0) * (m + 1) / n_sub
                zm = s.z0 + (s.z1 - s.z0) * (f0 + f1) / 2
                tm = depth_t(zm)
                pieces.append((zm, s.p0 + d * f0, s.p0 + d * f1, color_at(tm), width_at(tm)))
    pieces.sort(key=lambda x: x[0])

    # --- SVG ------------------------------------------------------------
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {p.width} {p.height}" '
        f'width="{p.width}" height="{p.height}">',
        f'<rect width="{p.width}" height="{p.height}" fill="#ffffff"/>',
    ]
    out.append('<g stroke-linecap="round" stroke-linejoin="round">')
    for _, q0, q1, col, w in pieces:
        out.append(
            f'<line x1="{q0[0]:.2f}" y1="{q0[1]:.2f}" x2="{q1[0]:.2f}" y2="{q1[1]:.2f}" '
            f'stroke="{col}" stroke-width="{w:.2f}"/>'
        )
    for q0, q1, nv, kind, t in wedge_shapes:
        half = p.wedge_width / 2
        col = color_at(t)
        if kind > 0:  # 実楔: 手前に出る三角形
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

    def _tspans(text: str, charge: str, fs: float) -> str:
        """H2O の 2 を下付き、電荷を上付きにする。dy は累積なので都度戻す。"""
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

    for i, sym in enumerate(scene.labels):
        if not sym:
            continue
        t = max(depth_t(float(z[i])), p.label_min_t)
        out.append(
            f'<text x="{sxy[i][0]:.2f}" y="{sxy[i][1]:.2f}" fill="{color_at(t)}" '
            f'font-family="Helvetica,Arial,sans-serif" font-size="{p.font_size}" '
            f'text-anchor="middle" dominant-baseline="central">' + _tspans(sym, scene.charges[i], p.font_size) + "</text>"
        )
    out.append("</svg>")
    return "\n".join(out)


__all__ = [
    "Scene",
    "RenderParams",
    "build_scene",
    "build_flat_scene",
    "render_svg",
    "quat_to_matrix",
    "canonical_rotation",
    "embed_and_optimize",
    "replace",
]
