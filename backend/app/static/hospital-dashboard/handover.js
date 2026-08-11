"use strict";
/* Pure handover document helpers for the hospital dashboard (Feature 6).

 * This module stays DOM-free so a Node harness can contract-test it (same
 * pattern as ecg.js / ecg-samples.js in the ambulance simulator). It knows
 * how to
 *   - build export URLs + download filenames for the FHIR / CDA endpoints,
 *   - escape text for safe HTML embedding,
 *   - summarize the dashboard's live state into a plain handover object, and
 *   - render that summary as a consolidated printable handover document.
 *
 * It deliberately contains no diagnosis: it is an export of transportable
 * prehospital monitoring data and carries a research-prototype boundary
 * statement on every document.
 */

(function (global) {
  const BOUNDARY =
    "Export of prehospital monitoring data captured by MEDHA LINK during an " +
    "emergency response. Research prototype - not a certified medical record. " +
    "The digitized ECG trace and vital observations are transportable records; " +
    "no diagnostic interpretation is made.";

  const EVENT_LABELS = {
    scene_arrival: "Scene arrival",
    transport_start: "Transport started",
    hospital_arrival: "Hospital arrival",
    case_closed: "Case closed",
    severity_changed: "Severity changed",
    patient_updated: "Patient updated",
    note_added: "Note added",
    state_updated: "State updated",
    hospital_accept: "Hospital accepted",
    hospital_decline: "Hospital declined",
    hospital_prepare: "Hospital prepared",
    ecg_added: "Digitized ECG added",
  };

  const VITAL_FIELDS = [
    ["heart_rate", "Heart rate", "bpm"],
    ["spo2", "SpO2", "%"],
    ["systolic_bp", "Systolic BP", "mmHg"],
    ["diastolic_bp", "Diastolic BP", "mmHg"],
    ["respiratory_rate", "Respiratory rate", "/min"],
    ["temperature", "Temperature", "degC"],
  ];

  function pad2(n) {
    return String(n).padStart(2, "0");
  }

  function exportUrl(caseId, fmt) {
    return "/api/v1/cases/" + caseId + "/handover?format=" + encodeURIComponent(fmt);
  }

  function filename(caseCode, fmt, date) {
    const d = date || new Date();
    const stamp =
      d.getFullYear() + pad2(d.getMonth() + 1) + pad2(d.getDate()) + "-" +
      pad2(d.getHours()) + pad2(d.getMinutes()) + pad2(d.getSeconds());
    const ext = fmt === "cda" ? "xml" : "json";
    return "medha-" + caseCode + "-handover-" + stamp + "." + ext;
  }

  function escape(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function summary(state) {
    const c = state && state.cases.find((x) => x.id === state.selectedId);
    if (!c) return null;
    const p = c.patient || {};
    const amb = c.ambulance || {};
    const dest = c.destination_hospital || null;
    const history = state.history || [];
    const series = {};
    for (const field of VITAL_FIELDS) {
      series[field[0]] = history.map((v) => v[field[0]]);
    }
    const latest = history[history.length - 1] || null;
    const ecgs = (state.ecgs || []).map((r) => {
      const ch = r.waveform && r.waveform.channels && r.waveform.channels[0];
      const quality = r.quality || {};
      return {
        id: r.id,
        capturedAt: r.captured_at,
        leadCount: r.lead_count,
        paperSpeed: r.paper_speed,
        checksPassed: !!quality.checks_passed,
        warnings: quality.warnings || [],
        channel: ch && ch.name ? ch.name : null,
        pointCount: ch && ch.points ? ch.points.length : 0,
        notes: r.notes || null,
      };
    });
    return {
      generatedAt: new Date().toISOString(),
      caseCode: c.id.slice(0, 4).toUpperCase(),
      caseId: c.id,
      patient: {
        name: p.name || "Unknown",
        age: p.age == null ? null : p.age,
        sex: p.sex || null,
        complaint: c.chief_complaint || null,
      },
      severity: c.severity || null,
      status: c.status || "active",
      created: c.created_at || null,
      ambulance: amb.vehicle_number || null,
      destination: dest ? { name: dest.name, city: dest.city } : null,
      eta: c.status === "transporting" && c.eta_minutes != null ? c.eta_minutes : null,
      acceptance:
        c.acceptance === "accepted"
          ? "accepted"
          : c.acceptance === "declined"
            ? "declined"
            : "pending",
      prepared: !!c.prepared_at,
      recommendedHospital:
        c.acceptance === "declined" && c.recommended_hospital
          ? c.recommended_hospital.name
          : null,
      timeline: (state.events || []).map((ev) => ({
        ts: ev.created_at,
        label: EVENT_LABELS[ev.event_type] || ev.event_type.replace("_", " "),
      })),
      vitals: { count: history.length, latest: latest, series: series },
      ecgs: ecgs,
      boundary: BOUNDARY,
    };
  }

  function _imageUrl(caseId, ecgId, kind) {
    return "/api/v1/cases/" + caseId + "/ecg/" + ecgId + "/image?kind=" + kind;
  }

  function _vitalRow(label, value, unit) {
    return (
      "<div class=\"pv-row\"><span>" + escape(label) + "</span>" +
      "<strong>" + (value == null ? "-" : escape(value)) + "</strong>" +
      "<em>" + escape(unit) + "</em></div>"
    );
  }

  function _latestVitalsHtml(summaryObj) {
    const v = summaryObj.vitals.latest;
    if (!v) return "<p class=\"pv-empty\">No vital readings recorded.</p>";
    return VITAL_FIELDS.map((f) =>
      _vitalRow(f[1], v[f[0]], f[2])
    ).join("");
  }

  function _ecgCardHtml(summaryObj, ecg) {
    const warn =
      !ecg.checksPassed && ecg.warnings.length
        ? "<p class=\"pv-warn\">Quality warnings: " + escape(ecg.warnings.join(", ")) + "</p>"
        : "";
    const meta = [
      ecg.channel ? "Lead " + ecg.channel : null,
      ecg.leadCount != null ? ecg.leadCount + " lead(s)" : null,
      ecg.paperSpeed ? ecg.paperSpeed + " mm/s" : null,
      ecg.capturedAt ? new Date(ecg.capturedAt).toLocaleString() : null,
    ].filter(Boolean).join(" · ");
    return (
      "<div class=\"pv-ecg\">" +
      "<img class=\"pv-ecg-photo\" alt=\"ECG photo\" src=\"" +
      escape(_imageUrl(summaryObj.caseId, ecg.id, "normalized")) + "\">" +
      "<canvas class=\"pv-ecg-trace\" data-print-trace=\"" + escape(ecg.id) +
      "\" width=\"640\" height=\"120\"></canvas>" +
      "<div class=\"pv-ecg-meta\">" + escape(meta) + "</div>" +
      warn +
      "</div>"
    );
  }

  function printHtml(summaryObj) {
    if (!summaryObj) return "";
    const p = summaryObj.patient;
    const s = summaryObj;
    const header = [
      "Case #" + escape(s.caseCode),
      s.severity ? "Severity: " + escape(s.severity) : null,
      s.status ? "Status: " + escape(s.status) : null,
      s.created ? "Created: " + escape(new Date(s.created).toLocaleString()) : null,
    ].filter(Boolean).join(" &middot; ");

    const transport = [];
    if (s.ambulance) transport.push("Ambulance: " + escape(s.ambulance));
    if (s.destination) {
      transport.push("Destination: " + escape(s.destination.name) +
        (s.destination.city ? ", " + escape(s.destination.city) : ""));
    }
    if (s.eta != null) transport.push("ETA: " + s.eta + " min");
    const acceptanceMap = {
      accepted: "Accepted by destination",
      declined: "Declined",
      pending: "Awaiting decision",
    };
    transport.push("Acceptance: " + acceptanceMap[s.acceptance]);
    if (s.prepared) transport.push("Preparation: Ready for arrival");
    if (s.recommendedHospital) {
      transport.push("Recommendation: " + escape(s.recommendedHospital));
    }

    const timeline = s.timeline.length
      ? s.timeline.map(
          (ev) =>
            "<li><time>" + escape(new Date(ev.ts).toLocaleString()) + "</time>" +
            "<span>" + escape(ev.label) + "</span></li>"
        ).join("")
      : "<li class=\"pv-empty\">No encounter events recorded.</li>";

    const ecgs = s.ecgs.length
      ? s.ecgs.map((e) => _ecgCardHtml(s, e)).join("")
      : "<p class=\"pv-empty\">No digitized ECG tracings recorded.</p>";

    return (
      "<div class=\"pv-doc\">" +
      "<h1>MEDHA LINK prehospital handover</h1>" +
      "<p class=\"pv-meta\">" + header + "</p>" +
      "<p class=\"pv-boundary\">" + escape(s.boundary) + "</p>" +
      "<div class=\"pv-section\"><h2>Patient</h2>" +
      "<p>" + escape(p.name) +
      (p.age != null ? ", age " + escape(p.age) : "") +
      (p.sex ? " &middot; " + escape(String(p.sex).toUpperCase()) : "") + "</p>" +
      (p.complaint ? "<p>Chief complaint: " + escape(p.complaint) + "</p>" : "") +
      "</div>" +
      "<div class=\"pv-section\"><h2>Encounter / Transport</h2>" +
      "<p>" + escape(transport.join(" &middot; ")) + "</p></div>" +
      "<div class=\"pv-section\"><h2>Encounter timeline</h2>" +
      "<ol class=\"pv-timeline\">" + timeline + "</ol></div>" +
      "<div class=\"pv-section\"><h2>Vitals</h2>" +
      "<p class=\"pv-count\">" + s.vitals.count + " recorded reading(s).</p>" +
      "<div class=\"pv-vitals\">" + _latestVitalsHtml(s) + "</div></div>" +
      "<div class=\"pv-section\"><h2>ECG</h2>" +
      "<div class=\"pv-ecgs\">" + ecgs + "</div></div>" +
      "<p class=\"pv-footer\">Generated by MEDHA LINK Hospital Command on " +
      escape(new Date(s.generatedAt).toLocaleString()) + " &middot; " +
      escape(s.boundary) + "</p>" +
      "</div>"
    );
  }

  const api = { BOUNDARY, exportUrl, filename, escape, summary, printHtml };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined") {
    window.Handover = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
