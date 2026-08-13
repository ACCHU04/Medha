"use strict";

const POLL_MS = 15000;
const SEVERITY_RANK = { critical: 0, high: 1, moderate: 2, low: 3 };

const THRESHOLDS = {
  heart_rate: { lo: 50, hi: 130 },
  spo2: { lo: null, hi: 90 },
  systolic_bp: { lo: 90, hi: 180 },
  diastolic_bp: { lo: 60, hi: 120 },
  respiratory_rate: { lo: 10, hi: 28 },
  temperature: { lo: 35, hi: 39 },
};

const state = {
  token: null,
  me: null,
  cases: [],
  selectedId: null,
  history: [],
  events: [],
  lastGps: null,
  gpsTrack: [],
  ecgs: [],
  ws: null,
  eventsWs: null,
  eventsReconnectTimer: null,
  reconnectTimer: null,
  reconnectDelay: 1000,
  pollTimer: null,
  replayIndex: null,
};

const replay = { timer: null, index: 0, active: false };

const $ = (id) => document.getElementById(id);

function showError(msg) {
  const banner = $("banner");
  banner.textContent = "⚠ " + msg;
  banner.className = "banner";
  banner.hidden = false;
}

function showInfo(msg) {
  const banner = $("banner");
  banner.textContent = msg;
  banner.className = "banner ok";
  banner.hidden = false;
}

function setConn(text, cls) {
  const el = $("conn-status");
  el.textContent = text;
  el.className = "badge" + (cls ? " " + cls : "");
}

async function api(method, path, body) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  const resp = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const data = await resp.json();
      if (data.detail) detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch (_) { /* ignore */ }
    throw new Error(`${resp.status} ${detail}`);
  }
  return resp.status === 204 ? null : resp.json();
}

function caseCode(caseId) {
  return "A" + String(caseId).replace(/-/g, "").slice(0, 4).toUpperCase();
}

function severityPill(sev) {
  const s = sev || "low";
  return `<span class="pill ${s}">${s.toUpperCase()}</span>`;
}

// ---- Auth ---- //

async function login(ev) {
  ev.preventDefault();
  showInfo("Signing in…");
  try {
    const data = await api("POST", "/api/v1/auth/login", {
      username: $("username").value.trim(),
      password: $("password").value,
    });
    state.token = data.access_token;
    state.me = await api("GET", "/api/v1/auth/me");
    if (state.me.role !== "doctor" && state.me.role !== "hospital_admin") {
      state.token = null;
      showError("Hospital dashboard is for staff only — '" + state.me.username + "' is a " + state.me.role + ". Use admin1 or doctor1.");
      return;
    }
    $("login-view").hidden = true;
    $("app-view").hidden = false;
    $("user-name").textContent = state.me.username;
    await loadCases();
    state.pollTimer = setInterval(loadCases, POLL_MS);
  } catch (err) {
    showError("Login failed: " + err.message);
  }
}

// ---- Queue ---- //

async function loadCases() {
  try {
    const cases = await api("GET", "/api/v1/cases");
    state.cases = cases.sort((a, b) => {
      const rank = SEVERITY_RANK[a.severity || "low"] - SEVERITY_RANK[b.severity || "low"];
      return rank !== 0 ? rank : new Date(b.created_at) - new Date(a.created_at);
    });
    renderQueue();
    const selected = state.selectedId ? state.cases.find((x) => x.id === state.selectedId) : null;
    if (selected) renderDetail(selected);
  } catch (err) {
    showError("Could not load cases: " + err.message);
  }
}

function renderQueue() {
  const body = $("queue-body");
  if (!state.cases.length) {
    body.innerHTML = `<tr><td colspan="4" class="empty">No open cases</td></tr>`;
    return;
  }
  body.innerHTML = state.cases.map((c) => {
    const patient = c.patient || {};
    const label = [patient.age, (patient.sex || "").toUpperCase()].filter(Boolean).join(" ");
    const etaCell =
      c.status === "transporting" && c.eta_minutes != null
        ? `<span class="eta-pill">ETA ${c.eta_minutes} MIN</span>`
        : `<span class="muted">${(c.status || "active").toUpperCase()}</span>`;
    const dest = c.destination_hospital ? `<div class="sub">→ ${c.destination_hospital.name}</div>` : "";
    return `<tr data-id="${c.id}" class="${c.id === state.selectedId ? "selected" : ""}">
      <td>${severityPill(c.severity)}</td>
      <td>${label || "—"}${dest}</td>
      <td>#${caseCode(c.id)}</td>
      <td>${etaCell}</td>
    </tr>`;
  }).join("");
}

$("queue-body").addEventListener("click", (ev) => {
  const row = ev.target.closest("tr[data-id]");
  if (row) selectCase(row.dataset.id);
});

$("refresh-btn").addEventListener("click", loadCases);

// ---- Case detail ---- //

async function selectCase(caseId) {
  state.selectedId = caseId;
  state.history = [];
  state.events = [];
  state.lastGps = null;
  state.gpsTrack = [];
  state.ecgs = [];
  mapFitted = false;
  stopReplay();
  state.replayIndex = null;
  renderTimeline();
  renderEcgRecords();
  renderHandover();
  updateReplayControls();
  closeWebSocket();
  closeEventsWebSocket();
  renderQueue();
  const c = state.cases.find((x) => x.id === caseId);
  renderDetail(c);
  renderVitals();
  try {
    state.history = await api("GET", `/api/v1/cases/${caseId}/vitals`);
    renderVitals();
    refreshHandover();
  } catch (err) {
    showError("Could not load vitals history: " + err.message);
  }
  api("GET", `/api/v1/cases/${caseId}/gps`)
    .then((rows) => {
      if (caseId !== state.selectedId) return;
      state.gpsTrack = rows || [];
      const cur = state.cases.find((x) => x.id === caseId);
      if (cur) drawMap(cur);
    })
    .catch(() => { /* live fixes will arrive over the WebSocket */ });
  loadTimeline(caseId);
  loadEcgRecords(caseId);
  connectWebSocket(caseId);
  connectEventsWebSocket(caseId);
}

function renderDetail(c) {
  $("detail-empty").hidden = true;
  $("detail-body").hidden = false;
  $("detail-case-id").textContent = "#" + caseCode(c.id);

  const p = c.patient || {};
  $("info-patient").innerHTML = `
    <strong>${p.name || "—"}</strong>
    <span class="muted">Age ${p.age ?? "—"} · Sex ${(p.sex || "—").toUpperCase()}</span>
    <span class="muted">Complaint: ${c.chief_complaint || "—"}</span>`;
  $("info-case").innerHTML = `
    <span class="muted">Severity</span>${severityPill(c.severity)}
    <span class="muted">Status</span>${(c.status || "—").toUpperCase()}
    <span class="muted">Created</span>${new Date(c.created_at).toLocaleString()}`;
  const a = c.ambulance || {};
  $("info-ambulance").innerHTML = `
    <strong>${a.vehicle_number || "—"}</strong>
    <span class="muted">Status: ${(a.status || "—").toUpperCase()}</span>`;
  renderTransport(c);
}

// ---- Transport / hospital acceptance (Feature 3) ---- //

function renderTransport(c) {
  const dest = c.destination_hospital;
  $("t-dest").textContent = dest ? "Destination: " + dest.name : "Destination: —";
  $("t-dest").className = dest ? "" : "muted";

  const eta = c.eta_minutes;
  const etaEl = $("t-eta");
  etaEl.textContent = c.status === "transporting" && eta != null ? "ETA " + eta + " MIN" : "ETA —";
  etaEl.className = "badge" + (eta != null ? " eta" : "");

  const accEl = $("t-accept");
  if (c.prepared_at) {
    accEl.textContent = "READY FOR ARRIVAL";
    accEl.className = "badge ready";
  } else if (c.acceptance === "accepted") {
    accEl.textContent = "ACCEPTED";
    accEl.className = "badge accepted";
  } else if (c.acceptance === "declined") {
    accEl.textContent = "DECLINED";
    accEl.className = "badge declined";
  } else {
    accEl.textContent = "AWAITING DECISION";
    accEl.className = "badge pending";
  }

  const recEl = $("t-recommend");
  if (c.acceptance === "declined" && c.recommended_hospital) {
    recEl.hidden = false;
    recEl.textContent = "This hospital declined — recommend " + c.recommended_hospital.name;
  } else {
    recEl.hidden = true;
  }

  const isStaff = state.me && (state.me.role === "doctor" || state.me.role === "hospital_admin");
  const actions = $("t-actions");
  const transportable = c.status === "transporting";
  actions.hidden = !(isStaff && transportable);
  if (isStaff && transportable) {
    $("btn-accept").disabled = c.acceptance === "accepted";
    $("btn-decline").disabled = c.acceptance === "declined";
    $("btn-prepare").disabled = c.acceptance !== "accepted" || !!c.prepared_at;
  }
  drawMap(c);
}

function drawMap(c) {
  if (!mapInstance) initMap();
  if (!mapInstance) return;
  if (!mapLayerGroup) mapLayerGroup = L.layerGroup().addTo(mapInstance);
  mapLayerGroup.clearLayers();

  const dest = c && c.destination_hospital;
  const destPos =
    dest && dest.latitude != null
      ? [Number(dest.latitude), Number(dest.longitude)]
      : null;
  const destValid = destPos && isFinite(destPos[0]) && isFinite(destPos[1]);

  const routeGeo = c && c.route_geojson;
  const planned =
    routeGeo && Array.isArray(routeGeo.coordinates) && routeGeo.coordinates.length >= 2
      ? routeGeo.coordinates
          .map((p) => [Number(p[0]), Number(p[1])])
          .filter((p) => isFinite(p[0]) && isFinite(p[1]))
      : null;

  const track = state.gpsTrack || [];
  const trackPos = track
    .map((g) => [Number(g.latitude), Number(g.longitude)])
    .filter((p) => isFinite(p[0]) && isFinite(p[1]));
  const livePos = trackPos.length ? trackPos[trackPos.length - 1] : null;
  const startPos = trackPos.length ? trackPos[0] : planned ? planned[0] : null;

  const plannedStyle = { color: "#475569", weight: 4, dashArray: "8 8", opacity: 0.9 };
  if (planned) {
    L.polyline(planned, plannedStyle).addTo(mapLayerGroup);
  } else if (livePos && destValid) {
    L.polyline([livePos, destPos], plannedStyle).addTo(mapLayerGroup);
  }
  if (trackPos.length >= 2) {
    L.polyline(trackPos, { color: "#0e7490", weight: 5, opacity: 1 }).addTo(mapLayerGroup);
  }
  if (startPos) {
    L.marker(startPos, { title: "Scene" }).addTo(mapLayerGroup).bindTooltip("Scene / pickup");
  }
  if (destValid) {
    L.marker(destPos, { title: "Hospital" })
      .addTo(mapLayerGroup)
      .bindTooltip(dest ? dest.name : "Hospital");
  }
  if (livePos) {
    L.circleMarker(livePos, {
      radius: 8,
      color: "#ffffff",
      weight: 2,
      fillColor: "#0e7490",
      fillOpacity: 1,
    }).addTo(mapLayerGroup);
  }

  const boundsPts = planned ? planned.slice() : trackPos.slice();
  if (destValid) boundsPts.push(destPos);
  if (!mapFitted && boundsPts.length) {
    mapInstance.fitBounds(L.latLngBounds(boundsPts), { padding: [30, 30], maxZoom: 16 });
    mapFitted = true;
  } else if (!mapFitted) {
    mapInstance.setView([18.52, 73.85], 12);
    mapFitted = true;
  }
}

// ---- Leaflet live map (Feature 3) ----

let mapInstance = null;
let mapLayerGroup = null;
let mapFitted = false;

function initMap() {
  const el = $("case-map");
  if (!el || typeof L === "undefined" || mapInstance) return;
  mapInstance = L.map(el, { zoomControl: true, attributionControl: true });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(mapInstance);
  setTimeout(() => { if (mapInstance) mapInstance.invalidateSize(); }, 0);
}

async function hospitalAction(action) {
  const c = state.cases.find((x) => x.id === state.selectedId);
  if (!c) return;
  const body = {};
  if (action === "accept") {
    body.hospital_id = (c.destination_hospital && c.destination_hospital.id) || (c.hospital_id || null);
    if (!body.hospital_id) { showError("No destination set yet"); return; }
  }
  if (action === "decline") {
    body.reason = "No available bed";
  }
  if (action === "prepare") {
    body.bed_type = "ICU";
  }
  try {
    const resp = await api("POST", `/api/v1/cases/${state.selectedId}/${action}`, body);
    const idx = state.cases.findIndex((x) => x.id === state.selectedId);
    if (idx >= 0) state.cases[idx] = resp.case;
    renderQueue();
    renderDetail(resp.case);
    loadTimeline(state.selectedId);
    showInfo(`Hospital ${action} recorded`);
  } catch (err) {
    showError(action + " failed: " + err.message);
  }
}

// ---- Vitals rendering ---- //

function exceedsThresholds(v) {
  const flags = [];
  if (v.heart_rate != null && (v.heart_rate < THRESHOLDS.heart_rate.lo || v.heart_rate > THRESHOLDS.heart_rate.hi)) flags.push("HR");
  if (v.spo2 != null && v.spo2 < THRESHOLDS.spo2.hi) flags.push("SpO₂");
  if (v.systolic_bp != null && (v.systolic_bp < THRESHOLDS.systolic_bp.lo || v.systolic_bp > THRESHOLDS.systolic_bp.hi)) flags.push("BP");
  if (v.diastolic_bp != null && (v.diastolic_bp < THRESHOLDS.diastolic_bp.lo || v.diastolic_bp > THRESHOLDS.diastolic_bp.hi)) flags.push("BP");
  if (v.respiratory_rate != null && (v.respiratory_rate < THRESHOLDS.respiratory_rate.lo || v.respiratory_rate > THRESHOLDS.respiratory_rate.hi)) flags.push("RR");
  if (v.temperature != null && (v.temperature < THRESHOLDS.temperature.lo || v.temperature > THRESHOLDS.temperature.hi)) flags.push("TEMP");
  return flags;
}

function setCard(id, value, unit, flags) {
  const card = $(id);
  card.querySelector("strong").textContent = value == null ? "—" : value;
  card.querySelector("small").textContent = value == null ? unit : unit;
  const em = card.querySelector("em");
  const exceeded = flags.length > 0;
  card.classList.toggle("threshold", exceeded);
  em.textContent = exceeded
    ? "VITAL THRESHOLD EXCEEDED"
    : "";
}

function renderVitals() {
  const latest = state.history[state.history.length - 1];
  if (!latest) {
    for (const id of ["card-hr", "card-spo2", "card-bp", "card-rr", "card-temp"]) setCard(id, null, "", []);
    return;
  }
  const flags = exceedsThresholds(latest);
  const flagMap = {};
  for (const f of flags) flagMap[f] = true;
  setCard("card-hr", latest.heart_rate, "BPM", flagMap.HR ? ["HR"] : []);
  setCard("card-spo2", latest.spo2, "%", flagMap["SpO₂"] ? ["SpO₂"] : []);
  const bpVal = latest.systolic_bp != null || latest.diastolic_bp != null
    ? `${latest.systolic_bp ?? "—"} / ${latest.diastolic_bp ?? "—"}` : null;
  setCard("card-bp", bpVal, "mmHg", flagMap.BP ? ["BP"] : []);
  setCard("card-rr", latest.respiratory_rate, "/min", flagMap.RR ? ["RR"] : []);
  setCard("card-temp", latest.temperature, "°C", flagMap.TEMP ? ["TEMP"] : []);
  drawCharts();
}

// ---- Canvas charts ---- //

function drawChart(canvasId, series) {
  const canvas = $(canvasId);
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || 300;
  const height = canvas.clientHeight || 130;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, height);

  const padX = 6, padTop = 12, padBottom = 18;
  const plotW = width - padX * 2;
  const plotH = height - padTop - padBottom;

  let lo = Infinity, hi = -Infinity;
  for (const s of series) {
    for (const v of s.values) {
      if (v == null) continue;
      lo = Math.min(lo, v);
      hi = Math.max(hi, v);
    }
  }
  if (!isFinite(lo)) { lo = 0; hi = 1; }
  if (lo === hi) { lo -= 1; hi += 1; }
  const range = hi - lo;
  lo -= range * 0.1;
  hi += range * 0.1;

  ctx.strokeStyle = "#e2e8f0";
  ctx.lineWidth = 1;
  ctx.font = "9px system-ui";
  ctx.fillStyle = "#64748b";
  for (let i = 0; i <= 4; i++) {
    const y = padTop + (plotH / 4) * i;
    ctx.beginPath();
    ctx.moveTo(padX, y);
    ctx.lineTo(width - padX, y);
    ctx.stroke();
    const val = hi - (range * 0.1 + (range + range * 0.2) * (i / 4));
    ctx.fillText(Math.round(val).toString(), 2, y - 2);
  }

  const n = state.history.length;
  for (const s of series) {
    ctx.strokeStyle = s.color;
    ctx.fillStyle = s.color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    let started = false;
    s.values.forEach((v, i) => {
      if (v == null) return;
      const x = n <= 1 ? padX + plotW / 2 : padX + (i / (n - 1)) * plotW;
      const y = padTop + (1 - (v - lo) / (hi - lo)) * plotH;
      if (!started) { ctx.moveTo(x, y); started = true; }
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    s.values.forEach((v, i) => {
      if (v == null) return;
      const x = n <= 1 ? padX + plotW / 2 : padX + (i / (n - 1)) * plotW;
      const y = padTop + (1 - (v - lo) / (hi - lo)) * plotH;
      ctx.beginPath();
      ctx.arc(x, y, 2, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  const first = state.history[0];
  const last = state.history[state.history.length - 1];
  if (first) {
    ctx.fillStyle = "#64748b";
    ctx.fillText(timeLabel(first.timestamp), padX, height - 5);
    if (last && last !== first) ctx.fillText(timeLabel(last.timestamp), width - padX - 30, height - 5);
  }

  if (state.replayIndex != null && state.history.length > 0) {
    const idx = Math.max(0, Math.min(state.history.length - 1, state.replayIndex));
    const x = n <= 1 ? padX + plotW / 2 : padX + (idx / (n - 1)) * plotW;
    ctx.strokeStyle = "#d97706";
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(x, padTop);
    ctx.lineTo(x, height - padBottom);
    ctx.stroke();
    ctx.setLineDash([]);
  }
}

function timeLabel(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function values(key) {
  return state.history.map((v) => v[key]);
}

function drawCharts() {
  drawChart("chart-hr", [{ color: "#16a34a", values: values("heart_rate") }]);
  drawChart("chart-spo2", [{ color: "#2563eb", values: values("spo2") }]);
  drawChart("chart-bp", [
    { color: "#dc2626", values: values("systolic_bp") },
    { color: "#ea580c", values: values("diastolic_bp") },
  ]);
  drawChart("chart-rr", [{ color: "#7c3aed", values: values("respiratory_rate") }]);
}

window.addEventListener("resize", () => { if (state.selectedId) drawCharts(); });

// ---- ECG records (Feature 4) ---- //

function drawRecordTrace(canvas, channel) {
  const ctx = canvas.getContext("2d");
  const pts = channel && channel.points;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!pts || pts.length < 2) return;
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const minX = Math.min.apply(null, xs);
  const maxX = Math.max.apply(null, xs);
  const minY = Math.min.apply(null, ys);
  const maxY = Math.max.apply(null, ys);
  const pad = 10;
  const plotW = canvas.width - pad * 2;
  const plotH = canvas.height - pad * 2;
  const sx = (x) => (maxX === minX ? pad + plotW / 2 : pad + ((x - minX) / (maxX - minX)) * plotW);
  const sy = (y) => (maxY === minY ? pad + plotH / 2 : pad + (1 - (y - minY) / (maxY - minY)) * plotH);
  ctx.strokeStyle = "#0f172a";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  pts.forEach((p, i) => {
    if (i === 0) ctx.moveTo(sx(p[0]), sy(p[1]));
    else ctx.lineTo(sx(p[0]), sy(p[1]));
  });
  ctx.stroke();
}

function renderEcgRecords() {
  const box = $("ecg-records");
  if (!state.ecgs.length) {
    box.innerHTML = `<div class="empty">No digitized ECG records</div>`;
    return;
  }
  box.innerHTML = state.ecgs.map((r) => {
    const ch = r.waveform && r.waveform.channels && r.waveform.channels[0];
    const grid = (r.waveform && r.waveform.grid) || {};
    const meta = [
      "Lead " + (ch && ch.name ? ch.name : "I"),
      grid.mm_per_px_x ? grid.mm_per_px_x + " px/mm" : null,
      "25 mm/s",
      r.captured_by ? "By " + r.captured_by : null,
      new Date(r.captured_at).toLocaleTimeString(),
    ].filter(Boolean).join(" · ");
    const warn =
      r.quality && r.quality.checks_passed === false && r.quality.warnings
        ? `<div class="hint warn">${r.quality.warnings.join(", ")}</div>`
        : "";
    return `<div class="ecg-record">
      <img class="ecg-photo" data-ecg="${r.id}" alt="ECG photo"
        src="/api/v1/cases/${state.selectedId}/ecg/${r.id}/image?kind=normalized">
      <canvas class="ecg-trace" data-trace="${r.id}" width="640" height="150"></canvas>
      <div class="ecg-meta">${meta}</div>
      ${warn}
      <div class="muted">Decision-support only, not a diagnosis</div>
    </div>`;
  }).join("");
  for (const img of box.querySelectorAll("img.ecg-photo")) {
    img.addEventListener("error", () => {
      if (img.dataset.fallback) { img.remove(); return; }
      img.dataset.fallback = "1";
      img.src = img.src.replace("kind=normalized", "kind=original");
    });
  }
  for (const r of state.ecgs) {
    const ch = r.waveform && r.waveform.channels && r.waveform.channels[0];
    const canvas = box.querySelector(`canvas[data-trace="${r.id}"]`);
    if (canvas) drawRecordTrace(canvas, ch);
  }
}

async function loadEcgRecords(caseId) {
  try {
    state.ecgs = await api("GET", `/api/v1/cases/${caseId}/ecg`);
    if (caseId === state.selectedId) {
      renderEcgRecords();
      refreshHandover();
    }
  } catch (err) {
    showError("Could not load ECG records: " + err.message);
  }
}

// ---- WebSocket ---- //

function closeWebSocket() {
  if (state.ws) {
    state.ws.onclose = null;
    state.ws.close();
    state.ws = null;
  }
  if (state.reconnectTimer) {
    clearTimeout(state.reconnectTimer);
    state.reconnectTimer = null;
  }
  state.reconnectDelay = 1000;
  setConn("—", "");
}

function connectWebSocket(caseId) {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${window.location.host}/ws/cases/${caseId}/vitals`, [state.token]);

  ws.onopen = () => {
    state.ws = ws;
    state.reconnectDelay = 1000;
    setConn("🟢 LIVE", "");
    if (caseId === state.selectedId) {
      api("GET", `/api/v1/cases/${caseId}/vitals`)
        .then((rows) => {
          if (caseId === state.selectedId) {
            state.history = rows;
            renderVitals();
            refreshHandover();
          }
        })
        .catch(() => { /* history will arrive via WS */ });
    }
  };

  ws.onmessage = (ev) => {
    if (caseId !== state.selectedId) return;
    const vital = JSON.parse(ev.data);
    state.history.push(vital);
    if (!replay.active) renderVitals();
    refreshHandover();
  };

  ws.onclose = (ev) => {
    if (state.ws !== ws) return;
    state.ws = null;
    if (ev.code === 4401) {
      setConn("🔴 SESSION EXPIRED", "err");
      showError("Session expired — please log in again.");
      return;
    }
    if (ev.code === 4404 || ev.code === 4403) {
      setConn("🔴 CLOSED", "err");
      return;
    }
    setConn("🟡 RECONNECTING…", "warn");
    state.reconnectTimer = setTimeout(() => {
      if (caseId === state.selectedId) connectWebSocket(caseId);
    }, state.reconnectDelay);
    state.reconnectDelay = Math.min(state.reconnectDelay * 2, 10000);
  };

  ws.onerror = () => ws.close();
}

// ---- Encounter timeline + events WebSocket (Feature 2) ---- //

const EVENT_META = {
  scene_arrival: { icon: "📍", label: "Scene arrival" },
  transport_start: { icon: "🚑", label: "Transport started" },
  hospital_arrival: { icon: "🏥", label: "Hospital arrival" },
  case_closed: { icon: "📋", label: "Case closed" },
  severity_changed: { icon: "⚠️", label: "Severity changed" },
  hospital_accept: { icon: "✅", label: "Hospital accepted" },
  hospital_decline: { icon: "⛔", label: "Hospital declined" },
  hospital_prepare: { icon: "🛏", label: "Hospital prepared" },
  ecg_added: { icon: "🧾", label: "Digitized ECG added" },
};

function renderTimeline() {
  const ol = $("case-timeline");
  if (!state.events.length) {
    ol.innerHTML = `<li class="empty">No encounter events yet</li>`;
    return;
  }
  ol.innerHTML = state.events.map((ev) => {
    const meta = EVENT_META[ev.event_type] || { icon: "•", label: ev.event_type.replace("_", " ") };
    const time = new Date(ev.created_at).toLocaleTimeString();
    return `<li><span class="t-icon">${meta.icon}</span><span>${meta.label}</span><time>${time}</time></li>`;
  }).join("");
}

async function loadTimeline(caseId) {
  try {
    state.events = await api("GET", `/api/v1/cases/${caseId}/events`);
    renderTimeline();
    refreshHandover();
  } catch (err) {
    showError("Could not load encounter timeline: " + err.message);
  }
}

function closeEventsWebSocket() {
  if (state.eventsWs) {
    state.eventsWs.onclose = null;
    state.eventsWs.close();
    state.eventsWs = null;
  }
  if (state.eventsReconnectTimer) {
    clearTimeout(state.eventsReconnectTimer);
    state.eventsReconnectTimer = null;
  }
}

function connectEventsWebSocket(caseId) {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${window.location.host}/ws/cases/${caseId}/events`, [state.token]);

  ws.onopen = () => {
    state.eventsWs = ws;
  };

  ws.onmessage = (ev) => {
    if (caseId !== state.selectedId) return;
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch (_) {
      return;
    }
    if (!msg) return;
    if (msg.type === "gps") {
      state.lastGps = msg.gps;
      state.gpsTrack.push(msg.gps);
      const c = state.cases.find((x) => x.id === caseId);
      if (c) drawMap(c);
      return;
    }
    if (msg.type !== "event") return;
    state.events.push(msg.event);
    renderTimeline();
    refreshHandover();
    if (msg.event.event_type === "ecg_added") loadEcgRecords(caseId);
    const idx = state.cases.findIndex((x) => x.id === caseId);
    if (msg.case) {
      if (idx >= 0) {
        if (msg.case.status === "closed") state.cases.splice(idx, 1);
        else state.cases[idx] = msg.case;
      }
      renderQueue();
      if (caseId === state.selectedId) renderDetail(msg.case);
    }
  };

  ws.onclose = (ev) => {
    if (state.eventsWs !== ws) return;
    state.eventsWs = null;
    if (ev.code === 4401 || ev.code === 4404 || ev.code === 4403) return;
    if (caseId !== state.selectedId) return;
    state.eventsReconnectTimer = setTimeout(() => {
      if (caseId === state.selectedId) connectEventsWebSocket(caseId);
    }, 3000);
  };

  ws.onerror = () => ws.close();
}

// ---- Handover (Feature 6) ---- //

function refreshHandover() {
  renderHandover();
  updateReplayControls();
}

function renderHandover() {
  const preview = $("handover-preview");
  const printBox = $("print-handover");
  const s = window.Handover ? Handover.summary(state) : null;
  if (!s) {
    preview.innerHTML = `<div class="empty">Select a case to build its handover preview.</div>`;
    printBox.innerHTML = "";
    return;
  }
  const html = Handover.printHtml(s);
  preview.innerHTML = html;
  printBox.innerHTML = html;
  for (const box of [preview, printBox]) {
    drawPrintTraces(box);
    for (const img of box.querySelectorAll("img.pv-ecg-photo")) {
      img.addEventListener("error", () => {
        if (img.dataset.fallback) { img.remove(); return; }
        img.dataset.fallback = "1";
        img.src = img.src.replace("kind=normalized", "kind=original");
      });
    }
  }
}

function drawPrintTraces(box) {
  for (const canvas of box.querySelectorAll("canvas[data-print-trace]")) {
    const id = canvas.dataset.printTrace;
    const rec = state.ecgs.find((r) => r.id === id);
    const ch = rec && rec.waveform && rec.waveform.channels && rec.waveform.channels[0];
    drawRecordTrace(canvas, ch);
  }
}

async function downloadExport(fmt) {
  const caseId = state.selectedId;
  if (!caseId) return;
  const url = Handover.exportUrl(caseId, fmt);
  try {
    const resp = await fetch(url, {
      headers: state.token ? { Authorization: "Bearer " + state.token } : {},
    });
    if (!resp.ok) {
      let detail = resp.statusText;
      try {
        const data = await resp.json();
        if (data.detail) detail = data.detail;
      } catch (_) { /* ignore */ }
      throw new Error(`${resp.status} ${detail}`);
    }
    const blob = await resp.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = Handover.filename(caseCode(caseId), fmt);
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
    showInfo(`Exported ${fmt.toUpperCase()} handover document`);
  } catch (err) {
    showError("Export failed: " + err.message);
  }
}

function printHandover() {
  renderHandover();
  window.print();
}

// ---- Vitals replay (recorded observations only, no interpolation) ---- //

function updateReplayControls() {
  const slider = $("replay-slider");
  const label = $("replay-label");
  const btn = $("btn-replay");
  const n = state.history.length;
  if (n === 0) {
    slider.max = 0;
    slider.value = 0;
    slider.disabled = true;
    btn.disabled = true;
    label.textContent = "No recorded vitals";
    return;
  }
  slider.disabled = false;
  slider.max = n - 1;
  slider.value = replay.active ? String(replay.index) : String(n - 1);
  btn.disabled = false;
  if (!replay.active) {
    label.textContent = `${n} recorded reading(s) · playback shows recorded values only`;
  }
}

function applyReplayIndex(i) {
  const n = state.history.length;
  if (n === 0) return;
  const idx = Math.max(0, Math.min(n - 1, i));
  replay.index = idx;
  state.replayIndex = idx;
  $("replay-slider").value = String(idx);
  $("replay-label").textContent =
    `Reading ${idx + 1} of ${n} · ${timeLabel(state.history[idx].timestamp)}`;
  const latest = state.history[idx];
  const flags = exceedsThresholds(latest);
  const flagMap = {};
  for (const f of flags) flagMap[f] = true;
  setCard("card-hr", latest.heart_rate, "BPM", flagMap.HR ? ["HR"] : []);
  setCard("card-spo2", latest.spo2, "%", flagMap["SpO₂"] ? ["SpO₂"] : []);
  const bpVal =
    latest.systolic_bp != null || latest.diastolic_bp != null
      ? `${latest.systolic_bp ?? "—"} / ${latest.diastolic_bp ?? "—"}`
      : null;
  setCard("card-bp", bpVal, "mmHg", flagMap.BP ? ["BP"] : []);
  setCard("card-rr", latest.respiratory_rate, "/min", flagMap.RR ? ["RR"] : []);
  setCard("card-temp", latest.temperature, "°C", flagMap.TEMP ? ["TEMP"] : []);
  drawCharts();
}

function startReplay() {
  if (state.history.length === 0) return;
  replay.active = true;
  $("btn-replay").textContent = "⏸ STOP REPLAY";
  applyReplayIndex(0);
  replay.timer = setInterval(() => {
    if (replay.index >= state.history.length - 1) {
      stopReplay();
      return;
    }
    applyReplayIndex(replay.index + 1);
  }, 1000);
}

function stopReplay() {
  if (replay.timer) {
    clearInterval(replay.timer);
    replay.timer = null;
  }
  const wasActive = replay.active;
  replay.active = false;
  replay.index = 0;
  state.replayIndex = null;
  $("btn-replay").textContent = "▶ REPLAY VITALS";
  if (wasActive) renderVitals();
  updateReplayControls();
}

// ---- Wire up ---- //

$("login-form").addEventListener("submit", login);
$("btn-accept").addEventListener("click", () => hospitalAction("accept"));
$("btn-decline").addEventListener("click", () => hospitalAction("decline"));
$("btn-prepare").addEventListener("click", () => hospitalAction("prepare"));
$("btn-export-fhir").addEventListener("click", () => downloadExport("fhir"));
$("btn-export-cda").addEventListener("click", () => downloadExport("cda"));
$("btn-print-pdf").addEventListener("click", printHandover);
$("btn-replay").addEventListener("click", () => {
  if (replay.active) stopReplay();
  else startReplay();
});
$("replay-slider").addEventListener("input", (ev) => {
  if (replay.active) stopReplay();
  applyReplayIndex(Number(ev.target.value));
});
