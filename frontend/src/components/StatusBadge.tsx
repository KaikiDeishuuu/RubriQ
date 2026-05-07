import { formatStatus, statusTone } from '../lib/format'
import type { SubmissionStatus } from '../lib/types'

interface StatusBadgeProps {
  status: SubmissionStatus
}

export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset ${statusTone(status)}`}>
      {formatStatus(status)}
    </span>
  )
}
