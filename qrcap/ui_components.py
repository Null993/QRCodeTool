"""Reusable, dependency-free Qt widgets used by the desktop interface."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class Card(QFrame):
    """A rounded content container with a ready-to-use vertical layout."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        compact: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        margin = 16 if compact else 22
        self.body.setContentsMargins(margin, margin, margin, margin)
        self.body.setSpacing(14)


class PageHeader(QWidget):
    """Consistent page title and supporting description."""

    def __init__(
        self,
        title: str,
        subtitle: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        layout.addWidget(title_label)

        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("pageSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)


def section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


def helper_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("helperText")
    label.setWordWrap(True)
    return label


def navigation_icon(kind: str) -> QIcon:
    """Create a small monochrome icon without depending on font glyphs."""

    icon = QIcon()
    for mode, color in (
        (QIcon.Mode.Normal, "#667085"),
        (QIcon.Mode.Selected, "#2563EB"),
        (QIcon.Mode.Active, "#2563EB"),
    ):
        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if kind == "generate":
            painter.drawRect(QRectF(3.0, 3.0, 5.0, 5.0))
            painter.drawRect(QRectF(12.0, 3.0, 5.0, 5.0))
            painter.drawRect(QRectF(3.0, 12.0, 5.0, 5.0))
            painter.drawRect(QRectF(12.0, 12.0, 2.0, 2.0))
            painter.drawPoint(QPointF(17.0, 17.0))
        elif kind == "scan":
            painter.drawLine(QPointF(3, 8), QPointF(3, 3))
            painter.drawLine(QPointF(3, 3), QPointF(8, 3))
            painter.drawLine(QPointF(12, 3), QPointF(17, 3))
            painter.drawLine(QPointF(17, 3), QPointF(17, 8))
            painter.drawLine(QPointF(3, 12), QPointF(3, 17))
            painter.drawLine(QPointF(3, 17), QPointF(8, 17))
            painter.drawLine(QPointF(12, 17), QPointF(17, 17))
            painter.drawLine(QPointF(17, 17), QPointF(17, 12))
            painter.drawLine(QPointF(6, 10), QPointF(14, 10))
        elif kind == "history":
            painter.drawEllipse(QRectF(3, 3, 14, 14))
            painter.drawLine(QPointF(10, 6), QPointF(10, 10))
            painter.drawLine(QPointF(10, 10), QPointF(13, 12))
        elif kind == "hotkey":
            painter.drawRoundedRect(QRectF(2.5, 4, 15, 12), 2, 2)
            painter.drawLine(QPointF(6, 8), QPointF(7, 8))
            painter.drawLine(QPointF(10, 8), QPointF(11, 8))
            painter.drawLine(QPointF(14, 8), QPointF(15, 8))
            painter.drawLine(QPointF(6, 12), QPointF(14, 12))
        else:
            painter.drawLine(QPointF(10, 2.5), QPointF(10, 17.5))
            painter.drawLine(QPointF(2.5, 10), QPointF(17.5, 10))
            painter.drawLine(QPointF(5, 5), QPointF(15, 15))
            painter.drawLine(QPointF(15, 5), QPointF(5, 15))

        painter.end()
        icon.addPixmap(pixmap, mode)
    return icon
