# Configuration Guide

## Environment Variables

All configuration is managed through the `.env` file in the project root.

### Template

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

### Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | ✅ Yes | — | Google Gemini API key. Get one at [aistudio.google.com](https://aistudio.google.com/) |
| `TESSERACT_PATH` | ❌ No | Auto-detect | Full path to `tesseract.exe` (Windows only). Auto-detects common install locations if not set. |

---

## Application Constants

These are defined in `app.py` as `_IndoljConstants` and should only be changed if the Indolj portal changes its API structure.

| Constant | Value | Description |
|---|---|---|
| `PAKISTAN_STATE_ID` | `"2"` | Indolj state ID for Pakistan |
| `PAKISTAN_COUNTRY_ID` | `"166"` | Indolj country ID for Pakistan |
| `DEFAULT_CITY_ID` | `"1"` | Fallback city ID (Karachi) |
| `LOGIN_PATH` | `/merchant/Login` | Portal login URL path |
| `BRANCHES_PATH` | `/merchant/branches` | Branch list endpoint |
| `SHIPPINGRATE_PATH` | `/merchant/shippingrate/{branch_id}` | Zone management page |
| `SAVE_ENDPOINT` | `/admin/ajax?action=saveMerchantAreas&tbl=1` | Zone save API |

---

## Flask Configuration

Set in `app.py`:

| Setting | Value | Description |
|---|---|---|
| `UPLOAD_FOLDER` | `uploads/` | Temporary directory for uploaded files |
| `MAX_CONTENT_LENGTH` | 16 MB | Maximum upload file size |

---

## AI Configuration

Set in `groq_processor.py`:

| Setting | Value | Description |
|---|---|---|
| AI Model | `gemini-2.0-flash-lite` | Gemini model for data cleaning |
| API Base URL | `https://generativelanguage.googleapis.com/v1beta/openai/` | OpenAI-compatible Gemini endpoint |
| Temperature | `0.1` | Low randomness for structured output |
| Max Tokens | `16000` | Maximum AI response length |
| Chunk Size | `60` | Data rows per AI API call |

---

## Retry Configuration

Used in `groq_processor.py` for AI calls:

| Setting | Value | Description |
|---|---|---|
| Max Retries | `4` | Maximum attempts per chunk |
| Retry Delays | `[5, 15, 30, 60]` seconds | Delay between retries (exponential-ish) |
| Inter-chunk Delay | `5` seconds | Pause between AI chunk calls (rate limit safe) |

Used in `indolj_importer.py` for HTTP:

| Setting | Value | Description |
|---|---|---|
| HTTP Retry Total | `3` | urllib3 retry count |
| HTTP Backoff Factor | `1` | Exponential backoff multiplier |
| HTTP Status Codes | `500, 502, 503, 504` | Which HTTP errors trigger retry |
| Request Timeout | `30` seconds | Per-request timeout |

---

## Importer Configuration

Passed to `run_importer()` per request:

| Key | Description |
|---|---|
| `delay_between_zones` | Seconds to wait between zone save operations (default: `0.5s`) |
| `max_retries` | Maximum auth retries (default: `3`) |

---

## City Mapping Configuration

`branch_city_mapping.json` maps branch IDs to city IDs. This file is automatically updated as the system discovers new branches.

```json
{
  "branches": {
    "40594": { "city_id": "1" },
    "45941": { "city_id": "3" }
  }
}
```

To pre-populate this file, use the Indolj portal to find your branch IDs and their corresponding city IDs:

| City | ID |
|---|---|
| Karachi | `1` |
| Lahore | `2` |
| Islamabad | `3` |
| Rawalpindi | `4` |
| Faisalabad | `5` |
| Multan | `6` |
| Peshawar | `7` |
| Quetta | `8` |
| Hyderabad | `9` |

---

## Area Mapping Database

`area_mapping.json` is a 830KB JSON file mapping area names to their Indolj IDs, organized by city:

```json
{
  "1": {
    "DHA Phase 1": "88",
    "DHA Phase 2": "89",
    "Gulshan-e-Iqbal Block 1": "161"
  },
  "2": {
    "DHA Lahore Phase 1": "201"
  }
}
```

**When to update this file**: If new delivery areas are added to the Indolj portal, this file must be updated manually (or via a scraping script) to reflect the new area IDs.

---

## Fuzzy Matching Threshold

In `groq_processor.py`, `match_areas_to_mapping()`:

```python
difflib.get_close_matches(lower_key, valid_keys_lower, n=1, cutoff=0.70)
```

The `cutoff=0.70` means an area name must be at least 70% similar to a known area name to be auto-matched. Reducing this increases match rate but may produce incorrect matches. Increasing it requires more precise spelling.

---

## Selenium Configuration

The Selenium browser automation uses:

```python
options.add_argument("--headless")        # No visible browser window
options.add_argument("--no-sandbox")      # Required for Docker/Linux
options.add_argument("--disable-dev-shm-usage")  # Docker memory fix
```

ChromeDriver is automatically downloaded by `webdriver-manager` to match your installed Chrome version. No manual ChromeDriver setup is required.

---

## Production Environment

For production, set these additional environment variables:

```env
FLASK_ENV=production
FLASK_DEBUG=0
```

See [Deployment.md](Deployment.md) for full production configuration.
