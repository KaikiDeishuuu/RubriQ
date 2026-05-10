import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { setAdminToken } from '../lib/api'
import { toClassNames } from '../lib/format'

const navItems = [
  { to: '/exams', label: '考试列表' },
  { to: '/exams/new', label: '新建考试' },
]

export function AppShell() {
  const [showBackToTop, setShowBackToTop] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    function handleScroll() {
      setShowBackToTop(window.scrollY > 480)
    }
    handleScroll()
    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  function scrollToTop() {
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  function handleLogout() {
    setAdminToken(null)
    navigate('/login', { replace: true })
  }

  return (
    <div className="min-h-screen text-ink-950" style={{ backgroundImage: 'var(--page-texture)' }}>
      <div className="mx-auto flex min-h-screen max-w-[1600px] flex-col lg:flex-row">
        <aside className="border-b border-ink-900/10 bg-ink-950 px-6 py-6 text-paper lg:sticky lg:top-0 lg:h-screen lg:w-80 lg:border-b-0 lg:border-r">
          <div className="flex h-full flex-col gap-8 overflow-y-auto">
            <div>
              <div className="inline-flex items-center rounded-full border border-gold-200/30 bg-white/5 px-3 py-1 text-[11px] uppercase tracking-[0.28em] text-gold-100">
                Studio
              </div>
              <h1 className="mt-4 font-display text-4xl leading-none text-white">
                RubriQ <span className="text-gold-100">·</span> Studio
              </h1>
              <p className="mt-2 text-xs uppercase tracking-[0.24em] text-slate-400">
                OCR-powered rubric grading workspace
              </p>
              <p className="mt-4 max-w-sm text-sm leading-6 text-slate-300">
                面向手写与中英混合试卷的 AI 评分平台：rubric 追溯、名单交叉校验、分批批改、复核可审计。
              </p>
            </div>
            <nav className="sticky top-4 z-10 space-y-2 rounded-3xl bg-ink-950/95 py-2 backdrop-blur">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === '/exams'}
                  className={({ isActive }) =>
                    toClassNames(
                      'block rounded-2xl px-4 py-3 text-sm font-semibold transition',
                      isActive
                        ? 'bg-gold-100 text-ink-950 shadow-soft'
                        : 'bg-white/5 text-slate-200 hover:bg-white/10 hover:text-white',
                    )
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-xs leading-6 text-slate-300">
              <p className="font-semibold text-white">推荐流程</p>
              <ol className="mt-2 list-decimal space-y-1 pl-4">
                <li>创建考试</li>
                <li>上传并确认评分标准</li>
                <li>上传并确认考试名单</li>
                <li>上传学生答卷与拆分</li>
                <li>分批批改、复核、导出</li>
              </ol>
            </div>
            <div className="mt-auto rounded-2xl border border-white/10 bg-white/5 p-4 text-sm leading-6 text-slate-300">
              <p className="font-semibold text-white">人工复核优先</p>
              <p className="mt-2">
                每个分数都保留 rubric 证据与教师改分痕迹，扣分摘要可编辑后再导出 PDF。
              </p>
            </div>
            <button
              type="button"
              onClick={handleLogout}
              className="rounded-full border border-white/15 bg-white/5 px-4 py-2 text-xs font-semibold text-slate-200 transition hover:bg-white/10 hover:text-white"
            >
              退出登录
            </button>
          </div>
        </aside>
        <main className="flex-1 px-4 py-4 sm:px-6 lg:px-8 lg:py-8">
          <div className="rounded-[2rem] border border-ink-900/10 bg-white/70 p-4 shadow-soft backdrop-blur sm:p-6 lg:p-8">
            <Outlet />
          </div>
        </main>
      </div>
      <button
        type="button"
        onClick={scrollToTop}
        aria-label="回到顶部"
        className={toClassNames(
          'fixed bottom-6 right-6 z-50 rounded-full border border-ink-900/10 bg-ink-950 px-4 py-3 text-sm font-semibold text-paper shadow-lift transition hover:bg-ink-800 focus:outline-none focus:ring-2 focus:ring-slateBlue-300 focus:ring-offset-2',
          showBackToTop ? 'translate-y-0 opacity-100' : 'pointer-events-none translate-y-3 opacity-0',
        )}
      >
        回到顶部
      </button>
    </div>
  )
}
