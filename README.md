# MolWeigh

既存Excelマクロ「当量計算表」を再実装する、試薬の当量(eq)計算・個人試薬ライブラリ・化合物検索を備えたデスクトップアプリ。

## 開発状況

Phase 1〜6完了(計算コア・化学式パーサー・DB層・RDKit/PubChem連携・解決ロジック統合・PySide6 GUI)。
残りはPhase 7/8(macOS/Windowsパッケージング)。テストは`tests/`配下に294件。

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

### 構造式エディタ(Ketcher)の準備

「化合物が見つかりません」ダイアログの「構造式を描く…」ボタンは、
[Ketcher](https://github.com/epam/ketcher)(オープンソースの構造式エディタ)を
`QWebEngineView`で埋め込んで使う。リポジトリには同梱していないため、
初回セットアップ時にNode.js(https://nodejs.org/ )を導入した上で以下を実行する。

```bash
python scripts/build_ketcher.py
```

`molweigh/ui/vendor/ketcher/` にビルド成果物が配置される(`.gitignore`済み)。
未配置の場合、「構造式を描く…」ボタンは警告を出すだけで、他の機能(化学式/SMILESの
テキスト入力)には影響しない。

### 3D構造プレビュー

構造入力パネルの「3D」タブは、`QPainter`で直接描画する自前実装のビューアで、
外部ライブラリ・追加セットアップは不要(`QWebEngineView`を使わないため、
Ketcher用のセットアップだけで動作する)。ドラッグして回転させた今の向きを、
「この向きを2Dに反映」ボタンでKetcherの2D構造式に書き戻すこともできる。

## 動作環境

- Python 3.11推奨(RDKit/PySide6の対応状況が安定)。開発機は現状Python 3.13。
- GUI: PySide6 / 化学計算: RDKit / DB: SQLite
- Windows優先で開発。macOS(Apple Silicon)対応は実機確保後に着手。
