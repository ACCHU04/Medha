"use strict";

const INTERVAL_MS = 2000;
const GPS_INTERVAL_MS = 5000;
const MAX_ATTEMPTS = 5;
const RETRY_MS = 5000;
const AVG_SPEED_KMH = 30;

const BASELINES = {
  normal: { hr: 118, spo2: 91, sys: 90, dia: 60, temp: 37.2, rr: 26 },
  critical: { hr: 142, spo2: 84, sys: 78, dia: 45, temp: 37.2, rr: 30 },
};

const WALK = {
  hr: { step: 2, lo: 80, hi: 200 },
  spo2: { step: 1, lo: 70, hi: 100 },
  sys: { step: 2, lo: 60, hi: 180 },
  dia: { step: 2, lo: 40, hi: 120 },
  temp: { step: 0.1, lo: 35.0, hi: 40.0 },
  rr: { step: 1, lo: 12, hi: 40 },
};

const state = {
  token: null,
  me: null,
  ambulance: null,
  patient: null,
  case: null,
  hospitals: [],
  mode: "normal",
  current: { ...BASELINES.normal },
  engineId: null,
  gpsId: null,
  running: false,
  device: null,
  clock: null,
  simOffline: false,
  network: "online",
  events: [],
  route: null,
  ws: null,
  ecg: null,
};

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

function showSync(msg) {
  const el = $("sync-status");
  el.textContent = msg;
  el.className = "hint sync-ok";
}

function clearError() {
  $("banner").hidden = true;
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

function setBadge(text) {
  const badge = $("amb-status");
  badge.textContent = text;
  badge.className = "badge";
}

function renderVitals(v) {
  $("v-hr").textContent = v.hr;
  $("v-spo2").textContent = v.spo2;
  $("v-bp").textContent = `${v.sys} / ${v.dia}`;
  $("v-temp").textContent = v.temp.toFixed(1);
  $("v-rr").textContent = v.rr;
  const box = state.mode === "critical" ? "critical" : "";
  document.querySelectorAll(".vital").forEach((el) => {
    el.classList.toggle("critical", box === "critical");
  });
}

function setEngineState(text) {
  $("engine-state").textContent = text;
}

// ---- Hybrid Logical Clock (byte-compatible mirror of app/services/sync/hlc.py) ----

class HlcTimestamp {
  constructor(ms, counter, deviceId) {
    this.ms = ms;
    this.counter = counter;
    this.deviceId = deviceId;
  }

  toString() {
    return (
      String(this.ms).padStart(20, "0") +
      ":" +
      String(this.counter).padStart(6, "0") +
      ":" +
      this.deviceId
    );
  }

  static fromString(value) {
    const parts = value.split(":");
    if (parts.length !== 3) throw new Error("malformed hlc");
    return new HlcTimestamp(Number(parts[0]), Number(parts[1]), parts[2]);
  }
}

class HlcClock {
  constructor(deviceId, wallMillis = null) {
    if (typeof deviceId !== "string" || deviceId.length !== 36) {
      throw new Error("device_id must be 36 chars");
    }
    this.deviceId = deviceId;
    this._wall = wallMillis || (() => Date.now());
    this._last = null;
  }

  now(received = null) {
    const wallMs = this._wall();
    const last = this._last;
    const lastMs = last === null ? null : last.ms;
    const recv =
      received === null || received === undefined
        ? null
        : typeof received === "string"
          ? HlcTimestamp.fromString(received)
          : received;

    let nowMs;
    let counter;
    if (recv === null) {
      if (last === null) {
        nowMs = wallMs;
        counter = 0;
      } else {
        nowMs = Math.max(wallMs, lastMs);
        counter = nowMs > lastMs ? 0 : last.counter + 1;
      }
    } else if (last === null) {
      nowMs = Math.max(wallMs, recv.ms);
      counter = nowMs > recv.ms ? 0 : recv.counter + 1;
    } else {
      nowMs = Math.max(wallMs, lastMs, recv.ms);
      if (nowMs === lastMs && nowMs === recv.ms) counter = Math.max(last.counter, recv.counter) + 1;
      else if (nowMs === lastMs) counter = last.counter + 1;
      else if (nowMs === recv.ms) counter = recv.counter + 1;
      else counter = 0;
    }

    const ts = new HlcTimestamp(nowMs, counter, this.deviceId);
    this._last = ts;
    return ts.toString();
  }
}

function hlcCmp(a, b) {
  const pa = a.split(":");
  const pb = b.split(":");
  for (let i = 0; i < 2; i++) {
    const x = Number(pa[i]);
    const y = Number(pb[i]);
    if (x < y) return -1;
    if (x > y) return 1;
  }
  if (pa[2] < pb[2]) return -1;
  if (pa[2] > pb[2]) return 1;
  return 0;
}

// ---- IndexedDB outbox ----

let _dbPromise = null;

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open("medha-sync", 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains("outbox")) {
        const store = db.createObjectStore("outbox", { keyPath: "id" });
        store.createIndex("status", "status");
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error || new Error("indexedDB open failed"));
  });
}

function ensureDb() {
  if (!_dbPromise) _dbPromise = openDb();
  return _dbPromise;
}

function allPending() {
  return ensureDb().then(
    (db) =>
      new Promise((resolve, reject) => {
        const t = db.transaction("outbox", "readonly");
        const req = t.objectStore("outbox").index("status").getAll("pending");
        req.onsuccess = () => resolve(req.result || []);
        req.onerror = () => reject(req.error);
      })
  );
}

function putRecord(db, rec) {
  return new Promise((resolve, reject) => {
    const t = db.transaction("outbox", "readwrite");
    const req = t.objectStore("outbox").put(rec);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

function deleteRecord(db, id) {
  return new Promise((resolve, reject) => {
    const t = db.transaction("outbox", "readwrite");
    const req = t.objectStore("outbox").delete(id);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

function updateStatus(id, status, error, attempts) {
  return ensureDb().then(
    (db) =>
      new Promise((resolve, reject) => {
        const t = db.transaction("outbox", "readwrite");
        const store = t.objectStore("outbox");
        const req = store.get(id);
        req.onsuccess = () => {
          const rec = req.result;
          if (!rec) { resolve(); return; }
          rec.status = status;
          if (error !== undefined) rec.error = error;
          if (attempts !== undefined) rec.attempts = attempts;
          store.put(rec);
          resolve();
        };
        req.onerror = () => reject(req.error);
      })
  );
}

function enqueueOp(op) {
  return ensureDb().then((db) =>
    putRecord(db, {
      id: op.id,
      op: op.op,
      entity: op.entity,
      ref_id: op.ref_id,
      device_id: op.device_id,
      hlc: op.hlc,
      payload: op.data,
      status: "pending",
      attempts: 0,
      created_at: new Date().toISOString(),
    })
  );
}

// ---- Device registration (stable HLC device id per browser) ----

async function ensureDevice() {
  const stored = localStorage.getItem("medha_device");
  if (stored) {
    try {
      const parsed = JSON.parse(stored);
      if (parsed && parsed.id) {
        state.device = { id: parsed.id };
        state.clock = new HlcClock(parsed.id);
        return;
      }
    } catch (_) { /* fall through and re-register */ }
  }
  const vehicle = (state.ambulance.vehicle_number || "amb").toLowerCase();
  const device = await api("POST", "/api/v1/devices", { label: "amb-sim-" + vehicle });
  state.device = { id: device.id };
  state.clock = new HlcClock(device.id);
  localStorage.setItem("medha_device", JSON.stringify({ id: device.id }));
}

// ---- Vital engine ----

function clamp(value, lo, hi) {
  return Math.min(hi, Math.max(lo, value));
}

function walkValue(key, value) {
  const rule = WALK[key];
  const next = value + (Math.floor(Math.random() * (rule.step * 2 + 1)) - rule.step);
  const clamped = clamp(next, rule.lo, rule.hi);
  return key === "temp" ? Math.round(clamped * 10) / 10 : Math.round(clamped);
}

function nextVitals() {
  const out = {};
  for (const key of ["hr", "spo2", "sys", "dia", "temp", "rr"]) {
    out[key] = walkValue(key, state.current[key]);
  }
  return out;
}

function toPayload(v) {
  return {
    heart_rate: v.hr,
    spo2: v.spo2,
    systolic_bp: v.sys,
    diastolic_bp: v.dia,
    temperature: v.temp,
    respiratory_rate: v.rr,
    source: "simulated",
  };
}

function newUuid() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

async function enqueueVital(v) {
  const op = {
    id: newUuid(),
    op: "upsert",
    entity: "vital",
    ref_id: state.case.id,
    device_id: state.device.id,
    hlc: state.clock.now(),
    data: { ...toPayload(v), case_id: state.case.id, timestamp: new Date().toISOString() },
  };
  await enqueueOp(op);
  return op;
}

function nextBackoffSeconds(attempts) {
  if (attempts <= 1) return 0;
  return Math.min(1 * Math.pow(2, attempts - 1), 60);
}

async function countPending() {
  const rows = await allPending();
  return rows.length;
}

async function flushOutbox() {
  const ops = (await allPending()).sort((a, b) => hlcCmp(a.hlc, b.hlc));
  if (ops.length === 0) return { sent: 0, skipped: 0 };

  const batch = ops.map((r) => ({
    op: r.op,
    entity: r.entity,
    id: r.id,
    device_id: r.device_id,
    hlc: r.hlc,
    data: r.payload,
  }));

  let resp;
  try {
    resp = await api("POST", "/api/v1/sync/push", { batch });
  } catch (err) {
    let failed = 0;
    for (const r of ops) {
      const attempts = r.attempts + 1;
      if (attempts > MAX_ATTEMPTS) {
        await updateStatus(r.id, "failed", "max attempts reached", attempts);
        failed++;
      } else {
        await updateStatus(r.id, "pending", "transport: " + err.message, attempts);
      }
    }
    const transportErr = new Error(err.message);
    transportErr.online = false;
    transportErr.failed = failed;
    throw transportErr;
  }

  const appliedIds = new Set((resp.applied || []).map((o) => String(o.id)));
  for (const r of ops) {
    if (appliedIds.has(String(r.id))) await deleteRecord(await ensureDb(), r.id);
  }
  for (const s of resp.skipped || []) {
    await updateStatus(String(s.id), "failed", s.reason || "skipped");
  }
  const transitions = ops.some((r) => r.entity === "transition");
  const gps = ops.some((r) => r.entity === "gps");
  return { sent: ops.length, skipped: (resp.skipped || []).length, transitions, gps };
}

// ---- Network / buffering ----

let retryTimer = null;

async function runFlush() {
  try {
    const result = await flushOutbox();
    await updateOfflineUI();
    if (result.transitions) await refreshEncounter();
    const pending = await countPending();
    const applied = result.sent - result.skipped;
    if (pending === 0) {
      if (result.sent > 0) {
        showSync("✓ " + applied + (result.skipped ? " synced, " + result.skipped + " rejected" : " vitals synced"));
      }
      setEngineState("Monitoring — online, queue empty");
    } else {
      showSync("✓ " + applied + " synced · " + pending + " still pending");
      setEngineState("Monitoring — online, " + pending + " pending");
    }
  } catch (err) {
    enterBuffering(err.message);
  }
}

function enterBuffering(reason) {
  state.network = "offline";
  updateOfflineUI().then(scheduleRetry);
  setEngineState("OFFLINE — buffering (" + reason + ")");
}

function scheduleRetry() {
  if (state.simOffline || retryTimer !== null) return;
  allPending().then((rows) => {
    if (rows.length === 0) return;
    retryTimer = setTimeout(() => {
      retryTimer = null;
      if (state.running) runFlush();
    }, RETRY_MS);
  });
}

async function recoverOnline() {
  if (state.simOffline) return;
  if (state.network !== "online") {
    state.network = "online";
    await updateOfflineUI();
  }
  await runFlush();
}

function setOffline(on) {
  state.simOffline = on;
  if (on) {
    if (retryTimer !== null) {
      clearTimeout(retryTimer);
      retryTimer = null;
    }
    state.network = "offline";
    updateOfflineUI();
    setEngineState("OFFLINE — buffering, monitoring continues");
  } else {
    state.network = "online";
    updateOfflineUI();
    runFlush();
  }
}

async function updateOfflineUI() {
  const pending = await countPending();
  const badge = $("net-badge");
  const btn = $("offline-btn");
  if (state.network === "offline") {
    badge.textContent = "🔴 OFFLINE — BUFFERING (" + pending + ")";
    badge.className = "badge offline";
    btn.textContent = "RESTORE NETWORK";
    btn.classList.add("toggled");
  } else {
    badge.textContent = "🟢 ONLINE" + (pending > 0 ? " — " + pending + " pending" : "");
    badge.className = "badge online";
    btn.textContent = "SIMULATE OFFLINE";
    btn.classList.remove("toggled");
  }
}

// ---- Auth ----

async function login(ev) {
  ev.preventDefault();
  clearError();
  try {
    const data = await api("POST", "/api/v1/auth/login", {
      username: $("username").value.trim(),
      password: $("password").value,
    });
    state.token = data.access_token;
    await loadSession();
  } catch (err) {
    showError("Login failed: " + err.message);
  }
}

async function loadSession() {
  state.me = await api("GET", "/api/v1/auth/me");
  state.ambulance = await api("GET", "/api/v1/ambulances/mine");
  await ensureDevice();
  $("login-view").hidden = true;
  $("app-view").hidden = false;
  $("para-name").textContent = state.me.username;
  $("amb-vehicle").textContent = state.ambulance.vehicle_number;
  setBadge(state.ambulance.status.toUpperCase());
  await loadHospitals();
  updateOfflineUI();
}

async function loadHospitals() {
  try {
    state.hospitals = await api("GET", "/api/v1/hospitals");
  } catch (_) {
    state.hospitals = [];
  }
  const select = $("dest-select");
  select.innerHTML = '<option value="__auto__">Auto (nearest)</option>';
  for (const h of state.hospitals) {
    const opt = document.createElement("option");
    opt.value = h.id;
    opt.textContent = h.name;
    select.appendChild(opt);
  }
}

// ---- Patient / Case ----

async function createPatient(ev) {
  ev.preventDefault();
  clearError();
  try {
    state.patient = await api("POST", "/api/v1/patients", {
      name: $("patient-name").value.trim(),
      age: Number($("patient-age").value),
      sex: $("patient-sex").value || null,
    });
    $("create-case-btn").disabled = false;
    showInfo("Patient saved: " + state.patient.name);
  } catch (err) {
    showError("Patient creation failed: " + err.message);
  }
}

async function createCase(ev) {
  ev.preventDefault();
  clearError();
  try {
    state.case = await api("POST", "/api/v1/cases", {
      patient_id: state.patient.id,
      ambulance_id: state.ambulance.id,
      chief_complaint: $("complaint").value.trim(),
      severity: $("severity").value,
    });
    $("case-id").textContent = state.case.id;
    $("dest-select").disabled = false;
    $("start-btn").disabled = false;
    updateEcgSend();
    resetEncounterUI();
    connectEventsWs();
    showInfo("Emergency case created");
  } catch (err) {
    showError("Case creation failed: " + err.message);
  }
}

// ---- Monitoring engine ----

async function tick() {
  if (!state.running) return;
  state.current = nextVitals();
  renderVitals(state.current);
  if (!state.simOffline) {
    try {
      await api("POST", `/api/v1/cases/${state.case.id}/vitals`, toPayload(state.current));
      await recoverOnline();
      return;
    } catch (err) {
      if (err instanceof TypeError) {
        await enqueueVital(state.current);
        await updateOfflineUI();
        return;
      }
      showError("Vital upload failed: " + err.message);
      return;
    }
  }
  try {
    await enqueueVital(state.current);
  } catch (err) {
    showError("Local queue write failed: " + err.message);
    return;
  }
  await updateOfflineUI();
}

function startMonitoring() {
  if (state.running) return;
  if (!state.case) return;
  clearError();
  state.running = true;
  state.simOffline = false;
  state.network = "online";
  $("start-btn").disabled = true;
  $("deteriorate-btn").disabled = false;
  $("stop-btn").disabled = false;
  $("offline-btn").disabled = false;
  setEngineState("Monitoring — online");
  state.current = { ...BASELINES.normal };
  state.mode = "normal";
  renderVitals(state.current);
  updateOfflineUI();
  state.engineId = setInterval(tick, INTERVAL_MS);
}

function stopMonitoring() {
  if (state.engineId !== null) {
    clearInterval(state.engineId);
    state.engineId = null;
  }
  state.running = false;
  if (retryTimer !== null) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
  $("start-btn").disabled = false;
  $("deteriorate-btn").disabled = true;
  $("stop-btn").disabled = true;
  $("offline-btn").disabled = true;
  $("offline-btn").classList.remove("toggled");
  if (state.network === "online") runFlush();
  setEngineState("Monitoring stopped");
}

async function simulateDeterioration() {
  if (!state.running) return;
  clearError();
  state.mode = "critical";
  state.current = { ...BASELINES.critical };
  renderVitals(state.current);
  setEngineState("CRITICAL — posting immediate critical reading");
  try {
    if (state.network === "online") {
      await api("POST", `/api/v1/cases/${state.case.id}/vitals`, toPayload(state.current));
    } else {
      await enqueueVital(state.current);
      await updateOfflineUI();
    }
    if (state.mode === "critical") {
      setEngineState("CRITICAL — continuing around critical baseline");
    }
  } catch (err) {
    showError("Critical vital failed: " + err.message);
  }
}

// ---- Encounter lifecycle (Feature 2) ----

const LIFECYCLE_EVENTS = {
  scene_arrival: { icon: "📍", label: "Scene arrival" },
  transport_start: { icon: "🚑", label: "Transport started" },
  hospital_arrival: { icon: "🏥", label: "Hospital arrival" },
  case_closed: { icon: "📋", label: "Case closed" },
  severity_changed: { icon: "⚠️", label: "Severity changed" },
  hospital_accept: { icon: "✅", label: "Hospital accepted" },
  hospital_decline: { icon: "⛔", label: "Hospital declined" },
  hospital_prepare: { icon: "🛏", label: "Hospital prepared" },
};

const STAGE_LABELS = {
  active: "ACTIVE",
  transporting: "EN ROUTE",
  at_hospital: "AT HOSPITAL",
  closed: "CLOSED",
};

function resetEncounterUI() {
  state.events = [];
  renderEncounterTimeline();
  updateEncounterUI();
}

function renderEncounterTimeline() {
  const ol = $("enc-timeline");
  ol.innerHTML = "";
  if (!state.events.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "No encounter events yet — start with Scene Arrival.";
    ol.appendChild(li);
    return;
  }
  for (const ev of state.events) {
    const li = document.createElement("li");
    const meta = LIFECYCLE_EVENTS[ev.event_type] || { icon: "•", label: ev.event_type.replace("_", " ") };
    if (ev.event_type === "hospital_prepare" && ev.payload && ev.payload.auto) {
      meta.label = "Auto-prepared (geofence)";
    }
    const time = new Date(ev.created_at).toLocaleTimeString();
    li.innerHTML = `<span class="t-icon">${meta.icon}</span><span>${meta.label}</span><time>${time}</time>`;
    ol.appendChild(li);
  }
}

function updateEncounterUI() {
  const stage = $("enc-stage");
  if (!state.case) {
    stage.textContent = "NO CASE";
    stage.className = "badge idle";
    setEncounterButtons({});
    return;
  }
  const status = state.case.status || "active";
  stage.textContent = STAGE_LABELS[status] || status.toUpperCase();
  stage.className = "badge status-" + status;
  const arrived = state.events.some((e) => e.event_type === "scene_arrival");
  setEncounterButtons({
    "btn-scene": status === "active" && !arrived,
    "btn-transport": status === "active",
    "btn-hospital": status === "transporting",
    "btn-close": ["active", "transporting", "at_hospital"].includes(status),
  });
  const transporting = status === "transporting";
  $("dest-select").disabled = !state.case || status !== "active";
  $("transport-info").hidden = !(status === "transporting" || status === "at_hospital");
}

function setEncounterButtons(map) {
  for (const id in map) $(id).disabled = !map[id];
}

async function enqueueTransition(eventType, extra) {
  const op = {
    id: newUuid(),
    op: "upsert",
    entity: "transition",
    ref_id: state.case.id,
    device_id: state.device.id,
    hlc: state.clock.now(),
    data: { case_id: state.case.id, event_type: eventType, ...(extra || {}) },
  };
  await enqueueOp(op);
  return op;
}

function applyLocalTransition(eventType) {
  const statusAfter = {
    scene_arrival: "active",
    transport_start: "transporting",
    hospital_arrival: "at_hospital",
    case_closed: "closed",
  };
  state.case.status = statusAfter[eventType];
  state.events.push({ event_type: eventType, created_at: new Date().toISOString() });
  updateEncounterUI();
}

function phaseFromEvents(events) {
  const types = new Set(events.map((e) => e.event_type));
  if (types.has("case_closed")) return "closed";
  if (types.has("hospital_arrival")) return "at_hospital";
  if (types.has("transport_start")) return "transporting";
  return "active";
}

// ---- Transport info (Feature 3) ----

const ACCEPT_LABELS = {
  accepted: "✅ ACCEPTED",
  declined: "⛔ DECLINED",
};

function renderTransportInfo() {
  if (!state.case) return;
  const dest = state.case.destination_hospital;
  $("t-dest").textContent = dest ? "→ " + dest.name : "→ destination pending";
  const eta = state.case.eta_minutes;
  const etaEl = $("t-eta");
  if (eta != null) {
    etaEl.textContent = "ETA " + eta + " MIN";
    etaEl.className = "badge eta";
  } else {
    etaEl.textContent = "ETA —";
    etaEl.className = "badge idle";
  }
  const acc = state.case.acceptance;
  const accEl = $("t-accept");
  if (state.case.prepared_at) {
    accEl.textContent = state.case.preparation_notes && state.case.preparation_notes.auto
      ? "🛏 READY FOR ARRIVAL (auto)"
      : "🛏 READY FOR ARRIVAL";
    accEl.className = "badge ready";
  } else if (ACCEPT_LABELS[acc]) {
    accEl.textContent = ACCEPT_LABELS[acc];
    accEl.className = "badge " + (acc === "accepted" ? "accepted" : "declined");
  } else {
    accEl.textContent = "⏳ AWAITING HOSPITAL";
    accEl.className = "badge pending";
  }
  const rec = state.case.recommended_hospital;
  const recEl = $("t-recommend");
  if (acc === "declined" && rec) {
    recEl.hidden = false;
    recEl.textContent = "Hospital declined — recommend " + rec.name;
  } else {
    recEl.hidden = true;
  }
  drawMap();
}

// ---- GPS engine + live map (Feature 3) ----

const SCENE_OFFSET_KM = { min: 3, max: 6 };

function resolveDestination(hospitalId) {
  if (hospitalId) return state.hospitals.find((h) => h.id === hospitalId) || null;
  const baseId = state.ambulance && state.ambulance.hospital_id;
  return (
    state.hospitals.find((h) => h.id === baseId) ||
    state.hospitals[0] ||
    null
  );
}

function routePayload(r) {
  return {
    coordinates: r.coords,
    distance_m: r.distanceM,
    duration_s: r.durationS,
    source: r.source,
  };
}

function applyRoute(payload) {
  const coords = (payload && payload.coordinates || []).map((c) => [
    Number(c[0]),
    Number(c[1]),
  ]);
  if (coords.length < 2) return null;
  const first = coords[0];
  const last = coords[coords.length - 1];
  state.route = {
    start: { lat: first[0], lng: first[1] },
    dest: { lat: last[0], lng: last[1] },
    coords,
    distanceM: payload.distance_m || 0,
    durationS: payload.duration_s || 60,
    durationMs: (payload.duration_s || 60) * 1000,
    source: payload.source || "osrm",
    t: 0,
    lastTick: null,
  };
  mapFitted = false;
  return state.route;
}

async function buildRoute(dest) {
  const rt = await MedhaRoute.buildRoute(dest, SCENE_OFFSET_KM);
  state.route = {
    start: rt.origin,
    dest: rt.destination,
    coords: rt.coordinates,
    distanceM: rt.distance_m,
    durationS: rt.duration_s,
    durationMs: rt.duration_s * 1000,
    source: rt.source,
    t: 0,
    lastTick: null,
  };
  mapFitted = false;
  return state.route;
}

function ensureRoute() {
  if (state.route) return true;
  const dest = state.case && state.case.destination_hospital;
  if (!dest || dest.latitude == null || dest.longitude == null) return false;
  const persisted = state.case.route_geojson;
  if (persisted && Array.isArray(persisted.coordinates) && persisted.coordinates.length >= 2) {
    if (applyRoute(persisted)) {
      drawMap();
      return true;
    }
  }
  const start = MedhaRoute.randomScenePoint(
    { latitude: dest.latitude, longitude: dest.longitude },
    SCENE_OFFSET_KM.min,
    SCENE_OFFSET_KM.max
  );
  applyRoute(
    MedhaRoute.straightRoute(start, { lat: dest.latitude, lng: dest.longitude })
  );
  drawMap();
  return true;
}

function routePosition() {
  const r = state.route;
  if (!r) return null;
  return MedhaRoute.interpolateAlong(r.coords, Math.min(1, Math.max(0, r.t)));
}

function enqueueGps(pos) {
  const op = {
    id: newUuid(),
    op: "upsert",
    entity: "gps",
    ref_id: state.case.id,
    device_id: state.device.id,
    hlc: state.clock.now(),
    data: {
      case_id: state.case.id,
      ambulance_id: state.ambulance.id,
      latitude: pos.lat,
      longitude: pos.lng,
      recorded_at: new Date().toISOString(),
    },
  };
  return enqueueOp(op);
}

async function gpsTick() {
  if (!state.case || state.case.status !== "transporting") {
    stopGps();
    return;
  }
  if (!ensureRoute()) return;
  const now = Date.now();
  if (state.route.lastTick !== null) {
    state.route.t += (now - state.route.lastTick) / state.route.durationMs;
  }
  state.route.lastTick = now;
  const pos = routePosition();
  drawMap();
  if (!state.simOffline) {
    try {
      await api("POST", `/api/v1/cases/${state.case.id}/gps`, {
        case_id: state.case.id,
        ambulance_id: state.ambulance.id,
        latitude: pos.lat,
        longitude: pos.lng,
        recorded_at: new Date().toISOString(),
      });
      await recoverOnline();
      return;
    } catch (err) {
      if (err instanceof TypeError) {
        await enqueueGps(pos);
        await updateOfflineUI();
        return;
      }
      return;
    }
  }
  try {
    await enqueueGps(pos);
  } catch (err) {
    showError("GPS queue write failed: " + err.message);
    return;
  }
  await updateOfflineUI();
}

function syncGpsEngine() {
  const status = state.case && state.case.status;
  if (status === "transporting") {
    if (state.gpsId === null) state.gpsId = setInterval(gpsTick, GPS_INTERVAL_MS);
    ensureRoute();
  } else if (state.gpsId !== null) {
    stopGps();
  }
}

function stopGps() {
  if (state.gpsId !== null) {
    clearInterval(state.gpsId);
    state.gpsId = null;
  }
}

// ---- Leaflet live map ----

let mapInstance = null;
let mapRouteLayer = null;
let mapStartMarker = null;
let mapDestMarker = null;
let mapLiveMarker = null;
let mapFitted = false;

function initMap() {
  const el = $("enc-map");
  if (!el || typeof L === "undefined" || mapInstance) return;
  mapInstance = L.map(el, { zoomControl: true, attributionControl: true });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(mapInstance);
  setTimeout(() => { if (mapInstance) mapInstance.invalidateSize(); }, 0);
}

function drawMap() {
  if (!mapInstance) initMap();
  if (!mapInstance) return;
  const r = state.route;
  const dest = state.case && state.case.destination_hospital;
  const destPos = r ? r.dest : dest ? { lat: Number(dest.latitude), lng: Number(dest.longitude) } : null;
  const destValid = destPos && isFinite(destPos.lat) && isFinite(destPos.lng);
  const startPos = r && r.start ? r.start : null;
  const startValid = startPos && isFinite(startPos.lat) && isFinite(startPos.lng);
  const livePos = r ? routePosition() : null;
  const routeCoords = r
    ? r.coords.map((c) => [c[0], c[1]]).filter((c) => isFinite(c[0]) && isFinite(c[1]))
    : [];

  if (!mapRouteLayer) {
    mapRouteLayer = L.polyline([], {
      color: "#475569",
      weight: 4,
      dashArray: "8 8",
      opacity: 0.9,
    }).addTo(mapInstance);
  }
  mapRouteLayer.setLatLngs(routeCoords);

  if (!mapStartMarker && startValid) {
    mapStartMarker = L.marker([startPos.lat, startPos.lng], { title: "Scene" })
      .addTo(mapInstance)
      .bindTooltip("Scene / pickup");
  } else if (mapStartMarker && !startValid) {
    mapInstance.removeLayer(mapStartMarker);
    mapStartMarker = null;
  }
  if (mapStartMarker && startValid) {
    mapStartMarker.setLatLng([startPos.lat, startPos.lng]);
  }

  if (!mapDestMarker && destValid) {
    mapDestMarker = L.marker([destPos.lat, destPos.lng], { title: "Hospital" })
      .addTo(mapInstance)
      .bindTooltip(dest && dest.name ? dest.name : "Hospital");
  } else if (mapDestMarker && !destValid) {
    mapInstance.removeLayer(mapDestMarker);
    mapDestMarker = null;
  }
  if (mapDestMarker && destValid) {
    mapDestMarker.setLatLng([destPos.lat, destPos.lng]);
  }

  if (!mapLiveMarker) {
    mapLiveMarker = L.circleMarker([0, 0], {
      radius: 8,
      color: "#ffffff",
      weight: 2,
      fillColor: "#0e7490",
      fillOpacity: 1,
    }).addTo(mapInstance);
  }
  if (livePos) {
    mapLiveMarker.setLatLng([livePos.lat, livePos.lng]);
    mapLiveMarker.setStyle({ fillColor: state.route.source === "straight_line" ? "#b45309" : "#0e7490" });
  }

  if (!mapFitted && startValid && destValid) {
    mapInstance.fitBounds(
      L.latLngBounds(
        [[startPos.lat, startPos.lng], [destPos.lat, destPos.lng]]
      ),
      { padding: [36, 36] }
    );
    mapFitted = true;
  } else if (!mapFitted && livePos) {
    mapInstance.setView([livePos.lat, livePos.lng], 13);
    mapFitted = true;
  }
}

// ---- Paper ECG digitization (Feature 4) ----

const ECG_MAX_DIM = 1600;

function ecgCanvasToB64(canvas) {
  return canvas.toDataURL("image/jpeg", 0.85).replace(/^data:image\/jpeg;base64,/, "");
}

function loadImageFromFile(file) {
  return new Promise((resolve, reject) => {
    if (typeof createImageBitmap === "function") {
      createImageBitmap(file).then(resolve).catch(() => loadImageViaUrl(file).then(resolve, reject));
    } else {
      loadImageViaUrl(file).then(resolve, reject);
    }
  });
}

function loadImageViaUrl(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("could not decode image")); };
    img.src = url;
  });
}

function drawToCanvas(source, maxDim) {
  const canvas = $("ecg-canvas");
  const scale = Math.min(1, maxDim / Math.max(source.width, source.height));
  canvas.width = Math.max(1, Math.round(source.width * scale));
  canvas.height = Math.max(1, Math.round(source.height * scale));
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
  canvas.hidden = false;
  return ctx.getImageData(0, 0, canvas.width, canvas.height);
}

function cropImageData(image, box) {
  const out = new ImageData(box.w, box.h);
  for (let y = 0; y < box.h; y++) {
    for (let x = 0; x < box.w; x++) {
      const si = ((box.y + y) * image.width + (box.x + x)) * 4;
      const di = (y * box.w + x) * 4;
      out.data[di] = image.data[si];
      out.data[di + 1] = image.data[si + 1];
      out.data[di + 2] = image.data[si + 2];
      out.data[di + 3] = 255;
    }
  }
  return out;
}

function normCanvasFromData(imageData) {
  const canvas = document.createElement("canvas");
  canvas.width = imageData.width;
  canvas.height = imageData.height;
  canvas.getContext("2d").putImageData(imageData, 0, 0);
  return canvas;
}

function drawTracePreview(waveform) {
  const canvas = $("ecg-trace");
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const ch = waveform && waveform.channels && waveform.channels[0];
  const pts = ch && ch.points;
  canvas.hidden = !pts || pts.length < 2;
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

function renderEcgStatus() {
  const el = $("ecg-status");
  const q = state.ecg && state.ecg.quality;
  const w = state.ecg && state.ecg.waveform;
  el.className = "hint";
  if (!q) {
    el.textContent = "Capture a paper ECG photo (JPEG/PNG) to digitize it.";
    return;
  }
  const qLabel = q.checks_passed ? "quality OK" : "quality WARN (" + q.warnings.join(", ") + ")";
  if (!w) {
    el.textContent = "No ECG grid detected — " + qLabel + ". Try a flatter, well-lit photo.";
    el.className = "hint warn";
    return;
  }
  const ch = w.channels[0];
  const grid = w.grid || {};
  if (!state.ecg.gridBox) {
    el.textContent = "No grid detected — best-effort trace, " + ch.points.length + " samples · " + qLabel;
    el.className = "hint warn";
    return;
  }
  el.textContent = "Grid " + grid.mm_per_px_x + " px/mm · " + ch.points.length + " samples · " + qLabel;
  el.className = "hint sync-ok";
}

function updateEcgSend() {
  const w = state.ecg && state.ecg.waveform;
  const pts = w && w.channels && w.channels[0] && w.channels[0].points;
  const ok = state.case && state.ecg && state.ecg.quality && pts && pts.length >= 2;
  $("ecg-send-btn").disabled = !ok;
}

function processEcgImage(image) {
  const quality = window.EcgDigitize.estimateQuality(image);
  const gridBox = window.EcgDigitize.detectGridBox(image);
  state.ecg = { original: $("ecg-canvas"), normalized: null, quality, waveform: null, gridBox };
  if (gridBox) {
    const cropped = cropImageData(image, gridBox);
    const scale = window.EcgDigitize.estimateGridScale(cropped, { x: 0, y: 0, w: gridBox.w, h: gridBox.h });
    const mmpx = scale.mm_per_px_x > 0 ? scale.mm_per_px_x : 1;
    const waveform = window.EcgDigitize.extractTrace(cropped, { mm_per_px: mmpx, sample_mm: 2, name: "I" });
    state.ecg.normalized = normCanvasFromData(cropped);
    state.ecg.waveform = waveform;
  } else {
    const waveform = window.EcgDigitize.extractTrace(image, { mm_per_px: 1, sample_mm: 2, name: "I" });
    if (waveform.channels[0].points.length >= 2) {
      state.ecg.waveform = waveform;
      state.ecg.normalized = normCanvasFromData(image);
    }
  }
  drawTracePreview(state.ecg.waveform);
  renderEcgStatus();
  updateEcgSend();
}

async function handleEcgFile(ev) {
  const file = ev.target.files && ev.target.files[0];
  ev.target.value = "";
  if (!file) return;
  clearError();
  try {
    const source = await loadImageFromFile(file);
    const image = drawToCanvas(source, ECG_MAX_DIM);
    processEcgImage(image);
  } catch (err) {
    showError("ECG capture failed: " + err.message);
  }
}

function putSampleToCanvas(variant) {
  const sample = window.EcgSamples.makeSampleImage(variant);
  const canvas = $("ecg-canvas");
  canvas.width = sample.width;
  canvas.height = sample.height;
  const ctx = canvas.getContext("2d");
  ctx.putImageData(new ImageData(sample.data, sample.width, sample.height), 0, 0);
  canvas.hidden = false;
  return ctx.getImageData(0, 0, canvas.width, canvas.height);
}

function loadSample() {
  clearError();
  try {
    processEcgImage(putSampleToCanvas($("ecg-sample-select").value));
  } catch (err) {
    showError("Sample ECG load failed: " + err.message);
  }
}

async function sendEcg() {
  if (!state.case) { showError("Create an emergency case first"); return; }
  const ecg = state.ecg || {};
  if (!ecg.waveform || !ecg.quality) { showError("Capture and digitize an ECG first"); return; }
  clearError();
  const payload = {
    case_id: state.case.id,
    captured_at: new Date().toISOString(),
    source: "paper_photo",
    lead_count: ecg.waveform.channels.length,
    paper_speed: "25",
    image_original: ecgCanvasToB64(ecg.original),
    image_normalized: ecg.normalized ? ecgCanvasToB64(ecg.normalized) : null,
    waveform: ecg.waveform,
    quality: ecg.quality,
    notes: null,
  };
  const status = $("ecg-status");
  if (!state.simOffline) {
    try {
      await api("POST", `/api/v1/cases/${state.case.id}/ecg`, payload);
      status.className = "hint sync-ok";
      status.textContent = "Digitized ECG sent to hospital.";
      await recoverOnline();
      return;
    } catch (err) {
      if (!(err instanceof TypeError)) {
        status.className = "hint warn";
        status.textContent = "Digitized ECG rejected by server: " + err.message;
        return;
      }
    }
  }
  const op = {
    id: newUuid(),
    op: "upsert",
    entity: "ecg",
    ref_id: state.case.id,
    device_id: state.device.id,
    hlc: state.clock.now(),
    data: payload,
  };
  try {
    await enqueueOp(op);
  } catch (err) {
    showError("ECG queue write failed: " + err.message);
    return;
  }
  status.className = "hint sync-ok";
  status.textContent = "Digitized ECG queued for sync.";
  await updateOfflineUI();
}

// ---- Live events websocket (Feature 3) ----

function connectEventsWs() {
  disconnectEventsWs();
  const proto = "bearer " + state.token;
  try {
    const ws = new WebSocket(`/ws/cases/${state.case.id}/events`, [proto]);
    state.ws = ws;
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (_) { return; }
      if (msg && msg.type === "event") refreshEncounter();
    };
    ws.onclose = () => { if (state.ws === ws) state.ws = null; };
  } catch (_) { /* live updates optional */ }
}

function disconnectEventsWs() {
  if (state.ws) {
    try { state.ws.close(); } catch (_) { /* ignore */ }
    state.ws = null;
  }
}

async function refreshAmbulance() {
  try {
    state.ambulance = await api("GET", "/api/v1/ambulances/mine");
    setBadge(state.ambulance.status.toUpperCase());
  } catch (_) { /* keep last known status */ }
}

async function refreshEncounter() {
  if (!state.case) return;
  try {
    const [c, events] = await Promise.all([
      api("GET", "/api/v1/cases/" + state.case.id),
      api("GET", "/api/v1/cases/" + state.case.id + "/events"),
    ]);
    state.case = c;
    state.events = events || [];
    renderEncounterTimeline();
    updateEncounterUI();
    renderTransportInfo();
    syncGpsEngine();
  } catch (err) {
    showError("Could not refresh encounter: " + err.message);
  }
  refreshAmbulance();
}

async function doTransition(eventType) {
  let extra = {};
  if (eventType === "transport_start") {
    const chosen = $("dest-select").value;
    if (chosen && chosen !== "__auto__") extra = { hospital_id: chosen };
    const dest = resolveDestination(chosen && chosen !== "__auto__" ? chosen : null);
    if (dest) {
      try {
        const r = await buildRoute(dest);
        if (r && isFinite(r.distanceM)) {
          extra.route = routePayload(r);
          if (state.case) state.case.route_geojson = extra.route;
        }
      } catch (err) {
        showError("Route unavailable — transport continues without a map: " + err.message);
      }
    }
  }

  // Online: send the transition straight to the server so the hospital sees
  // the new state immediately and the UI can never diverge from reality.
  if (!state.simOffline) {
    try {
      const result = await api("POST", `/api/v1/cases/${state.case.id}/transitions`, {
        event_type: eventType,
        ...(extra.hospital_id ? { hospital_id: extra.hospital_id } : {}),
        ...(extra.route ? { route: extra.route } : {}),
      });
      if (result && result.case) state.case = result.case;
      await recoverOnline();
    } catch (err) {
      if (err instanceof TypeError) {
        await enqueueTransition(eventType, extra);
        applyLocalTransition(eventType);
        drawMap();
        await updateOfflineUI();
        syncGpsEngine();
        return;
      }
      showError("Transition rejected by server: " + err.message);
      return;
    }
    await refreshEncounter();
    if (eventType === "case_closed" && state.running) stopMonitoring();
    if (eventType === "case_closed") disconnectEventsWs();
    return;
  }

  // Offline: queue locally as before.
  try {
    await enqueueTransition(eventType, extra);
  } catch (err) {
    showError("Transition queue write failed: " + err.message);
    return;
  }
  applyLocalTransition(eventType);
  drawMap();
  await updateOfflineUI();
  syncGpsEngine();
  if (eventType === "case_closed" && state.running) stopMonitoring();
  if (eventType === "case_closed") disconnectEventsWs();
}

// ---- Wire up ----

if (typeof document !== "undefined") {
  $("login-form").addEventListener("submit", login);
  $("patient-form").addEventListener("submit", createPatient);
  $("case-form").addEventListener("submit", createCase);
  $("start-btn").addEventListener("click", startMonitoring);
  $("deteriorate-btn").addEventListener("click", simulateDeterioration);
  $("stop-btn").addEventListener("click", stopMonitoring);
  $("offline-btn").addEventListener("click", () => setOffline(!state.simOffline));
  $("btn-scene").addEventListener("click", () => doTransition("scene_arrival"));
  $("btn-transport").addEventListener("click", () => doTransition("transport_start"));
  $("btn-hospital").addEventListener("click", () => doTransition("hospital_arrival"));
  $("btn-close").addEventListener("click", () => doTransition("case_closed"));
  $("ecg-file").addEventListener("change", handleEcgFile);
  $("ecg-send-btn").addEventListener("click", sendEcg);
  $("ecg-sample-btn").addEventListener("click", loadSample);
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { HlcTimestamp, HlcClock, hlcCmp, MAX_ATTEMPTS };
}

