"""3Dmol.js(3D構造ビューア用JSライブラリ)を取得し molweigh/ui/vendor/3dmol/ に配置する。

CDN(jsdelivr)から一度だけダウンロードしてローカルに保存する。アプリ実行時に
毎回ネット接続が必要にならないよう、Ketcherと同様にオフラインで使えるよう
ローカルへ同梱する。
実行例:
    python scripts/fetch_3dmol.py
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

VERSION = "2.5.5"
URL = f"https://cdn.jsdelivr.net/npm/3dmol@{VERSION}/build/3Dmol-min.js"

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = REPO_ROOT / "molweigh" / "ui" / "vendor" / "3dmol"
DEST = VENDOR_DIR / "3Dmol-min.js"


def main() -> None:
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    print(f"downloading {URL} ...")
    try:
        urllib.request.urlretrieve(URL, DEST)
    except OSError as exc:
        print(f"ダウンロードに失敗しました: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"saved: {DEST} ({DEST.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
