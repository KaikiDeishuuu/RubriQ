import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import {
  downloadBlob,
  exportResultsCsv,
  exportResultsXlsx,
  getResults,
} from '../lib/api'
import { formatScore, toClassNames } from '../lib/format'
import type { ExamResultsResponse } from '../lib/types'
import { SectionCard } from '../components/SectionCard'
import { StatusBadge } from '../components/StatusBadge'

export function BatchResultsPage() {
  const { examId } = useParams()
  const numericExamId = Number(examId)
  const [data, setData] = useState<ExamResultsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [exporting, setExporting] = useState<'csv' | 'xlsx' | null>(null)

  useEffect(() => {
    void loadResults()
  }, [numericExamId])

  async function loadResults() {
    if (!Number.isFinite(numericExamId)) {
      setError('考试 ID 无效')
      setLoading(false)
      return
    }
    try {
      setLoading(true)
      setError(null)
      setData(await getResults(numericExamId))
    } catch (error) {
      setError(error instanceof Error ? error.message : '加载结果失败')
    } finally {
      setLoading(false)
    }
  }

  async function handleExport(format: 'csv' | 'xlsx') {
    if (!Number.isFinite(numericExamId)) {
      return
    }
    setExporting(format)
    try {
      const blob = format === 'csv' ? await exportResultsCsv(numericExamId) : await exportResultsXlsx(numericExamId)
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
          </div>
        }
      >
        <div className="grid gap-4 md:grid-cols-4">
          <Metric label="答卷数" value={String(data?.rows.length ?? 0)} />
          <Metric label="已评分" value={String(gradedCount)} />
          <Metric label="待复核" value={String(reviewCount)} />
          <Metric label="失败" value={String(failedCount)} />
        </div>
      </SectionCard>

      {loading ? <Message message="正在加载批量结果..." /> : null}
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
                    </td>
                    <td className="px-5 py-4">
                      <StatusBadge status={row.status} />
                    </td>
                    <td className="px-5 py-4 font-semibold text-ink-950">{formatScore(row.total_score)}</td>
                    {data.questions.map((question) => (
                      <td key={question.id} className="px-5 py-4 font-medium text-ink-900">
                        {formatScore(row.question_scores[question.question_no] ?? 0)}
                      </td>
                    ))}
                    <td className="px-5 py-4">
                      <Link
                        to={`/exams/${numericExamId}/review/${row.submission_id}`}
                        className="rounded-full border border-ink-900/10 bg-white px-3 py-2 text-xs font-semibold text-ink-950 transition hover:bg-paper"
                      >
                        打开复核
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
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
