# Architecture — AI Areas Importer

## Overview

AI Areas Importer is a three-layer automation system:

1. **Presentation Layer** — Flask web app with SSE streaming frontend
2. **AI Processing Layer** — Gemini AI for data cleaning + difflib for fuzzy matching
3. **Portal Automation Layer** — HTTP session + Selenium for Indolj portal sync

---

## Component Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        BROWSER (Client)                             │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Single Page App (index.html + style.css + main.js)          │   │
│  │  Phase 1: Form  →  Phase 2: SSE Progress  →  Phase 3: Results│   │
│  └────────────────────────────┬─────────────────────────────────┘   │
└───────────────────────────────│─────────────────────────────────────┘
                                │ HTTP/SSE
┌───────────────────────────────▼─────────────────────────────────────┐
│                     FLASK APPLICATION (app.py)                      │
│                                                                      │
│  POST /api/upload-file  →  Store file + credentials in session       │
│  GET  /api/process      →  SSE stream (5-step pipeline)              │
│  POST /api/upload       →  Legacy synchronous endpoint               │
│  GET  /api/geofence-stats                                            │
│  GET  /api/branch-mapping (debug)                                    │
│                                                                      │
│  Services: resolve_city_id(), _build_importer_config()               │
│  Helpers:  load_branch_city_mapping(), load_geofence_data()          │
└──────┬───────────────────────────────────┬───────────────────────────┘
       │                                   │
       ▼                                   ▼
┌──────────────────┐            ┌─────────────────────────────────────┐
│  groq_processor  │            │          indolj_importer            │
│                  │            │                                      │
│ process_data_    │            │  AuthManager                         │
│   with_groq()    │            │    _requests_login()                 │
│                  │            │    _selenium_login()                 │
│ extract_json_    │            │                                      │
│   array()        │            │  ExistingZoneFetcher                 │
│                  │            │    _fetch_via_requests()             │
│ match_areas_to_  │            │    _fetch_via_selenium()             │
│   mapping()      │            │                                      │
│                  │            │  ZoneHTMLParser(HTMLParser)          │
│ load_city_       │            │                                      │
│   mapping()      │            │  IndoljAPIClient                     │
│                  │            │    save_zone()                       │
│ _get_cached_     │            │                                      │
│   area_mapping() │            │  run_importer()                      │
└──────────────────┘            │    Phase 1: Dedup detection          │
                                │    Phase 2: Remove wrong zones       │
                                │    Phase 3: Create/Update zones      │
                                └─────────────────────────────────────┘

Data Files
├── area_mapping.json        ← 830KB, {city_id: {area_name: area_id}}
└── branch_city_mapping.json ← Auto-learned {branch_id: {city_id}}

External Services
├── Google Gemini API        ← AI data cleaning
└── Indolj Portal            ← console.indolj.io (target system)
```

---

## Module Responsibilities

### `app.py` — Flask Application & Orchestrator

The entry point. Responsible for:
- Handling file uploads and session management
- Orchestrating the 5-step SSE pipeline
- Coordinating between `groq_processor` and `indolj_importer`
- City detection via `resolve_city_id()` (2-tier: local → portal)
- Geofence and branch mapping API endpoints

**Key Design Decision — SSE Streaming**: The `/api/process` endpoint uses Server-Sent Events to push live progress to the browser. The importer runs in a `threading.Thread` while the SSE generator polls a shared `progress_events` list, yielding events to the client.

### `groq_processor.py` — AI & Matching Engine

Responsible for:
- Chunking raw data (60 lines/chunk) and sending to Gemini AI
- Parsing, repairing, and deduplicating AI responses
- Fuzzy-matching cleaned area names to the area_mapping.json database
- Caching the 830KB area_mapping.json in memory (`_get_cached_area_mapping`)

**Key Design Decision — 3-Tier Matching**:
1. Exact string match
2. Case-insensitive exact match
3. `difflib.get_close_matches()` with 70% cutoff

**Key Design Decision — AI Chunking**: Gemini has token limits. The processor splits input into 60-row chunks, processes each chunk with full retry logic, then merges results.

### `indolj_importer.py` — Portal Automation

Responsible for:
- Authenticating to the Indolj portal (requests first, Selenium fallback)
- Fetching all existing zones from the portal (HTML parse first, Selenium fallback)
- 3-phase zone synchronization: dedup, remove wrong-zone areas, create/update
- Making POST requests to `/admin/ajax?action=saveMerchantAreas`

**Key Design Decision — Dual-Path Authentication**: The system first tries a direct HTTP POST login (fast, no browser overhead). If that fails (JS-rendered login, anti-bot), it falls back to headless Chrome.

---

## Data Flow

```
File Input (CSV/Excel/Image)
    │
    ├─→ pandas.read_csv()   ─┐
    ├─→ pandas.read_excel()  ├─→ raw_text: str
    └─→ pytesseract.image_  ─┘
        to_string()
         │
         ▼
process_data_with_groq(raw_text, area_mapping.json)
    │   Split into 60-line chunks
    │   For each chunk → Gemini API → JSON array
    │   extract_json_array() → repair truncated JSON
    │   _ensure_zone_names() → Zone_{charge} fallback
    │   Dedup by (area_name, zone_name)
    │
    └─→ structured_data: List[Dict]
         [{"Zone Name": "Zone A", "Area Name": "DHA Phase 1",
           "Delivery Charge": "99", ...}, ...]
         │
         ▼
resolve_city_id(branch_id, ...)
    │   Tier 1: branch_city_mapping.json lookup
    │   Tier 2: Portal HTML scraping
    │   Auto-save new discoveries
    │
    └─→ city_id: str ("1" = Karachi, "2" = Lahore, ...)
         │
         ▼
match_areas_to_mapping(structured_data, area_mapping.json, city_id)
    │   load_city_mapping() → city-specific {name: id} dict
    │   Per area: exact → case-insensitive → difflib fuzzy
    │
    └─→ grouped_zones: Dict, unmatched: List
         grouped_zones = {
             "Zone A": {
                 "Zone Name": "Zone A",
                 "area_ids": ["88", "215", "161"],
                 "Delivery Charge": "99",
                 ...
             }
         }
         │
         ▼
run_importer(config, grouped_zones)
    │
    ├── Phase 0: AuthManager.get_session()
    │       └─ requests login → probe → Selenium fallback
    │
    ├── Phase 1: ExistingZoneFetcher.fetch()
    │       └─ HTML parse → Selenium + Load More if needed
    │
    ├── Phase 2: Dedup detection + removal
    │       └─ IndoljAPIClient.save_zone() for affected zones
    │
    └── Phase 3: Create / Update zones
            └─ IndoljAPIClient.save_zone() for each zone
             │
             ▼
         report: Dict
         {"status": "success", "created": 2, "updated": 5, ...}
```

---

## Authentication Flow

```
AuthManager.get_session()
    │
    ├─→ _requests_login()
    │     GET  /merchant/Login  (fetch CSRF token)
    │     POST /merchant/Login  (submit credentials + CSRF)
    │     _probe_auth()         (GET /merchant/branches — 200 = logged in)
    │     ✓ Returns session if successful
    │
    └─→ _selenium_login()  (only if requests login fails)
          HeadlessChrome → navigate to login URL
          Type username/password → click submit
          Wait for redirect (not login URL)
          Extract cookies → inject into requests.Session
          ✓ Returns session with cookies
```

---

## SSE Event Protocol

```
Client opens GET /api/process?session_id=...
    │
    ├── Server yields: data: {"step": 1, "status": "active", "title": "...", "detail": "..."}
    ├── Server yields: data: {"step": 1, "status": "done", "title": "...", "detail": "..."}
    ├── Server yields: data: {"step": 2, "status": "active", ...}
    │   ...
    ├── Server yields: data: {"step": 5, "status": "done", ...}
    │
    ├── Server yields: data: {"step": "complete", "report": {...}}   ← success
    │   OR
    └── Server yields: data: {"step": "error", "message": "..."}     ← failure
```

---

## Concurrency Model

The SSE generator runs in the main Flask request thread. The importer runs in a `threading.Thread`. They communicate via:
- `progress_events: list` — shared mutable list (thread-safe for GIL-protected append/pop)
- `report_holder: dict` — result container
- `error_holder: dict` — error container

The SSE generator polls `progress_events` with `time.sleep(0.3)` until the thread completes.

> **Production Note**: This model works correctly for a single-worker deployment. For multi-worker gunicorn, upgrade to a Redis-backed job queue (Celery or RQ) with SSE served by the worker.
