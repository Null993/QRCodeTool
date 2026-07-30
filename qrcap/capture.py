from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget


class _ScreenOverlay(QWidget):
    """One native overlay per screen to avoid mixed-DPI spanning failures."""

    def __init__(
        self,
        controller: "CaptureScreen",
        geometry: QRect,
        capture: QPixmap,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.screen_geometry = QRect(geometry)
        self.capture = capture
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(self.screen_geometry)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.capture, self.capture.rect())

        selection = self.controller.selection_rect
        intersection = selection.intersected(self.screen_geometry)
        if not intersection.isEmpty():
            local = intersection.translated(-self.screen_geometry.topLeft())
            painter.setPen(QPen(QColor(0, 180, 255), 3))
            painter.drawRect(local)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.grabMouse()
            self.controller.begin_selection(
                event.globalPosition().toPoint(),
                self,
            )

    def mouseMoveEvent(self, event) -> None:
        if self.controller.selecting:
            self.controller.update_selection(
                event.globalPosition().toPoint()
            )

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if QWidget.mouseGrabber() is self:
                self.releaseMouse()
            self.controller.finish_selection(
                event.globalPosition().toPoint()
            )

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.controller.cancel()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        if not self.controller.closing and not self.controller.finished:
            QTimer.singleShot(0, self.controller.cancel)
        super().closeEvent(event)


class CaptureScreen(QObject):
    """Coordinated per-screen overlays with cross-monitor selection."""

    def __init__(self, callback, cancel_callback=None):
        super().__init__()
        self.callback = callback
        self.cancel_callback = cancel_callback
        self.start = QPoint()
        self.end = QPoint()
        self.selecting = False
        self.finished = False
        self.closing = False
        self.mouse_overlay: _ScreenOverlay | None = None

        self.screen_captures: list[tuple[QRect, QPixmap]] = []
        for screen in QGuiApplication.screens():
            self.screen_captures.append(
                (QRect(screen.geometry()), screen.grabWindow(0))
            )

        self.overlays = [
            _ScreenOverlay(self, geometry, capture)
            for geometry, capture in self.screen_captures
        ]

    @property
    def selection_rect(self) -> QRect:
        if not self.selecting and self.start == self.end:
            return QRect()
        return QRect(self.start, self.end).normalized()

    def show(self) -> None:
        for overlay in self.overlays:
            overlay.setGeometry(overlay.screen_geometry)
            overlay.show()
            overlay.raise_()

    def raise_(self) -> None:
        for overlay in self.overlays:
            overlay.raise_()

    def activateWindow(self) -> None:
        cursor_position = QCursor.pos()
        target = next(
            (
                overlay
                for overlay in self.overlays
                if overlay.screen_geometry.contains(cursor_position)
            ),
            self.overlays[0] if self.overlays else None,
        )
        if target is not None:
            target.activateWindow()
            target.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def begin_selection(
        self,
        global_position: QPoint,
        overlay: _ScreenOverlay,
    ) -> None:
        self.start = global_position
        self.end = global_position
        self.selecting = True
        self.mouse_overlay = overlay
        self._update_overlays()

    def update_selection(self, global_position: QPoint) -> None:
        self.end = global_position
        self._update_overlays()

    def finish_selection(self, global_position: QPoint) -> None:
        if not self.selecting or self.finished:
            return
        self.end = global_position
        self.selecting = False
        global_rect = QRect(self.start, self.end).normalized()
        if global_rect.width() <= 5 or global_rect.height() <= 5:
            self.cancel()
            return

        cropped = self._compose_selection(
            self.screen_captures,
            global_rect,
        )
        self.finished = True
        self._close_overlays()
        QTimer.singleShot(0, lambda pixmap=cropped: self.callback(pixmap))

    def cancel(self) -> None:
        if self.finished:
            return
        self.finished = True
        if self.mouse_overlay is not None:
            try:
                self.mouse_overlay.releaseMouse()
            except RuntimeError:
                pass
        self._close_overlays()
        if self.cancel_callback:
            QTimer.singleShot(0, self.cancel_callback)

    def _close_overlays(self) -> None:
        self.closing = True
        for overlay in self.overlays:
            overlay.close()

    def _update_overlays(self) -> None:
        for overlay in self.overlays:
            overlay.update()

    @staticmethod
    def _compose_selection(
        screen_captures: list[tuple[QRect, QPixmap]],
        global_rect: QRect,
    ) -> QPixmap:
        scales = [
            pixmap.width() / geometry.width()
            for geometry, pixmap in screen_captures
            if (
                geometry.width() > 0
                and not global_rect.intersected(geometry).isEmpty()
            )
        ]
        output_scale = max(scales, default=1.0)
        output = QImage(
            max(1, round(global_rect.width() * output_scale)),
            max(1, round(global_rect.height() * output_scale)),
            QImage.Format.Format_RGB32,
        )
        output.fill(Qt.GlobalColor.black)
        painter = QPainter(output)

        for geometry, screen_pixmap in screen_captures:
            intersection = global_rect.intersected(geometry)
            if intersection.isEmpty() or screen_pixmap.isNull():
                continue

            scale_x = screen_pixmap.width() / geometry.width()
            scale_y = screen_pixmap.height() / geometry.height()
            source = QRectF(
                (intersection.x() - geometry.x()) * scale_x,
                (intersection.y() - geometry.y()) * scale_y,
                intersection.width() * scale_x,
                intersection.height() * scale_y,
            )
            target = QRectF(
                (intersection.x() - global_rect.x()) * output_scale,
                (intersection.y() - global_rect.y()) * output_scale,
                intersection.width() * output_scale,
                intersection.height() * output_scale,
            )
            painter.drawPixmap(target, screen_pixmap, source)

        painter.end()
        output.setDevicePixelRatio(1.0)
        return QPixmap.fromImage(output)
