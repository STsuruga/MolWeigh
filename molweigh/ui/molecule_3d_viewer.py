"""RDKitで生成した3D配座を、マウスドラッグで回転できる簡易ビューアで表示する。

Ketcher自身の3D Viewer(Miew)と違い、ここでの回転操作は表示用のみで
2D構造への書き戻しは一切行わない(読み取り専用のプレビュー)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen, QWheelEvent
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.structure_3d import Atom3D, Molecule3D
from . import theme

_CPK_COLORS: dict[str, tuple[int, int, int]] = {
    "H": (255, 255, 255),
    "C": (90, 90, 90),
    "N": (48, 80, 248),
    "O": (255, 13, 13),
    "S": (255, 200, 50),
    "P": (255, 128, 0),
    "F": (144, 224, 80),
    "Cl": (31, 200, 31),
    "Br": (166, 41, 41),
    "I": (148, 0, 148),
}
_DEFAULT_COLOR = (222, 20, 147)

_ATOM_RADII: dict[str, float] = {
    "H": 0.30,
    "C": 0.62,
    "N": 0.58,
    "O": 0.54,
    "S": 0.90,
    "P": 0.90,
    "F": 0.50,
    "Cl": 0.90,
    "Br": 1.00,
    "I": 1.15,
}
_DEFAULT_RADIUS = 0.65

_BASE_SCALE = 55.0  # Å→pxの基準倍率
_MIN_ZOOM = 0.3
_MAX_ZOOM = 4.0
_DRAG_SENSITIVITY = 0.01
_ZOOM_STEP = 1.0015


@dataclass
class _Projected:
    x: float
    y: float
    depth: float  # 描画順(奥から手前)判定用


class Molecule3DView(QWidget):
    """3D配座をドラッグで回転・ホイールでズームして眺める読み取り専用ビュー。"""

    def __init__(self, molecule: Molecule3D, parent: QWidget | None = None):
        super().__init__(parent)
        self._molecule = _centered(molecule)
        self._yaw = 0.35
        self._pitch = -0.25
        self._zoom = 1.0
        self._dragging = False
        self._last_pos = QPointF()
        self.setMinimumSize(360, 360)
        self.setMouseTracking(False)

    def sizeHint(self) -> QSize:
        return QSize(520, 480)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._last_pos = event.position()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._dragging:
            return
        pos = event.position()
        dx = pos.x() - self._last_pos.x()
        dy = pos.y() - self._last_pos.y()
        self._last_pos = pos
        self._yaw += dx * _DRAG_SENSITIVITY
        self._pitch += dy * _DRAG_SENSITIVITY
        self._pitch = max(-math.pi / 2, min(math.pi / 2, self._pitch))
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = _ZOOM_STEP ** event.angleDelta().y()
        self._zoom = max(_MIN_ZOOM, min(_MAX_ZOOM, self._zoom * factor))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(theme.SURFACE))

        cx, cy = self.width() / 2, self.height() / 2
        scale = _BASE_SCALE * self._zoom
        cos_yaw, sin_yaw = math.cos(self._yaw), math.sin(self._yaw)
        cos_pitch, sin_pitch = math.cos(self._pitch), math.sin(self._pitch)

        def rotate(x: float, y: float, z: float) -> tuple[float, float, float]:
            # yaw(Y軸回転) → pitch(X軸回転)の順で適用
            x1 = x * cos_yaw + z * sin_yaw
            z1 = -x * sin_yaw + z * cos_yaw
            y1 = y * cos_pitch - z1 * sin_pitch
            z2 = y * sin_pitch + z1 * cos_pitch
            return x1, y1, z2

        projected: list[_Projected] = []
        for atom in self._molecule.atoms:
            rx, ry, rz = rotate(atom.x, atom.y, atom.z)
            projected.append(_Projected(x=cx + rx * scale, y=cy - ry * scale, depth=rz))

        draw_items: list[tuple[float, str, object]] = []
        for bond in self._molecule.bonds:
            depth = (projected[bond.begin].depth + projected[bond.end].depth) / 2
            draw_items.append((depth, "bond", bond))
        for i, atom in enumerate(self._molecule.atoms):
            draw_items.append((projected[i].depth, "atom", (i, atom)))
        draw_items.sort(key=lambda item: item[0])

        for _, kind, payload in draw_items:
            if kind == "bond":
                self._draw_bond(painter, payload, projected)
            else:
                index, atom = payload
                self._draw_atom(painter, projected[index], atom.symbol)

    def _draw_bond(self, painter: QPainter, bond, projected: list[_Projected]) -> None:
        p1, p2 = projected[bond.begin], projected[bond.end]
        color = QColor(150, 150, 150)
        offsets = _bond_offsets(bond.order)
        dx, dy = p2.x - p1.x, p2.y - p1.y
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        for offset in offsets:
            pen = QPen(color, 2.2)
            painter.setPen(pen)
            painter.drawLine(
                QPointF(p1.x + nx * offset, p1.y + ny * offset),
                QPointF(p2.x + nx * offset, p2.y + ny * offset),
            )

    def _draw_atom(self, painter: QPainter, point: _Projected, symbol: str) -> None:
        color = QColor(*_CPK_COLORS.get(symbol, _DEFAULT_COLOR))
        radius = _ATOM_RADII.get(symbol, _DEFAULT_RADIUS) * _BASE_SCALE * self._zoom * 0.6
        painter.setPen(QPen(color.darker(140), 1))
        painter.setBrush(color)
        painter.drawEllipse(QPointF(point.x, point.y), radius, radius)


class Molecule3DDialog(QDialog):
    """`Molecule3DView` を包む読み取り専用のプレビューダイアログ。"""

    def __init__(self, molecule: Molecule3D, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("3Dプレビュー")
        self.resize(560, 560)

        hint_label = QLabel("ドラッグで回転、ホイールでズームできます(2D構造には反映されません)。")
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")

        self._view = Molecule3DView(molecule, self)

        close_button = QPushButton("閉じる")
        close_button.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(hint_label)
        layout.addWidget(self._view, 1)
        layout.addWidget(close_button)


def _centered(molecule: Molecule3D) -> Molecule3D:
    if not molecule.atoms:
        return molecule
    cx = sum(a.x for a in molecule.atoms) / len(molecule.atoms)
    cy = sum(a.y for a in molecule.atoms) / len(molecule.atoms)
    cz = sum(a.z for a in molecule.atoms) / len(molecule.atoms)
    centered_atoms = [Atom3D(symbol=a.symbol, x=a.x - cx, y=a.y - cy, z=a.z - cz) for a in molecule.atoms]
    return Molecule3D(atoms=centered_atoms, bonds=molecule.bonds)


def _bond_offsets(order: float) -> list[float]:
    if order >= 2.9:
        return [-3.0, 0.0, 3.0]
    if order >= 1.9:
        return [-2.0, 2.0]
    return [0.0]
