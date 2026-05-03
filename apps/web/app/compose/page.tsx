"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type {
  ProductSnapshot,
  Segment,
  DecisionOption,
  ConfidentField,
} from "@/lib/api";
import type { Confidence } from "@/lib/confidence";
import { ConfidenceBand } from "@/components/ui/confidence-band";

// ─── Progress messages ────────────────────────────────────────────────────────

const SNAPSHOT_MSG: Record<string, string> = {
  queued: "Scraping...",
  started: "Searching...",
  finished: "Extracting...",
};

const ICP_MSG: Record<string, string> = {
  queued: "Analyzing search results...",
  started: "Building segments...",
};

const SIM_MSG: Record<string, string> = {
  queued: "Queuing simulation...",
  started: "Running simulation...",
};

// ─── Shared primitives ───────────────────────────────────────────────────────

function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="font-mono text-[10.5px] uppercase tracking-[0.12em] mb-1"
      style={{ color: "var(--ink-3)" }}
    >
      {children}
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2
      className="text-[22px] font-semibold tracking-tight mb-6"
      style={{ color: "var(--ink)" }}
    >
      {children}
    </h2>
  );
}

function ErrorMsg({ msg }: { msg: string }) {
  return (
    <p
      className="mt-3 text-[13px] font-mono"
      style={{ color: "var(--conf-low)" }}
    >
      {msg}
    </p>
  );
}

function PrimaryButton({
  children,
  disabled,
  onClick,
  type = "button",
}: {
  children: React.ReactNode;
  disabled?: boolean;
  onClick?: () => void;
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className="px-5 py-2.5 rounded text-[14px] font-medium transition-opacity"
      style={{
        background: disabled ? "var(--line)" : "var(--ink)",
        color: disabled ? "var(--ink-3)" : "var(--bg)",
        cursor: disabled ? "not-allowed" : "pointer",
      }}
    >
      {children}
    </button>
  );
}

function GhostButton({
  children,
  onClick,
}: {
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="px-4 py-2.5 rounded text-[14px]"
      style={{ color: "var(--ink-3)", border: "1px solid var(--line)" }}
    >
      {children}
    </button>
  );
}

function StepIndicator({
  step,
  total,
}: {
  step: number;
  total: number;
}) {
  return (
    <div className="flex items-center gap-2 mb-8">
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          className="h-1 rounded-full"
          style={{
            width: 32,
            background:
              i < step
                ? "var(--ink)"
                : i === step
                  ? "var(--ink-2)"
                  : "var(--line-strong)",
          }}
        />
      ))}
      <span
        className="ml-2 font-mono text-[11px]"
        style={{ color: "var(--ink-3)" }}
      >
        {step + 1} / {total}
      </span>
    </div>
  );
}

// ─── Step A — URL input ───────────────────────────────────────────────────────

function StepURL({
  onComplete,
}: {
  onComplete: (snap: ProductSnapshot, url: string) => void;
}) {
  const [url, setUrl] = useState("");
  const [phase, setPhase] = useState<"idle" | "working" | "error">("idle");
  const [message, setMessage] = useState("Scraping...");
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = url.trim();
    if (!trimmed) return;
    setPhase("working");
    setMessage("Scraping...");
    setError("");
    try {
      const job = await api.createSnapshot(trimmed);
      const status = await api.pollSnapshotJob(job.job_id, (s) => {
        setMessage(SNAPSHOT_MSG[s.status] ?? "Working...");
      });
      if (status.status === "failed") {
        throw new Error(status.error ?? "Snapshot failed");
      }
      const snap = await api.getSnapshot(status.snapshot_id!);
      onComplete(snap, trimmed);
    } catch (err) {
      setPhase("error");
      setError(err instanceof Error ? err.message : "Something went wrong");
    }
  }

  return (
    <div className="max-w-xl mx-auto pt-20">
      <StepIndicator step={0} total={4} />
      <Eyebrow>Step 1 of 4</Eyebrow>
      <SectionHeading>Paste a product URL</SectionHeading>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://linear.app"
          disabled={phase === "working"}
          className="w-full px-4 py-3 rounded text-[15px] font-mono"
          style={{
            background: "var(--bg-elevated)",
            border: "1.5px solid var(--line-strong)",
            color: "var(--ink)",
            outline: "none",
          }}
        />
        <div className="flex items-center gap-3">
          <PrimaryButton
            type="submit"
            disabled={phase === "working" || !url.trim()}
          >
            {phase === "working" ? message : "Analyze"}
          </PrimaryButton>
        </div>
      </form>
      {error && <ErrorMsg msg={error} />}
    </div>
  );
}

// ─── Step B — Snapshot review ────────────────────────────────────────────────

const SNAPSHOT_FIELD_LABELS: Array<{
  key: keyof ProductSnapshot;
  label: string;
}> = [
  { key: "category", label: "Category" },
  { key: "value_prop", label: "Value proposition" },
  { key: "pricing", label: "Pricing" },
  { key: "features", label: "Key features" },
  { key: "audience", label: "Audience" },
  { key: "competitors", label: "Competitors" },
];

function SnapshotFieldRow({
  label,
  field,
}: {
  label: string;
  field: ConfidentField | null;
}) {
  if (!field) return null;
  return (
    <div
      className="py-3 flex items-start gap-4"
      style={{ borderBottom: "1px solid var(--line)" }}
    >
      <div
        className="w-36 shrink-0 font-mono text-[11px] uppercase tracking-wider pt-0.5"
        style={{ color: "var(--ink-3)" }}
      >
        {label}
      </div>
      <div className="flex-1 text-[14px]" style={{ color: "var(--ink)" }}>
        {field.value}
      </div>
      <div className="shrink-0">
        <ConfidenceBand confidence={field.confidence} size="sm" />
      </div>
    </div>
  );
}

function StepSnapshot({
  snapshot,
  onComplete,
  onBack,
}: {
  snapshot: ProductSnapshot;
  onComplete: (segs: Segment[]) => void;
  onBack: () => void;
}) {
  const [phase, setPhase] = useState<"idle" | "working" | "error">("idle");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const hasLowSignal = SNAPSHOT_FIELD_LABELS.some(
    ({ key }) => (snapshot[key] as ConfidentField | null)?.confidence === "low",
  );

  async function handleGenerateSegments() {
    setPhase("working");
    setMessage("Analyzing search results...");
    setError("");
    try {
      const job = await api.createICPs(snapshot.id);
      const status = await api.pollICPJob(job.job_id, (s) => {
        setMessage(ICP_MSG[s.status] ?? "Working...");
      });
      if (status.status === "failed") {
        throw new Error(status.error ?? "Segment generation failed");
      }
      const segs = await api.getSegments(snapshot.id);
      onComplete(segs);
    } catch (err) {
      setPhase("error");
      setError(err instanceof Error ? err.message : "Something went wrong");
    }
  }

  return (
    <div className="max-w-2xl mx-auto pt-12 pb-20">
      <StepIndicator step={1} total={4} />
      <Eyebrow>Step 2 of 4</Eyebrow>
      <SectionHeading>Product snapshot</SectionHeading>

      {hasLowSignal && (
        <div
          className="mb-6 px-4 py-3 rounded text-[13px]"
          style={{
            background: "var(--conf-low-soft)",
            border: "1px solid var(--conf-low-line)",
            color: "var(--conf-low)",
          }}
        >
          Limited signal — some fields have low confidence. Results may be
          less accurate.
        </div>
      )}

      <div
        className="rounded-lg overflow-hidden mb-8"
        style={{
          border: "1px solid var(--line)",
          background: "var(--bg-elevated)",
        }}
      >
        {SNAPSHOT_FIELD_LABELS.map(({ key, label }) => (
          <SnapshotFieldRow
            key={key}
            label={label}
            field={snapshot[key] as ConfidentField | null}
          />
        ))}
      </div>

      <div className="flex items-center gap-3">
        <PrimaryButton
          disabled={phase === "working"}
          onClick={handleGenerateSegments}
        >
          {phase === "working" ? message : "Generate customer segments"}
        </PrimaryButton>
        <GhostButton onClick={onBack}>Back</GhostButton>
      </div>
      {error && <ErrorMsg msg={error} />}
    </div>
  );
}

// ─── Step C — Segment studio ─────────────────────────────────────────────────

function SegmentCard({ segment }: { segment: Segment }) {
  const isLow = segment.confidence === "low";
  const isMed = segment.confidence === "medium";

  return (
    <div
      className={`rounded-lg p-5 ${isLow ? "lc-stripe" : ""}`}
      style={{
        background: "var(--bg-elevated)",
        border: isMed
          ? "1px dashed var(--conf-med-line)"
          : "1px solid var(--line)",
        opacity: isLow ? 0.78 : 1,
      }}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <h3
          className="text-[15px] font-semibold"
          style={{
            color: "var(--ink)",
            fontStyle: isLow ? "italic" : "normal",
          }}
        >
          {segment.name}
        </h3>
        <ConfidenceBand
          confidence={segment.confidence}
          hypothesis={isLow}
          size="sm"
        />
      </div>

      {segment.descriptor && (
        <p
          className="text-[13px] leading-relaxed mb-3"
          style={{
            color: "var(--ink-2)",
            fontStyle: isLow ? "italic" : "normal",
          }}
        >
          {segment.descriptor}
        </p>
      )}

      {segment.job_to_be_done && (
        <div className="mb-3">
          <div
            className="font-mono text-[10px] uppercase tracking-wider mb-1"
            style={{ color: "var(--ink-3)" }}
          >
            Job to be done
          </div>
          <p
            className="text-[13px]"
            style={{
              color: "var(--ink-2)",
              fontStyle: isLow ? "italic" : "normal",
            }}
          >
            {segment.job_to_be_done}
          </p>
        </div>
      )}

      {segment.drivers && segment.drivers.length > 0 && (
        <div className="mb-3">
          <div
            className="font-mono text-[10px] uppercase tracking-wider mb-2"
            style={{ color: "var(--ink-3)" }}
          >
            Drivers
          </div>
          <div className="flex flex-wrap gap-1.5">
            {segment.drivers.map((d) => (
              <span
                key={d.label}
                className="px-2 py-0.5 rounded text-[12px] font-mono"
                style={{
                  background: "var(--bg-sunken)",
                  color: "var(--ink-2)",
                  border: "1px solid var(--line)",
                }}
              >
                {d.label}
              </span>
            ))}
          </div>
        </div>
      )}

      {segment.evidence.length > 0 && (
        <div>
          <div
            className="font-mono text-[10px] uppercase tracking-wider mb-2"
            style={{ color: "var(--ink-3)" }}
          >
            Evidence
          </div>
          <div className="flex flex-col gap-2">
            {segment.evidence.slice(0, 3).map((e) => (
              <blockquote
                key={e.id}
                className="text-[12.5px] leading-relaxed pl-3"
                style={{
                  borderLeft: "2px solid var(--line-strong)",
                  color: "var(--ink-2)",
                  fontStyle: "italic",
                }}
              >
                &ldquo;{e.quote}&rdquo;
                <footer
                  className="mt-1 font-mono text-[10.5px] not-italic"
                  style={{ color: "var(--ink-3)" }}
                >
                  — {e.source}
                </footer>
              </blockquote>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StepSegments({
  segments,
  onComplete,
  onBack,
}: {
  segments: Segment[];
  onComplete: () => void;
  onBack: () => void;
}) {
  return (
    <div className="max-w-2xl mx-auto pt-12 pb-20">
      <StepIndicator step={2} total={4} />
      <Eyebrow>Step 3 of 4</Eyebrow>
      <SectionHeading>Customer segments</SectionHeading>

      <div className="flex flex-col gap-4 mb-8">
        {segments.map((seg) => (
          <SegmentCard key={seg.id} segment={seg} />
        ))}
      </div>

      <div className="flex items-center gap-3">
        <PrimaryButton onClick={onComplete}>Define decisions</PrimaryButton>
        <GhostButton onClick={onBack}>Back</GhostButton>
      </div>
    </div>
  );
}

// ─── Step D — Decision composer ───────────────────────────────────────────────

type OptionRow = {
  id: string;
  label: string;
  description: string;
  option_type: DecisionOption["option_type"];
};

const OPTION_TYPES: Array<{ value: DecisionOption["option_type"]; label: string }> =
  [
    { value: "pricing", label: "Pricing" },
    { value: "feature", label: "Feature" },
    { value: "copy", label: "Copy" },
    { value: "bundling", label: "Bundling" },
    { value: "onboarding", label: "Onboarding" },
  ];

function newRow(): OptionRow {
  return {
    id: Math.random().toString(36).slice(2),
    label: "",
    description: "",
    option_type: "pricing",
  };
}

function StepDecisions({
  snapshot,
  segments,
  url,
  onComplete,
  onBack,
}: {
  snapshot: ProductSnapshot;
  segments: Segment[];
  url: string;
  onComplete: (simulationId: string) => void;
  onBack: () => void;
}) {
  const [rows, setRows] = useState<OptionRow[]>([newRow(), newRow()]);
  const [phase, setPhase] = useState<"idle" | "working" | "error">("idle");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const canSubmit =
    rows.length >= 2 &&
    rows.every((r) => r.label.trim() && r.description.trim());

  function updateRow(id: string, patch: Partial<OptionRow>) {
    setRows((prev) =>
      prev.map((r) => (r.id === id ? { ...r, ...patch } : r)),
    );
  }

  function addRow() {
    if (rows.length < 5) setRows((prev) => [...prev, newRow()]);
  }

  function removeRow(id: string) {
    if (rows.length > 2) setRows((prev) => prev.filter((r) => r.id !== id));
  }

  async function handleSubmit() {
    if (!canSubmit) return;
    setPhase("working");
    setMessage("Queuing simulation...");
    setError("");

    const options: DecisionOption[] = rows.map((r) => ({
      label: r.label.trim(),
      description: r.description.trim(),
      option_type: r.option_type,
    }));

    try {
      const jobResp = await api.createSimulation(snapshot.id, options);
      const jobStatus = await api.pollSimulationJob(
        jobResp.job_id,
        (s) => { setMessage(SIM_MSG[s.status] ?? "Running..."); },
      );
      if (jobStatus.status === "failed") {
        throw new Error(jobStatus.error ?? "Simulation failed");
      }

      const simulation = await api.getSimulation(jobResp.simulation_id);

      // Save to localStorage
      try {
        const confSummary = {
          high: segments.filter((s) => s.confidence === "high").length,
          medium: segments.filter((s) => s.confidence === "medium").length,
          low: segments.filter((s) => s.confidence === "low").length,
        };

        const recentItem = {
          url,
          snapshotId: snapshot.id,
          snapshotCreatedAt: snapshot.created_at,
          segmentCount: segments.length,
          confidenceSummary: confSummary,
          simulationId: simulation.id,
        };
        const recent: unknown[] = JSON.parse(
          localStorage.getItem("dsim_recent_products") ?? "[]",
        );
        recent.unshift(recentItem);
        localStorage.setItem(
          "dsim_recent_products",
          JSON.stringify(recent.slice(0, 10)),
        );

        const topSentiments = simulation.options.map((opt) => {
          const optCells = simulation.cells.filter(
            (c) => c.option_letter === opt.letter,
          );
          const best = optCells.sort(
            (a, b) =>
              (a.range_low + a.range_high) - (b.range_low + b.range_high),
          )[0];
          return {
            optionLetter: opt.letter,
            optionTitle: opt.title,
            sentiment: best?.reaction_sentiment ?? null,
          };
        });

        const calibrationItem = {
          simulationId: simulation.id,
          decisionLabel: simulation.options.map((o) => o.title).join(" vs "),
          predictedSentiments: topSentiments,
          createdAt: simulation.created_at,
          outcome: null,
        };
        const queue: unknown[] = JSON.parse(
          localStorage.getItem("dsim_calibration_queue") ?? "[]",
        );
        queue.unshift(calibrationItem);
        localStorage.setItem(
          "dsim_calibration_queue",
          JSON.stringify(queue),
        );
      } catch {
        // localStorage errors are non-fatal
      }

      onComplete(simulation.id);
    } catch (err) {
      setPhase("error");
      setError(err instanceof Error ? err.message : "Something went wrong");
    }
  }

  const inputStyle = {
    background: "var(--bg-elevated)",
    border: "1px solid var(--line-strong)",
    color: "var(--ink)",
    outline: "none",
    borderRadius: 6,
  };

  return (
    <div className="max-w-2xl mx-auto pt-12 pb-20">
      <StepIndicator step={3} total={4} />
      <Eyebrow>Step 4 of 4</Eyebrow>
      <SectionHeading>Define your decision options</SectionHeading>

      <div className="flex flex-col gap-3 mb-6">
        {rows.map((row, i) => (
          <div
            key={row.id}
            className="rounded-lg p-4"
            style={{
              background: "var(--bg-elevated)",
              border: "1px solid var(--line)",
            }}
          >
            <div className="flex items-center gap-2 mb-3">
              <span
                className="font-mono text-[11px] uppercase tracking-wider"
                style={{ color: "var(--ink-3)" }}
              >
                Option {String.fromCharCode(65 + i)}
              </span>
              {rows.length > 2 && (
                <button
                  type="button"
                  onClick={() => removeRow(row.id)}
                  className="ml-auto text-[12px] font-mono"
                  style={{ color: "var(--ink-3)" }}
                >
                  Remove
                </button>
              )}
            </div>
            <div className="flex flex-col gap-2">
              <input
                type="text"
                placeholder="Short name (e.g. Free Trial)"
                value={row.label}
                onChange={(e) => updateRow(row.id, { label: e.target.value })}
                className="w-full px-3 py-2 text-[14px]"
                style={inputStyle}
              />
              <input
                type="text"
                placeholder="What is this decision? (e.g. Add 14-day free trial)"
                value={row.description}
                onChange={(e) =>
                  updateRow(row.id, { description: e.target.value })
                }
                className="w-full px-3 py-2 text-[13px]"
                style={inputStyle}
              />
              <select
                value={row.option_type}
                onChange={(e) =>
                  updateRow(row.id, {
                    option_type: e.target.value as DecisionOption["option_type"],
                  })
                }
                className="px-3 py-2 text-[13px] font-mono"
                style={{ ...inputStyle, width: "auto" }}
              >
                {OPTION_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        ))}
      </div>

      {rows.length < 5 && (
        <button
          type="button"
          onClick={addRow}
          className="mb-6 text-[13px] font-mono"
          style={{ color: "var(--accent)" }}
        >
          + Add option
        </button>
      )}

      <div className="flex items-center gap-3">
        <PrimaryButton
          disabled={!canSubmit || phase === "working"}
          onClick={handleSubmit}
        >
          {phase === "working" ? message : "Run simulation"}
        </PrimaryButton>
        <GhostButton onClick={onBack}>Back</GhostButton>
      </div>
      {error && <ErrorMsg msg={error} />}
    </div>
  );
}

// ─── Root Composer ────────────────────────────────────────────────────────────

type ComposerStep = "url" | "snapshot" | "segments" | "decisions";

export default function ComposePage() {
  const router = useRouter();
  const [step, setStep] = useState<ComposerStep>("url");
  const [url, setUrl] = useState("");
  const [snapshot, setSnapshot] = useState<ProductSnapshot | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);

  // Handle ?snapshotId= for "continue where you left off"
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const snapshotId = params.get("snapshotId");
    if (!snapshotId) return;
    (async () => {
      try {
        const snap = await api.getSnapshot(snapshotId);
        const segs = await api.getSegments(snapshotId);
        setSnapshot(snap);
        setSegments(segs);
        setStep("segments");
      } catch {
        // Silently fall through to normal URL input
      }
    })();
  }, []);

  return (
    <main className="min-h-screen px-6" style={{ background: "var(--bg)" }}>
      {step === "url" && (
        <StepURL
          onComplete={(snap, u) => {
            setSnapshot(snap);
            setUrl(u);
            setStep("snapshot");
          }}
        />
      )}

      {step === "snapshot" && snapshot && (
        <StepSnapshot
          snapshot={snapshot}
          onComplete={(segs) => {
            setSegments(segs);
            setStep("segments");
          }}
          onBack={() => setStep("url")}
        />
      )}

      {step === "segments" && snapshot && (
        <StepSegments
          segments={segments}
          onComplete={() => setStep("decisions")}
          onBack={() => setStep("snapshot")}
        />
      )}

      {step === "decisions" && snapshot && (
        <StepDecisions
          snapshot={snapshot}
          segments={segments}
          url={url}
          onComplete={(simId) => router.push(`/dashboard/${simId}`)}
          onBack={() => setStep("segments")}
        />
      )}
    </main>
  );
}
