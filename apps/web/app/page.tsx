'use client'

import '@fontsource/dm-serif-display'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { api } from '@/lib/api'

const SERIF: React.CSSProperties = {
  fontFamily: "'DM Serif Display', Georgia, serif",
}

// ─── Inline helpers ───────────────────────────────────────────────────────────

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
}

// ─── Preview card sub-components (inlined) ────────────────────────────────────

function PreviewCellHigh({
  conf, range, note,
}: { conf: string; range: string; note: string }) {
  return (
    <div
      className="p-2 h-full"
      style={{
        border: '1px solid rgba(76,175,112,0.35)',
        background: 'rgba(76,175,112,0.05)',
        borderRadius: 4,
      }}
    >
      <div className="font-mono text-[9px]" style={{ color: '#4CAF70' }}>{conf}</div>
      <div className="font-mono text-[13px] font-semibold" style={{ color: '#4CAF70' }}>{range}</div>
      <div className="text-[9px] mt-1" style={{ color: '#7A7470' }}>{note}</div>
    </div>
  )
}

function PreviewCellMed({
  conf, range, note,
}: { conf: string; range: string; note: string }) {
  return (
    <div
      className="p-2 h-full"
      style={{
        border: '1px dashed rgba(196,127,10,0.45)',
        background: 'rgba(196,127,10,0.04)',
        borderRadius: 4,
      }}
    >
      <div className="font-mono text-[9px] italic" style={{ color: '#C47F0A' }}>{conf}</div>
      <div className="font-mono text-[13px] font-semibold" style={{ color: '#E09410' }}>{range}</div>
      <div className="text-[9px] mt-1" style={{ color: '#7A7470' }}>{note}</div>
    </div>
  )
}

function PreviewCellLow({
  conf, range, note,
}: { conf: string; range: string; note: string }) {
  return (
    <div
      className="relative p-2 h-full overflow-hidden"
      style={{
        border: '1px solid rgba(232,93,48,0.20)',
        background: 'rgba(232,93,48,0.03)',
        borderRadius: 4,
        opacity: 0.78,
      }}
    >
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            'repeating-linear-gradient(-45deg,transparent,transparent 5px,rgba(232,93,48,0.07) 5px,rgba(232,93,48,0.07) 10px)',
        }}
      />
      <div className="relative font-mono text-[9px] italic" style={{ color: '#E85D30' }}>{conf}</div>
      <div className="relative font-mono text-[13px] font-semibold" style={{ color: '#E85D30' }}>{range}</div>
      <div className="relative text-[9px] mt-1" style={{ color: '#7A7470' }}>{note}</div>
    </div>
  )
}

// ─── URL input (reused in hero and CTA) ──────────────────────────────────────

function UrlInput({
  value,
  onChange,
  onSubmit,
  submitting,
  error,
  className = '',
}: {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  submitting: boolean
  error: string | null
  className?: string
}) {
  return (
    <div className={className}>
      <div
        className="flex border border-[#28282E] rounded-md overflow-hidden
          focus-within:border-[#C47F0A] focus-within:ring-2 focus-within:ring-[#C47F0A]/20
          transition-all"
      >
        <input
          type="url"
          value={value}
          onChange={e => onChange(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') onSubmit() }}
          placeholder="https://yourproduct.com"
          className="flex-1 border-none outline-none px-4 py-3 font-mono text-[12px]
            placeholder:text-[#3A3530]"
          style={{ background: '#111113', color: '#EDE8DF' }}
        />
        <button
          onClick={onSubmit}
          disabled={submitting}
          className="bg-[#C47F0A] hover:bg-[#E09410] text-white px-5 py-3
            text-[13px] font-medium transition-colors whitespace-nowrap disabled:opacity-60"
        >
          {submitting ? 'Starting...' : 'Run simulation →'}
        </button>
      </div>
      {error && (
        <p className="font-mono text-[11px] mt-2" style={{ color: '#E85D30' }}>
          {error}
        </p>
      )}
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function LandingPage() {
  const router = useRouter()

  const [heroUrl, setHeroUrl] = useState('')
  const [heroSubmitting, setHeroSubmitting] = useState(false)
  const [heroError, setHeroError] = useState<string | null>(null)

  const [ctaUrl, setCtaUrl] = useState('')
  const [ctaSubmitting, setCtaSubmitting] = useState(false)
  const [ctaError, setCtaError] = useState<string | null>(null)

  async function handleSubmit(
    url: string,
    setSubmitting: (v: boolean) => void,
    setError: (v: string | null) => void,
  ) {
    if (!url.trim() || !url.startsWith('http')) {
      setError('Please enter a full URL including https://')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const data = await api.createSnapshot(url.trim())
      router.push(`/loading-sim/${data.job_id}`)
    } catch {
      setError('Something went wrong. Please try again.')
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen" style={{ background: '#080808', color: '#EDE8DF' }}>

      {/* ── Nav ─────────────────────────────────────────────────────────────── */}
      <nav
        className="sticky top-0 z-50 h-14 border-b flex items-center"
        style={{
          borderColor: '#1C1C22',
          background: 'rgba(7,7,8,0.90)',
          backdropFilter: 'blur(12px)',
        }}
      >
        <div className="max-w-[1100px] mx-auto px-6 md:px-20 w-full flex items-center justify-between">
          <Link href="/" className="font-mono text-[13px] tracking-wider" style={{ color: '#C47F0A' }}>
            DECISION SIM
          </Link>
          <div className="hidden md:flex items-center gap-8">
            <a
              href="#how-it-works"
              className="text-[13px] transition-colors hover:text-[#EDE8DF]"
              style={{ color: '#7A7470' }}
            >
              How it works
            </a>
            <a
              href="#use-cases"
              className="text-[13px] transition-colors hover:text-[#EDE8DF]"
              style={{ color: '#7A7470' }}
            >
              Use cases
            </a>
            <a
              href="#pricing"
              className="text-[13px] transition-colors hover:text-[#EDE8DF]"
              style={{ color: '#7A7470' }}
            >
              Pricing
            </a>
          </div>
          <button
            onClick={() => scrollTo('cta')}
            className="bg-[#C47F0A] hover:bg-[#E09410] text-white px-4 py-1.5
              text-[12px] font-medium rounded transition-colors"
          >
            Run a simulation →
          </button>
        </div>
      </nav>

      {/* ── Hero ────────────────────────────────────────────────────────────── */}
      <section
        className="grid grid-cols-1 lg:grid-cols-2"
        style={{ minHeight: 'calc(100vh - 56px)' }}
      >
        {/* Left */}
        <div className="flex flex-col justify-center px-6 py-12 md:px-16 md:py-20">
          <div
            className="font-mono text-[11px] tracking-[0.14em] uppercase mb-4"
            style={{ color: '#C47F0A' }}
          >
            For Series A–B founders · Growth PMs · Product consultants
          </div>
          <h1
            className="text-[50px] leading-[1.06] font-normal"
            style={{ ...SERIF, color: '#EDE8DF' }}
          >
            Simulate how your customers react —{' '}
            <br />
            <em className="not-italic" style={{ color: '#E09410' }}>
              before you ship.
            </em>
          </h1>
          <p
            className="text-[15px] leading-[1.7] max-w-[420px] mt-4"
            style={{ color: '#7A7470' }}
          >
            Paste your product URL. Describe the decision — a pricing change,
            a feature removal, a rebrand. Get a report showing which customer
            segments will churn, which will upgrade, and why — before you roll
            anything out.
          </p>

          <UrlInput
            value={heroUrl}
            onChange={setHeroUrl}
            onSubmit={() => handleSubmit(heroUrl, setHeroSubmitting, setHeroError)}
            submitting={heroSubmitting}
            error={heroError}
            className="max-w-[500px] mt-8"
          />

          <div className="flex gap-5 mt-3">
            {['✓ Free first simulation', '✓ Results in ~5 minutes', '✓ No account required'].map(t => (
              <span key={t} className="font-mono text-[11px]" style={{ color: '#3A3530' }}>{t}</span>
            ))}
          </div>
        </div>

        {/* Right — simulation preview */}
        <div
          className="hidden lg:flex flex-col justify-center px-12 border-l relative overflow-hidden"
          style={{ borderColor: '#1C1C22', background: '#0D0D0F' }}
        >
          {/* Grid pattern */}
          <div
            className="absolute inset-0 pointer-events-none"
            style={{
              backgroundImage:
                'linear-gradient(#1C1C22 1px, transparent 1px), linear-gradient(90deg, #1C1C22 1px, transparent 1px)',
              backgroundSize: '36px 36px',
              opacity: 0.35,
            }}
          />

          <div
            className="font-mono text-[10px] tracking-[0.1em] uppercase mb-3 relative z-10"
            style={{ color: '#3A3530' }}
          >
            Live simulation — Linear.app · Pricing change
          </div>

          {/* Simulation preview card */}
          <div
            className="border rounded-lg overflow-hidden relative z-10"
            style={{
              borderColor: '#28282E',
              background: '#080808',
              boxShadow: '0 24px 64px rgba(0,0,0,0.5)',
            }}
          >
            {/* Topbar */}
            <div
              className="flex justify-between items-center px-4 py-2.5 border-b"
              style={{ borderColor: '#1C1C22' }}
            >
              <span className="font-mono text-[11px]" style={{ color: '#7A7470' }}>
                linear.app — Raise seat price 30%
              </span>
              <div className="flex items-center gap-1.5 font-mono text-[10px]" style={{ color: '#4CAF70' }}>
                <div
                  className="w-1.5 h-1.5 rounded-full animate-pulse"
                  style={{ background: '#4CAF70' }}
                />
                Simulation complete
              </div>
            </div>

            {/* Column headers */}
            <div
              className="grid border-b"
              style={{
                gridTemplateColumns: '180px 1fr 1fr',
                borderColor: '#1C1C22',
              }}
            >
              {['Segment', 'Option A · +30%', 'Option B · Free tier'].map(h => (
                <div
                  key={h}
                  className="px-3 py-2 font-mono text-[10px] uppercase tracking-[0.06em]"
                  style={{ color: '#3A3530' }}
                >
                  {h}
                </div>
              ))}
            </div>

            {/* Data rows */}
            {[
              {
                seg: 'Power dev teams',
                jtbd: 'JTBD: ship faster',
                a: <PreviewCellHigh conf="HIGH CONFIDENCE" range="12–18% churn" note="Price-insensitive if speed holds" />,
                b: <PreviewCellMed conf="MED CONFIDENCE" range="28–44% trial-down" note="May downgrade to free" />,
              },
              {
                seg: 'Solo devs',
                jtbd: 'JTBD: stay organised cheap',
                a: <PreviewCellLow conf="LOW CONFIDENCE" range="62–78% churn" note="Evaluating alternatives" />,
                b: <PreviewCellHigh conf="HIGH CONFIDENCE" range="7–12% churn" note="Free tier fits JTBD" />,
              },
              {
                seg: 'Growth PM teams',
                jtbd: 'JTBD: cross-team alignment',
                a: <PreviewCellMed conf="MED CONFIDENCE" range="31–47% churn" note="Budget approval friction" />,
                b: <PreviewCellMed conf="MED CONFIDENCE" range="15–22% churn" note="Free may reduce credibility" />,
              },
            ].map((row, i) => (
              <div
                key={i}
                className="grid"
                style={{ gridTemplateColumns: '180px 1fr 1fr' }}
              >
                <div
                  className="px-3 py-3 border-r border-b"
                  style={{ borderColor: '#1C1C22' }}
                >
                  <div className="text-[11px] font-medium" style={{ color: '#EDE8DF' }}>
                    {row.seg}
                  </div>
                  <div className="font-mono text-[9px] mt-0.5" style={{ color: '#3A3530' }}>
                    {row.jtbd}
                  </div>
                </div>
                <div className="p-2 border-r border-b" style={{ borderColor: '#1C1C22' }}>
                  {row.a}
                </div>
                <div className="p-2 border-b" style={{ borderColor: '#1C1C22' }}>
                  {row.b}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Stats bar ───────────────────────────────────────────────────────── */}
      <div className="border-y py-8" style={{ borderColor: '#1C1C22', background: '#0D0D0D' }}>
        <div className="max-w-[1100px] mx-auto px-6 md:px-20 grid grid-cols-3">
          {[
            { num: '$0.31', label: 'API cost per simulation', note: 'Honest number, not rounded up' },
            { num: '~5 min', label: 'End-to-end latency', note: 'Scrape → segment → simulate → memo' },
            { num: '4–5', label: 'Segments per product', note: 'Evidence-anchored, not guessed' },
          ].map(({ num, label, note }) => (
            <div key={num} className="text-center">
              <div className="text-[38px] font-normal" style={{ ...SERIF, color: '#C47F0A' }}>
                {num}
              </div>
              <div className="font-mono text-[11px] tracking-wider mt-1" style={{ color: '#7A7470' }}>
                {label}
              </div>
              <div className="text-[12px] mt-1" style={{ color: '#3A3530' }}>
                {note}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── How it works ────────────────────────────────────────────────────── */}
      <section id="how-it-works" className="py-24">
        <div className="max-w-[1100px] mx-auto px-6 md:px-20">
          <div
            className="font-mono text-[11px] tracking-[0.14em] uppercase mb-3"
            style={{ color: '#C47F0A' }}
          >
            How it works
          </div>
          <h2 className="text-[36px] font-normal mb-4" style={{ ...SERIF, color: '#EDE8DF' }}>
            Three steps between you and a decision memo.
          </h2>
          <p
            className="text-[15px] leading-[1.65] max-w-[520px] mb-12"
            style={{ color: '#7A7470' }}
          >
            No setup. No integrations. Paste a URL, describe your decision, read the simulation.
          </p>

          <div
            className="grid grid-cols-1 md:grid-cols-3 rounded-lg overflow-hidden border"
            style={{ borderColor: '#1C1C22' }}
          >
            {[
              {
                num: '01 — RESEARCH',
                title: 'Paste your product URL',
                desc: 'We scrape your product, pricing pages, and feature copy. Then we pull external signals — reviews, forum posts, analyst coverage — to understand how your actual customers talk about you.',
                detail: 'Sources: G2 · Reddit · Capterra · press · blogs',
              },
              {
                num: '02 — DEFINE',
                title: 'Describe your decision',
                desc: 'Write it in plain English: raise seat price from $8 to $12, remove the free tier, or rebrand from dev tool to ops platform. Compare 2–3 options side by side.',
                detail: 'Supports: pricing · feature gates · copy changes · deprecation',
              },
              {
                num: '03 — READ',
                title: 'Get the simulation report',
                desc: 'A confidence-banded dashboard showing how each customer segment reacts to each option — with churn probability ranges, top concerns, and a mandatory counter-case to the strongest recommendation.',
                detail: 'Output: dashboard · exportable PDF memo',
              },
            ].map((step, i) => (
              <div
                key={step.num}
                className="p-9"
                style={{
                  background: '#111113',
                  borderRight: i < 2 ? '1px solid #1C1C22' : 'none',
                }}
              >
                <div
                  className="font-mono text-[11px] mb-5"
                  style={{ color: '#C47F0A' }}
                >
                  {step.num}
                </div>
                <h3
                  className="text-[22px] font-normal mb-3"
                  style={{ ...SERIF, color: '#EDE8DF' }}
                >
                  {step.title}
                </h3>
                <p className="text-[13px] leading-[1.65]" style={{ color: '#7A7470' }}>
                  {step.desc}
                </p>
                <div
                  className="mt-4 pt-4 border-t font-mono text-[10px]"
                  style={{ borderColor: '#1C1C22', color: '#3A3530' }}
                >
                  {step.detail}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Use cases ───────────────────────────────────────────────────────── */}
      <section
        id="use-cases"
        className="py-24 border-y"
        style={{ borderColor: '#1C1C22', background: '#0D0D0D' }}
      >
        <div className="max-w-[1100px] mx-auto px-6 md:px-20">
          <h2 className="text-[36px] font-normal mb-3" style={{ ...SERIF, color: '#EDE8DF' }}>
            The decisions where it matters.
          </h2>
          <p className="text-[15px]" style={{ color: '#7A7470' }}>
            These are the calls where being wrong costs a quarter.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-12">
            {[
              {
                tag: 'PRICING CHANGE',
                title: 'Raising prices on a product users have grown comfortable with',
                desc: "You've been charging $19/mo for three years. You want $39. Some customers will follow. Some will leave. Which segments are which?",
                chip: "Avg $340k ARR at risk on a $1M SaaS at 20% churn",
                chipColor: '#4CAF70',
                chipBorder: 'rgba(76,175,112,0.2)',
                chipBg: 'rgba(76,175,112,0.05)',
              },
              {
                tag: 'FEATURE DEPRECATION',
                title: "Removing something users love but you can't maintain",
                desc: "You want to kill the CSV export or the legacy dashboard. Some users have built their whole workflow around it. Which ones churn vs adapt?",
                chip: 'Simulate before the support tickets start',
                chipColor: '#C47F0A',
                chipBorder: 'rgba(196,127,10,0.2)',
                chipBg: 'rgba(196,127,10,0.05)',
              },
              {
                tag: 'REPOSITIONING',
                title: 'Shifting ICP from SMB to enterprise mid-growth',
                desc: 'Your website now says enterprise-grade. Your current users are founder-sized teams. Which segments read the new positioning as a betrayal?',
                chip: "Identify the segments you'd be quietly firing",
                chipColor: '#4CAF70',
                chipBorder: 'rgba(76,175,112,0.2)',
                chipBg: 'rgba(76,175,112,0.05)',
              },
            ].map(card => (
              <div
                key={card.tag}
                className="rounded-lg p-7 transition-colors cursor-default"
                style={{ border: '1px solid #1C1C22', background: '#111113' }}
                onMouseEnter={e => (e.currentTarget.style.borderColor = '#28282E')}
                onMouseLeave={e => (e.currentTarget.style.borderColor = '#1C1C22')}
              >
                <div
                  className="font-mono text-[10px] tracking-[0.1em] uppercase mb-4"
                  style={{ color: '#C47F0A' }}
                >
                  {card.tag}
                </div>
                <h3
                  className="text-[19px] font-normal mb-3 leading-[1.2]"
                  style={{ ...SERIF, color: '#EDE8DF' }}
                >
                  {card.title}
                </h3>
                <p className="text-[13px] leading-[1.6] mb-4" style={{ color: '#7A7470' }}>
                  {card.desc}
                </p>
                <span
                  className="font-mono text-[11px] px-3 py-1.5 rounded inline-block"
                  style={{
                    color: card.chipColor,
                    border: `1px solid ${card.chipBorder}`,
                    background: card.chipBg,
                  }}
                >
                  {card.chip}
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Pricing ─────────────────────────────────────────────────────────── */}
      <section id="pricing" className="py-24">
        <div className="max-w-[1100px] mx-auto px-6 md:px-20">
          <h2 className="text-[36px] font-normal mb-3" style={{ ...SERIF, color: '#EDE8DF' }}>
            One simulation. One decision de-risked.
          </h2>
          <p className="text-[15px] max-w-[480px]" style={{ color: '#7A7470' }}>
            A bad pricing move costs months of churn recovery. A simulation costs
            less than the Notion workspace you forgot to cancel.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-w-[780px] mt-12">
            {/* Single simulation */}
            <div
              className="rounded-lg p-9"
              style={{ border: '1px solid #1C1C22', background: '#111113' }}
            >
              <div
                className="font-mono text-[11px] tracking-[0.1em] uppercase mb-3"
                style={{ color: '#7A7470' }}
              >
                SINGLE SIMULATION
              </div>
              <div
                className="text-[44px] font-normal leading-[1]"
                style={{ ...SERIF, color: '#EDE8DF' }}
              >
                $49
                <span className="font-sans text-[14px]" style={{ color: '#7A7470' }}>
                  {' '}/per simulation
                </span>
              </div>
              <p
                className="text-[13px] mt-2 mb-6 pb-6 border-b"
                style={{ color: '#7A7470', borderColor: '#1C1C22' }}
              >
                One product URL. One decision. Full report. No subscription needed.
              </p>
              <ul className="list-none mb-7">
                {[
                  'Up to 5 customer segments identified from evidence',
                  'Compare 3 decision options side by side',
                  'Confidence-banded dashboard (Low / Medium / High)',
                  'Exportable PDF decision memo',
                  'Mandatory counter-case included',
                ].map(item => (
                  <li
                    key={item}
                    className="flex items-start gap-2 text-[12px] py-2 border-b"
                    style={{ color: '#7A7470', borderColor: '#1C1C22' }}
                  >
                    <span className="font-mono shrink-0" style={{ color: '#C47F0A' }}>—</span>
                    {item}
                  </li>
                ))}
              </ul>
              <button
                onClick={() => scrollTo('cta')}
                className="w-full py-3 rounded border text-[13px] bg-transparent
                  transition-colors hover:border-[#C47F0A]"
                style={{ borderColor: '#28282E', color: '#EDE8DF' }}
              >
                Run one simulation
              </button>
              <p className="font-mono text-[10px] mt-2" style={{ color: '#3A3530' }}>
                No account required. Pay and download.
              </p>
            </div>

            {/* Pro */}
            <div
              className="rounded-lg p-9"
              style={{ border: '1px solid #C47F0A', background: 'rgba(196,127,10,0.04)' }}
            >
              <div
                className="font-mono text-[11px] tracking-[0.1em] uppercase mb-3"
                style={{ color: '#7A7470' }}
              >
                PRO — ONGOING USE
              </div>
              <div
                className="text-[44px] font-normal leading-[1]"
                style={{ ...SERIF, color: '#EDE8DF' }}
              >
                $199
                <span className="font-sans text-[14px]" style={{ color: '#7A7470' }}>
                  {' '}/month
                </span>
              </div>
              <p
                className="text-[13px] mt-2 mb-6 pb-6 border-b"
                style={{ color: '#7A7470', borderColor: 'rgba(196,127,10,0.2)' }}
              >
                For PMs and consultants running simulations regularly. Calibration
                improves as you record real outcomes.
              </p>
              <ul className="list-none mb-7">
                {[
                  'Unlimited simulations',
                  'Calibration loop — record outcomes, improve accuracy over time',
                  'Product library — save and re-simulate the same product over time',
                  'White-label PDF memo for client delivery',
                  'Priority pipeline — 5-min target vs 10-min standard',
                ].map(item => (
                  <li
                    key={item}
                    className="flex items-start gap-2 text-[12px] py-2 border-b"
                    style={{ color: '#7A7470', borderColor: 'rgba(196,127,10,0.15)' }}
                  >
                    <span className="font-mono shrink-0" style={{ color: '#C47F0A' }}>—</span>
                    {item}
                  </li>
                ))}
              </ul>
              <button
                onClick={() => scrollTo('cta')}
                className="w-full py-3 rounded bg-[#C47F0A] hover:bg-[#E09410]
                  text-white text-[13px] font-medium transition-colors"
              >
                Start free trial
              </button>
              <p className="font-mono text-[10px] mt-2" style={{ color: '#3A3530' }}>
                14-day trial. Cancel anytime. First simulation is free.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── Final CTA ───────────────────────────────────────────────────────── */}
      <section
        id="cta"
        className="py-28 text-center border-t"
        style={{ borderColor: '#1C1C22', background: '#0D0D0D' }}
      >
        <h2
          className="text-[46px] font-normal leading-[1.08]"
          style={{ ...SERIF, color: '#EDE8DF' }}
        >
          Your next pricing call
          <br />
          is in two weeks.
        </h2>
        <p
          className="text-[15px] max-w-[460px] mx-auto mt-4 mb-9 leading-[1.65]"
          style={{ color: '#7A7470' }}
        >
          By then you can either have a simulation report showing the probable
          reaction per segment, or you can find out the hard way.
        </p>

        <UrlInput
          value={ctaUrl}
          onChange={setCtaUrl}
          onSubmit={() => handleSubmit(ctaUrl, setCtaSubmitting, setCtaError)}
          submitting={ctaSubmitting}
          error={ctaError}
          className="max-w-[480px] mx-auto"
        />

        <p
          className="font-mono text-[11px] mt-5 max-w-[380px] mx-auto leading-[1.6]"
          style={{ color: '#3A3530' }}
        >
          API cost per simulation: $0.31. You&apos;re selling this at $49.
          The margin is not the pitch — the outcome is.
        </p>
      </section>

      {/* ── Footer ──────────────────────────────────────────────────────────── */}
      <footer
        className="border-t py-6 px-6 md:px-20 flex justify-between items-center"
        style={{ borderColor: '#1C1C22' }}
      >
        <span className="font-mono text-[12px]" style={{ color: '#3A3530' }}>
          DECISION SIM
        </span>
        <span className="font-mono text-[11px]" style={{ color: '#3A3530' }}>
          Early access · Built in public
        </span>
      </footer>

    </div>
  )
}
