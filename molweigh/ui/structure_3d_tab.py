"""構造入力パネルの「3D」タブ。

Ketcherの`getMolfile()`で取得したMOLブロック(楔形つき)からSMILESへ変換し
(`structure.smiles_from_molblock`)、バックグラウンドで3D配座を生成して
`Molecule3DView`(QPainter直描き)に表示する。「この向きを2Dに反映」で、
ユーザーがドラッグで回転させた今の向きを2D構造式へ書き戻せる。
Ketcher自身の「3D Viewer→Apply」機能とは全く別の実装であり、その内部
回転ロジックを一切経由しないため、立体中心が壊れる問題は起きない。

「向きを整える」「形を整える」「配座を選び直す」はクリーンアップ機能
(`core/lineart_render.py::cleanup_geometry`)のUI側。形を整える・配座を
選び直すは重い処理のため`SceneBuilder`経由でバックグラウンド実行し、直前の
Sceneを1つだけ保持して「元に戻す」で復元できる。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core import lineart_render, structure
from ..core.lineart_render import CleanupResult, Scene
from . import theme
from .molecule_3d_view import Molecule3DView
from .scene_builder import SceneBuilder


class Structure3DTab(QWidget):
    """`on_reflect`は「この向きを2Dに反映」で得たMOLブロックを受け取るコールバック。"""

    def __init__(self, on_reflect: Callable[[str], None], parent: QWidget | None = None):
        super().__init__(parent)
        self._on_reflect = on_reflect
        self._scene: Scene | None = None
        self._undo_scene: Scene | None = None
        self._pending_undo_scene: Scene | None = None

        self._builder = SceneBuilder(self)
        self._builder.sceneReady.connect(self._on_scene_ready)
        self._builder.cleanupReady.connect(self._on_cleanup_ready)
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

        self._orient_button = QPushButton("向きを整える")
        self._orient_button.setToolTip("見やすい初期姿勢を再計算します(ほぼ即時)")
        self._orient_button.setEnabled(False)
        self._orient_button.clicked.connect(self._on_orient_clicked)

        self._optimize_button = QPushButton("形を整える")
        self._optimize_button.setToolTip("歪んだ結合長・結合角を力場計算で正します")
        self._optimize_button.setEnabled(False)
        self._optimize_button.clicked.connect(lambda: self._start_cleanup("optimize"))

        self._reembed_button = QPushButton("配座を選び直す")
        self._reembed_button.setToolTip("配座をゼロから生成し直します(数秒かかることがあります)")
        self._reembed_button.setEnabled(False)
        self._reembed_button.clicked.connect(lambda: self._start_cleanup("reembed"))

        self._undo_button = QPushButton("クリーンアップを取り消す")
        self._undo_button.setEnabled(False)
        self._undo_button.clicked.connect(self._on_undo_clicked)

        cleanup_row = QHBoxLayout()
        cleanup_row.addWidget(self._orient_button)
        cleanup_row.addWidget(self._optimize_button)
        cleanup_row.addWidget(self._reembed_button)
        cleanup_row.addWidget(self._undo_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._status_label)
        layout.addWidget(self._view, 1)
        layout.addLayout(button_row)
        layout.addLayout(cleanup_row)

    def request_build(self, smiles: str, molblock: str | None = None) -> None:
        """`smiles`から3D配座生成をバックグラウンドで開始する(数秒かかりうる)。

        `molblock`を渡すと、橋かけ構造など2D座標をそのまま使えない分子でも
        Ketcherで描いた向きに近い3D姿勢を初期表示にする(Stage 2)。
        """
        self._reflect_button.setEnabled(False)
        self._undo_scene = None
        self._undo_button.setEnabled(False)
        self._set_cleanup_buttons_enabled(False)
        self._set_status("配座を生成中…")
        self._builder.build(smiles, mode="solid", molblock=molblock)

    def show_error(self, message: str) -> None:
        self._set_status(message)
        self._reflect_button.setEnabled(False)
        self._set_cleanup_buttons_enabled(False)
        self._scene = None
        self._view.set_scene(None)

    def shutdown(self) -> None:
        self._builder.shutdown()

    def _on_scene_ready(self, scene: Scene) -> None:
        self._scene = scene
        self._view.set_scene(scene)
        self._set_status("ドラッグで回転、Ctrl+ドラッグで平面内回転、ホイールでズームできます。")
        self._reflect_button.setEnabled(True)
        self._set_cleanup_buttons_enabled(True)

    def _on_reflect_clicked(self) -> None:
        if self._scene is None:
            return
        molblock = structure.build_molblock_from_scene(self._scene, self._view.current_rotation())
        self._on_reflect(molblock)

    # --- クリーンアップ機能 -------------------------------------------------

    def _on_orient_clicked(self) -> None:
        """機能C(向きを整える): 現在の配座はそのまま、初期姿勢だけ再計算する。ほぼ無コスト。"""
        if self._scene is None:
            return
        new_scene = lineart_render.recompute_initial_rotation(self._scene)
        self._scene = new_scene
        self._view.set_scene(new_scene)
        self._view.reset_view()  # 再計算した新しい向きをそのまま見せる
        self._set_status("向きを再計算しました。")

    def _start_cleanup(self, mode: str) -> None:
        if self._scene is None:
            return
        self._pending_undo_scene = self._scene
        self._set_cleanup_buttons_enabled(False)
        self._reflect_button.setEnabled(False)
        self._set_status("形を整えています…" if mode == "optimize" else "配座を選び直しています…(数秒かかることがあります)")
        self._builder.cleanup(self._scene, mode=mode)

    def _on_cleanup_ready(self, result: CleanupResult) -> None:
        old_scene = self._pending_undo_scene
        self._undo_scene = old_scene
        self._undo_button.setEnabled(True)

        # カメラ維持: ユーザーが手で回転させた現在の向き(self._view._rotation)は
        # そのまま保持し、新Sceneの初期姿勢だけ旧Sceneのものに据え置く。
        # cleanup_geometryが返す新しい初期姿勢をそのまま採用すると、視点が
        # 急に飛んだように見える(仕様書4章参照)。
        new_scene = replace(result.scene, initial_rotation=old_scene.initial_rotation) if old_scene else result.scene
        self._scene = new_scene
        self._view.set_scene(new_scene)

        self._set_cleanup_buttons_enabled(True)
        self._reflect_button.setEnabled(True)

        energy_text = f"エネルギー変化: {result.energy_delta:+.1f} kcal/mol"
        if result.stereo_changed:
            self._set_status(f"{energy_text}(警告: 立体中心の表記が変化しました。「取り消す」で元に戻せます)", warning=True)
        else:
            self._set_status(energy_text)

    def _on_undo_clicked(self) -> None:
        if self._undo_scene is None:
            return
        self._scene = self._undo_scene
        self._view.set_scene(self._undo_scene)
        self._undo_scene = None
        self._undo_button.setEnabled(False)
        self._set_status("クリーンアップを取り消しました。")

    def _set_cleanup_buttons_enabled(self, enabled: bool) -> None:
        self._orient_button.setEnabled(enabled)
        self._optimize_button.setEnabled(enabled)
        self._reembed_button.setEnabled(enabled)
        # 取り消せる状態は維持する(処理中でも直前の状態には戻せてよい)
        if not enabled:
            self._undo_button.setEnabled(False)
        elif self._undo_scene is not None:
            self._undo_button.setEnabled(True)

    def _set_status(self, message: str, warning: bool = False) -> None:
        self._status_label.setText(message)
        color = theme.WARNING_TEXT if warning else theme.TEXT_MUTED
        self._status_label.setStyleSheet(f"color: {color}; font-size: 12px;")
