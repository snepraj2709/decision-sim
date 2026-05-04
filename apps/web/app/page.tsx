"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ─── LocalStorage types ───────────────────────────────────────────────────────

interface RecentProduct {
  url: string;
  snapshotId: string;
  snapshotCreatedAt: string;
  segmentCount: number;
  confidenceSummary: { high: number; medium: number; low: number };
  simulationId: string | null;
}

interface PredictedSentiment {
  optionLetter: string;
  optionTitle: string;
  sentiment: string | null;
}

interface CalibrationItem {
  simulationId: string;
  decisionLabel: string;
  predictedSentiments: PredictedSentiment[];
  createdAt: string;
  outcome: "positive" | "neutral" | "negative" | "mixed" | null;
}

interface ReportedItem {
  simulationId: string;
  decisionLabel: string;
  predicted: string | null;
  reported: string;
  match: boolean;
  optionLetter: string;
}

// ─── Sentiment display ────────────────────────────────────────────────────────

const SENTIMENT_ICON: Record<string, string> = {
  positive: "✓",
  neutral: "~",
  negative: "✗",
  mixed: "±",
};

const SENTIMENT_LABELS: { value: "positive" | "neutral" | "negative" | "mixed"; label: string }[] = [
  { value: "positive", label: "Positive" },
  { value: "neutral", label: "Neutral" },
  { value: "negative", label: "Negative" },
  { value: "mixed", label: "Mixed" },
];

// ─── Shared primitives ───────────────────────────────────────────────────────

function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="font-mono text-[10.5px] uppercase tracking-[0.12em] mb-2"
      style={{ color: "var(--ink-3)" }}
    >
      {children}
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2
      className="text-[17px] font-semibold tracking-tight mb-4"
      style={{ color: "var(--ink)" }}
    >
      {children}
    </h2>
  );
}

function relativeDate(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const days = Math.floor(diff / 86400000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 30) return `${Math.floor(days / 7)} weeks ago`;
  return `${Math.floor(days / 30)} months ago`;
}

function urlHost(url: string): string {
  try {
    return new URL(url).hostname.replace("www.", "");
  } catch {
    return url;
  }
}

// ─── Calibration modal ────────────────────────────────────────────────────────

function CalibrationModal({
  item,
  options,
  onClose,
  onSubmitted,
}: {
  item: CalibrationItem;
  options: { letter: string; title: string }[];
  onClose: () => void;
  onSubmitted: (result: ReportedItem) => void;
}) {
  const [selectedOption, setSelectedOption] = useState(
    options[0]?.letter ?? ""
  );
  const [selectedSentiment, setSelectedSentiment] = useState<
    "positive" | "neutral" | "negative" | "mixed" | null
  >(null);
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    if (!selectedSentiment) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(
        `${API_BASE}/api/v1/simulations/${item.simulationId}/outcome`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            option_letter: selectedOption,
            reported_sentiment: selectedSentiment,
            notes: notes.trim() || null,
          }),
        }
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(body.detail ?? "Something went wrong.");
        return;
      }

      // Fetch accuracy summary
      const accRes = await fetch(
        `${API_BASE}/api/v1/simulations/${item.simulationId}/accuracy`
      );
      let predicted: string | null = null;
      let match = false;
      if (accRes.ok) {
        const acc = await accRes.json();
        predicted = acc.predicted ?? null;
        match = acc.match ?? false;
      }

      onSubmitted({
        simulationId: item.simulationId,
        decisionLabel: item.decisionLabel,
        predicted,
        reported: selectedSentiment,
        match,
        optionLetter: selectedOption,
      });
    } catch {
      setError("Network error — check your connection.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.3)" }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl p-6"
        style={{
          background: "var(--bg-elevated)",
          border: "1px solid var(--line-strong)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="font-mono text-[10.5px] uppercase tracking-wider mb-3"
          style={{ color: "var(--ink-3)" }}
        >
          Calibration check
        </div>
        <h3
          className="text-[16px] font-semibold mb-1"
          style={{ color: "var(--ink)" }}
        >
          What actually happened?
        </h3>
        <p
          className="text-[13px] mb-5 leading-relaxed"
          style={{ color: "var(--ink-2)" }}
        >
          You simulated <strong>{item.decisionLabel}</strong>{" "}
          {relativeDate(item.createdAt)}. Did it land?
        </p>

        {/* Option selector */}
        {options.length > 1 && (
          <div className="mb-4">
            <label
              className="font-mono text-[11px] uppercase tracking-wider block mb-1.5"
              style={{ color: "var(--ink-3)" }}
            >
              Which option did you ship?
            </label>
            <select
              value={selectedOption}
              onChange={(e) => setSelectedOption(e.target.value)}
              className="w-full rounded px-3 py-2 text-[13px]"
              style={{
                background: "var(--bg-sunken)",
                border: "1px solid var(--line-strong)",
                color: "var(--ink)",
              }}
            >
              {options.map((o, index) => (
                <option
                  key={`${o.letter}-${o.title}-${index}`}
                  value={o.letter}
                >
                  {o.letter}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Sentiment buttons */}
        <div className="mb-4">
          <label
            className="font-mono text-[11px] uppercase tracking-wider block mb-1.5"
            style={{ color: "var(--ink-3)" }}
          >
            How did it go?
          </label>
          <div className="grid grid-cols-2 gap-2">
            {SENTIMENT_LABELS.map(({ value, label }) => (
              <button
                key={value}
                onClick={() => setSelectedSentiment(value)}
                className="py-2.5 rounded text-[13px] font-medium"
                style={{
                  background:
                    selectedSentiment === value
                      ? "var(--ink)"
                      : "var(--bg-sunken)",
                  border: "1px solid var(--line-strong)",
                  color:
                    selectedSentiment === value ? "var(--bg)" : "var(--ink)",
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Notes */}
        <div className="mb-5">
          <label
            className="font-mono text-[11px] uppercase tracking-wider block mb-1.5"
            style={{ color: "var(--ink-3)" }}
          >
            Any notes? (optional)
          </label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value.slice(0, 500))}
            placeholder="What surprised you?"
            rows={2}
            className="w-full rounded px-3 py-2 text-[13px] resize-none"
            style={{
              background: "var(--bg-sunken)",
              border: "1px solid var(--line-strong)",
              color: "var(--ink)",
            }}
          />
          <div
            className="font-mono text-[10px] mt-0.5 text-right"
            style={{ color: "var(--ink-3)" }}
          >
            {notes.length}/500
          </div>
        </div>

        {error && (
          <p
            className="text-[12px] mb-3"
            style={{ color: "var(--conf-low)" }}
          >
            {error}
          </p>
        )}

        <button
          onClick={handleSubmit}
          disabled={!selectedSentiment || submitting}
          className="w-full py-2.5 rounded text-[13px] font-semibold mb-3"
          style={{
            background:
              selectedSentiment && !submitting
                ? "var(--ink)"
                : "var(--bg-sunken)",
            color:
              selectedSentiment && !submitting ? "var(--bg)" : "var(--ink-3)",
            border: "1px solid var(--line-strong)",
            cursor: selectedSentiment && !submitting ? "pointer" : "default",
          }}
        >
          {submitting ? "Logging…" : "Log outcome"}
        </button>
        <button
          onClick={onClose}
          className="w-full text-center text-[12px] font-mono"
          style={{ color: "var(--ink-3)" }}
        >
          Remind me later
        </button>
      </div>
    </div>
  );
}

// ─── Accuracy result card ────────────────────────────────────────────────────

function AccuracyCard({ item }: { item: ReportedItem }) {
  return (
    <div
      className="rounded-lg p-4"
      style={{
        background: "var(--bg-elevated)",
        border: "1px solid var(--line)",
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div
            className="text-[13px] font-medium"
            style={{ color: "var(--ink)" }}
          >
            {item.decisionLabel}
          </div>
          <div
            className="font-mono text-[11px] mt-0.5"
            style={{ color: "var(--ink-3)" }}
          >
            {item.optionLetter}
          </div>
        </div>
        <div
          className="shrink-0 font-mono text-[13px]"
          style={{ color: item.match ? "var(--conf-high)" : "var(--conf-low)" }}
        >
          {item.match ? "Match ✓" : "Miss ✗"}
        </div>
      </div>
      <div
        className="mt-2 text-[12px] font-mono"
        style={{ color: "var(--ink-2)" }}
      >
        Predicted {item.predicted ?? "—"} · Reported {item.reported}
        {!item.match && (
          <span style={{ color: "var(--ink-3)" }}>
            {" "}· We&apos;ve adjusted the model.
          </span>
        )}
      </div>
    </div>
  );
}

// ─── Home page ────────────────────────────────────────────────────────────────

export default function HomePage() {
  const router = useRouter();
  const [recent, setRecent] = useState<RecentProduct[]>([]);
  const [calibration, setCalibration] = useState<CalibrationItem[]>([]);
  const [reported, setReported] = useState<ReportedItem[]>([]);
  const [activeCalibration, setActiveCalibration] =
    useState<CalibrationItem | null>(null);

  useEffect(() => {
    try {
      const r = JSON.parse(
        localStorage.getItem("dsim_recent_products") ?? "[]"
      ) as RecentProduct[];
      setRecent(r);
    } catch {
      /* ignore */
    }
    try {
      const q = JSON.parse(
        localStorage.getItem("dsim_calibration_queue") ?? "[]"
      ) as CalibrationItem[];
      setCalibration(q.filter((item) => item.outcome === null));
    } catch {
      /* ignore */
    }
  }, []);

  function handleSubmitted(result: ReportedItem) {
    // Update queue in localStorage — mark as reported.
    try {
      const queue = JSON.parse(
        localStorage.getItem("dsim_calibration_queue") ?? "[]"
      ) as CalibrationItem[];
      const updated = queue.map((q) =>
        q.simulationId === result.simulationId
          ? { ...q, outcome: result.reported as CalibrationItem["outcome"] }
          : q
      );
      localStorage.setItem("dsim_calibration_queue", JSON.stringify(updated));
    } catch {
      /* ignore */
    }
    setCalibration((prev) =>
      prev.filter((q) => q.simulationId !== result.simulationId)
    );
    setReported((prev) => [result, ...prev]);
    setActiveCalibration(null);
  }

  // Build option list for the active modal from the calibration item.
  const activeOptions: { letter: string; title: string }[] =
    activeCalibration?.predictedSentiments.map((ps) => ({
      letter: ps.optionLetter,
      title: ps.optionTitle,
    })) ?? [];

  const mostRecentSim = recent.find((r) => r.simulationId)?.simulationId;

  return (
    <main
      className="min-h-screen px-6 py-10"
      style={{ background: "var(--bg)" }}
    >
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <header className="mb-12">
          <div
            className="font-mono text-[10.5px] uppercase tracking-[0.12em] mb-2"
            style={{ color: "var(--ink-3)" }}
          >
            Decision Simulation Engine
          </div>
          <h1
            className="text-[28px] font-semibold tracking-tight mb-3"
            style={{ color: "var(--ink)" }}
          >
            Flight log
          </h1>
          <p
            className="text-[14px] leading-relaxed max-w-lg"
            style={{ color: "var(--ink-2)" }}
          >
            Simulate how customer segments will react to product decisions —
            before you ship.
          </p>
        </header>

        {/* ── Section 1: CTA ─────────────────────────────────────────────── */}
        <section className="mb-12">
          <button
            onClick={() => router.push("/compose")}
            className="px-6 py-3 rounded text-[15px] font-semibold"
            style={{ background: "var(--ink)", color: "var(--bg)" }}
          >
            Simulate a decision
          </button>

          {mostRecentSim && (
            <div className="mt-3">
              <button
                onClick={() => router.push(`/dashboard/${mostRecentSim}`)}
                className="text-[13px] font-mono"
                style={{ color: "var(--ink-3)" }}
              >
                Or continue where you left off →
              </button>
            </div>
          )}
        </section>

        {/* ── Section 2: Recent products ──────────────────────────────────── */}
        {recent.length > 0 && (
          <section className="mb-12">
            <Eyebrow>Recent products</Eyebrow>
            <SectionHeading>Your simulations</SectionHeading>

            <div className="flex flex-col gap-3">
              {recent.map((item, i) => (
                <div
                  key={`${item.snapshotId}-${i}`}
                  className="relative rounded-lg transition-colors"
                  style={{
                    background: "var(--bg-elevated)",
                    border: "1px solid var(--line)",
                  }}
                >
                  <button
                    type="button"
                    onClick={() =>
                      router.push(`/compose?snapshotId=${item.snapshotId}`)
                    }
                    className="w-full rounded-lg p-4 text-left"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div
                          className="font-mono text-[13px] font-medium truncate"
                          style={{ color: "var(--ink)" }}
                        >
                          {urlHost(item.url)}
                        </div>
                        <div
                          className="text-[12px] mt-0.5 truncate font-mono"
                          style={{ color: "var(--ink-3)" }}
                        >
                          {item.url}
                        </div>
                      </div>
                      <div
                        className="font-mono text-[11px] shrink-0"
                        style={{ color: "var(--ink-3)" }}
                      >
                        {relativeDate(item.snapshotCreatedAt)}
                      </div>
                    </div>

                    <div
                      className={`mt-3 flex items-center gap-4 ${
                        item.simulationId ? "pr-32" : ""
                      }`}
                    >
                      <div
                        className="font-mono text-[11px]"
                        style={{ color: "var(--ink-3)" }}
                      >
                        {item.segmentCount} segments
                      </div>
                      <div className="flex items-center gap-2">
                        {item.confidenceSummary.high > 0 && (
                          <span
                            className="font-mono text-[11px]"
                            style={{ color: "var(--conf-high)" }}
                          >
                            H:{item.confidenceSummary.high}
                          </span>
                        )}
                        {item.confidenceSummary.medium > 0 && (
                          <span
                            className="font-mono text-[11px]"
                            style={{ color: "var(--conf-med)" }}
                          >
                            M:{item.confidenceSummary.medium}
                          </span>
                        )}
                        {item.confidenceSummary.low > 0 && (
                          <span
                            className="font-mono text-[11px]"
                            style={{ color: "var(--conf-low)" }}
                          >
                            L:{item.confidenceSummary.low}
                          </span>
                        )}
                      </div>
                    </div>
                  </button>
                  {item.simulationId && (
                    <button
                      type="button"
                      onClick={() =>
                        router.push(`/dashboard/${item.simulationId}`)
                      }
                      className="absolute bottom-4 right-4 z-10 font-mono text-[11px]"
                      style={{ color: "var(--accent)" }}
                    >
                      View dashboard →
                    </button>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {/* ── Section 3: Calibration strip ────────────────────────────────── */}
        {calibration.length > 0 && (
          <section className="mb-12">
            <Eyebrow>Calibration</Eyebrow>
            <SectionHeading>Did it land?</SectionHeading>
            <p
              className="text-[13px] mb-4 leading-relaxed"
              style={{ color: "var(--ink-2)" }}
            >
              You simulated these decisions. Logging what actually happened
              sharpens future predictions.
            </p>

            <div className="flex flex-col gap-3">
              {calibration.map((item) => (
                <div
                  key={item.simulationId}
                  className="rounded-lg p-4"
                  style={{
                    background: "var(--bg-elevated)",
                    border: "1px solid var(--line)",
                  }}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div
                        className="text-[13px] font-medium"
                        style={{ color: "var(--ink)" }}
                      >
                        {item.decisionLabel}
                      </div>
                      <div
                        className="font-mono text-[11px] mt-0.5"
                        style={{ color: "var(--ink-3)" }}
                      >
                        You simulated this {relativeDate(item.createdAt)} — did it land?
                      </div>
                    </div>
                    <button
                      onClick={() => setActiveCalibration(item)}
                      className="shrink-0 px-3 py-1.5 rounded text-[12px] font-medium"
                      style={{
                        background: "var(--bg-sunken)",
                        border: "1px solid var(--line-strong)",
                        color: "var(--ink-2)",
                      }}
                    >
                      What happened?
                    </button>
                  </div>

                  {item.predictedSentiments.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-3">
                      {item.predictedSentiments.map((ps, index) => (
                        <div
                          key={`${ps.optionLetter}-${ps.optionTitle}-${ps.sentiment ?? "none"}-${index}`}
                          className="flex items-center gap-1.5"
                        >
                          <span
                            className="font-mono text-[11px]"
                            style={{ color: "var(--ink-3)" }}
                          >
                            {ps.optionTitle}
                          </span>
                          {ps.sentiment && (
                            <span
                              className="font-mono text-[12px]"
                              style={{ color: "var(--ink-2)" }}
                            >
                              {SENTIMENT_ICON[ps.sentiment] ?? ps.sentiment}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {/* ── Section 4: Reported outcomes ────────────────────────────────── */}
        {reported.length > 0 && (
          <section className="mb-12">
            <Eyebrow>Reported</Eyebrow>
            <SectionHeading>Outcomes logged</SectionHeading>
            <div className="flex flex-col gap-3">
              {reported.map((item) => (
                <AccuracyCard key={item.simulationId} item={item} />
              ))}
            </div>
          </section>
        )}

        {/* Footer */}
        <footer className="pt-8 border-t" style={{ borderColor: "var(--line)" }}>
          <button
            onClick={() => router.push("/calibration")}
            className="font-mono text-[12px]"
            style={{ color: "var(--ink-3)" }}
          >
            Model accuracy →
          </button>
        </footer>
      </div>

      {/* Calibration modal */}
      {activeCalibration && (
        <CalibrationModal
          item={activeCalibration}
          options={activeOptions}
          onClose={() => setActiveCalibration(null)}
          onSubmitted={handleSubmitted}
        />
      )}
    </main>
  );
}
