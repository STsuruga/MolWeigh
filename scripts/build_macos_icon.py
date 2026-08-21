"""アプリアイコン(molweigh/resources/app_icon.ico)からmacOS用の.icnsを生成する。

macOSネイティブの`iconutil`コマンドが必要なため、macOS上でしか実行できない
(GitHub ActionsのmacOSランナーで`molweigh.spec`のビルド前に実行する想定)。
PyInstallerの`BUNDLE(icon=...)`は`.icns`のみ受け付け`.ico`は使えないため、この
変換が必要。物理Mac実機がなく開発機(Windows)では動作確認できていない
(仕様書9.3節の既知の制約と同様)。

実行例:
    python scripts/build_macos_icon.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ICO = REPO_ROOT / "molweigh" / "resources" / "app_icon.ico"
OUTPUT_ICNS = REPO_ROOT / "molweigh" / "resources" / "app_icon.icns"

# iconsetが要求する標準サイズ一式。元画像が256x256の場合、512/1024系列は
# アップスケールになる(元アイコンの解像度がその程度のため、実測上大きな
# 破綻はないが完全なレティナ品質ではない)。
ICONSET_SIZES = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit("このスクリプトはmacOS上でのみ実行できます(iconutilが必要)。")
    if shutil.which("iconutil") is None:
        raise SystemExit("iconutilが見つかりません(macOS標準コマンドのはずです)。")
    if not SOURCE_ICO.is_file():
        raise SystemExit(f"アイコン元ファイルが見つかりません: {SOURCE_ICO}")

    base = Image.open(SOURCE_ICO).convert("RGBA")

    iconset_dir = REPO_ROOT / "build" / "AppIcon.iconset"
    if iconset_dir.exists():
        shutil.rmtree(iconset_dir)
    iconset_dir.mkdir(parents=True)

    for filename, size in ICONSET_SIZES:
        resized = base.resize((size, size), Image.LANCZOS)
        resized.save(iconset_dir / filename)
        print(f"generated {filename} ({size}x{size})")

    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(OUTPUT_ICNS)],
        check=True,
    )
    print(f"wrote {OUTPUT_ICNS}")


if __name__ == "__main__":
    main()
