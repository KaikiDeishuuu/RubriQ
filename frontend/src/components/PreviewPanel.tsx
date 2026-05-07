import { toClassNames } from '../lib/format'

interface PreviewPanelProps {
  title: string
  description?: string
  pages: Array<{ label: string; url: string }>
  activeIndex: number
  onChange: (index: number) => void
}

export function PreviewPanel({ title, description, pages, activeIndex, onChange }: PreviewPanelProps) {
  const activePage = pages[activeIndex]

  return (
    <section className="rounded-3xl border border-ink-900/10 bg-white/80 p-4 shadow-soft">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h3 className="font-display text-2xl text-ink-950">{title}</h3>
          {description ? <p className="mt-2 text-sm text-ink-700">{description}</p> : null}
        </div>
        <div className="rounded-full bg-ink-950 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-paper">
          共 {pages.length} 页
        </div>
      </div>
      {activePage ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_160px]">
          <div className="overflow-hidden rounded-2xl border border-ink-900/10 bg-parchment">
            <img src={activePage.url} alt={activePage.label} className="h-[72vh] w-full object-contain" />
          </div>
          <div className="space-y-3 overflow-auto pr-1 lg:max-h-[72vh]">
            {pages.map((page, index) => (
              <button
                type="button"
                key={page.label}
                onClick={() => onChange(index)}
                className={toClassNames(
                  'block w-full overflow-hidden rounded-2xl border text-left transition',
                  index === activeIndex
                    ? 'border-slateBlue-400 bg-slateBlue-50 shadow-lift'
                    : 'border-ink-900/10 bg-white/80 hover:-translate-y-0.5 hover:shadow-soft',
                )}
              >
                <img src={page.url} alt={page.label} className="h-28 w-full object-cover" />
                <div className="px-3 py-2 text-xs font-semibold text-ink-700">{page.label}</div>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="rounded-2xl border border-dashed border-ink-900/15 bg-paper px-6 py-16 text-center text-sm text-ink-700">
          暂无预览。
        </div>
      )}
    </section>
  )
}
