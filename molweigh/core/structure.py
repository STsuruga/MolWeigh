"""SMILES文字列からRDKitのMolを構築し、分子量・化学式・2D構造式画像を得る。

新規化合物や非販売化合物など、化学式パーサーやPubChemでは解決できない
場合の入力経路として使う。画像はUI側でそのまま使えるよう `QPixmap` に
変換して返す。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolDescriptors
from rdkit.Geometry import Point3D

from . import lineart_render


@dataclass
class StructureInfo:
    smiles: str
    molecular_weight: float
    formula: str


def smiles_from_molblock(molblock: str) -> str:
    """MOLブロックから立体化学つきのSMILESを得る。

    Ketcherの2D編集キャンバス上の楔形は、この経路(`MolFromMolBlock`が
    ウェッジ結合から立体中心を自動判定する)を通すことで初めてSMILESへ
    正しく反映される。3Dタブの配座生成はSMILES文字列を入力に取るため、
    「3D化」する際はKetcherから`getSmiles()`ではなく`getMolfile()`で
    取得したMOLブロックをこの関数に通してから渡す。
    """
    mol = Chem.MolFromMolBlock(molblock)
    if mol is None:
        raise ValueError("MOLブロックを解析できませんでした。")
    return Chem.MolToSmiles(mol)


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

    ChemDraw風の自前線画レンダラー(`core/lineart_render.py`)で描画する。
    平面レイアウトが破綻する構造(トリプチセンのような橋かけ環など)は
    `build_scene(mode="auto")`が自動的に3D配座を正射影した立体線画へ
    切り替える(奥行きを濃淡と隠線ギャップで表現する)。

    ライブラリ由来の化合物で`LibraryEntry.preview_svg`が保存済みの場合は、
    毎回ここで生成し直すのではなく`rasterize_svg(entry.preview_svg, size)`を
    直接使うほうが望ましい(カードグリッドで多数を同時に描く際の負荷軽減)。
    """
    scene = lineart_render.build_scene(smiles, mode="auto")
    svg = lineart_render.render_svg(scene, params=lineart_render.RenderParams(width=size[0], height=size[1]))
    return rasterize_svg(svg, size)


def generate_preview_svg(smiles: str, render_mode: str = "auto") -> str:
    """`LibraryEntry.preview_svg`に保存するためのSVG文字列を生成する。

    `viewBox`付きのSVGとして保存するため、後から`rasterize_svg`で任意の
    表示サイズ(テーブルヘッダ90×70・ライブラリカード110×85・登録
    プレビュー168×128)に再ラスタライズできる。
    """
    scene = lineart_render.build_scene(smiles, mode=render_mode)
    return lineart_render.render_svg(scene)


def rasterize_svg(svg: str, size: tuple[int, int]) -> QPixmap:
    """SVG文字列を指定サイズの`QPixmap`にラスタライズする。"""
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(*size)
    pixmap.fill(Qt.GlobalColor.white)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


def realign_bridged_structure_molblock(smiles: str) -> str | None:
    """橋かけ構造(bridgehead原子を持つ)の場合のみ、3D投影レイアウトのMOLブロックを返す。

    Ketcherの2D自動レイアウトは橋かけ構造をうまく描けないことがあるが、
    Ketcher自身の描画アルゴリズムは外部から差し替えられない。その代わり、
    Ketcherの `setMolecule()` はMOLブロックの座標をそのまま尊重して表示する
    ため、こちらで計算した見やすいレイアウトをMOLブロックとして渡すことで、
    Ketcherのキャンバス上に反映できる。橋かけ構造でない場合は整列が不要
    なのでNoneを返す。

    `lineart_render.build_scene(smiles, mode="solid")`と全く同じ経路
    (同じ`canonical_rotation`)を通す。以前は`orient_canonically`という
    別実装のPCAベースの向き選択を使っており、対称分子で固有値が縮退する
    弱点に加えて、カード等のプレビュー画像(こちらは常に
    `lineart_render`側のアルゴリズムを使う)と向きが一致しないという
    実害があったため、経路を一本化した。
    """
    mol = _mol_from_smiles(smiles)
    if rdMolDescriptors.CalcNumBridgeheadAtoms(mol) == 0:
        return None
    scene = lineart_render.build_scene(smiles, mode="solid")
    return build_molblock_from_scene(scene)


def build_molblock_from_scene(scene: lineart_render.Scene, rotation: tuple[float, float, float, float] = (1, 0, 0, 0)) -> str:
    """3Dタブ(`ui/molecule_3d_view.py`)で表示中の`Scene`に対し、ユーザーが
    ドラッグで回転させた「今見ている向き」のXY座標で2Dレイアウトを持つ
    MOLブロックを作る(「この向きを2Dに反映」用)。

    `Scene`は原子・結合・(初期姿勢を含む)配座を自己完結で持っているため、
    3D配座を再生成する必要はなく、`compute_geometry`と同じ回転行列を
    座標へ直接適用して`RWMol`を組み立て直すだけでよい。
    """
    R = lineart_render.quat_to_matrix(rotation) @ scene.initial_rotation
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
        x, y, _ = xyz[i]
        conformer.SetAtomPosition(i, Point3D(float(x), float(y), 0.0))
    conformer.Set3D(False)
    mol.AddConformer(conformer, assignId=True)

    result = mol.GetMol()
    Chem.SanitizeMol(result)
    return Chem.MolToMolBlock(result)


def _mol_from_smiles(smiles: str) -> Chem.Mol:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"SMILESを解析できません: {smiles!r}")
    return mol
