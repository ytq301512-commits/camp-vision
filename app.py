from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


STYLE = """
QWidget { color: #e8edf3; background: #101419; font-family: "Microsoft YaHei UI"; font-size: 13px; }
#sidebar { background: #0b0f13; border-right: 1px solid #252c34; }
#appTitle { font-size: 24px; font-weight: 700; color: #f8fafc; }
#appSubtitle { color: #38bdf8; font-size: 10px; font-weight: 700; }
#pageTitle { font-size: 22px; font-weight: 700; color: #f8fafc; }
#muted { color: #88939f; }
#panel { background: #171d24; border: 1px solid #29323c; border-radius: 6px; }
#regionLabel { color: #b8c2cc; }
#statusLabel { color: #8fa0b2; padding: 8px 2px; }
QPushButton { background: #1b232c; border: 1px solid #34404c; border-radius: 5px; padding: 8px 13px; }
QPushButton:hover { background: #24303b; border-color: #4b5e70; }
QPushButton:pressed { background: #151b21; }
#primaryButton { background: #0284c7; border-color: #0ea5e9; color: white; font-weight: 600; }
#primaryButton:hover { background: #0396dc; }
#primaryButton[running="true"] { background: #be123c; border-color: #e11d48; }
#navButton { text-align: left; border: 0; background: transparent; padding: 11px 12px; color: #9da9b6; }
#navButton:hover { background: #151c23; color: #e8edf3; }
#navButton:checked { background: #17232c; color: #7dd3fc; border-left: 3px solid #38bdf8; }
QTableWidget { background: #12171d; alternate-background-color: #151b22; border: 1px solid #29323c; border-radius: 5px; gridline-color: #252d36; selection-background-color: #164e63; }
QHeaderView::section { background: #1a2129; color: #9eacb9; border: 0; border-bottom: 1px solid #303a45; padding: 9px; font-weight: 600; }
QLineEdit, QSpinBox { background: #0e1318; border: 1px solid #34404c; border-radius: 4px; padding: 7px; }
QScrollBar:vertical { background: #11161b; width: 10px; }
QScrollBar::handle:vertical { background: #3a4652; border-radius: 4px; min-height: 24px; }
QToolTip { background: #f8fafc; color: #111827; border: 0; padding: 5px; }
"""


def find_project_root() -> Path:
    package_path = Path(__file__).resolve()
    for candidate in (Path.cwd(), *package_path.parents):
        if (candidate / "data" / "roster.json").exists():
            return candidate
    return Path.cwd()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Camp Vision")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(STYLE)
    window = MainWindow(find_project_root())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

