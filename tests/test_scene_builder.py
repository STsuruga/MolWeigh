from PySide6.QtCore import QEventLoop, QTimer

from molweigh.ui.scene_builder import SceneBuilder


def _run_until(condition, timeout_ms=15000):
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)

    def check():
        if condition():
            loop.quit()
        else:
            QTimer.singleShot(20, check)

    QTimer.singleShot(0, check)
    timer.start(timeout_ms)
    loop.exec()


class TestSceneBuilder:
    def test_build_emits_scene_ready(self, qapp):
        builder = SceneBuilder()
        results = []
        builder.sceneReady.connect(results.append)

        builder.build("CCO", mode="auto")
        _run_until(lambda: len(results) == 1)

        assert len(results) == 1
        assert len(results[0].coords) == 3
        builder.shutdown()

    def test_invalid_smiles_emits_failed(self, qapp):
        builder = SceneBuilder()
        errors = []
        builder.failed.connect(errors.append)

        builder.build("not-a-smiles(((", mode="auto")
        _run_until(lambda: len(errors) == 1)

        assert len(errors) == 1
        builder.shutdown()

    def test_stale_job_is_discarded(self, qapp):
        # build()はサニティのため前のスレッドをwait()で待つ実装なので、後発の
        # build("CCCC")が呼ばれる時点で世代カウンタは既に進んでいる。先発の
        # build("CCO")の結果はその世代不一致で破棄され、後発の結果だけが届く。
        builder = SceneBuilder()
        results = []
        builder.sceneReady.connect(results.append)

        builder.build("CCO", mode="auto")  # 3原子(C,C,O)
        builder.build("CCCC", mode="auto")  # 4原子(C,C,C,C)
        _run_until(lambda: len(results) >= 1)
        # 念のため少し待ち、2件目が来ないことを確認する
        _run_until(lambda: False, timeout_ms=300)

        assert len(results) == 1
        assert len(results[0].coords) == 4
        builder.shutdown()
