"""3Dmol.js(WebGL)による3D構造ビューア。

自作のQPainterによる疑似3D描画ではなく、実際のWebGL z-bufferによる
正しい隠線・隠面処理、滑らかなマウス操作の回転・ズーム・パンが標準で
使える。3Dmol.jsは `molweigh/ui/vendor/3dmol/` にローカル同梱し
(`scripts/fetch_3dmol.py` で取得)、Ketcherと同様にローカルHTTP
サーバー経由で配信することでオフラインでも動作する。
"""

from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget

from . import theme

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor" / "3dmol"


class Molecule3DNotBundledError(RuntimeError):
    """3Dmol.jsの静的ファイルが同梱されていない場合に送出する。"""

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
  var viewer = $3Dmol.createViewer(document.getElementById("viewer"), {{backgroundColor: "white"}});
  var molblock = {molblock_json};
  viewer.addModel(molblock, "mol");
  viewer.setStyle({{}}, {{stick: {{radius: 0.09, colorscheme: "blackCarbon"}}}});
  viewer.zoomTo();
  viewer.render();
</script>
</body>
</html>
"""


class _QuietRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass


class Molecule3DWebView(QWidget):
    """3Dmol.jsを埋め込んだ3D構造ビューア本体。読み取り専用(2D構造には反映しない)。"""

    def __init__(self, molblock: str, parent: QWidget | None = None):
        super().__init__(parent)
        if not (_VENDOR_DIR / "3Dmol-min.js").exists():
            raise Molecule3DNotBundledError(
                f"3Dmol.jsの静的ファイルが見つかりません: {_VENDOR_DIR}\n"
                "scripts/fetch_3dmol.py を実行して取得してください。"
            )

        self._server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            lambda *args: _QuietRequestHandler(*args, directory=str(_VENDOR_DIR)),
        )
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._server_thread.start()
        port = self._server.server_address[1]

        self._view = QWebEngineView(self)
        html = _HTML_TEMPLATE.format(molblock_json=json.dumps(molblock))
        self._view.setHtml(html, baseUrl=QUrl(f"http://127.0.0.1:{port}/"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

    def shutdown(self) -> None:
        self._server.shutdown()


class Molecule3DWebDialog(QDialog):
    """`Molecule3DWebView` を包む読み取り専用のプレビューダイアログ。"""

    def __init__(self, molblock: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("3Dプレビュー")
        self.resize(600, 600)

        hint_label = QLabel("ドラッグで回転、ホイールでズームできます(2D構造には反映されません)。")
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")

        self._view = Molecule3DWebView(molblock, self)

        close_button = QPushButton("閉じる")
        close_button.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(hint_label)
        layout.addWidget(self._view, 1)
        layout.addWidget(close_button)

    def done(self, result: int) -> None:
        self._view.shutdown()
        super().done(result)
