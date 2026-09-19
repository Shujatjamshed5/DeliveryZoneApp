# Folder Structure Reference

## Complete Tree

```
DeliveryZoneApp/
│
├── app.py                         ← Flask application (main entry point)
├── groq_processor.py              ← AI processing & area matching engine
├── indolj_importer.py             ← Portal automation (HTTP + Selenium)
│
├── area_mapping.json              ← Area database: {city_id: {name: area_id}}
├── branch_city_mapping.json       ← Auto-learned cache: {branch_id: {city_id}}
│
├── requirements.txt               ← Python package dependencies
├── .env                           ← Secret env vars (GITIGNORED — never commit)
├── .env.example                   ← Template with placeholder values
├── .gitignore                     ← Git ignore rules
├── README.md                      ← Project overview and quick start
│
├── static/                        ← Browser-served static assets
│   ├── css/
│   │   └── style.css              ← Full UI stylesheet (913 lines, dark theme)
│   ├── js/
│   │   └── main.js                ← SPA logic: SSE client, drag-drop, stepper
│   └── assets/
│       └── icons/
│           └── delivery.png       ← Hero icon (delivery bike)
│
├── templates/                     ← Flask (Jinja2) HTML templates
│   └── index.html                 ← Single-page app (3 phases: form/progress/results)
│
├── uploads/                       ← Temp storage for uploaded files (auto-cleaned)
│
├── docs/                          ← Full project documentation
│   ├── Architecture.md            ← System design, data flow, concurrency model
│   ├── API.md                     ← REST API reference
│   ├── Configuration.md           ← All config options
│   ├── DeveloperGuide.md          ← Code walkthrough, how-to guides
│   ├── Deployment.md              ← Docker, Gunicorn, Nginx, systemd
│   ├── FolderStructure.md         ← This file
│   ├── Installation.md            ← Step-by-step setup guide
│   ├── Troubleshooting.md         ← Common issues and fixes
│   └── Workflow.md                ← End-to-end data flow narrative
│
└── chromedriver-win64/            ← (Legacy — ChromeDriver now auto-managed)
```

---

## File Descriptions

### Root Files

| File | Size | Purpose |
|---|---|---|
| `app.py` | ~720 lines | Flask entry point. Routes, SSE stream, session management, city detection, geofence loading |
| `groq_processor.py` | ~420 lines | AI data cleaning, JSON repair, area matching, caching |
| `indolj_importer.py` | ~953 lines | Portal auth, zone fetching, 3-phase sync, HTML parsing |
| `area_mapping.json` | 830 KB | Master area database — city → area name → area ID |
| `branch_city_mapping.json` | <1 KB | Auto-updated cache mapping branch IDs to city IDs |
| `requirements.txt` | <1 KB | Pinned Python package versions |
| `.env` | <1 KB | Secret API keys — **never commit to git** |
| `.env.example` | <1 KB | Template with placeholder values — safe to commit |
| `.gitignore` | <1 KB | Rules for files to exclude from git |
| `README.md` | ~5 KB | Project overview, quick start, tech stack |

### `static/css/style.css` (913 lines)

| Section | Lines | Description |
|---|---|---|
| Design Tokens | 1–36 | CSS custom properties for colors, fonts, radii |
| Reset & Base | 38–57 | Box model reset, body styles |
| Animated Background | 59–112 | Floating mesh orbs animation |
| App Container | 114–130 | Max-width layout wrapper |
| Hero Section | 132–210 | Icon ring, title, subtitle chips |
| Cards | 212–260 | Glassmorphic card containers |
| Form Fields | 262–330 | Input, label, grid styles |
| Dropzone | 332–420 | File drag-drop zone with states |
| Submit Button | 422–470 | Primary CTA button with loader |
| Phase Transitions | 472–490 | Active/inactive phase animations |
| Stepper | 492–590 | 5-step progress tracker |
| Timer Bar | 592–630 | Elapsed time display |
| Result Hero | 632–700 | Success/error result animation |
| Stats Grid | 702–760 | 6-card metrics display |
| Missing Panel | 762–840 | Collapsible unmatched areas panel |
| Logs Container | 842–880 | Terminal-style action logs |
| Toast | 882–913 | Error notification toast |

### `static/js/main.js` (448 lines)

| Section | Lines | Purpose |
|---|---|---|
| DOM refs | 7–53 | All element selectors |
| State | 55–63 | File selection, SSE connection, timer state |
| Drag & Drop | 65–109 | File drop zone interaction |
| Form Submit | 111–173 | Upload file → open SSE stream |
| SSE Handler | 175–226 | Parse events → update UI |
| Stepper UI | 228–267 | Step state management |
| Timer | 269–312 | Elapsed time tracking |
| Results | 314–392 | Render report, missing areas, logs |
| Reset | 399–421 | Return to form phase |
| Helpers | 423–448 | Phase switching, toast, toggle |

### `templates/index.html` (361 lines)

| Phase | Lines | Description |
|---|---|---|
| `#phase-form` | 27–117 | Credentials form + file upload dropzone |
| `#phase-progress` | 122–241 | 5-step SSE progress tracker + timer |
| `#phase-results` | 246–348 | Stats grid + missing areas + logs |
| Error Toast | 350–355 | Floating notification toast |

---

## Data File Formats

### `area_mapping.json`

```json
{
  "1": {
    "DHA Phase 1": "88",
    "DHA Phase 2": "89",
    "Gulshan-e-Iqbal Block 1": "161"
  },
  "2": {
    "DHA Lahore Phase 1": "201",
    "Gulberg III": "202"
  }
}
```

- **Key** (outer): `city_id` string ("1" = Karachi, "2" = Lahore, etc.)
- **Key** (inner): Area name as it appears on the Indolj portal
- **Value** (inner): Area ID integer (as string)

### `branch_city_mapping.json`

```json
{
  "branches": {
    "40594": { "city_id": "1" },
    "45941": { "city_id": "3" },
    "46235": { "city_id": "51" }
  }
}
```

- **Key**: `branch_id` (Indolj branch identifier)
- **Value**: Object with `city_id` string

This file is automatically updated whenever the app detects a new branch ID via the portal. You can also manually add entries here to skip the portal lookup.

---

## What NOT to Modify

| File | Reason |
|---|---|
| `area_mapping.json` | Changes here affect all area matching. Only update if Indolj adds/changes areas. |
| `.env` | Contains live API credentials. Use `.env.example` as reference. |
| `static/css/style.css` (tokens) | Changing CSS variables affects the entire UI theme |
