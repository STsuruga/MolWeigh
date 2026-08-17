# MolWeigh 仕様書

既存Excelマクロ「当量計算表」を再実装した、試薬の当量(eq)計算・個人試薬ライブラリ・
化合物検索・分子構造描画を備えたPySide6製デスクトップアプリ。

- リポジトリ: `D:\ユーザー\shuta\ドキュメント\MolWeigh`
- 起動: `python main.py`
- テスト: `tests/` 配下に232件(pytest)
- 主要スタック: PySide6(GUI) / RDKit(化学計算・構造処理) / SQLite(DB) / Ketcher(2D構造式エディタ、Web埋め込み) / 自前実装の線画3Dビューア(ChemDraw風、Web埋め込み)

---

## 1. 全体アーキテクチャ

3層構成。UI層は他の層に依存するが、逆方向の依存はない(coreはQt非依存の純粋ロジックを目指す)。

```
molweigh/
├── core/     … Qt非依存の計算・データ処理ロジック
│   ├── calc.py             当量(eq)計算の中核(旧Excelマクロのセル式を1:1移植)
│   ├── formula_parser.py   化学式文字列 → 分子量(RDKit不使用、正規表現+原子量表)
│   ├── structure.py        SMILES → RDKit Mol、2D構造式画像生成(★詳細は第4章)
│   ├── structure_3d.py     RDKitによる3D配座生成(★詳細は第4章)
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
│   ├── structure_input_panel.py   構造入力パネル(★詳細は第4章)
│   ├── structure_editor.py        Ketcher埋め込み本体(★詳細は第4章)
│   ├── molecule_lineart_viewer.py 線画3Dビューア(ChemDraw風、★詳細は第4章)
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

分子構造まわりは大きく分けて **(A) 2D構造式の編集(Ketcher)**、**(B) 構造式画像の静的レンダリング**、**(C) 橋かけ構造(bridgehead)の特別対応**、**(D) 3Dプレビュー(自前実装の線画ビューア)** の4つの仕組みで構成される。

### 4.1 (A) Ketcherによる2D構造式編集(`ui/structure_editor.py`)

[Ketcher](https://github.com/epam/ketcher)(EPAM製オープンソース構造式エディタ、React製Webアプリ)を`QWebEngineView`に埋め込んで使用する。

- **オフライン配信の仕組み**: Ketcherのビルド成果物(`molweigh/ui/vendor/ketcher/`、`scripts/build_ketcher.py`で取得・`.gitignore`済み)を、`http.server.ThreadingHTTPServer`でOSが割り当てた空きポート(`127.0.0.1:0`)からデーモンスレッドで配信する。`file://`直接オープンではCRAビルドの絶対パスアセット参照が壊れるため、この方式を採用している。
- **`KetcherView(QWidget)`**が中核の再利用可能部品。以下の2箇所から使われる:
  - `StructureInputPanel`(メイン画面常設、常時ロード)
  - `ReagentEditorDialog`(化合物登録ダイアログ内、独立インスタンス)
  - (`StructureEditorDialog`というモーダルダイアログ版のクラスも存在するが、現在どこからも呼び出されていない=未使用のレガシークラス)
- **SMILES取得の非同期パターン**: `QWebEngineView.page().runJavaScript()`のコールバックはJSのPromiseを直接awaitできない制約があるため、`window.ketcher.getSmiles()`の結果を`window.__molweighResult`というグローバル変数に書き込ませ、Python側は150ms間隔・最大40回(=6秒)のポーリングで読み取る(`get_smiles(callback)`)。
- **`set_smiles(text)`**は`window.ketcher.setMolecule(text)`を呼ぶ。名前に反して、渡す文字列はSMILESに限らず**MOLブロック文字列でもよい**(Ketcher側が自動判定する)。この性質が後述4.5節の「橋かけ構造を整列」機能の実現手段になっている。
- `shutdown()`でローカルHTTPサーバーを停止する(ウィンドウを閉じる際に必ず呼び出す必要がある)。

### 4.2 (B) 構造式画像の静的レンダリング(`core/structure.py::render_structure_image`)

アプリ全体で使われる構造式サムネイル/プレビュー画像の**唯一の共通入口**。以下すべてがこの関数を呼ぶ:

- `reagent_table.py`(テーブル列ヘッダーのサムネイル、90×70px)
- `library_dialog.py`(ライブラリカードの構造式画像、110×85px)
- `reagent_editor_dialog.py`(登録プレビューカードの構造式画像、168×128px)

処理: SMILESからRDKitの`Mol`を構築 → (橋かけ構造なら4.3節の特別処理) → `Draw.MolToImage()`でPIL画像生成 → `QImage`(RGBA8888)経由で`QPixmap`に変換。

### 4.3 (C) 橋かけ構造(bridgehead)の特別対応 ★最重要

**課題**: トリプチセンやアダマンタンのような橋かけ環(bridgehead原子を持つ籠状構造)は、RDKitの標準的な2Dレイアウトアルゴリズムでは無理に平面化されて環同士が重なり、RDKitが重なり箇所に警告マーク(赤い四角や"C"ラベル)を付けてしまう。

**対応方針**: 該当構造だけを検出し、RDKitで生成した3D配座のXY座標を**そのまま2Dレイアウトとして流用**する。Z軸(奥行き)を潰して2D平面に投影することで、環が交差する様子がそのまま「奥行きを表す交差線」として描画され、無理な平面化による破綻を避けられる。通常の(橋かけでない)分子は一切変更しない。

#### 処理フロー

```
render_structure_image(smiles)
  │
  ├─ RDKitでMol構築
  ├─ rdMolDescriptors.CalcNumBridgeheadAtoms(mol) > 0 ?
  │     │ No → 通常のRDKit標準2Dレイアウトで描画(変更なし)
  │     │ Yes ↓
  │     └─ _project_3d_to_2d(smiles) を試みる(失敗時はValueErrorを捕捉し通常描画にフォールバック)
  │
  └─ Draw.MolToImage() → QPixmap
```

**`_project_3d_to_2d(smiles) -> Chem.Mol`**(`core/structure.py`):
1. `structure_3d.embed_and_optimize(smiles)` で3D配座を生成(4.4節参照。明示的な水素付き)
2. `orient_canonically(mol_3d)` で見やすい向きに回転(下記アルゴリズム)
3. `Chem.RemoveHs()` で水素を除去(通常の骨格式表示に合わせる)
4. 3D座標のX・Yだけをコピーし、Z=0.0に固定した新しい`Conformer`を作成して`Set3D(False)` — 実質的に3D構造を正射影で2D化したもの
5. この2D座標を持つ`Mol`を返す

**`orient_canonically(mol)` — 向き選択アルゴリズム**(橋かけ構造の2D投影だけでなく、4.6節の線画3Dビューアの初期表示角度にも流用する共有ユーティリティ):

分子を回転させて「原子同士が2D投影で最も重なりにくい向き」を選ぶ。

1. 全原子の3D座標を取得し、重心を原点に平行移動
2. 水素以外(重原子)の座標だけで共分散行列を計算し、主成分分析(PCA)で3本の主軸(固有ベクトル)を得る
   - **水素を除外する理由**: 水素は結合長が短く、どの向きでも隣接原子の近くに留まるため、「重なりにくさ」の評価に含めると水素間の距離だけで結果が決まってしまう
3. **3本の主軸それぞれを「奥行き(Z)」に割り当てる3通りの回転**を全て試す(残り2軸が画面内のX/Y平面になる)
   - 「分散が最小の軸を奥行きにすれば綺麗に見える」という単純な仮定は必ずしも成立しないため、3パターン全てを候補として評価する(実装過程でトリプチセンにおいて反例を確認済み)
   - 各候補で回転行列の行列式が負(鏡映)になる場合は最後の列を反転し、正しい回転(鏡映でない)を保つ
4. 各候補について、回転後の**重原子のみ**を2D投影(X,Y)し、全原子ペアの最小距離(`_min_pairwise_distance_2d`)をスコアとして計算
5. スコア(最小距離)が最大、つまり**原子同士が最も離れて見える**候補を採用
6. 採用した回転を(水素を含む)全原子に適用し、`Mol`の座標を書き換える

この設計により、トリプチセンのようなプロペラ状の構造は「翼が綺麗に開いて見える」角度が自動選択され、アダマンタンのような籠状構造も重なりの少ない見やすい向きで描画される。

### 4.4 3D配座生成(`core/structure_3d.py`)

ChemDrawの「3D Clean Up」に相当する処理。**Ketcher自身の2D編集データとは完全に独立した別経路**であり、ここで生成した3D構造を2D編集データへ書き戻すことは一切ない(4.5節・4.6節の理由を参照)。

**`embed_and_optimize(smiles) -> Chem.Mol`**:
1. `Chem.MolFromSmiles` → `Chem.AddHs`(明示的水素付加、現実的な3D形状のために必要)
2. `AllChem.ETKDGv3()`パラメータ(固定シード`0xC0FFEE`、再現性のため)で`EmbedMolecule`。失敗時は`useRandomCoords=True`で1回リトライ。それでも失敗すれば`ValueError`
3. `AllChem.MMFFOptimizeMolecule`(MMFF94力場)で構造最適化。収束しない/MMFFパラメータが存在しない場合は`AllChem.UFFOptimizeMolecule`(より汎用的なUFF力場)にフォールバック

**`structure.generate_lineart_data(smiles) -> LineArtMolecule`**(`core/structure.py`): 上記の3D配座を`orient_canonically`で見やすい向きに回転し、`Chem.RemoveHs()`で水素を除去したうえで、原子座標・結合リストを`LineArtAtom`/`LineArtBond`のデータクラスへ変換する。4.6節の3Dプレビュー(線画ビューア)への入力となる。回転・投影・隠線処理そのものはJS側で行うため、ここではRDKit側の下ごしらえ(3D配座生成+初期向き決定+水素除去)のみを行う。

### 4.5 なぜKetcher自身の3D機能を使わないか

Ketcherには標準で「3D Viewer」ボタン(Miewエンジンによる表示)があるが、これは**単に回転して見るだけの機能でエネルギー最小化は行わない**。さらに、回転後に画面内の「Apply」ボタンで2D構造へ書き戻すと、Ketcher自身の警告文言(「Stereocenters can be changed after the strong 3D rotation」)の通り**立体中心が壊れることがある**ことを実機検証で確認した。これがユーザー報告のあった「3次元構造を反映すると赤いエラーマークが出る」現象の原因だった。

この経緯から、3D関連機能はすべてKetcherの2D編集データと完全に切り離し、**読み取り専用のプレビュー用途に限定**する設計とした(4.4節・4.6節)。

### 4.6 (D) 3Dプレビュー — ChemDraw風線画ビューア(`ui/molecule_lineart_viewer.py`)

「3Dプレビュー」ボタンで開く、マウス操作で回転・ズームできる読み取り専用の3D構造ビューア。

**採用経緯**: 当初はPySide6の`QPainter`で自作した疑似3Dレンダラー(手動の回転行列適用+正射影+奥行きソート)、次に[3Dmol.js](https://3dmol.org/)(WebGLベースの分子ビューアライブラリ)を採用したが、ChemDrawの「Clean Up 3D Structure」に見た目を寄せたいという要望を踏まえ、**自前実装のベクター線画レンダラーに置き換えた**。ChemDrawの3D表示は立体的な3Dモデルではなく、3D座標を2Dへ正射影したうえで結合線同士の交差箇所に隠線ギャップを入れる「線画」であり、WebGLの球体・厚みのあるスティック表現とは根本的に見た目が異なるため、既存ライブラリの流用ではなく自作が必要だった。

- **役割分担**: 化学計算(3D配座生成)は引き続きPython/RDKit側(`structure_3d.embed_and_optimize` + `structure.generate_lineart_data`)が担う。回転(クォータニオン、ジンバルロック回避)・正射影・線分交差判定・隠線ギャップ計算・SVG描画・マウス操作は**すべてJavaScript側で完結**させ、ドラッグ中にPython⇔JS間の往復は一切発生させない(以前のQPainter自作レンダラーで、フレームごとにPython側で再計算するコストが大きすぎた反省を踏まえた設計)。
- **隠線ギャップ処理**: 全結合ペアを総当たりで線分交差判定し(結合数は数十〜百程度なのでO(n²)で十分)、交差する2本の結合のうち奥(depthが小さい)側の結合を、交差点付近の固定ピクセル幅(既定3px)だけ分割してギャップを開ける。色や太さでの奥行き表現はChemDraw同様に行わない。
- **オフライン配信**: 外部ライブラリではなく自前実装のJSのため、Ketcher/3Dmol.js時代のようなローカルHTTPサーバー配信は不要。生成したHTML(原子・結合データのJSONとJSを直接埋め込み)を`QWebEngineView.setHtml()`にそのまま渡すだけで、外部CDN・追加セットアップなしに完全オフラインで動作する。
- **構成**: `MoleculeLineArtWebView(QWidget)`(ビューア本体、`LineArtMolecule`をJSON化してHTMLへ埋め込み) + `MoleculeLineArtWebDialog(QDialog)`(閉じるボタン付きのダイアログラッパー、600×600、ヒントラベル表示)。ローカルサーバーもファイル同梱もないため、`KetcherNotBundledError`のような「未配置」エラーは存在しない。

### 4.7 構造入力パネルの4つのボタン(`ui/structure_input_panel.py`)

メイン画面に常設される`StructureInputPanel`は、`KetcherView`(左、常時表示)と情報表示+4ボタンのサイドバー(右、幅150px固定)で構成される。`ReagentEditorDialog`にもほぼ同じ4ボタン(「構造式を反映」という名称のみ異なる)が実装されている。

| ボタン | 処理 | 説明 |
|---|---|---|
| **分子量を計算** | `get_smiles` → `compound_source.resolve_from_smiles` | 化学式・分子量ラベルを更新するのみ。計算テーブルには反映しない。「試薬に追加」を押す前でも確認できるようにするための機能。 |
| **3Dプレビュー** | `get_smiles` → `structure.generate_lineart_data` → `MoleculeLineArtWebDialog` | RDKitでエネルギー最小化した3D構造を、ChemDraw風の線画(隠線ギャップ表示)として別ウィンドウで表示。2D構造には一切反映されない(読み取り専用)。 |
| **橋かけ構造を整列** | `get_smiles` → `structure.realign_bridged_structure_molblock` → (橋かけなら)`ketcher.set_smiles(molblock)` | 現在Ketcherに描かれている構造が橋かけ構造(bridgehead原子あり)であれば、4.3節のアルゴリズムで見やすい向きに再配置したMOLブロックを**Ketcherのキャンバスへ書き戻す**。橋かけ構造でない場合は「整列は不要です」と案内するのみで何もしない。手描きで乱雑になった橋かけ構造をワンクリックで整理できる、Ketcher自身の自動レイアウトを外部から差し替えられないという制約への対処。 |
| **試薬に追加** | `get_smiles` → `resolve_from_smiles` → `added_to_table.emit(info)` | 化学式・分子量ラベルを更新し、`CompoundInfo`を計算テーブルへ渡す(`MainWindow`が最初の空き列に挿入、なければ新規列を追加)。 |

いずれのボタンも、Ketcherが未初期化(`KetcherNotBundledError`)・構造式が空・SMILES解析失敗・3D埋め込み失敗などのエラーは、パネル内の固定サイズエラーラベルに表示される(表示/非表示の切り替えではなくテキストの有無だけを変えることで、エラー表示の有無によってボタン位置がずれないようにしている)。

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

SQLite、`PRAGMA user_version`によるバージョン管理マイグレーション。現在version 1のみ:

- `library`テーブル: `id, name, cas_number, formula, molecular_weight NOT NULL, density, smiles, source NOT NULL, use_count DEFAULT 0, created_at, updated_at`
- `templates`テーブル: `id, name, payload TEXT NOT NULL, created_at, updated_at`

保存先は`db/paths.py`がOSごとに解決(Windows: `%APPDATA%/MolWeigh/molweigh.db`、macOS: `~/Library/Application Support/MolWeigh/`、その他: `~/.local/share/MolWeigh/`)。

---

## 8. 外部連携・セットアップ

| 対象 | 用途 | 取得方法 | 配置先 | 補足 |
|---|---|---|---|---|
| Ketcher | 2D構造式エディタ | `python scripts/build_ketcher.py`(要Node.js) | `molweigh/ui/vendor/ketcher/`(gitignore) | 未配置でも他機能は動作、該当ボタンが警告を出すのみ |
| PubChem PUG REST/PUG-View | 化合物名/CAS検索、分子量・化学式・SMILES・比重取得 | 実行時にHTTPS通信(`core/pubchem_client.py`) | — | 比重取得は失敗しても例外を出さずNoneを返す(欠損が多いフィールドのため) |

線画3Dビューア(`ui/molecule_lineart_viewer.py`)は自前実装のJSを埋め込むだけで、外部取得・追加セットアップは不要。

---

## 9. テスト方針

- `tests/`配下にファイル単位でpytestテストを配置(232件)。
- Qt依存のテストはセッションスコープの`qapp`フィクスチャ(オフスクリーンプラットフォーム)を使用。
- **既知の環境依存事項**: `QWebEngineView`を伴うテスト(Ketcher・線画3Dビューア関連)を大量に同一プロセスで実行すると、蓄積したリソースが原因でPySide6がまれにネイティブクラッシュ(access violation)することがある。これはテスト対象コードの不具合ではなく環境依存の既知の問題。フルスイートを1プロセスで回さず、ファイル単位のチャンクに分けて実行することで回避する。

---

## 10. 既知の制約・未実装事項

- ライブラリの部分一致検索で複数件ヒットした場合の候補選択UIは未実装(現状は完全一致優先、なければ最初の1件を自動採用)。
- `TemplateEditDialog`の試薬追加は、ライブラリの先頭エントリ(使用回数順)を仮追加するだけの簡易実装で、専用の選択UIはない。
- `StructureEditorDialog`(モーダル版のKetcherダイアログ)は実装済みだが現在どこからも呼び出されていない未使用クラス。
- macOS(Apple Silicon)向けパッケージングは実機確保後に着手予定(現状Windows優先)。
