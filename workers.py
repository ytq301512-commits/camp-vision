from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import traceback

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from .matcher import CharacterMatcher
from .card_matcher import CardImageMatcher
from .models import Match, OcrDetection
from .ocr import RapidOcrEngine


@dataclass
class _CardTrack:
    stable: Match | None = None
    pending: Match | None = None
    confirmations: int = 0
    missing: int = 0


class CardResultStabilizer:
    """Suppress one-frame card swaps and smooth the label position.

    Card matching runs less often than OCR and its contour boxes can move a
    few pixels while the game redraws.  A result becomes visible after two
    consecutive observations for the same card slot. A stable result is
    removed as soon as its slot is missed by default; callers can opt into a
    short grace period when their capture source is noisy.
    """

    def __init__(self, confirm_frames: int = 2, max_missing_frames: int = 0, smoothing: float = 0.35) -> None:
        self.confirm_frames = max(1, int(confirm_frames))
        self.max_missing_frames = max(0, int(max_missing_frames))
        self.smoothing = min(1.0, max(0.0, float(smoothing)))
        self._tracks: list[_CardTrack] = []

    @staticmethod
    def _center(match: Match) -> tuple[float, float]:
        box = match.detection.box
        return (box.left + box.right) / 2, (box.top + box.bottom) / 2

    @classmethod
    def _same_slot(cls, left: Match, right: Match) -> bool:
        left_x, left_y = cls._center(left)
        right_x, right_y = cls._center(right)
        left_box = left.detection.box
        right_box = right.detection.box
        tolerance = max(42.0, min(max(left_box.width, right_box.width), 100) * 0.70)
        return (
            abs(left_x - right_x) <= tolerance
            and abs(left_y - right_y) <= max(50.0, max(left_box.height, right_box.height) * 2.5)
        )

    def reset(self) -> None:
        self._tracks.clear()

    def _smooth(self, previous: Match, current: Match) -> Match:
        if self.smoothing >= 1.0:
            return current
        old = previous.detection.box
        new = current.detection.box
        amount = self.smoothing

        def blend(before: int, after: int) -> int:
            return round(before + (after - before) * amount)

        detection = replace(
            current.detection,
            box=replace(
                new,
                left=blend(old.left, new.left),
                top=blend(old.top, new.top),
                right=blend(old.right, new.right),
                bottom=blend(old.bottom, new.bottom),
            ),
        )
        return replace(current, detection=detection)

    def update(self, matches: list[Match]) -> list[Match]:
        """Return only temporally stable card matches for the current scan."""
        # A detector can return overlapping windows for one physical card.
        # Keep the strongest one before assigning candidates to tracks.
        candidates: list[Match] = []
        for candidate in sorted(matches, key=lambda item: item.score, reverse=True):
            if any(self._same_slot(candidate, previous) for previous in candidates):
                continue
            candidates.append(candidate)

        assignments: dict[int, Match] = {}
        used_tracks: set[int] = set()
        new_tracks: set[int] = set()
        for candidate in candidates:
            choices = [
                (index, track)
                for index, track in enumerate(self._tracks)
                if index not in used_tracks
                and self._same_slot(candidate, track.pending or track.stable)  # type: ignore[arg-type]
            ]
            if choices:
                candidate_x, candidate_y = self._center(candidate)
                index, _ = min(
                    choices,
                    key=lambda item: (
                        abs(candidate_x - self._center(item[1].pending or item[1].stable)[0])
                        + abs(candidate_y - self._center(item[1].pending or item[1].stable)[1])
                    ),
                )
                assignments[index] = candidate
                used_tracks.add(index)
            else:
                self._tracks.append(_CardTrack(pending=candidate, confirmations=1))
                new_index = len(self._tracks) - 1
                assignments[new_index] = candidate
                used_tracks.add(new_index)
                new_tracks.add(new_index)

        for index, track in enumerate(self._tracks):
            if index in new_tracks:
                continue
            candidate = assignments.get(index)
            if candidate is None:
                track.missing += 1
                track.pending = None
                track.confirmations = 0
                continue
            track.missing = 0
            if track.stable is not None and candidate.character.name == track.stable.character.name:
                track.stable = self._smooth(track.stable, candidate)
                track.pending = None
                track.confirmations = 0
                continue
            if track.pending is not None and candidate.character.name == track.pending.character.name:
                track.pending = self._smooth(track.pending, candidate)
                track.confirmations += 1
            else:
                track.pending = candidate
                track.confirmations = 1
            if track.confirmations >= self.confirm_frames and track.pending is not None:
                track.stable = track.pending
                track.pending = None
                track.confirmations = 0

        self._tracks = [track for track in self._tracks if track.missing <= self.max_missing_frames]
        stable = [track.stable for track in self._tracks if track.stable is not None]
        return sorted(stable, key=lambda item: (item.detection.box.top, _center_x(item)))


def _center_x(match: Match) -> float:
    box = match.detection.box
    return (box.left + box.right) / 2


def _same_card_slot(left: Match, right: Match) -> bool:
    """Return whether two results refer to the same physical card position."""
    a = left.detection.box
    b = right.detection.box
    horizontal = abs(_center_x(left) - _center_x(right))
    # Card detections expose a wider name strip than OCR.  Keep the tolerance
    # below the usual distance between adjacent cards so neighboring cards do
    # not collapse into one result.
    tolerance = max(56.0, min(max(a.width, b.width), 110) * 0.68)
    vertical = abs((a.top + a.bottom) / 2 - (b.top + b.bottom) / 2)
    return horizontal <= tolerance and vertical <= max(80, max(a.height, b.height) * 2)


def _row_grid(ocr_matches: list[Match]) -> tuple[float, float] | None:
    """Use neighboring OCR names to locate the fixed-width card row."""
    centers = sorted(_center_x(item) for item in ocr_matches)
    gaps = [right - left for left, right in zip(centers, centers[1:])]
    adjacent = [gap for gap in gaps if 120 <= gap <= 240]
    if not adjacent:
        return None
    pitch = sorted(adjacent)[len(adjacent) // 2]
    # An OCR name is a precise center reference; using a later one avoids
    # extrapolation from a partially clipped first card.
    return centers[-1], pitch


def _snap_to_grid(match: Match, anchor: float, pitch: float) -> tuple[int, Match]:
    slot = round((_center_x(match) - anchor) / pitch)
    target = anchor + slot * pitch
    box = match.detection.box
    offset = round(target - _center_x(match))
    detection = replace(match.detection, box=replace(box, left=box.left + offset, right=box.right + offset))
    return slot, replace(match, detection=detection)


def fuse_matches(ocr_matches: list[Match], card_matches: list[Match]) -> list[Match]:
    """Fuse channels with card matching as the authoritative result.

    A card result occupies a slot before OCR is considered. OCR only fills a
    slot where no card result was found, which prevents the two channels from
    producing duplicate camp labels.
    """
    if not ocr_matches:
        return list(card_matches)
    if not card_matches:
        return list(ocr_matches)
    grid = _row_grid(ocr_matches) if card_matches else None
    if grid is not None:
        anchor, pitch = grid
        slots: dict[int, Match] = {}
        for candidate in sorted(card_matches, key=lambda item: item.score, reverse=True):
            slot, snapped = _snap_to_grid(candidate, anchor, pitch)
            # A distant contour may belong to another UI element. Only align
            # a result when its center is plausibly inside the chosen card.
            if abs(_center_x(candidate) - (anchor + slot * pitch)) <= pitch * 0.40:
                slots.setdefault(slot, snapped)
        for candidate in sorted(ocr_matches, key=lambda item: item.score, reverse=True):
            slot, snapped = _snap_to_grid(candidate, anchor, pitch)
            slots.setdefault(slot, snapped)
        return [slots[slot] for slot in sorted(slots)]

    selected_cards: list[Match] = []
    for candidate in sorted(card_matches, key=lambda item: (-item.score, _center_x(item))):
        if any(_same_card_slot(candidate, existing) for existing in selected_cards):
            continue
        selected_cards.append(candidate)

    selected: list[Match] = list(selected_cards)
    for candidate in sorted(ocr_matches, key=lambda item: (-item.score, _center_x(item))):
        if any(_same_card_slot(candidate, existing) for existing in selected_cards):
            continue
        duplicate = next((item for item in selected if _same_card_slot(candidate, item)), None)
        if duplicate is not None:
            if candidate.score > duplicate.score:
                selected[selected.index(duplicate)] = candidate
            continue
        selected.append(candidate)
    return sorted(selected, key=lambda item: (item.detection.box.top, _center_x(item)))


def merge_recognition_results(
    detections: list[OcrDetection],
    matches: list[Match],
    card_matches: list[Match] | None = None,
) -> tuple[list[OcrDetection], list[Match]]:
    """Merge current results and optional cached card results without ghosts."""
    card_matches = card_matches or []
    ocr_matches = [item for item in matches if item.source != "card"]
    available_cards = [item for item in matches if item.source == "card"] + card_matches
    merged = fuse_matches(ocr_matches, available_cards)
    kept_detection_ids = {id(item.detection) for item in merged}
    suppressed_ids = {
        id(item.detection)
        for item in matches
        if item.source != "card" and id(item.detection) not in kept_detection_ids
    }
    merged_detections = [item for item in detections if id(item) not in suppressed_ids]
    known_ids = {id(item) for item in merged_detections}
    for item in merged:
        if id(item.detection) not in known_ids:
            merged_detections.append(item.detection)
            known_ids.add(id(item.detection))
    return merged_detections, merged


class RecognitionSignals(QObject):
    finished = Signal(object, object)
    failed = Signal(str)


class RecognitionTask(QRunnable):
    def __init__(
        self,
        image_supplier: Callable[[], np.ndarray],
        engine: RapidOcrEngine,
        matcher: CharacterMatcher,
        card_matcher: CardImageMatcher | None = None,
        use_ocr: bool = True,
        use_card: bool = True,
    ) -> None:
        super().__init__()
        self.image_supplier = image_supplier
        self.engine = engine
        self.matcher = matcher
        self.card_matcher = card_matcher
        self.use_ocr = use_ocr
        self.use_card = use_card
        self.signals = RecognitionSignals()

    @Slot()
    def run(self) -> None:
        try:
            image = self.image_supplier()
            detections: list[OcrDetection] = self.engine.recognize(image) if self.use_ocr else []
            matches: list[Match] = self.matcher.match_detections(detections) if self.use_ocr else []
            if self.use_card and self.card_matcher is not None:
                image_matches = self.card_matcher.match(image, detections)
                detections, matches = merge_recognition_results(detections, matches, image_matches)
            self.signals.finished.emit(detections, matches)
        except Exception as exc:
            traceback.print_exc()
            self.signals.failed.emit(str(exc))
