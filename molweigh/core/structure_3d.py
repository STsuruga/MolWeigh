"""RDKitによる3D配座生成(ChemDrawの「3D Clean Up」に相当する処理)。

Ketcher自身の「3D Viewer」はMiewエンジンによる単純な回転表示に過ぎず、
エネルギー最小化は行わない。しかも回転後に「Apply」で2D構造へ書き戻すと
立体中心が壊れることがある、とKetcher自身が警告している。そのため3D生成は
Ketcherの2D編集データとは完全に切り離した別経路とし、ここで生成した3D構造を
2Dへ書き戻すことは一切行わない(読み取り専用のプレビュー用途に限定する)。
"""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import AllChem

_EMBED_SEED = 0xC0FFEE


def embed_and_optimize(smiles: str) -> Chem.Mol:
    """SMILESから水素付加・立体配座生成・力場最適化(MMFF94、失敗時UFF)を行い、
    3D配座(明示的な水素付き)を持つRDKitのMolを返す。"""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"SMILESを解析できません: {smiles!r}")
    mol = Chem.AddHs(mol)

    params = AllChem.ETKDGv3()
    params.randomSeed = _EMBED_SEED
    if AllChem.EmbedMolecule(mol, params) < 0:
        params.useRandomCoords = True
        if AllChem.EmbedMolecule(mol, params) < 0:
            raise ValueError("3D構造を生成できませんでした。構造が特殊すぎる可能性があります。")

    try:
        converged = AllChem.MMFFOptimizeMolecule(mol)
    except (RuntimeError, ValueError):
        converged = -1
    if converged != 0:
        AllChem.UFFOptimizeMolecule(mol)

    return mol
