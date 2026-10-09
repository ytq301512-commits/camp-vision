import base64
import importlib.util
import json
from pathlib import Path

import camp_vision.license as license_module


def _issue(payload: dict, n: int, d: int) -> str:
    tool_path = Path(__file__).resolve().parents[1] / "tools" / "license_issue.py"
    spec = importlib.util.spec_from_file_location("license_issue", tool_path)
    assert spec and spec.loader
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(canonical).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(tool.sign(canonical, n, d)).rstrip(b"=").decode()
    return f"CV1.{encoded}.{signature}"


def test_signed_license_is_accepted_and_machine_binding_is_enforced(monkeypatch) -> None:
    tool_path = Path(__file__).resolve().parents[1] / "tools" / "license_issue.py"
    spec = importlib.util.spec_from_file_location("license_issue_keygen", tool_path)
    assert spec and spec.loader
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    n, e, d = tool.make_keypair(512)
    monkeypatch.setattr(license_module, "PUBLIC_KEY_N", n)
    monkeypatch.setattr(license_module, "PUBLIC_KEY_E", e)
    payload = {"product": "camp-vision", "license_id": "TEST", "customer": "Test", "machine": "ABC"}
    key = _issue(payload, n, d)
    assert license_module.validate_license_key(key, "ABC")[0] is True
    assert license_module.validate_license_key(key, "OTHER")[0] is False


def test_malformed_license_is_rejected() -> None:
    valid, message, payload = license_module.validate_license_key("not-a-license")
    assert valid is False
    assert payload is None
    assert message


def test_issuer_finds_private_key_in_pyinstaller_internal(tmp_path, monkeypatch) -> None:
    tool_path = Path(__file__).resolve().parents[1] / "tools" / "license_issuer_gui.py"
    monkeypatch.syspath_prepend(str(tool_path.parent))
    spec = importlib.util.spec_from_file_location("license_issuer_gui", tool_path)
    assert spec and spec.loader
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    executable = tmp_path / "CampVisionLicenseIssuer.exe"
    internal = tmp_path / "_internal"
    internal.mkdir()
    expected = internal / "license_private_key.json"
    expected.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(tool.sys, "frozen", True, raising=False)
    monkeypatch.setattr(tool.sys, "executable", str(executable))
    monkeypatch.setattr(tool.sys, "_MEIPASS", str(internal), raising=False)
    assert tool.private_key_path() == expected
