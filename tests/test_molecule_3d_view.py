from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from molweigh.core import lineart_render as lr
from molweigh.ui.molecule_3d_view import Molecule3DView


def _key_event(key):
    return QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)


class TestMolecule3DView:
    def test_constructs_without_scene(self, qapp):
        view = Molecule3DView()
        assert view.current_rotation() == (1.0, 0.0, 0.0, 0.0)

    def test_paints_without_error_when_scene_set(self, qapp):
        scene = lr.build_scene("CCO", mode="auto")
        view = Molecule3DView(scene)
        view.resize(200, 200)
        pixmap = view.grab()
        assert not pixmap.isNull()

    def test_paints_without_error_when_no_scene(self, qapp):
        view = Molecule3DView()
        view.resize(200, 200)
        pixmap = view.grab()
        assert not pixmap.isNull()

    def test_arrow_key_rotates_around_y_axis(self, qapp):
        scene = lr.build_scene("CCO", mode="solid")
        view = Molecule3DView(scene)
        for _ in range(6):  # 6 * 15deg = 90deg
            view.keyPressEvent(_key_event(Qt.Key.Key_Right))
        w, x, y, z = view.current_rotation()
        assert abs(w - 0.7071) < 1e-3
        assert abs(y - 0.7071) < 1e-3
        assert abs(x) < 1e-9
        assert abs(z) < 1e-9

    def test_reset_view_returns_to_identity(self, qapp):
        scene = lr.build_scene("CCO", mode="solid")
        view = Molecule3DView(scene)
        view.keyPressEvent(_key_event(Qt.Key.Key_Right))
        assert view.current_rotation() != (1.0, 0.0, 0.0, 0.0)
        view.reset_view()
        assert view.current_rotation() == (1.0, 0.0, 0.0, 0.0)

    def test_wheel_zoom_changes_scale_within_bounds(self, qapp):
        scene = lr.build_scene("CCO", mode="auto")
        view = Molecule3DView(scene)
        assert view._scale == 1.0
        for _ in range(200):  # far more than needed to hit the clamp
            from PySide6.QtCore import QPoint, QPointF
            from PySide6.QtGui import QWheelEvent

            event = QWheelEvent(
                QPointF(10, 10),
                QPointF(10, 10),
                QPoint(0, 0),
                QPoint(0, 120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            )
            view.wheelEvent(event)
        assert view._scale <= 8.0

    def test_set_scene_updates_current_scene(self, qapp):
        view = Molecule3DView()
        scene = lr.build_scene("CCO", mode="auto")
        view.set_scene(scene)
        assert view._scene is scene
