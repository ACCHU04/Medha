"use strict";
/* Pre-arrival packet for the hospital dashboard.
 *
 * Pure, DOM-free helpers that compact the dashboard's live state for a case
 * into a single pre-arrival packet (PATIENT / ACUITY / VITALS / ECG /
 * TRANSPORT / HOSPITAL). It mirrors the handover.js pattern so a Node harness
 * can contract-test it headlessly. It is a decision-support summary of
 * transportable monitoring data — it performs no diagnosis and carries the
 * same research-prototype boundary statement as the handover document.
 */

(function (global) {
  const BOUNDARY = "Decision-support only — not a diagnosis.";

  const RISK_CLASS_LABEL = { high: "High", medium: "Medium", low: "Low" };

  function escape(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function build(state) {
    const c = state && state.cases.find((x) => x.id === state.selectedId);
    if (!c) return null;
    const p = c.patient || {};
    const amb = c.ambulance || {};
    const dest = c.destination_hospital || null;
    const risk = c.latest_risk || null;
    const history = state.history || [];
    const latest = history[history.length - 1] || null;
    const ecgs = state.ecgs || [];
    const lastEcg = ecgs.length ? ecgs[ecgs.length - 1] : null;

    return {
      caseCode: String(c.id).slice(0, 4).toUpperCase(),
      caseId: c.id,
      patient: {
        name: p.name || "Unknown",
        age: p.age == null ? null : p.age,
        sex: p.sex || null,
        complaint: c.chief_complaint || null,
      },
      acuity: {
        riskClass: risk ? risk.risk_class : null,
        score: risk && typeof risk.score === "number" ? risk.score : null,
        sirsMet: risk ? !!risk.sirs_met : false,
        severity: c.severity || null,
      },
      vitals: {
        count: history.length,
        latest: latest
          ? {
              heartRate: latest.heart_rate,
              spo2: latest.spo2,
              systolicBp: latest.systolic_bp,
              diastolicBp: latest.diastolic_bp,
              respiratoryRate: latest.respiratory_rate,
              temperature: latest.temperature,
              timestamp: latest.timestamp,
            }
          : null,
      },
      ecg: {
        count: ecgs.length,
        captured: !!lastEcg,
        qualityOk: lastEcg ? !!((lastEcg.quality || {}).checks_passed) : null,
      },
      transport: {
        destination: dest ? dest.name : null,
        eta:
          c.status === "transporting" && c.eta_minutes != null
            ? c.eta_minutes
            : null,
        status: c.status || "active",
        vehicle: amb.vehicle_number || null,
        gpsLive: !!(state.lastGps && state.gpsTrack && state.gpsTrack.length),
      },
      hospital: {
        acceptance:
          c.acceptance === "accepted"
            ? "accepted"
            : c.acceptance === "declined"
              ? "declined"
              : "pending",
        prepared: !!c.prepared_at,
        preparedAuto: !!(c.preparation_notes && c.preparation_notes.auto),
      },
      boundary: BOUNDARY,
    };
  }

  function _pill(cls, text) {
    return '<span class="pk-pill ' + escape(cls) + '">' + escape(text) + "</span>";
  }

  function printHtml(p) {
    if (!p) return "";
    const patient = p.patient;
    const acuity = p.acuity;
    const vitals = p.vitals;
    const ecg = p.ecg;
    const transport = p.transport;
    const hospital = p.hospital;

    const acuityCell = acuity.score == null
      ? _pill("pk-neutral", "No NEWS2 yet")
      : _pill("pk-risk-" + (acuity.riskClass || "low"), "NEWS2 " + acuity.score) +
        (acuity.sirsMet ? _pill("pk-sirs", "SIRS ✓") : "");
    const severityCell = acuity.severity
      ? _pill("pk-sev pk-sev-" + acuity.severity, String(acuity.severity).toUpperCase())
      : "";

    const vitalCell =
      vitals.count === 0 || !vitals.latest
        ? '<span class="pk-empty">No vitals recorded</span>'
        : _pill("pk-ok", vitals.count + " reading(s)") +
          '<span class="pk-vitals">' +
          "HR " + (vitals.latest.heartRate == null ? "—" : escape(vitals.latest.heartRate)) +
          " · SpO₂ " + (vitals.latest.spo2 == null ? "—" : escape(vitals.latest.spo2)) +
          " · BP " + (vitals.latest.systolicBp == null ? "—" : escape(vitals.latest.systolicBp)) +
          "/" + (vitals.latest.diastolicBp == null ? "—" : escape(vitals.latest.diastolicBp)) +
          " · RR " + (vitals.latest.respiratoryRate == null ? "—" : escape(vitals.latest.respiratoryRate)) +
          " · T " + (vitals.latest.temperature == null ? "—" : escape(vitals.latest.temperature)) +
          "</span>";

    const ecgCell = !ecg.captured
      ? '<span class="pk-empty">Not captured</span>'
      : _pill("pk-ok", "Captured · digitized") +
        (ecg.qualityOk == null ? "" : ecg.qualityOk ? _pill("pk-ok", "Quality OK") : _pill("pk-warn", "Quality warn")) +
        '<span class="pk-muted">' + ecg.count + " tracing(s)</span>";

    const transportCell =
      (transport.vehicle ? '<span class="pk-muted">' + escape(transport.vehicle) + "</span>" : "") +
      _pill("pk-sev", String(transport.status || "active").replace("_", " ").toUpperCase()) +
      (transport.destination ? '<span class="pk-muted">→ ' + escape(transport.destination) + "</span>" : "") +
      (transport.eta != null ? _pill("pk-eta", "ETA " + transport.eta + " min") : "") +
      (transport.gpsLive ? _pill("pk-gps", "GPS LIVE") : "");

    const hospitalCell =
      hospital.acceptance === "accepted"
        ? _pill("pk-ok", "ACCEPTED")
        : hospital.acceptance === "declined"
          ? _pill("pk-warn", "DECLINED")
          : _pill("pk-neutral", "AWAITING DECISION") +
            (hospital.prepared ? _pill("pk-ok", "READY FOR ARRIVAL") : "");

    const row = (label, inner) =>
      '<div class="pk-row"><span class="pk-label">' + label + "</span><div class=\"pk-value\">" + inner + "</div></div>";

    return (
      '<div class="pk-packet">' +
      '<h3 class="pk-title">PRE-ARRIVAL PACKET <span class="pk-case">#' + escape(p.caseCode) + "</span></h3>" +
      '<p class="pk-boundary">' + escape(p.boundary) + "</p>" +
      row("PATIENT", '<span class="pk-name">' + escape(patient.name) + "</span>" +
        (patient.age != null ? '<span class="pk-muted">Age ' + escape(patient.age) + "</span>" : "") +
        (patient.sex ? '<span class="pk-muted">' + escape(String(patient.sex).toUpperCase()) + "</span>" : "") +
        (patient.complaint ? '<span class="pk-muted">' + escape(patient.complaint) + "</span>" : "")) +
      row("ACUITY", acuityCell + severityCell) +
      row("VITALS", vitalCell) +
      row("ECG", ecgCell) +
      row("TRANSPORT", transportCell) +
      row("HOSPITAL", hospitalCell) +
      "</div>"
    );
  }

  const api = { BOUNDARY, build, printHtml, escape };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined") {
    window.Packet = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
