import type { ReactNode } from 'react'

import { toClassNames } from '../lib/format'

interface SectionCardProps {
  title: string
  description?: string
  action?: ReactNode
  children: ReactNode
  className?: string
}

export function SectionCard({ title, description, action, children, className }: SectionCardProps) {
  return (
    <section className={toClassNames('rounded-3xl border border-ink-900/10 bg-parchment/95 p-5 shadow-soft backdrop-blur', className)}>
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-2xl leading-none text-ink-950">{title}</h2>
          {description ? <p className="mt-2 text-sm text-ink-700">{description}</p> : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      {children}
    </section>
  )
}
