"use strict";
/* Headless contract check for the shared route/map geometry helpers
 * (medha/route.js). route.js is DOM-free, so this harness can exercise the
 * real module: haversine distance, scene-point offsets, polyline
 * interpolation, the straight-line fallback route, and the OSRM fetch with
 * offline fallback. It reports structural facts the Python side asserts.
 * All coordinates are synthetic fixture data.
 */

const path = require("path");

const R = require(path.join(
  __dirname, "..", "..", "app", "static", "vendor", "medha", "route.js"
));

const DEST = { latitude: 18.5204, longitude: 73.8567 };
const SCENE = { lat: 18.53, lng: 73.86 };

const out = {};

// haversineKm: MEDHA (18.5204, 73.8567) -> Ruby Hall (18.5285, 73.8631) ~= 1.13km
out.haversineKm = R.haversineKm(18.5204, 73.8567, 18.5285, 73.8631);

// offsetFrom(center, bearing, km): ~4km NE of origin
const off = R.offsetFrom({ latitude: 18.5204, longitude: 73.8567 }, Math.PI / 4, 4.0);
out.offsetKm = R.haversineKm(18.5204, 73.8567, off.lat, off.lng);

// randomScenePoint(dest, minKm, maxKm) stays in bounds
const scene = R.randomScenePoint(DEST, 3, 6);
out.sceneKm = R.haversineKm(DEST.latitude, DEST.longitude, scene.lat, scene.lng);

// straightRoute(start, dest) derives distance/duration at AVG_SPEED_KMH
const sr = R.straightRoute(SCENE, { lat: DEST.latitude, lng: DEST.longitude });
out.straight = { source: sr.source, distanceM: sr.distance_m, durationS: sr.duration_s };

// polyline measurement + fraction interpolation
const coords = [[18.52, 73.85], [18.53, 73.86], [18.54, 73.87]];
const cLens = R.cumulativeLengths(coords);
const total = R.pathDistanceKm(coords);
const mid = R.interpolateAlong(coords, 0.5);
const startPt = R.interpolateAlong(coords, 0);
out.pathTotalKm = total;
out.cumTailKm = cLens[cLens.length - 1];
out.midKm = R.haversineKm(18.52, 73.85, mid.lat, mid.lng);
out.interpStart = [startPt.lat, startPt.lng];

async function main() {
  // Force OSRM offline so buildRoute must take the straight-line fallback.
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    throw new Error("offline");
  };
  try {
    const fb = await R.buildRoute(DEST, { minKm: 3, maxKm: 6 });
    out.fallback = {
      source: fb.source,
      coords: fb.coordinates.length,
      hasOrigin: typeof fb.origin === "object" && typeof fb.origin.lat === "number",
      hasDestination: fb.destination.lng === DEST.longitude,
      distanceM: fb.distance_m,
      durationS: fb.duration_s,
    };
  } finally {
    globalThis.fetch = realFetch;
  }
  process.stdout.write(JSON.stringify(out));
}

main();
