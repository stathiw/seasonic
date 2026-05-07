import sys
import os
import numpy as np
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QLabel, QSizePolicy, QFileDialog, QMessageBox,
    QComboBox,
)
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QImage, QPixmap, QPainter, QKeySequence, QShortcut, QPen, QColor, QFont

from s7k_parser import S7KFile

SPEED_OF_SOUND = 1500.0

COLORMAP_NAMES = ['Grayscale', 'viridis', 'cividis', 'copper', 'ocean']

def _build_lut(name):
    from matplotlib import colormaps
    cmap = colormaps[name]
    lut = (cmap(np.linspace(0, 1, 256))[:, :3] * 255).astype(np.uint8)
    lut[0] = 0
    return lut

COLORMAPS = {name: _build_lut(name) for name in COLORMAP_NAMES if name != 'Grayscale'}


class SonarWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._pixmap = None
        self._scale_info = None
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(400, 300)

    def set_image(self, data, scale_info=None):
        self._scale_info = scale_info
        if data is None:
            self._pixmap = None
            self.update()
            return

        display = np.ascontiguousarray(data)
        if display.ndim == 3:
            h, w, _ = display.shape
            qimg = QImage(display.data, w, h, w * 3, QImage.Format_RGB888)
        else:
            h, w = display.shape
            qimg = QImage(display.data, w, h, w, QImage.Format_Grayscale8)
        self._pixmap = QPixmap.fromImage(qimg)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(30, 30, 30))

        if self._pixmap is None:
            return

        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        if self._scale_info:
            mode = self._scale_info['mode']
            if mode == 'rect':
                ml, mt, mr, mb = 50, 5, 5, 25
            else:
                ml, mt, mr, mb = 5, 5, 30, 15
        else:
            ml, mt, mr, mb = 0, 0, 0, 0

        avail_w = self.width() - ml - mr
        avail_h = self.height() - mt - mb

        scaled = self._pixmap.scaled(avail_w, avail_h, Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation)
        ix = ml + (avail_w - scaled.width()) // 2
        iy = mt + (avail_h - scaled.height()) // 2
        iw = scaled.width()
        ih = scaled.height()

        painter.drawPixmap(ix, iy, scaled)

        if self._scale_info:
            if self._scale_info['mode'] == 'rect':
                self._draw_rect_scale(painter, ix, iy, iw, ih)
            else:
                self._draw_fan_scale(painter, ix, iy, iw, ih)

    @staticmethod
    def _nice_interval(max_val, target_ticks=5):
        if max_val <= 0:
            return 1
        rough = max_val / target_ticks
        mag = 10 ** int(np.floor(np.log10(rough)))
        for step in [1, 2, 5, 10]:
            if mag * step >= rough:
                return mag * step
        return mag * 10

    @staticmethod
    def _symmetric_ticks(half, step):
        ticks = {0.0}
        a = step
        while a <= half + 0.01:
            ticks.add(round(a, 2))
            ticks.add(round(-a, 2))
            a += step
        return sorted(a for a in ticks if abs(a) <= half + 0.01)

    @staticmethod
    def _format_range(r_m):
        return f"{int(r_m)}m" if r_m % 1 == 0 else f"{r_m:.1f}m"

    def _draw_rect_scale(self, painter, ix, iy, iw, ih):
        info = self._scale_info
        max_range = info['max_range_m']
        swath_deg = np.degrees(info['swath_rad'])
        half_deg = swath_deg / 2

        pen = QPen(QColor(180, 180, 180))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setFont(QFont("monospace", 8))

        painter.drawRect(ix, iy, iw - 1, ih - 1)

        grid_pen = QPen(QColor(180, 180, 180, 80))
        grid_pen.setWidth(2)
        grid_pen.setStyle(Qt.DotLine)

        interval = self._nice_interval(max_range)
        r = 0.0
        while r <= max_range + 0.001:
            frac = r / max_range if max_range > 0 else 0
            y = iy + int(frac * (ih - 1))
            painter.setPen(pen)
            painter.drawLine(ix - 4, y, ix, y)
            painter.drawText(ix - 48, y - 7, 42, 14,
                             Qt.AlignRight | Qt.AlignVCenter,
                             self._format_range(r))
            if r > 0:
                painter.setPen(grid_pen)
                painter.drawLine(ix + 1, y, ix + iw - 2, y)
            r += interval

        angle_step = self._nice_interval(swath_deg, target_ticks=7)
        for a in self._symmetric_ticks(half_deg, angle_step):
            frac = (a + half_deg) / swath_deg
            x = ix + int(frac * (iw - 1))
            painter.setPen(pen)
            painter.drawLine(x, iy + ih - 1, x, iy + ih + 3)
            label = f"{a:+.0f}°" if a != 0 else "0°"
            painter.drawText(x - 20, iy + ih + 4, 40, 14,
                             Qt.AlignCenter, label)
            painter.setPen(grid_pen)
            painter.drawLine(x, iy + 1, x, iy + ih - 2)

    def _draw_fan_scale(self, painter, ix, iy, iw, ih):
        info = self._scale_info
        max_range = info['max_range_m']
        swath = info['swath_rad']
        half = swath / 2
        half_deg = np.degrees(half)
        n_samples = info['n_samples']
        fan_img_h = info['fan_img_h']
        fx, fy = info['fan_origin_frac']

        ox = ix + fx * iw
        oy = iy + fy * ih
        scale = ih / fan_img_h
        max_r_px = n_samples * scale

        painter.save()
        painter.setClipRect(ix, iy, iw, ih)

        arc_pen = QPen(QColor(220, 220, 220, 180))
        arc_pen.setWidth(2)

        radial_pen = QPen(QColor(220, 220, 220, 100))
        radial_pen.setWidth(2)
        radial_pen.setStyle(Qt.DashLine)

        start_angle_16 = int((270 - half_deg) * 16)
        span_angle_16 = int(2 * half_deg * 16)

        interval = self._nice_interval(max_range)
        r_m = interval
        while r_m < max_range - 0.001:
            r_px = (r_m / max_range) * max_r_px
            rect = QRectF(ox - r_px, oy - r_px, 2 * r_px, 2 * r_px)
            painter.setPen(arc_pen)
            painter.drawArc(rect, start_angle_16, span_angle_16)
            r_m += interval

        angle_step = self._nice_interval(np.degrees(swath), target_ticks=7)
        angle_ticks = self._symmetric_ticks(half_deg, angle_step)

        for a_deg in angle_ticks:
            a_rad = np.radians(a_deg)
            ex = ox + max_r_px * np.sin(a_rad)
            ey = oy + max_r_px * np.cos(a_rad)
            painter.setPen(radial_pen)
            painter.drawLine(QPointF(ox, oy), QPointF(ex, ey))

        painter.restore()

        painter.setFont(QFont("monospace", 8))
        shadow = QColor(0, 0, 0, 200)
        fg = QColor(220, 220, 220)

        r_m = interval
        while r_m < max_range - 0.001:
            r_px = (r_m / max_range) * max_r_px
            lx = int(ox + r_px * np.sin(half)) + 2
            ly = int(oy + r_px * np.cos(half))
            label = self._format_range(r_m)
            painter.setPen(shadow)
            painter.drawText(lx + 1, ly + 1, label)
            painter.setPen(fg)
            painter.drawText(lx, ly, label)
            r_m += interval

        for a_deg in angle_ticks:
            a_rad = np.radians(a_deg)
            lx = ox + (max_r_px + 3) * np.sin(a_rad)
            ly = oy + (max_r_px + 3) * np.cos(a_rad)
            label = f"{a_deg:+.0f}°" if a_deg != 0 else "0°"
            painter.setPen(shadow)
            painter.drawText(int(lx) - 14, int(ly) + 1, 30, 14,
                             Qt.AlignCenter, label)
            painter.setPen(fg)
            painter.drawText(int(lx) - 15, int(ly), 30, 14,
                             Qt.AlignCenter, label)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.s7k = None
        self.current_frame = 0
        self.playing = False
        self.playback_fps = 10
        self.fan_mode = False
        self._colormap_name = 'Grayscale'
        self._fan_map = None
        self._fan_map_key = None

        self.setWindowTitle("Seasonic")

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.btn_open = QPushButton("Open")
        self.btn_open.setFixedWidth(60)
        self.btn_open.clicked.connect(self.open_file)
        toolbar.addWidget(self.btn_open)

        self.btn_view = QPushButton("Fan")
        self.btn_view.setFixedWidth(50)
        self.btn_view.clicked.connect(self.toggle_view)
        toolbar.addWidget(self.btn_view)

        self.btn_screenshot = QPushButton("Screenshot")
        self.btn_screenshot.setFixedWidth(90)
        self.btn_screenshot.clicked.connect(self.save_screenshot)
        toolbar.addWidget(self.btn_screenshot)

        self.cmap_combo = QComboBox()
        self.cmap_combo.addItems(COLORMAP_NAMES)
        self.cmap_combo.setFixedWidth(100)
        self.cmap_combo.currentTextChanged.connect(self.change_colormap)
        toolbar.addWidget(self.cmap_combo)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.sonar_widget = SonarWidget()
        layout.addWidget(self.sonar_widget, stretch=1)

        playback = QHBoxLayout()
        playback.setSpacing(8)

        self.btn_prev = QPushButton("◀")
        self.btn_prev.setFixedWidth(40)
        self.btn_prev.clicked.connect(self.step_back)
        playback.addWidget(self.btn_prev)

        self.btn_play = QPushButton("Play")
        self.btn_play.setFixedWidth(60)
        self.btn_play.clicked.connect(self.toggle_play)
        playback.addWidget(self.btn_play)

        self.btn_next = QPushButton("▶")
        self.btn_next.setFixedWidth(40)
        self.btn_next.clicked.connect(self.step_forward)
        playback.addWidget(self.btn_next)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(0)
        self.slider.valueChanged.connect(self.slider_changed)
        playback.addWidget(self.slider, stretch=1)

        self.frame_label = QLabel("No file loaded")
        self.frame_label.setFixedWidth(160)
        playback.addWidget(self.frame_label)

        layout.addLayout(playback)

        self.play_timer = QTimer()
        self.play_timer.timeout.connect(self.step_forward)

        QShortcut(QKeySequence(Qt.Key_Space), self, self.toggle_play)
        QShortcut(QKeySequence(Qt.Key_Right), self, self.step_forward)
        QShortcut(QKeySequence(Qt.Key_Left), self, self.step_back)
        QShortcut(QKeySequence(Qt.Key_Home), self, lambda: self.go_to_frame(0))
        QShortcut(QKeySequence(Qt.Key_End), self, lambda: self.go_to_frame(
            self.s7k.frame_count - 1 if self.s7k else 0))
        QShortcut(QKeySequence("Ctrl+O"), self, self.open_file)
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_screenshot)

        self.resize(1200, 800)

    def open_file(self):
        if self.playing:
            self.toggle_play()

        path, _ = QFileDialog.getOpenFileName(
            self, "Open S7K File", os.path.expanduser("~"),
            "S7K Files (*.s7k);;All Files (*)",
        )
        if not path:
            return

        self.load_file(path)

    def load_file(self, path):
        self.s7k = S7KFile(path)
        self.current_frame = 0

        if self.s7k.frame_count == 0:
            self.setWindowTitle("Seasonic")
            self.frame_label.setText("No frames found")
            self.slider.setMaximum(0)
            self.sonar_widget.set_image(None)
            return

        self.setWindowTitle(f"Seasonic — {os.path.basename(path)}")
        self.slider.setMaximum(self.s7k.frame_count - 1)
        self.show_frame(0)

    def _normalize(self, data):
        log_data = np.log1p(data.astype(np.float32))
        max_val = np.percentile(log_data, 99.5)
        if max_val > 0:
            normalized = np.clip(log_data / max_val, 0, 1)
        else:
            normalized = np.zeros_like(log_data)
        return (normalized * 255).astype(np.uint8)

    def show_frame(self, index):
        if not self.s7k or self.s7k.frame_count == 0:
            return

        index = max(0, min(index, self.s7k.frame_count - 1))
        self.current_frame = index

        frame = self.s7k.read_frame(index)
        if not frame:
            self.sonar_widget.set_image(None)
            self.frame_label.setText(f"Frame {index + 1}/{self.s7k.frame_count}")
        else:
            gray = self._normalize(frame.data)
            if self.fan_mode:
                display = self._apply_fan_projection(gray, self.s7k.swath_angle)
            else:
                display = gray.T
            display = self._apply_colormap(display)
            self.sonar_widget.set_image(display, self._build_scale_info(frame))
            self.frame_label.setText(
                f"Frame {index + 1}/{self.s7k.frame_count}"
                f"  Ping {frame.ping_number}")

        self.slider.blockSignals(True)
        self.slider.setValue(index)
        self.slider.blockSignals(False)

    def _build_scale_info(self, frame):
        if frame.sample_rate <= 0:
            return None
        swath = self.s7k.swath_angle if self.s7k.swath_angle else 2.0
        n_samples = frame.n_samples
        max_range_m = n_samples * SPEED_OF_SOUND / (2 * frame.sample_rate)
        if self.fan_mode and self._fan_map:
            out_h, out_w, _, _, _, cx, cy = self._fan_map
            return {
                'mode': 'fan',
                'max_range_m': max_range_m,
                'swath_rad': swath,
                'n_samples': n_samples,
                'fan_origin_frac': (cx / out_w, cy / out_h),
                'fan_img_h': out_h,
            }
        return {
            'mode': 'rect',
            'max_range_m': max_range_m,
            'swath_rad': swath,
        }

    def _apply_colormap(self, gray):
        lut = COLORMAPS.get(self._colormap_name)
        if lut is None:
            return gray
        return lut[gray]

    def change_colormap(self, name):
        self._colormap_name = name
        if self.s7k:
            self.show_frame(self.current_frame)

    def step_forward(self):
        if not self.s7k:
            return
        if self.current_frame < self.s7k.frame_count - 1:
            self.show_frame(self.current_frame + 1)
        elif self.playing:
            self.toggle_play()

    def step_back(self):
        if not self.s7k:
            return
        if self.current_frame > 0:
            self.show_frame(self.current_frame - 1)

    def go_to_frame(self, index):
        self.show_frame(index)

    def slider_changed(self, value):
        self.show_frame(value)

    def toggle_view(self):
        self.fan_mode = not self.fan_mode
        self.btn_view.setText("Rect" if self.fan_mode else "Fan")
        self._fan_map = None
        self._fan_map_key = None
        if self.s7k:
            self.show_frame(self.current_frame)

    def _build_fan_map(self, n_beams, n_samples, swath):
        half = swath / 2.0
        sin_half = np.sin(half)
        cos_half = np.cos(half)

        y_min = min(0.0, n_samples * cos_half)
        out_h = int(np.ceil(n_samples - y_min)) + 2
        out_w = int(np.ceil(2 * n_samples * sin_half)) + 2

        cx = out_w / 2.0
        cy = -y_min + 1.0

        ys, xs = np.mgrid[0:out_h, 0:out_w]
        dx = xs - cx
        dy = ys - cy
        r = np.sqrt(dx * dx + dy * dy)
        theta = np.arctan2(dx, dy)

        r_idx = r.astype(np.int32)
        beam_idx = ((theta + half) / swath * (n_beams - 1)).astype(np.int32)

        valid = ((r_idx >= 0) & (r_idx < n_samples) &
                 (beam_idx >= 0) & (beam_idx < n_beams) &
                 (np.abs(theta) <= half))

        self._fan_map = (out_h, out_w, beam_idx, r_idx, valid, cx, cy)
        self._fan_map_key = (n_beams, n_samples, swath)

    def _apply_fan_projection(self, gray, swath_angle):
        n_beams, n_samples = gray.shape
        swath = swath_angle if swath_angle else 2.0
        key = (n_beams, n_samples, swath)
        if self._fan_map is None or self._fan_map_key != key:
            self._build_fan_map(n_beams, n_samples, swath)
        out_h, out_w, beam_idx, r_idx, valid, _, _ = self._fan_map
        out = np.zeros((out_h, out_w), dtype=np.uint8)
        out[valid] = gray[beam_idx[valid], r_idx[valid]]
        return out

    def save_screenshot(self):
        if self.sonar_widget._pixmap is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Screenshot",
            os.path.expanduser("~/Pictures/screenshot.png"),
            "PNG (*.png);;JPEG (*.jpg);;All Files (*)",
        )
        if path:
            img = self.sonar_widget.grab().toImage()
            ext = os.path.splitext(path)[1].lower()
            fmt = "JPEG" if ext in (".jpg", ".jpeg") else "PNG"
            if not img.save(path, fmt):
                QMessageBox.warning(self, "Screenshot",
                                    f"Failed to save: {path}")

    def toggle_play(self):
        if not self.s7k:
            return
        self.playing = not self.playing
        if self.playing:
            self.btn_play.setText("Pause")
            self.play_timer.start(1000 // self.playback_fps)
        else:
            self.btn_play.setText("Play")
            self.play_timer.stop()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Seasonic")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
