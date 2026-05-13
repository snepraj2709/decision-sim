"""RQ task definitions — worker-side entry points.

The pipelines themselves are async; RQ tasks are sync. We bridge with
`asyncio.run`, and each task must create and dispose its own async engine
inside that event loop. asyncpg pools keep loop references, so sharing the
FastAPI process engine/sessionmaker across RQ jobs can poison later jobs.

Run a worker:
    uv run rq worker --url redis://localhost:6379

Step 2 will register tasks here. Step 1 leaves the file with the imports
and a single placeholder so the worker has something to load.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.config import Settings
    from app.models import Simulation

log = structlog.get_logger()


def task_run_snapshot(url: str) -> str:
    """Worker task — wraps the snapshot pipeline.

    Returns the snapshot ID as a string (RQ serializes return values).
    Step 2 implements the body.
    """
    log.info("task.snapshot.start", url=url)

    async def _run() -> str:
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        from app.config import get_settings

        settings = get_settings()
        engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=1,
            max_overflow=0,
        )

        try:
            async with async_sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )() as db:
                from app.pipelines.snapshot import run_snapshot_pipeline

                snapshot_id = await run_snapshot_pipeline(url, db)
                return str(snapshot_id)
        finally:
            await engine.dispose()

    snapshot_id = asyncio.run(_run())
    log.info("task.snapshot.done", url=url, snapshot_id=snapshot_id)
    return snapshot_id


def task_run_icps(snapshot_id: str) -> list[str]:
    """Worker task — wraps the ICP pipeline. Step 3 implements."""
    log.info("task.icps.start", snapshot_id=snapshot_id)

    async def _run() -> list[str]:
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        from app.config import get_settings

        settings = get_settings()
        engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=1,
            max_overflow=0,
        )

        try:
            async with async_sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )() as db:
                from app.pipelines.icp import run_icp_pipeline

                ids = await run_icp_pipeline(uuid.UUID(snapshot_id), db)
                return [str(i) for i in ids]
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def task_run_simulation(simulation_id: str) -> None:
    """Worker task — wraps the simulation pipeline. Step 4 implements."""
    log.info("task.simulation.start", simulation_id=simulation_id)

    async def _run() -> None:
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        from app.config import get_settings

        settings = get_settings()
        engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=1,
            max_overflow=0,
        )

        try:
            async with async_sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )() as db:
                from app.pipelines.simulation import run_simulation

                await run_simulation(uuid.UUID(simulation_id), db)
        finally:
            await engine.dispose()

    asyncio.run(_run())


def task_run_simulation_v2(simulation_id: str) -> None:
    """V2 simulation task using the multi-agent architecture.

    Falls back to V1 task if AGENT_MODE != v2. The fallback should not
    normally trigger because the dispatch in simulations.py already routes
    correctly, but it guards against direct invocation.
    """
    from app.agents.config import is_agent_mode_v2

    if not is_agent_mode_v2():
        task_run_simulation(simulation_id)
        return

    log.info("task.simulation_v2.start", simulation_id=simulation_id)
    asyncio.run(_run_simulation_orchestrated(simulation_id))
    log.info("task.simulation_v2.done", simulation_id=simulation_id)


async def _run_simulation_orchestrated(simulation_id: str) -> None:
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from app.config import get_settings

    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
    )

    try:
        async with async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )() as db:
            await _orchestrated_pipeline(simulation_id, db, settings)
    finally:
        await engine.dispose()


async def _orchestrated_pipeline(simulation_id: str, db: AsyncSession, settings: Settings) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.agents.calibration_agent import (
        CalibrationAgent,
        CalibrationInput,
        CalibrationOutput,
    )
    from app.agents.devil_advocate import run_all_devil_advocates
    from app.agents.orchestrator import OrchestratorAgent, OrchestratorInput
    from app.agents.reaction_analyst import run_all_reactions
    from app.models import ProductSnapshot, Segment, Simulation

    simulation = await db.get(Simulation, uuid.UUID(simulation_id))
    if simulation is None:
        raise ValueError(f"Simulation {simulation_id} not found")

    simulation.status = "running"
    await db.commit()
    try:
        seg_stmt = (
            select(Segment)
            .where(Segment.snapshot_id == simulation.snapshot_id)
            .options(selectinload(Segment.evidence))
            .order_by(Segment.share_pct.desc())
        )
        segments = list((await db.execute(seg_stmt)).scalars().all())
        snapshot = await db.get(ProductSnapshot, simulation.snapshot_id)
        options = list(simulation.options or [])
        option_types = list({str(opt.get("option_type", "feature")) for opt in options})

        # 1. Calibration (pure Python, no LLM calls)
        cal_agent = CalibrationAgent()
        cal_agent_out = await cal_agent.execute(CalibrationInput(
            option_types=option_types,
            db=db,        ))
        calibration_output = cal_agent_out.result
        if calibration_output is None:
            calibration_output = CalibrationOutput(rates={}, stale_flags=[], low_n_types=[])

        # 2. Reactions — all (segment × option) pairs in parallel
        options_for_reactions: list[dict[str, str]] = [
            {
                "letter": str(opt["label"]),
                "text": str(opt.get("description", "")),
                "option_type": str(opt.get("option_type", "feature")),
            }
            for opt in options
        ]
        reaction_outputs = await run_all_reactions(
            segments=segments,
            options=options_for_reactions,
            snapshot_category=getattr(snapshot, "category", "") or "",
        )

        # 3. Devil's Advocate — cells approved by DEVIL_ADVOCATE_MODE in parallel
        segments_by_id = {str(s.id): s for s in segments}
        options_by_letter: dict[str, str] = {str(opt["label"]): str(opt.get("description", "")) for opt in options}
        da_outputs = await run_all_devil_advocates(
            reaction_outputs=reaction_outputs,
            segments_by_id=segments_by_id,
            options_by_letter=options_by_letter,
        )

        # 4. Orchestrator — synthesises all agent outputs into Decision Memo
        orchestrator = OrchestratorAgent()
        orch_out = await orchestrator.execute(OrchestratorInput(
            segments=segments,
            reaction_outputs=reaction_outputs,
            da_outputs=da_outputs,
            calibration_output=calibration_output,
            simulation_id=simulation_id,
        ))

        # 5. Persist cells + orchestrator memo
        option_type_by_letter: dict[str, str] = {
            str(opt["label"]): str(opt.get("option_type", "feature")) for opt in options
        }
        await _persist_v2_results(
            db=db,
            simulation=simulation,
            segments=segments,
            reaction_outputs=reaction_outputs,
            da_outputs=da_outputs,
            orch_result=orch_out.result,
            option_type_by_letter=option_type_by_letter,
            min_sources=settings.min_sources_for_high_confidence,
        )

    except Exception:
        sim2 = await db.get(Simulation, uuid.UUID(simulation_id))
        if sim2 is not None:
            sim2.status = "failed"
            await db.commit()
        raise


async def _persist_v2_results(
    db: AsyncSession,
    simulation: Simulation,
    segments: list[Any],
    reaction_outputs: list[Any],
    da_outputs: list[Any],
    orch_result: Any,
    option_type_by_letter: dict[str, str],
    min_sources: int,
) -> None:
    from app.core.confidence import (
        TriangulationInput,
        compute_segment_stability,
        evidence_density_from_count,
        triangulate,
    )
    from app.pipelines.simulation.persist import persist_cells
    from app.pipelines.simulation.score import BASE_RATES, CellResult

    seg_by_id = {s.id: s for s in segments}

    # Pre-compute embeddings list per segment for stability calculation
    all_embeddings: dict[Any, list[float]] = {}
    for s in segments:
        emb = s.embedding
        if emb is None:
            all_embeddings[s.id] = []
        elif hasattr(emb, "tolist"):
            all_embeddings[s.id] = [float(x) for x in emb.tolist()]
        elif isinstance(emb, list):
            all_embeddings[s.id] = [float(x) for x in emb]
        else:
            all_embeddings[s.id] = []

    da_by_cell_id = {
        out.result.cell_id: out.result
        for out in da_outputs
        if out.result
    }

    cell_results: list[CellResult] = []
    for out in reaction_outputs:
        if not out.result:
            continue
        reaction = out.result.cell  # ReactionResult
        segment = seg_by_id.get(reaction.segment_id)
        if segment is None:
            continue

        if reaction.failed or segment.confidence == "low":
            confidence = "low"
        else:
            option_type = option_type_by_letter.get(reaction.option_label, "feature")
            evidence_density = evidence_density_from_count(
                len(segment.evidence or []), min_for_high=min_sources
            )
            type_rates = BASE_RATES.get(option_type, BASE_RATES["feature"])
            baserate = type_rates.get(reaction.reaction_sentiment, 0.25)
            seg_emb = all_embeddings.get(reaction.segment_id, [])
            other_embeddings = [
                emb
                for sid, emb in all_embeddings.items()
                if sid != reaction.segment_id and emb
            ]
            stability = compute_segment_stability(seg_emb, other_embeddings)
            confidence = triangulate(TriangulationInput(
                llm_baserate_agreement=baserate,
                evidence_density=evidence_density,
                construct_stability=stability,
            ))

        da = da_by_cell_id.get(f"{reaction.segment_id}:{reaction.option_label}")

        cell_results.append(CellResult(
            segment_id=reaction.segment_id,
            option_label=reaction.option_label,
            reaction_sentiment=reaction.reaction_sentiment,
            adoption_probability=reaction.adoption_probability,
            churn_probability=reaction.churn_probability,
            top_concern=reaction.top_concern,
            time_horizon=reaction.time_horizon,
            reasoning_trace=reaction.reasoning_trace,
            confidence=confidence,
            devil_advocate=da.counter_case if da else "",
            smallest_experiment=da.invalidating_experiment if da else "",
        ))

    await persist_cells(
        simulation_id=simulation.id,
        cell_results=cell_results,
        db=db,
    )

    if orch_result is not None:
        orchestrator_memo: dict[str, Any] = {
            "recommendation": orch_result.recommendation,
            "confidence_rationale": orch_result.confidence_rationale,
            "strongest_counter_case": orch_result.strongest_counter_case,
            "conflict_resolution": orch_result.conflict_resolution,
            "rubric_failures_count": orch_result.rubric_failures_count,
            "stale_calibration_types": orch_result.stale_calibration_types,
        }
        if hasattr(simulation, "orchestrator_memo"):
            simulation.orchestrator_memo = orchestrator_memo
            await db.commit()
        else:
            log.warning(
                "orchestrator_memo not persisted: Simulation model has no "
                "orchestrator_memo field. Add migration 0004."
            )
