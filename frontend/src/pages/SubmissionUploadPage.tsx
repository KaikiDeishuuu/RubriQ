import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { DropZone } from '../components/DropZone'
import { PreviewPanel } from '../components/PreviewPanel'
import { SectionCard } from '../components/SectionCard'
import { StatusBadge } from '../components/StatusBadge'
import {
  buildStorageUrl,
  confirmBatchSplit,
  getBatch,
  getResults,
  listBatches,
  processSubmission,
  startBatchGrading,
  updateBatchCandidates,
  uploadBatch,
  uploadSubmissions,
} from '../lib/api'
import { formatScore, isSubmissionActive, toClassNames } from '../lib/format'
import type {
  BatchCandidateUpdatePayload,
  BatchSplitCandidate,
  BatchStatus,
  BatchUploadMode,
  ExamResultsResponse,
  SubmissionBatchDetail,
} from '../lib/types'

type UploadTab = 'single' | BatchUploadMode

const BATCH_TABS: Array<{ mode: UploadTab; label: string; description: string }> = [
  { mode: 'single', label: '单独 PDF', description: '保留原有多 PDF 上传方式。' },
  { mode: 'zip', label: 'ZIP 批量', description: 'ZIP 内每个 PDF 会成为一份学生答卷。' },
  { mode: 'combined_fixed', label: '合并 PDF 固定页', description: '按每份固定页数拆分合并 PDF。' },
  { mode: 'combined_auto', label: '合并 PDF 自动拆分', description: '识别每页页首信息并生成候选页段。' },
]

export function SubmissionUploadPage() {
  const { examId } = useParams()
  const numericExamId = Number(examId)
  const [results, setResults] = useState<ExamResultsResponse | null>(null)
  const [batches, setBatches] = useState<SubmissionBatchDetail[]>([])
  const [activeBatch, setActiveBatch] = useState<SubmissionBatchDetail | null>(null)
  const [candidateDrafts, setCandidateDrafts] = useState<BatchCandidateUpdatePayload[]>([])
  const [activePageIndex, setActivePageIndex] = useState(0)
  const [activeTab, setActiveTab] = useState<UploadTab>('single')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [batchFile, setBatchFile] = useState<File | null>(null)
  const [studentName, setStudentName] = useState('')
  const [studentId, setStudentId] = useState('')
  const [pagesPerSubmission, setPagesPerSubmission] = useState(1)
  const [uploading, setUploading] = useState(false)
  const [batchBusy, setBatchBusy] = useState(false)
  const [processingIds, setProcessingIds] = useState<number[]>([])
  const loadingRef = useRef(false)
  const backgroundLoadingRef = useRef(false)

  useEffect(() => {
    void loadAll()
  }, [numericExamId])

  useEffect(() => {
    if (!activeBatch || !isBatchActive(activeBatch.status)) {
      return
    }
    const timerId = window.setInterval(() => {
      void refreshActiveBatch(activeBatch.id)
    }, 3000)
    return () => window.clearInterval(timerId)
  }, [activeBatch?.id, activeBatch?.status])

  useEffect(() => {
    if (!results?.rows.some((row) => isSubmissionActive(row.status))) {
      return
    }
    const timerId = window.setInterval(() => {
      void loadResults({ background: true })
    }, 3000)
    return () => window.clearInterval(timerId)
  }, [results])

  useEffect(() => {
    if (!activeBatch) {
      setCandidateDrafts([])
      return
    }
    setCandidateDrafts(activeBatch.candidates.map(candidateToDraft))
    setActivePageIndex(0)
  }, [activeBatch?.id, activeBatch?.split_version, activeBatch?.candidates.length])

  async function loadAll() {
    await Promise.all([loadResults(), loadBatches()])
  }

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
      const data = await getResults(numericExamId)
      setResults(data)
    } catch (error) {
      setError(error instanceof Error ? error.message : '加载学生答卷失败')
    } finally {
      requestRef.current = false
      if (!background) {
        setLoading(false)
      }
    }
  }

  async function loadBatches() {
    if (!Number.isFinite(numericExamId)) {
      return
    }
    try {
      const data = await listBatches(numericExamId)
      setBatches(data)
      setActiveBatch((current) => current ? data.find((batch) => batch.id === current.id) ?? current : data[0] ?? null)
    } catch (error) {
      setError(error instanceof Error ? error.message : '加载批量上传记录失败')
    }
  }

  async function refreshActiveBatch(batchId: number) {
    if (!Number.isFinite(numericExamId)) {
      return
    }
    try {
      const batch = await getBatch(numericExamId, batchId)
      setActiveBatch(batch)
      setBatches((current) => [batch, ...current.filter((item) => item.id !== batch.id)])
    } catch (error) {
      setError(error instanceof Error ? error.message : '刷新批次状态失败')
    }
  }

  async function handleUpload() {
    if (files.length === 0 || !Number.isFinite(numericExamId)) {
      return
    }
    setUploading(true)
    try {
      await uploadSubmissions(numericExamId, files, studentName || undefined, studentId || undefined)
      setFiles([])
      await loadResults()
    } catch (error) {
      setError(error instanceof Error ? error.message : '上传学生答卷失败')
    } finally {
      setUploading(false)
    }
  }

  async function handleBatchUpload() {
    if (!batchFile || activeTab === 'single' || !Number.isFinite(numericExamId)) {
      return
    }
    setUploading(true)
    setFeedback(null)
    try {
      const response = await uploadBatch(
        numericExamId,
        activeTab,
        batchFile,
        activeTab === 'combined_fixed' ? pagesPerSubmission : undefined,
      )
      setBatchFile(null)
      setActiveBatch(response.batch)
      setBatches((current) => [response.batch, ...current.filter((batch) => batch.id !== response.batch.id)])
      setFeedback('批量文件已上传，系统正在后台渲染并生成拆分候选。')
    } catch (error) {
      setError(error instanceof Error ? error.message : '上传批量文件失败')
    } finally {
      setUploading(false)
    }
  }

  async function handleSaveCandidates() {
    if (!activeBatch || !Number.isFinite(numericExamId)) {
      return
    }
    setBatchBusy(true)
    try {
      const batch = await updateBatchCandidates(numericExamId, activeBatch.id, candidateDrafts)
      setActiveBatch(batch)
      setBatches((current) => [batch, ...current.filter((item) => item.id !== batch.id)])
      setFeedback('拆分候选已保存。')
    } catch (error) {
      setError(error instanceof Error ? error.message : '保存拆分候选失败')
    } finally {
      setBatchBusy(false)
    }
  }

  async function handleConfirmSplit() {
    if (!activeBatch || !Number.isFinite(numericExamId)) {
      return
    }
    setBatchBusy(true)
    try {
      await updateBatchCandidates(numericExamId, activeBatch.id, candidateDrafts)
      const response = await confirmBatchSplit(numericExamId, activeBatch.id)
      setActiveBatch(response.batch)
      setBatches((current) => [response.batch, ...current.filter((item) => item.id !== response.batch.id)])
      setFeedback(`拆分已确认，已生成 ${response.created_submission_count} 份可批改答卷。`)
      await loadResults()
    } catch (error) {
      setError(error instanceof Error ? error.message : '确认拆分失败')
    } finally {
      setBatchBusy(false)
    }
  }

  async function handleStartBatchGrading() {
    if (!activeBatch || !Number.isFinite(numericExamId)) {
      return
    }
    setBatchBusy(true)
    try {
      const response = await startBatchGrading(numericExamId, activeBatch.id)
      await refreshActiveBatch(activeBatch.id)
      await loadResults()
      setFeedback(`已提交 ${response.queued_submission_count} 份答卷进入后台批改。`)
    } catch (error) {
      setError(error instanceof Error ? error.message : '启动批次批改失败')
    } finally {
      setBatchBusy(false)
    }
  }

  async function handleStartProcessing(submissionId: number) {
    setProcessingIds((current) => [...current, submissionId])
    try {
      await processSubmission(submissionId)
      await loadResults()
    } catch (error) {
      setError(error instanceof Error ? error.message : '启动处理失败')
    } finally {
      setProcessingIds((current) => current.filter((id) => id !== submissionId))
    }
  }

  function updateDraft(index: number, patch: Partial<BatchCandidateUpdatePayload>) {
    setCandidateDrafts((current) => current.map((candidate, candidateIndex) => candidateIndex === index ? { ...candidate, ...patch } : candidate))
  }

  const exam = results?.exam
  const selectedTab = BATCH_TABS.find((tab) => tab.mode === activeTab) ?? BATCH_TABS[0]
  const batchPages = activeBatch?.pages.map((page) => ({ label: `Page ${page.page_no}`, url: buildStorageUrl(page.image_path) })) ?? []
  const validationError = useMemo(() => validateCandidateDrafts(candidateDrafts, activeBatch?.total_pages ?? null), [candidateDrafts, activeBatch?.total_pages])
  const canConfirmSplit = Boolean(activeBatch && candidateDrafts.length > 0 && !validationError && candidateDrafts.every((candidate) => candidate.confirmed && candidate.student_name && candidate.student_id))
  const canStartBatchGrading = Boolean(activeBatch?.status === 'ready_for_grading' || activeBatch?.status === 'completed_with_errors')

  return (
    <div className="space-y-6">
      <SectionCard
        title={exam ? `${exam.title}的学生答卷` : '上传学生答卷'}
        description="上传学生 PDF、ZIP 批次或合并 PDF；合并文件必须先拆分确认，才能进入 AI 批改。"
        action={
          <Link
            to={Number.isFinite(numericExamId) ? `/exams/${numericExamId}/rubric` : '/exams'}
            className="rounded-full border border-ink-900/10 bg-white px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-paper"
          >
            返回评分标准
          </Link>
        }
      >
        <div className="grid gap-4 md:grid-cols-3">
          <Metric label="考试" value={exam?.title ?? '未知'} />
          <Metric label="总分" value={formatScore(exam?.total_score ?? 0)} />
          <Metric label="评分标准状态" value={exam?.needs_rubric_review ? '需要老师确认' : '已确认'} />
        </div>
      </SectionCard>

      {loading ? <InlineMessage message="正在加载批量结果..." /> : null}
      {error ? <InlineMessage message={error} tone="error" /> : null}
      {feedback ? <InlineMessage message={feedback} tone="success" /> : null}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <SectionCard title="上传答卷" description={selectedTab.description}>
          <div className="space-y-5">
            <div className="flex flex-wrap gap-2">
              {BATCH_TABS.map((tab) => (
                <button
                  type="button"
                  key={tab.mode}
                  onClick={() => {
                    setActiveTab(tab.mode)
                    setFiles([])
                    setBatchFile(null)
                  }}
                  className={toClassNames(
                    'rounded-full px-4 py-2 text-sm font-semibold transition',
                    activeTab === tab.mode
                      ? 'bg-ink-950 text-paper'
                      : 'border border-ink-900/10 bg-white text-ink-950 hover:bg-paper',
                  )}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {activeTab === 'single' ? (
              <SinglePdfUpload
                files={files}
                studentName={studentName}
                studentId={studentId}
                uploading={uploading}
                onFilesSelected={setFiles}
                onStudentNameChange={setStudentName}
                onStudentIdChange={setStudentId}
                onUpload={handleUpload}
                onClear={() => setFiles([])}
              />
            ) : (
              <BatchUploadForm
                mode={activeTab}
                file={batchFile}
                pagesPerSubmission={pagesPerSubmission}
                uploading={uploading}
                onFileSelected={(files) => setBatchFile(files[0] ?? null)}
                onPagesPerSubmissionChange={setPagesPerSubmission}
                onUpload={handleBatchUpload}
              />
            )}
          </div>
        </SectionCard>

        <SectionCard title="批量拆分预览" description="所有批次都必须在这里确认拆分候选，确认前不能进入 AI 批改。">
          <div className="space-y-5">
            {batches.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {batches.map((batch) => (
                  <button
                    type="button"
                    key={batch.id}
                    onClick={() => setActiveBatch(batch)}
                    className={toClassNames(
                      'rounded-full px-3 py-2 text-xs font-semibold transition',
                      activeBatch?.id === batch.id
                        ? 'bg-slateBlue-500 text-white'
                        : 'border border-ink-900/10 bg-white text-ink-950 hover:bg-paper',
                    )}
                  >
                    #{batch.id} · {formatBatchMode(batch.mode)} · {formatBatchStatus(batch.status)}
                  </button>
                ))}
              </div>
            ) : (
              <InlineMessage message="暂无批量上传记录。" />
            )}

            {activeBatch ? (
              <div className="space-y-5">
                <BatchSummary batch={activeBatch} />
                {isBatchActive(activeBatch.status) ? <InlineMessage message="系统正在后台渲染或拆分，请稍候，页面会自动刷新。" /> : null}
                {activeBatch.status !== 'ready_for_grading' && activeBatch.status !== 'grading' ? (
                  <InlineMessage message="未完成拆分确认，不能开始 AI 评分。请确认每个候选页段和学生信息。" tone="warning" />
                ) : null}
                {batchPages.length > 0 ? (
                  <PreviewPanel
                    title="页面预览"
                    description="检查每页是否归入正确学生答卷。"
                    pages={batchPages}
                    activeIndex={activePageIndex}
                    onChange={setActivePageIndex}
                  />
                ) : null}
                <CandidateEditor candidates={activeBatch.candidates} drafts={candidateDrafts} onChange={updateDraft} />
                {validationError ? <InlineMessage message={validationError} tone="error" /> : null}
                <div className="flex flex-wrap gap-3">
                  <button
                    type="button"
                    onClick={() => void handleSaveCandidates()}
                    disabled={batchBusy || candidateDrafts.length === 0 || Boolean(validationError)}
                    className="rounded-full border border-ink-900/10 bg-white px-5 py-3 text-sm font-semibold text-ink-950 transition hover:bg-paper disabled:opacity-50"
                  >
                    保存拆分候选
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleConfirmSplit()}
                    disabled={batchBusy || !canConfirmSplit}
                    className="rounded-full bg-ink-950 px-5 py-3 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:opacity-50"
                  >
                    确认拆分
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleStartBatchGrading()}
                    disabled={batchBusy || !canStartBatchGrading}
                    className="rounded-full border border-slateBlue-200 bg-slateBlue-50 px-5 py-3 text-sm font-semibold text-slateBlue-500 transition hover:bg-slateBlue-100 disabled:opacity-50"
                  >
                    开始批改本批次
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        </SectionCard>
      </div>

      <SectionCard title="学生答卷列表" description="确认拆分并生成 Submission 后，可以单独处理每份答卷并查看状态。">
        {results?.rows.some((row) => isSubmissionActive(row.status) || processingIds.includes(row.submission_id)) ? (
          <ProcessingWorkflow />
        ) : null}
        {results ? (
          <div className="overflow-hidden rounded-2xl border border-ink-900/10 bg-white">
            <table className="min-w-full divide-y divide-ink-900/10 text-sm">
              <thead className="bg-paper text-left text-[11px] uppercase tracking-[0.2em] text-ink-700">
                <tr>
                  <th className="px-4 py-3">学生</th>
                  <th className="px-4 py-3">状态</th>
                  <th className="px-4 py-3">分数</th>
                  <th className="px-4 py-3">复核</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-900/10">
                {results.rows.map((row) => (
                  <tr key={row.submission_id} className="align-top">
                    <td className="px-4 py-4">
                      <div className="font-semibold text-ink-950">{row.student_name || '未知学生'}</div>
                      <div className="mt-1 text-xs text-ink-700">{row.student_id || '暂无学号'}</div>
                    </td>
                    <td className="px-4 py-4">
                      <StatusBadge status={row.status} />
                    </td>
                    <td className="px-4 py-4 font-semibold text-ink-950">{formatScore(row.total_score)}</td>
                    <td className="px-4 py-4">
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => handleStartProcessing(row.submission_id)}
                          disabled={processingIds.includes(row.submission_id) || isSubmissionActive(row.status)}
                          className="rounded-full border border-slateBlue-200 bg-slateBlue-50 px-3 py-2 text-xs font-semibold text-slateBlue-500 transition hover:bg-slateBlue-100 disabled:opacity-50"
                        >
                          {processingIds.includes(row.submission_id) || isSubmissionActive(row.status) ? '处理中...' : '开始处理'}
                        </button>
                        <Link
                          to={`/exams/${numericExamId}/review/${row.submission_id}`}
                          className="rounded-full border border-ink-900/10 bg-white px-3 py-2 text-xs font-semibold text-ink-950 transition hover:bg-paper"
                        >
                          打开复核
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </SectionCard>
    </div>
  )
}

function SinglePdfUpload({
  files,
  studentName,
  studentId,
  uploading,
  onFilesSelected,
  onStudentNameChange,
  onStudentIdChange,
  onUpload,
  onClear,
}: {
  files: File[]
  studentName: string
  studentId: string
  uploading: boolean
  onFilesSelected: (files: File[]) => void
  onStudentNameChange: (value: string) => void
  onStudentIdChange: (value: string) => void
  onUpload: () => void
  onClear: () => void
}) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <TextInput label="学生姓名（可选）" value={studentName} onChange={onStudentNameChange} placeholder="可作为默认提示，AI 也会尝试识别" />
        <TextInput label="学号（可选）" value={studentId} onChange={onStudentIdChange} placeholder="可作为默认提示，AI 也会尝试识别" />
      </div>
      <DropZone title="拖拽学生 PDF 到这里" description="每个 PDF 会生成一份学生答卷。" multiple onFilesSelected={onFilesSelected} />
      <FileList files={files} />
      <div className="flex flex-wrap gap-3">
        <button type="button" onClick={onUpload} disabled={files.length === 0 || uploading} className="rounded-full bg-ink-950 px-5 py-3 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:opacity-50">
          {uploading ? '正在上传...' : '上传答卷'}
        </button>
        <button type="button" onClick={onClear} className="rounded-full border border-ink-900/10 bg-white px-5 py-3 text-sm font-semibold text-ink-950 transition hover:bg-paper">
          清空选择
        </button>
      </div>
    </div>
  )
}

function BatchUploadForm({
  mode,
  file,
  pagesPerSubmission,
  uploading,
  onFileSelected,
  onPagesPerSubmissionChange,
  onUpload,
}: {
  mode: BatchUploadMode
  file: File | null
  pagesPerSubmission: number
  uploading: boolean
  onFileSelected: (files: File[]) => void
  onPagesPerSubmissionChange: (value: number) => void
  onUpload: () => void
}) {
  return (
    <div className="space-y-4">
      {mode === 'combined_fixed' ? (
        <label className="block space-y-2">
          <span className="text-sm font-semibold text-ink-800">每份答卷页数</span>
          <input
            type="number"
            min="1"
            value={pagesPerSubmission}
            onChange={(event) => onPagesPerSubmissionChange(Math.max(1, Number(event.target.value) || 1))}
            className="w-full rounded-2xl border border-ink-900/10 bg-white px-4 py-3 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
          />
        </label>
      ) : null}
      <DropZone
        title={mode === 'zip' ? '拖拽 ZIP 到这里' : '拖拽合并 PDF 到这里'}
        description={mode === 'zip' ? 'ZIP 内每个 PDF 会成为候选答卷，文件名会尝试解析学生信息。' : '系统会先渲染所有页面并生成拆分预览，确认前不会评分。'}
        accept={mode === 'zip' ? '.zip' : '.pdf'}
        onFilesSelected={onFileSelected}
      />
      {file ? <FileList files={[file]} /> : null}
      <button type="button" onClick={onUpload} disabled={!file || uploading} className="rounded-full bg-ink-950 px-5 py-3 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:opacity-50">
        {uploading ? '正在上传...' : '上传并生成拆分预览'}
      </button>
    </div>
  )
}

function CandidateEditor({ candidates, drafts, onChange }: { candidates: BatchSplitCandidate[]; drafts: BatchCandidateUpdatePayload[]; onChange: (index: number, patch: Partial<BatchCandidateUpdatePayload>) => void }) {
  if (drafts.length === 0) {
    return <InlineMessage message="暂无拆分候选。" />
  }
  const candidateById = new Map(candidates.map((candidate) => [candidate.id, candidate]))
  return (
    <div className="space-y-3">
      {drafts.map((draft, index) => {
        const original = draft.id ? candidateById.get(draft.id) : null
        const splitConfidence = original?.split_confidence ?? 0
        const risky = Boolean(original?.needs_review || splitConfidence < 0.75 || original?.error_message)
        return (
          <div key={draft.id ?? index} className={toClassNames('rounded-2xl border p-4', risky ? 'border-gold-200 bg-gold-50/60' : 'border-ink-900/10 bg-white')}>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <div className="font-semibold text-ink-950">候选 #{draft.candidate_index ?? index + 1}</div>
              <div className="text-xs font-semibold text-ink-700">置信度 {Math.round(splitConfidence * 100)}%</div>
            </div>
            {original?.error_message ? <InlineMessage message={original.error_message} tone="error" /> : null}
            {risky ? <div className="mb-3 text-xs font-semibold text-amber-800">该候选需要人工复核后才能确认。</div> : null}
            <div className="grid gap-3 md:grid-cols-[minmax(6rem,0.7fr)_minmax(6rem,0.7fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.2fr)_auto]">
              <NumberInput label="起始页" value={draft.start_page} onChange={(value) => onChange(index, { start_page: value })} />
              <NumberInput label="结束页" value={draft.end_page} onChange={(value) => onChange(index, { end_page: value })} />
              <TextInput label="学生姓名" value={draft.student_name ?? ''} onChange={(value) => onChange(index, { student_name: value })} />
              <TextInput label="学号" value={draft.student_id ?? ''} onChange={(value) => onChange(index, { student_id: value })} />
              <TextInput label="复核备注" value={draft.review_notes ?? ''} onChange={(value) => onChange(index, { review_notes: value })} />
              <label className="flex items-end gap-2 pb-3 text-sm font-semibold text-ink-800">
                <input type="checkbox" checked={draft.confirmed} onChange={(event) => onChange(index, { confirmed: event.target.checked })} />
                已确认
              </label>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function BatchSummary({ batch }: { batch: SubmissionBatchDetail }) {
  const needsReviewCount = batch.candidates.filter((candidate) => candidate.needs_review).length
  return (
    <div className="grid gap-3 md:grid-cols-4">
      <Metric label="模式" value={formatBatchMode(batch.mode)} />
      <Metric label="状态" value={formatBatchStatus(batch.status)} />
      <Metric label="页面" value={String(batch.total_pages ?? batch.pages.length)} />
      <Metric label="需复核候选" value={String(needsReviewCount)} />
    </div>
  )
}

function ProcessingWorkflow() {
  const steps = ['已提交处理请求', '渲染答卷页面', '识别学生信息与答案', '按评分标准逐题评分', '刷新结果与复核状态']
  return (
    <div className="rounded-2xl border border-slateBlue-200 bg-slateBlue-50 p-4 text-sm text-slateBlue-500">
      <div className="font-semibold text-slateBlue-500">正在后台处理答卷</div>
      <div className="mt-3 space-y-2">
        {steps.map((step, index) => (
          <div key={step} className="flex items-center gap-3">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-white text-xs font-bold text-slateBlue-500 ring-1 ring-inset ring-slateBlue-100">{index + 1}</span>
            <span>{step}</span>
          </div>
        ))}
      </div>
      <div className="mt-3 text-xs text-ink-700">页面会每 3 秒自动刷新。</div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-ink-900/10 bg-paper p-4">
      <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-ink-700">{label}</div>
      <div className="mt-2 font-display text-2xl text-ink-950">{value}</div>
    </div>
  )
}

function TextInput({ label, value, placeholder, onChange }: { label: string; value: string; placeholder?: string; onChange: (value: string) => void }) {
  return (
    <label className="block space-y-2">
      <span className="text-sm font-semibold text-ink-800">{label}</span>
      <input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="w-full rounded-2xl border border-ink-900/10 bg-white px-4 py-3 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100" />
    </label>
  )
}

function NumberInput({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return (
    <label className="block space-y-2">
      <span className="text-xs font-semibold text-ink-700">{label}</span>
      <input type="number" min="1" value={value} onChange={(event) => onChange(Math.max(1, Number(event.target.value) || 1))} className="w-full min-w-[6rem] rounded-2xl border border-ink-900/10 bg-white px-3 py-2 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100" />
    </label>
  )
}

function FileList({ files }: { files: File[] }) {
  if (files.length === 0) {
    return null
  }
  return (
    <div className="rounded-2xl border border-ink-900/10 bg-paper p-4 text-sm text-ink-700">
      <div className="font-semibold text-ink-950">已选择文件</div>
      <ul className="mt-3 space-y-2">
        {files.map((file) => (
          <li key={`${file.name}-${file.size}`} className="flex items-center justify-between gap-4 rounded-xl bg-white px-3 py-2">
            <span>{file.name}</span>
            <span>{Math.round(file.size / 1024)} KB</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function InlineMessage({ message, tone = 'neutral' }: { message: string; tone?: 'neutral' | 'error' | 'success' | 'warning' }) {
  return (
    <div
      className={toClassNames(
        'rounded-2xl border px-4 py-3 text-sm',
        tone === 'error' && 'border-red-200 bg-red-50 text-red-700',
        tone === 'success' && 'border-sage-100 bg-sage-50 text-sage-400',
        tone === 'warning' && 'border-gold-200 bg-gold-50 text-amber-800',
        tone === 'neutral' && 'border-ink-900/10 bg-white/80 text-ink-700',
      )}
    >
      {message}
    </div>
  )
}

function candidateToDraft(candidate: BatchSplitCandidate): BatchCandidateUpdatePayload {
  return {
    id: candidate.id,
    candidate_index: candidate.candidate_index,
    start_page: candidate.start_page,
    end_page: candidate.end_page,
    student_name: candidate.student_name,
    student_id: candidate.student_id,
    review_notes: candidate.review_notes,
    confirmed: candidate.confirmed,
  }
}

function validateCandidateDrafts(candidates: BatchCandidateUpdatePayload[], totalPages: number | null): string | null {
  const ranges = [...candidates].sort((left, right) => left.start_page - right.start_page)
  for (const candidate of ranges) {
    if (candidate.start_page < 1 || candidate.end_page < candidate.start_page) {
      return '候选页段不合法。'
    }
    if (totalPages !== null && candidate.end_page > totalPages) {
      return '候选页段超过批次总页数。'
    }
  }
  for (let index = 1; index < ranges.length; index += 1) {
    if (ranges[index].start_page <= ranges[index - 1].end_page) {
      return '候选页段不能重叠。'
    }
  }
  return null
}

function isBatchActive(status: BatchStatus): boolean {
  return ['uploaded', 'splitting', 'materializing', 'grading'].includes(status)
}

function formatBatchMode(mode: BatchUploadMode): string {
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

function formatBatchStatus(status: BatchStatus): string {
  switch (status) {
    case 'uploaded':
      return '已上传'
    case 'splitting':
      return '拆分中'
    case 'needs_split_review':
      return '需确认拆分'
    case 'split_ready':
      return '拆分可确认'
    case 'materializing':
      return '生成答卷中'
    case 'ready_for_grading':
      return '可批改'
    case 'grading':
      return '批改中'
    case 'completed':
      return '已完成'
    case 'completed_with_errors':
      return '部分完成'
    case 'failed':
      return '失败'
    default:
      return status
  }
}
