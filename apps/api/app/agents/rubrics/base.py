"""
Rubric evaluation primitives.

Rubric scores are NEVER persisted to the database. They are used in-flight:
  - To determine whether an agent should retry with a modified prompt
  - To pass failure metadata to the Orchestrator agent for synthesis

RubricDimension has two types:
  - Hard gate (is_hard_gate=True): failure blocks the output and triggers a retry
  - Soft gate (is_hard_gate=False): failure is recorded and passed to Orchestrator
    as a flag, but does not block. Use for low-n calibration rates, thin evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RubricDimension:
    name: str
    passed: bool
    score: float          # 0.0 to 1.0
    is_hard_gate: bool = True
    reason: str | None = None


@dataclass
class RubricResult:
    dimensions: list[RubricDimension] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True only if all hard gates pass."""
        hard_gates = [d for d in self.dimensions if d.is_hard_gate]
        if not hard_gates:
            return True
        return all(d.passed for d in hard_gates)

    @property
    def failure_reason(self) -> str:
        """Concatenated reasons for all failed dimensions."""
        failed = [d for d in self.dimensions if not d.passed]
        if not failed:
            return ""
        return "; ".join(
            f"{d.name}: {d.reason or 'no reason provided'}" for d in failed
        )

    @property
    def soft_flags(self) -> list[RubricDimension]:
        """Soft-gate failures to pass to Orchestrator as warning flags."""
        return [d for d in self.dimensions if not d.is_hard_gate and not d.passed]

    def as_metadata(self) -> dict:
        """Serialise for inclusion in Orchestrator synthesis prompt."""
        return {
            "passed": self.passed,
            "failure_reason": self.failure_reason,
            "dimensions": [
                {
                    "name": d.name,
                    "passed": d.passed,
                    "score": d.score,
                    "is_hard_gate": d.is_hard_gate,
                    "reason": d.reason,
                }
                for d in self.dimensions
            ],
        }
