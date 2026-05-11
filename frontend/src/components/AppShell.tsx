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
    <div className="min-h-dvh text-ink-950" style={{ backgroundImage: 'var(--page-texture)' }}>
      <div className="flex min-h-dvh w-full flex-col lg:flex-row">
        <aside className="relative overflow-hidden border-b border-ink-900/10 bg-ink-950 px-5 py-5 text-paper lg:sticky lg:top-0 lg:h-dvh lg:w-[18rem] lg:shrink-0 lg:border-b-0 lg:border-r lg:px-5 lg:py-5 xl:w-[19rem]">
          <div className="pointer-events-none absolute -left-24 -top-24 h-52 w-52 rounded-full bg-slateBlue-400/20 blur-3xl" />
          <div className="pointer-events-none absolute -bottom-20 right-0 h-44 w-44 rounded-full bg-gold-200/10 blur-3xl" />
          <div className="sidebar-scrollbar relative flex h-full min-h-0 flex-col gap-4 overflow-y-auto overscroll-contain">
            <div className="rounded-[1.75rem] border border-white/10 bg-white/[0.04] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
              <div className="inline-flex items-center rounded-full border border-gold-200/30 bg-white/5 px-2.5 py-1 text-[10px] uppercase tracking-[0.26em] text-gold-100">
                Studio
              </div>
              <h1 className="mt-3 font-display text-3xl leading-none text-white xl:text-[2.1rem]">
                RubriQ <span className="text-gold-100">·</span> Studio
              </h1>
              <p className="mt-2 text-[11px] uppercase tracking-[0.2em] text-slate-400">
                OCR rubric workspace
              </p>
              <p className="mt-3 text-sm leading-5 text-slate-300">
                面向手写与中英混合试卷的 AI 评分、复核与导出工作台。
              </p>
            </div>
            <nav className="space-y-2 rounded-[1.6rem] border border-white/10 bg-white/[0.04] p-2 backdrop-blur">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === '/exams'}
                  className={({ isActive }) =>
                    toClassNames(
                      'block rounded-2xl px-3.5 py-2.5 text-sm font-semibold transition',
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
            <div className="rounded-[1.6rem] border border-white/10 bg-white/[0.04] p-3 text-xs leading-5 text-slate-300">
              <p className="font-semibold text-white">推荐流程</p>
              <ol className="mt-2 list-decimal space-y-0.5 pl-4">
                <li>创建考试</li>
                <li>确认评分标准</li>
                <li>确认考试名单</li>
                <li>上传并拆分答卷</li>
                <li>批改、复核、导出</li>
              </ol>
            </div>
            <div className="mt-auto rounded-[1.6rem] border border-white/10 bg-white/[0.04] p-3 text-xs leading-5 text-slate-300">
              <p className="font-semibold text-white">人工复核优先</p>
              <p className="mt-1.5">
                分数保留 rubric 证据与教师改分痕迹，扣分摘要可编辑后导出。
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
        <main className="min-w-0 flex-1 px-4 py-4 sm:px-6 lg:px-8 lg:py-8">
          <div className="mx-auto max-w-[1360px] rounded-[2rem] border border-ink-900/10 bg-white/70 p-4 shadow-soft backdrop-blur sm:p-6 lg:p-8">
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
