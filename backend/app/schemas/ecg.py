"""Digitized ECG payloads (Feature 4).

The write path is offline-first: the ambulance captures a paper ECG photo,
digitizes it in the browser, and pushes it through the sync outbox as an
``ecg`` entity whose data validates against ``EcgSyncPayload``. Images travel
as base64 strings inside the op payload and are decoded server-side into
BYTEA. The read path returns metadata + waveform but never the raw bytes
(those come from the dedicated image endpoint).
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class EcgGridBounds(BaseModel):
    x: int
    y: int
    w: int
    h: int


class EcgGrid(BaseModel):
    """Detected ECG grid geometry in normalized-image pixels."""
    mm_per_px_x: float
    mm_per_px_y: float
    bounds: EcgGridBounds | None = None


class WaveformChannel(BaseModel):
    """One digitized trace: ordered x/y samples in grid millimeters."""
    name: str | None = None
    sample_mm: float = Field(default=2.0, gt=0)
    points: list[list[float]]


class EcgWaveform(BaseModel):
    grid: EcgGrid | None = None
    channels: list[WaveformChannel] = Field(default_factory=list)


class EcgQuality(BaseModel):
    resolution: dict | None = None
    blur_score: float | None = None
    contrast_score: float | None = None
    brightness: float | None = None
    checks_passed: bool = False
    warnings: list[str] = Field(default_factory=list)


class EcgSyncPayload(BaseModel):
    """Validated inside the sync apply layer (mirrors VitalCreate usage)."""
    case_id: UUID
    captured_at: datetime | None = None
    source: str = "paper_photo"
    lead_count: int | None = Field(default=None, ge=1, le=16)
    paper_speed: str = "25"
    image_original: str = Field(min_length=1)
    image_normalized: str | None = None
    waveform: dict | None = None
    quality: dict | None = None
    notes: str | None = None


class EcgOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    case_id: UUID
    captured_by: str | None = None
    captured_at: datetime
    source: str
    lead_count: int | None
    paper_speed: str
    waveform: dict | None
    quality: dict | None
    notes: str | None
    created_at: datetime
