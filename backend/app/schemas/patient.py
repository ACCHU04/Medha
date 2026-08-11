from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PatientCreate(BaseModel):
    id: UUID | None = None
    device_id: UUID | None = None
    hlc: str | None = None
    name: str = Field(min_length=1, max_length=128)
    age: int | None = Field(default=None, ge=0, le=130)
    sex: str | None = Field(default=None, max_length=16)
    blood_type: str | None = Field(default=None, max_length=8)
    medical_history: dict | None = None


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    age: int | None
    sex: str | None
    blood_type: str | None
    medical_history: dict | None
    created_by_id: UUID | None
    created_at: datetime
