"""Loads and validates the scoring schema from config/scoring_schema.json."""

import json
import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "scoring_schema.json"
)


def load_schema(path: str | None = None) -> dict:
    """Load and return the scoring schema.

    Args:
        path: optional override path to the JSON file

    Returns:
        Parsed schema dict with 'dimensions' and 'composite' keys
    """
    schema_path = path or DEFAULT_SCHEMA_PATH
    if not os.path.exists(schema_path):
        raise FileNotFoundError(f"Scoring schema not found at {schema_path}")

    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)

    if "dimensions" not in schema:
        raise ValueError("Schema missing 'dimensions' key")
    if "composite" not in schema:
        raise ValueError("Schema missing 'composite' key")

    logger.info("Loaded scoring schema with %d dimensions", len(schema["dimensions"]))
    return schema


def get_dimension_config(dimension_name: str, schema: dict | None = None) -> dict:
    """Return the configuration for a single dimension.

    Args:
        dimension_name: e.g. "population_demographics"
        schema: pre-loaded schema dict, or None to load from disk

    Returns:
        dict with keys: label, weight, indicators, and optionally requires_manual
    """
    if schema is None:
        schema = load_schema()
    dims = schema["dimensions"]
    if dimension_name not in dims:
        raise KeyError(f"Unknown dimension: '{dimension_name}'")
    return dims[dimension_name]


def list_dimensions(schema: dict | None = None) -> list[str]:
    """Return all dimension names in schema order."""
    if schema is None:
        schema = load_schema()
    return list(schema["dimensions"].keys())
