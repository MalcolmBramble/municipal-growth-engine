"""One-time script to fetch all ~30K Census places and write config/fips_places.csv."""

import csv
import os
import sys
import time

import requests
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.constants import STATE_ABBR_TO_FIPS, STATE_FIPS_TO_ABBR

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

API_KEY = os.getenv("CENSUS_API_KEY")
# Use ACS5 for the FIPS fetch — it has all places, not just large cities
BASE_URL = "https://api.census.gov/data/2023/acs/acs5"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "fips_places.csv")


def fetch_places_for_state(state_fips: str) -> list[dict]:
    """Fetch all places in a state from the Census ACS API."""
    # Build URL — key is optional for the Census API
    url = f"{BASE_URL}?get=NAME&for=place:*&in=state:{state_fips}"
    if API_KEY:
        url += f"&key={API_KEY}"
    resp = requests.get(url, timeout=30)

    if resp.status_code == 204 or not resp.text.strip():
        return []

    if resp.status_code != 200:
        print(f"  Warning: state {state_fips} returned status {resp.status_code}, skipping")
        return []

    try:
        data = resp.json()
    except Exception:
        print(f"  Warning: state {state_fips} returned invalid JSON, skipping")
        return []

    # data[0] is header row: ["NAME", "state", "place"]
    # data[1:] are data rows
    results = []
    for row in data[1:]:
        name = row[0]
        s_fips = row[1]
        p_fips = row[2]
        # NAME comes as "Columbus city, Ohio" — extract just the place name part
        place_name = name.split(",")[0].strip() if "," in name else name.strip()
        state_abbr = STATE_FIPS_TO_ABBR.get(s_fips, "??")
        results.append({
            "state_fips": s_fips,
            "state_abbr": state_abbr,
            "place_fips": p_fips,
            "place_name": place_name,
        })
    return results


def main():
    if not API_KEY:
        print("Note: No CENSUS_API_KEY found — proceeding without key (works for low volume)")

    all_places = []
    state_fips_list = sorted(STATE_ABBR_TO_FIPS.values())
    total = len(state_fips_list)

    print(f"Fetching places for {total} states/territories...")
    for i, state_fips in enumerate(state_fips_list, 1):
        abbr = STATE_FIPS_TO_ABBR.get(state_fips, state_fips)
        print(f"  [{i}/{total}] {abbr} (FIPS {state_fips})...", end=" ")
        places = fetch_places_for_state(state_fips)
        print(f"{len(places)} places")
        all_places.extend(places)
        if i < total:
            time.sleep(0.3)

    # Write CSV
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["state_fips", "state_abbr", "place_fips", "place_name"])
        writer.writeheader()
        writer.writerows(all_places)

    print(f"\nDone! Wrote {len(all_places)} places to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
