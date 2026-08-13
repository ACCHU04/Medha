# Contributing to MEDHA LINK

Thank you for your interest in MEDHA LINK — a pre-hospital emergency coordination platform built for tier 2–3 India.  
Every contribution, from a bug fix to a new sensor driver, directly impacts patient outcomes.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Before You Start](#before-you-start)
- [How to Contribute](#how-to-contribute)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Open Contribution Areas](#open-contribution-areas)
- [Pull Request Guidelines](#pull-request-guidelines)
- [Commit Message Format](#commit-message-format)
- [Reporting Bugs](#reporting-bugs)
- [⚠ Patient Safety Note](#-patient-safety-note)

---

## Code of Conduct

Be respectful, inclusive, and constructive. This project serves emergency patients in underserved areas — keep that mission central in every discussion.

---

## Before You Start

1. **Search existing issues** before opening a new one — your idea or bug may already be tracked.
2. For **large features**, open an issue first and describe your plan. We'll discuss before you write code.
3. For **small fixes** (typos, docs, CSS tweaks), go ahead and submit a PR directly.

---

## How to Contribute

```
Fork → Clone → Branch → Code → Test → Push → Pull Request
```

```bash
# 1. Fork the repo on GitHub, then clone your fork
git clone https://github.com/<your-username>/Medha.git
cd Medha

# 2. Add the upstream remote
git remote add upstream https://github.com/ACCHU04/Medha.git

# 3. Create a feature branch (never commit directly to main)
git checkout -b feature/your-feature-name

# 4. Make your changes, then push
git push origin feature/your-feature-name

# 5. Open a Pull Request on GitHub against ACCHU04/Medha:main
```

---

## Development Setup

### Requirements

| Tool | Version |
|---|---|
| Python | 3.11+ |
| PostgreSQL | 14+ |
| Node.js | Not required (vanilla JS, no build step) |
| Git | Any recent version |

### Local run

```bash
# Clone and enter the project
cd backend

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

# Install dependencies
pip install -r requirements.txt

# Copy and edit environment variables
copy .env.example .env          # Windows
# cp .env.example .env          # macOS / Linux

# Run database migrations
alembic upgrade head

# Start the dev server
uvicorn app.main:app --reload --port 8000
```

Open:
- Ambulance simulator → http://localhost:8000/ambulance-simulator/
- Hospital dashboard → http://localhost:8000/hospital-dashboard/

Default credentials: `paramedic1 / s3curepass` · `admin1 / s3curepass`

### Run tests

```bash
pytest -v
```

---

## Project Structure

```
Medha/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app + WebSocket connection manager
│   │   ├── models.py          # SQLAlchemy ORM models
│   │   ├── schemas.py         # Pydantic request/response schemas
│   │   ├── routers/           # API route handlers
│   │   ├── sync/              # HLC clock + offline sync engine
│   │   └── static/
│   │       ├── ambulance-simulator/   # Paramedic UI (HTML/CSS/JS)
│   │       ├── hospital-dashboard/    # Hospital UI (HTML/CSS/JS)
│   │       ├── assistant.js           # AI assistant rules engine
│   │       ├── voice.js               # SpeechRecognition + TTS layer
│   │       └── assistant.css          # Assistant panel styles
│   ├── alembic/               # Database migrations
│   └── requirements.txt
├── docs/                      # Walkthroughs and design docs
└── CONTRIBUTING.md
```

---

## Open Contribution Areas

These are the areas most actively welcoming contributions:

### 🔌 Hardware & Sensor Integration
> Context: Raspberry Pi 5 edge device with ECG, SpO₂, BP, Temp (DS18B20), GPS (u-blox NEO-M9N), Camera (CSI)

- **DS18B20 temperature driver** — Python 1-Wire reader → POST to `/api/v1/vitals`
- **MAX3010x SpO₂ driver** — I²C reader with signal quality validation
- **GPS NMEA parser** — serial read from u-blox, parse lat/lon/speed, push to vitals stream
- **UPS battery monitor** — read cell voltage via GPIO or I²C fuel gauge; expose `/api/v1/device/battery`
- **Camera ECG scan** — improve the current paper ECG digitization pipeline (contrast, rotation correction, grid detection)

### 🧠 Clinical Decision Support
> Pure logic, no ML required for most of these

- **NEWS2 / MEWS auto-scoring** — calculate from live vitals (HR, SpO₂, BP, RR, Temp), show color-coded badge
- **SIRS / Sepsis flag** — rule-based: Temp + HR + RR + infection checkbox → alert
- **Shock index** — HR ÷ Systolic BP; flag if > 1.0
- **Pediatric vital ranges** — age-adjusted thresholds (HR, RR, BP) switchable in the UI

### 📡 Connectivity & Sync
- **SMS fallback** — when 4G drops, use EC25 modem AT commands to send a case summary SMS to the hospital
- **Geofence trigger** — when GPS is within 5 km of destination hospital, auto-POST `prepare_bed` event
- **HLC replay viewer** — a UI to scrub through the causal event timeline of a completed encounter

### 🌐 Internationalisation (i18n)
- **Hindi UI labels** — translate all ambulance + hospital UI strings to Hindi
- **Regional languages** — Kannada, Tamil, Telugu, Marathi translations
- **Voice protocol coaching** — Hindi TTS for step-by-step paramedic guidance based on chief complaint

### 📄 Docs & Testing
- Unit tests for HLC merge logic (`backend/app/sync/`)
- Integration tests for encounter state machine (illegal transition rejection)
- API documentation improvements (OpenAPI descriptions, example payloads)
- Architecture diagrams

---

## Pull Request Guidelines

- **One feature / fix per PR** — keep it focused and reviewable
- **Include a description** — what problem does this solve? How did you test it?
- **Link the issue** — `Closes #42` in your PR description
- **No patient data** — never include real medical records, even anonymized. Use synthetic data only.
- **No new external CDN dependencies** — the system must work offline. Vendor any new JS libraries locally.
- **Run tests before submitting** — `pytest -v` must pass

### PR title format

```
feat: add NEWS2 scoring badge to vitals panel
fix:  correct SpO₂ alert threshold for pediatric mode
docs: add sensor wiring guide for DS18B20
chore: bump alembic migration for battery_status table
```

---

## Commit Message Format

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

[optional body]
[optional footer: Closes #issue]
```

**Types:** `feat` · `fix` · `docs` · `style` · `refactor` · `test` · `chore`  
**Scopes:** `vitals` · `ecg` · `sync` · `hlc` · `ui` · `auth` · `gps` · `assistant` · `hardware`

**Examples:**
```
feat(vitals): add DS18B20 temperature driver for 1-Wire bus
fix(sync): handle HLC merge when remote tick equals local tick
docs(ecg): add paper ECG quality checklist walkthrough
```

---

## Reporting Bugs

Open an issue with:

1. **What you did** — steps to reproduce
2. **What you expected** — expected behaviour
3. **What happened** — actual behaviour + error message / screenshot
4. **Environment** — OS, browser, Python version, device (Pi 5 / laptop)

Use the label `bug` for confirmed bugs, `question` for unclear behaviour.

---

## ⚠ Patient Safety Note

MEDHA LINK is a **research prototype**. It is not certified as a medical device.  
All data in this repository is **synthetic**. Do not use with real patient information.  
Any clinical decision support features (NEWS2, SIRS, shock index) are **informational aids only** — they do not replace clinical judgment.

If you are adding a clinical algorithm, cite the source (e.g., *RCP NEWS2 guidelines 2017*) in the PR description.

---

## Thank You

MEDHA LINK exists because someone in a tier 2–3 ambulance deserves the same quality of care coordination as someone in a metro hospital. Your contribution makes that real.
