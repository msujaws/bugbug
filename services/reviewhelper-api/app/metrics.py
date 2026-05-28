"""Metrics aggregations for the automated-review dashboard.

Operates on ``ReviewRequest`` rows (anything exposing the same attributes), so
the SQL stays in the router and the analytics are easy to unit-test. Token
usage and model names are read from the ``details`` JSON written by the review
pipeline; risk/complexity/skip data come from the typed columns.

The time-saved model is ported from qreviews: a nonlinear per-axis estimate of
the human review time an automated review displaces.
"""

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from statistics import median
from typing import Iterable

from app.enums import ReviewStatus
from app.pricing import estimate_cost_usd


# Hours a human reviewer would otherwise spend per score axis. Nonlinear
# (power 1.8) so high-risk/high-complexity revisions save disproportionately
# more time than trivial ones.
#   s=0 -> 0.10h   s=3 -> 0.46h   s=7 -> 2.13h   s=10 -> 3.66h
def _axis_hours(score: int | None) -> float:
    if score is None:
        return 0.0
    return 0.1 + 0.05 * (max(0, int(score)) ** 1.8)


def _usage_cost(model: str, usage: dict) -> float:
    return estimate_cost_usd(
        model or "",
        input_tokens=usage.get("input_tokens", 0) or 0,
        output_tokens=usage.get("output_tokens", 0) or 0,
        cache_read=usage.get("cache_read_input_tokens", 0) or 0,
        cache_write=usage.get("cache_creation_input_tokens", 0) or 0,
    )


def request_cost(req) -> float:
    """Estimated USD cost of the scoring + review LLM calls for one request."""
    details = req.details or {}
    return _usage_cost(
        details.get("scoring_model", ""), details.get("scoring_usage") or {}
    ) + _usage_cost(details.get("model", ""), details.get("usage") or {})


def _tokens(req) -> dict[str, int]:
    details = req.details or {}
    out: dict[str, int] = defaultdict(int)
    for key in ("scoring_usage", "usage"):
        usage = details.get(key) or {}
        for field_name in (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        ):
            out[field_name] += usage.get(field_name, 0) or 0
    return dict(out)


def _was_reviewed(req) -> bool:
    return req.status == ReviewStatus.PUBLISHED


@dataclass
class Summary:
    group_slug: str | None = None
    requests: int = 0
    scored: int = 0
    reviewed: int = 0
    skipped: int = 0
    failed: int = 0
    coverage_pct: float = 0.0
    skipped_by_reason: dict[str, int] = field(default_factory=dict)
    median_risk: float | None = None
    median_complexity: float | None = None
    median_time_to_review_seconds: float | None = None
    estimated_cost_usd: float = 0.0
    time_saved_hours: float = 0.0
    tokens: dict[str, int] = field(default_factory=dict)
    feedback: dict[str, int] = field(default_factory=lambda: {"up": 0, "down": 0})

    def to_dict(self) -> dict:
        return asdict(self)


def compute_summary(
    requests: Iterable,
    *,
    group_slug: str | None = None,
    feedback_counts: dict[str, int] | None = None,
) -> Summary:
    total = 0
    scored = 0
    reviewed = 0
    skipped = 0
    failed = 0
    risks: list[int] = []
    complexities: list[int] = []
    time_to_review: list[float] = []
    tok: dict[str, int] = defaultdict(int)
    total_cost = 0.0
    total_time_saved = 0.0
    skipped_by_reason: dict[str, int] = defaultdict(int)

    for req in requests:
        total += 1
        if req.risk is not None:
            scored += 1
            risks.append(req.risk)
        if req.complexity is not None:
            complexities.append(req.complexity)

        if _was_reviewed(req):
            reviewed += 1
            if req.created_at and req.updated_at:
                time_to_review.append((req.updated_at - req.created_at).total_seconds())
            total_time_saved += _axis_hours(req.risk) + _axis_hours(req.complexity)
        elif req.status == ReviewStatus.SKIPPED:
            skipped += 1
            skipped_by_reason[req.skipped_reason or "unknown"] += 1
        elif req.status == ReviewStatus.FAILED:
            failed += 1

        for key, value in _tokens(req).items():
            tok[key] += value
        total_cost += request_cost(req)

    coverage = (reviewed / total * 100.0) if total else 0.0

    return Summary(
        group_slug=group_slug,
        requests=total,
        scored=scored,
        reviewed=reviewed,
        skipped=skipped,
        failed=failed,
        coverage_pct=round(coverage, 1),
        skipped_by_reason=dict(skipped_by_reason),
        median_risk=float(median(risks)) if risks else None,
        median_complexity=float(median(complexities)) if complexities else None,
        median_time_to_review_seconds=(
            float(median(time_to_review)) if time_to_review else None
        ),
        estimated_cost_usd=round(total_cost, 4),
        time_saved_hours=round(total_time_saved, 2),
        tokens=dict(tok),
        feedback=feedback_counts or {"up": 0, "down": 0},
    )


def score_histograms(requests: Iterable) -> dict[str, list[int]]:
    """Counts of revisions at each 0-10 risk and complexity score."""
    risk_buckets = [0] * 11
    complexity_buckets = [0] * 11
    for req in requests:
        if isinstance(req.risk, int) and 0 <= req.risk <= 10:
            risk_buckets[req.risk] += 1
        if isinstance(req.complexity, int) and 0 <= req.complexity <= 10:
            complexity_buckets[req.complexity] += 1
    return {"risk": risk_buckets, "complexity": complexity_buckets}


def daily_throughput(requests: Iterable, *, days: int = 30) -> list[dict]:
    """[{date, requests, reviewed, skipped, cost_usd}, ...] bucketed by day."""
    buckets: dict[str, dict[str, float]] = {}
    for req in requests:
        created = req.created_at
        if not created:
            continue
        day = created.strftime("%Y-%m-%d")
        bucket = buckets.setdefault(
            day, {"requests": 0, "reviewed": 0, "skipped": 0, "cost_usd": 0.0}
        )
        bucket["requests"] += 1
        if _was_reviewed(req):
            bucket["reviewed"] += 1
        elif req.status == ReviewStatus.SKIPPED:
            bucket["skipped"] += 1
        bucket["cost_usd"] += request_cost(req)

    out = [
        {
            "date": day,
            "requests": int(v["requests"]),
            "reviewed": int(v["reviewed"]),
            "skipped": int(v["skipped"]),
            "cost_usd": round(v["cost_usd"], 4),
        }
        for day, v in sorted(buckets.items())
    ]
    return out[-days:] if days else out


def request_to_detail(req) -> dict:
    """Serialize one request for the dashboard's detail view."""
    details = req.details or {}
    return {
        "id": req.id,
        "revision_id": req.revision_id,
        "diff_id": req.diff_id,
        "status": req.status.value
        if isinstance(req.status, ReviewStatus)
        else req.status,
        "created_at": _iso(req.created_at),
        "updated_at": _iso(req.updated_at),
        "risk": req.risk,
        "complexity": req.complexity,
        "risk_factors": details.get("risk_factors", []),
        "complexity_factors": details.get("complexity_factors", []),
        "in_diff_test_signal": req.in_diff_test_signal,
        "coverage_signal": req.coverage_signal,
        "skipped_reason": req.skipped_reason,
        "group": (details.get("thresholds") or {}).get("group"),
        "summary": req.summary,
        "tokens": _tokens(req),
        "estimated_cost_usd": round(request_cost(req), 4),
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
