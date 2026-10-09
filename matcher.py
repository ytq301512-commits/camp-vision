from __future__ import annotations

from difflib import SequenceMatcher
import re
import unicodedata

from .models import Character, Match, OcrDetection


_IGNORED = re.compile(r"[\s\W_]+", re.UNICODE)


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return _IGNORED.sub("", value)


def _edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(min(
                current[-1] + 1,
                previous[right_index] + 1,
                previous[right_index - 1] + (left_char != right_char),
            ))
        previous = current
    return previous[-1]


class CharacterMatcher:
    def __init__(self, characters: list[Character], threshold: float = 0.72) -> None:
        self.characters = characters
        self.threshold = threshold
        self._terms: list[tuple[str, Character]] = []
        for character in characters:
            for term in (character.name, *character.aliases):
                normalized = normalize_text(term)
                if normalized:
                    self._terms.append((normalized, character))

    def _unique_prefix_match(self, prefix: str) -> Character | None:
        """Return a character only when a visible prefix identifies one."""
        candidates = {character for term, character in self._terms if term.startswith(prefix)}
        return next(iter(candidates)) if len(candidates) == 1 else None

    def match_text(self, text: str) -> tuple[Character, float] | None:
        candidate = normalize_text(text)
        if not candidate:
            return None

        best: tuple[Character, float] | None = None
        for term, character in self._terms:
            if candidate == term:
                score = 1.0
            elif len(term) == 1 and candidate.startswith(term) and candidate[len(term):].isdigit():
                score = 0.90
            elif min(len(candidate), len(term)) >= 2 and (candidate in term or term in candidate):
                # OCR often joins a level or cost marker to a short character name.
                score = min(len(candidate), len(term)) / max(len(candidate), len(term))
                score = max(score, 0.88)
            elif min(len(candidate), len(term)) >= 2:
                score = SequenceMatcher(None, candidate, term).ratio()
                # A single recognition typo is recoverable for names long enough
                # to avoid confusing nearly every two-character name.
                if min(len(candidate), len(term)) >= 3 and _edit_distance(candidate, term) == 1:
                    score = max(score, 0.76)
            else:
                score = 0.0

            if score >= self.threshold and (best is None or score > best[1]):
                best = (character, score)

        if best is None:
            # Cards can overlap the name so OCR may see only the first glyph
            # (occasionally followed by a level digit). Use this as a guarded
            # fallback: ambiguous prefixes are rejected instead of guessed.
            prefix = candidate[0] if len(candidate) == 1 else ""
            if len(candidate) > 1 and candidate[1:].isdigit():
                prefix = candidate[0]
            if prefix:
                character = self._unique_prefix_match(prefix)
                if character is not None:
                    return character, 0.74
        return best

    def match_detections(self, detections: list[OcrDetection]) -> list[Match]:
        matches: list[Match] = []
        seen: set[tuple[str, int, int]] = set()
        for detection in detections:
            result = self.match_text(detection.text)
            if result is None:
                continue
            character, score = result
            key = (character.name, detection.box.left // 8, detection.box.top // 8)
            if key in seen:
                continue
            seen.add(key)
            matches.append(Match(detection=detection, character=character, score=score))
        return matches
