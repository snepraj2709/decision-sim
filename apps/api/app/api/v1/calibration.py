"""Calibration endpoints — Step 6.

POST /simulations/{simulation_id}/outcome   — record what actually happened
GET  /simulations/{simulation_id}/outcome   — fetch outcome reports for a sim
GET  /calibration/rates                     — current CalibrationRate table
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.core.calibration import (
    DuplicateOutcomeError,
    get_accuracy_summary,
    recompute_rates,
    record_outcome,
)
from app.models import CalibrationRate, OutcomeReport, Simulation
from app.schemas import (
    AccuracySummary,
    CalibrationRateRead,
    CalibrationRatesResponse,
    OutcomeReportCreate,
    OutcomeReportRead,
)

router = APIRouter()


@router.post(
    "/simulations/{simulation_id}/outcome",
    status_code=status.HTTP_201_CREATED,
    response_model=OutcomeReportRead,
    summary="Record what actually happened after shipping a decision",
)
async def create_outcome(
    simulation_id: uuid.UUID,
    body: OutcomeReportCreate,
    db: DbSession,
) -> OutcomeReportRead:
    # Verify simulation exists and the option_letter is valid.
    stmt = (
        select(Simulation)
        .where(Simulation.id == simulation_id)
        .options(selectinload(Simulation.cells))
    )
    sim = (await db.execute(stmt)).scalar_one_or_none()
    if sim is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Simulation {simulation_id} not found",
        )

    valid_letters = {str(opt.get("label", "")) for opt in (sim.options or [])}
    if body.option_letter not in valid_letters:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"option_letter {body.option_letter!r} not found in simulation. "
                f"Valid letters: {sorted(valid_letters)}"
            ),
        )

    try:
        report = await record_outcome(
            simulation_id=simulation_id,
            option_letter=body.option_letter,
            reported_sentiment=body.reported_sentiment,
            notes=body.notes,
            db=db,
        )
    except DuplicateOutcomeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    await recompute_rates(sim.decision_type, db)
    await db.commit()

    return OutcomeReportRead.model_validate(report)


@router.get(
    "/simulations/{simulation_id}/outcome",
    response_model=list[OutcomeReportRead],
    summary="Get outcome reports for a simulation",
)
async def list_outcomes(
    simulation_id: uuid.UUID,
    db: DbSession,
) -> list[OutcomeReportRead]:
    stmt = select(Simulation.id).where(Simulation.id == simulation_id)
    if (await db.execute(stmt)).scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Simulation {simulation_id} not found",
        )

    reports_stmt = select(OutcomeReport).where(
        OutcomeReport.simulation_id == simulation_id
    )
    reports = (await db.execute(reports_stmt)).scalars().all()
    return [OutcomeReportRead.model_validate(r) for r in reports]


@router.get(
    "/simulations/{simulation_id}/accuracy",
    response_model=AccuracySummary,
    summary="Predicted vs reported sentiment for a simulation",
)
async def get_accuracy(
    simulation_id: uuid.UUID,
    db: DbSession,
) -> AccuracySummary:
    summary = await get_accuracy_summary(simulation_id, db)
    if not summary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No outcome report found for simulation {simulation_id}",
        )
    predicted = summary.get("predicted")
    return AccuracySummary(
        predicted=str(predicted) if predicted is not None else None,
        reported=str(summary["reported"]),
        match=bool(summary["match"]),
        option_letter=str(summary["option_letter"]),
        simulation_id=str(summary["simulation_id"]),
    )


@router.get(
    "/calibration/rates",
    response_model=CalibrationRatesResponse,
    summary="Current calibration rates per option_type and sentiment",
)
async def get_calibration_rates(db: DbSession) -> CalibrationRatesResponse:
    rows = (await db.execute(select(CalibrationRate))).scalars().all()
    nested: dict[str, dict[str, CalibrationRateRead]] = {}
    for row in rows:
        nested.setdefault(row.option_type, {})[row.sentiment] = CalibrationRateRead(
            rate=row.rate,
            sample_count=row.sample_count,
        )
    return CalibrationRatesResponse(rates=nested)
