/**
 * MEDHA LINK — AI Assistant Rules Engine  (assistant.js)
 *
 * Exposes a single object:
 *   window.assistant.process(text, context) → { reply, fill?, action? }
 *
 * "text"    – the raw spoken / typed string (English or Hindi)
 * "context" – live page data snapshot (patient, case, vitals, status, eta, acceptance)
 *
 * LLM-READY INTERFACE:
 *   To swap in an LLM endpoint later, replace only the body of
 *   assistant._ruleEngine(text, context) with an async fetch call.
 *   Every other file (voice.js, HTML) stays untouched.
 *
 * Today's implementation is a pure offline rule engine — zero API keys, zero network.
 */

"use strict";

(function () {

  /* ================================================================
     KEYWORD BANKS  (English + Hindi)
     ================================================================ */

  // Severity
  const SEV_MAP = [
    { keys: ["critical", "अति गंभीर", "बहुत गंभीर", "extremely severe"], value: "critical" },
    { keys: ["high", "serious", "गंभीर", "severe", "urgent", "तीव्र"], value: "high" },
    { keys: ["moderate", "medium", "मध्यम", "मध्यम गंभीरता"], value: "moderate" },
    { keys: ["low", "mild", "हल्का", "सामान्य", "minor"], value: "low" },
  ];

  // Chief complaints
  const COMPLAINT_MAP = [
    { keys: ["chest pain", "सीने में दर्द", "सीने का दर्द", "chest ache", "chest tightness"], value: "Chest pain" },
    { keys: ["breathlessness", "shortness of breath", "सांस की तकलीफ", "breathing difficulty", "सांस फूलना"], value: "Shortness of breath" },
    { keys: ["head injury", "सिर में चोट", "head trauma"], value: "Head injury" },
    { keys: ["abdominal pain", "पेट दर्द", "stomach pain", "पेट में दर्द"], value: "Abdominal pain" },
    { keys: ["unconscious", "बेहोश", "unresponsive", "fainting", "syncope", "होश खोना"], value: "Unconscious" },
    { keys: ["stroke", "लकवा", "paralysis", "facial droop"], value: "Stroke / Neurological" },
    { keys: ["trauma", "accident", "दुर्घटना", "injury", "चोट"], value: "Trauma" },
    { keys: ["fever", "बुखार", "high temperature"], value: "Fever" },
    { keys: ["seizure", "दौरा", "convulsion", "epilepsy"], value: "Seizure" },
    { keys: ["bleeding", "खून बह रहा है", "hemorrhage", "blood loss"], value: "Bleeding" },
    { keys: ["allergic", "एलर्जी", "anaphylaxis"], value: "Allergic reaction" },
    { keys: ["cardiac arrest", "heart attack", "दिल का दौरा", "हृदयाघात"], value: "Cardiac arrest / Heart attack" },
    { keys: ["diabetic", "diabetes", "मधुमेह", "sugar", "hypoglycemia", "शुगर"], value: "Diabetic emergency" },
    { keys: ["burn", "जलन", "जलना", "scald"], value: "Burns" },
    { keys: ["fracture", "हड्डी टूटना", "broken bone"], value: "Fracture" },
  ];

  // Sex
  const SEX_MAP = [
    { keys: ["male", "man", "boy", "पुरुष", "लड़का", "आदमी", "gents", "m"], value: "m" },
    { keys: ["female", "woman", "girl", "महिला", "लड़की", "औरत", "f", "lady"], value: "f" },
  ];

  // Action chips
  const ACTION_MAP = [
    { keys: ["create case", "create emergency", "केस बनाओ", "case बनाओ"], action: "create-case" },
    { keys: ["start monitoring", "monitoring शुरू", "start vitals", "monitor patient"], action: "start-monitoring" },
    { keys: ["digitize", "send ecg", "ecg भेजो", "digitize ecg", "digitize and send"], action: "digitize-ecg" },
    { keys: ["accept case", "accept", "स्वीकार करो", "case accept"], action: "accept-case" },
    { keys: ["prepare bed", "bed ready", "बेड तैयार करो", "prepare"], action: "prepare-bed" },
    { keys: ["refresh queue", "refresh", "reload", "ताज़ा करो", "update queue"], action: "refresh-queue" },
  ];

  // Q&A patterns
  const QA_PATTERNS = [
    {
      keys: ["patient name", "patient ka naam", "मरीज का नाम", "नाम क्या है", "who is the patient"],
      answer: (ctx) => ctx.patient ? `Patient: ${ctx.patient.name || "—"}` : "No patient on record yet.",
    },
    {
      keys: ["patient age", "age", "उम्र", "कितने साल", "how old"],
      answer: (ctx) => ctx.patient ? `Age: ${ctx.patient.age ?? "—"}` : "No patient on record yet.",
    },
    {
      keys: ["complaint", "chief complaint", "problem", "क्या हुआ", "what happened", "issue"],
      answer: (ctx) => ctx.case ? `Chief complaint: ${ctx.case.chief_complaint || "—"}` : "No case created yet.",
    },
    {
      keys: ["severity", "गंभीरता", "how serious", "कितना गंभीर"],
      answer: (ctx) => ctx.case ? `Severity: ${(ctx.case.severity || "—").toUpperCase()}` : "No case created yet.",
    },
    {
      keys: ["eta", "arrival time", "कितनी देर", "how long", "when will", "पहुंचने में"],
      answer: (ctx) => ctx.eta != null ? `ETA: ${ctx.eta} minutes` : "ETA not set yet.",
    },
    {
      keys: ["acceptance", "accepted", "hospital status", "hospital ne", "स्वीकृति"],
      answer: (ctx) => ctx.acceptance ? `Hospital: ${ctx.acceptance.toUpperCase()}` : "No hospital acceptance yet.",
    },
    {
      keys: ["status", "case status", "stage", "अभी क्या stage"],
      answer: (ctx) => ctx.status ? `Case status: ${ctx.status.toUpperCase()}` : "No active case.",
    },
    {
      keys: ["vitals", "heart rate", "hr", "spo2", "blood pressure", "bp", "vital"],
      answer: (ctx) => {
        if (!ctx.vitals) return "No vitals data yet.";
        const v = ctx.vitals;
        const parts = [];
        if (v.hr) parts.push(`HR ${v.hr}`);
        if (v.spo2) parts.push(`SpO₂ ${v.spo2}%`);
        if (v.bp) parts.push(`BP ${v.bp}`);
        if (v.temp) parts.push(`Temp ${v.temp}°C`);
        if (v.rr) parts.push(`RR ${v.rr}`);
        return parts.length ? parts.join(" · ") : "No vitals data yet.";
      },
    },
    {
      keys: ["hello", "hi", "hey", "namaste", "नमस्ते", "help", "मदद"],
      answer: (_ctx) => "Hello! I'm MEDHA AI. I can fill patient details by voice, answer questions about the active case, or trigger actions. Try saying \"chest pain high severity\" or \"what is the ETA?\"",
    },
  ];

  /* ================================================================
     UTILITY: fuzzy / substring match
     ================================================================ */

  function normalise(s) {
    return (s || "").toLowerCase().replace(/[।,.!?]/g, "").trim();
  }

  function anyKey(text, keys) {
    const t = normalise(text);
    return keys.some((k) => t.includes(normalise(k)));
  }

  /* ================================================================
     NAME EXTRACTION (English + Hindi patterns)
     "name Ramesh"  |  "नाम रमेश"  |  "my name is Anil"
     ================================================================ */

  function extractName(text) {
    const t = normalise(text);
    // Hindi: "नाम <name>"
    let m = text.match(/नाम\s+([^\d\s,।.]{2,30})/u);
    if (m) return m[1].trim();
    // English: "name <name>" or "patient name <name>"
    m = t.match(/(?:patient\s+)?name(?:\s+is)?\s+([a-z]{2,30}(?:\s[a-z]{2,20})?)/);
    if (m) return titleCase(m[1].trim());
    // "my name is <name>"
    m = t.match(/my name is\s+([a-z]{2,30}(?:\s[a-z]{2,20})?)/);
    if (m) return titleCase(m[1].trim());
    return null;
  }

  function titleCase(s) {
    return s.replace(/\b\w/g, (c) => c.toUpperCase());
  }

  /* ================================================================
     AGE EXTRACTION  ("age 45" | "उम्र 45" | "45 years old" | Hindi numerals)
     ================================================================ */

  const HINDI_NUMS = {
    "शून्य":0,"एक":1,"दो":2,"तीन":3,"चार":4,"पांच":5,"पाँच":5,"छह":6,"सात":7,"आठ":8,"नौ":9,"दस":10,
    "ग्यारह":11,"बारह":12,"तेरह":13,"चौदह":14,"पंद्रह":15,"सोलह":16,"सत्रह":17,"अठारह":18,"उन्नीस":19,
    "बीस":20,"इक्कीस":21,"बाईस":22,"तेईस":23,"चौबीस":24,"पच्चीस":25,"छब्बीस":26,"सत्ताईस":27,
    "अट्ठाईस":28,"उनतीस":29,"तीस":30,"इकतीस":31,"बत्तीस":32,"तैंतीस":33,"चौंतीस":34,"पैंतीस":35,
    "छत्तीस":36,"सैंतीस":37,"अड़तीस":38,"उनतालीस":39,"चालीस":40,"इकतालीस":41,"बयालीस":42,
    "तैंतालीस":43,"चौंतालीस":44,"पैंतालीस":45,"छियालीस":46,"सैंतालीस":47,"अड़तालीस":48,"उनचास":49,
    "पचास":50,"साठ":60,"सत्तर":70,"अस्सी":80,"नब्बे":90,"सौ":100,
  };

  function extractAge(text) {
    const t = normalise(text);
    // "age 45" / "उम्र 45"
    let m = t.match(/(?:age|उम्र|years?|साल)\s+(\d{1,3})/);
    if (m) return parseInt(m[1], 10);
    // "45 years" / "45 साल"
    m = t.match(/(\d{1,3})\s*(?:year|साल|वर्ष)/);
    if (m) return parseInt(m[1], 10);
    // Hindi word numerals
    for (const [word, num] of Object.entries(HINDI_NUMS)) {
      if (t.includes(normalise(word)) && num > 0 && num < 130) return num;
    }
    return null;
  }

  /* ================================================================
     RULE ENGINE  (sync, offline, zero keys)
     ================================================================ */

  function ruleEngine(text, context) {
    const t = normalise(text);
    const fill = {};
    let reply = "";
    let action = null;

    // ---- Q&A: check first ----
    for (const qa of QA_PATTERNS) {
      if (anyKey(text, qa.keys)) {
        reply = qa.answer(context || {});
        return { reply, fill: null, action: null };
      }
    }

    // ---- Action chips ----
    for (const a of ACTION_MAP) {
      if (anyKey(text, a.keys)) {
        action = a.action;
        const labels = {
          "create-case": "Creating emergency case…",
          "start-monitoring": "Starting vitals monitoring…",
          "digitize-ecg": "Digitizing & sending ECG…",
          "accept-case": "Accepting case…",
          "prepare-bed": "Preparing bed…",
          "refresh-queue": "Refreshing queue…",
        };
        reply = labels[action] || "Running action…";
        return { reply, fill: null, action };
      }
    }

    // ---- Field fill ----
    const name = extractName(text);
    if (name) fill["patient-name"] = name;

    const age = extractAge(text);
    if (age !== null && age >= 0 && age <= 130) fill["patient-age"] = age;

    for (const s of SEX_MAP) {
      if (anyKey(text, s.keys)) { fill["patient-sex"] = s.value; break; }
    }

    for (const c of COMPLAINT_MAP) {
      if (anyKey(text, c.keys)) { fill["complaint"] = c.value; break; }
    }

    for (const s of SEV_MAP) {
      if (anyKey(text, s.keys)) { fill["severity"] = s.value; break; }
    }

    // ---- Build reply ----
    if (Object.keys(fill).length > 0) {
      const parts = [];
      if (fill["patient-name"])  parts.push(`Name → ${fill["patient-name"]}`);
      if (fill["patient-age"] != null) parts.push(`Age → ${fill["patient-age"]}`);
      if (fill["patient-sex"])   parts.push(`Sex → ${fill["patient-sex"] === "m" ? "Male" : "Female"}`);
      if (fill["complaint"])     parts.push(`Complaint → ${fill["complaint"]}`);
      if (fill["severity"])      parts.push(`Severity → ${fill["severity"].toUpperCase()}`);
      reply = "✓ Filled: " + parts.join(", ");
    } else {
      // Generic fallback
      reply = "I didn't catch that. Try: \"name Ramesh age 45 male chest pain high severity\", or ask \"what is the ETA?\"";
    }

    return { reply, fill: Object.keys(fill).length ? fill : null, action };
  }

  /* ================================================================
     PUBLIC API
     ================================================================ */

  window.assistant = {
    /**
     * Process a user utterance and return a structured result.
     *
     * @param {string} text  - Raw spoken or typed text
     * @param {object} context - Live page data:
     *   { patient, case, vitals: {hr,spo2,bp,temp,rr}, status, eta, acceptance }
     * @returns {{ reply: string, fill: object|null, action: string|null }}
     *
     * LLM SWAP: replace ruleEngine() call below with:
     *   const result = await fetch('/api/v1/assistant', { method:'POST', body: JSON.stringify({text, context}) });
     *   return result.json();
     */
    process(text, context) {
      try {
        return ruleEngine(text, context);
      } catch (err) {
        return { reply: "Sorry, something went wrong processing your request.", fill: null, action: null };
      }
    },

    /** Convenience: extract name only */
    extractName,

    /** Convenience: extract age only */
    extractAge,
  };

})();
