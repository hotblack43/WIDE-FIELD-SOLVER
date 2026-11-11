"""Immutable camera-installation visible-sky mask calibration."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import numpy as np
from PIL import Image


class VisibleSkyMaskError(ValueError):
    """A configured installation mask is absent, ambiguous, or incompatible."""


def _immutable_bool(values: np.ndarray) -> np.ndarray:
    answer = np.asarray(values, dtype=bool).copy()
    answer.flags.writeable = False
    return answer


@dataclass(frozen=True)
class MaskLayers:
    static_mask: np.ndarray
    dynamic_mask: np.ndarray
    finite_mask: np.ndarray
    combined_mask: np.ndarray
    pixel_counts: Mapping[str, int]


@dataclass(frozen=True)
class VisibleSkyMask:
    visible_mask: np.ndarray
    status: str
    mask_id: str | None
    installation_id: str | None
    mask_sha256: str | None
    manifest_path: Path | None
    manifest: Mapping[str, object]

    @classmethod
    def load(
        cls,
        manifest_path: Path,
        *,
        installation_id: str,
        instrument: str,
        detector_shape: tuple[int, int],
        plane_layout: str,
        orientation: str,
    ) -> "VisibleSkyMask":
        path = Path(manifest_path).expanduser().resolve(strict=True)
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VisibleSkyMaskError(f"visible-sky manifest is unreadable: {path}") from exc
        if manifest.get("schema") != "wide-field-solver-visible-sky-mask-v1":
            raise VisibleSkyMaskError("visible-sky manifest schema is unsupported")
        if manifest.get("status") != "approved":
            raise VisibleSkyMaskError("visible-sky mask is not approved for production")
        checks = (
            ("installation", manifest.get("installation_id"), installation_id),
            ("instrument", manifest.get("instrument"), instrument),
            ("shape", tuple(manifest.get("detector_shape", ())), tuple(detector_shape)),
            ("plane layout", manifest.get("plane_layout"), plane_layout),
            ("orientation", manifest.get("orientation"), orientation),
        )
        for label, recorded, observed in checks:
            if recorded != observed:
                raise VisibleSkyMaskError(
                    f"visible-sky {label} mismatch: manifest={recorded!r}, runtime={observed!r}"
                )
        mask_name = manifest.get("mask_file")
        if not isinstance(mask_name, str) or Path(mask_name).name != mask_name:
            raise VisibleSkyMaskError("visible-sky mask file must be adjacent to its manifest")
        mask_path = path.parent / mask_name
        try:
            mask_bytes = mask_path.read_bytes()
        except OSError as exc:
            raise VisibleSkyMaskError(f"visible-sky mask is unreadable: {mask_path}") from exc
        digest = hashlib.sha256(mask_bytes).hexdigest()
        if digest != manifest.get("mask_sha256"):
            raise VisibleSkyMaskError("visible-sky mask checksum mismatch")
        with Image.open(mask_path) as image:
            pixels = np.asarray(image.convert("L"), dtype=np.uint8)
        expected_shape = tuple(manifest["detector_shape"])
        if pixels.shape != expected_shape:
            raise VisibleSkyMaskError(
                f"visible-sky mask file shape mismatch: {pixels.shape} != {expected_shape}"
            )
        values = set(np.unique(pixels).tolist())
        if not values.issubset({0, 255}):
            raise VisibleSkyMaskError(
                f"visible-sky mask must be binary 0/255, found {sorted(values)}"
            )
        return cls(
            visible_mask=_immutable_bool(pixels == 255),
            status="approved",
            mask_id=str(manifest["mask_id"]),
            installation_id=str(manifest["installation_id"]),
            mask_sha256=digest,
            manifest_path=path,
            manifest=MappingProxyType(dict(manifest)),
        )

    @classmethod
    def not_configured(cls, detector_shape: tuple[int, int]) -> "VisibleSkyMask":
        shape = tuple(int(value) for value in detector_shape)
        if len(shape) != 2 or min(shape) <= 0:
            raise VisibleSkyMaskError("detector shape must contain two positive dimensions")
        return cls(
            visible_mask=_immutable_bool(np.ones(shape, dtype=bool)),
            status="not_configured",
            mask_id=None,
            installation_id=None,
            mask_sha256=None,
            manifest_path=None,
            manifest=MappingProxyType({"status": "not_configured"}),
        )

    def combine(self, dynamic_mask: np.ndarray, finite_mask: np.ndarray) -> MaskLayers:
        dynamic = np.asarray(dynamic_mask, dtype=bool)
        finite = np.asarray(finite_mask, dtype=bool)
        shape = self.visible_mask.shape
        if dynamic.shape != shape or finite.shape != shape:
            raise VisibleSkyMaskError(
                f"mask layer shape mismatch: static={shape}, dynamic={dynamic.shape}, "
                f"finite={finite.shape}"
            )
        static = _immutable_bool(self.visible_mask)
        dynamic = _immutable_bool(dynamic)
        finite = _immutable_bool(finite)
        combined = _immutable_bool(static & dynamic & finite)
        counts = MappingProxyType({
            "total": int(static.size),
            "static_visible": int(static.sum()),
            "dynamic": int(dynamic.sum()),
            "finite": int(finite.sum()),
            "combined": int(combined.sum()),
        })
        return MaskLayers(static, dynamic, finite, combined, counts)
