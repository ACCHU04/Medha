"use strict";
/* Headless contract check for the dashboard pre-arrival packet (Feature 3).
 * packet.js is DOM-free, so this harness exercises the real module:
 * packet construction from live dashboard state, HTML escaping, and the
 * compact printable card. It reports structural facts the Python side
 * asserts. All inputs are synthetic fixture data.
 */

const path = require("path");

const dir = process.argv[2];
const P = require(path.join(dir, "packet.js"));

const FIXTURE = {
  cases: [
    {
      id: "aaaa-bbbb-cccc-dddd",
      severity: "high",
      status: "transporting",
      chief_complaint: 'Chest <pain> & "dyspnea"',
      eta_minutes: 6,
      acceptance: "accepted",
      prepared_at: "2026-08-11T10:05:00Z",
      preparation_notes: { auto: true, notes: "OR ready" },
      latest_risk: { score: 8, risk_class: "high", sirs_met: true, scoring_version: "news2-5-v1" },
      patient: { name: "Anita <Sharma> & Co", age: 42, sex: "f" },
      ambulance: { vehicle_number: "AMB-1234" },
      destination_hospital: { name: "City General", city: "Pune" },
    },
  ],
  selectedId: "aaaa-bbbb-cccc-dddd",
  history: [
    {
      timestamp: "2026-08-11T10:01:00Z",
      heart_rate: 122,
      spo2: 89,
      systolic_bp: 95,
      diastolic_bp: 62,
      respiratory_rate: 28,
      temperature: 37.4,
    },
  ],
  events: [
    { event_type: "scene_arrival", created_at: "2026-08-11T10:00:00Z" },
    { event_type: "hospital_accept", created_at: "2026-08-11T10:05:00Z" },
  ],
  ecgs: [
    {
      id: "ecg-1",
      captured_at: "2026-08-11T10:02:00Z",
      lead_count: 1,
      waveform: { channels: [{ name: "I", points: [[0, 10], [2, 12]] }], grid: {} },
      quality: { checks_passed: true, warnings: [] },
    },
  ],
  lastGps: { lat: 18.52, lng: 73.85, ts: 1723359600000 },
  gpsTrack: [[18.51, 73.84], [18.52, 73.85]],
};

const out = {};

const p = P.build(FIXTURE);
out.packet = {
  caseCode: p.caseCode,
  patientName: p.patient.name,
  patientEscaped: null,
  complaint: p.patient.complaint,
  riskClass: p.acuity.riskClass,
  score: p.acuity.score,
  sirsMet: p.acuity.sirsMet,
  severity: p.acuity.severity,
  vitalsCount: p.vitals.count,
  latestHr: p.vitals.latest ? p.vitals.latest.heartRate : null,
  ecgCount: p.ecg.count,
  ecgCaptured: p.ecg.captured,
  ecgQualityOk: p.ecg.qualityOk,
  destination: p.transport.destination,
  eta: p.transport.eta,
  status: p.transport.status,
  vehicle: p.transport.vehicle,
  gpsLive: p.transport.gpsLive,
  acceptance: p.hospital.acceptance,
  prepared: p.hospital.prepared,
  preparedAuto: p.hospital.preparedAuto,
  boundary: p.boundary,
};

const html = P.printHtml(p);
out.printHtml = {
  hasBoundary: html.indexOf("Decision-support only") !== -1,
  hasPatient: html.indexOf("Anita") !== -1,
  hasPatientEscaped: html.indexOf("Anita &lt;Sharma&gt; &amp; Co") !== -1,
  hasComplaintEscaped: html.indexOf("Chest &lt;pain&gt;") !== -1,
  hasNoRawScript: html.indexOf("<script>") === -1,
  hasNews2: html.indexOf("NEWS2 8") !== -1,
  hasSirs: html.indexOf("SIRS ✓") !== -1,
  hasEta: html.indexOf("ETA 6 min") !== -1,
  hasGps: html.indexOf("GPS LIVE") !== -1,
  hasAccepted: html.indexOf("ACCEPTED") !== -1,
  hasSections: ["PATIENT", "ACUITY", "VITALS", "ECG", "TRANSPORT", "HOSPITAL"].every(
    (s) => html.indexOf(s) !== -1
  ),
};

const minimal = P.build({
  cases: [{ id: "zzzz", patient: { name: "B" } }],
  selectedId: "zzzz",
  history: [],
  events: [],
  ecgs: [],
  lastGps: null,
  gpsTrack: [],
});
const mhtml = P.printHtml(minimal);
out.minimal = {
  caseCode: minimal.caseCode,
  hasNoNews2: mhtml.indexOf("No NEWS2 yet") !== -1,
  hasNoVitals: mhtml.indexOf("No vitals recorded") !== -1,
  hasNoEcg: mhtml.indexOf("Not captured") !== -1,
  hasAwaiting: mhtml.indexOf("AWAITING DECISION") !== -1,
};

const empty = P.build({ cases: [], selectedId: "nope", history: [], ecgs: [] });
out.missing = { isNull: empty === null };

process.stdout.write(JSON.stringify(out));
