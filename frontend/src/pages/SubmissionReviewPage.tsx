import { FormEvent, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { PreviewPanel } from '../components/PreviewPanel'
import { SectionCard } from '../components/SectionCard'
import { StatusBadge } from '../components/StatusBadge'
import {
  buildStorageUrl,
  getSubmission,
  overrideAnswer,
  processSubmission,
} from '../lib/api'
import { confidenceTone, formatConfidence, formatScore, isSubmissionActive, toClassNames } from '../lib/format'
import type { Answer, ConfidenceLevel, SubmissionDetail, SubmissionStatus } from '../lib/types'

export function SubmissionReviewPage() {
  const { examId, submissionId } = useParams()
  const numericExamId = Number(examId)
  const numericSubmissionId = Number(submissionId)
  const [submission, setSubmission] = useState<SubmissionDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedPageIndex, setSelectedPageIndex] = useState(0)
  const [selectedQuestionId, setSelectedQuestionId] = useState<number | null>(null)
  const [processing, setProcessing] = useState(false)
  const [savingOverride, setSavingOverride] = useState(false)
  const loadingRef = useRef(false)
  const backgroundLoadingRef = useRef(false)
  const manualQuestionSelectionRef = useRef(false)

  useEffect(() => {
    void loadSubmission()
  }, [numericSubmissionId])

  useEffect(() => {
    if (!submission || !isSubmissionActive(submission.status)) {
      return
    }
    const timerId = window.setInterval(() => {
      void loadSubmission({ background: true })
    }, 3000)
    return () => window.clearInterval(timerId)
  }, [submission?.status])

  useEffect(() => {
    manualQuestionSelectionRef.current = false
    if (submission?.exam.questions.length) {
      setSelectedQuestionId((current) => current ?? submission.exam.questions[0].id)
    }
    if (submission?.pages.length) {
      setSelectedPageIndex(0)
    }
  }, [submission?.id])

  async function loadSubmission({ background = false }: { background?: boolean } = {}) {
    if (!Number.isFinite(numericSubmissionId)) {
      setError('答卷 ID 无效')
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
      setSubmission(await getSubmission(numericSubmissionId))
    } catch (error) {
      setError(error instanceof Error ? error.message : '加载答卷失败')
    } finally {
      requestRef.current = false
      if (!background) {
        setLoading(false)
      }
    }
  }

  async function handleProcess() {
    if (!submission) {
      return
    }
    setProcessing(true)
    try {
      await processSubmission(submission.id)
      await loadSubmission()
    } catch (error) {
      setError(error instanceof Error ? error.message : '处理答卷失败')
    } finally {
      setProcessing(false)
    }
  }

  async function handleOverride(event: FormEvent<HTMLFormElement>, answer: Answer) {
    event.preventDefault()
    setSavingOverride(true)
    try {
      const formData = new FormData(event.currentTarget)
      const scoreRaw = String(formData.get('teacher_override_score') ?? '').trim()
      const teacherComment = String(formData.get('teacher_comment') ?? '').trim()
      await overrideAnswer(answer.id, {
        teacher_override_score: scoreRaw === '' ? null : Number(scoreRaw),
        teacher_comment: teacherComment === '' ? null : teacherComment,
      })
      await loadSubmission()
    } catch (error) {
      setError(error instanceof Error ? error.message : '保存人工改分失败')
    } finally {
      setSavingOverride(false)
    }
  }

  const pages =
    submission?.pages.map((page) => ({
      label: `Page ${page.page_no}`,
      url: buildStorageUrl(page.image_path),
    })) ?? []
  const answerByQuestion = new Map(submission?.answers.map((answer) => [answer.question_id, answer]) ?? [])
  const activeQuestion =
    submission?.exam.questions.find((question) => question.id === selectedQuestionId) ?? submission?.exam.questions[0] ?? null
  const activeAnswer = activeQuestion ? answerByQuestion.get(activeQuestion.id) ?? null : null
  const completedQuestionCount = submission?.answers.length ?? 0
  const totalQuestionCount = submission?.exam.questions.length ?? 0
  const submissionIsActive = submission ? isSubmissionActive(submission.status) : false
  const completedQuestion = submission?.exam.questions.find((question) => answerByQuestion.has(question.id)) ?? null
  const activeQuestionIsWaiting = Boolean(submissionIsActive && activeQuestion && !activeAnswer && completedQuestion)

  useEffect(() => {
    if (!submissionIsActive || manualQuestionSelectionRef.current || activeAnswer || !completedQuestion) {
      return
    }
    setSelectedQuestionId(completedQuestion.id)
    const completedAnswer = answerByQuestion.get(completedQuestion.id)
    if (completedAnswer?.source_page) {
      setSelectedPageIndex(Math.max(0, completedAnswer.source_page - 1))
    }
  }, [submissionIsActive, activeAnswer, completedQuestion, answerByQuestion])

  return (
    <div className="space-y-6">
      <SectionCard
        title={submission ? `${submission.student_name || '学生答卷'}` : '答卷复核'}
        description="查看答卷页面和 AI 提取的答案，必要时手动修改分数和评语。"
        action={
          <div className="flex flex-wrap gap-2">
            <Link
              to={Number.isFinite(numericExamId) ? `/exams/${numericExamId}/results` : '/exams'}
              className="rounded-full border border-ink-900/10 bg-white px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-paper"
            >
              返回结果
            </Link>
            <button
              type="button"
              onClick={() => void handleProcess()}
              disabled={processing || !submission || submissionIsActive}
              className="rounded-full bg-ink-950 px-4 py-2 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:opacity-50"
            >
              {processing || submissionIsActive ? '处理中...' : '开始批改'}
            </button>
          </div>
        }
      >
        <div className="grid gap-4 md:grid-cols-4">
          <Metric label="学生" value={submission?.student_name || '未知'} />
          <Metric label="学号" value={submission?.student_id || '待识别'} />
          <Metric label="总分" value={formatScore(submission?.total_score ?? 0)} />
          <div className="rounded-2xl border border-ink-900/10 bg-white px-4 py-4 shadow-sm">
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-ink-700">状态</div>
            <div className="mt-3">
              {submission ? <StatusBadge status={submission.status} /> : <span className="text-sm text-ink-700">加载中</span>}
            </div>
          </div>
        </div>
      </SectionCard>

      {loading ? <Message message="正在加载答卷详情..." /> : null}
      {error ? <Message message={error} tone="error" /> : null}
      {submissionIsActive && submission ? <ProcessingWorkflow status={submission.status} /> : null}

      {submission ? (
        <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
          <div className="space-y-6">
            <SectionCard title="题目导航" description={`选择题目，查看该题得分、答案和评分证据。已完成 ${completedQuestionCount}/${totalQuestionCount} 题。`}>
              {submission.exam.questions.length === 0 ? (
                <Message message="评分标准尚未解析。" />
              ) : (
                <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
                  {submission.exam.questions.map((question) => {
                    const answer = answerByQuestion.get(question.id)
                    const labelScore = answer
                      ? `${formatScore(answer.effective_score)}/${formatScore(question.max_score)}`
                      : submissionIsActive
                        ? '评分中'
                        : '暂无答案'
                    return (
                      <button
                        type="button"
                        key={question.id}
                        onClick={() => {
                          manualQuestionSelectionRef.current = true
                          setSelectedQuestionId(question.id)
                          if (answer?.source_page) {
                            setSelectedPageIndex(Math.max(0, answer.source_page - 1))
                          }
                        }}
                        className={toClassNames(
                          'rounded-2xl border px-4 py-3 text-left transition',
                          question.id === activeQuestion?.id
                            ? 'border-slateBlue-400 bg-slateBlue-50 shadow-lift'
                            : 'border-ink-900/10 bg-white hover:-translate-y-0.5 hover:shadow-soft',
                        )}
                      >
                        <div className="flex items-center justify-between gap-4">
                          <div className="font-semibold text-ink-950">{question.question_no}</div>
                          <span className="text-xs font-semibold text-ink-700">{labelScore}</span>
                        </div>
                        <p className="mt-2 line-clamp-2 text-sm text-ink-700">{question.title}</p>
                      </button>
                    )
                  })}
                </div>
              )}
            </SectionCard>
            <PreviewPanel
              title="页面预览"
              description="浏览学生答卷页面，点击图片可放大查看。"
              pages={pages}
              activeIndex={selectedPageIndex}
              onChange={setSelectedPageIndex}
            />
          </div>

          <div className="space-y-6 min-w-0">
            <SectionCard
              title="答案复核"
              description={activeQuestion ? `${activeQuestion.question_no} · ${activeQuestion.title}` : '请选择一道题进行复核。'}
            >
              {activeQuestion && activeAnswer ? (
                <div className="space-y-5">
                  <div className="grid gap-3 grid-cols-3">
                    <InfoTile label="AI 得分" value={`${formatScore(activeAnswer.score)} / ${formatScore(activeAnswer.max_score)}`} />
                    <InfoTile label="置信度" value={formatConfidence(activeAnswer.confidence)} tone={activeAnswer.confidence} />
                    <InfoTile label="需要复核" value={activeAnswer.needs_human_review ? '是' : '否'} />
                  </div>

                  <div className="rounded-2xl border border-ink-900/10 bg-paper p-5">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-ink-700">识别出的答案</div>
                    <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-ink-900">
                      {activeAnswer.extracted_answer || '未识别到答案文本。'}
                    </p>
                  </div>

                  <div className="rounded-2xl border border-ink-900/10 bg-white p-5">
                    <div className="mb-4 flex items-center justify-between gap-4">
                      <div>
                        <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-ink-700">评分项评估</div>
                        <div className="mt-1 text-sm text-ink-700">每一行都记录该评分项给分和对应证据，方便复查。</div>
                      </div>
                    </div>
                    <div className="-mx-5 overflow-hidden">
                      <table className="w-full text-left text-sm">
                        <thead className="border-b border-ink-900/10 bg-paper/50 text-[11px] uppercase tracking-[0.18em] text-ink-700">
                          <tr>
                            <th className="w-[45%] px-5 py-3">评分说明</th>
                            <th className="w-[10%] px-5 py-3 text-right">得分</th>
                            <th className="w-[45%] px-5 py-3">证据</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-ink-900/10">
                          {activeAnswer.rubric_results.length > 0 ? (
                            activeAnswer.rubric_results.map((result) => (
                              <tr key={result.id} className="align-top">
                                <td className="px-5 py-4 align-top">
                                  <div className="font-semibold text-ink-950">评分项 #{result.rubric_item_id}</div>
                                  <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-ink-700">{result.reason}</div>
                                </td>
                                <td className="px-5 py-4 align-top text-right font-semibold text-ink-950">{formatScore(result.awarded_score)}</td>
                                <td className="px-5 py-4 align-top">
                                  <div className="whitespace-pre-wrap text-sm leading-6 text-ink-700">{result.evidence || '暂无证据。'}</div>
                                </td>
                              </tr>
                            ))
                          ) : (
                            <tr>
                              <td className="px-5 py-4 text-sm text-ink-700" colSpan={3}>该答案暂无评分项记录。</td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
                    <div className="rounded-2xl border border-ink-900/10 bg-white p-5">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-ink-700">缺失要点</div>
                      <div className="mt-3 space-y-2">
                        {activeAnswer.missing_points.length > 0 ? (
                          activeAnswer.missing_points.map((point) => (
                            <span
                              key={point}
                              className="block rounded-2xl bg-gold-50 px-3 py-2 text-sm leading-6 text-amber-800 ring-1 ring-inset ring-gold-200"
                            >
                              {point}
                            </span>
                          ))
                        ) : (
                          <span className="text-sm text-ink-700">暂无缺失要点记录。</span>
                        )}
                      </div>
                    </div>

                    <div className="rounded-2xl border border-ink-900/10 bg-white p-5">
                      <form key={activeAnswer.id} className="space-y-4" onSubmit={(event) => void handleOverride(event, activeAnswer)}>
                        <label className="block space-y-2">
                          <span className="text-sm font-semibold text-ink-800">老师改分</span>
                          <input
                            name="teacher_override_score"
                            defaultValue={activeAnswer.teacher_override_score ?? activeAnswer.score}
                            type="number"
                            step="0.1"
                            min="0"
                            max={activeAnswer.max_score}
                            className="w-full rounded-2xl border border-ink-900/10 bg-paper px-4 py-3 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
                          />
                        </label>
                        <label className="block space-y-2">
                          <span className="text-sm font-semibold text-ink-800">老师评语</span>
                          <textarea
                            name="teacher_comment"
                            rows={4}
                            defaultValue={activeAnswer.teacher_comment ?? ''}
                            placeholder="说明改分原因，或确认 AI 评分无误。"
                            className="w-full rounded-2xl border border-ink-900/10 bg-paper px-4 py-3 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
                          />
                        </label>
                        <button
                          type="submit"
                          disabled={savingOverride}
                          className="rounded-full bg-ink-950 px-5 py-3 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:opacity-50"
                        >
                          {savingOverride ? '正在保存...' : '保存改分'}
                        </button>
                      </form>
                    </div>
                  </div>

                  <details className="rounded-2xl border border-ink-900/10 bg-paper p-4">
                    <summary className="cursor-pointer text-sm font-semibold text-ink-950">AI 原始响应</summary>
                    <pre className="mt-3 overflow-auto whitespace-pre-wrap text-xs leading-6 text-ink-800">
                      {activeAnswer.raw_ai_response || '暂无原始响应。'}
                    </pre>
                  </details>
                </div>
              ) : (
                <Message
                  message={
                    activeQuestionIsWaiting
                      ? `该题仍在等待评分，已有 ${completedQuestionCount}/${totalQuestionCount} 题完成，可点击左侧已出分题目先查看。`
                      : submissionIsActive && activeQuestion
                        ? `该题正在等待评分结果，当前已完成 ${completedQuestionCount}/${totalQuestionCount} 题。`
                        : '请先开始批改，或选择已处理的题目查看 AI 评分证据。'
                  }
                />
              )}
            </SectionCard>

            <SectionCard title="识别过程记录" description="这里展示视觉模型返回的学生信息和答卷识别原始记录。">
              <details className="rounded-2xl border border-ink-900/10 bg-paper p-4">
                <summary className="cursor-pointer text-sm font-semibold text-ink-950">学生信息识别原始响应</summary>
                <pre className="mt-3 overflow-auto whitespace-pre-wrap text-xs leading-6 text-ink-800">
                  {submission.raw_extraction_response || '暂无识别原始响应。'}
                </pre>
              </details>
            </SectionCard>
          </div>
        </div>
      ) : null}
    </div>
  )
}

const PIPELINE_STEPS = [
  { key: 'processing' as SubmissionStatus, label: '提交处理', desc: '已接收处理请求' },
  { key: 'rendering' as SubmissionStatus, label: '渲染页面', desc: '将 PDF 逐页转为高清图片' },
  { key: 'extracting' as SubmissionStatus, label: '识别提取', desc: 'AI 视觉模型识别姓名、学号和每道题答案文本' },
  { key: 'grading' as SubmissionStatus, label: 'AI 评分', desc: '按评分标准逐题打分并生成复核证据' },
]

function ProcessingWorkflow({ status }: { status: SubmissionStatus }) {
  const activeIndex = PIPELINE_STEPS.findIndex((step) => step.key === status)
  const currentStep = activeIndex >= 0 ? activeIndex : 0

  return (
    <div
      className="animate-workflow-slide-in rounded-3xl border border-slateBlue-200 bg-gradient-to-br from-slateBlue-50/60 via-white to-white p-6 shadow-soft"
      style={{ animationDelay: '0.1s' }}
    >
      <div className="flex items-center gap-4">
        <span className="relative flex h-4 w-4">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-slateBlue-400 opacity-60" />
          <span className="relative inline-flex h-4 w-4 rounded-full bg-slateBlue-500 shadow-sm" />
        </span>
        <div>
          <h3 className="font-display text-2xl text-slateBlue-500">正在处理答卷</h3>
          <p className="mt-1 text-sm text-ink-700 animate-workflow-pulse">
            {PIPELINE_STEPS[currentStep].desc}
          </p>
        </div>
      </div>

      <div className="mt-6 grid gap-3 md:grid-cols-4">
        {PIPELINE_STEPS.map((step, index) => {
          const isCompleted = index < currentStep
          const isActive = index === currentStep
          const isPending = index > currentStep

          return (
            <div
              key={step.key}
              className="animate-workflow-slide-in rounded-2xl px-4 py-4 text-sm transition-all duration-500"
              style={{ animationDelay: `${0.15 + index * 0.1}s` }}
            >
              <div
                className={toClassNames(
                  'rounded-2xl px-4 py-4 transition-all duration-500',
                  isCompleted && 'bg-sage-50 ring-1 ring-inset ring-sage-200',
                  isActive && 'animate-workflow-shimmer bg-white ring-2 ring-slateBlue-300 shadow-md',
                  isPending && 'bg-white/60 ring-1 ring-inset ring-ink-900/10',
                )}
              >
                <div className="flex items-center gap-3">
                  <span
                    className={toClassNames(
                      'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold transition-all duration-500',
                      isCompleted && 'bg-sage-400 text-white',
                      isActive && 'bg-slateBlue-500 text-white shadow-sm',
                      isPending && 'bg-ink-100 text-ink-700',
                    )}
                  >
                    {isCompleted ? (
                      <svg
                        className="animate-workflow-check h-4 w-4"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={3}
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                      </svg>
                    ) : isActive ? (
                      <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <circle cx="12" cy="12" r="10" strokeDasharray="32" strokeDashoffset="32" strokeLinecap="round" />
                      </svg>
                    ) : (
                      index + 1
                    )}
                  </span>
                  <div className="min-w-0">
                    <div
                      className={toClassNames(
                        'truncate font-semibold transition-colors duration-500',
                        isCompleted && 'text-sage-400',
                        isActive && 'text-slateBlue-500',
                        isPending && 'text-ink-700',
                      )}
                    >
                      {step.label}
                    </div>
                    <div className="mt-0.5 truncate text-[11px] text-ink-700">{step.desc}</div>
                  </div>
                </div>
                {isActive ? (
                  <div className="mt-3 h-1 overflow-hidden rounded-full bg-slateBlue-100">
                    <div
                      className="h-full rounded-full bg-slateBlue-400"
                      style={{
                        width: '100%',
                        animation: 'workflow-shimmer 1.5s linear infinite',
                        backgroundSize: '200% 100%',
                      }}
                    />
                  </div>
                ) : isCompleted ? (
                  <div className="mt-3 h-1 rounded-full bg-sage-200">
                    <div className="h-full w-full rounded-full bg-sage-400 transition-all duration-500" />
                  </div>
                ) : null}
              </div>
            </div>
          )
        })}
      </div>

      <p className="mt-5 text-sm text-ink-700 animate-workflow-pulse">
        {currentStep >= 3
          ? '评分通常需要 10–30 秒，请耐心等待。'
          : currentStep >= 1
            ? 'AI 模型正在处理，稍后进入评分阶段。'
            : '正在准备数据，即将进入 AI 处理阶段。'}
        页面每 3 秒自动刷新。
      </p>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-ink-900/10 bg-white px-4 py-4 shadow-sm">
      <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-ink-700">{label}</div>
      <div className="mt-2 font-display text-2xl text-ink-950">{value}</div>
    </div>
  )
}

function InfoTile({ label, value, tone }: { label: string; value: string; tone?: ConfidenceLevel }) {
  return (
    <div className="rounded-2xl border border-ink-900/10 bg-paper p-4">
      <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-ink-700">{label}</div>
      <div className={toClassNames('mt-2 text-sm font-semibold text-ink-950', tone ? confidenceTone(tone) : '')}>
        {value}
      </div>
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
