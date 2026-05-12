"""
SegmentArchitectAgent

Wraps the ICP pipeline (cluster → synthesize → anchor → score).
Does NOT write to the database — the pipeline task handles that.

Rubric:
  Hard gates: anchor_density, segment_distinctness (if these fail, segments are unusable)
  Soft gates: jtbd_completeness, naming_precision (LLM-as-judge via Haiku)

Retry strategy:
  - If anchor_density fails: cannot fix with a retry — escalate immediately
  - If segment_distinctness fails: retry with lower min_cluster_size (more granular)
  - If JTBD completeness fails: retry synthesis for the failing segment(s) only
  - If naming fails: inject naming constraint into synthesis prompt
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import dspy

from app.agents.base import Agent, AgentOutput
from app.agents.config import HAIKU_MODEL, SONNET_MODEL
from app.agents.rubrics.base import RubricDimension, RubricResult
from app.agents.rubrics.functional import check_anchor_density, check_segment_distinctness
from app.agents.rubrics.signatures import JTBDCompletenessRubric, SegmentNamingRubric
from app.pipelines.icp.anchor import AnchoredSegment, run_anchor
from app.pipelines.icp.cluster import ClusterResult, run_cluster
from app.pipelines.icp.synthesize import run_synthesize


@dataclass
class SegmentInput:
    snapshot_id: str
    search_results: list[Any]  # SearchResult list from EvidenceOutput
    retry_with_finer_clustering: bool = False
    jtbd_constraint: str | None = None    # injected on JTBD retry
    naming_constraint: str | None = None  # injected on naming retry


@dataclass
class SegmentOutput:
    segments: list[AnchoredSegment]
    segment_embeddings: list[list[float]]  # centroid embeddings for distinctness check


class SegmentArchitectAgent(Agent[SegmentInput, SegmentOutput]):
    name = "segment_architect"
    model = SONNET_MODEL  # synthesis uses Sonnet

    def __init__(self) -> None:
        self._lm_haiku = dspy.LM(model=HAIKU_MODEL)
        # Predictors use Haiku via dspy.context(lm=self._lm_haiku) at call time
        self._jtbd_rubric = dspy.Predict(JTBDCompletenessRubric)
        self._naming_rubric = dspy.Predict(SegmentNamingRubric)

    async def run(self, input: SegmentInput) -> SegmentOutput:
        min_cluster_size = 2 if not input.retry_with_finer_clustering else 1
        cluster_result, embeddings = await run_cluster(
            input.search_results, min_cluster_size=min_cluster_size
        )

        synthesis_kwargs: dict[str, str] = {}
        if input.jtbd_constraint:
            synthesis_kwargs["jtbd_constraint"] = input.jtbd_constraint
        if input.naming_constraint:
            synthesis_kwargs["naming_constraint"] = input.naming_constraint

        synthesized = await run_synthesize(cluster_result, **synthesis_kwargs)
        anchored = await run_anchor(synthesized, cluster_result)

        # Collect centroid embeddings for the distinctness rubric
        segment_embeddings = [s.centroid_embedding for s in anchored]

        return SegmentOutput(segments=anchored, segment_embeddings=segment_embeddings)

    async def evaluate_rubric(
        self, input: SegmentInput, output: SegmentOutput
    ) -> RubricResult:
        dimensions: list[RubricDimension] = []

        # Hard gates (function-based)
        dimensions.append(check_anchor_density(output.segments))
        if len(output.segment_embeddings) >= 2:
            dimensions.append(check_segment_distinctness(output.segment_embeddings))

        # Soft gates (Haiku LLM-as-judge) — run all checks in parallel
        async def check_jtbd(seg: AnchoredSegment) -> RubricDimension:
            with dspy.context(lm=self._lm_haiku):
                result = self._jtbd_rubric(
                    segment_name=seg.name, jtbd=seg.job_to_be_done
                )
            return RubricDimension(
                name=f"jtbd_completeness:{seg.name}",
                passed=result.passed,
                score=1.0 if result.passed else 0.0,
                is_hard_gate=False,
                reason=result.reason,
            )

        async def check_naming(seg: AnchoredSegment) -> RubricDimension:
            with dspy.context(lm=self._lm_haiku):
                result = self._naming_rubric(segment_name=seg.name)
            return RubricDimension(
                name=f"naming_precision:{seg.name}",
                passed=result.passed,
                score=1.0 if result.passed else 0.0,
                is_hard_gate=False,
                reason=result.reason,
            )

        if output.segments:
            jtbd_results, naming_results = await asyncio.gather(
                asyncio.gather(*(check_jtbd(s) for s in output.segments)),
                asyncio.gather(*(check_naming(s) for s in output.segments)),
            )
            dimensions.extend(jtbd_results)
            dimensions.extend(naming_results)

        return RubricResult(dimensions=dimensions)

    def build_retry_input(
        self, input: SegmentInput, rubric_result: RubricResult
    ) -> SegmentInput:
        failed_names = [d.name for d in rubric_result.dimensions if not d.passed]
        retry = SegmentInput(
            snapshot_id=input.snapshot_id,
            search_results=input.search_results,
        )
        if any("segment_distinctness" in n for n in failed_names):
            retry.retry_with_finer_clustering = True
        if any("jtbd_completeness" in n for n in failed_names):
            retry.jtbd_constraint = (
                "Each job_to_be_done MUST describe a specific functional outcome "
                "the customer actively pursues — not a state they are in. "
                "Include what they DO or ACHIEVE as a result of using the product."
            )
        if any("naming_precision" in n for n in failed_names):
            retry.naming_constraint = (
                "Each segment name MUST identify a specific persona type that a "
                "real person could recognise as describing themselves. Avoid generic "
                "categories like 'Business users' or 'Enterprise customers'. "
                "Include role, context, or key behaviour in the name."
            )
        return retry
