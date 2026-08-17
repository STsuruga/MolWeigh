"""3Dmol.js(WebGL)による3D構造ビューア。

自作のQPainter疑似3D描画や、SVGを毎フレーム再構築する自前線画レンダラー
(いずれも過去に採用したが撤回)ではなく、実際のWebGL z-bufferによる
正しい隠線・隠面処理、滑らかなマウス操作の回転・ズーム・パンが標準で
使える、実績のあるライブラリに寄せている。3Dmol.jsは
`molweigh/ui/vendor/3dmol/`にローカル同梱し(`scripts/fetch_3dmol.py`で
取得)、Ketcherと同じ「一時ディレクトリにHTML一式を書き出し、ローカル
HTTPサーバーを起動して`QWebEngineView.load()`で読み込む」方式で配信する
(`setHtml()`は、環境によってはウィンドウが完全に白紙のまま描画されない
という実機報告があり、確実に動作するKetcherの読み込み方式に統一した)。

読み取り専用のプレビューが既定だが、「この向きを2Dに反映」ボタンで、
3Dmol.jsの`getView()`から現在のカメラ回転(クォータニオン)を取得し、
それを`core/structure.py::generate_3d_view`が用意した基準座標(3Dmol.jsに
渡したMOLブロックと同じ正準向き・原点)に適用して2Dレイアウトを計算する。
"""

from __future__ import annotations

import http.server
import json
import shutil
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.structure import Molecule3DData, build_molblock_from_2d_layout
from . import theme

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor" / "3dmol"
_VENDOR_FILENAME = "3Dmol-min.js"


class Molecule3DNotBundledError(RuntimeError):
    """3Dmol.jsの静的ファイルが同梱されていない場合に送出する。"""


class _QuietRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass


_HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="3Dmol-min.js"></script>
<style>
  html, body {{ margin: 0; padding: 0; height: 100%; background: #ffffff; }}
  #viewer {{ width: 100%; height: 100%; position: relative; }}
</style>
</head>
<body>
<div id="viewer"></div>
<script>
(function () {{
  "use strict";
  var viewer = $3Dmol.createViewer(document.getElementById("viewer"), {{backgroundColor: "white"}});
  var molblock = {molblock_json};
  viewer.addModel(molblock, "mol");
  viewer.setStyle({{}}, {{stick: {{radius: 0.09, colorscheme: "blackCarbon"}}}});
  viewer.zoomTo();
  viewer.render();

  // 「この向きを2Dに反映」用: generate_3d_view()が用意した、molblockと同じ
  // 座標系(正準向き・原点)の重原子のみの基準座標。
  var refAtoms = {atoms_json};

  function quatToMatrix(qx, qy, qz, qw) {{
    // 3Dmol.jsのgetView()は[x, y, z, w]順でクォータニオンを返す。
    return [
      1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw),
      2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw),
      2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy),
    ];
  }}

  window.__MOLWEIGH_GET_LAYOUT__ = function () {{
    var v = viewer.getView();
    var m = quatToMatrix(v[4], v[5], v[6], v[7]);
    return refAtoms.map(function (a) {{
      return [m[0] * a.x + m[1] * a.y + m[2] * a.z, m[3] * a.x + m[4] * a.y + m[5] * a.z];
    }});
  }};
}})();
</script>
</body>
</html>
"""


class Molecule3DWebView(QWidget):
    """3Dmol.jsを埋め込んだ3D構造ビューア本体。読み取り専用(2D構造には反映しない)。"""

    def __init__(self, molblock: str, view_data: Molecule3DData, parent: QWidget | None = None):
        super().__init__(parent)
        vendor_file = _VENDOR_DIR / _VENDOR_FILENAME
        if not vendor_file.exists():
            raise Molecule3DNotBundledError(
                f"3Dmol.jsの静的ファイルが見つかりません: {_VENDOR_DIR}\n"
                "scripts/fetch_3dmol.py を実行して取得してください。"
            )

        self._tmp_dir = tempfile.TemporaryDirectory(prefix="molweigh_3dmol_")
        tmp_path = Path(self._tmp_dir.name)
        shutil.copyfile(vendor_file, tmp_path / _VENDOR_FILENAME)

        atoms_json = json.dumps([{"x": a.x, "y": a.y, "z": a.z} for a in view_data.atoms])
        html = _HTML_TEMPLATE.format(molblock_json=json.dumps(molblock), atoms_json=atoms_json)
        (tmp_path / "index.html").write_text(html, encoding="utf-8")

        self._server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            lambda *args: _QuietRequestHandler(*args, directory=str(tmp_path)),
        )
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._server_thread.start()
        port = self._server.server_address[1]

        self._view = QWebEngineView(self)
        self._view.load(QUrl(f"http://127.0.0.1:{port}/index.html"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

    def shutdown(self) -> None:
        self._server.shutdown()
        self._tmp_dir.cleanup()


class Molecule3DWebDialog(QDialog):
    """`Molecule3DWebView` を包むプレビューダイアログ。

    既定では読み取り専用だが、「この向きを2Dに反映」ボタンで、ユーザーが
    ドラッグで回転させた今の見た目をそのまま2DレイアウトのMOLブロックとして
    書き出せる(2D構造式の再構築のみ行い、`smiles`自体は変更しない)。
    呼び出し側は`exec()`後に`molblock_to_apply`が`None`でなければ、それを
    Ketcherの`set_smiles()`に渡して反映する。
    """

    def __init__(
        self, molblock: str, view_data: Molecule3DData, smiles: str, parent: QWidget | None = None
    ):
        super().__init__(parent)
        self.setWindowTitle("3Dプレビュー")
        self.resize(600, 600)

        self._smiles = smiles
        self.molblock_to_apply: str | None = None

        hint_label = QLabel(
            "ドラッグで回転、ホイールでズームできます。"
            "「この向きを2Dに反映」で今の見た目を2D構造式に書き戻せます。"
        )
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")

        self._view = Molecule3DWebView(molblock, view_data, self)

        self._reflect_button = QPushButton("この向きを2Dに反映")
        self._reflect_button.clicked.connect(self._on_reflect)

        close_button = QPushButton("閉じる")
        close_button.clicked.connect(self.reject)

        button_row = QHBoxLayout()
        button_row.addWidget(self._reflect_button)
        button_row.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(hint_label)
        layout.addWidget(self._view, 1)
        layout.addLayout(button_row)

    def _on_reflect(self) -> None:
        self._reflect_button.setEnabled(False)
        self._view._view.page().runJavaScript(
            "JSON.stringify(window.__MOLWEIGH_GET_LAYOUT__())", self._on_layout_received
        )

    def _on_layout_received(self, value: object) -> None:
        if not isinstance(value, str):
            self._reflect_button.setEnabled(True)
            return
        layout = [(pt[0], pt[1]) for pt in json.loads(value)]
        self.molblock_to_apply = build_molblock_from_2d_layout(self._smiles, layout)
        self.accept()

    def done(self, result: int) -> None:
        self._view.shutdown()
        super().done(result)
