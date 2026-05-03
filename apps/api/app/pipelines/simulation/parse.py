"""Stage 1 — Option parsing.

Validates the raw option dicts stored in Simulation.options and returns
typed ParsedOption dataclasses ready for downstream stages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

OptionType = Literal["pricing", "copy", "feature", "bundling", "onboarding"]

_VALID_OPTION_TYPES = frozenset({"pricing", "copy", "feature", "bundling", "onboarding"})


@dataclass(frozen=True)
class ParsedOption:
    label: str
    description: str
    option_type: OptionType


def parse_options(options: list[dict[str, object]]) -> list[ParsedOption]:
    """Validate and parse raw option dicts into ParsedOption dataclasses.

    Args:
        options: Raw list from Simulation.options JSON column.

    Raises:
        ValueError: If count is outside [2, 5], labels are not unique,
                    descriptions exceed 500 chars, or option_type is unknown.
    """
    if not (2 <= len(options) <= 5):
        raise ValueError(f"Simulation requires 2-5 options, got {len(options)}")

    parsed: list[ParsedOption] = []
    seen_labels: set[str] = set()

    for opt in options:
        label = str(opt.get("label", "")).strip()
        description = str(opt.get("description", "")).strip()
        option_type = str(opt.get("option_type", "feature"))

        if not label:
            raise ValueError("Option label cannot be empty")
        if label in seen_labels:
            raise ValueError(f"Duplicate option label: {label!r}")
        if len(description) > 500:
            raise ValueError(
                f"Option description exceeds 500 chars for label {label!r}"
            )
        if option_type not in _VALID_OPTION_TYPES:
            raise ValueError(
                f"Unknown option_type {option_type!r} for label {label!r}"
            )

        seen_labels.add(label)
        parsed.append(
            ParsedOption(
                label=label,
                description=description,
                option_type=option_type,  # type: ignore[arg-type]
            )
        )

    return parsed
