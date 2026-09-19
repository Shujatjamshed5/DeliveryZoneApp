import json
import logging
import os
import tempfile
import threading
import time
import traceback
import uuid
from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    stream_with_context,
)
from indolj_importer import AuthManager, run_importer
import pandas as pd
from werkzeug.utils import secure_filename

from groq_processor import match_areas_to_mapping, process_data_with_groq

try:
  import pytesseract
  from PIL import Image

  if os.name == "nt":
    tesseract_path = os.environ.get("TESSERACT_PATH", "")
    if not tesseract_path:
      # Auto-detect common installation locations
      tesseract_paths = [
          r"C:\Program Files\Tesseract-OCR\tesseract.exe",
          r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
          r"C:\Users\{}\AppData\Local\Tesseract-OCR\tesseract.exe".format(
              os.environ.get("USERNAME", "")
          ),
      ]
      for path in tesseract_paths:
        if os.path.exists(path):
          tesseract_path = path
          break
    if tesseract_path and os.path.exists(tesseract_path):
      pytesseract.pytesseract.tesseract_cmd = tesseract_path
  TESSERACT_AVAILABLE = True
except ImportError:
  TESSERACT_AVAILABLE = False

load_dotenv()

# ==============================================================================
# CONSTANTS
# ==============================================================================


class _IndoljConstants:
  """Static constants for the Indolj portal. Centralizes magic strings."""

  PAKISTAN_STATE_ID: str = "2"
  PAKISTAN_COUNTRY_ID: str = "166"
  DEFAULT_CITY_ID: str = "1"  # Karachi
  LOGIN_PATH: str = "/merchant/Login"
  BRANCHES_PATH: str = "/merchant/branches"
  SHIPPINGRATE_PATH: str = "/merchant/shippingrate/{branch_id}"
  # The branch's Areas page — also where the 'chosen.js' city dropdown widget
  # renders the branch's real city NAME as plain text. This is now the
  # primary, most reliable way to identify a branch's city (see
  # detect_branch_city_name in indolj_importer.py) — no numeric city_id
  # guessing/translation needed.
  BRANCHAREAS_PATH: str = "/merchant/branchareas/{branch_id}"
  SAVE_ENDPOINT: str = "/admin/ajax?action=saveMerchantAreas&tbl=1"


C = _IndoljConstants()

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = os.path.join(tempfile.gettempdir(), "uploads")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB

try:
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
except OSError:
    pass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAPPING_FILE = "area_mapping.json"


def _drop_zone_id_column(df):
  """Drop any 'ZoneID' / 'Zone ID' / 'Zone_ID' column from the uploaded file.

  The excel/CSV's own ZoneID (portal's internal id for whatever zone the areas
  were exported from) should never be used by the AI to group/name zones —
  zones are grouped by Delivery Charge / Zone Name per the existing rules.
  Dropping the column outright is more reliable than asking the AI to
  "ignore" it, since it never even reaches the prompt this way.
  """
  cols_to_drop = [
      c for c in df.columns
      if str(c).strip().lower().replace(" ", "").replace("_", "") == "zoneid"
  ]
  if cols_to_drop:
    logger.info(f"Dropping ZoneID column(s) from input: {cols_to_drop}")
    df = df.drop(columns=cols_to_drop)
  return df

sessions = {}

CITY_NAMES = {
    "1": "Karachi",
    "3": "Lahore",
    "4": "Islamabad",
    # Legacy numeric city_id → name table. No longer used for area matching
    # (the user now selects the branch's city by name directly, validated
    # against area_mapping.json via validate_city_name() below). Kept only
    # for the cosmetic /api/geofence-stats debug endpoint.
}


def validate_city_name(city_name: str, mapping_file: str = MAPPING_FILE) -> str:
  """Validate a user-provided city name against area_mapping.json's keys.

  This REPLACES the old Selenium-based auto-detection that used to run here
  (detect_branch_city / detect_branch_city_name in indolj_importer.py, now
  removed). The user selects the branch's city directly in the UI, which is
  faster and removes the DOM-timing flakiness Selenium kept hitting for
  some branches (e.g. 46025).

  Case-insensitive (area_mapping.json has "islamabad" lowercase while other
  cities are capitalized). Returns the mapping's canonical key (correct
  case) so downstream code always sees a key that exists in the file.

  Raises ValueError with a clear message if the city isn't in the mapping.
  """
  if not city_name or not city_name.strip():
    raise ValueError("Branch city is required but was not provided.")

  city_name = city_name.strip()

  if not os.path.exists(mapping_file):
    # Nothing to validate against — trust the caller's value as-is.
    return city_name

  with open(mapping_file, "r", encoding="utf-8") as f:
    full_mapping = json.load(f)

  key_lookup = {str(k).strip().lower(): k for k in full_mapping.keys()}
  canonical = key_lookup.get(city_name.lower())

  if not canonical:
    available = ", ".join(sorted(full_mapping.keys()))
    raise ValueError(
        f"'{city_name}' was not found in area_mapping.json. Available "
        f"cities: {available}"
    )

  return canonical


def _build_importer_config(
    username: str,
    password: str,
    merchant_id: str,
    branch_id: str,
    base_url: str,
    city_name: str = None,
    city_id: str = None,
) -> dict:
  """Build the config dict passed to run_importer. Single source of truth.

  city_name is the user-selected identifier (validated via validate_city_name).
  city_id is kept only for the legacy/cosmetic build_area_id_to_name_map
  param (which scans all cities regardless of this value — it doesn't filter
  by it) and for backward compatibility with any caller still on the old
  numeric-id flow.
  """
  return {
      "username": username,
      "password": password,
      "merchant_id": merchant_id,
      "branch_id": branch_id,
      "city_id": city_id or "1",
      "city_name": city_name,
      "state_id": C.PAKISTAN_STATE_ID,
      "country_id": C.PAKISTAN_COUNTRY_ID,
      "base_url": base_url,
      "login_path": C.LOGIN_PATH,
      "branches_path": C.BRANCHES_PATH,
      "shippingrate_path": C.SHIPPINGRATE_PATH,
      "branchareas_path": C.BRANCHAREAS_PATH,
      "save_endpoint": C.SAVE_ENDPOINT,
      "mapping_path": MAPPING_FILE,
      "request_timeout": 30,
      "delay_between_zones": 0.5,
      "max_retries": 3,
  }


# ==============================================================================
# ✅ BRANCH-CITY MAPPING LOADER — NO NETWORK NEEDED
# ==============================================================================
def load_branch_city_mapping(mapping_file: str = "branch_city_mapping.json") -> dict:
  """Load branch-to-city mapping from local JSON file.

  File format:
  {
    "branches": {
      "1": {"city_id": "1"},
      "2": {"city_id": "2"},
      ...
    }
  }

  Returns: {branch_id: {city_id: "1"}} or empty dict if file not found
  """
  try:
    if not os.path.exists(mapping_file):
      logger.warning(f"Branch mapping not found: {mapping_file}")
      return {}

    with open(mapping_file, "r", encoding="utf-8") as f:
      data = json.load(f)

    branches = data.get("branches", {})
    logger.info(f"✓ Loaded branch mapping for {len(branches)} branch(es)")
    return branches

  except Exception as e:
    logger.error(f"Failed to load branch mapping: {e}")
    return {}


# ==============================================================================
# GEOFENCE DATA LOADER — greendot areas ko area_mapping.json se load karo
# ==============================================================================
def load_geofence_data(mapping_file: str = MAPPING_FILE) -> dict:
  """area_mapping.json se valid (geofenced) area_ids load karo.

  area_mapping.json format:
  {
    "1": {
      "DHA Phase 1": "101",
      "DHA Phase 2": "102",
      ...
    },
    "2": {...}
  }

  Returns: {city_id: set(area_ids)} where area_ids exist in mapping
  """
  try:
    if not os.path.exists(mapping_file):
      logger.warning(
          f"Geofence file not found: {mapping_file}. Proceeding without"
          " validation."
      )
      return {}

    with open(mapping_file, "r", encoding="utf-8") as f:
      area_mapping = json.load(f)

    geofence_areas = {}

    for city_id, city_data in area_mapping.items():
      geofence_ids = set()

      if isinstance(city_data, dict):
        if "areas" in city_data:
          for area in city_data.get("areas", []):
            area_id = str(area.get("area_id"))
            if area_id:
              geofence_ids.add(area_id)
        else:
          for area_name, area_id in city_data.items():
            if area_id and not area_name.startswith("_"):
              geofence_ids.add(str(area_id))

      geofence_areas[str(city_id)] = geofence_ids
      logger.info(
          f"Geofence: City {city_id} → {len(geofence_ids)} valid areas loaded"
          " from mapping"
      )

    total_geofence = sum(len(aids) for aids in geofence_areas.values())
    logger.info(
        f"Total geofence areas: {total_geofence} across {len(geofence_areas)}"
        " cities"
    )

    return geofence_areas

  except json.JSONDecodeError as e:
    logger.error(f"Invalid JSON in {mapping_file}: {e}")
    return {}

  except Exception as e:
    logger.error(f"Failed to load geofence data: {traceback.format_exc()}")
    return {}


@app.route("/")
def index():
  return render_template("index.html")


# ==============================================================================
# STEP 1 — File + Credentials Upload
# ==============================================================================
@app.route("/api/upload-file", methods=["POST"])
def upload_file() -> tuple:
  """File aur credentials accept karo, session mein store karo."""
  try:
    username = request.form.get("username")
    password = request.form.get("password")
    merchant_id = request.form.get("merchant_id")
    branch_id = request.form.get("branch_id")
    city_name = request.form.get("city_name")
    base_url = request.form.get("base_url", "https://console.indolj.io")

    if not all([username, password, merchant_id, branch_id, city_name]):
      return jsonify({"error": "Missing required credentials (including branch city)."}), 400

    try:
      city_name = validate_city_name(city_name)
    except ValueError as e:
      return jsonify({"error": str(e)}), 400

    if "file" not in request.files:
      return jsonify({"error": "No file uploaded."}), 400

    file = request.files["file"]
    if file.filename == "":
      return jsonify({"error": "No file selected."}), 400

    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(file_path)

    session_id = str(uuid.uuid4())[:8]
    sessions[session_id] = {
        "file_path": file_path,
        "filename": filename,
        "username": username,
        "password": password,
        "merchant_id": merchant_id,
        "branch_id": branch_id,
        "city_name": city_name,
        "base_url": base_url,
    }

    return jsonify({"session_id": session_id, "filename": filename})

  except Exception as e:
    logger.error(f"Upload error: {traceback.format_exc()}")
    return jsonify({"error": str(e)}), 500


# ==============================================================================
# STEP 2 — SSE Process Stream
# ==============================================================================
@app.route("/api/process")
def process_stream():
  """SSE endpoint — step-by-step progress stream."""
  session_id = request.args.get("session_id")
  if not session_id or session_id not in sessions:

    def error_stream():
      yield f"data: {json.dumps({'step': 'error', 'message': 'Invalid session ID'})}\n\n"

    return Response(error_stream(), mimetype="text/event-stream")

  sess = sessions.pop(session_id)

  def generate():
    try:
      file_path = sess["file_path"]
      filename = sess["filename"]
      file_ext = os.path.splitext(filename)[1].lower()

      # ── STEP 1: File Read ──────────────────────────────────────────
      yield sse_event(
          1,
          "active",
          "Reading & Parsing File",
          f"Extracting data from {filename}...",
      )

      raw_text = ""
      if file_ext == ".csv":
        df = pd.read_csv(file_path, index_col=False)  # index_col=False guards against trailing-comma column shift
        df = _drop_zone_id_column(df)
        raw_text = df.to_csv(index=False)

      elif file_ext in [".xls", ".xlsx"]:
        df = pd.read_excel(file_path)
        df = _drop_zone_id_column(df)
        raw_text = df.to_csv(index=False)

      elif file_ext in [".jpg", ".jpeg", ".png"]:
        if not TESSERACT_AVAILABLE:
          yield sse_event(
              "error",
              message=(
                  "Tesseract OCR not installed. Cannot process image files."
              ),
          )
          return
        img = Image.open(file_path)
        raw_text = pytesseract.image_to_string(img)

      else:
        yield sse_event(
            "error",
            message=(
                f"Unsupported file type: {file_ext}. Upload CSV, Excel, JPG,"
                " or PNG."
            ),
        )
        return

      if not raw_text.strip():
        yield sse_event(
            "error", message="Could not extract any data from the file."
        )
        return

      lines = [l for l in raw_text.split("\n") if l.strip()]
      row_count = max(0, len(lines) - 1)

      yield sse_event(
          1,
          "done",
          "Reading & Parsing File",
          f"Found {row_count} data row(s) in {filename}",
      )

      # ── STEP 3: City (user-provided — no Selenium detection needed) ──
      city_name = sess["city_name"]
      city_label = city_name
      city_confidence = "high"  # user-selected, not a guess
      pre_session = None

      yield sse_event(
          3,
          "active",
          "Matching Areas to Database",
          f"Using branch city: {city_label}",
      )

      # ── STEP 2: Groq AI ────────────────────────────────────────────
      yield sse_event(
          2,
          "active",
          "AI Analysis & Cleaning",
          "Sending data to Groq AI for cleaning and zone grouping...",
      )

      structured_data = process_data_with_groq(raw_text, MAPPING_FILE)

      if not structured_data:
        yield sse_event(
            "error",
            message=(
                "Groq AI returned no structured data. Check your input file"
                " format."
            ),
        )
        return

      unique_zones = len(set(r.get("Zone Name", "") for r in structured_data))
      yield sse_event(
          2,
          "done",
          "AI Analysis & Cleaning",
          f"AI found {len(structured_data)} area(s) → {unique_zones} zone(s) by"
          " delivery charge",
      )

      # ── STEP 3 Continued: City-Restricted Area Matching ─────────────────────
      yield sse_event(
          3,
          "active",
          "Matching Areas to Database",
          f"City: {city_label}. Fuzzy matching"
          f" {len(structured_data)} areas strictly within {city_label}...",
      )

      # ✅ Pass city_name (the reliable identifier — read directly off the
      # branch's Areas page) to match_areas_to_mapping. area_mapping.json is
      # keyed by city NAME, so this is a direct match, no id translation.
      grouped_zones, unmatched = match_areas_to_mapping(
          structured_data, MAPPING_FILE, city_name=city_label
      )

      total_matched = sum(
          len(z.get("area_ids", [])) for z in grouped_zones.values()
      )
      unmatched_count = len(unmatched)

      yield sse_event(
          3,
          "done",
          "Matching Areas to Database",
          f"{city_label}: Matched {total_matched}/{len(structured_data)} areas"
          f" across {len(grouped_zones)} zone(s). {unmatched_count} unresolved.",
      )

      # ✅ Areas the AI extracted but that don't exist anywhere in
      # area_mapping.json for this city — these never even make it into the
      # import (unlike the "non-geofenced" ones caught later inside
      # run_importer, which DO exist in the mapping but lack a portal
      # geofence). Keep them, with zone context, so the user can see exactly
      # which areas need to be added to the database.
      db_unresolved_lines = []
      db_unresolved_flat = []
      for zname, zdata in grouped_zones.items():
        for area in zdata.get("missing_areas", []):
          db_unresolved_lines.append(
              f"UNRESOLVED: '{area}' not found in area database for zone"
              f" '{zname}' — add it manually"
          )
          db_unresolved_flat.append(f"[{zname}] {area} (not in database)")

      # ── STEP 4 & 5: Auth + Upload (thread) ────────────────────────
      yield sse_event(
          4,
          "active",
          "Authenticating to Portal",
          f"Preparing portal connection as {sess['username']}...",
      )

      config = _build_importer_config(
          username=sess["username"],
          password=sess["password"],
          merchant_id=sess["merchant_id"],
          branch_id=sess["branch_id"],
          city_name=city_name,
          base_url=sess["base_url"],
      )

      report_holder = {"report": None}
      error_holder = {"error": None}
      progress_events = []

      def importer_progress(event_type, detail):
        progress_events.append((event_type, detail))

      geofence_areas = load_geofence_data(MAPPING_FILE)

      def run_import_thread():
        try:
          report_holder["report"] = run_importer(
              config,
              grouped_zones,
              progress_callback=importer_progress,
              pre_session=pre_session,
              geofence_areas=geofence_areas,
          )
        except Exception as e:
          error_holder["error"] = str(e)
          logger.error(f"Import thread error: {traceback.format_exc()}")

      thread = threading.Thread(target=run_import_thread)
      thread.start()

      auth_done_flag = False
      upload_start_flag = False

      while thread.is_alive() or progress_events:
        while progress_events:
          evt_type, detail = progress_events.pop(0)

          if evt_type == "auth_start":
            pass

          elif evt_type == "auth_done":
            yield sse_event(4, "done", "Authenticating to Portal", detail)
            auth_done_flag = True

          elif evt_type == "upload_start":
            yield sse_event(
                5, "active", "Uploading to Indolj Portal", detail
            )
            upload_start_flag = True

          elif evt_type == "upload_progress":
            yield sse_event(
                5, "active", "Uploading to Indolj Portal", detail
            )

          elif evt_type == "upload_done":
            yield sse_event(5, "done", "Uploading to Indolj Portal", detail)

        time.sleep(0.3)

      thread.join()

      if not auth_done_flag:
        yield sse_event(
            4, "done", "Authenticating to Portal", "Authentication completed."
        )
      if not upload_start_flag:
        yield sse_event(
            5, "active", "Uploading to Indolj Portal", "Processing zones..."
        )
        yield sse_event(
            5, "done", "Uploading to Indolj Portal", "All zones processed!"
        )

      if error_holder["error"]:
        yield sse_event("error", message=error_holder["error"])
        return

      report = report_holder["report"]

      if report and isinstance(report.get("missing_areas"), dict):
        flat_missing = []
        for zone_name, areas in report["missing_areas"].items():
          for area in areas:
            flat_missing.append(f"[{zone_name}] {area} (non-geofenced)")
        report["missing_areas"] = flat_missing

      if report:
        # Merge in the "not found in database at all" areas caught during
        # matching (before import even started) alongside the
        # "non-geofenced" ones caught during import, so the user sees a
        # single, complete list of everything they need to add manually.
        report["missing_areas"] = db_unresolved_flat + report.get(
            "missing_areas", []
        )
        # Surface the same items inside the Operation Timeline log — prepended
        # since matching happens before the import phase that generates the
        # rest of the log lines.
        report["logs"] = db_unresolved_lines + report.get("logs", [])

        report["city_label"] = city_label
        report["city_confidence"] = city_confidence

      try:
        os.remove(file_path)
      except Exception:
        pass

      yield f"data: {json.dumps({'step': 'complete', 'report': report})}\n\n"

    except Exception as e:
      logger.error(f"Process stream error: {traceback.format_exc()}")
      yield f"data: {json.dumps({'step': 'error', 'message': str(e)})}\n\n"

  return Response(
      stream_with_context(generate()),
      mimetype="text/event-stream",
      headers={
          "Cache-Control": "no-cache",
          "X-Accel-Buffering": "no",
      },
  )


# ==============================================================================
# SSE Event Helper
# ==============================================================================
def sse_event(step, status=None, title=None, detail=None, message=None) -> str:
  if step == "error":
    data = {"step": "error", "message": message or "Unknown error"}
  else:
    data = {
        "step": step,
        "status": status,
        "title": title,
        "detail": detail,
    }
  return f"data: {json.dumps(data)}\n\n"


# ==============================================================================
# Legacy Non-SSE Endpoint
# ==============================================================================
@app.route("/api/upload", methods=["POST"])
def upload_legacy():
  """Non-SSE legacy endpoint — backward compat with city-restricted fuzzy matching."""
  try:
    username = request.form.get("username")
    password = request.form.get("password")
    merchant_id = request.form.get("merchant_id")
    branch_id = request.form.get("branch_id")
    city_name = request.form.get("city_name")
    base_url = request.form.get("base_url", "https://console.indolj.io")

    if not all([username, password, merchant_id, branch_id, city_name]):
      return jsonify({"error": "Missing required credentials (including branch city)."}), 400

    try:
      city_name = validate_city_name(city_name)
    except ValueError as e:
      return jsonify({"error": str(e)}), 400

    if "file" not in request.files:
      return jsonify({"error": "No file uploaded."}), 400

    file = request.files["file"]
    if file.filename == "":
      return jsonify({"error": "No file selected."}), 400

    filename = secure_filename(file.filename)
    file_ext = os.path.splitext(filename)[1].lower()
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(file_path)

    raw_text = ""
    if file_ext == ".csv":
      df = pd.read_csv(file_path, index_col=False)  # index_col=False guards against trailing-comma column shift
      df = _drop_zone_id_column(df)
      raw_text = df.to_csv(index=False)
    elif file_ext in [".xls", ".xlsx"]:
      df = pd.read_excel(file_path)
      df = _drop_zone_id_column(df)
      raw_text = df.to_csv(index=False)
    elif file_ext in [".jpg", ".jpeg", ".png"]:
      if not TESSERACT_AVAILABLE:
        return jsonify({"error": "Tesseract OCR not installed."}), 500
      img = Image.open(file_path)
      raw_text = pytesseract.image_to_string(img)
    else:
      return jsonify({"error": f"Unsupported file type: {file_ext}"}), 400

    if not raw_text.strip():
      return jsonify({"error": "Could not extract any data from the file."}), 400

    # ✅ CITY — user-provided, already validated against area_mapping.json above
    pre_session = None
    city_confidence = "high"

    structured_data = process_data_with_groq(raw_text, MAPPING_FILE)
    if not structured_data:
      return jsonify({"error": "Failed to parse structured data via Groq."}), 500

    city_label = city_name

    # ✅ MATCH AREAS STRICTLY WITHIN DETECTED CITY — city_name is read
    # directly off the branch's Areas page (chosen.js dropdown), matching
    # area_mapping.json's keys exactly.
    grouped_zones, _ = match_areas_to_mapping(
        structured_data, MAPPING_FILE, city_name=city_label
    )

    config = _build_importer_config(
        username=username,
        password=password,
        merchant_id=merchant_id,
        branch_id=branch_id,
        city_name=city_name,
        base_url=base_url,
    )

    geofence_areas = load_geofence_data(MAPPING_FILE)

    report = run_importer(
        config,
        grouped_zones,
        pre_session=pre_session,
        geofence_areas=geofence_areas,
    )

    if isinstance(report.get("missing_areas"), dict):
      flat = []
      for zname, areas in report["missing_areas"].items():
        for area in areas:
          flat.append(f"[{zname}] {area} (non-geofenced)")
      report["missing_areas"] = flat

    report["city_label"] = city_name
    report["city_confidence"] = city_confidence

    try:
      os.remove(file_path)
    except Exception:
      pass

    return jsonify(report)

  except Exception as e:
    logger.error(f"Legacy upload error: {traceback.format_exc()}")
    return jsonify({"error": str(e)}), 500


# ==============================================================================
# GEOFENCE STATS ENDPOINT
# ==============================================================================
@app.route("/api/geofence-stats", methods=["GET"])
def geofence_stats():
  """Geofence data stats return karo."""
  try:
    geofence_areas = load_geofence_data(MAPPING_FILE)

    stats = {
        "total_cities": len(geofence_areas),
        "total_geofence_areas": sum(
            len(aids) for aids in geofence_areas.values()
        ),
        "cities": {},
    }

    for city_id in sorted(
        geofence_areas.keys(), key=lambda x: int(x) if x.isdigit() else 999
    ):
      area_ids = geofence_areas[city_id]
      city_name = CITY_NAMES.get(city_id, f"City {city_id}")
      stats["cities"][city_id] = {
          "name": city_name,
          "greendot_areas_count": len(area_ids),
          "area_ids_sample": sorted(list(area_ids))[:15],
      }

    return jsonify(stats), 200

  except Exception as e:
    logger.error(f"Geofence stats error: {traceback.format_exc()}")
    return jsonify({"error": str(e)}), 500


# ==============================================================================
# BRANCH MAPPING STATS ENDPOINT (Debug)
# ==============================================================================
@app.route("/api/branch-mapping", methods=["GET"])
def get_branch_mapping():
  """Debug endpoint - check current branch mapping."""
  try:
    branches = load_branch_city_mapping("branch_city_mapping.json")
    stats = {
        "status": "success",
        "total_branches": len(branches),
        "branches": branches,
    }
    return jsonify(stats), 200
  except Exception as e:
    logger.error(f"Error loading branch mapping: {traceback.format_exc()}")
    return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)