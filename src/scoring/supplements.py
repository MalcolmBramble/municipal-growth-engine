"""Supplemental data loader for manual scoring overrides.

Reads a JSON or CSV file containing hand-researched data for dimensions
that lack API coverage (e.g., graduation rates, bond ratings, crime stats).
Merges into the scoring pipeline as manual_scores or profile field overrides.
"""

import csv
import json
import logging
import os

logger = logging.getLogger(__name__)


def load_supplements(path: str) -> dict:
    """Load supplemental data from a JSON or CSV file.

    JSON format (preferred):
    {
      "Columbus, OH": {
        "manual_scores": {
          "public_safety": 1,
          "fiscal_health": 0
        },
        "data": {
          "graduation_rate": 85.2,
          "bond_rating": "AA",
          "homicide_count": 120,
          "violent_crime_rate": 450.3
        }
      }
    }

    CSV format:
    city,dimension,score,notes
    "Columbus, OH",public_safety,1,"Based on UCR data showing 15% decline in violent crime"
    "Columbus, OH",fiscal_health,0,"AA bond rating, stable revenue"

    Returns:
        dict keyed by city string, each containing:
        - manual_scores: dict[str, int] for dimension overrides
        - data: dict of supplemental field values
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Supplements file not found: {path}")

    ext = os.path.splitext(path)[1].lower()

    if ext == ".json":
        return _load_json(path)
    elif ext == ".csv":
        return _load_csv(path)
    else:
        raise ValueError(f"Unsupported supplements format: {ext} (use .json or .csv)")


def _load_json(path: str) -> dict:
    """Load supplemental data from JSON."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    result = {}
    for city_key, city_data in raw.items():
        entry = {"manual_scores": {}, "data": {}}

        if isinstance(city_data, dict):
            # Extract manual_scores
            scores = city_data.get("manual_scores", {})
            for dim, score in scores.items():
                entry["manual_scores"][dim] = max(-2, min(2, int(score)))

            # Extract supplemental data fields
            entry["data"] = city_data.get("data", {})

        result[_normalize_key(city_key)] = entry

    logger.info("Loaded supplements for %d cities from %s", len(result), path)
    return result


def _load_csv(path: str) -> dict:
    """Load supplemental data from CSV.

    CSV columns: city, dimension, score, notes (optional)
    """
    result = {}

    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            city_key = _normalize_key(row.get("city", "").strip())
            dimension = row.get("dimension", "").strip()
            score_str = row.get("score", "").strip()

            if not city_key or not dimension or not score_str:
                continue

            if city_key not in result:
                result[city_key] = {"manual_scores": {}, "data": {}}

            try:
                score = max(-2, min(2, int(score_str)))
                result[city_key]["manual_scores"][dimension] = score
            except ValueError:
                logger.warning("Invalid score '%s' for %s/%s", score_str, city_key, dimension)

    logger.info("Loaded supplements for %d cities from %s", len(result), path)
    return result


def get_city_supplements(
    supplements: dict, city_name: str, state_abbr: str,
) -> dict:
    """Look up supplements for a specific city.

    Tries multiple key formats: "Columbus, OH", "Columbus city, OH", etc.

    Returns:
        dict with "manual_scores" and "data" keys, or empty defaults if not found
    """
    empty = {"manual_scores": {}, "data": {}}

    # Try various key formats
    candidates = [
        _normalize_key(f"{city_name}, {state_abbr}"),
        _normalize_key(f"{city_name.replace(' city', '')}, {state_abbr}"),
        _normalize_key(f"{city_name.replace(' town', '')}, {state_abbr}"),
        _normalize_key(city_name),
    ]

    for key in candidates:
        if key in supplements:
            return supplements[key]

    return empty


def _normalize_key(s: str) -> str:
    """Normalize a city key for matching."""
    return s.strip().lower()
