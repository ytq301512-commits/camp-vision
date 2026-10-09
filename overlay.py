from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from .capture import qt_capture_scales
from .models import Match


# The OCR name is rendered near the bottom of each card. Six text-heights
# above that name is the card-top anchor in the reference layout.
CAMP_LABEL_CARD_OFFSET = 6.0
CAMP_LABEL_GAP = 4


def camp_label_rect(
    text_rect: QRect,
    label_width: int,
    label_height: int,
    reference_text_rect: QRect | None = None,
) -> QRect:
    """Place a camp label above a card using one shared vertical reference."""
    reference = reference_text_rect if reference_text_rect is not None else text_rect
    card_top = reference.top() - round(reference.height() * CAMP_LABEL_CARD_OFFSET)
    y = max(0, card_top - label_height - CAMP_LABEL_GAP)
    x = text_rect.center().x() - label_width // 2
    return QRect(x, y, label_width, label_height)


def virtual_desktop_geometry() -> QRect:
    screens = QApplication.screens()
    if not screens:
        return QRect(0, 0, 1920, 1080)
    geometry = QRect(screens[0].geometry())
    for screen in screens[1:]:
        geometry = geometry.united(screen.geometry())
    return geometry


def exclude_from_capture(widget: QWidget) -> None:
    if sys.platform != "win32":
        return
    try:
        # WDA_EXCLUDEFROMCAPTURE keeps labels out of subsequent desktop frames.
        ctypes.windll.user32.SetWindowDisplayAffinity(int(widget.winId()), 0x11)
    except (AttributeError, OSError):
        pass


class RegionSelector(QWidget):
    selected = Signal(QRect)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(virtual_desktop_geometry())
        self._start: QPoint | None = None
        self._end: QPoint | None = None

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(event)
        self.activateWindow()
        self.raise_()

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.position().toPoint()
            self._end = self._start
            self.update()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._start is not None:
            self._end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._start is None or event.button() != Qt.MouseButton.LeftButton:
            return
        self._end = event.position().toPoint()
        local = QRect(self._start, self._end).normalized()
        if local.width() >= 20 and local.height() >= 20:
            global_rect = QRect(local)
            global_rect.translate(self.geometry().topLeft())
            self.selected.emit(global_rect)
        else:
            self.cancelled.emit()
        self.close()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(5, 8, 12, 145))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._start is None or self._end is None:
            painter.setPen(QColor("white"))
            painter.setFont(QFont("Microsoft YaHei UI", 14))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "拖动框选要识别的文字区域 · Esc 取消")
            return
        selection = QRect(self._start, self._end).normalized()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(selection, Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setPen(QPen(QColor("#38bdf8"), 2))
        painter.drawRect(selection)
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Microsoft YaHei UI", 10))
        painter.drawText(selection.adjusted(8, 8, -8, -8), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, f"{selection.width()} × {selection.height()}")


class ResultOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__()
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        flags |= Qt.WindowType.WindowTransparentForInput
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(virtual_desktop_geometry())
        self._region = QRect()
        self._matches: list[Match] = []
        self._resolution: tuple[int, int] | None = None

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(event)
        exclude_from_capture(self)

    def set_resolution(self, resolution: tuple[int, int] | None) -> None:
        self._resolution = resolution

    def set_results(self, region: QRect, matches: list[Match]) -> None:
        self._region = QRect(region)
        self._matches = matches
        self.update()
        if matches and not self.isVisible():
            self.show()
        elif not matches:
            self.hide()

    def clear(self) -> None:
        self._matches = []
        self.hide()

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        # Clear the translucent backing store before painting the current
        # frame. Without this, a label that moved or disappeared can remain
        # as a stale pixel region on some Windows desktop compositors.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        desktop_origin = self.geometry().topLeft()
        # OCR boxes are measured in the physical screenshot returned by mss,
        # while this transparent Qt window paints in logical screen pixels.
        # Convert them back so labels stay over the text selected by the user.
        x_scale, y_scale = qt_capture_scales(self._region, self._resolution)
        text_rects: list[QRect] = []
        for match in self._matches:
            box = match.detection.box
            text_rects.append(
                QRect(
                    self._region.left() + round(box.left / x_scale) - desktop_origin.x(),
                    self._region.top() + round(box.top / y_scale) - desktop_origin.y(),
                    max(round(box.width / x_scale), 2),
                    max(round(box.height / y_scale), 2),
                )
            )
        reference_text_rect = text_rects[0] if text_rects else None
        for match, text_rect in zip(self._matches, text_rects):
            color = QColor(match.character.color)

            # The table resolves the person name; the on-screen result is
            # intentionally only the corresponding camp above the card.
            label = match.character.camp
            painter.setFont(QFont("Microsoft YaHei UI", 10, QFont.Weight.DemiBold))
            metrics = painter.fontMetrics()
            label_width = metrics.horizontalAdvance(label) + 16
            label_height = metrics.height() + 8
            label_rect = camp_label_rect(text_rect, label_width, label_height, reference_text_rect)
            painter.setPen(Qt.PenStyle.NoPen)
            background = QColor("#0b1016")
            background.setAlpha(225)
            painter.setBrush(background)
            painter.drawRoundedRect(label_rect, 4, 4)
            painter.setPen(color.lighter(125))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label)
