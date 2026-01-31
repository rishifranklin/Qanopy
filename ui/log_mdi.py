from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMdiSubWindow, QWidget, QVBoxLayout, QTextEdit, QLabel

from qanopy.core.logger import CanFrameLogger


class LogMdiSubWindow(QMdiSubWindow):
    def __init__(self, logger: CanFrameLogger) -> None:
        super().__init__()
        self.setWindowTitle("Log Viewer (recent frames)")
        self.logger = logger

        root = QWidget()
        self.setWidget(root)
        layout = QVBoxLayout()
        root.setLayout(layout)

        self.txt = QTextEdit()
        self.txt.setReadOnly(True)

        self.lbl = QLabel("Shows recent frames captured (ring buffer).")
        layout.addWidget(self.lbl)
        layout.addWidget(self.txt)

        self.timer = QTimer()
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._refresh)
        self.timer.start()

    def _refresh(self) -> None:
        lines = self.logger.get_recent_lines(200)
        self.txt.setPlainText("\n".join(lines))
        self.txt.verticalScrollBar().setValue(self.txt.verticalScrollBar().maximum())
