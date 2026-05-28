"""Read-only metrics API backing the automated-review dashboard.

Surfaces cost, benefit, and adoption metrics over the review_requests the
service has processed, plus thumbs-up/down feedback. Guarded by the dashboard
API key.
"""

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_dashboard_api_key
from app.database.connection import get_db
from app.database.models import Feedback, ReviewRequest
from app.enums import FeedbackType, Platform
from app.metrics import (
    compute_summary,
    daily_throughput,
    request_to_detail,
    score_histograms,
)
from app.reviewer_groups import get_reviewer_groups_config

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["dashboard"],
    dependencies=[Depends(verify_dashboard_api_key)],
)


def _group_of(req: ReviewRequest) -> Optional[str]:
    return ((req.details or {}).get("thresholds") or {}).get("group")


async def _load_requests(db: AsyncSession, group: Optional[str]) -> list[ReviewRequest]:
    stmt = (
        select(ReviewRequest)
        .where(ReviewRequest.platform == Platform.PHABRICATOR)
        .order_by(ReviewRequest.created_at.desc())
    )
    requests = list(await db.scalars(stmt))
    if group:
        requests = [r for r in requests if _group_of(r) == group]
    return requests


async def _feedback_counts(db: AsyncSession) -> dict[str, int]:
    stmt = select(Feedback.feedback_type, func.count()).group_by(Feedback.feedback_type)
    counts = {"up": 0, "down": 0}
    for feedback_type, count in await db.execute(stmt):
        if feedback_type == FeedbackType.UP:
            counts["up"] = count
        elif feedback_type == FeedbackType.DOWN:
            counts["down"] = count
    return counts


@router.get("/summary")
async def api_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    group: Optional[str] = None,
):
    requests = await _load_requests(db, group)
    feedback = await _feedback_counts(db)
    summary = compute_summary(requests, group_slug=group, feedback_counts=feedback)
    return JSONResponse(summary.to_dict())


@router.get("/histograms")
async def api_histograms(
    db: Annotated[AsyncSession, Depends(get_db)],
    group: Optional[str] = None,
):
    requests = await _load_requests(db, group)
    return JSONResponse(score_histograms(requests))


@router.get("/timeseries")
async def api_timeseries(
    db: Annotated[AsyncSession, Depends(get_db)],
    group: Optional[str] = None,
    days: int = 30,
):
    requests = await _load_requests(db, group)
    return JSONResponse(daily_throughput(requests, days=days))


@router.get("/revisions")
async def api_revisions(
    db: Annotated[AsyncSession, Depends(get_db)],
    group: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    requests = await _load_requests(db, group)
    page = requests[offset : offset + limit]
    return JSONResponse(
        {"total": len(requests), "items": [request_to_detail(r) for r in page]}
    )


@router.get("/revision/{review_request_id}")
async def api_revision(
    review_request_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    req = await db.get(ReviewRequest, review_request_id)
    if req is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(request_to_detail(req))


@router.get("/groups")
async def api_groups():
    config = get_reviewer_groups_config()
    return JSONResponse(
        [
            {
                "slug": group.slug,
                "enabled": group.enabled,
                "risk_threshold": group.effective_risk_threshold(config.defaults),
                "complexity_threshold": group.effective_complexity_threshold(
                    config.defaults
                ),
                "restrict_to_member_authors": group.restrict_to_member_authors,
                "has_skill": group.skill is not None,
            }
            for group in config.groups
        ]
    )
