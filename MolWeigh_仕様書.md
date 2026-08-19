# MolWeigh 仕様書

既存Excelマクロ「当量計算表」を再実装した、試薬の当量(eq)計算・個人試薬ライブラリ・
化合物検索・分子構造描画を備えたPySide6製デスクトップアプリ。

- リポジトリ: `D:\ユーザー\shuta\ドキュメント\MolWeigh`
- 起動: `python main.py`
- テスト: `tests/` 配下に294件(pytest)
- 主要スタック: PySide6(GUI) / RDKit(化学計算・構造処理) / SQLite(DB) / Ketcher(2D構造式エディタ、Web埋め込み) / 自前実装のChemDraw風線画レンダラー(`core/lineart_render.py`、Qt非依存・SVG出力)

---

## 1. 全体アーキテクチャ

3層構成。UI層は他の層に依存するが、逆方向の依存はない(coreはQt非依存の純粋ロジックを目指す)。

```
molweigh/
├── core/     … Qt非依存の計算・データ処理ロジック
│   ├── calc.py             当量(eq)計算の中核(旧Excelマクロのセル式を1:1移植)
│   ├── formula_parser.py   化学式文字列 → 分子量(RDKit不使用、正規表現+原子量表)
│   ├── structure.py        SMILES → RDKit Mol、2D/3D構造の統合窓口(★詳細は第4章)
│   ├── lineart_render.py   ChemDraw風線画レンダラー本体(Qt非依存、★詳細は第4章)
│   ├── structure_3d.py     3Dプレビュー(旧経路)用の3D配座生成(★詳細は第4章)
│   ├── pubchem_client.py   PubChem PUG REST/PUG-View APIラッパー
│   └── compound_source.py  化合物解決の統合窓口(ライブラリ→PubChem→手動入力)
├── db/       … SQLite永続化
│   ├── schema.py           PRAGMA user_versionベースのマイグレーション
│   ├── paths.py            OS別アプリデータディレクトリ解決
│   ├── library_repo.py     個人試薬ライブラリのCRUD
│   └── template_repo.py    テンプレート(条件セット)のCRUD
├── ui/       … PySide6ウィジェット群
│   ├── main_window.py             メインウィンドウ(全パネルの統合)
│   ├── reagent_table.py           当量計算テーブル
│   ├── structure_input_panel.py   構造入力パネル、「2D編集」/「3D」タブ(★詳細は第4章)
│   ├── structure_editor.py        Ketcher埋め込み本体(★詳細は第4章)
│   ├── structure_3d_tab.py        「3D」タブの中身(★詳細は第4章)
│   ├── molecule_3d_view.py        QPainter直描きの3D構造ビュー(★詳細は第4章)
│   ├── scene_builder.py           3D配座生成をバックグラウンドスレッドで行うワーカー
│   ├── library_dialog.py          試薬ライブラリのカードグリッド
│   ├── template_list_panel.py     テンプレート一覧(常設・軽量)
│   ├── template_list_dialog.py    テンプレート管理ウィンドウ(編集・削除)
│   ├── pubchem_browser_panel.py   PubChem埋め込みブラウザ
│   ├── reagent_editor_dialog.py   化合物登録ダイアログ
│   └── theme.py                   共有スタイル定数・グローバルQSS
├── main.py   … 起動エントリポイント
scripts/
└── build_ketcher.py   Ketcherの静的ビルドを取得(初回セットアップ、要Node.js)
```

---

## 2. 画面構成

メインウィンドウは1つの`QMainWindow`で、コードのみでレイアウトを組み立てる(`.ui`ファイルなし)。

```
┌─────────────────────────────────────────────────────────────────┐
│ weight単位: [mg ▾]                                                │
├───────────────────────────┬─────────────────────────────────────┤
│ 【左カラム(幅1)】           │ 【右カラム(幅2)】                    │
│                            │                                     │
│ 当量計算テーブル             │ 構造入力パネル(幅1)                  │
│ (ReagentTableWidget)       │ (StructureInputPanel)               │
│                            │  Ketcher編集画面 + 分子量/化学式表示  │
│ [テンプレートに追加]         │  + 4つの操作ボタン                   │
│ [テンプレート管理]           │                                     │
│         [テーブルをリセット] ├─────────────────┬───────────────────┤
│                            │ 化合物ライブラリ   │ PubChem検索       │
│ テンプレート一覧             │ (LibraryGridWidget)│(PubChemBrowser  │
│ (TemplateListPanel)        │  カードグリッド     │ Panel)          │
│                            │                   │ 埋め込みブラウザ  │
└───────────────────────────┴─────────────────┴───────────────────┘
```

- 左右比は1:2(構造描画・ライブラリ・PubChem検索を優先的に広く取る)。
- 当量計算テーブルは内容にぴったり合う高さ(`content_height()`)に固定し、余った縦スペースはテンプレート一覧に回す。
- 構造入力パネル・PubChem検索パネルはどちらも常時展開(開閉トグルなし)。

---

## 3. 主要機能

### 3.1 当量(eq)計算テーブル(`reagent_table.py`)

- 列 = 試薬(動的に追加/削除)、行 = `Fw / weight / d(g/cm3) / volume(mL) / molarity(M) / mmol / eq` の固定7行。
- 先頭列(列0)は常に**基準試薬**。基準の`Fw`と`weight`から`mmol`を算出し、他の列はそれを基準にeqを計算する。
- 各非基準列は以下の優先順位で計算モードが決まる(`_recompute_column`):
  1. `volume_ml` + `density` + `fw` が揃っている → 体積×比重を実測値として`mmol`・`eq`を逆算(`weight`を自動補完)
  2. `weight_is_actual` が真で `weight_value` + `fw` がある → 実測重量から`mmol`・`eq`を逆算(`density`があれば`volume`も補完)
  3. `target_eq` + 基準`mmol` がある → 目標eqから必要`mmol`・`weight`を算出(**秤量計画モード**、`molarity`のみ設定時は`weight`を介さず`volume`だけ算出)
  4. いずれも無ければ未計算
- eqセルは状態に応じて背景色が変わる:基準列=グレー、実測由来=緑、目標(計画)由来=青。
- weight単位(`mg`/`g`)は全列共通の1つのコンボボックスで一括切替(単位変更時は既存値を自動換算)。行ラベルにも現在の単位を表示(例:`weight(mg)`)。
- **左端の行ラベル列(Fw〜eq)は横スクロールしても常に表示される**(Excelのウィンドウ枠固定に相当)。同じQtモデルを共有する`QTableView`をcolumn 0の上にオーバーレイし、縦スクロール位置を双方向同期させる方式で実装。
- 分子量(Fw)の**表示は小数点以下2桁**(`_fmt_fw`)、その他の数値表示は有効数字4桁(`_fmt`)。ただし内部で保持する分子量の精度は4桁で丸め済み(化合物解決の時点で丸める、後述)。
- 各列ヘッダーには構造式サムネイル(`structure.render_structure_image`)・試薬名・化学式・未保存バッジ("追加"ボタンでライブラリへ保存)・削除("×")ボタンを表示。

### 3.2 個人試薬ライブラリ(`library_dialog.py`, `db/library_repo.py`)

- カードグリッド形式(`LibraryGridWidget`)。カード1件につき構造式画像・名前・化学式・CAS番号・分子量(小数点2桁)・比重を表示。
- カードサイズは固定(138×240px)で、パネル幅に応じて列数だけが可変(カード自体の大きさは変わらない)。
- 検索ボックスでリアルタイム絞り込み(名前/CAS/化学式の部分一致)。
- 使用回数(`use_count`)の多い順にソート表示。カードから「追加」を押すと計算テーブルへ反映され、使用回数がインクリメントされる。
- 「+ 新しい化合物を登録」から`ReagentEditorDialog`を開いて新規登録できる。
- ライブラリへの自動保存はしない(検索するたびに何でも増えると収拾がつかなくなるため)。ユーザーが明示的に保存操作をした場合のみ登録される。

### 3.3 テンプレート(条件セット)(`template_list_panel.py`, `template_list_dialog.py`, `db/template_repo.py`)

- 現在の計算テーブルの内容を「テンプレート」として保存し、後で一括呼び出しできる。
- 保存対象は`library_id`を持つ列のみ(ライブラリ未登録の列は含まれない=先に個別保存が必要)。
- テンプレートの中身は試薬を`library_id`で参照するJSON(生の分子量等は持たない)。呼び出し時にライブラリから最新値を引き直すため、ライブラリ側の情報更新が自動的に反映される。
- メイン画面下部の`TemplateListPanel`(常設・スクロール一覧・ダブルクリックで呼び出し)と、`TemplateListDialog`(名前変更・組成編集・削除ができる管理ウィンドウ)の2つの入口がある。

### 3.4 化合物解決(`core/compound_source.py`)

呼び出し優先順位:
1. **個人ライブラリ**(完全一致優先、なければ最初の部分一致を自動採用。複数候補からの選択UIは未実装)
2. **PubChem**(名前/CAS検索 → CID → 分子量・化学式・SMILES・可能なら比重)
3. どちらもヒットしない場合はUI側が化学式入力/構造式描画にフォールバック

いずれの経路で解決しても**ライブラリへの自動保存はしない**。分子量は解決時点で小数点以下4桁に丸める(表示は2桁だが、計算にはこの4桁精度の値を使う)。

---

## 4. 分子構造の描画(詳細)

分子構造まわりは大きく分けて **(A) 2D構造式の編集(Ketcher)**、**(B) ChemDraw風線画レンダラーによる静的レンダリング**、**(C) 3Dタブ(QPainter直描き)**、**(D) 「この向きを2Dに反映」** の4つの仕組みで構成される。旧仕様(WebEngineベースの3Dmol.js/自前JSビューア、橋かけ構造専用の分岐)は全面的に置き換えた(下記4.8節に経緯を記す)。

### 4.1 (A) Ketcherによる2D構造式編集(`ui/structure_editor.py`)

[Ketcher](https://github.com/epam/ketcher)(EPAM製オープンソース構造式エディタ、React製Webアプリ)を`QWebEngineView`に埋め込んで使用する。

- **オフライン配信の仕組み**: Ketcherのビルド成果物(`molweigh/ui/vendor/ketcher/`、`scripts/build_ketcher.py`で取得・`.gitignore`済み)を、`http.server.ThreadingHTTPServer`でOSが割り当てた空きポート(`127.0.0.1:0`)からデーモンスレッドで配信する。`file://`直接オープンではCRAビルドの絶対パスアセット参照が壊れるため、この方式を採用している。
- **`KetcherView(QWidget)`**が中核の再利用可能部品。`StructureInputPanel`(メイン画面常設)と`ReagentEditorDialog`(化合物登録ダイアログ)の両方から使う。
- **非同期取得パターン**: `QWebEngineView.page().runJavaScript()`のコールバックはJSのPromiseを直接awaitできない制約があるため、`window.ketcher.getSmiles()`/`getMolfile()`の結果を`window.__molweighResult`というグローバル変数に書き込ませ、Python側は150ms間隔・最大40回(=6秒)のポーリングで読み取る(`get_smiles(callback)` / `get_molblock(callback)`)。
  - **既知のバグと修正**: 取得結果に`.strip()`を適用すると、MOLブロックの1行目(分子名、多くの場合空行)が失われて以降の全行がズレ、RDKitがパースに失敗する(`Cannot convert '...' to unsigned int on line 4`)。SMILESと違いMOLブロックは行位置が構造的な意味を持つため、末尾のみを削る`.rstrip()`に変更して修正した。
- **`set_smiles(text)`**は`window.ketcher.setMolecule(text)`を呼ぶ。名前に反して、渡す文字列はSMILESに限らず**MOLブロック文字列でもよい**(Ketcher側が自動判定する)。「橋かけ構造を整列」「この向きを2Dに反映」機能はこの性質を使ってKetcherのキャンバスへ書き戻す。
- `shutdown()`でローカルHTTPサーバーを停止する(ウィンドウを閉じる際に必ず呼び出す必要がある)。

### 4.2 (B) ChemDraw風線画レンダラー(`core/lineart_render.py`) ★最重要

Qt非依存(numpy + RDKitのみに依存)の純関数モジュール。分子ごとに前計算済みの`Scene`を組み立て、そこへ任意の回転(クォータニオン)を適用して**SVG文字列**を生成する。座標そのものは書き換えず、姿勢は別パラメータとして都度適用するため、回転が非破壊でありやり直し・保存・比較が素直に行える。

**平面/立体の自動切替(`build_scene(smiles, mode="auto")`)**:

| mode | 挙動 |
|---|---|
| `flat` | 従来型の平面構造式(RDKitのCoordGenレイアウト+楔形) |
| `solid` | 3D配座を正射影した立体線画(深度キュー+隠線ギャップで奥行きを表現) |
| `auto`(既定) | まず平面で描き、**レイアウトが実際に破綻しているかを測って**立体に切り替える |

判定は構造的なルール(橋かけ原子の有無など)では行わない。シクロヘキサンやステロイドは非平面な構造だが平面の六角形で描くのが化学者の慣例であり、構造ルールで判定すると誤って立体側に落ちるため、**実際に平面レイアウトを生成し、その破綻度を測る**方式にした:

- **最小原子間距離**(標準結合長で正規化) < `FLAT_DMIN_MIN`(0.42) → 重なって読めない
- **結合線の交差数** > `FLAT_MAX_CROSSINGS`(0) → 環系が平面に展開できていない

どちらか一方でも該当すれば立体に切り替える(カンファーは交差数ゼロだが原子間距離だけが破綻しており、両方の指標が必要なことを示す実例)。塩・水和物はSMILESを`.`で分割し、フラグメントごとに`build_scene`を再帰呼び出しして向きを個別に決めたうえで、重原子数の多い順に1.6Å間隔で横並びに配置する(ETKDGが対イオンや結晶水を分子本体の任意の位置に置くため、素朴に描くと重なる対策)。単独分子は`H2O`/`HCl`のように水素を先に書く慣習に従う。

**立体モードの配座生成(`lineart_render.embed_and_optimize`)**: `core/structure_3d.py`とは別の実装。見やすさ優先で、24配座を`EmbedMultipleConfs`(ETKDGv3、固定シード)し、力場(MMFF94、フォールバックUFF)は「破綻した形を弾く」役割に留め、**採用する配座は投影したときの見やすさ(`_clarity`:48方向サンプリングで全原子ペア最小距離を最大化)で選ぶ**。単一配座のETKDGでは鎖状分子がゴーシュに折れることがある(デカンで実測確認)ため、複数配座からの選択が必須と判断した。

**初期姿勢(`canonical_rotation`)**: 旧`orient_canonically`(PCA主軸3本から3候補)は使わない。トリプチセンのような対称分子は共分散行列の固有値が縮退し固有ベクトルが不定になるため機能しない。代わりにFibonacci格子で半球上に160方向をサンプリングし、各方向を奥行きにした2D投影の最小原子間距離を総当たりでスコア化する。

**隠線ギャップ・深度キュー**: 全結合ペアの線分交差をnumpyでベクトル化して判定し(O(n²)だが結合数は高々数百)、交差点でのZは端点からの補間`t`/`u`で求める(端点のZで比較すると斜め交差で誤る)。奥側の結合に「手前側の線幅×`gap_ratio`(2.5)」のギャップを開ける(固定px幅だとズーム時に破綻するため)。深度→濃淡変換には`min_span`ガード(力場最適化後の数値誤差で平面分子がまだらのグレーになるのを防ぐ)、`depth_gamma`(線形だと中間深度が一律グレーに沈むのを防ぐ)、`min_t`下限(長鎖の奥端が消えるのを防ぐ)の3つのガードを入れている(いずれも実測で必要と判明)。

**共有ジオメトリ(`compute_geometry`)**: 描画片(線分・楔形・ラベル、色はRGB整数タプル)を計算する部分を`RenderGeometry`として切り出し、SVG文字列化(`render_svg`)とQPainter直描き(4.3節)の両方がこれを共有する。二重実装を避けるための設計。

**処理時間の実測**(20〜28原子、仕様書内部データ): 配座生成(初回のみ)は284ms〜3.1秒、描画/フレームは分子サイズにほぼ依存せず2ms前後。**描画自体はPythonのまま60fpsに十分間に合う**(JS/WebGLへ逃がす必要はない)。旧QPainter実装が遅かったのはフレームごとにRDKit側で再計算していたためで、前計算済みのnumpy配列に行列積を掛けるだけなら問題にならない。一方**配座生成は最大3〜4秒**かかるため、必ずバックグラウンドスレッド(4.3節`scene_builder.py`)に逃がす。

### 4.3 (C) 3Dタブ(`ui/structure_3d_tab.py`, `ui/molecule_3d_view.py`, `ui/scene_builder.py`)

`StructureInputPanel`/`ReagentEditorDialog`は`QTabWidget`で「2D編集」/「3D」の2タブを持つ(旧「3Dプレビュー」ボタン+別ダイアログ方式から変更)。

- **タブ切替時の非同期生成(`scene_builder.py::SceneBuilder`)**: 「3D」タブに切り替えると、Ketcherの`getMolfile()`→`structure.smiles_from_molblock()`(楔形からRDKitが立体化学を自動判定、`MolToSmiles`)で得たSMILESを`QThread`上でバックグラウンド生成する。構造が変わって再度呼ばれた場合、世代カウンタ(`_generation`)で古いジョブの結果を無視する(「生成中に構造が変わったら前のジョブを破棄する」という要件)。
- **`Molecule3DView(QWidget)`**: `paintEvent`で`compute_geometry`の結果を直接描画する(`QGraphicsView`は不要)。`QWebEngineView`を一切使わないため、既知の環境依存クラッシュ(WebEngineを大量に使うテストでのネイティブクラッシュ、4.9節参照)から解放される。
  - 操作: 左ドラッグ=アークボール回転(ドラッグ点を仮想球上のベクトルに写し、その間の回転を現在姿勢に左から合成)、ホイール=ズーム、中ドラッグ=パン、矢印キー=15°ステップ回転、`R`キーで初期姿勢にリセット、ドラッグ終了時は角速度を`QTimer`(16ms間隔)で0.92倍ずつ減衰させる慣性を持つ。
- **`Structure3DTab(QWidget)`**: 上記2つを束ね、「配座を生成中…」の状態表示、失敗時のエラー表示、「この向きを2Dに反映」「向きをリセット」ボタンを提供する。

### 4.4 (D) 「この向きを2Dに反映」(`structure.build_molblock_from_scene`)

3Dタブでユーザーがドラッグで回転させた**今の見た目**を、そのまま2Dレイアウトを持つMOLブロックとしてKetcherへ書き戻せる。

```python
R = quat_to_matrix(rotation) @ scene.initial_rotation
xyz = scene.coords @ R.T   # 現在の回転を適用したXYZ
```

`Scene`は原子記号・結合・形式電荷(`formal_charges`)を自己完結で持っているため、3D配座を再生成する必要はなく、この回転行列を座標へ直接適用して`Chem.RWMol`を組み立て直すだけでよい(塩の形式電荷も保持されるよう`atom.SetFormalCharge()`を設定する)。呼び出し側(`structure_input_panel.py`/`reagent_editor_dialog.py`)は`Structure3DTab`の`on_reflect`コールバックで`ketcher.set_smiles(molblock)`を呼び、2D編集タブへ自動的に切り替える。

### 4.5 なぜKetcher自身の3D機能を使わないか

Ketcherには標準で「3D Viewer」ボタン(Miewエンジンによる表示)があるが、これは**単に回転して見るだけの機能でエネルギー最小化は行わない**。さらに、回転後に画面内の「Apply」ボタンで2D構造へ書き戻すと、Ketcher自身の警告文言(「Stereocenters can be changed after the strong 3D rotation」)の通り**立体中心が壊れることがある**ことを実機検証で確認した。これがユーザー報告のあった「3次元構造を反映すると赤いエラーマークが出る」現象の原因だった。

この経緯から、3D関連機能は既定でKetcherの2D編集データと切り離し、**読み取り専用のプレビュー**とする設計とした。ただし4.4節の「この向きを2Dに反映」機能は、Ketcher自身の「3D Viewer→Apply」とは全く別の実装(RDKit側で`Scene`から`RWMol`を再構築し、回転後のXY座標をMOLブロックへ書き込んで`setMolecule()`に渡す)であり、Ketcherの内部3D回転ロジックを一切経由しないため、上記の立体中心破壊は起きない。逆に楔形→立体化学の変換(4.3節`smiles_from_molblock`)は`Chem.MolFromMolBlock`のウェッジ結合自動判定に一度だけ通すだけで、Ketcher自身の3D回転ロジックには触れないため安全。

### 4.6 構造入力パネルのタブとボタン(`ui/structure_input_panel.py`)

メイン画面に常設される`StructureInputPanel`は、`QTabWidget`(左、「2D編集」=`KetcherView`/「3D」=`Structure3DTab`)と情報表示+3ボタンのサイドバー(右、幅150px固定)で構成される。`ReagentEditorDialog`にもほぼ同じ構成(「構造式を反映」という名称のみ異なるボタンが1つ追加)が実装されている。

| ボタン/操作 | 処理 | 説明 |
|---|---|---|
| **分子量を計算** | `get_smiles` → `compound_source.resolve_from_smiles` | 化学式・分子量ラベルを更新するのみ。計算テーブルには反映しない。「試薬に追加」を押す前でも確認できるようにするための機能。 |
| **「3D」タブに切替** | `get_molblock` → `smiles_from_molblock` → `SceneBuilder.build` | RDKitで見やすさ優先に選んだ3D配座を、QPainter直描きの`Molecule3DView`で表示。既定では2D構造に影響しないが、「この向きを2Dに反映」を押した場合のみ回転させた角度をKetcherの2D構造式に書き戻す(4.4節)。 |
| **橋かけ構造を整列** | `get_smiles` → `structure.realign_bridged_structure_molblock` → (橋かけなら)`ketcher.set_smiles(molblock)` | 現在Ketcherに描かれている構造が橋かけ構造(bridgehead原子あり)であれば、3D投影で見やすい向きに再配置したMOLブロックを**Ketcherのキャンバスへ書き戻す**。橋かけ構造でない場合は「整列は不要です」と案内するのみ。手描きで乱雑になった橋かけ構造をワンクリックで整理できる、Ketcher自身の自動レイアウトを外部から差し替えられないという制約への対処(4.2節の`auto`判定とは別軸の機能として存置)。 |
| **試薬に追加** | `get_smiles` → `resolve_from_smiles` → `added_to_table.emit(info)` | 化学式・分子量ラベルを更新し、`CompoundInfo`を計算テーブルへ渡す(`MainWindow`が最初の空き列に挿入、なければ新規列を追加)。 |

いずれの操作も、Ketcherが未初期化(`KetcherNotBundledError`)・構造式が空・SMILES解析失敗・3D埋め込み失敗などのエラーは、パネル内の固定サイズエラーラベル(2D関連)または3Dタブ内のステータス表示(3D関連)に表示される。

### 4.7 構造式画像のレンダリング入口とプレビュー保存

**`core/structure.py::render_structure_image(smiles, size)`** — アプリ全体で使われる構造式サムネイル/プレビュー画像のオンザフライ生成入口。`lineart_render.build_scene(smiles, mode="auto")` → `render_svg()` → `rasterize_svg()`(`QSvgRenderer`+`QPainter`でSVGを指定サイズの`QPixmap`にラスタライズ)という経路を通る。

- `reagent_table.py`(テーブル列ヘッダーのサムネイル、90×70px)
- `reagent_editor_dialog.py`(登録プレビューカードの構造式画像、168×128px、保存前でSMILESのみの段階)

**`LibraryEntry.preview_svg`(DB保存、7章参照)** — ライブラリ登録済みの化合物は、毎回SVGを生成し直すのではなく`preview_svg`列に焼いたSVGを`rasterize_svg()`で直接ラスタライズする(`library_dialog.py`のカードグリッドが該当。カードを多数同時に描く際の負荷軽減が目的)。`preview_svg`が`None`(未保存・旧データ)の場合は`render_structure_image`にフォールバックする。

- **保存時**: `ReagentEditorDialog._on_save()`が`structure.generate_preview_svg(smiles)`(既定`render_mode="auto"`)で焼いたSVGを`LibraryEntry.preview_svg`にセットして保存する。
- **「プレビューを更新」ボタン**(ライブラリカード): 構造式やモードを後から直したときに、保存済み`preview_svg`を明示的に焼き直して`library_repo.update()`で永続化できる。

### 4.8 3D関連実装の変遷(参考)

3Dプレビュー機能は本セッション中に複数回作り直されている。将来同じ問題を再発させないための記録:

1. **PySide6 `QPainter`による自作疑似3Dレンダラー(初代)** — フレームごとにRDKit側で再計算しており低速だった。
2. **ChemDraw風SVGを毎フレーム再構築する自前JSレンダラー(`QWebEngineView` + `setHtml()`)** — 実機で「ウィンドウは開くが完全に白紙のまま」という、開発機では再現できない環境依存の描画不具合が報告され、`baseUrl`付与・`AA_ShareOpenGLContexts`・GPUコンポジット無効化・`load()`方式への変更など複数の対策を講じても解決しなかった。
3. **3Dmol.js(WebGLベースの分子ビューアライブラリ)** — 実績があり確実に動作するはずだったが、上記2と同じ症状が再発。
4. **現行: QPainter直描き(4.3節)** — `QWebEngineView`を一切使わない設計に変更し、根本原因(WebEngine関連の環境依存描画不具合)を回避した。副次効果として、4.9節のWebEngine関連テストクラッシュの発生源も1つ減っている。

この経緯から、**3D関連の描画不具合を疑う場合は、まずWebEngine依存を疑う**のが定石になっている。

---

## 5. データモデル

### `ReagentColumn`(`ui/reagent_table.py`) — 計算テーブルの1列

```python
name: str = ""
formula: str | None = None
smiles: str | None = None
source: str = "manual"           # "library" | "pubchem" | "formula_parser" | "smiles" | "manual"
library_id: int | None = None
fw: float | None = None          # 分子量。4桁精度で丸めて保持
density: float | None = None
molarity: float | None = None
weight_value: float | None = None
weight_unit: str = "mg"
volume_ml: float | None = None
target_eq: float | None = None
weight_is_actual: bool = False   # weightが実測値かどうか(実測/計画モードの分岐に使用)
```

### `CompoundInfo`(`core/compound_source.py`) — 化合物解決の統一結果

```python
name: str
formula: str | None
molecular_weight: float
density: float | None
smiles: str | None
source: Literal["library", "pubchem", "formula_parser", "smiles"]
library_id: int | None = None
```

### `LibraryEntry`(`db/library_repo.py`) — ライブラリ1件

```python
id: int | None
name: str
molecular_weight: float
source: str
cas_number: str | None = None
formula: str | None = None
density: float | None = None
smiles: str | None = None
use_count: int = 0
created_at: str = ""
updated_at: str = ""
preview_svg: str | None = None   # 保存時に焼いたSVG(4.7節)。未保存/旧データはNone
render_mode: str = "auto"        # "auto" | "flat" | "solid"
```

### `Template`(`db/template_repo.py`) — 保存済みテンプレート

```python
id: int | None
name: str
payload: dict   # {"reagents": [{"name", "library_id", "role": "base"|"additive", "eq"}, ...]}
created_at: str = ""
updated_at: str = ""
```

---

## 6. 計算ロジック(`core/calc.py`)

旧Excelマクロのセル式を1:1移植した、Qt非依存の純粋関数群。

- **秤量計画(base → target)**: `calc_base_mmol` → `calc_target_mmol` → `calc_required_weight` / `calc_required_volume`
- **実績記録(measured → actual eq)**: `calc_actual_mmol`(重量優先、次に密度×体積、次にモル濃度×体積の優先順位) → `calc_actual_eq`

`reagent_table.py`の`recompute_all`/`_recompute_column`がこれらを呼び出し、各列の`weight_value`/`volume_ml`を副作用として補完しながら`ComputedResult(mmol, eq, is_actual)`を返す(4章の計算モード優先順位を参照)。

---

## 7. データベース(`db/schema.py`)

SQLite、`PRAGMA user_version`によるバージョン管理マイグレーション。現在version 2:

- **version 1**: `library`テーブル: `id, name, cas_number, formula, molecular_weight NOT NULL, density, smiles, source NOT NULL, use_count DEFAULT 0, created_at, updated_at` / `templates`テーブル: `id, name, payload TEXT NOT NULL, created_at, updated_at`
- **version 2**: `library`に`preview_svg TEXT`(4.7節、保存済みプレビューSVG)と`render_mode TEXT NOT NULL DEFAULT 'auto'`を追加。既存レコードは`preview_svg IS NULL`のまま`render_structure_image()`のオンザフライ生成にフォールバックするため、マイグレーション時の一括再生成は不要。

保存先は`db/paths.py`がOSごとに解決(Windows: `%APPDATA%/MolWeigh/molweigh.db`、macOS: `~/Library/Application Support/MolWeigh/`、その他: `~/.local/share/MolWeigh/`)。

---

## 8. 外部連携・セットアップ

| 対象 | 用途 | 取得方法 | 配置先 | 補足 |
|---|---|---|---|---|
| Ketcher | 2D構造式エディタ | `python scripts/build_ketcher.py`(要Node.js) | `molweigh/ui/vendor/ketcher/`(gitignore) | 未配置でも他機能は動作、該当ボタンが警告を出すのみ |
| PubChem PUG REST/PUG-View | 化合物名/CAS検索、分子量・化学式・SMILES・比重取得 | 実行時にHTTPS通信(`core/pubchem_client.py`) | — | 比重取得は失敗しても例外を出さずNoneを返す(欠損が多いフィールドのため) |

3Dプレビュー(`lineart_render.py` + `molecule_3d_view.py`)はQt/numpy/RDKitのみに依存する自前実装のため、外部ライブラリの取得・追加セットアップは不要。

---

## 9. テスト方針

- `tests/`配下にファイル単位でpytestテストを配置(294件)。
- Qt依存のテストはセッションスコープの`qapp`フィクスチャ(オフスクリーンプラットフォーム)を使用。
- **既知の環境依存事項**: `QWebEngineView`を伴うテスト(Ketcher・PubChem埋め込みブラウザ関連)を大量に同一プロセスで実行すると、蓄積したリソースが原因でPySide6がまれにネイティブクラッシュすることがある(exit code 127でサマリー行が出ない、または`Windows fatal exception`のスタックトレースが出て`threading.Thread.start()`自体が失敗する、など症状は複数パターンある)。これはテスト対象コードの不具合ではなく環境依存の既知の問題。`StructureInputPanel`/`ReagentEditorDialog`が3Dタブ(`Structure3DTab`)を持つようになったことで1テストあたりのオブジェクト数が増え、`test_structure_input_panel.py`・`test_reagent_editor_dialog.py`はファイル単位どころかクラス単位でもまれに閾値を超えてクラッシュすることがある(逆に3Dタブ自体は`QWebEngineView`を使わないので、単体では負荷を増やさない)。疑わしい場合はクラス単位、それでも再現するならテスト単位までチャンクを細かくして「個々のテストロジックは全て正しいか」を切り分けること(2026-08時点で両ファイルとも個別実行では全件パス確認済み)。exit codeだけでなく「N passed」のサマリー行の有無で成否を判定すること。

---

## 10. 既知の制約・未実装事項

- ライブラリの部分一致検索で複数件ヒットした場合の候補選択UIは未実装(現状は完全一致優先、なければ最初の1件を自動採用)。
- `TemplateEditDialog`の試薬追加は、ライブラリの先頭エントリ(使用回数順)を仮追加するだけの簡易実装で、専用の選択UIはない。
- `StructureEditorDialog`(モーダル版のKetcherダイアログ)は実装済みだが現在どこからも呼び出されていない未使用クラス。
- `LibraryEntry.render_mode`(`auto`/`flat`/`solid`)を手動で切り替えるUIは未実装。現状は常に`auto`判定に従う(4.2節)。ライブラリカードの「プレビューを更新」は既存の`render_mode`のまま焼き直すのみ。
- ChemDraw CDXML(.cdxml/.cdx)との相互変換は未実装。pip版RDKit(2026.03.5で確認)には`Chem.HasChemDrawCDXSupport()`/`MolsFromCDXML`/`MolToCDXMLBlock`が同梱されており追加ライセンス不要で対応可能だが、本セッションでは着手していない。
- macOS(Apple Silicon)向けパッケージングは実機確保後に着手予定(現状Windows優先)。
