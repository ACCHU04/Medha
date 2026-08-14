"use strict";
/* Headless contract check for the ECG color-normalization step.
 *
 * Uses the same synthetic generator as ecg-samples.js. On a degraded
 * (too-dark / low-contrast) sample, normalizeColors must whiten the paper
 * enough that grid detection and waveform extraction that FAIL on the raw
 * image SUCCEED on the normalized one. This locks the pipeline contract:
 *
 *   quality(original) -> normalizeColors -> grid -> scale -> trace
 *
 * It validates deterministically on synthetic data; real photographs remain a
 * manual acceptance step.
 */

const path = require("path");
const samples = require(path.join(process.argv[2], "ecg-samples.js"));
const ecg = require(path.join(process.argv[2], "ecg.js"));

function meanGray(image) {
  const n = image.width * image.height;
  let sum = 0;
  for (let i = 0; i < n; i++) {
    sum += (image.data[i * 4] + image.data[i * 4 + 1] + image.data[i * 4 + 2]) / 3;
  }
  return sum / n;
}

function pipeline(image) {
  const quality = ecg.estimateQuality(image);
  const box = ecg.detectGridBox(image);
  let waveform = null;
  if (box) {
    const scale = ecg.estimateGridScale(image, { x: 0, y: 0, w: box.w, h: box.h });
    waveform = ecg.extractTrace(image, {
      box,
      mm_per_px: scale.mm_per_px_x > 0 ? scale.mm_per_px_x : 1,
      sample_mm: 2,
    });
  }
  return { quality, box, waveform };
}

const variants = {};
for (const variant of samples.VARIANTS) {
  const raw = samples.makeSampleImage(variant);
  const before = pipeline(raw);
  const normalized = ecg.normalizeColors(raw);
  const after = pipeline(normalized);
  variants[variant] = {
    rawBrightness: Math.round(meanGray(raw) * 100) / 100,
    normBrightness: Math.round(meanGray(normalized) * 100) / 100,
    rawGridDetected: !!before.box,
    normGridDetected: !!after.box,
    rawPoints: before.waveform ? before.waveform.channels[0].points.length : 0,
    normPoints: after.waveform ? after.waveform.channels[0].points.length : 0,
  };
}

// Contract assertions.
const dark = variants.dark;
const lowContrast = variants["low-contrast"];
const clean = variants.clean;

let normalizeOk = true;
let detail = [];

// A dark sample should be lifted toward paper white.
if (dark.rawBrightness < 60) {
  if (dark.normBrightness < 160) {
    normalizeOk = false;
    detail.push("dark sample not whitened");
  }
} else {
  normalizeOk = false;
  detail.push("dark sample generator produced bright image");
}

// Grid detection must succeed on the normalized dark + low-contrast samples.
for (const v of [dark, lowContrast]) {
  if (!v.rawGridDetected && !v.normGridDetected) {
    normalizeOk = false;
    detail.push("normalization did not recover grid");
  }
  if (v.normPoints < 30) {
    normalizeOk = false;
    detail.push("normalization did not recover waveform");
  }
}

// A clean image must remain detectable after normalization (no regression).
if (!clean.normGridDetected || clean.normPoints < 30) {
  normalizeOk = false;
  detail.push("normalization regressed the clean sample");
}

process.stdout.write(
  JSON.stringify({ variants, normalizeOk, detail })
);
