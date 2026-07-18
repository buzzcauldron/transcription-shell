"""Project JSON schema for a measured sample."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class Point(BaseModel):
    x: float
    y: float


class RingTick(BaseModel):
    """A ring boundary intersection along a measurement path (distance from path start)."""

    distance_px: float
    year: int | None = None
    confidence: float = 1.0
    flag: Literal["ok", "missing", "false", "uncertain"] = "ok"
    note: str = ""


class MeasurePath(BaseModel):
    id: str = "path0"
    points: list[Point] = Field(default_factory=list)
    rings: list[RingTick] = Field(default_factory=list)
    # Optional second path for incline correction
    incline_partner_id: str | None = None


class ScaleInfo(BaseModel):
    micrometers_per_pixel: float | None = None
    unit: Literal["um", "mm", "cm"] = "um"
    # Optional calibration segment in image coords
    p1: Point | None = None
    p2: Point | None = None
    known_length: float | None = None
    known_unit: Literal["um", "mm", "cm"] | None = None


class Project(BaseModel):
    version: int = 1
    image_path: str
    sample_code: str = ""
    species: str = ""
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    outer_year: int | None = None
    pith_year: int | None = None
    pith: Point | None = None
    sample_type: Literal["core", "disc"] = "core"
    preprocess_preset: str = "sanded_core"
    detect_method: Literal["classical", "unet"] = "classical"
    scale: ScaleInfo = Field(default_factory=ScaleInfo)
    paths: list[MeasurePath] = Field(default_factory=list)
    # Extra painted mask path relative to project dir (optional)
    paint_mask: str | None = None

    def primary_path(self) -> MeasurePath | None:
        return self.paths[0] if self.paths else None

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | str) -> "Project":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()
