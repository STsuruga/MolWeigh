"""SMILES文字列からRDKitのMolを構築し、分子量・化学式・2D構造式画像を得る。

新規化合物や非販売化合物など、化学式パーサーやPubChemでは解決できない
場合の入力経路として使う。画像はUI側でそのまま使えるよう `QPixmap` に
変換して返す。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolDescriptors

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


def render_structure_image(
    smiles: str,
    size: tuple[int, int] = (300, 300),
    device_pixel_ratio: float = 1.0,
    molblock: str | None = None,
) -> QPixmap:
    """SMILES文字列から2D構造式画像を生成し、`QPixmap` として返す。

    ChemDraw風の自前線画レンダラー(`core/lineart_render.py`)で描画する。
    平面レイアウトが破綻する構造(トリプチセンのような橋かけ環など)は
    `build_scene(mode="auto")`が自動的に3D配座を正射影した立体線画へ
    切り替える(奥行きを濃淡と隠線ギャップで表現する)。

    ライブラリ由来の化合物で`LibraryEntry.preview_svg`が保存済みの場合は、
    毎回ここで生成し直すのではなく`rasterize_svg(entry.preview_svg, size)`を
    直接使うほうが望ましい(カードグリッドで多数を同時に描く際の負荷軽減)。

    `device_pixel_ratio`は表示先ウィジェットの`devicePixelRatioF()`を渡すと
    HiDPI画面でのにじみを防げる(既定1.0=従来通り)。

    `molblock`(Ketcherの2D座標つきMOLブロック)を渡すと、ユーザーが整えた
    向きをそのまま使い、CoordGenでの再レイアウトをスキップする。

    `Scene`の組み立ては`get_or_build_scene`のインメモリキャッシュを経由する
    (同じ構造を何度も描く際の計算集約、Stage 3)。
    """
    scene = lineart_render.get_or_build_scene(smiles, mode="auto", molblock=molblock)
    svg = lineart_render.render_svg(scene, params=lineart_render.RenderParams(width=size[0], height=size[1]))
    return rasterize_svg(svg, size, device_pixel_ratio)


def generate_preview_svg(smiles: str, render_mode: str = "auto", molblock: str | None = None) -> str:
    """`LibraryEntry.preview_svg`に保存するためのSVG文字列を生成する。

    `viewBox`付きのSVGとして保存するため、後から`rasterize_svg`で任意の
    表示サイズ(テーブルヘッダ90×70・ライブラリカード110×85・登録
    プレビュー168×128)に再ラスタライズできる。

    `molblock`を渡すと、ユーザーが整えた向きをそのまま焼き込む。
    """
    scene = lineart_render.get_or_build_scene(smiles, mode=render_mode, molblock=molblock)
    return lineart_render.render_svg(scene)


def rasterize_svg(svg: str, size: tuple[int, int], device_pixel_ratio: float = 1.0) -> QPixmap:
    """SVG文字列を指定サイズの`QPixmap`にラスタライズする。

    `device_pixel_ratio`(既定1.0)を1より大きくすると、論理サイズ(`size`)は
    変えずに物理ピクセル数だけ引き上げてラスタライズし、
    `QPixmap.setDevicePixelRatio()`を設定する。HiDPI画面でのにじみ対策。
    """
    physical_w = max(round(size[0] * device_pixel_ratio), 1)
    physical_h = max(round(size[1] * device_pixel_ratio), 1)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(physical_w, physical_h)
    pixmap.setDevicePixelRatio(device_pixel_ratio)
    pixmap.fill(Qt.GlobalColor.white)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, physical_w, physical_h))
    painter.end()
    return pixmap


def build_molblock_from_scene(scene: lineart_render.Scene, rotation: tuple[float, float, float, float] = (1, 0, 0, 0)) -> str:
    """3Dタブ(`ui/molecule_3d_view.py`)で表示中の`Scene`に対し、ユーザーが
    ドラッグで回転させた「今見ている向き」のXY座標で2Dレイアウトを持つ
    MOLブロックを作る(「この向きを2Dに反映」用)。

    `Scene`は原子・結合・(初期姿勢を含む)配座を自己完結で持っているため、
    3D配座を再生成する必要はなく、`compute_geometry`と同じ回転行列を
    座標へ直接適用して`RWMol`を組み立て直すだけでよい
    (`lineart_render.scene_to_mol`と共有、3Dクリーンアップ機能も同じ
    経路を使う)。
    """
    mol = lineart_render.scene_to_mol(scene, rotation, flatten=True)
    return Chem.MolToMolBlock(mol)


def _mol_from_smiles(smiles: str) -> Chem.Mol:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"SMILESを解析できません: {smiles!r}")
    return mol
