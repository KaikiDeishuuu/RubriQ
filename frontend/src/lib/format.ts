import type { ConfidenceLevel, SubmissionStatus } from './types'

const currencyFormatter = new Intl.NumberFormat('zh-CN', {
  maximumFractionDigits: 2,
  minimumFractionDigits: 0,
})

export function formatScore(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') {
    return '0'
  }
  const numericValue = typeof value === 'number' ? value : Number(value)
  if (Number.isNaN(numericValue)) {
    return String(value)
  }
  return currencyFormatter.format(numericValue)
}

export function formatStatus(status: SubmissionStatus): string {
  switch (status) {
    case 'uploaded':
      return '已上传'
    case 'processing':
      return '处理中'
    case 'graded':
      return '已评分'
    case 'needs_review':
      return '待人工复核'
    case 'failed':
      return '处理失败'
    default:
      return status
  }
}

export function statusTone(status: SubmissionStatus): string {
  switch (status) {
    case 'graded':
      return 'bg-sage-100 text-sage-400 ring-sage-200'
    case 'needs_review':
      return 'bg-gold-50 text-amber-800 ring-gold-200'
    case 'processing':
      return 'bg-slateBlue-50 text-slateBlue-500 ring-slateBlue-100'
    case 'failed':
      return 'bg-red-50 text-red-700 ring-red-200'
    case 'uploaded':
      return 'bg-paper text-ink-700 ring-ink-900/10'
    default:
      return 'bg-paper text-ink-700 ring-ink-900/10'
  }
}

export function formatConfidence(confidence: ConfidenceLevel): string {
  switch (confidence) {
    case 'high':
      return '高'
    case 'medium':
      return '中'
    case 'low':
      return '低'
    default:
      return confidence
  }
}

export function confidenceTone(confidence: ConfidenceLevel): string {
  switch (confidence) {
    case 'high':
      return 'bg-sage-100 text-sage-400 ring-sage-200'
    case 'medium':
      return 'bg-gold-50 text-amber-800 ring-gold-200'
    case 'low':
      return 'bg-red-50 text-red-700 ring-red-200'
    default:
      return 'bg-paper text-ink-700 ring-ink-900/10'
  }
}

export function toClassNames(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ')
}
