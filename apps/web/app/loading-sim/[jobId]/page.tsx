'use client'

import { use, useEffect } from 'react'
import { useRouter } from 'next/navigation'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export default function LoadingSimPage({
  params,
}: {
  params: Promise<{ jobId: string }>
}) {
  const { jobId } = use(params)
  const router = useRouter()

  useEffect(() => {
    let cancelled = false
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/snapshots/jobs/${jobId}`)
        if (!res.ok) return
        const data = await res.json()
        if (cancelled) return
        if (data.status === 'finished' && data.snapshot_id) {
          clearInterval(interval)
          router.push(`/compose?snapshotId=${data.snapshot_id}`)
        } else if (data.status === 'failed') {
          clearInterval(interval)
          router.push('/compose')
        }
      } catch { /* ignore network errors, keep polling */ }
    }, 2000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [jobId, router])

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center gap-4"
      style={{ background: '#080808' }}
    >
      <div
        className="w-5 h-5 rounded-full animate-ping"
        style={{ background: '#C47F0A', opacity: 0.6 }}
      />
      <p className="font-mono text-[13px]" style={{ color: '#7A7470' }}>
        Researching your product...
      </p>
      <p className="font-mono text-[11px]" style={{ color: '#3A3530' }}>
        Scraping · Pulling signals · Building segments
      </p>
    </div>
  )
}
