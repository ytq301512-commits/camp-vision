from __future__ import annotations

import csv
import json
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .models import Character, DEFAULT_COLOR, load_roster, save_roster


class RosterWidget(QWidget):
    changed = Signal(object)

    def __init__(self, roster_path: Path) -> None:
        super().__init__()
        self.roster_path = roster_path
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["人物名称", "阵营", "别名（逗号分隔）", "标签颜色"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)

        add_button = QPushButton("添加人物")
        remove_button = QPushButton("删除选中")
        color_button = QPushButton("选择颜色")
        import_button = QPushButton("导入")
        export_button = QPushButton("导出")
        save_button = QPushButton("保存人物库")
        save_button.setObjectName("primaryButton")

        add_button.clicked.connect(self.add_empty_row)
        remove_button.clicked.connect(self.remove_selected)
        color_button.clicked.connect(self.choose_color)
        import_button.clicked.connect(self.import_roster)
        export_button.clicked.connect(self.export_roster)
        save_button.clicked.connect(self.save)

        buttons = QHBoxLayout()
        for button in (add_button, remove_button, color_button):
            buttons.addWidget(button)
        buttons.addStretch()
        for button in (import_button, export_button, save_button):
            buttons.addWidget(button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        self.reload()

    def reload(self) -> None:
        try:
            self.set_characters(load_roster(self.roster_path))
        except Exception as exc:
            QMessageBox.warning(self, "人物库读取失败", str(exc))
            self.set_characters([])

    def set_characters(self, characters: list[Character]) -> None:
        self.table.setRowCount(0)
        for character in characters:
            self._append_character(character)

    def _append_character(self, character: Character) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [character.name, character.camp, ", ".join(character.aliases), character.color]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 3:
                item.setBackground(QColor(character.color))
            self.table.setItem(row, column, item)

    def add_empty_row(self) -> None:
        self._append_character(Character("新人物", "待设置", (), DEFAULT_COLOR))
        self.table.setCurrentCell(self.table.rowCount() - 1, 0)
        self.table.editItem(self.table.currentItem())

    def remove_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)

    def choose_color(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        current = self.table.item(row, 3)
        color = QColorDialog.getColor(QColor(current.text() if current else DEFAULT_COLOR), self, "选择标签颜色")
        if color.isValid():
            if current is None:
                current = QTableWidgetItem()
                self.table.setItem(row, 3, current)
            current.setText(color.name())
            current.setBackground(color)

    def characters(self) -> list[Character]:
        values: list[Character] = []
        for row in range(self.table.rowCount()):
            fields = [self.table.item(row, column).text().strip() if self.table.item(row, column) else "" for column in range(4)]
            if not any(fields):
                continue
            values.append(Character.from_dict({"name": fields[0], "camp": fields[1], "aliases": fields[2], "color": fields[3]}))
        return values

    def save(self) -> None:
        try:
            characters = self.characters()
            save_roster(self.roster_path, characters)
            self.changed.emit(characters)
            QMessageBox.information(self, "已保存", f"人物库已保存，共 {len(characters)} 人")
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))

    def import_roster(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "导入人物库", "", "人物库 (*.json *.csv)")
        if not filename:
            return
        try:
            path = Path(filename)
            if path.suffix.lower() == ".json":
                characters = load_roster(path)
            else:
                with path.open("r", encoding="utf-8-sig", newline="") as handle:
                    characters = [Character.from_dict(row) for row in csv.DictReader(handle)]
            self.set_characters(characters)
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", str(exc))

    def export_roster(self) -> None:
        filename, selected_filter = QFileDialog.getSaveFileName(self, "导出人物库", "人物库.json", "JSON (*.json);;CSV (*.csv)")
        if not filename:
            return
        try:
            path = Path(filename)
            characters = self.characters()
            if path.suffix.lower() == ".csv" or selected_filter.startswith("CSV"):
                with path.open("w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=["name", "camp", "aliases", "color"])
                    writer.writeheader()
                    for item in characters:
                        writer.writerow({"name": item.name, "camp": item.camp, "aliases": ",".join(item.aliases), "color": item.color})
            else:
                save_roster(path.with_suffix(".json") if not path.suffix else path, characters)
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))

