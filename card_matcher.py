"""Fast card-art matching used together with OCR.

The game cards keep the same portrait artwork while the name text can be
covered by another card.  This module finds the portrait-shaped card regions
and compares them with the small reference library shipped in
``assets/card_templates``.  OCR remains the primary source when it is clear;
card matching supplies a fallback (and a useful correction) when text is
missing or partially covered.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .gpu_matcher import OpenClHammingMatcher, gpu_available
from .models import Box, Character, Match, OcrDetection


@dataclass
class _Template:
    character: Character
    gray: np.ndarray
    keypoints: object | None
    descriptors: np.ndarray | None
    full_descriptors: np.ndarray | None = None


class CardImageMatcher:
    """Match visible card portraits against a compact image template set."""

    # Templates contain the wide upper panel (artwork and hero name) from the
    # official card image, matching the user's red-box crop.
    SIZE = (96, 84)

    @staticmethod
    def _name_box(box: tuple[int, int, int, int], image_height: int | None = None) -> tuple[int, int, int, int]:
        """Return the card's name strip in the same role as an OCR box.

        The matcher compares the full card panel, but the overlay positions a
        camp label relative to the detected name text.  Returning only the
        lower name strip keeps card mode on the same geometry as OCR mode and
        prevents a full-card box from pushing the label far above the card.
        """
        x, y, w, h = box
        left = x + round(w * 0.10)
        right = x + round(w * 0.90)
        name_height = max(12, round(h * 0.15))
        top = y + h - round(h * 0.11)
        if image_height is not None and image_height <= 400 and y + h >= image_height * 0.75:
            # A tightly selected shop row ends just below every card name.
            # Contours may stop at the artwork, so anchor to the common row
            # baseline instead of their inconsistent lower edges.
            top = image_height - max(20, round(image_height * 0.13))
        return left, top, max(1, right - left), name_height

    def __init__(
        self,
        characters: list[Character],
        template_dir: Path | None = None,
        use_gpu: bool = False,
    ) -> None:
        self.characters = {item.name: item for item in characters}
        self.templates: list[_Template] = []
        self._cv2 = None
        self.use_gpu = False
        self._orb = None
        self._feature_orb = None
        self._feature_matcher = None
        self._feature_templates: list[_Template] = []
        self._gpu_matcher: OpenClHammingMatcher | None = None
        try:
            import cv2

            self._cv2 = cv2
        except ImportError:
            return

        self._orb = cv2.ORB_create(nfeatures=160)
        self._feature_orb = cv2.ORB_create(nfeatures=500)

        if template_dir is not None:
            directories = [template_dir]
        else:
            module_path = Path(__file__).resolve()
            # Source checkout and PyInstaller onedir place data at different
            # levels, so accept both layouts.
            directories = [
                module_path.parents[2] / "assets" / "card_templates",
                module_path.parents[1] / "assets" / "card_templates",
            ]
        directory = next((item for item in directories if item.is_dir()), directories[0])
        if not directory.is_dir():
            return
        for path in sorted(directory.glob("*.png")):
            character = self.characters.get(path.stem)
            if character is None:
                continue
            # cv2.imread cannot reliably open non-ASCII Windows paths; decode
            # the bytes explicitly so Chinese character names work as files.
            image = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
            if image is None or image.size == 0:
                continue
            gray = cv2.resize(image, self.SIZE, interpolation=cv2.INTER_AREA)
            keypoints, descriptors = self._orb.detectAndCompute(gray, None)
            _, full_descriptors = self._feature_orb.detectAndCompute(image, None)
            self.templates.append(_Template(character, gray, keypoints, descriptors, full_descriptors))
        # Querying one indexed matcher is much cheaper than matching every
        # screenshot crop separately against all full-size template images.
        indexed = [item.full_descriptors for item in self.templates if item.full_descriptors is not None]
        if indexed:
            self._feature_matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
            self._feature_matcher.add(indexed)
            self._feature_matcher.train()
            self._feature_templates = [item for item in self.templates if item.full_descriptors is not None]
        self.set_gpu_enabled(use_gpu)

    @staticmethod
    def cuda_available() -> bool:
        try:
            import cv2

            return bool(hasattr(cv2, "cuda") and cv2.cuda.getCudaEnabledDeviceCount() > 0)
        except Exception:
            return False

    @property
    def acceleration_backend(self) -> str:
        return "OpenCL GPU" if self.use_gpu else "CPU"

    @staticmethod
    def hardware_acceleration_available() -> bool:
        """Return whether the card matcher can use a real OpenCL GPU."""
        return gpu_available()

    def set_gpu_enabled(self, enabled: bool) -> None:
        if self._cv2 is None:
            self.use_gpu = False
            return
        self._gpu_matcher = None
        if enabled and self._feature_templates and gpu_available():
            try:
                self._gpu_matcher = OpenClHammingMatcher(
                    [item.full_descriptors for item in self._feature_templates]
                )
            except Exception:
                self._gpu_matcher = None
        self.use_gpu = self._gpu_matcher is not None
        self._cv2.ocl.setUseOpenCL(self.use_gpu)

    @property
    def available(self) -> bool:
        return bool(self._cv2 is not None and self.templates)

    @staticmethod
    def _iou(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> float:
        ax, ay, aw, ah = left
        bx, by, bw, bh = right
        x1, y1 = max(ax, bx), max(ay, by)
        x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
        intersection = max(0, x2 - x1) * max(0, y2 - y1)
        union = aw * ah + bw * bh - intersection
        return intersection / union if union else 0.0

    def _card_boxes(self, image: np.ndarray) -> list[tuple[int, int, int, int]]:
        """Find portrait-like rectangles without running a second text detector."""
        cv2 = self._cv2
        if cv2 is None or image.ndim != 3:
            return []
        height, width = image.shape[:2]
        if self.use_gpu:
            image_gpu = cv2.UMat(image)
            gray_gpu = cv2.cvtColor(image_gpu, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray_gpu, 35, 120).get()
        else:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray, 35, 120)
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        min_height = max(55, int(height * 0.16))
        min_width = max(70, int(width * 0.035))
        # A screenshot may contain only the card itself, so the outer card
        # outline can occupy nearly the full recognition region.
        max_height = min(600, int(height * 0.95))
        candidates: list[tuple[int, int, int, int]] = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            ratio = w / max(h, 1)
            # The recognition template is the wide upper card panel (artwork
            # plus hero name), while older libraries used a narrow portrait.
            # Keep the legacy range and allow the new red-box aspect ratio.
            if not (min_height <= h <= max_height and 0.48 <= ratio <= 1.35):
                continue
            if w < min_width or w * h < 7000:
                continue
            candidates.append((x, y, w, h))

        # In the shop row cards touch edge to edge, so contours often do not
        # close around every card. Add two staggered passes of normalized
        # windows for a short, card-row-only capture.
        if height <= 400:
            panel_height = max(55, int(height * 0.78))
            panel_width = max(70, int(panel_height * 0.95))
            top = max(0, int(height * 0.18))
            for offset in (0, panel_width // 2):
                for x in range(offset, width, panel_width):
                    if x + panel_width <= width:
                        candidates.append((x, top, panel_width, panel_height))

        # Keep the largest outline when both the border and inner portrait were
        # detected.  The order is stable for overlay rendering.
        candidates.sort(key=lambda value: value[2] * value[3], reverse=True)
        kept: list[tuple[int, int, int, int]] = []
        for candidate in candidates:
            if any(self._iou(candidate, previous) > 0.72 for previous in kept):
                continue
            kept.append(candidate)
        return sorted(kept, key=lambda value: (value[1], value[0]))

    def _score(self, crop: np.ndarray, template: _Template, descriptors: np.ndarray | None = None) -> float:
        cv2 = self._cv2
        if cv2 is None:
            return 0.0
        if crop.ndim == 2 and crop.shape[:2] == (self.SIZE[1], self.SIZE[0]):
            gray = crop
        elif self.use_gpu:
            gray_gpu = cv2.cvtColor(cv2.UMat(crop), cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else cv2.UMat(crop)
            gray = cv2.resize(gray_gpu, self.SIZE, interpolation=cv2.INTER_AREA).get()
        else:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
            gray = cv2.resize(gray, self.SIZE, interpolation=cv2.INTER_AREA)
        # Normalized correlation handles DPI and card-size changes.  Ignore a
        # small border so the tier dots and rounded frame do not dominate it.
        a = gray[4:-4, 4:-4].astype(np.float32)
        b = template.gray[4:-4, 4:-4].astype(np.float32)
        a -= a.mean()
        b -= b.mean()
        denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
        correlation = float(np.sum(a * b) / denominator) if denominator else 0.0
        correlation = max(0.0, min(1.0, (correlation + 1.0) / 2.0))

        orb_score = 0.0
        if template.descriptors is not None:
            if descriptors is None and self._orb is not None:
                _, descriptors = self._orb.detectAndCompute(gray, None)
            if descriptors is not None and len(descriptors):
                matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
                pairs = matcher.knnMatch(template.descriptors, descriptors, k=2)
                good = sum(1 for pair in pairs if len(pair) == 2 and pair[0].distance < 0.78 * pair[1].distance)
                orb_score = min(1.0, good / 10.0)
        # Correlation is the stable signal for this fixed portrait layout;
        # ORB is only a bonus because some cards have very few keypoints.
        return 0.82 * correlation + 0.18 * orb_score

    def _best(self, image: np.ndarray, box: tuple[int, int, int, int]) -> tuple[_Template, float] | None:
        cv2 = self._cv2
        if cv2 is None:
            return None
        x, y, w, h = box
        crop = image[max(0, y): y + h, max(0, x): x + w]
        if crop.size == 0:
            return None
        if self.use_gpu:
            return self._feature_best(crop)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        gray = cv2.resize(gray, self.SIZE, interpolation=cv2.INTER_AREA)
        descriptors = None
        if self._orb is not None:
            _, descriptors = self._orb.detectAndCompute(gray, None)
        ranked = sorted(
            ((self._score(gray, item, descriptors), item) for item in self.templates),
            reverse=True,
            key=lambda value: value[0],
        )
        if not ranked:
            return None
        score, template = ranked[0]
        # A margin rejects background rectangles that happen to look vaguely
        # like a card.  The threshold is intentionally conservative because
        # OCR is still available as a fallback.
        margin = score - ranked[1][0] if len(ranked) > 1 else score
        # Lower-scoring matches are usually board artwork or UI controls. A
        # stricter floor prevents the displayed camp from changing between
        # unrelated candidates as the game animates.
        if score >= 0.72 and (score >= 0.82 or margin >= 0.05):
            return template, score

        return self._feature_best(crop)

    def _feature_best(self, crop: np.ndarray) -> tuple[_Template, float] | None:
        # The fixed-size correlation falls sharply when a live card is
        # stretched or partially dimmed. Native-resolution keypoints still
        # recognize its artwork, provided they agree on one template.
        if self._feature_matcher is None or self._feature_orb is None:
            return None
        cv2 = self._cv2
        crop_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        _, native_descriptors = self._feature_orb.detectAndCompute(crop_gray, None)
        if native_descriptors is None:
            return None
        if self._gpu_matcher is not None:
            try:
                gpu_votes = self._gpu_matcher.votes(native_descriptors)
                votes = {index: int(count) for index, count in enumerate(gpu_votes) if count}
            except Exception:
                self.set_gpu_enabled(False)
                votes = self._cpu_feature_votes(native_descriptors)
        else:
            votes = self._cpu_feature_votes(native_descriptors)
        ranked_votes = sorted(votes.items(), key=lambda value: value[1], reverse=True)
        if not ranked_votes:
            return None
        winner, count = ranked_votes[0]
        runner_up = ranked_votes[1][1] if len(ranked_votes) > 1 else 0
        if count < 12 or count - runner_up < 6:
            return None
        return self._feature_templates[winner], min(1.0, 0.72 + count / 250)

    def _cpu_feature_votes(self, descriptors: np.ndarray) -> dict[int, int]:
        votes: dict[int, int] = {}
        for pair in self._feature_matcher.knnMatch(descriptors, k=2):
            if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance:
                index = pair[0].imgIdx
                votes[index] = votes.get(index, 0) + 1
        return votes

    def match(self, image: np.ndarray, ocr_detections: list[OcrDetection]) -> list[Match]:
        if not self.available or not isinstance(image, np.ndarray):
            return []
        candidates: list[tuple[Match, tuple[int, int, int, int]]] = []
        for x, y, w, h in self._card_boxes(image):
            # Edge detection often returns the outline of the complete card
            # (portrait aspect), while the template is its upper red-box
            # panel. Try that normalized panel in addition to the full box.
            boxes = [(x, y, w, h)]
            if w / max(h, 1) < 0.92:
                panel_height = max(1, int(h * 0.64))
                inset = max(0, int(w * 0.01))
                boxes.insert(0, (x + inset, y, max(1, w - inset * 2), panel_height))
            selected = next(
                ((box, candidate) for box in boxes if (candidate := self._best(image, box)) is not None),
                None,
            )
            if selected is None:
                continue
            box, result = selected
            template, score = result
            # Keep matching against the complete panel, while exposing only
            # the bottom name strip to the common OCR/overlay pipeline.
            name_box = self._name_box(box, image.shape[0])
            detection = OcrDetection(
                text=template.character.name,
                confidence=score,
                box=Box(name_box[0], name_box[1], name_box[0] + name_box[2], name_box[1] + name_box[3]),
                source="card",
            )
            candidates.append((Match(detection=detection, character=template.character, score=score, source="card"), box))
        # The staggered row windows can overlap the same physical card. Keep
        # only the strongest result in each overlapping area.
        candidates.sort(key=lambda item: item[0].score, reverse=True)
        unique: list[tuple[Match, tuple[int, int, int, int]]] = []
        for item, full_box in candidates:
            if any(
                self._iou(full_box, previous_box)
                > (0.30 if item.character.name == previous.character.name else 0.55)
                for previous, previous_box in unique
            ):
                continue
            unique.append((item, full_box))
        return sorted((item for item, _ in unique), key=lambda item: (item.detection.box.top, item.detection.box.left))
