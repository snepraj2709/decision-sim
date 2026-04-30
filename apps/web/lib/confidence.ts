/**
 * Confidence — the central UX primitive.
 *
 * This type is mirrored by the API's Pydantic Literal["high","medium","low"].
 * The two MUST stay in sync. Step 5 will add a CI check that codegens these
 * types from the OpenAPI schema; until then, this is the canonical source.
 */
export type Confidence = "high" | "medium" | "low";

export const CONFIDENCE_LABEL: Record<Confidence, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
};

/**
 * Token bundle for a confidence state. Use `tokens(c).fg` etc. when you need
 * inline `style={{ color: ... }}` — this keeps token references explicit and
 * grep-able instead of hidden in Tailwind class strings.
 */
export const tokens = (c: Confidence) =>
  ({
    high:   { fg: "var(--conf-high)",   soft: "var(--conf-high-soft)",   line: "var(--conf-high-line)"   },
    medium: { fg: "var(--conf-med)",    soft: "var(--conf-med-soft)",    line: "var(--conf-med-line)"    },
    low:    { fg: "var(--conf-low)",    soft: "var(--conf-low-soft)",    line: "var(--conf-low-line)"    },
  }[c]);
