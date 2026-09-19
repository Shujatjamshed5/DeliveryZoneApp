# Workflow — End-to-End Data Flow

This document walks through a complete import session from start to finish.

---

## Overview

```
User opens http://localhost:5000
            │
            ▼
     Phase 1: Form
     → Enter credentials + upload file
            │
            ▼
     Phase 2: Progress (5 Steps)
     → Real-time SSE updates
            │
            ▼
     Phase 3: Results
     → Stats + missing areas + logs
```

---

## Step 0 — User Opens the App

Flask serves `templates/index.html`. The page loads:
- The **Form Phase** is visible (credentials + file upload)
- `static/css/style.css` renders the dark glassmorphic theme
- `static/js/main.js` initializes all event listeners

---

## Step A — File Upload (Client → Server)

1. User fills credentials and drops/selects a CSV file
2. User clicks **"Start Processing"**
3. JavaScript calls `POST /api/upload-file` with `multipart/form-data`
4. Flask saves the file to `uploads/` with `secure_filename()`
5. Flask creates a session entry in `sessions = {}`:
   ```python
   sessions["a1b2c3d4"] = {
       "file_path": "uploads/delivery_zones.csv",
       "username": "pizzahut_pk",
       "password": "...",
       "merchant_id": "200274",
       "branch_id": "40594",
       "base_url": "https://console.indolj.io"
   }
   ```
6. Server responds with `{"session_id": "a1b2c3d4", "filename": "delivery_zones.csv"}`
7. JavaScript switches to **Progress Phase** and opens SSE connection

---

## Step 1 — File Reading & Parsing

**Server**: `generate()` in `process_stream()`

```
SSE → data: {"step": 1, "status": "active", "title": "Reading & Parsing File", ...}
```

- **CSV/Excel**: `pandas.read_csv()` or `pandas.read_excel()` → convert to CSV string
- **Image**: `pytesseract.image_to_string(PIL.Image.open(file_path))`

Result: `raw_text` — a multi-line string with header + data rows.

```
SSE → data: {"step": 1, "status": "done", "detail": "Found 47 data row(s) in delivery_zones.csv"}
```

---

## Step 2 — AI Analysis & Cleaning

**Server**: `process_data_with_groq(raw_text, area_mapping.json)`

```
SSE → data: {"step": 2, "status": "active", "title": "AI Analysis & Cleaning", ...}
```

**What happens**:

1. Split `raw_text` into 60-row chunks (preserving the header per chunk)
2. For each chunk, send to Gemini AI with a strict 6-rule prompt:
   - Use NEW price (not OLD) as delivery charge
   - Zone Name = column value OR `"Zone_{charge}"`
   - Fix spelling errors in area names
   - Expand grouped entries (`"North Nazimabad all block"` → 14 rows)
   - Default missing fields to `"0"`
   - Output raw JSON only

3. Parse the AI response with `extract_json_array()` — 4 repair strategies
4. Merge all chunk results
5. Deduplicate by `(area_name.lower(), zone_name.lower())`

**Result**: `structured_data` — a list of clean, structured records:

```json
[
  {"Zone Name": "Zone A", "Area Name": "DHA Phase 1", "Delivery Charge": "99", ...},
  {"Zone Name": "Zone A", "Area Name": "DHA Phase 2", "Delivery Charge": "99", ...},
  {"Zone Name": "Zone B", "Area Name": "Gulshan Block 1", "Delivery Charge": "149", ...}
]
```

```
SSE → data: {"step": 2, "status": "done", "detail": "AI found 52 area(s) → 3 zone(s) by delivery charge"}
```

---

## Step 3 — City Detection & Area Matching

**Server**: `resolve_city_id()` + `match_areas_to_mapping()`

```
SSE → data: {"step": 3, "status": "active", "title": "Matching Areas to Database", ...}
```

### 3a — City Detection

`resolve_city_id(branch_id="40594", ...)`

**Tier 1**: Check `branch_city_mapping.json`:
```json
{"branches": {"40594": {"city_id": "1"}}}  → city_id = "1" (Karachi)
```
→ Takes ~0ms, no network call.

**Tier 2** (only if branch not in local file):
- Login to portal
- Scrape `/merchant/branches` JSON or HTML
- Detect `city_id` from branch data
- Auto-save: `branch_city_mapping["40594"] = {"city_id": "1"}`

### 3b — Area Matching

`match_areas_to_mapping(structured_data, "area_mapping.json", city_id="1")`

For each area name in `structured_data`:

```
"DHA Phase 1"
    → Exact match in area_mapping["1"]["DHA Phase 1"] = "88" ✓ (matched)

"DHA Phaze 6"
    → No exact match
    → Case-insensitive: no match
    → Fuzzy: "dha phaze 6" ≈ "dha phase 6" (90% similar) → area_id = "93" ✓ (fuzzy matched)

"Unknown Village XYZ"
    → No exact match
    → No case-insensitive match
    → No fuzzy match (< 70% similar to anything)
    → Added to unmatched_names list ✗
```

Result: `grouped_zones` dict organizing areas into zones:

```python
grouped_zones = {
    "Zone A": {
        "Zone Name": "Zone A",
        "area_ids": ["88", "89", "93"],
        "Delivery Charge": "99",
        "missing_areas": ["Unknown Village XYZ"],
        ...
    }
}
```

```
SSE → data: {"step": 3, "status": "done", "detail": "Karachi: Matched 51/52 areas across 3 zone(s). 1 unresolved."}
```

---

## Step 4 — Authentication

**Server (background thread)**: `AuthManager.get_session()`

```
SSE → data: {"step": 4, "status": "active", "title": "Authenticating to Portal", ...}
```

**(If `pre_session` already exists from city detection → skip re-login, reuse session)**

Otherwise:
1. `_requests_login()`: GET login page → extract CSRF token → POST credentials
2. `_probe_auth()`: GET `/merchant/branches` → expect HTTP 200 (not a redirect to login)
3. If that fails: `_selenium_login()` → headless Chrome → login → extract cookies

```
SSE → data: {"step": 4, "status": "done", "detail": "Login successful!"}
```

---

## Step 5 — Portal Sync

**Server (background thread)**: `run_importer()`

```
SSE → data: {"step": 5, "status": "active", "title": "Uploading to Indolj Portal", ...}
```

### 5a — Fetch Existing Zones

`ExistingZoneFetcher.fetch(session)`

- GET `/merchant/shippingrate/{branch_id}`
- Parse with `ZoneHTMLParser` → extract all zones, their area IDs, fees, settings
- If "Load More" button found → use Selenium to click it until all zones load
- Result: `existing_zones = {"Zone A": {"zone_id": "123", "area_ids": [...], "fee": "80"}, ...}`

### 5b — Phase 1: Deduplication Detection

Scan all target area IDs against all existing zones. Log any conflicts found (area in wrong zone).

### 5c — Phase 2: Remove Wrong-Zone Areas

For each conflict: save the conflicting zone without the duplicated area IDs.

```python
api.save_zone(old_zone_info, updated_ids_without_duplicates, zone_id="123")
```

### 5d — Phase 3: Create / Update Zones

For each zone in `grouped_zones`:

**If zone already exists on portal**:
- Compare area IDs and fee
- If unchanged → skip (log: `SKIP 'Zone A' — already up-to-date`)
- If changed → merge area IDs (existing ∪ new) → save
  ```
  api.save_zone(zone_data, merged_area_ids, zone_id="123")
  ```

**If zone is new**:
- Create with all area IDs
  ```
  api.save_zone(zone_data, area_ids, zone_id="")  ← empty zone_id = create new
  ```

The API call sends a POST to `/admin/ajax?action=saveMerchantAreas&tbl=1` with `X-Requested-With: XMLHttpRequest`.

Between each zone, wait `delay_between_zones = 0.5s` (rate limit protection).

```
SSE → data: {"step": 5, "status": "active", "detail": "Processing 'Zone A' (1/3)..."}
SSE → data: {"step": 5, "status": "active", "detail": "Processing 'Zone B' (2/3)..."}
SSE → data: {"step": 5, "status": "active", "detail": "Processing 'Zone C' (3/3)..."}
SSE → data: {"step": 5, "status": "done",   "detail": "Done! Created=1, Updated=2, Removed=0, Failed=0"}
```

---

## Final Report

```
SSE → data: {
  "step": "complete",
  "report": {
    "status": "success",
    "total_zones": 3,
    "created": 1,
    "updated": 2,
    "removed": 0,
    "skipped": 0,
    "failed": 0,
    "deduplicated": 0,
    "city_id": "1",
    "city_label": "Karachi",
    "missing_areas": ["[Zone C] Unknown Village XYZ (non-geofenced)"],
    "logs": ["...", "...", "..."]
  }
}
```

JavaScript switches to **Results Phase**, renders the stats grid, missing areas panel, and color-coded action logs.

---

## Cleanup

After a successful or failed run:
- The uploaded file is deleted: `os.remove(file_path)`
- The session entry is consumed (popped) at the start of `process_stream()`
- The SSE connection closes when the client receives the `complete` or `error` event

---

## Error Recovery

At any step, if an exception is raised:

```
SSE → data: {"step": "error", "message": "Authentication failed — check username/password."}
```

JavaScript shows the error state in the Results Phase with the error message.

The user can click **"Sync Another File"** to reset and try again.
