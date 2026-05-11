import { FormEvent, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { BadCaseReportButton } from '../components/BadCaseReportButton'
import { PreviewPanel } from '../components/PreviewPanel'
import { SectionCard } from '../components/SectionCard'
import { StatusBadge } from '../components/StatusBadge'
import {
  downloadBlob,
  exportSubmissionPdf,
  getSubmission,
  overrideAnswer,
  processSubmission,
  updateDeductionSummary,
  updateSubmissionTeacherFinalized,
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
  const [exportingPdf, setExportingPdf] = useState(false)
  const [savingOverride, setSavingOverride] = useState(false)
  const [savingReviewFlag, setSavingReviewFlag] = useState(false)
  const [savingTeacherFinalized, setSavingTeacherFinalized] = useState(false)
  const [deductionDraft, setDeductionDraft] = useState<string>('')
  const [deductionDraftDirty, setDeductionDraftDirty] = useState(false)
  const [savingDeduction, setSavingDeduction] = useState(false)
  const deductionDraftDirtyRef = useRef(false)
  const loadingRef = useRef(false)
  const backgroundLoadingRef = useRef(false)
  const manualQuestionSelectionRef = useRef(false)

  useEffect(() => {
    deductionDraftDirtyRef.current = false
    setDeductionDraftDirty(false)
    void loadSubmission()
  }, [numericSubmissionId])

  useEffect(() => {
    if (!submission || (!isSubmissionActive(submission.status) && !submission.answers.some((answer) => answer.review_decision === 'in_progress'))) {
      return
    }
    const timerId = window.setInterval(() => {
      void loadSubmission({ background: true })
    }, 3000)
    return () => window.clearInterval(timerId)
  }, [submission?.status, submission?.answers])

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
      const data = await getSubmission(numericSubmissionId)
      setSubmission(data)
      if (!background || !deductionDraftDirtyRef.current) {
        setDeductionDraft(data.deduction_summary ?? '')
        deductionDraftDirtyRef.current = false
        setDeductionDraftDirty(false)
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : '加载答卷失败')
    } finally {
      requestRef.current = false
      if (!background) {
        setLoading(false)
      }
    }
  }

  async function handleSaveDeduction() {
    if (!submission) {
      return
    }
    setSavingDeduction(true)
    try {
      const updated = await updateDeductionSummary(submission.id, { summary: deductionDraft })
      setSubmission(updated)
      setDeductionDraft(updated.deduction_summary ?? '')
      deductionDraftDirtyRef.current = false
      setDeductionDraftDirty(false)
    } catch (error) {
      setError(error instanceof Error ? error.message : '保存扣分摘要失败')
    } finally {
      setSavingDeduction(false)
    }
  }

  async function handleResetDeduction() {
    if (!submission) {
      return
    }
    setSavingDeduction(true)
    try {
      const updated = await updateDeductionSummary(submission.id, { reset: true })
      setSubmission(updated)
      setDeductionDraft(updated.deduction_summary ?? '')
      deductionDraftDirtyRef.current = false
      setDeductionDraftDirty(false)
    } catch (error) {
      setError(error instanceof Error ? error.message : '恢复扣分摘要失败')
    } finally {
      setSavingDeduction(false)
    }
  }

  async function handleProcess() {
    if (!submission || (submission.batch_id !== null && !submission.split_confirmed)) {
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

  async function handleExportPdf() {
    if (!submission || submissionIsActive) {
      return
    }
    setExportingPdf(true)
    try {
      const blob = await exportSubmissionPdf(submission.id)
      await downloadBlob(blob, `submission-${submission.id}-review.pdf`)
    } catch (error) {
      setError(error instanceof Error ? error.message : '导出评分说明 PDF 失败')
    } finally {
      setExportingPdf(false)
    }
  }

  async function handleTeacherFinalized() {
    if (!submission) {
      return
    }
    setSavingTeacherFinalized(true)
    try {
      const updated = await updateSubmissionTeacherFinalized(submission.id, { teacher_finalized: !submission.teacher_finalized })
      setSubmission(updated)
      setDeductionDraft(updated.deduction_summary ?? '')
    } catch (error) {
      setError(error instanceof Error ? error.message : '保存整卷终审标记失败')
    } finally {
      setSavingTeacherFinalized(false)
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

  async function handleReviewFlag(answer: Answer, reviewed: boolean) {
    setSavingReviewFlag(true)
    try {
      await overrideAnswer(answer.id, { reviewed })
      await loadSubmission()
    } catch (error) {
      setError(error instanceof Error ? error.message : '保存复核状态失败')
    } finally {
      setSavingReviewFlag(false)
    }
  }

  const pages =
    submission?.pages.map((page) => ({
      label: `Page ${page.page_no}`,
      storagePath: page.image_path,
    })) ?? []
  const answerByQuestion = new Map(submission?.answers.map((answer) => [answer.question_id, answer]) ?? [])
  const activeQuestion =
    submission?.exam.questions.find((question) => question.id === selectedQuestionId) ?? submission?.exam.questions[0] ?? null
  const activeAnswer = activeQuestion ? answerByQuestion.get(activeQuestion.id) ?? null : null
  const activeAnswerReviewing = activeAnswer?.review_decision === 'in_progress'
  const completedQuestionCount = submission?.answers.length ?? 0
  const totalQuestionCount = submission?.exam.questions.length ?? 0
  const reviewedQuestionCount = submission?.answers.filter((answer) => !answer.needs_human_review).length ?? 0
  const pendingReviewQuestionCount = submission?.answers.filter((answer) => answer.needs_human_review).length ?? 0
  const submissionIsActive = submission ? isSubmissionActive(submission.status) : false
  const splitLocked = Boolean(submission?.batch_id !== null && submission && !submission.split_confirmed)
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
              onClick={() => void handleTeacherFinalized()}
              disabled={savingTeacherFinalized || !submission}
              className={toClassNames(
                'rounded-full px-4 py-2 text-sm font-semibold transition disabled:opacity-50',
                submission?.teacher_finalized
                  ? 'border border-sage-200 bg-sage-50 text-sage-500 hover:bg-sage-100'
                  : 'border border-gold-200 bg-gold-50 text-amber-800 hover:bg-gold-100',
              )}
            >
              {savingTeacherFinalized ? '正在保存...' : submission?.teacher_finalized ? '取消终审标记' : '标记整卷已终审'}
            </button>
            <button
              type="button"
              onClick={() => void handleExportPdf()}
              disabled={exportingPdf || !submission || submissionIsActive}
              className="rounded-full border border-ink-900/10 bg-white px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-paper disabled:opacity-50"
            >
              {exportingPdf ? '正在导出...' : '导出评分说明 PDF'}
            </button>
            <button
              type="button"
              onClick={() => void handleProcess()}
              disabled={processing || !submission || submissionIsActive || splitLocked}
              className="rounded-full bg-ink-950 px-4 py-2 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:opacity-50"
            >
              {splitLocked ? '等待拆分确认' : processing || submissionIsActive ? '处理中...' : '开始批改'}
            </button>
          </div>
        }
      >
        <div className="grid gap-4 md:grid-cols-4 xl:grid-cols-8">
          <Metric label="学生" value={submission?.student_name || '未知'} />
          <Metric label="学号" value={submission?.student_id || '待识别'} />
          <Metric label="总分" value={formatScore(submission?.total_score ?? 0)} />
          <Metric label="复核进度" value={`${reviewedQuestionCount}/${completedQuestionCount || totalQuestionCount}`} />
          <Metric label="待复核" value={String(pendingReviewQuestionCount)} />
          <Metric label="整卷终审" value={submission?.teacher_finalized ? '已终审' : '未标记'} />
          <Metric label="来源" value={submission?.source_mode ? formatSourceMode(submission.source_mode) : '单份上传'} />
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
      {splitLocked ? <Message message="该答卷来自批量上传，必须先在拆分预览页确认页段后才能开始批改。" tone="error" /> : null}

      {submission ? (
        <SectionCard
          title="扣分摘要"
          description="紧贴 rubric 自动生成，可编辑后导出 PDF 也将使用编辑后的版本。"
          action={
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void handleSaveDeduction()}
                disabled={savingDeduction || (deductionDraft === (submission.deduction_summary ?? ''))}
                className="rounded-full bg-ink-950 px-4 py-2 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:opacity-50"
              >
                {savingDeduction ? '保存中...' : '保存修改'}
              </button>
              <button
                type="button"
                onClick={() => void handleResetDeduction()}
                disabled={savingDeduction || !submission.deduction_summary_edited}
                className="rounded-full border border-ink-900/10 bg-white px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-paper disabled:opacity-50"
              >
                恢复 AI 自动生成
              </button>
            </div>
          }
        >
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2 text-xs">
              <span
                className={toClassNames(
                  'rounded-full px-3 py-1 font-semibold ring-1 ring-inset',
                  submission.deduction_summary_edited
                    ? 'bg-gold-50 text-amber-800 ring-gold-200'
                    : 'bg-paper text-ink-700 ring-ink-900/10',
                )}
              >
                {submission.deduction_summary_edited ? '教师已编辑（重评不会覆盖）' : 'AI 自动生成（每次重评后自动刷新）'}
              </span>
              {deductionDraftDirty ? (
                <span className="rounded-full bg-amber-50 px-3 py-1 font-semibold text-amber-800 ring-1 ring-inset ring-amber-200">
                  有未保存修改，后台刷新不会覆盖
                </span>
              ) : null}
            </div>
            <textarea
              value={deductionDraft}
              onChange={(event) => {
                setDeductionDraft(event.target.value)
                deductionDraftDirtyRef.current = true
                setDeductionDraftDirty(true)
              }}
              rows={Math.min(20, Math.max(6, deductionDraft.split('\n').length + 1))}
              className="w-full rounded-2xl border border-ink-900/10 bg-white px-4 py-3 font-mono text-sm leading-6 text-ink-950 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
              placeholder="例如：第 1 题（满分 5 分，得 3 分，扣 2 分） 单位错误，缺少例子。"
            />
          </div>
        </SectionCard>
      ) : null}

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
                    const hasAiReview = Boolean(answer?.review_score !== null && answer?.review_score !== undefined)
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
                        <div className="mt-2 flex items-start justify-between gap-3">
                          <p className="line-clamp-2 text-sm text-ink-700">{question.title}</p>
                          <div className="flex shrink-0 flex-col items-end gap-1">
                            {hasAiReview ? <AiReviewBadge /> : null}
                            <ReviewBadge answer={answer} active={submissionIsActive} />
                          </div>
                        </div>
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
              action={pages[selectedPageIndex] ? (
                <BadCaseReportButton
                  imageStoragePath={pages[selectedPageIndex].storagePath}
                  routeKey="vision_student_extraction"
                  examId={submission.exam_id}
                  submissionId={submission.id}
                  compact
                />
              ) : null}
            />
          </div>

          <div className="space-y-6 min-w-0">
            <SectionCard
              title="答案复核"
              description={activeQuestion ? `${activeQuestion.question_no} · ${activeQuestion.title}` : '请选择一道题进行复核。'}
            >
              {activeQuestion && activeAnswer ? (
                <div className="space-y-5">
                  <div className="grid gap-3 md:grid-cols-4">
                    <InfoTile label="AI 得分" value={`${formatScore(activeAnswer.score)} / ${formatScore(activeAnswer.max_score)}`} />
                    <InfoTile label="置信度" value={formatConfidence(activeAnswer.confidence)} tone={activeAnswer.confidence} />
                    <InfoTile label="复核状态" value={activeAnswer.needs_human_review ? '待复核' : '已复核'} />
                    <InfoTile label="最终得分" value={`${formatScore(activeAnswer.effective_score)} / ${formatScore(activeAnswer.max_score)}`} />
                  </div>

                  <AiReviewPanel answer={activeAnswer} />

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
                        {activeAnswerReviewing ? (
                          <Message message="AI 正在复审本题，完成前暂不能人工改分或确认复核；页面会自动刷新。" tone="warning" />
                        ) : null}
                        <label className="block space-y-2">
                          <span className="text-sm font-semibold text-ink-800">老师改分</span>
                          <input
                            name="teacher_override_score"
                            defaultValue={activeAnswer.teacher_override_score ?? activeAnswer.score}
                            type="number"
                            step="0.1"
                            min="0"
                            max={activeAnswer.max_score}
                            disabled={activeAnswerReviewing}
                            className="w-full rounded-2xl border border-ink-900/10 bg-paper px-4 py-3 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100 disabled:opacity-50"
                          />
                        </label>
                        <label className="block space-y-2">
                          <span className="text-sm font-semibold text-ink-800">老师评语</span>
                          <textarea
                            name="teacher_comment"
                            rows={4}
                            defaultValue={activeAnswer.teacher_comment ?? ''}
                            placeholder="说明改分原因，或确认 AI 评分无误。"
                            disabled={activeAnswerReviewing}
                            className="w-full rounded-2xl border border-ink-900/10 bg-paper px-4 py-3 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100 disabled:opacity-50"
                          />
                        </label>
                        <div className="flex flex-wrap gap-2">
                          <button
                            type="submit"
                            disabled={savingOverride || activeAnswerReviewing}
                            className="rounded-full bg-ink-950 px-5 py-3 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:opacity-50"
                          >
                            {savingOverride ? '正在保存...' : '保存改分'}
                          </button>
                          <button
                            type="button"
                            onClick={() => void handleReviewFlag(activeAnswer, true)}
                            disabled={savingReviewFlag || activeAnswerReviewing || !activeAnswer.needs_human_review}
                            className="rounded-full border border-sage-200 bg-sage-50 px-5 py-3 text-sm font-semibold text-sage-400 transition hover:bg-sage-100 disabled:opacity-50"
                          >
                            {savingReviewFlag ? '正在保存...' : '确认本题已复核'}
                          </button>
                          <button
                            type="button"
                            onClick={() => void handleReviewFlag(activeAnswer, false)}
                            disabled={savingReviewFlag || activeAnswerReviewing || activeAnswer.needs_human_review}
                            className="rounded-full border border-gold-200 bg-gold-50 px-5 py-3 text-sm font-semibold text-amber-800 transition hover:bg-gold-100 disabled:opacity-50"
                          >
                            重新标记需复核
                          </button>
                        </div>
                      </form>
                    </div>
                  </div>

                  <details className="rounded-2xl border border-ink-900/10 bg-paper p-4">
                    <summary className="cursor-pointer text-sm font-semibold text-ink-950">AI 原始响应</summary>
                    <div className="mt-3 space-y-3">
                      <RawResponseBlock title="最终 AI 原始响应" value={activeAnswer.raw_ai_response} />
                      <RawResponseBlock title="快速评分原始响应" value={activeAnswer.fast_raw_ai_response} />
                      <RawResponseBlock title="强模型复审原始响应" value={activeAnswer.review_raw_ai_response} />
                    </div>
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

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-ink-900/10 bg-white px-4 py-4 shadow-sm">
      <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-ink-700">{label}</div>
      <div className="mt-2 font-display text-2xl text-ink-950">{value}</div>
    </div>
  )
}

function AiReviewBadge() {
  return (
    <span className="rounded-full bg-slateBlue-50 px-2.5 py-1 text-[11px] font-semibold text-slateBlue-500 ring-1 ring-inset ring-slateBlue-200">
      已复审
    </span>
  )
}

function ReviewBadge({ answer, active }: { answer: Answer | undefined; active: boolean }) {
  if (!answer) {
    return (
      <span className="shrink-0 rounded-full bg-paper px-2.5 py-1 text-[11px] font-semibold text-ink-700 ring-1 ring-inset ring-ink-900/10">
        {active ? '评分中' : '未评分'}
      </span>
    )
  }
  return answer.needs_human_review ? (
    <span className="shrink-0 rounded-full bg-gold-50 px-2.5 py-1 text-[11px] font-semibold text-amber-800 ring-1 ring-inset ring-gold-200">
      待复核
    </span>
  ) : (
    <span className="shrink-0 rounded-full bg-sage-100 px-2.5 py-1 text-[11px] font-semibold text-sage-400 ring-1 ring-inset ring-sage-200">
      已复核
    </span>
  )
}

function AiReviewPanel({ answer }: { answer: Answer }) {
  const hasReview = answer.review_score !== null && answer.review_score !== undefined
  const triggers = answer.review_triggers ?? []
  if (!hasReview && triggers.length === 0 && answer.review_decision === 'not_required') {
    return null
  }
  return (
    <div className="rounded-2xl border border-slateBlue-200 bg-slateBlue-50/60 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slateBlue-500">AI 复审</div>
          <p className="mt-1 text-sm text-ink-700">快速模型先评分，触发质量规则后由强模型复审；最终仍由老师确认。</p>
        </div>
        <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-slateBlue-500 ring-1 ring-inset ring-slateBlue-200">
          {formatReviewDecision(answer.review_decision)}
        </span>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <InfoTile label="快速得分" value={answer.fast_score !== null && answer.fast_score !== undefined ? `${formatScore(answer.fast_score)} / ${formatScore(answer.max_score)}` : '-'} tone={answer.fast_confidence ?? undefined} />
        <InfoTile label="复审得分" value={hasReview ? `${formatScore(answer.review_score)} / ${formatScore(answer.max_score)}` : '未复审'} tone={answer.review_confidence ?? undefined} />
        <InfoTile label="分差" value={formatReviewDelta(answer)} />
      </div>
      {triggers.length > 0 ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {triggers.map((trigger) => (
            <span key={trigger} className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-ink-700 ring-1 ring-inset ring-ink-900/10">
              {formatReviewTrigger(trigger)}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function RawResponseBlock({ title, value }: { title: string; value: string | null }) {
  return (
    <div>
      <div className="text-xs font-semibold text-ink-700">{title}</div>
      <pre className="mt-1 overflow-auto whitespace-pre-wrap rounded-2xl bg-white p-3 text-xs leading-6 text-ink-800 ring-1 ring-inset ring-ink-900/10">
        {value || '暂无原始响应。'}
      </pre>
    </div>
  )
}

function formatReviewDelta(answer: Answer): string {
  if (answer.fast_score === null || answer.fast_score === undefined || answer.review_score === null || answer.review_score === undefined) {
    return '-'
  }
  const delta = Math.abs(Number(answer.review_score) - Number(answer.fast_score))
  return formatScore(delta)
}

function formatReviewDecision(decision: string): string {
  switch (decision) {
    case 'accepted_review':
      return '采用强模型复审'
    case 'failed':
      return '复审失败，需老师复核'
    case 'kept_fast':
      return '保留快速评分'
    case 'needs_teacher_review':
      return '需老师复核'
    default:
      return '无需强模型复审'
  }
}

function formatReviewTrigger(trigger: string): string {
  switch (trigger) {
    case 'low_confidence':
      return '低置信度'
    case 'model_requested_review':
      return '模型建议复核'
    case 'missing_rubric_evidence':
      return '评分项证据不足'
    case 'score_variance':
      return '同题分差较大'
    case 'score_delta':
      return '快慢模型分差较大'
    default:
      return trigger
  }
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

function Message({ message, tone = 'neutral' }: { message: string; tone?: 'neutral' | 'error' | 'warning' }) {
  const toneClass = tone === 'error'
    ? 'border-red-200 bg-red-50 text-red-700'
    : tone === 'warning'
      ? 'border-gold-200 bg-gold-50 text-amber-800'
      : 'border-ink-900/10 bg-white/80 text-ink-700'
  return (
    <div className={toClassNames('rounded-2xl border px-4 py-3 text-sm', toneClass)}>
      {message}
    </div>
  )
}
