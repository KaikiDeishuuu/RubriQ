import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import {
  deleteSubmission,
  downloadBlob,
  exportResultsCsv,
  exportResultsPdf,
  exportResultsXlsx,
  getResults,
} from '../lib/api'
import { formatScore, isSubmissionActive, toClassNames } from '../lib/format'
import type { ExamResultsResponse } from '../lib/types'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { SectionCard } from '../components/SectionCard'
import { StatusBadge } from '../components/StatusBadge'

type ExportFormat = 'csv' | 'xlsx' | 'pdf'

async function exportResults(format: ExportFormat, examId: number): Promise<Blob> {
  if (format === 'csv') {
    return exportResultsCsv(examId)
  }
  if (format === 'xlsx') {
    return exportResultsXlsx(examId)
  }
  return exportResultsPdf(examId)
}

export function BatchResultsPage() {
  const { examId } = useParams()
  const numericExamId = Number(examId)
  const [data, setData] = useState<ExamResultsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [exporting, setExporting] = useState<ExportFormat | null>(null)
  const loadingRef = useRef(false)
  const backgroundLoadingRef = useRef(false)

  useEffect(() => {
    void loadResults()
  }, [numericExamId])

  useEffect(() => {
    if (!data?.ai_review_active && !data?.rows.some((row) => isSubmissionActive(row.status))) {
      return
    }
    const timerId = window.setInterval(() => {
      void loadResults({ background: true })
    }, 3000)
    return () => window.clearInterval(timerId)
  }, [data])

  async function loadResults({ background = false }: { background?: boolean } = {}) {
    if (!Number.isFinite(numericExamId)) {
      setError('考试 ID 无效')
      if (!background) {
        setLoading(false)
      }
      return
    }
    const requestRef = background ? backgroundLoadingRef : loadingRef
    if (requestRef.current) {
      return
    }
    requestRef.current = true
    try {
      if (!background) {
        setLoading(true)
      }
      setError(null)
      setData(await getResults(numericExamId))
    } catch (error) {
      setError(error instanceof Error ? error.message : '加载结果失败')
    } finally {
      requestRef.current = false
      if (!background) {
        setLoading(false)
      }
    }
  }

  async function handleDelete() {
    if (deleteTarget === null) return
    setDeleting(true)
    try {
      await deleteSubmission(deleteTarget)
      setData((prev) =>
        prev
          ? { ...prev, rows: prev.rows.filter((row) => row.submission_id !== deleteTarget) }
          : prev,
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除答卷失败')
    } finally {
      setDeleting(false)
      setDeleteTarget(null)
    }
  }

  async function handleExport(format: ExportFormat) {
    if (!Number.isFinite(numericExamId)) {
      return
    }
    setExporting(format)
    try {
      const blob = await exportResults(format, numericExamId)
      await downloadBlob(blob, `exam-${numericExamId}-results.${format}`)
    } catch (error) {
      setError(error instanceof Error ? error.message : '导出结果失败')
    } finally {
      setExporting(null)
    }
  }

  const exam = data?.exam
  const gradedCount = data?.rows.filter((row) => row.status === 'graded').length ?? 0
  const reviewCount = data?.rows.filter((row) => row.status === 'needs_review').length ?? 0
  const failedCount = data?.rows.filter((row) => row.status === 'failed').length ?? 0
  const aiReviewedCount = data?.rows.reduce((total, row) => total + row.ai_reviewed_answer_count, 0) ?? 0
  const pendingAnswerReviewCount = data?.rows.reduce((total, row) => total + row.pending_review_answer_count, 0) ?? 0

  return (
    <div className="space-y-6">
      <SectionCard
        title={exam ? `${exam.title}批量结果` : '批量结果'}
        description="查看全班批改进度，复核需要人工确认的答卷，并导出成绩。"
        action={
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void handleExport('csv')}
              disabled={exporting !== null}
              className="rounded-full bg-ink-950 px-4 py-2 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:opacity-50"
            >
              {exporting === 'csv' ? '正在导出 CSV...' : '导出 CSV'}
            </button>
            <button
              type="button"
              onClick={() => void handleExport('xlsx')}
              disabled={exporting !== null}
              className="rounded-full border border-ink-900/10 bg-white px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-paper disabled:opacity-50"
            >
              {exporting === 'xlsx' ? '正在导出 Excel...' : '导出 Excel'}
            </button>
            <button
              type="button"
              onClick={() => void handleExport('pdf')}
              disabled={exporting !== null}
              className="rounded-full border border-slateBlue-200 bg-slateBlue-50 px-4 py-2 text-sm font-semibold text-slateBlue-500 transition hover:bg-slateBlue-100 disabled:opacity-50"
            >
              {exporting === 'pdf' ? '正在导出 PDF...' : '导出 PDF'}
            </button>
          </div>
        }
      >
        <div className="grid gap-4 md:grid-cols-6">
          <Metric label="答卷数" value={String(data?.rows.length ?? 0)} />
          <Metric label="已评分" value={String(gradedCount)} />
          <Metric label="待复核答卷" value={String(reviewCount)} />
          <Metric label="AI 复审题" value={String(aiReviewedCount)} />
          <Metric label="待复核题" value={String(pendingAnswerReviewCount)} />
          <Metric label="失败" value={String(failedCount)} />
        </div>
      </SectionCard>

      {loading ? <Message message="正在加载批量结果..." /> : null}
      {data?.ai_review_active ? <Message message="强模型正在复审同题分差较大的答案，页面会自动刷新直到完成。" /> : null}
      {data?.ai_review_statuses.includes('failed') ? <Message message="部分批次 AI 复审失败，相关题目已标记为待教师复核。" tone="error" /> : null}
      {error ? <Message message={error} tone="error" /> : null}

      {data ? (
        <section className="overflow-hidden rounded-3xl border border-ink-900/10 bg-white shadow-soft">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-ink-900/10 bg-paper px-5 py-4">
            <div>
              <h3 className="font-display text-2xl text-ink-950">{data.exam.title}</h3>
              <p className="mt-1 text-sm text-ink-700">{data.exam.description || '暂无考试说明。'}</p>
            </div>
            <Link
              to={`/exams/${numericExamId}/submissions`}
              className="rounded-full border border-slateBlue-200 bg-slateBlue-50 px-4 py-2 text-sm font-semibold text-slateBlue-500 transition hover:bg-slateBlue-100"
            >
              管理学生答卷
            </Link>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-ink-900/10 text-sm">
              <thead className="bg-white text-left text-[11px] uppercase tracking-[0.2em] text-ink-700">
                <tr>
                  <th className="px-5 py-4">学生</th>
                  <th className="px-5 py-4">状态</th>
                  <th className="px-5 py-4">总分</th>
                  {data.questions.map((question) => (
                    <th key={question.id} className="px-5 py-4">
                      {question.question_no}
                    </th>
                  ))}
                  <th className="px-5 py-4">复核</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-900/10 bg-white">
                {data.rows.map((row) => (
                  <tr key={row.submission_id} className="align-top">
                    <td className="px-5 py-4">
                      <div className="font-semibold text-ink-950">{row.student_name || '未知学生'}</div>
                      <div className="mt-1 text-xs text-ink-700">{row.student_id || '暂无学号'}</div>
                      {row.source_mode ? (
                        <div className="mt-2 text-[11px] font-semibold text-slateBlue-500">
                          {formatSourceMode(row.source_mode)}{row.split_confidence !== null && row.split_confidence !== undefined ? ` · 拆分置信度 ${Math.round(row.split_confidence * 100)}%` : ''}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-5 py-4">
                      <StatusBadge status={row.status} />
                    </td>
                    <td className="px-5 py-4 font-semibold text-ink-950">{formatScore(row.total_score)}</td>
                    {data.questions.map((question) => {
                      const score = row.question_scores[question.question_no]
                      return (
                        <td key={question.id} className="px-5 py-4 font-medium text-ink-900">
                          {score === undefined && isSubmissionActive(row.status) ? (
                            <span className="text-xs font-semibold text-slateBlue-500">评分中</span>
                          ) : (
                            formatScore(score ?? 0)
                          )}
                        </td>
                      )
                    })}
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-2">
                        <Link
                          to={`/exams/${numericExamId}/review/${row.submission_id}`}
                          className="rounded-full border border-ink-900/10 bg-white px-3 py-2 text-xs font-semibold text-ink-950 transition hover:bg-paper"
                        >
                          打开复核
                        </Link>
                        <button
                          type="button"
                          onClick={() => setDeleteTarget(row.submission_id)}
                          className="rounded-full p-1.5 text-ink-700/50 transition hover:bg-red-50 hover:text-red-600"
                          title="删除答卷"
                        >
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="删除答卷"
        message="删除后，该学生的答卷和评分数据将永久丢失。确定要删除吗？"
        confirmLabel="删除"
        tone="danger"
        loading={deleting}
        onConfirm={() => void handleDelete()}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-ink-900/10 bg-white px-4 py-4 shadow-sm">
      <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-ink-700">{label}</div>
      <div className="mt-2 font-display text-3xl text-ink-950">{value}</div>
    </div>
  )
}

function formatSourceMode(mode: string): string {
  switch (mode) {
    case 'zip':
      return 'ZIP 批量'
    case 'combined_fixed':
      return '固定页拆分'
    case 'combined_auto':
      return '自动拆分'
    default:
      return mode
  }
}

function Message({ message, tone = 'neutral' }: { message: string; tone?: 'neutral' | 'error' }) {
  return (
    <div
      className={toClassNames(
        'rounded-2xl border px-4 py-3 text-sm',
        tone === 'error' ? 'border-red-200 bg-red-50 text-red-700' : 'border-ink-900/10 bg-white/80 text-ink-700',
      )}
    >
      {message}
    </div>
  )
}
