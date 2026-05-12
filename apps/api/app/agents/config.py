"""
Agent configuration — model routing and feature flags.

All values are read from environment variables at import time.
Set these in your .env or docker-compose environment.

Required additions to .env.example:
  SONNET_MODEL=claude-sonnet-4-20250514
  HAIKU_MODEL=claude-haiku-4-5-20251001
  DEVIL_ADVOCATE_MODE=selective   # all | selective | off
  AGENT_MODE=v1                   # v1=pipeline | v2=agents (default v1 for safety)
"""

from __future__ import annotations

import os

# ── Model routing ────────────────────────────────────────────────────────────
# Use Haiku for rubric evaluation and standard D.A. cells (cheap judge calls).
# Use Sonnet for generation: synthesis, reactions, key D.A. cells, Orchestrator.
SONNET_MODEL: str = os.getenv("SONNET_MODEL", "claude-sonnet-4-20250514")
HAIKU_MODEL: str = os.getenv("HAIKU_MODEL", "claude-haiku-4-5-20251001")


# ── Devil's Advocate mode ─────────────────────────────────────────────────────
class DevilAdvocateMode:
    ALL = "all"           # Run D.A. on every cell regardless of confidence
    SELECTIVE = "selective"  # Run D.A. only on cells where reaction rubric did not fully pass
    OFF = "off"           # Skip D.A. entirely (useful for cost profiling)


DEVIL_ADVOCATE_MODE: str = os.getenv(
    "DEVIL_ADVOCATE_MODE", DevilAdvocateMode.SELECTIVE
)


def da_should_run(reaction_rubric_passed: bool) -> bool:
    """Determine whether D.A. should run for a given cell."""
    mode = DEVIL_ADVOCATE_MODE
    if mode == DevilAdvocateMode.OFF:
        return False
    if mode == DevilAdvocateMode.ALL:
        return True
    # SELECTIVE: run only if the reaction rubric did not fully pass
    return not reaction_rubric_passed


# ── Agent mode (feature flag) ─────────────────────────────────────────────────
class AgentMode:
    V1 = "v1"   # Original pipeline-of-programs (safe default)
    V2 = "v2"   # New multi-agent architecture


AGENT_MODE: str = os.getenv("AGENT_MODE", AgentMode.V1)


def is_agent_mode_v2() -> bool:
    return AGENT_MODE == AgentMode.V2
