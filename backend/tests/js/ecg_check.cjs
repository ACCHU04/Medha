"use strict";
/* Headless contract check for the ECG digitization pipeline (Feature 4).
 *
 * Generates a synthetic paper-ECG-like image in a raw pixel buffer (grid
 * lines + a repeating PQRST waveform), runs quality -> grid -> scale -> trace,
 * and reports structural facts for Python-side assertions. This validates the
 * algorithm deterministically on synthetic data only; real-world photographs
 * are a manual acceptance step, not an automated claim.
 */

const path = require("path");

const ecg = require(path.join(process.argv[2], "ecg.js"));

const WIDTH = 800;
const HEIGHT = 600;
const MM_PX = 8; // synthetic grid: 8 px == 1 mm

function makeSyntheticImage() {
  const data = new Uint8ClampedArray(WIDTH * HEIGHT * 4);
  const set = (x, y, r, g, b) => {
    if (x < 0 || x >= WIDTH || y < 0 || y >= HEIGHT) return;
    const i = (y * WIDTH + x) * 4;
    data[i] = r;
    data[i + 1] = g;
    data[i + 2] = b;
    data[i + 3] = 255;
  };
  // white paper
  for (let i = 0; i < WIDTH * HEIGHT; i++) {
    data[i * 4] = 250;
    data[i * 4 + 1] = 250;
    data[i * 4 + 2] = 250;
    data[i * 4 + 3] = 255;
  }
  // red vertical grid lines every 8 px, 2 px wide
  for (let x = 0; x < WIDTH; x += MM_PX) {
    for (let dx = 0; dx < 2; dx++) {
      for (let y = 0; y < HEIGHT; y++) set(x + dx, y, 240, 80, 80);
    }
  }
  // blue horizontal grid lines every 8 px, 2 px wide
  for (let y = 0; y < HEIGHT; y += MM_PX) {
    for (let dy = 0; dy < 2; dy++) {
      for (let x = 0; x < WIDTH; x++) set(x, y + dy, 90, 140, 240);
    }
  }
  return data;
}

function ecgY(x) {
  const t = x % 200; // one beat every 200 px (~25 mm)
  const gauss = (mu, sigma, amp) =>
    amp * Math.exp(-((t - mu) * (t - mu)) / (2 * sigma * sigma));
  let v = gauss(25, 8, 15); // P
  v += -gauss(55, 3, 12); // Q
  v += gauss(65, 4, 60); // R
  v += -gauss(75, 3, 18); // S
  v += gauss(120, 15, 30); // T
  return 300 - v;
}

function paintWaveform(data) {
  const set = (x, y, r, g, b) => {
    const i = (y * WIDTH + x) * 4;
    data[i] = r;
    data[i + 1] = g;
    data[i + 2] = b;
    data[i + 3] = 255;
  };
  for (let x = 0; x < WIDTH; x++) {
    const y = Math.round(ecgY(x));
    for (let dx = -1; dx <= 1; dx++) {
      for (let dy = -1; dy <= 1; dy++) set(x + dx, y + dy, 35, 35, 35);
    }
  }
}

const data = makeSyntheticImage();
paintWaveform(data);
const image = { width: WIDTH, height: HEIGHT, data };

const quality = ecg.estimateQuality(image);
const box = ecg.detectGridBox(image);
let scale = { mm_per_px_x: 1, mm_per_px_y: 1 };
if (box) scale = ecg.estimateGridScale(image, box);
const trace = ecg.extractTrace(image, {
  box,
  mm_per_px: scale.mm_per_px_x,
  sample_mm: 2,
});

const points = trace.channels[0].points;
let traceOk = points.length >= 30;
let yMin = Infinity;
let yMax = -Infinity;
const waveformSamples = [];
for (const pt of points) {
  if (pt.length !== 2) traceOk = false;
  if (pt[1] < yMin) yMin = pt[1];
  if (pt[1] > yMax) yMax = pt[1];
}
// Self-check: reconstruct a few points back to pixels and compare to generator.
const stepPx = Math.max(1, Math.round(2 * scale.mm_per_px_x));
for (let i = 0; i < points.length; i += Math.max(1, Math.floor(points.length / 5))) {
  const xMm = points[i][0];
  const yMm = points[i][1];
  const xPx = Math.round(xMm * scale.mm_per_px_x);
  const yPx = HEIGHT - 1 - Math.round(yMm * scale.mm_per_px_y);
  const expected = Math.round(ecgY(xPx));
  waveformSamples.push({ xPx, yPx, expected });
  if (Math.abs(yPx - expected) > 6) traceOk = false;
}

process.stdout.write(
  JSON.stringify({
    width: WIDTH,
    height: HEIGHT,
    quality,
    box,
    scale,
    pointCount: points.length,
    yRangeMm: [yMin, yMax],
    waveformSamples,
    traceOk,
  })
);
