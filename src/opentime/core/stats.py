from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from opentime.db import queries


@dataclass
class TaskDurationSummary:
    """Summary statistics for a task type's duration."""

    task_type: str
    count: int
    mean_seconds: float
    median_seconds: float
    p95_seconds: float
    min_seconds: float
    max_seconds: float


class DurationStats:
    """Computes duration statistics from paired start/end events."""

    def __init__(self, conn: sqlite3.Connection, agent_id: str) -> None:
        self._conn = conn
        self._agent_id = agent_id

    def get_durations(self, task_type: str) -> list[float]:
        """Get all completed durations for a task type, in seconds."""
        return queries.compute_task_durations(self._conn, self._agent_id, task_type)

    def summarize(self, task_type: str) -> TaskDurationSummary | None:
        """Compute mean, median, p95, min, max for a task type."""
        durations = self.get_durations(task_type)
        if not durations:
            return None
        durations.sort()
        n = len(durations)
        mean = sum(durations) / n
        median = durations[n // 2] if n % 2 == 1 else (durations[n // 2 - 1] + durations[n // 2]) / 2
        p95_idx = min(int(n * 0.95), n - 1)
        return TaskDurationSummary(
            task_type=task_type,
            count=n,
            mean_seconds=round(mean, 3),
            median_seconds=round(median, 3),
            p95_seconds=round(durations[p95_idx], 3),
            min_seconds=round(durations[0], 3),
            max_seconds=round(durations[-1], 3),
        )

    def list_task_types(self) -> list[str]:
        """List all distinct task types that have recorded events."""
        return queries.distinct_task_types(self._conn, self._agent_id)

    def summarize_all(self) -> list[TaskDurationSummary]:
        """Compute summaries for all known task types."""
        results = []
        for tt in self.list_task_types():
            s = self.summarize(tt)
            if s is not None:
                results.append(s)
        return results

    def recommend_timeout(
        self, task_type: str, percentile: float = 0.95, safety_margin: float = 1.2,
    ) -> dict | None:
        """Recommend a timeout for a task type based on historical durations.

        Args:
            task_type: The task type to analyze.
            percentile: Which percentile to base the recommendation on (0.0-1.0).
            safety_margin: Multiplier applied to the percentile value (e.g., 1.2 = 20% buffer).

        Returns:
            Dict with recommendation details, or None if no data.
        """
        durations = self.get_durations(task_type)
        if not durations:
            return None
        durations.sort()
        pval = _percentile(durations, percentile)
        recommended = round(pval * safety_margin, 3)
        return {
            "recommended_seconds": recommended,
            "percentile_value": round(pval, 3),
            "percentile": percentile,
            "safety_margin": safety_margin,
            "sample_count": len(durations),
        }

    def check_timeout_risk(
        self, task_type: str, elapsed_seconds: float, timeout_seconds: float,
    ) -> dict | None:
        """Check if an active task is at risk of exceeding its timeout.

        Args:
            task_type: The task type to compare against.
            elapsed_seconds: How long the task has been running.
            timeout_seconds: The timeout threshold.

        Returns:
            Dict with risk assessment, or None if no historical data.
        """
        durations = self.get_durations(task_type)
        if not durations:
            return None
        durations.sort()
        n = len(durations)
        median = durations[n // 2] if n % 2 == 1 else (durations[n // 2 - 1] + durations[n // 2]) / 2
        p95 = _percentile(durations, 0.95)
        time_remaining = timeout_seconds - elapsed_seconds
        pct_through = round((elapsed_seconds / timeout_seconds) * 100, 1) if timeout_seconds > 0 else 100.0
        # At risk if: elapsed past the median AND remaining time is less than 20% of timeout
        at_risk = elapsed_seconds > median and time_remaining < (timeout_seconds * 0.2)
        return {
            "elapsed_seconds": round(elapsed_seconds, 3),
            "timeout_seconds": round(timeout_seconds, 3),
            "time_remaining": round(time_remaining, 3),
            "median_duration": round(median, 3),
            "p95_duration": round(p95, 3),
            "percent_through_timeout": pct_through,
            "at_risk": at_risk,
            "sample_count": n,
        }


    def compare_approaches(self, approaches: list[dict]) -> dict:
        """Compare multiple approaches using historical duration data.

        Each approach is a dict with "name" and "steps", where each step has
        "task_type" and "estimated_seconds". Steps with historical data get
        their estimates replaced with the actual median duration.

        Returns ranked approaches (fastest first) with adjusted durations.
        """
        # Cache summaries to avoid repeated DB queries
        summary_cache: dict[str, TaskDurationSummary | None] = {}
        results = []

        for approach in approaches:
            steps = []
            total_estimated = 0.0
            total_adjusted = 0.0
            steps_with_data = 0

            for step in approach["steps"]:
                task_type = step["task_type"]
                estimated = step["estimated_seconds"]
                total_estimated += estimated

                if task_type not in summary_cache:
                    summary_cache[task_type] = self.summarize(task_type)

                summary = summary_cache[task_type]
                if summary is not None:
                    adjusted = summary.median_seconds
                    sample_count = summary.count
                    steps_with_data += 1
                else:
                    adjusted = estimated
                    sample_count = 0

                total_adjusted += adjusted
                steps.append({
                    "task_type": task_type,
                    "estimated_seconds": estimated,
                    "adjusted_seconds": round(adjusted, 3),
                    "has_historical_data": summary is not None,
                    "sample_count": sample_count,
                    "confidence": _confidence_level(sample_count),
                })

            step_count = len(approach["steps"])
            results.append({
                "name": approach["name"],
                "steps": steps,
                "total_estimated_seconds": round(total_estimated, 3),
                "total_adjusted_seconds": round(total_adjusted, 3),
                "adjustment_coverage": round(steps_with_data / step_count, 3) if step_count > 0 else 0.0,
            })

        # Sort by total_adjusted_seconds (fastest first)
        results.sort(key=lambda r: r["total_adjusted_seconds"])

        fastest = results[0]["total_adjusted_seconds"] if results else 0
        slowest = results[-1]["total_adjusted_seconds"] if results else 0

        return {
            "approaches": results,
            "recommendation": results[0]["name"] if results else None,
            "savings_vs_worst": round(slowest - fastest, 3),
        }


def _percentile(sorted_data: list[float], p: float) -> float:
    """Compute the p-th percentile of sorted data (0.0-1.0)."""
    n = len(sorted_data)
    idx = min(int(n * p), n - 1)
    return sorted_data[idx]


def _confidence_level(sample_count: int) -> str:
    """Map sample count to a confidence level label."""
    if sample_count == 0:
        return "none"
    if sample_count < 5:
        return "low"
    if sample_count < 20:
        return "medium"
    return "high"
