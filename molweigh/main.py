"""MolWeighの起動エントリポイント。"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .db import schema
from .db.paths import get_db_path
from .ui import theme
from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.APP_STYLESHEET)
    conn = schema.get_connection(get_db_path())
    window = MainWindow(conn)
    window.resize(960, 560)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
