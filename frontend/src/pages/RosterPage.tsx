import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { DropZone } from '../components/DropZone'
import { SectionCard } from '../components/SectionCard'
import {
  confirmRoster,
  deleteRoster,
  getRoster,
  parseRoster,
  putRoster,
  uploadRoster,
} from '../lib/api'
import { toClassNames } from '../lib/format'
import type { RosterDetail, RosterEntry, RosterStatus } from '../lib/types'

interface DraftEntry {
  student_name: string
  student_id: string
}

const STATUS_LABEL: Record<RosterStatus, string> = {
  not_uploaded: '未上传',
  parsing: 'AI 解析中',
  needs_review: '待确认',
  confirmed: '已确认',
}

const STATUS_TONE: Record<RosterStatus, string> = {
  not_uploaded: 'bg-paper text-ink-700 ring-ink-900/10',
  parsing: 'bg-slateBlue-50 text-slateBlue-500 ring-slateBlue-100',
  needs_review: 'bg-gold-50 text-amber-800 ring-gold-200',
  confirmed: 'bg-sage-100 text-sage-400 ring-sage-200',
}

export function RosterPage() {
  const { examId } = useParams()
  const numericExamId = Number(examId)

  const [roster, setRoster] = useState<RosterDetail | null>(null)
  const [drafts, setDrafts] = useState<DraftEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)

  useEffect(() => {
    void loadRoster()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [numericExamId])

  useEffect(() => {
    if (roster) {
      setDrafts(rosterToDrafts(roster.entries))
    }
  }, [roster?.entries])

  async function loadRoster() {
    if (!Number.isFinite(numericExamId)) {
      setError('考试 ID 无效')
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const detail = await getRoster(numericExamId)
      setRoster(detail)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载名单失败')
    } finally {
      setLoading(false)
    }
  }

  async function handleUpload(files: File[], sourceKind: 'pdf' | 'csv' | 'xlsx') {
    const file = files[0]
    if (!file || !Number.isFinite(numericExamId)) {
      return
    }
    setBusy(true)
    setError(null)
    setFeedback(null)
    try {
      await uploadRoster(numericExamId, file, sourceKind)
      if (sourceKind === 'pdf') {
        setFeedback('PDF 已上传，开始 AI 解析...')
        await parseRoster(numericExamId)
      } else {
        setFeedback('表格已上传并解析。')
      }
      await loadRoster()
    } catch (err) {
      setError(err instanceof Error ? err.message : '上传名单失败')
    } finally {
      setBusy(false)
    }
  }

  async function handleSaveDrafts() {
    if (!Number.isFinite(numericExamId)) {
      return
    }
    setBusy(true)
    setError(null)
    setFeedback(null)
    try {
      const entries = drafts
        .map((draft) => ({
          student_name: draft.student_name.trim() || null,
          student_id: draft.student_id.trim() || null,
        }))
        .filter((entry) => entry.student_name || entry.student_id)
      await putRoster(numericExamId, { entries, source: 'manual' })
      setFeedback('名单已保存。')
      await loadRoster()
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存名单失败')
    } finally {
      setBusy(false)
    }
  }

  async function handleConfirm() {
    if (!Number.isFinite(numericExamId)) {
      return
    }
    setBusy(true)
    setError(null)
    setFeedback(null)
    try {
      await confirmRoster(numericExamId)
      setFeedback('名单已确认，可以用于拆分绑定。')
      await loadRoster()
    } catch (err) {
      setError(err instanceof Error ? err.message : '确认名单失败')
    } finally {
      setBusy(false)
    }
  }

  async function handleClear() {
    if (!Number.isFinite(numericExamId) || !window.confirm('确定要清空当前名单吗？')) {
      return
    }
    setBusy(true)
    setError(null)
    setFeedback(null)
    try {
      await deleteRoster(numericExamId)
      setFeedback('名单已清空。')
      await loadRoster()
    } catch (err) {
      setError(err instanceof Error ? err.message : '清空名单失败')
    } finally {
      setBusy(false)
    }
  }

  function updateDraft(index: number, patch: Partial<DraftEntry>) {
    setDrafts((current) => current.map((draft, idx) => (idx === index ? { ...draft, ...patch } : draft)))
  }

  function addDraft() {
    setDrafts((current) => [...current, { student_name: '', student_id: '' }])
  }

  function removeDraft(index: number) {
    setDrafts((current) => current.filter((_, idx) => idx !== index))
  }

  const status = roster?.roster_status ?? 'not_uploaded'
  const dirty = useMemo(() => roster ? !areDraftsEqual(drafts, rosterToDrafts(roster.entries)) : false, [drafts, roster])
  const filledDraftCount = drafts.filter((draft) => draft.student_name.trim() || draft.student_id.trim()).length

  return (
    <div className="space-y-6">
      <SectionCard
        title="考试名单"
        description="上传后名单可用于拆分预览自动绑定与身份交叉校验，建议在上传学生答卷前先确认名单。"
        action={
          <Link
            to={Number.isFinite(numericExamId) ? `/exams/${numericExamId}/rubric` : '/exams'}
            className="rounded-full border border-ink-900/10 bg-white px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-paper"
          >
            返回评分标准
          </Link>
        }
      >
        <div className="flex flex-wrap items-center gap-3 text-sm text-ink-700">
          <span className="text-ink-700">状态：</span>
          <span className={toClassNames('rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset', STATUS_TONE[status])}>
            {STATUS_LABEL[status]}
          </span>
          <span>条目数：{roster?.entries.length ?? 0}</span>
          {roster?.roster_error_message ? (
            <span className="rounded-full bg-red-50 px-3 py-1 text-xs font-semibold text-red-700 ring-1 ring-inset ring-red-200">
              {roster.roster_error_message}
            </span>
          ) : null}
        </div>
      </SectionCard>

      {loading ? <InlineMessage message="正在加载名单..." /> : null}
      {error ? <InlineMessage message={error} tone="error" /> : null}
      {feedback ? <InlineMessage message={feedback} tone="success" /> : null}

      <div className="grid gap-6 xl:grid-cols-2">
        <SectionCard title="PDF 名单（视觉解析）" description="上传 PDF 后将调用视觉模型自动提取学生姓名与学号。">
          <DropZone
            title="拖拽名单 PDF"
            description="上传后自动触发解析，结果会出现在右侧表格中等待确认。"
            accept=".pdf"
            onFilesSelected={(files) => void handleUpload(files, 'pdf')}
          />
        </SectionCard>

        <SectionCard title="CSV / Excel 名单" description="支持 .csv / .xlsx 文件，需要包含「姓名」「学号」列（中英文都识别）。">
          <DropZone
            title="拖拽 CSV 或 Excel"
            description="上传后系统会直接解析表格行。"
            accept=".csv,.xlsx,.xlsm"
            onFilesSelected={(files) => {
              const file = files[0]
              if (!file) {
                return
              }
              const lower = file.name.toLowerCase()
              const kind: 'csv' | 'xlsx' = lower.endsWith('.csv') ? 'csv' : 'xlsx'
              void handleUpload(files, kind)
            }}
          />
        </SectionCard>
      </div>

      <SectionCard
        title="编辑名单"
        description="可以直接修改/增删行；保存后状态会回到「待确认」，确认后才会生效用于拆分。"
        action={
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={addDraft}
              className="rounded-full border border-ink-900/10 bg-white px-3 py-2 text-xs font-semibold text-ink-950 transition hover:bg-paper"
            >
              新增一行
            </button>
            <button
              type="button"
              onClick={() => void handleClear()}
              disabled={busy || !roster?.entries.length}
              className="rounded-full border border-red-200 bg-white px-3 py-2 text-xs font-semibold text-red-700 transition hover:bg-red-50 disabled:opacity-50"
            >
              清空名单
            </button>
          </div>
        }
      >
        {drafts.length === 0 ? (
          <InlineMessage message="尚未导入或新增任何名单条目。" />
        ) : (
          <div className="overflow-hidden rounded-2xl border border-ink-900/10 bg-white">
            <table className="min-w-full divide-y divide-ink-900/10 text-sm">
              <thead className="bg-paper text-left text-[11px] uppercase tracking-[0.2em] text-ink-700">
                <tr>
                  <th className="w-16 px-4 py-3">序号</th>
                  <th className="px-4 py-3">姓名</th>
                  <th className="px-4 py-3">学号</th>
                  <th className="w-24 px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-900/10">
                {drafts.map((draft, index) => (
                  <tr key={index} className="align-middle">
                    <td className="px-4 py-2 text-ink-700">{index + 1}</td>
                    <td className="px-4 py-2">
                      <input
                        value={draft.student_name}
                        onChange={(event) => updateDraft(index, { student_name: event.target.value })}
                        className="h-10 w-full rounded-xl border border-ink-900/10 bg-white px-3 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
                      />
                    </td>
                    <td className="px-4 py-2">
                      <input
                        value={draft.student_id}
                        onChange={(event) => updateDraft(index, { student_id: event.target.value })}
                        className="h-10 w-full rounded-xl border border-ink-900/10 bg-white px-3 outline-none transition focus:border-slateBlue-300 focus:ring-2 focus:ring-slateBlue-100"
                      />
                    </td>
                    <td className="px-4 py-2">
                      <button
                        type="button"
                        onClick={() => removeDraft(index)}
                        className="rounded-full border border-ink-900/10 bg-white px-3 py-1 text-xs font-semibold text-red-700 transition hover:bg-red-50"
                      >
                        删除
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="mt-4 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => void handleSaveDrafts()}
            disabled={busy || !dirty || filledDraftCount === 0}
            className="rounded-full border border-ink-900/10 bg-white px-5 py-3 text-sm font-semibold text-ink-950 transition hover:bg-paper disabled:opacity-50"
          >
            保存名单
          </button>
          <button
            type="button"
            onClick={() => void handleConfirm()}
            disabled={busy || dirty || (roster?.entries.length ?? 0) === 0 || status === 'confirmed'}
            className="rounded-full bg-ink-950 px-5 py-3 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:opacity-50"
          >
            {status === 'confirmed' ? '名单已确认' : '确认名单'}
          </button>
          {dirty ? <InlineMessage message="编辑尚未保存。" tone="warning" /> : null}
        </div>
      </SectionCard>
    </div>
  )
}

function rosterToDrafts(entries: RosterEntry[]): DraftEntry[] {
  return entries.map((entry) => ({
    student_name: entry.student_name ?? '',
    student_id: entry.student_id ?? '',
  }))
}

function areDraftsEqual(a: DraftEntry[], b: DraftEntry[]): boolean {
  if (a.length !== b.length) {
    return false
  }
  for (let i = 0; i < a.length; i += 1) {
    if (a[i].student_name !== b[i].student_name || a[i].student_id !== b[i].student_id) {
      return false
    }
  }
  return true
}

function InlineMessage({ message, tone = 'info' }: { message: string; tone?: 'info' | 'error' | 'warning' | 'success' }) {
  const palette =
    tone === 'error'
      ? 'border-red-200 bg-red-50 text-red-700'
      : tone === 'warning'
        ? 'border-amber-200 bg-amber-50 text-amber-900'
        : tone === 'success'
          ? 'border-sage-200 bg-sage-50 text-sage-500'
          : 'border-ink-900/10 bg-paper text-ink-700'
  return <div className={toClassNames('rounded-2xl border px-4 py-3 text-sm', palette)}>{message}</div>
}
