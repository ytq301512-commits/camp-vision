from PySide6.QtCore import QRect

from camp_vision.capture import qt_rect_to_capture_rect, resolution_to_scale


def test_qt_selection_is_scaled_to_physical_capture_pixels() -> None:
    # A 2560x1600 display at 150% is exposed to Qt as 1707x1067 logical
    # pixels.  The selected logical rectangle must become the corresponding
    # physical mss rectangle before OCR.
    logical = QRect(575, 694, 693, 123)

    assert qt_rect_to_capture_rect(logical, scale=1.5) == QRect(862, 1041, 1040, 185)


def test_manual_resolution_scales_logical_selection_by_axis() -> None:
    # A 2560x1600 physical display exposed as 1707x1067 logical pixels.
    assert resolution_to_scale((2560, 1600), (1707, 1067)) == (
        2560 / 1707,
        1600 / 1067,
    )
    logical = QRect(575, 694, 693, 123)
    assert qt_rect_to_capture_rect(logical, scale=2560 / 1707) == QRect(862, 1041, 1040, 184)
