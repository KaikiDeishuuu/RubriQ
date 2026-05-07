import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { listExams } from '../lib/api'
import { formatScore, toClassNames } from '../lib/format'
import type { ExamListItem } from '../lib/types'
import { SectionCard } from '../components/SectionCard'

export function ExamListPage() {
  const [exams, setExams] = useState<ExamListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    async function load() {
      try {
        setError(null)
        const data = await listExams()
        if (active) {
          setExams(data)
        }
      } catch (error) {
        if (active) {
          setError(error instanceof Error ? error.message : '加载考试列表失败')
        }
      } finally {
        if (active) {
          setLoading(false)
        }
      }
    }
    load()
    return () => {
      active = false
    }
  }, [])

  return (
    <div className="space-y-6">
      <SectionCard
        title="考试列表"
        description="创建考试、上传评分标准 PDF，然后在人工复核流程中处理学生答卷。"
        action={
          <Link
            to="/exams/new"
            className="inline-flex rounded-full bg-ink-950 px-4 py-2 text-sm font-semibold text-paper transition hover:bg-ink-800"
          >
            新建考试
          </Link>
        }
      >
        <div className="grid gap-4 md:grid-cols-3">
          <Metric label="考试数量" value={String(exams.length)} />
          <Metric label="评分方式" value="按评分标准可追溯评分" />
          <Metric label="导出" value="CSV / Excel" />
        </div>
      </SectionCard>

      {loading ? <StateMessage message="正在加载考试列表..." /> : null}
      {error ? <StateMessage message={error} tone="error" /> : null}

      {!loading && !error ? (
        exams.length === 0 ? (
          <SectionCard
            title="暂无考试"
            description="先创建一个考试，再上传评分标准并开始处理学生答卷。"
          >
            <div className="flex justify-start">
              <Link
                to="/exams/new"
                className="inline-flex rounded-full bg-slateBlue-400 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slateBlue-500"
              >
                新建一个考试
              </Link>
            </div>
          </SectionCard>
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {exams.map((exam) => (
              <article
                key={exam.id}
                className="rounded-3xl border border-ink-900/10 bg-white/85 p-5 shadow-soft transition hover:-translate-y-0.5 hover:shadow-lift"
              >
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h3 className="font-display text-3xl text-ink-950">{exam.title}</h3>
                    <p className="mt-2 max-w-2xl text-sm leading-6 text-ink-700">
                      {exam.description || '暂无考试说明。'}
                    </p>
                  </div>
                  <span
                    className={toClassNames(
                      'rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset',
                      exam.needs_rubric_review
                        ? 'bg-gold-50 text-amber-800 ring-gold-200'
                        : 'bg-sage-100 text-sage-400 ring-sage-200',
                    )}
                  >
                    {exam.needs_rubric_review ? '评分标准待复核' : '评分标准已确认'}
                  </span>
                </div>
                <div className="mt-5 grid grid-cols-3 gap-3 text-sm">
                  <Metric label="题目数" value={String(exam.question_count)} compact />
                  <Metric label="答卷数" value={String(exam.submission_count)} compact />
                  <Metric label="总分" value={formatScore(exam.total_score)} compact />
                </div>
                <div className="mt-5 flex flex-wrap gap-2">
                  <Link
                    to={`/exams/${exam.id}/rubric`}
                    className="rounded-full bg-ink-950 px-4 py-2 text-sm font-semibold text-paper transition hover:bg-ink-800"
                  >
                    复核评分标准
                  </Link>
                  <Link
                    to={`/exams/${exam.id}/submissions`}
                    className="rounded-full border border-ink-900/10 bg-white px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-paper"
                  >
                    上传学生答卷
                  </Link>
                  <Link
                    to={`/exams/${exam.id}/results`}
                    className="rounded-full border border-slateBlue-200 bg-slateBlue-50 px-4 py-2 text-sm font-semibold text-slateBlue-500 transition hover:bg-slateBlue-100"
                  >
                    批量结果
                  </Link>
                </div>
              </article>
            ))}
          </div>
        )
      ) : null}
    </div>
  )
}

function Metric({ label, value, compact = false }: { label: string; value: string; compact?: boolean }) {
  return (
    <div className={toClassNames('rounded-2xl border border-ink-900/10 bg-paper px-4 py-3', compact ? 'min-h-[84px]' : '')}>
      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-700">{label}</div>
      <div className={toClassNames('mt-2 font-display text-2xl text-ink-950', compact ? 'text-xl' : 'text-3xl')}>
        {value}
      </div>
    </div>
  )
}

function StateMessage({ message, tone = 'neutral' }: { message: string; tone?: 'neutral' | 'error' }) {
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
