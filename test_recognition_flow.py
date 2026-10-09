import os
from pathlib import Path
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from camp_vision.main_window import MainWindow
from camp_vision.models import Box, Character, Match, OcrDetection
from camp_vision.workers import CardResultStabilizer, fuse_matches, merge_recognition_results


class FakeOcr:
    def recognize(self, image):  # type: ignore[no-untyped-def]
        return [OcrDetection("狂铁", 1.0, Box(0, 0, 20, 20))]


def test_recognition_task_updates_results_table() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Path(__file__).resolve().parents[1])
    window.save_config = False
    window.ocr_checkbox.setChecked(True)
    window.card_checkbox.setChecked(False)
    window.engine = FakeOcr()
    window._submit(lambda: object(), None)

    deadline = time.monotonic() + 3
    while window.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()

    assert window.busy is False
    assert window.results.rowCount() == 1
    assert window.results.item(0, 1).text() == "狂铁"
    assert window.results.item(0, 2).text() == "1日落海"

    window.close()


def test_recognition_intervals_allow_faster_scanning() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Path(__file__).resolve().parents[1])
    window.save_config = False

    assert window.interval.minimum() == 50
    assert window.card_interval.minimum() == 150
    window.timer.start(100)
    window.interval.setValue(100)
    window.interval.setValue(50)
    assert window.timer.interval() == 50

    window.close()


def test_dual_mode_prefers_card_result_for_one_slot() -> None:
    ocr_character = Character("OCR", "魏", color="#ffffff")
    card_character = Character("Card", "蜀", color="#ffffff")
    ocr_detection = OcrDetection("OCR", 1.0, Box(102, 138, 128, 156))
    card_detection = OcrDetection("Card", 0.74, Box(84, 136, 146, 157), source="card")
    ocr = Match(ocr_detection, ocr_character, 1.0)
    card = Match(card_detection, card_character, 0.74, source="card")

    merged = fuse_matches([ocr], [card])

    assert merged == [card]
    detections, matches = merge_recognition_results([ocr_detection], [ocr], [card])
    assert matches == [card]
    assert detections == [card_detection]


def test_dual_mode_uses_ocr_only_for_missing_card_slot() -> None:
    first = Character("First", "魏", color="#ffffff")
    second = Character("Second", "蜀", color="#ffffff")
    first_detection = OcrDetection("First", 1.0, Box(100, 138, 126, 156))
    second_detection = OcrDetection("Second", 1.0, Box(260, 138, 290, 156))
    card_detection = OcrDetection("First", 0.9, Box(84, 136, 146, 157), source="card")
    first_match = Match(first_detection, first, 1.0)
    second_match = Match(second_detection, second, 1.0)
    card_match = Match(card_detection, first, 0.9, source="card")

    merged = fuse_matches([first_match, second_match], [card_match])

    assert [item.character.name for item in merged] == ["First", "Second"]
    assert [item.source for item in merged] == ["card", "ocr"]


def test_dual_mode_aligns_card_labels_to_ocr_card_spacing() -> None:
    character = Character("Hero", "魏", color="#ffffff")

    def match(center: int, source: str, score: float = 0.9) -> Match:
        width = 105 if source == "card" else 40
        detection = OcrDetection("Hero", score, Box(center - width // 2, 138, center + width // 2, 157), source=source)
        return Match(detection, character, score, source=source)

    # Measured centers from the user's screenshot: card contours are uneven,
    # while the three adjacent OCR names establish a 168px card pitch.
    cards = [match(x, "card") for x in (786, 852, 1048, 1244, 1440, 1572, 1762, 1900)]
    ocr = [match(x, "ocr") for x in (911, 1416, 1584, 1752)]

    merged = fuse_matches(ocr, cards)
    centers = [round((item.detection.box.left + item.detection.box.right) / 2) for item in merged]

    assert len(merged) == 8
    assert all(item.source == "card" for item in merged)
    assert max(centers[index + 1] - centers[index] for index in range(7)) - min(
        centers[index + 1] - centers[index] for index in range(7)
    ) <= 1


def test_card_results_need_two_frames_and_smooth_one_card_jitter() -> None:
    character = Character("Hero", "Camp", color="#ffffff")

    def card(left: int, name: str = "Hero") -> Match:
        detection = OcrDetection(name, 0.9, Box(left, 100, left + 90, 120), source="card")
        return Match(detection, character, 0.9, source="card")

    stabilizer = CardResultStabilizer(confirm_frames=2, max_missing_frames=2, smoothing=0.5)
    assert stabilizer.update([card(100)]) == []
    first_stable = stabilizer.update([card(110)])
    assert len(first_stable) == 1
    assert first_stable[0].detection.box.left == 105

    moved = stabilizer.update([card(130)])
    assert moved[0].detection.box.left == 118
    assert stabilizer.update([]) == moved
    assert stabilizer.update([]) == moved
    assert stabilizer.update([]) == []


def test_card_results_disappear_on_first_scan_after_card_is_deleted() -> None:
    character = Character("Hero", "Camp", color="#ffffff")
    detection = OcrDetection("Hero", 0.9, Box(100, 100, 190, 120), source="card")
    card = Match(detection, character, 0.9, source="card")
    stabilizer = CardResultStabilizer()

    stabilizer.update([card])
    assert stabilizer.update([card]) == [card]
    assert stabilizer.update([]) == []


def test_card_result_swap_at_one_slot_does_not_flash_immediately() -> None:
    first_character = Character("First", "Camp A", color="#ffffff")
    second_character = Character("Second", "Camp B", color="#ffffff")

    def card(character: Character) -> Match:
        detection = OcrDetection(character.name, 0.9, Box(100, 100, 190, 120), source="card")
        return Match(detection, character, 0.9, source="card")

    stabilizer = CardResultStabilizer(confirm_frames=2)
    stabilizer.update([card(first_character)])
    assert stabilizer.update([card(first_character)])[0].character == first_character
    assert stabilizer.update([card(second_character)])[0].character == first_character
    assert stabilizer.update([card(second_character)])[0].character == second_character
