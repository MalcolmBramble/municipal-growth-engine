"""Tests for supplemental data loader."""

import json
import os
import tempfile

import pytest

from src.scoring.supplements import load_supplements, get_city_supplements


class TestLoadSupplementsJSON:
    """Test loading supplements from JSON files."""

    def test_load_json(self):
        data = {
            "Columbus, OH": {
                "manual_scores": {"public_safety": 1, "fiscal_health": 0},
                "data": {"graduation_rate": 85.2, "bond_rating": "AA"},
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name

        try:
            result = load_supplements(path)
            assert "columbus, oh" in result
            entry = result["columbus, oh"]
            assert entry["manual_scores"]["public_safety"] == 1
            assert entry["manual_scores"]["fiscal_health"] == 0
            assert entry["data"]["graduation_rate"] == 85.2
        finally:
            os.unlink(path)

    def test_clamps_scores(self):
        data = {
            "Test City, TX": {
                "manual_scores": {"public_safety": 5, "fiscal_health": -5},
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name

        try:
            result = load_supplements(path)
            entry = result["test city, tx"]
            assert entry["manual_scores"]["public_safety"] == 2
            assert entry["manual_scores"]["fiscal_health"] == -2
        finally:
            os.unlink(path)

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_supplements("/nonexistent/path.json")

    def test_unsupported_format_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            path = f.name
        try:
            with pytest.raises(ValueError, match="Unsupported supplements format"):
                load_supplements(path)
        finally:
            os.unlink(path)


class TestLoadSupplementsCSV:
    """Test loading supplements from CSV files."""

    def test_load_csv(self):
        csv_content = (
            "city,dimension,score,notes\n"
            '"Columbus, OH",public_safety,1,"Low crime"\n'
            '"Columbus, OH",fiscal_health,-1,"Budget issues"\n'
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            path = f.name

        try:
            result = load_supplements(path)
            assert "columbus, oh" in result
            entry = result["columbus, oh"]
            assert entry["manual_scores"]["public_safety"] == 1
            assert entry["manual_scores"]["fiscal_health"] == -1
        finally:
            os.unlink(path)

    def test_csv_skips_invalid_scores(self):
        csv_content = (
            "city,dimension,score,notes\n"
            '"Test, TX",public_safety,abc,"bad score"\n'
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            path = f.name

        try:
            result = load_supplements(path)
            entry = result.get("test, tx", {"manual_scores": {}})
            assert "public_safety" not in entry["manual_scores"]
        finally:
            os.unlink(path)

    def test_csv_skips_empty_rows(self):
        csv_content = (
            "city,dimension,score,notes\n"
            ",public_safety,1,\n"
            '"Test, TX",,1,\n'
            '"Test, TX",public_safety,,\n'
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            path = f.name

        try:
            result = load_supplements(path)
            assert len(result) == 0
        finally:
            os.unlink(path)


class TestGetCitySupplements:
    """Test city supplement lookup."""

    def test_exact_match(self):
        supplements = {
            "columbus, oh": {
                "manual_scores": {"public_safety": 1},
                "data": {},
            }
        }
        result = get_city_supplements(supplements, "Columbus", "OH")
        assert result["manual_scores"]["public_safety"] == 1

    def test_city_suffix_stripped(self):
        supplements = {
            "columbus, oh": {
                "manual_scores": {"fiscal_health": 0},
                "data": {},
            }
        }
        result = get_city_supplements(supplements, "Columbus city", "OH")
        assert result["manual_scores"]["fiscal_health"] == 0

    def test_not_found_returns_empty(self):
        supplements = {}
        result = get_city_supplements(supplements, "Nowhere", "XX")
        assert result == {"manual_scores": {}, "data": {}}

    def test_town_suffix_stripped(self):
        supplements = {
            "hempstead, ny": {
                "manual_scores": {"education": -1},
                "data": {},
            }
        }
        result = get_city_supplements(supplements, "Hempstead town", "NY")
        assert result["manual_scores"]["education"] == -1
