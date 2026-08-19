"""構造入力パネルの「3D」タブ。

Ketcherの`getMolfile()`で取得したMOLブロック(楔形つき)からSMILESへ変換し
(`structure.smiles_from_molblock`)、バックグラウンドで3D配座を生成して
`Molecule3DView`(QPainter直描き)に表示する。「この向きを2Dに反映」で、
ユーザーがドラッグで回転させた今の向きを2D構造式へ書き戻せる。
Ketcher自身の「3D Viewer→Apply」機能とは全く別の実装であり、その内部
回転ロジックを一切経由しないため、立体中心が壊れる問題は起きない。
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core import structure
from ..core.lineart_render import Scene
from . import theme
from .molecule_3d_view import Molecule3DView
from .scene_builder import SceneBuilder


class Structure3DTab(QWidget):
    """`on_reflect`は「この向きを2Dに反映」で得たMOLブロックを受け取るコールバック。"""

    def __init__(self, on_reflect: Callable[[str], None], parent: QWidget | None = None):
        super().__init__(parent)
        self._on_reflect = on_reflect
        self._scene: Scene | None = None

        self._builder = SceneBuilder(self)
        self._builder.sceneReady.connect(self._on_scene_ready)
        self._builder.failed.connect(self.show_error)

        self._view = Molecule3DView()

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")

        self._reflect_button = QPushButton("この向きを2Dに反映")
        self._reflect_button.setEnabled(False)
        self._reflect_button.clicked.connect(self._on_reflect_clicked)

        reset_button = QPushButton("向きをリセット")
        reset_button.clicked.connect(self._view.reset_view)

        button_row = QHBoxLayout()
        button_row.addWidget(self._reflect_button)
        button_row.addWidget(reset_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._status_label)
        layout.addWidget(self._view, 1)
        layout.addLayout(button_row)

    def request_build(self, smiles: str) -> None:
        """`smiles`から3D配座生成をバックグラウンドで開始する(数秒かかりうる)。"""
        self._reflect_button.setEnabled(False)
        self._status_label.setText("配座を生成中…")
        self._builder.build(smiles, mode="solid")

    def show_error(self, message: str) -> None:
        self._status_label.setText(message)
        self._reflect_button.setEnabled(False)
        self._scene = None
        self._view.set_scene(None)

    def shutdown(self) -> None:
        self._builder.shutdown()

    def _on_scene_ready(self, scene: Scene) -> None:
        self._scene = scene
        self._view.set_scene(scene)
        self._status_label.setText("ドラッグで回転、ホイールでズームできます。")
        self._reflect_button.setEnabled(True)

    def _on_reflect_clicked(self) -> None:
        if self._scene is None:
            return
        molblock = structure.build_molblock_from_scene(self._scene, self._view.current_rotation())
        self._on_reflect(molblock)
