import { Fragment } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Simulation, Segment, SimulationCell } from "@/lib/api";
import type { Confidence } from "@/lib/confidence";
import { PrintButton } from "./print-button";

// ─── Helpers ──────────────────────────────────────────────────────────────────

const CONF_WEIGHT: Record<Confidence, number> = { high: 3, medium: 2, low: 1 };

function weightedChurn(cells: SimulationCell[]): number {
  let totalW = 0;
  let sum = 0;
  for (const c of cells) {
    const w = CONF_WEIGHT[c.confidence];
    totalW += w;
    sum += ((c.range_low + c.range_high) / 2) * w;
  }
  return totalW > 0 ? sum / totalW : 100;
}

function normalizeHorizon(raw: string | null): string {
  if (!raw) return "Immediate";
  const l = raw.toLowerCase();
  if (l.includes("180") || l.includes("6 month")) return "180d+";
  if (l.includes("90") || l.includes("3 month") || l.includes("quarter")) return "90d";
  if (l.includes("30") || l.includes("month")) return "30d";
  return "Immediate";
}

// cell.option_letter = original DecisionOption.label (e.g. "Price +20%")
function uniqueOptionLetters(cells: SimulationCell[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const c of cells) {
    if (!seen.has(c.option_letter)) { seen.add(c.option_letter); out.push(c.option_letter); }
  }
  return out;
}

function rankedOptions(simulation: Simulation) {
  return uniqueOptionLetters(simulation.cells)
    .map((letter) => {
      const cells = simulation.cells.filter((c) => c.option_letter === letter);
      return { letter, cells, churn: weightedChurn(cells) };
    })
    .sort((a, b) => a.churn - b.churn);
}

// ─── Confidence chip ─────────────────────────────────────────────────────────

const CONF_COLORS: Record<Confidence, { fg: string; bg: string; border: string }> = {
  high:   { fg: "var(--conf-high)",  bg: "var(--conf-high-soft)",  border: "var(--conf-high-line)"  },
  medium: { fg: "var(--conf-med)",   bg: "var(--conf-med-soft)",   border: "var(--conf-med-line)"   },
  low:    { fg: "var(--conf-low)",   bg: "var(--conf-low-soft)",   border: "var(--conf-low-line)"   },
};

function ConfChip({ conf }: { conf: Confidence }) {
  const c = CONF_COLORS[conf];
  return (
    <span
      className="inline-block px-1.5 py-0.5 rounded text-[11px] font-mono align-middle mx-1"
      style={{ color: c.fg, background: c.bg, border: `1px solid ${c.border}` }}
    >
      {conf}
    </span>
  );
}

// ─── Compact grid ────────────────────────────────────────────────────────────

const SENTIMENT_ICON: Record<string, string> = {
  positive: "✓",
  neutral: "~",
  negative: "✗",
  mixed: "±",
};

function CompactGrid({
  simulation,
  segments,
  optionLetters,
}: {
  simulation: Simulation;
  segments: Segment[];
  optionLetters: string[];
}) {
  return (
    <div
      className="overflow-x-auto"
      style={{ border: "1px solid var(--line)", borderRadius: 8, overflow: "hidden" }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: `minmax(140px, 180px) repeat(${optionLetters.length}, 1fr)`,
          minWidth: 180 + optionLetters.length * 120,
        }}
      >
        {/* Header */}
        <div style={{ background: "var(--bg-sunken)", borderBottom: "1px solid var(--line)", padding: "8px 12px" }} />
        {optionLetters.map((letter) => (
          <div
            key={letter}
            style={{
              background: "var(--bg-sunken)",
              borderBottom: "1px solid var(--line)",
              borderLeft: "1px solid var(--line)",
              padding: "8px 12px",
            }}
          >
            <div className="text-[12px] font-medium" style={{ color: "var(--ink)" }}>
              {letter}
            </div>
          </div>
        ))}

        {/* Rows */}
        {segments.map((seg) => (
          <Fragment key={seg.id}>
            <div
              style={{
                padding: "8px 12px",
                borderBottom: "1px solid var(--line)",
                background: "var(--bg-elevated)",
              }}
            >
              <div className="text-[12px] font-medium" style={{ color: "var(--ink)" }}>
                {seg.name}
              </div>
            </div>
            {optionLetters.map((letter) => {
              const cell = simulation.cells.find(
                (c) => c.segment_id === seg.id && c.option_letter === letter,
              );
              if (!cell) {
                return (
                  <div
                    key={`empty-${seg.id}-${letter}`}
                    style={{
                      borderBottom: "1px solid var(--line)",
                      borderLeft: "1px solid var(--line)",
                      background: "var(--bg-elevated)",
                    }}
                  />
                );
              }
              return (
                <div
                  key={`${seg.id}-${letter}`}
                  style={{
                    padding: "8px 12px",
                    borderBottom: "1px solid var(--line)",
                    borderLeft: "1px solid var(--line)",
                    background: "var(--bg-elevated)",
                    opacity: cell.confidence === "low" ? 0.78 : 1,
                  }}
                >
                  <div className="flex items-center gap-1.5">
                    {cell.reaction_sentiment && (
                      <span className="font-mono text-[12px]" style={{ color: "var(--ink-2)" }}>
                        {SENTIMENT_ICON[cell.reaction_sentiment] ?? cell.reaction_sentiment}
                      </span>
                    )}
                    <span className="font-mono text-[11px]" style={{ color: "var(--ink-2)" }}>
                      {cell.range_low}–{cell.range_high}%
                    </span>
                    <ConfChip conf={cell.confidence} />
                  </div>
                </div>
              );
            })}
          </Fragment>
        ))}
      </div>
    </div>
  );
}



// ─── Memo page ────────────────────────────────────────────────────────────────

export default async function MemoPage({
  params,
}: {
  params: Promise<{ simulationId: string }>;
}) {
  const { simulationId } = await params;
  const simulation = await api.getSimulation(simulationId);
  const segments = await api.getSegments(simulation.snapshot_id);
  const segmentById = new Map(segments.map((s) => [s.id, s]));

  const optionLetters = uniqueOptionLetters(simulation.cells);
  const ranked = rankedOptions(simulation);
  const best = ranked[0];
  const second = ranked[1];

  // Counter-cases from low/medium cells with devil_advocate text
  const devilCells = simulation.cells
    .filter((c) => (c.confidence === "low" || c.confidence === "medium") && c.devil_advocate)
    .slice(0, 3);

  // Experiments grouped by time horizon
  const experimentCells = simulation.cells.filter((c) => c.invalidating_experiment);
  const groups: Record<string, { cell: SimulationCell; seg: Segment | undefined }[]> = {};
  for (const cell of experimentCells) {
    const h = normalizeHorizon(cell.time_horizon);
    if (!groups[h]) groups[h] = [];
    groups[h].push({ cell, seg: segmentById.get(cell.segment_id) });
  }
  const HORIZON_ORDER = ["Immediate", "30d", "90d", "180d+"];

  return (
    <>
      <style>{`
        @media print {
          .print-hide { display: none !important; }
          body { background: white !important; color: black !important; }
          .memo-root { max-width: 100% !important; padding: 0 !important; }
        }
      `}</style>

      <main
        className="memo-root min-h-screen px-6 py-10"
        style={{ background: "var(--bg)" }}
      >
        <div className="max-w-3xl mx-auto">

          {/* Nav */}
          <div className="print-hide flex items-center justify-between mb-10">
            <Link
              href={`/dashboard/${simulation.id}`}
              className="font-mono text-[11px] uppercase tracking-wider"
              style={{ color: "var(--ink-3)" }}
            >
              ← Dashboard
            </Link>
            <PrintButton />
          </div>

          {/* Header */}
          <div className="mb-10">
            <div
              className="font-mono text-[10.5px] uppercase tracking-[0.12em] mb-2"
              style={{ color: "var(--ink-3)" }}
            >
              Decision memo
            </div>
            <h1
              className="text-[28px] font-semibold tracking-tight mb-2"
              style={{ color: "var(--ink)", fontFamily: "var(--font-source-serif)" }}
            >
              {optionLetters.join(" vs ")}
            </h1>
            <div className="font-mono text-[12px]" style={{ color: "var(--ink-3)" }}>
              {segments.length} segments · {simulation.cells.length} cells ·{" "}
              {new Date(simulation.created_at).toLocaleDateString("en-US", {
                year: "numeric",
                month: "long",
                day: "numeric",
              })}
            </div>
          </div>

          {/* ── 1. Recommendation ──────────────────────────────────── */}
          {best && (
            <section
              className="mb-10 p-6 rounded-lg"
              style={{ background: "var(--bg-elevated)", border: "1px solid var(--line)" }}
            >
              <h2
                className="text-[18px] font-semibold mb-4"
                style={{ color: "var(--ink)", fontFamily: "var(--font-source-serif)" }}
              >
                Recommendation
              </h2>

              <p className="text-[15px] leading-relaxed mb-4" style={{ color: "var(--ink)" }}>
                Ship <strong>{best.letter}</strong>. It has the lowest projected
                churn across segments (confidence-weighted average:{" "}
                <span className="font-mono">{Math.round(best.churn)}%</span>).
              </p>

              {best.cells.map((cell) => {
                const seg = segmentById.get(cell.segment_id);
                if (!seg) return null;
                return (
                  <p
                    key={cell.id}
                    className="text-[14px] leading-relaxed mb-2"
                    style={{ color: "var(--ink-2)" }}
                  >
                    <strong>{seg.name}</strong> will churn at{" "}
                    <span className="font-mono">{cell.range_low}–{cell.range_high}%</span>
                    {cell.time_horizon ? ` within ${cell.time_horizon}` : ""}.
                    <ConfChip conf={cell.confidence} />
                  </p>
                );
              })}

              {second && (
                <p className="mt-4 text-[13px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
                  Closest alternative:{" "}
                  <strong style={{ color: "var(--ink-2)" }}>{second.letter}</strong>{" "}
                  at <span className="font-mono">{Math.round(second.churn)}%</span> weighted churn.
                </p>
              )}
            </section>
          )}

          {/* ── 2. Counter-case ─────────────────────────────────────── */}
          <section
            className="mb-10 p-6 rounded-lg"
            style={{ background: "var(--bg-elevated)", border: "1.5px solid var(--conf-low-line)" }}
          >
            <h2
              className="text-[18px] font-semibold mb-2"
              style={{ color: "var(--ink)", fontFamily: "var(--font-source-serif)" }}
            >
              Before you ship
            </h2>
            <p className="text-[13px] mb-5" style={{ color: "var(--ink-3)" }}>
              Three things that could make this wrong:
            </p>

            {devilCells.length === 0 && (
              <p className="text-[14px]" style={{ color: "var(--ink-3)" }}>
                No significant counter-cases at low or medium confidence.
              </p>
            )}

            {devilCells.map((cell, i) => {
              const seg = segmentById.get(cell.segment_id);
              return (
                <div key={cell.id} className="mb-5">
                  <div
                    className="font-mono text-[10.5px] uppercase tracking-wider mb-1"
                    style={{ color: "var(--ink-3)" }}
                  >
                    {i + 1}. {cell.option_letter} × {seg?.name ?? "Unknown"}
                    <ConfChip conf={cell.confidence} />
                  </div>
                  <p
                    className="text-[14px] leading-relaxed pl-3 italic"
                    style={{ color: "var(--ink-2)", borderLeft: "2px solid var(--conf-low-line)" }}
                  >
                    {cell.devil_advocate}
                  </p>
                  <Link
                    href={`/dashboard/${simulation.id}`}
                    className="print-hide font-mono text-[11px] mt-1 block"
                    style={{ color: "var(--accent)" }}
                  >
                    View cell →
                  </Link>
                </div>
              );
            })}
          </section>

          {/* ── 3. Invalidating experiments ─────────────────────────── */}
          {Object.keys(groups).length > 0 && (
            <section className="mb-10">
              <h2
                className="text-[18px] font-semibold mb-5"
                style={{ color: "var(--ink)", fontFamily: "var(--font-source-serif)" }}
              >
                Smallest invalidating experiments
              </h2>
              {HORIZON_ORDER.filter((h) => groups[h]).map((horizon) => (
                <div key={horizon} className="mb-6">
                  <div
                    className="font-mono text-[10.5px] uppercase tracking-wider mb-3"
                    style={{ color: "var(--ink-3)" }}
                  >
                    {horizon}
                  </div>
                  <div className="flex flex-col gap-3">
                    {groups[horizon].map(({ cell, seg }) => (
                      <div
                        key={cell.id}
                        className="p-4 rounded-lg"
                        style={{ background: "var(--bg-elevated)", border: "1px solid var(--line)" }}
                      >
                        <div
                          className="font-mono text-[10px] uppercase tracking-wider mb-1"
                          style={{ color: "var(--ink-3)" }}
                        >
                          {cell.option_letter} × {seg?.name ?? "Unknown"}
                        </div>
                        <p className="text-[14px] leading-relaxed" style={{ color: "var(--ink)" }}>
                          {cell.invalidating_experiment}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </section>
          )}

          {/* ── 4. Segment reactions table ───────────────────────────── */}
          <section className="mb-10">
            <h2
              className="text-[18px] font-semibold mb-5"
              style={{ color: "var(--ink)", fontFamily: "var(--font-source-serif)" }}
            >
              Segment reactions
            </h2>
            <CompactGrid
              simulation={simulation}
              segments={segments}
              optionLetters={optionLetters}
            />
          </section>

          {/* Footer */}
          <div className="text-[12px] font-mono text-center pb-8" style={{ color: "var(--ink-4)" }}>
            Generated by Decision Simulation Engine ·{" "}
            {new Date(simulation.created_at).toISOString()}
          </div>
        </div>
      </main>
    </>
  );
}
