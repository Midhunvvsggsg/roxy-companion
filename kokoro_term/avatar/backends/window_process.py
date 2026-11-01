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
        self.roam_enabled: bool = True
        self._is_dragging: bool = False
        self._wander_dir: int = 1

        # Animation timer (24 FPS max)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_animation_tick)
        self.timer.start(41) # ~24 FPS

        # Gentle screen roaming / wander timer (every 18 seconds)
        self.roam_timer = QTimer(self)
        self.roam_timer.timeout.connect(self.on_roam_step)
        self.roam_timer.start(18000)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            # If clicked in upper head region, trigger head-pat reaction!
            pos_y = event.position().y()
            if pos_y < 180:
                import random
                reaction = random.choice(["blush", "happy", "smug"])
                self.animation.set_emotion(reaction)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._is_dragging = False
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def on_roam_step(self):
        """Gentle autonomous desktop pet roaming step across screen."""
        if not self.roam_enabled or self._is_dragging or self.animation.is_speaking:
            return

        screen = self.screen()
        if not screen:
            return
        geo = screen.geometry()
        cur_pos = self.pos()

        # Step 25-45 pixels in current wander direction
        step = 35 * self._wander_dir
        new_x = cur_pos.x() + step

        # Bounce if near screen boundaries
        if new_x <= geo.left() + 20:
            self._wander_dir = 1
            new_x = geo.left() + 30
        elif new_x + self.width() >= geo.right() - 20:
            self._wander_dir = -1
            new_x = geo.right() - self.width() - 30

        self.move(new_x, cur_pos.y())

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
                        elif msg_type == "pose" and isinstance(val, str):
                            avatar_widget.animation.set_pose(val)
                        elif msg_type == "roam":
                            avatar_widget.roam_enabled = bool(val)
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
