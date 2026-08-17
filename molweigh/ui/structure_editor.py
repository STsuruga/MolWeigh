"""Ketcher(埋め込みWeb構造式エディタ)によるマウス構造式入力。

`molweigh/ui/vendor/ketcher/` にKetcherの静的ビルド(`index.html` 一式)を
配置しておく必要がある(`scripts/build_ketcher.py` 参照。リポジトリには
含めず、セットアップ時にビルドする)。`file://` で直接開くとCRAビルドの
絶対パスアセット参照やモジュール読み込みがブロックされるため、
`127.0.0.1` のローカルHTTPサーバー経由で配信する。
"""

from __future__ import annotations

import http.server
import socket
import threading
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from . import theme

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor" / "ketcher"

_POLL_INTERVAL_MS = 150
_POLL_TIMEOUT_TICKS = 40  # 150ms * 40 = 6秒でタイムアウト

_GET_SMILES_JS = """
window.__molweighResult = undefined;
window.ketcher.getSmiles()
    .then(function (smiles) { window.__molweighResult = smiles; })
    .catch(function () { window.__molweighResult = null; });
"""
_POLL_JS = (
    "typeof window.__molweighResult !== 'undefined' "
    "? window.__molweighResult : '__molweigh_pending__'"
)


class KetcherNotBundledError(RuntimeError):
    """Ketcherの静的ビルドが同梱されていない場合に送出する。"""


class _QuietRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass


class StructureEditorDialog(QDialog):
    """Ketcherを埋め込んだ構造式エディタ。「確定」でSMILESを`self.smiles`に格納する。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        if not (_VENDOR_DIR / "index.html").exists():
            raise KetcherNotBundledError(
                f"Ketcherの静的ビルドが見つかりません: {_VENDOR_DIR}\n"
                "scripts/build_ketcher.py を実行してビルドしてください。"
            )

        self.setWindowTitle("構造式を描く")
        self.resize(960, 720)
        self.smiles: str | None = None

        self._server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            lambda *args: _QuietRequestHandler(*args, directory=str(_VENDOR_DIR)),
        )
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._server_thread.start()
        port = self._server.server_address[1]

        self._view = QWebEngineView(self)
        self._view.load(QUrl(f"http://127.0.0.1:{port}/index.html"))

        self._error_label = QLabel("")
        self._error_label.setStyleSheet(f"color: {theme.DANGER_TEXT};")
        self._error_label.hide()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._view)
        layout.addWidget(self._error_label)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        # QWebEnginePage.runJavaScript()はPromiseの解決を待たず、Promiseオブジェクト
        # 自体を返そうとしても空値になる。JS側でグローバル変数に結果を書き込ませ、
        # Python側は同期式のポーリングでその値を取りに行く。
        self._error_label.hide()
        self._view.page().runJavaScript(_GET_SMILES_JS)
        self._poll_ticks = 0
        QTimer.singleShot(_POLL_INTERVAL_MS, self._poll_for_smiles)

    def _poll_for_smiles(self) -> None:
        self._poll_ticks += 1
        if self._poll_ticks > _POLL_TIMEOUT_TICKS:
            self._show_error("構造式の取得がタイムアウトしました。")
            return
        self._view.page().runJavaScript(_POLL_JS, self._on_poll_result)

    def _on_poll_result(self, value: object) -> None:
        if value == "__molweigh_pending__":
            QTimer.singleShot(_POLL_INTERVAL_MS, self._poll_for_smiles)
            return
        if isinstance(value, str) and value.strip():
            self.smiles = value.strip()
            self.accept()
        else:
            self._show_error("構造式が空です。原子を配置してください。")

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.show()

    def done(self, result: int) -> None:
        self._server.shutdown()
        super().done(result)
