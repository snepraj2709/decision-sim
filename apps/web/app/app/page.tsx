'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
const OPTION_TYPES = ['pricing', 'feature', 'copy', 'bundling', 'onboarding'] as const

// ─── Types ────────────────────────────────────────────────────────────────────
// Matches the existing localStorage structure — do not rename these fields.

interface RecentProduct {
  url: string
  snapshotId: string
  snapshotCreatedAt: string
  segmentCount: number
  confidenceSummary: { high: number; medium: number; low: number }
  simulationId: string | null
}

interface RateCell {
  rate: number
  sample_count: number
}

type RatesData = Record<string, Record<string, RateCell>>

// ─── Helpers ──────────────────────────────────────────────────────────────────

function relativeDate(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const days = Math.floor(diff / 86400000)
  if (days === 0) return 'Today'
  if (days === 1) return 'Yesterday'
  if (days < 7) return `${days} days ago`
  if (days < 30) return `${Math.floor(days / 7)} weeks ago`
  return `${Math.floor(days / 30)} months ago`
}

function urlHost(url: string): string {
  try {
    return new URL(url).hostname.replace('www.', '')
  } catch {
    return url
  }
}

// Average rate across all sentiment buckets for an option type.
function aggRate(typeRates: Record<string, RateCell>): { rate: number; sampleCount: number } {
  const cells = Object.values(typeRates)
  if (cells.length === 0) return { rate: 0, sampleCount: 0 }
  const rate = cells.reduce((s, c) => s + c.rate, 0) / cells.length
  const sampleCount = cells.reduce((s, c) => s + c.sample_count, 0)
  return { rate, sampleCount }
}

function rateColor(rate: number): string {
  if (rate > 0.7) return '#4CAF70'
  if (rate >= 0.4) return '#C47F0A'
  return '#E85D30'
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AppHomePage() {
  const router = useRouter()
  const [newSimUrl, setNewSimUrl] = useState('')
  const [recent, setRecent] = useState<RecentProduct[]>([])
  const [ratesData, setRatesData] = useState<RatesData | null>(null)
  const [ratesLoading, setRatesLoading] = useState(true)

  useEffect(() => {
    try {
      const raw = localStorage.getItem('dsim_recent_products') ?? '[]'
      setRecent(JSON.parse(raw) as RecentProduct[])
    } catch { /* ignore */ }

    fetch(`${API_BASE}/api/v1/calibration/rates`)
      .then(r => r.json())
      .then(d => { setRatesData(d.rates); setRatesLoading(false) })
      .catch(() => setRatesLoading(false))
  }, [])

  function handleNewSim() {
    const url = newSimUrl.trim()
    if (!url) {
      router.push('/compose')
      return
    }
    router.push(`/compose?url=${encodeURIComponent(url)}`)
  }

  return (
    <div className="min-h-screen" style={{ background: '#080808' }}>

      {/* ── Nav ───────────────────────────────────────────────────────────── */}
      <nav
        className="sticky top-0 z-50 border-b"
        style={{ borderColor: '#1C1C22', background: '#080808' }}
      >
        <div className="max-w-[1100px] mx-auto px-6 md:px-16 h-12 flex items-center justify-between">
          <Link
            href="/"
            className="font-mono text-[13px] tracking-wider"
            style={{ color: '#C47F0A' }}
          >
            DECISION SIM
          </Link>
          <div className="flex items-center gap-6">
            <Link
              href="/compose"
              className="text-[13px] transition-colors hover:text-[#EDE8DF]"
              style={{ color: '#7A7470' }}
            >
              New simulation
            </Link>
            <Link
              href="/calibration"
              className="text-[13px] transition-colors hover:text-[#EDE8DF]"
              style={{ color: '#7A7470' }}
            >
              Calibration
            </Link>
          </div>
        </div>
      </nav>

      <div className="max-w-[1100px] mx-auto">

        {/* ── Section 1: New simulation entry ──────────────────────────────── */}
        <section className="pt-16 pb-12 px-6 md:px-16">
          <div
            className="font-mono text-[11px] tracking-[0.14em] uppercase"
            style={{ color: '#C47F0A' }}
          >
            DECISION SIM — FLIGHT LOG
          </div>
          <h1
            className="font-serif-display text-[42px] leading-[1.06] font-normal mt-4"
            style={{ color: '#EDE8DF' }}
          >
            Your decision flight log.
          </h1>
          <p className="text-[15px] mt-2" style={{ color: '#7A7470' }}>
            Simulations run. Decisions pre-mortemed before shipping.
          </p>

          <div
            className="flex max-w-[500px] border border-[#28282E] rounded-md overflow-hidden
              focus-within:border-[#C47F0A] focus-within:ring-2 focus-within:ring-[#C47F0A]/20
              transition-all mt-8"
          >
            <input
              type="url"
              value={newSimUrl}
              onChange={e => setNewSimUrl(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleNewSim() }}
              placeholder="https://yourproduct.com"
              className="flex-1 border-none outline-none px-4 py-3 font-mono text-[12px]
                placeholder:text-[#3A3530]"
              style={{ background: '#111113', color: '#EDE8DF' }}
            />
            <button
              onClick={handleNewSim}
              className="bg-[#C47F0A] hover:bg-[#E09410] text-white px-5 py-3
                text-[13px] font-medium transition-colors whitespace-nowrap"
            >
              → New simulation
            </button>
          </div>
        </section>

        <div className="border-t mx-6 md:mx-16" style={{ borderColor: '#1C1C22' }} />

        {/* ── Section 2: Flight Log ─────────────────────────────────────────── */}
        <section className="py-12 px-6 md:px-16">
          <div className="flex items-center justify-between mb-6">
            <span
              className="font-mono text-[11px] tracking-[0.14em] uppercase"
              style={{ color: '#3A3530' }}
            >
              RECENT SIMULATIONS
            </span>
            <Link
              href="/compose"
              className="text-[13px] transition-colors hover:text-[#EDE8DF]"
              style={{ color: '#7A7470' }}
            >
              Start new →
            </Link>
          </div>

          {recent.length === 0 ? (
            <div
              className="py-20 text-center rounded-lg"
              style={{ border: '1px dashed #1C1C22' }}
            >
              <p className="font-mono text-[13px]" style={{ color: '#3A3530' }}>
                No simulations yet.
              </p>
              <p className="font-mono text-[13px] mt-1" style={{ color: '#3A3530' }}>
                Paste a product URL above to run your first.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3">
              {recent.map((item, i) => (
                <div
                  key={`${item.snapshotId}-${i}`}
                  className="rounded-lg transition-all cursor-pointer group
                    hover:bg-[#151517]"
                  style={{ border: '1px solid #1C1C22', background: '#111113' }}
                  onClick={() => {
                    if (item.simulationId) {
                      router.push(`/dashboard/${item.simulationId}`)
                    } else {
                      router.push(`/compose?snapshotId=${item.snapshotId}`)
                    }
                  }}
                >
                  <div className="p-4">
                    {/* Row 1 — identity + date + status */}
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div
                          className="font-sans font-medium text-[15px] group-hover:text-white transition-colors"
                          style={{ color: '#EDE8DF' }}
                        >
                          {urlHost(item.url)}
                        </div>
                        <div
                          className="font-mono text-[11px] mt-0.5 truncate"
                          style={{ color: '#3A3530' }}
                        >
                          {item.url}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <span className="font-mono text-[11px]" style={{ color: '#3A3530' }}>
                          {relativeDate(item.snapshotCreatedAt)}
                        </span>
                        {item.simulationId ? (
                          <span
                            className="font-mono text-[10px] tracking-wider px-2 py-0.5 rounded"
                            style={{
                              background: 'rgba(76,175,112,0.1)',
                              color: '#4CAF70',
                              border: '1px solid rgba(76,175,112,0.2)',
                            }}
                          >
                            done
                          </span>
                        ) : (
                          <span
                            className="font-mono text-[10px] tracking-wider px-2 py-0.5 rounded"
                            style={{
                              background: 'rgba(196,127,10,0.1)',
                              color: '#C47F0A',
                              border: '1px solid rgba(196,127,10,0.2)',
                            }}
                          >
                            ready
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Row 2 — data summary */}
                    <div className="mt-3 flex items-center gap-4">
                      <span className="font-mono text-[12px]" style={{ color: '#7A7470' }}>
                        {item.segmentCount} segments
                      </span>
                      <div className="flex items-center gap-1.5">
                        {item.confidenceSummary.high > 0 && (
                          <>
                            <span
                              className="w-1.5 h-1.5 rounded-full inline-block"
                              style={{ background: '#4CAF70' }}
                            />
                            <span className="font-mono text-[12px]" style={{ color: '#7A7470' }}>
                              {item.confidenceSummary.high} High
                            </span>
                          </>
                        )}
                        {item.confidenceSummary.medium > 0 && (
                          <>
                            <span
                              className="w-1.5 h-1.5 rounded-full inline-block ml-1"
                              style={{ background: '#C47F0A' }}
                            />
                            <span className="font-mono text-[12px]" style={{ color: '#7A7470' }}>
                              {item.confidenceSummary.medium} Med
                            </span>
                          </>
                        )}
                        {item.confidenceSummary.low > 0 && (
                          <>
                            <span
                              className="w-1.5 h-1.5 rounded-full inline-block ml-1 opacity-60"
                              style={{ background: '#E85D30' }}
                            />
                            <span className="font-mono text-[12px]" style={{ color: '#7A7470' }}>
                              {item.confidenceSummary.low} Low
                            </span>
                          </>
                        )}
                      </div>
                      {item.simulationId ? (
                        <button
                          type="button"
                          className="font-mono text-[12px] ml-auto transition-colors hover:text-[#E09410]"
                          style={{ color: '#C47F0A' }}
                          onClick={e => {
                            e.stopPropagation()
                            router.push(`/dashboard/${item.simulationId}`)
                          }}
                        >
                          → View
                        </button>
                      ) : (
                        <span
                          className="font-mono text-[12px] ml-auto"
                          style={{ color: '#7A7470' }}
                        >
                          Snapshot ready · Resume →
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* ── Section 3: Calibration strip ──────────────────────────────────── */}
        <section
          className="py-10 px-6 md:px-16 border-t"
          style={{ borderColor: '#1C1C22' }}
        >
          <div className="flex items-center justify-between">
            <span
              className="font-mono text-[11px] tracking-[0.14em] uppercase"
              style={{ color: '#3A3530' }}
            >
              MODEL ACCURACY
            </span>
            <Link
              href="/calibration"
              className="font-mono text-[11px] transition-colors hover:text-[#EDE8DF]"
              style={{ color: '#7A7470' }}
            >
              View full calibration →
            </Link>
          </div>

          {ratesLoading ? (
            <div className="flex flex-wrap gap-2 mt-4">
              {[0, 1, 2].map(n => (
                <div
                  key={n}
                  className="animate-pulse rounded w-20 h-14"
                  style={{ background: '#1C1C22' }}
                />
              ))}
            </div>
          ) : ratesData && Object.keys(ratesData).length > 0 ? (
            <div className="flex flex-wrap gap-2 mt-4">
              {OPTION_TYPES.filter(t => ratesData[t]).map(optType => {
                const { rate, sampleCount } = aggRate(ratesData[optType] ?? {})
                return (
                  <div
                    key={optType}
                    className="rounded px-3 py-2"
                    style={{ border: '1px solid #1C1C22', background: '#111113' }}
                  >
                    <div
                      className="font-mono text-[10px] uppercase tracking-wider"
                      style={{ color: '#3A3530' }}
                    >
                      {optType}
                    </div>
                    <div
                      className="font-mono text-[14px] font-medium"
                      style={{ color: rateColor(rate) }}
                    >
                      {(rate * 100).toFixed(0)}%
                    </div>
                    <div className="font-mono text-[9px]" style={{ color: '#3A3530' }}>
                      {sampleCount < 5 ? 'Prior' : `n=${sampleCount}`}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <p className="font-mono text-[12px] mt-4" style={{ color: '#3A3530' }}>
              No calibration data yet. Record outcomes after simulations to improve accuracy.
            </p>
          )}
        </section>

      </div>
    </div>
  )
}
