# API Reference

## Base URL

```
http://localhost:5000
```

---

## Endpoints

### `POST /api/upload-file`

Upload a file and credentials. Returns a session ID used to open the SSE stream.

#### Request

`Content-Type: multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `username` | string | ✅ | Indolj portal username |
| `password` | string | ✅ | Indolj portal password |
| `merchant_id` | string | ✅ | Indolj merchant ID (found in portal URL) |
| `branch_id` | string | ✅ | Target branch ID to sync zones for |
| `base_url` | string | ❌ | Portal base URL (default: `https://console.indolj.io`) |
| `file` | file | ✅ | CSV, XLSX, XLS, JPG, or PNG file |

#### Response `200 OK`

```json
{
  "session_id": "a1b2c3d4",
  "filename": "delivery_zones.csv"
}
```

#### Response `400 Bad Request`

```json
{
  "error": "Missing required credentials."
}
```

#### Response `500 Internal Server Error`

```json
{
  "error": "Error description"
}
```

---

### `GET /api/process`

Opens an SSE (Server-Sent Events) stream that emits step-by-step progress events.

#### Query Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `session_id` | string | ✅ | Session ID returned by `/api/upload-file` |

#### Response Headers

```
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

#### SSE Event Format

Each event is a JSON object prefixed with `data: ` and followed by two newlines:

```
data: <json>\n\n
```

#### Step Progress Events (Steps 1–5)

```json
{
  "step": 1,
  "status": "active",
  "title": "Reading & Parsing File",
  "detail": "Extracting data from zones.csv..."
}
```

```json
{
  "step": 1,
  "status": "done",
  "title": "Reading & Parsing File",
  "detail": "Found 47 data row(s) in zones.csv"
}
```

| Field | Values | Description |
|---|---|---|
| `step` | `1` to `5` | Current pipeline step number |
| `status` | `"active"` \| `"done"` \| `"error"` | Step state |
| `title` | string | Step display name |
| `detail` | string | Human-readable progress detail |

##### Steps

| Step | Title | Description |
|---|---|---|
| 1 | Reading & Parsing File | File ingestion (CSV/Excel/OCR) |
| 2 | AI Analysis & Cleaning | Gemini AI data cleaning |
| 3 | Matching Areas to Database | City detection + fuzzy matching |
| 4 | Authenticating to Portal | Login to Indolj |
| 5 | Uploading to Indolj Portal | Zone create/update sync |

#### Completion Event

```json
{
  "step": "complete",
  "report": {
    "status": "success",
    "total_zones": 3,
    "created": 1,
    "updated": 2,
    "removed": 0,
    "skipped": 0,
    "failed": 0,
    "moved": 0,
    "deduplicated": 0,
    "city_id": "1",
    "city_label": "Karachi",
    "missing_areas": ["[Zone A] Unknown Area Name (non-geofenced)"],
    "logs": [
      "Starting enhanced import: 3 zone(s) to process.",
      "Found 12 existing zone(s) on portal.",
      "CREATE 'Zone A' — 5 area(s), fee=99",
      "✓ Created 'Zone A'",
      "UPDATE 'Zone B' — added 2 area(s)",
      "✓ Updated 'Zone B'"
    ]
  }
}
```

##### Report Object

| Field | Type | Description |
|---|---|---|
| `status` | `"success"` \| `"error"` | Overall status |
| `total_zones` | integer | Number of zones in input file |
| `created` | integer | New zones created on portal |
| `updated` | integer | Existing zones updated |
| `removed` | integer | Areas removed from wrong zones |
| `skipped` | integer | Zones already up-to-date |
| `failed` | integer | Zones that failed to save |
| `moved` | integer | Areas moved between zones |
| `deduplicated` | integer | Duplicate area conflicts detected |
| `city_id` | string | Detected city ID |
| `city_label` | string | Human-readable city name |
| `missing_areas` | string[] | Areas from CSV not found in area_mapping.json |
| `logs` | string[] | Full action log entries |

#### Error Event

```json
{
  "step": "error",
  "message": "Authentication failed — check username/password."
}
```

---

### `POST /api/upload` *(Legacy)*

Synchronous (non-SSE) version of the full pipeline. Accepts the same fields as `/api/upload-file` + the file in a single multipart request.

> **Note**: This endpoint blocks until complete. Use `/api/upload-file` + `/api/process` (SSE) for the real-time UI experience.

#### Request

Same fields as `/api/upload-file`, all in one request.

#### Response `200 OK`

Same structure as the `report` object in the SSE completion event.

---

### `GET /api/geofence-stats`

Returns statistics about the area database.

#### Response `200 OK`

```json
{
  "total_cities": 9,
  "total_geofence_areas": 10247,
  "cities": {
    "1": {
      "name": "Karachi",
      "greendot_areas_count": 3891,
      "area_ids_sample": ["88", "89", "161", "215"]
    },
    "2": {
      "name": "Lahore",
      "greendot_areas_count": 2847,
      "area_ids_sample": ["201", "202", "203"]
    }
  }
}
```

---

### `GET /api/branch-mapping`

> ⚠️ **Debug endpoint** — restrict access in production.

Returns the current branch-to-city mapping cache.

#### Response `200 OK`

```json
{
  "status": "success",
  "total_branches": 13,
  "branches": {
    "40594": { "city_id": "1" },
    "45941": { "city_id": "3" }
  }
}
```

---

## Error Handling

All endpoints return consistent error objects:

```json
{
  "error": "Human-readable error message"
}
```

| HTTP Code | Meaning |
|---|---|
| `400` | Missing fields, unsupported file type, empty file |
| `500` | Server error (AI failure, portal unreachable, etc.) |

---

## Rate Limits

There are no built-in rate limits on the Flask endpoints. The Gemini AI calls are subject to Google's rate limits (handled internally with retry logic).

For production, add rate limiting via Flask-Limiter:

```python
from flask_limiter import Limiter
limiter = Limiter(app, default_limits=["10 per minute"])
```
