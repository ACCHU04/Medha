# Dashboard Handover — Manual Walkthrough

**Feature:** Hospital dashboard handover view + FHIR / CDA / PDF export (Feature 6)
**Status:** Manual acceptance checklist
**Date:** 2026-08-11

## Scope of this checklist

This walkthrough verifies that a hospital staff member can open a case and
produce an interoperable handover of the prehospital monitoring data captured
by MEDHA LINK — as a machine-readable **FHIR R4 JSON** document, a **CDA
R2-style XML** document, and a **printable human-readable** handover (browser
"Save as PDF"). It also verifies the **vitals replay** control, which replays
**recorded observations only** (no interpolation of synthetic values).

The exported document is an **export of transportable prehospital monitoring
data**: it carries a research-prototype boundary statement and makes **no
diagnostic interpretation** (no rhythm diagnosis, no ECG conclusion).

## How to run

1. Start the backend: `uvicorn app.main:app --reload --port 8000`.
2. Open `http://127.0.0.1:8000/hospital-dashboard/` and log in as `admin1` / `s3curepass`.
3. (Ambulance side) in the ambulance simulator, create a patient + case,
   push vitals, and **DIGITIZE & SEND** a `clean` ECG sample so the case has a
   full dataset.
4. In the dashboard, select that case from the queue.
5. Scroll to the **HANDOVER** section at the bottom of the case detail.

## Acceptance criteria

| Item | Expected behaviour | Pass |
|---|---|---|
| Handover preview | The section shows a consolidated printable document: patient, encounter/transport (ambulance, destination, ETA, acceptance, preparation), encounter timeline, vitals, ECG thumbnails + waveforms, boundary banner, and a generated-at footer | ☐ |
| Prototype labeling | Both the preview and the exported documents carry the "research prototype — not a certified medical record — no diagnostic interpretation" boundary | ☐ |
| FHIR JSON export | **⬇ FHIR JSON** downloads `medha-<CODE>-handover-<timestamp>.json`; opens as an FHIR R4 `Bundle` of type `document` with Patient / Encounter / Composition / Observation / DiagnosticReport entries | ☐ |
| CDA XML export | **⬇ CDA XML** downloads `medha-<CODE>-handover-<timestamp>.xml`; is well-formed XML with a `ClinicalDocument` root in the `urn:hl7-org:v3` namespace | ☐ |
| PDF export | **🖨 PDF (print)** opens the print dialog; "Save as PDF" produces a clean single-page-per-section document (light background, dark text) containing the same content as the preview | ☐ |
| Vitals replay | **▶ REPLAY VITALS** steps through the recorded readings one at a time (1 per second), updating the live vital cards and a marker on the history charts; the slider has exactly one stop per recorded reading; **STOP** restores the latest reading | ☐ |
| Replay = recorded only | The replay never shows values between recorded readings (no interpolation); each step matches a real row in the vitals history | ☐ |
| Live refresh | New vitals / timeline events / ECG records pushed from the ambulance while the case is open appear in the handover preview within one poll/WS cycle | ☐ |

## Checks

- [ ] Handover preview shows patient demographics and chief complaint
- [ ] Preview shows ambulance vehicle number, destination hospital, ETA (when transporting), and acceptance / preparation state
- [ ] Encounter timeline entries appear with labels and timestamps
- [ ] Latest vitals row and reading count appear; non-null values only
- [ ] Each digitized ECG shows a photo thumbnail and a drawn waveform trace with lead / leads / speed metadata
- [ ] FHIR JSON exports only after selecting a case (no export button is active with no case)
- [ ] Downloaded FHIR JSON and CDA XML filenames follow `medha-<CODE>-handover-<timestamp>.*`
- [ ] The print preview ("Print" from the dialog) hides the dashboard UI and shows only the handover document
- [ ] The handover document explicitly says it is **not** a certified medical record and makes no diagnosis
- [ ] `node --check` passes on `handover.js` and `app.js`
- [ ] `pytest tests/test_js_handover.py -q` passes (contract tests for `handover.js`)

## Backend contract

The exports come from `GET /api/v1/cases/{case_id}/handover?format=fhir|cda`
(Feature 5). Access is restricted to the owning paramedic or any hospital staff
member; the `format` query is validated (`fhir` | `cda`, else 400).

## Clinical boundary

The handover documents transport monitoring data and digitized ECG traces for
the receiving hospital. They do **not** diagnose, classify rhythms, or
interpret the trace. All use is decision-support; the research-prototype
boundary is printed on every human-readable document and embedded in every
machine-readable export.
