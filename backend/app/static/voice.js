/**
 * MEDHA LINK — Voice + Assistant UI Layer  (voice.js)
 *
 * Responsibilities:
 *   1. SpeechRecognition (en-IN primary, hi-IN secondary) with interim results
 *      streamed live to #voice-transcript and #assistant-messages
 *   2. On final result → calls assistant.process(text, getContext())
 *   3. Field-fill with highlight flash on ambulance form inputs
 *   4. Action chip dispatch (finds existing button by ID and clicks it)
 *   5. TTS replies via window.speechSynthesis (respects #assistant-tts-toggle)
 *   6. Graceful degradation when SpeechRecognition not available
 *   7. Panel toggle (open/close #assistant-panel)
 *   8. Text send via #assistant-send / Enter key
 */

"use strict";

(function () {

  /* ================================================================
     CONSTANTS
     ================================================================ */

  // Languages to cycle through for recognition
  const LANGS = ["en-IN", "hi-IN"];
  let langIdx = 0;

  // Map from assistant action names to existing DOM button IDs
  const ACTION_BUTTON_MAP = {
    "create-case":       "create-case-btn",
    "start-monitoring":  "start-btn",
    "digitize-ecg":      "ecg-send-btn",
    "accept-case":       "btn-accept",
    "prepare-bed":       "btn-prepare",
    "refresh-queue":     "refresh-btn",
  };

  /* ================================================================
     DOM HELPERS
     ================================================================ */

  const $ = (id) => document.getElementById(id);

  function isAmbulance() {
    // Ambulance screen has #patient-name; hospital screen does not
    return !!$("patient-name");
  }

  /* ================================================================
     CONTEXT: read live page state into a plain object
     assistant.process() will use this for Q&A answers
     ================================================================ */

  function getContext() {
    const ctx = {};

    // Patient (ambulance has form fields; hospital has info-patient div)
    if (isAmbulance()) {
      const pName = $("patient-name");
      const pAge  = $("patient-age");
      const pSex  = $("patient-sex");
      if (pName) ctx.patient = {
        name: pName.value || null,
        age:  pAge ? Number(pAge.value) || null : null,
        sex:  pSex ? pSex.value || null : null,
      };
      // Case
      const complaint = $("complaint");
      const severity  = $("severity");
      const caseId    = $("case-id");
      if (complaint) ctx.case = {
        chief_complaint: complaint.value || null,
        severity: severity ? severity.value || null : null,
        id: caseId ? caseId.textContent.trim() : null,
      };
      // Vitals
      const hr   = $("v-hr");
      const spo2 = $("v-spo2");
      const bp   = $("v-bp");
      const temp = $("v-temp");
      const rr   = $("v-rr");
      if (hr) ctx.vitals = {
        hr:   hr.textContent.trim(),
        spo2: spo2 ? spo2.textContent.trim() : null,
        bp:   bp   ? bp.textContent.trim()   : null,
        temp: temp ? temp.textContent.trim()  : null,
        rr:   rr   ? rr.textContent.trim()    : null,
      };
      // Status / transport
      const encStage = $("enc-stage");
      if (encStage) ctx.status = encStage.textContent.trim();
      const tEta  = $("t-eta");
      const tAccept = $("t-accept");
      if (tEta)    ctx.eta = tEta.textContent.replace(/ETA|MIN/gi, "").trim() || null;
      if (tAccept) ctx.acceptance = tAccept.textContent.trim();
    } else {
      // Hospital: grab from rendered detail panel
      const infoPat  = $("info-patient");
      const infoCase = $("info-case");
      if (infoPat)  ctx.patient = { name: infoPat.textContent.trim() };
      if (infoCase) ctx.case    = { text: infoCase.textContent.trim() };
      const cardHr   = $("card-hr");
      if (cardHr) {
        const strong = cardHr.querySelector("strong");
        ctx.vitals = { hr: strong ? strong.textContent.trim() : null };
      }
      const tEta    = $("t-eta");
      const tAccept = $("t-accept");
      if (tEta)    ctx.eta = tEta.textContent.replace(/ETA|MIN/gi, "").trim() || null;
      if (tAccept) ctx.acceptance = tAccept.textContent.trim();
    }

    return ctx;
  }

  /* ================================================================
     ASSISTANT MESSAGE LIST UI
     ================================================================ */

  const msgList = $("assistant-messages");

  function clearPlaceholder() {
    if (!msgList) return;
    const ph = msgList.querySelector(".placeholder");
    if (ph) ph.remove();
  }

  function addMessage(text, role /* "user" | "bot" | "placeholder" */, extra) {
    if (!msgList) return;
    clearPlaceholder();
    const div = document.createElement("div");
    div.className = "ai-msg " + role + (extra ? " " + extra : "");
    div.textContent = text;
    msgList.appendChild(div);
    msgList.scrollTop = msgList.scrollHeight;
    return div;
  }

  function showTyping() {
    if (!msgList) return null;
    clearPlaceholder();
    const div = document.createElement("div");
    div.className = "ai-typing";
    div.innerHTML = "<span></span><span></span><span></span>";
    msgList.appendChild(div);
    msgList.scrollTop = msgList.scrollHeight;
    return div;
  }

  // Initialise with welcome message
  function initMessages() {
    if (!msgList) return;
    if (msgList.children.length === 0) {
      addMessage(
        isAmbulance()
          ? "Hello! Say the patient details or type a command. Try: \"name Ramesh age 45 male chest pain high severity\"."
          : "Hello! Ask about the active case or use the chips below. Try: \"What is the ETA?\" or \"Accept case\".",
        "placeholder"
      );
    }
  }

  /* ================================================================
     FIELD FILL + HIGHLIGHT FLASH
     ================================================================ */

  function fillFields(fillMap) {
    if (!fillMap) return;
    for (const [fieldId, value] of Object.entries(fillMap)) {
      const el = $(fieldId);
      if (!el) continue;
      el.value = value;
      // Dispatch events so existing JS listeners notice
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      // Highlight flash
      el.classList.remove("fill-flash");
      void el.offsetWidth; // reflow to restart animation
      el.classList.add("fill-flash");
      el.addEventListener("animationend", () => el.classList.remove("fill-flash"), { once: true });
    }
  }

  /* ================================================================
     ACTION CHIP DISPATCH
     ================================================================ */

  function dispatchAction(actionName) {
    if (!actionName) return;
    const btnId = ACTION_BUTTON_MAP[actionName];
    if (!btnId) return;
    const btn = $(btnId);
    if (btn && !btn.disabled) {
      btn.click();
    } else if (btn && btn.disabled) {
      addMessage("⚠ That action isn't available right now.", "bot");
    }
  }

  /* ================================================================
     TTS — speak a reply
     ================================================================ */

  function speak(text) {
    const toggle = $("assistant-tts-toggle");
    if (!toggle || !toggle.checked) return;
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const utt = new SpeechSynthesisUtterance(text);
    // Prefer an en-IN or hi-IN voice if available
    const voices = window.speechSynthesis.getVoices();
    const preferred = voices.find((v) => v.lang === "en-IN") ||
                      voices.find((v) => v.lang === "hi-IN") ||
                      voices.find((v) => v.lang.startsWith("en")) ||
                      null;
    if (preferred) utt.voice = preferred;
    utt.rate = 1.0;
    utt.pitch = 1.0;
    window.speechSynthesis.speak(utt);
  }

  /* ================================================================
     PROCESS TEXT (call rules engine → fill + reply)
     ================================================================ */

  function processText(text) {
    if (!text.trim()) return;

    // Show user message
    addMessage(text, "user");

    // Typing indicator
    const typingEl = showTyping();

    // Small delay for natural feel (rules are sync, but LLM would be async)
    setTimeout(() => {
      if (typingEl) typingEl.remove();

      let result;
      try {
        result = window.assistant.process(text, getContext());
      } catch (err) {
        result = { reply: "Error: " + err.message, fill: null, action: null };
      }

      // Fill form fields
      fillFields(result.fill);

      // Show bot reply
      const isActionResult = !!result.action;
      addMessage(result.reply, "bot", isActionResult ? "action-result" : "");

      // Dispatch action chip
      dispatchAction(result.action);

      // TTS
      speak(result.reply);
    }, 280);
  }

  /* ================================================================
     SPEECH RECOGNITION
     ================================================================ */

  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null;
  let activeTarget = null; // which mic button triggered recognition

  function isSpeechSupported() {
    return !!SpeechRec;
  }

  function createRecognition(lang) {
    const rec = new SpeechRec();
    rec.lang = lang;
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    rec.continuous = false;
    return rec;
  }

  // Show interim result in transcript chip (ambulance) + message list header
  let interimMsgEl = null;

  function onInterim(transcript) {
    // Ambulance transcript chip
    const chip = $("voice-transcript");
    if (chip) {
      chip.textContent = transcript;
      chip.style.display = "flex";
      chip.removeAttribute("hidden");
    }
    // In-chat interim
    if (!interimMsgEl) {
      interimMsgEl = showTyping();
    }
  }

  function clearInterim() {
    const chip = $("voice-transcript");
    if (chip) {
      chip.textContent = "";
      chip.style.display = "none";
      chip.setAttribute("hidden", "");
    }
    if (interimMsgEl) {
      interimMsgEl.remove();
      interimMsgEl = null;
    }
  }

  function setListeningState(listening, micBtn) {
    // Main assistant mic
    const mainMic = $("assistant-mic");
    const hint    = $("assistant-listen-hint");
    if (mainMic) mainMic.classList.toggle("listening", listening);
    if (hint) {
      if (listening) hint.removeAttribute("hidden");
      else hint.setAttribute("hidden", "");
    }
    // Inline mic button (mic-patient or mic-case)
    if (micBtn) micBtn.classList.toggle("listening", listening);
  }

  function startListening(micBtn) {
    if (!isSpeechSupported()) return;
    if (recognition) {
      recognition.abort();
      recognition = null;
    }

    // Cycle languages
    const lang = LANGS[langIdx % LANGS.length];
    langIdx++;

    recognition = createRecognition(lang);
    activeTarget = micBtn || $("assistant-mic");

    setListeningState(true, micBtn);
    addMessage(`🎙 Listening (${lang})…`, "bot");

    recognition.onresult = (ev) => {
      let interim = "";
      let final   = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const t = ev.results[i][0].transcript;
        if (ev.results[i].isFinal) final += t;
        else interim += t;
      }
      if (interim) onInterim(interim);
      if (final) {
        clearInterim();
        processText(final.trim());
      }
    };

    recognition.onerror = (ev) => {
      clearInterim();
      setListeningState(false, activeTarget);
      if (ev.error !== "no-speech" && ev.error !== "aborted") {
        addMessage(`⚠ Mic error: ${ev.error}`, "bot");
      }
      recognition = null;
      activeTarget = null;
    };

    recognition.onend = () => {
      clearInterim();
      setListeningState(false, activeTarget);
      recognition = null;
      activeTarget = null;
    };

    try {
      recognition.start();
    } catch (e) {
      setListeningState(false, micBtn);
      addMessage("⚠ Could not start microphone: " + e.message, "bot");
    }
  }

  function stopListening() {
    if (recognition) {
      recognition.stop();
    }
  }

  /* ================================================================
     WIRE MIC BUTTONS
     ================================================================ */

  function wireMicButton(id) {
    const btn = $(id);
    if (!btn) return;
    if (!isSpeechSupported()) {
      btn.disabled = true;
      btn.title = "Voice recognition not supported in this browser (use Chrome/Edge)";
      return;
    }
    btn.addEventListener("click", () => {
      if (btn.classList.contains("listening")) {
        stopListening();
      } else {
        // If this is a patient/case mic, open the panel first
        openPanel();
        startListening(btn);
      }
    });
  }

  wireMicButton("assistant-mic");
  wireMicButton("mic-patient");
  wireMicButton("mic-case");

  /* ================================================================
     ASSISTANT PANEL TOGGLE
     ================================================================ */

  function openPanel() {
    document.body.classList.add("assistant-open");
    initMessages();
    const input = $("assistant-input");
    if (input) setTimeout(() => input.focus(), 230);
  }

  function closePanel() {
    document.body.classList.remove("assistant-open");
  }

  // FAB toggles the popup open/closed
  const toggleBtn = $("assistant-toggle");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      if (document.body.classList.contains("assistant-open")) {
        closePanel();
      } else {
        openPanel();
      }
    });
  }

  // Wire close button inside panel header
  const closeBtn = $("assistant-close");
  if (closeBtn) {
    closeBtn.addEventListener("click", closePanel);
  }

  /* ================================================================
     TEXT INPUT — send on button click or Enter key
     ================================================================ */

  const inputEl = $("assistant-input");
  const sendBtn = $("assistant-send");

  function sendText() {
    if (!inputEl) return;
    const text = inputEl.value.trim();
    if (!text) return;
    inputEl.value = "";
    processText(text);
  }

  if (sendBtn) {
    sendBtn.addEventListener("click", sendText);
  }

  if (inputEl) {
    inputEl.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        sendText();
      }
    });
  }

  /* ================================================================
     SUGGESTION CHIPS — wire click events
     ================================================================ */

  const suggestionsEl = $("assistant-suggestions");
  if (suggestionsEl) {
    suggestionsEl.addEventListener("click", (ev) => {
      const chip = ev.target.closest("[data-action]");
      if (!chip) return;
      const action = chip.dataset.action;
      // Synthesise text → run through assistant
      const actionTextMap = {
        "create-case":      "create case",
        "start-monitoring": "start monitoring",
        "digitize-ecg":     "digitize and send ecg",
        "accept-case":      "accept case",
        "prepare-bed":      "prepare bed",
        "refresh-queue":    "refresh queue",
      };
      const text = actionTextMap[action] || action;
      processText(text);
    });
  }

  /* ================================================================
     INIT
     ================================================================ */

  // Init: start closed — user opens via FAB
  function initPanel() {
    initMessages();
    // Panel starts closed; FAB is always visible via CSS
  }

  // Wait for DOM ready (script is at bottom of body so it's already ready,
  // but guard in case of deferred loading)
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initPanel);
  } else {
    initPanel();
  }

  // Pre-load TTS voices (Chrome requires a user gesture first,
  // but caching the list makes subsequent calls instant)
  if (window.speechSynthesis) {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.onvoiceschanged = () => {
      window.speechSynthesis.getVoices(); // cache
    };
  }

})();
