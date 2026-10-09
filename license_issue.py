"""Create CampVision offline license keys.

Keep the generated private key outside any release archive. The application
contains only the public key needed to verify a key.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import sys
from datetime import date, timedelta
from pathlib import Path


PREFIX = "CV1"
E = 65537


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def is_probable_prime(value: int) -> bool:
    if value < 2 or value % 2 == 0:
        return value == 2
    small = (3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)
    if any(value % p == 0 for p in small):
        return False
    odd, rounds = value - 1, 0
    while odd % 2 == 0:
        rounds += 1
        odd //= 2
    for base in (2, 3, 5, 7, 11, 13, 17, 19):
        if base >= value:
            continue
        probe = pow(base, odd, value)
        if probe in (1, value - 1):
            continue
        for _ in range(rounds - 1):
            probe = pow(probe, 2, value)
            if probe == value - 1:
                break
        else:
            return False
    return True


def prime(bits: int) -> int:
    while True:
        value = secrets.randbits(bits) | (1 << (bits - 1)) | 1
        if is_probable_prime(value):
            return value


def make_keypair(bits: int = 2048) -> tuple[int, int, int]:
    while True:
        p, q = prime(bits // 2), prime(bits // 2)
        if p == q:
            continue
        n = p * q
        phi = (p - 1) * (q - 1)
        if __import__("math").gcd(E, phi) == 1:
            return n, E, pow(E, -1, phi)


def digest_info(payload: bytes) -> bytes:
    return bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(payload).digest()


def sign(payload: bytes, n: int, d: int) -> bytes:
    size = (n.bit_length() + 7) // 8
    encoded = b"\x00\x01" + b"\xff" * (size - len(digest_info(payload)) - 3) + b"\x00" + digest_info(payload)
    return pow(int.from_bytes(encoded, "big"), d, n).to_bytes(size, "big")


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def write_module(public_n: int, path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = text.replace("PUBLIC_KEY_N = 0", f"PUBLIC_KEY_N = {public_n}")
    path.write_text(text, encoding="utf-8")


def init_key(path: Path, module: Path) -> None:
    if path.exists():
        raise SystemExit(f"Refusing to overwrite {path}")
    print("正在生成 2048 位签名密钥，可能需要几秒…")
    n, e, d = make_keypair()
    path.write_text(json.dumps({"n": str(n), "e": e, "d": str(d)}, indent=2), encoding="utf-8")
    write_module(n, module)
    print(f"私钥已保存：{path}\n请妥善备份，不要放入发布压缩包。")


def create_license_key(path: Path, customer: str, machine: str, days: int | None) -> str:
    key = json.loads(path.read_text(encoding="utf-8"))
    expires = "" if days is None else (date.today() + timedelta(days=days)).isoformat()
    payload = {
        "product": "camp-vision",
        "license_id": secrets.token_hex(8).upper(),
        "customer": customer,
        "machine": machine.upper() or "*",
        "issued": date.today().isoformat(),
        "expires": expires,
    }
    encoded = b64(canonical(payload))
    signature = b64(sign(canonical(payload), int(key["n"]), int(key["d"])))
    return f"{PREFIX}.{encoded}.{signature}"


def issue(path: Path, customer: str, machine: str, days: int | None) -> None:
    print(create_license_key(path, customer, machine, days))


def main() -> int:
    parser = argparse.ArgumentParser(description="CampVision 卡密发行工具")
    parser.add_argument("--private-key", default="license_private_key.json")
    parser.add_argument("--module", default="src/camp_vision/license.py")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="生成新的发行密钥")
    issue_parser = sub.add_parser("issue", help="生成卡密")
    issue_parser.add_argument("--customer", required=True)
    issue_parser.add_argument("--machine", default="*", help="客户软件显示的机器码；* 表示不绑定机器")
    issue_parser.add_argument("--days", type=int, default=None, help="有效天数；省略表示永久")
    args = parser.parse_args()
    private_key, module = Path(args.private_key), Path(args.module)
    if args.command == "init":
        init_key(private_key, module)
    else:
        if not private_key.exists():
            raise SystemExit(f"找不到私钥：{private_key}，请先运行 init")
        issue(private_key, args.customer, args.machine, args.days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
