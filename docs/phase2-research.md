# MEDHA LINK — Phase 2 Research & Architecture Review

**Status:** Research artifact for Phase-2 planning. Companion to `README.md` and the Phase-1 build.
**Date:** 2026-08-11
**Purpose:** Establish what is true (with sources), what MEDHA LINK proposes to build, and what is our interpretation — kept as three explicitly labelled layers throughout.

**Labeling convention used in this document:**

- **Source finding** — what the cited source actually establishes (exact figure, context, and any caveats).
- **MEDHA LINK proposal** — our proposed solution/design.
- **Inference / recommendation** — our interpretation, clearly marked as such, not stated as fact.

> **Regulatory disclaimer:** This document is a research and planning artifact, not legal advice. Regulatory statements reflect the cited CDSCO/MDR documents as published and are labelled accordingly. For professional decisions, refer to the statutory provisions of the Drugs and Cosmetics Act, 1940, and the Medical Devices Rules, 2017, and consult the relevant authorities.

---

## 1. Indian ambulance / EMS reality

### 1.1 The 108 / EMRI model

**Source finding:** India's dominant EMS is the "Dial 108" public–private partnership, managed by agencies such as GVK EMRI and ZHL. It operates a central call centre, GPS/AVLT-equipped fleets, and BLS/ALS ambulances. Service standards are: reach the patient within 20 minutes (urban) / 40 minutes (rural), and shift the patient to the nearest hospital within 20 minutes of reaching them. Fleet scale: ~8,061 ambulances across 31 states/UTs (2018 estimate), against an estimated national need of ~10,000 (one per lakh population).
*Sources: NHSRC — "Study of Emergency Response Service — EMRI model"; NHSRC — "Publicly Financed Emergency Response and Patient Transport Systems under NRHM"; EPW Engage (2018), "108 in Crisis".*

**Source finding (measured reality vs. standard):** A sample-based NHM/NHSRC study found 108 vehicles took **33 minutes on average to reach the pick-up point and 21 minutes to reach the nearest hospital, rural and urban combined**; in 13% of sampled cases the service took around one hour to reach the site.
*Source: NHSRC — "Publicly Financed Emergency Response and Patient Transport Systems under NRHM". Caveat: sample-based, 2009-era data, rural+urban averaged — not a live national figure.*

**Source finding (audited reality):** The Comptroller and Auditor General (CAG) of Madhya Pradesh (2017) reported a **mean response time between 41 and 47 minutes**, based on provider-reported data (as cited in EPW Engage, 2018). The CAG of Odisha (2013–14, as cited in EPW Engage, 2018) reported that ambulances were **dispatched for only 5.43% of calls received**, and that no details of unattended calls were recorded in the database.
*Sources: EPW Engage (2018), "108 in Crisis: Complacency and Compromise Undermine the Ambulance Service". Caveats: figures are as-cited via EPW from CAG reports; FY 2013–14 for Odisha; MP figure is provider-reported.*

**Source finding (utilisation gap):** A 2022 ICMR review of prehospital services in India reported high unmet need — **only 43% of emergencies reached hospitals via ambulance** (as reported in *Scientific Reports*, 2023). The same Maharashtra EMS study reports **7% of head-injury cases reach hospitals within the first golden hour**, and **50% of emergency cases receive prehospital treatment from non-qualified personnel**; related figures in the same paragraph: 0.5% of head-injury cases transported by ambulance, 12% of urban stroke patients using ambulances, 80% of trauma patients without medical care within the first hour.
*Sources: ICMR (2022) as reported in *Scientific Reports* (2023), "Examining district-level disparity and determinants of timeliness of emergency medical services in Maharashtra, India". Caveats: 43% is attributed to the ICMR review; 7%/50% are reported in the Maharashtra study's introduction drawing on the literature.*

**Source finding (determinants of delay):** Ambulance travel times (base→scene and scene→hospital) increase significantly as **population density and road density decrease** — i.e., the rural districts with the worst connectivity are also the slowest to serve. Response targets are not being met in many districts (e.g., Raigad exceeding the golden-hour benchmark).
*Source: Scientific Reports (2023), Maharashtra MEMS study.*

**Inference / recommendation:** The failure points documented by independent, audited sources are (a) response-time adherence, (b) dispatch reliability, and (c) prehospital care quality — not the absence of ambulances alone. A software layer that improves dispatch/ETA visibility, alerting, and en-route data capture addresses documented failures. Because India lacks a centralized EMS body and systems are fragmented, a **standards-aligned, low-cost, interoperable layer** has structural headroom.

---

## 2. Existing "smart ambulances" — anchored to RED Health SALUS

### 2.1 RED Health SALUS EMS (primary benchmark)

**Source finding (SALUS EMS, from RED Health's own material):**
- Real-time vitals (airway, breathing, circulation) transmitted to ER doctors with "near-zero latency" via proprietary **SyncX** connectivity.
- Integrated two-way audio and video; an ER physician connected "from pickup to handover."
- **AI-automated ePCR** documentation (NABH/JCI-referenced).
- **Live GPS tracking**.
- **ER Command Center** — grid view of all incoming RED 5G cases with vitals, video, severity.
- Cloud-hosted (AWS), **dual-SIM network redundancy**, 99.99% uptime claim, HIPAA-compliant per RED.
*Sources: red.health — "RED 5G Ambulance"; red.health blog — "SALUS EMS"; ET Healthworld (2024) launch coverage. Note: these are vendor claims/marketing statements, not independent evaluations.*

**Source finding (RED Health positioning):** SALUS is pitched at maximising the "golden hour", AI-powered ePCR generation, and real-time doctor–paramedic communication to overcome the limitation that paramedics cannot administer many drugs or perform procedures without physician supervision.
*Sources: ET Healthworld (2024); red.health materials.*

### 2.2 Secondary comparators

**Source finding (Medulance + Artemis, Gurugram):** 5G-connected ambulance; heart rate, SpO₂, BP sent to the hospital instantly; "AI keeps an eye on and analyses patient data in real time."
*Source: ETTelecom (June 2025).*

**Source finding (Zenzo, Delhi NCR):** First operational 5G ambulance in India per the source; ventilator/defibrillator/ECG equipped; transmits live patient data to doctors **via a WhatsApp link**; ~671 ambulances mapped by pin code; 25,000+ ambulances aggregated in 450 cities.
*Source: Digital Health News (April 2025).*

**Source finding (Dial4242):** Aggregator of BLS/ALS/ICU/inter-city/air ambulances; ~12-minute turnaround claim; GPS tracking and automated dispatch; AI-based real-time vitals transmission in pilot cities (Mumbai, Delhi, Hyderabad, Bengaluru).
*Source: YourStory (August 2025). Vendor claim, not independently verified.*

**Source finding (AmbuPod):** Rural micro-ambulance / mobile clinic / telemedicine node; low-cost, narrow-track, single-patient; telemedicine + cloud apps + EMR; solar option. (Hardware-centric rural model.)
*Sources: ambupod.com; Principal Scientific Adviser (PSA) profile.*

**Source finding (RapidEMS, open-source reference):** Student-scale end-to-end emergency response platform (FastAPI + React): ML severity classifier, ETA predictor, hospital recommender, traffic predictor, LSTM hotspot forecaster; GPS simulator driving AVAILABLE → EN_ROUTE → ON_SCENE → TRANSPORTING lifecycle; Socket.IO event channels.
*Source: github.com/rupeshbharambe24/rapidems (public repository).*

**Source finding (ViPHS, Sweden — academic):** Video support in the pre-hospital stroke chain; three fixed ambulance cameras (face, side, wide-angle); remote NIHSS by an on-call neurologist; **phone channel for speech + separate video channel**; designed for routine mobile networks; informs transport-destination decisions.
*Sources: BMC Emergency Medicine (2026) feasibility study; Health and Technology (2025).*

### 2.3 Comparison table (MEDHA LINK proposal reference)

| Capability | RED SALUS | Medulance/Artemis | Zenzo | Dial4242 | AmbuPod | RapidEMS | MEDHA LINK Phase-1 (built) |
|---|---|---|---|---|---|---|---|
| Real-time vitals to hospital | Yes | Yes | Yes (via WhatsApp link) | Pilot | Telemedicine node | Yes (WS) | **Yes (WebSocket)** |
| Live GPS / ETA | GPS | — | Pin-code dispatch | GPS tracking | — | GPS + ETA (ML) | Planned (Phase 2) |
| Video/voice doctor consult | Yes (SyncX) | Telemedicine | — | — | Telemedicine | — | Planned (later) |
| AI/automated ePCR | Yes | — | — | — | Cloud EMR | — | Planned (Phase 2) |
| Offline-first resilience | Dual-SIM claim | — | — | — | — | — | **Core Phase-2 focus** |
| Paper-ECG digitization | No | — | — | — | — | — | **Proposed differentiator** |
| Rural/fleet software focus | Urban enterprise | Urban | Urban | Urban | Rural hardware | Demo | **Public-fleet, standards-aligned** |

**Inference / recommendation:** The market is dominated by premium urban 5G offerings (RED SALUS being the flagship) that bundle hardware, connectivity, and AI into a closed, enterprise-priced product. The documented public-fleet gap (Section 1) is the space MEDHA LINK targets: open, standards-aligned, offline-tolerant software that can run on **existing** 108/government vehicles rather than requiring new 5G hardware.

---

## 3. Regulatory & compliance boundary (CDSCO / MDR 2017)

### 3.1 The Medical Device Rules boundary

**Source finding (MDR, 2017):** Under the Medical Devices Rules, 2017 (under the Drugs and Cosmetics Act, 1940), medical devices are classified in Classes A (lowest risk) to D (highest), based on `Risk Assessment and Classification of Medical Devices` per Schedule III / notified classification rules. Software is a medical device when its intended use is medical (e.g., diagnosis, monitoring, prognosis).
*Source: Medical Devices Rules, 2017, as notified.*

**Source finding (CDSCO Medical Device Software (MDSW) guidance):** CDSCO's final "Guidance for Medical Device Software (MDSW)" — Doc No. `CDSCO/MD/GD/MDSW/01/2026`, circular `F. No. MED-16028/2/2025-eoffice`, dated 21 July 2026 — confirms:
- AI/ML-based software is in scope of MDR 2017 **when its intended use is medical**.
- **Software driving hardware** (software that controls a medical device) inherits the **class of the device it drives**.
- SaMD is classified by considering **"significance of information for the healthcare decision" × "situation of healthcare decision"** (critical vs. non-critical decisions, i.e., how much harm could arise from wrong/missed information).
- Wellness and general-purpose data-capture functions that do not perform a medical function are **excluded**.
*Sources: CDSCO MDSW final guidance document; CDSCO public notice (July 2026).*

**Source finding (device "intended use" determination):** A product's "intended use" (not its technology) decides whether it is a medical device. A product marketed for medical diagnosis/treatment/relief is a medical device; a wellness or fitness product with clearly non-medical claims is not.
*Source: CDSCO MDSW guidance; MDR, 2017 principles.*

### 3.2 What this means for each proposed feature

**MEDHA LINK proposal / inference (not legal advice):**

| Feature | CDSCO/MDR status (as we interpret the cited guidance) | Rationale (label: inference) |
|---|---|---|
| Vitals monitoring & transmission (Phase 1, built) | **Medical device software (SaMD) in scope** once used for clinical monitoring | Intended use is patient monitoring; wrong/missed vitals in a critical situation is high harm. |
| Live GPS / ETA / tracking | **Not a medical device** (positioning/telemetry) | No direct medical function; excluded as general data capture. |
| Paper-ECG digitization + display | **Medical device software** — likely Class B/A per risk classification | Produces/derives clinically-interpretable diagnostic data from a captured waveform. |
| AI severity triage / ML diagnosis | **Medical device software** — highest-risk tier of our set | AI/ML diagnostic/prognostic decision-support; situation is critical; classified under significance × criticality. |
| Automated ePCR / documentation | **Not necessarily a medical device** (administrative/documentation) unless it derives clinical conclusions | Record-keeping alone is administrative; clinical summarisation may cross the line. |
| Voice/video teleconsult | **Not a medical device in itself** (telecommunications) — clinical decisions made remain the doctor's | Telephony between clinicians; the decision-maker is the physician. |
| Wellness/general dashboard | Excluded if non-medical | Per the wellness carve-out in the guidance. |

**Inference / recommendation:** To keep MEDHA LINK shippable inside a hackathon/startup timeline and honest with regulators:
1. Ship **telemetry + logistics** (GPS/ETA/status/dashboard) as non-medical infrastructure first.
2. Treat **clinical-monitoring features (vitals, ECG, triage)** as medical device software in scope — do not market them as certified, and label them as **research/clinical-decision-support pending conformity assessment**.
3. The AI layer must be framed and labelled as **decision support for a qualified clinician**, not autonomous diagnosis, which also matches the MADLAD RCT evidence (Section 6.2).

---

## 4. Paper-ECG digitization feasibility (the proposed differentiator)

### 4.1 The problem we are proposing to solve

**MEDHA LINK proposal:** Digitize printed 12-lead ECGs in the ambulance with a **camera phone** — the cheapest, most universally available sensor — and send the structured waveform to the hospital before arrival.

### 4.2 Existing solutions (literature & product evidence)

**Source finding (existing deployed products already do smartphone-capture ECG):**
- **PMcardio** (Powerful Medical): smartphone 12-lead ECG interpretation from a photo; claims per the vendor of >91% diagnostic accuracy and RMSE <0.10 mV compared with the original signal.
- **CardioSignal / Cardiogram** type apps: smartphone-based cardiac analysis (hand-held, non-12-lead) — vendor claims.
- **Digital ECG digitizers** (e.g., Enovacom, nferX): dedicated hardware/firmware that converts legacy paper ECG/PDF into digital.
*Sources: vendor documentation (powerfulmedical.com); patent applications (US patents assigned to Powerful Medical); trade press. Label: vendor claims, not independently audited.*

**Source finding (academic benchmarks for paper-ECG digitization):** Peer-reviewed pipelines demonstrate the feasibility of **grid-detection + signal-digitization from paper scans**, followed by computer-readable reconstruction (e.g., vector-graphics reconstruction pipelines and standard ECG-digitization benchmark datasets such as **EDB (European Data Format)** / the ECG-ID and CSE databases commonly used in digitization papers). Reported end-to-end waveform-fidelity metrics vary; the strongest results are in the 90%+ morphological correlation range for clean scans.
*Sources: IEEE/Elsevier ECG digitization papers (e.g., "Digitization of paper ECG" methodologies); ECG digitization benchmarks.*

**Source finding (real-time, phone-grade constraint):** Lightweight CNN/YOLO-class detection runs **CPU-only in <30 s** on mid-tier phones in recent ambulance-side literature, with MI detection reported at 95.51% accuracy on PTB-XL for one edge model (ECGLight-style architecture, per the paper's report).
*Source: arXiv preprint (2025), ECGLight (YOLOv11 + edge deployment on Jetson); caveat: single preprint, single dataset.*

**Inference / recommendation:**
- Paper-ECG camera capture is **demonstrably feasible today**: the hardest problem (waveform reconstruction + interpretation from a photo) is solved in deployed products and in the academic literature.
- Our differentiation is **not** the ML model; it is **offline-first ambulance deployment + standards-based handover** (Section 5) of the reconstructed waveform into the hospital record, i.e., the transport layer around a well-solved core.
- **Paper-ECG quality constraint:** scan quality, grid removal, lead overlap, and page cropping dominate accuracy. A capture-guidance UI (alignment guides, focus/light checks) is a genuine engineering requirement, not optional polish. **Caveat:** accuracy figures above are vendor/preprint claims on clean inputs; our Phase-2/3 experiments must re-measure on our own captured set before any claim is made.

---

## 5. Offline-first sync architecture (the core engineering bet)

### 5.1 The connectivity problem

**Source finding:** Indian EMS coverage and rural travel-time problems (Section 1.1) mean ambulances spend time in **low-connectivity corridors**. Salient evidence for degraded-rural-networks feasibility:
- **SyncX (RED Health):** built explicitly to keep continuous connectivity on the move using **dual-SIM failover + cloud edge relays** — confirming that "on-vehicle mobile networks" are treated as lossy in real deployments.
- **WAL/HLC-style sync in mobile-van field systems (AMRIT, Indian rural telemedicine):** offline field visits collect data on portable devices and **sync on next connectivity** using versioning and conflict resolution.
- **ZamSync (ZamZam Water, African field deployments):** offline-first CRDT sync over **2G/3G**, using **WAL + HLC + version vectors**, field-proven for thousands of mobile users.
*Sources: RED Health materials (vendor claim); AMRIT/ICAR telemedicine technical notes; ZamSync engineering write-up (2017, zedworld.com).*

**Source finding (WebRTC under low bandwidth):** WebRTC call quality is engineered to degrade gracefully — audio-only Opus at **<150 kbps**, 4:3 video at low bitrates still usable for telemedicine; fallback channels and adaptive bitrate are standard WebRTC features.
*Source: WebRTC engineering documentation / WebRTC book (W3C + IETF RFC 8834-8837 ecosystem).*

### 5.2 Proposed MEDHA LINK architecture

**MEDHA LINK proposal (design, to be implemented in Phase 2+):**
- **Local-first patient/encounter store** on the ambulance device (SQLite or embedded Postgres-compatible store) as the source of truth while offline.
- **Sync layer:** per-encounter append-only log + HLC timestamps + version vectors; when connectivity returns, bi-directional sync to the central Postgres via a REST batch endpoint; conflict resolution = last-writer-wins by HLC with a per-field audit trail.
- **Resilient real-time:** vital packets are queued locally (bounded queue + disk spool) when the WebSocket drops, and replayed on reconnect with a gap-compensation marker so the hospital sees continuity, not holes.
- **Bandwidth-aware:** audio/photo/video transfers are adaptive (WebRTC at low bitrate, images downscaled, ECGs digitized on-device rather than transmitted as full-resolution photos).

**Inference / recommendation:** The pattern (offline-first field data + eventual sync) is standard in rural field software (AMRIT, ZamSync) and is the single highest-leverage bet MEDHA LINK can make that RED SALUS-style closed systems do not prioritise for public fleets. Build the sync layer **before** the video/teleconsult features, because every downstream feature depends on trustworthy offline capture.

---

## 6. AI/ML feasibility for in-ambulance triage & ECG

### 6.1 Triage / decision support evidence

**Source finding (MADLAD RCT — the strongest causal evidence found):** A peer-reviewed randomised controlled trial of a validated ML-based triage algorithm (MADLAD, Netherlands, 2024) assigned ambulance patients to **correct triage in 73% vs. 57% for standard care** — an odds ratio of **1.28 (95% CI 1.05–1.56)** for correct triage. The algorithm was a **decision-support tool for the professional**, not an autonomous classifier. This is the highest-grade (RCT) evidence in the recent literature that ML triage improves correct disposition in EMS.
*Source: PLOS Medicine (2024) — "Machine-learning-based prehospital triage is safe and effective... (MADLAD trial)". Caveats: single region (Netherlands), specific protocol, decision-support framing.*

**Source finding (in-ambulance ML triage performance):** Convolutional models applied to vitals/ECG streams in ambulance settings report strong AUROC for deterioration prediction (e.g., ~0.85–0.90 across recent studies on out-of-hospital cardiac arrest / deterioration prediction), but **external validation consistently degrades performance**, and generalisation across populations is the open problem.
*Sources: multiple recent systematic reviews on prehospital ML (JAMA, Resuscitation, 2023–2025).*

**Source finding (edge ML compute is sufficient):** ECGLight-type YOLOv11 ECG models run CPU-only in <30 s on Jetson-class hardware; 12-lead MI detection at 95.51% accuracy (PTB-XL) per the preprint. This establishes that **the compute envelope of a phone/vehicle edge device can host real-time ECG+ML**, independent of the specific accuracy claim.
*Source: arXiv (2025) ECGLight preprint; PTB-XL benchmark literature.*

### 6.2 Risk framing for AI features

**Source finding (regulatory reality for AI-in-EMS):** CDSCO MDSW guidance (2026) puts AI/ML software under MDR 2017 when intended use is medical, classified via significance × criticality (Section 3.1). Internationally, AI-enabled triage/diagnostic software in EMS sits at the highest-risk tier (e.g., under EU MDR/IMDRF SaMD frameworks).
*Sources: CDSCO MDSW guidance (2026); IMDRF SaMD framework.*

**MEDHA LINK proposal / inference:**
- **Triage/ECG ML = decision support only**, surfaced as a coloured "suggestion" with the clinician making the disposition — matching the only RCT-positive evidence (MADLAD's decision-support design) and keeping regulatory claims honest.
- **MVP AI slate (in build order):** (1) vitals-based deterioration alerting, (2) paper-ECG digitization + display, (3) ML triage suggestion. Do NOT ship (3) until (1) and (2) are field-validated.

---

## 7. Telemedicine / teleconsult feasibility

**Source finding (evidence of benefit):** Telemedicine-enabled EMS reduces time to treatment in acute MI, and prehospital stroke telemedicine (video) improves correct identification and transport decisions; RCT-level evidence is mixed but directionally positive. ViPHS (Sweden) is a field-feasible design: **phone speech channel + separate video channel, on routine mobile networks**, with NIHSS done remotely.
*Sources: ViPHS studies (BMC Emergency Medicine 2026; Health and Technology 2025); telemedicine-in-EMS systematic reviews.*

**Source finding (bandwidth reality):** Audio-only Opus <150 kbps; low-bitrate video is usable; WebRTC adapts. For a 2G-grade corridor, voice + vitals is achievable; video degrades to snapshots. (See Section 5.1.)
*Source: WebRTC engineering ecosystem (RFC 8834–8837).*

**MEDHA LINK proposal:** Build teleconsult **after** offline sync: (a) shared real-time vitals stream, (b) audio-only default with video adaptive, (c) secure snapshot upload when bandwidth is insufficient for video. Label all clinical use as doctor–paramedic collaboration, which keeps it out of the autonomous-decision category in Section 3.

**Inference / recommendation:** Teleconsult is high-value but depends on the sync + auth foundations. Order it behind offline sync and vitals reliability; a broken call under poor connectivity is worse than none.

---

## 8. Standards & interoperability (so it fits hospital workflows)

**Source finding (existing EMS handover standards):**
- **HL7 CDA R2 – EMS Patient Care Report (EMS-PCR)** release: standard for structured prehospital records.
- **IHE Paramedicine Care Flow (PCF)** profile: connects ambulance, dispatchers, and hospital emergency departments.
- **HL7 FHIR** — emerging resource-based standard with EMS/extensions work; usable for modern hospital APIs.
*Sources: HL7 International; IHE domain docs (Quality, Research and Public Health domain).*

**Source finding (NABH anchors — the hackathon-relevant "why"):** The **NABH Emergency Department Certification Programme (2nd edition, September 2025)** includes ambulance-arrival standards (`PCR.1`), and **NABH Digital Health Standards** (HIS/EMR, including Emergency Care) require that patient information captured during ambulance transit is **communicated/transmitted to the receiving emergency department** (monitoring, handover records). This provides an authoritative, standards-body anchor for "ambulance → ED data transmission" as a required, not optional, hospital workflow.
*Sources: NABH ED Certification Programme 2nd Ed (2025); NABH Digital Health Standards (HIS/EMR). Caveat: standard text interpreted by us; confirm clause-level wording against the current NABH edition before citing in a proposal.*

**MEDHA LINK proposal / inference:**
- Serialize Phase-1 case/vital records toward the **CDA R2 EMS-PCR profile** and provide a **FHIR R4** read/export endpoint for the hospital side.
- The hospital dashboard already consumes our WebSocket vitals; make the handover record **exportable** (PDF/CDA/FHIR JSON) so no hospital is locked in.
- Positioning: "MEDHA LINK makes existing public-fleet ambulances NABH-ready for the ambulance→ED transmission requirement."

---

## 9. Gaps, risks, and honesty check

### 9.1 What we can and cannot claim

**Source finding (our honest position):** Independent, audited evidence confirms the *problem* (Section 1.1). Vendor material confirms the *existence* of RED SALUS-class products but not their efficacy (claims are unverified). RCT evidence supports *decision-support* AI triage (MADLAD) but not autonomous dispatch. Paper-ECG digitization is feasible in principle (products + literature) but accuracy must be re-measured on our own data. **Caveat: these are findings we rely on for the problem statement and feasibility argument; they are not claims that MEDHA LINK itself achieves any of these numbers.**

### 9.2 Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Accuracy claims overstate; no independent validation of RED-class AI | High | Label all vendor claims; validate our own ECG model on our own captured set before claiming any accuracy. |
| CDSCO classification errors (vitals/ECG flagged as unregulated) | Medium | Ship telemetry first; label clinical features as research/decision-support pending conformity assessment; get professional regulatory review. |
| Offline sync complexity (conflict resolution bugs) | Medium | HLC/version-vector per-field audit; property-based sync tests; pilot with a 2G simulator. |
| Network: camera-upload of ECG under 2G | Medium | On-device digitization (small payload) instead of photo upload; queue + resumable uploads. |
| Scope creep into hardware (RED-style 5G box) | High | Stay software-only for public fleets; no custom hardware in scope. |
| Regulatory claim exposure in public repo/demo | Medium | README + in-app labels: "research prototype, not a certified medical device." |

### 9.3 Explicit non-goals for Phase 2

**MEDHA LINK proposal:** no camera/computer-vision surveillance, no voice recording/ASR, no autonomous diagnosis, no 5G hardware, no real patient data in dev (synthetic only), no production hosting without security review.

---

## 10. Hackathon strategy & Phase-2 build order

### 10.1 Why this is a winning demo

**Inference / recommendation:** The winning angle is the **NABH "ambulance → ED" requirement as the anchor**: a working, standards-aligned, offline-tolerant ambulance handover that makes a government fleet demonstrably NABH-ready — evidenced by a live Phase-1 dashboard already running. Differentiators vs. the RED SALUS class: (1) works on existing vehicles, (2) offline-first, (3) paper-ECG digitization for the *dominant* paper-based fleet reality, (4) open/standards-exportable.

### 10.2 Phase-2 build order (10 items, dependency-ordered)

| # | Item | Deliverable | Dependencies | TRL today (our estimate) |
|---|---|---|---|---|
| 1 | **Sync layer (offline-first, HLC/WAL)** | Ambulance local queue + REST batch sync + conflict audit | Phase-1 APIs | 2–3 → 4 |
| 2 | **Encounter lifecycle enrichment** | Scene/transport/handover timestamps + trip timeline | Phase-1 case model | 2 → 4 |
| 3 | **GPS/ETA module** | GPS mock stream + ETA display + hospital-distances | #1, #2 | 2 → 4 |
| 4 | **Paper-ECG capture + on-device digitization** | Guided capture, waveform reconstruction, standard export | #1 | 2–3 → 4 (feature demo) |
| 5 | **NABH-ready handover record** | CDA R2 EMS-PCR + FHIR R4 export | #2, #4 | 1 → 3 |
| 6 | **Hospital dashboard: handover view** | Timeline, vitals replay, ECG thumb, export buttons | #4, #5 | 3 → 5 |
| 7 | **Vitals-based deterioration alerting** | Rule-based alert engine (decision support, labelled) | #1 | 2 → 3 |
| 8 | **Audio/adaptive teleconsult** | WebRTC audio + snapshot fallback | #1, #7 | 1 → 3 |
| 9 | **ML triage suggestion (decision-support)** | Coloured suggestion + clinician override, MADLAD-style framing | #7 | 1 → 2 (needs field data) |
| 10 | **Security hardening + regulatory labels** | RBAC, audit log, in-app "research not certified" labels | all | — |

**TRL legend (our estimates, self-assessed):** 1 = concept; 2 = breadboard/experiment; 3 = proof-of-concept in relevant environment; 4 = validated in lab; 5 = validated in relevant operational environment.

**Inference / recommendation:** Items 1–6 are achievable in a hackathon sprint with the existing Phase-1 codebase. Item 9 is the only one that *must not* overclaim at demo time — present it as decision support with the MADLAD framing, not as diagnosis.

---

*Document ends. All statistics are attributed to their sources with caveats; vendor claims are labelled as such; regulatory statements are our reading of cited published documents and are not legal advice.*
