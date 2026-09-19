<div align="center">

# 🚀 AI Areas Importer

**Automated Delivery Zone Sync for Indolj POS**

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.x-black?logo=flask)](https://flask.palletsprojects.com)
[![Gemini AI](https://img.shields.io/badge/AI-Google%20Gemini-4285F4?logo=google)](https://ai.google.dev)
[![Selenium](https://img.shields.io/badge/Selenium-4.x-43B02A?logo=selenium)](https://selenium.dev)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

*Upload a messy CSV → AI cleans it → Delivery zones sync automatically*

</div>

---

## What Is This?

**AI Areas Importer** is an enterprise-grade automation platform for restaurant chains and food delivery operators using the [Indolj POS system](https://indolj.io). It eliminates the painful manual process of configuring delivery zones per branch.

### The Problem It Solves

Every time a restaurant chain wants to update delivery pricing by area, a staff member has to:
1. Open the Indolj portal for every branch
2. Manually search for each delivery area
3. Type in the correct fee for each zone
4. Repeat for hundreds of areas across multiple cities

This takes hours and is error-prone. **AI Areas Importer does it in under 2 minutes.**

### How It Works

```
📄 Upload CSV/Excel/Image
        ↓
🧠 Gemini AI cleans & structures the data
        ↓
🔍 Fuzzy-match areas to 10,000+ area database
        ↓
🔐 Authenticate to Indolj portal
        ↓
☁️  Sync all delivery zones automatically
        ↓
📊 View results dashboard
```

---

## Features

| Feature | Description |
|---|---|
| **Multi-format Upload** | CSV, Excel (.xlsx/.xls), JPG, PNG (via OCR) |
| **AI Data Cleaning** | Fixes spelling errors, expands grouped areas, normalizes zone names |
| **Smart City Detection** | 2-tier: local JSON cache → portal scraping |
| **Fuzzy Area Matching** | 3-tier: exact → case-insensitive → difflib 70% cutoff |
| **Auto-Deduplication** | Detects and fixes areas placed in wrong zones |
| **Real-time SSE Progress** | Live 5-step progress stream in the browser |
| **Auto-Learning Cache** | Saves discovered branch→city mappings for future use |
| **Graceful Degradation** | Falls back from `requests` to Selenium if needed |

---

## Quick Start

### Prerequisites

- Python 3.11+
- Google Chrome (for Selenium fallback)
- Tesseract OCR *(optional, only for image uploads)*
  - Windows: [Download installer](https://github.com/UB-Mannheim/tesseract/wiki)
  - Linux: `sudo apt install tesseract-ocr`

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/yourname/DeliveryZoneApp.git
cd DeliveryZoneApp

# 2. Create a virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables
copy .env.example .env
# Edit .env and add your Gemini API key

# 5. Run the app
python app.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

### Getting a Gemini API Key

1. Go to [Google AI Studio](https://aistudio.google.com/)
2. Click **Get API Key**
3. Copy the key and add it to your `.env` file:
   ```
   GEMINI_API_KEY=your_key_here
   ```

---

## Usage

1. **Enter your Indolj portal credentials** — Username, Password, Merchant ID, Branch ID
2. **Upload your file** — Drag & drop or browse for CSV/Excel/Image
3. **Click "Start Processing"** — Watch the 5-step live progress
4. **Review results** — See created/updated/failed zones and any unmatched areas

### Supported CSV Format

Your CSV can have any of these column names (AI will figure it out):

```csv
Area Name, Delivery Charge, Zone Name
DHA Phase 1, 99, Zone A
Gulshan-e-Iqbal, 149, Zone B
North Nazimabad all block, 120, Zone C
```

The AI handles:
- Messy column names
- Spelling errors (`"DHA Phaze 6"` → `"DHA Phase 6"`)
- Grouped entries (`"North Nazimabad all block"` → 14 separate block entries)
- Old/New price columns (always uses the New price)

---

## Project Structure

```
DeliveryZoneApp/
├── app.py                    # Flask application — routes & SSE stream
├── groq_processor.py         # AI processing & area matching
├── indolj_importer.py        # Portal automation & HTTP API client
├── area_mapping.json         # 830KB area database (10,000+ areas, 9 cities)
├── branch_city_mapping.json  # Auto-learned branch→city cache
├── requirements.txt          # Python dependencies
├── .env.example              # Environment variable template
├── .gitignore
├── static/
│   ├── css/style.css         # Dark theme UI styles
│   ├── js/main.js            # SSE client & drag-drop UI
│   └── assets/icons/
├── templates/index.html      # Single-page app (3-phase UI)
├── uploads/                  # Temp file storage (auto-cleaned)
└── docs/                     # Full documentation
    ├── Architecture.md
    ├── Installation.md
    ├── Configuration.md
    ├── DeveloperGuide.md
    ├── Deployment.md
    ├── Troubleshooting.md
    ├── API.md
    ├── FolderStructure.md
    └── Workflow.md
```

---

## Configuration

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | ✅ Yes | Google Gemini API key |
| `TESSERACT_PATH` | ❌ Optional | Path to Tesseract binary (Windows) |

See [docs/Configuration.md](docs/Configuration.md) for full details.

---

## Documentation

| Document | Description |
|---|---|
| [Architecture.md](docs/Architecture.md) | System design & component overview |
| [Installation.md](docs/Installation.md) | Step-by-step setup guide |
| [Configuration.md](docs/Configuration.md) | All config options explained |
| [DeveloperGuide.md](docs/DeveloperGuide.md) | Code walkthrough for contributors |
| [Deployment.md](docs/Deployment.md) | Docker & production deployment |
| [Troubleshooting.md](docs/Troubleshooting.md) | Common issues & solutions |
| [API.md](docs/API.md) | REST API reference |
| [FolderStructure.md](docs/FolderStructure.md) | Full folder & file reference |
| [Workflow.md](docs/Workflow.md) | End-to-end data flow walkthrough |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web Framework | Flask 3.x |
| AI / LLM | Google Gemini 2.0 Flash (via OpenAI-compatible API) |
| Browser Automation | Selenium 4.x + webdriver-manager |
| HTTP Client | requests + urllib3 |
| Data Parsing | Pandas, openpyxl, Pytesseract |
| Frontend | Vanilla HTML/CSS/JS + SSE |
| Styling | CSS Custom Properties, Outfit font, JetBrains Mono |
| Icons | Phosphor Icons |

---

## Security Notes

- **Never commit your `.env` file** — it's in `.gitignore`
- Portal credentials are stored only in server memory for the duration of a request
- The `/api/branch-mapping` endpoint is for debugging only — restrict it in production
- In production, run behind Nginx with HTTPS and restrict port 5000 to localhost

See [docs/Deployment.md](docs/Deployment.md) for production hardening steps.

---

## License

MIT License — see [LICENSE](LICENSE) for details.
