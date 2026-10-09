from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json


DEFAULT_COLOR = "#22c55e"


@dataclass(frozen=True)
class Box:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)


@dataclass(frozen=True)
class OcrDetection:
    text: str
    confidence: float
    box: Box
    source: str = "ocr"


@dataclass(frozen=True)
class Character:
    name: str
    camp: str
    aliases: tuple[str, ...] = field(default_factory=tuple)
    color: str = DEFAULT_COLOR

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Character":
        name = str(value.get("name", "")).strip()
        camp = str(value.get("camp", "")).strip()
        if not name or not camp:
            raise ValueError("人物名称和阵营不能为空")
        aliases_value = value.get("aliases", [])
        if isinstance(aliases_value, str):
            aliases = tuple(item.strip() for item in aliases_value.split(",") if item.strip())
        else:
            aliases = tuple(str(item).strip() for item in aliases_value if str(item).strip())
        color = str(value.get("color", DEFAULT_COLOR)).strip() or DEFAULT_COLOR
        if not color.startswith("#") or len(color) not in (4, 7):
            color = DEFAULT_COLOR
        return cls(name=name, camp=camp, aliases=aliases, color=color)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "camp": self.camp,
            "aliases": list(self.aliases),
            "color": self.color,
        }


@dataclass(frozen=True)
class Match:
    detection: OcrDetection
    character: Character
    score: float
    source: str = "ocr"


def load_roster(path: Path) -> list[Character]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get("characters", payload) if isinstance(payload, dict) else payload
    if not isinstance(values, list):
        raise ValueError("人物库 JSON 必须包含 characters 数组")
    return [Character.from_dict(value) for value in values]


def save_roster(path: Path, characters: list[Character]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "characters": [character.to_dict() for character in characters]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
