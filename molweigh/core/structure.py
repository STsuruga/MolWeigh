"""SMILES文字列からRDKitのMolを構築し、分子量・化学式・2D構造式画像を得る。

新規化合物や非販売化合物など、化学式パーサーやPubChemでは解決できない
場合の入力経路として使う。画像はUI側でそのまま使えるよう `QPixmap` に
変換して返す。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtGui import QImage, QPixmap
from rdkit import Chem
from rdkit.Chem import Descriptors, Draw, rdMolDescriptors
from rdkit.Geometry import Point3D

from . import structure_3d


@dataclass
class StructureInfo:
    smiles: str
    molecular_weight: float
    formula: str


@dataclass
class LineArtAtom:
    symbol: str
    x: float
    y: float
    z: float


@dataclass
class LineArtBond:
    begin: int
    end: int
    order: float


@dataclass
class LineArtMolecule:
    atoms: list[LineArtAtom]
    bonds: list[LineArtBond]


def parse_smiles(smiles: str) -> StructureInfo:
    """SMILES文字列を解析し、分子量・化学式を算出する。"""
    mol = _mol_from_smiles(smiles)
    return StructureInfo(
        smiles=smiles,
        molecular_weight=Descriptors.MolWt(mol),
        formula=rdMolDescriptors.CalcMolFormula(mol),
    )


def render_structure_image(smiles: str, size: tuple[int, int] = (300, 300)) -> QPixmap:
    """SMILES文字列から2D構造式画像を生成し、`QPixmap` として返す。

    トリプチセンのような橋かけ環(bridgehead原子を持つ構造)は、通常の2D
    レイアウトでは無理に平面化されて環同士が重なり、RDKitが重なり箇所に
    警告マークを付けてしまうことがある。その場合は3D構造を生成して
    XY座標をそのまま2Dレイアウトとして使うことで、立体形状が伝わる
    (奥行きを交差線で表現する)描画にする。
    """
    mol = _mol_from_smiles(smiles)
    if rdMolDescriptors.CalcNumBridgeheadAtoms(mol) > 0:
        try:
            mol = _project_3d_to_2d(smiles)
        except ValueError:
            pass
    pil_image = Draw.MolToImage(mol, size=size).convert("RGBA")
    data = pil_image.tobytes("raw", "RGBA")
    qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage.copy())


def realign_bridged_structure_molblock(smiles: str) -> str | None:
    """橋かけ構造(bridgehead原子を持つ)の場合のみ、3D投影レイアウトのMOLブロックを返す。

    Ketcherの2D自動レイアウトは橋かけ構造をうまく描けないことがあるが、
    Ketcher自身の描画アルゴリズムは外部から差し替えられない。その代わり、
    Ketcherの `setMolecule()` はMOLブロックの座標をそのまま尊重して表示する
    ため、こちらで計算した見やすいレイアウトをMOLブロックとして渡すことで、
    Ketcherのキャンバス上に反映できる。橋かけ構造でない場合は整列が不要
    なのでNoneを返す。
    """
    mol = _mol_from_smiles(smiles)
    if rdMolDescriptors.CalcNumBridgeheadAtoms(mol) == 0:
        return None
    projected = _project_3d_to_2d(smiles)
    return Chem.MolToMolBlock(projected)


def generate_lineart_data(smiles: str) -> LineArtMolecule:
    """線画3Dビューア(`ui/molecule_lineart_viewer.py`)向けに、正準な向きに揃えた
    3D原子座標・結合リストを生成する。

    幾何処理(回転・投影・隠線処理)はJS側で行うため、ここではRDKitでの
    3D配座生成と、見やすい初期角度への回転(`orient_canonically`)、水素の
    除去(骨格式表示の慣習に合わせる)のみを行い、素の座標・結合データを返す。
    """
    mol_3d = structure_3d.embed_and_optimize(smiles)
    orient_canonically(mol_3d)
    mol = Chem.RemoveHs(mol_3d)
    conformer = mol.GetConformer()
    atoms = []
    for atom in mol.GetAtoms():
        pos = conformer.GetAtomPosition(atom.GetIdx())
        atoms.append(LineArtAtom(symbol=atom.GetSymbol(), x=pos.x, y=pos.y, z=pos.z))
    bonds = [
        LineArtBond(begin=b.GetBeginAtomIdx(), end=b.GetEndAtomIdx(), order=b.GetBondTypeAsDouble())
        for b in mol.GetBonds()
    ]
    return LineArtMolecule(atoms=atoms, bonds=bonds)


def build_molblock_from_lineart_layout(smiles: str, layout: list[tuple[float, float]]) -> str:
    """線画3Dビューア(`ui/molecule_lineart_viewer.py`)で表示中の分子に対し、
    ユーザーがマウスで回転させた「今見ている向き」のXY座標(JS側で計算済み)を
    そのまま2Dレイアウトとして持つMOLブロックを作る。

    `generate_lineart_data`と同じ経路(`embed_and_optimize` → `RemoveHs`)で
    Molを組み立て直す。埋め込みは固定シードで決定的なため、原子順序は
    ビューアが表示していたものと一致する(`layout`の各要素と対応)。
    """
    mol_3d = structure_3d.embed_and_optimize(smiles)
    mol = Chem.RemoveHs(mol_3d)
    if mol.GetNumAtoms() != len(layout):
        raise ValueError("原子数が一致しないため、2Dへの反映に失敗しました。")
    conformer = Chem.Conformer(mol.GetNumAtoms())
    for i, (x, y) in enumerate(layout):
        conformer.SetAtomPosition(i, Point3D(float(x), float(y), 0.0))
    conformer.Set3D(False)
    mol.RemoveAllConformers()
    mol.AddConformer(conformer, assignId=True)
    return Chem.MolToMolBlock(mol)


def _project_3d_to_2d(smiles: str) -> Chem.Mol:
    """3D配座のXY座標をそのまま2Dレイアウトとして流用したMolを作る。"""
    mol_3d = structure_3d.embed_and_optimize(smiles)
    orient_canonically(mol_3d)
    mol = Chem.RemoveHs(mol_3d)
    conformer_3d = mol.GetConformer()
    conformer_2d = Chem.Conformer(mol.GetNumAtoms())
    for i in range(mol.GetNumAtoms()):
        pos = conformer_3d.GetAtomPosition(i)
        conformer_2d.SetAtomPosition(i, Point3D(pos.x, pos.y, 0.0))
    conformer_2d.Set3D(False)
    mol.RemoveAllConformers()
    mol.AddConformer(conformer_2d, assignId=True)
    return mol


def orient_canonically(mol: Chem.Mol) -> None:
    """3D座標を回転し、重原子同士が2D投影で最も重なりにくい向きを選ぶ。

    水素原子は結合長が短く常にどの向きでも隣接原子に近いままなので、
    重なりにくさの評価に含めると水素間の距離だけで決まってしまう。
    そのため主成分分析・スコア評価とも重原子のみを対象にする(回転自体は
    全原子に適用する)。主成分分析で得られる3本の主軸のうち、どれを
    奥行き(Z)に選ぶかで見た目の重なり具合が大きく変わる(分散最小の軸が
    必ずしも一番綺麗に見えるとは限らない)ため、3通り全てを試し、2D投影
    した際の重原子間の最小距離が最大になる向きを採用する。

    橋かけ構造の2D投影(`_project_3d_to_2d`)だけでなく、線画3Dビューア
    (`ui/molecule_lineart_viewer.py`)の初期表示角度にも流用する。
    """
    conformer = mol.GetConformer()
    coords = np.array([list(conformer.GetAtomPosition(i)) for i in range(mol.GetNumAtoms())])
    heavy_mask = np.array([atom.GetAtomicNum() != 1 for atom in mol.GetAtoms()])
    centered = coords - coords.mean(axis=0)

    _, eigenvectors = np.linalg.eigh(np.cov(centered[heavy_mask].T))

    best_rotation, best_score = None, -np.inf
    for depth_axis in range(3):
        other_axes = [i for i in range(3) if i != depth_axis]
        rotation = np.column_stack(
            [eigenvectors[:, other_axes[0]], eigenvectors[:, other_axes[1]], eigenvectors[:, depth_axis]]
        )
        if np.linalg.det(rotation) < 0:
            rotation[:, -1] *= -1
        score = _min_pairwise_distance_2d((centered @ rotation)[heavy_mask])
        if score > best_score:
            best_score, best_rotation = score, rotation

    rotated = centered @ best_rotation
    for i in range(mol.GetNumAtoms()):
        x, y, z = rotated[i]
        conformer.SetAtomPosition(i, Point3D(float(x), float(y), float(z)))


def _min_pairwise_distance_2d(rotated: np.ndarray) -> float:
    """回転後の座標をXY平面に投影した際の、原子間最小距離(重なりにくさの指標)。"""
    xy = rotated[:, :2]
    diffs = xy[:, None, :] - xy[None, :, :]
    dists = np.sqrt((diffs**2).sum(axis=2))
    np.fill_diagonal(dists, np.inf)
    return float(dists.min())


def _mol_from_smiles(smiles: str) -> Chem.Mol:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"SMILESを解析できません: {smiles!r}")
    return mol
