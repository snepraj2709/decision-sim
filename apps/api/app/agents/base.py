"""
Agent base class.

Every agent has three responsibilities:
  run()             — execute the core logic (wraps an existing pipeline stage)
  evaluate_rubric() — assess output quality against defined dimensions
  build_retry_input() — modify the input to address the specific rubric failure

The execute() method coordinates all three with retry logic.

Rubric results are NEVER persisted — they are returned as part of AgentOutput
for the Orchestrator to consume.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.agents.rubrics.base import RubricResult

logger = logging.getLogger(__name__)


@dataclass
class AgentOutput[OutputT]:
    result: OutputT
    rubric_passed: bool
    rubric_result: RubricResult
    attempts: int
    agent_name: str

    @property
    def needs_orchestrator_attention(self) -> bool:
        """True if Orchestrator should receive a warning about this output."""
        return not self.rubric_passed or bool(self.rubric_result.soft_flags)

    def failure_metadata(self) -> dict[str, object]:
        """Serialisable metadata for Orchestrator synthesis prompt."""
        return {
            "agent": self.agent_name,
            "rubric_passed": self.rubric_passed,
            "attempts": self.attempts,
            "rubric": self.rubric_result.as_metadata(),
        }


class Agent[InputT, OutputT](ABC):
    """
    Abstract base for all Decision Sim agents.

    Subclasses MUST define:
      - name: str class attribute
      - model: str class attribute (use SONNET_MODEL or HAIKU_MODEL from config)
      - run()
      - evaluate_rubric()
      - build_retry_input()
    """

    name: str = "unnamed_agent"
    model: str  # must be set by subclass
    max_retries: int = 2

    @abstractmethod
    async def run(self, input: InputT) -> OutputT:
        """Execute the agent's primary logic. May call DSPy programs or pipeline stages."""
        ...

    @abstractmethod
    async def evaluate_rubric(
        self, input: InputT, output: OutputT
    ) -> RubricResult:
        """
        Evaluate output quality against rubric dimensions.
        Must be deterministic where possible (function-based checks first).
        LLM-as-judge calls (Haiku) only for dimensions that require semantic judgment.
        """
        ...

    @abstractmethod
    def build_retry_input(
        self, input: InputT, rubric_result: RubricResult
    ) -> InputT:
        """
        Construct a modified input that addresses the specific rubric failure.
        The failure_reason is available via rubric_result.failure_reason.
        Do NOT return the original input unchanged — that causes an identical retry.
        """
        ...

    async def execute(self, input: InputT) -> AgentOutput[OutputT]:
        """
        Run the agent with retry logic.
        Returns AgentOutput regardless of rubric outcome — never raises on rubric failure.
        The caller (Orchestrator) decides how to handle rubric-failed outputs.
        """
        last_output: OutputT | None = None
        last_rubric: RubricResult = RubricResult()

        for attempt in range(1, self.max_retries + 1):
            logger.info(
                "agent=%s attempt=%d/%d", self.name, attempt, self.max_retries
            )
            try:
                output = await self.run(input)
            except Exception as exc:
                logger.error(
                    "agent=%s attempt=%d run() failed: %s", self.name, attempt, exc
                )
                # On run failure: escalate immediately, don't retry
                return AgentOutput(
                    result=last_output,   # type: ignore[arg-type]
                    rubric_passed=False,
                    rubric_result=last_rubric,
                    attempts=attempt,
                    agent_name=self.name,
                )

            rubric_result = await self.evaluate_rubric(input, output)
            last_output = output
            last_rubric = rubric_result

            if rubric_result.passed:
                logger.info(
                    "agent=%s passed rubric on attempt %d", self.name, attempt
                )
                return AgentOutput(
                    result=output,
                    rubric_passed=True,
                    rubric_result=rubric_result,
                    attempts=attempt,
                    agent_name=self.name,
                )

            logger.warning(
                "agent=%s attempt=%d rubric failed: %s",
                self.name,
                attempt,
                rubric_result.failure_reason,
            )

            if attempt < self.max_retries:
                input = self.build_retry_input(input, rubric_result)

        # Exhausted retries — return last output with rubric_passed=False
        logger.error(
            "agent=%s exhausted %d retries. Escalating to Orchestrator.",
            self.name,
            self.max_retries,
        )
        return AgentOutput(
            result=last_output,      # type: ignore[arg-type]
            rubric_passed=False,
            rubric_result=last_rubric,
            attempts=self.max_retries,
            agent_name=self.name,
        )
