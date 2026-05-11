import type { BadCase, BadCaseRouteKey, BadCaseStatus } from './types'

export interface BadCaseFilters {
  route_key?: BadCaseRouteKey | ''
  status?: BadCaseStatus | ''
  search?: string
  page?: number
  page_size?: number
}

export function badCaseKey(imageStoragePath: string, routeKey: BadCaseRouteKey): string {
  return `${routeKey}::${imageStoragePath}`
}

export function formatBadCaseRoute(routeKey: BadCaseRouteKey): string {
  switch (routeKey) {
    case 'vision_split_header':
      return '拆分页眉'
    case 'vision_student_extraction':
      return '学生答题识别'
    case 'vision_rubric':
      return '评分标准识别'
    case 'vision_roster':
      return '名单识别'
    default:
      return routeKey
  }
}

export function formatBadCaseStatus(status: BadCaseStatus): string {
  switch (status) {
    case 'pending':
      return '待处理'
    case 'triaged':
      return '已分拣'
    case 'ready':
      return '可导出'
    case 'exported':
      return '已导出'
    case 'discarded':
      return '已丢弃'
    default:
      return status
  }
}

export function badCaseStatusTone(status: BadCaseStatus): string {
  switch (status) {
    case 'ready':
      return 'bg-sage-100 text-sage-400 ring-sage-200'
    case 'triaged':
      return 'bg-slateBlue-50 text-slateBlue-500 ring-slateBlue-100'
    case 'exported':
      return 'bg-paper text-ink-700 ring-ink-900/10'
    case 'discarded':
      return 'bg-red-50 text-red-700 ring-red-200'
    case 'pending':
    default:
      return 'bg-gold-50 text-amber-800 ring-gold-200'
  }
}

export function isBadCaseExportable(caseItem: Pick<BadCase, 'status' | 'ground_truth_text'>): boolean {
  return caseItem.status === 'ready' && Boolean(caseItem.ground_truth_text?.trim())
}

export function renderedExamFilePagePath(examId: number, kind: 'rubric' | 'roster', fileId: number, pageNo: number): string {
  return `rendered/exams/${examId}/${kind}/${fileId}/page-${String(pageNo).padStart(3, '0')}.png`
}

export function buildBadCaseQuery(filters: BadCaseFilters): string {
  const params = new URLSearchParams()
  if (filters.route_key) params.set('route_key', filters.route_key)
  if (filters.status) params.set('status', filters.status)
  if (filters.search?.trim()) params.set('search', filters.search.trim())
  if (filters.page !== undefined) params.set('page', String(filters.page))
  if (filters.page_size !== undefined) params.set('page_size', String(filters.page_size))
  const text = params.toString()
  return text ? `?${text}` : ''
}
