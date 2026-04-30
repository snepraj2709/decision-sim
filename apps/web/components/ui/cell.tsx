/**
 * Cell — the unit of the Comparative Dashboard grid.
 *
 * A Cell shows a churn % range (low–high) with a confidence state. Three
 * visual states:
 *   - high:    bold tabular-nums, solid range bar, no decoration
 *   - medium:  dashed inner outline, lighter bar opacity
 *   - low:     diagonal stripe background, italic, striped range bar
 *
 * Cells are buttons — clicking opens the cell's reasoning trace + evidence
 * panel. Only Low/Medium confidence cells get the prominent devil's-advocate
 * affordance; High cells get a quieter "stress-test" trigger so the dashboard
 * doesn't feel uniformly anxious.
 */

import { type Confidence, tokens } from "@/lib/confidence";
import { ConfidenceGlyph } from "./confidence-band";

interface RangeBarProps {
  low: number;
  high: number;
  confidence: Confidence;
}

function RangeBar({ low, high, confidence }: RangeBarProps) {
  const t = tokens(confidence);
  // Map 0..MAX to 0..1; MAX=80 fits the churn % scale well
  const MAX = 80;
  const left = Math.min(low, MAX) / MAX;
  const right = Math.min(high, MAX) / MAX;
  const w = Math.max(0.04, right - left);

  const opacity =
    confidence === "high" ? 0.9 : confidence === "medium" ? 0.7 : 0.55;

  const fill =
    confidence === "low"
      ? `repeating-linear-gradient(135deg, ${t.fg} 0 2px, transparent 2px 5px)`
      : t.fg;

  return (
    <div
      className="relative w-full h-[6px] rounded-full"
      style={{ background: "var(--line-soft)" }}
    >
      <div
        className="absolute top-0 h-full rounded-full"
        style={{
          left: `${left * 100}%`,
          width: `${w * 100}%`,
          background: fill,
          opacity,
        }}
      />
      {/* Tick marks at 25/50/75% */}
      {[0.25, 0.5, 0.75].map((tk) => (
        <span
          key={tk}
          className="absolute top-0 h-full"
          style={{
            left: `${tk * 100}%`,
            width: 1,
            background: "var(--bg-elevated)",
          }}
        />
      ))}
    </div>
  );
}

interface CellProps {
  rangeLow: number;
  rangeHigh: number;
  confidence: Confidence;
  /** When true, additionally fades the cell — used for whole-row degradation */
  degraded?: boolean;
  active?: boolean;
  onClick?: () => void;
}

export function Cell({
  rangeLow,
  rangeHigh,
  confidence,
  degraded = false,
  active = false,
  onClick,
}: CellProps) {
  const t = tokens(confidence);
  const stripeClass = confidence === "low" ? "lc-stripe" : "";

  return (
    <button
      onClick={onClick}
      className={`relative w-full h-full px-4 py-3.5 text-left transition-all ${stripeClass}`}
      style={{
        background: active ? t.soft : "var(--bg-elevated)",
        borderLeft: "1px solid var(--line)",
        opacity: degraded ? 0.78 : 1,
      }}
    >
      {/* Dashed inner outline for medium confidence */}
      {confidence === "medium" && (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-1 rounded"
          style={{ border: `1px dashed ${t.line}` }}
        />
      )}

      <div className="relative flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <ConfidenceGlyph
            confidence={confidence}
            size={confidence === "high" ? 10 : 11}
          />
          <span
            className="font-mono text-[14px] tabular-nums whitespace-nowrap"
            style={{
              color: "var(--ink)",
              fontWeight: confidence === "high" ? 600 : 500,
              fontStyle: confidence === "low" ? "italic" : "normal",
              letterSpacing: "-0.01em",
            }}
          >
            {rangeLow}–{rangeHigh}
            <span style={{ color: "var(--ink-3)" }}>%</span>
          </span>
        </div>
        <span
          className="font-mono text-[10px] uppercase tracking-wider whitespace-nowrap shrink-0"
          style={{
            color: t.fg,
            fontStyle: confidence === "low" ? "italic" : "normal",
          }}
        >
          {confidence === "low" ? "low" : confidence === "medium" ? "med" : "high"}
        </span>
      </div>

      <div className="relative mt-2 flex items-center gap-1">
        <RangeBar low={rangeLow} high={rangeHigh} confidence={confidence} />
      </div>
    </button>
  );
}
