from __future__ import annotations

import base64
import hashlib
import json
import platform
import re
import subprocess
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


# Replaced by tools/license_issue.py --init after the first key pair is made.
PUBLIC_KEY_N = 16166483163107109081408597024041047609495787262396119640759510900594452365460079333337845082665510979048284790936606629845798231788962999813265444909219866687072910933360782009534323154793388450843049094988754186667057305738928736307021307767016458077918478409997611847771113970145187456401917999688039019768591050932361222461281379158908428961187043072381521547073106606044913280685915180766908008895473587761385080107704727328882930717970567644205654723614177617014887399406529297045970346627004180501061223566928195203508205376310093321654062663483947334566472117471874037358092250895565922914349824987177907205003
PUBLIC_KEY_E = 65537
LICENSE_PREFIX = "CV1"
LICENSE_SETTINGS_KEY = "license_key"


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def machine_fingerprint() -> str:
    """Return a stable, non-reversible identifier for the current Windows PC."""
    values: list[str] = [platform.system(), platform.node()]
    if platform.system() == "Windows":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                values.append(str(winreg.QueryValueEx(key, "MachineGuid")[0]))
        except (FileNotFoundError, OSError):
            pass
    values.append(str(uuid.getnode()))
    return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest().upper()


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _rsa_verify(payload: bytes, signature: bytes, n: int, e: int) -> bool:
    if not n or len(signature) != (n.bit_length() + 7) // 8:
        return False
    encoded = pow(int.from_bytes(signature, "big"), e, n).to_bytes(len(signature), "big")
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(payload).digest()
    expected = b"\x00\x01" + b"\xff" * (len(encoded) - len(digest_info) - 3) + b"\x00" + digest_info
    return encoded == expected


def parse_license_key(value: str) -> tuple[dict[str, Any], bytes]:
    normalized = re.sub(r"\s+", "", value.strip())
    parts = normalized.split(".")
    if len(parts) != 3 or parts[0] != LICENSE_PREFIX:
        raise ValueError("卡密格式不正确")
    payload = json.loads(_b64decode(parts[1]).decode("utf-8"))
    signature = _b64decode(parts[2])
    if not isinstance(payload, dict):
        raise ValueError("卡密内容不正确")
    return payload, signature


def validate_license_key(value: str, machine_id: str | None = None) -> tuple[bool, str, dict[str, Any] | None]:
    try:
        payload, signature = parse_license_key(value)
    except (ValueError, json.JSONDecodeError, UnicodeError, base64.binascii.Error) as exc:
        return False, str(exc), None
    if not _rsa_verify(_canonical_payload(payload), signature, PUBLIC_KEY_N, PUBLIC_KEY_E):
        return False, "卡密签名无效", None
    if payload.get("product") != "camp-vision":
        return False, "卡密不是本软件的授权", None
    bound_machine = str(payload.get("machine", "")).upper()
    current_machine = (machine_id or machine_fingerprint()).upper()
    if bound_machine not in {"", "*", current_machine}:
        return False, "卡密未授权当前电脑", None
    expires = str(payload.get("expires", ""))
    if expires:
        try:
            if date.today() > date.fromisoformat(expires):
                return False, f"卡密已于 {expires} 到期", None
        except ValueError:
            return False, "卡密有效期格式不正确", None
    return True, "授权有效", payload


def stored_license(settings: QSettings | None = None) -> str:
    settings = settings or QSettings("CampVision", "CampVision")
    return str(settings.value(LICENSE_SETTINGS_KEY, "") or "")


def save_license(value: str, settings: QSettings | None = None) -> None:
    settings = settings or QSettings("CampVision", "CampVision")
    settings.setValue(LICENSE_SETTINGS_KEY, value.strip())
    settings.sync()


def license_summary(payload: dict[str, Any]) -> str:
    customer = str(payload.get("customer", "授权用户"))
    expires = str(payload.get("expires", "永久")) or "永久"
    return f"{customer} · 有效期：{expires}"


class LicenseDialog(QDialog):
    def __init__(self, settings: QSettings | None = None, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.settings = settings or QSettings("CampVision", "CampVision")
        self.setWindowTitle("Camp Vision 授权激活")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        title = QLabel("请输入卡密以继续使用")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)
        info = QLabel("此授权绑定当前电脑。请把下面的机器码发给软件销售者获取卡密。")
        info.setWordWrap(True)
        layout.addWidget(info)
        form = QFormLayout()
        self.machine_edit = QLineEdit(machine_fingerprint())
        self.machine_edit.setReadOnly(True)
        self.machine_edit.setToolTip("复制完整机器码发给销售者")
        form.addRow("机器码", self.machine_edit)
        layout.addLayout(form)
        self.key_edit = QPlainTextEdit()
        self.key_edit.setPlaceholderText("粘贴卡密，例如 CV1....")
        self.key_edit.setMaximumHeight(100)
        layout.addWidget(self.key_edit)
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #ef4444;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox()
        self.activate_button = buttons.addButton("激活", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("退出", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._activate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _activate(self) -> None:
        value = self.key_edit.toPlainText().strip()
        valid, message, payload = validate_license_key(value)
        if not valid or payload is None:
            self.error_label.setText(message)
            return
        save_license(value, self.settings)
        QMessageBox.information(self, "激活成功", license_summary(payload))
        self.accept()


def require_license(settings: QSettings | None = None) -> bool:
    settings = settings or QSettings("CampVision", "CampVision")
    value = stored_license(settings)
    if value:
        valid, _, _ = validate_license_key(value)
        if valid:
            return True
    dialog = LicenseDialog(settings)
    return dialog.exec() == QDialog.DialogCode.Accepted
