import React, { FormEvent, useState } from 'react'

import { createBadCase } from '../lib/api'
import { formatBadCaseRoute } from '../lib/badcases'
import { toClassNames } from '../lib/format'
import type { BadCaseRouteKey } from '../lib/types'

interface BadCaseReportButtonProps {
  imageStoragePath: string
  routeKey: BadCaseRouteKey
  examId?: number | null
  submissionId?: number | null
  batchId?: number | null
  batchPageId?: number | null
  compact?: boolean
}

export function BadCaseReportButton({
  imageStoragePath,
  routeKey,
  examId = null,
  submissionId = null,
  batchId = null,
  batchPageId = null,
  compact = false,
}: BadCaseReportButtonProps) {
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [reported, setReported] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await createBadCase({
        image_storage_path: imageStoragePath,
        route_key: routeKey,
        exam_id: examId,
        submission_id: submissionId,
        batch_id: batchId,
        batch_page_id: batchPageId,
        reporter_note: note.trim() || null,
      })
      setReported(true)
      setOpen(false)
      setNote('')
    } catch (error) {
      setError(error instanceof Error ? error.message : '上报 OCR Bad Case 失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={saving || reported}
        className={toClassNames(
          'inline-flex items-center rounded-full font-semibold transition disabled:opacity-60',
          compact ? 'px-3 py-1.5 text-xs' : 'px-4 py-2 text-sm',
          reported
            ? 'border border-sage-200 bg-sage-50 text-sage-500'
            : 'border border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100',
        )}
        title={`${formatBadCaseRoute(routeKey)} · ${imageStoragePath}`}
      >
        {reported ? '已上报' : '报告 OCR'}
      </button>

      {open ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
          <div className="absolute inset-0 bg-ink-950/50 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <form onSubmit={handleSubmit} className="relative w-full max-w-lg rounded-3xl border border-ink-900/10 bg-white p-6 shadow-lift">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="font-display text-2xl text-ink-950">报告 OCR Bad Case</h2>
                <p className="mt-2 text-sm text-ink-700">{formatBadCaseRoute(routeKey)}</p>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded-full border border-ink-900/10 bg-white px-3 py-1.5 text-xs font-semibold text-ink-950 transition hover:bg-paper"
              >
                关闭
              </button>
            </div>
            <p className="mt-4 break-all rounded-2xl border border-ink-900/10 bg-paper px-4 py-3 text-xs text-ink-700">
              {imageStoragePath}
            </p>
            <label className="mt-4 block">
              <span className="text-sm font-semibold text-ink-800">问题说明</span>
              <textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                rows={4}
                className="mt-2 w-full rounded-2xl border border-ink-900/10 bg-white px-4 py-3 text-sm leading-6 text-ink-950 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
                placeholder="例如：姓名识别错误、整页 OCR 为空、题号区域漏识别。"
              />
            </label>
            {error ? <p className="mt-3 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p> : null}
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded-full border border-ink-900/10 bg-white px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-paper"
              >
                取消
              </button>
              <button
                type="submit"
                disabled={saving}
                className="rounded-full bg-ink-950 px-4 py-2 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:opacity-50"
              >
                {saving ? '正在上报...' : '提交上报'}
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </>
  )
}
