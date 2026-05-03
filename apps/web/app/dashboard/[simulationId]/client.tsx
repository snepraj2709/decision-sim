"use client";

import { Fragment, useState } from "react";
import { useRouter } from "next/navigation";
import { Cell } from "@/components/ui/cell";
import { ConfidenceBand } from "@/components/ui/confidence-band";
import type { Simulation, Segment, SimulationCell, OptionInput } from "@/lib/api";
import type { Confidence } from "@/lib/confidence";

// ─── Sentiment ────────────────────────────────────────────────────────────────

const SENTIMENT_ICON: Record<string, string> = {
  positive: "✓",
  neutral: "~",
  negative: "✗",
  mixed: "±",
};

const SENTIMENT_COLOR: Record<string, string> = {
  positive: "var(--conf-high)",
  neutral: "var(--ink-3)",
  negative: "var(--conf-low)",
  mixed: "var(--conf-med)",
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

// cell.option_letter = the original DecisionOption.label (e.g. "Price +20%")
// OptionInput.letter = first 2 chars of that label (e.g. "Pr") — only used for prefix matching
function matchOption(
  optionLetter: string,
  options: OptionInput[],
): OptionInput | undefined {
  return options.find((o) => optionLetter.startsWith(o.letter));
}

// Unique option letters in encounter order from cells
function uniqueOptionLetters(cells: SimulationCell[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const c of cells) {
    if (!seen.has(c.option_letter)) {
      seen.add(c.option_letter);
      out.push(c.option_letter);
    }
  }
  return out;
}

function findCell(
  cells: SimulationCell[],
  segmentId: string,
  optionLetter: string,
): SimulationCell | undefined {
  return cells.find(
    (c) => c.segment_id === segmentId && c.option_letter === optionLetter,
  );
}

function confidenceCounts(
  cells: SimulationCell[],
): Record<Confidence, number> {
  const out: Record<Confidence, number> = { high: 0, medium: 0, low: 0 };
  for (const c of cells) out[c.confidence]++;
  return out;
}

// ─── Drawer ───────────────────────────────────────────────────────────────────

function DrawerSection({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-5">
      <div
        className="font-mono text-[10px] uppercase tracking-wider mb-1.5"
        style={{ color: "var(--ink-3)" }}
      >
        {label}
      </div>
      <div
        className="text-[13px] leading-relaxed"
        style={{ color: "var(--ink-2)" }}
      >
        {children}
      </div>
    </div>
  );
}

function CellDrawer({
  cell,
  segmentName,
  optionLabel,
  onClose,
}: {
  cell: SimulationCell;
  segmentName: string;
  optionLabel: string;
  onClose: () => void;
}) {
  const isLowMed =
    cell.confidence === "low" || cell.confidence === "medium";

  return (
    <div
      className="fixed top-0 bottom-0 z-10 overflow-y-auto"
      style={{
        right: 208,
        width: 360,
        background: "var(--bg-elevated)",
        borderLeft: "1px solid var(--line-strong)",
      }}
    >
      <div
        className="px-5 py-4"
        style={{ borderBottom: "1px solid var(--line)" }}
      >
        <div className="flex items-start justify-between gap-2 mb-2">
          <div
            className="font-mono text-[10.5px] uppercase tracking-wider leading-snug"
            style={{ color: "var(--ink-3)" }}
          >
            {optionLabel} × {segmentName}
          </div>
          <button
            onClick={onClose}
            className="font-mono text-[12px] shrink-0"
            style={{ color: "var(--ink-3)" }}
          >
            ✕
          </button>
        </div>
        <div className="flex items-center gap-2 mt-1">
          <ConfidenceBand confidence={cell.confidence} size="sm" />
          <span
            className="font-mono text-[12px]"
            style={{ color: "var(--ink-2)" }}
          >
            {cell.range_low}–{cell.range_high}% churn
          </span>
          {cell.reaction_sentiment && (
            <span
              className="font-mono text-[13px] ml-auto font-semibold"
              style={{
                color:
                  SENTIMENT_COLOR[cell.reaction_sentiment] ?? "var(--ink-3)",
              }}
            >
              {SENTIMENT_ICON[cell.reaction_sentiment] ??
                cell.reaction_sentiment}
            </span>
          )}
        </div>
      </div>

      <div className="px-5 py-5">
        {cell.reasoning_trace && (
          <DrawerSection label="In-character reasoning">
            {cell.reasoning_trace}
          </DrawerSection>
        )}

        {cell.top_concern && (
          <DrawerSection label="Top concern">
            {cell.top_concern}
          </DrawerSection>
        )}

        {isLowMed && cell.devil_advocate && (
          <DrawerSection label="Devil&rsquo;s advocate">
            <div
              className="pl-3 italic"
              style={{
                borderLeft: "2px solid var(--conf-low-line)",
                color: "var(--ink-2)",
              }}
            >
              {cell.devil_advocate}
            </div>
          </DrawerSection>
        )}

        {cell.invalidating_experiment && (
          <DrawerSection label="Smallest invalidating experiment">
            {cell.invalidating_experiment}
          </DrawerSection>
        )}

        {cell.time_horizon && (
          <DrawerSection label="Time horizon">
            <span className="font-mono">{cell.time_horizon}</span>
          </DrawerSection>
        )}
      </div>
    </div>
  );
}

// ─── Right Rail ───────────────────────────────────────────────────────────────

function RightRail({
  simulation,
  optionLetters,
  onExport,
}: {
  simulation: Simulation;
  optionLetters: string[];
  onExport: () => void;
}) {
  return (
    <div
      className="fixed top-0 right-0 bottom-0 overflow-y-auto z-20"
      style={{
        width: 208,
        background: "var(--bg-elevated)",
        borderLeft: "1px solid var(--line)",
      }}
    >
      <div className="px-4 py-5">
        <div
          className="font-mono text-[10px] uppercase tracking-wider mb-4"
          style={{ color: "var(--ink-3)" }}
        >
          Confidence summary
        </div>

        {optionLetters.map((letter) => {
          const optCells = simulation.cells.filter(
            (c) => c.option_letter === letter,
          );
          const counts = confidenceCounts(optCells);
          return (
            <div key={letter} className="mb-4">
              <div
                className="text-[12px] font-medium mb-1.5 leading-snug"
                style={{ color: "var(--ink)" }}
              >
                {letter}
              </div>
              <div className="flex flex-col gap-1">
                {(["high", "medium", "low"] as Confidence[]).map((conf) => (
                  <div
                    key={conf}
                    className="flex items-center justify-between"
                  >
                    <ConfidenceBand confidence={conf} size="sm" showLabel />
                    <span
                      className="font-mono text-[12px]"
                      style={{ color: "var(--ink-2)" }}
                    >
                      {counts[conf]}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          );
        })}

        <div
          className="mt-6 pt-4"
          style={{ borderTop: "1px solid var(--line)" }}
        >
          <button
            onClick={onExport}
            className="w-full px-3 py-2.5 rounded text-[13px] font-medium"
            style={{ background: "var(--ink)", color: "var(--bg)" }}
          >
            Export memo
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Dashboard Client ─────────────────────────────────────────────────────────

export function DashboardClient({
  simulation,
  segments,
}: {
  simulation: Simulation;
  segments: Segment[];
}) {
  const router = useRouter();
  const [activeCell, setActiveCell] = useState<SimulationCell | null>(null);

  const segmentById = new Map(segments.map((s) => [s.id, s]));
  const optionLetters = uniqueOptionLetters(simulation.cells);

  function handleCellClick(cell: SimulationCell) {
    setActiveCell((prev) => (prev?.id === cell.id ? null : cell));
  }

  return (
    <div
      className="min-h-screen"
      style={{ background: "var(--bg)", marginRight: 208 }}
    >
      {/* Top bar */}
      <header
        className="sticky top-0 z-30 px-6 py-3 flex items-center gap-3"
        style={{
          background: "var(--bg-elevated)",
          borderBottom: "1px solid var(--line)",
        }}
      >
        <button
          onClick={() => router.push("/")}
          className="font-mono text-[11px] uppercase tracking-wider"
          style={{ color: "var(--ink-3)" }}
        >
          ← Flight log
        </button>
        <span style={{ color: "var(--line-strong)" }}>|</span>
        <span
          className="font-mono text-[11px] truncate"
          style={{ color: "var(--ink-3)" }}
        >
          {optionLetters.join(" vs ")}
        </span>
        {simulation.overall_confidence && (
          <div className="ml-auto shrink-0">
            <ConfidenceBand
              confidence={simulation.overall_confidence}
              size="sm"
            />
          </div>
        )}
      </header>

      {/* Grid */}
      <div className="overflow-x-auto">
        <div
          style={{
            display: "grid",
            gridTemplateColumns: `minmax(180px, 220px) repeat(${optionLetters.length}, minmax(160px, 1fr))`,
            minWidth: 220 + optionLetters.length * 160,
          }}
        >
          {/* Header row */}
          <div
            className="sticky top-[49px] z-10 px-4 py-3"
            style={{
              background: "var(--bg-elevated)",
              borderBottom: "1px solid var(--line-strong)",
              borderRight: "1px solid var(--line)",
            }}
          />
          {optionLetters.map((letter) => {
            const matched = matchOption(letter, simulation.options);
            return (
              <div
                key={letter}
                className="sticky top-[49px] z-10 px-4 py-3"
                style={{
                  background: "var(--bg-elevated)",
                  borderBottom: "1px solid var(--line-strong)",
                  borderLeft: "1px solid var(--line)",
                }}
              >
                <div
                  className="text-[14px] font-semibold"
                  style={{ color: "var(--ink)" }}
                >
                  {letter}
                </div>
                {matched?.title && (
                  <div
                    className="text-[11px] mt-0.5 leading-snug"
                    style={{ color: "var(--ink-3)" }}
                  >
                    {matched.title}
                  </div>
                )}
              </div>
            );
          })}

          {/* Data rows */}
          {segments.map((seg) => {
            const isLow = seg.confidence === "low";
            return (
              <Fragment key={seg.id}>
                {/* Segment label */}
                <div
                  className={`px-4 py-4 ${isLow ? "lc-grain" : ""}`}
                  style={{
                    background: "var(--bg-elevated)",
                    borderBottom: "1px solid var(--line)",
                    borderRight: "1px solid var(--line)",
                    opacity: isLow ? 0.78 : 1,
                  }}
                >
                  <div
                    className="text-[13px] font-medium leading-snug"
                    style={{
                      color: "var(--ink)",
                      fontStyle: isLow ? "italic" : "normal",
                    }}
                  >
                    {seg.name}
                  </div>
                  <div className="mt-1.5">
                    <ConfidenceBand
                      confidence={seg.confidence}
                      size="sm"
                      hypothesis={isLow}
                    />
                  </div>
                  {seg.share_pct != null && (
                    <div
                      className="mt-1 font-mono text-[10.5px]"
                      style={{ color: "var(--ink-3)" }}
                    >
                      ~{seg.share_pct}% of market
                    </div>
                  )}
                </div>

                {/* Grid cells */}
                {optionLetters.map((letter) => {
                  const cell = findCell(simulation.cells, seg.id, letter);
                  if (!cell) {
                    return (
                      <div
                        key={`empty-${seg.id}-${letter}`}
                        style={{
                          background: "var(--bg-elevated)",
                          borderBottom: "1px solid var(--line)",
                          borderLeft: "1px solid var(--line)",
                        }}
                      />
                    );
                  }
                  const isActive = activeCell?.id === cell.id;
                  return (
                    <div
                      key={`${seg.id}-${letter}`}
                      className="relative"
                      style={{ borderBottom: "1px solid var(--line)" }}
                    >
                      {cell.reaction_sentiment && (
                        <span
                          className="absolute top-2.5 left-4 z-10 pointer-events-none font-mono text-[12px] font-semibold"
                          style={{
                            color:
                              SENTIMENT_COLOR[cell.reaction_sentiment] ??
                              "var(--ink-3)",
                          }}
                        >
                          {SENTIMENT_ICON[cell.reaction_sentiment] ??
                            cell.reaction_sentiment}
                        </span>
                      )}
                      <Cell
                        rangeLow={cell.range_low}
                        rangeHigh={cell.range_high}
                        confidence={cell.confidence}
                        degraded={cell.confidence === "low"}
                        active={isActive}
                        onClick={() => handleCellClick(cell)}
                      />
                    </div>
                  );
                })}
              </Fragment>
            );
          })}
        </div>
      </div>

      {/* Drawer */}
      {activeCell && (
        <CellDrawer
          cell={activeCell}
          segmentName={
            segmentById.get(activeCell.segment_id)?.name ?? "Unknown segment"
          }
          optionLabel={activeCell.option_letter}
          onClose={() => setActiveCell(null)}
        />
      )}

      {/* Right rail */}
      <RightRail
        simulation={simulation}
        optionLetters={optionLetters}
        onExport={() => router.push(`/memo/${simulation.id}`)}
      />
    </div>
  );
}
