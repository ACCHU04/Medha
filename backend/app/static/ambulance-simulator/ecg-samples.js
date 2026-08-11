"use strict";

/* Synthetic paper-ECG sample images (Feature 4 closeout).
 *
 * Pure, DOM-free generators that paint a paper-ECG-like image into a raw
 * pixel buffer ({ width, height, data: Uint8ClampedArray }) — mirroring the
 * geometry of tests/js/ecg_check.cjs (white paper, red time-grid, blue
 * amplitude-grid, repeating PQRST waveform). Variants degrade the image in
 * controlled ways so the demo and the quality walkthrough have representative
 * inputs without needing a camera or real photo. Browser wiring lives in
 * app.js; this file is deterministic and unit-testable headlessly in Node.
 */

const BASE_WIDTH = 800;
const BASE_HEIGHT = 600;
const MM_PX = 8;
const GRID_RED = [240, 80, 80];
const GRID_BLUE = [90, 140, 240];
const WAVE_INK = [35, 35, 35];

function makeBuffer(width, height) {
  return new Uint8ClampedArray(width * height * 4);
}

function fillPaper(data, width, height, shade) {
  for (let i = 0; i < width * height; i++) {
    data[i * 4] = shade;
    data[i * 4 + 1] = shade;
    data[i * 4 + 2] = shade;
    data[i * 4 + 3] = 255;
  }
}

function paintGrid(data, width, height) {
  const set = (x, y, rgb) => {
    if (x < 0 || x >= width || y < 0 || y >= height) return;
    const i = (y * width + x) * 4;
    data[i] = rgb[0];
    data[i + 1] = rgb[1];
    data[i + 2] = rgb[2];
    data[i + 3] = 255;
  };
  for (let x = 0; x < width; x += MM_PX) {
    for (let dx = 0; dx < 2; dx++) {
      for (let y = 0; y < height; y++) set(x + dx, y, GRID_RED);
    }
  }
  for (let y = 0; y < height; y += MM_PX) {
    for (let dy = 0; dy < 2; dy++) {
      for (let x = 0; x < width; x++) set(x, y + dy, GRID_BLUE);
    }
  }
}

function waveformValue(x) {
  const t = x % 200;
  const gauss = (mu, sigma, amp) => amp * Math.exp(-((t - mu) * (t - mu)) / (2 * sigma * sigma));
  let v = gauss(25, 8, 15);
  v += -gauss(55, 3, 12);
  v += gauss(65, 4, 60);
  v += -gauss(75, 3, 18);
  v += gauss(120, 15, 30);
  return 300 - v;
}

function paintWaveform(data, width, height) {
  const set = (x, y, rgb) => {
    if (x < 0 || x >= width || y < 0 || y >= height) return;
    const i = (y * width + x) * 4;
    data[i] = rgb[0];
    data[i + 1] = rgb[1];
    data[i + 2] = rgb[2];
    data[i + 3] = 255;
  };
  for (let x = 0; x < width; x++) {
    const y = Math.round(waveformValue(x));
    for (let dx = -1; dx <= 1; dx++) {
      for (let dy = -1; dy <= 1; dy++) set(x + dx, y + dy, WAVE_INK);
    }
  }
}

function boxBlur(data, width, height) {
  const out = makeBuffer(width, height);
  const radius = 3;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      let r = 0;
      let g = 0;
      let b = 0;
      let count = 0;
      for (let dy = -radius; dy <= radius; dy++) {
        for (let dx = -radius; dx <= radius; dx++) {
          const px = x + dx;
          const py = y + dy;
          if (px < 0 || px >= width || py < 0 || py >= height) continue;
          const i = (py * width + px) * 4;
          r += data[i];
          g += data[i + 1];
          b += data[i + 2];
          count++;
        }
      }
      const i = (y * width + x) * 4;
      out[i] = r / count;
      out[i + 1] = g / count;
      out[i + 2] = b / count;
      out[i + 3] = 255;
    }
  }
  return out;
}

function scaleBrightness(data, width, height, factor) {
  const out = makeBuffer(width, height);
  for (let i = 0; i < width * height; i++) {
    out[i * 4] = Math.min(255, Math.round(data[i * 4] * factor));
    out[i * 4 + 1] = Math.min(255, Math.round(data[i * 4 + 1] * factor));
    out[i * 4 + 2] = Math.min(255, Math.round(data[i * 4 + 2] * factor));
    out[i * 4 + 3] = 255;
  }
  return out;
}

function reduceContrast(data, width, height, amount) {
  const out = makeBuffer(width, height);
  const paper = 250;
  for (let i = 0; i < width * height; i++) {
    for (let c = 0; c < 3; c++) {
      const v = data[i * 4 + c];
      out[i * 4 + c] = Math.max(0, Math.min(255, Math.round(paper - (paper - v) * (1 - amount))));
    }
    out[i * 4 + 3] = 255;
  }
  return out;
}

function makeSampleImage(variant, width, height) {
  width = width || BASE_WIDTH;
  height = height || BASE_HEIGHT;
  variant = variant || "clean";

  let data = makeBuffer(width, height);
  fillPaper(data, width, height, 250);
  if (variant !== "gridless") paintGrid(data, width, height);
  paintWaveform(data, width, height);

  if (variant === "blurry") data = boxBlur(data, width, height);
  if (variant === "dark") data = scaleBrightness(data, width, height, 0.18);
  if (variant === "low-contrast") data = reduceContrast(data, width, height, 0.85);

  return { width, height, data, variant };
}

const VARIANTS = ["clean", "blurry", "dark", "gridless", "low-contrast"];

if (typeof module !== "undefined" && module.exports) {
  module.exports = { makeSampleImage, VARIANTS, BASE_WIDTH, BASE_HEIGHT, MM_PX };
}

if (typeof window !== "undefined") {
  window.EcgSamples = { makeSampleImage, VARIANTS, BASE_WIDTH, BASE_HEIGHT, MM_PX };
}
