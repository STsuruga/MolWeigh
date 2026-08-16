"""OS別のアプリデータ保存先パスを解決する。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "MolWeigh"
DB_FILENAME = "molweigh.db"


def get_app_data_dir() -> Path:
    """OSごとのアプリデータディレクトリを返す(存在しなければ作成する)。"""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ["APPDATA"])
    else:
        base = Path.home() / ".local" / "share"
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_db_path() -> Path:
    """SQLiteデータベースファイルのパスを返す。"""
    return get_app_data_dir() / DB_FILENAME
