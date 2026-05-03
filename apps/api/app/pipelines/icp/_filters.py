"""Shared fast filters for ICP evidence and segment text."""

from __future__ import annotations

import html
import re

import structlog

log = structlog.get_logger()

MINIMUM_SNIPPET_LENGTH = 40

NON_CUSTOMER_PATTERNS: list[re.Pattern[str]] = [
    # Competitor comparisons
    re.compile(r"\b(?:vs\.?|versus|alternatives?|competitors?|compared? to)\b", re.IGNORECASE),
    # Review aggregation / top-N lists
    re.compile(r"\b(?:top \d+|best overall|best rated|highest rated)\b", re.IGNORECASE),
    re.compile(r"\b\d+\s+people have already reviewed\b", re.IGNORECASE),
    re.compile(r"\bcommunity submitted\s+\d+\s+reviews\b", re.IGNORECASE),
    re.compile(r"^\s*\d+\.\s+.*\b(?:best|recommended|highly customizable|all[- ]in[- ]one)\b", re.IGNORECASE),
    # Review-count metadata
    re.compile(r"\d+[\.,]?\d*\s*(?:reviews?|ratings?|stars?)", re.IGNORECASE),
    # Pricing/plan pages
    re.compile(r"\b(?:pricing|per seat|per month|per user|free trial|upgrade)\b", re.IGNORECASE),
    # Employee reviews (Glassdoor, Blind, LinkedIn insider)
    re.compile(r"\b(?:glassdoor|teamblind|blind\.com|current employee|former employee)\b", re.IGNORECASE),
    # Generic navigation / metadata
    re.compile(r"\b(?:cookies?|privacy policy|terms of service|sign up|log in|get started)\b", re.IGNORECASE),
]

NON_CUSTOMER_SOURCE_KINDS = frozenset({
    "press",
    "blog",
    "glassdoor",
    "blind",
    "teamblind",
})

INVALID_SEGMENT_NAMES = frozenset({
    "unknown",
    "unknown segment",
    "n/a",
    "not available",
    "not enough information",
    "insufficient data",
    "no segment",
    "unnamed",
})

_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_LEADING_URL_RE = re.compile(r"^\s*https?://\S+\s*", re.IGNORECASE)
_LEADING_AVATAR_RE = re.compile(r"^\s*(?:https\s+)?avatar\b[:\-\s]*", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


def _decode_html_entities(value: str) -> str:
    decoded = value
    for _ in range(3):
        next_value = html.unescape(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return decoded


def clean_snippet(snippet: str, *, enforce_minimum_length: bool = False) -> str:
    """Remove URL artifacts, avatar placeholders, and HTML remnants."""
    cleaned = _decode_html_entities(snippet)
    cleaned = _MARKDOWN_IMAGE_RE.sub(" ", cleaned)
    cleaned = _HTML_TAG_RE.sub(" ", cleaned)
    cleaned = _LEADING_URL_RE.sub("", cleaned)
    cleaned = _LEADING_AVATAR_RE.sub("", cleaned)

    tokens = [
        token
        for token in cleaned.split()
        if not re.match(r"^https?://", token, re.IGNORECASE)
    ]
    cleaned = " ".join(tokens)
    cleaned = re.sub(r"^(?:&|amp;)+\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = _LEADING_AVATAR_RE.sub("", cleaned)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip(" \t\r\n\"'")

    if enforce_minimum_length and len(cleaned) < MINIMUM_SNIPPET_LENGTH:
        return ""
    return cleaned


def is_customer_evidence(snippet: str, source_kind: str) -> tuple[bool, str]:
    """Return whether a snippet is customer evidence and, if not, why."""
    cleaned = clean_snippet(snippet)
    normalized_source_kind = source_kind.strip().lower()

    if normalized_source_kind in NON_CUSTOMER_SOURCE_KINDS:
        reason = f"source_kind_{normalized_source_kind}"
        log.debug("icp.evidence.filtered", reason=reason, snippet_start=cleaned[:80])
        return False, reason

    if len(cleaned) < MINIMUM_SNIPPET_LENGTH:
        log.debug("icp.evidence.filtered", reason="too_short", snippet_start=cleaned[:80])
        return False, "too_short"

    for pattern in NON_CUSTOMER_PATTERNS:
        if pattern.search(cleaned):
            reason = f"pattern:{pattern.pattern}"
            log.debug("icp.evidence.filtered", reason=reason, snippet_start=cleaned[:80])
            return False, reason

    return True, ""


def is_invalid_segment_name(name: str | None) -> bool:
    """Return true when a segment name is missing or a non-persona placeholder."""
    if name is None:
        return True
    return name.strip().lower() in INVALID_SEGMENT_NAMES
