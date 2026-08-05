"""Chart recommender: heuristically generates Vega-Lite chart specs.

Given tabular results, inspects column types and data shape to recommend
appropriate visualizations (bar, line, pie, table). Emits framework-agnostic
Vega-Lite JSON so any frontend can render the charts.
"""

from __future__ import annotations

from typing import Any

from backend.core.logging import get_logger
from backend.models.schemas import ChartSpec, ChartType

logger = get_logger(__name__)


class HeuristicChartRecommender:
    """Recommends charts from result shape using simple heuristics."""

    def recommend(
        self,
        columns: list[str],
        rows: list[dict[str, Any]],
        *,
        question: str = "",
        max_charts: int = 2,
    ) -> list[ChartSpec]:
        """Generate chart specs for a result set.

        Rules of thumb:
        * A dimension + a numeric measure -> bar chart (top N).
        * A date/time dimension + numeric measure -> line chart.
        * Small categorical sets with a share measure -> pie chart.
        * Anything else -> a table spec.

        Args:
            columns: Result column names.
            rows: Result rows.
            question: Original question (used for titles).
            max_charts: Maximum number of charts to emit.

        Returns:
            List of Vega-Lite chart specifications.
        """
        if not rows or not columns:
            return []

        specs: list[ChartSpec] = []
        numeric_cols = self._numeric_columns(columns, rows)
        date_cols = self._date_columns(columns, rows)
        categorical_cols = [c for c in columns if c not in numeric_cols and c not in date_cols]

        # 1. Line chart when a date column + numeric measure exist.
        if date_cols and numeric_cols and len(specs) < max_charts:
            specs.append(
                ChartSpec(
                    recommended_type=ChartType.LINE,
                    title=self._title("Trend", question),
                    rationale="A date dimension with a numeric measure suggests a time series.",
                    vega_lite={
                        "mark": {"type": "line", "point": True},
                        "encoding": {
                            "x": {"field": date_cols[0], "type": "temporal"},
                            "y": {"field": numeric_cols[0], "type": "quantitative"},
                        },
                    },
                )
            )

        # 2. Bar chart for a category + numeric measure.
        if categorical_cols and numeric_cols and len(specs) < max_charts:
            specs.append(
                ChartSpec(
                    recommended_type=ChartType.BAR,
                    title=self._title("Comparison", question),
                    rationale="A categorical dimension with a numeric measure is well shown as bars.",
                    vega_lite={
                        "mark": {"type": "bar"},
                        "encoding": {
                            "x": {"field": categorical_cols[0], "type": "nominal", "sort": "-y"},
                            "y": {"field": numeric_cols[0], "type": "quantitative"},
                        },
                    },
                )
            )

        # 3. Pie chart for a small set of categories with a measure.
        if categorical_cols and numeric_cols and len(rows) <= 8 and len(specs) < max_charts:
            specs.append(
                ChartSpec(
                    recommended_type=ChartType.PIE,
                    title=self._title("Share", question),
                    rationale="Few categories with a share-like measure are suited to a pie chart.",
                    vega_lite={
                        "mark": {"type": "arc"},
                        "encoding": {
                            "theta": {"field": numeric_cols[0], "type": "quantitative"},
                            "color": {"field": categorical_cols[0], "type": "nominal"},
                        },
                    },
                )
            )

        # 4. Always include a table spec as the baseline view.
        specs.append(
            ChartSpec(
                recommended_type=ChartType.TABLE,
                title="Data table",
                rationale="The raw result rows as a table.",
                vega_lite={},
            )
        )
        return specs

    @staticmethod
    def _numeric_columns(columns: list[str], rows: list[dict[str, Any]]) -> list[str]:
        """Return columns whose values look numeric.

        Args:
            columns: Column names.
            rows: Sample rows.

        Returns:
            List of numeric column names.
        """
        numeric = []
        for col in columns:
            values = [r.get(col) for r in rows[:10] if r.get(col) is not None]
            if values and all(isinstance(v, (int, float)) for v in values):
                numeric.append(col)
        return numeric

    @staticmethod
    def _date_columns(columns: list[str], rows: list[dict[str, Any]]) -> list[str]:
        """Return columns whose values look like ISO dates/timestamps.

        Args:
            columns: Column names.
            rows: Sample rows.

        Returns:
            List of date-like column names.
        """
        import re

        date_pattern = re.compile(
            r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$"
        )
        result = []
        for col in columns:
            values = [r.get(col) for r in rows[:10] if r.get(col) is not None]
            if values and all(isinstance(v, str) and date_pattern.match(v) for v in values):
                result.append(col)
        return result

    @staticmethod
    def _title(fallback: str, question: str) -> str:
        """Build a chart title from the question or a fallback.

        Args:
            fallback: Default title when the question is empty.
            question: The original user question.

        Returns:
            A title string.
        """
        if question:
            return question[:80]
        return fallback
