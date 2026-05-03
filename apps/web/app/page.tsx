"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

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
  outcome: "positive" | "neutral" | "negative" | null;
}

// ─── Sentiment display ────────────────────────────────────────────────────────

const SENTIMENT_ICON: Record<string, string> = {
  positive: "✓",
  neutral: "~",
  negative: "✗",
  mixed: "±",
};

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
  onClose,
  onAnswer,
}: {
  item: CalibrationItem;
  onClose: () => void;
  onAnswer: (outcome: "positive" | "neutral" | "negative") => void;
}) {
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
          className="text-[16px] font-semibold mb-2"
          style={{ color: "var(--ink)" }}
        >
          What actually happened?
        </h3>
        <p
          className="text-[13px] mb-5 leading-relaxed"
          style={{ color: "var(--ink-2)" }}
        >
          You simulated <strong>{item.decisionLabel}</strong>{" "}
          {relativeDate(item.createdAt)}. How did it land?
        </p>
        <div className="flex gap-3">
          {(
            [
              { value: "positive", label: "It worked" },
              { value: "neutral", label: "Mixed" },
              { value: "negative", label: "It didn't land" },
            ] as const
          ).map(({ value, label }) => (
            <button
              key={value}
              onClick={() => onAnswer(value)}
              className="flex-1 py-2.5 rounded text-[13px] font-medium"
              style={{
                background: "var(--bg-sunken)",
                border: "1px solid var(--line-strong)",
                color: "var(--ink)",
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          onClick={onClose}
          className="mt-4 w-full text-center text-[12px] font-mono"
          style={{ color: "var(--ink-3)" }}
        >
          Remind me later
        </button>
      </div>
    </div>
  );
}

// ─── Home page ────────────────────────────────────────────────────────────────

export default function HomePage() {
  const router = useRouter();
  const [recent, setRecent] = useState<RecentProduct[]>([]);
  const [calibration, setCalibration] = useState<CalibrationItem[]>([]);
  const [activeCalibration, setActiveCalibration] =
    useState<CalibrationItem | null>(null);

  useEffect(() => {
    try {
      const r = JSON.parse(
        localStorage.getItem("dsim_recent_products") ?? "[]",
      ) as RecentProduct[];
      setRecent(r);
    } catch {
      /* ignore */
    }
    try {
      const q = JSON.parse(
        localStorage.getItem("dsim_calibration_queue") ?? "[]",
      ) as CalibrationItem[];
      setCalibration(q.filter((item) => item.outcome === null));
    } catch {
      /* ignore */
    }
  }, []);

  function handleCalibrationAnswer(
    item: CalibrationItem,
    outcome: "positive" | "neutral" | "negative",
  ) {
    try {
      const queue = JSON.parse(
        localStorage.getItem("dsim_calibration_queue") ?? "[]",
      ) as CalibrationItem[];
      const updated = queue.map((q) =>
        q.simulationId === item.simulationId ? { ...q, outcome } : q,
      );
      localStorage.setItem("dsim_calibration_queue", JSON.stringify(updated));
    } catch {
      /* ignore */
    }
    setCalibration((prev) =>
      prev.filter((q) => q.simulationId !== item.simulationId),
    );
    setActiveCalibration(null);
  }

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
                <button
                  key={`${item.snapshotId}-${i}`}
                  onClick={() =>
                    router.push(`/compose?snapshotId=${item.snapshotId}`)
                  }
                  className="w-full text-left rounded-lg p-4 transition-colors"
                  style={{
                    background: "var(--bg-elevated)",
                    border: "1px solid var(--line)",
                  }}
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

                  <div className="mt-3 flex items-center gap-4">
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
                    {item.simulationId && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          router.push(`/dashboard/${item.simulationId}`);
                        }}
                        className="ml-auto font-mono text-[11px]"
                        style={{ color: "var(--accent)" }}
                      >
                        View dashboard →
                      </button>
                    )}
                  </div>
                </button>
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
                        Simulated {relativeDate(item.createdAt)}
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
                      {item.predictedSentiments.map((ps) => (
                        <div
                          key={ps.optionLetter}
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
      </div>

      {/* Calibration modal */}
      {activeCalibration && (
        <CalibrationModal
          item={activeCalibration}
          onClose={() => setActiveCalibration(null)}
          onAnswer={(outcome) =>
            handleCalibrationAnswer(activeCalibration, outcome)
          }
        />
      )}
    </main>
  );
}
