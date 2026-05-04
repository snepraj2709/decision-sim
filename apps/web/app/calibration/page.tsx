"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const OPTION_TYPES = ["pricing", "feature", "copy", "bundling", "onboarding"] as const;
const SENTIMENTS = ["positive", "neutral", "negative", "mixed"] as const;

interface RateCell {
  rate: number;
  sample_count: number;
}

type RatesData = Record<string, Record<string, RateCell>>;

function label(cell: RateCell): string {
  if (cell.sample_count === 0) return "Prior";
  if (cell.sample_count >= 5) return "Validated";
  return `n=${cell.sample_count}`;
}

function labelColor(cell: RateCell): string {
  if (cell.sample_count === 0) return "var(--ink-3)";
  if (cell.sample_count >= 5) return "var(--conf-high)";
  return "var(--conf-med)";
}

export default function CalibrationPage() {
  const router = useRouter();
  const [rates, setRates] = useState<RatesData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/calibration/rates`)
      .then((r) => r.json())
      .then((d) => setRates(d.rates))
      .catch(() => setError("Could not load calibration data."));
  }, []);

  return (
    <main
      className="min-h-screen px-6 py-10"
      style={{ background: "var(--bg)" }}
    >
      <div className="max-w-3xl mx-auto">
        <header className="mb-10">
          <button
            onClick={() => router.push("/")}
            className="font-mono text-[12px] mb-6 block"
            style={{ color: "var(--ink-3)" }}
          >
            ← Flight log
          </button>
          <div
            className="font-mono text-[10.5px] uppercase tracking-[0.12em] mb-2"
            style={{ color: "var(--ink-3)" }}
          >
            Decision Simulation Engine
          </div>
          <h1
            className="text-[24px] font-semibold tracking-tight mb-2"
            style={{ color: "var(--ink)" }}
          >
            Model accuracy
          </h1>
          <p
            className="text-[13px] leading-relaxed max-w-lg"
            style={{ color: "var(--ink-2)" }}
          >
            Base rates per option type and sentiment. Prior rows (n=0) are
            seeded from historical defaults. Validated rows have 5+ real
            outcomes and the model has adjusted to them.
          </p>
        </header>

        {error && (
          <p className="text-[13px]" style={{ color: "var(--conf-low)" }}>
            {error}
          </p>
        )}

        {rates && (
          <div
            className="rounded-xl overflow-hidden"
            style={{ border: "1px solid var(--line)" }}
          >
            {/* Header row */}
            <div
              className="grid font-mono text-[11px] uppercase tracking-wider px-4 py-2.5"
              style={{
                gridTemplateColumns: "160px repeat(4, 1fr)",
                background: "var(--bg-sunken)",
                color: "var(--ink-3)",
                borderBottom: "1px solid var(--line)",
              }}
            >
              <div>Option type</div>
              {SENTIMENTS.map((s) => (
                <div key={s} className="text-center">
                  {s}
                </div>
              ))}
            </div>

            {OPTION_TYPES.map((optType, i) => {
              const typeRates = rates[optType] ?? {};
              return (
                <div
                  key={optType}
                  className="grid px-4 py-3 items-center"
                  style={{
                    gridTemplateColumns: "160px repeat(4, 1fr)",
                    borderBottom:
                      i < OPTION_TYPES.length - 1
                        ? "1px solid var(--line)"
                        : "none",
                    background: "var(--bg-elevated)",
                  }}
                >
                  <div
                    className="font-mono text-[12px] font-medium capitalize"
                    style={{ color: "var(--ink)" }}
                  >
                    {optType}
                  </div>
                  {SENTIMENTS.map((sentiment) => {
                    const cell = typeRates[sentiment];
                    if (!cell) {
                      return (
                        <div
                          key={sentiment}
                          className="text-center font-mono text-[11px]"
                          style={{ color: "var(--ink-3)" }}
                        >
                          —
                        </div>
                      );
                    }
                    return (
                      <div key={sentiment} className="text-center">
                        <div
                          className="font-mono text-[13px] font-medium"
                          style={{ color: "var(--ink)" }}
                        >
                          {(cell.rate * 100).toFixed(0)}%
                        </div>
                        <div
                          className="font-mono text-[10px] mt-0.5"
                          style={{ color: labelColor(cell) }}
                        >
                          {label(cell)}
                        </div>
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        )}

        {!rates && !error && (
          <p
            className="font-mono text-[12px]"
            style={{ color: "var(--ink-3)" }}
          >
            Loading…
          </p>
        )}
      </div>
    </main>
  );
}
