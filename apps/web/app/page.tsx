/**
 * Step 1 demo page.
 *
 * What this proves:
 *   1. The design tokens are wired correctly — primitives render at all three
 *      confidence states and physically look different (filled / ringed /
 *      striped, plus italics + stripe pattern for Low).
 *   2. The Next.js → FastAPI link works — health status reflects backend.
 *
 * Step 5 replaces this page with the real Saved Products / flight-log home.
 */

import { ConfidenceBand } from "@/components/ui/confidence-band";
import { Cell } from "@/components/ui/cell";
import { type Confidence } from "@/lib/confidence";
import { api } from "@/lib/api";

const CONF_STATES: Confidence[] = ["high", "medium", "low"];

async function getHealth() {
  try {
    return await api.health();
  } catch (err) {
    return { error: err instanceof Error ? err.message : "Unknown error" };
  }
}

export default async function Home() {
  const health = await getHealth();

  return (
    <main className="min-h-screen px-8 py-10 max-w-5xl mx-auto">
      <header className="mb-10">
        <div
          className="font-mono text-[10.5px] uppercase tracking-[0.12em] mb-2"
          style={{ color: "var(--ink-3)" }}
        >
          Decision Simulation Engine — Step 1 scaffolding
        </div>
        <h1
          className="text-[28px] font-semibold tracking-tight"
          style={{ color: "var(--ink)" }}
        >
          Tokens & primitives smoke test
        </h1>
        <p
          className="mt-2 text-[14px] leading-relaxed max-w-2xl"
          style={{ color: "var(--ink-2)" }}
        >
          If everything below renders correctly — three visually distinct
          confidence states, the API health card showing &quot;ok&quot; — Step 1
          is wired correctly and Step 2 (the scrape pipeline) can begin.
        </p>
      </header>

      {/* ── API Health ───────────────────────────────────────────────────── */}
      <section className="mb-10">
        <SectionEyebrow>API health</SectionEyebrow>
        <div
          className="mt-2 rounded-md p-4 font-mono text-[12.5px]"
          style={{
            background: "var(--bg-elevated)",
            border: "1px solid var(--line)",
            color: "var(--ink-2)",
          }}
        >
          <pre className="whitespace-pre-wrap">
            {JSON.stringify(health, null, 2)}
          </pre>
        </div>
      </section>

      {/* ── ConfidenceBand at all three states ───────────────────────────── */}
      <section className="mb-10">
        <SectionEyebrow>ConfidenceBand</SectionEyebrow>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          {CONF_STATES.map((c) => (
            <ConfidenceBand key={c} confidence={c} size="sm" />
          ))}
          {CONF_STATES.map((c) => (
            <ConfidenceBand key={`${c}-lg`} confidence={c} size="lg" />
          ))}
          <ConfidenceBand confidence="low" hypothesis />
        </div>
      </section>

      {/* ── Cell at all three states ─────────────────────────────────────── */}
      <section className="mb-10">
        <SectionEyebrow>Cell — dashboard grid unit</SectionEyebrow>
        <div
          className="mt-3 grid grid-cols-3 rounded-md overflow-hidden"
          style={{
            border: "1px solid var(--line)",
            background: "var(--bg-elevated)",
          }}
        >
          <Cell rangeLow={3} rangeHigh={8} confidence="high" />
          <Cell rangeLow={20} rangeHigh={30} confidence="medium" />
          <Cell rangeLow={50} rangeHigh={70} confidence="low" degraded />
        </div>
        <p
          className="mt-3 text-[12.5px] leading-relaxed"
          style={{ color: "var(--ink-3)" }}
        >
          The High cell uses a solid filled glyph and bold weight. Medium has a
          dashed inner outline and ringed glyph. Low has the diagonal stripe
          pattern, italic mono, and a striped range bar — and is faded to 78%
          opacity to show whole-row degradation.
        </p>
      </section>
    </main>
  );
}

function SectionEyebrow({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="font-mono text-[10.5px] uppercase tracking-[0.12em]"
      style={{ color: "var(--ink-3)" }}
    >
      {children}
    </div>
  );
}
