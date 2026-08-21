from PySide6.QtCore import QEventLoop, QTimer

from molweigh.ui.structure_3d_tab import Structure3DTab


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


class TestStructure3DTab:
    def test_constructs_with_reflect_disabled(self, qapp):
        tab = Structure3DTab(on_reflect=lambda molblock: None)
        assert not tab._reflect_button.isEnabled()
        tab.shutdown()

    def test_request_build_enables_reflect_once_ready(self, qapp):
        tab = Structure3DTab(on_reflect=lambda molblock: None)
        tab.request_build("CCO")
        _run_until(lambda: tab._reflect_button.isEnabled())
        assert tab._scene is not None
        tab.shutdown()

    def test_invalid_smiles_shows_error_and_keeps_reflect_disabled(self, qapp):
        tab = Structure3DTab(on_reflect=lambda molblock: None)
        tab.request_build("not-a-smiles(((")
        _run_until(lambda: tab._status_label.text() != "配座を生成中…")
        assert not tab._reflect_button.isEnabled()
        assert tab._scene is None
        tab.shutdown()

    def test_reflect_click_invokes_callback_with_molblock(self, qapp):
        received = []
        tab = Structure3DTab(on_reflect=lambda molblock: received.append(molblock))
        tab.request_build("CCO")
        _run_until(lambda: tab._reflect_button.isEnabled())

        tab._on_reflect_clicked()

        assert len(received) == 1
        assert "V2000" in received[0]
        tab.shutdown()

    def test_cleanup_buttons_enabled_once_scene_ready(self, qapp):
        tab = Structure3DTab(on_reflect=lambda molblock: None)
        assert not tab._orient_button.isEnabled()
        tab.request_build("CCCCCCCCCC")
        _run_until(lambda: tab._orient_button.isEnabled())
        assert tab._optimize_button.isEnabled()
        assert tab._reembed_button.isEnabled()
        assert not tab._undo_button.isEnabled()  # まだクリーンアップしていない
        tab.shutdown()

    def test_orient_recomputes_rotation_synchronously(self, qapp):
        tab = Structure3DTab(on_reflect=lambda molblock: None)
        tab.request_build("CCCCCCCCCC")
        _run_until(lambda: tab._orient_button.isEnabled())

        tab._on_orient_clicked()

        assert tab._scene is not None
        assert not tab._undo_button.isEnabled()  # 向きの再計算はUndo対象外

    def test_optimize_updates_scene_and_enables_undo(self, qapp):
        tab = Structure3DTab(on_reflect=lambda molblock: None)
        tab.request_build("CCCCCCCCCC")
        _run_until(lambda: tab._optimize_button.isEnabled())
        original_scene = tab._scene

        tab._start_cleanup("optimize")
        assert not tab._optimize_button.isEnabled()  # 処理中は無効化
        _run_until(lambda: tab._optimize_button.isEnabled())

        assert tab._scene is not None
        assert tab._scene is not original_scene
        assert tab._undo_button.isEnabled()
        assert "エネルギー変化" in tab._status_label.text()
        tab.shutdown()

    def test_undo_restores_previous_scene(self, qapp):
        tab = Structure3DTab(on_reflect=lambda molblock: None)
        tab.request_build("CCCCCCCCCC")
        _run_until(lambda: tab._optimize_button.isEnabled())
        original_scene = tab._scene

        tab._start_cleanup("optimize")
        _run_until(lambda: tab._undo_button.isEnabled())

        tab._on_undo_clicked()

        assert tab._scene is original_scene
        assert not tab._undo_button.isEnabled()
        tab.shutdown()

    def test_optimize_preserves_camera_by_keeping_old_initial_rotation(self, qapp):
        tab = Structure3DTab(on_reflect=lambda molblock: None)
        tab.request_build("CCCCCCCCCC")
        _run_until(lambda: tab._optimize_button.isEnabled())
        old_initial_rotation = tab._scene.initial_rotation

        tab._start_cleanup("optimize")
        _run_until(lambda: tab._optimize_button.isEnabled())

        import numpy as np

        assert np.array_equal(tab._scene.initial_rotation, old_initial_rotation)
        tab.shutdown()
