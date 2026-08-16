# MolWeigh

既存Excelマクロ「当量計算表」を再実装する、試薬の当量(eq)計算・個人試薬ライブラリ・化合物検索を備えたデスクトップアプリ。

## 開発状況

MVP優先で段階的に実装中(計算コア → DB → 化学式パーサー → RDKit/PubChem連携 → GUI → パッケージング)。

## セットアップ(開発)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pytest
```

## 動作環境

- Python 3.11推奨(RDKit/PySide6の対応状況が安定)。開発機は現状Python 3.13。
- GUI: PySide6 / 化学計算: RDKit / DB: SQLite
- Windows優先で開発。macOS(Apple Silicon)対応は実機確保後に着手。
