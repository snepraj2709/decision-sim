"""
EvidenceCuratorAgent

Wraps stages 1-3 of the snapshot pipeline:
  scrape.py → search.py → extract.py

Stage 4 (score.py → database write) stays in the pipeline and is NOT wrapped here.
The agent does NOT write to the database. The pipeline task does that after
receiving the agent's output.

Rubric: entirely function-based — no LLM calls for evidence evaluation.
All three dimensions are soft gates. Failure flags evidence_thin=True, which
is passed downstream so the Orchestrator can reduce confidence accordingly.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.agents.base import Agent, AgentOutput
from app.agents.config import SONNET_MODEL
from app.agents.rubrics.base import RubricResult
from app.agents.rubrics.functional import (
    check_customer_voice_ratio,
    check_recency,
    check_source_diversity,
)
from app.pipelines.snapshot.extract import ExtractionResult, run_extraction
from app.pipelines.snapshot.scrape import ScrapeResult, run_scrape
from app.pipelines.snapshot.search import SearchResult, run_search


@dataclass
class EvidenceInput:
    url: str
    expand_search: bool = False  # set True on retry — use more queries


@dataclass
class EvidenceOutput:
    scrape_result: ScrapeResult
    search_results: list[SearchResult]
    extraction: ExtractionResult
    evidence_thin: bool  # True if rubric flagged low evidence quality


class EvidenceCuratorAgent(Agent[EvidenceInput, EvidenceOutput]):
    name = "evidence_curator"
    model = SONNET_MODEL  # extraction uses Sonnet; rubric eval is function-based

    async def run(self, input: EvidenceInput) -> EvidenceOutput:
        scrape_result = await run_scrape(input.url)
        max_results = 15 if not input.expand_search else 25
        search_results = await run_search(scrape_result, max_results=max_results)
        extraction = await run_extraction(scrape_result, search_results)
        return EvidenceOutput(
            scrape_result=scrape_result,
            search_results=search_results,
            extraction=extraction,
            evidence_thin=False,  # rubric decides this
        )

    async def evaluate_rubric(
        self, input: EvidenceInput, output: EvidenceOutput
    ) -> RubricResult:
        snippets = [r.snippet for r in output.search_results if r.snippet]
        diversity = check_source_diversity(output.search_results)
        recency = check_recency(output.search_results)
        voice = check_customer_voice_ratio(snippets)
        return RubricResult(dimensions=[diversity, recency, voice])

    def build_retry_input(
        self, input: EvidenceInput, rubric_result: RubricResult
    ) -> EvidenceInput:
        # On any soft-gate failure: expand search on retry
        return EvidenceInput(url=input.url, expand_search=True)

    async def execute(self, input: EvidenceInput) -> AgentOutput[EvidenceOutput]:
        agent_output = await super().execute(input)
        # Flag evidence_thin based on rubric outcome
        if agent_output.result and not agent_output.rubric_passed:
            agent_output.result.evidence_thin = True
        return agent_output
