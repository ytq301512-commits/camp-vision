from PySide6.QtCore import QRect

from camp_vision.overlay import camp_label_rect


def test_camp_label_is_above_card_from_name_text_size() -> None:
    # These are logical-pixel coordinates after converting a 150% physical
    # screenshot.  A 24px physical OCR box is 16px in the Qt overlay.
    text_rect = QRect(104, 164, 28, 16)

    label = camp_label_rect(text_rect, label_width=70, label_height=22)

    assert abs(label.center().x() - text_rect.center().x()) <= 1
    assert label.top() == 42
    assert label.bottom() < text_rect.top()


def test_all_camp_labels_use_first_text_box_height() -> None:
    first = QRect(104, 164, 28, 16)
    second = QRect(300, 170, 36, 20)

    first_label = camp_label_rect(first, label_width=70, label_height=22, reference_text_rect=first)
    second_label = camp_label_rect(second, label_width=70, label_height=22, reference_text_rect=first)

    assert second_label.top() == first_label.top()
    assert second_label.center().x() != first_label.center().x()
