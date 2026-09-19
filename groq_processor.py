import os
import json
import logging
import traceback
import re
import time
import difflib
import google.generativeai as genai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def extract_json_array(text):
    """Robustly extracts a JSON array from text, attempting to fix truncations."""
    text = text.strip()
    try:
        return json.loads(text)
    except:
        pass

    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except:
        pass

    start = text.find('[')
    if start != -1:
        end = text.rfind(']')
        if end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except:
                pass
        last_brace = text.rfind('}')
        if last_brace != -1 and last_brace > start:
            fixed_text = text[start:last_brace + 1] + ']'
            try:
                return json.loads(fixed_text)
            except:
                pass
    return []


def process_data_with_groq(raw_text_or_csv, mapping_file_path, progress_callback=None):
    """
    Uses Gemini 1.5 Flash to:
    1. Parse raw CSV/image text into structured records
    2. Correct spelling mistakes in area names
    3. Expand grouped areas (e.g. "North Nazimabad all block", "Clifton all block")
    4. If OLD and NEW price columns exist, always use NEW price as Delivery Charge
    5. Group by Zone Name if present, else group by Delivery Charge value
       (each unique charge = one zone named "Zone {charge}")
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment variables. Set it first: export GEMINI_API_KEY=your_key")

    # Initialize Gemini AI client
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-3.5-flash-lite",
        system_instruction="You are a data processing assistant. Always respond with ONLY a raw valid JSON array. No markdown. No explanation. Just the JSON array starting with [ and ending with ].",
        generation_config={
            "temperature": 0.1,
            "response_mime_type": "application/json"
        }
    )

    lines = [l for l in raw_text_or_csv.split('\n') if l.strip()]
    header = lines[0] if lines else ""
    data_lines = lines[1:] if len(lines) > 1 else []
    data_lines = [l for l in data_lines if l.strip() and l.strip() != ',']

    # Gemini has a robust context window, but chunking ensures stability and avoids memory/response cutoffs.
    chunk_size = 80  
    chunks = []
    if len(data_lines) > 0:
        for i in range(0, len(data_lines), chunk_size):
            chunk_lines = data_lines[i:i + chunk_size]
            chunks.append(header + "\n" + "\n".join(chunk_lines))
    else:
        chunks = [raw_text_or_csv]

    all_structured_data = []

    for idx, chunk in enumerate(chunks):
        detail = f"Processing chunk {idx + 1}/{len(chunks)} with Gemini AI..."
        logger.info(detail)
        if progress_callback:
            progress_callback(detail)

        prompt = f"""You are a data cleaning assistant for a delivery zone automation system.
You will be given raw data containing delivery area names and pricing info.

CRITICAL RULES — follow all of these exactly:

RULE 1 — OLD vs NEW Price:
  If the data has columns named "OLD" and "NEW" (or "Old Price"/"New Price", or similar),
  ALWAYS use the NEW column value as the "Delivery Charge". Ignore the OLD value completely.
  Example: if row says "DHA Phase 6 | OLD: 230 | NEW: 150", set Delivery Charge = 150.

RULE 2 — Zone Name:
  - If the data has a "Zone Name" column, use it exactly.
  - If there is NO Zone Name column, set Zone Name = "Zone_" + the delivery charge value.
    Example: charge=99 → Zone Name = "Zone_99", charge=149 → Zone Name = "Zone_149"
  - This way areas with same delivery charge will automatically be grouped together.

RULE 3 — Area Name Correction:
  Correct obvious spelling/OCR mistakes:
  - "ii chundigar raod" → "I.I Chundrigar Road"
  - "new karachi sector 3" → "New Karachi Sector 3"
  - "dha phase 6" → "DHA Phase 6"
  - Capitalize properly, fix typos

RULE 4 — Expand grouped areas (CRITICAL):
  If an entry says "all block" or groups multiple areas, EXPLICITLY expand them into separate records for EVERY known block.
  - "Clifton all block" → MUST expand to: "Clifton Block 1", "Clifton Block 2", "Clifton Block 3", "Clifton Block 4", "Clifton Block 5", "Clifton Block 6", "Clifton Block 7", "Clifton Block 8".
  - "North Nazimabad all block" → expand to Block A, Block B, Block C ... Block N.
  - "Gulistan e Johar block 1,2,3" → split into 3 separate records.
  - Each split record gets the same Zone Name and Delivery Charge.

RULE 5 — Missing fields:
  If any pricing field is missing, use "0". Never leave blank.

RULE 6 — Output only JSON:
  Respond with ONLY a raw JSON array. No markdown, no explanation, no extra text.

Output format (one object per area):
[{{
  "Zone Name": "Zone_99 or actual zone name",
  "Area Name": "Corrected Area Name",
  "Delivery Charge": "99",
  "FreeDeliveryAfter": "0",
  "FreeDeliveryAfterMobile": "0",
  "Minimum Order Value": "0",
  "Delivery Estimation": "0"
}}]

Raw Data:
{chunk}"""

        try:
            # Using Gemini 1.5 Flash to generate structured output
            response = model.generate_content(prompt)
            result_text = response.text.strip()
            
            structured_data = extract_json_array(result_text)

            if not structured_data:
                logger.warning(f"Chunk {idx + 1} returned empty JSON. Response: {result_text[:200]}...")
            else:
                logger.info(f"Chunk {idx + 1} returned {len(structured_data)} records.")

            all_structured_data.extend(structured_data)

            # Minimal delay for Gemini rate limits (can be adjusted based on your tier)
            if idx < len(chunks) - 1:
                time.sleep(1.0) 

        except Exception as e:
            logger.error(f"Gemini processing failed on chunk {idx + 1}: {traceback.format_exc()}")
            raise Exception(f"Failed to process chunk {idx + 1} with Gemini: {e}")

    # ── POST-PROCESSING ──
    all_structured_data = _ensure_zone_names(all_structured_data)
    logger.info(f"Total records after Gemini processing: {len(all_structured_data)}")
    _log_zone_summary(all_structured_data)

    return all_structured_data


def _ensure_zone_names(records):
    """Post-processing: if Zone Name is still 'Default Zone' or empty, generate it from delivery charge."""
    result = []
    for r in records:
        zone = r.get("Zone Name", "").strip()
        charge = str(r.get("Delivery Charge", "0")).strip()

        if not zone or zone.lower() in ("default zone", "defaultzone", ""):
            zone = f"Zone_{charge}" if charge and charge != "0" else "Zone_Default"
            r["Zone Name"] = zone

        result.append(r)
    return result


def _log_zone_summary(records):
    """Log a summary of zones and their area counts."""
    zone_counts = {}
    for r in records:
        z = r.get("Zone Name", "Unknown")
        zone_counts[z] = zone_counts.get(z, 0) + 1

    logger.info(f"Zone summary ({len(zone_counts)} zones):")
    for zone, count in sorted(zone_counts.items()):
        logger.info(f"  {zone}: {count} area(s)")



# city_id → city name translation (FALLBACK ONLY — see note below).
# area_mapping.json is keyed by CITY NAME (e.g. "Lahore", "islamabad"), not by
# numeric city_id, so city_id must be translated before it can be used to pick
# the correct bucket.
#
# ⚠️ CONFIRMED CORRECTION: area_mapping.json itself embeds a "city_id" field
# inside a couple of city buckets, scraped straight from the portal. That
# ground truth shows:
#     Karachi -> city_id "1"   (matches the old assumption)
#     Lahore  -> city_id "3"   (the old table had "3": "Islamabad" — WRONG,
#                                this was the actual bug: a Lahore branch
#                                resolving to city_id=3 was being treated as
#                                Islamabad everywhere in app.py, including in
#                                the old fallback match logic below)
# "2" is therefore NOT confirmed as Islamabad — it was only ever a guess.
# Because of this, match_areas_to_mapping() below reads the embedded
# "city_id" field straight from area_mapping.json FIRST (authoritative) and
# only falls back to this static table for cities that don't have an
# embedded id. Verify "2" against the real portal before relying on it.
CITY_ID_TO_NAME = {
    "1": "Karachi",
    "3": "Lahore",
    # "2": unconfirmed — do not assume Islamabad. Check the portal directly
    #      (e.g. open a known Islamabad branch's shippingrate page and read
    #      its city_id) before adding an entry here.
    "4": "Rawalpindi",
    "5": "Faisalabad",
    "6": "Multan",
    "7": "Peshawar",
    "8": "Quetta",
    "9": "Hyderabad",
}


def match_areas_to_mapping(structured_data, mapping_file_path, progress_callback=None, city_id=None, city_name=None):
    """
    Takes AI-structured data and matches area names to area_mapping.json using fuzzy matching.
    Returns (matched_zones_dict, all_missing_areas).

    city_id: numeric branch city id (e.g. "2"). Translated to a city name via
             CITY_ID_TO_NAME before lookup, since area_mapping.json is keyed by name.
    city_name: optional — pass the already-resolved city label (e.g. app.py's
               CITY_NAMES.get(city_id)) directly to skip/override the translation above.
    """
    mapping = {}
    if os.path.exists(mapping_file_path):
        with open(mapping_file_path, "r", encoding="utf-8") as f:
            full_mapping = json.load(f)

        logger.info(f"Loaded area_mapping.json - Top-level keys: {list(full_mapping.keys())[:10]}")

        # Case-insensitive lookup of the real keys ("islamabad" is lowercase in
        # the file while other cities are capitalized).
        key_lookup = {
            str(k).strip().lower(): k
            for k, v in full_mapping.items()
            if isinstance(v, dict) and len(v) > 0
        }

        # Authoritative: some city buckets embed their own real "city_id"
        # (scraped from the portal). This is ground truth and overrides any
        # static guess table — it's what caught Lahore actually being id 3,
        # not 2.
        embedded_id_to_key = {
            str(v.get("city_id")): k
            for k, v in full_mapping.items()
            if isinstance(v, dict) and v.get("city_id") not in (None, "")
        }

        if city_id or city_name:
            matched_key = None

            # 1) Embedded ground-truth id match (most reliable)
            if city_id is not None and str(city_id) in embedded_id_to_key:
                matched_key = embedded_id_to_key[str(city_id)]

            # 2) Explicit city_name / translated-id name match
            candidate_names = []
            if not matched_key:
                if city_name:
                    candidate_names.append(str(city_name))
                if city_id is not None:
                    translated = CITY_ID_TO_NAME.get(str(city_id))
                    if translated:
                        candidate_names.append(translated)
                    candidate_names.append(str(city_id))  # in case a mapping is ever keyed by raw id

                for name in candidate_names:
                    if name.strip().lower() in key_lookup:
                        matched_key = key_lookup[name.strip().lower()]
                        break

            if matched_key:
                mapping = full_mapping[matched_key]
                logger.info(
                    f"✓ city_id={city_id} city_name={city_name} → matched '{matched_key}' "
                    f"with {len(mapping)} areas"
                )
            else:
                # CRITICAL: do NOT silently fall back to some other city's areas.
                # That silent fallback was the actual bug (e.g. Lahore branches
                # getting matched against Islamabad's area list). Better to
                # return zero matches (areas show up as "missing") than to
                # upload areas against the wrong city.
                available_cities = list(full_mapping.keys())
                logger.error(
                    f"✗ Could not resolve city for city_id={city_id} city_name={city_name} "
                    f"(tried: {candidate_names}). Available cities in area_mapping.json: "
                    f"{available_cities}. Refusing to fall back to a different city — "
                    f"all areas for this batch will be reported as unmatched instead of "
                    f"being matched against the wrong city."
                )
                mapping = {}
        else:
            if isinstance(full_mapping, dict) and len(full_mapping) > 0:
                first_key = list(full_mapping.keys())[0]
                first_value = full_mapping[first_key]
                
                if isinstance(first_value, dict):
                    mapping = first_value
                    logger.info(f"Auto-detected multi-city format, using city '{first_key}': {len(mapping)} areas")
                else:
                    mapping = full_mapping
                    logger.info(f"Flat format detected: {len(mapping)} areas loaded")

    lower_mapping = {k.lower(): v for k, v in mapping.items()}
    valid_keys_lower = list(lower_mapping.keys())

    total_areas = len(structured_data)
    matched_count = 0
    unmatched_names = []

    grouped_zones = {}

    for row in structured_data:
        zone_name = row.get("Zone Name", "Zone_Default").strip()
        area_name = row.get("Area Name", "").strip()

        if not area_name:
            continue

        if zone_name not in grouped_zones:
            grouped_zones[zone_name] = {
                "Zone Name": zone_name,
                "areas": [],
                "area_ids": [],
                "area_names": [], 
                "missing_areas": [],
                "Delivery Charge": str(row.get("Delivery Charge", "0")),
                "FreeDeliveryAfter": str(row.get("FreeDeliveryAfter", "0")),
                "FreeDeliveryAfterMobile": str(row.get("FreeDeliveryAfterMobile", "0")),
                "Minimum Order Value": str(row.get("Minimum Order Value", "0")),
                "Delivery Estimation": str(row.get("Delivery Estimation", "0")),
            }

        grouped_zones[zone_name]["areas"].append(area_name)

        matched_area_id = None
        matched_area_name = None

        if area_name in mapping:
            matched_area_id = mapping[area_name]
            matched_area_name = area_name
            matched_count += 1
        else:
            lower_key = area_name.lower()
            if lower_key in lower_mapping:
                matched_area_id = lower_mapping[lower_key]
                for orig_name, area_id in mapping.items():
                    if area_id == matched_area_id:
                        matched_area_name = orig_name
                        break
                matched_count += 1
            else:
                matches = difflib.get_close_matches(lower_key, valid_keys_lower, n=1, cutoff=0.70)
                if matches:
                    matched_area_id = lower_mapping[matches[0]]
                    for orig_name, area_id in mapping.items():
                        if area_id == matched_area_id:
                            matched_area_name = orig_name
                            break
                    matched_count += 1
                    logger.info(f"Fuzzy matched '{area_name}' -> '{matched_area_name}' (ID: {matched_area_id})")
                else:
                    grouped_zones[zone_name]["missing_areas"].append(area_name)
                    unmatched_names.append(area_name)
        
        if matched_area_id:
            grouped_zones[zone_name]["area_ids"].append(matched_area_id)
            grouped_zones[zone_name]["area_names"].append(matched_area_name or area_name)

    detail = f"Matched {matched_count}/{total_areas} areas. {len(unmatched_names)} unresolved."
    logger.info(detail)
    if progress_callback:
        progress_callback(detail)

    return grouped_zones, unmatched_names