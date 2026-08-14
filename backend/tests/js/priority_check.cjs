"use strict";
/* Headless contract check for the ambulance offline-queue priority grouping
 * (Feature 4). app.js exposes opPriority(entity, data) so the real module can
 * be tested: ECG/transition records and high-news2 vitals are HIGH priority,
 * everything else is NORMAL. The harness reports facts the Python side
 * asserts. All inputs are synthetic.
 */

const path = require("path");

const dir = process.argv[2];
global.MedhaClinical = require(path.join(dir, "..", "vendor", "medha", "clinical.js"));
const { opPriority } = require(path.join(dir, "app.js"));

const out = {
  ecg: opPriority("ecg", { case_id: "x", source: "paper_photo" }),
  transition: opPriority("transition", { event_type: "transport_start" }),
  vitalHigh: opPriority("vital", {
    heart_rate: 145,
    spo2: 80,
    systolic_bp: 90,
    diastolic_bp: 60,
    respiratory_rate: 28,
    temperature: 39.2,
  }),
  vitalNormal: opPriority("vital", {
    heart_rate: 95,
    spo2: 96,
    systolic_bp: 120,
    diastolic_bp: 80,
    respiratory_rate: 18,
    temperature: 37.0,
  }),
  gps: opPriority("gps", { latitude: 18.5, longitude: 73.8 }),
  vitalNoClinical: null,
};

// Without the clinical module the high check must still be a safe guess.
if (typeof require !== "undefined") {
  delete global.MedhaClinical;
}
out.vitalNoClinical = opPriority("vital", {
  heart_rate: 145,
  spo2: 80,
  systolic_bp: 90,
  diastolic_bp: 60,
  respiratory_rate: 28,
  temperature: 39.2,
});

process.stdout.write(JSON.stringify(out));
