"""Scoring engine — evaluates a CityDataProfile against the scoring schema."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..ingest.aggregator import CityDataProfile
from .schema import load_schema, list_dimensions

logger = logging.getLogger(__name__)


@dataclass
class DimensionScore:
    name: str
    score: int  # -2 to +2
    indicators: dict[str, float | None] = field(default_factory=dict)
    source: str = "calculated"  # "calculated" or "manual_override"
    confidence: str = "high"  # "high" (API data), "medium" (partial), "low" (manual/proxy)


@dataclass
class ScoredCity:
    profile: CityDataProfile
    dimension_scores: dict[str, DimensionScore] = field(default_factory=dict)
    composite_score: int = 0
    band: str = "Stable"
    scored_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ScoringEngine:
    """Evaluates a CityDataProfile against scoring thresholds."""

    def __init__(self, schema: dict | None = None):
        self.schema = schema or load_schema()

    def score(
        self,
        profile: CityDataProfile,
        manual_scores: dict[str, int] | None = None,
    ) -> ScoredCity:
        """Score a city across all 9 dimensions.

        Args:
            profile: CityDataProfile with data from all sources
            manual_scores: optional dict mapping dimension name to score (-2 to +2)
                           for dimensions without API data or to override calculated scores

        Returns:
            ScoredCity with per-dimension scores, composite, and band
        """
        manual_scores = manual_scores or {}
        result = ScoredCity(profile=profile)

        for dim_name in list_dimensions(self.schema):
            dim_config = self.schema["dimensions"][dim_name]

            # Check for manual override first
            if dim_name in manual_scores:
                score_val = max(-2, min(2, manual_scores[dim_name]))
                result.dimension_scores[dim_name] = DimensionScore(
                    name=dim_name,
                    score=score_val,
                    indicators={},
                    source="manual_override",
                    confidence="low",
                )
                continue

            # Calculate from indicators
            dim_score = self._score_dimension(profile, dim_name, dim_config)
            result.dimension_scores[dim_name] = dim_score

        # Composite score
        result.composite_score = sum(ds.score for ds in result.dimension_scores.values())
        result.band = self._classify_band(result.composite_score)

        return result

    def _score_dimension(
        self, profile: CityDataProfile, dim_name: str, dim_config: dict,
    ) -> DimensionScore:
        """Score a single dimension by evaluating its indicators."""
        indicators = dim_config.get("indicators", {})

        if not indicators:
            # No indicators defined (e.g., public_safety) — score as 0 with low confidence
            return DimensionScore(
                name=dim_name, score=0, indicators={},
                source="calculated", confidence="low",
            )

        indicator_scores = []
        raw_values = {}

        for ind_name, ind_config in indicators.items():
            value = self._resolve_field(profile, ind_config)
            raw_values[ind_name] = value

            if value is None:
                continue

            ind_type = ind_config.get("type", "threshold")

            if ind_type == "categorical":
                score = self._score_categorical(value, ind_config)
            elif ind_type == "ratio":
                score = self._score_ratio(value, ind_config)
            elif ind_type == "deviation":
                score = self._score_deviation(value, ind_config)
            else:
                score = self._score_threshold(value, ind_config)

            if score is not None:
                indicator_scores.append(score)

        if not indicator_scores:
            return DimensionScore(
                name=dim_name, score=0, indicators=raw_values,
                source="calculated", confidence="low",
            )

        avg = sum(indicator_scores) / len(indicator_scores)
        final_score = max(-2, min(2, round(avg)))

        # Determine confidence
        total_indicators = len(indicators)
        scored_count = len(indicator_scores)
        if scored_count == total_indicators:
            confidence = "high"
        elif scored_count >= total_indicators / 2:
            confidence = "medium"
        else:
            confidence = "low"

        # Proxy-based dimensions get medium at best
        if dim_config.get("requires_manual"):
            confidence = min(confidence, "medium", key=["high", "medium", "low"].index)

        return DimensionScore(
            name=dim_name, score=final_score, indicators=raw_values,
            source="calculated", confidence=confidence,
        )

    def _resolve_field(self, profile: CityDataProfile, ind_config: dict) -> float | str | None:
        """Extract the value for an indicator from the profile."""
        source_field = ind_config["source_field"]

        # Handle nested fields like "hazard_scores.tornado"
        if "." in source_field:
            parts = source_field.split(".", 1)
            container = getattr(profile, parts[0], None)
            if isinstance(container, dict):
                value = container.get(parts[1])
            else:
                value = None
        else:
            value = getattr(profile, source_field, None)

        # Try fallback field if primary is None
        if value is None and "fallback_field" in ind_config:
            value = getattr(profile, ind_config["fallback_field"], None)

        return value

    @staticmethod
    def _score_threshold(value: float, ind_config: dict) -> int | None:
        """Score a numeric value against threshold ranges."""
        for t in ind_config.get("thresholds", []):
            t_min = t.get("min")
            t_max = t.get("max")

            if t_min is not None and t_max is not None:
                if t_min <= value < t_max:
                    return t["score"]
            elif t_min is not None:
                if value >= t_min:
                    return t["score"]
            elif t_max is not None:
                if value < t_max:
                    return t["score"]

        return None

    @staticmethod
    def _score_ratio(value: float, ind_config: dict) -> int | None:
        """Score a value as a ratio to a national benchmark."""
        benchmark = ind_config.get("national_benchmark")
        if not benchmark:
            return None
        ratio = value / benchmark

        for t in ind_config.get("thresholds", []):
            t_min = t.get("min_ratio")
            t_max = t.get("max_ratio")

            if t_min is not None and t_max is not None:
                if t_min <= ratio < t_max:
                    return t["score"]
            elif t_min is not None:
                if ratio >= t_min:
                    return t["score"]
            elif t_max is not None:
                if ratio < t_max:
                    return t["score"]

        return None

    @staticmethod
    def _score_deviation(value: float, ind_config: dict) -> int | None:
        """Score a value as deviation from a national benchmark (in pp)."""
        benchmark = ind_config.get("national_benchmark")
        if benchmark is None:
            return None
        dev = value - benchmark

        for t in ind_config.get("thresholds", []):
            t_min = t.get("min_dev")
            t_max = t.get("max_dev")

            if t_min is not None and t_max is not None:
                if t_min <= dev < t_max:
                    return t["score"]
            elif t_min is not None:
                if dev >= t_min:
                    return t["score"]
            elif t_max is not None:
                if dev < t_max:
                    return t["score"]

        return None

    @staticmethod
    def _score_categorical(value, ind_config: dict) -> int | None:
        """Score a categorical value (e.g., risk rating string)."""
        categories = ind_config.get("categories", {})
        if value in categories:
            return categories[value]
        return None

    def _classify_band(self, composite: int) -> str:
        """Map composite score to a classification band."""
        for band in self.schema.get("composite", {}).get("bands", []):
            b_min = band.get("min")
            b_max = band.get("max")

            if b_min is not None and b_max is not None:
                if b_min <= composite <= b_max:
                    return band["label"]
            elif b_min is not None:
                if composite >= b_min:
                    return band["label"]
            elif b_max is not None:
                if composite <= b_max:
                    return band["label"]

        return "Unclassified"
