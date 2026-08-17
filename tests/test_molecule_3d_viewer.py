from PySide6.QtCore import QPointF
from PySide6.QtGui import QMouseEvent
from PySide6.QtCore import QEvent, Qt

from molweigh.core.structure_3d import generate_3d_conformer
from molweigh.ui.molecule_3d_viewer import Molecule3DDialog, Molecule3DView


def _mouse_event(event_type, pos, button=Qt.MouseButton.LeftButton):
    point = QPointF(*pos)
    return QMouseEvent(
        event_type,
        point,
        point,
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )


class TestMolecule3DView:
    def test_constructs_and_centers_molecule(self, qapp):
        mol3d = generate_3d_conformer("CCO")
        view = Molecule3DView(mol3d)
        avg_x = sum(a.x for a in view._molecule.atoms) / len(view._molecule.atoms)
        assert abs(avg_x) < 1e-6

    def test_drag_updates_rotation(self, qapp):
        mol3d = generate_3d_conformer("CCO")
        view = Molecule3DView(mol3d)
        initial_yaw, initial_pitch = view._yaw, view._pitch

        view.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress, (100, 100)))
        view.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, (150, 130)))

        assert view._yaw != initial_yaw
        assert view._pitch != initial_pitch

    def test_release_stops_dragging(self, qapp):
        mol3d = generate_3d_conformer("CCO")
        view = Molecule3DView(mol3d)
        view.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress, (100, 100)))
        assert view._dragging is True
        view.mouseReleaseEvent(_mouse_event(QEvent.Type.MouseButtonRelease, (100, 100)))
        assert view._dragging is False

    def test_paint_does_not_raise(self, qapp):
        mol3d = generate_3d_conformer("c1ccccc1")  # ring + aromatic bonds
        view = Molecule3DView(mol3d)
        view.resize(400, 400)
        view.repaint()  # 例外が出なければOK


class TestMolecule3DDialog:
    def test_constructs_with_view(self, qapp):
        mol3d = generate_3d_conformer("CCO")
        dialog = Molecule3DDialog(mol3d)
        assert dialog._view is not None
