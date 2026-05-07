import { useEffect, useState } from 'react'

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
  const [lightboxOpen, setLightboxOpen] = useState(false)
  const [zoom, setZoom] = useState(1)

  useEffect(() => {
    if (!lightboxOpen) {
      return
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setLightboxOpen(false)
      }
      if (event.key === 'ArrowLeft') {
        onChange(Math.max(0, activeIndex - 1))
        setZoom(1)
      }
      if (event.key === 'ArrowRight') {
        onChange(Math.min(pages.length - 1, activeIndex + 1))
        setZoom(1)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [activeIndex, lightboxOpen, onChange, pages.length])

  const zoomIn = () => setZoom((current) => Math.min(3, Number((current + 0.25).toFixed(2))))
  const zoomOut = () => setZoom((current) => Math.max(0.5, Number((current - 0.25).toFixed(2))))
  const resetZoom = () => setZoom(1)
  const showPreviousPage = () => {
    onChange(Math.max(0, activeIndex - 1))
    resetZoom()
  }
  const showNextPage = () => {
    onChange(Math.min(pages.length - 1, activeIndex + 1))
    resetZoom()
  }

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
          <button
            type="button"
            onClick={() => {
              resetZoom()
              setLightboxOpen(true)
            }}
            className="overflow-hidden rounded-2xl border border-ink-900/10 bg-parchment text-left transition hover:shadow-lift"
          >
            <img src={activePage.url} alt={activePage.label} className="h-[72vh] w-full object-contain" />
            <div className="border-t border-ink-900/10 bg-white/80 px-4 py-2 text-center text-xs font-semibold text-ink-700">
              点击放大查看
            </div>
          </button>
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
      {lightboxOpen && activePage ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-ink-950/70 backdrop-blur-sm" onClick={() => setLightboxOpen(false)} />
          <div className="relative mx-4 flex h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-3xl border border-white/20 bg-white shadow-lift">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-900/10 px-4 py-3">
              <div>
                <h3 className="font-display text-xl text-ink-950">{activePage.label}</h3>
                <p className="text-xs font-semibold text-ink-700">缩放 {Math.round(zoom * 100)}%</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={zoomOut}
                  className="rounded-full border border-ink-900/10 bg-white px-3 py-2 text-xs font-semibold text-ink-950 transition hover:bg-paper"
                >
                  缩小
                </button>
                <button
                  type="button"
                  onClick={resetZoom}
                  className="rounded-full border border-ink-900/10 bg-white px-3 py-2 text-xs font-semibold text-ink-950 transition hover:bg-paper"
                >
                  重置
                </button>
                <button
                  type="button"
                  onClick={zoomIn}
                  className="rounded-full border border-ink-900/10 bg-white px-3 py-2 text-xs font-semibold text-ink-950 transition hover:bg-paper"
                >
                  放大
                </button>
                <button
                  type="button"
                  onClick={() => setLightboxOpen(false)}
                  className="rounded-full bg-ink-950 px-3 py-2 text-xs font-semibold text-paper transition hover:bg-ink-800"
                >
                  关闭
                </button>
              </div>
            </div>
            <div className="relative min-h-0 flex-1 overflow-auto bg-parchment p-4">
              {pages.length > 1 ? (
                <>
                  <button
                    type="button"
                    onClick={showPreviousPage}
                    disabled={activeIndex === 0}
                    className="absolute left-4 top-1/2 z-10 -translate-y-1/2 rounded-full bg-white/90 px-4 py-3 text-sm font-semibold text-ink-950 shadow-soft transition hover:bg-white disabled:opacity-40"
                  >
                    上一页
                  </button>
                  <button
                    type="button"
                    onClick={showNextPage}
                    disabled={activeIndex === pages.length - 1}
                    className="absolute right-4 top-1/2 z-10 -translate-y-1/2 rounded-full bg-white/90 px-4 py-3 text-sm font-semibold text-ink-950 shadow-soft transition hover:bg-white disabled:opacity-40"
                  >
                    下一页
                  </button>
                </>
              ) : null}
              <div className="flex min-h-full items-start justify-center">
                <img
                  src={activePage.url}
                  alt={activePage.label}
                  className="origin-top rounded-xl shadow-soft transition-transform"
                  style={{ transform: `scale(${zoom})` }}
                />
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  )
}
