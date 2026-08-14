"""NABH / FHIR handover record (Feature 5).

Assembles a case's prehospital monitoring data (patient, encounter/transport,
vitals stream, digitized ECG records) into an interoperable handover document:

* ``build_fhir`` -> FHIR R4 JSON ``Bundle`` of type ``document``
  (Composition + Patient + Encounter + Practitioner + Location + vitals
  Observations + ECG DiagnosticReport/Observation pair).
* ``build_cda``  -> a simplified CDA R2-style XML envelope with the same
  clinical content as narrative sections.

This is an export of transportable prehospital monitoring data. It performs no
diagnostic interpretation (no rhythm diagnosis, no ECG conclusion) and every
document carries a research-prototype boundary statement. Access rules mirror
the ECG/vitals read path: the owning paramedic or any hospital staff.
"""

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from xml.etree import ElementTree

from ..models import (
    Ambulance,
    CaseEvent,
    EcgTracing,
    EmergencyCase,
    GpsPoint,
    Hospital,
    Patient,
    User,
    Vital,
)
from ..models.enums import UserRole
from ..models.user import utcnow

BOUNDARY_STATEMENT = (
    "Export of prehospital monitoring data captured by MEDHA LINK during an "
    "emergency response. Research prototype - not a certified medical record. "
    "The digitized ECG trace and vital observations are transportable records; "
    "no diagnostic interpretation is made."
)

_LOINC = "http://loinc.org"
_UOM = "http://unitsofmeasure.org"
_V3_ACTC = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
_V2_0074 = "http://terminology.hl7.org/CodeSystem/v2-0074"

# (vital column, LOINC code, LOINC display, UCUM unit, display unit)
_VITAL_SPECS = [
    ("heart_rate", "8867-4", "Heart rate", "1/min", "/min"),
    ("spo2", "59408-5", "Oxygen saturation in Arterial blood", "%", "%"),
    ("systolic_bp", "8480-6", "Systolic blood pressure", "mm[Hg]", "mmHg"),
    ("diastolic_bp", "8462-4", "Diastolic blood pressure", "mm[Hg]", "mmHg"),
    ("temperature", "8310-5", "Body temperature", "Cel", "degC"),
    ("respiratory_rate", "9279-1", "Respiratory rate", "1/min", "/min"),
]

_SEX_TO_GENDER = {
    "m": "male",
    "f": "female",
    "M": "male",
    "F": "female",
    "male": "male",
    "female": "female",
}


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _case_or_404(db: Session, case_id: UUID) -> EmergencyCase:
    case = db.get(EmergencyCase, case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Case not found"
        )
    return case


def _check_access(case: EmergencyCase, user: User) -> None:
    if user.role == UserRole.paramedic and case.created_by_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized for this case",
        )


def _load_case(db: Session, case_id: UUID, user: User) -> EmergencyCase:
    case = _case_or_404(db, case_id)
    _check_access(case, user)
    return case


def _load_context(
    db: Session, case: EmergencyCase
) -> tuple[Patient | None, Ambulance | None, Hospital | None, list[Vital], list[EcgTracing], list[CaseEvent], GpsPoint | None]:
    patient = db.get(Patient, case.patient_id) if case.patient_id else None
    ambulance = db.get(Ambulance, case.ambulance_id) if case.ambulance_id else None
    hospital = db.get(Hospital, case.hospital_id) if case.hospital_id else None
    vitals = list(
        db.scalars(
            select(Vital)
            .where(Vital.case_id == case.id)
            .order_by(Vital.timestamp, Vital.hlc)
        )
    )
    ecgs = list(
        db.scalars(
            select(EcgTracing)
            .where(EcgTracing.case_id == case.id)
            .order_by(EcgTracing.captured_at)
        )
    )
    events = list(
        db.scalars(
            select(CaseEvent)
            .where(CaseEvent.case_id == case.id)
            .order_by(CaseEvent.created_at, CaseEvent.hlc)
        )
    )
    gps = db.scalar(
        select(GpsPoint)
        .where(GpsPoint.case_id == case.id)
        .order_by(GpsPoint.recorded_at.desc(), GpsPoint.hlc.desc())
        .limit(1)
    )
    return patient, ambulance, hospital, vitals, ecgs, events, gps


# ---------------------------------------------------------------------------
# FHIR R4 bundle
# ---------------------------------------------------------------------------

class _UuidRegistry:
    """Maps logical keys to stable per-document resource ids."""

    def __init__(self) -> None:
        self._ids: dict[str, str] = {}

    def resource(self, key: str) -> str:
        if key not in self._ids:
            self._ids[key] = str(uuid4())
        return self._ids[key]

    def ref(self, key: str) -> str:
        return f"urn:uuid:{self.resource(key)}"


def _entry(resource_id: str, resource: dict) -> dict:
    return {"fullUrl": f"urn:uuid:{resource_id}", "resource": resource}


def _patient_resource(registry, patient: Patient) -> dict:
    resource = {
        "resourceType": "Patient",
        "id": registry.resource(f"patient-{patient.id}"),
        "identifier": [
            {"system": "urn:medha:patient", "value": str(patient.id)}
        ],
        "name": [{"text": patient.name}],
        "gender": _SEX_TO_GENDER.get(patient.sex or "", "unknown"),
    }
    if patient.age is not None:
        resource["extension"] = [
            {
                "url": "http://hl7.org/fhir/StructureDefinition/patient-age",
                "valueAge": {
                    "value": patient.age,
                    "unit": "years",
                    "system": _UOM,
                    "code": "a",
                },
            }
        ]
    return resource


def _practitioner_resource(registry, user: User) -> dict:
    return {
        "resourceType": "Practitioner",
        "id": registry.resource(f"practitioner-{user.id}"),
        "identifier": [{"system": "urn:medha:user", "value": str(user.id)}],
        "name": [{"text": user.username}],
    }


def _location_resource(registry, hospital: Hospital | None, ambulance: Ambulance | None) -> dict | None:
    if hospital is None:
        return None
    resource: dict = {
        "resourceType": "Location",
        "id": registry.resource(f"location-{hospital.id}"),
        "name": hospital.name,
        "address": {"city": hospital.city},
    }
    if hospital.latitude is not None and hospital.longitude is not None:
        resource["position"] = {
            "latitude": float(hospital.latitude),
            "longitude": float(hospital.longitude),
        }
    if ambulance is not None:
        resource["description"] = f"Ambulance {ambulance.vehicle_number}"
    return resource


def _vital_observation(registry, case, patient, vital: Vital) -> dict:
    resource = {
        "resourceType": "Observation",
        "id": registry.resource(f"vital-{vital.id}"),
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "vital-signs",
                    }
                ]
            }
        ],
        "code": {"coding": []},
        "subject": registry.ref(f"patient-{patient.id}") if patient else None,
        "encounter": registry.ref(f"encounter-{case.id}"),
        "effectiveDateTime": _iso(vital.timestamp),
    }
    components = []
    for attr, code, display, unit_code, unit in _VITAL_SPECS:
        value = getattr(vital, attr)
        if value is None:
            continue
        components.append(
            {
                "code": {"coding": [{"system": _LOINC, "code": code, "display": display}]},
                "valueQuantity": {
                    "value": float(value),
                    "unit": unit,
                    "system": _UOM,
                    "code": unit_code,
                },
            }
        )
    if not components:
        return None
    if vital.heart_rate is not None:
        resource["code"]["coding"].append(
            {"system": _LOINC, "code": "8867-4", "display": "Heart rate"}
        )
    else:
        resource["code"]["coding"].append(components[0]["code"]["coding"][0])
    resource["component"] = components
    return resource


def _ecg_report(registry, case, patient, ecg: EcgTracing) -> tuple[dict, dict]:
    """Returns (DiagnosticReport, waveform Observation) for one tracing."""
    obs_id = registry.resource(f"ecg-waveform-{ecg.id}")
    report_id = registry.resource(f"ecg-report-{ecg.id}")
    waveform_json = json.dumps(ecg.waveform) if ecg.waveform is not None else None
    quality = ecg.quality or {}

    waveform_obs: dict = {
        "resourceType": "Observation",
        "id": obs_id,
        "status": "final",
        "code": {
            "coding": [{"system": _LOINC, "code": "11524-6", "display": "EKG study"}]
        },
        "subject": registry.ref(f"patient-{patient.id}") if patient else None,
        "encounter": registry.ref(f"encounter-{case.id}"),
        "effectiveDateTime": _iso(ecg.captured_at),
    }
    if waveform_json is not None:
        waveform_obs["extension"] = [
            {
                "url": "http://medha.example/fhir/StructureDefinition/ecg-waveform-mm",
                "valueString": waveform_json,
            }
        ]
    component = [
        {
            "code": {"coding": [{"system": _LOINC, "code": "44966-6", "display": "Lead count"}]},
            "valueInteger": ecg.lead_count,
        }
        if ecg.lead_count is not None
        else None,
        {
            "code": {"coding": [{"system": _LOINC, "code": "44967-4", "display": "Paper speed"}]},
            "valueString": ecg.paper_speed,
        }
        if ecg.paper_speed
        else None,
    ]
    waveform_obs["component"] = [c for c in component if c is not None]
    waveform_obs["note"] = [
        {
            "text": (
                f"Quality check {'passed' if quality.get('checks_passed') else 'failed'}"
                f" (warnings: {', '.join(quality.get('warnings') or []) or 'none'}). "
                + BOUNDARY_STATEMENT
            )
        }
    ]

    report: dict = {
        "resourceType": "DiagnosticReport",
        "id": report_id,
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": _V2_0074,
                        "code": "EC",
                        "display": "Electrocardiography",
                    }
                ]
            }
        ],
        "code": {
            "coding": [{"system": _LOINC, "code": "11524-6", "display": "EKG study"}]
        },
        "subject": registry.ref(f"patient-{patient.id}") if patient else None,
        "encounter": registry.ref(f"encounter-{case.id}"),
        "effectiveDateTime": _iso(ecg.captured_at),
        "result": [registry.ref(f"ecg-waveform-{ecg.id}")],
    }
    if ecg.notes:
        report["note"] = [{"text": ecg.notes}]
    return report, waveform_obs


def _encounter_resource(registry, case, hospital, ambulance, gps) -> dict:
    resource = {
        "resourceType": "Encounter",
        "id": registry.resource(f"encounter-{case.id}"),
        "identifier": [
            {"system": "urn:medha:case", "value": str(case.id)}
        ],
        "status": "finished" if case.status.value == "closed" else "in-progress",
        "class": {
            "system": _V3_ACTC,
            "code": "EMER",
            "display": "emergency",
        },
        "subject": registry.ref(f"patient-{case.patient_id}"),
        "period": {
            "start": _iso(case.created_at),
            "end": _iso(case.closed_at),
        },
        "location": [],
    }
    if case.chief_complaint:
        resource["reasonCode"] = [{"text": case.chief_complaint}]
    if case.severity is not None:
        resource["priority"] = {"text": str(case.severity.value)}
    if hospital is not None:
        resource["location"].append(
            {"location": registry.ref(f"location-{hospital.id}")}
        )
    if gps is not None and gps.latitude is not None and gps.longitude is not None:
        resource["extension"] = [
            {
                "url": "http://medha.example/fhir/StructureDefinition/last-known-position",
                "valueString": (
                    f"{float(gps.latitude):.6f},{float(gps.longitude):.6f}"
                    f" @ {_iso(gps.recorded_at)}"
                ),
            }
        ]
    return resource


def _composition_resource(
    registry,
    case,
    patient,
    author: User,
    ambulance: Ambulance | None,
    hospital: Hospital | None,
    vital_refs: list[str],
    ecg_report_refs: list[str],
    event_lines: list[str],
) -> dict:
    section = lambda title, entries, text=None: {
        "title": title,
        "entry": [{"reference": ref} for ref in entries],
        **({"text": {"status": "generated", "div": f"<div>{text}</div>"}} if text else {}),
    }
    transport_lines = [
        f"Ambulance: {ambulance.vehicle_number}" if ambulance else "Ambulance: not assigned",
        f"Status: {case.status.value}",
    ]
    if case.severity is not None:
        transport_lines.append(f"Severity: {case.severity.value}")
    if case.chief_complaint:
        transport_lines.append(f"Chief complaint: {case.chief_complaint}")
    if case.gcs is not None:
        transport_lines.append(f"GCS: {case.gcs}")
    if case.medications:
        transport_lines.append(f"Medications: {case.medications}")
    if hospital is not None:
        transport_lines.append(f"Destination: {hospital.name}, {hospital.city}")
    if case.acceptance_status is not None:
        transport_lines.append(f"Acceptance: {case.acceptance_status.value}")
    if event_lines:
        transport_lines.append("Timeline: " + "; ".join(event_lines))

    composition: dict = {
        "resourceType": "Composition",
        "id": registry.resource(f"composition-{case.id}"),
        "status": "final",
        "type": {
            "coding": [
                {
                    "system": _LOINC,
                    "code": "57016-8",
                    "display": "Emergency department Note",
                }
            ]
        },
        "subject": registry.ref(f"patient-{case.patient_id}"),
        "date": _iso(utcnow()),
        "author": [registry.ref(f"practitioner-{author.id}")],
        "title": "MEDHA LINK prehospital handover",
        "confidentiality": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-Confidentiality",
                    "code": "N",
                    "display": "normal",
                }
            ]
        },
        "section": [
            section("Record scope", [], BOUNDARY_STATEMENT),
            section("Patient", [registry.ref(f"patient-{patient.id}")] if patient else []),
            section("Encounter / Transport", [registry.ref(f"encounter-{case.id}")], "<br/>".join(transport_lines)),
            section("Vital signs", vital_refs, f"{len(vital_refs)} vital reading(s)."),
            section("ECG", ecg_report_refs, f"{len(ecg_report_refs)} digitized ECG tracing(s)."),
        ],
    }
    return composition


def build_fhir(db: Session, case_id: UUID, user: User) -> dict:
    """Assemble an FHIR R4 ``Bundle`` (type ``document``) for the case."""
    case = _load_case(db, case_id, user)
    patient, ambulance, hospital, vitals, ecgs, events, gps = _load_context(db, case)

    registry = _UuidRegistry()
    entries: list[dict] = []

    author = case.created_by or user
    if patient:
        entries.append(_entry(registry.resource(f"patient-{patient.id}"), _patient_resource(registry, patient)))
    entries.append(_entry(registry.resource(f"practitioner-{author.id}"), _practitioner_resource(registry, author)))
    location = _location_resource(registry, hospital, ambulance)
    if location is not None:
        entries.append(_entry(registry.resource(f"location-{hospital.id}"), location))
    entries.append(_entry(registry.resource(f"encounter-{case.id}"), _encounter_resource(registry, case, hospital, ambulance, gps)))

    vital_refs: list[str] = []
    for vital in vitals:
        obs = _vital_observation(registry, case, patient, vital)
        if obs is None:
            continue
        vital_refs.append(registry.ref(f"vital-{vital.id}"))
        entries.append(_entry(registry.resource(f"vital-{vital.id}"), obs))

    ecg_report_refs: list[str] = []
    for ecg in ecgs:
        report, waveform_obs = _ecg_report(registry, case, patient, ecg)
        ecg_report_refs.append(registry.ref(f"ecg-report-{ecg.id}"))
        entries.append(_entry(registry.resource(f"ecg-waveform-{ecg.id}"), waveform_obs))
        entries.append(_entry(registry.resource(f"ecg-report-{ecg.id}"), report))

    event_lines = [
        f"{ev.created_at.isoformat()} {ev.event_type.value}"
        for ev in events
    ]
    composition = _composition_resource(
        registry,
        case,
        patient,
        author,
        ambulance,
        hospital,
        vital_refs,
        ecg_report_refs,
        event_lines,
    )
    entries.append(_entry(registry.resource(f"composition-{case.id}"), composition))

    return {
        "resourceType": "Bundle",
        "type": "document",
        "timestamp": _iso(utcnow()),
        "identifier": {"system": "urn:medha:handover", "value": f"case/{case.id}"},
        "entry": entries,
    }


# ---------------------------------------------------------------------------
# CDA-style XML envelope
# ---------------------------------------------------------------------------

_NS = "urn:hl7-org:v3"
_CDA_LOINC = "2.16.840.1.113883.6.1"


def _el(parent, tag: str, text: str | None = None, attrs: dict | None = None):
    node = ElementTree.SubElement(parent, f"{{{_NS}}}{tag}")
    if text is not None:
        node.text = text
    if attrs:
        for key, value in attrs.items():
            node.set(key, value)
    return node


def build_cda(db: Session, case_id: UUID, user: User) -> str:
    """Assemble a simplified CDA R2-style XML envelope (narrative-only)."""
    case = _load_case(db, case_id, user)
    patient, ambulance, hospital, vitals, ecgs, events, gps = _load_context(db, case)
    author = case.created_by or user

    ElementTree.register_namespace("", _NS)
    doc = ElementTree.Element(f"{{{_NS}}}ClinicalDocument")
    _el(doc, "typeId", attrs={"root": "2.16.840.1.113883.1.3", "extension": "POCD_HD000040"})
    _el(doc, "id", attrs={"root": "urn:medha", "extension": str(case.id)})
    _el(
        doc, "code",
        attrs={
            "code": "57016-8",
            "codeSystem": _CDA_LOINC,
            "codeSystemName": "LOINC",
            "displayName": "Emergency department Note",
        },
    )
    _el(doc, "title", "MEDHA LINK prehospital handover")
    _el(doc, "effectiveTime", attrs={"value": (_iso(case.created_at) or "").replace("-", "").replace(":", "").replace("Z", "")})
    _el(doc, "confidentialityCode", attrs={"code": "N", "codeSystem": "2.16.840.1.113883.5.25"})

    # recordTarget
    record_target = _el(doc, "recordTarget")
    patient_role = _el(record_target, "patientRole")
    _el(patient_role, "id", attrs={"root": "urn:medha", "extension": str(patient.id)} if patient else {})
    if patient is not None:
        patient_node = _el(patient_role, "patient")
        name_node = _el(patient_node, "name")
        _el(name_node, "text", patient.name)
        gender_code = _SEX_TO_GENDER.get(patient.sex or "", "unknown")
        code = {"male": "M", "female": "F"}.get(gender_code, "UN")
        _el(patient_node, "administrativeGenderCode", attrs={"code": code, "codeSystem": "2.16.840.1.113883.5.1"})
        if patient.age is not None:
            _el(patient_node, "age", str(patient.age), attrs={"unit": "a", "value": str(patient.age)})

    # author
    author_node = _el(doc, "author")
    _el(author_node, "time", attrs={"value": (_iso(case.created_at) or "").replace("-", "").replace(":", "").replace("Z", "")})
    assigned = _el(author_node, "assignedAuthor")
    _el(assigned, "id", attrs={"root": "urn:medha", "extension": str(author.id)})
    person = _el(assigned, "assignedPerson")
    aname = _el(person, "name")
    _el(aname, "text", author.username)

    # custodian
    custodian = _el(doc, "custodian")
    assigned_custodian = _el(custodian, "assignedCustodian")
    org = _el(assigned_custodian, "representedCustodianOrganization")
    _el(org, "name", "MEDHA LINK (research prototype)")

    # component -> structuredBody
    component = _el(doc, "component")
    body = _el(component, "structuredBody")

    def _add_section(title: str, narrative: str):
        sec = _el(body, "component")
        section = _el(sec, "section")
        _el(section, "title", title)
        text_node = _el(section, "text")
        for i, line in enumerate(narrative.split("\n")):
            _el(text_node, "paragraph", line)

    scope = BOUNDARY_STATEMENT + (
        f" Case {case.id} created {_iso(case.created_at)} by {author.username}."
    )
    _add_section("Record scope", scope)

    transport = []
    transport.append(f"Ambulance: {ambulance.vehicle_number}" if ambulance else "Ambulance: not assigned")
    transport.append(f"Status: {case.status.value}")
    if case.severity is not None:
        transport.append(f"Severity: {case.severity.value}")
    if case.chief_complaint:
        transport.append(f"Chief complaint: {case.chief_complaint}")
    if case.gcs is not None:
        transport.append(f"GCS: {case.gcs}")
    if case.medications:
        transport.append(f"Medications: {case.medications}")
    if hospital is not None:
        transport.append(f"Destination: {hospital.name}, {hospital.city}")
    if case.acceptance_status is not None:
        transport.append(f"Acceptance: {case.acceptance_status.value}")
    if gps is not None:
        transport.append(f"Last known position: {float(gps.latitude):.6f}, {float(gps.longitude):.6f}")
    transport.append("Timeline: " + "; ".join(f"{e.created_at.isoformat()} {e.event_type.value}" for e in events))
    _add_section("Encounter / Transport", "\n".join(transport))

    vital_lines = []
    for vital in vitals:
        parts = [f"[{_iso(vital.timestamp)}]"]
        for attr, code, display, unit_code, unit in _VITAL_SPECS:
            value = getattr(vital, attr)
            if value is not None:
                parts.append(f"{display}: {value} {unit}")
        vital_lines.append(", ".join(parts))
    if not vital_lines:
        vital_lines.append("No vital readings recorded.")
    _add_section("Vital signs", "\n".join(vital_lines))

    ecg_lines = []
    for ecg in ecgs:
        quality = ecg.quality or {}
        line = (
            f"[{_iso(ecg.captured_at)}] source={ecg.source} leads={ecg.lead_count} "
            f"speed={ecg.paper_speed} mm/s quality_checks_passed={quality.get('checks_passed')} "
            f"warnings={', '.join(quality.get('warnings') or [])}"
        )
        if ecg.waveform is not None:
            line += f" waveform={json.dumps(ecg.waveform)}"
        if ecg.notes:
            line += f" notes={ecg.notes}"
        ecg_lines.append(line)
    if not ecg_lines:
        ecg_lines.append("No ECG tracings recorded.")
    _add_section("ECG", "\n".join(ecg_lines))

    return ElementTree.tostring(doc, encoding="unicode", xml_declaration=True)
