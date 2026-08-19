"""MolWeighの起動エントリポイント。"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .db import schema
from .db.paths import get_db_path
from .ui import theme
from .ui.main_window import MainWindow


def main() -> int:
    # QtWebEngineウィジェット(Ketcher・PubChemパネル)を使う場合、QApplication
    # 生成前にこの属性を立てることが公式に必須とされている(環境によっては
    # OpenGLコンテキスト共有の設定漏れがWebEngineの描画不具合の原因になりうる
    # ため)。3Dプレビューは`ui/molecule_3d_view.py`(QPainter直描き)に
    # 置き換わり、WebEngineには依存しなくなった。
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
