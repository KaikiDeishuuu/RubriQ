import React, { useEffect, useRef, useState } from 'react'

import { BadCaseDrawer } from '../components/BadCaseDrawer'
import { SectionCard } from '../components/SectionCard'
import {
  badCaseStatusTone,
  formatBadCaseRoute,
  formatBadCaseStatus,
  isBadCaseExportable,
  type BadCaseFilters,
} from '../lib/badcases'
import {
  downloadBlob,
  exportBadCasesZip,
  getBadCaseStats,
  listBadCases,
  previewBadCaseRedaction,
  updateBadCase,
} from '../lib/api'
import { toClassNames } from '../lib/format'
import type { BadCase, BadCaseRedactionPreview, BadCaseRouteKey, BadCaseStatsItem, BadCaseStatus } from '../lib/types'

const routeOptions: Array<{ value: BadCaseRouteKey | ''; label: string }> = [
  { value: '', label: '全部流程' },
  { value: 'vision_split_header', label: formatBadCaseRoute('vision_split_header') },
  { value: 'vision_student_extraction', label: formatBadCaseRoute('vision_student_extraction') },
  { value: 'vision_rubric', label: formatBadCaseRoute('vision_rubric') },
  { value: 'vision_roster', label: formatBadCaseRoute('vision_roster') },
]

const statusOptions: Array<{ value: BadCaseStatus | ''; label: string }> = [
  { value: '', label: '全部状态' },
  { value: 'pending', label: formatBadCaseStatus('pending') },
  { value: 'triaged', label: formatBadCaseStatus('triaged') },
  { value: 'ready', label: formatBadCaseStatus('ready') },
  { value: 'exported', label: formatBadCaseStatus('exported') },
  { value: 'discarded', label: formatBadCaseStatus('discarded') },
]

interface BadCasesPageViewProps {
  cases: BadCase[]
  stats: BadCaseStatsItem[]
  total: number
  page: number
  pageSize: number
  loading: boolean
  error: string | null
  filters: BadCaseFilters
  exporting: boolean
  onFiltersChange: (filters: BadCaseFilters) => void
  onSelectCase: (caseItem: BadCase) => void
  onExport: () => void
  onRefresh: () => void
}

export function BadCasesPage() {
  const [cases, setCases] = useState<BadCase[]>([])
  const [stats, setStats] = useState<BadCaseStatsItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [filters, setFilters] = useState<BadCaseFilters>({ route_key: '', status: '', search: '', page: 1, page_size: 20 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedCase, setSelectedCase] = useState<BadCase | null>(null)
  const [saving, setSaving] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [preview, setPreview] = useState<BadCaseRedactionPreview | null>(null)
  const [exporting, setExporting] = useState(false)
  const requestIdRef = useRef(0)

  useEffect(() => {
    void loadCases(filters)
  }, [filters.route_key, filters.status, filters.search, filters.page, filters.page_size])

  async function loadCases(activeFilters: BadCaseFilters = filters) {
    const requestId = requestIdRef.current + 1
    requestIdRef.current = requestId
    try {
      setLoading(true)
      setError(null)
      const [listResponse, statsResponse] = await Promise.all([listBadCases(activeFilters), getBadCaseStats()])
      if (requestId !== requestIdRef.current) {
        return
      }
      setCases(listResponse.items)
      setTotal(listResponse.total)
      setPage(listResponse.page)
      setPageSize(listResponse.page_size)
      setStats(statsResponse)
      if (selectedCase) {
        setSelectedCase(listResponse.items.find((item) => item.id === selectedCase.id) ?? selectedCase)
      }
    } catch (error) {
      if (requestId === requestIdRef.current) {
        setError(error instanceof Error ? error.message : '加载 Bad Case 失败')
      }
    } finally {
      if (requestId === requestIdRef.current) {
        setLoading(false)
      }
    }
  }

  function handleFiltersChange(nextFilters: BadCaseFilters) {
    setFilters((current) => ({ ...current, ...nextFilters }))
  }

  async function handleSave(payload: { ground_truth_text: string | null; status: BadCaseStatus; redact_pii: boolean; reporter_note: string | null }) {
    if (!selectedCase) {
      return
    }
    setSaving(true)
    try {
      const updated = await updateBadCase(selectedCase.id, payload)
      setSelectedCase(updated)
      setCases((current) => current.map((item) => (item.id === updated.id ? updated : item)))
      setError(null)
      void loadCases()
    } catch (error) {
      setError(error instanceof Error ? error.message : '保存 Bad Case 失败')
    } finally {
      setSaving(false)
    }
  }

  async function handlePreview() {
    if (!selectedCase) {
      return
    }
    setPreviewing(true)
    try {
      setPreview(await previewBadCaseRedaction(selectedCase.id))
      setError(null)
    } catch (error) {
      setError(error instanceof Error ? error.message : '生成脱敏预览失败')
    } finally {
      setPreviewing(false)
    }
  }

  async function handleExport() {
    setExporting(true)
    try {
      const blob = await exportBadCasesZip({ route_key: filters.route_key || undefined })
      await downloadBlob(blob, `paddleocr-badcases-${new Date().toISOString().slice(0, 10)}.zip`)
      await loadCases()
    } catch (error) {
      setError(error instanceof Error ? error.message : '导出 Bad Case 失败')
    } finally {
      setExporting(false)
    }
  }

  function handleSelectCase(caseItem: BadCase) {
    setSelectedCase(caseItem)
    setPreview(null)
  }

  return (
    <>
      <BadCasesPageView
        cases={cases}
        stats={stats}
        total={total}
        page={page}
        pageSize={pageSize}
        loading={loading}
        error={error}
        filters={filters}
        exporting={exporting}
        onFiltersChange={handleFiltersChange}
        onSelectCase={handleSelectCase}
        onExport={() => void handleExport()}
        onRefresh={() => void loadCases()}
      />
      <BadCaseDrawer
        caseItem={selectedCase}
        saving={saving}
        previewing={previewing}
        previewStoragePath={preview?.preview_storage_path ?? null}
        previewMethod={preview?.redaction_method ?? null}
        previewFailed={preview?.redaction_failed ?? false}
        onClose={() => setSelectedCase(null)}
        onSave={(payload) => void handleSave(payload)}
        onPreview={() => void handlePreview()}
      />
    </>
  )
}

export function BadCasesPageView({
  cases,
  stats,
  total,
  page,
  pageSize,
  loading,
  error,
  filters,
  exporting,
  onFiltersChange,
  onSelectCase,
  onExport,
  onRefresh,
}: BadCasesPageViewProps) {
  const readyCount = stats.filter((item) => item.status === 'ready').reduce((sum, item) => sum + item.count, 0)
  const pendingCount = stats.filter((item) => item.status === 'pending').reduce((sum, item) => sum + item.count, 0)
  const exportedCount = stats.filter((item) => item.status === 'exported').reduce((sum, item) => sum + item.count, 0)
  const exportableCount = cases.filter(isBadCaseExportable).length
  const pageCount = Math.max(1, Math.ceil(total / pageSize))

  function setFilter(next: BadCaseFilters) {
    onFiltersChange({ ...next, page: next.page ?? 1 })
  }

  return (
    <div className="space-y-6">
      <SectionCard
        title="PaddleOCR Bad Cases"
        description="收集 OCR 失败、低置信度和人工反馈样本，补充 ground truth 后打包导出用于 PaddleOCR 复训。"
        action={
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={onRefresh}
              disabled={loading}
              className="rounded-full border border-ink-900/10 bg-white px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-paper disabled:opacity-50"
            >
              刷新
            </button>
            <button
              type="button"
              onClick={onExport}
              disabled={exporting || readyCount === 0}
              className="rounded-full bg-ink-950 px-4 py-2 text-sm font-semibold text-paper transition hover:bg-ink-800 disabled:opacity-50"
            >
              {exporting ? '正在导出...' : '导出 ZIP'}
            </button>
          </div>
        }
      >
        <div className="grid gap-4 md:grid-cols-5">
          <Metric label="总样本" value={String(total)} />
          <Metric label="待处理" value={String(pendingCount)} />
          <Metric label="可导出" value={String(readyCount)} />
          <Metric label="当前页可导出样本" value={String(exportableCount)} />
          <Metric label="已导出" value={String(exportedCount)} />
        </div>
      </SectionCard>

      <SectionCard title="筛选" description="按识别流程、状态或文本搜索定位样本。">
        <div className="grid gap-3 lg:grid-cols-[220px_180px_minmax(0,1fr)]">
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-700">流程</span>
            <select
              value={filters.route_key ?? ''}
              onChange={(event) => setFilter({ route_key: event.target.value as BadCaseRouteKey | '' })}
              className="mt-2 w-full rounded-2xl border border-ink-900/10 bg-white px-4 py-3 text-sm text-ink-950"
            >
              {routeOptions.map((item) => (
                <option key={item.value || 'all'} value={item.value}>{item.label}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-700">状态</span>
            <select
              value={filters.status ?? ''}
              onChange={(event) => setFilter({ status: event.target.value as BadCaseStatus | '' })}
              className="mt-2 w-full rounded-2xl border border-ink-900/10 bg-white px-4 py-3 text-sm text-ink-950"
            >
              {statusOptions.map((item) => (
                <option key={item.value || 'all'} value={item.value}>{item.label}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-700">搜索</span>
            <input
              value={filters.search ?? ''}
              onChange={(event) => setFilter({ search: event.target.value })}
              className="mt-2 w-full rounded-2xl border border-ink-900/10 bg-white px-4 py-3 text-sm text-ink-950"
              placeholder="搜索 OCR 原文、ground truth 或图片路径"
            />
          </label>
        </div>
      </SectionCard>

      {loading ? <StateMessage message="正在加载 Bad Case..." /> : null}
      {error ? <StateMessage message={error} tone="error" /> : null}

      <section className="overflow-hidden rounded-3xl border border-ink-900/10 bg-white/85 shadow-soft">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-ink-900/10 text-left text-sm">
            <thead className="bg-paper text-xs font-semibold uppercase tracking-[0.16em] text-ink-700">
              <tr>
                <th className="px-4 py-3">ID</th>
                <th className="px-4 py-3">流程</th>
                <th className="px-4 py-3">状态</th>
                <th className="px-4 py-3">触发原因</th>
                <th className="px-4 py-3">图片路径</th>
                <th className="px-4 py-3">Ground truth</th>
                <th className="px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-900/10">
              {cases.map((caseItem) => (
                <tr key={caseItem.id} className="align-top hover:bg-paper/70">
                  <td className="px-4 py-3 font-semibold text-ink-950">#{caseItem.id}</td>
                  <td className="px-4 py-3 text-ink-700">{formatBadCaseRoute(caseItem.route_key)}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset ${badCaseStatusTone(caseItem.status)}`}>
                      {formatBadCaseStatus(caseItem.status)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-ink-700">{caseItem.trigger_reason}</td>
                  <td className="max-w-md px-4 py-3 text-xs text-ink-700">
                    <span className="break-all">{caseItem.image_storage_path}</span>
                  </td>
                  <td className="px-4 py-3 text-ink-700">
                    {caseItem.ground_truth_text?.trim() ? '已填写' : '未填写'}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      onClick={() => onSelectCase(caseItem)}
                      className="rounded-full border border-slateBlue-200 bg-slateBlue-50 px-3 py-1.5 text-xs font-semibold text-slateBlue-500 transition hover:bg-slateBlue-100"
                    >
                      查看详情
                    </button>
                  </td>
                </tr>
              ))}
              {!loading && cases.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-sm text-ink-700">
                    暂无 Bad Case。
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-ink-900/10 bg-paper px-4 py-3 text-sm text-ink-700">
          <span>第 {page} / {pageCount} 页，共 {total} 条</span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => onFiltersChange({ page: Math.max(1, page - 1) })}
              disabled={page <= 1}
              className="rounded-full border border-ink-900/10 bg-white px-3 py-1.5 text-xs font-semibold text-ink-950 disabled:opacity-50"
            >
              上一页
            </button>
            <button
              type="button"
              onClick={() => onFiltersChange({ page: Math.min(pageCount, page + 1) })}
              disabled={page >= pageCount}
              className="rounded-full border border-ink-900/10 bg-white px-3 py-1.5 text-xs font-semibold text-ink-950 disabled:opacity-50"
            >
              下一页
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-ink-900/10 bg-paper px-4 py-3">
      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-700">{label}</div>
      <div className="mt-2 font-display text-3xl text-ink-950">{value}</div>
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
