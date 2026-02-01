"""
Copyright 2026 [Rishi Franklin]

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QMdiSubWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QCheckBox,
    QSpinBox,
    QMenu,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
)

from qanopy.core.datastore import DataStore
from qanopy.core.session_manager import SessionManager


class EnumAxisItem(pg.AxisItem):
    """
    Render integer-valued ticks using DBC 'choices' when available.
    """
    def __init__(self, choices: Dict[int, str], *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._choices = {int(k): str(v) for k, v in choices.items()}

    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            try:
                fv = float(v)
                iv = int(round(fv))
                if abs(fv - float(iv)) < 1e-6 and iv in self._choices:
                    out.append(self._choices[iv])
                else:
                    out.append(f"{fv:g}")
            except Exception:
                out.append(str(v))
        return out


def _rand_dark_qcolor() -> QColor:
    """
    Random dark-ish QColor (avoid washed out lines).
    """
    import colorsys
    h = random.random()
    s = 0.75 + 0.25 * random.random()
    v = 0.30 + 0.25 * random.random()
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return QColor(int(r * 255), int(g * 255), int(b * 255))


@dataclass
class PlotChannel:
    key: str
    name: str
    plot: pg.PlotItem
    curve: pg.PlotDataItem

    unit: str = ""
    choices: Optional[Dict[int, str]] = None

    is_derived: bool = False
    src_a: Optional[str] = None
    src_b: Optional[str] = None

    # Style state (per-graph)
    line_color: Optional[QColor] = None
    bg_color: Optional[QColor] = None
    default_line_color: Optional[QColor] = None


class PlotStyleDialog(QDialog):
    def __init__(self, parent: QWidget, title: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Style: {title}")
        self.setModal(True)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.lbl = QLabel(title)
        self.lbl.setWordWrap(True)
        layout.addWidget(self.lbl)

        row = QHBoxLayout()
        self.btn_line = QPushButton("Set Line Color…")
        self.btn_bg = QPushButton("Set Background…")
        self.btn_reset = QPushButton("Reset Colors")
        row.addWidget(self.btn_line)
        row.addWidget(self.btn_bg)
        row.addWidget(self.btn_reset)
        row.addStretch(1)
        layout.addLayout(row)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        layout.addWidget(bb)

        # Callbacks assigned by owner
        self.on_line = None
        self.on_bg = None
        self.on_reset = None

        self.btn_line.clicked.connect(self._do_line)
        self.btn_bg.clicked.connect(self._do_bg)
        self.btn_reset.clicked.connect(self._do_reset)

    def _do_line(self) -> None:
        if callable(self.on_line):
            self.on_line()

    def _do_bg(self) -> None:
        if callable(self.on_bg):
            self.on_bg()

    def _do_reset(self) -> None:
        if callable(self.on_reset):
            self.on_reset()


class PlotStyleViewBox(pg.ViewBox):
    """
    Per-plot ViewBox that provides:
      - Right click menu: line/background controls
      - Double click: open style dialog
    """

    def __init__(self, owner: "PlotMdiSubWindow") -> None:
        super().__init__()
        self._owner = owner
        self._channel: Optional[PlotChannel] = None

    def set_channel(self, ch: PlotChannel) -> None:
        self._channel = ch

    def mouseDoubleClickEvent(self, ev) -> None:
        try:
            if ev.button() == Qt.MouseButton.LeftButton and self._channel is not None:
                self._owner.open_style_dialog(self._channel)
                ev.accept()
                return
        except Exception:
            pass
        super().mouseDoubleClickEvent(ev)

    def raiseContextMenu(self, ev) -> None:
        # Custom menu per graph
        if self._channel is None:
            return super().raiseContextMenu(ev)

        menu = QMenu()

        act_line = menu.addAction("Set Line Color…")
        act_bg = menu.addAction("Set Background Color…")
        menu.addSeparator()
        act_reset = menu.addAction("Reset Colors")

        try:
            pos = ev.screenPos()  # QPointF (Qt6)
            chosen = menu.exec(pos.toPoint())
        except Exception:
            chosen = None

        if chosen is None:
            return

        if chosen == act_line:
            self._owner.pick_line_color(self._channel)
        elif chosen == act_bg:
            self._owner.pick_bg_color(self._channel)
        elif chosen == act_reset:
            self._owner.reset_colors(self._channel)


class PlotMdiSubWindow(QMdiSubWindow):
    """
    Classic plotting behavior:
      - X axis is absolute time (no shifting).
      - Y axis can show DBC enum labels via EnumAxisItem.
      - Per-graph style controls (line + background).

    NEW:
      - Show values under cursor A/B (and ΔY for numeric signals).
    """

    def __init__(self, datastore: DataStore, sessions: SessionManager) -> None:
        super().__init__()
        self.setWindowTitle("Plots")

        self.datastore = datastore
        self.sessions = sessions

        self._channels: List[PlotChannel] = []
        self._paused = False
        self._snap_s = 0.0

        self._cursor_a_x = 0.0
        self._cursor_b_x = 0.0
        self._cursor_sync_guard = False

        # NEW: throttle UI updates of cursor readout (avoid UI churn at 20 Hz)
        self._readout_tick = 0

        root = QWidget()
        self.setWidget(root)

        layout = QVBoxLayout()
        root.setLayout(layout)

        # Controls
        top = QHBoxLayout()

        self.chk_pause = QCheckBox("Pause")
        self.chk_pause.stateChanged.connect(self._on_pause_changed)

        self.chk_grid = QCheckBox("Grid")
        self.chk_grid.setChecked(True)
        self.chk_grid.stateChanged.connect(self._apply_grid)

        self.sp_line = QSpinBox()
        self.sp_line.setRange(1, 10)
        self.sp_line.setValue(2)
        self.sp_line.valueChanged.connect(self._apply_line_width)

        self.sp_snap_ms = QSpinBox()
        self.sp_snap_ms.setRange(0, 5000)
        self.sp_snap_ms.setValue(0)
        self.sp_snap_ms.valueChanged.connect(self._on_snap_changed)

        self.btn_fit = QPushButton("Zoom to fit")
        self.btn_fit.clicked.connect(self._zoom_to_fit)

        self.lbl_cursor = QLabel("Cursor: -")

        top.addWidget(self.chk_pause)
        top.addSpacing(10)
        top.addWidget(QLabel("Line"))
        top.addWidget(self.sp_line)
        top.addSpacing(10)
        top.addWidget(QLabel("Snap (ms)"))
        top.addWidget(self.sp_snap_ms)
        top.addSpacing(10)
        top.addWidget(self.chk_grid)
        top.addSpacing(10)
        top.addWidget(self.btn_fit)
        top.addSpacing(10)
        top.addWidget(self.lbl_cursor)
        top.addStretch(1)

        layout.addLayout(top)

        # NEW: Cursor value readout label
        self.lbl_cursor_values = QLabel("Values @ Cursors: -")
        self.lbl_cursor_values.setWordWrap(True)
        layout.addWidget(self.lbl_cursor_values)

        self.glw = pg.GraphicsLayoutWidget()
        layout.addWidget(self.glw)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(50)

    # Public API
    def add_signal(self, signal_key: str, display_name: str) -> None:
        for ch in self._channels:
            if (not ch.is_derived) and ch.key == signal_key:
                return

        unit, choices = ("", None)
        try:
            unit, choices = self._resolve_dbc_meta(signal_key)
        except Exception:
            pass

        vb = PlotStyleViewBox(self)
        plot = self._create_plot(display_name, unit=unit, choices=choices, viewbox=vb)

        line_color = _rand_dark_qcolor()
        pen = pg.mkPen(color=line_color, width=int(self.sp_line.value()))
        curve = plot.plot([], [], pen=pen)
        curve.setClipToView(True)
        curve.setDownsampling(auto=True, method="peak")

        ch = PlotChannel(
            key=signal_key,
            name=display_name,
            plot=plot,
            curve=curve,
            unit=unit,
            choices=choices,
            is_derived=False,
            line_color=line_color,
            default_line_color=QColor(line_color),
            bg_color=None,
        )
        self._channels.append(ch)
        vb.set_channel(ch)

        self._apply_grid()
        self._install_cursors_for_plot(plot)

        # NEW: attempt to populate readout (even if data arrives later)
        self._update_cursor_value_readout()

    def add_derived_difference(self, a_key: str, a_name: str, b_key: str, b_name: str) -> None:
        name = f"DIFF: ({a_name}) - ({b_name})"

        vb = PlotStyleViewBox(self)
        plot = self._create_plot(name, unit="", choices=None, viewbox=vb)

        line_color = _rand_dark_qcolor()
        pen = pg.mkPen(color=line_color, width=int(self.sp_line.value()))
        curve = plot.plot([], [], pen=pen)
        curve.setClipToView(True)
        curve.setDownsampling(auto=True, method="peak")

        ch = PlotChannel(
            key=f"DIFF::{a_key}::{b_key}",
            name=name,
            plot=plot,
            curve=curve,
            is_derived=True,
            src_a=a_key,
            src_b=b_key,
            line_color=line_color,
            default_line_color=QColor(line_color),
            bg_color=None,
        )
        self._channels.append(ch)
        vb.set_channel(ch)

        self._apply_grid()
        self._install_cursors_for_plot(plot)

        # NEW: attempt to populate readout
        self._update_cursor_value_readout()

    # Plot creation
    def _create_plot(
        self,
        title: str,
        unit: str,
        choices: Optional[Dict[int, str]],
        viewbox: Optional[pg.ViewBox],
    ) -> pg.PlotItem:
        axis_items = {}
        if choices:
            axis_items["left"] = EnumAxisItem(choices=choices, orientation="left")

        plot = self.glw.addPlot(axisItems=axis_items, viewBox=viewbox)
        plot.setTitle(title)

        plot.setLabel("bottom", "Time (s)")
        if unit:
            plot.setLabel("left", unit)

        if self._channels:
            plot.setXLink(self._channels[0].plot)

        plot.showGrid(x=True, y=True, alpha=0.25)
        self.glw.nextRow()
        return plot

    # Per-graph style controls
    def open_style_dialog(self, ch: PlotChannel) -> None:
        dlg = PlotStyleDialog(self.widget(), ch.name)

        dlg.on_line = lambda: self.pick_line_color(ch)
        dlg.on_bg = lambda: self.pick_bg_color(ch)
        dlg.on_reset = lambda: self.reset_colors(ch)

        dlg.exec()

    def pick_line_color(self, ch: PlotChannel) -> None:
        initial = ch.line_color if ch.line_color is not None else _rand_dark_qcolor()
        c = QColorDialog.getColor(initial, self.widget(), f"Line Color: {ch.name}")
        if not c.isValid():
            return

        ch.line_color = QColor(c)
        w = int(self.sp_line.value())
        ch.curve.setPen(pg.mkPen(color=ch.line_color, width=w))

    def pick_bg_color(self, ch: PlotChannel) -> None:
        initial = ch.bg_color if ch.bg_color is not None else QColor(0, 0, 0)
        c = QColorDialog.getColor(initial, self.widget(), f"Background: {ch.name}")
        if not c.isValid():
            return

        ch.bg_color = QColor(c)
        try:
            ch.plot.getViewBox().setBackgroundColor(ch.bg_color)
        except Exception:
            # If this fails for any reason, keep state but avoid crashing
            pass

    def reset_colors(self, ch: PlotChannel) -> None:
        # Reset to original random line color, and dark background (black)
        if ch.default_line_color is None:
            ch.default_line_color = _rand_dark_qcolor()

        ch.line_color = QColor(ch.default_line_color)
        w = int(self.sp_line.value())
        ch.curve.setPen(pg.mkPen(color=ch.line_color, width=w))

        ch.bg_color = QColor(0, 0, 0)
        try:
            ch.plot.getViewBox().setBackgroundColor(ch.bg_color)
        except Exception:
            pass

    # Controls
    def _on_pause_changed(self) -> None:
        self._paused = self.chk_pause.isChecked()

    def _apply_grid(self) -> None:
        show = self.chk_grid.isChecked()
        for ch in self._channels:
            try:
                ch.plot.showGrid(x=show, y=show, alpha=0.25)
            except Exception:
                pass

    def _apply_line_width(self) -> None:
        w = int(self.sp_line.value())
        for ch in self._channels:
            try:
                color = ch.line_color if ch.line_color is not None else _rand_dark_qcolor()
                ch.curve.setPen(pg.mkPen(color=color, width=w))
            except Exception:
                pass

    def _on_snap_changed(self) -> None:
        ms = int(self.sp_snap_ms.value())
        self._snap_s = (ms / 1000.0) if ms > 0 else 0.0

        # NEW: snap current cursor positions immediately (so readout matches)
        self._cursor_a_x = self._apply_snap(self._cursor_a_x)
        self._cursor_b_x = self._apply_snap(self._cursor_b_x)
        self._sync_cursor_lines()
        self._update_cursor_value_readout()

    # Data fetch + refresh
    def _fetch_xy(self, key: str) -> Tuple[np.ndarray, np.ndarray]:
        ds = self.datastore
        for meth in ("get_series", "get_xy", "get_points", "get"):
            fn = getattr(ds, meth, None)
            if fn is None:
                continue
            try:
                out = fn(key)
            except Exception:
                continue
            if out is None:
                return np.array([]), np.array([])
            if isinstance(out, tuple) and len(out) == 2:
                x, y = out
                return np.asarray(x, dtype=float), np.asarray(y, dtype=float)
        return np.array([]), np.array([])

    def _refresh(self) -> None:
        if self._paused or not self._channels:
            return

        for ch in self._channels:
            if ch.is_derived:
                self._refresh_derived(ch)
            else:
                x, y = self._fetch_xy(ch.key)
                ch.curve.setData(x, y)

        self._sync_cursor_lines()

        # NEW: Throttled readout refresh so it stays correct as data grows
        self._readout_tick = (self._readout_tick + 1) & 0xFFFF
        if (self._readout_tick % 5) == 0:  # ~4 Hz at 20 Hz refresh
            self._update_cursor_value_readout()

    def _refresh_derived(self, ch: PlotChannel) -> None:
        if not ch.src_a or not ch.src_b:
            ch.curve.setData([], [])
            return

        xa, ya = self._fetch_xy(ch.src_a)
        xb, yb = self._fetch_xy(ch.src_b)

        if xa.size < 2 or xb.size < 2:
            ch.curve.setData([], [])
            return

        try:
            yb_i = np.interp(xa, xb, yb)
            yd = ya - yb_i
            ch.curve.setData(xa, yd)
        except Exception:
            ch.curve.setData([], [])

    # Zoom-to-fit
    def _zoom_to_fit(self) -> None:
        if not self._channels:
            return

        x_min = None
        x_max = None

        for ch in self._channels:
            data = ch.curve.getData()
            if not data:
                continue
            x, y = data
            if x is None or y is None or len(x) < 2:
                continue
            x_min = float(np.min(x)) if x_min is None else min(x_min, float(np.min(x)))
            x_max = float(np.max(x)) if x_max is None else max(x_max, float(np.max(x)))

        if x_min is not None and x_max is not None and x_max > x_min:
            try:
                self._channels[0].plot.setXRange(x_min, x_max, padding=0.02)
            except Exception:
                pass

        for ch in self._channels:
            try:
                data = ch.curve.getData()
                if not data:
                    continue
                x, y = data
                if y is None or len(y) < 2:
                    continue
                ymin = float(np.min(y))
                ymax = float(np.max(y))
                if abs(ymax - ymin) < 1e-12:
                    ymin -= 1.0
                    ymax += 1.0
                ch.plot.setYRange(ymin, ymax, padding=0.1)
            except Exception:
                continue

    # DBC meta
    def _resolve_dbc_meta(self, signal_key: str) -> Tuple[str, Optional[Dict[int, str]]]:
        parts = str(signal_key).split(":")
        if len(parts) < 4:
            return ("", None)

        sid = parts[0]
        dbc_key = parts[1]
        frame_id = int(parts[2])
        sig_name = ":".join(parts[3:])

        sess = self.sessions.get(sid)
        db = sess.dbcs.get_db(dbc_key)
        msg = db.get_message_by_frame_id(frame_id)
        sig = msg.get_signal_by_name(sig_name)

        unit = sig.unit or ""
        choices = dict(sig.choices) if getattr(sig, "choices", None) else None
        return (unit, choices)

    # Cursors (existing behavior)
    def _install_cursors_for_plot(self, plot: pg.PlotItem) -> None:
        line_a = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen(width=2))
        line_b = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen(style=Qt.PenStyle.DashLine, width=2))

        plot._pycan_cursor_a = line_a  # type: ignore[attr-defined]
        plot._pycan_cursor_b = line_b  # type: ignore[attr-defined]

        plot.addItem(line_a)
        plot.addItem(line_b)

        line_a.setPos(self._cursor_a_x)
        line_b.setPos(self._cursor_b_x)

        line_a.sigPositionChanged.connect(lambda: self._on_cursor_moved("A", plot))
        line_b.sigPositionChanged.connect(lambda: self._on_cursor_moved("B", plot))

    def _apply_snap(self, x: float) -> float:
        if self._snap_s <= 0.0:
            return x
        return round(float(x) / self._snap_s) * self._snap_s

    def _on_cursor_moved(self, which: str, src_plot: pg.PlotItem) -> None:
        if self._cursor_sync_guard:
            return
        try:
            if which == "A":
                x = float(src_plot._pycan_cursor_a.value())  # type: ignore[attr-defined]
                self._cursor_a_x = self._apply_snap(x)
                self.lbl_cursor.setText(f"Cursor [A]: {x:.3f}")
            else:
                x = float(src_plot._pycan_cursor_b.value())  # type: ignore[attr-defined]
                self._cursor_b_x = self._apply_snap(x)
                self.lbl_cursor.setText(f"Cursor [B]: {x:.3f}")
        except Exception:
            return

        self._sync_cursor_lines()
        dt_ms = abs(self._cursor_b_x - self._cursor_a_x) * 1000.0
        self.setWindowTitle(f"Plots  |  Δt={dt_ms:.3f} ms")

        # NEW: immediate readout refresh on cursor move
        self._update_cursor_value_readout()

    def _sync_cursor_lines(self) -> None:
        self._cursor_sync_guard = True
        try:
            for ch in self._channels:
                p = ch.plot
                if hasattr(p, "_pycan_cursor_a"):
                    p._pycan_cursor_a.setPos(self._cursor_a_x)  # type: ignore[attr-defined]
                    p._pycan_cursor_b.setPos(self._cursor_b_x)  # type: ignore[attr-defined]
        finally:
            self._cursor_sync_guard = False

    # ---------------- NEW: Cursor value readout ----------------

    def _y_at(self, x: np.ndarray, y: np.ndarray, xq: float) -> Optional[float]:
        """
        Get y-value at time xq. Uses interpolation if x is monotonic, otherwise nearest.
        Clamps to first/last sample outside range.
        """
        try:
            if x is None or y is None:
                return None
            x = np.asarray(x, dtype=float)
            y = np.asarray(y, dtype=float)
            if x.size < 1 or y.size < 1:
                return None
            if x.size == 1:
                return float(y[0])

            # If not monotonic increasing, fallback to nearest point
            if np.any(np.diff(x) < 0):
                idx = int(np.argmin(np.abs(x - float(xq))))
                return float(y[idx])

            if float(xq) <= float(x[0]):
                return float(y[0])
            if float(xq) >= float(x[-1]):
                return float(y[-1])

            return float(np.interp(float(xq), x, y))
        except Exception:
            return None

    def _fmt_value(self, ch: PlotChannel, v: Optional[float]) -> str:
        if v is None:
            return "-"

        # categorical / enum
        if ch.choices:
            try:
                iv = int(round(float(v)))
                lbl = ch.choices.get(iv, None)
                if lbl is not None:
                    return f"{lbl} ({iv})"
                return f"{iv}"
            except Exception:
                return str(v)

        # numeric
        try:
            fv = float(v)
            if ch.unit:
                return f"{fv:.6g} {ch.unit}"
            return f"{fv:.6g}"
        except Exception:
            return str(v)

    def _fmt_delta(self, ch: PlotChannel, a: Optional[float], b: Optional[float]) -> str:
        if a is None or b is None:
            return ""
        if ch.choices:
            return ""  # Δ doesn't mean anything for enums
        try:
            dv = float(b) - float(a)
            if ch.unit:
                return f"{dv:.6g} {ch.unit}"
            return f"{dv:.6g}"
        except Exception:
            return ""

    def _value_pair_for_channel(self, ch: PlotChannel, xa: float, xb: float) -> Tuple[Optional[float], Optional[float]]:
        """
        Returns (value_at_A, value_at_B) for channel, using datastore series
        so it works regardless of pyqtgraph downsampling/clipping.
        """
        if ch.is_derived:
            if not ch.src_a or not ch.src_b:
                return (None, None)

            x1, y1 = self._fetch_xy(ch.src_a)
            x2, y2 = self._fetch_xy(ch.src_b)
            if x1.size < 1 or x2.size < 1:
                return (None, None)

            a1 = self._y_at(x1, y1, xa)
            b1 = self._y_at(x1, y1, xb)
            a2 = self._y_at(x2, y2, xa)
            b2 = self._y_at(x2, y2, xb)

            va = (a1 - a2) if (a1 is not None and a2 is not None) else None
            vb = (b1 - b2) if (b1 is not None and b2 is not None) else None
            return (va, vb)

        x, y = self._fetch_xy(ch.key)
        if x.size < 1:
            return (None, None)
        return (self._y_at(x, y, xa), self._y_at(x, y, xb))

    def _update_cursor_value_readout(self) -> None:
        if not self._channels:
            self.lbl_cursor_values.setText("Values @ Cursors: -")
            return

        xa = float(self._cursor_a_x)
        xb = float(self._cursor_b_x)

        lines: List[str] = []
        MAX_LINES = 12

        # show values for all stacked plots
        for ch in self._channels[:MAX_LINES]:
            va, vb = self._value_pair_for_channel(ch, xa, xb)

            a_txt = self._fmt_value(ch, va)
            b_txt = self._fmt_value(ch, vb)
            d_txt = self._fmt_delta(ch, va, vb)

            if d_txt:
                lines.append(f"{ch.name}:  A={a_txt}   B={b_txt}   Δ={d_txt}")
            else:
                lines.append(f"{ch.name}:  A={a_txt}   B={b_txt}")

        if len(self._channels) > MAX_LINES:
            lines.append(f"... ({len(self._channels) - MAX_LINES} more)")

        if not lines:
            self.lbl_cursor_values.setText("Values @ Cursors: -")
            return

        self.lbl_cursor_values.setText("\n".join(lines))

    # Cleanup
    def closeEvent(self, event) -> None:
        try:
            self._timer.stop()
        except Exception:
            pass
        super().closeEvent(event)
