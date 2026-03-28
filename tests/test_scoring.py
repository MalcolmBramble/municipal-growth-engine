"""Tests for the scoring engine."""

import pytest

from src.ingest.aggregator import CityDataProfile
from src.scoring.engine import ScoringEngine, DimensionScore, ScoredCity
from src.scoring.schema import load_schema, list_dimensions, get_dimension_config


# ── Schema tests ─────────────────────────────────────────────────────────────

class TestSchema:
    def test_load_schema(self):
        schema = load_schema()
        assert "dimensions" in schema
        assert "composite" in schema

    def test_list_dimensions_returns_nine(self):
        dims = list_dimensions()
        assert len(dims) == 9
        assert "population_demographics" in dims
        assert "public_safety" in dims

    def test_get_dimension_config(self):
        config = get_dimension_config("population_demographics")
        assert config["label"] == "Population & Demographics"
        assert "indicators" in config
        assert "poverty_rate" in config["indicators"]

    def test_get_unknown_dimension_raises(self):
        with pytest.raises(KeyError, match="Unknown dimension"):
            get_dimension_config("nonexistent_dimension")


# ── Threshold scoring tests ─────────────────────────────────────────────────

class TestThresholdScoring:
    def setup_method(self):
        self.engine = ScoringEngine()

    def test_poverty_rate_low_scores_positive(self):
        profile = _make_profile(poverty_rate=8.0)
        result = self.engine.score(profile)
        # poverty_rate < 10 → +2 in both population_demographics and quality_of_life
        pop_score = result.dimension_scores["population_demographics"]
        assert pop_score.indicators["poverty_rate"] == 8.0

    def test_poverty_rate_high_scores_negative(self):
        profile = _make_profile(poverty_rate=25.0)
        result = self.engine.score(profile)
        pop_score = result.dimension_scores["population_demographics"]
        assert pop_score.score <= -1

    def test_unemployment_rate_scoring(self):
        profile = _make_profile(unemployment_rate=3.0)
        result = self.engine.score(profile)
        econ_score = result.dimension_scores["economic_base"]
        assert econ_score.indicators["unemployment_rate"] == 3.0

    def test_walk_score_high(self):
        profile = _make_profile(walk_score=85, transit_score=75)
        result = self.engine.score(profile)
        infra = result.dimension_scores["infrastructure"]
        assert infra.score == 2

    def test_walk_score_low(self):
        profile = _make_profile(walk_score=25, transit_score=10)
        result = self.engine.score(profile)
        infra = result.dimension_scores["infrastructure"]
        assert infra.score == -2


class TestCategoricalScoring:
    def setup_method(self):
        self.engine = ScoringEngine()

    def test_risk_rating_very_low(self):
        profile = _make_profile(risk_rating="Very Low", hazard_scores={
            "tornado": "Very Low", "hurricane": "Very Low",
            "flood": "Very Low", "heat_wave": "Very Low",
        })
        result = self.engine.score(profile)
        climate = result.dimension_scores["climate_environment"]
        assert climate.score == 2

    def test_risk_rating_very_high(self):
        profile = _make_profile(risk_rating="Very High", hazard_scores={
            "tornado": "Very High", "hurricane": "Very High",
            "flood": "Very High", "heat_wave": "Very High",
        })
        result = self.engine.score(profile)
        climate = result.dimension_scores["climate_environment"]
        assert climate.score == -2


class TestManualOverrides:
    def setup_method(self):
        self.engine = ScoringEngine()

    def test_manual_override_replaces_calculated(self):
        profile = _make_profile()
        result = self.engine.score(profile, manual_scores={"public_safety": 1})
        ps = result.dimension_scores["public_safety"]
        assert ps.score == 1
        assert ps.source == "manual_override"
        assert ps.confidence == "low"

    def test_manual_override_clamped(self):
        profile = _make_profile()
        result = self.engine.score(profile, manual_scores={"public_safety": 5})
        assert result.dimension_scores["public_safety"].score == 2

    def test_manual_override_negative(self):
        profile = _make_profile()
        result = self.engine.score(profile, manual_scores={"fiscal_health": -2})
        assert result.dimension_scores["fiscal_health"].score == -2
        assert result.dimension_scores["fiscal_health"].source == "manual_override"


class TestCompositeBands:
    def setup_method(self):
        self.engine = ScoringEngine()

    def test_band_severe_decline(self):
        assert self.engine._classify_band(-10) == "Severe Decline"

    def test_band_declining(self):
        assert self.engine._classify_band(-5) == "Declining"

    def test_band_stable(self):
        assert self.engine._classify_band(0) == "Stable"

    def test_band_growing(self):
        assert self.engine._classify_band(6) == "Growing"

    def test_band_rapid_growth(self):
        assert self.engine._classify_band(12) == "Rapid Growth"


# ── Full city profile tests ──────────────────────────────────────────────────

class TestColumbus:
    """Columbus OH should score approximately +5 to +7 with manual overrides."""

    def test_columbus_profile(self):
        profile = _make_columbus()
        engine = ScoringEngine()
        result = engine.score(profile, manual_scores={
            "public_safety": 1,
            "fiscal_health": 1,
        })

        _print_breakdown("COLUMBUS, OH", result)

        assert 3 <= result.composite_score <= 9, (
            f"Columbus composite {result.composite_score} outside expected range 3-9"
        )
        assert result.band in ("Stable", "Growing")


class TestDetroit:
    """Detroit with max-negative manual overrides should score deeply negative.

    With poverty at 34.5%, unemployment at 9.7%, income at $39K, and manual
    -2 for public_safety and fiscal_health, Detroit is genuinely severe.
    """

    def test_detroit_profile(self):
        profile = _make_detroit()
        engine = ScoringEngine()
        result = engine.score(profile, manual_scores={
            "public_safety": -2,
            "fiscal_health": -2,
        })

        _print_breakdown("DETROIT, MI", result)

        assert -14 <= result.composite_score <= -6, (
            f"Detroit composite {result.composite_score} outside expected range -14 to -6"
        )
        assert result.band in ("Severe Decline", "Declining")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_profile(**kwargs) -> CityDataProfile:
    """Create a minimal profile with optional overrides."""
    defaults = {
        "city_name": "Test City",
        "state_abbr": "OH",
        "state_fips": "39",
        "place_fips": "00000",
    }
    defaults.update(kwargs)
    return CityDataProfile(**defaults)


def _make_columbus() -> CityDataProfile:
    return CityDataProfile(
        city_name="Columbus city",
        state_abbr="OH",
        state_fips="39",
        place_fips="18000",
        population=946000,
        median_income=66082,
        poverty_rate=18.13,
        bachelors_plus_pct=38.2,
        unemployment_rate=3.7,
        unemployment_trend=-0.5,
        walk_score=41,
        transit_score=27,
        median_sale_price=300000,
        price_yoy_change=5.2,
        zhvi=270000,
        zhvi_yoy_change=6.1,
        risk_rating="Relatively Low",
        risk_score=8.5,
        hazard_scores={
            "tornado": "Relatively Moderate",
            "hurricane": "Very Low",
            "flood": "Relatively Low",
            "heat_wave": "Relatively Low",
        },
    )


def _make_detroit() -> CityDataProfile:
    return CityDataProfile(
        city_name="Detroit city",
        state_abbr="MI",
        state_fips="26",
        place_fips="22000",
        population=633218,
        median_income=39209,
        poverty_rate=34.5,
        bachelors_plus_pct=16.8,
        unemployment_rate=9.7,
        unemployment_trend=0.8,
        walk_score=55,
        transit_score=42,
        median_sale_price=85000,
        price_yoy_change=-2.1,
        zhvi=72000,
        zhvi_yoy_change=-1.5,
        risk_rating="Relatively Moderate",
        risk_score=14.0,
        hazard_scores={
            "tornado": "Relatively Low",
            "hurricane": "Very Low",
            "flood": "Relatively Low",
            "heat_wave": "Relatively Moderate",
        },
    )


def _print_breakdown(label: str, result: ScoredCity) -> None:
    """Print a full scoring breakdown for visual validation."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  Composite: {result.composite_score} — Band: {result.band}")
    print(f"{'='*60}")
    for dim_name, ds in result.dimension_scores.items():
        score_bar = "+" * max(0, ds.score) + "-" * max(0, -ds.score)
        print(f"  {dim_name:.<35} {ds.score:+d}  [{ds.confidence}] ({ds.source})")
        for ind_name, ind_val in ds.indicators.items():
            print(f"    {ind_name}: {ind_val}")
    print()
