# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller ビルド仕様。

`pyinstaller molweigh.spec` で実行する。Ketcher の静的ビルド
(`molweigh/ui/vendor/ketcher/`、`scripts/build_ketcher.py` で事前生成が必要)
と RDKit のデータファイルを同梱する。QtWebEngine 関連のバイナリ・リソースは
`pyinstaller-hooks-contrib` の PySide6 フックが自動収集する。
"""

import os
import sys

import rdkit
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# PyInstallerがspecファイルをexec()する際に注入する組み込み変数
# (specファイルには__file__が存在しないため、これを使う)。
REPO_ROOT = os.path.abspath(SPECPATH)
KETCHER_DIR = os.path.join(REPO_ROOT, "molweigh", "ui", "vendor", "ketcher")

# Windowsは.icoをそのまま使える。macOSは.icnsが必要(PyInstallerのBUNDLEは.icoを
# 受け付けない)。物理Mac実機がないため、.icnsはCI側(macOSランナー)で
# .github/workflows/build.ymlのステップにより.icoから生成し、同じパスに置く。
# ローカルWindowsビルドでは.icnsが存在しないため、その場合はicon=Noneにフォール
# バックする(BUNDLE自体sys.platform=="darwin"でしか実行されないので実害はない)。
ICON_ICO = os.path.join(REPO_ROOT, "molweigh", "resources", "app_icon.ico")
ICON_ICNS = os.path.join(REPO_ROOT, "molweigh", "resources", "app_icon.icns")

if not os.path.isdir(KETCHER_DIR):
    raise SystemExit(
        f"Ketcherの静的ビルドが見つかりません: {KETCHER_DIR}\n"
        "先に `python scripts/build_ketcher.py` を実行してください。"
    )

rdkit_data_dir = os.path.join(os.path.dirname(rdkit.__file__), "Data")

datas = [
    (KETCHER_DIR, os.path.join("molweigh", "ui", "vendor", "ketcher")),
    (rdkit_data_dir, os.path.join("rdkit", "Data")),
]
datas += collect_data_files("rdkit")

a = Analysis(
    ["main.py"],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "PySide6.QtSvg",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtNetwork",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MolWeigh",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_ICO if os.path.isfile(ICON_ICO) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MolWeigh",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="MolWeigh.app",
        icon=ICON_ICNS if os.path.isfile(ICON_ICNS) else None,
        bundle_identifier="com.molweigh.app",
        info_plist={
            "NSHighResolutionCapable": "True",
            "CFBundleShortVersionString": "0.2.0",
        },
    )
