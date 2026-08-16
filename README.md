# MolWeigh

既存Excelマクロ「当量計算表」を再実装する、試薬の当量(eq)計算・個人試薬ライブラリ・化合物検索を備えたデスクトップアプリ。

## 開発状況

Phase 1〜6完了(計算コア・化学式パーサー・DB層・RDKit/PubChem連携・解決ロジック統合・PySide6 GUI)。
残りはPhase 7/8(macOS/Windowsパッケージング)。テストは`tests/`配下に125件。

## 起動

```bash
python main.py
```

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
