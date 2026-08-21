"""3D配座生成(`lineart_render.build_scene`)をバックグラウンドスレッドで行う。

3D配座生成(`embed_and_optimize`)は複数配座のETKDG埋め込み+力場最適化を
伴い、最大3〜4秒かかることが実測されている(仕様書6.2節)。メインスレッドで
呼ぶとUIが固まるため、`QThread`上で実行しシグナルで結果を返す。

構造が変わって再度呼ばれた場合、古いジョブの結果は世代カウンタで無視する
(「生成中に構造が変わったら前のジョブを破棄する」という仕様書7.1節の要件)。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from ..core import lineart_render
from ..core.lineart_render import Scene


class _SceneBuilderWorker(QObject):
    finished = Signal(object)  # Scene
    failed = Signal(str)

    def __init__(self, smiles: str, mode: str, molblock: str | None = None) -> None:
        super().__init__()
        self._smiles = smiles
        self._mode = mode
        self._molblock = molblock

    def run(self) -> None:
        try:
            scene = lineart_render.get_or_build_scene(self._smiles, mode=self._mode, molblock=self._molblock)
        except ValueError as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(scene)


class _CleanupWorker(QObject):
    finished = Signal(object)  # lineart_render.CleanupResult
    failed = Signal(str)

    def __init__(self, scene: Scene, mode: str) -> None:
        super().__init__()
        self._scene = scene
        self._mode = mode

    def run(self) -> None:
        try:
            result = lineart_render.cleanup_geometry(self._scene, mode=self._mode)
        except ValueError as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


class SceneBuilder(QObject):
    """呼び出し側は`build()`/`cleanup()`を呼び、`sceneReady`/`cleanupReady`/`failed`
    シグナルを購読する。"""

    sceneReady = Signal(object)  # Scene
    cleanupReady = Signal(object)  # lineart_render.CleanupResult
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _SceneBuilderWorker | _CleanupWorker | None = None
        self._generation = 0

    def build(self, smiles: str, mode: str = "solid", molblock: str | None = None) -> None:
        """`molblock`を渡すと、solidモードでもKetcherで描いた向きに近い3D姿勢を選ぶ
        (`lineart_render.build_scene`のmolblock引数、Stage 2)。"""
        generation = self._start_job()
        worker = _SceneBuilderWorker(smiles, mode, molblock)
        worker.finished.connect(lambda scene: self._on_finished(generation, scene))
        self._run(worker, generation)

    def cleanup(self, scene: Scene, mode: str = "optimize") -> None:
        """現在のSceneに`lineart_render.cleanup_geometry`を適用する(3Dクリーンアップ機能)。"""
        generation = self._start_job()
        worker = _CleanupWorker(scene, mode)
        worker.finished.connect(lambda result: self._on_cleanup_finished(generation, result))
        self._run(worker, generation)

    def shutdown(self) -> None:
        self._stop_thread()

    def _start_job(self) -> int:
        self._generation += 1
        self._stop_thread()
        return self._generation

    def _run(self, worker: _SceneBuilderWorker | _CleanupWorker, generation: int) -> None:
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.failed.connect(lambda message: self._on_failed(generation, message))
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)

        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_finished(self, generation: int, scene: Scene) -> None:
        if generation == self._generation:
            self.sceneReady.emit(scene)

    def _on_cleanup_finished(self, generation: int, result) -> None:
        if generation == self._generation:
            self.cleanupReady.emit(result)

    def _on_failed(self, generation: int, message: str) -> None:
        if generation == self._generation:
            self.failed.emit(message)

    def _stop_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
            self._worker = None
