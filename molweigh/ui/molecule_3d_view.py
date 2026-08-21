"""QPainter直描きの3D構造ビュー(アークボール回転)。

`QWebEngineView`を一切使わないため、既知の環境依存クラッシュ(WebEngineを
大量に使うテストでのネイティブクラッシュ)から解放される。幾何計算は
`core/lineart_render.py::compute_geometry()`をSVG出力(`render_svg`)と
共有しており、二重実装は作らない。分子サイズにほぼ依存せず1フレーム
数msで描画できるため(仕様書実測)、JS/WebGLに逃がす必要はない。
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QMouseEvent, QPainter, QPen, QPolygonF, QWheelEvent
from PySide6.QtWidgets import QWidget

from ..core.lineart_render import RenderParams, Scene, compute_geometry

Quaternion = tuple[float, float, float, float]  # (w, x, y, z)

_IDENTITY_ROTATION: Quaternion = (1.0, 0.0, 0.0, 0.0)
_ZOOM_MIN = 0.2
_ZOOM_MAX = 8.0
_KEY_ROTATION_STEP = np.radians(15)

# 仮想球半径 = 0.5*min(w,h)*ARCBALL_SENSITIVITY。1.0(半径そのまま)だと中央付近の
# ドラッグに対して回転が急峻になり「ずれている」と感じやすいため縮小する。
ARCBALL_SENSITIVITY = 0.7

# Ctrl+ドラッグ(画面平面内回転)の感度。1pxあたりのラジアン数。
# 画面中心からの角度(atan2)を使う実装は中心付近で方向が不安定になり
# (中心に近いほど同じ距離の動きが大きい角度変化になる)、感度過多・回転の
# 飽和(=急激な符号反転で打ち消し合う)として体感された。水平ドラッグ量に
# 単純比例させる方式にして、中心特異点を排除している。
ROLL_SENSITIVITY = 0.006


def _quat_multiply(a: Quaternion, b: Quaternion) -> Quaternion:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def _quat_normalize(q: Quaternion) -> Quaternion:
    n = float(np.linalg.norm(q))
    if n < 1e-9:
        return _IDENTITY_ROTATION
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


def _quat_from_axis_angle(axis: np.ndarray, angle: float) -> Quaternion:
    norm = float(np.linalg.norm(axis))
    if norm < 1e-9 or abs(angle) < 1e-9:
        return _IDENTITY_ROTATION
    axis = axis / norm
    half = angle / 2
    s = np.sin(half)
    return (float(np.cos(half)), float(axis[0] * s), float(axis[1] * s), float(axis[2] * s))


class Molecule3DView(QWidget):
    """マウス操作(アークボール回転・ホイールズーム・中ドラッグでパン)で
    回転できる読み取り専用の3D構造ビュー。"""

    rotationChanged = Signal()

    def __init__(self, scene: Scene | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._scene = scene
        self._rotation: Quaternion = _IDENTITY_ROTATION
        self._scale = 1.0
        self._pan_offset = np.zeros(2)

        self._dragging = False
        self._rolling = False
        self._panning = False
        self._last_arcball = np.array([0.0, 0.0, 1.0])
        self._last_pos: QPointF | None = None

        # 隠線ギャップ判定はO(n^2)で最も重く、姿勢(回転)とウィンドウサイズにしか
        # 依存しない。ズーム・パンだけの再描画では回転が変わらないため、直前の
        # 結果をそのまま使い回す(S1: 交差判定キャッシュ)。
        self._geom_cache_scene: Scene | None = None
        self._geom_cache_rotation: Quaternion | None = None
        self._geom_cache_size: tuple[int, int] | None = None
        self._geom_cache_result = None

    def set_scene(self, scene: Scene | None) -> None:
        self._scene = scene
        self.update()

    def current_rotation(self) -> Quaternion:
        """現在の回転をクォータニオン(w,x,y,z)として返す(「この向きを2Dに反映」用)。"""
        return self._rotation

    def reset_view(self) -> None:
        """`Scene.initial_rotation`(見やすい初期角度)へ戻す。"""
        self._rotation = _IDENTITY_ROTATION
        self._scale = 1.0
        self._pan_offset = np.zeros(2)
        self.update()

    # --- アークボール幾何 -------------------------------------------------

    def _arcball_vector(self, pos: QPointF) -> np.ndarray:
        w, h = max(self.width(), 1), max(self.height(), 1)
        r = 0.5 * min(w, h) * ARCBALL_SENSITIVITY
        x = (pos.x() - w / 2) / r
        y = -(pos.y() - h / 2) / r
        d2 = x * x + y * y
        if d2 <= 0.5:
            z = np.sqrt(1.0 - d2)
        else:
            z = 0.5 / np.sqrt(d2)  # Holroyd方式: 縁の外側は双曲面に逃がし不連続を防ぐ
        v = np.array([x, y, z])
        return v / np.linalg.norm(v)

    def _apply_rotation(self, axis: np.ndarray, angle: float) -> None:
        dq = _quat_from_axis_angle(np.asarray(axis, dtype=float), angle)
        self._rotation = _quat_normalize(_quat_multiply(dq, self._rotation))
        self.rotationChanged.emit()

    # --- マウス操作 ---------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._rolling = True
            else:
                self._dragging = True
                self._last_arcball = self._arcball_vector(event.position())
        elif event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
        self._last_pos = event.position()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._rolling and self._last_pos is not None:
            dx = event.position().x() - self._last_pos.x()
            delta = -dx * ROLL_SENSITIVITY
            if abs(delta) > 1e-9:
                self._apply_rotation(np.array([0.0, 0.0, 1.0]), delta)
            self._last_pos = event.position()
            self.update()
        elif self._dragging:
            cur = self._arcball_vector(event.position())
            prev = self._last_arcball
            axis = np.cross(prev, cur)
            dot = float(np.clip(np.dot(prev, cur), -1.0, 1.0))
            angle = float(np.arccos(dot))
            if np.linalg.norm(axis) > 1e-9 and angle > 1e-6:
                self._apply_rotation(axis, angle)
            self._last_arcball = cur
            self.update()
        elif self._panning and self._last_pos is not None:
            delta = event.position() - self._last_pos
            self._pan_offset += np.array([delta.x(), delta.y()])
            self._last_pos = event.position()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._rolling = False
        elif event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
        self._last_pos = None

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.1 if event.angleDelta().y() > 0 else 1 / 1.1
        self._scale = float(np.clip(self._scale * factor, _ZOOM_MIN, _ZOOM_MAX))
        self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Left:
            self._apply_rotation(np.array([0.0, 1.0, 0.0]), -_KEY_ROTATION_STEP)
        elif key == Qt.Key.Key_Right:
            self._apply_rotation(np.array([0.0, 1.0, 0.0]), _KEY_ROTATION_STEP)
        elif key == Qt.Key.Key_Up:
            self._apply_rotation(np.array([1.0, 0.0, 0.0]), -_KEY_ROTATION_STEP)
        elif key == Qt.Key.Key_Down:
            self._apply_rotation(np.array([1.0, 0.0, 0.0]), _KEY_ROTATION_STEP)
        elif key == Qt.Key.Key_R:
            self.reset_view()
        else:
            super().keyPressEvent(event)
            return
        self.update()

    # --- 描画 -------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("white"))

        if self._scene is None or len(self._scene.coords) == 0:
            painter.end()
            return

        size = (self.width(), self.height())
        if (
            self._geom_cache_result is not None
            and self._geom_cache_scene is self._scene
            and self._geom_cache_rotation == self._rotation
            and self._geom_cache_size == size
        ):
            geometry = self._geom_cache_result
        else:
            params = RenderParams(width=size[0], height=size[1])
            geometry = compute_geometry(self._scene, self._rotation, params)
            self._geom_cache_scene = self._scene
            self._geom_cache_rotation = self._rotation
            self._geom_cache_size = size
            self._geom_cache_result = geometry
        params = geometry.params  # キャッシュ命中時はローカルのparamsが未定義のため、geometry側から取得する

        painter.translate(self._pan_offset[0], self._pan_offset[1])
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(self._scale, self._scale)
        painter.translate(-self.width() / 2, -self.height() / 2)

        for line in geometry.lines:
            pen = QPen(QColor(*line.color))
            pen.setWidthF(line.width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(float(line.p0[0]), float(line.p0[1])), QPointF(float(line.p1[0]), float(line.p1[1])))

        for wedge in geometry.wedges:
            color = QColor(*wedge.color)
            if wedge.kind > 0:  # 実楔: 塗りつぶし三角形
                half = params.wedge_width / 2
                a = wedge.p1 + wedge.normal * half
                b = wedge.p1 - wedge.normal * half
                poly = QPolygonF(
                    [
                        QPointF(float(wedge.p0[0]), float(wedge.p0[1])),
                        QPointF(float(a[0]), float(a[1])),
                        QPointF(float(b[0]), float(b[1])),
                    ]
                )
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawPolygon(poly)
            else:  # 破線楔
                pen = QPen(color)
                pen.setWidthF(params.width_near * 0.85)
                painter.setPen(pen)
                length = float(np.linalg.norm(wedge.p1 - wedge.p0))
                steps = max(int(length / params.hash_pitch), 2)
                for m in range(1, steps + 1):
                    f = m / steps
                    c = wedge.p0 + (wedge.p1 - wedge.p0) * f
                    w = (params.wedge_width / 2) * f
                    p0 = c - wedge.normal * w
                    p1 = c + wedge.normal * w
                    painter.drawLine(QPointF(float(p0[0]), float(p0[1])), QPointF(float(p1[0]), float(p1[1])))

        painter.setBrush(Qt.BrushStyle.NoBrush)
        font = QFont("Helvetica")
        font.setPointSizeF(params.font_size)
        painter.setFont(font)
        for label in geometry.labels:
            painter.setPen(QColor(*label.color))
            rect = QRectF(label.pos[0] - 30, label.pos[1] - 12, 60, 24)
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), label.text + label.charge)

        painter.end()
