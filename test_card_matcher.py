from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import pytest

from camp_vision.card_matcher import CardImageMatcher
from camp_vision.gpu_matcher import gpu_available
from camp_vision.models import load_roster


def test_card_detection_box_is_the_bottom_name_strip() -> None:
    left, top, width, height = CardImageMatcher._name_box((100, 20, 200, 100))

    assert (left, top, width, height) == (120, 109, 160, 15)


def test_card_row_name_strip_matches_ocr_text_height() -> None:
    left, top, width, height = CardImageMatcher._name_box((100, 28, 117, 124), image_height=159)

    assert (left, top, width, height) == (112, 138, 93, 19)


def test_card_row_recognizes_each_visible_hero_once() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "tests" / "fixtures" / "card_row.png"
    image = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    matcher = CardImageMatcher(load_roster(root / "data" / "roster.json"))

    matches = matcher.match(image, [])

    assert Counter(match.character.name for match in matches) == Counter({
        "梦奇": 2,
        "狂铁": 1,
        "狄仁杰": 1,
        "百里玄策": 1,
        "苏烈": 1,
        "孙": 1,
        "云中君": 1,
        "干将莫邪": 1,
        "蔡文姬": 1,
        "牛魔": 1,
        "大乔": 1,
    })
    assert all(12 <= match.detection.box.height <= 22 for match in matches)
    assert all(136 <= match.detection.box.top <= 142 for match in matches)


@pytest.mark.skipif(not gpu_available(), reason="OpenCL GPU is unavailable")
def test_gpu_card_matching_keeps_cpu_recognition_result() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "tests" / "fixtures" / "card_row.png"
    image = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    roster = load_roster(root / "data" / "roster.json")
    cpu = CardImageMatcher(roster, use_gpu=False)
    gpu = CardImageMatcher(roster, use_gpu=True)

    assert gpu.acceleration_backend == "OpenCL GPU"
    assert Counter(item.character.name for item in gpu.match(image, [])) == Counter(
        item.character.name for item in cpu.match(image, [])
    )
