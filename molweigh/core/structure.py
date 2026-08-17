"""SMILES文字列からRDKitのMolを構築し、分子量・化学式・2D構造式画像を得る。

新規化合物や非販売化合物など、化学式パーサーやPubChemでは解決できない
場合の入力経路として使う。画像はUI側でそのまま使えるよう `QPixmap` に
変換して返す。
"""

from __future__ import annotations

from dataclasses import dataclass

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


def _project_3d_to_2d(smiles: str) -> Chem.Mol:
    """3D配座のXY座標をそのまま2Dレイアウトとして流用したMolを作る。"""
    mol_3d = structure_3d.embed_and_optimize(smiles)
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


def _mol_from_smiles(smiles: str) -> Chem.Mol:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"SMILESを解析できません: {smiles!r}")
    return mol
