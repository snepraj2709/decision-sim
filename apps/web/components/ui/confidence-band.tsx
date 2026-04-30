/**
 * ConfidenceBand — the most-used confidence affordance in the app.
 *
 * Three visual states, each physically distinct:
 *   - high:    solid filled circle glyph, firm copy
 *   - medium:  open ring glyph, regular copy
 *   - low:     striped lozenge glyph, italic, optional "Hypothesis" relabel
 *
 * Ported from the design's primitives.jsx. The visual language is locked —
 * do not change colors or shapes here without updating tokens.css.
 */

import { type Confidence, CONFIDENCE_LABEL, tokens } from "@/lib/confidence";

interface ConfidenceGlyphProps {
  confidence: Confidence;
  size?: number;
}

export function ConfidenceGlyph({ confidence, size = 10 }: ConfidenceGlyphProps) {
  const t = tokens(confidence);

  if (confidence === "high") {
    return (
      <span
        aria-hidden
        style={{
          width: size,
          height: size,
          borderRadius: 999,
          background: t.fg,
          display: "inline-block",
        }}
      />
    );
  }

  if (confidence === "medium") {
    return (
      <span
        aria-hidden
        style={{
          width: size,
          height: size,
          borderRadius: 999,
          border: `1.5px solid ${t.fg}`,
          background: "transparent",
          display: "inline-block",
        }}
      />
    );
  }

  // low — striped lozenge
  return (
    <span
      aria-hidden
      style={{
        width: size + 4,
        height: size,
        borderRadius: 2,
        background: `repeating-linear-gradient(135deg, ${t.fg} 0 1.5px, transparent 1.5px 4px)`,
        border: `1px solid ${t.fg}`,
        display: "inline-block",
      }}
    />
  );
}

interface ConfidenceBandProps {
  confidence?: Confidence;
  size?: "sm" | "lg";
  showLabel?: boolean;
  /**
   * When true and confidence === "low", relabels the band as "Hypothesis"
   * and italicizes the text. Use this on segment cards where Low confidence
   * means "this segment is a guess, not a portrait."
   */
  hypothesis?: boolean;
}

export function ConfidenceBand({
  confidence = "high",
  size = "sm",
  showLabel = true,
  hypothesis = false,
}: ConfidenceBandProps) {
  const t = tokens(confidence);
  const text =
    confidence === "low" && hypothesis ? "Hypothesis" : CONFIDENCE_LABEL[confidence];
  const px =
    size === "lg"
      ? "px-2 py-1 text-[12px]"
      : "px-1.5 py-0.5 text-[11px]";

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded ${px} font-medium`}
      style={{
        color: t.fg,
        background: t.soft,
        border: `1px solid ${t.line}`,
        fontStyle: confidence === "low" && hypothesis ? "italic" : "normal",
        letterSpacing: confidence === "high" ? "-0.01em" : 0,
      }}
    >
      <ConfidenceGlyph confidence={confidence} size={size === "lg" ? 11 : 9} />
      {showLabel && <span>{text}</span>}
    </span>
  );
}
