import os
import json
import time
import logging
import traceback
import re
import difflib
from html.parser import HTMLParser
from typing import Optional, Tuple, List, Dict, Any, Callable
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

logger = logging.getLogger(__name__)


# ==============================================================================
# HTML PARSER — zones + fee + all settings extract karta hai
# ==============================================================================
class ZoneHTMLParser(HTMLParser):
    """
    Parse shipping rate HTML to extract:
      - zone_name, zone_id
      - selected area_ids
      - fee, minimum, min_for_free_delivery, min_for_free_delivery_mobile,
        delivery_estimation  (taake re-save ke waqt correct values use hon)
    """

    # Input name → key mapping
    ZONE_FIELD_MAP = {
        "[fee]":                         "fee",
        "[minimum]":                     "minimum",
        "[min_for_free_delivery]":       "min_for_free_delivery",
        "[min_for_free_delivery_mobile]":"min_for_free_delivery_mobile",
        "[delivery_estimation]":         "delivery_estimation",
        "[status]":                      "status",
        "[weight_charges]":              "weight_charges",
    }

    def __init__(self):
        super().__init__()
        self.zones            = {}
        self.current_zone_name = None
        self.current_zone_id   = None
        self.in_select         = False
        self.select_id         = None
        self.select_name       = None
        self.current_option_value    = None
        self.current_option_selected = False
        self._zone_counter     = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if tag == "input":
            input_id   = attrs_dict.get("id", "")
            name_attr  = attrs_dict.get("name", "")
            input_val  = attrs_dict.get("value", "")

            # Zone name input
            if input_id.startswith("zone-name-"):
                self.current_zone_name = input_val.strip()
                self._zone_counter     = int(input_id.split("-")[-1])
                self.current_zone_id   = ""

            # Zone ID input
            if "[zone_id]" in name_attr:
                idx = self._extract_index(name_attr)
                if idx is not None and idx == self._zone_counter:
                    self.current_zone_id = input_val
                    if self.current_zone_name:
                        # Initialize zone entry with all fields
                        self.zones[self.current_zone_name] = {
                            "zone_id":                    self.current_zone_id,
                            "area_ids":                   [],
                            "fee":                        "0",
                            "minimum":                    "0",
                            "min_for_free_delivery":      "0",
                            "min_for_free_delivery_mobile": "0",
                            "delivery_estimation":        "0",
                            "status":                     "1",
                            "weight_charges":             "0",
                        }

            # Zone settings inputs (fee, minimum, etc.)
            for field_suffix, field_key in self.ZONE_FIELD_MAP.items():
                if field_suffix in name_attr:
                    idx = self._extract_index(name_attr)
                    if (idx is not None
                            and idx == self._zone_counter
                            and self.current_zone_name
                            and self.current_zone_name in self.zones):
                        self.zones[self.current_zone_name][field_key] = input_val
                    break

        # Select (area dropdown)
        if tag == "select":
            select_id   = attrs_dict.get("id", "")
            select_name = attrs_dict.get("name", "")
            if select_id.startswith("area_") or "[areas][]" in select_name:
                idx = (
                    self._extract_index(select_id)
                    if select_id.startswith("area_")
                    else self._extract_index(select_name)
                )
                if idx is not None and idx == self._zone_counter:
                    self.in_select   = True
                    self.select_id   = select_id
                    self.select_name = select_name

        # Option inside select
        if tag == "option" and self.in_select:
            self.current_option_value    = attrs_dict.get("value", "")
            self.current_option_selected = (
                "selected" in attrs_dict
                or attrs_dict.get("selected") is not None
            )

    def handle_endtag(self, tag):
        if tag == "select":
            self.in_select   = False
            self.select_id   = None
            self.select_name = None

        if tag == "option" and self.in_select and self.current_zone_name:
            if self.current_option_selected and self.current_option_value:
                if self.current_zone_name in self.zones:
                    self.zones[self.current_zone_name]["area_ids"].append(
                        self.current_option_value
                    )
            self.current_option_value    = None
            self.current_option_selected = False

    def _extract_index(self, text: str) -> Optional[int]:
        m = re.search(r"(\d+)", text)
        return int(m.group(1)) if m else None



# ==============================================================================
# MAIN EXPORT FUNCTION — GEOFENCE VALIDATION ADDED
# ==============================================================================
def build_area_id_to_name_map(mapping_file: str = "area_mapping.json", city_id: str = "1") -> dict:
    """
    Build mapping: area_id → area_name from area_mapping.json
    Dynamically scans all cities (Karachi, Lahore, etc.) and formats (Flat & Structured).
    
    Returns: {area_id: area_name}
    """
    area_id_to_name = {}
    
    try:
        if not os.path.exists(mapping_file):
            logger.warning(f"{mapping_file} not found - using area IDs only")
            return area_id_to_name
        
        with open(mapping_file, "r", encoding="utf-8") as f:
            area_mapping = json.load(f)
        
        # Har city (Karachi, Lahore, ID "1", etc.) par dynamically loop chalayein
        for city_key, city_data in area_mapping.items():
            if isinstance(city_data, dict):
                if "areas" in city_data:
                    # Format 1: Structured format {"areas": [{"area_id": "161", "name": "DHA Phase 1"}]}
                    for area in city_data.get("areas", []):
                        area_id = str(area.get("area_id", ""))
                        area_name = area.get("name", "")
                        if area_id and area_name:
                            area_id_to_name[area_id] = area_name
                else:
                    # Format 2: Flat format {"DHA Phase 1": "161"}
                    for area_name, area_id in city_data.items():
                        if area_id and not str(area_name).startswith("_"):
                            area_id_to_name[str(area_id)] = str(area_name)
        
        logger.info(f"Built area name map: {len(area_id_to_name)} areas loaded successfully")
        return area_id_to_name
    
    except Exception as e:
        logger.error(f"Failed to build area name map: {e}")
        return area_id_to_name


def get_area_display_name(area_id: str, area_id_to_name_map: dict) -> str:
    """Get display name for area."""
    area_id_str = str(area_id)
    area_name = area_id_to_name_map.get(area_id_str, None)
    
    if area_name:
        return area_name
    else:
        return f'Unknown Area (ID: {area_id_str})'
 
 
# ==============================================================================
# UPDATED run_importer() WITH AREA NAMES
# ==============================================================================
 
def run_importer(
    config: dict,
    grouped_zones: dict,
    progress_callback: Optional[Callable[[str, str], None]] = None,
    pre_session: Optional[requests.Session] = None,
    geofence_areas: Optional[dict] = None
) -> dict:
    """
    Enhanced importer with area name logging.
    """
    report = {
        "status":         "success",
        "total_zones":    0,
        "created":        0,
        "updated":        0,
        "removed":        0,
        "skipped":        0,
        "failed":         0,
        "moved":          0,   # duplicate areas relocated to their correct zone
        "deduplicated":   0,   # duplicate area detections found during scan
        "updated_areas":  0,   # individual areas newly merged into existing zones
        "total_areas":    0,   # subtotal of all areas across zones after merge
        "city_id":        config.get("city_id", "1"),
        "missing_areas":  {},
        "logs":           []
    }
 
    def log(msg):
        logger.info(msg)
        report["logs"].append(msg)
 
    try:
        # ── BUILD AREA NAME MAP ──
        city_id = config.get("city_id", "1")
        area_id_to_name = build_area_id_to_name_map(
            config.get("mapping_path", "area_mapping.json"),
            city_id
        )
        
        def area_display(area_id):
            """Helper function for consistent area display"""
            return get_area_display_name(area_id, area_id_to_name)
 
        zones_list = list(grouped_zones.values())
        report["total_zones"] = len(zones_list)
        log(f"Starting enhanced import: {len(zones_list)} zone(s) to process.")
 
        # Authenticate
        if progress_callback:
            progress_callback("auth_start", f"Logging in as {config['username']}...")
 
        if pre_session is not None:
            session = pre_session
            log("Reusing pre-authenticated session.")
        else:
            auth    = AuthManager(config)
            session = auth.get_session()
            log("Successfully authenticated to portal.")
 
        if progress_callback:
            progress_callback("auth_done", "Login successful!")
 
        log(f"Using city_id={city_id}")
        report["city_id"] = city_id
 
        # Load existing zones
        log("Fetching ALL existing zones from portal...")
        fetcher        = ExistingZoneFetcher(config)
        existing_zones = fetcher.fetch(session)
        log(f"Found {len(existing_zones)} existing zone(s) on portal.")
 
        api = IndoljAPIClient(config, session)
 
        area_name_to_info = {}
        for zname, zdata in existing_zones.items():
            for area_id in zdata.get("area_ids", []):
                area_name_to_info.setdefault(area_id, []).append({
                    "zone": zname,
                    "area_id": area_id,
                    "fee": zdata.get("fee", "0")
                })
 
        log(f"Built area deduplication map with {len(area_name_to_info)} area(s).")
 
        # ── PHASE 1: Deduplication & Price Check ──
        log("\n── PHASE 1: Deduplication & Price Check...")
        
        for zone in zones_list:
            target_zone_name = zone["Zone Name"]
            target_fee = zone.get("Delivery Charge", "0")
            area_ids = zone.get("area_ids", [])
 
            for area_id in area_ids:
                area_id_str = str(area_id)
                
                for existing_zone_name, existing_zone_data in existing_zones.items():
                    if existing_zone_name == target_zone_name:
                        continue
                    
                    if area_id_str in existing_zone_data.get("area_ids", []):
                        existing_fee = existing_zone_data.get("fee", "0")
                        
                        # ✅ SHOW AREA NAME
                        log(
                            f"DEDUP: {area_display(area_id_str)} found in WRONG zone "
                            f"'{existing_zone_name}' (fee={existing_fee}) "
                            f"→ moving to '{target_zone_name}' (fee={target_fee})"
                        )
                        
                        report["deduplicated"] += 1
 
        # ── PHASE 2: Remove areas with wrong price/zone ──
        log("\n── PHASE 2: Removing areas with wrong price/zone...")
        
        zones_needing_update = {}
        
        for zone in zones_list:
            target_zone_name = zone["Zone Name"]
            target_fee = zone.get("Delivery Charge", "0")
            target_area_ids = set(str(a) for a in zone.get("area_ids", []))
 
            for existing_zone_name, existing_zone_data in existing_zones.items():
                if existing_zone_name == target_zone_name:
                    existing_fee = existing_zone_data.get("fee", "0")
                    if existing_fee != target_fee:
                        log(
                            f"PRICE CHANGE: '{existing_zone_name}' "
                            f"fee: {existing_fee} → {target_fee}"
                        )
                
                else:
                    existing_area_ids = set(existing_zone_data.get("area_ids", []))
                    duplicate_ids = existing_area_ids & target_area_ids
                    
                    if duplicate_ids:
                        # ✅ SHOW AREA NAMES
                        dup_display = ", ".join([area_display(aid) for aid in duplicate_ids])
                        log(
                            f"DUPLICATE FOUND: {len(duplicate_ids)} area(s) in "
                            f"'{existing_zone_name}' already: {dup_display} "
                            f"→ moving to '{target_zone_name}'"
                        )
                        zones_needing_update.setdefault(existing_zone_name, set()).update(
                            duplicate_ids
                        )
 
        # Execute removals
        if zones_needing_update:
            for old_zone_name, ids_to_remove in zones_needing_update.items():
                old_zone_data = existing_zones.get(old_zone_name)
                if not old_zone_data:
                    continue
 
                updated_ids = [
                    aid for aid in old_zone_data["area_ids"]
                    if aid not in ids_to_remove
                ]
 
                # ✅ SHOW AREA NAMES
                removed_display = ", ".join([area_display(aid) for aid in ids_to_remove])
                log(
                    f"REMOVING {len(ids_to_remove)} area(s) from "
                    f"'{old_zone_name}': {removed_display} (keeping {len(updated_ids)})"
                )
 
                old_zone_info = {
                    "Zone Name": old_zone_name,
                    "Delivery Charge": old_zone_data.get("fee", "0"),
                    "Minimum Order Value": old_zone_data.get("minimum", "0"),
                    "FreeDeliveryAfter": old_zone_data.get("min_for_free_delivery", "0"),
                    "FreeDeliveryAfterMobile": old_zone_data.get("min_for_free_delivery_mobile", "0"),
                    "Delivery Estimation": old_zone_data.get("delivery_estimation", "0"),
                }
 
                if not updated_ids:
                    log(f"⚠️  SKIP: '{old_zone_name}' would have 0 areas - not saving")
                    report["removed"] += len(ids_to_remove)
                    report["moved"] += len(ids_to_remove)
                    report["skipped"] += 1
                    continue
                
                success, msg = api.save_zone(
                    old_zone_info,
                    updated_ids,
                    zone_id=old_zone_data["zone_id"]
                )
 
                if success:
                    log(f"✓ Removed {len(ids_to_remove)} area(s) from '{old_zone_name}'")
                    report["removed"] += len(ids_to_remove)
                    report["moved"] += len(ids_to_remove)
                    existing_zones[old_zone_name]["area_ids"] = updated_ids
                else:
                    log(f"✗ Failed to remove from '{old_zone_name}': {msg}")
                    report["failed"] += 1
 
                time.sleep(config.get("delay_between_zones", 0.5))
 
        # ── PHASE 3: Create/Update zones ──
        log("\n── PHASE 3: Creating/Updating zones with correct pricing...")
        
        if progress_callback:
            progress_callback(
                "upload_start",
                f"Uploading {len(zones_list)} zone(s) to portal..."
            )
 
        for i, zone in enumerate(zones_list):
            zname = zone["Zone Name"]
            area_ids = zone.get("area_ids", [])
            
            if not area_ids:
                log(f"SKIP '{zname}' — zero valid mapped areas.")
                report["failed"] += 1
                if progress_callback:
                    progress_callback(
                        "upload_progress",
                        f"Skipped '{zname}' ({i+1}/{len(zones_list)})"
                    )
                continue
 
            if progress_callback:
                progress_callback(
                    "upload_progress",
                    f"Processing '{zname}' ({i+1}/{len(zones_list)})..."
                )
 
            existing = existing_zones.get(zname)
            
            if existing:
                existing_ids = set(existing["area_ids"])
                new_ids = set(str(a) for a in area_ids)
                existing_fee = existing.get("fee", "0")
                new_fee = zone.get("Delivery Charge", "0")
 
                price_changed = existing_fee != new_fee
                areas_changed = new_ids != existing_ids
                
                if not price_changed and not areas_changed:
                    log(f"SKIP '{zname}' — already up-to-date (fee={existing_fee}, areas={len(existing_ids)})")
                    report["skipped"] += 1
                    report["total_areas"] += len(existing_ids)
                    continue
 
                merged_ids = list(existing_ids | new_ids)
                added = len(new_ids - existing_ids)
                
                # ✅ SHOW AREA NAMES FOR NEW AREAS
                if added > 0:
                    new_areas = new_ids - existing_ids
                    added_display = ", ".join([area_display(aid) for aid in new_areas])
                    log(
                        f"UPDATE '{zname}' — added {added} area(s): {added_display} "
                        f"({len(existing_ids)} → {len(merged_ids)} total)"
                    )
                else:
                    log(
                        f"UPDATE '{zname}' — price change {existing_fee}→{new_fee} "
                        f"({len(merged_ids)} areas)"
                    )
 
                success, msg = api.save_zone(zone, merged_ids, zone_id=existing["zone_id"])
                if success:
                    log(f"✓ Updated '{zname}'")
                    report["updated"] += 1
                    report["updated_areas"] += added
                    report["total_areas"] += len(merged_ids)
                else:
                    # ✅ SHOW WHICH AREAS FAILED
                    failed_display = ", ".join([area_display(aid) for aid in merged_ids[:5]])
                    log(f"✗ Failed '{zname}' — {msg} (areas: {failed_display}...)")
                    report["failed"] += 1
 
            else:
                # ✅ SHOW AREA NAMES FOR NEW ZONE
                areas_display = ", ".join([area_display(aid) for aid in area_ids[:5]])
                if len(area_ids) > 5:
                    areas_display += f" ... +{len(area_ids) - 5} more"
                
                log(
                    f"CREATE '{zname}' — {len(area_ids)} area(s), "
                    f"fee={zone.get('Delivery Charge', '0')} | areas: {areas_display}"
                )
                success, msg = api.save_zone(zone, area_ids, zone_id="")
                if success:
                    log(f"✓ Created '{zname}'")
                    report["created"] += 1
                    report["total_areas"] += len(area_ids)
                else:
                    log(f"✗ Failed to create '{zname}': {msg}")
                    report["failed"] += 1
 
            time.sleep(config.get("delay_between_zones", 0.5))
 
        if progress_callback:
            progress_callback(
                "upload_done",
                f"Done! Created={report['created']}, Updated={report['updated']}, "
                f"Removed={report['removed']}, Failed={report['failed']}"
            )
 
        log(
            f"\n{'='*70}\nSUMMARY\n{'='*70}\n"
            f"Total Zones: {report['total_zones']}\n"
            f"Created: {report['created']} ✓\n"
            f"Updated: {report['updated']} ✓\n"
            f"Areas Added/Updated: {report['updated_areas']}\n"
            f"Removed/Moved: {report['removed']} (duplicates/wrong price)\n"
            f"Deduplicated: {report['deduplicated']}\n"
            f"Subtotal Areas (all zones): {report['total_areas']}\n"
            f"Skipped: {report['skipped']}\n"
            f"Failed: {report['failed']} ✗\n"
            f"{'='*70}"
        )
 
    except Exception as e:
        report["status"] = "error"
        err_msg = f"CRITICAL ERROR: {traceback.format_exc()}"
        log(err_msg)
        logger.error(err_msg)
 
    return report


# ==============================================================================
# AUTH MANAGER
# ==============================================================================
class AuthManager:
    def __init__(self, cfg: dict) -> None:
        self.cfg     = cfg
        self.session = requests.Session()
        retries = Retry(
            total=cfg.get("max_retries", 3),
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504]
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.mount("http://",  HTTPAdapter(max_retries=retries))

    def get_session(self) -> requests.Session:
        if self._requests_login():
            return self.session
        if SELENIUM_AVAILABLE and self._selenium_login():
            return self.session
        raise RuntimeError("Authentication failed — check username/password.")

    def _probe_auth(self) -> bool:
        try:
            url = f"{self.cfg['base_url']}{self.cfg['branches_path']}"
            r   = self.session.get(url, timeout=10, allow_redirects=False)
            return r.status_code == 200 and "login" not in r.url.lower()
        except Exception:
            return False

    def _requests_login(self) -> bool:
        try:
            login_url = f"{self.cfg['base_url']}{self.cfg['login_path']}"
            resp      = self.session.get(login_url, timeout=15)
            payload   = {
                "username": self.cfg["username"],
                "password": self.cfg["password"]
            }
            for token_name in ["csrf_token", "_token", "ci_csrf_token"]:
                if f'name="{token_name}"' in resp.text:
                    m = re.search(rf'name="{token_name}" value="([^"]+)"', resp.text)
                    if m:
                        payload[token_name] = m.group(1)
                        break
            headers = {"Referer": login_url, "Origin": self.cfg["base_url"]}
            self.session.post(login_url, data=payload, headers=headers, timeout=20)
            return self._probe_auth()
        except Exception as e:
            logger.error(f"Direct login exception: {e}")
            return False

    def login_sequence(self, driver, wait) -> bool:
        """Shared login sequence using Selenium driver and wait objects."""
        login_url = f"{self.cfg['base_url']}{self.cfg['login_path']}"
        driver.get(login_url)
        time.sleep(2)
        wait.until(EC.presence_of_element_located((By.ID, "username"))).send_keys(
            self.cfg["username"]
        )
        wait.until(EC.presence_of_element_located((By.ID, "password"))).send_keys(
            self.cfg["password"]
        )
        wait.until(
            EC.element_to_be_clickable((By.ID, "submitBtn"))
        ).click()
        time.sleep(4)
        return "login" not in driver.current_url.lower()

    def _selenium_login(self) -> bool:
        driver = None
        try:
            service = Service(ChromeDriverManager().install())
            options = webdriver.ChromeOptions()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            driver = webdriver.Chrome(service=service, options=options)
            wait   = WebDriverWait(driver, 20)

            if not self.login_sequence(driver, wait):
                return False

            for cookie in driver.get_cookies():
                self.session.cookies.set(
                    cookie["name"], cookie["value"],
                    domain=cookie.get("domain"),
                    path=cookie.get("path", "/")
                )
            return True
        except Exception as e:
            logger.error(f"Selenium login failed: {e}")
            return False
        finally:
            if driver:
                driver.quit()


# ==============================================================================
# EXISTING ZONE FETCHER — Load More bhi handle karta hai
# ==============================================================================
class ExistingZoneFetcher:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg

    def fetch(self, session: requests.Session) -> dict:
        """
        Pehle requests try karo.
        Agar Load More button hai ya 0 zones mile → Selenium use karo
        (Selenium Load More button click karta rehta hai jab tak sab load na hon).
        """
        zones, has_more = self._fetch_via_requests(session)

        if zones and not has_more:
            logger.info(f"All {len(zones)} zone(s) loaded via HTML parse (no Load More).")
            return zones

        if has_more:
            logger.info(
                f"Load More detected ({len(zones)} partial zones). "
                "Switching to Selenium for complete fetch..."
            )
        else:
            logger.info("0 zones from HTML parse. Trying Selenium...")

        return self._fetch_via_selenium()

    def _fetch_via_requests(self, session: requests.Session) -> Tuple[dict, bool]:
        """
        Returns: (zones_dict, has_load_more_button)
        """
        url = (
            f"{self.cfg['base_url']}"
            f"{self.cfg['shippingrate_path'].format(branch_id=self.cfg['branch_id'])}"
        )
        try:
            r      = session.get(url, timeout=30)
            html   = r.text
            parser = ZoneHTMLParser()
            parser.feed(html)

            # Load More button check
            has_more = (
                "Load More" in html
                or "onScrollLoad" in html
                or "load_more" in html.lower()
            )

            logger.info(
                f"HTML parse: {len(parser.zones)} zone(s), "
                f"Load More={has_more}"
            )
            return parser.zones, has_more

        except Exception as e:
            logger.debug(f"Requests zone fetch failed: {e}")
            return {}, False

    def _fetch_via_selenium(self) -> dict:
        """
        Selenium se saare zones load karo — Load More button baar baar click karo.
        """
        if not SELENIUM_AVAILABLE:
            logger.warning("Selenium not available — cannot fetch all zones.")
            return {}

        driver = None
        zones  = {}

        try:
            service = Service(ChromeDriverManager().install())
            options = webdriver.ChromeOptions()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            driver = webdriver.Chrome(service=service, options=options)
            wait   = WebDriverWait(driver, 25)

            # Login using shared sequence
            auth_mgr = AuthManager(self.cfg)
            if not auth_mgr.login_sequence(driver, wait):
                logger.error("Selenium login sequence failed during zone fetching.")
                return {}

            # Shippingrate page
            shipping_url = (
                f"{self.cfg['base_url']}"
                f"{self.cfg['shippingrate_path'].format(branch_id=self.cfg['branch_id'])}"
            )
            driver.get(shipping_url)
            time.sleep(3)

            # ── Load More button baar baar click karo ──
            max_clicks  = 12   # safety limit
            click_count = 0

            for _ in range(max_clicks):
                try:
                    load_more_btn = driver.find_element(
                        By.XPATH,
                        "//button[contains(text(), 'Load More') or "
                        "contains(@onclick, 'onScrollLoad')]"
                    )
                    if load_more_btn.is_displayed() and load_more_btn.is_enabled():
                        driver.execute_script("arguments[0].click();", load_more_btn)
                        click_count += 1
                        logger.info(f"Load More clicked ({click_count}x) — waiting...")
                        time.sleep(2)
                    else:
                        break
                except Exception:
                    break  # Button nahi mila = sab load ho gaya

            if click_count > 0:
                logger.info(f"Load More clicked {click_count} time(s). All zones loaded.")
            else:
                logger.info("No Load More button found — all zones were on first page.")

            # ── JS se saare zones extract karo (fee bhi) ──
            zones = driver.execute_script("""
                const result = {};
                document.querySelectorAll("input[id^='zone-name-']").forEach(input => {
                    const idx = input.getAttribute('data-i')
                                || input.id.replace('zone-name-', '');
                    const name = input.value.trim();
                    if (!name) return;

                    // Zone ID
                    let zoneId = '';
                    const idInput =
                        document.querySelector(`input#zone-id-${idx}`) ||
                        document.querySelector(`input[name*='zones[${idx}][zone_id]']`);
                    if (idInput) zoneId = idInput.value;

                    // Zone settings
                    const getVal = (field) => {
                        const el = document.querySelector(
                            `input[name*='zones[${idx}][${field}]']`
                        );
                        return el ? el.value : '0';
                    };

                    // Selected area IDs
                    const select =
                        document.querySelector(`select#area_${idx}`) ||
                        document.querySelector(
                            `select[name*='zones[${idx}][areas]']`
                        );
                    const areaIds = [];
                    if (select) {
                        Array.from(select.options).forEach(opt => {
                            if (opt.selected && opt.value)
                                areaIds.push(opt.value);
                        });
                    }

                    result[name] = {
                        zone_id:                    zoneId,
                        area_ids:                   areaIds,
                        fee:                        getVal('fee'),
                        minimum:                    getVal('minimum'),
                        min_for_free_delivery:      getVal('min_for_free_delivery'),
                        min_for_free_delivery_mobile: getVal('min_for_free_delivery_mobile'),
                        delivery_estimation:        getVal('delivery_estimation'),
                        status:                     getVal('status') || '1',
                        weight_charges:             getVal('weight_charges'),
                    };
                });
                return result;
            """) or {}

            logger.info(f"Selenium fetched {len(zones)} zone(s) total.")

        except Exception as e:
            logger.error(f"Selenium zone fetch failed: {e}\n{traceback.format_exc()}")
        finally:
            if driver:
                driver.quit()

        return zones


# ==============================================================================
# INDOLJ API CLIENT
# ==============================================================================
class IndoljAPIClient:
    def __init__(self, cfg: dict, session: requests.Session) -> None:
        self.cfg      = cfg
        self.session  = session
        self.save_url = f"{cfg['base_url']}{cfg['save_endpoint']}"
        self.referer  = (
            f"{cfg['base_url']}"
            f"{cfg['shippingrate_path'].format(branch_id=cfg['branch_id'])}"
        )

    def save_zone(self, zone_data: dict, area_ids: list, zone_id: str = "") -> Tuple[bool, str]:
        """Zone save/update karo. area_ids = final list jo portal pe honi chahiye."""
        zone_name = zone_data["Zone Name"]

        payload = {
            "merchant_id":                          self.cfg["merchant_id"],
            "branch_id":                            self.cfg["branch_id"],
            "city_id":                              self.cfg["city_id"],
            "state_id":                             self.cfg["state_id"],
            "country_id":                           self.cfg["country_id"],
            "zones[0][zone_name]":                  zone_name,
            "zones[0][minimum]":                    zone_data.get("Minimum Order Value", "0"),
            "zones[0][fee]":                        zone_data.get("Delivery Charge", "0"),
            "zones[0][delivery_estimation]":        zone_data.get("Delivery Estimation", "0"),
            "zones[0][min_for_free_delivery]":      zone_data.get("FreeDeliveryAfter", "0"),
            "zones[0][min_for_free_delivery_mobile]":
                zone_data.get("FreeDeliveryAfterMobile", "0"),
            "zones[0][status]":                     "1",
            "zones[0][zone_id]":                    zone_id or "",
            "zones[0][weight_charges]":             "0",
            "zones[0][additional_weight_charges]":  "0",
            "zones[0][end_weight_range]":           "0",
            "additional_weight_charges":            "0",
            "end_weight_range":                     "0",
        }

        if not area_ids:
            return False, "No valid area IDs provided"

        payload["zones[0][areas][]"] = area_ids

        headers = {
            "Accept":           "application/json, text/javascript, */*; q=0.01",
            "Accept-Language":  "en-US,en;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
            "Origin":           self.cfg["base_url"],
            "Referer":          self.referer,
        }

        try:
            r = self.session.post(
                self.save_url,
                data=payload,
                headers=headers,
                timeout=self.cfg.get("request_timeout", 30)
            )

            logger.debug(f"API response {r.status_code}: {r.text[:300]}")

            if r.status_code != 200:
                return False, f"HTTP {r.status_code}: {r.text[:200]}"

            try:
                resp_json = r.json()
                if (resp_json.get("success") is True
                        or resp_json.get("status") == "success"):
                    return True, str(resp_json.get("message", resp_json.get("msg", "OK")))
                if resp_json.get("success") is False or "error" in resp_json:
                    return False, str(resp_json)
                return True, str(resp_json.get("msg", resp_json.get("message", "OK")))
            except Exception:
                if "error" in r.text.lower() or "exception" in r.text.lower():
                    return False, r.text[:300]
                return True, "OK (non-JSON response)"

        except requests.exceptions.RequestException as e:
            return False, f"Network error: {e}"
        except Exception as e:
            return False, f"Unexpected error: {e}"