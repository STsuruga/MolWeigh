"""Ketcher(構造式エディタ)の静的ビルドを取得し molweigh/ui/vendor/ketcher/ に配置する。

Node.js/npmが必要(https://nodejs.org/ からインストール)。
実行例:
    python scripts/build_ketcher.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

KETCHER_VERSION = "v3.17.0"
KETCHER_REPO = "https://github.com/epam/ketcher.git"

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = REPO_ROOT / ".ketcher_build"
VENDOR_DIR = REPO_ROOT / "molweigh" / "ui" / "vendor" / "ketcher"


def run(cmd: list[str], cwd: Path) -> None:
    # Windowsではnpm/npxが.cmdシムのため、shutil.whichで解決した実パスを渡さないと
    # shell=False の subprocess.run が `FileNotFoundError: [WinError 2]` で失敗する。
    resolved = shutil.which(cmd[0])
    if resolved is None:
        raise FileNotFoundError(f"コマンドが見つかりません: {cmd[0]}")
    print(f"$ {' '.join(cmd)}  (cwd={cwd})")
    subprocess.run([resolved, *cmd[1:]], cwd=cwd, check=True)


def main() -> None:
    if shutil.which("npm") is None:
        print("npmが見つかりません。Node.jsをインストールしてから再実行してください。", file=sys.stderr)
        sys.exit(1)

    if not (BUILD_DIR / ".git").exists():
        BUILD_DIR.parent.mkdir(parents=True, exist_ok=True)
        run(
            [
                "git", "clone", "--filter=blob:none", "--no-checkout",
                "--branch", KETCHER_VERSION, KETCHER_REPO, str(BUILD_DIR),
            ],
            cwd=REPO_ROOT,
        )
        run(["git", "sparse-checkout", "init", "--cone"], cwd=BUILD_DIR)
        run(["git", "sparse-checkout", "set", "example", "packages"], cwd=BUILD_DIR)
        run(["git", "checkout", KETCHER_VERSION], cwd=BUILD_DIR)

    run(["npm", "install", "--ignore-scripts"], cwd=BUILD_DIR)
    run(["npm", "run", "build:packages"], cwd=BUILD_DIR)
    run(["npm", "run", "build:example:standalone"], cwd=BUILD_DIR)

    built_dir = BUILD_DIR / "example" / "dist" / "standalone"
    if not (built_dir / "index.html").exists():
        print(f"ビルド成果物が見つかりません: {built_dir}", file=sys.stderr)
        sys.exit(1)

    if VENDOR_DIR.exists():
        shutil.rmtree(VENDOR_DIR)
    VENDOR_DIR.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(built_dir, VENDOR_DIR)
    print(f"Ketcherを配置しました: {VENDOR_DIR}")


if __name__ == "__main__":
    main()
