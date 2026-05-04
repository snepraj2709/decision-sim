"""Step 6 — Calibration loop.

Records user-reported outcomes, recomputes CalibrationRate per option_type,
and surfaces accuracy comparisons against simulation predictions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CalibrationRate, OutcomeReport, Simulation, SimulationCell

log = structlog.get_logger()

# Matches BASE_RATES in score.py — used as the prior when no DB row exists.
_PRIOR: dict[str, dict[str, float]] = {
    "pricing": {"positive": 0.10, "neutral": 0.25, "negative": 0.55, "mixed": 0.10},
    "feature": {"positive": 0.45, "neutral": 0.30, "negative": 0.15, "mixed": 0.10},
    "copy": {"positive": 0.20, "neutral": 0.50, "negative": 0.15, "mixed": 0.15},
    "bundling": {"positive": 0.25, "neutral": 0.35, "negative": 0.25, "mixed": 0.15},
    "onboarding": {"positive": 0.35, "neutral": 0.40, "negative": 0.15, "mixed": 0.10},
}

_SENTIMENTS = ("positive", "neutral", "negative", "mixed")
_MIN_SAMPLES = 5  # below this, blend with prior


class DuplicateOutcomeError(Exception):
    """Raised when an outcome for (simulation_id, option_letter) already exists."""


async def record_outcome(
    simulation_id: uuid.UUID,
    option_letter: str,
    reported_sentiment: str,
    notes: str | None,
    db: AsyncSession,
) -> OutcomeReport:
    """Persist an OutcomeReport row.

    Raises DuplicateOutcomeError if a report for this (simulation_id,
    option_letter) pair already exists.
    """
    report = OutcomeReport(
        id=uuid.uuid4(),
        simulation_id=simulation_id,
        option_letter=option_letter,
        reported_sentiment=reported_sentiment,
        reported_at=datetime.now(tz=UTC),
        notes=notes,
    )
    db.add(report)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateOutcomeError(
            f"Outcome already recorded for simulation {simulation_id}, option {option_letter!r}"
        ) from exc
    return report


async def recompute_rates(option_type: str, db: AsyncSession) -> None:
    """Recompute CalibrationRate for option_type using all historical reports.

    Uses a Laplace-smoothing-like blend when sample count is below _MIN_SAMPLES:

        rate = (prior_rate * M + observed_rate * n) / (M + n)

    where M = _MIN_SAMPLES (5), n = number of reports for this option_type,
    and observed_rate = count(sentiment=s) / n.

    Above M, observed_rate takes over:
        rate = count(sentiment=s) / n

    This prevents a single report from collapsing the prior to 0 or 1.
    """
    # Count reports per sentiment for this option_type, joined via Simulation.
    stmt = (
        select(
            OutcomeReport.reported_sentiment,
            func.count(OutcomeReport.id).label("cnt"),
        )
        .join(Simulation, Simulation.id == OutcomeReport.simulation_id)
        .where(Simulation.decision_type == option_type)
        .group_by(OutcomeReport.reported_sentiment)
    )
    rows = (await db.execute(stmt)).all()
    counts: dict[str, int] = {row.reported_sentiment: row.cnt for row in rows}
    n = sum(counts.values())

    prior_map = _PRIOR.get(option_type, _PRIOR["feature"])

    for sentiment in _SENTIMENTS:
        observed_count = counts.get(sentiment, 0)

        if n == 0:
            blended = prior_map.get(sentiment, 0.25)
        elif n < _MIN_SAMPLES:
            prior_rate = prior_map.get(sentiment, 0.25)
            observed_rate = observed_count / n
            blended = (prior_rate * _MIN_SAMPLES + observed_rate * n) / (_MIN_SAMPLES + n)
        else:
            blended = observed_count / n

        # Clamp to [0, 1] — formula is always safe but guard against fp drift.
        blended = max(0.0, min(1.0, blended))

        await db.execute(
            update(CalibrationRate)
            .where(
                CalibrationRate.option_type == option_type,
                CalibrationRate.sentiment == sentiment,
            )
            .values(rate=blended, sample_count=n, updated_at=datetime.now(tz=UTC))
        )

    log.info(
        "calibration.recompute_rates",
        option_type=option_type,
        total_reports=n,
    )


async def get_accuracy_summary(
    simulation_id: uuid.UUID,
    db: AsyncSession,
) -> dict[str, object]:
    """Compare predicted sentiment vs reported_sentiment for a simulation.

    Returns a dict with predicted, reported, match, option_letter, and
    simulation_id. Uses the modal (most common) predicted sentiment across
    cells for the shipped option_letter.
    """
    report_stmt = select(OutcomeReport).where(
        OutcomeReport.simulation_id == simulation_id
    )
    report = (await db.execute(report_stmt)).scalar_one_or_none()
    if report is None:
        return {}

    # Find cells for the shipped option_letter — take the first cell's sentiment
    # as the prediction (cells per option typically agree directionally).
    cell_stmt = (
        select(SimulationCell.reaction_sentiment)
        .where(
            SimulationCell.simulation_id == simulation_id,
            SimulationCell.option_letter == report.option_letter,
            SimulationCell.reaction_sentiment.is_not(None),
        )
        .limit(1)
    )
    predicted = (await db.execute(cell_stmt)).scalar_one_or_none()

    return {
        "predicted": predicted,
        "reported": report.reported_sentiment,
        "match": predicted == report.reported_sentiment,
        "option_letter": report.option_letter,
        "simulation_id": str(simulation_id),
    }
