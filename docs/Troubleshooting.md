# Troubleshooting Guide

## Common Issues

---

### 1. App fails to start — `ModuleNotFoundError`

**Symptom**:
```
ModuleNotFoundError: No module named 'flask'
```

**Cause**: Virtual environment not activated or dependencies not installed.

**Fix**:
```bash
# Activate the virtual environment
source venv/bin/activate     # macOS/Linux
venv\Scripts\activate        # Windows

# Re-install dependencies
pip install -r requirements.txt
```

---

### 2. `GEMINI_API_KEY` not found

**Symptom**:
```
openai.AuthenticationError: No API key provided
```
or
```
Error: 401 Unauthorized
```

**Fix**:
1. Make sure `.env` exists (copy from `.env.example`)
2. Check that `GEMINI_API_KEY=your_key_here` is set in `.env`
3. Restart the Flask app after editing `.env`
4. Verify the key is valid at [aistudio.google.com](https://aistudio.google.com/)

---

### 3. AI returns no data (empty JSON)

**Symptom**: Step 2 (AI Analysis) succeeds but 0 areas are found.

**Possible Causes**:
- CSV has no data rows (only a header)
- CSV uses non-standard column names the AI can't understand
- Rate limit hit on Gemini API (should auto-retry)

**Fix**:
1. Open your CSV in a spreadsheet and verify it has data rows below the header
2. Make sure the file isn't empty when saved
3. Check the Flask console for retry messages:
   ```
   Rate limit on chunk 1 attempt 1. Waiting 5s before retry...
   ```
4. If retries still fail, check your Gemini API quota at [console.cloud.google.com](https://console.cloud.google.com/)

---

### 4. Login fails — "Authentication failed"

**Symptom**: Step 4 fails with authentication error.

**Possible Causes**:
- Wrong username or password
- Indolj portal is down or URL changed
- Your IP is blocked by the portal

**Fix**:
1. Test your credentials by logging in manually at [console.indolj.io](https://console.indolj.io)
2. Verify the `base_url` field (should be `https://console.indolj.io`)
3. Check if the portal is accessible from your network
4. If Selenium is needed but Chrome is missing, install Chrome

**Debug**:
Check Flask logs for:
```
Direct login exception: ...
Selenium login failed: ...
```

---

### 5. Selenium / Chrome errors

**Symptom**:
```
selenium.common.exceptions.WebDriverException: Message: 'chromedriver' executable needs to be in PATH
```
or
```
SessionNotCreatedException: Chrome version mismatch
```

**Fix**:
webdriver-manager handles ChromeDriver automatically. If it fails:

```bash
# Update webdriver-manager
pip install --upgrade webdriver-manager

# Or manually place a matching chromedriver in the project root
# and set the path in indolj_importer.py
```

Check Chrome version: `google-chrome --version` or `chromium --version`

---

### 6. 0 areas matched — all unresolved

**Symptom**: Step 3 completes with 0 matched areas and many unresolved.

**Possible Causes**:
- Wrong city detected (areas are in Lahore data but being matched against Karachi)
- Area names in your CSV are completely different from the database
- `area_mapping.json` is outdated

**Fix**:
1. Check the city label shown in Step 3 detail message
2. If wrong city: add your branch ID to `branch_city_mapping.json`:
   ```json
   {
     "branches": {
       "your_branch_id": { "city_id": "2" }
     }
   }
   ```
3. Check area names for typos — fuzzy matching handles minor errors but not completely different names
4. Check `/api/geofence-stats` to see how many areas exist per city

---

### 7. SSE stream disconnects mid-process

**Symptom**: Progress bar freezes, browser connection drops.

**Possible Causes**:
- Proxy/firewall buffering SSE data
- Flask dev server timeout
- Long AI processing time

**Fix**:
1. For Nginx: add `proxy_buffering off;` and `proxy_read_timeout 300s;`
2. For Chrome: SSE connections auto-reconnect — if it doesn't, try a hard refresh
3. For long files (100+ rows): split your CSV into smaller files

---

### 8. Upload file fails — "Unsupported file type"

**Symptom**: Error on file upload about unsupported format.

**Supported formats**: `.csv`, `.xlsx`, `.xls`, `.jpg`, `.jpeg`, `.png`

**Fix**: Convert your file to CSV or Excel format.

---

### 9. Image/OCR upload fails — Tesseract not installed

**Symptom**:
```
Error: Tesseract OCR not installed. Cannot process image files.
```

**Fix**:
- Windows: Download and install from [https://github.com/UB-Mannheim/tesseract/wiki](https://github.com/UB-Mannheim/tesseract/wiki)
- Set `TESSERACT_PATH` in your `.env`:
  ```env
  TESSERACT_PATH=C:\Program Files\Tesseract-OCR\tesseract.exe
  ```
- Linux: `sudo apt-get install tesseract-ocr`

---

### 10. Some zones fail to save — HTTP errors

**Symptom**: Step 5 shows failed zones in the report.

**Possible Causes**:
- Session expired during a long import
- Indolj API rejected the payload (invalid area IDs)
- Network timeout

**Fix**:
1. Check the Action Logs panel for specific error messages
2. Look for `HTTP 403` — session may have expired, try again
3. Look for `HTTP 422` — some area IDs may no longer exist in Indolj
4. Update `area_mapping.json` if area IDs have changed on the portal

---

### 11. Port 5000 already in use

**Symptom**:
```
OSError: [Errno 98] Address already in use
```

**Fix**:
```bash
# Find what's using port 5000
# Windows:
netstat -ano | findstr :5000
taskkill /PID <pid> /F

# Linux/macOS:
lsof -ti:5000 | xargs kill -9

# Or run on a different port:
python app.py  # then edit app.py: app.run(port=5001)
```

---

### 12. Missing areas panel shows nothing after import

**Symptom**: Import completes, some areas unresolved, but the "Areas Not Found" panel is empty.

**Cause**: Areas not matched are only shown if they are in `report["missing_areas"]`. If this list is empty, all areas were matched.

**If you expect unmatched areas to appear**:
Check the Flask console logs for `"unresolved"` count during Step 3. If they were matched but shouldn't be, the fuzzy matching threshold may be too low. Increase `cutoff=0.70` to `cutoff=0.80` in `match_areas_to_mapping()`.

---

## Logging

Enable more verbose logging by editing `app.py`:

```python
logging.basicConfig(level=logging.DEBUG)  # Change INFO to DEBUG
```

Log files can be added by modifying the logging config — see [Configuration.md](Configuration.md).

---

## Getting Help

1. Check the Action Logs panel in the results dashboard
2. Check the Flask console output (terminal where you ran `python app.py`)
3. Use the browser DevTools → Network tab → EventStream to inspect raw SSE events
4. Check `/api/geofence-stats` to verify your area database is loaded correctly
