from __future__ import annotations

import ctypes
from pathlib import Path
from typing import Any

import numpy as np

from .models import Box, OcrDetection


class OcrUnavailableError(RuntimeError):
    pass


class RapidOcrEngine:
    def __init__(self, use_gpu: bool = False) -> None:
        self.use_gpu = bool(use_gpu and self.hardware_acceleration_available())
        self._engine: Any = None
        self._active_provider = "CPUExecutionProvider"

    @staticmethod
    def cuda_available() -> bool:
        """Return whether the installed ONNX Runtime exposes NVIDIA CUDA."""
        try:
            import onnxruntime as ort

            if "CUDAExecutionProvider" not in ort.get_available_providers():
                return False
            # get_available_providers() can list CUDA even when the provider
            # DLL cannot load because CUDA/cuDNN DLLs are absent. Probe the
            # provider library so the switch is disabled instead of causing a
            # noisy first-recognition fallback.
            if hasattr(ctypes, "WinDLL") and ort.__file__:
                provider_dll = Path(ort.__file__).parent / "capi" / "onnxruntime_providers_cuda.dll"
                if provider_dll.exists():
                    ctypes.WinDLL(str(provider_dll))
            return True
        except Exception:
            return False

    @staticmethod
    def directml_available() -> bool:
        try:
            import onnxruntime as ort

            return "DmlExecutionProvider" in ort.get_available_providers()
        except Exception:
            return False

    @classmethod
    def hardware_acceleration_available(cls) -> bool:
        return cls.cuda_available() or cls.directml_available()

    @property
    def active_provider(self) -> str:
        return self._active_provider

    def set_gpu_enabled(self, enabled: bool) -> None:
        """Change the execution mode; the next recognition rebuilds sessions."""
        desired = bool(enabled and self.hardware_acceleration_available())
        if desired == self.use_gpu:
            return
        self.use_gpu = desired
        self._engine = None
        self._active_provider = "CPUExecutionProvider"

    def _load(self) -> Any:
        if self._engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as exc:
                raise OcrUnavailableError("未安装 RapidOCR，请运行安装脚本") from exc
            use_cuda = self.use_gpu and self.cuda_available()
            use_dml = self.use_gpu and not use_cuda and self.directml_available()
            kwargs = {
                "det_use_cuda": use_cuda,
                "cls_use_cuda": use_cuda,
                "rec_use_cuda": use_cuda,
                "det_use_dml": use_dml,
                "cls_use_dml": use_dml,
                "rec_use_dml": use_dml,
            }
            try:
                self._engine = RapidOCR(**kwargs)
            except Exception:
                # A CUDA provider can be listed while its driver DLLs are
                # unavailable. Keep the app usable and transparently fall
                # back to CPU for this run.
                if not self.use_gpu:
                    raise
                self.use_gpu = False
                self._engine = RapidOCR(
                    det_use_cuda=False,
                    cls_use_cuda=False,
                    rec_use_cuda=False,
                    det_use_dml=False,
                    cls_use_dml=False,
                    rec_use_dml=False,
                )
            try:
                self._active_provider = self._engine.text_det.infer.session.get_providers()[0]
            except (AttributeError, IndexError):
                self._active_provider = "CPUExecutionProvider"
            if self._active_provider not in {"CUDAExecutionProvider", "DmlExecutionProvider"}:
                # ONNX Runtime may advertise CUDA while its CUDA/cuDNN DLLs
                # are missing. RapidOCR then silently creates CPU sessions.
                self.use_gpu = False
        return self._engine

    def recognize(self, image: np.ndarray) -> list[OcrDetection]:
        result, _elapsed = self._load()(image)
        if not result:
            return []

        detections: list[OcrDetection] = []
        for item in result:
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue
            points, text, confidence = item[0], str(item[1]).strip(), float(item[2])
            if not text or points is None or len(points) == 0:
                continue
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            detections.append(
                OcrDetection(
                    text=text,
                    confidence=confidence,
                    box=Box(int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))),
                )
            )
        return detections
