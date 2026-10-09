from pathlib import Path


def test_release_launcher_imports_package_entrypoint() -> None:
    source = Path(__file__).resolve().parents[1] / "launcher.py"
    text = source.read_text(encoding="utf-8")
    assert "from camp_vision.app import main" in text
    assert "from .main_window import MainWindow" not in text
