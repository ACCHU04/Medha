"use strict";
/* Pure route geometry helpers for the MEDHA LINK tracking map.

 * Shared by the ambulance simulator and the hospital dashboard. This module
 * stays DOM-free so a Node harness can contract-test it (same pattern as
 * handover.js / ecg.js). It knows how to
 *   - generate a random scene/pickup offset around a destination,
 *   - request an OSRM driving route with a straight-line fallback,
 *   - measure polyline length and interpolate a position along it, and
 *   - build the route payload persisted as a case's route_geojson.
 *
 * OSRM / OSM are enhancements, never a hard dependency: every helper has a
 * local fallback so the simulation keeps working fully offline.
 */

(function (global) {
  const AVG_SPEED_KMH = 30;
  const EARTH_RADIUS_KM = 6371.0;
  const OSRM_URL =
    "https://router.project-osrm.org/route/v1/driving/{coords}?overview=full&geometries=geojson";
  const OSRM_TIMEOUT_MS = 6000;

  function haversineKm(lat1, lon1, lat2, lon2) {
    const toRad = (d) => (d * Math.PI) / 180;
    const phi1 = toRad(lat1);
    const phi2 = toRad(lat2);
    const dPhi = toRad(lat2 - lat1);
    const dLambda = toRad(lon2 - lon1);
    const a =
      Math.sin(dPhi / 2) ** 2 +
      Math.cos(phi1) * Math.cos(phi2) * Math.sin(dLambda / 2) ** 2;
    return 2 * EARTH_RADIUS_KM * Math.asin(Math.sqrt(a));
  }

  function offsetFrom(center, bearing, km) {
    const lat = Number(center.latitude);
    const lng = Number(center.longitude);
    const latRad = (lat * Math.PI) / 180;
    const dLat = (km / EARTH_RADIUS_KM) * Math.cos(bearing);
    const dLng = (km / EARTH_RADIUS_KM) * Math.sin(bearing) / Math.cos(latRad);
    return {
      lat: lat + dLat * (180 / Math.PI),
      lng: lng + dLng * (180 / Math.PI),
    };
  }

  function randomScenePoint(dest, minKm, maxKm) {
    const bearing = Math.random() * 2 * Math.PI;
    const km = minKm + Math.random() * (maxKm - minKm);
    return offsetFrom(dest, bearing, km);
  }

  function pathDistanceKm(coords) {
    let total = 0;
    for (let i = 1; i < coords.length; i++) {
      total += haversineKm(
        coords[i - 1][0], coords[i - 1][1], coords[i][0], coords[i][1]
      );
    }
    return total;
  }

  function cumulativeLengths(coords) {
    const lengths = [0];
    let total = 0;
    for (let i = 1; i < coords.length; i++) {
      total += haversineKm(
        coords[i - 1][0], coords[i - 1][1], coords[i][0], coords[i][1]
      );
      lengths.push(total);
    }
    return lengths;
  }

  function interpolateAlong(coords, frac) {
    if (!coords || coords.length === 0) return null;
    if (coords.length === 1) {
      return { lat: Number(coords[0][0]), lng: Number(coords[0][1]) };
    }
    const clamped = Math.min(1, Math.max(0, frac));
    const lens = cumulativeLengths(coords);
    const total = lens[lens.length - 1];
    if (total <= 0) {
      const last = coords[coords.length - 1];
      return { lat: Number(last[0]), lng: Number(last[1]) };
    }
    const target = clamped * total;
    let i = 1;
    while (i < lens.length - 1 && lens[i] < target) i++;
    const segLen = lens[i] - lens[i - 1] || 1e-9;
    const t = Math.max(0, Math.min(1, (target - lens[i - 1]) / segLen));
    const aLat = Number(coords[i - 1][0]);
    const aLng = Number(coords[i - 1][1]);
    const bLat = Number(coords[i][0]);
    const bLng = Number(coords[i][1]);
    return {
      lat: aLat + (bLat - aLat) * t,
      lng: aLng + (bLng - aLng) * t,
    };
  }

  function straightRoute(start, dest) {
    const coordinates = [
      [Number(start.lat), Number(start.lng)],
      [Number(dest.lat), Number(dest.lng)],
    ];
    const distance_m = Math.round(pathDistanceKm(coordinates) * 1000);
    const duration_s = Math.round((distance_m / 1000 / AVG_SPEED_KMH) * 3600);
    return {
      coordinates,
      distance_m,
      duration_s,
      source: "straight_line",
    };
  }

  async function fetchOsrm(start, dest, opts) {
    const timeoutMs = (opts && opts.timeoutMs) || OSRM_TIMEOUT_MS;
    const coords = start.lng + "," + start.lat + ";" + dest.lng + "," + dest.lat;
    const url = OSRM_URL.replace("{coords}", coords);
    const ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    const timer = ctrl ? setTimeout(() => ctrl.abort(), timeoutMs) : null;
    try {
      const resp = await fetch(url, ctrl ? { signal: ctrl.signal } : undefined);
      if (!resp.ok) throw new Error("OSRM HTTP " + resp.status);
      const data = await resp.json();
      if (!data.routes || !data.routes.length) throw new Error("OSRM: no route");
      const r = data.routes[0];
      const coordinates = (r.geometry && r.geometry.coordinates || []).map(
        (c) => [Number(c[1]), Number(c[0])]
      );
      if (coordinates.length < 2) throw new Error("OSRM: empty geometry");
      return {
        coordinates,
        distance_m: Math.round(r.distance || 0),
        duration_s: Math.round(r.duration || 0),
        source: "osrm",
      };
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  async function buildRoute(dest, opts) {
    const minKm = (opts && opts.minKm) || 3;
    const maxKm = (opts && opts.maxKm) || 6;
    const destLat = Number(dest && dest.latitude);
    const destLng = Number(dest && dest.longitude);
    if (!isFinite(destLat) || !isFinite(destLng)) {
      throw new Error("destination lacks valid coordinates");
    }
    const start = randomScenePoint(dest, minKm, maxKm);
    let route;
    try {
      route = await fetchOsrm(start, dest, opts);
    } catch (err) {
      route = straightRoute(start, {
        lat: Number(dest.latitude),
        lng: Number(dest.longitude),
      });
      route._fallbackReason = String((err && err.message) || "error");
    }
    route.origin = { lat: Number(start.lat), lng: Number(start.lng) };
    route.destination = {
      lat: Number(dest.latitude),
      lng: Number(dest.longitude),
    };
    return route;
  }

  const api = {
    AVG_SPEED_KMH,
    OSRM_URL,
    haversineKm,
    offsetFrom,
    randomScenePoint,
    pathDistanceKm,
    cumulativeLengths,
    interpolateAlong,
    straightRoute,
    fetchOsrm,
    buildRoute,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined") {
    window.MedhaRoute = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
