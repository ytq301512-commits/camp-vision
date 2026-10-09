"""Download official hero card images and build red-box recognition templates."""

from __future__ import annotations

import argparse
import json
import ssl
import time
from pathlib import Path
from urllib.request import Request, urlopen

import cv2
import numpy as np


API_URL = "https://game.gtimg.cn/images/amside/ide_timer/589094_oscard_new_1.js"

# The original roster intentionally keeps a few one-character display names
# (for example ``孙`` and ``蒙``). Resolve those names to the official API
# records while retaining the roster/template filenames used by the app.
NAME_ALIASES = {"孙": "孙膑", "扁": "扁鹊", "蒙": "蒙犽"}

# The reference crop includes the full card width and the artwork/name area,
# stopping before the narrow Hero separator and the skill description.
LEFT = 3
TOP = 0
RIGHT = 401
BOTTOM = 350


def _download(url: str) -> np.ndarray:
    request = Request(url, headers={"User-Agent": "CampVision card template updater"})
    context = ssl._create_unverified_context()
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=45, context=context) as response:
                payload = response.read()
            break
        except Exception as exc:  # network/CDN failures are often transient
            last_error = exc
            if attempt == 2:
                raise
            time.sleep(0.5 * (attempt + 1))
    else:
        raise OSError(f"unable to download {url}: {last_error}")
    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None or image.size == 0:
        raise ValueError(f"unable to decode image: {url}")
    return image


def update(roster_path: Path, template_dir: Path, api_path: Path | None = None) -> tuple[int, int]:
    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    characters = roster.get("characters", roster) if isinstance(roster, dict) else roster
    api_payload = json.loads(api_path.read_text(encoding="utf-8")) if api_path else json.loads(
        _download_json(API_URL).decode("utf-8")
    )
    rows = {str(item["name"]): item for item in api_payload.get("heroCards", [])}

    template_dir.mkdir(parents=True, exist_ok=True)
    updated = 0
    missing: list[str] = []
    for character in characters:
        name = str(character.get("name", "")).strip()
        row = rows.get(NAME_ALIASES.get(name, name))
        if row is None or not row.get("cardImage"):
            missing.append(name)
            continue
        image = _download(str(row["cardImage"]))
        height, width = image.shape[:2]
        if width < RIGHT or height < BOTTOM:
            raise ValueError(f"card image for {name!r} is too small: {width}x{height}")
        crop = image[TOP:BOTTOM, LEFT:RIGHT]
        output = template_dir / f"{name}.png"
        encoded = cv2.imencode(".png", crop)[1]
        if encoded is None or encoded.size == 0:
            raise OSError(f"unable to encode {output}")
        encoded.tofile(str(output))
        updated += 1

    if missing:
        raise ValueError("missing official card images for: " + ", ".join(missing))
    return updated, len(characters)


def _download_json(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "CampVision card template updater"})
    with urlopen(request, timeout=45) as response:
        return response.read()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roster", type=Path, default=Path("data/roster.json"))
    parser.add_argument("--templates", type=Path, default=Path("assets/card_templates"))
    parser.add_argument("--api", type=Path, help="Use a saved API response instead of downloading it")
    args = parser.parse_args()
    updated, total = update(args.roster, args.templates, args.api)
    print(f"updated {updated}/{total} templates")


if __name__ == "__main__":
    main()
