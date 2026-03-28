"""FIPS place code resolver — maps city names to Census FIPS codes."""

import csv
import logging
import os

import requests

from .constants import STATE_ABBR_TO_FIPS, STATE_FIPS_TO_ABBR, STATE_NAME_TO_ABBR
from .exceptions import ResolverError

logger = logging.getLogger(__name__)

DEFAULT_CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "fips_places.csv")

# Suffixes the Census Bureau appends to place names
PLACE_SUFFIXES = ["city", "town", "village", "borough", "CDP", "municipality", "urban county"]


class FIPSResolver:
    """Resolves user-provided city/state strings to Census FIPS codes.

    Strategy: CSV lookup first, Census API fallback.
    """

    def __init__(self, csv_path: str | None = None, api_key: str | None = None):
        self._csv_path = csv_path or DEFAULT_CSV_PATH
        self._api_key = api_key
        self._lookup: dict[tuple[str, str], dict] | None = None

    def _load_csv(self) -> dict[tuple[str, str], dict]:
        """Load the FIPS places CSV into a lookup dict keyed by (normalized_name, state_abbr)."""
        lookup = {}
        if not os.path.exists(self._csv_path):
            logger.warning("FIPS CSV not found at %s — CSV lookup disabled", self._csv_path)
            return lookup

        with open(self._csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Key by (lowercase place name, uppercase state abbr)
                name_lower = row["place_name"].strip().lower()
                state = row["state_abbr"].strip().upper()
                lookup[(name_lower, state)] = {
                    "city_name": row["place_name"].strip(),
                    "state_abbr": state,
                    "state_fips": row["state_fips"].strip().zfill(2),
                    "place_fips": row["place_fips"].strip().zfill(5),
                }
        logger.info("Loaded %d places from CSV", len(lookup))
        return lookup

    @property
    def lookup(self) -> dict[tuple[str, str], dict]:
        if self._lookup is None:
            self._lookup = self._load_csv()
        return self._lookup

    def _parse_input(self, city_state: str) -> tuple[str, str]:
        """Parse 'Columbus, OH' or 'Columbus, Ohio' into (city_name, state_abbr)."""
        if "," not in city_state:
            raise ResolverError(
                f"Invalid format: '{city_state}'. Expected 'City, ST' or 'City, State'."
            )
        parts = [p.strip() for p in city_state.split(",", 1)]
        city_name = parts[0]
        state_raw = parts[1]

        # Resolve state abbreviation
        state_upper = state_raw.upper()
        if state_upper in STATE_ABBR_TO_FIPS:
            state_abbr = state_upper
        elif state_raw.title() in STATE_NAME_TO_ABBR:
            state_abbr = STATE_NAME_TO_ABBR[state_raw.title()]
        else:
            raise ResolverError(f"Unknown state: '{state_raw}'")

        return city_name, state_abbr

    def _csv_lookup(self, city_name: str, state_abbr: str) -> dict | None:
        """Try to find the city in the local CSV."""
        name_lower = city_name.lower()

        # Direct match
        if (name_lower, state_abbr) in self.lookup:
            return self.lookup[(name_lower, state_abbr)]

        # Try appending common suffixes
        for suffix in PLACE_SUFFIXES:
            key = (f"{name_lower} {suffix}", state_abbr)
            if key in self.lookup:
                return self.lookup[key]

        # Substring match: find any entry where the place name starts with the query
        for (pname, pstate), result in self.lookup.items():
            if pstate == state_abbr and pname.startswith(name_lower):
                return result

        return None

    def _api_lookup(self, city_name: str, state_abbr: str) -> dict | None:
        """Fallback: query the Census API for all places in the state and find a match."""
        state_fips = STATE_ABBR_TO_FIPS[state_abbr]
        url = f"https://api.census.gov/data/2023/acs/acs5?get=NAME&for=place:*&in=state:{state_fips}"
        if self._api_key:
            url += f"&key={self._api_key}"
        logger.info("Falling back to Census API for %s, %s", city_name, state_abbr)

        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("Census API fallback failed: %s", e)
            return None

        name_lower = city_name.lower()
        for row in data[1:]:
            # row: ["Columbus city, Ohio", "39", "18000"]
            api_name = row[0].split(",")[0].strip().lower()
            place_fips = row[2]

            if api_name == name_lower or api_name.startswith(name_lower):
                census_name = row[0].split(",")[0].strip()
                return {
                    "city_name": census_name,
                    "state_abbr": state_abbr,
                    "state_fips": state_fips,
                    "place_fips": place_fips,
                }

            # Also try without suffix
            base_name = api_name.rsplit(" ", 1)[0] if " " in api_name else api_name
            if base_name == name_lower:
                census_name = row[0].split(",")[0].strip()
                return {
                    "city_name": census_name,
                    "state_abbr": state_abbr,
                    "state_fips": state_fips,
                    "place_fips": place_fips,
                }

        return None

    def resolve(self, city_state: str) -> dict:
        """Resolve a city/state string to FIPS codes.

        Args:
            city_state: e.g. "Columbus, OH" or "Columbus, Ohio"

        Returns:
            dict with keys: city_name, state_abbr, state_fips, place_fips

        Raises:
            ResolverError: if the city cannot be found
        """
        city_name, state_abbr = self._parse_input(city_state)

        # Try CSV first
        result = self._csv_lookup(city_name, state_abbr)
        if result:
            logger.info("Resolved '%s' via CSV: %s", city_state, result)
            return result

        # Try Census API fallback
        result = self._api_lookup(city_name, state_abbr)
        if result:
            logger.info("Resolved '%s' via API: %s", city_state, result)
            return result

        raise ResolverError(
            f"Could not resolve '{city_state}'. Check spelling or provide state abbreviation."
        )
