from camp_vision.matcher import CharacterMatcher, normalize_text
from camp_vision.models import Box, Character, OcrDetection


def test_normalize_text_removes_spacing_and_punctuation() -> None:
    assert normalize_text("  阿 尔-法！ ") == "阿尔法"


def test_matches_name_and_alias() -> None:
    character = Character("齐天大圣", "神话", ("悟空",), "#ffffff")
    matcher = CharacterMatcher([character])

    assert matcher.match_text("齐天大圣")[0] == character
    assert matcher.match_text("悟 空")[0] == character


def test_matches_name_with_joined_level_marker() -> None:
    character = Character("霞", "艾欧尼亚")
    matcher = CharacterMatcher([character])

    result = matcher.match_text("霞2")
    assert result is not None
    assert result[0] == character


def test_recovers_single_ocr_typo_in_long_name() -> None:
    character = Character("齐天大圣", "神话")
    result = CharacterMatcher([character]).match_text("齐天大盛")

    assert result is not None
    assert result[0] == character


def test_rejects_unrelated_text() -> None:
    matcher = CharacterMatcher([Character("亚索", "艾欧尼亚")])
    assert matcher.match_text("商店刷新") is None


def test_unique_first_character_recovers_a_partly_hidden_name() -> None:
    first = Character("牛魔", "大河流域")
    other = Character("孙尚香", "逐鹿")

    result = CharacterMatcher([first, other]).match_text("牛")

    assert result is not None
    assert result[0] == first
    assert result[1] < 1.0


def test_ambiguous_first_character_is_not_guessed() -> None:
    matcher = CharacterMatcher([Character("孙尚香", "逐鹿"), Character("孙膑", "河洛")])

    assert matcher.match_text("孙") is None


def test_detection_match_keeps_location() -> None:
    character = Character("盖伦", "德玛西亚")
    detection = OcrDetection("盖伦", 0.96, Box(10, 20, 60, 45))
    matches = CharacterMatcher([character]).match_detections([detection])

    assert len(matches) == 1
    assert matches[0].detection.box.left == 10
    assert matches[0].character.camp == "德玛西亚"
