import enum


class UserRole(str, enum.Enum):
    paramedic = "paramedic"
    doctor = "doctor"
    hospital_admin = "hospital_admin"


class AmbulanceStatus(str, enum.Enum):
    available = "available"
    en_route = "en_route"
    transporting = "transporting"
    offline = "offline"


class CaseSeverity(str, enum.Enum):
    low = "low"
    moderate = "moderate"
    high = "high"
    critical = "critical"


class CaseStatus(str, enum.Enum):
    active = "active"
    transporting = "transporting"
    at_hospital = "at_hospital"
    closed = "closed"


class CaseAcceptance(str, enum.Enum):
    accepted = "accepted"
    declined = "declined"


class VitalSource(str, enum.Enum):
    device = "device"
    simulated = "simulated"
    manual = "manual"


class CaseEventType(str, enum.Enum):
    scene_arrival = "scene_arrival"
    transport_start = "transport_start"
    hospital_arrival = "hospital_arrival"
    case_closed = "case_closed"
    severity_changed = "severity_changed"
    patient_updated = "patient_updated"
    note_added = "note_added"
    state_updated = "state_updated"
    hospital_accept = "hospital_accept"
    hospital_decline = "hospital_decline"
    hospital_prepare = "hospital_prepare"
