"""Small seller-only GUI for issuing CampVision license keys."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from license_issue import create_license_key


def private_key_path() -> Path:
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        candidates = [
            Path(getattr(sys, "_MEIPASS", executable_dir)) / "license_private_key.json",
            executable_dir / "_internal" / "license_private_key.json",
            executable_dir / "license_private_key.json",
        ]
        return next((path for path in candidates if path.exists()), candidates[0])
    return Path(__file__).resolve().parents[1] / "license_private_key.json"


class IssuerWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Camp Vision 卡密生成器")
        self.setMinimumSize(720, 520)
        root = QVBoxLayout(self)
        title = QLabel("Camp Vision 卡密生成器")
        title.setStyleSheet("font-size: 21px; font-weight: 600;")
        root.addWidget(title)
        hint = QLabel("输入客户信息和机器码，生成一条对应卡密。此工具仅供软件销售者使用。")
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        self.customer = QLineEdit()
        self.customer.setPlaceholderText("例如：张三")
        form.addRow("客户名称", self.customer)
        self.machine = QLineEdit()
        self.machine.setPlaceholderText("粘贴客户软件显示的机器码")
        self.machine.textChanged.connect(self._normalize_machine)
        form.addRow("机器码", self.machine)
        self.duration = QComboBox()
        self.duration.addItem("永久", None)
        for days in (30, 90, 180, 365, 730):
            self.duration.addItem(f"{days} 天", days)
        self.duration.addItem("自定义天数", "custom")
        self.duration.currentIndexChanged.connect(self._duration_changed)
        form.addRow("有效期", self.duration)
        self.custom_days = QSpinBox()
        self.custom_days.setRange(1, 36500)
        self.custom_days.setValue(365)
        self.custom_days.setSuffix(" 天")
        self.custom_days.setEnabled(False)
        form.addRow("自定义", self.custom_days)
        root.addLayout(form)

        actions = QHBoxLayout()
        self.generate = QPushButton("生成卡密")
        self.generate.setDefault(True)
        self.generate.clicked.connect(self._generate)
        self.copy = QPushButton("复制卡密")
        self.copy.setEnabled(False)
        self.copy.clicked.connect(self._copy)
        actions.addWidget(self.generate)
        actions.addWidget(self.copy)
        actions.addStretch()
        root.addLayout(actions)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("生成的卡密会显示在这里")
        root.addWidget(self.output, 1)
        self.status = QLabel(f"发行私钥：{private_key_path()}")
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    def _normalize_machine(self, value: str) -> None:
        normalized = re.sub(r"[^0-9A-Fa-f]", "", value).upper()
        if normalized != value:
            self.machine.blockSignals(True)
            self.machine.setText(normalized)
            self.machine.blockSignals(False)

    def _duration_changed(self, _index: int) -> None:
        self.custom_days.setEnabled(self.duration.currentData() == "custom")

    def _generate(self) -> None:
        customer = self.customer.text().strip()
        machine = self.machine.text().strip().upper()
        if not customer:
            QMessageBox.warning(self, "信息不完整", "请填写客户名称。")
            self.customer.setFocus()
            return
        if len(machine) != 64:
            QMessageBox.warning(self, "机器码不正确", "机器码应为 64 位十六进制字符串。")
            self.machine.setFocus()
            return
        key_path = private_key_path()
        if not key_path.exists():
            QMessageBox.critical(
                self,
                "找不到私钥",
                f"未找到发行私钥：\n{key_path}\n\n请先完整解压 ZIP，再运行卡密生成器；不要直接在压缩包中双击 EXE。",
            )
            return
        selected = self.duration.currentData()
        days = self.custom_days.value() if selected == "custom" else selected
        try:
            key = create_license_key(key_path, customer, machine, days)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "生成失败", str(exc))
            return
        self.output.setPlainText(key)
        self.copy.setEnabled(True)
        self.status.setText("生成成功。请复制完整卡密发给客户；不要泄露发行私钥。")

    def _copy(self) -> None:
        value = self.output.toPlainText().strip()
        if value:
            QApplication.clipboard().setText(value)
            self.status.setText("卡密已复制到剪贴板。")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Camp Vision License Issuer")
    window = IssuerWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
