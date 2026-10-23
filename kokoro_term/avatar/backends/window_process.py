from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from kokoro_term.avatar.animation import AnimationEngine
from kokoro_term.avatar.compositor import AvatarCompositor


class PySideAvatarWidget(QWidget):
    """Frameless, transparent, draggable 2D animated avatar window."""

    def __init__(self, avatar_dir: str | Path, parent=None):
        super().__init__(parent)
        self.avatar_dir = Path(avatar_dir)
        self.compositor = AvatarCompositor(self.avatar_dir, target_size=(420, 420))
        self.animation = AnimationEngine()

        # Frameless and transparent window configuration
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SubWindow
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self.setFixedSize(420, 420)
        self._drag_pos = QPoint()

        # Animation timer (24 FPS max)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_animation_tick)
        self.timer.start(41) # ~24 FPS

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def on_animation_tick(self):
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        now = time.time()
        state = self.animation.update(now)
        frame = self.compositor.composite(state)

        # Convert PIL Image to QPixmap
        data = frame.tobytes("raw", "RGBA")
        qimage = QImage(data, frame.width, frame.height, QImage.Format.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimage)

        painter.drawPixmap(0, 0, pixmap)


def run_ipc_server(avatar_widget: PySideAvatarWidget, port: int):
    """Listen for JSON control messages from the main kokoro-term process."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", port))
    server.listen(1)

    while True:
        try:
            conn, _ = server.accept()
            with conn:
                f = conn.makefile("r", encoding="utf-8")
                for line in f:
                    if not line:
                        break
                    try:
                        msg = json.loads(line.strip())
                        msg_type = msg.get("type")
                        val = msg.get("value")

                        if msg_type == "emotion" and isinstance(val, str):
                            avatar_widget.animation.set_emotion(val)
                        elif msg_type == "speaking":
                            avatar_widget.animation.set_speaking(bool(val))
                        elif msg_type == "mouth" and isinstance(val, str):
                            avatar_widget.animation.set_mouth_shape(val)
                        elif msg_type == "mouth_level" and isinstance(val, (int, float)):
                            avatar_widget.animation.set_mouth_level(float(val))
                        elif msg_type == "character" and isinstance(val, str):
                            new_dir = Path("characters") / val / "avatar"
                            if new_dir.exists():
                                avatar_widget.compositor = AvatarCompositor(new_dir, target_size=(420, 420))
                    except Exception:
                        pass
        except Exception:
            time.sleep(0.5)


def main():
    parser = argparse.ArgumentParser(description="Kokoro-Term 2D Avatar Window Process")
    parser.add_argument("--port", type=int, default=18492, help="IPC TCP port")
    parser.add_argument("--avatar-dir", type=str, default="characters/roxy/avatar", help="Avatar directory")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    widget = PySideAvatarWidget(avatar_dir=args.avatar_dir)
    widget.show()

    # Start IPC listener in background thread
    ipc_thread = threading.Thread(target=run_ipc_server, args=(widget, args.port), daemon=True)
    ipc_thread.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
