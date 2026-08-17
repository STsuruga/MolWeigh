"""ChemDraw「Clean Up 3D Structure」風の、回転可能な線画3Dビューア。

3Dmol.js版(丸みのあるスティック表示のWebGLレンダリング)とは異なり、こちらは
ChemDrawの3D構造表示と同じ原理 ― 3D原子座標を2Dへ正射影し、結合線同士が
交差する箇所で奥にある線を分割してギャップを入れる(隠線除去/line-break技法)
ベクター線画を描く。役割分担として、化学計算(3D配座生成)はPython(RDKit、
`core/structure.py::generate_lineart_data`)が担い、幾何処理(回転・投影・
交差判定・ギャップ計算)と描画・マウス操作はすべてJavaScript側で完結させる
(Python⇔JS間の往復を発生させない)。

外部ライブラリではなく自前実装のJSのため、Ketcher/3Dmol.jsのような
ローカルHTTPサーバー経由の配信は不要で、生成したHTMLにスクリプトを直接
埋め込んで `QWebEngineView.setHtml()` で読み込む。
"""

from __future__ import annotations

import json

from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.structure import LineArtMolecule
from . import theme

# --- 幾何処理(回転・正射影・線分交差判定・隠線ギャップ計算)+ 描画 + マウス操作 ---
# クォータニオンで回転を保持することでジンバルロックを避ける。マウスドラッグの
# たびに小さな回転をクォータニオン合成で積み重ね、requestAnimationFrameで
# dirtyフラグが立っている時だけ再描画する(アイドル時はCPUを使わない)。
_LINEART_JS = r"""
(function () {
  "use strict";

  var atomsIn = window.__MOLWEIGH_ATOMS__;
  var bonds = window.__MOLWEIGH_BONDS__;
  var container = document.getElementById("viewer");

  // 重心を原点へ平行移動しておく(回転・ズームの中心を分子の中心に合わせる)。
  var cx = 0, cy = 0, cz = 0;
  for (var i = 0; i < atomsIn.length; i++) {
    cx += atomsIn[i].x; cy += atomsIn[i].y; cz += atomsIn[i].z;
  }
  cx /= atomsIn.length; cy /= atomsIn.length; cz /= atomsIn.length;
  var atoms = atomsIn.map(function (a) {
    return { x: a.x - cx, y: a.y - cy, z: a.z - cz };
  });

  // --- クォータニオン([w, x, y, z]) ---
  function quatMultiply(a, b) {
    return [
      a[0] * b[0] - a[1] * b[1] - a[2] * b[2] - a[3] * b[3],
      a[0] * b[1] + a[1] * b[0] + a[2] * b[3] - a[3] * b[2],
      a[0] * b[2] - a[1] * b[3] + a[2] * b[0] + a[3] * b[1],
      a[0] * b[3] + a[1] * b[2] - a[2] * b[1] + a[3] * b[0],
    ];
  }
  function quatNormalize(q) {
    var n = Math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]) || 1;
    return [q[0] / n, q[1] / n, q[2] / n, q[3] / n];
  }
  function quatFromAxisAngle(axis, angle) {
    var len = Math.sqrt(axis[0] * axis[0] + axis[1] * axis[1] + axis[2] * axis[2]);
    if (len < 1e-9) return [1, 0, 0, 0];
    var half = angle / 2, s = Math.sin(half) / len;
    return [Math.cos(half), axis[0] * s, axis[1] * s, axis[2] * s];
  }
  function quatToMatrix(q) {
    var w = q[0], x = q[1], y = q[2], z = q[3];
    return [
      1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
      2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
      2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y),
    ];
  }

  // --- 状態 ---
  var rotation = [1, 0, 0, 0]; // 単位クォータニオン(初期角度はPython側で計算済みのためここは単位のまま)
  var scale = 55; // Å→pxの基準倍率(ホイールでズーム)
  var dragging = false, lastX = 0, lastY = 0, dirty = true;
  var GAP_PX = 3;

  function project() {
    var m = quatToMatrix(rotation);
    var w = container.clientWidth || 500, h = container.clientHeight || 500;
    return atoms.map(function (a) {
      var rx = m[0] * a.x + m[1] * a.y + m[2] * a.z;
      var ry = m[3] * a.x + m[4] * a.y + m[5] * a.z;
      var rz = m[6] * a.x + m[7] * a.y + m[8] * a.z;
      return { sx: rx * scale + w / 2, sy: -ry * scale + h / 2, depth: rz };
    });
  }

  // 2D線分p1-p2とp3-p4の交点をパラメトリックに解く。端点での接触(共有原子)は
  // 対象外にするため、0<t<1・0<u<1の厳密な内部交差のみを交点として扱う。
  function segIntersect(p1, p2, p3, p4) {
    var d1x = p2.sx - p1.sx, d1y = p2.sy - p1.sy;
    var d2x = p4.sx - p3.sx, d2y = p4.sy - p3.sy;
    var denom = d1x * d2y - d1y * d2x;
    if (Math.abs(denom) < 1e-9) return null;
    var dx = p3.sx - p1.sx, dy = p3.sy - p1.sy;
    var t = (dx * d2y - dy * d2x) / denom;
    var u = (dx * d1y - dy * d1x) / denom;
    if (t <= 0 || t >= 1 || u <= 0 || u >= 1) return null;
    return { t: t, u: u };
  }

  // 全結合ペアの交差を総当たりで調べ(結合数は数十〜百程度が想定なのでO(n^2)で十分)、
  // 奥にある結合(depthが小さい方)側にギャップを入れる位置(t値)を記録する。
  function computeSegmentsWithGaps(projected) {
    var n = bonds.length;
    var depths = bonds.map(function (b) {
      return (projected[b.begin].depth + projected[b.end].depth) / 2;
    });
    var cuts = bonds.map(function () { return []; });

    for (var i = 0; i < n; i++) {
      for (var j = i + 1; j < n; j++) {
        var bi = bonds[i], bj = bonds[j];
        if (bi.begin === bj.begin || bi.begin === bj.end ||
            bi.end === bj.begin || bi.end === bj.end) continue; // 端点共有は無視
        var hit = segIntersect(projected[bi.begin], projected[bi.end], projected[bj.begin], projected[bj.end]);
        if (!hit) continue;
        if (depths[i] < depths[j]) cuts[i].push(hit.t);
        else if (depths[j] < depths[i]) cuts[j].push(hit.u);
      }
    }

    var pieces = [];
    for (var k = 0; k < n; k++) {
      var b = bonds[k];
      var p1 = projected[b.begin], p2 = projected[b.end];
      var len = Math.hypot(p2.sx - p1.sx, p2.sy - p1.sy) || 1;
      var halfGapT = (GAP_PX / len) / 2;
      var ranges = [[0, 1]];
      var ts = cuts[k].slice().sort(function (a, c) { return a - c; });
      for (var m = 0; m < ts.length; m++) {
        var lo = ts[m] - halfGapT, hi = ts[m] + halfGapT;
        var next = [];
        for (var r = 0; r < ranges.length; r++) {
          var s = ranges[r][0], e = ranges[r][1];
          if (hi <= s || lo >= e) { next.push([s, e]); continue; }
          if (lo > s) next.push([s, Math.max(s, lo)]);
          if (hi < e) next.push([Math.min(e, hi), e]);
        }
        ranges = next.filter(function (se) { return se[1] - se[0] > 1e-4; });
      }
      for (var q = 0; q < ranges.length; q++) {
        var s2 = ranges[q][0], e2 = ranges[q][1];
        pieces.push({
          x1: p1.sx + (p2.sx - p1.sx) * s2, y1: p1.sy + (p2.sy - p1.sy) * s2,
          x2: p1.sx + (p2.sx - p1.sx) * e2, y2: p1.sy + (p2.sy - p1.sy) * e2,
          order: b.order,
        });
      }
    }
    return pieces;
  }

  function render() {
    var w = container.clientWidth || 500, h = container.clientHeight || 500;
    var projected = project();
    var pieces = computeSegmentsWithGaps(projected);
    var svg = '<svg width="' + w + '" height="' + h + '" xmlns="http://www.w3.org/2000/svg">';
    svg += '<rect width="' + w + '" height="' + h + '" fill="white"/>';
    for (var i = 0; i < pieces.length; i++) {
      var seg = pieces[i];
      var dx = seg.x2 - seg.x1, dy = seg.y2 - seg.y1;
      var len = Math.hypot(dx, dy) || 1;
      var nx = -dy / len, ny = dx / len;
      var order = Math.round(seg.order);
      var offsets = order <= 1 ? [0] : (order === 2 ? [-1.3, 1.3] : [-2.6, 0, 2.6]);
      for (var o = 0; o < offsets.length; o++) {
        var ox = nx * offsets[o], oy = ny * offsets[o];
        svg += '<line x1="' + (seg.x1 + ox) + '" y1="' + (seg.y1 + oy) +
               '" x2="' + (seg.x2 + ox) + '" y2="' + (seg.y2 + oy) +
               '" stroke="black" stroke-width="1.6" stroke-linecap="round"/>';
      }
    }
    svg += "</svg>";
    container.innerHTML = svg;
  }

  container.addEventListener("mousedown", function (e) {
    dragging = true; lastX = e.clientX; lastY = e.clientY;
  });
  window.addEventListener("mousemove", function (e) {
    if (!dragging) return;
    var dx = e.clientX - lastX, dy = e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY;
    var dist = Math.sqrt(dx * dx + dy * dy);
    if (dist > 0) {
      var angle = dist * 0.008;
      var qDelta = quatFromAxisAngle([-dy, dx, 0], angle);
      rotation = quatNormalize(quatMultiply(qDelta, rotation));
      dirty = true;
    }
  });
  window.addEventListener("mouseup", function () { dragging = false; });
  container.addEventListener("wheel", function (e) {
    scale *= Math.pow(1.0015, -e.deltaY);
    scale = Math.max(8, Math.min(400, scale));
    dirty = true;
    e.preventDefault();
  }, { passive: false });
  window.addEventListener("resize", function () { dirty = true; });

  function loop() {
    if (dirty) { render(); dirty = false; }
    window.requestAnimationFrame(loop);
  }
  loop();
})();
"""

_HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body {{ margin: 0; padding: 0; height: 100%; background: #ffffff; overflow: hidden; }}
  #viewer {{ width: 100%; height: 100%; cursor: grab; }}
  #viewer:active {{ cursor: grabbing; }}
</style>
</head>
<body>
<div id="viewer"></div>
<script>
window.__MOLWEIGH_ATOMS__ = {atoms_json};
window.__MOLWEIGH_BONDS__ = {bonds_json};
</script>
<script>
{lineart_js}
</script>
</body>
</html>
"""


class MoleculeLineArtWebView(QWidget):
    """ChemDraw風の線画3Dビューア本体。読み取り専用(2D構造には反映しない)。"""

    def __init__(self, molecule: LineArtMolecule, parent: QWidget | None = None):
        super().__init__(parent)

        atoms_json = json.dumps([{"x": a.x, "y": a.y, "z": a.z} for a in molecule.atoms])
        bonds_json = json.dumps(
            [{"begin": b.begin, "end": b.end, "order": b.order} for b in molecule.bonds]
        )
        html = _HTML_TEMPLATE.format(atoms_json=atoms_json, bonds_json=bonds_json, lineart_js=_LINEART_JS)

        self._view = QWebEngineView(self)
        self._view.setHtml(html)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)


class MoleculeLineArtWebDialog(QDialog):
    """`MoleculeLineArtWebView` を包む読み取り専用のプレビューダイアログ。"""

    def __init__(self, molecule: LineArtMolecule, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("3Dプレビュー")
        self.resize(600, 600)

        hint_label = QLabel("ドラッグで回転、ホイールでズームできます(2D構造には反映されません)。")
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")

        self._view = MoleculeLineArtWebView(molecule, self)

        close_button = QPushButton("閉じる")
        close_button.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(hint_label)
        layout.addWidget(self._view, 1)
        layout.addWidget(close_button)
