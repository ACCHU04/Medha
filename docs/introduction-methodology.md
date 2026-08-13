# MEDHA LINK — Introduction & Methodology

## Introduction

MEDHA LINK is a pre-hospital emergency response and telemetry coordination platform built to solve a core problem in emergency medical services: during a live case, the paramedic in the ambulance, the hospital staff waiting to receive the patient, and the doctors coordinating care are all disconnected — relying on paper forms and verbal handoffs that are slow, error-prone, and untraceable.

MEDHA LINK closes this gap by streaming case data live, end-to-end: a paramedic captures patient and case details on an ambulance-side interface; vitals, GPS location, and case events stream to the hospital in real time; hospital staff see the incoming case — vitals, severity, ETA — the moment monitoring starts, not when the ambulance pulls in. On arrival, the system produces a structured digital handover instead of a verbal one, exportable in standard clinical formats (FHIR R4 / CDA). A bilingual (English/Hindi) voice-and-text AI assistant is embedded throughout to speed up field documentation.

The current build is the Phase 1 monorepo: a full-stack FastAPI + PostgreSQL system with realtime WebSocket streaming, offline-first sync, paper-ECG digitization, FHIR/CDA handover export, and Phase-1 browser UIs for the ambulance and hospital sides — all running on synthetic data only, as a research prototype.

## Methodology

The system was designed around four principles, each realized as a concrete component:

1. **Event-driven case lifecycle** — Every case is a forward-only state machine (`active → transporting → at_hospital → closed`), driven by typed events (scene arrival, transport start, hospital arrival, case closed, severity change). Illegal transitions are rejected (`409`); every transition is logged immutably, so the full case history is always replayable.

2. **Realtime-first architecture** — A single WebSocket broadcast layer carries vitals, GPS/ETA, and case-event updates. REST writes, offline sync pushes, and live streams all feed the same channel, so ambulance and hospital screens always reconcile to one shared state.

3. **Offline-first sync** — Since ambulances often lose connectivity, every record carries a Hybrid Logical Clock (HLC) for conflict-aware ordering. Clients queue changes locally and reconcile automatically via push/pull sync endpoints on reconnect — no data loss in dead zones.

4. **Interoperability by design** — Handovers export as FHIR R4 JSON Bundles and CDA R2-style XML with LOINC/UCUM coding, so the platform integrates with existing hospital EHR systems rather than inventing a proprietary format.

**Implementation stack:**

- **Backend:** Python 3.11, FastAPI, SQLAlchemy 2.0, Pydantic 2, PostgreSQL 16, Alembic (10 tables, 8 migrations)
- **Auth:** JWT bearer tokens, bcrypt hashing, role-based access (`paramedic`, `doctor`, `hospital_admin`)
- **Frontend (Phase 1):** Vanilla JS/HTML/CSS via FastAPI static mount, Leaflet maps, OSRM routing with haversine fallback
- **AI assistant:** Rules-based intent engine (fill/action/reply) + Web Speech API for bilingual voice
- **Testing:** pytest/httpx backend suite + headless Node contract tests for shared browser modules

**Validation:** an end-to-end seeded demo across all three roles — login → patient/case creation → live vitals monitoring → hospital accept/prepare → arrival → structured handover — verifying the full pipeline works consistently, with synthetic data throughout.
