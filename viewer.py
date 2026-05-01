import sys
import os
import numpy as np
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QLabel, QSizePolicy, QFileDialog,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap, QPainter, QKeySequence, QShortcut

from s7k_parser import S7KFile


class SonarWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._pixmap = None
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(400, 300)

    def set_image(self, gray_2d):
        if gray_2d is None:
            self._pixmap = None
            self.update()
            return

        display = np.ascontiguousarray(gray_2d)
        h, w = display.shape
        qimg = QImage(display.data, w, h, w, QImage.Format_Grayscale8)
        self._pixmap = QPixmap.fromImage(qimg)
        self.update()

    def paintEvent(self, event):
        if self._pixmap is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        scaled = self._pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.s7k = None
        self.current_frame = 0
        self.playing = False
        self.playback_fps = 10

        self.setWindowTitle("Seasonic")

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)

        self.sonar_widget = SonarWidget()
        layout.addWidget(self.sonar_widget, stretch=1)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.btn_open = QPushButton("Open")
        self.btn_open.setFixedWidth(60)
        self.btn_open.clicked.connect(self.open_file)
        controls.addWidget(self.btn_open)

        self.btn_prev = QPushButton("◀")
        self.btn_prev.setFixedWidth(40)
        self.btn_prev.clicked.connect(self.step_back)
        controls.addWidget(self.btn_prev)

        self.btn_play = QPushButton("Play")
        self.btn_play.setFixedWidth(60)
        self.btn_play.clicked.connect(self.toggle_play)
        controls.addWidget(self.btn_play)

        self.btn_next = QPushButton("▶")
        self.btn_next.setFixedWidth(40)
        self.btn_next.clicked.connect(self.step_forward)
        controls.addWidget(self.btn_next)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(0)
        self.slider.valueChanged.connect(self.slider_changed)
        controls.addWidget(self.slider, stretch=1)

        self.frame_label = QLabel("No file loaded")
        self.frame_label.setFixedWidth(160)
        controls.addWidget(self.frame_label)

        layout.addLayout(controls)

        self.play_timer = QTimer()
        self.play_timer.timeout.connect(self.step_forward)

        QShortcut(QKeySequence(Qt.Key_Space), self, self.toggle_play)
        QShortcut(QKeySequence(Qt.Key_Right), self, self.step_forward)
        QShortcut(QKeySequence(Qt.Key_Left), self, self.step_back)
        QShortcut(QKeySequence(Qt.Key_Home), self, lambda: self.go_to_frame(0))
        QShortcut(QKeySequence(Qt.Key_End), self, lambda: self.go_to_frame(
            self.s7k.frame_count - 1 if self.s7k else 0))
        QShortcut(QKeySequence("Ctrl+O"), self, self.open_file)

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
            self.sonar_widget.set_image(gray.T)
            self.frame_label.setText(
                f"Frame {index + 1}/{self.s7k.frame_count}"
                f"  Ping {frame.ping_number}")

        self.slider.blockSignals(True)
        self.slider.setValue(index)
        self.slider.blockSignals(False)

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
