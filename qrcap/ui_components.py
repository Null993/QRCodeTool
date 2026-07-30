"""Reusable, dependency-free Qt widgets used by the desktop interface."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QLabel,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)


class ThemedCheckBox(QCheckBox):
    """A stable checkbox that does not inherit platform accent artifacts."""

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMinimumHeight(22)

    def sizeHint(self) -> QSize:
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(text_width + 30, max(22, super().sizeHint().height()))

    def paintEvent(self, event) -> None:
        del event
        application = QApplication.instance()
        theme = (
            application.property("qrcapTheme")
            if application is not None
            else "light"
        )
        dark = theme == "dark"
        enabled = self.isEnabled()
        checked = self.checkState() != Qt.CheckState.Unchecked

        border = QColor("#667085" if dark else "#98A2B3")
        surface = QColor("#111926" if dark else "#FFFFFF")
        accent = QColor("#3B82F6" if dark else "#2563EB")
        text_color = QColor("#DEE5EF" if dark else "#344054")
        if not enabled:
            border.setAlpha(110)
            surface.setAlpha(150)
            text_color.setAlpha(120)
        elif self.underMouse() and not checked:
            border = accent

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        indicator_size = 18.0
        indicator_top = (self.height() - indicator_size) / 2.0
        indicator = QRectF(0.5, indicator_top + 0.5, 17.0, 17.0)

        painter.setPen(QPen(accent if checked else border, 1.25))
        painter.setBrush(accent if checked else surface)
        painter.drawRoundedRect(indicator, 4.0, 4.0)

        if checked:
            painter.setPen(QPen(QColor("#FFFFFF"), 2.0))
            if self.checkState() == Qt.CheckState.PartiallyChecked:
                painter.drawLine(
                    QPointF(4.5, indicator_top + 9.0),
                    QPointF(13.5, indicator_top + 9.0),
                )
            else:
                painter.drawLine(
                    QPointF(4.3, indicator_top + 9.0),
                    QPointF(7.5, indicator_top + 12.0),
                )
                painter.drawLine(
                    QPointF(7.5, indicator_top + 12.0),
                    QPointF(13.8, indicator_top + 5.5),
                )

        painter.setPen(text_color)
        painter.setFont(self.font())
        painter.drawText(
            QRectF(26.0, 0.0, max(0.0, self.width() - 26.0), self.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.text(),
        )
        painter.end()


class ThemedCheckItemDelegate(QStyledItemDelegate):
    """Paint item-view check states with the same colors as the application."""

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        check_state = index.data(Qt.ItemDataRole.CheckStateRole)
        if check_state is None:
            return
        check_state = Qt.CheckState(check_state)

        styled_option = QStyleOptionViewItem(option)
        self.initStyleOption(styled_option, index)
        style = (
            option.widget.style()
            if option.widget is not None
            else QApplication.style()
        )
        native_rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator,
            styled_option,
            option.widget,
        )
        center = native_rect.center()
        indicator = QRectF(
            center.x() - 8.5,
            center.y() - 8.5,
            17.0,
            17.0,
        )

        application = QApplication.instance()
        dark = (
            application is not None
            and application.property("qrcapTheme") == "dark"
        )
        border = QColor("#667085" if dark else "#98A2B3")
        surface = QColor("#111926" if dark else "#FFFFFF")
        accent = QColor("#3B82F6" if dark else "#2563EB")
        checked = check_state != Qt.CheckState.Unchecked

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(accent if checked else border, 1.25))
        painter.setBrush(accent if checked else surface)
        painter.drawRoundedRect(indicator, 3.5, 3.5)

        if checked:
            painter.setPen(QPen(QColor("#FFFFFF"), 2.0))
            if check_state == Qt.CheckState.PartiallyChecked:
                painter.drawLine(
                    QPointF(indicator.left() + 4.0, indicator.center().y()),
                    QPointF(indicator.right() - 4.0, indicator.center().y()),
                )
            else:
                painter.drawLine(
                    QPointF(
                        indicator.left() + 4.0,
                        indicator.top() + 9.0,
                    ),
                    QPointF(
                        indicator.left() + 7.0,
                        indicator.top() + 12.0,
                    ),
                )
                painter.drawLine(
                    QPointF(
                        indicator.left() + 7.0,
                        indicator.top() + 12.0,
                    ),
                    QPointF(
                        indicator.right() - 3.0,
                        indicator.top() + 5.5,
                    ),
                )
        painter.restore()


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


class StablePixmapLabel(QLabel):
    """A preview label whose pixmap cannot enlarge its parent layout."""

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        *,
        preferred_size: QSize = QSize(200, 150),
    ) -> None:
        super().__init__(text, parent)
        self._preferred_size = QSize(preferred_size)
        self.setMinimumSize(self._preferred_size)
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Ignored,
        )

    def sizeHint(self) -> QSize:
        return QSize(self._preferred_size)

    def minimumSizeHint(self) -> QSize:
        return QSize(self._preferred_size)


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


def _paint_qr_glyph(
    painter: QPainter,
    color: QColor,
    width: float = 1.8,
) -> None:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    # Four open scan-frame corners keep the glyph legible at 16 px.
    for start, corner, end in (
        (QPointF(8, 3), QPointF(3, 3), QPointF(3, 8)),
        (QPointF(16, 3), QPointF(21, 3), QPointF(21, 8)),
        (QPointF(3, 16), QPointF(3, 21), QPointF(8, 21)),
        (QPointF(21, 16), QPointF(21, 21), QPointF(16, 21)),
    ):
        painter.drawLine(start, corner)
        painter.drawLine(corner, end)

    # Three finder blocks and a compact data mark suggest a QR code.
    painter.drawRoundedRect(QRectF(6.5, 6.5, 4, 4), 0.5, 0.5)
    painter.drawRoundedRect(QRectF(13.5, 6.5, 4, 4), 0.5, 0.5)
    painter.drawRoundedRect(QRectF(6.5, 13.5, 4, 4), 0.5, 0.5)
    painter.drawLine(QPointF(14, 14), QPointF(17.5, 14))
    painter.drawLine(QPointF(14, 14), QPointF(14, 17.5))
    painter.drawPoint(QPointF(17.5, 17.5))


def themed_tray_icon(theme: str) -> QIcon:
    """Create a high-contrast monochrome QR glyph for dynamic icons."""
    color = QColor("#FFFFFF" if theme == "dark" else "#111111")
    icon = QIcon()

    for size in (16, 20, 24, 32, 48):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 24.0, size / 24.0)
        _paint_qr_glyph(painter, color)
        painter.end()
        icon.addPixmap(pixmap)

    return icon


def static_application_icon() -> QIcon:
    """Create a transparent black/white icon for executable resources."""
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 24.0, size / 24.0)
        # A white halo remains visible on dark shells; the black core remains
        # visible on light shells. Static EXE resources cannot switch at run
        # time, so this avoids relying on either background color.
        _paint_qr_glyph(painter, QColor("#FFFFFF"), 4.2)
        _paint_qr_glyph(painter, QColor("#111111"), 1.8)
        painter.end()
        icon.addPixmap(pixmap)
    return icon
