'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { api } from '@/lib/api'

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
      const data = await api.createSnapshot(url)
      router.push(`/loading-sim/${data.job_id}`)
    } catch {
      setError('Something went wrong. Please try again.')
      setSubmitting(false)
    }
  }

  function scrollTo(id: string) {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
  }

  return (
    <div className="min-h-screen bg-[#F3F0EA] text-[#181816]">

      {/* NAV — only render if layout.tsx does NOT already provide a global nav */}
      <nav className="sticky top-0 z-50 flex items-center justify-between
        px-16 h-[60px] border-b border-[#D8D4CC] bg-[#F3F0EA]">
        <span className="font-mono text-[13px] tracking-[0.1em] text-[#181816]">
          DECISION<span className="text-[#B87010]">SIM</span>
        </span>
        <div className="hidden md:flex gap-9">
          {['How it works', 'Use cases', 'Pricing'].map((label, i) => (
            <button
              key={label}
              onClick={() => scrollTo(['how', 'cases', 'pricing'][i])}
              className="text-[13px] text-[#58584E] hover:text-[#181816] transition-colors bg-transparent border-none cursor-pointer"
            >
              {label}
            </button>
          ))}
        </div>
        <button
          onClick={() => scrollTo('cta')}
          className="px-5 py-2 border border-[#181816] rounded-[3px]
            text-[13px] font-medium text-[#181816] bg-transparent
            hover:bg-[#181816] hover:text-[#F3F0EA] transition-all"
        >
          Run a simulation →
        </button>
      </nav>

      {/* HERO — centered, max-w-[900px] */}
      <div className="max-w-[900px] mx-auto px-12 pt-16 pb-20 text-center">

        {/* Eyebrow with amber lines */}
        <div className="flex items-center justify-center gap-4 mb-10">
          <div className="w-8 h-px bg-[#B87010]" />
          <span className="font-mono text-[11px] tracking-[0.18em] uppercase text-[#B87010]">
            For founders · Growth PMs · Product consultants
          </span>
          <div className="w-8 h-px bg-[#B87010]" />
        </div>

        {/* Headline — Source Serif 4, 68px */}
        <h1 className="font-serif text-[68px] leading-[1.02] font-normal
          tracking-[-0.02em] text-[#181816] mb-7">
          Know which customers leave<br />
          before you change{' '}
          <em className="italic text-[#B87010]">anything.</em>
        </h1>

        {/* Subheadline */}
        <p className="text-[18px] text-[#58584E] leading-[1.7]
          max-w-[560px] mx-auto mb-11">
          Paste your product URL. Describe your decision —
          a pricing change, a feature cut, a rebrand. Get a{' '}
          <strong className="text-[#181816] font-medium">
            segment-by-segment reaction report
          </strong>{' '}
          before you ship a single line.
        </p>

        {/* URL input — NOT a form tag */}
        <div className="flex max-w-[520px] mx-auto mb-5
          border border-[#C4C0B6] rounded-[4px] overflow-hidden
          bg-white shadow-[0_2px_8px_rgba(0,0,0,0.06)]
          focus-within:border-[#B87010]
          focus-within:shadow-[0_0_0_3px_rgba(184,112,16,0.12),0_2px_8px_rgba(0,0,0,0.06)]
          transition-all">
          <input
            type="url"
            value={heroUrl}
            onChange={e => { setHeroUrl(e.target.value); setHeroError(null) }}
            onKeyDown={e => e.key === 'Enter' && handleSubmit(heroUrl, setHeroSubmitting, setHeroError)}
            placeholder="https://yourproduct.com"
            className="flex-1 border-none outline-none px-[18px] py-[14px]
              font-mono text-[12px] text-[#181816] bg-transparent
              placeholder:text-[#A0A096]"
          />
          <button
            onClick={() => handleSubmit(heroUrl, setHeroSubmitting, setHeroError)}
            disabled={heroSubmitting}
            className="px-6 py-[14px] bg-[#181816] text-[#F3F0EA]
              text-[13px] font-medium whitespace-nowrap border-l border-[#D8D4CC]
              hover:bg-[#2A2A26] transition-colors disabled:opacity-60"
          >
            {heroSubmitting ? 'Starting...' : 'Simulate →'}
          </button>
        </div>

        {/* Error */}
        {heroError && (
          <p className="font-mono text-[11px] text-[#CC4820] mb-3">{heroError}</p>
        )}

        {/* Meta row */}
        <div className="flex justify-center gap-7">
          {['Free first simulation', '~5 minutes end-to-end', 'No account required'].map(t => (
            <span key={t} className="font-mono text-[11px] text-[#A0A096]
              flex items-center gap-1.5">
              <span className="text-[#B87010]">✓</span> {t}
            </span>
          ))}
        </div>
      </div>

      {/* SIMULATION EXHIBIT */}
      <div className="px-16 pb-20">

        {/* Exhibit label with trailing rule */}
        <div className="flex items-center gap-3 max-w-[1100px] mx-auto mb-5">
          <span className="font-mono text-[10px] tracking-[0.16em] uppercase
            text-[#A0A096] whitespace-nowrap">
            Figure 1 — Example simulation output
          </span>
          <div className="flex-1 h-px bg-[#D8D4CC]" />
        </div>

        {/* The exhibit card */}
        <div className="max-w-[1100px] mx-auto bg-white border border-[#D8D4CC]
          rounded-[6px] overflow-hidden shadow-[0_4px_24px_rgba(0,0,0,0.06)]">

          {/* Exhibit header */}
          <div className="flex items-start justify-between px-7 py-5
            border-b border-[#D8D4CC] bg-[#F3F0EA]">
            <div className="font-mono text-[12px] text-[#58584E] leading-[1.5]">
              <span className="text-[#181816] font-medium">linear.app</span>
              {' '}— Scenario: Raise seat price 30%<br />
              Simulation generated against 4 customer segments · 2 decision options
            </div>
            <div className="flex items-center gap-2 font-mono text-[10px]
              text-[#1A9452] px-3 py-1.5 border border-[rgba(26,148,82,0.28)]
              bg-[rgba(26,148,82,0.08)] rounded-[3px] shrink-0 ml-4">
              <span className="w-1.5 h-1.5 bg-[#1A9452] rounded-full animate-pulse" />
              Simulation complete
            </div>
          </div>

          {/* Table — standard HTML table in React */}
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr className="bg-[#FAFAF8]">
                  <th className="w-[200px] text-left px-5 py-[10px]
                    font-mono text-[10px] font-medium tracking-[0.1em] uppercase
                    text-[#A0A096] border-b border-r border-[#D8D4CC]">
                    Segment
                  </th>
                  <th className="text-left px-5 py-[10px]
                    font-mono text-[10px] font-medium tracking-[0.1em] uppercase
                    text-[#A0A096] border-b border-r border-[#D8D4CC]">
                    Option A &nbsp;·&nbsp; Raise prices 30%
                  </th>
                  <th className="text-left px-5 py-[10px]
                    font-mono text-[10px] font-medium tracking-[0.1em] uppercase
                    text-[#A0A096] border-b border-[#D8D4CC]">
                    Option B &nbsp;·&nbsp; Add free tier
                  </th>
                </tr>
              </thead>
              <tbody>

                {/* Row 1 */}
                <tr>
                  <td className="px-5 py-4 border-b border-r border-[#D8D4CC] align-top">
                    <div className="text-[13px] font-medium text-[#181816] mb-1">
                      Power dev teams
                    </div>
                    <div className="font-mono text-[10px] text-[#A0A096] tracking-[0.04em]">
                      JTBD: ship faster, fewer interruptions
                    </div>
                  </td>
                  <td className="px-4 py-3 border-b border-r border-[#D8D4CC] align-top">
                    {/* HIGH cell */}
                    <div className="rounded-[4px] p-[10px] border
                      border-[rgba(26,148,82,0.28)] bg-[rgba(26,148,82,0.08)]">
                      <div className="font-mono text-[9px] tracking-[0.08em]
                        text-[#1A9452] mb-1">HIGH CONFIDENCE</div>
                      <div className="font-mono text-[15px] font-semibold text-[#1A9452]">
                        12–18% churn
                      </div>
                      <div className="text-[11px] text-[#A0A096] mt-1.5 leading-[1.4]">
                        Price-insensitive if speed gains hold
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3 border-b border-[#D8D4CC] align-top">
                    {/* MEDIUM cell */}
                    <div className="rounded-[4px] p-[10px]"
                      style={{ border: '1px dashed rgba(184,112,16,0.4)', background: 'rgba(184,112,16,0.05)' }}>
                      <div className="font-mono text-[9px] tracking-[0.08em]
                        text-[#B87010] italic mb-1">MED CONFIDENCE</div>
                      <div className="font-mono text-[15px] font-semibold text-[#C47A10]">
                        28–44% downgrade
                      </div>
                      <div className="text-[11px] text-[#A0A096] mt-1.5 leading-[1.4]">
                        Risk of trial-down reducing LTV
                      </div>
                    </div>
                  </td>
                </tr>

                {/* Row 2 */}
                <tr>
                  <td className="px-5 py-4 border-b border-r border-[#D8D4CC] align-top">
                    <div className="text-[13px] font-medium text-[#181816] mb-1">
                      Solo devs &amp; indie hackers
                    </div>
                    <div className="font-mono text-[10px] text-[#A0A096] tracking-[0.04em]">
                      JTBD: stay organised without overhead
                    </div>
                  </td>
                  <td className="px-4 py-3 border-b border-r border-[#D8D4CC] align-top">
                    {/* LOW cell — needs diagonal stripes via inline style on inner div */}
                    <div className="rounded-[4px] p-[10px] relative overflow-hidden"
                      style={{
                        border: '1px solid rgba(204,72,32,0.22)',
                        background: 'rgba(204,72,32,0.05)',
                        opacity: 0.78,
                      }}>
                      {/* diagonal stripes overlay */}
                      <div className="absolute inset-0 pointer-events-none" style={{
                        background: 'repeating-linear-gradient(-45deg, transparent, transparent 5px, rgba(204,72,32,0.08) 5px, rgba(204,72,32,0.08) 10px)',
                      }} />
                      <div className="font-mono text-[9px] tracking-[0.08em]
                        text-[#CC4820] italic mb-1 relative z-10">LOW CONFIDENCE</div>
                      <div className="font-mono text-[15px] font-semibold
                        text-[#CC4820] relative z-10">62–78% churn</div>
                      <div className="text-[11px] text-[#A0A096] mt-1.5 leading-[1.4] relative z-10">
                        Actively evaluating Plane, Jira free
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3 border-b border-[#D8D4CC] align-top">
                    {/* HIGH cell */}
                    <div className="rounded-[4px] p-[10px] border
                      border-[rgba(26,148,82,0.28)] bg-[rgba(26,148,82,0.08)]">
                      <div className="font-mono text-[9px] tracking-[0.08em]
                        text-[#1A9452] mb-1">HIGH CONFIDENCE</div>
                      <div className="font-mono text-[15px] font-semibold text-[#1A9452]">
                        7–12% churn
                      </div>
                      <div className="text-[11px] text-[#A0A096] mt-1.5 leading-[1.4]">
                        Free tier directly resolves JTBD
                      </div>
                    </div>
                  </td>
                </tr>

                {/* Row 3 */}
                <tr>
                  <td className="px-5 py-4 border-r border-[#D8D4CC] align-top">
                    <div className="text-[13px] font-medium text-[#181816] mb-1">
                      Growth-stage PM teams
                    </div>
                    <div className="font-mono text-[10px] text-[#A0A096] tracking-[0.04em]">
                      JTBD: cross-functional alignment at speed
                    </div>
                  </td>
                  <td className="px-4 py-3 border-r border-[#D8D4CC] align-top">
                    {/* MEDIUM cell */}
                    <div className="rounded-[4px] p-[10px]"
                      style={{ border: '1px dashed rgba(184,112,16,0.4)', background: 'rgba(184,112,16,0.05)' }}>
                      <div className="font-mono text-[9px] tracking-[0.08em]
                        text-[#B87010] italic mb-1">MED CONFIDENCE</div>
                      <div className="font-mono text-[15px] font-semibold text-[#C47A10]">
                        31–47% churn
                      </div>
                      <div className="text-[11px] text-[#A0A096] mt-1.5 leading-[1.4]">
                        Budget approval friction at $12+ seat
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3 align-top">
                    {/* MEDIUM cell */}
                    <div className="rounded-[4px] p-[10px]"
                      style={{ border: '1px dashed rgba(184,112,16,0.4)', background: 'rgba(184,112,16,0.05)' }}>
                      <div className="font-mono text-[9px] tracking-[0.08em]
                        text-[#B87010] italic mb-1">MED CONFIDENCE</div>
                      <div className="font-mono text-[15px] font-semibold text-[#C47A10]">
                        15–22% churn
                      </div>
                      <div className="text-[11px] text-[#A0A096] mt-1.5 leading-[1.4]">
                        Free may reduce perceived seriousness
                      </div>
                    </div>
                  </td>
                </tr>

              </tbody>
            </table>
          </div>

          {/* Legend */}
          <div className="flex items-center gap-5 px-7 py-3.5
            border-t border-[#D8D4CC] bg-[#F3F0EA]">
            {[
              { label: 'High confidence', boxClass: 'border border-[rgba(26,148,82,0.28)] bg-[rgba(26,148,82,0.08)]' },
              { label: 'Medium confidence', style: { border: '1px dashed rgba(184,112,16,0.4)', background: 'rgba(184,112,16,0.05)' } },
              { label: 'Low confidence (diagonal = epistemic caution)', boxClass: 'border border-[rgba(204,72,32,0.22)] bg-[rgba(204,72,32,0.05)] opacity-[0.78]' },
            ].map(({ label, boxClass, style }) => (
              <div key={label} className="flex items-center gap-2">
                <div
                  className={`w-[10px] h-[10px] rounded-[2px] ${boxClass ?? ''}`}
                  style={style}
                />
                <span className="font-mono text-[10px] text-[#A0A096]">{label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* STATS BAND */}
      <div className="border-t border-b border-[#D8D4CC] bg-white py-14 px-16">
        <div className="max-w-[1100px] mx-auto grid grid-cols-3">
          {[
            { n: '$0.31', label: 'API cost per simulation', note: 'Honest. Not rounded up for elegance.' },
            { n: '~5 min', label: 'End-to-end latency', note: 'Scrape → segment → simulate → memo' },
            { n: '4–5', label: 'Segments per product', note: 'Evidence-anchored, not LLM-hallucinated' },
          ].map(({ n, label, note }, i) => (
            <div key={label}
              className={`${i < 2 ? 'pr-14 mr-14 border-r border-[#D8D4CC]' : ''}`}>
              <div className="font-serif text-[48px] leading-[1] text-[#B87010]">{n}</div>
              <div className="font-mono text-[11px] text-[#58584E] mt-2 tracking-[0.04em]">{label}</div>
              <div className="text-[13px] text-[#A0A096] mt-1">{note}</div>
            </div>
          ))}
        </div>
      </div>

      {/* HOW IT WORKS */}
      <section id="how" className="py-24 px-16 border-t border-[#D8D4CC] bg-white">
        <div className="max-w-[1100px] mx-auto">
          <div className="flex items-center gap-3 mb-5">
            <div className="w-6 h-px bg-[#B87010]" />
            <span className="font-mono text-[11px] tracking-[0.16em] uppercase text-[#B87010]">
              How it works
            </span>
          </div>
          <h2 className="font-serif text-[44px] font-normal leading-[1.1] text-[#181816]">
            Three steps between you<br />and a decision memo.
          </h2>
          <p className="text-[16px] text-[#58584E] leading-[1.7] max-w-[520px] mt-3">
            No setup. No integrations. Paste a URL, describe your decision, read the simulation.
          </p>

          <div className="grid grid-cols-3 mt-14">
            {[
              {
                n: '01',
                title: 'Paste your product URL',
                body: 'We scrape your product, pricing pages, and feature copy. Then we pull external signals — reviews, forum posts, analyst coverage — to understand how your actual customers talk about you.',
                tag: 'Sources: G2 · Reddit · Capterra · press · blogs\nFilters out: competitor mentions · Glassdoor · marketing copy',
              },
              {
                n: '02',
                title: 'Describe your decision',
                body: 'Write it in plain English. Raise seat price from $8 to $12. Remove the free tier. Rebrand from dev tool to ops platform. Compare 2–3 options side by side.',
                tag: 'Supports: pricing · feature gates · copy changes\nbundling · onboarding · deprecation',
              },
              {
                n: '03',
                title: 'Read the simulation',
                body: 'A confidence-banded dashboard showing how each segment reacts to each option — with churn ranges, top concerns, and a mandatory counter-case to the strongest recommendation.',
                tag: 'Output: confidence dashboard · decision memo · PDF\nIncludes: mandatory counter-case · calibration history',
              },
            ].map(({ n, title, body, tag }, i) => (
              <div key={n}
                className={i < 2 ? 'pr-14 mr-14 border-r border-[#D8D4CC]' : ''}>
                <div className="font-serif text-[80px] leading-[1] text-[#D8D4CC]
                  font-normal mb-6 pb-5 border-b border-[#D8D4CC]">
                  {n}
                </div>
                <h3 className="font-serif text-[22px] font-normal text-[#181816] mb-3 leading-[1.2]">
                  {title}
                </h3>
                <p className="text-[14px] text-[#58584E] leading-[1.7]">{body}</p>
                <div className="mt-5 font-mono text-[10px] text-[#A0A096]
                  leading-[1.7] tracking-[0.04em] whitespace-pre-line">
                  {tag}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* USE CASES */}
      <section id="cases" className="py-24 px-16 border-t border-[#D8D4CC]">
        <div className="max-w-[1100px] mx-auto">
          <div className="flex items-center gap-3 mb-5">
            <div className="w-6 h-px bg-[#B87010]" />
            <span className="font-mono text-[11px] tracking-[0.16em] uppercase text-[#B87010]">
              Use cases
            </span>
          </div>
          <h2 className="font-serif text-[44px] font-normal leading-[1.1] text-[#181816]">
            The decisions where being<br />wrong costs a quarter.
          </h2>
          <p className="text-[16px] text-[#58584E] leading-[1.7] max-w-[520px] mt-3">
            A simulation costs less than a rounding error on that loss.
          </p>

          <div className="grid grid-cols-3 gap-6 mt-14">
            {[
              {
                type: 'Pricing change',
                title: 'Raising prices on a product users have grown comfortable with',
                body: "You've been charging $19/mo for three years. You want $39. Some customers will follow. Some will leave. Which segments are which — and at what price point do they flip?",
                chip: 'Avg $340k ARR at risk on a $1M SaaS at 20% churn',
                chipColor: 'text-[#1A9452] border-[rgba(26,148,82,0.25)] bg-[rgba(26,148,82,0.08)]',
              },
              {
                type: 'Feature deprecation',
                title: "Removing something users love but you can't afford to maintain",
                body: "You want to kill the CSV export, the API v1 endpoint, or the legacy dashboard. Some users built their entire workflow around it. Which ones churn vs adapt?",
                chip: 'Simulate before the support tickets start',
                chipColor: 'text-[#B87010] border-[rgba(184,112,16,0.25)] bg-[#FDF0DC]',
              },
              {
                type: 'Repositioning',
                title: 'Shifting ICP from SMB to enterprise mid-growth',
                body: "Your website now says enterprise-grade. Your current users are founder-sized teams. You're about to send a mixed signal. Which segments read the new positioning as betrayal?",
                chip: "Identify the segments you'd be quietly firing",
                chipColor: 'text-[#1A9452] border-[rgba(26,148,82,0.25)] bg-[rgba(26,148,82,0.08)]',
              },
            ].map(({ type, title, body, chip, chipColor }) => (
              <div key={type}
                className="p-8 border border-[#D8D4CC] border-t-[3px] border-t-[#C4C0B6]
                  rounded-[4px] bg-[#F3F0EA]
                  hover:border-t-[#B87010] transition-colors group">
                <div className="font-mono text-[10px] tracking-[0.14em] uppercase
                  text-[#A0A096] mb-4">{type}</div>
                <h3 className="font-serif text-[20px] font-normal text-[#181816]
                  mb-3 leading-[1.25]">{title}</h3>
                <p className="text-[13px] text-[#58584E] leading-[1.65] mb-5">{body}</p>
                <span className={`inline-block font-mono text-[11px] px-3 py-1.5
                  rounded-[3px] border ${chipColor}`}>{chip}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* PRICING */}
      <section id="pricing" className="py-24 px-16 border-t border-[#D8D4CC] bg-white">
        <div className="max-w-[1100px] mx-auto">
          <div className="flex items-center gap-3 mb-5">
            <div className="w-6 h-px bg-[#B87010]" />
            <span className="font-mono text-[11px] tracking-[0.16em] uppercase text-[#B87010]">
              Pricing
            </span>
          </div>
          <h2 className="font-serif text-[44px] font-normal leading-[1.1] text-[#181816]">
            One simulation.<br />One decision de-risked.
          </h2>
          <p className="text-[16px] text-[#58584E] leading-[1.7] max-w-[520px] mt-3">
            A bad pricing move costs months of churn recovery.
            A simulation costs less than the Notion workspace you forgot to cancel.
          </p>

          <div className="grid grid-cols-2 gap-5 max-w-[820px] mt-14">

            {/* Card 1 — single sim */}
            <div className="p-11 bg-white border border-[#D8D4CC] rounded-[4px]">
              <div className="font-mono text-[11px] tracking-[0.12em] uppercase
                text-[#A0A096] mb-4">Single simulation</div>
              <div className="font-serif text-[52px] font-normal text-[#181816] leading-[1]">
                $49{' '}
                <span className="font-sans text-[15px] text-[#A0A096]">/ simulation</span>
              </div>
              <p className="text-[14px] text-[#58584E] mt-2.5 mb-7 pb-7
                border-b border-[#D8D4CC] leading-[1.55]">
                One product URL. One decision. Full report. No subscription needed.
              </p>
              <ul className="list-none mb-9">
                {[
                  'Up to 5 customer segments from evidence',
                  'Compare 3 decision options side by side',
                  'Confidence-banded dashboard',
                  'Exportable PDF decision memo',
                  'Mandatory counter-case included',
                ].map(f => (
                  <li key={f} className="flex gap-2.5 text-[13px] text-[#58584E]
                    py-2.5 border-b border-[#D8D4CC] items-start">
                    <span className="font-mono text-[#B87010] shrink-0">—</span>
                    {f}
                  </li>
                ))}
              </ul>
              <button
                onClick={() => scrollTo('cta')}
                className="w-full py-3.5 border border-[#C4C0B6] rounded-[3px]
                  bg-transparent text-[#181816] text-[13px] font-medium
                  hover:border-[#181816] transition-colors">
                Run one simulation
              </button>
              <p className="font-mono text-[10px] text-[#A0A096] mt-3 text-center">
                No account required · Pay and download
              </p>
            </div>

            {/* Card 2 — pro, bordered in dark */}
            <div className="p-11 bg-white border border-[#181816] rounded-[4px]">
              <div className="font-mono text-[11px] tracking-[0.12em] uppercase
                text-[#A0A096] mb-4">Pro — ongoing use</div>
              <div className="font-serif text-[52px] font-normal text-[#181816] leading-[1]">
                $199{' '}
                <span className="font-sans text-[15px] text-[#A0A096]">/ month</span>
              </div>
              <p className="text-[14px] text-[#58584E] mt-2.5 mb-7 pb-7
                border-b border-[#D8D4CC] leading-[1.55]">
                For PMs and consultants running simulations regularly.
                Calibration improves as you record real outcomes.
              </p>
              <ul className="list-none mb-9">
                {[
                  'Unlimited simulations',
                  'Calibration loop — accuracy improves over time',
                  'Product library — re-simulate the same product',
                  'White-label PDF memo for client delivery',
                  'Priority pipeline — 5-min target',
                ].map(f => (
                  <li key={f} className="flex gap-2.5 text-[13px] text-[#58584E]
                    py-2.5 border-b border-[#D8D4CC] items-start">
                    <span className="font-mono text-[#B87010] shrink-0">—</span>
                    {f}
                  </li>
                ))}
              </ul>
              <button
                onClick={() => scrollTo('cta')}
                className="w-full py-3.5 rounded-[3px] bg-[#181816] text-[#F3F0EA]
                  text-[13px] font-medium hover:bg-[#2A2A26] transition-colors">
                Start free trial
              </button>
              <p className="font-mono text-[10px] text-[#A0A096] mt-3 text-center">
                14-day trial · Cancel anytime
              </p>
            </div>

          </div>
        </div>
      </section>

      {/* CTA — dark bookend */}
      <section id="cta"
        className="py-32 px-16 text-center bg-[#181816] border-t border-[#D8D4CC]">
        <div className="flex items-center justify-center gap-4 mb-8">
          <div className="w-8 h-px bg-[#B87010]" />
          <span className="font-mono text-[11px] tracking-[0.18em] uppercase text-[#B87010]">
            Get started
          </span>
          <div className="w-8 h-px bg-[#B87010]" />
        </div>

        <h2 className="font-serif text-[56px] font-normal text-[#F3F0EA] leading-[1.06] mb-5">
          Your next pricing call<br />is in two weeks.
        </h2>
        <p className="text-[16px] text-[#6A6860] max-w-[440px] mx-auto mb-12 leading-[1.7]">
          By then you can either have a simulation report showing the probable
          reaction per segment — or you can find out the hard way.
        </p>

        <div className="flex max-w-[520px] mx-auto
          border border-[#3A3A36] rounded-[4px] overflow-hidden bg-[#1E1E1C]
          focus-within:border-[#B87010] transition-colors">
          <input
            type="url"
            value={ctaUrl}
            onChange={e => { setCtaUrl(e.target.value); setCtaError(null) }}
            onKeyDown={e => e.key === 'Enter' && handleSubmit(ctaUrl, setCtaSubmitting, setCtaError)}
            placeholder="https://yourproduct.com"
            className="flex-1 border-none outline-none px-[18px] py-[14px]
              font-mono text-[12px] text-[#F3F0EA] bg-transparent
              placeholder:text-[#3A3A36]"
          />
          <button
            onClick={() => handleSubmit(ctaUrl, setCtaSubmitting, setCtaError)}
            disabled={ctaSubmitting}
            className="px-6 py-[14px] bg-[#B87010] text-white
              text-[13px] font-medium whitespace-nowrap border-l border-[#3A3A36]
              hover:bg-[#D4820E] transition-colors disabled:opacity-60">
            {ctaSubmitting ? 'Starting...' : 'Run simulation →'}
          </button>
        </div>

        {ctaError && (
          <p className="font-mono text-[11px] text-[#CC4820] mt-3">{ctaError}</p>
        )}

        <p className="font-mono text-[11px] text-[#3A3A36] mt-5">
          <span className="text-[#5A5A54]">API cost per simulation: $0.31.</span>
          {' '}You&apos;re selling this at $49. The margin is not the pitch.
        </p>
      </section>

      {/* FOOTER */}
      <footer className="bg-[#181816] border-t border-[#2A2A26]
        px-16 py-6 flex items-center justify-between">
        <span className="font-mono text-[12px] text-[#3A3A36]">DECISIONSIM</span>
        <span className="font-mono text-[11px] text-[#3A3A36]">
          Early access · Built in public
        </span>
      </footer>

    </div>
  )
}
