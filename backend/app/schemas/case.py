from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from ..models.enums import CaseAcceptance, CaseSeverity, CaseStatus
from .ambulance import AmbulanceOut
from .hospital import HospitalOut
from .patient import PatientOut


class CaseCreate(BaseModel):
    id: UUID | None = None
    device_id: UUID | None = None
    hlc: str | None = None
    patient_id: UUID
    ambulance_id: UUID
    chief_complaint: str | None = None
    severity: CaseSeverity | None = None


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    ambulance_id: UUID | None
    hospital_id: UUID | None
    severity: CaseSeverity | None
    status: CaseStatus
    chief_complaint: str | None
    created_by_id: UUID | None
    created_at: datetime
    closed_at: datetime | None
    acceptance: CaseAcceptance | None = None
    decision_by_id: UUID | None = None
    decision_at: datetime | None = None
    decline_reason: str | None = None
    recommended_hospital_id: UUID | None = None
    prepared_at: datetime | None = None
    preparation_notes: dict | None = None
    route_geojson: dict | None = None
    patient: PatientOut | None = None
    ambulance: AmbulanceOut | None = None
    destination_hospital: HospitalOut | None = None
    recommended_hospital: HospitalOut | None = None
    eta_minutes: int | None = None
