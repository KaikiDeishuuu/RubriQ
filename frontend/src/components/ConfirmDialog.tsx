import { toClassNames } from '../lib/format'

interface ConfirmDialogProps {
  open: boolean
  title: string
  message: string
  confirmLabel?: string
  tone?: 'danger' | 'neutral'
  loading?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = '确认',
  tone = 'neutral',
  loading = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-ink-950/40 backdrop-blur-sm" onClick={loading ? undefined : onCancel} />
      <div className="relative mx-4 w-full max-w-md rounded-3xl border border-ink-900/10 bg-white p-6 shadow-lift">
        <h3 className="font-display text-xl text-ink-950">{title}</h3>
        <p className="mt-3 text-sm leading-6 text-ink-700">{message}</p>
        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={loading}
            className="rounded-full border border-ink-900/10 bg-white px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-paper disabled:opacity-50"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={loading}
            className={toClassNames(
              'rounded-full px-4 py-2 text-sm font-semibold text-white transition disabled:opacity-50',
              tone === 'danger'
                ? 'bg-red-600 hover:bg-red-700'
                : 'bg-ink-950 hover:bg-ink-800',
            )}
          >
            {loading ? '处理中...' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
