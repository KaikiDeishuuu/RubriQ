import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { DropZone } from '../components/DropZone'
import { SectionCard } from '../components/SectionCard'
import { StatusBadge } from '../components/StatusBadge'
import {
  getResults,
  processSubmission,
  uploadSubmissions,
} from '../lib/api'
import { formatScore, toClassNames } from '../lib/format'
import type { ExamResultsResponse } from '../lib/types'

export function SubmissionUploadPage() {
  const { examId } = useParams()
  const numericExamId = Number(examId)
  const [results, setResults] = useState<ExamResultsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [studentName, setStudentName] = useState('')
  const [studentId, setStudentId] = useState('')
  const [uploading, setUploading] = useState(false)
  const [processingIds, set开始处理ingIds] = useState<number[]>([])

  useEffect(() => {
    void loadResults()
  }, [numericExamId])

  useEffect(() => {
    if (!results?.rows.some((row) => row.status === 'processing')) {
      return
    }
    const timerId = window.setInterval(() => {
      void loadResults()
    }, 3000)
    return () => window.clearInterval(timerId)
  }, [results])

  async function loadResults() {
    if (!Number.isFinite(numericExamId)) {
      setError('考试 ID 无效')
      setLoading(false)
      return
    }
    try {
      setLoading(true)
      setError(null)
      const data = await getResults(numericExamId)
      setResults(data)
    } catch (error) {
      setError(error instanceof Error ? error.message : '加载学生答卷失败')
    } finally {
      setLoading(false)
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

  async function handle开始处理(submissionId: number) {
    set开始处理ingIds((current) => [...current, submissionId])
    try {
      await processSubmission(submissionId)
      await loadResults()
    } catch (error) {
      setError(error instanceof Error ? error.message : '启动处理失败')
    } finally {
      set开始处理ingIds((current) => current.filter((id) => id !== submissionId))
    }
  }

  const exam = results?.exam

  return (
    <div className="space-y-6">
      <SectionCard
        title={exam ? `${exam.title}的学生答卷` : '上传学生答卷'}
        description="上传一份或多份学生 PDF，启动批改任务，并在同一页面查看处理状态。"
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
          <div className="rounded-2xl border border-ink-900/10 bg-paper p-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-ink-700">考试</div>
            <div className="mt-2 font-display text-2xl text-ink-950">{exam?.title ?? '未知'}</div>
          </div>
          <div className="rounded-2xl border border-ink-900/10 bg-paper p-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-ink-700">总分</div>
            <div className="mt-2 font-display text-2xl text-ink-950">{formatScore(exam?.total_score ?? 0)}</div>
          </div>
          <div className="rounded-2xl border border-ink-900/10 bg-paper p-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-ink-700">评分标准状态</div>
            <div className="mt-2 text-sm font-semibold text-ink-950">
              {exam?.needs_rubric_review ? '需要老师确认' : '已确认'}
            </div>
          </div>
        </div>
      </SectionCard>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <SectionCard title="上传答卷" description="将学生 PDF 拖到面板中，或手动选择文件。">
          <div className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <label className="block space-y-2">
                <span className="text-sm font-semibold text-ink-800">学生姓名（可选）</span>
                <input
                  value={studentName}
                  onChange={(event) => setStudentName(event.target.value)}
                  className="w-full rounded-2xl border border-ink-900/10 bg-white px-4 py-3 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
                  placeholder="可作为默认提示，AI 也会尝试识别"
                />
              </label>
              <label className="block space-y-2">
                <span className="text-sm font-semibold text-ink-800">学号（可选）</span>
                <input
                  value={studentId}
                  onChange={(event) => setStudentId(event.target.value)}
                  className="w-full rounded-2xl border border-ink-900/10 bg-white px-4 py-3 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
                  placeholder="可作为默认提示，AI 也会尝试识别"
                />
              </label>
            </div>
            <DropZone
              title="拖拽学生 PDF 到这里"
              description="每个 PDF 会生成一份学生答卷，AI 会识别学生信息和每题答案。"
              multiple
              onFilesSelected={setFiles}
            />
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={handleUpload}
                disabled={files.length === 0 || uploading}
                className="rounded-full bg-ink-950 px-5 py-3 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {uploading ? '正在上传...' : '上传答卷'}
              </button>
              <button
                type="button"
                onClick={() => setFiles([])}
                className="rounded-full border border-ink-900/10 bg-white px-5 py-3 text-sm font-semibold text-ink-950 transition hover:bg-paper"
              >
                清空选择
              </button>
            </div>
            {files.length > 0 ? (
              <div className="rounded-2xl border border-ink-900/10 bg-paper p-4 text-sm text-ink-700">
                <div className="font-semibold text-ink-950">已选择文件</div>
                <ul className="mt-3 space-y-2">
                  {files.map((file) => (
                    <li key={file.name} className="flex items-center justify-between gap-4 rounded-xl bg-white px-3 py-2">
                      <span>{file.name}</span>
                      <span>{Math.round(file.size / 1024)} KB</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </SectionCard>

        <SectionCard title="学生答卷列表" description="可以单独处理每份答卷，并查看当前批改状态。">
          {loading ? <InlineMessage message="正在加载批量结果..." /> : null}
          {error ? <InlineMessage message={error} tone="error" /> : null}
          {results?.rows.some((row) => row.status === 'processing' || processingIds.includes(row.submission_id)) ? (
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
                            onClick={() => handle开始处理(row.submission_id)}
                            disabled={processingIds.includes(row.submission_id) || row.status === 'processing'}
                            className="rounded-full border border-slateBlue-200 bg-slateBlue-50 px-3 py-2 text-xs font-semibold text-slateBlue-500 transition hover:bg-slateBlue-100 disabled:opacity-50"
                          >
                            {processingIds.includes(row.submission_id) || row.status === 'processing' ? '处理中...' : '开始处理'}
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
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-white text-xs font-bold text-slateBlue-500 ring-1 ring-inset ring-slateBlue-100">
              {index + 1}
            </span>
            <span>{step}</span>
          </div>
        ))}
      </div>
      <div className="mt-3 text-xs text-ink-700">页面会每 3 秒自动刷新，处理完成后会显示姓名、学号、分数和复核入口。</div>
    </div>
  )
}

function InlineMessage({ message, tone = 'neutral' }: { message: string; tone?: 'neutral' | 'error' }) {
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
