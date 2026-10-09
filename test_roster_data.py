from pathlib import Path

from camp_vision.models import load_roster


def test_reference_roster_contains_all_six_camps() -> None:
    characters = load_roster(Path(__file__).resolve().parents[1] / "data" / "roster.json")
    assert len(characters) == 85
    # The displayed camp now includes the card tier prefix (for example,
    # ``1大河``).  Strip that prefix when checking the six base camps.
    assert {character.camp[1:] for character in characters} == {
        "大河",
        "逐鹿",
        "三分",
        "河洛",
        "日落海",
        "无阵营",
    }
    assert any(character.name == "干将莫邪" and character.camp == "1大河" for character in characters)
    assert any(character.name == "嬴政" and character.camp == "4逐鹿" for character in characters)
    assert any(character.name == "弈星" and "奔星" in character.aliases for character in characters)
