from __future__ import annotations

from pathlib import Path

import mss
import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication, QImage


def _screen_for_rect(rect: QRect):
    """Return the Qt screen containing ``rect`` (or the first screen)."""
    app = QGuiApplication.instance()
    if app is None:
        return None
    screen = app.screenAt(rect.center())
    if screen is None:
        screens = app.screens()
        screen = screens[0] if screens else None
    return screen


def qt_device_scale(rect: QRect) -> float:
    """Return the Windows capture scale for a Qt (logical-pixel) rect.

    Qt reports widget/screen coordinates in logical pixels when Windows display
    scaling is enabled (for example, a 2560x1600 display at 150% is exposed as
    roughly 1707x1067).  ``mss`` captures physical pixels, so using the Qt
    rectangle directly makes the captured area too small and offset.
    """
    screen = _screen_for_rect(rect)
    if screen is None:
        return 1.0
    return max(float(screen.devicePixelRatio()), 1.0)


def resolution_to_scale(
    resolution: tuple[int, int], logical_size: tuple[int, int]
) -> tuple[float, float]:
    """Convert a selected physical resolution into Qt logical-pixel scales."""
    physical_width, physical_height = resolution
    logical_width, logical_height = logical_size
    if physical_width <= 0 or physical_height <= 0 or logical_width <= 0 or logical_height <= 0:
        return 1.0, 1.0
    return physical_width / logical_width, physical_height / logical_height


def qt_capture_scales(
    rect: QRect, resolution: tuple[int, int] | None = None
) -> tuple[float, float]:
    """Return horizontal/vertical scales from Qt coordinates to mss pixels.

    When a user supplied resolution is present, it is treated as the physical
    pixel size of the selected display. This is useful when Windows reports a
    logical screen size because display scaling is enabled.
    """
    if resolution is None:
        scale = qt_device_scale(rect)
        return scale, scale
    screen = _screen_for_rect(rect)
    if screen is None:
        return 1.0, 1.0
    geometry = screen.geometry()
    return resolution_to_scale(resolution, (geometry.width(), geometry.height()))


def qt_rect_to_capture_rect(
    rect: QRect,
    scale: float | None = None,
    resolution: tuple[int, int] | None = None,
) -> QRect:
    """Convert a Qt logical-pixel rectangle to the physical mss rectangle."""
    if scale is None:
        x_factor, y_factor = qt_capture_scales(rect, resolution)
    else:
        x_factor = y_factor = max(float(scale), 0.01)
    left = round(rect.left() * x_factor)
    top = round(rect.top() * y_factor)
    right = round((rect.left() + rect.width()) * x_factor)
    bottom = round((rect.top() + rect.height()) * y_factor)
    return QRect(
        left,
        top,
        max(right - left, 1),
        max(bottom - top, 1),
    )


def capture_region(rect: QRect, resolution: tuple[int, int] | None = None) -> np.ndarray:
    physical_rect = qt_rect_to_capture_rect(rect, resolution=resolution)
    monitor = {
        "left": physical_rect.left(),
        "top": physical_rect.top(),
        "width": physical_rect.width(),
        "height": physical_rect.height(),
    }
    with mss.mss() as capture:
        frame = np.asarray(capture.grab(monitor))
    return np.ascontiguousarray(frame[:, :, :3])


def load_image(path: Path) -> np.ndarray:
    image = QImage(str(path))
    if image.isNull():
        raise ValueError(f"无法读取图片：{path}")
    converted = image.convertToFormat(QImage.Format.Format_RGB888)
    width, height = converted.width(), converted.height()
    ptr = converted.bits()
    array = np.frombuffer(ptr, dtype=np.uint8, count=converted.sizeInBytes())
    array = array.reshape((height, converted.bytesPerLine()))[:, : width * 3]
    return np.ascontiguousarray(array.reshape((height, width, 3))[:, :, ::-1])
