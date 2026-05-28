from datetime import datetime, timedelta
from types import SimpleNamespace

from app.enums import ReviewStatus
from app.metrics import (
    compute_summary,
    daily_throughput,
    request_cost,
    request_to_detail,
    score_histograms,
)

BASE = datetime(2026, 5, 1, 12, 0, 0)


def _req(
    *,
    status,
    risk=None,
    complexity=None,
    skipped_reason=None,
    details=None,
    minutes=5,
    created=BASE,
    rid=1,
):
    return SimpleNamespace(
        id=rid,
        revision_id=1000 + rid,
        diff_id=2000 + rid,
        status=status,
        risk=risk,
        complexity=complexity,
        skipped_reason=skipped_reason,
        in_diff_test_signal="absent",
        coverage_signal="uncovered",
        summary="A summary",
        created_at=created,
        updated_at=created + timedelta(minutes=minutes),
        details=details or {},
    )


def test_request_cost_sums_scoring_and_review():
    req = _req(
        status=ReviewStatus.PUBLISHED,
        details={
            "scoring_model": "claude-haiku-4-5",
            "scoring_usage": {"input_tokens": 1_000_000, "output_tokens": 0},
            "model": "claude-opus-4-6",
            "usage": {"input_tokens": 1_000_000, "output_tokens": 0},
        },
    )
    # 1M Haiku input ($1) + 1M Opus input ($15) = $16.
    assert round(request_cost(req), 2) == 16.0


def test_compute_summary_counts_and_coverage():
    requests = [
        _req(status=ReviewStatus.PUBLISHED, risk=1, complexity=2, rid=1),
        _req(
            status=ReviewStatus.SKIPPED,
            risk=5,
            complexity=1,
            skipped_reason="above_threshold",
            rid=2,
        ),
        _req(
            status=ReviewStatus.SKIPPED,
            skipped_reason="not_enabled",
            rid=3,
        ),
        _req(status=ReviewStatus.FAILED, rid=4),
    ]
    summary = compute_summary(requests, feedback_counts={"up": 3, "down": 1})
    assert summary.requests == 4
    assert summary.reviewed == 1
    assert summary.skipped == 2
    assert summary.failed == 1
    assert summary.coverage_pct == 25.0
    assert summary.skipped_by_reason == {"above_threshold": 1, "not_enabled": 1}
    assert summary.median_risk == 3.0  # median of [1, 5]
    assert summary.feedback == {"up": 3, "down": 1}
    # Only the reviewed revision contributes time saved.
    assert summary.time_saved_hours > 0


def test_score_histograms():
    requests = [
        _req(status=ReviewStatus.PUBLISHED, risk=0, complexity=10, rid=1),
        _req(status=ReviewStatus.PUBLISHED, risk=0, complexity=3, rid=2),
    ]
    hist = score_histograms(requests)
    assert hist["risk"][0] == 2
    assert hist["complexity"][10] == 1
    assert hist["complexity"][3] == 1


def test_daily_throughput_buckets_by_day():
    day1 = datetime(2026, 5, 1, 9, 0, 0)
    day2 = datetime(2026, 5, 2, 9, 0, 0)
    requests = [
        _req(status=ReviewStatus.PUBLISHED, risk=1, complexity=1, created=day1, rid=1),
        _req(
            status=ReviewStatus.SKIPPED,
            skipped_reason="above_threshold",
            created=day1,
            rid=2,
        ),
        _req(status=ReviewStatus.PUBLISHED, risk=1, complexity=1, created=day2, rid=3),
    ]
    series = daily_throughput(requests)
    assert series == [
        {
            "date": "2026-05-01",
            "requests": 2,
            "reviewed": 1,
            "skipped": 1,
            "cost_usd": 0.0,
        },
        {
            "date": "2026-05-02",
            "requests": 1,
            "reviewed": 1,
            "skipped": 0,
            "cost_usd": 0.0,
        },
    ]


def test_request_to_detail_shape():
    req = _req(
        status=ReviewStatus.SKIPPED,
        risk=5,
        complexity=1,
        skipped_reason="above_threshold",
        details={
            "risk_factors": ["touches IPC"],
            "thresholds": {"group": "ip-protection-reviewers"},
        },
    )
    detail = request_to_detail(req)
    assert detail["status"] == "skipped"
    assert detail["risk"] == 5
    assert detail["skipped_reason"] == "above_threshold"
    assert detail["group"] == "ip-protection-reviewers"
    assert detail["risk_factors"] == ["touches IPC"]
    assert detail["created_at"].startswith("2026-05-01")
