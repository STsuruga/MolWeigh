"""MolWeighの起動エントリポイント。"""

from __future__ import annotations

import os
import sys

# QtWebEngine(Chromium)のGPUコンポジット周りは、環境によって(特定のGPU
# ドライバ等)描画が完全に固まる/白紙のままになることがある既知の問題群。
# QWebEngineWidgetsをインポートする前(=Chromiumプロセスが起動する前)に
# 設定しておく必要があるため、他のインポートより先にここで行う。
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu-compositing")

# デバッグ用: 通常のブラウザから http://127.0.0.1:9223 を開くと、アプリ内の
# QWebEngineView(Ketcher・3Dプレビュー等)の中身をChrome DevTools相当の
# 画面で直接調査できる(コンソールエラー・DOM状態などを実機で確認するため)。
# 原因調査が終わったら削除してよい一時的な設定。
os.environ.setdefault("QTWEBENGINE_REMOTE_DEBUGGING", "9223")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .db import schema
from .db.paths import get_db_path
from .ui import theme
from .ui.main_window import MainWindow


def main() -> int:
    # QtWebEngineウィジェット(Ketcher・PubChemパネル・3Dプレビュー等)を使う場合、
    # QApplication生成前にこの属性を立てることが公式に必須とされている
    # (環境によってOpenGLコンテキスト共有の設定漏れがWebEngineの描画不具合の
    # 原因になりうるため)。
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.APP_STYLESHEET)
    conn = schema.get_connection(get_db_path())
    window = MainWindow(conn)
    window.resize(1500, 900)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
