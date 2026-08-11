"use strict";
/* Headless contract check for the synthetic ECG sample variants (Feature 4
 * closeout). Generates each variant, runs the real digitization pipeline
 * (quality -> grid -> scale -> trace), and reports structural facts so the
 * Python side can assert deterministic expected outcomes per variant.
 */

const path = require("path");
const fs = require("fs");

const dir = process.argv[2];
const ecg = require(path.join(dir, "ecg.js"));
const samples = require(path.join(dir, "ecg-samples.js"));

const out = {};
for (const variant of samples.VARIANTS) {
  const image = samples.makeSampleImage(variant);
  const quality = ecg.estimateQuality(image);
  const box = ecg.detectGridBox(image);
  let scale = { mm_per_px_x: 1, mm_per_px_y: 1 };
  if (box) scale = ecg.estimateGridScale(image, box);
  const trace = box
    ? ecg.extractTrace(image, { mm_per_px: scale.mm_per_px_x, sample_mm: 2 })
    : { channels: [{ points: [] }] };
  out[variant] = {
    width: image.width,
    height: image.height,
    quality,
    box,
    scale,
    pointCount: trace.channels[0].points.length,
  };
}

process.stdout.write(JSON.stringify(out));
