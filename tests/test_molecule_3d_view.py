import numpy as np
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from molweigh.core import lineart_render as lr
from molweigh.ui.molecule_3d_view import Molecule3DView


def _key_event(key):
    return QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)


def _mouse_event(event_type, pos, button=Qt.MouseButton.LeftButton, buttons=None, modifiers=Qt.KeyboardModifier.NoModifier):
    if buttons is None:
        buttons = button
    return QMouseEvent(event_type, pos, pos, button, buttons, modifiers)


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

    def test_repaint_with_unchanged_rotation_hits_geometry_cache(self, qapp):
        # 2回目以降の再描画(姿勢・サイズ不変)はジオメトリキャッシュを使う経路。
        # キャッシュ命中時に`params`未定義でcrashしないことを確認する回帰テスト
        # (ウェッジ・ラベルを持つキラル分子でないと該当コードパスを通らない)。
        scene = lr.build_scene("C[C@@H](N)C(=O)O", mode="auto")
        view = Molecule3DView(scene)
        view.resize(200, 200)
        view.grab()  # 1回目: キャッシュミスでジオメトリを構築
        pixmap = view.grab()  # 2回目: キャッシュ命中
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

    def test_arcball_vector_is_unit_length_center_and_edge(self, qapp):
        view = Molecule3DView()
        view.resize(200, 200)
        center = view._arcball_vector(QPointF(100, 100))
        assert np.allclose(center, [0.0, 0.0, 1.0])
        edge = view._arcball_vector(QPointF(199, 100))  # ウィンドウ端(縁の外側、Holroyd方式)
        assert abs(np.linalg.norm(edge) - 1.0) < 1e-9

    def test_ctrl_drag_rotates_around_view_axis_only(self, qapp):
        scene = lr.build_scene("CCO", mode="solid")
        view = Molecule3DView(scene)
        view.resize(200, 200)
        press = _mouse_event(QEvent.Type.MouseButtonPress, QPointF(150, 100), modifiers=Qt.KeyboardModifier.ControlModifier)
        view.mousePressEvent(press)
        move = _mouse_event(
            QEvent.Type.MouseMove, QPointF(100, 150), buttons=Qt.MouseButton.LeftButton, modifiers=Qt.KeyboardModifier.ControlModifier
        )
        view.mouseMoveEvent(move)
        w, x, y, z = view.current_rotation()
        assert abs(x) < 1e-9
        assert abs(y) < 1e-9
        assert abs(z) > 1e-3  # Z軸(画面奥行き)まわりの回転のみ生じている
