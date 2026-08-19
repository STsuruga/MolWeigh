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
