import React, { FormEvent, useEffect, useState, type ReactNode } from 'react'

import { AuthenticatedImage } from './AuthenticatedImage'
import {
  badCaseStatusTone,
  formatBadCaseRoute,
  formatBadCaseStatus,
  isBadCaseExportable,
} from '../lib/badcases'
import { toClassNames } from '../lib/format'
import type { BadCase, BadCaseStatus } from '../lib/types'

interface BadCaseDrawerProps {
  caseItem: BadCase | null
  saving: boolean
  previewing: boolean
  previewStoragePath: string | null
  previewMethod: string | null
  previewFailed: boolean
  onClose: () => void
  onSave: (payload: { ground_truth_text: string | null; status: BadCaseStatus; redact_pii: boolean; reporter_note: string | null }) => void
  onPreview: () => void
}

const editableStatuses: BadCaseStatus[] = ['pending', 'triaged', 'ready', 'exported', 'discarded']

export function BadCaseDrawer({
  caseItem,
  saving,
  previewing,
  previewStoragePath,
  previewMethod,
  previewFailed,
  onClose,
  onSave,
  onPreview,
}: BadCaseDrawerProps) {
  const [groundTruth, setGroundTruth] = useState('')
  const [status, setStatus] = useState<BadCaseStatus>('pending')
  const [redactPii, setRedactPii] = useState(true)
  const [reporterNote, setReporterNote] = useState('')

  useEffect(() => {
    if (!caseItem) {
      return
    }
    setGroundTruth(caseItem.ground_truth_text ?? '')
    setStatus(caseItem.status)
    setRedactPii(caseItem.redact_pii)
    setReporterNote(caseItem.reporter_note ?? '')
  }, [caseItem])

  if (!caseItem) {
    return null
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onSave({
      ground_truth_text: groundTruth.trim() || null,
      status,
      redact_pii: redactPii,
      reporter_note: reporterNote.trim() || null,
    })
  }

  const exportable = isBadCaseExportable({ status, ground_truth_text: groundTruth })

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-ink-950/50 backdrop-blur-sm" onClick={onClose} />
      <aside className="relative flex h-full w-full max-w-5xl flex-col overflow-hidden bg-parchment shadow-lift">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-ink-900/10 bg-white/85 px-5 py-4">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-ink-950 px-3 py-1 text-xs font-semibold text-paper">
                #{caseItem.id}
              </span>
              <span className="rounded-full border border-ink-900/10 bg-white px-3 py-1 text-xs font-semibold text-ink-700">
                {formatBadCaseRoute(caseItem.route_key)}
              </span>
              <span className={`rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset ${badCaseStatusTone(status)}`}>
                {formatBadCaseStatus(status)}
              </span>
            </div>
            <h2 className="mt-3 font-display text-3xl text-ink-950">OCR Bad Case 详情</h2>
            <p className="mt-1 break-all text-xs text-ink-700">{caseItem.image_storage_path}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full border border-ink-900/10 bg-white px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-paper"
          >
            关闭
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.05fr)_minmax(420px,0.95fr)]">
            <div className="space-y-5">
              <Panel title="原始图片">
                <AuthenticatedImage
                  storagePath={caseItem.image_storage_path}
                  alt={`Bad case ${caseItem.id}`}
                  className="max-h-[58vh] w-full rounded-2xl object-contain"
                  wrapperStyle={{ minHeight: '18rem' }}
                />
              </Panel>

              <Panel
                title="脱敏预览"
                action={
                  <button
                    type="button"
                    onClick={onPreview}
                    disabled={previewing}
                    className="rounded-full border border-slateBlue-200 bg-slateBlue-50 px-3 py-1.5 text-xs font-semibold text-slateBlue-500 transition hover:bg-slateBlue-100 disabled:opacity-50"
                  >
                    {previewing ? '生成中...' : '生成预览'}
                  </button>
                }
              >
                {previewStoragePath ? (
                  <div className="space-y-3">
                    <AuthenticatedImage
                      storagePath={previewStoragePath}
                      alt="脱敏预览"
                      className="max-h-[42vh] w-full rounded-2xl object-contain"
                      wrapperStyle={{ minHeight: '14rem' }}
                    />
                    <p className={toClassNames('text-xs font-semibold', previewFailed ? 'text-red-700' : 'text-ink-700')}>
                      方法：{previewMethod || 'unknown'}{previewFailed ? '，脱敏失败，已使用占位图' : ''}
                    </p>
                  </div>
                ) : (
                  <div className="rounded-2xl border border-dashed border-ink-900/15 bg-white/70 px-4 py-12 text-center text-sm text-ink-700">
                    点击“生成预览”查看导出时使用的脱敏图片。
                  </div>
                )}
              </Panel>
            </div>

            <form onSubmit={handleSubmit} className="space-y-5">
              <Panel title="标注与状态">
                <div className="space-y-4">
                  <label className="block">
                    <span className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-700">状态</span>
                    <select
                      value={status}
                      onChange={(event) => setStatus(event.target.value as BadCaseStatus)}
                      className="mt-2 w-full rounded-2xl border border-ink-900/10 bg-white px-4 py-3 text-sm text-ink-950 shadow-sm focus:border-slateBlue-300 focus:outline-none focus:ring-2 focus:ring-slateBlue-100"
                    >
                      {editableStatuses.map((item) => (
                        <option key={item} value={item}>
                          {formatBadCaseStatus(item)}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="block">
                    <span className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-700">Ground truth</span>
                    <textarea
                      value={groundTruth}
                      onChange={(event) => setGroundTruth(event.target.value)}
                      rows={8}
                      className="mt-2 w-full rounded-2xl border border-ink-900/10 bg-white px-4 py-3 font-mono text-sm leading-6 text-ink-950 shadow-sm focus:border-slateBlue-300 focus:outline-none focus:ring-2 focus:ring-slateBlue-100"
                      placeholder="输入修正后的 OCR 文本"
                    />
                  </label>

                  <label className="block">
                    <span className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-700">备注</span>
                    <textarea
                      value={reporterNote}
                      onChange={(event) => setReporterNote(event.target.value)}
                      rows={3}
                      className="mt-2 w-full rounded-2xl border border-ink-900/10 bg-white px-4 py-3 text-sm leading-6 text-ink-950 shadow-sm focus:border-slateBlue-300 focus:outline-none focus:ring-2 focus:ring-slateBlue-100"
                      placeholder="记录人工判断、样本问题或处理说明"
                    />
                  </label>

                  <label className="flex items-center gap-3 rounded-2xl border border-ink-900/10 bg-white/80 px-4 py-3 text-sm font-semibold text-ink-950">
                    <input
                      type="checkbox"
                      checked={redactPii}
                      onChange={(event) => setRedactPii(event.target.checked)}
                      className="h-4 w-4 rounded border-ink-900/20 text-slateBlue-500 focus:ring-slateBlue-300"
                    />
                    导出前脱敏学生信息
                  </label>

                  <div className="rounded-2xl border border-ink-900/10 bg-paper px-4 py-3 text-sm text-ink-700">
                    {exportable ? '该样本已满足导出条件。' : '导出需要状态为“可导出”且填写 ground truth。'}
                  </div>

                  <button
                    type="submit"
                    disabled={saving}
                    className="w-full rounded-full bg-ink-950 px-4 py-3 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:opacity-50"
                  >
                    {saving ? '正在保存...' : '保存标注'}
                  </button>
                </div>
              </Panel>

              <Panel title="OCR 原文">
                <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-2xl border border-ink-900/10 bg-white px-4 py-3 font-mono text-xs leading-5 text-ink-950">
                  {caseItem.ocr_raw_text || '无 OCR 原文'}
                </pre>
                {caseItem.ocr_error_message ? (
                  <p className="mt-3 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                    {caseItem.ocr_error_message}
                  </p>
                ) : null}
              </Panel>

              <Panel title="触发信息">
                <dl className="grid gap-3 text-sm text-ink-700 sm:grid-cols-2">
                  <Meta label="原因" value={caseItem.trigger_reason} />
                  <Meta label="来源" value={caseItem.trigger_source === 'manual' ? '人工报告' : '自动捕获'} />
                  <Meta label="模型" value={caseItem.ocr_model} />
                  <Meta label="最后出现" value={new Date(caseItem.last_seen_at).toLocaleString()} />
                  <Meta label="考试 ID" value={caseItem.exam_id ?? '—'} />
                  <Meta label="答卷 ID" value={caseItem.submission_id ?? '—'} />
                  <Meta label="批次 ID" value={caseItem.batch_id ?? '—'} />
                  <Meta label="批次页 ID" value={caseItem.batch_page_id ?? '—'} />
                </dl>
              </Panel>
            </form>
          </div>
        </div>
      </aside>
    </div>
  )
}

function Panel({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-3xl border border-ink-900/10 bg-white/85 p-4 shadow-soft">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="font-display text-2xl text-ink-950">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  )
}

function Meta({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-2xl border border-ink-900/10 bg-paper px-3 py-2">
      <dt className="text-[11px] font-semibold uppercase tracking-[0.16em] text-ink-700">{label}</dt>
      <dd className="mt-1 break-all font-semibold text-ink-950">{value}</dd>
    </div>
  )
}
