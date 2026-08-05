"""Chart recommendation interface."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from backend.models.schemas import ChartSpec


@runtime_checkable
class ChartRecommender(Protocol):
    """Protocol for recommending charts based on tabular query results."""

    def recommend(
        self,
        columns: list[str],
        rows: list[dict[str, Any]],
        *,
        question: str = "",
        max_charts: int = 2,
    ) -> list[ChartSpec]:
        """Generate chart recommendations for a result set.

        Args:
            columns: Result column names.
            rows: Result rows as dicts.
            question: The original user question (for contextual titles).
            max_charts: Maximum number of chart specs to return.

        Returns:
            A list of Vega-Lite chart specifications.
        """
        ...
