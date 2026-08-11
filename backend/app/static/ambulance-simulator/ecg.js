"use strict";

/* Paper ECG digitization (Feature 4).
 *
 * Pure image-processing helpers that operate on raw pixel buffers
 * ({ width, height, data: Uint8ClampedArray }) with NO DOM dependencies, so
 * they run in the ambulance simulator and are unit-testable headlessly in
 * Node (tests/js/ecg_check.cjs). Browser-side capture/canvas/crop lives in
 * app.js; everything here is deterministic.
 *
 * v1 scope: quality check -> grid detection -> composite waveform trace.
 * It digitizes a paper ECG into a transportable record. It does NOT
 * diagnose, classify rhythms, or interpret the trace.
 */

function _rgb(i, data) {
  return { r: data[i], g: data[i + 1], b: data[i + 2] };
}

function _isGridPixel(c) {
  const mx = Math.max(c.r, c.g, c.b);
  const mn = Math.min(c.r, c.g, c.b);
  const sat = mx - mn;
  const light = (mx + mn) / 2;
  return sat > 24 && light > 60 && light < 250;
}

function _isWavePixel(c) {
  const gray = (c.r + c.g + c.b) / 3;
  const mx = Math.max(c.r, c.g, c.b);
  const mn = Math.min(c.r, c.g, c.b);
  return gray < 150 && mx - mn < 70;
}

/* ---- Quality ---- */

function estimateQuality(image) {
  const w = image.width;
  const h = image.height;
  const data = image.data;
  const n = w * h;
  if (n === 0) {
    return {
      resolution: { w, h },
      checks_passed: false,
      warnings: ["empty image"],
    };
  }

  let sum = 0;
  let sum2 = 0;
  for (let i = 0; i < n; i++) {
    const g = (data[i * 4] + data[i * 4 + 1] + data[i * 4 + 2]) / 3;
    sum += g;
    sum2 += g * g;
  }
  const brightness = sum / n;
  const variance = Math.max(0, sum2 / n - brightness * brightness);
  const contrast_score = Math.sqrt(variance);

  let gsum = 0;
  let gsum2 = 0;
  let gcount = 0;
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const i = (y * w + x) * 4;
      const gx = (data[i + 4] + data[i + 5] + data[i + 6]) / 3
        - (data[i - 4] + data[i - 3] + data[i - 2]) / 3;
      const gy = (data[i + w * 4] + data[i + w * 4 + 1] + data[i + w * 4 + 2]) / 3
        - (data[i - w * 4] + data[i - w * 4 + 1] + data[i - w * 4 + 2]) / 3;
      const mag = Math.sqrt(gx * gx + gy * gy);
      gsum += mag;
      gsum2 += mag * mag;
      gcount++;
    }
  }
  const gmean = gsum / gcount;
  const blur_score = Math.max(0, gsum2 / gcount - gmean * gmean);

  const warnings = [];
  if (Math.min(w, h) < 480) warnings.push("low resolution");
  if (brightness < 60) warnings.push("too dark");
  if (brightness > 245) warnings.push("washed out");
  if (contrast_score < 15) warnings.push("low contrast");
  if (blur_score < 300) warnings.push("blurry");

  return {
    resolution: { w, h },
    brightness: Math.round(brightness * 100) / 100,
    contrast_score: Math.round(contrast_score * 100) / 100,
    blur_score: Math.round(blur_score * 100) / 100,
    checks_passed: warnings.length === 0,
    warnings,
  };
}

/* ---- Grid detection ---- */

function detectGridBox(image) {
  const w = image.width;
  const h = image.height;
  const data = image.data;
  const n = w * h;

  const colCount = new Array(w).fill(0);
  const rowCount = new Array(h).fill(0);
  let hits = 0;
  for (let i = 0; i < n; i++) {
    if (_isGridPixel(_rgb(i * 4, data))) {
      colCount[i % w]++;
      rowCount[(i / w) | 0]++;
      hits++;
    }
  }
  if (hits < 10) return null;

  const minPer = 3;
  let x0 = w - 1;
  let y0 = h - 1;
  let x1 = 0;
  let y1 = 0;
  for (let x = 0; x < w; x++) {
    if (colCount[x] >= minPer) {
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
    }
  }
  for (let y = 0; y < h; y++) {
    if (rowCount[y] >= minPer) {
      if (y < y0) y0 = y;
      if (y > y1) y1 = y;
    }
  }
  if (x1 <= x0 || y1 <= y0) return null;
  return { x: x0, y: y0, w: x1 - x0 + 1, h: y1 - y0 + 1 };
}

/* ---- Grid scale (px per mm via line periodicity) ---- */

function estimateGridScale(image, box) {
  const w = image.width;
  const data = image.data;
  const col = [];
  for (let x = box.x; x < box.x + box.w; x++) {
    let c = 0;
    for (let y = box.y; y < box.y + box.h; y++) {
      if (_isGridPixel(_rgb((y * w + x) * 4, data))) c++;
    }
    col.push(c);
  }

  // Binarize: dense columns (grid time lines) vs sparse (amplitude lines only).
  const maxC = Math.max.apply(null, col);
  const bin = col.map((c) => (maxC > 0 && c >= maxC * 0.5 ? 1 : 0));

  const n = bin.length;
  const maxLag = Math.min(64, (n / 2) | 0);
  let best = 1;
  let bestScore = -1;
  for (let lag = 2; lag <= maxLag; lag++) {
    let score = 0;
    for (let i = 0; i + lag < n; i++) {
      if (bin[i] === bin[i + lag]) score++;
    }
    const norm = score / (n - lag);
    if (norm > bestScore) {
      bestScore = norm;
      best = lag;
    }
  }
  if (bestScore < 0.5) best = 1;
  return { mm_per_px_x: best, mm_per_px_y: best };
}

/* ---- Composite trace extraction ---- */

function extractTrace(image, options) {
  options = options || {};
  const w = image.width;
  const h = image.height;
  const data = image.data;
  const mmpx = (options.mm_per_px && options.mm_per_px > 0) ? options.mm_per_px : 1;
  const sampleMm = (options.sample_mm && options.sample_mm > 0) ? options.sample_mm : 2;
  const stepPx = Math.max(1, Math.round(sampleMm * mmpx));

  const yOf = new Array(w).fill(null);
  for (let x = 0; x < w; x++) {
    let sum = 0;
    let count = 0;
    for (let y = 0; y < h; y++) {
      if (_isWavePixel(_rgb((y * w + x) * 4, data))) {
        sum += y;
        count++;
      }
    }
    yOf[x] = count > 0 ? sum / count : null;
  }

  let last = null;
  for (let x = 0; x < w; x++) {
    if (yOf[x] === null) yOf[x] = last;
    else last = yOf[x];
  }

  const points = [];
  for (let x = 0; x < w; x += stepPx) {
    if (yOf[x] === null) continue;
    const xMm = +(x / mmpx).toFixed(2);
    const yMm = +((h - 1 - yOf[x]) / mmpx).toFixed(2);
    points.push([xMm, yMm]);
  }

  return {
    channels: [
      {
        name: options.name || "I",
        sample_mm: sampleMm,
        points,
      },
    ],
    grid: { mm_per_px_x: mmpx, mm_per_px_y: mmpx },
  };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    estimateQuality,
    detectGridBox,
    estimateGridScale,
    extractTrace,
  };
}

if (typeof window !== "undefined") {
  window.EcgDigitize = {
    estimateQuality,
    detectGridBox,
    estimateGridScale,
    extractTrace,
  };
}
