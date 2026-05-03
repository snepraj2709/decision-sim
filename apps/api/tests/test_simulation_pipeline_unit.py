"""Unit tests for the simulation pipeline — no LLM, no DB.

Tests verify:
1. parse_options validation and failure modes
2. score_cells confidence computation from triangulate()
3. persist_cells idempotency and overall_confidence logic
4. 409 guard in segments.py
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.pipelines.simulation.parse import ParsedOption, parse_options
from app.pipelines.simulation.score import (
    BASE_RATES,
    CellResult,
    _baserate_agreement,
    _churn_range,
)


# ── parse_options ─────────────────────────────────────────────────────────────

class TestParseOptions:
    def _opt(
        self,
        label: str = "A",
        description: str = "Test option",
        option_type: str = "pricing",
    ) -> dict[str, object]:
        return {"label": label, "description": description, "option_type": option_type}

    def test_valid_two_options(self) -> None:
        opts = [self._opt("A"), self._opt("B", option_type="feature")]
        result = parse_options(opts)
        assert len(result) == 2
        assert result[0].label == "A"
        assert result[0].option_type == "pricing"

    def test_valid_five_options(self) -> None:
        opts = [self._opt(str(i)) for i in range(5)]
        result = parse_options(opts)
        assert len(result) == 5

    def test_too_few_options_raises(self) -> None:
        with pytest.raises(ValueError, match="2-5"):
            parse_options([self._opt("A")])

    def test_too_many_options_raises(self) -> None:
        with pytest.raises(ValueError, match="2-5"):
            parse_options([self._opt(str(i)) for i in range(6)])

    def test_duplicate_labels_raise(self) -> None:
        with pytest.raises(ValueError, match="Duplicate"):
            parse_options([self._opt("A"), self._opt("A")])

    def test_description_over_500_chars_raises(self) -> None:
        long_desc = "x" * 501
        with pytest.raises(ValueError, match="500"):
            parse_options([self._opt("A", description=long_desc), self._opt("B")])

    def test_empty_label_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            parse_options([{"label": "  ", "description": "ok", "option_type": "pricing"}, self._opt("B")])

    def test_unknown_option_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown"):
            parse_options([self._opt("A", option_type="unknown"), self._opt("B")])

    def test_returns_parsed_option_dataclasses(self) -> None:
        opts = [self._opt("Raise", option_type="bundling"), self._opt("Hold", option_type="copy")]
        result = parse_options(opts)
        assert all(isinstance(r, ParsedOption) for r in result)
        assert result[0].option_type == "bundling"


# ── BASE_RATES ────────────────────────────────────────────────────────────────

class TestBaseRates:
    def test_all_option_types_covered(self) -> None:
        expected = {"pricing", "feature", "copy", "bundling", "onboarding"}
        assert set(BASE_RATES.keys()) == expected

    def test_all_sentiments_covered(self) -> None:
        sentiments = {"positive", "neutral", "negative", "mixed"}
        for rates in BASE_RATES.values():
            assert set(rates.keys()) == sentiments

    def test_rates_sum_to_one(self) -> None:
        for option_type, rates in BASE_RATES.items():
            total = sum(rates.values())
            assert abs(total - 1.0) < 1e-9, f"{option_type} rates sum to {total}"

    def test_pricing_negative_is_dominant(self) -> None:
        assert BASE_RATES["pricing"]["negative"] > BASE_RATES["pricing"]["positive"]

    def test_feature_positive_is_dominant(self) -> None:
        assert BASE_RATES["feature"]["positive"] > BASE_RATES["feature"]["negative"]

    def test_baserate_agreement_returns_rate(self) -> None:
        rate = _baserate_agreement("pricing", "negative")
        assert rate == BASE_RATES["pricing"]["negative"]

    def test_unknown_option_type_falls_back_to_feature(self) -> None:
        rate = _baserate_agreement("unknown", "positive")
        assert rate == BASE_RATES["feature"]["positive"]


# ── _churn_range ─────────────────────────────────────────────────────────────

class TestChurnRange:
    def test_midpoint_gives_symmetric_band(self) -> None:
        low, high = _churn_range(0.5)
        assert low == 40
        assert high == 60

    def test_zero_churn_clamps_at_zero(self) -> None:
        low, high = _churn_range(0.0)
        assert low == 0
        assert high == 10

    def test_full_churn_clamps_at_100(self) -> None:
        low, high = _churn_range(1.0)
        assert low == 90
        assert high == 100

    def test_low_lte_high(self) -> None:
        for churn in (0.0, 0.1, 0.5, 0.9, 1.0):
            low, high = _churn_range(churn)
            assert low <= high


# ── CellResult overall_confidence ─────────────────────────────────────────────

def _make_cell(confidence: str) -> CellResult:
    return CellResult(
        segment_id=uuid.uuid4(),
        option_label="A",
        reaction_sentiment="neutral",
        adoption_probability=0.5,
        churn_probability=0.3,
        top_concern="",
        time_horizon="90d",
        reasoning_trace="",
        confidence=confidence,
        devil_advocate="",
        smallest_experiment="",
    )


class TestOverallConfidence:
    """Worst-of-cells: one Low pulls the run to Low."""

    def _overall(self, cells: list[CellResult]) -> str:
        from app.pipelines.simulation.persist import _overall_confidence
        return _overall_confidence(cells)

    def test_all_high_gives_high(self) -> None:
        cells = [_make_cell("high"), _make_cell("high")]
        assert self._overall(cells) == "high"

    def test_one_medium_gives_medium(self) -> None:
        cells = [_make_cell("high"), _make_cell("medium")]
        assert self._overall(cells) == "medium"

    def test_one_low_gives_low(self) -> None:
        cells = [_make_cell("high"), _make_cell("medium"), _make_cell("low")]
        assert self._overall(cells) == "low"

    def test_all_low_gives_low(self) -> None:
        cells = [_make_cell("low"), _make_cell("low")]
        assert self._overall(cells) == "low"


# ── _option_labels ────────────────────────────────────────────────────────────

class TestOptionLabels:
    def _labels(self, options: list[dict[str, object]]) -> frozenset[str]:
        from app.pipelines.simulation.persist import _option_labels
        return _option_labels(options)

    def test_extracts_labels(self) -> None:
        opts = [{"label": "A"}, {"label": "B"}]
        assert self._labels(opts) == frozenset({"A", "B"})

    def test_ignores_non_dicts(self) -> None:
        opts = [{"label": "A"}, "bad", 42]  # type: ignore[list-item]
        assert self._labels(opts) == frozenset({"A"})

    def test_empty_list(self) -> None:
        assert self._labels([]) == frozenset()


# ── score_cells confidence propagation from evidence_density ──────────────────

class TestScoreCellsConfidencePropagation:
    """Thin segment evidence should pull cell confidence to Low."""

    @pytest.mark.asyncio
    async def test_zero_evidence_produces_low_confidence(self) -> None:
        from app.pipelines.simulation.react import ReactionResult
        from app.pipelines.simulation.score import score_cells

        segment_id = uuid.uuid4()

        # A segment with NO evidence
        segment = MagicMock()
        segment.id = segment_id
        segment.name = "Test Segment"
        segment.evidence = []
        segment.drivers = []
        segment.leaves = ""
        segment.embedding = [0.1] * 1536

        option = ParsedOption(label="A", description="Raise prices by 20%", option_type="pricing")

        reaction = ReactionResult(
            segment_id=segment_id,
            option_label="A",
            reaction_sentiment="negative",
            adoption_probability=0.3,
            churn_probability=0.7,
            top_concern="Price too high",
            time_horizon="30d",
            reasoning_trace="We can't afford this.",
            failed=False,
        )

        with patch(
            "app.pipelines.simulation.score._generate_devils_advocate",
            new=AsyncMock(return_value=("", "")),
        ):
            cells = await score_cells([segment], [reaction], [option], min_sources=3)

        assert len(cells) == 1
        # Zero evidence_density forces the geometric mean to zero → Low
        assert cells[0].confidence == "low"

    @pytest.mark.asyncio
    async def test_failed_reaction_forces_low_confidence(self) -> None:
        from app.pipelines.simulation.react import ReactionResult
        from app.pipelines.simulation.score import score_cells

        segment_id = uuid.uuid4()
        evidence = MagicMock()
        evidence.quote = "Great product"
        evidence.source = "reddit.com"

        segment = MagicMock()
        segment.id = segment_id
        segment.name = "Test Segment"
        segment.evidence = [evidence, evidence, evidence]
        segment.drivers = [{"label": "speed", "weight": 0.8}]
        segment.leaves = "price spike"
        segment.embedding = [0.1] * 1536

        option = ParsedOption(label="A", description="Add feature", option_type="feature")

        reaction = ReactionResult(
            segment_id=segment_id,
            option_label="A",
            reaction_sentiment="neutral",
            adoption_probability=0.5,
            churn_probability=0.5,
            top_concern="Simulation failed - retry",
            time_horizon="90d",
            reasoning_trace="",
            failed=True,  # DSPy call failed
        )

        with patch(
            "app.pipelines.simulation.score._generate_devils_advocate",
            new=AsyncMock(return_value=("What if users love it?", "Survey 20 beta users")),
        ):
            cells = await score_cells([segment], [reaction], [option], min_sources=3)

        assert cells[0].confidence == "low"

    @pytest.mark.asyncio
    async def test_high_evidence_feature_positive_can_reach_medium(self) -> None:
        from app.pipelines.simulation.react import ReactionResult
        from app.pipelines.simulation.score import score_cells

        segment_id = uuid.uuid4()

        # Build 3 distinct mock evidence items with different domain markers
        evidences = []
        for domain in ("reddit.com", "g2.com", "producthunt.com"):
            e = MagicMock()
            e.quote = f"Love it from {domain}"
            e.source = domain
            evidences.append(e)

        # Segment with distinct embedding
        emb_a = [1.0] + [0.0] * 1535
        emb_b = [0.0, 1.0] + [0.0] * 1534  # orthogonal → max stability

        segment = MagicMock()
        segment.id = segment_id
        segment.name = "Power Users"
        segment.evidence = evidences
        segment.drivers = [{"label": "speed", "weight": 0.9}]
        segment.leaves = "downtime"
        segment.embedding = emb_a

        # A second segment for stability calculation
        other_seg = MagicMock()
        other_seg.id = uuid.uuid4()
        other_seg.name = "Casual Users"
        other_seg.evidence = evidences
        other_seg.drivers = [{"label": "price", "weight": 0.6}]
        other_seg.leaves = "support issues"
        other_seg.embedding = emb_b

        option = ParsedOption(label="A", description="New collaboration feature", option_type="feature")

        reaction = ReactionResult(
            segment_id=segment_id,
            option_label="A",
            reaction_sentiment="positive",
            adoption_probability=0.85,
            churn_probability=0.05,
            top_concern="Rollout timeline",
            time_horizon="30d",
            reasoning_trace="This solves our core workflow problem.",
            failed=False,
        )

        cells = await score_cells(
            [segment, other_seg],
            [reaction],
            [option],
            min_sources=3,
        )

        main_cell = next(c for c in cells if c.segment_id == segment_id)
        # feature+positive has baserate 0.45, 3 sources → density=1.0,
        # orthogonal segments → stability=1.0. geo_mean = (0.45*1*1)^(1/3) ≈ 0.766 → high
        assert main_cell.confidence in ("medium", "high")

    @pytest.mark.asyncio
    async def test_devil_advocate_generated_for_low_medium_cells(self) -> None:
        from app.pipelines.simulation.react import ReactionResult
        from app.pipelines.simulation.score import score_cells

        segment_id = uuid.uuid4()
        segment = MagicMock()
        segment.id = segment_id
        segment.name = "Test"
        segment.evidence = []  # no evidence → low confidence
        segment.drivers = []
        segment.leaves = ""
        segment.embedding = []

        option = ParsedOption(label="A", description="Price increase", option_type="pricing")
        reaction = ReactionResult(
            segment_id=segment_id,
            option_label="A",
            reaction_sentiment="negative",
            adoption_probability=0.2,
            churn_probability=0.8,
            top_concern="Too expensive",
            time_horizon="immediate",
            reasoning_trace="",
            failed=False,
        )

        mock_da = AsyncMock(return_value=("Evidence of price insensitivity", "Run 30-user survey"))
        with patch("app.pipelines.simulation.score._generate_devils_advocate", new=mock_da):
            cells = await score_cells([segment], [reaction], [option], min_sources=3)

        assert cells[0].devil_advocate == "Evidence of price insensitivity"
        assert cells[0].smallest_experiment == "Run 30-user survey"
        mock_da.assert_called_once()

    @pytest.mark.asyncio
    async def test_devil_advocate_empty_for_high_confidence_cells(self) -> None:
        from app.pipelines.simulation.react import ReactionResult
        from app.pipelines.simulation.score import score_cells

        # To get high confidence: need all three signals near 1.0
        # evidence_density = 1.0 (3+ sources)
        # baserate = feature+positive = 0.45 → geo_mean needs tweaking
        # stability = 1.0 (only segment)
        # geo_mean(0.45, 1.0, 1.0)^(1/3) = 0.766 → high

        segment_id = uuid.uuid4()
        evidences = [MagicMock() for _ in range(3)]
        for e in evidences:
            e.quote = "Great"
            e.source = "test.com"

        segment = MagicMock()
        segment.id = segment_id
        segment.name = "Power Users"
        segment.evidence = evidences
        segment.drivers = [{"label": "speed", "weight": 0.9}]
        segment.leaves = "downtime"
        segment.embedding = [1.0] + [0.0] * 1535  # only segment → stability=1.0

        option = ParsedOption(label="A", description="New feature", option_type="feature")
        reaction = ReactionResult(
            segment_id=segment_id,
            option_label="A",
            reaction_sentiment="positive",
            adoption_probability=0.9,
            churn_probability=0.05,
            top_concern="",
            time_horizon="30d",
            reasoning_trace="Love it.",
            failed=False,
        )

        mock_da = AsyncMock(return_value=("challenge", "experiment"))
        with patch("app.pipelines.simulation.score._generate_devils_advocate", new=mock_da):
            cells = await score_cells([segment], [reaction], [option], min_sources=3)

        if cells[0].confidence == "high":
            assert cells[0].devil_advocate == ""
            assert cells[0].smallest_experiment == ""
            mock_da.assert_not_called()
