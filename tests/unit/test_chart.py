"""Unit tests for the heuristic chart recommender."""

from __future__ import annotations

from backend.agents.chart import HeuristicChartRecommender
from backend.models.schemas import ChartType


def make_recommender():
    """Return a fresh recommender instance."""
    return HeuristicChartRecommender()


class TestChartRecommendation:
    """Chart specs must match the shape of the result data."""

    def test_empty_results_no_charts(self):
        recommender = make_recommender()
        assert recommender.recommend([], []) == []

    def test_category_plus_numeric_yields_bar_and_table(self):
        recommender = make_recommender()
        rows = [
            {"product": "Laptop", "revenue": 420000},
            {"product": "Mouse", "revenue": 65000},
        ]
        specs = recommender.recommend(["product", "revenue"], rows)
        types = {s.recommended_type for s in specs}
        assert ChartType.BAR in types
        assert ChartType.TABLE in types

    def test_date_column_yields_line_chart(self):
        recommender = make_recommender()
        rows = [
            {"day": "2026-06-01", "sales": 100},
            {"day": "2026-06-02", "sales": 150},
        ]
        specs = recommender.recommend(["day", "sales"], rows)
        types = {s.recommended_type for s in specs}
        assert ChartType.LINE in types

    def test_small_category_set_yields_pie(self):
        recommender = make_recommender()
        rows = [
            {"country": "India", "count": 40},
            {"country": "USA", "count": 30},
            {"country": "UK", "count": 20},
        ]
        specs = recommender.recommend(["country", "count"], rows, max_charts=3)
        types = {s.recommended_type for s in specs}
        assert ChartType.PIE in types

    def test_vega_lite_spec_is_serializable(self):
        recommender = make_recommender()
        rows = [{"product": "Laptop", "revenue": 420000}]
        specs = recommender.recommend(["product", "revenue"], rows)
        for spec in specs:
            payload = spec.model_dump(mode="json")
            assert isinstance(payload, dict)
            assert "vega_lite" in payload
