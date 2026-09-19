# Developer Guide

## Development Setup

```bash
git clone https://github.com/yourname/DeliveryZoneApp.git
cd DeliveryZoneApp

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env
# Fill in your GEMINI_API_KEY in .env

python app.py
```

The app runs in debug mode by default (`app.run(debug=True)`), which enables:
- Auto-reloading on file changes
- Detailed error pages
- Flask debugger

---

## Code Walkthrough

### Entry Point: `app.py`

#### Application Bootstrap

```python
load_dotenv()        # Load .env file into os.environ
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
```

#### Constants (`_IndoljConstants`)

All magic strings for the Indolj portal are centralized here. Do not scatter API paths throughout the codebase.

```python
C = _IndoljConstants()
# Usage: C.LOGIN_PATH, C.SAVE_ENDPOINT, etc.
```

#### Session Management

```python
sessions: dict = {}  # {session_id: {credentials + file_path}}
```

This is an in-memory dict. Session IDs are 8-character UUID fragments. Sessions are consumed (popped) when the SSE stream opens.

> **Note for contributors**: This works for single-process deployment. For multi-worker production, replace with Redis sessions.

#### `resolve_city_id()` — 2-Tier City Detection

```python
city_id, pre_session = resolve_city_id(
    branch_id=sess["branch_id"],
    username=sess["username"],
    password=sess["password"],
    base_url=sess["base_url"],
    branch_city_mapping=branch_city_mapping,
)
```

Returns a pre-authenticated `requests.Session` if Tier 2 (portal) detection was used — this session is reused by the importer to avoid double-login.

#### SSE Generator (`generate()`)

The generator function uses Python's generator protocol to stream events:

```python
def generate():
    yield sse_event(1, "active", "Reading & Parsing File", "...")
    # ... do work ...
    yield sse_event(1, "done", "Reading & Parsing File", "...")
```

The importer thread communicates via shared lists:
```python
progress_events = []           # Thread appends (type, detail) tuples
report_holder   = {"report": None}  # Thread writes final report
error_holder    = {"error": None}   # Thread writes error if any
```

---

### AI Module: `groq_processor.py`

#### `process_data_with_groq(raw_text, mapping_file)` → `list[dict]`

Main function. Splits raw CSV text into 60-row chunks and processes each with the Gemini API.

**Retry Logic**:
```python
max_retries = 4
retry_delays = [5, 15, 30, 60]  # seconds

for attempt in range(max_retries):
    try:
        response = client.chat.completions.create(...)
        structured_data = extract_json_array(response.choices[0].message.content)
        if structured_data:
            break  # Success
        # Empty response → retry
    except Exception as e:
        if "429" in str(e):  # Rate limit → wait and retry
            time.sleep(retry_delays[attempt])
        else:
            raise
```

#### `extract_json_array(text)` → `list`

4-level JSON repair for AI responses:
1. Direct `json.loads()` — fast path
2. Strip markdown fences (` ```json `)
3. Find `[...]` brackets manually
4. Truncation repair — find last `}` and append `]`

#### `_get_cached_area_mapping(mapping_file_path)` → `dict`

Module-level singleton cache. The 830KB JSON file is loaded once and kept in memory. Subsequent calls return the cached version instantly.

#### `match_areas_to_mapping(structured_data, mapping_file, city_id)` → `(dict, list)`

3-tier fuzzy matching:
```python
# Tier 1: Exact string match
if area_name in mapping:
    ...

# Tier 2: Case-insensitive
if area_name.lower() in lower_mapping:
    ...

# Tier 3: difflib fuzzy match (70% similarity threshold)
matches = difflib.get_close_matches(area_name.lower(), valid_keys, n=1, cutoff=0.70)
```

Returns `(grouped_zones, unmatched_names)`.

---

### Importer Module: `indolj_importer.py`

#### `ZoneHTMLParser(HTMLParser)`

Parses the Indolj shippingrate HTML page to extract all existing zones and their settings. Uses Python's built-in `html.parser` — no external dependency.

Key patterns it looks for:
- `<input id="zone-name-{i}">` → zone name
- `<input name="zones[{i}][zone_id]">` → zone ID
- `<input name="zones[{i}][fee]">` → delivery fee
- `<select id="area_{i}">` → area IDs (selected options)

#### `AuthManager`

```python
auth = AuthManager(config)
session = auth.get_session()  # Returns authenticated requests.Session
```

Login flow:
1. `_requests_login()`: GET login page → extract CSRF → POST credentials → probe auth
2. `_selenium_login()`: Fallback for JS-rendered or anti-bot-protected login pages

#### `ExistingZoneFetcher`

```python
fetcher = ExistingZoneFetcher(config)
existing_zones = fetcher.fetch(session)  # Dict of {zone_name: zone_data}
```

Fetch flow:
1. `_fetch_via_requests()`: HTML parse with `ZoneHTMLParser`
2. If "Load More" detected or 0 zones → `_fetch_via_selenium()`: headless Chrome + repeated button clicks

#### `IndoljAPIClient.save_zone()`

```python
payload = {
    "merchant_id": ...,
    "branch_id": ...,
    "zones[0][zone_name]": ...,
    "zones[0][fee]": ...,
    "zones[0][areas][]": [area_id_1, area_id_2, ...],
    ...
}
r = self.session.post(self.save_url, data=payload, headers={"X-Requested-With": "XMLHttpRequest"})
```

The API expects `X-Requested-With: XMLHttpRequest` to identify AJAX requests.

#### `run_importer()` — 3-Phase Sync

**Phase 1 — Deduplication Detection**:
Find all areas in the input that already exist in the wrong zone on the portal.

**Phase 2 — Remove from Wrong Zones**:
For each conflict, save the old zone without the duplicate area IDs.

**Phase 3 — Create/Update Correct Zones**:
For each zone in the input:
- If zone exists: merge area IDs + save (update)
- If zone is new: save with all area IDs (create)

---

### Frontend: `static/js/main.js`

The frontend is a vanilla JS single-page app with three phases:

```
Phase 1 (form)    → Phase 2 (progress) → Phase 3 (results)
```

**SSE Connection**:
```javascript
const eventSource = new EventSource(`/api/process?session_id=${sessionId}`);
eventSource.onmessage = (evt) => {
    const data = JSON.parse(evt.data);
    if (typeof data.step === 'number') updateStep(data.step, data.status, data.detail);
    if (data.step === 'complete')       showResults(data.report);
    if (data.step === 'error')          showGlobalError(data.message);
};
```

**Timer**: Tracks elapsed time and estimates remaining time based on hard-coded per-step estimates.

---

## Making Changes

### Adding a New AI Rule

Add to the `prompt` string in `process_data_with_groq()`:

```python
prompt = f"""...
RULE 7 — Your new rule:
  Description of what the AI should do.
  Example: "old format" → "new format"
...
"""
```

### Adding a New City

1. Add to `CITY_NAMES` in `app.py`:
   ```python
   CITY_NAMES = {
       "1": "Karachi", ...,
       "10": "Your City",
   }
   ```
2. Add area data to `area_mapping.json` under key `"10"`:
   ```json
   {
     "10": {
       "Area Name 1": "area_id_1",
       "Area Name 2": "area_id_2"
     }
   }
   ```

### Adding a New File Format

In `process_stream()` and `upload_legacy()` in `app.py`:

```python
elif file_ext == '.pdf':
    import pdfplumber
    with pdfplumber.open(file_path) as pdf:
        raw_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
```

### Changing the AI Model

In `groq_processor.py`, change the `model` parameter:

```python
model="gemini-2.0-flash"  # More powerful, slower
# or
model="gemini-2.0-flash-lite"  # Current default — fast, cost-effective
```

### Adding a New SSE Step

1. Add a new `<div class="step" data-step="6">` in `templates/index.html`
2. Yield a step-6 event in the `generate()` function in `app.py`
3. Add time estimate in `STEP_EST` in `static/js/main.js`

---

## Code Style

- **Python**: PEP 8, 4-space indentation, f-strings for formatting
- **Type hints**: All new functions must have parameter and return type annotations
- **Docstrings**: One-line summary + longer description for non-trivial functions
- **JavaScript**: ES6+, `const`/`let`, arrow functions, IIFE wrapper for encapsulation
- **CSS**: Custom properties for all colors/sizes, BEM-like class naming

---

## Debugging Tips

### Debug SSE Events in Browser

Open DevTools → Network tab → click on the `/api/process` request → EventStream tab.

### Debug Selenium Login

Set `--headless` mode to visible to watch the browser:
```python
# Temporarily remove this line in _selenium_login():
options.add_argument("--headless")
```

### Debug Area Matching

Add a temporary call after `match_areas_to_mapping()`:
```python
for name in unmatched:
    print(f"UNMATCHED: {name!r}")
```

### Check Cached Mapping

```python
# In a Python shell:
from groq_processor import _get_cached_area_mapping
mapping = _get_cached_area_mapping("area_mapping.json")
print(list(mapping["1"].items())[:5])
```
