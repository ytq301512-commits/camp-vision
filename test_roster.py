from camp_vision.models import Character, load_roster, save_roster


def test_roster_round_trips_unicode_names_and_aliases(tmp_path) -> None:
    path = tmp_path / "roster.json"
    expected = [Character("阿狸", "艾欧尼亚", ("九尾妖狐",), "#38bdf8")]

    save_roster(path, expected)

    assert load_roster(path) == expected

