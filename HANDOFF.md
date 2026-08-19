# MolWeigh 引継ぎメモ

このファイルは新しいチャットセッションで作業を再開するための起点。
詳細な技術仕様は [`MolWeigh_仕様書.md`](MolWeigh_仕様書.md) を参照(第4章が
特に頻繁に変わっている分子構造描画まわり)。このメモは「今どこにいて、
次に何をすべきか」を素早く把握するためのもの。

## プロジェクトの位置づけ

既存Excelマクロ「当量計算表」を再実装した、試薬の当量(eq)計算・個人試薬
ライブラリ・化合物検索・分子構造描画を備えたPySide6製デスクトップアプリ。
リポジトリ: https://github.com/STsuruga/MolWeigh (public)。

## 現在の状態(2026-08-19時点)

- Phase 1〜6(計算コア・DB・RDKit/PubChem連携・GUI)は完成、テスト294件全パス。
- **分子構造の描画部分を今回のセッションで全面刷新した**(自前のChemDraw風
  線画レンダラー`core/lineart_render.py` + QPainter直描きの3Dタブ)。
  詳細と設計判断の経緯は仕様書4章、特に4.8節「3D関連実装の変遷」を参照。
  **3Dmol.js → 自前WebEngine版 → 3Dmol.js → 現行のQPainter版、と3回作り
  直している**。同じ問題(実機で白紙描画)に当たったら4.8節をまず読むこと。
- ユーザーから「分子構造の描画はまだ不満あるけど一回リリース」との発言あり。
  **具体的に何が不満かはこのセッションでは聞けていない**。次のセッションで
  真っ先に確認すべき事項。憶測だが、線画の見た目の質(線の太さ・隠線ギャップの
  出方)や、`render_mode`(`auto`/`flat`/`solid`)を手動切り替えるUIが
  まだ無いことが候補として考えられる。
- **Win/Mac向けの初回リリース(v0.1.0)を今回のセッションで完了した**。
  https://github.com/STsuruga/MolWeigh/releases/tag/v0.1.0
  Windows版はローカルビルド・実機動作確認まで完了、GitHub Actions CIで
  Windows/macOS両方のビルドが成功し、両OS分のzipをGitHub Releaseに添付
  済み。進捗は下記「パッケージング/リリース」節を参照。

## アーキテクチャの要点(詳細は仕様書1章・4章)

```
core/lineart_render.py   Qt非依存の線画レンダラー本体(SVG出力)。平面/立体を
                          「実際にレイアウトして破綻を測る」方式で自動判定。
core/structure.py         SMILES↔RDKit Molの窓口。render_structure_image()が
                          唯一の共通描画入口。realign_bridged_structure_molblock()
                          は「橋かけ構造を整列」ボタン用(lineart_renderと
                          同じcanonical_rotationを通るよう統一済み=今回直した
                          不具合、後述)。
ui/molecule_3d_view.py    QWebEngineViewを使わないQPainter直描きの3Dビュー。
ui/structure_3d_tab.py    3Dタブの中身(Molecule3DView + SceneBuilder + 反映ボタン)。
ui/scene_builder.py       3D配座生成をバックグラウンドスレッドで行うワーカー。
ui/structure_editor.py    Ketcher埋め込み(get_smiles/get_molblock)。
```

## このセッションで踏んだ地雷(次に同じ轍を踏まないために)

1. **`.strip()`はMOLブロックを壊す**。Ketcherの`getMolfile()`結果に
   `.strip()`をかけると必須の空行(1行目)が消え、RDKitのパースが全行ズレて
   失敗する。`structure_editor.py`の`_on_poll_result`は`.rstrip()`に修正済み。
   同様の文字列処理をどこかに追加するときは要注意。
2. **向き選択アルゴリズムは1つに統一すること**。かつて`structure.py`に
   独自のPCAベース`orient_canonically`があり、`lineart_render.py`の
   球面サンプリング方式`canonical_rotation`と別々に存在していた結果、
   「Ketcherに書き戻す向き」と「カードのプレビュー」が同じ分子なのに
   違う向きで表示される不具合が実際に起きた(ユーザー報告で発覚)。今は
   `realign_bridged_structure_molblock`も`lineart_render.build_scene`を
   通るよう統一済み。**新しい「向きを決める」処理を書きたくなったら、まず
   既存の`canonical_rotation`を使えないか検討すること**。
3. **QWebEngineViewを大量に使うテストは同一プロセスでクラッシュしうる**
   (`Windows fatal exception`、exit code 127など症状は複数パターン)。
   `test_structure_input_panel.py`・`test_reagent_editor_dialog.py`は
   ファイル単位どころかクラス単位でもまれに落ちる。個々のテストロジックが
   正しいかはテスト単位まで分けて確認すること(仕様書9章に詳細)。

## パッケージング/リリース(完了 — v0.1.0公開済み)

- `molweigh.spec`(PyInstaller仕様)をリポジトリ直下に追加。Ketcherの
  静的ビルド(`molweigh/ui/vendor/ketcher/`、`scripts/build_ketcher.py`で
  事前生成が必要)とRDKitのデータファイルを同梱する。spec内で`__file__`は
  使えない(PyInstallerが`exec()`するため未定義)。代わりにPyInstallerが
  注入する`SPECPATH`を使うこと。
- `.github/workflows/build.yml`を追加。**物理Mac実機がないため、macOS
  ビルドはGitHub Actionsの`macos-latest`ランナーで行う方針**(Windows側は
  ローカルで直接ビルド・検証可能)。`workflow_dispatch`(手動実行)と
  `v*`タグpushの両方でトリガーされる。
- **Windows版はローカルビルド→実機起動→スクリーンショットで動作確認済み**
  (ソースツリー外の作業ディレクトリから起動し、相対パス依存のバグを
  検出できる状態で確認)。ユーザーから「exe化したときにバックエンド機能が
  壊れていないか確認して」との明示的な指示があったため、以下を確認した:
  - Ketcher(QWebEngineView+ローカルHTTPサーバー)がツールバーごと正常に
    ロードされ、実際にベンゼン環を描画できた(インタラクティブに動作)。
  - PubChemパネル(QWebEngineView+HTTPS)が実際のNIH/PubChemページを
    ロードできた → `requests`/`certifi`のCA証明書バンドルが凍結ビルドでも
    正しく解決されている証拠。
  - `db/paths.py`のAppDataパス解決 → 既存の開発時DB(`%APPDATA%\MolWeigh\
    molweigh.db`)がexe版でもそのまま読み込めた(ライブラリカードに
    DMAP/aspirinが表示され、新レンダラーのSVGプレビューも正しく描画)。
  - **QPainter直描きの3Dタブ**(今回のセッションで最も大きく変更した部分)
    →「2D編集」でベンゼン環を描き、「3D」タブに切り替えて正常にレンダリング
    されることを確認。「この向きを2Dに反映」「向きをリセット」ボタンも
    表示された。このタブはWebEngineに依存しないため、パッケージング起因の
    問題が起きるリスクはそもそも低いが、念のため確認できた。
  - 上記により、`requests`/HTTPS証明書・`__file__`相対パスのデータファイル
    (Ketcherベンダーディレクトリ・RDKitデータ)・OS別AppDataパス解決という、
    「開発時は動くがexe化すると壊れる」典型的な落とし穴は一通り確認済み。
  - macOSビルドは物理実機がないため実機動作は未確認だが、CIビルド自体は
    成功している(GitHub Actions run `32209970484`、両OSとも成功、
    成果物`MolWeigh-windows`/`MolWeigh-macos`をアップロード済み)。
    CDXML連携等未実装機能は対象外。
  - **CI構築で踏んだ地雷**(`scripts/build_ketcher.py`、2件とも修正済み):
    1. `subprocess.run(["npm", ...])`は`shell=False`だとWindowsで
       `FileNotFoundError: [WinError 2]`になる。`npm`は`npm.cmd`という
       シムでCreateProcessが直接実行できないため。`shutil.which()`で
       解決した実パスを渡すよう修正。ローカルで気づかなかったのは、
       Ketcherのベンダーディレクトリが既にこのスクリプト以前の方法で
       作られていて、このスクリプトのnpm呼び出し自体を実行していな
       かったため。
    2. GitHub ActionsのWindowsランナーはコンソールが既定でcp1252になって
       おり、日本語の`print()`が`UnicodeEncodeError`で落ちる。
       `sys.stdout.reconfigure(encoding="utf-8")`で回避。他のスクリプトで
       Windows CI上で日本語を`print()`する場合は同じ問題に当たりうる。
    3. **`actions/upload-artifact`はディレクトリをアップロードする際に
       シンボリックリンクを実体化(コピー)する。** macOSの`.app`バンドル
       内のQtフレームワークは`Versions/Current -> A`等のシンボリックリンク
       を多用しており、これが実体化されると本来200MB台のバンドルが
       3.7GBまで肥大化した(実際に発生し、気づかず初回ダウンロードを
       試みて2分でタイムアウトしたことで発覚)。対策として`build.yml`の
       macOSジョブでは`ditto -c -k --sequesterRsrc --keepParent`で
       ランナー上で先にzip化してから単一ファイルとしてアップロードする
       よう変更済み(Windows側も`Compress-Archive`で統一)。**ディレクトリ
       ごとアーティファクトとしてアップロードする設計は避け、必ず
       ランナー上でアーカイブ化してから単一ファイルをアップロードする方が
       安全**、というのが得られた教訓。
  - **窓ターゲティングの罠**: exe化した別プロセスのウィンドウをPowerShellの
    `SetForegroundWindow`で操作しようとした際、`Get-Process`の
    `MainWindowHandle`が安定する前にクリックすると、誤って全く別の
    ウィンドウ(このセッションではIDE自体)をクリックしてしまったことがある。
    プロセス起動後は数秒待ってから`MainWindowTitle`/`MainWindowHandle`が
    有効な値になっているか確認し、`SetForegroundWindow`実行後は必ず
    `GetForegroundWindow()`で実際に意図したハンドルが前面に来たかを
    検証してからクリックすること。
- 進捗は本セッションの残りタスクを参照。中断した場合、`git log`と
  `gh run list`でどこまで終わっているか確認できる。

## 次にやること(優先順)

1. **ユーザーに「分子構造の描画の何が不満か」を具体的に聞く**。曖昧なまま
   手を動かさない。
2. パッケージング/リリースは完了。次にリリースする際は、`molweigh.spec`の
   `CFBundleShortVersionString`とgitタグのバージョン番号を一致させること
   (今回は両方とも`0.1.0`)。タグ付け・Release作成は公開リポジトリへの
   可視アクションのため、実行前に必ずユーザーに確認すること。
3. `LibraryEntry.render_mode`を手動切り替えるUIが無いこと(仕様書10章に
   既知の制約として記載済み)。不満の正体がこれなら着手候補。
4. CDXML(ChemDraw)連携は未着手(独立した小機能、仕様書10章参照)。
